"""
Meeting events — published by MeetingService.

Per EVENT_BUS_SPEC §7.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.events.base_event import BaseEvent


@dataclass
class MeetingStartedEvent(BaseEvent):
    event_name: str = "meeting_started"


@dataclass
class MeetingEndedEvent(BaseEvent):
    event_name: str = "meeting_ended"
