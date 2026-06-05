# SmartDesk API Specification

Version: 1.2

Status: Frontend Integration Contract

Last Updated: 2026-06-04

---

# 1. Scope

本文档用于 React + Vite 前端与当前 FastAPI 后端集成。

快速展示版本包含：

* 会议、议程、参会者管理
* 10 个座位状态、签到、发言席
* 匿名或记名投票
* 服务呼叫
* WebSocket 实时事件同步
* 翻译历史展示

语音识别进入当前实现范围。前端座位端应在当前座位为 Speaker Seat 时接入麦克风和 `/ws/speech/{meeting_id}?seat=N`；会议核心流程仍不得依赖语音模块成功运行。

---

# 2. Base URLs

开发环境：

```text
HTTP:      http://localhost:8000
WebSocket: ws://localhost:8000
```

React + Vite 开发服务器应使用代理：

```text
/api -> http://localhost:8000
/ws  -> ws://localhost:8000
```

前端代码只使用相对路径 `/api/...`，WebSocket 地址根据当前页面协议和主机动态构造。

---

# 3. Response Format

大多数成功响应使用统一格式：

```json
{
  "success": true,
  "message": "OK",
  "data": {}
}
```

业务失败的目标格式：

```json
{
  "success": false,
  "message": "Seat already checked in",
  "data": null,
  "error_code": "SEAT_ALREADY_CHECKED_IN"
}
```

当前部分 FastAPI 路由可能返回框架错误格式：

```json
{
  "detail": "ERROR_CODE"
}
```

前端 API 客户端必须同时兼容 `message`、`error_code` 和 `detail`。

常用状态码：

| Status | Meaning |
|---|---|
| 200 | Success |
| 201 | Created |
| 400 | Validation or invalid state |
| 404 | Not found |
| 409 | Conflict |
| 422 | FastAPI request validation error |
| 500 | Internal or speech module error |

---

# 4. Shared Data Types

```ts
type MeetingStatus = "pending" | "active" | "finished"
type SeatStatus = "vacant" | "occupied_unchecked" | "checked_in"
type VoteStatus = "open" | "closed"
type ServiceCallStatus = "pending" | "resolved" | "cancelled"
type ServiceType = "coffee" | "tea" | "water" | "other"

interface ApiResponse<T> {
  success: boolean
  message: string
  data: T | null
  error_code?: string | null
}

interface Meeting {
  id: number
  title: string
  description: string | null
  status: MeetingStatus
  created_at: string
  started_at: string | null
  ended_at: string | null
}

interface Agenda {
  id: number
  meeting_id: number
  title: string
  sort_order: number
}

interface Attendee {
  id: number
  meeting_id: number
  name: string
  title: string
  seat_id: number | null
  checked_in: boolean
}

interface SeatState {
  seat_id: number
  status: SeatStatus
  attendee_id: number | null
  updated_at: string
}

interface SpeakerSeat {
  seat_id: number | null
}

interface Vote {
  id: number
  meeting_id: number
  title: string
  options: string[]
  status: VoteStatus
  is_anonymous: boolean
}

interface VoteOptionStat {
  option: string
  count: number
  attendee_ids: number[] | null
}

interface VoteStatistics {
  vote_id: number
  title: string
  is_anonymous: boolean
  status: VoteStatus
  total_votes: number
  results: VoteOptionStat[]
}

interface ServiceCall {
  id: number
  meeting_id: number
  seat_id: number
  service_type: ServiceType
  status: ServiceCallStatus
  created_at: string | null
}

interface TranslationRecord {
  id: number
  meeting_id: number
  seat_id: number
  utterance_id: string | null
  source_lang: string
  target_lang: string
  source_text: string
  translated_text: string
  source_type: "offline_rescore" | "streaming_fallback" | "manual" | string
  created_at: string
}
```

---

# 5. Frontend Initialization

`GET /api/dashboard` 当前为预留接口，不得作为前端依赖。

管理员页面初始化时，并行请求：

```http
GET /api/meetings/active
GET /api/seats
GET /api/seats/speaker
GET /api/votes/active
GET /api/service-calls?meeting_id={activeMeetingId}
GET /api/translations?meeting_id={activeMeetingId}
GET /api/meetings/{activeMeetingId}/agendas
GET /api/meetings/{activeMeetingId}/attendees
```

座位页面初始化时，并行请求：

```http
GET /api/meetings/active
GET /api/seats
GET /api/seats/speaker
GET /api/votes/active
GET /api/service-calls/current?meeting_id={activeMeetingId}&seat_id={seatId}
GET /api/translations?meeting_id={activeMeetingId}&seat_id={seatId}
GET /api/meetings/{activeMeetingId}/agendas
GET /api/meetings/{activeMeetingId}/attendees
```

没有 active meeting 时，不请求需要 `meeting_id` 的接口，并显示等待会议开始状态。

`SeatState` 只包含 `attendee_id`。前端必须通过 attendees 列表将其映射为参会者姓名。

---

# 6. Meeting APIs

| Method | Path | Request | Response Data |
|---|---|---|---|
| GET | `/api/meetings` | - | `Meeting[]` |
| POST | `/api/meetings` | `{"title":"Board Meeting","description":"Quarterly Review"}` | `Meeting` |
| GET | `/api/meetings/active` | - | `Meeting \| null` |
| GET | `/api/meetings/{meeting_id}` | - | `Meeting` |
| POST | `/api/meetings/{meeting_id}/start` | - | `Meeting` |
| POST | `/api/meetings/{meeting_id}/end` | - | `Meeting` |

规则：

* 同时只允许一个 active meeting。
* 启动会议发布 `meeting_started`。
* 结束会议发布 `meeting_ended`，并重置座位状态、关闭 open vote。

---

# 7. Agenda APIs

| Method | Path | Request | Response Data |
|---|---|---|---|
| GET | `/api/meetings/{meeting_id}/agendas` | - | `Agenda[]` |
| POST | `/api/meetings/{meeting_id}/agendas` | `{"title":"Financial Report","sort_order":1}` | `Agenda` |
| DELETE | `/api/meetings/{meeting_id}/agendas/{agenda_id}` | - | `null` |

---

# 8. Attendee APIs

| Method | Path | Request | Response Data |
|---|---|---|---|
| GET | `/api/meetings/{meeting_id}/attendees` | - | `Attendee[]` |
| POST | `/api/meetings/{meeting_id}/attendees` | `{"name":"John","title":"CEO"}` | `Attendee` |
| DELETE | `/api/meetings/{meeting_id}/attendees/{attendee_id}` | - | `null` |

签到业务主键使用 `attendee_id`。

---

# 9. Seat APIs

| Method | Path | Request | Response Data |
|---|---|---|---|
| GET | `/api/seats` | - | `SeatState[]` |
| POST | `/api/seats/{seat_id}/checkin` | `{"attendee_id":8}` | `SeatState` |
| GET | `/api/seats/speaker` | - | `SpeakerSeat` |
| POST | `/api/seats/speaker` | `{"seat_id":5}` | `SpeakerSeat` |
| DELETE | `/api/seats/speaker` | - | `SpeakerSeat` |

座位状态：

```text
vacant -> occupied_unchecked -> checked_in
```

当前仅允许一个发言席。

---

# 10. Vote APIs

| Method | Path | Request | Response Data |
|---|---|---|---|
| GET | `/api/votes/active` | - | `Vote \| null` |
| POST | `/api/votes` | `{"meeting_id":1,"title":"Approve Budget","options":["Agree","Reject","Abstain"],"is_anonymous":true}` | `Vote` |
| GET | `/api/votes/{vote_id}` | - | `Vote` |
| POST | `/api/votes/{vote_id}/submit` | `{"attendee_id":5,"option":"Agree"}` | `Vote` |
| GET | `/api/votes/{vote_id}/statistics` | - | `VoteStatistics` |
| POST | `/api/votes/{vote_id}/close` | - | `Vote` |

规则：

* 同时最多一个 open vote。
* 每个 attendee 对同一投票只有一条记录；重复提交会更新该记录。
* `vote_updated` WebSocket 事件不包含统计结果，管理员收到事件后重新请求 statistics。

---

# 11. Service Call APIs

`meeting_id` 是查询参数，不在 JSON 请求体中。

| Method | Path | Request | Response Data |
|---|---|---|---|
| GET | `/api/service-calls?meeting_id={meeting_id}` | - | `ServiceCall[]` |
| GET | `/api/service-calls/current?meeting_id={meeting_id}&seat_id={seat_id}` | - | `ServiceCall \| null` |
| POST | `/api/service-calls?meeting_id={meeting_id}` | `{"seat_id":4,"service_type":"coffee"}` | `ServiceCall` |
| POST | `/api/service-calls/{call_id}/resolve` | - | `ServiceCall` |
| POST | `/api/service-calls/{call_id}/cancel` | - | `ServiceCall` |

规则：

* 同一座位同时只允许一个 pending service call。
* `resolved` 和 `cancelled` 为终态。

---

# 12. Translation and Speech APIs

Speech recognition is governed by `docs/adr/0001` through `docs/adr/0004` and
`docs/adr/SPEECH_SYSTEM_OVERVIEW.md`. The first speech-enabled version must use
real FunASR ASR/VAD. Runtime mock fallback is not part of the contract.
Translation may remain a placeholder while ASR integration is completed.

`speech_module/` is legacy reference code and must not be modified by SmartDesk
implementation tasks. Runtime integration should use `backend/speech_module/`
or new backend service/websocket modules only when the task explicitly allows
that scope.

Speech uses two WebSocket channels:

| Channel | Direction | Purpose |
|---|---|---|
| `/ws/{meeting_id}?seat=N` | server to clients | Meeting broadcast events, including speech transcript events |
| `/ws/speech/{meeting_id}?seat=N` | current Speaker Seat to server | Live PCM16 audio upload and speech control messages |

Live interim captions are broadcast as `translation_interim` events on the
meeting broadcast channel. Final captions are persisted to `translation_records`
and broadcast as `translation_final`.

## Compatible Final Audio Upload

`POST /api/translations` is retained only as a compatibility path for complete
audio files or developer diagnostics. It must not be used for live interim
captions. It accepts `audio`, `meeting_id`, and `seat_id` form fields and
returns `TranslationRecord`. `utterance_id` may be `null` for compatibility
uploads because no speech WebSocket utterance exists.

## Live Speech WebSocket

```text
WS /ws/speech/{meeting_id}?seat={seat_id}
```

Only the current Speaker Seat may connect and upload audio. The frontend sends
JSON control messages and PCM16 little-endian binary frames. The backend owns
utterance IDs, VAD, final sentence boundaries, offline rescore, persistence, and
speech WebSocket errors.

Client control messages:

```json
{"type":"start","sample_rate":16000,"encoding":"pcm_s16le","channels":1}
{"type":"end_hint"}
{"type":"cancel"}
```

Server control messages on `/ws/speech/...`:

```json
{"type":"started","utterance_id":"utt_1_3_000042","session_key":"speech_1_3"}
{"type":"utterance_started","utterance_id":"utt_1_3_000043"}
{"type":"error","code":"NOT_SPEAKER_SEAT","message":"Only the speaker seat may stream audio"}
```

Audio frames:

```text
encoding:    pcm_s16le
sample_rate: 16000
channels:    1
frame_ms:    100 recommended
```

语音模块在当前版本必须接入真实 ASR。前端不得自动访问麦克风；只有用户在 Speaker Seat 页面主动开始发言时才请求麦克风权限。

## Process Audio

```http
POST /api/translations
Content-Type: multipart/form-data
```

FormData：

```text
audio       required, WAV file
meeting_id  required, integer
seat_id     required, integer
session_key deprecated, ignored for live speech
```

Deprecated HTTP interim response shape, retained only for historical context:

```json
{
  "text": "interim transcript"
}
```

Final upload response data: `TranslationRecord`

## Get Translation History

```http
GET /api/translations?meeting_id={meeting_id}&seat_id={optionalSeatId}
```

响应 data：

```json
{
  "meeting_id": 1,
  "entries": []
}
```

---

# 13. Reserved API

```http
GET /api/dashboard
```

该路径为预留设计，当前后端不可用。前端不得调用。

---

# 14. Common Error Codes

```text
MEETING_NOT_FOUND
ACTIVE_MEETING_EXISTS
MEETING_ALREADY_FINISHED
ATTENDEE_NOT_FOUND
SEAT_NOT_FOUND
SEAT_OCCUPIED
SEAT_NOT_OCCUPIED
SEAT_ALREADY_CHECKED_IN
INVALID_SEAT_STATE
SPEAKER_SEAT_NOT_FOUND
VOTE_NOT_FOUND
VOTE_CLOSED
DUPLICATE_VOTE
INVALID_VOTE_OPTION
SERVICE_CALL_NOT_FOUND
SERVICE_CALL_ALREADY_RESOLVED
TRANSLATION_FAILED
SPEECH_MODULE_ERROR
NOT_SPEAKER_SEAT
SPEECH_WS_NOT_STARTED
INVALID_AUDIO_FORMAT
SPEECH_MODEL_NOT_READY
INTERNAL_ERROR
ATTENDEE_NOT_IN_ACTIVE_MEETING
ATTENDEE_ALREADY_CHECKED_IN
SEAT_ALREADY_BOUND
MEETING_NOT_ACTIVE
```

---

# 15. Development-Only Endpoints

The following endpoints exist solely for quick-showcase and development workflows.
They are **not** part of the production API contract. No frontend code should
depend on them.

| Method | Path | Description |
|---|---|---|
| POST | `/api/dev/seats/{seat_id}/occupy` | Transition seat to `occupied_unchecked` |
| POST | `/api/dev/seats/{seat_id}/vacate` | Transition seat to `vacant` |

Both return `ApiResponse<SeatState>`.

**Environment variable control:**

| Variable | Default | Description |
|---|---|---|
| `ENABLE_DEMO_SEAT_API` | `false` | When `true`, enables the dev seat API endpoints |
| `ENABLE_DEMO_SEED` | `false` | When `true`, auto-creates demo meeting data on startup |

**Demo seed** creates a meeting with:

- 1 active meeting
- 5 agenda items
- 8 attendees (4 checked in to seats 1-4, 4 unbound)
- 10 seat states: 4 checked_in, 2 occupied_unchecked, 4 vacant
- Speaker seat reserved (seat 1)
- 1 open vote
- 1 pending service call
- 2 translation records

Demo seed only runs when:
1. `ENABLE_DEMO_SEED=true` is set, **and**
2. No meetings exist yet in the database (idempotent)

---

# 16. Frontend Rules

* Normal meeting, seat, vote, and service-call mutations continue to use HTTP
  APIs.
* The only client-to-server WebSocket data path in this contract is live speech
  audio on `/ws/speech/{meeting_id}?seat=N`.
* Meeting broadcast WebSocket events indicate that data changed. For ordinary
  business events, clients re-fetch the related HTTP resource.
* `translation_interim` is an exception: clients update the local interim
  transcript map directly and do not perform a full HTTP refresh for each
  interim revision.
* `translation_final` removes the matching interim entry by `utterance_id` and
  may either insert the final record locally or refresh translation history.
* WebSocket disconnect should show a connection warning and disable unsafe
  writes. Speech capture must stop when `/ws/speech` disconnects.
* The frontend must not decide final speech boundaries; backend VAD owns final
  utterance decisions.
* Do not call interfaces that are not listed in this document.
