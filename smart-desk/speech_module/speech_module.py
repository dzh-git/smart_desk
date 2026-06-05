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
import importlib.util
import os
import time
import numpy as np
from typing import Optional
from .audio_utils import resample_if_needed


class SpeechModule:
    """Production interface for the meeting translation backend.

    All STT methods return "" on failure (no exceptions). MT methods return
    placeholder strings until Opus-MT is integrated.
    """

    def __init__(
        self, max_workers: int = 4,
        history_store: Optional["HistoryStore"] = None,
        mt_engine: Optional["MTEngine"] = None,
    ):
        self._max_workers = max_workers
        self._ready = False
        self._history_store = history_store
        self._mt_engine = mt_engine

        # Per-session streaming state: session_key -> state dict
        # Each state dict:
        #   "processor"        : StreamingChunkProcessor (CIF cache + accumulated text)
        #   "pending_text"     : str  (text awaiting sentence-final punctuation)
        #   "committed_text"   : str  (completed sentences, flushed)
        #   "pending_start_time": float (monotonic timestamp when pending started)
        #   "meeting_id"       : int | None  (set via set_session_context)
        #   "seat_id"          : int | None  (set via set_session_context)
        #   "next_segment_id"  : int  (auto-incremented per commit)
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
        for dep in ("torch", "funasr"):
            if importlib.util.find_spec(dep) is None:
                raise RuntimeError(
                    f"Missing required speech dependency: {dep}. "
                    "Install backend speech dependencies before enabling speech recognition."
                )
        from .stt_streaming import warmup_streaming, warmup_offline
        warmup_streaming()   # Paraformer Streaming for process_interim_*
        warmup_offline()     # Paraformer-large for transcribe / transcribe_array
        if self._mt_engine and os.environ.get("SMART_DESK_ENABLE_MT") == "1":
            self._mt_engine.preload()
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

    def transcribe_array(self, audio: np.ndarray, sr: int) -> str:
        """Transcribe audio array, auto-resampling to 16kHz if needed.

        Delegates to centralized resample_if_needed (CR-013).
        """
        try:
            from .stt_streaming import offline_rescore
            if sr != 16000:
                audio = resample_if_needed(audio, sr, 16000)
            return offline_rescore(audio)
        except Exception:
            return ""

    # ── Translation ──────────────────────────────────────────────────────────

    def translate_text(self, text: str) -> tuple[str, str]:
        """Auto-detect language → return (zh_str, en_str). Neither is None.

        Delegates to MTEngine if available, otherwise returns placeholder.
        """
        if self._mt_engine and self._mt_engine.ready:
            return self._mt_engine.translate(text)
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
        """Transcribe an audio chunk, merge with previous results.

        Returns accumulated text (committed + pending). Sentence-boundary-aware:
        text accumulates until sentence-final punctuation is seen.
        """
        from .audio_utils import load_audio
        audio, sr = load_audio(audio_path)
        return self.process_interim_array(audio, session_key, sr)

    def process_interim_array(
        self, audio: np.ndarray, session_key: str = "default",
        sample_rate: int = 16000,
    ) -> str:
        """Transcribe audio array chunk with sentence-boundary-aware merging.

        The CIF encoder/decoder cache is kept alive across all chunks in a
        session. Sentence boundaries are detected from text content (punctuation),
        not from audio VAD signals. This prevents over-splitting when speakers
        pause mid-sentence.
        """
        state = self._ensure_session(session_key)
        processor = state["processor"]

        if sample_rate != 16000:
            audio = resample_if_needed(audio, sample_rate, 16000)

        # Never set is_final=True — CIF cache stays alive across chunks.
        # Sentence boundaries are determined by text content, not VAD.
        result = processor.process_chunk(audio, is_final=False)
        raw_text = result["full_text"]

        return self._merge_sentence_aware(state, raw_text)

    def reset_interim(self, session_key: str = "default") -> None:
        """Reset SentenceMerger state for a new utterance. Preserves CIF cache."""
        state = self._sessions.get(session_key)
        if state is not None:
            state["merger"].reset()

    def start_utterance(self, session_key: str = "default") -> None:
        """Mark start of a new utterance. Resets SentenceMerger only."""
        self.reset_interim(session_key)

    def get_last_utterance_id(self, session_key: str = "default") -> int:
        """Get the last utterance_id tracked for a session. Returns -1 if unset."""
        state = self._sessions.get(session_key)
        if state is None:
            return -1
        return state.get("_last_utterance_id", -1)

    def set_last_utterance_id(self, session_key: str, utterance_id: int) -> None:
        """Set the last utterance_id for a streaming session."""
        state = self._ensure_session(session_key)
        state["_last_utterance_id"] = utterance_id

    def get_interim(self, session_key: str = "default") -> str:
        """Get current accumulated text without processing new audio."""
        state = self._sessions.get(session_key)
        if state is None:
            return ""
        merger = state["merger"]
        committed = "".join(dl["text"] for dl in merger.committed_lines)
        return committed + merger.pending_text

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
            from .sentence_merge import SentenceMerger
            self._sessions[session_key] = {
                "processor": StreamingChunkProcessor(),
                "merger": SentenceMerger(),
                "meeting_id": None,
                "seat_id": None,
                "next_segment_id": 1,
            }
        return self._sessions[session_key]

    def _merge_sentence_aware(self, state: dict, raw_text: str) -> str:
        """Merge raw ASR output with pending text, flushing on sentence boundary.

        Delegates to SentenceMerger for joint decision logic
        (punctuation + length + age + gap).

        Returns committed_text + pending_text (the full visible output).
        """
        merger = state["merger"]
        flushed = merger.feed(raw_text, time.monotonic(), segment_id=0)
        if flushed is not None:
            self._record_commit(state, flushed)

        committed = "".join(dl["text"] for dl in merger.committed_lines)
        return committed + merger.pending_text

    def _record_commit(self, state: dict, text: str) -> None:
        """Record committed sentence to history store if configured."""
        if self._history_store is None:
            return
        mid = state.get("meeting_id")
        sid = state.get("seat_id")
        if mid is None or sid is None:
            return
        seg_id = state["next_segment_id"]
        self._history_store.upsert(
            meeting_id=mid, seat_id=sid, segment_id=seg_id,
            zh_text=text, en_text="", is_final=True,
        )
        state["next_segment_id"] = seg_id + 1
