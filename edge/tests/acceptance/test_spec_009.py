"""Acceptance tests for SPEC-009 (qc-edge: SQLite outbox and HTTP publisher).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One ``test_caNN_*`` per automatable CA, at least (CA-17 is manual and is recorded
in ``reviews/SPEC-009/r1-test-report.md``). Tests named ``test_extra_*`` are exploratory edge
cases around the SPEC (security tag: key and refusal body out of logs and ``last_error``,
``CLOUD_API_URL`` validation, idempotency R-05, R-06) that no CA spells out.

Rules followed (``reviews/checklist.md`` and ``docs/architecture.md`` §10):

* the only boundaries replaced are the ones the SPEC names: the cloud network (an
  ``httpx.MockTransport`` with a fake cloud that implements the SPEC-004 idempotency, or a local
  HTTP server on ``127.0.0.1`` where the SPEC puts ``CLOUD_API_URL`` there), the clock, the RNG,
  ``uvicorn.run`` (spy) and the LAN socket; SQLite is real, in ``tmp_path``;
* every key and token is generated at run time (``secrets``), never a literal in a URL or header;
* images are synthetic and generated in memory (R-14); the dummy ONNX model is built here with
  ``onnx.helper`` in ``tmp_path``;
* no test runs the test suite in a subprocess: CA-09 runs a short ``python`` script, and CA-16
  runs pytest on two explicit files, deselecting itself.
"""

from __future__ import annotations

import asyncio
import hashlib
import http.server
import io
import json
import logging
import random
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import onnx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from onnx import TensorProto, helper
from PIL import Image, ImageFile

import qc_edge.cli
import qc_edge.netinfo
import qc_edge.publish_loop
from qc_contracts import Grade, InspectionCreate, ObjectType, Source
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.outbox import SqliteOutbox
from qc_edge.publish_loop import ConnectivityState, PublishLoop
from qc_edge.publisher import (
    HttpPublisher,
    PublishAuthError,
    PublishRejectedError,
    PublishResult,
    PublishTransientError,
)
from qc_edge.sink import SinkError
from qc_preprocess import PreprocessParams

pytestmark = pytest.mark.acceptance

EDGE_ROOT = Path(__file__).resolve().parents[2]  # edge/
ROOT = EDGE_ROOT.parent  # repository root

BATCH_PATH = "/api/v1/inspections/batch"
HEALTH_PATH = "/api/v1/health"
SESSION_HEADER = "X-Session-Token"
PORT = 8000
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
STUB_VERSION = "stub-v0"
REAL_VERSION = "partqc-mnv3-v1"
ISO_FIXED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$")

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
)

# architecture.md §3.2
CONTRACT_FIELDS = {
    "inspection_id",
    "device_id",
    "lot_id",
    "inspected_at",
    "object_type",
    "grade",
    "grade_score",
    "type_confidence",
    "grade_confidence",
    "needs_review",
    "model_version",
    "model_sha256",
    "latency_ms",
    "source",
}

OUTBOX_COLUMNS = [
    "inspection_id",
    "payload",
    "created_at",
    "attempts",
    "next_attempt_at",
    "sent_at",
    "status",
    "last_error",
]


def new_key() -> str:
    """A device key generated at run time (never a literal)."""
    return "acc_" + secrets.token_urlsafe(24)


def new_marker() -> str:
    return "mk-" + secrets.token_hex(12)


# =========================================================================== domain helpers


def inspection(
    *,
    model_version: str = REAL_VERSION,
    source: Source = Source.LIVE,
    inspected_at: datetime = T0,
    lot_id: str = "L-001",
) -> InspectionCreate:
    return InspectionCreate(
        inspection_id=uuid.uuid4(),
        device_id="edge-01",
        lot_id=lot_id,
        inspected_at=inspected_at,
        object_type=ObjectType.SCREW,
        grade=Grade.GOOD,
        grade_score=1.1,
        type_confidence=0.9,
        grade_confidence=0.8,
        needs_review=False,
        model_version=model_version,
        model_sha256=hashlib.sha256(b"acceptance-model").hexdigest(),
        latency_ms=42,
        source=source,
    )


class ManualClock:
    """The fake clock of the SPEC (always UTC)."""

    def __init__(self, start: datetime = T0) -> None:
        self.now = start
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self.now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.now += timedelta(seconds=seconds)

    def set(self, value: datetime) -> None:
        with self._lock:
            self.now = value


Failure = Callable[[httpx.Request], "Exception | httpx.Response | None"]


class FakeCloud:
    """Fake cloud with the SPEC-004 idempotency: a dict by ``inspection_id``.

    A batch that contains a ``reject_ids`` item is refused as a whole (nothing stored), like the
    real API (single transaction). ``fail`` may return an exception (raised), a response
    (returned) or ``None`` (normal behaviour). ``lose_next`` stores the batch and then raises a
    timeout ("lost response").
    """

    def __init__(self) -> None:
        self.stored: dict[str, dict[str, Any]] = {}
        self.writes: list[str] = []
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []
        self.batches: list[list[str]] = []
        self.answers: list[tuple[str, str]] = []
        self.reject_ids: set[str] = set()
        self.reject_response: Callable[[], httpx.Response] = lambda: httpx.Response(
            422, json={"detail": "Value cannot be stored"}
        )
        self.fail: Failure | None = None
        self.lose_next = False
        self.health_status = 200
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            body = request.read()
            self.requests.append(request)
            self.bodies.append(body)
            if self.fail is not None:
                outcome = self.fail(request)
                if isinstance(outcome, Exception):
                    raise outcome
                if isinstance(outcome, httpx.Response):
                    return outcome
            if request.url.path == HEALTH_PATH and request.method == "GET":
                return httpx.Response(self.health_status, json={"status": "ok", "db": "ok"})
            if request.url.path == BATCH_PATH and request.method == "POST":
                items = json.loads(body)["items"]
                ids = [item["inspection_id"] for item in items]
                self.batches.append(ids)
                if any(i in self.reject_ids for i in ids):
                    return self.reject_response()
                results = []
                for item in items:
                    iid = item["inspection_id"]
                    if iid in self.stored:
                        results.append({"inspection_id": iid, "status": "duplicate"})
                    else:
                        self.stored[iid] = item
                        self.writes.append(iid)
                        results.append({"inspection_id": iid, "status": "created"})
                self.answers.extend((r["inspection_id"], r["status"]) for r in results)
                if self.lose_next:
                    self.lose_next = False
                    raise httpx.ReadTimeout("response lost", request=request)
                return httpx.Response(200, json={"results": results})
            return httpx.Response(404, json={"detail": "Not Found"})

    def batch_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == BATCH_PATH]

    def health_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == HEALTH_PATH]


@dataclass
class Rig:
    path: Path
    clock: ManualClock
    connectivity: ConnectivityState
    outbox: SqliteOutbox
    cloud: FakeCloud
    publisher: HttpPublisher
    loop: PublishLoop
    key: str
    base_url: str = "https://cloud.test"
    puts: list[InspectionCreate] = field(default_factory=list)

    def put(self, item: InspectionCreate | None = None) -> InspectionCreate:
        item = item if item is not None else inspection()
        self.outbox.put(item)
        self.puts.append(item)
        return item

    def rows(self) -> list[dict[str, Any]]:
        return read_rows(self.path)

    def drain(self, *, step_s: float = 2.0, max_cycles: int = 2000) -> int:
        cycles = 0
        while self.outbox.stats().pending > 0:
            assert cycles < max_cycles, "outbox did not drain"
            self.loop.run_once()
            self.clock.advance(step_s)
            cycles += 1
        return cycles


def make_rig(tmp_path: Path, *, start: datetime = T0, name: str = "outbox.sqlite3") -> Rig:
    path = tmp_path / name
    clock = ManualClock(start)
    connectivity = ConnectivityState()
    outbox = SqliteOutbox(path, clock=clock, connectivity=connectivity)
    cloud = FakeCloud()
    key = new_key()
    base_url = "https://cloud.test"
    publisher = HttpPublisher(base_url, key, transport=httpx.MockTransport(cloud))
    loop = PublishLoop(outbox, publisher, connectivity, clock=clock, rng=random.Random(0))
    return Rig(path, clock, connectivity, outbox, cloud, publisher, loop, key, base_url)


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    r = make_rig(tmp_path)
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


def raw_rows(path: Path) -> list[tuple[Any, ...]]:
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT * FROM outbox ORDER BY inspection_id").fetchall()
    finally:
        con.close()


def ts(value: str) -> datetime:
    assert ISO_FIXED.fullmatch(value), value
    return datetime.fromisoformat(value)


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
        if record.stack_info:
            parts.append(record.stack_info)
    return "\n".join(parts)


def request_ids(request: httpx.Request) -> list[str]:
    return [item["inspection_id"] for item in json.loads(request.read())["items"]]


# =========================================================================== CLI helpers


def build_dummy_onnx(type_probs: Sequence[float], grade_probs: Sequence[float]) -> bytes:
    """ReduceMean(input) -> Reshape [N,1] -> Mul 0 -> Add constants (SPEC-008 §6 dummy)."""
    t, g = len(type_probs), len(grade_probs)
    inp = helper.make_tensor_value_info("image", TensorProto.FLOAT, ["N", 3, 224, 224])
    out_t = helper.make_tensor_value_info("type_probs", TensorProto.FLOAT, ["N", t])
    out_g = helper.make_tensor_value_info("grade_probs", TensorProto.FLOAT, ["N", g])
    inits = [
        helper.make_tensor("shape_n1", TensorProto.INT64, [2], [-1, 1]),
        helper.make_tensor("zero", TensorProto.FLOAT, [], [0.0]),
        helper.make_tensor("type_const", TensorProto.FLOAT, [1, t], list(type_probs)),
        helper.make_tensor("grade_const", TensorProto.FLOAT, [1, g], list(grade_probs)),
    ]
    nodes = [
        helper.make_node("ReduceMean", ["image"], ["mean"], axes=[1, 2, 3], keepdims=0),
        helper.make_node("Reshape", ["mean", "shape_n1"], ["mean_n1"]),
        helper.make_node("Mul", ["mean_n1", "zero"], ["zeros_n1"]),
        helper.make_node("Add", ["zeros_n1", "type_const"], ["type_probs"]),
        helper.make_node("Add", ["zeros_n1", "grade_const"], ["grade_probs"]),
    ]
    graph = helper.make_graph(nodes, "acc9-dummy", [inp], [out_t, out_g], initializer=inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model.SerializeToString()


def make_model_dir(root: Path, name: str = "partqc-acc9-v1") -> Path:
    d = root / name
    d.mkdir(parents=True)
    data = build_dummy_onnx([0.9, 0.05, 0.05], [0.05, 0.8, 0.05, 0.05, 0.05])
    (d / "model.onnx").write_bytes(data)
    (d / "model.sha256").write_text(f"{hashlib.sha256(data).hexdigest()}  model.onnx\n")
    (d / "labels.json").write_text(
        json.dumps(
            {
                "object_types": ["screw", "nut", "other"],
                "grades": ["perfect", "good", "fair", "poor", "unusable"],
            }
        )
    )
    PreprocessParams().to_json(d / "preprocessing.json")
    (d / "decision.json").write_text(
        json.dumps(
            {"type_threshold": 0.5, "unusable_threshold": 0.4, "grade_review_threshold": 0.6}
        )
    )
    return d


def synthetic_jpeg(seed: int = 9) -> bytes:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def capture(client: TestClient, token: str, lot_id: str = "L-009") -> httpx.Response:
    return client.post(
        "/api/capture",
        headers={SESSION_HEADER: token},
        data={"lot_id": lot_id, "mode": "inspect"},
        files={"image": ("foto.jpg", synthetic_jpeg(), "image/jpeg")},
    )


def call_main(argv: list[str]) -> int:
    try:
        value = qc_edge.cli.main(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return value if isinstance(value, int) else 0


class UvicornRunner:
    """``uvicorn.run`` spy: runs ``scenario(app)`` (with the app lifespan) instead of serving.

    Exceptions raised by the scenario are stored and re-raised by ``check()``, so that ``main``
    can never swallow an assertion.
    """

    def __init__(self, scenario: Callable[[Any], Any] | None = None) -> None:
        self.scenario = scenario
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.result: Any = None
        self.error: BaseException | None = None

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))
        if self.scenario is None:
            return
        app = args[0] if args else kwargs["app"]
        try:
            self.result = self.scenario(app)
        except BaseException as exc:  # noqa: BLE001 - re-raised by check()
            self.error = exc

    def check(self) -> None:
        if self.error is not None:
            raise self.error


@dataclass
class EdgeEnv:
    tmp: Path
    data_dir: Path
    token: str


@pytest.fixture
def edge_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EdgeEnv:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)  # relative defaults land in tmp_path, never in the repository
    data_dir = tmp_path / "edge-data"
    token = secrets.token_urlsafe(30)
    monkeypatch.setenv("EDGE_PORT", str(PORT))
    monkeypatch.setenv("EDGE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setenv("DATASET_DIR", str(tmp_path / "dataset"))
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    monkeypatch.setattr(qc_edge.netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])
    return EdgeEnv(tmp=tmp_path, data_dir=data_dir, token=token)


@pytest.fixture
def loop_spy(monkeypatch: pytest.MonkeyPatch) -> list[PublishLoop]:
    """Records every ``PublishLoop`` built (the original constructor still runs)."""
    built: list[PublishLoop] = []
    original = PublishLoop.__init__

    def spy(self: PublishLoop, *args: Any, **kwargs: Any) -> None:
        built.append(self)
        original(self, *args, **kwargs)

    monkeypatch.setattr(PublishLoop, "__init__", spy)
    return built


class _RecorderHandler(http.server.BaseHTTPRequestHandler):
    server: _Recorder

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.record(self.command, self.path, dict(self.headers.items()), body)
        status, payload = self.server.answer(self.command, self.path, body)
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return


class _Recorder(http.server.ThreadingHTTPServer):
    """Local HTTP cloud on 127.0.0.1: records every request; a fake SPEC-004 batch endpoint."""

    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _RecorderHandler)
        self.lock = threading.Lock()
        self.seen: list[tuple[str, str, dict[str, str], bytes]] = []
        self.stored: dict[str, dict[str, Any]] = {}

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def record(self, method: str, path: str, headers: dict[str, str], body: bytes) -> None:
        with self.lock:
            self.seen.append((method, path, headers, body))

    def answer(self, method: str, path: str, body: bytes) -> tuple[int, Any]:
        if method == "GET" and path == HEALTH_PATH:
            return 200, {"status": "ok", "db": "ok"}
        if method == "POST" and path == BATCH_PATH:
            results = []
            with self.lock:
                for item in json.loads(body)["items"]:
                    iid = item["inspection_id"]
                    status = "duplicate" if iid in self.stored else "created"
                    self.stored.setdefault(iid, item)
                    results.append({"inspection_id": iid, "status": status})
            return 200, {"results": results}
        return 404, {"detail": "Not Found"}


@pytest.fixture
def local_cloud() -> Iterator[_Recorder]:
    server = _Recorder()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# =========================================================================== CA-01


def test_ca01_put_is_idempotent_by_inspection_id(rig: Rig) -> None:
    item = inspection()
    for _ in range(3):
        rig.outbox.put(item)
    assert rig.outbox.stats().pending == 1
    rows = rig.rows()
    assert len(rows) == 1
    assert rows[0]["inspection_id"] == str(item.inspection_id)
    assert rows[0]["status"] == "pending"
    assert rows[0]["attempts"] == 0


def test_extra_schema_dates_and_payload_follow_section_4_1(rig: Rig) -> None:
    item = rig.put()
    con = sqlite3.connect(rig.path)
    try:
        columns = [r[1] for r in con.execute("PRAGMA table_info(outbox)")]
        indexes = {r[1] for r in con.execute("PRAGMA index_list(outbox)")}
        journal = con.execute("PRAGMA journal_mode").fetchone()[0]
        index_cols = [r[2] for r in con.execute("PRAGMA index_info(outbox_due)")]
        pk = [r[1] for r in con.execute("PRAGMA table_info(outbox)") if r[5]]
    finally:
        con.close()
    assert columns == OUTBOX_COLUMNS
    assert pk == ["inspection_id"]
    assert "outbox_due" in indexes
    assert index_cols == ["status", "next_attempt_at", "created_at"]
    assert journal.lower() == "wal"
    row = rig.rows()[0]
    assert ts(row["created_at"]) == T0
    assert ts(row["next_attempt_at"]) <= T0
    assert row["sent_at"] is None and row["last_error"] is None
    assert json.loads(row["payload"]) == json.loads(item.model_dump_json())


def test_extra_put_never_changes_an_existing_row_r05(rig: Rig) -> None:
    first = rig.put()
    altered = first.model_copy(update={"lot_id": "L-OTHER", "latency_ms": 999})
    rig.outbox.put(altered)
    assert json.loads(rig.rows()[0]["payload"])["lot_id"] == "L-001"
    rig.loop.run_once()
    before = rig.rows()
    assert before[0]["status"] == "sent"
    rig.clock.advance(5)
    rig.outbox.put(first)
    rig.outbox.put(altered)
    assert rig.rows() == before  # status `sent` (and every column) untouched
    rig.clock.advance(120)
    rig.loop.run_once()
    assert len(rig.cloud.batch_requests()) == 1  # never re-sent
    assert rig.cloud.stored[str(first.inspection_id)]["lot_id"] == "L-001"


# =========================================================================== CA-02


def test_ca02_150_items_go_in_two_batches_in_created_at_order(rig: Rig) -> None:
    order = list(range(150))
    random.Random(9).shuffle(order)
    items: list[tuple[int, InspectionCreate]] = []
    for offset in order:  # created_at is not the insertion order
        rig.clock.set(T0 + timedelta(seconds=offset))
        items.append((offset, rig.put()))
    rig.clock.set(T0 + timedelta(seconds=200))
    expected = [str(item.inspection_id) for _, item in sorted(items, key=lambda p: p[0])]

    rig.loop.run_once()
    rig.loop.run_once()

    batches = rig.cloud.batch_requests()
    assert len(batches) == 2
    assert len(rig.cloud.requests) == 2  # no other request
    sent = [request_ids(r) for r in batches]
    assert [len(s) for s in sent] == [100, 50]
    assert sent[0] + sent[1] == expected
    stats = rig.outbox.stats()
    assert stats.pending == 0
    assert stats.connectivity == "online"
    assert stats.last_success_at is not None
    rows = rig.rows()
    assert len(rows) == 150
    assert all(r["status"] == "sent" for r in rows)
    assert all(r["sent_at"] is not None and ts(r["sent_at"]) for r in rows)


# =========================================================================== CA-03


def test_ca03_duplicate_answers_also_mark_items_sent(rig: Rig) -> None:
    items = [rig.put() for _ in range(5)]
    for item in items[:3]:  # already stored in the cloud (e.g. a lost response before)
        rig.cloud.stored[str(item.inspection_id)] = json.loads(item.model_dump_json())
    rig.loop.run_once()
    answers = dict(rig.cloud.answers)
    assert [answers[str(i.inspection_id)] for i in items] == ["duplicate"] * 3 + ["created"] * 2
    rows = {r["inspection_id"]: r for r in rig.rows()}
    assert all(rows[str(i.inspection_id)]["status"] == "sent" for i in items)
    assert rig.outbox.stats().pending == 0
    assert rig.outbox.stats().connectivity == "online"


# =========================================================================== CA-04


def _connect_error(request: httpx.Request) -> Exception:
    return httpx.ConnectError("connection refused", request=request)


def _timeout(request: httpx.Request) -> Exception:
    return httpx.ReadTimeout("timed out", request=request)


def _unavailable(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, json={"detail": "Service Unavailable"})


@pytest.mark.parametrize(
    "failure", [_connect_error, _timeout, _unavailable], ids=["connect", "timeout", "503"]
)
def test_ca04_transient_failure_schedules_a_retry(rig: Rig, failure: Failure) -> None:
    items = [rig.put() for _ in range(3)]
    rig.cloud.fail = failure
    t = T0 + timedelta(seconds=10)
    rig.clock.set(t)
    rig.loop.run_once()
    n_requests = len(rig.cloud.requests)
    assert n_requests >= 1
    rows = rig.rows()
    assert len(rows) == len(items)
    for row in rows:
        assert row["status"] == "pending"
        assert row["attempts"] == 1
        due = ts(row["next_attempt_at"])
        assert t + timedelta(seconds=0.8) <= due <= t + timedelta(seconds=1.2)
        assert row["last_error"]
    assert rig.outbox.stats().connectivity == "offline"
    assert rig.outbox.stats().pending == 3

    rig.clock.advance(0.7)  # before the earliest next_attempt_at
    rig.loop.run_once()
    assert len(rig.cloud.requests) == n_requests


# =========================================================================== CA-05


def test_ca05_backoff_doubles_with_20_percent_jitter_capped_at_60(rig: Rig) -> None:
    item = rig.put()
    rig.cloud.fail = _connect_error
    factors: list[float] = []
    for n in range(10):  # attempts 0 -> 10
        now = rig.clock()
        rig.loop.run_once()
        row = rig.rows()[0]
        assert row["attempts"] == n + 1
        delay = (ts(row["next_attempt_at"]) - now).total_seconds()
        low, high = min(60.0, 0.8 * 2**n), min(60.0, 1.2 * 2**n)
        assert low - 1e-6 <= delay <= high + 1e-6, (n, delay)
        assert delay <= 60.0
        if 1.2 * 2**n <= 60:
            factors.append(delay / 2**n)
        rig.clock.set(ts(row["next_attempt_at"]))
    assert rig.rows()[0]["attempts"] == 10
    assert rig.rows()[0]["inspection_id"] == str(item.inspection_id)
    assert len(set(round(f, 6) for f in factors)) > 1  # jitter really varies


# =========================================================================== CA-06


def test_ca06_bisection_isolates_the_rejected_item(rig: Rig) -> None:
    items = [rig.put() for _ in range(8)]
    bad = str(items[5].inspection_id)
    rig.cloud.reject_ids = {bad}
    rig.drain()
    rows = {r["inspection_id"]: r for r in rig.rows()}
    assert sum(r["status"] == "sent" for r in rows.values()) == 7
    assert rows[bad]["status"] == "dead"
    assert rows[bad]["last_error"]
    assert rig.outbox.stats().dead == 1
    assert rig.outbox.stats().pending == 0
    assert set(rig.cloud.stored) == {str(i.inspection_id) for i in items} - {bad}

    before = len(rig.cloud.batch_requests())
    for _ in range(5):
        rig.clock.advance(120)
        rig.loop.run_once()
    after = rig.cloud.batch_requests()[before:]
    assert all(bad not in request_ids(r) for r in after)
    assert rows[bad]["status"] == rig.rows()[5]["status"] == "dead"


# =========================================================================== CA-07


@pytest.mark.parametrize("status", [401, 403])
def test_ca07_auth_error_pauses_publishing(
    edge_env: EdgeEnv, tmp_path: Path, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    caplog.set_level(logging.DEBUG)
    r = make_rig(tmp_path)
    try:
        for _ in range(3):
            r.put()
        r.cloud.fail = lambda request: httpx.Response(status, json={"detail": "Invalid API key"})
        for _ in range(5):
            r.loop.run_once()
            r.clock.advance(30)  # 150 s in total: even the health check must stay quiet
        assert len(r.cloud.requests) == 1
        assert r.cloud.requests[0].headers["x-api-key"] == r.key
        assert all(row["attempts"] == 0 for row in r.rows())
        assert all(row["status"] == "pending" for row in r.rows())
        assert r.outbox.stats().connectivity == "auth_error"

        app = create_app(EdgeSettings(), None, r.outbox)

        async def go() -> tuple[httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
            async with httpx.AsyncClient(
                transport=transport, base_url=f"http://127.0.0.1:{PORT}"
            ) as c:
                status_resp = await c.get("/api/status", headers={SESSION_HEADER: edge_env.token})
                console_resp = await c.get("/")
                return status_resp, console_resp

        status_resp, console_resp = asyncio.run(go())
        assert status_resp.status_code == 200
        assert status_resp.json()["sink"]["connectivity"] == "auth_error"
        assert status_resp.json()["sink"]["pending"] == 3
        assert console_resp.status_code == 200
        assert "auth_error" in console_resp.text

        text = log_text(caplog)
        assert r.key not in text
        assert all(r.key not in (row["last_error"] or "") for row in r.rows())
        # §4.3: one single error log asking to check DEVICE_API_KEY
        errors = [
            rec
            for rec in caplog.records
            if rec.levelno >= logging.ERROR and "DEVICE_API_KEY" in rec.getMessage()
        ]
        assert len(errors) == 1
    finally:
        r.outbox.close()


# =========================================================================== CA-08


def test_ca08_outage_and_lost_response_deliver_exactly_once(rig: Rig) -> None:
    started = time.monotonic()
    outage = (T0 + timedelta(seconds=30), T0 + timedelta(seconds=150))
    lost = {"armed": True, "outage_hits": 0}

    def failure(request: httpx.Request) -> Exception | None:
        now = rig.clock()
        if outage[0] <= now < outage[1]:
            lost["outage_hits"] += 1
            return httpx.ConnectError("network is unreachable", request=request)
        if now >= outage[1] and lost["armed"] and request.url.path == BATCH_PATH:
            lost["armed"] = False
            rig.cloud.lose_next = True
        return None

    rig.cloud.fail = failure
    cycles = 0
    second = 0
    while True:
        if second < 200:
            rig.put()
        if second % 2 == 0:
            rig.loop.run_once()
            cycles += 1
            if second >= 200 and rig.outbox.stats().pending == 0:
                break
        assert cycles <= 2000, "did not drain in 2000 cycles"
        rig.clock.advance(1)
        second += 1

    put_ids = {str(i.inspection_id) for i in rig.puts}
    assert len(put_ids) == 200
    assert set(rig.cloud.stored) == put_ids
    assert len(rig.cloud.writes) == 200
    assert len(set(rig.cloud.writes)) == 200  # zero duplicate writes
    assert lost["armed"] is False  # the lost response really happened
    assert any(status == "duplicate" for _, status in rig.cloud.answers)
    stats = rig.outbox.stats()
    assert stats.dead == 0 and stats.pending == 0
    assert lost["outage_hits"] > 0  # the outage really refused requests
    assert time.monotonic() - started < 30


# =========================================================================== CA-09

CHILD = """
import os, signal, sys, uuid, hashlib
from datetime import UTC, datetime
from pathlib import Path
from qc_contracts import Grade, InspectionCreate, ObjectType, Source
from qc_edge.outbox import SqliteOutbox

box = SqliteOutbox(Path(sys.argv[1]))
ids = []
for i in range(20):
    item = InspectionCreate(
        inspection_id=uuid.uuid4(), device_id="edge-01", lot_id="L-KILL",
        inspected_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC), object_type=ObjectType.NUT,
        grade=Grade.FAIR, grade_score=2.0, type_confidence=0.95, grade_confidence=0.7,
        needs_review=False, model_version="partqc-mnv3-v1",
        model_sha256=hashlib.sha256(b"kill").hexdigest(), latency_ms=10, source=Source.LIVE)
    box.put(item)
    ids.append(str(item.inspection_id))
sys.stdout.write("\\n".join(ids) + "\\n")
sys.stdout.flush()
os.kill(os.getpid(), signal.SIGKILL)
"""


def test_ca09_committed_puts_survive_sigkill(tmp_path: Path) -> None:
    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    db = tmp_path / "kill" / "outbox.sqlite3"
    db.parent.mkdir()
    proc = subprocess.run(
        [sys.executable, str(script), str(db)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == -signal.SIGKILL, proc.stderr
    ids = proc.stdout.split()
    assert len(ids) == 20

    clock = ManualClock(datetime.now(UTC) + timedelta(seconds=5))
    connectivity = ConnectivityState()
    outbox = SqliteOutbox(db, clock=clock, connectivity=connectivity)
    try:
        cloud = FakeCloud()
        publisher = HttpPublisher(
            "https://cloud.test", new_key(), transport=httpx.MockTransport(cloud)
        )
        loop = PublishLoop(outbox, publisher, connectivity, clock=clock, rng=random.Random(0))
        assert outbox.stats().pending == 20
        for _ in range(10):
            if outbox.stats().pending == 0:
                break
            loop.run_once()
            clock.advance(2)
        assert outbox.stats().pending == 0
        assert sorted(cloud.writes) == sorted(ids)
        assert len(cloud.writes) == 20
    finally:
        outbox.close()


# =========================================================================== CA-10


def test_ca10_only_contract_json_goes_to_the_two_cloud_routes(rig: Rig) -> None:
    items = [rig.put() for _ in range(6)]
    rig.cloud.reject_ids = {str(items[2].inspection_id)}  # bisection requests too
    rig.drain()
    rig.clock.advance(61)
    rig.loop.run_once()  # idle: health check
    rig.cloud.fail = _connect_error
    rig.put()
    rig.loop.run_once()  # failing request too

    assert rig.cloud.health_requests(), "the health check should have happened"
    assert len(rig.cloud.batch_requests()) >= 3
    for request in rig.cloud.requests:
        route = (request.method, request.url.path)
        assert route in {("POST", BATCH_PATH), ("GET", HEALTH_PATH)}, route
        assert request.url.host == "cloud.test"
        if route[0] == "POST":
            assert request.headers["x-api-key"] == rig.key
            ctype = request.headers["content-type"]
            assert ctype.split(";")[0].strip() == "application/json"
            assert "multipart" not in ctype
            body = json.loads(request.read())
            assert set(body) == {"items"}
            assert 1 <= len(body["items"]) <= 100
            for item in body["items"]:
                assert set(item) == CONTRACT_FIELDS
                for value in item.values():
                    assert not isinstance(value, (dict, list))
                    assert not (isinstance(value, str) and len(value) > 64)
            assert len(request.read()) < 600 * len(body["items"])
        else:
            assert request.read() == b""


# =========================================================================== CA-11


def test_ca11_plain_http_cloud_url_is_refused(
    edge_env: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    key = new_key()
    monkeypatch.setenv("DEVICE_API_KEY", key)
    monkeypatch.setenv("CLOUD_API_URL", "http://api.exemplo.org")
    spy = UvicornRunner()
    monkeypatch.setattr(uvicorn, "run", spy)
    assert call_main([]) == 2
    out = capsys.readouterr()
    text = "\n".join([log_text(caplog), out.out, out.err])
    assert "CLOUD_API_URL" in text
    assert spy.calls == []
    assert key not in text


def test_ca11_loopback_http_cloud_url_starts(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVICE_API_KEY", new_key())
    monkeypatch.setenv("CLOUD_API_URL", "http://127.0.0.1:9000")
    spy = UvicornRunner()
    monkeypatch.setattr(uvicorn, "run", spy)
    assert call_main([]) == 0
    assert len(spy.calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://api.exemplo.org",
        "https://partqc.exemplo.org/",
        "http://localhost:9000",
        "http://127.0.0.1",
    ],
)
def test_extra_cloud_url_accepted(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("DEVICE_API_KEY", new_key())
    monkeypatch.setenv("CLOUD_API_URL", url)
    spy = UvicornRunner()
    monkeypatch.setattr(uvicorn, "run", spy)
    assert call_main([]) == 0
    assert len(spy.calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost.exemplo.org",
        "http://127.0.0.1.exemplo.org",
        "http://exemplo.org/127.0.0.1",
        "http://192.168.0.10:8001",
        "http://127.0.0.2:9000",
        "ftp://api.exemplo.org",
        "api.exemplo.org",
        "https://",
        "https://user:pw@api.exemplo.org",
        "https://api.exemplo.org/?next=x",
    ],
)
@pytest.mark.parametrize("stub", [False, True], ids=["no-flag", "stub-model"])
def test_extra_cloud_url_refused_with_or_without_stub(
    edge_env: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    url: str,
    stub: bool,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("DEVICE_API_KEY", new_key())
    monkeypatch.setenv("CLOUD_API_URL", url)
    spy = UvicornRunner()
    monkeypatch.setattr(uvicorn, "run", spy)
    assert call_main(["--stub-model"] if stub else []) == 2
    out = capsys.readouterr()
    text = "\n".join([log_text(caplog), out.out, out.err])
    assert "CLOUD_API_URL" in text
    assert spy.calls == []
    if "user:pw" in url:
        assert "user:pw" not in text  # a credential in the URL is never echoed


def test_extra_empty_cloud_url_means_not_set(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch, loop_spy: list[PublishLoop]
) -> None:
    """``.env.example``: an empty ``CLOUD_API_URL`` means nothing is sent (no loop)."""
    monkeypatch.setenv("DEVICE_API_KEY", new_key())
    monkeypatch.setenv("CLOUD_API_URL", "")
    spy = UvicornRunner()
    monkeypatch.setattr(uvicorn, "run", spy)
    assert call_main([]) == 0
    assert len(spy.calls) == 1
    assert loop_spy == []


# =========================================================================== CA-12


def _no_flag_scenario(env: EdgeEnv) -> Callable[[Any], dict[str, Any]]:
    def scenario(app: Any) -> dict[str, Any]:
        with TestClient(app) as client:
            responses = [capture(client, env.token) for _ in range(3)]
            status = client.get("/api/status", headers={SESSION_HEADER: env.token})
            time.sleep(0.5)  # a loop (if any) would have done its first cycle by now
        return {"responses": responses, "status": status}

    return scenario


@pytest.mark.parametrize("missing", ["DEVICE_API_KEY", "CLOUD_API_URL"])
def test_ca12_without_key_or_url_the_outbox_fills_and_nothing_is_sent(
    edge_env: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    local_cloud: _Recorder,
    loop_spy: list[PublishLoop],
    missing: str,
) -> None:
    monkeypatch.setenv("MODEL_DIR", str(make_model_dir(edge_env.tmp / "models")))
    if missing == "DEVICE_API_KEY":
        monkeypatch.setenv("CLOUD_API_URL", local_cloud.url)
    else:
        monkeypatch.setenv("DEVICE_API_KEY", new_key())
    runner = UvicornRunner(_no_flag_scenario(edge_env))
    monkeypatch.setattr(uvicorn, "run", runner)
    assert call_main([]) == 0
    runner.check()
    result = runner.result
    assert [r.status_code for r in result["responses"]] == [200, 200, 200]
    sink = result["status"].json()["sink"]
    assert sink["pending"] == 3
    assert sink["connectivity"] == "disabled"

    path = edge_env.data_dir / "outbox.sqlite3"
    assert path.is_file()
    rows = read_rows(path)
    assert len(rows) == 3
    assert all(r["status"] == "pending" for r in rows)
    ids = {r.json()["inspection"]["inspection_id"] for r in result["responses"]}
    assert {r["inspection_id"] for r in rows} == ids
    assert all(json.loads(r["payload"])["model_version"] == "partqc-acc9-v1" for r in rows)

    reopened = SqliteOutbox(path)
    try:
        stats = reopened.stats()
        assert stats.pending == 3
        assert stats.connectivity == "disabled"
    finally:
        reopened.close()
    assert loop_spy == []
    assert local_cloud.seen == []


# =========================================================================== CA-13


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (None, "online"),
        (_unavailable, "offline"),
        (_connect_error, "offline"),
        (_timeout, "offline"),
    ],
    ids=["200", "503", "connect", "timeout"],
)
def test_ca13_idle_health_check_after_61_seconds(
    rig: Rig, failure: Failure | None, expected: str
) -> None:
    rig.cloud.fail = failure
    rig.clock.advance(61)
    rig.loop.run_once()
    assert len(rig.cloud.requests) == 1
    request = rig.cloud.requests[0]
    assert (request.method, request.url.path) == ("GET", HEALTH_PATH)
    assert rig.outbox.stats().connectivity == expected


def test_extra_health_check_turns_offline_into_online(rig: Rig) -> None:
    rig.cloud.fail = _connect_error
    rig.clock.advance(61)
    rig.loop.run_once()
    assert rig.outbox.stats().connectivity == "offline"
    rig.cloud.fail = None
    rig.clock.advance(61)
    rig.loop.run_once()
    assert rig.outbox.stats().connectivity == "online"
    assert len(rig.cloud.health_requests()) == 2


# =========================================================================== CA-14


def test_ca14_lifespan_stops_the_thread_and_keeps_sqlite_consistent(
    edge_env: EdgeEnv, tmp_path: Path
) -> None:
    path = tmp_path / "life" / "outbox.sqlite3"
    path.parent.mkdir()
    connectivity = ConnectivityState()
    outbox = SqliteOutbox(path, connectivity=connectivity)
    cloud = FakeCloud()
    publisher = HttpPublisher("https://cloud.test", new_key(), transport=httpx.MockTransport(cloud))
    loop = PublishLoop(outbox, publisher, connectivity, interval_s=0.05)
    first = [inspection() for _ in range(30)]
    for item in first:
        outbox.put(item)
    app = create_app(EdgeSettings(), None, outbox, background=[loop])
    before = set(threading.enumerate())
    try:
        with TestClient(app):
            started = set(threading.enumerate()) - before
            assert started, "the PublishLoop thread did not start"
            deadline = time.monotonic() + 2
            while len(cloud.stored) < 30 and time.monotonic() < deadline:
                time.sleep(0.02)
            for _ in range(20):  # still writing while the lifespan ends
                outbox.put(inspection())
            t_exit = time.monotonic()
        elapsed = time.monotonic() - t_exit
        assert elapsed <= 10
        assert all(not t.is_alive() for t in started)
        assert {str(i.inspection_id) for i in first} <= set(cloud.stored)
        assert len(cloud.writes) == len(set(cloud.writes))
    finally:
        outbox.close()
    con = sqlite3.connect(path)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("SELECT count(*) FROM outbox").fetchone()[0] == 50
    finally:
        con.close()


# =========================================================================== CA-15


def test_ca15_concurrent_puts_while_run_once(rig: Rig) -> None:
    errors: list[BaseException] = []
    done = threading.Event()
    ids: list[str] = []
    ids_lock = threading.Lock()

    def writer() -> None:
        try:
            for _ in range(50):
                item = inspection()
                rig.outbox.put(item)
                with ids_lock:
                    ids.append(str(item.inspection_id))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def publisher() -> None:
        try:
            while not done.is_set():
                rig.loop.run_once()
                rig.clock.advance(0.01)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    pub = threading.Thread(target=publisher)
    writers = [threading.Thread(target=writer) for _ in range(4)]
    pub.start()
    for w in writers:
        w.start()
    for w in writers:
        w.join(timeout=60)
    done.set()
    pub.join(timeout=60)
    assert errors == []
    rows = rig.rows()
    assert len(rows) == 200
    assert {r["inspection_id"] for r in rows} == set(ids)

    rig.drain()
    assert set(rig.cloud.stored) == set(ids)
    assert len(rig.cloud.writes) == 200


# =========================================================================== CA-16


def test_ca16_outbox_coverage_is_at_least_80_percent(tmp_path: Path) -> None:
    """pytest --cov=qc_edge.outbox on two explicit files (the author's outbox tests and this
    file), deselecting this test: no suite inside the suite (architecture.md §10)."""
    files = [EDGE_ROOT / "tests" / "test_outbox.py", Path(__file__)]
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--cov=qc_edge.outbox",
        "--cov-report=term",
        "-k",
        "not test_ca16",
        *[str(f) for f in files],
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    match = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", proc.stdout, re.MULTILINE)
    assert match, proc.stdout[-3000:]
    assert int(match.group(1)) >= 80


# =========================================================================== CA-18


def _fastapi_422(marker: str) -> Callable[[], httpx.Response]:
    def build() -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "detail": [
                    {
                        "type": "less_than_equal",
                        "loc": ["body", "items", 2, "type_confidence"],
                        "msg": "Input should be less than or equal to 1",
                        "input": marker,
                        "ctx": {"le": 1.0},
                    },
                    {
                        "type": "string_pattern_mismatch",
                        "loc": ["body", "items", 2, "lot_id"],
                        "msg": "String should match pattern",
                        "input": {"echo": marker, "nested": [marker]},
                    },
                ]
            },
        )

    return build


def _string_422(marker: str) -> Callable[[], httpx.Response]:
    return lambda: httpx.Response(422, json={"detail": "Value cannot be stored"})


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (_fastapi_422, "HTTP 422: 2 validation errors"),
        (_string_422, "HTTP 422: Value cannot be stored"),
    ],
    ids=["fastapi-default", "string-detail"],
)
def test_ca18_refusal_body_never_reaches_logs_or_last_error(
    rig: Rig,
    caplog: pytest.LogCaptureFixture,
    body: Callable[[str], Callable[[], httpx.Response]],
    expected: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = new_marker()
    items = [rig.put() for _ in range(4)]
    assert all(marker not in i.model_dump_json() for i in items)
    bad = str(items[2].inspection_id)
    rig.cloud.reject_ids = {bad}
    rig.cloud.reject_response = body(marker)
    rig.drain()
    rows = {r["inspection_id"]: r for r in rig.rows()}
    assert rows[bad]["status"] == "dead"
    assert rows[bad]["last_error"] == expected
    assert [rows[str(i.inspection_id)]["status"] for i in items] == ["sent", "sent", "dead", "sent"]
    assert marker not in log_text(caplog)
    assert all(marker not in (r["last_error"] or "") for r in rows.values())
    assert rig.key not in log_text(caplog)


def test_extra_rejected_error_carries_only_the_summary(rig: Rig) -> None:
    marker = new_marker()
    items = [inspection() for _ in range(4)]
    rig.cloud.reject_ids = {str(items[2].inspection_id)}
    rig.cloud.reject_response = _fastapi_422(marker)
    with pytest.raises(PublishRejectedError) as excinfo:
        rig.publisher.publish_batch(items)
    exc = excinfo.value
    assert exc.detail == "HTTP 422: 2 validation errors"
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    for e in chain:
        assert marker not in str(e)
        assert marker not in repr(e)
        assert marker not in repr(e.args)
        assert marker not in repr(getattr(e, "__dict__", {}))


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (413, b'{"detail": "Request Entity Too Large"}', "HTTP 413: Request Entity Too Large"),
        (413, b"<html>too large</html>", "HTTP 413"),
        (422, b"not json at all", "HTTP 422"),
        (422, b'{"error": "x"}', "HTTP 422"),
        (422, b'{"detail": 7}', "HTTP 422"),
        (422, b'{"detail": []}', "HTTP 422: 0 validation errors"),
        (422, b"[1, 2]", "HTTP 422"),
    ],
)
def test_extra_refusal_summary_formats(rig: Rig, status: int, body: bytes, expected: str) -> None:
    item = inspection()
    rig.cloud.fail = lambda request: httpx.Response(
        status, content=body, headers={"content-type": "application/json"}
    )
    with pytest.raises(PublishRejectedError) as excinfo:
        rig.publisher.publish_batch([item])
    assert excinfo.value.detail == expected


def test_extra_refusal_detail_is_cut_and_control_characters_replaced(rig: Rig) -> None:
    control = "\x00\x1b\n\r\t\x7f\x85"
    detail = "Valor inválido ✓ " + control + "x" * 400
    rig.cloud.fail = lambda request: httpx.Response(422, json={"detail": detail})
    with pytest.raises(PublishRejectedError) as excinfo:
        rig.publisher.publish_batch([inspection()])
    got = excinfo.value.detail
    expected_text = "".join("?" if unicodedata.category(ch) == "Cc" else ch for ch in detail[:200])
    assert got == "HTTP 422: " + expected_text
    assert not any(unicodedata.category(ch) == "Cc" for ch in got)


# =========================================================================== CA-19


def _stub_scenario(env: EdgeEnv) -> Callable[[Any], dict[str, Any]]:
    def scenario(app: Any) -> dict[str, Any]:
        with TestClient(app) as client:
            responses = [capture(client, env.token) for _ in range(3)]
            status = client.get("/api/status", headers={SESSION_HEADER: env.token})
            time.sleep(0.5)  # a loop (if any) would have done its first cycle by now
        return {"responses": responses, "status": status}

    return scenario


def test_ca19_stub_model_keeps_inspections_in_memory_only(
    edge_env: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    local_cloud: _Recorder,
    loop_spy: list[PublishLoop],
) -> None:
    caplog.set_level(logging.DEBUG)
    path = edge_env.tmp / "operation" / "outbox.sqlite3"
    path.parent.mkdir()
    original = SqliteOutbox(path)
    previous = [inspection(model_version=REAL_VERSION) for _ in range(2)]
    for item in previous:
        original.put(item)
    original.close()
    snapshot = raw_rows(path)
    assert len(snapshot) == 2

    key = new_key()
    monkeypatch.setenv("OUTBOX_PATH", str(path))
    monkeypatch.setenv("DEVICE_API_KEY", key)
    monkeypatch.setenv("CLOUD_API_URL", local_cloud.url)
    monkeypatch.delenv("MODEL_DIR", raising=False)
    runner = UvicornRunner(_stub_scenario(edge_env))
    monkeypatch.setattr(uvicorn, "run", runner)
    assert call_main(["--stub-model"]) == 0
    runner.check()
    result = runner.result

    # 1. three 200 answers from the stub
    assert [r.status_code for r in result["responses"]] == [200, 200, 200]
    assert all(r.json()["inspection"]["model_version"] == STUB_VERSION for r in result["responses"])
    # 2. status
    sink = result["status"].json()["sink"]
    assert sink["pending"] == 3
    assert sink["dead"] == 0
    assert sink["connectivity"] == "disabled"
    # 3. nothing left for the cloud
    assert local_cloud.seen == []
    assert loop_spy == []
    # 4. the file is untouched
    assert raw_rows(path) == snapshot
    assert all(STUB_VERSION not in row[1] for row in raw_rows(path))
    # 5. warning with --stub-model, no key anywhere
    warnings = [
        rec
        for rec in caplog.records
        if rec.levelno == logging.WARNING and "--stub-model" in rec.getMessage()
    ]
    assert warnings
    assert key not in log_text(caplog)
    # 6. a later publication sends only the 2 original ids
    connectivity = ConnectivityState()
    reopened = SqliteOutbox(path, connectivity=connectivity)
    try:
        cloud = FakeCloud()
        publisher = HttpPublisher(
            "https://cloud.test", new_key(), transport=httpx.MockTransport(cloud)
        )
        loop = PublishLoop(reopened, publisher, connectivity, rng=random.Random(0))
        for _ in range(10):
            if reopened.stats().pending == 0:
                break
            loop.run_once()
        assert reopened.stats().pending == 0
        assert sorted(cloud.stored) == sorted(str(i.inspection_id) for i in previous)
        assert all(item["model_version"] != STUB_VERSION for item in cloud.stored.values())
        assert all(STUB_VERSION.encode() not in body for body in cloud.bodies)
    finally:
        reopened.close()


def test_ca19_stub_model_never_creates_outbox_path(
    edge_env: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    local_cloud: _Recorder,
) -> None:
    missing_dir = edge_env.tmp / "sem-outbox"
    monkeypatch.setenv("OUTBOX_PATH", str(missing_dir / "outbox.sqlite3"))
    monkeypatch.setenv("DEVICE_API_KEY", new_key())
    monkeypatch.setenv("CLOUD_API_URL", local_cloud.url)
    runner = UvicornRunner(_stub_scenario(edge_env))
    monkeypatch.setattr(uvicorn, "run", runner)
    assert call_main(["--stub-model"]) == 0
    runner.check()
    assert [r.status_code for r in runner.result["responses"]] == [200, 200, 200]
    assert not (missing_dir / "outbox.sqlite3").exists()
    assert not missing_dir.exists()
    assert not (edge_env.data_dir / "outbox.sqlite3").exists()
    assert local_cloud.seen == []


def test_extra_stub_model_without_key_or_url_writes_no_outbox(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = UvicornRunner(_stub_scenario(edge_env))
    monkeypatch.setattr(uvicorn, "run", runner)
    assert call_main(["--stub-model"]) == 0
    runner.check()
    assert [r.status_code for r in runner.result["responses"]] == [200, 200, 200]
    assert runner.result["status"].json()["sink"]["connectivity"] == "disabled"
    assert not (edge_env.data_dir / "outbox.sqlite3").exists()


# =========================================================================== extras: §4.4


def test_extra_cli_with_key_and_url_publishes_over_real_http(
    edge_env: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    local_cloud: _Recorder,
    loop_spy: list[PublishLoop],
) -> None:
    """§4.4 first row, end to end: outbox + PublishLoop + HttpPublisher over a real socket."""
    caplog.set_level(logging.DEBUG)
    key = new_key()
    monkeypatch.setenv("MODEL_DIR", str(make_model_dir(edge_env.tmp / "models")))
    monkeypatch.setenv("DEVICE_API_KEY", key)
    monkeypatch.setenv("CLOUD_API_URL", local_cloud.url + "/")

    def scenario(app: Any) -> dict[str, Any]:
        with TestClient(app) as client:
            responses = [capture(client, edge_env.token) for _ in range(3)]
            deadline = time.monotonic() + 8
            status = None
            while time.monotonic() < deadline:
                status = client.get("/api/status", headers={SESSION_HEADER: edge_env.token})
                if status.json()["sink"]["pending"] == 0:
                    break
                time.sleep(0.1)
        return {"responses": responses, "status": status}

    runner = UvicornRunner(scenario)
    monkeypatch.setattr(uvicorn, "run", runner)
    assert call_main([]) == 0
    runner.check()
    sink = runner.result["status"].json()["sink"]
    assert sink["pending"] == 0
    assert sink["connectivity"] == "online"
    assert sink["last_success_at"]
    assert len(loop_spy) == 1
    ids = {r.json()["inspection"]["inspection_id"] for r in runner.result["responses"]}
    assert set(local_cloud.stored) == ids
    for method, path, headers, body in local_cloud.seen:
        assert (method, path) in {("POST", BATCH_PATH), ("GET", HEALTH_PATH)}
        lowered = {k.lower(): v for k, v in headers.items()}
        if method == "POST":
            assert lowered["x-api-key"] == key
            assert lowered["content-type"].startswith("application/json")
            for item in json.loads(body)["items"]:
                assert set(item) == CONTRACT_FIELDS
                assert item["source"] == "live"
    assert key not in log_text(caplog)
    rows = read_rows(edge_env.data_dir / "outbox.sqlite3")
    assert len(rows) == 3 and all(r["status"] == "sent" for r in rows)


def test_extra_corrupted_outbox_file_does_not_start(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = edge_env.tmp / "corrupt.sqlite3"
    path.write_bytes(b"this is not a sqlite database" * 100)
    monkeypatch.setenv("OUTBOX_PATH", str(path))
    spy = UvicornRunner()
    monkeypatch.setattr(uvicorn, "run", spy)
    code = call_main([])
    assert code != 0
    assert spy.calls == []


# =========================================================================== extras: security


def test_extra_key_never_reaches_last_error_even_in_transport_messages(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    rig.put()
    key = rig.key
    rig.cloud.fail = lambda request: httpx.ConnectError(
        f"proxy said: bad header X-API-Key={key} " + "y" * 900, request=request
    )
    rig.loop.run_once()
    row = rig.rows()[0]
    assert row["last_error"]
    assert key not in row["last_error"]
    assert len(row["last_error"]) <= 500
    assert key not in log_text(caplog)


def test_extra_redirect_is_not_followed(rig: Rig) -> None:
    """A 3xx to another host would carry X-API-Key there: it must not be followed."""
    rig.put()
    rig.cloud.fail = lambda request: (
        httpx.Response(307, headers={"location": "https://evil.test/collect"})
        if request.url.host == "cloud.test"
        else None
    )
    rig.loop.run_once()
    assert all(r.url.host == "cloud.test" for r in rig.cloud.requests)
    assert len(rig.cloud.requests) == 1
    row = rig.rows()[0]
    assert row["status"] == "pending" and row["attempts"] == 1
    assert rig.outbox.stats().connectivity == "offline"


@pytest.mark.parametrize("status", [400, 404, 405, 429, 500, 502, 504])
def test_extra_unexpected_statuses_are_transient(rig: Rig, status: int) -> None:
    rig.put()
    rig.cloud.fail = lambda request: httpx.Response(status, json={"detail": "x"})
    rig.loop.run_once()
    row = rig.rows()[0]
    assert row["status"] == "pending" and row["attempts"] == 1
    assert rig.outbox.stats().connectivity == "offline"
    with pytest.raises(PublishTransientError):
        rig.publisher.publish_batch([inspection()])


@pytest.mark.parametrize(
    "mangle",
    ["reversed", "short", "other-ids", "not-json", "bad-status", "empty"],
)
def test_extra_malformed_success_answer_is_transient(rig: Rig, mangle: str) -> None:
    """A 200 whose results do not match the batch never marks anything as sent (R-05)."""
    items = [rig.put() for _ in range(3)]

    def failure(request: httpx.Request) -> httpx.Response | None:
        if request.url.path != BATCH_PATH:
            return None
        ids = request_ids(request)
        results = [{"inspection_id": i, "status": "created"} for i in ids]
        if mangle == "reversed":
            return httpx.Response(200, json={"results": results[::-1]})
        if mangle == "short":
            return httpx.Response(200, json={"results": results[:-1]})
        if mangle == "other-ids":
            results[0]["inspection_id"] = str(uuid.uuid4())
            return httpx.Response(200, json={"results": results})
        if mangle == "not-json":
            return httpx.Response(200, content=b"<html>ok</html>")
        if mangle == "bad-status":
            results[1]["status"] = "stored"
            return httpx.Response(200, json={"results": results})
        return httpx.Response(200, json={})

    rig.cloud.fail = failure
    rig.loop.run_once()
    rows = rig.rows()
    assert all(r["status"] == "pending" and r["attempts"] == 1 for r in rows), rows
    assert rig.outbox.stats().pending == len(items)
    with pytest.raises(PublishTransientError):
        rig.publisher.publish_batch(items)


def test_extra_publish_result_and_errors_shape(rig: Rig) -> None:
    items = [inspection() for _ in range(2)]
    rig.cloud.stored[str(items[0].inspection_id)] = {}
    results = rig.publisher.publish_batch(items)
    assert results == [
        PublishResult(items[0].inspection_id, "duplicate"),
        PublishResult(items[1].inspection_id, "created"),
    ]
    rig.cloud.fail = lambda request: httpx.Response(401, json={"detail": "Invalid API key"})
    with pytest.raises(PublishAuthError):
        rig.publisher.publish_batch(items)


@pytest.mark.parametrize(("status", "healthy"), [(200, True), (204, False), (503, False)])
def test_extra_check_health_is_true_only_with_200(rig: Rig, status: int, healthy: bool) -> None:
    rig.cloud.health_status = status
    assert rig.publisher.check_health() is healthy


def test_extra_trailing_slash_base_url_builds_clean_paths(tmp_path: Path) -> None:
    cloud = FakeCloud()
    publisher = HttpPublisher(
        "https://cloud.test/", new_key(), transport=httpx.MockTransport(cloud)
    )
    publisher.publish_batch([inspection()])
    assert cloud.requests[0].url.path == BATCH_PATH


# =========================================================================== extras: loop


def test_extra_two_rejected_items_in_a_full_batch(rig: Rig) -> None:
    items = [rig.put() for _ in range(100)]
    bad = {str(items[17].inspection_id), str(items[80].inspection_id)}
    rig.cloud.reject_ids = bad
    rig.drain()
    rows = {r["inspection_id"]: r for r in rig.rows()}
    assert {i for i, r in rows.items() if r["status"] == "dead"} == bad
    assert sum(r["status"] == "sent" for r in rows.values()) == 98
    assert rig.outbox.stats().dead == 2
    assert len(rig.cloud.writes) == 98
    assert len(rig.cloud.batch_requests()) <= 40  # bisection, not item by item


def test_extra_unexpected_exception_never_kills_the_loop(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    rig.put()

    class Exploding:
        def publish_batch(self, items: Sequence[InspectionCreate]) -> list[PublishResult]:
            raise RuntimeError("boom")

        def check_health(self) -> bool:
            raise RuntimeError("boom")

    loop = PublishLoop(rig.outbox, Exploding(), rig.connectivity, clock=rig.clock)
    loop.run_once()  # must not raise
    row = rig.rows()[0]
    assert row["status"] == "pending" and row["attempts"] == 1 and row["last_error"]
    assert any(rec.exc_info for rec in caplog.records), "stack trace expected in the log"
    rig.clock.advance(61)
    loop.run_once()  # idle health check that raises: still no exception


def test_extra_auth_error_keeps_new_items_pending(rig: Rig) -> None:
    rig.put()
    rig.cloud.fail = lambda request: httpx.Response(401, json={"detail": "Invalid API key"})
    rig.loop.run_once()
    for _ in range(3):
        rig.put()
        rig.clock.advance(5)
        rig.loop.run_once()
    assert len(rig.cloud.requests) == 1
    assert rig.outbox.stats().pending == 4
    assert all(r["attempts"] == 0 for r in rig.rows())


def test_extra_source_is_published_as_stored_r06(rig: Rig) -> None:
    live = rig.put(inspection(source=Source.LIVE))
    simulated = rig.put(inspection(source=Source.SIMULATED))
    rig.loop.run_once()
    assert rig.cloud.stored[str(live.inspection_id)]["source"] == "live"
    assert rig.cloud.stored[str(simulated.inspection_id)]["source"] == "simulated"


def test_extra_put_after_close_is_a_sink_error(tmp_path: Path) -> None:
    box = SqliteOutbox(tmp_path / "closed.sqlite3")
    box.close()
    with pytest.raises(SinkError):
        box.put(inspection())


def test_extra_status_shows_last_success_after_publication(edge_env: EdgeEnv, rig: Rig) -> None:
    rig.put()
    rig.loop.run_once()
    app = create_app(EdgeSettings(), None, rig.outbox)
    with TestClient(app) as client:
        sink = client.get("/api/status", headers={SESSION_HEADER: edge_env.token}).json()["sink"]
    assert sink["connectivity"] == "online"
    assert sink["pending"] == 0 and sink["dead"] == 0
    assert datetime.fromisoformat(sink["last_success_at"].replace("Z", "+00:00")) == T0
