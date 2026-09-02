@echo off
setlocal
title SmartDesk Gesture Controller (SolidWorks)

rem ==========================================
rem SolidWorks mode: start in model view mode.
rem ==========================================

set "SD_ROOT=%~dp0"
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"
for %%I in ("%SD_ROOT%\..") do set "REPO_ROOT=%%~fI"
set "VENV_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
set "PYTHONUTF8=1"

echo ==========================================
echo   SmartDesk Gesture Controller (SolidWorks)
echo ==========================================
echo.

if not exist "%VENV_PYTHON%" (
    echo   [ERROR] Virtual env not found: %VENV_PYTHON%
    echo   Run: "%REPO_ROOT%\SETUP_PYTHON.bat"
    echo   For details, see README.md in %SD_ROOT%
    echo.
    echo   Press any key to exit...
    pause >nul
    exit /b 1
)
"%VENV_PYTHON%" "%REPO_ROOT%\scripts\check_python_runtime.py" >nul
if errorlevel 1 exit /b 1

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

echo   Starting in SOLIDWORKS mode...
echo   Gestures: Open_Palm = rotate, Victory = pan, Pinch = zoom,
echo             Thumb_Up = fit, ILoveYou = isometric, Closed_Fist = exit
echo ==========================================
echo.

"%VENV_PYTHON%" -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo   [INFO] PySide6 is not installed; native overlay disabled.
    echo   Browser status card at http://127.0.0.1:8765/ remains available.
    echo   Install with: pip install PySide6
    echo.
)

cd /d "%SD_ROOT%"
"%VENV_PYTHON%" -m hands.gesture_controller --mode solidworks
set "CONTROLLER_EXIT=%ERRORLEVEL%"

echo.
echo   Gesture controller exited with code %CONTROLLER_EXIT%.
echo   Press any key to close this window...
echo ==========================================
pause >nul
exit /b %CONTROLLER_EXIT%
