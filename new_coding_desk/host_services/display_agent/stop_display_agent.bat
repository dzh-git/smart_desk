@echo off
title SmartDesk Display Agent Stop
setlocal enabledelayedexpansion

set "SD_ROOT=%~dp0..\.."
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"
set "RUNTIME_DIR=%SD_ROOT%\.smartdesk-runtime"

echo ==========================================
echo   Stopping SmartDesk Display Agent...
echo ==========================================
echo.

set "KILLED=0"

:: ── PID file ────────────────────────────────────────────────────────────────
set "PID_FILE=%RUNTIME_DIR%\display_agent.pid"
if exist "%PID_FILE%" (
    for /f "usebackq tokens=1" %%p in ("%PID_FILE%") do (
        if not "%%p"=="" (
            taskkill /PID %%p /T /F >nul 2>&1
            if !ERRORLEVEL! EQU 0 (
                echo   [OK] Killed display_agent PID %%p
                set "KILLED=1"
            )
        )
    )
    del "%PID_FILE%" >nul 2>&1
) else (
    echo   [--] No display_agent.pid file found
)

:: ── Port 8766 fallback ─────────────────────────────────────────────────────
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8766 " ^| findstr /c:"LISTENING" 2^>nul') do (
    taskkill /PID %%a /T /F >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo   [OK] Port 8766 - killed PID %%a
        set "KILLED=1"
    )
)

:: ── Window title fallback ──────────────────────────────────────────────────
taskkill /FI "WINDOWTITLE eq SmartDesk Display Agent*" /T /F >nul 2>&1

echo.
if "!KILLED!"=="1" (
    echo   Display Agent stopped.
) else (
    echo   No Display Agent processes were running.
)
echo ==========================================

endlocal
