import os
import numpy as np
import tempfile
import soundfile as sf
from unittest.mock import patch


def test_load_audio_resamples_to_16k():
    from speech_module.audio_utils import load_audio_resampled
    # Create a 1-second 44.1kHz dummy WAV
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name
        dummy = np.random.randn(44100).astype(np.float32)
        sf.write(f.name, dummy, 44100)
    try:
        audio, sr = load_audio_resampled(tmp_path, target_sr=16000)
        assert sr == 16000
        assert 15000 < len(audio) < 17000  # ~1 sec at 16kHz
    finally:
        os.unlink(tmp_path)


def test_load_audio_resampled_uses_centralized_resample(capfd):
    """CR-013: load_audio_resampled must delegate to centralized resample_if_needed,
    not inline scipy.signal.resample directly."""
    from unittest.mock import patch
    import soundfile as sf
    import tempfile
    import os

    # Create a 48kHz dummy WAV (different from target 16kHz)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name
        dummy = np.random.randn(48000).astype(np.float32)
        sf.write(f.name, dummy, 48000)

    try:
        with patch("speech_module.audio_utils.resample_if_needed",
                   wraps=lambda samples, orig_sr, target_sr=16000: samples[:int(len(samples) * target_sr / orig_sr)]) as mock_resample:
            from speech_module.audio_utils import load_audio_resampled
            audio, sr = load_audio_resampled(tmp_path, target_sr=16000)
            # CR-013: Must delegate to centralized resample_if_needed
            assert mock_resample.called, (
                "load_audio_resampled must use centralized resample_if_needed, "
                "not inline scipy.signal.resample"
            )
            assert sr == 16000
    finally:
        os.unlink(tmp_path)


def test_transcribe_array_uses_centralized_resample():
    """CR-013: transcribe_array must delegate to centralized resample_if_needed
    for sample rate conversion, not inline scipy.signal.resample."""
    from unittest.mock import patch, MagicMock
    import numpy as np

    # We need to test that transcribe_array calls resample_if_needed when sr != 16000.
    # We patch the offline_rescore to avoid triggering actual STT models.
    with patch("speech_module.speech_module.resample_if_needed",
               wraps=lambda samples, orig_sr, target_sr=16000: samples[:int(len(samples) * target_sr / orig_sr)]) as mock_resample, \
         patch("speech_module.stt_streaming.offline_rescore", return_value="test text"):
        from speech_module.speech_module import SpeechModule
        sm = SpeechModule(max_workers=1)
        # Create audio at 48kHz to trigger resampling
        audio = np.random.randn(48000).astype(np.float32)
        result = sm.transcribe_array(audio, sr=48000)
        # CR-013: Must delegate to centralized resample_if_needed
        assert mock_resample.called, (
            "transcribe_array must use centralized resample_if_needed, "
            "not inline scipy.signal.resample"
        )
        assert result == "test text"
