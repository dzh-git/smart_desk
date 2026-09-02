@echo off
setlocal
set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
set "PIO_PYTHON=%REPO_ROOT%\.tools\platformio-venv\Scripts\python.exe"
set "PIO_EXE=%REPO_ROOT%\.tools\platformio-venv\Scripts\pio.exe"
set "PYTHONUTF8=1"
set "PLATFORMIO_CORE_DIR=%REPO_ROOT%\.tools\platformio-core"

if not exist "%PIO_EXE%" (
    echo   [ERROR] PlatformIO environment not found.
    echo   Run: "%REPO_ROOT%\SETUP_PYTHON.bat"
    exit /b 1
)
"%PIO_PYTHON%" "%REPO_ROOT%\scripts\check_python_runtime.py" >nul
if errorlevel 1 exit /b 1
"%PIO_EXE%" %*
exit /b %ERRORLEVEL%
