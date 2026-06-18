@echo off
setlocal
title SmartDesk Gesture Controller

rem ==========================================
rem SmartDesk Gesture Controller Launcher
rem Standalone process, not part of start.bat
rem Requires Windows, a camera, and packages from requirements.txt
rem ==========================================

rem Resolve the project root from this batch file's location.
set "SD_ROOT=%~dp0"
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"
set "VENV_PYTHON=%SD_ROOT%\.venv\Scripts\python.exe"

echo ==========================================
echo   SmartDesk Gesture Controller
echo ==========================================
echo.

if not exist "%VENV_PYTHON%" (
    echo   [ERROR] Virtual env not found: %VENV_PYTHON%
    echo   Run: python -m venv "%SD_ROOT%\.venv"
    echo   Then: "%SD_ROOT%\.venv\Scripts\pip.exe" install -r "%SD_ROOT%\requirements.txt"
    pause
    exit /b 1
)
echo   Python: %VENV_PYTHON%

rem Check required packages, but let the controller report runtime errors.
echo   Checking gesture-control dependencies...
"%VENV_PYTHON%" -c "import mediapipe, cv2, pyautogui, pynput, websockets; print('  All gesture deps: OK')" 2>&1
if errorlevel 1 (
    echo   [WARN] Some gesture-control packages are missing.
    echo   Run: "%SD_ROOT%\.venv\Scripts\pip.exe" install -r "%SD_ROOT%\requirements.txt"
    echo   Continuing anyway; some features may be unavailable.
)

"%VENV_PYTHON%" -c "import win32gui" >nul 2>&1
if errorlevel 1 (
    echo   [INFO] pywin32 is not installed; the debug window will not stay on top.
)
echo.

echo   Starting: .venv\Scripts\python.exe -m hands.gesture_controller %*
echo.
echo   Hotkeys:
echo     Ctrl+Alt+G  = pause / resume
echo     Ctrl+Alt+Q  = emergency exit
echo     q (in debug window) = quit
echo.
echo   Close this window or press Ctrl+C to stop the controller.
echo ==========================================
echo.

cd /d "%SD_ROOT%"
"%VENV_PYTHON%" -m hands.gesture_controller %*
set "CONTROLLER_EXIT=%ERRORLEVEL%"

echo.
echo ==========================================
echo   Gesture controller exited with code %CONTROLLER_EXIT%.
echo ==========================================
pause
exit /b %CONTROLLER_EXIT%
