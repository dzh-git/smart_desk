# Speech Module — MT Engine Design Spec

Version: 1.0
Date: 2026-06-02
Status: Design Approved

---

# 1. Context & Problem

SmartDesk Speech Module currently implements full ASR pipeline (Paraformer streaming + offline STT, VAD, sentence merging, punctuation, history store) but **translation is a placeholder**. `SpeechModule.translate_text()` returns `"[translation not available]"` for all inputs.

Frontend display pipeline (VAD → STT → sentence merge → WebSocket broadcast → TranslationPanel.vue dual-line display) is already complete end-to-end. Only the MT engine is missing.

---

# 2. Scope

Replace placeholder with local Opus-MT (Helsinki-NLP) for bidirectional zh↔en translation.

**In scope:**
- New `mt_engine.py` module with `MTEngine` class
- `MTEngine.preload()` to load 2 models (zh→en, en→zh)
- `MTEngine.translate(text)` → `(zh: str, en: str)`
- Integrate into `SpeechModule.__init__` and `preload()`
- Graceful degradation on failure

**Out of scope:**
- Interim (streaming) translation — final sentences only
- Other language pairs
- TTS
- Multi-speaker recognition
- Cloud API fallback

---

# 3. Architecture

## 3.1 New File

```
speech_module/mt_engine.py
```

## 3.2 Class Interface

```python
class MTEngine:
    """Bidirectional zh↔en translation via Helsinki-NLP Opus-MT."""

    def __init__(self, model_dir: str | None = None, device: str = "cpu"):
        ...

    def preload(self) -> None:
        """Load both models + warmup. Idempotent. Raises on failure."""
        ...

    @property
    def ready(self) -> bool:
        """True after preload() completed successfully."""
        ...

    def translate(self, text: str) -> tuple[str, str]:
        """Auto-detect language → translate to the other.
        
        Returns (zh_str, en_str). Neither is None.
        On failure returns (text, "[translation failed]") or similar placeholder.
        """
        ...
```

## 3.3 Internals

```
MTEngine
├── _zh2en_model (MarianMTModel)
├── _zh2en_tokenizer (MarianTokenizer)
├── _en2zh_model (MarianMTModel)
├── _en2zh_tokenizer (MarianTokenizer)
│
├── preload()
│   ├── load Helsinki-NLP/opus-mt-zh-en
│   │   ├── explicit model_dir
│   │   ├── local HF cache: models/models--Helsinki-NLP--opus-mt-zh-en/snapshots/*/
│   │   └── fallback: HuggingFace Hub download
│   ├── load Helsinki-NLP/opus-mt-en-zh (same resolution)
│   └── warmup with dummy input
│
└── translate(text)
    ├── detect_language(text)          # reuse text_utils.detect_language
    ├── if zh → zh2en_model.generate() → en_text, return (text, en_text)
    ├── if en → en2zh_model.generate() → zh_text, return (zh_text, text)
    └── on error → return (text, "[translation unavailable]")
```

## 3.4 Model Resolution Priority

Same pattern as `stt_streaming.py`:
1. Explicit `model_dir` parameter (if provided)
2. Local HuggingFace cache (`models/models--Helsinki-NLP--opus-mt-*/snapshots/*/`)
3. HuggingFace Hub download (auto-cached)

## 3.5 SpeechModule Integration

Modify `speech_module/speech_module.py`:

```python
class SpeechModule:
    def __init__(
        self, max_workers: int = 4,
        history_store: Optional["HistoryStore"] = None,
        mt_engine: Optional["MTEngine"] = None,   # NEW
    ):
        ...
        self._mt_engine = mt_engine

    def preload(self) -> None:
        if self._ready:
            return
        from .stt_streaming import warmup_streaming, warmup_offline
        warmup_streaming()
        warmup_offline()
        if self._mt_engine:                        # NEW
            self._mt_engine.preload()              # NEW
        self._ready = True

    def translate_text(self, text: str) -> tuple[str, str]:
        if self._mt_engine and self._mt_engine.ready:
            return self._mt_engine.translate(text)
        from .text_utils import detect_language
        lang = detect_language(text)
        if lang == "zh":
            return (text, "[translation not available]")
        return ("[translation not available]", text)
```

**No changes to**: `stt_streaming.py`, `sentence_merge.py`, `punctuation.py`, `history_store.py`, `audio_utils.py`, `text_utils.py`, `fsmn_vad.py`, `history_store.py`.

**No changes to**: frontend (`TranslationPanel.vue`, `useAudioRecorder.js`), backend (`routers/translation.py`, `desk_coordinator.py`), WebSocket.

## 3.6 Dependencies

```python
# transformers (HuggingFace)
from transformers import MarianMTModel, MarianTokenizer
```

Add `transformers` to `speech_module/requirements.txt` or project `requirements.txt`.

---

# 4. Error Handling

```
translate(text)
├── empty text? → return ("", "")
├── detect_language ambiguous (mixed zh+en)?
│     → treat as zh (default), still attempt translation
├── model not loaded / self._mt_engine is None?
│     → fallback to placeholder "[translation not available]"
├── model.generate() exception (OOM, timeout, etc.)?
│     → log error, return (text, "[translation failed]")
└── model.generate() returns empty string?
│     → return (text, "[translation unavailable]")
```

**Core principle**: Never raise. STT pipeline continues even if MT fails. Placeholder text shown instead of crash. Existing `translate_text()` fallback path preserved.

---

# 5. Performance Targets

| Metric | Target |
|--------|--------|
| Model load time (both) | < 10s on NUC CPU |
| Memory (both models) | < 1GB RAM |
| Single sentence translate | < 500ms |
| Preload (full, incl STT) | < 30s |

Models: ~300MB each, MarianMT optimized for CPU inference.

---

# 6. Testing

## 6.1 Unit Tests

File: `speech_module/tests/test_mt_engine.py`

```python
def test_translate_zh_to_en():    # "大家好" → en output non-empty
def test_translate_en_to_zh():    # "Hello" → zh output non-empty
def test_empty_input():           # "" → ("", "")
def test_model_not_loaded():      # preload() not called → placeholder fallback
def test_mixed_language():        # ambiguous input → still produces output
def test_preload_idempotent():    # calling preload() twice doesn't crash
```

## 6.2 Integration Test

Existing `pytest speech_module/tests/` — verify MT models load and produce output.

## 6.3 Manual Verification

```bash
python -c "
from speech_module import SpeechModule
from speech_module.mt_engine import MTEngine

mt = MTEngine()
mt.preload()
print(mt.translate('大家好'))    # → ('大家好', 'Hello everyone')
print(mt.translate('Hello'))    # → ('你好', 'Hello')

# Full pipeline
sm = SpeechModule(mt_engine=mt)
sm.preload()
print(sm.translate_text('大家好'))  # → ('大家好', 'Hello everyone')
"
```

---

# 7. Migration & Compatibility

- `MTEngine` is **optional** — `SpeechModule` works without it (placeholder fallback)
- Backend `TranslationService` creates `SpeechModule` — add `mt_engine=MTEngine()` during init
- `_record_commit()` currently stores `en_text=""` — after MT integration, stores real translation
- No database migration needed
- No frontend changes needed — WebSocket payload already carries both `zh` and `en` fields
- No API changes needed

---

# 8. File Changes Summary

| File | Action |
|------|--------|
| `speech_module/mt_engine.py` | **NEW** |
| `speech_module/speech_module.py` | Modify `__init__`, `preload()`, `translate_text()` |
| `speech_module/requirements.txt` | Add `transformers` (if not present) |
| `speech_module/tests/test_mt_engine.py` | **NEW** |
| `backend/services/translation.py` | Pass `mt_engine` to SpeechModule (1 line) |

Total: **1 new file, 2 modified files, 1 new test file**.
