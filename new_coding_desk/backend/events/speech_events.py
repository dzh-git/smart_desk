"""
Speech-speaking events — published by SpeechStreamService.

Per the lighting integration plan, the AI_SPEAKING light effect is driven
while a speaker is actually talking (utterance in SPEAKING state), not by the
static "speaker seat set" event. These two events carry ``seat_id`` so the
LightingManager can light only the speaker's strip.

    speaker_speaking       -> turn on AI_SPEAKING for payload["seat_id"]
    speaker_speaking_stop  -> revert that seat to its previous mode
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.events.base_event import BaseEvent


@dataclass
class SpeakerSpeakingEvent(BaseEvent):
    event_name: str = "speaker_speaking"


@dataclass
class SpeakerSpeakingStopEvent(BaseEvent):
    event_name: str = "speaker_speaking_stop"
