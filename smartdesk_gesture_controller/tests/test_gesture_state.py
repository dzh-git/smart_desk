"""Tests for hands.gesture_state — pure-logic state machine.

Phase 9 simplified test suite.

No camera, no pyautogui, no MediaPipe. Just the state machine fed synthetic
HandInput frames and asserted on ActionIntent lists.

Phase 9 changes:
- Thumb_Up / Thumb_Down normalised to None (no action mapping).
- mouse / mouse_scroll modes disabled (unreachable).
- ILoveYou left/right swipe switches modes (standby/presentation/solidworks).
- Victory HOLD toggles pen mode in presentation.
- SolidWorks: Thumb_Up fit and ILoveYou isometric removed.
"""
from __future__ import annotations

import pytest

from hands.gesture_config import (
    GestureConfig,
    MODE_MOUSE,
    MODE_MOUSE_SCROLL,
    MODE_PAUSED,
    MODE_PRESENTATION,
    MODE_PRESENTATION_PEN,
    MODE_SOLIDWORKS,
    MODE_STANDBY,
)
from hands.gesture_state import (
    ActionIntent,
    Gesture,
    GestureState,
    HandInput,
    StepResult,
    _interp,
    _normalize_gesture,
    G_CLOSED_FIST,
    G_NONE,
    G_OPEN_PALM,
    G_PINCH,
    G_POINTING_UP,
    G_THUMB_DOWN,
    G_THUMB_UP,
    G_VICTORY,
    G_ILOVEYOU,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _cfg(**overrides) -> GestureConfig:
    """Build a test config with minimal cooldowns so tests don't need sleeps."""
    defaults = dict(
        initial_mode=MODE_STANDBY,
        pause_on_start=False,
        wave_cooldown=0.0,
        wave_threshold=10.0,
        drag_cooldown=0.0,
        fist_exit_cooldown=0.0,
        single_cooldown=0.0,
        click_cooldown=0.0,
        pinch_click_distance=35.0,
        pinch_threshold=0.045,
        pinch_release_threshold=0.065,
        hand_loss_timeout=1.0,
        smoothening=1.0,
        mouse_smoothing=0.0,
        mouse_speed=1.0,
        mouse_max_step_px=80,
        mouse_fps=20,
        screen_size=(1920, 1080),
        start_presentation_hold=0.0,
        enter_mouse_hold=0.0,
        enter_solidworks_hold=0.0,
        exit_mode_hold=0.0,
        pen_mode_hold=0.0,
        erase_hold=0.0,
        page_turn_cooldown=0.0,
        mode_switch_cooldown=0.0,
        pen_toggle_cooldown=0.0,
        swipe_threshold_x=0.18,
        swipe_threshold_y_limit=0.12,
        swipe_time_window=0.8,
        iloveyou_swipe_threshold_x=0.22,
        drag_hold_time=0.35,
        click_max_movement_px=25,
        right_click_hold=0.5,
        right_click_cooldown=0.5,
        scroll_threshold_y=0.08,
        scroll_amount=5,
        scroll_cooldown=0.12,
        solidworks_drag_sensitivity=1.2,
        solidworks_zoom_sensitivity=8.0,
        solidworks_deadzone=0.01,
        pinch_zoom_deadzone=0.01,
        solidworks_view_cooldown=0.8,
        fit_view_hold=0.5,
        isometric_view_hold=0.8,
    )
    defaults.update(overrides)
    return GestureConfig(**defaults)


def _hand(gesture=Gesture.NONE, palm_xy=None, wave_x=None, pinch_distance=None) -> HandInput:
    return HandInput(gesture=gesture, palm_xy=palm_xy, wave_x=wave_x, pinch_distance=pinch_distance)


def _result_intents(state: GestureState, hand: HandInput, now: float = 1.0) -> list:
    return state.step(hand, now).intents


def _step(state: GestureState, hand: HandInput, now: float = 1.0) -> StepResult:
    return state.step(hand, now)


# ── _interp (preserved) ──────────────────────────────────────────────────────

class TestInterp:
    def test_basic(self) -> None:
        assert _interp(50, 0, 100, 0, 200) == 100.0

    def test_clamp_low(self) -> None:
        assert _interp(-10, 0, 100, 0, 200) == 0.0

    def test_clamp_high(self) -> None:
        assert _interp(110, 0, 100, 0, 200) == 200.0

    def test_zero_span(self) -> None:
        assert _interp(50, 10, 10, 0, 200) == 0.0


# ── gesture normalization (Phase 9: Thumb_Up/Thumb_Down → None) ──────────────

class TestNormalizeGesture:
    def test_legacy_fist(self) -> None:
        assert _normalize_gesture(Gesture.FIST) == G_CLOSED_FIST

    def test_legacy_single_finger(self) -> None:
        assert _normalize_gesture(Gesture.SINGLE_FINGER) == G_POINTING_UP

    def test_legacy_two_finger(self) -> None:
        assert _normalize_gesture(Gesture.TWO_FINGER) == G_VICTORY

    def test_spec_closed_fist(self) -> None:
        assert _normalize_gesture(Gesture.CLOSED_FIST) == G_CLOSED_FIST

    def test_thumb_up_normalised_to_none(self) -> None:
        """Phase 9: Thumb_Up is normalised to None (no action mapping)."""
        assert _normalize_gesture("Thumb_Up") == G_NONE
        assert _normalize_gesture(Gesture.THUMB_UP) == G_NONE

    def test_thumb_down_normalised_to_none(self) -> None:
        """Phase 9: Thumb_Down is normalised to None (no action mapping)."""
        assert _normalize_gesture("Thumb_Down") == G_NONE
        assert _normalize_gesture(Gesture.THUMB_DOWN) == G_NONE

    def test_none_input(self) -> None:
        assert _normalize_gesture(None) == G_NONE

    def test_iloveyou_normalised(self) -> None:
        assert _normalize_gesture(Gesture.ILOVEYOU) == G_ILOVEYOU
        assert _normalize_gesture("ILoveYou") == G_ILOVEYOU


# ── state construction ───────────────────────────────────────────────────────

class TestStateConstruction:
    def test_default_mode(self) -> None:
        cfg = _cfg(initial_mode=MODE_STANDBY)
        st = GestureState(cfg)
        assert st.mode == MODE_STANDBY
        assert not st.paused

    def test_pause_on_start(self) -> None:
        cfg = _cfg(pause_on_start=True)
        st = GestureState(cfg)
        assert st.paused


# ── toggle_pause ─────────────────────────────────────────────────────────────

class TestTogglePause:
    def test_toggle_on(self) -> None:
        st = GestureState(_cfg(pause_on_start=False))
        paused = st.toggle_pause()
        assert paused is True
        assert st.paused

    def test_toggle_off(self) -> None:
        st = GestureState(_cfg(pause_on_start=True))
        paused = st.toggle_pause()
        assert paused is False
        assert not st.paused

    def test_pause_releases_mouse(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION)
        st = GestureState(cfg)
        st.is_left_down = True
        st.toggle_pause()
        assert not st.is_left_down

    def test_resume_goes_to_standby(self) -> None:
        """Spec §11.4: resume always goes to standby."""
        st = GestureState(_cfg(initial_mode=MODE_PRESENTATION, pause_on_start=True))
        st.toggle_pause()  # resume
        assert st.mode == MODE_STANDBY


# ── set_active_mode ──────────────────────────────────────────────────────────

class TestModeSwitch:
    def test_set_active_mode_presentation(self) -> None:
        st = GestureState(_cfg())
        st.set_active_mode(MODE_PRESENTATION)
        assert st.mode == MODE_PRESENTATION

    def test_set_active_mode_invalid_raises(self) -> None:
        st = GestureState(_cfg())
        with pytest.raises(ValueError):
            st.set_active_mode("invalid")

    def test_solidworks_no_longer_raises(self) -> None:
        st = GestureState(_cfg())
        st.set_active_mode(MODE_SOLIDWORKS)
        assert st.mode == MODE_SOLIDWORKS

    def test_activate_from_paused(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION, pause_on_start=True)
        st = GestureState(cfg)
        result = st.activate_from_standby()
        assert result is True
        assert not st.paused


# ═══════════════════════════════════════════════════════════════════════════
# Phase 9: Standby mode — ILoveYou swipe switches modes
# ═══════════════════════════════════════════════════════════════════════════

class TestStandbyILoveYouSwipe:
    """Phase 9: ILoveYou swipe in standby switches modes."""

    def test_iloveyou_right_swipe_enters_presentation(self) -> None:
        """ILoveYou right swipe → presentation (no F5)."""
        cfg = _cfg(iloveyou_swipe_threshold_x=0.22, camera_width=640)
        st = GestureState(cfg)
        # Frame 1: establish start position.
        st.step(_hand(Gesture.ILOVEYOU, palm_xy=(200, 240)), now=1.0)
        # Frame 2: right swipe (dx = 200px, dx_norm = 200/640 = 0.3125 > 0.22).
        result = st.step(_hand(Gesture.ILOVEYOU, palm_xy=(400, 240)), now=1.1)
        assert st.mode == MODE_PRESENTATION
        # Phase 9: no F5 sent — PPT slideshow is user's responsibility.
        presses = [i for i in result.intents if i.type == "press"]
        assert len(presses) == 0

    def test_iloveyou_left_swipe_enters_solidworks(self) -> None:
        """ILoveYou left swipe → solidworks."""
        cfg = _cfg(iloveyou_swipe_threshold_x=0.22, camera_width=640)
        st = GestureState(cfg)
        st.step(_hand(Gesture.ILOVEYOU, palm_xy=(400, 240)), now=1.0)
        result = st.step(_hand(Gesture.ILOVEYOU, palm_xy=(200, 240)), now=1.1)
        assert st.mode == MODE_SOLIDWORKS

    def test_iloveyou_small_move_no_mode_change(self) -> None:
        """Small ILoveYou movement doesn't trigger mode switch."""
        cfg = _cfg(iloveyou_swipe_threshold_x=0.22, camera_width=640)
        st = GestureState(cfg)
        st.step(_hand(Gesture.ILOVEYOU, palm_xy=(300, 240)), now=1.0)
        result = st.step(_hand(Gesture.ILOVEYOU, palm_xy=(310, 240)), now=1.1)
        assert st.mode == MODE_STANDBY
        assert result.intents == []

    def test_open_palm_no_action_in_standby(self) -> None:
        """standby中Open_Palm不触发动作."""
        st = GestureState(_cfg())
        result = st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        assert result.intents == []
        assert st.mode == MODE_STANDBY

    def test_standby_closed_fist_releases(self) -> None:
        """Closed_Fist in standby emits release_all (safety)."""
        st = GestureState(_cfg(initial_mode=MODE_STANDBY))
        result = st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        types = [i.type for i in result.intents]
        assert "release_all" in types

    def test_thumb_up_in_standby_does_nothing(self) -> None:
        """Phase 9: Thumb_Up normalised to None, no action in standby."""
        st = GestureState(_cfg())
        result = st.step(_hand(Gesture.THUMB_UP), now=1.0)
        assert st.mode == MODE_STANDBY
        assert result.intents == []

    def test_thumb_down_in_standby_does_nothing(self) -> None:
        """Phase 9: Thumb_Down normalised to None, no action in standby."""
        st = GestureState(_cfg())
        result = st.step(_hand(Gesture.THUMB_DOWN), now=1.0)
        assert st.mode == MODE_STANDBY
        assert result.intents == []


# ═══════════════════════════════════════════════════════════════════════════
# Phase 9: Presentation mode
# ═══════════════════════════════════════════════════════════════════════════

class TestPresentationSwipe:
    """Open_Palm swipe for page turn (preserved from Phase 3)."""

    def test_swipe_right_triggers_next_page(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_threshold=10.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.1)
        presses = [i for i in result.intents if i.type == "press"]
        assert len(presses) == 1
        assert presses[0].key == "right"

    def test_swipe_left_triggers_prev_page(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_threshold=10.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.1)
        presses = [i for i in result.intents if i.type == "press"]
        assert len(presses) == 1
        assert presses[0].key == "left"

    def test_page_turn_cooldown_blocks_repeat(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_threshold=10.0,
                   page_turn_cooldown=1.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.1)
        assert any(i.type == "press" for i in result.intents)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=400.0), now=1.5)
        assert not any(i.type == "press" for i in result.intents)

    def test_one_swipe_one_turn(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_threshold=10.0,
                   page_turn_cooldown=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.0)
        result1 = st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.1)
        assert any(i.type == "press" for i in result1.intents)
        result2 = st.step(_hand(Gesture.OPEN_PALM, wave_x=400.0), now=1.2)
        assert not any(i.type == "press" for i in result2.intents)


class TestPresentationVictoryPen:
    """Phase 9: Victory HOLD toggles pen mode."""

    def test_victory_hold_enters_pen(self) -> None:
        """Victory HOLD → presentation_pen (Ctrl+P)."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, pen_mode_hold=0.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY), now=1.0)
        result = st.step(_hand(Gesture.VICTORY), now=2.0)
        assert st.mode == MODE_PRESENTATION_PEN
        hotkeys = [i for i in result.intents if i.type == "hotkey"]
        assert len(hotkeys) == 1
        assert hotkeys[0].keys == ["ctrl", "p"]

    def test_closed_fist_hold_exits_presentation(self) -> None:
        """Closed_Fist HOLD → standby (Esc + release_all)."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY
        types = [i.type for i in result.intents]
        assert "press" in types
        assert "release_all" in types

    def test_thumb_up_no_action_in_presentation(self) -> None:
        """Phase 9: Thumb_Up normalised to None, no action in presentation."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, pen_mode_hold=0.0)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.THUMB_UP), now=1.0)
        assert st.mode == MODE_PRESENTATION
        # Thumb_Up → None → no intents
        assert result.intents == []

    def test_thumb_down_no_action_in_presentation(self) -> None:
        """Phase 9: Thumb_Down normalised to None, no erase in presentation."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, erase_hold=0.0)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.THUMB_DOWN), now=1.0)
        assert st.mode == MODE_PRESENTATION
        assert result.intents == []


class TestPresentationILoveYouSwipe:
    """Phase 9: ILoveYou swipe in presentation switches modes.

    presentation: right→standby, left→solidworks.
    """

    def test_iloveyou_right_swipe_returns_to_standby(self) -> None:
        """From presentation: ILoveYou right swipe → standby (with Esc)."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION,
                   iloveyou_swipe_threshold_x=0.22, camera_width=640)
        st = GestureState(cfg)
        st.step(_hand(Gesture.ILOVEYOU, palm_xy=(200, 240)), now=1.0)
        result = st.step(_hand(Gesture.ILOVEYOU, palm_xy=(400, 240)), now=1.1)
        assert st.mode == MODE_STANDBY
        # Should include Esc to exit PPT and release_all.
        types = [i.type for i in result.intents]
        assert "press" in types  # Esc
        assert "release_all" in types

    def test_iloveyou_left_swipe_enters_solidworks(self) -> None:
        """From presentation: ILoveYou left swipe → solidworks."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION,
                   iloveyou_swipe_threshold_x=0.22, camera_width=640)
        st = GestureState(cfg)
        st.step(_hand(Gesture.ILOVEYOU, palm_xy=(400, 240)), now=1.0)
        result = st.step(_hand(Gesture.ILOVEYOU, palm_xy=(200, 240)), now=1.1)
        assert st.mode == MODE_SOLIDWORKS
        assert any(i.type == "release_all" for i in result.intents)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 9: Presentation Pen mode
# ═══════════════════════════════════════════════════════════════════════════

class TestPresentationPenVictory:
    """Phase 9: Victory HOLD exits pen mode (not Thumb_Up)."""

    def test_victory_hold_returns_to_presentation(self) -> None:
        """Victory HOLD → back to presentation (mouse_up + Ctrl+A)."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pen_mode_hold=0.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY), now=1.0)
        result = st.step(_hand(Gesture.VICTORY), now=2.0)
        assert st.mode == MODE_PRESENTATION
        types = [i.type for i in result.intents]
        assert "hotkey" in types
        hotkey = [i for i in result.intents if i.type == "hotkey"][0]
        assert hotkey.keys == ["ctrl", "a"]

    def test_victory_hold_with_left_down_releases(self) -> None:
        """When left mouse is down, exit pen also emits mouse_up(left)."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pen_mode_hold=0.5)
        st = GestureState(cfg)
        st.is_left_mouse_down = True
        st.step(_hand(Gesture.VICTORY), now=1.0)
        result = st.step(_hand(Gesture.VICTORY), now=2.0)
        types = [i.type for i in result.intents]
        assert "mouse_up" in types

    def test_closed_fist_hold_exits_pen_to_standby(self) -> None:
        """Closed_Fist HOLD → standby (mouse_up + Esc + release_all)."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.is_left_mouse_down = True
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY
        types = [i.type for i in result.intents]
        assert "mouse_up" in types
        assert "press" in types
        assert "release_all" in types

    def test_thumb_up_no_action_in_pen(self) -> None:
        """Phase 9: Thumb_Up normalised to None, no action in pen mode."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pen_mode_hold=0.0)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.THUMB_UP), now=1.0)
        assert st.mode == MODE_PRESENTATION_PEN
        # Thumb_Up → None, may trigger hand-loss or no-op
        # No hardware actions should fire.
        hw_types = {"press", "hotkey", "mouse_down", "mouse_up", "click", "scroll",
                    "key_down", "key_up"}
        assert not any(i.type in hw_types for i in result.intents)

    def test_thumb_down_no_action_in_pen(self) -> None:
        """Phase 9: Thumb_Down normalised to None, no erase in pen mode."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, erase_hold=0.0)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.THUMB_DOWN), now=1.0)
        assert st.mode == MODE_PRESENTATION_PEN
        hw_types = {"press", "hotkey", "mouse_down", "mouse_up", "click", "scroll",
                    "key_down", "key_up"}
        assert not any(i.type in hw_types for i in result.intents)


class TestPresentationPenPinch:
    """PINCH draw with hysteresis (preserved from Phase 3)."""

    def test_pinch_start_triggers_mouse_down_once(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pinch_click_distance=35.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 1
        assert mouse_downs[0].button == "left"
        assert st.is_left_mouse_down
        assert st.is_pinching

    def test_pinch_hold_no_repeat_mouse_down(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pinch_click_distance=35.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(321, 241), pinch_distance=30.0), now=1.2)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 0
        assert st.is_pinching

    def test_pinch_release_triggers_mouse_up(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pinch_click_distance=35.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        assert st.is_left_mouse_down
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=55.0), now=1.2)
        mouse_ups = [i for i in result.intents if i.type == "mouse_up"]
        assert len(mouse_ups) == 1
        assert not st.is_left_mouse_down
        assert not st.is_pinching

    def test_pinch_hysteresis_no_jitter(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pinch_click_distance=35.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        assert st.is_pinching
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=40.0), now=1.2)
        assert st.is_pinching

    def test_full_pinch_draw_cycle(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pinch_click_distance=35.0)
        st = GestureState(cfg)
        r1 = st.step(_hand(Gesture.POINTING_UP, palm_xy=(300, 200), pinch_distance=50.0), now=1.0)
        assert not st.is_pinching
        r2 = st.step(_hand(Gesture.POINTING_UP, palm_xy=(310, 210), pinch_distance=30.0), now=1.1)
        assert st.is_pinching
        assert st.is_left_mouse_down
        r3 = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 220), pinch_distance=30.0), now=1.2)
        assert not any(i.type == "mouse_down" for i in r3.intents)
        r4 = st.step(_hand(Gesture.POINTING_UP, palm_xy=(330, 230), pinch_distance=55.0), now=1.3)
        assert not st.is_pinching
        assert not st.is_left_mouse_down
        assert any(i.type == "mouse_up" for i in r4.intents)

    def test_pen_none_timeout_releases_left(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, hand_loss_timeout=1.0,
                   pinch_click_distance=35.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        assert st.is_left_mouse_down
        result = st.step(_hand(Gesture.NONE), now=3.0)
        types = [i.type for i in result.intents]
        assert "mouse_up" in types
        assert "release_all" in types
        assert st.mode == MODE_PRESENTATION_PEN
        assert not st.is_left_mouse_down


# ═══════════════════════════════════════════════════════════════════════════
# Phase 9: mouse / mouse_scroll modes are disabled
# ═══════════════════════════════════════════════════════════════════════════

class TestMouseModeDisabled:
    """Phase 9: mouse/mouse_scroll modes are disabled and unreachable."""

    def test_mouse_mode_falls_back_to_standby(self) -> None:
        """If somehow in mouse mode, immediately falls back to standby."""
        cfg = _cfg(initial_mode=MODE_MOUSE)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240)), now=1.0)
        assert st.mode == MODE_STANDBY
        assert any(i.type == "release_all" for i in result.intents)

    def test_mouse_scroll_mode_falls_back_to_standby(self) -> None:
        """If somehow in mouse_scroll mode, immediately falls back to standby."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240)), now=1.0)
        assert st.mode == MODE_STANDBY
        assert any(i.type == "release_all" for i in result.intents)

    def test_pointing_up_in_standby_does_not_enter_mouse(self) -> None:
        """Phase 9: Pointing_Up no longer enters mouse mode via HOLD."""
        cfg = _cfg(enter_mouse_hold=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP), now=1.0)
        st.step(_hand(Gesture.POINTING_UP), now=2.0)
        assert st.mode == MODE_STANDBY


# ═══════════════════════════════════════════════════════════════════════════
# Phase 9: SolidWorks mode
# ═══════════════════════════════════════════════════════════════════════════

class TestSolidWorksRotate:
    """Open_Palm rotate (preserved from Phase 5)."""

    def test_open_palm_start_triggers_mouse_down_middle(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 200)), now=1.0)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 1
        assert mouse_downs[0].button == "middle"
        assert st.is_middle_mouse_down
        assert st.active_continuous_action == "solidworks_rotate"

    def test_open_palm_continuous_move_outputs_move_rel(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(350, 250)), now=1.1)
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(380, 280)), now=1.2)
        moves = [i for i in result.intents if i.type == "move_rel"]
        assert len(moves) >= 1

    def test_open_palm_hold_no_repeat_mouse_down(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(350, 250)), now=1.1)
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(360, 260)), now=1.2)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 0
        assert st.is_middle_mouse_down

    def test_open_palm_end_triggers_mouse_up_middle(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(350, 250)), now=1.1)
        assert st.is_middle_mouse_down
        result = st.step(_hand(Gesture.POINTING_UP), now=1.2)
        mouse_ups = [i for i in result.intents if i.type == "mouse_up"]
        assert len(mouse_ups) == 1
        assert not st.is_middle_mouse_down
        assert st.active_continuous_action is None


class TestSolidWorksPan:
    """Victory pan (preserved from Phase 5)."""

    def test_victory_start_triggers_shift_and_middle(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(300, 200)), now=1.0)
        key_downs = [i for i in result.intents if i.type == "key_down"]
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(key_downs) == 1
        assert key_downs[0].key == "shift"
        assert len(mouse_downs) == 1
        assert mouse_downs[0].button == "middle"
        assert st.is_shift_down
        assert st.is_middle_mouse_down
        assert st.active_continuous_action == "solidworks_pan"

    def test_victory_continuous_move_outputs_move_rel(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.VICTORY, palm_xy=(350, 250)), now=1.1)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(380, 280)), now=1.2)
        moves = [i for i in result.intents if i.type == "move_rel"]
        assert len(moves) >= 1

    def test_victory_hold_no_repeat(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.VICTORY, palm_xy=(350, 250)), now=1.1)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(360, 260)), now=1.2)
        assert not any(i.type == "key_down" for i in result.intents)
        assert not any(i.type == "mouse_down" for i in result.intents)

    def test_victory_end_triggers_mouse_up_and_key_up(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.VICTORY, palm_xy=(350, 250)), now=1.1)
        result = st.step(_hand(Gesture.POINTING_UP), now=1.2)
        mouse_ups = [i for i in result.intents if i.type == "mouse_up"]
        key_ups = [i for i in result.intents if i.type == "key_up"]
        assert len(mouse_ups) == 1
        assert len(key_ups) == 1
        assert key_ups[0].key == "shift"
        assert not st.is_middle_mouse_down
        assert not st.is_shift_down


class TestSolidWorksMutualExclusion:
    """Rotate/pan/zoom mutual exclusion (preserved from Phase 5)."""

    def test_rotate_to_pan_releases_middle_first(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(350, 250)), now=1.1)
        assert st.active_continuous_action == "solidworks_rotate"
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(360, 260)), now=1.2)
        types = [i.type for i in result.intents]
        if "mouse_up" in types and "key_down" in types:
            assert types.index("mouse_up") < types.index("key_down")
        assert st.active_continuous_action == "solidworks_pan"

    def test_pan_to_rotate_releases_middle_and_shift_first(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.VICTORY, palm_xy=(350, 250)), now=1.1)
        assert st.active_continuous_action == "solidworks_pan"
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(360, 260)), now=1.2)
        assert st.active_continuous_action == "solidworks_rotate"
        assert not st.is_shift_down

    def test_rotate_to_zoom_releases_middle(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0,
                   pinch_click_distance=35.0, pinch_zoom_deadzone=0.0,
                   solidworks_zoom_sensitivity=8.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(350, 250)), now=1.1)
        assert st.is_middle_mouse_down
        result = st.step(_hand(Gesture.PINCH, palm_xy=(350, 250), pinch_distance=30.0), now=1.2)
        mouse_ups = [i for i in result.intents if i.type == "mouse_up"]
        assert len(mouse_ups) >= 1
        assert not st.is_middle_mouse_down


class TestSolidWorksZoom:
    """PINCH zoom (preserved from Phase 5)."""

    def test_pinch_distance_increase_scrolls_positive(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, pinch_click_distance=35.0,
                   pinch_zoom_deadzone=0.0, solidworks_zoom_sensitivity=8.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.PINCH, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        assert st.is_pinching
        result = st.step(_hand(Gesture.PINCH, palm_xy=(320, 240), pinch_distance=35.0), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) >= 1
        assert scrolls[0].amount > 0

    def test_pinch_distance_decrease_scrolls_negative(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, pinch_click_distance=35.0,
                   pinch_zoom_deadzone=0.0, solidworks_zoom_sensitivity=8.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.PINCH, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        assert st.is_pinching
        result = st.step(_hand(Gesture.PINCH, palm_xy=(320, 240), pinch_distance=25.0), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) >= 1
        assert scrolls[0].amount < 0

    def test_pinch_small_change_no_scroll(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, pinch_click_distance=35.0,
                   pinch_zoom_deadzone=100.0, solidworks_zoom_sensitivity=8.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.PINCH, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        result = st.step(_hand(Gesture.PINCH, palm_xy=(320, 240), pinch_distance=31.0), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) == 0


class TestSolidWorksPhase9Changes:
    """Phase 9 specific changes to SolidWorks mode."""

    def test_thumb_up_no_fit_view(self) -> None:
        """Phase 9: Thumb_Up normalised to None, no fit view action."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, fit_view_hold=0.0)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.THUMB_UP), now=1.0)
        assert st.mode == MODE_SOLIDWORKS
        # Thumb_Up → None, may trigger no-hand or no-op. No press("f").
        presses = [i for i in result.intents if i.type == "press" and i.key == "f"]
        assert len(presses) == 0

    def test_iloveyou_swipe_switches_mode(self) -> None:
        """Phase 9: ILoveYou right swipe in solidworks → presentation."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS,
                   iloveyou_swipe_threshold_x=0.22, camera_width=640)
        st = GestureState(cfg)
        # Right swipe → presentation (no F5)
        st.step(_hand(Gesture.ILOVEYOU, palm_xy=(200, 240)), now=1.0)
        result = st.step(_hand(Gesture.ILOVEYOU, palm_xy=(400, 240)), now=1.1)
        assert st.mode == MODE_PRESENTATION
        # Should have release_all for safety.
        types = [i.type for i in result.intents]
        assert "release_all" in types
        # No F5.
        presses = [i for i in result.intents if i.type == "press" and i.key == "f5"]
        assert len(presses) == 0

    def test_iloveyou_left_swipe_returns_to_standby(self) -> None:
        """Phase 9: ILoveYou left swipe in solidworks → standby."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS,
                   iloveyou_swipe_threshold_x=0.22, camera_width=640)
        st = GestureState(cfg)
        st.step(_hand(Gesture.ILOVEYOU, palm_xy=(400, 240)), now=1.0)
        result = st.step(_hand(Gesture.ILOVEYOU, palm_xy=(200, 240)), now=1.1)
        assert st.mode == MODE_STANDBY
        assert any(i.type == "release_all" for i in result.intents)

    def test_closed_fist_hold_exits_to_standby(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY
        assert "release_all" in [i.type for i in result.intents]

    def test_exit_clears_active_continuous_action(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, exit_mode_hold=0.0,
                   solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(350, 250)), now=1.1)
        assert st.active_continuous_action == "solidworks_rotate"
        st.step(_hand(Gesture.CLOSED_FIST), now=1.2)
        assert st.mode == MODE_STANDBY
        assert st.active_continuous_action is None
        assert not st.is_middle_mouse_down
        assert not st.is_shift_down

    def test_none_timeout_releases_and_stays_solidworks(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, hand_loss_timeout=1.0,
                   solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.VICTORY, palm_xy=(350, 250)), now=1.1)
        assert st.is_middle_mouse_down
        result = st.step(_hand(Gesture.NONE), now=3.0)
        types = [i.type for i in result.intents]
        assert "mouse_up" in types
        assert "key_up" in types
        assert "release_all" in types
        assert not st.is_middle_mouse_down
        assert not st.is_shift_down
        assert st.active_continuous_action is None
        assert st.mode == MODE_SOLIDWORKS


class TestSolidWorksDeadzone:
    """Deadzone filtering (preserved from Phase 5)."""

    def test_open_palm_small_move_no_move_rel(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.1,
                   camera_width=640, camera_height=480)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(320, 240)), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(325, 245)), now=1.1)
        moves = [i for i in result.intents if i.type == "move_rel"]
        assert len(moves) == 0

    def test_victory_small_move_no_move_rel(self) -> None:
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.1,
                   camera_width=640, camera_height=480)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240)), now=1.0)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(325, 245)), now=1.1)
        moves = [i for i in result.intents if i.type == "move_rel"]
        assert len(moves) == 0


# ═══════════════════════════════════════════════════════════════════════════
# None / hand-loss handling
# ═══════════════════════════════════════════════════════════════════════════

class TestNoneHandLoss:
    """None超过hand_lost_timeout后触发release_all."""

    def test_short_none_no_release(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION, hand_loss_timeout=2.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        result = st.step(_hand(Gesture.NONE), now=1.5)
        assert not any(i.type == "release_all" for i in result.intents)

    def test_long_none_triggers_release_all(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION, hand_loss_timeout=1.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        result = st.step(_hand(Gesture.NONE), now=3.0)
        types = [i.type for i in result.intents]
        assert "release_all" in types
        assert types.count("release_all") == 1
        assert st._hand_loss_released is True

    def test_long_none_repeated_frames_emit_release_all_once(self) -> None:
        """同一连续无手事件超过超时后只输出一次 release_all。"""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, hand_loss_timeout=1.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        # First timeout frame: emit release_all.
        r1 = st.step(_hand(Gesture.NONE), now=3.0)
        assert r1.intents.count(ActionIntent.release_all()) == 1
        # Subsequent no-hand frames: empty intents.
        for t in (3.1, 3.2, 3.3, 4.0, 5.0):
            r = st.step(_hand(Gesture.NONE), now=t)
            assert r.intents == [], f"expected no intents at t={t}, got {r.intents}"
            assert r.note == "Hand lost timeout (already released)"
        assert st._hand_loss_released is True

    def test_hand_reappearance_rearms_hand_loss_release(self) -> None:
        """手重新出现后，下一次独立无手事件仍可再次触发 release_all。"""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, hand_loss_timeout=1.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        # First hand-loss event.
        r1 = st.step(_hand(Gesture.NONE), now=3.0)
        assert r1.intents.count(ActionIntent.release_all()) == 1
        # Hand comes back: latch resets.
        r2 = st.step(_hand(Gesture.OPEN_PALM), now=4.0)
        assert st._hand_loss_released is False
        # Second independent hand-loss event: release_all again.
        r3 = st.step(_hand(Gesture.NONE), now=6.0)
        assert r3.intents.count(ActionIntent.release_all()) == 1
        # No further duplicates.
        r4 = st.step(_hand(Gesture.NONE), now=7.0)
        assert r4.intents == []

    def test_pen_none_timeout_releases_left_once(self) -> None:
        """画笔模式下无手超时释放左键并只触发一次。"""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, hand_loss_timeout=1.0,
                   pinch_click_distance=35.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        assert st.is_left_mouse_down
        # First timeout: mouse_up + release_all.
        r1 = st.step(_hand(Gesture.NONE), now=3.0)
        types = [i.type for i in r1.intents]
        assert types.count("mouse_up") == 1
        assert types.count("release_all") == 1
        assert not st.is_left_mouse_down
        # Subsequent no-hand frames: nothing.
        r2 = st.step(_hand(Gesture.NONE), now=4.0)
        assert r2.intents == []
        assert st.mode == MODE_PRESENTATION_PEN

    def test_solidworks_none_timeout_releases_continuous_once(self) -> None:
        """SolidWorks 连续操作无手超时只释放一次。"""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, hand_loss_timeout=1.0,
                   solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.VICTORY, palm_xy=(350, 250)), now=1.1)
        assert st.is_middle_mouse_down and st.is_shift_down
        r1 = st.step(_hand(Gesture.NONE), now=3.0)
        types = [i.type for i in r1.intents]
        assert types.count("mouse_up") == 1
        assert types.count("key_up") == 1
        assert types.count("release_all") == 1
        assert st.mode == MODE_SOLIDWORKS
        # Repeated frames: no duplicate.
        r2 = st.step(_hand(Gesture.NONE), now=4.0)
        assert r2.intents == []

    def test_force_release_prevents_duplicate_hand_loss_release(self) -> None:
        """显式 force_release 后同一无手时段不再重复 release_all。"""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, hand_loss_timeout=1.0)
        st = GestureState(cfg)
        st.is_left_mouse_down = True
        st.is_shift_down = True
        # Explicit release before timeout is reached.
        intents = st.force_release()
        assert intents.count(ActionIntent.release_all()) == 1
        assert st._hand_loss_released is True
        # Later no-hand timeout frame must not duplicate.
        r = st.step(_hand(Gesture.NONE), now=10.0)
        assert r.intents == []

    def test_hand_present_after_force_release_rearms(self) -> None:
        """force_release 后见手，下一次无手事件仍可触发。"""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, hand_loss_timeout=1.0)
        st = GestureState(cfg)
        st.is_left_mouse_down = True
        st.force_release()
        assert st._hand_loss_released is True
        st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        assert st._hand_loss_released is False
        r = st.step(_hand(Gesture.NONE), now=3.0)
        assert r.intents.count(ActionIntent.release_all()) == 1

    def test_force_release(self) -> None:
        st = GestureState(_cfg())
        st.is_left_down = True
        st.is_single_mouse_active = True
        intents = st.force_release()
        assert st.is_left_down is False
        assert st.is_single_mouse_active is False
        kinds = [i.type for i in intents]
        assert "release_all" in kinds

    def test_release_all_is_idempotent(self) -> None:
        """release_all 多次调用不产生副作用（幂等）。"""
        st = GestureState(_cfg())
        st.is_left_mouse_down = True
        st.is_middle_mouse_down = True
        st.is_shift_down = True
        # First call releases everything.
        intents1 = st.force_release()
        assert "release_all" in [i.type for i in intents1]
        assert not st.is_left_mouse_down
        assert not st.is_middle_mouse_down
        assert not st.is_shift_down
        # Second call — no crash, no side effects, state stays clean.
        intents2 = st.force_release()
        assert intents2 == []
        assert not st.is_left_mouse_down
        assert not st.is_middle_mouse_down
        assert not st.is_shift_down

    def test_release_all_action_idempotent(self) -> None:
        """ActionIntent.release_all() itself is always safe to emit multiple times."""
        from hands.gesture_actions import ActionLayer, FakeDriver
        driver = FakeDriver()
        actions = ActionLayer(enable_system_mouse=False, driver=driver)
        # Emit release_all three times in a row — must not crash.
        actions.execute([
            ActionIntent.release_all(),
            ActionIntent.release_all(),
            ActionIntent.release_all(),
        ])
        # No exception means pass. release_all internally calls mouseUp/keyUp
        # for each held button/key, which FakeDriver records individually.

    def test_should_release_on_hand_loss_false_when_no_hold(self) -> None:
        st = GestureState(_cfg())
        assert st.should_release_on_hand_loss(now=100.0) is False


# ═══════════════════════════════════════════════════════════════════════════
# Cooldown
# ═══════════════════════════════════════════════════════════════════════════

class TestCooldown:
    """cooldown内不重复触发离散动作."""

    def test_mode_switch_cooldown_blocks_reentry(self) -> None:
        cfg = _cfg(iloveyou_swipe_threshold_x=0.22, camera_width=640,
                   mode_switch_cooldown=5.0)
        st = GestureState(cfg)
        # Enter presentation via ILoveYou right swipe
        st.step(_hand(Gesture.ILOVEYOU, palm_xy=(200, 240)), now=1.0)
        st.step(_hand(Gesture.ILOVEYOU, palm_xy=(400, 240)), now=1.1)
        assert st.mode == MODE_PRESENTATION
        assert not st._cooldown_ok("mode_switch", 1.1)

    def test_release_all_not_blocked_by_cooldown(self) -> None:
        """release_all不受cooldown限制."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, exit_mode_hold=0.0,
                   mode_switch_cooldown=100.0)
        st = GestureState(cfg)
        st._set_cooldown("mode_switch", 100.0, 1.0)
        st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY


# ═══════════════════════════════════════════════════════════════════════════
# Paused
# ═══════════════════════════════════════════════════════════════════════════

class TestPausedState:
    """paused中任意手势不触发硬件动作."""

    def test_paused_blocks_actions(self) -> None:
        st = GestureState(_cfg(initial_mode=MODE_PRESENTATION, pause_on_start=True))
        result = st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        assert result.intents == []
        assert "PAUSED" in result.note

    def test_paused_still_tracks_hand(self) -> None:
        st = GestureState(_cfg(pause_on_start=True))
        st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        assert st.last_hand_seen == 1.0

    def test_paused_no_hardware_for_any_gesture(self) -> None:
        st = GestureState(_cfg(pause_on_start=True))
        result = st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        assert result.intents == []
        assert result.mode == MODE_PAUSED

    def test_paused_mode_in_result(self) -> None:
        st = GestureState(_cfg(pause_on_start=True))
        result = st.step(_hand(Gesture.VICTORY), now=1.0)
        assert result.mode == MODE_PAUSED

    def test_paused_hand_reappearance_rearms_hand_loss_latch(self) -> None:
        """force_release 后 paused 分支见手必须重新布防，恢复后再次无手才能释放。"""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, pause_on_start=True, hand_loss_timeout=1.0)
        st = GestureState(cfg)
        st.is_left_mouse_down = True

        # 1. paused 中显式 force_release：释放一次并置位锁存。
        intents = st.force_release()
        assert intents.count(ActionIntent.release_all()) == 1
        assert st._hand_loss_released is True
        assert not st.is_left_mouse_down

        # 2. paused 中识别有效手：锁存重新布防。
        r1 = st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        assert r1.intents == []
        assert r1.mode == MODE_PAUSED
        assert st._hand_loss_released is False
        assert st.hand_lost_start_time is None

        # 3. 恢复（进入 standby）。
        st.toggle_pause()
        assert st.paused is False
        assert st.mode == MODE_STANDBY

        # 4. 恢复后新的连续操作使某按键处于按下状态。
        st.is_left_mouse_down = True

        # 5. 持续无手首次超过超时：恰好输出一次 release_all。
        r2 = st.step(_hand(Gesture.NONE), now=3.0)
        assert r2.intents.count(ActionIntent.release_all()) == 1
        assert st._hand_loss_released is True

        # 6. 后续连续无手帧不再重复输出。
        r3 = st.step(_hand(Gesture.NONE), now=4.0)
        assert r3.intents == []
        assert r3.note == "Hand lost timeout (already released)"


# ═══════════════════════════════════════════════════════════════════════════
# ActionIntent / StepResult compat (preserved)
# ═══════════════════════════════════════════════════════════════════════════

class TestActionIntentFields:
    def test_press_has_key_field(self) -> None:
        i = ActionIntent.press("right")
        assert i.type == "press"
        assert i.key == "right"
        assert i.args == ("right",)

    def test_hotkey_has_keys_field(self) -> None:
        i = ActionIntent.hotkey("ctrl", "p")
        assert i.type == "hotkey"
        assert i.keys == ["ctrl", "p"]

    def test_move_has_xy_fields(self) -> None:
        i = ActionIntent.move(100.0, 200.0)
        assert i.type == "move"
        assert i.x == 100.0
        assert i.y == 200.0

    def test_release_all_has_type_only(self) -> None:
        i = ActionIntent.release_all()
        assert i.type == "release_all"
        assert i.args == ()

    def test_new_factory_methods(self) -> None:
        assert ActionIntent.move_to(1, 2).type == "move_to"
        assert ActionIntent.move_rel(3, 4).type == "move_rel"
        assert ActionIntent.scroll(5).type == "scroll"
        assert ActionIntent.key_down("shift").type == "key_down"
        assert ActionIntent.key_up("shift").type == "key_up"
        assert ActionIntent.status("hi").type == "status"
        assert ActionIntent.noop().type == "noop"


class TestStepResultCompat:
    def test_note_alias_for_status_text(self) -> None:
        r = StepResult(mode=MODE_STANDBY, status_text="hello")
        assert r.note == "hello"

    def test_debug_info_present(self) -> None:
        st = GestureState(_cfg())
        result = st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        assert "mode" in result.debug_info
        assert "current_gesture" in result.debug_info

    def test_debug_info_includes_phase7_fields(self) -> None:
        st = GestureState(_cfg())
        result = st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        assert "hand_lost_duration" in result.debug_info
        assert "cooldown_until" in result.debug_info


# ═══════════════════════════════════════════════════════════════════════════
# Dry-run safety (preserved)
# ═══════════════════════════════════════════════════════════════════════════

class TestDryRunSafety:
    def test_dry_run_solidworks_actions_recorded_only(self) -> None:
        from hands.gesture_actions import ActionLayer, FakeDriver
        driver = FakeDriver()
        actions = ActionLayer(enable_system_mouse=False, driver=driver)
        actions.execute([
            ActionIntent.mouse_down(button="middle"),
            ActionIntent.move_rel(10, 20),
            ActionIntent.mouse_up(button="middle"),
            ActionIntent.key_down("shift"),
            ActionIntent.scroll(5),
            ActionIntent.key_up("shift"),
            ActionIntent.press("f"),
            ActionIntent.hotkey("ctrl", "7"),
            ActionIntent.release_all(),
        ])
        assert ("mouse_down", "middle") in driver.events
        assert ("move_rel", 10, 20) in driver.events
        assert ("mouse_up", "middle") in driver.events
        assert ("key_down", "shift") in driver.events
        assert ("scroll", 5) in driver.events
        assert ("key_up", "shift") in driver.events
        assert ("press", "f") in driver.events
        assert ("hotkey", ["ctrl", "7"]) in driver.events
