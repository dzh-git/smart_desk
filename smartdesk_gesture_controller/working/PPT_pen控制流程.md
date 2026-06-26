
## 一、模式切换流程

### 1. 进入 PPT_pen 模式
**触发条件**：在 `presentation` 模式下，稳定保持 `Victory` 手势超过 `pen_mode_hold` 时间

**关键代码**（`gesture_intent_tracker.py`）：
```python
# 第 736-743 行：Victory HOLD in presentation → pen_mode_enter
if (current_mode == MODE_PRESENTATION and g == "Victory" and
        self._hold_attempt is None and
        self._attempt is None and self._session is None and
        not self._zoom_active):
    if (now - self._stable_since) >= cfg.mode_arm_duration:
        events.extend(self._begin_hold_attempt(
            INTENT_PEN_MODE, frame, now))
        return events
```

**状态机处理**（`gesture_state.py`）：
```python
# 第 1197-1227 行：_on_pen_mode_toggle()
def _on_pen_mode_toggle(self, evt: ControlEvent, now: float) -> List[ActionIntent]:
    if self.mode == MODE_PRESENTATION:
        self._set_cooldown(_COOLDOWN_PEN_TOGGLE, cfg.pen_toggle_cooldown, now)
        self._enter_mode(MODE_PRESENTATION_PEN, now)
        intents.append(ActionIntent.hotkey("ctrl", "p"))  # 进入画笔模式
    elif self.mode == MODE_PRESENTATION_PEN:
        # 释放左键（如正在绘制）
        if self.is_left_mouse_down:
            intents.append(ActionIntent.mouse_up(button="left"))
        self._enter_mode(MODE_PRESENTATION, now)
        intents.append(ActionIntent.hotkey("ctrl", "a"))  # 退出画笔模式
```

---

## 二、画笔绘制流程（核心）

### 2.1 开始绘制（PINCH 检测）
**触发条件**：在 `presentation_pen` 模式下，`pinch_distance_norm < pinch_threshold`

**关键代码**（`gesture_intent_tracker.py` 第 655-669 行）：
```python
# 在 _try_start() 中检查
if (current_mode == MODE_PRESENTATION_PEN and
        frame.pinch_distance_norm is not None and
        frame.hand_present and
        self._session is None and self._attempt is None and
        not self._zoom_active and self._hold_attempt is None):
    if frame.pinch_distance_norm < cfg.pinch_threshold:
        events.extend(self._begin_session_attempt(
            CTRL_PEN_DRAW, EVT_PEN_DRAW_BEGIN, frame, now))
        return events
```

**创建画笔会话**（`_begin_session_attempt()` 第 1115-1155 行）：
```python
def _begin_session_attempt(self, control_type: str, begin_evt: str,
                           frame: GestureFrame, now: float) -> List[ControlEvent]:
    # 画笔模式使用 index_tip_xy 作为绘制位置
    if control_type == CTRL_PEN_DRAW and frame.index_tip_xy is not None:
        palm = frame.index_tip_xy
    else:
        palm = frame.palm_xy or (0.0, 0.0)
    
    # 画笔会话按住左键
    buttons = ["left"]
    
    self._session = ControlSession(
        session_id=session_id,
        control_type=control_type,  # CTRL_PEN_DRAW
        phase=SESSION_IDLE,
        start_position=palm,
        last_position=palm,
        started_at=now,
        last_seen_at=now,
        pressed_buttons=buttons,  # 按住左键
    )
```

### 2.2 状态机处理开始事件
**关键代码**（`gesture_state.py` 第 1229-1242 行）：
```python
def _on_pen_draw_begin(self) -> List[ActionIntent]:
    """Handle EVT_PEN_DRAW_BEGIN: press left mouse button once."""
    if self.mode != MODE_PRESENTATION_PEN:
        return []
    if self.is_left_mouse_down:  # 幂等：避免重复按下
        return []
    self.is_left_mouse_down = True
    self.is_pinching = True
    self.active_continuous_action = "pen_draw"
    return [ActionIntent.mouse_down(button="left")]  # 按下左键开始绘制
```

---

### 2.3 绘制更新（移动光标）
**Tracker 更新会话**（`gesture_intent_tracker.py` 第 1157-1279 行）：
```python
def _update_session(self, frame: GestureFrame, current_mode: str,
                    now: float) -> List[ControlEvent]:
    # 画笔会话使用 index_tip_xy 跟踪位置
    if ses.control_type == CTRL_PEN_DRAW and frame.index_tip_xy is not None:
        pos = frame.index_tip_xy
    else:
        pos = frame.palm_xy
    
    # 计算移动增量
    if ses.last_position is not None:
        raw_dx = pos[0] - ses.last_position[0]
        raw_dy = pos[1] - ses.last_position[1]
    
    # 应用运动约束（死区、最大步长、速度限制）
    dx, dy = self._constrain_motion(raw_dx, raw_dy, ses.last_position, now, dt)
    
    # 会话从 IDLE 过渡到 ACTIVE（超过死区和最小运动时间）
    if ses.phase == SESSION_IDLE:
        dist = (raw_dx * raw_dx + raw_dy * raw_dy) ** 0.5
        if dist > cfg.motion_deadzone:
            if ses.motion_started:
                ses.motion_duration = now - ses.started_at
            if ses.motion_duration >= cfg.min_motion_duration:
                ses.phase = SESSION_ACTIVE
                events.append(ControlEvent(
                    type=EVT_PEN_DRAW_BEGIN, phase="begin", ...))
    
    # 活跃会话发出更新事件
    elif ses.phase == SESSION_ACTIVE:
        if abs(dx) > 0 or abs(dy) > 0:
            events.append(ControlEvent(
                type=EVT_PEN_DRAW_UPDATE, phase="update",
                dx=dx, dy=dy, position=pos))
```

**状态机处理更新事件**（`gesture_state.py` 第 1244-1255 行）：
```python
def _on_pen_draw_update(self, evt: ControlEvent, now: float) -> Optional[ActionIntent]:
    """Handle EVT_PEN_DRAW_UPDATE: move cursor while drawing."""
    if self.mode != MODE_PRESENTATION_PEN:
        return None
    if evt.position is None:
        return None
    # 使用 _maybe_move 进行平滑移动
    return self._maybe_move(evt.position, now)
```

---

### 2.4 结束绘制（释放 PINCH）
**触发条件**：`pinch_distance_norm > pinch_release_threshold`

**Tracker 检查释放**（`gesture_intent_tracker.py` 第 1174-1190 行）：
```python
# 在 _update_session() 中检查画笔会话的坏帧
if ses.control_type == CTRL_PEN_DRAW:
    # 坏帧条件：捏合释放 或 手丢失
    pd = frame.pinch_distance_norm
    if not frame.hand_present:
        ses.bad_frames += 1
    elif pd is not None and pd > cfg.pinch_release_threshold:
        ses.bad_frames += 1  # 捏合释放 → 坏帧累积
    else:
        # 捏合仍保持 → 不计入坏帧
        ses.bad_frames = 0
        ses.bad_since = None

# 坏帧超时后结束会话
def _check_intent_lost(self, events: List[ControlEvent], now: float) -> None:
    if self._session is not None:
        ses = self._session
        if ses.bad_frames > grace or \
           (ses.bad_since is not None and (now - ses.bad_since) > lost_timeout):
            end_events = self._end_session(reason, now)
            events.extend(end_events)
```

**状态机处理结束事件**（`gesture_state.py` 第 1257-1271 行）：
```python
def _on_pen_draw_end(self) -> List[ActionIntent]:
    """Handle EVT_PEN_DRAW_END: release left mouse button."""
    if self.mode != MODE_PRESENTATION_PEN:
        return []
    if not self.is_left_mouse_down:  # 幂等
        return []
    self.is_left_mouse_down = False
    self.is_pinching = False
    self.active_continuous_action = None
    return [ActionIntent.mouse_up(button="left")]  # 释放左键结束绘制
```

---

## 三、非绘制状态下的光标移动

**关键代码**（`gesture_state.py` 第 807-837 行）：
```python
def _step_presentation_pen(self, hand: HandInput, now: float) -> Tuple[List[ActionIntent], str]:
    """Phase 9 presentation_pen mode."""
    g = hand.gesture_name
    intents: List[ActionIntent] = []
    
    # 当没有活跃的画笔会话时，允许光标移动
    if hand.palm_xy is not None and self.active_continuous_action != "pen_draw":
        mv = self._maybe_move(hand.palm_xy, now)
        if mv is not None:
            intents.append(mv)
    
    return intents, self._PEN_STATUS
```

---

## 四、完整事件流总结

```
用户捏合手指 (pinch_distance_norm < threshold)
    ↓
GestureIntentTracker._try_start()
    → 创建 ControlSession(CTRL_PEN_DRAW)
    → 发出 EVT_PEN_DRAW_BEGIN
    ↓
GestureState._handle_events()
    → 调用 _on_pen_draw_begin()
    → 执行 ActionIntent.mouse_down("left")  # 按下左键
    ↓
用户移动手指
    ↓
GestureIntentTracker._update_session()
    → 计算 dx, dy（应用约束）
    → 发出 EVT_PEN_DRAW_UPDATE
    ↓
GestureState._on_pen_draw_update()
    → 执行 ActionIntent.move_rel(dx, dy)  # 移动光标绘制
    ↓
用户释放手指 (pinch_distance_norm > release_threshold)
    ↓
GestureIntentTracker._update_session()
    → 坏帧累积 → 超时
    → 发出 EVT_PEN_DRAW_END
    ↓
GestureState._on_pen_draw_end()
    → 执行 ActionIntent.mouse_up("left")  # 释放左键
```

---

## 五、可能的问题点

如果你遇到画笔问题，检查：

1. **捏合检测阈值**（`gesture_config.py`）：
   - `pinch_threshold`：进入捏合的距离（默认 0.045）
   - `pinch_release_threshold`：释放捏合的距离（默认 0.065）

2. **Tracker 是否正确初始化画笔会话**：
   - 检查 `frame.pinch_distance_norm` 是否正确计算
   - 检查 `index_tip_xy` 是否可用

3. **状态机是否正确跟踪**：
   - `self.is_left_mouse_down` 状态
   - `self.active_continuous_action == "pen_draw"`

4. **动作层是否启用**（`enable_system_mouse`）：
   - 如果为 False，使用 FakeDriver（不触实系统）

需要我进一步分析具体哪个环节可能有问题吗？