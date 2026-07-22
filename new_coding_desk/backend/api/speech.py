"""
Speech API — model status and preload control.

Per Task 119:
    GET  /api/speech/status   → unified model readiness state
    POST /api/speech/preload  → trigger background model preload

Returns unified ApiResponse with speech status dict.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from backend.schemas import ApiResponse
from backend.services.speech_stream_service import (
    stream_service,
    _preload_speech_models_background,
)

router = APIRouter(prefix="/api/speech", tags=["speech"])


@router.get("/status")
def get_speech_status():
    """GET /api/speech/status — return unified model readiness state.

    Response data:
    {
        "ready": bool,
        "preloading": bool,
        "streaming_model": "unknown"|"loading"|"loaded"|"error",
        "offline_model": "unknown"|"loading"|"loaded"|"error",
        "punctuation_model": "unknown"|"loading"|"loaded"|"error",
        "vad_model": "unknown"|"loading"|"loaded"|"error",
        "translation_model": "unknown"|"loaded"|"error"|"disabled",
        "translation_model_path": str,
        "translation_last_error": str|null,
        "voice_gate": {... adaptive threshold and pause defaults ...},
        "punctuation_fallback": bool,
        "last_error": str|null
    }
    """
    status = stream_service.get_model_status()
    return ApiResponse.ok(data=status)


@router.post("/preload")
def trigger_preload():
    """POST /api/speech/preload — trigger model preload in background.

    Returns immediately; preload runs in a background thread.
    Check GET /api/speech/status to monitor progress.
    """
    _preload_speech_models_background()
    return ApiResponse.ok(message="Preload triggered")


@router.get("/diagnostics")
def get_speech_diagnostics(
    limit: int = Query(default=5000, ge=1, le=10000),
    utterance_id: str | None = Query(default=None),
):
    """Return bounded speech latency events and live queue diagnostics.

    The payload contains timings and identifiers only; no PCM audio is stored.
    Tracing must be enabled before backend startup with
    ``SMART_DESK_ENABLE_SPEECH_TRACE=true``.
    """
    from backend.services.interim_translation_service import (
        sentence_translation_service,
    )
    from backend.services.speech_finalization_service import finalization_queue
    from backend.websocket.speech_trace import get_trace, is_trace_enabled

    all_events = get_trace()
    events = all_events
    if utterance_id:
        events = [
            event for event in events
            if event.get("utterance_id") == utterance_id
        ]
    events = events[-limit:]
    runtime = stream_service.get_model_status()
    sessions = runtime.get("sessions", [])
    return ApiResponse.ok(data={
        "captured_at_wall_ms": int(time.time() * 1000),
        "trace_enabled": is_trace_enabled(),
        "event_count_total": len(all_events),
        "event_count_returned": len(events),
        "filter_utterance_id": utterance_id,
        "events": events,
        "queues": {
            "finalization": finalization_queue.get_diagnostics(),
            "sentence_translation": sentence_translation_service.get_diagnostics(),
        },
        "runtime": {
            "active_sessions": runtime.get("active_sessions", 0),
            "sessions": sessions,
            "process_rss_mb": runtime.get("process_rss_mb", 0),
        },
        "indicators": {
            "streaming_asr_slower_than_realtime": any(
                int(session.get("last_processing_ms", 0)) > 100
                for session in sessions
            ),
            "finalization_backlog": finalization_queue.pending_count > 1,
            "sentence_translation_backlog": (
                sentence_translation_service.pending_count > 1
            ),
        },
    })


@router.post("/diagnostics/clear")
def clear_speech_diagnostics():
    """Clear only the in-memory trace ring before a controlled reproduction."""
    from backend.websocket.speech_trace import clear_trace, is_trace_enabled

    clear_trace()
    return ApiResponse.ok(data={
        "trace_enabled": is_trace_enabled(),
        "event_count": 0,
    }, message="Speech diagnostics cleared")
