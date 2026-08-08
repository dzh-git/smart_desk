"""
SpeechStreamService — manages speech stream sessions and utterance IDs.

Per WEBSOCKET_PROTOCOL §3-4, ADR 0003:
    Session lifecycle: connected → start → PCM16 stream → end_hint/cancel → disconnect.
    utterance_id format: utt_{meeting_id}_{seat_id}_{seq:06d}.
    session_key format: speech_{meeting_id}_{seat_id}.

Phase 2 scope:
    - Session creation/removal
    - Utterance ID generation

Phase 3 additions:
    - PCM16 → float32 conversion
    - Revision tracking per utterance
    - SpeechModule integration (streaming ASR via process_interim_array)
    - EventBus events for translation_interim
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from backend.services.speech_inference_runtime import inference_runtime
from backend.services.speech_debug_capture import (
    record_speech_debug_decoder_call,
    record_speech_debug_revision,
    save_speech_debug_capture,
)

import numpy as np

from backend.speech_module.caption_formatter import CaptionFormatter
from backend.speech_module.english_punctuation import (
    add_english_punctuation,
    get_english_punctuation_status,
    has_trusted_terminal_boundary,
    strip_provisional_terminal,
)
from backend.speech_module.punctuation import ALL_BOUNDARY
from backend.speech_module.text_utils import (
    format_english_streaming_display,
    merge_texts,
    merge_english_transcripts,
    normalize_english_display,
)
from backend.websocket.speech_trace import trace
from backend.events import event_bus
from backend.events.speech_events import (
    SpeakerSpeakingEvent,
    SpeakerSpeakingStopEvent,
)

logger = logging.getLogger(__name__)

# ── VAD configuration (Task 122) ──────────────────────────────────────────────

# Adaptive low-latency voice gate defaults.  Values are float32 PCM RMS.
# Deployed browser microphones can produce clean speech around 6 mRMS.  Keep
# the absolute floor just above the measured steady-noise band (about 4 mRMS)
# and let the adaptive noise ratios raise it in louder rooms.
VAD_SILENCE_THRESHOLD_RMS: float = 0.005  # compatibility alias / minimum onset
VAD_CONTINUE_THRESHOLD_RMS: float = 0.0045
VAD_NOISE_START_RATIO: float = 2.0
VAD_NOISE_CONTINUE_RATIO: float = 1.5
VAD_CALIBRATION_FRAMES: int = 3          # 300 ms at 100 ms/frame
VAD_PRE_ROLL_FRAMES: int = 3             # retain the first consonants
VAD_START_CONFIRM_FRAMES: int = 2
LIVE_ASR_LANGUAGE_MODES = frozenset({"auto", "zh", "en"})
SENSEVOICE_AUTO_PROBE_SECONDS = 1.2
SENSEVOICE_LIVE_INTERVAL_SECONDS = 1.0
SENSEVOICE_LIVE_WINDOW_SECONDS = 8.0
SENSEVOICE_LIVE_WINDOW_FRAMES = round(SENSEVOICE_LIVE_WINDOW_SECONDS * 10)

# Boundary policy: punctuation + pause first, silence fallback last.
VAD_SENTENCE_PAUSE_S: float = 0.9
VAD_CHINESE_FINALIZE_PAUSE_S: float = 2.0
VAD_CLAUSE_PAUSE_S: float = 1.3
VAD_NATURAL_PAUSE_S: float = 2.0
VAD_SILENCE_DURATION_S: float = 3.0      # compatibility alias / hard silence
VAD_SOFT_UTTERANCE_S: float = 30.0
VAD_MAX_UTTERANCE_S: float = 45.0
ROLLOVER_OVERLAP_MS: int = 300
ROLLOVER_OVERLAP_BYTES: int = int(16000 * 2 * ROLLOVER_OVERLAP_MS / 1000)
CONTINUOUS_ROLLOVER_REASONS = frozenset({
    "soft_sentence_limit",
    "max_duration",
})
SEMANTIC_SENTENCE_END = frozenset("。！？.!?")
ENGLISH_CLAUSE_COMMIT_WORDS = 40
ENGLISH_FORCE_COMMIT_WORDS = 50
ENGLISH_CLAUSE_END = frozenset(",;:，；：")
SENTENCE_COMMIT_REASONS = frozenset({
    "english_sentence_pause",
    "sentence_pause",
    "natural_pause",
    "hard_silence",
    "soft_sentence_limit",
    "max_duration",
    "end_hint",
})

# ── Utterance state machine constants (Task 122) ──────────────────────────────

UTTERANCE_STATE_IDLE = "IDLE"
UTTERANCE_STATE_SPEAKING = "SPEAKING"
UTTERANCE_STATE_PENDING_END = "PENDING_END"
UTTERANCE_STATE_FINALIZING = "FINALIZING"
UTTERANCE_STATE_READY_FOR_NEXT = "READY_FOR_NEXT"


class SpeechStreamSession:
    """A single speech stream session for one (meeting_id, seat_id) pair.

    Each session corresponds to one speech WebSocket connection from the
    current Speaker Seat. Sessions are tracked by session_key.
    """

    def __init__(
        self, meeting_id: int, seat_id: int, session_key: str
    ) -> None:
        self.meeting_id = meeting_id
        self.seat_id = seat_id
        self.session_key = session_key
        self.session_token: str = uuid.uuid4().hex  # unique per connection
        self.created_at = datetime.now(timezone.utc)
        self.utterance_count: int = 0
        # Phase 3: per-utterance tracking
        self.current_utterance_id: str | None = None
        self.revision: int = 0
        # Phase 02: per-session caption formatter for punctuated two-line captions
        self.caption_formatter: CaptionFormatter = CaptionFormatter()
        # Phase 4: PCM16 audio buffer for current utterance (concatenated raw bytes)
        self._utterance_buffer: list[bytes] = []
        # Task 122: VAD state tracking
        self.utterance_state: str = UTTERANCE_STATE_IDLE
        self.vad_silence_seconds: float = 0.0
        self.noise_floor_rms: float = 0.003
        self.calibration_frames_remaining = VAD_CALIBRATION_FRAMES
        self.voice_start_frames = 0
        self.voice_active = False
        self.has_speech = False
        # Live capture diagnostics. These distinguish a connected-but-silent
        # browser from PCM that is arriving below the adaptive voice gate.
        self.pcm_frames_received: int = 0
        self.pcm_bytes_received: int = 0
        self.last_input_rms: float = 0.0
        self.peak_input_rms: float = 0.0
        self.last_pcm_at: float | None = None
        self.processed_frames: int = 0
        self.last_processing_ms: int = 0
        self.peak_processing_ms: int = 0
        self.speaking_event_active = False
        self.utterance_audio_seconds = 0.0
        self.last_streaming_text = ""
        self.last_source_text = ""
        self.speech_debug_decoder_calls: list[dict[str, Any]] = []
        self.speech_debug_revisions: list[dict[str, Any]] = []
        self.last_caption: dict[str, str] = {
            "previous_line": "",
            "current_line": "",
            "mode": "two_line",
        }
        self._pre_roll: deque[bytes] = deque(maxlen=VAD_PRE_ROLL_FRAMES)
        self._rollover_overlap_pcm: bytes = b""
        self._rollover_started_at: float | None = None
        # Task 126: terminal utterance_id set — prevents duplicate final/cancel
        # for the same utterance_id. Each utterance_id can only be terminal once.
        self.terminal_utterance_ids: set[str] = set()
        # Semantic lyric sentence tracking is intentionally independent from
        # CaptionFormatter's visual two-line wrapping.
        self.sentence_sequence: int = 0
        self.active_sentence_id: str | None = None
        self.active_sentence_sequence: int = 0
        self.sentence_committed_raw_len: int = 0
        # English uses one online decoder per semantic sentence.  A completed
        # sentence is never reconstructed from a later cumulative hypothesis.
        self.english_sentence_start_frame: int = 0
        self.english_committed_text_len: int = 0
        # Task 130: bilingual live recognition routing.
        self.requested_language: str = "auto"
        self.detected_language: str = "unknown"
        self.recognition_engine: str = "unknown"
        self.last_sensevoice_inference_audio_seconds: float = 0.0
        self.last_sensevoice_text: str = ""
        self.sensevoice_window_start_frame: int = 0
        self.sensevoice_task_running: bool = False
        self.sensevoice_last_error: str | None = None
        # True English streaming diagnostics. SenseVoice remains only for LID,
        # final correction, and the explicit local-model-missing fallback.
        self.english_streaming_frames: int = 0
        self.english_streaming_last_error: str | None = None
        self.english_streaming_flushed: bool = False
        # Chinese Paraformer keeps final CIF tokens in its streaming cache.
        # This flag ensures one explicit final flush per detected pause.
        self.chinese_streaming_flushed: bool = False
        self.english_punctuation_last_error: str | None = None
        self.english_punctuation_source_text: str = ""
        self.english_punctuation_text: str = ""
        self.english_punctuation_inference_ms: float = 0.0
        self.paraformer_replayed_frames: int = 0
        # PCM ingress diagnostics are updated by the WebSocket queue.
        self.pcm_queue_frames: int = 0
        self.audio_backlog_ms: int = 0
        self.peak_audio_backlog_ms: int = 0


class SpeechStreamService:
    """Manages speech stream sessions and utterance ID generation.

    Phase 3 additions:
        - SpeechModule (lazy-loaded) for streaming ASR
        - PCM16 → float32 conversion
        - Utterance revision counting
        - EventBus interim publication

    Thread-safety notes:
        FastAPI WebSocket handlers run in the asyncio event loop. All access
        to _sessions happens in the same event loop, so no locking is required.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SpeechStreamSession] = {}
        # Phase 3: SpeechModule (lazy-loaded on first PCM frame)
        self._speech_module = None
        self._speech_module_error: str | None = None
        # Phase 5: per-(meeting_id, seat_id) monotonically increasing
        # sequence counter for utterance_id. Lives outside session lifecycle
        # so that reconnect gets a new, non-conflicting ID (ADR 0003).
        self._utterance_sequences: dict[tuple[int, int], int] = {}
        self._sentence_sequences: dict[tuple[int, int], int] = {}
        # Task 119: background preload concurrency control
        self._preload_started: bool = False
        self._preload_lock: threading.Lock = threading.Lock()

    # ── SpeechModule (lazy-loaded) ───────────────────────────────────────────

    def _get_speech_module(self):
        """Lazy-load and preload SpeechModule. Raises RuntimeError on failure.

        If a background preload was already started (via
        _preload_speech_models_background), waits for it to finish.
        Thread-safe — SpeechModule.preload() handles lock-based concurrency.

        If no background preload was triggered, this performs a synchronous
        preload (original lazy-init path, e.g. first PCM frame arriving before
        background preload completes).
        """
        if self._speech_module_error:
            raise RuntimeError(self._speech_module_error)
        if self._speech_module is None:
            from backend.speech_module import SpeechModule

            module = SpeechModule()
            try:
                module.preload()
                self._speech_module = module
            except Exception as exc:
                self._speech_module_error = str(exc)
                raise RuntimeError(
                    f"Speech module not available: {exc}"
                )
        # If background preload is still running, wait for it.
        # Calling preload() again is safe — SpeechModule.preload()
        # blocks on its internal lock until the running preload finishes,
        # then returns immediately (idempotent).
        if not self._speech_module.ready:
            self._speech_module.preload()
        return self._speech_module

    @property
    def is_speech_available(self) -> bool:
        """True if SpeechModule has been loaded and is ready.

        Does NOT trigger loading — only returns current state.
        """
        return self._speech_module is not None and self._speech_module.ready

    def ensure_speech_module(self) -> bool:
        """Attempt to load SpeechModule. Returns True if models are ready.

        Triggers lazy load (preload models, warmup). Safe to call
        multiple times — cached on success or error.

        Returns:
            True if models are loaded and ready (streaming + offline ASR),
            False otherwise.
        """
        try:
            module = self._get_speech_module()
            return module.ready
        except RuntimeError:
            return False

    # ── Model status (Task 119) ───────────────────────────────────────────────

    def get_model_status(self) -> dict:
        """Return unified model readiness state.

        If SpeechModule has been created, returns its detailed status dict.
        Otherwise returns the initial pre-preload state.
        """
        if self._speech_module is not None:
            base = dict(self._speech_module.status)
        else:
            from backend.speech_module.speech_module import _INITIAL_STATUS
            base = dict(_INITIAL_STATUS)

        # Add the legacy Chinese punctuation fallback indicator. Loading and
        # preloading are transitional states, not failures; reporting fallback
        # there made the frontend show a false "model unavailable" warning.
        try:
            from backend.speech_module.punctuation import is_punctuation_loaded
            punctuation_status = base.get("punctuation_model", "unknown")
            base["punctuation_fallback"] = (
                punctuation_status == "error"
                or (
                    punctuation_status == "loaded"
                    and not is_punctuation_loaded()
                )
            )
        except Exception:
            base["punctuation_fallback"] = (
                base.get("punctuation_model") == "error"
            )

        try:
            from backend.services.translation_model_service import (
                TranslationModelService,
                is_translation_model_enabled,
            )
            translation = TranslationModelService.get_instance()
            model_statuses = translation.get_status()
            base["translation_models"] = model_statuses
            direction_states = [item["status"] for item in model_statuses.values()]
            base["translation_model"] = (
                "disabled" if not is_translation_model_enabled()
                else "loaded" if all(state == "loaded" for state in direction_states)
                else "error" if any(state == "error" for state in direction_states)
                else "unknown"
            )
            base["translation_model_path"] = translation.model_path
            base["translation_last_error"] = translation.load_error
        except Exception as exc:
            base["translation_model"] = "error"
            base["translation_last_error"] = str(exc)

        try:
            from backend.speech_module.bilingual_asr import get_bilingual_asr_status

            base["bilingual_final_asr"] = get_bilingual_asr_status()
        except Exception as exc:
            base["bilingual_final_asr"] = {
                "status": "error", "path": "", "error": str(exc),
            }

        try:
            from backend.speech_module.english_streaming import get_english_streaming_status

            base["english_streaming_asr"] = get_english_streaming_status()
        except Exception as exc:
            base["english_streaming_asr"] = {
                "status": "error", "path": "", "error": str(exc),
                "engine": "sherpa_onnx_streaming",
            }
        try:
            base["english_online_punctuation"] = get_english_punctuation_status()
        except Exception as exc:
            base["english_online_punctuation"] = {
                "status": "error", "path": "", "error": str(exc),
                "engine": "sherpa_onnx_online_punctuation",
                "last_inference_ms": 0.0,
            }

        try:
            from backend.speech_module.stt_streaming import get_offline_asr_status

            base["chinese_final_asr"] = get_offline_asr_status()
        except Exception as exc:
            base["chinese_final_asr"] = {
                "status": "error", "path": "", "error": str(exc),
            }

        base["voice_gate"] = {
            "minimum_onset_rms": VAD_SILENCE_THRESHOLD_RMS,
            "minimum_continue_rms": VAD_CONTINUE_THRESHOLD_RMS,
            "noise_start_ratio": VAD_NOISE_START_RATIO,
            "noise_continue_ratio": VAD_NOISE_CONTINUE_RATIO,
            "sentence_pause_seconds": VAD_SENTENCE_PAUSE_S,
            "chinese_finalize_pause_seconds": VAD_CHINESE_FINALIZE_PAUSE_S,
            "clause_pause_seconds": VAD_CLAUSE_PAUSE_S,
            "natural_pause_seconds": VAD_NATURAL_PAUSE_S,
            "hard_silence_seconds": VAD_SILENCE_DURATION_S,
            "soft_utterance_seconds": VAD_SOFT_UTTERANCE_S,
            "max_utterance_seconds": VAD_MAX_UTTERANCE_S,
        }

        base["active_sessions"] = self.active_session_count
        base["max_buffered_audio_seconds"] = self.max_buffered_audio_seconds()
        now = time.monotonic()
        base["sessions"] = [
            {
                "session_key": session.session_key,
                "meeting_id": session.meeting_id,
                "seat_id": session.seat_id,
                "utterance_id": session.current_utterance_id,
                "pcm_frames_received": session.pcm_frames_received,
                "pcm_bytes_received": session.pcm_bytes_received,
                "last_input_rms": round(session.last_input_rms, 6),
                "peak_input_rms": round(session.peak_input_rms, 6),
                "noise_floor_rms": round(session.noise_floor_rms, 6),
                "onset_threshold_rms": round(max(
                    VAD_SILENCE_THRESHOLD_RMS,
                    session.noise_floor_rms * VAD_NOISE_START_RATIO,
                ), 6),
                "voice_active": session.voice_active,
                "calibration_frames_remaining": session.calibration_frames_remaining,
                "last_pcm_age_ms": (
                    round((now - session.last_pcm_at) * 1000)
                    if session.last_pcm_at is not None else None
                ),
                "processed_frames": session.processed_frames,
                "last_processing_ms": session.last_processing_ms,
                "peak_processing_ms": session.peak_processing_ms,
                "pcm_queue_frames": session.pcm_queue_frames,
                "audio_backlog_ms": session.audio_backlog_ms,
                "peak_audio_backlog_ms": session.peak_audio_backlog_ms,
                "requested_language": session.requested_language,
                "detected_language": session.detected_language,
                "recognition_engine": session.recognition_engine,
                "sensevoice_rolling": {
                    "running": session.sensevoice_task_running,
                    "latest_pending": bool(
                        session.recognition_engine == "sensevoice_rolling_fallback"
                        and session.utterance_audio_seconds
                            > session.last_sensevoice_inference_audio_seconds
                    ),
                    "last_error": session.sensevoice_last_error,
                },
                "english_streaming": {
                    "engine": "sherpa_onnx_streaming",
                    "frames_processed": session.english_streaming_frames,
                    "flushed": session.english_streaming_flushed,
                    "last_error": session.english_streaming_last_error,
                    "fallback_active": (
                        session.recognition_engine == "sensevoice_rolling_fallback"
                    ),
                },
                "english_online_punctuation": {
                    "engine": "sherpa_onnx_online_punctuation",
                    "last_inference_ms": round(
                        session.english_punctuation_inference_ms, 2,
                    ),
                    "last_error": session.english_punctuation_last_error,
                    "source_text_len": len(
                        session.english_punctuation_source_text,
                    ),
                },
            }
            for session in self._sessions.values()
        ]
        base["soft_utterance_seconds"] = VAD_SOFT_UTTERANCE_S
        base["hard_utterance_seconds"] = VAD_MAX_UTTERANCE_S
        base["rollover_overlap_ms"] = ROLLOVER_OVERLAP_MS
        base["live_asr"] = {
            "language_modes": sorted(LIVE_ASR_LANGUAGE_MODES),
            "auto_probe_ms": round(SENSEVOICE_AUTO_PROBE_SECONDS * 1000),
            "sensevoice_interval_ms": round(SENSEVOICE_LIVE_INTERVAL_SECONDS * 1000),
            "sensevoice_window_ms": round(SENSEVOICE_LIVE_WINDOW_SECONDS * 1000),
            "english_streaming_engine": "sherpa_onnx_streaming",
            **inference_runtime.diagnostics(),
        }
        try:
            from backend.services.speech_finalization_service import finalization_queue
            base["pending_finalizations"] = finalization_queue.pending_count
        except Exception:
            base["pending_finalizations"] = 0
        try:
            import os
            import psutil
            base["process_rss_mb"] = round(
                psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024),
                1,
            )
        except Exception:
            base["process_rss_mb"] = None

        return base

    # ── VAD detection (Task 122) ─────────────────────────────────────────────

    @staticmethod
    def _compute_rms(audio: np.ndarray) -> float:
        """Compute RMS (root mean square) of a float32 audio array.

        Args:
            audio: float32 numpy array, e.g. from pcm16_to_float32().

        Returns:
            RMS value as float.
        """
        return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))

    def _check_vad_end(self, session_key: str, audio: np.ndarray) -> bool:
        """Compatibility helper: hard-silence decision for an active voice."""
        session = self._sessions.get(session_key)
        if session is None:
            return False
        rms = self._compute_rms(audio)
        frame_duration_s = float(len(audio)) / 16000.0  # 16kHz
        continue_threshold = max(
            VAD_CONTINUE_THRESHOLD_RMS,
            session.noise_floor_rms * VAD_NOISE_CONTINUE_RATIO,
        )
        if session.voice_active and rms < continue_threshold:
            session.vad_silence_seconds += frame_duration_s
        else:
            session.vad_silence_seconds = 0.0
        return session.has_speech and session.vad_silence_seconds >= VAD_SILENCE_DURATION_S

    def _gate_frame(
        self, session: SpeechStreamSession, pcm_bytes: bytes, audio: np.ndarray,
    ) -> tuple[list[bytes], bool]:
        """Return frames admitted to ASR and whether voice began this frame."""
        rms = self._compute_rms(audio)
        frame_duration = float(len(audio)) / 16000.0
        session._pre_roll.append(pcm_bytes)

        if session.calibration_frames_remaining > 0 and not session.voice_active:
            # A conservative EWMA learns the room floor without normalising it.
            session.noise_floor_rms = (
                0.8 * session.noise_floor_rms + 0.2 * min(rms, VAD_SILENCE_THRESHOLD_RMS)
            )
            session.calibration_frames_remaining -= 1
            # Complete the full 500 ms room calibration before voice onset.
            # The rolling pre-buffer still retains the final 300 ms so an
            # attendee who begins slightly early does not lose consonants.
            return [], False

        onset_threshold = max(
            VAD_SILENCE_THRESHOLD_RMS,
            session.noise_floor_rms * VAD_NOISE_START_RATIO,
        )
        continue_threshold = max(
            VAD_CONTINUE_THRESHOLD_RMS,
            session.noise_floor_rms * VAD_NOISE_CONTINUE_RATIO,
        )

        if not session.voice_active:
            if rms >= onset_threshold:
                session.voice_start_frames += 1
            else:
                session.voice_start_frames = 0
                # Do not let unconfirmed speech rapidly raise the learned
                # floor and chase the onset threshold upward.  A quieter frame
                # can lower the estimate promptly; louder frames influence it
                # only very slowly.
                alpha = 0.05 if rms <= session.noise_floor_rms else 0.005
                session.noise_floor_rms = (
                    (1.0 - alpha) * session.noise_floor_rms + alpha * rms
                )
            if session.voice_start_frames < VAD_START_CONFIRM_FRAMES:
                return [], False

            session.voice_active = True
            session.has_speech = True
            session.vad_silence_seconds = 0.0
            session.chinese_streaming_flushed = False
            session.voice_start_frames = 0
            admitted = list(session._pre_roll)
            session._pre_roll.clear()
            return admitted, True

        if rms >= continue_threshold:
            session.vad_silence_seconds = 0.0
            # The prior pause was a hesitation rather than an utterance end.
            # Paraformer has already closed its old cache; the next speech
            # frame starts its new cache while retaining cumulative text.
            session.chinese_streaming_flushed = False
        else:
            session.vad_silence_seconds += frame_duration
        return [pcm_bytes], False

    @staticmethod
    def _meaningful_length(text: str) -> int:
        return len("".join(ch for ch in text.strip() if ch.isalnum()))

    def _boundary_reason(
        self,
        session: SpeechStreamSession,
        text: str,
        *,
        natural_boundary_committed: bool = False,
        committed_boundary: str = "",
        english_boundary_confirmed: bool = False,
    ) -> str | None:
        if not session.has_speech:
            return None
        if session.utterance_audio_seconds >= VAD_MAX_UTTERANCE_S:
            return "max_duration"

        silence = session.vad_silence_seconds
        stripped = text.rstrip()
        meaningful = self._meaningful_length(stripped)
        if stripped and meaningful >= 2:
            if session.detected_language == "en" and (
                english_boundary_confirmed
                and silence + 1e-6 >= VAD_SENTENCE_PAUSE_S
            ):
                # A short English pause closes only the semantic lyric sentence.
                # The utterance and Zipformer stream remain alive so the next
                # sentence keeps its acoustic context and onset words.
                return "english_sentence_pause"
            if (
                session.detected_language != "en"
                and stripped[-1] in "。！？.!?"
                and silence + 1e-6 >= VAD_CHINESE_FINALIZE_PAUSE_S
            ):
                return "sentence_pause"
            if (
                session.utterance_audio_seconds >= VAD_SOFT_UTTERANCE_S
                and natural_boundary_committed
            ):
                if committed_boundary in "。！？.!?":
                    return "soft_sentence_limit"
            if meaningful >= 4 and silence >= VAD_NATURAL_PAUSE_S:
                return "natural_pause"
        if silence >= VAD_SILENCE_DURATION_S:
            return "hard_silence"
        return None

    @staticmethod
    def _publish_speaking(session: SpeechStreamSession) -> None:
        if session.speaking_event_active:
            return
        session.speaking_event_active = True
        event_bus.publish(SpeakerSpeakingEvent(
            meeting_id=session.meeting_id,
            payload={"seat_id": session.seat_id},
        ))

    @staticmethod
    def _publish_speaking_stop(session: SpeechStreamSession) -> None:
        if not session.speaking_event_active:
            return
        session.speaking_event_active = False
        event_bus.publish(SpeakerSpeakingStopEvent(
            meeting_id=session.meeting_id,
            payload={"seat_id": session.seat_id},
        ))

    @staticmethod
    def _semantic_raw_count(text: str) -> int:
        return sum(1 for ch in text if ch not in ALL_BOUNDARY)

    @staticmethod
    def _semantic_offset_for_raw(text: str, raw_len: int) -> int:
        if raw_len <= 0:
            return 0
        count = 0
        for index, ch in enumerate(text):
            if ch not in ALL_BOUNDARY:
                count += 1
                if count == raw_len:
                    cursor = index + 1
                    while cursor < len(text) and text[cursor] in ALL_BOUNDARY:
                        cursor += 1
                    return cursor
        return len(text)

    def _ensure_sentence_identity(
        self,
        session: SpeechStreamSession,
    ) -> tuple[str, int]:
        if session.active_sentence_id is None:
            key = (session.meeting_id, session.seat_id)
            session.sentence_sequence = max(
                session.sentence_sequence,
                self._sentence_sequences.get(key, 0),
            ) + 1
            self._sentence_sequences[key] = session.sentence_sequence
            session.active_sentence_sequence = session.sentence_sequence
            utterance_id = session.current_utterance_id or "unknown"
            session.active_sentence_id = (
                f"{utterance_id}:s{session.sentence_sequence:06d}"
            )
        return session.active_sentence_id, session.active_sentence_sequence

    def _track_semantic_sentences(
        self,
        session: SpeechStreamSession,
        source_text: str,
        boundary_reason: str | None,
    ) -> dict[str, Any]:
        """Return completed sentences plus the currently forming sentence.

        Terminal punctuation inside cumulative ASR text is confirmed when
        later content follows it.  Punctuation at the tail is only committed
        by a semantic VAD/end boundary, preventing provisional punctuation
        from producing flickering translations.
        """
        text = source_text.strip()
        completed: list[dict[str, Any]] = []

        while text:
            offset = self._semantic_offset_for_raw(
                text,
                session.sentence_committed_raw_len,
            )
            suffix = text[offset:].lstrip()
            if not suffix:
                break
            split_at = 0
            for index, ch in enumerate(suffix):
                if ch in SEMANTIC_SENTENCE_END and suffix[index + 1:].strip():
                    split_at = index + 1
                    break
            if split_at == 0:
                break
            sentence = suffix[:split_at].strip()
            sentence_id, sequence = self._ensure_sentence_identity(session)
            completed.append({
                "sentence_id": sentence_id,
                "sentence_sequence": sequence,
                "source_text": sentence,
            })
            session.sentence_committed_raw_len += self._semantic_raw_count(sentence)
            session.active_sentence_id = None
            session.active_sentence_sequence = 0

        offset = self._semantic_offset_for_raw(
            text,
            session.sentence_committed_raw_len,
        ) if text else 0
        remaining = text[offset:].strip() if text else ""

        if remaining and boundary_reason in SENTENCE_COMMIT_REASONS:
            sentence_id, sequence = self._ensure_sentence_identity(session)
            completed.append({
                "sentence_id": sentence_id,
                "sentence_sequence": sequence,
                "source_text": remaining,
            })
            session.sentence_committed_raw_len += self._semantic_raw_count(remaining)
            session.active_sentence_id = None
            session.active_sentence_sequence = 0
            remaining = ""

        if remaining:
            sentence_id, sequence = self._ensure_sentence_identity(session)
            return {
                "sentence_id": sentence_id,
                "sentence_sequence": sequence,
                "sentence_source_text": remaining,
                "sentence_state": "forming",
                "completed_sentences": completed,
            }
        if completed:
            latest = completed[-1]
            return {
                "sentence_id": latest["sentence_id"],
                "sentence_sequence": latest["sentence_sequence"],
                "sentence_source_text": latest["source_text"],
                "sentence_state": "completed",
                "completed_sentences": completed,
            }
        return {
            "sentence_id": None,
            "sentence_sequence": 0,
            "sentence_source_text": "",
            "sentence_state": "forming",
            "completed_sentences": [],
        }

    def _track_english_sentences(
        self,
        session: SpeechStreamSession,
        source_text: str,
        boundary_reason: str | None,
    ) -> dict[str, Any]:
        """Commit confirmed English prefixes and expose one forming suffix.

        The online punctuator can confirm an earlier sentence once following
        words arrive. Such prefixes become locked lyric rows immediately and
        enter translation without waiting for the whole utterance. Long text
        may also settle at clause punctuation after 40 words or at a hard
        50-word boundary. The cumulative Zipformer decoder remains alive so
        the next sentence keeps its acoustic context.
        """
        text = normalize_english_display(source_text).strip()
        if not text:
            return {
                "sentence_id": None,
                "sentence_sequence": 0,
                "sentence_source_text": "",
                "sentence_state": "forming",
                "completed_sentences": [],
            }

        completed: list[dict[str, Any]] = []
        cursor = min(session.english_committed_text_len, len(text))

        while cursor < len(text):
            untrimmed = text[cursor:]
            suffix = untrimmed.lstrip()
            if not suffix:
                cursor = len(text)
                break
            start = cursor + (len(untrimmed) - len(suffix))
            split_at = self._english_confirmed_split_offset(suffix)
            if split_at == 0:
                cursor = start
                break

            sentence = suffix[:split_at].strip()
            sentence_id, sequence = self._ensure_sentence_identity(session)
            completed.append({
                "sentence_id": sentence_id,
                "sentence_sequence": sequence,
                "source_text": sentence,
                "requires_english_correction": False,
                "recognition_status": "ok",
                "source_locked": True,
            })
            cursor = start + split_at
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            session.english_committed_text_len = cursor
            session.active_sentence_id = None
            session.active_sentence_sequence = 0

        remaining = text[cursor:].strip() if cursor < len(text) else ""
        had_internal_commits = session.english_committed_text_len > 0

        if remaining and boundary_reason in SENTENCE_COMMIT_REASONS:
            sentence_id, sequence = self._ensure_sentence_identity(session)
            start = min(
                max(0, session.english_sentence_start_frame),
                len(session._utterance_buffer),
            )
            raw_audio = b"".join(session._utterance_buffer[start:])
            session.english_sentence_start_frame = len(session._utterance_buffer)
            can_correct = bool(raw_audio) and not had_internal_commits
            committed = {
                "sentence_id": sentence_id,
                "sentence_sequence": sequence,
                "source_text": remaining,
                "requires_english_correction": can_correct,
                "audio": self.pcm16_to_float32(raw_audio).copy()
                if can_correct else None,
                "recognition_status": "correcting" if can_correct else "ok",
                "source_locked": not can_correct,
            }
            completed.append(committed)
            session.english_committed_text_len = len(text)
            session.active_sentence_id = None
            session.active_sentence_sequence = 0
            remaining = ""

        if remaining:
            sentence_id, sequence = self._ensure_sentence_identity(session)
            return {
                "sentence_id": sentence_id,
                "sentence_sequence": sequence,
                "sentence_source_text": remaining,
                "sentence_state": "forming",
                "completed_sentences": completed,
            }
        if completed:
            latest = completed[-1]
            return {
                "sentence_id": latest["sentence_id"],
                "sentence_sequence": latest["sentence_sequence"],
                "sentence_source_text": latest["source_text"],
                "sentence_state": "completed",
                "completed_sentences": completed,
            }
        return {
            "sentence_id": None,
            "sentence_sequence": 0,
            "sentence_source_text": "",
            "sentence_state": "forming",
            "completed_sentences": [],
        }

    @staticmethod
    def _english_confirmed_split_offset(text: str) -> int:
        """Return an end offset for a stable English semantic prefix."""
        word_count = 0
        for match in re.finditer(r"\S+", text):
            token = match.group(0)
            if any(ch.isalnum() for ch in token):
                word_count += 1
            visible = token.rstrip("]})\"'”’")
            boundary = visible[-1] if visible else ""
            has_following = bool(text[match.end():].strip())

            # Following content confirms sentence-final punctuation at any
            # length. This is the normal lyrics-style paragraph boundary.
            if boundary in SEMANTIC_SENTENCE_END and has_following:
                return match.end()
            if (
                word_count > ENGLISH_CLAUSE_COMMIT_WORDS
                and boundary in ENGLISH_CLAUSE_END
                and has_following
            ):
                return match.end()
            if word_count >= ENGLISH_FORCE_COMMIT_WORDS:
                return match.end()
        return 0

    def complete_active_sentence(
        self,
        session_key: str,
        source_text: str,
        boundary_reason: str = "end_hint",
    ) -> dict[str, Any]:
        """Commit the remaining semantic sentence for a manual boundary."""
        session = self._sessions.get(session_key)
        if session is None:
            return {"completed_sentences": []}
        if session.detected_language == "en":
            return self._track_english_sentences(
                session,
                source_text,
                boundary_reason,
            )
        return self._track_semantic_sentences(
            session,
            source_text,
            boundary_reason,
        )

    def update_pcm_queue(self, session_key: str, pending_frames: int) -> None:
        """Publish the ingress queue depth to diagnostics and priority gates."""
        session = self._sessions.get(session_key)
        if session is None:
            return
        session.pcm_queue_frames = max(0, int(pending_frames))
        session.audio_backlog_ms = session.pcm_queue_frames * 100
        session.peak_audio_backlog_ms = max(
            session.peak_audio_backlog_ms,
            session.audio_backlog_ms,
        )
        inference_runtime.update_stream(
            session_key,
            voice_active=session.voice_active,
            backlog_ms=session.audio_backlog_ms,
        )

    @staticmethod
    def _route_fields(session: SpeechStreamSession) -> dict[str, str]:
        return {
            "requested_language": session.requested_language,
            "detected_language": session.detected_language,
            "recognition_engine": session.recognition_engine,
            "source_lang": session.detected_language,
        }

    def _recognize_sensevoice_snapshot(
        self,
        session: SpeechStreamSession,
        *,
        language: str,
        force: bool = False,
        purpose: str = "rolling",
    ) -> tuple[str, str, int]:
        """Recognize the latest bounded utterance window with SenseVoice."""
        if not session._utterance_buffer:
            return session.last_sensevoice_text, session.detected_language, 0
        elapsed = (
            session.utterance_audio_seconds
            - session.last_sensevoice_inference_audio_seconds
        )
        if not force and elapsed + 1e-6 < SENSEVOICE_LIVE_INTERVAL_SECONDS:
            return session.last_sensevoice_text, session.detected_language, 0

        from backend.speech_module.bilingual_asr import recognize_bilingual

        buffer_len = len(session._utterance_buffer)
        window_start = max(0, buffer_len - SENSEVOICE_LIVE_WINDOW_FRAMES)
        pcm = b"".join(session._utterance_buffer[window_start:])
        audio = self.pcm16_to_float32(pcm)
        trace(
            f"sensevoice_{purpose}_start_at",
            utterance_id=session.current_utterance_id,
            meeting_id=session.meeting_id,
            seat_id=session.seat_id,
            window_start_frame=window_start,
            window_frames=buffer_len - window_start,
        )
        started = time.perf_counter()
        session.sensevoice_task_running = True
        try:
            result = recognize_bilingual(
                audio,
                language=language,
            )  # serialized by model lock
            session.sensevoice_last_error = None
        except Exception as exc:
            session.sensevoice_last_error = str(exc)
            if session.last_sensevoice_text:
                trace(
                    f"sensevoice_{purpose}_degraded_at",
                    utterance_id=session.current_utterance_id,
                    meeting_id=session.meeting_id,
                    seat_id=session.seat_id,
                    error=str(exc),
                )
                return (
                    session.last_sensevoice_text,
                    session.detected_language
                    if session.detected_language in {"zh", "en"}
                    else language,
                    round((time.perf_counter() - started) * 1000),
                )
            raise
        finally:
            session.sensevoice_task_running = False
        infer_ms = round((time.perf_counter() - started) * 1000)
        text = result.text.strip()
        detected = result.source_lang
        if detected == "en":
            text = normalize_english_display(text)

        if (
            purpose == "rolling"
            and window_start > 0
            and session.last_sensevoice_text
            and window_start > session.sensevoice_window_start_frame
        ):
            text = merge_english_transcripts(session.last_sensevoice_text, text)

        session.last_sensevoice_inference_audio_seconds = (
            session.utterance_audio_seconds
        )
        session.last_sensevoice_text = text
        session.sensevoice_window_start_frame = window_start
        trace(
            f"sensevoice_{purpose}_end_at",
            utterance_id=session.current_utterance_id,
            meeting_id=session.meeting_id,
            seat_id=session.seat_id,
            infer_ms=infer_ms,
            detected_language=detected,
            text_length=len(text),
        )
        return text, detected, infer_ms

    # ── PCM16 conversion ────────────────────────────────────────────────────

    @staticmethod
    def pcm16_to_float32(data: bytes) -> np.ndarray:
        """Convert PCM16 little-endian bytes to float32 numpy array.

        Args:
            data: Raw PCM16 s16le bytes (16kHz mono).

        Returns:
            np.ndarray of dtype float32, range [-1.0, 1.0].
        """
        raw = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        raw /= 32768.0
        return raw

    # ── Utterance lifecycle (Phase 3) ─────────────────────────────────────────

    def start_utterance(
        self,
        session_key: str,
        utterance_id: str,
        *,
        continuous_rollover: bool = False,
        language_mode: str | None = None,
    ) -> None:
        """Begin a new utterance — reset revision, set utterance_id.

        Also resets SpeechModule's sentence merger for this session.
        Call this when the client sends 'start'.
        """
        session = self._sessions.get(session_key)
        if session is None:
            logger.warning(
                "start_utterance called for unknown session %s", session_key,
            )
            return
        previous_noise_floor = session.noise_floor_rms
        previous_speaking_event = session.speaking_event_active
        if language_mode is not None:
            if language_mode not in LIVE_ASR_LANGUAGE_MODES:
                raise ValueError(f"Unsupported language_mode: {language_mode}")
            session.requested_language = language_mode
        # A repeated manual start must not leave the previous temporary light
        # active. Duration rollovers are one continuous speech action.
        if not continuous_rollover:
            self._publish_speaking_stop(session)
        session.current_utterance_id = utterance_id
        session.revision = 0
        session._utterance_buffer.clear()
        session.caption_formatter.reset()
        # Task 122: reset VAD state
        session.utterance_state = UTTERANCE_STATE_SPEAKING
        session.vad_silence_seconds = 0.0
        session.noise_floor_rms = (
            previous_noise_floor if continuous_rollover else 0.003
        )
        session.calibration_frames_remaining = (
            0 if continuous_rollover else VAD_CALIBRATION_FRAMES
        )
        session.voice_start_frames = 0
        session.voice_active = continuous_rollover
        session.has_speech = continuous_rollover
        session.utterance_audio_seconds = 0.0
        session.last_streaming_text = ""
        session.last_source_text = ""
        session.speech_debug_decoder_calls.clear()
        session.speech_debug_revisions.clear()
        session.last_caption = {
            "previous_line": "",
            "current_line": "",
            "mode": "two_line",
        }
        session.active_sentence_id = None
        session.active_sentence_sequence = 0
        session.sentence_committed_raw_len = 0
        session.english_sentence_start_frame = 0
        session.english_committed_text_len = 0
        session.detected_language = (
            session.requested_language
            if session.requested_language in {"zh", "en"}
            else "unknown"
        )
        session.recognition_engine = (
            "paraformer_streaming" if session.requested_language == "zh"
            else "sherpa_onnx_streaming" if session.requested_language == "en"
            else "unknown"
        )
        session.last_sensevoice_inference_audio_seconds = 0.0
        session.last_sensevoice_text = ""
        session.sensevoice_window_start_frame = 0
        session.paraformer_replayed_frames = 0
        session.sensevoice_task_running = False
        session.sensevoice_last_error = None
        session.english_streaming_frames = 0
        session.english_streaming_last_error = None
        session.english_streaming_flushed = False
        session.chinese_streaming_flushed = False
        session.english_punctuation_last_error = None
        session.english_punctuation_source_text = ""
        session.english_punctuation_text = ""
        session.english_punctuation_inference_ms = 0.0
        session._pre_roll.clear()
        if continuous_rollover:
            session.speaking_event_active = previous_speaking_event
            session._rollover_started_at = time.monotonic()
        else:
            session._rollover_overlap_pcm = b""
            session._rollover_started_at = None

        # Reset SpeechModule per-utterance state
        if self._speech_module is not None and self._speech_module.ready:
            self._speech_module.set_session_context(
                session_key, session.meeting_id, session.seat_id,
            )
            self._speech_module.start_utterance(session_key)

    def cancel_utterance(self, session_key: str) -> str | None:
        """Cancel current utterance. Returns the cancelled utterance_id or None.

        Resets revision to 0 and clears current_utterance_id.
        Also resets SpeechModule's sentence merger for this session.

        Task 126: marks the utterance_id as terminal on cancel, preventing
        duplicate final/cancel events for the same utterance.
        """
        session = self._sessions.get(session_key)
        if session is None:
            return None
        uid = session.current_utterance_id
        if uid:
            # Task 126: track as terminal before clearing
            session.terminal_utterance_ids.add(uid)
        session.current_utterance_id = None
        session.revision = 0
        session._utterance_buffer.clear()
        session.caption_formatter.reset()
        session.active_sentence_id = None
        session.active_sentence_sequence = 0
        session.sentence_committed_raw_len = 0
        session.english_sentence_start_frame = 0
        session.english_committed_text_len = 0
        session.english_punctuation_last_error = None
        session.english_punctuation_source_text = ""
        session.english_punctuation_text = ""
        session.english_punctuation_inference_ms = 0.0
        # Task 122: reset VAD state
        session.utterance_state = UTTERANCE_STATE_IDLE
        session.vad_silence_seconds = 0.0
        session.voice_active = False
        session.has_speech = False
        session.chinese_streaming_flushed = False
        session.last_streaming_text = ""
        session.speech_debug_decoder_calls.clear()
        session.speech_debug_revisions.clear()
        session._pre_roll.clear()
        session._rollover_overlap_pcm = b""
        session._rollover_started_at = None
        session.pcm_queue_frames = 0
        session.audio_backlog_ms = 0
        inference_runtime.update_stream(
            session_key,
            voice_active=False,
            backlog_ms=0,
        )
        self._publish_speaking_stop(session)
        if self._speech_module is not None and self._speech_module.ready:
            if hasattr(self._speech_module, "reset_streaming_state"):
                self._speech_module.reset_streaming_state(session_key)
            else:
                self._speech_module.reset_interim(session_key)
        return uid

    def reset_caption_formatter(self, session_key: str) -> None:
        """Reset the caption formatter for a session (e.g. after finalization)."""
        session = self._sessions.get(session_key)
        if session is not None:
            session.caption_formatter.reset()

    def _flush_chinese_stream(
        self,
        session_key: str,
        session: SpeechStreamSession,
        speech_module: Any,
    ) -> str:
        """Release Paraformer's pending final token(s) once per pause."""
        if (
            session.detected_language != "zh"
            or session.recognition_engine != "paraformer_streaming"
            or session.chinese_streaming_flushed
        ):
            return ""
        try:
            if hasattr(speech_module, "finish_chinese_interim"):
                flushed = speech_module.finish_chinese_interim(session_key)
            else:
                # Compatibility for lightweight adapters used in diagnostics.
                flushed = speech_module.process_interim_array(
                    np.zeros(1600, dtype=np.float32),
                    session_key,
                    is_final=True,
                )
            self._record_chinese_decoder_call(
                session, speech_module, session_key, stage="final_flush",
            )
            session.chinese_streaming_flushed = True
            trace(
                "chinese_streaming_flush_at",
                utterance_id=session.current_utterance_id,
                meeting_id=session.meeting_id,
                seat_id=session.seat_id,
                silence_ms=round(session.vad_silence_seconds * 1000),
                text_len=len(flushed or ""),
            )
            return str(flushed or "")
        except Exception as exc:
            # Preserve the existing live hypothesis if a degraded adapter does
            # not support explicit finalization.
            logger.warning("Chinese streaming flush failed; retaining interim text: %s", exc)
            return ""

    @staticmethod
    def _record_chinese_decoder_call(
        session: SpeechStreamSession,
        speech_module: Any,
        session_key: str,
        *,
        stage: str,
    ) -> None:
        getter = getattr(speech_module, "get_interim_debug", None)
        if not callable(getter):
            return
        try:
            record_speech_debug_decoder_call(
                session,
                stage=stage,
                decoder=getter(session_key),
            )
        except Exception as exc:
            logger.warning("Speech decoder debug capture failed: %s", exc)

    def snapshot_auto_finalization(
        self,
        session_key: str,
        source_text: str,
        boundary_reason: str,
    ) -> dict[str, Any] | None:
        """Terminate a segment and copy its PCM for background final ASR."""
        session = self._sessions.get(session_key)
        if session is None or not session.current_utterance_id:
            return None
        utterance_id = session.current_utterance_id
        if utterance_id in session.terminal_utterance_ids:
            return None

        # A VAD-triggered finalization bypasses finalize_utterance(), so flush
        # the online English decoder here as well. This prevents its final
        # partial words from being lost on a hard silence or duration rollover.
        if (
            session.detected_language == "en"
            and session.recognition_engine == "sherpa_onnx_streaming"
            and self._speech_module is not None
        ):
            try:
                flushed = self._speech_module.finish_english_interim(session_key)
                session.english_streaming_flushed = True
                if flushed:
                    caption = session.caption_formatter.update(
                        flushed, time.monotonic(), source_lang="en",
                    )
                    session.last_source_text = caption.punctuated_text
                    session.last_caption = {
                        "previous_line": caption.previous_line,
                        "current_line": caption.current_line,
                        "mode": caption.mode,
                    }
                    session.revision += 1
            except Exception as exc:
                session.english_streaming_last_error = str(exc)
                logger.warning("English streaming VAD flush failed: %s", exc)

        text = (session.last_source_text or source_text).strip()
        continuous_rollover = boundary_reason in CONTINUOUS_ROLLOVER_REASONS
        overlap_pcm = b""
        if continuous_rollover and session._utterance_buffer:
            overlap_pcm = b"".join(session._utterance_buffer)[-ROLLOVER_OVERLAP_BYTES:]
        pcm_bytes = b"".join(session._utterance_buffer)
        audio = self.pcm16_to_float32(pcm_bytes).copy()
        snapshot = {
            "utterance_id": utterance_id,
            "meeting_id": session.meeting_id,
            "seat_id": session.seat_id,
            "source_text": text,
            "boundary_reason": boundary_reason,
            "audio_seconds": session.utterance_audio_seconds,
            "audio": audio,
            "sr": 16000,
            "has_speech": session.has_speech,
            "caption": dict(session.last_caption),
            "continuous_rollover": continuous_rollover,
            "rollover_overlap_ms": round(len(overlap_pcm) / 32.0),
            "rollover_overlap_frames": (len(overlap_pcm) + 3199) // 3200,
            "requested_language": session.requested_language,
            "detected_language": session.detected_language,
            "recognition_engine": session.recognition_engine,
            "recognized_text": (
                session.last_sensevoice_text
                if session.recognition_engine == "sensevoice_rolling_fallback"
                else ""
            ),
            "recognition_status": (
                "degraded" if session.sensevoice_last_error else "ok"
            ),
        }

        try:
            save_speech_debug_capture(
                session,
                pcm_bytes=pcm_bytes,
                boundary_reason=boundary_reason,
            )
        except Exception as exc:
            logger.warning("Speech debug capture failed: %s", exc)

        session.terminal_utterance_ids.add(utterance_id)
        session._utterance_buffer.clear()
        session.caption_formatter.reset()
        session._rollover_overlap_pcm = overlap_pcm
        session.voice_active = continuous_rollover
        session.utterance_state = UTTERANCE_STATE_FINALIZING
        inference_runtime.update_stream(
            session_key,
            voice_active=continuous_rollover,
            backlog_ms=session.audio_backlog_ms,
        )
        if not continuous_rollover:
            self._publish_speaking_stop(session)
        return snapshot

    def prepare_next_utterance(
        self,
        session_key: str,
        meeting_id: int,
        seat_id: int,
        *,
        continuous_rollover: bool = False,
    ) -> str | None:
        """Prepare the next utterance after auto-finalization.

        Generates a new utterance_id and starts a new utterance with
        reset state (revision, buffer, VAD, caption formatter).

        The speech WS remains open — no reconnect needed.

        Args:
            session_key: Active speech session key.
            meeting_id: Active meeting ID.
            seat_id: Speaker seat ID.

        Returns:
            The new utterance_id, or None if session is unknown.
        """
        session = self._sessions.get(session_key)
        if session is None:
            return None

        new_uid = self.generate_utterance_id(meeting_id, seat_id)
        self.start_utterance(
            session_key,
            new_uid,
            continuous_rollover=continuous_rollover,
            language_mode=session.requested_language,
        )
        # The room floor was already calibrated for this open WebSocket.
        # Skipping a second 500 ms calibration avoids losing speech at an
        # automatic rollover; the three-frame onset pre-roll is still kept.
        session.calibration_frames_remaining = 0
        logger.debug(
            "Prepared next utterance: %s (session=%s)",
            new_uid, session_key,
        )
        return new_uid

    # ── Task 126: terminal utterance_id tracking ──────────────────────────────

    def mark_utterance_terminal(
        self, session_key: str, utterance_id: str,
    ) -> None:
        """Mark an utterance_id as terminal (finalized / cancelled / failed).

        Idempotent — subsequent calls for the same utterance_id are no-ops.
        Guards against duplicate final/cancel for the same utterance.
        """
        session = self._sessions.get(session_key)
        if session and utterance_id:
            session.terminal_utterance_ids.add(utterance_id)

    def is_utterance_terminal(
        self, session_key: str, utterance_id: str,
    ) -> bool:
        """Check if an utterance_id has already been finalized/cancelled."""
        session = self._sessions.get(session_key)
        if session:
            return utterance_id in session.terminal_utterance_ids
        return False

    def process_pcm_frame(
        self, session_key: str, pcm_bytes: bytes,
    ) -> dict[str, Any]:
        """Process a PCM16 binary frame through streaming ASR.

        Args:
            session_key: Active speech session key.
            pcm_bytes: Raw PCM16 s16le bytes.

        Returns:
            dict with keys: utterance_id (str|None), revision (int), source_text (str).

        Raises:
            RuntimeError: If SpeechModule is not available (models not loaded).
            RuntimeError: If session_key is unknown.
        """
        # 1. Resolve session
        session = self._sessions.get(session_key)
        if session is None:
            raise RuntimeError(f"Session {session_key} not found")

        # 2. Convert PCM16 and pass it through the adaptive voice gate.  Until
        # actual speech is confirmed, neither ASR nor persistence sees audio.
        audio = self.pcm16_to_float32(pcm_bytes)
        input_rms = self._compute_rms(audio)
        session.pcm_frames_received += 1
        session.pcm_bytes_received += len(pcm_bytes)
        session.last_input_rms = input_rms
        session.peak_input_rms = max(session.peak_input_rms, input_rms)
        session.last_pcm_at = time.monotonic()
        admitted_frames, voice_started = self._gate_frame(session, pcm_bytes, audio)
        if voice_started:
            self._publish_speaking(session)

        if not admitted_frames:
            return {
                "utterance_id": session.current_utterance_id,
                "revision": session.revision,
                "source_text": "",
                "caption": {
                    "previous_line": "",
                    "current_line": "",
                    "mode": "listening",
                },
                "vad_should_finalize": False,
                "boundary_reason": None,
                **self._route_fields(session),
            }

        # 3. Buffer admitted speech first. Recognition is routed per utterance:
        # Paraformer for Chinese and true online Zipformer for English.
        sm = self._get_speech_module()
        sm.set_session_context(
            session_key, session.meeting_id, session.seat_id,
        )
        trace("asr_streaming_start_at",
              utterance_id=session.current_utterance_id,
              meeting_id=session.meeting_id,
              seat_id=session.seat_id,
              requested_language=session.requested_language,
              recognition_engine=session.recognition_engine)
        _asr_t0 = time.perf_counter()
        raw_text = session.last_source_text
        for admitted in admitted_frames:
            self.append_audio(session_key, admitted)
            admitted_audio = self.pcm16_to_float32(admitted)
            session.utterance_audio_seconds += len(admitted_audio) / 16000.0
        inference_runtime.update_stream(
            session_key,
            voice_active=session.voice_active,
            backlog_ms=session.audio_backlog_ms,
        )

        def process_paraformer(frames: list[bytes]) -> str:
            text = session.last_source_text
            overlap_pcm = session._rollover_overlap_pcm
            if overlap_pcm:
                try:
                    sm.process_interim_array(
                        self.pcm16_to_float32(overlap_pcm), session_key,
                    )
                    self._record_chinese_decoder_call(
                        session, sm, session_key, stage="rollover_replay",
                    )
                    sm.reset_interim(session_key)
                except Exception as exc:
                    logger.warning(
                        "Speech rollover overlap replay failed: session=%s error=%s",
                        session_key,
                        exc,
                    )
                finally:
                    session._rollover_overlap_pcm = b""
            for frame in frames:
                text = sm.process_interim_array(
                    self.pcm16_to_float32(frame), session_key,
                )
                self._record_chinese_decoder_call(
                    session, sm, session_key, stage="streaming",
                )
            return text

        def process_english_stream(frames: list[bytes]) -> str:
            """Process each admitted PCM frame exactly once with Zipformer.

            When the local English model is missing or fails, preserve the old
            bounded SenseVoice path as a visible degraded fallback instead of
            making the speaker stream unusable.
            """
            # A fresh decoder is created after every committed English
            # sentence. Never seed it from a previous sentence's display
            # text, otherwise an empty/silent first result can resurrect the
            # completed sentence in the new lyric row.
            text = ""
            if session.recognition_engine != "sensevoice_rolling_fallback":
                try:
                    for frame in frames:
                        text = sm.process_english_interim_array(
                            self.pcm16_to_float32(frame), session_key,
                        )
                        session.english_streaming_frames += 1
                    session.recognition_engine = "sherpa_onnx_streaming"
                    session.english_streaming_last_error = None
                    return normalize_english_display(text)
                except Exception as exc:
                    session.english_streaming_last_error = str(exc)
                    session.sensevoice_last_error = str(exc)
                    session.recognition_engine = "sensevoice_rolling_fallback"
                    logger.warning(
                        "English streaming model unavailable; using SenseVoice fallback: %s",
                        exc,
                    )
                    trace(
                        "english_streaming_fallback_at",
                        utterance_id=session.current_utterance_id,
                        meeting_id=session.meeting_id,
                        seat_id=session.seat_id,
                        error=str(exc),
                    )
            if session.utterance_audio_seconds + 1e-6 >= SENSEVOICE_LIVE_INTERVAL_SECONDS:
                text, _, _ = self._recognize_sensevoice_snapshot(
                    session, language="en", purpose="rolling",
                )
            return normalize_english_display(text)

        requested = session.requested_language
        if requested == "zh":
            session.detected_language = "zh"
            session.recognition_engine = "paraformer_streaming"
            raw_text = process_paraformer(admitted_frames)
        elif requested == "en":
            session.detected_language = "en"
            raw_text = process_english_stream(admitted_frames)
        elif session.detected_language == "unknown":
            if session.utterance_audio_seconds >= SENSEVOICE_AUTO_PROBE_SECONDS:
                probe_text, detected, _ = self._recognize_sensevoice_snapshot(
                    session,
                    language="auto",
                    force=True,
                    purpose="probe",
                )
                session.detected_language = detected
                session.recognition_engine = (
                    "sherpa_onnx_streaming"
                    if detected == "en"
                    else "paraformer_streaming"
                )
                trace(
                    "live_asr_route_selected_at",
                    utterance_id=session.current_utterance_id,
                    meeting_id=session.meeting_id,
                    seat_id=session.seat_id,
                    requested_language="auto",
                    detected_language=detected,
                    recognition_engine=session.recognition_engine,
                    probe_audio_ms=round(session.utterance_audio_seconds * 1000),
                )
                if detected == "en":
                    # Replay all buffered audio into the fresh stream so the
                    # 1.2 s automatic language probe never loses sentence
                    # onset. The probe text is only a fallback if Zipformer is
                    # not locally available.
                    raw_text = process_english_stream(session._utterance_buffer)
                    raw_text = raw_text or probe_text
                else:
                    replay_frames = session._utterance_buffer[
                        session.paraformer_replayed_frames:
                    ]
                    paraformer_text = process_paraformer(replay_frames)
                    session.paraformer_replayed_frames = len(
                        session._utterance_buffer
                    )
                    raw_text = paraformer_text or probe_text
        elif session.detected_language == "zh":
            session.recognition_engine = "paraformer_streaming"
            if (
                session.chinese_streaming_flushed
                and session.vad_silence_seconds > 0.0
            ):
                # Do not start an empty decoder after a pause flush.  It would
                # replace the complete live hypothesis with an empty result.
                raw_text = session.last_streaming_text
            else:
                raw_text = process_paraformer(admitted_frames)
            session.paraformer_replayed_frames = len(session._utterance_buffer)
        else:
            raw_text = process_english_stream(admitted_frames)

        # Paraformer retains a small right-context/CIF cache.  A 0.9 s pause is
        # sufficient evidence to flush the tail into the *live* event, without
        # waiting for background final ASR or a database refresh.  A duration
        # rollover also needs the same flush even while speech continues.
        should_flush_chinese = (
            session.detected_language == "zh"
            and not session.chinese_streaming_flushed
            and (
                session.vad_silence_seconds + 1e-6 >= VAD_SENTENCE_PAUSE_S
                or session.utterance_audio_seconds >= VAD_MAX_UTTERANCE_S
            )
        )
        if should_flush_chinese:
            flushed = self._flush_chinese_stream(session_key, session, sm)
            if flushed:
                # Some Paraformer versions return a shorter final hypothesis
                # for an incomplete chunk.  A flush may extend live text, but
                # must never make an already rendered subtitle regress.
                raw_text = merge_texts(raw_text, flushed)

        if raw_text:
            session.last_streaming_text = raw_text
        if (
            session.detected_language == "en"
            and session.recognition_engine == "sensevoice_rolling_fallback"
            and session.vad_silence_seconds >= VAD_SENTENCE_PAUSE_S
            and session.utterance_audio_seconds
                > session.last_sensevoice_inference_audio_seconds + 0.05
        ):
            raw_text, _, _ = self._recognize_sensevoice_snapshot(
                session,
                language="en",
                force=True,
                purpose="rolling",
            )
        english_boundary_confirmed = False
        if session.detected_language == "en":
            # Zipformer supplies words while the lightweight text model restores
            # punctuation/casing. A 0.9 s pause is only a candidate boundary:
            # an incomplete tail such as "do we have any" stays in the same
            # decoder until more words arrive or the natural-silence fallback
            # fires. This prevents a VAD hesitation from fabricating a period.
            unpunctuated = normalize_english_display(raw_text)
            short_pause = bool(unpunctuated) and (
                session.vad_silence_seconds + 1e-6 >= VAD_SENTENCE_PAUSE_S
            )
            try:
                punctuated = add_english_punctuation(unpunctuated)
                english_boundary_confirmed = short_pause and (
                    has_trusted_terminal_boundary(unpunctuated, punctuated)
                )
                if not english_boundary_confirmed:
                    punctuated = strip_provisional_terminal(punctuated)
                raw_text = punctuated
                punct_status = get_english_punctuation_status()
                session.english_punctuation_source_text = unpunctuated
                session.english_punctuation_text = punctuated
                session.english_punctuation_inference_ms = float(
                    punct_status.get("last_inference_ms") or 0.0
                )
                session.english_punctuation_last_error = None
                trace(
                    "english_online_punctuation_at",
                    utterance_id=session.current_utterance_id,
                    meeting_id=session.meeting_id,
                    seat_id=session.seat_id,
                    inference_ms=session.english_punctuation_inference_ms,
                    boundary_confirmed=english_boundary_confirmed,
                    short_pause=short_pause,
                    source_text_len=len(unpunctuated),
                )
            except Exception as exc:
                session.english_punctuation_last_error = str(exc)
                # Missing punctuation is a readable degraded state. Do not
                # restore the old short-pause forced period; a 2 s natural
                # pause or explicit end still commits the sentence safely.
                raw_text = format_english_streaming_display(
                    unpunctuated, sentence_complete=False,
                )
                trace(
                    "english_online_punctuation_failed_at",
                    utterance_id=session.current_utterance_id,
                    meeting_id=session.meeting_id,
                    seat_id=session.seat_id,
                    error=str(exc),
                )
            if (
                english_boundary_confirmed
                and session.recognition_engine == "sherpa_onnx_streaming"
            ):
                # Finish this decoder before exposing the sentence, then let
                # the next PCM frame create an isolated decoder for the next
                # sentence.  The WebSocket utterance and VAD remain alive.
                try:
                    if hasattr(sm, "rotate_english_interim"):
                        flushed = sm.rotate_english_interim(session_key)
                    elif hasattr(sm, "finish_english_interim"):
                        flushed = sm.finish_english_interim(session_key)
                        if hasattr(sm, "reset_streaming_state"):
                            sm.reset_streaming_state(session_key)
                    else:
                        # Lightweight test doubles and degraded adapters may
                        # expose only the streaming input method. The sentence
                        # still freezes; production SpeechModule always has a
                        # dedicated rotation method.
                        flushed = unpunctuated
                    if flushed:
                        flushed_punctuated = add_english_punctuation(flushed)
                        raw_text = (
                            flushed_punctuated
                            if has_trusted_terminal_boundary(
                                flushed, flushed_punctuated,
                            )
                            else raw_text
                        )
                    session.english_streaming_flushed = True
                except Exception as exc:
                    session.english_streaming_last_error = str(exc)
                    logger.warning("English sentence decoder rotation failed: %s", exc)
        _asr_ms = round((time.perf_counter() - _asr_t0) * 1000)

        # 4. Apply caption formatter and evaluate a content-aware boundary.
        _now = time.monotonic()
        caption_result = session.caption_formatter.update(
            raw_text,
            _now,
            source_lang=session.detected_language,
        )
        caption_result = (
            session.caption_formatter.check_timeout(_now) or caption_result
        )

        session.revision += 1
        source_text = caption_result.punctuated_text
        session.last_source_text = source_text
        session.last_caption = {
            "previous_line": caption_result.previous_line,
            "current_line": caption_result.current_line,
            "mode": caption_result.mode,
        }
        boundary_reason = self._boundary_reason(
            session,
            source_text,
            natural_boundary_committed=caption_result.natural_boundary_committed,
            committed_boundary=caption_result.committed_boundary,
            english_boundary_confirmed=english_boundary_confirmed,
        )
        record_speech_debug_revision(
            session,
            raw_text=raw_text,
            source_text=source_text,
            boundary_reason=boundary_reason,
        )
        # English sentence pauses feed translation_sentence but must not reset
        # the underlying online recognizer. Only a hard/manual/duration
        # boundary creates a new utterance and clears its decoder cache.
        vad_should_finalize = (
            boundary_reason is not None
            and boundary_reason != "english_sentence_pause"
        )
        sentence_state = (
            self._track_english_sentences(session, source_text, boundary_reason)
            if session.detected_language == "en"
            else self._track_semantic_sentences(
                session,
                source_text,
                boundary_reason,
            )
        )
        if (
            session.detected_language == "en"
            and english_boundary_confirmed
            and boundary_reason == "english_sentence_pause"
            and session.english_streaming_flushed
        ):
            # The current result was tracked against the completed cumulative
            # decoder. The next PCM frame starts a fresh decoder and therefore
            # a fresh text offset.
            session.english_committed_text_len = 0

        if raw_text and session._rollover_started_at is not None:
            logger.info(
                "Speech rollover first interim: utterance=%s latency_ms=%d",
                session.current_utterance_id,
                round((time.monotonic() - session._rollover_started_at) * 1000),
            )
            session._rollover_started_at = None

        if raw_text:
            trace("asr_streaming_end_at",
                  utterance_id=session.current_utterance_id,
                  meeting_id=session.meeting_id,
                  seat_id=session.seat_id,
                  revision=session.revision,
                  asr_infer_ms=_asr_ms,
                  vad_should_finalize=vad_should_finalize,
                  detected_language=session.detected_language,
                  recognition_engine=session.recognition_engine)

        return {
            "utterance_id": session.current_utterance_id,
            "revision": session.revision,
            "source_text": source_text,
            "caption": {
                "previous_line": caption_result.previous_line,
                "current_line": caption_result.current_line,
                "mode": caption_result.mode,
            },
            "vad_should_finalize": vad_should_finalize,
            "boundary_reason": boundary_reason,
            **self._route_fields(session),
            **sentence_state,
        }

    # ── Audio buffer (Phase 4) ───────────────────────────────────────────────

    def append_audio(self, session_key: str, pcm_bytes: bytes) -> None:
        """Append PCM16 audio data to the current utterance buffer.

        The buffer accumulates all PCM16 frames between start and end_hint.
        Buffer is cleared on start_utterance, cancel, and finalize.
        """
        session = self._sessions.get(session_key)
        if session is None:
            return
        session._utterance_buffer.append(pcm_bytes)

    def get_buffered_audio(self, session_key: str) -> np.ndarray | None:
        """Concatenate buffered PCM16 frames into a float32 numpy array.

        Returns None if the buffer is empty.
        """
        session = self._sessions.get(session_key)
        if session is None or not session._utterance_buffer or not session.has_speech:
            return None
        raw = b"".join(session._utterance_buffer)
        return self.pcm16_to_float32(raw)

    def clear_audio_buffer(self, session_key: str) -> None:
        """Clear the utterance audio buffer. Idempotent."""
        session = self._sessions.get(session_key)
        if session is not None:
            session._utterance_buffer.clear()

    def finalize_utterance(self, session_key: str) -> dict[str, Any] | None:
        """Finalize the current utterance: return audio and metadata for ASR.

        Returns dict with keys:
            audio (np.ndarray), sr (int), utterance_id (str|None),
            meeting_id (int), seat_id (int)
        Or None if no buffer or no session.

        Does NOT persist or publish — caller (WS handler) owns that step.
        After calling this, the utterance buffer is cleared.

        Task 126: returns None if the utterance_id is already terminal
        (prevents duplicate finalization from race conditions).
        """
        session = self._sessions.get(session_key)
        if session is None or not session._utterance_buffer:
            return None

        # Task 126: guard against re-finalizing a terminal utterance
        if (session.current_utterance_id
                and session.current_utterance_id in session.terminal_utterance_ids):
            logger.debug(
                "Skipping finalize for already-terminal utterance %s "
                "(session=%s)", session.current_utterance_id, session_key,
            )
            return None

        live_flush = False
        if (
            session.detected_language == "zh"
            and not session.chinese_streaming_flushed
        ):
            try:
                speech_module = self._get_speech_module()
                flushed = self._flush_chinese_stream(
                    session_key,
                    session,
                    speech_module,
                )
                if flushed:
                    flushed = merge_texts(session.last_streaming_text, flushed)
                    caption = session.caption_formatter.update(
                        flushed,
                        time.monotonic(),
                        source_lang="zh",
                    )
                    session.last_streaming_text = flushed
                    session.last_source_text = caption.punctuated_text
                    session.last_caption = {
                        "previous_line": caption.previous_line,
                        "current_line": caption.current_line,
                        "mode": caption.mode,
                    }
                    session.revision += 1
                    live_flush = True
            except Exception as exc:
                logger.warning("Chinese end-hint flush failed; retaining interim text: %s", exc)

        if (
            session.detected_language == "en"
            and session.recognition_engine == "sherpa_onnx_streaming"
        ):
            try:
                flushed = self._speech_module.finish_english_interim(session_key)
                session.english_streaming_flushed = True
                if flushed:
                    caption = session.caption_formatter.update(
                        flushed, time.monotonic(), source_lang="en",
                    )
                    session.last_source_text = caption.punctuated_text
                    session.last_caption = {
                        "previous_line": caption.previous_line,
                        "current_line": caption.current_line,
                        "mode": caption.mode,
                    }
                    session.revision += 1
            except Exception as exc:
                session.english_streaming_last_error = str(exc)
                logger.warning("English streaming flush failed; retaining interim text: %s", exc)

        if (
            session.detected_language == "en"
            and session._utterance_buffer
            and session.utterance_audio_seconds
                > session.last_sensevoice_inference_audio_seconds + 0.05
        ):
            try:
                corrected, _, _ = self._recognize_sensevoice_snapshot(
                    session,
                    language="en",
                    force=True,
                    purpose="final_correction",
                )
                if corrected:
                    caption = session.caption_formatter.update(
                        corrected,
                        time.monotonic(),
                        source_lang="en",
                    )
                    session.last_source_text = caption.punctuated_text
                    session.last_caption = {
                        "previous_line": caption.previous_line,
                        "current_line": caption.current_line,
                        "mode": caption.mode,
                    }
                    session.revision += 1
            except Exception as exc:
                logger.warning(
                    "English end-hint correction failed; retaining rolling text: %s",
                    exc,
                )

        pcm_bytes = b"".join(session._utterance_buffer)
        audio = self.get_buffered_audio(session_key)
        if audio is None:
            return None

        result = {
            "audio": audio.copy(),
            "sr": 16000,
            "utterance_id": session.current_utterance_id,
            "meeting_id": session.meeting_id,
            "seat_id": session.seat_id,
            "source_text": session.last_source_text,
            "audio_seconds": session.utterance_audio_seconds,
            "requested_language": session.requested_language,
            "detected_language": session.detected_language,
            "recognition_engine": session.recognition_engine,
            "recognized_text": (
                session.last_sensevoice_text
                if session.recognition_engine == "sensevoice_rolling_fallback"
                else ""
            ),
            "recognition_status": (
                "degraded" if session.sensevoice_last_error else "ok"
            ),
            "live_flush": live_flush,
            "revision": session.revision,
            "caption": dict(session.last_caption),
        }

        try:
            save_speech_debug_capture(
                session,
                pcm_bytes=pcm_bytes,
                boundary_reason="end_hint",
            )
        except Exception as exc:
            logger.warning("Speech debug capture failed: %s", exc)

        # Clear buffer; keep utterance_id/revision for event correlation
        session._utterance_buffer.clear()
        session.voice_active = False
        session.utterance_state = UTTERANCE_STATE_FINALIZING
        inference_runtime.update_stream(
            session_key,
            voice_active=False,
            backlog_ms=session.audio_backlog_ms,
        )
        self._publish_speaking_stop(session)
        return result

    # ── Session management ─────────────────────────────────────────────────

    def create_session(
        self, meeting_id: int, seat_id: int,
    ) -> tuple[str, str]:
        """Create a new speech stream session.

        Returns (session_key, session_token) where session_token is a
        unique identifier for this specific connection instance. Used by
        remove_session() for identity-safe cleanup.

        When a second connection opens for the same (meeting_id, seat_id),
        the old session is replaced in _sessions but its token remains
        unique. The old connection's finally block cannot delete the new
        session because its token won't match.

        Args:
            meeting_id: The active meeting ID.
            seat_id: The Speaker Seat ID (1..9).

        Returns:
            Tuple of (session_key, session_token).
        """
        session_key = f"speech_{meeting_id}_{seat_id}"
        if session_key in self._sessions:
            logger.warning(
                "Session %s already exists — replacing",
                session_key,
            )
        session = SpeechStreamSession(
            meeting_id=meeting_id,
            seat_id=seat_id,
            session_key=session_key,
        )
        self._sessions[session_key] = session
        logger.info(
            "Session created: %s token=%s (meeting=%d, seat=%d)",
            session_key, session.session_token, meeting_id, seat_id,
        )
        return session_key, session.session_token

    def get_session(self, session_key: str) -> SpeechStreamSession | None:
        """Get a session by key, or None."""
        return self._sessions.get(session_key)

    def remove_session(self, session_key: str, session_token: str) -> bool:
        """Remove a session only if its token matches. Identity-safe.

        If a newer connection replaced this session under the same key,
        the stored session's token will differ and removal is skipped.
        This prevents a stale WS handler from deleting the new session.

        Also cleans up the SpeechModule's per-session state for the key.

        Args:
            session_key: The session key from create_session().
            session_token: The token that was returned alongside session_key.

        Returns:
            True if the session was actually removed, False if skipped.
        """
        session = self._sessions.get(session_key)
        if session is None or session.session_token != session_token:
            logger.debug(
                "remove_session skipped: token mismatch or no session "
                "(key=%s)", session_key,
            )
            return False

        self._publish_speaking_stop(session)

        del self._sessions[session_key]
        inference_runtime.remove_stream(session_key)
        logger.debug("Session removed: %s (token=%s)", session_key, session_token)

        if self._speech_module is not None and self._speech_module.ready:
            self._speech_module._sessions.pop(session_key, None)

        return True

    @property
    def active_session_count(self) -> int:
        """Number of currently active sessions."""
        return len(self._sessions)

    def max_buffered_audio_seconds(self) -> float:
        """Largest active per-utterance audio buffer duration."""
        return round(max(
            (session.utterance_audio_seconds for session in self._sessions.values()),
            default=0.0,
        ), 3)

    # ── Utterance ID generation ────────────────────────────────────────────

    def seed_utterance_sequence(
        self, meeting_id: int, seat_id: int, persisted_sequence: int,
    ) -> None:
        """Raise the in-memory counter to at least the persisted sequence."""
        key = (meeting_id, seat_id)
        current = self._utterance_sequences.get(key, 0)
        if persisted_sequence > current:
            self._utterance_sequences[key] = persisted_sequence
            logger.info(
                "Seeded utterance sequence: meeting=%d seat=%d seq=%d",
                meeting_id, seat_id, persisted_sequence,
            )

    def generate_utterance_id(self, meeting_id: int, seat_id: int) -> str:
        """Generate a monotonically increasing unique utterance ID.

        The sequence counter is independent of SpeechStreamSession lifecycle:
        it lives in `_utterance_sequences` keyed by (meeting_id, seat_id).
        This guarantees that reconnections produce non-conflicting IDs.

        Format per ADR 0003: utt_{meeting_id}_{seat_id}_{seq:06d}
        e.g. "utt_1_1_000042" or "utt_1_1_000043" after reconnect.

        Args:
            meeting_id: The active meeting ID.
            seat_id: The Speaker Seat ID.

        Returns:
            e.g. "utt_1_3_000042"
        """
        key = (meeting_id, seat_id)
        seq = self._utterance_sequences.get(key, 0) + 1
        self._utterance_sequences[key] = seq

        uid = (
            f"utt_{meeting_id}_{seat_id}_"
            f"{seq:06d}"
        )

        # Also update the session-level counter for internal consistency
        session_key = f"speech_{meeting_id}_{seat_id}"
        session = self._sessions.get(session_key)
        if session is not None:
            session.utterance_count = seq

        logger.debug("Generated utterance_id: %s (seq=%d)", uid, seq)
        return uid


# Module-level singleton — shared across all speech WS connections.
stream_service = SpeechStreamService()


# ── Background preload (Task 119) ──────────────────────────────────────────────


def _start_daemon_thread(
    target: threading.Thread,  # type: ignore[arg-type]
    name: str = "speech-preload",
) -> threading.Thread:
    """Start a daemon thread for background tasks.

    Extracted as a separate function for testability — tests can patch this
    narrow function instead of ``threading.Thread.start`` globally, which
    avoids interfering with Starlette/FastAPI ``TestClient`` internals.

    Args:
        target: Callable for the thread to run.
        name: Thread name for debugging.

    Returns:
        The started daemon thread.
    """
    thread = threading.Thread(target=target, daemon=True, name=name)
    thread.start()
    return thread


def _preload_speech_models_background() -> None:
    """Trigger SpeechModule preload in a background daemon thread.

    Service-level concurrency control:
    - At most one preload thread runs at a time.
    - Creates ``_speech_module`` immediately with ``preloading=True`` so that
      ``GET /api/speech/status`` reflects the loading state right away.
    - Idempotent: subsequent calls while preload is running are no-ops.

    Thread-safety:
    - ``_preload_started`` flag guarded by ``_preload_lock`` (double-checked).
    - ``SpeechModule.preload()`` has its own internal lock for model loading.
    """
    # Fast path: already started (lock-free check)
    if stream_service._preload_started:
        logger.debug("Background preload already in progress — skipping")
        return

    with stream_service._preload_lock:
        # Double-check after acquiring lock
        if stream_service._preload_started:
            return
        # Already loaded — no-op
        if (
            stream_service._speech_module is not None
            and stream_service._speech_module.ready
        ):
            return

        stream_service._preload_started = True

        # Create SpeechModule immediately for API status visibility.
        # This ensures GET /api/speech/status returns preloading=true
        # without waiting for the background thread to start.
        if stream_service._speech_module is None:
            from backend.speech_module import SpeechModule

            module = SpeechModule()
            module._status["preloading"] = True
            stream_service._speech_module = module
        else:
            stream_service._speech_module._status["preloading"] = True

    def _run() -> None:
        try:
            module = stream_service._speech_module
            module.preload()  # thread-safe, idempotent
            try:
                from backend.services.translation_model_service import (
                    TranslationModelService,
                    is_translation_model_enabled,
                )
                if is_translation_model_enabled():
                    TranslationModelService.get_instance().load_all()
            except Exception as exc:
                logger.warning("Background translation preload failed: %s", exc)
            if module.ready:
                logger.info("Background preload: all models ready")
            else:
                logger.warning(
                    "Background preload: models not ready "
                    "(streaming=%s offline=%s punc=%s)",
                    module.status.get("streaming_model", "?"),
                    module.status.get("offline_model", "?"),
                    module.status.get("punctuation_model", "?"),
                )
        except Exception as exc:
            logger.warning("Background preload failed: %s", exc)
        finally:
            stream_service._preload_started = False

    _start_daemon_thread(_run, name="speech-preload")
    logger.debug("Background preload thread started")
