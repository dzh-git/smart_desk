"""Tests for hands.gesture_state — pure-logic state machine.

No camera, no pyautogui, no MediaPipe. Just the state machine fed synthetic
HandInput frames and asserted on ActionIntent lists.
"""
from __future__ import annotations

import pytest

from hands.gesture_config import (
    GestureConfig,
    MODE_MOUSE,
    MODE_PRESENTATION,
    MODE_STANDBY,
)
from hands.gesture_state import (
    ActionIntent,
    Gesture,
    GestureState,
    HandInput,
    StepResult,
    _interp,
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
        hand_loss_timeout=1.0,
        smoothening=1.0,
        mouse_fps=20,
        screen_size=(1920, 1080),
    )
    defaults.update(overrides)
    return GestureConfig(**defaults)


def _hand(gesture: Gesture = Gesture.NONE, palm_xy=None, wave_x=None, pinch_distance=None) -> HandInput:
    return HandInput(gesture=gesture, palm_xy=palm_xy, wave_x=wave_x, pinch_distance=pinch_distance)


def _result_intents(state: GestureState, hand: HandInput, now: float = 1.0) -> list[ActionIntent]:
    return state.step(hand, now).intents


# ── _interp ──────────────────────────────────────────────────────────────────

class TestInterp:
    def test_basic(self) -> None:
        assert _interp(50, 0, 100, 0, 200) == 100.0

    def test_clamp_low(self) -> None:
        assert _interp(-10, 0, 100, 0, 200) == 0.0

    def test_clamp_high(self) -> None:
        assert _interp(110, 0, 100, 0, 200) == 200.0

    def test_zero_span(self) -> None:
        assert _interp(50, 10, 10, 0, 200) == 0.0


# ── state construction ────────────────────────────────────────────────────────

class TestStateConstruction:
    def test_default_mode(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, pause_on_start=False)
        st = GestureState(cfg)
        assert st.mode == MODE_MOUSE
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
        cfg = _cfg(initial_mode=MODE_MOUSE, pause_on_start=False)
        st = GestureState(cfg)
        st.is_left_down = True
        st.toggle_pause()
        assert not st.is_left_down


# ── set_active_mode / activate_from_standby ─────────────────────────────────

class TestModeSwitch:
    def test_set_active_mode_mouse(self) -> None:
        st = GestureState(_cfg())
        st.set_active_mode(MODE_MOUSE)
        assert st.mode == MODE_MOUSE
        assert not st.paused

    def test_set_active_mode_presentation(self) -> None:
        st = GestureState(_cfg())
        st.set_active_mode(MODE_PRESENTATION)
        assert st.mode == MODE_PRESENTATION

    def test_set_active_mode_invalid_raises(self) -> None:
        st = GestureState(_cfg())
        with pytest.raises(ValueError):
            st.set_active_mode("invalid")

    def test_solidworks_not_implemented(self) -> None:
        st = GestureState(_cfg())
        with pytest.raises(NotImplementedError):
            st.set_active_mode("solidworks")

    def test_activate_from_standby_promotes(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, pause_on_start=False)
        st = GestureState(cfg)
        st.mode = MODE_STANDBY
        st.activate_from_standby()
        assert st.mode == MODE_MOUSE

    def test_activate_from_paused(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION, pause_on_start=True)
        st = GestureState(cfg)
        result = st.activate_from_standby()
        assert result is True
        assert not st.paused


# ── no-hand handling ─────────────────────────────────────────────────────────

class TestNoHand:
    def test_no_hand_no_intents(self) -> None:
        st = GestureState(_cfg(initial_mode=MODE_MOUSE))
        intents = _result_intents(st, _hand(Gesture.NONE))
        assert intents == []

    def test_no_hand_resets_wave(self) -> None:
        st = GestureState(_cfg(initial_mode=MODE_PRESENTATION))
        st.prev_wave_x = 300.0
        _result_intents(st, _hand(Gesture.NONE))
        assert st.prev_wave_x is None

    def test_hand_loss_timeout_releases_drag(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, hand_loss_timeout=2.0)
        st = GestureState(cfg)
        st.is_left_down = True
        st.last_hand_seen = 0.0
        # Simulate a hand appearing briefly, then disappearing.
        _result_intents(st, _hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160)), now=1.0)
        assert st.last_hand_seen == 1.0
        # Hand gone for > timeout
        intents = _result_intents(st, _hand(Gesture.NONE), now=4.0)
        kinds = [i.kind for i in intents]
        assert "release_all" in kinds or "mouse_up" in kinds

    def test_force_release(self) -> None:
        st = GestureState(_cfg())
        st.is_left_down = True
        st.is_single_mouse_active = True
        intents = st.force_release()
        assert st.is_left_down is False
        assert st.is_single_mouse_active is False
        kinds = [i.kind for i in intents]
        assert "release_all" in kinds

    def test_should_release_on_hand_loss_false_when_no_hold(self) -> None:
        st = GestureState(_cfg())
        assert st.should_release_on_hand_loss(now=100.0) is False


# ── paused ────────────────────────────────────────────────────────────────────

class TestPausedState:
    def test_paused_blocks_actions(self) -> None:
        st = GestureState(_cfg(initial_mode=MODE_PRESENTATION, pause_on_start=True))
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(320, 160)), now=1.0)
        assert result.intents == []
        assert "PAUSED" in result.note

    def test_paused_still_tracks_hand(self) -> None:
        st = GestureState(_cfg(pause_on_start=True))
        st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        assert st.last_hand_seen == 1.0


# ── presentation mode ────────────────────────────────────────────────────────

class TestPresentationMode:
    def test_open_palm_wave_right(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_cooldown=0.0, wave_threshold=10.0)
        st = GestureState(cfg)
        # First frame: set prev_wave_x
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 160), wave_x=300.0), now=1.0)
        # Second frame: move right past threshold
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(350, 160), wave_x=350.0), now=1.1)
        kinds = [i.kind for i in result.intents]
        assert "press" in kinds
        # The diff is positive (moved right in camera) → press('right')
        if result.intents:
            assert result.intents[0].args == ("right",)

    def test_open_palm_wave_left(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_cooldown=0.0, wave_threshold=10.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=330.0), now=1.1)
        # diff = 330 - 350 = -20 < -threshold → press('left')
        kinds = [i.kind for i in result.intents]
        assert "press" in kinds
        if result.intents:
            assert result.intents[0].args == ("left",)

    def test_wave_cooldown(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_cooldown=1.0, wave_threshold=10.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.5)
        # Within cooldown → no press
        assert result.intents == []

    def test_fist_returns_standby(self) -> None:
        st = GestureState(_cfg(initial_mode=MODE_PRESENTATION))
        result = st.step(_hand(Gesture.FIST), now=1.0)
        assert st.mode == MODE_STANDBY

    def test_non_open_palm_ignores_wave(self) -> None:
        st = GestureState(_cfg(initial_mode=MODE_PRESENTATION))
        result = st.step(_hand(Gesture.SINGLE_FINGER, wave_x=300.0), now=1.0)
        assert result.intents == []


# ── mouse mode — single finger ──────────────────────────────────────────────

class TestMouseSingleFinger:
    def test_enter_single_finger_moves_cursor(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, single_cooldown=0.0, screen_size=(1920, 1080))
        st = GestureState(cfg)
        # First stable frame: enters single-finger mode
        result = st.step(
            _hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160)),
            now=1.0,
        )
        assert st.is_single_mouse_active

    def test_move_intent_produced(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, single_cooldown=0.0, mouse_fps=20, screen_size=(1920, 1080))
        st = GestureState(cfg)
        st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160)), now=1.0)
        # Second frame: should produce a move intent
        result = st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(330, 170)), now=1.1)
        move_intents = [i for i in result.intents if i.kind == "move"]
        assert len(move_intents) == 1

    def test_pinch_click(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, single_cooldown=0.0, click_cooldown=0.0, pinch_click_distance=35.0)
        st = GestureState(cfg)
        # Enter single-finger mode
        st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160)), now=1.0)
        # Not pinched
        st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160), pinch_distance=50.0), now=1.05)
        # Pinched — edge trigger
        result = st.step(
            _hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160), pinch_distance=30.0),
            now=1.1,
        )
        kinds = [i.kind for i in result.intents]
        assert "click" in kinds

    def test_click_cooldown(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, single_cooldown=0.0, click_cooldown=1.0, pinch_click_distance=35.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.SINGLE_FINGER), now=1.0)
        st.step(_hand(Gesture.SINGLE_FINGER, pinch_distance=30.0), now=1.1)
        st.last_click_time = 1.1
        # Immediate second pinch — within cooldown
        result = st.step(_hand(Gesture.SINGLE_FINGER, pinch_distance=30.0), now=1.15)
        kinds = [i.kind for i in result.intents]
        assert "click" not in kinds

    def test_fist_exits_single_mouse(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, single_cooldown=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.SINGLE_FINGER), now=1.0)
        assert st.is_single_mouse_active
        result = st.step(_hand(Gesture.FIST), now=1.1)
        assert not st.is_single_mouse_active

    def test_fist_returns_standby(self) -> None:
        st = GestureState(_cfg(initial_mode=MODE_MOUSE))
        result = st.step(_hand(Gesture.FIST), now=1.0)
        assert st.mode == MODE_STANDBY


# ── mouse mode — drag / two-finger ──────────────────────────────────────────

class TestMouseDrag:
    def test_enter_drag(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, drag_cooldown=0.0)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.TWO_FINGER, palm_xy=(320, 160)), now=1.0)
        assert st.is_left_down
        kinds = [i.kind for i in result.intents]
        assert "hotkey" in kinds  # Ctrl+P
        assert "mouse_down" in kinds

    def test_drag_move(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, drag_cooldown=0.0, mouse_fps=20, screen_size=(1920, 1080))
        st = GestureState(cfg)
        st.step(_hand(Gesture.TWO_FINGER, palm_xy=(320, 160)), now=1.0)
        result = st.step(_hand(Gesture.TWO_FINGER, palm_xy=(340, 170)), now=1.1)
        move_intents = [i for i in result.intents if i.kind == "move"]
        assert len(move_intents) == 1

    def test_fist_exits_drag(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, drag_cooldown=0.0, fist_exit_cooldown=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.TWO_FINGER), now=1.0)
        assert st.is_left_down
        result = st.step(_hand(Gesture.FIST), now=1.1)
        assert not st.is_left_down
        kinds = [i.kind for i in result.intents]
        assert "mouse_up" in kinds
        assert "hotkey" in kinds

    def test_drag_overrides_single_mouse(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, single_cooldown=0.0, drag_cooldown=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.SINGLE_FINGER), now=1.0)
        assert st.is_single_mouse_active
        # Drag takes over
        st.step(_hand(Gesture.TWO_FINGER), now=1.1)
        assert st.is_left_down
        assert not st.is_single_mouse_active


# ── no-hand with held state ──────────────────────────────────────────────────

class TestNoHandRelease:
    def test_no_hand_releases_single_mouse_after_timeout(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, single_cooldown=0.0, hand_loss_timeout=2.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160)), now=1.0)
        assert st.is_single_mouse_active
        # Hand disappears, timeout not yet reached
        result = st.step(_hand(Gesture.NONE), now=2.5)
        assert st.is_single_mouse_active  # still within grace
        # Timeout exceeded
        result = st.step(_hand(Gesture.NONE), now=3.5)
        assert not st.is_single_mouse_active

    def test_no_hand_releases_drag_after_timeout(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, drag_cooldown=0.0, hand_loss_timeout=1.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.TWO_FINGER, palm_xy=(320, 160)), now=1.0)
        assert st.is_left_down
        st.step(_hand(Gesture.NONE), now=1.5)
        # Within timeout: is_left_down still true but no immediate release
        # (the hand-loss check is in _handle_no_hand, gated by timeout)
        result = st.step(_hand(Gesture.NONE), now=3.0)
        assert not st.is_left_down


# ── standby mode ────────────────────────────────────────────────────────────

class TestStandbyMode:
    def test_standby_no_intents(self) -> None:
        st = GestureState(_cfg(initial_mode=MODE_STANDBY))
        result = st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        assert result.intents == []
        assert "Standby" in result.note
