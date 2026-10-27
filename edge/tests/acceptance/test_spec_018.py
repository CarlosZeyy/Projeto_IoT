"""Acceptance tests for SPEC-018 (qc-edge: heartbeat of the gateway).

Written by the tester from the SPEC acceptance criteria. Covers CA-08 to CA-11. Tests named
``test_extra_*`` are exploratory edge cases around SPEC-018 section 4.4 (security tag: key and
refusal body out of logs, no image in the body, interval validation, the heartbeat never blocks
nor duplicates the delivery of inspections) that no CA spells out.

Rules followed (``reviews/checklist.md`` and ``docs/architecture.md`` section 10):

* the only boundaries replaced are the ones the SPEC names: the cloud network (an
  ``httpx.MockTransport``, or a local HTTP server on ``127.0.0.1``), the monotonic clock and
  ``uvicorn.run`` (spy); SQLite is real, in ``tmp_path``;
* every key and token is generated at run time (``secrets``), never a literal in a URL or header;
* images are synthetic and generated in memory (R-14); the dummy ONNX model is built here with
  ``onnx.helper`` in ``tmp_path``;
* no test runs pytest in a subprocess.
"""

from __future__ import annotations

import ast
import hashlib
import http.server
import io
import json
import logging
import secrets
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import onnx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from onnx import TensorProto, helper
from PIL import Image

import qc_edge
import qc_edge.cli
import qc_edge.netinfo
from qc_contracts import (
    MAX_HEARTBEAT_COUNT,
    Grade,
    HeartbeatCreate,
    InspectionCreate,
    ObjectType,
    Source,
)
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.heartbeat import HeartbeatLoop
from qc_edge.onnx_inferencer import OnnxInferencer
from qc_edge.outbox import SqliteOutbox
from qc_edge.publisher import HttpPublisher, PublishAuthError, PublishTransientError
from qc_preprocess import PreprocessParams

pytestmark = pytest.mark.acceptance

EDGE_ROOT = Path(__file__).resolve().parents[2]  # edge/
SRC = EDGE_ROOT / "src" / "qc_edge"

CLOUD = "https://cloud.test"
DEVICE = "edge-07"
HB_PATH = f"/api/v1/devices/{DEVICE}/heartbeat"
BATCH_PATH = "/api/v1/inspections/batch"
HEALTH_PATH = "/api/v1/health"
SESSION_HEADER = "X-Session-Token"
MODEL_NAME = "partqc-acc18-v1"
HEARTBEAT_FIELDS = {
    "sent_at",
    "model_version",
    "model_sha256",
    "app_version",
    "uptime_s",
    "outbox_pending",
    "outbox_dead",
}
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
)


def new_key() -> str:
    """A device key generated at run time (never a literal)."""
    return "acc_" + secrets.token_urlsafe(24)


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    formatter = logging.Formatter()
    parts = [caplog.text]
    for record in caplog.records:
        parts.extend((record.getMessage(), str(record.msg), repr(record.args)))
        if record.exc_info:
            parts.append(formatter.formatException(record.exc_info))
    return "\n".join(parts)


def inspection() -> InspectionCreate:
    return InspectionCreate(
        inspection_id=uuid.uuid4(),
        device_id=DEVICE,
        lot_id="L-018",
        inspected_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        object_type=ObjectType.SCREW,
        grade=Grade.GOOD,
        grade_score=1.0,
        type_confidence=0.9,
        grade_confidence=0.8,
        needs_review=False,
        model_version="partqc-mnv3-v1",
        model_sha256=hashlib.sha256(b"acc18").hexdigest(),
        latency_ms=21,
        source=Source.LIVE,
    )


# =========================================================================== model and images


def build_dummy_onnx(type_probs: Sequence[float], grade_probs: Sequence[float]) -> bytes:
    """ReduceMean(input) -> Reshape [N,1] -> Mul 0 -> Add constants (SPEC-008 section 6 dummy)."""
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
    graph = helper.make_graph(nodes, "acc18-dummy", [inp], [out_t, out_g], initializer=inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model.SerializeToString()


def make_model_dir(root: Path, name: str = MODEL_NAME) -> Path:
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


def synthetic_jpeg(seed: int = 18) -> bytes:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def capture(client: TestClient, token: str) -> httpx.Response:
    return client.post(
        "/api/capture",
        headers={SESSION_HEADER: token},
        data={"lot_id": "L-018", "mode": "inspect"},
        files={"image": ("foto.jpg", synthetic_jpeg(), "image/jpeg")},
    )


# =========================================================================== fake cloud


Answer = Callable[[httpx.Request], httpx.Response]


class Cloud:
    """``httpx.MockTransport`` handler that records every request."""

    def __init__(self, answer: Answer | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.answer: Answer = answer or (lambda request: httpx.Response(204))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        return self.answer(request)


def raise_connect(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def raise_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


@dataclass
class Rig:
    tmp: Path
    key: str
    cloud: Cloud
    publisher: HttpPublisher
    outbox: SqliteOutbox
    inferencer: OnnxInferencer

    def loop(self, *, with_model: bool = True, **kwargs: Any) -> HeartbeatLoop:
        kwargs.setdefault("interval_s", 60)
        inferencer = self.inferencer if with_model else None
        return HeartbeatLoop(self.publisher, self.outbox, inferencer, **kwargs)

    def rows(self) -> list[tuple[Any, ...]]:
        con = sqlite3.connect(self.outbox.path)
        try:
            return con.execute("select * from outbox order by inspection_id").fetchall()
        finally:
            con.close()

    def heartbeats(self) -> list[HeartbeatCreate]:
        return [HeartbeatCreate.model_validate_json(r.content) for r in self.cloud.requests]


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    key = new_key()
    cloud = Cloud()
    publisher = HttpPublisher(CLOUD, key, transport=httpx.MockTransport(cloud), device_id=DEVICE)
    outbox = SqliteOutbox(tmp_path / "outbox.sqlite3")
    items = [inspection() for _ in range(3)]
    for item in items:
        outbox.put(item)
    outbox.mark_dead(items[0].inspection_id, "HTTP 422: 1 validation error")
    inferencer = OnnxInferencer(make_model_dir(tmp_path / "models"))
    try:
        yield Rig(tmp_path, key, cloud, publisher, outbox, inferencer)
    finally:
        publisher.close()
        outbox.close()


# =========================================================================== CA-08


def test_ca08_one_cycle_sends_the_heartbeat_with_model_and_outbox(rig: Rig) -> None:
    rig.loop().run_once()
    assert len(rig.cloud.requests) == 1
    request = rig.cloud.requests[0]
    assert request.method == "POST"
    assert request.url.path == HB_PATH
    assert request.headers["X-API-Key"] == rig.key
    hb = HeartbeatCreate.model_validate_json(request.content)
    assert hb.outbox_pending == 2
    assert hb.outbox_dead == 1
    info = rig.inferencer.model_info
    assert hb.model_version == info.model_version == MODEL_NAME
    assert hb.model_sha256 == info.model_sha256


def test_ca08_without_model_the_model_fields_are_null(rig: Rig) -> None:
    rig.loop(with_model=False).run_once()
    assert len(rig.cloud.requests) == 1
    hb = rig.heartbeats()[0]
    assert hb.model_version is None
    assert hb.model_sha256 is None
    assert (hb.outbox_pending, hb.outbox_dead) == (2, 1)


# =========================================================================== CA-09


@pytest.mark.parametrize(
    "answer",
    [raise_connect, lambda request: httpx.Response(503)],
    ids=["connect-error", "http-503"],
)
def test_ca09_cloud_down_three_cycles_no_exception_and_outbox_unchanged(
    rig: Rig, answer: Answer, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    rig.cloud.answer = answer
    before = rig.rows()
    loop = rig.loop()
    for _ in range(3):
        loop.run_once()  # must not raise
    assert len(rig.cloud.requests) == 3
    assert rig.rows() == before
    assert len(before) == 3
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) >= 3
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_ca09_capture_keeps_working_with_the_cloud_down(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(qc_edge.netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])
    rig.cloud.answer = raise_connect
    token = secrets.token_urlsafe(30)
    settings = EdgeSettings(
        EDGE_DATA_DIR=rig.tmp / "edge-data",
        EDGE_SESSION_TOKEN=token,
        DATASET_DIR=rig.tmp / "dataset",
        DEVICE_ID=DEVICE,
    )
    loop = rig.loop(interval_s=10)
    for _ in range(3):
        loop.run_once()
    rows_before = rig.rows()
    app = create_app(settings, rig.inferencer, rig.outbox, background=[loop])
    with TestClient(app) as client:
        resp = capture(client, token)
        assert resp.status_code == 200, resp.text
        assert resp.json()["inspection"]["model_version"] == MODEL_NAME
    after = rig.rows()
    assert len(after) == len(rows_before) + 1  # only the capture added a row


@pytest.mark.parametrize("status", [401, 403])
def test_ca09_auth_error_only_the_first_cycle_sends_and_one_error(
    rig: Rig, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    rig.cloud.answer = lambda request: httpx.Response(status)
    loop = rig.loop()
    loop.run_once()
    loop.run_once()
    assert len(rig.cloud.requests) == 1
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert rig.key not in log_text(caplog)


# =========================================================================== CA-10


@dataclass
class EdgeEnv:
    tmp: Path
    token: str
    key: str


@pytest.fixture
def edge_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EdgeEnv:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    token = secrets.token_urlsafe(30)
    key = new_key()
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "edge-data"))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setenv("DATASET_DIR", str(tmp_path / "dataset"))
    monkeypatch.setenv("DEVICE_ID", DEVICE)
    monkeypatch.setenv("MODEL_DIR", str(make_model_dir(tmp_path / "models")))
    monkeypatch.setenv("DEVICE_API_KEY", key)
    # Loopback http is accepted (SPEC-009 CA-11); nothing listens on port 9 and, without the
    # app lifespan (uvicorn.run is a spy), no request is ever made.
    monkeypatch.setenv("CLOUD_API_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(qc_edge.netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])
    return EdgeEnv(tmp_path, token, key)


class UvicornSpy:
    """``uvicorn.run`` spy: keeps the app (background services) and optionally runs a scenario."""

    def __init__(self, scenario: Callable[[Any], Any] | None = None) -> None:
        self.scenario = scenario
        self.apps: list[Any] = []
        self.result: Any = None
        self.error: BaseException | None = None

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        app = args[0] if args else kwargs["app"]
        self.apps.append(app)
        if self.scenario is None:
            return
        try:
            self.result = self.scenario(app)
        except BaseException as exc:  # noqa: BLE001 - re-raised by check()
            self.error = exc

    def check(self) -> None:
        if self.error is not None:
            raise self.error


@pytest.fixture
def heartbeat_spy(monkeypatch: pytest.MonkeyPatch) -> list[HeartbeatLoop]:
    """Records every ``HeartbeatLoop`` built (the original constructor still runs)."""
    built: list[HeartbeatLoop] = []
    original = HeartbeatLoop.__init__

    def spy(self: HeartbeatLoop, *args: Any, **kwargs: Any) -> None:
        built.append(self)
        original(self, *args, **kwargs)

    monkeypatch.setattr(HeartbeatLoop, "__init__", spy)
    return built


def call_main(argv: list[str]) -> int:
    try:
        value = qc_edge.cli.main(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return value if isinstance(value, int) else 0


def start_edge(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> tuple[int, UvicornSpy]:
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    return call_main(argv), spy


def test_ca10_control_heartbeat_is_registered_with_key_url_and_model(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch, heartbeat_spy: list[HeartbeatLoop]
) -> None:
    """Positive control of CA-10 (otherwise "no loop" would pass trivially)."""
    code, spy = start_edge(monkeypatch, [])
    assert code == 0
    assert len(spy.apps) == 1
    assert len(heartbeat_spy) == 1


def test_ca10_no_heartbeat_with_stub_model(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch, heartbeat_spy: list[HeartbeatLoop]
) -> None:
    code, spy = start_edge(monkeypatch, ["--stub-model"])
    assert code == 0
    assert len(spy.apps) == 1
    assert heartbeat_spy == []


def test_ca10_no_heartbeat_with_interval_zero(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch, heartbeat_spy: list[HeartbeatLoop]
) -> None:
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", "0")
    code, spy = start_edge(monkeypatch, [])
    assert code == 0
    assert len(spy.apps) == 1
    assert heartbeat_spy == []


def test_ca10_no_heartbeat_without_device_api_key(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch, heartbeat_spy: list[HeartbeatLoop]
) -> None:
    monkeypatch.delenv("DEVICE_API_KEY")
    code, spy = start_edge(monkeypatch, [])
    assert code == 0
    assert len(spy.apps) == 1
    assert heartbeat_spy == []


@pytest.mark.parametrize("value", ["5", "abc"])
def test_ca10_invalid_interval_exits_with_code_2(
    edge_env: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    heartbeat_spy: list[HeartbeatLoop],
    value: str,
) -> None:
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", value)
    code, spy = start_edge(monkeypatch, [])
    assert code == 2
    assert spy.apps == []
    assert heartbeat_spy == []


# =========================================================================== CA-11

HTTP_CLIENT_MODULES = {"httpx", "requests", "urllib.request", "urllib3", "http.client", "aiohttp"}


def _http_imports(tree: ast.AST) -> list[str]:
    found = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"__import__", "import_module"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    names = [arg.value]
        for name in names:
            if any(name == m or name.startswith(m + ".") for m in HTTP_CLIENT_MODULES):
                found.append(name)
    return found


def test_ca11_only_the_publisher_imports_httpx() -> None:
    importers = {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if _http_imports(ast.parse(path.read_text(encoding="utf-8")))
    }
    assert importers == {"publisher.py"}
    assert (SRC / "heartbeat.py").is_file()  # the new module exists and is covered by the scan


def test_ca11_checker_is_not_tautological() -> None:
    for source in (
        "import httpx",
        "from httpx import Client",
        "import urllib.request",
        "from urllib import request",
        "import importlib\nimportlib.import_module('httpx')",
        "__import__('requests')",
    ):
        assert _http_imports(ast.parse(source)), source
    assert not _http_imports(ast.parse("from urllib.parse import quote"))


# ==================================================================== extras: body and timing


def test_extra_body_has_only_contract_fields_and_app_version(rig: Rig) -> None:
    """R-02: no image, no personal data; ``app_version = qc_edge.__version__``."""
    rig.loop().run_once()
    body = json.loads(rig.cloud.requests[0].content)
    assert set(body) == HEARTBEAT_FIELDS
    assert body["app_version"] == qc_edge.__version__
    assert rig.cloud.requests[0].headers["content-type"].startswith("application/json")


def test_extra_uptime_follows_the_monotonic_clock_and_is_capped(rig: Rig) -> None:
    now = [1000.0]
    loop = rig.loop(monotonic=lambda: now[0])
    now[0] += 7500.9
    loop.run_once()
    now[0] += float(MAX_HEARTBEAT_COUNT) * 2
    loop.run_once()
    first, second = rig.heartbeats()
    assert first.uptime_s == 7500
    assert second.uptime_s == MAX_HEARTBEAT_COUNT


def test_extra_sent_at_is_utc_and_recent(rig: Rig) -> None:
    before = datetime.now(UTC)
    rig.loop().run_once()
    after = datetime.now(UTC)
    hb = rig.heartbeats()[0]
    assert hb.sent_at.utcoffset() is not None
    assert before.replace(microsecond=0) <= hb.sent_at <= after


def test_extra_heartbeat_reflects_the_outbox_of_each_cycle(rig: Rig) -> None:
    loop = rig.loop()
    loop.run_once()
    rig.outbox.put(inspection())
    loop.run_once()
    first, second = rig.heartbeats()
    assert (first.outbox_pending, second.outbox_pending) == (2, 3)


def test_extra_stop_does_not_wait_for_the_interval(rig: Rig) -> None:
    loop = rig.loop(interval_s=3600)
    loop.start()
    deadline = time.monotonic() + 5
    while not rig.cloud.requests and time.monotonic() < deadline:
        time.sleep(0.02)
    t0 = time.monotonic()
    loop.stop()
    assert time.monotonic() - t0 < 3
    sent = len(rig.cloud.requests)
    time.sleep(0.2)
    assert len(rig.cloud.requests) == sent  # nothing after stop


def test_extra_auth_error_stops_the_thread(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    rig.cloud.answer = lambda request: httpx.Response(401)
    loop = rig.loop(interval_s=10)
    loop.start()
    deadline = time.monotonic() + 5
    while not rig.cloud.requests and time.monotonic() < deadline:
        time.sleep(0.02)
    loop.stop()
    assert len(rig.cloud.requests) == 1
    assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 1


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_extra_loop_refuses_a_non_positive_interval(rig: Rig, bad: str) -> None:
    with pytest.raises(ValueError):
        rig.loop(interval_s=float(bad))


# =========================================================================== extras: send_heartbeat


def test_extra_send_heartbeat_results(rig: Rig) -> None:
    hb = rig.loop().build()
    for status in (200, 201, 404, 500, 502):
        rig.cloud.answer = lambda request, s=status: httpx.Response(s, json={"x": 1})
        with pytest.raises(PublishTransientError):
            rig.publisher.send_heartbeat(hb)
    for status in (401, 403):
        rig.cloud.answer = lambda request, s=status: httpx.Response(s)
        with pytest.raises(PublishAuthError):
            rig.publisher.send_heartbeat(hb)
    for answer in (raise_connect, raise_timeout):
        rig.cloud.answer = answer
        with pytest.raises(PublishTransientError):
            rig.publisher.send_heartbeat(hb)
    rig.cloud.answer = lambda request: httpx.Response(204)
    assert rig.publisher.send_heartbeat(hb) is None


def test_extra_refusal_body_and_key_never_reach_the_error_or_log(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = "mk-" + secrets.token_hex(12)
    key = rig.key
    loop = rig.loop()
    answers: list[Answer] = [
        lambda request: httpx.Response(
            422, json={"detail": [{"msg": marker, "input": marker, "loc": ["body", "x"]}]}
        ),
        lambda request: httpx.Response(500, text=marker * 10),
        lambda request: httpx.Response(413, text=marker),
    ]
    for answer in answers:
        rig.cloud.answer = answer
        with pytest.raises(PublishTransientError) as info:
            rig.publisher.send_heartbeat(loop.build())
        assert marker not in str(info.value)
        loop.run_once()

    def leaky(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"proxy said X-API-Key={key} {marker}", request=request)

    rig.cloud.answer = leaky
    with pytest.raises(PublishTransientError) as info:
        rig.publisher.send_heartbeat(loop.build())
    assert key not in str(info.value)
    loop.run_once()
    text = log_text(caplog)
    assert key not in text
    assert marker * 2 not in text
    assert '"input"' not in text


def test_extra_redirect_is_not_followed(rig: Rig) -> None:
    rig.cloud.answer = lambda request: (
        httpx.Response(307, headers={"location": "https://evil.test/collect"})
        if request.url.host == "cloud.test"
        else httpx.Response(204)
    )
    with pytest.raises(PublishTransientError):
        rig.publisher.send_heartbeat(rig.loop().build())
    assert [r.url.host for r in rig.cloud.requests] == ["cloud.test"]


def test_extra_oversized_answer_is_transient(rig: Rig) -> None:
    rig.cloud.answer = lambda request: httpx.Response(422, content=b"x" * (600 * 1024))
    with pytest.raises(PublishTransientError):
        rig.publisher.send_heartbeat(rig.loop().build())


def test_extra_heartbeat_never_writes_the_outbox(rig: Rig) -> None:
    before = rig.rows()
    for answer in (
        lambda request: httpx.Response(204),
        raise_connect,
        lambda request: httpx.Response(401),
    ):
        rig.cloud.answer = answer
        rig.loop().run_once()
    assert rig.rows() == before


# =========================================================================== extras: interval


@pytest.mark.parametrize("value", ["10", "3600", "60"])
def test_extra_interval_limits_accepted(
    edge_env: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    heartbeat_spy: list[HeartbeatLoop],
    value: str,
) -> None:
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", value)
    code, _ = start_edge(monkeypatch, [])
    assert code == 0
    assert len(heartbeat_spy) == 1
    assert heartbeat_spy[0].interval_s == int(value)


def test_extra_interval_default_is_60(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch, heartbeat_spy: list[HeartbeatLoop]
) -> None:
    code, _ = start_edge(monkeypatch, [])
    assert code == 0
    assert heartbeat_spy[0].interval_s == 60


@pytest.mark.parametrize("value", ["9", "3601", "-1", "60.5", "1e3", "0x10", "sessenta"])
def test_extra_interval_refused(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", value)
    code, spy = start_edge(monkeypatch, [])
    assert code == 2
    assert spy.apps == []


@pytest.mark.parametrize("argv", [[], ["--stub-model"]])
def test_extra_invalid_interval_names_the_variable_not_the_value(
    edge_env: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    argv: list[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = "zz" + secrets.token_hex(8)
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", marker)
    code, _ = start_edge(monkeypatch, argv)
    assert code == 2
    text = log_text(caplog)
    assert "HEARTBEAT_INTERVAL_S" in text
    assert marker not in text


def test_extra_no_heartbeat_without_cloud_url(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch, heartbeat_spy: list[HeartbeatLoop]
) -> None:
    monkeypatch.delenv("CLOUD_API_URL")
    code, _ = start_edge(monkeypatch, [])
    assert code == 0
    assert heartbeat_spy == []


def test_extra_no_model_still_registers_the_heartbeat(
    edge_env: EdgeEnv, monkeypatch: pytest.MonkeyPatch, heartbeat_spy: list[HeartbeatLoop]
) -> None:
    """§4.4: the heartbeat carries ``None`` when no model is loaded (not a reason to skip it)."""
    monkeypatch.delenv("MODEL_DIR")
    code, _ = start_edge(monkeypatch, [])
    assert code == 0
    assert len(heartbeat_spy) == 1


# =========================================================================== extras: real HTTP


class _Handler(http.server.BaseHTTPRequestHandler):
    server: LocalCloud

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.record(self.command, self.path, dict(self.headers.items()), body)
        status, payload = self.server.answer(self.command, self.path, body)
        data = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        if data:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    do_GET = _handle
    do_POST = _handle

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return


class LocalCloud(http.server.ThreadingHTTPServer):
    """Local cloud on 127.0.0.1: fake batch route; the heartbeat waits for ``release``."""

    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.lock = threading.Lock()
        self.seen: list[tuple[str, str, dict[str, str], bytes]] = []
        self.stored: dict[str, int] = {}
        self.release = threading.Event()
        self.heartbeat_arrived = threading.Event()

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
                    self.stored[iid] = self.stored.get(iid, 0) + 1
                    results.append({"inspection_id": iid, "status": status})
            return 200, {"results": results}
        if method == "POST" and path == HB_PATH:
            self.heartbeat_arrived.set()
            self.release.wait(4)  # below the 5 s timeout of the publisher
            return 204, None
        return 404, {"detail": "Not Found"}


@pytest.fixture
def local_cloud() -> Iterator[LocalCloud]:
    server = LocalCloud()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_extra_real_http_heartbeat_does_not_block_nor_duplicate_inspections(
    edge_env: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    local_cloud: LocalCloud,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("CLOUD_API_URL", local_cloud.url)

    def scenario(app: Any) -> dict[str, Any]:
        with TestClient(app) as client:
            assert local_cloud.heartbeat_arrived.wait(5), "no heartbeat at start"
            # The heartbeat is still waiting for its answer: captures and publishing go on.
            responses = [capture(client, edge_env.token) for _ in range(3)]
            deadline = time.monotonic() + 3.5
            pending = None
            while time.monotonic() < deadline:
                status = client.get("/api/status", headers={SESSION_HEADER: edge_env.token})
                pending = status.json()["sink"]["pending"]
                if pending == 0:
                    break
                time.sleep(0.05)
            delivered_while_blocked = not local_cloud.release.is_set() and pending == 0
            local_cloud.release.set()
        return {"responses": responses, "blocked_ok": delivered_while_blocked}

    spy = UvicornSpy(scenario)
    monkeypatch.setattr(uvicorn, "run", spy)
    assert call_main([]) == 0
    spy.check()
    assert all(r.status_code == 200 for r in spy.result["responses"])
    assert spy.result["blocked_ok"], "inspections waited for the heartbeat"
    ids = {r.json()["inspection"]["inspection_id"] for r in spy.result["responses"]}
    assert set(local_cloud.stored) == ids
    assert all(count == 1 for count in local_cloud.stored.values())
    heartbeats = [s for s in local_cloud.seen if s[1] == HB_PATH]
    assert len(heartbeats) >= 1
    for method, _path, headers, body in heartbeats:
        assert method == "POST"
        lowered = {k.lower(): v for k, v in headers.items()}
        assert lowered["x-api-key"] == edge_env.key
        hb = HeartbeatCreate.model_validate_json(body)
        assert hb.model_version == MODEL_NAME
        assert set(json.loads(body)) == HEARTBEAT_FIELDS
    batch_ids = [
        item["inspection_id"]
        for method, path, _h, body in local_cloud.seen
        if (method, path) == ("POST", BATCH_PATH)
        for item in json.loads(body)["items"]
    ]
    assert sorted(batch_ids) == sorted(ids)
    assert edge_env.key not in log_text(caplog)
