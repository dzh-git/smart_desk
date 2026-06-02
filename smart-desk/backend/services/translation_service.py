from __future__ import annotations
from sqlalchemy.orm import Session
from backend.services.event_bus import EventBus, BaseEvent


class TranslationService:
    """Orchestrates translation: delegates STT/MT to SpeechModule, persists via Repository, publishes events."""

    def __init__(self, db: Session, event_bus: EventBus, translation_repo,
                 speech_module=None, mt_engine=None):
        self.db = db
        self.bus = event_bus
        self.repo = translation_repo
        self.speech = speech_module
        self.mt = mt_engine

    @property
    def ready(self) -> bool:
        if not self.speech or not self.speech.ready:
            return False
        if self.mt is not None and not getattr(self.mt, 'ready', False):
            return False
        return True

    def preload(self):
        """Trigger model preload (called by meeting_started subscriber)."""
        if self.speech:
            self.speech.preload()

    def translate_text(self, text: str):
        if not self.speech or not self.speech.ready:
            return "", ""
        return self.speech.translate_text(text)

    def transcribe_audio(self, audio_path: str):
        if not self.speech or not self.speech.ready:
            return ""
        return self.speech.transcribe(audio_path)

    def process_interim(self, audio_path: str, session_key: str):
        if not self.speech or not self.speech.ready:
            return ""
        return self.speech.process_interim_chunk(audio_path, session_key)

    def reset_interim(self, session_key: str):
        if self.speech:
            self.speech.reset_interim(session_key)

    def start_utterance(self, session_key: str):
        if self.speech:
            self.speech.start_utterance(session_key)

    def get_history(self, meeting_id: int, seat_id: int | None = None, limit: int = 500):
        if seat_id is not None:
            return self.repo.list_by_meeting_seat(meeting_id, seat_id, limit)
        return self.repo.list_by_meeting(meeting_id, limit)

    def delete_history(self, meeting_id: int):
        return self.repo.delete_by_meeting(meeting_id)

    def on_translation_final(self, meeting_id: int, seat_id: int,
                              zh: str, en: str, segment_id: int = 0,
                              source_lang: str = "zh", target_lang: str = "en"):
        """Persist and broadcast final translation.

        source_lang/target_lang default to 'zh'/'en' matching the parameter
        names. Callers that know the actual direction should pass them
        explicitly to avoid incorrect auto-detection.
        """
        self.repo.upsert(
            meeting_id=meeting_id, seat_id=seat_id,
            source_lang=source_lang, target_lang=target_lang,
            source_text=zh, translated_text=en,
        )
        self.bus.publish(BaseEvent(
            name="translation_final",
            payload={
                "zh": zh, "en": en, "seat_id": seat_id,
                "segment_id": segment_id, "is_final": True,
                "meeting_id": meeting_id, "source_lang": source_lang,
                "target_lang": target_lang,
            },
        ))

    def cleanup_expired(self, retention_days: int = 180):
        return self.repo.cleanup_expired(retention_days)
