@echo off
title SmartDesk Launcher

echo ==========================================
echo   SmartDesk - Smart Conference Table
echo   Phase 06 - Demo Launcher
echo ==========================================
echo.

cd /d "%~dp0"

:: --- Set demo environment variables ---
set ENABLE_DEMO_SEED=true
set ENABLE_DEMO_SEAT_API=true
set VITE_ENABLE_DEMO_CONTROLS=true

:: --- Kill old processes ---
echo [0/3] Cleaning old processes...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING 2^>nul') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr LISTENING 2^>nul') do taskkill /PID %%a /F >nul 2>&1
timeout /t 2 /nobreak >nul

:: --- Backend ---
echo.
echo [1/3] Starting backend (FastAPI)...
start "SmartDesk-Backend" cmd /k "title SmartDesk-Backend && cd /d "%~dp0" && set ENABLE_DEMO_SEED=true && set ENABLE_DEMO_SEAT_API=true && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
timeout /t 4 /nobreak >nul

:: --- Frontend ---
echo.
echo [2/3] Starting frontend (Vite)...
start "SmartDesk-Frontend" cmd /k "title SmartDesk-Frontend && cd /d "%~dp0frontend" && set VITE_ENABLE_DEMO_CONTROLS=true && npm run dev -- --host 127.0.0.1"
timeout /t 4 /nobreak >nul

:: --- Launch browser ---
echo.
echo [3/3] Opening browser...
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
echo   Close this window will NOT stop processes.
echo   Close SmartDesk-Frontend / SmartDesk-Backend to stop.
echo   Or run kill.bat to stop all.
echo ==========================================
echo.

pause
