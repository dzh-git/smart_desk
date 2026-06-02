# Changes: Task-009

## Files
- [new] backend/services/vote_service.py
- [new] backend/services/service_call_service.py
- [new] tests/test_vote_service.py
- [new] tests/test_service_call_service.py
- [mod] backend/services/vote_service.py (CR-001-003, CR-005-006, CR-011)
- [mod] backend/services/service_call_service.py (CR-002-003, CR-005, CR-009)
- [mod] backend/repositories/service_call_repository.py (CR-009)
- [mod] tests/test_vote_service.py (CR-004, CR-007, CR-010, CR-012)
- [mod] tests/test_service_call_service.py (CR-005, CR-008, CR-012)
- [mod] tests/test_service_call_repository.py (CR-009, CR-013, CR-018)
- [mod] backend/repositories/service_call_repository.py (CR-018)
- [mod] backend/services/service_call_service.py (CR-018)
- [mod] tests/test_service_call_service.py (CR-019, CR-018, CR-020)
- [mod] backend/services/vote_service.py (CR-021, CR-022)
- [mod] tests/conftest.py (CR-020)

## Summary
**Round 1:** Implemented VoteService (vote CRUD, cast validation, close, statistics with anonymous/named distinction) and ServiceCallService (call CRUD, pending-per-seat enforcement, timeout auto-cancel). Both services publish events via EventBus. All 6 TDD-driven tests pass. Fixed one test ordering bug in test_resolve_then_cancel caused by repository's desc ordering of list_by_meeting.

**Round 2 (review fixes):** Fixed 4 code review issues:
- CR-001: Added meeting-scope validation in VoteService.close() via get_by_id(vote_id, meeting_id) before closing.
- CR-002: Removed unused `self.db = db` from both service constructors.
- CR-003: Added input validation (empty title/options in VoteService, valid service_types in ServiceCallService).
- CR-004: Changed weak assertion `>= 1` to `== 1` in test_cast_and_close.

**Round 3 (pending issues):** Fixed 6 remaining review issues:
- CR-005: Removed unused `db: Session` parameter from both service constructors and updated all callers.
- CR-006: Replaced ambiguous `return None` in cast() and close() with typed exceptions (VoteNotFoundError, VoteClosedError, InvalidVoteOptionError).
- CR-007: Added test_statistics_named covering the non-anonymous statistics branch with per-option voter ID lists.
- CR-008: Added test_cancel_expired covering timeout auto-cancel with event publishing verification.
- CR-009: Added meeting_id parameter to cancel_expired() in both service and repository for meeting-level scoping.
- CR-010: Enhanced test_statistics_anonymous with actual vote count assertions (results["A"]==1, results["B"]==0).

**Round 4 (spec review fixes):** Fixed 3 remaining pending issues:
- CR-011: Removed dead `if ok:` guard in VoteService.cast() — all failure paths raise exceptions so the guard was always True.
- CR-012: Added 9 missing error-path tests: 8 in test_vote_service.py (test_create_empty_title, test_create_whitespace_title, test_create_empty_options, test_cast_nonexistent_vote, test_cast_closed_vote, test_cast_invalid_option, test_close_nonexistent_vote, test_close_already_closed) and 1 in test_service_call_service.py (test_create_invalid_service_type).
- CR-013: Fixed weak assertion `>= 1` to `== 1` in test_service_call_repository.py test_cancel_expired.

**Round 5 (pending issue fixes):** Fixed 3 remaining pending issues:
- CR-014: Added `force_expire(call_id, seconds_ago)` method to ServiceCallRepository, eliminating the 2-level-deep test reach-through (`svc.repo.db.execute()`). Updated both service-level and repository-level test_cancel_expired to use the new public API.
- CR-015: Added `test_create_with_custom_text` to test_service_call_service.py verifying custom_text forwarding through the service layer.
- CR-016: Added typed exception classes (ServiceCallError, ServiceCallNotFoundError, DuplicatePendingCallError) to ServiceCallService. Updated create() to raise DuplicatePendingCallError, resolve()/cancel() to raise ServiceCallNotFoundError. Updated VoteService.get_statistics() to raise VoteNotFoundError instead of returning None. Added 4 new tests and updated 1 test for exception-based error handling.

**Round 6 (CR-017 fix):** Moved inline exception imports (`DuplicatePendingCallError`, `ServiceCallNotFoundError`) from inside test functions to module-level import in test_service_call_service.py, consistent with test_vote_service.py conventions and PEP 8.

**Round 7 (CR-018, CR-019 fixes):** Fixed 3 pending issues:
- CR-017: Confirmed already resolved — exception imports at module level. Updated Decision Reason.
- CR-018: Removed `meeting_id` parameter from `cancel_expired()` in both `ServiceCallService` and `ServiceCallRepository`, aligning with task spec signature `cancel_expired(self, timeout_seconds: int = 300)`. Updated both service-level and repository-level tests.
- CR-019: Yielded `scr` (ServiceCallRepository) from `sc_services` fixture as 4th value. `test_cancel_expired` now uses `scr.force_expire()` directly instead of reaching through `svc.repo.force_expire()`. All other tests unpack with `_` for the 4th value.

**Round 8 (CR-020, CR-021, CR-022 fixes):** Fixed 3 remaining pending issues:
- CR-020: Extracted `force_expire()` from production `ServiceCallRepository` into a standalone test utility `force_expire_service_call(db, call_id, seconds_ago)` in `tests/conftest.py`. Removed from production class. Updated both `test_service_call_service.py` and `test_service_call_repository.py` to import and use the conftest helper.
- CR-021: Removed dead `if v:` guard in `VoteService.close()`. After pre-validation raises exceptions for all failure paths, the repository `close()` cannot return None in this single-threaded architecture. The `vote_closed` event is now published unconditionally, consistent with how `cast()` publishes `vote_updated` unconditionally (per CR-011).
- CR-022: Removed `return True` from `VoteService.cast()`. Since all failure paths raise typed exceptions, the boolean return was vestigial and misled callers into a non-existent success/failure contract. Method now returns `None` implicitly, signaling callers to rely on exception handling.
