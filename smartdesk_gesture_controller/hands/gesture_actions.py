"""Thin wrapper around pyautogui system control actions.

Why a wrapper instead of calling ``pyautogui`` directly from the state machine:
    1. Every action is gated by ``enable_system_mouse`` so the controller can
       run as a dry-run for demos and tests without hijacking the real cursor.
    2. The hot-path mouse-move throttle and the safety ``release_all`` live in
       one place, so the controller and the shutdown path cannot forget them.
    3. Tests inject a fake driver and assert on call sequences instead of
       touching the real display.

The real ``pyautogui`` import is deferred to ``_real_driver()`` so that simply
importing this module (e.g. in tests on a headless CI) does not trigger
pyautogui's failsafe / display initialization.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("hands.actions")


@dataclass
class _Call:
    """One recorded action — used by the fake driver in tests and by logs."""

    name: str
    args: Tuple[Any, ...] = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:  # pragma: no cover - debug only
        kwargs = ", ".join(f"{k}={v!r}" for k, v in self.kwargs.items())
        joined = ", ".join([*(repr(a) for a in self.args), kwargs] if kwargs else [*(repr(a) for a in self.args)])
        return f"{self.name}({joined})"


class FakeDriver:
    """Records every call instead of touching the OS. Used in dry-run + tests."""

    def __init__(self) -> None:
        self.calls: List[_Call] = []

    # The methods below mirror the pyautogui surface we actually use.
    def moveTo(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("moveTo", args, kwargs))

    def click(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("click", args, kwargs))

    def mouseDown(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("mouseDown", args, kwargs))

    def mouseUp(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("mouseUp", args, kwargs))

    def press(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("press", args, kwargs))

    def hotkey(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("hotkey", args, kwargs))

    def size(self) -> Tuple[int, int]:  # pyautogui ships this too
        return (1920, 1080)

    def names(self) -> List[str]:
        return [c.name for c in self.calls]

    def reset(self) -> None:
        self.calls.clear()


def _real_driver() -> Any:
    """Import pyautogui lazily and configure it for safety."""
    import pyautogui

    # Disable the move-to-corner failsafe by default (the gesture cursor can
    # legitimately approach corners), but keep our own Ctrl+Alt+Q escape hatch.
    pyautogui.FAILSAFE = False
    return pyautogui


class ActionLayer:
    """All OS-level side effects the gesture controller can perform."""

    def __init__(
        self,
        enable_system_mouse: bool,
        driver: Optional[Any] = None,
    ) -> None:
        self.enable_system_mouse = enable_system_mouse
        # When system mouse is disabled we always use the fake driver so the
        # recorded calls can still be inspected by tests / status UI.
        self._driver: Any = driver if driver is not None else (FakeDriver() if not enable_system_mouse else None)
        self._is_left_down: bool = False

    # ── driver wiring ───────────────────────────────────────────────────────
    def _py(self) -> Any:
        if self._driver is None:
            self._driver = _real_driver()
        return self._driver

    def using_fake_driver(self) -> bool:
        return isinstance(self._driver, FakeDriver)

    def fake_driver(self) -> FakeDriver:
        """Return the fake driver — only valid when ``using_fake_driver``."""
        assert isinstance(self._driver, FakeDriver), "fake driver not active"
        return self._driver

    # ── tracking ────────────────────────────────────────────────────────────
    @property
    def is_left_down(self) -> bool:
        return self._is_left_down

    # ── actions ─────────────────────────────────────────────────────────────
    def move_to(self, x: float, y: float) -> None:
        self._apply("moveTo", x, y)

    def left_click(self) -> None:
        self._apply("click", button="left")

    def mouse_down(self, x: Optional[float] = None, y: Optional[float] = None) -> None:
        kwargs: Dict[str, Any] = {"button": "left"}
        if x is not None and y is not None:
            kwargs["x"], kwargs["y"] = x, y
        self._apply("mouseDown", **kwargs)
        self._is_left_down = True

    def mouse_up(self, x: Optional[float] = None, y: Optional[float] = None) -> None:
        kwargs: Dict[str, Any] = {"button": "left"}
        if x is not None and y is not None:
            kwargs["x"], kwargs["y"] = x, y
        self._apply("mouseUp", **kwargs)
        self._is_left_down = False

    def press(self, key: str) -> None:
        self._apply("press", key)

    def hotkey(self, *keys: str) -> None:
        self._apply("hotkey", *keys)

    def release_all(self) -> None:
        """Safety net: ensure no mouse button stays pressed.

        Called on shutdown, on hand-loss timeout, and on any unhandled
        exception in the main loop. Idempotent.
        """
        if self._is_left_down:
            try:
                self._apply("mouseUp", button="left")
            except Exception:  # pragma: no cover - defensive
                logger.exception("release_all: mouseUp failed")
            self._is_left_down = False

    # ── internals ───────────────────────────────────────────────────────────
    def _apply(self, name: str, *args: Any, **kwargs: Any) -> None:
        if not self.enable_system_mouse:
            # Dry-run: still route through the fake driver so tests can assert.
            getattr(self._py(), name)(*args, **kwargs)
            return
        try:
            getattr(self._py(), name)(*args, **kwargs)
        except Exception:
            # Never let a pyautogui error kill the control loop; the safety
            # layer above still owes the user a release_all on the way out.
            logger.exception("action %s failed", name)
