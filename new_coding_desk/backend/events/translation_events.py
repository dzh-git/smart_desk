"""
Translation events — published by TranslationService and SpeechStreamService.

Per EVENT_BUS_SPEC §5, §10:
    translation_interim            — published by SpeechStreamService (ephemeral)
    translation_interim_cancelled  — published by SpeechStreamService (ephemeral)
    translation_final              — published by TranslationService (persisted)
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.events.base_event import BaseEvent


@dataclass
class TranslationInterimEvent(BaseEvent):
    """Streaming ASR interim result — ephemeral, not persisted.

    Published by SpeechStreamService on each PCM16 binary frame.
    Broadcast to /ws/{meeting_id} via WebSocketEventHandler.

    Payload per EVENT_BUS_SPEC §5:
        utterance_id, seat_id, revision,
        source_lang, target_lang,
        source_text, translated_text, is_final
    """
    event_name: str = "translation_interim"


@dataclass
class TranslationInterimCancelledEvent(BaseEvent):
    """Indicates a pending interim utterance was discarded.

    Published by SpeechStreamService when client sends cancel.
    Broadcast to /ws/{meeting_id} via WebSocketEventHandler.
    Payload: utterance_id, seat_id, reason.
    """
    event_name: str = "translation_interim_cancelled"


@dataclass
class TranslationFinalizingEvent(BaseEvent):
    """Moves a completed realtime segment into pending history immediately."""
    event_name: str = "translation_finalizing"


@dataclass
class TranslationFinalEvent(BaseEvent):
    """Finalized translation record — persisted, then broadcast.

    Published by TranslationService after offline ASR rescore + database write.
    """
    event_name: str = "translation_final"
