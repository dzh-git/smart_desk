# Test Results — Task 105

## 基线对比

| 套件 | Baseline | 当前 | 差异 |
|---|---|---|---|
| 全量 | 188 passed, 4 skipped | **197 passed, 4 skipped** | **+9** |
| test_speech_websocket_blackbox | 8 passed, 1 skipped | 15 passed, 1 skipped | +7 |
| test_speech_stream_service | 21 passed | **23 passed** | **+2** |
| test_seat_service | 44 passed | 44 passed | 0 |

## 新增测试覆盖

| 测试方法 | 覆盖点 | 耗时 |
|---|---|---|
| `test_binary_before_start_no_db_write` | binary-before-start 不缓冲、不运行 ASR、不落库 | ~1s |
| `test_speaker_switch_cancels_old_interim` | set_speaker_seat 1→2: old WS 关闭、cancelled 广播、无 DB 写 | ~14s |
| `test_clear_speaker_cancels_interim` | clear_speaker_seat: cancelled 广播、无 DB 写 | ~14s |
| `test_new_speaker_can_connect_after_switch` | 切换后新 seat 可连接并 start | ~1s |
| `test_duplicate_speech_ws_connection_closes_old` | 重复连接时旧 WS 失效 + 自动关闭 + 不落库 | ~15s |
| `test_old_speech_ws_rejects_messages_after_speaker_switch` | 切换后旧 WS binary/end_hint 被拒绝 + 不落库 | ~15s |
| `test_remove_session_with_wrong_token_does_not_delete` | 单元: 旧 token 调 remove 不删新 session | <1s |
| `test_duplicate_ws_identity_safe_cleanup_preserves_new_session` | 黑盒: 重复连接后新 WS final 链路完整 | ~17s |
| `test_same_key_reconnect_generates_increasing_ids` | 单元: 同 key 重建 session 后 utterance_id 继续递增 | <1s |

## 详细结果

```text
$ pytest tests/test_speech_websocket_blackbox.py -q
...s............
15 passed, 1 skipped

$ pytest tests/test_speech_stream_service.py -q
.......................
23 passed

$ pytest tests/test_seat_service.py -q
............................................
44 passed

$ pytest -q
[............................................................]
197 passed, 4 skipped
```

## 验证摘要

- [x] 所有现有 Phase 2/3/4 测试通过
- [x] binary-before-start 返回明确错误 `SPEECH_WS_NOT_STARTED`，不落库
- [x] speaker seat 1→2 切换关闭旧 WS、广播 translation_interim_cancelled(reason=speaker_seat_changed)
- [x] clear_speaker_seat 同样清理旧 WS 并广播 cancelled
- [x] 新 Speaker Seat 可立即建立新连接并 start
- [x] 旧 utterance 即使有 interim 但未 end_hint，切换后不写 translation_records
- [x] SpeechWSRegistry 不干扰普通 /ws/{meeting_id} 广播通道
- [x] 关闭/断开连接时 registry 和 stream session 正确清理
- [x] **重复连接**: 旧 WS 立即标记失效 (invalidation flag)，close 调度；不再处理业务消息
- [x] **切换后消息拒绝**: 旧 WS 即使在 close frame 到达前收到消息，invalidation 检查也会在消息循环入口拦截
- [x] **identity-safe 注销**: `unregister(meeting_id, seat_id, ws)` 只移除匹配的 WS，防止旧 handler 误删新连接
- [x] **stream session identity-safe cleanup**: `session_token` 保证旧 WS 的 `remove_session` 不删新 session
- [x] **重复连接后新 WS final 链路验证**: ws2 发 `end_hint` → `finalize_utterance` 成功 → DB 有记录
- [x] **单元测试**: 旧 token 调 `remove_session` 返回 False，新 session 完整保留
- [x] **utterance_id 跨重连唯一**: `_utterance_sequences` 独立于 session 生命周期；ws1→ws2 重连后 uid2 != uid1 且递增
- [x] **黑盒测试 uid1/uid2 可区分**: ws2 final 后 DB 仅 uid2 存在，uid1 不存在
- [x] 现有 Phase 2/3/4 全部测试通过，无回归
