# Task 101 — 语音 WebSocket 黑盒测试：测试运行结果

## 运行命令

```bash
pytest tests/test_speech_websocket_blackbox.py -q
```

## 汇总

| 结果 | 数量 |
|------|------|
| 通过 | 0 |
| 失败 | **5** |
| 跳过 | 0 |

## 逐场景分析

### Scenario 1 — 非 Speaker Seat 连接被拒绝

```
FAILED: [MISSING FEATURE] Scenario 1 — Non-speaker seat rejected.
  URL: /ws/speech/1?seat=3
  Expected: WS message {'type': 'error', 'code': 'NOT_SPEAKER_SEAT'}
  Got: WebSocketDisconnect:
  Required: /ws/speech/{meeting_id} endpoint has not been registered in backend/main.py.
```

**结论：** 预期失败 ✓。端点未注册时，Starlette 路由器返回 close frame (code=1000)。测试代码正确：如果端点存在，它会尝试接收 JSON 并断言 `NOT_SPEAKER_SEAT`。

**缺失功能：**
1. `backend/main.py` — 注册 `/ws/speech/{meeting_id}` 路由
2. `backend/websocket/` — speech WS handler（验证 speaker seat 身份）

---

### Scenario 2 — Speaker Seat start → started + utterance_id

```
FAILED: [MISSING FEATURE] Scenario 2 — Speaker seat start flow.
  Expected: send 'start' → receive 'started' with utterance_id
  Got: WebSocketDisconnect:
  Phase 2 must: ...
```

**结论：** 预期失败 ✓。与 Scenario 1 相同的根本原因。

**缺失功能：**
1. 端点注册
2. `start` 控制消息处理
3. `utterance_id` 生成（ADR 0003 格式 `utt_{meeting_id}_{seat_id}_{seq:06d}`）
4. `started` 响应（含 `session_key`）

---

### Scenario 3 — PCM16 binary → translation_interim 广播

```
FAILED: [MISSING FEATURE] Scenario 3 — PCM16 interim broadcast.
  Expected: PCM16 frame → translation_interim on broadcast channel
  Got: WebSocketDisconnect:
  Phase 2 must: ...
```

**结论：** 预期失败 ✓。在 PCM16 阶段之前失败（甚至更早）。

**缺失功能：**
1. 端点注册
2. PCM16 binary frame 接收和解析
3. `SpeechStreamService` — 流式 ASR 管道
4. `TranslationInterimEvent` — EventBus 事件类型
5. `WebSocketEventHandler.BROADCAST_EVENTS` — 添加 `translation_interim`

---

### Scenario 4 — Final → translation_final + GET 可查

```
FAILED: [MISSING FEATURE] Scenario 4 — Final + persistence.
  Expected: 'end_hint' → translation_final broadcast + GET /api/translations queryable
  Got: WebSocketDisconnect:
  Phase 2 must: ...
```

**结论：** 预期失败 ✓。`TranslationService.process_final()` 已存在但 speech WS 未接入。

**缺失功能：**
1. 端点注册
2. `end_hint` 控制消息处理
3. Speech WS → `TranslationService.process_final()` 集成
4. `translation_final` EventBus 发布（事件类已存在但未连接）

---

### Scenario 5 — Speaker Seat 切换 → 旧连接关闭 + cancelled 广播

```
FAILED: [MISSING FEATURE] Scenario 5 — Speaker seat switch.
  Expected: POST /api/seats/speaker → old WS closes + translation_interim_cancelled broadcast
  Got: WebSocketDisconnect:
  Phase 2 must: ...
```

**结论：** 预期失败 ✓。

**缺失功能：**
1. 端点注册
2. `SeatService.set_speaker_seat()` — 集成强制关闭旧 speech WS
3. `TranslationInterimCancelledEvent` — EventBus 事件类型
4. `WebSocketEventHandler.BROADCAST_EVENTS` — 添加 `translation_interim_cancelled`
5. `WebSocketService` — 支持按 seat_id 和 meeting_id 定位并关闭特定连接

## 总体判断

| 标准 | 结果 |
|------|------|
| 测试代码是否正确？ | 是 — 所有消息格式和业务流程均符合 WEBSOCKET_PROTOCOL 和 ADR |
| 测试是否因缺失功能而失败？ | 是 — 100% 因 `/ws/speech/` 端点未注册 |
| 是否有测试代码导致的失败？ | 否 — 全部归因于后端未实现 |
| 是否可以进入 Phase 2？ | **是** |

## 缺失功能汇总（Phase 2 清单）

| # | 组件 | 文件 | 说明 |
|---|------|------|------|
| 1 | WS 路由 | `backend/main.py` | 注册 `@app.websocket("/ws/speech/{meeting_id}")` |
| 2 | Speech WS Handler | `backend/websocket/speech_handler.py` (new) | 连接验证、msg 分发、binary 处理 |
| 3 | SpeechStreamService | `backend/services/speech_stream_service.py` (new) | 流式状态管理、VAD 集成、interim 发布 |
| 4 | Interim 事件 | `backend/events/translation_events.py` | 新增 `TranslationInterimEvent`, `TranslationInterimCancelledEvent` |
| 5 | 广播注册 | `backend/websocket/event_handler.py` | `BROADCAST_EVENTS` 添加 `translation_interim`, `translation_interim_cancelled` |
| 6 | WS 连接追踪 | `backend/websocket/ws_service.py` | 支持按 seat_id 查找/关闭连接 |
| 7 | Speaker 切换钩子 | `backend/services/seat_service.py` | `set_speaker_seat()` 中断旧 speech WS |
