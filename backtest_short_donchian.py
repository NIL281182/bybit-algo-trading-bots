#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest: Donchian Breakout SHORT — зеркальная стратегия для шорта.

Правила:
- Вход (Short): close < Donchian Low(20) AND close < EMA50 (фильтр нисходящего тренда)
- Стоп: entry + ATR_MUL * ATR(14)
- Выход (трейлинг): close > EMA20
- Только Short, без лонгов.

Тестируем на разных таймфреймах и активах для поиска лучшей комбинации.
"""

import requests
import pandas as pd
import numpy as np

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVALS = ["1d", "4h", "1h"]
START = "2020-01-01"
FEE_PCT = 0.0006
RISK_PCT = 0.01
DONCHIAN = 20
EMA_FILT = 50
EMA_TRAIL = 20
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
    df["ema20"] = df["close"].ewm(span=EMA_TRAIL, adjust=False).mean()
    df["donchian_low"] = df["low"].rolling(DONCHIAN).min().shift(1)

    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(ATR_LEN).mean()
    return df


def backtest_short(symbol, interval, start_str):
    df = fetch_klines(symbol, interval, start_str)
    if len(df) < 100:
        print(f"  [{symbol} {interval}] Недостаточно данных ({len(df)} баров)")
        return None

    df = add_indicators(df)

    # Buy & Hold reference (for short, inverted)
    bh_start = df["close"].iloc[50 + DONCHIAN]
    bh_end = df["close"].iloc[-1]
    bh_return = (bh_end / bh_start - 1) * 100

    equity = 10000.0
    equity_curve = [equity]
    trades = []
    in_pos = False
    entry = stop = size_btc = None

    # Skip initial bars for indicators warm-up
    start_idx = 50 + DONCHIAN

    for i in range(start_idx, len(df)):
        row = df.iloc[i]
        ts = row["timestamp"]

        if not in_pos:
            # Short signal: close < donchian_low AND close < ema50 (downtrend)
            if row["close"] < row["donchian_low"] and row["close"] < row["ema50"]:
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
                    "exit_time": None, "exit": None, "pnl_usd": None, "pnl_pct": None,
                    "exit_type": None,
                })
            equity_curve.append(equity)
        else:
            exit_price = None
            exit_type = None

            # 1. Stop loss hit
            if row["high"] >= stop:
                exit_price = stop
                if row["open"] > stop:
                    exit_price = row["open"]
                exit_type = "stop"

            # 2. Trailing exit: close > EMA20
            if exit_type is None:
                if row["close"] > row["ema20"]:
                    exit_price = row["close"]
                    exit_type = "trailing_ema20"

            if exit_type is None:
                equity_curve.append(equity)
                continue

            # PnL for short = size * (entry - exit) - fee
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
        return {
            "symbol": symbol, "interval": interval, "trades": 0,
            "win_rate": 0, "pf": 0, "ret": 0, "dd": 0, "expectancy": 0,
            "bh_ret": bh_return, "period": str(df["timestamp"].iloc[start_idx].date()),
        }

    wins = closed[closed["pnl_usd"] > 0]
    losses = closed[closed["pnl_usd"] <= 0]

    total_ret = (equity / 10000.0 - 1) * 100
    win_rate = len(wins) / len(closed) * 100
    pf = abs(wins["pnl_usd"].sum() / losses["pnl_usd"].sum()) if len(losses) and losses["pnl_usd"].sum() != 0 else float("inf")
    eq_s = pd.Series(equity_curve)
    dd = ((eq_s - eq_s.cummax()) / eq_s.cummax()).min() * 100
    expectancy = closed["pnl_usd"].mean()

    return {
        "symbol": symbol, "interval": interval, "trades": len(closed),
        "win_rate": win_rate, "pf": pf, "ret": total_ret, "dd": dd,
        "expectancy": expectancy, "bh_ret": bh_return,
        "period": f"{df['timestamp'].iloc[start_idx].date()} -> {df['timestamp'].iloc[-1].date()}",
    }


def main():
    results = []
    print("=" * 70)
    print("BACKTEST: Donchian Breakout SHORT (Mirror of Long v3)")
    print("=" * 70)
    print(f"Strategy: close < DonchianLow({DONCHIAN}) AND close < EMA{EMA_FILT}")
    print(f"Stop: entry + {ATR_MUL}*ATR | Exit: close > EMA{EMA_TRAIL}")
    print(f"Risk: {RISK_PCT*100}% equity | Fee: {FEE_PCT*100}%")
    print("=" * 70)
    print()

    for symbol in SYMBOLS:
        for interval in INTERVALS:
            print(f"[ Testing {symbol} {interval} ... ]")
            res = backtest_short(symbol, interval, START)
            if res:
                results.append(res)
                s = "  " if res["trades"] == 0 else ""
                print(f"  Trades: {res['trades']} | Win: {res['win_rate']:.1f}% | "
                      f"Ret: {res['ret']:+.2f}% | DD: {res['dd']:.2f}% | PF: {res['pf']:.2f}")
            print()

    # Summary table
    print("=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)
    print(f"{'Symbol':<10} {'TF':<6} {'Trades':<8} {'Win%':<8} {'Ret%':<10} {'DD%':<8} {'PF':<8} {'B&H%':<8}")
    print("-" * 70)
    for r in results:
        print(f"{r['symbol']:<10} {r['interval']:<6} {r['trades']:<8} {r['win_rate']:<8.1f} "
              f"{r['ret']:<+10.2f} {r['dd']:<8.2f} {r['pf']:<8.2f} {r['bh_ret']:<+8.2f}")
    print("=" * 70)

    # Find best by Profit Factor > 1.5 and reasonable DD
    viable = [r for r in results if r["pf"] > 1.5 and r["dd"] > -30 and r["trades"] >= 10]
    if viable:
        viable.sort(key=lambda x: x["pf"], reverse=True)
        best = viable[0]
        print()
        print(f"🏆 BEST VIABLE SETUP: {best['symbol']} {best['interval']}")
        print(f"   PF={best['pf']:.2f}, DD={best['dd']:.2f}%, Trades={best['trades']}, Win={best['win_rate']:.1f}%")
    else:
        print()
        print("⚠️  No viable setup found (PF > 1.5 + DD < 30% + Trades >= 10)")
        print("   Short strategy may not work well on chosen assets/timeframes.")


if __name__ == "__main__":
    main()
