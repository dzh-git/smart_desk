@echo off
title NewDesk Launcher

echo ==========================================
echo   NewDesk Backend
echo ==========================================
echo.

cd /d "%~dp0"

:: --- Kill old processes ---
echo [0/1] Cleaning old processes...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING 2^>nul') do taskkill /PID %%a /F >nul 2>&1
timeout /t 2 /nobreak >nul

:: --- Backend ---
echo.
echo [1/1] Starting backend...
start "ND-Backend" cmd /k "cd /d %~dp0 && uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul

:: --- Get IP ---
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4" ^| findstr /v "192.168.56" ^| findstr /v "172." ^| findstr /v "10."') do set IP=%%a
if defined IP set IP=%IP:~1%

:: --- Launch browser ---
timeout /t 2 /nobreak >nul
start http://localhost:8000

echo.
echo ==========================================
echo   Ready!
echo.
echo   API:   http://localhost:8000
echo   Docs:  http://localhost:8000/docs
if defined IP echo   LAN:   http://%IP%:8000
echo.
echo   Close this window will NOT stop backend.
echo   Close ND-Backend window to stop.
echo ==========================================
echo.

pause
