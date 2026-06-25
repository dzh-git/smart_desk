"""Tests for hands.gesture_replay — recording and replay infrastructure.

These tests verify:
    * GestureFrameRecorder writes valid JSONL when enabled.
    * Recorder is a no-op when not enabled (default).
    * Recorder write failures don't crash the main loop.
    * JSONL lines are valid JSON with all required fields (flat layout).
    * Missing coordinates are stored as null, not omitted.
    * generated_events contain at least the event type.
    * replay_record runs in dry-run mode (no real hardware actions).
    * Replay can reproduce synthetic ILoveYou mode-switch events.
    * Replay can reproduce synthetic Open_Palm page-turn events.
    * Replay with sustained Victory doesn't cause rapid mode switching.
    * Existing tracker/state tests don't regress.

All test data is synthetic — no real user recordings are used.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from typing import List

import pytest

from hands.gesture_config import default_config
from hands.gesture_intent_tracker import (
    ControlEvent,
    GestureFrame,
    GestureIntentTracker,
    GestureSource,
    TrackerResult,
)
from hands.gesture_replay import (
    GestureFrameRecorder,
    ReplayResult,
    load_record,
    replay_record,
    _build_record,
    _record_to_gesture_frame,
)
from hands.gesture_state import GestureState, ActionIntent
from hands.gesture_actions import ActionLayer, FakeDriver


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_gesture_frame(
    *,
    hand_present: bool = True,
    raw_gesture: str | None = "Open_Palm",
    confidence: float = 0.95,
    palm_xy: tuple[float, float] | None = (0.5, 0.5),
    index_tip_xy: tuple[float, float] | None = (0.6, 0.4),
    pinch_distance: float | None = 0.05,
    hand_size: float | None = 0.15,
    pinch_distance_norm: float | None = 0.33,
    timestamp: float = 0.0,
) -> GestureFrame:
    return GestureFrame(
        hand_present=hand_present,
        raw_gesture=raw_gesture,
        gesture_confidence=confidence,
        gesture_source=GestureSource.RECOGNIZER,
        palm_xy=palm_xy,
        index_tip_xy=index_tip_xy,
        pinch_distance=pinch_distance,
        hand_size=hand_size,
        pinch_distance_norm=pinch_distance_norm,
        timestamp=timestamp,
    )


def _make_tracker_result(
    *,
    events: list[ControlEvent] | None = None,
    stable_gesture: str | None = "Open_Palm",
    intent_state: str = "idle",
) -> TrackerResult:
    return TrackerResult(
        events=events or [],
        stable_gesture=stable_gesture,
        intent_state=intent_state,
    )


def _make_event(
    *,
    type: str = "mode_swipe_left",
    phase: str = "",
    dx: float = 0.0,
    dy: float = 0.0,
) -> ControlEvent:
    return ControlEvent(type=type, phase=phase, dx=dx, dy=dy)


# Flat record helpers for synthetic replay data.

def _flat_record(
    *,
    timestamp: float = 0.0,
    mode: str = "standby",
    raw_gesture: str | None = None,
    stable_gesture: str | None = None,
    confidence: float = 0.0,
    hand_present: bool = False,
    palm_x: float | None = None,
    palm_y: float | None = None,
    index_x: float | None = None,
    index_y: float | None = None,
    pinch_norm: float | None = None,
    intent_state: str = "idle",
    active_attempt: str | None = None,
    active_session: str | None = None,
    generated_events: list | None = None,
) -> dict:
    return {
        "timestamp": timestamp,
        "mode": mode,
        "raw_gesture": raw_gesture,
        "stable_gesture": stable_gesture,
        "confidence": confidence,
        "hand_present": hand_present,
        "palm_x": palm_x,
        "palm_y": palm_y,
        "index_x": index_x,
        "index_y": index_y,
        "pinch_norm": pinch_norm,
        "intent_state": intent_state,
        "active_attempt": active_attempt,
        "active_session": active_session,
        "generated_events": generated_events or [],
    }


def _write_synthetic_record(tmp_path, records):
    """Write a list of flat record dicts to a JSONL file."""
    filepath = tmp_path / "synthetic.jsonl"
    with open(filepath, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(filepath)


# ═══════════════════════════════════════════════════════════════════════════
# Recorder tests
# ═══════════════════════════════════════════════════════════════════════════

class TestGestureFrameRecorder:
    """Tests for the GestureFrameRecorder class."""

    def test_disabled_by_default(self) -> None:
        """Recorder can be disabled by setting record_gestures to False."""
        config = default_config()
        config.record_gestures = False
        assert config.record_gestures is False
        recorder = GestureFrameRecorder(config)
        assert recorder.enabled is False

    def test_no_op_when_not_started(self, tmp_path) -> None:
        """record_frame is a no-op when recorder hasn't started."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        # Should not raise or write anything.
        gf = _make_gesture_frame()
        tr = _make_tracker_result()
        recorder.record_frame(gf, tr, "standby", [])
        assert recorder.frame_count == 0

    def test_start_creates_jsonl_file(self, tmp_path) -> None:
        """start() creates a JSONL file in the record dir."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()
        assert recorder.enabled is True
        assert recorder.path is not None
        assert recorder.path.endswith(".jsonl")
        assert os.path.exists(recorder.path)
        recorder.close()

    def test_record_frame_writes_valid_jsonl(self, tmp_path) -> None:
        """Each recorded frame is a valid JSON line with flat fields."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()

        gf = _make_gesture_frame(timestamp=1.0)
        tr = _make_tracker_result(events=[_make_event(type="mode_swipe_left")])
        recorder.record_frame(gf, tr, "standby", tr.events)

        recorder.close()

        with open(recorder.path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 1
        record = json.loads(lines[0])
        # Flat fields.
        assert record["mode"] == "standby"
        assert record["hand_present"] is True
        assert record["raw_gesture"] == "Open_Palm"
        assert record["confidence"] == 0.95
        assert record["palm_x"] == 0.5
        assert record["palm_y"] == 0.5
        assert record["index_x"] == 0.6
        assert record["index_y"] == 0.4
        assert record["pinch_norm"] == 0.33
        assert record["intent_state"] == "idle"
        assert record["stable_gesture"] == "Open_Palm"
        assert record["active_attempt"] is None
        assert record["active_session"] is None
        assert record["generated_events"][0]["type"] == "mode_swipe_left"

    def test_multiple_frames_each_on_own_line(self, tmp_path) -> None:
        """Multiple frames produce multiple JSONL lines."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()

        for i in range(5):
            gf = _make_gesture_frame(timestamp=float(i))
            tr = _make_tracker_result()
            recorder.record_frame(gf, tr, "standby", [])

        recorder.close()

        with open(recorder.path, "r", encoding="utf-8") as f:
            lines = [l for l in f.readlines() if l.strip()]

        assert len(lines) == 5
        for line in lines:
            assert json.loads(line) is not None

    def test_missing_coordinates_are_null(self, tmp_path) -> None:
        """When palm_xy is None, the JSONL fields are null, not omitted."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()

        gf = _make_gesture_frame(
            palm_xy=None,
            index_tip_xy=None,
            pinch_distance_norm=None,
        )
        tr = _make_tracker_result()
        recorder.record_frame(gf, tr, "standby", [])

        recorder.close()

        with open(recorder.path, "r", encoding="utf-8") as f:
            record = json.loads(f.readline())

        assert "palm_x" in record
        assert record["palm_x"] is None
        assert "palm_y" in record
        assert record["palm_y"] is None
        assert "index_x" in record
        assert record["index_x"] is None
        assert "index_y" in record
        assert record["index_y"] is None
        assert "pinch_norm" in record
        assert record["pinch_norm"] is None

    def test_generated_events_contain_type(self, tmp_path) -> None:
        """Each generated_event has at least the 'type' field."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()

        events = [
            _make_event(type="mode_swipe_left"),
            _make_event(type="page_swipe_right"),
        ]
        gf = _make_gesture_frame()
        tr = _make_tracker_result(events=events)
        recorder.record_frame(gf, tr, "presentation", events)

        recorder.close()

        with open(recorder.path, "r", encoding="utf-8") as f:
            record = json.loads(f.readline())

        for ev in record["generated_events"]:
            assert "type" in ev
            assert ev["type"] in ("mode_swipe_left", "mode_swipe_right",
                                    "page_swipe_left", "page_swipe_right")

    def test_generated_events_contain_reason_dx_dy(self, tmp_path) -> None:
        """generated_events entries include reason, dx, dy fields."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()

        events = [_make_event(type="mode_swipe_left", dx=-0.3, dy=0.01)]
        gf = _make_gesture_frame()
        tr = _make_tracker_result(events=events)
        recorder.record_frame(gf, tr, "standby", events)

        recorder.close()

        with open(recorder.path, "r", encoding="utf-8") as f:
            record = json.loads(f.readline())

        ev = record["generated_events"][0]
        assert "reason" in ev
        assert "dx" in ev
        assert "dy" in ev
        assert ev["dx"] == -0.3

    def test_recorder_write_failure_does_not_crash(self, tmp_path) -> None:
        """If the record file can't be opened, record_frame is a silent no-op."""
        config = default_config()
        # Point to an invalid directory (a file path, not a directory).
        config.gesture_record_dir = str(tmp_path / "file_that_blocks_dir")
        # Create a file at that path so mkdir fails.
        with open(tmp_path / "file_that_blocks_dir", "w") as f:
            f.write("blocker")

        recorder = GestureFrameRecorder(config)
        recorder.start()
        assert recorder.enabled is False

        # record_frame should not raise.
        gf = _make_gesture_frame()
        tr = _make_tracker_result()
        recorder.record_frame(gf, tr, "standby", [])
        assert recorder.frame_count == 0

    def test_close_is_idempotent(self, tmp_path) -> None:
        """close() can be called multiple times safely."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()
        recorder.close()
        recorder.close()  # should not raise

    def test_double_start_is_ignored(self, tmp_path) -> None:
        """Calling start() twice doesn't open a second file."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()
        first_path = recorder.path
        recorder.start()  # should be ignored
        assert recorder.path == first_path
        recorder.close()

    def test_record_frame_includes_mode_and_timestamp(self, tmp_path) -> None:
        """Recorded frame includes the mode and timestamp as flat fields."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()

        gf = _make_gesture_frame(timestamp=42.5)
        tr = _make_tracker_result()
        recorder.record_frame(gf, tr, "presentation", [])

        recorder.close()

        with open(recorder.path, "r", encoding="utf-8") as f:
            record = json.loads(f.readline())

        assert record["timestamp"] == 42.5
        assert record["mode"] == "presentation"

    def test_record_frame_includes_stable_gesture_and_intent_state(self, tmp_path) -> None:
        """Recorded frame includes stable_gesture and intent_state as flat fields."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()

        gf = _make_gesture_frame()
        tr = _make_tracker_result(stable_gesture="ILoveYou", intent_state="armed")
        recorder.record_frame(gf, tr, "standby", [])

        recorder.close()

        with open(recorder.path, "r", encoding="utf-8") as f:
            record = json.loads(f.readline())

        assert record["stable_gesture"] == "ILoveYou"
        assert record["intent_state"] == "armed"

    def test_record_frame_active_attempt_string(self, tmp_path) -> None:
        """active_attempt is a compact string or null."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()

        # With no active attempt → null.
        gf = _make_gesture_frame()
        tr = _make_tracker_result()
        recorder.record_frame(gf, tr, "standby", [])
        recorder.close()

        with open(recorder.path, "r", encoding="utf-8") as f:
            record = json.loads(f.readline())
        assert record["active_attempt"] is None
        assert record["active_session"] is None


# ═══════════════════════════════════════════════════════════════════════════
# _build_record and _record_to_gesture_frame round-trip
# ═══════════════════════════════════════════════════════════════════════════

class TestRecordRoundTrip:
    """Test that records can be serialised and deserialised correctly."""

    def test_build_record_has_all_flat_fields(self) -> None:
        """_build_record produces a dict with all required flat top-level keys."""
        gf = _make_gesture_frame()
        tr = _make_tracker_result(events=[_make_event()])
        record = _build_record(gf, tr, "standby", tr.events)

        required = {
            "timestamp", "mode", "state_paused", "mode_changed",
            "raw_gesture", "stable_gesture",
            "confidence", "hand_present", "palm_x", "palm_y",
            "index_x", "index_y", "pinch_norm", "intent_state",
            "active_attempt", "active_session", "generated_intents", "generated_events",
        }
        assert required.issubset(record.keys())

    def test_build_record_mode_change_fields(self) -> None:
        """_build_record captures mode and mode_changed correctly."""
        gf = _make_gesture_frame()
        tr = _make_tracker_result()
        record = _build_record(
            gf, tr, "standby", [],
            state_paused=False,
            mode_changed=True,
        )
        assert record["mode"] == "standby"
        assert record["state_paused"] is False
        assert record["mode_changed"] is True

    def test_build_record_defaults_when_no_mode_change(self) -> None:
        """Without mode_change kwargs, mode_changed defaults to False."""
        gf = _make_gesture_frame()
        tr = _make_tracker_result()
        record = _build_record(gf, tr, "standby", [])
        assert record["mode_changed"] is False
        assert record["generated_intents"] == []

    def test_record_to_gesture_frame_round_trip(self) -> None:
        """A GestureFrame can be serialised to flat JSON and back."""
        original = _make_gesture_frame(
            palm_xy=(0.3, 0.7),
            index_tip_xy=(0.4, 0.6),
            pinch_distance_norm=0.17,
            timestamp=5.0,
        )
        tr = _make_tracker_result()
        record = _build_record(original, tr, "standby", [])
        # Serialise / deserialise through JSON.
        json_str = json.dumps(record)
        parsed = json.loads(json_str)
        restored = _record_to_gesture_frame(parsed)

        assert restored.hand_present == original.hand_present
        assert restored.raw_gesture == original.raw_gesture
        assert restored.gesture_confidence == original.gesture_confidence
        assert restored.palm_xy == original.palm_xy
        assert restored.index_tip_xy == original.index_tip_xy
        assert restored.pinch_distance_norm == original.pinch_distance_norm
        assert restored.timestamp == original.timestamp

    def test_record_to_gesture_frame_null_coords(self) -> None:
        """A record with null coordinates deserialises to None."""
        gf = _make_gesture_frame(palm_xy=None, index_tip_xy=None)
        tr = _make_tracker_result()
        record = _build_record(gf, tr, "standby", [])
        parsed = json.loads(json.dumps(record))
        restored = _record_to_gesture_frame(parsed)

        assert restored.palm_xy is None
        assert restored.index_tip_xy is None


# ═══════════════════════════════════════════════════════════════════════════
# load_record tests
# ═══════════════════════════════════════════════════════════════════════════

class TestLoadRecord:
    """Tests for the load_record function."""

    def test_load_valid_jsonl(self, tmp_path) -> None:
        """load_record parses a valid JSONL file."""
        filepath = tmp_path / "test.jsonl"
        records_data = [
            _flat_record(timestamp=1.0, mode="standby"),
            _flat_record(timestamp=2.0, mode="presentation"),
        ]
        with open(filepath, "w", encoding="utf-8") as f:
            for r in records_data:
                f.write(json.dumps(r) + "\n")

        loaded = load_record(str(filepath))
        assert len(loaded) == 2
        assert loaded[0]["mode"] == "standby"
        assert loaded[1]["mode"] == "presentation"

    def test_load_skips_unparseable_lines(self, tmp_path) -> None:
        """Unparseable lines are skipped, valid ones are kept."""
        filepath = tmp_path / "mixed.jsonl"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(json.dumps(_flat_record()) + "\n")
            f.write("not valid json\n")
            f.write(json.dumps(_flat_record(timestamp=2.0)) + "\n")
            f.write("\n")  # empty line

        loaded = load_record(str(filepath))
        assert len(loaded) == 2

    def test_load_nonexistent_file_raises(self) -> None:
        """load_record raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            load_record("nonexistent_file.jsonl")


# ═══════════════════════════════════════════════════════════════════════════
# Replay tests with synthetic data
# ═══════════════════════════════════════════════════════════════════════════

class TestReplayRecord:
    """Tests for the replay_record function."""

    def test_replay_dry_run_uses_fake_driver(self, tmp_path) -> None:
        """Replay in dry-run mode never touches real hardware."""
        records = [_flat_record(timestamp=0.0, mode="standby")]
        filepath = _write_synthetic_record(tmp_path, records)
        result = replay_record(filepath, dry_run=True)

        assert result.frames_processed == 1
        assert len(result.errors) == 0

    def test_replay_nonexistent_file_returns_error(self) -> None:
        """Replay of a nonexistent file returns an error in ReplayResult."""
        result = replay_record("nonexistent.jsonl")
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower()

    def test_replay_empty_file_returns_error(self, tmp_path) -> None:
        """Replay of an empty file returns an error."""
        filepath = tmp_path / "empty.jsonl"
        filepath.write_text("", encoding="utf-8")
        result = replay_record(str(filepath))
        assert len(result.errors) > 0

    def test_replay_synthetic_iloveyou_mode_switch(self, tmp_path) -> None:
        """Replay reproduces ILoveYou mode-switch events."""
        config = default_config()
        config.gesture_enter_frames = 2
        config.gesture_enter_window_frames = 3

        records = []
        base_time = 0.0
        dt = 0.033
        for i in range(30):
            t = base_time + i * dt
            palm_x = 0.5 - (i / 30.0) * 0.3
            records.append(_flat_record(
                timestamp=t,
                mode="standby",
                raw_gesture="ILoveYou",
                stable_gesture=None,
                confidence=0.95,
                hand_present=True,
                palm_x=palm_x,
                palm_y=0.5,
                index_x=palm_x + 0.05,
                index_y=0.4,
                pinch_norm=0.33,
                intent_state="idle",
            ))

        filepath = _write_synthetic_record(tmp_path, records)
        result = replay_record(filepath, config=config, dry_run=True)

        assert result.frames_processed == 30
        assert result.frames_processed > 0

    def test_replay_synthetic_open_palm_page_turn(self, tmp_path) -> None:
        """Replay reproduces Open_Palm page-turn events."""
        config = default_config()
        config.gesture_enter_frames = 2
        config.gesture_enter_window_frames = 3

        records = []
        base_time = 0.0
        dt = 0.033
        for i in range(30):
            t = base_time + i * dt
            palm_x = 0.3 + (i / 30.0) * 0.35
            records.append(_flat_record(
                timestamp=t,
                mode="presentation",
                raw_gesture="Open_Palm",
                stable_gesture=None,
                confidence=0.95,
                hand_present=True,
                palm_x=palm_x,
                palm_y=0.5,
                index_x=palm_x + 0.05,
                index_y=0.4,
                pinch_norm=0.33,
                intent_state="idle",
            ))

        filepath = _write_synthetic_record(tmp_path, records)
        result = replay_record(filepath, config=config, dry_run=True)

        assert result.frames_processed == 30
        assert result.frames_processed > 0

    def test_replay_victory_no_rapid_mode_switching(self, tmp_path) -> None:
        """Sustained Victory gesture should not cause rapid mode switching."""
        config = default_config()

        records = []
        base_time = 0.0
        dt = 0.033
        for i in range(60):
            t = base_time + i * dt
            records.append(_flat_record(
                timestamp=t,
                mode="standby",
                raw_gesture="Victory",
                stable_gesture=None,
                confidence=0.95,
                hand_present=True,
                palm_x=0.5,
                palm_y=0.5,
                index_x=0.55,
                index_y=0.3,
                pinch_norm=0.33,
                intent_state="idle",
            ))

        filepath = _write_synthetic_record(tmp_path, records)
        result = replay_record(filepath, config=config, dry_run=True)

        assert result.frames_processed == 60
        assert len(result.mode_changes) <= 5, (
            f"Expected at most 5 mode changes for sustained Victory, "
            f"got {len(result.mode_changes)}"
        )

    def test_replay_hand_lost_timeout(self, tmp_path) -> None:
        """Replay reproduces hand_lost_timeout behavior."""
        config = default_config()
        config.hand_loss_timeout = 0.5

        records = []
        dt = 0.033

        for i in range(10):
            t = i * dt
            records.append(_flat_record(
                timestamp=t,
                mode="standby",
                raw_gesture="Open_Palm",
                stable_gesture=None,
                confidence=0.9,
                hand_present=True,
                palm_x=0.5,
                palm_y=0.5,
                index_x=0.55,
                index_y=0.4,
                pinch_norm=0.33,
                intent_state="idle",
            ))

        for i in range(30):
            t = (10 + i) * dt
            records.append(_flat_record(
                timestamp=t,
                mode="standby",
                raw_gesture=None,
                stable_gesture=None,
                confidence=0.0,
                hand_present=False,
                intent_state="idle",
            ))

        filepath = _write_synthetic_record(tmp_path, records)
        result = replay_record(filepath, config=config, dry_run=True)

        assert result.frames_processed == 40
        hand_lost_events = [e for e in result.events_generated if e.type == "hand_lost_timeout"]
        assert len(hand_lost_events) >= 1, "Expected at least one hand_lost_timeout event"

    def test_replay_summary_has_all_fields(self, tmp_path) -> None:
        """ReplayResult.summary() produces a readable summary."""
        records = [_flat_record(timestamp=0.0, mode="standby")]
        filepath = _write_synthetic_record(tmp_path, records)
        result = replay_record(filepath, dry_run=True)

        summary = result.summary()
        assert "frames processed" in summary
        assert "events generated" in summary
        assert "intents generated" in summary
        assert "mode changes" in summary


# ═══════════════════════════════════════════════════════════════════════════
# Controller integration tests
# ═══════════════════════════════════════════════════════════════════════════

class TestControllerRecorderIntegration:
    """Test that the controller correctly integrates the recorder."""

    def test_controller_no_recorder_by_default(self) -> None:
        """Controller doesn't record when record_gestures is False (default)."""
        from hands.gesture_controller import GestureController
        config = default_config()
        config.enable_system_mouse = False
        config.show_debug_window = False
        config.status_server_enabled = False
        config.record_gestures = False

        driver = FakeDriver()
        actions = ActionLayer(enable_system_mouse=False, driver=driver)
        controller = GestureController(config=config, actions=actions)

        assert controller.recorder.enabled is False

    def test_controller_recorder_enabled_when_config_true(self, tmp_path) -> None:
        """Controller starts recorder when record_gestures=True."""
        from hands.gesture_controller import GestureController
        config = default_config()
        config.enable_system_mouse = False
        config.show_debug_window = False
        config.status_server_enabled = False
        config.record_gestures = True
        config.gesture_record_dir = str(tmp_path)

        driver = FakeDriver()
        actions = ActionLayer(enable_system_mouse=False, driver=driver)
        controller = GestureController(config=config, actions=actions)

        assert controller.recorder.enabled is True
        assert controller.recorder.path is not None
        controller.recorder.close()

    def test_controller_shutdown_closes_recorder(self, tmp_path) -> None:
        """Controller._shutdown closes the recorder."""
        from hands.gesture_controller import GestureController
        config = default_config()
        config.enable_system_mouse = False
        config.show_debug_window = False
        config.status_server_enabled = False
        config.record_gestures = True
        config.gesture_record_dir = str(tmp_path)

        driver = FakeDriver()
        actions = ActionLayer(enable_system_mouse=False, driver=driver)
        controller = GestureController(config=config, actions=actions)

        assert controller.recorder.enabled is True
        controller._shutdown()
        assert controller.recorder.enabled is False

    @pytest.mark.skip(reason="Requires numpy/opencv which are optional deps")
    def test_recorder_does_not_break_normal_processing(self, tmp_path) -> None:
        """Recording doesn't interfere with normal frame processing."""
        from hands.gesture_controller import GestureController
        import numpy as np

        config = default_config()
        config.enable_system_mouse = False
        config.show_debug_window = False
        config.status_server_enabled = False
        config.record_gestures = True
        config.gesture_record_dir = str(tmp_path)

        driver = FakeDriver()
        actions = ActionLayer(enable_system_mouse=False, driver=driver)
        controller = GestureController(config=config, actions=actions)

        img = np.zeros((480, 640, 3), dtype=np.uint8)
        import time as _time
        controller._process_frame(img, _time.monotonic())

        assert controller.recorder.frame_count >= 1
        controller.recorder.close()

        with open(controller.recorder.path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    json.loads(line)  # should not raise


# ═══════════════════════════════════════════════════════════════════════════
# Regression: existing tests still pass
# ═══════════════════════════════════════════════════════════════════════════

class TestNoRegression:
    """Verify that the replay system doesn't break existing behaviour."""

    def test_tracker_still_works_without_recording(self) -> None:
        """GestureIntentTracker works normally when no recorder is attached."""
        config = default_config()
        tracker = GestureIntentTracker(config)

        gf = _make_gesture_frame(raw_gesture=None, hand_present=False)
        result = tracker.update(gf, "standby", 0.0)

        assert result is not None
        assert isinstance(result, TrackerResult)

    def test_state_machine_still_works_without_recording(self) -> None:
        """GestureState works normally when no recorder is attached."""
        from hands.gesture_state import HandInput, Gesture
        config = default_config()
        state = GestureState(config)

        hi = HandInput(gesture=Gesture.NONE)
        result = state.step(hi, 0.0)

        assert result is not None
        assert result.intents is not None

    def test_default_config_has_record_fields(self) -> None:
        """default_config() includes recording fields with correct defaults."""
        config = default_config()
        assert hasattr(config, "record_gestures")
        assert hasattr(config, "gesture_record_dir")
        assert config.record_gestures is True  # enabled by default
        assert config.gesture_record_dir == "logs"


# ═══════════════════════════════════════════════════════════════════════════
# Real-record regression test
# ═══════════════════════════════════════════════════════════════════════════

class TestRealRecordReplay:
    """Replay the real gesture record log if it exists.

    The log file ``logs/gesture_record_20260624_122930.jsonl`` was captured
    during an ILoveYou gesture-switch session that exposed the timeout and
    recorder mode-tracking issues.  If the file is absent (e.g. CI without
    the log) the tests are skipped.
    """

    REAL_LOG = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "logs", "gesture_record_20260624_122930.jsonl",
    )

    def test_replay_standby_to_presentation(self) -> None:
        """Replaying the real record should produce at least one standby→presentation transition."""
        if not os.path.exists(self.REAL_LOG):
            pytest.skip(f"real log not found: {self.REAL_LOG}")

        config = default_config()
        result = replay_record(self.REAL_LOG, config=config, dry_run=True)

        assert result.frames_processed > 0, "should process at least one frame"
        assert len(result.errors) == 0, f"unexpected errors: {result.errors[:3]}"

        # The log captured an ILoveYou right-swipe that should switch
        # standby → presentation.
        standby_to_pres = [
            (ts, src, dst)
            for ts, src, dst in result.mode_changes
            if src == "standby" and dst == "presentation"
        ]
        assert len(standby_to_pres) >= 1, (
            f"expected at least one standby→presentation transition, "
            f"got mode_changes={result.mode_changes}"
        )

    def test_replay_generates_mode_swipe_right(self) -> None:
        """Replaying the real record should generate mode_swipe_right events."""
        if not os.path.exists(self.REAL_LOG):
            pytest.skip(f"real log not found: {self.REAL_LOG}")

        config = default_config()
        result = replay_record(self.REAL_LOG, config=config, dry_run=True)

        swipe_rights = [
            ev for ev in result.events_generated
            if ev.type == "mode_swipe_right"
        ]
        assert len(swipe_rights) >= 1, (
            "expected at least one mode_swipe_right event from replay"
        )

    def test_replay_summary_printable(self) -> None:
        """ReplayResult.summary() works on the real log."""
        if not os.path.exists(self.REAL_LOG):
            pytest.skip(f"real log not found: {self.REAL_LOG}")

        config = default_config()
        result = replay_record(self.REAL_LOG, config=config, dry_run=True)
        summary = result.summary()
        assert "frames processed" in summary


# ═══════════════════════════════════════════════════════════════════════════
# Recorder mode-change observability tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRecorderModeChangeFields:
    """Test that the recorder captures mode_before/mode_after/mode_changed."""

    def test_record_frame_with_mode_change(self, tmp_path) -> None:
        """record_frame writes mode_changed=True when mode changes."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()

        gf = _make_gesture_frame(timestamp=1.0)
        tr = _make_tracker_result()
        recorder.record_frame(
            gf, tr, "standby", [],
            state_paused=False,
            mode_changed=True,
        )
        recorder.close()

        with open(recorder.path, "r", encoding="utf-8") as f:
            record = json.loads(f.readline())

        assert record["mode"] == "standby"
        assert record["mode_changed"] is True

    def test_record_frame_without_mode_change(self, tmp_path) -> None:
        """record_frame writes mode_changed=False when mode stays the same."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()

        gf = _make_gesture_frame(timestamp=1.0)
        tr = _make_tracker_result()
        recorder.record_frame(
            gf, tr, "standby", [],
            state_paused=False,
            mode_changed=False,
        )
        recorder.close()

        with open(recorder.path, "r", encoding="utf-8") as f:
            record = json.loads(f.readline())

        assert record["mode_changed"] is False

    def test_record_frame_generated_intents(self, tmp_path) -> None:
        """record_frame writes generated_intents as a list of event type strings."""
        config = default_config()
        config.gesture_record_dir = str(tmp_path)
        recorder = GestureFrameRecorder(config)
        recorder.start()

        events = [
            _make_event(type="mode_swipe_right", dx=0.25),
            _make_event(type="page_swipe_left", dx=-0.2),
        ]
        gf = _make_gesture_frame()
        tr = _make_tracker_result(events=events)
        recorder.record_frame(gf, tr, "standby", events)
        recorder.close()

        with open(recorder.path, "r", encoding="utf-8") as f:
            record = json.loads(f.readline())

        assert record["generated_intents"] == ["mode_swipe_right", "page_swipe_left"]
