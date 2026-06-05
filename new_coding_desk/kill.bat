@echo off
title SmartDesk Killer
echo ==========================================
echo   Stopping SmartDesk processes...
echo ==========================================

:: Kill by window title (set by start.bat)
taskkill /FI "WINDOWTITLE eq SmartDesk-Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq SmartDesk-Frontend*" /F >nul 2>&1

:: Fallback: kill anything still listening on project ports
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1

:: Note: uvicorn runs as python.exe on Windows, so the port-based fallback
:: above (lines 12-13) is what actually catches lingering backend processes.
:: If you need to kill all python.exe, uncomment the line below carefully:
:: for /f "tokens=2" %%a in ('tasklist ^| findstr /i "python" 2^>nul') do taskkill /PID %%a /F >nul 2>&1

echo Done.
pause
