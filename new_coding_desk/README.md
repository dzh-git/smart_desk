# SmartDesk

SmartDesk 是一个面向 Windows 局域网环境的智能会议桌 demo。当前仓库包含
FastAPI 后端、React/Vite 前端、SQLite 持久化、WebSocket 实时同步、
本地 FunASR 语音识别、实时字幕、可选 OPUS-MT 翻译，以及可选的中央主机
屏幕采集与 WebRTC 共享功能。

手势识别控制器不再属于当前前后端项目；如需中央主机手势控制，请使用独立项目目录。

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
| `/seat/:seatId` | 1 到 10 号座位端。 |
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
| `ENABLE_TRANSLATION_MODEL=true` | 启用本地 OPUS-MT zh-en 最终翻译。 |
| `TRANSLATION_MODEL_PATH=...` | 覆盖本地翻译模型路径。 |
| `RUN_TRANSLATION_SMOKE=true` | 启用翻译模型 smoke test。 |
| `ENABLE_SCREEN_STREAM=true` | 随 `start.bat` 启动 Display Agent、FFmpeg 和 MediaMTX；默认关闭。 |
| `SMARTDESK_AGENT_URL=...` | 后端只读状态聚合使用的 Display Agent 地址，默认 `http://127.0.0.1:8766`。 |
| `SMARTDESK_STREAM_PATH=screen` | MediaMTX 屏幕流路径。 |

## Main Folders

| Path | Purpose |
|---|---|
| `backend/` | FastAPI app、routers、services、repositories、models、WebSocket handlers。 |
| `backend/speech_module/` | 当前语音实现：FunASR、标点、caption formatting。 |
| `frontend/` | React + Vite + TypeScript 前端。 |
| `host_services/display_agent/` | 中央主机本地 Windows 窗口发现与切换 Agent。 |
| `host_services/screen_stream/` | FFmpeg/MediaMTX 配置、显示器探测和进程 Supervisor。 |
| `docs/` | 当前 API、状态机、运行手册、架构和 ADR 文档。 |
| `tests/` | 后端测试和语音测试。 |
| `models/` | 本地模型权重和缓存，不纳入 git。 |
| `.hf_cache/` | HuggingFace 缓存，不纳入 git。 |
| `真实语音数据集/` | 真实中文语音样本数据集，不纳入 git。 |

## Documentation Map

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
- Interim events：`translation_interim`，不持久化、不翻译
- Final events：`translation_final`，持久化到 `translation_records`
- Cancel cleanup：`translation_interim_cancelled`
- Auto-final：后端 RMS endpoint detection
- Manual fallback：`end_hint`
- Optional translation：`ENABLE_TRANSLATION_MODEL=true`

## Notes

- Runtime databases、logs、caches 和 `working/` 都是本地运行产物。
- 模型目录和真实语音数据集需保留，但不提交到 git。
- 当前仓库不包含手势识别模块和手势依赖。
