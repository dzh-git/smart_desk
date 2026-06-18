"""Configuration for the standalone gesture-control process.

All tunable parameters live here as a single dataclass so the controller,
state machine, action layer and status server can be constructed from one
object. ``default_config()`` returns values ported from ``hands/test2.py``
with the new safety knobs (hand-loss timeout, dry-run mode, status server)
added on top.

CLI overrides are resolved in ``config_from_args``; the package never reads
``sys.argv`` at import time so the modules stay import-safe for unit tests.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field, replace
from typing import Tuple


# Modes are an explicit union so the state machine can validate transitions
# and the SolidWorks stub can refuse to run until its second phase lands.
MODE_STANDBY = "standby"
MODE_PRESENTATION = "presentation"
MODE_MOUSE = "mouse"
MODE_SOLIDWORKS = "solidworks"
VALID_MODES = (MODE_STANDBY, MODE_PRESENTATION, MODE_MOUSE, MODE_SOLIDWORKS)


@dataclass
class GestureConfig:
    """All knobs for one gesture-control process instance."""

    # ── Camera ──────────────────────────────────────────────────────────────
    camera_index: int = 0
    cam_width: int = 640
    cam_height: int = 320

    # ── Screen mapping region (camera px → screen px) ───────────────────────
    # Kept as a margin inside the camera frame so the cursor does not stick
    # to the very edges, matching the reference implementation.
    map_margin: int = 50

    # ── Timing / cooldowns (seconds unless noted) ───────────────────────────
    wave_cooldown: float = 1.0          # between two slide gestures
    wave_threshold: float = 10.0        # min horizontal delta (camera px) to count as a wave
    drag_cooldown: float = 0.3          # stabilization before entering drag mode
    fist_exit_cooldown: float = 1.0     # between two fist-exit triggers
    single_cooldown: float = 0.25       # stabilization before single-finger mouse mode
    click_cooldown: float = 0.35        # anti-bounce for pinch click
    hand_loss_timeout: float = 1.0      # release mouse + back to standby after this

    # ── Mouse movement ──────────────────────────────────────────────────────
    smoothening: float = 1.0            # 1 = no extra smoothing (matches reference)
    mouse_fps: int = 20                 # throttle pyautogui.moveTo calls
    pinch_click_distance: float = 35.0  # camera px between thumb tip(4) and index tip(8)

    # ── Behavior / safety switches ──────────────────────────────────────────
    initial_mode: str = MODE_STANDBY
    enable_system_mouse: bool = True    # False = dry-run, recognize but never control
    show_debug_window: bool = True      # cv2.imshow window
    debug_window_topmost: bool = True   # win32gui HWND_TOPMOST on Windows
    pause_on_start: bool = True         # begin paused; requires explicit activation
    exit_key: str = "q"                 # key inside the cv2 window to quit

    # ── Global hotkeys (best-effort via pynput; falls back to cv2-only) ─────
    hotkey_toggle_pause: str = "<ctrl>+<alt>+g"
    hotkey_emergency_exit: str = "<ctrl>+<alt>+q"

    # ── Status broadcast server ─────────────────────────────────────────────
    status_server_enabled: bool = True
    status_server_host: str = "127.0.0.1"
    status_server_port: int = 8765
    status_broadcast_interval: float = 0.2  # seconds between broadcasts

    # ── MediaPipe Hands ─────────────────────────────────────────────────────
    max_num_hands: int = 1
    min_detection_confidence: float = 0.7
    min_tracking_confidence: float = 0.5

    # Derived (filled lazily; not set by argparse)
    screen_size: Tuple[int, int] = field(default=(0, 0))

    def map_region(self) -> Tuple[int, int, int, int]:
        """Return (x_start, x_end, y_start, y_end) of the screen-mapping box."""
        m = self.map_margin
        return (
            m,
            max(m + 1, self.cam_width - m),
            m,
            max(m + 1, self.cam_height - m),
        )

    @property
    def mouse_frame_interval(self) -> float:
        return 1.0 / max(1, self.mouse_fps)


def default_config() -> GestureConfig:
    """Factory used by tests and the CLI entry point."""
    return GestureConfig()


def resolve_screen_size(config: GestureConfig) -> GestureConfig:
    """Populate ``screen_size`` from pyautogui if available.

    Kept separate from ``default_config`` so unit tests can construct a config
    without importing pyautogui (which triggers display initialization).
    """
    try:
        import pyautogui

        size = pyautogui.size()  # (width, height)
        return replace(config, screen_size=(int(size[0]), int(size[1])))
    except Exception:
        # Fall back to a common resolution; the controller will warn.
        return replace(config, screen_size=(1920, 1080))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hands.gesture_controller",
        description="SmartDesk local gesture controller (standalone process).",
    )
    parser.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    parser.add_argument(
        "--mode",
        choices=(MODE_PRESENTATION, MODE_MOUSE),
        default=MODE_MOUSE,
        help="active control mode on startup after leaving standby (default mouse)",
    )
    parser.add_argument(
        "--no-mouse",
        action="store_true",
        help="dry-run: recognize gestures but never touch the system mouse/keyboard",
    )
    parser.add_argument(
        "--no-debug",
        action="store_true",
        help="disable the cv2 debug window",
    )
    parser.add_argument(
        "--no-server",
        action="store_true",
        help="disable the ws://127.0.0.1:8765 status broadcast server",
    )
    parser.add_argument(
        "--no-pause-on-start",
        action="store_true",
        help="start already active instead of paused in standby",
    )
    return parser


def config_from_args(argv: list[str] | None = None) -> GestureConfig:
    """Build a config from CLI args. Used by ``__main__`` only."""
    args = build_arg_parser().parse_args(argv)
    config = default_config()
    config.camera_index = args.camera
    config.initial_mode = args.mode
    config.enable_system_mouse = not args.no_mouse
    config.show_debug_window = not args.no_debug
    config.status_server_enabled = not args.no_server
    config.pause_on_start = not args.no_pause_on_start
    return config
