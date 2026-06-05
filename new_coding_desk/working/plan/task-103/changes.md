# Task 103 — Phase 3: PCM16 Reception, Streaming ASR, translation_interim Broadcast

## Goal
Implement PCM16 binary frame reception, streaming ASR via SpeechModule, revision tracking, TranslationInterimEvent publication, and broadcast to the meeting channel.

## Modified Files

| File | Operation | Description |
|------|-----------|-------------|
| `backend/events/translation_events.py` | **Modified** | Added `TranslationInterimEvent` and `TranslationInterimCancelledEvent` dataclasses |
| `backend/websocket/event_handler.py` | **Modified** | Added `translation_interim` and `translation_interim_cancelled` to `BROADCAST_EVENTS` (15→17 events) |
| `backend/services/speech_stream_service.py` | **Modified** | Added PCM16→float32 conversion, SpeechModule lazy-loading, utterance revision tracking, `start_utterance()`, `cancel_utterance()`, `process_pcm_frame()` methods |
| `backend/websocket/speech_ws.py` | **Modified** | Added `_handle_binary_message()` for PCM16 frame processing, updated `start` to register utterance, updated `cancel` to publish `TranslationInterimCancelledEvent`, session_key propagation |
| `tests/test_speech_stream_service.py` | **Created** | 15 unit tests: PCM16 conversion, revision tracking, cancel behavior, error paths |
| `tests/test_speech_websocket_blackbox.py` | **Modified** | Added 2 Phase 3 tests + 1 conditional skip; added `_load_pcm16_frames()` helper using real speech dataset |
| `tests/fixtures/speech_sample.pcm` | **Created** | Pre-converted PCM16 speech fixture (录音1.m4a → 2s 16kHz mono s16le via ffmpeg) |
| `working/plan/task-103/changes.md` | **Created** | This file |
| `working/plan/task-103/test-results.md` | **Created** | Test results |

## Implementation Summary

### 1. Event Definitions (`backend/events/translation_events.py`)
- `TranslationInterimEvent` — ephemeral streaming ASR result, payload per EVENT_BUS_SPEC §5
- `TranslationInterimCancelledEvent` — discarded utterance notification

### 2. Broadcast Registration (`backend/websocket/event_handler.py`)
- `translation_interim` and `translation_interim_cancelled` added to `BROADCAST_EVENTS`
- WebSocketEventHandler now registered for 17 total events (was 15)
- Comment updated to reflect Phase 3 change

### 3. SpeechStreamService (`backend/services/speech_stream_service.py`)
- **SpeechModule lazy loading**: `_get_speech_module()` → `preload()` on first PCM16 frame, error cached for fast-fail
- **`is_speech_available` property**: read-only status check
- **`ensure_speech_module()`**: triggers preload, returns True/False
- **`pcm16_to_float32()`**: static method, converts PCM16 s16le bytes → float32 numpy array
- **`start_utterance()`**: sets current_utterance_id, resets revision, calls SpeechModule.start_utterance()
- **`cancel_utterance()`**: clears utterance_id/revision, returns cancelled utterance_id, resets SpeechModule
- **`process_pcm_frame()`**: full pipeline — PCM16→float32, ASR via `process_interim_array()`, revision increment
- **`SpeechStreamSession`**: added `current_utterance_id` and `revision` fields
- **`remove_session()`**: added SpeechModule session cleanup

### 4. Speech WS Handler (`backend/websocket/speech_ws.py`)
- **`_handle_binary_message()`**: new async handler:
  - Calls `stream_service.process_pcm_frame(session_key, data)`
  - Catches `RuntimeError` (models not loaded) → sends `MODEL_NOT_LOADED` error
  - Skips empty ASR results (no speech detected)
  - Publishes `TranslationInterimEvent` via EventBus
- **`_handle_text_message()`**: updated:
  - Now accepts `session_key` parameter
  - `start` → also calls `stream_service.start_utterance()`
  - `cancel` → calls `stream_service.cancel_utterance()`, publishes `TranslationInterimCancelledEvent`

### 5. Test Fixture (`tests/fixtures/speech_sample.pcm`)
- Pre-converted from `真实语音数据集/录音1.m4a` using ffmpeg
- 2 seconds, 16kHz mono, s16le raw PCM
- Used by `_load_pcm16_frames()` helper

## Architecture Decisions

- **Lazy loading**: SpeechModule is loaded on first binary frame, not at app startup. This avoids modifying `backend/main.py` lifespan (which was not in the allowed modify list). The `ensure_speech_module()` method can be called proactively if startup-time loading is desired.
- **Error caching**: Preload failures are cached in `_speech_module_error`. Subsequent calls fail immediately without retrying. This was explicitly required: "模型缺失或依赖缺失时返回明确错误，不 mock".
- **EventBus bridge**: Services publish events synchronously. `WebSocketEventHandler.__call__` detects running event loop and uses `asyncio.create_task()` to schedule broadcast. This pattern was already established in Phase 2.
- **Real speech data**: Sine wave audio produced empty ASR results. The test now uses real Chinese speech from the dataset to ensure meaningful ASR output.

## Protocol Verification

| Checkpoint | WEBSOCKET_PROTOCOL / EVENT_BUS_SPEC | Implementation |
|------------|--------------------------------------|----------------|
| PCM16 binary frame receive | §3: binary WS messages, s16le 16kHz | ✅ `_handle_binary_message()` |
| Convert to float32 | §3: audio processing | ✅ `pcm16_to_float32()` |
| Call streaming ASR | §4: backend streaming ASR | ✅ `SpeechModule.process_interim_array()` |
| Utterance revision | §5: revision in payload | ✅ Per-session revision counter |
| translation_interim payload | EVENT_BUS_SPEC §5 | ✅ utterance_id, seat_id, revision, source_lang, target_lang, source_text, translated_text, is_final |
| Broadcast to /ws/{meeting_id} | WEBSOCKET_PROTOCOL §5 | ✅ WebSocketEventHandler broadcasts |
| No database write | §5: ephemeral | ✅ No DB write |
| Model missing error | Task requirement | ✅ MODEL_NOT_LOADED error |
| cancel → cancelled event | WEBSOCKET_PROTOCOL §5 | ✅ TranslationInterimCancelledEvent |
| Real ASR, no mock | Task requirement | ✅ Real Paraformer Streaming model loaded |
