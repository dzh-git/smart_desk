from __future__ import annotations
from dataclasses import dataclass, field
from collections.abc import Callable
import logging
import threading
import time

logger = logging.getLogger(__name__)


@dataclass
class BaseEvent:
    """Event envelope for publishing on the EventBus.

    Attributes:
        name: Event type identifier used for routing to subscribers.
        payload: Arbitrary key-value data carried by the event. The dict is
            mutable and shared — the same BaseEvent instance is passed to
            every handler. Handlers must not mutate payload unless they
            intend to communicate with subsequent handlers.
        timestamp: Unix timestamp of event creation (auto-set).
    """

    name: str
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """Thread-safe in-process pub/sub event bus.

    Handlers are called synchronously in the publishing thread.
    Subscribe is not idempotent: registering the same handler twice
    results in duplicate calls.
    Unsubscribe of an unregistered handler or event silently no-ops.

    Thread safety: subscribe, unsubscribe, and publish use a snapshot-based
    locking strategy. The lock is held only for the minimal critical section
    (dict mutation or list copy) and released before handler iteration.
    publish() iterates a snapshot of the handler list so handlers may
    safely call subscribe, unsubscribe, or publish during publish without
    deadlock.
    """

    def __init__(self):
        self._handlers: dict[str, list[Callable[[BaseEvent], None]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_name: str, handler: Callable[[BaseEvent], None]) -> None:
        """Register a handler to be called when `event_name` is published.

        Args:
            event_name: The event type to subscribe to.
            handler: A callable that receives the published BaseEvent.
                Called synchronously in the publisher's thread.

        Note:
            Not idempotent — subscribing the same handler twice will
            cause it to be called twice per published event.
        """
        with self._lock:
            if event_name not in self._handlers:
                self._handlers[event_name] = []
            self._handlers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: Callable[[BaseEvent], None]) -> None:
        """Remove a previously registered handler for `event_name`.

        Args:
            event_name: The event type to unsubscribe from.
            handler: The exact callable object previously passed to subscribe().

        Note:
            Silently no-ops if the handler or event is not registered.
            Deletes the handler list for the event if it becomes empty.
        """
        with self._lock:
            handlers = self._handlers.get(event_name)
            if handlers:
                try:
                    handlers.remove(handler)
                except ValueError:
                    pass
                if not handlers:
                    del self._handlers[event_name]

    def publish(self, event: BaseEvent) -> None:
        """Deliver an event to all subscribed handlers.

        Args:
            event: The BaseEvent to deliver. Handlers are matched by
                event.name.

        Note:
            Handlers are called synchronously in the publishing thread.
            A snapshot of the handler list is taken before iteration,
            so mutations from within handlers do not affect delivery.
            Exceptions from handlers are logged and do not propagate.
        """
        with self._lock:
            handlers = list(self._handlers.get(event.name, []))
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "Handler for event '%s' raised an exception", event.name
                )


# Singleton
event_bus = EventBus()
