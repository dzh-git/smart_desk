"""Bounded single-worker queue for automatic speech finalization."""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from backend.database import SessionLocal
from backend.events import event_bus
from backend.events.translation_events import TranslationInterimCancelledEvent
from backend.services.translation_service import TranslationService
from backend.services.speech_inference_runtime import inference_runtime
from backend.services.speech_debug_capture import update_speech_debug_final_result
from backend.websocket.speech_trace import trace

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeechFinalizationJob:
    meeting_id: int
    seat_id: int
    utterance_id: str
    source_text: str
    boundary_reason: str
    audio_seconds: float
    next_utterance_id: str | None = None
    audio: np.ndarray | None = None
    sample_rate: int = 16000
    recognized_text: str = ""
    detected_language: str = "unknown"
    recognition_engine: str = "unknown"
    recognition_status: str = "ok"
    queued_at_monotonic: float = field(
        default_factory=time.monotonic, compare=False, repr=False,
    )


class SpeechFinalizationQueue:
    """Serializes translation model access without blocking audio reception."""

    def __init__(self, max_pending: int = 8) -> None:
        self._translation_capacity = max_pending
        self._queue: queue.Queue[tuple[SpeechFinalizationJob, bool]] = queue.Queue(
            # The second half is a bounded source-only overflow. It uses the
            # same worker, so database record order remains deterministic.
            maxsize=max_pending * 2,
        )
        self._active = 0
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._submitted_count = 0
        self._completed_count = 0
        self._last_queue_wait_ms = 0
        self._max_queue_wait_ms = 0
        self._last_processing_ms = 0
        self._max_processing_ms = 0

    @property
    def pending_count(self) -> int:
        with self._lock:
            return self._queue.qsize() + self._active

    def get_diagnostics(self) -> dict[str, int]:
        with self._lock:
            return {
                "pending": self._queue.qsize() + self._active,
                "queued": self._queue.qsize(),
                "active": self._active,
                "translation_capacity": self._translation_capacity,
                "queue_capacity": self._queue.maxsize,
                "submitted_count": self._submitted_count,
                "completed_count": self._completed_count,
                "last_queue_wait_ms": self._last_queue_wait_ms,
                "max_queue_wait_ms": self._max_queue_wait_ms,
                "last_processing_ms": self._last_processing_ms,
                "max_processing_ms": self._max_processing_ms,
            }

    def submit(self, job: SpeechFinalizationJob) -> bool:
        """Queue a translated final, falling back to a fast source-only save."""
        self._ensure_worker()
        with self._lock:
            translate = (
                self._queue.qsize() + self._active
                < self._translation_capacity
            )
        try:
            self._queue.put_nowait((job, translate))
            with self._lock:
                self._submitted_count += 1
                queue_depth = self._queue.qsize() + self._active
            trace(
                "finalization_queued_at",
                utterance_id=job.utterance_id,
                meeting_id=job.meeting_id,
                seat_id=job.seat_id,
                queue_depth=queue_depth,
                translate=translate,
                boundary_reason=job.boundary_reason,
                audio_seconds=job.audio_seconds,
            )
            if not translate:
                logger.warning(
                    "Speech translation backlog full; queued source-only: "
                    "utterance=%s",
                    job.utterance_id,
                )
            return translate
        except queue.Full:
            trace(
                "finalization_queue_overflow_at",
                utterance_id=job.utterance_id,
                meeting_id=job.meeting_id,
                seat_id=job.seat_id,
                queue_depth=self.pending_count,
            )
            logger.warning(
                "Speech finalization overflow full; saving source only now: "
                "utterance=%s",
                job.utterance_id,
            )
            # This path intentionally skips translation and offline ASR. The
            # only synchronous work left is a short SQLite insert, preserving
            # the recognized Chinese text instead of dropping the segment.
            self._process(job, translate=False, use_audio=False)
            return False

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._run,
                name="speech-finalization",
                daemon=True,
            )
            self._worker.start()

    def _run(self) -> None:
        while True:
            job, translate = self._queue.get()
            queue_wait_ms = round(
                (time.monotonic() - job.queued_at_monotonic) * 1000,
            )
            with self._lock:
                self._active = 1
                self._last_queue_wait_ms = queue_wait_ms
                self._max_queue_wait_ms = max(
                    self._max_queue_wait_ms, queue_wait_ms,
                )
                queue_depth = self._queue.qsize() + self._active
            trace(
                "finalization_dequeued_at",
                utterance_id=job.utterance_id,
                meeting_id=job.meeting_id,
                seat_id=job.seat_id,
                queue_wait_ms=queue_wait_ms,
                queue_depth=queue_depth,
                translate=translate,
            )
            processing_started = time.monotonic()
            try:
                inference_runtime.wait_for_final(
                    boundary_reason=job.boundary_reason,
                    trace_fields={
                        "utterance_id": job.utterance_id,
                        "meeting_id": job.meeting_id,
                        "seat_id": job.seat_id,
                    },
                )
                self._process(job, translate=translate)
            finally:
                processing_ms = round(
                    (time.monotonic() - processing_started) * 1000,
                )
                with self._lock:
                    self._active = 0
                    self._completed_count += 1
                    self._last_processing_ms = processing_ms
                    self._max_processing_ms = max(
                        self._max_processing_ms, processing_ms,
                    )
                self._queue.task_done()
                trace(
                    "finalization_worker_completed_at",
                    utterance_id=job.utterance_id,
                    meeting_id=job.meeting_id,
                    seat_id=job.seat_id,
                    processing_ms=processing_ms,
                    queue_wait_ms=queue_wait_ms,
                    queue_depth=self.pending_count,
                    translate=translate,
                )

    @staticmethod
    def _process(
        job: SpeechFinalizationJob,
        *,
        translate: bool,
        use_audio: bool = True,
    ) -> None:
        started = time.monotonic()
        db = SessionLocal()
        try:
            service = TranslationService(db, event_bus)
            if job.recognized_text.strip() and job.recognition_engine == "sensevoice_rolling":
                record = service.process_final_text(
                    source_text=job.recognized_text,
                    source_lang=job.detected_language,
                    meeting_id=job.meeting_id,
                    seat_id=job.seat_id,
                    utterance_id=job.utterance_id,
                    source_type="speech_ws",
                    translate=translate,
                    recognition_status=job.recognition_status,
                    recognition_error=(
                        None if job.recognition_status == "ok"
                        else "SenseVoice rolling correction failed; last valid text retained"
                    ),
                )
            elif use_audio and job.audio is not None and len(job.audio) > 0:
                record = service.process_final_array(
                    audio=job.audio,
                    sr=job.sample_rate,
                    meeting_id=job.meeting_id,
                    seat_id=job.seat_id,
                    utterance_id=job.utterance_id,
                    source_type="speech_ws",
                    fallback_source_text=job.source_text,
                    translate=translate,
                )
            else:
                record = service.process_final_text(
                    source_text=job.source_text,
                    meeting_id=job.meeting_id,
                    seat_id=job.seat_id,
                    utterance_id=job.utterance_id,
                    source_type="speech_ws",
                    translate=translate,
                    recognition_error=(
                        "Finalization queue overflow; streaming ASR text was preserved"
                        if not use_audio else "Final audio was unavailable"
                    ),
                )
            try:
                update_speech_debug_final_result(
                    job.utterance_id,
                    translation_id=record.id,
                    source_text=record.source_text,
                    source_lang=record.source_lang,
                    source_type=record.source_type,
                    recognition_status=job.recognition_status,
                )
            except Exception:
                logger.exception(
                    "Speech debug final-result update failed: utterance=%s",
                    job.utterance_id,
                )
            logger.info(
                "Speech auto-final complete: utterance=%s reason=%s "
                "text_len=%d audio_seconds=%.2f translation_ms=%d next=%s",
                job.utterance_id,
                job.boundary_reason,
                len(job.source_text),
                job.audio_seconds,
                round((time.monotonic() - started) * 1000),
                job.next_utterance_id,
            )
        except Exception:
            logger.exception(
                "Speech background finalization failed: utterance=%s",
                job.utterance_id,
            )
            event_bus.publish(TranslationInterimCancelledEvent(
                meeting_id=job.meeting_id,
                payload={
                    "utterance_id": job.utterance_id,
                    "seat_id": job.seat_id,
                    "reason": "finalization_failed",
                },
            ))
        finally:
            db.close()


finalization_queue = SpeechFinalizationQueue()
