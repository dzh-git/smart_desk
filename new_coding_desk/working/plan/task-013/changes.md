# Changes: Task-013

## Files
- [new] `D:\learning\smart_desktop\smart-desk\backend\routers\seats.py`
- [mod] `D:\learning\smart_desktop\smart-desk\backend\main.py`
- [new] `D:\learning\smart_desktop\smart-desk\tests\test_seats_router.py`
- [mod] `D:\learning\smart_desktop\smart-desk\backend\services\service_call_service.py`
- [mod] `D:\learning\smart_desktop\smart-desk\backend\repositories\service_call_repository.py`
- [del] `D:\learning\smart_desktop\smart-desk\backend\routers\checkin.py`

## Summary
Replaced `backend/routers/checkin.py` with `backend/routers/seats.py`. The new router:
- Uses `/api/seats` prefix instead of `/api/checkin`
- Enforces pre-assigned attendee requirement (no anonymous auto-create)
- Uses `SeatService` for checkin logic via `SeatService.checkin()` which validates seat state ("occupied_unchecked"), attendee existence, and cross-seat conflicts
- Provides speaker seat endpoints at `/api/seats/speaker`
- Uses unified response format `{"success": True, "message": "OK", "data": ...}`

In `main.py`:
- Swapped `checkin` router import for `seats`
- Swapped `app.include_router(checkin.router)` for `app.include_router(seats.router)`
- Removed `persist_vote_cast` and `persist_service_call` imports (replaced with direct Service calls)
- Added `event_bus` import
- Updated WebSocket handler: `vote_cast` uses `VoteService` directly; `service_call` uses `ServiceCallService` directly
- Updated `debug_simulate` endpoint to also update DB `SeatState` via `SeatService` (necessary for checkin to succeed since `SeatService.checkin()` requires DB seat status "occupied_unchecked", not just in-memory state)

## Review Issue Fixes (Session 2)

- **CR-001**: Added `attendee_id` parameter to `ServiceCallRepository.create()` and `ServiceCallService.create()`. Updated WebSocket `service_call` handler in main.py to resolve attendee via seat+meeting lookup and pass `attendee_id` to track who requested each service.
- **CR-002**: `DELETE /api/seats/speaker` now raises `HTTPException(400, "NO_ACTIVE_MEETING")` when no active meeting exists, symmetric with `POST /api/seats/speaker`.
- **CR-003**: Wrapped `VoteService.cast()` call in WebSocket handler with `try-except VoteError` to prevent uncaught exceptions from closing the WebSocket connection on bad votes.
- **CR-004**: Removed duplicate `AttendeeRepository(db)` in `checkin()` endpoint; reuses `svc.attendee_repo` instead, eliminating redundant DB lookups.
