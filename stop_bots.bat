@echo off
chcp 866 >nul
cls
echo ============================================
echo   Ostanovka torgovykh botov
echo ============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_bots.ps1"

echo.
echo ============================================
echo Boty ostanovleny.
echo ============================================
timeout /t 3 >nul
