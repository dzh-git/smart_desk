# PPT 画笔手势控制流程规范

## 1. 概述

`presentation_pen` 模式允许用户在 PPT 幻灯片放映时使用手势控制画笔，实现隔空绘图功能。

**核心原理**：手势控制器模拟鼠标事件（左键按下+移动），PPT 的画笔工具会跟随光标移动并绘制线条。

---

## 2. 进入画笔模式

### 2.1 触发条件

在 `presentation` 模式下，保持 **Victory 手势**（✌️）稳定 **0.8 秒**（默认 `pen_mode_hold`），即可进入 `presentation_pen` 模式。

### 2.2 操作流程

1. 进入 PPT 幻灯片放映模式
2. 使用 **Open_Palm 手势**（✋）切换到 `presentation` 模式
3. 保持 **Victory 手势**（✌️）不动，等待 0.8 秒
4. 系统发送 `Ctrl+P` 快捷键，激活 PPT 画笔工具
5. 模式切换为 `presentation_pen`

### 2.3 退出画笔模式

在 `presentation_pen` 模式下，再次保持 **Victory 手势**（✌️）稳定 0.8 秒，系统发送 `Ctrl+A` 快捷键并释放鼠标左键，返回 `presentation` 模式。

---

## 3. 画笔控制流程

### 3.1 开始画线

**触发条件**：

- 当前模式为 `presentation_pen`
- 检测到 **捏合手势**（拇指和食指距离 < `pinch_threshold`）
- 手存在且没有其他活跃动作

**执行动作**：

```python
# gesture_state.py::_on_pen_draw_begin()
self.is_left_mouse_down = True
self.is_pinching = True
self.active_continuous_action = "pen_draw"
return [ActionIntent.mouse_down(button="left")]
```

- 按下鼠标左键（模拟画笔接触屏幕）
- PPT 开始绘制线条

**代码位置**：`gesture_intent_tracker.py` 第 655-669 行（开始检测）、`gesture_state.py` 第 1274-1287 行（执行按下）

---

### 3.2 画线中（移动跟踪）

**触发条件**：

- `pen_draw` session 处于 `SESSION_ACTIVE` 状态
- 手发生移动（`dx` 或 `dy` 不为 0）

**跟踪方式**：

- 使用 **食指尖位置**（`index_tip_xy`）跟踪移动（而非手掌位置）
- 位置数据经过低通滤波平滑处理（`landmark_smoothing=0.45`）

**执行动作**：

```python
# gesture_state.py::_on_pen_draw_update()
return self._maybe_move(evt.position, now)  # 移动光标
```

- 光标移动到新的位置
- PPT 跟随光标绘制线条

**代码位置**：`gesture_intent_tracker.py` 第 1157-1279 行（session 更新）、`gesture_state.py` 第 1289-1300 行（执行移动）

---

### 3.3 结束画线

**触发条件**（满足任一即可）：

1. **释放捏合**：拇指和食指距离 > `pinch_release_threshold`
2. **手丢失**：连续 `hand_loss_timeout` 秒未检测到手

**执行动作**：

```python
# gesture_state.py::_on_pen_draw_end()
self.is_left_mouse_down = False
self.is_pinching = False
self.active_continuous_action = None
return [ActionIntent.mouse_up(button="left")]
```

- 释放鼠标左键（模拟画笔离开屏幕）
- PPT 停止绘制线条

**代码位置**：`gesture_intent_tracker.py` 第 454-524 行（手丢失处理）、`gesture_state.py` 第 1302-1316 行（执行释放）

---

## 6. 配置参数

### 6.1 画笔模式相关

| 参数                        | 类型  | 默认值 | 说明                                                    |
| --------------------------- | ----- | ------ | ------------------------------------------------------- |
| `pen_mode_hold`           | float | 0.8    | Victory 手势保持稳定的时长（秒），用于进入/退出画笔模式 |
| `pinch_threshold`         | float | 0.045  | 捏合开始阈值（归一化距离），低于此值视为捏合            |
| `pinch_release_threshold` | float | 0.065  | 捏合释放阈值（归一化距离），高于此值视为释放            |
| `motion_deadzone`         | float | 0.01   | 移动死区，小于此值的移动将被忽略（过滤抖动）            |
| `min_motion_duration`     | float | 0.1    | 最小移动持续时间（秒），避免误触发                      |

### 6.2 位置平滑相关

| 参数                   | 类型  | 默认值 | 说明                                            |
| ---------------------- | ----- | ------ | ----------------------------------------------- |
| `landmark_smoothing` | float | 0.45   | 位置低通滤波权重（0-1），越高越灵敏，越低越平滑 |
| `mouse_smoothing`    | float | 0.35   | 鼠标移动平滑系数（legacy，部分路径使用）        |

---

## 7. 完整流程图

```
[PPT 幻灯片放映]
    ↓
[Open_Palm 手势] → 进入 presentation 模式
    ↓
[Victory 手势保持 0.8秒] → 发送 Ctrl+P → 进入 presentation_pen 模式
    ↓
[捏合手势]（拇指食指距离 < 0.045）→ 按下鼠标左键（开始画线）
    ↓
[手移动]（跟踪食指尖位置）→ 移动光标（画线中）
    ↓
[释放捏合]（拇指食指距离 > 0.065）→ 释放鼠标左键（结束画线）
    ↓
[Victory 手势保持 0.8秒] → 发送 Ctrl+A → 返回 presentation 模式
```

---

## 8. 注意事项

### 8.1 手丢失处理

- 如果手丢失超过 `hand_loss_timeout` 秒（默认 1.5 秒），系统会自动结束画笔 session 并释放鼠标左键
- 避免突然移开手，应缓慢释放捏合手势

### 8.2 误触发防护

- **移动死区**：`motion_deadzone=0.01` 过滤微小抖动
- **最小移动时长**：`min_motion_duration=0.1` 避免瞬时误触发
- **捏合阈值迟滞**：`pinch_threshold` 和 `pinch_release_threshold` 之间有 0.02 的迟滞区间，避免频繁切换

### 8.3 调试建议

- 使用 debug 窗口观察 `pinch_norm` 值，确认捏合检测是否正常
- 观察 `active_continuous_action` 字段，确认画笔 session 状态
- 如果画线不流畅，尝试调整 `landmark_smoothing` 参数

---

## 9. 代码文件索引

| 功能                     | 文件路径                      | 行号      |
| ------------------------ | ----------------------------- | --------- |
| 进入/退出画笔模式        | `gesture_intent_tracker.py` | 655-700   |
| 开始画笔 session         | `gesture_intent_tracker.py` | 1115-1155 |
| 更新画笔 session         | `gesture_intent_tracker.py` | 1157-1279 |
| 结束画笔 session         | `gesture_intent_tracker.py` | 1281-1300 |
| 处理 EVT_PEN_DRAW_BEGIN  | `gesture_state.py`          | 1274-1287 |
| 处理 EVT_PEN_DRAW_UPDATE | `gesture_state.py`          | 1289-1300 |
| 处理 EVT_PEN_DRAW_END    | `gesture_state.py`          | 1302-1316 |
| 手丢失处理               | `gesture_intent_tracker.py` | 454-524   |

---

