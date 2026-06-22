"""Main controller facade — wires recognition → state → actions, runs the loop.

This is the only module that touches the camera (cv2) and the global hotkey
listener (pynput, with a cv2-only fallback). Everything else is injected, so
the safety guarantees (release on exit, release on exception, release on
hand-loss) all funnel through :meth:`GestureController._shutdown`.

Run as a standalone process:

    python -m hands.gesture_controller
    python -m hands.gesture_controller --mode presentation --no-debug

Safety contract:
    1. Starts in standby/paused — control must be explicitly activated.
    2. ``Ctrl+Alt+G`` toggles pause; ``Ctrl+Alt+Q`` (or the ``q`` key in the
       debug window) quits. All exit paths call ``_shutdown`` which releases
       every held mouse button.
    3. Any unhandled exception in the frame loop triggers ``release_all`` and
       a controlled exit rather than leaving the cursor held.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from .gesture_actions import ActionLayer
from .gesture_config import (
    GestureConfig,
    MODE_PRESENTATION,
    MODE_STANDBY,
    config_from_args,
    default_config,
    resolve_screen_size,
)
from .gesture_recognition import HandRecognizer
from .gesture_state import ActionIntent, GestureState, StepResult
from .gesture_status_server import GestureStatusServer

logger = logging.getLogger("hands.controller")

# Model files that must exist in the project root for offline demo.
_REQUIRED_MODEL_FILES = ("hand_landmarker.task",)


def check_model_files(
    project_root: Optional[str] = None,
    use_gesture_recognizer: bool = True,
) -> list:
    """Check that required model files exist in the project root.

    Returns a list of missing required model file paths (empty if all present).
    The caller is responsible for printing/logging a clear error; this function
    only reports missing paths so messages are not duplicated between main()
    and start().

    Phase 8: when ``use_gesture_recognizer`` is True (the default),
    ``gesture_recognizer.task`` is also required.  When False, only
    ``hand_landmarker.task`` is checked.
    """
    if project_root is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    missing = []
    for fname in _REQUIRED_MODEL_FILES:
        path = os.path.join(project_root, fname)
        if not os.path.exists(path):
            missing.append(path)
    if use_gesture_recognizer:
        gr_path = os.path.join(project_root, "gesture_recognizer.task")
        if not os.path.exists(gr_path):
            missing.append(gr_path)
    return missing


class GestureController:
    """Owns the camera, recognizer, state, actions and status server."""

    # Debug window title (kept as a constant so every cv2 call uses the same name).
    _DEBUG_WINDOW_NAME = "SmartDesk Gesture Control"

    def __init__(
        self,
        config: Optional[GestureConfig] = None,
        *,
        recognizer: Optional[HandRecognizer] = None,
        actions: Optional[ActionLayer] = None,
        status_server: Optional[GestureStatusServer] = None,
        cap: Optional[Any] = None,
    ) -> None:
        self.config = config or default_config()
        # Resolve screen size once (pyautogui import deferred inside the helper).
        self.config = resolve_screen_size(self.config)

        self.recognizer = recognizer or HandRecognizer(
            max_num_hands=self.config.max_num_hands,
            min_detection_confidence=self.config.min_detection_confidence,
            min_tracking_confidence=self.config.min_tracking_confidence,
            use_gesture_recognizer=self.config.use_gesture_recognizer,
            min_gesture_confidence=self.config.min_gesture_confidence,
            fallback_to_rule_gestures=self.config.fallback_to_rule_gestures,
            gesture_recognizer_model_path=self.config.gesture_recognizer_model_path,
        )
        self.actions = actions or ActionLayer(enable_system_mouse=self.config.enable_system_mouse)
        self.state = GestureState(self.config)
        self.status_server = status_server  # built in start() if enabled

        # External resources we own (and must release in _shutdown).
        self._cap: Optional[Any] = cap
        self._owns_cap = cap is None
        self._hotkey_listener: Optional[Any] = None

        self._running = False
        self._prev_fps_time: float = 0.0
        self._debug_window_topmost_set = False

    # ── public lifecycle ───────────────────────────────────────────────────
    def start(self) -> int:
        """Open resources and enter the frame loop. Returns process exit code."""
        # ── Pre-flight: check model files exist (spec §5, no network at demo) ──
        missing = check_model_files(use_gesture_recognizer=self.config.use_gesture_recognizer)
        if missing:
            for m in missing:
                fname = os.path.basename(m)
                print(f"[Error] Model file not found: {fname}")
                print(f"        Expected path: {m}")
                if fname == "gesture_recognizer.task":
                    print(f"        Place gesture_recognizer.task in the project root,")
                    print(f"        or set use_gesture_recognizer=False to use rule-based fallback only.")
                else:
                    print(f"        Please place the model file in the project root before running the demo.")
                logger.error("Model file not found: %s", fname)
            return 3

        try:
            self._open_camera()
        except Exception:
            logger.exception("failed to open camera %s", self.config.camera_index)
            self._shutdown()
            return 2

        # Create a resizable debug window with an enlarged initial size so the
        # user can clearly observe hand landmarks and gesture text (spec §13).
        if self.config.show_debug_window:
            import cv2

            cv2.namedWindow(self._DEBUG_WINDOW_NAME, cv2.WINDOW_NORMAL)
            init_w = int(self.config.camera_width * self.config.debug_window_scale)
            init_h = int(self.config.camera_height * self.config.debug_window_scale)
            cv2.resizeWindow(self._DEBUG_WINDOW_NAME, init_w, init_h)

        if self.config.status_server_enabled:
            self.status_server = GestureStatusServer(
                host=self.config.status_server_host,
                port=self.config.status_server_port,
                broadcast_interval=self.config.status_broadcast_interval,
            )
            if not self.status_server.start():
                # Server is optional — keep running without it.
                self.status_server = None
        self.status_server_update(
            camera_ok=True,
            control_enabled=self.config.enable_system_mouse,
            mode=self.state.mode,
            paused=self.state.paused,
        )

        self._install_hotkeys()

        logger.info(
            "gesture controller started — mode=%s mouse=%s debug=%s server=%s",
            self.state.mode,
            self.config.enable_system_mouse,
            self.config.show_debug_window,
            self.status_server is not None,
        )
        self._print_banner()

        try:
            self._running = True
            self._loop()
        except KeyboardInterrupt:
            logger.info("interrupted by user")
        except Exception:
            logger.exception("frame loop crashed")
        finally:
            self._shutdown()
        return 0

    def stop(self) -> None:
        """Request a graceful stop from another thread."""
        self._running = False

    # ── the loop ───────────────────────────────────────────────────────────
    def _loop(self) -> None:
        cap = self._cap
        assert cap is not None
        while self._running:
            ok, img = cap.read()
            if not ok:
                logger.warning("camera read failed; exiting loop")
                break

            now = time.time()
            try:
                self._process_frame(img, now)
            except Exception:
                # Never let a single bad frame kill the loop; release any held
                # state so the cursor can't get stuck, then continue.
                logger.exception("frame processing error — releasing and continuing")
                self._safe_release()

            if self._check_exit_key():
                break

    def _process_frame(self, img, now: float) -> None:
        # Mirror + RGB, matching reference impl.
        import cv2

        img = cv2.flip(img, 1)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        frame_result = self.recognizer.process_frame(img_rgb)
        hand_input = self.recognizer.to_hand_input(frame_result)

        result: StepResult = self.state.step(hand_input, now)
        self._dispatch_intents(result.intents)

        # Debug window + status broadcast.
        if self.config.show_debug_window:
            self.recognizer.draw(img, frame_result)
            self._render_debug(img, result, now, frame_result)
            display_img = self._scale_for_display(img)
            cv2.imshow(self._DEBUG_WINDOW_NAME, display_img)
            self._pin_debug_window_once(self._DEBUG_WINDOW_NAME)

        self.status_server_update(
            mode=result.mode,
            gesture=hand_input.gesture.value,
            action=result.note,
            paused=self.state.paused,
            fps=self._compute_fps(now),
        )

    # ── intent dispatch ────────────────────────────────────────────────────
    def _dispatch_intents(self, intents: list) -> None:
        """Execute all intents via the ActionLayer's unified ``execute`` entry.

        Phase 3: switched from the manual ``_apply_intent`` switch to
        ``ActionLayer.execute`` so every intent type (move_to, move_rel,
        scroll, key_down, key_up, click, status, noop …) is handled
        correctly, not just the legacy subset.
        """
        self.actions.execute(intents)

    def _apply_intent(self, intent: ActionIntent) -> None:
        """Execute a single intent (kept for backward compat / tests)."""
        self.actions.execute(intent)

    # ── safety helpers ─────────────────────────────────────────────────────
    def _safe_release(self) -> None:
        """Release mouse via both the state machine and the action layer."""
        try:
            intents = self.state.force_release()
            self._dispatch_intents(intents)
        except Exception:  # pragma: no cover - defensive
            logger.exception("force_release failed")
        try:
            self.actions.release_all()
        except Exception:  # pragma: no cover - defensive
            logger.exception("actions.release_all failed")

    def _shutdown(self) -> None:
        """Single exit path: release everything, close resources."""
        logger.info("shutting down gesture controller")
        self._safe_release()
        try:
            self.recognizer.close()
        except Exception:  # pragma: no cover
            logger.exception("recognizer close failed")

        if self._owns_cap and self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # pragma: no cover
                logger.exception("camera release failed")
        self._cap = None

        if self.config.show_debug_window:
            try:
                import cv2

                cv2.destroyAllWindows()
            except Exception:  # pragma: no cover
                pass

        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception:  # pragma: no cover
                pass
            self._hotkey_listener = None

        if self.status_server is not None:
            try:
                self.status_server.update(action="controller exited", paused=True)
                self.status_server.stop()
            except Exception:  # pragma: no cover
                logger.exception("status server stop failed")
            self.status_server = None

    # ── hotkeys ────────────────────────────────────────────────────────────
    def _install_hotkeys(self) -> None:
        """Install global Ctrl+Alt+G (pause) and Ctrl+Alt+Q (exit) via pynput.

        Falls back silently to cv2-only mode if pynput is unavailable; in that
        case the user can still quit with the ``q`` key in the debug window.
        """
        try:
            from pynput import keyboard
        except ImportError:
            logger.warning("pynput not installed — global hotkeys disabled; use 'q' to quit")
            return
        except Exception:  # pragma: no cover - environment dependent
            logger.exception("pynput import failed — global hotkeys disabled")
            return

        try:
            pause_combo = keyboard.HotKey(
                keyboard.HotKey.parse(self.config.hotkey_toggle_pause), self._on_toggle_pause
            )
            exit_combo = keyboard.HotKey(
                keyboard.HotKey.parse(self.config.hotkey_emergency_exit), self._on_emergency_exit
            )

            def on_press(key):
                pause_combo.press(self._canonical(key))
                exit_combo.press(self._canonical(key))

            listener = keyboard.Listener(on_press=on_press)
            listener.daemon = True
            listener.start()
            self._hotkey_listener = listener
            logger.info("global hotkeys active: %s / %s", self.config.hotkey_toggle_pause, self.config.hotkey_emergency_exit)
        except Exception:  # pragma: no cover - environment dependent
            logger.exception("failed to install hotkey listener — use 'q' to quit")

    @staticmethod
    def _canonical(key) -> Any:
        # pynput exposes either a KeyCode (chars) or a special Key; the HotKey
        # helper wants the KeyCode. For special keys we pass them through.
        try:
            from pynput import keyboard

            if isinstance(key, keyboard.KeyCode):
                return key
            return keyboard.KeyCode.from_char(getattr(key, "name", "") or "")
        except Exception:  # pragma: no cover - defensive
            return key

    def _on_toggle_pause(self) -> None:
        paused = self.state.toggle_pause()
        action = "paused" if paused else "resumed"
        logger.info("hotkey: control %s", action)
        if paused:
            self._safe_release()
        self.status_server_update(paused=paused, action=action)

    def _on_emergency_exit(self) -> None:
        logger.info("hotkey: emergency exit requested")
        self.stop()

    # ── debug rendering ────────────────────────────────────────────────────
    def _scale_for_display(self, img):
        """Scale the debug image by ``debug_window_scale`` for easier observation.

        Landmarks and text are drawn on the original-resolution image first, then
        the whole frame is resized.  This keeps the drawing logic unchanged while
        making everything (including the gesture text) larger on screen.
        """
        import cv2

        scale = self.config.debug_window_scale
        if scale <= 1.0:
            return img
        h, w = img.shape[:2]
        return cv2.resize(img, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_LINEAR)

    def _render_debug(self, img, result: StepResult, now: float, frame_result=None) -> None:
        import cv2

        fps = self._compute_fps(now)
        cv2.putText(img, f"FPS: {int(fps)}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
        mode_text = f"[{result.mode.upper()}]{' (PAUSED)' if self.state.paused else ''}"
        cv2.putText(img, mode_text, (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        # ── Current recognized gesture (always shown, even when paused) ────
        di = result.debug_info
        current_gesture = di.get("current_gesture", "none")
        gesture_color = (0, 255, 0) if current_gesture != "none" else (120, 120, 120)
        cv2.putText(img, f"gesture: {current_gesture}", (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, gesture_color, 2)

        cv2.putText(img, result.note[:60], (10, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # ── Phase 8: gesture recognition source / confidence / raw name ────
        y_offset = 150
        if frame_result is not None:
            source = frame_result.gesture_source or "none"
            conf = frame_result.gesture_confidence
            raw = frame_result.raw_gesture
            if source != "none" or conf is not None or raw is not None:
                cv2.putText(img, f"src: {source}", (10, y_offset),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 255), 1)
                y_offset += 20
                if conf is not None:
                    cv2.putText(img, f"conf: {conf:.2f}", (10, y_offset),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 255), 1)
                    y_offset += 20
                if raw is not None and raw != current_gesture:
                    cv2.putText(img, f"raw: {raw}", (10, y_offset),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 255), 1)
                    y_offset += 20

        # ── Phase 6: dry-run calibration info (spec §7) ────────────────────
        # stable_duration
        stable = di.get("stable_duration", 0.0)
        cv2.putText(img, f"stable: {stable:.2f}s", (10, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        y_offset += 20
        # active_continuous_action
        action = di.get("active_continuous_action", None)
        if action:
            cv2.putText(img, f"action: {action}", (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
            y_offset += 20
        # mouse / middle / shift state
        flags = []
        if di.get("is_left_mouse_down"):
            flags.append("L-down")
        if di.get("is_middle_mouse_down"):
            flags.append("M-down")
        if di.get("is_shift_down"):
            flags.append("Shift-down")
        if di.get("is_pinching"):
            flags.append("Pinch")
        if flags:
            cv2.putText(img, " | ".join(flags), (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 100, 255), 1)
            y_offset += 20

        # Extra calibration fields (phase 7: pinch distance, swipe dx/dy, lost time, cooldown).
        if di.get("pinch_distance") is not None:
            cv2.putText(img, f"pinch: {di['pinch_distance']:.3f}", (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            y_offset += 20
        swipe_dx = di.get("swipe_dx", 0.0)
        swipe_dy = di.get("swipe_dy", 0.0)
        if swipe_dx or swipe_dy:
            cv2.putText(img, f"swipe dx/dy: {swipe_dx:.2f}/{swipe_dy:.2f}", (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            y_offset += 20
        lost_duration = di.get("hand_lost_duration", 0.0)
        if lost_duration > 0.0:
            cv2.putText(img, f"lost: {lost_duration:.1f}s", (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            y_offset += 20
        cooldown_until = di.get("cooldown_until", 0.0)
        if cooldown_until > now:
            cv2.putText(img, f"cooldown: {max(0.0, cooldown_until - now):.2f}s", (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            y_offset += 20

        if not self.config.enable_system_mouse:
            cv2.putText(img, "DRY-RUN (no system mouse)", (10, img.shape[0] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

        # Map region overlay.
        x1, x2, y1, y2 = self.config.map_region()
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 255), 2)

    def _pin_debug_window_once(self, window_name: str) -> None:
        if self._debug_window_topmost_set or not self.config.debug_window_topmost:
            return
        try:
            import os

            if os.name != "nt":
                self._debug_window_topmost_set = True
                return
            import win32con
            import win32gui

            hwnd = win32gui.FindWindow(None, window_name)
            if hwnd:
                win32gui.SetWindowPos(
                    hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
                )
                self._debug_window_topmost_set = True
        except ImportError:
            logger.warning("pywin32 not installed — debug window will not be topmost")
            self._debug_window_topmost_set = True
        except Exception:  # pragma: no cover - environment dependent
            self._debug_window_topmost_set = True

    # ── exit key ───────────────────────────────────────────────────────────
    def _check_exit_key(self) -> bool:
        if not self.config.show_debug_window:
            return False
        try:
            import cv2

            key = cv2.waitKey(1) & 0xFF
            if key == ord(self.config.exit_key):
                logger.info("exit key pressed: %s", self.config.exit_key)
                return True
        except Exception:  # pragma: no cover - environment dependent
            pass
        return False

    # ── camera ─────────────────────────────────────────────────────────────
    def _open_camera(self) -> None:
        import cv2

        cap = cv2.VideoCapture(self.config.camera_index)
        cap.set(3, self.config.cam_width)
        cap.set(4, self.config.cam_height)
        if not cap.isOpened():
            raise RuntimeError(f"camera index {self.config.camera_index} could not be opened")
        self._cap = cap

    # ── misc ───────────────────────────────────────────────────────────────
    def _compute_fps(self, now: float) -> float:
        fps = 0.0
        if self._prev_fps_time and now > self._prev_fps_time:
            fps = 1.0 / (now - self._prev_fps_time)
        self._prev_fps_time = now
        return fps

    def status_server_update(self, **fields) -> None:
        if self.status_server is not None:
            try:
                self.status_server.update(**fields)
            except Exception:  # pragma: no cover - defensive
                logger.exception("status_server.update failed")

    def _print_banner(self) -> None:
        print("=" * 60)
        print("SmartDesk Gesture Controller")
        print(f"  mode on activate: {self.config.initial_mode}")
        print(f"  system mouse:     {'ENABLED' if self.config.enable_system_mouse else 'DRY-RUN'}")
        print(f"  debug window:     {'on' if self.config.show_debug_window else 'off'}")
        print(f"  status server:    {'ws://%s:%s' % (self.config.status_server_host, self.config.status_server_port) if self.status_server else 'off'}")
        print(f"  pause hotkey:     {self.config.hotkey_toggle_pause}")
        print(f"  exit hotkey:      {self.config.hotkey_emergency_exit}")
        gr_status = "on" if self.config.use_gesture_recognizer else "off (rule fallback)"
        print(f"  gesture recognizer: {gr_status}")
        if self.config.show_debug_window:
            print(f"  quit via window:  press '{self.config.exit_key}'")
        print("Gestures:")
        print("  presentation: open palm swipe left/right = prev/next, fist = standby")
        print("  mouse:        pointing up = move, pinch = click/drag,")
        print("                victory hold = scroll mode, thumb down = right click,")
        print("                fist = exit mode")
        print("  solidworks:   open palm = rotate, victory = pan, pinch = zoom,")
        print("                thumb up = fit, iloveyou = isometric, fist = exit")
        print("=" * 60)


def main(argv: Optional[list] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config = config_from_args(argv)
    controller = GestureController(config=config)
    return controller.start()


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
