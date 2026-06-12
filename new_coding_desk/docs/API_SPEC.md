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
- The frontend must initialize by calling the concrete resources below. There
  is no aggregate dashboard endpoint dependency in the current app.

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

## Meeting APIs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/meetings` | List meetings. |
| `POST` | `/api/meetings` | Create a pending meeting. |
| `GET` | `/api/meetings/active` | Return the current active meeting or `null`. |
| `GET` | `/api/meetings/{meeting_id}` | Get one meeting. |
| `POST` | `/api/meetings/{meeting_id}/start` | Start a pending meeting; only one active meeting is allowed. |
| `POST` | `/api/meetings/{meeting_id}/end` | End an active meeting. |
| `GET` | `/api/meetings/{meeting_id}/agendas` | List agenda items. |
| `POST` | `/api/meetings/{meeting_id}/agendas` | Add an agenda item. |
| `DELETE` | `/api/meetings/{meeting_id}/agendas/{agenda_id}` | Delete an agenda item. |
| `GET` | `/api/meetings/{meeting_id}/attendees` | List attendees. |
| `POST` | `/api/meetings/{meeting_id}/attendees` | Add an attendee. |
| `DELETE` | `/api/meetings/{meeting_id}/attendees/{attendee_id}` | Delete an attendee. |

Ending a meeting resets seats to `vacant`, clears attendee seat bindings,
sets attendees to `checked_in=false`, closes any open vote, preserves the
speaker seat value, and keeps historical votes, service calls, and translation
records.

## Seat APIs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/seats` | Return all 10 seat states. |
| `POST` | `/api/seats/{seat_id}/checkin` | Check an attendee into an occupied unchecked seat. |
| `GET` | `/api/seats/speaker` | Return the current speaker seat. |
| `POST` | `/api/seats/speaker` | Set speaker seat. |
| `DELETE` | `/api/seats/speaker` | Clear speaker seat. |

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

## Service Call APIs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/service-calls?meeting_id=N` | List calls for a meeting. |
| `GET` | `/api/service-calls/current?meeting_id=N&seat_id=N` | Return the current pending call for a seat. |
| `POST` | `/api/service-calls?meeting_id=N` | Create a call. |
| `POST` | `/api/service-calls/{call_id}/resolve` | Resolve a call. |
| `POST` | `/api/service-calls/{call_id}/cancel` | Cancel a call. |

Supported service types are the backend-supported values only, currently used
by the frontend as demo service request options.

## Translation APIs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/translations?meeting_id=N&seat_id=N` | Query persisted final translation records. |
| `POST` | `/api/translations` | Compatibility final audio upload path. Not used for realtime interim. |

Realtime speech final records are persisted to `translation_records` and are
queryable through `GET /api/translations`.

`translation_records` include:

- `id`
- `meeting_id`
- `seat_id`
- `utterance_id`
- `source_lang`
- `target_lang`
- `source_text`
- `translated_text`
- `source_type`
- `created_at`

Interim speech text is never persisted and never translated.

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

See `WEBSOCKET_PROTOCOL.md` for the binary audio and event contract.

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
GET /api/translations?meeting_id={activeMeetingId}&seat_id={seatId}
GET /api/meetings/{activeMeetingId}/agendas
GET /api/meetings/{activeMeetingId}/attendees
```

If there is no active meeting, the frontend must show a waiting state and must
not call endpoints that require `meeting_id`.
