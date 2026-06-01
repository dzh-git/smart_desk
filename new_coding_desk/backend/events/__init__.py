"""
EventBus — module decoupling via process-internal events.

Per EVENT_BUS_SPEC:
    Service → EventBus.publish(event) → EventHandler → WebSocketService.broadcast()

Exports:
    EventBus      — singleton publish/subscribe hub
    BaseEvent     — base class for all events
"""
from backend.events.event_bus import EventBus, event_bus
from backend.events.base_event import BaseEvent
from backend.events.service_call_events import (
    ServiceCallCreatedEvent,
    ServiceCallResolvedEvent,
    ServiceCallCancelledEvent,
)
from backend.events.translation_events import TranslationFinalEvent

__all__ = [
    "EventBus",
    "event_bus",
    "BaseEvent",
    "ServiceCallCreatedEvent",
    "ServiceCallResolvedEvent",
    "ServiceCallCancelledEvent",
    "TranslationFinalEvent",
]
