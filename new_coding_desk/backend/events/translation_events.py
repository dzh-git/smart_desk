"""
Translation events — published by TranslationService.

Per EVENT_BUS_SPEC §10.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.events.base_event import BaseEvent


@dataclass
class TranslationFinalEvent(BaseEvent):
    event_name: str = "translation_final"
