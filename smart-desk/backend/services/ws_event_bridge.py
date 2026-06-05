"""WebSocket EventBridge — subscribes to EventBus events and broadcasts them via WebSocket."""
from __future__ import annotations
import asyncio

from backend.services.event_bus import event_bus
from backend.services.ws_service import ws_svc

# Event name → WS message type (mapped to match frontend WS listeners).
# Multiple event names may map to the same WS type when the frontend uses
# a single handler for related events (e.g. VotingPanel listens for
# "vote_updated" regardless of whether the event is vote_started/vote_updated/vote_closed).
EVENT_TO_WS_TYPE = {
    "seat_occupied": "seat_occupied",
    "seat_vacant": "seat_vacant",
    "checkin_prompt": "checkin_prompt",
    "check_in": "check_in",
    "speaker_seat_set": "speaker_seat_set",
    "speaker_seat_clear": "speaker_seat_clear",
    "meeting_started": "meeting_started",
    "meeting_ended": "meeting_ended",
    "vote_started": "vote_updated",
    "vote_updated": "vote_updated",
    "vote_closed": "vote_updated",
    "service_call_created": "service_call_created",
    "service_call_resolved": "service_call_resolved",
    "service_call_cancelled": "service_call_cancelled",
    "translation_final": "translation_final",
    "recording_stop": "recording_stop",
}

# Reference to the main event loop captured at startup.
# Used by _run_async to schedule WebSocket operations from non-asyncio threads
# (e.g. threading.Timer callbacks) via asyncio.run_coroutine_threadsafe().
_loop: asyncio.AbstractEventLoop | None = None


def _run_async(coro):
    """Schedule a coroutine for execution, thread-safe.

    - If called from the event loop thread: uses asyncio.ensure_future (fire-and-forget).
    - If called from another thread: uses asyncio.run_coroutine_threadsafe()
      with the stored main loop to safely cross the thread boundary.
      WebSocket transports are bound to their accepting loop and cannot be
      used from a different loop.
    """
    try:
        loop = asyncio.get_running_loop()
        asyncio.ensure_future(coro)
    except RuntimeError:
        if _loop is None:
            raise RuntimeError(
                "WS EventBridge not initialized: no main loop stored. "
                "Call register_ws_bridge() first."
            )
        asyncio.run_coroutine_threadsafe(coro, _loop)


def _make_ws_handler(event_name: str):
    """Create a handler that broadcasts an EventBus event to WebSocket."""

    def handler(event):
        # CR-003: Defensive guard against non-dict payload.
        if not isinstance(event.payload, dict):
            return

        ws_type = EVENT_TO_WS_TYPE.get(event_name, event_name)
        meeting_id = event.payload.get("meeting_id")
        if not meeting_id:
            # For events without meeting_id, broadcast to all rooms.
            for room in ws_svc.rooms.values():
                _run_async(room.broadcast({
                    "type": ws_type,
                    "payload": event.payload,
                }))
            return

        room = ws_svc.get_or_create(meeting_id)
        # For checkin_prompt, send only to the target seat.
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
    """Register all EventBus→WS handlers. Call once at startup.

    Captures the current event loop so that _run_async can safely schedule
    WebSocket operations from non-asyncio threads (e.g. Timer callbacks).
    If no event loop is running (e.g. in tests), _loop stays None and
    _run_async will raise a clear error when called from a non-asyncio thread.
    """
    global _loop
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = None
    for event_name in EVENT_TO_WS_TYPE:
        event_bus.subscribe(event_name, _make_ws_handler(event_name))
