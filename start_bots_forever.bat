@echo off
cd /d "%~dp0"

chcp 866 >nul
echo ============================================
echo   Zapusk botov s avtoperezapuskom (watchdog)
echo ============================================
echo.

echo [1/2] Zapusk BTC Donchian v3 Bot...
start "BTC Donchian v3 Bot [Watchdog]" cmd /k call "%~dp0run_donchian_loop.bat"

echo [2/2] Zapusk ETH EMA Pullback Bot...
start "ETH EMA Pullback Bot [Watchdog]" cmd /k call "%~dp0run_ema_loop.bat"

echo.
echo Oba bota zapushcheny. Esli bot upadet, okno samo perezapustit ego.
timeout /t 3 >nul
