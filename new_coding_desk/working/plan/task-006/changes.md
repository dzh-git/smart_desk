# Changes: Task-006

## Files
- [new] D:\learning\smart_desktop\smart-desk\backend\repositories\service_call_repository.py
- [new] D:\learning\smart_desktop\smart-desk\backend\repositories\translation_repository.py
- [new] D:\learning\smart_desktop\smart-desk\tests\test_service_call_repository.py
- [new] D:\learning\smart_desktop\smart-desk\tests\test_translation_repository.py
- [new] D:\learning\smart_desktop\smart-desk\tests\conftest.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\models.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\repositories\service_call_repository.py (SR-001 fix + CR-005 fix)
- [mod] D:\learning\smart_desktop\smart-desk\backend\repositories\translation_repository.py (SR-001 fix + CR-001 fix)
- [mod] D:\learning\smart_desktop\smart-desk\tests\test_service_call_repository.py (CR-004 refactor + CR-007 coverage: 6 new tests)
- [mod] D:\learning\smart_desktop\smart-desk\tests\test_translation_repository.py (CR-003 fix + CR-004 refactor + CR-007 coverage: 4 new tests)

## Summary
Added three new columns to ServiceCall model (custom_text, cancel_reason, resolved_at). Implemented ServiceCallRepository with full CRUD and TranslationRepository with upsert and cleanup. All 16 repository tests pass.

### SR-001 Fix (from previous round)
Replaced `datetime.utcnow()` with `datetime.now(timezone.utc)` in resolve, cancel_expired, and cleanup_expired.

### CR-001 Fix: TranslationRepository.upsert now actually upserts
Changed upsert() from plain insert to real upsert: checks for existing record, updates translated_text if found, inserts new otherwise.

### CR-002 Fix: ServiceCall status comment
Updated status comment from `pending / acknowledged / completed` to `pending / resolved / cancelled`.

### CR-003 Fix: datetime.utcnow() in test_cleanup_expired
Replaced `datetime.utcnow()` with `datetime.now(timezone.utc)` in test.

### CR-004 Fix: Shared db_session fixture
Extracted duplicate db_session fixture into shared tests/conftest.py.

### CR-005 Fix: cancel_expired SQL filtering (this round)
Refactored `cancel_expired` to push time filtering from Python loop to SQL WHERE clause (`ServiceCall.created_at < cutoff_naive`), consistent with `cleanup_expired`. Removed ~20 lines of Python-side tzinfo normalization and manual looping.

### CR-006 Fix: UniqueConstraint on TranslationRecord (this round)
Added `UniqueConstraint('meeting_id', 'seat_id', 'source_lang', 'target_lang', 'source_text')` to `TranslationRecord.__table_args__` for DB-level upsert safety.

### CR-007 Fix: Test coverage (this round)
Added 9 new tests: `test_create_with_custom_text`, `test_list_by_meeting`, `test_get_pending_all`, `test_resolve_nonexistent`, `test_cancel_nonexistent`, `test_list_by_meeting_seat`, `test_delete_by_meeting`, `test_cleanup_expired_no_expired`, `test_upsert_empty_strings`.

### CR-008 Fix: cancel_expired tzinfo inconsistency (this round)
Removed `.replace(tzinfo=None)` from `cancel_expired` — now passes timezone-aware `cutoff` directly to SQL filter, consistent with `cleanup_expired`. Updated `test_cancel_expired` to inject timezone-aware datetime (removed `.replace(tzinfo=None)`) to match model default.

### CR-009 Fix: TranslationRepository.upsert atomicity (this round)
Replaced SELECT-then-INSERT pattern with atomic `sqlite_insert(...).on_conflict_do_update(index_elements=[...], set_=...)`. Uses SQLite's native `INSERT ... ON CONFLICT DO UPDATE` for true atomic upsert, eliminating race condition between SELECT and INSERT.
