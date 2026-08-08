from __future__ import annotations

import json
import wave
from types import SimpleNamespace

import numpy as np

from backend.services.speech_debug_capture import (
    record_speech_debug_decoder_call,
    record_speech_debug_revision,
    save_speech_debug_capture,
    update_speech_debug_final_result,
)


def _session(utterance_id: str = "utt_debug_001") -> SimpleNamespace:
    return SimpleNamespace(
        current_utterance_id=utterance_id,
        meeting_id=1,
        seat_id=1,
        requested_language="zh",
        detected_language="zh",
        recognition_engine="paraformer_streaming",
        last_source_text="共青团员们。",
        last_input_rms=0.03125,
        vad_silence_seconds=0.9,
        chinese_streaming_flushed=True,
        revision=7,
        speech_debug_decoder_calls=[],
        speech_debug_revisions=[],
    )


def test_capture_disabled_records_nothing(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("SMART_DESK_CAPTURE_SPEECH_DEBUG", raising=False)
    monkeypatch.setenv("SMART_DESK_SPEECH_DEBUG_DIR", str(tmp_path))
    session = _session()
    record_speech_debug_revision(
        session,
        raw_text="共青团员们",
        source_text="共青团员们。",
        boundary_reason="sentence_pause",
    )
    assert session.speech_debug_revisions == []
    assert save_speech_debug_capture(
        session,
        pcm_bytes=b"\x00\x00" * 1600,
        boundary_reason="sentence_pause",
    ) is None
    assert list(tmp_path.iterdir()) == []


def test_capture_saves_exact_pcm_and_compact_changed_revisions(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SMART_DESK_CAPTURE_SPEECH_DEBUG", "true")
    monkeypatch.setenv("SMART_DESK_SPEECH_DEBUG_DIR", str(tmp_path))
    session = _session()
    for _ in range(2):
        record_speech_debug_revision(
            session,
            raw_text="共青团员们",
            source_text="共青团员们。",
            boundary_reason="sentence_pause",
        )
    assert len(session.speech_debug_revisions) == 1

    pcm = b"\x01\x00" * 1600
    result = save_speech_debug_capture(
        session,
        pcm_bytes=pcm,
        boundary_reason="sentence_pause",
    )
    assert result is not None
    with wave.open(result["wav"], "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.readframes(1600) == pcm
    payload = json.loads(open(result["json"], encoding="utf-8").read())
    assert payload["schema"] == "smartdesk-speech-debug-v1"
    assert payload["final_live_text"] == "共青团员们。"
    assert len(payload["revisions"]) == 1
    assert "token" not in json.dumps(payload, ensure_ascii=False).lower()


def test_capture_includes_decoder_calls_and_database_final(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SMART_DESK_CAPTURE_SPEECH_DEBUG", "true")
    monkeypatch.setenv("SMART_DESK_SPEECH_DEBUG_DIR", str(tmp_path))
    session = _session()
    record_speech_debug_decoder_call(
        session,
        stage="streaming",
        decoder={
            "frame_index": 1,
            "samples": 1600,
            "is_final": False,
            "chunk_text": "共青",
            "before_text": "",
            "after_text": "共青",
            "decode_ms": 12,
            "cache_valid": True,
            "cache_size": 3,
        },
    )
    result = save_speech_debug_capture(
        session,
        pcm_bytes=b"\x01\x00" * 1600,
        boundary_reason="sentence_pause",
    )
    assert result is not None

    updated = update_speech_debug_final_result(
        session.current_utterance_id,
        translation_id=42,
        source_text="共青团员们。",
        source_lang="zh",
        source_type="speech_ws",
        recognition_status="ok",
    )
    assert updated == result["json"]
    payload = json.loads(open(result["json"], encoding="utf-8").read())
    assert payload["decoder_calls"][0]["chunk_text"] == "共青"
    assert payload["database_final"] == {
        "translation_id": 42,
        "source_text": "共青团员们。",
        "source_lang": "zh",
        "source_type": "speech_ws",
        "recognition_status": "ok",
    }


def test_streaming_processor_exposes_debug_only_when_capture_enabled(
    monkeypatch,
) -> None:
    from backend.speech_module import stt_streaming

    class FakeStreamingModel:
        def generate(self, *, input, cache, is_final, **kwargs):
            cache["encoder"] = True
            return [{"text": "今天好" if is_final else "今天"}]

    monkeypatch.setattr(stt_streaming, "_streaming_model", FakeStreamingModel())
    monkeypatch.setenv("SMART_DESK_CAPTURE_SPEECH_DEBUG", "true")
    processor = stt_streaming.StreamingChunkProcessor()

    processor.process_chunk(np.zeros(1600, dtype=np.float32))
    assert processor.last_debug == {
        "frame_index": 1,
        "samples": 1600,
        "is_final": False,
        "chunk_text": "今天",
        "before_text": "",
        "after_text": "今天",
        "decode_ms": processor.last_debug["decode_ms"],
        "cache_valid": True,
        "cache_size": 1,
    }

    monkeypatch.setenv("SMART_DESK_CAPTURE_SPEECH_DEBUG", "false")
    processor.process_chunk(np.zeros(1600, dtype=np.float32), is_final=True)
    assert processor.last_debug == {}
