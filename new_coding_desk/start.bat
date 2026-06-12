@echo off
title SmartDesk Launcher

:: ==========================================
::   SmartDesk - Smart Conference Table
::   Windows startup script
:: ==========================================

:: ── Project root (always resolve from batch file location) ──────────────────
set "SD_ROOT=%~dp0"
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"

echo ==========================================
echo   SmartDesk - Smart Conference Table
echo ==========================================
echo.

:: ── Demo environment variables ──────────────────────────────────────────────
set ENABLE_DEMO_SEED=true
set ENABLE_DEMO_SEED_WHEN_NO_ACTIVE=true
set ENABLE_DEMO_SEAT_API=true
set VITE_ENABLE_DEMO_CONTROLS=true
set ENABLE_TRANSLATION_MODEL=false

echo   Environment:
echo     ENABLE_DEMO_SEED             = true
echo     ENABLE_DEMO_SEED_WHEN_NO_ACTIVE = true
echo     ENABLE_DEMO_SEAT_API         = true
echo     VITE_ENABLE_DEMO_CONTROLS    = true
echo     ENABLE_TRANSLATION_MODEL     = false
echo.

:: ── Step 0: Prepare runtime directory and clean old instances ───────────────
echo [0/4] Preparing workspace...
if not exist "%SD_ROOT%\.smartdesk-runtime" mkdir "%SD_ROOT%\.smartdesk-runtime"
set "SKIP_PAUSE=1"
call "%SD_ROOT%\kill.bat"
set "SKIP_PAUSE="
%SystemRoot%\System32\timeout.exe /t 2 /nobreak >nul
echo.

:: ── Step 1: Check dependencies ─────────────────────────────────────────────
echo [1/4] Checking dependencies...
echo.

:: Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] Python not found in PATH.
    pause
    exit /b 1
)
echo   Python: OK

:: Core Python packages
python -c "import fastapi, sqlalchemy, pydantic, numpy, uvicorn; print('  OK')" 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] Missing core Python packages.
    echo   Run: pip install -r "%SD_ROOT%\requirements.txt"
    pause
    exit /b 1
)

:: Speech packages (optional)
python -c "import torch, funasr, scipy, soundfile" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [WARN] Speech packages missing - streaming ASR unavailable.
    echo   Install: pip install -r "%SD_ROOT%\requirements.txt"
) else (
    echo   Speech packages: OK
)

:: pydub (optional)
python -c "import pydub" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [INFO] pydub not installed - file transcoding disabled.
)

:: npm
where npm >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] npm not found.
    pause
    exit /b 1
)
echo   npm: OK

:: node_modules
if not exist "%SD_ROOT%\frontend\node_modules" (
    echo   [ERROR] frontend\node_modules not found.
    echo   Run: cd frontend ^&^& npm install
    pause
    exit /b 1
)
echo   node_modules: OK
echo.

:: ── Step 2: Start Backend ──────────────────────────────────────────────────
echo [2/4] Starting backend (FastAPI) on http://127.0.0.1:8000 ...
echo.
:: Launch cmd.exe window via PowerShell Start-Process with -PassThru to capture PID
powershell -NoProfile -Command "$p = Start-Process cmd.exe -ArgumentList '/k ""title SmartDesk Backend && cd /d %SD_ROOT% && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level info""' -WindowStyle Normal -PassThru; $p.Id | Set-Content -Encoding ascii '%SD_ROOT%\.smartdesk-runtime\backend.pid'"
if exist "%SD_ROOT%\.smartdesk-runtime\backend.pid" (
    set /p BACKEND_PID=<"%SD_ROOT%\.smartdesk-runtime\backend.pid"
    echo   Backend window PID: %BACKEND_PID%
) else (
    echo   [WARN] Could not save backend PID
)
echo   Waiting 8s for backend to start...
%SystemRoot%\System32\timeout.exe /t 8 /nobreak >nul
echo.

:: ── Step 3: Start Frontend ─────────────────────────────────────────────────
echo [3/4] Starting frontend (Vite) on http://127.0.0.1:5173 ...
echo.
powershell -NoProfile -Command "$p = Start-Process cmd.exe -ArgumentList '/k ""title SmartDesk Frontend && cd /d %SD_ROOT%\frontend && npm run dev -- --host 127.0.0.1""' -WindowStyle Normal -PassThru; $p.Id | Set-Content -Encoding ascii '%SD_ROOT%\.smartdesk-runtime\frontend.pid'"
if exist "%SD_ROOT%\.smartdesk-runtime\frontend.pid" (
    set /p FRONTEND_PID=<"%SD_ROOT%\.smartdesk-runtime\frontend.pid"
    echo   Frontend window PID: %FRONTEND_PID%
) else (
    echo   [WARN] Could not save frontend PID
)
echo   Frontend starting (allow 5-8s for initial compile)...
%SystemRoot%\System32\timeout.exe /t 4 /nobreak >nul
echo.

:: ── Step 4: Open browser ───────────────────────────────────────────────────
echo [4/4] Opening browser...
%SystemRoot%\System32\timeout.exe /t 2 /nobreak >nul
start http://localhost:5173

echo.
echo ==========================================
echo   SmartDesk is starting up!
echo.
echo   Frontend: http://localhost:5173
echo   API:      http://localhost:8000
echo   Docs:     http://localhost:8000/docs
echo.
echo   Demo controls enabled.
echo.
echo   Close this window will NOT stop processes.
echo   Run kill.bat to stop all.
echo ==========================================
echo.

pause
exit /b 0
