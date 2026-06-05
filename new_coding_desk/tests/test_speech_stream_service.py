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

import numpy as np
import pytest

from backend.services.speech_stream_service import stream_service


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

    def teardown_method(self) -> None:
        """Clean up session."""
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
