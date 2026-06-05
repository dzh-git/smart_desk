@echo off
title SmartDesk Killer
echo ==========================================
echo   Stopping SmartDesk processes...
echo ==========================================

:: Kill by window title (set by start.bat)
taskkill /FI "WINDOWTITLE eq SmartDesk-Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq SmartDesk-Frontend*" /F >nul 2>&1

:: Fallback: kill anything still listening on project ports.
:: This is the primary mechanism on Windows since uvicorn runs as
:: python.exe and is not matched by WINDOWTITLE after the window
:: is closed manually.
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING" 2^>nul') do taskkill /PID %%a /F >nul 2>&1

echo.
echo   Ports 8000 and 5173 should now be free.
echo   If uvicorn is still running (python.exe), close the
echo   SmartDesk-Backend / SmartDesk-Frontend console windows
echo   manually, or kill python.exe via Task Manager.
echo.
echo Done.
pause
