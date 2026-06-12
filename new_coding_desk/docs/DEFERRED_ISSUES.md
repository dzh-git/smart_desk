# SmartDesk Deferred Issues

These issues are known and non-blocking for the v1 demo.

## ASR Accuracy

Current ASR quality depends on the local FunASR models, microphone quality, and
room noise. The demo acceptance target is pipeline correctness: PCM input,
interim display, auto-final, persistence, and final broadcast. Better accuracy
requires model replacement, model tuning, or improved audio hardware.

## RMS Endpoint Detection

The current final boundary uses RMS endpoint detection. It works for the local
demo but is less robust than a dedicated neural VAD. FunASR FSMN-VAD integration
is deferred.

## Translation Model Disabled by Default

OPUS-MT zh-en is available as an optional local model but is disabled unless
`ENABLE_TRANSLATION_MODEL=true`. This avoids requiring every developer to
download or load the model for ordinary backend tests.

## Translation Cache Deployment

Production deployment needs a clear model cache strategy for `models/` and
`.hf_cache/`. The current repository intentionally does not track model weights.

## Playwright Microphone Automation

Automated E2E tests use PCM fixtures rather than browser microphone permission.
Manual demo still requires a browser microphone grant.

## Local Database Growth

Repeated manual demos and E2E runs can create many meetings in the local SQLite
database. The database is disposable in local demo mode and can be deleted
before startup.

## Windows Launcher Cleanup

`start.bat` starts long-running backend and frontend windows. Use `kill.bat` to
clean up ports and processes.

## Frontend Lint Warnings

Some React Fast Refresh warnings may remain if shared test utilities export
non-component helpers. They do not affect build or runtime behavior.

## Punctuation Quality

Chinese punctuation and two-line caption formatting are functional but may need
future product tuning for readability and typography.
