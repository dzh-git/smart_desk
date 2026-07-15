# 手势、模式与应用切换规范

## 处理链路

```text
Camera → HandRecognizer → GestureIntentTracker → GestureState
       → ActionLayer（鼠标/键盘）
       → DisplayAgentClient → Display Agent（应用窗口）
```

状态机保持纯逻辑；控制器只在 I Love You 模式滑动产生跨应用模式变化时调用 Display Agent。切换前执行安全释放，切换失败恢复原模式。

## 应用与模式

| 模式 | 前台应用 |
|---|---|
| `standby` | SmartDesk Chrome/Edge 会议大屏 |
| `presentation`、`presentation_pen` | PowerPoint |
| `solidworks` | SolidWorks |

I Love You 方向规则：

| 当前模式 | 右滑 | 左滑 |
|---|---|---|
| `standby` | `presentation` / PowerPoint | `solidworks` / SolidWorks |
| `presentation` | `standby` / SmartDesk | `solidworks` / SolidWorks |
| `solidworks` | `presentation` / PowerPoint | `standby` / SmartDesk |

静止的 I Love You 不切换。识别需满足稳定帧、方向一致性、位移阈值与 `mode_switch_cooldown`。

## 模式内手势

| 模式 | 手势 | 行为 |
|---|---|---|
| `presentation` | Open Palm 左右滑 | 上一页/下一页 |
| `presentation` | Victory 保持 | 进入画笔模式 |
| `presentation_pen` | Pointing Up / PINCH | 移动画笔 / 绘制 |
| `solidworks` | Open Palm 移动 | 旋转 |
| `solidworks` | Victory 移动 | 平移 |
| `solidworks` | PINCH 距离变化 | 缩放 |
| 活动模式 | Closed Fist 保持 | 安全释放并退出 |

任何手丢失、暂停、退出或异常路径必须执行 `release_all`。手势模块不得直接访问会议数据库或会议业务 WebSocket。
