"""Gesture Replay System — record and replay gesture frames for issue reproduction.

This module provides two components:

1. **GestureFrameRecorder** — attached to the controller's ``_process_frame``
   loop.  When recording is enabled, writes one JSON line per frame to
   ``logs/gesture_record_*.jsonl``.  Each line contains the full GestureFrame,
   the TrackerResult summary, the current mode, and the generated events.

2. **replay_record** — reads a JSONL record file, reconstructs GestureFrame
   objects, feeds them through ``GestureIntentTracker.update`` and
   ``GestureState.step``, and collects the resulting intents.  By default
   runs in **dry-run mode** — no real mouse/keyboard actions are executed.

Design constraints:
    * Recording files are written only to ``logs/``.
    * Recorder write failures never interrupt the main loop.
    * Replay never calls real hardware — it uses FakeDriver internally.
    * Missing coordinate fields in JSONL are stored as ``null``, not omitted.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Tuple

from .gesture_config import GestureConfig, default_config
from .gesture_intent_tracker import (
    ControlEvent,
    GestureFrame,
    GestureIntentTracker,
    GestureSource,
    TrackerResult,
)
from .gesture_state import ActionIntent, GestureState, StepResult
from .gesture_actions import ActionLayer, FakeDriver

logger = logging.getLogger("hands.replay")


# ═══════════════════════════════════════════════════════════════════════════
# Recording
# ═══════════════════════════════════════════════════════════════════════════

class GestureFrameRecorder:
    """Records per-frame gesture data to a JSONL file.

    Lifecycle:
        recorder = GestureFrameRecorder(config)
        recorder.start()                # opens file
        recorder.record_frame(...)      # one call per frame
        recorder.close()                # flush + close

    If ``start()`` fails (e.g. directory not writable), all subsequent
    ``record_frame`` calls become no-ops.  The main loop is never interrupted.
    """

    def __init__(self, config: Optional[GestureConfig] = None) -> None:
        self.config = config or default_config()
        self._file = None
        self._path: Optional[str] = None
        self._enabled = False
        self._frame_count = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def start(self) -> None:
        """Open a new JSONL file for recording.

        If the file cannot be opened, ``enabled`` stays False and all
        ``record_frame`` calls are no-ops.
        """
        if self._enabled:
            logger.warning("recorder already active — ignoring start()")
            return

        record_dir = self.config.gesture_record_dir
        if not record_dir:
            record_dir = "logs"

        try:
            os.makedirs(record_dir, exist_ok=True)
        except OSError as exc:
            logger.error("cannot create record dir %s: %s", record_dir, exc)
            return

        filename = f"gesture_record_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        filepath = os.path.join(record_dir, filename)

        try:
            self._file = open(filepath, "w", encoding="utf-8")
            self._path = filepath
            self._enabled = True
            self._frame_count = 0
            logger.info("gesture recording started: %s", filepath)
        except OSError as exc:
            logger.error("cannot open record file %s: %s", filepath, exc)
            self._file = None
            self._path = None
            self._enabled = False

    def record_frame(
        self,
        gesture_frame: GestureFrame,
        tracker_result: TrackerResult,
        mode: str,
        generated_events: List[ControlEvent],
        *,
        mode_after: Optional[str] = None,
        state_result_mode: Optional[str] = None,
        state_paused: Optional[bool] = None,
        mode_changed: bool = False,
    ) -> None:
        """Write one frame's data as a JSON line.

        ``mode`` is the mode **before** ``GestureState.step()``; ``mode_after``
        is the mode after.  ``mode_changed`` is True when they differ.

        Failures are logged but never raised — the main loop must not break.
        """
        if not self._enabled or self._file is None:
            return

        try:
            record = _build_record(
                gesture_frame, tracker_result, mode, generated_events,
                mode_after=mode_after,
                state_result_mode=state_result_mode,
                state_paused=state_paused,
                mode_changed=mode_changed,
            )
            line = json.dumps(record, ensure_ascii=False, default=_json_default)
            self._file.write(line + "\n")
            self._file.flush()
            self._frame_count += 1
        except Exception as exc:
            # Never let recording break the main loop.
            logger.warning("record_frame failed (frame %d): %s", self._frame_count, exc)

    def close(self) -> None:
        """Flush and close the recording file."""
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except Exception as exc:
                logger.warning("error closing record file: %s", exc)
            finally:
                self._file = None
                self._enabled = False
                logger.info(
                    "gesture recording stopped: %s (%d frames)",
                    self._path,
                    self._frame_count,
                )


def _build_record(
    gesture_frame: GestureFrame,
    tracker_result: TrackerResult,
    mode: str,
    generated_events: List[ControlEvent],
    *,
    mode_after: Optional[str] = None,
    state_result_mode: Optional[str] = None,
    state_paused: Optional[bool] = None,
    mode_changed: bool = False,
) -> Dict[str, Any]:
    """Build a flat JSON-serialisable dict for one frame.

    Field layout (flat, no nesting)::

        timestamp, mode, mode_before_state_step, mode_after_state_step,
        state_result_mode, state_paused, mode_changed,
        raw_gesture, stable_gesture, confidence,
        hand_present, palm_x, palm_y, index_x, index_y, pinch_norm,
        intent_state, active_attempt, active_session, generated_intents, generated_events

    ``mode`` (alias ``mode_before_state_step``) records the mode **before**
    ``GestureState.step()``; ``mode_after_state_step`` records it after.
    ``mode_changed`` is True when they differ.  ``generated_intents`` is a
    list of intent type strings produced by ``state.step()``.
    ``active_attempt`` is a compact ``"<intent_type>:<phase>:<id>"`` string
    or ``null``.  ``active_session`` is ``"<control_type>:<phase>:<id>"`` or
    ``null``.
    """
    gf = gesture_frame
    tr = tracker_result

    # Compact attempt string.
    att = tr.active_attempt
    if att is not None:
        active_attempt = f"{att.intent_type}:{att.phase}:{att.attempt_id}"
    else:
        active_attempt = None

    # Compact session string.
    ses = tr.active_session
    if ses is not None:
        active_session = f"{ses.control_type}:{ses.phase}:{ses.session_id}"
    else:
        active_session = None

    # Extract intent type strings from tracker_result.events (if present).
    generated_intents = [ev.type for ev in generated_events]

    return {
        "timestamp": gf.timestamp,
        "mode": mode,
        "mode_before_state_step": mode,
        "mode_after_state_step": mode_after if mode_after is not None else mode,
        "state_result_mode": state_result_mode,
        "state_paused": state_paused,
        "mode_changed": mode_changed,
        "raw_gesture": gf.raw_gesture,
        "stable_gesture": tr.stable_gesture,
        "confidence": gf.gesture_confidence,
        "hand_present": gf.hand_present,
        "palm_x": gf.palm_xy[0] if gf.palm_xy is not None else None,
        "palm_y": gf.palm_xy[1] if gf.palm_xy is not None else None,
        "index_x": gf.index_tip_xy[0] if gf.index_tip_xy is not None else None,
        "index_y": gf.index_tip_xy[1] if gf.index_tip_xy is not None else None,
        "pinch_norm": gf.pinch_distance_norm,
        "intent_state": tr.intent_state,
        "active_attempt": active_attempt,
        "active_session": active_session,
        "generated_intents": generated_intents,
        "generated_events": [
            {
                "type": ev.type,
                "phase": ev.phase,
                "reason": ev.reason,
                "dx": ev.dx,
                "dy": ev.dy,
            }
            for ev in generated_events
        ],
    }


def _json_default(obj: Any) -> Any:
    """Fallback JSON serialiser for dataclass / enum values."""
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, GestureSource):
        return obj.value
    return str(obj)


# ═══════════════════════════════════════════════════════════════════════════
# Replay
# ═══════════════════════════════════════════════════════════════════════════

class ReplayResult:
    """Summary of a replay run."""

    def __init__(self) -> None:
        self.frames_processed: int = 0
        self.events_generated: List[ControlEvent] = []
        self.intents_generated: List[ActionIntent] = []
        self.mode_changes: List[Tuple[float, str, str]] = []  # (timestamp, from, to)
        self.errors: List[str] = []

    def summary(self) -> str:
        lines = [
            f"frames processed: {self.frames_processed}",
            f"events generated: {len(self.events_generated)}",
            f"intents generated: {len(self.intents_generated)}",
            f"mode changes: {len(self.mode_changes)}",
        ]
        for ts, src, dst in self.mode_changes:
            lines.append(f"  [{ts:.3f}] {src} → {dst}")
        if self.errors:
            lines.append(f"errors: {len(self.errors)}")
            for err in self.errors:
                lines.append(f"  {err}")
        return "\n".join(lines)


def load_record(path: str) -> List[Dict[str, Any]]:
    """Load a JSONL record file and return a list of frame dicts.

    Lines that fail to parse are skipped with a warning.
    """
    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("skipping unparseable line %d in %s: %s", lineno, path, exc)
    logger.info("loaded %d frames from %s", len(records), path)
    return records


def _record_to_gesture_frame(record: Dict[str, Any]) -> GestureFrame:
    """Reconstruct a GestureFrame from a flat JSONL record dict."""
    palm_x = record.get("palm_x")
    palm_y = record.get("palm_y")
    index_x = record.get("index_x")
    index_y = record.get("index_y")

    palm_xy = (palm_x, palm_y) if palm_x is not None and palm_y is not None else None
    index_tip_xy = (index_x, index_y) if index_x is not None and index_y is not None else None

    return GestureFrame(
        hand_present=record.get("hand_present", False),
        raw_gesture=record.get("raw_gesture"),
        gesture_confidence=record.get("confidence", 0.0),
        gesture_source=GestureSource.NONE,  # not stored in flat record
        palm_xy=palm_xy,
        index_tip_xy=index_tip_xy,
        pinch_distance=None,  # not stored in flat record
        hand_size=None,       # not stored in flat record
        pinch_distance_norm=record.get("pinch_norm"),
        timestamp=record.get("timestamp", 0.0),
    )


def _record_to_mode(record: Dict[str, Any]) -> str:
    """Extract the mode from a record dict."""
    return record.get("mode", "standby")


def _record_to_events(record: Dict[str, Any]) -> List[ControlEvent]:
    """Reconstruct ControlEvent list from a flat record dict."""
    events_data = record.get("generated_events", [])
    events: List[ControlEvent] = []
    for ev_data in events_data:
        events.append(ControlEvent(
            type=ev_data.get("type", ""),
            phase=ev_data.get("phase", ""),
            dx=ev_data.get("dx", 0.0),
            dy=ev_data.get("dy", 0.0),
            reason=ev_data.get("reason", ""),
        ))
    return events


def replay_record(
    record_path: str,
    config: Optional[GestureConfig] = None,
    *,
    dry_run: bool = True,
) -> ReplayResult:
    """Replay a JSONL gesture record through the tracker and state machine.

    Args:
        record_path: Path to the JSONL record file.
        config: Optional config override.  If None, uses ``default_config()``.
        dry_run: If True (default), no real mouse/keyboard actions are executed.
                 If False, actions are dispatched via the real ActionLayer.

    Returns:
        ReplayResult with frame count, events, intents, and mode changes.
    """
    result = ReplayResult()
    config = config or default_config()

    # Load records.
    try:
        records = load_record(record_path)
    except FileNotFoundError:
        result.errors.append(f"record file not found: {record_path}")
        return result
    except Exception as exc:
        result.errors.append(f"failed to load record: {exc}")
        return result

    if not records:
        result.errors.append("record file is empty or has no parseable lines")
        return result

    # Set up tracker and state machine.
    # Disable pause_on_start so replay processes frames immediately.
    config.pause_on_start = False
    config.start_paused = False
    tracker = GestureIntentTracker(config)
    state = GestureState(config)

    # Action layer: always use FakeDriver for dry-run.
    if dry_run:
        actions = ActionLayer(enable_system_mouse=False, driver=FakeDriver())
    else:
        actions = ActionLayer(enable_system_mouse=config.enable_system_mouse)

    # Process each frame.
    for record in records:
        try:
            gf = _record_to_gesture_frame(record)
            recorded_mode = _record_to_mode(record)

            # Use recorded timestamp for tracker; fall back to sequential index.
            now = gf.timestamp if gf.timestamp > 0 else float(result.frames_processed)

            # Feed through tracker.
            tracker_result = tracker.update(gf, state.mode, now)

            # Feed through state machine.  We need a HandInput for the legacy
            # path; since replay only has GestureFrame, we pass a minimal
            # HandInput.  The event path is what matters for replay.
            from .gesture_state import HandInput
            hand_input = HandInput(
                gesture=_gesture_str_to_enum(gf.raw_gesture),
                palm_xy=gf.palm_xy,
                wave_x=gf.palm_xy[0] if gf.palm_xy else None,
                pinch_distance=gf.pinch_distance,
            )

            mode_before = state.mode
            step_result: StepResult = state.step(
                hand_input, now, events=tracker_result.events
            )

            # Collect intents (dry-run still dispatches to FakeDriver).
            actions.execute(step_result.intents)
            result.intents_generated.extend(step_result.intents)
            result.events_generated.extend(tracker_result.events)

            # Track mode changes.
            if state.mode != mode_before:
                result.mode_changes.append((now, mode_before, state.mode))

            # Reset tracker if mode changed (matches controller behaviour).
            if state.mode != mode_before:
                tracker.reset()

            result.frames_processed += 1
        except Exception as exc:
            result.errors.append(f"frame {result.frames_processed}: {exc}")
            logger.warning("replay frame %d failed: %s", result.frames_processed, exc)
            result.frames_processed += 1

    return result


def _gesture_str_to_enum(gesture_str: Optional[str]):
    """Convert a gesture string to the Gesture enum.

    Returns Gesture.NONE for unrecognised or None values.
    """
    from .gesture_state import Gesture
    if gesture_str is None:
        return Gesture.NONE

    # Map common gesture names to enum values.
    mapping = {
        "Closed_Fist": Gesture.CLOSED_FIST,
        "Open_Palm": Gesture.OPEN_PALM,
        "Pointing_Up": Gesture.POINTING_UP,
        "Thumb_Down": Gesture.THUMB_DOWN,
        "Thumb_Up": Gesture.THUMB_UP,
        "Victory": Gesture.VICTORY,
        "ILoveYou": Gesture.ILOVEYOU,
        "None": Gesture.NONE,
        "none": Gesture.NONE,
    }
    return mapping.get(gesture_str, Gesture.NONE)
