"""
Agenda events — published by MeetingService.

Per EVENT_BUS_SPEC §7, §Agenda Event Rules:
    agenda_updated is published after create, delete, set_current, advance,
    complete, or skip.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.events.base_event import BaseEvent


@dataclass
class AgendaUpdatedEvent(BaseEvent):
    event_name: str = "agenda_updated"
