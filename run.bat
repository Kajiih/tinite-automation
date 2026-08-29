@echo off
rem Double-clickable launcher for Windows (powered by uv)
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ==========================================================================
echo     Amazon VAT Report - FC_Transfer Price Automation ^& Country Summary
echo ==========================================================================
echo.

set "PATH=%LOCALAPPDATA%\bin;%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"

where uv >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Installing uv (fast Python package runner)...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%LOCALAPPDATA%\bin;%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
)

uv run process_report.py %*

echo.
pause
