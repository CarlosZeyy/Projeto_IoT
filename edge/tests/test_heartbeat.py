"""Heartbeat of the edge (SPEC-018 section 4.4): ``HttpPublisher.send_heartbeat``,
``HeartbeatLoop`` and its registration by ``qc-edge``.

The cloud is an ``httpx.MockTransport``; keys are generated at run time (R-03).
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import threading
import types
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import qc_edge
from qc_contracts import MAX_HEARTBEAT_COUNT, HeartbeatCreate
from qc_edge import cli
from qc_edge.heartbeat import HeartbeatLoop
from qc_edge.inference import ModelInfo
from qc_edge.onnx_inferencer import OnnxInferencer
from qc_edge.outbox import SqliteOutbox
from qc_edge.publish_loop import PublishLoop
from qc_edge.publisher import (
    HttpPublisher,
    PublishAuthError,
    PublishTransientError,
)
from qc_edge.sink import InMemorySink, SinkError, SinkStats

BASE_URL = "https://cloud.test"
DEVICE = "edge-01"
HEARTBEAT_PATH = f"/api/v1/devices/{DEVICE}/heartbeat"
SHA = "d" * 64
MODEL = ModelInfo("partqc-test-v1", SHA)
CONSOLE = {"client": ("127.0.0.1", 50000), "base_url": "http://127.0.0.1:8000"}

Handler = Callable[[httpx.Request], httpx.Response]


def new_key() -> str:
    return "dk-" + secrets.token_urlsafe(24)


class Cloud:
    """Records every request and answers with ``handler`` (204 by default)."""

    def __init__(self, handler: Handler | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.handler = handler or (lambda request: httpx.Response(204))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


class ModelOnly:
    """An ``Inferencer`` with only the ``model_info`` the heartbeat reads."""

    def __init__(self, info: ModelInfo) -> None:
        self.model_info = info


class Monotonic:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def publisher(cloud: Cloud, key: str | None = None, **kwargs: Any) -> HttpPublisher:
    return HttpPublisher(
        BASE_URL, key or new_key(), transport=cloud.transport, device_id=DEVICE, **kwargs
    )


def heartbeat(**overrides: Any) -> HeartbeatCreate:
    fields: dict[str, Any] = {
        "sent_at": datetime.now(UTC),
        "model_version": MODEL.model_version,
        "model_sha256": SHA,
        "app_version": "0.0.0",
        "uptime_s": 5,
        "outbox_pending": 0,
        "outbox_dead": 0,
    }
    fields.update(overrides)
    return HeartbeatCreate(**fields)


@pytest.fixture
def outbox(tmp_path: Path, fake_cloud: types.ModuleType) -> Iterator[SqliteOutbox]:
    """An outbox with 2 ``pending`` rows and 1 ``dead`` row."""
    box = SqliteOutbox(tmp_path / "outbox.sqlite3")
    items = [fake_cloud.make_inspection() for _ in range(3)]
    for item in items:
        box.put(item)
    box.mark_dead(items[0].inspection_id, "HTTP 422: Value cannot be stored")
    try:
        yield box
    finally:
        box.close()


def outbox_rows(box: SqliteOutbox) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(box.path)
    try:
        return conn.execute("SELECT * FROM outbox ORDER BY rowid").fetchall()
    finally:
        conn.close()


# ---------- HttpPublisher.send_heartbeat ----------


def test_send_heartbeat_posts_the_contract_with_the_key() -> None:
    cloud = Cloud()
    key = new_key()
    sent = heartbeat(outbox_pending=2)
    publisher(cloud, key).send_heartbeat(sent)
    (request,) = cloud.requests
    assert request.method == "POST"
    assert str(request.url) == BASE_URL + HEARTBEAT_PATH
    assert request.headers["X-API-Key"] == key
    assert request.headers["Content-Type"] == "application/json"
    assert HeartbeatCreate.model_validate_json(request.content) == sent
    assert b"image" not in request.content


@pytest.mark.parametrize("status", [401, 403])
def test_send_heartbeat_auth_statuses(status: int) -> None:
    cloud = Cloud(lambda request: httpx.Response(status, json={"detail": "x"}))
    with pytest.raises(PublishAuthError, match=f"HTTP {status}"):
        publisher(cloud).send_heartbeat(heartbeat())


@pytest.mark.parametrize("status", [200, 201, 301, 404, 429, 500, 502, 503])
def test_send_heartbeat_other_statuses_are_transient(status: int) -> None:
    cloud = Cloud(lambda request: httpx.Response(status, content=b"secret-body"))
    with pytest.raises(PublishTransientError) as info:
        publisher(cloud).send_heartbeat(heartbeat())
    assert str(info.value) == f"HTTP {status}"


def test_send_heartbeat_422_is_transient_with_the_summary_only() -> None:
    echoed = "echoed-" + secrets.token_hex(6)
    body = {"detail": [{"type": "x", "input": echoed}, {"type": "y", "input": echoed}]}
    cloud = Cloud(lambda request: httpx.Response(422, json=body))
    with pytest.raises(PublishTransientError) as info:
        publisher(cloud).send_heartbeat(heartbeat())
    assert str(info.value) == "HTTP 422: 2 validation errors"


def test_send_heartbeat_network_error_never_shows_the_key() -> None:
    key = new_key()

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect with {key}")

    with pytest.raises(PublishTransientError) as info:
        publisher(Cloud(fail), key).send_heartbeat(heartbeat())
    assert key not in str(info.value)
    assert "ConnectError" in str(info.value)


def test_send_heartbeat_response_cap_and_deadline() -> None:
    big = Cloud(lambda request: httpx.Response(422, content=b"x" * 2048))
    with pytest.raises(PublishTransientError, match="response too large"):
        publisher(big, max_response_bytes=1024).send_heartbeat(heartbeat())

    clock = Monotonic()

    def slow(request: httpx.Request) -> httpx.Response:
        def chunks() -> Iterator[bytes]:
            clock.now += 16
            yield b"{}"

        return httpx.Response(422, content=chunks())

    with pytest.raises(PublishTransientError, match="request deadline exceeded"):
        publisher(Cloud(slow), monotonic=clock).send_heartbeat(heartbeat())


def test_send_heartbeat_requires_a_device_id() -> None:
    plain = HttpPublisher(BASE_URL, new_key(), transport=Cloud().transport)
    with pytest.raises(ValueError, match="device_id"):
        plain.send_heartbeat(heartbeat())


@pytest.mark.parametrize("device_id", ["EDGE_01", "ed", "edge-01\n", ""])
def test_publisher_refuses_an_invalid_device_id(device_id: str) -> None:
    with pytest.raises(ValueError, match="DEVICE_ID_PATTERN"):
        HttpPublisher(BASE_URL, new_key(), device_id=device_id)


# ---------- HeartbeatLoop ----------


def test_build_with_model_and_outbox_counts(outbox: SqliteOutbox) -> None:
    clock = Monotonic(500.0)
    loop = HeartbeatLoop(
        publisher(Cloud()), outbox, ModelOnly(MODEL), interval_s=60, monotonic=clock
    )
    clock.now += 7500.9
    built = loop.build()
    assert (built.model_version, built.model_sha256) == (MODEL.model_version, SHA)
    assert (built.outbox_pending, built.outbox_dead) == (2, 1)
    assert built.uptime_s == 7500
    assert built.app_version == qc_edge.__version__
    assert abs(built.sent_at - datetime.now(UTC)) < timedelta(seconds=5)


def test_build_without_model() -> None:
    loop = HeartbeatLoop(publisher(Cloud()), InMemorySink(), None, interval_s=60)
    built = loop.build()
    assert built.model_version is None and built.model_sha256 is None
    assert (built.outbox_pending, built.outbox_dead) == (0, 0)


def test_build_caps_the_counters() -> None:
    class HugeSink(InMemorySink):
        def stats(self) -> SinkStats:
            return SinkStats(MAX_HEARTBEAT_COUNT + 5, MAX_HEARTBEAT_COUNT + 9, None, "offline")

    clock = Monotonic(0.0)
    loop = HeartbeatLoop(publisher(Cloud()), HugeSink(), None, interval_s=60, monotonic=clock)
    clock.now = 10.0 * MAX_HEARTBEAT_COUNT
    built = loop.build()
    assert built.uptime_s == built.outbox_pending == built.outbox_dead == MAX_HEARTBEAT_COUNT
    clock.now = -50.0  # a monotonic clock never goes back, but the value is never negative
    assert loop.build().uptime_s == 0


def test_run_once_sends_one_heartbeat(outbox: SqliteOutbox, dummy_model: types.ModuleType) -> None:
    directory = dummy_model.write_model_dir(Path(outbox.path).parent / "models")
    inferencer = OnnxInferencer(directory)
    cloud = Cloud()
    key = new_key()
    HeartbeatLoop(publisher(cloud, key), outbox, inferencer, interval_s=60).run_once()
    (request,) = cloud.requests
    assert request.url.path == HEARTBEAT_PATH
    assert request.headers["X-API-Key"] == key
    body = HeartbeatCreate.model_validate_json(request.content)
    assert body.model_version == inferencer.model_info.model_version == directory.name
    assert body.model_sha256 == inferencer.model_info.model_sha256
    assert (body.outbox_pending, body.outbox_dead) == (2, 1)


def test_run_once_without_model_sends_nulls(outbox: SqliteOutbox) -> None:
    cloud = Cloud()
    HeartbeatLoop(publisher(cloud), outbox, None, interval_s=60).run_once()
    payload = json.loads(cloud.requests[0].content)
    assert payload["model_version"] is None and payload["model_sha256"] is None


@pytest.mark.parametrize("failure", ["connect", "503", "timeout"])
def test_cloud_down_is_a_warning_and_the_outbox_does_not_change(
    outbox: SqliteOutbox, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "connect":
            raise httpx.ConnectError("connection refused")
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(503, json={"detail": "Database unavailable"})

    cloud = Cloud(handler)
    key = new_key()
    before = outbox_rows(outbox)
    loop = HeartbeatLoop(publisher(cloud, key), outbox, None, interval_s=60)
    with caplog.at_level(logging.DEBUG, logger="qc_edge"):
        for _ in range(3):
            loop.run_once()
    assert len(cloud.requests) == 3
    assert outbox_rows(outbox) == before
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 3
    assert all(r.getMessage().startswith("heartbeat failed: ") for r in warnings)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert key not in caplog.text
    assert not loop.auth_error


@pytest.mark.parametrize("status", [401, 403])
def test_auth_error_stops_the_loop_with_one_error(
    outbox: SqliteOutbox, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    cloud = Cloud(lambda request: httpx.Response(status, json={"detail": "nope"}))
    key = new_key()
    loop = HeartbeatLoop(publisher(cloud, key), outbox, None, interval_s=60)
    with caplog.at_level(logging.DEBUG, logger="qc_edge"):
        loop.run_once()
        loop.run_once()
    assert len(cloud.requests) == 1
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "DEVICE_API_KEY" in errors[0].getMessage()
    assert loop.auth_error
    assert key not in caplog.text


def test_sink_error_skips_the_cycle(caplog: pytest.LogCaptureFixture) -> None:
    class BrokenSink(InMemorySink):
        def stats(self) -> SinkStats:
            raise SinkError("outbox read failed (OperationalError)")

    cloud = Cloud()
    loop = HeartbeatLoop(publisher(cloud), BrokenSink(), None, interval_s=60)
    with caplog.at_level(logging.WARNING, logger="qc_edge"):
        loop.run_once()
    assert cloud.requests == []
    assert "heartbeat skipped" in caplog.text


def test_invalid_heartbeat_is_skipped_without_values(caplog: pytest.LogCaptureFixture) -> None:
    cloud = Cloud()
    loop = HeartbeatLoop(
        publisher(cloud), InMemorySink(), None, interval_s=60, app_version="bad version"
    )
    with caplog.at_level(logging.WARNING, logger="qc_edge"):
        loop.run_once()
    assert cloud.requests == []
    assert "1 validation errors" in caplog.text
    assert "bad version" not in caplog.text


def test_unexpected_publisher_error_is_a_warning_with_the_class_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Exploding:
        def send_heartbeat(self, heartbeat: HeartbeatCreate) -> None:
            raise RuntimeError("detail-" + "x" * 10)

    loop = HeartbeatLoop(Exploding(), InMemorySink(), None, interval_s=60)
    with caplog.at_level(logging.WARNING, logger="qc_edge"):
        loop.run_once()
    assert "heartbeat failed unexpectedly: RuntimeError" in caplog.text
    assert "detail-" not in caplog.text


@pytest.mark.parametrize("interval", [0, -1, float("nan")])
def test_interval_must_be_positive(interval: float) -> None:
    with pytest.raises(ValueError, match="interval_s"):
        HeartbeatLoop(publisher(Cloud()), InMemorySink(), None, interval_s=interval)


def test_thread_sends_right_away_and_stops() -> None:
    sent = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        sent.set()
        return httpx.Response(204)

    cloud = Cloud(handler)
    loop = HeartbeatLoop(publisher(cloud), InMemorySink(), None, interval_s=3600)
    loop.start()
    try:
        assert sent.wait(5)
    finally:
        loop.stop()
    assert len(cloud.requests) == 1
    loop.stop()  # idempotent


def test_thread_ends_after_an_auth_error() -> None:
    cloud = Cloud(lambda request: httpx.Response(401))
    loop = HeartbeatLoop(publisher(cloud), InMemorySink(), None, interval_s=10)
    loop.start()
    thread = loop._thread
    assert thread is not None
    thread.join(5)
    assert not thread.is_alive()
    assert len(cloud.requests) == 1
    loop.stop()


# ---------- registration by qc-edge (SPEC-018 section 4.4, SPEC-009 section 4.4) ----------


class _Spy:
    def __init__(self) -> None:
        self.background: list[Any] = []
        self.sink: Any = None
        self.app: Any = None
        self.inferencer: Any = None

    def create_app(self, settings: Any, inferencer: Any, sink: Any, **kwargs: Any) -> Any:
        self.sink = sink
        self.inferencer = inferencer
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


@pytest.fixture
def cloud_env(monkeypatch: pytest.MonkeyPatch) -> str:
    device_key = new_key()
    monkeypatch.setenv("DEVICE_API_KEY", device_key)
    monkeypatch.setenv("CLOUD_API_URL", "http://127.0.0.1:9")
    return device_key


def _kinds(spy: _Spy) -> list[type]:
    return [type(service) for service in spy.background]


def test_heartbeat_registered_with_the_publish_loop(
    spy: _Spy, cloud_env: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="qc_edge"):
        cli.main([])
    assert _kinds(spy) == [PublishLoop, HeartbeatLoop]
    heartbeat_loop = spy.background[1]
    assert heartbeat_loop.interval_s == 60
    assert heartbeat_loop._sink is spy.sink
    assert heartbeat_loop._publisher is not spy.background[0]._publisher
    assert "heartbeat enabled (every 60 s)" in caplog.text
    assert cloud_env not in caplog.text


def test_heartbeat_uses_the_loaded_model(
    spy: _Spy, cloud_env: str, dummy_model: types.ModuleType, tmp_path: Path, monkeypatch
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models")
    monkeypatch.setenv("MODEL_DIR", str(directory))
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", "3600")
    cli.main([])
    heartbeat_loop = spy.background[1]
    assert heartbeat_loop.interval_s == 3600
    assert heartbeat_loop._inferencer is spy.inferencer
    assert heartbeat_loop.build().model_version == directory.name


@pytest.mark.parametrize("value", ["10", "3600", ""])
def test_valid_intervals(spy: _Spy, cloud_env: str, monkeypatch, value: str) -> None:
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", value)
    cli.main([])
    assert spy.background[1].interval_s == int(value or 60)


def test_interval_zero_turns_the_heartbeat_off(spy: _Spy, cloud_env: str, monkeypatch) -> None:
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", "0")
    cli.main([])
    assert _kinds(spy) == [PublishLoop]


def test_no_heartbeat_with_stub_model(spy: _Spy, cloud_env: str) -> None:
    cli.main(["--stub-model"])
    assert spy.background == []


@pytest.mark.parametrize("missing", ["DEVICE_API_KEY", "CLOUD_API_URL"])
def test_no_heartbeat_without_key_or_url(
    spy: _Spy, cloud_env: str, monkeypatch, missing: str
) -> None:
    monkeypatch.delenv(missing)
    cli.main([])
    assert spy.background == []


@pytest.mark.parametrize("value", ["5", "9", "3601", "-1", "abc", "60.5", "1e3"])
@pytest.mark.parametrize("stub", [False, True])
def test_invalid_interval_exits_2(
    spy: _Spy, cloud_env: str, monkeypatch, caplog: pytest.LogCaptureFixture, value: str, stub: bool
) -> None:
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", value)
    with caplog.at_level(logging.INFO, logger="qc_edge"), pytest.raises(SystemExit) as info:
        cli.main(["--stub-model"] if stub else [])
    assert info.value.code == 2
    assert "HEARTBEAT_INTERVAL_S" in caplog.text


def test_capture_keeps_working_with_the_cloud_down(
    spy: _Spy,
    cloud_env: str,
    dummy_model: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    jpeg_bytes: bytes,
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models")
    monkeypatch.setenv("MODEL_DIR", str(directory))
    cli.main([])  # the URL points to a closed port: every heartbeat fails
    with TestClient(spy.app, **CONSOLE) as client:
        spy.background[1].run_once()
        response = client.post(
            "/api/capture",
            headers={"X-Session-Token": client.app.state.session_token},
            data={"lot_id": "L-001", "mode": "inspect"},
            files={"image": ("a.jpg", jpeg_bytes, "image/jpeg")},
        )
    assert response.status_code == 200
    assert spy.sink.stats().pending == 1
