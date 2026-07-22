"""
EventBus — module decoupling via process-internal events.

Per EVENT_BUS_SPEC:
    Service → EventBus.publish(event) → EventHandler → WebSocketService.broadcast()

Exports:
    EventBus      — singleton publish/subscribe hub
    BaseEvent     — base class for all events
    All 15 event types per EVENT_BUS_SPEC.
"""
from backend.events.event_bus import EventBus, event_bus
from backend.events.base_event import BaseEvent
from backend.events.meeting_events import (
    MeetingStartedEvent,
    MeetingEndedEvent,
)
from backend.events.seat_events import (
    SeatOccupiedEvent,
    SeatVacantEvent,
    CheckinPromptEvent,
    CheckInEvent,
    SpeakerSeatSetEvent,
    SpeakerSeatClearEvent,
)
from backend.events.vote_events import (
    VoteStartedEvent,
    VoteUpdatedEvent,
    VoteClosedEvent,
)
from backend.events.service_call_events import (
    ServiceCallCreatedEvent,
    ServiceCallResolvedEvent,
    ServiceCallCancelledEvent,
)
from backend.events.speech_events import (
    SpeakerSpeakingEvent,
    SpeakerSpeakingStopEvent,
)
from backend.events.translation_events import (
    TranslationFinalEvent,
    TranslationFinalizingEvent,
    TranslationSentenceEvent,
)
from backend.events.agenda_events import AgendaUpdatedEvent

__all__ = [
    "EventBus",
    "event_bus",
    "BaseEvent",
    # Meeting events
    "MeetingStartedEvent",
    "MeetingEndedEvent",
    # Agenda events
    "AgendaUpdatedEvent",
    # Seat events
    "SeatOccupiedEvent",
    "SeatVacantEvent",
    "CheckinPromptEvent",
    "CheckInEvent",
    "SpeakerSeatSetEvent",
    "SpeakerSeatClearEvent",
    # Vote events
    "VoteStartedEvent",
    "VoteUpdatedEvent",
    "VoteClosedEvent",
    # Service call events
    "ServiceCallCreatedEvent",
    "ServiceCallResolvedEvent",
    "ServiceCallCancelledEvent",
    # Speech-speaking events
    "SpeakerSpeakingEvent",
    "SpeakerSpeakingStopEvent",
    # Translation events
    "TranslationFinalizingEvent",
    "TranslationSentenceEvent",
    "TranslationFinalEvent",
]
