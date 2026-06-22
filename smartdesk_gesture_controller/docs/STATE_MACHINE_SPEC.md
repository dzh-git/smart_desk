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

状态机输入：

```text
HandInput
当前 mode
当前时间 now
上一次手势状态
上一次连续动作状态
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
Thumb_Up 保持 → presentation
Pointing_Up 保持 → mouse
ILoveYou 保持 → solidworks
Closed_Fist → standby
```

---

### 2.3 连续动作必须有 begin / update / end

涉及拖动、画笔、中键旋转、Shift+中键平移时，状态机必须维护连续动作状态。

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

### 2.4 所有退出路径必须 release_all

以下情况必须输出 `ActionIntent(type="release_all")`：

```text
Closed_Fist 退出当前模式
手丢失超时
切换模式
暂停程序
退出程序
异常处理
从 solidworks 回 standby
从 presentation_pen 回 standby
从 mouse_drag 回 standby
```

---

## 3. 状态列表

系统第一版定义以下状态：

```text
MODE_STANDBY
MODE_PRESENTATION
MODE_PRESENTATION_PEN
MODE_MOUSE
MODE_MOUSE_SCROLL
MODE_SOLIDWORKS
MODE_PAUSED
```

不建议第一版继续扩展更多状态。

---

## 4. 状态说明总表

| 状态                 | 含义            | 是否执行控制动作 | 典型用途         |
| ------------------ | ------------- | -------- | ------------ |
| `standby`          | 待机            | 否        | 程序启动后的安全状态   |
| `presentation`     | PPT 演示        | 是        | 翻页、进入画笔、退出演示 |
| `presentation_pen` | PPT 画笔        | 是        | 指针移动、画线、擦除   |
| `mouse`            | 鼠标控制          | 是        | 鼠标移动、点击、拖拽   |
| `mouse_scroll`     | 鼠标滚轮          | 是        | 滚动网页或文档      |
| `solidworks`       | SolidWorks 查看 | 是        | 旋转、平移、缩放模型   |
| `paused`           | 暂停            | 否        | 热键暂停后的安全状态   |

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
鼠标模式退出
暂停恢复后选择回待机
异常恢复
```

### 5.3 允许动作

| 手势            | 条件       | 输出动作          | 新状态            |
| ------------- | -------- | ------------- | -------------- |
| `Thumb_Up`    | 保持 1.5 秒 | `press("f5")` | `presentation` |
| `Pointing_Up` | 保持 1.0 秒 | 无键盘动作         | `mouse`        |
| `ILoveYou`    | 保持 1.5 秒 | 无键盘动作         | `solidworks`   |
| `Open_Palm`   | 任意       | 无动作           | `standby`      |
| `Closed_Fist` | 任意       | `release_all` | `standby`      |
| `None`        | 任意       | 无动作           | `standby`      |

### 5.4 禁止动作

```text
standby 模式下禁止 Open_Palm 触发 F5
standby 模式下禁止 PINCH 触发点击
standby 模式下禁止 Victory 触发画笔
standby 模式下禁止任何鼠标拖动
```

### 5.5 状态提示

推荐显示：

```text
Standby: Thumb Up = PPT, Pointing Up = Mouse, I Love You = SolidWorks
```

---

## 6. MODE_PRESENTATION

### 6.1 状态定位

`presentation` 用于 PPT 演示控制。

### 6.2 进入条件

```text
从 standby 中 Thumb_Up 保持 1.5 秒，发送 F5 后进入
```

### 6.3 允许动作

| 手势              | 条件                   | 输出动作                           | 新状态                |
| --------------- | -------------------- | ------------------------------ | ------------------ |
| `Open_Palm` 向右挥 | 达到 SWIPE_RIGHT 条件    | `press("right")`               | `presentation`     |
| `Open_Palm` 向左挥 | 达到 SWIPE_LEFT 条件     | `press("left")`                | `presentation`     |
| `Victory`       | 保持 0.5 秒             | `hotkey("ctrl", "p")`          | `presentation_pen` |
| `Thumb_Down`    | 保持 0.5 秒             | `press("e")`                   | `presentation`     |
| `Thumb_Up`      | 保持 0.5 秒             | `hotkey("ctrl", "a")`          | `presentation`     |
| `ILoveYou`      | 保持 0.8 秒             | `press("b")`                   | `presentation`     |
| `Closed_Fist`   | 保持 0.8 秒             | `press("esc")` + `release_all` | `standby`          |
| `None`          | 短暂丢失                 | 无动作                            | `presentation`     |
| `None`          | 超过 hand_lost_timeout | `release_all`                  | `presentation`     |

### 6.4 冷却规则

```text
翻页后必须进入 page_turn_cooldown
进入画笔后必须进入 pen_toggle_cooldown
退出演示后必须进入 mode_switch_cooldown
```

### 6.5 禁止动作

```text
presentation 模式下 Thumb_Up 不允许再次触发 F5
presentation 模式下 PINCH 不允许触发普通鼠标点击
presentation 模式下 Open_Palm 保持不触发启动动作
```

### 6.6 状态提示

推荐显示：

```text
Presentation: Open Palm Swipe = Page, Victory = Pen, Fist = Exit
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
| `Thumb_Down`  | 保持 0.5 秒                           | `press("e")`                                        | `presentation_pen` |
| `Thumb_Up`    | 保持 0.5 秒                           | `mouse_up("left")` + `hotkey("ctrl", "a")`          | `presentation`     |
| `Closed_Fist` | 保持 0.8 秒                           | `mouse_up("left")` + `press("esc")` + `release_all` | `standby`          |
| `None`        | 超过 hand_lost_timeout               | `mouse_up("left")` + `release_all`                  | `presentation_pen` |

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
Pen Mode: Pointing Up = Move, Pinch = Draw, Thumb Up = Cursor, Fist = Exit
```

---

## 8. MODE_MOUSE

### 8.1 状态定位

`mouse` 用于通用鼠标控制。

### 8.2 进入条件

```text
standby 模式下 Pointing_Up 保持 1.0 秒
```

### 8.3 允许动作

| 手势              | 条件                   | 输出动作                   | 新状态            |
| --------------- | -------------------- | ---------------------- | -------------- |
| `Pointing_Up`   | 移动                   | `move_to` 或 `move_rel` | `mouse`        |
| `PINCH` 短按      | 小于 drag_hold_time    | `click("left")`        | `mouse`        |
| `PINCH` 长按      | 超过 drag_hold_time    | `mouse_down("left")`   | `mouse`        |
| `PINCH` 长按 + 移动 | 移动                   | `move_to` 或 `move_rel` | `mouse`        |
| `PINCH` 释放      | 已经拖拽                 | `mouse_up("left")`     | `mouse`        |
| `Victory`       | 保持 0.5 秒             | 无动作                    | `mouse_scroll` |
| `Thumb_Down`    | 保持 0.5 秒             | `click("right")`       | `mouse`        |
| `Closed_Fist`   | 保持 0.8 秒             | `release_all`          | `standby`      |
| `None`          | 超过 hand_lost_timeout | `release_all`          | `mouse`        |

### 8.4 连续动作状态

`mouse` 需要维护：

```text
is_left_mouse_down
pinch_start_time
pinch_started_as_click_candidate
last_pointer_position
```

### 8.5 点击与拖拽区分

规则：

```text
PINCH 持续时间 < drag_hold_time 且位移较小：
    click("left")

PINCH 持续时间 >= drag_hold_time：
    mouse_down("left")
    后续移动视为拖拽

PINCH 释放：
    如果已经 mouse_down，则 mouse_up("left")
```

推荐默认值：

```text
drag_hold_time = 0.35s
click_max_movement = 25px
```

### 8.6 状态提示

推荐显示：

```text
Mouse: Pointing Up = Move, Pinch = Click/Drag, Victory = Scroll, Fist = Exit
```

---

## 9. MODE_MOUSE_SCROLL

### 9.1 状态定位

`mouse_scroll` 是鼠标滚轮子模式。

### 9.2 进入条件

```text
mouse 模式下 Victory 保持 0.5 秒
```

### 9.3 允许动作

| 手势               | 条件                     | 输出动作              | 新状态            |
| ---------------- | ---------------------- | ----------------- | -------------- |
| `Victory` + 向上移动 | dy < -scroll_threshold | `scroll(+amount)` | `mouse_scroll` |
| `Victory` + 向下移动 | dy > scroll_threshold  | `scroll(-amount)` | `mouse_scroll` |
| `Pointing_Up`    | 保持 0.5 秒               | 无动作               | `mouse`        |
| `Closed_Fist`    | 保持 0.8 秒               | `release_all`     | `standby`      |
| `None`           | 超过 hand_lost_timeout   | `release_all`     | `mouse`        |

### 9.4 限制

```text
mouse_scroll 模式下不允许 PINCH 触发点击。
mouse_scroll 模式下不允许 Open_Palm 触发任何动作。
```

### 9.5 状态提示

推荐显示：

```text
Scroll Mode: Victory Up/Down = Scroll, Pointing Up = Mouse, Fist = Exit
```

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
standby 模式下 ILoveYou 保持 1.5 秒
```

### 10.3 允许动作

| 手势               | 条件                     | 输出动作                                         | 新状态          |
| ---------------- | ---------------------- | -------------------------------------------- | ------------ |
| `Open_Palm` 开始移动 | 稳定出现并超过移动死区            | `mouse_down("middle")`                       | `solidworks` |
| `Open_Palm` 持续移动 | 已经 middle_down         | `move_rel(dx, dy)`                           | `solidworks` |
| `Open_Palm` 结束   | 手势变化 / None            | `mouse_up("middle")`                         | `solidworks` |
| `Victory` 开始移动   | 稳定出现并超过移动死区            | `key_down("shift")` + `mouse_down("middle")` | `solidworks` |
| `Victory` 持续移动   | 已经 shift + middle_down | `move_rel(dx, dy)`                           | `solidworks` |
| `Victory` 结束     | 手势变化 / None            | `mouse_up("middle")` + `key_up("shift")`     | `solidworks` |
| `PINCH` 距离增大     | 超过缩放死区                 | `scroll(+amount)`                            | `solidworks` |
| `PINCH` 距离减小     | 超过缩放死区                 | `scroll(-amount)`                            | `solidworks` |
| `Thumb_Up`       | 保持 0.5 秒               | `press("f")`                                 | `solidworks` |
| `ILoveYou`       | 保持 0.8 秒               | `hotkey("ctrl", "7")`                        | `solidworks` |
| `Closed_Fist`    | 保持 0.8 秒               | `release_all`                                | `standby`    |
| `None`           | 超过 hand_lost_timeout   | `release_all`                                | `solidworks` |

### 10.4 连续动作状态

`solidworks` 需要维护：

```text
solidworks_action = none | rotate | pan | zoom
is_middle_mouse_down
is_shift_down
last_hand_center
last_pinch_distance
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
先 mouse_up("middle")
再 key_down("shift") + mouse_down("middle")
进入 pan
```

如果当前正在 pan，突然识别到 Open_Palm：

```text
先 mouse_up("middle") + key_up("shift")
再 mouse_down("middle")
进入 rotate
```

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
SolidWorks: Open Palm = Rotate, Victory = Pan, Pinch = Zoom, Thumb Up = Fit, Fist = Exit
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
| `standby`          | `Thumb_Up` HOLD    | `presentation`     | `press("f5")`                                       |
| `standby`          | `Pointing_Up` HOLD | `mouse`            | 无                                                   |
| `standby`          | `ILoveYou` HOLD    | `solidworks`       | 无                                                   |
| `presentation`     | `Victory` HOLD     | `presentation_pen` | `hotkey("ctrl", "p")`                               |
| `presentation`     | `Closed_Fist` HOLD | `standby`          | `press("esc")` + `release_all`                      |
| `presentation_pen` | `Thumb_Up` HOLD    | `presentation`     | `mouse_up("left")` + `hotkey("ctrl", "a")`          |
| `presentation_pen` | `Closed_Fist` HOLD | `standby`          | `mouse_up("left")` + `press("esc")` + `release_all` |
| `mouse`            | `Victory` HOLD     | `mouse_scroll`     | 无                                                   |
| `mouse`            | `Closed_Fist` HOLD | `standby`          | `release_all`                                       |
| `mouse_scroll`     | `Pointing_Up` HOLD | `mouse`            | 无                                                   |
| `mouse_scroll`     | `Closed_Fist` HOLD | `standby`          | `release_all`                                       |
| `solidworks`       | `Closed_Fist` HOLD | `standby`          | `release_all`                                       |
| 任意状态               | `Ctrl+Alt+G`       | `paused`           | `release_all`                                       |
| `paused`           | `Ctrl+Alt+G`       | `standby`          | `release_all`                                       |
| 任意状态               | `Ctrl+Alt+Q`       | 程序退出               | `release_all`                                       |

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
None 超时
模式切换
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

---

## 14. None 与手丢失处理

### 14.1 短暂 None

如果手势短暂丢失，但未超过 `hand_lost_timeout`：

```text
不立即切换模式
不触发离散动作
连续拖拽动作可以暂时保持，但不再更新移动
```

### 14.2 长时间 None

如果手势丢失超过 `hand_lost_timeout`：

```text
输出 release_all
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

动态手势需要维护轨迹窗口：

```text
hand_center_history = [(time, x, y), ...]
```

只保留最近：

```text
swipe_time_window = 0.8s
```

根据窗口内位移判断：

```text
dx = latest_x - oldest_x
dy = latest_y - oldest_y
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
stable_duration
cooldown_until
active_continuous_action
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
Thumb_Up 保持不足 1.5 秒，不触发 F5
Thumb_Up 保持超过 1.5 秒，触发 F5 并进入 presentation
Open_Palm 在 standby 中不触发动作
Pointing_Up 保持后进入 mouse
ILoveYou 保持后进入 solidworks
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
Thumb_Up 触发 Ctrl+A 并回 presentation
Closed_Fist 触发 Esc + release_all + standby
None 超时触发 release_all
```

### 19.4 mouse 测试

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
mouse
mouse_scroll
```

第三优先级：

```text
solidworks
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
