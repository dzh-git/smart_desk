# SmartDesk 全量技术规格

Version: 1.0
Date: 2026-06-02
Status: Draft — Pending Review
Scope: 5 Modules — Speech, Seat, Vote, Service Call, Dashboard

---

# 1. 系统概述

## 1.1 项目背景

SmartDesk 是面向会议场景的智能会议桌系统。10 个智能座位通过 Arduino TOF 传感器检测入座，NUC 中央服务器处理语音识别/翻译，11 台平板终端（10 座位 + 1 管理台）提供交互界面。

## 1.2 核心能力

- 自动入座检测（TOF 传感器 → 座位状态机）
- 签到管理（occupied_unchecked → checked_in）
- 发言席管理（单一 Speaker Seat）
- 实时语音识别（Paraformer Streaming + Offline）
- 实时双语翻译（Helsinki-NLP Opus-MT zh↔en）
- 匿名/记名投票
- 服务呼叫（咖啡/茶/水/其他）
- WebSocket 实时广播同步

## 1.3 V1 Scope

**包含：** 10 座位、单会议实时运行、中文↔英文翻译、投票、服务呼叫、翻译历史

**不包含：** TTS、会议录音回放、多会议并发、多发言人同时识别、云端部署

## 1.4 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI (Python 3.11+) |
| 数据库 | SQLite (SQLAlchemy ORM) |
| 实时通信 | WebSocket (room-based broadcast) |
| ASR | FunASR Paraformer (Streaming + Large Offline) |
| VAD | FSMN-VAD |
| 翻译 | Helsinki-NLP Opus-MT (MarianMT) |
| 硬件通信 | pyserial (115200 baud JSON-over-USB) |
| 前端 | Vue 3 + Vite + ECharts |
| 部署 | uvicorn + vite (bare-metal, NUC) |

---

# 2. 系统架构

## 2.1 架构总图

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
│  routers/                                           │
│  ├── meetings.py     (CRUD + 内联 DB)               │
│  ├── checkin.py      (签到)                         │
│  ├── votes.py        (投票 CRUD + 持久化)            │
│  ├── service_calls.py(服务呼叫 CRUD + 持久化)         │
│  └── translation.py  (语音识别/翻译 + Speaker Seat)   │
│                                                     │
│  services/                                          │
│  ├── desk_coordinator.py  (中央编排器)               │
│  ├── business_logic.py    (纯状态机，无 I/O)         │
│  ├── serial_service.py    (Arduino 串口)            │
│  └── ws_service.py        (WebSocket 房间管理)       │
│                                                     │
│  database.py  (SQLAlchemy engine/session)           │
│  models.py    (6 ORM 模型)                           │
│  schemas.py   (Pydantic DTO)                        │
└────────────┬───────────────────────────────┬────────┘
             │                               │
             ▼                               ▼
      speech_module/                   Hardware Layer
      (ASR + MT + VAD)            Arduino Nano ×10
                                  (TOF + LED)
```

## 2.2 模块职责

### Router 层 (`backend/routers/`)
- 参数校验、调用 Service/内联 DB、返回响应
- 禁止：直接业务逻辑（但当前实现中 DB 操作在 Router 内联）

### Service 层 (`backend/services/`)
| 文件 | 职责 |
|---|---|
| `desk_coordinator.py` | 中央编排：串口事件 → 状态机 → WS 广播 → LED 控制 |
| `business_logic.py` | 纯状态机：Seat(3态)、Vote(2态)，零 I/O |
| `serial_service.py` | Arduino 串口管理：10路连接、心跳检测、LED 指令 |
| `ws_service.py` | WebSocket 房间管理：按 meeting_id 分组广播 |

### Speech Module (`speech_module/`)
独立模块，不依赖 FastAPI/WebSocket/Arduino/Vue。可独立运行测试。

### 实际架构 vs 文档架构差异

| 文档定义 | 实际实现 |
|---|---|
| Repository 层隔离 DB | Router 内联 SQLAlchemy 查询 |
| EventBus 解耦 | `desk_coordinator` 直接回调 + 方法调用 |
| `events/` 目录 | 不存在，事件流在 `desk_coordinator._on_serial` 回调中 |
| `hardware/` 目录 | 硬件抽象仅在 `serial_service.py` |

## 2.3 依赖规则

允许：
```text
Router → Service → 内联 DB 查询
Service → WebSocket 广播
TranslationService → SpeechModule
```

禁止：
```text
SpeechModule → FastAPI / WebSocket / Arduino / Vue
Hardware → Database / WebSocket (当前 serial_service 遵守此规则)
```

---

# 3. 数据模型

## 3.1 数据库

- 类型：SQLite
- 文件：`smart_desk.db`（项目根目录）
- ORM：SQLAlchemy 2.0
- 引擎创建：`backend/database.py`

## 3.2 表总览 (9 张)

```text
meetings           — 会议主表
agendas            — 议程
attendees          — 参会者
seat_states        — 座位状态
speaker_seat       — 发言席（单行表）
votes              — 投票定义
vote_records       — 投票记录
service_calls      — 服务呼叫
translation_records — 翻译历史
```

## 3.3 DDL

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
约束：同一时间仅允许一个 `status='active'` 的会议（Service 层保证）

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
    seat_id    INTEGER,          -- NULL = 未分配座位
    checked_in BOOLEAN NOT NULL DEFAULT 0
);
CREATE INDEX idx_attendees_meeting ON attendees(meeting_id);
```
业务主键：`attendee_id`。`name` 不要求唯一。

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
表中永远只允许一条记录（id=1），系统初始化自动创建（seat_id=NULL）。

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

### service_calls
```sql
CREATE TABLE service_calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id   INTEGER NOT NULL REFERENCES meetings(id),
    seat_id      INTEGER NOT NULL,
    service_type TEXT NOT NULL,       -- coffee | tea | water | other
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | resolved | cancelled
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at  DATETIME
);
CREATE INDEX idx_service_calls_meeting_status ON service_calls(meeting_id, status);
```
约束：同一 seat 同时仅允许一个 `status='pending'` 的呼叫（Service 层保证）

### translation_records
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
规则：只允许新增，禁止修改历史记录。

## 3.4 初始化数据

系统首次启动时自动创建：
- `seat_states`：seat_id 1~10，status='vacant'
- `speaker_seat`：id=1，seat_id=NULL

## 3.5 ORM 模型归属

| 模型 | 定义位置 |
|---|---|
| Meeting, Agenda, Attendee | `backend/models.py` |
| Vote, VoteRecord | `backend/models.py` |
| ServiceCall | `backend/models.py` |
| TranslationRecord | `speech_module/history_store.py`（独立 SQLite） |

---

# 4. API 参考

## 4.1 统一响应格式

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
| 409 | Conflict |
| 500 | Internal Error |

## 4.3 Dashboard API

### GET /api/dashboard
Caller: Admin Tablet
Service: DashboardService（聚合查询）

Response:
```json
{
  "meeting": {},
  "speaker_seat": 3,
  "active_vote": {},
  "pending_service_calls": [],
  "seats": []
}
```

## 4.4 Meeting APIs

| Method | Endpoint | Caller | Service | Event |
|---|---|---|---|---|
| GET | `/api/meetings` | Admin | MeetingService | — |
| POST | `/api/meetings` | Admin | MeetingService | — |
| GET | `/api/meetings/{id}` | Admin | MeetingService | — |
| GET | `/api/meetings/active` | Admin, Seat | MeetingService | — |
| POST | `/api/meetings/{id}/start` | Admin | MeetingService | `meeting_started` |
| POST | `/api/meetings/{id}/end` | Admin | MeetingService | `meeting_ended` |

### POST /api/meetings
```json
{"title": "Board Meeting", "description": "Quarterly Review"}
```
→ 201 Created

## 4.5 Agenda APIs

| Method | Endpoint | Caller |
|---|---|---|
| GET | `/api/meetings/{id}/agendas` | Admin |
| POST | `/api/meetings/{id}/agendas` | Admin |

### POST /api/meetings/{id}/agendas
```json
{"title": "Financial Report", "sort_order": 1}
```

## 4.6 Attendee APIs

| Method | Endpoint | Caller |
|---|---|---|
| GET | `/api/meetings/{id}/attendees` | Admin, Seat |
| POST | `/api/meetings/{id}/attendees` | Admin |

### POST /api/meetings/{id}/attendees
```json
{"name": "John", "title": "CEO"}
```

## 4.7 Seat APIs

座位状态机：`vacant` → `occupied_unchecked` → `checked_in`

| Method | Endpoint | Caller | Service | Event |
|---|---|---|---|---|
| GET | `/api/seats` | Admin | SeatService | — |
| POST | `/api/seats/{id}/checkin` | Seat Tablet | SeatService | `check_in` |
| GET | `/api/seats/speaker` | Admin, Seat | SeatService | — |
| POST | `/api/seats/speaker` | Admin | SeatService | `speaker_seat_set` |
| DELETE | `/api/seats/speaker` | Admin | SeatService | `speaker_seat_clear` |

### POST /api/seats/{seat_id}/checkin
```json
{"attendee_id": 8}
```
前置条件：seat status = `occupied_unchecked`

### POST /api/seats/speaker
```json
{"seat_id": 5}
```
规则：同一时间仅允许一个 Speaker Seat

## 4.8 Vote APIs

| Method | Endpoint | Caller | Event |
|---|---|---|---|
| GET | `/api/votes/active` | Seat, Admin | — |
| POST | `/api/votes` | Admin | `vote_started` |
| GET | `/api/votes/{id}` | Seat, Admin | — |
| POST | `/api/votes/{id}/submit` | Seat | `vote_updated` |
| GET | `/api/votes/{id}/statistics` | Admin | — |
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
约束：一人一票（`UNIQUE(vote_id, attendee_id)`）

### GET /api/votes/{id}/statistics

匿名响应：
```json
{"vote_id": 1, "is_anonymous": true, "results": {"Agree": 5, "Reject": 2}}
```

记名响应：
```json
{"vote_id": 1, "is_anonymous": false, "results": {"Agree": [1,3,8], "Reject": [5]}}
```

## 4.9 Service Call APIs

| Method | Endpoint | Caller | Event |
|---|---|---|---|
| POST | `/api/service-calls` | Seat | `service_call_created` |
| GET | `/api/service-calls` | Admin | — |
| GET | `/api/service-calls/current?seat_id=4` | Seat | — |
| POST | `/api/service-calls/{id}/resolve` | Admin | `service_call_resolved` |
| POST | `/api/service-calls/{id}/cancel` | Seat, Admin | `service_call_cancelled` |

### POST /api/service-calls
```json
{"seat_id": 4, "service_type": "coffee"}
```
service_type 枚举：`coffee` | `tea` | `water` | `other`

约束：同一 seat 同时仅允许一个 pending call

## 4.10 Translation APIs

| Method | Endpoint | Caller | Notes |
|---|---|---|---|
| POST | `/api/translate` | Seat | 纯文本翻译 |
| POST | `/api/translate/audio` | Seat | FormData: audio + meeting_id + seat_id + final |
| GET | `/api/translate/history?meeting_id=N` | Admin | 翻译历史 |
| DELETE | `/api/translate/history?meeting_id=N` | Admin | 清空历史 |
| POST | `/api/translate/preload` | Admin | 触发模型预加载 |
| GET | `/api/translate/preload/status` | Seat | 查询加载状态 |
| POST | `/api/translate/speaker-seat` | Admin | 设置发言席 |
| GET | `/api/translate/speaker-seat` | Admin, Seat | 查询发言席 |

### POST /api/translate/audio (FormData)
```
audio: binary (WAV)
meeting_id: int
seat_id: int
final: bool
utterance_id: int
```

final=false → streaming ASR（Paraformer Streaming + SentenceMerger）
final=true → offline rescore（Paraformer-large）→ translate → persist → broadcast

## 4.11 错误码全集

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
INTERNAL_ERROR
```

---

# 5. 事件系统

## 5.1 实际实现

项目 **未使用** EventBus 模式。事件流通过以下机制实现：

1. **硬件 → 状态机：** `serial_service._on_message` 回调 → `desk_coordinator._on_serial`
2. **状态机 → WS 广播：** `desk_coordinator` 直接调用 `ws_svc.get_or_create(meeting_id).broadcast()`
3. **Router → WS 广播：** Router 直接调用 `ws_svc` broadcast

## 5.2 事件流架构

```text
SerialService (daemon thread)
    ↓ _on_message callback
DeskCoordinator._on_serial()
    ↓ 更新状态机 (business_logic.py)
    ↓ 控制 LED (serial_service.set_led)
    ↓ 广播 WS (ws_service.broadcast)
    ↓ 调度定时任务 (threading.Timer)
All Tablets
```

## 5.3 完整事件列表 (15 个业务事件 + 1 连接事件)

### Seat Events
| Event | Publisher | Payload | Broadcast |
|---|---|---|---|
| `seat_occupied` | DeskCoordinator | `{"seat_id": 3}` | YES |
| `seat_vacant` | DeskCoordinator | `{"seat_id": 3}` | YES |
| `checkin_prompt` | DeskCoordinator | `{"seat_id": 3}` | YES（仅目标 seat 处理）|
| `check_in` | checkin router | `{"seat_id": 3, "attendee_id": 8}` | YES |
| `speaker_seat_set` | translation router | `{"seat_id": 5}` | YES |
| `speaker_seat_clear` | translation router | `{}` | YES |

### Meeting Events
| Event | Publisher | Payload | Broadcast |
|---|---|---|---|
| `meeting_started` | meetings router | `{"meeting_id": 1}` | YES |
| `meeting_ended` | meetings router | `{"meeting_id": 1}` | YES |

### Vote Events
| Event | Publisher | Payload | Broadcast |
|---|---|---|---|
| `vote_started` | votes router | `{"vote_id": 1, "title": "..."}` | YES |
| `vote_updated` | votes router | `{"vote_id": 1}` | YES（不含统计）|
| `vote_closed` | votes router | `{"vote_id": 1}` | YES |

### Service Call Events
| Event | Publisher | Payload | Broadcast |
|---|---|---|---|
| `service_call_created` | service_calls router | `{"call_id": 1, "seat_id": 4, "service_type": "coffee"}` | YES |
| `service_call_resolved` | service_calls router | `{"call_id": 1}` | YES |
| `service_call_cancelled` | service_calls router | `{"call_id": 1}` | YES |

### Translation Events
| Event | Publisher | Payload | Broadcast |
|---|---|---|---|
| `translation_result` | DeskCoordinator | `{"zh": "...", "en": "...", "seat_id": 3, "segment_id": 15, "is_final": true}` | YES |

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

一个会议一个房间。同房间所有客户端接收全部广播。客户端自行过滤（如 checkin_prompt 仅目标 seat 响应）。

## 6.5 实现

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
Server 侧心跳超时：5 秒无 pong → 标记座位断开。

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

## 7.3 实现

文件：`backend/services/serial_service.py`

核心类：
- `SeatConnection` dataclass：seat_id, port, last_heartbeat, connected
- `SerialService`：管理 10 路连接，daemon 线程 2秒轮询扫描
- stub 模式：`stub=True`（默认），开发环境无硬件可运行
- 单例：`serial_svc = SerialService(stub=True)`

## 7.4 LED 状态映射

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

## 8.2 会议状态机

```text
 pending ──► active ──► finished
```

规则：
- 同一时间仅允许一个 `active` 会议
- `finished` 不可逆

## 8.3 投票状态机

```text
 open ──► closed
```

规则：
- 同一时间最多一个 `open` 投票
- `closed` 不可逆
- 一人一票（`UNIQUE(vote_id, attendee_id)`）

## 8.4 服务呼叫状态机

```text
                ┌──► resolved
 pending ───────┤
                └──► cancelled
```

规则：
- 同一 seat 同时仅允许一个 `pending` 呼叫
- `resolved` 和 `cancelled` 均为终态

---

# 9. 业务流程图

## 9.1 入座签到流程

```text
TOF 传感器检测
    ↓
SerialService._read_all() 读到 {"type":"seat_occupied","seat_id":3}
    ↓
DeskCoordinator._on_serial()
    ├── state_machine.seat_occupied(3)
    │   └── EMPTY → OCCUPIED
    ├── serial_svc.set_led(3, pattern="wave", color=BLUE)
    ├── ws_svc.broadcast({"event":"seat_occupied","payload":{"seat_id":3}})
    └── threading.Timer(3.0)
        └── ws_svc.send_to_seat(3, {"type":"checkin_prompt","payload":{"seat_id":3}})
            ↓
        Seat 3 Tablet 弹出 CheckInModal
            ↓
        POST /api/checkin  (attendee_id=8)
            ↓
        DeskCoordinator.on_checkin()
            ├── state_machine.check_in(3, 8, name)
            │   └── OCCUPIED → CHECKED_IN
            ├── serial_svc.set_led(3, pattern="solid", color=WARM_WHITE)
            └── ws_svc.broadcast({"event":"check_in","payload":{"seat_id":3,"attendee_id":8}})
```

## 9.2 发言席切换流程

```text
Admin Tablet
    ↓
POST /api/translate/speaker-seat  {"meeting_id":1, "seat_id":5}
    ↓
_speaker_seats[1] = 5
    ↓
DeskCoordinator.on_speaker_seat(1, 5)
    ├── 所有座位 LED 重置为状态默认色
    ├── serial_svc.set_led(5, pattern="solid", color=BLUE)   ← 发言席蓝色
    └── ws_svc.broadcast({"event":"speaker_seat_set","payload":{"seat_id":5}})
        ↓
    Seat 5 TranslationPanel: 开始录音
    其他 Seat TranslationPanel: 显示 listening 状态

Clear:
DELETE /api/seats/speaker
    ↓
DeskCoordinator.on_speaker_clear()
    ├── 所有座位 LED 重置
    └── ws_svc.broadcast({"event":"speaker_seat_clear"})
```

## 9.3 投票流程

```text
Admin Tablet
    ↓
POST /api/votes  {"meeting_id":1, "title":"Approve Budget", "options":["Agree","Reject","Abstain"], "is_anonymous":false}
    ↓
VoteService 创建 vote (status=open) + 持久化
    ↓
DeskCoordinator.on_vote_start()
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
DeskCoordinator.on_vote_close()
    ├── 所有座位 LED 恢复状态默认色
    └── ws_svc.broadcast({"event":"vote_closed","payload":{"vote_id":1}})
        ↓
Admin: GET /api/votes/1/statistics → 查看结果
```

## 9.4 服务呼叫流程

```text
Seat 4 Tablet
    ↓
POST /api/service-calls  {"seat_id":4, "service_type":"coffee"}
    ↓
检查：seat_id=4 是否已有 pending call? → 409 拒绝
否则：写入 service_calls (status=pending)
    ↓
ws_svc.broadcast({"event":"service_call_created","payload":{"call_id":1,"seat_id":4,"service_type":"coffee"}})
    ↓
Admin Tablet: ServicePanel 显示 "Seat 4 → Coffee [Mark Resolved]"
    ↓
Admin: POST /api/service-calls/1/resolve
    ↓
status→resolved, resolved_at=NOW
    ↓
ws_svc.broadcast({"event":"service_call_resolved","payload":{"call_id":1}})
```

## 9.5 翻译流程

```text
Speaker (Seat 3) 说话
    ↓
Seat 3 Tablet 浏览器: useAudioRecorder
    ├── VAD 检测语音活动 → 分段录音
    ├── interim (每 800ms): POST /api/translate/audio  final=false
    │   └── Paraformer Streaming → SentenceMerger 累积
    │       └── HTTP 200 {"zh": accumulated_text, "en": "", "final": false}
    └── final (VAD silence / 20s timeout): POST /api/translate/audio  final=true
        ↓
    Paraformer-large offline rescore → 完整文本
        ↓
    MTEngine.translate(text) → Opus-MT zh↔en
        ↓
    history_store.upsert(zh_text, en_text, meeting_id, seat_id, segment_id)
        ↓
    DeskCoordinator.on_translation_result()
        └── ws_svc.broadcast({"event":"translation_result","payload":{"zh":"...","en":"...","seat_id":3,"segment_id":15,"is_final":true}})
            ↓
        所有 Tablet TranslationPanel: 双语显示更新
```

---

# 10. 前端组件映射

## 10.1 路由

| 路径 | 组件 | 用途 |
|---|---|---|
| `/` | HomeView | 会议列表，创建会议 |
| `/meeting/:id?seat=N` | MeetingView | 会议详情（编排所有面板）|

seat 参数：1~10 为座位平板，无 seat 参数 = 管理台（isAdmin=true）

## 10.2 组件树

```text
App.vue
├── provide: seatId, isAdmin, appConnected
├── <router-view>
│   ├── HomeView.vue
│   │   └── BaseDialog.vue (创建会议表单)
│   └── MeetingView.vue
│       ├── 接收 WS 消息 → lastWsMsg → 传给子组件
│       ├── SeatGrid.vue
│       │   ├── CheckInModal.vue
│       │   └── 10 个座位卡片 (occupied/checkedIn/LED 视觉效果)
│       ├── TranslationPanel.vue
│       │   ├── TranscriptHistoryModal.vue (Teleport to body)
│       │   ├── useAudioRecorder.js (VAD 录音 + STT 上传)
│       │   └── 发言席管理 + 双行抄本显示
│       ├── VotingPanel.vue
│       │   ├── BaseDialog.vue (创建投票)
│       │   └── ECharts 环形图 (CDN)
│       ├── ServicePanel.vue
│       │   └── 4 服务类型按钮 + 呼叫列表
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
| `translation_result` | TranslationPanel | 双语抄本更新，按 segment_id 去重 |
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
| `useSeat.js` | seatId 决议链：route.query.seat → localStorage → 默认1 |
| `useWebSocket.js` | WS 连接：自动重连(3s)、心跳(15s ping)、onMessage 回调 |
| `useAudioRecorder.js` | VAD 录音：@ricky0123/vad-web + onnxruntime-web AudioWorklet 16kHz，每800ms interim，VAD silence 触发 final，20s 超时强制 final |

## 10.5 API 模块

文件：`frontend/src/api/index.js`

基础 URL：`/api`（Vite proxy 同源代理）。fetch 封装，自动 JSON 序列化/错误处理。

关键 API 函数：
```javascript
// Meetings
listMeetings()      createMeeting(data)     getMeeting(id)
updateMeeting(id,d) deleteMeeting(id)

// Agendas
listAgendas(mid)    addAgenda(mid, data)    removeAgenda(mid, aid)

// Attendees
listAttendees(mid)  addAttendee(mid, data)  removeAttendee(mid, aid)

// Check-in
checkin(mid, seatId)

// Votes
listVotes(mid)      createVote(mid, data)   getVote(mid, vid)
castVote(mid, vid, data)   closeVote(mid, vid)

// Service Calls
listServiceCalls(mid)       createServiceCall(mid, data)
updateCallStatus(mid, cid, data)

// Translation
translate(data)             uploadAudio(mid, seatId, blob, isFinal, utteranceId)
preloadModels()             getPreloadStatus()
setSpeakerSeat(mid, seatId) getSpeakerSeat(mid)
getTranscriptHistory(mid)
```

注意：`uploadAudio` 使用 `multipart/form-data`，其余全部 `application/json`。

---

# 11. 部署配置

## 11.1 环境要求

- OS: Windows 11 / Linux
- Python: 3.11+
- Node.js: 18+
- 硬件: NUC, USB Hub ×1, Arduino Nano ×10, 平板 ×11

## 11.2 端口分配

| 服务 | 端口 |
|---|---|
| FastAPI Backend | 8000 |
| Vite Dev Server | 5173 |
| WebSocket | 8000 (同 HTTP) |

## 11.3 启动脚本

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

## 11.4 依赖

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

## 11.5 模型缓存

STT 模型（FunASR Paraformer）和 MT 模型（Opus-MT）缓存在：
- FunASR: `~/.cache/modelscope/` 或项目 `models/` 目录
- Opus-MT: `~/.cache/huggingface/hub/` 或项目 `models/` 目录

模型加载优先级：显式 `model_dir` 参数 → 本地 HF/modelscope 缓存 → Hub 下载

## 11.6 目录结构总览

```text
smart-desk/
├── backend/
│   ├── main.py              # FastAPI app, lifespan, CORS, seed data
│   ├── database.py          # SQLAlchemy engine/session
│   ├── models.py            # ORM: Meeting, Agenda, Attendee, Vote, VoteRecord, ServiceCall
│   ├── schemas.py           # Pydantic: 请求/响应 DTO
│   ├── requirements.txt
│   ├── routers/
│   │   ├── meetings.py      # Meeting/Agenda/Attendee CRUD
│   │   ├── checkin.py       # 签到（含匿名参会者创建）
│   │   ├── votes.py         # 投票 CRUD + persist_vote_cast
│   │   ├── service_calls.py # 服务呼叫 CRUD + persist_service_call
│   │   └── translation.py   # 翻译/STT/SpeakerSeat/History
│   └── services/
│       ├── business_logic.py    # DeskStateMachine (纯状态机)
│       ├── desk_coordinator.py  # 中央编排器 (singleton: desk)
│       ├── serial_service.py    # Arduino 串口 (singleton: serial_svc)
│       └── ws_service.py        # WebSocket 房间 (singleton: ws_svc)
├── speech_module/
│   ├── __init__.py
│   ├── speech_module.py     # 对外 Facade
│   ├── stt_streaming.py     # Paraformer Streaming + Offline
│   ├── mt_engine.py         # Opus-MT zh↔en
│   ├── sentence_merge.py    # 句边界感知文本合并
│   ├── punctuation.py       # CT-Transformer 标点恢复
│   ├── fsmn_vad.py          # VAD
│   ├── audio_utils.py       # 音频加载/重采样
│   ├── text_utils.py        # 语言检测/文本相似度
│   ├── history_store.py     # SQLite 翻译历史
│   └── tests/
│       ├── test_mt_engine.py
│       └── ...
├── frontend/
│   └── src/
│       ├── main.js           # Vue 入口
│       ├── App.vue           # 根组件 + provide/inject
│       ├── style.css         # 全局样式 (暗色主题)
│       ├── api/index.js      # fetch 封装
│       ├── router/index.js   # Vue Router
│       ├── composables/      # useSeat, useWebSocket, useAudioRecorder
│       ├── views/            # HomeView, MeetingView
│       ├── components/       # SeatGrid, TranslationPanel, VotingPanel, ...
│       └── utils/status.js   # 状态格式化
├── models/                   # 模型缓存目录
├── start.bat / start.sh
├── kill.bat / kill.sh
└── speech_history.db         # 翻译历史 SQLite
```

---

# 12. Speech Module

## 12.1 模块架构

```text
speech_module/speech_module.py  (Facade)
    ├── stt_streaming.py      Paraformer Streaming (process_interim_chunk)
    │                         Paraformer-large   (transcribe / transcribe_array)
    ├── fsmn_vad.py           FSMN-VAD (语音活动检测)
    ├── punctuation.py        CT-Transformer (标点恢复)
    ├── sentence_merge.py     SentenceMerger (句边界感知文本累积)
    ├── mt_engine.py          Opus-MT zh↔en (仅 final 翻译)
    ├── audio_utils.py        音频加载 + 16kHz 重采样
    ├── text_utils.py         语言检测 (zh/en) + 文本相似度
    └── history_store.py      SQLite 翻译历史持久化
```

设计原则：**SpeechModule 必须可独立运行**，不依赖 FastAPI/WebSocket/Arduino/Vue。

## 12.2 STT 流水线

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
Paraformer-large (offline rescore，更高准确率)
    ↓
CT-Transformer 标点恢复
    ↓
MTEngine.translate(text) → (zh, en)
    ↓
history_store.upsert()
    ↓
WebSocket broadcast: {"event":"translation_result", "payload":{zh, en, seat_id, segment_id}}
```

## 12.3 MT Engine

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

性能目标：
| 指标 | 目标 |
|---|---|
| 双模型加载 | < 10s |
| 内存占用 | < 1GB |
| 单句翻译延迟 | < 500ms |
| 完整 preload (含 STT) | < 30s |

## 12.4 SentenceMerger

文件：`speech_module/sentence_merge.py`

句边界联合决策：标点结尾 (。！？.!?) + 长度 ≥ 阈值 + pending 时长 ≥ 阈值 + 新 chunk 与 pending 间隔。

目的：防止说话者句中停顿时过早切分句子。

## 12.5 HistoryStore

文件：`speech_module/history_store.py`

独立 SQLite 数据库（`speech_history.db`），管理 `translation_records` 表。

```python
class HistoryStore:
    def upsert(meeting_id, seat_id, segment_id, zh_text, en_text, is_final)
    def query_by_seat(meeting_id, seat_id, limit, offset) -> list[dict]
    def query_by_meeting(meeting_id, limit, offset) -> list[dict]
    def get_last_segment_id(meeting_id, seat_id) -> int
```

## 12.6 SpeechModule Facade

```python
class SpeechModule:
    def __init__(max_workers=4, history_store=None, mt_engine=None)
    def preload() -> None                      # 加载所有模型 + warmup
    def transcribe(audio_path) -> str          # 离线转写文件
    def transcribe_array(audio, sr) -> str     # 离线转写数组
    def translate_text(text) -> tuple[str,str] # MT 翻译（自动语言检测）
    def transcribe_and_translate(path) -> tuple[str,str]  # STT → MT 流水线
    def process_interim_chunk(path, session_key) -> str   # 流式 chunk
    def process_interim_array(audio, session_key, sr) -> str
    def reset_interim(session_key) -> None     # 重置句合并状态
    def start_utterance(session_key) -> None   # 新话语开始
    def get_interim(session_key) -> str        # 当前累积文本
    def set_session_context(session_key, meeting_id, seat_id)  # 绑定会议
    def get_history(meeting_id, seat_id, limit, offset) -> list[dict]
    def get_next_segment_id(meeting_id, seat_id) -> int
```

---

# 13. 测试策略

每个模块必须可独立测试：

| 模块 | 测试命令 |
|---|---|
| SpeechModule | `pytest speech_module/tests/` |
| SeatService | `pytest tests/test_seat_service.py` |
| VoteService | `pytest tests/test_vote_service.py` |
| WebSocket | `pytest tests/test_ws.py` |
| Hardware | `pytest tests/test_serial.py` |

现有测试：
- `speech_module/tests/test_mt_engine.py`：5 单元测试（快）+ 3 集成测试（标记 slow）

---

# 14. 版本历史

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-06-02 | Initial full spec — 5 modules integrated (Speech, Seat, Vote, Service Call, Dashboard) |

---

# Appendix A: 实际实现与文档差异 (Delta)

本文档基于实际代码库编写（非仅设计文档）。以下差异已在上文反映：

| 项目 | 初始设计文档 | 实际代码 | 本文档采用 |
|---|---|---|---|
| Repository 层 | 6 个 Repository 类 | 不存在，Router 内联 DB | 实际 |
| EventBus | 独立 EventBus 类 | 不存在，desk_coordinator 回调 | 实际 |
| events/ 目录 | 独立事件文件 | 不存在 | 实际 |
| hardware/ 目录 | 独立硬件抽象层 | 仅 serial_service.py | 实际 |
| 翻译 DB 表 | 在 backend SQLite 中 | 独立 speech_history.db (HistoryStore) | 实际 |
| ORM 模型 | 9 表统一在 models.py | 6 表在 models.py + translation_records 在 history_store.py | 实际 |

# Appendix B: 新增内容索引

以下内容在原有分拆文档中不存在，本文档新增：

1. **状态机图** (§8)：Seat(3态)、Meeting(3态)、Vote(2态)、ServiceCall(3态) 完整状态转移
2. **业务流程图** (§9)：入座签到、发言席切换、投票、服务呼叫、翻译 5 条主流程
3. **前端组件映射** (§10)：完整组件树、11 个 WS 事件处理表、Composable/API 清单
4. **部署配置** (§11)：端口分配、启动脚本、依赖清单、目录结构全览
5. **硬件串口协议** (§7)：完整的 JSON-over-USB 协议定义（boot/pong/led 消息格式）
6. **实现差异表** (Appendix A)：设计文档 vs 实际代码差异透明化
