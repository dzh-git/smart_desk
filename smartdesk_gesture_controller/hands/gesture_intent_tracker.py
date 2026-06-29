"""Gesture Intent Tracker — pure-logic candidate stabilisation and control-event generation.

Phase 1 of the control-flow-driven refactor.  This module sits between the
recogniser and the state machine:

    Recognizer → GestureFrame
    → GestureIntentTracker.update(frame, current_mode, now)
    → TrackerResult (contains ControlEvent[])
    → GestureState (event path + legacy compat path)
    → ActionIntent[]
    → ActionLayer

The tracker does **not** switch modes, execute system actions, or manage
cooldowns.  It only stabilises gesture candidates, manages short-lived
attempts (mode switch / page turn) and continuous sessions (SolidWorks
rotate / pan), and outputs :class:`ControlEvent` objects for the state
machine to act upon.

All positions and distances use normalised coordinates [0, 1].
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("hands.intent_tracker")

from .gesture_config import (
    GestureConfig,
    MODE_PRESENTATION,
    MODE_PRESENTATION_PEN,
    MODE_SOLIDWORKS,
    MODE_STANDBY,
)


# ═══════════════════════════════════════════════════════════════════════════
# Event type constants
# ═══════════════════════════════════════════════════════════════════════════

EVT_MODE_SWIPE_LEFT = "mode_swipe_left"
EVT_MODE_SWIPE_RIGHT = "mode_swipe_right"
EVT_PAGE_SWIPE_LEFT = "page_swipe_left"
EVT_PAGE_SWIPE_RIGHT = "page_swipe_right"
EVT_ROTATE_BEGIN = "rotate_begin"
EVT_ROTATE_UPDATE = "rotate_update"
EVT_ROTATE_END = "rotate_end"
EVT_PAN_BEGIN = "pan_begin"
EVT_PAN_UPDATE = "pan_update"
EVT_PAN_END = "pan_end"
EVT_ZOOM_UPDATE = "zoom_update"
EVT_CANCEL = "cancel"
EVT_HAND_LOST_TIMEOUT = "hand_lost_timeout"

# ── Phase 2 event types ───────────────────────────────────────────────────
EVT_PEN_MODE_TOGGLE = "pen_mode_toggle"
EVT_PEN_DRAW_BEGIN = "pen_draw_begin"
EVT_PEN_DRAW_UPDATE = "pen_draw_update"
EVT_PEN_DRAW_END = "pen_draw_end"
EVT_FIST_HOLD_COMMITTED = "fist_hold_committed"

ALL_EVENT_TYPES = (
    EVT_MODE_SWIPE_LEFT, EVT_MODE_SWIPE_RIGHT,
    EVT_PAGE_SWIPE_LEFT, EVT_PAGE_SWIPE_RIGHT,
    EVT_ROTATE_BEGIN, EVT_ROTATE_UPDATE, EVT_ROTATE_END,
    EVT_PAN_BEGIN, EVT_PAN_UPDATE, EVT_PAN_END,
    EVT_ZOOM_UPDATE, EVT_CANCEL, EVT_HAND_LOST_TIMEOUT,
    # Phase 2
    EVT_PEN_MODE_TOGGLE,
    EVT_PEN_DRAW_BEGIN, EVT_PEN_DRAW_UPDATE, EVT_PEN_DRAW_END,
    EVT_FIST_HOLD_COMMITTED,
)


# ═══════════════════════════════════════════════════════════════════════════
# Gesture source
# ═══════════════════════════════════════════════════════════════════════════

class GestureSource(str, Enum):
    """Where the gesture classification came from."""
    RECOGNIZER = "recognizer"   # MediaPipe official GestureRecognizer
    RULE_FALLBACK = "rule"      # Legacy landmark-rule classification
    NONE = "none"               # No classification available


# ═══════════════════════════════════════════════════════════════════════════
# GestureFrame — per-frame recogniser output
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class GestureFrame:
    """Normalised per-frame input to the tracker.

    ``hand_present=True, raw_gesture=None`` means a hand was detected but the
    classifier could not determine the gesture.  This counts as a
    classification failure for grace purposes but does **not** start the
    hand-loss timer.

    ``hand_present=False`` means no hand was detected.  Only this state,
    sustained for ``hand_loss_timeout``, produces ``hand_lost_timeout``.

    Task-2 additions:
        * ``hand_size`` — scale reference (distance wrist→middle_mcp in
          image-normalised coordinates).  Used to normalise pinch distance.
        * ``pinch_distance_norm`` — thumb-index distance divided by
          ``hand_size``.  Scale-invariant: stays relatively stable when the
          hand moves closer/farther from the camera.
        * ``pinch_distance`` (legacy field) — raw thumb-index distance in
          image-normalised coordinates.  Kept for backward compat with
          Task-1 tracker logic; new code should prefer ``pinch_distance_norm``.
    """
    hand_present: bool = False
    raw_gesture: Optional[str] = None
    gesture_confidence: float = 0.0
    gesture_source: GestureSource = GestureSource.NONE
    palm_xy: Optional[Tuple[float, float]] = None
    centroid_xy: Optional[Tuple[float, float]] = None
    index_tip_xy: Optional[Tuple[float, float]] = None
    pinch_distance: Optional[float] = None
    hand_size: Optional[float] = None
    pinch_distance_norm: Optional[float] = None
    timestamp: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# ControlEvent — output of the tracker
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ControlEvent:
    """A control event emitted by the tracker for the state machine to act on.

    ``attempt_id`` is used for mode-switch, page-turn, and zoom (short-lived).
    ``session_id`` is used for rotate/pan (continuous, holds buttons/keys).
    """
    type: str
    phase: str = ""           # "begin", "update", "end" for continuous; "" for discrete
    attempt_id: Optional[str] = None
    session_id: Optional[str] = None
    dx: float = 0.0
    dy: float = 0.0
    position: Optional[Tuple[float, float]] = None
    reason: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# GestureAttempt — short-lived atomic action tracking
# ═══════════════════════════════════════════════════════════════════════════

# Attempt phases
AP_IDLE = "idle"
AP_ARMED = "armed"
AP_TRACKING = "tracking"
AP_COMMITTED = "committed"
AP_RELEASED = "released"
AP_CANCELLED = "cancelled"

# Attempt intent types
INTENT_MODE_SWIPE = "mode_swipe"
INTENT_PAGE_SWIPE = "page_swipe"
INTENT_ZOOM = "zoom"
# Phase 2 intent types (not yet wired into production action path)
INTENT_PEN_MODE = "pen_mode"       # Victory HOLD → enter/exit presentation_pen
INTENT_FIST_HOLD = "fist_hold"     # Closed_Fist HOLD → stable commit for mode exit


@dataclass
class GestureAttempt:
    """Tracks a short-lived atomic action (mode switch, page turn, zoom).

    Once committed, the attempt cannot commit again until it is released or
    cancelled.
    """
    attempt_id: str
    intent_type: str
    phase: str = AP_IDLE
    start_position: Optional[Tuple[float, float]] = None
    last_position: Optional[Tuple[float, float]] = None
    started_at: float = 0.0
    last_seen_at: float = 0.0
    committed: bool = False
    # Trajectory tracking
    trajectory: List[Tuple[float, float, float]] = field(default_factory=list)
    # Direction consistency
    direction_samples: List[float] = field(default_factory=list)
    # Bad frame counter (classification failures while active)
    bad_frames: int = 0
    bad_since: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════════════
# ControlSession — continuous action with held buttons/keys
# ═══════════════════════════════════════════════════════════════════════════

# Session control types
CTRL_ROTATE = "rotate"
CTRL_PAN = "pan"
# Phase 2 session control type (not yet wired into production action path)
CTRL_PEN_DRAW = "pen_draw"

# Session phases
SESSION_IDLE = "idle"
SESSION_ACTIVE = "active"
SESSION_ENDING = "ending"


@dataclass
class ControlSession:
    """Tracks a continuous action that holds mouse buttons / keys.

    Only used for SolidWorks rotate (middle mouse) and pan (shift + middle
    mouse) in Phase 1.  Zoom does not create a session.
    """
    session_id: str
    control_type: str
    phase: str = SESSION_IDLE
    start_position: Optional[Tuple[float, float]] = None
    last_position: Optional[Tuple[float, float]] = None
    started_at: float = 0.0
    last_seen_at: float = 0.0
    pressed_buttons: List[str] = field(default_factory=list)
    pressed_keys: List[str] = field(default_factory=list)
    # Bad frame tracking
    bad_frames: int = 0
    bad_since: Optional[float] = None
    # Motion tracking for begin threshold
    motion_duration: float = 0.0
    motion_started: bool = False
    # Last frame timestamp for velocity calculation
    last_frame_time: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════════════
# TrackerResult — returned by update()
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TrackerResult:
    """Output of :meth:`GestureIntentTracker.update`."""
    events: List[ControlEvent] = field(default_factory=list)
    stable_gesture: Optional[str] = None
    intent_state: str = "idle"
    active_attempt: Optional[GestureAttempt] = None
    active_session: Optional[ControlSession] = None
    debug_info: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# Internal state enum for the tracker
# ═══════════════════════════════════════════════════════════════════════════

class _TrackerState(str, Enum):
    IDLE = "idle"
    CANDIDATE = "candidate"
    ARMED = "armed"
    SESSION = "session"
    ZOOM = "zoom"
    HAND_LOST = "hand_lost"


# ═══════════════════════════════════════════════════════════════════════════
# GestureIntentTracker
# ═══════════════════════════════════════════════════════════════════════════

class GestureIntentTracker:
    """Stabilises gesture candidates and outputs control events.

    The tracker is pure logic — no I/O, no side effects.  It maintains
    internal state across :meth:`update` calls and returns a
    :class:`TrackerResult` each frame.

    Lifecycle::

        idle → candidate → armed → tracking → committed → released → idle
                                     ↘ cancelled ↗

        idle → session (active) → ending → idle

    See ``working/控制流程驱动重构计划.md`` §3–§5 for full spec.
    """

    def __init__(self, config: GestureConfig) -> None:
        self.config = config

        # ── Candidate confirmation state ───────────────────────────────────
        self._gesture_history: List[Tuple[float, str, float, GestureSource]] = []
        # (timestamp, gesture_name, confidence, source)
        self._stable_gesture: Optional[str] = None
        self._stable_since: float = 0.0

        # ── Attempt / session ──────────────────────────────────────────────
        self._attempt: Optional[GestureAttempt] = None
        self._session: Optional[ControlSession] = None
        self._attempt_counter: int = 0
        self._session_counter: int = 0

        # ── Hand-loss tracking ─────────────────────────────────────────────
        self._hand_lost_start: Optional[float] = None
        self._hand_lost_fired: bool = False
        self._last_hand_seen: Optional[float] = None

        # ── Zoom tracking ──────────────────────────────────────────────────
        self._zoom_active: bool = False
        self._zoom_last_distance: Optional[float] = None

        # ── Phase 2: HOLD-commit tracking (Closed_Fist / Victory pen mode) ──
        # These are hold-to-commit attempts: the gesture must stay stable
        # for a configured duration before a single commit event fires.
        # Unlike swipe attempts, HOLD-commits don't track trajectory.
        self._hold_attempt: Optional[GestureAttempt] = None
        self._hold_committed: bool = False

        # ── Phase 2: Pen draw session tracking ─────────────────────────────
        # Pen draw uses a ControlSession (CTRL_PEN_DRAW) because it holds
        # the left mouse button during drawing.
        # Not wired into production action path yet.

        # ── Smoothed landmark position ─────────────────────────────────────
        self._smoothed_palm: Optional[Tuple[float, float]] = None

        # ── Internal state ─────────────────────────────────────────────────
        self._state: _TrackerState = _TrackerState.IDLE

        # ── Bad frame tracking for active attempt/session ──────────────────
        self._bad_frame_count: int = 0
        self._bad_frame_start: Optional[float] = None

    # ═══════════════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════════════

    def update(self, frame: GestureFrame, current_mode: str, now: float) -> TrackerResult:
        """Process one frame and return control events.

        Args:
            frame: Normalised recogniser output for this frame.
            current_mode: The current GestureState mode (standby, presentation, etc.)
            now: Monotonic timestamp in seconds.

        Returns:
            TrackerResult with events, stable gesture, and debug info.
        """
        events: List[ControlEvent] = []

        # ── 1. Hand-loss tracking ──────────────────────────────────────────
        if not frame.hand_present:
            hand_events = self._handle_hand_absent(now, events)
            # If hand_lost_timeout fired, cancel any active attempt/session.
            return self._build_result(events, now)

        # Hand is present — reset hand-loss state.
        # Before clearing, check if the hand just reappeared during an active
        # pen_draw session.  A large jump (> 0.1 in normalised coords) means
        # the hand left and came back elsewhere; end the old stroke and start
        # a fresh session so PPT does not draw a connecting line.
        if (self._hand_lost_start is not None and
                self._session is not None and
                self._session.control_type == CTRL_PEN_DRAW):
            elapsed = now - self._hand_lost_start
            if elapsed < self.config.hand_loss_timeout:
                last_pos = self._session.last_position
                new_pos = frame.centroid_xy
                if last_pos is not None and new_pos is not None:
                    dist = math.hypot(new_pos[0] - last_pos[0],
                                      new_pos[1] - last_pos[1])
                    if dist > 0.1:
                        # Only restart if pinch is still held; otherwise the
                        # normal bad-frame logic will end the session.
                        if (frame.pinch_distance_norm is not None and
                                frame.pinch_distance_norm < self.config.pinch_threshold):
                            events.extend(self._end_session("hand_reappear_far", now))
                            events.extend(self._begin_session_attempt(
                                CTRL_PEN_DRAW, EVT_PEN_DRAW_BEGIN, frame, now))

        self._hand_lost_start = None
        self._hand_lost_fired = False
        self._last_hand_seen = now

        # ── 2. Smooth landmarks ────────────────────────────────────────────
        smoothed_palm = self._smooth_palm(frame.palm_xy, now)
        smoothed_frame = self._frame_with_palm(frame, smoothed_palm)

        # ── 3. Update candidate confirmation ───────────────────────────────
        self._update_candidate(smoothed_frame, now)

        # ── 4. If hand_lost_timeout was previously fired, rearm ────────────
        # (Already handled by resetting _hand_lost_fired above.)

        # ── 5. Dispatch by current state ───────────────────────────────────
        if self._session is not None and self._session.phase in (SESSION_IDLE, SESSION_ACTIVE):
            events.extend(self._update_session(smoothed_frame, current_mode, now))
        elif self._attempt is not None and self._attempt.phase in (AP_ARMED, AP_TRACKING, AP_COMMITTED):
            events.extend(self._update_attempt(smoothed_frame, current_mode, now))
        elif self._zoom_active:
            events.extend(self._update_zoom(smoothed_frame, now))
        elif self._hold_attempt is not None:
            # Route to hold update for both armed (pre-commit) and committed states.
            events.extend(self._update_hold_attempt(smoothed_frame, current_mode, now))
        else:
            # ── 6. Try to start a new attempt / session ─────────────────────
            events.extend(self._try_start(smoothed_frame, current_mode, now))

        # ── 7. Check for intent lost timeout on active attempt/session ─────
        self._check_intent_lost(events, now)

        # Diagnostic logging for pen_draw debugging.
        session_phase = "None"
        if self._session is not None:
            session_phase = f"{self._session.control_type}:{self._session.phase}"
        logger.info(
            "[Tracker] mode=%s pinch_norm=%s stable_gesture=%s session=%s events=%s",
            current_mode,
            getattr(frame, "pinch_distance_norm", None),
            self._stable_gesture,
            session_phase,
            [e.type for e in events],
        )

        return self._build_result(events, now)

    def reset(self) -> None:
        """Cancel any active attempt/session and return to idle.

        Called by the state machine on mode switch, pause, or exception.
        Does not emit events — the caller is responsible for safety releases.
        """
        self._attempt = None
        self._session = None
        self._zoom_active = False
        self._zoom_last_distance = None
        self._hold_attempt = None
        self._hold_committed = False
        self._bad_frame_count = 0
        self._bad_frame_start = None
        self._gesture_history.clear()
        self._stable_gesture = None
        self._stable_since = 0.0
        self._smoothed_palm = None
        self._state = _TrackerState.IDLE
        # Note: hand-loss state is NOT reset here — only reset on hand present.

    def cancel(self, reason: str = "") -> List[ControlEvent]:
        """Explicitly cancel any active attempt/session, emitting end events.

        Returns the list of end/cancel events produced.
        """
        events: List[ControlEvent] = []
        if self._session is not None:
            if self._session.phase == SESSION_ACTIVE:
                if self._session.control_type == CTRL_ROTATE:
                    evt_type = EVT_ROTATE_END
                elif self._session.control_type == CTRL_PAN:
                    evt_type = EVT_PAN_END
                else:  # CTRL_PEN_DRAW
                    evt_type = EVT_PEN_DRAW_END
                events.append(ControlEvent(
                    type=evt_type, phase="end",
                    session_id=self._session.session_id,
                    reason=reason or "cancelled",
                ))
            # Session in SESSION_IDLE produces no end event (no begin was emitted).
            self._session = None

        if self._attempt is not None and self._attempt.phase in (AP_ARMED, AP_TRACKING, AP_COMMITTED):
            events.append(ControlEvent(
                type=EVT_CANCEL, phase="cancel",
                attempt_id=self._attempt.attempt_id,
                reason=reason or "cancelled",
            ))
            self._attempt = None

        if self._hold_attempt is not None and not self._hold_committed:
            events.append(ControlEvent(
                type=EVT_CANCEL, phase="cancel",
                attempt_id=self._hold_attempt.attempt_id,
                reason=reason or "cancelled",
            ))
        self._hold_attempt = None
        self._hold_committed = False

        self._zoom_active = False
        self._zoom_last_distance = None
        self._bad_frame_count = 0
        self._bad_frame_start = None
        self._state = _TrackerState.IDLE
        return events

    # ═══════════════════════════════════════════════════════════════════════
    # Hand-loss handling
    # ═══════════════════════════════════════════════════════════════════════

    def _handle_hand_absent(self, now: float, events: List[ControlEvent]) -> List[ControlEvent]:
        """Handle hand-absent frame: track timeout, emit hand_lost_timeout once."""
        if self._hand_lost_start is None:
            self._hand_lost_start = now

        # If last_hand_seen is None (never seen), start grace from now.
        reference = self._last_hand_seen if self._last_hand_seen is not None else self._hand_lost_start
        elapsed = now - reference

        if elapsed < self.config.hand_loss_timeout:
            # Within grace period — no events, but cancel active attempt/session
            # via intent_lost (bad frames will accumulate).
            return events

        if self._hand_lost_fired:
            # Already fired for this continuous hand-loss event.
            return events

        # ── Fire hand_lost_timeout once ────────────────────────────────────
        self._hand_lost_fired = True

        # End any active session.
        if self._session is not None and self._session.phase == SESSION_ACTIVE:
            if self._session.control_type == CTRL_ROTATE:
                evt_type = EVT_ROTATE_END
            elif self._session.control_type == CTRL_PAN:
                evt_type = EVT_PAN_END
            else:  # CTRL_PEN_DRAW
                evt_type = EVT_PEN_DRAW_END
            events.append(ControlEvent(
                type=evt_type, phase="end",
                session_id=self._session.session_id,
                reason="hand_lost_timeout",
            ))
            self._session = None

        # Cancel any active attempt.
        if self._attempt is not None and self._attempt.phase in (AP_ARMED, AP_TRACKING, AP_COMMITTED):
            events.append(ControlEvent(
                type=EVT_CANCEL, phase="cancel",
                attempt_id=self._attempt.attempt_id,
                reason="hand_lost_timeout",
            ))
            self._attempt = None

        # Cancel any active HOLD attempt (Phase 2).
        if self._hold_attempt is not None and not self._hold_committed:
            events.append(ControlEvent(
                type=EVT_CANCEL, phase="cancel",
                attempt_id=self._hold_attempt.attempt_id,
                reason="hand_lost_timeout",
            ))
            self._hold_attempt = None
        self._hold_committed = False

        # Reset zoom.
        self._zoom_active = False
        self._zoom_last_distance = None

        # Reset stable gesture so stale classification doesn't leak after hand loss.
        self._stable_gesture = None
        self._stable_since = 0.0
        self._gesture_history.clear()

        events.append(ControlEvent(
            type=EVT_HAND_LOST_TIMEOUT,
            reason="hand_lost_timeout",
        ))

        self._state = _TrackerState.HAND_LOST
        return events

    # ═══════════════════════════════════════════════════════════════════════
    # Landmark smoothing
    # ═══════════════════════════════════════════════════════════════════════

    def _smooth_palm(self, palm_xy: Optional[Tuple[float, float]],
                     now: float) -> Optional[Tuple[float, float]]:
        """Low-pass filter on palm position.

        ``landmark_smoothing`` is the weight of the new observation (0–1).
        Higher = more responsive, lower = smoother.
        """
        if palm_xy is None:
            return self._smoothed_palm  # keep last known

        if self._smoothed_palm is None:
            self._smoothed_palm = palm_xy
            return palm_xy

        alpha = self.config.landmark_smoothing
        sx = self._smoothed_palm[0] + alpha * (palm_xy[0] - self._smoothed_palm[0])
        sy = self._smoothed_palm[1] + alpha * (palm_xy[1] - self._smoothed_palm[1])
        self._smoothed_palm = (sx, sy)
        return self._smoothed_palm

    def _frame_with_palm(self, frame: GestureFrame,
                         smoothed_palm: Optional[Tuple[float, float]]) -> GestureFrame:
        """Return a copy of *frame* with smoothed palm position.

        Preserves ``hand_size`` and ``pinch_distance_norm`` so that zoom
        logic can use the normalised distance after landmark smoothing.
        """
        if smoothed_palm is None or smoothed_palm == frame.palm_xy:
            return frame
        return GestureFrame(
            hand_present=frame.hand_present,
            raw_gesture=frame.raw_gesture,
            gesture_confidence=frame.gesture_confidence,
            gesture_source=frame.gesture_source,
            palm_xy=smoothed_palm,
            centroid_xy=frame.centroid_xy,
            index_tip_xy=frame.index_tip_xy,
            pinch_distance=frame.pinch_distance,
            hand_size=frame.hand_size,
            pinch_distance_norm=frame.pinch_distance_norm,
            timestamp=frame.timestamp,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Candidate confirmation
    # ═══════════════════════════════════════════════════════════════════════

    def _update_candidate(self, frame: GestureFrame, now: float) -> None:
        """Update gesture history and compute stable_gesture.

        Candidate confirmation rule (spec §4.1):
        - Official classifier must match at least ``gesture_enter_frames``
          out of the last ``gesture_enter_window_frames`` frames, with
          confidence >= ``gesture_enter_confidence``.
        - Rule fallback results do not participate in confidence judgement
          but must still pass ``enter_frames`` and ``arm_duration``.
        - ``raw_gesture=None, hand_present=True`` counts as classification
          failure, not hand loss.
        """
        cfg = self.config

        # Record into history.
        g = frame.raw_gesture
        conf = frame.gesture_confidence
        src = frame.gesture_source

        self._gesture_history.append((now, g or "", conf, src))

        # Prune entries older than the window.
        window = cfg.gesture_enter_window_frames
        if len(self._gesture_history) > window:
            self._gesture_history = self._gesture_history[-window:]

        # Count matches for each gesture in the window.
        counts: Dict[str, int] = {}
        for _, gest, confidence, source in self._gesture_history:
            if not gest:
                continue
            # Rule fallback: count without confidence gate.
            if source == GestureSource.RULE_FALLBACK:
                counts[gest] = counts.get(gest, 0) + 1
            else:
                # Official recognizer: only count if confidence meets threshold.
                if confidence >= cfg.gesture_enter_confidence:
                    counts[gest] = counts.get(gest, 0) + 1

        # Determine stable gesture.
        required = cfg.gesture_enter_frames
        best_gesture: Optional[str] = None
        best_count = 0
        for gest, cnt in counts.items():
            if cnt >= required and cnt > best_count:
                best_gesture = gest
                best_count = cnt

        if best_gesture is not None:
            if best_gesture != self._stable_gesture:
                self._stable_gesture = best_gesture
                self._stable_since = now
        else:
            # No gesture meets the threshold — but don't immediately clear
            # if we're in an active attempt/session (grace period handles that).
            if self._attempt is None and self._session is None and not self._zoom_active:
                self._stable_gesture = None

    # ═══════════════════════════════════════════════════════════════════════
    # Attempt / session creation
    # ═══════════════════════════════════════════════════════════════════════

    def _try_start(self, frame: GestureFrame, current_mode: str,
                   now: float) -> List[ControlEvent]:
        """Try to start a new attempt or session based on stable gesture.

        Priority (when no attempt/session is active):
        1. SolidWorks mode: Open_Palm → rotate, Victory → pan, pinch → zoom.
        2. Any mode: ILoveYou → mode-switch attempt.
        3. Presentation mode: Open_Palm → page-turn attempt.
        4. Phase 2 hold/draw (wired into production via ControlEvent → _handle_events):
           a. Closed_Fist → fist_hold attempt (stable hold → commit → EVT_FIST_HOLD_COMMITTED).
           b. Victory in presentation → pen_mode attempt (stable hold → commit → EVT_PEN_MODE_TOGGLE).
           c. PINCH in presentation_pen → pen_draw session (holds left mouse → EVT_PEN_DRAW_*).
        """
        events: List[ControlEvent] = []
        cfg = self.config
        g = self._stable_gesture

        # ── Pen draw in presentation_pen → pen_draw session ────────────────
        # Driven by pinch_distance_norm < pinch_threshold (not raw_gesture).
        # The session holds the left mouse button (like SolidWorks rotate
        # holds the middle mouse button).
        # Checked BEFORE the `g is None` guard because pen_draw does not
        # require a stable gesture — only pinch distance.
        if (current_mode == MODE_PRESENTATION_PEN and
                frame.pinch_distance_norm is not None and
                frame.hand_present and
                self._session is None and self._attempt is None and
                not self._zoom_active and self._hold_attempt is None):
            if frame.pinch_distance_norm < cfg.pinch_threshold:
                events.extend(self._begin_session_attempt(
                    CTRL_PEN_DRAW, EVT_PEN_DRAW_BEGIN, frame, now))
                return events

        if g is None:
            return events

        palm = frame.palm_xy

        # ── Zoom: based on pinch_distance_norm (scale-invariant) ──────────
        if (current_mode == MODE_SOLIDWORKS and
                frame.pinch_distance_norm is not None and
                not self._zoom_active and
                self._session is None and
                self._attempt is None):
            if frame.pinch_distance_norm < cfg.pinch_threshold:
                events.extend(self._begin_zoom(frame, now))
                return events

        # ── SolidWorks rotate: Open_Palm ───────────────────────────────────
        if (current_mode == MODE_SOLIDWORKS and g == "Open_Palm" and
                self._session is None and self._attempt is None and
                not self._zoom_active):
            events.extend(self._begin_session_attempt(
                CTRL_ROTATE, EVT_ROTATE_BEGIN, frame, now))
            return events

        # ── SolidWorks pan: Victory ────────────────────────────────────────
        if (current_mode == MODE_SOLIDWORKS and g == "Victory" and
                self._session is None and self._attempt is None and
                not self._zoom_active):
            events.extend(self._begin_session_attempt(
                CTRL_PAN, EVT_PAN_BEGIN, frame, now))
            return events

        # ── Mode switch: ILoveYou ──────────────────────────────────────────
        if g == "ILoveYou" and self._attempt is None and self._session is None:
            # Must be stable for mode_arm_duration.
            if (now - self._stable_since) >= cfg.mode_arm_duration:
                events.extend(self._begin_attempt(
                    INTENT_MODE_SWIPE, frame, now))
                return events

        # ── Page turn: Open_Palm in presentation ───────────────────────────
        if (current_mode == MODE_PRESENTATION and g == "Open_Palm" and
                self._attempt is None and self._session is None):
            events.extend(self._begin_attempt(
                INTENT_PAGE_SWIPE, frame, now))
            return events

        # ═══════════════════════════════════════════════════════════════════
        # Phase 2 candidates (not wired into production action path)
        # ═══════════════════════════════════════════════════════════════════

        # ── Closed_Fist HOLD → fist_hold_committed ─────────────────────────
        # Stable Closed_Fist in any active mode triggers a hold attempt.
        # The commit event is emitted after exit_mode_hold duration.
        # GestureState still decides whether to act on it.
        if (g == "Closed_Fist" and self._hold_attempt is None and
                self._attempt is None and self._session is None and
                not self._zoom_active):
            if (now - self._stable_since) >= cfg.mode_arm_duration:
                events.extend(self._begin_hold_attempt(
                    INTENT_FIST_HOLD, frame, now))
                return events

        # ── Victory HOLD in presentation → pen_mode_enter ──────────────────
        # Stable Victory in presentation mode triggers a pen_mode attempt.
        # The commit event is emitted after pen_mode_hold duration.
        if (current_mode == MODE_PRESENTATION and g == "Victory" and
                self._hold_attempt is None and
                self._attempt is None and self._session is None and
                not self._zoom_active):
            if (now - self._stable_since) >= cfg.mode_arm_duration:
                events.extend(self._begin_hold_attempt(
                    INTENT_PEN_MODE, frame, now))
                return events

        # ── Victory HOLD in presentation_pen → pen_mode_exit ───────────────
        # Stable Victory in presentation_pen mode triggers a pen_mode exit.
        if (current_mode == MODE_PRESENTATION_PEN and g == "Victory" and
                self._hold_attempt is None and
                self._attempt is None and self._session is None and
                not self._zoom_active):
            if (now - self._stable_since) >= cfg.mode_arm_duration:
                events.extend(self._begin_hold_attempt(
                    INTENT_PEN_MODE, frame, now))
                return events

        return events

    # ═══════════════════════════════════════════════════════════════════════
    # Attempt lifecycle (mode switch, page turn)
    # ═══════════════════════════════════════════════════════════════════════

    def _begin_attempt(self, intent_type: str, frame: GestureFrame,
                       now: float) -> List[ControlEvent]:
        """Create a new GestureAttempt in armed state."""
        self._attempt_counter += 1
        attempt_id = f"att_{self._attempt_counter}"
        palm = frame.palm_xy or (0.0, 0.0)

        self._attempt = GestureAttempt(
            attempt_id=attempt_id,
            intent_type=intent_type,
            phase=AP_ARMED,
            start_position=palm,
            last_position=palm,
            started_at=now,
            last_seen_at=now,
            trajectory=[(now, palm[0], palm[1])],
        )
        self._state = _TrackerState.ARMED
        self._bad_frame_count = 0
        self._bad_frame_start = None
        return []

    def _update_attempt(self, frame: GestureFrame, current_mode: str,
                        now: float) -> List[ControlEvent]:
        """Update an active attempt: track trajectory, check commit conditions."""
        events: List[ControlEvent] = []
        assert self._attempt is not None
        att = self._attempt
        cfg = self.config

        # Track bad frames (classification doesn't match intent gesture).
        g = frame.raw_gesture
        expected_gesture = self._expected_gesture_for_attempt(att.intent_type)

        if g is None or g != expected_gesture:
            # For mode swipe, after armed we don't require continued ILoveYou.
            if att.intent_type == INTENT_MODE_SWIPE and att.phase == AP_TRACKING:
                # In tracking phase, classification is irrelevant.
                att.bad_frames = 0
                att.bad_since = None
            elif g is None and frame.hand_present:
                # raw_gesture=None with hand present = classification failure.
                att.bad_frames += 1
                if att.bad_since is None:
                    att.bad_since = now
            elif att.phase == AP_ARMED:
                # In armed phase, classification mismatch is more serious.
                att.bad_frames += 1
                if att.bad_since is None:
                    att.bad_since = now
        else:
            att.bad_frames = 0
            att.bad_since = None

        # ── Update trajectory ──────────────────────────────────────────────
        palm = frame.palm_xy
        if palm is not None:
            # In armed phase, only update trajectory if classification
            # matches (or is None = classification failure, not wrong gesture).
            # Once in TRACKING, always update.
            should_update = True
            if att.phase == AP_ARMED:
                if g is not None and g != expected_gesture:
                    # Wrong gesture in armed phase — don't update trajectory.
                    should_update = False
            if should_update:
                att.last_position = palm
                att.last_seen_at = now
                att.trajectory.append((now, palm[0], palm[1]))

                # Limit trajectory length.
                if len(att.trajectory) > 60:
                    att.trajectory = att.trajectory[-60:]

                # Transition to tracking once motion starts.
                if att.phase == AP_ARMED:
                    att.phase = AP_TRACKING
                    self._state = _TrackerState.ARMED

        # ── Check timeout ──────────────────────────────────────────────────
        timeout = (cfg.mode_swipe_timeout if att.intent_type == INTENT_MODE_SWIPE
                   else cfg.page_swipe_timeout)
        if (now - att.started_at) > timeout:
            events.append(ControlEvent(
                type=EVT_CANCEL, phase="cancel",
                attempt_id=att.attempt_id,
                reason="timeout",
            ))
            self._attempt = None
            self._state = _TrackerState.IDLE
            return events

        # ── Check commit conditions (only in TRACKING) ─────────────────────
        if att.phase == AP_TRACKING and att.committed is False:
            commit_evt = self._check_commit(att, current_mode, now)
            if commit_evt is not None:
                events.append(commit_evt)
                att.committed = True
                att.phase = AP_COMMITTED

        # ── Check release after commit ─────────────────────────────────────
        if att.phase == AP_COMMITTED:
            release_evt = self._check_release(att, now)
            if release_evt is not None:
                events.append(release_evt)
                self._attempt = None
                self._state = _TrackerState.IDLE

        return events

    def _check_commit(self, att: GestureAttempt, current_mode: str,
                      now: float) -> Optional[ControlEvent]:
        """Check if an attempt should commit (emit its event).

        Conditions:
        - Horizontal displacement exceeds threshold.
        - Vertical displacement within y-limit.
        - Motion duration >= min_motion_duration.
        - Direction consistency over direction_consistency_frames.
        """
        cfg = self.config
        if len(att.trajectory) < 2:
            return None

        start = att.trajectory[0]
        latest = att.trajectory[-1]
        dx = latest[1] - start[1]
        dy = latest[2] - start[2]
        dt = latest[0] - start[0]

        # Threshold selection.
        if att.intent_type == INTENT_MODE_SWIPE:
            threshold = cfg.iloveyou_swipe_threshold_x
        else:
            threshold = cfg.swipe_threshold_x
        y_limit = cfg.swipe_threshold_y_limit

        # Vertical check.
        if abs(dy) > y_limit:
            return None

        # Duration check.
        if dt < cfg.min_motion_duration:
            return None

        # Direction consistency: collect valid direction samples from
        # the trajectory, require at least ``direction_consistency_frames``
        # valid samples, and all must agree.
        required_dirs = cfg.direction_consistency_frames
        directions: List[int] = []
        for i in range(1, len(att.trajectory)):
            step_dx = att.trajectory[i][1] - att.trajectory[i - 1][1]
            if abs(step_dx) < cfg.motion_deadzone * 0.5:
                continue  # skip near-zero steps
            directions.append(1 if step_dx > 0 else -1)
        # Need at least N valid direction samples.
        if len(directions) < required_dirs:
            return None
        # Check the most recent N samples for consistency.
        recent_dirs = directions[-required_dirs:]
        if len(set(recent_dirs)) > 1:
            return None
        # Also reject if there are conflicting directions anywhere in
        # the recent window (direction changes indicate jitter).
        # Use the last N samples only — earlier ones are stale.

        # Horizontal displacement check.
        if abs(dx) < threshold:
            return None

        # ── Commit! ────────────────────────────────────────────────────────
        if att.intent_type == INTENT_MODE_SWIPE:
            evt_type = EVT_MODE_SWIPE_RIGHT if dx > 0 else EVT_MODE_SWIPE_LEFT
        else:
            evt_type = EVT_PAGE_SWIPE_RIGHT if dx > 0 else EVT_PAGE_SWIPE_LEFT

        return ControlEvent(
            type=evt_type,
            attempt_id=att.attempt_id,
            dx=dx, dy=dy,
            position=att.last_position,
            reason="committed",
        )

    def _check_release(self, att: GestureAttempt, now: float) -> Optional[ControlEvent]:
        """Check if a committed attempt should be released.

        Release conditions:
        - Trajectory returns near start (|dx| < threshold * 0.5).
        - Timeout exceeded.
        """
        cfg = self.config
        if len(att.trajectory) < 2:
            return None

        start = att.trajectory[0]
        latest = att.trajectory[-1]
        dx = latest[1] - start[1]

        if att.intent_type == INTENT_MODE_SWIPE:
            threshold = cfg.iloveyou_swipe_threshold_x
        else:
            threshold = cfg.swipe_threshold_x

        if abs(dx) < threshold * 0.5:
            att.phase = AP_RELEASED
            return ControlEvent(
                type=EVT_CANCEL, phase="release",
                attempt_id=att.attempt_id,
                reason="released",
            )

        return None

    def _expected_gesture_for_attempt(self, intent_type: str) -> Optional[str]:
        """Return the gesture name expected for the given intent type."""
        if intent_type == INTENT_MODE_SWIPE:
            return "ILoveYou"
        if intent_type == INTENT_PAGE_SWIPE:
            return "Open_Palm"
        # Phase 2 hold attempts
        if intent_type == INTENT_FIST_HOLD:
            return "Closed_Fist"
        if intent_type == INTENT_PEN_MODE:
            return "Victory"
        return None

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 2: HOLD-commit attempt lifecycle (Closed_Fist / Victory pen mode)
    # ═══════════════════════════════════════════════════════════════════════

    def _begin_hold_attempt(self, intent_type: str, frame: GestureFrame,
                            now: float) -> List[ControlEvent]:
        """Begin a HOLD-to-commit attempt.

        Unlike swipe attempts, HOLD attempts don't track trajectory. They
        simply wait for the gesture to stay stable for a configured duration,
        then emit a single commit event.

        The commit duration is determined by the config:
        - INTENT_FIST_HOLD: ``exit_mode_hold``
        - INTENT_PEN_MODE: ``pen_mode_hold``

        Not wired into production action path — GestureState still decides
        whether to act on the commit event.
        """
        self._attempt_counter += 1
        attempt_id = f"hold_{self._attempt_counter}"
        palm = frame.palm_xy or (0.0, 0.0)

        self._hold_attempt = GestureAttempt(
            attempt_id=attempt_id,
            intent_type=intent_type,
            phase=AP_ARMED,
            start_position=palm,
            last_position=palm,
            started_at=now,
            last_seen_at=now,
        )
        self._hold_committed = False
        self._state = _TrackerState.ARMED
        self._bad_frame_count = 0
        self._bad_frame_start = None
        return []

    def _update_hold_attempt(self, frame: GestureFrame, current_mode: str,
                             now: float) -> List[ControlEvent]:
        """Update a HOLD attempt: track classification stability, check commit.

        The gesture must remain stable (matching the expected gesture) for
        the configured hold duration. Classification failures accumulate as
        bad frames; if they exceed the grace period, the attempt is cancelled.

        Once the hold duration is met, a single commit event fires and the
        attempt enters AP_COMMITTED. After commit, the attempt is released
        when the gesture changes or hand is lost.
        """
        events: List[ControlEvent] = []
        assert self._hold_attempt is not None
        att = self._hold_attempt
        cfg = self.config

        g = frame.raw_gesture
        expected = self._expected_gesture_for_attempt(att.intent_type)

        # Track bad frames.
        if g is None and frame.hand_present:
            att.bad_frames += 1
            if att.bad_since is None:
                att.bad_since = now
        elif g != expected:
            att.bad_frames += 1
            if att.bad_since is None:
                att.bad_since = now
        else:
            att.bad_frames = 0
            att.bad_since = None
            att.last_seen_at = now

        # Determine hold duration based on intent type.
        if att.intent_type == INTENT_FIST_HOLD:
            hold_duration = cfg.exit_mode_hold
        elif att.intent_type == INTENT_PEN_MODE:
            hold_duration = cfg.pen_mode_hold
        else:
            hold_duration = cfg.exit_mode_hold

        # ── Check commit ───────────────────────────────────────────────────
        if not self._hold_committed:
            stable_duration = now - att.started_at
            # Subtract bad-frame time from stable duration.
            if att.bad_since is not None:
                stable_duration = (att.last_seen_at - att.started_at) if att.last_seen_at > att.started_at else 0.0

            if stable_duration >= hold_duration and att.bad_frames == 0:
                self._hold_committed = True
                att.phase = AP_COMMITTED

                # Emit the appropriate commit event.
                if att.intent_type == INTENT_FIST_HOLD:
                    events.append(ControlEvent(
                        type=EVT_FIST_HOLD_COMMITTED,
                        attempt_id=att.attempt_id,
                        reason="hold_committed",
                    ))
                elif att.intent_type == INTENT_PEN_MODE:
                    # Pen mode toggle: enter in presentation, exit in presentation_pen.
                    if current_mode == MODE_PRESENTATION:
                        events.append(ControlEvent(
                            type=EVT_PEN_MODE_TOGGLE,
                            attempt_id=att.attempt_id,
                            reason="pen_mode_enter",
                        ))
                    elif current_mode == MODE_PRESENTATION_PEN:
                        events.append(ControlEvent(
                            type=EVT_PEN_MODE_TOGGLE,
                            attempt_id=att.attempt_id,
                            reason="pen_mode_exit",
                        ))
        else:
            # ── After commit: release when gesture changes ──────────────────
            if g != expected and g is not None:
                att.phase = AP_RELEASED
                self._hold_attempt = None
                self._hold_committed = False
                self._state = _TrackerState.IDLE

        return events

    # ═══════════════════════════════════════════════════════════════════════
    # Session lifecycle (SolidWorks rotate / pan)
    # ═══════════════════════════════════════════════════════════════════════

    def _begin_session_attempt(self, control_type: str, begin_evt: str,
                               frame: GestureFrame,
                               now: float) -> List[ControlEvent]:
        """Begin a rotate or pan session candidate.

        The session starts in SESSION_IDLE and transitions to SESSION_ACTIVE
        once motion exceeds the deadzone for min_motion_duration.
        """
        self._session_counter += 1
        session_id = f"ses_{self._session_counter}"
        # Pen draw uses the 21-landmark centroid for a stable cursor anchor;
        # fall back to index_tip_xy / palm_xy if centroid is unavailable.
        if control_type == CTRL_PEN_DRAW and frame.centroid_xy is not None:
            palm = frame.centroid_xy
        elif control_type == CTRL_PEN_DRAW and frame.index_tip_xy is not None:
            palm = frame.index_tip_xy
        else:
            palm = frame.palm_xy or (0.0, 0.0)

        buttons: List[str] = []
        keys: List[str] = []
        if control_type == CTRL_ROTATE:
            buttons = ["middle"]
        elif control_type == CTRL_PAN:
            keys = ["shift"]
            buttons = ["middle"]
        elif control_type == CTRL_PEN_DRAW:
            buttons = ["left"]

        self._session = ControlSession(
            session_id=session_id,
            control_type=control_type,
            phase=SESSION_IDLE,
            start_position=palm,
            last_position=palm,
            started_at=now,
            last_seen_at=now,
            pressed_buttons=buttons,
            pressed_keys=keys,
        )
        self._state = _TrackerState.SESSION
        self._bad_frame_count = 0
        self._bad_frame_start = None
        logger.info(
            "[Session] begin control_type=%s session_id=%s position=%s",
            control_type, session_id, palm,
        )
        return []

    def _update_session(self, frame: GestureFrame, current_mode: str,
                        now: float) -> List[ControlEvent]:
        """Update an active session: motion tracking, begin/update events."""
        events: List[ControlEvent] = []
        assert self._session is not None
        ses = self._session
        cfg = self.config

        # Track bad frames.
        g = frame.raw_gesture
        if ses.control_type == CTRL_ROTATE:
            expected = "Open_Palm"
        elif ses.control_type == CTRL_PAN:
            expected = "Victory"
        else:  # CTRL_PEN_DRAW
            expected = None  # pen_draw uses pinch_distance_norm, not gesture name

        if ses.control_type == CTRL_PEN_DRAW:
            # Pen draw session: bad frame only when pinch is released
            # (pinch_distance_norm > pinch_release_threshold) or hand absent.
            pd = frame.pinch_distance_norm
            if not frame.hand_present:
                ses.bad_frames += 1
                if ses.bad_since is None:
                    ses.bad_since = now
            elif pd is not None and pd > cfg.pinch_release_threshold:
                ses.bad_frames += 1
                if ses.bad_since is None:
                    ses.bad_since = now
            else:
                # pinch still held or classification failure (g is None) —
                # do NOT count as bad frame.
                ses.bad_frames = 0
                ses.bad_since = None
        else:
            if g is None and frame.hand_present:
                # Classification failure — grace period.
                ses.bad_frames += 1
                if ses.bad_since is None:
                    ses.bad_since = now
            elif g != expected:
                # Different gesture — count as bad frame but with shorter grace.
                ses.bad_frames += 1
                if ses.bad_since is None:
                    ses.bad_since = now
            else:
                ses.bad_frames = 0
                ses.bad_since = None

        # Update position — pen_draw uses centroid_xy, others use palm_xy.
        if ses.control_type == CTRL_PEN_DRAW and frame.centroid_xy is not None:
            pos = frame.centroid_xy
        elif ses.control_type == CTRL_PEN_DRAW and frame.index_tip_xy is not None:
            pos = frame.index_tip_xy
        else:
            pos = frame.palm_xy
        if pos is None:
            return events

        # Compute motion delta from last position.
        if ses.last_position is not None:
            raw_dx = pos[0] - ses.last_position[0]
            raw_dy = pos[1] - ses.last_position[1]
        else:
            raw_dx = raw_dy = 0.0

        # Compute dt for velocity limiting.
        if ses.last_frame_time is not None and now > ses.last_frame_time:
            dt = now - ses.last_frame_time
        else:
            dt = 0.0
        ses.last_frame_time = now

        # Apply motion constraints.
        dx, dy = self._constrain_motion(raw_dx, raw_dy, ses.last_position, now, dt)

        ses.last_position = pos
        ses.last_seen_at = now

        if ses.phase == SESSION_IDLE:
            # Check if motion exceeds deadzone for min_motion_duration.
            dist = (raw_dx * raw_dx + raw_dy * raw_dy) ** 0.5
            if dist > cfg.motion_deadzone:
                if not ses.motion_started:
                    ses.motion_started = True
                    # Track when motion started using the tracker's timestamp.
                    ses.motion_duration = 0.0
                    ses.started_at = now
                else:
                    ses.motion_duration = now - ses.started_at

                logger.info(
                    "[Session] IDLE control_type=%s dist=%.4f deadzone=%.4f "
                    "motion_duration=%.3f min=%.3f bad_frames=%d",
                    ses.control_type, dist, cfg.motion_deadzone,
                    ses.motion_duration, cfg.min_motion_duration, ses.bad_frames,
                )

                if ses.motion_duration >= cfg.min_motion_duration:
                    ses.phase = SESSION_ACTIVE
                    if ses.control_type == CTRL_ROTATE:
                        evt_type = EVT_ROTATE_BEGIN
                    elif ses.control_type == CTRL_PAN:
                        evt_type = EVT_PAN_BEGIN
                    else:  # CTRL_PEN_DRAW
                        evt_type = EVT_PEN_DRAW_BEGIN
                    events.append(ControlEvent(
                        type=evt_type, phase="begin",
                        session_id=ses.session_id,
                        position=pos,
                    ))
            else:
                ses.motion_started = False
                ses.motion_duration = 0.0

        elif ses.phase == SESSION_ACTIVE:
            # Emit update events.
            if ses.control_type == CTRL_ROTATE:
                evt_type = EVT_ROTATE_UPDATE
            elif ses.control_type == CTRL_PAN:
                evt_type = EVT_PAN_UPDATE
            else:  # CTRL_PEN_DRAW
                evt_type = EVT_PEN_DRAW_UPDATE
            if abs(dx) > 0 or abs(dy) > 0:
                events.append(ControlEvent(
                    type=evt_type, phase="update",
                    session_id=ses.session_id,
                    dx=dx, dy=dy,
                    position=pos,
                ))
                logger.info(
                    "[Session] ACTIVE update control_type=%s dx=%.4f dy=%.4f "
                    "position=%s bad_frames=%d",
                    ses.control_type, dx, dy, pos, ses.bad_frames,
                )
            else:
                logger.info(
                    "[Session] ACTIVE no-motion control_type=%s position=%s "
                    "bad_frames=%d",
                    ses.control_type, pos, ses.bad_frames,
                )

        return events

    def _end_session(self, reason: str, now: float) -> List[ControlEvent]:
        """End the active session and return end events."""
        events: List[ControlEvent] = []
        if self._session is None:
            logger.info("[Session] end requested but no active session (reason=%s)", reason)
            return events

        ses = self._session
        logger.info(
            "[Session] end control_type=%s phase=%s session_id=%s reason=%s",
            ses.control_type, ses.phase, ses.session_id, reason,
        )
        if ses.phase == SESSION_ACTIVE:
            if ses.control_type == CTRL_ROTATE:
                evt_type = EVT_ROTATE_END
            elif ses.control_type == CTRL_PAN:
                evt_type = EVT_PAN_END
            else:  # CTRL_PEN_DRAW
                evt_type = EVT_PEN_DRAW_END
            events.append(ControlEvent(
                type=evt_type, phase="end",
                session_id=ses.session_id,
                reason=reason,
            ))
        # Session in SESSION_IDLE that gets cancelled does not emit end event
        # (no begin was emitted).

        self._session = None
        self._state = _TrackerState.IDLE
        return events

    # ═══════════════════════════════════════════════════════════════════════
    # Zoom lifecycle
    # ═══════════════════════════════════════════════════════════════════════

    def _begin_zoom(self, frame: GestureFrame, now: float) -> List[ControlEvent]:
        """Begin a zoom attempt based on normalised pinch distance."""
        self._attempt_counter += 1
        attempt_id = f"zoom_{self._attempt_counter}"
        self._zoom_active = True
        self._zoom_last_distance = frame.pinch_distance_norm
        self._state = _TrackerState.ZOOM
        return []

    def _update_zoom(self, frame: GestureFrame, now: float) -> List[ControlEvent]:
        """Update zoom: emit zoom_update events based on normalised pinch distance delta.

        Uses ``pinch_distance_norm`` (scale-invariant) for all threshold and
        delta calculations.  ``pinch_distance`` (raw pixels) is never used.
        """
        events: List[ControlEvent] = []
        cfg = self.config

        if frame.pinch_distance_norm is None:
            return events

        pd = frame.pinch_distance_norm

        # Check release threshold.
        if pd > cfg.pinch_release_threshold:
            # Zoom ended.
            self._zoom_active = False
            self._zoom_last_distance = None
            self._state = _TrackerState.IDLE
            return events

        # Compute delta from last frame.
        if self._zoom_last_distance is not None:
            delta = pd - self._zoom_last_distance
            if abs(delta) > cfg.pinch_zoom_deadzone:
                # Apply sensitivity scaling.
                amount = int(delta * cfg.solidworks_zoom_sensitivity * 100)
                if amount == 0:
                    amount = (1 if delta > 0 else -1) * cfg.solidworks_min_zoom_step
                if cfg.invert_scroll:
                    amount = -amount
                if amount != 0:
                    events.append(ControlEvent(
                        type=EVT_ZOOM_UPDATE,
                        attempt_id=f"zoom_{self._attempt_counter}",
                        dx=float(amount),
                        reason="zoom_delta",
                    ))
            self._zoom_last_distance = pd
        else:
            self._zoom_last_distance = pd

        return events

    # ═══════════════════════════════════════════════════════════════════════
    # Intent lost timeout
    # ═══════════════════════════════════════════════════════════════════════

    def _check_intent_lost(self, events: List[ControlEvent], now: float) -> None:
        """Check if active attempt/session should be cancelled due to bad frames.

        Two independent cancellation conditions (either one triggers):
        - ``bad_frames > gesture_keep_grace_frames`` (frame-count gate)
        - ``bad_since`` duration exceeds ``intent_lost_timeout`` (time gate)
        """
        cfg = self.config
        grace = cfg.gesture_keep_grace_frames
        lost_timeout = cfg.intent_lost_timeout

        # Check session.
        if self._session is not None:
            ses = self._session
            should_end = False
            reason = ""
            if ses.bad_frames > grace:
                should_end = True
                reason = "grace_exceeded"
            elif ses.bad_since is not None and (now - ses.bad_since) > lost_timeout:
                should_end = True
                reason = "intent_lost"
            if should_end:
                end_events = self._end_session(reason, now)
                events.extend(end_events)
                return

        # Check attempt.
        if self._attempt is not None:
            att = self._attempt
            # For mode swipe in tracking phase, classification is irrelevant.
            if att.intent_type == INTENT_MODE_SWIPE and att.phase in (AP_TRACKING, AP_COMMITTED):
                return
            should_cancel = False
            reason = ""
            if att.bad_frames > grace:
                should_cancel = True
                reason = "grace_exceeded"
            elif att.bad_since is not None and (now - att.bad_since) > lost_timeout:
                should_cancel = True
                reason = "intent_lost"
            if should_cancel:
                events.append(ControlEvent(
                    type=EVT_CANCEL, phase="cancel",
                    attempt_id=att.attempt_id,
                    reason=reason,
                ))
                self._attempt = None
                self._state = _TrackerState.IDLE
            return

        # Check HOLD attempt (Phase 2: Closed_Fist / Victory pen mode).
        if self._hold_attempt is not None and not self._hold_committed:
            att = self._hold_attempt
            should_cancel = False
            reason = ""
            if att.bad_frames > grace:
                should_cancel = True
                reason = "grace_exceeded"
            elif att.bad_since is not None and (now - att.bad_since) > lost_timeout:
                should_cancel = True
                reason = "intent_lost"
            if should_cancel:
                events.append(ControlEvent(
                    type=EVT_CANCEL, phase="cancel",
                    attempt_id=att.attempt_id,
                    reason=reason,
                ))
                self._hold_attempt = None
                self._state = _TrackerState.IDLE

    # ═══════════════════════════════════════════════════════════════════════
    # Motion constraints
    # ═══════════════════════════════════════════════════════════════════════

    def _constrain_motion(self, dx: float, dy: float,
                          last_pos: Optional[Tuple[float, float]],
                          now: float,
                          dt: float = 0.0) -> Tuple[float, float]:
        """Apply deadzone, max step, and velocity constraints.

        Args:
            dx, dy: Raw per-frame displacement.
            last_pos: Last position (unused currently, reserved).
            now: Current timestamp.
            dt: Time since last frame in seconds.  When > 0, velocity
                limiting is applied via ``max_motion_velocity``.

        Returns the constrained (dx, dy).
        """
        cfg = self.config

        # Deadzone.
        if abs(dx) < cfg.motion_deadzone:
            dx = 0.0
        if abs(dy) < cfg.motion_deadzone:
            dy = 0.0

        # Max step per frame.
        step_dist = (dx * dx + dy * dy) ** 0.5
        if step_dist > cfg.max_motion_step > 0:
            scale = cfg.max_motion_step / step_dist
            dx *= scale
            dy *= scale
            step_dist = (dx * dx + dy * dy) ** 0.5

        # Velocity limit: if dt > 0, constrain speed.
        if dt > 0 and cfg.max_motion_velocity > 0:
            velocity = step_dist / dt
            if velocity > cfg.max_motion_velocity:
                scale = cfg.max_motion_velocity * dt / step_dist
                dx *= scale
                dy *= scale

        return dx, dy

    # ═══════════════════════════════════════════════════════════════════════
    # Result builder
    # ═══════════════════════════════════════════════════════════════════════

    def _build_result(self, events: List[ControlEvent],
                      now: float) -> TrackerResult:
        """Build the TrackerResult with debug info."""
        att = self._attempt
        ses = self._session

        # Determine intent_state string.
        if ses is not None:
            if ses.phase == SESSION_ACTIVE:
                state_str = f"session:{ses.control_type}"
            else:
                state_str = f"session_candidate:{ses.control_type}"
        elif att is not None:
            state_str = f"attempt:{att.intent_type}:{att.phase}"
        elif self._hold_attempt is not None:
            state_str = f"hold:{self._hold_attempt.intent_type}:{self._hold_attempt.phase}"
        elif self._zoom_active:
            state_str = "zoom"
        elif self._hand_lost_fired:
            state_str = "hand_lost"
        else:
            state_str = "idle"

        # Bad frame info.
        bad_frames = 0
        bad_since = None
        if ses is not None:
            bad_frames = ses.bad_frames
            bad_since = ses.bad_since
        elif att is not None:
            bad_frames = att.bad_frames
            bad_since = att.bad_since
        elif self._hold_attempt is not None:
            bad_frames = self._hold_attempt.bad_frames
            bad_since = self._hold_attempt.bad_since

        # Hand lost duration.
        hand_lost_duration = 0.0
        if self._hand_lost_start is not None:
            hand_lost_duration = now - self._hand_lost_start

        debug = {
            "tracker_state": self._state.value,
            "stable_gesture": self._stable_gesture,
            "stable_since": round(self._stable_since, 3) if self._stable_since else 0,
            "active_attempt_id": att.attempt_id if att else None,
            "active_attempt_phase": att.phase if att else None,
            "active_attempt_intent": att.intent_type if att else None,
            "active_session_id": ses.session_id if ses else None,
            "active_session_type": ses.control_type if ses else None,
            "active_session_phase": ses.phase if ses else None,
            "hold_attempt_id": self._hold_attempt.attempt_id if self._hold_attempt else None,
            "hold_attempt_intent": self._hold_attempt.intent_type if self._hold_attempt else None,
            "hold_committed": self._hold_committed,
            "zoom_active": self._zoom_active,
            "zoom_last_distance": self._zoom_last_distance,
            "bad_frames": bad_frames,
            "bad_since": round(bad_since, 3) if bad_since else None,
            "hand_lost_start": round(self._hand_lost_start, 3) if self._hand_lost_start else None,
            "hand_lost_duration": round(hand_lost_duration, 3),
            "hand_lost_fired": self._hand_lost_fired,
            "smoothed_palm": self._smoothed_palm,
            "gesture_history_len": len(self._gesture_history),
        }

        return TrackerResult(
            events=events,
            stable_gesture=self._stable_gesture,
            intent_state=state_str,
            active_attempt=att,
            active_session=ses,
            debug_info=debug,
        )
