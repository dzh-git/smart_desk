"""
Speech API — model status and preload control.

Per Task 119:
    GET  /api/speech/status   → unified model readiness state
    POST /api/speech/preload  → trigger background model preload

Returns unified ApiResponse with speech status dict.
"""
from __future__ import annotations

from fastapi import APIRouter
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
