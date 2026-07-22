@echo off
setlocal
cd /d "%~dp0.."
set "GRAPHIFY_NO_BACKUP=1"
graphify update . %*
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%
