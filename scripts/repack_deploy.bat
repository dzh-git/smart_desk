@echo off
:: 重新打包部署包：从源仓库 new_coding_desk 生成 smart_desk_devided
:: 用法：双击本文件，或命令行运行 scripts\repack_deploy.bat
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0repack_deploy.ps1" %*
echo.
pause
