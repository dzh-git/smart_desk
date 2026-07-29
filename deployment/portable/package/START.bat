@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\START.ps1" %*
exit /b %ERRORLEVEL%
