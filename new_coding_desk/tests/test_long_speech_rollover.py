from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
import threading
import time

import pytest
import numpy as np

from backend.services.speech_stream_service import (
    SpeechStreamService,
    SpeechStreamSession,
)
from backend.speech_module.speech_module import SpeechModule
from backend.speech_module.stt_streaming import StreamingChunkProcessor


def test_long_utterance_ignores_comma_and_uses_hard_duration_boundary() -> None:
    service = SpeechStreamService()
    session = SpeechStreamSession(1, 1, "speech_1_1")
    session.has_speech = True

    session.utterance_audio_seconds = 30.0
    assert service._boundary_reason(
        session,
        "这是一个完整从句，后面仍在继续。",
        natural_boundary_committed=True,
        committed_boundary="，",
    ) is None
    assert service._boundary_reason(
        session,
        "标点模型临时补出的句号。",
        natural_boundary_committed=False,
    ) is None

    session.utterance_audio_seconds = 45.0
    assert service._boundary_reason(session, "仍在连续发言") == "max_duration"

    status = service.get_model_status()
    assert status["soft_utterance_seconds"] == 30.0
    assert status["hard_utterance_seconds"] == 45.0
    assert status["rollover_overlap_ms"] == 300
    assert status["max_buffered_audio_seconds"] == 0.0
    assert "pending_finalizations" in status
    assert "process_rss_mb" in status


def test_speech_status_reports_pcm_input_before_voice_gate() -> None:
    service = SpeechStreamService()
    session = SpeechStreamSession(41, 1, "speech_41_1")
    service._sessions[session.session_key] = session
    service.start_utterance(session.session_key, "utt_41_1_000001")

    pcm = np.full(1600, 100, dtype=np.int16).tobytes()
    service.process_pcm_frame(session.session_key, pcm)

    diagnostic = service.get_model_status()["sessions"][0]
    assert diagnostic["pcm_frames_received"] == 1
    assert diagnostic["pcm_bytes_received"] == len(pcm)
    assert diagnostic["last_input_rms"] > 0
    assert diagnostic["voice_active"] is False
    assert diagnostic["calibration_frames_remaining"] == 2


def test_start_utterance_fully_resets_streaming_processor_cache() -> None:
    speech = SpeechModule()
    processor = StreamingChunkProcessor()
    processor._cache = {"encoder": [1]}
    processor._accumulated_text = "旧的实时文字"
    processor._total_frames = 99
    speech._sessions["speech_1_1"] = {
        "processor": processor,
        "meeting_id": 1,
        "seat_id": 1,
        "next_segment_id": 1,
    }

    speech.start_utterance("speech_1_1")

    assert processor._cache == {}
    assert processor.accumulated_text == ""
    assert processor._total_frames == 0


def test_slow_translation_worker_does_not_block_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.speech_finalization_service import (
        SpeechFinalizationJob,
        SpeechFinalizationQueue,
    )

    service = SpeechFinalizationQueue(max_pending=2)
    completed = threading.Event()

    def slow_process(*_args: object, **_kwargs: object) -> None:
        time.sleep(0.2)
        completed.set()

    monkeypatch.setattr(service, "_process", slow_process)
    started = time.monotonic()
    assert service.submit(SpeechFinalizationJob(
        meeting_id=1,
        seat_id=1,
        utterance_id="utt_slow",
        source_text="后台翻译不应阻塞实时音频。",
        boundary_reason="end_hint",
        audio_seconds=30.0,
    ))
    assert time.monotonic() - started < 0.05
    assert completed.wait(1.0)


def test_translation_backlog_uses_ordered_source_only_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.speech_finalization_service import (
        SpeechFinalizationJob,
        SpeechFinalizationQueue,
    )

    service = SpeechFinalizationQueue(max_pending=1)
    monkeypatch.setattr(service, "_ensure_worker", lambda: None)
    first = SpeechFinalizationJob(1, 1, "utt_first", "第一段。", "max_duration", 30.0)
    second = SpeechFinalizationJob(1, 1, "utt_second", "第二段。", "max_duration", 30.0)

    assert service.submit(first) is True
    assert service.submit(second) is False
    assert service._queue.get_nowait() == (first, True)
    assert service._queue.get_nowait() == (second, False)


@pytest.mark.anyio
async def test_streaming_asr_does_not_block_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.speech_stream_service import stream_service
    from backend.websocket.speech_ws import _handle_binary_message

    key, token = stream_service.create_session(1, 1)
    stream_service.start_utterance(key, "utt_1_1_000001")

    def slow_process(*_args: object) -> dict[str, object]:
        time.sleep(0.15)
        return {
            "utterance_id": "utt_1_1_000001",
            "revision": 1,
            "source_text": "",
            "vad_should_finalize": False,
            "boundary_reason": None,
        }

    monkeypatch.setattr(stream_service, "process_pcm_frame", slow_process)
    ws = AsyncMock()
    try:
        task = asyncio.create_task(
            _handle_binary_message(ws, b"\x00" * 3200, 1, 1, key),
        )
        await asyncio.sleep(0.02)
        assert task.done() is False
        await asyncio.wait_for(task, timeout=1.0)
    finally:
        stream_service.remove_session(key, token)


@pytest.mark.anyio
async def test_auto_final_starts_next_utterance_before_background_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.speech_finalization_service import finalization_queue
    from backend.services.speech_stream_service import stream_service
    from backend.websocket.speech_ws import _handle_binary_message

    key, token = stream_service.create_session(1, 1)
    sequence_key = (1, 1)
    previous_sequence = stream_service._utterance_sequences.get(sequence_key)
    try:
        stream_service.seed_utterance_sequence(1, 1, 1)
        stream_service.start_utterance(key, "utt_1_1_000001")
        session = stream_service.get_session(key)
        assert session is not None
        session.has_speech = True
        session.utterance_audio_seconds = 45.0
        session._utterance_buffer.append(b"\x01\x00" * 1600)

        monkeypatch.setattr(
            stream_service,
            "process_pcm_frame",
            lambda *_: {
                "utterance_id": "utt_1_1_000001",
                "revision": 8,
                "source_text": "这是一段足够长的实时识别文本。",
                "vad_should_finalize": True,
                "boundary_reason": "max_duration",
            },
        )
        submitted: list[object] = []
        monkeypatch.setattr(
            finalization_queue,
            "submit",
            lambda job: submitted.append(job) or True,
        )

        ws = AsyncMock()
        await _handle_binary_message(ws, b"\x01\x00" * 1600, 1, 1, key)

        next_uid = stream_service.get_session(key).current_utterance_id
        assert next_uid is not None and next_uid != "utt_1_1_000001"
        ws.send_json.assert_awaited_with({
            "type": "utterance_started",
            "utterance_id": next_uid,
        })
        assert len(submitted) == 1
        assert submitted[0].utterance_id == "utt_1_1_000001"
        assert submitted[0].source_text == "这是一段足够长的实时识别文本。"
        assert submitted[0].sample_rate == 16000
        assert submitted[0].audio is not None
        assert len(submitted[0].audio) == 1600
    finally:
        stream_service.remove_session(key, token)
        if previous_sequence is None:
            stream_service._utterance_sequences.pop(sequence_key, None)
        else:
            stream_service._utterance_sequences[sequence_key] = previous_sequence


@pytest.mark.anyio
async def test_end_hint_queues_bilingual_final_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from backend.services.speech_finalization_service import finalization_queue
    from backend.services.speech_stream_service import stream_service
    from backend.websocket.speech_ws import _handle_text_message

    key, token = stream_service.create_session(9, 1)
    try:
        stream_service.start_utterance(key, "utt_9_1_000001")
        session = stream_service.get_session(key)
        assert session is not None
        session.has_speech = True
        session.last_source_text = "Welcome to the meeting."
        session.utterance_audio_seconds = 0.1
        session._utterance_buffer.append(b"\x01\x00" * 1600)
        submitted: list[object] = []
        monkeypatch.setattr(
            finalization_queue,
            "submit",
            lambda job: submitted.append(job) or True,
        )

        await _handle_text_message(
            AsyncMock(), json.dumps({"type": "end_hint"}), 9, 1, key,
        )

        assert len(submitted) == 1
        job = submitted[0]
        assert job.source_text == "Welcome to the meeting."
        assert job.audio is not None and len(job.audio) == 1600
        assert job.sample_rate == 16000
        assert stream_service.is_utterance_terminal(key, job.utterance_id)
    finally:
        stream_service.remove_session(key, token)


def test_duration_rollover_replays_300ms_once_without_counting_it() -> None:
    class FakeSpeechModule:
        ready = True

        def __init__(self) -> None:
            self.calls: list[int] = []
            self.reset_interim_calls = 0

        def set_session_context(self, *_args: object) -> None:
            return None

        def start_utterance(self, *_args: object) -> None:
            return None

        def process_interim_array(self, audio, *_args: object) -> str:
            self.calls.append(len(audio))
            return "重叠上下文" if len(self.calls) == 1 else "新的实时内容"

        def reset_interim(self, *_args: object) -> None:
            self.reset_interim_calls += 1

    service = SpeechStreamService()
    fake = FakeSpeechModule()
    service._speech_module = fake
    key, _token = service.create_session(1, 1)
    service.start_utterance(
        key, "utt_1_1_000001", language_mode="zh",
    )
    session = service.get_session(key)
    assert session is not None
    session.has_speech = True
    session.voice_active = True
    session.speaking_event_active = True
    frame = b"\x10\x00" * 1600  # 100 ms
    session._utterance_buffer.extend([frame] * 5)
    session.utterance_audio_seconds = 45.0
    session.last_source_text = "旧段实时内容。"

    snapshot = service.snapshot_auto_finalization(
        key, session.last_source_text, "max_duration",
    )
    assert snapshot is not None
    assert snapshot["rollover_overlap_ms"] == 300
    assert len(session._rollover_overlap_pcm) == len(frame) * 3
    assert session.speaking_event_active is True

    service.prepare_next_utterance(
        key, 1, 1, continuous_rollover=True,
    )
    assert session.voice_active is True
    result = service.process_pcm_frame(key, frame)

    assert fake.calls == [4800, 1600]
    assert fake.reset_interim_calls == 1
    assert session._rollover_overlap_pcm == b""
    assert session._utterance_buffer == [frame]
    assert session.utterance_audio_seconds == pytest.approx(0.1)
    assert result["source_text"].startswith("新的实时内容")
