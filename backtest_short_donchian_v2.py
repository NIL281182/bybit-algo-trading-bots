#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest: Donchian Breakout SHORT v2 — улучшенная версия.

Улучшения:
1. Фильтр EMA50 slope < 0 (EMA50 должна падать)
2. Для 4H: дневной фильтр тренда (1D close < EMA50 И EMA50 падает)
3. Более быстрый трейлинг: выход при close > EMA10 (вместо EMA20)

Правила:
- Вход (Short): close < Donchian Low(20) AND close < EMA50 AND EMA50_slope < 0
- Стоп: entry + 2.0 * ATR(14)
- Выход: close > EMA10
- Только Short.
"""

import requests
import pandas as pd
import numpy as np

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVALS = ["1d", "4h"]
START = "2020-01-01"
FEE_PCT = 0.0006
RISK_PCT = 0.01
DONCHIAN = 20
EMA_FILT = 50
EMA_TRAIL = 10   # быстрее чем EMA20
ATR_MUL = 2.0
ATR_LEN = 14


def fetch_klines(symbol, interval, start_str):
    url = "https://api.binance.com/api/v3/klines"
    start_ms = int(pd.to_datetime(start_str).timestamp() * 1000)
    all_rows = []
    while True:
        params = {"symbol": symbol, "interval": interval, "startTime": start_ms, "limit": 1000}
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        all_rows.extend(data)
        start_ms = data[-1][0] + 1
        if len(data) < 1000:
            break
    cols = ["timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"]
    df = pd.DataFrame(all_rows, columns=cols)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df[["timestamp", "open", "high", "low", "close", "volume"]].copy()


def add_indicators(df):
    df["ema50"] = df["close"].ewm(span=EMA_FILT, adjust=False).mean()
    df["ema10"] = df["close"].ewm(span=EMA_TRAIL, adjust=False).mean()
    df["donchian_low"] = df["low"].rolling(DONCHIAN).min().shift(1)
    # EMA50 slope: positive = rising, negative = falling
    df["ema50_slope"] = df["ema50"].diff(3)

    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(ATR_LEN).mean()
    return df


def backtest_short(symbol, interval, start_str, use_daily_filter=False):
    df = fetch_klines(symbol, interval, start_str)
    if len(df) < 100:
        return None

    df = add_indicators(df)

    # Optional: daily trend filter for 4H
    if use_daily_filter and interval == "4h":
        df_1d = fetch_klines(symbol, "1d", start_str)
        df_1d = add_indicators(df_1d)
        df_1d["date"] = df_1d["timestamp"].dt.date
        df_1d["trend_down"] = (df_1d["close"] < df_1d["ema50"]) & (df_1d["ema50_slope"] < 0)
        trend_map = df_1d.set_index("date")[["trend_down"]]

        df["date"] = df["timestamp"].dt.date
        df = df.merge(trend_map, left_on="date", right_index=True, how="left")
        df["trend_down"] = df["trend_down"].ffill()
    else:
        df["trend_down"] = True  # disabled

    bh_start = df["close"].iloc[50 + DONCHIAN]
    bh_end = df["close"].iloc[-1]
    bh_return = (bh_end / bh_start - 1) * 100

    equity = 10000.0
    equity_curve = [equity]
    trades = []
    in_pos = False
    entry = stop = size_btc = None

    start_idx = 50 + DONCHIAN

    for i in range(start_idx, len(df)):
        row = df.iloc[i]
        ts = row["timestamp"]

        if not in_pos:
            # Strict filters:
            cond1 = row["close"] < row["donchian_low"]
            cond2 = row["close"] < row["ema50"]
            cond3 = row["ema50_slope"] < 0
            cond4 = row["trend_down"] if "trend_down" in row else True

            if cond1 and cond2 and cond3 and cond4:
                entry = row["close"]
                stop = entry + ATR_MUL * row["atr14"]
                risk = stop - entry
                if risk <= 0 or pd.isna(risk):
                    equity_curve.append(equity)
                    continue
                size_btc = (equity * RISK_PCT) / risk
                in_pos = True
                trades.append({
                    "entry_time": ts, "entry": entry, "stop": stop,
                    "size_btc": size_btc, "risk_usd": equity * RISK_PCT,
                    "exit_time": None, "exit": None, "pnl_usd": None,
                    "exit_type": None,
                })
            equity_curve.append(equity)
        else:
            exit_price = None
            exit_type = None

            if row["high"] >= stop:
                exit_price = stop
                if row["open"] > stop:
                    exit_price = row["open"]
                exit_type = "stop"

            if exit_type is None and row["close"] > row["ema10"]:
                exit_price = row["close"]
                exit_type = "trailing_ema10"

            if exit_type is None:
                equity_curve.append(equity)
                continue

            gross = size_btc * (entry - exit_price)
            fee = (entry + exit_price) * size_btc * FEE_PCT
            pnl = gross - fee
            equity += pnl
            trades[-1].update({
                "exit_time": ts, "exit": exit_price,
                "exit_type": exit_type,
                "pnl_usd": pnl, "pnl_pct": pnl / (equity - pnl),
            })
            in_pos = False
            entry = stop = size_btc = None
            equity_curve.append(equity)

    df_trades = pd.DataFrame(trades)
    closed = df_trades.dropna(subset=["pnl_usd"])
    if len(closed) == 0:
        return None

    wins = closed[closed["pnl_usd"] > 0]
    losses = closed[closed["pnl_usd"] <= 0]

    total_ret = (equity / 10000.0 - 1) * 100
    win_rate = len(wins) / len(closed) * 100
    pf = abs(wins["pnl_usd"].sum() / losses["pnl_usd"].sum()) if len(losses) and losses["pnl_usd"].sum() != 0 else float("inf")
    eq_s = pd.Series(equity_curve)
    dd = ((eq_s - eq_s.cummax()) / eq_s.cummax()).min() * 100
    expectancy = closed["pnl_usd"].mean()

    return {
        "symbol": symbol, "interval": interval,
        "daily_filter": use_daily_filter, "trades": len(closed),
        "win_rate": win_rate, "pf": pf, "ret": total_ret, "dd": dd,
        "expectancy": expectancy, "bh_ret": bh_return,
    }


def main():
    results = []
    print("=" * 70)
    print("BACKTEST: Donchian Breakout SHORT v2 (Enhanced)")
    print("=" * 70)
    print("Filters: close<DonchianLow, close<EMA50, EMA50_slope<0, daily_filter(4H)")
    print("Exit: close > EMA10 (faster trailing)")
    print("=" * 70)
    print()

    for symbol in SYMBOLS:
        for interval in INTERVALS:
            for use_filter in [False, True]:
                label = f"{symbol} {interval}"
                if interval == "4h" and use_filter:
                    label += " + daily"
                elif interval == "4h" and not use_filter:
                    label += " (no daily)"

                print(f"[ Testing {label} ... ]")
                res = backtest_short(symbol, interval, START, use_filter)
                if res:
                    results.append(res)
                    print(f"  Trades: {res['trades']} | Win: {res['win_rate']:.1f}% | "
                          f"Ret: {res['ret']:+.2f}% | DD: {res['dd']:.2f}% | PF: {res['pf']:.2f}")
                print()

    print("=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)
    hdr = f"{'Symbol':<10} {'TF':<8} {'Filter':<12} {'Trades':<8} {'Win%':<8} {'Ret%':<10} {'DD%':<8} {'PF':<8}"
    print(hdr)
    print("-" * 70)
    for r in results:
        filt = "daily" if r.get("daily_filter") else "none"
        print(f"{r['symbol']:<10} {r['interval']:<8} {filt:<12} {r['trades']:<8} {r['win_rate']:<8.1f} "
              f"{r['ret']:<+10.2f} {r['dd']:<8.2f} {r['pf']:<8.2f}")
    print("=" * 70)

    viable = [r for r in results if r["pf"] > 1.5 and r["dd"] > -25 and r["trades"] >= 10]
    if viable:
        viable.sort(key=lambda x: x["pf"], reverse=True)
        best = viable[0]
        print()
        print(f"BEST VIABLE SETUP: {best['symbol']} {best['interval']}")
        print(f"  PF={best['pf']:.2f}, DD={best['dd']:.2f}%, Trades={best['trades']}, Win={best['win_rate']:.1f}%")
    else:
        print()
        print("No viable setup found (PF > 1.5 + DD < 25% + Trades >= 10)")


if __name__ == "__main__":
    main()
