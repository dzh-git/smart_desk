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

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from backend.database import SessionLocal
from backend.events import event_bus
from backend.events.translation_events import (
    TranslationFinalEvent,
    TranslationFinalizingEvent,
    TranslationInterimCancelledEvent,
    TranslationInterimEvent,
    TranslationSentenceEvent,
)
from backend.repositories.seat_repository import SeatRepository
from backend.repositories.translation_repository import TranslationRepository
from backend.services.meeting_service import MeetingService
from backend.services.interim_translation_service import (
    EnglishSentenceCorrectionJob,
    SentenceTranslationJob,
    english_sentence_correction_service,
    sentence_translation_service,
)
from backend.services.speech_finalization_service import (
    SpeechFinalizationJob,
    finalization_queue,
)
from backend.services.speech_stream_service import stream_service
from backend.websocket.speech_registry import speech_registry
from backend.websocket.speech_trace import trace
from backend.speech_module.text_utils import detect_language

logger = logging.getLogger(__name__)

# Streaming ASR is CPU-bound and must never run on FastAPI's event-loop
# thread. There is only one active speaker, so one ordered worker preserves
# model/session safety while keeping WebSocket receive and broadcasts alive.
_streaming_asr_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="smartdesk-streaming-asr",
)

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

ERROR_INVALID_LANGUAGE_MODE: dict[str, Any] = {
    "type": "error",
    "code": "INVALID_LANGUAGE_MODE",
    "message": "language_mode must be one of: auto, zh, en",
}

# ── Constants ───────────────────────────────────────────────────────────────

MIN_SEAT_ID = 1
MAX_SEAT_ID = 9


# ── Session replacement ─────────────────────────────────────────────────────

def _cancel_replaced_session(meeting_id: int, seat_id: int) -> str | None:
    """Cancel and broadcast the utterance owned by an older connection."""
    session_key = f"speech_{meeting_id}_{seat_id}"
    session = stream_service.get_session(session_key)
    if session is None or session.current_utterance_id is None:
        return None

    cancelled_uid = stream_service.cancel_utterance(session_key)
    if cancelled_uid:
        event_bus.publish(TranslationInterimCancelledEvent(
            meeting_id=meeting_id,
            payload={
                "utterance_id": cancelled_uid,
                "seat_id": seat_id,
                "reason": "session_replaced",
            },
        ))
    return cancelled_uid


def _publish_completed_sentences(
    *,
    meeting_id: int,
    seat_id: int,
    utterance_id: str,
    revision: int,
    completed_sentences: list[dict[str, Any]],
    source_lang: str = "unknown",
) -> None:
    """Broadcast and enqueue every newly committed semantic sentence."""
    for sentence in completed_sentences:
        source_text = str(sentence.get("source_text") or "").strip()
        sentence_id = str(sentence.get("sentence_id") or "")
        if not source_text or not sentence_id:
            continue
        sequence = int(sentence.get("sentence_sequence") or 0)
        sentence_source_lang = (
            source_lang
            if source_lang in {"zh", "en"}
            else detect_language(source_text)
        )
        target_lang = "en" if sentence_source_lang == "zh" else "zh"
        requires_english_correction = bool(
            sentence_source_lang == "en"
            and sentence.get("requires_english_correction")
        )
        if requires_english_correction:
            # The visible raw Zipformer sentence is deliberately published
            # once.  SenseVoice may replace it once with punctuation/casing;
            # the frontend then locks its source text forever.
            event_bus.publish(TranslationSentenceEvent(
                meeting_id=meeting_id,
                payload={
                    "utterance_id": utterance_id,
                    "sentence_id": sentence_id,
                    "sentence_sequence": sequence,
                    "seat_id": seat_id,
                    "revision": revision,
                    "source_lang": "en",
                    "target_lang": "zh",
                    "source_text": source_text,
                    "translated_text": "",
                    "translation_status": "pending",
                    "recognition_status": "correcting",
                    "source_locked": False,
                    "is_final": False,
                },
            ))
            audio = sentence.get("audio")
            if audio is not None:
                english_sentence_correction_service.submit(
                    EnglishSentenceCorrectionJob(
                        meeting_id=meeting_id,
                        seat_id=seat_id,
                        utterance_id=utterance_id,
                        sentence_id=sentence_id,
                        sentence_sequence=sequence,
                        revision=revision,
                        source_text=source_text,
                        audio=audio,
                    ),
                )
            continue
        job = SentenceTranslationJob(
            meeting_id=meeting_id,
            seat_id=seat_id,
            utterance_id=utterance_id,
            sentence_id=sentence_id,
            sentence_sequence=sequence,
            revision=revision,
            source_lang=sentence_source_lang,
            target_lang=target_lang,
            source_text=source_text,
            recognition_status=str(sentence.get("recognition_status") or "ok"),
            source_locked=bool(sentence.get("source_locked", True)),
        )
        trace(
            "sentence_completed_at",
            utterance_id=utterance_id,
            meeting_id=meeting_id,
            seat_id=seat_id,
            sentence_id=sentence_id,
            sentence_sequence=sequence,
            revision=revision,
            source_text_len=len(source_text),
        )
        event_bus.publish(TranslationSentenceEvent(
            meeting_id=meeting_id,
            payload={
                "utterance_id": utterance_id,
                "sentence_id": sentence_id,
                "sentence_sequence": sequence,
                "seat_id": seat_id,
                "revision": revision,
                "source_lang": sentence_source_lang,
                "target_lang": target_lang,
                "source_text": source_text,
                "translated_text": "",
                "translation_status": "pending",
                "recognition_status": job.recognition_status,
                "source_locked": job.source_locked,
                "is_final": False,
            },
        ))
        trace(
            "sentence_pending_broadcast_at",
            utterance_id=utterance_id,
            meeting_id=meeting_id,
            seat_id=seat_id,
            sentence_id=sentence_id,
            sentence_sequence=sequence,
            revision=revision,
        )
        sentence_translation_service.submit(job)


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

        # ── 4. Restore sequence and replace any older session ─────────────
        persisted_sequence = TranslationRepository(db).max_utterance_sequence(
            meeting_id, seat_id,
        )
        stream_service.seed_utterance_sequence(
            meeting_id, seat_id, persisted_sequence,
        )
        _cancel_replaced_session(meeting_id, seat_id)

        # ── 5. Create session ──────────────────────────────────────────────
        # Returns (session_key, session_token) for identity-safe cleanup.
        session_key, session_token = stream_service.create_session(
            meeting_id, seat_id,
        )

        # ── 6. Register in speech registry ─────────────────────────────────
        speech_registry.register(meeting_id, seat_id, ws)

        # ── 7. Message loop ────────────────────────────────────────────────
        # Receive PCM independently from CPU inference. The bounded queue
        # provides backpressure rather than silently dropping speech.
        pcm_queue: asyncio.Queue[tuple[bytes, int, float]] = asyncio.Queue(
            maxsize=50,
        )
        receive_frame_index = 0

        async def process_pcm_queue() -> None:
            while True:
                data, frame_index, queued_at = await pcm_queue.get()
                try:
                    queue_wait_ms = round(
                        (time.perf_counter() - queued_at) * 1000
                    )
                    stream_service.update_pcm_queue(
                        session_key,
                        pcm_queue.qsize(),
                    )
                    trace(
                        "backend_pcm_dequeued_at",
                        session_key=session_key,
                        meeting_id=meeting_id,
                        seat_id=seat_id,
                        frame_index=frame_index,
                        queue_wait_ms=queue_wait_ms,
                        pcm_queue_frames=pcm_queue.qsize(),
                    )
                    await _handle_binary_message(
                        ws,
                        data,
                        meeting_id,
                        seat_id,
                        session_key,
                        frame_index=frame_index,
                        queue_wait_ms=queue_wait_ms,
                    )
                finally:
                    pcm_queue.task_done()
                    stream_service.update_pcm_queue(
                        session_key,
                        pcm_queue.qsize(),
                    )

        pcm_worker = asyncio.create_task(process_pcm_queue())
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
                    try:
                        message_data = json.loads(raw["text"])
                    except (TypeError, json.JSONDecodeError):
                        message_data = {}
                    message_type = message_data.get("type")
                    if message_type == "end_hint":
                        await pcm_queue.join()
                    elif message_type == "cancel":
                        while not pcm_queue.empty():
                            try:
                                pcm_queue.get_nowait()
                                pcm_queue.task_done()
                            except asyncio.QueueEmpty:
                                break
                        # A frame already inside native inference cannot be
                        # interrupted safely. Wait for that one frame before
                        # resetting model/session state; queued frames are gone.
                        await pcm_queue.join()
                        stream_service.update_pcm_queue(session_key, 0)
                    await _handle_text_message(
                        ws, raw["text"], meeting_id, seat_id, session_key,
                    )
                elif "bytes" in raw:
                    receive_frame_index += 1
                    queued_at = time.perf_counter()
                    current_session = stream_service.get_session(session_key)
                    trace(
                        "backend_pcm_received_at",
                        session_key=session_key,
                        utterance_id=(
                            current_session.current_utterance_id
                            if current_session else None
                        ),
                        meeting_id=meeting_id,
                        seat_id=seat_id,
                        size_bytes=len(raw["bytes"]),
                        frame_index=receive_frame_index,
                    )
                    await pcm_queue.put(
                        (raw["bytes"], receive_frame_index, queued_at),
                    )
                    stream_service.update_pcm_queue(
                        session_key,
                        pcm_queue.qsize(),
                    )
                    trace(
                        "backend_pcm_queued_at",
                        session_key=session_key,
                        meeting_id=meeting_id,
                        seat_id=seat_id,
                        frame_index=receive_frame_index,
                        pcm_queue_frames=pcm_queue.qsize(),
                        audio_backlog_ms=pcm_queue.qsize() * 100,
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
            pcm_worker.cancel()
            try:
                await pcm_worker
            except asyncio.CancelledError:
                pass
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
        language_mode = str(data.get("language_mode") or "auto").strip().lower()
        if language_mode not in {"auto", "zh", "en"}:
            await ws.send_json(ERROR_INVALID_LANGUAGE_MODE)
            return
        utterance_id = stream_service.generate_utterance_id(
            meeting_id, seat_id,
        )

        # Phase 3: register utterance and reset SpeechModule for this session
        stream_service.start_utterance(
            session_key,
            utterance_id,
            language_mode=language_mode,
        )

        trace("utterance_started_at", utterance_id=utterance_id,
              meeting_id=meeting_id, seat_id=seat_id)

        await ws.send_json({
            "type": "started",
            "utterance_id": utterance_id,
            "session_key": session_key,
            "language_mode": language_mode,
        })

        logger.info(
            "Speech start: meeting=%d seat=%d utterance=%s",
            meeting_id, seat_id, utterance_id,
        )

    elif msg_type == "end_hint":
        # Queue the same bilingual sentence-final pipeline used by VAD rollover.
        loop = asyncio.get_running_loop()
        finalized = await loop.run_in_executor(
            _streaming_asr_executor,
            stream_service.finalize_utterance,
            session_key,
        )
        if finalized is None:
            logger.debug(
                "end_hint with no buffered audio (meeting=%d seat=%d)",
                meeting_id, seat_id,
            )
            return

        trace("end_hint_received_at",
              utterance_id=finalized.get("utterance_id"),
              meeting_id=meeting_id, seat_id=seat_id,
              buffer_duration_ms=(
                  len(finalized.get("audio", [])) / 16
                  if "audio" in finalized else 0
              ))

        utterance_id = str(finalized["utterance_id"])
        fallback_text = str(finalized.get("source_text") or "").strip()
        session = stream_service.get_session(session_key)
        sentence_result = stream_service.complete_active_sentence(
            session_key,
            fallback_text,
            "end_hint",
        )
        _publish_completed_sentences(
            meeting_id=meeting_id,
            seat_id=seat_id,
            utterance_id=utterance_id,
            revision=session.revision if session is not None else 0,
            completed_sentences=list(
                sentence_result.get("completed_sentences") or [],
            ),
            source_lang=str(finalized.get("detected_language") or "unknown"),
        )
        stream_service.reset_caption_formatter(session_key)
        stream_service.mark_utterance_terminal(session_key, utterance_id)
        event_bus.publish(TranslationFinalizingEvent(
            meeting_id=meeting_id,
            payload={
                "utterance_id": utterance_id,
                "seat_id": seat_id,
                "source_text": fallback_text,
                "source_lang": "unknown",
                "target_lang": "unknown",
                "boundary_reason": "end_hint",
            },
        ))
        finalization_queue.submit(SpeechFinalizationJob(
            meeting_id=meeting_id,
            seat_id=seat_id,
            utterance_id=utterance_id,
            source_text=fallback_text,
            boundary_reason="end_hint",
            audio_seconds=float(finalized.get("audio_seconds") or 0.0),
            audio=finalized["audio"],
            sample_rate=int(finalized["sr"]),
            recognized_text=str(finalized.get("recognized_text") or ""),
            detected_language=str(finalized.get("detected_language") or "unknown"),
            recognition_engine=str(finalized.get("recognition_engine") or "unknown"),
            recognition_status=str(finalized.get("recognition_status") or "ok"),
        ))

    elif msg_type == "cancel":
        # Phase 3: cancel current utterance and broadcast cancelled event
        cancelled_uid = stream_service.cancel_utterance(session_key)

        if cancelled_uid:
            trace("cancel_event_created_at",
                  utterance_id=cancelled_uid, meeting_id=meeting_id,
                  seat_id=seat_id)
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
    *,
    frame_index: int | None = None,
    queue_wait_ms: int = 0,
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

    if frame_index is None:
        frame_index = session.pcm_frames_received + 1
        trace("backend_pcm_received_at", session_key=session_key,
              utterance_id=session.current_utterance_id,
              meeting_id=meeting_id, seat_id=seat_id, size_bytes=len(data),
              frame_index=frame_index)

    trace("backend_process_pcm_start_at",
          utterance_id=session.current_utterance_id,
          meeting_id=meeting_id, seat_id=seat_id)
    try:
        loop = asyncio.get_running_loop()
        processing_started = time.perf_counter()
        result = await loop.run_in_executor(
            _streaming_asr_executor,
            stream_service.process_pcm_frame,
            session_key,
            data,
        )
        processing_ms = round((time.perf_counter() - processing_started) * 1000)
        current_session = stream_service.get_session(session_key)
        if current_session is not None:
            current_session.processed_frames += 1
            current_session.last_processing_ms = processing_ms
            current_session.peak_processing_ms = max(
                current_session.peak_processing_ms,
                processing_ms,
            )
        trace(
            "backend_process_pcm_end_at",
            utterance_id=session.current_utterance_id,
            meeting_id=meeting_id,
            seat_id=seat_id,
            frame_index=frame_index,
            processing_ms=processing_ms,
            queue_wait_ms=queue_wait_ms,
            audio_backlog_ms=(
                current_session.audio_backlog_ms
                if current_session else 0
            ),
            slower_than_realtime=processing_ms > 100,
        )
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
    if source_text:
        source_lang = str(result.get("source_lang") or "unknown")
        if source_lang not in {"zh", "en"}:
            source_lang = detect_language(source_text)
        target_lang = "en" if source_lang == "zh" else "zh"
        # Phase 02: build payload with two-line caption
        payload: dict[str, Any] = {
            "utterance_id": result["utterance_id"],
            "seat_id": seat_id,
            "revision": result["revision"],
            "source_lang": source_lang,
            "target_lang": target_lang,
            "source_text": source_text,
            "translation_source_text": result.get("sentence_source_text", ""),
            "translated_text": "",
            "sentence_id": result.get("sentence_id"),
            "sentence_sequence": result.get("sentence_sequence", 0),
            "sentence_source_text": result.get("sentence_source_text", ""),
            "sentence_state": result.get("sentence_state", "forming"),
            "is_final": False,
            "requested_language": result.get("requested_language", "auto"),
            "detected_language": result.get("detected_language", source_lang),
            "recognition_engine": result.get("recognition_engine", "unknown"),
        }
        if "caption" in result:
            payload["caption"] = result["caption"]

        trace("interim_event_created_at",
              utterance_id=result["utterance_id"],
              meeting_id=meeting_id, seat_id=seat_id,
              revision=result["revision"],
              source_text_len=len(source_text))

        event_bus.publish(TranslationInterimEvent(
            meeting_id=meeting_id,
            payload=payload,
        ))
        _publish_completed_sentences(
            meeting_id=meeting_id,
            seat_id=seat_id,
            utterance_id=str(result["utterance_id"]),
            revision=int(result["revision"]),
            completed_sentences=list(result.get("completed_sentences") or []),
            source_lang=source_lang,
        )

        trace("interim_event_broadcast_at",
              utterance_id=result["utterance_id"],
              meeting_id=meeting_id, seat_id=seat_id,
              revision=result["revision"])

    # ── Non-blocking automatic rollover ───────────────────────────────────
    if result.get("vad_should_finalize"):
        boundary_reason = str(result.get("boundary_reason") or "vad_boundary")
        finalized = stream_service.snapshot_auto_finalization(
            session_key,
            source_text,
            boundary_reason,
        )
        new_uid = stream_service.prepare_next_utterance(
            session_key,
            meeting_id,
            seat_id,
            continuous_rollover=bool(
                finalized and finalized.get("continuous_rollover")
            ),
        )
        if new_uid:
            try:
                await ws.send_json({
                    "type": "utterance_started",
                    "utterance_id": new_uid,
                })
            except Exception:
                pass

        if finalized is None:
            return

        old_uid = str(finalized["utterance_id"])
        final_text = str(finalized["source_text"]).strip()
        if not finalized["has_speech"] or len(finalized.get("audio", [])) == 0:
            event_bus.publish(TranslationInterimCancelledEvent(
                meeting_id=meeting_id,
                payload={
                    "utterance_id": old_uid,
                    "seat_id": seat_id,
                    "reason": "asr_empty_result",
                },
            ))
            return

        event_bus.publish(TranslationFinalizingEvent(
            meeting_id=meeting_id,
            payload={
                "utterance_id": old_uid,
                "seat_id": seat_id,
                "source_text": final_text,
                "source_lang": "unknown",
                "target_lang": "unknown",
                "boundary_reason": boundary_reason,
                "next_utterance_id": new_uid,
                "caption": finalized.get("caption"),
                "rollover_overlap_ms": finalized.get("rollover_overlap_ms", 0),
            },
        ))
        queued = finalization_queue.submit(SpeechFinalizationJob(
            meeting_id=meeting_id,
            seat_id=seat_id,
            utterance_id=old_uid,
            source_text=final_text,
            boundary_reason=boundary_reason,
            audio_seconds=float(finalized["audio_seconds"]),
            next_utterance_id=new_uid,
            audio=finalized["audio"],
            sample_rate=int(finalized["sr"]),
            recognized_text=str(finalized.get("recognized_text") or ""),
            detected_language=str(finalized.get("detected_language") or "unknown"),
            recognition_engine=str(finalized.get("recognition_engine") or "unknown"),
            recognition_status=str(finalized.get("recognition_status") or "ok"),
        ))
        logger.info(
            "Speech auto-final queued: utterance=%s reason=%s text_len=%d "
            "audio_seconds=%.2f overlap_frames=%d queue_depth=%d next=%s queued=%s",
            old_uid,
            boundary_reason,
            len(final_text),
            finalized["audio_seconds"],
            finalized.get("rollover_overlap_frames", 0),
            finalization_queue.pending_count,
            new_uid,
            queued,
        )
