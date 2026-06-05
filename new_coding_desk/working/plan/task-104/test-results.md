# Task 104 — Test Results

## Verification Commands

```bash
pytest tests/test_translation_service.py -q
pytest tests/test_speech_stream_service.py -q
pytest tests/test_speech_websocket_blackbox.py -q
pytest -q
```

## Results

### TranslationService Unit Tests (`test_translation_service.py`)

```
7 passed in 17.34s
```

| Test | Result |
|------|--------|
| `test_writes_utterance_id_and_source_type` | ✅ Real ASR → record with utterance_id and source_type |
| `test_publishes_translation_final_event` | ✅ Event published with full payload (translation_id, utterance_id, source_text, etc.) |
| `test_asr_empty_result_raises_error` | ✅ Sine wave → `ASR_EMPTY_RESULT` ValidationError |
| `test_records_without_explicit_source_type` | ✅ server_default `'speech_ws'` applied |
| `test_record_visible_via_translation_api` | ✅ get_history returns record with new fields |
| `test_migration_runs_twice_safely` | ✅ Idempotent — second call no-op |
| `test_new_tables_have_columns` | ✅ Tables created after migration also have columns |

### SpeechStreamService Unit Tests (`test_speech_stream_service.py`)

```
21 passed in 20.68s
```

Phase 3 tests: 15 (unchanged from Phase 3) ✅
Phase 4 additions: 6 ✅

| New Test | Result |
|----------|--------|
| `test_append_audio_buffers_pcm_bytes` | ✅ |
| `test_append_audio_cleared_on_start` | ✅ |
| `test_append_audio_cleared_on_cancel` | ✅ |
| `test_finalize_utterance_returns_audio_and_metadata` | ✅ |
| `test_finalize_without_buffer_returns_none` | ✅ |
| `test_process_pcm_frame_buffers_audio` | ✅ |

### Blackbox Tests (`test_speech_websocket_blackbox.py`)

```
8 passed, 1 skipped in 22.82s
```

| Test | Phase | Result |
|------|-------|--------|
| `test_non_speaker_seat_cannot_start_speech_ws` | 2 | ✅ |
| `test_speaker_seat_can_start_speech_ws` | 2 | ✅ |
| `test_pcm16_binary_triggers_interim_broadcast` | 3 | ✅ (fixed — direct receive, no ThreadPoolExecutor) |
| `test_pcm16_binary_error_when_models_unavailable` | 3 | ⏭️ (models loaded — skipped) |
| `test_cancel_utterance_clears_state` | 3 | ✅ |
| `test_end_hint_triggers_final_broadcast` | 4 | ✅ **Full pipeline: PCM16→buffer→end_hint→ASR rescore→persist→translation_final broadcast** |
| `test_end_hint_triggers_final_and_translation_records_queryable` | 4 | ✅ **GET /api/translations returns record with utterance_id + source_type** |
| `test_interim_not_persisted_before_end_hint` | 4 | ✅ **No DB records before end_hint** |
| `test_end_hint_without_audio_is_noop` | 4 | ✅ **end_hint with no audio = no-op, no crash, no record** |

### Full Test Suite

```
180 passed, 1 skipped, 0 failed in 90.67s
```

| Suite | Before (Phase 3) | After (Phase 4) | Delta |
|-------|-------------------|------------------|-------|
| All tests | 163 passed | 180 passed | **+17 tests** |

## Regression Check

| Suite | Result |
|-------|--------|
| `test_websocket_integration.py` | ✅ |
| `test_speech_websocket_blackbox.py` | ✅ (Phase 2/3 tests preserved, Phase 4 new) |
| `test_speech_stream_service.py` | ✅ (Phase 3 tests preserved, Phase 4 new) |
| `test_translation_service.py` | ✅ (new) |
| `test_seat_service.py` | ✅ |
| `test_meeting_service.py` | ✅ |
| `test_votes_router.py` | ✅ |
| `test_service_calls_router.py` | ✅ |
| `test_dev_api.py` | ✅ |

Zero regression. All existing tests pass.

## translation_final Payload Example

```json
{
  "event": "translation_final",
  "meeting_id": 1,
  "timestamp": 1780668775,
  "payload": {
    "translation_id": 1,
    "utterance_id": "utt_1_1_000001",
    "seat_id": 1,
    "source_lang": "zh",
    "target_lang": "en",
    "source_text": "共青团员们",
    "translated_text": "[translation not available]",
    "source_type": "speech_ws"
  }
}
```

## ASR/VAD Model Status

| Model | Status |
|-------|--------|
| Paraformer Streaming | ✅ Loaded (local cache, device=cpu) |
| Paraformer-large | ✅ Loaded (local cache, device=cpu) — used for offline rescore |

## Database Migration

| Method | Idempotent | Breaking |
|--------|-----------|----------|
| `ensure_translation_record_columns()` | ✅ PRAGMA-based column check | ❌ No — old records return None/null for new fields |

## Can Enter Phase 5

**Yes.** Phase 4 is complete:

- ✅ translation_records: utterance_id + source_type columns
- ✅ Idempotent SQLite migration
- ✅ Schema exposes new fields in GET /api/translations
- ✅ Audio buffering per utterance (SpeechStreamSession._utterance_buffer)
- ✅ end_hint → finalize_utterance → process_final_array (array-based ASR)
- ✅ Real SpeechModule.transcribe_array() for offline rescore
- ✅ TranslationFinalEvent with full payload → broadcast
- ✅ ASR_EMPTY_RESULT and MODEL_NOT_LOADED errors
- ✅ Interim not persisted before end_hint
- ✅ No mock fallback
- ✅ Zero regression
- ✅ Phase 3 blackbox test ThreadPoolExecutor removed
