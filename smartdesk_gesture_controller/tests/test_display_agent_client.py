from __future__ import annotations

import io
from urllib import error

import pytest

from hands.display_agent_client import DisplayAgentClient


class _Response:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body


def test_status_reads_active_app(monkeypatch):
    monkeypatch.setattr(
        "hands.display_agent_client.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            b'{"agent_state":"online","active_app":"smartdesk"}'
        ),
    )
    result = DisplayAgentClient("http://127.0.0.1:8766").status()
    assert result.ok is True
    assert result.online is True
    assert result.active_app == "smartdesk"


def test_activate_posts_only_allowed_app(monkeypatch):
    seen = {}

    def _open(req, **_kwargs):
        seen["method"] = req.method
        seen["body"] = req.data
        return _Response(b'{"ok":true,"app":"powerpoint","action":"activate"}')

    monkeypatch.setattr("hands.display_agent_client.request.urlopen", _open)
    result = DisplayAgentClient("http://127.0.0.1:8766/").activate("powerpoint")
    assert result.ok is True
    assert seen == {"method": "POST", "body": b'{"app": "powerpoint"}'}

    with pytest.raises(ValueError):
        DisplayAgentClient("http://127.0.0.1:8766").activate("notepad")


def test_http_409_is_online_failure(monkeypatch):
    def _open(req, **_kwargs):
        raise error.HTTPError(
            req.full_url,
            409,
            "Conflict",
            {},
            io.BytesIO(
                b'{"ok":false,"app":"solidworks","action":"none",'
                b'"detail":"SolidWorks window not found"}'
            ),
        )

    monkeypatch.setattr("hands.display_agent_client.request.urlopen", _open)
    result = DisplayAgentClient("http://127.0.0.1:8766").activate("solidworks")
    assert result.ok is False
    assert result.online is True
    assert result.status_code == 409
    assert result.detail == "SolidWorks window not found"


def test_connection_error_is_offline(monkeypatch):
    def _open(*_args, **_kwargs):
        raise error.URLError("refused")

    monkeypatch.setattr("hands.display_agent_client.request.urlopen", _open)
    result = DisplayAgentClient("http://127.0.0.1:8766").activate("smartdesk")
    assert result.ok is False
    assert result.online is False
    assert "refused" in result.detail


def test_malformed_response_is_reported(monkeypatch):
    monkeypatch.setattr(
        "hands.display_agent_client.request.urlopen",
        lambda *_args, **_kwargs: _Response(b"not-json"),
    )
    result = DisplayAgentClient("http://127.0.0.1:8766").activate("smartdesk")
    assert result.ok is False
    assert result.online is True
    assert "Invalid Display Agent response" in result.detail
