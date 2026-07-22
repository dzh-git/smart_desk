from __future__ import annotations

import numpy as np
import pytest

from backend.services.speech_stream_service import SpeechStreamService
from backend.services.speech_inference_runtime import inference_runtime
from backend.speech_module.bilingual_asr import SpeechRecognitionResult


@pytest.fixture(autouse=True)
def _clear_runtime_stream():
    yield
    inference_runtime.remove_stream("speech_90_1")


class _RoutingSpeechModule:
    ready = True

    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []
        self.english_frames: list[np.ndarray] = []
        self.english_rotations = 0

    def set_session_context(self, *args) -> None:
        pass

    def start_utterance(self, *args) -> None:
        self.frames.clear()
        self.english_frames.clear()

    def reset_interim(self, *args) -> None:
        pass

    def rotate_english_interim(self, *args) -> str:
        self.english_rotations += 1
        return ""

    def process_interim_array(self, audio, session_key):
        self.frames.append(audio)
        return "这是中文实时结果"

    def process_english_interim_array(self, audio, session_key):
        self.english_frames.append(audio)
        return "All right ,that sounds good .Next word."


def _service() -> tuple[SpeechStreamService, str, _RoutingSpeechModule]:
    service = SpeechStreamService()
    key, _ = service.create_session(90, 1)
    module = _RoutingSpeechModule()
    service._speech_module = module
    return service, key, module


def _voice_frame() -> bytes:
    samples = np.full(1600, 5000, dtype=np.int16)
    return samples.tobytes()


def _silence_frame() -> bytes:
    return np.zeros(1600, dtype=np.int16).tobytes()


def _admit_immediately(service: SpeechStreamService, key: str) -> None:
    session = service.get_session(key)
    assert session is not None
    session.calibration_frames_remaining = 0
    session.voice_active = True
    session.has_speech = True


def test_invalid_language_mode_is_rejected() -> None:
    service, key, _ = _service()
    with pytest.raises(ValueError):
        service.start_utterance(key, "utt_90_1_000001", language_mode="fr")


def test_manual_chinese_routes_directly_to_paraformer() -> None:
    service, key, module = _service()
    service.start_utterance(key, "utt_90_1_000002", language_mode="zh")
    _admit_immediately(service, key)
    result = service.process_pcm_frame(key, _voice_frame())
    assert result["detected_language"] == "zh"
    assert result["recognition_engine"] == "paraformer_streaming"
    assert len(module.frames) == 1


def test_manual_english_uses_true_streaming_without_chinese_punctuation(monkeypatch) -> None:
    service, key, module = _service()
    monkeypatch.setattr(
        "backend.speech_module.bilingual_asr.recognize_bilingual",
        lambda audio, language="auto": SpeechRecognitionResult(
            "All right ,that sounds good .Next word.", "en",
        ),
    )
    service.start_utterance(key, "utt_90_1_000003", language_mode="en")
    _admit_immediately(service, key)
    result = {}
    for _ in range(10):
        result = service.process_pcm_frame(key, _voice_frame())
    assert result["source_text"] == "All right, that sounds good. Next word."
    assert result["recognition_engine"] == "sherpa_onnx_streaming"
    assert module.frames == []
    assert len(module.english_frames) == 10


@pytest.mark.parametrize(
    ("detected", "engine", "paraformer_used"),
    [("zh", "paraformer_streaming", True), ("en", "sherpa_onnx_streaming", False)],
)
def test_auto_probe_locks_route_for_the_utterance(
    monkeypatch, detected, engine, paraformer_used,
) -> None:
    service, key, module = _service()
    probe_text = "自动探测中文" if detected == "zh" else "Automatic English probe."
    monkeypatch.setattr(
        "backend.speech_module.bilingual_asr.recognize_bilingual",
        lambda audio, language="auto": SpeechRecognitionResult(probe_text, detected),
    )
    service.start_utterance(key, "utt_90_1_000004", language_mode="auto")
    _admit_immediately(service, key)
    result = {}
    for _ in range(12):
        result = service.process_pcm_frame(key, _voice_frame())
    assert result["requested_language"] == "auto"
    assert result["detected_language"] == detected
    assert result["recognition_engine"] == engine
    assert bool(module.frames) is paraformer_used


def test_english_sentence_completion_freezes_identity_before_correction() -> None:
    service, key, _ = _service()
    service.start_utterance(key, "utt_90_1_000005", language_mode="en")
    session = service.get_session(key)
    assert session is not None

    first = service._track_english_sentences(
        session, "The first sentence.", "english_sentence_pause",
    )
    next_sentence = service._track_english_sentences(
        session, "The next sentence", None,
    )
    assert first["completed_sentences"][0]["sentence_id"] != next_sentence["sentence_id"]
    assert first["completed_sentences"][0]["source_text"] == "The first sentence."


def test_english_vad_pause_restores_case_and_closes_streaming_sentence() -> None:
    service, key, module = _service()
    module.process_english_interim_array = lambda *_args: (
        "NEW CLUB WE HAVE FIFTY MEMBERS"
    )
    service.start_utterance(key, "utt_90_1_000006", language_mode="en")
    _admit_immediately(service, key)
    service.process_pcm_frame(key, _voice_frame())
    result = {}
    for _ in range(9):
        result = service.process_pcm_frame(key, _silence_frame())
    assert result["source_text"] == "New club we have fifty members."
    assert result["boundary_reason"] == "english_sentence_pause"
    assert result["vad_should_finalize"] is False
    assert result["completed_sentences"][0]["source_text"].endswith(".")


def test_english_sentence_pause_starts_an_isolated_decoder_for_next_sentence() -> None:
    service, key, module = _service()
    hypotheses = [
        "I KNOW BUT IT'S ALWAYS PACKED WITH PEOPLE",
        "WHICH SUPERMARKET DO YOU USUALLY GO TO",
    ]

    def _streaming_hypothesis(*_args):
        module.english_frames.append(np.zeros(1, dtype=np.float32))
        return hypotheses[min(module.english_rotations, 1)]

    module.process_english_interim_array = _streaming_hypothesis
    service.start_utterance(key, "utt_90_1_000007", language_mode="en")
    _admit_immediately(service, key)
    service.process_pcm_frame(key, _voice_frame())
    for _ in range(9):
        service.process_pcm_frame(key, _silence_frame())

    result = service.process_pcm_frame(key, _voice_frame())
    assert result["source_text"] == "Which supermarket do you usually go to"
    assert "people" not in result["source_text"]
    assert module.english_rotations == 1
    assert result["vad_should_finalize"] is False
