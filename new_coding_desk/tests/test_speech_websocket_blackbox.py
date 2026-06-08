"""
SmartDesk Speech Phase 2/3/4 — Voice WebSocket Black-Box Tests.

Spec: WEBSOCKET_PROTOCOL §3-7, ADR 0001-0004, API_SPEC §12.
Target: /ws/speech/{meeting_id}?seat={seat_id}

Phase 2 scope (connection & permission only):
    - Non-Speaker-Seat connection → NOT_SPEAKER_SEAT error
    - Speaker Seat connection → start → started + utterance_id + session_key
    - utterance_id format: utt_{meeting_id}_{seat_id}_{seq:06d}

Phase 3 additions:
    - PCM16 binary frame → translation_interim broadcast (real speech dataset)
    - PCM16 binary frame → MODEL_NOT_LOADED error (models unavailable)
    - Cancel utterance → state cleared, new utterance can start

Phase 4 additions:
    - end_hint → offline ASR rescore → persist → translation_final broadcast
    - GET /api/translations returns records with utterance_id and source_type
    - No database writes for interim (ephemeral)
"""
from __future__ import annotations

import os
import re
from typing import Generator

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import Base
from backend.services.speech_stream_service import stream_service
from tests.conftest import TEST_ENGINE, TestSessionLocal


# ── Helper: PCM16 real speech fixture ────────────────────────────────────────


_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
_PCM_FIXTURE = os.path.join(_FIXTURE_DIR, "speech_sample.pcm")
# 100ms @ 16kHz s16le mono = 3200 bytes
_FRAME_SIZE = 3200


def _load_pcm16_frames(
    count: int = 20,
    start_offset: int = 0,
) -> list[bytes]:
    """Load real speech PCM16 frames from the test fixture.

    The fixture was pre-converted from 真实语音数据集/录音1.m4a
    (Chinese speech) using ffmpeg:
        16kHz mono, s16le, 2 seconds total.

    Args:
        count: Number of 100ms frames to return (default 20 = 2 seconds).
        start_offset: Frame offset to start from (0 = beginning).

    Returns:
        List of PCM16 s16le byte strings, each 3200 bytes (100ms @ 16kHz).
    """
    if not os.path.exists(_PCM_FIXTURE):
        raise FileNotFoundError(
            f"PCM16 fixture not found: {_PCM_FIXTURE}. "
            "Run: ffmpeg -i 真实语音数据集/录音1.m4a "
            "-t 2 -f s16le -ac 1 -ar 16000 tests/fixtures/speech_sample.pcm"
        )

    with open(_PCM_FIXTURE, "rb") as f:
        raw = f.read()

    # Split into 100ms frames
    offset = start_offset * _FRAME_SIZE
    frames: list[bytes] = []
    for i in range(count):
        start = offset + i * _FRAME_SIZE
        end = start + _FRAME_SIZE
        if end > len(raw):
            break  # not enough data
        frames.append(raw[start:end])

    return frames


# ── Helper: DB cleanup ──────────────────────────────────────────────────────


def _clean_tables() -> None:
    """Drop and recreate all tables, init seat states."""
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    db = TestSessionLocal()
    try:
        from backend.repositories.seat_repository import SeatRepository
        SeatRepository.init_seats(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Helper: HTTP workflow ───────────────────────────────────────────────────


def _create_meeting(client: TestClient) -> int:
    """Create and start a meeting, return meeting_id."""
    resp = client.post(
        "/api/meetings",
        json={"title": "Speech WS Test", "description": ""},
    )
    assert resp.status_code == 201, f"Create meeting failed: {resp.json()}"
    mid = resp.json()["data"]["id"]
    resp2 = client.post(f"/api/meetings/{mid}/start")
    assert resp2.status_code == 200, f"Start meeting failed: {resp2.json()}"
    return mid


def _set_speaker_seat(client: TestClient, seat_id: int) -> None:
    """Set the speaker seat via HTTP API."""
    resp = client.post("/api/seats/speaker", json={"seat_id": seat_id})
    assert resp.status_code == 200, f"Set speaker seat failed: {resp.json()}"
    assert resp.json()["data"]["seat_id"] == seat_id


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function", autouse=True)
def _reset_db() -> Generator[None, None, None]:
    """Clean DB before each test."""
    _clean_tables()
    yield
    _clean_tables()


# ── Test class ──────────────────────────────────────────────────────────────


class TestSpeechWebSocketBlackBox:
    """Black-box tests for /ws/speech/{meeting_id}?seat=N.

    Phase 2: connection & permission.
    Phase 3: PCM16 → interim broadcast, cancel handling.
    Phase 4: end_hint → final ASR → persist → translation_final broadcast.
    """

    # ── Phase 2: non-speaker seat rejected ─────────────────────────────────

    def test_non_speaker_seat_cannot_start_speech_ws(self) -> None:
        """Non-Speaker-Seat connection → NOT_SPEAKER_SEAT error.

        Per WEBSOCKET_PROTOCOL §3.
        """
        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=3"
            ) as ws:
                data = ws.receive_json()

                assert data.get("type") == "error", (
                    f"Expected error type, got: {data}"
                )
                assert data.get("code") == "NOT_SPEAKER_SEAT", (
                    f"Expected NOT_SPEAKER_SEAT, got: {data}"
                )

    # ── Phase 2: speaker seat start flow ───────────────────────────────────

    def test_speaker_seat_can_start_speech_ws(self) -> None:
        """Speaker Seat sends 'start' → receives 'started'.

        Per WEBSOCKET_PROTOCOL §3 and ADR 0003.
        """
        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=1"
            ) as ws:
                ws.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })

                data = ws.receive_json()

                assert data.get("type") == "started", (
                    f"Expected 'started', got: {data}"
                )

                # utterance_id: utt_{meeting_id}_{seat_id}_{seq:06d}
                utterance_id: str = data.get("utterance_id", "")
                expected_pattern = rf"utt_{mid}_1_\d{{6}}"
                assert re.match(expected_pattern, utterance_id), (
                    f"utterance_id '{utterance_id}' does not match "
                    f"pattern '{expected_pattern}'"
                )

                # session_key: speech_{meeting_id}_{seat_id}
                session_key: str = data.get("session_key", "")
                assert session_key == f"speech_{mid}_1", (
                    f"Expected session_key 'speech_{mid}_1', "
                    f"got: '{session_key}'"
                )

    # ── Phase 3: PCM16 binary → interim broadcast ──────────────────────────

    def test_pcm16_binary_triggers_interim_broadcast(self) -> None:
        """PCM16 binary frame → translation_interim broadcast (real speech).

        Binary frames are routed through SpeechModule.process_interim_array().
        Real Chinese speech from 真实语音数据集 fixture is used.
        ASR model is loaded in this environment (local cache).

        Per requirements:
            - Real ASR processing, no mock fallback
            - translation_interim payload per EVENT_BUS_SPEC §5
            - Ephemeral — no database write
            - Broadcast format per WEBSOCKET_PROTOCOL §5
        """
        if not stream_service.ensure_speech_module():
            pytest.skip("Speech models not loaded — cannot test interim broadcast")

        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(f"/ws/{mid}") as broadcast_ws:
                connected = broadcast_ws.receive_json()
                assert connected["event"] == "connected"

                with client.websocket_connect(
                    f"/ws/speech/{mid}?seat=1"
                ) as speech_ws:
                    speech_ws.send_json({
                        "type": "start",
                        "sample_rate": 16000,
                        "encoding": "pcm_s16le",
                        "channels": 1,
                    })
                    started = speech_ws.receive_json()
                    assert started["type"] == "started"
                    uid = started["utterance_id"]

                    # Send 2 seconds of real speech PCM16 (20 frames)
                    frames = _load_pcm16_frames(count=20)
                    assert len(frames) == 20
                    for frame in frames:
                        speech_ws.send_bytes(frame)

                    # Receive translation_interim on broadcast channel.
                    # Models ARE loaded on this machine; ASR produces output
                    # after ~1.7s of audio, so the event is deterministic.
                    interim = broadcast_ws.receive_json()
                    assert interim["event"] == "translation_interim", (
                        f"Expected translation_interim, got: {interim}"
                    )

                    payload = interim["payload"]
                    assert payload["utterance_id"] == uid
                    assert payload["revision"] >= 1
                    assert payload["seat_id"] == 1
                    assert isinstance(payload["source_text"], str)
                    assert len(payload["source_text"]) > 0
                    assert payload["is_final"] is False

                    # Phase 02: interim payload must contain caption
                    assert "caption" in payload, (
                        "interim payload missing 'caption' field"
                    )
                    caption = payload["caption"]
                    assert isinstance(caption, dict)
                    assert "previous_line" in caption
                    assert "current_line" in caption
                    assert caption["mode"] == "two_line"

                    # Verify broadcast message format per §5
                    assert interim["meeting_id"] == mid
                    assert isinstance(interim["timestamp"], int)

    # ── Phase 3: model error path ──────────────────────────────────────────

    def test_pcm16_binary_error_when_models_unavailable(self) -> None:
        """PCM16 binary frame → MODEL_NOT_LOADED error (models absent).

        Defensive error path: when speech models cannot be loaded,
        the server returns a clear error instead of crashing.
        """
        if stream_service.ensure_speech_module():
            pytest.skip("Models loaded — error path not exercised")

        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=1"
            ) as ws:
                ws.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started = ws.receive_json()
                assert started["type"] == "started"

                ws.send_bytes(b"\x00" * 3200)

                error = ws.receive_json()
                assert error.get("type") == "error"
                assert error.get("code") == "MODEL_NOT_LOADED"

    # ── Phase 3: cancel utterance ──────────────────────────────────────────

    def test_cancel_utterance_clears_state(self) -> None:
        """Client sends 'cancel' → utterance cleared, new start works.

        Cancel resets utterance state and publishes
        TranslationInterimCancelledEvent.
        """
        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(f"/ws/speech/{mid}?seat=1") as ws:
                # Start utterance 1
                ws.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started = ws.receive_json()
                assert started["type"] == "started"
                uid1 = started["utterance_id"]

                # Cancel utterance 1
                ws.send_json({"type": "cancel"})

                # Start utterance 2 — should get a different utterance_id
                ws.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started2 = ws.receive_json()
                assert started2["type"] == "started"
                uid2: str = started2["utterance_id"]
                assert uid2 != uid1
                assert re.match(rf"utt_{mid}_1_\d{{6}}", uid2)

    # ── Phase 02: caption appears in interim payload ────────────────────────

    def test_interim_payload_has_caption(self) -> None:
        """Every translation_interim payload must contain caption fields."""
        if not stream_service.ensure_speech_module():
            pytest.skip("Speech models not loaded")

        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(f"/ws/{mid}") as broadcast_ws:
                broadcast_ws.receive_json()  # "connected"

                with client.websocket_connect(
                    f"/ws/speech/{mid}?seat=1"
                ) as speech_ws:
                    speech_ws.send_json({
                        "type": "start",
                        "sample_rate": 16000,
                        "encoding": "pcm_s16le",
                        "channels": 1,
                    })
                    speech_ws.receive_json()  # started

                    frames = _load_pcm16_frames(count=20)
                    for frame in frames:
                        speech_ws.send_bytes(frame)

                    # Collect first interim caption
                    caption_seen = False
                    for _attempt in range(50):
                        msg = broadcast_ws.receive_json()
                        if msg["event"] == "translation_interim":
                            payload = msg["payload"]
                            if "caption" in payload:
                                cap = payload["caption"]
                                assert "previous_line" in cap
                                assert "current_line" in cap
                                assert cap["mode"] == "two_line"
                                caption_seen = True
                                break

                    assert caption_seen, (
                        "No translation_interim with caption received"
                    )

    # ── Phase 4: end_hint → final broadcast ────────────────────────────────

    def test_end_hint_triggers_final_broadcast(self) -> None:
        """start + PCM16 + end_hint → translation_final broadcast + persist.

        Phase 4 flow:
            1. Client sends 'start' → receives utterance_id
            2. Client streams PCM16 frames (buffered server-side)
            3. Client sends 'end_hint' → triggers offline ASR rescore
            4. TranslationService.process_final_array() persists to DB
            5. TranslationFinalEvent published → broadcast on /ws/{meeting_id}
            6. translation_final payload includes utterance_id and record id
        """
        if not stream_service.ensure_speech_module():
            pytest.skip("Speech models not loaded — cannot test final broadcast")

        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            # Connect both broadcast WS and speech WS
            with client.websocket_connect(f"/ws/{mid}") as broadcast_ws:
                broadcast_ws.receive_json()  # consume "connected"

                with client.websocket_connect(
                    f"/ws/speech/{mid}?seat=1"
                ) as speech_ws:
                    # Start utterance
                    speech_ws.send_json({
                        "type": "start",
                        "sample_rate": 16000,
                        "encoding": "pcm_s16le",
                        "channels": 1,
                    })
                    started = speech_ws.receive_json()
                    assert started["type"] == "started"
                    uid = started["utterance_id"]

                    # Stream PCM16 frames (2 seconds of real speech)
                    frames = _load_pcm16_frames(count=20)
                    for frame in frames:
                        speech_ws.send_bytes(frame)

                    # Signal end of utterance → triggers offline ASR + persist
                    speech_ws.send_json({"type": "end_hint"})

                    # Drain interim events until translation_final arrives.
                    # Interim events arrive before translation_final because
                    # they are emitted per PCM16 frame during streaming.
                    final = None
                    for _attempt in range(50):
                        msg = broadcast_ws.receive_json()
                        if msg["event"] == "translation_final":
                            final = msg
                            break

                    assert final is not None, (
                        "No translation_final event received on broadcast "
                        "channel after end_hint"
                    )

                    payload = final["payload"]
                    # Verify required fields per EVENT_BUS_SPEC §5
                    assert "translation_id" in payload, (
                        "translation_final payload missing translation_id"
                    )
                    assert payload["utterance_id"] == uid, (
                        f"utterance_id mismatch: {payload['utterance_id']} vs {uid}"
                    )
                    assert payload["seat_id"] == 1
                    assert isinstance(payload["source_text"], str)
                    assert len(payload["source_text"]) > 0, (
                        "source_text should not be empty with real speech"
                    )
                    # Phase 02: final source_text should contain punctuation
                    assert any(p in payload["source_text"] for p in "。？！，.!?"), (
                        f"final source_text lacks punctuation: "
                        f"'{payload['source_text']}'"
                    )
                    assert isinstance(payload["translated_text"], str)
                    assert payload["source_type"] == "speech_ws"

                    # Verify broadcast message format per §5
                    assert final["meeting_id"] == mid
                    assert isinstance(final["timestamp"], int)

    def test_end_hint_triggers_final_and_translation_records_queryable(
        self,
    ) -> None:
        """After end_hint, GET /api/translations returns the persisted record.

        Verifies:
            - translation_records contains utterance_id and source_type
            - GET /api/translations?meeting_id=... returns the new record
            - The record's source_text matches the real ASR output
        """
        if not stream_service.ensure_speech_module():
            pytest.skip("Speech models not loaded")

        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(f"/ws/speech/{mid}?seat=1") as ws:
                ws.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started = ws.receive_json()
                uid = started["utterance_id"]

                frames = _load_pcm16_frames(count=20)
                for frame in frames:
                    ws.send_bytes(frame)

                ws.send_json({"type": "end_hint"})

            # Query translation records via HTTP API
            resp = client.get(f"/api/translations?meeting_id={mid}")
            assert resp.status_code == 200, (
                f"GET /api/translations?meeting_id={mid} failed: "
                f"{resp.status_code} {resp.json()}"
            )

            data = resp.json()
            data_field = data.get("data", {})
            entries = data_field.get("entries", [])
            matches = [e for e in entries if e.get("utterance_id") == uid]
            assert len(matches) >= 1, (
                f"No translation record found for utterance_id {uid} "
                f"in response: {data}"
            )

            record = matches[0]
            assert record["utterance_id"] == uid
            assert record["source_type"] == "speech_ws"
            assert isinstance(record["source_text"], str)
            assert len(record["source_text"]) > 0
            # Phase 02: persisted source_text contains punctuation
            assert any(p in record["source_text"] for p in "。？！，.!?"), (
                f"DB source_text lacks punctuation: "
                f"'{record['source_text']}'"
            )
            assert record["seat_id"] == 1

    def test_interim_not_persisted_before_end_hint(self) -> None:
        """Interim ASR results do NOT produce DB records.

        Only end_hint triggers persistence. Before end_hint,
        no translation records exist for the utterance.
        """
        if not stream_service.ensure_speech_module():
            pytest.skip("Speech models not loaded")

        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(f"/ws/speech/{mid}?seat=1") as ws:
                ws.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started = ws.receive_json()
                uid = started["utterance_id"]

                # Send speech frames but NO end_hint
                frames = _load_pcm16_frames(count=20)
                for frame in frames:
                    ws.send_bytes(frame)

            # Query — should have NO records for this utterance
            resp = client.get(f"/api/translations?meeting_id={mid}")
            assert resp.status_code == 200, (
                f"GET /api/translations?meeting_id={mid} failed: "
                f"{resp.status_code}"
            )
            data = resp.json()
            data_field = data.get("data", {})
            entries = data_field.get("entries", [])
            matches = [e for e in entries if e.get("utterance_id") == uid]
            assert len(matches) == 0, (
                f"Found unexpected translation records before end_hint: "
                f"{matches}"
            )

    def test_end_hint_without_audio_is_noop(self) -> None:
        """end_hint with no buffered audio does not error.

        Sending end_hint immediately after start (no PCM16 frames)
        results in a no-op — no error, no crash, no DB record.
        """
        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(f"/ws/speech/{mid}?seat=1") as ws:
                ws.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                ws.receive_json()  # started

                # end_hint with no audio — should be a safe no-op
                ws.send_json({"type": "end_hint"})
                # No response expected on speech WS

            # Verify no translation record was created
            resp = client.get(f"/api/translations?meeting_id={mid}")
            assert resp.status_code == 200, (
                f"GET /api/translations?meeting_id={mid} failed: "
                f"{resp.status_code}"
            )
            data = resp.json()
            data_field = data.get("data", {})
            entries = data_field.get("entries", [])
            # There may be seed data records from other seats — the check
            # is that no record exists for this specific seat.
            seat_entries = [e for e in entries if e.get("seat_id") == 1]
            assert len(seat_entries) == 0, (
                f"Expected no records for seat after end_hint without audio, "
                f"got {len(seat_entries)}"
            )

    # ── Phase 5: binary-before-start guard ──────────────────────────────────

    def test_binary_before_start_no_db_write(self) -> None:
        """Binary PCM before 'start' → SPEECH_WS_NOT_STARTED error, no DB write.

        Phase 5 fix: binary frames received before 'start' must NOT:
            - buffer audio
            - run ASR
            - generate final records

        Per requirement: explicitly return SPEECH_WS_NOT_STARTED error.
        """
        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=1"
            ) as ws:
                # Send binary PCM WITHOUT sending 'start'
                ws.send_bytes(b"\x00" * 3200)

                # Must receive SPEECH_WS_NOT_STARTED error
                error = ws.receive_json()
                assert error.get("type") == "error", (
                    f"Expected error, got: {error}"
                )
                assert error.get("code") == "SPEECH_WS_NOT_STARTED", (
                    f"Expected SPEECH_WS_NOT_STARTED, got: {error}"
                )

                # Send end_hint — must be a safe no-op
                ws.send_json({"type": "end_hint"})

            # Verify no translation records were created
            resp = client.get(f"/api/translations?meeting_id={mid}")
            assert resp.status_code == 200
            data = resp.json()
            data_field = data.get("data", {})
            entries = data_field.get("entries", [])
            # No records should exist for this meeting
            assert len(entries) == 0, (
                f"Expected no translation records after binary-before-start, "
                f"got {len(entries)}: {entries}"
            )

    # ── Phase 5: speaker seat hard switch ────────────────────────────────────

    def test_speaker_switch_cancels_old_interim(self) -> None:
        """Speaker switch from seat 1 to seat 2 → cancelled event + no DB write.

        Per WEBSOCKET_PROTOCOL §7:
            - Old seat speech WS is closed
            - Pending interim is discarded (not persisted)
            - translation_interim_cancelled broadcast with reason="speaker_seat_changed"
            - New speaker seat can connect and start
        """
        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            # Connect speech WS for seat 1
            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=1"
            ) as speech_ws:
                # Start utterance and get utterance_id
                speech_ws.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started = speech_ws.receive_json()
                assert started["type"] == "started"
                uid1 = started["utterance_id"]

                # Send some audio (5 frames = 500ms) WITHOUT end_hint
                frames = _load_pcm16_frames(count=5)
                for frame in frames:
                    speech_ws.send_bytes(frame)

                # Connect broadcast channel to observe events
                with client.websocket_connect(f"/ws/{mid}") as broadcast_ws:
                    broadcast_ws.receive_json()  # consume "connected"

                    # SWITCH: set speaker seat to 2 (without ending utterance on 1)
                    _set_speaker_seat(client, 2)

                    # Collect events until translation_interim_cancelled arrives.
                    # Interim events from the 5 frames may arrive first.
                    cancelled = None
                    for _attempt in range(50):
                        msg = broadcast_ws.receive_json()
                        if msg["event"] == "translation_interim_cancelled":
                            cancelled = msg
                            break

                    assert cancelled is not None, (
                        "No translation_interim_cancelled event received "
                        "after speaker switch"
                    )

                    # Verify cancelled payload
                    payload = cancelled["payload"]
                    assert payload["seat_id"] == 1, (
                        f"Expected seat_id=1, got: {payload}"
                    )
                    assert payload["reason"] == "speaker_seat_changed", (
                        f"Expected reason='speaker_seat_changed', "
                        f"got: {payload.get('reason')}"
                    )
                    # The utterance_id should match the cancelled utterance
                    assert payload["utterance_id"] == uid1, (
                        f"Expected utterance_id={uid1}, "
                        f"got: {payload.get('utterance_id')}"
                    )

                    # Verify broadcast format per §5
                    assert cancelled["meeting_id"] == mid
                    assert isinstance(cancelled["timestamp"], int)

            # Old speech WS is now disconnected (context manager exited).
            # Verify no translation records were persisted for the cancelled utterance.
            resp = client.get(f"/api/translations?meeting_id={mid}")
            assert resp.status_code == 200
            data = resp.json()
            data_field = data.get("data", {})
            entries = data_field.get("entries", [])
            matches = [e for e in entries if e.get("utterance_id") == uid1]
            assert len(matches) == 0, (
                f"Cancelled utterance {uid1} should not be persisted, "
                f"found {len(matches)} record(s): {matches}"
            )

            # New speaker seat (2) can connect and start a new utterance
            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=2"
            ) as new_ws:
                new_ws.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started2 = new_ws.receive_json()
                assert started2["type"] == "started"
                uid2: str = started2["utterance_id"]
                # Must be a different utterance_id from the cancelled one
                assert uid2 != uid1, (
                    f"New utterance_id should differ from cancelled one: {uid2}"
                )
                assert re.match(rf"utt_{mid}_2_\d{{6}}", uid2), (
                    f"utterance_id '{uid2}' does not match pattern "
                    f"for seat 2"
                )

    def test_clear_speaker_cancels_interim(self) -> None:
        """Clear speaker seat → cancelled event + no DB write.

        Per WEBSOCKET_PROTOCOL §7: clearing the speaker seat is also a hard
        switch — old speech WS is closed, interim cancelled.
        """
        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=1"
            ) as speech_ws:
                speech_ws.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started = speech_ws.receive_json()
                assert started["type"] == "started"
                uid1 = started["utterance_id"]

                frames = _load_pcm16_frames(count=5)
                for frame in frames:
                    speech_ws.send_bytes(frame)

                with client.websocket_connect(f"/ws/{mid}") as broadcast_ws:
                    broadcast_ws.receive_json()  # "connected"

                    # CLEAR: delete the speaker seat
                    resp = client.delete("/api/seats/speaker")
                    assert resp.status_code == 200

                    cancelled = None
                    for _attempt in range(50):
                        msg = broadcast_ws.receive_json()
                        if msg["event"] == "translation_interim_cancelled":
                            cancelled = msg
                            break

                    assert cancelled is not None, (
                        "No translation_interim_cancelled after clear speaker"
                    )
                    assert cancelled["payload"]["seat_id"] == 1
                    assert (
                        cancelled["payload"]["reason"] == "speaker_seat_changed"
                    )
                    assert cancelled["payload"]["utterance_id"] == uid1

            # Verify no persistence of cancelled utterance
            resp = client.get(f"/api/translations?meeting_id={mid}")
            data = resp.json()
            entries = data.get("data", {}).get("entries", [])
            matches = [e for e in entries if e.get("utterance_id") == uid1]
            assert len(matches) == 0

    def test_new_speaker_can_connect_after_switch(self) -> None:
        """After speaker switch, new seat can open /ws/speech and start.

        Verifies the full cycle: set seat 1 → seat 2 → seat 3,
        each new seat can connect and start successfully.
        """
        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            # Set speaker to seat 2 — old seat 1 may or may not have a WS
            _set_speaker_seat(client, 2)

            # Connect new speaker seat and verify it works
            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=2"
            ) as ws:
                ws.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started = ws.receive_json()
                assert started["type"] == "started"
                assert re.match(rf"utt_{mid}_2_\d{{6}}", started["utterance_id"])

            # Switch to seat 3 — seat 2 had/has a WS connection
            _set_speaker_seat(client, 3)

            # Seat 3 can also connect and start
            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=3"
            ) as ws3:
                ws3.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started3 = ws3.receive_json()
                assert started3["type"] == "started"
                assert re.match(rf"utt_{mid}_3_\d{{6}}", started3["utterance_id"])

    # ── Phase 5 acceptance: duplicate connection ────────────────────────────

    def test_duplicate_speech_ws_connection_closes_old(self) -> None:
        """Second WS for same (meeting_id, seat_id) invalidates the first.

        Per requirement: old WS must not be able to continue start/binary/
        end_hint after a duplicate connection. No stale speech WS allowed.
        """
        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=1"
            ) as ws1:
                # ws1 starts utterance and sends audio
                ws1.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started1 = ws1.receive_json()
                assert started1["type"] == "started"
                uid1 = started1["utterance_id"]

                frames = _load_pcm16_frames(count=5)
                for frame in frames:
                    ws1.send_bytes(frame)

                # Second connection for SAME seat — ws1 must be invalidated
                with client.websocket_connect(
                    f"/ws/speech/{mid}?seat=1"
                ) as ws2:
                    ws2.send_json({
                        "type": "start",
                        "sample_rate": 16000,
                        "encoding": "pcm_s16le",
                        "channels": 1,
                    })
                    started2 = ws2.receive_json()
                    assert started2["type"] == "started"
                    uid2 = started2["utterance_id"]
                    # Phase 5: sequence is global per (meeting, seat), so
                    # reconnections get monotonically increasing IDs.
                    assert re.match(rf"utt_{mid}_1_\d{{6}}", uid2)
                    assert uid2 != uid1, (
                        f"Reconnected utterance_id {uid2} "
                        f"must differ from {uid1}"
                    )

                    # Try to end_hint on ws1 — must be dropped (invalidated)
                    try:
                        ws1.send_json({"type": "end_hint"})
                    except Exception:
                        pass

                # uid1 must NOT be in DB (old WS was invalidated)
                resp = client.get(f"/api/translations?meeting_id={mid}")
                assert resp.status_code == 200
                entries = resp.json().get("data", {}).get("entries", [])
                matches_old = [
                    e for e in entries if e.get("utterance_id") == uid1
                ]
                assert len(matches_old) == 0, (
                    f"Old WS utterance {uid1} persisted after duplicate "
                    f"connection: {matches_old}"
                )

    # ── Phase 5 acceptance: post-switch message rejection ───────────────────

    def test_old_speech_ws_rejects_messages_after_speaker_switch(self) -> None:
        """After speaker seat switch, old WS messages do not produce records.

        Per requirement: seat 1 speech WS start + audio → switch to seat 2 →
        seat 1 sends binary and end_hint → no final, no DB write.
        """
        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=1"
            ) as speech_ws:
                # Start utterance and stream audio
                speech_ws.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started = speech_ws.receive_json()
                assert started["type"] == "started"
                uid1 = started["utterance_id"]

                frames = _load_pcm16_frames(count=10)
                for frame in frames:
                    speech_ws.send_bytes(frame)

                # Switch speaker to seat 2 — seat 1 is no longer speaker
                _set_speaker_seat(client, 2)

                # Seat 1 WS tries to end_hint after being invalidated
                # Must NOT produce a final record.
                try:
                    speech_ws.send_json({"type": "end_hint"})
                except Exception:
                    pass

            # Verify no persistence for the old seat's utterance
            resp = client.get(f"/api/translations?meeting_id={mid}")
            assert resp.status_code == 200
            entries = resp.json().get("data", {}).get("entries", [])
            matches = [e for e in entries if e.get("utterance_id") == uid1]
            assert len(matches) == 0, (
                f"Old speaker seat utterance {uid1} persisted after switch: "
                f"{matches}"
            )

            # New speaker seat 2 should be able to connect and work
            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=2"
            ) as ws2:
                ws2.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started2 = ws2.receive_json()
                assert started2["type"] == "started"

    # ── Phase 5 acceptance: identity-safe session cleanup ─────────────────

    def test_duplicate_ws_identity_safe_cleanup_preserves_new_session(
        self,
    ) -> None:
        """Duplicate WS does not corrupt sessions — new WS finalizes correctly.

        Verifies:
            1. ws1 connects, starts utterance, sends audio.
            2. ws2 connects (same seat) — replaces ws1's session.
            3. ws1's finally calls remove_session with old token — identity-safe
               check prevents deletion of ws2's session.
            4. ws2 sends end_hint → final record with ws2's utterance_id
               appears in GET /api/translations.
            5. ws1's utterance_id is NOT persisted.
        """
        with TestClient(app) as client:
            mid = _create_meeting(client)
            _set_speaker_seat(client, 1)

            # ws1: first connection for seat 1
            with client.websocket_connect(
                f"/ws/speech/{mid}?seat=1"
            ) as ws1:
                ws1.send_json({
                    "type": "start",
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "channels": 1,
                })
                started1 = ws1.receive_json()
                assert started1["type"] == "started"
                uid1 = started1["utterance_id"]

                frames = _load_pcm16_frames(count=5)
                for frame in frames:
                    ws1.send_bytes(frame)

                # ws2: second connection (same seat) — replaces ws1's session
                with client.websocket_connect(
                    f"/ws/speech/{mid}?seat=1"
                ) as ws2:
                    ws2.send_json({
                        "type": "start",
                        "sample_rate": 16000,
                        "encoding": "pcm_s16le",
                        "channels": 1,
                    })
                    started2 = ws2.receive_json()
                    assert started2["type"] == "started"
                    uid2 = started2["utterance_id"]
                    assert uid2 != uid1, (
                        f"Reconnected uid {uid2} must differ from {uid1}"
                    )

                    frames2 = _load_pcm16_frames(count=10)
                    for frame in frames2:
                        ws2.send_bytes(frame)

                    # Close ws1 explicitly while ws2's connection is active.
                    # This triggers ws1's handler cleanup (identity-safe
                    # remove_session with ws1's token — must not affect ws2).
                    ws1.close()

                    # ws2 finalizes — must produce a DB record
                    ws2.send_json({"type": "end_hint"})

                # ws2's with block exited (connection closed)
            # ws1's with block exited (already closed above)

            # Verify: uid2 persisted, uid1 did NOT.
            # Cross-session sequence guarantees uid1 != uid2, so we can
            # distinguish them in the DB.
            resp = client.get(f"/api/translations?meeting_id={mid}")
            assert resp.status_code == 200
            entries = resp.json().get("data", {}).get("entries", [])

            matches_uid1 = [
                e for e in entries if e.get("utterance_id") == uid1
            ]
            matches_uid2 = [
                e for e in entries if e.get("utterance_id") == uid2
            ]

            assert len(matches_uid1) == 0, (
                f"Old ws1 utterance {uid1} should NOT be persisted: "
                f"{matches_uid1}"
            )
            assert len(matches_uid2) >= 1, (
                f"ws2 utterance {uid2} should be persisted after "
                f"duplicate-connect + finalize, got {entries}"
            )
            assert len(matches_uid2) == 1, (
                f"Expected exactly 1 record for utterance {uid2}, "
                f"got {len(matches_uid2)}: {matches_uid2}"
            )
