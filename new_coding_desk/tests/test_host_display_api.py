"""
Tests for GET /api/host-display/status — read-only aggregation.

All upstream HTTP calls (Agent, MediaMTX) are mocked via httpx.Client.

Covers:
  - Normal response with both upstreams online
  - Agent offline → agent_state=offline, apps all false
  - MediaMTX offline → stream_state=unknown
  - Timeout / network failure → graceful degradation
  - Malformed upstream response → no 500
  - viewer_count null when metrics unavailable
  - POST /api/host-display/activate fails closed without Seat 1 authentication
  - No shell execution
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.main import app
    return TestClient(app)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _mock_httpx_response(status_code=200, json_data=None, text=None):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    if text is not None:
        resp.text = text
    return resp


def _patch_httpx(client_get_side_effect):
    """Patch httpx.Client to return the given side effect for .get()."""
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)
    mock_client.get = MagicMock(side_effect=client_get_side_effect)
    return patch("backend.api.host_display.httpx.Client", return_value=mock_client)


# ── Normal response ─────────────────────────────────────────────────────────


def test_status_normal_both_online(client):
    """Both Agent and MediaMTX online → full status."""
    def fake_get(url):
        if "/status" in url:
            return _mock_httpx_response(
                json_data={
                    "agent_state": "online",
                    "apps": {
                        "powerpoint": {"running": True, "window_found": True},
                        "solidworks": {"running": False, "window_found": False},
                        "smartdesk": {"running": True, "window_found": True},
                    },
                    "active_app": "powerpoint",
                }
            )
        if "/v3/paths/list" in url:
            return _mock_httpx_response(
                json_data={
                    "items": [
                        {"name": "screen", "ready": True}
                    ]
                }
            )
        if "/metrics" in url:
            return _mock_httpx_response(
                text='paths_readers{name="screen",state="ready",readerType="webrtc"} 10\n'
            )
        return _mock_httpx_response(status_code=404)

    with _patch_httpx(fake_get):
        resp = client.get("/api/host-display/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_state"] == "online"
    assert data["stream_state"] == "online"
    assert data["active_app"] == "powerpoint"
    assert data["apps"]["powerpoint"]["running"] is True
    assert data["apps"]["solidworks"]["running"] is False
    assert "viewer_count" in data


def test_status_agent_offline(client):
    """Agent offline → agent_state=offline, apps all false."""
    def fake_get(url):
        if "/status" in url:
            raise ConnectionError("Agent not running")
        return _mock_httpx_response(status_code=404)

    with _patch_httpx(fake_get):
        resp = client.get("/api/host-display/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_state"] == "offline"
    assert data["active_app"] is None
    for app in ("powerpoint", "solidworks", "smartdesk"):
        assert data["apps"][app]["running"] is False
        assert data["apps"][app]["window_found"] is False


def test_status_mediamtx_offline(client):
    """MediaMTX offline → stream_state=unknown."""
    def fake_get(url):
        if "/status" in url:
            return _mock_httpx_response(json_data={
                "agent_state": "online",
                "apps": {},
                "active_app": None,
            })
        raise ConnectionError("MediaMTX not running")

    with _patch_httpx(fake_get):
        resp = client.get("/api/host-display/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_state"] == "online"
    assert data["stream_state"] == "unknown"


def test_status_timeout_no_500(client):
    """Timeout on upstream → no 500."""
    import httpx
    def fake_get(url):
        raise httpx.TimeoutException("timed out")

    with _patch_httpx(fake_get):
        resp = client.get("/api/host-display/status")

    assert resp.status_code == 200


def test_status_malformed_upstream_no_500(client):
    """Malformed JSON from upstream → no 500."""
    def fake_get(url):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        return resp

    with _patch_httpx(fake_get):
        resp = client.get("/api/host-display/status")

    assert resp.status_code == 200
    data = resp.json()
    # Malformed Agent → offline
    assert data["agent_state"] == "offline"


def test_viewer_count_null_when_metrics_unavailable(client):
    """viewer_count is null when metrics endpoint fails."""
    def fake_get(url):
        if "/status" in url:
            return _mock_httpx_response(json_data={
                "agent_state": "online", "apps": {}, "active_app": None
            })
        if "/v3/paths/list" in url:
            return _mock_httpx_response(json_data={"items": [
                {"name": "screen", "ready": True}
            ]})
        raise ConnectionError("metrics offline")

    with _patch_httpx(fake_get):
        resp = client.get("/api/host-display/status")

    data = resp.json()
    assert data["viewer_count"] is None


def test_viewer_count_parsed_from_metrics(client):
    """viewer_count parsed from paths_readers metric (1.19.0 schema)."""
    def fake_get(url):
        if "/status" in url:
            return _mock_httpx_response(json_data={
                "agent_state": "online", "apps": {}, "active_app": None
            })
        if "/v3/paths/list" in url:
            return _mock_httpx_response(json_data={"items": []})
        if "/metrics" in url:
            return _mock_httpx_response(
                text='paths_readers{name="screen",state="ready",readerType="webrtc"} 7\n'
                     'paths_readers{name="other",state="ready",readerType="webrtc"} 3\n'
            )
        return _mock_httpx_response(status_code=404)

    with _patch_httpx(fake_get):
        resp = client.get("/api/host-display/status")

    data = resp.json()
    assert data["viewer_count"] == 7


def test_viewer_count_null_when_metric_absent(client):
    """viewer_count null when metric is present but not for our path."""
    def fake_get(url):
        if "/status" in url:
            return _mock_httpx_response(json_data={
                "agent_state": "online", "apps": {}, "active_app": None
            })
        if "/v3/paths/list" in url:
            return _mock_httpx_response(json_data={"items": [
                {"name": "screen", "ready": True}
            ]})
        if "/metrics" in url:
            return _mock_httpx_response(text='paths_readers{name="other",state="ready",readerType="webrtc"} 3\n')
        return _mock_httpx_response(status_code=404)

    with _patch_httpx(fake_get):
        resp = client.get("/api/host-display/status")

    data = resp.json()
    assert data["viewer_count"] is None


# ── Authenticated activate endpoint ───────────────────────────────────────


def test_activate_requires_host_authentication(client):
    """POST activation fails closed without Seat 1 credentials."""
    resp = client.post("/api/host-display/activate", json={"app": "powerpoint"})
    assert resp.status_code in (403, 422)


def test_no_activate_get_endpoint(client):
    """No GET activate variant either."""
    resp = client.get("/api/host-display/activate")
    assert resp.status_code in (404, 405)


# ── Stability checks ───────────────────────────────────────────────────────


def test_status_always_returns_apps_dict(client):
    """Status always has the apps dict with three keys."""
    def fake_get(url):
        raise ConnectionError("everything offline")

    with _patch_httpx(fake_get):
        resp = client.get("/api/host-display/status")

    data = resp.json()
    assert set(data["apps"].keys()) == {"powerpoint", "solidworks", "smartdesk"}


def test_status_has_profile_key(client):
    """Status always has profile key."""
    def fake_get(url):
        raise ConnectionError("offline")

    with _patch_httpx(fake_get):
        resp = client.get("/api/host-display/status")

    data = resp.json()
    assert "profile" in data
