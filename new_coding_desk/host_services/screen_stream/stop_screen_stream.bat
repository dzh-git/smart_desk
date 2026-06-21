@echo off
title SmartDesk Screen Stream Stop
setlocal enabledelayedexpansion

:: ── Resolve paths ───────────────────────────────────────────────────────────
set "SD_ROOT=%~dp0..\.."
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"
set "RUNTIME_DIR=%SD_ROOT%\.smartdesk-runtime\screen-stream"

echo ==========================================
echo   Stopping SmartDesk Screen Stream...
echo ==========================================
echo.

set "KILLED=0"

:: ── Stop FFmpeg and MediaMTX via PID files ──────────────────────────────────
for %%n in (ffmpeg mediamtx) do (
    set "PID_FILE=!RUNTIME_DIR!\%%n.pid"
    if exist "!PID_FILE!" (
        for /f "usebackq tokens=1" %%p in ("!PID_FILE!") do (
            if not "%%p"=="" (
                taskkill /PID %%p /T /F >nul 2>&1
                if !ERRORLEVEL! EQU 0 (
                    echo   [OK] Killed %%n PID %%p
                    set "KILLED=1"
                ) else (
                    echo   [--] %%n PID %%p already exited
                )
            )
        )
        del "!PID_FILE!" >nul 2>&1
    ) else (
        echo   [--] No %%n.pid file found
    )
)

:: ── Port fallback for RTSP and WebRTC ───────────────────────────────────────
::   Only kills processes that listen on these ports. The command-line layer
::   in kill.bat is more specific to avoid killing unrelated FFmpeg instances.
for %%p in (8554 8889) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p " ^| findstr /c:"LISTENING" 2^>nul') do (
        taskkill /PID %%a /T /F >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo   [OK] Port %%p - killed PID %%a
            set "KILLED=1"
        )
    )
)

echo.
if "!KILLED!"=="1" (
    echo   Screen stream stopped.
) else (
    echo   No screen stream processes were running.
)
echo ==========================================

endlocal
