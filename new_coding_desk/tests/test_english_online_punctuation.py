from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.speech_module.english_punctuation import (
    add_english_punctuation,
    get_english_punctuation_status,
    get_english_punctuation_model_path,
    has_trusted_terminal_boundary,
    strip_provisional_terminal,
)


def test_model_path_prefers_environment_override(monkeypatch) -> None:
    target = Path("D:/Ai_project/smart_desktop/test-english-punctuation")
    monkeypatch.setenv("ENGLISH_ONLINE_PUNCTUATION_MODEL_PATH", str(target))
    assert get_english_punctuation_model_path() == target


def test_incomplete_tail_blocks_short_pause_boundary() -> None:
    assert not has_trusted_terminal_boundary(
        "DO WE HAVE ANY", "Do we have any.",
    )
    assert not has_trusted_terminal_boundary(
        "THERE WILL BE A", "There will be a.",
    )


def test_complete_question_allows_short_pause_boundary() -> None:
    assert has_trusted_terminal_boundary(
        "ANY QUESTIONS", "Any questions?",
    )
    assert has_trusted_terminal_boundary(
        "DO WE HAVE ANY ASSIGNMENTS", "Do we have any assignments?",
    )


def test_provisional_terminal_is_hidden_but_internal_punctuation_is_kept() -> None:
    assert strip_provisional_terminal(
        "Any questions? Do we have any."
    ) == "Any questions? Do we have any"


@pytest.mark.skipif(
    os.getenv("RUN_ENGLISH_PUNCTUATION_SMOKE", "").casefold() != "true",
    reason="real local punctuation model smoke test is opt-in",
)
def test_real_model_restores_internal_question_boundaries() -> None:
    source = (
        "in addition to your participation in class which accounts for 10 "
        "percent there will be a midterm test 20 percent a final exam 30 "
        "percent and a research paper 40 percent any questions do we have any "
        "assignments yes i believe you've all got your textbook"
    )
    result = add_english_punctuation(source)

    assert "any questions? do we have any assignments?" in result.casefold()
    assert get_english_punctuation_status()["last_inference_ms"] < 100
