@echo off
setlocal
title SmartDesk Gesture Controller (Dry-Run)

rem ==========================================
rem Dry-run mode: recognize gestures, display
rem debug info, but do NOT control mouse/keyboard.
rem Use this for on-site calibration and testing.
rem ==========================================

set "SD_ROOT=%~dp0"
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"
set "VENV_PYTHON=%SD_ROOT%\.venv\Scripts\python.exe"

echo ==========================================
echo   SmartDesk Gesture Controller (DRY-RUN)
echo ==========================================
echo.

if not exist "%VENV_PYTHON%" (
    echo   [ERROR] Virtual env not found: %VENV_PYTHON%
    echo   Create it with:  python -m venv "%SD_ROOT%\.venv"
    echo   Then install:    "%SD_ROOT%\.venv\Scripts\pip.exe" install -r "%SD_ROOT%\requirements.txt"
    echo   For details, see README.md in %SD_ROOT%
    echo.
    echo   Press any key to exit...
    pause >nul
    exit /b 1
)
echo   Python: %VENV_PYTHON%

rem Check model file exists.
if not exist "%SD_ROOT%\hand_landmarker.task" (
    echo   [ERROR] Model file not found: hand_landmarker.task
    echo   Please place the model file in the project root before running.
    echo   Expected path: %SD_ROOT%\hand_landmarker.task
    echo   Do not rely on a network download at the demo site.
    echo   For details, see README.md and docs/DEPLOYMENT_RUNBOOK.md.
    echo.
    echo   Press any key to exit...
    pause >nul
    exit /b 1
)

echo.
echo   Starting in DRY-RUN mode (no system mouse/keyboard control)...
echo   Hotkeys:
echo     Ctrl+Alt+G  = pause / resume
echo     Ctrl+Alt+Q  = emergency exit
echo     q (in debug window) = quit
echo ==========================================
echo.

cd /d "%SD_ROOT%"
"%VENV_PYTHON%" -m hands.gesture_controller --no-mouse
set "CONTROLLER_EXIT=%ERRORLEVEL%"

echo.
echo   Gesture controller exited with code %CONTROLLER_EXIT%.
echo   Press any key to close this window...
echo ==========================================
pause >nul
exit /b %CONTROLLER_EXIT%