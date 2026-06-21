@echo off
title SmartDesk Killer
setlocal enabledelayedexpansion

:: -- Resolve project root -------------------------------------------------
if not defined SD_ROOT (
    set "SD_ROOT=%~dp0"
    if "!SD_ROOT:~-1!"=="\" set "SD_ROOT=!SD_ROOT:~0,-1!"
)
set "RUNTIME_DIR=%SD_ROOT%\.smartdesk-runtime"

echo ========================================
echo   Stopping SmartDesk processes...
echo ========================================
echo.

set /a "COUNT=0"
set /a "KILLED=0"

:: -----------------------------------------------------------------------
:: LAYER 1 -- PID file
::   Reads backend.pid / frontend.pid and taskkill /PID /T /F
::   /T kills the entire tree: cmd.exe wrapper + child python/node
:: -----------------------------------------------------------------------
echo  [1/4] PID File

for %%f in (backend frontend display_agent screen_supervisor) do (
    set "PID_FILE=!RUNTIME_DIR!\%%f.pid"
    if exist "!PID_FILE!" (
        for /f "usebackq tokens=1" %%p in ("!PID_FILE!") do (
            if not "%%p"=="" (
                taskkill /PID %%p /T /F >nul 2>&1
                if !ERRORLEVEL! EQU 0 (
                    echo    [OK] Killed %%f PID %%p
                    set /a "COUNT+=1"
                    set "KILLED=1"
                ) else (
                    echo    [--] %%f PID %%p already exited
                )
            )
        )
        del "!PID_FILE!" >nul 2>&1
    ) else (
        echo    [--] No %%f.pid file found
    )
)
echo.

:: -----------------------------------------------------------------------
:: LAYER 2 -- Command line (WMI)
::   Uses PowerShell Get-CimInstance to find cmd.exe processes with
::   "SmartDesk" in their /k argument.
:: -----------------------------------------------------------------------
echo  [2/4] Command Line
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter ""name='cmd.exe' AND commandline LIKE '%%SmartDesk%%'"" -ErrorAction SilentlyContinue | ForEach-Object { & taskkill /PID $_.ProcessId /T /F }" >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    echo    [OK] Killed SmartDesk-related cmd.exe windows
    set /a "COUNT+=1"
    set "KILLED=1"
) else (
    echo    [--] No SmartDesk cmd.exe windows found by command line
)
echo.

:: -----------------------------------------------------------------------
:: LAYER 3 -- Port
::   Kills any orphaned python/node processes still LISTENING on ports
:: -----------------------------------------------------------------------
echo  [3/4] Port
for %%p in (8000 5173 8766 8889) do (
    set "FREED=0"
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p " ^| findstr /c:"LISTENING" 2^>nul') do (
        taskkill /PID %%a /T /F >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo    [OK] Port %%p - killed PID %%a
            set /a "COUNT+=1"
            set "FREED=1"
            set "KILLED=1"
        )
    )
    if !FREED! EQU 0 (
        echo    [--] Port %%p is already free
    )
)
echo.

:: -----------------------------------------------------------------------
:: LAYER 4 -- Window title
::   Best-effort fallback for orphaned windows
:: -----------------------------------------------------------------------
echo  [4/4] Window Title
for %%t in ("SmartDesk Backend*" "SmartDesk Frontend*" "SmartDesk-Backend*" "SmartDesk-Frontend*" "SmartDesk Launcher*") do (
    taskkill /FI "WINDOWTITLE eq %%~t" /T /F >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo    [OK] Closed %%~t
        set /a "COUNT+=1"
        set "KILLED=1"
    )
)
echo.

:: -----------------------------------------------------------------------
:: Summary
:: -----------------------------------------------------------------------
echo ========================================
if !KILLED! EQU 1 (
    echo   Cleanup complete: !COUNT! process^(es^) terminated.
) else (
    echo   No SmartDesk processes were running.
)
echo ========================================

:: -- End ------------------------------------------------------------------
if not defined SKIP_PAUSE (
    echo.
    echo   This window will close automatically in 5 seconds.
    %SystemRoot%\System32\timeout.exe /t 5 /nobreak >nul
)
endlocal
