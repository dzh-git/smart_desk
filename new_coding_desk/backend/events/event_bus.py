"""
EventBus — process-internal publish/subscribe.

Per EVENT_BUS_SPEC §1-4, §13:
    - Events published by Services only
    - Subscribers registered at startup (no runtime dynamic registration)
    - V1: in-process, no persistence, no external broker

Usage:
    from backend.events import event_bus, BaseEvent

    event_bus.subscribe("seat_occupied", my_handler)
    event_bus.publish(SeatOccupiedEvent(meeting_id=1, payload={"seat_id": 3}))
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

from backend.events.base_event import BaseEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[BaseEvent], None]


class EventBus:
    """Process-internal publish/subscribe event hub.

    All handlers for an event are called synchronously in registration order.
    A handler that raises does not prevent other handlers from running.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)

    # ── Public API ──────────────────────────────────────────────────────────

    def publish(self, event: BaseEvent) -> None:
        """Publish an event to all registered subscribers.

        Per E1: only Services should call this method.
        """
        handlers = self._subscribers.get(event.event_name, [])
        if not handlers:
            return
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "EventBus: handler %s failed for event %s",
                    handler.__name__,
                    event.event_name,
                )

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Register a handler for an event type.

        Per §12: called at startup. No runtime dynamic registration.
        """
        self._subscribers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """Remove a handler. Rarely needed; provided for test cleanup."""
        try:
            self._subscribers[event_name].remove(handler)
        except ValueError:
            pass

    # ── Introspection ───────────────────────────────────────────────────────

    @property
    def registered_events(self) -> list[str]:
        """List all event names that have at least one subscriber."""
        return sorted(self._subscribers.keys())

    def subscriber_count(self, event_name: str) -> int:
        """How many handlers registered for a given event."""
        return len(self._subscribers.get(event_name, []))


# Singleton
event_bus = EventBus()
