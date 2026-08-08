"""Opt-in, bounded speech diagnostics for reproducing live ASR defects.

The capture is disabled unless ``SMART_DESK_CAPTURE_SPEECH_DEBUG=true``.
Files are local-only runtime artifacts: exact server-received PCM as WAV plus
a compact JSON timeline containing only text changes and decoder state.
"""
from __future__ import annotations

import json
import os
import re
import time
import wave
from pathlib import Path
from typing import Any


_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def is_speech_debug_capture_enabled() -> bool:
    return os.environ.get("SMART_DESK_CAPTURE_SPEECH_DEBUG", "").lower() == "true"


def _capture_dir() -> Path:
    configured = os.environ.get("SMART_DESK_SPEECH_DEBUG_DIR", "").strip()
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[2] / ".smartdesk-runtime" / "speech-debug"


def record_speech_debug_revision(
    session: Any,
    *,
    raw_text: str,
    source_text: str,
    boundary_reason: str | None,
) -> None:
    """Append one compact record only when the visible/raw text changes."""
    if not is_speech_debug_capture_enabled():
        return
    revisions = session.speech_debug_revisions
    previous = revisions[-1] if revisions else None
    if (
        previous
        and previous.get("raw_text") == raw_text
        and previous.get("source_text") == source_text
        and previous.get("boundary_reason") == boundary_reason
    ):
        return
    revisions.append({
        "revision": int(session.revision),
        "time_ms": int(time.time() * 1000),
        "raw_text": raw_text,
        "source_text": source_text,
        "input_rms": round(float(session.last_input_rms), 6),
        "silence_ms": round(float(session.vad_silence_seconds) * 1000),
        "chinese_flushed": bool(session.chinese_streaming_flushed),
        "boundary_reason": boundary_reason,
    })
    if len(revisions) > 500:
        del revisions[:-500]


def record_speech_debug_decoder_call(
    session: Any,
    *,
    stage: str,
    decoder: dict[str, Any] | None,
) -> None:
    """Record one Paraformer generate/merge result for the active utterance."""
    if not is_speech_debug_capture_enabled() or not decoder:
        return
    calls = session.speech_debug_decoder_calls
    calls.append({
        "time_ms": int(time.time() * 1000),
        "revision": int(session.revision),
        "stage": stage,
        "input_rms": round(float(session.last_input_rms), 6),
        "silence_ms": round(float(session.vad_silence_seconds) * 1000),
        **decoder,
    })
    if len(calls) > 1000:
        del calls[:-1000]


def save_speech_debug_capture(
    session: Any,
    *,
    pcm_bytes: bytes,
    boundary_reason: str,
) -> dict[str, str] | None:
    """Persist one WAV+JSON pair and retain only the newest bounded captures."""
    if not is_speech_debug_capture_enabled() or not pcm_bytes:
        return None
    destination = _capture_dir()
    destination.mkdir(parents=True, exist_ok=True)
    safe_id = _SAFE_NAME.sub("_", str(session.current_utterance_id or "unknown"))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = destination / f"{stamp}-{safe_id}"
    wav_path = base.with_suffix(".wav")
    json_path = base.with_suffix(".json")

    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(pcm_bytes)

    payload = {
        "schema": "smartdesk-speech-debug-v1",
        "captured_at_ms": int(time.time() * 1000),
        "utterance_id": session.current_utterance_id,
        "meeting_id": session.meeting_id,
        "seat_id": session.seat_id,
        "requested_language": session.requested_language,
        "detected_language": session.detected_language,
        "recognition_engine": session.recognition_engine,
        "boundary_reason": boundary_reason,
        "audio_seconds": round(len(pcm_bytes) / 32000.0, 3),
        "final_live_text": session.last_source_text,
        "decoder_calls": list(session.speech_debug_decoder_calls),
        "revisions": list(session.speech_debug_revisions),
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    _prune_old_captures(destination)
    return {"wav": str(wav_path), "json": str(json_path)}


def update_speech_debug_final_result(
    utterance_id: str | None,
    *,
    translation_id: int,
    source_text: str,
    source_lang: str,
    source_type: str | None,
    recognition_status: str,
) -> str | None:
    """Attach the persisted final text to the matching capture JSON."""
    if not is_speech_debug_capture_enabled() or not utterance_id:
        return None
    destination = _capture_dir()
    safe_id = _SAFE_NAME.sub("_", str(utterance_id))
    candidates = sorted(
        destination.glob(f"*-{safe_id}.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    json_path = candidates[0]
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["database_final"] = {
        "translation_id": int(translation_id),
        "source_text": source_text,
        "source_lang": source_lang,
        "source_type": source_type,
        "recognition_status": recognition_status,
    }
    temp_path = json_path.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temp_path, json_path)
    return str(json_path)


def _prune_old_captures(destination: Path) -> None:
    try:
        max_captures = max(
            1,
            min(20, int(os.environ.get("SMART_DESK_SPEECH_DEBUG_MAX_CAPTURES", "5"))),
        )
    except ValueError:
        max_captures = 5
    json_files = sorted(
        destination.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old_json in json_files[max_captures:]:
        old_wav = old_json.with_suffix(".wav")
        old_json.unlink(missing_ok=True)
        old_wav.unlink(missing_ok=True)
