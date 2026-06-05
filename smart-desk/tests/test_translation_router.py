"""Integration tests for translation router -- new /api/translations paths (Task 015)."""

import threading
import pytest

pytestmark = pytest.mark.usefixtures("reset_state")


def test_auto_preload_works_in_sync_context():
    """CR-007: Auto-preload handler must trigger preload even when called from
    a sync context with no event loop (e.g. threadpool worker thread).

    The old asyncio-based handler caught RuntimeError and silently did nothing
    in sync contexts -- meaning meeting_started never triggered preload.
    The fix uses a daemon thread so it works regardless of the calling context.
    """
    import backend.routers.translation as trans_mod
    from backend.routers.translation import _on_meeting_started_for_preload, _speech
    from backend.services.event_bus import BaseEvent

    original_ready = _speech._ready
    original_preload = _speech.preload
    original_preloading = trans_mod._preloading
    preload_called = threading.Event()

    # Reset module-level _preloading in case a prior test triggered preload
    # and the background thread hasn't finished yet.
    trans_mod._preloading = False
    _speech._ready = False

    def tracking_preload():
        preload_called.set()
        _speech._ready = True

    _speech.preload = tracking_preload

    try:
        event = BaseEvent(name="meeting_started", payload={"meeting_id": 1})
        _on_meeting_started_for_preload(event)

        # preload should be called in background thread within timeout
        assert preload_called.wait(timeout=5), "preload was not triggered in background thread"
    finally:
        _speech.preload = original_preload
        _speech._ready = original_ready
        trans_mod._preloading = original_preloading


def test_auto_preload_skips_when_already_ready():
    """CR-007: Auto-preload should be a no-op when models are already loaded."""
    import backend.routers.translation as trans_mod
    from backend.routers.translation import _on_meeting_started_for_preload, _speech
    from backend.services.event_bus import BaseEvent

    original_ready = _speech._ready
    original_preload = _speech.preload
    original_preloading = trans_mod._preloading
    preload_called = threading.Event()

    trans_mod._preloading = False
    _speech._ready = True  # Already ready

    def tracking_preload():
        preload_called.set()

    _speech.preload = tracking_preload

    try:
        event = BaseEvent(name="meeting_started", payload={"meeting_id": 1})
        _on_meeting_started_for_preload(event)

        # Give a small window for any thread to run, then verify no preload
        import time
        time.sleep(0.1)
        assert not preload_called.is_set(), "preload should not be called when already ready"
    finally:
        _speech.preload = original_preload
        _speech._ready = original_ready
        trans_mod._preloading = original_preloading


def test_preload_status_new_path(client):
    """GET /api/translations/preload/status should return success envelope."""
    resp = client.get("/api/translations/preload/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["message"] == "OK"
    assert "ready" in body["data"]
    assert "loading" in body["data"]


def test_translate_text_new_path(client):
    """POST /api/translations should accept text translation request."""
    resp = client.post("/api/translations", json={"text": "Hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "zh" in body["data"]
    assert "en" in body["data"]


def test_get_history_new_path(client):
    """GET /api/translations?meeting_id=N should return history list."""
    resp = client.get("/api/translations?meeting_id=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)


def test_delete_history_new_path(client):
    """DELETE /api/translations?meeting_id=N should return deleted count."""
    resp = client.delete("/api/translations?meeting_id=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "deleted" in body["data"]


def test_old_translate_path_not_found(client):
    """Old /api/translate paths should return 404."""
    resp = client.get("/api/translate/history?meeting_id=1")
    assert resp.status_code == 404


def test_old_speaker_seat_path_not_found(client):
    """Old speaker-seat endpoint should no longer exist."""
    resp = client.post("/api/translate/speaker-seat", json={"meeting_id": 1, "seat_id": 2})
    assert resp.status_code in (404, 405)


@pytest.mark.asyncio
async def test_temp_file_cleanup_on_audio_read_failure():
    """CR-010: When audio.read() raises after temp file creation, the temp file
    must still be cleaned up via the finally block.

    CR-014: Failure must raise HTTPException (500) so the unified error handler
    returns success=false, not success=true with inline error string.
    """
    import os
    import backend.routers.translation as trans_mod
    from unittest.mock import patch, AsyncMock, MagicMock
    from fastapi import HTTPException

    # Create audio mock whose read() raises
    audio_mock = MagicMock()
    audio_mock.filename = "test_recording.wav"
    audio_mock.read = AsyncMock(side_effect=RuntimeError("simulated read failure"))

    # Track unlinked files
    unlinked_paths = []
    original_unlink = os.unlink

    def tracking_unlink(path):
        unlinked_paths.append(path)
        original_unlink(path)

    # Save original state
    original_ready = trans_mod._speech._ready

    with patch.object(trans_mod._pending_sema, 'acquire', return_value=True), \
         patch.object(trans_mod._pending_sema, 'release'), \
         patch('os.unlink', side_effect=tracking_unlink), \
         patch.object(trans_mod, 'get_logger') as mock_get_logger:
        trans_mod._speech._ready = True

        with pytest.raises(HTTPException) as exc_info:
            await trans_mod.transcribe_audio(
                meeting_id=1, seat_id=1, final=True, utterance_id=0, audio=audio_mock
            )

        assert exc_info.value.status_code == 500

    trans_mod._speech._ready = original_ready

    # CR-012: Verify that logger.exception was used (not traceback.print_exc)
    mock_logger = mock_get_logger.return_value
    mock_logger.exception.assert_called_once()
    # CR-012: Verify traceback module was not imported/used for logging
    assert "Audio transcription failed" in str(mock_logger.exception.call_args)

    # Verify at least one .wav temp file was cleaned up
    wav_unlinks = [p for p in unlinked_paths if p.endswith('.wav')]
    assert len(wav_unlinks) > 0, (
        "No temp .wav file was unlinked — temp file may have leaked. "
        f"All unlinked paths: {unlinked_paths}"
    )
    for path in wav_unlinks:
        assert not os.path.exists(path), f"Temp file still exists on disk: {path}"


def test_audio_endpoint_returns_500_on_error(client):
    """CR-014: Audio endpoint failure should return HTTP 500 with success=false,
    not 200 with success=true and inline error string."""
    import backend.routers.translation as trans_mod
    from unittest.mock import patch

    original_ready = trans_mod._speech._ready
    original_transcribe = trans_mod._speech.transcribe

    def raise_error(path):
        raise RuntimeError("simulated transcribe failure")

    try:
        trans_mod._speech._ready = True
        trans_mod._speech.transcribe = raise_error

        with patch.object(trans_mod._pending_sema, 'acquire', return_value=True), \
             patch.object(trans_mod._pending_sema, 'release'), \
             patch('os.unlink'):
            resp = client.post(
                "/api/translations/audio",
                data={"meeting_id": 1, "seat_id": 1, "final": "true", "utterance_id": 0},
                files={"audio": ("test.wav", b"fake audio data", "audio/wav")},
            )
            # CR-014: Should return 500 from unified error handler
            assert resp.status_code == 500, f"Expected 500, got {resp.status_code}: {resp.json()}"
            body = resp.json()
            assert body["success"] is False, f"Expected success=false, got: {body}"
    finally:
        trans_mod._speech._ready = original_ready
        trans_mod._speech.transcribe = original_transcribe


def test_preload_models_guards_against_concurrent_preload():
    """CR-015: _preload_models() must check _preloading before proceeding,
    preventing concurrent preloads from the /preload endpoint and the
    EventBus daemon thread path."""
    import backend.routers.translation as trans_mod
    from unittest.mock import patch

    original_ready = trans_mod._speech._ready
    original_preloading = trans_mod._preloading

    try:
        trans_mod._speech._ready = False
        trans_mod._preloading = True  # simulate daemon thread already preloading

        with patch.object(trans_mod._executor, 'submit') as mock_submit:
            import asyncio
            async def run_test():
                await trans_mod._preload_models()
            asyncio.run(run_test())

            # With _preloading=True, _preload_models should return early
            # without submitting to the executor
            mock_submit.assert_not_called()
    finally:
        trans_mod._speech._ready = original_ready
        trans_mod._preloading = original_preloading


def test_preload_models_preloading_flag_resets_on_early_exception():
    """CR-015: If asyncio.get_running_loop() raises RuntimeError, _preloading
    must stay False (not stuck True permanently)."""
    import backend.routers.translation as trans_mod
    from unittest.mock import patch

    original_ready = trans_mod._speech._ready
    original_preloading = trans_mod._preloading

    try:
        trans_mod._speech._ready = False
        trans_mod._preloading = False

        with patch('asyncio.get_running_loop', side_effect=RuntimeError("no loop")):
            import asyncio
            async def run_test():
                await trans_mod._preload_models()
            with patch.object(trans_mod, 'get_logger'):
                # Should not raise — the RuntimeError propagates but _preloading
                # should be False since it's set after get_running_loop()
                try:
                    asyncio.run(run_test())
                except RuntimeError:
                    pass  # expected

            # CR-015: _preloading must NOT be stuck at True
            assert trans_mod._preloading is False, (
                "_preloading stuck at True after RuntimeError in get_running_loop(). "
                "The flag should be reset because _preloading = True is now AFTER "
                "asyncio.get_running_loop()."
            )
    finally:
        trans_mod._speech._ready = original_ready
        trans_mod._preloading = original_preloading
