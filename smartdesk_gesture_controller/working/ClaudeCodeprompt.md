# Claude Code 提示词：修复 ILoveYou 模式切换回放暴露的问题

你是无上下文的 Claude Code。请先阅读指定文档和日志，再做最小代码修复。不要凭感觉重构。

## 0. 必须先读取的规范文档

开始修改代码前，必须先阅读 `docs/` 下全部规范文档，特别是：

- `docs/STATE_MACHINE_SPEC.md`
- `docs/CONFIG_SPEC.md`
- `docs/GESTURE_MAPPING_SPEC.md`
- `docs/ACTION_INTENT_SPEC.md`
- `docs/TEST_ACCEPTANCE_SPEC.md`

读取后再检查本次实测日志和分析文档：

- `logs/gesture_record_20260624_122930.jsonl`
- `working/ILoveYou手势切换模式流程分析.md`

## 1. 本次问题背景

用户实测：使用 `ILoveYou` 手势切换模式失败。过程记录在：

```text
logs/gesture_record_20260624_122930.jsonl
```

该日志的关键事实：

1. 第一次 `att_1` 失败是合理的：手掌水平位移很小，最终 timeout cancel。
2. 第二次 `att_2` 已生成 `mode_swipe_right`：

```text
timestamp = 443743.875
generated_events contains mode_swipe_right
dx ≈ 0.225
```

3. 日志中的 `mode` 仍显示 `standby`，不能直接证明状态机没有处理事件，因为当前 controller 在 `GestureState.step()` 之前调用了 recorder：

```text
gesture_controller.py:
  recorder.record_frame(...)
  mode_before = self.state.mode
  result = self.state.step(...)
```

所以 `mode` 记录的是事件处理前模式。

4. 第三次 `att_3` 接近成功，但在约 `0.844s` 时被 timeout cancel。当前默认：

```text
mode_swipe_timeout = 0.80
```

该阈值对真实手势偏紧，而且当前 `_update_attempt()` 先检查 timeout，再检查 commit，导致“刚达到位移阈值但略超时”的帧直接取消。

## 2. 对用户分析文档的判断

`working/ILoveYou手势切换模式流程分析.md` 中以下判断基本正确：

- 识别层能识别 ILoveYou。
- stable_gesture 能稳定到 ILoveYou。
- Tracker 能进入 armed/tracking。
- 第二次尝试确实生成了 `mode_swipe_right`。
- 第一次失败主要因为位移不足。

以下判断需要修正：

- “mode 字段仍为 standby，所以状态机未处理事件”不成立。当前 recorder 记录的是 `GestureState.step()` 之前的 mode。
- 文档中把 `mode_swipe_timeout` 写成 2.0 秒不符合当前代码和规范，当前默认是 0.80 秒。
- 第三次失败不应解释为“状态机未处理”，更接近 Tracker 超时策略过紧或 timeout/commit 顺序不合理。

## 3. 重要限制

本阶段只修复 ILoveYou 模式切换的可观测性和明显的 Tracker 超时不稳定问题。

禁止：

- 不要修改 `docs/` 下任何规范文档。
- 不要修改 README、启动脚本、模型文件、依赖文件。
- 不要重写状态机整体架构。
- 不要引入新依赖。
- 不要让 Tracker 直接执行动作、切换模式或管理 cooldown。
- 不要在 Tracker 或状态机中直接调用 `pyautogui`。
- 不要把屏幕像素阈值引入 Tracker 判定。
- 不要删除 Gesture Replay System。
- 不要修复 Open_Palm 翻页和 Victory 快速切换，除非新增测试表明它们被本次最小改动直接影响；这些问题后续单独用 replay log 修。
- 不要把环境失败写成“全部测试通过”。

允许：

- 增加必要的 replay/recorder 字段来证明状态机处理后的 mode。
- 微调 `mode_swipe_timeout` 或 timeout/commit 判定顺序，但必须有测试覆盖。
- 增加针对该实测日志的回放测试。

## 4. 允许读取的代码文件

除上面的 `docs/`、日志和分析文档外，只读取必要代码：

- `hands/gesture_controller.py`
- `hands/gesture_replay.py`
- `hands/gesture_intent_tracker.py`
- `hands/gesture_state.py`
- `hands/gesture_config.py`
- `tests/test_gesture_replay.py`
- `tests/test_gesture_intent_tracker.py`
- `tests/test_gesture_state.py`

如确需读取其他文件，必须在反馈文件中说明原因。

## 5. 允许修改的文件

只允许修改：

- `hands/gesture_controller.py`
- `hands/gesture_replay.py`
- `hands/gesture_intent_tracker.py`
- `hands/gesture_config.py`（仅限配置默认值或注释）
- `tests/test_gesture_replay.py`
- `tests/test_gesture_intent_tracker.py`
- `tests/test_gesture_state.py`（仅当状态机行为测试确实需要补充）
- `working/plan/task-iloveyou-replay-fix/changes.md`
- `working/plan/task-iloveyou-replay-fix/test-results.md`
- `working/plan/task-iloveyou-replay-fix/final-report.md`

不要修改其他文件。

## 6. 优先方案

### 任务 A：修复 recorder 的可观测性

当前记录的 `mode` 是 tracker 处理时的模式，也就是 `GestureState.step()` 前的模式。这会误导回放分析。

优先修复方案：

1. 保留现有 `mode` 字段，避免破坏旧日志读取。
2. 新增字段：

```text
mode_before_state_step
mode_after_state_step
state_result_mode
state_paused
generated_intents
mode_changed
```

3. 在 `gesture_controller._process_frame()` 中，把 recorder 调用移到 `state.step()` 之后，或者让 recorder 接收 step 前后模式和 intents。
4. `generated_events` 仍记录 Tracker 事件。
5. `generated_intents` 记录本帧状态机输出的 ActionIntent 摘要，至少包含 `type/key/keys/button/dx/dy/amount`。
6. `mode` 字段建议继续写处理前模式，或明确改为处理后模式；无论选择哪种，都必须在代码注释和测试中固定语义。推荐保留 `mode=mode_before_state_step`，新增 `mode_after_state_step` 解决歧义。

验收：

- 对一帧 `mode_swipe_right`，记录中能同时看到：

```text
mode_before_state_step = standby
mode_after_state_step = presentation
mode_changed = true
generated_events contains mode_swipe_right
```

### 任务 B：让 replay 能验证真实日志的状态机结果

当前 replay 会重新跑 Tracker 和 GestureState，但需要新增针对该真实日志的回归测试。

实现要求：

1. 新增测试读取 `logs/gesture_record_20260624_122930.jsonl`。
2. replay 时必须使用 `pause_on_start=False`、`start_paused=False`。
3. 验证回放至少出现一次：

```text
standby -> presentation
```

4. 验证 replay 生成过 `mode_swipe_right`。
5. 如果日志文件不存在，测试可以 skip，并说明原因；不要让 CI 因本地日志缺失失败。

验收：

- 该日志在 replay 中能复现一次 mode change。
- 测试名称要能说明这是“实测日志回归”。

### 任务 C：修复 ILoveYou 超时过紧导致的不稳定

基于实测日志，第三次尝试在约 `0.844s` 被 timeout cancel，而默认 `mode_swipe_timeout=0.80`。这对真实手势偏紧。

优先方案：

1. 将 `mode_swipe_timeout` 默认值从 `0.80` 调整到更实用的值，建议：

```text
mode_swipe_timeout = 1.20
```

2. 保持 `page_swipe_timeout = 0.80` 不变，避免扩大翻页误触风险。
3. 增加测试覆盖：一条 ILoveYou swipe 在 `0.84s ~ 1.10s` 内完成，应能提交 `mode_swipe_right`。
4. 保持 `min_motion_duration`、`iloveyou_swipe_threshold_x`、`swipe_threshold_y_limit` 不变，避免本阶段同时调多个参数。

备选方案：

- 如果不想改默认值，则修改 `_update_attempt()` 中 timeout 与 commit 的顺序：在超时附近如果当前帧已满足 commit 条件，优先 commit，再结束 attempt。
- 但该方案必须避免超过 timeout 很久仍提交。建议只允许很小宽限，例如 `now - att.started_at <= timeout + 0.10`。

优先采用“增大 `mode_swipe_timeout` 到 1.20 秒”，因为它更符合真实用户完成手势的时间，风险也比改判定顺序低。

## 7. 不要做的修复

本阶段不要处理：

- PPT Open_Palm 翻页失败。
- Victory HOLD 在 presentation / presentation_pen 快速来回切换。
- Closed_Fist。
- SolidWorks。
- 画笔/PINCH。
- 大规模重构 replay 文件格式。

这些问题需要新的对应 replay log 后单独修。

## 8. 必须新增或更新的测试

至少新增以下测试：

1. recorder 写入 step 前后 mode：

```text
mode_before_state_step = standby
mode_after_state_step = presentation
mode_changed = true
```

2. recorder 写入 `generated_intents`。

3. replay 实测日志：

```text
logs/gesture_record_20260624_122930.jsonl
```

若文件存在，应断言：

```text
mode_changes contains standby -> presentation
events_generated contains mode_swipe_right
```

若文件不存在，应 `pytest.skip()`，并在测试结果报告中说明。

4. Tracker 测试：ILoveYou swipe 持续约 0.9s 仍可提交。

5. Tracker 测试：明显超出 `mode_swipe_timeout` 且未满足位移阈值仍 cancel。

## 9. 测试命令

请运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_gesture_replay.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_gesture_intent_tracker.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_gesture_state.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_gesture_controller.py -q -k "not check_model_files"
.\.venv\Scripts\python.exe -m pytest tests -q
git diff --check -- hands\gesture_controller.py hands\gesture_replay.py hands\gesture_intent_tracker.py hands\gesture_config.py tests\test_gesture_replay.py tests\test_gesture_intent_tracker.py tests\test_gesture_state.py working\plan\task-iloveyou-replay-fix
```

如果全量测试中 `check_model_files` 或 Windows Temp 权限相关测试失败，要写成“环境失败”，不要写“全部通过”。

## 10. 验收标准

本阶段通过条件：

- `logs/gesture_record_20260624_122930.jsonl` replay 能显示至少一次 `standby -> presentation`。
- 新 recorder 日志不再用单个 `mode` 字段误导分析，必须能区分 step 前后 mode。
- `generated_events` 和 `generated_intents` 都能在同一帧中审查。
- ILoveYou 在约 0.9s 完成的真实速度下可提交。
- `page_swipe_timeout` 不被误改。
- Tracker 仍不执行动作、不切换模式、不管理 cooldown。
- 状态机仍负责模式切换和 cooldown。
- 所有新增/相关测试通过，或明确报告环境失败/未运行。

## 11. 反馈格式

完成后必须创建：

```text
working/plan/task-iloveyou-replay-fix/changes.md
working/plan/task-iloveyou-replay-fix/test-results.md
working/plan/task-iloveyou-replay-fix/final-report.md
```

`changes.md` 必须包含：

- 修改了哪些文件。
- recorder 字段语义：哪些是 step 前，哪些是 step 后。
- 是否调整了 `mode_swipe_timeout`，调整前后值。
- 是否没有修改 `page_swipe_timeout`。

`test-results.md` 必须包含：

- 每条测试命令。
- 结果：通过 / 环境失败 / 未运行。
- 如果跳过真实日志测试，说明日志文件不存在。
- 不允许把部分失败写成全部通过。

`final-report.md` 必须包含：

- 对用户分析文档的最终判断：哪些正确，哪些需要修正。
- 本次修复如何帮助定位 ILoveYou 切换问题。
- 后续 Open_Palm 翻页和 Victory 快速切换需要单独 replay log 分析，不在本阶段修。

## 12. 之前反复犯过的错误，必须避免

- 不要在没有读 `docs/` 规范前改代码。
- 不要把日志中的处理前 `mode` 当成状态机处理后的 `mode`。
- 不要把 `raw_gesture=None, hand_present=True` 当成真正手丢失。
- 不要用固定帧数替代真实时间判断。
- 不要使用屏幕像素作为 Tracker 判断阈值。
- 不要在正常连续动作结束时滥用 `release_all`。
- 不要让同一 attempt 重复 committed。
- 不要写临时 debug 脚本后忘记删除。
- 不要修改不在允许列表中的文件。
- 不要把环境失败、跳过、未实机验证写成测试通过。
