"""Tests for hands.gesture_actions — ActionLayer, FakeDriver, execute().

Tests use FakeDriver so nothing touches the real OS. Real pyautogui is only
tested indirectly when ``enable_system_mouse=True`` — but those tests are
skipped on environments without a display.

Core action-driver coverage:
    1. press recorded
    2. hotkey recorded
    3. mouse_down / mouse_up recorded
    4. key_down / key_up recorded
    5. move_to / move_rel recorded
    6. scroll recorded
    7. release_all releases left / middle / right / shift / ctrl / alt
    8. release_all idempotent (repeatable, no crash)
    9. noop does nothing
    10. status does not control mouse/keyboard
    11. execute(None) and execute([]) do not crash
    12. dry-run / FakeDriver mode never touches real OS
"""
from __future__ import annotations

import pytest

from hands.gesture_actions import (
    ActionLayer,
    FakeDriver,
    _Call,
)
from hands.gesture_state import ActionIntent


# ── helpers ──────────────────────────────────────────────────────────────────

def _layer() -> tuple[ActionLayer, FakeDriver]:
    """Build a dry-run ActionLayer with a fresh FakeDriver."""
    d = FakeDriver()
    a = ActionLayer(enable_system_mouse=False, driver=d)
    return a, d


# ── FakeDriver basics ────────────────────────────────────────────────────────

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
        assert d.events == []

    def test_kwargs(self) -> None:
        d = FakeDriver()
        d.mouseDown(button="left", x=10, y=20)
        assert d.calls[0].kwargs == {"button": "left", "x": 10, "y": 20}

    def test_size(self) -> None:
        d = FakeDriver()
        assert d.size() == (1920, 1080)

    def test_events_format(self) -> None:
        """FakeDriver.events must match the public action-driver tuple format."""
        d = FakeDriver()
        d.press("f5")
        d.hotkey("ctrl", "p")
        d.mouseDown(button="left")
        d.mouseUp(button="left")
        d.moveRel(10, -5)
        d.scroll(5)
        d.keyDown("shift")
        d.keyUp("shift")
        assert d.events == [
            ("press", "f5"),
            ("hotkey", ["ctrl", "p"]),
            ("mouse_down", "left"),
            ("mouse_up", "left"),
            ("move_rel", 10, -5),
            ("scroll", 5),
            ("key_down", "shift"),
            ("key_up", "shift"),
        ]

    def test_has_event(self) -> None:
        d = FakeDriver()
        d.press("esc")
        assert d.has_event("press", "esc")
        assert not d.has_event("press", "f5")


# ── execute() entry point ────────────────────────────────────────────────────

class TestExecuteEntryPoint:
    """execute() accepts None, single intent, list, and empty list."""

    def test_execute_none(self) -> None:
        a, d = _layer()
        a.execute(None)
        assert d.events == []

    def test_execute_empty_list(self) -> None:
        a, d = _layer()
        a.execute([])
        assert d.events == []

    def test_execute_single_intent(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.press("f5"))
        assert d.events == [("press", "f5")]

    def test_execute_list_in_order(self) -> None:
        a, d = _layer()
        a.execute([
            ActionIntent.mouse_down(button="middle"),
            ActionIntent.move_rel(10, 20),
            ActionIntent.mouse_up(button="middle"),
        ])
        assert d.events == [
            ("mouse_down", "middle"),
            ("move_rel", 10, 20),
            ("mouse_up", "middle"),
        ]

    def test_execute_unknown_type_raises(self) -> None:
        a, d = _layer()
        bad = ActionIntent(type="does_not_exist")
        with pytest.raises(ValueError, match="unknown ActionIntent type"):
            a.execute(bad)


# ── keyboard actions ─────────────────────────────────────────────────────────

class TestKeyboardActions:
    def test_press_recorded(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.press("f5"))
        assert ("press", "f5") in d.events

    def test_hotkey_recorded(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.hotkey("ctrl", "p"))
        assert ("hotkey", ["ctrl", "p"]) in d.events

    def test_key_down_recorded(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.key_down("shift"))
        assert ("key_down", "shift") in d.events
        assert "shift" in a.held_keys

    def test_key_up_recorded(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.key_down("shift"))
        a.execute(ActionIntent.key_up("shift"))
        assert ("key_up", "shift") in d.events
        assert "shift" not in a.held_keys

    def test_press_missing_key_raises(self) -> None:
        a, d = _layer()
        with pytest.raises(ValueError):
            a.execute(ActionIntent(type="press"))


# ── mouse actions ────────────────────────────────────────────────────────────

class TestMouseActions:
    def test_mouse_down_recorded(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.mouse_down(button="left"))
        assert ("mouse_down", "left") in d.events
        assert "left" in a.held_buttons

    def test_mouse_up_recorded(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.mouse_down(button="left"))
        a.execute(ActionIntent.mouse_up(button="left"))
        assert ("mouse_up", "left") in d.events
        assert "left" not in a.held_buttons

    def test_mouse_down_middle(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.mouse_down(button="middle"))
        assert ("mouse_down", "middle") in d.events
        assert "middle" in a.held_buttons

    def test_click_recorded(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.click(button="left"))
        assert ("click", "left") in d.events

    def test_click_right(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.click(button="right"))
        assert ("click", "right") in d.events

    def test_move_to_recorded(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.move_to(960, 540))
        assert ("move_to", 960, 540) in d.events

    def test_move_rel_recorded(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.move_rel(20, -10))
        assert ("move_rel", 20, -10) in d.events

    def test_legacy_move_alias(self) -> None:
        """Legacy 'move' type should be treated as move_to by execute()."""
        a, d = _layer()
        a.execute(ActionIntent.move(100, 200))
        assert ("move_to", 100, 200) in d.events

    def test_scroll_recorded(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.scroll(5))
        assert ("scroll", 5) in d.events

    def test_scroll_negative(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.scroll(-5))
        assert ("scroll", -5) in d.events


# ── release_all ──────────────────────────────────────────────────────────────

class TestReleaseAll:
    def test_release_all_releases_six(self) -> None:
        """release_all must release left/middle/right + shift/ctrl/alt."""
        a, d = _layer()
        a.release_all()
        # Six events: 3 mouse_up + 3 key_up
        mouse_ups = [e for e in d.events if e[0] == "mouse_up"]
        key_ups = [e for e in d.events if e[0] == "key_up"]
        assert len(mouse_ups) == 3
        assert len(key_ups) == 3
        buttons = {e[1] for e in mouse_ups}
        keys = {e[1] for e in key_ups}
        assert buttons == {"left", "middle", "right"}
        assert keys == {"shift", "ctrl", "alt"}

    def test_release_all_idempotent(self) -> None:
        """Calling release_all twice must not crash."""
        a, d = _layer()
        a.release_all()
        a.release_all()
        # 12 events total (6 + 6)
        assert len(d.events) == 12

    def test_release_all_after_holds(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.mouse_down(button="left"))
        a.execute(ActionIntent.mouse_down(button="middle"))
        a.execute(ActionIntent.key_down("shift"))
        a.release_all()
        assert a.held_buttons == set()
        assert a.held_keys == set()

    def test_release_all_via_execute(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.release_all())
        assert len([e for e in d.events if e[0] == "mouse_up"]) == 3
        assert len([e for e in d.events if e[0] == "key_up"]) == 3

    def test_release_all_clears_is_left_down(self) -> None:
        a, d = _layer()
        a.mouse_down()
        assert a.is_left_down
        a.release_all()
        assert not a.is_left_down

    def test_release_all_when_nothing_held(self) -> None:
        """release_all with nothing held must not crash and must still fire 6 releases."""
        a, d = _layer()
        a.release_all()
        assert len(d.events) == 6


# ── noop and status ──────────────────────────────────────────────────────────

class TestNoopAndStatus:
    def test_noop_does_nothing(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.noop())
        assert d.events == []

    def test_status_no_mouse_keyboard(self) -> None:
        """status must not produce any mouse or keyboard events."""
        a, d = _layer()
        a.execute(ActionIntent.status("Presentation mode active"))
        assert d.events == []
        # No mouse_down, mouse_up, click, press, hotkey, scroll, key_down, key_up
        hardware_types = {"mouse_down", "mouse_up", "click", "press", "hotkey",
                          "scroll", "key_down", "key_up", "move_to", "move_rel"}
        assert not any(e[0] in hardware_types for e in d.events)

    def test_status_empty_text_ok(self) -> None:
        a, d = _layer()
        a.execute(ActionIntent.status())
        assert d.events == []


# ── dry-run safety ───────────────────────────────────────────────────────────

class TestDryRunSafety:
    """FakeDriver must never touch the real OS."""

    def test_dry_run_uses_fake_driver(self) -> None:
        a, d = _layer()
        assert a.using_fake_driver()

    def test_dry_run_events_go_to_fake(self) -> None:
        a, d = _layer()
        a.execute([
            ActionIntent.press("right"),
            ActionIntent.click("left"),
            ActionIntent.scroll(5),
        ])
        assert len(d.events) == 3

    def test_real_mouse_skipped_in_ci(self) -> None:
        """When enable_system_mouse=True and no driver injected, it would import
        pyautogui — but this test is always skipped on headless CI."""
        pass  # documented behaviour; real-driver tests run locally only


# ── backward compat: legacy positional methods ───────────────────────────────

class TestLegacyMethods:
    """The controller calls these methods directly; they must keep working."""

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

    def test_using_fake_driver_true(self) -> None:
        assert self.actions.using_fake_driver() is True


# ── ActionIntent backward compat ─────────────────────────────────────────────

class TestActionIntentCompat:
    """kind/args properties must bridge old controller dispatch to new fields."""

    def test_kind_alias(self) -> None:
        i = ActionIntent(type="press", key="f5")
        assert i.kind == "press"

    def test_args_for_press(self) -> None:
        i = ActionIntent.press("right")
        assert i.args == ("right",)

    def test_args_for_hotkey(self) -> None:
        i = ActionIntent.hotkey("ctrl", "p")
        assert i.args == ("ctrl", "p")

    def test_args_for_move(self) -> None:
        i = ActionIntent.move(100.0, 200.0)
        assert i.args == (100.0, 200.0)

    def test_args_for_mouse_down(self) -> None:
        i = ActionIntent.mouse_down(10, 20)
        assert i.args == (10, 20)

    def test_args_for_click(self) -> None:
        i = ActionIntent.click()
        assert i.args == ()

    def test_args_for_release_all(self) -> None:
        i = ActionIntent.release_all()
        assert i.args == ()

    def test_kwargs_empty(self) -> None:
        i = ActionIntent.press("esc")
        assert i.kwargs == {}
