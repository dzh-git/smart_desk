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

import logging
import time

import numpy as np
from sqlalchemy.orm import Session

from backend.events.event_bus import EventBus
from backend.events.translation_events import TranslationFinalEvent
from backend.exceptions import ValidationError
from backend.models.translation_record import TranslationRecord
from backend.repositories.translation_repository import TranslationRepository
from backend.services.base import BaseService
from backend.services.translation_model_service import (
    TranslationModelService,
    is_translation_model_enabled,
)
from backend.speech_module.punctuation import add_punctuation
from backend.speech_module.text_utils import detect_language
from backend.websocket.speech_trace import trace

logger = logging.getLogger(__name__)

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

    # ── Final (file-based) ───────────────────────────────────────────────────

    def process_final(
        self, audio_path: str, meeting_id: int, seat_id: int,
        utterance_id: str | None = None,
        source_type: str | None = "speech_ws",
    ) -> TranslationRecord:
        """T2: Run full offline ASR → translate → persist → publish event.

        File-based variant (for HTTP upload scenarios).
        Delegates to process_final_array after loading the audio file.

        Publishes: translation_final event with payload including utterance_id.
        """
        speech = _get_speech()
        try:
            from backend.speech_module.audio_utils import load_audio
            audio, sr = load_audio(audio_path)
        except Exception as exc:
            raise ValidationError(
                f"Audio loading failed: {exc}",
                "TRANSLATION_FAILED",
            ) from exc

        return self.process_final_array(
            audio=audio, sr=sr,
            meeting_id=meeting_id, seat_id=seat_id,
            utterance_id=utterance_id, source_type=source_type,
        )

    # ── Final (array-based, Phase 4) ─────────────────────────────────────────

    def process_final_array(
        self, audio: np.ndarray, sr: int,
        meeting_id: int, seat_id: int,
        utterance_id: str | None = None,
        source_type: str | None = "speech_ws",
    ) -> TranslationRecord:
        """T2: Offline ASR rescore → translate → persist → publish event.

        Array-based variant for speech WS flow (concatenated PCM buffer).
        Uses SpeechModule.transcribe_array() for full-context offline rescore.

        Args:
            audio: float32 numpy array, 16kHz mono preferred.
            sr: Sample rate of the input audio (auto-resampled to 16kHz).
            meeting_id: Active meeting ID.
            seat_id: Speaker seat ID.
            utterance_id: The utterance_id from the speech WS start message.
            source_type: Origin of the record.

        Returns:
            The persisted TranslationRecord.

        Raises:
            ValidationError: On empty ASR result, model error, or persistence failure.

        Published event payload (EVENT_BUS_SPEC §5):
            translation_id, utterance_id, seat_id,
            source_lang, target_lang,
            source_text, translated_text,
            source_type
        """
        self._ensure_preloaded()
        speech = _get_speech()

        trace("finalization_start_at",
              utterance_id=utterance_id,
              meeting_id=meeting_id, seat_id=seat_id)

        # 1. Full offline ASR rescore
        _offline_t0 = time.monotonic()
        try:
            source_text = speech.transcribe_array(audio, sr)
        except Exception as exc:
            raise ValidationError(
                f"Transcription failed: {exc}",
                "TRANSLATION_FAILED",
            ) from exc
        _offline_ms = round((time.monotonic() - _offline_t0) * 1000)

        if not source_text or not source_text.strip():
            raise ValidationError(
                "Transcription returned empty text",
                "ASR_EMPTY_RESULT",
            )

        # Phase 02: apply punctuation to final source_text before persist
        source_text = add_punctuation(source_text)

        # 2. Detect source language
        source_lang = detect_language(source_text)
        if source_lang == "zh":
            target_lang = "en"
        else:
            source_lang = "en"
            target_lang = "zh"

        # 3. Translate (real model if enabled, otherwise placeholder)
        _trans_t0 = time.monotonic()
        if source_lang == "zh" and is_translation_model_enabled():
            # Use real OPUS-MT zh-en model
            model_svc = TranslationModelService.get_instance()
            try:
                translated_text = model_svc.translate(source_text)
            except Exception as exc:
                logger.warning("Translation failed (non-fatal): %s", exc)
                translated_text = f"[translation failed: {exc}]"
        else:
            # Fallback: use SpeechModule translate_text placeholder
            try:
                zh_str, en_str = speech.translate_text(source_text)
            except Exception as exc:
                raise ValidationError(
                    f"Translation failed: {exc}",
                    "TRANSLATION_FAILED",
                ) from exc

            if source_lang == "zh":
                translated_text = en_str  # placeholder
            else:
                translated_text = zh_str  # placeholder
        _trans_ms = round((time.monotonic() - _trans_t0) * 1000)

        # 4. Persist to translation_records (with new fields)
        record = self.repo.create(
            meeting_id=meeting_id,
            seat_id=seat_id,
            source_lang=source_lang,
            target_lang=target_lang,
            source_text=source_text.strip(),
            translated_text=translated_text.strip(),
            utterance_id=utterance_id,
            source_type=source_type,
        )

        trace("offline_rescore_complete_at",
              utterance_id=utterance_id,
              meeting_id=meeting_id, seat_id=seat_id,
              offline_asr_ms=_offline_ms,
              translation_ms=_trans_ms,
              translation_id=record.id)

        # 5. Publish event (DB committed inside repo.create())
        payload: dict = {
            "translation_id": record.id,
            "utterance_id": utterance_id,
            "seat_id": seat_id,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "source_text": source_text.strip(),
            "translated_text": translated_text.strip(),
            "source_type": source_type,
        }
        self.event_bus.publish(
            TranslationFinalEvent(
                meeting_id=meeting_id,
                payload=payload,
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
