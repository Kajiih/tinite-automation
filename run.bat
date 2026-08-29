@echo off
rem Double-clickable launcher for Windows (powered by uv)
setlocal

cd /d "%~dp0"

echo ==========================================================================
echo     Amazon VAT Report - FC_Transfer Price Automation ^& Country Summary
echo ==========================================================================
echo.

set "UV_CMD=uv"

rem Check if uv is available in current PATH
where uv >nul 2>nul
if %ERRORLEVEL% equ 0 goto run_script

rem Check standard Windows installation directories for uv.exe
if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"
    goto run_script
)
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
    set "UV_CMD=%USERPROFILE%\.cargo\bin\uv.exe"
    goto run_script
)
if exist "%LOCALAPPDATA%\Programs\uv\uv.exe" (
    set "UV_CMD=%LOCALAPPDATA%\Programs\uv\uv.exe"
    goto run_script
)

rem If uv is not found anywhere, install it via official PowerShell installer
echo uv was not found on your system. Installing uv...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"

if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"
    goto run_script
)
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
    set "UV_CMD=%USERPROFILE%\.cargo\bin\uv.exe"
    goto run_script
)

where uv >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Failed to find or install uv automatically.
    echo Please install uv manually from https://astral.sh/uv or install Python 3.11+.
    echo.
    goto cleanup
)

:run_script
"%UV_CMD%" run process_report.py %*

:cleanup
echo.
echo ==========================================================================
echo Execution finished. Press any key to close this window.
echo ==========================================================================
pause >nul
