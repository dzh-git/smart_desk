# backend/routers/translation.py
from __future__ import annotations
import asyncio
import atexit
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException
from pydantic import BaseModel

from backend.database import SessionLocal
from backend.repositories.translation_repository import TranslationRepository
from backend.services.background_tasks import get_logger
from backend.services.event_bus import event_bus
from backend.services.translation_service import TranslationService
from backend.utils import _ok
from speech_module import SpeechModule
from speech_module.mt_engine import MTEngine

router = APIRouter(prefix="/api/translations", tags=["translations"])

# Singletons
_mt_engine = MTEngine(device="cpu")
_speech = SpeechModule(max_workers=4, mt_engine=_mt_engine)
_executor = ThreadPoolExecutor(max_workers=4)
atexit.register(_executor.shutdown, wait=True)
_pending_sema = threading.Semaphore(4)
_preloading = False
_preload_error: str | None = None


class TextTranslateRequest(BaseModel):
    text: str


async def _preload_models():
    global _preloading, _preload_error
    if _speech.ready or _preloading:
        return
    loop = asyncio.get_running_loop()
    _preloading = True
    _preload_error = None
    try:
        await loop.run_in_executor(_executor, _speech.preload)
    except Exception as e:
        _preload_error = str(e)
        get_logger().exception("Preload failed")
    finally:
        _preloading = False


def _start_background_preload() -> bool:
    """Start model preload in a daemon thread; return True if a new job started."""
    global _preloading, _preload_error
    if _speech.ready or _preloading:
        return False
    _preloading = True
    _preload_error = None

    def _run():
        global _preloading, _preload_error
        try:
            _speech.preload()
        except Exception as e:
            _preload_error = str(e)
            get_logger().exception("Preload failed")
        finally:
            _preloading = False

    threading.Thread(target=_run, daemon=True).start()
    return True


@router.post("/preload")
async def preload():
    _start_background_preload()
    return _ok({"ready": _speech.ready, "loading": _preloading, "error": _preload_error})


@router.get("/preload/status")
def preload_status():
    return _ok({"ready": _speech.ready, "loading": _preloading, "error": _preload_error})


@router.post("")
def translate_text(data: TextTranslateRequest):
    zh, en = _speech.translate_text(data.text.strip())
    return _ok({"zh": zh, "en": en})


@router.get("")
def get_history(meeting_id: int = Query(...)):
    db = SessionLocal()
    try:
        repo = TranslationRepository(db)
        rows = repo.list_by_meeting(meeting_id, limit=500)
        entries = [{"id": r.id, "zh": r.source_text, "en": r.translated_text,
                     "seat_id": r.seat_id, "ts": r.created_at.timestamp()}
                   for r in rows]
        return _ok(entries)
    finally:
        db.close()


@router.delete("")
def delete_history(meeting_id: int = Query(...)):
    db = SessionLocal()
    try:
        repo = TranslationRepository(db)
        count = repo.delete_by_meeting(meeting_id)
        return _ok({"deleted": count})
    finally:
        db.close()


@router.post("/audio")
async def transcribe_audio(
    meeting_id: int = Form(...),
    seat_id: int = Form(...),
    final: bool = Form(True),
    utterance_id: int = Form(0),
    audio: UploadFile = File(...),
):
    if not _speech.ready:
        return _ok({"zh": "", "en": "", "final": final, "ready": False})

    acquired = _pending_sema.acquire(blocking=final)
    if not acquired:
        return _ok({"zh": "", "en": "", "final": False, "skipped": True})

    tmp_path = None
    try:
        suffix = os.path.splitext(audio.filename or "recording.wav")[1] or ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            tmp.write(await audio.read())

        loop = asyncio.get_running_loop()
        session_key = f"{meeting_id}_{seat_id}"

        _last_utt = _speech.get_last_utterance_id(session_key)
        if _last_utt != -1 and utterance_id != _last_utt:
            _speech.start_utterance(session_key)

        if final:
            zh_text = await loop.run_in_executor(_executor, _speech.transcribe, tmp_path)
            if not zh_text or zh_text == "[无法识别语音]":
                _speech.reset_interim(session_key)
                return _ok({"zh": zh_text or "", "en": "", "final": True, "seat_id": seat_id})

            zh, en = _speech.translate_text(zh_text)
            _speech.reset_interim(session_key)

            # Persist via TranslationService
            db = SessionLocal()
            try:
                repo = TranslationRepository(db)
                ts_svc = TranslationService(db, event_bus, repo, _speech, _mt_engine)
                ts_svc.on_translation_final(meeting_id, seat_id, zh, en, segment_id=0)
            finally:
                db.close()

            return _ok({"zh": zh, "en": en, "final": True, "seat_id": seat_id})
        else:
            _speech.set_last_utterance_id(session_key, utterance_id)
            accumulated = await loop.run_in_executor(
                _executor, _speech.process_interim_chunk, tmp_path, session_key
            )
            return _ok({"zh": accumulated, "en": "", "final": False})

    except Exception:
        get_logger().exception("Audio transcription failed")
        raise HTTPException(status_code=500, detail="Audio transcription failed")
    finally:
        _pending_sema.release()
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ── EventBus subscription: auto-preload on meeting_started (spec Q22) ──

def _on_meeting_started_for_preload(event):
    """When meeting_started fires, trigger model preload in a background thread.

    Runs preload in a daemon thread rather than relying on asyncio, since
    EventBus handlers are called synchronously in the publishing thread
    (which may be a threadpool worker with no event loop — e.g., sync
    FastAPI endpoints).
    """
    _start_background_preload()


event_bus.subscribe("meeting_started", _on_meeting_started_for_preload)
