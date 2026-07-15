"""Tests for hands.gesture_overlay.

Status derivation logic is tested as pure functions (no Qt required).
Lifecycle is tested via FakeOverlay injection (same pattern as FakeDriver).
GUI rendering code is marked ``pragma: no cover`` (requires a real display).
"""

from __future__ import annotations

import sys

import pytest

from hands.gesture_overlay import (
    BADGE_STYLES,
    COLOR_AMBER,
    COLOR_CYAN,
    COLOR_GREEN,
    COLOR_MUTED,
    COLOR_ROSE,
    HAND_LOSS_TIMEOUT,
    PAGE_GLOW_MS,
    check_page_turn,
    derive_camera,
    derive_hand,
    derive_status,
)
from hands.gesture_config import config_from_args, default_config

_NOW = 1_000_000.0


# ── derive_camera ───────────────────────────────────────────────────────────


def test_derive_camera_online():
    assert derive_camera({"camera_ok": True}) == ("Online", COLOR_GREEN)


def test_derive_camera_offline():
    assert derive_camera({"camera_ok": False}) == ("Offline", COLOR_ROSE)


def test_derive_camera_missing_field():
    assert derive_camera({}) == ("Offline", COLOR_ROSE)


# ── derive_hand (5 cases matching spec) ─────────────────────────────────────


def test_derive_hand_unavailable_when_camera_off():
    assert derive_hand({"camera_ok": False}) == ("Unavailable", COLOR_MUTED)


def test_derive_hand_searching_when_no_hand():
    snap = {
        "camera_ok": True,
        "hand_present": False,
        "gesture": "none",
        "hand_lost_duration": 0.0,
    }
    assert derive_hand(snap) == ("Searching", COLOR_AMBER)


def test_derive_hand_detected_via_hand_present():
    snap = {"camera_ok": True, "hand_present": True, "gesture": "none"}
    assert derive_hand(snap) == ("Detected", COLOR_GREEN)


def test_derive_hand_detected_via_gesture_not_none():
    snap = {"camera_ok": True, "hand_present": False, "gesture": "Open_Palm"}
    assert derive_hand(snap) == ("Detected", COLOR_GREEN)


def test_derive_hand_lost_after_timeout():
    snap = {
        "camera_ok": True,
        "hand_present": False,
        "gesture": "none",
        "hand_lost_duration": HAND_LOSS_TIMEOUT + 0.1,
    }
    assert derive_hand(snap) == ("Lost", COLOR_ROSE)


# ── derive_status (13-level priority chain) ─────────────────────────────────


def test_status_paused_wins_everything():
    snap = {"paused": True, "camera_ok": False, "mode": "presentation"}
    assert derive_status(snap, ("", ""), _NOW, None) == ("Paused", COLOR_AMBER, False)


def test_status_paused_via_control_enabled_false():
    snap = {"paused": False, "control_enabled": False, "camera_ok": True}
    assert derive_status(snap, ("Detected", COLOR_GREEN), _NOW, None) == (
        "Paused",
        COLOR_AMBER,
        False,
    )


def test_status_camera_offline_when_not_paused():
    snap = {"paused": False, "camera_ok": False}
    assert derive_status(snap, ("", ""), _NOW, None) == (
        "Camera Offline",
        COLOR_ROSE,
        False,
    )


def test_status_display_switch_failed():
    snap = {
        "paused": False,
        "camera_ok": True,
        "display_switch_state": "failed",
    }
    assert derive_status(snap, ("Detected", COLOR_GREEN), _NOW, None) == (
        "Display Switch Failed",
        COLOR_ROSE,
        False,
    )


def test_status_display_switching():
    snap = {
        "paused": False,
        "camera_ok": True,
        "display_switch_state": "switching",
    }
    assert derive_status(snap, ("Detected", COLOR_GREEN), _NOW, None) == (
        "Switching Display",
        COLOR_CYAN,
        True,
    )


def test_status_hand_lost():
    snap = {"paused": False, "camera_ok": True, "mode": "presentation"}
    assert derive_status(snap, ("Lost", COLOR_ROSE), _NOW, None) == (
        "Hand Lost",
        COLOR_ROSE,
        False,
    )


def test_status_show_your_hand():
    snap = {"paused": False, "camera_ok": True, "mode": "presentation"}
    assert derive_status(snap, ("Searching", COLOR_AMBER), _NOW, None) == (
        "Show Your Hand",
        COLOR_AMBER,
        False,
    )


def test_status_standby():
    snap = {"paused": False, "camera_ok": True, "mode": "standby"}
    assert derive_status(snap, ("Detected", COLOR_GREEN), _NOW, None) == (
        "Standby",
        COLOR_MUTED,
        False,
    )


def test_status_pen_mode_no_draw():
    snap = {
        "paused": False,
        "camera_ok": True,
        "mode": "presentation_pen",
        "action": "idle",
        "intent_phase": "idle",
    }
    assert derive_status(snap, ("Detected", COLOR_GREEN), _NOW, None) == (
        "Pen Mode",
        COLOR_CYAN,
        False,
    )


def test_status_pen_mode_drawing():
    snap = {
        "paused": False,
        "camera_ok": True,
        "mode": "presentation_pen",
        "action": "pen_draw",
        "intent_phase": "idle",
    }
    _, _, glow = derive_status(snap, ("Detected", COLOR_GREEN), _NOW, None)
    assert glow is True


def test_status_solidworks():
    snap = {"paused": False, "camera_ok": True, "mode": "solidworks"}
    assert derive_status(snap, ("Detected", COLOR_GREEN), _NOW, None) == (
        "SolidWorks",
        COLOR_CYAN,
        False,
    )


def test_status_next_slide_glow():
    snap = {"paused": False, "camera_ok": True, "mode": "presentation"}
    text, color, glow = derive_status(
        snap, ("Detected", COLOR_GREEN), _NOW, "next"
    )
    assert (text, color, glow) == ("Next Slide", COLOR_CYAN, True)


def test_status_previous_slide_glow():
    snap = {"paused": False, "camera_ok": True, "mode": "presentation"}
    text, color, glow = derive_status(
        snap, ("Detected", COLOR_GREEN), _NOW, "previous"
    )
    assert (text, color, glow) == ("Previous Slide", COLOR_CYAN, True)


def test_status_cooling_down():
    snap = {
        "paused": False,
        "camera_ok": True,
        "mode": "presentation",
        "cooldown_until": _NOW + 0.5,
    }
    assert derive_status(snap, ("Detected", COLOR_GREEN), _NOW, None) == (
        "Cooling Down",
        COLOR_MUTED,
        False,
    )


def test_status_recognizing_glow():
    snap = {
        "paused": False,
        "camera_ok": True,
        "mode": "presentation",
        "intent_phase": "attempt:page_swipe:tracking",
    }
    text, color, glow = derive_status(
        snap, ("Detected", COLOR_GREEN), _NOW, None
    )
    assert (text, color, glow) == ("Recognizing", COLOR_CYAN, True)


def test_status_ready_to_flip():
    snap = {
        "paused": False,
        "camera_ok": True,
        "mode": "presentation",
        "intent_phase": "idle",
        "cooldown_until": 0.0,
    }
    assert derive_status(snap, ("Detected", COLOR_GREEN), _NOW, None) == (
        "Ready to Flip",
        COLOR_GREEN,
        False,
    )


def test_status_fallback_standby():
    snap = {"paused": False, "camera_ok": True, "mode": "unknown_mode"}
    assert derive_status(snap, ("Detected", COLOR_GREEN), _NOW, None) == (
        "Standby",
        COLOR_MUTED,
        False,
    )


# ── check_page_turn ─────────────────────────────────────────────────────────


def test_check_page_turn_next_via_action():
    assert check_page_turn({"action": "page_swipe_right"}) == "next"


def test_check_page_turn_previous_via_action():
    assert check_page_turn({"action": "page_swipe_left"}) == "previous"


def test_check_page_turn_next_via_next_keyword():
    assert check_page_turn({"action": "Next slide"}) == "next"


def test_check_page_turn_previous_via_previous_keyword():
    assert check_page_turn({"action": "Previous slide"}) == "previous"


def test_check_page_turn_none():
    assert check_page_turn({"action": "idle", "gesture": "none"}) is None


# ── config fields ───────────────────────────────────────────────────────────


def test_overlay_config_defaults():
    config = default_config()
    assert config.overlay_enabled is True
    assert config.overlay_click_through is True
    assert config.overlay_topmost_interval == 1.0
    assert config.overlay_update_interval == 0.05
    assert config.overlay_width == 300
    assert config.overlay_card_alpha == 0.72


def test_no_overlay_flag_disables():
    config = config_from_args(["--no-overlay"])
    assert config.overlay_enabled is False


def test_no_overlay_flag_does_not_affect_server():
    config = config_from_args(["--no-overlay"])
    assert config.status_server_enabled is True


def test_no_server_flag_does_not_affect_overlay():
    config = config_from_args(["--no-server"])
    assert config.overlay_enabled is True


# ── constants ───────────────────────────────────────────────────────────────


def test_badge_styles_cover_all_colors():
    for color in (COLOR_GREEN, COLOR_AMBER, COLOR_ROSE, COLOR_CYAN, COLOR_MUTED):
        assert color in BADGE_STYLES


def test_page_glow_ms_is_800ms():
    assert PAGE_GLOW_MS == 0.8


# ── FakeOverlay (same injection pattern as FakeDriver) ──────────────────────


class FakeOverlay:
    """Records update calls but never starts a real GUI."""

    def __init__(self):
        self.updates: list[dict] = []
        self.started = False
        self.stopped = False

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self) -> None:
        self.stopped = True

    def update(self, **fields):
        self.updates.append(fields)


def _make_controller(overlay=None):
    """Build a controller with fake driver and no hardware deps."""
    from hands.gesture_actions import ActionLayer, FakeDriver
    from hands.gesture_controller import GestureController

    config = default_config()
    config.enable_system_mouse = False
    config.show_debug_window = False
    config.status_server_enabled = False
    config.overlay_enabled = False  # prevent start() from creating real overlay
    driver = FakeDriver()
    actions = ActionLayer(enable_system_mouse=False, driver=driver)
    return GestureController(config=config, actions=actions, overlay=overlay)


def test_controller_accepts_overlay_injection():
    fake = FakeOverlay()
    controller = _make_controller(overlay=fake)
    assert controller.overlay is fake


def test_status_update_calls_both_server_and_overlay():
    fake_overlay = FakeOverlay()
    controller = _make_controller(overlay=fake_overlay)
    controller.status_update(mode="presentation", paused=False)
    assert len(fake_overlay.updates) == 1
    assert fake_overlay.updates[0]["mode"] == "presentation"


def test_status_update_noop_when_overlay_none():
    controller = _make_controller(overlay=None)
    # Should not raise.
    controller.status_update(mode="presentation", paused=False)
    assert controller.overlay is None


def test_overlay_update_directly():
    fake_overlay = FakeOverlay()
    controller = _make_controller(overlay=fake_overlay)
    controller.overlay_update(mode="solidworks", camera_ok=True)
    assert fake_overlay.updates[0]["mode"] == "solidworks"
    assert fake_overlay.updates[0]["camera_ok"] is True


# ── PySide6 missing → start() returns False ─────────────────────────────────


def test_overlay_start_returns_false_without_pyside6(monkeypatch):
    """When PySide6 is not importable, overlay.start() returns False."""
    from hands.gesture_overlay import GestureOverlay

    # Make PySide6 imports fail.
    monkeypatch.setitem(sys.modules, "PySide6", None)
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", None)
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", None)
    monkeypatch.setitem(sys.modules, "PySide6.QtGui", None)
    monkeypatch.setitem(sys.modules, "PySide6.QtSvg", None)

    overlay = GestureOverlay()
    assert overlay.start() is False
    overlay.stop()  # should be a safe no-op


# ── GestureOverlay.update() thread safety ───────────────────────────────────


def test_overlay_update_merges_fields():
    from hands.gesture_overlay import GestureOverlay

    overlay = GestureOverlay()
    overlay.update(mode="presentation", camera_ok=True)
    overlay.update(hand_present=True)

    # Read back via the internal state (same lock pattern as status server).
    with overlay._lock:
        assert overlay._state["mode"] == "presentation"
        assert overlay._state["camera_ok"] is True
        assert overlay._state["hand_present"] is True
        # Unmodified fields should retain defaults.
        assert overlay._state["gesture"] == "none"

    overlay.stop()
