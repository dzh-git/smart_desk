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
  `POST /api/people`,
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
| `SMARTDESK_ALLOW_PROTOTYPE_IDENTITY_CHECKIN` | `false` | Development-only opt-in allowing a `PROTOTYPE` + `PROVISIONAL` identity result to reach the existing seat check-in state machine. Never enable before local calibration is accepted. |
| `ENABLE_TRANSLATION_MODEL` | unset | Enable local OPUS-MT translation for final records. |
| `TRANSLATION_ZH_EN_MODEL_PATH` | `models/opus-mt-zh-en` | Local Chinese-to-English model directory. |
| `TRANSLATION_EN_ZH_MODEL_PATH` | `models/opus-mt-en-zh` | Local English-to-Chinese model directory. |
| `BILINGUAL_ASR_MODEL_PATH` | `models/SenseVoiceSmall` | Local bilingual sentence-final ASR directory. |
| `ENGLISH_STREAMING_ASR_MODEL_PATH` | `models/sherpa-onnx-streaming-zipformer-en-2023-06-26` | Local English streaming Zipformer directory. |
| `ENGLISH_ONLINE_PUNCTUATION_MODEL_PATH` | `models/sherpa-onnx-online-punct-en-2024-08-06` | Local English online punctuation and casing model directory. |
| `CHINESE_ASR_MODEL_PATH` | `models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch` | Local Chinese-specialized sentence-final ASR directory. |
| `TRANSLATION_MODEL_PATH` | unset | Legacy Chinese-to-English path override. |
| `RUN_TRANSLATION_SMOKE` | unset | Run translation model smoke tests. |
| `VITE_ENABLE_DEMO_CONTROLS` | `false` | Show frontend demo controls. |
| `SMARTDESK_AGENT_URL` | `http://127.0.0.1:8766` | Loopback Display Agent used by the read-only host-display status aggregator. |
| `SMARTDESK_MEDIAMTX_CONTROL_URL` | `http://127.0.0.1:9997` | Loopback MediaMTX Control API base URL. |
| `SMARTDESK_MEDIAMTX_METRICS_URL` | `http://127.0.0.1:9998/metrics` | Loopback MediaMTX metrics endpoint. |
| `SMARTDESK_STREAM_PATH` | `screen` | Screen stream path used by status aggregation. |
| `ENABLE_DISPLAY_AGENT` | `true` | Start the loopback Display Agent independently of screen streaming. |
| `ENABLE_SCREEN_STREAM` | `false` | Start the FFmpeg/MediaMTX screen-stream supervisor. |

## Meeting APIs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/meetings` | List meetings. Optional `status=pending`, `active`, or `finished` filters results before returning up to 200 matches, newest first. |
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
| `POST` | `/api/meetings/{meeting_id}/attendees` | Add an attendee to a pending or active meeting. |
| `DELETE` | `/api/meetings/{meeting_id}/attendees/{attendee_id}` | Remove an unchecked attendee with no identity check-in or voting history. |
| `PUT` | `/api/meetings/{meeting_id}/seat-assignments/{seat_id}` | Assign an attendee to a seat in a pending or active meeting. |
| `DELETE` | `/api/meetings/{meeting_id}/seat-assignments/{seat_id}` | Clear the assignment for an unchecked seat in a pending or active meeting. |

Create request bodies (JSON):

```json
POST /api/meetings
{ "title": "Q3 Review", "description": null }   // title 1..200 (required); 201

POST /api/meetings/{meeting_id}/agendas
{ "title": "Opening", "sort_order": 0 }          // title 1..500 (required); sort_order int >= 0, default 0

POST /api/meetings/{meeting_id}/attendees
{ "name": "Alice", "title": "", "personId": "person_001" }
// name 1..100 (required); title default ""; personId optional stable identity
```

Meeting backend statuses are `pending`, `active`, and `finished`. The frontend
maps a finished meeting being reviewed to local `meetingStatus=meeting_ended`.

Ending a meeting resets seats to `vacant`, clears attendee seat bindings and
the current speaker, sets attendees to `checked_in=false`, and closes the
meeting's open vote. Historical attendees, votes, service calls, and
translation records remain readable. Attendee and seat assignment changes
return `400 MEETING_FINISHED` after the meeting ends.

Attendee deletion returns `409 ATTENDEE_ALREADY_CHECKED_IN` for a checked-in
attendee or `409 ATTENDEE_HAS_HISTORY` for an attendee with stored check-in
evidence or votes.

## People APIs

`Person.id` is the stable identifier used by local face templates across
meetings. It is distinct from the per-meeting, auto-incrementing
`Attendee.id`.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/people` | List stable people. |
| `POST` | `/api/people` | Create a stable person; returns 201. |

```json
POST /api/people
{ "id": "person_001", "name": "Alice" }
```

`id` must contain 3–64 ASCII letters, numbers, dots, underscores, or hyphens.
An attendee may reference a Person through optional `personId`; the same Person
cannot appear twice in one meeting.

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
| `POST` | `/api/seats/{seat_id}/identity-checkin` | Validate Android identity evidence, map stable Person to the active meeting attendee, then reuse normal check-in. |
| `POST` | `/api/seats/{seat_id}/debug-admit` | In configured `identity_mode=debug` only, authenticate the bound tablet and admit its assigned attendee without fabricating biometric evidence. |
| `POST` | `/api/seats/{seat_id}/tablet-vacate` | Authenticate the bound tablet, release the attendee and return the seat to `vacant`. |
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

`POST /api/seats/{seat_id}/identity-checkin` request body:

```json
{
  "eventId": "6fe8e135-15f5-4a3f-946c-8800d7519937",
  "eventTimestamp": 1785168000000,
  "personCode": "person_001",
  "deviceId": "tablet-a83f0a90-1f47-4a7d-83ca-53d4b570a201",
  "deviceSeatId": 1,
  "status": "VERIFIED",
  "similarity": 0.82,
  "thresholdStatus": "PROVISIONAL",
  "verificationLevel": "PROTOTYPE",
  "modelVersion": "se-mobilefacenet-ms1mv3-arcface-emb256-v1"
}
```

The request must include `X-SmartDesk-Device-Token`. The token is compared
against the salted PBKDF2 hash stored for the provisioned tablet; raw device
tokens are never stored by the backend.

The endpoint never trusts face evidence as a direct attendee ID. It:

1. authenticates an enabled device provisioned for the URL seat and rejects
   either a registry or request seat mismatch;
2. requires `eventTimestamp` in Unix epoch milliseconds; a new event older
   than 120 seconds or more than 30 seconds in the future is rejected with
   `IDENTITY_EVENT_STALE` or `IDENTITY_EVENT_FUTURE` (bounded settings:
   `SMARTDESK_IDENTITY_MAX_EVENT_AGE_SECONDS` and
   `SMARTDESK_IDENTITY_MAX_FUTURE_SKEW_SECONDS`);
3. rejects non-`VERIFIED` and `CALIBRATION_PENDING` results;
4. accepts `VALIDATED` only with `thresholdStatus=VALIDATED`;
5. rejects `PROTOTYPE` by default; the explicit development environment flag
   may allow `PROTOTYPE` only with `thresholdStatus=PROVISIONAL`;
6. resolves `Person.id` to exactly one attendee in the active meeting;
7. accepts either `vacant` or `occupied_unchecked`; a vacant seat is occupied
   inside the same transaction before delegating duplicate-seat and
   attendee-binding checks to `SeatService.check_in`;
8. atomically commits Seat, Attendee and the durable identity event, then emits
   `seat_occupied` followed by `check_in` for a newly occupied seat;
9. persists `eventId`; an identical retry returns the existing checked-in
   state without broadcasting a second `check_in`, while conflicting evidence
   using the same ID returns HTTP 409.

`POST /api/seats/{seat_id}/tablet-vacate` requires
`X-SmartDesk-Device-Token` and this body:

```json
{"deviceId": "tablet-a83f0a90-1f47-4a7d-83ca-53d4b570a201", "deviceSeatId": 1}
```

The device registry seat, URL seat and `deviceSeatId` must match, and an active
meeting must exist. Success clears both seat and attendee bindings, emits
`seat_vacant`, and returns the standard `SeatStateResponse`.

Identity submissions use a bounded per-device/seat sliding-window limiter
(default 60/minute). HTTP 429 returns stable `RATE_LIMITED` plus
`Retry-After`; change the bounded limit with
`SMARTDESK_IDENTITY_RATE_LIMIT_PER_MINUTE`.

Provisioning is fail-closed unless
`SMARTDESK_DEVICE_PROVISIONING_TOKEN` contains at least 24 characters:

```http
POST /api/tablet-devices/provision
X-SmartDesk-Provisioning-Token: <admin provisioning token>
Content-Type: application/json
```

```json
{
  "deviceId": "tablet-a83f0a90-1f47-4a7d-83ca-53d4b570a201",
  "seatId": 1,
  "deviceToken": "unique-device-token-at-least-24-chars",
  "enabled": true,
  "replaceExisting": false
}
```

Provisioning the same physical device rotates its token and may move it to an
unbound seat. A seat may have only one registered tablet. Replacing a different
tablet requires the admin-authorized request to set `replaceExisting=true`.

Before loading a formal seat page, Android validates its stored binding:

```http
POST /api/tablet-devices/{deviceId}/validate
X-SmartDesk-Device-Token: <per-device token>
Content-Type: application/json

{"seatId": 1, "appVersion": "0.8.0"}
```

The response includes the stable physical `deviceId`, derived human-readable
`seatAlias` such as `tablet-seat-01`, and the backend-authoritative
`identityMode` (`formal` or `debug`). Missing or invalid integration config
always resolves to `formal`.

`POST /api/seats/{seatId}/debug-admit` accepts the same authenticated device
identity shape as tablet vacate:

```json
{"deviceId": "tablet-a83f0a90-1f47-4a7d-83ca-53d4b570a201", "deviceSeatId": 1}
```

It is rejected with `DEBUG_IDENTITY_MODE_DISABLED` outside debug mode. The
server selects only the active meeting attendee assigned to the authenticated
seat, reuses the normal seat state machine, and never writes an identity event.

### Central face-template management and tablet synchronization

All management writes require the bound Seat 1 `deviceId` and
`X-SmartDesk-Device-Token`. Raw photos are never accepted by these APIs.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/face-templates` | Seat 1 list/capacity/revisions. |
| `PUT` | `/api/face-templates/{personId}` | Seat 1 upload a device-encrypted 256-D template envelope. |
| `DELETE` | `/api/face-templates/{personId}` | Delete an unused template without deleting Person/history. |
| `GET/PUT` | `/api/face-templates/meetings/{meetingId}/assignments` | Read or batch update Seat 1 host and Seat 2–9 participant mappings through existing attendees. |
| `PUT` | `/api/tablet-devices/{deviceId}/face-transport-key` | Register the device Android-Keystore RSA public key. |
| `GET` | `/api/tablet-devices/{deviceId}/face-template-bundle` | Download the single template assigned to that participant seat, encrypted to the device. |
| `POST` | `/api/tablet-devices/{deviceId}/face-template-sync-ack` | Report target meeting/revision/count/result and redacted error. |

The central library holds at most 81 templates. Adding the 82nd evicts the
oldest template not referenced by a pending or active meeting and returns the
evicted person; if every template is protected, the request returns
`FACE_TEMPLATE_CAPACITY_LOCKED`. Bundles carry the assigned `personId`, its
single template, exact model hash, pipeline version, dimension, provisional
threshold, meeting ID, and template-set revision. Verification is 1:1; Top2
is optional diagnostic data and does not gate admission.

The formal Android seat page sends authenticated operational heartbeats:

```http
POST /api/tablet-devices/tablet-a83f0a90-1f47-4a7d-83ca-53d4b570a201/heartbeat
X-SmartDesk-Device-Token: <per-device token>
Content-Type: application/json
```

```json
{
  "seatId": 1,
  "appVersion": "0.8.0",
  "cameraStatus": "READY",
  "faceModelStatus": "READY",
  "registeredTemplatesCount": 3,
  "microphoneStatus": "READY",
  "meetingWebsocketStatus": "CONNECTED",
  "diagnosticStatus": "READY",
  "lastError": null
}
```

The device ID, token, and bound seat must all match. Heartbeats never contain
face images, embeddings, diagnostic crops, or raw audio.
`appVersion` must be SemVer and at least
`SMARTDESK_TABLET_MIN_APP_VERSION` (default `0.8.0`). Invalid and old clients
receive `DEVICE_APP_VERSION_INVALID` and `DEVICE_APP_VERSION_UNSUPPORTED`.
Heartbeat rate is limited per device/seat (default 30/minute, configurable
through `SMARTDESK_TABLET_HEARTBEAT_RATE_LIMIT_PER_MINUTE`); provisioning is
limited per client (default 10/minute). Both return `RATE_LIMITED` and
`Retry-After` when exceeded.

Current Android face results remain `CALIBRATION_PENDING` until the 75-run
field calibration is complete. The production default therefore cannot use
them for automatic check-in.

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
votes from the same attendee update the existing vote record. A finished
meeting returns `400 MEETING_FINISHED` when a caller tries to create a vote
or change a legacy open vote. Repeating a close on an already closed vote
returns the existing record. Active-vote lookup excludes legacy open records
from finished meetings.

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

Create, resolve, and cancel return `400 MEETING_FINISHED` for finished
meetings. Service call history remains readable.

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
      "translation_status": "ok",
      "translation_error": null,
      "source_type": null,
      "created_at": "2026-06-13T10:00:00"
    }
  ]
}
```

`TranslationRecordResponse` fields: `id`, `meeting_id`, `seat_id`,
`utterance_id` (nullable), `source_lang`, `target_lang`, `source_text`,
`translated_text`, `translation_status`, `translation_error` (nullable),
`source_type` (nullable), `created_at`. Interim results are
never persisted.

When `ENABLE_TRANSLATION_MODEL=true`, SenseVoiceSmall detects Chinese or English
from the final sentence audio. English final text comes from SenseVoiceSmall;
Chinese final text is rescored by the local Paraformer-large model. The matching
local OPUS-MT direction translates it. A missing model keeps the source record, sets `translation_status` to
`unavailable`, and uses `[translation not available]` for compatibility.

## Speech APIs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/speech/status` | Return speech model readiness and preload state. |
| `POST` | `/api/speech/preload` | Start background speech model preload. |
| `GET` | `/api/speech/diagnostics?limit=N&utterance_id=ID` | Return bounded latency trace events, queue timings and runtime indicators. |
| `POST` | `/api/speech/diagnostics/clear` | Clear the in-memory latency trace before a controlled reproduction. |

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

Live source revisions use `translation_interim` with semantic sentence fields.
Completed sentences use ordered `translation_sentence` events (`pending`, then
`ok` or `unavailable`) keyed by `sentence_id`; these events are ephemeral and
are not written to translation history.

`GET /api/speech/status` also reports `vad_model`, `translation_model`,
`translation_model_path`, `translation_last_error`, and the active
`voice_gate` defaults. `live_asr` reports automatic probe/window intervals,
PyTorch/OMP/MKL thread budgets and maximum audio backlog; each active session
reports `pcm_queue_frames`, `audio_backlog_ms`, requested/detected language and
recognition engine. English diagnostics include `english_streaming_asr` and
`english_online_punctuation` model state, path, load error and latest inference
latency. Translation readiness is diagnostic and does not block
Chinese speech recognition. Runtime diagnostics include `active_sessions`,
`pending_finalizations`, `process_rss_mb`, `max_buffered_audio_seconds`,
`soft_utterance_seconds` (30), `hard_utterance_seconds` (45), and
`rollover_overlap_ms` (300).

Speech diagnostics are enabled before process startup with
`SMART_DESK_ENABLE_SPEECH_TRACE=true`; browser capture additionally requires
`VITE_ENABLE_SPEECH_TRACE=true`. The local launcher enables both. Diagnostic
events contain timestamps, identifiers, durations and queue depths, never PCM
audio. Queue metrics distinguish streaming frames slower than the 100 ms input
cadence, sentence-translation waiting/inference, and finalization waiting/work.

## Hardware Status API

```http
GET /api/hardware/status
```

`data.seats` contains the Arduino/Windows-compatible or ESP32 controller
channel. Each item includes `device_type`, device/firmware identity,
`current_mode`, `intended_mode`, command ACK state, heartbeat, sensor
diagnostics, and the last error. ESP32 connections whose heartbeat expires are
reported offline.

`data.tablets` is a separate nine-seat Android channel. It reports provisioning
and enablement, online/offline derived from authenticated `last_seen_at`,
app version, camera, face model, registered-template count, microphone,
meeting-WebSocket status, diagnostic status, last error, and face-template
target meeting/revision/count/sync result/redacted error. The default
offline window is 45 seconds and can be configured from 10–300 seconds with
`SMARTDESK_TABLET_OFFLINE_TIMEOUT_SECONDS`.

## Host Display and Screen Stream APIs

The complete Phase 1-6 process, network, HTTP, frontend, and deployment
contract is defined in `HOST_DISPLAY_CONTRACT.md`.

### SmartDesk backend: status and Seat 1 control relay

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

The bound Seat 1 Android tablet may switch the host application through:

```http
POST /api/host-display/activate
X-SmartDesk-Device-Token: <device-token>

{"deviceId":"...","deviceSeatId":1,"app":"powerpoint|solidworks|smartdesk"}
```

The backend authenticates an enabled device bound to Seat 1, accepts only the
three application values, and forwards only `{app}` to the configured,
loopback-validated Display Agent URL with a short timeout. The caller cannot
provide a target URL. Stable errors include `HOST_DEVICE_AUTH_FAILED`,
`DISPLAY_AGENT_OFFLINE`, `DISPLAY_APP_INVALID`,
`DISPLAY_APP_ALREADY_ACTIVE`, and `DISPLAY_ACTIVATION_FAILED`.

### Central-host local Display Agent

These endpoints are served by the local Display Agent and are reachable only
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
