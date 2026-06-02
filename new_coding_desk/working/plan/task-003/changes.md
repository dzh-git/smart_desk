# Changes: Task-003

## Files
- [mod] D:\learning\smart_desktop\smart-desk\backend\repositories\__init__.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\repositories\meeting_repository.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\repositories\attendee_repository.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\models.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\schemas.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\routers\service_calls.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\main.py
- [mod] D:\learning\smart_desktop\smart-desk\tests\test_meeting_repository.py
- [mod] D:\learning\smart_desktop\smart-desk\tests\test_attendee_repository.py

### Third Review Fixes (2 Pending Issues Resolved)

**CR-008: has_history ServiceCall check scoped by attendee_id (not seat_id proxy)**
- Added `attendee_id` column (nullable FK to attendees.id) to `ServiceCall` model in `models.py`
- Updated `has_history()` in `attendee_repository.py` to filter by `ServiceCall.attendee_id == attendee_id`
- Added `attendee_id` field to `ServiceCallCreate` and `ServiceCallOut` schemas in `schemas.py`
- Updated `create_service_call` router to store `attendee_id` from request data
- Updated `persist_service_call` helper to look up attendee by seat+meeting and set `attendee_id`
- Updated seed data in `main.py` with explicit `attendee_id` values
- Updated existing test `test_has_history_returns_true_when_has_service_call` to use `attendee_id`
- Added regression test `test_has_history_service_call_is_attendee_scoped`

**CR-009: get_active() now returns deterministic results**
- Added `.order_by(Meeting.created_at.desc())` to `get_active()` query in `meeting_repository.py`
- Added regression test `test_get_active_deterministic_when_multiple_active`

## Summary

### Initial Implementation
MeetingRepository and AttendeeRepository already implemented with full CRUD methods. Models already include `started_at` and `ended_at` columns on Meeting. All 9 original tests pass.

### Review Fixes (7 Pending Issues Resolved)

**CR-001: datetime.utcnow() deprecated**
- Replaced `datetime.utcnow()` with `datetime.now(timezone.utc)` in `meeting_repository.py` `update_status` method
- Added `timezone` import

**CR-002: Missing test coverage for 10 methods**
- Added 9 MeetingRepository tests: get_by_id (found + missing), delete (success + missing), add_agenda, list_agendas (ordered + empty), remove_agenda (success + wrong meeting)
- Added 11 AttendeeRepository tests: get_by_id (found + missing), get_by_seat (found + empty), count_by_meeting, count_checked_in, delete (success + missing), has_history for missing attendee, has_history with VoteRecord, has_history with ServiceCall
- Total: 30 tests (15 MeetingRepository + 15 AttendeeRepository)

**CR-003: update_status validation**
- Added `VALID_STATUSES` class attribute (`{"pending", "active", "finished"}`)
- `update_status` now raises `ValueError` for invalid status strings before modifying database
- Added test `test_update_status_rejects_invalid`

**CR-004: Fragile test ordering**
- Changed `test_list_all_returns_desc_order` to create Meeting objects directly with explicit `created_at` timestamps (1 month apart)
- Eliminates dependency on system clock timing; ordering is fully deterministic

**CR-005: has_history VoteRecord not meeting-scoped**
- Added `Vote` import to `attendee_repository.py`
- Modified `has_history` VoteRecord query to JOIN `Vote` and filter by `Vote.meeting_id == meeting_id`
- Added test `test_has_history_vote_record_is_meeting_scoped` verifying cross-meeting isolation

**CR-006: has_history checked_in early return not meeting-scoped**
- Added `if a.meeting_id != meeting_id: return False` guard in `has_history` after fetching attendee
- Added test `test_has_history_checked_in_is_meeting_scoped` verifying cross-meeting isolation for checked-in attendees
- Total: 32 tests (15 MeetingRepository + 17 AttendeeRepository)

**SR-001: test_list_all_returns_desc_order lost ordering verification**
- Restored positional ordering assertions: `meetings[0].title == "Second"` and `meetings[1].title == "First"`
- Replaced set-based comparison that did not verify descending order

**CR-007: models.py still uses deprecated datetime.utcnow in 5 column defaults**
- Added `timezone` import to models.py
- Replaced all 5 `datetime.utcnow` column defaults with `lambda: datetime.now(timezone.utc)`:
  - `Meeting.created_at`, `ServiceCall.created_at`, `TranslationRecord.created_at`
  - `SeatState.updated_at` (default + onupdate), `SpeakerSeat.updated_at` (default + onupdate)

**CR-008: has_history ServiceCall check scoped by attendee_id**
- See Third Review Fixes above

**CR-009: get_active() deterministic ordering**
- See Third Review Fixes above

### Fourth Review Fix (1 Pending Issue Resolved)

**CR-010: list_by_meeting() now returns deterministic results**
- Added `.order_by(Attendee.id)` to `list_by_meeting()` query in `attendee_repository.py`
- Added regression test `test_list_by_meeting_returns_id_order` verifying 3 attendees returned sorted by id ascending
- Total: 35 tests (16 MeetingRepository + 19 AttendeeRepository)

### Fifth Review Fix (1 Pending Issue Resolved)

**CR-011: update_status preserves started_at/ended_at on re-activation/re-completion**
- Added `is None` guard to `started_at` and `ended_at` assignments in `update_status()`
- Timestamps now record the FIRST state transition, not the most recent call
- `if status == "active" and m.started_at is None:` — preserves original activation time
- `if status == "finished" and m.ended_at is None:` — preserves original completion time
- Added regression tests: `test_update_status_preserves_started_at_on_re_activation`, `test_update_status_preserves_ended_at_on_re_completion`
- Total: 37 tests (18 MeetingRepository + 19 AttendeeRepository)
