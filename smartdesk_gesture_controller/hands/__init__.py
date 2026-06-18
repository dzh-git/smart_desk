"""SmartDesk local gesture-control package.

This package is a **standalone process**, not part of the FastAPI backend.
It captures the host camera, classifies hand gestures via MediaPipe, and
drives the Windows mouse/keyboard through pyautogui so a presenter can
control PowerPoint, SolidWorks and other desktop apps — including the
``/display`` page — without touching the mouse.

The public surface is intentionally tiny: only :class:`GestureController`
is re-exported. Internal modules (config, actions, state, recognition,
status server) are implementation details and may change between releases.

Run it as a module from the repository root:

    python -m hands.gesture_controller
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .gesture_controller import GestureController
    from .gesture_state import ActionIntent, Gesture


def __getattr__(name: str) -> Any:
    if name == "GestureController":
        from .gesture_controller import GestureController

        return GestureController
    if name in {"Gesture", "ActionIntent"}:
        from .gesture_state import ActionIntent, Gesture

        return {"Gesture": Gesture, "ActionIntent": ActionIntent}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["GestureController", "Gesture", "ActionIntent"]
