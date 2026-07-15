# 部署、状态显示与验收

## 启动顺序

1. 在中央 Windows 主机启动 `new_coding_desk/start.bat`，确认 Display Agent `GET http://127.0.0.1:8766/health` 正常。
2. 提前打开所需 PowerPoint 演示文稿和 SolidWorks 模型。
3. 打开 SmartDesk `/display` 大屏。
4. 启动 `smartdesk_gesture_controller/start_gesture.bat`。
5. 先用 `--no-mouse` 标定，再启用真实控制。

## 状态提示

状态卡和原生悬浮层显示 Camera、Hand 与 Status。应用切换中显示 `Switching Display`，失败显示 `Display Switch Failed`；详细原因在状态 WebSocket 和日志中。

## 自动测试

```powershell
.venv\Scripts\python -m pytest tests -q
```

测试不得操作真实鼠标键盘，统一使用 FakeDriver 和假的 Display Agent 客户端。

## 实机验收

- 从会议屏 I Love You 右滑，PowerPoint 在 2 秒内获得前台焦点；再次右滑返回会议屏。
- 从会议屏左滑进入 SolidWorks；再次左滑返回会议屏。
- PowerPoint 与 SolidWorks 之间按相反方向切换。
- 关闭目标应用后切换，当前窗口和内部模式保持不变，并显示明确失败。
- `presentation` 与 `presentation_pen` 间切换不重复激活 PowerPoint。
- 手离开、暂停、退出和异常后没有鼠标键或辅助键保持按下。
- Display Agent 离线时识别循环继续运行，状态显示切屏离线。
