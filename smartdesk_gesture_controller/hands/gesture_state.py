"""Gesture / mode state machine — pure logic, no I/O.

Everything timing-sensitive (mode transitions, stabilization windows, pinch
edge detection, wave thresholding, hand-loss timeout) lives here as methods on
``GestureState``. The controller feeds in the recognized gesture booleans plus
a monotonic ``now`` and receives a list of :class:`ActionIntent` to execute.

Keeping this side-effect free is what makes the gesture pipeline testable
without a camera or pyautogui: tests construct a state, call ``step(...)``,
and assert on the returned intents and the new mode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .gesture_config import (
    GestureConfig,
    MODE_MOUSE,
    MODE_PRESENTATION,
    MODE_SOLIDWORKS,
    MODE_STANDBY,
)


class Gesture(str, Enum):
    """Discrete gesture classification produced by ``gesture_recognition``."""

    NONE = "none"               # no hand detected
    FIST = "fist"
    OPEN_PALM = "open_palm"
    SINGLE_FINGER = "single_finger"   # index straight, others bent
    TWO_FINGER = "two_finger"         # index + middle straight, ring + pinky bent
    PINCH = "pinch"                   # thumb tip + index tip close (used inside single-finger mouse)
    UNKNOWN = "unknown"


@dataclass
class ActionIntent:
    """A declarative action the controller should perform this frame.

    The state machine never calls pyautogui itself; it returns intents so the
    controller can apply them through the gated ActionLayer and feed the
    status server in one place.
    """

    kind: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)

    # Common intent factories keep the call sites readable.
    @classmethod
    def move(cls, x: float, y: float) -> "ActionIntent":
        return cls("move", (x, y))

    @classmethod
    def click(cls) -> "ActionIntent":
        return cls("click")

    @classmethod
    def mouse_down(cls, x: Optional[float] = None, y: Optional[float] = None) -> "ActionIntent":
        return cls("mouse_down", (x, y))

    @classmethod
    def mouse_up(cls, x: Optional[float] = None, y: Optional[float] = None) -> "ActionIntent":
        return cls("mouse_up", (x, y))

    @classmethod
    def press(cls, key: str) -> "ActionIntent":
        return cls("press", (key,))

    @classmethod
    def release_all(cls) -> "ActionIntent":
        return cls("release_all")

    @classmethod
    def hotkey(cls, *keys: str) -> "ActionIntent":
        return cls("hotkey", keys)


@dataclass
class HandInput:
    """Recognized hand state for one frame.

    ``palm_xy`` is the palm center in *camera* pixel coordinates (used for
    screen mapping); ``wave_x`` is the palm center's x used for slide gesture
    differencing; ``pinch_distance`` is in camera px.
    """

    gesture: Gesture
    palm_xy: Optional[tuple] = None        # (x, y) camera px
    wave_x: Optional[float] = None         # palm center x for wave tracking
    pinch_distance: Optional[float] = None


@dataclass
class StepResult:
    """Returned by ``GestureState.step`` each frame."""

    intents: List[ActionIntent] = field(default_factory=list)
    mode: str = MODE_STANDBY
    note: str = ""      # human-readable status text for the debug window / WS server


class GestureState:
    """Tracks modes, stabilization timers and edge-triggered gestures.

    The object is mutable but every transition is expressed as a method so the
    controller has one chokepoint and tests can drive it deterministically.
    """

    def __init__(self, config: GestureConfig) -> None:
        self.config = config
        self.mode: str = config.initial_mode
        self.paused: bool = config.pause_on_start

        # Mouse move smoothing (matches reference impl field names).
        self.ploc_x: float = 0.0
        self.ploc_y: float = 0.0
        self.cloc_x: float = 0.0
        self.cloc_y: float = 0.0
        self.last_mouse_time: float = 0.0

        # Mode activation stabilization windows.
        self._drag_start: float = 0.0
        self._single_start: float = 0.0
        self.is_single_mouse_active: bool = False
        self.is_left_down: bool = False

        # Edge-triggered gesture bookkeeping.
        self.prev_pinch: bool = False
        self.last_click_time: float = 0.0
        self.prev_wave_x: Optional[float] = None
        self.cooldown_wave: float = 0.0
        self.cooldown_fist: float = 0.0

        # Hand-loss safety.
        self.last_hand_seen: float = 0.0

    # ── public controls ─────────────────────────────────────────────────────
    def toggle_pause(self) -> bool:
        """Pause/resume control. Returns the new paused state."""
        self.paused = not self.paused
        if self.paused:
            # Releasing on pause prevents a stuck button while the user steps away.
            self._reset_mouse_modes()
        return self.paused

    def set_active_mode(self, mode: str) -> None:
        """Switch the active control mode (after leaving standby)."""
        if mode not in (MODE_PRESENTATION, MODE_MOUSE, MODE_SOLIDWORKS):
            raise ValueError(f"unknown active mode: {mode}")
        if mode == MODE_SOLIDWORKS:
            # Reserved for the second phase; refuse now so it can't be entered.
            raise NotImplementedError("SolidWorks mode is deferred to phase 2")
        self._reset_mouse_modes()
        self.mode = mode
        self.paused = False

    def activate_from_standby(self) -> bool:
        """Leave standby/pause into the configured active mode."""
        if self.paused or self.mode == MODE_STANDBY:
            self.paused = False
            # If we were sitting in standby, promote to the initial active mode.
            if self.mode == MODE_STANDBY:
                self.mode = self.config.initial_mode
            return True
        return False

    # ── the frame step ──────────────────────────────────────────────────────
    def step(self, hand: HandInput, now: float) -> StepResult:
        """Advance the state machine one frame.

        ``hand.gesture == NONE`` means no hand was detected this frame.
        """
        intents: List[ActionIntent] = []
        note = ""

        # ── Pause short-circuits everything except hand-loss bookkeeping ──
        if self.paused:
            if hand.gesture != Gesture.NONE:
                self.last_hand_seen = now
            return StepResult(intents, self.mode, "PAUSED — press activate to resume")

        # ── No hand: run hand-loss safety, release anything held ──────────
        if hand.gesture == Gesture.NONE:
            intents.extend(self._handle_no_hand(now))
            self.prev_wave_x = None
            self.prev_pinch = False
            return StepResult(intents, self.mode, "No hand detected")

        # Hand present.
        self.last_hand_seen = now

        # ── Dispatch by mode ──────────────────────────────────────────────
        if self.mode == MODE_PRESENTATION:
            intents, note = self._step_presentation(hand, now)
            # Presentation mode never holds the mouse; ensure clean state.
            self._reset_mouse_modes_if_stale(intents)
        elif self.mode == MODE_MOUSE:
            intents, note = self._step_mouse(hand, now)
        else:
            # Standby or unknown: observe only.
            note = f"Standby — gesture: {hand.gesture.value}"

        return StepResult(intents, self.mode, note)

    # ── presentation mode ───────────────────────────────────────────────────
    def _step_presentation(self, hand: HandInput, now: float) -> tuple[List[ActionIntent], str]:
        intents: List[ActionIntent] = []
        note = "Presentation"

        if hand.gesture == Gesture.FIST:
            # Fist drops back to standby so the user can step away cleanly.
            self.mode = MODE_STANDBY
            self._reset_mouse_modes()
            return intents, "FIST → standby"

        if hand.gesture != Gesture.OPEN_PALM:
            self.prev_wave_x = None
            return intents, "Presentation (waiting for open palm)"

        wave_x = hand.wave_x if hand.wave_x is not None else (
            hand.palm_xy[0] if hand.palm_xy is not None else None
        )
        if wave_x is None:
            return intents, "Presentation (open palm)"

        # Set cooldown anchor when first entering open-palm state so the
        # first wave gesture must wait cooldown seconds from first detection.
        if self.prev_wave_x is None:
            self.prev_wave_x = wave_x
            self.cooldown_wave = now
            return intents, "Presentation (open palm)"

        if now - self.cooldown_wave < self.config.wave_cooldown:
            self.prev_wave_x = wave_x
            return intents, "Presentation (wave cooldown)"

        if self.prev_wave_x is not None:
            diff = wave_x - self.prev_wave_x
            if diff > self.config.wave_threshold:
                intents.append(ActionIntent.press("right"))
                self.cooldown_wave = now
                note = "Slide NEXT (right)"
            elif diff < -self.config.wave_threshold:
                intents.append(ActionIntent.press("left"))
                self.cooldown_wave = now
                note = "Slide PREV (left)"
        self.prev_wave_x = wave_x
        return intents, note

    # ── mouse mode ──────────────────────────────────────────────────────────
    def _step_mouse(self, hand: HandInput, now: float) -> tuple[List[ActionIntent], str]:
        intents: List[ActionIntent] = []
        cfg = self.config

        # --- Two-finger drag/pen mode has highest priority while active -----
        drag_stable = self._update_stable(hand.gesture == Gesture.TWO_FINGER, now, "_drag_start", cfg.drag_cooldown)

        if self.is_left_down or drag_stable:
            # Exit via fist → mouse up + back to plain mouse mode.
            if self.is_left_down and hand.gesture == Gesture.FIST and (now - self.cooldown_fist > cfg.fist_exit_cooldown):
                intents.append(ActionIntent.mouse_up(self.cloc_x, self.cloc_y))
                intents.append(ActionIntent.hotkey("ctrl", "p"))
                self._reset_mouse_modes()
                self.cooldown_fist = now
                return intents, "Drag exit (fist) → mouse up"

            # Move while dragging.
            if hand.palm_xy is not None:
                mv = self._maybe_move(hand.palm_xy, now)
                if mv is not None:
                    intents.append(mv)

            # Enter drag once stable.
            if drag_stable and not self.is_left_down:
                intents.append(ActionIntent.hotkey("ctrl", "p"))
                intents.append(ActionIntent.mouse_down(self.cloc_x, self.cloc_y))
                self.is_left_down = True
                # Drag takes over from single-finger mouse to avoid fighting.
                if self.is_single_mouse_active:
                    self._deactivate_single_mouse()
                return intents, "Drag mode entered (Ctrl+P + down)"

            return intents, "Drag/pen active"

        # --- Not dragging: release any held button as a fallthrough ---------
        if self.is_left_down:
            intents.append(ActionIntent.mouse_up(self.cloc_x, self.cloc_y))
            self.is_left_down = False

        # --- Single-finger mouse mode --------------------------------------
        single_stable = self._update_stable(
            hand.gesture == Gesture.SINGLE_FINGER, now, "_single_start", cfg.single_cooldown
        )

        if self.is_single_mouse_active or single_stable:
            # Exit via fist.
            if self.is_single_mouse_active and hand.gesture == Gesture.FIST:
                self._deactivate_single_mouse()
                return intents, "Single-mouse exit (fist)"

            # Activate once stable.
            if single_stable and not self.is_single_mouse_active:
                self._activate_single_mouse()

            # Move via palm center.
            if hand.palm_xy is not None:
                mv = self._maybe_move(hand.palm_xy, now)
                if mv is not None:
                    intents.append(mv)

            # Pinch click (edge-triggered, cooldown-gated).
            if hand.pinch_distance is not None:
                pinched = hand.pinch_distance < cfg.pinch_click_distance
                if (not self.prev_pinch) and pinched and (now - self.last_click_time > cfg.click_cooldown):
                    intents.append(ActionIntent.click())
                    self.last_click_time = now
                    return intents, "Left click (pinch)"
                self.prev_pinch = pinched

            return intents, "Single-finger mouse"

        # --- Default: open palm does nothing in mouse mode; fist → standby --
        if hand.gesture == Gesture.FIST:
            self.mode = MODE_STANDBY
            self._reset_mouse_modes()
            return intents, "FIST → standby"

        # Reset pinch edge state when not in single-finger mode.
        self.prev_pinch = False
        return intents, f"Mouse idle (gesture: {hand.gesture.value})"

    # ── helpers ─────────────────────────────────────────────────────────────
    def _handle_no_hand(self, now: float) -> List[ActionIntent]:
        """Release held buttons after the hand-loss timeout; sooner if dragging."""
        intents: List[ActionIntent] = []
        # Always drop wave tracking when the hand is gone.
        self.prev_wave_x = None
        if self.is_left_down or self.is_single_mouse_active:
            # Hold for a brief grace period; if the hand does not come back,
            # the controller's hand-loss check calls force_release().
            timeout = self.config.hand_loss_timeout
            if self.last_hand_seen and (now - self.last_hand_seen) > timeout:
                intents.extend(self.force_release())
        return intents

    def force_release(self) -> List[ActionIntent]:
        """Release every held button and reset mouse modes.

        Public so the controller can call it on shutdown, exception, or
        hand-loss timeout without going through ``step``.
        """
        intents: List[ActionIntent] = []
        if self.is_left_down:
            intents.append(ActionIntent.mouse_up(self.cloc_x, self.cloc_y))
        if self.is_single_mouse_active or self.is_left_down:
            intents.append(ActionIntent.release_all())
        self._reset_mouse_modes()
        return intents

    def should_release_on_hand_loss(self, now: float) -> bool:
        """True when the hand has been gone past the timeout AND we hold state."""
        if not (self.is_left_down or self.is_single_mouse_active):
            return False
        if not self.last_hand_seen:
            return False
        return (now - self.last_hand_seen) > self.config.hand_loss_timeout

    def _maybe_move(self, palm_xy: tuple, now: float) -> Optional[ActionIntent]:
        """Throttled, smoothed move intent. Returns None when throttled out."""
        if now - self.last_mouse_time < self.config.mouse_frame_interval:
            return None
        sx, sy = self.config.map_region()[0], self.config.map_region()[1]
        # Defer actual mapping math; the controller injects screen coords via
        # the ActionLayer. Here we just hand back camera-space intent so the
        # controller (which knows screen_size) can interp. To keep the state
        # machine pure and testable we instead compute the screen coord now
        # using config.map_region + screen_size.
        x_start, x_end, y_start, y_end = self.config.map_region()
        sw, sh = self.config.screen_size or (1920, 1080)
        px, py = palm_xy
        # Linear interpolation camera→screen (matches np.interp in reference).
        tx = _interp(px, x_start, x_end, 0, sw)
        ty = _interp(py, y_start, y_end, 0, sh)
        s = self.config.smoothening if self.config.smoothening > 0 else 1.0
        self.cloc_x = self.ploc_x + (tx - self.ploc_x) / s
        self.cloc_y = self.ploc_y + (ty - self.ploc_y) / s
        self.ploc_x, self.ploc_y = self.cloc_x, self.cloc_y
        self.last_mouse_time = now
        return ActionIntent.move(self.cloc_x, self.cloc_y)

    def _update_stable(self, condition: bool, now: float, attr: str, cooldown: float) -> bool:
        """Track a stabilization window. Returns True once held >= cooldown."""
        start = getattr(self, attr)
        if condition:
            if start == 0.0:
                setattr(self, attr, now)
                return cooldown <= 0.0  # immediate when cooldown is zero
            return (now - start) >= cooldown
        setattr(self, attr, 0.0)
        return False

    def _activate_single_mouse(self) -> None:
        self.is_single_mouse_active = True
        self.ploc_x = self.ploc_y = 0.0
        self.cloc_x = self.cloc_y = 0.0
        self.last_mouse_time = 0.0
        self.prev_pinch = False

    def _deactivate_single_mouse(self) -> None:
        self.is_single_mouse_active = False
        self._single_start = 0.0
        self.prev_pinch = False
        self.prev_wave_x = None

    def _reset_mouse_modes(self) -> None:
        """Clear every transient mouse/drag/single flag without emitting intents."""
        self.is_left_down = False
        self.is_single_mouse_active = False
        self._drag_start = 0.0
        self._single_start = 0.0
        self.prev_pinch = False
        self.prev_wave_x = None
        self.ploc_x = self.ploc_y = 0.0
        self.cloc_x = self.cloc_y = 0.0

    def _reset_mouse_modes_if_stale(self, intents: List[ActionIntent]) -> None:
        """In non-mouse modes, drop any stale drag/single state with a release."""
        if self.is_left_down or self.is_single_mouse_active:
            intents.append(ActionIntent.mouse_up(self.cloc_x, self.cloc_y))
            intents.append(ActionIntent.release_all())
            self._reset_mouse_modes()


def _interp(value: float, in_start: float, in_end: float, out_start: float, out_end: float) -> float:
    """Linear interpolation; equivalent to ``numpy.interp`` for scalars.

    Inlined to avoid a numpy dependency in this pure-logic module (the
    recognition layer still uses numpy, but the state machine stays light).
    """
    span = in_end - in_start
    if span == 0:
        return out_start
    ratio = (value - in_start) / span
    if ratio < 0:
        ratio = 0.0
    elif ratio > 1:
        ratio = 1.0
    return out_start + ratio * (out_end - out_start)
