# Task 1 Final Report

## Status

completed

## Root Cause

`GestureState._handle_no_hand()` 在手丢失超过 `hand_lost_timeout` 后**每帧**都输出 `ActionIntent.release_all()`，真实 `ActionLayer.release_all()` 每次都会无条件执行 3 次 `mouseUp` + 3 次 `keyUp`；PyAutoGUI 默认 `PAUSE=0.1` 导致每个无手帧至少阻塞约 0.6 秒，从而将 FPS 拖到约 1 FPS。

## Changes

- `hands/gesture_state.py`：新增 `_hand_loss_released` 边沿锁存。
  - 见手时复位；
  - paused 中识别有效手时同样复位 `hand_lost_start_time` 与 `_hand_loss_released`；
  - 同一次连续无手事件首次超时时输出完整安全释放并置位；
  - 后续无手帧返回空意图；
  - `force_release()` 置位，避免同一无手时段重复释放。
- `tests/test_gesture_state.py`：新增/增强 8 个测试，覆盖单次释放、重复帧不重复、见手重新布防、画笔/SolidWorks 连续动作释放、`force_release()` 边界、paused 见手重新布防后再次丢失等场景。

## Verification

### 自动化测试结果

- `pytest tests/test_gesture_state.py`：103 passed
- `pytest tests/test_gesture_actions.py tests/test_gesture_controller.py`：110 passed
- `pytest tests/`：288 passed

### paused → 见手 → 恢复 → 再次丢失路径测试

- 由 `tests/test_gesture_state.py::TestPausedState::test_paused_hand_reappearance_rearms_hand_loss_latch` 确定性覆盖，通过。
- 验证：
  1. `force_release()` 后 `_hand_loss_released = True`；
  2. paused 中识别 `Open_Palm` 后锁存复位为 `False`，`hand_lost_start_time` 清空；
  3. `toggle_pause()` 恢复后进入 standby；
  4. 持续无手超过 `hand_lost_timeout` 后首次超时帧恰好输出一次 `release_all`；
  5. 后续连续无手帧不再输出任何硬件意图。

### 真实设备测试状态

未执行，等待用户验证。本环境无真实摄像头与目标程序。

## Safety Invariants

- `release_all` 六项无条件释放保留：未修改 `hands/gesture_actions.py`；`ActionLayer.release_all()` 仍执行 `mouseUp(left/middle/right)` + `keyUp(shift/ctrl/alt)`，幂等测试通过。
- 手重新出现后重新布防：`step()` 中 `gname != G_NONE` 分支及 paused 分支识别有效手时均复位 `_hand_loss_released = False` 并清空 `hand_lost_start_time`，下一次独立无手事件可再次触发一次释放。
- 暂停/退出/异常安全路径保留：
  - 进入暂停时控制器仍调用 `_safe_release()` → `force_release()` + `ActionLayer.release_all()`；
  - paused 中仍不输出任何硬件 ActionIntent；
  - `force_release()` 幂等语义不变；
  - 异常退出路径未改动；
  - 模式切换、Closed_Fist、Ctrl+Alt+Q 等安全释放路径未改动。
- 手丢失后仍保持当前主模式（presentation / presentation_pen / solidworks），未变。

## Remaining Risks

- **真实设备 FPS 验证**：自动化测试无法复现 PyAutoGUI 同步阻塞，必须在目标 Windows + 摄像头环境验证。
- **暂停恢复边界**：当前控制器在恢复时（`Ctrl+Alt+G`）不额外调用 `release_all`，与既有行为一致；但如现场期望恢复也释放，可由控制器单独调整，状态机已保证恢复后见手重新布防。
- **误按/抖动**：如果识别层在“无手”期间偶发抖动回有手再立即丢失，会复位锁存并可能多触发一次释放。这属于识别层稳定性问题，本状态机修复不引入也不消除该风险。

## Manual Acceptance Steps

1. 在目标 Windows 主机上运行 `start_gesture.bat`，确认 paused 状态调试窗口显示 FPS > 20。
2. 按一次 `Ctrl+Alt+G` 恢复到 standby；确认 FPS 仍 > 20。
3. 让画面中持续无手超过 `hand_lost_timeout`（默认请查阅 `hands/gesture_config.py`，通常为 1.0–2.0 秒），保持至少 10 秒。
   - **目标结果**：FPS 不再降到约 1；应恢复到与正常识别接近的水平，持续 > 20 FPS。
4. 将手放入画面，确认程序恢复响应；再移开手超过超时，确认程序仍安全释放一次，且帧率不持续下降。
5. 在 PPT 画笔或 SolidWorks 中按住对应按键/鼠标键后移开手，确认手丢失后鼠标左键/中键/Shift 不会卡住，且只释放一次。

> 注意：不要仅通过 `start_gesture_dry_run.bat` 验证性能；dry-run 使用 `FakeDriver`，不会暴露 PyAutoGUI 阻塞。
