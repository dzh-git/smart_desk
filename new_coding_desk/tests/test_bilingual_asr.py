from __future__ import annotations

import numpy as np

from backend.services.translation_service import _normalize_punctuation
from backend.speech_module.bilingual_asr import (
    SpeechRecognitionResult,
    normalize_language,
    parse_sensevoice_result,
)
from backend.speech_module.speech_module import SpeechModule


def test_parse_sensevoice_chinese_tag_and_strip_rich_tags() -> None:
    result = parse_sensevoice_result([
        {"text": "<|zh|><|NEUTRAL|><|Speech|><|woitn|>你好，欢迎。"},
    ])
    assert result.source_lang == "zh"
    assert "你好" in result.text
    assert "<|" not in result.text


def test_parse_sensevoice_english_tag() -> None:
    result = parse_sensevoice_result([
        {"text": "<|en|><|NEUTRAL|><|Speech|><|withitn|>Welcome to the meeting."},
    ])
    assert result.source_lang == "en"
    assert "Welcome to the meeting" in result.text


def test_language_falls_back_to_text_for_unknown_metadata() -> None:
    assert normalize_language("auto", "这是中文") == "zh"
    assert normalize_language("auto", "This is English") == "en"


def test_chinese_final_routes_through_paraformer(monkeypatch) -> None:
    from backend.speech_module import bilingual_asr, stt_streaming

    monkeypatch.setattr(
        bilingual_asr,
        "recognize_bilingual",
        lambda audio: SpeechRecognitionResult("就清杯的本科。", "zh"),
    )
    monkeypatch.setattr(stt_streaming, "offline_rescore", lambda audio: "就清北的本科")

    result = SpeechModule().transcribe_array_with_language(
        np.zeros(1600, dtype=np.float32),
    )
    assert result.text == "就清北的本科"
    assert result.source_lang == "zh"
    assert result.recognition_model == "paraformer_zh"


def test_english_final_does_not_run_chinese_paraformer(monkeypatch) -> None:
    from backend.speech_module import bilingual_asr, stt_streaming

    monkeypatch.setattr(
        bilingual_asr,
        "recognize_bilingual",
        lambda audio: SpeechRecognitionResult("Welcome.", "en"),
    )
    monkeypatch.setattr(
        stt_streaming,
        "offline_rescore",
        lambda audio: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    result = SpeechModule().transcribe_array_with_language(
        np.zeros(1600, dtype=np.float32),
    )
    assert result.text == "Welcome."
    assert result.recognition_model == "sensevoice"


def test_duplicate_and_conflicting_chinese_punctuation_is_normalized() -> None:
    raw = "你好，，大家注意啊。，行情好？？不代表价格好。。。"
    assert _normalize_punctuation(raw, "zh") == "你好，大家注意啊。行情好？不代表价格好。"
