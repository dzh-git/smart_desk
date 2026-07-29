from __future__ import annotations

from fastapi.testclient import TestClient

from frontend_server import create_app


def test_static_frontend_serves_assets_and_spa_routes(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(
        "<html>SmartDesk</html>",
        encoding="utf-8",
    )
    (tmp_path / "assets" / "app.js").write_text(
        "console.log('ok')",
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path))

    assert client.get("/health").json()["status"] == "ok"
    assert "SmartDesk" in client.get("/seat/1").text
    assert "console.log" in client.get("/assets/app.js").text


def test_static_frontend_fails_clearly_without_build(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.get("/health").status_code == 503
    assert client.get("/seat/1").status_code == 503
