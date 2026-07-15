"""Tests for hands.gesture_controller intent dispatch.

These tests keep the controller at the boundary between pure state intents
and the ActionLayer. They use FakeDriver so no OS mouse/keyboard events run.

Phase 3 coverage:
    * PPT intent dispatch: press, hotkey, mouse_down, mouse_up, release_all
    * move_to / move intent dispatch
    * FakeDriver records all PPT actions without touching the real OS
    * _dispatch_intents via execute() handles list of intents in order

Phase 6 coverage:
    * Model file check (check_model_files)
    * Dry-run safety (FakeDriver never touches OS)
    * Controller dispatches via ActionLayer.execute()
    * Config preservation (start_paused / enable_hotkeys / dry_run)
"""
from __future__ import annotations

import os
import tempfile

import pytest

from hands.display_agent_client import DisplayAgentResult
from hands.gesture_actions import ActionLayer, FakeDriver
from hands.gesture_config import default_config
from hands.gesture_controller import GestureController
from hands.gesture_state import ActionIntent


def _controller_with_fake_driver() -> tuple[GestureController, FakeDriver]:
    config = default_config()
    config.enable_system_mouse = False
    config.show_debug_window = False
    config.status_server_enabled = False

    driver = FakeDriver()
    actions = ActionLayer(enable_system_mouse=False, driver=driver)
    controller = GestureController(config=config, actions=actions)
    return controller, driver


# ── preserved: hotkey dispatch ──────────────────────────────────────────────

def test_hotkey_intent_dispatches_ctrl_p_as_two_keys() -> None:
    controller, driver = _controller_with_fake_driver()

    controller._apply_intent(ActionIntent.hotkey("ctrl", "p"))

    assert driver.names() == ["hotkey"]
    assert driver.calls[0].args == ("ctrl", "p")


def test_hotkey_intent_dispatches_multi_key_combo_without_splitting() -> None:
    controller, driver = _controller_with_fake_driver()

    controller._apply_intent(ActionIntent.hotkey("ctrl", "alt", "q"))

    assert driver.names() == ["hotkey"]
    assert driver.calls[0].args == ("ctrl", "alt", "q")


# ── Phase 3: PPT intent dispatch via _dispatch_intents ──────────────────────

def test_dispatch_press_f5_recorded() -> None:
    """PPT 启动: press("f5") 正确分发到 FakeDriver."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.press("f5")])
    assert ("press", "f5") in driver.events


def test_dispatch_press_right_left_recorded() -> None:
    """PPT 翻页: press("right") / press("left") 正确分发."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.press("right")])
    controller._dispatch_intents([ActionIntent.press("left")])
    assert ("press", "right") in driver.events
    assert ("press", "left") in driver.events


def test_dispatch_hotkey_ctrl_p_recorded() -> None:
    """PPT 进入画笔: hotkey(["ctrl","p"]) 正确分发."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.hotkey("ctrl", "p")])
    assert ("hotkey", ["ctrl", "p"]) in driver.events


def test_dispatch_hotkey_ctrl_a_recorded() -> None:
    """PPT 取消画笔: hotkey(["ctrl","a"]) 正确分发."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.hotkey("ctrl", "a")])
    assert ("hotkey", ["ctrl", "a"]) in driver.events


def test_dispatch_press_esc_and_release_all_recorded() -> None:
    """PPT 退出演示: press("esc") + release_all 正确分发."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([
        ActionIntent.press("esc"),
        ActionIntent.release_all(),
    ])
    assert ("press", "esc") in driver.events
    # release_all produces 3 mouse_up + 3 key_up events
    mouse_ups = [e for e in driver.events if e[0] == "mouse_up"]
    key_ups = [e for e in driver.events if e[0] == "key_up"]
    assert len(mouse_ups) == 3
    assert len(key_ups) == 3


def test_dispatch_mouse_down_up_recorded() -> None:
    """PPT 画笔画线: mouse_down("left") + mouse_up("left") 正确分发."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([
        ActionIntent.mouse_down(button="left"),
        ActionIntent.mouse_up(button="left"),
    ])
    assert ("mouse_down", "left") in driver.events
    assert ("mouse_up", "left") in driver.events


def test_dispatch_move_to_recorded() -> None:
    """PPT 画笔移动: move intent 正确分发为 move_to."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.move(960.0, 540.0)])
    assert ("move_to", 960.0, 540.0) in driver.events


def test_dispatch_full_pen_exit_sequence() -> None:
    """完整画笔退出序列: mouse_up + hotkey(ctrl,a) 按顺序分发."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([
        ActionIntent.mouse_up(button="left"),
        ActionIntent.hotkey("ctrl", "a"),
    ])
    # Events must be in order
    assert driver.events[0] == ("mouse_up", "left")
    assert driver.events[1] == ("hotkey", ["ctrl", "a"])


def test_dispatch_full_ppt_exit_sequence() -> None:
    """完整 PPT 退出序列: mouse_up + press(esc) + release_all 按顺序分发."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([
        ActionIntent.mouse_up(button="left"),
        ActionIntent.press("esc"),
        ActionIntent.release_all(),
    ])
    assert driver.events[0] == ("mouse_up", "left")
    assert driver.events[1] == ("press", "esc")
    # release_all produces 3 mouse_up + 3 key_up after the esc press
    mouse_ups = [e for e in driver.events if e[0] == "mouse_up"]
    key_ups = [e for e in driver.events if e[0] == "key_up"]
    assert len(mouse_ups) >= 3  # 1 explicit + 3 from release_all
    assert len(key_ups) == 3


def test_dry_run_fake_driver_never_touches_os() -> None:
    """#17: dry-run / FakeDriver 下 PPT 动作只记录，不真实控制鼠标键盘."""
    controller, driver = _controller_with_fake_driver()
    assert controller.actions.using_fake_driver()
    # Dispatch a full PPT cycle
    controller._dispatch_intents([
        ActionIntent.press("f5"),
        ActionIntent.press("right"),
        ActionIntent.press("left"),
        ActionIntent.hotkey("ctrl", "p"),
        ActionIntent.mouse_down(button="left"),
        ActionIntent.mouse_up(button="left"),
        ActionIntent.hotkey("ctrl", "a"),
        ActionIntent.press("esc"),
        ActionIntent.release_all(),
    ])
    # All recorded as events, no real OS interaction.
    # release_all produces 6 events (3 mouse_up + 3 key_up), so total = 8 + 6 = 14.
    assert len(driver.events) == 14
    # No exception, all events are tuples (fake driver format)
    for ev in driver.events:
        assert isinstance(ev, tuple)


def test_dispatch_press_e_for_erase_recorded() -> None:
    """PPT 擦除: press("e") 正确分发."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.press("e")])
    assert ("press", "e") in driver.events


def test_release_all_idempotent_via_dispatch() -> None:
    """#18: release_all 仍然幂等 (通过 controller dispatch)."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.release_all()])
    controller._dispatch_intents([ActionIntent.release_all()])
    # Should not crash; 12 events (6 + 6 release calls)
    mouse_ups = [e for e in driver.events if e[0] == "mouse_up"]
    key_ups = [e for e in driver.events if e[0] == "key_up"]
    assert len(mouse_ups) == 6  # 3 per release_all × 2
    assert len(key_ups) == 6


# ── Phase 4: Mouse mode intent dispatch ─────────────────────────────────────

def test_dispatch_mouse_click_left_recorded() -> None:
    """Mouse left click dispatch."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.click(button="left")])
    assert ("click", "left") in driver.events


def test_dispatch_mouse_click_right_recorded() -> None:
    """Mouse right click dispatch."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.click(button="right")])
    assert ("click", "right") in driver.events


def test_dispatch_scroll_positive_recorded() -> None:
    """Mouse scroll up dispatch."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.scroll(5)])
    assert ("scroll", 5) in driver.events


def test_dispatch_scroll_negative_recorded() -> None:
    """Mouse scroll down dispatch."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.scroll(-5)])
    assert ("scroll", -5) in driver.events


def test_dispatch_move_rel_recorded() -> None:
    """Mouse relative move dispatch."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.move_rel(20, -10)])
    assert ("move_rel", 20, -10) in driver.events


def test_dispatch_full_mouse_drag_sequence() -> None:
    """Full mouse drag sequence in order."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([
        ActionIntent.mouse_down(button="left"),
        ActionIntent.move(500.0, 300.0),
        ActionIntent.mouse_up(button="left"),
    ])
    assert driver.events[0] == ("mouse_down", "left")
    assert driver.events[1] == ("move_to", 500.0, 300.0)
    assert driver.events[2] == ("mouse_up", "left")


def test_dry_run_mouse_actions_never_touch_os() -> None:
    """Phase 4 #23: dry-run / FakeDriver mouse actions only recorded."""
    controller, driver = _controller_with_fake_driver()
    assert controller.actions.using_fake_driver()
    controller._dispatch_intents([
        ActionIntent.move_to(960, 540),
        ActionIntent.click(button="left"),
        ActionIntent.mouse_down(button="left"),
        ActionIntent.move_rel(10, 20),
        ActionIntent.mouse_up(button="left"),
        ActionIntent.scroll(5),
        ActionIntent.click(button="right"),
        ActionIntent.release_all(),
    ])
    for ev in driver.events:
        assert isinstance(ev, tuple)


# ── Phase 5: SolidWorks intent dispatch ─────────────────────────────────────

def test_dispatch_solidworks_mouse_down_middle_recorded() -> None:
    """SolidWorks rotate: mouse_down("middle") dispatch."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.mouse_down(button="middle")])
    assert ("mouse_down", "middle") in driver.events


def test_dispatch_solidworks_key_down_shift_recorded() -> None:
    """SolidWorks pan: key_down("shift") dispatch."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.key_down("shift")])
    assert ("key_down", "shift") in driver.events


def test_dispatch_solidworks_key_up_shift_recorded() -> None:
    """SolidWorks pan end: key_up("shift") dispatch."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.key_up("shift")])
    assert ("key_up", "shift") in driver.events


def test_dispatch_solidworks_move_rel_recorded() -> None:
    """SolidWorks rotate/pan move: move_rel dispatch."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.move_rel(15, -10)])
    assert ("move_rel", 15, -10) in driver.events


def test_dispatch_solidworks_press_f_recorded() -> None:
    """SolidWorks fit view: press("f") dispatch."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.press("f")])
    assert ("press", "f") in driver.events


def test_dispatch_solidworks_hotkey_ctrl_7_recorded() -> None:
    """SolidWorks isometric: hotkey("ctrl","7") dispatch."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([ActionIntent.hotkey("ctrl", "7")])
    assert ("hotkey", ["ctrl", "7"]) in driver.events


def test_dispatch_full_solidworks_pan_sequence() -> None:
    """Full SolidWorks pan sequence: key_down + mouse_down + move + mouse_up + key_up."""
    controller, driver = _controller_with_fake_driver()
    controller._dispatch_intents([
        ActionIntent.key_down("shift"),
        ActionIntent.mouse_down(button="middle"),
        ActionIntent.move_rel(10, 20),
        ActionIntent.mouse_up(button="middle"),
        ActionIntent.key_up("shift"),
    ])
    assert driver.events[0] == ("key_down", "shift")
    assert driver.events[1] == ("mouse_down", "middle")
    assert driver.events[2] == ("move_rel", 10, 20)
    assert driver.events[3] == ("mouse_up", "middle")
    assert driver.events[4] == ("key_up", "shift")


def test_dry_run_solidworks_actions_never_touch_os() -> None:
    """Phase 5 #25: dry-run / FakeDriver SolidWorks actions only recorded."""
    controller, driver = _controller_with_fake_driver()
    assert controller.actions.using_fake_driver()
    controller._dispatch_intents([
        ActionIntent.mouse_down(button="middle"),
        ActionIntent.key_down("shift"),
        ActionIntent.move_rel(10, 20),
        ActionIntent.scroll(5),
        ActionIntent.mouse_up(button="middle"),
        ActionIntent.key_up("shift"),
        ActionIntent.press("f"),
        ActionIntent.hotkey("ctrl", "7"),
        ActionIntent.release_all(),
    ])
    for ev in driver.events:
        assert isinstance(ev, tuple)


# ── Phase 6: Model file check, dry-run safety, config preservation ─────────

def test_check_model_files_returns_empty_when_exists() -> None:
    """Model file check passes when hand_landmarker.task exists."""
    from hands.gesture_controller import check_model_files
    # The project root has hand_landmarker.task, so check should pass.
    # use_gesture_recognizer=False to only check hand_landmarker.task.
    missing = check_model_files(use_gesture_recognizer=False)
    assert missing == []


def test_check_model_files_returns_missing_when_absent() -> None:
    """Model file check reports missing file when not present."""
    from hands.gesture_controller import check_model_files
    # Use a temp dir with no model file.  use_gesture_recognizer=False so
    # only hand_landmarker.task is required.
    with tempfile.TemporaryDirectory() as tmpdir:
        missing = check_model_files(tmpdir, use_gesture_recognizer=False)
        assert len(missing) == 1
        assert "hand_landmarker.task" in missing[0]


# ── Phase 8: GestureRecognizer model file check ─────────────────────────────

def test_check_model_files_includes_gesture_recognizer_when_enabled() -> None:
    """When use_gesture_recognizer=True, gesture_recognizer.task is required."""
    from hands.gesture_controller import check_model_files
    with tempfile.TemporaryDirectory() as tmpdir:
        missing = check_model_files(tmpdir, use_gesture_recognizer=True)
        # Both hand_landmarker.task and gesture_recognizer.task should be missing.
        assert len(missing) == 2
        names = [os.path.basename(m) for m in missing]
        assert "hand_landmarker.task" in names
        assert "gesture_recognizer.task" in names


def test_check_model_files_excludes_gesture_recognizer_when_disabled() -> None:
    """When use_gesture_recognizer=False, gesture_recognizer.task is NOT required."""
    from hands.gesture_controller import check_model_files
    with tempfile.TemporaryDirectory() as tmpdir:
        missing = check_model_files(tmpdir, use_gesture_recognizer=False)
        assert len(missing) == 1
        assert "hand_landmarker.task" in missing[0]
        assert "gesture_recognizer.task" not in missing[0]


def test_check_model_files_passes_when_both_exist() -> None:
    """When both model files exist and use_gesture_recognizer=True, no missing."""
    from hands.gesture_controller import check_model_files
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create both dummy model files.
        open(os.path.join(tmpdir, "hand_landmarker.task"), "w").close()
        open(os.path.join(tmpdir, "gesture_recognizer.task"), "w").close()
        missing = check_model_files(tmpdir, use_gesture_recognizer=True)
        assert missing == []


# ── Phase 8: GestureRecognizer config preservation ──────────────────────────

def test_use_gesture_recognizer_config_default_true() -> None:
    """use_gesture_recognizer defaults to True."""
    config = default_config()
    assert config.use_gesture_recognizer is True


def test_use_gesture_recognizer_config_can_be_disabled() -> None:
    """use_gesture_recognizer can be set to False."""
    config = default_config()
    config.use_gesture_recognizer = False
    assert config.use_gesture_recognizer is False


def test_fallback_to_rule_gestures_config_default_true() -> None:
    """fallback_to_rule_gestures defaults to True."""
    config = default_config()
    assert config.fallback_to_rule_gestures is True


def test_gesture_recognizer_model_path_config() -> None:
    """gesture_recognizer_model_path defaults to gesture_recognizer.task."""
    config = default_config()
    assert config.gesture_recognizer_model_path == "gesture_recognizer.task"


def test_min_gesture_confidence_config_default() -> None:
    """min_gesture_confidence defaults to 0.65."""
    config = default_config()
    assert config.min_gesture_confidence == 0.65


# ── Phase 8: SWIPE still computed by state machine (not recognizer) ──────────

def test_swipe_still_computed_by_state_machine() -> None:
    """SWIPE_LEFT / SWIPE_RIGHT still come from Open_Palm trajectory in state machine.

    This verifies that the HandInput from to_hand_input still carries ``wave_x``
    (palm center x), which the state machine uses for swipe trajectory computation.
    SWIPE is not a GestureRecognizer canned gesture — it must remain landmark-based.
    """
    from hands.gesture_recognition import HandRecognizer, _FrameResult
    from hands.gesture_state import Gesture

    # Build a recognizer with a fake GR that returns Open_Palm.
    r = HandRecognizer(
        use_gesture_recognizer=True,
        gesture_recognizer_fn=lambda mp_image: ("Open_Palm", 0.99),
    )

    # Construct a frame result with open-palm landmarks (landmarks carry wave_x).
    from tests.test_gesture_recognition import _open_palm
    lm = _open_palm()
    fr = _FrameResult(
        landmarks=lm,
        raw_hand_landmarks=None,
        gesture="Open_Palm",
        gesture_confidence=0.99,
        gesture_source="gesture_recognizer",
        raw_gesture="Open_Palm",
    )
    hi = r.to_hand_input(fr)

    # wave_x must be present — the state machine needs it for swipe detection.
    assert hi.wave_x is not None
    assert hi.gesture == Gesture.OPEN_PALM
    # palm_xy must also be present (used for DRAG / move_rel).
    assert hi.palm_xy is not None


def test_dry_run_fake_driver_never_calls_real_pyautogui() -> None:
    """Dry-run / FakeDriver never touches real OS mouse/keyboard."""
    controller, driver = _controller_with_fake_driver()
    assert controller.actions.using_fake_driver()
    # Dispatch various intents — all should be recorded by FakeDriver only.
    controller._dispatch_intents([
        ActionIntent.move_to(100, 200),
        ActionIntent.click(button="left"),
        ActionIntent.mouse_down(button="middle"),
        ActionIntent.key_down("shift"),
        ActionIntent.scroll(5),
        ActionIntent.key_up("shift"),
        ActionIntent.mouse_up(button="middle"),
        ActionIntent.press("f"),
        ActionIntent.hotkey("ctrl", "7"),
        ActionIntent.release_all(),
    ])
    # All events are tuples (FakeDriver format), no real OS calls.
    for ev in driver.events:
        assert isinstance(ev, tuple)


def test_controller_dispatches_via_action_layer_execute() -> None:
    """Controller still dispatches intents via ActionLayer.execute()."""
    controller, driver = _controller_with_fake_driver()
    # _dispatch_intents should call actions.execute()
    controller._dispatch_intents([ActionIntent.press("f5")])
    assert ("press", "f5") in driver.events


class _FakeDisplayAgent:
    def __init__(self, result: DisplayAgentResult) -> None:
        self.result = result
        self.apps = []

    def status(self) -> DisplayAgentResult:
        return self.result

    def activate(self, app: str) -> DisplayAgentResult:
        self.apps.append(app)
        return self.result


@pytest.mark.parametrize(
    ("before", "after", "target"),
    [
        ("standby", "presentation", "powerpoint"),
        ("presentation", "standby", "smartdesk"),
        ("standby", "solidworks", "solidworks"),
        ("solidworks", "standby", "smartdesk"),
        ("presentation", "solidworks", "solidworks"),
        ("solidworks", "presentation", "powerpoint"),
    ],
)
def test_display_agent_receives_all_mode_swipe_mappings(before, after, target):
    client = _FakeDisplayAgent(
        DisplayAgentResult(ok=True, online=True, app=target)
    )
    controller, _ = _controller_with_fake_driver()
    controller.display_agent_client = client
    controller.state.mode = after

    assert controller._sync_display_mode_transition(before, after, 10.0) is True
    assert client.apps == [target]
    assert controller.state.mode == after
    assert controller._display_status["display_active_app"] == target


def test_display_switch_failure_restores_previous_mode():
    client = _FakeDisplayAgent(
        DisplayAgentResult(
            ok=False,
            online=True,
            app="solidworks",
            detail="SolidWorks window not found",
            status_code=409,
        )
    )
    controller, _ = _controller_with_fake_driver()
    controller.display_agent_client = client
    controller.state.mode = "solidworks"

    assert controller._sync_display_mode_transition("standby", "solidworks", 10.0) is False
    assert controller.state.mode == "standby"
    assert controller._display_status["display_switch_state"] == "failed"
    assert controller._display_status["display_switch_error"] == "SolidWorks window not found"


def test_presentation_pen_does_not_reactivate_powerpoint():
    client = _FakeDisplayAgent(DisplayAgentResult(ok=True, online=True))
    controller, _ = _controller_with_fake_driver()
    controller.display_agent_client = client
    controller.state.mode = "presentation_pen"

    assert controller._sync_display_mode_transition(
        "presentation", "presentation_pen", 10.0
    ) is True
    assert client.apps == []


def test_start_paused_config_preserved() -> None:
    """start_paused config is not broken."""
    config = default_config()
    config.start_paused = True
    config.pause_on_start = True
    assert config.start_paused is True
    assert config.pause_on_start is True


def test_enable_hotkeys_config_preserved() -> None:
    """enable_hotkeys config is not broken."""
    config = default_config()
    assert config.enable_hotkeys is True
    config.enable_hotkeys = False
    assert config.enable_hotkeys is False


def test_dry_run_config_preserved() -> None:
    """dry_run config is not broken."""
    config = default_config()
    config.dry_run = True
    config.enable_system_mouse = False
    assert config.dry_run is True
    assert config.enable_system_mouse is False


def test_config_hotkeys_not_broken() -> None:
    """Ctrl+Alt+G / Ctrl+Alt+Q hotkey strings are preserved."""
    config = default_config()
    assert "ctrl" in config.hotkey_toggle_pause.lower()
    assert "alt" in config.hotkey_toggle_pause.lower()
    assert "g" in config.hotkey_toggle_pause.lower()
    assert "ctrl" in config.hotkey_emergency_exit.lower()
    assert "alt" in config.hotkey_emergency_exit.lower()
    assert "q" in config.hotkey_emergency_exit.lower()


def test_solidworks_zoom_sensitivity_can_be_negative() -> None:
    """SolidWorks zoom direction can be reversed via negative sensitivity."""
    config = default_config()
    config.solidworks_zoom_sensitivity = -8.0
    assert config.solidworks_zoom_sensitivity == -8.0


# ── Phase 10: keyboard backend + cv2 fallback ───────────────────────────────

def test_keyboard_backend_registers_global_hotkeys(monkeypatch):
    """keyboard backend registers Ctrl+Alt+G and Ctrl+Alt+Q."""
    import sys

    registered = []

    def fake_add_hotkey(hotkey, callback):
        registered.append(hotkey)
        return f"handle_{hotkey}"

    fake_keyboard = type(
        "FakeKeyboard",
        (),
        {
            "add_hotkey": staticmethod(fake_add_hotkey),
            "remove_hotkey": staticmethod(lambda h: None),
            "unhook_all_hotkeys": staticmethod(lambda: None),
        },
    )
    monkeypatch.setitem(sys.modules, "keyboard", fake_keyboard)

    controller, _ = _controller_with_fake_driver()
    controller._install_hotkeys()

    assert controller._hotkey_backend == "keyboard"
    assert "ctrl+alt+g" in registered
    assert "ctrl+alt+q" in registered

    # Cleanup should clear backend state.
    controller._uninstall_hotkeys()
    assert controller._hotkey_backend is None


def test_keyboard_backend_registration_failure_still_starts(monkeypatch, caplog):
    """If keyboard.add_hotkey fails the controller does not crash and prints a warning."""
    import sys

    def fake_add_hotkey(hotkey, callback):
        raise RuntimeError("keyboard registration failed")

    fake_keyboard = type(
        "FakeKeyboard",
        (),
        {
            "add_hotkey": staticmethod(fake_add_hotkey),
            "remove_hotkey": staticmethod(lambda h: None),
            "unhook_all_hotkeys": staticmethod(lambda: None),
        },
    )
    monkeypatch.setitem(sys.modules, "keyboard", fake_keyboard)

    # Make pynput unavailable as well so we hit the final fallback path.
    monkeypatch.setitem(sys.modules, "pynput", None)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", None)

    controller, _ = _controller_with_fake_driver()
    controller._install_hotkeys()

    assert controller._hotkey_backend is None
    assert controller._hotkey_handles == []
    assert "global hotkeys unavailable" in caplog.text.lower()


def test_debug_window_p_key_toggles_pause(monkeypatch):
    """Pressing 'p' in the cv2 window toggles pause/resume."""
    import cv2

    controller, _ = _controller_with_fake_driver()
    controller.config.show_debug_window = True
    controller.state.paused = True  # start paused for toggle test
    assert controller.state.paused is True

    # Simulate a single 'p' keypress.
    def fake_waitKey(delay):
        return ord('p') & 0xFF

    monkeypatch.setattr(cv2, "waitKey", fake_waitKey)
    controller._handle_debug_keys()
    assert controller.state.paused is False

    # Pressing 'p' again resumes pause.
    controller._handle_debug_keys()
    assert controller.state.paused is True


def test_debug_window_space_key_toggles_pause(monkeypatch):
    """Pressing Space in the cv2 window toggles pause/resume."""
    import cv2

    controller, _ = _controller_with_fake_driver()
    controller.config.show_debug_window = True
    controller.state.paused = True  # start paused for toggle test
    assert controller.state.paused is True

    def fake_waitKey(delay):
        return 32  # Space

    monkeypatch.setattr(cv2, "waitKey", fake_waitKey)
    controller._handle_debug_keys()
    assert controller.state.paused is False


def test_debug_window_q_key_quits(monkeypatch):
    """Pressing 'q' in the cv2 window requests exit."""
    import cv2

    controller, _ = _controller_with_fake_driver()
    controller.config.show_debug_window = True

    def fake_waitKey(delay):
        return ord('q') & 0xFF

    monkeypatch.setattr(cv2, "waitKey", fake_waitKey)
    assert controller._handle_debug_keys() is True


def test_debug_window_esc_key_quits(monkeypatch):
    """Pressing Esc in the cv2 window requests exit."""
    import cv2

    controller, _ = _controller_with_fake_driver()
    controller.config.show_debug_window = True

    def fake_waitKey(delay):
        return 27  # Esc

    monkeypatch.setattr(cv2, "waitKey", fake_waitKey)
    assert controller._handle_debug_keys() is True


def test_no_mouse_uses_fake_driver():
    """--no-mouse creates a controller that uses FakeDriver."""
    from hands.gesture_config import config_from_args

    config = config_from_args(["--no-mouse"])
    controller = GestureController(config=config)
    assert controller.config.dry_run is True
    assert controller.config.enable_system_mouse is False
    assert controller.actions.using_fake_driver()


def test_start_unpaused_argument():
    """--start-unpaused disables pause_on_start / start_paused."""
    from hands.gesture_config import config_from_args

    config = config_from_args(["--start-unpaused"])
    assert config.pause_on_start is False
    assert config.start_paused is False


def test_no_pause_on_start_argument():
    """--no-pause-on-start still works."""
    from hands.gesture_config import config_from_args

    config = config_from_args(["--no-pause-on-start"])
    assert config.pause_on_start is False
    assert config.start_paused is False


# ═══════════════════════════════════════════════════════════════════════════
# Task-2 — GestureFrame construction in controller
# ═══════════════════════════════════════════════════════════════════════════

from hands.gesture_intent_tracker import GestureFrame, GestureSource
from hands.gesture_recognition import _FrameResult


def test_controller_constructs_gesture_frame_from_frame_result() -> None:
    """The controller's recognizer can produce a GestureFrame from _FrameResult."""
    controller, driver = _controller_with_fake_driver()
    recognizer = controller.recognizer

    # Build a _FrameResult with raw hand landmarks.
    class _FakeLM:
        def __init__(self, x, y):
            self.x = x
            self.y = y

    raw_hand = [[_FakeLM(0.4, 0.6) if i == 0 else
                 _FakeLM(0.5, 0.4) if i == 9 else
                 _FakeLM(0.55, 0.3) if i == 8 else
                 _FakeLM(0.45, 0.35) if i == 4 else
                 _FakeLM(0.0, 0.0) for i in range(21)]]
    # Fix: need individual landmarks, not nested list
    raw_hand = []
    hand_lms = []
    for i in range(21):
        if i == 0:
            hand_lms.append(_FakeLM(0.4, 0.6))
        elif i == 4:
            hand_lms.append(_FakeLM(0.45, 0.35))
        elif i == 8:
            hand_lms.append(_FakeLM(0.55, 0.3))
        elif i == 9:
            hand_lms.append(_FakeLM(0.5, 0.4))
        else:
            hand_lms.append(_FakeLM(0.0, 0.0))
    raw_hand = [hand_lms]

    fr = _FrameResult(
        landmarks=[[i, 0, 0] for i in range(21)],
        raw_hand_landmarks=raw_hand,
        gesture="Open_Palm",
        gesture_confidence=0.9,
        gesture_source="gesture_recognizer",
        raw_gesture="Open_Palm",
    )
    gf = recognizer.to_gesture_frame(fr)

    assert gf.hand_present is True
    assert gf.raw_gesture == "Open_Palm"
    assert gf.gesture_source == GestureSource.RECOGNIZER
    assert gf.palm_xy is not None
    assert gf.index_tip_xy is not None
    assert gf.hand_size is not None
    assert gf.pinch_distance_norm is not None


def test_controller_no_hand_gesture_frame() -> None:
    """No-hand _FrameResult produces hand_present=False GestureFrame."""
    controller, driver = _controller_with_fake_driver()
    recognizer = controller.recognizer

    fr = _FrameResult(landmarks=None, gesture="None", gesture_source="none")
    gf = recognizer.to_gesture_frame(fr)

    assert gf.hand_present is False
    assert gf.raw_gesture is None
    assert gf.palm_xy is None
    assert gf.pinch_distance_norm is None


# ── Phase 3 fix: tracker.update receives monotonic time ─────────────────────

def test_tracker_update_receives_monotonic_time() -> None:
    """Controller._process_frame passes monotonic time to tracker.update.

    We patch tracker.update to capture the ``now`` argument, then call
    _process_frame with a no-hand frame.  The captured value must be
    close to time.monotonic() (not time.time()).
    """
    import time as _time

    controller, driver = _controller_with_fake_driver()

    captured_now = {}
    original_update = controller.tracker.update

    def _capture_update(frame, current_mode, now):
        captured_now["value"] = now
        return original_update(frame, current_mode, now)

    controller.tracker.update = _capture_update

    # Build a no-hand frame result (avoids needing mediapipe/cv2).
    from hands.gesture_recognition import _FrameResult
    fr = _FrameResult(landmarks=None, gesture="None", gesture_source="none")
    hand_input = controller.recognizer.to_hand_input(fr)
    gesture_frame = controller.recognizer.to_gesture_frame(fr)

    mono_before = _time.monotonic()
    controller._process_frame.__wrapped__ if hasattr(controller._process_frame, "__wrapped__") else None

    # Call _process_frame directly with a dummy image and monotonic time.
    import numpy as np
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    now_mono = _time.monotonic()
    controller._process_frame(img, now_mono)
    mono_after = _time.monotonic()

    assert "value" in captured_now, "tracker.update was not called"
    captured = captured_now["value"]
    # The captured value must be within the monotonic window we measured,
    # proving it came from time.monotonic() — not time.time() (which would
    # be ~1.7 billion, far outside this range on any current machine).
    assert mono_before - 1.0 <= captured <= mono_after + 1.0, \
        f"captured now={captured} is not monotonic; expected ~[{mono_before}, {mono_after}]"

    # Sanity: time.time() should be much larger than monotonic on this machine.
    wall = _time.time()
    assert abs(wall - captured) > 1000, \
        f"captured now={captured} looks like wall-clock time={wall}; expected monotonic"


def test_controller_loop_uses_monotonic_time() -> None:
    """The _loop method uses time.monotonic(), not time.time()."""
    import inspect
    from hands.gesture_controller import GestureController
    src = inspect.getsource(GestureController._loop)
    assert "time.monotonic()" in src, "_loop must use time.monotonic()"
    assert "time.time()" not in src, "_loop must NOT use time.time()"
