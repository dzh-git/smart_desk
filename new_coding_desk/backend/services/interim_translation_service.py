"""Latest-wins background translation for streaming ASR partials."""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

from backend.events import event_bus
from backend.events.translation_events import TranslationInterimEvent
from backend.events.translation_events import TranslationSentenceEvent
from backend.services.translation_model_service import (
    NOT_AVAILABLE,
    TranslationModelService,
)
from backend.websocket.speech_trace import trace
from backend.services.speech_inference_runtime import inference_runtime

logger = logging.getLogger(__name__)


def caption_window_text(
    source_text: str,
    caption: dict[str, object] | None,
    source_lang: str,
) -> str:
    """Return only the source text currently visible in the two-line caption."""
    if not caption:
        return source_text.strip()
    lines = [
        str(caption.get("previous_line") or "").strip(),
        str(caption.get("current_line") or "").strip(),
    ]
    visible = [line for line in lines if line]
    if not visible:
        return source_text.strip()
    return ("" if source_lang == "zh" else " ").join(visible)


@dataclass(frozen=True)
class InterimTranslationJob:
    session_key: str
    meeting_id: int
    seat_id: int
    utterance_id: str
    revision: int
    source_lang: str
    target_lang: str
    source_text: str


class InterimTranslationService:
    """Translate only the newest partial without blocking audio reception."""

    def __init__(
        self,
        *,
        debounce_seconds: float = 0.20,
        max_debounce_seconds: float = 0.60,
        translation_model: TranslationModelService | None = None,
    ) -> None:
        self._debounce_seconds = debounce_seconds
        self._max_debounce_seconds = max_debounce_seconds
        self._translation_model = translation_model
        self._condition = threading.Condition()
        self._pending: dict[str, InterimTranslationJob] = {}
        self._last_submitted: dict[str, tuple[str, str]] = {}
        self._worker: threading.Thread | None = None
        self._active = 0

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending) + self._active

    def submit(self, job: InterimTranslationJob) -> bool:
        clean = job.source_text.strip()
        meaningful = sum(ch.isalnum() for ch in clean)
        if meaningful < 2 or job.source_lang not in {"zh", "en"}:
            return False

        signature = (job.utterance_id, clean)
        with self._condition:
            if self._last_submitted.get(job.session_key) == signature:
                return False
            self._last_submitted[job.session_key] = signature
            self._pending[job.session_key] = job
            self._ensure_worker_locked()
            self._condition.notify_all()
        return True

    def cancel(self, session_key: str, utterance_id: str | None = None) -> None:
        with self._condition:
            pending = self._pending.get(session_key)
            if pending is not None and (
                utterance_id is None or pending.utterance_id == utterance_id
            ):
                self._pending.pop(session_key, None)
            signature = self._last_submitted.get(session_key)
            if signature is not None and (
                utterance_id is None or signature[0] == utterance_id
            ):
                self._last_submitted.pop(session_key, None)

    def wait_for_idle(self, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._pending or self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def _ensure_worker_locked(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._run,
            name="speech-interim-translation",
            daemon=True,
        )
        self._worker.start()

    def _take_debounced_job(self) -> InterimTranslationJob:
        with self._condition:
            while not self._pending:
                self._condition.wait()
            session_key, job = next(iter(self._pending.items()))
            self._pending.pop(session_key, None)

            quiet_deadline = time.monotonic() + self._debounce_seconds
            hard_deadline = time.monotonic() + self._max_debounce_seconds
            while True:
                remaining = min(quiet_deadline, hard_deadline) - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
                newer = self._pending.pop(session_key, None)
                if newer is not None:
                    job = newer
                    quiet_deadline = time.monotonic() + self._debounce_seconds
            self._active = 1
            return job

    def _run(self) -> None:
        while True:
            job = self._take_debounced_job()
            try:
                model = self._translation_model or TranslationModelService.get_instance()
                translated = model.translate(
                    job.source_text,
                    job.source_lang,
                    job.target_lang,
                )
                available = bool(translated and translated != NOT_AVAILABLE)
                event_bus.publish(TranslationInterimEvent(
                    meeting_id=job.meeting_id,
                    payload={
                        "utterance_id": job.utterance_id,
                        "seat_id": job.seat_id,
                        "revision": job.revision,
                        "translation_revision": job.revision,
                        "source_lang": job.source_lang,
                        "target_lang": job.target_lang,
                        "source_text": job.source_text,
                        "translation_source_text": job.source_text,
                        "translated_text": translated if available else "",
                        "translation_only": True,
                        "translation_status": "ok" if available else "unavailable",
                        "is_final": False,
                    },
                ))
            except Exception:
                logger.exception(
                    "Realtime interim translation failed: utterance=%s revision=%d",
                    job.utterance_id,
                    job.revision,
                )
            finally:
                with self._condition:
                    self._active = 0
                    self._condition.notify_all()


interim_translation_service = InterimTranslationService()


@dataclass(frozen=True)
class SentenceTranslationJob:
    """A committed semantic sentence that must be translated in order."""

    meeting_id: int
    seat_id: int
    utterance_id: str
    sentence_id: str
    sentence_sequence: int
    revision: int
    source_lang: str
    target_lang: str
    source_text: str
    recognition_status: str = "ok"
    source_locked: bool = True
    queued_at_monotonic: float = field(
        default_factory=time.monotonic, compare=False, repr=False,
    )


@dataclass(frozen=True)
class EnglishSentenceCorrectionJob:
    """One frozen Zipformer sentence waiting for its SenseVoice correction."""

    meeting_id: int
    seat_id: int
    utterance_id: str
    sentence_id: str
    sentence_sequence: int
    revision: int
    source_text: str
    audio: object


class EnglishSentenceCorrectionService:
    """Serialize English sentence-final ASR before translation.

    Zipformer stays on the latency-critical PCM path.  This worker only sees
    a copied sentence PCM snapshot, and yields whenever live audio is backed
    up.  It publishes the one allowed source-text replacement, then hands the
    locked result to the normal ordered translation queue.
    """

    def __init__(self, *, max_queue_size: int = 32) -> None:
        self._queue: queue.Queue[EnglishSentenceCorrectionJob] = queue.Queue(
            maxsize=max_queue_size,
        )
        self._lock = threading.Lock()
        self._submitted: set[str] = set()
        self._worker: threading.Thread | None = None

    def submit(self, job: EnglishSentenceCorrectionJob) -> bool:
        with self._lock:
            if job.sentence_id in self._submitted:
                return False
            self._submitted.add(job.sentence_id)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._run,
                    name="speech-english-sentence-correction",
                    daemon=True,
                )
                self._worker.start()
        try:
            self._queue.put_nowait(job)
            trace(
                "english_sentence_correction_queued_at",
                utterance_id=job.utterance_id,
                meeting_id=job.meeting_id,
                seat_id=job.seat_id,
                sentence_id=job.sentence_id,
                sentence_sequence=job.sentence_sequence,
            )
            return True
        except queue.Full:
            with self._lock:
                self._submitted.discard(job.sentence_id)
            self._publish_locked(job, job.source_text, "degraded")
            return False

    @staticmethod
    def _fallback(text: str) -> str:
        from backend.speech_module.text_utils import format_english_streaming_display

        return format_english_streaming_display(text, sentence_complete=True)

    def _publish_locked(
        self,
        job: EnglishSentenceCorrectionJob,
        text: str,
        recognition_status: str,
    ) -> None:
        source_text = text.strip() or self._fallback(job.source_text)
        locked_revision = job.revision + 1
        payload = {
            "utterance_id": job.utterance_id,
            "sentence_id": job.sentence_id,
            "sentence_sequence": job.sentence_sequence,
            "seat_id": job.seat_id,
            "revision": locked_revision,
            "source_lang": "en",
            "target_lang": "zh",
            "source_text": source_text,
            "translated_text": "",
            "translation_status": "pending",
            "recognition_status": recognition_status,
            "source_locked": True,
            "is_final": False,
        }
        event_bus.publish(TranslationSentenceEvent(
            meeting_id=job.meeting_id,
            payload=payload,
        ))
        trace(
            "english_sentence_correction_locked_at",
            utterance_id=job.utterance_id,
            meeting_id=job.meeting_id,
            seat_id=job.seat_id,
            sentence_id=job.sentence_id,
            sentence_sequence=job.sentence_sequence,
            recognition_status=recognition_status,
        )
        sentence_translation_service.submit(SentenceTranslationJob(
            meeting_id=job.meeting_id,
            seat_id=job.seat_id,
            utterance_id=job.utterance_id,
            sentence_id=job.sentence_id,
            sentence_sequence=job.sentence_sequence,
            revision=locked_revision,
            source_lang="en",
            target_lang="zh",
            source_text=source_text,
            recognition_status=recognition_status,
            source_locked=True,
        ))

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                inference_runtime.wait_for_medium(
                    trace_fields={
                        "utterance_id": job.utterance_id,
                        "meeting_id": job.meeting_id,
                        "seat_id": job.seat_id,
                        "sentence_id": job.sentence_id,
                    },
                )
                from backend.speech_module.bilingual_asr import recognize_bilingual
                from backend.speech_module.text_utils import normalize_english_sentence_final

                result = recognize_bilingual(job.audio, language="en")
                corrected = normalize_english_sentence_final(result.text)
                self._publish_locked(
                    job,
                    corrected or self._fallback(job.source_text),
                    "ok" if corrected else "degraded",
                )
            except Exception:
                logger.exception(
                    "English sentence correction failed: sentence=%s",
                    job.sentence_id,
                )
                self._publish_locked(job, self._fallback(job.source_text), "degraded")
            finally:
                with self._lock:
                    self._submitted.discard(job.sentence_id)
                self._queue.task_done()


class SentenceTranslationService:
    """FIFO translation worker for completed lyric sentences.

    Unlike interim partial translation, completed sentences are never
    replaced by newer work.  De-duplication is by sentence_id and completed
    results are broadcast with the same identity as the pending event.
    """

    def __init__(
        self,
        *,
        max_queue_size: int = 64,
        translation_model: TranslationModelService | None = None,
    ) -> None:
        self._queue: queue.Queue[SentenceTranslationJob] = queue.Queue(
            maxsize=max_queue_size,
        )
        self._translation_model = translation_model
        self._lock = threading.Lock()
        self._submitted: dict[str, int] = {}
        self._worker: threading.Thread | None = None
        self._active = 0
        self._submitted_count = 0
        self._completed_count = 0
        self._last_queue_wait_ms = 0
        self._max_queue_wait_ms = 0
        self._last_inference_ms = 0
        self._max_inference_ms = 0

    @property
    def pending_count(self) -> int:
        return int(self._queue.unfinished_tasks)

    def get_diagnostics(self) -> dict[str, int]:
        with self._lock:
            return {
                "pending": int(self._queue.unfinished_tasks),
                "queued": self._queue.qsize(),
                "active": self._active,
                "queue_capacity": self._queue.maxsize,
                "submitted_count": self._submitted_count,
                "completed_count": self._completed_count,
                "last_queue_wait_ms": self._last_queue_wait_ms,
                "max_queue_wait_ms": self._max_queue_wait_ms,
                "last_inference_ms": self._last_inference_ms,
                "max_inference_ms": self._max_inference_ms,
            }

    def submit(self, job: SentenceTranslationJob) -> bool:
        clean = job.source_text.strip()
        if (
            sum(ch.isalnum() for ch in clean) < 2
            or job.source_lang not in {"zh", "en"}
        ):
            return False
        with self._lock:
            if job.revision <= self._submitted.get(job.sentence_id, -1):
                return False
            if len(self._submitted) >= 4096:
                self._submitted.pop(next(iter(self._submitted)))
            self._submitted[job.sentence_id] = job.revision
            self._ensure_worker_locked()
        try:
            self._queue.put_nowait(job)
            with self._lock:
                self._submitted_count += 1
                queue_depth = int(self._queue.unfinished_tasks)
            trace(
                "sentence_translation_queued_at",
                utterance_id=job.utterance_id,
                meeting_id=job.meeting_id,
                seat_id=job.seat_id,
                sentence_id=job.sentence_id,
                sentence_sequence=job.sentence_sequence,
                revision=job.revision,
                queue_depth=queue_depth,
                source_text_len=len(clean),
            )
            return True
        except queue.Full:
            with self._lock:
                if self._submitted.get(job.sentence_id) == job.revision:
                    self._submitted.pop(job.sentence_id, None)
            self._publish_result(
                job,
                translated_text="",
                status="unavailable",
                error="sentence translation queue is full",
            )
            trace(
                "sentence_translation_queue_overflow_at",
                utterance_id=job.utterance_id,
                meeting_id=job.meeting_id,
                seat_id=job.seat_id,
                sentence_id=job.sentence_id,
                sentence_sequence=job.sentence_sequence,
                queue_depth=self.pending_count,
            )
            return False

    def wait_for_idle(self, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.pending_count == 0:
                return True
            time.sleep(0.01)
        return self.pending_count == 0

    def reset_for_tests(self) -> None:
        """Forget completed ids after the worker becomes idle."""
        self.wait_for_idle()
        with self._lock:
            self._submitted.clear()

    def _ensure_worker_locked(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._run,
            name="speech-sentence-translation",
            daemon=True,
        )
        self._worker.start()

    @staticmethod
    def _payload(job: SentenceTranslationJob) -> dict[str, object]:
        return {
            "utterance_id": job.utterance_id,
            "sentence_id": job.sentence_id,
            "sentence_sequence": job.sentence_sequence,
            "seat_id": job.seat_id,
            "revision": job.revision,
            "source_lang": job.source_lang,
            "target_lang": job.target_lang,
            "source_text": job.source_text,
            "recognition_status": job.recognition_status,
            "source_locked": job.source_locked,
        }

    def _publish_result(
        self,
        job: SentenceTranslationJob,
        *,
        translated_text: str,
        status: str,
        error: str | None = None,
    ) -> None:
        payload = self._payload(job)
        payload.update({
            "translated_text": translated_text,
            "translation_status": status,
            "is_final": False,
        })
        if error:
            payload["translation_error"] = error
        event_bus.publish(TranslationSentenceEvent(
            meeting_id=job.meeting_id,
            payload=payload,
        ))
        trace(
            "sentence_translation_broadcast_at",
            utterance_id=job.utterance_id,
            meeting_id=job.meeting_id,
            seat_id=job.seat_id,
            sentence_id=job.sentence_id,
            sentence_sequence=job.sentence_sequence,
            revision=job.revision,
            translation_status=status,
            translated_text_len=len(translated_text),
        )

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            queue_wait_ms = round(
                (time.monotonic() - job.queued_at_monotonic) * 1000,
            )
            with self._lock:
                self._active = 1
                self._last_queue_wait_ms = queue_wait_ms
                self._max_queue_wait_ms = max(
                    self._max_queue_wait_ms, queue_wait_ms,
                )
                queue_depth = int(self._queue.unfinished_tasks)
            trace(
                "sentence_translation_dequeued_at",
                utterance_id=job.utterance_id,
                meeting_id=job.meeting_id,
                seat_id=job.seat_id,
                sentence_id=job.sentence_id,
                sentence_sequence=job.sentence_sequence,
                revision=job.revision,
                queue_wait_ms=queue_wait_ms,
                queue_depth=queue_depth,
            )
            inference_started = time.monotonic()
            try:
                inference_runtime.wait_for_medium(
                    trace_fields={
                        "utterance_id": job.utterance_id,
                        "meeting_id": job.meeting_id,
                        "seat_id": job.seat_id,
                        "sentence_id": job.sentence_id,
                    },
                )
                model = self._translation_model or TranslationModelService.get_instance()
                try:
                    translated = model.translate(
                        job.source_text,
                        job.source_lang,
                        job.target_lang,
                        quality="live",
                    )
                except TypeError:
                    # Compatibility for small test doubles and third-party
                    # adapters implementing the historical three-argument API.
                    translated = model.translate(
                        job.source_text,
                        job.source_lang,
                        job.target_lang,
                    )
                available = bool(translated and translated != NOT_AVAILABLE)
                self._publish_result(
                    job,
                    translated_text=translated if available else "",
                    status="ok" if available else "unavailable",
                    error=None if available else "translation model unavailable",
                )
            except Exception as exc:
                logger.exception(
                    "Sentence translation failed: sentence=%s sequence=%d",
                    job.sentence_id,
                    job.sentence_sequence,
                )
                self._publish_result(
                    job,
                    translated_text="",
                    status="unavailable",
                    error=str(exc),
                )
            finally:
                inference_ms = round(
                    (time.monotonic() - inference_started) * 1000,
                )
                with self._lock:
                    self._active = 0
                    self._completed_count += 1
                    self._last_inference_ms = inference_ms
                    self._max_inference_ms = max(
                        self._max_inference_ms, inference_ms,
                    )
                self._queue.task_done()
                trace(
                    "sentence_translation_inference_end_at",
                    utterance_id=job.utterance_id,
                    meeting_id=job.meeting_id,
                    seat_id=job.seat_id,
                    sentence_id=job.sentence_id,
                    sentence_sequence=job.sentence_sequence,
                    revision=job.revision,
                    queue_wait_ms=queue_wait_ms,
                    inference_ms=inference_ms,
                    queue_depth=self.pending_count,
                )


sentence_translation_service = SentenceTranslationService()
english_sentence_correction_service = EnglishSentenceCorrectionService()
