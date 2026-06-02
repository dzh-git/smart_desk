# SmartDesk 全量技术规格（目标架构）

Version: 2.0
Date: 2026-06-02
Status: Target Architecture — Approved
Scope: 5 Modules — Speech, Seat, Vote, Service Call, Dashboard

---

# 1. 系统概述

## 1.1 项目背景

SmartDesk 是面向会议场景的智能会议桌系统。10 个智能座位通过 Arduino TOF 传感器检测入座，NUC 中央服务器处理语音识别/翻译，11 台平板终端（10 座位 + 1 管理台）提供交互界面。

## 1.2 项目目标 [待实现]

| 指标 | 目标值 |
|---|---|
| STT 语音识别准确率 | >= 85% |
| 端到端延迟 | < 2s（说话 → 所有平板显示翻译） |
| 稳定性 | 连续运行 3 小时无崩溃 |
| 交付周期 | 24 小时 |

注：当前代码库未系统化测量上述指标，需建立自动化评估流水线。

## 1.3 V1 Scope

**包含：** 10 座位、单会议实时运行、中文<->英文翻译、投票、服务呼叫、翻译历史

**不包含：** TTS、会议录音回放、多会议并发、多发言人同时识别、云端部署、用户认证

## 1.4 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI (Python 3.11+) |
| 数据库 | SQLite (SQLAlchemy ORM) — 统一 `smart_desk.db` |
| 实时通信 | WebSocket (room-based broadcast) |
| 事件系统 | In-process EventBus (dict dispatch, 零外部依赖) [待实现] |
| ASR | FunASR Paraformer (Streaming + Large Offline) |
| VAD | Client: vad-web + Server: FSMN-VAD（双重 VAD）|
| 翻译 | Helsinki-NLP Opus-MT (MarianMT) zh↔en |
| 硬件通信 | pyserial (115200 baud JSON-over-USB) |
| 前端 | Vue 3 + Vite + ECharts |
| 部署 | Dev: Vite proxy → uvicorn / Prod: Nginx same-origin |

---

# 2. 系统架构（目标架构）

## 2.1 架构总图 [待实现]

```text
                    ┌────────────────┐
                    │   Frontend     │
                    │ Vue 3 + Vite   │
                    │ 11 Tablets     │
                    └───────┬────────┘
                            │
                  HTTP      │      WebSocket
                            │
┌───────────────────────────▼─────────────────────────┐
│                    FastAPI (main.py)                 │
│                                                     │
│  routers/  (参数校验 + 调用 Service)                  │
│  ├── meetings.py          ├── seats.py              │
│  ├── votes.py             ├── service_calls.py       │
│  ├── translations.py      ├── attendees.py           │
│  └── dashboard.py                                   │
│                                                     │
│  services/  (业务逻辑 + 编排)                  [待实现] │
│  ├── meeting_service.py       ├── seat_service.py    │
│  ├── vote_service.py          ├── service_call_service.py │
│  ├── translation_service.py   ├── dashboard_service.py    │
│  ├── seat_state_machine.py (重命名自 business_logic.py)   │
│  ├── serial_service.py        ├── ws_service.py           │
│  └── event_bus.py             (新增)                      │
│                                                     │
│  repositories/  (数据访问隔离)                 [待实现] │
│  ├── meeting_repository.py    ├── attendee_repository.py  │
│  ├── seat_repository.py       ├── vote_repository.py      │
│  ├── service_call_repository.py                          │
│  └── translation_repository.py                           │
│                                                     │
│  database.py  (SQLAlchemy engine/session)            │
│  models.py    (9 ORM 模型, 含 TranslationRecord)     │
│  schemas.py   (Pydantic DTO)                         │
└────────────┬───────────────────────────────┬────────┘
             │                               │
             ▼                               ▼
      speech_module/                   Hardware Layer
      (ASR + MT + Dual VAD)       Arduino Nano ×10
                                  (TOF + LED)
```

## 2.2 模块职责

### Router 层 (`backend/routers/`)
- 参数校验、调用 Service、返回统一响应格式 `{"success": bool, "message": str, "data": {}}`
- 禁止：直接数据库操作、业务逻辑

### Service 层 (`backend/services/`) — 7 个新文件 [待实现]

| 文件 | 职责 |
|---|---|
| `meeting_service.py` | 会议 CRUD、开始/结束会议、cleanup、并发控制 |
| `seat_service.py` | 座位状态管理、签到校验、发言席管理 |
| `vote_service.py` | 投票 CRUD、投票提交、统计、关闭 |
| `service_call_service.py` | 服务呼叫 CRUD、超时自动取消 |
| `translation_service.py` | 翻译编排、STT/MT 调用、历史查询 |
| `dashboard_service.py` | 聚合查询：返回 meeting + speaker_seat + active_vote + pending_service_calls + seats |
| `seat_state_machine.py` | 纯状态机（重命名自 `business_logic.py`），零 I/O |
| `serial_service.py` | Arduino 串口管理：10路连接、心跳检测、LED 指令 |
| `ws_service.py` | WebSocket 房间管理：按 meeting_id 分组广播 |
| `event_bus.py` | 新增：In-process EventBus，dict dispatch |

### Repository 层 (`backend/repositories/`) — 6 个新文件 [待实现]

| 文件 | 管理的表 | 职责 |
|---|---|---|
| `meeting_repository.py` | `meetings`, `agendas` | 会议和议程 CRUD |
| `attendee_repository.py` | `attendees` | 参会者 CRUD、参会历史检查 |
| `seat_repository.py` | `seat_states`, `speaker_seat` | 座位状态和发言席读写 |
| `vote_repository.py` | `votes`, `vote_records` | 投票定义和投票记录 |
| `service_call_repository.py` | `service_calls` | 服务呼叫 CRUD |
| `translation_repository.py` | `translation_records` | 翻译历史读写、保留清理 |

每个 Repository 管理 1-2 张表，遵循 docs 定义的归属关系。

### Speech Module (`speech_module/`)
独立模块，不依赖 FastAPI/WebSocket/Arduino/Vue。可独立运行测试。翻译历史持久化由后端 Repository 负责，不再维护独立 `speech_history.db`。

## 2.3 目标架构 vs 当前实现差异

| 文档定义（目标）| 当前实现 | 状态 |
|---|---|---|
| Repository 层隔离 DB（6 个 Repository）| Router 内联 SQLAlchemy 查询 | [待实现] |
| Service 层（7 个 Service 文件）| 仅 `desk_coordinator.py` + `business_logic.py` | [待实现] |
| EventBus 解耦 | `desk_coordinator` 直接回调 + 方法调用 | [待实现] |
| TranslationRecord 在 backend SQLite | `speech_module/history_store.py` 独立 SQLite | [待实现] |
| Speaker Seat 持久化 DB | 内存 `_speaker_seats` dict | [待实现] |
| 双重 VAD（Client + Server）| 仅有 Server VAD (FSMN-VAD) | 部分实现 |
| 模型预加载由 `meeting_started` 触发 | 手动调用 `/preload` | [待实现] |
| 文件日志持久化 `logs/` 目录 | 仅 stdout | [待实现] |

## 2.4 依赖规则

允许：
```text
Router → Service → Repository → SQLite
Service → EventBus.publish(event)
Service → WebSocket 广播
TranslationService → SpeechModule
Handler → EventBus.subscribe(event_name, handler)
```

禁止：
```text
SpeechModule → FastAPI / WebSocket / Arduino / Vue
Hardware → Database / WebSocket
Router → 直接 DB 操作 / 业务逻辑
```

---

# 3. 数据模型

## 3.1 数据库

- 类型：SQLite
- 文件：`smart_desk.db`（项目根目录，统一数据库）
- ORM：SQLAlchemy 2.0
- 引擎创建：`backend/database.py`
- **注意：不再使用独立的 `speech_history.db`。TranslationRecord 已移入统一 SQLite。**

## 3.2 初始化策略 [待实现]

系统启动时自动执行（`main.py` lifespan）：
1. 检测数据库文件是否存在
2. 自动创建缺失的表（`Base.metadata.create_all`）
3. 自动创建种子数据（seed data）
4. 幂等操作——多次启动不会重复创建

种子数据：
- `seat_states`：seat_id 1~10，status='vacant'
- `speaker_seat`：id=1，seat_id=NULL

## 3.3 表总览 (9 张，统一 SQLite)

```text
meetings              — 会议主表
agendas               — 议程
attendees             — 参会者
seat_states           — 座位状态
speaker_seat          — 发言席（单行表，持久化 DB）
votes                 — 投票定义
vote_records          — 投票记录
service_calls         — 服务呼叫
translation_records   — 翻译历史（从 speech_history.db 移入）[待实现]
```

## 3.4 DDL

### meetings
```sql
CREATE TABLE meetings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | active | finished
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at  DATETIME,
    ended_at    DATETIME
);
```
约束：同一时间仅允许一个 `status='active'` 的会议（MeetingService 层保证，返回 400 + `ACTIVE_MEETING_EXISTS`）

### agendas
```sql
CREATE TABLE agendas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id),
    title      TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_agendas_meeting_sort ON agendas(meeting_id, sort_order);
```

### attendees
```sql
CREATE TABLE attendees (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id),
    name       TEXT NOT NULL,
    title      TEXT,
    seat_id    INTEGER UNIQUE,        -- NULL = 未分配座位; UNIQUE 约束保证一 seat 一 attendee
    checked_in BOOLEAN NOT NULL DEFAULT 0
);
CREATE INDEX idx_attendees_meeting ON attendees(meeting_id);
```
约束：
- `seat_id` 为 UNIQUE（可 NULL）——一个 seat 最多绑定一个 attendee [待实现]
- 一个 attendee 最多占用一个 seat（Service 层保证）
- 签到前必须预先分配 attendee（不允许匿名自动创建参会者）

### seat_states
```sql
CREATE TABLE seat_states (
    seat_id     INTEGER PRIMARY KEY,   -- 固定 1~10
    status      TEXT NOT NULL DEFAULT 'vacant',  -- vacant | occupied_unchecked | checked_in
    attendee_id INTEGER,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```
系统初始化时自动创建 seat_id 1~10，全部 `vacant`。

### speaker_seat
```sql
CREATE TABLE speaker_seat (
    id         INTEGER PRIMARY KEY CHECK (id = 1),  -- 永远只有一行
    seat_id    INTEGER,          -- NULL = 无发言席
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```
- 表中永远只允许一条记录（id=1），系统初始化自动创建（seat_id=NULL）
- 持久化 DB，服务器重启后 Speaker Seat 状态保留 [待实现]
- Speaker Seat 在座位离座时**不清除**——需 Admin 手动清除
- `meeting_ended` 时清除（seat_id 设为 NULL）

### votes
```sql
CREATE TABLE votes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id   INTEGER NOT NULL REFERENCES meetings(id),
    title        TEXT NOT NULL,
    options_json TEXT NOT NULL,       -- JSON array, e.g. '["Agree","Reject","Abstain"]'
    is_anonymous BOOLEAN NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'open',  -- open | closed
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at    DATETIME
);
CREATE INDEX idx_votes_meeting_status ON votes(meeting_id, status);
```
约束：同一时间最多一个 `status='open'` 的投票（VoteService 保证）
规则：`meeting_ended` → 自动关闭任何 open 投票 → broadcast `vote_closed` [待实现]

### vote_records
```sql
CREATE TABLE vote_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vote_id     INTEGER NOT NULL REFERENCES votes(id),
    attendee_id INTEGER NOT NULL REFERENCES attendees(id),
    option      TEXT NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(vote_id, attendee_id)   -- 一人一票
);
CREATE INDEX idx_vote_records_vote ON vote_records(vote_id);
CREATE INDEX idx_vote_records_attendee ON vote_records(attendee_id);
```
规则：
- 无最低参与人数要求——1 票即有效
- 座位置空前的投票记录保留，计入统计

### service_calls
```sql
CREATE TABLE service_calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id   INTEGER NOT NULL REFERENCES meetings(id),
    seat_id      INTEGER NOT NULL,
    service_type TEXT NOT NULL,       -- coffee | tea | water | other
    custom_text  TEXT,                -- service_type='other' 时的自定义文本 [待实现]
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | resolved | cancelled
    cancel_reason TEXT,               -- TIMEOUT | manual [待实现]
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at  DATETIME
);
CREATE INDEX idx_service_calls_meeting_status ON service_calls(meeting_id, status);
```
约束：
- 同一 seat 同时仅允许一个 `status='pending'` 的呼叫（Service 层保证）
- `pending` 超过 5 分钟（可配置 `SERVICE_CALL_TIMEOUT_SECONDS`）→ 自动取消，reason=`TIMEOUT`，广播 `service_call_cancelled` [待实现]

### translation_records [待实现：移入 backend SQLite]
```sql
CREATE TABLE translation_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id      INTEGER NOT NULL REFERENCES meetings(id),
    seat_id         INTEGER NOT NULL,
    source_lang     TEXT NOT NULL,
    target_lang     TEXT NOT NULL,
    source_text     TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_trans_records_meeting ON translation_records(meeting_id);
CREATE INDEX idx_trans_records_meeting_seat ON translation_records(meeting_id, seat_id);
CREATE INDEX idx_trans_records_created ON translation_records(created_at);
```
规则：
- 只允许新增，禁止修改历史记录
- 保留 180 天（可配置 `TRANSLATION_RETENTION_DAYS`）
- 每日清理任务删除 `created_at < cutoff` 的记录 [待实现]

## 3.5 ORM 模型归属（目标）

| 模型 | 定义位置 |
|---|---|
| Meeting, Agenda, Attendee, Vote, VoteRecord | `backend/models.py` |
| ServiceCall | `backend/models.py` |
| SeatState, SpeakerSeat | `backend/models.py` |
| TranslationRecord | `backend/models.py` [待实现：当前在 speech_module/history_store.py] |

---

# 4. API 参考

## 4.1 统一响应格式

**所有端点（包括 audio/stt 端点）** 均使用统一包装格式：

成功：
```json
{"success": true, "message": "OK", "data": {}}
```

失败：
```json
{"success": false, "message": "Seat already checked in", "data": null, "error_code": "SEAT_ALREADY_CHECKED_IN"}
```

## 4.2 HTTP 状态码

| 状态码 | 含义 |
|---|---|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request |
| 404 | Not Found |
| 409 | Conflict（如重复签到、重复 check-in、ACTIVE_MEETING_EXISTS）|
| 500 | Internal Error |

## 4.3 API 路径映射（目标 vs 当前代码）

| 功能 | 当前代码路径 | 目标路径（本文档）| 状态 |
|---|---|---|---|
| 文本翻译 | `/api/translate` | `/api/translations` | [待实现] |
| 音频翻译 | `/api/translate/audio` | `/api/translations/audio` | [待实现] |
| 翻译历史 | `/api/translate/history` | `GET /api/translations?meeting_id=N` | [待实现] |
| 发言席设置 | `/api/translate/speaker-seat` | `/api/seats/speaker` | [待实现] |
| 模型预加载 | `/api/translate/preload` | `/api/translations/preload` | [待实现] |
| 预加载状态 | `/api/translate/preload/status` | `/api/translations/preload/status` | [待实现] |

## 4.4 Dashboard API

### GET /api/dashboard
Caller: Admin Tablet
Service: DashboardService（聚合 Repository 查询）

Response:
```json
{
  "success": true,
  "message": "OK",
  "data": {
    "meeting": {},
    "speaker_seat": 3,
    "active_vote": {},
    "pending_service_calls": [],
    "seats": []
  }
}
```

DashboardService 通过 Repository 查询聚合上述 5 个数据块，不直接访问数据库。

## 4.5 Meeting APIs

| Method | Endpoint | Caller | Service | Event |
|---|---|---|---|---|
| GET | `/api/meetings` | Admin | MeetingService | -- |
| POST | `/api/meetings` | Admin | MeetingService | -- |
| GET | `/api/meetings/{id}` | Admin | MeetingService | -- |
| GET | `/api/meetings/active` | Admin, Seat | MeetingService | -- |
| POST | `/api/meetings/{id}/start` | Admin | MeetingService | `meeting_started` |
| POST | `/api/meetings/{id}/end` | Admin | MeetingService | `meeting_ended` |

### POST /api/meetings
```json
{"title": "Board Meeting", "description": "Quarterly Review"}
```
Response: 201 Created

约束：当已有 `status='active'` 的会议时，返回 400 + `ACTIVE_MEETING_EXISTS`。

### POST /api/meetings/{id}/start
触发副作用：
1. Meeting.status → `active`
2. 触发模型预加载（SpeechModule.preload()）[待实现：当前手动触发]
3. Broadcast `meeting_started`

### POST /api/meetings/{id}/end [待实现部分逻辑]
触发副作用：
1. Meeting.status → `finished`，记录 `ended_at`
2. 所有座位状态重置为 `vacant`
3. 清除 Speaker Seat（`speaker_seat.seat_id = NULL`）
4. 自动关闭任何 open 投票 → broadcast `vote_closed`
5. 保留 vote_records、service_calls、translation_records 数据
6. Broadcast `meeting_ended`

## 4.6 Agenda APIs

| Method | Endpoint | Caller |
|---|---|---|
| GET | `/api/meetings/{id}/agendas` | Admin |
| POST | `/api/meetings/{id}/agendas` | Admin |
| DELETE | `/api/meetings/{id}/agendas/{agenda_id}` | Admin |

### POST /api/meetings/{id}/agendas
```json
{"title": "Financial Report", "sort_order": 1}
```

## 4.7 Attendee APIs

| Method | Endpoint | Caller |
|---|---|---|
| GET | `/api/meetings/{id}/attendees` | Admin, Seat |
| POST | `/api/meetings/{id}/attendees` | Admin |
| DELETE | `/api/meetings/{id}/attendees/{attendee_id}` | Admin |

### POST /api/meetings/{id}/attendees
```json
{"name": "John", "title": "CEO"}
```

### DELETE /api/meetings/{id}/attendees/{attendee_id}
约束：如果该 attendee 已参与会议（签到、投票、服务呼叫），拒绝删除并返回错误。

## 4.8 Seat APIs

座位状态机：`vacant` → `occupied_unchecked` → `checked_in`

| Method | Endpoint | Caller | Service | Event |
|---|---|---|---|---|
| GET | `/api/seats` | Admin | SeatService | -- |
| POST | `/api/seats/{id}/checkin` | Seat Tablet | SeatService | `check_in` |
| GET | `/api/seats/speaker` | Admin, Seat | SeatService | -- |
| POST | `/api/seats/speaker` | Admin | SeatService | `speaker_seat_set` |
| DELETE | `/api/seats/speaker` | Admin | SeatService | `speaker_seat_clear` |

### POST /api/seats/{seat_id}/checkin
```json
{"attendee_id": 8}
```
前置条件：seat status = `occupied_unchecked`，attendee 必须已预分配
约束：
- 一个 attendee 最多占用一个 seat——重复签到返回 409 Conflict
- 一个 seat 最多绑定一个 attendee（DB UNIQUE 约束 + Service 校验）
- 不允许匿名自动创建参会者

### 座位重新入座 [待实现]
当座位离座后重新入座（TOF 检测入座），新 occupant 自动绑定到该座位之前的 attendee，保留参会者身份。

### POST /api/seats/speaker
```json
{"seat_id": 5}
```
规则：同一时间仅允许一个 Speaker Seat。切换时立即中断当前录音，丢弃未完成音频，强制切换。 [待实现：发言席切换中断录音]

## 4.9 Vote APIs

| Method | Endpoint | Caller | Event |
|---|---|---|---|
| GET | `/api/votes/active` | Seat, Admin | -- |
| POST | `/api/votes` | Admin | `vote_started` |
| GET | `/api/votes/{id}` | Seat, Admin | -- |
| POST | `/api/votes/{id}/submit` | Seat | `vote_updated` |
| GET | `/api/votes/{id}/statistics` | Admin, Seat | -- |
| POST | `/api/votes/{id}/close` | Admin | `vote_closed` |

### POST /api/votes
```json
{
  "meeting_id": 1,
  "title": "Approve Budget",
  "options": ["Agree", "Reject", "Abstain"],
  "is_anonymous": true
}
```

### POST /api/votes/{id}/submit
```json
{"attendee_id": 5, "option": "Agree"}
```
约束：一人一票（DB `UNIQUE(vote_id, attendee_id)`）
规则：无最低参与人数（1 票即有效）、座位置空前投票保留并计入统计

### GET /api/votes/{id}/statistics
投票关闭后，Seat 平板也可查看最终统计结果。

匿名响应：
```json
{"vote_id": 1, "is_anonymous": true, "results": {"Agree": 5, "Reject": 2}}
```

记名响应：
```json
{"vote_id": 1, "is_anonymous": false, "results": {"Agree": [1,3,8], "Reject": [5]}}
```

## 4.10 Service Call APIs

| Method | Endpoint | Caller | Event |
|---|---|---|---|
| POST | `/api/service-calls` | Seat | `service_call_created` |
| GET | `/api/service-calls` | Admin | -- |
| GET | `/api/service-calls/current?seat_id=4` | Seat | -- |
| POST | `/api/service-calls/{id}/resolve` | Admin | `service_call_resolved` |
| POST | `/api/service-calls/{id}/cancel` | Seat, Admin | `service_call_cancelled` |

### POST /api/service-calls
```json
{"seat_id": 4, "service_type": "coffee"}
```

或自定义服务：
```json
{"seat_id": 4, "service_type": "other", "custom_text": "可乐"}
```

service_type 枚举：`coffee` | `tea` | `water` | `other`
约束：同一 seat 同时仅允许一个 pending call

### 超时自动取消 [待实现]
`pending` 超过 5 分钟（可配置 `SERVICE_CALL_TIMEOUT_SECONDS`）→ 自动取消：
- `cancel_reason = "TIMEOUT"`
- 记录保留在 DB
- Broadcast `service_call_cancelled`

## 4.11 Translation APIs

| Method | Endpoint | Caller | Notes |
|---|---|---|---|
| POST | `/api/translations` | Seat | 纯文本翻译 [待实现：路径重命名] |
| POST | `/api/translations/audio` | Seat | FormData: audio + meeting_id + seat_id + final [待实现] |
| GET | `/api/translations?meeting_id=N` | Admin | 翻译历史 [待实现] |
| DELETE | `/api/translations?meeting_id=N` | Admin | 清空历史 [待实现] |
| POST | `/api/translations/preload` | -- | 触发模型预加载（由 meeting_started 自动调用）[待实现] |
| GET | `/api/translations/preload/status` | Seat | 查询加载状态 [待实现] |

### POST /api/translations/audio (FormData)
```
audio: binary (WAV, PCM16, 16000 Hz, Mono, max 20s segment)
meeting_id: int
seat_id: int
final: bool
utterance_id: int
```

音频格式要求：
- 格式：WAV
- 编码：PCM 16-bit
- 采样率：16000 Hz（后端可重采样不支持的采样率到 16kHz）[待实现：自动重采样]
- 声道：Mono
- 最大分段：20 秒

`final=false` → streaming ASR（Paraformer Streaming + SentenceMerger）
`final=true` → offline rescore（Paraformer-large）→ translate → persist → broadcast `translation_final`

### 模型未就绪时的行为 [待实现]
当 MT 模型加载失败时，会议继续但语音功能不可用。
- `GET /api/translations/preload/status` 返回 `{"ready": false}`
- 翻译 API 返回 `{"ready": false}`，不抛异常

## 4.12 错误码全集

```text
MEETING_NOT_FOUND           ACTIVE_MEETING_EXISTS
MEETING_ALREADY_FINISHED    ATTENDEE_NOT_FOUND
SEAT_NOT_FOUND              SEAT_OCCUPIED
SEAT_NOT_OCCUPIED           SEAT_ALREADY_CHECKED_IN
INVALID_SEAT_STATE          SPEAKER_SEAT_NOT_FOUND
VOTE_NOT_FOUND              VOTE_CLOSED
DUPLICATE_VOTE              INVALID_VOTE_OPTION
SERVICE_CALL_NOT_FOUND      SERVICE_CALL_ALREADY_RESOLVED
TRANSLATION_FAILED          SPEECH_MODULE_ERROR
MODEL_NOT_READY             ATTENDEE_HAS_HISTORY
INTERNAL_ERROR
```

---

# 5. 事件系统（目标架构）

## 5.1 EventBus 设计 [待实现]

V1 采用 In-process 简单 EventBus，零外部依赖：

```python
class BaseEvent:
    name: str
    payload: dict
    timestamp: float

class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}

    def publish(self, event: BaseEvent) -> None:
        """同步调用所有注册的 handler。"""

    def subscribe(self, event_name: str, handler: Callable) -> None:
        """注册事件处理器。"""
```

特点：
- Dict dispatch（`event_name → [handler, ...]`）
- 同步发布（handler 异常不影响其他 handler）
- 单例：`event_bus = EventBus()`
- V1 足够，不引入 Redis/RabbitMQ/kafka 等外部依赖

## 5.2 事件发布架构 [待实现]

```text
SerialService (daemon thread)
    ↓ _on_message callback
DeskCoordinator._on_serial()
    ↓ 更新状态机 (seat_state_machine.py)
    ↓ 控制 LED (serial_service.set_led)
    ↓ event_bus.publish(SeatOccupied(seat_id=3))
    ↓
EventBus → SeatService.on_seat_occupied()
         → ws_service.broadcast(event)
         → 其他订阅者
All Tablets
```

## 5.3 完整事件列表 (15 个业务事件)

### Seat Events
| Event | Publisher | Payload | Broadcast |
|---|---|---|---|
| `seat_occupied` | SerialService (via EventBus) | `{"seat_id": 3}` | YES |
| `seat_vacant` | SerialService (via EventBus) | `{"seat_id": 3}` | YES |
| `checkin_prompt` | SeatService | `{"seat_id": 3}` | YES（仅目标 seat 处理）|
| `check_in` | SeatService | `{"seat_id": 3, "attendee_id": 8}` | YES |
| `speaker_seat_set` | SeatService | `{"seat_id": 5}` | YES |
| `speaker_seat_clear` | SeatService | `{}` | YES |

### Meeting Events
| Event | Publisher | Payload | Broadcast |
|---|---|---|---|
| `meeting_started` | MeetingService | `{"meeting_id": 1}` | YES |
| `meeting_ended` | MeetingService | `{"meeting_id": 1}` | YES |

### Vote Events
| Event | Publisher | Payload | Broadcast |
|---|---|---|---|
| `vote_started` | VoteService | `{"vote_id": 1, "title": "..."}` | YES |
| `vote_updated` | VoteService | `{"vote_id": 1}` | YES（重命名为 vote_updated）|
| `vote_closed` | VoteService | `{"vote_id": 1}` | YES |

### Service Call Events
| Event | Publisher | Payload | Broadcast |
|---|---|---|---|
| `service_call_created` | ServiceCallService | `{"call_id": 1, "seat_id": 4, "service_type": "coffee"}` | YES |
| `service_call_resolved` | ServiceCallService | `{"call_id": 1}` | YES |
| `service_call_cancelled` | ServiceCallService | `{"call_id": 1, "reason": "TIMEOUT"}` | YES |

### Translation Events
| Event | Publisher | Payload | Broadcast |
|---|---|---|---|
| `translation_final` | TranslationService | `{"zh": "...", "en": "...", "seat_id": 3, "segment_id": 15, "is_final": true}` | YES |

### 事件命名变更对照

| 旧名称（当前代码）| 新名称（目标）| 影响范围 |
|---|---|---|
| `vote_update` | `vote_updated` | Frontend + Backend |
| `vote_cast` (frontend) | `vote_updated` | Frontend only |
| `translation_result` | `translation_final` | Backend only |
| `service_update` | 拆分为 `service_call_created` / `resolved` / `cancelled` | Backend + Frontend |

注意：`translation_interim` **不进入 WebSocket**，由 HTTP 直接返回，避免高频广播。

---

# 6. WebSocket 协议

## 6.1 端点

```text
ws://host:8000/ws/{meeting_id}?seat=N
```

V1 仅支持服务端 → 客户端广播。客户端不通过 WebSocket 发送业务请求。

## 6.2 连接生命周期

连接：
```json
{"event": "connected", "meeting_id": 1, "timestamp": 1748700000, "payload": {}}
```

断开：不发送业务事件，仅从房间移除。

## 6.3 消息格式

```json
{
  "event": "event_name",
  "meeting_id": 1,
  "timestamp": 1748700000,
  "payload": {}
}
```

## 6.4 房间模型

```text
meeting_id → Room → connections
```

一个会议一个房间。同房间所有客户端接收全部广播。客户端自行过滤（如 `checkin_prompt` 仅目标 seat 响应）。

## 6.5 断线行为 [待实现]

当 WebSocket 连接断开时，前端执行以下行为：

1. **UI 覆盖层：** 显示 "Connection Lost" 半透明遮罩
2. **允许操作：** 查看当前缓存数据（只读）
3. **阻止操作：** 投票、服务呼叫、所有实时交互操作
4. **自动重连：** 每 3 秒尝试重连一次
5. **重连成功：** 执行全量状态同步（重新请求 Dashboard/metting/seat 数据），然后恢复交互
6. **重连期间：** 用户不可离开当前页面

## 6.6 实现

文件：`backend/services/ws_service.py`

核心类：
- `Connection`：持有 WebSocket + seat_id
- `MeetingRoom`：connections 列表，`broadcast(msg)` 发送 JSON
- `WSService`：`rooms: dict[int, MeetingRoom]`，`get_or_create()` 懒创建

---

# 7. 硬件层

## 7.1 硬件架构

```text
NUC Server (USB Hub)
    ├── Arduino Nano #1  (Seat 1: TOF + LED)
    ├── Arduino Nano #2  (Seat 2: TOF + LED)
    ├── ...
    └── Arduino Nano #10 (Seat 10: TOF + LED)
```

## 7.2 串口协议

- 波特率：115200
- 格式：JSON + `\n`（UTF-8 编码）
- 库：pyserial（可选依赖，缺失时自动退化为 stub 模式）

### Arduino → Server

**启动消息：**
```json
{"type": "boot", "seat_id": 3}
```
用于自动端口发现和座位绑定。

**心跳：**
```json
{"type": "pong"}
```
Server 侧心跳超时：5 秒无 pong → 标记串口断开。

**TOF 检测（stub 模式下模拟）：**
```json
{"type": "seat_occupied", "seat_id": 3}
{"type": "seat_vacant", "seat_id": 3}
```

### Server → Arduino

**LED 控制：**
```json
{"type": "led", "pattern": "breathe", "color": [80, 140, 255], "brightness": 60}
```

LED Pattern 枚举：
| Pattern | 用途 |
|---|---|
| `off` | 座位空闲 |
| `breathe` | 空座位待机呼吸 |
| `wave` | 有人入座（未签到）|
| `solid` | 已签到 / 发言中 |

亮度上限：80（保护 LED 寿命）

## 7.3 Arduino 断线行为

当 Arduino 心跳超时（5 秒无 pong）时：
- `SeatConnection.connected = False`
- 日志记录：`WARNING: Seat {N} serial disconnected (heartbeat timeout)`
- `seat_states` 表中的记录**不变**（物理层问题不改变业务状态）
- 不广播任何业务事件

重连后：
- 自动恢复连接
- LED 状态根据当前座位状态重新同步

## 7.4 座位检测模式

- **Stub 模式：** 保留用于开发环境。通过命令行/配置开关控制。无硬件可运行。
- **Production 模式：** TOF 传感器为唯一位入座检测信号。无其他检测手段。

## 7.5 会议结束后的硬件事件 [待实现]

当 Meeting 处于 `finished` 状态时：
- 记录物理 TOF 事件（日志），但不改变业务状态
- 座位状态保持 `vacant`，不响应 `seat_occupied` / `seat_vacant`

## 7.6 实现

文件：`backend/services/serial_service.py`

核心类：
- `SeatConnection` dataclass：seat_id, port, last_heartbeat, connected
- `SerialService`：管理 10 路连接，daemon 线程 2秒轮询扫描
- stub 模式：`stub=True`（默认），开发环境无硬件可运行
- 单例：`serial_svc = SerialService(stub=True)`

## 7.7 LED 状态映射

| 座位状态 | Pattern | Color | 含义 |
|---|---|---|---|
| vacant | breathe | (255,200,150) 暖黄 | 待入座 |
| occupied_unchecked | wave | (80,140,255) 蓝 | 等待签到 |
| checked_in | solid | (255,220,180) 暖白 | 已签到 |
| speaker_seat | solid | (80,140,255) 蓝 | 当前发言 |
| vote_cast | solid (2s) | (212,176,76) 金 | 投票闪烁 |

---

# 8. 状态机

## 8.1 座位状态机

```text
         TOF 检测入座
  vacant ──────────────► occupied_unchecked
    ▲                        │
    │                        │ POST /api/seats/{id}/checkin
    │                        ▼
    │                    checked_in
    │                        │
    └────────────────────────┘
         TOF 检测离座 / 会议结束
```

状态定义：
- `vacant`：空座。LED: breathe 暖黄。
- `occupied_unchecked`：有人但未签到。LED: wave 蓝。
- `checked_in`：已签到。LED: solid 暖白。

规则：
- 仅 `occupied_unchecked` → `checked_in`
- `checked_in` 无法回退到 `occupied_unchecked`
- 任何状态 → `vacant`（离座或会议结束）
- Speaker Seat 在座位离座时不清除——Admin 必须手动清除
- 重新入座时自动绑定该座位之前的 attendee [待实现]

## 8.2 会议状态机

```text
 pending ──► active ──► finished
```

规则：
- 同一时间仅允许一个 `active` 会议（返回 400 + `ACTIVE_MEETING_EXISTS`）
- `finished` 不可逆
- 创建会议时不可指定 `active` 状态——必须通过 `/start` 端点转换

## 8.3 投票状态机

```text
 open ──► closed
```

规则：
- 同一时间最多一个 `open` 投票
- `closed` 不可逆
- 一人一票（`UNIQUE(vote_id, attendee_id)`）
- 无最低参与人数要求（1 票即有效）
- `meeting_ended` → 自动关闭 open 投票 + broadcast `vote_closed` [待实现]
- 投票关闭后 Seat 平板可查看统计结果

## 8.4 服务呼叫状态机

```text
                ┌──► resolved
 pending ───────┤
                └──► cancelled (manual / TIMEOUT)
```

规则：
- 同一 seat 同时仅允许一个 `pending` 呼叫
- `resolved` 和 `cancelled` 均为终态
- `pending` 超时 5 分钟 → 自动 `cancelled`，reason=`TIMEOUT` [待实现]

---

# 9. 业务流程图

## 9.1 入座签到流程

```text
TOF 传感器检测
    ↓
SerialService._read_all() 读到 {"type":"seat_occupied","seat_id":3}
    ↓
EventBus.publish(SeatOccupied(seat_id=3))    [待实现: EventBus]
    ↓
SeatService.on_seat_occupied()
    ├── state_machine.seat_occupied(3)
    │   └── vacant → occupied_unchecked
    ├── serial_svc.set_led(3, pattern="wave", color=BLUE)
    ├── ws_svc.broadcast({"event":"seat_occupied","payload":{"seat_id":3}})
    └── Timer(3s) → ws_svc.send_to_seat(3, {"event":"checkin_prompt","payload":{"seat_id":3}})
            ↓
        Seat 3 Tablet 弹出 CheckInModal
            ↓
        POST /api/seats/3/checkin  {"attendee_id": 8}
            ↓
        SeatService.checkin(3, 8)
            ├── 校验：seat status = occupied_unchecked
            ├── 校验：attendee 已预分配
            ├── 校验：attendee 未在其他 seat 签到（409 Conflict）
            ├── state_machine.check_in(3, 8)
            │   └── occupied_unchecked → checked_in
            ├── seat_repository.update(3, status="checked_in", attendee_id=8)   [待实现: Repository]
            ├── serial_svc.set_led(3, pattern="solid", color=WARM_WHITE)
            └── ws_svc.broadcast({"event":"check_in","payload":{"seat_id":3,"attendee_id":8}})
```

## 9.2 发言席切换流程

```text
Admin Tablet
    ↓
POST /api/seats/speaker  {"seat_id": 5}
    ↓
SeatService.set_speaker(5)
    ├── 如果有当前 Speaker Seat 正在录音 → 立即中断，丢弃未完成音频   [待实现]
    ├── speaker_seat seat_id = 5（持久化 DB）   [待实现]
    ├── 所有座位 LED 重置为状态默认色
    ├── serial_svc.set_led(5, pattern="solid", color=BLUE)   ← 发言席蓝色
    └── ws_svc.broadcast({"event":"speaker_seat_set","payload":{"seat_id":5}})
        ↓
    Seat 5 TranslationPanel: 开始录音
    其他 Seat TranslationPanel: 显示 listening 状态

Clear:
DELETE /api/seats/speaker
    ↓
SeatService.clear_speaker()
    ├── speaker_seat seat_id = NULL（持久化 DB）   [待实现]
    ├── 所有座位 LED 重置
    └── ws_svc.broadcast({"event":"speaker_seat_clear"})
```

## 9.3 投票流程

```text
Admin Tablet
    ↓
POST /api/votes  {"meeting_id":1, "title":"Approve Budget", "options":["Agree","Reject","Abstain"], "is_anonymous":false}
    ↓
VoteService 创建 vote (status=open) + VoteRepository 持久化   [待实现: Repository]
    ↓
EventBus.publish(VoteStarted(vote_id=1))   [待实现: EventBus]
    ├── 所有 occupied 座位 LED → gold
    └── ws_svc.broadcast({"event":"vote_started","payload":{"vote_id":1,"title":"..."}})
        ↓
    所有 Seat Tablet: VotingPanel 显示投票选项
        ↓
    Seat 3 投票: POST /api/votes/1/submit  {"attendee_id":5, "option":"Agree"}
        ↓
    VoteService 写入 vote_records (UNIQUE 约束防重复)
        ↓
    ws_svc.broadcast({"event":"vote_updated","payload":{"vote_id":1}})
    (不包含统计结果，仅通知更新)
        ↓
Admin 关闭: POST /api/votes/1/close
    ↓
VoteService status→closed
    ↓
EventBus.publish(VoteClosed(vote_id=1))   [待实现: EventBus]
    ├── 所有座位 LED 恢复状态默认色
    └── ws_svc.broadcast({"event":"vote_closed","payload":{"vote_id":1}})
        ↓
Admin + Seat: GET /api/votes/1/statistics → 查看结果（Seat 也可查看）
```

## 9.4 服务呼叫流程

```text
Seat 4 Tablet
    ↓
POST /api/service-calls  {"seat_id":4, "service_type":"coffee"}
或 {"seat_id":4, "service_type":"other", "custom_text":"可乐"}
    ↓
ServiceCallService: 检查 seat_id=4 是否已有 pending call → 409 拒绝
否则：ServiceCallRepository 写入 service_calls (status=pending)   [待实现: Repository]
    ↓
ws_svc.broadcast({"event":"service_call_created","payload":{"call_id":1,"seat_id":4,"service_type":"coffee"}})
    ↓
Admin Tablet: ServicePanel 显示 "Seat 4 → coffee [Mark Resolved]"
    ↓
Admin: POST /api/service-calls/1/resolve
    ↓
status→resolved, resolved_at=NOW
    ↓
ws_svc.broadcast({"event":"service_call_resolved","payload":{"call_id":1}})

超时场景 [待实现]:
    定时器检测 pending > 5 分钟
    → status→cancelled, cancel_reason="TIMEOUT"
    → ws_svc.broadcast({"event":"service_call_cancelled","payload":{"call_id":1,"reason":"TIMEOUT"}})
```

## 9.5 翻译流程（双重 VAD）

```text
Speaker (Seat 3) 说话
    ↓
Seat 3 Tablet 浏览器: useAudioRecorder
    ├── Client VAD (vad-web): 实时语音活动检测 → 分段录音
    ├── interim (每 800ms): POST /api/translations/audio  final=false
    │   └── Server VAD (FSMN-VAD) 统一校验 → 过滤误触发   [client VAD 已存在，server VAD 已存在]
    │   └── Paraformer Streaming → SentenceMerger 累积
    │       └── HTTP 200 {"zh": accumulated_text, "en": "", "final": false}
    └── final (VAD silence / 20s timeout): POST /api/translations/audio  final=true
        ↓
    Server VAD (FSMN-VAD) → 最终验证语音段有效性
        ↓
    Paraformer-large offline rescore → 完整文本
        ↓
    MTEngine.translate(text) → Opus-MT zh↔en
        ↓
    TranslationRepository.upsert(zh_text, en_text, meeting_id, seat_id, segment_id)   [待实现: Repository]
        ↓
    TranslationService.on_translation_result()
        └── ws_svc.broadcast({"event":"translation_final","payload":{"zh":"...","en":"...","seat_id":3,"segment_id":15,"is_final":true}})
            ↓
        所有 Tablet TranslationPanel: 双语显示更新
```

VAD 分工：
- **Client VAD (vad-web)：** 实时分段、减少上传频率、提升响应速度
- **Server VAD (FSMN-VAD)：** 统一校验、过滤误触发、保证 ASR 输入质量
- **Server VAD 拥有最终裁决权**

---

# 10. 前端组件映射

## 10.1 路由

| 路径 | 组件 | 用途 |
|---|---|---|
| `/` | HomeView | 会议列表，创建会议 |
| `/meeting/:id?seat=N` | MeetingView | 会议详情（编排所有面板）|

seat 参数：1~10 为座位平板，无 seat 参数 = 管理台（isAdmin=true）
isAdmin 判定：URL query 中无 `?seat=` 参数 → isAdmin=true

## 10.2 组件树

```text
App.vue
├── provide: seatId, isAdmin, appConnected
├── ConnectionLostOverlay.vue  (新增: WS 断线遮罩) [待实现]
├── <router-view>
│   ├── HomeView.vue
│   │   └── BaseDialog.vue (创建会议表单)
│   └── MeetingView.vue
│       ├── 接收 WS 消息 → lastWsMsg → 传给子组件
│       ├── SeatGrid.vue (1~10 座位置示)
│       │   ├── CheckInModal.vue
│       │   └── 10 个座位卡片 (occupied/checkedIn/LED 视觉效果)
│       ├── TranslationPanel.vue
│       │   ├── TranscriptHistoryModal.vue (Teleport to body)
│       │   ├── useAudioRecorder.js (Client VAD 录音 + STT 上传)
│       │   └── 发言席管理 + 双行抄本显示
│       ├── VotingPanel.vue
│       │   ├── BaseDialog.vue (创建投票)
│       │   └── ECharts 环形图 (CDN)
│       ├── ServicePanel.vue
│       │   └── 4 服务类型按钮 + 自定义输入 + 呼叫列表
│       ├── AgendaPanel.vue (议程 CRUD)
│       └── AttendeePanel.vue
│           └── BaseDialog.vue (添加参会者)
```

## 10.3 WebSocket 事件 → 前端组件处理

| WS Event | 处理组件 | 效果 |
|---|---|---|
| `seat_occupied` | SeatGrid | 座位蓝色 wave，脉冲动画 |
| `seat_vacant` | SeatGrid | 座位恢复空状态 |
| `checkin_prompt` | SeatGrid | 目标座位弹出 CheckInModal |
| `check_in` | SeatGrid, AttendeePanel | LED 金色，更新签到计数 |
| `speaker_seat_set` | TranslationPanel | 更新发言席，清除旧抄本 |
| `speaker_seat_clear` | TranslationPanel | 停止录音，清除显示 |
| `translation_final` | TranslationPanel | 双语抄本更新，按 segment_id 去重 |
| `vote_started` | VotingPanel, SeatGrid | 投票面板激活，LED 金色 |
| `vote_updated` | VotingPanel | 重载投票列表，重绘图表 |
| `vote_closed` | VotingPanel, SeatGrid | 投票关闭，LED 恢复 |
| `service_call_created` | ServicePanel | 刷新服务呼叫列表 |
| `service_call_resolved` | ServicePanel | 刷新服务呼叫列表 |
| `service_call_cancelled` | ServicePanel | 刷新服务呼叫列表 |
| `meeting_started` | MeetingView | meeting.status='active'，触发模型预加载 |
| `meeting_ended` | MeetingView, SeatGrid | 会议结束，座位重置 |

## 10.4 Composables

| Composable | 职责 |
|---|---|
| `useSeat.js` | seatId 决议链：route.query.seat → localStorage → 默认1。支持 1-10 范围。|
| `useWebSocket.js` | WS 连接：自动重连(3s)、心跳(15s ping)、断线时设置 appConnected=false |
| `useAudioRecorder.js` | 双重 VAD 录音：Client VAD (vad-web) 实时分段 + onnxruntime-web AudioWorklet 16kHz，每800ms interim，VAD silence 触发 final，20s 超时强制 final |

## 10.5 API 模块

文件：`frontend/src/api/index.js`

基础 URL：`/api`（Vite proxy 同源代理 / Nginx same-origin）。fetch 封装，自动 JSON 序列化/错误处理。

关键 API 函数（目标路径）：
```javascript
// Meetings
listMeetings()      createMeeting(data)     getMeeting(id)
updateMeeting(id,d) deleteMeeting(id)

// Agendas
listAgendas(mid)    addAgenda(mid, data)    removeAgenda(mid, aid)

// Attendees
listAttendees(mid)  addAttendee(mid, data)  removeAttendee(mid, aid)

// Check-in (Seats)
checkin(seatId, attendeeId)
getSpeakerSeat()    setSpeakerSeat(seatId)  clearSpeakerSeat()

// Votes
listVotes(mid)      createVote(mid, data)   getVote(mid, vid)
castVote(mid, vid, data)   closeVote(mid, vid)
getVoteStatistics(mid, vid)

// Service Calls
listServiceCalls(mid)       createServiceCall(mid, data)
resolveServiceCall(mid, cid)  cancelServiceCall(mid, cid)

// Translation
translateText(data)
uploadAudio(mid, seatId, blob, isFinal, utteranceId)
getPreloadStatus()
getTranslationHistory(mid)
```

注意：`uploadAudio` 使用 `multipart/form-data`（WAV, PCM16, 16000 Hz, Mono, max 20s），其余全部 `application/json`。

## 10.6 多 Admin 平板支持

允许多台 Admin 平板同时连接。Admin 为 UI 模式（无 `?seat=` 参数），非认证身份。所有权写操作必须幂等——状态由后端持有。

---

# 11. 部署配置

## 11.1 环境要求

- OS: Windows 11 / Linux
- Python: 3.11+
- Node.js: 18+
- 硬件: NUC, USB Hub ×1, Arduino Nano ×10, 平板 ×11

## 11.2 端口分配

| 服务 | Dev 端口 | Prod 端口 |
|---|---|---|
| FastAPI Backend | 8000 | 8000 (仅本地) |
| Vite Dev Server | 5173 | -- |
| Nginx | -- | 80/443 |
| WebSocket | 8000 (同 HTTP) | 80/443 (Nginx proxy) |

## 11.3 CORS 和代理配置

### Dev 模式
Vite 配置 proxy：
```javascript
// vite.config.js
export default {
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true }
    }
  }
}
```
无需后端配置 CORS。

### Prod 模式
Nginx same-origin 部署：
```nginx
location / {
    root /opt/smart-desk/frontend/dist;
    try_files $uri /index.html;
}
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
}
location /ws/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```
无需 `allow_origins=["*"]`。前后端同源，无跨域。

## 11.4 认证 [V1 无认证]

V1 不实现用户认证。采用 LAN 可信网络模型：
- isAdmin 由 URL query 中无 `?seat=` 参数判定
- 无登录、无 token、无 session

## 11.5 启动脚本

### Windows (`start.bat`)
```batch
:: 杀掉旧进程 (通过端口 8000/5173 查找 PID)
:: 启动后端: uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
:: 启动前端: npx vite --host 0.0.0.0 --port 5173
:: 自动打开 http://localhost:5173
```

### Linux/Mac (`start.sh`)
```bash
pkill -f "uvicorn backend.main:app"
pkill -f "vite"
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 &
npx vite --host 0.0.0.0 --port 5173 &
```

### 停止脚本
- Windows: `kill.bat`（按窗口标题 "SD-Backend" / "SD-Frontend" 杀进程）
- Linux: `kill.sh`（pkill）

## 11.6 日志 [待实现]

- **文件持久化：** `logs/` 目录，每日轮转
- **日志级别：** INFO（默认）/ DEBUG（开发）
- **关键日志事件：**
  - STT/MT 错误
  - 串口断开/重连
  - WebSocket 断线
  - 状态转换（meeting/vote/seat/service_call）
  - EventBus 事件发布失败

## 11.7 依赖

### Python (`backend/requirements.txt`)
```
fastapi>=0.109.0          uvicorn[standard]>=0.27.0
sqlalchemy>=2.0.0         pydantic>=2.0.0
python-multipart>=0.0.5   pyserial>=3.5
funasr>=1.0.0             modelscope>=1.10.0
soundfile>=0.12.0         scipy>=1.10.0
numpy>=1.24.0             transformers>=4.40.0
sentencepiece>=0.2.0
```

### Node (`frontend/package.json`)
```json
{
  "dependencies": {
    "vue": "^3.4",
    "vue-router": "^4.3",
    "@ricky0123/vad-web": "^0.0.29",
    "onnxruntime-web": "^1.22.0"
  },
  "devDependencies": {
    "vite": "^5.4",
    "@vitejs/plugin-vue": "^5.0"
  }
}
```
ECharts 通过 CDN 加载（VotingPanel.vue）。

## 11.8 模型缓存

STT 模型（FunASR Paraformer）和 MT 模型（Opus-MT）缓存在：
- FunASR: `~/.cache/modelscope/` 或项目 `models/` 目录
- Opus-MT: `~/.cache/huggingface/hub/` 或项目 `models/` 目录

模型加载优先级：显式 `model_dir` 参数 → 本地 HF/modelscope 缓存 → Hub 下载

## 11.9 目录结构总览（目标）

```text
smart-desk/
├── backend/
│   ├── main.py              # FastAPI app, lifespan, DB init, seed data
│   ├── database.py          # SQLAlchemy engine/session
│   ├── models.py            # ORM: 9 模型 (含 TranslationRecord)
│   ├── schemas.py           # Pydantic: 请求/响应 DTO
│   ├── requirements.txt
│   ├── routers/
│   │   ├── meetings.py      # Meeting/Agenda CRUD (调用 MeetingService)
│   │   ├── attendees.py     # Attendee CRUD (调用 MeetingService)
│   │   ├── seats.py         # 签到/发言席 (调用 SeatService) [待实现: 从 checkin.py + translation.py 拆分]
│   │   ├── votes.py         # 投票 CRUD (调用 VoteService)
│   │   ├── service_calls.py # 服务呼叫 CRUD (调用 ServiceCallService)
│   │   ├── translations.py  # 翻译/STT/历史 (调用 TranslationService) [待实现: 从 translation.py 重构]
│   │   └── dashboard.py     # Dashboard 聚合 (调用 DashboardService) [待实现: 新增]
│   ├── services/
│   │   ├── event_bus.py          # In-process EventBus [待实现]
│   │   ├── meeting_service.py    # 会议业务逻辑 [待实现]
│   │   ├── seat_service.py       # 座位业务逻辑 [待实现]
│   │   ├── seat_state_machine.py # 纯状态机 (重命名自 business_logic.py)
│   │   ├── vote_service.py       # 投票业务逻辑 [待实现]
│   │   ├── service_call_service.py # 服务呼叫业务逻辑 [待实现]
│   │   ├── translation_service.py  # 翻译编排 [待实现]
│   │   ├── dashboard_service.py    # Dashboard 聚合 [待实现]
│   │   ├── serial_service.py       # Arduino 串口
│   │   └── ws_service.py           # WebSocket 房间管理
│   └── repositories/
│       ├── meeting_repository.py     # meetings + agendas [待实现]
│       ├── attendee_repository.py    # attendees [待实现]
│       ├── seat_repository.py        # seat_states + speaker_seat [待实现]
│       ├── vote_repository.py        # votes + vote_records [待实现]
│       ├── service_call_repository.py # service_calls [待实现]
│       └── translation_repository.py  # translation_records [待实现]
├── speech_module/
│   ├── __init__.py
│   ├── speech_module.py     # 对外 Facade
│   ├── stt_streaming.py     # Paraformer Streaming + Offline
│   ├── mt_engine.py         # Opus-MT zh↔en
│   ├── sentence_merge.py    # 句边界感知文本合并
│   ├── punctuation.py       # CT-Transformer 标点恢复
│   ├── fsmn_vad.py          # Server VAD (FSMN-VAD)
│   ├── audio_utils.py       # 音频加载/重采样
│   ├── text_utils.py        # 语言检测/文本相似度
│   └── tests/
│       ├── test_mt_engine.py
│       └── ...
├── frontend/
│   └── src/
│       ├── main.js           # Vue 入口
│       ├── App.vue           # 根组件 + provide/inject + ConnectionLostOverlay
│       ├── style.css         # 全局样式 (暗色主题)
│       ├── api/index.js      # fetch 封装 (目标路径)
│       ├── router/index.js   # Vue Router
│       ├── composables/      # useSeat, useWebSocket, useAudioRecorder
│       ├── views/            # HomeView, MeetingView
│       ├── components/       # SeatGrid, TranslationPanel, VotingPanel, ...
│       └── utils/status.js   # 状态格式化
├── models/                   # 模型缓存目录
├── logs/                     # 日志目录 [待实现]
├── start.bat / start.sh
├── kill.bat / kill.sh
└── smart_desk.db             # 统一 SQLite 数据库
```

---

# 12. Speech Module

## 12.1 模块架构

```text
speech_module/speech_module.py  (Facade)
    ├── stt_streaming.py      Paraformer Streaming (process_interim_chunk)
    │                         Paraformer-large   (transcribe / transcribe_array)
    ├── fsmn_vad.py           FSMN-VAD Server VAD (统一校验、过滤误触发)
    ├── punctuation.py        CT-Transformer (标点恢复)
    ├── sentence_merge.py     SentenceMerger (句边界感知文本累积)
    ├── mt_engine.py          Opus-MT zh↔en (仅 final 翻译)
    ├── audio_utils.py        音频加载 + 16kHz 重采样（支持不兼容采样率自动转换）
    └── text_utils.py         语言检测 (zh/en) + 文本相似度
```

设计原则：**SpeechModule 必须可独立运行**，不依赖 FastAPI/WebSocket/Arduino/Vue。

注意：翻译历史持久化由后端 `TranslationRepository` 负责，不再在 speech_module 中维护 `history_store.py`。

## 12.2 双重 VAD 架构

```text
Client (Browser)                    Server (Python)
─────────────                       ────────────
vad-web (onnxruntime-web)     →      FSMN-VAD
AudioWorklet 16kHz                  统一校验
实时语音段检测                       过滤误触发
减少上传频率                        保证 ASR 输入质量
提升前端响应速度                     拥有最终裁决权
```

- **Client VAD (vad-web):** 实时分段录音，降低网络传输频率，提升 UI 响应
- **Server VAD (FSMN-VAD):** 对收到的音频段进行二次验证，过滤客户端误触发
- **Server VAD 有最终裁决权**——即使 client VAD 判定为语音，server VAD 仍可拒绝

## 12.3 STT 流水线

### Streaming (Interim)
```
音频 chunk (16kHz float32)
    ↓
FSMN-VAD → 语音段检测
    ↓
Paraformer Streaming (CIF cache 跨 chunk 保持)
    ↓
CT-Transformer 标点恢复
    ↓
SentenceMerger (句边界检测: 标点 + 长度 + 时长 + 间隔)
    ↓
累积文本 = committed_sentences + pending_text
    ↓
HTTP 200 {"zh": accumulated_text, "en": "", "final": false}
```

### Offline (Final)
```
完整语音段
    ↓
FSMN-VAD → 最终语音段有效性验证
    ↓
Paraformer-large (offline rescore，更高准确率)
    ↓
CT-Transformer 标点恢复
    ↓
MTEngine.translate(text) → (zh, en)
    ↓
TranslationRepository.upsert()  [待实现：Repository]
    ↓
WebSocket broadcast: {"event":"translation_final", "payload":{zh, en, seat_id, segment_id}}
```

## 12.4 MT Engine

文件：`speech_module/mt_engine.py`

```python
class MTEngine:
    """Bidirectional zh↔en via Helsinki-NLP Opus-MT."""

    def __init__(self, model_dir: str | None = None, device: str = "cpu")
    def preload(self) -> None          # 加载 zh→en + en→zh 两个模型，幂等
    @property
    def ready(self) -> bool            # preload 完成标志
    def translate(self, text: str) -> tuple[str, str]  # (zh_str, en_str)，永不抛异常
```

模型：
- `Helsinki-NLP/opus-mt-zh-en` (~300MB) — 中→英
- `Helsinki-NLP/opus-mt-en-zh` (~300MB) — 英→中

模型加载优先级（与 STT 一致）：
1. 显式 `model_dir` 参数
2. 本地 HuggingFace 缓存
3. HuggingFace Hub 下载

错误处理：永不抛异常。空输入 → `("", "")`，模型未加载 → `"[translation not available]"`，翻译失败 → `"[translation failed]"`。

### 模型预加载时机 [待实现]

预加载由 `meeting_started` 事件自动触发（非手动调用 `/preload`）。
- MeetingService.start() → EventBus.publish(MeetingStarted) → TranslationService 订阅 → SpeechModule.preload()
- 预加载失败时，会议继续，翻译 API 返回 `{"ready": false}`

### 模型加载失败处理 [待实现]

- 会议继续进行，非语音功能正常
- `GET /api/translations/preload/status` 返回 `{"ready": false}`
- 翻译 API 返回 `{"ready": false}`，不抛 500

性能目标：
| 指标 | 目标 |
|---|---|
| 双模型加载 | < 10s |
| 内存占用 | < 1GB |
| 单句翻译延迟 | < 500ms |
| 完整 preload (含 STT) | < 30s |

## 12.5 SentenceMerger

文件：`speech_module/sentence_merge.py`

句边界联合决策：标点结尾 (。！？.!?) + 长度 >= 阈值 + pending 时长 >= 阈值 + 新 chunk 与 pending 间隔。

目的：防止说话者句中停顿时过早切分句子。

## 12.6 翻译历史保留 [待实现]

- 保留期：180 天（可配置 `TRANSLATION_RETENTION_DAYS`）
- 每日清理任务：删除 `translation_records` 中 `created_at < cutoff` 的记录
- 清理任务由 `TranslationRepository.cleanup_expired()` 执行

## 12.7 SpeechModule Facade

```python
class SpeechModule:
    def __init__(max_workers=4, mt_engine=None)
    def preload() -> None                      # 加载所有模型 + warmup
    def transcribe(audio_path) -> str          # 离线转写文件
    def transcribe_array(audio, sr) -> str     # 离线转写数组 (支持自动重采样到16kHz)
    def translate_text(text) -> tuple[str,str] # MT 翻译（自动语言检测）
    def transcribe_and_translate(path) -> tuple[str,str]  # STT → MT 流水线
    def process_interim_chunk(path, session_key) -> str   # 流式 chunk
    def process_interim_array(audio, session_key, sr) -> str
    def reset_interim(session_key) -> None     # 重置句合并状态
    def start_utterance(session_key) -> None   # 新话语开始
    def get_interim(session_key) -> str        # 当前累积文本
    def set_session_context(session_key, meeting_id, seat_id)  # 绑定会议
```

---

# 13. 测试策略

每个模块必须可独立测试：

| 模块 | 测试命令 | 覆盖目标 |
|---|---|---|
| SpeechModule | `pytest speech_module/tests/` | MT translate, STT transcribe, VAD |
| SeatService | `pytest tests/test_seat_service.py` | 签到/状态机/发言席 [待实现] |
| VoteService | `pytest tests/test_vote_service.py` | CRUD/投票/统计/关闭 [待实现] |
| ServiceCallService | `pytest tests/test_service_call.py` | CRUD/超时取消 [待实现] |
| TranslationService | `pytest tests/test_translation_service.py` | 翻译编排 [待实现] |
| WebSocket | `pytest tests/test_ws.py` | 连接/广播/断线 [待实现] |
| Hardware | `pytest tests/test_serial.py` | 串口协议/心跳/断线 [待实现] |
| Repository 层 | `pytest tests/test_repositories.py` | 每 Repository CRUD [待实现] |
| EventBus | `pytest tests/test_event_bus.py` | publish/subscribe [待实现] |

测试原则：
- Service 层测试使用 mock Repository（避免数据库依赖）
- Repository 层测试使用内存 SQLite（`:memory:`）
- SpeechModule 标记 slow 的集成测试可选运行（需要模型下载）

现有测试：
- `speech_module/tests/test_mt_engine.py`：5 单元测试（快）+ 3 集成测试（标记 slow）

---

# 14. 版本历史

| Version | Date | Changes |
|---|---|---|
| 2.0 | 2026-06-02 | Target Architecture rewrite: 40 Q&A decisions applied, EventBus + Repository pattern, unified SQLite, dual VAD, all API paths aligned |
| 1.0 | 2026-06-02 | Initial full spec — 5 modules integrated (Speech, Seat, Vote, Service Call, Dashboard) |

---

# Appendix A: 已知差距 — 目标架构 vs 当前实现（迁移路线图）

以下差异标记了当前代码与目标架构的差距，按优先级排序：

## P0 — 阻塞项（影响核心功能）

| # | 当前实现 | 目标 | 迁移方案 |
|---|---|---|---|
| A1 | Router 内联 SQLAlchemy 查询 | Repository 层隔离 | 逐 Router 抽取 Repository，每次一个模块 |
| A2 | `desk_coordinator` 直接回调 | EventBus publish/subscribe | 实现 EventBus，逐步迁移事件发布 |
| A3 | TranslationRecord 在独立 `speech_history.db` | 统一 `smart_desk.db` | 数据迁移 + TranslationRepository 实现 |
| A4 | Speaker Seat 在内存 `_speaker_seats` dict | DB `speaker_seat` 表 | 迁移到 SeatRepository |

## P1 — 重要项（影响质量/可维护性）

| # | 当前实现 | 目标 | 迁移方案 |
|---|---|---|---|
| B1 | API 路径 `/api/translate/*` | `/api/translations/*`, `/api/seats/speaker` | Router 重构，更新前端 API 调用 |
| B2 | 事件名 `vote_update` / `translation_result` | `vote_updated` / `translation_final` | 全局重命名 |
| B3 | 签到允许匿名自动创建 attendee | 必须预分配 attendee | 移除自动创建逻辑，加校验 |
| B4 | 模型预加载手动触发 | `meeting_started` 自动触发 | TranslationService 订阅 MeetingStarted 事件 |
| B5 | 单一 Admin 平板（隐式假设） | 多 Admin 平板支持 | 确保所有写操作幂等 |

## P2 — 增强项（改善用户体验/运维）

| # | 当前实现 | 目标 | 迁移方案 |
|---|---|---|---|
| C1 | 无断线 UI 处理 | Connection Lost 遮罩 + 3s 重连 | 新增 ConnectionLostOverlay.vue |
| C2 | 无服务呼叫超时 | 5 分钟超时自动取消 | ServiceCallService 定时器 |
| C3 | 无翻译历史清理 | 180 天保留 + 每日清理 | TranslationRepository.cleanup_expired() |
| C4 | 无文件日志 | logs/ 目录每日轮转 | Python logging + RotatingFileHandler |
| C5 | `business_logic.py` | 重命名为 `seat_state_machine.py` | 文件重命名 + 更新 import |
| C6 | 无 seat 重入座绑定 | 自动绑定座位前 attendee | SeatService.on_seat_occupied() |
| C7 | meeting_ended 不关闭投票 | 自动关闭 open 投票 | MeetingService.end() 中触发 |
| C8 | 发言席切换不中断录音 | 立即中断当前录音 | TranslationService 中强制 reset |
| C9 | 无投票统计 Seat 访问 | Seat 平板可看统计 | GET statistics 不加 admin 限制 |

---

# Appendix B: 决策记录 — 40 项架构决策

| # | 决策领域 | 决策内容 |
|---|---|---|
| Q1 | 项目目标 | STT >= 85%，端到端 < 2s，连续 3h 无崩溃，24h 交付 |
| Q2 | 架构模式 | Router → Service → Repository → SQLite + EventBus |
| Q3 | API 路径 | 按 docs 路径统一重命名（translations / seats/speaker）|
| Q4 | 数据库 | 9 表统一 backend SQLite，TranslationRecord 移入 |
| Q5 | 签到 | 必须预分配参会者，不允许匿名自动创建 |
| Q6 | Dashboard | DashboardService 通过 Repository 聚合查询 |
| Q7 | VAD | 双重 VAD：Client vad-web + Server FSMN-VAD，Server 有最终裁决权 |
| Q8 | 座位检测 | Stub 模式保留开发环境；Production TOF 为唯一信号 |
| Q9 | 事件名称 | `vote_updated`, `translation_final`, `service_call_created/resolved/cancelled` |
| Q10 | EventBus | In-process dict dispatch，零外部依赖 |
| Q11 | Speaker Seat | 持久化 DB `speaker_seat` 表，服务器重启保留 |
| Q12 | Service 层 | 7 新文件：Meeting/Seat/Vote/ServiceCall/Translation/DashboardService + SeatStateMachine |
| Q13 | Repository 层 | 6 新文件：Meeting/Attendee/Seat/Vote/ServiceCall/TranslationRepository |
| Q14 | 响应格式 | 所有端点统一 `{"success": bool, "message": str, "data": {}}` |
| Q15 | 认证 | V1 无认证，LAN 可信网络，isAdmin 由 URL query 无 `?seat=` 判定 |
| Q16 | 会议结束 | 重置所有座位 vacant，清除 Speaker Seat，保留投票/呼叫/翻译记录 |
| Q17 | 投票结果 | 投票关闭后 Seat 平板可查看统计 |
| Q18 | 并发会议 | 400 + `ACTIVE_MEETING_EXISTS` 拒绝第二个 active 会议 |
| Q19 | 座位置空投票 | 置空前投票保留，计入统计 |
| Q20 | Speaker Seat 清除 | 离座不清除，Admin 手动清除 |
| Q21 | 投票自动关闭 | `meeting_ended` → 自动关闭 open 投票 + broadcast `vote_closed` |
| Q22 | 模型预加载 | `meeting_started` 事件触发，非手动 |
| Q23 | 音频格式 | WAV, PCM16, 16000 Hz, Mono, max 20s；后端可重采样 |
| Q24 | CORS / 部署 | Dev: Vite proxy / Prod: Nginx same-origin，无 CORS |
| Q25 | WS 断线 | Connection Lost 遮罩，3s 重连，重连后全量状态同步 |
| Q26 | 多座位签到 | 一 attendee 一 seat，一 seat 一 attendee，seat_id UNIQUE nullable |
| Q27 | 模型加载失败 | 会议继续，翻译 API 返回 `{"ready": false}` |
| Q28 | 翻译保留 | 180 天，`TRANSLATION_RETENTION_DAYS` 可配置，每日清理 |
| Q29 | DB 初始化 | 启动自动创建表和种子数据，幂等 |
| Q30 | 服务呼叫超时 | pending > 5min → auto-cancel, reason=TIMEOUT |
| Q31 | 座位重入座 | 新 occupant 自动绑定座位前 attendee |
| Q32 | 服务类型 | `other` + 可选 `custom_text` |
| Q33 | 多 Admin | 允许多台 Admin 平板，Admin = UI 模式，写操作幂等 |
| Q34 | Arduino 断线 | 心跳 5s 超时，seat_states 不变，日志记录 |
| Q35 | 座位数量 | 10 座位，useSeat 支持 1-10 |
| Q36 | 投票法定人数 | 无最低要求，1 票有效 |
| Q37 | 删除参会者 | 已参与会议（签到/投票/服务呼叫）则拒绝删除 |
| Q38 | 发言席切换 | 立即中断当前录音，丢弃未完成音频 |
| Q39 | 会后硬件事件 | 记录物理状态但不改变业务状态 |
| Q40 | 日志 | 文件持久化 `logs/` 目录，每日轮转，记录 STT/MT 错误、断线、状态转换 |

---

*文档结束。本规格为 SmartDesk 系统的目标架构定义，描述应构建的内容，而非当前已实现的代码。所有 `[待实现]` 标记的章节表示当前代码与目标的差距，对应迁移路线图见 Appendix A。*
