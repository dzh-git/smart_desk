# Task 102 — 后端 speech WebSocket 连接与 Speaker Seat 权限

## 目标
实现 `/ws/speech/{meeting_id}?seat=N` 端点的连接、权限验证和 `start` 控制消息。

## 修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/services/speech_stream_service.py` | **新增** | SpeechStreamService — 会话管理、utterance_id 生成 |
| `backend/websocket/speech_ws.py` | **新增** | Speech WebSocket handler — 连接、验证、消息循环 |
| `backend/main.py` | **修改** | 注册 `/ws/speech/{meeting_id}` 路由 |
| `tests/test_speech_websocket_blackbox.py` | **修改** | 仅保留 Phase 2 的 2 个测试，删除 Phase 3+ 占位和别名 |
| `working/plan/task-102/changes.md` | **新增** | 本文件 |
| `working/plan/task-102/test-results.md` | **新增** | 测试结果 |

## 实现总结

### 新增文件

**`backend/services/speech_stream_service.py`**:
- `SpeechStreamSession` — 单个会话（meeting_id, seat_id, session_key, utterance_count）
- `SpeechStreamService` — 会话生命周期管理、utterance_id 生成（格式 `utt_{meeting_id}_{seat_id}_{seq:06d}` per ADR 0003）
- 模块级单例 `stream_service`

**`backend/websocket/speech_ws.py`**:
- `handle_speech_ws()` — 异步 WS 处理器
  - 接受连接 → 验证 seat 范围 (1-10) → 验证 meeting active → 验证 speaker seat → 消息循环
  - `start` 消息 → 生成 utterance_id → 返回 `started`
  - PCM16 binary → 无操作（Phase 2 不做 ASR）
  - `end_hint` / `cancel` → 无操作
  - 非 speaker seat / 无效 meeting → 发送 error JSON + 关闭连接

### 修改文件

**`backend/main.py`**:
- 新增 `from backend.websocket.speech_ws import handle_speech_ws`
- 新增 `@app.websocket("/ws/speech/{meeting_id}")` 端点，`Query(seat)` 为必填参数

**`tests/test_speech_websocket_blackbox.py`**:
- `test_non_speaker_seat_cannot_start_speech_ws` — 非 Speaker Seat 连接 → `NOT_SPEAKER_SEAT`
- `test_speaker_seat_can_start_speech_ws` — Speaker Seat → `start` → `started` + utterance_id
- utterance_id 格式验证：`utt_{meeting_id}_{seat_id}_{seq:06d}`（正则匹配）
- **删除** 3 个 Phase 3+ 占位测试（`test_pcm16_binary_triggers_interim_broadcast`、`test_final_produces_translation_final_and_persists`、`test_speaker_seat_switch_closes_old_and_broadcasts_cancelled`）
- **删除** 2 个别名测试（`test_non_speaker_seat_is_rejected`、`test_speaker_seat_start_gets_started_with_utterance_id`）
- **删除** 未使用的 `_enable_dev_api` fixture、`_add_attendee_and_checkin`、`_make_pcm16_frame`、`time`/`math`/`struct` 导入

## 协议验证

| 检查点 | WEBSOCKET_PROTOCOL | 实现 |
|--------|-------------------|------|
| 端点路径 | `/ws/speech/{meeting_id}?seat=N` | ✅ |
| seat 范围 1-10 | §3 | ✅ |
| meeting 存在且 active | §3 | ✅ |
| seat == SpeakerSeat | §3 | ✅ |
| 非 Speaker 返回 `NOT_SPEAKER_SEAT` | §3 | ✅ |
| `start` → `started` + utterance_id | §3, ADR 0003 | ✅ |
| `started` 含 session_key | §3 | ✅ |
| utterance_id 格式 `utt_M_S_SEQ` | ADR 0003 | ✅ |
| 拒绝消息后关闭连接 | §3 | ✅ |
| 非 Speaker 不进入消息循环 | §3 | ✅ |
