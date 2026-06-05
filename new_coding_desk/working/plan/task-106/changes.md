# Task 106 — Speech Phase 6: 前端麦克风采集与 /ws/speech 客户端

## 修改文件列表

| 文件 | 操作 | 说明 |
|---|---|---|
| `frontend/src/audio/types.ts` | **新增** | SpeechStatus (idle/requesting_microphone/connecting_speech_ws/recording/stopping/error) + SpeechState |
| `frontend/src/audio/microphone.ts` | **新增** | MicrophoneCapture 类 — getUserMedia → AudioContext(16kHz) → ScriptProcessorNode → PCM16 s16le 100ms 帧 |
| `frontend/src/audio/speechWsClient.ts` | **新增** | SpeechWsClient 类 — /ws/speech WebSocket 连接管理，start/end_hint/cancel 协议封装 |
| `frontend/src/hooks/useSpeechStream.ts` | **新增** | useSpeechStream hook — 编排 MicrophoneCapture + SpeechWsClient，状态机管理 |
| `frontend/src/components/SeatTablet.tsx` | 修改 | VoicePlaceholder → SpeechControl 组件；Speaker Seat 显示录音控制，非 Speaker 显示只读提示 |
| `frontend/src/test-setup.ts` | 修改 | 添加 navigator.mediaDevices.getUserMedia mock + MockAudioContext + MockMediaStream |
| `frontend/src/__tests__/seat.test.tsx` | 修改 | SimpleMockWebSocket → MultiMockWebSocket (多实例跟踪)；新增 9 个语音测试 |
| `working/plan/task-106/changes.md` | **新增** | 本文件 |
| `working/plan/task-106/test-results.md` | **新增** | 测试结果 |

## 浏览器权限与 AudioContext 处理方式

**麦克风权限请求**：
- `navigator.mediaDevices.getUserMedia({ audio: true })` — 标准浏览器 API，触发权限弹窗
- 权限拒绝时抛出 `DOMException`，MicrophoneCapture.start() 将异常转换为 `"Microphone access denied: ..."` 消息
- SpeakControl 组件在 Start 前检查 `navigator.mediaDevices?.getUserMedia != null`，不支持时禁用 Start

**AudioContext**：
- 使用 `new AudioContext({ sampleRate: 16000 })` 直接请求 16kHz
- 通过 `createMediaStreamSource(stream)` 连接麦克风流
- `ScriptProcessorNode(bufferSize=4096, inputChannels=1, outputChannels=1)` 处理音频
- `onaudioprocess` 回调中获取 Float32Array → 累积缓冲 → 100ms 帧切割 → float32ToPcm16 转换

**清理顺序** (`MicrophoneCapture.stop()`):
1. `processorNode.disconnect()` — 断开处理节点
2. `sourceNode.disconnect()` — 断开音频源
3. `audioContext.close()` — 关闭 AudioContext
4. 遍历 `stream.getTracks()` → 逐条 `track.stop()` — 释放麦克风

## PCM16 采样/转换实现说明

**帧规格** (per WEBSOCKET_PROTOCOL §3):
- 采样率: 16kHz
- 位深: 16-bit signed little-endian (s16le)
- 声道: 1 (mono)
- 帧长: 100ms → 1600 samples → 3200 bytes

**float32 → PCM16 转换** (`MicrophoneCapture.float32ToPcm16`):
```typescript
static float32ToPcm16(float32: Float32Array): Int16Array {
  const pcm16 = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32[i]));
    pcm16[i] = clamped < 0
      ? Math.round(clamped * 0x8000)   // [-1, 0) → [-32768, 0)
      : Math.round(clamped * 0x7FFF);   // [0, 1] → [0, 32767]
  }
  return pcm16;
}
```

**帧缓冲与切割**: `processAudioInput()` 累积 `onaudioprocess` 回调的 Float32Array 数据，达到 1600 samples 时切割为完整帧发送，剩余数据保留到下次回调。

## /ws/speech 消息流程说明

```
客户端                         服务器
  |                              |
  |-- TCP connect --------------->|
  |<-- 101 Switching Protocols ---|
  |                              |
  |-- {"type":"start",           |
  |    "sample_rate":16000,      |
  |    "encoding":"pcm_s16le",   |
  |    "channels":1}             |
  |<-- {"type":"started",        |
  |     "utterance_id":"utt_..", |  ← connect() resolve
  |     "session_key":"speech_."}|
  |                              |
  |-- [binary PCM16 frame] ----->|  ← sendAudio() (每 100ms)
  |-- [binary PCM16 frame] ----->|
  |                              |
  |-- {"type":"end_hint"} ------->|  ← stop()
  |-- TCP close ----------------->|
  |                              |
  (或)
  |-- {"type":"cancel"} --------->|  ← cancel()
  |-- TCP close ----------------->|
```

**状态机**:
```
idle → requesting_microphone → connecting_speech_ws → recording
recording → stopping → idle          (end_hint 路径)
recording → idle                     (cancel 路径)
requesting_microphone → error        (用户拒绝麦克风)
connecting_speech_ws → error         (WS 错误/后端 error 消息)
error → idle                         (Dismiss/Retry)
```

**错误处理**:
- `SpeechWsClient.connect()` 在收到 `{"type":"error"}` 时 reject promise
- `useSpeechStream` 的 catch 将错误消息设置为 `error` 状态
- SeatTablet SpeechControl 显示错误消息 + Retry 按钮
- 支持错误码: `NOT_SPEAKER_SEAT`, `SPEECH_WS_NOT_STARTED`, `MODEL_NOT_LOADED`, `ASR_EMPTY_RESULT`, `TRANSLATION_FAILED`
