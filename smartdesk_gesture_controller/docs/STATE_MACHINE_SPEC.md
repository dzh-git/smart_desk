# STATE_MACHINE_SPEC.md

# SmartDesk Gesture Controller 状态机规范

## 1. 文档目的

本文档用于定义 SmartDesk Gesture Controller 的状态机结构、状态切换规则、进入/退出条件和安全释放规则。

后续 `gesture_state.py` 的修改必须以本文档为准。

本文档重点解决以下问题：

1. 系统有哪些模式。
2. 每个模式如何进入和退出。
3. 同一个手势在不同模式下如何解释。
4. 什么时候必须执行 `release_all`。
5. 如何避免鼠标键、Shift 键、中键卡住。

---

## 2. 状态机设计原则

### 2.1 状态机只输出动作意图，不直接执行动作

`gesture_state.py` 不应直接调用 PyAutoGUI。

第一阶段采用混合输入：已迁移功能不再由状态机直接消费帧级手势，未迁移功能继续使用兼容路径。

```text
ControlEvent[]（模式切换、PPT 翻页、SolidWorks 旋转/平移/缩放）
HandInput（PPT 画笔、Closed_Fist、暂停恢复等未迁移功能的兼容路径）
当前 mode
当前时间 now
cooldown 状态
安全释放状态
```

状态机输出：

```text
StepResult
```

其中 `StepResult` 包括：

```text
new_mode
status_text
intents: list[ActionIntent]
```

动作执行由 `gesture_actions.py` 完成。

---

### 2.2 模式切换必须显式

禁止隐式切换模式。

例如，不允许：

```text
检测到 Open_Palm 后，根据当前前台窗口猜测进入 PPT 或 SolidWorks
```

必须通过明确手势进入模式：

```text
ILoveYou 右滑 → presentation
ILoveYou 左滑 → solidworks
Victory HOLD → presentation_pen（从 presentation）
Victory HOLD → presentation（从 presentation_pen）
Closed_Fist → standby
```

---

### 2.3 连续动作必须有 begin / update / end

涉及拖动、画笔、中键旋转、Shift+中键平移时，必须有 begin / update / end。第一阶段中，SolidWorks 旋转和平移的连续会话由 `GestureIntentTracker` 管理，状态机只消费 `rotate_begin/update/end`、`pan_begin/update/end` 事件并映射为 `ActionIntent`。

连续动作包括：

```text
left_drag
middle_drag
shift_middle_drag
pen_draw
solidworks_rotate
solidworks_pan
```

每个连续动作必须有：

```text
begin
update
end
cancel
```

---

### 2.5 控制流程驱动边界

第一阶段新增中间层：

```text
Recognizer → GestureFrame
→ GestureIntentTracker.update(frame, current_mode, now)
→ ControlEvent[]
→ GestureState
→ ActionIntent[]
→ ActionLayer
```

`GestureIntentTracker` 负责：

```text
稳定候选
管理 gesture_attempt_id
管理 ControlSession
跟踪标准化轨迹
容忍短暂分类失败
输出稳定 ControlEvent
```

`GestureState` 负责：

```text
当前 mode
cooldown
模式转换
安全释放策略
ControlEvent 到 ActionIntent 的映射
未迁移功能的兼容 HandInput 处理
```

Tracker 不得直接切换模式、执行系统动作或管理 cooldown。cooldown 只由状态机管理。

### 2.6 raw_gesture None 与真正手丢失

必须区分：

```text
hand_present=True, raw_gesture=None
```

表示检测到手，但分类器暂时无法确定类别。该情况只计入分类失败容忍，不启动手丢失计时，不立即 `release_all`。

```text
hand_present=False
```

才表示真正没有检测到手。只有该状态连续超过 `hand_loss_timeout`，Tracker 才输出一次 `hand_lost_timeout`，由状态机执行安全释放。有效手重新出现后重新布防下一次手丢失。

---

### 2.4 危险状态退出路径必须 release_all

以下情况必须输出 `ActionIntent(type="release_all")`：

```text
Closed_Fist 退出当前模式
每次连续手丢失首次超时
从活动模式切换
暂停程序
退出程序
异常处理
从 solidworks 回 standby
从 presentation_pen 回 standby
从 mouse_drag 回 standby
```

当前代码从安全的 `standby` 进入 `presentation` 或 `solidworks` 时只切换内部状态，不输出 `release_all`，因为 standby 不持有连续按键。进入 `presentation` 也不发送 F5。

---

## 3. 状态列表

系统第一版定义以下状态：

```text
MODE_STANDBY
MODE_PRESENTATION
MODE_PRESENTATION_PEN
MODE_SOLIDWORKS
MODE_PAUSED
```

**已禁用状态**（第一版简化演示不使用）：

```text
MODE_MOUSE（已禁用）
MODE_MOUSE_SCROLL（已禁用）
```

不建议第一版继续扩展更多状态。

---

## 4. 状态说明总表

| 状态                 | 含义            | 是否执行控制动作 | 典型用途         |
| ------------------ | ------------- | -------- | ------------ |
| `standby`          | 待机            | 否        | 程序启动后的安全状态   |
| `presentation`     | PPT 演示        | 是        | 翻页、进入画笔、退出演示 |
| `presentation_pen` | PPT 画笔        | 是        | 指针移动、画线      |
| `solidworks`       | SolidWorks 查看 | 是        | 旋转、平移、缩放模型   |
| `paused`           | 暂停            | 否        | 热键暂停后的安全状态   |
| `mouse`            | 鼠标控制（已禁用）    | 否        | 第一版不使用       |
| `mouse_scroll`     | 鼠标滚轮（已禁用）    | 否        | 第一版不使用       |

---

## 5. MODE_STANDBY

### 5.1 状态定位

`standby` 是安全待机状态。

在该状态下，系统可以识别手势，但不应该随意控制鼠标或键盘。

### 5.2 进入条件

以下情况进入 `standby`：

```text
程序启动完成
Closed_Fist 从其他模式退出
PPT 演示退出
SolidWorks 模式退出
暂停恢复后选择回待机
异常恢复
```

### 5.3 允许动作

| 输入事件 / 手势   | 条件       | 输出动作          | 新状态            |
| ------------- | -------- | ------------- | -------------- |
| `mode_swipe_right` | attempt 已提交且不在冷却 | 无键盘动作         | `presentation` |
| `mode_swipe_left`  | attempt 已提交且不在冷却 | 无键盘动作         | `solidworks`   |
| `Open_Palm`   | 任意       | 无动作           | `standby`      |
| `Closed_Fist` | 任意       | `release_all` | `standby`      |
| `None`        | 任意       | 无动作           | `standby`      |

**模式切换说明**：

```text
Standby 不再通过 Thumb_Up 启动 PPT，也不再进入 mouse 模式。
模式切换统一由 ILoveYou 左右滑完成。

ILoveYou 稳定进入 attempt 后，Tracker 根据轨迹输出：
mode_swipe_right: standby → presentation
mode_swipe_left: standby → solidworks

从 standby 切换到活动模式时不输出键盘或鼠标动作；只更新内部模式。
```

### 5.4 禁止动作

```text
standby 模式下禁止 Open_Palm 触发任何动作
standby 模式下禁止 PINCH 触发点击
standby 模式下禁止 Victory 触发任何动作
standby 模式下禁止任何鼠标拖动
standby 模式下 Thumb_Up / Thumb_Down 不触发任何动作
```

### 5.5 状态提示

推荐显示：

```text
Standby: ILoveYou Swipe Right = PPT, Swipe Left = SolidWorks, Fist = Exit
```

---

## 6. MODE_PRESENTATION

### 6.1 状态定位

`presentation` 用于 PPT 演示控制。

### 6.2 进入条件

```text
从 standby 中 ILoveYou 右滑，进入 presentation
```

### 6.3 允许动作

| 输入事件 / 手势      | 条件                   | 输出动作                           | 新状态                |
| --------------- | -------------------- | ------------------------------ | ------------------ |
| `page_swipe_right` | attempt 已提交且不在冷却 | `press("right")`               | `presentation`     |
| `page_swipe_left`  | attempt 已提交且不在冷却 | `press("left")`                | `presentation`     |
| `Victory`       | 保持 0.5 秒             | `hotkey("ctrl", "p")`          | `presentation_pen` |
| `mode_swipe_right` | attempt 已提交且不在冷却 | `press("esc")` + `release_all` | `standby`         |
| `mode_swipe_left`  | attempt 已提交且不在冷却 | `release_all`                    | `solidworks`      |
| `Closed_Fist`   | 保持 0.8 秒             | `press("esc")` + `release_all` | `standby`          |
| `raw_gesture=None` 且 `hand_present=True` | 短暂分类失败 | 无动作 | `presentation` |
| `hand_lost_timeout` | 每次连续真正手丢失首次超过 hand_loss_timeout | `release_all` | `presentation` |

### 6.4 冷却规则

```text
翻页后必须进入 page_turn_cooldown
进入画笔后必须进入 pen_toggle_cooldown
退出演示后必须进入 mode_switch_cooldown
模式切换后必须进入 mode_switch_cooldown
```

### 6.5 禁止动作

```text
presentation 模式下 PINCH 不允许触发普通鼠标点击
presentation 模式下 Open_Palm 保持不触发启动动作
presentation 模式下 Thumb_Up / Thumb_Down 不触发任何动作
```

### 6.6 状态提示

推荐显示：

```text
Presentation: Open Palm Swipe = Page, Victory = Pen, ILoveYou Swipe = Switch Mode, Fist = Exit
```

---

## 7. MODE_PRESENTATION_PEN

### 7.1 状态定位

`presentation_pen` 是 PPT 画笔子模式。

该状态下，系统主要控制鼠标移动和左键按下/释放。

### 7.2 进入条件

```text
presentation 模式下 Victory 保持 0.5 秒
```

进入时输出：

```text
hotkey("ctrl", "p")
```

### 7.3 允许动作

| 手势            | 条件                                 | 输出动作                                                | 新状态                |
| ------------- | ---------------------------------- | --------------------------------------------------- | ------------------ |
| `Pointing_Up` | 移动                                 | `move_to` 或 `move_rel`                              | `presentation_pen` |
| `PINCH` 开始    | pinch_distance < threshold         | `mouse_down("left")`                                | `presentation_pen` |
| `PINCH` 保持    | 移动                                 | `move_to` 或 `move_rel`                              | `presentation_pen` |
| `PINCH` 释放    | pinch_distance > release_threshold | `mouse_up("left")`                                  | `presentation_pen` |
| `Victory`     | 保持 0.5 秒                           | `mouse_up("left")` + `hotkey("ctrl", "a")`          | `presentation`     |
| `Closed_Fist` | 保持 0.8 秒                           | `mouse_up("left")` + `press("esc")` + `release_all` | `standby`          |
| `None`        | 每次连续丢失首次超过 hand_lost_timeout | 按需 `mouse_up("left")` + `release_all`              | `presentation_pen` |

**画笔切换说明**：

```text
Victory 在 presentation 中表示进入画笔；
Victory 在 presentation_pen 中表示退出画笔。
```

### 7.4 连续动作状态

`presentation_pen` 需要维护：

```text
is_left_mouse_down
last_pointer_position
last_pinch_state
```

### 7.5 退出条件

退出 `presentation_pen` 时必须：

```text
mouse_up("left")
release_all
```

如果退出到 `presentation`，不发送 `Esc`。

如果退出到 `standby`，必须发送 `Esc`。

### 7.6 状态提示

推荐显示：

```text
Pen Mode: Pointing Up = Move, Pinch = Draw, Victory = Exit Pen, Fist = Exit
```

---

## 8. MODE_MOUSE（已废弃）

> **Deprecated / Disabled in simplified demo version**
>
> 由于当前演示重点是 PPT 和 SolidWorks，且鼠标模式会增加误触和调试成本，
> 简化版本暂时禁用 mouse / mouse_scroll。

原模式名称：

```text
mouse（已废弃）
```

原功能：

| 功能      | 手势                     | 动作                          |
| ------- | ---------------------- | --------------------------- |
| 鼠标移动    | `Pointing_Up`          | 根据食指或手掌中心移动鼠标               |
| 左键单击    | `PINCH` 短按             | `click("left")`             |
| 拖拽开始    | `PINCH` 长按             | `mouse_down("left")`        |
| 拖拽持续    | `PINCH` 长按 + 移动        | 鼠标移动                        |
| 拖拽结束    | `PINCH` 释放             | `mouse_up("left")`          |
| 进入滚轮子模式 | `Victory` 保持 0.5 秒     | 进入 `mouse_scroll`           |
| 右键单击    | `Thumb_Down` 保持 0.5 秒  | `click("right")`            |
| 退出鼠标模式  | `Closed_Fist` 保持 0.8 秒 | `release_all` + 回 `standby` |

**第一版不启用此模式。保留为后续版本参考。**

---

## 9. MODE_MOUSE_SCROLL（已废弃）

> **Deprecated / Disabled in simplified demo version**
>
> 由于当前演示重点是 PPT 和 SolidWorks，且鼠标模式会增加误触和调试成本，
> 简化版本暂时禁用 mouse / mouse_scroll。

原模式名称：

```text
mouse_scroll（已废弃）
```

原功能：

| 功能     | 手势                        | 动作                |
| ------ | ------------------------- | ----------------- |
| 向上滚动   | `Victory` + 手向上移动         | `scroll(+amount)` |
| 向下滚动   | `Victory` + 手向下移动         | `scroll(-amount)` |
| 退出滚轮模式 | `Closed_Fist` 或 `None` 超时 | 回 `mouse`         |

**第一版不启用此模式。保留为后续版本参考。**

---

## 10. MODE_SOLIDWORKS

### 10.1 状态定位

`solidworks` 用于 SolidWorks 模型查看。

第一版目标只实现：

```text
旋转
平移
缩放
缩放全部拟合
退出
```

### 10.2 进入条件

```text
standby 模式下 ILoveYou 左滑，进入 solidworks
presentation 模式下 ILoveYou 左滑，进入 solidworks
```

### 10.3 允许动作

| 输入事件 / 手势      | 条件                     | 输出动作                                         | 新状态          |
| ---------------- | ---------------------- | -------------------------------------------- | ------------ |
| `rotate_begin` | session 创建且不在其他会话中 | `mouse_down("middle")`                       | `solidworks` |
| `rotate_update` | rotate session 活动 | `move_rel(dx, dy)`                           | `solidworks` |
| `rotate_end`   | session 正常结束 | `mouse_up("middle")`                         | `solidworks` |
| `pan_begin`   | session 创建且不在其他会话中 | `key_down("shift")` + `mouse_down("middle")` | `solidworks` |
| `pan_update`   | pan session 活动 | `move_rel(dx, dy)`                           | `solidworks` |
| `pan_end`     | session 正常结束 | `mouse_up("middle")` + `key_up("shift")`     | `solidworks` |
| `zoom_update`     | pinch_distance 变化超过死区 | `scroll(amount)`                            | `solidworks` |
| `mode_swipe_right` | attempt 已提交且不在冷却 | `release_all`                                    | `presentation` |
| `mode_swipe_left`  | attempt 已提交且不在冷却 | `release_all`                                    | `standby`     |
| `Closed_Fist`    | 保持 0.8 秒               | `release_all`                                | `standby`    |
| `hand_lost_timeout` | 每次连续真正手丢失首次超过 hand_loss_timeout | 按需释放中键/Shift + `release_all`           | `solidworks` |

### 10.4 连续动作状态

第一阶段中，`solidworks` 的 rotate/pan 会话由 Tracker 维护，状态机只需要记录已输出的按键/鼠标释放状态，避免重复 down/up：

```text
is_middle_mouse_down
is_shift_down
active_session_id
active_control_type
```

### 10.5 旋转与平移互斥

同一时间只能执行一种 SolidWorks 连续动作：

```text
rotate
pan
zoom
```

如果当前正在 rotate，突然识别到 Victory：

```text
不立即切换到 pan
保持当前 rotate session，直到 rotate_end / cancel / hand_lost_timeout
```

如果当前正在 pan，突然识别到 Open_Palm：

```text
不立即切换到 rotate
保持当前 pan session，直到 pan_end / cancel / hand_lost_timeout
```

活动 session 期间同时屏蔽模式切换、缩放和其他连续控制候选。

### 10.6 退出条件

退出 `solidworks` 时必须输出：

```text
mouse_up("middle")
key_up("shift")
mouse_up("left")
release_all
```

### 10.7 状态提示

推荐显示：

```text
SolidWorks: Open Palm = Rotate, Victory = Pan, Pinch = Zoom, ILoveYou Swipe = Switch Mode, Fist = Exit
```

---

## 11. MODE_PAUSED

### 11.1 状态定位

`paused` 是热键暂停状态。

该状态下，识别可以继续运行，但不执行任何鼠标和键盘动作。

### 11.2 进入条件

```text
Ctrl+Alt+G
```

进入时必须输出：

```text
release_all
```

### 11.3 允许动作

| 输入           | 动作   | 新状态                   |
| ------------ | ---- | --------------------- |
| `Ctrl+Alt+G` | 恢复   | 恢复到暂停前模式，或回 `standby` |
| `Ctrl+Alt+Q` | 退出程序 | 退出                    |
| 任意手势         | 无动作  | `paused`              |

### 11.4 恢复策略

推荐第一版采用安全策略：

```text
从 paused 恢复后，一律进入 standby。
```

不建议恢复到暂停前模式，因为暂停前可能处于拖拽、画笔、中键旋转等危险状态。

### 11.5 状态提示

推荐显示：

```text
Paused: Ctrl+Alt+G = Resume to Standby, Ctrl+Alt+Q = Quit
```

---

## 12. 状态切换总表

| 当前状态               | 输入                 | 下一个状态              | 必须动作                                                |
| ------------------ | ------------------ | ------------------ | --------------------------------------------------- |
| `standby`          | `mode_swipe_right` | `presentation`     | 无系统动作                                             |
| `standby`          | `mode_swipe_left`  | `solidworks`       | 无系统动作                                             |
| `presentation`     | `Victory` HOLD     | `presentation_pen` | `hotkey("ctrl", "p")`                               |
| `presentation`     | `mode_swipe_right` | `standby`          | `press("esc")` + `release_all`                      |
| `presentation`     | `mode_swipe_left`  | `solidworks`       | `release_all`                                       |
| `presentation`     | `Closed_Fist` HOLD | `standby`          | `press("esc")` + `release_all`                      |
| `presentation_pen` | `Victory` HOLD     | `presentation`     | `mouse_up("left")` + `hotkey("ctrl", "a")`          |
| `presentation_pen` | `Closed_Fist` HOLD | `standby`          | `mouse_up("left")` + `press("esc")` + `release_all` |
| `solidworks`       | `mode_swipe_right` | `presentation`     | `release_all`                                       |
| `solidworks`       | `mode_swipe_left`  | `standby`          | `release_all`                                       |
| `solidworks`       | `Closed_Fist` HOLD | `standby`          | `release_all`                                       |
| 任意状态               | `Ctrl+Alt+G`       | `paused`           | `release_all`                                       |
| `paused`           | `Ctrl+Alt+G`       | `standby`          | 无新增系统动作；进入 paused 时已经释放                         |
| 任意状态               | `Ctrl+Alt+Q`       | 程序退出               | `release_all`                                       |

**模式切换说明**：

```text
1. ILoveYou 滑动切换模式必须有 mode_switch_cooldown
2. ILoveYou 静止不触发切换
3. 滑动必须满足 x 方向阈值和 y 方向限制
4. 从活动模式离开时执行安全释放；standby → 活动模式不输出系统动作
5. Victory HOLD 在 presentation 中表示进入画笔，在 presentation_pen 中表示退出画笔
```

---

## 13. release_all 规范

`release_all` 必须至少包含：

```text
mouse_up("left")
mouse_up("middle")
mouse_up("right")
key_up("shift")
key_up("ctrl")
key_up("alt")
```

如果后续使用更多按键，例如：

```text
space
middle
left
right
```

也必须加入释放逻辑。

### 13.1 release_all 触发场景

以下场景必须触发：

```text
Closed_Fist 退出
每次连续真正手丢失首次超过 hand_loss_timeout
从活动模式切换
暂停
退出程序
异常捕获
摄像头读取失败
MediaPipe 推理异常
动作层异常
```

### 13.2 release_all 幂等性

`release_all` 必须是幂等的。

也就是说，即使当前没有按下任何鼠标键或键盘键，重复调用 `release_all` 也不能报错。

当前 `ActionLayer.release_all()` 每次都会无条件转发 3 个 `mouse_up` 和 3 个 `key_up`。因此幂等表示“重复执行安全”，而不是要求状态机逐帧重复生成该意图。

---

## 14. None 与手丢失处理

### 14.1 短暂 None

如果检测到手但分类暂时失败：

```text
hand_present=True
raw_gesture=None
```

则：

```text
不立即切换模式
不触发离散动作
连续拖拽动作可以暂时保持，但不再更新移动
不启动 hand_loss_timeout
```

### 14.2 长时间 None

如果真正无手超过 `hand_loss_timeout`：

```text
同一次连续丢失事件首次超时时输出 release_all
清除连续动作状态
保持当前主模式，或根据配置回 standby
```

第一版推荐：

```text
presentation：保持 presentation
presentation_pen：保持 presentation_pen，但释放左键
mouse：保持 mouse，但释放左键
solidworks：保持 solidworks，但释放中键和 Shift
```

这样用户的手重新进入画面后，不需要重新进入模式。

### 14.3 单次触发与重新布防

当前实现通过 `_hand_loss_released` 锁存避免在每个无手帧重复执行 PyAutoGUI 释放：

```text
首次超过超时：输出完整释放序列，并将 _hand_loss_released 置为 True
后续连续无手帧：不再输出硬件 ActionIntent
有效手重新出现：清空 hand_lost_start_time，并将 _hand_loss_released 复位为 False
paused 中识别到有效手：同样重新布防，但 paused 本身仍不输出硬件动作
```

`release_all` 动作仍然幂等；“动作可重复安全执行”不代表状态机应对同一次丢失事件逐帧重复输出。

---

## 15. 手势稳定性处理

状态机必须维护以下信息：

```text
last_gesture
current_gesture
gesture_start_time
gesture_stable_duration
last_trigger_time
cooldown_until
```

### 15.1 HOLD 判定

```text
如果 current_gesture == last_gesture:
    stable_duration = now - gesture_start_time
else:
    gesture_start_time = now
    stable_duration = 0
```

当：

```text
stable_duration >= required_hold_time
now >= cooldown_until
```

才允许触发 HOLD 动作。

### 15.2 动态手势判定

第一阶段已迁移的动态手势由 `GestureIntentTracker` 判定，不再由状态机直接维护原始轨迹窗口：

```text
模式切换：ILoveYou 稳定进入 attempt → palm_xy 轨迹 → mode_swipe_left/right
PPT 翻页：Open_Palm 稳定进入 attempt → palm_xy 轨迹 → page_swipe_left/right
SolidWorks 旋转/平移：Open_Palm/Victory 稳定进入 session → rotate/pan events
SolidWorks 缩放：pinch_distance 滞回和 deadzone → zoom_update
```

状态机只检查 cooldown、当前 mode 和互斥条件，并将事件映射为动作意图。

未迁移功能仍可暂时使用旧 HOLD / PINCH / Pointing_Up 逻辑。

### 15.3 attempt 与 session 约束

模式切换、翻页和缩放使用短期 `attempt_id`：

```text
同一 attempt committed 后，直到 released/cancelled/timeout 前不得再次 committed
新一次滑动必须生成新的 attempt_id
一次 page_swipe 只能翻一页
一次 mode_swipe 只能切换一次
```

旋转和平移使用 `ControlSession`：

```text
mouse_down / key_down 每个 session 只能输出一次
正常结束只精确释放 session 拥有的鼠标键/键盘键
session 活动期间不得启动第二个控制或模式切换
```

---

## 16. 冷却时间处理

状态机必须统一处理冷却时间。

每次触发离散动作后，设置：

```text
cooldown_until = now + cooldown
```

在冷却时间内：

```text
不允许重复触发同一类离散动作
连续动作 update 不受影响
release_all 不受冷却限制
Closed_Fist 不受冷却限制
Ctrl+Alt+Q 不受冷却限制
```

---

## 17. 状态机输出结构建议

建议 `StepResult` 包含：

```python
@dataclass
class StepResult:
    mode: str
    intents: list[ActionIntent]
    status_text: str
    debug_info: dict
```

建议 `debug_info` 包含：

```text
current_gesture
raw_gesture
stable_gesture
stable_duration
cooldown_until
active_continuous_action
active_attempt_id
active_session_id
intent_phase
hand_lost_duration
pinch_distance
swipe_dx
swipe_dy
```

---

## 18. 状态机内部变量建议

建议 `GestureState` 维护：

```python
class GestureState:
    mode: str
    previous_mode: str | None

    last_gesture: str
    gesture_start_time: float
    cooldown_until: float

    hand_lost_start_time: float | None
    _hand_loss_released: bool

    active_attempt_id: str | None
    active_session_id: str | None
    active_control_type: str | None

    is_left_mouse_down: bool
    is_middle_mouse_down: bool
    is_shift_down: bool

    active_continuous_action: str | None

    last_pointer_position: tuple[float, float] | None
    last_hand_center: tuple[float, float] | None
    last_pinch_distance: float | None

    hand_center_history: list[tuple[float, float, float]]
```

---

## 19. 单元测试要求

状态机必须补充以下测试：

### 19.1 standby 测试

```text
ILoveYou 右滑进入 presentation
ILoveYou 左滑进入 solidworks
Open_Palm 在 standby 中不触发动作
Thumb_Up / Thumb_Down 在 standby 中不触发任何动作
Closed_Fist 在 standby 中不触发动作（已在 standby）
Victory 在 standby 中不触发动作
PINCH 在 standby 中不触发动作
```

### 19.2 presentation 测试

```text
Open_Palm 向右挥触发 right
Open_Palm 向左挥触发 left
翻页后 cooldown 内不重复触发
Victory 保持进入 presentation_pen
Closed_Fist 触发 Esc + release_all + standby
```

### 19.3 presentation_pen 测试

```text
PINCH 开始触发 mouse_down(left)
PINCH 释放触发 mouse_up(left)
Victory HOLD 触发 Ctrl+A 并回 presentation（toggle 退出画笔）
Closed_Fist 触发 Esc + release_all + standby
None 超时触发 release_all
Thumb_Up / Thumb_Down 不触发任何动作
```

### 19.4 mouse 测试（已废弃）

> mouse / mouse_scroll 模式在第一版简化演示中已禁用。
> 以下测试保留为后续版本参考。

```text
Pointing_Up 移动输出 move intent
PINCH 短按触发 click
PINCH 长按触发 mouse_down
PINCH 释放触发 mouse_up
Victory 保持进入 mouse_scroll
Closed_Fist 触发 release_all + standby
```

### 19.5 solidworks 测试

```text
Open_Palm 开始移动触发 mouse_down(middle)
Open_Palm 持续移动触发 move_rel
Open_Palm 结束触发 mouse_up(middle)
Victory 开始移动触发 key_down(shift) + mouse_down(middle)
Victory 结束触发 mouse_up(middle) + key_up(shift)
Closed_Fist 触发 release_all + standby
```

### 19.6 paused 测试

```text
Ctrl+Alt+G 进入 paused 并 release_all
paused 中任意手势不执行动作
Ctrl+Alt+G 恢复到 standby
Ctrl+Alt+Q 退出程序前 release_all
```

---

## 20. 第一版实现优先级

第一优先级：

```text
standby
presentation
presentation_pen
release_all
```

第二优先级：

```text
solidworks
```

已废弃（第一版不实现）：

```text
mouse
mouse_scroll
```

但代码结构必须在第一轮就预留 `solidworks` 状态，避免后续再重构。

---

## 21. 结论

状态机的目标不是让手势越多越好，而是保证：

```text
状态清楚
动作唯一
退出可靠
连续动作不会卡住
测试可以覆盖
```

后续开发必须优先完成状态机规范，再实现动作层和具体手势识别。
