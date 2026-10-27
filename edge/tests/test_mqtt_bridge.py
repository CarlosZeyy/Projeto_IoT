"""The bridge (SPEC-020 section 4.4) and the whole MQTT path with the ``PublishLoop``.

The cloud is the ``FakeCloud`` of SPEC-009 (``httpx.MockTransport`` with the SPEC-004
idempotency), reached by a real ``HttpPublisher``; the broker is the ``InMemoryBroker``; the
bridge and the publisher run in the same process, and the loop has a manual clock.
"""

from __future__ import annotations

import json
import logging
import os
import random
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from qc_contracts import BatchResult, InspectionCreate
from qc_edge import mqtt_bridge
from qc_edge.config import BridgeSettings
from qc_edge.mqtt_bridge import INVALID_BATCH, MqttBridge
from qc_edge.mqtt_publisher import MqttPublisher, batch_topic, health_topic
from qc_edge.mqtt_transport import (
    InMemoryBroker,
    MqttMessage,
    MqttTransportError,
    PahoMqttTransport,
)
from qc_edge.outbox import SqliteOutbox
from qc_edge.publish_loop import ConnectivityState, PublishLoop
from qc_edge.publisher import (
    HttpPublisher,
    PublishAuthError,
    PublishRejectedError,
    PublishResult,
    PublishTransientError,
)

DEVICE = "edge-01"
REPLY = "partqc/v1/edge-01/reply/abcdef0123456789"
SUMMARY = "HTTP 422: Value cannot be stored"
ROOT = Path(__file__).resolve().parents[2]


def device_key() -> str:
    return "dk-" + secrets.token_urlsafe(24)


class StubPublisher:
    """A ``Publisher`` whose outcome is set by the test."""

    def __init__(self, outcome: Any = None, healthy: Any = True) -> None:
        self.outcome = outcome
        self.healthy = healthy
        self.batches: list[list[InspectionCreate]] = []

    def publish_batch(self, items: Any) -> list[PublishResult]:
        self.batches.append(list(items))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return [PublishResult(item.inspection_id, "created") for item in items]

    def check_health(self) -> bool:
        if isinstance(self.healthy, Exception):
            raise self.healthy
        return bool(self.healthy)


class Wire:
    """A bridge on an ``InMemoryBroker`` and a client that sends requests and keeps answers."""

    def __init__(self, publisher: Any) -> None:
        self.broker = InMemoryBroker()
        self.bridge = MqttBridge(self.broker.client("bridge"), publisher, DEVICE)
        self.bridge.start()
        self.client = self.broker.client("edge")
        self.answers: list[MqttMessage] = []
        self.client.subscribe("partqc/v1/edge-01/reply/#", self.answers.append)
        self.client.connect()

    def send(self, topic: str, payload: bytes = b"", **props: Any) -> None:
        props.setdefault("response_topic", REPLY)
        props.setdefault("correlation_data", b"\x07" * 16)
        self.client.publish(MqttMessage(topic, payload, **props))


def batch_payload(fake_cloud: types.ModuleType, n: int = 2) -> tuple[bytes, list[Any]]:
    items = [fake_cloud.make_inspection() for _ in range(n)]
    body = {"items": [json.loads(i.model_dump_json()) for i in items]}
    return json.dumps(body).encode(), items


# -- MqttBridge.handle -------------------------------------------------------------------------


def test_start_subscribes_only_the_two_request_topics() -> None:
    wire = Wire(StubPublisher())
    assert wire.bridge.topics == ("partqc/v1/edge-01/batch", "partqc/v1/edge-01/health")
    subscriptions = wire.broker._subscriptions
    filters = sorted(f for client, f, _h in subscriptions if client.client_id == "bridge")
    assert filters == ["partqc/v1/edge-01/batch", "partqc/v1/edge-01/health"]


def test_batch_ok_answers_the_batch_result(fake_cloud: types.ModuleType) -> None:
    stub = StubPublisher()
    wire = Wire(stub)
    payload, items = batch_payload(fake_cloud, 3)
    wire.send(batch_topic(DEVICE), payload)
    (answer,) = wire.answers
    assert answer.topic == REPLY
    assert answer.correlation_data == b"\x07" * 16
    assert answer.user_properties == (("result", "ok"),)
    result = BatchResult.model_validate_json(answer.payload)
    assert [r.inspection_id for r in result.results] == [i.inspection_id for i in items]
    assert [i.inspection_id for i in stub.batches[0]] == [i.inspection_id for i in items]


@pytest.mark.parametrize(
    "payload",
    [b"not json", b"{}", b'{"items": []}', b'{"items": [{"x": 1}]}', b"\xff\xfe"],
    ids=["not-json", "no-items", "empty", "invalid-item", "not-utf8"],
)
def test_invalid_batch_is_rejected_without_calling_the_api(payload: bytes) -> None:
    stub = StubPublisher()
    wire = Wire(stub)
    wire.send(batch_topic(DEVICE), payload)
    (answer,) = wire.answers
    assert answer.user_property("result") == "rejected"
    assert answer.payload == INVALID_BATCH.encode()
    assert stub.batches == []


def test_batch_of_101_items_is_rejected(fake_cloud: types.ModuleType) -> None:
    stub = StubPublisher()
    wire = Wire(stub)
    payload, _items = batch_payload(fake_cloud, 101)
    wire.send(batch_topic(DEVICE), payload)
    assert wire.answers[0].payload == b"HTTP 422: invalid batch payload"
    assert stub.batches == []


@pytest.mark.parametrize(
    ("error", "result", "payload"),
    [
        (PublishRejectedError(SUMMARY), "rejected", SUMMARY.encode()),
        (PublishAuthError("HTTP 401"), "auth", b""),
        (PublishTransientError("HTTP 503"), "transient", b""),
        (RuntimeError("boom"), "transient", b""),
    ],
)
def test_publisher_errors_map_to_results(
    fake_cloud: types.ModuleType, error: Exception, result: str, payload: bytes
) -> None:
    wire = Wire(StubPublisher(outcome=error))
    body, _items = batch_payload(fake_cloud)
    wire.send(batch_topic(DEVICE), body)
    (answer,) = wire.answers
    assert answer.user_property("result") == result
    assert answer.payload == payload


@pytest.mark.parametrize(
    ("healthy", "result"),
    [(True, "ok"), (False, "transient"), (RuntimeError("x"), "transient")],
)
def test_health(healthy: Any, result: str) -> None:
    wire = Wire(StubPublisher(healthy=healthy))
    wire.send(health_topic(DEVICE))
    (answer,) = wire.answers
    assert answer.user_properties == (("result", result),)
    assert answer.payload == b""


@pytest.mark.parametrize(
    "props",
    [
        {"response_topic": None},
        {"correlation_data": None},
        {"correlation_data": b""},
        {"response_topic": ""},
    ],
    ids=["no-response-topic", "no-correlation", "empty-correlation", "empty-response-topic"],
)
def test_request_without_properties_is_ignored(
    fake_cloud: types.ModuleType, caplog: pytest.LogCaptureFixture, props: dict[str, Any]
) -> None:
    stub = StubPublisher()
    wire = Wire(stub)
    body, _items = batch_payload(fake_cloud)
    with caplog.at_level(logging.WARNING):
        wire.send(batch_topic(DEVICE), body, **props)
    assert wire.answers == []
    assert stub.batches == []
    assert "ignored" in caplog.text


@pytest.mark.parametrize(
    "response_topic",
    [
        "partqc/v1/edge-01/batch",
        "partqc/v1/edge-02/reply/abc",
        "partqc/v1/edge-01/reply/",
        "partqc/v1/edge-01/reply/a/b",
        "elsewhere",
    ],
)
def test_response_topic_outside_the_reply_topics_is_ignored(
    fake_cloud: types.ModuleType, response_topic: str
) -> None:
    stub = StubPublisher()
    wire = Wire(stub)
    body, _items = batch_payload(fake_cloud)
    wire.send(batch_topic(DEVICE), body, response_topic=response_topic)
    assert stub.batches == []
    assert [m.topic for m in wire.broker.published] == [batch_topic(DEVICE)]


def test_message_on_another_topic_is_ignored() -> None:
    stub = StubPublisher()
    bridge = MqttBridge(InMemoryBroker().client(), stub, DEVICE)
    bridge.handle(MqttMessage("partqc/v1/edge-02/batch", b"{}", REPLY, b"\x01"))
    assert stub.batches == []


def test_answer_that_cannot_be_published_is_logged(
    fake_cloud: types.ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    broker = InMemoryBroker()
    transport = broker.client()
    bridge = MqttBridge(transport, StubPublisher(), DEVICE)
    body, _items = batch_payload(fake_cloud)
    with caplog.at_level(logging.WARNING):
        bridge.handle(MqttMessage(batch_topic(DEVICE), body, REPLY, b"\x01"))  # not connected
    assert "answer on partqc/v1/edge-01/batch not published" in caplog.text


def test_logs_have_only_counts_result_and_topic(
    fake_cloud: types.ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    detail = "HTTP 422: Value cannot be stored"
    wire = Wire(StubPublisher(outcome=PublishRejectedError(detail)))
    body, items = batch_payload(fake_cloud, 2)
    with caplog.at_level(logging.DEBUG):
        wire.send(batch_topic(DEVICE), body)
    assert "batch of 2 item(s) on partqc/v1/edge-01/batch: rejected" in caplog.text
    assert detail not in caplog.text
    for item in items:
        assert str(item.inspection_id) not in caplog.text
    assert body.decode() not in caplog.text


def test_start_with_broker_down_raises_but_keeps_the_subscriptions() -> None:
    broker = InMemoryBroker()
    broker.stop()
    bridge = MqttBridge(broker.client("bridge"), StubPublisher(), DEVICE)
    with pytest.raises(MqttTransportError):
        bridge.start()
    assert len(broker._subscriptions) == 2


# -- the whole path: PublishLoop -> MqttPublisher -> broker -> bridge -> HttpPublisher -> API ----


class Path_:
    def __init__(self, tmp_path: Path, fc: types.ModuleType, timeout_s: float = 15.0) -> None:
        self.fc = fc
        self.clock = fc.FakeClock()
        self.cloud = fc.FakeCloud()
        self.key = device_key()
        self.http = HttpPublisher(fc.BASE_URL, self.key, transport=self.cloud.transport)
        self.broker = InMemoryBroker()
        self.bridge = MqttBridge(self.broker.client("bridge"), self.http, DEVICE)
        self.bridge.start()
        self.state = ConnectivityState()
        self.path = tmp_path / "outbox.sqlite3"
        self.outbox = SqliteOutbox(self.path, clock=self.clock, connectivity=self.state)
        self.edge = self.broker.client("edge")
        self.publisher = MqttPublisher(self.edge, DEVICE, timeout_s)
        self.loop = PublishLoop(
            self.outbox, self.publisher, self.state, clock=self.clock, rng=random.Random(0)
        )

    def put(self, n: int) -> list[InspectionCreate]:
        items = [self.fc.make_inspection() for _ in range(n)]
        for item in items:
            self.outbox.put(item)
        return items

    def statuses(self) -> dict[UUID, tuple[str, int, str | None]]:
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute("SELECT inspection_id, status, attempts, last_error FROM outbox")
            return {UUID(r[0]): (r[1], r[2], r[3]) for r in rows}
        finally:
            conn.close()

    def run_until_empty(self, step_s: float = 2.0, max_cycles: int = 500) -> None:
        for _ in range(max_cycles):
            if self.outbox.stats().pending == 0:
                return
            self.loop.run_once()
            self.clock.advance(step_s)
        raise AssertionError("outbox not empty")

    def close(self) -> None:
        self.http.close()
        self.outbox.close()


@pytest.fixture
def path(tmp_path: Path, fake_cloud: types.ModuleType) -> Iterator[Path_]:
    env = Path_(tmp_path, fake_cloud)
    yield env
    env.close()


def test_end_to_end_delivery(path: Path_) -> None:
    items = path.put(20)
    path.run_until_empty()
    assert sorted(path.cloud.writes) == sorted(i.inspection_id for i in items)
    assert len(path.cloud.writes) == 20
    assert {s for s, _a, _e in path.statuses().values()} == {"sent"}
    assert path.state.connectivity == "online"
    for message in path.broker.published_on(batch_topic(DEVICE)):
        assert message.response_topic == path.publisher.reply_topic


def test_lost_answer_is_resent_and_deduplicated(
    tmp_path: Path, fake_cloud: types.ModuleType
) -> None:
    path = Path_(tmp_path, fake_cloud, timeout_s=0.05)
    dropped: list[MqttMessage] = []

    def drop_first_answer(message: MqttMessage) -> bool:
        if message.topic == path.publisher.reply_topic and not dropped:
            dropped.append(message)
            return False
        return True

    path.broker.intercept = drop_first_answer
    items = path.put(5)
    path.run_until_empty()
    assert len(dropped) == 1
    assert len(path.cloud.writes) == 5
    assert len(path.cloud.batch_requests) == 2
    second = json.loads(path.cloud.batch_requests[1].content)["items"]
    assert {UUID(i["inspection_id"]) for i in second} == {i.inspection_id for i in items}
    assert {s for s, _a, _e in path.statuses().values()} == {"sent"}
    path.close()


def test_broker_down_then_back(path: Path_) -> None:
    path.broker.stop()
    first = path.put(50)
    for _ in range(30):
        path.loop.run_once()
        path.clock.advance(4)
    assert path.cloud.requests == []
    assert all(s == "pending" for s, _a, _e in path.statuses().values())
    path.broker.start()
    second = path.put(50)
    path.run_until_empty()
    expected = {i.inspection_id for i in first + second}
    assert set(path.cloud.writes) == expected
    assert len(path.cloud.writes) == len(expected)
    assert {s for s, _a, _e in path.statuses().values()} == {"sent"}


def test_without_bridge_nothing_is_sent(tmp_path: Path, fake_cloud: types.ModuleType) -> None:
    env = Path_(tmp_path, fake_cloud, timeout_s=0.2)
    try:
        env.bridge.stop()
        env.put(3)
        env.loop.run_once()
        assert env.edge.pubacks == 1  # the broker acknowledged the batch
        assert {(s, a) for s, a, _e in env.statuses().values()} == {("pending", 1)}
        assert env.cloud.requests == []
    finally:
        env.close()


def test_rejected_item_becomes_dead_by_bisection(
    path: Path_, caplog: pytest.LogCaptureFixture
) -> None:
    items = path.put(4)
    bad = str(items[2].inspection_id)
    echoed = "echoed-input-" + secrets.token_hex(4)

    def fail(request: httpx.Request, batch: list[dict[str, Any]]) -> httpx.Response | None:
        if any(i["inspection_id"] == bad for i in batch):
            return httpx.Response(422, json={"detail": "Value cannot be stored", "input": echoed})
        return None

    path.cloud.fail = fail
    with caplog.at_level(logging.DEBUG):
        path.run_until_empty()
    statuses = path.statuses()
    assert statuses[items[2].inspection_id][0] == "dead"
    assert statuses[items[2].inspection_id][2] == "HTTP 422: Value cannot be stored"
    assert sorted(s for s, _a, _e in statuses.values()) == ["dead", "sent", "sent", "sent"]
    for answer in path.broker.published_on("partqc/v1/edge-01/reply/#"):
        assert echoed.encode() not in answer.payload
    assert echoed not in caplog.text


def test_auth_error_pauses_the_loop(path: Path_) -> None:
    path.cloud.fail = lambda request, batch: httpx.Response(401, json={"detail": "x"})
    path.put(2)
    path.loop.run_once()
    assert path.state.connectivity == "auth_error"
    published = len(path.broker.published)
    path.clock.advance(120)
    path.loop.run_once()
    assert len(path.broker.published) == published
    assert {(s, a) for s, a, _e in path.statuses().values()} == {("pending", 0)}


def test_health_through_the_bridge(path: Path_) -> None:
    assert path.publisher.check_health() is True
    assert len(path.cloud.health_requests) == 1
    path.cloud.health_status = 503
    assert path.publisher.check_health() is False


def test_no_secret_nor_payload_in_the_logs(path: Path_, caplog: pytest.LogCaptureFixture) -> None:
    items = path.put(3)
    with caplog.at_level(logging.DEBUG):
        path.run_until_empty()
    assert path.key not in caplog.text
    for item in items:
        assert str(item.inspection_id) not in caplog.text
    assert "L-001" not in caplog.text  # the lot of every inspection of the fake cloud


# -- python -m qc_edge.mqtt_bridge -------------------------------------------------------------

BRIDGE_VARS = (
    "DEVICE_ID",
    "DEVICE_API_KEY",
    "CLOUD_API_URL",
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
)


@pytest.fixture
def bridge_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    for name in BRIDGE_VARS:
        monkeypatch.delenv(name, raising=False)
    values = {
        "DEVICE_API_KEY": device_key(),
        "CLOUD_API_URL": "http://127.0.0.1:9",
        "MQTT_USERNAME": "partqc-edge",
        "MQTT_PASSWORD": "pw-" + secrets.token_urlsafe(12),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def _memory_factory(broker: InMemoryBroker, seen: list[BridgeSettings]) -> Any:
    def factory(settings: BridgeSettings) -> Any:
        seen.append(settings)
        return broker.client("bridge")

    return factory


def test_main_runs_until_the_stop_event(
    bridge_env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    broker = InMemoryBroker()
    seen: list[BridgeSettings] = []
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    with caplog.at_level(logging.DEBUG):
        code = mqtt_bridge.main(
            [], transport_factory=_memory_factory(broker, seen), stop_event=stop
        )
    assert code == 0
    (settings,) = seen
    assert settings.MQTT_HOST == "127.0.0.1" and settings.MQTT_PORT == 1883
    assert broker._subscriptions == []  # disconnected on the way out
    assert bridge_env["MQTT_PASSWORD"] not in caplog.text
    assert bridge_env["DEVICE_API_KEY"] not in caplog.text


def test_main_with_broker_down_keeps_running(
    bridge_env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    broker = InMemoryBroker()
    broker.stop()
    stop = threading.Event()
    stop.set()
    with caplog.at_level(logging.INFO):
        code = mqtt_bridge.main([], transport_factory=_memory_factory(broker, []), stop_event=stop)
    assert code == 0
    assert "retrying in the background" in caplog.text


def test_main_exits_0_on_sigterm(bridge_env: dict[str, str]) -> None:
    broker = InMemoryBroker()
    before = signal.getsignal(signal.SIGTERM)
    threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGTERM)).start()
    code = mqtt_bridge.main([], transport_factory=_memory_factory(broker, []))
    assert code == 0
    assert signal.getsignal(signal.SIGTERM) == before


@pytest.mark.parametrize(
    ("unset", "override", "named"),
    [
        ("DEVICE_API_KEY", None, "DEVICE_API_KEY"),
        ("CLOUD_API_URL", None, "CLOUD_API_URL"),
        ("MQTT_USERNAME", None, "MQTT_USERNAME"),
        ("MQTT_PASSWORD", None, "MQTT_PASSWORD"),
        (None, ("MQTT_HOST", "192.168.0.10"), "MQTT_HOST"),
        (None, ("MQTT_PORT", "0"), "MQTT_PORT"),
        (None, ("CLOUD_API_URL", "http://api.exemplo.org"), "CLOUD_API_URL"),
        (None, ("DEVICE_API_KEY", "chave com espaço"), "DEVICE_API_KEY"),
        (None, ("DEVICE_ID", "Edge_01"), "DEVICE_ID"),
    ],
)
def test_main_invalid_configuration_exits_2(
    bridge_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    unset: str | None,
    override: tuple[str, str] | None,
    named: str,
) -> None:
    if unset:
        monkeypatch.delenv(unset)
    if override:
        monkeypatch.setenv(*override)
    called: list[BridgeSettings] = []
    with caplog.at_level(logging.INFO):
        code = mqtt_bridge.main([], transport_factory=_memory_factory(InMemoryBroker(), called))
    assert code == 2
    assert called == []
    assert named in caplog.text
    assert bridge_env["MQTT_PASSWORD"] not in caplog.text
    if override:
        assert override[1] not in caplog.text


def test_main_unknown_argument_exits_2(
    bridge_env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        code = mqtt_bridge.main(["--password=hunter-" + "x" * 6])
    assert code == 2
    assert "--password" in caplog.text
    assert "hunter" not in caplog.text


def _module_env(extra: dict[str, str]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in BRIDGE_VARS}
    env.update(extra)
    return env


def test_module_without_device_api_key_exits_2(bridge_env: dict[str, str]) -> None:
    env = _module_env({k: v for k, v in bridge_env.items() if k != "DEVICE_API_KEY"})
    done = subprocess.run(
        [sys.executable, "-m", "qc_edge.mqtt_bridge"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 2
    assert "DEVICE_API_KEY" in done.stderr
    assert bridge_env["MQTT_PASSWORD"] not in done.stderr


def test_module_exits_0_on_sigterm_with_the_broker_down(bridge_env: dict[str, str]) -> None:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = _module_env({**bridge_env, "MQTT_PORT": str(port)})
    process = subprocess.Popen(
        [sys.executable, "-m", "qc_edge.mqtt_bridge"],
        env=env,
        cwd=ROOT,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stderr is not None
        deadline = time.monotonic() + 30
        lines = []
        while time.monotonic() < deadline:
            line = process.stderr.readline()
            lines.append(line)
            if "mqtt bridge running" in line:
                break
        else:
            raise AssertionError("bridge did not start")
        process.send_signal(signal.SIGTERM)
        _out, rest = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == 0
    text = "".join(lines) + rest
    assert "retrying in the background" in text
    assert bridge_env["MQTT_PASSWORD"] not in text
    assert bridge_env["DEVICE_API_KEY"] not in text


# -- real broker (mqtt marker) ---------------------------------------------------------------


def _real(broker: types.SimpleNamespace, **kwargs: Any) -> PahoMqttTransport:
    return PahoMqttTransport(broker.host, broker.port, broker.username, broker.password, **kwargs)


@pytest.mark.mqtt
def test_real_broker_end_to_end(
    tmp_path: Path,
    fake_cloud: types.ModuleType,
    mosquitto_broker: types.SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = Path_(tmp_path, fake_cloud, timeout_s=5)
    env.bridge = MqttBridge(_real(mosquitto_broker), env.http, DEVICE)
    env.bridge.start()
    edge = _real(mosquitto_broker)
    env.publisher = MqttPublisher(edge, DEVICE, 5)
    env.loop = PublishLoop(
        env.outbox, env.publisher, env.state, clock=env.clock, rng=random.Random(0)
    )
    try:
        items = env.put(20)
        with caplog.at_level(logging.DEBUG):
            env.run_until_empty()
        assert sorted(env.cloud.writes) == sorted(i.inspection_id for i in items)
        assert {s for s, _a, _e in env.statuses().values()} == {"sent"}
        assert env.publisher.check_health() is True
        assert mosquitto_broker.password not in caplog.text
        assert env.key not in caplog.text
    finally:
        edge.disconnect()
        env.bridge.stop()
        env.close()


@pytest.mark.mqtt
def test_real_broker_restart_restores_the_subscriptions(
    tmp_path: Path, fake_cloud: types.ModuleType, mosquitto_broker: types.SimpleNamespace
) -> None:
    env = Path_(tmp_path, fake_cloud, timeout_s=3)
    bridge_transport = _real(mosquitto_broker)
    env.bridge = MqttBridge(bridge_transport, env.http, DEVICE)
    env.bridge.start()
    edge = _real(mosquitto_broker, connect_timeout_s=1)
    publisher = MqttPublisher(edge, DEVICE, 3)
    try:
        assert publisher.check_health() is True
        mosquitto_broker.stop()
        assert publisher.check_health() is False
        mosquitto_broker.restart()
        deadline = time.monotonic() + 40  # paho reconnects within its backoff (1 to 30 s)
        while time.monotonic() < deadline and not publisher.check_health():
            time.sleep(0.5)
        assert publisher.check_health() is True
    finally:
        edge.disconnect()
        env.bridge.stop()
        env.close()
