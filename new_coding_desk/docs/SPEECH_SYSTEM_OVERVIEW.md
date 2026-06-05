# SmartDesk 语音识别与翻译系统 — 架构与操作全貌

本文档根据 2026-06-05 的四项架构决策更新，描述从当前状态到目标架构的完整设计。

相关 ADR：`docs/adr/0001` ~ `0004`。

---

## 1. 目标架构：双 WebSocket 通道

```
通道 A：会议广播 WebSocket  /ws/{meeting_id}?seat=N
  ├─ 管理员和所有座位接收事件
  ├─ 接收 translation_interim（新增）
  ├─ 接收 translation_final
  └─ 接收原有 seat / vote / service-call 事件

通道 B：语音上行 WebSocket  /ws/speech/{meeting_id}?seat=N
  ├─ 仅当前 Speaker Seat 可连接
  ├─ 前端持续发送 PCM16 二进制帧
  └─ 后端运行 Server VAD + Paraformer Streaming ASR
```

---

## 2. 完整流程

```text
1. Seat 3 是当前 Speaker Seat
2. Seat 3 打开 /ws/speech/1?seat=3
3. 前端发送 start 控制消息
4. 后端生成 utterance_id = utt_1_3_000042，返回 started
5. 前端持续发送 PCM16 binary frames (每 100ms 一帧)
6. 后端缓存 PCM 到 ring buffer，同时跑 Streaming ASR
7. 后端每 300–500 ms 广播 translation_interim（通道 A）
8. FSMN-VAD 检测句末（静音 > 800ms）
9. 后端从 PCM buffer 截取完整 utterance
10. 调用 TranslationService.process_final_array()
11. Offline ASR rescore → 翻译 → 写 translation_records
12. 广播 translation_final（通道 A）
13. 前端用 final 替换 interim，清除 interimMap 对应条目
```

---

## 3. 新增事件

### 3.1 translation_interim

```json
{
  "event": "translation_interim",
  "meeting_id": 1,
  "payload": {
    "utterance_id": "utt_1_3_000042",
    "seat_id": 3,
    "revision": 4,
    "source_lang": "zh",
    "target_lang": "en",
    "source_text": "我认为这个方案需要重新",
    "translated_text": "",
    "is_final": false
  }
}
```

- 不写数据库、不被覆盖后可丢弃
- 广播节流 300–500 ms
- 仅用于 UI 实时显示

### 3.2 translation_final（扩展现有事件）

在现有 payload 基础上新增 `utterance_id`，方便前端替换 interim：

```json
{
  "event": "translation_final",
  "payload": {
    "utterance_id": "utt_1_3_000042",
    "translation_id": 42,
    "seat_id": 3,
    "source_lang": "zh",
    "target_lang": "en",
    "source_text": "我认为这个方案需要重新评估。",
    "translated_text": "I think this plan needs to be re-evaluated."
  }
}
```

### 3.3 translation_interim_cancelled（可选）

Speaker Seat 切换时广播，通知前端丢弃旧 interim：

```json
{
  "event": "translation_interim_cancelled",
  "payload": {
    "utterance_id": "utt_1_3_000042",
    "seat_id": 3,
    "reason": "speaker_seat_changed"
  }
}
```

---

## 4. 核心决策

| # | 决策 | ADR |
|---|------|-----|
| 语音上行 | WebSocket 音频流 `/ws/speech/{id}?seat=N`，替代 HTTP chunk | 0001 |
| Final 音频来源 | 后端缓存整句 PCM，VAD 触发后 Offline ASR rescore | 0002 |
| utterance_id | 后端生成，start 后返回前端 | 0003 |
| Speaker Seat 切换 | 硬切换：旧 WS 立即关闭，interim 丢弃不写库 | 0004 |

---

## 5. 后端模块调整

### 5.1 新增模块

```
backend/websocket/speech_ws.py          # 语音上行 WS 连接（接收 binary PCM + JSON 控制）
backend/services/speech_stream_service.py # Streaming ASR 编排（缓存 PCM、调 SpeechModule、发 interim）
backend/speech_module/stream_session.py  # 单 utterance 的 PCM buffer + CIF 缓存
backend/events/translation_events.py     # 新增 TranslationInterimEvent
```

### 5.2 修改模块

```
backend/services/translation_service.py
  + process_final_array(audio, sr, meeting_id, seat_id, utterance_id)
  + _finalize_text(source_text, meeting_id, seat_id, utterance_id)  # 共用核心
  保留 process_final_file(audio_path, ...) 兼容旧 HTTP 入口
```

### 5.3 职责边界

```text
speech_ws.py       → 只做连接管理，不写库、不广播业务事件
SpeechStreamService → 校验 Speaker Seat、管理 session、调 ASR、发 interim、触发 final
TranslationService → final 写库、翻译、发 translation_final
SpeechModule       → 只负责 VAD / ASR / MT，不知 FastAPI/WS/EventBus
```

---

## 6. 前端模块调整

### 6.1 新增 `frontend/src/audio/`

```
audio/
  audioTypes.ts          # PCM16 / AudioConfig 等类型
  AudioCaptureClient.ts  # 麦克风权限、AudioContext、AudioWorklet 加载
  pcm16.ts               # Float32 → PCM16 little-endian
  resample.ts            # 浏览器采样率 → 16000 Hz
  energyVad.ts           # 轻量能量门限（不负责断句）
  useSpeechStream.ts     # React hook：连接 /ws/speech、发 start/PCM、管理状态
  worklets/
    pcm-worklet.ts       # AudioWorklet 处理器
```

### 6.2 修改模块

```
frontend/src/hooks/useWebSocket.ts  → 支持接收 translation_interim 事件
frontend/src/components/TranscriptPanel.tsx  → 新增 interimMap 状态，显示流式文本
frontend/src/components/SeatTablet.tsx  → 调用 useSpeechStream hook
```

### 6.3 前端状态模型

```typescript
type InterimTranscript = {
  utterance_id: string
  seat_id: number
  source_text: string
  revision: number
}

// TranscriptPanel 新增：
const [interimMap, setInterimMap] = useState<Record<string, InterimTranscript>>({})
const [finalEntries, setFinalEntries] = useState<TranslationRecord[]>([])

// 收到 translation_interim → 只更新 interimMap，不做全量 HTTP 刷新
// 收到 translation_final → 删除 interimMap 条目，插入 finalEntries，必要时 refresh
```

---

## 7. 协议参数

```yaml
speech_stream:
  transport:
    protocol: websocket
    endpoint: /ws/speech/{meeting_id}?seat={seat_id}
    audio_encoding: pcm_s16le
    sample_rate: 16000
    channels: 1
    client_frame_ms: 100          # 每帧 3200 bytes

  asr:
    model: paraformer_streaming
    chunk_size: [0, 10, 5]        # 显示粒度 600ms, lookahead 300ms
    interim_emit_interval_ms: 500

  vad:
    engine: fsmn_vad
    endpoint_silence_ms: 800
    min_speech_ms: 300
    max_single_segment_ms: 20000

  final:
    offline_rescore: true
    translate_after_final: true
    persist_final_only: true
    fallback_on_rescore_fail: use_last_stable_interim
```

---

## 8. 延迟预估

```text
interim 首次显示:  1.1–1.8 s（采集 100ms + ASR chunk 600ms + lookahead 300ms + 推理 + 广播节流）
interim 稳态更新:  0.6–1.2 s
final 完整结果:    1.2–3.0 s（含句末静音等待 + rescore + 翻译 + 写库）
```

---

## 9. 控制消息协议

### 前端 → 后端

| type | 说明 |
|---|---|
| `start` | 开始语音流（含 sample_rate/encoding/channels） |
| binary PCM16 | 音频帧，每 100ms 一帧 |
| `end_hint` | 提示可能说完（后端 VAD 最终决定） |
| `cancel` | 取消当前 utterance |

### 后端 → 前端

| type | 说明 |
|---|---|
| `started` | 返回 utterance_id 和 session_key |
| `utterance_started` | 新 utterance 自动开始（同一连接内连续说话） |
| `error` | 错误（含 code 和 message） |

---

## 10. 当前代码中的缺口（待实现）

| 缺口 | 说明 |
|---|---|
| SpeechModule 翻译假实现 | `translate_text()` 返回 `[translation not available]`，需接入 Opus-MT |
| 后端 speech_ws.py | 语音上行 WebSocket 端点，尚不存在 |
| 后端 SpeechStreamService | 流式 ASR 编排层，尚不存在 |
| 后端 process_final_array() | TranslationService 新方法，尚不存在 |
| 前端 audio/ 模块 | 浏览器麦克风采集全套，尚不存在 |
| 前端 useSpeechStream | React hook，尚不存在 |
| 前端 TranscriptPanel interim 支持 | interimMap 状态和流式 UI，尚不存在 |
| 前端 api/resources.ts | 缺少 POST 音频上传封装 |
| EventBus translation_interim | 新事件类型，尚不存在 |
