"""Native desktop floating overlay window for gesture status display.

This module provides a frameless, translucent, always-on-top overlay window
that shows the three-row device status (Camera / Hand / Status) without
relying on a browser.  It uses PySide6 for the GUI and Win32 API for
topmost re-assertion and click-through support.

Design mirrors :class:`hands.gesture_status_server.GestureStatusServer`:

* Synchronous public API (``start``/``stop``/``update``) — the controller's
  main loop never touches Qt objects directly.
* Runs in a daemon thread so the blocking ``QApplication.exec()`` does not
  stall the gesture recognition loop.
* ``update(**fields)`` only merges a dict under a lock; the GUI thread polls
  the snapshot via a ``QTimer`` — no cross-thread signal emission.

If PySide6 is not installed or the platform is not Windows, ``start()``
returns ``False`` and the controller silently falls back to the browser
status card.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Constants (mirror hands/frontend/styles.css + app.js) ───────────────────

HAND_LOSS_TIMEOUT: float = 1.0
PAGE_GLOW_MS: float = 0.8  # seconds

COLOR_GREEN = "green"
COLOR_AMBER = "amber"
COLOR_ROSE = "rose"
COLOR_CYAN = "cyan"
COLOR_MUTED = "muted"

# Badge stylesheet fragments keyed by semantic colour.
BADGE_STYLES: Dict[str, str] = {
    "green": "color: #2dd4a8; background: rgba(45, 212, 168, 0.12);",
    "amber": "color: #f59e0b; background: rgba(245, 158, 11, 0.12);",
    "rose": "color: #f43f5e; background: rgba(244, 63, 94, 0.12);",
    "cyan": "color: #22d3ee; background: rgba(34, 211, 238, 0.12);",
    "muted": "color: rgba(148, 163, 184, 0.7); background: rgba(148, 163, 184, 0.10);",
}


# ── Module-level pure functions (no Qt dependency — unit-testable) ───────────


def derive_camera(snapshot: Dict[str, Any]) -> Tuple[str, str]:
    """Return (text, colour) for the Camera row."""
    if snapshot.get("camera_ok"):
        return ("Online", COLOR_GREEN)
    return ("Offline", COLOR_ROSE)


def derive_hand(snapshot: Dict[str, Any]) -> Tuple[str, str]:
    """Return (text, colour) for the Hand row."""
    if not snapshot.get("camera_ok"):
        return ("Unavailable", COLOR_MUTED)
    if snapshot.get("hand_present") or (
        snapshot.get("gesture") and snapshot["gesture"] != "none"
    ):
        return ("Detected", COLOR_GREEN)
    lost = snapshot.get("hand_lost_duration", 0.0) or 0.0
    if lost > HAND_LOSS_TIMEOUT:
        return ("Lost", COLOR_ROSE)
    return ("Searching", COLOR_AMBER)


def _is_recognizing(snapshot: Dict[str, Any]) -> bool:
    phase = snapshot.get("intent_phase", "") or ""
    return (
        "attempt:" in phase
        or "session_candidate:" in phase
        or "hold:" in phase
    )


def _is_drawing(snapshot: Dict[str, Any]) -> bool:
    action = snapshot.get("action", "") or ""
    phase = snapshot.get("intent_phase", "") or ""
    return "pen_draw" in action or "session:pen" in phase


def derive_status(
    snapshot: Dict[str, Any],
    hand: Tuple[str, str],
    now: float,
    forced_glow: Optional[str],
) -> Tuple[str, str, bool]:
    """Return (text, colour, glow) for the Status row.

    13-level priority chain — mirrors ``hands/frontend/app.js`` line-by-line.
    """
    # 1 — Paused overrides everything.
    if snapshot.get("paused") or snapshot.get("control_enabled") is False:
        return ("Paused", COLOR_AMBER, False)
    # 2 — Camera offline.
    if not snapshot.get("camera_ok"):
        return ("Camera Offline", COLOR_ROSE, False)
    # 3 — Hand lost (blocking).
    if hand[0] == "Lost":
        return ("Hand Lost", COLOR_ROSE, False)
    # 4 — Searching for hand.
    if hand[0] == "Searching":
        return ("Show Your Hand", COLOR_AMBER, False)
    # 5 — Standby mode.
    if snapshot.get("mode") == "standby":
        return ("Standby", COLOR_MUTED, False)
    # 6 — Pen mode (glow when actively drawing).
    if snapshot.get("mode") == "presentation_pen":
        return ("Pen Mode", COLOR_CYAN, _is_drawing(snapshot))
    # 7 — SolidWorks mode.
    if snapshot.get("mode") == "solidworks":
        return ("SolidWorks", COLOR_CYAN, False)
    # 8 — Forced glow: next slide.
    if forced_glow == "next":
        return ("Next Slide", COLOR_CYAN, True)
    # 9 — Forced glow: previous slide.
    if forced_glow == "previous":
        return ("Previous Slide", COLOR_CYAN, True)
    # 10 — Cooling down.
    cooldown_until = snapshot.get("cooldown_until", 0.0) or 0.0
    if cooldown_until > now:
        return ("Cooling Down", COLOR_MUTED, False)
    # 11 — Recognizing (glow).
    if _is_recognizing(snapshot):
        return ("Recognizing", COLOR_CYAN, True)
    # 12 — Ready to flip.
    if snapshot.get("mode") == "presentation":
        return ("Ready to Flip", COLOR_GREEN, False)
    # 13 — Fallback.
    return ("Standby", COLOR_MUTED, False)


def check_page_turn(snapshot: Dict[str, Any]) -> Optional[str]:
    """Detect page-turn actions; return ``'next'`` / ``'previous'`` / ``None``."""
    action = snapshot.get("action", "") or ""
    gesture = snapshot.get("gesture", "") or ""
    if "page_swipe_right" in action or "Next" in action:
        return "next"
    if "page_swipe_left" in action or "Previous" in action:
        return "previous"
    if "page_swipe_right" in gesture:
        return "next"
    if "page_swipe_left" in gesture:
        return "previous"
    return None


# ── GestureOverlay — thread-safe lifecycle wrapper ─────────────────────────


class GestureOverlay:
    """Native topmost translucent overlay showing device status.

    Lifecycle mirrors :class:`GestureStatusServer`:

    * ``start() -> bool``  — spawn daemon thread, return ``False`` on failure.
    * ``stop()``           — signal quit, join thread.
    * ``update(**fields)`` — thread-safe snapshot merge (never touches Qt).
    """

    def __init__(
        self,
        *,
        click_through: bool = True,
        topmost_interval: float = 1.0,
        update_interval: float = 0.05,
        card_alpha: float = 0.72,
        width: int = 300,
        screen_size: Tuple[int, int] = (0, 0),
    ) -> None:
        self._click_through = click_through
        self._topmost_interval = topmost_interval
        self._update_interval = update_interval
        self._card_alpha = card_alpha
        self._width = width
        self._screen_size = screen_size

        self._state: Dict[str, Any] = {
            "mode": "standby",
            "gesture": "none",
            "action": "idle",
            "camera_ok": False,
            "control_enabled": True,
            "paused": True,
            "fps": 0.0,
            "hand_present": False,
            "hand_lost_duration": 0.0,
            "cooldown_until": 0.0,
            "intent_phase": "idle",
        }
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._start_error: Optional[BaseException] = None
        self._ready = threading.Event()  # signalled when GUI thread is ready or failed

        # GUI objects — only touched from the GUI thread.
        self._app = None
        self._window = None
        self._update_timer = None
        self._topmost_timer = None

        # Page-glow state (read/written only from GUI thread).
        self._forced_glow: Optional[str] = None
        self._forced_glow_until: float = 0.0

    # ── public API ──────────────────────────────────────────────────────

    def start(self) -> bool:
        """Spawn the overlay GUI thread.  Returns ``False`` on failure."""
        if self._running:
            return True
        self._start_error = None
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="hands-overlay-gui",
            daemon=True,
        )
        self._thread.start()
        # Wait for the GUI thread to signal ready (or failure), with a
        # generous timeout for PySide6 / Qt initialisation on slow machines.
        self._ready.wait(timeout=10.0)
        if self._start_error is not None:
            logger.warning("overlay failed to start: %r", self._start_error)
            return False
        if not self._running:
            logger.warning("overlay thread exited without starting")
            return False
        return True

    def stop(self) -> None:
        """Signal the GUI thread to quit.  Safe to call multiple times."""
        # Don't guard on self._running here — start() may have returned True
        # and then the GUI thread could be mid-shutdown.  Always attempt quit.
        self._running = False
        app = self._app
        if app is not None:
            try:
                app.quit()  # thread-safe static method
            except Exception:  # pragma: no cover - defensive
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def update(self, **fields: Any) -> None:
        """Merge partial state.  Safe to call from the controller thread."""
        with self._lock:
            self._state.update(fields)

    # ── GUI thread entry point ──────────────────────────────────────────

    def _run_loop(self) -> None:  # pragma: no cover - requires display
        """Run the QApplication event loop in the daemon thread."""
        try:
            from PySide6.QtCore import Qt, QTimer
            from PySide6.QtWidgets import QApplication
        except ImportError as exc:
            self._start_error = exc
            logger.warning("PySide6 not installed; overlay disabled")
            self._ready.set()
            return

        if os.name != "nt":
            self._start_error = RuntimeError("overlay requires Windows")
            logger.warning("overlay requires Windows; disabled")
            self._ready.set()
            return

        try:
            self._app = QApplication.instance() or QApplication([])
            window_cls = _create_overlay_window_class()
            self._window = window_cls(self._card_alpha, self._width)
            self._setup_window()
            self._window.show()

            # Update timer: poll snapshot → derive → refresh widget.
            self._update_timer = QTimer()
            self._update_timer.timeout.connect(self._on_update_tick)
            self._update_timer.start(int(self._update_interval * 1000))

            # Topmost timer: re-assert HWND_TOPMOST every ~1 s.
            self._topmost_timer = QTimer()
            self._topmost_timer.timeout.connect(self._on_topmost_tick)
            self._topmost_timer.start(int(self._topmost_interval * 1000))

            self._running = True
            self._ready.set()  # signal start() that we're ready
            logger.info("overlay window started")
            self._app.exec()
        except Exception as exc:
            logger.exception("overlay loop crashed")
            self._start_error = exc
            self._ready.set()
        finally:
            self._running = False
            self._ready.set()  # ensure start() never hangs
            self._cleanup_qt()

    # ── window setup ────────────────────────────────────────────────────

    def _setup_window(self) -> None:  # pragma: no cover - requires display
        from PySide6.QtCore import Qt

        w = self._window
        w.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        w.setAttribute(Qt.WA_TranslucentBackground, True)
        w.setAttribute(Qt.WA_ShowWithoutActivating, True)

        x, y = self._compute_position()
        w.move(x, y)

        # Win32 attributes need the HWND, which is only valid after show().
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self._apply_win32_attributes)

    def _compute_position(self) -> Tuple[int, int]:  # pragma: no cover
        try:
            screen = self._app.primaryScreen()
            geo = screen.availableGeometry()
            return (geo.right() - self._width - 24, geo.top() + 24)
        except Exception:
            sw, _sh = self._screen_size or (1920, 1080)
            return (sw - self._width - 24, 24)

    # ── Win32 layer ─────────────────────────────────────────────────────

    def _apply_win32_attributes(self) -> None:  # pragma: no cover - env
        try:
            import win32con
            import win32gui
        except ImportError:
            logger.warning("pywin32 not installed; overlay topmost/click-through limited")
            return

        try:
            hwnd = int(self._window.winId())
            if not hwnd:
                return

            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            ex_style |= win32con.WS_EX_TOOLWINDOW
            ex_style |= win32con.WS_EX_LAYERED
            if self._click_through:
                ex_style |= win32con.WS_EX_TRANSPARENT
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)

            self._assert_topmost(hwnd)
        except Exception:
            logger.exception("failed to apply win32 overlay attributes")

    def _assert_topmost(self, hwnd: int) -> None:  # pragma: no cover - env
        import win32con
        import win32gui

        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOPMOST,
            0, 0, 0, 0,
            win32con.SWP_NOMOVE
            | win32con.SWP_NOSIZE
            | win32con.SWP_NOACTIVATE
            | win32con.SWP_SHOWWINDOW,
        )

    def _on_topmost_tick(self) -> None:  # pragma: no cover - env
        try:
            hwnd = int(self._window.winId())
            if hwnd:
                self._assert_topmost(hwnd)
        except Exception:
            pass

    # ── update tick (GUI thread) ────────────────────────────────────────

    def _on_update_tick(self) -> None:  # pragma: no cover - requires display
        with self._lock:
            snapshot = dict(self._state)
        now = time.time()

        # Page-turn glow detection (800 ms).
        direction = check_page_turn(snapshot)
        if direction is not None:
            self._forced_glow = direction
            self._forced_glow_until = now + PAGE_GLOW_MS

        forced_glow = self._forced_glow
        if forced_glow is not None and now >= self._forced_glow_until:
            self._forced_glow = None
            forced_glow = None

        camera = derive_camera(snapshot)
        hand = derive_hand(snapshot)
        status = derive_status(snapshot, hand, now, forced_glow)

        if self._window is not None:
            self._window.update_display(camera, hand, status)

    # ── cleanup ─────────────────────────────────────────────────────────

    def _cleanup_qt(self) -> None:  # pragma: no cover - requires display
        try:
            if self._update_timer is not None:
                self._update_timer.stop()
            if self._topmost_timer is not None:
                self._topmost_timer.stop()
            if self._window is not None:
                self._window.close()
                self._window.deleteLater()
        except Exception:
            pass


# ── OverlayWindow widget (built lazily when PySide6 is available) ───────────


def _create_overlay_window_class():
    """Build and return the real ``OverlayWindow`` QWidget subclass.

    Called lazily from ``_run_loop`` so that the module can be imported
    without PySide6 installed.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import (
        QFrame,
        QGraphicsDropShadowEffect,
        QHBoxLayout,
        QLabel,
        QVBoxLayout,
        QWidget,
    )

    class _OverlayWindow(QWidget):
        """Frameless translucent top-level widget with a status card."""

        def __init__(self, card_alpha: float, width: int):
            super().__init__()
            self._card_alpha = card_alpha
            self._width = width
            self.setFixedSize(width + 48, 200)
            self._build_ui()
            self._apply_stylesheet()

        # ── UI construction ─────────────────────────────────────────────

        def _build_ui(self):
            layout = QVBoxLayout(self)
            layout.setContentsMargins(24, 24, 24, 24)

            # Semi-transparent card container.
            self._card = QFrame()
            self._card.setObjectName("cardWidget")
            card_layout = QVBoxLayout(self._card)
            card_layout.setContentsMargins(18, 18, 18, 18)
            card_layout.setSpacing(10)

            # Header: Radar icon + bilingual title.
            header = QHBoxLayout()
            header.setSpacing(12)
            self._radar_label = QLabel()
            self._radar_label.setFixedSize(24, 24)
            self._load_radar_icon()

            title_box = QVBoxLayout()
            title_box.setSpacing(0)
            self._title_zh = QLabel("手势控制")
            self._title_zh.setObjectName("titleZh")
            self._title_en = QLabel("Gesture Controller")
            self._title_en.setObjectName("titleEn")
            title_box.addWidget(self._title_zh)
            title_box.addWidget(self._title_en)
            header.addWidget(self._radar_label)
            header.addLayout(title_box)
            header.addStretch()
            card_layout.addLayout(header)
            card_layout.addSpacing(6)

            # Three status rows.
            self._camera_label, self._camera_badge = self._make_row(card_layout, "Camera")
            self._hand_label, self._hand_badge = self._make_row(card_layout, "Hand")
            self._status_label, self._status_badge = self._make_row(card_layout, "Status")

            layout.addWidget(self._card)
            layout.addStretch()

            # Glow effect (cyan, only enabled for specific statuses).
            self._glow_effect = QGraphicsDropShadowEffect(self._card)
            self._glow_effect.setBlurRadius(28)
            self._glow_effect.setColor(QColor(34, 211, 238, 89))
            self._glow_effect.setOffset(0, 0)
            self._glow_effect.setEnabled(False)
            self._card.setGraphicsEffect(self._glow_effect)

        def _make_row(self, parent_layout, label_text):
            row = QHBoxLayout()
            label = QLabel(label_text)
            label.setObjectName("rowLabel")
            badge = QLabel("...")
            badge.setObjectName("badge")
            badge.setAlignment(Qt.AlignCenter)
            row.addWidget(label)
            row.addStretch()
            row.addWidget(badge)
            parent_layout.addLayout(row)
            return label, badge

        def _load_radar_icon(self):
            svg_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "frontend",
                "radar.svg",
            )
            try:
                renderer = QSvgRenderer(svg_path)
                pixmap = QPixmap(24, 24)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                renderer.render(painter)
                painter.end()
                self._radar_label.setPixmap(pixmap)
            except Exception:
                # Fallback: draw concentric circles + crosshairs.
                from PySide6.QtCore import QPointF

                pixmap = QPixmap(24, 24)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                pen = QPen(QColor(255, 255, 255, 230), 2)
                painter.setPen(pen)
                painter.drawEllipse(QPointF(12, 12), 5, 5)
                painter.drawEllipse(QPointF(12, 12), 9, 9)
                painter.drawLine(12, 3, 12, 5)
                painter.drawLine(12, 19, 12, 21)
                painter.drawLine(3, 12, 5, 12)
                painter.drawLine(19, 12, 21, 12)
                painter.setBrush(QColor(255, 255, 255, 230))
                painter.drawEllipse(QPointF(12, 12), 2, 2)
                painter.end()
                self._radar_label.setPixmap(pixmap)

        def _apply_stylesheet(self):
            self.setStyleSheet(
                """
                QWidget { background: transparent; }
                #cardWidget {
                    background-color: rgba(8, 13, 22, %s);
                    border: 1px solid rgba(120, 160, 200, 0.18);
                    border-radius: 8px;
                }
                #titleZh {
                    color: rgba(255, 255, 255, 0.92);
                    font-size: 14px; font-weight: 600;
                }
                #titleEn {
                    color: rgba(255, 255, 255, 0.54);
                    font-size: 11px; font-weight: 500;
                }
                #rowLabel {
                    color: rgba(255, 255, 255, 0.58);
                    font-size: 13px; font-weight: 500;
                }
                QLabel#badge {
                    font-size: 12px; font-weight: 600;
                    border-radius: 999px;
                    padding: 3px 10px;
                }
                """
                % self._card_alpha
            )

        # ── Public update ───────────────────────────────────────────────

        def update_display(self, camera, hand, status):
            text_cam, color_cam = camera
            text_hand, color_hand = hand
            text_status, color_status, glow = status

            self._camera_badge.setText(text_cam)
            self._camera_badge.setStyleSheet(BADGE_STYLES.get(color_cam, ""))
            self._hand_badge.setText(text_hand)
            self._hand_badge.setStyleSheet(BADGE_STYLES.get(color_hand, ""))
            self._status_badge.setText(text_status)
            self._status_badge.setStyleSheet(BADGE_STYLES.get(color_status, ""))

            self._glow_effect.setEnabled(glow)

    return _OverlayWindow
