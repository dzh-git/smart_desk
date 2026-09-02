"""Order-independent punctuation adapter regression tests."""
from __future__ import annotations

from backend.speech_module import punctuation
from backend.speech_module.caption_formatter import CaptionConfig, CaptionFormatter


class ConflictingPunctuationModel:
    def generate(self, *, input: str, disable_pbar: bool):
        del input, disable_pbar
        return [{"text": "今天天气真好，。我们去了。"}]


def test_model_conflict_before_existing_terminal_is_normalized(monkeypatch):
    monkeypatch.setattr(
        punctuation,
        "_punc_model",
        ConflictingPunctuationModel(),
    )

    assert (
        punctuation.add_punctuation("今天天气真好。我们去了")
        == "今天天气真好。我们去了。"
    )


def test_caption_flow_is_stable_when_punctuation_model_is_loaded(
    monkeypatch,
):
    monkeypatch.setattr(
        punctuation,
        "_punc_model",
        ConflictingPunctuationModel(),
    )
    formatter = CaptionFormatter(
        CaptionConfig(min_line_length=5),
        punctuator=punctuation.add_punctuation,
    )

    result = formatter.update("今天天气真好。我们去了", 1.0)

    assert result.previous_line == "今天天气真好。"
    assert result.current_line == "我们去了。"
