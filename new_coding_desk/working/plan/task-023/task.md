# Task 023: Multi-Admin Support Verification + Meeting Ended Hardware Event Guard

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, Vue 3, WebSocket

## Task Objective

Address two remaining P1/P2 items: (B5) Ensure multi-admin tablet support by making all write operations idempotent, and (C7) Guard against TOF hardware events after meeting ended — log but don't change business state. Also ensure `GET /api/votes/{id}/statistics` is accessible to Seat tablets (C9).

This is Task 23 of 26.

---

**Files:**
- Modify: `D:\learning\smart_desktop\smart-desk\backend\services\seat_service.py`
- Modify: `D:\learning\smart_desktop\smart-desk\backend\main.py` (serial handler)
- Modify: `D:\learning\smart_desktop\smart-desk\backend\routers\votes.py`

- [ ] **Step 1: Guard serial events when no active meeting (migration C7)**

In the `_on_serial` callback in `main.py` (from Task 021), the guard already exists:
```python
active = mr.get_active()
if not active:
    get_logger().info(f"Ignoring {msg_type} for seat {seat_id}: no active meeting")
    return
```
Verify this handles the `meeting_ended` scenario correctly. When a meeting ends, `status` becomes `finished`, so `get_active()` returns `None`, and subsequent TOF events are logged but not acted upon.

- [ ] **Step 2: Ensure all write operations are idempotent (migration B5)**

Audit the Service-layer write operations:

In `MeetingService.create`: Session creates new record each time → idempotent by nature.

In `SeatService.checkin`: Returns `None` if already checked in → idempotent.

In `SeatService.set_speaker_seat`: Always sets to new value → idempotent.

In `VoteService.cast`: Uses `UNIQUE(vote_id, attendee_id)` constraint → idempotent.

In `VoteService.create`: Creates new vote each time → fine (multiple admins can create multiple votes but only one open at a time).

In `ServiceCallService.create`: Returns `None` if seat already has pending call → idempotent.

No additional changes needed — the Service layer already implements idempotency through validation checks.

- [ ] **Step 3: Ensure vote statistics accessible to Seat tablets (migration C9)**

In `backend/routers/votes.py`, the `get_vote_statistics` endpoint has no admin restriction check. Verify there's no middleware or guard blocking Seat access:

```python
@router.get("/{vote_id}/statistics")
def get_vote_statistics(vote_id: int, db: Session = Depends(get_db)):
    # No admin check — accessible to both Admin and Seat tablets
    svc = _get_service(db)
    stats = svc.get_statistics(vote_id)
    if not stats:
        raise HTTPException(404, detail="VOTE_NOT_FOUND")
    return _ok(stats)
```

This is already correct — no changes needed.

- [ ] **Step 4: Handle seat_id 0 (admin tablet) in WS endpoint**

In `main.py` ws_endpoint, admin tablets connect with `seat=0`. The current code handles this via `desk.register_seat(seat, meeting_id)` which is no longer available (moved to `desk_coordinator`). Since the EventBus bridge broadcasts without needing seat registration, the `register_seat`/`unregister_seat` calls are no longer needed:

```python
@app.websocket("/ws/{meeting_id}")
async def ws_endpoint(ws: WebSocket, meeting_id: int, seat: int = Query(0)):
    try:
        async for msg in ws_svc.handle(ws, meeting_id, seat):
            # ... handle messages without desk.register_seat/unregister_seat
    except Exception:
        pass
```

Remove the `register_seat`/`unregister_seat` and `registered` flag logic.

- [ ] **Step 5: Remove CORS middleware (Nginx same-origin)**

In `backend/main.py`, remove:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
This is per spec decision Q24: Dev uses Vite proxy, Prod uses Nginx same-origin. No CORS needed.

- [ ] **Step 6: Verify app starts**

```bash
cd D:\learning\smart_desktop\smart-desk && python -c "from backend.main import app; print('OK')"
```
