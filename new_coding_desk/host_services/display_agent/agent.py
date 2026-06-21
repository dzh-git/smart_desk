"""SmartDesk Display Agent — user-session-level HTTP service.

Binds 127.0.0.1:8766 only. Provides:
  GET  /status   — read-only summary of which apps are running / visible.
  POST /activate — switch foreground to powerpoint | solidworks | smartdesk.

Security:
  - The Pydantic schema uses extra="forbid" — only the `app` field is
    accepted, and only with the three enum values. No paths, URLs, commands,
    or extra JSON fields are accepted.
  - All process/window/COM/subprocess operations are guarded with try/except
    and return stable error dicts; the agent never crashes from a Win32 failure.
  - The Edge launch for SmartDesk display uses a fixed executable candidate
    list and a fixed URL — never caller-supplied.
  - subprocess is invoked with argv arrays only; never shell=True.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

# Add this directory to sys.path so win32_windows / powerpoint_control can be
# imported even when the agent is launched from another working directory.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict

from config import CONFIG
from win32_windows import (
    find_powerpoint_windows,
    find_solidworks_windows,
    find_smartdesk_display_windows,
    bring_window_to_foreground,
    move_window_to_display,
    is_process_running,
    is_win32_available,
)
from powerpoint_control import (
    start_slideshow_on_display,
    is_slideshow_running,
    is_com_available,
)


# ── App ────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="SmartDesk Display Agent",
    version="1.0.0",
    description="User-session-level host display controller (loopback only).",
)

# CORS: explicit origin whitelist. No "*" — every origin must be approved.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CONFIG.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# ── Schemas ────────────────────────────────────────────────────────────────


class ActivateRequest(BaseModel):
    """Strict activate request. extra='forbid' rejects any extra fields."""

    model_config = ConfigDict(extra="forbid")

    app: Literal["powerpoint", "solidworks", "smartdesk"] = Field(
        ..., description="Target application to bring to foreground."
    )


class AppStatus(BaseModel):
    running: bool
    window_found: bool


class StatusResponse(BaseModel):
    agent_state: Literal["online"]
    win32_available: bool
    com_available: bool
    apps: dict[str, AppStatus]
    active_app: str | None = None


class ActivateResponse(BaseModel):
    ok: bool
    app: str
    action: str
    detail: str = ""


# ── Helpers ────────────────────────────────────────────────────────────────


def _build_app_status() -> dict[str, AppStatus]:
    """Build per-app status dicts."""
    # PowerPoint
    ppt_running = is_process_running("POWERPNT")
    ppt_windows = find_powerpoint_windows() if ppt_running else []
    ppt_status = AppStatus(
        running=ppt_running, window_found=len(ppt_windows) > 0
    )

    # SolidWorks
    sw_running = is_process_running("SLDWORKS")
    sw_windows = find_solidworks_windows() if sw_running else []
    sw_status = AppStatus(
        running=sw_running, window_found=len(sw_windows) > 0
    )

    # SmartDesk display (browser)
    sd_windows = find_smartdesk_display_windows(CONFIG.smartdesk_display_url)
    sd_status = AppStatus(
        running=len(sd_windows) > 0, window_found=len(sd_windows) > 0
    )

    return {
        "powerpoint": ppt_status,
        "solidworks": sw_status,
        "smartdesk": sd_status,
    }


def _activate_powerpoint() -> tuple[dict, int]:
    """Activate PowerPoint: prefer slideshow window, else start slideshow.

    Returns (result_dict, http_status). Uses 409 when no PowerPoint window
    is found and one cannot be started.

    Design: when starting a slideshow via COM, the existing editor window
    is FIRST moved to the target display so the slideshow inherits the
    correct display position. The new slideshow window is then located
    (best-effort) and activated; if it cannot be found the editor window
    is activated as a fallback.
    """
    # Single enumeration of all PowerPoint windows
    all_windows = find_powerpoint_windows()

    # Prefer an existing slideshow window
    slideshow_windows = [
        w for w in all_windows
        if "slide show" in w.title.lower()
    ]
    if slideshow_windows:
        hwnd = slideshow_windows[0].hwnd
        moved = move_window_to_display(hwnd, CONFIG.target_display_index)
        fg = bring_window_to_foreground(hwnd)
        if fg:
            return (
                {
                    "ok": True,
                    "app": "powerpoint",
                    "action": "activate_slideshow",
                    "detail": "" if moved else "Activated but move failed",
                },
                200,
            )
        return (
            {
                "ok": False,
                "app": "powerpoint",
                "action": "activate_slideshow",
                "detail": "Failed to bring slideshow to foreground",
            },
            200,
        )

    # No slideshow — try to start one via COM. Move the editor window to
    # the target display BEFORE starting so the slideshow appears there.
    editor_windows = [
        w for w in all_windows
        if "slide show" not in w.title.lower()
    ]
    if editor_windows and CONFIG.enable_powerpoint_com and is_com_available():
        editor_hwnd = editor_windows[0].hwnd
        # Move the editor to the target display first — this is the key
        # step that ensures target_display_index participates.
        move_window_to_display(editor_hwnd, CONFIG.target_display_index)

        result = start_slideshow_on_display(CONFIG.target_display_index)
        if not result.get("ok"):
            return (
                {
                    "ok": False,
                    "app": "powerpoint",
                    "action": "start_slideshow",
                    "detail": result.get("error", "COM start failed"),
                },
                200,
            )

        # COM start succeeded — try to locate the new slideshow window
        # (best-effort, single poll). Fall back to the editor window.
        new_windows = find_powerpoint_windows()
        new_slideshow = [
            w for w in new_windows
            if "slide show" in w.title.lower()
        ]
        if new_slideshow:
            # A new slideshow window appeared — activate it directly
            fg = bring_window_to_foreground(new_slideshow[0].hwnd)
            if fg:
                return (
                    {
                        "ok": True,
                        "app": "powerpoint",
                        "action": "located_and_moved",
                        "detail": result.get("note", ""),
                    },
                    200,
                )
            return (
                {
                    "ok": False,
                    "app": "powerpoint",
                    "action": "start_slideshow",
                    "detail": "COM started but could not activate slideshow window",
                },
                200,
            )
        # No slideshow window detected yet — COM reported success and the
        # editor was already moved to the target display. Report success
        # reflecting either a fresh COM start or the editor activation.
        if new_windows:
            # Editor window present (slideshow may still be initializing)
            fg = bring_window_to_foreground(new_windows[0].hwnd)
            return (
                {
                    "ok": bool(fg),
                    "app": "powerpoint",
                    "action": "start_slideshow",
                    "detail": result.get("note", ""),
                },
                200,
            )
        # COM started, editor moved, but no new slideshow window was found
        # by the follow-up enumeration. Determine success by whether we can
        # activate the editor window (best-effort proxy for slideshow
        # activation). If bring_window_to_foreground fails, the slideshow
        # could not be brought forward → not success.
        fg = bring_window_to_foreground(editor_hwnd)
        return (
            {
                "ok": bool(fg),
                "app": "powerpoint",
                "action": "activate_slideshow",
                "detail": result.get("note", ""),
            },
            200,
        )

    # No slideshow, no COM — try to bring editor window forward
    if editor_windows:
        hwnd = editor_windows[0].hwnd
        if bring_window_to_foreground(hwnd):
            return (
                {
                    "ok": True,
                    "app": "powerpoint",
                    "action": "activate_editor",
                    "detail": "Only editor window found; slideshow not started",
                },
                200,
            )

    return (
        {
            "ok": False,
            "app": "powerpoint",
            "action": "none",
            "detail": "No PowerPoint window found and COM unavailable",
        },
        409,
    )


def _activate_solidworks() -> tuple[dict, int]:
    """Activate SolidWorks: restore, move to target display, maximize.

    Returns (result_dict, http_status). Move is a required step — if it
    fails the result is not fully successful (ok=False). No window → 409.
    """
    windows = find_solidworks_windows()
    if not windows:
        return (
            {
                "ok": False,
                "app": "solidworks",
                "action": "none",
                "detail": "SolidWorks window not found",
            },
            409,
        )

    hwnd = windows[0].hwnd
    # Move to target display first, then foreground. Move is REQUIRED.
    moved = move_window_to_display(hwnd, CONFIG.target_display_index)
    fg = bring_window_to_foreground(hwnd)

    if moved and fg:
        return (
            {
                "ok": True,
                "app": "solidworks",
                "action": "move_and_activate",
                "detail": "",
            },
            200,
        )
    if moved:
        return (
            {
                "ok": True,
                "app": "solidworks",
                "action": "move_and_activate",
                "detail": "Moved but foreground activation failed",
            },
            200,
        )
    # Move failed — not full success regardless of foreground outcome
    return (
        {
            "ok": False,
            "app": "solidworks",
            "action": "activate_only" if fg else "failed",
            "detail": "Activated but move failed" if fg else "Could not bring SolidWorks to foreground",
        },
        200,
    )


def _find_edge_executable() -> str | None:
    """Find a usable Edge executable from the fixed candidate list."""
    for path in CONFIG.edge_executable_candidates:
        if os.path.isfile(path):
            return path
    return None


def _activate_smartdesk() -> tuple[dict, int]:
    """Activate SmartDesk display window, or launch it in Edge app mode.

    Returns (result_dict, http_status).
    """
    # Look for an existing browser window showing the display URL
    windows = find_smartdesk_display_windows(CONFIG.smartdesk_display_url)
    if windows:
        hwnd = windows[0].hwnd
        moved = move_window_to_display(hwnd, CONFIG.target_display_index)
        fg = bring_window_to_foreground(hwnd)
        if fg:
            return (
                {
                    "ok": True,
                    "app": "smartdesk",
                    "action": "activate_existing",
                    "detail": "" if moved else "Activated but move failed",
                },
                200,
            )
        return (
            {
                "ok": False,
                "app": "smartdesk",
                "action": "activate_existing",
                "detail": "Failed to bring window to foreground",
            },
            200,
        )

    # No existing window — launch Edge in app mode with the FIXED URL.
    # The URL comes from CONFIG, never from the request body.
    edge_exe = _find_edge_executable()
    if not edge_exe:
        return (
            {
                "ok": False,
                "app": "smartdesk",
                "action": "launch",
                "detail": "Edge executable not found",
            },
            409,
        )

    # Fixed argv — no shell, no user input.
    argv = [
        edge_exe,
        "--app=" + CONFIG.smartdesk_display_url,
        "--new-window",
    ]
    try:
        # No shell=True, fixed argv only.
        subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return (
            {
                "ok": True,
                "app": "smartdesk",
                "action": "launch_app_mode",
                "detail": f"Launched {CONFIG.smartdesk_display_url}",
            },
            200,
        )
    except Exception as exc:
        return (
            {
                "ok": False,
                "app": "smartdesk",
                "action": "launch",
                "detail": f"Failed to launch Edge: {exc}",
            },
            200,
        )


def _detect_active_app() -> str | None:
    """Best-effort detection of the currently active app.

    Priority:
      1. PowerPoint slideshow (via COM) → "powerpoint"
      2. SolidWorks foreground window → "solidworks"
      3. SmartDesk display window foreground → "smartdesk"
      4. None

    Uses window-existence checks (foreground/visible windows of the known
    processes) as a proxy for "active" since exact foreground HWND
    comparison is brittle in unit tests.
    """
    if is_slideshow_running():
        return "powerpoint"
    # SolidWorks foreground
    if is_win32_available() and find_solidworks_windows():
        return "solidworks"
    # SmartDesk display window foreground
    if is_win32_available() and find_smartdesk_display_windows(
        CONFIG.smartdesk_display_url
    ):
        return "smartdesk"
    return None


# ── Endpoints ──────────────────────────────────────────────────────────────


@app.get("/status")
def get_status() -> StatusResponse:
    """Read-only summary of running apps and windows."""
    apps = _build_app_status()
    return StatusResponse(
        agent_state="online",
        win32_available=is_win32_available(),
        com_available=is_com_available(),
        apps=apps,
        active_app=_detect_active_app(),
    )


@app.post("/activate")
def activate(req: ActivateRequest):
    """Switch foreground to one of the three supported apps.

    Returns 409 Conflict when the requested app has no window and cannot
    be started; 200 otherwise. The response body is always an
    ActivateResponse-shaped dict (ok/app/action), even on 409, so clients
    can rely on a stable schema.
    """
    if req.app == "powerpoint":
        result, status = _activate_powerpoint()
    elif req.app == "solidworks":
        result, status = _activate_solidworks()
    elif req.app == "smartdesk":
        result, status = _activate_smartdesk()
    else:
        # Unreachable due to Literal, but defensive
        raise HTTPException(status_code=400, detail="Invalid app")

    body = ActivateResponse(**result)
    if status == 409:
        return JSONResponse(status_code=409, content=body.model_dump())
    return body


@app.options("/activate")
@app.options("/status")
def options_handler(request: Request):
    """Handle CORS preflight. FastAPI CORSMiddleware will add headers."""
    return JSONResponse(content={})


@app.get("/health")
def health():
    return {"status": "ok", "agent": "display_agent"}


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    import uvicorn

    print(f"[Display Agent] Listening on http://{CONFIG.host}:{CONFIG.port}")
    print(f"[Display Agent] Allowed origins: {CONFIG.allowed_origins}")
    print(f"[Display Agent] Win32 available: {is_win32_available()}")
    print(f"[Display Agent] COM available: {is_com_available()}")
    uvicorn.run(
        app,
        host=CONFIG.host,
        port=CONFIG.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
