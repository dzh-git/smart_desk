set MEDIAPIPE_DISABLE_GPU_USAGE_REPORTING=1
set GLOG_minloglevel=2
@echo off
setlocal
title SmartDesk Gesture Controller

rem Resolve the project root from this batch file's location.
set "SD_ROOT=%~dp0"
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"
set "VENV_PYTHON=%SD_ROOT%\.venv\Scripts\python.exe"

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

rem Check model file exists (spec section 5: no network at demo site).
if not exist "%SD_ROOT%\hand_landmarker.task" (
    echo   [ERROR] Model file not found: hand_landmarker.task
    echo   Please place the model file in the project root before running the demo.
    echo   Expected path: %SD_ROOT%\hand_landmarker.task
    echo   Do not rely on a network download at the demo site.
    echo   For details, see README.md and docs/DEPLOYMENT_RUNBOOK.md.
    echo.
    echo   Press any key to exit...
    pause >nul
    exit /b 1
)

"%VENV_PYTHON%" -c "import mediapipe, cv2, pyautogui, pynput, websockets" 2>nul
if errorlevel 1 (
    echo   [WARN] Some gesture-control packages are missing.
    echo   Run: "%SD_ROOT%\.venv\Scripts\pip.exe" install -r "%SD_ROOT%\requirements.txt"
    echo   Continuing anyway; some features may be unavailable.
)

"%VENV_PYTHON%" -c "import win32gui" >nul 2>&1
if errorlevel 1 (
    echo   [INFO] pywin32 is not installed; the debug window will not stay on top.
)

cd /d "%SD_ROOT%"
"%VENV_PYTHON%" -m hands.gesture_controller %*
set "CONTROLLER_EXIT=%ERRORLEVEL%"

if %CONTROLLER_EXIT% neq 0 (
    echo.
    echo   [ERROR] Gesture controller exited with code %CONTROLLER_EXIT%.
    echo   Check logs for details.
    echo   Press any key to close this window...
    pause >nul
)

exit /b %CONTROLLER_EXIT%
