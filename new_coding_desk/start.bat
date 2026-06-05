@echo off
title SmartDesk Launcher

echo ==========================================
echo   SmartDesk - Smart Conference Table
echo   Phase 08 - Speech Demo Launcher
echo ==========================================
echo.

:: Save the project root (%~dp0 includes trailing backslash)
set "SD_ROOT=%~dp0"

:: --- Set demo environment variables ---
set ENABLE_DEMO_SEED=true
set ENABLE_DEMO_SEAT_API=true
set VITE_ENABLE_DEMO_CONTROLS=true

:: --- Step 0: Kill old processes ---
echo [0/4] Cleaning old processes...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING 2^>nul') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr LISTENING 2^>nul') do taskkill /PID %%a /F >nul 2>&1
timeout /t 2 /nobreak >nul
echo   Old processes cleaned.
echo.

:: --- Step 1: Check Python dependencies ---
echo [1/4] Checking Python dependencies...
python -c "import fastapi, sqlalchemy, pydantic, numpy, uvicorn; print('  Core: OK')" 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   [ERROR] Missing core Python packages.
    echo   Run: pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
python -c "import torch, funasr, scipy, soundfile; print('  Speech: OK')" 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   [WARN] Some speech packages missing. Streaming ASR will be unavailable.
    echo   Run: pip install -r requirements.txt
    echo.
)
python -c "import pydub; print('  File transcoding: OK')" 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [INFO] pydub not installed - audio file transcoding disabled.
    echo   (Optional, not required for /ws/speech streaming demo.)
)
echo.

:: --- Step 2: Backend ---
echo [2/4] Starting backend (FastAPI)...
pushd "%SD_ROOT%"
start "SmartDesk-Backend" cmd /k "title SmartDesk-Backend && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level info"
popd
timeout /t 5 /nobreak >nul
echo.

:: --- Step 3: Frontend ---
echo [3/4] Starting frontend (Vite)...
pushd "%SD_ROOT%frontend"
start "SmartDesk-Frontend" cmd /k "title SmartDesk-Frontend && npm run dev -- --host 127.0.0.1"
popd
timeout /t 4 /nobreak >nul
echo.

:: --- Step 4: Launch browser ---
echo [4/4] Opening browser...
timeout /t 2 /nobreak >nul
start http://localhost:5173

echo.
echo ==========================================
echo   SmartDesk is starting up!
echo.
echo   Frontend: http://localhost:5173
echo   API:      http://localhost:8000
echo   Docs:     http://localhost:8000/docs
echo.
echo   Demo controls enabled:
echo     - Auto-seed meeting data
echo     - Seat API controls
echo     - Demo seat preview
echo.
echo   Speech demo workflow:
echo     1. Admin: set Speaker Seat (click seat in preview bar)
echo     2. Seat:  open seat URL with Speaker Seat
echo     3. Seat:  click Start -^> grant mic -^> speak
echo     4. Admin: watch live transcript in Bilingual Transcript panel
echo.
echo   Close this window will NOT stop processes.
echo   Run kill.bat to stop all.
echo ==========================================
echo.

pause
