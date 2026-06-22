"""Gesture / mode state machine — pure logic, no I/O.

Everything timing-sensitive (mode transitions, stabilization windows, pinch
edge detection, wave thresholding, hand-loss timeout) lives here as methods on
``GestureState``. The controller feeds in the recognized gesture booleans plus
a monotonic ``now`` and receives a list of :class:`ActionIntent` to execute.

Phase 2 (STATE_MACHINE_SPEC.md):
    * 7 modes: standby / presentation / presentation_pen / mouse /
      mouse_scroll / solidworks / paused.
    * Unified HOLD mechanism (gesture must stay stable for N seconds).
    * Unified cooldown mechanism (discrete actions gated).
    * None / hand-loss timeout → release_all.
    * All exit paths emit release_all.
    * solidworks enterable/exitable (rotate/pan/zoom deferred to phase 5).

Keeping this side-effect free is what makes the gesture pipeline testable
without a camera or pyautogui: tests construct a state, call ``step(...)``,
and assert on the returned intents and the new mode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from .gesture_config import (
    GestureConfig,
    MODE_MOUSE,
    MODE_MOUSE_SCROLL,
    MODE_PAUSED,
    MODE_PRESENTATION,
    MODE_PRESENTATION_PEN,
    MODE_SOLIDWORKS,
    MODE_STANDBY,
)


# ═══════════════════════════════════════════════════════════════════════════
# Gesture enum & normalization
# ═══════════════════════════════════════════════════════════════════════════

class Gesture(str, Enum):
    """Discrete gesture classification.

    Two naming families coexist:
    * **Legacy** (produced by the current ``gesture_recognition.py``):
      ``FIST``, ``OPEN_PALM``, ``SINGLE_FINGER``, ``TWO_FINGER``, ``PINCH``.
    * **Spec-canonical** (GESTURE_MAPPING_SPEC §5, future GestureRecognizer):
      ``CLOSED_FIST``, ``POINTING_UP``, ``THUMB_UP``, ``THUMB_DOWN``,
      ``VICTORY``, ``ILOVEYOU``.

    The state machine normalizes legacy names to spec-canonical names via
    :func:`_normalize_gesture` so both families work transparently.
    """

    NONE = "none"
    # Legacy (recognition layer)
    FIST = "fist"
    OPEN_PALM = "open_palm"
    SINGLE_FINGER = "single_finger"
    TWO_FINGER = "two_finger"
    PINCH = "pinch"
    UNKNOWN = "unknown"
    # Spec-canonical (tests & future recognizer)
    CLOSED_FIST = "Closed_Fist"
    POINTING_UP = "Pointing_Up"
    THUMB_UP = "Thumb_Up"
    THUMB_DOWN = "Thumb_Down"
    VICTORY = "Victory"
    ILOVEYOU = "ILoveYou"


# Canonical gesture name constants (strings the state machine switches on).
G_NONE = "none"
G_CLOSED_FIST = "Closed_Fist"
G_OPEN_PALM = "Open_Palm"
G_POINTING_UP = "Pointing_Up"
G_THUMB_UP = "Thumb_Up"
G_THUMB_DOWN = "Thumb_Down"
G_VICTORY = "Victory"
G_ILOVEYOU = "ILoveYou"
G_PINCH = "PINCH"
G_UNKNOWN = "unknown"

# Map legacy Gesture enum values → canonical gesture name strings.
# Phase 9: Thumb_Up / Thumb_Down are normalized to G_NONE (disabled, spec
# GESTURE_MAPPING_SPEC §3.2 — false-positive risk too high for v1).
_LEGACY_TO_CANONICAL: Dict[str, str] = {
    Gesture.NONE.value: G_NONE,
    Gesture.FIST.value: G_CLOSED_FIST,
    Gesture.OPEN_PALM.value: G_OPEN_PALM,
    Gesture.SINGLE_FINGER.value: G_POINTING_UP,
    Gesture.TWO_FINGER.value: G_VICTORY,
    Gesture.PINCH.value: G_PINCH,
    Gesture.UNKNOWN.value: G_UNKNOWN,
    # Spec-canonical values pass through.
    Gesture.CLOSED_FIST.value: G_CLOSED_FIST,
    Gesture.POINTING_UP.value: G_POINTING_UP,
    Gesture.THUMB_UP.value: G_NONE,       # Phase 9: disabled
    Gesture.THUMB_DOWN.value: G_NONE,     # Phase 9: disabled
    Gesture.VICTORY.value: G_VICTORY,
    Gesture.ILOVEYOU.value: G_ILOVEYOU,
}


def _normalize_gesture(g: Union[Gesture, str, None]) -> str:
    """Return the canonical gesture name string.

    Accepts a :class:`Gesture` enum member, a raw string, or ``None``
    (treated as no-hand).
    """
    if g is None:
        return G_NONE
    if isinstance(g, Gesture):
        g = g.value
    return _LEGACY_TO_CANONICAL.get(g, G_UNKNOWN)


# ═══════════════════════════════════════════════════════════════════════════
# ActionIntent (phase 1 — unchanged)
# ═══════════════════════════════════════════════════════════════════════════

# ── ActionIntent type constants (aligned with ACTION_INTENT_SPEC.md §4) ─────
INTENT_PRESS = "press"
INTENT_HOTKEY = "hotkey"
INTENT_MOUSE_DOWN = "mouse_down"
INTENT_MOUSE_UP = "mouse_up"
INTENT_CLICK = "click"
INTENT_MOVE_TO = "move_to"
INTENT_MOVE = "move"            # legacy alias for move_to (controller compat)
INTENT_MOVE_REL = "move_rel"
INTENT_SCROLL = "scroll"
INTENT_KEY_DOWN = "key_down"
INTENT_KEY_UP = "key_up"
INTENT_RELEASE_ALL = "release_all"
INTENT_STATUS = "status"
INTENT_NOOP = "noop"

ALL_INTENT_TYPES = (
    INTENT_PRESS, INTENT_HOTKEY, INTENT_MOUSE_DOWN, INTENT_MOUSE_UP,
    INTENT_CLICK, INTENT_MOVE_TO, INTENT_MOVE_REL, INTENT_SCROLL,
    INTENT_KEY_DOWN, INTENT_KEY_UP, INTENT_RELEASE_ALL, INTENT_STATUS,
    INTENT_NOOP,
)


@dataclass
class ActionIntent:
    """A declarative action the controller should perform this frame.

    Structure follows ``docs/ACTION_INTENT_SPEC.md`` §3.  The ``type`` field
    is the canonical action name; ``kind`` is kept as a read-only alias so
    existing controller code that reads ``intent.kind`` continues to work.
    """

    type: str
    key: Optional[str] = None
    keys: List[str] = field(default_factory=list)
    button: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    dx: Optional[float] = None
    dy: Optional[float] = None
    amount: Optional[int] = None
    text: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    # ── backward-compat aliases (read-only) ─────────────────────────────────
    @property
    def kind(self) -> str:
        return self.type

    @property
    def args(self) -> tuple:
        t = self.type
        if t in (INTENT_MOVE, INTENT_MOVE_TO):
            return (self.x, self.y)
        if t == INTENT_MOVE_REL:
            return (self.dx, self.dy)
        if t == INTENT_PRESS:
            return (self.key,)
        if t == INTENT_HOTKEY:
            return tuple(self.keys)
        if t in (INTENT_MOUSE_DOWN, INTENT_MOUSE_UP):
            return (self.x, self.y)
        if t == INTENT_SCROLL:
            return (self.amount,)
        if t in (INTENT_KEY_DOWN, INTENT_KEY_UP):
            return (self.key,)
        if t == INTENT_CLICK:
            return ()
        if t == INTENT_STATUS:
            return (self.text,)
        return ()

    @property
    def kwargs(self) -> Dict[str, Any]:
        return {}

    # ── factory methods ─────────────────────────────────────────────────────
    @classmethod
    def move(cls, x: float, y: float) -> "ActionIntent":
        return cls(type=INTENT_MOVE, x=x, y=y)

    @classmethod
    def move_to(cls, x: float, y: float) -> "ActionIntent":
        return cls(type=INTENT_MOVE_TO, x=x, y=y)

    @classmethod
    def move_rel(cls, dx: float, dy: float) -> "ActionIntent":
        return cls(type=INTENT_MOVE_REL, dx=dx, dy=dy)

    @classmethod
    def click(cls, button: str = "left") -> "ActionIntent":
        return cls(type=INTENT_CLICK, button=button)

    @classmethod
    def mouse_down(cls, x: Optional[float] = None, y: Optional[float] = None,
                   button: str = "left") -> "ActionIntent":
        return cls(type=INTENT_MOUSE_DOWN, x=x, y=y, button=button)

    @classmethod
    def mouse_up(cls, x: Optional[float] = None, y: Optional[float] = None,
                 button: str = "left") -> "ActionIntent":
        return cls(type=INTENT_MOUSE_UP, x=x, y=y, button=button)

    @classmethod
    def press(cls, key: str) -> "ActionIntent":
        return cls(type=INTENT_PRESS, key=key)

    @classmethod
    def hotkey(cls, *keys: str) -> "ActionIntent":
        return cls(type=INTENT_HOTKEY, keys=list(keys))

    @classmethod
    def key_down(cls, key: str) -> "ActionIntent":
        return cls(type=INTENT_KEY_DOWN, key=key)

    @classmethod
    def key_up(cls, key: str) -> "ActionIntent":
        return cls(type=INTENT_KEY_UP, key=key)

    @classmethod
    def scroll(cls, amount: int) -> "ActionIntent":
        return cls(type=INTENT_SCROLL, amount=amount)

    @classmethod
    def release_all(cls) -> "ActionIntent":
        return cls(type=INTENT_RELEASE_ALL)

    @classmethod
    def status(cls, text: str = "") -> "ActionIntent":
        return cls(type=INTENT_STATUS, text=text)

    @classmethod
    def noop(cls) -> "ActionIntent":
        return cls(type=INTENT_NOOP)


# ═══════════════════════════════════════════════════════════════════════════
# HandInput & StepResult
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class HandInput:
    """Recognized hand state for one frame.

    ``gesture`` accepts either a :class:`Gesture` enum (legacy, from the
    current recognition layer) or a canonical gesture name string (spec).
    The state machine normalizes it internally.

    ``palm_xy`` is the palm center in *camera* pixel coordinates;
    ``wave_x`` is the palm center's x used for slide gesture differencing;
    ``pinch_distance`` is in camera px (legacy) or normalized 0–1 (spec).
    """

    gesture: Union[Gesture, str] = Gesture.NONE
    palm_xy: Optional[Tuple[float, float]] = None
    wave_x: Optional[float] = None
    pinch_distance: Optional[float] = None

    @property
    def gesture_name(self) -> str:
        """Canonical gesture name string (normalized)."""
        return _normalize_gesture(self.gesture)

    @property
    def gesture_value(self) -> str:
        """Raw gesture string value (for status display / WS broadcast)."""
        g = self.gesture
        if isinstance(g, Gesture):
            return g.value
        return str(g)


@dataclass
class StepResult:
    """Returned by ``GestureState.step`` each frame.

    Phase 2 adds ``status_text`` and ``debug_info`` per STATE_MACHINE_SPEC §17.
    ``note`` is kept as a read-only alias for ``status_text`` so the
    unmodified controller keeps working.
    """

    mode: str = MODE_STANDBY
    intents: List[ActionIntent] = field(default_factory=list)
    status_text: str = ""
    debug_info: Dict[str, Any] = field(default_factory=dict)

    @property
    def note(self) -> str:
        """Legacy alias for ``status_text`` (controller reads ``result.note``)."""
        return self.status_text


# ═══════════════════════════════════════════════════════════════════════════
# GestureState — the state machine
# ═══════════════════════════════════════════════════════════════════════════

# Cooldown categories (each maps to a config field).
_COOLDOWN_PAGE_TURN = "page_turn"
_COOLDOWN_MODE_SWITCH = "mode_switch"
_COOLDOWN_CLICK = "click"
_COOLDOWN_RIGHT_CLICK = "right_click"
_COOLDOWN_PEN_TOGGLE = "pen_toggle"
_COOLDOWN_SOLIDWORKS_VIEW = "solidworks_view"
_COOLDOWN_SCROLL = "scroll"


class GestureState:
    """Tracks modes, stabilization timers and edge-triggered gestures.

    Phase 2 implements the unified HOLD + cooldown + None-handling skeleton
    described in STATE_MACHINE_SPEC.md.  Legacy mouse-move / wave-detection
    helpers are retained so the controller and existing behaviour continue
    to work while new sub-modes are phased in.
    """

    def __init__(self, config: GestureConfig) -> None:
        self.config = config
        self.mode: str = config.initial_mode
        # ``paused`` is kept as a boolean for controller compat; when True the
        # internal mode is treated as MODE_PAUSED.
        self.paused: bool = config.pause_on_start
        self.previous_mode: Optional[str] = None

        # ── Unified HOLD tracking (spec §15) ────────────────────────────────
        self.last_gesture: str = G_NONE
        self.gesture_start_time: float = 0.0
        self.gesture_stable_duration: float = 0.0
        # Per-category cooldown deadlines.
        self._cooldowns: Dict[str, float] = {}

        # ── Hand-loss safety (spec §14) ─────────────────────────────────────
        # Phase 3: default to None so a brand-new process doesn't immediately
        # trigger release_all (spec §14.2 recommendation).
        self.last_hand_seen: Optional[float] = None
        self.hand_lost_start_time: Optional[float] = None
        # Edge-trigger latch: ensures a single continuous hand-loss event only
        # emits the safety release sequence once.  Reset when a hand reappears.
        self._hand_loss_released: bool = False

        # ── Continuous-action state (spec §2.3) ─────────────────────────────
        self.active_continuous_action: Optional[str] = None
        self.is_left_mouse_down: bool = False
        self.is_middle_mouse_down: bool = False
        self.is_shift_down: bool = False
        self.last_pointer_position: Optional[Tuple[float, float]] = None
        self.last_hand_center: Optional[Tuple[float, float]] = None
        self.last_pinch_distance: Optional[float] = None

        # ── Phase 3: PINCH hysteresis state (spec §6.1 / §8) ────────────────
        # is_pinching tracks the hysteresis state (separate from
        # is_left_mouse_down which tracks the actual mouse button).
        self.is_pinching: bool = False

        # ── Phase 4: mouse PINCH click/drag distinction (spec §8.5) ─────────
        # When a PINCH starts, we record the start time and position.  If the
        # pinch is released before ``drag_hold_time`` and movement stays under
        # ``click_max_movement_px``, it's a click.  Otherwise it becomes a drag
        # (mouse_down → move → mouse_up).
        self._pinch_start_time: float = 0.0
        self._pinch_start_pos: Optional[Tuple[float, float]] = None
        self._pinch_click_candidate: bool = False

        # ── Phase 4: mouse_scroll tracking (spec §9.3) ──────────────────────
        # Last y position used for per-frame dy calculation in scroll mode.
        self._scroll_last_y: Optional[float] = None

        # ── Phase 3: SWIPE trajectory tracking (spec §7.1) ──────────────────
        # History of (time, x, y) for the last swipe_time_window seconds.
        self._swipe_history: List[Tuple[float, float, float]] = []
        # One-swipe-one-turn: armed flag prevents re-triggering until hand resets.
        self._swipe_armed: bool = True

        # ── Mouse move smoothing (legacy, controller compat) ────────────────
        self.ploc_x: float = 0.0
        self.ploc_y: float = 0.0
        self.cloc_x: float = 0.0
        self.cloc_y: float = 0.0
        self.last_mouse_time: float = 0.0

        # ── Legacy stabilization windows (kept for old mouse/drag behaviour) ─
        self._drag_start: float = 0.0
        self._single_start: float = 0.0
        self.is_single_mouse_active: bool = False
        # ``is_left_down`` aliases ``is_left_mouse_down`` for old tests.
        # Both refer to the same underlying flag via the property below.

        # ── Legacy edge-triggered gesture bookkeeping ───────────────────────
        self.prev_pinch: bool = False
        self.last_click_time: float = 0.0
        self.prev_wave_x: Optional[float] = None
        self.cooldown_wave: float = 0.0
        self.cooldown_fist: float = 0.0

    # ── is_left_down compat property ────────────────────────────────────────
    @property
    def is_left_down(self) -> bool:
        return self.is_left_mouse_down

    @is_left_down.setter
    def is_left_down(self, value: bool) -> None:
        self.is_left_mouse_down = value

    # ═══════════════════════════════════════════════════════════════════════
    # Public controls (controller compat)
    # ═══════════════════════════════════════════════════════════════════════

    def toggle_pause(self) -> bool:
        """Pause/resume control. Returns the new paused state.

        Entering pause emits ``release_all`` via :meth:`force_release`.
        Resuming always goes to ``standby`` (safe strategy, spec §11.4).
        """
        self.paused = not self.paused
        if self.paused:
            self.previous_mode = self.mode
            self._reset_continuous_state()
            self._set_cooldown(_COOLDOWN_MODE_SWITCH, self.config.mode_switch_cooldown, 0.0)
        else:
            # Resume → standby (never resume to a dangerous mid-drag state).
            self.mode = MODE_STANDBY
        return self.paused

    def set_active_mode(self, mode: str) -> None:
        """Switch the active control mode.

        Phase 2: solidworks no longer raises NotImplementedError — it is
        enterable (rotate/pan/zoom deferred to phase 5).
        """
        if mode not in (MODE_PRESENTATION, MODE_PRESENTATION_PEN, MODE_MOUSE,
                        MODE_MOUSE_SCROLL, MODE_SOLIDWORKS):
            raise ValueError(f"unknown active mode: {mode}")
        self._reset_continuous_state()
        self.mode = mode
        self.paused = False

    def activate_from_standby(self) -> bool:
        """Leave standby/pause into the configured active mode."""
        if self.paused or self.mode == MODE_STANDBY:
            self.paused = False
            if self.mode == MODE_STANDBY:
                self.mode = self.config.initial_mode
            return True
        return False

    # ═══════════════════════════════════════════════════════════════════════
    # The frame step
    # ═══════════════════════════════════════════════════════════════════════

    def step(self, hand: HandInput, now: float) -> StepResult:
        """Advance the state machine one frame.

        ``hand.gesture == NONE`` means no hand was detected this frame.
        """
        # ── Paused: block all hardware actions (spec §11) ──────────────────
        # Even in pause, the user may want to verify gesture recognition
        # accuracy, so we surface the current gesture in status_text.
        if self.paused:
            gname = hand.gesture_name
            if gname != G_NONE:
                # Treat hand re-detection in pause the same as active mode:
                # re-arm the hand-loss safety latch so a subsequent loss after
                # resuming can still emit release_all once.
                self.last_hand_seen = now
                self.hand_lost_start_time = None
                self._hand_loss_released = False
            gesture_desc = "no hand" if gname == G_NONE else gname
            return StepResult(
                mode=MODE_PAUSED,
                intents=[],
                status_text=f"PAUSED — gesture: {gesture_desc} — Ctrl+Alt+G to resume",
                debug_info=self._debug_info(hand, now),
            )

        # ── Update HOLD tracking ───────────────────────────────────────────
        gname = hand.gesture_name
        self._update_hold(gname, now)

        # ── No hand: run hand-loss safety (spec §14) ───────────────────────
        if gname == G_NONE:
            intents, note = self._handle_no_hand(now)
            return StepResult(self.mode, intents, note, self._debug_info(hand, now))

        # Hand present.
        self.last_hand_seen = now
        self.hand_lost_start_time = None
        self._hand_loss_released = False

        # ── Dispatch by mode ───────────────────────────────────────────────
        if self.mode == MODE_STANDBY:
            intents, note = self._step_standby(hand, now)
        elif self.mode == MODE_PRESENTATION:
            intents, note = self._step_presentation(hand, now)
        elif self.mode == MODE_PRESENTATION_PEN:
            intents, note = self._step_presentation_pen(hand, now)
        elif self.mode == MODE_SOLIDWORKS:
            intents, note = self._step_solidworks(hand, now)
        elif self.mode in (MODE_MOUSE, MODE_MOUSE_SCROLL):
            # Phase 9: mouse / mouse_scroll modes are disabled (spec
            # GESTURE_MAPPING_SPEC §3.2).  If somehow entered, fall back to
            # standby with release_all.
            intents = [ActionIntent.release_all()]
            self._enter_mode(MODE_STANDBY, now)
            note = f"{self.mode} disabled → standby (Phase 9)"
        else:
            intents, note = [], f"Unknown mode: {self.mode}"

        return StepResult(self.mode, intents, note, self._debug_info(hand, now))

    # ═══════════════════════════════════════════════════════════════════════
    # Mode handlers
    # ═══════════════════════════════════════════════════════════════════════

    # ── standby (spec §5, Phase 9 simplified) ──────────────────────────────
    def _step_standby(self, hand: HandInput, now: float) -> Tuple[List[ActionIntent], str]:
        """Phase 9 standby: ILoveYou swipe switches modes.

        ILoveYou right swipe → presentation (no F5).
        ILoveYou left swipe  → solidworks.
        Closed_Fist          → release_all (safety).
        """
        g = hand.gesture_name
        cfg = self.config

        _STANDBY_STATUS = "Standby: ILoveYou → Right=PPT, Left=SolidWorks, Fist=Release"

        # Closed_Fist → stay in standby, release_all (safety, spec §5.3).
        if g == G_CLOSED_FIST:
            self._reset_continuous_state()
            return [ActionIntent.release_all()], "Standby (fist — released)"

        # ILoveYou swipe → mode switch (spec Phase 9).
        if g == G_ILOVEYOU:
            return self._detect_iloveyou_swipe(hand, now, from_mode=MODE_STANDBY)

        # Other gestures → no action in standby.
        return [], _STANDBY_STATUS

    # ── presentation (spec §6, Phase 9 simplified) ─────────────────────────
    _PRESENTATION_STATUS = "Presentation: Open Palm Swipe = Page, Victory = Pen, Fist = Exit"

    def _step_presentation(self, hand: HandInput, now: float) -> Tuple[List[ActionIntent], str]:
        """Phase 9 presentation mode.

        Gestures:
        * Closed_Fist HOLD → standby (Esc + release_all).
        * Victory HOLD     → presentation_pen (Ctrl+P).
        * Open_Palm swipe  → page turn (left/right).
        * ILoveYou swipe   → mode switch (right=standby, left=solidworks).
        """
        g = hand.gesture_name
        cfg = self.config

        # Clear swipe tracking when not Open_Palm or ILoveYou.
        if g not in (G_OPEN_PALM, G_ILOVEYOU):
            self._swipe_history = []
            self._swipe_armed = True

        # Closed_Fist HOLD → standby (Esc + release_all).
        if g == G_CLOSED_FIST:
            if self._hold_triggered(G_CLOSED_FIST, cfg.exit_mode_hold, now):
                self._set_cooldown(_COOLDOWN_MODE_SWITCH, cfg.mode_switch_cooldown, now)
                self._enter_mode(MODE_STANDBY, now)
                return [ActionIntent.press("esc"), ActionIntent.release_all()], \
                       "Closed_Fist HOLD → standby (Esc + release)"

        # Victory HOLD → presentation_pen (Ctrl+P).
        if g == G_VICTORY:
            if self._hold_triggered(G_VICTORY, cfg.pen_mode_hold, now) and \
               self._cooldown_ok(_COOLDOWN_PEN_TOGGLE, now):
                self._set_cooldown(_COOLDOWN_PEN_TOGGLE, cfg.pen_toggle_cooldown, now)
                self._enter_mode(MODE_PRESENTATION_PEN, now)
                return [ActionIntent.hotkey("ctrl", "p")], "Victory HOLD → presentation_pen (Ctrl+P)"

        # ILoveYou swipe → mode switch (right=standby, left=solidworks).
        if g == G_ILOVEYOU:
            result = self._detect_iloveyou_swipe(hand, now, from_mode=MODE_PRESENTATION)
            # If swipe triggered, mode may have changed.
            if self.mode == MODE_STANDBY:
                # Right swipe from presentation → standby: add Esc to exit PPT.
                intents = list(result[0])
                intents.insert(0, ActionIntent.press("esc"))
                return intents, result[1]
            return result

        # Open_Palm swipe → page turn (spec §6.3, §7.1).
        if g == G_OPEN_PALM:
            return self._detect_swipe(hand, now)

        return [], self._PRESENTATION_STATUS

    # ── presentation_pen (spec §7, Phase 9 simplified) ─────────────────────
    _PEN_STATUS = "Pen Mode: Pointing Up = Move, Pinch = Draw, Victory = Exit, Fist = Exit"

    def _step_presentation_pen(self, hand: HandInput, now: float) -> Tuple[List[ActionIntent], str]:
        """Phase 9 presentation_pen mode.

        Gestures:
        * Closed_Fist HOLD → standby (mouse_up + Esc + release_all).
        * Victory HOLD     → back to presentation (mouse_up + Ctrl+A).
        * Pointing_Up      → move cursor.
        * PINCH (hysteresis) → draw (mouse_down/mouse_up).
        """
        g = hand.gesture_name
        cfg = self.config
        intents: List[ActionIntent] = []

        # Closed_Fist HOLD → standby (mouse_up + Esc + release_all).
        if g == G_CLOSED_FIST:
            if self._hold_triggered(G_CLOSED_FIST, cfg.exit_mode_hold, now):
                self._set_cooldown(_COOLDOWN_MODE_SWITCH, cfg.mode_switch_cooldown, now)
                if self.is_left_mouse_down:
                    intents.append(ActionIntent.mouse_up(button="left"))
                intents.append(ActionIntent.press("esc"))
                intents.append(ActionIntent.release_all())
                self._enter_mode(MODE_STANDBY, now)
                return intents, "Closed_Fist HOLD → standby (Esc + release)"

        # Victory HOLD → back to presentation (mouse_up + Ctrl+A).
        if g == G_VICTORY:
            if self._hold_triggered(G_VICTORY, cfg.pen_mode_hold, now) and \
               self._cooldown_ok(_COOLDOWN_PEN_TOGGLE, now):
                self._set_cooldown(_COOLDOWN_PEN_TOGGLE, cfg.pen_toggle_cooldown, now)
                if self.is_left_mouse_down:
                    intents.append(ActionIntent.mouse_up(button="left"))
                intents.append(ActionIntent.hotkey("ctrl", "a"))
                self._enter_mode(MODE_PRESENTATION, now)
                return intents, "Victory HOLD → presentation (Ctrl+A)"

        # ── PINCH draw with hysteresis (spec §7.3, §8) ──────────────────────
        if hand.pinch_distance is not None:
            self._update_pinch_hysteresis(hand.pinch_distance, intents)

        # ── Move pointer (Pointing_Up or while PINCH-drawing) ───────────────
        if hand.palm_xy is not None:
            mv = self._maybe_move(hand.palm_xy, now)
            if mv is not None:
                intents.append(mv)

        if intents:
            return intents, "Pen mode — active"
        return intents, self._PEN_STATUS

    # ── mouse (spec §8) ─────────────────────────────────────────────────────
    _MOUSE_STATUS = "Mouse: Pointing Up = Move, Pinch = Click/Drag, Victory = Scroll, Fist = Exit"

    def _step_mouse(self, hand: HandInput, now: float) -> Tuple[List[ActionIntent], str]:
        """Phase 4 mouse mode handler.

        Gestures:
        * Closed_Fist HOLD  → standby (release_all).
        * Victory HOLD      → mouse_scroll.
        * Thumb_Down HOLD   → click("right") — blocked while dragging.
        * PINCH (hysteresis) → click (short) or drag (long / large movement).
        * Pointing_Up       → move cursor.
        * During drag       → move cursor (follows hand).
        * Open_Palm         → no action (spec §12).
        """
        g = hand.gesture_name
        cfg = self.config
        intents: List[ActionIntent] = []

        # 1. Closed_Fist HOLD → standby (release_all).
        if g == G_CLOSED_FIST:
            if self._hold_triggered(G_CLOSED_FIST, cfg.exit_mode_hold, now):
                self._set_cooldown(_COOLDOWN_MODE_SWITCH, cfg.mode_switch_cooldown, now)
                self._enter_mode(MODE_STANDBY, now)
                return [ActionIntent.release_all()], "Closed_Fist HOLD → standby (release)"

        # 2. Victory HOLD → mouse_scroll.
        if g == G_VICTORY:
            if self._hold_triggered(G_VICTORY, cfg.pen_mode_hold, now) and \
               self._cooldown_ok(_COOLDOWN_MODE_SWITCH, now):
                self._set_cooldown(_COOLDOWN_MODE_SWITCH, cfg.mode_switch_cooldown, now)
                # Release left mouse if currently dragging (safety).
                if self.is_left_mouse_down:
                    intents.append(ActionIntent.mouse_up(button="left"))
                self._enter_mode(MODE_MOUSE_SCROLL, now)
                self._scroll_last_y = None  # reset scroll tracking
                return intents, "Victory HOLD → mouse_scroll"

        # 3. Thumb_Down HOLD → click("right") — blocked while dragging (spec §8.3 req #5).
        if g == G_THUMB_DOWN and not self.is_left_mouse_down:
            if self._hold_triggered(G_THUMB_DOWN, cfg.right_click_hold, now) and \
               self._cooldown_ok(_COOLDOWN_RIGHT_CLICK, now):
                self._set_cooldown(_COOLDOWN_RIGHT_CLICK, cfg.right_click_cooldown, now)
                intents.append(ActionIntent.click(button="right"))

        # 4. PINCH handling (hysteresis + click/drag distinction, spec §8.5).
        if hand.pinch_distance is not None:
            self._update_mouse_pinch(hand, now, intents)

        # 5. Move cursor: Pointing_Up, or during drag (PINCH held + left down).
        should_move = (g == G_POINTING_UP) or (self.is_left_mouse_down and self.is_pinching)
        if should_move and hand.palm_xy is not None:
            if not self.is_single_mouse_active:
                self._activate_single_mouse()
            mv = self._maybe_move(hand.palm_xy, now)
            if mv is not None:
                intents.append(mv)

        # 6. Open_Palm does nothing in mouse mode (spec §12).

        if intents:
            return intents, "Mouse: active"
        return intents, self._MOUSE_STATUS

    # ── mouse_scroll (spec §9) ──────────────────────────────────────────────
    _MOUSE_SCROLL_STATUS = "Scroll Mode: Victory Up/Down = Scroll, Pointing Up = Mouse, Fist = Exit"

    def _step_mouse_scroll(self, hand: HandInput, now: float) -> Tuple[List[ActionIntent], str]:
        """Phase 4 mouse_scroll mode handler.

        Gestures:
        * Closed_Fist HOLD  → standby (release_all).
        * Pointing_Up HOLD  → mouse.
        * Victory + up/down → scroll(+/-amount) with scroll_cooldown.
        * PINCH             → no action (spec §9.4).
        * Thumb_Down        → no action (spec §9.4).
        * Open_Palm         → no action (spec §9.4).
        """
        g = hand.gesture_name
        cfg = self.config
        intents: List[ActionIntent] = []

        # Reset scroll tracking when not Victory (prevents stale dy).
        if g != G_VICTORY:
            self._scroll_last_y = None

        # Closed_Fist HOLD → standby (release_all).
        if g == G_CLOSED_FIST:
            if self._hold_triggered(G_CLOSED_FIST, cfg.exit_mode_hold, now):
                self._set_cooldown(_COOLDOWN_MODE_SWITCH, cfg.mode_switch_cooldown, now)
                self._enter_mode(MODE_STANDBY, now)
                return [ActionIntent.release_all()], "Closed_Fist HOLD → standby (release)"

        # Pointing_Up HOLD → back to mouse.
        if g == G_POINTING_UP:
            if self._hold_triggered(G_POINTING_UP, cfg.pen_mode_hold, now) and \
               self._cooldown_ok(_COOLDOWN_MODE_SWITCH, now):
                self._set_cooldown(_COOLDOWN_MODE_SWITCH, cfg.mode_switch_cooldown, now)
                self._enter_mode(MODE_MOUSE, now)
                return [], "Pointing_Up HOLD → mouse"

        # Victory + vertical movement → scroll.
        if g == G_VICTORY and hand.palm_xy is not None:
            scroll_intents = self._handle_scroll(hand, now)
            intents.extend(scroll_intents)

        # PINCH, Thumb_Down, Open_Palm → no action in mouse_scroll (spec §9.4).

        if intents:
            return intents, "Scroll mode — active"
        return intents, self._MOUSE_SCROLL_STATUS

    # ── solidworks (spec §10, Phase 9 simplified) ──────────────────────────
    _SOLIDWORKS_STATUS = (
        "SolidWorks: Open Palm = Rotate, Victory = Pan, Pinch = Zoom, "
        "ILoveYou Swipe = Switch Mode, Fist = Exit"
    )

    def _step_solidworks(self, hand: HandInput, now: float) -> Tuple[List[ActionIntent], str]:
        """Phase 9 SolidWorks view-mode handler (spec §10).

        Gestures:
        * Closed_Fist HOLD  → standby (release_all).
        * Open_Palm + move  → mouse_down("middle") + move_rel — rotate.
        * Victory + move    → key_down("shift") + mouse_down("middle") + move_rel — pan.
        * PINCH             → scroll(+/-amount) — zoom (hysteresis + deadzone).
        * ILoveYou swipe    → right=presentation, left=standby.
        * Other / None      → end any active rotate/pan.

        Mutual exclusion (spec §10.5): rotate / pan / zoom are exclusive.
        """
        g = hand.gesture_name
        cfg = self.config
        intents: List[ActionIntent] = []

        # ── 1. Closed_Fist HOLD → standby (release_all) ─────────────────────
        if g == G_CLOSED_FIST:
            if self.active_continuous_action:
                intents.extend(self._end_solidworks_action())
            if self._hold_triggered(G_CLOSED_FIST, cfg.exit_mode_hold, now):
                self._set_cooldown(_COOLDOWN_MODE_SWITCH, cfg.mode_switch_cooldown, now)
                self._enter_mode(MODE_STANDBY, now)
                intents.append(ActionIntent.release_all())
                return intents, "Closed_Fist HOLD → standby (release)"
            return intents, "SolidWorks: Closed_Fist (holding)"

        # ── 2. ILoveYou swipe → mode switch ─────────────────────────────────
        if g == G_ILOVEYOU:
            if self.active_continuous_action:
                intents.extend(self._end_solidworks_action())
            result = self._detect_iloveyou_swipe(hand, now, from_mode=MODE_SOLIDWORKS)
            if self.mode != MODE_SOLIDWORKS:
                # Mode changed — add release_all for safety.
                intents.extend(result[0])
                intents.append(ActionIntent.release_all())
                return intents, result[1]
            return result

        # ── 3. Open_Palm → rotate (mouse_down middle + move_rel) ───────────
        if g == G_OPEN_PALM:
            # Switch from pan to rotate: release shift + middle first.
            if self.active_continuous_action == "solidworks_pan":
                intents.extend(self._end_solidworks_action())
            # Begin rotate if not already active.
            if self.active_continuous_action != "solidworks_rotate":
                intents.extend(self._begin_solidworks_rotate())
            # Move.
            if hand.palm_xy is not None:
                mv = self._solidworks_move(hand.palm_xy)
                if mv is not None:
                    intents.append(mv)
            return intents, "SolidWorks: Open_Palm (rotate)"

        # ── 4. Victory → pan (key_down shift + mouse_down middle + move_rel)
        if g == G_VICTORY:
            # Switch from rotate to pan: release middle first.
            if self.active_continuous_action == "solidworks_rotate":
                intents.extend(self._end_solidworks_action())
            # Begin pan if not already active.
            if self.active_continuous_action != "solidworks_pan":
                intents.extend(self._begin_solidworks_pan())
            # Move.
            if hand.palm_xy is not None:
                mv = self._solidworks_move(hand.palm_xy)
                if mv is not None:
                    intents.append(mv)
            return intents, "SolidWorks: Victory (pan)"

        # ── 5. PINCH → zoom (scroll) ────────────────────────────────────────
        if g == G_PINCH and hand.pinch_distance is not None:
            # End any active rotate/pan before zooming (spec §10.5).
            if self.active_continuous_action in ("solidworks_rotate",
                                                  "solidworks_pan"):
                intents.extend(self._end_solidworks_action())
            zoom_intents = self._solidworks_zoom(hand.pinch_distance)
            intents.extend(zoom_intents)
            return intents, "SolidWorks: PINCH (zoom)"

        # ── 6. Other gestures — end any active action ──────────────────────
        if self.active_continuous_action:
            intents.extend(self._end_solidworks_action())

        # Clear pinch tracking when not pinching.
        if self.is_pinching:
            self.is_pinching = False
        self.last_pinch_distance = None
        self.last_hand_center = None

        return intents, self._SOLIDWORKS_STATUS

    # ── SolidWorks helpers (Phase 5, spec §10.3–§10.6) ──────────────────────

    def _begin_solidworks_rotate(self) -> List[ActionIntent]:
        """Begin rotate: mouse_down("middle") once (spec §10.3)."""
        intents: List[ActionIntent] = []
        if not self.is_middle_mouse_down:
            intents.append(ActionIntent.mouse_down(button="middle"))
            self.is_middle_mouse_down = True
        self.active_continuous_action = "solidworks_rotate"
        self.last_hand_center = None  # reset position tracking
        return intents

    def _begin_solidworks_pan(self) -> List[ActionIntent]:
        """Begin pan: key_down("shift") + mouse_down("middle") (spec §10.3)."""
        intents: List[ActionIntent] = []
        if not self.is_shift_down:
            intents.append(ActionIntent.key_down("shift"))
            self.is_shift_down = True
        if not self.is_middle_mouse_down:
            intents.append(ActionIntent.mouse_down(button="middle"))
            self.is_middle_mouse_down = True
        self.active_continuous_action = "solidworks_pan"
        self.last_hand_center = None
        return intents

    def _end_solidworks_action(self) -> List[ActionIntent]:
        """End any active SolidWorks continuous action (spec §10.5, §10.6).

        Releases mouse_up("middle") and key_up("shift") as needed, and clears
        ``active_continuous_action``.  Called on gesture change, None timeout,
        Closed_Fist, Thumb_Up, ILoveYou, and mode exit.
        """
        intents: List[ActionIntent] = []
        if self.is_middle_mouse_down:
            intents.append(ActionIntent.mouse_up(button="middle"))
            self.is_middle_mouse_down = False
        if self.is_shift_down:
            intents.append(ActionIntent.key_up("shift"))
            self.is_shift_down = False
        self.active_continuous_action = None
        self.last_hand_center = None
        return intents

    def _solidworks_move(self, palm_xy: Tuple[float, float]) -> Optional[ActionIntent]:
        """Compute move_rel for SolidWorks rotate/pan (spec §10.3).

        Uses ``solidworks_drag_sensitivity`` to scale movement and
        ``solidworks_deadzone`` to filter micro-jitter.  Returns None when
        movement is within the deadzone.
        """
        cfg = self.config
        x, y = palm_xy

        if self.last_hand_center is None:
            self.last_hand_center = (x, y)
            return None

        last_x, last_y = self.last_hand_center
        raw_dx = x - last_x
        raw_dy = y - last_y
        self.last_hand_center = (x, y)

        # Deadzone check (normalized coordinates, spec §10.3 req #7).
        if x > 1.0:
            # Camera-px mode: convert deadzone to pixels.
            deadzone_x = cfg.solidworks_deadzone * cfg.camera_width
            deadzone_y = cfg.solidworks_deadzone * cfg.camera_height
        else:
            deadzone_x = cfg.solidworks_deadzone
            deadzone_y = cfg.solidworks_deadzone

        # Normalize raw delta for deadzone comparison.
        if x > 1.0:
            dx_norm = raw_dx / cfg.camera_width
            dy_norm = raw_dy / cfg.camera_height
        else:
            dx_norm = raw_dx
            dy_norm = raw_dy

        if abs(dx_norm) < cfg.solidworks_deadzone and \
           abs(dy_norm) < cfg.solidworks_deadzone:
            return None

        # Apply sensitivity scaling.
        dx = raw_dx * cfg.solidworks_drag_sensitivity
        dy = raw_dy * cfg.solidworks_drag_sensitivity
        return ActionIntent.move_rel(dx, dy)

    def _solidworks_zoom(self, pinch_distance: float) -> List[ActionIntent]:
        """Handle PINCH zoom with hysteresis + deadzone + min step (spec §10.3, §5).

        * Hysteresis: ``pinch_threshold`` / ``pinch_release_threshold`` (or
          ``pinch_click_distance`` × 1.4 in camera-px mode).
        * Deadzone: ``pinch_zoom_deadzone`` — small deltas ignored.
        * Sensitivity: ``solidworks_zoom_sensitivity`` scales delta → amount.
        * Min step: ``solidworks_min_zoom_step`` guarantees a non-zero scroll
          when the delta exceeds the deadzone but rounds to 0.
        * Invert: ``invert_scroll`` reverses the scroll direction globally.

        Direction (spec §5):
            PINCH distance increase → scroll(+amount) — zoom in.
            PINCH distance decrease → scroll(-amount) — zoom out.
        If the direction feels reversed in SolidWorks, either set
        ``invert_scroll = True`` or set ``solidworks_zoom_sensitivity`` to a
        negative value.
        """
        cfg = self.config
        intents: List[ActionIntent] = []

        # Determine thresholds + deadzone based on distance magnitude.
        if pinch_distance > 1.0:
            # Camera-px mode (legacy recognition layer).
            enter = cfg.pinch_click_distance
            release = enter * 1.4
            deadzone = cfg.pinch_zoom_deadzone * cfg.pinch_click_distance
            sens_scale = 1.0
        else:
            # Normalized mode (spec / future GestureRecognizer).
            enter = cfg.pinch_threshold
            release = cfg.pinch_release_threshold
            deadzone = cfg.pinch_zoom_deadzone
            # Scale up so normalized deltas produce meaningful scroll amounts.
            sens_scale = 100.0

        # ── Hysteresis: enter / exit pinch state ────────────────────────────
        if not self.is_pinching:
            if pinch_distance < enter:
                self.is_pinching = True
                self.last_pinch_distance = pinch_distance
                self.active_continuous_action = "solidworks_zoom"
            return intents

        # Currently pinching — check release.
        if pinch_distance > release:
            self.is_pinching = False
            self.last_pinch_distance = None
            if self.active_continuous_action == "solidworks_zoom":
                self.active_continuous_action = None
            return intents

        # ── Compute scroll from delta ───────────────────────────────────────
        if self.last_pinch_distance is not None:
            delta = pinch_distance - self.last_pinch_distance

            if abs(delta) > deadzone:
                amount = int(delta * cfg.solidworks_zoom_sensitivity * sens_scale)
                # If the delta is too small to produce a non-zero scroll amount,
                # still emit the minimum configured step so the user sees a
                # response (phase 7 fix for "amount=0 no reaction").
                if amount == 0:
                    amount = (1 if delta > 0 else -1) * cfg.solidworks_min_zoom_step
                if cfg.invert_scroll:
                    amount = -amount
                if amount != 0:
                    intents.append(ActionIntent.scroll(amount))
                self.last_pinch_distance = pinch_distance

        return intents

    # ═══════════════════════════════════════════════════════════════════════
    # HOLD & cooldown helpers (spec §15, §16)
    # ═══════════════════════════════════════════════════════════════════════

    def _update_hold(self, gesture_name: str, now: float) -> None:
        """Update the unified HOLD tracker.

        If the gesture is the same as last frame, ``gesture_stable_duration``
        grows.  If it changed (or hand was lost), the timer resets.
        """
        if gesture_name == G_NONE:
            # Hand lost — reset hold timer.  hand_lost_start_time is tracked
            # in _handle_no_hand / step() to avoid double-setting.
            self.gesture_stable_duration = 0.0
            return

        if gesture_name == self.last_gesture:
            self.gesture_stable_duration = now - self.gesture_start_time
        else:
            self.last_gesture = gesture_name
            self.gesture_start_time = now
            self.gesture_stable_duration = 0.0

    def _hold_triggered(self, gesture_name: str, required_hold: float, now: float) -> bool:
        """True when *gesture_name* has been stable for at least *required_hold*.

        Also requires that the gesture currently matches (defensive — the
        caller usually already checked, but this guards against stale state).
        """
        if self.last_gesture != gesture_name:
            return False
        return self.gesture_stable_duration >= required_hold

    def _set_cooldown(self, category: str, duration: float, now: float) -> None:
        """Set a cooldown deadline for *category*."""
        self._cooldowns[category] = now + duration

    def _cooldown_ok(self, category: str, now: float) -> bool:
        """True when *category* is not in cooldown (or never set)."""
        return now >= self._cooldowns.get(category, 0.0)

    # ═══════════════════════════════════════════════════════════════════════
    # None / hand-loss handling (spec §14)
    # ═══════════════════════════════════════════════════════════════════════

    def _handle_no_hand(self, now: float) -> Tuple[List[ActionIntent], str]:
        """Release held state after hand-loss timeout (spec §14).

        Short None: no action.  Long None (> hand_lost_timeout): release_all
        and clear continuous state.  Mode is preserved (spec §14.2) except
        mouse_scroll → mouse.

        Phase 3: ``last_hand_seen`` defaults to ``None`` (not 0.0) so a
        brand-new process with no hand ever seen does not immediately fire
        release_all.  On the first no-hand frame we initialise it to ``now``,
        starting the grace period from that moment.
        """
        # Track when the hand first disappeared (for debug/should_release).
        if self.hand_lost_start_time is None:
            self.hand_lost_start_time = now

        # Phase 3: if no hand was ever seen, start the grace period from now
        # instead of firing release_all immediately (spec §14.2 recommendation).
        if self.last_hand_seen is None:
            self.last_hand_seen = now

        timeout = self.config.hand_lost_timeout
        elapsed = now - self.last_hand_seen

        if elapsed < timeout:
            return [], "No hand detected (within grace)"

        # Timeout exceeded → release everything once per continuous hand-loss
        # event.  The latch prevents repeated release_all on every subsequent
        # no-hand frame, which would otherwise synchronously block the frame
        # loop via ActionLayer.release_all()'s unconditional mouse/key releases.
        if self._hand_loss_released:
            return [], "Hand lost timeout (already released)"
        self._hand_loss_released = True

        # Timeout exceeded → release everything.
        intents: List[ActionIntent] = []
        # presentation_pen must release left mouse on hand-loss (spec §7.3).
        if self.is_left_mouse_down:
            intents.append(ActionIntent.mouse_up(button="left"))
        if self.is_middle_mouse_down:
            intents.append(ActionIntent.mouse_up(button="middle"))
        if self.is_shift_down:
            intents.append(ActionIntent.key_up("shift"))
        intents.append(ActionIntent.release_all())

        self._reset_continuous_state()

        # mouse_scroll drops back to mouse on hand-loss (spec §9.3).
        if self.mode == MODE_MOUSE_SCROLL:
            self.mode = MODE_MOUSE

        return intents, "Hand lost timeout → release_all"

    def force_release(self) -> List[ActionIntent]:
        """Release every held button and reset continuous state.

        Public so the controller can call it on shutdown, exception, or
        hand-loss timeout without going through ``step``.
        """
        intents: List[ActionIntent] = []
        if self.is_left_mouse_down:
            intents.append(ActionIntent.mouse_up(button="left"))
        if self.is_middle_mouse_down:
            intents.append(ActionIntent.mouse_up(button="middle"))
        if self.is_shift_down:
            intents.append(ActionIntent.key_up("shift"))
        if self.is_left_mouse_down or self.is_middle_mouse_down or self.is_shift_down or \
           self.is_single_mouse_active or self.active_continuous_action:
            intents.append(ActionIntent.release_all())
        # Mark the safety release as done for the current hand-loss period so
        # the next no-hand frame does not duplicate the release.
        self._hand_loss_released = True
        self._reset_continuous_state()
        return intents

    def should_release_on_hand_loss(self, now: float) -> bool:
        """True when the hand has been gone past the timeout AND we hold state."""
        if not (self.is_left_mouse_down or self.is_middle_mouse_down or
                self.is_shift_down or self.is_single_mouse_active or
                self.active_continuous_action or self.is_pinching or
                self._pinch_click_candidate):
            return False
        if self.last_hand_seen is None:
            return False
        return (now - self.last_hand_seen) > self.config.hand_lost_timeout

    # ═══════════════════════════════════════════════════════════════════════
    # Mode transition helper
    # ═══════════════════════════════════════════════════════════════════════

    def _enter_mode(self, new_mode: str, now: float) -> None:
        """Switch to *new_mode*, resetting continuous state (spec §2.4)."""
        if new_mode != self.mode:
            self.previous_mode = self.mode
        self._reset_continuous_state()
        self.mode = new_mode
        # Reset hold tracker so a fresh gesture is required in the new mode.
        self.last_gesture = G_NONE
        self.gesture_start_time = now
        self.gesture_stable_duration = 0.0

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 3: PINCH hysteresis (spec §6.1, §8)
    # ═══════════════════════════════════════════════════════════════════════

    def _update_pinch_hysteresis(self, pinch_distance: float,
                                  intents: List[ActionIntent]) -> None:
        """Update PINCH state with hysteresis, appending mouse_down/mouse_up.

        Uses ``pinch_threshold`` (enter) and ``pinch_release_threshold`` (exit)
        for normalized distances (0–1).  Falls back to legacy
        ``pinch_click_distance`` (with a 1.4× release factor) for camera-px
        distances, preserving backward compatibility with the current
        recognition layer.

        Guarantees:
        * mouse_down("left") emitted exactly once on PINCH start.
        * mouse_up("left")   emitted exactly once on PINCH release.
        * No repeated mouse_down while PINCH is held.
        """
        # Determine thresholds based on distance magnitude.
        if pinch_distance > 1.0:
            # Camera-px mode (legacy recognition layer).
            enter = self.config.pinch_click_distance
            release = enter * 1.4  # hysteresis: release at 40% wider
        else:
            # Normalized mode (spec / future GestureRecognizer).
            enter = self.config.pinch_threshold
            release = self.config.pinch_release_threshold

        if not self.is_pinching:
            if pinch_distance < enter:
                # Enter PINCH — single mouse_down.
                self.is_pinching = True
                if not self.is_left_mouse_down:
                    intents.append(ActionIntent.mouse_down(button="left"))
                    self.is_left_mouse_down = True
                    self.active_continuous_action = "pen_draw"
        else:
            if pinch_distance > release:
                # Release PINCH — single mouse_up.
                self.is_pinching = False
                if self.is_left_mouse_down:
                    intents.append(ActionIntent.mouse_up(button="left"))
                    self.is_left_mouse_down = False
                    self.active_continuous_action = None

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 9: ILoveYou swipe — unified mode switching (spec GESTURE_MAPPING_SPEC §5)
    # ═══════════════════════════════════════════════════════════════════════

    def _detect_iloveyou_swipe(
        self, hand: HandInput, now: float, *, from_mode: str
    ) -> Tuple[List[ActionIntent], str]:
        """ILoveYou left/right swipe for unified mode switching.

        Right swipe → presentation (press F5).
        Left swipe  → solidworks.

        Uses the same time-window trajectory approach as presentation swipe:
        records (time, x, y) into ``_swipe_history``, prunes entries older
        than ``swipe_time_window``, and triggers when |dx| exceeds
        ``iloveyou_swipe_threshold_x`` with |dy| under
        ``swipe_threshold_y_limit``.

        One-swipe-one-turn: after a trigger the swipe is disarmed until the
        hand returns near the start position.
        """
        cfg = self.config
        intents: List[ActionIntent] = []

        x = hand.wave_x if hand.wave_x is not None else (
            hand.palm_xy[0] if hand.palm_xy is not None else None
        )
        y = hand.palm_xy[1] if hand.palm_xy is not None else None
        if x is None:
            return intents, f"{from_mode} (ILoveYou — no position)"

        self._swipe_history.append((now, x, y if y is not None else 0.0))

        # Prune entries older than swipe_time_window.
        window = cfg.swipe_time_window
        while self._swipe_history and self._swipe_history[0][0] < now - window:
            self._swipe_history.pop(0)

        if len(self._swipe_history) < 2:
            return intents, f"{from_mode} (ILoveYou — collecting)"

        oldest = self._swipe_history[0]
        latest = self._swipe_history[-1]
        dx = latest[1] - oldest[1]
        dy = latest[2] - oldest[2]

        # Determine thresholds (normalized 0–1 vs camera px).
        if x > 1.0:
            threshold = cfg.iloveyou_swipe_threshold_x * cfg.camera_width
            y_limit = cfg.swipe_threshold_y_limit * cfg.camera_width
        else:
            threshold = cfg.iloveyou_swipe_threshold_x
            y_limit = cfg.swipe_threshold_y_limit

        # Cooldown check.
        if not self._cooldown_ok(_COOLDOWN_MODE_SWITCH, now):
            if not self._swipe_armed and abs(dx) < threshold * 0.5:
                self._swipe_armed = True
            return intents, f"{from_mode} (ILoveYou — cooldown)"

        # Y-limit check.
        if y is not None and abs(dy) > y_limit:
            if not self._swipe_armed and abs(dx) < threshold * 0.5:
                self._swipe_armed = True
            return intents, f"{from_mode} (ILoveYou — y too large)"

        # Swipe trigger — only when armed.
        if self._swipe_armed and abs(dx) > threshold:
            self._set_cooldown(_COOLDOWN_MODE_SWITCH, cfg.mode_switch_cooldown, now)
            self._swipe_armed = False

            # Direction depends on current mode (Phase 9 spec):
            # standby:      right→presentation, left→solidworks
            # presentation: right→standby,     left→solidworks
            # solidworks:   right→presentation, left→standby
            #
            # No F5 is sent on entering presentation — PPT is expected to
            # already be in slideshow mode.  The state machine only tracks
            # mode; launching the slideshow is the user's responsibility.
            if from_mode == MODE_STANDBY:
                if dx > threshold:
                    self._enter_mode(MODE_PRESENTATION, now)
                    return [], "ILoveYou right swipe → presentation"
                else:
                    self._enter_mode(MODE_SOLIDWORKS, now)
                    return [], "ILoveYou left swipe → solidworks"
            elif from_mode == MODE_PRESENTATION:
                if dx > threshold:
                    self._enter_mode(MODE_STANDBY, now)
                    return [ActionIntent.release_all()], "ILoveYou right swipe → standby"
                else:
                    self._enter_mode(MODE_SOLIDWORKS, now)
                    return [ActionIntent.release_all()], "ILoveYou left swipe → solidworks"
            else:  # solidworks
                if dx > threshold:
                    self._enter_mode(MODE_PRESENTATION, now)
                    return [], "ILoveYou right swipe → presentation"
                else:
                    self._enter_mode(MODE_STANDBY, now)
                    return [ActionIntent.release_all()], "ILoveYou left swipe → standby"

        # Re-arm when hand returns near start.
        if not self._swipe_armed and abs(dx) < threshold * 0.5:
            self._swipe_armed = True

        return intents, f"{from_mode} (ILoveYou — swipe detected: dx={dx:.1f})"

    # ═══════════════════════════════════════════════════════════════════════
    # Legacy behaviour helpers (preserved from phase 1)
    # ═══════════════════════════════════════════════════════════════════════

    def _detect_swipe(self, hand: HandInput, now: float) -> Tuple[List[ActionIntent], str]:
        """Open_Palm swipe detection for presentation mode (spec §6.3, §7.1).

        Phase 3 rewrite:
        * Uses a time-window trajectory (``swipe_time_window``).
        * ``dx > swipe_threshold_x`` → next page; ``dx < -threshold`` → prev.
        * ``abs(dy)`` must be under ``swipe_threshold_y_limit``.
        * ``page_turn_cooldown`` after each turn.
        * One-swipe-one-turn: after a trigger the swipe is "disarmed" until
          the hand returns near the start position.
        * Falls back to legacy ``wave_threshold`` (camera px) when coordinates
          are in pixel space (value > 1.0).
        """
        intents: List[ActionIntent] = []

        # Resolve current hand position (x, y).
        x = hand.wave_x if hand.wave_x is not None else (
            hand.palm_xy[0] if hand.palm_xy is not None else None
        )
        y = hand.palm_xy[1] if hand.palm_xy is not None else None
        if x is None:
            return intents, "Presentation (open palm — no position)"

        # Record into trajectory history (time, x, y).
        self._swipe_history.append((now, x, y if y is not None else 0.0))

        # Prune entries older than swipe_time_window.
        window = self.config.swipe_time_window
        while self._swipe_history and self._swipe_history[0][0] < now - window:
            self._swipe_history.pop(0)

        if len(self._swipe_history) < 2:
            return intents, "Presentation (open palm — collecting)"

        # dx / dy from oldest to latest within the window.
        oldest = self._swipe_history[0]
        latest = self._swipe_history[-1]
        dx = latest[1] - oldest[1]
        dy = latest[2] - oldest[2]

        # Determine thresholds (normalized 0–1 vs camera px).
        if x > 1.0:
            # Camera-px mode (current recognition layer).
            threshold = self.config.wave_threshold
            # Convert normalized y_limit to pixel space proportionally.
            y_limit = self.config.swipe_threshold_y_limit * self.config.camera_width
        else:
            threshold = self.config.swipe_threshold_x
            y_limit = self.config.swipe_threshold_y_limit

        # Cooldown check — one turn per cooldown window.
        if not self._cooldown_ok(_COOLDOWN_PAGE_TURN, now):
            # Still re-arm if hand returns near start.
            if not self._swipe_armed and abs(dx) < threshold * 0.5:
                self._swipe_armed = True
            return intents, "Presentation (wave cooldown)"

        # Y-limit check: if y data available and movement too vertical, reject.
        if y is not None and abs(dy) > y_limit:
            if not self._swipe_armed and abs(dx) < threshold * 0.5:
                self._swipe_armed = True
            return intents, "Presentation (open palm — y too large)"

        # Swipe trigger — only when armed.
        if self._swipe_armed and abs(dx) > threshold:
            if dx > threshold:
                intents.append(ActionIntent.press("right"))
            else:
                intents.append(ActionIntent.press("left"))
            self._set_cooldown(_COOLDOWN_PAGE_TURN, self.config.page_turn_cooldown, now)
            self._swipe_armed = False  # one swipe = one turn

        # Re-arm when hand returns near the start position.
        if not self._swipe_armed and abs(dx) < threshold * 0.5:
            self._swipe_armed = True

        return intents, "Presentation (open palm)"

    def _handle_mouse_pointing(self, hand: HandInput, now: float) -> Tuple[List[ActionIntent], str]:
        """Pointing_Up → move cursor (legacy single-finger mouse).

        Phase 4: this method is retained for backward compat but the new
        ``_step_mouse`` handles movement inline.  It is no longer called by
        ``_step_mouse`` in Phase 4.
        """
        intents: List[ActionIntent] = []
        if not self.is_single_mouse_active:
            self._activate_single_mouse()
        if hand.palm_xy is not None:
            mv = self._maybe_move(hand.palm_xy, now)
            if mv is not None:
                intents.append(mv)
        # Pinch click (edge-triggered, cooldown-gated).
        if hand.pinch_distance is not None:
            pinched = hand.pinch_distance < self.config.pinch_click_distance
            if (not self.prev_pinch) and pinched and self._cooldown_ok(_COOLDOWN_CLICK, now):
                intents.append(ActionIntent.click())
                self._set_cooldown(_COOLDOWN_CLICK, self.config.click_cooldown, now)
                self.last_click_time = now
            self.prev_pinch = pinched
        return intents, "Mouse: pointing + move"

    def _handle_mouse_pinch(self, hand: HandInput, now: float) -> Tuple[List[ActionIntent], str]:
        """PINCH → click or drag (legacy compat, spec §8.5).

        Phase 4: this method is retained for backward compat but the new
        ``_step_mouse`` uses ``_update_mouse_pinch`` instead.
        """
        intents: List[ActionIntent] = []
        if hand.pinch_distance is None:
            return intents, "Mouse (pinch — no distance)"
        pinched = hand.pinch_distance < self.config.pinch_click_distance
        if pinched and not self.prev_pinch:
            if not self.is_left_mouse_down:
                intents.append(ActionIntent.mouse_down(button="left"))
                self.is_left_mouse_down = True
                self.active_continuous_action = "left_drag"
        elif not pinched and self.prev_pinch:
            if self.is_left_mouse_down:
                intents.append(ActionIntent.mouse_up(button="left"))
                self.is_left_mouse_down = False
                self.active_continuous_action = None
        self.prev_pinch = pinched
        if self.is_left_mouse_down and hand.palm_xy is not None:
            mv = self._maybe_move(hand.palm_xy, now)
            if mv is not None:
                intents.append(mv)
        return intents, "Mouse: pinch (click/drag)"

    def _handle_pen_pinch(self, hand: HandInput, now: float) -> Tuple[List[ActionIntent], str]:
        """PINCH → draw in presentation_pen (spec §7.3)."""
        intents: List[ActionIntent] = []
        if hand.pinch_distance is None:
            return intents, "Pen (pinch — no distance)"
        pinched = hand.pinch_distance < self.config.pinch_click_distance
        if pinched and not self.prev_pinch:
            if not self.is_left_mouse_down:
                intents.append(ActionIntent.mouse_down(button="left"))
                self.is_left_mouse_down = True
                self.active_continuous_action = "pen_draw"
        elif not pinched and self.prev_pinch:
            if self.is_left_mouse_down:
                intents.append(ActionIntent.mouse_up(button="left"))
                self.is_left_mouse_down = False
                self.active_continuous_action = None
        self.prev_pinch = pinched
        # Move pointer while drawing.
        if hand.palm_xy is not None:
            mv = self._maybe_move(hand.palm_xy, now)
            if mv is not None:
                intents.append(mv)
        return intents, "Pen: pinch (draw)"

    def _handle_scroll(self, hand: HandInput, now: float) -> List[ActionIntent]:
        """Victory + vertical movement → scroll (spec §9.3, Phase 4).

        Tracks per-frame dy of the palm y-coordinate.  When |dy| exceeds
        ``scroll_threshold_y`` (in normalized coordinates) and the scroll
        cooldown has elapsed, emits ``scroll(+amount)`` for upward hand
        movement (scroll up / content moves down) or ``scroll(-amount)`` for
        downward hand movement.

        Only called from ``_step_mouse_scroll`` — ordinary mouse mode never
        triggers scroll (spec §9.4, requirement #10).
        """
        cfg = self.config
        intents: List[ActionIntent] = []

        if hand.palm_xy is None:
            return intents

        _, y = hand.palm_xy

        # Initialize reference y on first frame (or after gesture change).
        if self._scroll_last_y is None:
            self._scroll_last_y = y
            return intents

        # Per-frame dy.
        dy = y - self._scroll_last_y
        self._scroll_last_y = y

        # Normalize dy if palm_xy is in camera pixels (y > 1.0).
        if y > 1.0:
            dy_norm = dy / self.config.camera_height
        else:
            dy_norm = dy

        threshold = cfg.scroll_threshold_y

        # Cooldown check — prevents multiple scrolls per frame window.
        if not self._cooldown_ok(_COOLDOWN_SCROLL, now):
            return intents

        # Hand up (dy < 0) -> scroll up (positive amount).
        # Hand down (dy > 0) -> scroll down (negative amount).
        # Direction note: in pyautogui, scroll(+) scrolls up (content moves down,
        # you see content above), scroll(-) scrolls down.  This matches the spec:
        #   手向上移动 = 向上滚动 / 放大视图方向
        #   手向下移动 = 向下滚动
        if dy_norm < -threshold:
            amount = cfg.scroll_amount
            if cfg.invert_scroll:
                amount = -amount
            intents.append(ActionIntent.scroll(amount))
            self._set_cooldown(_COOLDOWN_SCROLL, cfg.scroll_cooldown, now)
        elif dy_norm > threshold:
            amount = -cfg.scroll_amount
            if cfg.invert_scroll:
                amount = -amount
            intents.append(ActionIntent.scroll(amount))
            self._set_cooldown(_COOLDOWN_SCROLL, cfg.scroll_cooldown, now)

        return intents

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 4: mouse PINCH click/drag distinction (spec §8.5)
    # ═══════════════════════════════════════════════════════════════════════

    def _update_mouse_pinch(self, hand: HandInput, now: float,
                             intents: List[ActionIntent]) -> None:
        """Handle PINCH click/drag with hysteresis in mouse mode (spec §8.5).

        Uses ``pinch_threshold`` / ``pinch_release_threshold`` for normalized
        distances, falling back to ``pinch_click_distance`` (with 1.4× release
        factor) for camera-px distances.  Hysteresis prevents border jitter.

        Click vs drag distinction:
        * **Click candidate**: PINCH just started.  We wait to see if it
          becomes a drag (duration >= ``drag_hold_time`` or movement >
          ``click_max_movement_px``).
        * **Click**: PINCH released while still a click candidate →
          ``click("left")`` with ``click_cooldown``.
        * **Drag**: PINCH held past ``drag_hold_time`` or moved beyond
          ``click_max_movement_px`` → ``mouse_down("left")`` (once).  On
          release → ``mouse_up("left")`` (once).

        Guarantees:
        * ``mouse_down("left")`` emitted exactly once on drag start.
        * No repeated ``mouse_down`` while PINCH is held.
        * ``mouse_up("left")`` emitted exactly once on release.
        * ``click("left")`` only on short, small-movement release.
        """
        pd = hand.pinch_distance
        if pd is None:
            return

        cfg = self.config

        # Determine thresholds based on distance magnitude.
        if pd > 1.0:
            # Camera-px mode (legacy recognition layer).
            enter = cfg.pinch_click_distance
            release = enter * 1.4  # hysteresis: release at 40% wider
        else:
            # Normalized mode (spec / future GestureRecognizer).
            enter = cfg.pinch_threshold
            release = cfg.pinch_release_threshold

        if not self.is_pinching:
            # ── Check for PINCH enter ──────────────────────────────────────
            if pd < enter:
                self.is_pinching = True
                self._pinch_start_time = now
                self._pinch_start_pos = hand.palm_xy
                self._pinch_click_candidate = True
                # No intent on enter — wait to see if click or drag.
        else:
            # ── Check for PINCH release ────────────────────────────────────
            if pd > release:
                if self.is_left_mouse_down:
                    # Was dragging → mouse_up (once).
                    intents.append(ActionIntent.mouse_up(button="left"))
                    self.is_left_mouse_down = False
                    self.active_continuous_action = None
                elif self._pinch_click_candidate:
                    # Was click candidate → click (with cooldown).
                    if self._cooldown_ok(_COOLDOWN_CLICK, now):
                        intents.append(ActionIntent.click(button="left"))
                        self._set_cooldown(_COOLDOWN_CLICK, cfg.click_cooldown, now)
                self.is_pinching = False
                self._pinch_click_candidate = False
                self._pinch_start_pos = None
                return

            # ── Still pinching — check for drag transition ─────────────────
            if self._pinch_click_candidate and not self.is_left_mouse_down:
                duration = now - self._pinch_start_time

                # Transition to drag if held too long.
                if duration >= cfg.drag_hold_time:
                    intents.append(ActionIntent.mouse_down(button="left"))
                    self.is_left_mouse_down = True
                    self.active_continuous_action = "left_drag"
                    self._pinch_click_candidate = False
                # Transition to drag if moved too far.
                elif hand.palm_xy is not None and self._pinch_start_pos is not None:
                    dx = hand.palm_xy[0] - self._pinch_start_pos[0]
                    dy_mov = hand.palm_xy[1] - self._pinch_start_pos[1]
                    dist = (dx * dx + dy_mov * dy_mov) ** 0.5
                    if dist > cfg.click_max_movement_px:
                        intents.append(ActionIntent.mouse_down(button="left"))
                        self.is_left_mouse_down = True
                        self.active_continuous_action = "left_drag"
                        self._pinch_click_candidate = False

    # ── mouse move smoothing (legacy + spec migration) ─────────────────────
    def _maybe_move(self, palm_xy: tuple, now: float) -> Optional[ActionIntent]:
        """Throttled, smoothed move intent. Returns None when throttled out.

        Phase 4 migration (spec §8.3, CONFIG_SPEC §10):
        * Prefers ``mouse_smoothing`` (0–1, higher = smoother) over legacy
          ``smoothening`` (divisor, 1 = no smoothing).
        * Applies ``mouse_speed`` as a multiplier on the movement delta.
        * Applies ``mouse_max_step_px`` to prevent the cursor from jumping.
        * Final coordinates are clamped to screen boundaries (spec §8.3 req #4).
        * Cursor never jumps to screen edge on first call (spec §8.3 req #5).
        """
        if now - self.last_mouse_time < self.config.mouse_frame_interval:
            return None
        x_start, x_end, y_start, y_end = self.config.map_region()
        sw, sh = self.config.screen_size or (1920, 1080)
        px, py = palm_xy
        tx = _interp(px, x_start, x_end, 0, sw)
        ty = _interp(py, y_start, y_end, 0, sh)

        # Smoothing: prefer mouse_smoothing (spec), fall back to smoothening (legacy).
        if self.config.mouse_smoothing > 0:
            # alpha = movement fraction per frame (1 - smoothing).
            # smoothing=0 → alpha=1 (instant); smoothing=0.35 → alpha=0.65.
            alpha = 1.0 - min(0.95, self.config.mouse_smoothing)
        else:
            # Legacy: smoothening is a divisor (1 = no smoothing).
            s = max(1.0, self.config.smoothening)
            alpha = 1.0 / s

        # Initialize ploc on first call so we don't jump from (0,0).
        if self.ploc_x == 0.0 and self.ploc_y == 0.0:
            self.ploc_x, self.ploc_y = tx, ty

        # Smoothed target position.
        self.cloc_x = self.ploc_x + (tx - self.ploc_x) * alpha
        self.cloc_y = self.ploc_y + (ty - self.ploc_y) * alpha

        # Apply mouse_speed to the movement delta (spec §8.3, CONFIG_SPEC §10.2).
        speed = self.config.mouse_speed
        ddx = (self.cloc_x - self.ploc_x) * speed
        ddy = (self.cloc_y - self.ploc_y) * speed

        # Limit max step per frame to prevent jumps (spec §8.3, mouse_max_step_px).
        max_step = self.config.mouse_max_step_px
        step_dist = (ddx * ddx + ddy * ddy) ** 0.5
        if step_dist > max_step > 0:
            scale = max_step / step_dist
            ddx *= scale
            ddy *= scale

        # New position, clamped to screen boundaries (spec §8.3 req #4).
        new_x = max(0.0, min(float(sw), self.ploc_x + ddx))
        new_y = max(0.0, min(float(sh), self.ploc_y + ddy))

        self.ploc_x, self.ploc_y = new_x, new_y
        self.last_pointer_position = (new_x, new_y)
        self.last_mouse_time = now
        return ActionIntent.move(new_x, new_y)

    # ── legacy stabilization helpers ────────────────────────────────────────
    def _update_stable(self, condition: bool, now: float, attr: str, cooldown: float) -> bool:
        """Track a stabilization window. Returns True once held >= cooldown."""
        start = getattr(self, attr)
        if condition:
            if start == 0.0:
                setattr(self, attr, now)
                return cooldown <= 0.0
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

    # ── state reset ─────────────────────────────────────────────────────────
    def _reset_continuous_state(self) -> None:
        """Clear every transient continuous-action flag (no intents emitted)."""
        self.is_left_mouse_down = False
        self.is_middle_mouse_down = False
        self.is_shift_down = False
        self.is_single_mouse_active = False
        self.active_continuous_action = None
        self.is_pinching = False
        # Phase 4: mouse pinch click/drag state
        self._pinch_start_time = 0.0
        self._pinch_start_pos = None
        self._pinch_click_candidate = False
        # Phase 4: scroll tracking
        self._scroll_last_y = None
        # Phase 5: SolidWorks tracking
        self.last_hand_center = None
        self.last_pinch_distance = None
        self._drag_start = 0.0
        self._single_start = 0.0
        self.prev_pinch = False
        self.prev_wave_x = None
        self._swipe_history = []
        self._swipe_armed = True
        self.ploc_x = self.ploc_y = 0.0
        self.cloc_x = self.cloc_y = 0.0
        self.last_pointer_position = None

    # Legacy alias kept for old tests that call _reset_mouse_modes.
    def _reset_mouse_modes(self) -> None:
        self._reset_continuous_state()

    def _reset_mouse_modes_if_stale(self, intents: List[ActionIntent]) -> None:
        """In non-mouse modes, drop any stale drag/single state with a release."""
        if self.is_left_mouse_down or self.is_single_mouse_active:
            intents.append(ActionIntent.mouse_up(button="left"))
            intents.append(ActionIntent.release_all())
            self._reset_continuous_state()

    # ── debug info ──────────────────────────────────────────────────────────
    def _debug_info(self, hand: HandInput, now: float) -> Dict[str, Any]:
        # Compute current swipe dx/dy from history for debug display.
        swipe_dx = swipe_dy = 0.0
        if self._swipe_history and len(self._swipe_history) >= 2:
            oldest = self._swipe_history[0]
            latest = self._swipe_history[-1]
            swipe_dx = latest[1] - oldest[1]
            swipe_dy = latest[2] - oldest[2]
        # Time since hand was last seen (0 if hand is currently present).
        hand_lost_duration = 0.0
        if self.last_hand_seen is not None and now > self.last_hand_seen:
            hand_lost_duration = now - self.last_hand_seen
        # Next active cooldown deadline (0 if none active).
        cooldown_until = max(self._cooldowns.values()) if self._cooldowns else 0.0
        return {
            "mode": self.mode,
            "current_gesture": hand.gesture_name,
            "raw_gesture": hand.gesture_value,
            "stable_duration": round(self.gesture_stable_duration, 3),
            "last_gesture": self.last_gesture,
            "is_left_mouse_down": self.is_left_mouse_down,
            "is_middle_mouse_down": self.is_middle_mouse_down,
            "is_shift_down": self.is_shift_down,
            "is_pinching": self.is_pinching,
            "pinch_click_candidate": self._pinch_click_candidate,
            "active_continuous_action": self.active_continuous_action,
            "hand_lost_start_time": self.hand_lost_start_time,
            "last_hand_seen": self.last_hand_seen,
            "hand_lost_duration": round(hand_lost_duration, 3),
            "cooldown_until": round(cooldown_until, 3),
            "swipe_armed": self._swipe_armed,
            "last_hand_center": self.last_hand_center,
            "last_pinch_distance": self.last_pinch_distance,
            "pinch_distance": hand.pinch_distance,
            "swipe_dx": round(swipe_dx, 3),
            "swipe_dy": round(swipe_dy, 3),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Module-level helpers
# ═══════════════════════════════════════════════════════════════════════════

def _interp(value: float, in_start: float, in_end: float,
            out_start: float, out_end: float) -> float:
    """Linear interpolation; equivalent to ``numpy.interp`` for scalars."""
    span = in_end - in_start
    if span == 0:
        return out_start
    ratio = (value - in_start) / span
    if ratio < 0:
        ratio = 0.0
    elif ratio > 1:
        ratio = 1.0
    return out_start + ratio * (out_end - out_start)
