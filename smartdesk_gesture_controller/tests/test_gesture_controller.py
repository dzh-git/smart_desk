"""Tests for hands.gesture_controller intent dispatch.

These tests keep the controller at the boundary between pure state intents
and the ActionLayer. They use FakeDriver so no OS mouse/keyboard events run.
"""
from __future__ import annotations

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
