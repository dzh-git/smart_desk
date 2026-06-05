# Phase 2 验收修复报告

## 概述
修复 SmartDesk Speech Phase 2 的验收问题：清理测试文件中不属于 Phase 2 范围的占位测试、别名测试和未使用的辅助代码。

---

## 修改文件列表

| 文件 | 操作 |
|------|------|
| `tests/test_speech_websocket_blackbox.py` | **重写** — 仅保留 2 个 Phase 2 测试，其余全部删除 |
| `working/plan/task-102/changes.md` | **更新** — 反映最终状态 |
| `working/plan/task-102/test-results.md` | **更新** — 验收结果 |

未修改 `backend/main.py`、`backend/websocket/speech_ws.py`、`backend/services/speech_stream_service.py`——后端实现本身无需修复。

---

## 删除/调整了哪些 Phase 3+ 占位测试

### 删除了 5 个测试函数（3 个 Phase 3+ 占位 + 2 个别名）

| 删除的测试 | 类型 | 原因 |
|-----------|------|------|
| `test_pcm16_binary_triggers_interim_broadcast` | Phase 3+ 占位 | 主动 `pytest.fail("[NOT IMPLEMENTED]")`——Phase 3 会添加自己的 RED 测试 |
| `test_final_produces_translation_final_and_persists` | Phase 3+ 占位 | 同上 |
| `test_speaker_seat_switch_closes_old_and_broadcasts_cancelled` | Phase 3+ 占位 | 同上 |
| `test_non_speaker_seat_is_rejected` | 别名副本 | 语义等价于 `test_non_speaker_seat_cannot_start_speech_ws`，只保留规范命名 |
| `test_speaker_seat_start_gets_started_with_utterance_id` | 别名副本 | 语义等价于 `test_speaker_seat_can_start_speech_ws`，只保留规范命名 |

### 同时删除的关联代码

- `_enable_dev_api` fixture（仅被 scenario 5 使用）
- `_add_attendee_and_checkin` 辅助函数（仅被 scenario 5 使用）
- `_make_pcm16_frame` 辅助函数（仅被 scenario 3/4/5 使用）
- 不再需要的导入：`math`、`struct`、`time`

### 未使用的文件保持原样

以下文件在本次修复中未修改（后端实现本身无问题）：

```
backend/main.py
backend/websocket/speech_ws.py
backend/services/speech_stream_service.py
```

---

## 四条验证命令的结果

### 命令 1：非 Speaker Seat 拒绝

```bash
pytest tests/test_speech_websocket_blackbox.py::TestSpeechWebSocketBlackBox::test_non_speaker_seat_cannot_start_speech_ws -q
```

```
1 passed in 0.87s ✅
```

测试内容：Speaker Seat = 1，连接 `/ws/speech/{mid}?seat=3` → 收到 `{"type": "error", "code": "NOT_SPEAKER_SEAT"}`。

### 命令 2：Speaker Seat start 流程

```bash
pytest tests/test_speech_websocket_blackbox.py::TestSpeechWebSocketBlackBox::test_speaker_seat_can_start_speech_ws -q
```

```
1 passed in 0.95s ✅
```

测试内容：Speaker Seat = 1，连接 → 发送 `start` → 收到 `{"type": "started", "utterance_id": "utt_1_1_000001", "session_key": "speech_1_1"}`。

### 命令 3：完整测试文件

```bash
pytest tests/test_speech_websocket_blackbox.py -q
```

```
2 passed in 1.56s ✅
```

零 skip、零 xfail、零 fail。仅收集到 2 个 Phase 2 测试。

### 命令 4：完整后端套件

```bash
pytest tests/test_websocket_integration.py tests/test_speech_websocket_blackbox.py \
      tests/test_seat_service.py tests/test_meeting_service.py \
      tests/test_votes_router.py tests/test_service_calls_router.py \
      tests/test_dev_api.py -q
```

```
146 passed in 58.99s ✅
```

零回归。所有现有业务功能不受影响。

---

## 验收标准检查表

| 标准 | 结果 |
|------|------|
| 四条命令全部通过 | ✅ |
| 无 `skip` | ✅ |
| 无 `xfail` | ✅ |
| 无主动 `pytest.fail()` 测试 | ✅ |
| 仅包含 Phase 2 已实现能力的测试 | ✅ |
| 不修改 `speech_module/` | ✅ |
| 不实现 Phase 3+ 功能 | ✅ |
| utterance_id 格式严格验证 `utt_{mid}_{seat}_{seq:06d}` | ✅（正则 `re.match`） |
| session_key 格式验证 `speech_{mid}_{seat}` | ✅ |

---

## 是否可以进入 Phase 3

**是。** Phase 2 验收问题已全部修复。测试文件干净、精确、只测试已实现的能力。Phase 3 可以在此基础上添加自己的 RED 测试（interim 广播、final 持久化、Speaker 切换关闭旧 WS）。
