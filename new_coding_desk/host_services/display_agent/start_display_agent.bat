@echo off
title SmartDesk Display Agent
setlocal

:: ── Resolve paths ───────────────────────────────────────────────────────────
set "SD_ROOT=%~dp0..\.."
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"
for %%I in ("%SD_ROOT%\..") do set "REPO_ROOT=%%~fI"
set "VENV_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if defined SMARTDESK_PYTHON set "VENV_PYTHON=%SMARTDESK_PYTHON%"
set "PYTHON_GATE=%REPO_ROOT%\scripts\check_python_runtime.py"
if defined SMARTDESK_PYTHON_GATE set "PYTHON_GATE=%SMARTDESK_PYTHON_GATE%"
set "PYTHONUTF8=1"
set "AGENT_DIR=%SD_ROOT%\host_services\display_agent"
set "RUNTIME_DIR=%SD_ROOT%\.smartdesk-runtime"

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"

echo ==========================================
echo   SmartDesk Display Agent
echo ==========================================
echo.

:: ── Verify dependencies ─────────────────────────────────────────────────────
if not exist "%VENV_PYTHON%" (
    echo   [ERROR] SmartDesk Python environment not found: %VENV_PYTHON%
    echo   Run: "%REPO_ROOT%\SETUP_PYTHON.bat"
    pause
    exit /b 1
)
"%VENV_PYTHON%" "%PYTHON_GATE%" >nul
if errorlevel 1 exit /b 1

"%VENV_PYTHON%" -c "import fastapi, uvicorn, pydantic" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] Missing Python deps. Run: pip install fastapi uvicorn pydantic pywin32 psutil
    pause
    exit /b 1
)

:: pywin32 is optional — agent degrades gracefully if missing
"%VENV_PYTHON%" -c "import win32gui" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [WARN] pywin32 not installed — Win32 operations will be unavailable.
    echo   Install: pip install pywin32
)

echo   Starting Display Agent on http://127.0.0.1:8766 ...
echo   NOTE: Run this script as the logged-in user, not as a Windows Service.
echo.

cd /d "%AGENT_DIR%"
"%VENV_PYTHON%" agent.py
endlocal
