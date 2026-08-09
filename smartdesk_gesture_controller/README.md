# SmartDesk Gesture Controller

中央 Windows 主机上的独立手势控制进程。摄像头识别和模式状态机在本目录运行；Windows 应用切换复用主程序的 Display Agent，不复制 Win32 实现。

## 启动

```powershell
Set-Location ..
.\SETUP_PYTHON.bat
Set-Location smartdesk_gesture_controller
.\start_gesture.bat
```

需要提前放置 `hand_landmarker.task` 和 `gesture_recognizer.task`。安全标定可使用：

```powershell
..\.venv\Scripts\python.exe -m hands.gesture_controller --no-mouse
```

常用控制：`Ctrl+Alt+G` 暂停/恢复，`Ctrl+Alt+Q` 紧急退出，调试窗口内可用 `p`/空格和 `q`/Esc。

## 大屏应用切换

- I Love You 右滑：会议屏 → PowerPoint；PowerPoint → 会议屏；SolidWorks → PowerPoint。
- I Love You 左滑：会议屏 → SolidWorks；SolidWorks → 会议屏；PowerPoint → SolidWorks。
- PowerPoint 与 SolidWorks 必须提前打开；未打开时保持当前窗口和模式，并显示切换失败。
- Display Agent 默认地址为 `http://127.0.0.1:8766`。不可用时手势识别继续运行，但切屏功能离线。

## 当前规范

- [手势、模式与应用映射](docs/GESTURE_AND_DISPLAY_SPEC.md)
- [配置与状态接口](docs/CONFIG_AND_STATUS_SPEC.md)
- [部署与验收](docs/OPERATIONS_AND_ACCEPTANCE.md)

## 测试

```powershell
..\.venv\Scripts\python.exe -m pytest tests -q
```
