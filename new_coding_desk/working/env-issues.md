# SmartDesk — Environment Issues

This file records environment-specific issues discovered during development
and demo validation. These are NOT code bugs — they are missing dependencies,
platform quirks, or configuration gaps in the current environment.

---

### 1. pydub not installed (optional dependency)

**Status:** Open — documented, non-blocking

**Date discovered:** 2026-06-06

**Description:** `pydub` (>=0.25.0) is not installed in the current Python
environment (Anaconda Python 3.12.4).

**Impact:** The offline audio file loading path in
`backend/speech_module/audio_utils.py` uses `pydub.AudioSegment` for format
conversion. Since the streaming ASR pipeline receives raw PCM16 frames via
the speech WebSocket (not audio files), this dependency is **not required**
for the core demo flow.

The following paths work without pydub:
- `/ws/speech/{meeting_id}` — PCM16 frame upload and streaming ASR
- `SpeechModule.process_interim_array()` — float32 array ASR
- `SpeechModule.preload()` — model loading
- All translation finalize/persist operations

The following paths require pydub and will fail:
- `SpeechModule.transcribe(audio_path)` — file-based transcription
- `audio_utils.load_audio()` — audio file loading

**Error stack (on import):**
```
ModuleNotFoundError: No module named 'pydub'
```

**Fix:**
```bash
pip install pydub
```
Or install all dependencies:
```bash
pip install -r requirements.txt
```

**Workaround:** The demo flow does not use pydub, so no workaround is needed
for the Phase 8 demo. Install pydub only if audio file transcription is needed.

---

### 2. funasr model warmup first-load latency

**Status:** Expected behaviour — documented, non-blocking

**Date discovered:** 2026-06-06

**Description:** The first call to `SpeechModule.preload()` takes 10–60 seconds
because FunASR's `AutoModel` loads model weights from disk and initialises the
ONNX/CUDA runtime. Subsequent calls are instant.

**Impact:** The first `/ws/speech` connection may experience a delay before
the `started` response. The backend console will show loading progress.

**Observation:** `Paraformer Streaming loaded (local cache, device=cpu).`
followed by `Paraformer-large loaded (local cache, device=cpu).`

**Mitigation:** Start the backend and wait for the startup checks to complete
before beginning the demo. The first user to connect will pay the warmup cost.
