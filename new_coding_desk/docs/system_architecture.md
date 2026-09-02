# SmartDesk System Architecture

SmartDesk is a local demo system for a smart meeting table. It contains a
FastAPI backend, a React/Vite frontend, SQLite persistence, WebSocket realtime
updates, local FunASR speech recognition, and optional local OPUS-MT
translation.

## Runtime Components

```text
frontend/ React + Vite + TypeScript
  -> HTTP API for business resources
  -> /ws/{meeting_id}?seat=N for broadcast events
  -> /ws/speech/{meeting_id}?seat=N for Speaker Seat PCM audio

../android_tablet/ Android APK
  -> WebView loads the same frontend /seat/{seatId}
  -> SmartDeskNative exposes local camera and face verification only
  -> diagnostic-web is limited to configuration, enrollment, and calibration

backend/ FastAPI
  -> routers validate HTTP requests
  -> services own business rules
  -> repositories own SQLite access
  -> EventBus publishes realtime events
  -> websocket handlers broadcast events and receive speech audio
  -> backend/speech_module owns ASR, punctuation, caption formatting

SQLite
  -> people, meetings, agendas, attendees, seats, votes, service calls, translation_records
```

The frontend never connects directly to FunASR. All audio and business state
flows through the backend.

## Backend Responsibilities

### Router Layer

Routers validate request shape, call services, and return `ApiResponse`. They
do not contain business rules or direct database writes.

Current routers:

- `meetings.py`
- `people.py`
- `seats.py`
- `votes.py`
- `service_calls.py`
- `translations.py`
- `speech.py`
- `dev.py` for demo-only seat controls
- `host_display.py` for display status aggregation plus the authenticated Seat 1 fixed-target activation relay

### Service Layer

Services own business behavior:

- `MeetingService`: create/start/end meetings, reset seats on end, trigger
  speech preload on meeting start.
- `PersonService`: create and list stable identities shared across meetings.
- `SeatService`: occupy/vacate/check-in seats, manage Speaker Seat, cancel old
  speech sessions on speaker switch, and resolve guarded Android identity
  evidence to the active meeting attendee before reusing normal check-in.
- `VoteService`: create, submit/update, summarize, and close votes.
- `ServiceCallService`: create, resolve, and cancel service calls.
- `SpeechStreamService`: manage speech WebSocket sessions, receive PCM frames,
  publish interim captions, run RMS endpoint detection, auto-finalize
  utterances.
- `TranslationService`: run final ASR, persist `translation_records`, optionally
  translate final text, and publish `translation_final`.
- `TranslationModelService`: load and call OPUS-MT only when
  `ENABLE_TRANSLATION_MODEL=true`.

### Repository Layer

Repositories are the only layer that reads or writes SQLAlchemy models. See
`DATABASE_SCHEMA.md` for ownership.

## Speech Architecture

Speech uses a dual WebSocket design:

- meeting broadcast channel: `/ws/{meeting_id}?seat=N`
- speech uplink channel: `/ws/speech/{meeting_id}?seat=N`

Only the current Speaker Seat can open the speech uplink channel. The frontend
sends PCM16 little-endian 16 kHz mono binary frames.

Current utterance flow:

1. Frontend sends `start`.
2. Backend generates `utterance_id` in the form
   `utt_{meeting_id}_{seat_id}_{seq}`.
3. Backend publishes `translation_interim` for live captions.
4. Backend RMS endpoint detection is the current VAD implementation.
5. On silence, backend auto-finalizes without requiring `end_hint`.
6. `end_hint` remains a manual fallback.
7. Final ASR is persisted in `translation_records`.
8. Final translation uses OPUS-MT when enabled; otherwise the legacy placeholder
   is stored.

FunASR FSMN-VAD is not the current final trigger. It is a deferred improvement.

## Frontend Architecture

The frontend has three routes:

- Admin dashboard at `/admin` (also the default redirect from `/`).
- Seat tablet at `/seat/:seatId` for seats 1 through 9; seat 1 is the host seat.
- Central display at `/display`.

The admin dashboard is the only write-capable control surface for meeting
lifecycle, speaker seat, attendees, agenda command, votes, service resolution,
and ended-meeting review. Seat tablets handle check-in, voting, service calls,
Speaker Seat voice streaming, and read-only current agenda display. The central
display shows meeting status, agenda progress, and current or final vote
results; it does not provide write controls.

The transcript UI displays:

- live two-line caption from `translation_interim.payload.caption`;
- final history records from `translation_final` and `GET /api/translations`;
- cancellation cleanup from `translation_interim_cancelled`.

The frontend must not synthesize business state from events when HTTP refresh is
safer. For speech interim captions, it may update the live caption directly by
`utterance_id` and `revision`.

`frontend/src/native/` provides one `NativeBridge` boundary. Browser sessions
use `WebNativeBridge`; Android WebView sessions use `AndroidNativeBridge`.
Android emits `smartdesk-native-event`. A `PROTOTYPE` result is displayed but
does not automatically check in. Only `VALIDATED` evidence is submitted
automatically; an explicit demo control may submit `PROTOTYPE`, and the backend
still rejects it unless its development-only gate is enabled. Every current
native event carries `schemaVersion`, `eventId`, `timestamp`, `type`, and
`data`; the frontend suppresses repeated event IDs.

## Android Tablet Integration

The Android module remains separately built and never imports FastAPI or React
business logic. Its production flow is:

```text
persisted seat/device/server/frontend configuration
  -> WebView /seat/{seatId}
  -> SmartDeskNative.startFaceVerification(personId)
  -> CameraX + ML Kit + alignment + MobileFaceNet
  -> smartdesk-native-event identity_status
  -> frontend policy gate
  -> POST /api/seats/{seatId}/identity-checkin + device token + event ID
  -> authenticated TabletDevice binding + durable idempotency record
  -> Person -> active Attendee
  -> existing SeatService.check_in
```

Android does not access SQLite. The backend never performs face inference.
Configuration, enrollment, diagnostics, and threshold calibration stay in the
local `android_tablet/diagnostic-web` fallback page.
Device configuration and face templates are encrypted at rest with
Android Keystore AES-GCM keys. The credential Bridge method is origin- and
seat-path restricted, and raw tokens never appear in device-info/config
responses. The frontend reads the tablet `serverBaseUrl` synchronously through
`SmartDeskNative.getDeviceInfo()` for HTTP and WebSocket connections. Explicit
`app-config.js` values continue to take precedence.

## Host Services (Screen Stream & Display Agent)

These are Windows host-side helpers, separate from the FastAPI backend and the
React frontend. They are described normatively in `docs/HOST_DISPLAY_CONTRACT.md`.

- `host_services/display_agent/`: a user-session FastAPI process bound to
  loopback `127.0.0.1:8766`. It performs local Win32/COM application switching
  (PowerPoint/SolidWorks/SmartDesk) via `pywin32` + `psutil`. It exposes
  `GET /status`, `POST /activate`, and `GET /health`. The backend never calls
  Win32; it reaches this agent only over validated loopback HTTP for status and
  for the authenticated Seat 1 activation relay. Desktop `/admin` still calls
  the loopback Agent directly.
- `host_services/screen_stream/`: a supervisor that starts MediaMTX and FFmpeg
  (`ddagrab` Desktop Duplication capture + H.264 encoding). FFmpeg publishes
  RTSP on `127.0.0.1:8554`; MediaMTX distributes via WebRTC on `:8889` (HTTP)
  and `:8189` (ICE UDP), with Control API on `:9997` and metrics on `:9998`.
  FFmpeg and MediaMTX are external deployment binaries, not committed to Git.

The Display Agent and screen-stream supervisor run in the interactive user
session (not Session 0). `start.bat` launches the Display Agent by default via
`ENABLE_DISPLAY_AGENT=true`; `ENABLE_SCREEN_STREAM=true` independently enables
the FFmpeg/MediaMTX supervisor.

## Gesture Controller Integration

The sibling `smartdesk_gesture_controller/` process owns camera recognition and
gesture modes. For an I Love You mode swipe it calls the loopback Display Agent
to activate `smartdesk`, `powerpoint`, or `solidworks`. A failed activation
restores the previous gesture mode and is exposed through the gesture status
WebSocket. The gesture process does not write the database or publish meeting
business events.

## Demo Data and Startup

`start.bat` starts backend and frontend for local demo. Demo data is controlled
by environment variables. When demo seed is enabled and the database is empty,
the backend creates an active meeting, seats, attendees, agenda items, an open
vote, service call, and translation history.

Runtime databases and logs are disposable local artifacts. Model data and audio
fixtures are not disposable.

## Testing Strategy

Backend:

- service/unit tests for business rules;
- WebSocket blackbox tests for speech protocol;
- model smoke tests gated by environment variables where required.

Frontend:

- typecheck and unit tests;
- Playwright E2E speech tests using PCM fixtures instead of a physical
  microphone.

Acceptance for the current demo requires:

- backend `pytest -q` passes;
- frontend typecheck, tests, build, and speech E2E pass;
- no dependency on removed or deprecated interface names;
- final speech text is persisted and queryable.
