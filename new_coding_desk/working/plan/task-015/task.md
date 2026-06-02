# Task 015: Refactor Translation Router + New Dashboard Router

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Refactor `backend/routers/translation.py` to use `TranslationService`, rename API paths from `/api/translate/*` to `/api/translations/*` (migration B1), use unified response format. Remove `_speaker_seats` dict (now in DB). Also create `dashboard.py` router using `DashboardService`.

This is Task 15 of 26.

---

**Files:**
- Modify: `D:\learning\smart_desktop\smart-desk\backend\routers\translation.py`
- Create: `D:\learning\smart_desktop\smart-desk\backend\routers\dashboard.py`
- Modify: `D:\learning\smart_desktop\smart-desk\backend\main.py` (router registration)

- [ ] **Step 1: Rewrite translation.py with new paths**

```python
# backend/routers/translation.py
from __future__ import annotations
import asyncio
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, UploadFile, File, Form, Query
from pydantic import BaseModel

from backend.database import SessionLocal
from backend.repositories.translation_repository import TranslationRepository
from backend.services.event_bus import event_bus
from backend.services.translation_service import TranslationService
from speech_module import SpeechModule
from speech_module.mt_engine import MTEngine

router = APIRouter(prefix="/api/translations", tags=["translations"])

# Singletons
_mt_engine = MTEngine(device="cpu")
_speech = SpeechModule(max_workers=4, mt_engine=_mt_engine)
ts = TranslationService(None, event_bus, None, _speech, _mt_engine)
_executor = ThreadPoolExecutor(max_workers=4)
_pending_sema = threading.Semaphore(4)
_preloading = False


class TextTranslateRequest(BaseModel):
    text: str


def _ok(data):
    return {"success": True, "message": "OK", "data": data}


async def _preload_models():
    global _preloading
    if _speech.ready:
        return
    _preloading = True
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(_executor, _speech.preload)
    except Exception as e:
        print(f"[preload] Failed: {e}")
    finally:
        _preloading = False


@router.post("/preload")
async def preload():
    await _preload_models()
    return _ok({"ready": _speech.ready})


@router.get("/preload/status")
def preload_status():
    return _ok({"ready": _speech.ready, "loading": _preloading})


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

    suffix = os.path.splitext(audio.filename or "recording.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    try:
        loop = asyncio.get_running_loop()
        session_key = f"{meeting_id}_{seat_id}"

        _utt_state = _speech._sessions.get(session_key)
        _last_utt = _utt_state.get("_last_utterance_id", -1) if _utt_state else -1
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
            if _speech._sessions.get(session_key):
                _speech._sessions[session_key]["_last_utterance_id"] = utterance_id
            accumulated = await loop.run_in_executor(
                _executor, _speech.process_interim_chunk, tmp_path, session_key
            )
            return _ok({"zh": accumulated, "en": "", "final": False})

    except Exception as e:
        return _ok({"zh": "", "en": "", "final": final, "error": str(e)})
    finally:
        _pending_sema.release()
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
```

- [ ] **Step 2: Create dashboard.py router**

```python
# backend/routers/dashboard.py
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.seat_repository import SeatRepository
from backend.repositories.vote_repository import VoteRepository
from backend.repositories.service_call_repository import ServiceCallRepository
from backend.services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _ok(data):
    return {"success": True, "message": "OK", "data": data}


@router.get("")
def get_dashboard(meeting_id: int, db: Session = Depends(get_db)):
    svc = DashboardService(
        db,
        MeetingRepository(db), AttendeeRepository(db),
        SeatRepository(db), VoteRepository(db), ServiceCallRepository(db),
    )
    return _ok(svc.get_dashboard(meeting_id))
```

- [ ] **Step 3: Update main.py router registration**

In `backend/main.py`:
```python
from backend.routers import translation
from backend.routers import dashboard
app.include_router(translation.router)
app.include_router(dashboard.router)
```

Remove the old preload from lifespan since meeting_started subscriber handles it now:
```python
# Remove: from backend.routers.translation import preload_models
# Remove: asyncio.ensure_future(preload_models())
# Remove: from backend.routers.translation import history_store; history_store.close()
```

Important: At the bottom of this router file (translation.py), add the preload subscription using the module-level singletons:
```python
# ── EventBus subscription: auto-preload on meeting_started (spec Q22) ──
from backend.services.event_bus import event_bus

def _on_meeting_started_for_preload(event):
    """When meeting_started fires, trigger model preload async."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        asyncio.ensure_future(_preload_models())
    except RuntimeError:
        pass  # No running loop (test/sync context) — skip

event_bus.subscribe("meeting_started", _on_meeting_started_for_preload)
```
This references the module-level `_preload_models()` async function defined above (it uses the `_speech` and `_executor` singletons).

- [ ] **Step 4: Add audio auto-resampling support (spec sections 4.11, 12.1)**

In `speech_module/audio_utils.py`, ensure the `load_audio` or equivalent function supports automatic resampling to 16kHz when the input sample rate differs:

```python
# In speech_module/audio_utils.py — add/update:
import numpy as np
import soundfile as sf
from scipy import signal

def load_audio_resampled(path: str, target_sr: int = 16000) -> tuple[np.ndarray, int]:
    """Load audio and resample to target_sr if needed. Returns (audio_array, sample_rate)."""
    audio, sr = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)  # stereo -> mono
    if sr != target_sr:
        # Resample to target_sr
        num_samples = int(len(audio) * target_sr / sr)
        audio = signal.resample(audio, num_samples)
    return audio.astype(np.float32), target_sr
```

In `speech_module/speech_module.py`, update `transcribe_array` to auto-resample:

```python
def transcribe_array(self, audio: np.ndarray, sr: int) -> str:
    """Transcribe audio array, auto-resampling to 16kHz if needed."""
    if sr != 16000:
        from scipy import signal
        num_samples = int(len(audio) * 16000 / sr)
        audio = signal.resample(audio, num_samples).astype(np.float32)
    # ... existing transcription logic using 16kHz audio ...
```

Write unit test:
```python
# In speech_module/tests/test_audio_utils.py or test_speech_module.py
def test_load_audio_resamples_to_16k():
    import numpy as np
    from speech_module.audio_utils import load_audio_resampled
    # Create a 1-second 44.1kHz dummy WAV
    import tempfile, soundfile as sf
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        dummy = np.random.randn(44100).astype(np.float32)
        sf.write(f.name, dummy, 44100)
        audio, sr = load_audio_resampled(f.name, target_sr=16000)
        assert sr == 16000
        assert 15000 < len(audio) < 17000  # ~1 sec at 16kHz
```

Run: `pytest speech_module/tests/ -v -k "resample"`
Expected: PASS

- [ ] **Step 5: Verify old routes still respond**

Run: `cd D:\learning\smart_desktop\smart-desk && python -c "from backend.main import app; print(len(app.routes))"`
Expected: Routes count reflects new structure
