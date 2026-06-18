"""Tests for hands.gesture_actions — pyautogui action wrapper.

Tests use FakeDriver so nothing touches the real OS. Real pyautogui is only
tested indirectly when ``enable_system_mouse=True`` — but those tests are
skipped on environments without a display.
"""
from __future__ import annotations

import pytest

from hands.gesture_actions import (
    ActionLayer,
    FakeDriver,
    _Call,
)


class TestFakeDriver:
    def test_records_calls(self) -> None:
        d = FakeDriver()
        d.moveTo(100, 200)
        d.click(button="left")
        assert d.names() == ["moveTo", "click"]

    def test_reset(self) -> None:
        d = FakeDriver()
        d.moveTo(1, 2)
        d.reset()
        assert d.calls == []

    def test_kwargs(self) -> None:
        d = FakeDriver()
        d.mouseDown(button="left", x=10, y=20)
        assert d.calls[0].kwargs == {"button": "left", "x": 10, "y": 20}

    def test_size(self) -> None:
        d = FakeDriver()
        assert d.size() == (1920, 1080)


class TestActionLayerDryRun:
    """When enable_system_mouse=False, actions go through FakeDriver only."""

    def setup_method(self) -> None:
        self.driver = FakeDriver()
        self.actions = ActionLayer(enable_system_mouse=False, driver=self.driver)

    def test_move_to_recorded(self) -> None:
        self.actions.move_to(100, 200)
        assert self.driver.names() == ["moveTo"]

    def test_left_click_recorded(self) -> None:
        self.actions.left_click()
        assert "click" in self.driver.names()

    def test_mouse_down_tracking(self) -> None:
        self.actions.mouse_down(10, 20)
        assert self.actions.is_left_down
        assert "mouseDown" in self.driver.names()

    def test_mouse_up_tracking(self) -> None:
        self.actions.mouse_down()
        self.actions.mouse_up(10, 20)
        assert not self.actions.is_left_down

    def test_press_recorded(self) -> None:
        self.actions.press("left")
        assert self.driver.calls[0].args == ("left",)

    def test_hotkey_recorded(self) -> None:
        self.actions.hotkey("ctrl", "p")
        assert self.driver.calls[0].args == ("ctrl", "p")

    def test_release_all_when_down(self) -> None:
        self.actions.mouse_down()
        self.actions.release_all()
        assert not self.actions.is_left_down
        assert "mouseUp" in self.driver.names()

    def test_release_all_idempotent(self) -> None:
        self.actions.release_all()
        self.actions.release_all()
        # No crash, no extra calls
        assert self.driver.names() == []

    def test_using_fake_driver_true(self) -> None:
        assert self.actions.using_fake_driver() is True


class TestActionLayerRealMouse:
    """When enable_system_mouse=True and no driver injected, it imports pyautogui.

    Marked xfail on headless CI where pyautogui may not have a display.
    """

    @pytest.mark.skipif(True, reason="real pyautogui requires a display — test offline only")
    def test_real_driver_imported(self) -> None:
        # This test is intentionally always skipped; it documents the behavior
        # for developers running locally with a display.
        actions = ActionLayer(enable_system_mouse=True)
        assert not actions.using_fake_driver()
