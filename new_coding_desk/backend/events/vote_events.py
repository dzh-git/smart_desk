"""
Vote events — published by VoteService.

Per EVENT_BUS_SPEC §8.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.events.base_event import BaseEvent


@dataclass
class VoteStartedEvent(BaseEvent):
    event_name: str = "vote_started"


@dataclass
class VoteUpdatedEvent(BaseEvent):
    event_name: str = "vote_updated"


@dataclass
class VoteClosedEvent(BaseEvent):
    event_name: str = "vote_closed"
