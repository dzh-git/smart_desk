@echo off
chcp 65001 >nul
title SmartDesk 新平板一键部署
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\DEPLOY_TABLET.ps1"
set "SMARTDESK_DEPLOY_EXIT=%ERRORLEVEL%"
echo.
if not "%SMARTDESK_DEPLOY_EXIT%"=="0" echo 部署未完成，请保留本窗口中的错误信息。
pause
exit /b %SMARTDESK_DEPLOY_EXIT%
