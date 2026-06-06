# Deferred Issues

Non-blocking issues logged during development that do **not** block the v1.0 demo release. Each entry explains why it is safe to defer and suggested future improvements.

> **Final phase status (v1.0):** 9 items remain deferred. All are cosmetic, UX-nice-to-have, or low-impact optimizations. None affect the core demo flow.

---

### 1. ESLint `react-refresh/only-export-components` warnings in `shared.tsx`

**File:** `frontend/src/components/shared.tsx`  
**Warning:** "Fast refresh only works when a file only exports components. Use a new file to share constants or functions between components"

**Details:** `shared.tsx` exports 4 React components (`ConnectionBadge`, `MeetingStatusBadge`, `EmptyState`, `LoadingState`, `DisconnectedOverlay`, `SectionCard`) alongside 3 pure utility functions (`formatTime`, `formatDuration`, `timeAgo`) and 1 custom hook (`useClock`). The Fast Refresh plugin cannot guarantee hot-reload correctness for mixed-type exports.

**Impact:** None on build, typecheck, or runtime. In development, React Fast Refresh may fall back to a full page reload when these utility-only files change alongside component files. Users won't notice.

**Suggested fix:** Split pure functions and hooks into `src/hooks.ts` and `src/utils.ts`. Estimated effort ~15 min. Suitable for any phase with a refactoring window.

---

### 2. `lucide-react` excluded from Vite's optimizeDeps

**File:** `frontend/vite.config.ts`  
**Setting:** `optimizeDeps.exclude: ['lucide-react']`

**Details:** The Vite config excludes `lucide-react` from dependency pre-bundling. This was likely done to work around a known Vite issue with barrel-export icon libraries. It slightly increases cold-start time on `npm run dev` (~100–200 ms) and may delay HMR updates for icon changes (irrelevant since we don't modify node_modules).

**Impact:** Minor cold-start penalty only. No effect on build output.

**Suggested fix:** Remove the exclude entry once Vite 5's deps optimizer handles `lucide-react` natively. Test with a clean cache to confirm. Suitable for any future maintenance phase.

---

### 3. No SVG favicon file

**File:** `frontend/index.html` (line 5) references `/vite.svg`  
**Reality:** No `public/vite.svg` exists; no `vite.svg` at `frontend/` root.

**Details:** The favicon link points to a missing file. Browsers will silently fall back to no favicon. No console error, no runtime impact.

**Impact:** Cosmetic only — browser tab shows no favicon on dev or build.

**Suggested fix:** Either add `public/vite.svg` (a simple SVG icon) or remove the `<link>` line from `index.html`. Suitable for any phase, or skip entirely.

---

### 4. Test environment has 34s jsdom setup overhead

**Note:** The Vitest `jsdom` environment takes ~34 s to initialize on first run (cold cache). Subsequent runs are faster.

**Impact:** CI pipeline will see ~45 s for the test step on first run. Acceptable for a single-test baseline; will become more noticeable as test count grows.

**Suggested fix:** Split test runs in CI with `--no-cache` or move to a lighter environment if tests don't need a full DOM. Worth revisiting when test suite grows beyond ~20 files.

---

### 5. WebSocket full refresh on every event (Phase 04)

**File:** `frontend/src/hooks/useAdminData.ts`  
**Issue:** All WebSocket events (`seat_occupied`, `vote_updated`, etc.) trigger a full HTTP re-fetch of all admin resources.

**Details:** Per `docs/WEBSOCKET_PROTOCOL.md` §14, individual events should only refresh the affected resource (e.g. `seat_occupied` → refresh seats only). The current implementation uses a catch-all full refresh, which is correct but wasteful (6 extra HTTP calls per event).

**Impact:** Low — the backend endpoints are lightweight. Under high-frequency events (e.g. rapid translation_final) the extra requests add up.

**Suggested fix:** Map events to specific refresh functions (refreshSeats, refreshVote, etc.) in Phase 06 or later optimization window.

---

### 6. No auto-detect when new meeting starts while in "waiting for meeting" state (Phase 04)

**File:** `frontend/src/hooks/useAdminData.ts`  
**Issue:** When the admin dashboard shows "Waiting for Meeting" (no active meeting exists), the user must click the "Refresh" button to discover a newly started meeting. The frontend does not poll or receive a WebSocket event in this state because no WebSocket is connected (there's no meeting_id to connect to).

**Details:** The backend does not broadcast `meeting_started` events to clients that aren't yet connected to a meeting room. When the admin view has `noMeeting=true`, there's no WebSocket to receive real-time notifications. The user must manually refresh.

**Suggested fix (Phase 07 or later):**
  1. Backend: Add a system-wide broadcast room or a dedicated polling endpoint for "any meeting started".
  2. Frontend: Periodically poll `GET /api/meetings/active` every 15-30 seconds when `noMeeting` is true.
  3. Or: Use the heartbeat / retry mechanism in the WS to attempt connecting to meeting_id=0 as a "lobby" channel that receives system-wide events.

**Workaround:** The "Refresh" button on the waiting screen provides a manual fallback.

---

### 7. SeatTablet — no loading skeleton for service call operations

**File:** `frontend/src/components/SeatTablet.tsx`  
**Issue:** When service calls are being created or cancelled, only a spinner on the button is shown without a brief status message.

**Impact:** Low — operations typically complete in < 1 second.

**Suggested fix:** Add a brief toast or status indicator overlay for service operations. Suitable for any future UX polish phase.

---

### 8. SeatTablet voting — attendee ID resolution by name is fragile

**File:** `frontend/src/components/SeatTablet.tsx`  
**Issue:** The `voteSubmission` useMemo matches attendee by name (`a.name === myAttendeeName`) which breaks if two attendees share the same name.

**Details:** The SeatData hook does not expose the attendee ID for the current seat's checked-in attendee. The name-based lookup is a workaround.

**Impact:** Low — attendees in a meeting typically have unique names. Only fails with duplicate names.

**Suggested fix:** Expose `seatAttendeeId` directly from `useSeatData` by scanning attendees for the seat_id match. Suitable for any phase.

---

### 9. Disconnected overlay "Retry Now" vs WebSocket reconnect (Phase 04)

**File:** `frontend/src/components/SeatTablet.tsx`  
**Issue:** The disconnected overlay's "Retry Now" button triggers an HTTP refresh, but does not explicitly re-trigger WebSocket reconnection.

**Details:** The WebSocket hook's auto-reconnect handles reconnection, but "Retry Now" gives the user a misleading sense of reconnecting when it only re-fetches HTTP data.

**Impact:** Low — after WS reconnects, the default refresh event triggers a full HTTP re-fetch anyway.

**Suggested fix:** Add a "Reconnect" action that closes and reopens the WebSocket, or rename the button to "Refresh Data".

---

### 10. No stale-interim cleanup if translation_final/cancelled never arrives

**File:** `frontend/src/hooks/useAdminData.ts`, `frontend/src/hooks/useSeatData.ts`  
**Issue:** If a `translation_interim` event is received but no matching `translation_final` or `translation_interim_cancelled` follows (e.g., connection lost mid-utterance, or backend crash), the interim entry remains in the UI indefinitely.

**Impact:** Low — the interim text is visually distinct (italic, dimmed, spinner) so it's clear it's not final. A page refresh or new meeting clears all interims. The real-time translation use case means users see text appear and disappear normally.

**Suggested fix (Phase 09 or later):**
  1. Add a stale-interim timeout (e.g., 30 s without update → auto-remove).
  2. On WebSocket reconnect, clear all interims (they belong to a past connection epoch).

---

### 11. SeatTablet transcript section previously hidden when empty; now shows empty state

**File:** `frontend/src/components/SeatTablet.tsx`  
**Issue:** Before Phase 7, the SeatTablet hid the entire "Bilingual Transcript" section when there were no translations (`{translations.length > 0 && (...)}`). Now the TranscriptPanel is always rendered, showing the "No transcript yet" empty state.

**Impact:** Low — the empty state is informative and matches the AdminDashboard behaviour. Users see a placeholder instead of nothing, which is better for discoverability.

**Suggested fix:** None required — this is an intentional alignment with the AdminDashboard design. Revert to hidden-if-empty only if users find the empty state distracting.

---

### 12. `test_same_key_reconnect_generates_increasing_ids` flakes on utterance_id sequence

**File:** `tests/test_speech_stream_service.py`  
**Issue:** The test `TestUtteranceIdUniqueness::test_same_key_reconnect_generates_increasing_ids` expects `utt_1_1_000001` but when run after other tests that have already generated sequence IDs for (meeting=1, seat=1), the sequence starts at a higher number (e.g., 000016).

**Details:** The `_utterance_sequences` counter in `SpeechStreamService` is module-level and persists across tests within the same process. When test ordering is `[other tests that use (1,1)] → [this test]`, the counter has already advanced past 000001. In full-suite runs the test passes (different ordering); in targeted runs it may fail.

**Impact:** Low — only affects `pytest -k` or targeted test file runs. Full suite (`pytest -q`) passes. Not a production issue.

**Suggested fix:** Either (a) reset `SpeechStreamService._utterance_sequences` in a pytest fixture, or (b) parameterize the expected value dynamically. Suitable for any maintenance phase.