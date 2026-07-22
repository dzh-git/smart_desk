"""Sentence-final bilingual ASR, translation, persistence and event pipeline."""
from __future__ import annotations

import logging
import re
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
    NOT_AVAILABLE,
    TranslationModelService,
    is_translation_model_enabled,
)
from backend.speech_module.punctuation import add_punctuation
from backend.speech_module.text_utils import detect_language, normalize_english_display
from backend.websocket.speech_trace import trace

logger = logging.getLogger(__name__)
_speech = None


def _normalize_punctuation(text: str, source_lang: str) -> str:
    """Collapse duplicate/conflicting ASR punctuation without changing words."""
    text = re.sub(r"[，,]{2,}", "，" if source_lang == "zh" else ",", text)
    text = re.sub(r"[。．.]{2,}", "。" if source_lang == "zh" else ".", text)
    text = re.sub(r"[？?]{2,}", "？" if source_lang == "zh" else "?", text)
    text = re.sub(r"[！!]{2,}", "！" if source_lang == "zh" else "!", text)
    text = re.sub(r"([。！？.!?])\s*[，,]", r"\1", text)
    text = re.sub(r"[，,]\s*([。！？.!?])", r"\1", text)
    return text.strip()


def _is_narrowband_tone(audio: np.ndarray) -> bool:
    """Reject calibration beeps that VAD can mistake for human speech."""
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(samples) < 1600:
        return False
    samples = samples - float(samples.mean())
    spectrum = np.abs(np.fft.rfft(samples))
    total = float(spectrum.sum())
    return total > 0 and float(spectrum.max()) / total > 0.45


def _get_speech():
    global _speech
    if _speech is not None:
        return _speech
    from backend.services.speech_stream_service import stream_service

    return stream_service._get_speech_module()


class TranslationService(BaseService):
    """Turn one finalized sentence into a persisted bilingual transcript."""

    def __init__(self, db: Session, event_bus: EventBus) -> None:
        super().__init__(db, event_bus)
        self.repo = TranslationRepository(db)

    def _ensure_preloaded(self, *, require_final_asr: bool = True) -> None:
        speech = _get_speech()
        status = speech.status
        if status.get("streaming_model") != "loaded":
            speech.preload()
        if speech.status.get("streaming_model") != "loaded":
            raise ValidationError(
                f"Speech module preload failed: {speech.status.get('last_error')}",
                "SPEECH_MODULE_ERROR",
            )
        if require_final_asr and speech.status.get("offline_model") != "loaded":
            raise ValidationError(
                f"Bilingual final ASR is unavailable: {speech.status.get('last_error')}",
                "SPEECH_MODULE_ERROR",
            )

    def process_interim(self, audio_path: str, session_key: str) -> str:
        self._ensure_preloaded(require_final_asr=False)
        try:
            return _get_speech().process_interim_chunk(audio_path, session_key) or ""
        except Exception as exc:
            raise ValidationError(
                f"Interim processing failed: {exc}", "TRANSLATION_FAILED",
            ) from exc

    def process_final(
        self,
        audio_path: str,
        meeting_id: int,
        seat_id: int,
        utterance_id: str | None = None,
        source_type: str | None = "speech_ws",
    ) -> TranslationRecord:
        try:
            from backend.speech_module.audio_utils import load_audio

            audio, sr = load_audio(audio_path)
        except Exception as exc:
            raise ValidationError(
                f"Audio loading failed: {exc}", "TRANSLATION_FAILED",
            ) from exc
        return self.process_final_array(
            audio,
            sr,
            meeting_id,
            seat_id,
            utterance_id=utterance_id,
            source_type=source_type,
        )

    def process_final_array(
        self,
        audio: np.ndarray,
        sr: int,
        meeting_id: int,
        seat_id: int,
        utterance_id: str | None = None,
        source_type: str | None = "speech_ws",
        *,
        fallback_source_text: str = "",
        translate: bool = True,
    ) -> TranslationRecord:
        """Run bilingual final ASR and translate the detected language."""

        self._ensure_preloaded(require_final_asr=not bool(fallback_source_text.strip()))
        speech = _get_speech()
        if hasattr(speech, "trim_to_speech"):
            validated_audio = speech.trim_to_speech(audio, sr)
            if validated_audio is None or len(validated_audio) == 0:
                if fallback_source_text.strip():
                    return self.process_final_text(
                        fallback_source_text,
                        meeting_id,
                        seat_id,
                        utterance_id=utterance_id,
                        source_type=source_type,
                        translate=translate,
                        recognition_error="No confirmed speech in final ASR buffer",
                    )
                raise ValidationError("No confirmed speech in audio", "ASR_EMPTY_RESULT")
            audio = validated_audio

        if _is_narrowband_tone(audio):
            if fallback_source_text.strip():
                return self.process_final_text(
                    fallback_source_text,
                    meeting_id,
                    seat_id,
                    utterance_id=utterance_id,
                    source_type=source_type,
                    translate=translate,
                    recognition_error="Narrowband non-speech tone rejected by final ASR",
                )
            raise ValidationError("No confirmed speech in audio", "ASR_EMPTY_RESULT")

        trace(
            "finalization_start_at",
            utterance_id=utterance_id,
            meeting_id=meeting_id,
            seat_id=seat_id,
        )
        started = time.monotonic()
        recognition_status = "ok"
        recognition_error: str | None = None
        try:
            if hasattr(speech, "transcribe_array_with_language"):
                result = speech.transcribe_array_with_language(audio, sr)
                source_text = result.text.strip()
                source_lang = result.source_lang
                recognition_model = getattr(result, "recognition_model", "sensevoice")
            else:
                source_text = speech.transcribe_array(audio, sr).strip()
                source_lang = detect_language(source_text)
                recognition_model = "paraformer_zh" if source_lang == "zh" else "sensevoice"
        except Exception as exc:
            source_text = ""
            source_lang = "zh"
            recognition_model = "fallback"
            recognition_status = "degraded"
            recognition_error = str(exc)

        if not source_text:
            source_text = fallback_source_text.strip()
            if not source_text:
                raise ValidationError("Transcription returned empty text", "ASR_EMPTY_RESULT")
            source_lang = detect_language(source_text)
            recognition_status = "degraded"
            recognition_error = recognition_error or "Bilingual final ASR returned empty text"
            recognition_model = "fallback"

        source_lang = "zh" if source_lang == "zh" else "en"
        if source_lang == "zh" and recognition_model == "paraformer_zh":
            source_text = add_punctuation(source_text).strip()
        source_text = _normalize_punctuation(source_text, source_lang)
        target_lang = "en" if source_lang == "zh" else "zh"
        offline_ms = round((time.monotonic() - started) * 1000)

        return self._translate_persist_publish(
            source_text=source_text,
            source_lang=source_lang,
            target_lang=target_lang,
            meeting_id=meeting_id,
            seat_id=seat_id,
            utterance_id=utterance_id,
            source_type=source_type,
            translate=translate,
            recognition_status=recognition_status,
            recognition_error=recognition_error,
            offline_ms=offline_ms,
        )

    def process_final_text(
        self,
        source_text: str,
        meeting_id: int,
        seat_id: int,
        utterance_id: str | None = None,
        source_type: str | None = "speech_ws",
        *,
        translate: bool = True,
        apply_punctuation: bool = False,
        source_lang: str | None = None,
        recognition_status: str = "degraded",
        recognition_error: str | None = "Bilingual final ASR was not used",
    ) -> TranslationRecord:
        """Persist a streaming-text fallback while keeping failures explicit."""

        source_text = (source_text or "").strip()
        if not source_text:
            raise ValidationError(
                "Realtime transcription returned empty text", "ASR_EMPTY_RESULT",
            )
        source_lang = source_lang or detect_language(source_text)
        source_lang = "zh" if source_lang == "zh" else "en"
        if source_lang == "zh" and apply_punctuation:
            source_text = add_punctuation(source_text).strip()
        elif source_lang == "en":
            source_text = normalize_english_display(source_text)
        target_lang = "en" if source_lang == "zh" else "zh"
        return self._translate_persist_publish(
            source_text=source_text,
            source_lang=source_lang,
            target_lang=target_lang,
            meeting_id=meeting_id,
            seat_id=seat_id,
            utterance_id=utterance_id,
            source_type=source_type,
            translate=translate,
            recognition_status=recognition_status,
            recognition_error=recognition_error,
            offline_ms=0,
        )

    def _translate_persist_publish(
        self,
        *,
        source_text: str,
        source_lang: str,
        target_lang: str,
        meeting_id: int,
        seat_id: int,
        utterance_id: str | None,
        source_type: str | None,
        translate: bool,
        recognition_status: str,
        recognition_error: str | None,
        offline_ms: int,
    ) -> TranslationRecord:
        translation_started = time.monotonic()
        translation_error: str | None = None
        if translate:
            model_service = TranslationModelService.get_instance()
            try:
                translated_text = model_service.translate(
                    source_text, source_lang, target_lang,
                )
            except TypeError:
                # Compatibility for simple injected translators used by clients/tests.
                translated_text = model_service.translate(source_text)
            if translated_text == NOT_AVAILABLE:
                direction_status = (
                    model_service.get_status().get(f"{source_lang}_{target_lang}", {})
                    if hasattr(model_service, "get_status") else {}
                )
                translation_error = str(
                    direction_status.get("error")
                    or "Required local translation model is unavailable"
                )
        else:
            translated_text = NOT_AVAILABLE
            translation_error = "Translation skipped because finalization queue is overloaded"
        translation_ms = round((time.monotonic() - translation_started) * 1000)
        translation_status = "ok" if translated_text != NOT_AVAILABLE else "unavailable"

        record = self.repo.create(
            meeting_id=meeting_id,
            seat_id=seat_id,
            source_lang=source_lang,
            target_lang=target_lang,
            source_text=source_text,
            translated_text=translated_text,
            utterance_id=utterance_id,
            source_type=source_type,
        )
        payload: dict[str, object] = {
            "translation_id": record.id,
            "utterance_id": utterance_id,
            "seat_id": seat_id,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "source_text": source_text,
            "translated_text": translated_text,
            "source_type": source_type,
            "translation_status": translation_status,
            "recognition_status": recognition_status,
        }
        if translation_error:
            payload["translation_error"] = translation_error
        if recognition_error:
            payload["recognition_error"] = recognition_error
        self.event_bus.publish(TranslationFinalEvent(meeting_id=meeting_id, payload=payload))

        trace(
            "offline_rescore_complete_at",
            utterance_id=utterance_id,
            meeting_id=meeting_id,
            seat_id=seat_id,
            offline_asr_ms=offline_ms,
            translation_ms=translation_ms,
            translation_id=record.id,
            recognition_status=recognition_status,
            translation_status=translation_status,
        )
        return record

    def get_history(
        self, meeting_id: int, seat_id: int | None = None,
    ) -> list[TranslationRecord]:
        return self.repo.list_by_meeting(meeting_id, seat_id=seat_id)

    def reset_session(self, session_key: str) -> None:
        self._ensure_preloaded()
        _get_speech().reset_interim(session_key)
