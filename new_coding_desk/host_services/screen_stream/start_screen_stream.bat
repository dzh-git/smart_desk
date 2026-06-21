@echo off
title SmartDesk Screen Stream Supervisor
setlocal

:: ── Resolve paths ───────────────────────────────────────────────────────────
set "SD_ROOT=%~dp0..\.."
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"
set "SCREEN_STREAM_DIR=%SD_ROOT%\host_services\screen_stream"
set "RUNTIME_DIR=%SD_ROOT%\.smartdesk-runtime\screen-stream"

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"

echo ==========================================
echo   SmartDesk Screen Stream
echo ==========================================
echo.

:: ── Verify FFmpeg binary ────────────────────────────────────────────────────
if not exist "%SD_ROOT%\tools\ffmpeg\bin\ffmpeg.exe" (
    echo   [ERROR] FFmpeg not found: tools\ffmpeg\bin\ffmpeg.exe
    echo   Place FFmpeg binary at the above path. See README.md.
    pause
    exit /b 1
)
echo   FFmpeg: OK

:: ── Verify MediaMTX binary ──────────────────────────────────────────────────
if not exist "%SD_ROOT%\tools\mediamtx\mediamtx.exe" (
    echo   [ERROR] MediaMTX not found: tools\mediamtx\mediamtx.exe
    echo   Place MediaMTX binary at the above path. See README.md.
    pause
    exit /b 1
)
echo   MediaMTX: OK
echo.

:: ── Start supervisor (current user session, foreground) ─────────────────────
echo   Starting screen stream supervisor...
echo.
cd /d "%SCREEN_STREAM_DIR%"
python supervisor.py
endlocal
