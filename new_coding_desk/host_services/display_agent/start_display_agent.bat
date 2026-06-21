@echo off
title SmartDesk Display Agent
setlocal

:: ── Resolve paths ───────────────────────────────────────────────────────────
set "SD_ROOT=%~dp0..\.."
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"
set "AGENT_DIR=%SD_ROOT%\host_services\display_agent"
set "RUNTIME_DIR=%SD_ROOT%\.smartdesk-runtime"

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"

echo ==========================================
echo   SmartDesk Display Agent
echo ==========================================
echo.

:: ── Verify dependencies ─────────────────────────────────────────────────────
python -c "import fastapi, uvicorn, pydantic" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] Missing Python deps. Run: pip install fastapi uvicorn pydantic pywin32 psutil
    pause
    exit /b 1
)

:: pywin32 is optional — agent degrades gracefully if missing
python -c "import win32gui" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [WARN] pywin32 not installed — Win32 operations will be unavailable.
    echo   Install: pip install pywin32
)

echo   Starting Display Agent on http://127.0.0.1:8766 ...
echo   NOTE: Run this script as the logged-in user, not as a Windows Service.
echo.

cd /d "%AGENT_DIR%"
python agent.py
endlocal
