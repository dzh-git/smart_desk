@echo off
title SmartDesk Launcher
setlocal enabledelayedexpansion

:: ========================================
::  SmartDesk - Smart Conference Table
::  Windows startup script
:: ========================================

:: -- Project root (resolve from batch file location) ----------------------
set "SD_ROOT=%~dp0"
if "%SD_ROOT:~-1%"=="\" set "SD_ROOT=%SD_ROOT:~0,-1%"
for %%I in ("%SD_ROOT%\..") do set "REPO_ROOT=%%~fI"
set "VENV_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
set "PYTHONUTF8=1"

if not exist "%VENV_PYTHON%" (
    echo   [ERROR] SmartDesk Python environment not found: %VENV_PYTHON%
    echo   Run: "%REPO_ROOT%\SETUP_PYTHON.bat"
    pause
    exit /b 1
)
"%VENV_PYTHON%" "%REPO_ROOT%\scripts\check_python_runtime.py"
if %ERRORLEVEL% NEQ 0 (
    pause
    exit /b 1
)
set "PATH=%REPO_ROOT%\.venv\Scripts;%PATH%"

echo ========================================
echo   SmartDesk - Smart Conference Table
echo ========================================
echo.

:: -- Demo environment variables -----------------------------------------
set ENABLE_DEMO_SEED=true
set ENABLE_DEMO_SEED_WHEN_NO_ACTIVE=true
set ENABLE_DEMO_SEAT_API=true
set VITE_ENABLE_DEMO_CONTROLS=true
set ENABLE_TRANSLATION_MODEL=true
if not defined SMART_DESK_ENABLE_SPEECH_TRACE set "SMART_DESK_ENABLE_SPEECH_TRACE=true"
if not defined VITE_ENABLE_SPEECH_TRACE set "VITE_ENABLE_SPEECH_TRACE=true"
if not defined SMART_DESK_CAPTURE_SPEECH_DEBUG set "SMART_DESK_CAPTURE_SPEECH_DEBUG=false"
if not defined SMART_DESK_TORCH_THREADS set "SMART_DESK_TORCH_THREADS=4"
if not defined SMART_DESK_TORCH_INTEROP_THREADS set "SMART_DESK_TORCH_INTEROP_THREADS=1"
if not defined OMP_NUM_THREADS set "OMP_NUM_THREADS=4"
if not defined MKL_NUM_THREADS set "MKL_NUM_THREADS=4"
set "TRANSLATION_MODEL_PATH=%SD_ROOT%\models\opus-mt-zh-en"
set "TRANSLATION_ZH_EN_MODEL_PATH=%SD_ROOT%\models\opus-mt-zh-en"
set "TRANSLATION_EN_ZH_MODEL_PATH=%SD_ROOT%\models\opus-mt-en-zh"
set "BILINGUAL_ASR_MODEL_PATH=%SD_ROOT%\models\SenseVoiceSmall"
set "CHINESE_ASR_MODEL_PATH=%SD_ROOT%\models\iic\speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
if not defined ENABLE_SCREEN_STREAM set "ENABLE_SCREEN_STREAM=false"
if not defined ENABLE_DISPLAY_AGENT set "ENABLE_DISPLAY_AGENT=true"

echo   Environment:
echo     ENABLE_DEMO_SEED             = true
echo     ENABLE_DEMO_SEED_WHEN_NO_ACTIVE = true
echo     ENABLE_DEMO_SEAT_API         = true
echo     VITE_ENABLE_DEMO_CONTROLS    = true
echo     ENABLE_TRANSLATION_MODEL     = true
echo     SMART_DESK_SPEECH_TRACE      = %SMART_DESK_ENABLE_SPEECH_TRACE%
echo     VITE_SPEECH_TRACE            = %VITE_ENABLE_SPEECH_TRACE%
echo     SPEECH_DEBUG_AUDIO_CAPTURE   = %SMART_DESK_CAPTURE_SPEECH_DEBUG%
echo     TORCH_THREADS                = %SMART_DESK_TORCH_THREADS% / interop %SMART_DESK_TORCH_INTEROP_THREADS%
echo     OMP/MKL_THREADS              = %OMP_NUM_THREADS% / %MKL_NUM_THREADS%
echo     TRANSLATION_MODEL_PATH       = %TRANSLATION_MODEL_PATH%
echo     TRANSLATION_EN_ZH_MODEL_PATH = %TRANSLATION_EN_ZH_MODEL_PATH%
echo     BILINGUAL_ASR_MODEL_PATH     = %BILINGUAL_ASR_MODEL_PATH%
echo     CHINESE_ASR_MODEL_PATH       = %CHINESE_ASR_MODEL_PATH%
echo     ENABLE_SCREEN_STREAM         = %ENABLE_SCREEN_STREAM%
echo     ENABLE_DISPLAY_AGENT         = %ENABLE_DISPLAY_AGENT%
echo.

:: -- Step 0: Prepare runtime dir and clean old instances -----------------
echo [0/4] Preparing workspace...
if not exist "%SD_ROOT%\.smartdesk-runtime" mkdir "%SD_ROOT%\.smartdesk-runtime"
if exist "%SD_ROOT%\.smartdesk-runtime\backend.pid" del "%SD_ROOT%\.smartdesk-runtime\backend.pid"
if exist "%SD_ROOT%\.smartdesk-runtime\frontend.pid" del "%SD_ROOT%\.smartdesk-runtime\frontend.pid"
set "SKIP_PAUSE=1"
call "%SD_ROOT%\kill.bat"
set "SKIP_PAUSE="
%SystemRoot%\System32\timeout.exe /t 2 /nobreak >nul
echo.

:: -- Step 1: Check dependencies -------------------------------------------
echo [1/4] Checking dependencies...
echo.

:: Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] SmartDesk Python 3.11 was not added to PATH.
    pause
    exit /b 1
)
echo   Python: OK

:: Core Python packages
python -c "import fastapi, sqlalchemy, pydantic, numpy, uvicorn; print('  OK')" 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] Missing core Python packages.
    echo   Run: pip install -r "%SD_ROOT%\requirements.txt"
    pause
    exit /b 1
)

:: Arduino serial package (required because hardware is enabled in the integration config)
python -c "import serial" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] pyserial is missing; Arduino lighting cannot start.
    echo   Run: python -m pip install "pyserial^>=3.5"
    pause
    exit /b 1
)
echo   pyserial: OK

:: Speech packages (optional)
python -c "import torch, funasr, scipy, soundfile" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [WARN] Speech packages missing - streaming ASR unavailable.
    echo   Install: pip install -r "%SD_ROOT%\requirements.txt"
) else (
    echo   Speech packages: OK
)

:: Bilingual final ASR and local translation models
python -c "import transformers, sentencepiece" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [WARN] Translation packages missing - bilingual translation unavailable.
) else if not exist "%TRANSLATION_ZH_EN_MODEL_PATH%\model.safetensors" (
    echo   [WARN] Chinese-to-English model missing: %TRANSLATION_ZH_EN_MODEL_PATH%
) else if not exist "%TRANSLATION_EN_ZH_MODEL_PATH%\model.safetensors" if not exist "%TRANSLATION_EN_ZH_MODEL_PATH%\pytorch_model.bin" (
    echo   [WARN] English-to-Chinese model missing: %TRANSLATION_EN_ZH_MODEL_PATH%
) else if not exist "%BILINGUAL_ASR_MODEL_PATH%\model.pt" if not exist "%BILINGUAL_ASR_MODEL_PATH%\model.safetensors" (
    echo   [WARN] SenseVoiceSmall model missing: %BILINGUAL_ASR_MODEL_PATH%
    echo   Run: python backend\scripts\prepare_bilingual_models.py
) else if not exist "%CHINESE_ASR_MODEL_PATH%\model.pt" (
    echo   [WARN] Chinese Paraformer-large model missing: %CHINESE_ASR_MODEL_PATH%
) else (
    echo   Chinese and bilingual ASR plus translation models: OK
)

:: pydub (optional)
python -c "import pydub" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [INFO] pydub not installed - file transcoding disabled.
)

:: npm
where npm.cmd >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] npm not found.
    pause
    exit /b 1
)
echo   npm: OK

:: node_modules
if not exist "%SD_ROOT%\frontend\node_modules" (
    echo   [ERROR] frontend\node_modules not found.
    echo   Run: cd frontend ^&^& npm install
    pause
    exit /b 1
)
echo   node_modules: OK
echo.

:: -- Step 2: Start Backend -----------------------------------------------
echo [2/4] Starting backend FastAPI on http://0.0.0.0:8000 ...
echo.

powershell -NoProfile -Command ^
  "$p = Start-Process python.exe -ArgumentList '-m','uvicorn','backend.main:app','--host','0.0.0.0','--port','8000','--log-level','info' -WorkingDirectory '%SD_ROOT%' -WindowStyle Normal -PassThru -RedirectStandardOutput '%SD_ROOT%\.smartdesk-runtime\backend.stdout.log' -RedirectStandardError '%SD_ROOT%\.smartdesk-runtime\backend.stderr.log'; Start-Sleep -Milliseconds 500; if ($p -and -not $p.HasExited) { [IO.File]::WriteAllText('%SD_ROOT%\.smartdesk-runtime\backend.pid', $p.Id.ToString()) } else { Remove-Item '%SD_ROOT%\.smartdesk-runtime\backend.pid' -ErrorAction SilentlyContinue }"

if not exist "%SD_ROOT%\.smartdesk-runtime\backend.pid" (
    echo   [ERROR] Backend failed to start. Check:
    echo     %SD_ROOT%\.smartdesk-runtime\backend.stderr.log
    echo.
    echo   SmartDesk NOT started.
    pause
    exit /b 1
)

set /p BACKEND_PID=<"%SD_ROOT%\.smartdesk-runtime\backend.pid"
echo   Backend PID: %BACKEND_PID%

:: Verify backend process alive
powershell -NoProfile -Command "if (Get-Process -Id %BACKEND_PID% -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] Backend process PID=%BACKEND_PID% already exited.
    del "%SD_ROOT%\.smartdesk-runtime\backend.pid" >nul 2>&1
    echo   Check: %SD_ROOT%\.smartdesk-runtime\backend.stderr.log
    echo.
    echo   SmartDesk NOT started.
    pause
    exit /b 1
)

:: Poll port 8000 up to 30 seconds
echo   Waiting for backend on 127.0.0.1:8000 ...
set "BACKEND_OK=0"
for /L %%i in (1,1,30) do (
    if !BACKEND_OK! EQU 0 (
        powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/docs' -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop; exit 0 } catch { exit 1 }" >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            set "BACKEND_OK=1"
            echo   Backend ready after %%i seconds.
        ) else (
            powershell -NoProfile -Command "if (Get-Process -Id %BACKEND_PID% -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
            if !ERRORLEVEL! NEQ 0 (
                echo   [ERROR] Backend process died while waiting.
                del "%SD_ROOT%\.smartdesk-runtime\backend.pid" >nul 2>&1
                echo   Check: %SD_ROOT%\.smartdesk-runtime\backend.stderr.log
                echo.
                echo   SmartDesk NOT started.
                pause
                exit /b 1
            )
            <nul set /p "=."
%SystemRoot%\System32\timeout.exe /t 1 /nobreak >nul
        )
    )
)
if !BACKEND_OK! EQU 0 (
    echo.
    echo   [ERROR] Backend did not respond within 30 seconds on 127.0.0.1:8000.
    echo   Check: %SD_ROOT%\.smartdesk-runtime\backend.stderr.log
    echo.
    echo   SmartDesk NOT started.
    pause
    exit /b 1
)
echo.

:: -- Step 3: Start Frontend -----------------------------------------------
echo [3/4] Starting frontend Vite on http://0.0.0.0:5173 ...
echo.

powershell -NoProfile -Command ^
  "$p = Start-Process npm.cmd -ArgumentList 'run dev -- --host 0.0.0.0' -WorkingDirectory '%SD_ROOT%\frontend' -WindowStyle Normal -PassThru -RedirectStandardOutput '%SD_ROOT%\.smartdesk-runtime\frontend.stdout.log' -RedirectStandardError '%SD_ROOT%\.smartdesk-runtime\frontend.stderr.log'; Start-Sleep -Milliseconds 500; if ($p -and -not $p.HasExited) { [IO.File]::WriteAllText('%SD_ROOT%\.smartdesk-runtime\frontend.pid', $p.Id.ToString()) } else { Remove-Item '%SD_ROOT%\.smartdesk-runtime\frontend.pid' -ErrorAction SilentlyContinue }"

if not exist "%SD_ROOT%\.smartdesk-runtime\frontend.pid" (
    echo   [ERROR] Frontend failed to start. Check:
    echo     %SD_ROOT%\.smartdesk-runtime\frontend.stderr.log
    echo.
    echo   SmartDesk NOT started.
    pause
    exit /b 1
)

set /p FRONTEND_PID=<"%SD_ROOT%\.smartdesk-runtime\frontend.pid"
echo   Frontend PID: %FRONTEND_PID%

:: Verify frontend process alive
powershell -NoProfile -Command "if (Get-Process -Id %FRONTEND_PID% -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] Frontend process PID=%FRONTEND_PID% already exited.
    del "%SD_ROOT%\.smartdesk-runtime\frontend.pid" >nul 2>&1
    echo   Check: %SD_ROOT%\.smartdesk-runtime\frontend.stderr.log
    echo.
    echo   SmartDesk NOT started.
    pause
    exit /b 1
)

:: Poll port 5173 up to 30 seconds
echo   Waiting for frontend on 127.0.0.1:5173 ...
set "FRONTEND_OK=0"
for /L %%i in (1,1,30) do (
    if !FRONTEND_OK! EQU 0 (
        powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop; exit 0 } catch { exit 1 }" >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            set "FRONTEND_OK=1"
            echo   Frontend ready after %%i seconds.
        ) else (
            powershell -NoProfile -Command "if (Get-Process -Id %FRONTEND_PID% -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
            if !ERRORLEVEL! NEQ 0 (
                echo   [ERROR] Frontend process died while waiting.
                del "%SD_ROOT%\.smartdesk-runtime\frontend.pid" >nul 2>&1
                echo   Check: %SD_ROOT%\.smartdesk-runtime\frontend.stderr.log
                echo.
                echo   SmartDesk NOT started.
                pause
                exit /b 1
            )
            <nul set /p "=."
%SystemRoot%\System32\timeout.exe /t 1 /nobreak >nul
        )
    )
)
if !FRONTEND_OK! EQU 0 (
    echo.
    echo   [ERROR] Frontend did not respond within 30 seconds on 127.0.0.1:5173.
    echo   Check: %SD_ROOT%\.smartdesk-runtime\frontend.stderr.log
    echo.
    echo   SmartDesk NOT started.
    pause
    exit /b 1
)
echo.

:: -- Host display services -----------------------------------------------
echo [host-display] ...

:: Clean stale PID files from previous run (prevents false success)
if exist "%SD_ROOT%\.smartdesk-runtime\display_agent.pid" del "%SD_ROOT%\.smartdesk-runtime\display_agent.pid"
if exist "%SD_ROOT%\.smartdesk-runtime\screen_supervisor.pid" del "%SD_ROOT%\.smartdesk-runtime\screen_supervisor.pid"

:: Display Agent is independent from FFmpeg / MediaMTX screen streaming.
if /I "%ENABLE_DISPLAY_AGENT%"=="true" (
    echo   [display-agent] Starting on http://127.0.0.1:8766 ...
    start "SmartDesk Display Agent" /b powershell -NoProfile -Command "try { $p = Start-Process python.exe -ArgumentList 'agent.py' -WorkingDirectory '%SD_ROOT%\host_services\display_agent' -WindowStyle Hidden -PassThru -RedirectStandardOutput '%SD_ROOT%\.smartdesk-runtime\display_agent.stdout.log' -RedirectStandardError '%SD_ROOT%\.smartdesk-runtime\display_agent.stderr.log'; Start-Sleep -Milliseconds 500; try { $exited = $p.HasExited } catch { $exited = $false }; if ($p -and $p.Id -and -not $exited) { [IO.File]::WriteAllText('%SD_ROOT%\.smartdesk-runtime\display_agent.pid', $p.Id.ToString()) } } catch { $_ | Out-File -Encoding ascii '%SD_ROOT%\.smartdesk-runtime\display_agent.stderr.log'; Remove-Item '%SD_ROOT%\.smartdesk-runtime\display_agent.pid' -ErrorAction SilentlyContinue }"
    %SystemRoot%\System32\timeout.exe /t 1 /nobreak >nul
) else (
    echo   [display-agent] Disabled: ENABLE_DISPLAY_AGENT is not true.
)

:: Binary availability flags (set before any block so %var% is set at parse time)
set "SCREEN_STREAM_READY=1"
if /I "%ENABLE_SCREEN_STREAM%"=="true" if not exist "%SD_ROOT%\tools\ffmpeg\bin\ffmpeg.exe" set "SCREEN_STREAM_READY=0"
if /I "%ENABLE_SCREEN_STREAM%"=="true" if not exist "%SD_ROOT%\tools\mediamtx\mediamtx.exe" set "SCREEN_STREAM_READY=0"

:: Supervisor pre-check -- validates config, binaries, encoder before starting
if /I "%ENABLE_SCREEN_STREAM%"=="true" if %SCREEN_STREAM_READY% EQU 1 (
    echo   [screen-stream] Running supervisor pre-check ...
    python "%SD_ROOT%\host_services\screen_stream\supervisor.py" --check
    if errorlevel 1 (
        echo   [screen-stream] [ERROR] Supervisor pre-check failed.
        echo   [screen-stream] Screen stream NOT started -- fix errors above and retry.
        set "SCREEN_STREAM_READY=0"
    )
)

if /I "%ENABLE_SCREEN_STREAM%"=="true" (
    if %SCREEN_STREAM_READY% EQU 1 (
        echo   [screen-stream] Starting Screen Supervisor ...
        start "SmartDesk Screen Supervisor" /b powershell -NoProfile -Command "try { $p = Start-Process python.exe -ArgumentList 'supervisor.py' -WorkingDirectory '%SD_ROOT%\host_services\screen_stream' -WindowStyle Hidden -PassThru -RedirectStandardOutput '%SD_ROOT%\.smartdesk-runtime\screen_supervisor.stdout.log' -RedirectStandardError '%SD_ROOT%\.smartdesk-runtime\screen_supervisor.stderr.log'; Start-Sleep -Milliseconds 500; try { $exited = $p.HasExited } catch { $exited = $false }; if ($p -and $p.Id -and -not $exited) { [IO.File]::WriteAllText('%SD_ROOT%\.smartdesk-runtime\screen_supervisor.pid', $p.Id.ToString()) } } catch { $_ | Out-File -Encoding ascii '%SD_ROOT%\.smartdesk-runtime\screen_supervisor.stderr.log'; Remove-Item '%SD_ROOT%\.smartdesk-runtime\screen_supervisor.pid' -ErrorAction SilentlyContinue }"
        %SystemRoot%\System32\timeout.exe /t 1 /nobreak >nul
    ) else (
        if %SCREEN_STREAM_READY% EQU 0 (
            echo   [screen-stream] [ERROR] Required screen-stream binaries not found
            if not exist "%SD_ROOT%\tools\ffmpeg\bin\ffmpeg.exe" (
                echo   [screen-stream]   Missing: tools\ffmpeg\bin\ffmpeg.exe
            )
            if not exist "%SD_ROOT%\tools\mediamtx\mediamtx.exe" (
                echo   [screen-stream]   Missing: tools\mediamtx\mediamtx.exe
            )
        )
        echo   [screen-stream] Screen stream NOT started
    )
) else (
    echo   [screen-stream] Screen Stream disabled: ENABLE_SCREEN_STREAM is not true.
)

:: PID verification -- actually checks process is alive with Get-Process
if /I "%ENABLE_DISPLAY_AGENT%"=="true" (
    if exist "%SD_ROOT%\.smartdesk-runtime\display_agent.pid" (
        for /f "usebackq delims=" %%p in ("%SD_ROOT%\.smartdesk-runtime\display_agent.pid") do (
            powershell -NoProfile -Command "if (Get-Process -Id %%p -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
            if errorlevel 1 (
                del "%SD_ROOT%\.smartdesk-runtime\display_agent.pid"
                echo   [display-agent] [ERROR] PID=%%p exited -- check .smartdesk-runtime\display_agent.stderr.log
            ) else (
                echo   [display-agent] Running PID=%%p
            )
        )
    ) else (
        echo   [display-agent] [ERROR] Not running -- check .smartdesk-runtime\display_agent.stderr.log
    )
)

if /I "%ENABLE_SCREEN_STREAM%"=="true" if %SCREEN_STREAM_READY% EQU 1 (
    if exist "%SD_ROOT%\.smartdesk-runtime\screen_supervisor.pid" (
        for /f "usebackq delims=" %%p in ("%SD_ROOT%\.smartdesk-runtime\screen_supervisor.pid") do (
            powershell -NoProfile -Command "if (Get-Process -Id %%p -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
            if errorlevel 1 (
                del "%SD_ROOT%\.smartdesk-runtime\screen_supervisor.pid"
                echo   [screen-stream] [ERROR] Screen Supervisor PID=%%p exited -- check .smartdesk-runtime\screen_supervisor.stderr.log
            ) else (
                echo   [screen-stream] Screen Supervisor running PID=%%p
            )
        )
    ) else (
        echo   [screen-stream] [ERROR] Screen Supervisor not running -- check .smartdesk-runtime\screen_supervisor.stderr.log
    )
)
echo.

:: -- Step 4: Open browser --------------------------------------------------
echo [4/4] Opening browser ...
powershell -NoProfile -Command "Start-Process 'http://127.0.0.1:5173'"
echo.

echo ========================================
echo   SmartDesk started successfully!
echo.
echo   Frontend: http://127.0.0.1:5173
echo   API:      http://127.0.0.1:8000
echo   Docs:     http://127.0.0.1:8000/docs
echo.
echo   Demo controls enabled.
echo.
echo   Close this window will NOT stop processes.
echo   Run kill.bat to stop all.
echo ========================================
echo.

pause
endlocal
exit /b 0
