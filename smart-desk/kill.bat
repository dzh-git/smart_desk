@echo off
title SmartDesk Killer
echo ==========================================
echo   Killing SmartDesk processes...
echo ==========================================
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R ":8000[^0-9]*$" ^| findstr LISTENING 2^>nul') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R ":5173[^0-9]*$" ^| findstr LISTENING 2^>nul') do taskkill /PID %%a /F >nul 2>&1
echo Done.
pause
