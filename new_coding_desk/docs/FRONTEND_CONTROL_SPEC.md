# Frontend Control Spec

This document freezes the current frontend control target for SmartDesk v1.
It is based on the current FastAPI endpoints, frontend API client, and existing
Admin/Seat UI. It is not a future product wish list.

## Roles and Routes

Current implementation:

- `/` renders the Admin dashboard.
- `/?seat=N` renders the Seat tablet for seats 1 through 10.

Target v1 implementation:

- `/admin` renders the Admin control console.
- `/seat/:seatId` renders the Seat tablet for seats 1 through 10.
- `/` redirects to `/admin`.
- `/?seat=N` redirects to `/seat/N` for backward compatibility.
- `/display` is a placeholder only. Full central display control is deferred.

The Seat tablet must not expose a normal "Back to Admin" control unless
`VITE_ENABLE_DEMO_CONTROLS=true`.

## Current Implementable Controls

These controls are backed by existing backend endpoints and may be implemented
without adding new backend APIs:

| Area | Supported controls | Backend contract |
|---|---|---|
| Meeting | create, start, end | `POST /api/meetings`, `POST /api/meetings/{id}/start`, `POST /api/meetings/{id}/end` |
| Attendees | create, delete | `POST /api/meetings/{id}/attendees`, `DELETE /api/meetings/{id}/attendees/{attendee_id}` |
| Agenda | create, delete | `POST /api/meetings/{id}/agendas`, `DELETE /api/meetings/{id}/agendas/{agenda_id}` |
| Speaker seat | set, clear | `POST /api/seats/speaker`, `DELETE /api/seats/speaker` |
| Voting | create, close | `POST /api/votes`, `POST /api/votes/{id}/close` |
| Service calls | resolve | `POST /api/service-calls/{id}/resolve` |
| Seat check-in | check in existing attendee | `POST /api/seats/{seat_id}/checkin` |
| Demo seat state | occupy, vacate | `POST /api/dev/seats/{seat_id}/occupy`, `POST /api/dev/seats/{seat_id}/vacate` |

## Speech and Transcript Rules

The current speech contracts remain unchanged:

- Speech uplink: `/ws/speech/{meeting_id}?seat=N`.
- Meeting broadcast: `/ws/{meeting_id}?seat=N`.
- Only the current Speaker Seat may stream speech audio.
- Audio format is PCM16 little-endian, 16 kHz, mono.
- Interim events use `translation_interim`.
- Final events use `translation_final`.
- Cancelled live captions use `translation_interim_cancelled`.
- Interims are not persisted and are not translated.
- Finals are persisted in `translation_records`.

## Deferred Controls

These are intentionally not part of the current implementation batch:

- Attendee edit.
- Manual attendee-to-seat assignment from Admin.
- Agenda reorder, current agenda selection, and completed/skipped states.
- Display control beyond the `/display` placeholder.
- Service call `accepted` or `processing` states.
- Vote draft, publish, archive, and reopen states.
- Real authentication or role-based authorization.
- New events named `asr_interim` or `asr_final`.
- New database tables named `asr_segments` or `translation_segments`.

## Implementation Discipline

- Do not add backend endpoints for convenience unless a later task explicitly
  approves the contract change.
- Do not modify `speech_module/`; it is old reference code.
- New generated docs should be English-only unless explicitly requested
  otherwise.
- If the current UI needs behavior not listed here, record it as deferred
  instead of silently inventing a contract.
