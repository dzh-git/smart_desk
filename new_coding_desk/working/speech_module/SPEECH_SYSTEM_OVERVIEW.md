# SmartDesk 语音识别与翻译系统 — 当前操作全貌

本文档描述 SmartDesk v1.0 中语音识别与翻译系统的完整前后端操作流程，
按数据流经的层级组织。内容基于代码实现，不是设计文档。

---

## 1. 系统分层

```
前端（浏览器）
  │
  │  HTTP POST /api/translations  (上传音频)
  │  HTTP GET  /api/translations  (查询历史)
  │  WebSocket /ws/{id}?seat={n}  (接收 translation_final 事件)
  │
  ▼
路由层  (backend/api/translations.py)
  │
  │  根据 FormData 中的 final 字段分发
  │    final=false → process_interim()
  │    final=true  → process_final()
  │
  ▼
服务层  (backend/services/translation_service.py)
  │
  │  TranslationService 持有 SpeechModule 单例
  │
  ▼
语音模块  (backend/speech_module/)
  │
  │  SpeechModule: ASR(语音识别) + 语种检测 + 翻译占位
  │  当前翻译是假实现 — 返回 "[translation not available]"
  │
  ▼
数据库  (translation_records 表)
  │
  │  仅 final 流程写入
  │  字段: id, meeting_id, seat_id, source_lang, target_lang,
  │        source_text, translated_text, created_at
  │
  ▼
事件总线  →  WebSocket 广播  (translation_final 事件)
  │
  │  推送给所有连接的客户端（管理员 + 全部座位）
  │
  ▼
前端  ←  收到 WS 事件 → 全量 HTTP 刷新 → TranscriptPanel 更新
```

---

## 2. 核心概念：Interim 与 Final

语音识别系统区分两种处理模式，由客户端通过 `final` 字段控制：

### Interim（中间结果）

- **是什么**：用户还在说话，句子尚未说完时的部分识别文本
- **调用时机**：客户端持续采集麦克风，每隔几百毫秒发送一次音频 chunk
- **后端做的事**：仅运行 ASR，返回当前已识别出的不完整文本
- **不做什么**：不翻译、不写数据库、不发事件、不走 WebSocket
- **输出**：纯 HTTP 响应 `{text: "今天我们要讨论的是..."}`

### Final（最终结果）

- **是什么**：用户说完一句话后的完整识别 + 翻译结果
- **调用时机**：客户端检测到语音结束（VAD 检测静音超过阈值）
- **后端做的事**：ASR → 语种检测 → 翻译 → 写数据库 → 发布事件
- **输出**：HTTP 201 + 完整 TranslationRecord，同时 WebSocket 推送给所有客户端

### 打个比方

```
用户说："我认为这个方案需要重新评估...（停顿）...特别是预算方面。"

Interim 第1次（500ms后）: "我认为"
Interim 第2次（1s后）  : "我认为这个方案"
Interim 第3次（1.5s后）: "我认为这个方案需要重新"
...

检测到句子结束 → POST final=true
Final: {
  source_text: "我认为这个方案需要重新评估特别是预算方面。"
  translated_text: "I think this plan needs to be re-evaluated, especially the budget."
}
```

---

## 3. 后端：逐层详解

### 3.1 路由层（translations.py）

单一端点 `POST /api/translations`，接收 FormData：

```
POST /api/translations
Content-Type: multipart/form-data

audio: (binary WAV file)
meeting_id: 1
seat_id: 3
session_key: "1_3"
final: false            ← 客户端决定走哪条路径
```

路由根据 `final` 字段分叉：

```python
if not final:
    # T1: interim
    text = svc.process_interim(tmp_path, session_key)
    return ApiResponse.ok(data={"text": text})
else:
    # T2: final
    record = svc.process_final(tmp_path, meeting_id, seat_id)
    return ApiResponse.ok(data=record, status=201)
```

`session_key` 默认为 `"{meeting_id}_{seat_id}"`，用于 SpeechModule 维护每个座位的流式 ASR 状态（CIF 缓存、已提交文本等）。

### 3.2 服务层（TranslationService）

#### process_interim() → str

```
1. _ensure_preloaded()     → 确保模型已加载
2. speech.process_interim_chunk(audio_path, session_key)
   → 返回当前累计的文本
3. return text
```

无数据库写入，无事件发布，无 WebSocket 广播。

#### process_final() → TranslationRecord

```
1. _ensure_preloaded()      → 确保模型已加载
2. speech.transcribe(audio_path)  → 离线完整 ASR
   → 如果返回空文本，抛出 TRANSLATION_FAILED
3. speech.translate_text(source_text)  → 返回 (zh_str, en_str)
   → 当前实现：一个语言返回原文，另一个返回 "[translation not available]"
4. 语种检测：
   - 若 en_str == "[translation not available]" → source_lang="zh", target_lang="en"
   - 若 zh_str == "[translation not available]" → source_lang="en", target_lang="zh"
   - 其他情况 → "auto"/"auto"
5. repo.create(meeting_id, seat_id, source_lang, target_lang,
               source_text, translated_text)
   → 写入 translation_records 表
6. event_bus.publish(TranslationFinalEvent(...))
   → 事件 payload: {
        translation_id, seat_id, source_lang, target_lang,
        source_text, translated_text
     }
7. return record
```

### 3.3 SpeechModule（backend/speech_module/）

SpeechModule 是独立模块，通过懒加载单例模式供 TranslationService 使用：

```python
_speech = None  # 全局单例

def _get_speech():
    global _speech
    if _speech is None:
        from backend.speech_module import SpeechModule
        _speech = SpeechModule(max_workers=2)
    return _speech
```

**核心方法**：

| 方法 | 用途 | 当前状态 |
|---|---|---|
| `preload()` | 加载所有模型，预热 | 待模型文件到位后实装 |
| `ready` | 是否已预加载 | 属性 |
| `transcribe(audio_path)` | 完整离线 ASR | 依赖 Paraformer 模型 |
| `process_interim_chunk(path, key)` | 流式 ASR chunk 处理 | 依赖 Streaming Paraformer |
| `translate_text(text)` | 语种检测 + 翻译 | **当前是假的** — 只检测语种，翻译返回占位符 |
| `reset_interim(key)` | 重置某 session 的 interim 状态 | 保留 CIF 缓存 |

**翻译是假的**——这是当前最大的功能缺口：

```python
def translate_text(self, text: str) -> tuple[str, str]:
    lang = detect_language(text)
    if lang == "zh":
        return (text, "[translation not available]")   # zh→en 未实现
    return ("[translation not available]", text)        # en→zh 未实现
```

根据 `system_architecture.md` 的设计，目标翻译引擎是 Opus-MT，
但当前仅预留了接口。根目录 `speech_module/` 下有参考实现（含真正的 `mt_engine.py`）。

### 3.4 数据库

`translation_records` 表在 `DATABASE_SCHEMA.md` §11 中定义：

```
字段: id, meeting_id, seat_id, source_lang, target_lang,
      source_text, translated_text, created_at

规则: 只允许新增，禁止修改（D3: Immutable History）
索引: (meeting_id), (meeting_id, seat_id), (created_at)
归属: TranslationRepository
```

### 3.5 事件与 WebSocket

`TranslationFinalEvent` 在 `process_final()` 执行成功后发布。

事件处理器（`backend/events/`）将事件传给 WebSocket 管理器，
广播给连接在同一 `meeting_id` 下的所有客户端（管理员 + 10 个座位）。

事件 payload 结构：

```json
{
  "event": "translation_final",
  "meeting_id": 1,
  "timestamp": 1717572000,
  "payload": {
    "translation_id": 42,
    "seat_id": 3,
    "source_lang": "zh",
    "target_lang": "en",
    "source_text": "我认为这个方案需要重新评估。",
    "translated_text": "I think this plan needs re-evaluation."
  }
}
```

---

## 4. 前端：逐层详解

### 4.1 WebSocket 接收（useWebSocket.ts）

`useWebSocket` hook 是纯通道——它不区分事件类型，
所有收到的消息都通过 `onEvent(event_name, message)` 回调转发。

连接参数：
- 管理员：`/ws/{meeting_id}?seat=0`
- 座位 N：`/ws/{meeting_id}?seat=N`

断连后每 3 秒自动重连，重连成功后触发全量 HTTP 刷新。

### 4.2 数据编排（useAdminData.ts / useSeatData.ts）

**管理员端**（useAdminData）：

```
初始化（并行请求）:
  Step 1: fetchActiveMeeting() + fetchSeats() + fetchSpeakerSeat() + fetchActiveVote()
  Step 2: 如果 Step 1 返回了活跃会议 →
    fetchAgendas() + fetchAttendees() + fetchServiceCalls() + fetchTranslations()

WebSocket 事件处理:
  收到任何 WS 事件 →
    调用 doFetch(false) 触发全量 HTTP 重新获取
    （包括重新调用 fetchTranslations()，从而更新翻译列表）
```

**座位端**（useSeatData）：

同样的模式——初始化时并行获取翻译历史，收到 WS 事件后全量刷新。

### 4.3 翻译面板（TranscriptPanel.tsx）

Props：
```typescript
{
  entries: TranslationRecord[];   // 翻译记录列表（按 created_at 倒序）
  seatNameMap: Record<number, string>;  // seat_id → 发言者姓名
  loading?: boolean;
}
```

三种状态：
- **加载中**：3 行骨架屏
- **空数据**：MessageSquare 图标 + "No transcript yet"
- **有数据**：滚动列表，每条显示：
  - 头像（按 seat_id 循环 10 种颜色）
  - 发言者姓名 + 时间（HH:MM）+ 语种标签（EN/中文）
  - 原文（source_text）
  - 译文（左侧灰色竖线装饰）

**当前前端缺少的能力**：
- `resources.ts` 中只有 `fetchTranslations()`（GET 查历史），
  没有 POST 上传音频的方法
- TranscriptPanel 只能展示已完成的翻译记录，
  不能显示流式 interim 文本
- 没有浏览器麦克风采集模块

### 4.4 前端 API 层（api/resources.ts）

```typescript
// 仅有的翻译相关 API 方法：
export function fetchTranslations(meetingId: number) {
  return apiGet(`/translations?meeting_id=${meetingId}`);
}
```

类型定义（api/types.ts）：
```typescript
interface TranslationRecord {
  id: number;
  meeting_id: number;
  seat_id: number;
  source_lang: string;
  target_lang: string;
  source_text: string;
  translated_text: string;
  created_at: string;
}
```

---

## 5. 完整流程示例

假设 SmartDesk 正在进行会议，座位 3 的赵磊发言：

```
【步骤 1: Interim 流式识别 — 说话过程中】

浏览器(座位3): 麦克风采集 → 每500ms发送一个音频chunk
  POST /api/translations
  final=false, seat_id=3, audio=chunk1.wav

  → SpeechModule.process_interim_chunk("chunk1.wav", "1_3")
  → HTTP 200 {text: "我认为"}

浏览器(座位3): 再发一个chunk
  POST /api/translations
  final=false, seat_id=3, audio=chunk2.wav

  → HTTP 200 {text: "我认为这个方案"}

浏览器(座位3): 继续...
  → HTTP 200 {text: "我认为这个方案需要重新评估"}

【步骤 2: Final 完整识别 — 检测到句子结束】

浏览器(座位3): VAD检测到静音 → 发送 final=true
  POST /api/translations
  final=true, seat_id=3, audio=final.wav

  → SpeechModule.transcribe("final.wav")
    → source_text = "我认为这个方案需要重新评估。"
  → SpeechModule.translate_text(source_text)
    → 当前伪实现: ("我认为这个方案需要重新评估。", "[translation not available]")
  → 语种检测: source_lang="zh", target_lang="en"
  → 写入 translation_records:
      id=42, seat_id=3, source_text="我认为这个方案需要重新评估。",
      translated_text="[translation not available]"
  → 发布 TranslationFinalEvent
  → HTTP 201 {id: 42, seat_id: 3, ...}

【步骤 3: WebSocket 广播】

WebSocket → 推送给管理员仪表盘 + 所有座位平板:
  {
    "event": "translation_final",
    "payload": {
      "translation_id": 42,
      "seat_id": 3,
      "source_text": "我认为这个方案需要重新评估。"
      "translated_text": "[translation not available]"
    }
  }

【步骤 4: 前端更新】

管理员端: 收到 translation_final 事件 → doFetch(false)
  → fetchTranslations(1) → 获取最新 42 条记录
  → TranscriptPanel 重新渲染，新增赵磊的发言

其他座位端: 同样流程，翻译面板实时更新
```

---

## 6. 功能缺口总结

| 缺口 | 位置 | 说明 |
|---|---|---|
| **翻译是假实现** | `backend/speech_module/speech_module.py` `translate_text()` | 总是返回 `[translation not available]`，需要接入真正的 MT 引擎（如 Opus-MT） |
| **前端无音频采集** | `frontend/src/` | 没有浏览器麦克风采集模块，无法主动触发语音识别 |
| **前端无 POST 上传封装** | `frontend/src/api/resources.ts` | 缺少 `postAudio()` 之类的上传音频 API 方法 |
| **Interim 不广播** | 架构层面 | `translation_interim` 仅 HTTP 返回给上传端，管理员看不到流式文本 |
| **双副本 SpeechModule** | `speech_module/` vs `backend/speech_module/` | 根目录副本有真正的 mt_engine，后端副本是简化版 |
| **模型未实装** | `preload()` 方法 | Paraformer/FunASR 模型的下载路径和加载逻辑待补充 |
