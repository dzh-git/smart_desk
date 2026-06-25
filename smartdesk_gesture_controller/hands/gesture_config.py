"""Configuration for the standalone gesture-control process.

All tunable parameters live here as a single dataclass so the controller,
state machine, action layer and status server can be constructed from one
object.  ``default_config()`` returns values ported from ``hands/test2.py``
with the new safety knobs (hand-loss timeout, dry-run mode, status server)
added on top.

CLI overrides are resolved in ``config_from_args``; the package never reads
``sys.argv`` at import time so the modules stay import-safe for unit tests.

Phase 1 (CONFIG_SPEC.md):
    All spec-mandated parameters are now defined here with defaults.  Legacy
    field names (``cam_width``, ``wave_threshold``, ``smoothening`` …) are
    kept as properties that alias the new canonical names, so existing code
    (controller + state machine) continues to work without modification.
    New code should prefer the canonical names.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field, replace
from typing import Tuple


# Modes are an explicit union so the state machine can validate transitions.
# Phase 2 adds presentation_pen, mouse_scroll and paused per STATE_MACHINE_SPEC.
MODE_STANDBY = "standby"
MODE_PRESENTATION = "presentation"
MODE_PRESENTATION_PEN = "presentation_pen"
MODE_MOUSE = "mouse"
MODE_MOUSE_SCROLL = "mouse_scroll"
MODE_SOLIDWORKS = "solidworks"
MODE_PAUSED = "paused"
VALID_MODES = (
    MODE_STANDBY, MODE_PRESENTATION, MODE_PRESENTATION_PEN,
    MODE_MOUSE, MODE_MOUSE_SCROLL, MODE_SOLIDWORKS, MODE_PAUSED,
)
# Modes that the CLI --mode flag can pre-select (excludes sub-modes & paused).
CLI_MODES = (MODE_PRESENTATION, MODE_SOLIDWORKS)


@dataclass
class GestureConfig:
    """All knobs for one gesture-control process instance.

    Fields are grouped by category.  Where a legacy name and a spec name
    refer to the same concept, the canonical (spec) name is the dataclass
    field and the legacy name is exposed as a read-only property alias.
    """

    # ── Camera ──────────────────────────────────────────────────────────────
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30
    # Legacy alias kept for controller compat (controller reads cam_width/cam_height).
    map_margin: int = 50

    # ── Recognizer confidence ───────────────────────────────────────────────
    min_hand_detection_confidence: float = 0.7
    min_hand_presence_confidence: float = 0.6
    min_tracking_confidence: float = 0.5
    min_gesture_confidence: float = 0.65
    max_num_hands: int = 1

    # ── GestureRecognizer (Phase 8) ────────────────────────────────────────
    # When True, the recognition layer loads gesture_recognizer.task and uses
    # MediaPipe's official canned-gesture classification as the primary source
    # for static gestures.  Legacy landmark-rule classification is kept as a
    # fallback (see ``fallback_to_rule_gestures``).
    use_gesture_recognizer: bool = True
    gesture_recognizer_model_path: str = "gesture_recognizer.task"
    fallback_to_rule_gestures: bool = True

    # ── Timing / hold times (seconds) ───────────────────────────────────────
    hand_loss_timeout: float = 1.0      # release mouse + back to standby after this
    # NOTE: CONFIG_SPEC.md spells this "hand_lost_timeout"; existing code and
    # tests use "hand_loss_timeout".  We keep the code spelling for compat.
    start_presentation_hold: float = 1.5
    enter_mouse_hold: float = 1.0
    enter_solidworks_hold: float = 1.5
    exit_mode_hold: float = 0.8
    pen_mode_hold: float = 0.5
    erase_hold: float = 0.5
    right_click_hold: float = 0.5
    fit_view_hold: float = 0.5
    isometric_view_hold: float = 0.8

    # ── Cooldowns (seconds) ─────────────────────────────────────────────────
    page_turn_cooldown: float = 0.8     # between two slide gestures
    mode_switch_cooldown: float = 1.0
    click_cooldown: float = 0.35        # anti-bounce for pinch click
    right_click_cooldown: float = 0.5
    pen_toggle_cooldown: float = 0.6
    solidworks_view_cooldown: float = 0.8

    # ── Wave / swipe detection ──────────────────────────────────────────────
    # camera-px threshold (legacy, used by current state machine)
    wave_threshold: float = 10.0
    wave_cooldown: float = 1.0
    # Normalised thresholds (spec, for future state-machine rewrite)
    swipe_threshold_x: float = 0.18
    swipe_threshold_y_limit: float = 0.12
    swipe_time_window: float = 0.8
    # Phase 9: ILoveYou swipe threshold for mode switching.
    iloveyou_swipe_threshold_x: float = 0.22

    # ── Pinch ───────────────────────────────────────────────────────────────
    # Legacy: camera-px distance between thumb(4) and index(8) tips.
    pinch_click_distance: float = 35.0
    # Spec: normalised landmark distance (0–1).
    pinch_threshold: float = 0.045
    pinch_release_threshold: float = 0.065
    pinch_zoom_deadzone: float = 0.01

    # ── Mouse movement ──────────────────────────────────────────────────────
    smoothening: float = 1.0            # legacy (1 = no extra smoothing)
    mouse_smoothing: float = 0.35       # spec (0–1, higher = smoother)
    mouse_speed: float = 1.0
    mouse_max_step_px: int = 80
    mouse_fps: int = 20                 # throttle pyautogui.moveTo calls
    drag_cooldown: float = 0.3          # legacy: stabilization before entering drag
    drag_hold_time: float = 0.35        # spec: pinch hold before drag
    single_cooldown: float = 0.25       # legacy: stabilization before single-finger mouse
    click_max_movement_px: int = 25
    fist_exit_cooldown: float = 1.0     # legacy: between two fist-exit triggers

    # ── Scroll ──────────────────────────────────────────────────────────────
    scroll_threshold_y: float = 0.08
    scroll_amount: int = 5
    scroll_cooldown: float = 0.12
    invert_scroll: bool = False          # reverse scroll direction globally (mouse_scroll + solidworks zoom)

    # ── SolidWorks ──────────────────────────────────────────────────────────
    solidworks_drag_sensitivity: float = 1.2
    solidworks_zoom_sensitivity: float = 8.0
    solidworks_min_zoom_step: int = 1   # minimum scroll step per pinch delta (avoids amount=0)
    solidworks_deadzone: float = 0.01

    # ── Control-flow tracker (Phase 1, CONFIG_SPEC §6.6) ───────────────────
    # Candidate confirmation: official classifier must match at least
    # gesture_enter_frames out of the last gesture_enter_window_frames frames,
    # with per-frame confidence >= gesture_enter_confidence.
    gesture_enter_frames: int = 4
    gesture_enter_window_frames: int = 5
    # Grace frames for classification jitter while an attempt/session is active.
    gesture_keep_grace_frames: int = 6
    gesture_enter_confidence: float = 0.70
    gesture_keep_confidence: float = 0.45
    # Max continuous classification failure before cancelling attempt/session.
    intent_lost_timeout: float = 0.25
    # Min stable duration before ILoveYou mode-switch attempt enters armed.
    mode_arm_duration: float = 0.20
    # Max tracking time for mode-switch / page-turn attempts.
    # mode_swipe_timeout set to 3.0: gives ILoveYou swipe commits ample time.
    # page_swipe_timeout stays at 0.80 (Open_Palm swipes are faster).
    mode_swipe_timeout: float = 3.0
    page_swipe_timeout: float = 0.80
    # Landmark low-pass filter: weight of the new observation (0-1).
    landmark_smoothing: float = 0.45
    # Motion constraints (all in normalised coordinates).
    motion_deadzone: float = 0.015
    max_motion_step: float = 0.08      # max per-frame displacement
    max_motion_velocity: float = 1.5   # max normalised coords per second
    min_motion_duration: float = 0.12  # min dynamic action duration
    direction_consistency_frames: int = 3

    # ── Behavior / safety switches ──────────────────────────────────────────
    initial_mode: str = MODE_STANDBY
    enable_system_mouse: bool = True    # False = dry-run, recognize but never control
    dry_run: bool = False               # spec alias (if True, enable_system_mouse=False)
    show_debug_window: bool = True      # cv2.imshow window
    debug_window_topmost: bool = True   # win32gui HWND_TOPMOST on Windows
    debug_window_always_on_top: bool = True
    debug_window_scale: float = 1.5     # display scale factor (>1 enlarges the debug window for easier observation)
    show_landmarks: bool = True
    show_fps: bool = True
    show_action_log: bool = True
    pause_on_start: bool = False         # begin paused; requires explicit activation
    start_paused: bool = False          # spec alias for pause_on_start
    enable_hotkeys: bool = True
    exit_key: str = "q"                 # key inside the cv2 window to quit

    # ── Global hotkeys (best-effort via keyboard; falls back to cv2-only) ───
    hotkey_toggle_pause: str = "<ctrl>+<alt>+g"
    hotkey_emergency_exit: str = "<ctrl>+<alt>+q"

    # ── Gesture recording / replay ─────────────────────────────────────────
    record_gestures: bool = True            # enable recording in controller loop
    gesture_record_dir: str = "logs"              # diTruerectory for JSONL record files

    # ── Status broadcast server ─────────────────────────────────────────────
    status_server_enabled: bool = True
    status_server_host: str = "127.0.0.1"
    status_server_port: int = 8765
    status_broadcast_interval: float = 0.2  # seconds between broadcasts

    # Derived (filled lazily; not set by argparse)
    screen_size: Tuple[int, int] = field(default=(0, 0))

    # ── Legacy property aliases ─────────────────────────────────────────────
    @property
    def cam_width(self) -> int:
        return self.camera_width

    @cam_width.setter
    def cam_width(self, value: int) -> None:
        self.camera_width = value

    @property
    def cam_height(self) -> int:
        return self.camera_height

    @cam_height.setter
    def cam_height(self, value: int) -> None:
        self.camera_height = value

    @property
    def min_detection_confidence(self) -> float:
        """Legacy alias for ``min_hand_detection_confidence`` (controller compat)."""
        return self.min_hand_detection_confidence

    @min_detection_confidence.setter
    def min_detection_confidence(self, value: float) -> None:
        self.min_hand_detection_confidence = value

    @property
    def hand_lost_timeout(self) -> float:
        """Spec-canonical alias for ``hand_loss_timeout`` (CONFIG_SPEC spelling).

        The state machine internally prefers ``hand_lost_timeout`` per the
        spec; existing code/tests that read ``hand_loss_timeout`` keep working
        because the underlying dataclass field is still ``hand_loss_timeout``.
        """
        return self.hand_loss_timeout

    @hand_lost_timeout.setter
    def hand_lost_timeout(self, value: float) -> None:
        self.hand_loss_timeout = value

    # ── Derived helpers ─────────────────────────────────────────────────────
    def map_region(self) -> Tuple[int, int, int, int]:
        """Return (x_start, x_end, y_start, y_end) of the screen-mapping box."""
        m = self.map_margin
        return (
            m,
            max(m + 1, self.camera_width - m),
            m,
            max(m + 1, self.camera_height - m),
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
        choices=CLI_MODES,
        default=MODE_STANDBY,
        help="active control mode on startup after leaving standby (default standby)",
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
    parser.add_argument(
        "--start-unpaused",
        action="store_true",
        help="alias for --no-pause-on-start: start already active",
    )
    return parser


def config_from_args(argv: list[str] | None = None) -> GestureConfig:
    """Build a config from CLI args. Used by ``__main__`` only."""
    args = build_arg_parser().parse_args(argv)
    config = default_config()
    config.camera_index = args.camera
    config.initial_mode = args.mode
    config.enable_system_mouse = not args.no_mouse
    config.dry_run = args.no_mouse
    config.show_debug_window = not args.no_debug
    config.status_server_enabled = not args.no_server
    # Only override the dataclass defaults when the user explicitly requests
    # no-pause via CLI flags. Without these flags, keep the dataclass default
    # (pause_on_start=False) so double-clicking the .bat does not force pause.
    if args.no_pause_on_start or args.start_unpaused:
        config.pause_on_start = False
        config.start_paused = False
    return config
