"""
WebSocketEventHandler — bridges EventBus → WebSocket broadcast.

Per EVENT_BUS_SPEC §12, WEBSOCKET_PROTOCOL §12:
    The ONLY path for server→client push:
        Service → EventBus.publish(event) → WebSocketEventHandler → ws_service.broadcast()

Registered at startup for all 15 event types defined in EVENT_BUS_SPEC §14.

EventBus is synchronous. WebSocket broadcast is async. This handler bridges
the gap by scheduling the async broadcast.

Thread safety (fix Phase 04 review):
    FastAPI synchronous routes run in a thread-pool worker — that thread has
    NO running asyncio event loop, so asyncio.create_task would fail.

    Solution: the main asyncio event loop is captured at application startup
    (WebSocketEventHandler.capture_loop()). When __call__ is invoked from a
    worker thread, it uses loop.call_soon_threadsafe() to schedule the async
    broadcast on the main loop.

    When __call__ is invoked on the main loop (e.g. by an async route), it
    uses asyncio.create_task directly.

Duplicate registration guard:
    register_all() checks whether a handler is already registered for each
    event name and skips if so, avoiding double broadcast.
"""
from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

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
    the actual async broadcast as a fire-and-forget task.
    """

    # Event names that require broadcast per EVENT_BUS_SPEC.
    # translation_interim and translation_interim_cancelled were added in Phase 3.
    # agenda_updated was added in Phase 1.
    BROADCAST_EVENTS: ClassVar[frozenset[str]] = frozenset({
        "seat_occupied",
        "seat_vacant",
        "checkin_prompt",
        "check_in",
        "seat_assignment_updated",
        "speaker_seat_set",
        "speaker_seat_clear",
        "meeting_started",
        "meeting_ended",
        "agenda_updated",
        "vote_started",
        "vote_updated",
        "vote_closed",
        "service_call_created",
        "service_call_resolved",
        "service_call_cancelled",
        "translation_interim",
        "translation_sentence",
        "translation_interim_cancelled",
        "translation_finalizing",
        "translation_final",
    })

    # Main asyncio event loop, captured at startup by capture_loop().
    _main_loop: ClassVar[asyncio.AbstractEventLoop | None] = None

    # Track which event names this handler is registered for (dedup guard).
    _registered_events: ClassVar[set[str]] = set()

    # ── Startup ────────────────────────────────────────────────────────────

    @classmethod
    def capture_loop(cls) -> None:
        """Capture the running asyncio event loop.

        Called at application startup (inside lifespan) so that broadcasts
        can be scheduled from non-asyncio threads.
        """
        try:
            cls._main_loop = asyncio.get_running_loop()
            logger.debug(
                "WebSocketEventHandler: captured main loop id=%d",
                id(cls._main_loop),
            )
        except RuntimeError:
            logger.warning(
                "WebSocketEventHandler: no running loop during capture_loop()",
            )

    # ── Event handling ────────────────────────────────────────────────────

    def __call__(self, event: BaseEvent) -> None:
        """Handle an event: convert to WS format + schedule async broadcast.

        Synchronous (required by EventBus). Schedules the async broadcast
        on the correct event loop.

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

        # Determine which loop to schedule on
        try:
            loop = asyncio.get_running_loop()
            # We are on the main loop or an async worker — create_task directly
            self._schedule(loop, event.meeting_id, message)
        except RuntimeError:
            # No running loop — called from a sync route's thread-pool worker.
            # Use the captured main loop with call_soon_threadsafe.
            if self._main_loop is not None and self._main_loop.is_running():
                self._main_loop.call_soon_threadsafe(
                    self._schedule_inner, self._main_loop,
                    event.meeting_id, message,
                )
            else:
                logger.warning(
                    "WebSocketEventHandler: no event loop available, "
                    "broadcast skipped for %s (meeting_id=%s)",
                    event.event_name, event.meeting_id,
                )

    def _schedule(
        self, loop: asyncio.AbstractEventLoop,
        meeting_id: int, message: dict,
    ) -> None:
        """Create an async task on *loop* to broadcast."""
        task = loop.create_task(ws_service.broadcast(meeting_id, message))
        task.add_done_callback(_log_broadcast_error)

    def _schedule_inner(
        self, loop: asyncio.AbstractEventLoop,
        meeting_id: int, message: dict,
    ) -> None:
        """Inner callback for call_soon_threadsafe — same as _schedule."""
        self._schedule(loop, meeting_id, message)

    def _to_message(self, event: BaseEvent) -> dict:
        """Convert a BaseEvent to the WS message format per §5."""
        return {
            "event": event.event_name,
            "meeting_id": event.meeting_id,
            "timestamp": int(event.timestamp.timestamp()),
            "payload": event.payload,
        }

    # ── Startup registration ──────────────────────────────────────────────

    @classmethod
    def register_all(cls, event_bus) -> "WebSocketEventHandler":
        """Register this handler for all broadcast events on startup.

        Per EVENT_BUS_SPEC §12: fixed registration at startup.
        Returns the handler instance (keep reference to prevent GC).

        Duplicate registration guard: if already registered for a given
        event name, skip it.
        """
        handler = cls()
        for event_name in cls.BROADCAST_EVENTS:
            if event_name in cls._registered_events:
                logger.debug(
                    "WebSocketEventHandler: already registered for %s, skipping",
                    event_name,
                )
                continue
            event_bus.subscribe(event_name, handler)
            cls._registered_events.add(event_name)

        count = len(cls._registered_events)
        logger.info(
            "WebSocketEventHandler registered for %d events", count,
        )
        return handler
