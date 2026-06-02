# Task 011: WebSocket EventBridge — Wire EventBus to WebSocket Broadcast

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Create the WebSocket EventBridge that subscribes to all EventBus events and broadcasts them to the appropriate WebSocket rooms. This replaces the direct `ws_svc.broadcast()` calls scattered across `desk_coordinator.py` and routers. The bridge maps EventBus events 1:1 to WebSocket messages.

This is Task 11 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\backend\services\ws_event_bridge.py`
- Modify: `D:\learning\smart_desktop\smart-desk\backend\main.py` (register bridge in lifespan)
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_ws_event_bridge.py`

- [ ] **Step 1: Create the WS EventBridge module**

```python
# backend/services/ws_event_bridge.py
"""WebSocket EventBridge — subscribes to EventBus events and broadcasts them via WebSocket."""
from __future__ import annotations
import asyncio
from backend.services.event_bus import event_bus
from backend.services.ws_service import ws_svc


# Event name → WS message type (1:1 mapping from spec)
EVENT_TO_WS_TYPE = {
    "seat_occupied": "seat_occupied",
    "seat_vacant": "seat_vacant",
    "checkin_prompt": "checkin_prompt",
    "check_in": "check_in",
    "speaker_seat_set": "speaker_seat_set",
    "speaker_seat_clear": "speaker_seat_clear",
    "meeting_started": "meeting_started",
    "meeting_ended": "meeting_ended",
    "vote_started": "vote_started",
    "vote_updated": "vote_updated",
    "vote_closed": "vote_closed",
    "service_call_created": "service_call_created",
    "service_call_resolved": "service_call_resolved",
    "service_call_cancelled": "service_call_cancelled",
    "translation_final": "translation_final",
}


def _run_async(coro):
    """Run coroutine from sync context — cross-platform safe."""
    try:
        loop = asyncio.get_running_loop()
        asyncio.ensure_future(coro)
    except RuntimeError:
        asyncio.run(coro)


def _make_ws_handler(event_name: str):
    """Create a handler that broadcasts an EventBus event to WebSocket."""
    def handler(event):
        ws_type = EVENT_TO_WS_TYPE.get(event_name, event_name)
        meeting_id = event.payload.get("meeting_id")
        if not meeting_id:
            # Try to derive meeting_id from context (some events may not carry it)
            # For events without meeting_id, broadcast to all rooms
            for room in ws_svc.rooms.values():
                _run_async(room.broadcast({
                    "type": ws_type,
                    "payload": event.payload,
                }))
            return

        room = ws_svc.get_or_create(meeting_id)
        # For checkin_prompt, send only to the target seat
        if event_name == "checkin_prompt":
            seat_id = event.payload.get("seat_id")
            if seat_id:
                _run_async(room.send_to_seat(seat_id, {
                    "type": ws_type,
                    "payload": event.payload,
                }))
                return
        _run_async(room.broadcast({
            "type": ws_type,
            "payload": event.payload,
        }))
    return handler


def register_ws_bridge():
    """Register all EventBus→WS handlers. Call once at startup."""
    for event_name in EVENT_TO_WS_TYPE:
        event_bus.subscribe(event_name, _make_ws_handler(event_name))
```

- [ ] **Step 2: Write test**

```python
# tests/test_ws_event_bridge.py
import pytest
from backend.services.event_bus import event_bus, BaseEvent
from backend.services.ws_event_bridge import register_ws_bridge, EVENT_TO_WS_TYPE


def test_all_events_mapped():
    """Verify all 15 spec events are mapped."""
    assert len(EVENT_TO_WS_TYPE) == 15
    expected = {
        "seat_occupied", "seat_vacant", "checkin_prompt", "check_in",
        "speaker_seat_set", "speaker_seat_clear",
        "meeting_started", "meeting_ended",
        "vote_started", "vote_updated", "vote_closed",
        "service_call_created", "service_call_resolved", "service_call_cancelled",
        "translation_final",
    }
    assert set(EVENT_TO_WS_TYPE.keys()) == expected


def test_register_bridge_does_not_raise():
    """Verify bridge registration succeeds."""
    register_ws_bridge()  # Should not raise
```

Run: `pytest tests/test_ws_event_bridge.py -v`
Expected: PASS

- [ ] **Step 3: Register bridge in main.py lifespan**

In `backend/main.py` lifespan function, add after `serial_svc.start()`:
```python
from backend.services.ws_event_bridge import register_ws_bridge
register_ws_bridge()
```

- [ ] **Step 4: Verify app starts cleanly**

Run:
```bash
cd D:\learning\smart_desktop\smart-desk && python -c "from backend.main import app; print('OK')"
```
Expected: OK (no import errors)
