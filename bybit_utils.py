#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bybit_utils.py — общие функции для торговых ботов на Bybit.

Включает:
- подключение к API (торговая и публичная сессии),
- загрузку свечей с фильтром выбросов,
- работу с балансом, позицией, плечом,
- расчёт размера позиции (правильная формула без leverage в qty),
- валидацию минимального лота по instrument info,
- выставление и закрытие ордеров.
"""

import os
import math
import logging
from decimal import Decimal, ROUND_DOWN
import time
from datetime import datetime
from pybit.unified_trading import HTTP
from pybit.exceptions import FailedRequestError
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import urllib.request


def _fetch_country(url, timeout=5):
    """Вспомогательный запрос к сервису определения страны."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return None


def get_exit_node_country(timeout=5, max_retries=3, base_delay=2):
    """
    Определяет страну выходного узла (VPN) через ipinfo.io с fallback на ifconfig.co.
    Возвращает 2-буквенный код ("US", "NL", "DE"...) или None при ошибке.
    Делает несколько попыток с паузой, чтобы пережить временные сбои сети.
    Если ipinfo.io показывает US — перепроверяет через fallback (VPN-IP иногда
    ошибочно определяется как US на отдельных сервисах).
    """
    logger = logging.getLogger(__name__)

    # --- Основной источник: ipinfo.io ---
    primary = None
    for attempt in range(1, max_retries + 1):
        primary = _fetch_country("https://ipinfo.io/country", timeout=timeout)
        if primary:
            break
        if attempt < max_retries:
            time.sleep(base_delay * attempt)

    if not primary:
        logger.warning("ipinfo.io не отвечает, пробуем fallback...")

    # --- Fallback: ifconfig.co (ISO-код страны) ---
    fallback = None
    for attempt in range(1, max_retries + 1):
        fallback = _fetch_country("https://ifconfig.co/country-iso", timeout=timeout)
        if fallback:
            break
        if attempt < max_retries:
            time.sleep(base_delay * attempt)

    # --- Логика выбора результата ---
    if primary and fallback:
        primary_up = primary.upper()
        fallback_up = fallback.upper()
        if primary_up == fallback_up:
            logger.debug(f"VPN страна (оба сервиса согласны): {primary_up}")
            return primary_up
        else:
            # Если ipinfo.io говорит US, а fallback нет — доверяем fallback
            if primary_up == "US" and fallback_up != "US":
                logger.warning(
                    f"ipinfo.io показал US, но fallback ({fallback_up}) отличается. "
                    f"Используем fallback. Возможна утечка или ошибка сервиса."
                )
                return fallback_up
            # Наоборот: fallback говорит US, primary нет
            if fallback_up == "US" and primary_up != "US":
                logger.warning(
                    f"fallback показал US, но ipinfo.io ({primary_up}) отличается. "
                    f"Используем ipinfo.io."
                )
                return primary_up
            # Прочие расхождения — доверяем ipinfo.io, но логируем
            logger.warning(
                f"Расхождение VPN-стран: ipinfo.io={primary_up}, fallback={fallback_up}. "
                f"Используем ipinfo.io."
            )
            return primary_up

    if primary:
        logger.debug(f"VPN страна (ipinfo.io): {primary.upper()}")
        return primary.upper()
    if fallback:
        logger.info(f"VPN страна (только fallback): {fallback.upper()}")
        return fallback.upper()

    logger.warning("Не удалось определить страну VPN ни через ipinfo.io, ни через fallback")
    return None


def load_env():
    """Загружает переменные из .env, если файл существует."""
    dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)


def retry_api_call(callable_func, max_retries=3, base_delay=5, no_retry_substrings=None):
    """
    Повторяет callable при 403/429/сетевых ошибках с exponential backoff.
    no_retry_substrings — список строк; если ошибка содержит любую из них,
    retry НЕ делается (сразу пробрасывается).
    """
    logger = logging.getLogger(__name__)
    no_retry_substrings = [s.lower() for s in (no_retry_substrings or [])]
    for attempt in range(1, max_retries + 1):
        try:
            return callable_func()
        except (FailedRequestError, ConnectionError) as e:
            msg = str(e).lower()
            if any(s in msg for s in no_retry_substrings):
                raise
            is_rate_limit = any(x in msg for x in ["403", "429", "rate limit", "ip rate"])
            is_network = any(x in msg for x in ["connection", "reset", "aborted", "timeout"])
            if not (is_rate_limit or is_network) or attempt == max_retries:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(f"API ошибка (попытка {attempt}/{max_retries}): {e}. Povtor cherez {delay}s...")
            time.sleep(delay)
    return None


def setup_logger(name: str, log_file: str):
    """Настраивает логгер с выводом в файл и консоль."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(name)


def get_trade_session(api_key: str, api_secret: str, testnet: bool = True):
    """Создаёт торговую сессию pybit (Testnet или Mainnet)."""
    return HTTP(testnet=testnet, api_key=api_key, api_secret=api_secret)


def get_data_session(testnet: bool = False):
    """Создаёт публичную сессию для рыночных данных (Mainnet по умолчанию)."""
    return HTTP(testnet=testnet)


def fetch_klines(session, symbol: str, interval: str, limit: int = 200, category: str = "linear"):
    """
    Загружает свечи с Bybit и возвращает DataFrame.
    Применяет фильтр выбросов: отбрасывает свечи с ценами вне диапазона
    [median * 0.1, median * 10.0].
    """
    resp = retry_api_call(lambda: session.get_kline(
        category=category,
        symbol=symbol,
        interval=interval,
        limit=limit,
    ))
    if resp["retCode"] != 0:
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка загрузки свечей {interval}: {resp['retMsg']}")
        return None

    data = resp["result"]["list"]
    df = pd.DataFrame(
        data,
        columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"]
    )
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(float), unit="ms")
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Фильтр выбросов
    median_close = df["close"].median()
    lower = median_close * 0.1
    upper = median_close * 10.0
    mask = (
        (df["close"] >= lower) & (df["close"] <= upper) &
        (df["high"] >= lower) & (df["high"] <= upper) &
        (df["low"] >= lower) & (df["low"] <= upper)
    )
    removed = (~mask).sum()
    if removed:
        logger = logging.getLogger(__name__)
        logger.warning(f"[{interval}] Отброшено {removed} свечей с выбросами")
        df = df.loc[mask].reset_index(drop=True)

    return df


def get_wallet_balance(session, coin: str = "USDT") -> float:
    """Возвращает walletBalance для указанной монеты на Unified счёте."""
    resp = retry_api_call(lambda: session.get_wallet_balance(accountType="UNIFIED", coin=coin))
    if resp["retCode"] != 0:
        logging.getLogger(__name__).error(f"Ошибка баланса: {resp['retMsg']}")
        return 0.0
    result = resp["result"]["list"]
    for acc in result:
        for c in acc.get("coin", []):
            if c["coin"] == coin:
                return float(c["walletBalance"])
    return 0.0


def get_position(session, symbol: str, category: str = "linear"):
    """Возвращает открытую позицию по символу или None."""
    resp = retry_api_call(lambda: session.get_positions(category=category, symbol=symbol))
    if resp["retCode"] != 0:
        logging.getLogger(__name__).error(f"Ошибка позиции: {resp['retMsg']}")
        return None
    positions = resp["result"]["list"]
    for pos in positions:
        size = float(pos.get("size", 0))
        if size != 0:
            return pos
    return None


def get_instrument_info(session, symbol: str, category: str = "linear"):
    """
    Возвращает instrument info (minOrderQty, qtyStep и т.д.).
    """
    resp = retry_api_call(lambda: session.get_instruments_info(category=category, symbol=symbol))
    if resp["retCode"] != 0:
        logging.getLogger(__name__).error(f"Ошибка instrument info: {resp['retMsg']}")
        return None
    instruments = resp["result"]["list"]
    if not instruments:
        return None
    return instruments[0]


def set_leverage(session, symbol: str, leverage: int, category: str = "linear"):
    """Устанавливает плечо для long/short."""
    try:
        resp = retry_api_call(lambda: session.set_leverage(
            category=category,
            symbol=symbol,
            buyLeverage=str(leverage),
            sellLeverage=str(leverage),
        ), no_retry_substrings=["leverage not modified"])
        logger = logging.getLogger(__name__)
        if resp["retCode"] == 0:
            logger.info(f"Плечо установлено: {leverage}x")
        else:
            msg = resp.get("retMsg", "")
            if "leverage not modified" in msg:
                logger.info(f"Плечо уже {leverage}x")
            else:
                logger.warning(f"Ошибка установки плеча: {msg}")
    except Exception as e:
        msg = str(e)
        if "leverage not modified" in msg:
            logging.getLogger(__name__).info(f"Плечо уже {leverage}x")
        else:
            logging.getLogger(__name__).warning(f"Ошибка установки плеча: {e}")


def place_market_order(session, symbol: str, side: str, qty: float,
                       stop_loss: float = None, category: str = "linear") -> str:
    """
    Выставляет рыночный ордер.
    Возвращает orderId или None.
    """
    params = {
        "category": category,
        "symbol": symbol,
        "side": side,          # "Buy" или "Sell"
        "orderType": "Market",
        "qty": str(qty),
        "timeInForce": "GTC",
    }
    if stop_loss is not None:
        params["stopLoss"] = str(stop_loss)
        params["slTriggerBy"] = "LastPrice"

    resp = retry_api_call(lambda: session.place_order(**params))
    logger = logging.getLogger(__name__)
    if resp["retCode"] == 0:
        logger.info(f"Ордер {side} размещён, qty={qty}, SL={stop_loss}")
        return resp["result"]["orderId"]
    else:
        logger.error(f"Ошибка ордера: {resp['retMsg']}")
        return None


def close_position_market(session, symbol: str, category: str = "linear"):
    """Закрывает текущую позицию рыночным ордером."""
    pos = get_position(session, symbol, category)
    if not pos:
        logging.getLogger(__name__).info("Закрывать нечего — позиции нет.")
        return

    side = "Sell" if pos["side"] == "Buy" else "Buy"
    qty = pos["size"]

    resp = retry_api_call(lambda: session.place_order(
        category=category,
        symbol=symbol,
        side=side,
        orderType="Market",
        qty=str(qty),
        timeInForce="GTC",
        reduceOnly=True,
    ))
    logger = logging.getLogger(__name__)
    if resp["retCode"] == 0:
        logger.info(f"Позиция закрыта ордером {side}, qty={qty}")
    else:
        logger.error(f"Ошибка закрытия: {resp['retMsg']}")


def calculate_qty(equity: float, entry: float, stop: float, risk_pct: float) -> float:
    """
    Рассчитывает количество монет (BTC, ETH) исходя из допустимого риска.

    Примечание: leverage НЕ входит в формулу.
    Плечо только уменьшает требуемый margin, но не влияет на реальный убыток.
    Убыток = qty * |entry - stop|.
    """
    risk_usd = equity * risk_pct
    price_risk = abs(entry - stop)
    if price_risk <= 0:
        return 0.0
    qty = risk_usd / price_risk
    return qty


def normalize_qty(qty: float, instrument_info: dict) -> float:
    """
    Округляет qty вниз до qtyStep и проверяет minOrderQty.
    Возвращает 0.0 если qty меньше минимально допустимого.
    Использует Decimal для избежания float-ошибок.
    """
    lot = instrument_info.get("lotSizeFilter", {})
    min_qty = float(lot.get("minOrderQty", 0))
    qty_step = float(lot.get("qtyStep", 0))

    if qty_step <= 0 or min_qty <= 0:
        logging.getLogger(__name__).warning(
            f"Невалидные lotSizeFilter: minOrderQty={min_qty}, qtyStep={qty_step}"
        )
        return 0.0

    d_qty = Decimal(str(qty))
    d_step = Decimal(str(qty_step))
    d_min = Decimal(str(min_qty))

    rounded = float((d_qty / d_step).quantize(Decimal('1'), rounding=ROUND_DOWN) * d_step)
    if rounded < d_min:
        return 0.0
    return rounded


def get_api_keys_from_env():
    """Возвращает API ключи из переменных окружения."""
    key = os.environ.get("BYBIT_API_KEY", "")
    secret = os.environ.get("BYBIT_API_SECRET", "")
    return key, secret
