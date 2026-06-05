# SmartDesk System Architecture

Version: 2.1
Status: Architecture Baseline (Target)
Last Updated: 2026-06-04

---

# 0. Speech ADR Override

For speech recognition and transcript behavior, `docs/adr/0001` through
`docs/adr/0004` and `docs/adr/SPEECH_SYSTEM_OVERVIEW.md` override older
placeholder notes in this document.

Current speech-enabled architecture:

* `/ws/{meeting_id}?seat=N` is the meeting broadcast channel.
* `/ws/speech/{meeting_id}?seat=N` is the Speaker Seat audio uplink channel.
* Live audio uses PCM16 little-endian, 16 kHz, mono binary WebSocket frames.
* The backend owns VAD, utterance IDs, final boundaries, offline ASR rescore,
  persistence, and transcript events.
* The runtime contract requires real FunASR ASR/VAD. Mock speech fallback is
  not part of the implementation contract.
* Translation may remain a placeholder while ASR is integrated.
* `speech_module/` is legacy reference code and must not be modified by
  SmartDesk implementation tasks.

---

# 1. Project Overview

SmartDesk 是一个面向会议场景的智能会议桌系统。

系统由：

* 10 个智能座位（Arduino Nano + TOF + LED）
* 11 个平板终端（10 座位 + 1 管理台）
* NUC 中央服务器
* Speech Module（ASR + MT + Dual VAD）

组成。

核心能力：

* 自动入座检测（TOF 传感器）
* 签到管理（vacant -> occupied_unchecked -> checked_in）
* 发言席管理（单一 Speaker Seat，DB 持久化）
* 实时语音识别（Paraformer Streaming + Offline）
* 实时双语翻译（Helsinki-NLP Opus-MT zh<->en）
* 匿名/记名投票
* 服务呼叫（5 分钟超时自动取消）
* WebSocket 实时广播同步
* EventBus 事件驱动解耦

---

# 2. Architecture Principles

## P1. 单一职责

每个模块只负责一类业务。

禁止：

* 一个模块同时负责业务和通信
* 一个模块同时负责数据库和 WebSocket

---

## P2. Service First

所有业务逻辑必须位于 Service 层。

禁止：

Router 直接操作数据库。

错误：

```python
@router.post(...)
db.add(...)
```

正确：

```python
@router.post(...)
meeting_service.create(...)
```

---

## P3. Repository Isolation

数据库只能通过 Repository 访问。

禁止：

```python
session.query(...)
```

散落在各个 Service 中。

---

## P4. Event Driven

模块之间通过 EventBus 通信。V1 采用进程内 dict-dispatch 模式。

禁止：

```python
seat_service
    |
    v  直接调用
ws_service
```

正确：

```text
seat_service
    |
    v  SeatOccupiedEvent
EventBus
    |
    v
WebSocketEventHandler
    |
    v
WebSocketService.broadcast()
```

EventBus 接口：

```python
class EventBus:
    def publish(self, event: BaseEvent) -> None: ...
    def subscribe(self, event_name: str, handler) -> None: ...
```

BaseEvent 格式：

```python
class BaseEvent:
    event_name: str
    meeting_id: int | None
    timestamp: datetime
    payload: dict
```

事件必须由 Service 发布。Router、Repository、WebSocket 禁止发布事件。

事件默认不持久化，仅用于模块通知和 WebSocket 广播。

---

## P5. Speech Module Independence

SpeechModule 必须保持独立。

允许：

```python
speech.process_final(...)
```

禁止：

SpeechModule 导入：

* FastAPI
* WebSocket
* Arduino
* React

---

# 3. System Architecture

```text
                    +----------------+
                    |   Frontend     |
                    | React + Vite   |
                    | TypeScript     |
                    | Client VAD (*) |
                    +-------+--------+
                            |
                  HTTP      |      WebSocket
                            |
+---------------------------v-------------------------+
|                    FastAPI                          |
|                                                     |
|  routers/         (参数校验，调用 Service)           |
|                                                     |
|  Router --> Service --> Repository --> SQLite        |
|               |                                     |
|               |  EventBus.publish()                 |
|               v                                     |
|          EventBus                                   |
|          (in-process, dict-dispatch)                |
|               |                                     |
|               v                                     |
|     WebSocketEventHandler                           |
|               |                                     |
|               v                                     |
|     WebSocketService.broadcast()                    |
|                                                     |
|  Service Layer (6 services):                        |
|    MeetingService     SeatService                   |
|    VoteService        ServiceCallService            |
|    TranslationService WebSocketService              |
|                                                     |
|  SeatStateMachine (pure state machine, zero I/O)    |
|                                                     |
|  Repository Layer (6 repositories):                 |
|    MeetingRepository    AttendeeRepository          |
|    SeatRepository       VoteRepository              |
|    ServiceCallRepository  TranslationRepository     |
+------------+-------------------------------+--------+
             |                               |
             v                               v

      SpeechModule                    Hardware Layer
      (ASR + MT + FSMN-VAD)      Arduino Nano x10
      Server VAD (FSMN-VAD)      (TOF + LED)
```

Key architectural notes:

* EventBus: in-process dict-dispatch, V1 only. No Kafka/RabbitMQ/Redis.
* SeatStateMachine: formerly `business_logic.py`. Pure state machine with zero I/O dependencies.
* Frontend: React + Vite + TypeScript. The frontend only consumes HTTP API and WebSocket contracts.
* Dual VAD: Client-side VAD is optional for the demo build; Server-side FSMN-VAD remains the final quality gate.
* WebSocketEventHandler: bridges EventBus events to WebSocket broadcast. Fixed registration at startup.

---

# 4. Module Responsibilities

## 4.1 Router Layer

目录：

```text
backend/api/
```

职责：

* 参数校验
* 调用 Service
* 返回响应

禁止：

* 数据库操作
* WebSocket 操作
* 业务逻辑
* 发布事件

路由文件：

```text
meetings.py       -- /api/meetings, /api/meetings/{id}/agendas, /api/meetings/{id}/attendees
seats.py          -- /api/seats, /api/seats/{id}/checkin, /api/seats/speaker
votes.py          -- /api/votes
service_calls.py  -- /api/service-calls
translations.py   -- /api/translations
dashboard.py      -- /api/dashboard (reserved, not implemented in current demo backend)
```

---

## 4.2 Service Layer

目录：

```text
backend/services/
```

职责：

实现全部业务逻辑。发布事件通过 EventBus。

### 4.2.1 Service Classes

| Service | 职责 |
|---|---|
| MeetingService | 创建/结束会议、议程管理、参会者管理。meeting_started 触发模型预加载。meeting_ended 重置 seats 保留历史。 |
| SeatService | 入座/离座、签到、发言席管理。发布 seat_occupied, seat_vacant, checkin_prompt, check_in, speaker_seat_set, speaker_seat_clear。 |
| VoteService | 发起投票、投票记录、关闭投票。无 quorum 要求。会议结束时自动关闭所有 open 投票。 |
| ServiceCallService | 服务呼叫创建/解决/取消。5 分钟超时自动取消（可配置）。 |
| TranslationService | 调用 SpeechModule、翻译结果持久化、发布 translation_final。 |
| WebSocketService | 房间管理、客户端连接管理、广播消息。通过 WebSocketEventHandler 订阅 EventBus 事件。 |

### 4.2.2 SeatStateMachine

位置：

```text
backend/services/seat_state_machine.py
```

原名：`business_logic.py`

职责：

* 纯状态机，零 I/O 依赖
* 管理 seat 状态转移：vacant -> occupied_unchecked -> checked_in
* 验证状态转移合法性
* 不访问数据库，不发布事件，不操作 WebSocket

接口：

```python
class SeatStateMachine:
    def seat_occupied(self, seat_id: int) -> None
    def seat_vacant(self, seat_id: int) -> None
    def check_in(self, seat_id: int, attendee_id: int) -> None
    def get_status(self, seat_id: int) -> str
    def reset_all(self) -> None
```

---

## 4.3 Repository Layer

目录：

```text
backend/repositories/
```

职责：

唯一数据库访问入口。

| Repository | 对应模型 |
|---|---|
| MeetingRepository | meetings, agendas, attendees |
| AttendeeRepository | attendees |
| SeatRepository | seat_states, speaker_seat |
| VoteRepository | votes, vote_records |
| ServiceCallRepository | service_calls |
| TranslationRepository | translation_records |

禁止：

业务逻辑。

---

## 4.4 EventBus

目录：

```text
backend/events/
```

职责：

模块解耦。统一事件发布中心。

实现：V1 进程内 dict-dispatch。无外部消息队列依赖。

事件注册在应用启动时完成（固定注册），禁止运行时动态注册。

### Event List (Standardized)

#### Seat Events

| Event | Publisher | Payload |
|---|---|---|
| seat_occupied | SeatService | {"seat_id": N} |
| seat_vacant | SeatService | {"seat_id": N} |
| checkin_prompt | SeatService | {"seat_id": N} |
| check_in | SeatService | {"seat_id": N, "attendee_id": N} |
| speaker_seat_set | SeatService | {"seat_id": N} |
| speaker_seat_clear | SeatService | {} |

#### Meeting Events

| Event | Publisher | Payload |
|---|---|---|
| meeting_started | MeetingService | {"meeting_id": N} |
| meeting_ended | MeetingService | {"meeting_id": N} |

#### Vote Events

| Event | Publisher | Payload |
|---|---|---|
| vote_started | VoteService | {"vote_id": N, "title": "..."} |
| vote_updated | VoteService | {"vote_id": N} |
| vote_closed | VoteService | {"vote_id": N} |

#### Service Call Events

| Event | Publisher | Payload |
|---|---|---|
| service_call_created | ServiceCallService | {"call_id": N, "seat_id": N, "service_type": "..."} |
| service_call_resolved | ServiceCallService | {"call_id": N} |
| service_call_cancelled | ServiceCallService | {"call_id": N} |

#### Translation Events

| Event | Publisher | Payload |
|---|---|---|
| translation_interim | SpeechStreamService | {"utterance_id": "...", "seat_id": N, "revision": N, "source_lang": "...", "target_lang": "...", "source_text": "...", "translated_text": "", "is_final": false} |
| translation_final | TranslationService | {"utterance_id": "...", "translation_id": N, "seat_id": N, "source_lang": "...", "target_lang": "...", "source_text": "...", "translated_text": "...", "source_type": "..."} |
| translation_interim_cancelled | SpeechStreamService | {"utterance_id": "...", "seat_id": N, "reason": "speaker_seat_changed"} |

Interim transcript events enter EventBus/WebSocket for real-time UI display but
are not persisted. Final transcript events are persisted and broadcast.

### Event Flow

```text
Service
    |
    v  EventBus.publish(BaseEvent)
EventBus
    |
    v  dispatch by event_name
WebSocketEventHandler
    |
    v  format + route to room
WebSocketService.broadcast()
    |
    v
All connected clients (room = meeting_id)
```

---

## 4.5 WebSocket Layer

目录：

```text
backend/websocket/
```

职责：

* 房间管理（按 meeting_id 分组）
* 客户端连接管理
* 广播消息
* 断线处理：前端 overlay + 阻止写入 + 自动重连 + 重连后全量状态同步 [V1]

禁止：

业务逻辑。

端点：

```text
ws://host:8000/ws/{meeting_id}?seat=N
```

The meeting channel `/ws/{meeting_id}?seat=N` supports server-to-client
broadcast. The speech channel `/ws/speech/{meeting_id}?seat=N` supports
client-to-server PCM16 audio upload from the current Speaker Seat only. Other
business writes continue to use HTTP APIs.

---

## 4.6 Hardware Layer

目录：

```text
backend/hardware/
```

职责：

* 串口管理（pyserial, 115200 baud, JSON-over-USB）
* Arduino 通信（10 路连接）
* LED 控制（off / breathe / wave / solid, 亮度上限 80）

关键设计决策 [V1]：

* Arduino 断开：seat_states 保持不变。物理层 != 业务层。
* 会议结束后硬件操作：记录物理状态，不改变业务状态。

禁止：

数据库操作。

禁止：

WebSocket 操作。

---

## 4.7 Speech Module

目录：

```text
speech_module/
```

职责：

* VAD（FSMN-VAD 服务端）
* Streaming ASR（Paraformer Streaming）
* Offline ASR（Paraformer-large rescore）
* Translation（Opus-MT zh<->en）
* History（独立 SQLite, translation_records）

必须可以独立运行：

```bash
python tests/test_dataset.py
```

不依赖：

* FastAPI
* WebSocket
* Arduino

对外 Facade 接口：

```python
class SpeechModule:
    def preload() -> None                       # 加载所有模型 + warmup [V1]
    def transcribe(audio_path) -> str           # 离线转写文件
    def transcribe_array(audio, sr) -> str      # 离线转写数组
    def translate_text(text) -> tuple[str,str]  # MT 翻译（自动语言检测）
    def transcribe_and_translate(path) -> tuple[str,str]
    def process_interim_chunk(path, session_key) -> str
    def process_interim_array(audio, session_key, sr) -> str
    def reset_interim(session_key) -> None
    def start_utterance(session_key) -> None
    def get_interim(session_key) -> str
    def set_session_context(session_key, meeting_id, seat_id) -> None
    def get_history(meeting_id, seat_id, limit, offset) -> list[dict]
    def get_next_segment_id(meeting_id, seat_id) -> int
```

### 4.7.1 Dual VAD Design

Speech recognition is now in scope. The frontend captures microphone audio only
after explicit user action on the current Speaker Seat. The frontend may perform
lightweight energy checks for UI state, but it does not decide final utterance
boundaries. Server-side VAD owns final speech boundary decisions.

```
+-------------------------------------------+
|           Client VAD (vad-web)            |
|                                           |
|  Library: @ricky0123/vad-web              |
|  Runtime: onnxruntime-web + AudioWorklet  |
|                                           |
|  Responsibilities:                        |
|    - 前端实时分段                          |
|    - 降低上传频率                          |
|    - 提升实时性                            |
|                                           |
|  NOT: 最终语音判定依据                     |
+-------------------------------------------+
                    |
                    v  audio segments
+-------------------------------------------+
|          Server VAD (FSMN-VAD)            |
|                                           |
|  Library: FunASR FSMN-VAD                 |
|  Runtime: Python (server-side)            |
|                                           |
|  Responsibilities:                        |
|    - 服务端统一校验                        |
|    - 过滤误触发音频                        |
|    - 保证 ASR 输入质量                     |
|                                           |
|  HAS: 最终语音判定决定权                   |
+-------------------------------------------+

前端 VAD 结果不作为最终语音判定依据。
后端 FSMN-VAD 拥有最终决定权。
```

### 4.7.2 Audio Format

```
Transport: WebSocket binary frames on /ws/speech/{meeting_id}?seat=N
Encoding: PCM16 little-endian
Sample Rate: 16000 Hz
Channels: Mono
Recommended Frame Size: 100 ms
Final Source: backend buffered utterance PCM with offline ASR rescore
```

---

# 5. Data Flow

## 5.1 Seat Check-in

```text
TOF Sensor
    |
    v
HardwareService
    |
    v
SeatService  (updates seat_states via SeatRepository)
    |
    +--->  EventBus.publish(seat_occupied)
    |         |
    |         v
    |      WebSocketEventHandler --> WebSocketService.broadcast()
    |
    +--->  EventBus.publish(checkin_prompt)  [after 3s delay]
              |
              v
           WebSocketEventHandler --> WebSocketService.broadcast()
              |
              v
           Seat Tablet: CheckInModal popup
              |
              v
           POST /api/seats/{id}/checkin  {"attendee_id": N}
              |
              v
           SeatService.check_in()
              |
              v
           EventBus.publish(check_in)
              |
              v
           WebSocketEventHandler --> WebSocketService.broadcast()
```

Note: seat_occupied = 物理状态变化事件, checkin_prompt = 业务提示事件。二者必须分离。

---

## 5.2 Speech and Translation Flow

```text
Speaker Seat Browser Microphone
    |
    v
AudioContext / resample / PCM16 encode
    |
    v
/ws/speech/{meeting_id}?seat=N
    |
    +---> start control message
    |        |
    |        v
    |     backend generates utterance_id
    |
    +---> PCM16 binary frames
             |
             v
          SpeechStreamService
             |
             +---> streaming ASR -> EventBus.publish(translation_interim)
             |                         |
             |                         v
             |                      /ws/{meeting_id} broadcast
             |
             +---> backend VAD detects final boundary
                       |
                       v
                    buffered utterance PCM
                       |
                       v
                    TranslationService.process_final_array()
                       |
                       v
                    Paraformer-large offline ASR rescore
                       |
                       v
                    TranslationRepository.create()
                       |
                       v
                    EventBus.publish(translation_final)
                       |
                       v
                    /ws/{meeting_id} broadcast
```

`POST /api/translations` remains only as a compatibility path for complete
audio-file final processing or diagnostics. It is not the live interim channel.

---

## 5.3 Vote Flow

```text
Admin Tablet
    |
    v
POST /api/votes  {"meeting_id": N, "title": "...", "options": [...], "is_anonymous": bool}
    |
    v
VoteService.create() -> VoteRepository
    |
    v
EventBus.publish(vote_started)
    |
    v
WebSocketEventHandler -> WebSocketService.broadcast()
    |
    v
All Seat Tablets: VotingPanel active

Seat Tablet votes:
    POST /api/votes/{id}/submit  {"attendee_id": N, "option": "..."}
    |
    v
VoteService.submit() -> VoteRepository  (UNIQUE(vote_id, attendee_id) constraint)
    |
    v
EventBus.publish(vote_updated)   [no statistics in payload]
    |
    v
WebSocketEventHandler -> WebSocketService.broadcast()

Admin closes:
    POST /api/votes/{id}/close
    |
    v
VoteService.close() -> VoteRepository
    |
    v
EventBus.publish(vote_closed)
    |
    v
WebSocketEventHandler -> WebSocketService.broadcast()
```

Vote design decisions [V1]:

* 无 quorum 要求。任何投票数均有效。
* 一人一票（UNIQUE 约束防重复）。
* 座位空出后投票记录保留。
* 会议结束时自动关闭所有 open 投票。

---

## 5.4 Service Call Flow

```text
Seat Tablet
    |
    v
POST /api/service-calls?meeting_id=N  {"seat_id": N, "service_type": "coffee|tea|water|other"}
    |
    v
ServiceCallService.create()
    |
    +--->  检查：该 seat 是否已有 pending call -> 409 Conflict
    +--->  Repository 写入 (status=pending)
    +--->  启动 5-min timeout timer
    |
    v
EventBus.publish(service_call_created)
    |
    v
WebSocketEventHandler -> WebSocketService.broadcast()
    |
    v
Admin Tablet: ServicePanel notification

Admin resolves:
    POST /api/service-calls/{id}/resolve
    |
    v
ServiceCallService.resolve() -> Repository (status=resolved, resolved_at=NOW)
    |
    v
EventBus.publish(service_call_resolved)
    |
    v
WebSocketEventHandler -> WebSocketService.broadcast()

Auto-cancel (timeout) OR manual cancel:
    POST /api/service-calls/{id}/cancel
    |
    v
ServiceCallService.cancel() -> Repository (status=cancelled)
    |
    v
EventBus.publish(service_call_cancelled)
    |
    v
WebSocketEventHandler -> WebSocketService.broadcast()
```

Service call design decisions [V1]:

* 5 分钟超时自动取消（可配置）。
* 同一 seat 同时仅允许一个 pending 呼叫。
* resolved 和 cancelled 均为终态，不可逆。

---

## 5.5 Meeting Lifecycle Flow

```text
Admin: POST /api/meetings  {"title": "...", "description": "..."}
    -> 201 Created (status=pending)

Admin: POST /api/meetings/{id}/start
    -> MeetingService.start()
        |
        +-> 检查：无其他 active 会议
        +-> status = active, started_at = NOW
        +-> 触发 SpeechModule.preload() [V1]
        |     |
        |     +-> 成功: speech_ready = true
        |     +-> 失败: meeting 继续进行，speech 功能不可用 [V1]
        +-> EventBus.publish(meeting_started)

Admin: POST /api/meetings/{id}/end
    -> MeetingService.end()
        |
        +-> status = finished, ended_at = NOW
        +-> 重置所有 seat_states 为 vacant [V1]
        +-> 保留所有历史记录（meetings, attendees, votes, translations）[V1]
        +-> 自动关闭所有 open 投票
        +-> 停止硬件控制（不改变物理状态）[V1]
        +-> EventBus.publish(meeting_ended)
```

---

# 6. Dependency Rules

允许：

```text
Router -> Service -> Repository -> SQLite
```

允许：

```text
Service -> EventBus.publish()
```

允许：

```text
WebSocketEventHandler -> WebSocketService.broadcast()
```

允许：

```text
TranslationService -> SpeechModule
```

---

禁止：

```text
Router -> Repository    (跨层)
```

---

禁止：

```text
Repository -> Service   (反向依赖)
```

---

禁止：

```text
SpeechModule -> FastAPI
SpeechModule -> WebSocket
SpeechModule -> Arduino
```

---

禁止：

```text
Hardware -> Database
Hardware -> WebSocket
Hardware -> EventBus   (不发布业务事件)
```

---

禁止：

```text
Router -> EventBus.publish()   (事件只能由 Service 发布)
Repository -> EventBus.publish()
```

---

禁止：

```text
SeatStateMachine -> Database
SeatStateMachine -> EventBus
SeatStateMachine -> WebSocket
```

SeatStateMachine 为纯状态机，零 I/O。

---

# 7. Public Interfaces

## 7.1 HTTP API (Standardized Paths)

```
/api/meetings              GET    List meetings
/api/meetings              POST   Create meeting
/api/meetings/{id}         GET    Get meeting
/api/meetings/active       GET    Get active meeting
/api/meetings/{id}/start   POST   Start meeting
/api/meetings/{id}/end     POST   End meeting
/api/meetings/{id}/agendas  GET/POST  Agendas CRUD
/api/meetings/{id}/attendees GET/POST Attendees CRUD

/api/seats                 GET    List all seats
/api/seats/{id}/checkin    POST   Check in to seat
/api/seats/speaker         GET    Get speaker seat
/api/seats/speaker         POST   Set speaker seat
/api/seats/speaker         DELETE Clear speaker seat

/api/votes                 POST   Create vote
/api/votes/active          GET    Get active vote
/api/votes/{id}            GET    Get vote detail
/api/votes/{id}/submit     POST   Submit vote
/api/votes/{id}/statistics GET    Get vote statistics
/api/votes/{id}/close      POST   Close vote

/api/service-calls         POST   Create service call (?meeting_id=N)
/api/service-calls         GET    List service calls (?meeting_id=N)
/api/service-calls/current GET    Get current seat call (?meeting_id=N&seat_id=N)
/api/service-calls/{id}/resolve  POST   Resolve call
/api/service-calls/{id}/cancel   POST   Cancel call

/api/translations                POST   Compatible final audio upload (not live interim)
/api/translations                GET    Translation history (?meeting_id=N&seat_id=N)
/ws/speech/{meeting_id}?seat=N   WS     Speaker Seat live PCM16 speech uplink

/api/dashboard             GET    Reserved, not implemented in current demo backend
```

前端初始化时不得依赖 `/api/dashboard`。管理员页面应并行请求 active meeting、seats、speaker seat、active vote 和 service calls。

统一响应格式：

成功：

```json
{"success": true, "message": "OK", "data": {}}
```

失败：

```json
{"success": false, "message": "...", "data": null, "error_code": "..."}
```

---

## 7.2 WebSocket

端点：

```text
ws://host:8000/ws/{meeting_id}?seat=N
```

连接：

```json
{"event": "connected", "meeting_id": 1, "timestamp": 1748700000, "payload": {}}
```

断开：

* 前端 overlay + 阻止写入操作 [V1]
* 自动重连（3s 间隔）[V1]
* 重连后全量状态同步 [V1]
* 服务端从房间移除，不发送业务事件

消息格式：

```json
{
  "event": "event_name",
  "meeting_id": 1,
  "timestamp": 1748700000,
  "payload": {}
}
```

WebSocket 事件与 EventBus 事件一一对应。

---

## 7.3 SpeechModule

```python
preload()                                    # 加载所有模型 + warmup
process_interim(audio, session_key)          # Streaming ASR
process_final(audio, session_key)            # Offline ASR + Translate + Persist
reset_interim(session_key)                   # Reset sentence merge state
get_history(meeting_id, seat_id=None)        # Query translation history
```

---

# 8. Testing Strategy

每个模块必须能够独立测试。

SpeechModule：

```bash
pytest speech_module/tests/
```

VoteService：

```bash
pytest tests/test_vote_service.py
```

SeatService (含 SeatStateMachine)：

```bash
pytest tests/test_seat_service.py
```

WebSocket：

```bash
pytest tests/test_ws.py
```

Hardware：

```bash
pytest tests/test_serial.py
```

Repository：

```bash
pytest tests/test_repositories.py
```

EventBus：

```bash
pytest tests/test_event_bus.py
```

---

# 9. Claude Code Development Rules

Claude Code 每次修改范围不得超过一个模块。

推荐：

```text
仅修改：

speech_module/sentence_merge.py

目标：

解决重复句问题

禁止修改其他文件
```

---

禁止：

```text
修复整个项目
```

---

新增功能必须遵守：

```text
新增 Service -> 新增 Event -> 新增 API
```

流程。

禁止跨层直接修改。

---

# 10. Versioning

## V1 Scope

**包含：**

* 10 座位
* 单会议实时运行
* 中文<->英文翻译（Opus-MT）
* 匿名/记名投票（无 quorum）
* 服务呼叫（5-min 超时）
* 翻译历史（180 天留存）
* EventBus（进程内 dict-dispatch）
* 语音识别接口占位；Dual VAD 和 ASR 允许在展示版本后实现
* Router -> Service -> Repository -> SQLite 分层架构

**不包含：**

* TTS
* 会议录音回放
* 多会议并发
* 多发言人同时识别
* 云端部署
* 用户认证
* Kafka/RabbitMQ/Redis 消息队列

---

## V1 Key Design Decisions

| # | Decision | Detail |
|---|---|---|
| 1 | Seat states | vacant -> occupied_unchecked -> checked_in |
| 2 | Speaker seat | 单行 DB 持久化。会议结束后仍保留。重启后恢复。仅 Admin 手动清除。 [V1] |
| 3 | Single speaker | 同一时间仅允许一个 Speaker Seat |
| 4 | Vote | 一人一票（UNIQUE constraint）。无 quorum。座位空出后投票保留。会议结束自动关闭。 |
| 5 | Service call | 状态机：pending -> resolved/cancelled。5-min 超时自动取消（可配置）。 |
| 6 | Translation records | 表：translation_records。字段：id, meeting_id, seat_id, source_lang, target_lang, source_text, translated_text, created_at。只允许新增，禁止修改。180 天留存，每日清理。 [V1] |
| 7 | Business key | 全体使用 attendee_id 作为业务主键 |
| 8 | Auth | V1 无认证。LAN 可信网络模型。isAdmin = URL 无 ?seat= 参数（UI 模式，非认证）。 [V1] |
| 9 | Multi-Admin | 允许多个管理台同时操作。后端拥有全部状态。 [V1] |
| 10 | Attendee-seat binding | 1-to-1 绑定。重复绑定返回 409。 [V1] |
| 11 | Seat re-occupancy | 新入座者自动绑定到前一个 occupier 的 attendee。 [V1] |
| 12 | Delete attendee | 有参会历史记录（投票、翻译、签到）的 attendee 拒绝删除。 [V1] |
| 13 | Arduino disconnect | seat_states 保持不变。物理层 != 业务层。 [V1] |
| 14 | Post-meeting hardware | 记录物理状态，不改变业务状态。 [V1] |
| 15 | Meeting cleanup | 重置 seats 为 vacant，保留所有历史记录。 [V1] |
| 16 | Speech models | Speech-enabled builds require real FunASR ASR/VAD. Missing models must be reported as environment errors; no runtime mock fallback. |
| 17 | DB init | 应用启动时自动创建表 + 种子数据（seat_states 1~10, speaker_seat id=1）。幂等。dev 和 prod 均自动执行。 [V1] |
| 18 | Audio format | Speech WS uses PCM16 little-endian, 16000Hz, mono, recommended 100ms frames. Compatibility upload accepts complete audio files. |
| 19 | WS disconnect | 前端 overlay + 阻止写入 + 自动重连(3s) + 重连后全量状态同步 [V1] |
| 20 | Deployment | Dev: Vite proxy /api -> localhost:8000。Prod: Nginx same-origin，无 CORS。Logging: logs/ 目录，每日轮转。 [V1] |
| 21 | API paths | Live speech uses /ws/speech/{meeting_id}?seat=N. Final upload/history use /api/translations. Speaker seat uses /api/seats/speaker. |
| 22 | Event names | translation_final（非 translation_result），vote_updated（非 vote_cast），service_call_created/resolved/cancelled [V1] |

---

## Architecture Freeze

除重大问题外，不允许修改本文件定义的模块边界。
