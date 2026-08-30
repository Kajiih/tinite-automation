@echo off
setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0..\.."

:: Read argument from drag-and-drop on icon, or prompt interactively
set "CSV_PATH=%~1"
if "!CSV_PATH!"=="" (
    echo ========================================================
    echo   Amazon B2B Intra-EU Invoice Downloader (Windows)
    echo ========================================================
    echo.
    set /p "CSV_PATH=Drag and drop your VAT report (.csv) here and press Enter: "
)

:: Strip quotes
set "CSV_PATH=!CSV_PATH:"=!"
set "CSV_PATH=!CSV_PATH:'=!"

if "!CSV_PATH!"=="" (
    echo.
    echo [ERROR] No file specified.
    echo.
    pause
    exit /b 1
)

:: If relative, check in repo root
if not exist "!CSV_PATH!" (
    if exist "!REPO_ROOT!\!CSV_PATH!" (
        set "CSV_PATH=!REPO_ROOT!\!CSV_PATH!"
    )
)

if not exist "!CSV_PATH!" (
    echo.
    echo [ERROR] File not found: "!CSV_PATH!"
    echo.
    pause
    exit /b 1
)

:: Call main repository bootstrap with invoice-downloader command
call "!REPO_ROOT!\run.bat" invoice-downloader --report "!CSV_PATH!"
echo.
pause
