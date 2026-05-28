@echo off
title SmartDesk Killer
echo ==========================================
echo   Killing SmartDesk processes...
echo ==========================================

:: Kill by window title (set by start.bat "SD-Backend" / "SD-Frontend")
:: This only kills THIS project's processes, never unrelated ones.
taskkill /FI "WINDOWTITLE eq SD-Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq SD-Frontend*" /F >nul 2>&1

:: Fallback: kill anything still listening on project ports
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1

echo Done.
pause
