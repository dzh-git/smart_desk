"""
Translation router — thin FastAPI wrapper around speech_module.
Handles: HTTP endpoints, WS broadcast, transcript history, speaker seat.
Delegates: STT, MT, language detection, audio loading → speech_module.
"""
from __future__ import annotations
import asyncio
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, UploadFile, File, Form, Query
from pydantic import BaseModel

from backend.schemas import TranslationRequest, TranslationOut
from backend.services.desk_coordinator import desk
from speech_module import SpeechModule
from speech_module.mt_engine import MTEngine
from speech_module.history_store import HistoryStore
from speech_module.text_utils import text_similarity

router = APIRouter(prefix="/api/translate", tags=["translation"])

# Singleton speech module + history store (file-persisted, survives restarts)
history_store = HistoryStore("speech_history.db")
mt_engine = MTEngine(device="cpu")
speech = SpeechModule(max_workers=4, history_store=history_store, mt_engine=mt_engine)
_executor = ThreadPoolExecutor(max_workers=4)
_pending_sema = threading.Semaphore(4)
_preloading = False

# ── App-level state (not in speech_module — these depend on meeting context) ──

class SpeakerSeatRequest(BaseModel):
    meeting_id: int
    seat_id: int  # 0 = clear

_speaker_seats: dict[int, int] = {}


# ── Preload ──

async def preload_models():
    """Preload STT models in background. Idempotent."""
    global _preloading
    if speech.ready:
        return
    _preloading = True
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(_executor, speech.preload)
    except Exception as e:
        print(f"[preload] Failed: {e}")
    finally:
        _preloading = False


@router.post("/preload")
async def preload():
    await preload_models()
    return {"ok": True, "ready": speech.ready}


@router.get("/preload/status")
def preload_status():
    return {"ready": speech.ready, "loading": _preloading}


# ── Transcript history ──

@router.get("/history")
def get_history(meeting_id: int = Query(...)):
    """Query translation history from persistent HistoryStore."""
    rows = speech.get_history(meeting_id, limit=500)
    entries = []
    for row in rows:
        try:
            ts = time.mktime(time.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S"))
        except (ValueError, TypeError):
            ts = time.time()
        entries.append({
            "id": row["segment_id"],
            "zh": row["zh_text"],
            "en": row["en_text"],
            "seat_id": row["seat_id"],
            "ts": ts,
        })
    return {"meeting_id": meeting_id, "entries": entries}


@router.delete("/history")
def clear_history(meeting_id: int = Query(...)):
    """Delete all history records for a meeting."""
    conn = history_store._get_conn()
    conn.execute("DELETE FROM translation_history WHERE meeting_id = ?", (meeting_id,))
    conn.commit()
    return {"ok": True}


# ── Speaker seat ──

@router.post("/speaker-seat")
async def set_speaker_seat(data: SpeakerSeatRequest):
    if data.seat_id == 0:
        _speaker_seats.pop(data.meeting_id, None)
        await desk.on_speaker_clear(data.meeting_id)
        return {"ok": True, "meeting_id": data.meeting_id, "speaker_seat": None}
    _speaker_seats[data.meeting_id] = data.seat_id
    await desk.on_speaker_seat(data.meeting_id, data.seat_id)
    return {"ok": True, "meeting_id": data.meeting_id, "speaker_seat": data.seat_id}


@router.get("/speaker-seat")
def get_speaker_seat(meeting_id: int):
    seat_id = _speaker_seats.get(meeting_id)
    return {"meeting_id": meeting_id, "speaker_seat": seat_id}


# ── Text translation ──

@router.post("", response_model=TranslationOut)
async def translate(data: TranslationRequest):
    text = data.text.strip()
    zh, en = speech.translate_text(text)
    return TranslationOut(
        original=zh, translated=en,
        source_lang="auto", target_lang="auto",
    )


# ── Audio upload (STT + translation) ──

@router.post("/audio")
async def transcribe_audio(
    meeting_id: int = Form(...),
    seat_id: int = Form(...),
    final: bool = Form(True),
    utterance_id: int = Form(0),
    audio: UploadFile = File(...),
):
    """
    Receive audio → STT → translate (only if final) → broadcast (only if final).

    interim (final=false): Streaming ASR via Paraformer Streaming + SentenceMerger.
    final   (final=true):  Offline rescore via Paraformer-large → translate → record → broadcast.
    """
    if not speech.ready:
        return {"zh": "", "en": "", "final": final, "ready": False}

    acquired = _pending_sema.acquire(blocking=final)
    if not acquired:
        return {"zh": "", "en": "", "final": False, "skipped": True}

    suffix = os.path.splitext(audio.filename or "recording.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    try:
        loop = asyncio.get_running_loop()
        session_key = f"{meeting_id}_{seat_id}"

        # Detect utterance boundary via utterance_id increment → reset SentenceMerger
        _utt_state = speech._sessions.get(session_key)
        _last_utt = _utt_state.get("_last_utterance_id", -1) if _utt_state else -1
        if _last_utt != -1 and utterance_id != _last_utt:
            speech.start_utterance(session_key)

        if final:
            try:
                # Offline full-context rescore for best quality on complete utterance
                zh_text = await loop.run_in_executor(
                    _executor, speech.transcribe, tmp_path
                )

                if not zh_text or zh_text == "[无法识别语音]":
                    speech.reset_interim(session_key)
                    return {"zh": zh_text or "", "en": "", "final": True,
                            "segment_id": 0, "seat_id": seat_id}

                zh, en = speech.translate_text(zh_text)

                # Dedup against last entry for this meeting+seat
                existing = speech.get_history(meeting_id, seat_id, limit=1)
                if existing and text_similarity(existing[0].get("zh_text", ""), zh) > 0.8:
                    seg_id = existing[0]["segment_id"]
                else:
                    seg_id = speech.get_next_segment_id(meeting_id, seat_id)

                history_store.upsert(
                    meeting_id=meeting_id, seat_id=seat_id,
                    segment_id=seg_id, zh_text=zh, en_text=en, is_final=True,
                )

                await desk.on_translation_result(meeting_id, zh, en, seat_id, seg_id)
                speech.reset_interim(session_key)

                return {"zh": zh, "en": en, "final": True,
                        "segment_id": seg_id, "seat_id": seat_id}
            except Exception as e:
                print(f"[transcribe] Error processing final audio: {e}")
                speech.reset_interim(session_key)
                return {"zh": "", "en": "", "final": True, "error": str(e),
                        "segment_id": 0, "seat_id": seat_id}

        else:
            try:
                # Track utterance_id for boundary detection
                if speech._sessions.get(session_key):
                    speech._sessions[session_key]["_last_utterance_id"] = utterance_id
                # Streaming ASR → SentenceMerger handles accumulation + sentence boundary
                accumulated = await loop.run_in_executor(
                    _executor, speech.process_interim_chunk, tmp_path, session_key
                )
                return {"zh": accumulated, "en": "", "final": False}
            except Exception as e:
                print(f"[transcribe] Error processing interim audio: {e}")
                return {"zh": "", "en": "", "final": False, "error": str(e)}

    finally:
        _pending_sema.release()
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
