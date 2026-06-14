@echo off
cd /d "%~dp0"
chcp 866 >nul
:loop
cls
echo [%date% %time%] ========================================
echo [%date% %time%] Zapusk ETH EMA Pullback Bot...
echo [%date% %time%] ========================================
echo.
python bot_ema_pullback_eth.py
if %errorlevel% neq 0 (
    echo [%date% %time%] ETH Bot zavershilsya s oshibkoy %errorlevel%. Perezapusk cherez 15 sek...
) else (
    echo [%date% %time%] ETH Bot zavershilsya shtatno. Perezapusk cherez 15 sek...
)
timeout /t 15 >nul
goto loop
