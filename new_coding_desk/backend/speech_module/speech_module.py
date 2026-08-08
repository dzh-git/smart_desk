"""SpeechModule — production facade for speech recognition and translation.

Wraps Paraformer Streaming (streaming STT), SenseVoiceSmall (language detection
and English final STT), Paraformer-large (Chinese final STT),
FSMN-VAD (voice activity detection), CT-Transformer (punctuation restoration),
and audio preprocessing.

Implements the interface specified in docs/speech-module-spec.md §1.1.
Adds sentence-boundary-aware text merging to prevent over-splitting when
speakers pause mid-sentence (see docs/speech_module_interface_diff.md §2).

Lifecycle:
    sm = SpeechModule(max_workers=4)
    sm.preload()          # load all models, warmup
    text = sm.transcribe("audio.wav")
    interim = sm.process_interim_chunk("chunk.wav", session_key="seat_3")

Status tracking (Task 119):
    sm.preload()
    sm.status  -> {
        "ready": True,
        "preloading": False,
        "streaming_model": "loaded",
        "offline_model": "loaded",
        "bilingual_final_asr": "loaded",
        "chinese_final_asr": "loaded",
        "punctuation_model": "loaded",
        "last_error": None,
    }
"""

from __future__ import annotations
import threading
from typing import Optional

import numpy as np


# ── Model status constants ─────────────────────────────────────────────────────

STATUS_UNKNOWN = "unknown"
STATUS_LOADING = "loading"
STATUS_LOADED = "loaded"
STATUS_ERROR = "error"

_INITIAL_STATUS = {
    "ready": False,
    "preloading": False,
    "streaming_model": STATUS_UNKNOWN,
    "english_streaming_asr": STATUS_UNKNOWN,
    "english_online_punctuation": STATUS_UNKNOWN,
    "offline_model": STATUS_UNKNOWN,
    "bilingual_final_asr": STATUS_UNKNOWN,
    "chinese_final_asr": STATUS_UNKNOWN,
    "punctuation_model": STATUS_UNKNOWN,
    "vad_model": STATUS_UNKNOWN,
    "last_error": None,
}


class SpeechModule:
    """Production interface for the meeting translation backend.

    All STT methods return "" on failure (no exceptions). MT methods return
    placeholder strings until Opus-MT is integrated.

    Status is tracked per-instance via `self.status`.  Preload is idempotent
    and guarded by a threading.Lock so concurrent calls do not double-load.
    """

    def __init__(
        self, max_workers: int = 4,
        history_store: Optional["HistoryStore"] = None,
    ):
        self._max_workers = max_workers
        self._history_store = history_store

        # Unified status (Task 119)
        self._status: dict = dict(_INITIAL_STATUS)
        self._preload_lock = threading.Lock()

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
        return self._status["ready"]

    @property
    def status(self) -> dict:
        """Unified model status dict (read-only snapshot).

        Keys:
            ready             — bool, all models loaded
            preloading        — bool, preload in progress
            streaming_model   — "unknown" | "loading" | "loaded" | "error"
            english_streaming_asr — sherpa-onnx English online ASR status
            english_online_punctuation — sherpa-onnx English punctuation status
            offline_model     — "unknown" | "loading" | "loaded" | "error"
            bilingual_final_asr — SenseVoice language/English final status
            chinese_final_asr — Paraformer-large Chinese final status
            punctuation_model — "unknown" | "loading" | "loaded" | "error"
            last_error        — str | None
        """
        return dict(self._status)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def preload(self) -> None:
        """Load all models + warmup. Idempotent and thread-safe.

        Load order:
            1. Paraformer Streaming (for process_interim_*)
            2. sherpa-onnx Zipformer (for English online ASR; degradable)
            3. sherpa-onnx online punctuation (English text post-processing)
            4. SenseVoiceSmall (language detection and final ASR)
            5. Paraformer-large (for Chinese final ASR)
            6. CT-Transformer punctuation (for Chinese final punctuation)

        On failure, marks the failing model as STATUS_ERROR and keeps
        last_error populated.  Other models may still load.  The overall
        ready flag is only set when ALL models succeed.
        """
        # Fast path: already loaded
        if self._status["ready"]:
            return

        # Lock to prevent concurrent preload racing
        if not self._preload_lock.acquire(blocking=False):
            # Another thread is already preloading — wait for it
            self._preload_lock.acquire()
            self._preload_lock.release()
            return

        try:
            # Another thread may have completed preload while we waited for the lock
            if self._status["ready"]:
                return

            self._status["preloading"] = True

            # 1. Streaming model (Paraformer Streaming)
            self._status["streaming_model"] = STATUS_LOADING
            try:
                from .stt_streaming import warmup_streaming
                warmup_streaming()
                self._status["streaming_model"] = STATUS_LOADED
            except Exception as exc:
                self._status["streaming_model"] = STATUS_ERROR
                self._status["last_error"] = f"streaming: {exc}"
                _log_warning(f"Streaming model load failed: {exc}")

            # 2. English true streaming model. It is deliberately
            # non-blocking: a missing local Zipformer falls back to the
            # existing SenseVoice rolling path and must not take Chinese ASR
            # offline.
            self._status["english_streaming_asr"] = STATUS_LOADING
            try:
                from .english_streaming import warmup_english_streaming
                warmup_english_streaming()
                self._status["english_streaming_asr"] = STATUS_LOADED
            except Exception as exc:
                self._status["english_streaming_asr"] = STATUS_ERROR
                _log_warning(f"English streaming model load failed; fallback enabled: {exc}")

            # 3. Lightweight English online punctuation. Missing punctuation
            # delays sentence confirmation but must not take English ASR down.
            self._status["english_online_punctuation"] = STATUS_LOADING
            try:
                from .english_punctuation import warmup_english_punctuation
                warmup_english_punctuation()
                self._status["english_online_punctuation"] = STATUS_LOADED
            except Exception as exc:
                self._status["english_online_punctuation"] = STATUS_ERROR
                _log_warning(f"English online punctuation unavailable: {exc}")

            # 4. Bilingual language detection + English final ASR
            self._status["offline_model"] = STATUS_LOADING
            self._status["bilingual_final_asr"] = STATUS_LOADING
            try:
                from .bilingual_asr import warmup_bilingual_asr
                warmup_bilingual_asr()
                self._status["bilingual_final_asr"] = STATUS_LOADED
            except Exception as exc:
                self._status["bilingual_final_asr"] = STATUS_ERROR
                self._status["last_error"] = f"offline: {exc}"
                _log_warning(f"Bilingual final model load failed: {exc}")

            # 5. Chinese-specialized final ASR
            self._status["chinese_final_asr"] = STATUS_LOADING
            try:
                from .stt_streaming import warmup_offline
                warmup_offline()
                self._status["chinese_final_asr"] = STATUS_LOADED
            except Exception as exc:
                self._status["chinese_final_asr"] = STATUS_ERROR
                self._status["last_error"] = f"chinese_offline: {exc}"
                _log_warning(f"Chinese final model load failed: {exc}")

            self._status["offline_model"] = (
                STATUS_LOADED
                if self._status["bilingual_final_asr"] == STATUS_LOADED
                and self._status["chinese_final_asr"] == STATUS_LOADED
                else STATUS_ERROR
            )

            # 6. Punctuation model (CT-Transformer, Paraformer Chinese only)
            self._status["punctuation_model"] = STATUS_LOADING
            try:
                from .punctuation import warmup_punc
                warmup_punc()
                # Check whether warmup actually set the model
                from .punctuation import is_punctuation_loaded
                if is_punctuation_loaded():
                    self._status["punctuation_model"] = STATUS_LOADED
                else:
                    self._status["punctuation_model"] = STATUS_ERROR
                    self._status["last_error"] = "punctuation: warmup completed but model not loaded"
                    _log_warning("Punctuation model warmup did not set model instance")
            except Exception as exc:
                self._status["punctuation_model"] = STATUS_ERROR
                self._status["last_error"] = f"punctuation: {exc}"
                _log_warning(f"Punctuation model load failed: {exc}")

            # A usable meeting speech pipeline requires streaming and final ASR.
            # Translation failures remain non-blocking and are reported separately.
            all_ok = (
                self._status["streaming_model"] == STATUS_LOADED
                and self._status["bilingual_final_asr"] == STATUS_LOADED
                and self._status["chinese_final_asr"] == STATUS_LOADED
            )
            self._status["ready"] = all_ok

            # 5. FSMN-VAD is a quality layer. Failure is visible in status but
            # does not make ASR unavailable because the adaptive gate remains.
            self._status["vad_model"] = STATUS_LOADING
            try:
                from .fsmn_vad import get_default_vad
                get_default_vad()
                self._status["vad_model"] = STATUS_LOADED
            except Exception as exc:
                self._status["vad_model"] = STATUS_ERROR
                _log_warning(f"FSMN-VAD load failed: {exc}")

        finally:
            self._status["preloading"] = False
            self._preload_lock.release()

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
        """Transcribe a float32 mono array. Compatibility text-only wrapper."""
        try:
            return self.transcribe_array_with_language(audio, sample_rate).text
        except Exception:
            return ""

    def transcribe_array_with_language(
        self, audio: np.ndarray, sample_rate: int = 16000,
    ) -> "SpeechRecognitionResult":
        """Return automatic zh/en final text using the language-specific ASR."""
        from .bilingual_asr import SpeechRecognitionResult, recognize_bilingual

        if sample_rate != 16000:
            from .audio_utils import resample_if_needed

            audio = resample_if_needed(audio, sample_rate, 16000)
        result = recognize_bilingual(audio)
        if not isinstance(result, SpeechRecognitionResult):
            raise RuntimeError("Bilingual ASR returned an invalid result")
        if result.source_lang == "zh":
            try:
                from .stt_streaming import offline_rescore

                chinese_text = offline_rescore(audio).strip()
                if chinese_text:
                    return SpeechRecognitionResult(
                        text=chinese_text,
                        source_lang="zh",
                        recognition_model="paraformer_zh",
                    )
            except Exception as exc:
                _log_warning(f"Chinese final rescore unavailable, using SenseVoice: {exc}")
        return result

    def trim_to_speech(
        self, audio: np.ndarray, sample_rate: int = 16000,
    ) -> np.ndarray | None:
        """Return FSMN-confirmed speech or None; fall back on model failure."""
        try:
            from .fsmn_vad import trim_to_speech
            return trim_to_speech(audio, sample_rate)
        except Exception as exc:
            _log_warning(f"FSMN-VAD validation unavailable, using gated audio: {exc}")
            return audio

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
        *,
        is_final: bool = False,
    ) -> str:
        """Transcribe audio array chunk, return accumulated full text.

        Returns the raw cumulative full_text from StreamingChunkProcessor
        directly. Does NOT pass through SentenceMerger, because
        result["full_text"] is already the accumulated text with overlap-aware
        merging applied by StreamingChunkProcessor. Sending cumulative text
        through SentenceMerger would cause duplication when the merger flushes
        (see Task 112 root cause: committed old full text + pending new full
        text that includes the old text = duplicated output).

        The CIF encoder/decoder cache is kept alive across normal chunks.
        Set ``is_final=True`` exactly once at a confirmed speech pause to flush
        the decoder's pending final token(s) into the live hypothesis.
        """
        state = self._ensure_session(session_key)
        processor = state["processor"]

        if sample_rate != 16000:
            from .audio_utils import resample_if_needed
            audio = resample_if_needed(audio, sample_rate, 16000)

        result = processor.process_chunk(audio, is_final=is_final)

        # Task 112: return raw cumulative full_text directly.
        # Bypass SentenceMerger entirely to prevent committed + pending
        # duplication when cumulative text grows beyond flush thresholds.
        return result["full_text"]

    def finish_chinese_interim(self, session_key: str = "default") -> str:
        """Flush the Chinese online decoder without replaying speech audio.

        Paraformer Streaming keeps a small CIF look-ahead cache.  At a real
        pause the cache must be finalized, otherwise the final Chinese
        character can remain buffered until the utterance is reset.  A short
        zero tail supplies the explicit end marker without duplicating the
        preceding speech frame.
        """
        tail = np.zeros(1600, dtype=np.float32)  # 100 ms at 16 kHz
        return self.process_interim_array(
            tail,
            session_key,
            is_final=True,
        )

    def process_english_interim_array(
        self, audio: np.ndarray, session_key: str = "default",
        sample_rate: int = 16000,
    ) -> str:
        """Feed one PCM chunk into the session's true English online stream."""
        state = self._ensure_session(session_key)
        if sample_rate != 16000:
            from .audio_utils import resample_if_needed
            audio = resample_if_needed(audio, sample_rate, 16000)
        processor = state.get("english_processor")
        if processor is None:
            from .english_streaming import EnglishStreamingProcessor
            processor = EnglishStreamingProcessor()
            state["english_processor"] = processor
        return processor.process_chunk(audio, 16000)

    def finish_english_interim(self, session_key: str = "default") -> str:
        """Flush a session's English online recognizer at an explicit end."""
        state = self._sessions.get(session_key)
        processor = state.get("english_processor") if state else None
        return processor.finish() if processor is not None else ""

    def rotate_english_interim(self, session_key: str = "default") -> str:
        """Finish one English sentence and start a fresh online decoder.

        This deliberately does not reset the surrounding WebSocket utterance
        or VAD state.  The next PCM frame creates a new Zipformer stream, so
        later cumulative hypotheses cannot revise an already committed lyric.
        """
        state = self._sessions.get(session_key)
        processor = state.get("english_processor") if state else None
        if processor is None:
            return ""
        text = processor.finish()
        state["english_processor"] = None
        return text

    def reset_interim(self, session_key: str = "default") -> None:
        """Reset accumulated text for a new utterance. Preserves CIF cache."""
        state = self._sessions.get(session_key)
        if state is not None:
            state["processor"].reset_accumulated_text()

    def reset_streaming_state(self, session_key: str = "default") -> None:
        """Fully reset text, frame counters, and encoder/decoder CIF caches."""
        state = self._sessions.get(session_key)
        if state is not None:
            state["processor"].reset()
            state["english_processor"] = None

    def start_utterance(self, session_key: str = "default") -> None:
        """Mark start of a new utterance with an isolated streaming cache."""
        self.reset_streaming_state(session_key)

    def get_interim(self, session_key: str = "default") -> str:
        """Get current accumulated text without processing new audio."""
        state = self._sessions.get(session_key)
        if state is None:
            return ""
        return state["processor"].accumulated_text

    def get_interim_debug(self, session_key: str = "default") -> dict:
        """Return the most recent opt-in streaming decoder diagnostic."""
        state = self._sessions.get(session_key)
        if state is None:
            return {}
        return dict(getattr(state["processor"], "last_debug", {}) or {})

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
                "english_processor": None,
                "meeting_id": None,
                "seat_id": None,
                "next_segment_id": 1,
            }
        return self._sessions[session_key]


# ── Module-level helper ─────────────────────────────────────────────────────────

def _log_warning(msg: str) -> None:
    """Print a warning to stderr (no logging dependency in this module)."""
    import sys
    print(f"[WARN] SpeechModule: {msg}", file=sys.stderr, flush=True)
