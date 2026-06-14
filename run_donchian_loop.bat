@echo off
cd /d "%~dp0"
chcp 866 >nul
:loop
cls
echo [%date% %time%] ========================================
echo [%date% %time%] Zapusk BTC Donchian v3 Bot...
echo [%date% %time%] ========================================
echo.
python bot_donchian_v3.py
if %errorlevel% neq 0 (
    echo [%date% %time%] BTC Bot zavershilsya s oshibkoy %errorlevel%. Perezapusk cherez 15 sek...
) else (
    echo [%date% %time%] BTC Bot zavershilsya shtatno. Perezapusk cherez 15 sek...
)
timeout /t 15 >nul
goto loop
