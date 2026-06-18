# SmartDesk Gesture Controller

这是一个独立的 Windows 本地手势控制程序，用摄像头识别手势，并通过 `pyautogui` 模拟鼠标、键盘操作，用于控制中央主机上的 `/display` 大屏、PPT、SolidWorks 或其他桌面程序。

它不属于 SmartDesk 前端、FastAPI 后端或语音识别模块。它只需要和会议桌系统同时运行在中央主机上。

## 目录结构

```text
smartdesk_gesture_controller/
  hands/
    gesture_config.py        # 配置与 CLI 参数
    gesture_actions.py       # pyautogui 动作层 + FakeDriver 测试驱动
    gesture_state.py         # 手势模式状态机
    gesture_recognition.py   # MediaPipe 手势识别与分类
    gesture_status_server.py # 本地状态广播 ws://127.0.0.1:8765
    gesture_controller.py    # 主循环入口
  tests/
    test_gesture_*.py
  requirements.txt
  start_gesture.bat
  README.md
```

## 安装

在 Windows 中进入本目录：

```bat
cd /d D:\Ai_project\smart_desktop\smartdesk_gesture_controller
pip install -r requirements.txt
```

如果只运行单元测试，仍建议安装 `pytest`。真实摄像头控制需要 `mediapipe`、`opencv-python`、`pyautogui`、`pynput` 等依赖。

## 启动方式

### 1. 安全 dry-run 验证

只识别手势，不控制系统鼠标键盘：

```bat
python -m hands.gesture_controller --no-mouse
```

### 2. 正式启动

默认启动后处于暂停/standby，需要按 `Ctrl+Alt+G` 恢复控制：

```bat
python -m hands.gesture_controller
```

### 3. 使用启动脚本

```bat
start_gesture.bat
```

### 4. 指定模式

PPT / 浏览器翻页：

```bat
python -m hands.gesture_controller --mode presentation
```

通用鼠标控制：

```bat
python -m hands.gesture_controller --mode mouse
```

### 5. 常用参数

```text
--camera N             指定摄像头编号，默认 0
--mode presentation    启用后进入演示翻页模式
--mode mouse           启用后进入鼠标控制模式
--no-mouse             dry-run，不控制系统鼠标键盘
--no-debug             不显示 OpenCV 调试窗口
--no-server            不启动 ws://127.0.0.1:8765 状态广播
--no-pause-on-start    启动后直接激活，不等待 Ctrl+Alt+G
```

## 停止方式

优先使用：

```text
Ctrl+Alt+Q   紧急退出，释放鼠标后退出
q            在调试窗口中退出
Ctrl+C       在启动终端中停止进程
```

如果鼠标处于拖动状态，退出流程会调用 `release_all()`，避免鼠标左键长期按住。

## 手势映射

### presentation 模式

```text
张开手掌向右挥动：下一页 / right
张开手掌向左挥动：上一页 / left
握拳：回到 standby
```

### mouse 模式

```text
单指：移动鼠标
拇指 + 食指捏合：左键点击
双指：拖动 / 画笔模式，触发 Ctrl+P + mouseDown
拖动中握拳：mouseUp + 退出拖动模式
握拳：回到 standby
```

SolidWorks 专用模式当前只预留枚举，尚未实现专用右键/中键映射。SolidWorks 目前可先用 mouse 模式进行基础点击、拖动验证。

## 本地状态广播

程序默认启动：

```text
ws://127.0.0.1:8765
```

广播内容示例：

```json
{
  "mode": "mouse",
  "gesture": "single_finger",
  "action": "Single-finger mouse",
  "camera_ok": true,
  "control_enabled": true,
  "paused": false,
  "fps": 29.4,
  "connected_clients": 0,
  "timestamp": 1718600000.0
}
```

这个接口只用于未来大屏显示手势状态；不控制 SmartDesk 业务。

## 测试

```bat
python -m pytest tests -q
```

当前测试不需要真实摄像头，不会控制系统鼠标。

## 与 SmartDesk 主项目的关系

- 不修改 SmartDesk 前端。
- 不修改 SmartDesk FastAPI 后端。
- 不修改 WebSocket 业务协议。
- 不依赖会议、投票、字幕、语音识别功能。
- 作为独立 Windows 本地进程运行。

推荐部署方式：会议桌系统正常启动后，另开一个终端或双击 `start_gesture.bat` 启动本程序。