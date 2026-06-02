"""
TranslationService — ASR + translation pipeline.

Per system_architecture §4.2, API_SPEC §10, EVENT_BUS_SPEC §10:
    - Calls SpeechModule frozen API (process_interim, process_final).
    - Persists final results to translation_records.
    - Publishes translation_final event for WebSocket broadcast.

Business rules:
    T1: translation_interim → no event, no WebSocket, direct HTTP return.
    T2: translation_final   → save DB + publish translation_final event.
    T3: history query from translation_records table (not SpeechModule HistoryStore).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.events.event_bus import EventBus
from backend.events.translation_events import TranslationFinalEvent
from backend.exceptions import ValidationError
from backend.models.translation_record import TranslationRecord
from backend.repositories.translation_repository import TranslationRepository
from backend.services.base import BaseService

# ── SpeechModule singleton ─────────────────────────────────────────────────────
_speech = None  # lazy singleton

NOT_AVAILABLE = "[translation not available]"


def _get_speech():
    """Return the module-level SpeechModule singleton, creating it if needed."""
    global _speech
    if _speech is None:
        from backend.speech_module import SpeechModule

        _speech = SpeechModule(max_workers=2)
    return _speech


# ── Service ────────────────────────────────────────────────────────────────────


class TranslationService(BaseService):
    """Translation pipeline: STT → translate → persist → event.

    Uses SpeechModule singleton for ASR/translation.
    Persists to translation_records via TranslationRepository.

    Business rules T1-T3 enforced here.
    Events published: translation_final.
    """

    def __init__(self, db: Session, event_bus: EventBus) -> None:
        super().__init__(db, event_bus)
        self.repo = TranslationRepository(db)

    # ── Preload ──────────────────────────────────────────────────────────────

    def _ensure_preloaded(self) -> None:
        """Ensure SpeechModule models are loaded. Idempotent."""
        speech = _get_speech()
        if not speech.ready:
            try:
                speech.preload()
            except Exception as exc:
                raise ValidationError(
                    f"Speech module preload failed: {exc}",
                    "SPEECH_MODULE_ERROR",
                ) from exc

    # ── Interim ──────────────────────────────────────────────────────────────

    def process_interim(self, audio_path: str, session_key: str) -> str:
        """T1: Process interim audio chunk, return accumulated text.

        No DB write. No event publish. HTTP direct return.
        """
        self._ensure_preloaded()
        speech = _get_speech()
        try:
            text = speech.process_interim_chunk(audio_path, session_key)
        except Exception as exc:
            raise ValidationError(
                f"Interim processing failed: {exc}",
                "TRANSLATION_FAILED",
            ) from exc
        return text or ""

    # ── Final ────────────────────────────────────────────────────────────────

    def process_final(
        self, audio_path: str, meeting_id: int, seat_id: int
    ) -> TranslationRecord:
        """T2: Run full offline ASR → translate → persist → publish event.

        Returns the persisted TranslationRecord.
        Publishes: translation_final event with payload:
            {translation_id, seat_id, source_lang, target_lang,
             source_text, translated_text}
        """
        self._ensure_preloaded()
        speech = _get_speech()

        # 1. Full offline ASR
        try:
            source_text = speech.transcribe(audio_path)
        except Exception as exc:
            raise ValidationError(
                f"Transcription failed: {exc}",
                "TRANSLATION_FAILED",
            ) from exc

        if not source_text or not source_text.strip():
            raise ValidationError(
                "Transcription returned empty text",
                "TRANSLATION_FAILED",
            )

        # 2. Translate (auto-detect language)
        try:
            zh_str, en_str = speech.translate_text(source_text)
        except Exception as exc:
            raise ValidationError(
                f"Translation failed: {exc}",
                "TRANSLATION_FAILED",
            ) from exc

        # 3. Detect source language from translate_text result
        if en_str == NOT_AVAILABLE and zh_str != NOT_AVAILABLE:
            source_lang = "zh"
            target_lang = "en"
            translated_text = en_str
            # source_text is the original ASR output; zh_str is the confirmed zh text
        elif zh_str == NOT_AVAILABLE and en_str != NOT_AVAILABLE:
            source_lang = "en"
            target_lang = "zh"
            translated_text = zh_str
        else:
            # Both populated or both unavailable — default to auto/auto
            source_lang = "auto"
            target_lang = "auto"
            translated_text = en_str if en_str != NOT_AVAILABLE else zh_str

        # 4. Persist to translation_records
        record = self.repo.create(
            meeting_id=meeting_id,
            seat_id=seat_id,
            source_lang=source_lang,
            target_lang=target_lang,
            source_text=source_text.strip(),
            translated_text=translated_text.strip(),
        )

        # 5. Publish event (DB committed inside repo.create())
        self.event_bus.publish(
            TranslationFinalEvent(
                meeting_id=meeting_id,
                payload={
                    "translation_id": record.id,
                    "seat_id": seat_id,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "source_text": source_text.strip(),
                    "translated_text": translated_text.strip(),
                },
            )
        )

        return record

    # ── History ──────────────────────────────────────────────────────────────

    def get_history(
        self, meeting_id: int, seat_id: int | None = None
    ) -> list[TranslationRecord]:
        """T3: Query translation history from translation_records table."""
        return self.repo.list_by_meeting(meeting_id, seat_id=seat_id)

    # ── Session reset ────────────────────────────────────────────────────────

    def reset_session(self, session_key: str) -> None:
        """Reset interim state for a session (SentenceMerger buffer).

        Preserves CIF cache for streaming ASR continuity.
        """
        self._ensure_preloaded()
        speech = _get_speech()
        speech.reset_interim(session_key)
