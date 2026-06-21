"""
Phase 2 review contract tests for Windows Display Agent.

These tests verify BEHAVIORAL and STRUCTURAL contracts NOT covered by
test_display_agent.py.  Areas covered:

  A. Agent Network Boundary (host/IP validation, CORS configuration)
  B. Activate Request Security (injection fields, fixed URL/executable)
  C. PowerPoint (target_display_index, post-launch window management, 409 on
     no window, COM/Win32 unavailability)
  D. SolidWorks (move failure → ok=False, 409 on no window)
  E. SmartDesk (URL parameter used in window matching, no generic-title
     false match, Edge no-shell, fixed URL)
  F. active_app (full detection for all three apps, not just PowerPoint)
  G. Dependencies (pywin32, psutil in requirements.txt, platform markers,
     README runtime model)

Tests that fail due to current production defects are EXPECTED_FAIL and
document known gaps for ZCode.  There must be 0 import/fixture/test-errors.

Usage:
    pytest tests/test_display_agent_review_contract.py -v
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

AGENT_DIR = (
    Path(__file__).resolve().parent.parent / "host_services" / "display_agent"
)
sys.path.insert(0, str(AGENT_DIR))


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    """Standard TestClient with all Win32/COM/subprocess mocked.

    Individual tests override specific mocks as needed.  By default all
    Win32/COM is unavailable and all processes are not running.
    """
    import agent
    import config as agent_config

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
        mock_cfg.is_origin_allowed = (
            agent_config.AgentConfig.is_origin_allowed.__get__(mock_cfg)
        )

        with patch("agent.is_win32_available", return_value=False), \
             patch("agent.is_com_available", return_value=False), \
             patch("agent.is_process_running", return_value=False), \
             patch("agent.find_powerpoint_windows", return_value=[]), \
             patch("agent.find_solidworks_windows", return_value=[]), \
             patch("agent.find_smartdesk_display_windows", return_value=[]), \
             patch("agent.is_slideshow_running", return_value=False), \
             patch("agent.bring_window_to_foreground", return_value=True), \
             patch("agent.move_window_to_display", return_value=True), \
             patch("agent.subprocess.Popen") as mock_popen, \
             TestClient(agent.app) as c:
            mock_popen_obj = MagicMock()
            mock_popen_obj.pid = 9999
            mock_popen_obj.returncode = None
            mock_popen.return_value = mock_popen_obj
            yield c


@pytest.fixture
def agent_dir() -> Path:
    """Convenience: absolute path to the display agent directory."""
    return AGENT_DIR


# =====================================================================
# A. Agent Network Boundary
# =====================================================================


class TestAgentNetworkBoundary:
    """Config / host must enforce loopback-only binding."""

    def test_default_host_is_127001(self) -> None:
        """AgentConfig default host is 127.0.0.1."""
        import config
        cfg = config.AgentConfig()
        assert cfg.host == "127.0.0.1", (
            f"Default host must be 127.0.0.1, got '{cfg.host}'"
        )

    def test_non_loopback_host_0_0_0_0_rejected(
        self, tmp_path, monkeypatch
    ) -> None:
        """[EXPECTED_FAIL] AgentConfig.load() must reject host='0.0.0.0'.

        Production defect: config.json can set any host value without
        validation.  The agent will bind all interfaces.
        """
        import config as cfg_mod
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('{"host": "0.0.0.0"}', encoding="utf-8")
        monkeypatch.setattr(cfg_mod, "SCRIPT_DIR", tmp_path)
        cfg = cfg_mod.AgentConfig.load()
        # If validation existed, host would be forced to 127.0.0.1.
        # Currently 0.0.0.0 is accepted — this assertion reveals the gap.
        assert cfg.host == "127.0.0.1", (
            f"Non-loopback host '0.0.0.0' accepted without validation. "
            f"AgentConfig must validate host on load()."
        )

    def test_lan_ip_host_rejected(self, tmp_path, monkeypatch) -> None:
        """[EXPECTED_FAIL] AgentConfig must reject LAN IP like 192.168.x.x."""
        import config as cfg_mod
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('{"host": "192.168.1.100"}', encoding="utf-8")
        monkeypatch.setattr(cfg_mod, "SCRIPT_DIR", tmp_path)
        cfg = cfg_mod.AgentConfig.load()
        assert cfg.host == "127.0.0.1", (
            f"LAN IP '192.168.1.100' accepted without validation. "
            f"AgentConfig must enforce loopback-only hosts."
        )

    def test_ipv6_wildcard_host_rejected(self, tmp_path, monkeypatch) -> None:
        """[EXPECTED_FAIL] AgentConfig must reject IPv6 wildcard '::'."""
        import config as cfg_mod
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('{"host": "::"}', encoding="utf-8")
        monkeypatch.setattr(cfg_mod, "SCRIPT_DIR", tmp_path)
        cfg = cfg_mod.AgentConfig.load()
        assert cfg.host == "127.0.0.1", (
            f"IPv6 wildcard '::' accepted without validation. "
            f"AgentConfig must enforce loopback-only hosts."
        )

    def test_port_0_rejected(self, tmp_path, monkeypatch) -> None:
        """[EXPECTED_FAIL] Port 0 must be rejected."""
        import config as cfg_mod
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('{"port": 0}', encoding="utf-8")
        monkeypatch.setattr(cfg_mod, "SCRIPT_DIR", tmp_path)
        cfg = cfg_mod.AgentConfig.load()
        assert cfg.port > 0, (
            f"Port 0 was accepted without validation. "
            f"Valid ports are 1-65535."
        )

    def test_port_99999_rejected(self, tmp_path, monkeypatch) -> None:
        """[EXPECTED_FAIL] Port >65535 must be rejected."""
        import config as cfg_mod
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('{"port": 99999}', encoding="utf-8")
        monkeypatch.setattr(cfg_mod, "SCRIPT_DIR", tmp_path)
        cfg = cfg_mod.AgentConfig.load()
        assert 0 < cfg.port <= 65535, (
            f"Port 99999 was accepted without validation."
        )

    def test_cors_middleware_explicit_origins(self) -> None:
        """CORSMiddleware uses explicit origins, not wildcard."""
        import agent
        for mw in agent.app.user_middleware:
            if mw.cls == CORSMiddleware:
                origins = mw.kwargs.get("allow_origins", [])
                assert origins != ["*"], "CORS must not use wildcard origins"
                assert "*" not in origins, (
                    "CORS origins must be explicit, not wildcard"
                )
                return
        pytest.fail("No CORSMiddleware registered on the agent app")

    def test_cors_no_credentials_with_wildcard(self) -> None:
        """CORS must not combine '*' origins with credentials=True.

        Current code has allow_credentials=False, so this is safe.
        The test guards against a future regression.
        """
        import agent
        for mw in agent.app.user_middleware:
            if mw.cls == CORSMiddleware:
                origins = mw.kwargs.get("allow_origins", [])
                creds = mw.kwargs.get("allow_credentials", False)
                if "*" in origins or origins == ["*"]:
                    assert not creds, (
                        "CORS '*' with allow_credentials=True is insecure"
                    )
                return

    def test_cors_status_endpoint_rejects_unknown_origin(self, client) -> None:
        """OPTIONS /status from unknown origin gets no allow-origin header."""
        resp = client.options(
            "/status",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        allow = resp.headers.get("access-control-allow-origin")
        assert allow != "http://evil.example.com", (
            f"Unknown origin received allow-origin: {allow}"
        )

    def test_config_host_cannot_be_empty_string(self, tmp_path, monkeypatch) -> None:
        """[EXPECTED_FAIL] AgentConfig.load() must reject empty host string.

        Uses config.json with host="" to test via the load path, not a
        direct attribute set on a non-validated object.
        """
        import config as cfg_mod
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('{"host": ""}', encoding="utf-8")
        monkeypatch.setattr(cfg_mod, "SCRIPT_DIR", tmp_path)
        cfg = cfg_mod.AgentConfig.load()
        assert cfg.host == "127.0.0.1", (
            f"Empty host string in config.json was accepted without "
            f"validation. Loaded host='{cfg.host}' — should be forced "
            f"to '127.0.0.1'."
        )


# =====================================================================
# B. Activate Request Security
# =====================================================================


class TestActivateSecurity:
    """POST /activate rejects injection and uses only fixed values."""

    def test_activate_rejects_command_injection(self, client) -> None:
        """command field rejected with 422."""
        resp = client.post("/activate", json={
            "app": "smartdesk", "command": "rm -rf /"
        })
        assert resp.status_code == 422

    def test_activate_rejects_process_field(self, client) -> None:
        """process field rejected."""
        resp = client.post("/activate", json={
            "app": "powerpoint", "process": "calc.exe"
        })
        assert resp.status_code == 422

    def test_activate_rejects_args_field(self, client) -> None:
        """args field rejected."""
        resp = client.post("/activate", json={
            "app": "solidworks", "args": ["--dangerous"]
        })
        assert resp.status_code == 422

    def test_activate_smartdesk_uses_fixed_executable(self, client) -> None:
        """SmartDesk Edge launch uses fixed candidate list, not request body.

        Verify by checking that no executable path from the request reaches
        subprocess.Popen — the executable is always from CONFIG.
        """
        import agent
        with patch("agent.find_smartdesk_display_windows", return_value=[]), \
             patch("agent._find_edge_executable",
                   return_value="/fixed/msedge.exe"), \
             patch("agent.subprocess.Popen") as mock_popen:
            resp = client.post("/activate", json={"app": "smartdesk"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True, (
            f"Expected ok=True for SmartDesk launch. Got: {data}"
        )
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert isinstance(args, list)
        # The executable in argv must be from the fixed list, not user-supplied
        executable = args[0]
        assert "fixed" in executable, (
            f"Edge executable must come from config's fixed candidate list, "
            f"got: {executable}"
        )
        # Verify the URL is from config, not from request body
        display_url_flag = next(
            (a for a in args if a.startswith("--app=")), None
        )
        assert display_url_flag is not None, (
            "Edge must be launched with --app= flag"
        )
        assert agent.CONFIG.smartdesk_display_url in display_url_flag, (
            "The --app= URL must come from CONFIG.smartdesk_display_url, "
            "not from the request body"
        )


# =====================================================================
# C. PowerPoint Behavior
# =====================================================================


class TestPowerPointBehavior:
    """PowerPoint activation: slideshow window, COM start, display placement."""

    def test_activate_powerpoint_prefers_slideshow_window(self, client) -> None:
        """Existing slideshow window → activate_slideshow."""
        from win32_windows import WindowInfo
        slideshow = WindowInfo(
            hwnd=100, title="PowerPoint Slide Show - doc.pptx",
            process_name="POWERPNT.EXE", pid=1001,
        )
        with patch("agent.find_powerpoint_windows", return_value=[slideshow]), \
             patch("agent.bring_window_to_foreground", return_value=True), \
             patch("agent.is_slideshow_running", return_value=True):
            resp = client.post("/activate", json={"app": "powerpoint"})
        assert resp.status_code == 200
        assert resp.json()["action"] == "activate_slideshow"

    def test_powerpoint_editor_starts_slideshow_via_com(self, client) -> None:
        """Only editor window → starts slideshow via COM."""
        from win32_windows import WindowInfo
        editor = WindowInfo(
            hwnd=101, title="doc.pptx - PowerPoint",
            process_name="POWERPNT.EXE", pid=1001,
        )
        with patch("agent.find_powerpoint_windows", return_value=[editor]), \
             patch("agent.is_com_available", return_value=True), \
             patch("agent.start_slideshow_on_display",
                   return_value={"ok": True, "note": ""}), \
             patch("agent.bring_window_to_foreground", return_value=True):
            resp = client.post("/activate", json={"app": "powerpoint"})
        assert resp.status_code == 200
        assert resp.json()["action"] == "start_slideshow"

    def test_powerpoint_target_display_participates(self, client) -> None:
        """[EXPECTED_FAIL] target_display_index must be used in window movement.

        Production defect: start_slideshow_on_display() receives the
        display_index parameter but never uses it — calls
        presentation.SlideShowSettings.Run() without display targeting.
        After launching, the agent must locate the new slideshow window
        and move it to the target display.
        """
        import agent
        from win32_windows import WindowInfo
        editor = WindowInfo(
            hwnd=101, title="doc.pptx - PowerPoint",
            process_name="POWERPNT.EXE", pid=1001,
        )
        # Record which display_index was passed to window operations
        display_indices_used: list[int] = []

        real_move = agent.move_window_to_display

        def tracking_move(hwnd, display_index):
            display_indices_used.append(display_index)
            return True

        with patch("agent.find_powerpoint_windows", side_effect=[
            [editor],       # first call: editor only
            [],             # second call: no slideshow yet (COM starting) — irrelevant
        ]), \
             patch("agent.is_com_available", return_value=True), \
             patch("agent.start_slideshow_on_display",
                   return_value={"ok": True}), \
             patch("agent.move_window_to_display", side_effect=tracking_move), \
             patch("agent.bring_window_to_foreground", return_value=True), \
             patch.object(agent.CONFIG, "target_display_index", 2):
            client.post("/activate", json={"app": "powerpoint"})

        # target_display_index=2 must be passed to move_window_to_display
        assert 2 in display_indices_used, (
            f"target_display_index=2 was never passed to move_window_to_display. "
            f"Indices used: {display_indices_used}. "
            f"The display_index parameter is accepted by start_slideshow_on_display "
            f"but ignored (SlideShowSettings.Run() uses default display)."
        )

    def test_powerpoint_new_window_located_and_moved(self, client) -> None:
        """[EXPECTED_FAIL] After COM launch, agent must locate and move slideshow.

        Current agent starts the slideshow via COM but does not locate the
        new window, verify its position, or move it to the target display.
        """
        import agent
        from win32_windows import WindowInfo
        editor = WindowInfo(
            hwnd=101, title="doc.pptx - PowerPoint",
            process_name="POWERPNT.EXE", pid=1001,
        )
        with patch("agent.find_powerpoint_windows", side_effect=[
            [editor],        # first find: editor window exists
            [],              # after COM start: no window found yet (gap)
        ]), \
             patch("agent.is_com_available", return_value=True), \
             patch("agent.start_slideshow_on_display",
                   return_value={"ok": True, "note": ""}):
            resp = client.post("/activate", json={"app": "powerpoint"})
        data = resp.json()
        assert data["ok"] is True, (
            "After COM start the agent should locate the new slideshow "
            "window, move it to the target display, and activate it. "
            f"Got: {data}"
        )
        assert data["action"] in (
            "activate_slideshow", "located_and_moved"
        ), (
            f"Action should reflect window management after COM launch. "
            f"Got: {data['action']}"
        )

    def test_powerpoint_move_or_locate_failure_not_success(self, client) -> None:
        """[EXPECTED_FAIL] Post-launch failure must not be reported as success.

        If COM launch succeeds but the new window cannot be located or moved
        to the target display, the agent must report ok=False.
        """
        import agent
        from win32_windows import WindowInfo
        editor = WindowInfo(
            hwnd=101, title="doc.pptx - PowerPoint",
            process_name="POWERPNT.EXE", pid=1001,
        )
        with patch("agent.find_powerpoint_windows", side_effect=[
            [editor],
            [],
            [],
        ]), \
             patch("agent.is_com_available", return_value=True), \
             patch("agent.start_slideshow_on_display",
                   return_value={"ok": True, "note": ""}), \
             patch("agent.bring_window_to_foreground", return_value=False):
            resp = client.post("/activate", json={"app": "powerpoint"})
        data = resp.json()
        # Even if COM succeeds, failure to locate/activate the window
        # should result in ok=False
        assert data["ok"] is False, (
            f"Agent reported ok=True despite being unable to locate or "
            f"activate the new slideshow window. Got: {data}"
        )

    def test_powerpoint_no_window_returns_409(self, client) -> None:
        """[EXPECTED_FAIL] No PowerPoint window → 409 Conflict.

        Currently returns 200 with ok=False.
        """
        with patch("agent.find_powerpoint_windows", return_value=[]), \
             patch("agent.is_com_available", return_value=False):
            resp = client.post("/activate", json={"app": "powerpoint"})
        assert resp.status_code == 409, (
            f"No PowerPoint window should return 409, got {resp.status_code}. "
            f"Body: {resp.json()}"
        )

    def test_powerpoint_com_unavailable_stable_error(self, client) -> None:
        """COM unavailable → stable error response, agent doesn't crash."""
        with patch("agent.find_powerpoint_windows", return_value=[]), \
             patch("agent.is_com_available", return_value=False):
            resp = client.post("/activate", json={"app": "powerpoint"})
        assert resp.status_code in (200, 409), (
            f"Agent must return a stable HTTP status, got {resp.status_code}"
        )
        data = resp.json()
        assert "ok" in data
        assert "app" in data
        assert "action" in data

    def test_powerpoint_win32_unavailable_does_not_crash(self, client) -> None:
        """Win32 unavailable → agent does not crash, returns stable response."""
        with patch("agent.is_win32_available", return_value=False), \
             patch("agent.find_powerpoint_windows", return_value=[]), \
             patch("agent.is_com_available", return_value=False):
            resp = client.post("/activate", json={"app": "powerpoint"})
        assert resp.status_code in (200, 409), (
            f"Agent crashed or returned unexpected status: "
            f"{resp.status_code}"
        )


# =====================================================================
# D. SolidWorks Behavior
# =====================================================================


class TestSolidWorksBehavior:
    """SolidWorks activation: process match, display movement, error states."""

    def test_solidworks_matches_only_sldworks(self) -> None:
        """find_solidworks_windows only searches for SLDWORKS.exe process."""
        import win32_windows
        with patch("win32_windows.find_windows_by_title", return_value=[]):
            win32_windows.find_solidworks_windows()
        import win32_windows as ww
        with patch.object(ww, "find_windows_by_title", return_value=[]) as m:
            ww.find_solidworks_windows()
        _, kwargs = m.call_args
        proc_names = kwargs.get("process_names", [])
        assert all("sldworks" in p.lower() for p in proc_names), (
            f"SolidWorks window search must restrict to SLDWORKS.exe "
            f"processes. Got process_names={proc_names}"
        )

    def test_solidworks_move_failure_not_full_success(self, client) -> None:
        """[EXPECTED_FAIL] Move failure must not return ok=True.

        Currently when move fails but foreground succeeds, action='activate_only'
        with ok=True. Move is a required step — if it fails the result is not
        fully successful.
        """
        from win32_windows import WindowInfo
        fake_sw = WindowInfo(
            hwnd=3, title="part.sldprt - SolidWorks",
            process_name="SLDWORKS.exe", pid=3001,
        )
        with patch("agent.find_solidworks_windows", return_value=[fake_sw]), \
             patch("agent.move_window_to_display", return_value=False), \
             patch("agent.bring_window_to_foreground", return_value=True):
            resp = client.post("/activate", json={"app": "solidworks"})
        data = resp.json()
        assert data["ok"] is False, (
            f"SolidWorks move failure must produce ok=False. "
            f"Got ok=True with action='{data.get('action')}' — "
            f"move is a required step."
        )

    def test_solidworks_no_window_returns_409(self, client) -> None:
        """[EXPECTED_FAIL] No SolidWorks window → 409 error.

        Currently returns 200 with ok=False.
        """
        with patch("agent.find_solidworks_windows", return_value=[]):
            resp = client.post("/activate", json={"app": "solidworks"})
        assert resp.status_code == 409, (
            f"No SolidWorks window should return 409, got {resp.status_code}"
        )

    def test_solidworks_window_move_called_with_target_index(
        self, client
    ) -> None:
        """SolidWorks move_window_to_display is called with CONFIG's target."""
        import agent
        from win32_windows import WindowInfo
        fake_sw = WindowInfo(
            hwnd=3, title="part.sldprt - SolidWorks",
            process_name="SLDWORKS.exe", pid=3001,
        )
        with patch("agent.find_solidworks_windows", return_value=[fake_sw]), \
             patch("agent.move_window_to_display") as mock_move, \
             patch("agent.bring_window_to_foreground", return_value=True), \
             patch.object(agent.CONFIG, "target_display_index", 1):
            client.post("/activate", json={"app": "solidworks"})
        mock_move.assert_called_once()
        args = mock_move.call_args[0]
        assert args[1] == 1, (
            f"move_window_to_display called with display_index={args[1]}, "
            f"expected 1 (CONFIG.target_display_index)"
        )


# =====================================================================
# E. SmartDesk Behavior
# =====================================================================


class TestSmartDeskBehavior:
    """SmartDesk: precise window matching, fixed Edge launch, error states."""

    def test_smartdesk_uses_url_parameter_in_matching(self) -> None:
        """[EXPECTED_FAIL] find_smartdesk_display_windows must use URL parameter.

        Production defect: display_url_substr parameter is accepted but
        ignored — the function always searches for hardcoded ['display',
        'smartdesk'] substrings regardless of the URL argument.
        """
        import win32_windows as ww
        test_url = "http://127.0.0.1:5173/display"
        with patch.object(ww, "find_windows_by_title", return_value=[]) as m:
            ww.find_smartdesk_display_windows(test_url)
        title_substrings = m.call_args[0][0]
        assert "/display" in str(title_substrings) or test_url in str(title_substrings), (
            f"The display URL must be incorporated into title matching. "
            f"Current substrings: {title_substrings}. "
            f"The display_url_substr parameter '{test_url}' is accepted but ignored."
        )

    def test_smartdesk_matching_is_more_specific_than_generic(self) -> None:
        """[EXPECTED_FAIL] SmartDesk matching must not use generic 'display'.

        Currently any Edge/Chrome window with 'display' or 'smartdesk' in its
        title matches.  This could pick up unrelated browser tabs (e.g.
        "Display Settings", "SmartDesk admin page").
        """
        import win32_windows as ww
        with patch.object(ww, "find_windows_by_title", return_value=[]) as m:
            ww.find_smartdesk_display_windows("http://127.0.0.1:5173/display")
        title_substrings = m.call_args[0][0]
        # The matching should be specific enough to avoid false positives
        assert len(title_substrings) >= 1
        overly_generic = all(
            s.lower() in ("display", "smartdesk")
            for s in title_substrings
        )
        assert not overly_generic, (
            f"Title substrings {title_substrings} are too generic. "
            f"Must use more specific identifiers like the URL path '/display' "
            f"or process command-line arguments."
        )

    def test_smartdesk_edge_launch_no_shell(self, client) -> None:
        """Edge launched with argv list, not shell=True."""
        import agent
        with patch("agent.find_smartdesk_display_windows", return_value=[]), \
             patch("agent._find_edge_executable",
                   return_value="/fake/msedge.exe"), \
             patch("agent.subprocess.Popen") as mock_popen:
            client.post("/activate", json={"app": "smartdesk"})
        mock_popen.assert_called_once()
        _, kwargs = mock_popen.call_args
        assert kwargs.get("shell") is not True, (
            "subprocess.Popen must not use shell=True"
        )

    def test_smartdesk_edge_url_fixed_from_config(self, client) -> None:
        """Edge app URL comes from CONFIG, never from request body."""
        import agent
        with patch("agent.find_smartdesk_display_windows", return_value=[]), \
             patch("agent._find_edge_executable",
                   return_value="/fake/msedge.exe"), \
             patch.object(agent.CONFIG, "smartdesk_display_url",
                          "http://127.0.0.1:5173/display"), \
             patch("agent.subprocess.Popen") as mock_popen:
            resp = client.post("/activate", json={"app": "smartdesk"})
        assert resp.status_code == 200
        mock_popen.assert_called_once()
        argv = mock_popen.call_args[0][0]
        app_flag = next((a for a in argv if a.startswith("--app=")), "")
        assert "127.0.0.1:5173/display" in app_flag, (
            f"Edge --app flag must use the configured display URL. "
            f"Got: {app_flag}"
        )

    def test_smartdesk_no_edge_stable_error(self, client) -> None:
        """No Edge executable → stable error, no crash."""
        with patch("agent.find_smartdesk_display_windows", return_value=[]), \
             patch("agent._find_edge_executable", return_value=None):
            resp = client.post("/activate", json={"app": "smartdesk"})
        assert resp.status_code in (200, 409), (
            f"Expected stable error status, got {resp.status_code}"
        )
        data = resp.json()
        assert data["ok"] is False


# =====================================================================
# F. active_app Detection
# =====================================================================


class TestActiveAppDetection:
    """active_app must identify all three apps, not only PowerPoint."""

    def test_active_app_powerpoint_slideshow(self, client) -> None:
        """active_app='powerpoint' when slideshow is running."""
        with patch("agent.is_slideshow_running", return_value=True):
            resp = client.get("/status")
        assert resp.json()["active_app"] == "powerpoint"

    def test_active_app_solidworks_foreground(self, client) -> None:
        """[EXPECTED_FAIL] active_app='solidworks' when SolidWorks is foreground.

        Production defect: _detect_active_app() only checks
        is_slideshow_running() — it never identifies SolidWorks.
        """
        from win32_windows import WindowInfo
        fake_sw = WindowInfo(
            hwnd=3, title="part.sldprt - SolidWorks",
            process_name="SLDWORKS.exe", pid=3001,
        )
        # Current _detect_active_app doesn't use foreground window
        # detection at all — it only calls is_slideshow_running().
        # These mocks are what a correctly implemented function would use.
        with patch("agent.is_slideshow_running", return_value=False), \
             patch("agent.find_solidworks_windows", return_value=[fake_sw]), \
             patch("agent.is_win32_available", return_value=True):
            resp = client.get("/status")
        assert resp.json()["active_app"] == "solidworks", (
            "_detect_active_app should identify SolidWorks from the "
            "foreground window. Currently only checks PowerPoint slideshow."
        )

    def test_active_app_smartdesk_foreground(self, client) -> None:
        """[EXPECTED_FAIL] active_app='smartdesk' when SmartDesk is foreground.

        Production defect: same as SolidWorks — _detect_active_app never
        identifies SmartDesk.
        """
        from win32_windows import WindowInfo
        fake_sd = WindowInfo(
            hwnd=4, title="SmartDesk Display - http://127.0.0.1:5173/display",
            process_name="msedge.exe", pid=4001,
        )
        with patch("agent.is_slideshow_running", return_value=False), \
             patch("agent.find_smartdesk_display_windows",
                   return_value=[fake_sd]), \
             patch("agent.is_win32_available", return_value=True):
            resp = client.get("/status")
        assert resp.json()["active_app"] == "smartdesk", (
            "_detect_active_app should identify SmartDesk from the "
            "foreground window. Currently only checks PowerPoint slideshow."
        )

    def test_active_app_null_when_no_known_app(self, client) -> None:
        """active_app=None when no known app is in foreground."""
        with patch("agent.is_slideshow_running", return_value=False):
            resp = client.get("/status")
        assert resp.json()["active_app"] is None

    def test_active_app_field_present_in_status(self, client) -> None:
        """active_app key is always present in /status response."""
        resp = client.get("/status")
        assert "active_app" in resp.json()


# =====================================================================
# G. Dependencies and Runtime Model
# =====================================================================


class TestDependenciesAndRuntime:
    """requirements.txt, README, and runtime contract verification."""

    PROJECT_ROOT = Path(__file__).resolve().parent.parent

    def test_requirements_declares_pywin32(self) -> None:
        """[EXPECTED_FAIL] requirements.txt must declare pywin32 dependency.

        pywin32 is imported at runtime by win32_windows.py (lazy).  Without
        it the agent degrades but window operations won't work.
        """
        reqs = self.PROJECT_ROOT / "requirements.txt"
        text = reqs.read_text(encoding="utf-8")
        assert "pywin32" in text, (
            "pywin32 is required by win32_windows.py but not declared in "
            "requirements.txt"
        )

    def test_requirements_declares_psutil(self) -> None:
        """[EXPECTED_FAIL] requirements.txt must declare psutil dependency.

        psutil is used by is_process_running() in win32_windows.py.
        """
        reqs = self.PROJECT_ROOT / "requirements.txt"
        text = reqs.read_text(encoding="utf-8")
        assert "psutil" in text, (
            "psutil is used by is_process_running() but not declared in "
            "requirements.txt"
        )

    def test_requirements_windows_platform_markers(self) -> None:
        """[EXPECTED_FAIL] Windows-only deps should have platform markers.

        pywin32 and psutil are Windows-only.  They should be declared with
        a sys_platform marker so pip on other platforms doesn't try to
        install them.

        Note: when pywin32/psutil are not declared in requirements.txt at
        all (which is the current state), this test fails with an explicit
        assertion rather than skipping, because skip is not allowed per
        review contract rules.  There are separate tests that verify the
        presence of each dependency declaration individually.
        """
        reqs = self.PROJECT_ROOT / "requirements.txt"
        text = reqs.read_text(encoding="utf-8")
        has_pywin32 = "pywin32" in text
        has_psutil = "psutil" in text

        # Both deps must be declared before platform markers can be checked.
        # Since neither is present (documented by separate tests), this
        # assertion fails explicitly rather than skipping.
        assert has_pywin32 or has_psutil, (
            "Neither pywin32 nor psutil is declared in requirements.txt. "
            "Platform markers cannot be verified until both are present. "
            "See test_requirements_declares_pywin32 and "
            "test_requirements_declares_psutil for the individual gaps."
        )
        # Check for platform markers on pywin32
        if has_pywin32:
            assert "; sys_platform" in text.lower() or "; win32" in text.lower(), (
                "pywin32 should be declared with a Windows platform marker "
                "(e.g. 'pywin32; sys_platform == \"win32\"')"
            )

    def test_readme_agent_not_windows_service(self) -> None:
        """README explicitly states agent is NOT a Windows Service."""
        readme = AGENT_DIR / "README.md"
        text = readme.read_text(encoding="utf-8")
        assert "NOT a Windows Service" in text or "Session 0" in text, (
            "README must explicitly state the agent is a user-session-level "
            "process, not a Windows Service"
        )

    def test_readme_loopback_only_stated(self) -> None:
        """README explicitly states agent binds 127.0.0.1 only."""
        readme = AGENT_DIR / "README.md"
        text = readme.read_text(encoding="utf-8")
        assert "127.0.0.1" in text, (
            "README must document that the agent binds 127.0.0.1 only"
        )

    def test_agent_import_no_win32_at_module_level(self) -> None:
        """Agent module does not import pywin32 at top level.

        All pywin32 imports are lazy (inside functions).  This allows
        the agent to start and serve /status even when pywin32 is absent.
        The local win32_windows module is fine — it does lazy imports.
        """
        import agent as agent_mod
        source = inspect.getsource(agent_mod)
        # Top-level imports should not include pywin32
        # (but fastapi, pydantic, subprocess, os, sys are fine)
        top_level = source.split("\n\n")[0] if "\n\n" in source else source
        assert "pywin32" not in top_level, (
            "pywin32 must not be imported at module level"
        )
        # Check for actual pywin32 modules (not the local win32_windows helper).
        # pywin32 exports win32gui, win32process, win32api, win32con, etc.
        pywin32_modules = [
            "win32gui", "win32process", "win32api", "win32con",
            "win32com", "pythoncom", "win32file", "win32pipe",
        ]
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                for mod in pywin32_modules:
                    if mod in stripped and "_windows" not in stripped:
                        pytest.fail(
                            f"Agent must not import pywin32 at module "
                            f"level: {stripped}"
                        )
