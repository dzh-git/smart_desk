@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\DOCTOR.ps1" %*
exit /b %ERRORLEVEL%
