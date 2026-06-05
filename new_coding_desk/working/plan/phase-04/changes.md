# Phase 04: 管理端数据接入与 WebSocket 实时同步 — Changes

## Overview

Phase 04 replaces the mock-data-driven admin dashboard with a real API-connected
implementation. WebSocket integration enables real-time UI updates without
manually refreshing.

## Files Created

### `frontend/src/api/resources.ts`
Resource-specific API methods using the existing fetch client (`apiGet`).
Each method corresponds to one backend endpoint:
- `fetchActiveMeeting()` → `GET /api/meetings/active`
- `fetchSeats()` → `GET /api/seats`
- `fetchSpeakerSeat()` → `GET /api/seats/speaker`
- `fetchActiveVote()` → `GET /api/votes/active`
- `fetchVoteStatistics(voteId)` → `GET /api/votes/{id}/statistics`
- `fetchAgendas(meetingId)` → `GET /api/meetings/{id}/agendas`
- `fetchAttendees(meetingId)` → `GET /api/meetings/{id}/attendees`
- `fetchServiceCalls(meetingId)` → `GET /api/service-calls?meeting_id={id}`
- `fetchTranslations(meetingId)` → `GET /api/translations?meeting_id={id}`

### `frontend/src/hooks/useWebSocket.ts`
WebSocket lifecycle hook:
- Constructs URL as `ws[s]://host/ws/{meeting_id}?seat=0`
- Auto-reconnects every 3 seconds after disconnect
- Calls `onEvent` callback for each parsed server message
- Never sends client-side messages
- Returns connection status (`connecting` | `connected` | `disconnected`)
- Cleans up timers and socket on unmount

### `frontend/src/hooks/useAdminData.ts`
Admin data orchestration hook:
- Three-phase initialisation:
  1. Parallel: active meeting, seats, speaker seat, active vote
  2. If meeting exists: parallel fetch of agendas, attendees, service calls, translations
  3. If active vote exists: fetch statistics
- WebSocket event → HTTP re-fetch bridge (all events trigger a full re-fetch)
- Returns: loading, error, meeting, seats (10), speakerSeatId, attendees,
  agenda, activeVote, serviceCalls, translations, connection, noMeeting, refresh

### `frontend/src/__tests__/admin.test.tsx`
12 integration tests covering:
- API call path correctness (resources.test.ts covers path verification)
- Active meeting data flow
- No-meeting state (no meeting-dependent API calls)
- Always 10 seats regardless of backend data
- Speaker seat highlight
- Error state with retry button
- No mock behaviours (no Done/vote buttons)
- WebSocket URL construction (ws:// and wss://)
- WebSocket event list completeness
- Disconnected overlay absence when connected

### `frontend/src/api/__tests__/resources.test.ts`
10 unit tests for the resource API methods, verifying correct URL paths
and query parameter formatting.

## Files Modified

### `frontend/src/types.ts`
Replaced old mock-heavy types (`MeetingState`, `SeatState`, `AgendaItem`,
`Vote`, `ServiceRequest`, `TranscriptEntry` etc.) with clean UI types:
- `ConnectionStatus` — `"connecting" | "connected" | "disconnected"`
- `AppMode` — `"admin" | "seat"`
- `SeatDisplay` — seatId, attendeeName, attendeeTitle, isCheckedIn, isVacant, isSpeaker

### `frontend/src/api/adapters.ts`
- Moved `SeatDisplay` type to `types.ts`
- Import `SeatDisplay` from `../types`

### `frontend/src/components/shared.tsx`
- Updated `MeetingStatusBadge` for API status values: `"active"`, `"pending"`, `"finished"`

### `frontend/src/components/AdminHeader.tsx`
- Accepts simple props (`title`, `meetingStatus`, `connection`, etc.) instead of
  full `MeetingState`

### `frontend/src/components/ConferenceTable.tsx`
- Uses `SeatDisplay` instead of old `Seat` type
- Removed `stateConfig` (no more `speaking`, `muted`, `away` states)
- Supports only: vacant (dashed border), occupied_unchecked (amber bg),
  checked_in (white bg), speaker highlight (emerald ring + mic badge)
- Uses `UserCheck` icon and proper initials for occupied seats

### `frontend/src/components/AgendaPanel.tsx`
- Removed progress bar, completion tracking, duration, Chinese titles
- Shows agenda titles sorted by `sort_order`
- Empty state when no agenda items

### `frontend/src/components/VotePanel.tsx`
- Rewritten for read-only `VoteStatistics`
- Removed all voting interaction (`onVote`, `myVote`, click handlers)
- Shows results as percentage bars with count labels

### `frontend/src/components/ServicePanel.tsx`
- Removed `onResolve`/Done button
- Accepts `ServiceCall[]` from API with `seatNameMap` for attendee names
- Shows status badges (Pending/Resolved/Cancelled)
- Service type icons and colouring preserved

### `frontend/src/components/TranscriptPanel.tsx`
- Uses `TranslationRecord[]` from API with `seatNameMap` for speaker names
- Shows source_lang tag, source_text, translated_text
- Removed mock-only `isActive`/`showZh` props
- Timestamps from `created_at`

### `frontend/src/components/AdminDashboard.tsx`
- Major rewrite: uses `useAdminData` hook for all data
- Loading state, error state (with retry), waiting-for-meeting state
- Disconnected overlay when `connection === "disconnected"`
- Removed `setState`, `handleVote`, `handleResolveRequest` mock functions
- Metric cards computed from real data (elapsed, checked-in, speaker, pending)

### `frontend/src/components/SeatTablet.tsx`
- Simplified to placeholder for Phase 05
- Accepts only `seatId` and `onSwitchToAdmin` props

### `frontend/src/App.tsx`
- Removed `INITIAL_STATE` import
- No `MeetingState` state management
- Renders `AdminDashboard` by default
- `SeatTablet` render path kept for Phase 05

### `frontend/src/mockData.ts`
- Updated to valid TypeScript — exports `FIXTURE_SEAT_DISPLAYS` fixture

### `frontend/src/__tests__/App.test.tsx`
- Updated for real API flow (fetch mocks)
- Added: loading state, error state, no-meeting state
- Fixed seat count test to use `getAllByText`

## Phase 04 Review Fixes

### 1. Backend WebSocket thread-safety (`backend/websocket/event_handler.py`)
- **Problem:** FastAPI synchronous routes run in thread-pool workers without a
  running asyncio event loop. `asyncio.get_running_loop()` raised `RuntimeError`,
  causing broadcasts to be silently skipped.
- **Fix:** Added `capture_loop()` classmethod called at startup in lifespan.
  When `__call__` detects no running loop, it uses
  `loop.call_soon_threadsafe()` on the captured main loop to schedule the
  broadcast. Added duplicate registration guard via `_registered_events` set.

### 2. Backend event loop capture (`backend/main.py`)
- Added `WebSocketEventHandler.capture_loop()` call in the lifespan startup,
  before `register_all()`, to capture the main asyncio event loop.

### 3. Backend WebSocket integration tests (`tests/test_websocket_integration.py`)
- **Created 5 tests** using `TestClient` in context-manager mode:
  - `test_connected_event_on_connect` — client receives "connected" on WS open
  - `test_seat_occupied_event_via_dev_api` — HTTP dev occupy → WS event
  - `test_seat_vacant_event_via_dev_api` — HTTP dev vacate → WS event
  - `test_service_call_created_event` — HTTP service call → WS event
  - `test_multiple_clients_receive_broadcast` — 2 WS clients both receive events

### 4. Vote statistics error handling (`frontend/src/hooks/useAdminData.ts`)
- **Problem:** When `fetchVoteStatistics` failed, the hook caught the error and
  silently constructed fake zero-result statistics, hiding the failure.
- **Fix:** Added `hasActiveVote: boolean` and `voteStatsError: string | null`
  to `AdminData`. When statistics fail, `activeVote` remains `null` and
  `voteStatsError` carries the error message to the UI.
- `VotePanel` updated to show "Vote statistics unavailable" with error message
  and retry button when `hasActiveVote` is true but `activeVote` is null.

### 5. Frontend WebSocket tests (`frontend/src/__tests__/admin.test.tsx`)
- Replaced hand-written string/array tests with real behavior tests using a
  trackable `MockWebSocket` (`wsInstances` array):
  - `creates WS connection with correct meeting ID and seat=0`
  - `triggers HTTP re-fetch when seat_occupied event is received`
  - `triggers HTTP re-fetch when meeting_started event is received`
- Added vote stats error test: verifies "Vote statistics unavailable" shown,
  and no fake "0 votes cast" text appears.

### 6. Deferred issues (`working/deferred-issues.md`)
- Added item #8: "No auto-detect when new meeting starts while in waiting
  state" with suggested polling or lobby WS channel.

## Phase 04 Review Round 2 Fixes

### 7. Test database isolation (`tests/conftest.py`, 4 test files)
- **Problem:** `test_dev_api.py`, `test_service_calls_router.py`, `test_votes_router.py`,
  and `test_websocket_integration.py` imported `engine` from `backend.database`
  directly, causing `Base.metadata.drop_all/create_all` to operate on the real
  `smart_desk.db`.
- **Fix:** `conftest.py` module-level code creates a temp file-based SQLite engine
  and overrides `backend.database.engine` / `backend.database.SessionLocal` before
  any test module is imported. Also overrides `backend.main.engine` /
  `backend.main.SessionLocal` so the lifespan uses the test DB. Registers a
  `get_db` dependency override on the FastAPI app. An autouse `_reset_db` fixture
  drops/recreates tables per test. The real `smart_desk.db` hash is verified
  unchanged before and after the full test suite.
- **Files changed:**
  - `tests/conftest.py` — merged legacy fixtures + new DB override
  - `tests/test_dev_api.py` — removed `reset_state` fixture, import from conftest
  - `tests/test_service_calls_router.py` — same
  - `tests/test_votes_router.py` — same
  - `tests/test_websocket_integration.py` — same, uses `TEST_ENGINE` directly

### 8. VotePanel onRetryStats (`frontend/src/components/AdminDashboard.tsx`)
- Passed `onRetryStats={refresh}` to `VotePanel` so clicking Retry in the
  vote statistics error state triggers a full re-fetch.
- Added test: "retry button re-fetches vote statistics on click" — mocks
  statistics to fail once, succeed on retry, verifies UI transitions from
  error to statistics.

### 9. WebSocket reconnect full initialization (`frontend/src/hooks/useWebSocket.ts`)
- Added `firstConnectDoneRef` to detect reconnections (subsequent `onopen`
  events after the first successful connect). On reconnection, fires
  `onEvent("reconnected", ...)` which triggers a full HTTP re-fetch in
  `useAdminData` via the existing `handleWSEvent → doFetch` path.
- Added test: "triggers full re-initialization after WS reconnect" — closes
  the WebSocket, waits for the 3-second reconnect timer, verifies HTTP call
  count increases after reconnect.

## Verified

- `npm run typecheck` — passes
- `npm run lint` — 0 errors, 4 pre-existing warnings
- `npm test -- --run` — **43 tests**, 5 test files, all pass
- `npm run build` — builds in ~1.9s
- `npm run dev` — Vite server starts on localhost:5173
- `pytest -q` — **139 tests**, all pass
- `smart_desk.db` hash — unchanged before/after tests (SHA256 matches)
