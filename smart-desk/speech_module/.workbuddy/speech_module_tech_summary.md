# 语音识别模块技术摘要 — SmartDesk 集成规划

> **分析范围**: `speech_module/*.py` 共 10 个源文件 + `tests/` 下 2 个测试文件
> **分析日期**: 2026-06-05
> **分析原则**: 不改代码，仅做技术分析

---

## 结论摘要（10 行以内）

1. 参考代码是一个**成熟的会议翻译后端模块**，提供完整的 STT(语音识别) + MT(机器翻译) + 历史存储管线。
2. 识别架构：**后端直接采集/处理音频**，不依赖前端录音；基于 FunASR 的 Paraformer Streaming（流式）+ Paraformer-large（离线 2pass 纠错）。
3. 包含 **VAD (FSMN-VAD)**、**标点恢复 (CT-Transformer)**、**句子边界合并 (SentenceMerger)**、**翻译 (Opus-MT)**，不含降噪/说话人识别/字幕落库 UI。
4. 流式识别使用**函数调用而非 WebSocket** — 调用方逐 chunk 喂 numpy 数组。
5. 核心依赖：FunASR、PyTorch、transformers、scipy、numpy、soundfile；**可在 CPU 上运行**，不需要 GPU/CUDA。
6. **输入契约**：float32 numpy 数组，16000 Hz 单声道；输出为纯文本 string，带 sentence-boundary-aware 合并。
7. 代码结构清晰：`SpeechModule` 是顶层 facade，内部按职责拆分到 9 个子模块。
8. **推荐第一版集成**：复用 `SpeechModule.transcribe()`（文件上传后离线识别）+ `HistoryStore` 落库，通过 HTTP multipart 上传实现。
9. 流式 WebSocket 识别和翻译可以暂缓。
10. 当前限制：无说话人识别、无降噪 DSP、无前端实时推流网关。

---

## 1. 总体架构

### 1.1 前端录音 vs 后端采集

**参考代码是后端采集模式。** 代码中完全没有前端麦克风采集逻辑，音频以文件路径 (`audio_path`) 或 numpy 数组 (`audio: np.ndarray`) 的形式传入后端处理函数。这意味着音频由**调用方负责采集和传递** — 可以是前端录音后上传，也可以是服务端直接读取麦克风设备。

### 1.2 包含哪些信号处理能力

| 能力 | 是否包含 | 实现模块 | 说明 |
|------|----------|----------|------|
| VAD (语音活动检测) | ✅ 是 | `fsmn_vad.py` → `FSMNVAD` | FunASR FSMN-VAD，ML 模型，线程安全 |
| VAD 辅助（RMS 静音检测） | ✅ 是 | `stt_streaming.py` → `SilenceDetector` | 轻量级静音检测，辅助 is_final 触发 |
| VAD 段合并 | ✅ 是 | `fsmn_vad.py` → `merge_short_segments()` | 合并碎片化的短段 |
| 音频降噪 | ❌ 否 | — | 代码中无降噪 DSP；仅 `audio_utils.py` 有高通滤波 (80Hz 去低频噪声)，不算完整降噪 |
| 说话人识别 | ❌ 否 | — | 无 Speaker Diarization / embedding |
| 标点恢复 | ✅ 是 | `punctuation.py` | CT-Transformer 实时标点模型 |
| 句子边界合并 | ✅ 是 | `sentence_merge.py` → `SentenceMerger` | 基于标点+长度+时长+间隔联合判定 |
| 机器翻译 (zh↔en) | ✅ 是 | `mt_engine.py` → `MTEngine` | 双向 Opus-MT (Helsinki-NLP) |
| 字幕落库 | ✅ 部分 | `history_store.py` → `HistoryStore` | SQLite 持久化翻译记录；不含字幕 UI |
| 音频格式转换/重采样 | ✅ 是 | `audio_utils.py` | 统一转 16kHz 单声道 float32 |

### 1.3 实时识别 vs 上传文件后识别

**两种模式都支持**：

- **离线模式**：`SpeechModule.transcribe(audio_path)` → 传入完整文件路径，返回识别全文
- **流式（接近实时）模式**：`SpeechModule.process_interim_chunk()` / `process_interim_array()` → 调用方逐 chunk 传入 numpy 数组，每个 chunk 立即返回当前累计文本。缓存 (CIF/FSNN encoder state) 在 session 内跨 chunk 保持。

注意：这不是传统意义上"边说边出字幕"的实时推流，而是"chunk-based incremental decode" — 需要调用方自己管理音频分块和传输节奏。

### 1.4 传输协议

**不是 WebSocket，不是 HTTP streaming，不是普通 HTTP。** 参考代码是**纯 Python 函数调用** — 调用方在同一进程中直接传 numpy 数组。设计意图是被 SmartDesk 后端服务直接 import 使用。

代码中没有 HTTP 端点、WebSocket handler，也没有音频流传输协议。

---

## 2. 依赖与运行环境

### 2.1 核心依赖

| 依赖 | 用途 | 来源 |
|------|------|------|
| **FunASR** | ASR (Paraformer) + VAD (FSMN) + 标点 (CT-Transformer) | `pip install funasr` |
| **PyTorch** | 深度学习运行时（所有模型推理） | `pip install torch` |
| **transformers** | MarianMT 翻译模型加载 | `pip install transformers` |
| **scipy** | 音频重采样 (signal.resample)、高通滤波 (signal.butter) | `pip install scipy` |
| **numpy** | 音频数据处理 | 内置依赖 |
| **soundfile** | WAV/FLAC 文件读取 | `pip install soundfile` |
| **pydub** (可选) | m4a/AAC 文件 fallback | `pip install pydub` |
| **sqlite3** | 翻译历史存储 | Python 标准库 |
| **importlib** | 模型预热时的导入检测 | Python 标准库 |

### 2.2 模型文件

| 模型名 | ModelScope ID | 用途 | 估算大小 |
|--------|--------------|------|----------|
| Paraformer Streaming | `iic/speech_paraformer_asr_nat-zh-cn-16k-common-vocab8404-online` | 流式中文 ASR | ~200MB |
| Paraformer-large | `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch` | 离线 2pass 纠错 | ~800MB |
| FSMN-VAD | `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch` | 语音活动检测 | ~50MB |
| CT-Transformer | `iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch` | 标点恢复 | ~100MB |
| Opus-MT zh-en | `Helsinki-NLP/opus-mt-zh-en` | 中→英翻译 | ~300MB |
| Opus-MT en-zh | `Helsinki-NLP/opus-mt-en-zh` | 英→中翻译 | ~300MB |
| **总计** | — | — | **~1.75GB** |

模型查找优先级：**显式指定路径 → 本地 HF 缓存 (`models/models--funasr--*`) → 本地 ModelScope 缓存 (`models/iic/*`) → 自动下载**。首次运行时会自动从 ModelScope/HuggingFace 下载模型。

### 2.3 GPU/硬件依赖

**可以在纯 CPU 上运行。** 所有模型默认 `device="cpu"`。代码中引用 CUDA 仅作为可选参数 (`device="cuda"`) 传入 FunASR AutoModel，不强制要求。不需要 GPU。

不需要麦克风设备 — 代码不直接采集音频。

### 2.4 Windows 11 兼容性

**不确定，需要实际验证。** 代码使用 Linux 风格的路径拼接（`/`），但 Python 的 `os.path` 会自动适配 Windows。FunASR、PyTorch、transformers 在 Windows 上均可运行。主要风险点：

- `pydub` 在 Windows 上需要 ffmpeg（如果处理非 WAV 格式）
- 模型缓存路径中的 glob 模式 (`models/models--*`) 在 Windows 上理论上可用
- `scipy.signal.resample` 在 Windows 上正常工作

### 2.5 安装命令

```bash
# 核心依赖
pip install funasr torch transformers scipy numpy soundfile

# 可选
pip install pydub  # m4a/AAC 支持

# 翻译功能需要环境变量启用
export SMART_DESK_ENABLE_MT=1
```

### 2.6 配置与环境变量

| 变量 | 作用 | 默认值 |
|------|------|--------|
| `SMART_DESK_ENABLE_MT` | 控制是否加载翻译模型 | 不设置（禁用） |
| `SMART_DESK_RUN_SLOW_MODELS` | 控制慢速模型测试是否运行 | 不设置（跳过） |

没有独立的配置文件 (.env, .yaml) — 所有配置通过构造函数参数或环境变量传入。

---

## 3. 输入输出契约

### 3.1 输入音频格式

| 参数 | 要求 |
|------|------|
| 数据类型 | `numpy.ndarray`（`transcribe_array`/`process_interim_array`）或文件路径 string（`transcribe`） |
| 采样率 | **任意 → 自动重采样到 16000 Hz**（`resample_if_needed` 使用 scipy） |
| 声道数 | 任意 → 自动转单声道（`audio.mean(axis=1)` 取平均） |
| 位深/编码 | 通过 soundfile 或 pydub 自动解码为 float32 |
| 支持文件格式 | 所有 soundfile 支持的格式 (WAV, FLAC, OGG) + pydub fallback 支持 (m4a, AAC, MP3) |

### 3.2 输出结果结构

**当前输出是纯文本 string，不是结构化 JSON：**

```python
# transcribe() / transcribe_array()
text: str  # 识别全文，如 "今天天气不错。"

# transcribe_and_translate()
(zh_text: str, en_text: str)  # 双向翻译对

# process_interim_chunk() / process_interim_array()
accumulated_text: str  # committed_text + pending_text 拼接

# process_interim 内部 (StreamingChunkProcessor.process_chunk())
{
    "text": str,           # 本 chunk 的新文本
    "full_text": str,      # 累计全部文本
    "is_final": bool,      # 是否为最终结果
    "decode_ms": float,    # 解码耗时 (ms)
    "cache_valid": bool,   # encoder 缓存是否有效
}

# HistoryStore 查询
{
    "id": int,
    "meeting_id": int,
    "seat_id": int,
    "segment_id": int,
    "zh_text": str,
    "en_text": str,
    "is_final": bool,
    "created_at": str,     # ISO format
}
```

**当前输出中 NOT 包含的字段**：`confidence`、`language`、`start_time`、`end_time`（音频级别）、`speaker`、`segments`（时间戳级别）。`SentenceMerger` 内部保留了 `start_time_s`/`end_time_s` 但仅用于 flush 决策，没有暴露到返回结果中。

### 3.3 增量 partial result 和最终 final result

**支持。** 通过 `process_interim_chunk()` 流程：

- 每个 chunk 返回包含 `committed_text + pending_text` 的累计文本（即 partial result）
- 当 `SentenceMerger` 检测到句末标点（。！？.!?）或达到 flush 条件（长度 >30 字 / 时长 >2s / 间隔 >1.2s）时，文本才被 commit 到历史
- `is_final=False` 时 CIF encoder cache 保持活跃，下一个 chunk 继续增量解码
- 临时结果通过 `get_interim()` 可随时获取

### 3.4 错误返回格式

**所有 STT 方法返回空字符串 `""` 作为失败信号，不抛出异常。** 翻译方法返回带 placeholder 的 tuple：

```python
# STT 失败: 静默返回空字符串
text = sm.transcribe("broken.wav")  # → ""

# 翻译未就绪:
sm.translate_text("你好")  # → ("你好", "[translation not available]")

# 翻译失败:
sm.translate_text("你好")  # → ("你好", "[translation failed]")

# STT+翻译全部失败:
sm.transcribe_and_translate("broken.wav")  # → ("[无法识别语音]", "[translation unavailable]")
```

---

## 4. 代码结构

### 4.1 模块职责一览

| 文件 | 行数 | 职责 | 核心/辅助 |
|------|------|------|-----------|
| `speech_module.py` | ~287 | **顶层 facade**：暴露所有公开方法，管理 session 生命周期，orchestrate 各子模块 | 🔴 核心 |
| `stt_streaming.py` | ~352 | **STT 核心**：加载 Paraformer 模型，chunk-based 增量解码，offline rescore | 🔴 核心 |
| `audio_utils.py` | ~121 | **音频预处理**：加载/重采样/高通滤波/峰值归一化 | 🔴 核心 |
| `fsmn_vad.py` | ~142 | **语音活动检测**：FSMN-VAD 模型 + 段合并后处理 | 🟡 重要 |
| `sentence_merge.py` | ~151 | **句子合并**：标点+长度+时长+间隔联合 flush 决策 | 🟡 重要 |
| `punctuation.py` | ~91 | **标点恢复**：CT-Transformer 实时标点模型 | 🟡 重要 |
| `history_store.py` | ~222 | **翻译历史存储**：SQLite CRUD，线程安全，upsert 语义 | 🟡 重要 |
| `mt_engine.py` | ~147 | **机器翻译**：双向 Opus-MT zh↔en | 🟢 辅助（可后装） |
| `text_utils.py` | ~172 | **文本工具**：语言检测、文本合并、CER/WER 计算、文本相似度 | 🟢 辅助 |
| `__init__.py` | ~18 | 模块导出，只暴露 `SpeechModule` | 🟢 辅助 |

### 4.2 可直接抽取为 service 的模块

- **`SpeechModule`** (`speech_module.py`) — 本身就是 facade，天然适合被 FastAPI 的 service 层或 router 直接依赖注入
- **`HistoryStore`** (`history_store.py`) — 独立的存储层，可直接被 SmartDesk 现有 DB 替代或复用
- **`audio_utils.py`** — 纯函数，无状态，可独立使用
- **`text_utils.py`** — 纯函数，无状态

### 4.3 哪些是 demo/UI/脚本/测试

- `tests/test_audio_utils.py` — 音频工具单元测试 (3 个测试)
- `tests/test_mt_engine.py` — MTEngine 单元/集成测试 (7 个测试)
- 没有 UI、demo 页面或脚本文件

---

## 5. 与 SmartDesk 的集成建议

### 5.1 可直接复用的部分

| 模块 | 复用方式 | 改造程度 |
|------|----------|----------|
| `SpeechModule.transcribe()` | 直接导入调用 | 零改造 |
| `HistoryStore` | 导入使用，或映射到 SmartDesk 已有 DB | 轻量适配 |
| `audio_utils.load_audio()` | 直接导入调用 | 零改造 |
| `text_utils.detect_language()` | 直接导入调用 | 零改造 |
| `FSMNVAD.detect_segments()` | 直接导入调用 | 零改造 |
| `SentenceMerger` | 流式场景复用 | 零改造 |

### 5.2 需要重写或适配的部分

| 部分 | 原因 | 改造方式 |
|------|------|----------|
| 音频传输层 | 当前无 HTTP 协议 | 新增 FastAPI endpoint |
| 流式推流层 | 当前是 Python 函数调用，非 WebSocket | 新增 WebSocket handler |
| 前端音频采集 | 代码中无前端部分 | 由 React/Vite 前端自行实现 `MediaRecorder` / `getUserMedia` |
| 翻译模型加载 | 翻译模型 ~600MB，可能不需要第一版加载 | 通过环境变量控制 |
| Session 管理 | 当前在内存 dict，非持久化 | 如需要多进程，考虑 Redis 外化 |

### 5.3 推荐集成方式对比

| 方案 | 描述 | 延迟 | 复杂度 | 适用场景 |
|------|------|------|--------|----------|
| **A: HTTP 上传** | 前端录音完成 → multipart 上传 WAV → `transcribe()` → 返回文本 | 高（需完整录音） | ⭐ 低 | **第一版推荐** |
| **B: WebSocket 流式** | 前端边录边通过 WebSocket 发送 chunk → `process_interim_array()` → 实时返回 partial | 低（~900ms） | ⭐⭐⭐ 高 | 后续迭代 |
| **C: 后台任务** | HTTP 上传 → 入队 Celery/RQ → 异步处理 → Webhook/Polling 返回 | 中 | ⭐⭐ 中 | 长音频批量处理 |

### 5.4 第一版最小可展示方案

```
┌─────────────────┐     HTTP POST /api/speech/transcribe     ┌──────────────────┐
│  React/Vite 前端  │  ── multipart/form-data (audio.wav) ──▶ │  FastAPI 后端      │
│  MediaRecorder   │                                         │  ┌──────────────┐ │
│  录制 → 停止 → 上传 │  ◀── JSON { text, zh, en } ────────── │  │ SpeechModule  │ │
└─────────────────┘                                         │  │ .transcribe() │ │
                                                            │  └──────────────┘ │
                                                            │  ┌──────────────┐ │
                                                            │  │ HistoryStore  │ │
                                                            │  └──────────────┘ │
                                                            └──────────────────┘
```

**具体步骤**：
1. 将 `speech_module/` 整个目录复制到 SmartDesk 后端项目中
2. 安装依赖：`pip install funasr torch scipy numpy soundfile`
3. 首次启动时自动下载 Paraformer-large 模型 (~800MB)
4. 新增 FastAPI endpoint：`POST /api/speech/transcribe`，接收 WAV 文件，返回识别文本
5. 可选：同时调用 `translate_text()` 返回双语结果
6. 可选：将结果写入 `HistoryStore` 或 SmartDesk 已有 DB
7. 前端：使用浏览器 `MediaRecorder` API 录制音频，录制完成后 POST 到后端

### 5.5 建议暂缓的功能

| 功能 | 理由 |
|------|------|
| WebSocket 流式实时字幕 | 需要前后端双向 streaming、VAD 集成、断句逻辑，复杂度 3x |
| 机器翻译 (Opus-MT) | 模型 ~600MB，加载慢，可先用 `text_utils.detect_language()` 做语言标记即可 |
| 说话人识别 (Speaker Diarization) | 代码中完全没有，需要选型新模型 |
| 音频降噪 | 代码中没有，需要额外 DSP 选型 |
| 多语种识别（非中文） | Paraformer 当前仅配置了中文模型 |

---

## 6. 数据与接口

### 6.1 已有字幕/翻译记录存储

✅ **有。** `HistoryStore` (`history_store.py`) 提供完整的 SQLite 存储：

```sql
CREATE TABLE translation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL,
    seat_id INTEGER NOT NULL,
    segment_id INTEGER NOT NULL,
    zh_text TEXT NOT NULL DEFAULT '',
    en_text TEXT NOT NULL DEFAULT '',
    is_final INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(meeting_id, seat_id, segment_id)
);
```

接口：
- `insert()` / `upsert()` — 写入记录
- `query_by_meeting()` / `query_by_seat()` — 分页查询
- `get_last_segment_id()` — 获取下一个 segment ID
- `get_segment_count()` — 计数
- `cleanup_old(days)` — 删除过期记录

### 6.2 能否映射到 SmartDesk 当前 translation records

**不确定，需要看 SmartDesk 当前数据库 schema。** 从 `HistoryStore` 的字段来看：
- `meeting_id` → 可能映射为 SmartDesk 的 meeting/room/session ID
- `seat_id` → 说话人位置/用户 ID
- `segment_id` → 句子序号
- `zh_text` / `en_text` → 识别原文 + 翻译
- `is_final` → 区分 partial 和 final 结果
- `created_at` → 时间戳

如果 SmartDesk 已有类似字段的表，可直接映射；如果没有，可直接复用此表结构。

### 6.3 推荐新增或修改的 API

| API | 方法 | 说明 |
|-----|------|------|
| `POST /api/speech/transcribe` | multipart | 上传音频文件，返回识别文本。**第一版必需** |
| `GET /api/speech/history?meeting_id=X&seat_id=Y` | GET | 查询历史记录。**推荐** |
| `POST /api/speech/transcribe-and-translate` | multipart | 上传音频，返回双语结果。**可选** |
| `WS /api/speech/stream/{session_id}` | WebSocket | 流式实时识别。**暂缓** |

### 6.4 是否需要新增数据库表

**如果 SmartDesk 当前没有类似结构，推荐新增：**

```sql
-- 最小可用的翻译历史表
CREATE TABLE speech_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL,
    seat_id INTEGER NOT NULL,
    segment_id INTEGER NOT NULL,
    source_text TEXT NOT NULL DEFAULT '',
    translated_text TEXT NOT NULL DEFAULT '',
    source_lang VARCHAR(10) DEFAULT '',
    is_final BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(meeting_id, seat_id, segment_id)
);
```

如果 SmartDesk 已有 DB（如 PostgreSQL/MySQL），把 `HistoryStore` 的 SQLite 替换为对应的 ORM 即可。

---

## 7. 测试与风险

### 7.1 现有测试

| 测试文件 | 测试数量 | 类型 | 如何运行 |
|----------|----------|------|----------|
| `tests/test_audio_utils.py` | 3 | 单元测试 | `pytest tests/test_audio_utils.py -v` |
| `tests/test_mt_engine.py` | 7 (4 单元 + 3 集成) | 单元/集成 | `pytest tests/test_mt_engine.py -v`（集成需要 `SMART_DESK_RUN_SLOW_MODELS=1`） |

**测试覆盖漏洞**：
- ❌ 没有 `SpeechModule` 集成测试
- ❌ 没有 `stt_streaming.py` (StreamingChunkProcessor) 单元测试
- ❌ 没有 `HistoryStore` 测试
- ❌ 没有 `SentenceMerger` 测试
- ❌ 没有 VAD 测试
- ❌ 没有端到端 (音频文件→识别文本) 测试

### 7.2 已知限制

| 限制 | 影响 |
|------|------|
| **仅支持中文 ASR** | Paraformer 模型选型为 zh-cn，英文/多语种需要换模型 |
| **VAD 模型不参与流式** | `FSMNVAD` 是整段检测，流式场景用轻量 `SilenceDetector`（RMS 阈值），精确度低于 ML VAD |
| **STT 静默失败** | 所有异常返回 `""`，无错误码区分"真的静音"vs"模型 crash" |
| **Session 在内存** | 进程重启后流式 session 丢失 |
| **无 confidence 分数** | 无法做信心度过滤 |
| **无时间戳** | 无法做字幕级时间对齐 |
| **Opus-MT 质量有限** | `Helsinki-NLP/opus-mt` 是 2020 年的模型，翻译质量低于 GPT/Claude API |

### 7.3 风险分析

| 风险类别 | 风险描述 | 缓解措施 |
|----------|----------|----------|
| **性能** | Paraformer-large (~800MB) 首次加载可能需要 10-30 秒；CPU 推理长音频可能较慢 | 预热阶段加载模型；限制单次音频时长；可选异步处理 |
| **并发** | `_streaming_model` 是全局单例，多线程并发调用 `generate()` 需要 FunASR 内部线程安全（代码中加锁仅在 VAD） | 单进程单 worker 或用锁保护；或以任务队列串行化 |
| **资源占用** | 全部模型 ~1.75GB 内存；CPU 推理时 fan noise 和 CPU 占用 | 按需加载：第一版只加载 Paraformer-large，跳过翻译+标点+VAD |
| **模型下载** | 首次启动依赖网络从 ModelScope 下载 ~1GB 模型，可能失败或超时 | 预下载模型到 `models/` 目录，打包进 Docker |
| **fallback/mock** | STT 错误返回 `""`，无降级方案 | 可提供基于 Google Web Speech API 的 fallback；或写死 demo 文本做 mock |
| **音频格式** | 前端 `MediaRecorder` 输出格式因浏览器而异（Chrome→webm, Safari→mp4） | 服务端用 pydub+ffmpeg 做统一转码 |

### 7.4 fallback/mock 模式

代码本身有 fallback 设计：
- 标点模型加载失败 → `add_punctuation()` 返回原文（graceful degradation）
- 翻译未加载 → `translate_text()` 返回 placeholder
- STT 异常 → 返回空字符串

但**没有开箱即用的 mock 模式**。如需 mock，可在 SmartDesk 中创建一个 `MockSpeechModule`：
```python
class MockSpeechModule:
    def transcribe(self, path): return "[Mock] 这是模拟识别结果"
    def transcribe_and_translate(self, path): return ("[Mock] 模拟中文", "[Mock] Mock English")
```

---

## 建议 SmartDesk 第一版最小集成方案

### 目标
**可展示、可运行**：用户在前端点击录音 → 说完后上传 → 后端返回识别文本 + 语言检测结果。

### 需要的文件（从 speech_module 复制/依赖）

```
smart-desk/backend/
├── speech_module/              # 整体复制
│   ├── __init__.py
│   ├── speech_module.py
│   ├── stt_streaming.py        # 核心 ASR（只需要 offline_rescore）
│   ├── audio_utils.py
│   ├── text_utils.py
│   ├── history_store.py        # 可选
│   └── (其余文件可暂时保留但不用)
├── api/
│   └── speech.py               # 新增：FastAPI router
```

### 新增 FastAPI endpoint（伪代码）

```python
# api/speech.py
from fastapi import APIRouter, UploadFile, File
from speech_module import SpeechModule
from speech_module.history_store import HistoryStore
import tempfile

router = APIRouter(prefix="/api/speech")

# 全局单例（应用启动时 preload）
sm = SpeechModule(max_workers=2, history_store=HistoryStore("data/speech.db"))
sm.preload()  # 启动时加载模型

@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """接收音频文件，返回识别文本"""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    text = sm.transcribe(tmp_path)
    zh_text, en_text = sm.translate_text(text) if text else ("", "")

    return {
        "text": text,
        "zh": zh_text,
        "en": en_text,
        "language": "zh",
    }
```

### 前端最小实现

```jsx
// 使用 MediaRecorder API 录制，停止后上传
const [recording, setRecording] = useState(false);
const [result, setResult] = useState("");

const startRecord = async () => {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mediaRecorder = new MediaRecorder(stream);
  const chunks = [];
  mediaRecorder.ondataavailable = (e) => chunks.push(e.data);
  mediaRecorder.onstop = async () => {
    const blob = new Blob(chunks, { type: 'audio/wav' });
    const formData = new FormData();
    formData.append('file', blob, 'recording.wav');
    const res = await fetch('/api/speech/transcribe', { method: 'POST', body: formData });
    const data = await res.json();
    setResult(data.text);
  };
  mediaRecorder.start();
  setRecording(true);
  // ... 5 秒后自动停止或手动停止
};
```

### 第一版明确不做的

- ❌ 不启用 WebSocket 流式识别
- ❌ 不加载翻译模型 (Opus-MT)
- ❌ 不加载 VAD 模型 (FSMN)
- ❌ 不加载标点模型 (CT-Transformer)
- ❌ 不做说话人识别
- ❌ 不做音频降噪
- ✅ 只做：**上传文件 → Paraformer-large 识别 → 返回文本**

### 预计内存占用

仅加载 `Paraformer-large` (~800MB) → 约 **1-1.5GB 内存**，纯 CPU 推理单次识别延迟取决于音频长度。

---

*本文档基于 `speech_module/` 目录下全部代码分析生成。标记"不确定"的项需要在实际部署环境中验证。*
