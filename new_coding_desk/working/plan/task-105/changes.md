# Task 105 — Speech Phase 5: Speaker Seat 硬切换与 interim cancelled

包括验收修复：重复连接强关闭、旧 WS 消息拒绝、identity-safe 注销。

## 修改文件列表

| 文件 | 操作 | 说明 |
|---|---|---|
| `backend/websocket/speech_registry.py` | **新增** | SpeechWSRegistry — 按 (meeting_id, seat_id) 跟踪 + 失效标记 + identity-safe 注销 |
| `backend/websocket/speech_ws.py` | 修改 | 注册/注销 registry; binary-before-start 守卫; 消息循环 invalidation 检查 |
| `backend/services/seat_service.py` | 修改 | set_speaker_seat/clear_speaker_seat 集成硬切换; mark_invalidated |
| `backend/services/speech_stream_service.py` | 修改 | SpeechStreamSession.session_token; create_session 返回 (key, token); remove_session identity-safe; `_utterance_sequences` 跨 session 递增 |
| `backend/websocket/speech_ws.py` | 修改 | 接收/传递 session_token |
| `tests/test_speech_stream_service.py` | 修改 | 适配新 API; 新增 TestIdentitySafeCleanup + TestUtteranceIdUniqueness |
| `tests/test_speech_websocket_blackbox.py` | 修改 | 添加 8 个新测试; 修复 uid1/uid2 断言 |

未修改:
- `backend/services/speech_stream_service.py` — 仅通过 `cancel_utterance` / `get_session` 接口被调用
- `backend/events/translation_events.py` — TranslationInterimCancelledEvent 已定义
- `docs/WEBSOCKET_PROTOCOL.md` — §5、§7 已定义 speaker_seat_changed 协议
- `docs/API_SPEC.md` — 接口签名未变化
- `backend/speech_module/` — 不修改

## 旧 speech WS 如何定位和关闭

**定位**: `SpeechWSRegistry` (speech_registry.py) 维护 `_by_seat: dict[(meeting_id, seat_id), WebSocket]`。

**关闭流程** (SeatService._handle_speaker_seat_switch):
1. `stream_service.cancel_utterance(old_key)` — 清空 buffer、重置 revision、取消 SpeechModule 状态
2. `event_bus.publish(TranslationInterimCancelledEvent(...))` — 同步发布被取消事件
3. `speech_registry.close_seat(meeting_id, old_seat_id)` — 在主事件循环上调度 `ws.close(code=4001)`
4. WS handler 的 `receive()` 收到 `WebSocketDisconnect` → `finally` 中调用 `remove_session` + `speech_registry.unregister`
5. `WebSocketEventHandler` 将 `TranslationInterimCancelledEvent` 广播到 `/ws/{meeting_id}`

`close_seat` 是线程安全的：如果从同步 HTTP 路由调用，通过 `asyncio.run_coroutine_threadsafe(coro, loop)` 调度到主循环；如果从异步上下文调用，直接 `loop.create_task()`。

## translation_interim_cancelled payload 示例

```json
{
  "event": "translation_interim_cancelled",
  "meeting_id": 1,
  "timestamp": 1748700000,
  "payload": {
    "utterance_id": "utt_1_1_000005",
    "seat_id": 1,
    "reason": "speaker_seat_changed"
  }
}
```

- `utterance_id` — 被取消的 utterance ID；若无可用的则为空字符串
- `seat_id` — 旧 Speaker Seat 编号
- `reason` — 固定 `"speaker_seat_changed"` (与 `cancel` 消息产生的 `"user_cancelled"` 区分)

## 重复连接时旧 WS 如何关闭/拒绝

`speech_registry.register()` 检测到已存在相同 `(meeting_id, seat_id)` 的旧连接时：

1. **标记失效**: `self._invalidated.add(id(old_ws))` — 使旧 WS 立即停止处理业务消息
2. **调度关闭**: 通过 `loop.create_task(self._do_close(old_ws))` 或 `asyncio.run_coroutine_threadsafe` 异步关闭旧 WS
3. **替换注册**: 新 WS 接管 registry 中的 `(meeting_id, seat_id)` 条目

**identity-safe 注销**: `unregister(meeting_id, seat_id, ws)` 会检查 `self._by_seat.get(key) is ws`，只有匹配的 WS 才能移除对应的 registry 条目。这防止了旧 handler 在 finally 中误删新连接的条目。

同时 `stream_service.create_session()` 也会替换相同 key 的 session，旧 session 被替换后在旧 handler 的 finally 中通过 `remove_session` 清理。

## Speaker Seat 切换后旧 WS 如何阻止继续处理消息

两层防护:

### 第 1 层 — Invalidation Flag (消息循环检查)

`SeatService._handle_speaker_seat_switch()` 中:
```python
old_ws = speech_registry.get(meeting_id, old_seat_id)
if old_ws is not None:
    speech_registry.mark_invalidated(old_ws)
speech_registry.close_seat(meeting_id, old_seat_id)
```

`close_seat()` 是异步关闭（`ws.close(4001)`），在关闭执行前旧 handler 可能还能 `receive()` 到消息。`mark_invalidated()` 设置内存标记，**在消息循环每次迭代开始前**检查:

```python
if speech_registry.is_invalidated(ws):
    await ws.send_json(ERROR_NOT_SPEAKER_SEAT)
    break  # 退出循环 → finally 清理
```

这保证了即使 WS 尚未收到 close frame，所有后续消息（start/binary/end_hint/cancel）都被立即拒绝，不会进入 `_handle_text_message` 或 `_handle_binary_message`。

### 第 2 层 — cancel_utterance 清空 Buffer

`_handle_speaker_seat_switch` 首先调用 `stream_service.cancel_utterance(old_key)` 清空 audio buffer。这确保了即使有 race（invalidation 检查通过后才被标记，但极低概率），`end_hint` 的 `finalize_utterance` 也返回 None。

### 效果
- 旧 WS 的 start 被拒绝 → 不产生新 utterance
- 旧 WS 的 binary 被拒绝 → 不缓冲音频、不运行 ASR
- 旧 WS 的 end_hint 被拒绝 → 不落库、不广播 translation_final
- 同时 `translation_interim_cancelled(reason="speaker_seat_changed")` 正常广播

## stream session identity-safe cleanup 设计说明

### 问题

`SpeechStreamService` 之前用 `session_key = speech_{meeting_id}_{seat_id}` 作为唯一标识。当第二个 WS 连接同一 seat 时:
1. `create_session(meeting_id, seat_id)` 用相同 key 替换 `_sessions[session_key]` → 旧 session 对象被丢弃
2. 旧 WS handler 的 `finally` 块调用 `remove_session(session_key)` → `self._sessions.pop(key, None)` **无条件删除**，即使 key 现在指向新 session

**结果**: 新 WS 的 session 被旧 WS 的 cleanup 误删。新 WS 的 `finalize_utterance` 返回 None，无法落库。

### 设计

每 个 `SpeechStreamSession` 在 `__init__` 时生成唯一 `session_token = uuid.uuid4().hex`:

```python
class SpeechStreamSession:
    def __init__(self, meeting_id, seat_id, session_key):
        self.session_token: str = uuid.uuid4().hex  # unique per instance
        ...
```

`create_session` 返回 `(session_key, session_token)`:

```python
def create_session(self, meeting_id, seat_id) -> tuple[str, str]:
    session = SpeechStreamSession(meeting_id, seat_id, session_key)
    self._sessions[session_key] = session
    return session_key, session.session_token
```

`remove_session` 检查 token 是否匹配，匹配才删除:

```python
def remove_session(self, session_key, session_token) -> bool:
    session = self._sessions.get(session_key)
    if session is None or session.session_token != session_token:
        return False  # identity-safe: let caller know it was skipped
    del self._sessions[session_key]
    # cleanup SpeechModule._sessions[session_key]
    return True
```

### 效果

| 场景 | ws1 (旧) remove_session | ws2 (新) session |
|---|---|---|
| ws2 未连接 | token 匹配 → session 正常删除 | — |
| ws2 重复连接 (同 key) | token **不匹配** → 跳过 | **完整保留** |
| Speaker Seat 切换 | token 不匹配 → 跳过 | 保留 (但 Speaker Seat 切换另有 invalidation 关闭 ws2) |

`speech_ws.py` 中 `create_session` 的调用改为:

```python
session_key, session_token = stream_service.create_session(meeting_id, seat_id)
```
然后在 `finally` 中:
```python
stream_service.remove_session(session_key, session_token)
```

## utterance_id 跨重连唯一性设计

### 问题

`generate_utterance_id()` 之前从 `session.utterance_count` 递增。当第二个 WS 同 seat 重连时，新的 `SpeechStreamSession` 的 `utterance_count` 从 0 开始，ws1 和 ws2 都得到 `utt_1_1_000001`。违反 ADR 0003 的后端唯一性保证。

### 设计

`SpeechStreamService` 新增 `_utterance_sequences: dict[tuple[int, int], int]`，key 为 `(meeting_id, seat_id)`，value 为全局递增序列号：

```python
def __init__(self) -> None:
    ...
    self._utterance_sequences: dict[tuple[int, int], int] = {}

def generate_utterance_id(self, meeting_id: int, seat_id: int) -> str:
    key = (meeting_id, seat_id)
    seq = self._utterance_sequences.get(key, 0) + 1
    self._utterance_sequences[key] = seq
    uid = f"utt_{meeting_id}_{seat_id}_{seq:06d}"
    # Also sync session.utterance_count for internal consistency
    return uid
```

`_utterance_sequences` 独立于任何 `SpeechStreamSession` 的生命周期，确保同 (meeting, seat) 下的所有连接共享同一个递增计数器。会议结束后不做清理（保证运行期唯一）。

### 重复连接示例

| 连接 | 操作 | utterance_id | 序列号 |
|---|---|---|---|
| ws1 | `start` | `utt_1_1_000001` | 1 |
| ws1 (断线) | — | — | — |
| ws2 重连 | `start` | `utt_1_1_000002` | 2 (递增!) |
| ws2 | `start` | `utt_1_1_000003` | 3 |

之前: ws2 也得 `utt_1_1_000001` (冲突)。现在: ws2 得 `utt_1_1_000002` (唯一)。

### 测试

**单元测试** `TestUtteranceIdUniqueness.test_same_key_reconnect_generates_increasing_ids`:
- `create_session(1,1)` → `generate_utterance_id(1,1)` → `utt_1_1_000001`
- `create_session(1,1)` (同 key 重建) → `generate_utterance_id(1,1)` → `utt_1_1_000002`
- 三次调用 → `utt_1_1_000003`

**黑盒测试** 更新:
- `test_duplicate_speech_ws_connection_closes_old`: 恢复 `assert uid2 != uid1`，删除 "may collide" 注释
- `test_duplicate_ws_identity_safe_cleanup_preserves_new_session`: 新增 `uid2 != uid1` 断言; 分别 check DB 中 uid1 不存在、uid2 存在

### 测试

**单元测试** `TestIdentitySafeCleanup.test_remove_session_with_wrong_token_does_not_delete`:
- 创建 session S1 (token1), 创建 session S2 (token2) 替换
- `remove_session(key, token1)` → False (跳过), `_sessions[key]` 仍是 S2
- `remove_session(key, token2)` → True (删除), `_sessions[key]` 为 None

**黑盒测试** `test_duplicate_ws_identity_safe_cleanup_preserves_new_session`:
1. ws1 连接, start, 发 5 帧音频 → uid1
2. ws2 连接 (同 seat) → 替换 ws1 的 session → uid2
3. `ws1.close()` → 触发 ws1 handler finally → `remove_session(key, token_ws1)` → **跳过** (token 不匹配)
4. ws2 `send_json({"type": "end_hint"})` → `finalize_utterance` 成功 → DB 记录
5. 断言: 记录存在且仅 1 条 (ws1 的 end_hint 未泄漏)

## binary-before-start 修复说明

**问题**:
`_handle_binary_message` 在 `process_pcm_frame` 返回后才检查 `result["utterance_id"] is None`，但 `process_pcm_frame` 内部会先调用 `append_audio` 缓冲 PCM16 字节。这意味着未 start 时发送的 binary frame 会：
- 缓冲音频到 `_utterance_buffer`（违反不得缓存要求）
- 运行 ASR（如果模型已加载）
- 递增 revision 计数器

**修复** (speech_ws.py `_handle_binary_message`):
1. 在调用 `process_pcm_frame` **之前**检查 `session.current_utterance_id`
2. 若为空，发送 `SPEECH_WS_NOT_STARTED` 错误：
   ```json
   {"type": "error", "code": "SPEECH_WS_NOT_STARTED", "message": "Send 'start' before streaming audio"}
   ```
3. 立即返回，不缓冲、不运行 ASR、不发布事件

**测试验证** (`test_binary_before_start_no_db_write`):
- 不发送 `start` → 发 PCM frame → 收到 SPEECH_WS_NOT_STARTED
- 发 `end_hint` → 无操作 (buffer 为空)
- 查询 `GET /api/translations` → 没有记录
