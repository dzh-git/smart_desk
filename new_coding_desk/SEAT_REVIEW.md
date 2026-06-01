# Seat Module Review

**Date**: 2026-06-01
**Scope**: `backend/services/seat_service.py`, `backend/repositories/seat_repository.py`, `backend/api/seats.py`, `backend/schemas/seat.py`, `backend/models/seat_state.py`, `backend/models/speaker_seat.py`, `backend/events/seat_events.py`, `tests/test_seat_service.py`
**Verdict**: 0 blocking, 4 non-blocking findings.

---

## 1. State Machine Legality ✅

### States

```
vacant | occupied_unchecked | checked_in
```

### Allowed Transitions

| Transition | Method | Guard |
|---|---|---|
| `vacant → occupied_unchecked` | `seat_occupied()` | `status != "vacant"` → raises `SEAT_OCCUPIED` |
| `occupied_unchecked → checked_in` | `check_in()` | `status == "vacant"` → raises `SEAT_NOT_OCCUPIED`; `status == "checked_in"` → raises `SEAT_ALREADY_CHECKED_IN` |
| `any → vacant` | `seat_vacant()` | None (idempotent: already-vacant returns early, no event) |

### Illegal Transitions Blocked

| Attempt | Blocked By | Error |
|---|---|---|
| `occupied_unchecked → occupied_unchecked` | `seat_occupied` guard | `SEAT_OCCUPIED` |
| `checked_in → occupied_unchecked` | `seat_occupied` guard | `SEAT_OCCUPIED` |
| `checked_in → checked_in` | `check_in` guard | `SEAT_ALREADY_CHECKED_IN` |
| `vacant → checked_in` | `check_in` guard | `SEAT_NOT_OCCUPIED` |

**Conclusion**: All legal transitions guarded. All illegal transitions blocked. 36 tests confirm state machine correctness including full lifecycle round-trip.

### NB-1: `check_in` falls through without explicit assert

`seat_service.py:162` — comment says `# status == "occupied_unchecked"` but no explicit `elif` or `assert`. If new state added, `check_in` would silently allow it. Low risk (3 states stable), but recommend:

```python
# Current
if seat.status == "vacant":
    raise ...
if seat.status == "checked_in":
    raise ...
# Fall-through assumes occupied_unchecked

# Better
if seat.status != "occupied_unchecked":
    raise ValidationError(
        f"Seat {seat_id} invalid state for check-in: {seat.status}",
        "INVALID_STATE",
    )
```

---

## 2. Multiple Speaker Seats ✅

**No risk of multiple speaker seats.** Mechanism:

1. `SpeakerSeat` model: `id = Column(Integer, primary_key=True, default=1)` — single-row table by design
2. `init_seats()`: checks `db.get(SpeakerSeat, 1)`, creates exactly one row if missing. Idempotent.
3. `get_speaker_seat()`: always `db.get(SpeakerSeat, 1)` — returns singleton row or raises `RuntimeError`
4. `set_speaker_seat()` / `clear_speaker_seat()`: mutate the **same** row, never insert new rows

**Only creation path** is `init_seats()` at startup. No API endpoint creates speaker_seat rows. No repository method inserts into speaker_seat.

### NB-2: `SpeakerSeat.id` default may confuse

`SpeakerSeat.id` has `default=1` but is a PK. SQLAlchemy won't auto-increment PKs with a default. If `init_seats()` is somehow bypassed and someone calls `SpeakerSeat()` without explicit `id=1`, behavior depends on SQLite dialect. Since `init_seats()` always passes `id=1` explicitly, this is safe. Consider removing `default=1` to avoid confusion — the only creation site (`init_seats()`) already passes `id=1`.

---

## 3. Event Publishing ✅

### 6 Event Types — All Published Correctly

| Event | Publisher Method | Published After DB Save | Payload | WS Broadcast |
|---|---|---|---|---|
| `seat_occupied` | `seat_occupied()` (L98-101) | ✅ | `{seat_id}` | ✅ |
| `checkin_prompt` | `seat_occupied()` (L102-105) | ✅ | `{seat_id}` | ✅ |
| `seat_vacant` | `seat_vacant()` (L129-132) | ✅ | `{seat_id}` | ✅ |
| `check_in` | `check_in()` (L167-172) | ✅ | `{seat_id, attendee_id}` | ✅ |
| `speaker_seat_set` | `set_speaker_seat()` (L200-203) | ✅ | `{seat_id}` | ✅ |
| `speaker_seat_clear` | `clear_speaker_seat()` (L220-223) | ✅ | `{}` | ✅ |

**DB-save-then-publish ordering** correct — if publish fails, DB is already consistent.

**No double-publish**: `seat_vacant` returns early when already vacant (L122-123), no event.

**All 6 registered** in `WebSocketEventHandler.BROADCAST_EVENTS` (L47-62). Registration at startup via `register_all()`.

### NB-3: `_publish` mutates event object in-place

`seat_service.py:62-66`:

```python
def _publish(self, event, meeting_id):
    if meeting_id is not None:
        event.meeting_id = meeting_id  # side-effect mutation
    self.event_bus.publish(event)
```

Works because `BaseEvent` is a mutable dataclass. If `BaseEvent` ever becomes `frozen=True`, this breaks. Consider passing `meeting_id` to event constructor instead:

```python
event = SeatOccupiedEvent(
    meeting_id=meeting_id,
    payload={"seat_id": seat_id}
)
```

### NB-4: Dead imports in `seat_service.py`

- `ConflictError` (L26) — imported, never used
- `SEAT_COUNT` (L29) — imported, never used

Remove to keep clean.

---

## 4. Router Layer Violations ✅

### Dependency Chain

```
Router (api/seats.py)
  └─→ SeatService (services/seat_service.py)
        └─→ SeatRepository (repositories/seat_repository.py)
              └─→ SQLAlchemy Session
```

### Router Check (`api/seats.py`)

| Check | Result |
|---|---|
| Direct `db.query()` call? | ❌ None |
| Direct Repository instantiation? | ❌ None |
| Direct `event_bus.publish()`? | ❌ None (import only for DI into Service) |
| Service method calls only? | ✅ All 5 endpoints |
| Error → ApiResponse conversion? | ✅ `NotFoundError`→404, `ValidationError`→400 |
| `response_model` typing? | ✅ Uses `ApiResponse[List[SeatStateResponse]]` etc. |

Route ordering correct: `/speaker` routes (L86, L93, L109) defined before `/{seat_id}/checkin` (L63) — prevents FastAPI from matching "speaker" as `seat_id`.

### Service Check (`seat_service.py`)

| Check | Result |
|---|---|
| Business logic in Repository? | ❌ None |
| Direct WS/HTTP calls? | ❌ None |
| EventBus used correctly? | ✅ Publish only, no subscribe |
| Extends BaseService? | ✅ |

### Repository Check (`seat_repository.py`)

| Check | Result |
|---|---|
| Business logic? | ❌ None (pure CRUD) |
| EventBus reference? | ❌ None |
| Extends BaseRepository? | ❌ No (valid — custom PK, singleton row) |
| Auto-updates `updated_at`? | ✅ In `save_seat()` and `save_speaker_seat()` |

---

## Summary

| Category | Finding | Severity |
|---|---|---|
| State Machine | `check_in` falls through without explicit state check | Non-blocking |
| Speaker Seat | `SpeakerSeat.id` default confusing | Non-blocking |
| Events | `_publish` mutates event in-place | Non-blocking |
| Code Quality | Dead imports (`ConflictError`, `SEAT_COUNT`) | Non-blocking |
| Router | No layer violations | — |
| Multiple Speaker Seats | Impossible | — |
| Event correctness | All 6 published, ordered, WS-registered | — |

**0 blocking issues. 4 non-blocking improvements suggested.**
