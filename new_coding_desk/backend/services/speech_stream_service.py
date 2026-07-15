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
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import numpy as np

from backend.speech_module.caption_formatter import CaptionFormatter
from backend.websocket.speech_trace import trace
from backend.events import event_bus
from backend.events.speech_events import (
    SpeakerSpeakingEvent,
    SpeakerSpeakingStopEvent,
)

logger = logging.getLogger(__name__)

# ── VAD configuration (Task 122) ──────────────────────────────────────────────

# Adaptive low-latency voice gate defaults.  Values are float32 PCM RMS.
VAD_SILENCE_THRESHOLD_RMS: float = 0.010  # compatibility alias / minimum onset
VAD_CONTINUE_THRESHOLD_RMS: float = 0.007
VAD_NOISE_START_RATIO: float = 2.0
VAD_NOISE_CONTINUE_RATIO: float = 1.5
VAD_CALIBRATION_FRAMES: int = 5          # 500 ms at 100 ms/frame
VAD_PRE_ROLL_FRAMES: int = 3             # retain the first consonants
VAD_START_CONFIRM_FRAMES: int = 2

# Boundary policy: punctuation + pause first, silence fallback last.
VAD_SENTENCE_PAUSE_S: float = 0.9
VAD_CLAUSE_PAUSE_S: float = 1.3
VAD_NATURAL_PAUSE_S: float = 2.0
VAD_SILENCE_DURATION_S: float = 3.0      # compatibility alias / hard silence
VAD_SOFT_UTTERANCE_S: float = 30.0
VAD_MAX_UTTERANCE_S: float = 45.0
ROLLOVER_OVERLAP_MS: int = 300
ROLLOVER_OVERLAP_BYTES: int = int(16000 * 2 * ROLLOVER_OVERLAP_MS / 1000)
CONTINUOUS_ROLLOVER_REASONS = frozenset({
    "soft_sentence_limit",
    "soft_clause_limit",
    "max_duration",
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
        self.last_source_text = ""
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

        # Add punctuation_fallback indicator
        try:
            from backend.speech_module.punctuation import is_punctuation_loaded
            base["punctuation_fallback"] = not is_punctuation_loaded()
        except Exception:
            base["punctuation_fallback"] = True

        try:
            from backend.services.translation_model_service import (
                TranslationModelService,
                is_translation_model_enabled,
            )
            translation = TranslationModelService.get_instance()
            base["translation_model"] = (
                "loaded" if translation.loaded else (
                    "error" if translation.load_error else (
                        "unknown" if is_translation_model_enabled() else "disabled"
                    )
                )
            )
            base["translation_model_path"] = translation.model_path
            base["translation_last_error"] = translation.load_error
        except Exception as exc:
            base["translation_model"] = "error"
            base["translation_last_error"] = str(exc)

        base["voice_gate"] = {
            "minimum_onset_rms": VAD_SILENCE_THRESHOLD_RMS,
            "minimum_continue_rms": VAD_CONTINUE_THRESHOLD_RMS,
            "noise_start_ratio": VAD_NOISE_START_RATIO,
            "noise_continue_ratio": VAD_NOISE_CONTINUE_RATIO,
            "sentence_pause_seconds": VAD_SENTENCE_PAUSE_S,
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
            }
            for session in self._sessions.values()
        ]
        base["soft_utterance_seconds"] = VAD_SOFT_UTTERANCE_S
        base["hard_utterance_seconds"] = VAD_MAX_UTTERANCE_S
        base["rollover_overlap_ms"] = ROLLOVER_OVERLAP_MS
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
            session.voice_start_frames = 0
            admitted = list(session._pre_roll)
            session._pre_roll.clear()
            return admitted, True

        if rms >= continue_threshold:
            session.vad_silence_seconds = 0.0
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
    ) -> str | None:
        if not session.has_speech:
            return None
        if session.utterance_audio_seconds >= VAD_MAX_UTTERANCE_S:
            return "max_duration"

        silence = session.vad_silence_seconds
        stripped = text.rstrip()
        meaningful = self._meaningful_length(stripped)
        if stripped and meaningful >= 2:
            if stripped[-1] in "。！？.!?" and silence >= VAD_SENTENCE_PAUSE_S:
                return "sentence_pause"
            if stripped[-1] in "，；：,;:" and silence >= VAD_CLAUSE_PAUSE_S:
                return "clause_pause"
            if (
                session.utterance_audio_seconds >= VAD_SOFT_UTTERANCE_S
                and natural_boundary_committed
            ):
                if committed_boundary in "。！？.!?":
                    return "soft_sentence_limit"
                if committed_boundary in "，；：,;:":
                    return "soft_clause_limit"
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
        session.last_source_text = ""
        session.last_caption = {
            "previous_line": "",
            "current_line": "",
            "mode": "two_line",
        }
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
        # Task 122: reset VAD state
        session.utterance_state = UTTERANCE_STATE_IDLE
        session.vad_silence_seconds = 0.0
        session.voice_active = False
        session.has_speech = False
        session._pre_roll.clear()
        session._rollover_overlap_pcm = b""
        session._rollover_started_at = None
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

    def snapshot_auto_finalization(
        self,
        session_key: str,
        source_text: str,
        boundary_reason: str,
    ) -> dict[str, Any] | None:
        """Terminate and clear an automatic segment without materializing audio."""
        session = self._sessions.get(session_key)
        if session is None or not session.current_utterance_id:
            return None
        utterance_id = session.current_utterance_id
        if utterance_id in session.terminal_utterance_ids:
            return None

        text = (source_text or session.last_source_text).strip()
        continuous_rollover = boundary_reason in CONTINUOUS_ROLLOVER_REASONS
        overlap_pcm = b""
        if continuous_rollover and session._utterance_buffer:
            overlap_pcm = b"".join(session._utterance_buffer)[-ROLLOVER_OVERLAP_BYTES:]
        snapshot = {
            "utterance_id": utterance_id,
            "meeting_id": session.meeting_id,
            "seat_id": session.seat_id,
            "source_text": text,
            "boundary_reason": boundary_reason,
            "audio_seconds": session.utterance_audio_seconds,
            "has_speech": session.has_speech,
            "caption": dict(session.last_caption),
            "continuous_rollover": continuous_rollover,
            "rollover_overlap_ms": round(len(overlap_pcm) / 32.0),
            "rollover_overlap_frames": (len(overlap_pcm) + 3199) // 3200,
        }

        session.terminal_utterance_ids.add(utterance_id)
        session._utterance_buffer.clear()
        session.caption_formatter.reset()
        session._rollover_overlap_pcm = overlap_pcm
        session.voice_active = continuous_rollover
        session.utterance_state = UTTERANCE_STATE_FINALIZING
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
            }

        # 3. Get SpeechModule (lazy loads, raises if unavailable)
        sm = self._get_speech_module()
        sm.set_session_context(
            session_key, session.meeting_id, session.seat_id,
        )
        overlap_pcm = session._rollover_overlap_pcm
        if overlap_pcm:
            try:
                sm.process_interim_array(
                    self.pcm16_to_float32(overlap_pcm), session_key,
                )
                # Keep the encoder/CIF cache primed by the replay, but discard
                # replay text so the 300 ms context cannot be persisted twice.
                sm.reset_interim(session_key)
            except Exception as exc:
                logger.warning(
                    "Speech rollover overlap replay failed: session=%s bytes=%d error=%s",
                    session_key,
                    len(overlap_pcm),
                    exc,
                )
            finally:
                session._rollover_overlap_pcm = b""
        trace("asr_streaming_start_at",
              utterance_id=session.current_utterance_id,
              meeting_id=session.meeting_id,
              seat_id=session.seat_id)
        _asr_t0 = time.perf_counter()
        raw_text = session.last_source_text
        for admitted in admitted_frames:
            self.append_audio(session_key, admitted)
            admitted_audio = self.pcm16_to_float32(admitted)
            session.utterance_audio_seconds += len(admitted_audio) / 16000.0
            raw_text = sm.process_interim_array(admitted_audio, session_key)
        _asr_ms = round((time.perf_counter() - _asr_t0) * 1000)

        # 4. Apply caption formatter and evaluate a content-aware boundary.
        _now = time.monotonic()
        caption_result = session.caption_formatter.update(raw_text, _now)
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
        )
        vad_should_finalize = boundary_reason is not None

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
                  vad_should_finalize=vad_should_finalize)

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

        audio = self.get_buffered_audio(session_key)
        if audio is None:
            return None

        result = {
            "audio": audio,
            "sr": 16000,
            "utterance_id": session.current_utterance_id,
            "meeting_id": session.meeting_id,
            "seat_id": session.seat_id,
        }

        # Clear buffer; keep utterance_id/revision for event correlation
        session._utterance_buffer.clear()
        session.voice_active = False
        session.utterance_state = UTTERANCE_STATE_FINALIZING
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
                    TranslationModelService.get_instance().load()
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
