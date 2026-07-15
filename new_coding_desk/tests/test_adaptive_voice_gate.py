import numpy as np

from backend.services.speech_stream_service import (
    SpeechStreamService,
    VAD_CALIBRATION_FRAMES,
    VAD_START_CONFIRM_FRAMES,
)


def pcm(amplitude: float, samples: int = 1600) -> bytes:
    values = np.full(samples, amplitude, dtype=np.float32)
    return (values * 32767).astype(np.int16).tobytes()


class FakeSpeechModule:
    ready = True

    def __init__(self):
        self.calls = 0

    def set_session_context(self, *args):
        pass

    def start_utterance(self, *args):
        pass

    def reset_interim(self, *args):
        pass

    def process_interim_array(self, audio, session_key):
        self.calls += 1
        return "这是完整的一句话。"


def make_service():
    service = SpeechStreamService()
    module = FakeSpeechModule()
    service._speech_module = module
    key, token = service.create_session(1, 1)
    service.start_utterance(key, "utt_1_1_000001")
    return service, module, key, token


def test_silence_and_stable_noise_never_reach_asr_or_buffer():
    service, module, key, _ = make_service()
    for _ in range(300):
        result = service.process_pcm_frame(key, pcm(0.004))
        assert result["source_text"] == ""
        assert result["vad_should_finalize"] is False
    assert module.calls == 0
    assert service.get_buffered_audio(key) is None


def test_voice_requires_calibration_and_confirming_frames():
    service, module, key, _ = make_service()
    for _ in range(VAD_CALIBRATION_FRAMES):
        service.process_pcm_frame(key, pcm(0.003))
    for _ in range(VAD_START_CONFIRM_FRAMES - 1):
        result = service.process_pcm_frame(key, pcm(0.08))
        assert result["revision"] == 0
    result = service.process_pcm_frame(key, pcm(0.08))
    assert result["revision"] == 1
    assert result["source_text"]
    assert module.calls == 3  # 300 ms pre-roll is replayed on confirmed onset
    assert service.get_buffered_audio(key) is not None


def test_early_low_level_voice_does_not_make_gate_chase_speech():
    service, module, key, _ = make_service()
    # The attendee starts during calibration at the level measured on the
    # deployed microphone. Two subsequent 18 mRMS frames must still open the
    # gate instead of being learned as a rising noise floor.
    for _ in range(VAD_CALIBRATION_FRAMES):
        service.process_pcm_frame(key, pcm(0.008))
    for _ in range(VAD_START_CONFIRM_FRAMES):
        result = service.process_pcm_frame(key, pcm(0.018))

    assert result["source_text"]
    assert service.get_session(key).voice_active is True
    assert module.calls == 3


def test_content_aware_boundary_thresholds():
    service, _, key, _ = make_service()
    session = service.get_session(key)
    session.has_speech = True

    session.vad_silence_seconds = 0.89
    assert service._boundary_reason(session, "完整句子。") is None
    session.vad_silence_seconds = 0.9
    assert service._boundary_reason(session, "完整句子。") == "sentence_pause"

    session.vad_silence_seconds = 1.3
    assert service._boundary_reason(session, "这是一个从句，") == "clause_pause"
    session.vad_silence_seconds = 2.0
    assert service._boundary_reason(session, "没有标点但是内容充分") == "natural_pause"


def test_manual_finalize_of_pure_silence_is_quiet_noop():
    service, _, key, _ = make_service()
    for _ in range(30):
        service.process_pcm_frame(key, pcm(0.0))
    assert service.finalize_utterance(key) is None
