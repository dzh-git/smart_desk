from __future__ import annotations

import torch

from backend.services.translation_model_service import (
    NOT_AVAILABLE,
    TranslationModelService,
    _ModelBundle,
    _output_looks_degenerate,
    _split_translation_units,
)


class _CharacterTokenizer:
    def __call__(self, text: str, **kwargs):
        ids = list(range(max(1, len(text))))
        if kwargs.get("return_tensors") == "pt":
            return {"input_ids": torch.tensor([ids])}
        return {"input_ids": ids}

    def decode(self, ids, **kwargs) -> str:
        return "Safe translation."


def test_final_translation_is_split_at_terminal_sentences_before_generation() -> None:
    text = (
        "比分来到六比六的时候，许昕展现招牌技术优势，侧身全部启动，核心发力，一记有效刺身爆冲，"
        "球速极快，直接击穿对手防线。下一回，合许昕迅速调整七星放弃暴怨性能改应反手快丝斜线引附点变化，"
        "牵制对手一笔进攻失误。"
    )
    units = _split_translation_units(text, _CharacterTokenizer(), "zh")
    assert units == [
        "比分来到六比六的时候，许昕展现招牌技术优势，侧身全部启动，核心发力，一记有效刺身爆冲，球速极快，直接击穿对手防线。",
        "下一回，合许昕迅速调整七星放弃暴怨性能改应反手快丝斜线引附点变化，牵制对手一笔进攻失误。",
    ]


def test_overlong_unpunctuated_input_is_bounded_without_losing_text() -> None:
    text = "甲" * 150
    units = _split_translation_units(text, _CharacterTokenizer(), "zh")
    assert "".join(units) == text
    assert all(len(unit) <= 64 for unit in units)


def test_repetitive_or_length_capped_output_is_rejected() -> None:
    assert _output_looks_degenerate("Xu " * 60, generated_length=48, max_new_tokens=48)
    assert _output_looks_degenerate("Xiang " * 40, generated_length=12, max_new_tokens=48)
    assert not _output_looks_degenerate("A concise and readable translation ends normally.", 9, 48)


class _RetryTokenizer(_CharacterTokenizer):
    def __init__(self) -> None:
        self.decode_calls = 0

    def decode(self, ids, **kwargs) -> str:
        self.decode_calls += 1
        return ("Xu " * 60).strip() if self.decode_calls == 1 else "Recovered translation."


class _RetryModel:
    def __init__(self) -> None:
        self.options: list[dict] = []

    def generate(self, **kwargs):
        self.options.append(kwargs)
        length = kwargs["max_new_tokens"] if len(self.options) == 1 else 6
        return torch.tensor([list(range(length))])


def test_degenerate_output_retries_with_stricter_parameters() -> None:
    tokenizer = _RetryTokenizer()
    model = _RetryModel()
    service = TranslationModelService()
    service._enabled = True
    service._bundles[("zh", "en")] = _ModelBundle(
        "zh", "en", "test", tokenizer=tokenizer, model=model, loaded=True,
    )

    assert service.translate("这是用于重试的测试句子。", "zh", "en") == "Recovered translation."
    assert model.options[0]["no_repeat_ngram_size"] == 3
    assert model.options[1]["no_repeat_ngram_size"] == 2


def test_persistent_degenerate_output_is_unavailable() -> None:
    class _AlwaysLoopTokenizer(_CharacterTokenizer):
        def decode(self, ids, **kwargs) -> str:
            return ("Xiang " * 60).strip()

    class _AlwaysLoopModel:
        def generate(self, **kwargs):
            return torch.tensor([list(range(kwargs["max_new_tokens"]))])

    service = TranslationModelService()
    service._enabled = True
    service._bundles[("zh", "en")] = _ModelBundle(
        "zh", "en", "test", tokenizer=_AlwaysLoopTokenizer(),
        model=_AlwaysLoopModel(), loaded=True,
    )
    assert service.translate("这是退化失败测试。", "zh", "en") == NOT_AVAILABLE
