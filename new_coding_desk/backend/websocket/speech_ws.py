"""
Speech WebSocket handler — Speaker Seat audio uplink.

Per WEBSOCKET_PROTOCOL §3-7:
    Endpoint: /ws/speech/{meeting_id}?seat={seat_id}
    Only the current Speaker Seat may connect.
    Client sends JSON control messages + PCM16 binary frames.
    Server sends JSON control messages.

Phase 2 scope:
    - Connection acceptance
    - Meeting/seat validation
    - `start` → `started` + utterance_id
    - Binary frame receive (no-op)
    - `end_hint` / `cancel` receive (no-op)
    - Non-speaker seat rejection with NOT_SPEAKER_SEAT error.

Phase 3 additions:
    - PCM16 binary frame → streaming ASR → EventBus translation_interim
    - Revision tracking per utterance
    - `cancel` → TranslationInterimCancelledEvent via EventBus

Phase 4 additions:
    - Audio buffering per utterance for final ASR rescore
    - `end_hint` → concat buffered PCM16 → TranslationService.process_final_array()
    - TranslationFinalEvent published and broadcast on /ws/{meeting_id}
    - No database writes for interim; only final records persisted.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from backend.database import SessionLocal
from backend.events import event_bus
from backend.events.translation_events import (
    TranslationFinalEvent,
    TranslationInterimCancelledEvent,
    TranslationInterimEvent,
)
from backend.repositories.seat_repository import SeatRepository
from backend.services.meeting_service import MeetingService
from backend.services.speech_stream_service import stream_service
from backend.websocket.speech_registry import speech_registry

logger = logging.getLogger(__name__)

# ── Error payloads ──────────────────────────────────────────────────────────

ERROR_MEETING_NOT_ACTIVE: dict[str, Any] = {
    "type": "error",
    "code": "MEETING_NOT_ACTIVE",
    "message": "Meeting is not active or not found",
}

ERROR_NOT_SPEAKER_SEAT: dict[str, Any] = {
    "type": "error",
    "code": "NOT_SPEAKER_SEAT",
    "message": "Only the speaker seat may stream audio",
}

ERROR_SEAT_OUT_OF_RANGE: dict[str, Any] = {
    "type": "error",
    "code": "INVALID_SEAT_ID",
    "message": "Seat ID must be between 1 and 10",
}

ERROR_MODEL_NOT_LOADED: dict[str, Any] = {
    "type": "error",
    "code": "MODEL_NOT_LOADED",
    "message": "Speech recognition model is not loaded",
}

ERROR_NOT_STARTED: dict[str, Any] = {
    "type": "error",
    "code": "SPEECH_WS_NOT_STARTED",
    "message": "Send 'start' before streaming audio",
}

ERROR_ASR_EMPTY_RESULT: dict[str, Any] = {
    "type": "error",
    "code": "ASR_EMPTY_RESULT",
    "message": "No speech recognized in the audio",
}

# ── Constants ───────────────────────────────────────────────────────────────

MIN_SEAT_ID = 1
MAX_SEAT_ID = 10


# ── Handler ─────────────────────────────────────────────────────────────────


async def _send_error_and_close(
    ws: WebSocket, error_dict: dict[str, Any]
) -> None:
    """Send a JSON error message then close the WebSocket.

    Both operations are best-effort — exceptions are swallowed.
    """
    try:
        await ws.send_json(error_dict)
    except Exception:
        pass
    try:
        await ws.close(code=4000)
    except Exception:
        pass


async def handle_speech_ws(
    ws: WebSocket, meeting_id: int, seat_id: int
) -> None:
    """Handle a /ws/speech/{meeting_id} WebSocket connection.

    Args:
        ws: The FastAPI WebSocket object.
        meeting_id: Meeting ID from the URL path.
        seat_id: Seat ID from the ?seat= query parameter.
    """
    # ── 1. Accept ─────────────────────────────────────────────────────────
    await ws.accept()

    # ── 2. Validate seat range ────────────────────────────────────────────
    if seat_id < MIN_SEAT_ID or seat_id > MAX_SEAT_ID:
        await _send_error_and_close(ws, ERROR_SEAT_OUT_OF_RANGE)
        return

    # ── 3. Validate meeting + speaker seat ────────────────────────────────
    db = SessionLocal()
    try:
        active = MeetingService(db, event_bus).get_active_meeting()
        if active is None or active.id != meeting_id:
            await _send_error_and_close(ws, ERROR_MEETING_NOT_ACTIVE)
            return

        speaker = SeatRepository(db).get_speaker_seat()
        if speaker.seat_id != seat_id:
            await _send_error_and_close(ws, ERROR_NOT_SPEAKER_SEAT)
            return

        # ── 4. Create session ──────────────────────────────────────────────
        # Returns (session_key, session_token) for identity-safe cleanup.
        session_key, session_token = stream_service.create_session(
            meeting_id, seat_id,
        )

        # ── 5. Register in speech registry ─────────────────────────────────
        speech_registry.register(meeting_id, seat_id, ws)

        # ── 6. Message loop ────────────────────────────────────────────────
        try:
            while True:
                raw = await ws.receive()

                if raw["type"] == "websocket.disconnect":
                    logger.debug(
                        "Speech WS disconnect: meeting=%d seat=%d",
                        meeting_id, seat_id,
                    )
                    break

                # Phase 5: reject business messages on invalidated connections.
                # Invalidated means a newer connection replaced this one, or
                # the speaker seat was switched away. No further processing
                # is allowed — no ASR, no buffering, no persistence.
                if speech_registry.is_invalidated(ws):
                    logger.debug(
                        "Rejecting message on invalidated WS "
                        "(meeting=%d seat=%d)",
                        meeting_id, seat_id,
                    )
                    try:
                        await ws.send_json(ERROR_NOT_SPEAKER_SEAT)
                    except Exception:
                        pass
                    break

                if "text" in raw:
                    await _handle_text_message(
                        ws, raw["text"], meeting_id, seat_id, session_key,
                    )
                elif "bytes" in raw:
                    await _handle_binary_message(
                        ws, raw["bytes"], meeting_id, seat_id, session_key,
                    )

        except WebSocketDisconnect:
            logger.debug(
                "Speech WS WebSocketDisconnect: meeting=%d seat=%d",
                meeting_id, seat_id,
            )
        except Exception:
            logger.exception(
                "Speech WS error: meeting=%d seat=%d",
                meeting_id, seat_id,
            )
        finally:
            stream_service.remove_session(session_key, session_token)
            speech_registry.unregister(meeting_id, seat_id, ws)

    finally:
        db.close()


async def _handle_text_message(
    ws: WebSocket,
    text: str,
    meeting_id: int,
    seat_id: int,
    session_key: str,
) -> None:
    """Route an incoming text message based on its type field.

    Supported types:
        start    → generate utterance_id → stream_service.start_utterance() → send started
        end_hint → finalize buffered audio → TranslationService.process_final_array()
                   → persist → publish TranslationFinalEvent → broadcast
        cancel   → stream_service.cancel_utterance() → publish
                   TranslationInterimCancelledEvent
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(
            "Invalid JSON from speech WS (meeting=%d seat=%d): %s",
            meeting_id, seat_id, text[:200],
        )
        return

    msg_type = data.get("type", "")

    if msg_type == "start":
        utterance_id = stream_service.generate_utterance_id(
            meeting_id, seat_id,
        )

        # Phase 3: register utterance and reset SpeechModule for this session
        stream_service.start_utterance(session_key, utterance_id)

        await ws.send_json({
            "type": "started",
            "utterance_id": utterance_id,
            "session_key": session_key,
        })

        logger.info(
            "Speech start: meeting=%d seat=%d utterance=%s",
            meeting_id, seat_id, utterance_id,
        )

    elif msg_type == "end_hint":
        # Phase 4: finalize buffered PCM16 → offline ASR rescore → persist → broadcast
        finalized = stream_service.finalize_utterance(session_key)
        if finalized is None:
            logger.debug(
                "end_hint with no buffered audio (meeting=%d seat=%d)",
                meeting_id, seat_id,
            )
            return

        try:
            from backend.database import SessionLocal
            from backend.services.translation_service import TranslationService

            db = SessionLocal()
            try:
                tsvc = TranslationService(db, event_bus)
                record = tsvc.process_final_array(
                    audio=finalized["audio"],
                    sr=finalized["sr"],
                    meeting_id=finalized["meeting_id"],
                    seat_id=finalized["seat_id"],
                    utterance_id=finalized["utterance_id"],
                    source_type="speech_ws",
                )
                logger.info(
                    "Speech final: meeting=%d seat=%d utterance=%s record=%d",
                    meeting_id, seat_id, finalized["utterance_id"], record.id,
                )
            finally:
                db.close()
        except Exception as exc:
            # Map known exceptions to WS error responses
            exc_str = str(exc)
            if "ASR_EMPTY_RESULT" in exc_str or "empty text" in exc_str.lower():
                try:
                    await ws.send_json(ERROR_ASR_EMPTY_RESULT)
                except Exception:
                    pass
            elif "model not loaded" in exc_str.lower() or "speech module" in exc_str.lower():
                try:
                    await ws.send_json(ERROR_MODEL_NOT_LOADED)
                except Exception:
                    pass
            else:
                logger.exception(
                    "Finalize error (meeting=%d seat=%d): %s",
                    meeting_id, seat_id, exc,
                )
                try:
                    await ws.send_json({
                        "type": "error",
                        "code": "TRANSLATION_FAILED",
                        "message": str(exc),
                    })
                except Exception:
                    pass

    elif msg_type == "cancel":
        # Phase 3: cancel current utterance and broadcast cancelled event
        cancelled_uid = stream_service.cancel_utterance(session_key)

        if cancelled_uid:
            event_bus.publish(TranslationInterimCancelledEvent(
                meeting_id=meeting_id,
                payload={
                    "utterance_id": cancelled_uid,
                    "seat_id": seat_id,
                    "reason": "user_cancelled",
                },
            ))

        logger.info(
            "Speech cancel: meeting=%d seat=%d utterance=%s",
            meeting_id, seat_id, cancelled_uid,
        )

    else:
        logger.warning(
            "Unknown speech WS message type '%s' from meeting=%d seat=%d",
            msg_type, meeting_id, seat_id,
        )


async def _handle_binary_message(
    ws: WebSocket,
    data: bytes,
    meeting_id: int,
    seat_id: int,
    session_key: str,
) -> None:
    """Handle a PCM16 binary frame.

    Phase 3 flow:
        1. stream_service.process_pcm_frame() converts bytes → float32,
           runs SpeechModule.process_interim_array(), increments revision.
        2. If models are not loaded, sends MODEL_NOT_LOADED error.
        3. If ASR returns text, publishes TranslationInterimEvent via EventBus.
        4. No response is sent on the speech WS for successful processing
           (interim is broadcast on /ws/{meeting_id} instead).

    Phase 5 fix:
        Before any processing, guard against binary frames received before
        'start'. If no active utterance (current_utterance_id is None),
        send SPEECH_WS_NOT_STARTED error and return. No audio is buffered,
        no ASR is run, and no final is generated.

    Per WEBSOCKET_PROTOCOL §9: speech business logic belongs in the service.
    This handler only coordinates: receive → service → EventBus.
    """
    # Phase 5: require active utterance (client must send 'start' first)
    session = stream_service.get_session(session_key)
    if session is None or session.current_utterance_id is None:
        logger.debug(
            "Binary frame dropped — no active utterance (meeting=%d seat=%d)",
            meeting_id, seat_id,
        )
        try:
            await ws.send_json(ERROR_NOT_STARTED)
        except Exception:
            pass
        return

    try:
        result = stream_service.process_pcm_frame(session_key, data)
    except RuntimeError as exc:
        logger.warning(
            "Binary frame error (meeting=%d seat=%d): %s",
            meeting_id, seat_id, exc,
        )
        try:
            await ws.send_json({
                "type": "error",
                "code": "MODEL_NOT_LOADED",
                "message": str(exc),
            })
        except Exception:
            pass
        return

    # No active utterance — client should send 'start' first
    if result["utterance_id"] is None:
        logger.debug(
            "Binary frame dropped — no active utterance (meeting=%d seat=%d)",
            meeting_id, seat_id,
        )
        return

    # Publish interim event (skip empty ASR results)
    source_text: str = result.get("source_text", "")
    if not source_text:
        return

    event_bus.publish(TranslationInterimEvent(
        meeting_id=meeting_id,
        payload={
            "utterance_id": result["utterance_id"],
            "seat_id": seat_id,
            "revision": result["revision"],
            "source_lang": "zh",
            "target_lang": "en",
            "source_text": source_text,
            "translated_text": "",
            "is_final": False,
        },
    ))
