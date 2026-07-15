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
    2. ``Ctrl+Alt+G`` toggles pause; ``Ctrl+Alt+Q`` quits.  Both use the
       ``keyboard`` library for global hotkeys.  If the backend fails, the
       cv2 debug window accepts ``p`` / ``Space`` to toggle pause and ``q`` /
       ``Esc`` to quit.
    3. Any unhandled exception in the frame loop triggers ``release_all`` and
       a controlled exit rather than leaving the cursor held.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from .display_agent_client import DisplayAgentClient, DisplayAgentResult
from .gesture_actions import ActionLayer
from .gesture_camera import create_camera
from .gesture_config import (
    GestureConfig,
    MODE_PRESENTATION,
    MODE_PRESENTATION_PEN,
    MODE_SOLIDWORKS,
    MODE_STANDBY,
    config_from_args,
    default_config,
    resolve_screen_size,
)
from .gesture_recognition import HandRecognizer
from .gesture_state import ActionIntent, GestureState, StepResult
from .gesture_status_server import GestureStatusServer
from .gesture_intent_tracker import (
    EVT_MODE_SWIPE_LEFT,
    EVT_MODE_SWIPE_RIGHT,
    GestureFrame,
    GestureIntentTracker,
    TrackerResult,
)
from .gesture_replay import GestureFrameRecorder

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
        display_agent_client: Optional[DisplayAgentClient] = None,
        status_server: Optional[GestureStatusServer] = None,
        overlay: Optional[Any] = None,
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
        self.display_agent_client = display_agent_client
        if self.display_agent_client is None and self.config.display_agent_enabled:
            self.display_agent_client = DisplayAgentClient(
                self.config.display_agent_url,
                self.config.display_agent_timeout_seconds,
            )
        self.state = GestureState(self.config)
        self.tracker = GestureIntentTracker(self.config)
        self.status_server = status_server  # built in start() if enabled
        self.overlay = overlay              # built in start() if enabled

        # External resources we own (and must release in _shutdown).
        self._cap: Optional[Any] = cap
        self._owns_cap = cap is None
        self._camera_instance: Optional[Any] = None
        self._hotkey_listener: Optional[Any] = None
        self._hotkey_backend: Optional[str] = None
        self._hotkey_handles: list = []

        self._running = False
        self._prev_fps_time: float = 0.0
        self._debug_window_topmost_set = False
        self._display_status = {
            "display_agent_online": False,
            "display_active_app": None,
            "display_target_app": self._app_for_mode(self.state.mode),
            "display_switch_state": (
                "unknown" if self.config.display_agent_enabled else "disabled"
            ),
            "display_switch_error": "",
            "display_switch_at": 0.0,
        }

        # Gesture frame recorder (only active when config.record_gestures=True).
        self.recorder = GestureFrameRecorder(self.config)
        if self.config.record_gestures:
            self.recorder.start()

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

        if self.config.overlay_enabled and self.overlay is None:
            from .gesture_overlay import GestureOverlay
            try:
                self.overlay = GestureOverlay(
                    click_through=self.config.overlay_click_through,
                    topmost_interval=self.config.overlay_topmost_interval,
                    update_interval=self.config.overlay_update_interval,
                    card_alpha=self.config.overlay_card_alpha,
                    width=self.config.overlay_width,
                    screen_size=self.config.screen_size,
                )
                if not self.overlay.start():
                    self.overlay = None
            except Exception:  # pragma: no cover - defensive
                logger.exception("overlay start failed; continuing without it")
                self.overlay = None

        self._probe_display_agent()
        self.status_update(
            camera_ok=True,
            control_enabled=self.config.enable_system_mouse,
            mode=self.state.mode,
            paused=self.state.paused,
            hand_present=False,
            hand_lost_duration=0.0,
            cooldown_until=0.0,
            intent_phase="idle",
            **self._display_status,
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
        # Allow a few consecutive read failures before giving up.  Industrial
        # cameras may need a short warm-up after StartGrabbing, and transient
        # USB/GigE frame drops should not kill the session immediately.
        max_failures = 10
        failures = 0
        while self._running:
            ok, img = cap.read()
            if not ok:
                failures += 1
                if failures >= max_failures:
                    logger.warning("camera read failed %d times; exiting loop", failures)
                    break
                logger.debug("camera read transient failure (%d/%d); retrying", failures, max_failures)
                time.sleep(0.01)
                continue
            failures = 0

            # tracker uses monotonic time for consistent interval
            # measurement; legacy state machine also receives it (compatible).
            now = time.monotonic()
            try:
                self._process_frame(img, now)
            except Exception:
                # Never let a single bad frame kill the loop; release any held
                # state so the cursor can't get stuck, then continue.
                logger.exception("frame processing error — releasing and continuing")
                self._safe_release()

            if self._handle_debug_keys():
                break

    def _process_frame(self, img, now: float) -> None:
        # Mirror + RGB, matching reference impl.
        import cv2

        img = cv2.flip(img, 1)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        frame_result = self.recognizer.process_frame(img_rgb)
        hand_input = self.recognizer.to_hand_input(frame_result)

        # Construct GestureFrame and feed to tracker (migrated path).
        gesture_frame = self.recognizer.to_gesture_frame(frame_result)
        tracker_result = self.tracker.update(gesture_frame, self.state.mode, now)

        # Track mode before step to detect post-step mode changes.
        mode_before = self.state.mode

        # Pass both HandInput (legacy path) and events (migrated path) to
        # the state machine.  The state machine prioritises event-path
        # intents for migrated gestures and falls back to HandInput for
        # non-migrated gestures (Closed_Fist, Victory HOLD, PINCH, etc.).
        result: StepResult = self.state.step(
            hand_input, now, events=tracker_result.events
        )
        self._dispatch_intents(result.intents)

        is_mode_swipe = any(
            event.type in (EVT_MODE_SWIPE_LEFT, EVT_MODE_SWIPE_RIGHT)
            for event in tracker_result.events
        )
        if is_mode_swipe and self.state.mode != mode_before:
            if not self._sync_display_mode_transition(mode_before, self.state.mode, now):
                result.mode = self.state.mode

        # Phase 9: reset tracker when the state machine requests it.  The
        # state machine sets this flag whenever a mode transition occurs
        # (e.g. Victory HOLD toggling presentation <-> presentation_pen).
        # Resetting immediately after step() clears the tracker's stable
        # gesture/attempt state so the same pose cannot trigger the reverse
        # switch on the very next frame.
        if result.reset_tracker:
            self.tracker.reset()

        # Keep the legacy mode-changed flag for recorder / debug display.
        mode_changed = self.state.mode != mode_before

        # Record frame data AFTER state.step() so we capture the post-step
        # mode and whether a mode change occurred this frame.
        self.recorder.record_frame(
            gesture_frame, tracker_result, mode_before, tracker_result.events,
            state_paused=self.state.paused,
            mode_changed=mode_changed,
        )

        # Debug window + status broadcast.
        if self.config.show_debug_window:
            self.recognizer.draw(img, frame_result)
            self._render_debug(img, result, now, frame_result, gesture_frame, tracker_result)
            display_img = self._scale_for_display(img)
            cv2.imshow(self._DEBUG_WINDOW_NAME, display_img)
            self._pin_debug_window_once(self._DEBUG_WINDOW_NAME)

        # Convert the monotonic cooldown deadline to wall-clock time so the
        # status card can compare it against Date.now() / 1000.
        cooldown_until = result.debug_info.get("cooldown_until", 0.0)
        if cooldown_until > now:
            cooldown_until = time.time() + (cooldown_until - now)
        else:
            cooldown_until = 0.0

        self.status_update(
            mode=self.state.mode,
            gesture=hand_input.gesture.value,
            action=result.note,
            paused=self.state.paused,
            fps=self._compute_fps(now),
            hand_present=gesture_frame.hand_present,
            hand_lost_duration=result.debug_info.get("hand_lost_duration", 0.0),
            cooldown_until=cooldown_until,
            intent_phase=tracker_result.intent_state,
            **self._display_status,
        )

    # ── host application switching ───────────────────────────────────────
    @staticmethod
    def _app_for_mode(mode: str) -> Optional[str]:
        if mode == MODE_STANDBY:
            return "smartdesk"
        if mode in (MODE_PRESENTATION, MODE_PRESENTATION_PEN):
            return "powerpoint"
        if mode == MODE_SOLIDWORKS:
            return "solidworks"
        return None

    def _probe_display_agent(self) -> None:
        client = self.display_agent_client
        if client is None:
            return
        result = client.status()
        self._display_status.update(
            display_agent_online=result.online and result.ok,
            display_active_app=result.active_app,
            display_switch_state="ready" if result.ok else "unavailable",
            display_switch_error="" if result.ok else result.detail,
            display_switch_at=time.time(),
        )
        if not result.ok:
            logger.warning("Display Agent probe failed: %s", result.detail)

    def _sync_display_mode_transition(
        self, mode_before: str, mode_after: str, now: float
    ) -> bool:
        """Activate the app for an ILoveYou mode swipe, rolling back on failure."""
        source_app = self._app_for_mode(mode_before)
        target_app = self._app_for_mode(mode_after)
        if target_app is None or target_app == source_app:
            return True
        client = self.display_agent_client
        if client is None:
            return True

        self._display_status.update(
            display_target_app=target_app,
            display_switch_state="switching",
            display_switch_error="",
            display_switch_at=time.time(),
        )
        result: DisplayAgentResult = client.activate(target_app)
        self._display_status.update(
            display_agent_online=result.online,
            display_active_app=target_app if result.ok else self._display_status["display_active_app"],
            display_switch_state="active" if result.ok else "failed",
            display_switch_error="" if result.ok else result.detail,
            display_switch_at=time.time(),
        )
        if result.ok:
            logger.info("Display switched: %s -> %s", source_app, target_app)
            return True

        self.state.restore_mode(mode_before, now)
        self._display_status["display_target_app"] = source_app
        logger.warning(
            "Display switch failed; restored mode %s: %s", mode_before, result.detail
        )
        return False

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
        # Reset tracker state so stale attempts/sessions don't carry over.
        try:
            self.tracker.reset()
        except Exception:  # pragma: no cover - defensive
            logger.exception("tracker reset failed")

    def _shutdown(self) -> None:
        """Single exit path: release everything, close resources."""
        logger.info("shutting down gesture controller")
        # Close recorder first so all frames are flushed.
        try:
            self.recorder.close()
        except Exception:  # pragma: no cover - defensive
            logger.exception("recorder close failed")
        self._safe_release()
        try:
            self.recognizer.close()
        except Exception:  # pragma: no cover
            logger.exception("recognizer close failed")

        if self._owns_cap and self._camera_instance is not None:
            try:
                self._camera_instance.release()
            except Exception:  # pragma: no cover
                logger.exception("camera release failed")
        self._camera_instance = None
        self._cap = None

        if self.config.show_debug_window:
            try:
                import cv2

                cv2.destroyAllWindows()
            except Exception:  # pragma: no cover
                pass

        # Hotkey cleanup (keyboard library or pynput fallback).
        self._uninstall_hotkeys()

        # Push terminal state to all status consumers.
        self.status_update(
            camera_ok=False, action="controller exited", paused=True
        )

        if self.status_server is not None:
            try:
                self.status_server.stop()
            except Exception:  # pragma: no cover
                logger.exception("status server stop failed")
            self.status_server = None

        if self.overlay is not None:
            try:
                self.overlay.stop()
            except Exception:  # pragma: no cover
                logger.exception("overlay stop failed")
            self.overlay = None

    # ── hotkeys ────────────────────────────────────────────────────────────
    # ── hotkeys ────────────────────────────────────────────────────────────
    def _install_hotkeys(self) -> None:
        """Install global Ctrl+Alt+G (pause) and Ctrl+Alt+Q (exit).

        Primary backend is the ``keyboard`` library; it works more reliably on
        Windows than pynput.  If ``keyboard`` fails we silently fall back to the
        cv2 debug window keys (p/Space, q/Esc).  pynput is kept only as a last
        fallback if the user still has it installed but not ``keyboard``.
        """
        if not self.config.enable_hotkeys:
            logger.info("hotkeys disabled by config")
            return

        # Primary: keyboard library.
        if self._install_keyboard_hotkeys():
            return

        # Fallback: pynput (kept for compatibility, not the default).
        if self._install_pynput_hotkeys():
            return

        # Final fallback: user can still control via the debug window.
        logger.warning("global hotkeys unavailable — use debug window keys")
        logger.warning("Click the debug window and press 'p' or Space to resume")
        logger.warning("Press 'q' or Esc in the debug window to quit")

    def _install_keyboard_hotkeys(self) -> bool:
        """Try to install global hotkeys using the ``keyboard`` library.

        Returns ``True`` on success, ``False`` if the library is missing or
        registration fails.
        """
        try:
            import keyboard
        except ImportError:
            logger.info("keyboard library not installed — skipping keyboard backend")
            return False

        try:
            pause_hotkey = self._keyboard_hotkey(self.config.hotkey_toggle_pause)
            exit_hotkey = self._keyboard_hotkey(self.config.hotkey_emergency_exit)
            handle_pause = keyboard.add_hotkey(pause_hotkey, self._on_toggle_pause)
            handle_exit = keyboard.add_hotkey(exit_hotkey, self._on_emergency_exit)
            self._hotkey_handles = [handle_pause, handle_exit]
            self._hotkey_backend = "keyboard"
            logger.info("global hotkeys active (keyboard): %s / %s", pause_hotkey, exit_hotkey)
            logger.info("  pause/resume: %s", pause_hotkey)
            logger.info("  emergency exit: %s", exit_hotkey)
            return True
        except Exception:
            logger.exception("keyboard.add_hotkey failed — falling back")
            return False

    def _uninstall_keyboard_hotkeys(self) -> None:
        """Remove any hotkeys registered with the ``keyboard`` library."""
        if not self._hotkey_handles:
            return
        try:
            import keyboard

            for handle in self._hotkey_handles:
                try:
                    keyboard.remove_hotkey(handle)
                except Exception:
                    pass
            keyboard.unhook_all_hotkeys()
        except ImportError:
            pass
        except Exception:
            logger.exception("keyboard.remove_hotkey failed")
        finally:
            self._hotkey_handles.clear()
            self._hotkey_backend = None

    def _install_pynput_hotkeys(self) -> bool:
        """Legacy fallback: install global hotkeys via pynput.

        Kept only for compatibility; the ``keyboard`` library is preferred.
        Returns ``True`` on success.
        """
        try:
            from pynput import keyboard
        except ImportError:
            logger.info("pynput not installed — skipping pynput fallback")
            return False
        except Exception:  # pragma: no cover - environment dependent
            logger.exception("pynput import failed")
            return False

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
            self._hotkey_backend = "pynput"
            logger.info("global hotkeys active (pynput fallback): %s / %s", self.config.hotkey_toggle_pause, self.config.hotkey_emergency_exit)
            return True
        except Exception:  # pragma: no cover - environment dependent
            logger.exception("failed to install pynput hotkey listener")
            return False

    def _uninstall_pynput_hotkeys(self) -> None:
        """Stop the pynput listener if it was started."""
        if self._hotkey_listener is None:
            return
        try:
            self._hotkey_listener.stop()
        except Exception:
            pass
        self._hotkey_listener = None
        self._hotkey_backend = None

    def _uninstall_hotkeys(self) -> None:
        """Remove all installed global hotkeys (keyboard or pynput)."""
        self._uninstall_keyboard_hotkeys()
        self._uninstall_pynput_hotkeys()

    @staticmethod
    def _keyboard_hotkey(spec: str) -> str:
        """Convert the pynput-style spec ``<ctrl>+<alt>+g`` to ``ctrl+alt+g``."""
        return spec.replace("<", "").replace(">", "").lower()
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
        self.status_update(paused=paused, action=action)

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

    def _render_debug(self, img, result: StepResult, now: float,
                      frame_result=None, gesture_frame: Optional[GestureFrame] = None,
                      tracker_result: Optional[TrackerResult] = None) -> None:
        """Render comprehensive dry-run debug overlay.

        Displays all fields required by task-5 acceptance:
        mode, raw_gesture, stable_gesture, attempt phase/id, session id/type,
        palm_xy, index_tip_xy, dx/dy, velocity, hand_size, pinch_distance_norm,
        lost time, cooldown remaining, FPS.
        """
        import cv2

        fps = self._compute_fps(now)
        di = result.debug_info
        # Tracker debug info (may be None if tracker wasn't called).
        tdi = tracker_result.debug_info if tracker_result is not None else {}

        # ── Line 1: FPS ──
        cv2.putText(img, f"FPS: {int(fps)}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)

        # ── Line 2: Mode ──
        mode_text = f"[{result.mode.upper()}]{' (PAUSED)' if self.state.paused else ''}"
        cv2.putText(img, mode_text, (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        # ── Line 3: Raw gesture (from recognizer) ──
        raw_g = di.get("raw_gesture", "none")
        cur_g = di.get("current_gesture", "none")
        gesture_color = (0, 255, 0) if cur_g != "none" else (120, 120, 120)
        cv2.putText(img, f"raw_gesture: {raw_g}", (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, gesture_color, 2)

        # ── Line 4: Stable gesture (from tracker) ──
        stable_g = tdi.get("stable_gesture", None) or "none"
        cv2.putText(img, f"stable_gesture: {stable_g}", (10, 115),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 200, 255), 2)

        # ── Line 5: Status note ──
        cv2.putText(img, result.note[:70], (10, 138),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        # ── Lines 6+: Recognition source / confidence ──
        y = 158
        if frame_result is not None:
            source = frame_result.gesture_source or "none"
            conf = frame_result.gesture_confidence
            cv2.putText(img, f"src: {source}  conf: {conf:.2f}" if conf is not None else f"src: {source}",
                        (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 255), 1)
            y += 18

        # ── Attempt / Session state (from tracker) ──
        att_id = tdi.get("active_attempt_id")
        att_phase = tdi.get("active_attempt_phase")
        att_intent = tdi.get("active_attempt_intent")
        ses_id = tdi.get("active_session_id")
        ses_type = tdi.get("active_session_type")
        ses_phase = tdi.get("active_session_phase")
        if att_id or att_phase:
            cv2.putText(img, f"attempt: {att_intent or '?'}:{att_phase or '?'} id={att_id or '?'}",
                        (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 200, 100), 1)
            y += 18
        if ses_id or ses_type:
            cv2.putText(img, f"session: {ses_type or '?'}:{ses_phase or '?'} id={ses_id or '?'}",
                        (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 200, 100), 1)
            y += 18

        # ── Tracker intent state ──
        intent_state = tdi.get("tracker_state", "?")
        cv2.putText(img, f"tracker: {intent_state}", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
        y += 18

        # ── GestureFrame: palm_xy, index_tip_xy, hand_size, pinch_distance_norm ──
        if gesture_frame is not None and gesture_frame.hand_present:
            if gesture_frame.palm_xy is not None:
                cv2.putText(img, f"palm_xy: ({gesture_frame.palm_xy[0]:.3f}, {gesture_frame.palm_xy[1]:.3f})",
                            (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 255, 100), 1)
                y += 18
            if gesture_frame.index_tip_xy is not None:
                cv2.putText(img, f"index_xy: ({gesture_frame.index_tip_xy[0]:.3f}, {gesture_frame.index_tip_xy[1]:.3f})",
                            (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 255, 100), 1)
                y += 18
            if gesture_frame.hand_size is not None:
                cv2.putText(img, f"hand_size: {gesture_frame.hand_size:.3f}",
                            (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 255, 100), 1)
                y += 18
            if gesture_frame.pinch_distance_norm is not None:
                cv2.putText(img, f"pinch_norm: {gesture_frame.pinch_distance_norm:.3f}",
                            (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 255, 100), 1)
                y += 18

        # ── dx/dy and velocity from tracker smoothed palm ──
        smoothed = tdi.get("smoothed_palm")
        if smoothed is not None and gesture_frame is not None and gesture_frame.palm_xy is not None:
            dx = gesture_frame.palm_xy[0] - smoothed[0]
            dy = gesture_frame.palm_xy[1] - smoothed[1]
            dt = max(1e-6, 1.0 / max(1.0, fps))
            vel = (dx * dx + dy * dy) ** 0.5 / dt
            cv2.putText(img, f"dx/dy: {dx:+.4f}/{dy:+.4f}  vel: {vel:.2f}",
                        (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
            y += 18

        # ── Active continuous action + mouse/key flags ──
        action = di.get("active_continuous_action")
        if action:
            cv2.putText(img, f"action: {action}", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)
            y += 18
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
            cv2.putText(img, " | ".join(flags), (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 100, 255), 1)
            y += 18

        # ── Bad frames / intent lost ──
        bad_frames = tdi.get("bad_frames", 0)
        if bad_frames:
            cv2.putText(img, f"bad_frames: {bad_frames}", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 150, 0), 1)
            y += 18

        # ── Hand lost duration ──
        lost_dur = di.get("hand_lost_duration", 0.0)
        if lost_dur > 0.0:
            cv2.putText(img, f"hand_lost: {lost_dur:.1f}s", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
            y += 18

        # ── Cooldown remaining ──
        cooldown_until = di.get("cooldown_until", 0.0)
        if cooldown_until > now:
            cv2.putText(img, f"cooldown: {max(0.0, cooldown_until - now):.2f}s", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
            y += 18

        # ── Zoom state (if active) ──
        zoom_active = tdi.get("zoom_active", False)
        if zoom_active:
            zoom_dist = tdi.get("zoom_last_distance")
            cv2.putText(img, f"zoom: active dist={zoom_dist:.3f}" if zoom_dist else "zoom: active",
                        (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 200, 0), 1)
            y += 18

        # ── Dry-run / paused banner ──
        if not self.config.enable_system_mouse:
            cv2.putText(img, "DRY-RUN (no system mouse)", (10, img.shape[0] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)
        elif self.state.paused:
            cv2.putText(img, "Press 'p' or Space to resume", (10, img.shape[0] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 100), 2)

        # Draw centroid anchor as a red dot in presentation_pen mode.
        if (self.state.mode == MODE_PRESENTATION_PEN and
                gesture_frame is not None and
                gesture_frame.centroid_xy is not None):
            h, w = img.shape[:2]
            cx = int(gesture_frame.centroid_xy[0] * w)
            cy = int(gesture_frame.centroid_xy[1] * h)
            cv2.circle(img, (cx, cy), 8, (0, 0, 255), -1)
            cv2.putText(img, "centroid", (cx + 10, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

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

    # ── debug window key handling ──────────────────────────────────────────
    def _handle_debug_keys(self) -> bool:
        """Handle key-presses in the debug window.

        Returns ``True`` when the quit key is pressed (caller should exit the loop).
        """
        if not self.config.show_debug_window:
            return False
        try:
            import cv2

            key = cv2.waitKey(1) & 0xFF
            if key == ord(self.config.exit_key) or key == 27:  # q or Esc
                logger.info("exit key pressed: key=%d", key)
                return True
            if key == ord('p') or key == 32:  # p or Space
                self._on_toggle_pause()
        except Exception:  # pragma: no cover - environment dependent
            pass
        return False

    # ── camera ─────────────────────────────────────────────────────────────
    def _open_camera(self) -> None:
        """Open camera through the configured driver factory.

        If an externally provided ``cap`` was passed to ``__init__``,
        that instance is reused unchanged.
        """
        if self._cap is not None:
            # Caller provided an external camera instance (tests / mocks).
            self._camera_instance = self._cap
            return

        self._camera_instance = create_camera(self.config)
        self._cap = self._camera_instance

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

    def overlay_update(self, **fields) -> None:
        """Push a partial status update to the native overlay (if active)."""
        if self.overlay is not None:
            try:
                self.overlay.update(**fields)
            except Exception:  # pragma: no cover - defensive
                logger.exception("overlay.update failed")

    def status_update(self, **fields) -> None:
        """Unified status push: update both the WebSocket server and the overlay."""
        self.status_server_update(**fields)
        self.overlay_update(**fields)

    def _print_banner(self) -> None:
        """Print startup banner to the log file instead of the terminal."""
        gr_status = "on" if self.config.use_gesture_recognizer else "off (rule fallback)"
        logger.info("=" * 60)
        logger.info("SmartDesk Gesture Controller")
        logger.info("  camera driver:  %s", self.config.camera_driver)
        if self.config.camera_driver == "industrial":
            logger.info("  camera index:   %s", self.config.industrial_camera_index)
        else:
            logger.info("  camera index:   %s", self.config.camera_index)
        logger.info("  mode on activate: %s", self.config.initial_mode)
        logger.info("  system mouse:     %s", "ENABLED" if self.config.enable_system_mouse else "DRY-RUN")
        logger.info("  debug window:     %s", "on" if self.config.show_debug_window else "off")
        if self.status_server:
            logger.info(
                "  status server:    ws://%s:%s  |  http://%s:%s",
                self.config.status_server_host,
                self.config.status_server_port,
                self.config.status_server_host,
                self.config.status_server_port,
            )
        else:
            logger.info("  status server:    off")
        if self.overlay:
            logger.info("  overlay:           on (native topmost)")
        else:
            logger.info("  overlay:           off")
        logger.info("  pause hotkey:     %s", self.config.hotkey_toggle_pause)
        logger.info("  exit hotkey:      %s", self.config.hotkey_emergency_exit)
        logger.info("  gesture recognizer: %s", gr_status)
        if self.config.show_debug_window:
            logger.info(
                "  debug keys:       '%s'/Esc = quit, p/Space = pause/resume",
                self.config.exit_key,
            )
        logger.info("Gestures:")
        logger.info("  presentation: open palm swipe left/right = prev/next, fist = standby")
        logger.info("  mouse:        pointing up = move, pinch = click/drag,")
        logger.info("                victory hold = scroll mode, thumb down = right click,")
        logger.info("                fist = exit mode")
        logger.info("  solidworks:   open palm = rotate, victory = pan, pinch = zoom,")
        logger.info("                thumb up = fit, iloveyou = isometric, fist = exit")
        logger.info("=" * 60)


def main(argv: Optional[list] = None) -> int:
    """Entry point: configure logging to file and console, then start controller.

    INFO-level logs are written to ``logs/gesture_controller_YYYYMMDD_HHMMSS.log``.
    The console only shows WARNING and above, so normal startup/hand tracking
    status does not clutter the terminal window.
    """
    import os
    from datetime import datetime

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logs_dir = os.path.join(project_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(logs_dir, f"gesture_controller_{timestamp}.log")

    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    formatter = logging.Formatter(log_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    # Remove any default handlers so we can install our own.
    root_logger.handlers.clear()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    config = config_from_args(argv)
    controller = GestureController(config=config)
    return controller.start()


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
