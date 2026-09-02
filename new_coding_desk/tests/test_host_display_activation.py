from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from backend.api import host_display
from backend.main import app
from backend.services.tablet_device_service import TabletDeviceService
from tests.conftest import TestSessionLocal


DEVICE_ID = "host-tablet-01"
DEVICE_TOKEN = "host-tablet-device-token-000001"
client = TestClient(app)


def _provision(seat_id: int = 1) -> None:
    db = TestSessionLocal()
    try:
        TabletDeviceService(db).provision(
            device_id=DEVICE_ID,
            seat_id=seat_id,
            token=DEVICE_TOKEN,
        )
    finally:
        db.close()


def _agent(status_code: int = 200, body: dict | None = None):
    response = MagicMock(status_code=status_code)
    response.json.return_value = body if body is not None else {"ok": True}
    http = MagicMock()
    http.__enter__.return_value = http
    http.__exit__.return_value = None
    http.post.return_value = response
    return patch("backend.api.host_display.httpx.Client", return_value=http), http


def _request(app_name: str = "powerpoint"):
    return client.post(
        "/api/host-display/activate",
        headers={"X-SmartDesk-Device-Token": DEVICE_TOKEN},
        json={"deviceId": DEVICE_ID, "deviceSeatId": 1, "app": app_name},
    )


def test_host_tablet_activation_forwards_only_app_to_fixed_agent():
    _provision()
    context, http = _agent()
    with context:
        response = _request("solidworks")

    assert response.status_code == 200
    assert response.json()["data"] == {"app": "solidworks", "activated": True}
    http.post.assert_called_once_with(
        "http://127.0.0.1:8766/activate",
        json={"app": "solidworks"},
    )


def test_non_host_device_is_rejected_before_forwarding():
    _provision(seat_id=2)
    context, http = _agent()
    with context:
        response = _request()
    assert response.status_code == 403
    assert response.json()["error_code"] == "HOST_DEVICE_AUTH_FAILED"
    http.post.assert_not_called()


def test_wrong_device_token_is_rejected_before_forwarding():
    _provision()
    context, http = _agent()
    with context:
        response = client.post(
            "/api/host-display/activate",
            headers={"X-SmartDesk-Device-Token": "wrong-device-token-000001"},
            json={"deviceId": DEVICE_ID, "deviceSeatId": 1, "app": "powerpoint"},
        )
    assert response.status_code == 403
    assert response.json()["error_code"] == "HOST_DEVICE_AUTH_FAILED"
    http.post.assert_not_called()


def test_activation_application_whitelist_is_enforced():
    _provision()
    context, http = _agent()
    with context:
        response = _request("calculator")
    assert response.status_code == 422
    assert response.json()["error_code"] == "DISPLAY_APP_INVALID"
    http.post.assert_not_called()


def test_agent_conflict_maps_to_stable_already_active_error():
    _provision()
    context, _ = _agent(status_code=409)
    with context:
        response = _request()
    assert response.status_code == 409
    assert response.json()["error_code"] == "DISPLAY_APP_ALREADY_ACTIVE"


def test_agent_timeout_maps_to_stable_offline_error():
    _provision()
    context, http = _agent()
    http.post.side_effect = httpx.ConnectTimeout("offline")
    with context:
        response = _request()
    assert response.status_code == 503
    assert response.json()["error_code"] == "DISPLAY_AGENT_OFFLINE"


def test_loopback_agent_status_ignores_system_proxy_environment():
    response = MagicMock(status_code=200)
    response.json.return_value = {"agent_state": "online", "apps": {}}
    http = MagicMock()
    http.__enter__.return_value = http
    http.__exit__.return_value = None
    http.get.return_value = response

    with patch("backend.api.host_display.httpx.Client", return_value=http) as factory:
        result = host_display._read_agent_status()

    factory.assert_called_once_with(
        timeout=host_display.HTTP_TIMEOUT_SECONDS,
        trust_env=False,
    )
    assert result == {"agent_state": "online", "apps": {}}
