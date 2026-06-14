#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTC Donchian v3 Bot — Bybit Testnet (USDT Perpetual)
Стратегия: Donchian Breakout 20D + EMA50, выход по EMA20 trailing.
Таймфрейм: 1D. Проверка сигнала раз в час.
"""

import os
import time
from datetime import datetime

import pandas as pd

from bybit_utils import (
    load_env,
    setup_logger,
    get_trade_session,
    get_data_session,
    fetch_klines,
    get_wallet_balance,
    get_position,
    get_instrument_info,
    set_leverage,
    place_market_order,
    close_position_market,
    calculate_qty,
    normalize_qty,
    get_api_keys_from_env,
    get_exit_node_country,
)
from alerts import (
    alert_startup,
    alert_entry,
    alert_exit,
    alert_error,
    alert_balance_zero,
    alert_insufficient_qty,
)

# Загружаем .env ДО чтения переменных окружения
load_env()

# ======================== НАСТРОЙКИ ========================
API_KEY, API_SECRET = get_api_keys_from_env()

SYMBOL = "BTCUSDT"
CATEGORY = "linear"
LEVERAGE = 2
RISK_PCT = 0.01         # 1% от equity на сделку
DONCHIAN = 20
EMA_FILT = 50
EMA_TRAIL = 20
ATR_MUL = 2.0
ATR_LEN = 14

CHECK_INTERVAL = 3600   # секунды
# ==========================================================

log = setup_logger(__name__, "bot_donchian_v3.log")


def add_indicators(df):
    """Добавляет EMA50, EMA20, Donchian High, ATR14."""
    df["ema50"] = df["close"].ewm(span=EMA_FILT, adjust=False).mean()
    df["ema20"] = df["close"].ewm(span=EMA_TRAIL, adjust=False).mean()
    df["donchian_high"] = df["high"].rolling(window=DONCHIAN).max().shift(1)

    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(window=ATR_LEN).mean()
    return df


def main():
    log.info("=" * 60)
    log.info("Запуск Donchian v3 Bot | Bybit Testnet")
    log.info("=" * 60)

    if not API_KEY or not API_SECRET:
        log.error("❌ API_KEY или API_SECRET не найдены в переменных окружения!")
        return

    trade_session = get_trade_session(API_KEY, API_SECRET, testnet=True)
    data_session = get_data_session(testnet=False)

    # Проверка торгового соединения
    connected = False
    for attempt in range(1, 4):
        try:
            trade_session.get_account_info()
            log.info("Торговое соединение OK. Testnet: True")
            connected = True
            break
        except Exception as e:
            log.warning(f"Попытка {attempt}/3 подключения к Testnet: {e}")
            if attempt == 3:
                log.error(f"Ошибка подключения к Testnet: {e}")
                alert_error("Ошибка подключения к Bybit Testnet", str(e))
                return
            time.sleep(10)

    # Проверка загрузки данных
    try:
        test_df = fetch_klines(data_session, SYMBOL, interval="D", limit=10, category=CATEGORY)
        if test_df is not None and len(test_df) > 0:
            log.info(f"Данные с Mainnet OK. Последняя цена: {test_df['close'].iloc[-1]:,.2f}")
        else:
            log.warning("Не удалось загрузить данные с Mainnet — продолжаем с осторожностью")
    except Exception as e:
        log.error(f"Ошибка загрузки данных с Mainnet: {e}")
        alert_error("Ошибка загрузки данных с Mainnet", str(e))
        return

    alert_startup("Donchian v3 Bot", SYMBOL)

    # Заранее получаем instrument info для валидации лотов
    instrument = get_instrument_info(data_session, SYMBOL, CATEGORY)
    if instrument is None:
        log.warning("Не удалось получить instrument info — валидация лотов отключена")

    set_leverage(trade_session, SYMBOL, LEVERAGE, CATEGORY)

    in_position = False
    entry_price = None
    stop_price = None

    while True:
        try:
            # Проверяем, не ведёт ли VPN в США сейчас
            vpn_country = get_exit_node_country()
            if vpn_country is None:
                log.warning("Не удалось определить страну VPN, повторим через минуту...")
                time.sleep(60)
                continue
            if vpn_country == "US":
                log.warning(f"VPN подключён к США ({vpn_country}), пропускаем цикл...")
                time.sleep(CHECK_INTERVAL)
                continue
            log.info(f"VPN страна: {vpn_country}")

            log.info("--- Проверка сигнала ---")

            # 1. Загружаем данные с Mainnet
            df = fetch_klines(data_session, SYMBOL, interval="D", limit=100, category=CATEGORY)
            if df is None or len(df) < 60:
                log.warning("Недостаточно данных, ждём...")
                time.sleep(CHECK_INTERVAL)
                continue

            df = add_indicators(df)
            last = df.iloc[-1]
            prev = df.iloc[-2]

            current_price = last["close"]
            log.info(
                f"Цена (Mainnet): {current_price:.2f} | EMA50: {last['ema50']:.2f} | "
                f"Donchian: {last['donchian_high']:.2f} | ATR: {last['atr14']:.2f}"
            )

            # 2. Проверяем позицию на бирже (Testnet)
            pos = get_position(trade_session, SYMBOL, CATEGORY)

            if not in_position and pos is None:
                # ======== ПОИСК ВХОДА ========
                if prev["close"] > prev["donchian_high"] and prev["close"] > prev["ema50"]:
                    entry_price = current_price
                    stop_price = entry_price - ATR_MUL * last["atr14"]

                    equity = get_wallet_balance(trade_session)
                    if equity <= 0:
                        log.warning("Баланс 0, пропускаем вход.")
                        alert_balance_zero()
                        continue

                    qty = calculate_qty(equity, entry_price, stop_price, RISK_PCT)
                    if qty <= 0:
                        log.warning("Расчётное количество = 0, пропускаем.")
                        continue

                    # Валидация минимального лота
                    if instrument:
                        raw_qty = qty
                        qty = normalize_qty(qty, instrument)
                        if qty <= 0:
                            log.warning(
                                f"Qty ({raw_qty:.6f}) "
                                f"меньше минимально допустимого. Пропускаем."
                            )
                            alert_insufficient_qty(raw_qty)
                            continue

                    log.info(
                        f"🚀 СИГНАЛ ЛОНГ! Вход: {entry_price:.2f}, "
                        f"SL: {stop_price:.2f}, Qty: {qty}"
                    )
                    order_id = place_market_order(
                        trade_session, SYMBOL, "Buy", qty, stop_loss=stop_price, category=CATEGORY
                    )
                    if order_id:
                        in_position = True
                        alert_entry(SYMBOL, "Buy", entry_price, stop_price, qty, equity)
                    else:
                        entry_price = None
                        stop_price = None
                else:
                    log.info("Нет сигнала на вход.")

            elif in_position or pos is not None:
                # ======== ПРОВЕРКА ВЫХОДА ========
                if pos and not in_position:
                    log.info("Обнаружена позиция на бирже, перехватываем управление...")
                    in_position = True
                    entry_price = float(pos["avgPrice"])

                # Проверяем, не закрылась ли позиция по стопу
                if in_position and pos is None:
                    log.info("⛔ Позиция закрыта (вероятно, по стопу).")
                    alert_exit(SYMBOL, "Стоп-лосс сработал на бирже")
                    in_position = False
                    entry_price = None
                    stop_price = None
                    continue

                # Трейлинг-выход: close < EMA20 (по предыдущей закрытой свече)
                if prev["close"] < prev["ema20"]:
                    log.info(
                        f"📉 Трейлинг-выход! Close {prev['close']:.2f} < EMA20 {prev['ema20']:.2f}"
                    )
                    close_position_market(trade_session, SYMBOL, CATEGORY)
                    alert_exit(SYMBOL, "Трейлинг-выход (close < EMA20)", price=prev["close"])
                    in_position = False
                    entry_price = None
                    stop_price = None
                else:
                    log.info(
                        f"В позиции. Цена: {current_price:.2f}, EMA20: {last['ema20']:.2f} — держим."
                    )

        except Exception as e:
            log.error(f"Ошибка в цикле: {e}", exc_info=True)
            err_msg = str(e).lower()
            is_rate_limit = any(x in err_msg for x in ["403", "429", "rate limit", "ip rate"])
            is_network = any(x in err_msg for x in ["connection", "reset", "aborted", "timeout"])
            if is_rate_limit or is_network:
                # При 403 от Bybit (геоблок/rate-limit) делаем длинную паузу
                backoff = 300 if is_rate_limit else min(CHECK_INTERVAL, 30)
                log.warning(f"Сетевая/rate-limit ошибка — пауза {backoff} сек перед повтором...")
                time.sleep(backoff)
                continue
            alert_error(f"Ошибка в цикле Donchian v3", str(e))

        log.info(f"Следующая проверка через {CHECK_INTERVAL // 60} минут...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
