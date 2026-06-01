"""
Service call events — published by ServiceCallService.

Per EVENT_BUS_SPEC §9.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.events.base_event import BaseEvent


@dataclass
class ServiceCallCreatedEvent(BaseEvent):
    event_name: str = "service_call_created"


@dataclass
class ServiceCallResolvedEvent(BaseEvent):
    event_name: str = "service_call_resolved"


@dataclass
class ServiceCallCancelledEvent(BaseEvent):
    event_name: str = "service_call_cancelled"
