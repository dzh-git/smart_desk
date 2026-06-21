"""
Tests for the Display Agent — uses FastAPI TestClient with all Win32/COM/
subprocess operations mocked.

Covers:
  - GET /status (online, app states)
  - POST /activate for all three apps
  - Schema strictness (extra fields rejected, invalid app rejected)
  - CORS allow/deny
  - Window not found → stable error
  - COM unavailable → stable error
  - No shell=True in any subprocess call
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


# ── Path setup ──────────────────────────────────────────────────────────────

AGENT_DIR = (
    Path(__file__).resolve().parent.parent / "host_services" / "display_agent"
)
sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture
def client():
    """Create a TestClient with all Win32/COM deps mocked as unavailable by
    default; individual tests can override.
    """
    import agent
    import config as agent_config

    # Patch config to deterministic state
    with patch.object(agent, "CONFIG") as mock_cfg:
        mock_cfg.host = "127.0.0.1"
        mock_cfg.port = 8766
        mock_cfg.allowed_origins = [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
        mock_cfg.smartdesk_display_url = "http://127.0.0.1:5173/display"
        mock_cfg.edge_executable_candidates = ["/nonexistent/msedge.exe"]
        mock_cfg.target_display_index = 0
        mock_cfg.enable_powerpoint_com = True
        mock_cfg.is_origin_allowed = agent_config.AgentConfig.is_origin_allowed.__get__(mock_cfg)

        with TestClient(agent.app) as c:
            yield c


# ── GET /status ──────────────────────────────────────────────────────────────


def test_status_returns_online(client):
    """Status endpoint returns agent_state=online."""
    with patch("agent.is_win32_available", return_value=False), \
         patch("agent.is_com_available", return_value=False), \
         patch("agent.is_process_running", return_value=False), \
         patch("agent.find_powerpoint_windows", return_value=[]), \
         patch("agent.find_solidworks_windows", return_value=[]), \
         patch("agent.find_smartdesk_display_windows", return_value=[]), \
         patch("agent.is_slideshow_running", return_value=False):
        resp = client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_state"] == "online"
    assert data["win32_available"] is False
    assert data["com_available"] is False
    assert "powerpoint" in data["apps"]
    assert "solidworks" in data["apps"]
    assert "smartdesk" in data["apps"]
    assert data["apps"]["powerpoint"]["running"] is False
    assert data["apps"]["powerpoint"]["window_found"] is False


def test_status_detects_running_apps(client):
    """Status reflects running process + found windows."""
    from win32_windows import WindowInfo
    fake_window = WindowInfo(hwnd=12345, title="doc.pptx - PowerPoint",
                             process_name="POWERPNT.EXE", pid=999)
    with patch("agent.is_win32_available", return_value=True), \
         patch("agent.is_com_available", return_value=True), \
         patch("agent.is_process_running", side_effect=lambda n: "POWERPNT" in n.upper()), \
         patch("agent.find_powerpoint_windows", return_value=[fake_window]), \
         patch("agent.find_solidworks_windows", return_value=[]), \
         patch("agent.find_smartdesk_display_windows", return_value=[]), \
         patch("agent.is_slideshow_running", return_value=True):
        resp = client.get("/status")
    data = resp.json()
    assert data["apps"]["powerpoint"]["running"] is True
    assert data["apps"]["powerpoint"]["window_found"] is True
    assert data["active_app"] == "powerpoint"


# ── POST /activate — valid apps ─────────────────────────────────────────────


def test_activate_powerpoint_slideshow_existing(client):
    """Activate PowerPoint when slideshow window exists → activate_slideshow."""
    from win32_windows import WindowInfo
    fake_window = WindowInfo(
        hwnd=1, title="PowerPoint Slide Show - doc",
        process_name="POWERPNT.EXE", pid=1,
    )
    with patch("agent.find_powerpoint_windows", return_value=[fake_window]), \
         patch("agent.bring_window_to_foreground", return_value=True):
        resp = client.post("/activate", json={"app": "powerpoint"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["app"] == "powerpoint"
    assert data["action"] == "activate_slideshow"


def test_activate_powerpoint_start_slideshow_via_com(client):
    """No slideshow → start via COM."""
    editor_window = WindowInfoStub(2, "doc.pptx - PowerPoint")
    with patch("agent.find_powerpoint_windows", return_value=[editor_window]), \
         patch("agent.is_com_available", return_value=True), \
         patch("agent.start_slideshow_on_display",
               return_value={"ok": True}), \
         patch("agent.bring_window_to_foreground", return_value=True):
        resp = client.post("/activate", json={"app": "powerpoint"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["action"] == "start_slideshow"


def test_activate_solidworks_move_and_activate(client):
    """SolidWorks window found → move + activate."""
    from win32_windows import WindowInfo
    fake_window = WindowInfo(hwnd=3, title="part.sldprt - SolidWorks",
                             process_name="SLDWORKS.exe", pid=3)
    with patch("agent.find_solidworks_windows", return_value=[fake_window]), \
         patch("agent.move_window_to_display", return_value=True), \
         patch("agent.bring_window_to_foreground", return_value=True):
        resp = client.post("/activate", json={"app": "solidworks"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["action"] == "move_and_activate"


def test_activate_smartdesk_existing_window(client):
    """SmartDesk display window exists → activate."""
    from win32_windows import WindowInfo
    fake_window = WindowInfo(
        hwnd=4, title="SmartDesk Display",
        process_name="msedge.exe", pid=4,
    )
    with patch("agent.find_smartdesk_display_windows", return_value=[fake_window]), \
         patch("agent.bring_window_to_foreground", return_value=True):
        resp = client.post("/activate", json={"app": "smartdesk"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["action"] == "activate_existing"


def test_activate_smartdesk_launches_edge_app_mode(client):
    """No existing window → launch Edge with FIXED argv (no shell)."""
    with patch("agent.find_smartdesk_display_windows", return_value=[]), \
         patch("agent._find_edge_executable", return_value="/fake/msedge.exe"), \
         patch("agent.subprocess.Popen") as mock_popen:
        resp = client.post("/activate", json={"app": "smartdesk"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["action"] == "launch_app_mode"
    # Verify subprocess called with argv list, no shell
    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    cmd_list = args[0]
    assert isinstance(cmd_list, list)
    assert "--app=http://127.0.0.1:5173/display" in cmd_list
    assert kwargs.get("shell") in (None, False)


# ── POST /activate — error cases ────────────────────────────────────────────


def test_activate_solidworks_window_not_found(client):
    """SolidWorks not found → 409 Conflict with stable body, no crash."""
    with patch("agent.find_solidworks_windows", return_value=[]):
        resp = client.post("/activate", json={"app": "solidworks"})
    assert resp.status_code == 409
    data = resp.json()
    assert data["ok"] is False
    assert "not found" in data["detail"].lower()


def test_activate_powerpoint_com_unavailable(client):
    """PowerPoint with no slideshow + COM unavailable → graceful error."""
    editor_window = WindowInfoStub(5, "doc.pptx - PowerPoint")
    with patch("agent.find_powerpoint_windows", return_value=[editor_window]), \
         patch("agent.is_com_available", return_value=False), \
         patch("agent.bring_window_to_foreground", return_value=True):
        resp = client.post("/activate", json={"app": "powerpoint"})
    # Falls through to editor window activation
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["action"] == "activate_editor"


def test_activate_smartdesk_edge_not_found(client):
    """No window + Edge missing → 409 Conflict with stable body."""
    with patch("agent.find_smartdesk_display_windows", return_value=[]), \
         patch("agent._find_edge_executable", return_value=None):
        resp = client.post("/activate", json={"app": "smartdesk"})
    assert resp.status_code == 409
    data = resp.json()
    assert data["ok"] is False
    assert "edge" in data["detail"].lower()


# ── Schema strictness ───────────────────────────────────────────────────────


def test_activate_rejects_invalid_app(client):
    """Invalid app value → 422."""
    resp = client.post("/activate", json={"app": "notepad"})
    assert resp.status_code == 422


def test_activate_rejects_extra_fields(client):
    """Extra fields → 422 (extra='forbid')."""
    resp = client.post("/activate", json={"app": "powerpoint", "path": "evil.exe"})
    assert resp.status_code == 422


def test_activate_rejects_url_injection(client):
    """URL field rejected."""
    resp = client.post("/activate", json={
        "app": "powerpoint",
        "url": "http://evil.example.com/"
    })
    assert resp.status_code == 422


def test_activate_rejects_command_injection(client):
    """command field rejected."""
    resp = client.post("/activate", json={
        "app": "smartdesk",
        "command": "rm -rf /"
    })
    assert resp.status_code == 422


def test_activate_rejects_missing_app(client):
    """Missing app field → 422."""
    resp = client.post("/activate", json={})
    assert resp.status_code == 422


# ── CORS ────────────────────────────────────────────────────────────────────


def test_cors_allows_allowed_origin(client):
    """CORS preflight from allowed origin succeeds."""
    resp = client.options(
        "/activate",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    # CORSMiddleware responds to preflight
    assert resp.status_code in (200, 204)
    # The allow-origin header should be set
    assert resp.headers.get("access-control-allow-origin") in (
        "http://127.0.0.1:5173",
        "*",
    )


def test_cors_rejects_disallowed_origin(client):
    """CORS preflight from disallowed origin returns no allow-origin header."""
    resp = client.options(
        "/activate",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    # CORS middleware does not set allow-origin for disallowed origins
    allow_origin = resp.headers.get("access-control-allow-origin")
    # Should be absent or not the evil origin
    assert allow_origin != "http://evil.example.com"


# ── No shell=True invariant ─────────────────────────────────────────────────


def test_no_shell_true_in_subprocess_calls(client):
    """No subprocess call in the agent uses shell=True."""
    # Launching SmartDesk when no window exists triggers subprocess.Popen
    with patch("agent.find_smartdesk_display_windows", return_value=[]), \
         patch("agent._find_edge_executable", return_value="/fake/msedge.exe"), \
         patch("agent.subprocess.Popen") as mock_popen:
        client.post("/activate", json={"app": "smartdesk"})
    mock_popen.assert_called_once()
    _, kwargs = mock_popen.call_args
    assert kwargs.get("shell") is not True


# ── Helper ──────────────────────────────────────────────────────────────────


class WindowInfoStub:
    """Lightweight stub matching win32_windows.WindowInfo signature."""

    def __init__(self, hwnd, title, process_name="", pid=0):
        self.hwnd = hwnd
        self.title = title
        self.process_name = process_name
        self.pid = pid
