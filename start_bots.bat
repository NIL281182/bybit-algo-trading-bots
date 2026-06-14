@echo off
cd /d "%~dp0"

start "BTC Donchian v3 Bot" cmd /k python bot_donchian_v3.py
start "ETH EMA Pullback Bot" cmd /k python bot_ema_pullback_eth.py
