"""Bounded single-worker queue for automatic speech finalization."""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass

from backend.database import SessionLocal
from backend.events import event_bus
from backend.events.translation_events import TranslationInterimCancelledEvent
from backend.services.translation_service import TranslationService

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

    @property
    def pending_count(self) -> int:
        with self._lock:
            return self._queue.qsize() + self._active

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
            if not translate:
                logger.warning(
                    "Speech translation backlog full; queued source-only: "
                    "utterance=%s",
                    job.utterance_id,
                )
            return translate
        except queue.Full:
            logger.warning(
                "Speech finalization overflow full; saving source only now: "
                "utterance=%s",
                job.utterance_id,
            )
            # This path intentionally skips translation and offline ASR. The
            # only synchronous work left is a short SQLite insert, preserving
            # the recognized Chinese text instead of dropping the segment.
            self._process(job, translate=False)
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
            with self._lock:
                self._active = 1
            try:
                self._process(job, translate=translate)
            finally:
                with self._lock:
                    self._active = 0
                self._queue.task_done()

    @staticmethod
    def _process(job: SpeechFinalizationJob, *, translate: bool) -> None:
        started = time.monotonic()
        db = SessionLocal()
        try:
            service = TranslationService(db, event_bus)
            service.process_final_text(
                source_text=job.source_text,
                meeting_id=job.meeting_id,
                seat_id=job.seat_id,
                utterance_id=job.utterance_id,
                source_type="speech_ws",
                translate=translate,
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
