# Task 104 — Phase 4: Final ASR Rescore, utterance_id Persistence, translation_final Broadcast

## Goal
Implement offline ASR rescore on `end_hint`, persist final records with `utterance_id` and `source_type`, publish `translation_final` event.

## Modified Files

| File | Operation | Description |
|------|-----------|-------------|
| `backend/models/translation_record.py` | **Modified** | Added `utterance_id` (String, nullable) and `source_type` (String, nullable, server_default `'speech_ws'`) columns |
| `backend/migrations.py` | **Created** | Idempotent migration function `ensure_translation_record_columns()` using PRAGMA inspection |
| `backend/main.py` | **Modified** | Lifespan calls `ensure_translation_record_columns()` after `create_all()` |
| `backend/schemas/translation.py` | **Modified** | `TranslationRecordResponse` exposes `utterance_id` and `source_type` |
| `backend/services/translation_service.py` | **Modified** | Added `process_final_array(audio, sr, ...)` with array-based offline ASR; updated `process_final()` payload to include `utterance_id`, `source_type` |
| `backend/services/speech_stream_service.py` | **Modified** | Added audio buffer per utterance (`_utterance_buffer`), `append_audio()`, `get_buffered_audio()`, `finalize_utterance()`, `clear_audio_buffer()` |
| `backend/websocket/speech_ws.py` | **Modified** | `end_hint` now triggers `finalize_utterance()` → `TranslationService.process_final_array()` → persist + `TranslationFinalEvent`; added `ASR_EMPTY_RESULT` error; added `TRANSLATION_FAILED` error |
| `tests/test_translation_service.py` | **Created** | 7 tests: process_final_array writes utterance_id/source_type, publishes event, ASR empty error, nullable fields, migration idempotency |
| `tests/test_speech_stream_service.py` | **Modified** | Added 6 Phase 4 tests: audio buffer append/clear on start/cancel/finalize, process_pcm_frame buffers audio |
| `tests/test_speech_websocket_blackbox.py` | **Modified** | Replaced ThreadPoolExecutor with direct receive; added 4 Phase 4 tests: final broadcast, API query, interim not persisted, no-audio end_hint |
| `working/plan/task-104/changes.md` | **Created** | This file |
| `working/plan/task-104/test-results.md` | **Created** | Test results |

## Implementation Summary

### 1. Database Migration
- **Idempotent**: `ensure_translation_record_columns()` uses `inspect(engine).get_columns()` to check column existence before `ALTER TABLE`
- **Safe**: Repeated startup never fails, never drops data
- **SQLite compatible**: `ALTER TABLE ADD COLUMN` executed only when column is absent
- Called in `lifespan` after `Base.metadata.create_all()`

### 2. TranslationRecord Model
```python
utterance_id = Column(String(64), nullable=True, default=None)
source_type = Column(String(32), nullable=True, server_default="speech_ws")
```
- `utterance_id` links interim ↔ final for speech WS flow
- `source_type` tracks origin (`speech_ws`, `manual_upload`, `seed`)
- `server_default` ensures new records get `'speech_ws'` when not specified
- Old records return `None` for both fields

### 3. Audio Buffering (SpeechStreamService)
- Each `SpeechStreamSession` has a `_utterance_buffer: list[bytes]` for PCM16 frames
- `append_audio()` — called automatically by `process_pcm_frame()`
- `start_utterance()` — clears buffer for new utterance
- `cancel_utterance()` — clears buffer, resets state
- `finalize_utterance()` — concatenates buffer → float32 numpy, returns audio + metadata, clears buffer

### 4. TranslationService.process_final_array()
- Takes `audio: np.ndarray, sr: int` directly (no file I/O)
- Calls `SpeechModule.transcribe_array()` for full-context offline ASR
- Language auto-detection via `translate_text()`
- Persists to `translation_records` with `utterance_id` and `source_type`
- Publishes `TranslationFinalEvent` with payload per EVENT_BUS_SPEC §5:
  ```json
  {
    "translation_id": 42,
    "utterance_id": "utt_1_1_000017",
    "seat_id": 1,
    "source_lang": "zh",
    "target_lang": "en",
    "source_text": "共青团员们",
    "translated_text": "[translation not available]",
    "source_type": "speech_ws"
  }
  ```

### 5. end_hint → Final Flow (speech_ws.py)
1. Client sends `{"type": "end_hint"}`
2. `stream_service.finalize_utterance(session_key)` returns buffered audio
3. `TranslationService(db, event_bus).process_final_array(audio, sr, meeting_id, seat_id, utterance_id, "speech_ws")`
4. Service rescore → translate → persist → publish `TranslationFinalEvent`
5. EventBus → WebSocketEventHandler → `ws_service.broadcast()` → `/ws/{meeting_id}`
6. On error: `ASR_EMPTY_RESULT` or `MODEL_NOT_LOADED` sent on speech WS

### 6. Phase 3 Blackbox Test Fix
- Removed `concurrent.futures.ThreadPoolExecutor` receive pattern
- Replaced with deterministic `receive_json()` (models loaded → ASR produces output)
- Phase 4 tests drain interim events in a loop until `translation_final` arrives

## Protocol Verification

| Checkpoint | WEBSOCKET_PROTOCOL / EVENT_BUS_SPEC | Implementation |
|------------|--------------------------------------|----------------|
| translation_records: utterance_id | §5: payload field | ✅ Added, nullable |
| translation_records: source_type | §5: origin tracking | ✅ Added, server_default |
| Offline ASR rescore | §4: backend VAD + final rescore | ✅ `transcribe_array()` |
| translation_final payload | EVENT_BUS_SPEC §5, WEBSOCKET_PROTOCOL §5 | ✅ translation_id, utterance_id, seat_id, source_lang, target_lang, source_text, translated_text, source_type |
| translation_final broadcast | §5: broadcast to /ws/{meeting_id} | ✅ WebSocketEventHandler |
| end_hint → finalize | §4: client signal → backend finalize | ✅ finalize_utterance + process_final_array |
| Empty ASR result error | Task requirement | ✅ `ASR_EMPTY_RESULT` on speech WS |
| Model error | Task requirement | ✅ `MODEL_NOT_LOADED` on speech WS |
| Interim not persisted | §5: ephemeral | ✅ No DB write from interim path |
| GET /api/translations returns new fields | API_SPEC §10 | ✅ utterance_id, source_type in response |
| Idempotent migration | Task requirement | ✅ PRAGMA-based column check |
