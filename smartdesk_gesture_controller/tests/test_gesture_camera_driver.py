"""Regression tests for the optional camera driver integration.

These tests do not require a real camera; they only verify that
``GestureController`` uses the ``create_camera`` factory and respects
external ``cap`` ownership.
"""

import pytest
from hands.gesture_controller import GestureController
from hands.gesture_config import default_config


def _minimal_config(camera_driver: str = "industrial") -> object:
    """Return a config suitable for controller unit tests."""
    config = default_config()
    config.camera_driver = camera_driver
    config.show_debug_window = False
    config.status_server_enabled = False
    config.enable_system_mouse = False
    config.enable_hotkeys = False
    config.record_gestures = False
    return config


def test_camera_driver_external_cap_is_not_created_or_released():
    config = _minimal_config(camera_driver="opencv")

    class FakeCap:
        released = False

        def read(self):
            return False, None

        def release(self):
            self.released = True

    cap = FakeCap()
    controller = GestureController(config=config, cap=cap)

    assert controller._owns_cap is False
    assert controller._cap is cap

    controller._open_camera()
    assert controller._camera_instance is cap

    controller._shutdown()
    assert cap.released is False
    assert controller._cap is None
    assert controller._camera_instance is None


def test_camera_driver_open_camera_uses_factory(monkeypatch):
    config = _minimal_config(camera_driver="industrial")

    created = []

    def fake_create_camera(cfg):
        created.append(cfg.camera_driver)

        class FakeCam:
            def read(self):
                return False, None

            def release(self):
                pass

        return FakeCam()

    monkeypatch.setattr("hands.gesture_controller.create_camera", fake_create_camera)

    controller = GestureController(config=config)
    controller._open_camera()
    assert created == ["industrial"]
    assert controller._cap is controller._camera_instance


def test_camera_driver_opencv_factory_selection(monkeypatch):
    config = _minimal_config(camera_driver="opencv")

    created = []

    def fake_create_camera(cfg):
        created.append(cfg.camera_driver)

        class FakeCam:
            def read(self):
                return False, None

            def release(self):
                pass

        return FakeCam()

    monkeypatch.setattr("hands.gesture_controller.create_camera", fake_create_camera)

    controller = GestureController(config=config)
    controller._open_camera()
    assert created == ["opencv"]
    assert controller._cap is controller._camera_instance
