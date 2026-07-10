"""
LightingMode — lighting mode enum.

Mirrors the 11 modes defined in arduino_nano_controller/protocol.md §5 so that
Python-side code and the Arduino firmware agree on the exact SET_MODE strings.
Per Phase 4 plan, the LightingManager translates business events into these
mode values, which are forwarded verbatim to the firmware.
"""
from __future__ import annotations

from enum import Enum


class LightingMode(str, Enum):
    BOOT = "BOOT"
    IDLE = "IDLE"
    WELCOME = "WELCOME"
    MEETING_ACTIVE = "MEETING_ACTIVE"
    AGENDA_ACTIVE = "AGENDA_ACTIVE"
    VOTE_OPEN = "VOTE_OPEN"
    VOTE_CLOSED = "VOTE_CLOSED"
    SERVICE_CALL = "SERVICE_CALL"
    MEETING_ENDED = "MEETING_ENDED"
    AI_SPEAKING = "AI_SPEAKING"
    ERROR = "ERROR"
    OFF = "OFF"

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls._value2member_map_
