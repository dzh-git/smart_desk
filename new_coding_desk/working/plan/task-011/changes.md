# Changes: Task-011

## Files
- [new] D:\learning\smart_desktop\smart-desk\backend\services\ws_event_bridge.py
- [new] D:\learning\smart_desktop\smart-desk\tests\test_ws_event_bridge.py (split: 383 lines)
- [new] D:\learning\smart_desktop\smart-desk\tests\test_desk_coordinator_run_async.py (extracted + EventBus tests)
- [mod] D:\learning\smart_desktop\smart-desk\backend\main.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\services\desk_coordinator.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\routers\checkin.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\routers\meetings.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\routers\votes.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\routers\service_calls.py

## Summary

### Initial implementation
Created the WebSocket EventBridge module that subscribes to all 15 EventBus events and broadcasts them to the appropriate WebSocket rooms. The bridge maps EventBus events 1:1 to WebSocket message types. The `register_ws_bridge()` function is called during the FastAPI lifespan startup, after `serial_svc.start()`. The `_run_async` helper bridges the sync EventBus handler context to the async WebSocket methods.

### Fixes (CR-001, CR-002, CR-003)

**CR-001 — Thread/event-loop mismatch:**
- Added `_loop` module-level variable to store the main asyncio event loop
- `register_ws_bridge()` captures `asyncio.get_running_loop()` at startup (gracefully handles missing loop)
- `_run_async()` now uses `asyncio.ensure_future()` when on the event loop thread, and `asyncio.run_coroutine_threadsafe()` with the stored main loop when called from a non-asyncio thread (e.g., `threading.Timer` callbacks)
- This prevents silent WebSocket delivery failures that occurred when `asyncio.run()` created a new loop incompatible with the original WebSocket transport

**CR-002 — Zero behavior coverage:**
- Added 10 behavior tests covering: meeting_id routing, broadcast-all-rooms fallback, checkin_prompt seat targeting, checkin_prompt broadcast fallback, get_or_create room creation, non-dict payload guard, WS type mapping verification, thread-safety of `_run_async` (both ensure_future and run_coroutine_threadsafe paths), and end-to-end publish-to-broadcast pipeline
- Added `_clear_event_bus()` helper to reset the singleton event_bus between tests (subscribe is not idempotent)

**CR-003 — No defensive payload check:**
- Added `isinstance(event.payload, dict)` guard at the start of `_make_ws_handler` handler
- Non-dict payloads (e.g., `None`) are silently ignored instead of crashing with `AttributeError`

### Fix (SR-001)

**SR-001 — Step 4 app-startup verification documented:**
- Executed `python -c "from backend.main import app; print('OK')"` — outputs OK, no import errors
- All 15 tests pass; app starts cleanly with bridge registered in lifespan

### Fix (CR-004)

**CR-004 — desk_coordinator._run_async thread-safety bug:**
- Replaced `asyncio.run(coro)` fallback with `asyncio.run_coroutine_threadsafe(coro, _main_loop)`
- Added `_main_loop` module variable and `set_main_loop()` function (mirrors ws_event_bridge pattern)
- `set_main_loop()` captures `asyncio.get_running_loop()` during FastAPI lifespan
- Added 3 new tests in `TestDeskCoordinatorRunAsync` class:
  - `test_ensure_future_on_main_loop`: verifies ensure_future path in asyncio context
  - `test_run_coroutine_threadsafe_from_other_thread`: verifies cross-thread scheduling
  - `test_raises_when_no_main_loop_set`: verifies clear RuntimeError when uninitialized
- Updated `main.py` lifespan to call `set_main_loop()` after `register_ws_bridge()`

### Fix (CR-005)

**CR-005 — test_ws_event_bridge.py exceeds 400-line project limit:**
- Extracted `TestDeskCoordinatorRunAsync` class (86 lines) from `test_ws_event_bridge.py` (was 473 lines)
- Created new file `tests/test_desk_coordinator_run_async.py` with the extracted class
- Both files now within the 400-line limit: test_ws_event_bridge.py = 383 lines, test_desk_coordinator_run_async.py = 164 lines

### Fix (SR-002)

**SR-002 — Bridge handles zero events in production (no EventBus publishers exist):**
- Modified `desk_coordinator._on_serial` to publish `seat_occupied`/`seat_vacant` events to EventBus instead of directly calling `room.broadcast()`
- Modified `_schedule_checkin_prompt` to publish `checkin_prompt` events to EventBus instead of directly calling `room.send_to_seat()`
- The ws_event_bridge handlers pick up these events and broadcast to WebSocket rooms via thread-safe `_run_async`
- Added `TestDeskCoordinatorEventPublish` test class with 2 integration tests verifying the full pipeline: desk._on_serial → EventBus publish → handler receives correct event

### Fix (CR-006, CR-007) — Full EventBus adoption

**CR-006 — desk_coordinator public async methods bypass EventBus:**
- Converted all 7 desk_coordinator public async methods from direct room.broadcast() to EventBus.publish():
  - on_vote_start → vote_started event
  - on_vote_close → vote_closed event
  - on_meeting_end → meeting_ended event
  - on_service_call → service_call_created event
  - on_speaker_seat → speaker_seat_set event
  - on_speaker_clear → speaker_seat_clear event
  - on_translation_result → translation_final event (includes is_final: True in payload)
- Removed unused ws_svc import from desk_coordinator.py
- Added 7 tests (TestDeskCoordinatorPublicMethodsPublish) verifying each method publishes to EventBus

**CR-007 — Router files call room.broadcast() directly:**
- checkin.py: replaced room.broadcast({"type": "check_in", ...}) with EventBus.publish(check_in)
- meetings.py: replaced ws_svc.get_or_create(...).broadcast({"type": "meeting_started", ...}) with EventBus.publish(meeting_started)
- votes.py: replaced 3 asyncio.run(ws_svc.get_or_create(...).broadcast(...)) calls with EventBus.publish(vote_started/vote_updated/vote_closed)
- service_calls.py: replaced asyncio.run(ws_svc.get_or_create(...).broadcast(...)) with EventBus.publish(service_call_created)
- Removed unused asyncio and ws_svc imports from votes.py and service_calls.py
- Bug fix: sync router functions previously used asyncio.run() from thread pool threads (creates new event loop, WebSocket messages silently lost). EventBus._run_async correctly uses asyncio.run_coroutine_threadsafe()

**EVENT_TO_WS_TYPE update to match frontend:**
- Changed WS type values to match frontend listeners (verified against SeatGrid.vue, VotingPanel.vue, ServicePanel.vue, TranslationPanel.vue, MeetingView.vue):
  - vote_started/vote_updated/vote_closed → "vote_update" (VotingPanel listens for vote_update)
  - service_call_created/resolved/cancelled → "service_update" (ServicePanel listens for service_update)
  - translation_final → "translation_result" (TranslationPanel listens for translation_result)

### Fix (CR-008) — main.py ws_endpoint bypasses EventBus for vote_cast and service_call

**CR-008 — main.py ws_endpoint broadcasts vote_cast/service_call directly instead of via EventBus:**
- `persist_vote_cast` (votes.py): Added `event_bus.publish(BaseEvent(name="vote_updated", ...))` after successful db.commit(). Publishes only on valid vote cast; invalid votes (nonexistent, closed, bad option) return None without publishing.
- `persist_service_call` (service_calls.py): Added `event_bus.publish(BaseEvent(name="service_call_created", ...))` after db.refresh(sc). Publishes on every service call creation.
- `main.py` ws_endpoint: Removed direct `await room.broadcast()` calls for `vote_cast` (was broadcasting `vote_update`) and `service_call` (was broadcasting `service_update`). The persist functions now publish to EventBus, and the ws_event_bridge registered at startup handles WebSocket broadcast centrally.
- `ping`/`pong` and `led_sync` remain as direct WebSocket operations (not mapped in EVENT_TO_WS_TYPE).
- New test file: `tests/test_persist_eventbus_publish.py` (3 tests, 149 lines) verifying:
  - Successful vote cast publishes `vote_updated` to EventBus
  - Invalid vote cast (nonexistent vote) does NOT publish
  - Successful service call creation publishes `service_call_created` to EventBus

## Files
- [new] D:\learning\smart_desktop\smart-desk\tests\test_persist_eventbus_publish.py (CR-008 tests)
