"""
BaseEvent — unified event envelope.

Per EVENT_BUS_SPEC §3:
    All events share: event_name, meeting_id, timestamp, payload.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class BaseEvent:
    """Base class for all SmartDesk events.

    Subclass and set `event_name` as a class-level constant.
    """

    event_name: str
    meeting_id: int | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = field(default_factory=dict)
