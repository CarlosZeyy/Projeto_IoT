"""Lifespan, CLI and log hygiene (SPEC-007 sections 4.2 and 4.3)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import ImageFile

from qc_edge import cli
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import StubInferencer
from qc_edge.sink import InMemorySink


class _Service:
    def __init__(self, name: str, events: list[str], fail_stop: bool = False) -> None:
        self.name = name
        self.events = events
        self.fail_stop = fail_stop

    def start(self) -> None:
        self.events.append(f"start {self.name}")

    def stop(self) -> None:
        self.events.append(f"stop {self.name}")
        if self.fail_stop:
            raise RuntimeError("stop failed")


class _UvicornSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, app: Any, **kwargs: Any) -> None:
        self.calls.append((app, kwargs))


@pytest.fixture
def uvicorn_spy(monkeypatch: pytest.MonkeyPatch) -> _UvicornSpy:
    spy = _UvicornSpy()
    monkeypatch.setattr(cli.uvicorn, "run", spy)
    return spy


@pytest.fixture
def edge_env(clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("EDGE_DATA_DIR", str(data_dir))
    return data_dir


def test_background_services_start_in_order_and_stop_in_reverse(settings: EdgeSettings) -> None:
    events: list[str] = []
    services = [_Service("a", events), _Service("b", events, fail_stop=True), _Service("c", events)]
    app = create_app(settings, None, InMemorySink(), background=services)
    with TestClient(app):
        assert events == ["start a", "start b", "start c"]
    assert events[3:] == ["stop c", "stop b", "stop a"]


def test_startup_refuses_the_truncated_images_flag(
    settings: EdgeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    app = create_app(settings, None, InMemorySink(), background=[_Service("a", events)])
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    with pytest.raises(RuntimeError, match="LOAD_TRUNCATED_IMAGES"), TestClient(app):
        pass
    assert events == []  # checked before any background service


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EDGE_PORT", "70000"),
        ("DEVICE_ID", "Edge_01"),
        ("DEVICE_ID", "edge-01\n"),
        ("EDGE_SESSION_TOKEN", "0123456789"),
        ("EDGE_HOST", "not-an-ip"),
    ],
)
def test_invalid_configuration_exits_2_naming_the_variable(
    edge_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_spy: _UvicornSpy,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)
    with caplog.at_level(logging.INFO, logger="qc_edge"), pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2
    assert name in caplog.text
    if name == "EDGE_SESSION_TOKEN":
        assert value not in caplog.text
    assert uvicorn_spy.calls == []


def test_flag_exits_1_without_starting_the_server(
    edge_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_spy: _UvicornSpy,
) -> None:
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    with caplog.at_level(logging.INFO, logger="qc_edge"), pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 1
    assert "LOAD_TRUNCATED_IMAGES" in caplog.text
    assert uvicorn_spy.calls == []


def test_main_runs_uvicorn_without_proxy_headers(
    edge_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_spy: _UvicornSpy,
) -> None:
    monkeypatch.setenv("EDGE_PORT", "8123")
    with caplog.at_level(logging.INFO, logger="qc_edge"):
        cli.main([])
    ((app, kwargs),) = uvicorn_spy.calls
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8123
    assert kwargs["proxy_headers"] is False
    assert kwargs["access_log"] is False
    assert "http://127.0.0.1:8123/" in caplog.text
    assert app.state.session_token not in caplog.text
    assert "model not loaded" in caplog.text


def test_stub_model_flag(edge_env: Path, uvicorn_spy: _UvicornSpy, jpeg_bytes: bytes) -> None:
    cli.main(["--stub-model"])
    ((app, _),) = uvicorn_spy.calls
    token = app.state.session_token
    response = TestClient(app).post(
        "/api/capture",
        headers={"X-Session-Token": token},
        data={"lot_id": "L-001", "mode": "inspect"},
        files={"image": ("a.jpg", jpeg_bytes, "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["inspection"]["model_version"] == "stub-v0"


def test_unknown_arguments_are_ignored(
    edge_env: Path, uvicorn_spy: _UvicornSpy, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="qc_edge"):
        cli.main(["-q", "--stub", "--opt=hidden-value", "edge/tests"])
    assert len(uvicorn_spy.calls) == 1
    assert "ignoring 4 unknown command-line argument(s): -q --stub --opt" in caplog.text
    assert "hidden-value" not in caplog.text


def test_main_without_argv_reads_sys_argv(
    edge_env: Path, uvicorn_spy: _UvicornSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["qc-edge", "--stub-model"])
    cli.main()
    ((app, _),) = uvicorn_spy.calls
    assert (
        TestClient(app)
        .get("/api/status", headers={"X-Session-Token": app.state.session_token})
        .json()["model"]["loaded"]
    )


def test_logs_never_contain_the_token_or_the_device_key(
    edge_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    uvicorn_spy: _UvicornSpy,
    jpeg_bytes: bytes,
) -> None:
    token = "T0k" + "e" * 37
    device_key = "dk_" + "z" * 29
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setenv("DEVICE_API_KEY", device_key)
    with caplog.at_level(logging.DEBUG):
        cli.main(["--stub-model"])
        ((app, _),) = uvicorn_spy.calls
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            client.get(f"/capture?t={token}")
            client.get("/")
            for headers, image in (
                ({"X-Session-Token": token}, jpeg_bytes),
                ({"X-Session-Token": "wrong"}, jpeg_bytes),
                ({"X-Session-Token": token}, b"not an image"),
            ):
                client.post(
                    "/api/capture",
                    headers=headers,
                    data={"lot_id": "L-001", "mode": "inspect"},
                    files={"image": ("a.jpg", image, "image/jpeg")},
                )
    captured = capsys.readouterr()
    # The test client's own ``httpx`` logger prints the request URL: it is not the server.
    server_lines = "\n".join(
        record.getMessage() for record in caplog.records if not record.name.startswith("httpx")
    )
    assert "GET /capture 200" in server_lines  # the request log ran
    for text in (server_lines, captured.err, captured.out):
        assert token not in text
        assert device_key not in text


def test_stub_inferencer_is_never_the_default(edge_env: Path, uvicorn_spy: _UvicornSpy) -> None:
    cli.main([])
    ((app, _),) = uvicorn_spy.calls
    status = TestClient(app).get(
        "/api/status", headers={"X-Session-Token": app.state.session_token}
    )
    assert status.json()["model"]["loaded"] is False
    assert not isinstance(getattr(app.state, "inferencer", None), StubInferencer)
