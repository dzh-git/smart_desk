"""SpeechModule — production facade for speech recognition and translation.

Wraps Paraformer Streaming (streaming STT), Paraformer-large (offline STT),
FSMN-VAD (voice activity detection), and audio preprocessing.

Implements the interface specified in docs/speech-module-spec.md §1.1.
Adds sentence-boundary-aware text merging to prevent over-splitting when
speakers pause mid-sentence (see docs/speech_module_interface_diff.md §2).

Lifecycle:
    sm = SpeechModule(max_workers=4)
    sm.preload()          # load all models, warmup
    text = sm.transcribe("audio.wav")
    interim = sm.process_interim_chunk("chunk.wav", session_key="seat_3")
"""

from __future__ import annotations
import numpy as np
from typing import Optional


class SpeechModule:
    """Production interface for the meeting translation backend.

    All STT methods return "" on failure (no exceptions). MT methods return
    placeholder strings until Opus-MT is integrated.
    """

    def __init__(
        self, max_workers: int = 4,
        history_store: Optional["HistoryStore"] = None,
    ):
        self._max_workers = max_workers
        self._ready = False
        self._history_store = history_store

        # Per-session streaming state: session_key -> state dict
        # Each state dict:
        #   "processor"        : StreamingChunkProcessor (CIF cache + accumulated text)
        #   "meeting_id"       : int | None  (set via set_session_context)
        #   "seat_id"          : int | None  (set via set_session_context)
        #   "next_segment_id"  : int  (unused after Task 112 — was for _record_commit)
        self._sessions: dict[str, dict] = {}

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def ready(self) -> bool:
        """True after preload() has completed successfully."""
        return self._ready

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def preload(self) -> None:
        """Load all models + warmup. Idempotent. Raises on failure."""
        if self._ready:
            return
        from .stt_streaming import warmup_streaming, warmup_offline
        warmup_streaming()   # Paraformer Streaming for process_interim_*
        warmup_offline()     # Paraformer-large for transcribe / transcribe_array
        self._ready = True

    # ── STT ──────────────────────────────────────────────────────────────────

    def transcribe(self, audio_path: str) -> str:
        """Transcribe an audio file. Returns "" on failure (no raise)."""
        try:
            from .audio_utils import load_audio
            audio, sr = load_audio(audio_path)
            return self.transcribe_array(audio, sr)
        except Exception:
            return ""

    def transcribe_array(
        self, audio: np.ndarray, sample_rate: int = 16000,
    ) -> str:
        """Transcribe a float32 mono array. Returns "" on failure."""
        try:
            from .stt_streaming import offline_rescore
            if sample_rate != 16000:
                from .audio_utils import resample_if_needed
                audio = resample_if_needed(audio, sample_rate, 16000)
            return offline_rescore(audio)
        except Exception:
            return ""

    # ── Translation ──────────────────────────────────────────────────────────

    def translate_text(self, text: str) -> tuple[str, str]:
        """Auto-detect language → return (zh_str, en_str). Neither is None.

        Currently returns identity for the detected language and a placeholder
        for the other. Replace with real MT engine when available.
        """
        from .text_utils import detect_language
        lang = detect_language(text)
        if lang == "zh":
            return (text, "[translation not available]")
        return ("[translation not available]", text)

    def transcribe_and_translate(self, audio_path: str) -> tuple[str, str]:
        """STT → translate pipeline. Never raises."""
        text = self.transcribe(audio_path)
        if not text:
            return ("[无法识别语音]", "[translation unavailable]")
        return self.translate_text(text)

    # ── Streaming Interim ────────────────────────────────────────────────────

    def process_interim_chunk(
        self, audio_path: str, session_key: str = "default",
    ) -> str:
        """Transcribe an audio chunk, return accumulated text.

        Returns the raw cumulative full_text from StreamingChunkProcessor.
        No SentenceMerger post-processing (see Task 112).
        """
        from .audio_utils import load_audio
        audio, sr = load_audio(audio_path)
        return self.process_interim_array(audio, session_key, sr)

    def process_interim_array(
        self, audio: np.ndarray, session_key: str = "default",
        sample_rate: int = 16000,
    ) -> str:
        """Transcribe audio array chunk, return accumulated full text.

        Returns the raw cumulative full_text from StreamingChunkProcessor
        directly. Does NOT pass through SentenceMerger, because
        result["full_text"] is already the accumulated text with overlap-aware
        merging applied by StreamingChunkProcessor. Sending cumulative text
        through SentenceMerger would cause duplication when the merger flushes
        (see Task 112 root cause: committed old full text + pending new full
        text that includes the old text = duplicated output).

        The CIF encoder/decoder cache is kept alive across all chunks in a
        session (is_final is always False here).
        """
        state = self._ensure_session(session_key)
        processor = state["processor"]

        if sample_rate != 16000:
            from .audio_utils import resample_if_needed
            audio = resample_if_needed(audio, sample_rate, 16000)

        # Never set is_final=True — CIF cache stays alive across chunks.
        # Sentence boundaries are determined by text content, not VAD.
        result = processor.process_chunk(audio, is_final=False)

        # Task 112: return raw cumulative full_text directly.
        # Bypass SentenceMerger entirely to prevent committed + pending
        # duplication when cumulative text grows beyond flush thresholds.
        return result["full_text"]

    def reset_interim(self, session_key: str = "default") -> None:
        """Reset accumulated text for a new utterance. Preserves CIF cache."""
        state = self._sessions.get(session_key)
        if state is not None:
            state["processor"].reset_accumulated_text()

    def start_utterance(self, session_key: str = "default") -> None:
        """Mark start of a new utterance. Resets SentenceMerger only."""
        self.reset_interim(session_key)

    def get_interim(self, session_key: str = "default") -> str:
        """Get current accumulated text without processing new audio."""
        state = self._sessions.get(session_key)
        if state is None:
            return ""
        return state["processor"].accumulated_text

    # ── Session Context ────────────────────────────────────────────────────

    def set_session_context(
        self, session_key: str, meeting_id: int, seat_id: int,
    ) -> None:
        """Set meeting/seat metadata for a streaming session.

        Enables automatic history recording when sentences are committed.
        Call this once per session before process_interim_chunk/array.
        """
        state = self._ensure_session(session_key)
        state["meeting_id"] = meeting_id
        state["seat_id"] = seat_id

    # ── History Query ──────────────────────────────────────────────────────

    def get_history(
        self, meeting_id: int, seat_id: int | None = None,
        limit: int = 200, offset: int = 0,
    ) -> list[dict]:
        """Query translation history for a meeting/seat.

        Requires history_store to be configured in __init__.
        Returns empty list if no store is available.
        """
        if self._history_store is None:
            return []
        if seat_id is not None:
            return self._history_store.query_by_seat(
                meeting_id, seat_id, limit=limit, offset=offset,
            )
        return self._history_store.query_by_meeting(
            meeting_id, limit=limit, offset=offset,
        )

    def get_next_segment_id(
        self, meeting_id: int, seat_id: int,
    ) -> int:
        """Return the next available segment_id for a meeting-seat pair.

        Returns 1 if no history exists or no store configured.
        """
        if self._history_store is None:
            return 1
        return self._history_store.get_last_segment_id(meeting_id, seat_id) + 1

    # ── Internal Helpers ─────────────────────────────────────────────────────

    def _ensure_session(self, session_key: str) -> dict:
        """Get or create per-session state."""
        if session_key not in self._sessions:
            from .stt_streaming import StreamingChunkProcessor
            self._sessions[session_key] = {
                "processor": StreamingChunkProcessor(),
                "meeting_id": None,
                "seat_id": None,
                "next_segment_id": 1,
            }
        return self._sessions[session_key]

    # NOTE (Task 112): _merge_sentence_aware and _record_commit were removed.
    # They previously fed cumulative full_text through SentenceMerger, causing
    # committed + pending duplication when flush thresholds were exceeded.
    # process_interim_array now returns StreamingChunkProcessor's full_text
    # directly. If SentenceMerger is needed for future sentence-boundary
    # segmentation of final text, it must operate on incremental segment text
    # (not cumulative full_text), or use a dedicated "cumulative mode".
