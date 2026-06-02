@echo off
title NewDesk Killer
echo ==========================================
echo   Killing NewDesk processes...
echo ==========================================

:: Kill by window title (set by start.bat "ND-Backend")
:: This only kills THIS project's processes, never unrelated ones.
taskkill /FI "WINDOWTITLE eq ND-Backend*" /F >nul 2>&1

:: Fallback: kill anything still listening on project port
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1

echo Done.
pause
