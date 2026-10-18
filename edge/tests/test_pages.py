"""Console, phone page, static files and /api/status (SPEC-007 section 4.4)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from qc_edge import netinfo
from qc_edge.app import STATIC_DIR, TEMPLATES_DIR, create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import StubInferencer
from qc_edge.sink import InMemorySink, SinkStats

LOCAL = ("127.0.0.1", 50000)
START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
def lan_ips(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    ips = ["192.168.0.42", "10.0.0.7"]
    monkeypatch.setattr(netinfo, "detect_lan_ips", lambda: list(ips))
    return ips


def _app(settings: EdgeSettings, **kwargs: Any) -> Any:
    kwargs.setdefault("inferencer", StubInferencer())
    kwargs.setdefault("sink", InMemorySink())
    return create_app(settings, kwargs.pop("inferencer"), kwargs.pop("sink"), **kwargs)


def _capture(client: TestClient, token: str, image: bytes, lot_id: str) -> None:
    response = client.post(
        "/api/capture",
        headers={"X-Session-Token": token},
        data={"lot_id": lot_id, "mode": "inspect"},
        files={"image": ("a.jpg", image, "image/jpeg")},
    )
    assert response.status_code == 200


def test_console_from_loopback(settings: EdgeSettings, lan_ips: list[str], jpeg_bytes: bytes):
    app = _app(settings, clock=_Clock())
    token = app.state.session_token
    client = TestClient(app, client=LOCAL)
    for index in range(12):
        _capture(client, token, jpeg_bytes, f"L-{index:03d}")
    response = client.get("/")
    assert response.status_code == 200
    page = response.text
    assert "<svg" in page
    assert f"http://192.168.0.42:8000/capture?t={token}" in page
    assert 'href="/?ip=10.0.0.7"' in page
    assert "carregado: stub-v0" in page
    assert re.search(r'id="sink-pending">12<', page)
    assert '<meta http-equiv="refresh" content="5">' in page
    assert "<script" not in page
    lots = re.findall(r'<tr class="inspection"[^>]*><td>[^<]*</td><td>(L-\d{3})</td>', page)
    assert lots == [f"L-{index:03d}" for index in range(11, 1, -1)]
    assert response.headers["cache-control"] == "no-store"


def test_console_ip_parameter_must_be_detected(settings: EdgeSettings, lan_ips: list[str]):
    app = _app(settings)
    token = app.state.session_token
    client = TestClient(app, client=LOCAL)
    assert f"http://10.0.0.7:8000/capture?t={token}" in client.get("/?ip=10.0.0.7").text
    page = client.get("/?ip=8.8.8.8").text
    assert f"http://192.168.0.42:8000/capture?t={token}" in page
    assert "8.8.8.8" not in page


def test_console_without_model_and_without_lan(
    settings: EdgeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(netinfo, "detect_lan_ips", lambda: ["127.0.0.1"])
    app = _app(settings, inferencer=None)
    page = TestClient(app, client=LOCAL).get("/").text
    assert 'id="no-lan-warning"' in page
    assert "não carregado" in page
    assert "http://127.0.0.1:8000/capture?t=" in page


def test_console_shows_sink_stats(settings: EdgeSettings, lan_ips: list[str]) -> None:
    class _Sink(InMemorySink):
        def stats(self) -> SinkStats:
            return SinkStats(pending=7, dead=2, last_success_at=START, connectivity="offline")

    page = TestClient(_app(settings, sink=_Sink()), client=LOCAL).get("/").text
    assert re.search(r'id="sink-pending">7<', page)
    assert "offline" in page


@pytest.mark.parametrize(
    ("client", "headers"),
    [
        (("192.168.1.50", 50000), {}),
        (("10.0.0.7", 50000), {}),
        (LOCAL, {"X-Forwarded-For": "1.2.3.4"}),
        (LOCAL, {"CF-Connecting-IP": "1.2.3.4"}),
        (LOCAL, {"Forwarded": "for=1.2.3.4"}),
    ],
)
def test_console_refuses_non_local_or_proxied(
    settings: EdgeSettings, lan_ips: list[str], client: tuple[str, int], headers: dict[str, str]
) -> None:
    app = _app(settings)
    response = TestClient(app, client=client).get("/", headers=headers)
    assert response.status_code == 403
    assert app.state.session_token not in response.text


def test_console_accepts_ipv6_loopback(settings: EdgeSettings, lan_ips: list[str]) -> None:
    assert TestClient(_app(settings), client=("::1", 50000)).get("/").status_code == 200


def test_capture_page(settings: EdgeSettings) -> None:
    app = _app(settings)
    client = TestClient(app)
    response = client.get(f"/capture?t={app.state.session_token}")
    assert response.status_code == 200
    page = response.text
    assert '<input type="file" accept="image/*" capture="environment">' in page
    assert 'name="lot_id"' in page
    # SPEC-010: "coleta" is enabled and the collect fields are on the page.
    assert re.search(r'<option value="collect">coleta</option>', page)
    assert "disabled" not in page
    for name in ("item_id", "object_type", "grade", "labeler", "angle", "notes"):
        assert f'name="{name}"' in page, name
    assert response.headers["referrer-policy"] == "no-referrer"
    for query in ("", "?t=", "?t=wrong"):
        refused = client.get(f"/capture{query}")
        assert refused.status_code == 401
        assert "Sessão inválida. Leia o QR code no console." in refused.text


def test_page_files_are_self_contained() -> None:
    script = (STATIC_DIR / "capture.js").read_text(encoding="utf-8")
    assert len(script.splitlines()) <= 200
    for path in (
        TEMPLATES_DIR / "capture.html",
        STATIC_DIR / "capture.js",
        STATIC_DIR / "capture.css",
    ):
        text = path.read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, path.name
    # The page always sends the re-encoded JPEG, never the original file.
    assert "toBlob" in script and '"image/jpeg"' in script
    assert "Borda ocupada. Tente de novo." in script
    assert "Não foi possível preparar a foto. Tente de novo." in script


def test_static_files_are_served(settings: EdgeSettings) -> None:
    client = TestClient(_app(settings))
    assert client.get("/static/capture.js").status_code == 200
    assert client.get("/static/capture.css").status_code == 200
    assert client.get("/static/../app.py").status_code == 404


def test_captures_are_never_served(settings: EdgeSettings, jpeg_bytes: bytes) -> None:
    app = _app(settings)
    client = TestClient(app, client=LOCAL)
    body = client.post(
        "/api/capture",
        headers={"X-Session-Token": app.state.session_token},
        data={"lot_id": "L-001", "mode": "inspect"},
        files={"image": ("a.jpg", jpeg_bytes, "image/jpeg")},
    ).json()
    day = body["inspection"]["inspected_at"][:10]
    name = f"{body['inspection']['inspection_id']}.jpg"
    for prefix in ("/captures", "/data/captures", "/static/captures", "/edge/data/captures"):
        assert client.get(f"{prefix}/{day}/{name}").status_code == 404


def test_status(settings: EdgeSettings) -> None:
    app = _app(settings)
    client = TestClient(app)
    token = app.state.session_token
    body = client.get("/api/status", headers={"X-Session-Token": token}).json()
    assert set(body) == {"device_id", "contract_version", "model", "sink"}
    assert body["device_id"] == "edge-01"
    assert body["model"] == {"loaded": True, "model_version": "stub-v0", "model_sha256": "0" * 64}
    assert body["sink"] == {
        "pending": 0,
        "dead": 0,
        "last_success_at": None,
        "connectivity": "disabled",
    }
    for headers in ({}, {"X-Session-Token": "nope"}):
        response = client.get("/api/status", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid session token"}


def test_status_without_model_and_with_last_success(settings: EdgeSettings) -> None:
    class _Sink(InMemorySink):
        def stats(self) -> SinkStats:
            return SinkStats(pending=1, dead=0, last_success_at=START, connectivity="online")

    app = _app(settings, inferencer=None, sink=_Sink())
    body = TestClient(app).get("/api/status", headers={"X-Session-Token": app.state.session_token})
    payload = body.json()
    assert payload["model"] == {"loaded": False, "model_version": None, "model_sha256": None}
    assert datetime.fromisoformat(payload["sink"]["last_success_at"]) == START


def test_configured_token_is_the_one_accepted(clean_edge_env: None, data_dir: Any) -> None:
    token = "s" * 40
    settings = EdgeSettings(EDGE_DATA_DIR=data_dir, EDGE_SESSION_TOKEN=token)
    app = _app(settings)
    client = TestClient(app)
    assert app.state.session_token == token
    assert client.get("/api/status", headers={"X-Session-Token": token}).status_code == 200


def test_no_openapi_docs(settings: EdgeSettings) -> None:
    client = TestClient(_app(settings))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
