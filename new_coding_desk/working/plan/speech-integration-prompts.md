# SmartDesk Speech Integration Claude Code Prompts

Use these prompts one phase at a time from:

```text
D:\Ai_project\smart_desktop\new_coding_desk
```

Global rule for every phase:

```text
speech_module/ is legacy reference code. Do not modify it.
```

---

## Phase 1: Backend Black-Box Tests First

```text
请执行 SmartDesk Speech Phase 1：语音 WebSocket 黑盒测试先行。

当前工作目录：
D:\Ai_project\smart_desktop\new_coding_desk

你是实现者，不要分派子 agent。

重要限制：
- speech_module/ 是旧实现参考代码，不得修改。
- 不得修改 frontend/。
- 不得修改 docs/adr/。
- 不得实现业务代码，本阶段只写测试。
- 不得实现 mock fallback，真实模型不可用应作为环境问题记录。

允许读取：
- docs/API_SPEC.md
- docs/WEBSOCKET_PROTOCOL.md
- docs/EVENT_BUS_SPEC.md
- docs/system_architecture.md
- docs/adr/
- backend/
- tests/
- git status

允许修改：
- tests/test_speech_websocket_blackbox.py
- working/plan/task-101/changes.md
- working/plan/task-101/test-results.md
- working/env-issues.md（仅当真实环境问题阻塞且已尝试 3 种方案）

任务：
1. 新增语音 WebSocket 黑盒测试。
2. 覆盖：
   - 非 Speaker Seat 连接 /ws/speech/{meeting_id}?seat=N 被拒绝。
   - Speaker Seat 连接成功后发送 start，收到 started 和后端生成的 utterance_id。
   - 发送 PCM16 binary frame 后，会议广播通道能收到 translation_interim。
   - final 后，会议广播通道收到 translation_final，GET /api/translations 可查询记录。
   - Speaker Seat 切换后旧连接关闭，并广播 translation_interim_cancelled。
3. 当前业务代码尚未实现，测试应失败；失败原因必须指向缺失功能，而不是测试写错。

必须运行：
pytest tests/test_speech_websocket_blackbox.py -q

反馈要求：
- 修改文件列表
- 每个测试场景的当前结果
- 失败是否符合预期
- 是否可以进入 Phase 2
```

---

## Phase 2: Speech WS Connection And Speaker Seat Permission

```text
请执行 SmartDesk Speech Phase 2：后端 speech WebSocket 连接与 Speaker Seat 权限。

重要限制：
- speech_module/ 是旧实现参考代码，不得修改。
- 不得修改 frontend/。
- 不得修改 docs/adr/。
- 不得修改接口文档，除非发现实现与文档明显冲突，先记录到 working/task-issues.md。
- 不得实现 mock fallback。

允许读取：
- docs/API_SPEC.md
- docs/WEBSOCKET_PROTOCOL.md
- docs/EVENT_BUS_SPEC.md
- docs/system_architecture.md
- backend/
- tests/
- working/plan/task-101/

允许修改：
- backend/main.py
- backend/websocket/speech_ws.py
- backend/services/speech_stream_service.py
- tests/test_speech_websocket_blackbox.py
- working/plan/task-102/changes.md
- working/plan/task-102/test-results.md

任务：
1. 新增 /ws/speech/{meeting_id}?seat=N。
2. 校验 meeting 存在且 active。
3. 校验 seat 是当前 Speaker Seat。
4. 支持 start 控制消息。
5. start 后生成 utterance_id，格式 utt_{meeting_id}_{seat_id}_{seq}。
6. 返回 started 消息。
7. 非 Speaker Seat 连接必须失败或立即关闭，并返回明确错误。
8. 不处理真实 ASR，不广播 interim，本阶段只完成连接与权限。

必须运行：
pytest tests/test_speech_websocket_blackbox.py::test_speaker_seat_can_start_speech_ws -q
pytest tests/test_speech_websocket_blackbox.py::test_non_speaker_seat_cannot_start_speech_ws -q
pytest -q

反馈要求：
- 修改文件列表
- 验证结果摘要
- 仍失败的测试及原因
- 是否可以进入 Phase 3
```

---

## Phase 3: PCM Receive And Interim Broadcast

```text
请执行 SmartDesk Speech Phase 3：PCM 接收、streaming ASR、translation_interim 广播。

重要限制：
- speech_module/ 是旧实现参考代码，不得修改。
- 不得修改 frontend/。
- 不得修改 docs/adr/。
- 不得实现 mock fallback。
- 不得让 interim 写入数据库。

允许修改：
- backend/services/speech_stream_service.py
- backend/websocket/speech_ws.py
- backend/events/translation_events.py
- backend/websocket/event_handler.py
- tests/test_speech_stream_service.py
- tests/test_speech_websocket_blackbox.py
- working/plan/task-103/changes.md
- working/plan/task-103/test-results.md

任务：
1. 接收 PCM16 little-endian binary frame。
2. 转为 16kHz mono float32 numpy array。
3. 调用 backend.speech_module.SpeechModule.process_interim_array()。
4. 维护 utterance revision。
5. 通过 EventBus 发布 translation_interim。
6. WebSocketEventHandler 广播 translation_interim 到会议广播通道。
7. 不落库。
8. 模型缺失或依赖缺失时返回明确错误，不 mock。

必须运行：
pytest tests/test_speech_stream_service.py -q
pytest tests/test_speech_websocket_blackbox.py -q
pytest -q

反馈要求：
- 修改文件列表
- ASR/VAD 模型是否真实加载
- translation_interim 是否广播成功
- 验证结果摘要
- 是否可以进入 Phase 4
```

---

## Phase 4: Final Rescore And Persistence

```text
请执行 SmartDesk Speech Phase 4：final ASR rescore、utterance_id 落库、translation_final 广播。

重要限制：
- speech_module/ 是旧实现参考代码，不得修改。
- 不得修改 frontend/。
- 不得修改 docs/adr/。
- 不得实现 mock fallback。
- 翻译第一版允许占位，重点是真实 ASR source_text。

允许修改：
- backend/models/translation_record.py
- backend/repositories/translation_repository.py
- backend/services/translation_service.py
- backend/services/speech_stream_service.py
- backend/events/translation_events.py
- tests/test_translation_service.py
- tests/test_speech_websocket_blackbox.py
- working/plan/task-104/changes.md
- working/plan/task-104/test-results.md

任务：
1. translation_records 增加 utterance_id 与 source_type。
2. SQLite 需要幂等补列，不能破坏旧数据。
3. TranslationService 增加 process_final_array(audio, sr, meeting_id, seat_id, utterance_id)。
4. final 使用 SpeechModule.transcribe_array() 做真实离线 ASR。
5. 写入 translation_records。
6. 发布 translation_final，payload 包含 utterance_id。
7. translated_text 可为占位，但必须符合接口文档。
8. ASR 空结果或模型错误必须返回明确错误。

必须运行：
pytest tests/test_translation_service.py -q
pytest tests/test_speech_websocket_blackbox.py -q
pytest -q

反馈要求：
- 修改文件列表
- 数据库迁移方式
- translation_final payload 示例
- 验证结果摘要
- 是否可以进入 Phase 5
```

---

## Phase 5: Speaker Seat Hard Switch

```text
请执行 SmartDesk Speech Phase 5：Speaker Seat 硬切换与 interim cancelled。

重要限制：
- speech_module/ 是旧实现参考代码，不得修改。
- 不得修改 frontend/。
- 不得修改 docs/adr/。
- 不得实现 mock fallback。

允许修改：
- backend/services/seat_service.py
- backend/services/speech_stream_service.py
- backend/websocket/speech_ws.py
- backend/events/translation_events.py
- tests/test_seat_service.py
- tests/test_speech_websocket_blackbox.py
- working/plan/task-105/changes.md
- working/plan/task-105/test-results.md

任务：
1. Speaker Seat 设置或清除时，关闭旧 seat 的 speech WS。
2. 清理旧 SpeechStreamSession。
3. 未 final 的 interim 不落库。
4. 广播 translation_interim_cancelled。
5. reason 使用 speaker_seat_changed。
6. 新 Speaker Seat 可重新建立 speech WS。

必须运行：
pytest tests/test_speech_websocket_blackbox.py::test_speaker_switch_cancels_old_interim -q
pytest tests/test_seat_service.py -q
pytest -q

反馈要求：
- 修改文件列表
- 旧 WS 如何关闭
- cancelled 事件 payload 示例
- 验证结果摘要
- 是否可以进入 Phase 6
```

---

## Phase 6: Frontend Audio Capture And Speech WS

```text
请执行 SmartDesk Speech Phase 6：前端麦克风采集与 /ws/speech 客户端。

重要限制：
- speech_module/ 是旧实现参考代码，不得修改。
- 不得修改 backend/speech_module/。
- 不得修改 docs/adr/。
- 不得修改接口文档。
- 不得实现浏览器端断句，final 由后端 VAD 决定。

允许修改：
- frontend/src/audio/
- frontend/src/components/SeatTablet.tsx
- frontend/src/__tests__/seat.test.tsx
- frontend/src/test-setup.ts
- working/plan/task-106/changes.md
- working/plan/task-106/test-results.md

任务：
1. 新增音频采集模块。
2. 使用 getUserMedia + AudioContext。
3. 输出 16kHz mono PCM16 binary frame。
4. 新增 useSpeechStream hook。
5. 只有当前 Speaker Seat 可开始语音。
6. 支持 start、cancel、end_hint。
7. 显示连接、录音、错误状态。
8. 不实现 mock fallback。

必须运行：
cd frontend
npm run typecheck
npm test -- --run
npm run build

反馈要求：
- 修改文件列表
- 浏览器权限/AudioContext 处理方式
- 测试结果摘要
- 是否可以进入 Phase 7
```

---

## Phase 7: TranscriptPanel Realtime UI

```text
请执行 SmartDesk Speech Phase 7：TranscriptPanel interim/final/cancel UI。

重要限制：
- speech_module/ 是旧实现参考代码，不得修改。
- 不得修改 backend/speech_module/。
- 不得修改 docs/adr/。
- 不得修改接口文档。

允许修改：
- frontend/src/hooks/useWebSocket.ts
- frontend/src/components/TranscriptPanel.tsx
- frontend/src/hooks/useAdminData.ts
- frontend/src/hooks/useSeatData.ts
- frontend/src/__tests__/admin.test.tsx
- frontend/src/__tests__/seat.test.tsx
- working/plan/task-107/changes.md
- working/plan/task-107/test-results.md

任务：
1. useWebSocket 支持 translation_interim，不触发全量 HTTP refresh。
2. TranscriptPanel 增加 interimMap。
3. translation_interim 按 utterance_id 和 revision 覆盖显示。
4. translation_final 删除对应 interim 并展示 final。
5. translation_interim_cancelled 删除对应 interim。
6. 保持既有历史字幕展示。

必须运行：
cd frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build

反馈要求：
- 修改文件列表
- interim/final/cancel UI 行为说明
- 验证结果摘要
- 是否可以进入 Phase 8
```

---

## Phase 8: Startup And Real Model Demo Validation

```text
请执行 SmartDesk Speech Phase 8：启动脚本、依赖检查、真实模型演示验证。

重要限制：
- speech_module/ 是旧实现参考代码，不得修改。
- 不得修改 backend/speech_module/，除非只是读取验证。
- 不得修改 docs/adr/。
- 不得实现 mock fallback。

允许修改：
- start.bat
- kill.bat
- requirements.txt 或等价 Python 依赖文件
- backend/main.py（仅限启动检查）
- working/demo-runbook.md
- working/plan/task-108/changes.md
- working/plan/task-108/test-results.md
- working/env-issues.md（仅真实环境问题）

任务：
1. 增加 Python 依赖声明或启动检查。
2. 检查 funasr、torch、scipy、numpy、soundfile。
3. 检查 models/ 中 Paraformer Streaming、Paraformer-large、FSMN-VAD。
4. 缺失时给出明确错误和下载说明。
5. 更新 start.bat 启用语音功能环境变量。
6. 更新 demo-runbook，加入完整语音演示流程。
7. 完成真实模型 smoke test，不允许 mock。

必须运行：
pytest -q
cd frontend
npm run typecheck
npm test -- --run
npm run build

如可行，执行手动验证：
1. start.bat 启动
2. 管理端设置 Speaker Seat
3. Speaker Seat 授权麦克风并开始发言
4. 管理端看到 interim
5. 停顿后看到 final
6. GET /api/translations 可查到记录

反馈要求：
- 修改文件列表
- 模型/依赖检查结果
- 自动测试结果
- 手动演示验证结果
- 是否达到语音识别可展示标准
```
