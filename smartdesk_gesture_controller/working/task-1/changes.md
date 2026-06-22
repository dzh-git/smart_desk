# Task 1 Changes

## 根因确认

`GestureState._handle_no_hand()` 在手丢失超过 `hand_lost_timeout` 后，**每一帧**都返回包含 `ActionIntent.release_all()` 的完整安全释放序列。真实 `ActionLayer.release_all()` 会无条件执行 3 次 `mouseUp` 和 3 次 `keyUp`；在 PyAutoGUI 默认 `PAUSE=0.1` 的环境下，每个无手帧至少同步阻塞约 0.6 秒，导致恢复后画面无手时帧率掉到约 1 FPS。dry-run 使用 `FakeDriver` 没有这类延迟，因此不会复现。

修复对象：状态机重复输出事件，而非 `ActionLayer` 或 PyAutoGUI 本身。

## 修改文件清单

1. `hands/gesture_state.py`
2. `tests/test_gesture_state.py`

## 每个修改点及理由

### `hands/gesture_state.py`

1. **新增 `_hand_loss_released` 布尔锁存（`__init__`）**
   - 位置：Hand-loss safety 状态区。
   - 理由：标记“当前连续无手事件是否已经完成安全释放”。初始未触发。

2. **见手时复位锁存（`step()`）**
   - 在 `gname != G_NONE` 分支中设置 `self._hand_loss_released = False`。
   - 理由：任意有效手重新出现时重新布防，下一次独立手丢失事件可再次触发一次安全释放。

2.5. **paused 分支见手时同样复位锁存（`step()`）**
   - paused 分支识别到有效手时，除更新 `last_hand_seen` 外，同时清空 `hand_lost_start_time` 并设置 `_hand_loss_released = False`。
   - 理由：与活动状态见手语义保持一致，确保 `force_release()` 后 paused 中见手也能重新布防，恢复后再次无手仍可触发一次安全释放。

3. **超时后只释放一次（`_handle_no_hand()`）**
   - 在 `elapsed >= timeout` 后检查 `_hand_loss_released`：
     - 为 `False` 时输出完整释放序列（`mouse_up(left/middle)`、`key_up(shift)`、`release_all()`），并置锁存为 `True`。
     - 为 `True` 时直接返回空意图，避免每帧重复 `release_all`。
   - 理由：消除同一次连续无手事件重复触发安全释放，恢复正常帧率；同时保留首次超时的完整安全语义。

4. **`force_release()` 设置锁存**
   - 在 `_reset_continuous_state()` 前设置 `self._hand_loss_released = True`。
   - 理由：显式释放已经兜底了当前手丢失时段的安全释放；避免之后同一无手时段再次触发重复释放。`force_release()` 本身仍保持幂等（无 held 状态时返回 `[]`）。

### `tests/test_gesture_state.py`

- 增强 `test_long_none_triggers_release_all`：额外断言 `release_all` 恰好出现 1 次，并验证锁存置位。
- 新增 `test_long_none_repeated_frames_emit_release_all_once`：同一次连续无手超时后，后续多个无手帧均返回空意图。
- 新增 `test_hand_reappearance_rearms_hand_loss_release`：手重新出现后，下一次独立无手事件仍能再次触发一次 `release_all`。
- 新增 `test_pen_none_timeout_releases_left_once`：PPT 画笔按住左键时，首次超时释放左键 + `release_all`，后续帧不重复。
- 新增 `test_solidworks_none_timeout_releases_continuous_once`：SolidWorks 中键/Shift 按住时，首次超时释放一次，后续帧不重复。
- 新增 `test_force_release_prevents_duplicate_hand_loss_release`：显式 `force_release()` 后同一无手时段不再重复触发。
- 新增 `test_hand_present_after_force_release_rearms`：`force_release()` 后见手可重新布防，下次无手事件仍可触发。
- 新增 `test_paused_hand_reappearance_rearms_hand_loss_latch`：审查发现的边界问题——`force_release()` 后 paused 中见手，恢复后再次无手超时仍能恰好输出一次 `release_all`。

## 采用的方案

**优先方案：状态机边沿触发/布防标记。**

选择原因：
- 根因是状态机对同一事件每帧输出 `release_all`，去重最合适的位置是状态机本身。
- 只增加一个内部布尔锁存，改动最小，不触碰 `ActionLayer`、PyAutoGUI、配置、启动脚本、文档。
- 保留 `ActionLayer.release_all()` 的六项无条件释放语义和幂等性。
- 不引入线程、队列、sleep、跳帧或频率限流，不掩盖问题。

## 工作区既有修改

工作区已存在大量未提交改动（`git status` 显示 17 个文件已修改，包括 docs、README、bat、其他源码等）。这些属于本项目之前的 Phase 9 等迭代，**本任务没有覆盖或回退任何无关改动**。仅修改了 `hands/gesture_state.py` 和 `tests/test_gesture_state.py` 中与本缺陷直接相关的部分，并在新增测试时复用了现有测试辅助函数（`_cfg`、`_hand` 等）。

## `git diff --stat` 简要结果（本任务相关文件）

```text
 hands/gesture_state.py    |  296 +-
 tests/test_gesture_state.py | 1920 ++++++-------------
 2 files changed, 765 insertions(+), 1451 deletions(-)
```

> 注：统计数字较大是因为工作区已包含 Phase 9 等大量既有未提交改动；本任务实际新增/修改代码仅约 30 行（状态机 4 处 + 测试 7 个函数）。
