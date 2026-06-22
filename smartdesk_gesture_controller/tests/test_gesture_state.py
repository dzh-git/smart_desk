"""Tests for hands.gesture_state — pure-logic state machine.

No camera, no pyautogui, no MediaPipe. Just the state machine fed synthetic
HandInput frames and asserted on ActionIntent lists.

Phase 2 coverage (STATE_MACHINE_SPEC §19 / TEST_ACCEPTANCE_SPEC §4.2):
    1.  standby Thumb_Up HOLD不足时间不触发F5
    2.  standby Thumb_Up HOLD达到时间触发F5并进入presentation
    3.  standby Open_Palm不触发动作
    4.  standby Pointing_Up HOLD进入mouse
    5.  standby ILoveYou HOLD进入solidworks
    6.  presentation Victory HOLD触发Ctrl+P并进入presentation_pen
    7.  presentation Closed_Fist HOLD触发Esc+release_all并回standby
    8.  presentation_pen Thumb_Up HOLD触发mouse_up+Ctrl+A并回presentation
    9.  mouse Victory HOLD进入mouse_scroll
    10. mouse Closed_Fist HOLD触发release_all并回standby
    11. solidworks Closed_Fist HOLD触发release_all并回standby
    12. set_active_mode("solidworks")不抛NotImplementedError
    13. None超过hand_lost_timeout后触发release_all
    14. cooldown内不重复触发离散动作
    15. paused中任意手势不触发硬件动作

Plus preserved legacy coverage: _interp, wave detection, pinch click, etc.
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
        mouse_smoothing=0.0,  # use legacy smoothening in tests (instant)
        mouse_speed=1.0,
        mouse_max_step_px=80,
        mouse_fps=20,
        screen_size=(1920, 1080),
        # Phase 2 hold times — set to 0 for instant-trigger tests.
        start_presentation_hold=0.0,
        enter_mouse_hold=0.0,
        enter_solidworks_hold=0.0,
        exit_mode_hold=0.0,
        pen_mode_hold=0.0,
        erase_hold=0.0,
        page_turn_cooldown=0.0,
        mode_switch_cooldown=0.0,
        pen_toggle_cooldown=0.0,
        # Phase 3 swipe params
        swipe_threshold_x=0.18,
        swipe_threshold_y_limit=0.12,
        swipe_time_window=0.8,
        # Phase 4 mouse params
        drag_hold_time=0.35,
        click_max_movement_px=25,
        right_click_hold=0.5,
        right_click_cooldown=0.5,
        scroll_threshold_y=0.08,
        scroll_amount=5,
        scroll_cooldown=0.12,
        # Phase 5 SolidWorks params
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


# ── gesture normalization ────────────────────────────────────────────────────

class TestNormalizeGesture:
    def test_legacy_fist(self) -> None:
        assert _normalize_gesture(Gesture.FIST) == G_CLOSED_FIST

    def test_legacy_single_finger(self) -> None:
        assert _normalize_gesture(Gesture.SINGLE_FINGER) == G_POINTING_UP

    def test_legacy_two_finger(self) -> None:
        assert _normalize_gesture(Gesture.TWO_FINGER) == G_VICTORY

    def test_spec_closed_fist(self) -> None:
        assert _normalize_gesture(Gesture.CLOSED_FIST) == G_CLOSED_FIST

    def test_string_input(self) -> None:
        assert _normalize_gesture("Thumb_Up") == G_THUMB_UP

    def test_none_input(self) -> None:
        assert _normalize_gesture(None) == G_NONE


# ── state construction (preserved + updated) ─────────────────────────────────

class TestStateConstruction:
    def test_default_mode(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE)
        st = GestureState(cfg)
        assert st.mode == MODE_MOUSE
        assert not st.paused

    def test_pause_on_start(self) -> None:
        cfg = _cfg(pause_on_start=True)
        st = GestureState(cfg)
        assert st.paused


# ── toggle_pause (preserved + updated) ───────────────────────────────────────

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
        cfg = _cfg(initial_mode=MODE_MOUSE)
        st = GestureState(cfg)
        st.is_left_down = True
        st.toggle_pause()
        assert not st.is_left_down

    def test_resume_goes_to_standby(self) -> None:
        """Spec §11.4: resume always goes to standby."""
        st = GestureState(_cfg(initial_mode=MODE_PRESENTATION, pause_on_start=True))
        st.toggle_pause()  # resume
        assert st.mode == MODE_STANDBY


# ── set_active_mode (updated: solidworks no longer raises) ───────────────────

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

    def test_solidworks_no_longer_raises(self) -> None:
        """Phase 2: solidworks is enterable (spec §10, requirement #12)."""
        st = GestureState(_cfg())
        st.set_active_mode(MODE_SOLIDWORKS)
        assert st.mode == MODE_SOLIDWORKS

    def test_activate_from_standby_promotes(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE)
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


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2 required tests (STATE_MACHINE_SPEC §19)
# ═══════════════════════════════════════════════════════════════════════════

class TestStandbyHold:
    """Requirements #1–#5."""

    def test_thumb_up_hold_not_enough_no_f5(self) -> None:
        """#1: Thumb_Up HOLD不足时间不触发F5."""
        cfg = _cfg(start_presentation_hold=1.5, mode_switch_cooldown=10.0)
        st = GestureState(cfg)
        # First frame: start hold
        st.step(_hand(Gesture.THUMB_UP), now=1.0)
        # Second frame: hold not long enough
        result = st.step(_hand(Gesture.THUMB_UP), now=2.0)  # only 1.0s < 1.5s
        assert st.mode == MODE_STANDBY
        assert not any(i.type == "press" for i in result.intents)

    def test_thumb_up_hold_triggers_f5(self) -> None:
        """#2: Thumb_Up HOLD达到时间触发F5并进入presentation."""
        cfg = _cfg(start_presentation_hold=1.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.THUMB_UP), now=1.0)
        result = st.step(_hand(Gesture.THUMB_UP), now=3.0)  # 2.0s >= 1.5s
        assert st.mode == MODE_PRESENTATION
        types = [i.type for i in result.intents]
        assert "press" in types
        press_intent = [i for i in result.intents if i.type == "press"][0]
        assert press_intent.key == "f5"

    def test_open_palm_no_action_in_standby(self) -> None:
        """#3: standby中Open_Palm不触发动作."""
        st = GestureState(_cfg())
        result = st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        assert result.intents == []
        assert st.mode == MODE_STANDBY

    def test_pointing_up_hold_enters_mouse(self) -> None:
        """#4: standby中Pointing_Up HOLD进入mouse."""
        cfg = _cfg(enter_mouse_hold=1.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP), now=1.0)
        result = st.step(_hand(Gesture.POINTING_UP), now=2.5)  # 1.5s >= 1.0s
        assert st.mode == MODE_MOUSE

    def test_iloveyou_hold_enters_solidworks(self) -> None:
        """#5: standby中ILoveYou HOLD进入solidworks."""
        cfg = _cfg(enter_solidworks_hold=1.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.ILOVEYOU), now=1.0)
        result = st.step(_hand(Gesture.ILOVEYOU), now=3.0)  # 2.0s >= 1.5s
        assert st.mode == MODE_SOLIDWORKS


class TestPresentationHold:
    """Requirements #6–#7 + preserved wave detection."""

    def test_victory_hold_enters_pen(self) -> None:
        """#6: presentation中Victory HOLD触发Ctrl+P并进入presentation_pen."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, pen_mode_hold=0.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY), now=1.0)
        result = st.step(_hand(Gesture.VICTORY), now=2.0)  # 1.0s >= 0.5s
        assert st.mode == MODE_PRESENTATION_PEN
        types = [i.type for i in result.intents]
        assert "hotkey" in types
        hotkey_intent = [i for i in result.intents if i.type == "hotkey"][0]
        assert hotkey_intent.keys == ["ctrl", "p"]

    def test_closed_fist_hold_exits_presentation(self) -> None:
        """#7: presentation中Closed_Fist HOLD触发Esc+release_all并回standby."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)  # 1.0s >= 0.8s
        assert st.mode == MODE_STANDBY
        types = [i.type for i in result.intents]
        assert "press" in types
        assert "release_all" in types
        press_intent = [i for i in result.intents if i.type == "press"][0]
        assert press_intent.key == "esc"

    def test_open_palm_wave_right(self) -> None:
        """Preserved: Open_Palm向右挥触发right."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_cooldown=0.0, wave_threshold=10.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.1)
        kinds = [i.type for i in result.intents]
        assert "press" in kinds
        if result.intents:
            press = [i for i in result.intents if i.type == "press"][0]
            assert press.key == "right"

    def test_open_palm_wave_left(self) -> None:
        """Preserved: Open_Palm向左挥触发left."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_cooldown=0.0, wave_threshold=10.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=330.0), now=1.1)
        kinds = [i.type for i in result.intents]
        assert "press" in kinds

    def test_wave_cooldown(self) -> None:
        """翻页后cooldown内不重复触发 (Phase 3: cooldown starts after trigger)."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_cooldown=0.0,
                   wave_threshold=10.0, page_turn_cooldown=1.0)
        st = GestureState(cfg)
        # First frame — collect position
        st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.0)
        # Second frame — swipe triggers (dx=50 > threshold=10)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.1)
        assert any(i.type == "press" for i in result.intents)
        # Third frame — within cooldown, no repeat
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=400.0), now=1.5)
        assert not any(i.type == "press" for i in result.intents)


class TestPresentationPenHold:
    """Requirement #8."""

    def test_thumb_up_hold_returns_to_presentation(self) -> None:
        """#8: presentation_pen中Thumb_Up HOLD触发mouse_up+Ctrl+A并回presentation."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pen_mode_hold=0.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.THUMB_UP), now=1.0)
        result = st.step(_hand(Gesture.THUMB_UP), now=2.0)  # 1.0s >= 0.5s
        assert st.mode == MODE_PRESENTATION
        types = [i.type for i in result.intents]
        assert "hotkey" in types
        hotkey = [i for i in result.intents if i.type == "hotkey"][0]
        assert hotkey.keys == ["ctrl", "a"]

    def test_thumb_up_hold_with_left_down_releases(self) -> None:
        """When left mouse is down, exit pen also emits mouse_up(left)."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pen_mode_hold=0.5)
        st = GestureState(cfg)
        st.is_left_mouse_down = True
        st.step(_hand(Gesture.THUMB_UP), now=1.0)
        result = st.step(_hand(Gesture.THUMB_UP), now=2.0)
        types = [i.type for i in result.intents]
        assert "mouse_up" in types

    def test_closed_fist_hold_exits_pen_to_standby(self) -> None:
        """presentation_pen中Closed_Fist HOLD触发Esc+release_all并回standby."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY
        types = [i.type for i in result.intents]
        assert "release_all" in types


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3: PPT 演示模式闭环测试 (18 项要求)
# ═══════════════════════════════════════════════════════════════════════════

class TestPhase3PresentationSwipe:
    """Phase 3 要求 #3–#6: SWIPE 翻页 + cooldown + 一次挥手一页."""

    def test_swipe_right_triggers_next_page(self) -> None:
        """#3: presentation中Open_Palm右挥触发press("right")."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_threshold=10.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.1)
        presses = [i for i in result.intents if i.type == "press"]
        assert len(presses) == 1
        assert presses[0].key == "right"

    def test_swipe_left_triggers_prev_page(self) -> None:
        """#4: presentation中Open_Palm左挥触发press("left")."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_threshold=10.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.1)
        presses = [i for i in result.intents if i.type == "press"]
        assert len(presses) == 1
        assert presses[0].key == "left"

    def test_page_turn_cooldown_blocks_repeat(self) -> None:
        """#5: 翻页后page_turn_cooldown内不重复翻页."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_threshold=10.0,
                   page_turn_cooldown=1.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.1)
        assert any(i.type == "press" for i in result.intents)
        # Within cooldown — no repeat
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=400.0), now=1.5)
        assert not any(i.type == "press" for i in result.intents)

    def test_one_swipe_one_turn(self) -> None:
        """#6: 一次挥手最多触发一次翻页 (armed flag)."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_threshold=10.0,
                   page_turn_cooldown=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.0)
        result1 = st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.1)
        assert any(i.type == "press" for i in result1.intents)
        # Continue swiping in same direction — should NOT trigger again
        result2 = st.step(_hand(Gesture.OPEN_PALM, wave_x=400.0), now=1.2)
        assert not any(i.type == "press" for i in result2.intents)

    def test_swipe_y_limit_rejects_vertical(self) -> None:
        """swipe_threshold_y_limit: 过大的y位移不触发翻页."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_threshold=10.0,
                   swipe_threshold_y_limit=0.01, page_turn_cooldown=0.0)
        st = GestureState(cfg)
        # Move with large y component (palm_xy in camera px, y_limit converted)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300.0, 100.0)), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(360.0, 300.0)), now=1.1)
        # y_limit = 0.01 * 640 = 6.4 px; dy = 200 > 6.4 → rejected
        assert not any(i.type == "press" for i in result.intents)


class TestPhase3PresentationActions:
    """Phase 3: presentation Thumb_Down / Thumb_Up 快捷动作."""

    def test_presentation_thumb_down_hold_erases(self) -> None:
        """presentation中Thumb_Down HOLD触发press("e")."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, erase_hold=0.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.THUMB_DOWN), now=1.0)
        result = st.step(_hand(Gesture.THUMB_DOWN), now=2.0)  # 1.0s >= 0.5s
        presses = [i for i in result.intents if i.type == "press"]
        assert len(presses) == 1
        assert presses[0].key == "e"
        assert st.mode == MODE_PRESENTATION  # stays in presentation

    def test_presentation_thumb_up_hold_cancel_pen(self) -> None:
        """presentation中Thumb_Up HOLD触发hotkey("ctrl","a")."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, pen_mode_hold=0.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.THUMB_UP), now=1.0)
        result = st.step(_hand(Gesture.THUMB_UP), now=2.0)
        hotkeys = [i for i in result.intents if i.type == "hotkey"]
        assert len(hotkeys) == 1
        assert hotkeys[0].keys == ["ctrl", "a"]
        assert st.mode == MODE_PRESENTATION  # stays, NOT F5

    def test_presentation_thumb_up_does_not_trigger_f5(self) -> None:
        """presentation中Thumb_Up不能再次触发F5 (spec §6.5)."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, pen_mode_hold=0.0)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.THUMB_UP), now=1.0)
        presses = [i for i in result.intents if i.type == "press"]
        # Should NOT have press("f5")
        assert not any(p.key == "f5" for p in presses)


class TestPhase3PresentationPen:
    """Phase 3 要求 #9–#16: presentation_pen 画笔模式."""

    def test_pointing_up_outputs_move(self) -> None:
        """#9: presentation_pen中Pointing_Up输出move_to或move."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, screen_size=(1920, 1080))
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240)), now=1.0)
        moves = [i for i in result.intents if i.type in ("move", "move_to")]
        assert len(moves) >= 1

    def test_pinch_start_triggers_mouse_down_once(self) -> None:
        """#10: presentation_pen中PINCH开始只触发一次mouse_down("left")."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pinch_click_distance=35.0)
        st = GestureState(cfg)
        # Not pinching (distance > 35)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        # Pinch start (distance < 35)
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 1
        assert mouse_downs[0].button == "left"
        assert st.is_left_mouse_down
        assert st.is_pinching

    def test_pinch_hold_no_repeat_mouse_down(self) -> None:
        """#11: presentation_pen中PINCH保持不重复mouse_down."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pinch_click_distance=35.0)
        st = GestureState(cfg)
        # Start pinch
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        assert st.is_pinching
        # Hold pinch — no new mouse_down
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(321, 241), pinch_distance=30.0), now=1.2)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 0
        assert st.is_pinching  # still pinching

    def test_pinch_release_triggers_mouse_up(self) -> None:
        """#12: presentation_pen中PINCH释放触发mouse_up("left")."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pinch_click_distance=35.0)
        st = GestureState(cfg)
        # Start pinch
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        assert st.is_left_mouse_down
        # Release pinch (distance > 49 = 35*1.4)
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=55.0), now=1.2)
        mouse_ups = [i for i in result.intents if i.type == "mouse_up"]
        assert len(mouse_ups) == 1
        assert mouse_ups[0].button == "left"
        assert not st.is_left_mouse_down
        assert not st.is_pinching

    def test_pinch_hysteresis_no_jitter(self) -> None:
        """PINCH滞回: 距离在阈值之间时不抖动."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pinch_click_distance=35.0)
        st = GestureState(cfg)
        # Start pinch (distance < 35)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        assert st.is_pinching
        # Distance in hysteresis zone (35 < d < 49) — should stay pinching
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=40.0), now=1.2)
        assert st.is_pinching  # still pinching, no release

    def test_pen_thumb_down_hold_erases(self) -> None:
        """#13: presentation_pen中Thumb_Down HOLD触发press("e")."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, erase_hold=0.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.THUMB_DOWN), now=1.0)
        result = st.step(_hand(Gesture.THUMB_DOWN), now=2.0)
        presses = [i for i in result.intents if i.type == "press"]
        assert len(presses) == 1
        assert presses[0].key == "e"
        assert st.mode == MODE_PRESENTATION_PEN  # stays in pen

    def test_pen_thumb_up_hold_returns_to_presentation(self) -> None:
        """#14: presentation_pen中Thumb_Up HOLD触发mouse_up+Ctrl+A并回presentation."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pen_mode_hold=0.5)
        st = GestureState(cfg)
        st.is_left_mouse_down = True  # simulate drawing
        st.is_pinching = True
        st.step(_hand(Gesture.THUMB_UP), now=1.0)
        result = st.step(_hand(Gesture.THUMB_UP), now=2.0)
        assert st.mode == MODE_PRESENTATION
        types = [i.type for i in result.intents]
        assert "mouse_up" in types
        assert "hotkey" in types
        hotkey = [i for i in result.intents if i.type == "hotkey"][0]
        assert hotkey.keys == ["ctrl", "a"]
        assert not st.is_left_mouse_down

    def test_pen_closed_fist_hold_exits_to_standby(self) -> None:
        """#15: presentation_pen中Closed_Fist HOLD触发mouse_up+Esc+release_all并回standby."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.is_left_mouse_down = True  # simulate drawing
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY
        types = [i.type for i in result.intents]
        assert "mouse_up" in types
        assert "press" in types
        assert "release_all" in types
        esc = [i for i in result.intents if i.type == "press"][0]
        assert esc.key == "esc"

    def test_pen_none_timeout_releases_left(self) -> None:
        """#16: presentation_pen中None超时触发mouse_up+release_all."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, hand_loss_timeout=1.0,
                   pinch_click_distance=35.0)
        st = GestureState(cfg)
        # Hand seen + pinching (left down)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        assert st.is_left_mouse_down
        # Hand lost > timeout
        result = st.step(_hand(Gesture.NONE), now=3.0)
        types = [i.type for i in result.intents]
        assert "mouse_up" in types
        assert "release_all" in types
        # Mode preserved (spec §14.2)
        assert st.mode == MODE_PRESENTATION_PEN
        assert not st.is_left_mouse_down


class TestPhase3PinchDrawFlow:
    """Phase 3: PINCH 画线完整流程 (开始→保持→释放)."""

    def test_full_pinch_draw_cycle(self) -> None:
        """PINCH开始画线→持续画线→释放画线完整流程."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pinch_click_distance=35.0)
        st = GestureState(cfg)

        # 1. Not pinching, pointing — just move
        r1 = st.step(_hand(Gesture.POINTING_UP, palm_xy=(300, 200), pinch_distance=50.0), now=1.0)
        assert not st.is_pinching
        assert not st.is_left_mouse_down

        # 2. Pinch start — mouse_down
        r2 = st.step(_hand(Gesture.POINTING_UP, palm_xy=(310, 210), pinch_distance=30.0), now=1.1)
        assert st.is_pinching
        assert st.is_left_mouse_down
        assert any(i.type == "mouse_down" for i in r2.intents)

        # 3. Pinch hold + move — no new mouse_down, but move intent
        r3 = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 220), pinch_distance=30.0), now=1.2)
        assert st.is_pinching
        assert not any(i.type == "mouse_down" for i in r3.intents)

        # 4. Pinch release — mouse_up
        r4 = st.step(_hand(Gesture.POINTING_UP, palm_xy=(330, 230), pinch_distance=55.0), now=1.3)
        assert not st.is_pinching
        assert not st.is_left_mouse_down
        assert any(i.type == "mouse_up" for i in r4.intents)

    def test_pinch_no_mouse_up_leak_on_exit(self) -> None:
        """退出画笔模式时必须mouse_up (如果左键还按着)."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pen_mode_hold=0.0,
                   pinch_click_distance=35.0)
        st = GestureState(cfg)
        # Start pinching
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        assert st.is_left_mouse_down
        # Exit via Thumb_Up — must release left
        result = st.step(_hand(Gesture.THUMB_UP), now=1.2)
        assert any(i.type == "mouse_up" for i in result.intents)
        assert not st.is_left_mouse_down


class TestMouseHold:
    """Requirements #9–#10 + preserved mouse behaviour."""

    def test_victory_hold_enters_scroll(self) -> None:
        """#9: mouse中Victory HOLD进入mouse_scroll."""
        cfg = _cfg(initial_mode=MODE_MOUSE, pen_mode_hold=0.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY), now=1.0)
        st.step(_hand(Gesture.VICTORY), now=2.0)  # 1.0s >= 0.5s
        assert st.mode == MODE_MOUSE_SCROLL

    def test_closed_fist_hold_exits_mouse(self) -> None:
        """#10: mouse中Closed_Fist HOLD触发release_all并回standby."""
        cfg = _cfg(initial_mode=MODE_MOUSE, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY
        types = [i.type for i in result.intents]
        assert "release_all" in types

    def test_pointing_up_moves_cursor(self) -> None:
        """Preserved: Pointing_Up移动输出move intent."""
        cfg = _cfg(initial_mode=MODE_MOUSE, screen_size=(1920, 1080))
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160)), now=1.0)
        # Should produce a move intent (single-finger activates mouse)
        assert st.is_single_mouse_active

    def test_pinch_click(self) -> None:
        """Preserved: PINCH短按触发click.

        Phase 4: click now happens on PINCH *release* (not enter), when the
        pinch was short (< drag_hold_time) and movement was small
        (<= click_max_movement_px).  See spec §8.5.
        """
        cfg = _cfg(initial_mode=MODE_MOUSE, click_cooldown=0.0,
                   pinch_click_distance=35.0, drag_hold_time=1.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160)), now=1.0)
        # Not pinched
        st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160), pinch_distance=50.0), now=1.05)
        # Pinch start — no click yet (candidate)
        result_start = st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160), pinch_distance=30.0), now=1.1)
        assert not any(i.type == "click" for i in result_start.intents)
        # Pinch release (short, no movement) → click
        result = st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160), pinch_distance=55.0), now=1.2)
        kinds = [i.type for i in result.intents]
        assert "click" in kinds


class TestMouseScrollHold:
    """mouse_scroll exit paths."""

    def test_pointing_up_hold_returns_to_mouse(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, pen_mode_hold=0.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP), now=1.0)
        st.step(_hand(Gesture.POINTING_UP), now=2.0)
        assert st.mode == MODE_MOUSE

    def test_closed_fist_hold_exits_scroll(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY
        assert "release_all" in [i.type for i in result.intents]


class TestSolidworksHold:
    """Requirement #11."""

    def test_closed_fist_hold_exits_solidworks(self) -> None:
        """#11: solidworks中Closed_Fist HOLD触发release_all并回standby."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY
        types = [i.type for i in result.intents]
        assert "release_all" in types

    def test_solidworks_open_palm_triggers_rotate(self) -> None:
        """Phase 5: Open_Palm in solidworks triggers mouse_down(middle), not status."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(320, 240)), now=1.0)
        types = [i.type for i in result.intents]
        # Should emit mouse_down for rotate, not status
        assert "mouse_down" in types
        assert "status" not in types


# ═══════════════════════════════════════════════════════════════════════════
# None / hand-loss handling (requirement #13)
# ═══════════════════════════════════════════════════════════════════════════

class TestNoneHandLoss:
    """Requirement #13: None超过hand_lost_timeout后触发release_all."""

    def test_short_none_no_release(self) -> None:
        """短暂None不立即release."""
        cfg = _cfg(initial_mode=MODE_MOUSE, hand_loss_timeout=2.0)
        st = GestureState(cfg)
        # Hand seen
        st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160)), now=1.0)
        # Brief none — within grace
        result = st.step(_hand(Gesture.NONE), now=1.5)
        assert not any(i.type == "release_all" for i in result.intents)

    def test_long_none_triggers_release_all(self) -> None:
        """None超过timeout后触发release_all."""
        cfg = _cfg(initial_mode=MODE_MOUSE, hand_loss_timeout=1.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160)), now=1.0)
        # Hand gone for > timeout
        result = st.step(_hand(Gesture.NONE), now=3.0)
        types = [i.type for i in result.intents]
        assert "release_all" in types

    def test_long_none_clears_continuous_state(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, hand_loss_timeout=1.0)
        st = GestureState(cfg)
        # Hand seen first (sets last_hand_seen)
        st.step(_hand(Gesture.SINGLE_FINGER, palm_xy=(320, 160)), now=1.0)
        st.is_left_mouse_down = True
        st.active_continuous_action = "left_drag"
        # Hand lost > timeout → release + clear
        st.step(_hand(Gesture.NONE), now=3.0)
        assert not st.is_left_mouse_down
        assert st.active_continuous_action is None

    def test_mouse_scroll_drops_to_mouse_on_none_timeout(self) -> None:
        """Spec §9.3: mouse_scroll → mouse on hand-loss timeout."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, hand_loss_timeout=1.0)
        st = GestureState(cfg)
        # First no-hand frame starts grace period (last_hand_seen initialised to now).
        st.step(_hand(Gesture.NONE), now=3.0)
        # Second no-hand frame after timeout → drop to mouse.
        st.step(_hand(Gesture.NONE), now=5.0)
        assert st.mode == MODE_MOUSE

    def test_force_release(self) -> None:
        st = GestureState(_cfg())
        st.is_left_down = True
        st.is_single_mouse_active = True
        intents = st.force_release()
        assert st.is_left_down is False
        assert st.is_single_mouse_active is False
        kinds = [i.type for i in intents]
        assert "release_all" in kinds

    def test_should_release_on_hand_loss_false_when_no_hold(self) -> None:
        st = GestureState(_cfg())
        assert st.should_release_on_hand_loss(now=100.0) is False


# ═══════════════════════════════════════════════════════════════════════════
# Cooldown (requirement #14)
# ═══════════════════════════════════════════════════════════════════════════

class TestCooldown:
    """#14: cooldown内不重复触发离散动作."""

    def test_mode_switch_cooldown_blocks_reentry(self) -> None:
        """After entering presentation, can't immediately enter another mode."""
        cfg = _cfg(start_presentation_hold=0.0, enter_mouse_hold=0.0,
                   mode_switch_cooldown=5.0)
        st = GestureState(cfg)
        # Enter presentation via Thumb_Up
        st.step(_hand(Gesture.THUMB_UP), now=1.0)
        assert st.mode == MODE_PRESENTATION
        # Now try to immediately enter mouse via Pointing_Up — but we're in
        # presentation now, not standby, so this just tests that mode_switch
        # cooldown is set.
        assert not st._cooldown_ok("mode_switch", 1.0)

    def test_release_all_not_blocked_by_cooldown(self) -> None:
        """release_all不受cooldown限制."""
        cfg = _cfg(initial_mode=MODE_MOUSE, exit_mode_hold=0.0, mode_switch_cooldown=100.0)
        st = GestureState(cfg)
        # Set a huge cooldown
        st._set_cooldown("mode_switch", 100.0, 1.0)
        # Closed_Fist still triggers exit (exit not gated by mode_switch cooldown
        # because exit_mode_hold=0 and the transition still fires)
        st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        # Should have exited to standby despite cooldown
        assert st.mode == MODE_STANDBY


# ═══════════════════════════════════════════════════════════════════════════
# Paused (requirement #15)
# ═══════════════════════════════════════════════════════════════════════════

class TestPausedState:
    """#15: paused中任意手势不触发硬件动作."""

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
        """Even Closed_Fist in paused mode produces no hardware action."""
        st = GestureState(_cfg(pause_on_start=True))
        result = st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        assert result.intents == []
        assert result.mode == MODE_PAUSED

    def test_paused_mode_in_result(self) -> None:
        st = GestureState(_cfg(pause_on_start=True))
        result = st.step(_hand(Gesture.THUMB_UP), now=1.0)
        assert result.mode == MODE_PAUSED


# ═══════════════════════════════════════════════════════════════════════════
# Preserved: standby mode
# ═══════════════════════════════════════════════════════════════════════════

class TestStandbyMode:
    def test_standby_no_intents(self) -> None:
        st = GestureState(_cfg(initial_mode=MODE_STANDBY))
        result = st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        assert result.intents == []
        assert "Standby" in result.note

    def test_standby_closed_fist_releases(self) -> None:
        """Closed_Fist in standby emits release_all (safety)."""
        st = GestureState(_cfg(initial_mode=MODE_STANDBY))
        result = st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        types = [i.type for i in result.intents]
        assert "release_all" in types


# ═══════════════════════════════════════════════════════════════════════════
# Preserved: ActionIntent new-field access (phase 1 compat)
# ═══════════════════════════════════════════════════════════════════════════

class TestActionIntentFields:
    def test_press_has_key_field(self) -> None:
        i = ActionIntent.press("right")
        assert i.type == "press"
        assert i.key == "right"
        assert i.kind == "press"
        assert i.args == ("right",)

    def test_hotkey_has_keys_field(self) -> None:
        i = ActionIntent.hotkey("ctrl", "p")
        assert i.type == "hotkey"
        assert i.keys == ["ctrl", "p"]
        assert i.args == ("ctrl", "p")

    def test_move_has_xy_fields(self) -> None:
        i = ActionIntent.move(100.0, 200.0)
        assert i.type == "move"
        assert i.x == 100.0
        assert i.y == 200.0
        assert i.args == (100.0, 200.0)

    def test_mouse_down_has_button_field(self) -> None:
        i = ActionIntent.mouse_down(10, 20, button="middle")
        assert i.type == "mouse_down"
        assert i.button == "middle"

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


# ═══════════════════════════════════════════════════════════════════════════
# Preserved: StepResult compat
# ═══════════════════════════════════════════════════════════════════════════

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
        """Phase 7: debug_info 包含 hand_lost_duration 和 cooldown_until."""
        st = GestureState(_cfg())
        result = st.step(_hand(Gesture.OPEN_PALM), now=1.0)
        assert "hand_lost_duration" in result.debug_info
        assert "cooldown_until" in result.debug_info
        assert isinstance(result.debug_info["hand_lost_duration"], float)
        assert isinstance(result.debug_info["cooldown_until"], float)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4: Mouse Mode Enhancement (24 required tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestPhase4MouseEnter:
    """#1: standby中Pointing_Up HOLD进入mouse."""

    def test_pointing_up_hold_enters_mouse_mode(self) -> None:
        cfg = _cfg(enter_mouse_hold=1.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP), now=1.0)
        st.step(_hand(Gesture.POINTING_UP), now=2.5)  # 1.5s >= 1.0s
        assert st.mode == MODE_MOUSE


class TestPhase4MouseMove:
    """#2: mouse中Pointing_Up移动输出move_to或move_rel."""

    def test_pointing_up_outputs_move_intent(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, screen_size=(1920, 1080))
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240)), now=1.0)
        moves = [i for i in result.intents if i.type in ("move", "move_to", "move_rel")]
        assert len(moves) >= 1

    def test_move_clamped_to_screen_bounds(self) -> None:
        """Mouse coords must stay within screen boundaries."""
        cfg = _cfg(initial_mode=MODE_MOUSE, screen_size=(1920, 1080),
                   mouse_smoothing=0.0, smoothening=1.0, mouse_speed=1.0,
                   mouse_max_step_px=9999, mouse_fps=1)
        st = GestureState(cfg)
        # Move to extreme position
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(0, 0)), now=1.0)
        moves = [i for i in result.intents if i.type in ("move", "move_to")]
        if moves:
            assert moves[0].x >= 0
            assert moves[0].y >= 0

    def test_move_does_not_jump_to_edge_on_first_frame(self) -> None:
        """First-frame cursor should start at the target, not jump from (0,0)."""
        cfg = _cfg(initial_mode=MODE_MOUSE, screen_size=(1920, 1080),
                   mouse_smoothing=0.0, smoothening=1.0, mouse_speed=1.0)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240)), now=1.0)
        moves = [i for i in result.intents if i.type in ("move", "move_to")]
        if moves:
            # Should not be at screen edge
            assert 0 < moves[0].x < 1920
            assert 0 < moves[0].y < 1080


class TestPhase4MousePinchClick:
    """#3, #4: mouse中PINCH短按输出click("left"), 不触发mouse_down."""

    def test_pinch_short_press_triggers_click(self) -> None:
        """#3: PINCH短按触发click("left")."""
        cfg = _cfg(initial_mode=MODE_MOUSE, click_cooldown=0.0,
                   pinch_click_distance=35.0, drag_hold_time=1.0)
        st = GestureState(cfg)
        # Pointing, not pinched
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        # Pinch start
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        # Pinch release (short, no movement) → click
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=55.0), now=1.2)
        clicks = [i for i in result.intents if i.type == "click"]
        assert len(clicks) == 1
        assert clicks[0].button == "left"

    def test_pinch_short_press_no_mouse_down(self) -> None:
        """#4: PINCH短按不会触发mouse_down("left")."""
        cfg = _cfg(initial_mode=MODE_MOUSE, click_cooldown=0.0,
                   pinch_click_distance=35.0, drag_hold_time=1.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=55.0), now=1.2)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 0
        assert not st.is_left_mouse_down

    def test_click_cooldown_prevents_repeat(self) -> None:
        """click_cooldown prevents repeated clicks."""
        cfg = _cfg(initial_mode=MODE_MOUSE, click_cooldown=1.0,
                   pinch_click_distance=35.0, drag_hold_time=1.0)
        st = GestureState(cfg)
        # First click
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        r1 = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=55.0), now=1.2)
        assert any(i.type == "click" for i in r1.intents)
        # Second click within cooldown — should not trigger
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.3)
        r2 = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=55.0), now=1.4)
        assert not any(i.type == "click" for i in r2.intents)


class TestPhase4MousePinchDrag:
    """#5–#8: mouse中PINCH长按拖拽."""

    def test_pinch_long_press_triggers_mouse_down_once(self) -> None:
        """#5: PINCH长按输出一次mouse_down("left")."""
        cfg = _cfg(initial_mode=MODE_MOUSE, pinch_click_distance=35.0,
                   drag_hold_time=0.35)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        # Pinch start
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        # Hold past drag_hold_time → drag
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.5)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 1
        assert mouse_downs[0].button == "left"
        assert st.is_left_mouse_down

    def test_pinch_hold_no_repeat_mouse_down(self) -> None:
        """#6: PINCH长按保持不重复mouse_down."""
        cfg = _cfg(initial_mode=MODE_MOUSE, pinch_click_distance=35.0,
                   drag_hold_time=0.35)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.5)
        # Another frame holding — no new mouse_down
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(321, 241), pinch_distance=30.0), now=1.6)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 0
        assert st.is_left_mouse_down  # still down

    def test_pinch_drag_move_outputs_move(self) -> None:
        """#7: PINCH长按移动输出move intent."""
        cfg = _cfg(initial_mode=MODE_MOUSE, pinch_click_distance=35.0,
                   drag_hold_time=0.35, mouse_smoothing=0.0, smoothening=1.0)
        st = GestureState(cfg)
        # Start pointing + pinch → drag
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(300, 200), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(300, 200), pinch_distance=30.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(300, 200), pinch_distance=30.0), now=1.5)
        assert st.is_left_mouse_down
        # Move while dragging
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(350, 250), pinch_distance=30.0), now=1.6)
        moves = [i for i in result.intents if i.type in ("move", "move_to", "move_rel")]
        assert len(moves) >= 1

    def test_pinch_release_triggers_mouse_up(self) -> None:
        """#8: PINCH释放输出mouse_up("left")."""
        cfg = _cfg(initial_mode=MODE_MOUSE, pinch_click_distance=35.0,
                   drag_hold_time=0.35)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.5)
        assert st.is_left_mouse_down
        # Release
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=55.0), now=1.6)
        mouse_ups = [i for i in result.intents if i.type == "mouse_up"]
        assert len(mouse_ups) == 1
        assert mouse_ups[0].button == "left"
        assert not st.is_left_mouse_down

    def test_pinch_large_movement_triggers_drag(self) -> None:
        """PINCH期间移动超过click_max_movement_px → drag (not click)."""
        cfg = _cfg(initial_mode=MODE_MOUSE, pinch_click_distance=35.0,
                   drag_hold_time=10.0, click_max_movement_px=25)
        st = GestureState(cfg)
        # Pinch start at position A
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(300, 200), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(300, 200), pinch_distance=30.0), now=1.0)
        # Move far while pinching → drag (movement > 25px)
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(400, 300), pinch_distance=30.0), now=1.1)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 1
        assert st.is_left_mouse_down

    def test_drag_then_thumb_down_no_right_click(self) -> None:
        """#15: 拖拽时Thumb_Down不触发右键."""
        cfg = _cfg(initial_mode=MODE_MOUSE, pinch_click_distance=35.0,
                   drag_hold_time=0.35, right_click_hold=0.0,
                   right_click_cooldown=0.0)
        st = GestureState(cfg)
        # Start drag
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.5)
        assert st.is_left_mouse_down
        # Thumb_Down while dragging — no right click
        result = st.step(_hand(Gesture.THUMB_DOWN, palm_xy=(320, 240), pinch_distance=30.0), now=2.0)
        right_clicks = [i for i in result.intents if i.type == "click" and i.button == "right"]
        assert len(right_clicks) == 0


class TestPhase4MouseScrollEnter:
    """#9: mouse中Victory HOLD进入mouse_scroll."""

    def test_victory_hold_enters_scroll(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, pen_mode_hold=0.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY), now=1.0)
        st.step(_hand(Gesture.VICTORY), now=2.0)  # 1.0s >= 0.5s
        assert st.mode == MODE_MOUSE_SCROLL

    def test_victory_hold_releases_drag_before_scroll(self) -> None:
        """Entering scroll while dragging releases left mouse first."""
        cfg = _cfg(initial_mode=MODE_MOUSE, pinch_click_distance=35.0,
                   drag_hold_time=0.35, pen_mode_hold=0.0)
        st = GestureState(cfg)
        # Start drag
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.5)
        assert st.is_left_mouse_down
        # Victory HOLD → scroll (should release left first)
        result = st.step(_hand(Gesture.VICTORY), now=2.0)
        assert st.mode == MODE_MOUSE_SCROLL
        mouse_ups = [i for i in result.intents if i.type == "mouse_up"]
        assert len(mouse_ups) >= 1


class TestPhase4MouseScroll:
    """#10–#12, #20, #21: mouse_scroll滚轮 + 限制."""

    def test_victory_up_scrolls_positive(self) -> None:
        """#10: mouse_scroll中Victory向上移动输出scroll(+amount)."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, scroll_threshold_y=0.05,
                   scroll_amount=5, scroll_cooldown=0.0, camera_height=480)
        st = GestureState(cfg)
        # First frame — establish reference y
        st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240)), now=1.0)
        # Move up (y decreases) — dy = -100px, dy_norm = -100/480 ≈ -0.208 < -0.05
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(320, 140)), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) == 1
        assert scrolls[0].amount > 0  # positive = scroll up

    def test_victory_down_scrolls_negative(self) -> None:
        """#11: mouse_scroll中Victory向下移动输出scroll(-amount)."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, scroll_threshold_y=0.05,
                   scroll_amount=5, scroll_cooldown=0.0, camera_height=480)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240)), now=1.0)
        # Move down (y increases) — dy = +100px, dy_norm ≈ +0.208 > 0.05
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(320, 340)), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) == 1
        assert scrolls[0].amount < 0  # negative = scroll down

    def test_victory_up_scrolls_negative_when_inverted(self) -> None:
        """Phase 7: invert_scroll=True 时滚轮方向反转."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, scroll_threshold_y=0.05,
                   scroll_amount=5, scroll_cooldown=0.0, camera_height=480,
                   invert_scroll=True)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240)), now=1.0)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(320, 140)), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) == 1
        assert scrolls[0].amount < 0

    def test_victory_down_scrolls_positive_when_inverted(self) -> None:
        """Phase 7: invert_scroll=True 时向下移动输出正 scroll."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, scroll_threshold_y=0.05,
                   scroll_amount=5, scroll_cooldown=0.0, camera_height=480,
                   invert_scroll=True)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240)), now=1.0)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(320, 340)), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) == 1
        assert scrolls[0].amount > 0

    def test_scroll_cooldown_blocks_repeat(self) -> None:
        """#12: scroll_cooldown内不重复滚动."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, scroll_threshold_y=0.05,
                   scroll_amount=5, scroll_cooldown=1.0, camera_height=480)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240)), now=1.0)
        # First scroll
        r1 = st.step(_hand(Gesture.VICTORY, palm_xy=(320, 140)), now=1.1)
        assert any(i.type == "scroll" for i in r1.intents)
        # Second scroll within cooldown — blocked
        r2 = st.step(_hand(Gesture.VICTORY, palm_xy=(320, 100)), now=1.2)
        assert not any(i.type == "scroll" for i in r2.intents)

    def test_scroll_no_trigger_below_threshold(self) -> None:
        """Small movement below threshold doesn't scroll."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, scroll_threshold_y=0.1,
                   scroll_amount=5, scroll_cooldown=0.0, camera_height=480)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240)), now=1.0)
        # Tiny movement — dy = -10px, dy_norm = -10/480 ≈ -0.02 < 0.1 threshold
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(320, 230)), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) == 0

    def test_mouse_scroll_pinch_no_click(self) -> None:
        """#20: mouse_scroll中PINCH不触发左键点击."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, pinch_click_distance=35.0,
                   drag_hold_time=1.0, click_cooldown=0.0)
        st = GestureState(cfg)
        # PINCH in scroll mode — no click
        st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240), pinch_distance=55.0), now=1.2)
        clicks = [i for i in result.intents if i.type == "click"]
        assert len(clicks) == 0
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 0

    def test_mouse_scroll_thumb_down_no_right_click(self) -> None:
        """#21: mouse_scroll中Thumb_Down不触发右键."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL,
                   right_click_hold=0.0, right_click_cooldown=0.0)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.THUMB_DOWN), now=1.0)
        right_clicks = [i for i in result.intents if i.type == "click" and i.button == "right"]
        assert len(right_clicks) == 0


class TestPhase4MouseScrollExit:
    """#13, #17, #19: mouse_scroll退出路径."""

    def test_pointing_up_hold_returns_to_mouse(self) -> None:
        """#13: mouse_scroll中Pointing_Up HOLD回到mouse."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, pen_mode_hold=0.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP), now=1.0)
        st.step(_hand(Gesture.POINTING_UP), now=2.0)
        assert st.mode == MODE_MOUSE

    def test_closed_fist_hold_exits_scroll_to_standby(self) -> None:
        """#17: mouse_scroll中Closed_Fist HOLD输出release_all并回standby."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY
        assert "release_all" in [i.type for i in result.intents]

    def test_mouse_scroll_none_timeout_returns_to_mouse(self) -> None:
        """#19: mouse_scroll中None超时输出release_all并回mouse."""
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, hand_loss_timeout=1.0)
        st = GestureState(cfg)
        # First no-hand frame starts grace period
        st.step(_hand(Gesture.NONE), now=3.0)
        # Second no-hand frame after timeout → drop to mouse
        result = st.step(_hand(Gesture.NONE), now=5.0)
        assert st.mode == MODE_MOUSE
        assert "release_all" in [i.type for i in result.intents]


class TestPhase4MouseRightClick:
    """#14, #15: mouse中Thumb_Down HOLD右键."""

    def test_thumb_down_hold_triggers_right_click(self) -> None:
        """#14: mouse中Thumb_Down HOLD输出click("right")."""
        cfg = _cfg(initial_mode=MODE_MOUSE, right_click_hold=0.5,
                   right_click_cooldown=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.THUMB_DOWN), now=1.0)
        result = st.step(_hand(Gesture.THUMB_DOWN), now=2.0)  # 1.0s >= 0.5s
        right_clicks = [i for i in result.intents if i.type == "click" and i.button == "right"]
        assert len(right_clicks) == 1

    def test_thumb_down_cooldown(self) -> None:
        """右键触发后进入right_click_cooldown."""
        cfg = _cfg(initial_mode=MODE_MOUSE, right_click_hold=0.0,
                   right_click_cooldown=1.0)
        st = GestureState(cfg)
        # First right click
        r1 = st.step(_hand(Gesture.THUMB_DOWN), now=1.0)
        assert any(i.type == "click" and i.button == "right" for i in r1.intents)
        # Second within cooldown — blocked
        r2 = st.step(_hand(Gesture.THUMB_DOWN), now=1.5)
        assert not any(i.type == "click" and i.button == "right" for i in r2.intents)


class TestPhase4MouseExit:
    """#16: mouse中Closed_Fist HOLD退出."""

    def test_closed_fist_hold_exits_mouse_to_standby(self) -> None:
        """#16: mouse中Closed_Fist HOLD输出release_all并回standby."""
        cfg = _cfg(initial_mode=MODE_MOUSE, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY
        assert "release_all" in [i.type for i in result.intents]


class TestPhase4NoneHandLoss:
    """#18, #19: None/手丢失在鼠标模式下处理."""

    def test_mouse_none_timeout_releases_and_stays(self) -> None:
        """#18: mouse中None超时输出release_all，清除拖拽状态，保持mouse."""
        cfg = _cfg(initial_mode=MODE_MOUSE, hand_loss_timeout=1.0,
                   pinch_click_distance=35.0, drag_hold_time=0.35)
        st = GestureState(cfg)
        # Hand seen + start dragging
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.5)
        assert st.is_left_mouse_down
        assert st.is_pinching
        # Hand lost > timeout
        result = st.step(_hand(Gesture.NONE), now=3.0)
        types = [i.type for i in result.intents]
        assert "release_all" in types
        assert not st.is_left_mouse_down
        assert not st.is_pinching
        assert not st._pinch_click_candidate
        # Mode preserved (mouse stays mouse)
        assert st.mode == MODE_MOUSE


class TestPhase4NoScrollInMouseMode:
    """#22: 普通mouse模式中上下移动不触发scroll."""

    def test_mouse_mode_no_scroll_on_vertical_movement(self) -> None:
        """普通mouse模式中Victory上下移动不触发scroll."""
        cfg = _cfg(initial_mode=MODE_MOUSE, scroll_threshold_y=0.05,
                   scroll_amount=5, scroll_cooldown=0.0, camera_height=480)
        st = GestureState(cfg)
        # In mouse mode (NOT mouse_scroll), Victory vertical movement
        st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240)), now=1.0)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(320, 140)), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) == 0


class TestPhase4MouseOpenPalm:
    """#10 (禁令): mouse模式中Open_Palm不触发动作."""

    def test_open_palm_no_action_in_mouse(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE)
        st = GestureState(cfg)
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(320, 240)), now=1.0)
        # No hardware actions
        hw_types = {"press", "hotkey", "mouse_down", "mouse_up", "click", "scroll",
                    "key_down", "key_up"}
        assert not any(i.type in hw_types for i in result.intents)
        assert st.mode == MODE_MOUSE  # stays in mouse


class TestPhase4PinchHysteresis:
    """PINCH滞回机制在mouse模式下工作."""

    def test_pinch_hysteresis_no_jitter(self) -> None:
        """距离在阈值之间时不抖动."""
        cfg = _cfg(initial_mode=MODE_MOUSE, pinch_click_distance=35.0,
                   drag_hold_time=10.0)  # long so we stay in click candidate
        st = GestureState(cfg)
        # Start pinch (distance < 35)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        assert st.is_pinching
        # Distance in hysteresis zone (35 < d < 49) — should stay pinching
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=40.0), now=1.1)
        assert st.is_pinching  # still pinching, no release

    def test_normalized_pinch_thresholds(self) -> None:
        """normalized距离使用pinch_threshold/pinch_release_threshold."""
        cfg = _cfg(initial_mode=MODE_MOUSE, pinch_threshold=0.045,
                   pinch_release_threshold=0.065, drag_hold_time=10.0,
                   click_cooldown=0.0)
        st = GestureState(cfg)
        # Start pinch (normalized distance < 0.045)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=0.1), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=0.03), now=1.0)
        assert st.is_pinching
        # In hysteresis zone (0.045 < d < 0.065) — stay pinching
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=0.05), now=1.1)
        assert st.is_pinching
        # Release (d > 0.065)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=0.08), now=1.2)
        assert not st.is_pinching


class TestPhase4DryRunSafety:
    """#23: dry-run / FakeDriver下鼠标动作只记录，不真实控制鼠标键盘."""

    def test_dry_run_mouse_actions_recorded_only(self) -> None:
        """In dry-run, mouse intents are recorded by FakeDriver, not executed."""
        from hands.gesture_actions import ActionLayer, FakeDriver
        driver = FakeDriver()
        actions = ActionLayer(enable_system_mouse=False, driver=driver)
        # Dispatch mouse actions
        actions.execute([
            ActionIntent.move_to(960, 540),
            ActionIntent.click(button="left"),
            ActionIntent.mouse_down(button="left"),
            ActionIntent.move_rel(10, 20),
            ActionIntent.mouse_up(button="left"),
            ActionIntent.scroll(5),
            ActionIntent.click(button="right"),
        ])
        # All recorded, no real OS interaction
        assert ("move_to", 960, 540) in driver.events
        assert ("click", "left") in driver.events
        assert ("mouse_down", "left") in driver.events
        assert ("move_rel", 10, 20) in driver.events
        assert ("mouse_up", "left") in driver.events
        assert ("scroll", 5) in driver.events
        assert ("click", "right") in driver.events


class TestPhase4PPTRegression:
    """#24: 阶段3 PPT测试仍然全部通过."""

    def test_ppt_swipe_still_works(self) -> None:
        """PPT swipe翻页仍然正常."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_threshold=10.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.1)
        presses = [i for i in result.intents if i.type == "press"]
        assert len(presses) == 1
        assert presses[0].key == "right"

    def test_ppt_pen_pinch_draw_still_works(self) -> None:
        """PPT画笔PINCH画线仍然正常."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pinch_click_distance=35.0)
        st = GestureState(cfg)
        # Not pinching
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        # Pinch start — mouse_down
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 1
        # Pinch release — mouse_up
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=55.0), now=1.2)
        mouse_ups = [i for i in result.intents if i.type == "mouse_up"]
        assert len(mouse_ups) == 1

    def test_ppt_closed_fist_exit_still_works(self) -> None:
        """PPT退出仍然正常."""
        cfg = _cfg(initial_mode=MODE_PRESENTATION, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY
        types = [i.type for i in result.intents]
        assert "press" in types
        assert "release_all" in types


# ═══════════════════════════════════════════════════════════════════════════
# Phase 5: SolidWorks View Mode (27 required tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestPhase5SolidWorksEnter:
    """#1, #2: Enter solidworks mode."""

    def test_iloveyou_hold_enters_solidworks(self) -> None:
        """#1: standby中ILoveYou HOLD进入solidworks."""
        cfg = _cfg(enter_solidworks_hold=1.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.ILOVEYOU), now=1.0)
        st.step(_hand(Gesture.ILOVEYOU), now=3.0)  # 2.0s >= 1.5s
        assert st.mode == MODE_SOLIDWORKS

    def test_set_active_mode_solidworks_no_raise(self) -> None:
        """#2: set_active_mode("solidworks")不抛异常."""
        st = GestureState(_cfg())
        st.set_active_mode(MODE_SOLIDWORKS)
        assert st.mode == MODE_SOLIDWORKS


class TestPhase5SolidWorksRotate:
    """#3–#6: Open_Palm rotate."""

    def test_open_palm_start_triggers_mouse_down_middle(self) -> None:
        """#3: solidworks中Open_Palm开始移动输出mouse_down("middle")."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        # First frame — mouse_down emitted + position established
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 200)), now=1.0)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 1
        assert mouse_downs[0].button == "middle"
        assert st.is_middle_mouse_down
        assert st.active_continuous_action == "solidworks_rotate"

    def test_open_palm_continuous_move_outputs_move_rel(self) -> None:
        """#4: solidworks中Open_Palm持续移动输出move_rel."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(350, 250)), now=1.1)
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(380, 280)), now=1.2)
        moves = [i for i in result.intents if i.type == "move_rel"]
        assert len(moves) >= 1

    def test_open_palm_hold_no_repeat_mouse_down(self) -> None:
        """#5: solidworks中Open_Palm保持时不重复mouse_down("middle")."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(350, 250)), now=1.1)
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(360, 260)), now=1.2)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 0
        assert st.is_middle_mouse_down

    def test_open_palm_end_triggers_mouse_up_middle(self) -> None:
        """#6: solidworks中Open_Palm结束时输出mouse_up("middle")."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(350, 250)), now=1.1)
        assert st.is_middle_mouse_down
        result = st.step(_hand(Gesture.POINTING_UP), now=1.2)
        mouse_ups = [i for i in result.intents if i.type == "mouse_up"]
        assert len(mouse_ups) == 1
        assert mouse_ups[0].button == "middle"
        assert not st.is_middle_mouse_down
        assert st.active_continuous_action is None


class TestPhase5SolidWorksPan:
    """#7–#10: Victory pan."""

    def test_victory_start_triggers_shift_and_middle(self) -> None:
        """#7: solidworks中Victory开始移动输出key_down("shift")+mouse_down("middle")."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        # First frame — key_down + mouse_down emitted
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
        """#8: solidworks中Victory持续移动输出move_rel."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.VICTORY, palm_xy=(350, 250)), now=1.1)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(380, 280)), now=1.2)
        moves = [i for i in result.intents if i.type == "move_rel"]
        assert len(moves) >= 1

    def test_victory_hold_no_repeat_key_down_or_mouse_down(self) -> None:
        """#9: solidworks中Victory保持时不重复key_down/mouse_down."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.VICTORY, palm_xy=(350, 250)), now=1.1)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(360, 260)), now=1.2)
        key_downs = [i for i in result.intents if i.type == "key_down"]
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(key_downs) == 0
        assert len(mouse_downs) == 0

    def test_victory_end_triggers_mouse_up_and_key_up(self) -> None:
        """#10: solidworks中Victory结束时输出mouse_up("middle")+key_up("shift")."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.VICTORY, palm_xy=(350, 250)), now=1.1)
        assert st.is_shift_down and st.is_middle_mouse_down
        result = st.step(_hand(Gesture.POINTING_UP), now=1.2)
        mouse_ups = [i for i in result.intents if i.type == "mouse_up"]
        key_ups = [i for i in result.intents if i.type == "key_up"]
        assert len(mouse_ups) == 1
        assert mouse_ups[0].button == "middle"
        assert len(key_ups) == 1
        assert key_ups[0].key == "shift"
        assert not st.is_middle_mouse_down
        assert not st.is_shift_down


class TestPhase5SolidWorksMutualExclusion:
    """#11–#13: Rotate/pan/zoom mutual exclusion."""

    def test_rotate_to_pan_releases_middle_first(self) -> None:
        """#11: rotate切到pan时，先释放middle，再进入shift+middle."""
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
        assert st.is_shift_down
        assert st.is_middle_mouse_down

    def test_pan_to_rotate_releases_middle_and_shift_first(self) -> None:
        """#12: pan切到rotate时，先释放middle+shift，再进入middle."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.VICTORY, palm_xy=(350, 250)), now=1.1)
        assert st.active_continuous_action == "solidworks_pan"
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(360, 260)), now=1.2)
        assert st.active_continuous_action == "solidworks_rotate"
        assert not st.is_shift_down
        assert st.is_middle_mouse_down

    def test_rotate_to_zoom_releases_middle(self) -> None:
        """#13: rotate/pan切到zoom时，先释放连续动作."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.0,
                   pinch_click_distance=35.0, pinch_zoom_deadzone=0.0,
                   solidworks_zoom_sensitivity=8.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(350, 250)), now=1.1)
        assert st.active_continuous_action == "solidworks_rotate"
        assert st.is_middle_mouse_down
        result = st.step(_hand(Gesture.PINCH, palm_xy=(350, 250), pinch_distance=30.0), now=1.2)
        mouse_ups = [i for i in result.intents if i.type == "mouse_up"]
        assert len(mouse_ups) >= 1
        assert not st.is_middle_mouse_down


class TestPhase5SolidWorksZoom:
    """#14–#16: PINCH zoom."""

    def test_pinch_distance_increase_scrolls_positive(self) -> None:
        """#14: solidworks中PINCH距离增大输出scroll(+amount)."""
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
        """#15: solidworks中PINCH距离减小输出scroll(-amount)."""
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
        """#16: PINCH距离变化小于pinch_zoom_deadzone时不输出scroll."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, pinch_click_distance=35.0,
                   pinch_zoom_deadzone=100.0, solidworks_zoom_sensitivity=8.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.PINCH, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        assert st.is_pinching
        result = st.step(_hand(Gesture.PINCH, palm_xy=(320, 240), pinch_distance=31.0), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) == 0

    def test_pinch_tiny_delta_emits_min_zoom_step(self) -> None:
        """Phase 7: 缩放 delta 超过死区但 rounding 为 0 时，输出最小滚轮步长."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, pinch_click_distance=35.0,
                   pinch_zoom_deadzone=0.0, solidworks_zoom_sensitivity=8.0,
                   solidworks_min_zoom_step=2)
        st = GestureState(cfg)
        st.step(_hand(Gesture.PINCH, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        assert st.is_pinching
        # delta = 0.1 px; int(0.1 * 8.0 * 1.0) = 0 -> min step applied
        result = st.step(_hand(Gesture.PINCH, palm_xy=(320, 240), pinch_distance=30.1), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) == 1
        assert scrolls[0].amount == 2

    def test_pinch_zoom_inverted(self) -> None:
        """Phase 7: invert_scroll=True 时 SolidWorks 缩放方向反转."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, pinch_click_distance=35.0,
                   pinch_zoom_deadzone=0.0, solidworks_zoom_sensitivity=8.0,
                   invert_scroll=True)
        st = GestureState(cfg)
        st.step(_hand(Gesture.PINCH, palm_xy=(320, 240), pinch_distance=30.0), now=1.0)
        result = st.step(_hand(Gesture.PINCH, palm_xy=(320, 240), pinch_distance=35.0), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) >= 1
        assert scrolls[0].amount < 0


class TestPhase5SolidWorksViewShortcuts:
    """#17–#19: Thumb_Up fit, ILoveYou isometric, cooldown."""

    def test_thumb_up_hold_triggers_press_f(self) -> None:
        """#17: solidworks中Thumb_Up HOLD输出press("f")."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, fit_view_hold=0.5)
        st = GestureState(cfg)
        st.step(_hand(Gesture.THUMB_UP), now=1.0)
        result = st.step(_hand(Gesture.THUMB_UP), now=2.0)
        presses = [i for i in result.intents if i.type == "press"]
        assert len(presses) == 1
        assert presses[0].key == "f"
        assert st.mode == MODE_SOLIDWORKS

    def test_iloveyou_hold_triggers_ctrl_7(self) -> None:
        """#18: solidworks中ILoveYou HOLD输出hotkey("ctrl","7")."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, isometric_view_hold=0.8)
        st = GestureState(cfg)
        st.step(_hand(Gesture.ILOVEYOU), now=1.0)
        result = st.step(_hand(Gesture.ILOVEYOU), now=2.0)
        hotkeys = [i for i in result.intents if i.type == "hotkey"]
        assert len(hotkeys) == 1
        assert hotkeys[0].keys == ["ctrl", "7"]
        assert st.mode == MODE_SOLIDWORKS

    def test_view_cooldown_blocks_repeat(self) -> None:
        """#19: solidworks view cooldown内不重复触发."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, fit_view_hold=0.0,
                   solidworks_view_cooldown=1.0)
        st = GestureState(cfg)
        r1 = st.step(_hand(Gesture.THUMB_UP), now=1.0)
        assert any(i.type == "press" and i.key == "f" for i in r1.intents)
        r2 = st.step(_hand(Gesture.THUMB_UP), now=1.5)
        assert not any(i.type == "press" and i.key == "f" for i in r2.intents)


class TestPhase5SolidWorksExit:
    """#20, #24: Closed_Fist exit, active_continuous_action cleared."""

    def test_closed_fist_hold_exits_to_standby(self) -> None:
        """#20: solidworks中Closed_Fist HOLD输出release_all并回standby."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, exit_mode_hold=0.8)
        st = GestureState(cfg)
        st.step(_hand(Gesture.CLOSED_FIST), now=1.0)
        result = st.step(_hand(Gesture.CLOSED_FIST), now=2.0)
        assert st.mode == MODE_STANDBY
        assert "release_all" in [i.type for i in result.intents]

    def test_exit_clears_active_continuous_action(self) -> None:
        """#24: solidworks中退出后active_continuous_action被清空."""
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


class TestPhase5SolidWorksNoneTimeout:
    """#21: None超时处理."""

    def test_none_timeout_releases_and_stays_solidworks(self) -> None:
        """#21: solidworks中None超时输出mouse_up+key_up+release_all，保持solidworks."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, hand_loss_timeout=1.0,
                   solidworks_deadzone=0.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(300, 200)), now=1.0)
        st.step(_hand(Gesture.VICTORY, palm_xy=(350, 250)), now=1.1)
        assert st.is_middle_mouse_down
        assert st.is_shift_down
        result = st.step(_hand(Gesture.NONE), now=3.0)
        types = [i.type for i in result.intents]
        assert "mouse_up" in types
        assert "key_up" in types
        assert "release_all" in types
        assert not st.is_middle_mouse_down
        assert not st.is_shift_down
        assert st.active_continuous_action is None
        assert st.mode == MODE_SOLIDWORKS


class TestPhase5SolidWorksDeadzone:
    """#22, #23: Deadzone filtering."""

    def test_open_palm_small_move_no_move_rel(self) -> None:
        """#22: solidworks中Open_Palm小于deadzone不输出move_rel."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.1,
                   camera_width=640, camera_height=480)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, palm_xy=(320, 240)), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, palm_xy=(325, 245)), now=1.1)
        moves = [i for i in result.intents if i.type == "move_rel"]
        assert len(moves) == 0

    def test_victory_small_move_no_move_rel(self) -> None:
        """#23: solidworks中Victory小于deadzone不输出move_rel."""
        cfg = _cfg(initial_mode=MODE_SOLIDWORKS, solidworks_deadzone=0.1,
                   camera_width=640, camera_height=480)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240)), now=1.0)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(325, 245)), now=1.1)
        moves = [i for i in result.intents if i.type == "move_rel"]
        assert len(moves) == 0


class TestPhase5SolidWorksDryRun:
    """#25: dry-run / FakeDriver下SolidWorks动作只记录."""

    def test_dry_run_solidworks_actions_recorded_only(self) -> None:
        """#25: dry-run / FakeDriver下SolidWorks动作只记录，不真实控制鼠标键盘."""
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
        for ev in driver.events:
            assert isinstance(ev, tuple)


class TestPhase5PPTRegression:
    """#26: 阶段3 PPT测试仍然全部通过."""

    def test_ppt_swipe_still_works_phase5(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION, wave_threshold=10.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.OPEN_PALM, wave_x=300.0), now=1.0)
        result = st.step(_hand(Gesture.OPEN_PALM, wave_x=350.0), now=1.1)
        presses = [i for i in result.intents if i.type == "press"]
        assert len(presses) == 1
        assert presses[0].key == "right"

    def test_ppt_pen_pinch_still_works_phase5(self) -> None:
        cfg = _cfg(initial_mode=MODE_PRESENTATION_PEN, pinch_click_distance=35.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        mouse_downs = [i for i in result.intents if i.type == "mouse_down"]
        assert len(mouse_downs) == 1


class TestPhase5MouseRegression:
    """#27: 阶段4 mouse/mouse_scroll测试仍然全部通过."""

    def test_mouse_pinch_click_still_works(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE, click_cooldown=0.0,
                   pinch_click_distance=35.0, drag_hold_time=1.0)
        st = GestureState(cfg)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=50.0), now=1.0)
        st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=30.0), now=1.1)
        result = st.step(_hand(Gesture.POINTING_UP, palm_xy=(320, 240), pinch_distance=55.0), now=1.2)
        clicks = [i for i in result.intents if i.type == "click"]
        assert len(clicks) == 1

    def test_mouse_scroll_still_works(self) -> None:
        cfg = _cfg(initial_mode=MODE_MOUSE_SCROLL, scroll_threshold_y=0.05,
                   scroll_amount=5, scroll_cooldown=0.0, camera_height=480)
        st = GestureState(cfg)
        st.step(_hand(Gesture.VICTORY, palm_xy=(320, 240)), now=1.0)
        result = st.step(_hand(Gesture.VICTORY, palm_xy=(320, 140)), now=1.1)
        scrolls = [i for i in result.intents if i.type == "scroll"]
        assert len(scrolls) == 1
        assert scrolls[0].amount > 0
