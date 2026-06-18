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


class GestureController:
    """Owns the camera, recognizer, state, actions and status server."""

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
        try:
            self._open_camera()
        except Exception:
            logger.exception("failed to open camera %s", self.config.camera_index)
            self._shutdown()
            return 2

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
            self._render_debug(img, result, now)
            cv2.imshow("SmartDesk Gesture Control", img)
            self._pin_debug_window_once("SmartDesk Gesture Control")

        self.status_server_update(
            mode=result.mode,
            gesture=hand_input.gesture.value,
            action=result.note,
            paused=self.state.paused,
            fps=self._compute_fps(now),
        )

    # ── intent dispatch ────────────────────────────────────────────────────
    def _dispatch_intents(self, intents: list) -> None:
        for intent in intents:
            self._apply_intent(intent)

    def _apply_intent(self, intent: ActionIntent) -> None:
        kind = intent.kind
        if kind == "move":
            x, y = intent.args
            self.actions.move_to(x, y)
        elif kind == "click":
            self.actions.left_click()
        elif kind == "mouse_down":
            x, y = (intent.args + (None, None))[:2]
            self.actions.mouse_down(x, y)
        elif kind == "mouse_up":
            x, y = (intent.args + (None, None))[:2]
            self.actions.mouse_up(x, y)
        elif kind == "press":
            self.actions.press(intent.args[0])
        elif kind == "hotkey":
            self.actions.hotkey(*intent.args)
        elif kind == "release_all":
            self.actions.release_all()
        else:  # pragma: no cover - defensive
            logger.warning("unknown intent kind: %s", kind)

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
    def _render_debug(self, img, result: StepResult, now: float) -> None:
        import cv2

        fps = self._compute_fps(now)
        cv2.putText(img, f"FPS: {int(fps)}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
        mode_text = f"[{result.mode.upper()}]{' (PAUSED)' if self.state.paused else ''}"
        cv2.putText(img, mode_text, (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(img, result.note[:60], (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
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
        if self.config.show_debug_window:
            print(f"  quit via window:  press '{self.config.exit_key}'")
        print("Gestures:")
        print("  presentation: open palm swipe left/right = prev/next, fist = standby")
        print("  mouse:        single finger = move, pinch = click,")
        print("                two finger (hold) = drag, fist = exit mode")
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
