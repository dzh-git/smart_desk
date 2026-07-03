# SmartDesk 设备状态卡设计规范

## 1. 设计结论

建议为 PPT 手势控制添加一张 **Device Status Card（设备状态卡）**，而不是传统 HUD、Toast 或弹窗。

核心原则：

> 设备持续告诉操作者："我现在是否可用、是否看见手、是否正在执行。"

状态卡只回答操作者最关心的三个问题：

1. 摄像头是否工作？
2. 程序有没有拍到手？
3. 当前能不能翻页，或刚刚执行了什么动作？

不要展示教程、快捷键说明、调试参数、置信度、坐标、FPS、手势内部阶段等信息。这些属于调试面板，不属于现场操作者界面。

---

## 2. 放置位置

### 推荐位置

状态卡固定放在主界面的 **右上角**。

原因：

- 不遮挡 PPT 页面主体内容。
- 操作者扫视成本低，符合设备状态面板的习惯。
- 右上角适合承载"系统当前状态"，不会被误认为是主要操作区域。

### 边距与尺寸

```text
position: fixed
top: 24px
right: 24px
width: 300px
min-height: 132px
z-index: 50
```

移动端或窄窗口：

```text
left: 16px
right: 16px
top: 16px
width: auto
```

如果界面已有右侧控制栏，则状态卡应放在该栏顶部，作为"设备状态"模块，不再悬浮。

---

## 3. 信息架构

状态卡只展示三层信息。

```text
┌────────────────────────────────────┐
│ ◉ 手势控制                         │
│   Gesture Controller               │
│────────────────────────────────────│
│ Camera              Online         │
│ Hand                Detected       │
│ Status              Ready to Flip  │
└────────────────────────────────────┘
```

### Header

标题：

```text
手势控制
Gesture Controller
```

图标建议使用 `lucide-react`：

```text
Radar
```

`Radar` 比 `Hand` 更适合，因为它表达的是"持续感知中的设备"，而不是某一个具体手势。

### Row 1: Camera

用于说明摄像头链路是否可用。

| 原始数据            | 显示文本    | 颜色          |
| ------------------- | ----------- | ------------- |
| `camera_ok=true`  | `Online`  | `techGreen` |
| `camera_ok=false` | `Offline` | `techRose`  |

### Row 2: Hand

用于解决当前最大误解："没有拍到手，但操作者以为程序故障"。

| 条件                                                              | 显示文本        | 颜色          |
| ----------------------------------------------------------------- | --------------- | ------------- |
| 摄像头离线                                                        | `Unavailable` | `techMuted` |
| 摄像头在线，尚未检测到手                                          | `Searching`   | `techAmber` |
| `gesture` 不是 `none`，或状态快照能确认 `hand_present=true` | `Detected`    | `techGreen` |
| 手丢失超过`hand_loss_timeout` 后                                | `Lost`        | `techRose`  |

如果当前状态服务器暂时没有 `hand_present` 字段，第一版可以用 `gesture !== "none"` 近似判断 `Detected`，但推荐实现时补充广播 `hand_present`，避免把"看到手但分类失败"误判为 `Searching`。

### Row 3: Status

第三行不要写成 `Gesture: Ready`。操作者不关心内部对象叫 Gesture，而关心当前能否操作。

| 条件                                         | 显示文本           | 颜色 / 效果                   |
| -------------------------------------------- | ------------------ | ----------------------------- |
| `paused=true` 或 `control_enabled=false` | `Paused`         | `techAmber`                 |
| `camera_ok=false`                          | `Camera Offline` | `techRose`                  |
| `hand=Searching`                           | `Show Your Hand` | `techAmber`                 |
| `mode=standby`                             | `Standby`        | `techMuted`                 |
| `mode=presentation` 且可接收翻页           | `Ready to Flip`  | `techGreen`                 |
| 正在识别翻页 / 模式切换 attempt              | `Recognizing`    | `techCyan + glow`           |
| 刚触发下一页                                 | `Next Slide`     | `techCyan + glow`，约 800ms |
| 刚触发上一页                                 | `Previous Slide` | `techCyan + glow`，约 800ms |
| 冷却中                                       | `Cooling Down`   | `techMuted`，约 500ms       |
| `mode=presentation_pen`                    | `Pen Mode`       | `techCyan`                  |
| `mode=solidworks`                          | `SolidWorks`     | `techCyan`                  |

---

## 4. 视觉风格

整体风格必须克制、干净、偏高端科技设备面板。

### 卡片

```text
background: rgba(8, 13, 22, 0.72)
backdrop-filter: blur(18px)
border: 1px solid rgba(120, 160, 200, 0.18)
border-radius: 8px
box-shadow: 0 18px 48px rgba(0, 0, 0, 0.32)
```

避免：

- 大面积渐变背景
- 复杂装饰线条
- 多层嵌套卡片
- 大号标题
- 冗长说明文字
- 花哨动画

### 颜色语义

只使用四类语义色：

| 语义          | 用途                           |
| ------------- | ------------------------------ |
| `techGreen` | 可用、已检测、准备完成         |
| `techAmber` | 搜索中、暂停、需要操作者调整   |
| `techRose`  | 摄像头离线、手丢失、错误       |
| `techCyan`  | 正在识别、刚执行动作、活动模式 |

### Glow 规则

只有一种 Glow：

```text
shadow-cyan-glow
```

只允许在以下状态出现：

- `Recognizing`
- `Next Slide`
- `Previous Slide`
- `Pen Mode` 中正在绘制时

其余状态保持静态。这样操作者会自然理解：

> Cyan Glow = 设备正在执行识别或动作。

---

## 5. 状态生命周期

推荐状态流：

```text
Offline
  ↓
Online / Searching
  ↓
Detected / Ready to Flip
  ↓
Recognizing
  ↓
Next Slide 或 Previous Slide
  ↓
Cooling Down
  ↓
Ready to Flip
```

手离开画面时：

```text
Detected
  ↓
Searching
  ↓
Lost
```

这里的 `Searching` 很重要。它能告诉操作者：程序仍在工作，只是当前没有看到手。

---

## 6. 与现有状态服务器对接

当前 `GestureStatusServer` 广播字段包括：

```json
{
  "mode": "standby",
  "gesture": "none",
  "action": "idle",
  "camera_ok": false,
  "control_enabled": true,
  "paused": true,
  "fps": 0.0,
  "connected_clients": 0,
  "timestamp": 0.0
}
```

状态卡第一版可直接消费：

- `camera_ok`
- `mode`
- `gesture`
- `action`
- `paused`
- `control_enabled`
- `timestamp`

建议新增但不强制：

```json
{
  "hand_present": true,
  "hand_lost_duration": 0.0,
  "cooldown_until": 0.0
}
```

新增字段理由：

- `hand_present` 能区分"没有手"和"有手但分类失败"。
- `hand_lost_duration` 能稳定显示 `Searching` / `Lost`。
- `cooldown_until` 能准确显示 `Cooling Down`。

---

## 7. 组件结构

建议实现为：

```text
GestureStatusCard
 ├── DeviceHeader
 │    ├── Radar icon
 │    ├── 手势控制
 │    └── Gesture Controller
 └── StatusRows
      ├── StatusRow(Camera)
      ├── StatusRow(Hand)
      └── StatusRow(Status)
```

`StatusRow` 可以作为通用设备状态行：

```text
左侧：属性名
右侧：状态 Badge
```

不要在卡片内放教程，例如"Open Palm Swipe = Page"。这类内容可保留在调试窗口或帮助文档中。

---

## 8. Claude Code 实现提示词

```text
请为 SmartDesk Gesture Controller 添加一个简洁高端的设备状态卡（Device Status Card），用于 PPT 手势控制时显示当前设备状态。

只阅读 docs/ 下的文档，并遵守 docs/STATUS_DISPLAY_CARD.md 的设计规范。实现时先检查现有前端/状态显示结构和 WebSocket 状态服务器接入方式，不要重构无关模块。

目标：
1. 新增 GestureStatusCard 组件，用于显示三行必要信息：Camera、Hand、Status。
2. 状态卡默认固定在界面右上角；如果现有 UI 已有右侧栏，则放在右侧栏顶部。
3. 视觉风格必须简洁、高端、有科技感：深色半透明背景、轻微 blur、8px 圆角、细边框、克制阴影。
4. 不要使用 Toast、弹窗、成功提示或教程文本。所有反馈都在状态卡内部完成。
5. 不展示调试细节：不要显示 FPS、置信度、坐标、hand_lost_duration 数字、cooldown 数字、connected_clients。

数据来源：
- 优先复用现有 GestureStatusServer WebSocket 快照。
- 当前可用字段包括 mode、gesture、action、camera_ok、control_enabled、paused、timestamp。
- 如果代码中容易补充，请在状态广播中新增 hand_present、hand_lost_duration、cooldown_until；如果改动过大，则第一版用 gesture !== "none" 近似判断 Hand=Detected。

显示规则：
- Camera:
  - camera_ok=true -> Online，绿色
  - camera_ok=false -> Offline，红色
- Hand:
  - camera_ok=false -> Unavailable，灰色
  - hand_present=true 或 gesture !== "none" -> Detected，绿色
  - 摄像头在线但没有手 -> Searching，琥珀色
  - 手丢失超过 hand_loss_timeout -> Lost，红色
- Status:
  - paused=true 或 control_enabled=false -> Paused，琥珀色
  - camera_ok=false -> Camera Offline，红色
  - Hand=Searching -> Show Your Hand，琥珀色
  - mode=standby -> Standby，灰色
  - mode=presentation -> Ready to Flip，绿色
  - mode=presentation_pen -> Pen Mode，青色
  - mode=solidworks -> SolidWorks，青色
  - 刚触发 press("right") / page_swipe_right / 下一页动作 -> Next Slide，青色 glow，约 800ms 后进入 Cooling Down 或 Ready
  - 刚触发 press("left") / page_swipe_left / 上一页动作 -> Previous Slide，青色 glow，约 800ms 后进入 Cooling Down 或 Ready
  - 翻页冷却中 -> Cooling Down，灰色或弱青色
  - 正在识别 attempt / intent_phase=tracking 或类似状态 -> Recognizing，青色 glow

组件要求：
- 使用现有 Card / Badge / theme token / icon 体系；没有现成组件时再创建轻量组件。
- 图标优先使用 lucide-react 的 Radar。
- 卡片宽度约 300px，高度约 132-150px。
- 移动端 left/right 16px，top 16px，width auto。
- Glow 只允许用于 Recognizing、Next Slide、Previous Slide、Pen Mode 正在绘制，不要全局滥用。
- 文案只使用英文状态词和中文标题：手势控制 / Gesture Controller。

验收：
1. 摄像头离线时，用户能立即看到 Camera Offline。
2. 摄像头在线但没有手时，用户能看到 Show Your Hand 或 Hand=Searching。
3. 检测到手并处于 PPT 模式时，用户能看到 Ready to Flip。
4. 翻页时显示 Next Slide / Previous Slide，并有短暂青色 glow。
5. 冷却时显示 Cooling Down，避免用户误以为连续挥手应该连续翻页。
6. UI 不遮挡主要内容，不出现冗余说明，不像调试面板。
7. 运行现有测试；如果项目有前端构建或 lint 命令，也一并运行并修复相关问题。
```
