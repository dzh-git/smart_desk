"""
Translation router — SenseVoiceSmall (STT) + Opus-MT (translation).
Pure local models, CPU-optimized, zero network dependency after first download.
SenseVoiceSmall: 893MB, RTF 0.49 on CPU (faster than real-time)
Opus-MT zh-en: 300MB, 0.3-0.8s per sentence on CPU
"""
from __future__ import annotations
import asyncio
import os
import tempfile
import time
import warnings
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import re
import numpy as np
from fastapi import APIRouter, UploadFile, File, Form, Query
from pydantic import BaseModel

# pydub + funasr warn about missing ffmpeg — code uses soundfile, never touches ffmpeg
warnings.filterwarnings("ignore", message="Couldn't find ffmpeg or avconv")

from backend.schemas import TranslationRequest, TranslationOut
from backend.services.ws_service import ws_svc
from backend.services.desk_coordinator import desk

# Force offline mode — models are pre-cached
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

router = APIRouter(prefix="/api/translate", tags=["translation"])

_executor = ThreadPoolExecutor(max_workers=2)

# ── Lazy-loaded models ──

_stt_model = None
_mt_zh_en_model = None
_mt_zh_en_tokenizer = None
_mt_en_zh_model = None
_mt_en_zh_tokenizer = None
_preload_done = False
_preloading = False


class SpeakerSeatRequest(BaseModel):
    meeting_id: int
    seat_id: int  # 0 = clear


_speaker_seats: dict[int, int] = {}

# Transcript history: meeting_id → [{id, zh, en, seat_id, ts}]
_transcript_history: dict[int, list[dict]] = defaultdict(list)
_history_id_counter = 0


# ── Model loaders ──

def _get_stt_model():
    """Lazy-load SenseVoiceSmall from local cache."""
    global _stt_model
    if _stt_model is None:
        from funasr import AutoModel
        model_dir = os.path.expanduser(
            "~/.cache/modelscope/hub/models/iic/SenseVoiceSmall"
        )
        _stt_model = AutoModel(
            model=model_dir,
            device="cpu",
            disable_update=True,
            trust_remote_code=True,  # SenseVoiceSmall custom code — safe in offline env
        )
    return _stt_model


def _get_mt_zh_en_model():
    """Lazy-load Opus-MT zh→en (cached via HuggingFace)."""
    global _mt_zh_en_model, _mt_zh_en_tokenizer
    if _mt_zh_en_model is None:
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        model_name = "Helsinki-NLP/opus-mt-zh-en"
        _mt_zh_en_tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
        _mt_zh_en_model = AutoModelForSeq2SeqLM.from_pretrained(model_name, local_files_only=True)
    return _mt_zh_en_tokenizer, _mt_zh_en_model


def _get_mt_en_zh_model():
    """Lazy-load Opus-MT en→zh (cached via HuggingFace)."""
    global _mt_en_zh_model, _mt_en_zh_tokenizer
    if _mt_en_zh_model is None:
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        model_name = "Helsinki-NLP/opus-mt-en-zh"
        _mt_en_zh_tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
        _mt_en_zh_model = AutoModelForSeq2SeqLM.from_pretrained(model_name, local_files_only=True)
    return _mt_en_zh_tokenizer, _mt_en_zh_model


# ── Preload & warmup ──

def _warmup():
    """Load both models and run dummy inference to trigger JIT/optimization passes."""
    try:
        print("[preload] Loading SenseVoiceSmall...")
        _get_stt_model()
        print("[preload] Loading Opus-MT zh→en...")
        _get_mt_zh_en_model()
        print("[preload] Loading Opus-MT en→zh...")
        _get_mt_en_zh_model()
        # Warm STT with 1s silence — primes funasr internal buffers
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()  # release handle so Windows allows read
        try:
            import soundfile as sf
            sf.write(tmp.name, np.zeros(16000, dtype=np.float32), 16000)
            _transcribe_sensevoice(tmp.name)
        finally:
            os.unlink(tmp.name)
        # Warm MT with short text — primes PyTorch JIT
        _translate_zh_to_en("预热测试")
        _translate_en_to_zh("warmup test")
        print("[preload] Models ready.")
    except Exception as e:
        print(f"[preload] Warmup error (models will load on first use): {e}")


async def preload_models():
    """Preload STT+MT models in background thread. Idempotent, safe to call anytime."""
    global _preloading, _preload_done
    if _preload_done or _preloading:
        return
    _preloading = True
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(_executor, _warmup)
    except Exception as e:
        print(f"[preload] Failed: {e}")
    finally:
        _preloading = False
        _preload_done = True  # Mark done so frontend stops polling


# ── Audio loading (no ffmpeg) ──

def _load_audio(path: str) -> np.ndarray:
    """Load audio as float32 numpy array. Uses soundfile — no ffmpeg needed."""
    import soundfile as sf
    audio, sr = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000:
        from scipy import signal
        ratio = 16000 / sr
        audio = signal.resample(audio, int(len(audio) * ratio))
    return np.asarray(audio, dtype=np.float32)


# ── STT (SenseVoiceSmall) ──

def _transcribe_sensevoice(audio_path: str) -> str:
    """Transcribe Chinese speech using SenseVoiceSmall. Returns text."""
    try:
        model = _get_stt_model()
        result = model.generate(
            input=audio_path,
            language="auto",
            use_itn=True,
            batch_size_s=60,
        )
        if result and len(result) > 0:
            text = result[0].get("text", "").strip()
            # Strip all SenseVoice emotion/speech/language tags: <|NEUTRAL|>, <|Speech|>, <|withitn|>, etc.
            text = re.sub(r"<\|[^|]+\|>", "", text).strip()
            return text
    except Exception as e:
        print(f"[stt] SenseVoice failed: {e}")
    return ""


# ── Language detection ──

def _detect_language(text: str) -> str:
    """Detect if text is primarily Chinese or English. Returns 'zh' or 'en'."""
    cjk = sum(1 for c in text if '一' <= c <= '鿿' or '㐀' <= c <= '䶿')
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    return 'zh' if cjk >= latin else 'en'


# ── Translation (Opus-MT) ──

def _translate_zh_to_en(text: str) -> str:
    """Translate Chinese→English using Opus-MT."""
    try:
        tokenizer, model = _get_mt_zh_en_model()
        inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
        outputs = model.generate(**inputs, max_length=512, num_beams=4)
        return tokenizer.decode(outputs[0], skip_special_tokens=True)
    except Exception as e:
        print(f"[mt] zh→en failed: {e}")
    return ""


def _translate_en_to_zh(text: str) -> str:
    """Translate English→Chinese using Opus-MT."""
    try:
        tokenizer, model = _get_mt_en_zh_model()
        inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
        outputs = model.generate(**inputs, max_length=512, num_beams=4)
        return tokenizer.decode(outputs[0], skip_special_tokens=True)
    except Exception as e:
        print(f"[mt] en→zh failed: {e}")
    return ""


def _transcribe_and_translate(audio_path: str) -> tuple[str, str]:
    """STT + auto-detect language + translate. Always returns (zh, en)."""
    text = _transcribe_sensevoice(audio_path)
    if not text:
        return "[无法识别语音]", "[translation unavailable]"

    lang = _detect_language(text)
    if lang == 'zh':
        zh = text
        en = _translate_zh_to_en(zh) or f"[EN] {zh}"
    else:
        en = text
        zh = _translate_en_to_zh(en) or f"[ZH] {en}"
    return zh, en


async def _translate_text(text: str) -> tuple[str, str]:
    """Auto-detect and translate. Returns (zh, en)."""
    loop = asyncio.get_running_loop()
    lang = _detect_language(text)
    if lang == 'zh':
        en = await loop.run_in_executor(_executor, _translate_zh_to_en, text)
        return text, en or f"[EN] {text}"
    else:
        zh = await loop.run_in_executor(_executor, _translate_en_to_zh, text)
        return zh or f"[ZH] {text}", text


# ── Preload endpoints ──

@router.post("/preload")
async def preload():
    """Trigger model preloading. Idempotent — safe to call multiple times."""
    await preload_models()
    return {"ok": True, "ready": _preload_done}


@router.get("/preload/status")
def preload_status():
    models_loaded = (
        _stt_model is not None
        and _mt_zh_en_model is not None
        and _mt_en_zh_model is not None
    )
    return {"ready": _preload_done or models_loaded, "loading": _preloading}


# ── Transcript history ──

@router.get("/history")
def get_history(meeting_id: int = Query(...)):
    entries = _transcript_history.get(meeting_id, [])
    return {"meeting_id": meeting_id, "entries": entries}


@router.delete("/history")
def clear_history(meeting_id: int = Query(...)):
    _transcript_history.pop(meeting_id, None)
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
    zh, en = await _translate_text(text)
    return TranslationOut(
        original=zh,
        translated=en,
        source_lang="auto",
        target_lang="auto",
    )


# ── Audio (STT + translation) ──

@router.post("/audio")
async def transcribe_audio(
    meeting_id: int = Form(...),
    seat_id: int = Form(...),
    final: bool = Form(True),
    audio: UploadFile = File(...),
):
    """Receive audio → SenseVoice STT → Opus-MT → broadcast if final."""
    suffix = os.path.splitext(audio.filename or "recording.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    try:
        loop = asyncio.get_running_loop()
        zh_text, en_text = await loop.run_in_executor(
            _executor, _transcribe_and_translate, tmp_path
        )

        if final and zh_text and zh_text != "[无法识别语音]":
            global _history_id_counter
            _history_id_counter += 1
            entry = {
                "id": _history_id_counter,
                "zh": zh_text,
                "en": en_text,
                "seat_id": seat_id,
                "ts": time.time(),
            }
            _transcript_history[meeting_id].append(entry)
            # Cap history per meeting at 200 entries
            if len(_transcript_history[meeting_id]) > 200:
                _transcript_history[meeting_id] = _transcript_history[meeting_id][-200:]

            await desk.on_translation_result(meeting_id, zh_text, en_text, seat_id)

        return {"zh": zh_text, "en": en_text, "final": final, "seat_id": seat_id}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
