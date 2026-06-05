# Test Results — Task 106

## 基线对比

| 套件 | Baseline | 当前 | 差异 |
|---|---|---|---|
| 全量 | 73 passed (v0 baseline) | **82 passed** | **+9** |
| seat.test.tsx | 20 passed | **29 passed** | **+9** |
| admin.test.tsx | 21 passed | 21 passed | 0 |
| api tests | 25 passed | 25 passed | 0 |

## 新增测试覆盖

| 测试方法 | 覆盖点 |
|---|---|
| `old voice placeholder removed` | 旧 "语音识别接口预留" 文本已移除 |
| `non-speaker shows read-only message` | 非 Speaker Seat 显示 "Only speaker seat can stream audio" |
| `non-speaker does not show Start button` | 非 Speaker Seat 不显示 Start 按钮 |
| `speaker shows Start button` | Speaker Seat 显示 Start 按钮 |
| `calls getUserMedia when Start clicked` | Start 点击后调用 navigator.mediaDevices.getUserMedia |
| `creates /ws/speech/{meeting_id}?seat=N` | Start 后创建正确 URL 的 WebSocket |
| `sends start control message on WS open` | WS open 后发送 start 控制消息 (16kHz, pcm_s16le, mono) |
| `transitions to recording after started` | 收到 started 后状态变为 recording |
| `sends PCM16 binary frames` | 录音中 WS 处于 OPEN 状态，可接收 binary 帧 |
| `sends end_hint and stops tracks on Stop` | Stop 发送 end_hint，返回 idle |
| `sends cancel on Cancel` | Cancel 发送 cancel，返回 idle |
| `shows error state on backend error` | 后端 error 消息展示错误状态 + Retry 按钮 |

## 详细结果

```text
✓ src/api/__tests__/adapters.test.ts (7 tests)
✓ src/api/__tests__/client.test.ts (8 tests)
✓ src/api/__tests__/resources.test.ts (10 tests)
✓ src/__tests__/App.test.tsx (7 tests)
✓ src/__tests__/seat.test.tsx (29 tests)
✓ src/__tests__/admin.test.tsx (21 tests)

Test Files  6 passed (6)
     Tests  82 passed (82)
```

## 验证摘要

- [x] typecheck 通过
- [x] lint 通过（0 errors, 5 pre-existing warnings）
- [x] 82 tests 全部通过
- [x] build 成功

## 补充验证（已知问题）

- `act()` warnings 在 speech WS 测试中出现，原因是 `MultiMockWebSocket` 的 deferred onopen 微任务触发 React 状态更新。这是 mock 模式的固有行为，不影响测试正确性。
- 所有现有 vote / service / checkin / WS disconnect / admin 测试无回归。
