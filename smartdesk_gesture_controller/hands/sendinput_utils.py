"""Windows SendInput-based mouse/keyboard primitives.

Replaces ``pyautogui`` for the gesture controller by calling the Windows
``user32.SendInput`` API directly through ``ctypes``.  This avoids pulling in
an external dependency and gives deterministic low-level input behavior on
Windows.

The public functions intentionally mirror the pyautogui calls used by
``gesture_actions.ActionLayer``:

    moveTo(x, y)          absolute screen coordinates
    moveRel(dx, dy)       relative pixel delta
    click(button, ...)    left/middle/right click (no x/y, no clicks=count)
    mouseDown(button)     hold a mouse button
    mouseUp(button)       release a mouse button
    press(key)            press+release a single key
    hotkey(*keys)         press keys in order, release in reverse order
    keyDown(key)          hold a key
    keyUp(key)            release a key
    scroll(amount)        vertical wheel scroll
    size()                return primary screen size (via GetSystemMetrics)

All coordinates are integer screen pixels.  ``SendInput`` is called with the
INPUT_KEYBOARD / INPUT_MOUSE structures defined in ``winuser.h``.
"""
from __future__ import annotations

import ctypes
import math
import sys
from typing import Tuple

# Fail fast on non-Windows — this package is only meant for Windows desktop.
if sys.platform != "win32":
    raise ImportError("sendinput_utils requires Windows (user32/SendInput)")

user32 = ctypes.windll.user32

# ── SendInput constants ──────────────────────────────────────────────────
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

# Mouse flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800

# Virtual-screen normalizer used by absolute move.
SM_CXSCREEN = 0
SM_CYSCREEN = 1

# Key event flags
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_I(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("_", _INPUT_I)]


# ── mouse helpers ───────────────────────────────────────────────────────
_BUTTON_TO_DOWN_FLAGS = {
    "left": MOUSEEVENTF_LEFTDOWN,
    "middle": MOUSEEVENTF_MIDDLEDOWN,
    "right": MOUSEEVENTF_RIGHTDOWN,
}
_BUTTON_TO_UP_FLAGS = {
    "left": MOUSEEVENTF_LEFTUP,
    "middle": MOUSEEVENTF_MIDDLEUP,
    "right": MOUSEEVENTF_RIGHTUP,
}


def _button_flag(button: str, down: bool) -> int:
    b = button.lower()
    table = _BUTTON_TO_DOWN_FLAGS if down else _BUTTON_TO_UP_FLAGS
    if b not in table:
        raise ValueError(f"unsupported mouse button: {button!r}")
    return table[b]


def _send_mouse_input(dx: int, dy: int, flags: int, data: int = 0) -> None:
    inp = _INPUT()
    inp.type = INPUT_MOUSE
    inp._.mi.dx = dx
    inp._.mi.dy = dy
    inp._.mi.mouseData = data
    inp._.mi.dwFlags = flags
    inp._.mi.time = 0
    inp._.mi.dwExtraInfo = None
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _screen_size() -> Tuple[int, int]:
    return user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)


# ── keyboard helpers ────────────────────────────────────────────────────
# A minimal mapping of the human-readable key names used by the gesture
# controller to Windows virtual-key codes.  This covers all current usages.
# pyautogui-style special names are also included where possible.
_VK_MAP = {
    # letters
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45, "f": 0x46,
    "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C,
    "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50, "q": 0x51, "r": 0x52,
    "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
    "y": 0x59, "z": 0x5A,
    # digits
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    # function keys
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
    # navigation / editing
    "esc": 0x1B, "escape": 0x1B,
    "enter": 0x0D, "return": 0x0D,
    "space": 0x20, "spacebar": 0x20,
    "tab": 0x09,
    "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    # modifiers
    "shift": 0x10, "shiftleft": 0xA0, "shiftright": 0xA1,
    "ctrl": 0x11, "control": 0x11, "ctrlleft": 0xA2, "ctrlright": 0xA3,
    "alt": 0x12, "altleft": 0xA4, "altright": 0xA5,
    "win": 0x5B, "winleft": 0x5B, "winright": 0x5C,
    # common presentation keys
    "leftbracket": 0xDB, "[": 0xDB,
    "rightbracket": 0xDD, "]": 0xDD,
}


def _key_to_vk(key: str) -> int:
    """Return a Windows VK code for a pyautogui-style key name."""
    k = key.lower().strip()
    if k in _VK_MAP:
        return _VK_MAP[k]
    # Single character fallback (covers punctuation not explicitly listed).
    if len(k) == 1:
        return ord(k.upper())
    raise ValueError(f"unsupported key name: {key!r}")


def _send_key_input(vk: int, up: bool) -> None:
    flags = 0
    # Extended keys: right-side modifiers, arrow keys, navigation cluster.
    if vk in (0xA1, 0xA3, 0xA5, 0x5C, 0x25, 0x26, 0x27, 0x28,
              0x21, 0x22, 0x23, 0x24, 0x2D, 0x2E):
        flags |= KEYEVENTF_EXTENDEDKEY
    if up:
        flags |= KEYEVENTF_KEYUP
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp._.ki.wVk = vk
    inp._.ki.wScan = 0
    inp._.ki.dwFlags = flags
    inp._.ki.time = 0
    inp._.ki.dwExtraInfo = None
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


# ── public mouse API ─────────────────────────────────────────────────────
def moveTo(x: float, y: float) -> None:
    """Move the cursor to absolute screen coordinates (clamped to screen)."""
    sw, sh = _screen_size()
    # Clamp to valid screen pixels; Windows normalizes to 0..65535.
    sx = max(0, min(sw, int(round(x))))
    sy = max(0, min(sh, int(round(y))))
    # Normalize to 0..65535 as required by MOUSEEVENTF_ABSOLUTE.
    nx = int((sx * 65535) // max(1, sw - 1)) if sw > 1 else 0
    ny = int((sy * 65535) // max(1, sh - 1)) if sh > 1 else 0
    _send_mouse_input(nx, ny, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)


def moveRel(dx: float, dy: float) -> None:
    """Move the cursor by a relative pixel delta."""
    _send_mouse_input(int(round(dx)), int(round(dy)), MOUSEEVENTF_MOVE)


def mouseDown(button: str = "left", x: float | None = None, y: float | None = None) -> None:
    """Hold the specified mouse button.

    If ``x`` and ``y`` are provided, the cursor is moved to those absolute
    screen coordinates before the button is pressed (mirrors pyautogui).
    """
    if x is not None and y is not None:
        moveTo(x, y)
    _send_mouse_input(0, 0, _button_flag(button, True))


def mouseUp(button: str = "left", x: float | None = None, y: float | None = None) -> None:
    """Release the specified mouse button.

    If ``x`` and ``y`` are provided, the cursor is moved to those absolute
    screen coordinates before the button is released (mirrors pyautogui).
    """
    if x is not None and y is not None:
        moveTo(x, y)
    _send_mouse_input(0, 0, _button_flag(button, False))


def click(button: str = "left", x: float | None = None, y: float | None = None) -> None:
    """Click the specified mouse button once.

    If ``x`` and ``y`` are provided, the cursor is moved to those absolute
    screen coordinates before clicking (mirrors pyautogui).
    """
    if x is not None and y is not None:
        moveTo(x, y)
    mouseDown(button)
    mouseUp(button)


def scroll(amount: int) -> None:
    """Scroll the mouse wheel vertically by ``amount`` (WHEEL_DELTA units)."""
    # One wheel click == 120 WHEEL_DELTA units in Windows.
    delta = int(amount) * 120
    _send_mouse_input(0, 0, MOUSEEVENTF_WHEEL, data=delta)


# ── public keyboard API ──────────────────────────────────────────────────
def keyDown(key: str) -> None:
    """Hold a key."""
    _send_key_input(_key_to_vk(key), up=False)


def keyUp(key: str) -> None:
    """Release a key."""
    _send_key_input(_key_to_vk(key), up=True)


def press(key: str) -> None:
    """Press and release a key once."""
    keyDown(key)
    keyUp(key)


def hotkey(*keys: str) -> None:
    """Press all keys in order, then release them in reverse order."""
    vks = [_key_to_vk(k) for k in keys]
    for vk in vks:
        _send_key_input(vk, up=False)
    for vk in reversed(vks):
        _send_key_input(vk, up=True)


# ── compatibility helper ─────────────────────────────────────────────────
def size() -> Tuple[int, int]:
    """Return the primary screen size in pixels (matches the legacy pyautogui.size signature)."""
    return _screen_size()
