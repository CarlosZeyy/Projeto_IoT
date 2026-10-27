"""Acceptance tests for SPEC-020 (qc-edge: MQTT transport, local Mosquitto and the bridge).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation; only the public names given by the SPEC and the dev report were looked up
(``MqttPublisher``, ``MqttBridge``, ``InMemoryBroker``/``InMemoryTransport``, ``MqttMessage``,
``PahoMqttTransport``, ``qc_edge.mqtt_bridge.main``). One ``test_caNN_*`` per automatable CA, at
least (CA-12 is manual and is recorded in ``reviews/SPEC-020/r1-test-report.md``). Tests named
``test_extra_*`` are exploratory cases around the SPEC (security tag): the broker only on
loopback, credentials required, the bridge answering only on a ``ResponseTopic`` of the form of
section 4.1, malformed or huge payloads, forged answers, the PUBACK never confirming an item, a
single deadline with the broker down, no value or credential in the logs, R-05, R-06 and R-12.

Rules followed (``reviews/checklist.md`` and ``docs/architecture.md`` §10):

* the boundaries replaced are the ones the SPEC names: the cloud API (an ``httpx.MockTransport``
  with the SPEC-004 idempotency, or a local HTTP server on ``127.0.0.1`` where the bridge reads
  ``CLOUD_API_URL`` from the environment), the clock of the ``PublishLoop`` and the broker
  (``InMemoryBroker``, the test utility the SPEC asks for); the outbox is a real SQLite in
  ``tmp_path``;
* every key and password is generated at run time (``secrets``), never a literal;
* the real broker (CA-11, marker ``mqtt``) is started by this file on a free port of
  ``127.0.0.1`` with a random user and password; no public broker and no external network;
* no test runs the test suite in a subprocess: the subprocesses here are ``qc_edge.cli.main``
  and ``python -m qc_edge.mqtt_bridge``, with explicit environments and timeouts.
"""

from __future__ import annotations

import ast
import hashlib
import http.server
import json
import logging
import os
import random
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import ImageFile

import qc_edge.cli
import qc_edge.mqtt_bridge
import qc_edge.netinfo
from qc_contracts import BatchCreate, BatchResult, Grade, InspectionCreate, ObjectType, Source
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.mqtt_bridge import MqttBridge
from qc_edge.mqtt_publisher import MqttPublisher
from qc_edge.mqtt_transport import (
    InMemoryBroker,
    InMemoryTransport,
    MqttMessage,
    MqttTransportError,
    PahoMqttTransport,
)
from qc_edge.outbox import SqliteOutbox
from qc_edge.publish_loop import ConnectivityState, PublishLoop
from qc_edge.publisher import HttpPublisher, PublishTransientError

pytestmark = pytest.mark.acceptance

EDGE_ROOT = Path(__file__).resolve().parents[2]  # edge/
ROOT = EDGE_ROOT.parent  # repository root

DEVICE = "edge-01"
BATCH_TOPIC = f"partqc/v1/{DEVICE}/batch"
HEALTH_TOPIC = f"partqc/v1/{DEVICE}/health"
REPLY_FILTER = f"partqc/v1/{DEVICE}/reply/#"
REPLY_RE = re.compile(rf"^partqc/v1/{DEVICE}/reply/[^/+#]+$")
BATCH_PATH = "/api/v1/inspections/batch"
HEALTH_PATH = "/api/v1/health"
CLOUD_URL = "https://cloud.test"
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
TIMEOUT_S = 1.0  # MQTT_RESPONSE_TIMEOUT_S of the CAs that wait for an answer
MARGIN_S = 0.75  # scheduling slack on top of a deadline
EDGE_PORT = 8000
SESSION_HEADER = "X-Session-Token"
REFUSAL = "HTTP 422: Value cannot be stored"
INVALID_BATCH = "HTTP 422: invalid batch payload"

EDGE_ENV_VARS = (
    "EDGE_HOST",
    "EDGE_PORT",
    "EDGE_SESSION_TOKEN",
    "DEVICE_ID",
    "EDGE_DATA_DIR",
    "DEVICE_API_KEY",
    "CLOUD_API_URL",
    "MODEL_DIR",
    "DATASET_DIR",
    "OUTBOX_PATH",
    "TYPE_THRESHOLD",
    "UNUSABLE_THRESHOLD",
    "GRADE_REVIEW_THRESHOLD",
    "HEARTBEAT_INTERVAL_S",
    "EDGE_PUBLISHER",
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
    "MQTT_RESPONSE_TIMEOUT_S",
)


def new_key() -> str:
    """A device key generated at run time (never a literal)."""
    return "acc_" + secrets.token_urlsafe(24)


def new_password() -> str:
    """An MQTT password generated at run time (never a literal)."""
    return "pw-" + secrets.token_urlsafe(18)


def new_user() -> str:
    return "acc-user-" + secrets.token_hex(4)


# =========================================================================== domain helpers


def inspection(
    *, source: Source = Source.LIVE, lot_id: str = "L-020", device_id: str = DEVICE
) -> InspectionCreate:
    return InspectionCreate(
        inspection_id=uuid.uuid4(),
        device_id=device_id,
        lot_id=lot_id,
        inspected_at=T0,
        object_type=ObjectType.NUT,
        grade=Grade.FAIR,
        grade_score=2.2,
        type_confidence=0.91,
        grade_confidence=0.77,
        needs_review=False,
        model_version="partqc-mnv3-v1",
        model_sha256=hashlib.sha256(b"acceptance-020").hexdigest(),
        latency_ms=37,
        source=source,
    )


def batch_json(items: Sequence[InspectionCreate]) -> bytes:
    return BatchCreate(items=list(items)).model_dump_json().encode()


class ManualClock:
    """The injected clock of the ``PublishLoop`` (always UTC)."""

    def __init__(self, start: datetime = T0) -> None:
        self.now = start
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self.now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.now += timedelta(seconds=seconds)


class FakeCloud:
    """The simulated API of the CA context: idempotent by ``inspection_id`` (SPEC-004).

    A batch that contains a ``reject_ids`` item is refused as a whole with ``reject_body``
    (status 422), like the real API. ``fail`` may return a response that replaces the normal one.
    """

    def __init__(self) -> None:
        self.stored: dict[str, dict[str, Any]] = {}
        self.writes: list[str] = []
        self.requests: list[httpx.Request] = []
        self.batches: list[list[str]] = []
        self.answers: list[list[str]] = []
        self.reject_ids: set[str] = set()
        self.reject_body: dict[str, Any] = {"detail": "Value cannot be stored"}
        self.fail: Callable[[httpx.Request], httpx.Response | None] | None = None
        self.health_status = 200
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            body = request.read()
            self.requests.append(request)
            if self.fail is not None:
                outcome = self.fail(request)
                if outcome is not None:
                    return outcome
            if request.url.path == HEALTH_PATH and request.method == "GET":
                return httpx.Response(self.health_status, json={"status": "ok", "db": "ok"})
            if request.url.path == BATCH_PATH and request.method == "POST":
                items = json.loads(body)["items"]
                ids = [item["inspection_id"] for item in items]
                self.batches.append(ids)
                if any(i in self.reject_ids for i in ids):
                    return httpx.Response(422, json=self.reject_body)
                results = []
                for item in items:
                    iid = item["inspection_id"]
                    if iid in self.stored:
                        results.append({"inspection_id": iid, "status": "duplicate"})
                    else:
                        self.stored[iid] = item
                        self.writes.append(iid)
                        results.append({"inspection_id": iid, "status": "created"})
                self.answers.append([r["status"] for r in results])
                return httpx.Response(200, json={"results": results})
            return httpx.Response(404, json={"detail": "Not Found"})

    def batch_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == BATCH_PATH]

    def health_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == HEALTH_PATH]


class RecordingTransport:
    """Wraps an ``MqttTransport`` and records the QoS of every publish and subscribe."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.published: list[tuple[MqttMessage, int]] = []
        self.subscribed: list[tuple[str, int]] = []

    def connect(self, timeout_s: float | None = None) -> None:
        self.inner.connect(timeout_s)

    def publish(self, message: MqttMessage, qos: int = 1, timeout_s: float | None = None) -> None:
        self.published.append((message, qos))
        self.inner.publish(message, qos, timeout_s)

    def subscribe(self, topic_filter: str, handler: Any, qos: int = 1) -> None:
        self.subscribed.append((topic_filter, qos))
        self.inner.subscribe(topic_filter, handler, qos)

    def disconnect(self) -> None:
        self.inner.disconnect()


@dataclass
class MqttRig:
    """PublishLoop -> MqttPublisher -> InMemoryBroker -> MqttBridge -> HttpPublisher -> API."""

    path: Path
    clock: ManualClock
    connectivity: ConnectivityState
    outbox: SqliteOutbox
    cloud: FakeCloud
    broker: InMemoryBroker
    edge: RecordingTransport
    bridge_transport: RecordingTransport
    http_publisher: HttpPublisher
    bridge: MqttBridge
    publisher: MqttPublisher
    loop: PublishLoop
    key: str
    puts: list[InspectionCreate] = field(default_factory=list)

    def put(self, item: InspectionCreate | None = None) -> InspectionCreate:
        item = item if item is not None else inspection()
        self.outbox.put(item)
        self.puts.append(item)
        return item

    def rows(self) -> list[dict[str, Any]]:
        return read_rows(self.path)

    def drain(self, *, step_s: float = 2.0, max_cycles: int = 400) -> int:
        cycles = 0
        while self.outbox.stats().pending > 0:
            assert cycles < max_cycles, "outbox did not drain"
            self.loop.run_once()
            self.clock.advance(step_s)
            cycles += 1
        return cycles

    def batch_messages(self) -> list[MqttMessage]:
        return self.broker.published_on(BATCH_TOPIC)

    def health_messages(self) -> list[MqttMessage]:
        return self.broker.published_on(HEALTH_TOPIC)

    def replies(self) -> list[MqttMessage]:
        return self.broker.published_on(REPLY_FILTER)


def make_rig(
    tmp_path: Path, *, bridge_on: bool = True, timeout_s: float = TIMEOUT_S, name: str = "o.db"
) -> MqttRig:
    path = tmp_path / name
    clock = ManualClock()
    connectivity = ConnectivityState()
    outbox = SqliteOutbox(path, clock=clock, connectivity=connectivity)
    cloud = FakeCloud()
    key = new_key()
    broker = InMemoryBroker()
    bridge_transport = RecordingTransport(broker.client("acc-bridge"))
    http_publisher = HttpPublisher(CLOUD_URL, key, transport=httpx.MockTransport(cloud))
    bridge = MqttBridge(bridge_transport, http_publisher, DEVICE)
    if bridge_on:
        bridge.start()
    edge = RecordingTransport(broker.client("acc-edge"))
    publisher = MqttPublisher(edge, DEVICE, timeout_s)
    loop = PublishLoop(outbox, publisher, connectivity, clock=clock, rng=random.Random(0))
    return MqttRig(
        path,
        clock,
        connectivity,
        outbox,
        cloud,
        broker,
        edge,
        bridge_transport,
        http_publisher,
        bridge,
        publisher,
        loop,
        key,
    )


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[MqttRig]:
    r = make_rig(tmp_path)
    try:
        yield r
    finally:
        r.outbox.close()


@pytest.fixture
def rig_no_bridge(tmp_path: Path) -> Iterator[MqttRig]:
    r = make_rig(tmp_path, bridge_on=False)
    try:
        yield r
    finally:
        r.outbox.close()


def read_rows(path: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(path)
    try:
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM outbox ORDER BY created_at, rowid")
        return [dict(row) for row in cur.fetchall()]
    finally:
        con.close()


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Every visible part of every record: message, raw msg, args and formatted exception."""
    formatter = logging.Formatter()
    parts = [caplog.text]
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(str(record.msg))
        parts.append(repr(record.args))
        if record.exc_info:
            parts.append(formatter.formatException(record.exc_info))
        if record.exc_text:
            parts.append(record.exc_text)
    return "\n".join(parts)


def request(
    topic: str,
    payload: bytes,
    *,
    response_topic: str | None = None,
    correlation: bytes | None = None,
) -> MqttMessage:
    return MqttMessage(
        topic=topic,
        payload=payload,
        response_topic=response_topic,
        correlation_data=correlation,
    )


def reply_to(rig: MqttRig) -> str:
    return f"partqc/v1/{DEVICE}/reply/acc{secrets.token_hex(4)}"


# =========================================================================== CA-01


def test_ca01_twenty_items_delivered_once_through_mqtt(rig: MqttRig) -> None:
    items = [rig.put() for _ in range(20)]
    rig.drain()

    ids = [str(i.inspection_id) for i in items]
    assert sorted(rig.cloud.writes) == sorted(ids)  # the 20, once each
    assert len(rig.cloud.writes) == len(set(rig.cloud.writes)) == 20
    rows = rig.rows()
    assert len(rows) == 20
    assert all(r["status"] == "sent" for r in rows)
    assert rig.outbox.stats().pending == 0 and rig.outbox.stats().dead == 0

    messages = rig.batch_messages()
    assert messages, "nothing was published on partqc/v1/<device_id>/batch"
    seen: list[str] = []
    for message in messages:
        batch = BatchCreate.model_validate_json(message.payload)  # validates as BatchCreate
        assert 1 <= len(batch.items) <= 100
        seen.extend(str(i.inspection_id) for i in batch.items)
    assert sorted(set(seen)) == sorted(ids)


def test_ca01_edge_publisher_mqtt_puts_the_mqtt_publisher_in_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``EDGE_PUBLISHER=mqtt`` (with key, URL and MQTT credentials) builds the ``PublishLoop``
    with an ``MqttPublisher`` (section 4.5), not with the ``HttpPublisher``."""
    caplog.set_level(logging.DEBUG)
    env = edge_environment(tmp_path, monkeypatch)
    password = new_password()
    key = new_key()
    monkeypatch.setenv("EDGE_PUBLISHER", "mqtt")
    monkeypatch.setenv("MQTT_USERNAME", new_user())
    monkeypatch.setenv("MQTT_PASSWORD", password)
    monkeypatch.setenv("DEVICE_API_KEY", key)
    monkeypatch.setenv("CLOUD_API_URL", CLOUD_URL)
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", "0")
    built = loop_spy(monkeypatch)
    runs: list[Any] = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: runs.append((a, k)))

    assert call_main([]) == 0
    assert runs, "the server was not started"
    assert len(built) == 1
    publishers = [v for v in vars(built[0]).values() if isinstance(v, MqttPublisher)]
    assert publishers, "the PublishLoop was not built with an MqttPublisher"
    assert not [v for v in vars(built[0]).values() if isinstance(v, HttpPublisher)]
    text = log_text(caplog)
    assert password not in text and key not in text
    assert env.token not in text


# =========================================================================== CA-02


def test_ca02_lost_answer_resent_and_deduplicated(rig: MqttRig) -> None:
    dropped: list[MqttMessage] = []

    def drop_first_answer(message: MqttMessage) -> bool:
        if REPLY_RE.match(message.topic) and not dropped:
            dropped.append(message)
            return False  # the bridge already called the API; its answer is lost
        return True

    rig.broker.intercept = drop_first_answer
    items = [rig.put() for _ in range(5)]
    rig.drain()

    assert len(dropped) == 1
    ids = sorted(str(i.inspection_id) for i in items)
    assert sorted(rig.cloud.stored) == ids
    assert sorted(rig.cloud.writes) == ids  # once each
    assert len(rig.cloud.batch_requests()) == 2  # the batch reached the API twice
    assert rig.cloud.batches[0] == rig.cloud.batches[1]
    assert rig.cloud.answers[1] == ["duplicate"] * 5
    assert all(r["status"] == "sent" for r in rig.rows())


# =========================================================================== CA-03


def test_ca03_broker_down_two_minutes_200_items_no_loss_no_duplicate(rig: MqttRig) -> None:
    # 40 before the fall, 120 while the broker is stopped (120 s of the injected clock), 40 after.
    for _ in range(20):
        rig.put()
        rig.put()
        rig.loop.run_once()
        rig.clock.advance(1)
    delivered_before = len(rig.cloud.writes)
    assert delivered_before > 0

    rig.broker.stop()
    stopped_at = rig.clock()
    batches_at_stop = len(rig.cloud.batch_requests())
    for _ in range(120):
        rig.put()
        rig.loop.run_once()
        rig.clock.advance(1)
    assert rig.clock() - stopped_at == timedelta(minutes=2)
    assert len(rig.cloud.batch_requests()) == batches_at_stop  # nothing passed the stopped broker
    assert rig.outbox.stats().pending >= 120

    rig.broker.start()
    for _ in range(20):
        rig.put()
        rig.put()
        rig.loop.run_once()
        rig.clock.advance(1)
    rig.drain()

    assert len(rig.puts) == 200
    ids = {str(i.inspection_id) for i in rig.puts}
    assert len(ids) == 200
    assert set(rig.cloud.stored) == ids  # 200 distinct inspection_id
    assert len(rig.cloud.writes) == 200  # none stored twice
    statuses = [r["status"] for r in rig.rows()]
    assert len(statuses) == 200
    assert "pending" not in statuses and "dead" not in statuses


# =========================================================================== CA-04


def test_ca04_without_bridge_puback_but_rows_stay_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MQTT_RESPONSE_TIMEOUT_S", "1")
    timeout = EdgeSettings(DATASET_DIR=tmp_path / "ds").MQTT_RESPONSE_TIMEOUT_S
    assert timeout == 1.0
    r = make_rig(tmp_path, bridge_on=False, timeout_s=timeout)
    try:
        for _ in range(3):
            r.put()
        started = time.monotonic()
        r.loop.run_once()
        elapsed = time.monotonic() - started

        assert len(r.batch_messages()) == 1  # the broker acknowledged the publication...
        assert r.edge.inner.pubacks >= 1  # ... with a PUBACK (QoS 1)
        assert [qos for m, qos in r.edge.published if m.topic == BATCH_TOPIC] == [1]
        rows = r.rows()
        assert len(rows) == 3
        assert all(row["status"] == "pending" for row in rows)  # ... and nothing is sent
        assert all(row["attempts"] == 1 for row in rows)  # retry of SPEC-009
        assert all(row["sent_at"] is None for row in rows)
        assert r.cloud.requests == []
        assert elapsed <= timeout + MARGIN_S, elapsed
    finally:
        r.outbox.close()


# =========================================================================== CA-05


def test_ca05_refused_item_dead_with_summary_others_sent(rig: MqttRig) -> None:
    items = [rig.put() for _ in range(4)]
    bad = str(items[2].inspection_id)
    rig.cloud.reject_ids = {bad}
    rig.drain()

    rows = {r["inspection_id"]: r for r in rig.rows()}
    assert rows[bad]["status"] == "dead"
    assert rows[bad]["last_error"] == REFUSAL
    others = [str(i.inspection_id) for i in items if str(i.inspection_id) != bad]
    assert all(rows[i]["status"] == "sent" for i in others)
    assert sorted(rig.cloud.stored) == sorted(others)

    body = json.dumps(rig.cloud.reject_body).encode()
    rejected = [m for m in rig.replies() if m.user_property("result") == "rejected"]
    assert rejected, "the bridge never answered rejected"
    for message in rig.replies():
        assert body not in message.payload
        assert b'"detail"' not in message.payload
    for message in rejected:
        assert message.payload.decode("utf-8") == REFUSAL


def test_ca05_body_fields_beyond_the_summary_never_reach_the_answer(rig: MqttRig) -> None:
    marker = "echo-" + secrets.token_hex(10)
    rig.cloud.reject_body = {"detail": "Value cannot be stored", "input": marker, "ctx": [marker]}
    items = [rig.put() for _ in range(4)]
    bad = str(items[0].inspection_id)
    rig.cloud.reject_ids = {bad}
    rig.drain()
    assert {r["inspection_id"]: r for r in rig.rows()}[bad]["last_error"] == REFUSAL
    for message in rig.replies():
        assert marker.encode() not in message.payload


# =========================================================================== CA-06


@pytest.mark.parametrize("status", [401, 403])
def test_ca06_auth_error_pauses_publishing(rig: MqttRig, status: int) -> None:
    rig.cloud.fail = lambda request: httpx.Response(status, json={"detail": "Invalid API key"})
    for _ in range(3):
        rig.put()
    rig.loop.run_once()
    assert rig.outbox.stats().connectivity == "auth_error"
    published = len(rig.edge.published)
    api_calls = len(rig.cloud.requests)
    assert published >= 1 and api_calls >= 1

    for _ in range(3):
        rig.clock.advance(30)
        rig.loop.run_once()  # the next cycles publish nothing
    assert len(rig.edge.published) == published
    assert len(rig.cloud.requests) == api_calls
    assert all(row["status"] == "pending" and row["attempts"] == 0 for row in rig.rows())
    assert rig.outbox.stats().connectivity == "auth_error"


# =========================================================================== CA-07


def test_ca07_health_true_with_bridge_false_without_within_timeout(
    rig: MqttRig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rig.cloud.health_status = 200
    assert rig.publisher.check_health() is True
    assert len(rig.cloud.health_requests()) == 1
    health = rig.health_messages()
    assert len(health) == 1 and health[0].payload == b""

    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MQTT_RESPONSE_TIMEOUT_S", "1")
    timeout = EdgeSettings(DATASET_DIR=tmp_path / "ds").MQTT_RESPONSE_TIMEOUT_S
    publisher = MqttPublisher(rig.broker.client("acc-edge-2"), DEVICE, timeout)
    rig.bridge.stop()  # the bridge is off
    started = time.monotonic()
    assert publisher.check_health() is False
    elapsed = time.monotonic() - started
    assert elapsed <= timeout + MARGIN_S, elapsed
    assert len(rig.cloud.health_requests()) == 1


# =========================================================================== CA-08


@dataclass
class Run:
    code: int
    out: str


def run_edge(env: dict[str, str], cwd: Path, *args: str) -> Run:
    code = "import sys, qc_edge.cli; sys.exit(qc_edge.cli.main(sys.argv[1:]))"
    return run_python(["-c", code, *args], env, cwd)


def run_bridge(env: dict[str, str], cwd: Path, *args: str) -> Run:
    return run_python(["-m", "qc_edge.mqtt_bridge", *args], env, cwd)


def run_python(argv: list[str], env: dict[str, str], cwd: Path, timeout: float = 90) -> Run:
    try:
        done = subprocess.run(
            [sys.executable, *argv],
            env=env,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:  # it started instead of refusing the configuration
        pytest.fail(f"process did not exit within {timeout} s: {exc.cmd!r}")
    return Run(done.returncode, done.stdout + done.stderr)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def base_env(tmp_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in EDGE_ENV_VARS}
    env.update(
        {
            "EDGE_PORT": str(free_port()),
            "EDGE_DATA_DIR": str(tmp_path / "edge-data"),
            "DATASET_DIR": str(tmp_path / "dataset"),
            "EDGE_SESSION_TOKEN": secrets.token_urlsafe(30),
            "HEARTBEAT_INTERVAL_S": "0",
        }
    )
    return env


def cwd_for(tmp_path: Path) -> Path:
    work = tmp_path / "cwd"
    work.mkdir(exist_ok=True)  # never the repository (no .env is read from there)
    return work


def mqtt_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = base_env(tmp_path)
    env.update(
        {
            "EDGE_PUBLISHER": "mqtt",
            "MQTT_USERNAME": new_user(),
            "MQTT_PASSWORD": new_password(),
            "DEVICE_API_KEY": new_key(),
            "CLOUD_API_URL": CLOUD_URL,
        }
    )
    env.update(extra)
    return env


def test_ca08_invalid_edge_publisher_exits_2_with_the_message(tmp_path: Path) -> None:
    env = base_env(tmp_path)
    env["EDGE_PUBLISHER"] = "xyz"
    run = run_edge(env, cwd_for(tmp_path))
    assert run.code == 2
    assert "EDGE_PUBLISHER must be http or mqtt" in run.out


def test_ca08_remote_mqtt_host_exits_2(tmp_path: Path) -> None:
    env = mqtt_env(tmp_path, MQTT_HOST="192.168.0.10")
    run = run_edge(env, cwd_for(tmp_path))
    assert run.code == 2
    assert env["MQTT_PASSWORD"] not in run.out and env["DEVICE_API_KEY"] not in run.out


def test_ca08_empty_mqtt_password_exits_2(tmp_path: Path) -> None:
    env = mqtt_env(tmp_path, MQTT_PASSWORD="")
    run = run_edge(env, cwd_for(tmp_path))
    assert run.code == 2
    assert env["DEVICE_API_KEY"] not in run.out


def test_ca08_bridge_without_device_api_key_exits_2(tmp_path: Path) -> None:
    env = mqtt_env(tmp_path)
    del env["DEVICE_API_KEY"]
    run = run_bridge(env, cwd_for(tmp_path))
    assert run.code == 2
    assert env["MQTT_PASSWORD"] not in run.out


# =========================================================================== CA-09


class CloudServer(http.server.ThreadingHTTPServer):
    """Local API on 127.0.0.1 (``CLOUD_API_URL`` of the bridge ``main``), SPEC-004 idempotency."""

    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), CloudHandler)
        self.lock = threading.Lock()
        self.stored: dict[str, dict[str, Any]] = {}
        self.reject_ids: set[str] = set()
        self.reject_body: dict[str, Any] = {"detail": "Value cannot be stored"}
        self.auth_status: int | None = None
        self.keys: list[str] = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def answer(self, method: str, path: str, key: str, body: bytes) -> tuple[int, Any]:
        with self.lock:
            self.keys.append(key)
            if self.auth_status is not None:
                return self.auth_status, {"detail": "Invalid API key"}
            if method == "GET" and path == HEALTH_PATH:
                return 200, {"status": "ok", "db": "ok"}
            if method == "POST" and path == BATCH_PATH:
                items = json.loads(body)["items"]
                if any(item["inspection_id"] in self.reject_ids for item in items):
                    return 422, self.reject_body
                results = []
                for item in items:
                    iid = item["inspection_id"]
                    status = "duplicate" if iid in self.stored else "created"
                    self.stored.setdefault(iid, item)
                    results.append({"inspection_id": iid, "status": status})
                return 200, {"results": results}
            return 404, {"detail": "Not Found"}


class CloudHandler(http.server.BaseHTTPRequestHandler):
    server: CloudServer

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        key = self.headers.get("X-API-Key", "")
        status, payload = self.server.answer(self.command, self.path, key, body)
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = _handle
    do_POST = _handle

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return


@pytest.fixture
def cloud_server() -> Iterator[CloudServer]:
    server = CloudServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def test_ca09_no_password_key_or_batch_payload_in_the_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
    cloud_server: CloudServer,
) -> None:
    """CA-01, CA-05 and CA-06 with the bridge ``main`` (environment with ``MQTT_PASSWORD`` and
    ``DEVICE_API_KEY``, local API on 127.0.0.1) and the edge started with
    ``EDGE_PUBLISHER=mqtt``; the logs and the stderr of both carry none of them."""
    caplog.set_level(logging.DEBUG)
    password = new_password()
    key = new_key()
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(cwd_for(tmp_path))
    monkeypatch.setenv("DEVICE_ID", DEVICE)
    monkeypatch.setenv("DEVICE_API_KEY", key)
    monkeypatch.setenv("CLOUD_API_URL", cloud_server.url)
    monkeypatch.setenv("MQTT_USERNAME", new_user())
    monkeypatch.setenv("MQTT_PASSWORD", password)

    broker = InMemoryBroker()
    factory_settings: list[Any] = []

    def factory(settings: Any) -> InMemoryTransport:
        factory_settings.append(settings)
        return broker.client("acc-bridge-main")

    stop = threading.Event()
    codes: list[int] = []
    thread = threading.Thread(
        target=lambda: codes.append(
            qc_edge.mqtt_bridge.main([], transport_factory=factory, stop_event=stop)
        ),
        daemon=True,
    )
    thread.start()
    payloads: list[bytes] = []
    try:
        publisher = MqttPublisher(broker.client("acc-edge-main"), DEVICE, TIMEOUT_S)
        deadline = time.monotonic() + 20
        while not publisher.check_health():
            assert time.monotonic() < deadline, "the bridge main never answered"
        clock = ManualClock()
        connectivity = ConnectivityState()
        outbox = SqliteOutbox(tmp_path / "ca09.db", clock=clock, connectivity=connectivity)
        loop = PublishLoop(outbox, publisher, connectivity, clock=clock, rng=random.Random(1))
        try:
            # CA-01: delivery
            items = [inspection() for _ in range(20)]
            for item in items:
                outbox.put(item)
            # CA-05: one refused item (with an echo field in the body)
            refused = [inspection() for _ in range(4)]
            marker = "echo-" + secrets.token_hex(8)
            cloud_server.reject_body = {"detail": "Value cannot be stored", "input": marker}
            cloud_server.reject_ids = {str(refused[1].inspection_id)}
            for item in refused:
                outbox.put(item)
            cycles = 0
            while outbox.stats().pending > 0:
                assert cycles < 200
                loop.run_once()
                clock.advance(2)
                cycles += 1
            assert len(cloud_server.stored) == 23
            # CA-06: authentication
            cloud_server.auth_status = 401
            outbox.put(inspection())
            loop.run_once()
            assert outbox.stats().connectivity == "auth_error"
            payloads = [m.payload for m in broker.published_on(BATCH_TOPIC)]
        finally:
            outbox.close()
    finally:
        stop.set()
        thread.join(15)
    assert codes == [0]
    assert factory_settings, "the bridge main did not build its transport"
    assert key in cloud_server.keys  # the key really was in use

    # the edge started with EDGE_PUBLISHER=mqtt and the same secrets (uvicorn spied)
    monkeypatch.setenv("EDGE_PUBLISHER", "mqtt")
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "edge-data"))
    monkeypatch.setenv("DATASET_DIR", str(tmp_path / "dataset"))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", secrets.token_urlsafe(30))
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", "0")
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    monkeypatch.setattr(qc_edge.netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
    assert call_main([]) == 0

    text = log_text(caplog) + "\n" + "\n".join(capfd.readouterr())
    assert password not in text
    assert key not in text
    assert marker not in text
    assert payloads
    for payload in payloads:
        assert payload.decode() not in text
    # the ids alone may appear (SPEC-009 logs the dead item); no part of a payload may
    assert '"inspection_id"' not in text
    assert hashlib.sha256(b"acceptance-020").hexdigest() not in text
    assert all(item.model_dump_json() not in text for item in [*items, *refused])


# =========================================================================== CA-10


def _imports(path: Path) -> set[str]:
    """Top-level names imported by ``path`` (``import x.y``, ``from x import``, and
    ``importlib.import_module("x")``/``__import__("x")`` with a literal)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            first = node.args[0]
            if (
                fname in ("import_module", "__import__")
                and isinstance(first, ast.Constant)
                and isinstance(first.value, str)
            ):
                names.add(first.value.split(".")[0])
    return names


def _production_files() -> list[Path]:
    roots = [
        ROOT / "edge" / "src",
        ROOT / "api" / "src",
        ROOT / "dashboard",
        ROOT / "packages",
        ROOT / "ml" / "src",
        ROOT / "scripts",
    ]
    files: list[Path] = []
    for base in roots:
        if base.exists():
            files.extend(
                p
                for p in base.rglob("*.py")
                if "tests" not in p.relative_to(ROOT).parts and ".venv" not in p.parts
            )
    return files


def _lock_closure(root: str) -> set[str]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    packages = {p["name"]: p for p in lock["package"]}
    seen: set[str] = set()
    todo = [root]
    while todo:
        name = todo.pop()
        if name in seen or name not in packages:
            continue
        seen.add(name)
        pkg = packages[name]
        deps = list(pkg.get("dependencies", []))
        for group in ("optional-dependencies", "dev-dependencies"):
            for extra in pkg.get(group, {}).values():
                deps.extend(extra)
        todo.extend(d["name"] for d in deps)
    return seen


def test_ca10_paho_only_in_the_transport_httpx_only_in_the_publisher() -> None:
    edge_src = ROOT / "edge" / "src" / "qc_edge"
    paho_users = sorted(
        str(p.relative_to(ROOT)) for p in _production_files() if "paho" in _imports(p)
    )
    assert paho_users == ["edge/src/qc_edge/mqtt_transport.py"]
    httpx_users = sorted(
        str(p.relative_to(edge_src)) for p in edge_src.rglob("*.py") if "httpx" in _imports(p)
    )
    assert httpx_users == ["publisher.py"]

    assert "paho-mqtt" in _lock_closure("qc-edge")  # the check below is not vacuous
    assert "paho-mqtt" not in _lock_closure("qc-api")
    assert "paho-mqtt" not in _lock_closure("qc-dashboard")


# =========================================================================== CA-11 (mqtt)


@dataclass
class RealBroker:
    process: subprocess.Popen[bytes]
    host: str
    port: int
    username: str
    password: str


def _wait_port(process: subprocess.Popen[bytes], port: int, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"mosquitto exited with {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("mosquitto did not listen in time")


@pytest.fixture
def real_broker(tmp_path: Path) -> Iterator[RealBroker]:
    """A Mosquitto started by the test on a free port of 127.0.0.1, user and password only."""
    if os.environ.get("PARTQC_MQTT_TESTS") != "1":
        pytest.skip("set PARTQC_MQTT_TESTS=1 (and install mosquitto) to run")
    if shutil.which("mosquitto") is None or shutil.which("mosquitto_passwd") is None:
        pytest.skip("mosquitto and mosquitto_passwd must be on the PATH")
    directory = tmp_path / "broker"
    directory.mkdir(mode=0o700)
    username, password = new_user(), new_password()
    passwd = directory / "passwd"
    subprocess.run(
        ["mosquitto_passwd", "-b", "-c", str(passwd), username, password],
        check=True,
        capture_output=True,
        timeout=60,
    )
    passwd.chmod(0o600)
    port = free_port()
    config = directory / "acc.conf"
    config.write_text(
        f"listener {port} 127.0.0.1\nallow_anonymous false\npassword_file {passwd}\n"
        "persistence false\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        ["mosquitto", "-c", str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        _wait_port(process, port)
        yield RealBroker(process, "127.0.0.1", port, username, password)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(20)


@pytest.mark.mqtt
def test_ca11_real_broker_repeats_ca01_and_refuses_no_password(
    tmp_path: Path, real_broker: RealBroker
) -> None:
    b = real_broker
    edge_t = PahoMqttTransport(b.host, b.port, b.username, b.password, client_id="acc-edge")
    bridge_t = PahoMqttTransport(b.host, b.port, b.username, b.password, client_id="acc-bridge")
    monitor_t = PahoMqttTransport(b.host, b.port, b.username, b.password, client_id="acc-mon")
    cloud = FakeCloud()
    http_publisher = HttpPublisher(CLOUD_URL, new_key(), transport=httpx.MockTransport(cloud))
    bridge = MqttBridge(bridge_t, http_publisher, DEVICE)
    publisher = MqttPublisher(edge_t, DEVICE, 5.0)
    seen: list[bytes] = []
    lock = threading.Lock()

    def monitor(message: MqttMessage) -> None:
        with lock:
            seen.append(message.payload)

    clock = ManualClock()
    connectivity = ConnectivityState()
    path = tmp_path / "real.db"
    outbox = SqliteOutbox(path, clock=clock, connectivity=connectivity)
    try:
        monitor_t.subscribe(BATCH_TOPIC, monitor, 1)
        monitor_t.connect(10)
        bridge.start()
        deadline = time.monotonic() + 30
        while not publisher.check_health():
            assert time.monotonic() < deadline, "the bridge never answered through the broker"
        loop = PublishLoop(outbox, publisher, connectivity, clock=clock, rng=random.Random(0))
        items = [inspection() for _ in range(20)]
        for item in items:
            outbox.put(item)
        cycles = 0
        while outbox.stats().pending > 0:
            assert cycles < 200, "outbox did not drain"
            loop.run_once()
            clock.advance(2)
            cycles += 1

        ids = sorted(str(i.inspection_id) for i in items)
        assert sorted(cloud.writes) == ids  # the 20, once each
        rows = read_rows(path)
        assert len(rows) == 20 and all(r["status"] == "sent" for r in rows)
        deadline = time.monotonic() + 5
        while True:
            with lock:
                got = list(seen)
            if sorted({str(i.inspection_id) for p in got for i in batch_ids(p)}) == ids:
                break
            assert time.monotonic() < deadline, "the monitor did not see every batch"
            time.sleep(0.05)
        for payload in got:
            BatchCreate.model_validate_json(payload)
    finally:
        outbox.close()
        publisher.close()
        bridge.stop()
        monitor_t.disconnect()

    for username, password in ((None, None), (b.username, None), (b.username, new_password())):
        anonymous = PahoMqttTransport(b.host, b.port, username, password, client_id="acc-anon")
        try:
            with pytest.raises(MqttTransportError):
                anonymous.connect(5)
        finally:
            anonymous.disconnect()


def batch_ids(payload: bytes) -> list[InspectionCreate]:
    return list(BatchCreate.model_validate_json(payload).items)


@pytest.mark.mqtt
def test_extra_real_broker_nothing_retained(tmp_path: Path, real_broker: RealBroker) -> None:
    """After a round trip, a new subscriber to ``partqc/#`` gets no retained message: the batch
    and the answers are never published with ``retain``."""
    b = real_broker
    edge_t = PahoMqttTransport(b.host, b.port, b.username, b.password, client_id="acc-edge-r")
    bridge_t = PahoMqttTransport(b.host, b.port, b.username, b.password, client_id="acc-br-r")
    cloud = FakeCloud()
    bridge = MqttBridge(
        bridge_t, HttpPublisher(CLOUD_URL, new_key(), transport=httpx.MockTransport(cloud)), DEVICE
    )
    publisher = MqttPublisher(edge_t, DEVICE, 5.0)
    try:
        bridge.start()
        deadline = time.monotonic() + 30
        while not publisher.check_health():
            assert time.monotonic() < deadline
        results = publisher.publish_batch([inspection(), inspection()])
        assert len(results) == 2
    finally:
        publisher.close()
        bridge.stop()
    late = PahoMqttTransport(b.host, b.port, b.username, b.password, client_id="acc-late")
    probe = PahoMqttTransport(b.host, b.port, b.username, b.password, client_id="acc-probe")
    got: list[str] = []
    probe_topic = f"partqc/v1/{DEVICE}/probe"
    try:
        late.subscribe("partqc/#", lambda m: got.append(m.topic), 1)
        late.connect(10)
        time.sleep(1.0)
        retained = list(got)
        probe.connect(10)
        probe.publish(MqttMessage(topic=probe_topic, payload=b"p"), 1, 5)
        deadline = time.monotonic() + 5
        while probe_topic not in got:  # positive control: the late subscriber really listens
            assert time.monotonic() < deadline, "the late subscriber received nothing"
            time.sleep(0.05)
    finally:
        probe.disconnect()
        late.disconnect()
    assert retained == []


# =========================================================================== exploratory: §4.1


def test_extra_request_properties_follow_section_4_1(rig: MqttRig) -> None:
    rig.put()
    rig.put()
    rig.loop.run_once()
    assert rig.publisher.check_health() is True
    other = MqttPublisher(rig.broker.client("acc-edge-b"), DEVICE, TIMEOUT_S)
    assert other.check_health() is True

    requests = rig.batch_messages() + rig.health_messages()
    assert len(requests) == 3
    topics = {m.response_topic for m in requests[:2]}
    assert len(topics) == 1  # one session per publisher
    (mine,) = topics
    assert mine is not None and REPLY_RE.match(mine)
    third = requests[2].response_topic
    assert third is not None and REPLY_RE.match(third) and third != mine  # random session
    correlations = [m.correlation_data for m in requests]
    assert all(c is not None and len(c) == 16 for c in correlations)
    assert len(set(correlations)) == 3
    for message, qos in rig.edge.published:
        assert qos == 1, message.topic
    assert sorted(rig.bridge_transport.subscribed) == sorted([(BATCH_TOPIC, 1), (HEALTH_TOPIC, 1)])
    for message, qos in rig.bridge_transport.published:
        assert qos == 1, message.topic

    replies = rig.replies()
    assert len(replies) == 3
    for req, rep in zip(requests, replies, strict=True):
        assert rep.topic == req.response_topic
        assert rep.correlation_data == req.correlation_data
        assert rep.user_property("result") == "ok"
    assert BatchResult.model_validate_json(replies[0].payload)
    assert replies[1].payload == b"" and replies[2].payload == b""
    for message in requests + replies:
        assert b"image" not in message.payload.lower() and b"jpeg" not in message.payload.lower()


# =========================================================================== exploratory: bridge


BAD_RESPONSE_TOPICS = [
    f"partqc/v1/edge-02/reply/abc{secrets.token_hex(2)}",  # another device
    BATCH_TOPIC,  # would make the bridge publish a batch
    HEALTH_TOPIC,
    f"partqc/v1/{DEVICE}/reply/+",
    f"partqc/v1/{DEVICE}/reply/#",
    f"partqc/v1/{DEVICE}/reply/",
    f"partqc/v1/{DEVICE}/reply/abc/extra",
    f"partqc/v1/{DEVICE}/other/abc",
    "partqc/#",
    "$SYS/broker/x",
    "",
]


@pytest.mark.parametrize("response_topic", BAD_RESPONSE_TOPICS)
@pytest.mark.parametrize("topic", [BATCH_TOPIC, HEALTH_TOPIC])
def test_extra_bridge_answers_only_on_a_reply_topic_of_section_4_1(
    rig: MqttRig, caplog: pytest.LogCaptureFixture, topic: str, response_topic: str
) -> None:
    caplog.set_level(logging.DEBUG)
    attacker = rig.broker.client("acc-attacker")
    attacker.connect()
    payload = batch_json([inspection()]) if topic == BATCH_TOPIC else b""
    before = len(rig.broker.published)
    attacker.publish(
        request(topic, payload, response_topic=response_topic, correlation=secrets.token_bytes(16))
    )
    after = rig.broker.published[before:]
    assert [m.topic for m in after] == [topic]  # the bridge published nothing
    assert rig.cloud.requests == []  # and called no API
    assert payload.decode() not in log_text(caplog) or payload == b""


@pytest.mark.parametrize(
    ("response_topic", "correlation"),
    [(None, b"c" * 16), ("VALID", None), (None, None), ("VALID", b"")],
    ids=["no-response-topic", "no-correlation", "neither", "empty-correlation"],
)
def test_extra_request_without_properties_ignored_with_a_warning(
    rig: MqttRig, caplog: pytest.LogCaptureFixture, response_topic: str | None, correlation: Any
) -> None:
    caplog.set_level(logging.DEBUG)
    attacker = rig.broker.client("acc-attacker")
    attacker.connect()
    rt = reply_to(rig) if response_topic == "VALID" else None
    payload = batch_json([inspection()])
    before = len(rig.broker.published)
    attacker.publish(request(BATCH_TOPIC, payload, response_topic=rt, correlation=correlation))
    assert [m.topic for m in rig.broker.published[before:]] == [BATCH_TOPIC]
    assert rig.cloud.requests == []
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert payload.decode() not in log_text(caplog)


def test_extra_bridge_ignores_topics_of_another_device(rig: MqttRig) -> None:
    attacker = rig.broker.client("acc-attacker")
    attacker.connect()
    other = "partqc/v1/edge-02"
    for topic in (f"{other}/batch", f"{other}/health", f"partqc/v1/{DEVICE}/batch/x"):
        attacker.publish(
            request(
                topic,
                batch_json([inspection(device_id="edge-02")]),
                response_topic=f"{other}/reply/abc",
                correlation=secrets.token_bytes(16),
            )
        )
    assert rig.cloud.requests == []
    assert rig.replies() == []
    assert rig.broker.published_on(f"{other}/reply/#") == []


def _hundred_and_one() -> bytes:
    items = [json.loads(inspection().model_dump_json()) for _ in range(101)]
    return json.dumps({"items": items}).encode()


def _with_image_field() -> bytes:
    item = json.loads(inspection().model_dump_json())
    item["image"] = "data:image/jpeg;base64,IMGMARKER" + secrets.token_hex(8)
    return json.dumps({"items": [item]}).encode()


MALFORMED = {
    "empty": b"",
    "not-json": b"not json at all",
    "invalid-utf8": b"\xff\xfe\xfa{",
    "json-list": b"[1, 2, 3]",
    "no-items": b"{}",
    "zero-items": b'{"items": []}',
    "101-items": _hundred_and_one(),
    "bad-item": b'{"items": [{"inspection_id": "not-a-uuid"}]}',
    "huge": b'{"items": ["' + b"A" * (4 * 1024 * 1024) + b'"]}',
    "nul": b'{"items": [\x00]}',
}


@pytest.mark.parametrize("name", list(MALFORMED))
def test_extra_malformed_batch_is_rejected_without_calling_the_api(
    rig: MqttRig, caplog: pytest.LogCaptureFixture, name: str
) -> None:
    caplog.set_level(logging.DEBUG)
    payload = MALFORMED[name]
    attacker = rig.broker.client("acc-attacker")
    attacker.connect()
    rt, corr = reply_to(rig), secrets.token_bytes(16)
    started = time.monotonic()
    attacker.publish(request(BATCH_TOPIC, payload, response_topic=rt, correlation=corr))
    assert time.monotonic() - started < 10
    replies = rig.broker.published_on(rt)
    assert len(replies) == 1
    assert replies[0].correlation_data == corr
    assert replies[0].user_property("result") == "rejected"
    assert replies[0].payload == INVALID_BATCH.encode()
    assert rig.cloud.requests == []
    text = log_text(caplog)
    if len(payload) > 8:
        assert payload[:200].decode("utf-8", "replace") not in text


def test_extra_extra_fields_never_reach_the_api_r02(rig: MqttRig) -> None:
    """An ``image`` field smuggled into an item is either refused or dropped: it never reaches
    the API (R-02, R-04)."""
    payload = _with_image_field()
    attacker = rig.broker.client("acc-attacker")
    attacker.connect()
    rt = reply_to(rig)
    attacker.publish(
        request(BATCH_TOPIC, payload, response_topic=rt, correlation=secrets.token_bytes(16))
    )
    for req in rig.cloud.requests:
        assert b"IMGMARKER" not in req.read()
        assert b'"image"' not in req.read()
    assert len(rig.broker.published_on(rt)) == 1


def test_extra_replayed_batch_is_deduplicated_r05(rig: MqttRig) -> None:
    items = [inspection(), inspection()]
    payload = batch_json(items)
    attacker = rig.broker.client("acc-replayer")
    attacker.connect()
    statuses: list[list[str]] = []
    for _ in range(3):
        rt, corr = reply_to(rig), secrets.token_bytes(16)
        attacker.publish(request(BATCH_TOPIC, payload, response_topic=rt, correlation=corr))
        (reply,) = rig.broker.published_on(rt)
        assert reply.user_property("result") == "ok"
        statuses.append([r.status for r in BatchResult.model_validate_json(reply.payload).results])
    assert statuses == [["created", "created"], ["duplicate", "duplicate"], ["duplicate"] * 2]
    assert sorted(rig.cloud.writes) == sorted(str(i.inspection_id) for i in items)


def test_extra_bridge_health_maps_api_failure_to_transient(rig: MqttRig) -> None:
    rig.cloud.health_status = 503
    assert rig.publisher.check_health() is False
    (reply,) = rig.replies()
    assert reply.user_property("result") == "transient"
    assert reply.payload == b""


@pytest.mark.parametrize(
    ("status", "expected"), [(503, "transient"), (401, "auth"), (403, "auth"), (413, "rejected")]
)
def test_extra_bridge_maps_api_status_to_result(rig: MqttRig, status: int, expected: str) -> None:
    rig.cloud.fail = lambda request: (
        httpx.Response(status, json={"detail": "x"}) if request.url.path == BATCH_PATH else None
    )
    attacker = rig.broker.client("acc-client")
    attacker.connect()
    rt = reply_to(rig)
    attacker.publish(
        request(
            BATCH_TOPIC,
            batch_json([inspection()]),
            response_topic=rt,
            correlation=secrets.token_bytes(16),
        )
    )
    (reply,) = rig.broker.published_on(rt)
    assert reply.user_property("result") == expected
    if expected in ("transient", "auth"):
        assert reply.payload == b""
    else:
        assert reply.payload.decode().startswith(f"HTTP {status}")


# =========================================================================== exploratory: publisher


class FakeBridge:
    """A broker client that answers the batch requests with a tampered answer."""

    def __init__(self, broker: InMemoryBroker, answer: Callable[[MqttMessage], MqttMessage]):
        self.transport = broker.client("acc-fake-bridge")
        self.answer = answer
        self.transport.subscribe(BATCH_TOPIC, self._handle, 1)
        self.transport.connect()

    def _handle(self, message: MqttMessage) -> None:
        self.transport.publish(self.answer(message), 1)


def _ok_with(results: Callable[[list[str]], list[dict[str, str]]]) -> Callable[..., MqttMessage]:
    def build(message: MqttMessage) -> MqttMessage:
        ids = [str(i.inspection_id) for i in BatchCreate.model_validate_json(message.payload).items]
        body = json.dumps({"results": results(ids)}).encode()
        return MqttMessage(
            topic=message.response_topic or "",
            payload=body,
            correlation_data=message.correlation_data,
            user_properties=(("result", "ok"),),
        )

    return build


def _raw(payload: bytes, result: str | None) -> Callable[..., MqttMessage]:
    def build(message: MqttMessage) -> MqttMessage:
        props = (("result", result),) if result is not None else ()
        return MqttMessage(
            topic=message.response_topic or "",
            payload=payload,
            correlation_data=message.correlation_data,
            user_properties=props,
        )

    return build


TAMPERED = {
    "other-ids": _ok_with(lambda ids: [{"inspection_id": str(uuid.uuid4()), "status": "created"}]),
    "reversed": _ok_with(
        lambda ids: [{"inspection_id": i, "status": "created"} for i in ids[::-1]]
    ),
    "shorter": _ok_with(lambda ids: [{"inspection_id": i, "status": "created"} for i in ids[:-1]]),
    "longer": _ok_with(
        lambda ids: [{"inspection_id": i, "status": "created"} for i in [*ids, ids[0]]]
    ),
    "bad-status": _ok_with(lambda ids: [{"inspection_id": i, "status": "stored"} for i in ids]),
    "ok-not-json": _raw(b"{not json", "ok"),
    "ok-empty": _raw(b"", "ok"),
    "no-result": _raw(b"", None),
    "unknown-result": _raw(b"", "accepted"),
    "transient": _raw(b"", "transient"),
    "ok-uppercase": _raw(b"", "OK"),
}


@pytest.mark.parametrize("name", list(TAMPERED))
def test_extra_tampered_answer_is_transient_nothing_sent(rig_no_bridge: MqttRig, name: str) -> None:
    r = rig_no_bridge
    FakeBridge(r.broker, TAMPERED[name])
    for _ in range(2):
        r.put()
    started = time.monotonic()
    r.loop.run_once()
    elapsed = time.monotonic() - started
    (request_message,) = r.batch_messages()
    (answer,) = r.replies()  # the tampered answer was really sent ...
    assert answer.correlation_data == request_message.correlation_data
    assert elapsed < TIMEOUT_S * 0.6, elapsed  # ... and consumed (no wait for the timeout)
    rows = r.rows()
    assert all(row["status"] == "pending" and row["attempts"] == 1 for row in rows), rows
    assert all(row["sent_at"] is None for row in rows)
    assert r.outbox.stats().connectivity == "offline"


def test_extra_forged_answer_with_unknown_correlation_is_discarded(
    rig_no_bridge: MqttRig,
) -> None:
    r = rig_no_bridge
    forger = r.broker.client("acc-forger")
    forger.connect()

    def forge(message: MqttMessage) -> bool:
        if message.topic == BATCH_TOPIC and message.response_topic:
            ids = [str(i.inspection_id) for i in batch_ids(message.payload)]
            body = json.dumps({"results": [{"inspection_id": i, "status": "created"} for i in ids]})
            forger.publish(
                MqttMessage(
                    topic=message.response_topic,
                    payload=body.encode(),
                    correlation_data=secrets.token_bytes(16),  # not the request's
                    user_properties=(("result", "ok"),),
                )
            )
        return True

    r.broker.intercept = forge
    for _ in range(3):
        r.put()
    started = time.monotonic()
    r.loop.run_once()
    elapsed = time.monotonic() - started
    assert len(r.replies()) == 1  # the forged answer reached the reply topic ...
    assert elapsed >= TIMEOUT_S * 0.9, elapsed  # ... and was discarded: the request timed out
    assert all(row["status"] == "pending" and row["attempts"] == 1 for row in r.rows())


def test_extra_stale_answer_of_an_earlier_request_is_discarded(rig: MqttRig) -> None:
    """The answer to the first request is held back and replayed (as ``rejected``) right before
    the answer to the retry: it must not decide the second request."""
    held: list[MqttMessage] = []
    replayer = rig.broker.client("acc-replayer")
    replayer.connect()

    def hold_then_replay(message: MqttMessage) -> bool:
        if REPLY_RE.match(message.topic) and message.user_property("result") == "ok":
            if not held:
                held.append(message)
                return False
            if held and held[0].correlation_data != message.correlation_data:
                stale = held.pop()
                replayer.publish(
                    MqttMessage(
                        topic=stale.topic,
                        payload=REFUSAL.encode(),
                        correlation_data=stale.correlation_data,
                        user_properties=(("result", "rejected"),),
                    )
                )
        return True

    rig.broker.intercept = hold_then_replay
    rig.put()
    rig.drain()
    assert held == []  # the stale answer was replayed
    assert [m.user_property("result") for m in rig.replies()].count("rejected") == 1
    (row,) = rig.rows()
    assert row["status"] == "sent", row
    assert row["last_error"] is None or "Value cannot be stored" not in row["last_error"]


def test_extra_rejected_detail_from_the_bridge_is_sanitized(rig_no_bridge: MqttRig) -> None:
    r = rig_no_bridge
    long_text = "HTTP 422: bad\nline\r\x1b[31m\x00" + "x" * 2000
    FakeBridge(r.broker, _raw(long_text.encode() + b"\xff", "rejected"))
    r.put()
    r.drain()
    (row,) = r.rows()
    assert row["status"] == "dead"
    error = row["last_error"]
    assert error.startswith("HTTP 422: bad")
    assert not any(ord(c) < 0x20 or ord(c) == 0x7F for c in error), repr(error)
    assert len(error) < 2000


def test_extra_publish_and_health_with_broker_down_fail_fast(rig: MqttRig) -> None:
    rig.broker.stop()
    started = time.monotonic()
    assert rig.publisher.check_health() is False
    with pytest.raises(PublishTransientError):
        rig.publisher.publish_batch([inspection()])
    assert time.monotonic() - started <= 2 * TIMEOUT_S + MARGIN_S
    rig.broker.start()
    assert rig.publisher.check_health() is True


@pytest.fixture
def silent_listener() -> Iterator[int]:
    """A TCP listener on 127.0.0.1 that accepts and never answers (no CONNACK)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    accepted: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
                accepted.append(conn)
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield int(server.getsockname()[1])
    finally:
        stop.set()
        thread.join(2)
        for conn in accepted:
            conn.close()
        server.close()


@pytest.mark.parametrize("kind", ["closed-port", "silent-listener"])
def test_extra_real_transport_single_deadline_with_broker_unreachable(
    kind: str, silent_listener: int, caplog: pytest.LogCaptureFixture
) -> None:
    """With the real transport and no usable broker on loopback, ``check_health`` is ``False``
    and ``publish_batch`` raises ``PublishTransientError`` within ``MQTT_RESPONSE_TIMEOUT_S``
    (connection, PUBACK and answer share one deadline)."""
    caplog.set_level(logging.DEBUG)
    port = free_port() if kind == "closed-port" else silent_listener
    password = new_password()
    transport = PahoMqttTransport("127.0.0.1", port, new_user(), password, client_id="acc-dl")
    publisher = MqttPublisher(transport, DEVICE, TIMEOUT_S)
    try:
        started = time.monotonic()
        assert publisher.check_health() is False
        assert time.monotonic() - started <= TIMEOUT_S + MARGIN_S
        started = time.monotonic()
        with pytest.raises(PublishTransientError):
            publisher.publish_batch([inspection()])
        assert time.monotonic() - started <= TIMEOUT_S + MARGIN_S
    finally:
        publisher.close()
        transport.disconnect()
    assert password not in log_text(caplog)


# =========================================================================== exploratory: R-06


def test_extra_simulated_source_survives_the_mqtt_path_r06(rig: MqttRig) -> None:
    live, simulated = rig.put(inspection()), rig.put(inspection(source=Source.SIMULATED))
    rig.drain()
    assert rig.cloud.stored[str(live.inspection_id)]["source"] == "live"
    assert rig.cloud.stored[str(simulated.inspection_id)]["source"] == "simulated"


def test_extra_stub_model_with_mqtt_builds_no_publisher_r06(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    edge_environment(tmp_path, monkeypatch)
    monkeypatch.setenv("EDGE_PUBLISHER", "mqtt")
    monkeypatch.setenv("MQTT_USERNAME", new_user())
    monkeypatch.setenv("MQTT_PASSWORD", new_password())
    monkeypatch.setenv("DEVICE_API_KEY", new_key())
    monkeypatch.setenv("CLOUD_API_URL", CLOUD_URL)
    built = loop_spy(monkeypatch)
    transports: list[Any] = []
    original = PahoMqttTransport.__init__

    def spy(self: Any, *args: Any, **kwargs: Any) -> None:
        transports.append(self)
        original(self, *args, **kwargs)

    monkeypatch.setattr(PahoMqttTransport, "__init__", spy)
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
    assert call_main(["--stub-model"]) == 0
    assert built == []
    assert transports == []
    assert not (tmp_path / "edge-data" / "outbox.sqlite3").exists()


# =========================================================================== exploratory: config


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_extra_loopback_hosts_accepted(
    host: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MQTT_HOST", host)
    settings = EdgeSettings(DATASET_DIR=tmp_path / "ds")
    assert host == settings.MQTT_HOST


def test_extra_defaults_of_section_4_5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    s = EdgeSettings(DATASET_DIR=tmp_path / "ds")
    assert s.EDGE_PUBLISHER == "http"
    assert s.MQTT_HOST == "127.0.0.1"
    assert s.MQTT_PORT == 1883
    assert s.MQTT_RESPONSE_TIMEOUT_S == 15
    assert not s.MQTT_USERNAME and not s.MQTT_PASSWORD


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MQTT_HOST", "0.0.0.0"),
        ("MQTT_HOST", "127.0.0.2"),
        ("MQTT_HOST", "broker.example.com"),
        ("MQTT_HOST", "localhost.example.com"),
        ("MQTT_PORT", "0"),
        ("MQTT_PORT", "65536"),
        ("MQTT_PORT", "abc"),
        ("MQTT_RESPONSE_TIMEOUT_S", "0.5"),
        ("MQTT_RESPONSE_TIMEOUT_S", "61"),
        ("MQTT_RESPONSE_TIMEOUT_S", "nan"),
        ("MQTT_RESPONSE_TIMEOUT_S", "inf"),
        ("EDGE_PUBLISHER", "HTTP-x"),
    ],
)
def test_extra_invalid_values_exit_2_without_echoing_them(
    tmp_path: Path, name: str, value: str
) -> None:
    env = mqtt_env(tmp_path, **{name: value})
    run = run_edge(env, cwd_for(tmp_path))
    assert run.code == 2
    assert name in run.out
    if len(value) > 4:
        assert value not in run.out
    assert env["MQTT_PASSWORD"] not in run.out and env["DEVICE_API_KEY"] not in run.out


def test_extra_marker_value_of_edge_publisher_is_not_echoed(tmp_path: Path) -> None:
    marker = "pub" + secrets.token_hex(8)
    env = base_env(tmp_path)
    env["EDGE_PUBLISHER"] = marker
    run = run_edge(env, cwd_for(tmp_path))
    assert run.code == 2
    assert marker not in run.out


@pytest.mark.parametrize("missing", ["MQTT_USERNAME", "MQTT_PASSWORD"])
def test_extra_mqtt_credentials_required_at_the_edge(tmp_path: Path, missing: str) -> None:
    env = mqtt_env(tmp_path)
    del env[missing]
    run = run_edge(env, cwd_for(tmp_path))
    assert run.code == 2
    assert missing in run.out


@pytest.mark.parametrize(
    "change",
    [
        {"MQTT_PASSWORD": None},
        {"MQTT_USERNAME": None},
        {"CLOUD_API_URL": None},
        {"MQTT_HOST": "192.168.0.10"},
        {"MQTT_PORT": "70000"},
        {"CLOUD_API_URL": "http://cloud.example.com"},
    ],
    ids=["no-password", "no-user", "no-url", "remote-host", "bad-port", "plain-http-url"],
)
def test_extra_bridge_invalid_configuration_exits_2(
    tmp_path: Path, change: dict[str, str | None]
) -> None:
    env = mqtt_env(tmp_path)
    for name, value in change.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    run = run_bridge(env, cwd_for(tmp_path))
    assert run.code == 2
    assert env.get("MQTT_PASSWORD", "-" * 30) not in run.out
    assert env["DEVICE_API_KEY"] not in run.out


def test_extra_bridge_unknown_argument_exits_2_without_echoing_values(tmp_path: Path) -> None:
    """Option names may be named (SPEC-034 convention); values never are."""
    value = "val" + secrets.token_hex(8)
    positional = "pos" + secrets.token_hex(8)
    run = run_bridge(mqtt_env(tmp_path), cwd_for(tmp_path), f"--opt={value}", positional)
    assert run.code == 2
    assert value not in run.out and positional not in run.out


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_extra_bridge_exits_0_on_signal_with_broker_down(tmp_path: Path, signum: int) -> None:
    env = mqtt_env(tmp_path, MQTT_PORT=str(free_port()), PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        [sys.executable, "-m", "qc_edge.mqtt_bridge"],
        env=env,
        cwd=cwd_for(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        time.sleep(3)
        assert proc.poll() is None, "the bridge exited before the signal"
        proc.send_signal(signum)
        out, _ = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert proc.returncode == 0, out
    assert env["MQTT_PASSWORD"] not in out and env["DEVICE_API_KEY"] not in out


def test_extra_password_not_in_status_nor_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    env = edge_environment(tmp_path, monkeypatch)
    password = new_password()
    monkeypatch.setenv("EDGE_PUBLISHER", "mqtt")
    monkeypatch.setenv("MQTT_USERNAME", new_user())
    monkeypatch.setenv("MQTT_PASSWORD", password)
    settings = EdgeSettings()
    outbox = SqliteOutbox(tmp_path / "status.db", connectivity=ConnectivityState())
    try:
        app = create_app(settings, None, outbox)

        async def go() -> list[httpx.Response]:
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
            async with httpx.AsyncClient(
                transport=transport, base_url=f"http://127.0.0.1:{EDGE_PORT}"
            ) as c:
                return [
                    await c.get("/api/status", headers={SESSION_HEADER: env.token}),
                    await c.get("/"),
                ]

        responses = asyncio.run(go())
    finally:
        outbox.close()
    assert responses[0].status_code == 200
    for response in responses:
        assert password not in response.text


# =========================================================================== exploratory: files


def test_extra_mosquitto_example_config_loopback_no_anonymous() -> None:
    lines = [
        line.strip()
        for line in (EDGE_ROOT / "mosquitto" / "partqc.conf").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "listener 1883 127.0.0.1" in lines
    assert "allow_anonymous false" in lines
    assert not any(line.startswith("listener") and "127.0.0.1" not in line for line in lines)
    (pw,) = [line for line in lines if line.startswith("password_file")]
    path = pw.split(None, 1)[1]
    assert path.startswith("/") and not path.startswith(str(ROOT))
    assert "allow_anonymous true" not in lines


def test_extra_env_example_documents_the_variables_without_secrets() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    values: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*#?\s*([A-Z_]+)=(.*)$", line)
        if m:
            values.setdefault(m.group(1), m.group(2).strip())
    for name in (
        "EDGE_PUBLISHER",
        "MQTT_HOST",
        "MQTT_PORT",
        "MQTT_USERNAME",
        "MQTT_PASSWORD",
        "MQTT_RESPONSE_TIMEOUT_S",
    ):
        assert name in values, name
    assert values["MQTT_PASSWORD"] in ("", '""', "''")


def test_extra_paho_declared_only_by_qc_edge_r12() -> None:
    edge = tomllib.loads((EDGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(d.startswith("paho-mqtt") for d in edge["project"]["dependencies"])
    for other in ("api", "dashboard"):
        text = (ROOT / other / "pyproject.toml").read_text(encoding="utf-8")
        assert "paho" not in text
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    (paho,) = [p for p in lock["package"] if p["name"] == "paho-mqtt"]
    assert paho["version"] == "2.1.0"
    for forbidden in ("torch", "onnxruntime", "timm", "torchvision"):
        assert forbidden not in _lock_closure("qc-api")
        assert forbidden not in _lock_closure("qc-dashboard")


# =========================================================================== CLI helpers


@dataclass
class EdgeEnv:
    tmp: Path
    token: str


def edge_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EdgeEnv:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(cwd_for(tmp_path))
    token = secrets.token_urlsafe(30)
    monkeypatch.setenv("EDGE_PORT", str(EDGE_PORT))
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "edge-data"))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setenv("DATASET_DIR", str(tmp_path / "dataset"))
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    monkeypatch.setattr(qc_edge.netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])
    return EdgeEnv(tmp_path, token)


def loop_spy(monkeypatch: pytest.MonkeyPatch) -> list[PublishLoop]:
    built: list[PublishLoop] = []
    original = PublishLoop.__init__

    def spy(self: PublishLoop, *args: Any, **kwargs: Any) -> None:
        built.append(self)
        original(self, *args, **kwargs)

    monkeypatch.setattr(PublishLoop, "__init__", spy)
    return built


def call_main(argv: list[str]) -> int:
    try:
        value = qc_edge.cli.main(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return value if isinstance(value, int) else 0
