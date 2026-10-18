"""``qc-edge`` with the outbox and the cloud settings (SPEC-009 sections 3.1 and 4.2)."""

from __future__ import annotations

import logging
import secrets
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from qc_edge import cli
from qc_edge.config import EdgeSettings, check_cloud_api_url
from qc_edge.outbox import SqliteOutbox
from qc_edge.publish_loop import PublishLoop

CONSOLE = {"client": ("127.0.0.1", 50000), "base_url": "http://127.0.0.1:8000"}


class _Spy:
    """Replaces ``create_app`` (keeps the real app) and ``uvicorn.run``."""

    def __init__(self) -> None:
        self.background: list[Any] = []
        self.sink: Any = None
        self.app: Any = None

    def create_app(self, settings: Any, inferencer: Any, sink: Any, **kwargs: Any) -> Any:
        self.sink = sink
        self.background = list(kwargs.get("background", ()))
        self.app = _real_create_app(settings, inferencer, sink, **kwargs)
        return self.app


_real_create_app = cli.create_app


@pytest.fixture
def spy(clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Spy:
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "data"))
    spy = _Spy()
    monkeypatch.setattr(cli, "create_app", spy.create_app)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: None)
    return spy


def key() -> str:
    return "dk-" + secrets.token_urlsafe(24)


def capture(client: TestClient, image: bytes) -> int:
    return client.post(
        "/api/capture",
        headers={"X-Session-Token": client.app.state.session_token},
        data={"lot_id": "L-001", "mode": "inspect"},
        files={"image": ("a.jpg", image, "image/jpeg")},
    ).status_code


def test_default_outbox_path_and_disabled_without_key(
    spy: _Spy, tmp_path: Path, jpeg_bytes: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="qc_edge"):
        cli.main(["--stub-model"])
    assert isinstance(spy.sink, SqliteOutbox)
    assert spy.sink.path == tmp_path / "data" / "outbox.sqlite3"
    assert spy.background == []
    client = TestClient(spy.app, **CONSOLE)
    for _ in range(3):
        assert capture(client, jpeg_bytes) == 200
    status = client.get(
        "/api/status", headers={"X-Session-Token": spy.app.state.session_token}
    ).json()
    assert status["sink"]["pending"] == 3
    assert status["sink"]["connectivity"] == "disabled"
    assert 'data-connectivity="disabled"' in client.get("/").text
    assert "cloud publishing disabled (--stub-model)" in caplog.text


@pytest.mark.parametrize(
    ("variables", "reason"),
    [
        ({"CLOUD_API_URL": "http://127.0.0.1:9000"}, "DEVICE_API_KEY not set"),
        ({"DEVICE_API_KEY": "set"}, "CLOUD_API_URL not set"),
        ({}, "DEVICE_API_KEY and CLOUD_API_URL not set"),
    ],
)
def test_no_loop_without_key_and_url(
    spy: _Spy,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    variables: dict[str, str],
    reason: str,
) -> None:
    for name, value in variables.items():
        monkeypatch.setenv(name, key() if value == "set" else value)
    with caplog.at_level(logging.INFO, logger="qc_edge"):
        cli.main([])
    assert spy.background == []
    assert spy.sink.stats().connectivity == "disabled"
    assert reason in caplog.text


def test_stub_model_never_publishes_even_with_key_and_url(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVICE_API_KEY", key())
    monkeypatch.setenv("CLOUD_API_URL", "http://127.0.0.1:9000")
    cli.main(["--stub-model"])
    assert spy.background == []
    assert spy.sink.stats().connectivity == "disabled"


def test_loop_with_key_and_local_url(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    device_key = key()
    outbox_path = tmp_path / "elsewhere" / "box.sqlite3"
    monkeypatch.setenv("DEVICE_API_KEY", device_key)
    monkeypatch.setenv("CLOUD_API_URL", "http://127.0.0.1:9000/")
    monkeypatch.setenv("OUTBOX_PATH", str(outbox_path))
    with caplog.at_level(logging.DEBUG):
        cli.main([])
    (loop,) = spy.background
    assert isinstance(loop, PublishLoop)
    assert spy.sink.path == outbox_path
    assert spy.sink.stats().connectivity == "offline"
    assert "cloud publishing enabled" in caplog.text
    assert device_key not in caplog.text


@pytest.mark.parametrize("url", ["http://api.exemplo.org", "https://user:pw@api.exemplo.org"])
def test_invalid_cloud_url_exits_2(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, url: str
) -> None:
    monkeypatch.setenv("DEVICE_API_KEY", key())
    monkeypatch.setenv("CLOUD_API_URL", url)
    with caplog.at_level(logging.INFO, logger="qc_edge"), pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2
    assert "CLOUD_API_URL" in caplog.text
    assert url not in caplog.text
    assert "api.exemplo.org" not in caplog.text
    assert spy.app is None


def test_invalid_device_key_exits_2_without_the_value(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    bad = "chave inválida " + secrets.token_hex(4)
    monkeypatch.setenv("DEVICE_API_KEY", bad)
    monkeypatch.setenv("CLOUD_API_URL", "https://api.exemplo.org")
    with caplog.at_level(logging.INFO, logger="qc_edge"), pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2
    assert "DEVICE_API_KEY" in caplog.text
    assert bad not in caplog.text


def test_unopenable_outbox_exits_2(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    directory = tmp_path / "is-a-directory"
    directory.mkdir()
    monkeypatch.setenv("OUTBOX_PATH", str(directory))
    with caplog.at_level(logging.INFO, logger="qc_edge"), pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2
    assert "OUTBOX_PATH" in caplog.text


def test_outbox_survives_a_restart(spy: _Spy, jpeg_bytes: bytes, tmp_path: Path) -> None:
    cli.main(["--stub-model"])
    assert capture(TestClient(spy.app), jpeg_bytes) == 200
    cli.main(["--stub-model"])
    assert spy.sink.stats().pending == 1
    conn = sqlite3.connect(tmp_path / "data" / "outbox.sqlite3")
    try:
        assert conn.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
    finally:
        conn.close()


# -- CLOUD_API_URL -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.exemplo.org", "https://api.exemplo.org"),
        ("https://api.exemplo.org/", "https://api.exemplo.org"),
        ("https://api.exemplo.org:8443/base/", "https://api.exemplo.org:8443/base"),
        ("HTTPS://API.exemplo.org", "HTTPS://API.exemplo.org"),
        ("http://localhost:8001", "http://localhost:8001"),
        ("http://127.0.0.1:9000", "http://127.0.0.1:9000"),
    ],
)
def test_check_cloud_api_url_accepts(url: str, expected: str) -> None:
    assert check_cloud_api_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://api.exemplo.org",
        "http://10.0.0.5:8001",
        "http://[::1]:8001",
        "ws://localhost",
        "https://",
        "https:///path",
        "//api.exemplo.org",
        "https://u@api.exemplo.org",
        "https://api.exemplo.org/?a=1",
        "https://api.exemplo.org/#x",
        "https://api.exemplo.org:99999",
        "https://api.exemplo.org/ x",
        "https://api.exemplo.org\n",
        " https://api.exemplo.org",
    ],
)
def test_check_cloud_api_url_refuses(url: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        check_cloud_api_url(url)
    if "exemplo" in url:
        assert "exemplo" not in str(excinfo.value)


def test_settings_validate_cloud_api_url(clean_edge_env: None, tmp_path: Path) -> None:
    settings = EdgeSettings(EDGE_DATA_DIR=tmp_path, CLOUD_API_URL="https://api.exemplo.org/")
    assert settings.CLOUD_API_URL == "https://api.exemplo.org"
    with pytest.raises(ValueError, match="CLOUD_API_URL"):
        EdgeSettings(EDGE_DATA_DIR=tmp_path, CLOUD_API_URL="http://api.exemplo.org")
