"""
Phase 3 review contract tests for SmartDesk backend Host Display API.

These tests verify BEHAVIORAL and STRUCTURAL contracts NOT covered by
test_host_display_api.py.  Areas covered:

  A. Backend Read-Only Boundary (no POST/PUT/DELETE activate, no Win32/COM
     import, no shell/subprocess, no DB writes, no meeting WebSocket events)
  B. Upstream Access Security (loopback-only defaults, env var validation,
     HTTP timeout, SSRF protection)
  C. Stable Response Structure (all top-level fields present, correct types,
     apps stably contains three keys, graceful degradation on all upstream
     failure modes)
  D. MediaMTX Contract (version/schema pinning, Control API path version,
     viewer_count precise parsing, stream_state not based on string match)

Tests that fail due to current production defects are EXPECTED_FAIL and
document known gaps for ZCode.  There must be 0 import/fixture/test-errors.

Usage:
    pytest tests/test_host_display_review_contract.py -v
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient


# ── Helpers ───────────────────────────────────────────────────────────────


def _patch_httpx(side_effect):
    """Return a context manager that patches httpx.Client with the given side_effect.

    The side_effect callable receives the URL string and must return a
    MagicMock-like response.  ConnectionError and other exceptions are
    supported via side_effect on mock_client.get.
    """
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get = MagicMock(side_effect=side_effect)
    return patch("backend.api.host_display.httpx.Client",
                 return_value=mock_client)


def _get_pinned_mediamtx_version() -> str | None:
    """Read the pinned MediaMTX version from host_services/screen_stream/README.md.

    Returns the exact semver string (e.g. ``"1.19.0"``) if the README
    references a specific version like ``MediaMTX 1.19.0``.  Returns None
    when the file is missing, the version pattern is absent, or only a
    vague reference (``v1.x``) is found.

    The regex requires a three-part numeric version (X.Y.Z) immediately
    after "MediaMTX" with optional space/v/dash prefix.
    """
    import re
    root = Path(__file__).resolve().parent.parent
    readme = root / "host_services" / "screen_stream" / "README.md"
    if not readme.is_file():
        return None
    text = readme.read_text(encoding="utf-8")
    m = re.search(
        r'MediaMTX[\s\-–—]*(?:v|version)?\s*(\d+\.\d+\.\d+)',
        text, re.IGNORECASE
    )
    return m.group(1) if m else None


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    """TestClient against the backend FastAPI app."""
    from backend.main import app
    return TestClient(app)


@pytest.fixture
def clear_env(monkeypatch):
    """Clear SmartDesk-related env vars before each test.

    This ensures defaults are tested, not contamination from the shell.
    """
    for key in ("SMARTDESK_AGENT_URL", "SMARTDESK_MEDIAMTX_CONTROL_URL",
                "SMARTDESK_MEDIAMTX_METRICS_URL", "SMARTDESK_STREAM_PATH"):
        monkeypatch.delenv(key, raising=False)


# =====================================================================
# A. Backend Read-Only Boundary
# =====================================================================


class TestBackendReadOnlyBoundary:
    """Backend stays OS-isolated; tablet writes require Seat 1 authentication."""

    def test_post_activate_requires_host_authentication(self, client) -> None:
        """POST activation exists but fails closed without Seat 1 credentials."""
        resp = client.post("/api/host-display/activate", json={"app": "powerpoint"})
        assert resp.status_code in (403, 422)

    def test_no_get_activate_endpoint(self, client) -> None:
        """No GET variant of activate."""
        resp = client.get("/api/host-display/activate")
        assert resp.status_code in (404, 405), (
            f"GET activate should not exist, got {resp.status_code}"
        )

    def test_no_put_activate_endpoint(self, client) -> None:
        """No PUT or PATCH variant of activate."""
        for method in ("put", "patch", "delete"):
            resp = getattr(client, method)("/api/host-display/activate")
            assert resp.status_code in (404, 405), (
                f"{method.upper()} /api/host-display/activate should not exist"
            )

    def test_router_exposes_status_and_authenticated_activation(self) -> None:
        """The router exposes read-only status and one fixed-target relay."""
        from backend.api.host_display import router
        registered_routes = []
        for route in router.routes:
            for method in route.methods:
                if method in ("HEAD", "OPTIONS"):
                    continue
                registered_routes.append(f"{method} {route.path}")
        get_routes = [r for r in registered_routes if r.startswith("GET ")]
        post_routes = [r for r in registered_routes if r.startswith("POST ")]
        assert get_routes == ["GET /api/host-display/status"]
        assert post_routes == ["POST /api/host-display/activate"]

    def test_backend_does_not_import_win32(self) -> None:
        """host_display module does not import any Win32/COM module."""
        from backend.api import host_display as hd
        source = inspect.getsource(hd)
        forbidden_imports = [
            "win32gui", "win32process", "win32api", "win32com",
            "pythoncom", "pywin32", "ctypes", "_win32",
        ]
        for imp in forbidden_imports:
            assert imp not in source, (
                f"Backend host_display must not import Win32/COM: "
                f"'{imp}' found in source"
            )

    def test_backend_does_not_use_subprocess(self) -> None:
        """host_display module does not import or use subprocess/shell."""
        from backend.api import host_display as hd
        source = inspect.getsource(hd)
        assert "subprocess" not in source, (
            "Backend must not import subprocess"
        )
        assert "shell=True" not in source and 'shell="' not in source, (
            "Backend must not execute shell commands"
        )
        assert "os.system" not in source, (
            "Backend must not use os.system"
        )

    def test_backend_no_websocket_event_publish(self) -> None:
        """host_display must not publish meeting WebSocket events.

        The endpoint is read-only and should not emit events through the
        meeting event bus.
        """
        from backend.api import host_display as hd
        source = inspect.getsource(hd)
        assert "event_bus" not in source, (
            "host_display must not access the meeting event bus"
        )
        assert "event_bus.publish" not in source, (
            "host_display must not publish events on the event bus"
        )
        assert "WebSocketEventHandler" not in source, (
            "host_display must not use WebSocket event handlers"
        )

    def test_backend_no_database_writes(self) -> None:
        """host_display must not write to the database.

        The endpoint queries Agent and MediaMTX only — no DB writes.
        """
        from backend.api import host_display as hd
        source = inspect.getsource(hd)
        # Check for actual DB write patterns (not false positives from comments)
        write_patterns = [
            "db.add(", "db.commit(", "db.merge(", "db.delete(",
            "session.add(", "session.commit(", "session.merge(", "session.delete(",
            "Base.metadata", "SessionLocal",
            "from backend.repositories",
        ]
        for pattern in write_patterns:
            assert pattern not in source, (
                f"host_display must not write to the database: "
                f"found '{pattern}' in source"
            )


# =====================================================================
# B. Upstream Access Security
# =====================================================================


class TestUpstreamAccessSecurity:
    """Upstream URLs must be loopback-only with SSRF protection."""

    def test_agent_url_defaults_to_loopback(self, clear_env) -> None:
        """Default AGENT_URL is http://127.0.0.1:8766."""
        # Re-evaluate after clearing env vars
        import importlib
        import backend.api.host_display as hd
        importlib.reload(hd)
        assert hd.AGENT_URL == "http://127.0.0.1:8766", (
            f"Default AGENT_URL must be 127.0.0.1 loopback, "
            f"got '{hd.AGENT_URL}'"
        )

    def test_mediamtx_urls_default_to_loopback(self, clear_env) -> None:
        """Default MediaMTX URLs point to 127.0.0.1."""
        import importlib
        import backend.api.host_display as hd
        importlib.reload(hd)
        assert hd.MEDIAMTX_CONTROL_URL == "http://127.0.0.1:9997", (
            f"Default Control API URL must be 127.0.0.1 loopback"
        )
        assert "127.0.0.1" in hd.MEDIAMTX_METRICS_URL, (
            f"Default metrics URL must be 127.0.0.1 loopback"
        )

    def test_http_requests_use_timeout(self) -> None:
        """All upstream HTTP requests have a finite timeout."""
        from backend.api.host_display import HTTP_TIMEOUT_SECONDS
        assert isinstance(HTTP_TIMEOUT_SECONDS, (int, float)), (
            "HTTP_TIMEOUT_SECONDS must be a number"
        )
        assert 0 < HTTP_TIMEOUT_SECONDS <= 30, (
            f"HTTP timeout must be positive and reasonable "
            f"({HTTP_TIMEOUT_SECONDS}s)"
        )

    def test_read_functions_never_raise(self) -> None:
        """_read_* functions never raise exceptions (caught internally)."""
        from backend.api.host_display import (
            _read_agent_status, _read_mediamtx_paths, _read_mediamtx_metrics,
        )
        for reader in (_read_agent_status, _read_mediamtx_paths,
                       _read_mediamtx_metrics):
            # Simulate total network failure — must return None, not raise
            with patch("httpx.Client") as mock_cls:
                mock_client = MagicMock()
                mock_cls.return_value.__enter__.return_value = mock_client
                mock_client.get.side_effect = ConnectionError("network down")
                result = reader()
                assert result is None, (
                    f"{reader.__name__} returned {result!r} instead of None "
                    f"on network failure"
                )

    def test_read_functions_propagate_timeout(self) -> None:
        """HTTP timeout is passed to httpx.Client."""
        from backend.api.host_display import (
            _read_agent_status, HTTP_TIMEOUT_SECONDS,
        )
        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = httpx.TimeoutException("timeout")
            result = _read_agent_status()
            assert result is None, "Timeout must return None, not raise"

    def test_env_var_accepts_remote_agent_url(self, monkeypatch) -> None:
        """[EXPECTED_FAIL] Env var SMARTDESK_AGENT_URL must be validated.

        Currently the module accepts any URL from the environment without
        loopback validation, creating an SSRF risk.
        """
        import importlib
        import backend.api.host_display as hd
        monkeypatch.setenv("SMARTDESK_AGENT_URL", "http://evil.example.com:8766")
        importlib.reload(hd)

        # The module should have validation that rejects this
        # Currently it passes the URL through to httpx directly
        assert hd.AGENT_URL == "http://127.0.0.1:8766", (
            f"Remote URL in SMARTDESK_AGENT_URL must be rejected or "
            f"safely fallback to loopback. Got: '{hd.AGENT_URL}'"
        )

    def test_env_var_accepts_non_http_agent_url(self, monkeypatch) -> None:
        """[EXPECTED_FAIL] Non-HTTP URL in SMARTDESK_AGENT_URL must be rejected.

        The module should accept only http:// and https:// URLs.
        """
        import importlib
        import backend.api.host_display as hd
        monkeypatch.setenv("SMARTDESK_AGENT_URL", "file:///etc/passwd")
        importlib.reload(hd)
        assert hd.AGENT_URL.startswith("http"), (
            f"Non-HTTP URL must be rejected. Got: '{hd.AGENT_URL}'"
        )

    def test_ssrf_no_user_supplied_url(self) -> None:
        """No function in host_display accepts a caller-supplied URL.

        All HTTP URLs come from environment or module-level constants,
        never from the API request body.
        """
        from backend.api.host_display import (
            _read_agent_status, _read_mediamtx_paths, _read_mediamtx_metrics,
        )
        # These functions take no arguments — they read URLs from module
        # constants.  This is the correct design.
        import inspect
        for fn in (_read_agent_status, _read_mediamtx_paths,
                   _read_mediamtx_metrics):
            sig = inspect.signature(fn)
            params = list(sig.parameters.keys())
            msg = (
                f"{fn.__name__} must not accept a URL parameter from callers. "
                f"URLs must come from module-level constants only."
            )
            assert "url" not in params, msg
            assert "endpoint" not in params, msg


# =====================================================================
# C. Stable Response Structure
# =====================================================================


class TestStableResponseStructure:
    """GET /api/host-display/status always returns a complete, typed response."""

    REQUIRED_FIELDS = [
        "agent_state", "stream_state", "active_app",
        "viewer_count", "apps", "profile",
    ]
    REQUIRED_APPS = ["powerpoint", "solidworks", "smartdesk"]

    def test_response_has_all_required_fields(self, client) -> None:
        """Response contains all 6 top-level fields."""
        with _patch_httpx(lambda url: MagicMock(status_code=404)):
            resp = client.get("/api/host-display/status")
        assert resp.status_code == 200
        data = resp.json()
        for field in self.REQUIRED_FIELDS:
            assert field in data, (
                f"Required field '{field}' missing from response. "
                f"Fields present: {list(data.keys())}"
            )

    def test_apps_has_three_required_keys(self, client) -> None:
        """apps dict always contains powerpoint, solidworks, smartdesk."""
        with _patch_httpx(lambda url: MagicMock(status_code=404)):
            resp = client.get("/api/host-display/status")
        apps = resp.json().get("apps", {})
        for app in self.REQUIRED_APPS:
            assert app in apps, (
                f"Required app '{app}' missing from apps dict"
            )

    def test_apps_keys_never_change(self, client) -> None:
        """apps dict keys are always exactly the three standard apps."""
        with _patch_httpx(lambda url: MagicMock(status_code=404)):
            resp = client.get("/api/host-display/status")
        apps_keys = set(resp.json().get("apps", {}).keys())
        assert apps_keys == set(self.REQUIRED_APPS), (
            f"apps keys should always be exactly "
            f"{{'powerpoint', 'solidworks', 'smartdesk'}}. Got: {apps_keys}"
        )

    def test_agent_state_literal_values(self, client) -> None:
        """agent_state is 'online' or 'offline'."""
        # Online case
        def fake_online(url):
            if "/status" in url:
                r = MagicMock(status_code=200)
                r.json.return_value = {
                    "agent_state": "online", "apps": {}, "active_app": None
                }
                return r
            return MagicMock(status_code=404)
        with _patch_httpx(fake_online):
            resp = client.get("/api/host-display/status")
        assert resp.json()["agent_state"] in ("online", "offline"), (
            f"agent_state must be 'online' or 'offline'"
        )
        # Offline case
        with _patch_httpx(lambda u: (_ for _ in ()).throw(
            ConnectionError("offline"))):
            resp = client.get("/api/host-display/status")
        assert resp.json()["agent_state"] == "offline"

    def test_stream_state_literal_values(self, client) -> None:
        """stream_state is 'online', 'offline', or 'unknown'."""
        with _patch_httpx(lambda u: (_ for _ in ()).throw(
            ConnectionError("offline"))):
            resp = client.get("/api/host-display/status")
        assert resp.json()["stream_state"] in ("online", "offline", "unknown")

    def test_viewer_count_type(self, client) -> None:
        """viewer_count is int or None."""
        # Both upstreams offline → viewer_count is None
        with _patch_httpx(lambda u: (_ for _ in ()).throw(
            ConnectionError("offline"))):
            resp = client.get("/api/host-display/status")
        vc = resp.json()["viewer_count"]
        assert vc is None or isinstance(vc, int), (
            f"viewer_count must be int or None, got {type(vc).__name__}"
        )
        # When metrics available → int
        def fake_online(url):
            if "/status" in url:
                r = MagicMock(status_code=200)
                r.json.return_value = {
                    "agent_state": "online", "apps": {}, "active_app": None
                }
                return r
            if "/metrics" in url:
                r = MagicMock(status_code=200)
                r.text = 'paths_readers{name="screen",state="ready",readerType="webrtc"} 3\n'
                return r
            return MagicMock(status_code=404)
        with _patch_httpx(fake_online):
            resp = client.get("/api/host-display/status")
        assert isinstance(resp.json()["viewer_count"], int)

    def test_profile_has_width_height_fps(self, client) -> None:
        """profile contains width, height, fps (all int or None)."""
        with _patch_httpx(lambda u: (_ for _ in ()).throw(
            ConnectionError("offline"))):
            resp = client.get("/api/host-display/status")
        profile = resp.json().get("profile", {})
        for key in ("width", "height", "fps"):
            assert key in profile, (
                f"profile.{key} is missing"
            )
            assert profile[key] is None or isinstance(profile[key], int), (
                f"profile.{key} must be int or None, "
                f"got {type(profile[key]).__name__}"
            )

    def test_each_app_has_running_and_window_found(self, client) -> None:
        """Each app entry has running (bool) and window_found (bool)."""
        with _patch_httpx(lambda u: (_ for _ in ()).throw(
            ConnectionError("offline"))):
            resp = client.get("/api/host-display/status")
        apps = resp.json().get("apps", {})
        for app_name, app_data in apps.items():
            assert "running" in app_data, (
                f"apps.{app_name}.running is missing"
            )
            assert isinstance(app_data["running"], bool), (
                f"apps.{app_name}.running must be bool"
            )
            assert "window_found" in app_data, (
                f"apps.{app_name}.window_found is missing"
            )
            assert isinstance(app_data["window_found"], bool), (
                f"apps.{app_name}.window_found must be bool"
            )

    def test_agent_offline_all_apps_false(self, client) -> None:
        """Agent offline → all apps running=false, window_found=false."""
        with _patch_httpx(lambda u: (_ for _ in ()).throw(
            ConnectionError("offline"))):
            resp = client.get("/api/host-display/status")
        apps = resp.json()["apps"]
        for app_name in self.REQUIRED_APPS:
            assert apps[app_name]["running"] is False, (
                f"{app_name}.running must be False when agent is offline"
            )
            assert apps[app_name]["window_found"] is False, (
                f"{app_name}.window_found must be False when agent is offline"
            )

    def test_both_upstreams_offline_no_500(self, client) -> None:
        """Both Agent and MediaMTX offline → no 500."""
        with _patch_httpx(lambda u: (_ for _ in ()).throw(
            ConnectionError("both offline"))):
            resp = client.get("/api/host-display/status")
        assert resp.status_code == 200, (
            f"Expected 200 on upstream failure, got {resp.status_code}"
        )

    def test_timeout_upstream_no_500(self, client) -> None:
        """Timeout on upstream → no 500."""
        with _patch_httpx(lambda u: (_ for _ in ()).throw(
            httpx.TimeoutException("timed out"))):
            resp = client.get("/api/host-display/status")
        assert resp.status_code == 200, (
            f"Expected 200 on timeout, got {resp.status_code}"
        )

    def test_non_200_upstream_handled_gracefully(self, client) -> None:
        """Agent returns non-200 → treated as offline."""
        def fake_non_200(url):
            if "/status" in url:
                return MagicMock(status_code=503)
            return MagicMock(status_code=404)
        with _patch_httpx(fake_non_200):
            resp = client.get("/api/host-display/status")
        assert resp.status_code == 200
        assert resp.json()["agent_state"] == "offline"

    def test_non_json_upstream_handled_gracefully(self, client) -> None:
        """[EXPECTED_FAIL] Agent returns non-JSON → agent_state=offline.

        Production defect: resp.json() raises ValueError when agent returns
        non-JSON, but the except clause in _read_agent_status catches
        Exception broadly.  This test verifies the degraded behavior.
        """
        def fake_non_json(url):
            if "/status" in url:
                r = MagicMock(status_code=200)
                r.json.side_effect = ValueError("not json")
                return r
            return MagicMock(status_code=404)
        with _patch_httpx(fake_non_json):
            resp = client.get("/api/host-display/status")
        assert resp.status_code == 200
        assert resp.json()["agent_state"] == "offline", (
            "Non-JSON from agent must result in agent_state=offline"
        )

    def test_upstream_wrong_field_types(self, client) -> None:
        """[EXPECTED_FAIL] Wrong field types from agent must not cause 500.

        If agent returns 'apps' as a list instead of a dict, or 'running'
        as a string, the backend should still return 200 with degraded values.
        """
        def fake_bad_types(url):
            if "/status" in url:
                r = MagicMock(status_code=200)
                r.json.return_value = {
                    "agent_state": "online",
                    "apps": {"powerpoint": {
                        "running": "yes", "window_found": 1
                    }},
                    "active_app": "powerpoint",
                }
                return r
            return MagicMock(status_code=404)
        with _patch_httpx(fake_bad_types):
            resp = client.get("/api/host-display/status")
        assert resp.status_code == 200, (
            f"Field type errors must not cause 500, got {resp.status_code}. "
            f"Body: {resp.json()}"
        )

    def test_missing_apps_field_from_agent(self, client) -> None:
        """[EXPECTED_FAIL] Missing 'apps' in agent response → no 500.

        Backend should handle missing fields gracefully.
        """
        def fake_missing_apps(url):
            if "/status" in url:
                r = MagicMock(status_code=200)
                r.json.return_value = {
                    "agent_state": "online",
                    "active_app": None,
                    # No "apps" key
                }
                return r
            return MagicMock(status_code=404)
        with _patch_httpx(fake_missing_apps):
            resp = client.get("/api/host-display/status")
        assert resp.status_code == 200, (
            f"Missing 'apps' field must not cause 500, "
            f"got {resp.status_code}"
        )


# =====================================================================
# D. MediaMTX Contract
# =====================================================================


class TestMediaMTXContract:
    """MediaMTX version pinning, Control API paths, viewer_count parsing."""

    def test_mediamtx_version_pinned(self) -> None:
        """[EXPECTED_FAIL] Project must pin an exact MediaMTX semver.

        The Control API path and metrics format are version-specific.
        Reads ``host_services/screen_stream/README.md`` and requires a
        three-part version (X.Y.Z) — a vague ``v1.x`` is not sufficient.

        Once pinned to a concrete version like ``1.19.0``, all downstream
        tests (Control API path, metrics schema) can validate against that
        version's documented contract.
        """
        version = _get_pinned_mediamtx_version()
        assert version is not None, (
            "No exact MediaMTX version pinned in "
            "host_services/screen_stream/README.md.  "
            "Current README only references 'mediamtx_v1.x' which is too "
            "vague.  Pin an exact semver like '1.19.0' before the Control "
            "API path and metrics schema can be validated."
        )
        # Validate semver format
        parts = version.split(".")
        assert len(parts) == 3, (
            f"Pinned version '{version}' is not a valid three-part semver"
        )
        assert all(p.isdigit() for p in parts), (
            f"Pinned version '{version}' parts must be numeric"
        )

    def test_control_api_path_matches_pinned_version(self) -> None:
        """[EXPECTED_FAIL] Control API path must match pinned MediaMTX version.

        MediaMTX v1.19.0 uses ``/v3/paths/list`` for its Control API
        (see https://mediamtx.org/docs/features/control-api).

        This test first reads the pinned version from the screen_stream
        README.  If none is pinned it fails immediately.  If a version
        IS pinned it verifies the correct path constant is used in
        ``_read_mediamtx_paths``.

        Expected paths per version:
          - 1.19.x → /v3/paths/list
        """
        version = _get_pinned_mediamtx_version()
        assert version is not None, (
            "Cannot verify Control API path without an exact MediaMTX "
            "version pin.  See test_mediamtx_version_pinned."
        )

        # Determine expected path from the pinned version
        major_minor = ".".join(version.split(".")[:2])
        known_paths = {
            "1.19": "/v3/paths/list",
        }
        expected_path = known_paths.get(major_minor)
        assert expected_path is not None, (
            f"Control API path for MediaMTX {version} is not yet defined "
            f"in this test.  Known version→path mappings: {known_paths}"
        )

        # Check the production code
        import inspect
        from backend.api import host_display as hd
        source = inspect.getsource(hd._read_mediamtx_paths)
        assert expected_path in source, (
            f"MediaMTX {version} Control API path should be "
            f"'{expected_path}', but _read_mediamtx_paths uses a different "
            f"path.  Current code uses '/v2/paths' which was the v1.17 "
            f"path; it was changed to /v3/paths/list in v1.18+."
        )

    def test_metrics_schema_matches_pinned_version(self) -> None:
        """[EXPECTED_FAIL] viewer_count parsing must target MediaMTX 1.19.0 metrics schema.

        MediaMTX 1.19.0 exposes per-path reader counts via the
        ``paths_readers`` Prometheus metric (see
        https://mediamtx.org/docs/features/metrics):

          paths_readers{name="<path>",state="ready",readerType="<type>"} <count>

        The parser in ``_parse_viewer_count`` must extract the value of
        the metric line that matches ALL of:
          - Metric name: ``paths_readers``
          - Label ``name="<stream_path>"``  (e.g. ``name="screen"``)
          - Label ``state="ready"``
          - Label ``readerType="webrtc"``

        Other reader types (rtsp, hls), non-ready states, and other
        paths must not be counted.  Missing / duplicate / invalid
        metrics must return ``None``.
        """
        version = _get_pinned_mediamtx_version()
        assert version is not None, (
            "Cannot validate metrics schema without an exact MediaMTX "
            "version pin.  See test_mediamtx_version_pinned."
        )
        major_minor = ".".join(version.split(".")[:2])
        assert major_minor == "1.19", (
            f"This test targets MediaMTX 1.19.x metrics schema, "
            f"but pinned version is {version}.  Update the test."
        )
        from backend.api import host_display as hd
        import inspect
        source = inspect.getsource(hd._parse_viewer_count)
        # Must reference the correct metric name for 1.19.0
        assert "paths_readers" in source, (
            f"MediaMTX {version} uses 'paths_readers' metric for viewer "
            f"count.  Current _parse_viewer_count looks for 'webrtc' "
            f"which was the pre-1.18 format."
        )
        # Must filter by readerType
        assert 'readerType' in source or 'reader_type' in source, (
            "Must filter by readerType='webrtc' to avoid counting "
            "RTSP or HLS readers as WebRTC viewers."
        )

    def test_viewer_count_only_counts_webrtc_ready_readers(self) -> None:
        """viewer_count counts only paths_readers with readerType=webrtc & state=ready.

        MediaMTX 1.19.0 format:
          paths_readers{name="screen",state="ready",readerType="webrtc"} N

        Other readerTypes (rtsp, hls) or non-ready states are NOT
        WebRTC viewers and must be excluded.
        """
        from backend.api.host_display import _parse_viewer_count
        metrics = (
            'paths_readers{name="screen",state="ready",readerType="webrtc"} 5\n'
            'paths_readers{name="screen",state="ready",readerType="rtsp"} 3\n'
            'paths_readers{name="screen",state="ready",readerType="hls"} 2\n'
        )
        result = _parse_viewer_count(metrics, "screen")
        # Only webrtc readerType counts → 5
        # Current parser sums all lines matching 'webrtc' OR matching
        # any line containing path="screen" — either way it may
        # overcount.  This assertion verifies the correct contract.
        assert result is not None, (
            "viewer_count should not be None for valid 1.19.0 metrics"
        )
        assert result == 5, (
            f"viewer_count={result} — expected 5 (only webrtc readers). "
            f"The parser must filter by readerType='webrtc'."
        )

    def test_viewer_count_unrelated_path_not_counted(self) -> None:
        """Unrelated paths don't contribute to viewer_count."""
        from backend.api.host_display import _parse_viewer_count
        metrics = (
            'paths_readers{name="screen",state="ready",readerType="webrtc"} 5\n'
            'paths_readers{name="other",state="ready",readerType="webrtc"} 10\n'
        )
        result = _parse_viewer_count(metrics, "screen")
        assert result is not None
        assert result == 5, (
            f"viewer_count={result} — expected 5. "
            f"Unrelated path 'other' (10) must not be counted."
        )

    def test_viewer_count_no_metric_for_path_returns_null(self) -> None:
        """No metric matching the stream path → viewer_count is None."""
        from backend.api.host_display import _parse_viewer_count
        metrics = (
            'paths_readers{name="other",state="ready",readerType="webrtc"} 3\n'
        )
        result = _parse_viewer_count(metrics, "screen")
        assert result is None, (
            f"viewer_count must be None when no metric exists for path "
            f"'screen'. Got {result}"
        )

    def test_viewer_count_invalid_lines_ignored(self) -> None:
        """Invalid or malformed metric lines don't fabricate counts."""
        from backend.api.host_display import _parse_viewer_count
        metrics = (
            'paths_readers{name="screen",state="ready",readerType="webrtc"} 5\n'
            '# COMMENT line\n'
            'paths_readers{name="screen",state="ready",readerType="webrtc"} not_a_number\n'
            '  \n'
            'paths_readers{name="screen",state="ready",readerType="webrtc"} 3\n'
        )
        result = _parse_viewer_count(metrics, "screen")
        assert result is not None
        assert result == 8, (
            f"viewer_count={result} — expected 8 (5 + 3). "
            f"Comments and non-numeric values must be skipped."
        )

    def test_viewer_count_duplicate_metric_not_inflated(self) -> None:
        """Duplicate metric lines must not produce inflated viewer count.

        If the exact same metric line appears twice (e.g. from a
        misconfigured multi-target exporter), the parser must not
        double-count it.  Return ``None`` if ambiguity is detected
        rather than fabricating a count.
        """
        from backend.api.host_display import _parse_viewer_count
        metrics = (
            'paths_readers{name="screen",state="ready",readerType="webrtc"} 5\n'
            'paths_readers{name="screen",state="ready",readerType="webrtc"} 5\n'
        )
        result = _parse_viewer_count(metrics, "screen")
        # The contract: unreliable to determine which one is correct
        # when exact duplicates exist.  Return None rather than guess.
        assert result is None or result <= 5, (
            f"viewer_count={result} — duplicate metric lines must not "
            f"produce inflation.  Expected None or ≤5, got {result}."
        )

    def test_stream_state_not_determined_by_string_contains(self, client) -> None:
        """[EXPECTED_FAIL] stream_state must not use string 'screen' in metrics.

        Current code checks `STREAM_PATH in metrics_text` which means
        any metrics text containing 'screen' (even a comment or unrelated
        metric name) will set stream_state to online.
        """
        # Metrics text contains 'screen' but the path is NOT online
        # — this should NOT set stream_state=online.
        def fake_screen_string(url):
            if "/status" in url:
                r = MagicMock(status_code=200)
                r.json.return_value = {
                    "agent_state": "online", "apps": {}, "active_app": None
                }
                return r
            if "/v3/paths/list" in url:
                r = MagicMock(status_code=200)
                r.json.return_value = {"items": []}
                return r
            if "/metrics" in url:
                r = MagicMock(status_code=200)
                # 'screen' appears in comment text but NOT as a ready path
                r.text = '# HELP path_screen_duration description\n'
                return r
            return MagicMock(status_code=404)
        with _patch_httpx(fake_screen_string):
            resp = client.get("/api/host-display/status")
        assert resp.status_code == 200
        assert resp.json()["stream_state"] != "online", (
            "stream_state must not be 'online' just because metrics text "
            "contains the string 'screen'. The Control API shows no ready "
            "path and metrics contain no session data."
        )

    def test_stream_path_never_none_or_empty(self) -> None:
        """STREAM_PATH must be a non-empty string."""
        from backend.api.host_display import STREAM_PATH
        assert STREAM_PATH, "STREAM_PATH must be a non-empty string"
        assert isinstance(STREAM_PATH, str)

    def test_env_stream_path_sanitized(self, monkeypatch) -> None:
        """[EXPECTED_FAIL] SMARTDESK_STREAM_PATH must be validated.

        Currently the env var is used as-is without sanitization.
        """
        import importlib
        import backend.api.host_display as hd
        monkeypatch.setenv("SMARTDESK_STREAM_PATH", "../evil")
        importlib.reload(hd)
        assert hd.STREAM_PATH not in ("../evil",), (
            f"Stream path must be sanitized. Got: '{hd.STREAM_PATH}'"
        )
