@echo off
title SmartDesk Screen Stream Supervisor
setlocal

:: ── Resolve paths ───────────────────────────────────────────────────────────
set "SD_ROOT=%~dp0..\.."
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"
for %%I in ("%SD_ROOT%\..") do set "REPO_ROOT=%%~fI"
set "VENV_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if defined SMARTDESK_PYTHON set "VENV_PYTHON=%SMARTDESK_PYTHON%"
set "PYTHON_GATE=%REPO_ROOT%\scripts\check_python_runtime.py"
if defined SMARTDESK_PYTHON_GATE set "PYTHON_GATE=%SMARTDESK_PYTHON_GATE%"
set "PYTHONUTF8=1"
set "SCREEN_STREAM_DIR=%SD_ROOT%\host_services\screen_stream"
set "RUNTIME_DIR=%SD_ROOT%\.smartdesk-runtime\screen-stream"

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"

echo ==========================================
echo   SmartDesk Screen Stream
echo ==========================================
echo.

if not exist "%VENV_PYTHON%" (
    echo   [ERROR] SmartDesk Python environment not found: %VENV_PYTHON%
    echo   Run: "%REPO_ROOT%\SETUP_PYTHON.bat"
    pause
    exit /b 1
)
"%VENV_PYTHON%" "%PYTHON_GATE%" >nul
if errorlevel 1 exit /b 1

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
"%VENV_PYTHON%" supervisor.py
endlocal
