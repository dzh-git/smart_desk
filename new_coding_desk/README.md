# SmartDesk

SmartDesk 是一个面向 Windows 局域网环境的智能会议桌 demo。当前仓库包含
FastAPI 后端、React/Vite 前端、SQLite 持久化、WebSocket 实时同步、
本地 FunASR 语音识别、实时字幕、可选 OPUS-MT 翻译，以及可选的中央主机
屏幕采集与 WebRTC 共享功能。

中央主机手势控制由仓库同级目录 `../smartdesk_gesture_controller/` 提供。它不参与会议业务，但通过本机 Display Agent 切换会议屏、PowerPoint 和 SolidWorks。

## Quick Start

安装后端依赖：

```powershell
pip install -r requirements.txt
```

安装前端依赖：

```powershell
cd frontend
npm install
cd ..
```

启动本地 demo：

```powershell
.\start.bat
```

停止：

```powershell
.\kill.bat
```

可选屏幕共享（Screen Stream）：

PowerShell 中：

```powershell
$env:ENABLE_SCREEN_STREAM = "true"
.\start.bat
```

CMD 中：

```bat
set ENABLE_SCREEN_STREAM=true
start.bat
```

Screen Stream 默认关闭。启用前需将 FFmpeg 和 MediaMTX 二进制文件分别
放置到 `tools/ffmpeg/bin/ffmpeg.exe` 和 `tools/mediamtx/mediamtx.exe`。
详见 `host_services/screen_stream/README.md`。

该功能由中央主机本地 Display Agent、FFmpeg 和 MediaMTX 组成：FFmpeg
采集指定显示器，MediaMTX 通过 WebRTC 向局域网终端分发。`/admin` 中的
PowerPoint、SolidWorks、SmartDesk 窗口切换按钮只支持在中央主机本机浏览器
中使用，因为浏览器访问的 `127.0.0.1:8766` 始终指向浏览器所在机器。远程
终端可以观看 `/screen`，但不能通过该本地 Agent 控制中央主机窗口。

屏幕共享的代码和自动测试已经完成；外接显示器索引、PowerPoint/SolidWorks
窗口切换、局域网 WebRTC、10 客户端并发、延迟和长时间稳定性仍需在目标
Windows 主机上实测。未验证项见 `docs/DEFERRED_ISSUES.md`。

默认地址：

- 前端：`http://localhost:5173`
- 后端：`http://127.0.0.1:8000`
- OpenAPI：`http://127.0.0.1:8000/docs`
- Screen: `http://<中央主机IP>:5173/screen`
- WebRTC: `http://<中央主机IP>:8889/screen`

## Main Routes

| Route | Purpose |
|---|---|
| `/admin` | 主持人控制台。 |
| `/seat/:seatId` | 1 到 9 号座位端（seat 1 为主持人位）。 |
| `/display` | 中央大屏。 |
| `/screen` | 局域网终端使用的只读中央主机共享画面。 |
| `/` | 自动跳转到 `/admin`。 |
| `/?seat=N` | 兼容旧入口，自动跳转到 `/seat/N`。 |

## Useful Environment Variables

| Variable | Purpose |
|---|---|
| `ENABLE_DEMO_SEED=true` | 数据库为空时创建 demo 数据。 |
| `ENABLE_DEMO_SEED_WHEN_NO_ACTIVE=true` | 没有 active meeting 时创建 demo active meeting。 |
| `ENABLE_DEMO_SEAT_API=true` | 启用开发用座位占用/离座 API。 |
| `VITE_ENABLE_DEMO_CONTROLS=true` | 显示前端 demo 控件。 |
| `ENABLE_TRANSLATION_MODEL=true` | 启用本地 OPUS-MT 中英双向最终翻译。 |
| `TRANSLATION_ZH_EN_MODEL_PATH=...` | 覆盖本地中译英模型路径。 |
| `TRANSLATION_EN_ZH_MODEL_PATH=...` | 覆盖本地英译中模型路径。 |
| `BILINGUAL_ASR_MODEL_PATH=...` | 覆盖本地 SenseVoiceSmall 终稿识别路径。 |
| `ENGLISH_STREAMING_ASR_MODEL_PATH=...` | 覆盖本地 sherpa-onnx Zipformer 英语流式识别模型路径。 |
| `ENGLISH_ONLINE_PUNCTUATION_MODEL_PATH=...` | 覆盖本地 sherpa-onnx 英文在线标点模型路径。 |
| `CHINESE_ASR_MODEL_PATH=...` | 覆盖本地 Paraformer-large 中文终稿识别路径。 |
| `TRANSLATION_MODEL_PATH=...` | 旧版中译英路径兼容项。 |
| `RUN_TRANSLATION_SMOKE=true` | 启用翻译模型 smoke test。 |
| `ENABLE_DISPLAY_AGENT=true` | 启动本机窗口切换 Agent；默认开启。 |
| `ENABLE_SCREEN_STREAM=true` | 启动 FFmpeg 和 MediaMTX 屏幕串流；默认关闭。 |
| `SMARTDESK_AGENT_URL=...` | 后端只读状态聚合使用的 Display Agent 地址，默认 `http://127.0.0.1:8766`。 |
| `SMARTDESK_STREAM_PATH=screen` | MediaMTX 屏幕流路径。 |

## 项目结构（文件与目录说明）

仓库根目录下的每一份文件/目录作用如下：

### 配置与脚本

| 路径 | 作用 |
|---|---|
| `README.md` | 项目说明文档（即本文件）。 |
| `AGENTS.md` | 面向编码代理的项目约束、编码与协作规范。 |
| `requirements.txt` | 后端 Python 依赖清单，安装命令：`pip install -r requirements.txt`。 |
| `pytest.ini` | pytest 测试配置（测试发现路径与运行选项）。 |
| `start.bat` | 一键启动脚本：同时拉起 FastAPI 后端与 Vite 前端。 |
| `kill.bat` | 停止脚本：结束由 `start.bat` 启动的本地进程。 |

### 源码目录

| 路径 | 作用 |
|---|---|
| `backend/` | FastAPI 后端：路由、服务层、repository、ORM 模型、WebSocket 处理。 |
| `backend/speech_module/` | 语音实现：FunASR 识别、标点恢复、字幕格式化。 |
| `frontend/` | React + Vite + TypeScript 前端（含 `src/`、`package.json` 等）。 |
| `host_services/display_agent/` | 中央主机本地 Windows 窗口发现与切换 Agent（运行在 8766）。 |
| `host_services/screen_stream/` | FFmpeg/MediaMTX 配置、显示器探测与进程 Supervisor。 |
| `docs/` | 文档集合：API 契约、状态机、运行手册、架构与 ADR。 |
| `tests/` | 后端与语音自动化测试。 |
| `真实语音数据集/` | 真实中文语音样本（m4a + 转录 txt），用于评测，不纳入 git。 |
| `models/` | 本地模型权重与缓存（FunASR、OPUS-MT 等），不纳入 git。 |
| `tools/` | 第三方二进制：`tools/ffmpeg/`（FFmpeg）、`tools/mediamtx/`（MediaMTX），供 Screen Stream 使用。 |
| `node_modules/` | 前端 npm 依赖（由 `npm install` 生成，不纳入 git）。 |

### 运行产物（本地生成，不纳入 git）

| 路径 | 作用 |
|---|---|
| `smart_desk.db` | SQLite 运行数据库，由后端首次启动自动创建。 |
| `frontend.stderr.log` | 前端进程 stderr 日志，运行期输出。 |
| `working/` | 本地工作产物：计划、语音评测报告与 trace 等运行输出。 |
| `.hf_cache/` | HuggingFace 模型缓存目录，不纳入 git。 |

## Documentation Map

跨模块文档的权威来源与维护规则见仓库根目录的 `../DOCUMENTATION_INDEX.md`。

`docs/` 目录仅保留当前仍需要维护的文档。

| Document | Meaning |
|---|---|
| `docs/API_SPEC.md` | 当前 HTTP API 契约，包括会议、议程、座位、投票、服务、字幕和语音状态接口。 |
| `docs/HOST_DISPLAY_CONTRACT.md` | 中央主机屏幕采集、MediaMTX、Display Agent、只读状态 API、`/screen`、Admin 本机控制及启动部署的 Phase 1–6 冻结契约。 |
| `docs/DATABASE_SCHEMA.md` | SQLite 表结构、字段含义和 repository ownership。 |
| `docs/DEFERRED_ISSUES.md` | 当前 demo 已知但暂不阻塞的 deferred 问题。 |
| `docs/DEMO_RUNBOOK.md` | 本地启动、三端人工验收、语音验收和自动检查流程。 |
| `docs/EVENT_BUS_SPEC.md` | 后端 EventBus 事件发布者、事件名和客户端处理规则。 |
| `docs/FRONTEND_INTERACTION_SPEC.md` | 当前三端页面交互、按钮结果和 deferred 范围。 |
| `docs/FRONTEND_STATE_SPEC.md` | 当前前端状态分层、状态切换、按钮启用规则和会议结束数据来源。 |
| `docs/FRONTEND_VISUAL_SPEC.md` | SmartDesk 深色科技风视觉规范、token、组件和三端视觉约束。 |
| `docs/system_architecture.md` | 当前系统运行架构、后端分层、语音架构和测试策略。 |
| `docs/TECH_OVERVIEW.md` | 面向资深程序员的项目技术栈、构建方式和工程边界概览。 |
| `docs/WEBSOCKET_PROTOCOL.md` | 会议广播 WebSocket 和语音上行 WebSocket 协议。 |
| `docs/adr/0001-ws-audio-streaming.md` | ADR：语音上行从 HTTP chunk 改为 WebSocket 音频流。 |
| `docs/adr/0002-final-audio-source.md` | ADR：final 阶段使用后端缓存完整 PCM 做离线 ASR rescore。 |
| `docs/adr/0003-utterance-id-backend.md` | ADR：`utterance_id` 由后端生成。 |
| `docs/adr/0004-speaker-seat-switch.md` | ADR：Speaker Seat 切换为硬切换，旧 interim 丢弃。 |

已删除的旧文档类型：

- 一次性计划和提交范围文档。
- 过时的 frontend current-state 审查文档。
- 被 `FRONTEND_INTERACTION_SPEC.md` 和 `FRONTEND_STATE_SPEC.md` 合并覆盖的旧控制规范。
- agent 执行流程文档。

## Validation

后端：

```powershell
pytest -q
```

前端：

```powershell
cd frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build
npm run e2e:speech
```

屏幕共享代码级预检（需要已放置 FFmpeg，且依赖目标显示器和编码器）：

```powershell
python host_services/screen_stream/supervisor.py --check
```

如果命令因模型、浏览器、后端服务或本地环境缺失失败，应记录真实失败原因。

## Current Speech Contract

- Speech uplink：`/ws/speech/{meeting_id}?seat=N`
- Meeting broadcast：`/ws/{meeting_id}?seat=N`
- Audio：PCM16 little-endian、16 kHz、mono
- Language mode：发言席可选自动/中文/English；自动模式用 1.2 秒 SenseVoice 探测，本句锁定语言
- Interim events：中文由 Paraformer Streaming、英文由 sherpa-onnx Zipformer 真流式识别，并由本地 sherpa-onnx 在线标点模型低延迟恢复大小写和句内标点；仅在本地 Zipformer 缺失时降级到 SenseVoice 滚动识别。`translation_interim` 携带稳定 `sentence_id`、实际语言和识别引擎
- Sentence translation：英文短停顿只是候选边界，在线标点或后续文本确认后才提交；不完整尾词不会因 0.9 秒停顿被强制切开，无标点自然停顿 2 秒或手动停止仍会提交。完成后以 `translation_sentence` 按句顺序翻译；英文句末再由本地 SenseVoice 一次性校正，`source_locked` 后不再被后续流式结果改写
- Final events：SenseVoiceSmall 检测语言并识别英文；中文由 Paraformer-large 重识别，OPUS-MT 翻译到另一语言并持久化
- Live lyrics：终稿不会清除已配对的逐句字幕；英文在线标点确认句末且后续内容已经出现时，上一句立即结算、翻译并锁定为独立段落；超长内容在 40 词后可于逗号/分号等处结算，50 词按单词边界强制结算。`13rem` 固定高度字幕框保留完整句组并自动向下滚动
- Cancel cleanup：`translation_interim_cancelled`
- Auto-final：后端 RMS endpoint detection
- Manual fallback：`end_hint`
- 准备模型：`python backend/scripts/prepare_bilingual_models.py`
- 延迟验收：`python backend/scripts/benchmark_bilingual_translation.py`
- 启用翻译：`ENABLE_TRANSLATION_MODEL=true`
- CPU 预算：`SMART_DESK_TORCH_THREADS=4`、`SMART_DESK_TORCH_INTEROP_THREADS=1`（可覆盖）

### Speech latency diagnostics

`start.bat` enables bounded frontend/backend speech traces for local debugging.
Before a controlled reproduction, clear the backend ring buffer:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/speech/diagnostics/clear
```

Speak continuously for 20–30 seconds with at least three complete sentences,
including one short pause and one pause longer than two seconds. Then save the
backend diagnostics:

```powershell
$report = Invoke-RestMethod http://127.0.0.1:8000/api/speech/diagnostics?limit=10000
$report | ConvertTo-Json -Depth 12 | Set-Content .smartdesk-runtime/speech-backend-diagnostics.json -Encoding UTF8
```

In the speaker-seat browser DevTools console, run:

```javascript
window.__SMARTDESK_SPEECH_TRACE__.downloadTraceFile("speech-frontend-trace.json")
```

The backend file contains identifiers, timings, queue depths and memory only;
it does not contain PCM audio. Attach both JSON files when reporting latency.

### Reproducible speech dataset benchmark

The FLEURS-based benchmark bypasses microphone/browser timing and never starts
the FastAPI lifespan, Arduino, or Display Agent. Prepare the local CC-BY-4.0
subset and its volume-controlled/five-minute sessions:

```powershell
python backend/scripts/prepare_open_speech_latency_dataset.py
```

Replay PCM in production-sized 100 ms frames with the same 50-frame bounded
queue, live ASR routing and sentence translation used by the speech WebSocket:

```powershell
python backend/scripts/benchmark_streaming_speech_latency.py --suite smoke
python backend/scripts/benchmark_streaming_speech_latency.py --suite long
```

Evaluate final language detection, Chinese CER, English WER and translation
availability on the 30 original-volume utterances, then repeat after controlled
active-RMS normalization:

```powershell
python backend/scripts/benchmark_bilingual_speech_accuracy.py
python backend/scripts/benchmark_bilingual_speech_accuracy.py --normalize-audio `
  --output working/speech_latency_dataset/bilingual_accuracy_normalized_report.json
```

## Notes

- Runtime databases、logs、caches 和 `working/` 都是本地运行产物。
- 模型目录和真实语音数据集需保留，但不提交到 git。
- 手势识别模块位于同级 `../smartdesk_gesture_controller/`，与主程序共享 Display Agent，但不共享会议业务状态。
