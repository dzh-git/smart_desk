# SmartDesk Technical Overview

本文档面向有经验的程序员，用于快速了解 SmartDesk 当前技术栈、运行方式和主要工程边界。

## 1. 项目定位

SmartDesk 是一个本地智能会议桌 demo，包含：

- 主持人控制台 `/admin`
- 座位端 `/seat/:seatId`
- 中央大屏 `/display`
- 后端会议、议程、投票、服务、座位、字幕和语音识别能力

当前项目不包含手势识别模块；手势控制如需使用，应作为独立本地控制程序维护。

## 2. 技术栈

### 后端

| 类别 | 技术 |
|---|---|
| Web 框架 | FastAPI |
| ASGI Server | Uvicorn |
| 数据库 | SQLite |
| ORM | SQLAlchemy |
| 数据模型 | Pydantic |
| 实时通信 | FastAPI WebSocket |
| 测试 | pytest、httpx TestClient |

后端采用分层结构：

```text
api/            HTTP router，做参数校验和响应封装
services/       业务规则、状态机、事件发布
repositories/   SQLite / SQLAlchemy 数据访问
models/         ORM model
schemas/        Pydantic request/response schema
events/         EventBus 事件定义
websocket/      会议广播和语音 WebSocket
speech_module/  FunASR、标点、caption formatting
```

### 前端

| 类别 | 技术 |
|---|---|
| Framework | React 18 |
| Build Tool | Vite |
| Language | TypeScript |
| Router | react-router-dom |
| Styling | Tailwind CSS |
| Icons | lucide-react |
| Unit Test | Vitest + Testing Library |
| E2E | Playwright |

前端核心目录：

```text
frontend/src/components/   三端页面和共享 UI 组件
frontend/src/hooks/        数据加载、WebSocket、语音流 hook
frontend/src/api/          HTTP API client 和类型
frontend/src/audio/        浏览器麦克风、PCM、speech WS client
frontend/e2e/              Playwright 测试
```

### 语音与翻译

| 能力 | 当前实现 |
|---|---|
| 流式语音识别 | FunASR，本地模型 |
| 音频上行 | `/ws/speech/{meeting_id}?seat=N`，PCM16 16kHz mono |
| 实时字幕 | `translation_interim` WebSocket 事件 |
| 最终记录 | final ASR 后写入 `translation_records` |
| 翻译 | 可选 OPUS-MT zh-en，默认关闭 |
| 自动断句 | 后端 RMS endpoint detection |

### 主机侧服务（Host Services）

本地 Windows 主机侧的屏幕串流与应用切换组件，独立于 FastAPI 后端与 React 前端：

| 能力 | 组件 |
|---|---|
| 屏幕采集与编码 | FFmpeg（Windows `ddagrab` 桌面采集 + H.264 编码，外部二进制，不入库） |
| 流媒体分发 | MediaMTX 1.19.0（RTSP 发布 + WebRTC 分发，外部二进制） |
| Windows 显示控制 Agent | FastAPI + pywin32 + psutil，loopback `127.0.0.1:8766` |
| 监督进程 | supervisor 启动并守护 MediaMTX 与 FFmpeg |

FFmpeg 与 MediaMTX 为外部部署二进制，不提交到 Git；相关代码位于
`host_services/screen_stream` 与 `host_services/display_agent`。

## 3. 构建与运行

### 安装依赖

```powershell
pip install -r requirements.txt
cd frontend
npm install
cd ..
```

### 本地启动

```powershell
.\start.bat
```

默认地址：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`
- OpenAPI：`http://127.0.0.1:8000/docs`

停止：

```powershell
.\kill.bat
```

### 单独启动方式

后端：

```powershell
uvicorn backend.main:app --reload
```

前端：

```powershell
cd frontend
npm run dev
```

## 4. 构建与测试命令

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

说明：

- `npm run build` 生成前端生产构建。
- Playwright 测试通常需要前后端服务或测试配置可用。
- 语音/翻译相关测试可能受本地模型、缓存和硬件影响。

## 5. 核心运行机制

### HTTP API

业务写操作通过 HTTP API 完成，包括会议、议程、座位、投票、服务请求、字幕查询和语音模型状态。

接口契约见：

- `docs/API_SPEC.md`
- `docs/DATABASE_SCHEMA.md`

### WebSocket

项目有两个 WebSocket 通道：

| 通道 | 用途 |
|---|---|
| `/ws/{meeting_id}?seat=N` | 会议事件广播，例如投票、议程、座位、服务、字幕 final/interim。 |
| `/ws/speech/{meeting_id}?seat=N` | 当前发言席上传 PCM 音频。 |

业务事件只通知客户端刷新或更新 UI，不通过 WebSocket 执行业务写入。

协议见：

- `docs/WEBSOCKET_PROTOCOL.md`
- `docs/EVENT_BUS_SPEC.md`

### 状态模型

前端状态分为：

- `meetingStatus`：会议生命周期；
- `voteStatus`：投票状态；
- `agendaStatus`：单个议题推进状态；
- `AdminWorkspace`：主持人端本地 UI 分组，不是业务状态。

状态规则见：

- `docs/FRONTEND_STATE_SPEC.md`
- `docs/FRONTEND_INTERACTION_SPEC.md`

## 6. 数据与模型

- SQLite 是本地 demo 数据库。
- 运行数据库、日志和缓存可以视为本地运行产物。
- `models/` 和 `.hf_cache/` 存放本地模型，不提交到 git。
- `真实语音数据集/` 用于语音识别评估，不提交到 git。

## 7. 当前工程边界

当前已实现：

- 三端前端：主持人、座位、大屏；
- 会议生命周期；
- 后端持久化 Agenda Command Center；
- 投票创建、提交、关闭和结果展示；
- 服务请求创建、取消、处理；
- 发言席控制；
- 语音识别、实时字幕和最终字幕记录；
- 会议结束后的结果保留。

当前 deferred：

- 会议列表和历史会议选择；
- 完整权限系统；
- 主持人控制大屏；
- 大屏字幕和当前发言人展示；
- 完整议题编辑器；
- 投票 draft/publish/archive/reopen。

## 8. 给后续评审者的建议入口

快速评审建议优先阅读：

1. `README.md`
2. `docs/TECH_OVERVIEW.md`
3. `docs/API_SPEC.md`
4. `docs/FRONTEND_STATE_SPEC.md`
5. `docs/WEBSOCKET_PROTOCOL.md`
6. `docs/DEMO_RUNBOOK.md`

如果要评估架构演进，继续阅读：

- `docs/system_architecture.md`
- `docs/adr/`
