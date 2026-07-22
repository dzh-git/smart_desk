from __future__ import annotations

from unittest.mock import MagicMock

from backend.events import event_bus
from backend.services.interim_translation_service import (
    EnglishSentenceCorrectionJob,
    EnglishSentenceCorrectionService,
    InterimTranslationJob,
    InterimTranslationService,
    caption_window_text,
    SentenceTranslationJob,
    SentenceTranslationService,
)


def test_caption_window_text_excludes_scrolled_source_history() -> None:
    assert caption_window_text(
        "已经滚动消失的历史。当前上一行。当前下一行。",
        {"previous_line": "当前上一行。", "current_line": "当前下一行。"},
        "zh",
    ) == "当前上一行。当前下一行。"
    assert caption_window_text(
        "Old history. Current first. Current second.",
        {"previous_line": "Current first.", "current_line": "Current second."},
        "en",
    ) == "Current first. Current second."


def test_interim_translation_publishes_translation_only_update() -> None:
    model = MagicMock()
    model.translate.return_value = "Hello everyone."
    service = InterimTranslationService(
        debounce_seconds=0.0,
        max_debounce_seconds=0.0,
        translation_model=model,
    )
    received = []

    def capture(event) -> None:
        received.append(event)

    event_bus.subscribe("translation_interim", capture)
    try:
        assert service.submit(InterimTranslationJob(
            session_key="speech_1_1",
            meeting_id=1,
            seat_id=1,
            utterance_id="utt_1_1_000001",
            revision=7,
            source_lang="zh",
            target_lang="en",
            source_text="大家好",
        )) is True
        assert service.wait_for_idle()
    finally:
        event_bus.unsubscribe("translation_interim", capture)

    assert len(received) == 1
    assert received[0].payload["translation_only"] is True
    assert received[0].payload["translation_revision"] == 7
    assert received[0].payload["translated_text"] == "Hello everyone."
    model.translate.assert_called_once_with("大家好", "zh", "en")


def test_duplicate_interim_text_is_not_translated_twice() -> None:
    model = MagicMock()
    model.translate.return_value = "Hello."
    service = InterimTranslationService(
        debounce_seconds=0.0,
        max_debounce_seconds=0.0,
        translation_model=model,
    )
    job = InterimTranslationJob(
        session_key="speech_1_1",
        meeting_id=1,
        seat_id=1,
        utterance_id="utt_1_1_000001",
        revision=1,
        source_lang="zh",
        target_lang="en",
        source_text="你好",
    )
    assert service.submit(job) is True
    assert service.wait_for_idle()
    assert service.submit(job) is False
    model.translate.assert_called_once()


def test_completed_sentences_are_translated_fifo_without_replacement() -> None:
    model = MagicMock()
    model.translate.side_effect = ["First.", "Second."]
    service = SentenceTranslationService(translation_model=model)
    received = []

    def capture(event) -> None:
        received.append(event.payload)

    event_bus.subscribe("translation_sentence", capture)
    try:
        first = SentenceTranslationJob(
            1, 1, "utt_1", "utt_1:s000001", 1, 3,
            "zh", "en", "第一句。",
        )
        second = SentenceTranslationJob(
            1, 1, "utt_1", "utt_1:s000002", 2, 5,
            "zh", "en", "第二句。",
        )
        assert service.submit(first) is True
        assert service.submit(second) is True
        assert service.submit(first) is False
        assert service.wait_for_idle()
    finally:
        event_bus.unsubscribe("translation_sentence", capture)

    assert [item["sentence_id"] for item in received] == [
        "utt_1:s000001", "utt_1:s000002",
    ]
    assert [item["translated_text"] for item in received] == [
        "First.", "Second.",
    ]
    diagnostics = service.get_diagnostics()
    assert diagnostics["pending"] == 0
    assert diagnostics["submitted_count"] == 2
    assert diagnostics["completed_count"] == 2
    assert diagnostics["last_queue_wait_ms"] >= 0
    assert diagnostics["last_inference_ms"] >= 0


def test_english_sentence_correction_locks_source_before_translation(monkeypatch) -> None:
    service = EnglishSentenceCorrectionService()
    received = []
    submitted = []

    def capture(event) -> None:
        received.append(event.payload)

    monkeypatch.setattr(
        "backend.services.interim_translation_service.sentence_translation_service.submit",
        lambda job: submitted.append(job) or True,
    )
    event_bus.subscribe("translation_sentence", capture)
    try:
        service._publish_locked(EnglishSentenceCorrectionJob(
            1, 1, "utt_1", "utt_1:s000001", 1, 7,
            "when do you usually do that", object(),
        ), "When do you usually do that?", "ok")
    finally:
        event_bus.unsubscribe("translation_sentence", capture)

    assert received[0]["source_locked"] is True
    assert received[0]["recognition_status"] == "ok"
    assert received[0]["source_text"] == "When do you usually do that?"
    assert submitted[0].source_locked is True
    assert submitted[0].revision == 8


def test_sentence_translation_failure_is_explicitly_unavailable() -> None:
    model = MagicMock()
    model.translate.side_effect = RuntimeError("model failed")
    service = SentenceTranslationService(translation_model=model)
    received = []

    def capture(event) -> None:
        received.append(event.payload)

    event_bus.subscribe("translation_sentence", capture)
    try:
        assert service.submit(SentenceTranslationJob(
            1, 1, "utt_1", "utt_1:s000001", 1, 1,
            "en", "zh", "Welcome.",
        )) is True
        assert service.wait_for_idle()
    finally:
        event_bus.unsubscribe("translation_sentence", capture)

    assert received[0]["translation_status"] == "unavailable"
    assert received[0]["translated_text"] == ""
    assert received[0]["translation_error"] == "model failed"
