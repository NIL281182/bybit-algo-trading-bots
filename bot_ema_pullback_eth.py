#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETH/USDT EMA Pullback Bot — Bybit Testnet (USDT Perpetual)
Стратегия: 4H EMA20 Pullback + 1D EMA20 Trend Filter. Only Long.
Вход: pullback к EMA20 в восходящем тренде (low <= ema20, close > ema20).
Стоп: entry - 1.0 * ATR14.
Выход: trailing — позиция закрывается, если close 4H < EMA20.
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

SYMBOL = "ETHUSDT"
CATEGORY = "linear"
LEVERAGE = 2
RISK_PCT = 0.01
EMA_4H = 20
EMA_1D = 20
ATR_LEN = 14
SL_ATR_MULT = 1.0

CHECK_INTERVAL = 900    # секунды
# ==========================================================

log = setup_logger(__name__, "bot_ema_pullback_eth.log")


def add_indicators_4h(df):
    df["ema20"] = df["close"].ewm(span=EMA_4H, adjust=False).mean()
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(window=ATR_LEN).mean()
    return df


def add_indicators_1d(df):
    df["ema20"] = df["close"].ewm(span=EMA_1D, adjust=False).mean()
    df["trend_long"] = df["close"] > df["ema20"]
    return df


def merge_trend_to_4h(df_4h, df_1d):
    """Мержит дневной тренд (shift 1 чтобы избежать look-ahead)."""
    df_1d = df_1d.copy()
    df_1d["date"] = df_1d["timestamp"].dt.date
    df_1d["trend_long"] = df_1d["trend_long"].shift(1)
    trend_map = df_1d.set_index("date")[["trend_long"]]

    df_4h = df_4h.copy()
    df_4h["date"] = df_4h["timestamp"].dt.date
    df_4h = df_4h.merge(trend_map, left_on="date", right_index=True, how="left")
    df_4h["trend_long"] = df_4h["trend_long"].ffill()
    return df_4h


def main():
    log.info("=" * 60)
    log.info("Запуск EMA Pullback ETH Bot | Bybit Testnet")
    log.info("=" * 60)

    if not API_KEY or not API_SECRET:
        log.error("❌ API_KEY или API_SECRET не найдены в .env!")
        return

    trade_session = get_trade_session(API_KEY, API_SECRET, testnet=True)
    data_session = get_data_session(testnet=False)

    # Проверка соединений
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
                log.error(f"Ошибка Testnet: {e}")
                alert_error("Ошибка подключения к Bybit Testnet", str(e))
                return
            time.sleep(10)

    try:
        test_4h = fetch_klines(data_session, SYMBOL, "240", limit=10, category=CATEGORY)
        if test_4h is not None and len(test_4h) > 0:
            log.info(f"Данные 4H OK. Последняя цена: {test_4h['close'].iloc[-1]:,.2f}")
        else:
            log.warning("Не удалось загрузить 4H данные")
    except Exception as e:
        log.error(f"Ошибка данных: {e}")
        alert_error("Ошибка загрузки данных с Mainnet", str(e))
        return

    alert_startup("EMA Pullback ETH Bot", SYMBOL)

    # Заранее получаем instrument info для валидации лотов
    instrument = get_instrument_info(data_session, SYMBOL, CATEGORY)
    if instrument is None:
        log.warning("Не удалось получить instrument info — валидация лотов отключена")

    set_leverage(trade_session, SYMBOL, LEVERAGE, CATEGORY)

    in_position = False
    entry_price = None
    stop_price = None
    last_trade_date = None

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

            df_4h = fetch_klines(data_session, SYMBOL, "240", limit=200, category=CATEGORY)
            df_1d = fetch_klines(data_session, SYMBOL, "D", limit=100, category=CATEGORY)

            if df_4h is None or len(df_4h) < 60 or df_1d is None or len(df_1d) < 30:
                log.warning("Недостаточно данных, ждём...")
                time.sleep(CHECK_INTERVAL)
                continue

            df_4h = add_indicators_4h(df_4h)
            df_1d = add_indicators_1d(df_1d)
            df_4h = merge_trend_to_4h(df_4h, df_1d)

            last = df_4h.iloc[-1]
            prev = df_4h.iloc[-2]

            current_price = last["close"]
            trend_ok = bool(last["trend_long"]) if pd.notna(last["trend_long"]) else False

            log.info(
                f"ETH: {current_price:.2f} | 4H EMA20: {last['ema20']:.2f} | "
                f"ATR: {last['atr14']:.2f} | 1D тренд: {'ВВЕРХ' if trend_ok else 'НЕТ'}"
            )

            pos = get_position(trade_session, SYMBOL, CATEGORY)

            if not in_position and pos is None:
                # ======== ПОИСК ВХОДА ========
                today = last["timestamp"].date()
                if last_trade_date == today:
                    log.info("Кулдаун: сегодня уже была сделка.")
                elif not trend_ok:
                    log.info("Нет сигнала: дневной тренд не вверх.")
                else:
                    if prev["low"] <= prev["ema20"] and prev["close"] > prev["ema20"]:
                        entry_price = current_price
                        stop_price = entry_price - SL_ATR_MULT * last["atr14"]

                        equity = get_wallet_balance(trade_session)
                        if equity <= 0:
                            log.warning("Баланс 0, пропускаем вход.")
                            alert_balance_zero()
                        else:
                            qty = calculate_qty(equity, entry_price, stop_price, RISK_PCT)
                            if qty <= 0:
                                log.warning("Расчётное количество = 0, пропускаем.")
                            else:
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
                                    f"🚀 СИГНАЛ ЛОНГ ETH! Вход: {entry_price:.2f}, "
                                    f"SL: {stop_price:.2f}, Qty: {qty}"
                                )
                                order_id = place_market_order(
                                    trade_session, SYMBOL, "Buy", qty,
                                    stop_loss=stop_price, category=CATEGORY
                                )
                                if order_id:
                                    in_position = True
                                    last_trade_date = today
                                    alert_entry(SYMBOL, "Buy", entry_price, stop_price, qty, equity)
                                else:
                                    entry_price = None
                                    stop_price = None
                    else:
                        log.info("Нет сигнала: нет отскока от EMA20.")

            elif in_position or pos is not None:
                # ======== ПРОВЕРКА ВЫХОДА ========
                if pos and not in_position:
                    log.info("Обнаружена позиция на бирже, перехватываем управление...")
                    in_position = True
                    entry_price = float(pos["avgPrice"])

                if in_position and pos is None:
                    log.info("⛔ Позиция закрыта (вероятно, по стопу).")
                    alert_exit(SYMBOL, "Стоп-лосс сработал на бирже")
                    in_position = False
                    entry_price = None
                    stop_price = None
                    continue

                if prev["close"] < prev["ema20"]:
                    log.info(
                        f"📉 Трейлинг-выход ETH! Close {prev['close']:.2f} < EMA20 {prev['ema20']:.2f}"
                    )
                    close_position_market(trade_session, SYMBOL, CATEGORY)
                    alert_exit(SYMBOL, "Трейлинг-выход (close < EMA20)", price=prev["close"])
                    in_position = False
                    entry_price = None
                    stop_price = None
                else:
                    log.info(
                        f"В позиции ETH. Цена: {current_price:.2f}, EMA20: {last['ema20']:.2f} — держим."
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
            alert_error(f"Ошибка в цикле EMA Pullback ETH", str(e))

        log.info(f"Следующая проверка через {CHECK_INTERVAL // 60} минут...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
