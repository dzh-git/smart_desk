# Task 101 — 语音 WebSocket 黑盒测试

## 目标
为 SmartDesk Speech Phase 1 编写语音 WebSocket 黑盒测试，验证 `/ws/speech/{meeting_id}?seat=N` 端点的完整协议交互。

## 修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `tests/test_speech_websocket_blackbox.py` | **新增** | 语音 WebSocket 黑盒测试，覆盖 5 个场景 |
| `working/plan/task-101/changes.md` | **新增** | 本文件 |
| `working/plan/task-101/test-results.md` | **新增** | 测试运行结果 |

## 禁止修改
- `speech_module/` — 旧实现参考代码
- `frontend/`
- `docs/adr/`
- 业务代码（本阶段只写测试）
- mock fallback（真实模型不可用应作为环境问题记录）

## 测试场景

| # | 场景 | 预期行为 | 当前状态 |
|---|------|----------|----------|
| 1 | 非 Speaker Seat 连接到 speech WS | 被拒绝，返回 NOT_SPEAKER_SEAT | 端点缺失 |
| 2 | Speaker Seat 发送 start | 收到 started + utterance_id | 端点缺失 |
| 3 | PCM16 binary frame → translation_interim 广播 | 会议广播通道收到 interim | 端点缺失 |
| 4 | Final → translation_final 广播 + API 可查 | 会议广播收到 + GET 可查 | 端点缺失 |
| 5 | Speaker Seat 切换 → 旧连接关闭 + cancelled 广播 | 旧 WS 关闭 + interim_cancelled | 端点缺失 |

## 缺失功能清单（Phase 2 需要实现）

1. `backend/main.py` — 注册 `/ws/speech/{meeting_id}` WebSocket 端点
2. `backend/websocket/` — 新增 speech WS handler（验证 speaker seat、处理 start/end_hint/cancel、PCM16 binary 帧）
3. `backend/services/speech_stream_service.py` — 新增 SpeechStreamService（管理 utterance 生命周期、VAD、interim 发布）
4. `backend/events/translation_events.py` — 新增 TranslationInterimEvent（interim 和 cancelled 事件类型）
5. `backend/websocket/ws_service.py` — 新增 speaker seat 变更时强制关闭旧 speech WS 连接逻辑
