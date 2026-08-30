@echo off
setlocal enabledelayedexpansion

:: Navigate to repository root directory
cd /d "%~dp0"

:: Check common paths for uv.exe if not in standard PATH
where uv >nul 2>nul
if %errorlevel% neq 0 (
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set "PATH=%USERPROFILE%\.local\bin;!PATH!"
    ) else if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
        set "PATH=%USERPROFILE%\.cargo\bin;!PATH!"
    ) else if exist "%LOCALAPPDATA%\Programs\uv\uv.exe" (
        set "PATH=%LOCALAPPDATA%\Programs\uv;!PATH!"
    )
)

:: Auto-install uv if still not found
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo ========================================================
    echo  'uv' is not installed. Installing automatically...
    echo ========================================================
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;!PATH!"
)

:: Verify uv installation
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Failed to install 'uv'. Please install it from https://astral.sh/uv
    pause
    exit /b 1
)

:: Execute command via uv if arguments provided, otherwise launch Web Hub
if "%~1"=="" (
    uv run --no-dev --package web-hub python -m web_server.server
    pause >nul
) else (
    uv run %*
)
