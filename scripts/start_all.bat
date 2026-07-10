@echo off
REM ============================================================================
REM  SmartDesk 一体启动脚本 (Windows)
REM  并行启动三个模块，每个模块在独立的 cmd 窗口运行：
REM    1) 后端   FastAPI (uvicorn)         -> http://localhost:8000
REM    2) 前端   Vite dev server           -> http://localhost:5173
REM    3) 手势   gesture_controller        -> ws://127.0.0.1:8765
REM  窗口标题统一以 "SmartDesk-" 前缀命名，便于 stop_all.bat 精准停止。
REM ============================================================================

setlocal
set "ROOT=%~dp0.."
set "PY=python"

echo [SmartDesk] 正在启动模块 (ROOT=%ROOT%) ...

REM 1) 后端
start "SmartDesk-Backend" cmd /k "cd /d %ROOT%\new_coding_desk && %PY% -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"

REM 2) 前端
start "SmartDesk-Frontend" cmd /k "cd /d %ROOT%\new_coding_desk\frontend && npm run dev"

REM 3) 手势控制器（依赖摄像头；无摄像头环境可注释此行）
start "SmartDesk-Gesture" cmd /k "cd /d %ROOT%\smartdesk_gesture_controller && %PY% -m hands.gesture_controller"

echo [SmartDesk] 已全部启动。关闭对应窗口或运行 stop_all.bat 停止。
echo [SmartDesk] 后端 API 文档: http://localhost:8000/docs
echo [SmartDesk] 前端管理端:   http://localhost:5173/admin
endlocal
