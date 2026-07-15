"""Thin wrapper around Windows SendInput system control actions.

Why a wrapper instead of calling ``SendInput`` directly from the state machine:
    1. Every action is gated by ``enable_system_mouse`` so the controller can
       run as a dry-run for demos and tests without hijacking the real cursor.
    2. The hot-path mouse-move throttle and the safety ``release_all`` live in
       one place, so the controller and the shutdown path cannot forget them.
    3. Tests inject a fake driver and assert on call sequences instead of
       touching the real display.

The real Windows ``SendInput`` implementation is imported via ``sendinput_utils``
and returned by ``_real_driver()``.  The module is only usable on Windows; on
other platforms the import raises so that headless CI immediately fails fast
if someone tries to use system mouse there.

Phase 1 additions (docs/GESTURE_AND_DISPLAY_SPEC.md):
    * ``execute(intents)`` — unified entry point accepting a single
      ``ActionIntent``, a list, ``None``, or an empty list.
    * ``release_all`` now unconditionally releases left/middle/right mouse
      buttons and shift/ctrl/alt keys (idempotent, always safe).
    * ``FakeDriver`` gained ``scroll``, ``keyDown``, ``keyUp``, ``moveRel``
      and an ``events`` list in the spec's tuple format.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from . import sendinput_utils
from .gesture_state import ActionIntent

logger = logging.getLogger("hands.actions")

# Buttons and modifier keys that release_all always clears.
_RELEASE_BUTTONS: Tuple[str, ...] = ("left", "middle", "right")
_RELEASE_KEYS: Tuple[str, ...] = ("shift", "ctrl", "alt")


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
    """Records every call instead of touching the OS. Used in dry-run + tests.

    Two recording surfaces are maintained:
    * ``calls``  — list of ``_Call`` dataclass instances (backward compat).
    * ``events`` — list of driver event tuples described by the current gesture specification, e.g.
      ``("press", "f5")``, ``("mouse_down", "left")``, ``("release_all",)``.
    """

    def __init__(self) -> None:
        self.calls: List[_Call] = []
        self.events: List[tuple] = []

    # ── driver-compatible methods (mirroring pyautogui/SendInput signatures) ─
    def moveTo(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("moveTo", args, kwargs))
        # Extract x, y from positional or keyword args.
        x = args[0] if len(args) > 0 else kwargs.get("x", 0)
        y = args[1] if len(args) > 1 else kwargs.get("y", 0)
        self.events.append(("move_to", x, y))

    def moveRel(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("moveRel", args, kwargs))
        dx = args[0] if len(args) > 0 else kwargs.get("dx", 0)
        dy = args[1] if len(args) > 1 else kwargs.get("dy", 0)
        self.events.append(("move_rel", dx, dy))

    def click(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("click", args, kwargs))
        button = kwargs.get("button", "left")
        self.events.append(("click", button))

    def mouseDown(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("mouseDown", args, kwargs))
        button = kwargs.get("button", "left")
        self.events.append(("mouse_down", button))

    def mouseUp(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("mouseUp", args, kwargs))
        button = kwargs.get("button", "left")
        self.events.append(("mouse_up", button))

    def press(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("press", args, kwargs))
        key = args[0] if args else kwargs.get("key", "")
        self.events.append(("press", key))

    def hotkey(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("hotkey", args, kwargs))
        self.events.append(("hotkey", list(args)))

    def keyDown(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("keyDown", args, kwargs))
        key = args[0] if args else kwargs.get("key", "")
        self.events.append(("key_down", key))

    def keyUp(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("keyUp", args, kwargs))
        key = args[0] if args else kwargs.get("key", "")
        self.events.append(("key_up", key))

    def scroll(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(_Call("scroll", args, kwargs))
        amount = args[0] if args else kwargs.get("amount", 0)
        self.events.append(("scroll", amount))

    def size(self) -> Tuple[int, int]:  # matches the pyautogui / SendInput signature
        return (1920, 1080)

    # ── convenience ─────────────────────────────────────────────────────────
    def names(self) -> List[str]:
        return [c.name for c in self.calls]

    def reset(self) -> None:
        self.calls.clear()
        self.events.clear()

    def has_event(self, *prefix: Any) -> bool:
        """True if any event tuple starts with the given prefix."""
        return any(ev[: len(prefix)] == prefix for ev in self.events)


def _real_driver() -> Any:
    """Return the Windows SendInput driver module.

    ``sendinput_utils`` implements the same functions used by ``ActionLayer``:
    ``moveTo``, ``moveRel``, ``click``, ``mouseDown``, ``mouseUp``, ``press``,
    ``hotkey``, ``keyDown``, ``keyUp``, ``scroll``, ``size``.
    """
    # The module import is unconditional; guard platform at the top level to
    # surface a clear ImportError on non-Windows before any action is taken.
    if sys.platform != "win32":
        raise ImportError("sendinput_utils requires Windows")
    return sendinput_utils


class ActionLayer:
    """All OS-level side effects the gesture controller can perform.

    Phase 1: the layer accepts ``ActionIntent`` objects via :meth:`execute`
    and dispatches them to the appropriate SendInput / FakeDriver call.
    Existing positional methods (``move_to``, ``mouse_down`` …) are kept so
    the unmodified controller continues to work.
    """

    def __init__(
        self,
        enable_system_mouse: bool,
        driver: Optional[Any] = None,
    ) -> None:
        self.enable_system_mouse = enable_system_mouse
        # When system mouse is disabled we always use the fake driver so the
        # recorded calls can still be inspected by tests / status UI.
        self._driver: Any = driver if driver is not None else (FakeDriver() if not enable_system_mouse else None)

        # Track held state for release_all and conflict detection.
        self._held_buttons: set = set()   # subset of {"left","middle","right"}
        self._held_keys: set = set()      # subset of {"shift","ctrl","alt",...}
        # Legacy flag — some external code reads is_left_down directly.
        self._is_left_down: bool = False

    # ── driver wiring ───────────────────────────────────────────────────────
    def _py(self) -> Any:
        if self._driver is None:
            self._driver = sendinput_utils
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
        return "left" in self._held_buttons

    @property
    def held_buttons(self) -> set:
        return set(self._held_buttons)

    @property
    def held_keys(self) -> set:
        return set(self._held_keys)

    # ── existing positional actions (controller compat) ─────────────────────
    def move_to(self, x: float, y: float) -> None:
        self._apply("moveTo", x, y)

    def left_click(self) -> None:
        self._apply("click", button="left")

    def mouse_down(self, x: Optional[float] = None, y: Optional[float] = None) -> None:
        """Legacy left-button mouseDown — controller calls this."""
        kwargs: Dict[str, Any] = {"button": "left"}
        if x is not None and y is not None:
            kwargs["x"], kwargs["y"] = x, y
        self._apply("mouseDown", **kwargs)
        self._held_buttons.add("left")
        self._is_left_down = True

    def mouse_up(self, x: Optional[float] = None, y: Optional[float] = None) -> None:
        """Legacy left-button mouseUp — controller calls this."""
        kwargs: Dict[str, Any] = {"button": "left"}
        if x is not None and y is not None:
            kwargs["x"], kwargs["y"] = x, y
        self._apply("mouseUp", **kwargs)
        self._held_buttons.discard("left")
        self._is_left_down = False

    def press(self, key: str) -> None:
        self._apply("press", key)

    def hotkey(self, *keys: str) -> None:
        self._apply("hotkey", *keys)

    # ── release_all (safe cross-application transition) ────────────────────
    def release_all(self) -> None:
        """Release every mouse button and modifier key that could be held.

        Unconditionally calls ``mouseUp`` for left/middle/right and ``keyUp``
        for shift/ctrl/alt.  This is deliberately *always* executed — even if
        our tracking says nothing is held — because the OS may have a stuck
        button from an external source.  Idempotent: calling twice never
        raises and never leaves a button held.
        """
        for button in _RELEASE_BUTTONS:
            try:
                self._apply("mouseUp", button=button)
            except Exception:  # pragma: no cover - defensive
                logger.exception("release_all: mouseUp(%s) failed", button)
        for key in _RELEASE_KEYS:
            try:
                self._apply("keyUp", key)
            except Exception:  # pragma: no cover - defensive
                logger.exception("release_all: keyUp(%s) failed", key)
        self._held_buttons.clear()
        self._held_keys.clear()
        self._is_left_down = False

    # ── unified execute(intents) entry point ────────────────────────────────
    def execute(self, intents: Union[None, ActionIntent, Iterable[ActionIntent]]) -> None:
        """Execute one or more ``ActionIntent`` objects in order.

        Accepts:
        * ``None``           — no-op.
        * single ``ActionIntent`` — executed directly.
        * list of ``ActionIntent`` — executed sequentially.
        * empty list         — no-op.

        Unknown intent types raise ``ValueError`` (never silently swallowed).
        """
        if intents is None:
            return
        if isinstance(intents, ActionIntent):
            intents = [intents]
        for intent in intents:
            self._execute_one(intent)

    def _execute_one(self, intent: ActionIntent) -> None:
        t = intent.type

        # ── No-ops and non-hardware actions ────────────────────────────────
        if t == "noop":
            return
        if t == "status":
            logger.info("[status] %s", intent.text or "")
            return

        # ── Keyboard actions ───────────────────────────────────────────────
        if t == "press":
            if not intent.key:
                raise ValueError("press intent requires a non-empty key")
            self.press(intent.key)
            return
        if t == "hotkey":
            if not intent.keys:
                raise ValueError("hotkey intent requires a non-empty keys list")
            self.hotkey(*intent.keys)
            return
        if t == "key_down":
            if not intent.key:
                raise ValueError("key_down intent requires a non-empty key")
            self._key_down(intent.key)
            return
        if t == "key_up":
            if not intent.key:
                raise ValueError("key_up intent requires a non-empty key")
            self._key_up(intent.key)
            return

        # ── Mouse actions ──────────────────────────────────────────────────
        if t in ("move", "move_to"):
            if intent.x is None or intent.y is None:
                raise ValueError(f"{t} intent requires x and y")
            self.move_to(intent.x, intent.y)
            return
        if t == "move_rel":
            if intent.dx is None or intent.dy is None:
                raise ValueError("move_rel intent requires dx and dy")
            self._move_rel(intent.dx, intent.dy)
            return
        if t == "mouse_down":
            self._mouse_down_button(intent.button or "left")
            return
        if t == "mouse_up":
            self._mouse_up_button(intent.button or "left")
            return
        if t == "click":
            self._click_button(intent.button or "left")
            return
        if t == "scroll":
            if intent.amount is None:
                raise ValueError("scroll intent requires amount")
            self._scroll(intent.amount)
            return

        # ── Safety ─────────────────────────────────────────────────────────
        if t == "release_all":
            self.release_all()
            return

        raise ValueError(f"unknown ActionIntent type: {t!r}")

    # ── internal: button-aware primitives (used by execute) ─────────────────
    def _mouse_down_button(self, button: str) -> None:
        self._apply("mouseDown", button=button)
        self._held_buttons.add(button)
        if button == "left":
            self._is_left_down = True

    def _mouse_up_button(self, button: str) -> None:
        self._apply("mouseUp", button=button)
        self._held_buttons.discard(button)
        if button == "left":
            self._is_left_down = False

    def _click_button(self, button: str) -> None:
        self._apply("click", button=button)

    def _move_rel(self, dx: float, dy: float) -> None:
        self._apply("moveRel", dx, dy)

    def _scroll(self, amount: int) -> None:
        self._apply("scroll", amount)

    def _key_down(self, key: str) -> None:
        self._apply("keyDown", key)
        self._held_keys.add(key)

    def _key_up(self, key: str) -> None:
        self._apply("keyUp", key)
        self._held_keys.discard(key)

    # ── internals ───────────────────────────────────────────────────────────
    def _apply(self, name: str, *args: Any, **kwargs: Any) -> None:
        if not self.enable_system_mouse:
            # Dry-run: still route through the fake driver so tests can assert.
            getattr(self._py(), name)(*args, **kwargs)
            return
        try:
            getattr(self._py(), name)(*args, **kwargs)
        except Exception:
            # Never let a SendInput error kill the control loop; the safety
            # layer above still owes the user a release_all on the way out.
            logger.exception("action %s failed", name)
