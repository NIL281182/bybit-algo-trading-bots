#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTC Donchian Breakout v3 - Daily Trend Following (Only Long)
20-дневный пробой + фильтр EMA50, выход по EMA20 trailing.
"""

import requests
import pandas as pd
import numpy as np

SYMBOL   = 'BTCUSDT'
INTERVAL = '1d'
START    = '2020-01-01'
FEE_PCT  = 0.0006
RISK_PCT = 0.01
DONCHIAN = 20
EMA_FILT = 50
EMA_TRAIL= 20
ATR_MUL  = 2.0
ATR_LEN  = 14

def fetch_klines(symbol, interval, start_str, end_str=None):
    url = "https://api.binance.com/api/v3/klines"
    start_ms = int(pd.to_datetime(start_str).timestamp() * 1000)
    end_ms   = int(pd.to_datetime(end_str).timestamp() * 1000) if end_str else None
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
        if end_ms and start_ms >= end_ms:
            break
    cols = ['timestamp','open','high','low','close','volume',
            'close_time','quote_vol','trades','taker_buy_base',
            'taker_buy_quote','ignore']
    df = pd.DataFrame(all_rows, columns=cols)
    for col in ['open','high','low','close','volume']:
        df[col] = df[col].astype(float)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df[['timestamp','open','high','low','close','volume']].copy()

def add_indicators(df):
    df['ema50'] = df['close'].ewm(span=EMA_FILT, adjust=False).mean()
    df['ema20'] = df['close'].ewm(span=EMA_TRAIL, adjust=False).mean()
    df['donchian_high'] = df['high'].rolling(DONCHIAN).max().shift(1)
    # ATR
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift(1)).abs()
    lc = (df['low']  - df['close'].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(ATR_LEN).mean()
    return df

def backtest():
    print("[1/2] Loading daily data...")
    df = fetch_klines(SYMBOL, INTERVAL, START)
    print(f"      Daily bars: {len(df)} | {df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}")

    print("[2/2] Running backtest...")
    df = add_indicators(df)

    # Buy & Hold calc
    bh_start = df['close'].iloc[50]
    bh_end   = df['close'].iloc[-1]
    bh_return = (bh_end / bh_start - 1) * 100

    equity = 10000.0
    equity_curve = [equity]
    trades = []
    in_pos = False
    entry = stop = size_btc = None

    for i in range(50 + DONCHIAN, len(df)):
        row = df.iloc[i]
        ts = row['timestamp']

        if not in_pos:
            # Signal: close > donchian_high AND close > ema50
            if row['close'] > row['donchian_high'] and row['close'] > row['ema50']:
                entry = row['close']
                stop  = entry - ATR_MUL * row['atr14']
                risk  = entry - stop
                if risk <= 0:
                    equity_curve.append(equity)
                    continue
                size_btc = (equity * RISK_PCT) / risk
                in_pos = True
                trades.append({
                    'entry_time': ts, 'entry': entry, 'stop': stop,
                    'size_btc': size_btc, 'risk_usd': equity * RISK_PCT,
                    'exit_time': None, 'exit': None, 'pnl_usd': None, 'pnl_pct': None
                })
            equity_curve.append(equity)
        else:
            exit_price = None
            exit_type = None

            # 1. Stop loss
            if row['low'] <= stop:
                exit_price = stop
                if row['open'] < stop:
                    exit_price = row['open']
                exit_type = 'stop'

            # 2. Trailing exit: close < EMA20
            if exit_type is None:
                if row['close'] < row['ema20']:
                    exit_price = row['close']
                    exit_type = 'trailing_ema20'

            if exit_type is None:
                equity_curve.append(equity)
                continue

            gross = size_btc * (exit_price - entry)
            fee = (entry + exit_price) * size_btc * FEE_PCT
            pnl = gross - fee
            equity += pnl
            trades[-1].update({
                'exit_time': ts, 'exit': exit_price,
                'exit_type': exit_type,
                'pnl_usd': pnl, 'pnl_pct': pnl / (equity - pnl)
            })
            in_pos = False
            entry = stop = size_btc = None
            equity_curve.append(equity)

    df_trades = pd.DataFrame(trades)
    closed = df_trades.dropna(subset=['pnl_usd'])
    wins = closed[closed['pnl_usd'] > 0]
    losses = closed[closed['pnl_usd'] <= 0]

    total_ret = (equity / 10000.0 - 1) * 100
    win_rate = len(wins) / len(closed) * 100 if len(closed) else 0
    pf = abs(wins['pnl_usd'].sum() / losses['pnl_usd'].sum()) if len(losses) and losses['pnl_usd'].sum()!=0 else float('inf')
    eq_s = pd.Series(equity_curve)
    dd = ((eq_s - eq_s.cummax()) / eq_s.cummax()).min() * 100

    print("\n" + "="*60)
    print("BACKTEST v3: Donchian Breakout (Daily, Only Long)")
    print("="*60)
    print(f"Period       : {df['timestamp'].iloc[50].date()} -> {df['timestamp'].iloc[-1].date()}")
    print(f"Trades       : {len(closed)}")
    print(f"Winners      : {len(wins)} ({win_rate:.1f}%)")
    print(f"Losers       : {len(losses)} ({100-win_rate:.1f}%)")
    print(f"Start equity : $10,000")
    print(f"Final equity : ${equity:,.2f}")
    print(f"Strategy ret : {total_ret:+.2f}%")
    print(f"Buy&Hold ret : {bh_return:+.2f}%")
    print(f"Max DD       : {dd:.2f}%")
    print(f"Profit Factor: {pf:.2f}")
    if len(wins): print(f"Avg win      : ${wins['pnl_usd'].mean():,.2f}")
    if len(losses): print(f"Avg loss     : ${losses['pnl_usd'].mean():,.2f}")
    print(f"Expectancy   : ${closed['pnl_usd'].mean():,.2f} per trade")
    print("="*60)

    out = "C:/Users/nil28/trade/backtest_results_v3.csv"
    df_trades.to_csv(out, index=False, encoding='utf-8-sig')
    print(f"Saved: {out}")

if __name__ == '__main__':
    backtest()
