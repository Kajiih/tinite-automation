@echo off
rem Double-clickable launcher for Windows
cd /d "%~dp0"

echo ============================================================
echo     Amazon VAT Report - FC_Transfer Price Automation
echo ============================================================
echo.

where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv run process_report.py %*
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        python process_report.py %*
    ) else (
        echo Error: Neither 'uv' nor 'python' was found on your system.
        echo Please install Python (https://www.python.org/) or uv (https://docs.astral.sh/uv/).
    )
)

echo.
pause
