可以，按照你补充的信息，我建议**直接把语音链路改成 WebSocket 音频流方案**，并且把目标定义为：

```text
实时阶段：只显示 ASR 识别文本，不写库
最终阶段：Offline ASR 修正 + 翻译 + 写库 + 广播 final
翻译位置：UI 保留 translated_text 区域，但 interim 阶段先为空或显示“翻译生成中”
```

你当前文档里的问题是：`interim` 只通过 HTTP 返回给上传端，不进入 WebSocket/EventBus；而你现在的目标是管理员和所有座位都能看到实时识别文本，所以必须新增 `translation_interim` 广播链路。当前系统中 final 才写库、发布 `translation_final`，这一点可以保留。

---

# 1. 推荐最终架构

建议采用**双 WebSocket 通道**：

```text
通道 A：会议广播 WebSocket
/ws/{meeting_id}?seat=N

用途：
- 管理员和所有座位接收事件
- 接收 translation_interim
- 接收 translation_final
- 接收 seat / vote / service-call 等原有事件


通道 B：语音上行 WebSocket
/ws/speech/{meeting_id}?seat=N

用途：
- 只有当前 Speaker Seat 可以连接并发送音频
- 前端持续发送 PCM16 音频帧
- 后端运行 Server VAD + Paraformer Streaming
```

也就是说：

```text
Speaker Seat 浏览器
  ↓ WebSocket binary audio
/ws/speech/{meeting_id}?seat=N
  ↓
SpeechStreamService
  ↓
SpeechModule.process_interim_array()
  ↓
translation_interim
  ↓
EventBus
  ↓
WebSocketService.broadcast()
  ↓
管理员 + 所有座位
```

最终句子完成后：

```text
Server VAD 判断句子结束
  ↓
Offline ASR / rescore
  ↓
Final 翻译
  ↓
TranslationRepository.create()
  ↓
translation_final
  ↓
广播给管理员 + 所有座位
```

这样不破坏你原来的架构原则：业务逻辑仍在 Service 层，事件仍由 Service 发布，SpeechModule 仍不依赖 FastAPI、WebSocket、React 或 Arduino。你的系统架构文档也明确要求 SpeechModule 保持独立。

---

# 2. 新增事件设计

你需要新增一个 `translation_interim` 事件。

## 2.1 translation_interim

```json
{
  "event": "translation_interim",
  "meeting_id": 1,
  "timestamp": 1717572000,
  "payload": {
    "utterance_id": "m1_s3_00042",
    "seat_id": 3,
    "revision": 6,
    "source_lang": "zh",
    "target_lang": "en",
    "source_text": "我认为这个方案需要重新",
    "translated_text": "",
    "is_final": false
  }
}
```

特点：

```text
不写数据库
不保存历史
可以被覆盖
只用于 UI 实时显示
广播频率需要节流
```

## 2.2 translation_final

保留现有事件，但建议加入 `utterance_id`，方便前端用 final 替换 interim。

```json
{
  "event": "translation_final",
  "meeting_id": 1,
  "timestamp": 1717572000,
  "payload": {
    "utterance_id": "m1_s3_00042",
    "translation_id": 42,
    "seat_id": 3,
    "source_lang": "zh",
    "target_lang": "en",
    "source_text": "我认为这个方案需要重新评估。",
    "translated_text": "I think this plan needs to be re-evaluated."
  }
}
```

当前系统已经有 `translation_final` 写库和广播流程，所以你不是重做，而是增加一条 interim 实时显示链路。

---

# 3. WebSocket 音频协议建议

## 3.1 语音 WebSocket 地址

```text
/ws/speech/{meeting_id}?seat=N
```

后端连接时必须校验：

```text
1. meeting_id 是否为 active meeting
2. seat=N 是否为当前 Speaker Seat
3. 该 seat 是否已 check-in
4. 当前是否已有其他 speech session
```

因为你已经确定同一时间只有一个 Speaker Seat，所以后端可以强制：

```text
非 Speaker Seat 禁止发送音频
同一会议同一时间只允许一个 active speech stream
```

---

## 3.2 音频格式

建议固定为：

```text
Encoding: PCM16 little-endian
Sample Rate: 16000 Hz
Channels: Mono
Frame transport: WebSocket binary
```

你现有架构文档中 V1 音频格式就是 WAV / PCM16 / 16 kHz / Mono；WebSocket 流式传输时不需要每帧都封装 WAV header，直接发裸 PCM16 更合适。

---

## 3.3 控制消息

WebSocket 同时支持 JSON 控制帧和 binary 音频帧。

开始：

```json
{
  "type": "start",
  "meeting_id": 1,
  "seat_id": 3,
  "utterance_id": "m1_s3_00042",
  "sample_rate": 16000,
  "encoding": "pcm_s16le",
  "channels": 1
}
```

音频：

```text
binary PCM16 frame
```

前端认为可能结束时，可以发：

```json
{
  "type": "end_hint"
}
```

但注意：`end_hint` 只是提示，**不直接 final**。最终切句仍由后端 FSMN-VAD 决定。你的架构文档也明确说明，前端 VAD 不作为最终语音判定依据，后端 FSMN-VAD 拥有最终决定权。

取消：

```json
{
  "type": "cancel"
}
```

断线：

```text
直接丢弃当前 utterance
清理 session buffer
广播 speech_status: cancelled 可选
```

---

# 4. chunk 大小如何确定

这里要区分两个概念：

```text
1. WebSocket 网络发送帧大小
2. Paraformer Streaming 推理 chunk_size
```

它们不一定相同。

---

## 4.1 推荐初始参数

我建议你从下面这组参数开始：

| 参数                 |                   推荐值 |
| ------------------ | --------------------: |
| 前端采集格式             | 16 kHz / mono / PCM16 |
| WebSocket 发送帧      |                100 ms |
| 每帧大小               |            3200 bytes |
| 发送频率               |                10 fps |
| ASR chunk_size 初始值 |          `[0, 10, 5]` |
| ASR 显示粒度           |                600 ms |
| ASR lookahead      |                300 ms |
| interim 广播节流       |            300–500 ms |
| Server VAD 句末静音    |          默认 800 ms，可调 |
| 最大单句时长             |               15–20 s |

FunASR / Paraformer Streaming 官方示例中，`chunk_size=[0,10,5]` 表示实时显示粒度为 `10×60=600 ms`，lookahead 为 `5×60=300 ms`，并且最后一个语音片段需要设置 `is_final=True` 来强制输出最后文本。([Hugging Face][1])

---

## 4.2 为什么 WebSocket 发送帧选 100 ms

16 kHz、PCM16、mono 的码率是：

```text
16000 samples/s × 2 bytes × 1 channel = 32000 bytes/s
```

所以：

```text
100 ms = 3200 bytes
1 秒 = 10 帧
单路音频约 32 KB/s
```

你的系统只有一个 Speaker Seat 上行音频，所以这个带宽非常低。100 ms 是一个比较平衡的值：

```text
比 20 ms 更省 WebSocket 消息数量
比 500 ms 延迟更低
对 ASR 聚合也足够平滑
```

---

## 4.3 最优参数的测试方法

不要凭感觉定最终参数，建议做一个小型网格测试。

测试参数：

```text
WebSocket frame_ms: 40 / 80 / 100 / 160
ASR chunk_size: [0,8,4] / [0,10,5] / [0,12,6]
interim_emit_interval_ms: 300 / 500 / 700
vad_endpoint_silence_ms: 600 / 800 / 1000 / 1200
```

记录指标：

```text
P50 首字显示延迟
P90 首字显示延迟
P50 稳态更新延迟
P90 稳态更新延迟
final 输出延迟
CER / WER
CPU 占用
内存占用
WebSocket 丢帧或排队数量
```

验收标准建议：

```text
P90 interim 显示延迟 < 2 s
稳态更新间隔 < 800 ms
RTF < 0.5
final 文本准确率明显优于 interim
前端无明显跳字卡顿
```

其中 `RTF` 是实时率：

```text
RTF = 推理耗时 / 音频时长
```

例如：

```text
1 秒音频 0.3 秒处理完 → RTF = 0.3
1 秒音频 1.2 秒处理完 → RTF = 1.2，不适合实时
```

---

# 5. VAD 策略建议

## 5.1 前端 VAD

我建议前端 VAD **只做轻量辅助，不做最终切句**。

前端负责：

```text
麦克风权限
AudioWorklet 采集
重采样到 16 kHz
PCM16 编码
可选能量门限，减少纯静音上传
保留 300–500 ms pre-roll buffer
发送 end_hint
```

前端不负责：

```text
最终断句
最终 final
最终是否写库
```

原因是浏览器环境噪声、麦克风差异、座位平板硬件差异会导致前端 VAD 不稳定。你现在的系统定位是会议桌，应该让后端 FSMN-VAD 做统一判定。

---

## 5.2 后端 VAD

后端 FSMN-VAD 建议做成配置项：

```yaml
speech:
  vad:
    endpoint_silence_ms: 800
    min_speech_ms: 300
    pre_speech_padding_ms: 300
    post_speech_padding_ms: 200
    max_single_segment_ms: 20000
    speech_noise_threshold: 0.6
```

建议默认：

```text
endpoint_silence_ms = 800 ms
```

如果会议发言人语速较慢、停顿多，可以调到：

```text
1000–1200 ms
```

如果你更重视实时性，可以调到：

```text
600–700 ms
```

但太短会把一句话切碎。

---

# 6. 延迟预算预估

按照推荐初始参数，interim 识别文本的延迟大致是：

```text
前端采集与发送：100 ms
ASR chunk：600 ms
lookahead：300 ms
模型推理：50–300 ms
广播节流：300–500 ms
WebSocket + UI：50–100 ms
```

所以：

```text
interim 首次显示延迟 ≈ 1.1–1.8 s
稳态更新延迟 ≈ 0.6–1.2 s
```

这能满足你提出的 `<2s` 目标。

Final 阶段会更慢，因为它需要：

```text
句末静音等待：600–1000 ms
Offline ASR / rescore
翻译
写库
广播
```

所以 final 翻译可能在用户停顿后约：

```text
1.2–3 s
```

这没有问题，因为你的实时目标暂时是“识别文本”，不是“实时翻译文本”。

---

# 7. 推理速度预估

在你“只有一个 Speaker Seat”的条件下，压力不大。

我建议的硬件目标：

| 硬件                                          | 预估效果                                        |
| ------------------------------------------- | ------------------------------------------- |
| 高性能 NUC CPU-only，i7 / Ultra 7，32 GB RAM     | 可跑单路 streaming ASR，RTF 约 0.3–0.8，final 可能略慢 |
| 带 NVIDIA GPU 的小主机，RTX 3060 / 4060，8 GB VRAM | 单路 ASR + final rescore + 翻译较稳，RTF 通常可低于 0.2 |
| CPU-only + 同时加载 ASR、VAD、MT                  | 可做 Demo，但 final 翻译延迟可能波动                    |
| 16 GB RAM                                   | 可运行，但不宽裕                                    |
| 32 GB RAM                                   | 推荐配置                                        |

FunASR 官方介绍中，Paraformer 是非自回归端到端 ASR，适合利用 GPU 并行推理；FunASR 项目也把 ASR、VAD、标点等作为统一语音工具链提供。([ModelScope][2])

---

# 8. 前端 UI 改造建议

当前前端 TranscriptPanel 只能展示已完成的翻译记录，不能显示流式 interim 文本；并且现在的 WebSocket 处理逻辑是收到任何事件都全量刷新，这不适合高频 interim。

建议改成：

```typescript
type InterimTranscript = {
  utterance_id: string
  seat_id: number
  source_text: string
  translated_text?: string
  revision: number
  updated_at: string
}
```

前端状态：

```typescript
const [interimMap, setInterimMap] = useState<Record<string, InterimTranscript>>({})
const [finalEntries, setFinalEntries] = useState<TranslationRecord[]>([])
```

收到 `translation_interim`：

```text
只更新 interimMap
不要 fetchTranslations()
不要全量刷新
```

收到 `translation_final`：

```text
删除对应 utterance_id 的 interim
插入 finalEntries
必要时 fetchTranslations()
```

UI 显示：

```text
正在说话：
原文：我认为这个方案需要重新……
译文：翻译将在句子结束后生成

历史记录：
原文：我认为这个方案需要重新评估。
译文：I think this plan needs to be re-evaluated.
```

---

# 9. 后端模块改造建议

建议新增或调整这些模块：

```text
backend/websocket/speech_ws.py
backend/services/speech_stream_service.py
backend/services/translation_service.py
backend/events/translation_events.py
backend/speech_module/stream_session.py
```

职责划分：

```text
speech_ws.py
- 只负责 WebSocket 连接
- 接收 JSON 控制消息
- 接收 binary audio
- 调用 SpeechStreamService
- 不写库
- 不直接广播业务事件

SpeechStreamService
- 校验 Speaker Seat
- 管理 utterance session
- 调用 SpeechModule streaming ASR
- 发布 translation_interim
- 触发 final 流程
- 调用 TranslationService 保存 final

TranslationService
- 保留 final 写库
- 翻译
- 发布 translation_final

SpeechModule
- 只负责 VAD / ASR / MT
- 不知道 FastAPI / WebSocket / EventBus
```

这与现有架构中“Router/通信层不做业务，Service 发布事件，Repository 只负责数据库”的原则一致。

---

# 10. 最终推荐配置

你现在可以直接把设计定为：

```yaml
speech_stream:
  transport:
    protocol: websocket
    endpoint: /ws/speech/{meeting_id}?seat={seat_id}
    audio_encoding: pcm_s16le
    sample_rate: 16000
    channels: 1
    client_frame_ms: 100

  asr:
    model: paraformer_streaming
    chunk_size: [0, 10, 5]
    encoder_chunk_look_back: 4
    decoder_chunk_look_back: 1
    interim_emit_interval_ms: 500
    emit_only_on_text_change: true

  vad:
    engine: fsmn_vad
    endpoint_silence_ms: 800
    min_speech_ms: 300
    pre_speech_padding_ms: 300
    post_speech_padding_ms: 200
    max_single_segment_ms: 20000

  final:
    offline_rescore: true
    translate_after_final: true
    persist_final_only: true
    save_audio: false

  reconnect:
    on_disconnect: discard_current_utterance
```

---

# 11. 一句话总结

你应该把当前方案从：

```text
HTTP chunk → interim 只返回上传端 → final 后广播
```

改成：

```text
WebSocket 音频流 → 后端 Streaming ASR → translation_interim 广播给所有端 → final 后翻译、写库、translation_final 广播
```

最关键的设计原则是：**前端负责采集和低延迟传输，后端负责 VAD、ASR、final 判定和数据可信性；interim 只展示，final 才写库。**
