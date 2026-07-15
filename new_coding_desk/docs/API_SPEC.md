# SmartDesk API Specification

This document is the current HTTP API contract for the SmartDesk v1 demo.
Realtime speech does not use HTTP chunks; it uses the speech WebSocket defined
in `WEBSOCKET_PROTOCOL.md`.

## Common Rules

- Base URL: `http://127.0.0.1:8000`
- All JSON HTTP responses use:

```json
{
  "success": true,
  "message": "OK",
  "data": {},
  "error_code": null
}
```

- Errors use `success=false`, `data=null`, and a stable `error_code`.
- Exception (1): `GET /api/host-display/status` currently returns its stable
  status object directly, without the common response envelope. The local
  Display Agent also returns raw Agent objects. See
  `HOST_DISPLAY_CONTRACT.md` before changing either response shape.
- Exception (2): the **votes** and **service-calls** modules raise FastAPI
  `HTTPException` on errors, so their error body is the raw
  `{"detail": "<ERROR_CODE>"}` form **instead of** the common envelope. Their
  success responses still use the common envelope above.
- Create endpoints return HTTP **201** on success: `POST /api/meetings`,
  `POST /api/votes`, `POST /api/service-calls`, and `POST /api/translations`
  (when `final=true`). All other successful writes return 200.
- The frontend must initialize by calling the concrete resources below. There
  is no aggregate dashboard endpoint dependency in the current app.

## Health Check

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/health` | Local startup and health check. Response body: `{"status": "ok"}`. |

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `ENABLE_DEMO_SEED` | `false` | Create demo data only when the database has no meetings. |
| `ENABLE_DEMO_SEED_WHEN_NO_ACTIVE` | `false` | Create a demo active meeting if startup finds no active meeting. |
| `ENABLE_DEMO_SEAT_API` | `false` | Enable development-only seat occupy/vacate endpoints. |
| `ENABLE_TRANSLATION_MODEL` | unset | Enable real OPUS-MT translation for final records. |
| `TRANSLATION_MODEL_PATH` | unset | Override the local translation model directory. |
| `RUN_TRANSLATION_SMOKE` | unset | Run translation model smoke tests. |
| `VITE_ENABLE_DEMO_CONTROLS` | `false` | Show frontend demo controls. |
| `SMARTDESK_AGENT_URL` | `http://127.0.0.1:8766` | Loopback Display Agent used by the read-only host-display status aggregator. |
| `SMARTDESK_MEDIAMTX_CONTROL_URL` | `http://127.0.0.1:9997` | Loopback MediaMTX Control API base URL. |
| `SMARTDESK_MEDIAMTX_METRICS_URL` | `http://127.0.0.1:9998/metrics` | Loopback MediaMTX metrics endpoint. |
| `SMARTDESK_STREAM_PATH` | `screen` | Screen stream path used by status aggregation. |
| `ENABLE_SCREEN_STREAM` | `false` | Integrated startup switch for screen-stream services (Display Agent + Screen Supervisor). Set to `true` before running `start.bat` to enable. |

## Meeting APIs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/meetings` | List meetings. |
| `POST` | `/api/meetings` | Create a pending meeting. |
| `GET` | `/api/meetings/active` | Return the current active meeting or `null`. |
| `GET` | `/api/meetings/{meeting_id}` | Get one meeting. |
| `POST` | `/api/meetings/{meeting_id}/start` | Start a pending meeting; only one active meeting is allowed. |
| `POST` | `/api/meetings/{meeting_id}/end` | End an active meeting. |
| `GET` | `/api/meetings/{meeting_id}/agendas` | List agenda items. Keeps the existing top-level `Agenda[]` response shape. |
| `POST` | `/api/meetings/{meeting_id}/agendas` | Add an agenda item. Defaults to `status=pending`; active/ended lifecycle guards apply. |
| `DELETE` | `/api/meetings/{meeting_id}/agendas/{agenda_id}` | Delete a non-active agenda item; deleting active or ended-meeting agenda items is forbidden. |
| `POST` | `/api/meetings/{meeting_id}/agendas/{agenda_id}/set-current` | Set a pending/skipped agenda as the current active topic. |
| `POST` | `/api/meetings/{meeting_id}/agendas/advance` | Complete the current active topic and activate the next pending topic. |
| `POST` | `/api/meetings/{meeting_id}/agendas/{agenda_id}/complete` | Complete the current active topic. |
| `POST` | `/api/meetings/{meeting_id}/agendas/{agenda_id}/skip` | Skip the current active topic. |
| `GET` | `/api/meetings/{meeting_id}/attendees` | List attendees. |
| `POST` | `/api/meetings/{meeting_id}/attendees` | Add an attendee. |
| `DELETE` | `/api/meetings/{meeting_id}/attendees/{attendee_id}` | Delete an attendee. |

Create request bodies (JSON):

```json
POST /api/meetings
{ "title": "Q3 Review", "description": null }   // title 1..200 (required); 201

POST /api/meetings/{meeting_id}/agendas
{ "title": "Opening", "sort_order": 0 }          // title 1..500 (required); sort_order int >= 0, default 0

POST /api/meetings/{meeting_id}/attendees
{ "name": "Alice", "title": "" }                 // name 1..100 (required); title default ""
```

Meeting backend statuses are `pending`, `active`, and `finished`. The frontend
maps a finished meeting being reviewed to local `meetingStatus=meeting_ended`.

Ending a meeting resets seats to `vacant`, clears attendee seat bindings,
sets attendees to `checked_in=false`, closes any open vote, preserves the
speaker seat value, and keeps historical votes, service calls, and translation
records.

## Agenda APIs

Agenda items are persisted meeting resources. `GET
/api/meetings/{meeting_id}/agendas` must remain backward compatible: the
top-level response data stays an `Agenda[]`; each item is extended with status
and timestamp fields.

Agenda item shape:

```json
{
  "id": 1,
  "meeting_id": 1,
  "title": "Product Proposal Discussion",
  "sort_order": 3,
  "status": "active",
  "started_at": "2026-06-13T10:00:00Z",
  "completed_at": null,
  "skipped_at": null
}
```

Status values:

- `pending`
- `active`
- `completed`
- `skipped`

Allowed state transitions:

- `pending -> active`
- `skipped -> active`
- `active -> completed`
- `active -> skipped`
- `active -> completed + next pending -> active`

Forbidden state transitions:

- `completed -> active`
- `completed -> skipped`
- `pending -> completed`
- `pending -> skipped`
- `skipped -> completed`
- `active -> pending`

State mutation rules:

- A meeting must never have more than one `active` agenda item.
- Agenda status changes must run in a backend transaction.
- `set-current` accepts `pending` or `skipped` agenda items only.
- Calling `set-current` for the already active agenda is idempotent and must
  not update `started_at`.
- Calling `set-current` for a `completed` agenda returns `400`.
- If another agenda is active, `set-current` completes the old active agenda
  and activates the new agenda in the same transaction.
- `complete` only works for the current active agenda; otherwise it returns
  `400`.
- `skip` only works for the current active agenda; otherwise it returns `400`.
- `advance` requires an active agenda; otherwise it returns `400`.
- `advance` completes the current active agenda and activates the next
  `pending` agenda by `sort_order`.
- If `advance` finds no next pending agenda, the current active agenda becomes
  `completed` and there is no current agenda.
- `create agenda` defaults to `status=pending`.
- `delete agenda` is allowed only for non-active agenda items in an active
  meeting. Deleting an active agenda returns `400`.

Meeting lifecycle guard:

- Agenda write APIs only work when `meeting.status=active`.
- If the meeting is finished, `create`, `delete`, `set-current`, `advance`,
  `complete`, and `skip` return `400` or `409`.
- `GET /api/meetings/{meeting_id}/agendas` remains available for finished
  meetings so the frontend can show final agenda progress.

Timestamp rules:

- `pending`: `started_at=null`, `completed_at=null`, `skipped_at=null`.
- `active`: `started_at=now`, `completed_at=null`, `skipped_at=null`.
- `completed`: `completed_at=now`, `skipped_at=null`.
- `skipped`: `skipped_at=now`, `completed_at=null`.
- `skipped -> active`: clear `skipped_at` and refresh `started_at`.
- Switching current agenda: old active becomes `completed` with
  `completed_at=now`; new agenda becomes `active` with `started_at=now`,
  `completed_at=null`, and `skipped_at=null`.

Agenda mutation endpoints may return an agenda-state response for convenience:

```json
{
  "meeting_id": 1,
  "current_agenda": null,
  "agendas": [],
  "progress": {
    "total": 3,
    "completed": 1,
    "skipped": 1,
    "active": 0,
    "pending": 1,
    "current_index": null
  }
}
```

Frontend clients must still be able to refresh the source of truth through
`GET /api/meetings/{meeting_id}/agendas`.

## Seat APIs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/seats` | Return all 9 seat states. |
| `POST` | `/api/seats/{seat_id}/checkin` | Check an attendee into an occupied unchecked seat. |
| `GET` | `/api/seats/speaker` | Return the current speaker seat. |
| `POST` | `/api/seats/speaker` | Set speaker seat. See request body below. |
| `DELETE` | `/api/seats/speaker` | Clear speaker seat. |

`POST /api/seats/speaker` request body:

```json
{"seat_id": 1}
```

- `seat_id`：必填，integer，范围 1..9；`1` 为主持人位。

`GET /api/seats/speaker` 返回 `{"seat_id": int|null}`（无当前演讲者时为
`null`），不需要请求体。`DELETE /api/seats/speaker` 也不需要请求体。

`POST /api/seats/{seat_id}/checkin` request body:

```json
{"attendee_id": 3}
```

- `attendee_id`：必填，integer，`> 0`。

Check-in requires:

- active meeting exists;
- seat status is `occupied_unchecked`;
- attendee exists in the active meeting;
- attendee is not bound to a different seat;
- seat is not bound to a different attendee.

Successful check-in sets `seat.status=checked_in`, sets both seat and attendee
bindings, and broadcasts `check_in`.

## Development Seat APIs

These endpoints are for local demo setup only. They are unavailable unless
`ENABLE_DEMO_SEAT_API=true`; disabled endpoints should behave as not found.

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/dev/seats/{seat_id}/occupy` | Mark a vacant seat as occupied unchecked. |
| `POST` | `/api/dev/seats/{seat_id}/vacate` | Vacate a seat and clear attendee binding. |

## Vote APIs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/votes/active` | Return active open vote or `null`. |
| `GET` | `/api/votes?meeting_id={meeting_id}` | Return all votes for a meeting, newest first. Includes closed vote history. |
| `POST` | `/api/votes` | Create a vote. |
| `GET` | `/api/votes/{vote_id}` | Get vote detail. |
| `POST` | `/api/votes/{vote_id}/submit` | Submit or update attendee vote. |
| `GET` | `/api/votes/{vote_id}/statistics` | Get vote result counts. |
| `POST` | `/api/votes/{vote_id}/close` | Close vote. |

Vote lifecycle uses the current minimal backend statuses:

- `open`: published and visible to seat clients; attendees may submit or update votes.
- `closed`: final result state; vote submission is rejected, statistics remain queryable.

`draft` and `archived` are deferred. Only one `open` vote is supported. Repeated
votes from the same attendee update the existing vote record.

Create / submit request bodies (JSON):

```json
POST /api/votes
{ "meeting_id": 1, "title": "Lunch?", "options": ["A","B"], "is_anonymous": false }
// title <= 500, required; options >= 2 strings, required; is_anonymous default false; 201
// errors: 400 EMPTY_TITLE, 409 conflict

POST /api/votes/{vote_id}/submit
{ "attendee_id": 3, "option": "A" }
// errors: 404 vote not found, 400 (closed / invalid option)
```

Response shapes:

```json
Vote object:  { "id": 1, "meeting_id": 1, "title": "Lunch?", "options": ["A","B"], "status": "open", "is_anonymous": false, "total_votes": 0, "created_at": "2026-06-13T10:00:00", "closed_at": null }

GET /api/votes/{vote_id}/statistics:
{
  "vote_id": 1,
  "title": "Lunch?",
  "is_anonymous": false,
  "status": "open",
  "total_votes": 2,
  "results": [
    { "option": "A", "count": 1, "attendee_ids": [3] },
    { "option": "B", "count": 1, "attendee_ids": null }
  ]
}
// results follow the original option order defined on the vote; attendee_ids is null when the vote is anonymous
```

## Service Call APIs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/service-calls?meeting_id=N` | List calls for a meeting. |
| `GET` | `/api/service-calls/current?meeting_id=N&seat_id=N` | Return the current pending call for a seat. |
| `POST` | `/api/service-calls?meeting_id=N` | Create a call. |
| `POST` | `/api/service-calls/{call_id}/resolve` | Resolve a call. |
| `POST` | `/api/service-calls/{call_id}/cancel` | Cancel a call. |

`POST /api/service-calls?meeting_id=N` — `meeting_id` is a required query
parameter.

Request body:

```json
{
  "seat_id": 1,
  "service_type": "coffee",
  "custom_text": null
}
```

Constraints:

| Field | Required | Type | Constraints |
|---|---|---|---|
| `seat_id` | Yes | integer | 1..9 |
| `service_type` | Yes | string | `coffee` / `tea` / `water` / `other` |
| `custom_text` | No | string or null | Accepted by the request schema but not persisted by the current implementation. Callers must not expect this value in responses or history. |

`POST /api/service-calls` returns **201**.

Service call status lifecycle:

- `pending`: initial state when a call is created.
- `resolved`: set by `POST /api/service-calls/{call_id}/resolve`.
- `cancelled`: set by `POST /api/service-calls/{call_id}/cancel`.

Error `409` when creating a call while the seat already has a pending call.
Errors `404` (call not found) / `400` (invalid state) on resolve/cancel.

Service call object shape (in `data`):

```json
{ "id": 1, "meeting_id": 1, "seat_id": 4, "service_type": "coffee", "status": "pending", "created_at": "2026-06-13T10:00:00" }
```

## Translation APIs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/translations?meeting_id=N&seat_id=N` | Query persisted final translation records. Returns a history object (not a raw list); `seat_id` is an optional filter. |
| `POST` | `/api/translations` | Upload speech audio as **multipart/form-data**. Handles both interim (`final=false`) and final (`final=true`) results. |

`POST /api/translations` is **multipart/form-data**, not JSON. Fields:

| Field | Required | Type | Notes |
|---|---|---|---|
| `audio` | Yes | file | Audio blob. |
| `meeting_id` | Yes | integer | Target meeting. |
| `seat_id` | Yes | integer | Originating seat. |
| `session_key` | No | string | Default `""`. |
| `final` | No | boolean | Default `false`. |

Behavior by `final`:

- `final=false` (interim): server transcribes and returns the recognized text
  immediately. **Not persisted.** `data` is `{ "text": "..." }` (HTTP 200).
- `final=true`: server transcribes, persists a `translation_records` row, and
  returns it. `data` is a `TranslationRecordResponse` (**HTTP 201**). On failure
  returns 500.

`GET /api/translations` returns a history object:

```json
{
  "meeting_id": 1,
  "entries": [
    {
      "id": 1,
      "meeting_id": 1,
      "seat_id": 4,
      "utterance_id": null,
      "source_lang": "zh",
      "target_lang": "en",
      "source_text": "...",
      "translated_text": "...",
      "source_type": null,
      "created_at": "2026-06-13T10:00:00"
    }
  ]
}
```

`TranslationRecordResponse` fields: `id`, `meeting_id`, `seat_id`,
`utterance_id` (nullable), `source_lang`, `target_lang`, `source_text`,
`translated_text`, `source_type` (nullable), `created_at`. Interim results are
never persisted.

When `ENABLE_TRANSLATION_MODEL=true`, final Chinese source text is translated by
the local OPUS-MT zh-en model. When the model is disabled, `translated_text`
uses the backward-compatible value `[translation not available]`.

## Speech APIs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/speech/status` | Return speech model readiness and preload state. |
| `POST` | `/api/speech/preload` | Start background speech model preload. |

Speech audio upload uses WebSocket:

```text
/ws/speech/{meeting_id}?seat=N
```

The backend also exposes a general broadcast WebSocket for the same meeting
(used to push seat/agenda/vote/service-call/check-in events to clients):

```text
/ws/{meeting_id}?seat=N
```

See `WEBSOCKET_PROTOCOL.md` for the binary audio and event contract.

`GET /api/speech/status` also reports `vad_model`, `translation_model`,
`translation_model_path`, `translation_last_error`, and the active
`voice_gate` defaults. Translation readiness is diagnostic and does not block
Chinese speech recognition. Runtime diagnostics include `active_sessions`,
`pending_finalizations`, `process_rss_mb`, `max_buffered_audio_seconds`,
`soft_utterance_seconds` (30), `hard_utterance_seconds` (45), and
`rollover_overlap_ms` (300).

## Hardware Status API

```http
GET /api/hardware/status
```

Each item in `data.seats` includes `current_mode` (the last mode confirmed by
the Arduino ACK), `intended_mode`, `command_pending`, `last_ack_at`, and
`last_error`, in addition to seat, port, enabled, and connection fields. An
offline seat remains in the response so the management UI can show pending
commands and port diagnostics.

## Host Display and Screen Stream APIs

The complete Phase 1-6 process, network, HTTP, frontend, and deployment
contract is defined in `HOST_DISPLAY_CONTRACT.md`.

### SmartDesk backend: read-only status

```http
GET /api/host-display/status
```

This endpoint returns a raw stable status object containing `agent_state`,
`stream_state`, `active_app`, `viewer_count`, the three application states
(under `apps`, each `{running, window_found}`), and the stream profile (under
`profile`, `{width, height, fps}`; all nullable). Upstream Agent or MediaMTX
failures degrade to offline/unknown/null values and must not cause a backend
500.

Frontend integration note: this raw response is incompatible with the common
`apiGet()` envelope parser. Since Phase 5, `fetchHostDisplayStatus()` uses
`apiGetRaw()` which reads the body as-is without expecting an envelope.
Test fixtures return raw JSON matching the actual backend schema.

There is deliberately no backend application-switching endpoint:

```text
POST /api/host-display/activate  # forbidden / not implemented
```

### Central-host local Display Agent

These endpoints are not served by the SmartDesk backend and are reachable only
on the browser machine's loopback interface (CORS is a fixed origin whitelist —
default `http://127.0.0.1:5173`, `http://localhost:5173` — not `*`):

```http
GET  http://127.0.0.1:8766/status
POST http://127.0.0.1:8766/activate
GET  http://127.0.0.1:8766/health
```

`GET /status` returns:

```json
{
  "agent_state": "online",
  "win32_available": true,
  "com_available": true,
  "apps": {
    "powerpoint": { "running": true,  "window_found": true },
    "solidworks": { "running": false, "window_found": false },
    "smartdesk":  { "running": true,  "window_found": true }
  },
  "active_app": "powerpoint"
}
```

`GET /health` returns `{"status":"ok","agent":"display_agent"}`.

The `POST /activate` request accepts exactly one field and one of three values:

```json
{"app":"powerpoint"}
```

```text
powerpoint | solidworks | smartdesk
```

`POST /activate` returns `ActivateResponse`:

```json
{ "ok": true, "app": "powerpoint", "action": "activate", "detail": "" }
```

If the target app has no running window or cannot be brought to the foreground,
the Agent returns **HTTP 409** with the same `ActivateResponse` shape (e.g.
`{"ok": false, "app": "...", "action": "...", "detail": "..."}`). The request
schema uses `extra="forbid"`, so any unknown field is rejected.

Phase 5 Admin controls must probe the Agent and post directly to it. This works
only when `/admin` is opened on the central host. Remote control is deferred
until authentication and an authorized backend proxy exist.

### Browser stream endpoint

LAN viewers use MediaMTX directly:

```text
http://{central-host}:8889/screen
```

The `/screen` frontend route embeds this endpoint as a read-only WebRTC viewer.
Video data does not pass through the SmartDesk backend or meeting WebSocket.

## Frontend Initialization

Admin page:

```http
GET /api/meetings/active
GET /api/seats
GET /api/seats/speaker
GET /api/votes/active
GET /api/votes?meeting_id={activeMeetingId}
GET /api/service-calls?meeting_id={activeMeetingId}
GET /api/translations?meeting_id={activeMeetingId}
GET /api/meetings/{activeMeetingId}/agendas
GET /api/meetings/{activeMeetingId}/attendees
```

Seat page:

```http
GET /api/meetings/active
GET /api/seats
GET /api/seats/speaker
GET /api/votes/active
GET /api/votes?meeting_id={activeMeetingId}
GET /api/service-calls/current?meeting_id={activeMeetingId}&seat_id={seatId}
GET /api/translations?meeting_id={activeMeetingId}
GET /api/meetings/{activeMeetingId}/agendas
GET /api/meetings/{activeMeetingId}/attendees
```

Seat pages display meeting-wide public transcript history by default. The
`seat_id` query parameter remains an optional API capability for explicit
filtered reads, but the current seat UI does not pass it.

If there is no active meeting, the frontend must show a waiting state and must
not call endpoints that require `meeting_id`.
