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
import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


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
        # Phase 4: PCM16 audio buffer for current utterance (concatenated raw bytes)
        self._utterance_buffer: list[bytes] = []


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

    # ── SpeechModule (lazy-loaded) ───────────────────────────────────────────

    def _get_speech_module(self):
        """Lazy-load and preload SpeechModule. Raises RuntimeError on failure."""
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
        return self._speech_module

    @property
    def is_speech_available(self) -> bool:
        """True if SpeechModule has been loaded and is ready.

        Does NOT trigger loading — only returns current state.
        """
        return self._speech_module is not None and self._speech_module.ready

    def ensure_speech_module(self) -> bool:
        """Attempt to load SpeechModule. Returns True if successful.

        Triggers lazy load (preload models, warmup). Safe to call
        multiple times — cached on success or error.

        Returns:
            True if models are loaded and ready, False otherwise.
        """
        try:
            self._get_speech_module()
            return True
        except RuntimeError:
            return False

    # ── PCM16 conversion ─────────────────────────────────────────────────────

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
        """
        session = self._sessions.get(session_key)
        if session is None:
            return None
        uid = session.current_utterance_id
        session.current_utterance_id = None
        session.revision = 0
        session._utterance_buffer.clear()
        if self._speech_module is not None and self._speech_module.ready:
            self._speech_module.reset_interim(session_key)
        return uid

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
        source_text = sm.process_interim_array(audio, session_key)

        # 6. Bump revision
        session.revision += 1

        return {
            "utterance_id": session.current_utterance_id,
            "revision": session.revision,
            "source_text": source_text,
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
        """
        session = self._sessions.get(session_key)
        if session is None or not session._utterance_buffer:
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
