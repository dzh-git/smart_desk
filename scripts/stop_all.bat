@echo off
REM ============================================================================
REM  SmartDesk 停止脚本 (Windows)
REM  按窗口标题停止三个模块（含子进程树 /T）。
REM ============================================================================

echo [SmartDesk] 正在发送停止信号 ...

taskkill /F /T /FI "WINDOWTITLE eq SmartDesk-Backend" 2>nul
taskkill /F /T /FI "WINDOWTITLE eq SmartDesk-Frontend" 2>nul
taskkill /F /T /FI "WINDOWTITLE eq SmartDesk-Gesture" 2>nul

echo [SmartDesk] 停止信号已发送。若窗口残留，请手动关闭。
