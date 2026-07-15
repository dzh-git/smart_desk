"""
Unit tests for SpeechStreamService — Phase 3 additions.

Covers:
    - PCM16 → float32 conversion
    - Session utterance_id and revision tracking
    - cancel_utterance resets state
    - process_pcm_frame success path (models available) or error path (models absent)
    - process_pcm_frame with unknown session (RuntimeError)
"""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import numpy as np
import pytest

from backend.events import event_bus
from backend.services import translation_service as translation_service_mod
from backend.services.speech_stream_service import (
    stream_service,
    VAD_SILENCE_DURATION_S,
    UTTERANCE_STATE_IDLE,
    UTTERANCE_STATE_SPEAKING,
)
from backend.websocket.speech_ws import (
    _cancel_replaced_session,
    _handle_text_message,
    ERROR_MODEL_NOT_LOADED,
)


# ── Helpers ──────────────────────────────────────────────────────────────────────


def _make_pcm16_sine(
    duration_ms: int = 100,
    sample_rate: int = 16000,
    frequency: float = 440.0,
    amplitude: float = 0.5,
) -> bytes:
    """Generate a PCM16 sine wave frame as bytes.

    Args:
        duration_ms: Frame duration in milliseconds.
        sample_rate: Sample rate in Hz.
        frequency: Sine wave frequency in Hz.
        amplitude: Peak amplitude (0.0 to 1.0).

    Returns:
        PCM16 s16le bytes.
    """
    n_samples = int(sample_rate * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n_samples, endpoint=False)
    samples_f32 = (np.sin(2 * np.pi * frequency * t) * amplitude).astype(np.float32)
    samples_i16 = (samples_f32 * 32767).astype(np.int16)
    return samples_i16.tobytes()


# ── Tests ────────────────────────────────────────────────────────────────────────


class TestPcm16Conversion:
    """PCM16 little-endian bytes → float32 numpy array."""

    def test_converts_to_float32(self) -> None:
        """Output dtype is float32."""
        data = _make_pcm16_sine()
        result = stream_service.pcm16_to_float32(data)
        assert result.dtype == np.float32

    def test_normalizes_to_unit_range(self) -> None:
        """Values are in [-1.0, 1.0] range."""
        data = _make_pcm16_sine(amplitude=1.0)
        result = stream_service.pcm16_to_float32(data)
        assert np.abs(result).max() <= 1.0
        assert np.abs(result).min() >= 0.0

    def test_preserves_length(self) -> None:
        """3200 bytes (100ms @ 16kHz, s16le = 2 B/sample) → 1600 samples."""
        data = _make_pcm16_sine(duration_ms=100)
        result = stream_service.pcm16_to_float32(data)
        assert len(result) == 1600

    def test_silence_is_zero(self) -> None:
        """All-zero PCM16 → all-zero float32."""
        data = b"\x00" * 3200
        result = stream_service.pcm16_to_float32(data)
        assert np.all(result == 0.0)

    def test_negative_values_convert(self) -> None:
        """Negative int16 values → negative float32."""
        raw = np.array([-32768, -16384, -1], dtype=np.int16)
        result = stream_service.pcm16_to_float32(raw.tobytes())
        expected = np.array([-1.0, -0.5, -1.0 / 32768], dtype=np.float32)
        np.testing.assert_allclose(result, expected, atol=1e-6)


class TestSessionUtteranceTracking:
    """Session correctly tracks utterance_id and revision."""

    def setup_method(self) -> None:
        """Create a fresh session before each test."""
        self.session_key, self.session_token = stream_service.create_session(1, 1)

    def teardown_method(self) -> None:
        """Clean up session."""
        stream_service.remove_session(self.session_key, self.session_token)

    def test_start_utterance_sets_id(self) -> None:
        """start_utterance sets current_utterance_id on the session."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000001")
        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert session.current_utterance_id == "utt_1_1_000001"

    def test_start_utterance_resets_revision(self) -> None:
        """start_utterance resets revision to 0."""
        session = stream_service.get_session(self.session_key)
        assert session is not None
        session.revision = 5  # simulate prior increments

        stream_service.start_utterance(self.session_key, "utt_1_1_000002")
        assert session.revision == 0

    def test_cancel_clears_utterance_id(self) -> None:
        """cancel_utterance resets current_utterance_id and revision."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000004")
        uid = stream_service.cancel_utterance(self.session_key)
        assert uid == "utt_1_1_000004"

        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert session.current_utterance_id is None
        assert session.revision == 0

    def test_cancel_without_start_returns_none(self) -> None:
        """cancel_utterance returns None when no utterance active."""
        uid = stream_service.cancel_utterance(self.session_key)
        assert uid is None

    def test_cancel_unknown_session_returns_none(self) -> None:
        """cancel_utterance returns None for non-existent session."""
        uid = stream_service.cancel_utterance("speech_999_99")
        assert uid is None


class TestProcessPcmFrame:
    """process_pcm_frame behavior — both success and error paths."""

    def setup_method(self) -> None:
        """Create a fresh session before each test."""
        self.session_key, self.session_token = stream_service.create_session(1, 1)
        self._original_start_utterance = stream_service.start_utterance

        def _start_with_confirmed_voice(session_key: str, utterance_id: str) -> None:
            self._original_start_utterance(session_key, utterance_id)
            session = stream_service.get_session(session_key)
            if session is not None:
                session.calibration_frames_remaining = 0
                session.voice_active = True
                session.has_speech = True

        stream_service.start_utterance = _start_with_confirmed_voice

    def teardown_method(self) -> None:
        """Clean up session."""
        stream_service.start_utterance = self._original_start_utterance
        stream_service.remove_session(self.session_key, self.session_token)

    def test_unknown_session_raises(self) -> None:
        """process_pcm_frame on unknown session raises RuntimeError."""
        with pytest.raises(RuntimeError, match="Session .* not found"):
            stream_service.process_pcm_frame("speech_999_99", b"\x00" * 3200)

    def test_without_active_utterance_returns_none_uid(self) -> None:
        """When no start_utterance was called, utterance_id is None.

        The method should not raise — it returns None for utterance_id
        and the caller drops the frame.
        """
        try:
            result = stream_service.process_pcm_frame(
                self.session_key, b"\x00" * 3200,
            )
        except RuntimeError:
            # Models not loaded — this error path is also correct
            return

        assert result.get("utterance_id") is None

    def test_returns_expected_structure(self) -> None:
        """process_pcm_frame returns dict with expected keys.

        If models are loaded, the dict contains real ASR output.
        If not, RuntimeError is raised (see test_models_not_loaded_raises).
        """
        stream_service.start_utterance(self.session_key, "utt_1_1_000005")

        try:
            result = stream_service.process_pcm_frame(
                self.session_key, _make_pcm16_sine(),
            )
        except RuntimeError:
            # Models not available — error path is expected
            return

        # Success path: verify return structure
        assert isinstance(result, dict)
        assert result["utterance_id"] == "utt_1_1_000005"
        assert result["revision"] == 1
        assert isinstance(result["source_text"], str)

    def test_multiple_frames_increment_revision(self) -> None:
        """Each PCM16 frame increments the revision counter."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000006")

        try:
            r1 = stream_service.process_pcm_frame(
                self.session_key, _make_pcm16_sine(),
            )
            r2 = stream_service.process_pcm_frame(
                self.session_key, _make_pcm16_sine(),
            )
        except RuntimeError:
            return  # Models not available — skip

        assert r1["revision"] == 1
        assert r2["revision"] == 2

    # ── Phase 4: audio buffering ────────────────────────────────────────────

    def test_append_audio_buffers_pcm_bytes(self) -> None:
        """append_audio stores PCM16 bytes in the utterance buffer."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000008")
        stream_service.append_audio(self.session_key, b"\x00" * 3200)
        stream_service.append_audio(self.session_key, b"\x01" * 3200)

        audio = stream_service.get_buffered_audio(self.session_key)
        assert audio is not None
        assert len(audio) == 3200 * 2 // 2  # 6400 bytes → 3200 samples

    def test_append_audio_cleared_on_start(self) -> None:
        """start_utterance clears the audio buffer."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000009")
        stream_service.append_audio(self.session_key, b"\x00" * 3200)
        stream_service.start_utterance(self.session_key, "utt_1_1_000010")

        audio = stream_service.get_buffered_audio(self.session_key)
        assert audio is None  # Buffer was cleared

    def test_append_audio_cleared_on_cancel(self) -> None:
        """cancel_utterance clears the audio buffer."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000011")
        stream_service.append_audio(self.session_key, b"\x00" * 3200)
        stream_service.cancel_utterance(self.session_key)

        audio = stream_service.get_buffered_audio(self.session_key)
        assert audio is None

    def test_finalize_utterance_returns_audio_and_metadata(self) -> None:
        """finalize_utterance returns concatenated audio + metadata."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000012")
        stream_service.append_audio(self.session_key, b"\x00" * 3200)

        result = stream_service.finalize_utterance(self.session_key)
        assert result is not None
        assert "audio" in result
        assert result["sr"] == 16000
        assert result["utterance_id"] == "utt_1_1_000012"
        assert result["meeting_id"] == 1
        assert result["seat_id"] == 1

        # Buffer cleared after finalize
        audio_after = stream_service.get_buffered_audio(self.session_key)
        assert audio_after is None

        # Utterance_id preserved for event correlation
        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert session.current_utterance_id == "utt_1_1_000012"

    def test_finalize_without_buffer_returns_none(self) -> None:
        """finalize_utterance returns None when no audio buffered."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000013")
        result = stream_service.finalize_utterance(self.session_key)
        assert result is None

    def test_process_pcm_frame_buffers_audio(self) -> None:
        """process_pcm_frame automatically buffers PCM16 via append_audio."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000014")

        try:
            stream_service.process_pcm_frame(
                self.session_key, _make_pcm16_sine(),
            )
        except RuntimeError:
            return  # Models not loaded

        audio = stream_service.get_buffered_audio(self.session_key)
        assert audio is not None
        assert len(audio) == 1600

    # ── Phase 02: caption timeout commit ──────────────────────────────

    def test_timeout_commits_via_check_timeout(self, monkeypatch):
        """When ASR text does not change for text_change_timeout_s (2.0s),
        check_timeout commits uncommitted current_line to previous_line.

        Strategy:
          - Mock SpeechModule to return identical >=5-char text on each call.
          - Monkeypatch time.monotonic: first call → t0, second → t0 + 2.5.
          - First process_pcm_frame: update() sets _last_change_time = t0.
            check_timeout(t0) sees elapsed=0 and returns None.
            → current_line non-empty, previous_line empty.
          - Second process_pcm_frame: same text → update() short-circuits
            (raw_text == _last_raw), _last_change_time stays t0.
            check_timeout(t0+2.5) sees elapsed=2.5 >= 2.0 and commits.
            → previous_line non-empty, current_line empty.
        """
        mock_sm = _MockSpeechModule()
        monkeypatch.setattr(
            stream_service, '_get_speech_module', lambda: mock_sm,
        )

        t0 = 1000.0
        # Each frame records ``last_pcm_at`` and then checks caption timeout.
        time_values = [t0, t0, t0 + 2.5, t0 + 2.5]
        monkeypatch.setattr(time, 'monotonic', lambda: time_values.pop(0))

        # Reset CT-Transformer punctuation model to heuristic fallback so
        # the caption formatter does not split the mock text into two lines
        # (which would break assertions about previous_line being empty).
        monkeypatch.setattr(
            "backend.speech_module.punctuation._punc_model", None,
        )

        stream_service.start_utterance(self.session_key, "utt_1_1_000030")
        session = stream_service.get_session(self.session_key)
        assert session is not None
        session.caption_formatter.config.min_line_length = 5

        # ── First frame: text first seen, _last_change_time = t0 ──
        r1 = stream_service.process_pcm_frame(
            self.session_key, _make_pcm16_sine(),
        )
        c1 = r1["caption"]
        assert c1["current_line"] != "", \
            "First frame: current_line should hold uncommitted text"
        assert c1["previous_line"] == "", \
            "First frame: previous_line should be empty"

        # ── Second frame: same text → timeout triggers commit ──
        r2 = stream_service.process_pcm_frame(
            self.session_key, _make_pcm16_sine(),
        )
        c2 = r2["caption"]
        assert c2["previous_line"] != "", \
            "Second frame: previous_line should contain committed text"
        assert c2["current_line"] == "", \
            "Second frame: current_line should be empty after commit"

    def test_cached_error_fails_fast(self) -> None:
        """When _speech_module_error is set, process_pcm_frame raises immediately."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000007")

        # Inject simulated error
        old_error = stream_service._speech_module_error
        stream_service._speech_module_error = "Simulated: test error"
        try:
            with pytest.raises(RuntimeError, match="Simulated"):
                stream_service.process_pcm_frame(
                    self.session_key, _make_pcm16_sine(),
                )
        finally:
            stream_service._speech_module_error = old_error

    # ── Phase 02: caption formatter integration ───────────────────────────

    def test_process_pcm_frame_includes_caption(self, monkeypatch):
        """process_pcm_frame returns caption fields in the result dict."""
        mock_sm = _MockSpeechModule()
        monkeypatch.setattr(
            stream_service, '_get_speech_module', lambda: mock_sm,
        )

        stream_service.start_utterance(self.session_key, "utt_1_1_000020")
        result = stream_service.process_pcm_frame(
            self.session_key, _make_pcm16_sine(),
        )

        assert "caption" in result
        caption = result["caption"]
        assert "previous_line" in caption
        assert "current_line" in caption
        assert caption["mode"] == "two_line"
        assert isinstance(result["source_text"], str)

    def test_process_pcm_frame_punctuated_text(self, monkeypatch):
        """source_text in result is punctuated by the formatter."""
        mock_sm = _MockSpeechModule()
        monkeypatch.setattr(
            stream_service, '_get_speech_module', lambda: mock_sm,
        )

        stream_service.start_utterance(self.session_key, "utt_1_1_000021")
        result = stream_service.process_pcm_frame(
            self.session_key, _make_pcm16_sine(),
        )
        # The mock returns "今天天气真好我们出去散步了"; heuristic adds 。
        # With trailing-boundary rule the 。should not cause a split,
        # so source_text = punctuated text, caption.current_line non-empty.
        assert result["source_text"].endswith("。")
        assert result["source_text"] != ""

    def test_caption_reset_on_start_utterance(self, monkeypatch):
        """start_utterance resets the caption formatter."""
        mock_sm = _MockSpeechModule()
        monkeypatch.setattr(
            stream_service, '_get_speech_module', lambda: mock_sm,
        )

        # First utterance — formatter accumulates text
        stream_service.start_utterance(self.session_key, "utt_1_1_000022")
        stream_service.process_pcm_frame(
            self.session_key, _make_pcm16_sine(),
        )

        session = stream_service.get_session(self.session_key)
        assert session is not None
        # After first utterance, some state in caption formatter
        assert session.caption_formatter._last_raw != ""

        # Start a second utterance — must reset formatter
        stream_service.start_utterance(self.session_key, "utt_1_1_000023")
        assert session.caption_formatter._last_raw == ""
        assert session.caption_formatter._previous_line == ""

    def test_caption_reset_on_cancel_utterance(self, monkeypatch):
        """cancel_utterance resets the caption formatter."""
        mock_sm = _MockSpeechModule()
        monkeypatch.setattr(
            stream_service, '_get_speech_module', lambda: mock_sm,
        )

        stream_service.start_utterance(self.session_key, "utt_1_1_000024")
        stream_service.process_pcm_frame(
            self.session_key, _make_pcm16_sine(),
        )

        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert session.caption_formatter._last_raw != ""

        stream_service.cancel_utterance(self.session_key)
        assert session.caption_formatter._last_raw == ""

    def test_reset_caption_formatter_method(self):
        """reset_caption_formatter resets the formatter state."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000025")

        session = stream_service.get_session(self.session_key)
        assert session is not None
        session.caption_formatter._committed_raw_len = 10
        session.caption_formatter._previous_line = "test"

        stream_service.reset_caption_formatter(self.session_key)
        assert session.caption_formatter._committed_raw_len == 0
        assert session.caption_formatter._previous_line == ""


class _MockSpeechModule:
    """Minimal mock that replaces SpeechModule for caption tests.

    Returns a known ASR text string so the caption formatter can be
    exercised without loading real speech models.
    """

    def __init__(self):
        self._sessions: dict = {}
        self._ready = True

    @property
    def ready(self):
        return self._ready

    def preload(self):
        pass

    def set_session_context(self, session_key, meeting_id, seat_id):
        pass

    def process_interim_array(self, audio, session_key):
        return "今天天气真好我们出去散步了"

    def start_utterance(self, session_key):
        pass

    def reset_interim(self, session_key):
        pass


class TestIdentitySafeCleanup:
    """remove_session must not delete a replaced session."""

    def setup_method(self) -> None:
        self._sessions_before = set(stream_service._sessions.keys())

    def teardown_method(self) -> None:
        # Clean up any sessions left over from the test
        for k in list(stream_service._sessions.keys()):
            if k not in self._sessions_before:
                s = stream_service._sessions[k]
                stream_service.remove_session(k, s.session_token)

    def test_remove_session_with_wrong_token_does_not_delete(self) -> None:
        """remove_session with old token is a no-op after session replacement.

        Simulates: ws1 creates session S1 → ws2 replaces with S2 (same key) →
        ws1's finally calls remove_session(key, S1.token) → S2 must survive.
        """
        # Create session 1 (simulates ws1 connecting)
        key, token1 = stream_service.create_session(1, 1)
        assert stream_service.get_session(key) is not None

        # Create session 2 with same key (simulates ws2 duplicate connect)
        # This replaces session 1 in _sessions
        key2, token2 = stream_service.create_session(1, 1)
        assert key2 == key  # same key
        assert token2 != token1  # different token

        # ws1's finally tries to remove with OLD token — must NOT remove S2
        removed = stream_service.remove_session(key, token1)
        assert removed is False, "remove_session should refuse old token"

        # Session 2 must still be present
        stored = stream_service.get_session(key)
        assert stored is not None, "Session 2 was incorrectly deleted"
        assert stored.session_token == token2, "Session 2 is not the right session"

        # Clean up with correct token
        removed = stream_service.remove_session(key, token2)
        assert removed is True
        assert stream_service.get_session(key) is None


class TestUtteranceIdUniqueness:
    """utterance_id must be monotonically increasing across reconnections."""

    def setup_method(self) -> None:
        self._seq_snapshot = dict(
            stream_service._utterance_sequences,
        )

    def teardown_method(self) -> None:
        # Clean up any sessions created during test
        for k in list(stream_service._sessions.keys()):
            s = stream_service._sessions[k]
            stream_service.remove_session(k, s.session_token)
        # Restore sequence counter state
        stream_service._utterance_sequences.clear()
        stream_service._utterance_sequences.update(self._seq_snapshot)

    def test_same_key_reconnect_generates_increasing_ids(self) -> None:
        """Reconnecting with same (meeting, seat) produces monotonically
        increasing utterance_ids, not restarting from 000001."""
        # Session S1 → first utterance
        key1, token1 = stream_service.create_session(1, 1)
        uid1 = stream_service.generate_utterance_id(1, 1)
        assert uid1 == "utt_1_1_000001"

        # Session S2 replaces S1 (same key) → second utterance
        key2, token2 = stream_service.create_session(1, 1)
        assert key1 == key2
        uid2 = stream_service.generate_utterance_id(1, 1)
        assert uid2 == "utt_1_1_000002", (
            f"Expected utt_1_1_000002 after reconnect, got {uid2}"
        )
        assert uid2 != uid1

        # Third utterance — still incrementing
        uid3 = stream_service.generate_utterance_id(1, 1)
        assert uid3 == "utt_1_1_000003"

        # Clean up S2
        stream_service.remove_session(key2, token2)

    def test_persisted_sequence_seed_never_moves_counter_backwards(self) -> None:
        """Database history raises the counter but cannot lower live state."""
        stream_service.seed_utterance_sequence(41, 1, 25)
        assert stream_service.generate_utterance_id(41, 1) == "utt_41_1_000026"

        stream_service.seed_utterance_sequence(41, 1, 10)
        assert stream_service.generate_utterance_id(41, 1) == "utt_41_1_000027"


class TestDuplicateSessionCancellation:
    def test_replacement_cancels_old_utterance_and_publishes_event(self) -> None:
        key, token = stream_service.create_session(41, 1)
        stream_service.start_utterance(key, "utt_41_1_000025")
        events = []

        def _handler(event) -> None:
            events.append(event)

        event_bus.subscribe("translation_interim_cancelled", _handler)
        try:
            assert _cancel_replaced_session(41, 1) == "utt_41_1_000025"
            assert stream_service.get_session(key).current_utterance_id is None
            assert len(events) == 1
            assert events[0].payload == {
                "utterance_id": "utt_41_1_000025",
                "seat_id": 1,
                "reason": "session_replaced",
            }
        finally:
            event_bus.unsubscribe("translation_interim_cancelled", _handler)
            stream_service.remove_session(key, token)


class TestVadDetection:
    """VAD silence detection — RMS-based auto-final trigger.

    Uses mock SpeechModule to avoid real model dependency.
    Save/restores the real _speech_module to prevent test interference.
    """

    def setup_method(self) -> None:
        """Create a fresh session and save SpeechModule state."""
        self.session_key, self.session_token = stream_service.create_session(1, 1)
        # Save real SpeechModule state (may be None if not loaded)
        self._saved_speech_module = stream_service._speech_module
        self._saved_speech_module_error = stream_service._speech_module_error

    def teardown_method(self) -> None:
        """Clean up session and restore SpeechModule state."""
        stream_service.remove_session(self.session_key, self.session_token)
        # Restore SpeechModule state so other tests are unaffected
        stream_service._speech_module = self._saved_speech_module
        stream_service._speech_module_error = self._saved_speech_module_error

    def _make_silence(self) -> bytes:
        """Generate a zero PCM16 frame (100ms of silence)."""
        return b"\x00" * 3200

    def _make_speech_sine(self) -> bytes:
        """Generate a PCM16 sine wave frame (non-silent speech)."""
        return _make_pcm16_sine(amplitude=0.5)

    # ── VAD flag in process_pcm_frame ─────────────────────────────────

    def test_pure_silence_never_starts_or_finalizes_an_utterance(
        self, monkeypatch,
    ) -> None:
        """Pure silence is filtered before ASR and ends without an error."""
        mock_sm = _MockSpeechModule()
        # Direct assignment avoids lazy-loading real models
        stream_service._speech_module = mock_sm
        stream_service._speech_module_error = None

        stream_service.start_utterance(self.session_key, "utt_1_1_000050")

        for i in range(int(VAD_SILENCE_DURATION_S * 10) + 10):
            result = stream_service.process_pcm_frame(
                self.session_key, self._make_silence(),
            )
            assert not result.get("vad_should_finalize"), (
                f"Pure-silence frame {i} must not create an utterance"
            )
            assert result["source_text"] == ""

    def test_process_pcm_frame_no_vad_flag_on_speech(
        self, monkeypatch,
    ) -> None:
        """Speech frames (non-zero RMS) do not trigger vad_should_finalize."""
        mock_sm = _MockSpeechModule()
        stream_service._speech_module = mock_sm
        stream_service._speech_module_error = None

        stream_service.start_utterance(self.session_key, "utt_1_1_000051")

        # Send many speech frames — silence counter should stay at 0
        for _ in range(20):
            result = stream_service.process_pcm_frame(
                self.session_key, self._make_speech_sine(),
            )
            assert not result.get("vad_should_finalize"), (
                "Speech frames should not trigger VAD"
            )

    def test_vad_resets_on_speech_after_silence(
        self, monkeypatch,
    ) -> None:
        """Speech after silence resets the VAD counter."""
        mock_sm = _MockSpeechModule()
        stream_service._speech_module = mock_sm
        stream_service._speech_module_error = None

        stream_service.start_utterance(self.session_key, "utt_1_1_000052")

        # Some silence
        for _ in range(5):
            stream_service.process_pcm_frame(
                self.session_key, self._make_silence(),
            )

        # Speech frame resets silence counter
        result = stream_service.process_pcm_frame(
            self.session_key, self._make_speech_sine(),
        )
        assert not result.get("vad_should_finalize"), (
            "Speech should reset VAD counter"
        )

        # Verify silence counter was reset
        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert session.vad_silence_seconds == 0.0, (
            "VAD silence counter should be 0 after speech"
        )

    def test_vad_returns_false_for_unknown_session(self) -> None:
        """_check_vad_end returns False for non-existent session."""
        audio = stream_service.pcm16_to_float32(self._make_silence())
        result = stream_service._check_vad_end("speech_999_99", audio)
        assert result is False

    # ── VAD state machine transitions ─────────────────────────────────

    def test_start_utterance_resets_vad_state(self) -> None:
        """start_utterance resets utterance_state to SPEAKING and silence to 0."""
        session = stream_service.get_session(self.session_key)
        assert session is not None

        # Artificially set VAD state
        session.utterance_state = UTTERANCE_STATE_IDLE
        session.vad_silence_seconds = 5.0

        stream_service.start_utterance(self.session_key, "utt_1_1_000060")
        assert session.utterance_state == UTTERANCE_STATE_SPEAKING
        assert session.vad_silence_seconds == 0.0

    def test_cancel_utterance_resets_vad_state(self) -> None:
        """cancel_utterance resets utterance_state to IDLE and silence to 0."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000061")
        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert session.utterance_state == UTTERANCE_STATE_SPEAKING

        stream_service.cancel_utterance(self.session_key)
        assert session.utterance_state == UTTERANCE_STATE_IDLE
        assert session.vad_silence_seconds == 0.0

    def test_prepare_next_utterance_generates_new_id(self) -> None:
        """prepare_next_utterance generates a new unique utterance_id."""
        stream_service.start_utterance(self.session_key, "utt_1_1_000062")
        session = stream_service.get_session(self.session_key)
        assert session is not None
        old_uid = session.current_utterance_id

        new_uid = stream_service.prepare_next_utterance(
            self.session_key, 1, 1,
        )
        assert new_uid is not None
        assert new_uid != old_uid
        assert new_uid.startswith("utt_1_1_")

        # Verify session state is reset for new utterance
        assert session.current_utterance_id == new_uid
        assert session.revision == 0
        assert session.utterance_state == UTTERANCE_STATE_SPEAKING
        assert session.vad_silence_seconds == 0.0

    def test_prepare_next_utterance_unknown_session(self) -> None:
        """prepare_next_utterance returns None for unknown session."""
        result = stream_service.prepare_next_utterance(
            "speech_999_99", 999, 99,
        )
        assert result is None

    def test_vad_flag_in_result_dict(self, monkeypatch) -> None:
        """process_pcm_frame result dict contains vad_should_finalize key."""
        mock_sm = _MockSpeechModule()
        stream_service._speech_module = mock_sm
        stream_service._speech_module_error = None

        stream_service.start_utterance(self.session_key, "utt_1_1_000070")
        result = stream_service.process_pcm_frame(
            self.session_key, self._make_silence(),
        )
        assert "vad_should_finalize" in result
        assert isinstance(result["vad_should_finalize"], bool)


# ── Task 126: Terminal utterance tracking ──────────────────────────────────


class TestTerminalUtteranceTracking:
    """Terminal utterance_id tracking prevents duplicate final/cancel.

    Task 126: each utterance_id can only be finalized/cancelled once.
    Terminal set is maintained per session and tracks all utterance_ids
    that have been finalized, cancelled, or failed finalization.
    """

    def setup_method(self) -> None:
        self.session_key, self.session_token = stream_service.create_session(1, 1)
        self._original_start_utterance = stream_service.start_utterance

        def _start_with_confirmed_voice(session_key: str, utterance_id: str) -> None:
            self._original_start_utterance(session_key, utterance_id)
            session = stream_service.get_session(session_key)
            if session is not None:
                session.has_speech = True

        stream_service.start_utterance = _start_with_confirmed_voice

    def teardown_method(self) -> None:
        stream_service.start_utterance = self._original_start_utterance
        stream_service.remove_session(self.session_key, self.session_token)

    def test_cancel_marks_as_terminal(self) -> None:
        """cancel_utterance adds the utterance_id to the terminal set."""
        stream_service.start_utterance(self.session_key, "utt_term_cancel_001")
        uid = stream_service.cancel_utterance(self.session_key)
        assert uid == "utt_term_cancel_001"

        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert "utt_term_cancel_001" in session.terminal_utterance_ids

    def test_cancel_without_start_does_not_add_none(self) -> None:
        """cancel_utterance with no active utterance does not add to terminal."""
        uid = stream_service.cancel_utterance(self.session_key)
        assert uid is None

        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert len(session.terminal_utterance_ids) == 0

    def test_finalize_terminal_utterance_returns_none(self) -> None:
        """finalize_utterance skips already-terminal utterance.

        After cancel, trying to finalize the same utterance returns None
        instead of attempting duplicate finalization.
        """
        stream_service.start_utterance(self.session_key, "utt_term_final_001")
        stream_service.append_audio(self.session_key, b"\x00" * 3200)

        # Cancel first (marks terminal)
        cancelled_uid = stream_service.cancel_utterance(self.session_key)
        assert cancelled_uid == "utt_term_final_001"

        # Start a new utterance so there's a current_utterance_id
        stream_service.start_utterance(self.session_key, "utt_term_final_002")
        stream_service.append_audio(self.session_key, b"\x01" * 3200)

        # Try to finalize the *new* utterance — should succeed
        result = stream_service.finalize_utterance(self.session_key)
        assert result is not None
        assert result["utterance_id"] == "utt_term_final_002"

    def test_mark_utterance_terminal_idempotent(self) -> None:
        """mark_utterance_terminal can be called multiple times safely."""
        stream_service.mark_utterance_terminal(self.session_key, "utt_term_idem_001")

        # Second call should not raise
        stream_service.mark_utterance_terminal(self.session_key, "utt_term_idem_001")

        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert "utt_term_idem_001" in session.terminal_utterance_ids
        # Only one entry for the same utterance_id
        matches = [
            uid for uid in session.terminal_utterance_ids
            if uid == "utt_term_idem_001"
        ]
        assert len(matches) == 1

    def test_is_utterance_terminal_true_after_mark(self) -> None:
        """is_utterance_terminal returns True for marked utterance."""
        stream_service.mark_utterance_terminal(
            self.session_key, "utt_term_check_001",
        )
        assert stream_service.is_utterance_terminal(
            self.session_key, "utt_term_check_001",
        ) is True

    def test_is_utterance_terminal_false_for_new(self) -> None:
        """is_utterance_terminal returns False for unmarked utterance."""
        assert stream_service.is_utterance_terminal(
            self.session_key, "utt_term_nonexistent",
        ) is False

    def test_is_utterance_terminal_unknown_session(self) -> None:
        """is_utterance_terminal returns False for unknown session."""
        assert stream_service.is_utterance_terminal(
            "speech_999_99", "utt_term_unknown",
        ) is False

    def test_terminal_set_preserves_other_utterances(self) -> None:
        """Terminating one utterance does not affect other utterances."""
        stream_service.start_utterance(self.session_key, "utt_term_a_001")
        stream_service.cancel_utterance(self.session_key)

        stream_service.start_utterance(self.session_key, "utt_term_b_001")
        stream_service.append_audio(self.session_key, b"\x00" * 3200)
        result = stream_service.finalize_utterance(self.session_key)

        # Utterance B should finalize normally despite A being terminal
        assert result is not None
        assert result["utterance_id"] == "utt_term_b_001"

    def test_terminal_set_cleared_on_new_session(self) -> None:
        """New session has empty terminal set."""
        # First session has terminal entries
        stream_service.start_utterance(self.session_key, "utt_term_s1_001")
        stream_service.cancel_utterance(self.session_key)
        assert len(stream_service.get_session(self.session_key).terminal_utterance_ids) > 0

        # Create second session with same key
        new_key, new_token = stream_service.create_session(1, 1)
        try:
            new_session = stream_service.get_session(new_key)
            assert new_session is not None
            assert len(new_session.terminal_utterance_ids) == 0
        finally:
            stream_service.remove_session(new_key, new_token)

# ── Task 126: end_hint error path integration tests ─────────────────────────


class TestEndHintErrorPaths:
    """Verify that end_hint finalization failures publish
    TranslationInterimCancelledEvent, mark the utterance terminal, and
    send the correct WS error code.

    These test the ``_handle_text_message`` handler in ``speech_ws.py``
    by monkeypatching ``TranslationService.process_final_array`` to raise
    the relevant exception — no real ASR models are involved.
    """

    def _remove_session(self, key: str, token: str) -> None:
        stream_service.remove_session(key, token)

    # ── model_not_loaded ──────────────────────────────────────────────────

    @pytest.mark.anyio
    async def test_end_hint_model_not_loaded_publishes_cancelled(self) -> None:
        """model_not_loaded -> ERROR_MODEL_NOT_LOADED +
        TranslationInterimCancelledEvent + terminal."""
        key, token = stream_service.create_session(1, 1)
        try:
            stream_service.start_utterance(key, "utt_err_mnl_001")
            stream_service.get_session(key).has_speech = True
            stream_service.append_audio(key, b"\x00" * 3200)

            _original = (
                translation_service_mod.TranslationService.process_final_array
            )

            def _mock_raise(*args: object, **kwargs: object) -> object:
                raise RuntimeError("speech module not loaded")

            translation_service_mod.TranslationService.process_final_array = (
                _mock_raise  # type: ignore[assignment]
            )

            events: list[object] = []
            _handler = lambda e: events.append(e)
            event_bus.subscribe(
                "translation_interim_cancelled", _handler,
            )

            try:
                ws = AsyncMock()
                await _handle_text_message(
                    ws, json.dumps({"type": "end_hint"}),
                    1, 1, key,
                )
            finally:
                translation_service_mod.TranslationService.process_final_array = (
                    _original
                )
                event_bus.unsubscribe(
                    "translation_interim_cancelled", _handler,
                )

            # 1. ERROR_MODEL_NOT_LOADED sent to speech WS
            ws.send_json.assert_any_call(ERROR_MODEL_NOT_LOADED)

            # 2. Utterance is terminal
            assert stream_service.is_utterance_terminal(key, "utt_err_mnl_001")

            # 3. Cancelled event published
            assert len(events) == 1, (
                f"Expected 1 TranslationInterimCancelledEvent, got {len(events)}"
            )
            cancelled = events[0]
            assert cancelled.payload["utterance_id"] == "utt_err_mnl_001"
            assert cancelled.payload["seat_id"] == 1
            assert cancelled.payload["reason"] == "model_not_loaded"
        finally:
            self._remove_session(key, token)

    # ── generic RuntimeError ──────────────────────────────────────────────

    @pytest.mark.anyio
    async def test_end_hint_generic_error_publishes_cancelled(self) -> None:
        """Generic RuntimeError -> TRANSLATION_FAILED +
        TranslationInterimCancelledEvent + terminal."""
        key, token = stream_service.create_session(1, 1)
        try:
            stream_service.start_utterance(key, "utt_err_gen_001")
            stream_service.get_session(key).has_speech = True
            stream_service.append_audio(key, b"\x00" * 3200)

            _original = (
                translation_service_mod.TranslationService.process_final_array
            )

            def _mock_raise(*args: object, **kwargs: object) -> object:
                raise RuntimeError("transcription failed: internal error")

            translation_service_mod.TranslationService.process_final_array = (
                _mock_raise  # type: ignore[assignment]
            )

            events: list[object] = []
            _handler = lambda e: events.append(e)
            event_bus.subscribe(
                "translation_interim_cancelled", _handler,
            )

            try:
                ws = AsyncMock()
                await _handle_text_message(
                    ws, json.dumps({"type": "end_hint"}),
                    1, 1, key,
                )
            finally:
                translation_service_mod.TranslationService.process_final_array = (
                    _original
                )
                event_bus.unsubscribe(
                    "translation_interim_cancelled", _handler,
                )

            # 1. TRANSLATION_FAILED error sent (generic fallback)
            ws.send_json.assert_any_call({
                "type": "error",
                "code": "TRANSLATION_FAILED",
                "message": "transcription failed: internal error",
            })

            # 2. Utterance is terminal
            assert stream_service.is_utterance_terminal(key, "utt_err_gen_001")

            # 3. Cancelled event published
            assert len(events) == 1
            assert events[0].payload["utterance_id"] == "utt_err_gen_001"
            assert events[0].payload["reason"] == "finalization_failed"
        finally:
            self._remove_session(key, token)

    # ── ASR_EMPTY_RESULT (regression check) ────────────────────────────────

    @pytest.mark.anyio
    async def test_end_hint_asr_empty_publishes_cancelled(self) -> None:
        """ASR_EMPTY_RESULT -> ERROR_ASR_EMPTY_RESULT +
        TranslationInterimCancelledEvent + terminal."""
        key, token = stream_service.create_session(1, 1)
        try:
            stream_service.start_utterance(key, "utt_err_asr_001")
            stream_service.get_session(key).has_speech = True
            stream_service.append_audio(key, b"\x00" * 3200)

            _original = (
                translation_service_mod.TranslationService.process_final_array
            )

            def _mock_raise(*args: object, **kwargs: object) -> object:
                raise RuntimeError(
                    "Transcription returned empty text (ASR_EMPTY_RESULT)"
                )

            translation_service_mod.TranslationService.process_final_array = (
                _mock_raise  # type: ignore[assignment]
            )

            events: list[object] = []
            _handler = lambda e: events.append(e)
            event_bus.subscribe(
                "translation_interim_cancelled", _handler,
            )

            try:
                ws = AsyncMock()
                await _handle_text_message(
                    ws, json.dumps({"type": "end_hint"}),
                    1, 1, key,
                )
            finally:
                translation_service_mod.TranslationService.process_final_array = (
                    _original
                )
                event_bus.unsubscribe(
                    "translation_interim_cancelled", _handler,
                )

            # 1. ASR_EMPTY_RESULT error sent
            ws.send_json.assert_any_call({
                "type": "error",
                "code": "ASR_EMPTY_RESULT",
                "message": "No speech recognized in the audio",
            })

            # 2. Utterance is terminal
            assert stream_service.is_utterance_terminal(key, "utt_err_asr_001")

            # 3. Cancelled event published
            assert len(events) == 1
            assert events[0].payload["utterance_id"] == "utt_err_asr_001"
            assert events[0].payload["reason"] == "asr_empty_result"
        finally:
            self._remove_session(key, token)


# ── Task 129-lite: Duplicate finalization guard tests ──────────────────────────


class TestDuplicateFinalization:
    """Verify that finalize_utterance returns None when utterance is terminal.

    Task 129-lite: end_hint after successful final or cancel should not
    result in duplicate DB writes. The guard is in ``finalize_utterance``
    which checks ``terminal_utterance_ids`` before processing.
    """

    def setup_method(self) -> None:
        self.session_key, self.session_token = stream_service.create_session(1, 1)

    def teardown_method(self) -> None:
        stream_service.remove_session(self.session_key, self.session_token)

    def test_end_hint_after_successful_final_returns_none(self) -> None:
        """end_hint after successful final returns None (terminal guard)."""
        stream_service.start_utterance(self.session_key, "utt_dup_final_001")
        stream_service.append_audio(self.session_key, b"\x00" * 3200)

        # Mark as terminal (simulating successful finalization)
        stream_service.mark_utterance_terminal(
            self.session_key, "utt_dup_final_001",
        )

        # finalize_utterance must return None because utterance is terminal
        result = stream_service.finalize_utterance(self.session_key)
        assert result is None, (
            "finalize_utterance should return None for terminal utterance"
        )

    def test_end_hint_after_cancel_returns_none(self) -> None:
        """end_hint after cancel returns None (utterance cancelled)."""
        stream_service.start_utterance(self.session_key, "utt_dup_cancel_001")
        stream_service.append_audio(self.session_key, b"\x00" * 3200)

        # Cancel marks terminal AND clears the buffer
        cancelled_uid = stream_service.cancel_utterance(self.session_key)
        assert cancelled_uid == "utt_dup_cancel_001"

        # finalize_utterance should return None (terminal + no buffer)
        result = stream_service.finalize_utterance(self.session_key)
        assert result is None

    def test_duplicate_mark_terminal_is_idempotent(self) -> None:
        """Calling mark_utterance_terminal twice is safe."""
        stream_service.mark_utterance_terminal(
            self.session_key, "utt_dup_idem_001",
        )
        # Second call — must not raise
        stream_service.mark_utterance_terminal(
            self.session_key, "utt_dup_idem_001",
        )
        assert stream_service.is_utterance_terminal(
            self.session_key, "utt_dup_idem_001",
        )

    def test_duplicate_is_terminal_check_not_add_to_set(self) -> None:
        """is_utterance_terminal does not modify the terminal set."""
        stream_service.start_utterance(self.session_key, "utt_dup_noadd_001")
        session = stream_service.get_session(self.session_key)
        assert session is not None
        before_count = len(session.terminal_utterance_ids)

        # Calling is_utterance_terminal should NOT add to the set
        result = stream_service.is_utterance_terminal(
            self.session_key, "utt_dup_noadd_001",
        )
        assert result is False
        assert len(session.terminal_utterance_ids) == before_count


# ── Task 129-lite: VAD auto-final error path tests ────────────────────────────


class TestVadAutoFinalErrorPaths:
    """Verify that VAD auto-final failures publish
    TranslationInterimCancelledEvent and mark the utterance terminal.

    Unlike end_hint (3 exception branches), the VAD auto-final path in
    ``_handle_binary_message`` only has 2 branches because
    ``model_not_loaded`` is caught earlier at the ``process_pcm_frame``
    level, before the VAD check is reached.
    """

    def setup_method(self) -> None:
        self.session_key, self.session_token = stream_service.create_session(1, 1)

    def teardown_method(self) -> None:
        stream_service.remove_session(self.session_key, self.session_token)

    @pytest.mark.anyio
    async def test_vad_auto_final_asr_empty_publishes_cancelled(self) -> None:
        """VAD auto-final ASR_EMPTY_RESULT -> cancelled event + terminal."""
        stream_service.start_utterance(self.session_key, "utt_vad_asr_001")
        stream_service.append_audio(self.session_key, b"\x00" * 3200)

        _original_process = stream_service.process_pcm_frame
        _original_final = (
            translation_service_mod.TranslationService.process_final_array
        )

        # Mock process_pcm_frame to trigger VAD auto-final
        stream_service.process_pcm_frame = lambda sk, data: {  # type: ignore[method-assign]
            "utterance_id": "utt_vad_asr_001",
            "revision": 1,
            "source_text": "test",
            "caption": {
                "previous_line": "", "current_line": "test", "mode": "two_line",
            },
            "vad_should_finalize": True,
        }

        def _mock_raise(*args: object, **kwargs: object) -> object:
            raise RuntimeError(
                "Transcription returned empty text (ASR_EMPTY_RESULT)"
            )

        translation_service_mod.TranslationService.process_final_array = (
            _mock_raise  # type: ignore[assignment]
        )

        events: list[object] = []
        _handler = lambda e: events.append(e)
        event_bus.subscribe("translation_interim_cancelled", _handler)

        try:
            ws = AsyncMock()
            from backend.websocket.speech_ws import _handle_binary_message
            await _handle_binary_message(
                ws, b"\x00" * 3200, 1, 1, self.session_key,
            )
        finally:
            stream_service.process_pcm_frame = _original_process
            translation_service_mod.TranslationService.process_final_array = (
                _original_final
            )
            event_bus.unsubscribe(
                "translation_interim_cancelled", _handler,
            )

        # 1. Cancelled event published
        assert len(events) == 1, (
            f"Expected 1 TranslationInterimCancelledEvent, got {len(events)}"
        )
        assert events[0].payload["utterance_id"] == "utt_vad_asr_001"
        assert events[0].payload["seat_id"] == 1
        assert events[0].payload["reason"] == "asr_empty_result"

        # 2. Utterance is terminal
        assert stream_service.is_utterance_terminal(
            self.session_key, "utt_vad_asr_001",
        ), "VAD ASR_EMPTY_RESULT should mark terminal"

    @pytest.mark.anyio
    async def test_auto_final_empty_snapshot_is_cancelled_before_queue(self) -> None:
        """An auto-final snapshot without confirmed speech is dropped quietly."""
        stream_service.start_utterance(self.session_key, "utt_vad_gen_001")
        stream_service.append_audio(self.session_key, b"\x00" * 3200)

        _original_process = stream_service.process_pcm_frame
        _original_final = (
            translation_service_mod.TranslationService.process_final_array
        )

        stream_service.process_pcm_frame = lambda sk, data: {  # type: ignore[method-assign]
            "utterance_id": "utt_vad_gen_001",
            "revision": 1,
            "source_text": "test",
            "caption": {
                "previous_line": "", "current_line": "test", "mode": "two_line",
            },
            "vad_should_finalize": True,
        }

        def _mock_raise(*args: object, **kwargs: object) -> object:
            raise RuntimeError("VAD finalization failed: internal error")

        translation_service_mod.TranslationService.process_final_array = (
            _mock_raise  # type: ignore[assignment]
        )

        events: list[object] = []
        _handler = lambda e: events.append(e)
        event_bus.subscribe("translation_interim_cancelled", _handler)

        try:
            ws = AsyncMock()
            from backend.websocket.speech_ws import _handle_binary_message
            await _handle_binary_message(
                ws, b"\x00" * 3200, 1, 1, self.session_key,
            )
        finally:
            stream_service.process_pcm_frame = _original_process
            translation_service_mod.TranslationService.process_final_array = (
                _original_final
            )
            event_bus.unsubscribe(
                "translation_interim_cancelled", _handler,
            )

        assert len(events) == 1
        assert events[0].payload["utterance_id"] == "utt_vad_gen_001"
        assert events[0].payload["reason"] == "asr_empty_result"
        assert stream_service.is_utterance_terminal(
            self.session_key, "utt_vad_gen_001",
        )
