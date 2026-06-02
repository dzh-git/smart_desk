# Changes: Task-004

## Files
- [new] D:\learning\smart_desktop\smart-desk\backend\repositories\seat_repository.py
- [new] D:\learning\smart_desktop\smart-desk\tests\test_seat_repository.py

## Summary
Implemented SeatRepository with full seat state management (CRUD for seat_states table) and speaker seat persistence (speaker_seat single-row table, replacing in-memory _speaker_seats dict).

### Review fixes applied:
- CR-001: Added `VALID_STATUSES` set and `ValueError` validation in `update_seat` (following `MeetingRepository` pattern)
- CR-002: Added 3 edge case tests (non-existent seat_id, non-existent seat update, missing SpeakerSeat row)
- CR-003: Fixed return type annotations on SpeakerSeat methods from `-> SpeakerSeat` to `-> SpeakerSeat | None`
- CR-004: Added 2 edge case tests (`test_set_speaker_seat_when_no_row`, `test_clear_speaker_seat_when_no_row`) for SpeakerSeat methods on empty DB
- CR-005: Added `SeatRepository` import and `__all__` entry to `repositories/__init__.py`; added `test_import_from_repositories_package` TDD test

All 13 task-specific tests pass.
