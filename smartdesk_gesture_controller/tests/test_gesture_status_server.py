"""Tests for hands.gesture_status_server.

Covers the WebSocket broadcast state, the new status-card fields, and the
shared-port HTTP handler that serves ``hands/frontend/index.html`` plus its
static assets.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

from hands.gesture_status_server import GestureStatusServer


# Ports intentionally offset from the production default to avoid collisions.
_HTTP_PORT = 8767
_HTTP_PORT_2 = 8768


async def _http_get(host: str, port: int, path: str = "/") -> bytes:
    reader, writer = await asyncio.open_connection(host, port)
    try:
        request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
        writer.write(request.encode("ascii"))
        await writer.drain()
        return await reader.read()
    finally:
        writer.close()


@pytest.fixture
def status_server(tmp_path):
    # Build a tiny mock frontend directory so static-asset tests are isolated
    # from the production files while still exercising the same code paths.
    html_path = tmp_path / "index.html"
    html_path.write_text("<html><body>Gesture Controller Status Card</body></html>", encoding="utf-8")
    (tmp_path / "styles.css").write_text(".gesture-status-card { opacity: 1; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('status card');", encoding="utf-8")
    (tmp_path / "radar.svg").write_text("<svg></svg>", encoding="utf-8")

    server = GestureStatusServer(
        host="127.0.0.1",
        port=_HTTP_PORT,
        broadcast_interval=0.05,
        html_path=str(html_path),
    )
    assert server.start()
    try:
        yield server
    finally:
        server.stop()


def test_default_snapshot_contains_new_fields(status_server):
    snap = status_server.snapshot()
    assert snap["mode"] == "standby"
    assert snap["camera_ok"] is False
    assert "hand_present" in snap
    assert snap["hand_present"] is False
    assert "hand_lost_duration" in snap
    assert snap["hand_lost_duration"] == 0.0
    assert "cooldown_until" in snap
    assert snap["cooldown_until"] == 0.0
    assert "intent_phase" in snap
    assert snap["intent_phase"] == "idle"
    assert snap["display_agent_online"] is False
    assert snap["display_target_app"] == "smartdesk"
    assert snap["display_switch_state"] == "unknown"


def test_update_merges_fields(status_server):
    status_server.update(
        hand_present=True,
        hand_lost_duration=0.45,
        cooldown_until=1234567890.0,
        intent_phase="attempt:page_swipe:tracking",
    )
    snap = status_server.snapshot()
    assert snap["hand_present"] is True
    assert snap["hand_lost_duration"] == 0.45
    assert snap["cooldown_until"] == 1234567890.0
    assert snap["intent_phase"] == "attempt:page_swipe:tracking"
    # Timestamp is refreshed on every update.
    assert snap["timestamp"] > 0


def test_http_get_root_returns_html(status_server):
    response = asyncio.run(_http_get("127.0.0.1", _HTTP_PORT, "/"))
    assert b"200 OK" in response
    assert b"Gesture Controller Status Card" in response
    assert b"text/html" in response


def test_http_get_static_assets(status_server):
    css = asyncio.run(_http_get("127.0.0.1", _HTTP_PORT, "/styles.css"))
    assert b"200 OK" in css
    assert b"text/css" in css
    assert b".gesture-status-card" in css

    js = asyncio.run(_http_get("127.0.0.1", _HTTP_PORT, "/app.js"))
    assert b"200 OK" in js
    assert b"application/javascript" in js
    assert b"status card" in js

    svg = asyncio.run(_http_get("127.0.0.1", _HTTP_PORT, "/radar.svg"))
    assert b"200 OK" in svg
    assert b"image/svg+xml" in svg


def test_websocket_receives_snapshot_on_same_port(status_server):
    import websockets

    async def _read():
        async with websockets.connect(f"ws://127.0.0.1:{_HTTP_PORT}") as ws:
            msg = await ws.recv()
            data = json.loads(msg)
            assert data["mode"] == "standby"
            assert "hand_present" in data
            assert data["intent_phase"] == "idle"

    asyncio.run(_read())


def test_missing_index_html_returns_503():
    server = GestureStatusServer(
        host="127.0.0.1",
        port=_HTTP_PORT_2,
        html_path=os.path.join(tempfile.gettempdir(), "definitely_missing.html"),
    )
    assert server.start()
    try:
        response = asyncio.run(_http_get("127.0.0.1", _HTTP_PORT_2, "/"))
        assert b"503" in response
        assert b"Status card HTML not found" in response
    finally:
        server.stop()


def test_missing_static_asset_returns_404(status_server):
    response = asyncio.run(_http_get("127.0.0.1", _HTTP_PORT, "/missing.css"))
    assert b"404" in response
