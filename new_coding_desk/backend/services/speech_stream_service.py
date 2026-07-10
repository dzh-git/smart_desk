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

#: RMS threshold below which audio is considered silence (16kHz mono).
VAD_SILENCE_THRESHOLD_RMS: float = 0.006

#: Seconds of consecutive silence before auto-final is triggered.
VAD_SILENCE_DURATION_S: float = 1.2

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
        """Update VAD silence counter and return True if utterance should end.

        Called after each PCM frame processing. Updates the session's
        accumulated silence counter based on RMS of the audio frame.

        Returns True when consecutive silence exceeds VAD_SILENCE_DURATION_S,
        indicating the utterance should be auto-finalized.

        Args:
            session_key: Active speech session key.
            audio: float32 audio array from pcm16_to_float32().

        Returns:
            True if silence threshold exceeded (trigger auto-final).
        """
        session = self._sessions.get(session_key)
        if session is None:
            return False

        # Compute RMS of this frame
        rms = self._compute_rms(audio)
        frame_duration_s = float(len(audio)) / 16000.0  # 16kHz

        if rms < VAD_SILENCE_THRESHOLD_RMS:
            # Silence detected — accumulate
            session.vad_silence_seconds += frame_duration_s
            if session.vad_silence_seconds >= VAD_SILENCE_DURATION_S:
                logger.debug(
                    "VAD auto-final triggered for session %s "
                    "(silence=%.2fs rms=%.4f)",
                    session_key, session.vad_silence_seconds, rms,
                )
                return True
        else:
            # Speech detected — reset silence counter
            if session.vad_silence_seconds > 0:
                session.vad_silence_seconds = 0.0

        return False

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
        self, session_key: str, utterance_id: str,
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
        session.current_utterance_id = utterance_id
        session.revision = 0
        session._utterance_buffer.clear()
        session.caption_formatter.reset()
        # Task 122: reset VAD state
        session.utterance_state = UTTERANCE_STATE_SPEAKING
        session.vad_silence_seconds = 0.0

        # Lighting: a speaker is now talking -> AI_SPEAKING on this seat.
        event_bus.publish(
            SpeakerSpeakingEvent(
                meeting_id=session.meeting_id,
                payload={"seat_id": session.seat_id},
            )
        )

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
        # Lighting: speaker stopped -> revert this seat from AI_SPEAKING.
        event_bus.publish(
            SpeakerSpeakingStopEvent(
                meeting_id=session.meeting_id,
                payload={"seat_id": session.seat_id},
            )
        )
        if self._speech_module is not None and self._speech_module.ready:
            self._speech_module.reset_interim(session_key)
        return uid

    def reset_caption_formatter(self, session_key: str) -> None:
        """Reset the caption formatter for a session (e.g. after finalization)."""
        session = self._sessions.get(session_key)
        if session is not None:
            session.caption_formatter.reset()

    def prepare_next_utterance(
        self, session_key: str, meeting_id: int, seat_id: int,
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
        self.start_utterance(session_key, new_uid)
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

        # 2. Buffer raw PCM16 for final ASR (Phase 4)
        self.append_audio(session_key, pcm_bytes)

        # 3. Convert PCM16 → float32 numpy for interim ASR
        audio = self.pcm16_to_float32(pcm_bytes)

        # 4. Get SpeechModule (lazy loads, raises if unavailable)
        sm = self._get_speech_module()

        # 5. Run streaming ASR
        sm.set_session_context(
            session_key, session.meeting_id, session.seat_id,
        )
        trace("asr_streaming_start_at",
              utterance_id=session.current_utterance_id,
              meeting_id=session.meeting_id,
              seat_id=session.seat_id)
        _asr_t0 = time.perf_counter()
        raw_text = sm.process_interim_array(audio, session_key)
        _asr_ms = round((time.perf_counter() - _asr_t0) * 1000)

        # 6. Apply caption formatter (Phase 02)
        _now = time.monotonic()
        caption_result = session.caption_formatter.update(raw_text, _now)
        caption_result = (
            session.caption_formatter.check_timeout(_now) or caption_result
        )

        # 7. Bump revision
        session.revision += 1

        # 8. Task 122: Check VAD for auto-final detection
        vad_should_finalize = self._check_vad_end(session_key, audio)

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
            "source_text": caption_result.punctuated_text,
            "caption": {
                "previous_line": caption_result.previous_line,
                "current_line": caption_result.current_line,
                "mode": caption_result.mode,
            },
            "vad_should_finalize": vad_should_finalize,
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
        if session is None or not session._utterance_buffer:
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
            seat_id: The Speaker Seat ID (1..10).

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

        # Lighting: session gone -> revert this seat from AI_SPEAKING.
        event_bus.publish(
            SpeakerSpeakingStopEvent(
                meeting_id=session.meeting_id,
                payload={"seat_id": session.seat_id},
            )
        )

        del self._sessions[session_key]
        logger.debug("Session removed: %s (token=%s)", session_key, session_token)

        if self._speech_module is not None and self._speech_module.ready:
            self._speech_module._sessions.pop(session_key, None)

        return True

    @property
    def active_session_count(self) -> int:
        """Number of currently active sessions."""
        return len(self._sessions)

    # ── Utterance ID generation ────────────────────────────────────────────

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
