# Phase 9 修复：Victory HOLD 不再在 presentation / presentation_pen 间来回切换

## 问题原因

保持 Victory 手势不变时，模式会在 `presentation` 和 `presentation_pen` 之间来回切换，根因是 **HOLD-commit 是一次性事件，但状态机没有“互锁”**。

具体链路（以当前 frame 处于 presentation、稳定 Victory 已满足 `pen_mode_hold` 为例）：

1. `GestureIntentTracker._update_hold_attempt()` 检测到稳定时长达到 `pen_mode_hold`，且 `bad_frames == 0`，于是发射一次 `EVT_PEN_MODE_TOGGLE`。
2. `GestureState._handle_events()` 收到该事件，调用 `_on_pen_mode_toggle()`，把模式从 `presentation` 切到 `presentation_pen`。
3. 下一帧手仍是 Victory。`GestureIntentTracker` 的 `reset()` **未被调用**，因此：
   - `_hold_attempt` 仍然指向刚才的 attempt；
   - `_hold_committed = True`；
   - 在 `_update_hold_attempt()` 的 `else` 分支里，只要 `g != expected` 才会释放，但 `g == Victory` 所以不释放，attempt 仍然存活。
4. 由于 `GestureState` 刚刚切到 `presentation_pen`，而当前模式是 `presentation_pen`、稳定手势仍是 Victory，`_try_start()` 中“Victory in presentation_pen → pen_mode exit”条件再次满足，又开始一个新的 HOLD attempt。
5. 达到 `pen_mode_hold` 后再次发射 `EVT_PEN_MODE_TOGGLE`，状态机把它解释为“退出 presentation_pen”，于是切回 `presentation`。
6. 循环回到步骤 1，导致持续 flip-flop。

简言之：**一次 toggle 后，tracker 和 state machine 都没有等待用户“释放 Victory”就允许下一次反向 toggle**。

---

## 修复方案

采用“单次触发 + 手势释放重载（re-arm）”的互锁机制：

1. 在 `GestureState` 中新增一个布尔标志 `_pen_toggle_rearmed`（已在 `__init__` 中初始化为 `True`）。
2. `_on_pen_mode_toggle()` 只有在 `_pen_toggle_rearmed == True` 时才执行切换；切换成功后立即把该标志置为 `False`。
3. 在 `GestureState.step()` 中，只要当前识别到的手势不是 Victory（`gname != G_VICTORY`），就把 `_pen_toggle_rearmed` 重新置为 `True`。
   - 这包括：用户换了一个手势、手移出画面（`G_NONE`）等情况。
   - 这样用户必须“先松开 Victory，再重新摆出 Victory”才能触发下一次 toggle，彻底避免保持同一姿势时的来回切换。
4. 为了配合 `tracker.reset()` 在切换后立即清理 tracker 中的 `_hold_attempt`，`StepResult` 新增了 `reset_tracker` 字段。
   - 所有模式切换入口（`_enter_mode`、`_on_pen_mode_toggle`、`force_release` 等）都会设置 `self._needs_tracker_reset = True`。
   - `GestureController` 在 `state.step()` 之后检查 `result.reset_tracker`，立即调用 `self.tracker.reset()`。
   - 这样切换后的下一帧，tracker 是干净的，不会带着旧的 HOLD attempt 继续计时。

---

## 修改文件

- `hands/gesture_state.py`
  - 新增 `_pen_toggle_rearmed` 初始化。
  - 在 `step()` 中加入非 Victory 时的 re-arm 逻辑。
  - `_on_pen_mode_toggle()` 增加 re-arm 检查。
  - `_enter_mode()` 等方法设置 `_needs_tracker_reset`。
  - `StepResult` 增加 `reset_tracker` 字段，并在 `step()` 的两个返回点（有手 / 无手）消费 `_needs_tracker_reset`。

- `hands/gesture_controller.py`
  - 用 `result.reset_tracker` 替代原来的“mode_changed 才 reset”，确保任何状态机触发的模式切换都会立即清理 tracker。

---

## 验证

- 已运行 `py -3 -m py_compile` 对修改的三个文件做语法检查，无错误。

---

## 建议的额外测试

1. 启动 controller，进入 presentation 模式。
2. 摆出 Victory 并保持不动，等待进入 presentation_pen（应只进入一次）。
3. 保持 Victory 不动，确认不会自动切回 presentation。
4. 换一个手势（如 Open_Palm）或移开手，再重新摆出 Victory，确认能切回 presentation。
5. 同样测试从 presentation 进入 presentation_pen 后，用 Victory 切回 presentation，确认也只发生一次。
