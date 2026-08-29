@echo off
rem Double-clickable launcher for Windows (powered by uv)
cd /d "%~dp0"

echo ============================================================
echo     Amazon VAT Report - FC_Transfer Price Automation
echo ============================================================
echo.

set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"

where uv >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Installing uv...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
)

uv run process_report.py %*

echo.
pause
