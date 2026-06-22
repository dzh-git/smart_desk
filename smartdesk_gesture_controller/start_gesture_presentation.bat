@echo off
setlocal
title SmartDesk Gesture Controller (Presentation)

rem ==========================================
rem Presentation mode: start in PPT demo mode.
rem ==========================================

set "SD_ROOT=%~dp0"
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"
set "VENV_PYTHON=%SD_ROOT%\.venv\Scripts\python.exe"

echo ==========================================
echo   SmartDesk Gesture Controller (Presentation)
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

echo   Starting in PRESENTATION mode...
echo   Gestures: Thumb_Up hold = start PPT, Open_Palm swipe = pages,
echo             Victory hold = pen, Closed_Fist = exit
echo ==========================================
echo.

cd /d "%SD_ROOT%"
"%VENV_PYTHON%" -m hands.gesture_controller --mode presentation
set "CONTROLLER_EXIT=%ERRORLEVEL%"

echo.
echo   Gesture controller exited with code %CONTROLLER_EXIT%.
echo   Press any key to close this window...
echo ==========================================
pause >nul
exit /b %CONTROLLER_EXIT%