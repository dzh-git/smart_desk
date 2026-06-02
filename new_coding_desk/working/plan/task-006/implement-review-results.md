# Implement Review Results: Task-006

## Spec Review Issues

### SR-001: cancel_expired uses naive datetime.utcnow() causing timezone mismatch with model
- Status: Resolved
- Description: In `service_call_repository.py`, the `cancel_expired` method uses `datetime.utcnow()` (returns a naive datetime without tzinfo) to compute the cutoff. When `.timestamp()` is called on a naive datetime, Python interprets it as local time, not UTC. Meanwhile, `ServiceCall.created_at` is defined with `datetime.now(timezone.utc)` (timezone-aware UTC) in models.py line 96. The comparison `sc.created_at.timestamp() < cutoff` mixes two different timezone interpretations: `sc.created_at.timestamp()` correctly yields a UTC timestamp, but `datetime.utcnow().timestamp()` yields a local-time-interpreted timestamp. On a machine in UTC+8, this makes the cutoff appear ~8 hours in the future, causing `cancel_expired` to rarely or never detect actually-expired pending calls. The fix is to replace `datetime.utcnow()` with `datetime.now(timezone.utc)` to match the model's timezone convention, or use `datetime.utcnow().replace(tzinfo=timezone.utc)`.
- Decision Reason:

## Code Review Issues

### CR-001: TranslationRepository.upsert always inserts, never updates — misleading method name
- Status: Resolved
- Description: `TranslationRepository.upsert()` (translation_repository.py:11-22) performs a plain INSERT every time — it does not check for an existing record to update. Methods named `upsert` imply idempotent "update or insert" semantics. If a caller invokes this twice with identical parameters, they get duplicate rows instead of one updated row. This is a `create`, not an `upsert`, and the misleading name will cause bugs when consumers assume upsert guarantees.
- Decision Reason:

### CR-002: ServiceCall model status comment contradicts actual status values used in code
- Status: Resolved
- Description: `models.py:94` declares `status = Column(String(20), default="pending")  # pending / acknowledged / completed`. However, `ServiceCallRepository` (service_call_repository.py:44,53,72) writes only `"pending"`, `"resolved"`, and `"cancelled"` — the statuses `"acknowledged"` and `"completed"` appear nowhere in the codebase. A developer reading the model comment would believe these are valid statuses and may write code that never matches any real record, or store statuses no other code handles. The comment must match the implemented status workflow.
- Decision Reason:

### CR-003: test_cleanup_expired still uses deprecated datetime.utcnow() after SR-001 fix
- Status: Resolved
- Description: SR-001 replaced all production uses of `datetime.utcnow()` with `datetime.now(timezone.utc)` to avoid timezone misinterpretation. However, `test_translation_repository.py:40` still uses `datetime.utcnow()` to construct the old date injected into the DB. While this test currently passes because SQLite stores both as naive strings, the pattern is fragile: if the test were ever run against a timezone-aware database, or if `cleanup_expired` were changed to do Python-side comparison (as `cancel_expired` does), the naive datetime from `utcnow()` would fail comparison against `cleanup_expired`'s timezone-aware cutoff. Tests should model the same timezone discipline as production code.
- Decision Reason:

### CR-004: Identical db_session fixture duplicated in both test files
- Status: Resolved
- Description: `test_service_call_repository.py:10-17` and `test_translation_repository.py:10-17` define identical `db_session` fixtures (create in-memory SQLite engine, create all tables, create a Meeting, yield session and meeting_id, close). This duplication means any future change to the fixture (e.g., adding a second required table, switching to a different DB URL) must be applied in both places. As more repository tests are added across the project, this pattern will compound. A shared `conftest.py` should hold this fixture.
- Decision Reason:

### CR-005: cancel_expired filters in Python instead of SQL — inconsistent with cleanup_expired
- Status: Resolved
- Description: `service_call_repository.py:59-77` (`cancel_expired`) loads ALL pending ServiceCall records into Python memory, then loops to filter by `created_at < cutoff` with manual tzinfo normalization. In contrast, `translation_repository.py:54-60` (`cleanup_expired`) — implemented in the same task — correctly pushes the time filter to SQL via `TranslationRecord.created_at < cutoff`, which SQLAlchemy handles correctly by stripping tzinfo from the bound parameter. The comment on lines 66-67 justifies the Python-side approach with tzinfo concerns, but `cleanup_expired` proves this concern is unfounded: SQLAlchemy's parameter binding handles naive-vs-aware datetime conversion for SQLite automatically. This creates inconsistency between two similar methods within the same task, makes `cancel_expired` unnecessarily memory-bound, and the Python-side loop is ~100 lines of unnecessary code. The fix: strip tzinfo from the cutoff, add `ServiceCall.created_at < cutoff_naive` to the query filter, and remove the Python loop and tzinfo normalization.
- Decision Reason:

### CR-006: No DB-level unique constraint on translation_records for upsert safety
- Status: Resolved
- Description: `TranslationRepository.upsert()` (`translation_repository.py:11-34`) checks for an existing record in Python before deciding to insert or update. However, `TranslationRecord` in `models.py:100-112` has no `UniqueConstraint` on the lookup columns (`meeting_id`, `seat_id`, `source_lang`, `target_lang`, `source_text`). Two concurrent requests could both pass the Python-side existence check, both proceed to INSERT, and create duplicate rows — violating the upsert idempotency guarantee. Adding `UniqueConstraint('meeting_id', 'seat_id', 'source_lang', 'target_lang', 'source_text')` to `TranslationRecord` would make the DB enforce this at the schema level, and the upsert could use `INSERT ... ON CONFLICT UPDATE` or catch `IntegrityError` for a true atomic upsert.
- Decision Reason:

### CR-007: Missing test coverage for several repository methods introduced by this task
- Status: Resolved
- Description: The following methods introduced by this task have zero test coverage: `ServiceCallRepository.list_by_meeting`, `ServiceCallRepository.get_pending_all`, `ServiceCallRepository.create` with `custom_text` parameter, `ServiceCallRepository.resolve` on a nonexistent ID (returns None), `ServiceCallRepository.cancel` on a nonexistent ID (returns None), `TranslationRepository.list_by_meeting_seat`, `TranslationRepository.delete_by_meeting`, `TranslationRepository.cleanup_expired` with no expired records (returns 0), and `TranslationRepository.upsert` with empty string source_text/translated_text. These are all production code paths that could contain bugs (e.g., `delete_by_meeting` returning 0 for a valid meeting with records, `list_by_meeting_seat` returning wrong ordering). The task spec only required 7 tests, but production-readiness demands exercising the full public API surface of both repositories.
- Decision Reason:

### CR-008: cancel_expired strips tzinfo from cutoff — inconsistent with cleanup_expired and model defaults
- Status: Resolved
- Description: `service_call_repository.py:62` strips tzinfo from the cutoff (`cutoff.replace(tzinfo=None)`) before using it in the SQL WHERE clause. This is inconsistent with `cleanup_expired` in `translation_repository.py:57`, which passes the timezone-aware `cutoff` directly to the filter. Both model columns (`ServiceCall.created_at` at models.py:96 and `TranslationRecord.created_at` at models.py:114) use `datetime.now(timezone.utc)` as their default — a timezone-aware datetime. SQLAlchemy's SQLite DateTime type preserves the timezone offset in the stored string representation (e.g., `"2026-06-03 10:00:00+00:00"`), so `cancel_expired`'s naive parameter is compared against timezone-aware column strings while `cleanup_expired` compares same-format strings. The comment on line 61 ("SQLite stores naive datetimes") is misleading — SQLite stores whatever string SQLAlchemy's DateTime type adapter produces, which includes the tz offset when the Python datetime is tz-aware. Additionally, the test `test_cancel_expired` at `test_service_call_repository.py:45` injects a naive datetime via raw SQL (`.replace(tzinfo=None) - timedelta(...)`), while the test `test_cleanup_expired` at `test_translation_repository.py:43` injects a timezone-aware datetime — the two tests use different datetime formats, masking the production inconsistency. Fix: remove `.replace(tzinfo=None)` from `cancel_expired`, pass `cutoff` directly like `cleanup_expired` does. Update `test_cancel_expired` to inject timezone-aware datetimes (remove `.replace(tzinfo=None)`) to match the model default and test real production behavior.
- Decision Reason: Removed `.replace(tzinfo=None)` from `cancel_expired`, now passes timezone-aware `cutoff` directly to SQL filter, consistent with `cleanup_expired`. Updated test to inject timezone-aware datetime (removed `.replace(tzinfo=None)`). All 16 tests pass.

### CR-009: TranslationRepository.upsert SELECT-then-INSERT pattern is not atomic despite UniqueConstraint
- Status: Resolved
- Description: `translation_repository.py:14-34` (`upsert`) performs a SELECT to check for an existing record, then either UPDATEs the found record or INSERTs a new one. Even though `models.py:102-105` adds a `UniqueConstraint` to prevent duplicate rows, the SELECT-then-INSERT pattern is not atomic: two concurrent requests can both pass the existence check (line 14-20), both proceed to INSERT (line 26-33), the first INSERT succeeds, and the second raises an unhandled `IntegrityError` from the UniqueConstraint. The caller receives a 500 error instead of a graceful upsert. While SQLite's single-writer serialization makes this race unlikely in practice, the code is architecturally unsound and would break if the backend were ever switched to a concurrent database (PostgreSQL). Fix: either use SQLAlchemy's `INSERT ... ON CONFLICT DO UPDATE` (supported by SQLite 3.24+ via the `sqlalchemy.dialects.sqlite.insert().on_conflict_do_update()` dialect), or catch `IntegrityError` in the INSERT path and retry with SELECT+UPDATE.
- Decision Reason: Replaced SELECT-then-INSERT pattern with atomic `sqlite_insert(...).on_conflict_do_update(index_elements=[...], set_=...)`. SQLite dialect does not support `constraint` parameter (PostgreSQL only), so used `index_elements` with column name strings. All 16 tests pass.
