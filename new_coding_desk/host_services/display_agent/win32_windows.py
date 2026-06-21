"""Win32 window operations for Display Agent.

All Win32 / ctypes / pywin32 access is isolated here so that the agent can be
unit-tested with mocks. When pywin32 is not available, every function returns
a stable error dict rather than raising.

Key safety properties:
  - No shell execution.
  - No user-supplied paths, URLs, or command strings.
  - Window finding is by window title substring + process name match only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class WindowInfo:
    """Information about a found window."""

    hwnd: int
    title: str
    process_name: str
    pid: int


# ── Lazy imports of pywin32 ──────────────────────────────────────────────────


def _get_win32_modules():
    """Attempt to import pywin32 modules. Returns (win32gui, win32process,
    win32api, win32con) or raises ImportError.
    """
    try:
        import win32gui
        import win32process
        import win32api
        import win32con
        return win32gui, win32process, win32api, win32con
    except ImportError as exc:
        raise ImportError(
            f"pywin32 not available: {exc}. Install with: pip install pywin32"
        )


def is_win32_available() -> bool:
    """Check if pywin32 is importable."""
    try:
        _get_win32_modules()
        return True
    except ImportError:
        return False


# ── Window enumeration ──────────────────────────────────────────────────────


def _get_process_name(pid: int) -> str:
    """Get the process name for a PID. Returns '' on error."""
    try:
        import win32api
        import win32process
        handle = win32api.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_INFO | VM_READ
        try:
            exe_path = win32process.GetModuleFileNameEx(handle, 0)
            return exe_path.split("\\")[-1]
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return ""


def find_windows_by_title(
    title_substrings: list[str],
    process_names: list[str] | None = None,
) -> list[WindowInfo]:
    """Find all top-level windows whose title contains any of the substrings.

    If process_names is provided, only windows from those processes are
    returned.

    Returns a list of WindowInfo. Empty list if pywin32 unavailable or no
    matches found.
    """
    if not is_win32_available():
        return []

    win32gui, _, _, _ = _get_win32_modules()
    matches: list[WindowInfo] = []

    def _enum_handler(hwnd, _result):
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            title = ""
        if not title:
            return

        title_lower = title.lower()
        if not any(s.lower() in title_lower for s in title_substrings):
            return

        # Optionally filter by process name
        if process_names:
            try:
                _, pid = win32gui.GetWindowThreadProcessId(hwnd)
                proc_name = _get_process_name(pid)
                proc_lower = proc_name.lower()
                if not any(p.lower() in proc_lower for p in process_names):
                    return
                matches.append(
                    WindowInfo(
                        hwnd=hwnd,
                        title=title,
                        process_name=proc_name,
                        pid=pid,
                    )
                )
            except Exception:
                pass
        else:
            try:
                _, pid = win32gui.GetWindowThreadProcessId(hwnd)
            except Exception:
                pid = 0
            matches.append(
                WindowInfo(hwnd=hwnd, title=title, process_name="", pid=pid)
            )

    try:
        win32gui.EnumWindows(_enum_handler, None)
    except Exception:
        pass

    return matches


# ── Window activation ──────────────────────────────────────────────────────


def bring_window_to_foreground(hwnd: int) -> bool:
    """Bring a window to the foreground. Returns True on success."""
    if not is_win32_available():
        return False

    win32gui, _, _, win32con = _get_win32_modules()
    try:
        # If minimized, restore
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        # Bring to foreground
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def move_window_to_display(hwnd: int, display_index: int) -> bool:
    """Move a window to a specific display and maximize it.

    If display_index is -1, uses the primary monitor.
    Returns True on success.
    """
    if not is_win32_available():
        return False

    win32gui, _, win32api, win32con = _get_win32_modules()
    try:
        # Enumerate monitors
        monitors = win32api.EnumDisplayMonitors()
        if not monitors:
            return False

        if display_index < 0 or display_index >= len(monitors):
            display_index = 0

        # Get the target monitor's coordinates
        _, _, monitor_info = monitors[display_index]
        # monitor_info is (left, top, right, bottom)
        left, top, right, bottom = monitor_info

        # Move window to that monitor
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOP,
            left,
            top,
            right - left,
            bottom - top,
            win32con.SWP_NOZORDER | 0,
        )
        # Maximize
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        return True
    except Exception:
        return False


def is_process_running(process_name_substr: str) -> bool:
    """Check whether a process whose name contains the substring is running."""
    try:
        import psutil
    except ImportError:
        return False
    try:
        needle = process_name_substr.lower()
        for proc in psutil.process_iter(["name"]):
            name = proc.info.get("name", "") or ""
            if needle in name.lower():
                return True
        return False
    except Exception:
        return False


# ── Combined operations ────────────────────────────────────────────────────


def find_powerpoint_windows() -> list[WindowInfo]:
    """Find PowerPoint windows — slideshow or editor."""
    # PowerPoint slideshow windows contain "PowerPoint Slide Show"
    # Editor windows are titled by the document name + " - PowerPoint"
    return find_windows_by_title(
        title_substrings=["powerpoint", "slide show"],
        process_names=["POWERPNT.EXE"],
    )


def find_solidworks_windows() -> list[WindowInfo]:
    """Find SolidWorks windows."""
    return find_windows_by_title(
        title_substrings=["solidworks", "sldworks"],
        process_names=["SLDWORKS.exe"],
    )


def find_smartdesk_display_windows(display_url_substr: str) -> list[WindowInfo]:
    """Find browser windows showing the SmartDesk /display page.

    The `display_url_substr` (e.g. "http://127.0.0.1:5173/display") is
    incorporated into title matching. The URL path (e.g. "/display") and
    the host suffix of the URL are used as specific substrings so unrelated
    browser tabs titled "Display Settings" or "SmartDesk admin page" do not
    false-match.

    The matching is restricted to Edge/Chrome processes.
    """
    # Derive specific substrings from the configured URL — never the
    # bare words "display" or "smartdesk" alone, which would match
    # unrelated browser tabs.
    substrings: list[str] = []
    if isinstance(display_url_substr, str) and display_url_substr:
        # URL path component (e.g. "/display") — specific enough
        # to avoid generic-title false positives.
        path_part = display_url_substr
        # Strip scheme://host:port to get the path
        if "://" in path_part:
            after_scheme = path_part.split("://", 1)[1]
            if "/" in after_scheme:
                path_part = "/" + after_scheme.split("/", 1)[1]
            else:
                path_part = "/"
        # Host suffix (e.g. "127.0.0.1:5173") — only browser tabs pointing
        # at our local host qualify.
        host_part = ""
        if "://" in display_url_substr:
            host_part = display_url_substr.split("://", 1)[1].split("/", 1)[0]
        if path_part and path_part != "/":
            substrings.append(path_part)
        if host_part:
            substrings.append(host_part)
        # Full URL as a fallback substring
        substrings.append(display_url_substr)
    # Always have at least one specific identifier
    if not substrings:
        substrings = ["smartdesk/display", "/display"]

    return find_windows_by_title(
        substrings,
        process_names=["msedge.exe", "chrome.exe"],
    )
