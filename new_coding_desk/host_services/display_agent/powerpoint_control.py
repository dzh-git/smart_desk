"""PowerPoint COM automation.

Isolated from win32_windows.py to keep concerns separate. When COM is not
available, returns a stable error dict instead of raising.

The only operations are:
  - Detect whether a slideshow is currently running.
  - Start a slideshow on a target display via COM.

No arbitrary path/command acceptance — only the existing open presentation
is affected.
"""

from __future__ import annotations

from typing import Optional


def is_com_available() -> bool:
    """Check if pythoncom + win32com are importable."""
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        return False


def is_slideshow_running() -> bool:
    """Check whether PowerPoint is currently running a slideshow."""
    if not is_com_available():
        return False
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            app = win32com.client.GetActiveObject("PowerPoint.Application")
            try:
                # SlideShowWindow exists only during a slideshow
                if app.SlideShowWindows.Count > 0:
                    return True
            except Exception:
                pass
            return False
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return False


def start_slideshow_on_display(display_index: int) -> dict:
    """Start a slideshow for the currently-open presentation.

    Returns a dict:
      {"ok": True} on success
      {"ok": False, "error": "<reason>", "code": "<stable_code>"}
    """
    if not is_com_available():
        return {
            "ok": False,
            "error": "COM not available (pythoncom/win32com missing)",
            "code": "com_unavailable",
        }
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            try:
                app = win32com.client.GetActiveObject("PowerPoint.Application")
            except Exception:
                return {
                    "ok": False,
                    "error": "PowerPoint COM object not found",
                    "code": "powerpoint_not_running",
                }

            try:
                presentations = app.Presentations
            except Exception:
                # Some Office ROT proxies expose only the application shell.
                # Dispatch re-wraps the same running instance with its full
                # PowerPoint automation interface instead of starting a new
                # process when PowerPoint is already active.
                app = win32com.client.Dispatch("PowerPoint.Application")
                presentations = app.Presentations

            if presentations.Count == 0:
                return {
                    "ok": False,
                    "error": "No presentation open in PowerPoint",
                    "code": "no_presentation",
                }

            presentation = presentations.Item(1)

            # If a slideshow is already running, don't restart it
            if app.SlideShowWindows.Count > 0:
                return {"ok": True, "note": "slideshow already running"}

            # Start the slideshow
            try:
                presentation.SlideShowSettings.Run()
                return {"ok": True}
            except Exception as exc:
                return {
                    "ok": False,
                    "error": f"Failed to start slideshow: {exc}",
                    "code": "slideshow_start_failed",
                }
        finally:
            pythoncom.CoUninitialize()
    except Exception as exc:
        return {
            "ok": False,
            "error": f"COM error: {exc}",
            "code": "com_error",
        }
