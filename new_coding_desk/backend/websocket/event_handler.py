"""
WebSocketEventHandler — bridges EventBus → WebSocket broadcast.

Per EVENT_BUS_SPEC §12, WEBSOCKET_PROTOCOL §12:
    The ONLY path for server→client push:
        Service → EventBus.publish(event) → WebSocketEventHandler → ws_service.broadcast()

Registered at startup for all 15 event types defined in EVENT_BUS_SPEC §14.

EventBus is synchronous. WebSocket broadcast is async. This handler bridges
the gap by scheduling the async broadcast as a task on the running event loop
(via asyncio.create_task). Errors inside the task are logged but never escape
to the EventBus (which would crash other handlers).
"""
from __future__ import annotations

import asyncio
import logging

from backend.events.base_event import BaseEvent
from backend.websocket.ws_service import ws_service

logger = logging.getLogger(__name__)


def _log_broadcast_error(task: asyncio.Task) -> None:
    """Log any exception from a broadcast task (done callback)."""
    try:
        task.result()
    except Exception:
        logger.exception("WebSocketEventHandler: broadcast task failed")


class WebSocketEventHandler:
    """Converts EventBus events → WebSocket broadcast messages.

    Per WEBSOCKET_PROTOCOL §5: message format
        {event, meeting_id, timestamp, payload}

    __call__ is synchronous (required by EventBus contract). It schedules
    the actual async broadcast as a fire-and-forget task on the running loop.
    """

    # Event names that require broadcast (all 15 per EVENT_BUS_SPEC §14).
    # translation_interim is excluded per WEBSOCKET_PROTOCOL §10.
    BROADCAST_EVENTS: frozenset[str] = frozenset({
        "seat_occupied",
        "seat_vacant",
        "checkin_prompt",
        "check_in",
        "speaker_seat_set",
        "speaker_seat_clear",
        "meeting_started",
        "meeting_ended",
        "vote_started",
        "vote_updated",
        "vote_closed",
        "service_call_created",
        "service_call_resolved",
        "service_call_cancelled",
        "translation_final",
    })

    def __call__(self, event: BaseEvent) -> None:
        """Handle an event: convert to WS format + schedule async broadcast.

        Synchronous (required by EventBus). Schedules the async broadcast
        as a task on the running event loop. Does NOT block.

        Skips events without a meeting_id (can't determine room).
        """
        if event.meeting_id is None:
            logger.debug(
                "WebSocketEventHandler: skipping %s (no meeting_id)",
                event.event_name,
            )
            return

        if event.event_name not in self.BROADCAST_EVENTS:
            return

        message = self._to_message(event)

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(
                ws_service.broadcast(event.meeting_id, message)
            )
            task.add_done_callback(_log_broadcast_error)
        except RuntimeError:
            # No running event loop — e.g. called from a sync unit test
            logger.warning(
                "WebSocketEventHandler: no running loop, broadcast skipped for %s",
                event.event_name,
            )

    def _to_message(self, event: BaseEvent) -> dict:
        """Convert a BaseEvent to the WS message format per §5."""
        return {
            "event": event.event_name,
            "meeting_id": event.meeting_id,
            "timestamp": int(event.timestamp.timestamp()),
            "payload": event.payload,
        }

    # ── Startup registration ────────────────────────────────────────────────

    @classmethod
    def register_all(cls, event_bus) -> "WebSocketEventHandler":
        """Register this handler for all broadcast events on startup.

        Per EVENT_BUS_SPEC §12: fixed registration at startup.
        Returns the handler instance (keep reference to prevent GC).
        """
        handler = cls()
        for event_name in cls.BROADCAST_EVENTS:
            event_bus.subscribe(event_name, handler)
        logger.info(
            "WebSocketEventHandler registered for %d events",
            len(cls.BROADCAST_EVENTS),
        )
        return handler
