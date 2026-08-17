"""
Seat events — published by SeatService.

Per EVENT_BUS_SPEC §6.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from backend.events.base_event import BaseEvent


@dataclass
class SeatOccupiedEvent(BaseEvent):
    event_name: str = "seat_occupied"


@dataclass
class SeatVacantEvent(BaseEvent):
    event_name: str = "seat_vacant"


@dataclass
class CheckinPromptEvent(BaseEvent):
    event_name: str = "checkin_prompt"


@dataclass
class CheckInEvent(BaseEvent):
    event_name: str = "check_in"


@dataclass
class SeatAssignmentUpdatedEvent(BaseEvent):
    event_name: str = "seat_assignment_updated"


@dataclass
class SpeakerSeatSetEvent(BaseEvent):
    event_name: str = "speaker_seat_set"


@dataclass
class SpeakerSeatClearEvent(BaseEvent):
    event_name: str = "speaker_seat_clear"
