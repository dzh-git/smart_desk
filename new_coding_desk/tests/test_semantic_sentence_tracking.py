from __future__ import annotations

from backend.services.speech_stream_service import (
    SpeechStreamService,
    SpeechStreamSession,
)
from backend.events import event_bus


def _session() -> tuple[SpeechStreamService, SpeechStreamSession]:
    service = SpeechStreamService()
    session = SpeechStreamSession(1, 1, "speech_1_1")
    service._sessions[session.session_key] = session
    service.start_utterance(session.session_key, "utt_1_1_000001")
    session.has_speech = True
    return service, session


def test_following_content_confirms_terminal_sentence_once() -> None:
    service, session = _session()
    first = service._track_semantic_sentences(
        session,
        "第一句。第二句正在形成",
        None,
    )
    assert [item["source_text"] for item in first["completed_sentences"]] == [
        "第一句。",
    ]
    assert first["sentence_source_text"] == "第二句正在形成"
    first_id = first["completed_sentences"][0]["sentence_id"]
    assert first_id != first["sentence_id"]

    repeated = service._track_semantic_sentences(
        session,
        "第一句。第二句正在形成",
        None,
    )
    assert repeated["completed_sentences"] == []
    assert repeated["sentence_id"] == first["sentence_id"]


def test_tail_punctuation_requires_sentence_pause_confirmation() -> None:
    service, session = _session()
    provisional = service._track_semantic_sentences(session, "一句完成了。", None)
    assert provisional["completed_sentences"] == []
    assert provisional["sentence_state"] == "forming"

    committed = service._track_semantic_sentences(
        session,
        "一句完成了。",
        "sentence_pause",
    )
    assert committed["sentence_state"] == "completed"
    assert committed["completed_sentences"][0]["source_text"] == "一句完成了。"


def test_comma_and_visual_length_do_not_commit_semantic_sentence() -> None:
    service, session = _session()
    text = "这是一个很长的从句，" + "仍然属于同一句话" * 4
    result = service._track_semantic_sentences(session, text, None)
    assert result["completed_sentences"] == []
    assert result["sentence_source_text"] == text


def test_natural_pause_and_manual_end_commit_remaining_text() -> None:
    service, session = _session()
    natural = service._track_semantic_sentences(
        session,
        "没有终止标点但已经自然停顿",
        "natural_pause",
    )
    assert natural["completed_sentences"][0]["source_text"] == (
        "没有终止标点但已经自然停顿"
    )

    service.start_utterance(session.session_key, "utt_1_1_000002")
    manual = service.complete_active_sentence(
        session.session_key,
        "手动停止时提交剩余文本",
        "end_hint",
    )
    assert manual["completed_sentences"][0]["source_text"] == (
        "手动停止时提交剩余文本"
    )


def test_comma_pause_does_not_finalize_but_natural_pause_does() -> None:
    service, session = _session()
    session.utterance_audio_seconds = 3.0
    session.vad_silence_seconds = 1.3
    assert service._boundary_reason(session, "从句仍未结束，") is None
    session.vad_silence_seconds = 2.0
    assert service._boundary_reason(session, "从句仍未结束，") == "natural_pause"


def test_completed_sentence_pending_event_and_job_share_identity(monkeypatch) -> None:
    from backend.services.interim_translation_service import sentence_translation_service
    from backend.websocket.speech_ws import _publish_completed_sentences

    submitted = []
    received = []
    monkeypatch.setattr(
        sentence_translation_service,
        "submit",
        lambda job: submitted.append(job) or True,
    )

    def capture(event) -> None:
        received.append(event.payload)

    event_bus.subscribe("translation_sentence", capture)
    try:
        _publish_completed_sentences(
            meeting_id=1,
            seat_id=2,
            utterance_id="utt_1_2_000001",
            revision=7,
            completed_sentences=[{
                "sentence_id": "utt_1_2_000001:s000001",
                "sentence_sequence": 1,
                "source_text": "Welcome everyone.",
            }],
        )
    finally:
        event_bus.unsubscribe("translation_sentence", capture)

    assert received[0]["translation_status"] == "pending"
    assert received[0]["source_lang"] == "en"
    assert received[0]["target_lang"] == "zh"
    assert submitted[0].sentence_id == received[0]["sentence_id"]
    assert submitted[0].revision == received[0]["revision"]


def test_translation_sentence_is_registered_for_room_broadcast() -> None:
    from backend.websocket.event_handler import WebSocketEventHandler

    assert "translation_sentence" in WebSocketEventHandler.BROADCAST_EVENTS


def test_sentence_sequence_stays_monotonic_when_speech_session_reconnects() -> None:
    service = SpeechStreamService()
    first = SpeechStreamSession(1, 1, "speech_1_1")
    first.current_utterance_id = "utt_1_1_000001"
    assert service._ensure_sentence_identity(first)[1] == 1

    replacement = SpeechStreamSession(1, 1, "speech_1_1")
    replacement.current_utterance_id = "utt_1_1_000002"
    sentence_id, sequence = service._ensure_sentence_identity(replacement)
    assert sequence == 2
    assert sentence_id == "utt_1_1_000002:s000002"
