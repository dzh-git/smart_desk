# Speech Module MT Engine — Implementation Plan

Version: 1.0 | Date: 2026-06-02

---

## Step 1: Create `mt_engine.py`

File: `speech_module/mt_engine.py`

- [ ] `MTEngine` class with `__init__(model_dir, device)`
- [ ] `preload()` — load `opus-mt-zh-en` + `opus-mt-en-zh` via `MarianMTModel.from_pretrained`
- [ ] Model resolution: explicit dir → HF cache → Hub download
- [ ] `ready` property
- [ ] `translate(text)` — detect language → translate → return `(zh, en)`
- [ ] Error handling: never raise, return placeholder on failure

## Step 2: Integrate into `SpeechModule`

File: `speech_module/speech_module.py`

- [ ] `__init__` accepts optional `mt_engine: MTEngine`
- [ ] `preload()` calls `self._mt_engine.preload()` if present
- [ ] `translate_text()` delegates to `mt_engine.translate()` if available, else falls back to placeholder

## Step 3: Wire up in TranslationService

File: `backend/services/translation.py` (or where SpeechModule is instantiated)

- [ ] Create `MTEngine()` and pass to `SpeechModule(mt_engine=mt)`
- [ ] Call `sm.preload()` — now loads STT + MT together

## Step 4: Add `transformers` dependency

- [ ] Add `transformers` to `requirements.txt`

## Step 5: Tests

File: `speech_module/tests/test_mt_engine.py`

- [ ] `test_translate_zh_to_en`
- [ ] `test_translate_en_to_zh`
- [ ] `test_empty_input`
- [ ] `test_preload_idempotent`
- [ ] `test_model_not_loaded_fallback`

## Step 6: Verify

- [ ] `pytest speech_module/tests/`
- [ ] Manual: `python -c "from speech_module import SpeechModule; ... "`
- [ ] Integration: start backend, send audio, verify WS `translation_result.en` is real text
