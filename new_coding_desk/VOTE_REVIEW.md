# Vote Module Code Review

**Date:** 2026-06-01
**Branch:** `replace-speech-module`
**Reviewer:** Automated adversarial review
**Files reviewed:** 7 source files, 5 review dimensions

---

## 1. Executive Summary

The Vote module is **functional for single-user, human-paced meeting scenarios** but has structural deficiencies in concurrency safety and data integrity enforcement. The core logic (create, submit, close, statistics) is correctly organized around the Router->Service->Repository pattern. However, every multi-step operation relies on application-level check-then-act patterns with **no DB-level guard** — no unique constraints, no partial indexes, no `SELECT ... FOR UPDATE`. In a single-meeting-room context with ~10 seats, the practical risk of race conditions is low, but the module does not meet the robustness standard of its own documented schema (DATABASE_SCHEMA.md SS9) and should **not** be considered production-ready for a multi-tenant or high-concurrency deployment without the fixes listed below.

---

## 2. Review Scope

### Files Reviewed

| File | Lines | Role |
|------|-------|------|
| `backend/services/vote_service.py` | 211 | Business logic, rule enforcement, event publishing |
| `backend/api/votes.py` | 160 | HTTP routing, request/response mapping |
| `backend/models/vote.py` | 25 | ORM model for `votes` table |
| `backend/models/vote_record.py` | 22 | ORM model for `vote_records` table |
| `backend/repositories/vote_repository.py` | 73 | Data access for votes and vote_records |
| `backend/repositories/base.py` | 73 | Generic CRUD base class |
| `backend/database.py` | 35 | Engine, session, and `Base` configuration |
| `backend/events/event_bus.py` | 86 | In-process pub/sub event hub |
| `backend/events/vote_events.py` | 26 | Vote event dataclasses |
| `docs/DATABASE_SCHEMA.md` (SS9) | — | Schema specification (referenced, not reviewed in full) |

### Dimensions Checked

1. **Data Integrity & Schema Compliance** — Are DB constraints, uniqueness guarantees, and schema contracts enforced?
2. **Concurrency Safety** — Are TOCTOU races, dirty reads, and lost updates protected against?
3. **Business Rule Enforcement** — Do rules V1-V5 hold under all execution paths?
4. **Event System Correctness** — Are event publish/state-change orderings correct? Are events lost or duplicated?
5. **Error Handling & Robustness** — Are edge cases handled gracefully? Are inputs validated?

---

## 3. Findings by Dimension

### 3.1 Data Integrity & Schema Compliance

**Summary:** The ORM models do not enforce the uniqueness guarantees documented in DATABASE_SCHEMA.md. The `vote_records` table lacks the mandated `UNIQUE(vote_id, attendee_id)` constraint, and the `votes` table lacks a partial unique index to prevent multiple open votes. Application-level checks are the sole defense — and they are non-atomic.

| # | Severity | Title | Description |
|---|----------|-------|-------------|
| DI-1 | **HIGH** | Missing `UNIQUE(vote_id, attendee_id)` on `vote_records` | DATABASE_SCHEMA.md SS9 specifies this constraint ("one person, one vote"). `VoteRecord` model (`vote_record.py:14-21`) has no `UniqueConstraint`, no `unique=True` columns, no `__table_args__`. The live database created via `Base.metadata.create_all()` in `main.py` has no such index. |
| DI-2 | **HIGH** | No partial unique index prevents two open votes | `Vote` model (`vote.py:14-24`) has no index on `status WHERE status='open'`. `create_vote()` (`vote_service.py:58-66`) checks `get_open_vote()` in one DB round-trip then calls `create()` in another — non-atomic. Two concurrent POSTs can both observe zero open votes and both insert. |
| DI-3 | **MEDIUM** | No `FOREIGN KEY` enforcement on `meeting_id` | `database.py:16-19` does not issue `PRAGMA foreign_keys = ON`. SQLite FK enforcement is off by default. `Vote.meeting_id` (`vote.py:18`) and `VoteRecord.attendee_id` (`vote_record.py:19`) have `ForeignKey` annotations that are ignored at runtime. |
| DI-4 | **MEDIUM** | `json.loads(vote.options_json)` lacks error handling | `vote_service.py:183` calls `json.loads()` without try/except. Corrupted JSON in the database results in an unhandled `JSONDecodeError` and a raw 500. |

#### Detailed Analysis: DI-1 — Missing UNIQUE Constraint

The `VoteRecord` model at `vote_record.py:14-21`:

```python
class VoteRecord(Base):
    __tablename__ = "vote_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vote_id = Column(Integer, ForeignKey("votes.id"), nullable=False)
    attendee_id = Column(Integer, ForeignKey("attendees.id"), nullable=False)
    option = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
```

No `__table_args__`, no `UniqueConstraint`. Contrast with the documented requirement in DATABASE_SCHEMA.md SS9:

> 保证：一个人只能投一次 (Guarantee: one person can only vote once)

The application-layer upsert at `vote_service.py:128-138` is the only guard:

```python
existing = self.vote_repo.get_record(vote_id, attendee_id)   # SELECT
if existing:                                                   # CHECK
    existing.option = option
    self.vote_repo.save_record(existing)                       # UPDATE
else:
    self.vote_repo.create_record(...)                          # INSERT + COMMIT
```

Each request gets an independent `Session` from `get_db()` (`database.py:28-34`). Two concurrent requests for the same `(vote_id, attendee_id)` can both execute the SELECT (line 129) before either executes the INSERT (line 134), producing two rows.

**Fix:**

1. Add to `VoteRecord` model:
   ```python
   from sqlalchemy import UniqueConstraint
   __table_args__ = (UniqueConstraint("vote_id", "attendee_id", name="uq_vote_attendee"),)
   ```
2. Refactor `submit_vote()` to INSERT-first with IntegrityError catch:
   ```python
   try:
       self.vote_repo.create_record(vote_id=vote_id, attendee_id=attendee_id, option=option)
   except IntegrityError:
       self.db.rollback()
       existing = self.vote_repo.get_record(vote_id, attendee_id)
       existing.option = option
       self.vote_repo.save_record(existing)
   ```
3. For existing databases, run:
   ```sql
   CREATE UNIQUE INDEX IF NOT EXISTS uq_vote_attendee ON vote_records(vote_id, attendee_id);
   ```

#### Detailed Analysis: DI-2 — No Guard Against Multiple Open Votes

`create_vote()` at `vote_service.py:58-66`:

```python
existing = self.vote_repo.get_open_vote()   # line 59: SELECT ... WHERE status='open'
if existing is not None:                     # line 60: application-level check
    raise ConflictError(...)
vote = self.vote_repo.create(...)            # line 66: INSERT + COMMIT
```

The `get_open_vote()` at `vote_repository.py:27-29` performs a plain `SELECT ... WHERE status='open'` with no locking. The `create()` at `base.py:38-43` starts a new implicit transaction. Two concurrent sessions can both observe `None` and both proceed to INSERT.

**Fix:** Add a partial unique index (SQLite 3.8.0+, standard with Python 3.10+):
```sql
CREATE UNIQUE INDEX ix_single_open_vote ON votes(status) WHERE status = 'open';
```
Execute this as a raw DDL after `Base.metadata.create_all()` in `main.py`, since SQLAlchemy's `Index(..., postgresql_where=...)` parameter is PostgreSQL-only.

---

### 3.2 Concurrency Safety

**Summary:** The module has **three distinct TOCTOU race conditions** — in `create_vote()`, `submit_vote()`, and `close_vote()`. None use any form of locking (pessimistic or optimistic). SQLite's single-writer serialization narrows but does not close the race windows. Verified severity is lower than initially claimed because this is a single-meeting-room app with human-paced interactions, but the code quality gap is real.

| # | Severity | Title | Description |
|---|----------|-------|-------------|
| CS-1 | **HIGH** | Check-then-act in `create_vote()` enables duplicate open votes | `vote_service.py:59-66`: `get_open_vote()` (SELECT) and `create()` (INSERT+COMMIT) are not atomic. Two concurrent POSTs can both observe zero open votes and both insert. Violates business rule V1. |
| CS-2 | **MEDIUM** | TOCTOU in `submit_vote()` enables duplicate ballots | `vote_service.py:129-138`: `get_record()` (SELECT) and `create_record()` (INSERT+COMMIT) span separate implicit transactions with no lock. Two concurrent ballots from same attendee can both pass the None check. Violates rule V4. |
| CS-3 | **MEDIUM** | Ballot accepted after vote closed (V3 violation) | `vote_service.py:114`: status check reads `vote.status` in Session B's identity map. `close_vote()` in Session A can commit `status='closed'` between lines 114 and 132/134. Session B never refreshes the cached value and proceeds to persist a VoteRecord against a closed vote. |
| CS-4 | **LOW** | Concurrent `close_vote()` publishes duplicate events | `vote_service.py:158-169`: Two concurrent `close_vote()` calls can both read `status='open'`, both set it to `'closed'`, both commit (second is a no-op on data), and both publish `VoteClosedEvent`. |
| CS-5 | **LOW** | `submit_vote()` returns stale status after concurrent close | `vote_service.py:147`: returns the vote object read at line 111. If close happened between lines 111 and 147, the returned `vote.status` is `'open'` (stale in identity map) even though DB has `'closed'`. The API response at `votes.py:131` reads this stale status. |

#### Detailed Analysis: CS-3 — Ballot After Close

The race window spans `vote_service.py` lines 111 through 138:

```
Line 111: vote = self.get_vote(vote_id)          # SELECT, vote cached in session identity map
Line 114: if vote.status != "open": raise ...     # Reads cached attribute — no DB re-query
Line 121: options = json.loads(vote.options_json) # Reads cached attribute
Line 129: existing = self.vote_repo.get_record()  # Separate SELECT
Line 134: self.vote_repo.create_record()          # INSERT + COMMIT
```

Between line 114 and 134, a concurrent `close_vote()` in another session can:
1. Load the same vote (its own identity map)
2. Set `status = 'closed'`, `closed_at = datetime.now(timezone.utc)`
3. Call `self.vote_repo.save(vote)` which calls `self.db.commit()` — persisted to DB

Session B's identity map is **not invalidated** by Session A's commit (SQLAlchemy `expire_on_commit` only affects the committing session). Session B's `vote.status` remains `'open'` in memory, passes the guard at line 114, and the VoteRecord is persisted against a now-closed vote.

**Fix:** After the upsert, add `self.db.refresh(vote)` to reload from DB. But the proper fix is to add the `UNIQUE(vote_id, attendee_id)` constraint (DI-1) and re-check `vote.status` by re-querying within the same transaction as the upsert, rolling back if status changed.

**Verified severity downgrade (HIGH -> MEDIUM):** In a 10-seat physical smart desk, the practical likelihood of a human admin clicking "Close Vote" within the sub-second window of another attendee submitting a ballot is negligible. No data corruption or crash occurs — at worst, one extra VoteRecord against a closed vote inflates a tally by one.

---

### 3.3 Business Rule Enforcement

**Summary:** The five documented business rules (V1-V5) are nominally enforced in application code but lack corresponding DB-level guarantees. Rule enforcement is correct for the single-user, sequential case but degrades under any concurrency.

| # | Severity | Title | Description |
|---|----------|-------|-------------|
| BR-1 | **HIGH** | V1 ("Only one open vote") enforced only in application code | See CS-1/DI-2. No DB-level enforcement. |
| BR-2 | **MEDIUM** | V3 ("No voting after close") vulnerable to TOCTOU | See CS-3. Application-level check not synchronized with write. |
| BR-3 | **MEDIUM** | V4 ("One ballot per attendee") not enforced at DB level | See DI-1/CS-2. Upsert is non-atomic check-then-act. |
| BR-4 | **LOW** | `close_vote()` guard uses `== 'closed'` instead of `!= 'open'` | `vote_service.py:158`: `if vote.status == "closed"` accepts any non-closed value (e.g., future `'draft'` or `'pending'` status). Should reject unexpected states. |
| BR-5 | **MEDIUM** | No validation that `meeting_id` corresponds to an active meeting | `create_vote()` accepts any `meeting_id` without checking the meeting exists or is active. FK is not enforced at runtime (no `PRAGMA foreign_keys = ON`). |

#### Detailed Analysis: BR-4 — Weak Guard in close_vote()

```python
# vote_service.py:158
if vote.status == "closed":
    return vote  # idempotent
```

This only rejects already-closed votes. A vote with `status='pending'`, `'draft'`, or any other non-standard value (from a direct DB edit, future feature, or bug) passes through and is set to `'closed'` — silently masking the unexpected state.

**Fix:** Change to:
```python
if vote.status != "open":
    if vote.status == "closed":
        return vote  # idempotent
    raise ValidationError("Vote cannot be closed", "VOTE_NOT_CLOSABLE")
```

---

### 3.4 Event System Correctness

**Summary:** The event publishing pattern is well-structured with typed event dataclasses and a clean pub/sub bus. However, the **DB-commit-then-event-publish** ordering creates a consistency gap: if event publishing fails after the DB commit, the state change is persisted but subscribers never learn of it. The `EventBus.publish()` method (`event_bus.py:40-56`) catches handler exceptions individually, so a single failed handler does not block others — but a failure in the publish infrastructure itself (e.g., `self._subscribers` corrupted) would propagate uncaught.

| # | Severity | Title | Description |
|---|----------|-------|-------------|
| EV-1 | **MEDIUM** | DB commit before event publish — lost events on publish failure | `vote_service.py:66-79` (`create_vote`), `163-170` (`close_vote`): `self.vote_repo.create()`/`save()` calls `self.db.commit()` before `self.event_bus.publish()`. If publish() fails (infrastructure error), the DB is already mutated but no event fires. |
| EV-2 | **LOW** | No event payload schema enforcement | Event payloads are ad-hoc dicts (`vote_service.py:77`, `143`, `168`). No TypedDict, dataclass, or JSON Schema validation. Key renames break subscribers silently. |
| EV-3 | **LOW** | Event timestamp reflects construction time, not action time | `BaseEvent` (`base_event.py:23`) sets `timestamp` via `default_factory` at dataclass instantiation, which happens after `db.commit()` + `db.refresh()`. Under DB latency, the timestamp lags behind the actual business action. |
| EV-4 | **LOW** | `submit_vote` event payload omits voter identity | `vote_service.py:143`: payload is `{"vote_id": vote_id}` only. Observers cannot show "3 of 5 have voted" without a separate API call. |

#### Detailed Analysis: EV-1 — Commit-Before-Publish Ordering

All three state-mutating methods follow pattern:

```
DB write → db.commit() → event_bus.publish()
```

`EventBus.publish()` (`event_bus.py:40-56`) catches per-handler exceptions but does NOT wrap the entire method body in a try/except. If a failure occurs before handler iteration (e.g., `self._subscribers` is `None`, a `KeyError` in lookup, or memory exhaustion), the exception propagates to the service method, which has already committed to the DB.

**Fix (MVP-pragmatic):** Wrap each `publish()` call in a try/except that logs the failure:
```python
try:
    self.event_bus.publish(VoteStartedEvent(...))
except Exception:
    logger.exception("Failed to publish vote_started for vote %s", vote.id)
```
**Fix (robust):** Outbox pattern — write events to an `outbox_events` table in the same DB transaction, then an async worker publishes them.

---

### 3.5 Error Handling & Robustness

**Summary:** Error handling is adequate but incomplete. The service layer uses typed domain exceptions (`NotFoundError`, `ConflictError`, `ValidationError`) consistently, and the API layer (`votes.py`) maps them to appropriate HTTP status codes. However, there are unguarded operations that can produce raw 500 errors with no diagnostic context.

| # | Severity | Title | Description |
|---|----------|-------|-------------|
| ER-1 | **MEDIUM** | `json.loads(vote.options_json)` unguarded | `vote_service.py:121,183`: `json.loads()` has no try/except. Corrupted JSON in the DB causes `JSONDecodeError` -> raw 500. |
| ER-2 | **LOW** | `get_statistics()` silent skip of orphan records | `vote_service.py:189`: records whose `option` is not in the current `options_json` are silently skipped. `total_votes` (line 208) counts all rows but per-option counts exclude orphans — divergence with no warning. |
| ER-3 | **INFO** | Anonymity weakened at low `total_votes` | `vote_service.py:199`: `attendee_ids=None` for anonymous votes, but `total_votes` and per-option `count` are still exposed. With `total_votes=1`, the sole voter's choice is trivially inferable. This is inherent to small-population voting, not a code defect, but the API contract promises anonymity without qualification. |
| ER-4 | **LOW** | `json.loads()` in API layer duplicates service validation | `votes.py:53`: `_build_vote_response()` calls `json.loads(vote.options_json)` — the same parsing done in the service. A corrupted `options_json` crashes the response builder after the service operation already succeeded. |
| ER-5 | **LOW** | `submit_vote()` re-parses `options_json` on every ballot | `vote_service.py:121`: `json.loads(vote.options_json)` called on every ballot submission. Not a correctness issue, but could be cached on the Vote instance. |

#### Detailed Analysis: ER-1 — Unguarded JSON Parsing

Three call sites call `json.loads(vote.options_json)` without error handling:
- `vote_service.py:121` — option validation in `submit_vote()`
- `vote_service.py:183` — statistics computation in `get_statistics()`
- `votes.py:53` — response building in `_build_vote_response()`

The API's `submit_vote` endpoint (`votes.py:113-131`) catches `ValidationError` and `NotFoundError` only — `JSONDecodeError` falls through to FastAPI's default 500 handler.

**Fix:** Wrap in a helper:
```python
def _parse_options(vote: Vote) -> list[str]:
    try:
        return json.loads(vote.options_json)
    except json.JSONDecodeError:
        logger.error("Corrupted options_json for vote %s", vote.id)
        raise ValidationError("Vote options data is corrupted", "CORRUPTED_VOTE_OPTIONS")
```

---

## 4. Architecture Compliance

The Vote module follows the **Router -> Service -> Repository** pattern consistently, matching the Meeting module's architecture.

### Compliant Aspects (Verified Correct)

| Aspect | Evidence |
|--------|----------|
| **Router layer** is thin | `votes.py:38-159` — only request parsing, error mapping, and response building. No business logic. |
| **Service layer** owns business rules | `vote_service.py:32-37` class docstring lists V1-V5, all enforced in service methods. |
| **Repository layer** has no business logic | `vote_repository.py` extends `BaseRepository`, only CRUD queries. No EventBus access. |
| **Event publishing** only from Service | Events are published in `create_vote`, `submit_vote`, `close_vote` — all in `vote_service.py`, never in repository or router. |
| **Typed domain exceptions** | `NotFoundError`, `ConflictError`, `ValidationError` — consistent with the rest of the backend. |
| **Dependency injection via FastAPI** | `get_db()` (`database.py:28-34`) yields `Session`, service constructed per-request in `_service()` helper (`votes.py:39-40`). |

### Deviations from Ideal Pattern

1. **Repository methods independently commit** — `BaseRepository.create()` (`base.py:38-43`), `save()` (`base.py:63-67`), and `VoteRepository.create_record()` (`vote_repository.py:44-50`) all call `self.db.commit()`. This prevents the service layer from wrapping multiple repository operations in a single transaction. The Meeting module handles this better by having the service control transaction boundaries.

2. **Service returns ORM objects to the router** — `submit_vote()` returns a `Vote` ORM instance, and the router calls `_build_vote_response(vote, total)` which accesses ORM attributes. This is a minor leak of the persistence layer into the API layer, but consistent with how the Meeting module works.

---

## 5. Code Quality Notes

### Positive Observations

- **Well-documented business rules:** The class docstring (`vote_service.py:9-14`) lists all five rules (V1-V5), and each method's docstring references which rules it enforces. This makes the intent explicit and reviewable.
- **Consistent naming:** Methods follow a clear convention (`get_vote`, `create_vote`, `submit_vote`, `close_vote`). Repository methods mirror this (`get_open_vote`, `get_record`, `create_record`).
- **Clean event typing:** Each event is a named dataclass (`vote_events.py`) with a constant `event_name`, making event types grep-friendly.
- **Idempotent close:** `close_vote()` correctly handles repeated calls — the intent is sound even if the implementation guard is too permissive (BR-4).
- **File size:** All reviewed files are under 400 lines. `vote_service.py` is the largest at 211 lines, well within the project limit.

### Areas for Improvement

- **Repository commit granularity:** Each repository write method independently commits. This prevents atomic multi-table operations in the service layer. Consider a `flush_only` variant or moving commit control to the service.
- **Options JSON parsing:** Repeated `json.loads(vote.options_json)` calls at three call sites should be consolidated into a single helper with error handling.
- **Event payload typing:** Ad-hoc dicts at each call site invite drift between publisher and subscriber. Use typed payload objects.

---

## 6. Risk Assessment

| Dimension | Risk Level | Rationale |
|-----------|-----------|-----------|
| Data Integrity & Schema | **HIGH** | Missing DB constraints (DI-1, DI-2) are the root cause of all concurrency bugs. Application-level checks are non-atomic. Fix requires schema migration. |
| Concurrency Safety | **MEDIUM** | Three TOCTOU races exist (CS-1, CS-2, CS-3) but practical exploitability is low in a ~10-seat single-meeting-room context. SQLite serialized writes narrow race windows. |
| Business Rule Enforcement | **MEDIUM** | Rules V1, V3, V4 are vulnerable under concurrency with no DB-level backup. Rules V2 and V5 are correctly implemented. |
| Event System | **MEDIUM** | Commit-before-publish ordering (EV-1) creates a consistency gap. The gap is narrow (publish rarely fails) but the consequence (permanently lost event) is severe. |
| Error Handling | **LOW** | Unguarded `json.loads` is the main gap. Otherwise, error handling is consistent and uses typed exceptions with proper HTTP status code mapping. |

### Risk Matrix (Application Context)

For the current deployment context (single meeting room, ~10 seats, LAN, SQLite embedded):
- **Data corruption risk:** LOW — race windows are sub-millisecond, human-paced interactions rarely overlap
- **UI inconsistency risk:** MEDIUM — stale status responses (CS-5) and inflated vote counts (DI-1/CS-2) can cause user confusion
- **Event loss risk:** LOW — `publish()` is in-process and synchronous; failure is very rare

For a future multi-tenant or PostgreSQL deployment:
- **Data corruption risk: HIGH** — PostgreSQL's MVCC allows true concurrent writes, widening all race windows significantly

---

## 7. Conclusion

The Vote module is **functional and well-structured** for its current single-meeting-room deployment context. The Router->Service->Repository architecture is correctly implemented, business rules are documented and nominally enforced, and the event system is cleanly typed.

However, the module **should not be considered production-ready for broader deployment** without the following fixes:

### Critical Fixes (Must Do)

1. **Add `UNIQUE(vote_id, attendee_id)` constraint** to `VoteRecord` model (`vote_record.py`) and refactor `submit_vote()` to INSERT-first with IntegrityError fallback. This fixes DI-1 and CS-2 simultaneously.
2. **Add partial unique index** `WHERE status = 'open'` on `votes` table to prevent multiple open votes at the DB level. This fixes DI-2 and CS-1.
3. **Enable `PRAGMA foreign_keys = ON`** in `database.py` engine configuration. This fixes DI-3.

### Recommended Fixes (Should Do)

4. **Wrap `json.loads(vote.options_json)`** in a helper with try/except that raises `ValidationError` on malformed JSON (ER-1, ER-4).
5. **Add try/except around `event_bus.publish()`** calls in the service layer to log failures (EV-1).
6. **Tighten `close_vote()` guard** from `== 'closed'` to `!= 'open'` with explicit error for unexpected states (BR-4).
7. **Validate `meeting_id`** in `create_vote()` against an active meeting (BR-5).

### Nice-to-Have

8. Add typed event payload objects (EV-2).
9. Capture event timestamp at method entry, not after DB commit (EV-3).
10. Add a privacy threshold for anonymous vote statistics (ER-3).

### Overall Verdict

**Conditionally approved** for current single-meeting-room deployment. The module is safe for human-paced, low-concurrency use. Apply the critical fixes (items 1-3) before any multi-tenant or internet-facing deployment. The architecture and code quality are a solid foundation — the gaps are in robustness, not in design.
