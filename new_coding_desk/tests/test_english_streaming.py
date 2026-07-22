from __future__ import annotations

import types
from pathlib import Path

import numpy as np
import pytest

from backend.speech_module import english_streaming
from backend.speech_module.speech_module import SpeechModule
from backend.services.speech_stream_service import SpeechStreamService


class _FakeStream:
    def __init__(self) -> None:
        self.chunks: list[np.ndarray] = []
        self.finished = False

    def accept_waveform(self, sample_rate: int, audio: np.ndarray) -> None:
        assert sample_rate == 16000
        self.chunks.append(audio.copy())

    def input_finished(self) -> None:
        self.finished = True


class _FakeRecognizer:
    def create_stream(self) -> _FakeStream:
        return _FakeStream()

    def is_ready(self, stream: _FakeStream) -> bool:
        return False

    def decode_stream(self, stream: _FakeStream) -> None:
        raise AssertionError("fake stream is never queued")

    def get_result(self, stream: _FakeStream):
        words = ["the", "first", "word", "is", "ready"]
        return types.SimpleNamespace(text=" ".join(words[:len(stream.chunks)]))


@pytest.fixture(autouse=True)
def _reset_english_streaming(monkeypatch):
    monkeypatch.setattr(english_streaming, "_recognizer", None)
    monkeypatch.setattr(english_streaming, "_model_path", None)
    monkeypatch.setattr(english_streaming, "_load_error", None)


def _prepare_fake_model(monkeypatch):
    monkeypatch.setattr(english_streaming, "_validate_model", lambda _path: None)
    fake_module = types.SimpleNamespace(
        OnlineRecognizer=types.SimpleNamespace(
            from_transducer=lambda **_kwargs: _FakeRecognizer(),
        ),
    )
    monkeypatch.setitem(__import__("sys").modules, "sherpa_onnx", fake_module)


def test_processor_accepts_each_pcm_chunk_once_and_keeps_word_spaces(monkeypatch):
    _prepare_fake_model(monkeypatch)
    processor = english_streaming.EnglishStreamingProcessor()
    assert processor.process_chunk(np.ones(1600, dtype=np.float32)) == "the"
    assert processor.process_chunk(np.ones(1600, dtype=np.float32)) == "the first"
    assert processor.process_chunk(np.ones(1600, dtype=np.float32)) == "the first word"
    assert processor.frames_processed == 3
    assert processor.finish() == "the first word"
    assert processor.finish() == "the first word"


def test_missing_model_is_reported_without_runtime_download(monkeypatch):
    missing = Path("definitely-missing-english-streaming-model")
    monkeypatch.setattr(english_streaming, "get_english_streaming_model_path", lambda: missing)
    with pytest.raises(FileNotFoundError):
        english_streaming.warmup_english_streaming()
    status = english_streaming.get_english_streaming_status()
    assert status["status"] == "error"
    assert "prepare_bilingual_models.py" in str(status["error"])


def test_speech_module_uses_isolated_english_processors(monkeypatch):
    processors = []

    class _Processor:
        def __init__(self):
            self.text = ""
            processors.append(self)

        def process_chunk(self, audio, sample_rate):
            assert sample_rate == 16000
            self.text += " word"
            return self.text.strip()

        def finish(self):
            return self.text.strip()

    monkeypatch.setattr(english_streaming, "EnglishStreamingProcessor", _Processor)
    module = SpeechModule()
    audio = np.ones(1600, dtype=np.float32)
    assert module.process_english_interim_array(audio, "seat_a") == "word"
    assert module.process_english_interim_array(audio, "seat_b") == "word"
    assert len(processors) == 2
    assert module.finish_english_interim("seat_a") == "word"
    module.reset_streaming_state("seat_a")
    assert module.process_english_interim_array(audio, "seat_a") == "word"
    assert len(processors) == 3


def test_english_stream_failure_uses_named_sensevoice_fallback(monkeypatch):
    service = SpeechStreamService()
    key, _ = service.create_session(77, 1)

    class _Module:
        ready = True

        def set_session_context(self, *_args):
            pass

        def start_utterance(self, *_args):
            pass

        def process_english_interim_array(self, *_args):
            raise RuntimeError("Zipformer files missing")

    service._speech_module = _Module()
    monkeypatch.setattr(
        "backend.speech_module.bilingual_asr.recognize_bilingual",
        lambda *_args, **_kwargs: types.SimpleNamespace(
            text="fallback text", source_lang="en",
        ),
    )
    service.start_utterance(key, "utt_77_1_000001", language_mode="en")
    session = service.get_session(key)
    assert session is not None
    session.calibration_frames_remaining = 0
    session.voice_active = True
    session.has_speech = True
    frame = np.full(1600, 5000, dtype=np.int16).tobytes()
    for _ in range(10):
        result = service.process_pcm_frame(key, frame)
    assert result["recognition_engine"] == "sensevoice_rolling_fallback"
    assert result["source_text"] == "Fallback text"
