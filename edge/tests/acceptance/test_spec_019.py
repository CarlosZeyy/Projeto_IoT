"""Acceptance tests for SPEC-019 (live video mode over HTTPS on the LAN).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation; only the names the SPEC leaves open come from ``reviews/SPEC-019/r1-dev-report.md``
(``qc_edge.cli.uvicorn_kwargs``, the ``id`` of the console elements). CA-12 is manual and stays with
the humans, after the merge (SPEC section 3.3). Tests named ``test_extra_*`` are exploratory edge
cases that no CA spells out.

Rules followed (``docs/architecture.md`` section 10):

* the public interface is used: ``LiveStateMachine``, the HTTP routes, ``qc_edge.cli.main``;
* the outbox and the dummy ONNX model of SPEC-008 are real; only ``uvicorn.run``, the LAN socket and
  the clock are replaced, and a scripted ``Inferencer`` is used where a CA asks for one;
* every image is generated here with Pillow, never a real photo (R-14); no real certificate is
  needed (SPEC section 7); every token is generated at run time.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import types
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import uvicorn
from fastapi.testclient import TestClient
from PIL import Image, ImageFile

import qc_edge.cli
import qc_edge.netinfo
from qc_contracts import Grade, InspectionCreate, ObjectType
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import InferenceError, InferenceResult, ModelInfo
from qc_edge.live import LiveStateMachine
from qc_edge.onnx_inferencer import OnnxInferencer
from qc_edge.outbox import SqliteOutbox
from qc_edge.sink import InMemorySink, SinkError

pytestmark = pytest.mark.acceptance

HEADER = "X-Session-Token"
ROUTE = "/api/live/frame"
LOT = "LOTE-01"
SESSION_A = "sessao-a-" + "a" * 16
SESSION_B = "sessao-b-" + "b" * 16
SESSION_C = "sessao-c-" + "c" * 16
SUFFIX = " (modelo provisório)"
PROVISIONAL = "partqc-mnv3-provisional-v1"
OFFICIAL = "partqc-mnv3-v1"
PORT = 8000
LAN_IP = "192.168.0.42"
FAIR_PROBS = {"type_probs": (0.9, 0.05, 0.05), "grade_probs": (0.05, 0.05, 0.8, 0.05, 0.05)}
OTHER_PROBS = {"type_probs": (0.05, 0.05, 0.9), "grade_probs": (0.05, 0.8, 0.05, 0.05, 0.05)}
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
INSECURE_MESSAGE = "O vídeo ao vivo exige HTTPS (configure EDGE_TLS_CERT e EDGE_TLS_KEY)."
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
    "EDGE_TLS_CERT",
    "EDGE_TLS_KEY",
    "LIVE_WINDOW",
    "LIVE_MIN_AGREE",
    "LIVE_MIN_CONFIDENCE",
    "LIVE_EMPTY_FRAMES",
    "LIVE_MAX_SESSIONS",
    "LIVE_FPS",
)


# =========================================================================== results and images


def result(
    object_type: str = "screw",
    grade: str | None = "fair",
    confidence: float = 0.9,
    latency_ms: int = 5,
) -> InferenceResult:
    return InferenceResult(
        object_type=ObjectType(object_type),
        grade=Grade(grade) if grade is not None else None,
        grade_score=2.0 if grade is not None else None,
        type_confidence=confidence,
        grade_confidence=0.8 if grade is not None else None,
        needs_review=False,
        latency_ms=latency_ms,
    )


def unknown(confidence: float = 0.95) -> InferenceResult:
    return result("unknown", None, confidence)


def jpeg(width: int = 64, height: int = 48, seed: int = 8, **save: Any) -> bytes:
    rng = np.random.default_rng(seed)
    pixels = rng.integers(40, 216, size=(max(2, height // 8), max(2, width // 8), 3))
    image = Image.fromarray(pixels.astype(np.uint8), "RGB").resize((width, height))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85, **save)
    return buffer.getvalue()


def encoded(fmt: str, size: tuple[int, int] = (32, 32)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "steelblue").save(buffer, format=fmt)
    return buffer.getvalue()


def padded_jpeg(size: int) -> bytes:
    """A valid JPEG with exactly ``size`` bytes: zeros after the end-of-image marker."""
    data = jpeg()
    assert len(data) <= size
    return data + b"\x00" * (size - len(data))


def fake_socket_module(probe_ip: str) -> Any:
    class FakeSocket:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> FakeSocket:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def settimeout(self, value: float | None) -> None:
            pass

        def setblocking(self, flag: bool) -> None:
            pass

        def setsockopt(self, *args: Any) -> None:
            pass

        def connect(self, address: Any) -> None:
            pass

        def getsockname(self) -> tuple[str, int]:
            return (probe_ip, 54321)

        def close(self) -> None:
            pass

    module = types.SimpleNamespace(**vars(__import__("socket")))
    module.socket = FakeSocket
    module.getaddrinfo = lambda *a, **k: []
    module.gethostname = lambda: "acc-notebook"
    return module


# =========================================================================== inferencers and sinks


class SpyInferencer:
    """The real ONNX inferencer, counting the calls (CA-05: "the model is not called")."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls = 0

    @property
    def model_info(self) -> ModelInfo:
        return self.inner.model_info

    def infer(self, image: Image.Image) -> InferenceResult:
        self.calls += 1
        return self.inner.infer(image)


class ScriptedInferencer:
    """Answers each ``infer`` from a script; the last entry repeats. An exception is raised."""

    def __init__(
        self,
        script: Sequence[InferenceResult | Exception] = (result(),),
        version: str = "acc-model-v1",
    ) -> None:
        self.script = list(script)
        self.calls = 0
        self.version = version
        self.lock = threading.Lock()

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(self.version, "a" * 64)

    def infer(self, image: Image.Image) -> InferenceResult:
        with self.lock:
            index = min(self.calls, len(self.script) - 1)
            self.calls += 1
        entry = self.script[index]
        if isinstance(entry, Exception):
            raise entry
        return entry


class BlockingInferencer(ScriptedInferencer):
    """Blocks in ``infer`` until ``release`` is set, so the decode slot stays taken."""

    def __init__(self, script: Sequence[InferenceResult | Exception] = (result(),)) -> None:
        super().__init__(script)
        self.started = threading.Event()
        self.release = threading.Event()

    def infer(self, image: Image.Image) -> InferenceResult:
        self.started.set()
        assert self.release.wait(20), "the test never released the inferencer"
        return super().infer(image)


class FlakySink(InMemorySink):
    """``put`` raises the given exception only in the listed calls (1-based)."""

    def __init__(self, failures: dict[int, Exception]) -> None:
        super().__init__()
        self.failures = failures
        self.put_calls = 0

    def put(self, inspection: InspectionCreate) -> None:
        self.put_calls += 1
        failure = self.failures.get(self.put_calls)
        if failure is not None:
            raise failure
        super().put(inspection)


class ManualClock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> datetime:
        return T0 + timedelta(seconds=self.seconds)


# =========================================================================== fixtures


@dataclass
class EdgeEnv:
    tmp: Path
    data_dir: Path
    token: str
    monkeypatch: pytest.MonkeyPatch
    clients: list[TestClient] = field(default_factory=list)

    def captures(self) -> list[Path]:
        root = self.data_dir / "captures"
        return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []

    def model(self, name: str = OFFICIAL, dummy_model: Any = None, **probs: Any) -> OnnxInferencer:
        directory = dummy_model.write_model_dir(self.tmp / "models", name, **probs)
        return OnnxInferencer(directory)


@pytest.fixture
def edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EdgeEnv:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    data_dir = tmp_path / "edge-data"
    token = secrets.token_urlsafe(30)
    monkeypatch.setenv("EDGE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATASET_DIR", str(tmp_path / "dataset"))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    monkeypatch.setattr(qc_edge.netinfo, "socket", fake_socket_module(LAN_IP))
    return EdgeEnv(tmp=tmp_path, data_dir=data_dir, token=token, monkeypatch=monkeypatch)


@pytest.fixture
def run_client(edge: EdgeEnv) -> Iterator[Callable[..., TestClient]]:
    """``run_client(inferencer, sink, **create_app_kwargs)``: a started ``TestClient``."""
    started: list[TestClient] = []

    def start(inferencer: Any, sink: Any, **kwargs: Any) -> TestClient:
        client = TestClient(
            create_app(EdgeSettings(), inferencer, sink, **kwargs),
            raise_server_exceptions=False,
        )
        client.__enter__()
        started.append(client)
        return client

    yield start
    for client in started:
        client.__exit__(None, None, None)


def post_frame(
    client: TestClient,
    token: str | None,
    image: bytes | None = None,
    *,
    lot_id: str | None = LOT,
    session: str | None = SESSION_A,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    all_headers = dict(headers or {})
    if token is not None:
        all_headers[HEADER] = token
    data = {}
    if lot_id is not None:
        data["lot_id"] = lot_id
    if session is not None:
        data["session"] = session
    files = {"image": ("quadro.jpg", jpeg() if image is None else image, "image/jpeg")}
    return client.post(ROUTE, headers=all_headers, data=data, files=files)


def send_frames(client: TestClient, token: str, count: int, **kwargs: Any) -> list[httpx.Response]:
    return [post_frame(client, token, **kwargs) for _ in range(count)]


def console_get(app: Any, *, scheme: str = "http", host: str | None = None) -> httpx.Response:
    """Console GET from loopback (``127.0.0.1:<EDGE_PORT>``, SPEC-025 and SPEC-019 section 4.1)."""
    port = os.environ.get("EDGE_PORT", str(PORT))

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(
            transport=transport, base_url=f"{scheme}://127.0.0.1:{port}"
        ) as c:
            return await c.get("/", headers={"Host": host} if host is not None else None)

    return asyncio.run(go())


def latency_text(page: str) -> str:
    match = re.search(r'<(\w+)[^>]*\bid="live-latency"[^>]*>(.*?)</\1>', page, re.DOTALL)
    assert match is not None, "the console has no id=live-latency element"
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", match.group(2))).strip()


@dataclass
class Boot:
    code: int
    text: str
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]]


def boot_edge(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> Boot:
    """Run ``qc_edge.cli.main`` with ``uvicorn.run`` replaced by a spy (no server, no socket)."""
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(sys, "argv", ["qc-edge", *argv])
    caplog.set_level(logging.DEBUG)
    try:
        qc_edge.cli.main(list(argv))
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    out = capsys.readouterr()
    parts = [caplog.text, out.out, out.err]
    parts += [record.getMessage() for record in caplog.records]
    return Boot(code=code, text="\n".join(parts), calls=calls)


def tls_files(tmp: Path, key_mode: int = 0o600, content: str = "fake pem") -> tuple[Path, Path]:
    cert = tmp / "cert.pem"
    key = tmp / "key.pem"
    cert.write_text(content, encoding="utf-8")
    key.write_text(content, encoding="utf-8")
    cert.chmod(0o644)
    key.chmod(key_mode)
    return cert, key


def feed_all(
    machine: LiveStateMachine, results: Iterable[InferenceResult], start: int = 1
) -> list[Any]:
    """Feed the results, each with its own frame ``b"frame-N"`` and timestamp ``T0 + N s``."""
    return [
        machine.feed(item, f"frame-{n}".encode(), T0 + timedelta(seconds=n))
        for n, item in enumerate(results, start=start)
    ]


def emit_indexes(steps: Sequence[Any]) -> list[int]:
    return [n for n, step in enumerate(steps, start=1) if step.emit is not None]


def ca01_results() -> list[InferenceResult]:
    """1 ``poor``, 8 ``fair`` (type confidence with mean 0.85) and 1 ``poor``."""
    fair = [result("screw", "fair", 0.85) for _ in range(8)]
    return [result("screw", "poor", 0.9), *fair, result("screw", "poor", 0.9)]


# =========================================================================== CA-01 to CA-03


def test_ca01_emits_the_most_recent_frame_of_the_stable_pair() -> None:
    machine = LiveStateMachine()
    steps = feed_all(machine, ca01_results())

    assert emit_indexes(steps) == [10]
    assert [s.state for s in steps[:9]] == ["DETECTING"] * 9
    assert steps[9].state == "EMIT"
    emitted, frame, inspected_at = steps[9].emit
    assert emitted.grade == Grade.FAIR
    assert frame == b"frame-9"
    assert inspected_at == T0 + timedelta(seconds=9)
    assert steps[9].stability == pytest.approx(0.8)

    following = machine.feed(result("screw", "fair", 0.9), b"next", T0)
    assert following.state == "WAIT_REMOVAL"
    assert following.emit is None


@pytest.mark.parametrize(
    "results",
    [
        pytest.param(
            [result("screw", "fair", 0.95) for _ in range(7)]
            + [result("screw", "poor", 0.95) for _ in range(3)],
            id="only-7-equal",
        ),
        pytest.param(
            [result("screw", "fair", 0.79) for _ in range(8)]
            + [result("screw", "poor", 0.95) for _ in range(2)],
            id="8-equal-with-mean-0.79",
        ),
    ],
)
def test_ca02_no_emission(results: list[InferenceResult]) -> None:
    steps = feed_all(LiveStateMachine(), results)
    assert len(steps) == 10
    assert emit_indexes(steps) == []
    assert all(s.state != "EMIT" for s in steps)


def test_ca03_removal_needs_three_consecutive_unknowns_then_a_new_part_emits() -> None:
    machine = LiveStateMachine()
    assert emit_indexes(feed_all(machine, ca01_results())) == [10]

    steps = feed_all(machine, [result("screw", "fair", 0.9) for _ in range(20)])
    assert emit_indexes(steps) == []
    assert all(s.state == "WAIT_REMOVAL" for s in steps)

    steps = feed_all(machine, [unknown(), unknown(), result("screw", "fair", 0.9)])
    assert emit_indexes(steps) == []
    assert steps[-1].state == "WAIT_REMOVAL"

    steps = feed_all(machine, [unknown(), unknown(), unknown()])
    assert emit_indexes(steps) == []
    assert [s.state for s in steps] == ["WAIT_REMOVAL", "WAIT_REMOVAL", "IDLE"]

    steps = feed_all(machine, [result("nut", "good", 0.9) for _ in range(10)])
    assert emit_indexes(steps) == [10]
    assert steps[-1].state == "EMIT"
    assert steps[-1].emit[0].object_type == ObjectType.NUT


# =========================================================================== CA-04


def test_ca04_new_lot_restarts_the_window(
    edge: EdgeEnv, dummy_model: Any, run_client: Callable[..., TestClient]
) -> None:
    inferencer = edge.model(OFFICIAL, dummy_model, **FAIR_PROBS)
    sink = InMemorySink()
    client = run_client(inferencer, sink)

    first = send_frames(client, edge.token, 9, lot_id="LOTE-A")
    assert all(r.status_code == 200 and r.json()["inspection"] is None for r in first)

    after = send_frames(client, edge.token, 10, lot_id="LOTE-B")
    assert all(r.status_code == 200 for r in after)
    inspections = [r.json()["inspection"] for r in after]
    assert all(i is None for i in inspections[:9]), "an EMIT came before the 10th frame"
    assert inspections[9] is not None
    assert inspections[9]["lot_id"] == "LOTE-B"
    assert [i.lot_id for i in sink.items] == ["LOTE-B"]


# =========================================================================== CA-05


def _gif() -> bytes:
    return encoded("GIF")


def _png() -> bytes:
    return encoded("PNG")


@pytest.mark.parametrize(
    "case, expected",
    [
        ("no-token", 401),
        ("image-1048577-bytes", 413),
        ("content-length-1310721", 413),
        ("short-session", 422),
        ("lot-with-space", 422),
        ("gif", 415),
        ("valid-png", 415),
        ("jpeg-1001x1000", 415),
    ],
)
def test_ca05_refusals_do_not_reach_the_model(
    edge: EdgeEnv,
    dummy_model: Any,
    run_client: Callable[..., TestClient],
    case: str,
    expected: int,
) -> None:
    spy = SpyInferencer(edge.model(OFFICIAL, dummy_model, **FAIR_PROBS))
    sink = InMemorySink()
    client = run_client(spy, sink)

    if case == "no-token":
        response = post_frame(client, None)
    elif case == "image-1048577-bytes":
        response = post_frame(client, edge.token, padded_jpeg(1_048_577))
    elif case == "content-length-1310721":
        response = post_frame(client, edge.token, headers={"Content-Length": "1310721"})
    elif case == "short-session":
        response = post_frame(client, edge.token, session="curto")
    elif case == "lot-with-space":
        response = post_frame(client, edge.token, lot_id="lote 1")
    elif case == "gif":
        response = post_frame(client, edge.token, _gif())
    elif case == "valid-png":
        response = post_frame(client, edge.token, _png())
    else:
        response = post_frame(client, edge.token, jpeg(1001, 1000))

    assert response.status_code == expected, response.text
    assert spy.calls == 0
    assert sink.items == []
    assert edge.captures() == []


# =========================================================================== CA-06 and CA-07


def test_ca06_one_inspection_per_part(
    edge: EdgeEnv, dummy_model: Any, run_client: Callable[..., TestClient]
) -> None:
    sink = InMemorySink()
    client = run_client(edge.model(OFFICIAL, dummy_model, **FAIR_PROBS), sink)

    responses = send_frames(client, edge.token, 30)

    assert [r.status_code for r in responses] == [200] * 30
    with_inspection = [r.json()["inspection"] for r in responses if r.json()["inspection"]]
    assert len(with_inspection) == 1
    assert len(sink.items) == 1
    inspection_id = with_inspection[0]["inspection_id"]
    assert str(sink.items[0].inspection_id) == inspection_id
    files = edge.captures()
    assert [p.name for p in files] == [f"{inspection_id}.jpg"]
    # CA-17, last sentence: every one of the 30 answers has a result.
    assert all(r.json()["result"] is not None for r in responses)


def test_ca07_outbox_payload_has_the_contract_and_no_image(
    edge: EdgeEnv, dummy_model: Any, run_client: Callable[..., TestClient]
) -> None:
    path = edge.tmp / "outbox.sqlite3"
    outbox = SqliteOutbox(path)
    image = jpeg(320, 240, seed=71)
    try:
        client = run_client(edge.model(OFFICIAL, dummy_model, **FAIR_PROBS), outbox)
        responses = send_frames(client, edge.token, 30, image=image)
        client.__exit__(None, None, None)
    finally:
        outbox.close()

    emitted = [r.json()["inspection"] for r in responses if r.json()["inspection"]]
    assert len(emitted) == 1
    con = sqlite3.connect(path)
    try:
        payloads = [row[0] for row in con.execute("SELECT payload FROM outbox")]
    finally:
        con.close()
    assert len(payloads) == len(emitted) == 1
    parsed = json.loads(payloads[0])
    inspection = InspectionCreate.model_validate(parsed)
    assert str(inspection.inspection_id) == emitted[0]["inspection_id"]
    assert set(parsed) == set(InspectionCreate.model_fields)
    for key, value in parsed.items():
        assert not isinstance(value, (bytes, list, dict)), key
        assert len(str(value)) < 256, key
        assert not re.search(r"image|frame|photo|jpeg|bytes", key, re.IGNORECASE), key
    assert base64.b64encode(image[:64]).decode() not in payloads[0]
    assert image[:64] not in path.read_bytes()
    assert len(edge.captures()) == len(emitted)


# =========================================================================== CA-08


def test_ca08_session_limit_and_expiry(
    edge: EdgeEnv, dummy_model: Any, run_client: Callable[..., TestClient]
) -> None:
    edge.monkeypatch.setenv("LIVE_MAX_SESSIONS", "2")
    clock = ManualClock()
    client = run_client(
        edge.model(OFFICIAL, dummy_model, **FAIR_PROBS), InMemorySink(), clock=clock
    )

    clock.seconds = 0
    assert post_frame(client, edge.token, session=SESSION_A).status_code == 200
    clock.seconds = 30
    assert post_frame(client, edge.token, session=SESSION_B).status_code == 200
    clock.seconds = 31
    refused = post_frame(client, edge.token, session=SESSION_C)
    assert refused.status_code == 429
    assert refused.json() == {"detail": "too many live sessions"}
    clock.seconds = 61
    assert post_frame(client, edge.token, session=SESSION_C).status_code == 200


# =========================================================================== CA-09


@pytest.mark.parametrize(
    "case, cited",
    [
        ("cert-without-key", "EDGE_TLS_KEY"),
        ("key-without-cert", "EDGE_TLS_CERT"),
        ("key-with-mode-0644", "EDGE_TLS_KEY"),
        ("missing-cert-path", "EDGE_TLS_CERT"),
        ("missing-key-path", "EDGE_TLS_KEY"),
    ],
)
def test_ca09_invalid_tls_exits_2_citing_the_variable(
    edge: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    case: str,
    cited: str,
) -> None:
    secret_content = "PEM-CONTENT-" + secrets.token_hex(8)
    cert, key = tls_files(edge.tmp, content=secret_content)
    missing = edge.tmp / "nope.pem"
    if case == "cert-without-key":
        monkeypatch.setenv("EDGE_TLS_CERT", str(cert))
    elif case == "key-without-cert":
        monkeypatch.setenv("EDGE_TLS_KEY", str(key))
    elif case == "key-with-mode-0644":
        key.chmod(0o644)
        monkeypatch.setenv("EDGE_TLS_CERT", str(cert))
        monkeypatch.setenv("EDGE_TLS_KEY", str(key))
    elif case == "missing-cert-path":
        monkeypatch.setenv("EDGE_TLS_CERT", str(missing))
        monkeypatch.setenv("EDGE_TLS_KEY", str(key))
    else:
        monkeypatch.setenv("EDGE_TLS_CERT", str(cert))
        monkeypatch.setenv("EDGE_TLS_KEY", str(missing))

    boot = boot_edge(monkeypatch, caplog, capsys)

    assert boot.code == 2
    assert boot.calls == []
    assert cited in boot.text
    assert secret_content not in boot.text


def test_ca09_valid_tls_reaches_uvicorn_and_both_qr_urls_are_https(
    edge: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cert, key = tls_files(edge.tmp)
    monkeypatch.setenv("EDGE_TLS_CERT", str(cert))
    monkeypatch.setenv("EDGE_TLS_KEY", str(key))

    boot = boot_edge(monkeypatch, caplog, capsys)

    assert boot.code == 0
    assert len(boot.calls) == 1
    args, kwargs = boot.calls[0]
    assert str(kwargs["ssl_certfile"]) == str(cert)
    assert str(kwargs["ssl_keyfile"]) == str(key)
    pure = qc_edge.cli.uvicorn_kwargs(EdgeSettings())
    assert str(pure["ssl_certfile"]) == str(cert)
    assert str(pure["ssl_keyfile"]) == str(key)

    page = console_get(args[0], scheme="https")
    assert page.status_code == 200
    assert f"https://{LAN_IP}:{PORT}/capture?t={edge.token}" in page.text
    assert f"https://{LAN_IP}:{PORT}/live?t={edge.token}" in page.text
    assert f"http://{LAN_IP}" not in page.text


# =========================================================================== CA-10


def assert_page_headers(response: httpx.Response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_ca10_live_page(edge: EdgeEnv, run_client: Callable[..., TestClient]) -> None:
    client = run_client(ScriptedInferencer(), InMemorySink())

    without = client.get("/live")
    assert without.status_code == 401
    assert_page_headers(without)
    wrong = client.get("/live", params={"t": "x" * 40})
    assert wrong.status_code == 401
    assert_page_headers(wrong)

    page = client.get("/live", params={"t": edge.token})
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert_page_headers(page)
    assert "live.js" in page.text
    assert re.search(r'name="lot_id"|id="lot_id"', page.text)

    assert client.get("/static/live.html").status_code == 404

    script = client.get("/static/live.js")
    assert script.status_code == 200
    for needle in ("isSecureContext", "getUserMedia", "facingMode"):
        assert needle in script.text
    packaged = Path(qc_edge.__file__).parent / "static" / "live.js"
    assert packaged.read_text(encoding="utf-8") == script.text


# =========================================================================== CA-11


@pytest.mark.parametrize(
    "env, cited",
    [
        ({"LIVE_WINDOW": "2"}, "LIVE_WINDOW"),
        ({"LIVE_WINDOW": "10", "LIVE_MIN_AGREE": "11"}, "LIVE_MIN_AGREE"),
        ({"LIVE_MIN_CONFIDENCE": "1.2"}, "LIVE_MIN_CONFIDENCE"),
        ({"LIVE_MAX_SESSIONS": "0"}, "LIVE_MAX_SESSIONS"),
    ],
    ids=["window-2", "min-agree-11", "confidence-1.2", "max-sessions-0"],
)
def test_ca11_invalid_live_config_exits_2(
    edge: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    env: dict[str, str],
    cited: str,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    boot = boot_edge(monkeypatch, caplog, capsys)
    assert boot.code == 2
    assert boot.calls == []
    assert cited in boot.text


# =========================================================================== CA-13


def test_ca13_provisional_model_is_simulated_with_the_suffix(
    edge: EdgeEnv, dummy_model: Any, run_client: Callable[..., TestClient]
) -> None:
    sink = InMemorySink()
    client = run_client(edge.model(PROVISIONAL, dummy_model, **FAIR_PROBS), sink)

    responses = send_frames(client, edge.token, 30)

    assert [r.status_code for r in responses] == [200] * 30
    with_inspection = [r.json() for r in responses if r.json()["inspection"]]
    assert len(with_inspection) == 1
    assert with_inspection[0]["inspection"]["source"] == "simulated"
    assert [i.source.value for i in sink.items] == ["simulated"]
    assert with_inspection[0]["result"]["labels_pt"]["verdict"].endswith(SUFFIX)
    assert all(r.json()["result"]["labels_pt"]["verdict"].endswith(SUFFIX) for r in responses)


def test_ca13_official_model_is_live_without_the_suffix(
    edge: EdgeEnv, dummy_model: Any, run_client: Callable[..., TestClient]
) -> None:
    sink = InMemorySink()
    client = run_client(edge.model(OFFICIAL, dummy_model, **FAIR_PROBS), sink)

    responses = send_frames(client, edge.token, 30)

    with_inspection = [r.json() for r in responses if r.json()["inspection"]]
    assert len(with_inspection) == 1
    assert with_inspection[0]["inspection"]["source"] == "live"
    assert [i.source.value for i in sink.items] == ["live"]
    assert all("provisório" not in r.json()["result"]["labels_pt"]["verdict"] for r in responses)


# =========================================================================== CA-14


def test_ca14_photo_flow_without_tls_is_as_before(
    edge: EdgeEnv,
    dummy_model: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    run_client: Callable[..., TestClient],
) -> None:
    boot = boot_edge(monkeypatch, caplog, capsys)
    assert boot.code == 0
    args, kwargs = boot.calls[0]
    assert "ssl_certfile" not in kwargs
    assert "ssl_keyfile" not in kwargs
    pure = qc_edge.cli.uvicorn_kwargs(EdgeSettings())
    assert "ssl_certfile" not in pure
    assert "ssl_keyfile" not in pure

    page = console_get(args[0])
    assert page.status_code == 200
    assert f"http://{LAN_IP}:{PORT}/capture?t={edge.token}" in page.text
    assert f"https://{LAN_IP}" not in page.text
    assert "/live?" not in page.text

    sink = InMemorySink()
    client = run_client(edge.model(OFFICIAL, dummy_model, **FAIR_PROBS), sink)
    captured = client.post(
        "/api/capture",
        headers={HEADER: edge.token},
        data={"lot_id": LOT, "mode": "inspect"},
        files={"image": ("foto.jpg", jpeg(), "image/jpeg")},
    )
    assert captured.status_code == 200, captured.text
    body = captured.json()
    assert len(sink.items) == 1
    assert str(sink.items[0].inspection_id) == body["inspection"]["inspection_id"]
    assert body["inspection"]["source"] == "live"


# =========================================================================== CA-15 and CA-16


def test_ca15_empty_table_never_emits() -> None:
    machine = LiveStateMachine(window=10, min_agree=3, empty_frames=10)
    steps = feed_all(machine, [result("screw", "fair", 0.9), *[unknown(0.95) for _ in range(9)]])
    assert emit_indexes(steps) == []
    assert steps[9].state == "DETECTING"
    assert steps[9].stability == pytest.approx(0.9)

    step = machine.feed(unknown(0.95), b"x", T0)
    assert step.emit is None
    assert step.state == "IDLE"
    assert step.stability == 0


def test_ca15_known_type_without_grade_emits() -> None:
    steps = feed_all(LiveStateMachine(), [result("drill", None, 0.9) for _ in range(10)])
    assert emit_indexes(steps) == [10]
    assert steps[9].state == "EMIT"
    assert steps[9].emit[0].object_type == ObjectType.DRILL
    assert steps[9].emit[0].grade is None


def test_ca16_tie_does_not_emit_and_the_window_rolls() -> None:
    machine = LiveStateMachine(window=10, min_agree=5)
    alternating = [result("screw", "poor" if n % 2 == 0 else "fair", 0.9) for n in range(10)]
    steps = feed_all(machine, alternating)
    assert emit_indexes(steps) == []
    assert steps[9].state == "DETECTING"
    assert steps[9].stability == pytest.approx(0.5)

    eleventh = machine.feed(result("screw", "fair", 0.9), b"frame-11", T0)
    assert eleventh.state == "EMIT"
    assert eleventh.emit is not None
    assert eleventh.emit[0].grade == Grade.FAIR
    assert eleventh.emit[1] == b"frame-11"


# =========================================================================== CA-17 to CA-20


def test_ca17_result_is_never_null(
    edge: EdgeEnv, dummy_model: Any, run_client: Callable[..., TestClient]
) -> None:
    sink = InMemorySink()
    client = run_client(edge.model(OFFICIAL, dummy_model, **OTHER_PROBS), sink)

    responses = send_frames(client, edge.token, 3)

    for response in responses:
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"] == "IDLE"
        assert body["stability"] == 0
        assert body["inspection"] is None
        assert body["result"]["object_type"] == "unknown"
        assert body["result"]["grade"] is None
        assert body["result"]["labels_pt"]["grade"] is None
        assert body["result"]["labels_pt"]["object_type"] == "desconhecido"
        assert body["result"]["labels_pt"]["verdict"] == "desconhecido"
    assert sink.items == []
    assert edge.captures() == []


def test_ca18_failure_to_persist_resets_and_emits_again(
    edge: EdgeEnv, dummy_model: Any, run_client: Callable[..., TestClient]
) -> None:
    sink = FlakySink({1: SinkError("acc failure")})
    client = run_client(edge.model(OFFICIAL, dummy_model, **FAIR_PROBS), sink)

    responses = send_frames(client, edge.token, 30)

    assert responses[9].status_code == 503
    assert responses[9].json() == {"detail": "failed to persist inspection"}
    assert responses[19].status_code == 200
    emitted = responses[19].json()["inspection"]
    assert emitted is not None
    for n, response in enumerate(responses, start=1):
        if n in (10, 20):
            continue
        assert response.status_code == 200, (n, response.text)
        assert response.json()["inspection"] is None, n
    assert [str(i.inspection_id) for i in sink.items] == [emitted["inspection_id"]]
    assert [p.name for p in edge.captures()] == [f"{emitted['inspection_id']}.jpg"]


def test_ca19_failed_inference_does_not_enter_the_window(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    script: list[InferenceResult | Exception] = [result() for _ in range(4)]
    script += [InferenceError("acc failure")]
    script += [result() for _ in range(6)]
    sink = InMemorySink()
    client = run_client(ScriptedInferencer(script), sink)

    responses = send_frames(client, edge.token, 11)

    assert responses[4].status_code == 500
    assert responses[4].json() == {"detail": "inference failed"}
    ok = [n for n, r in enumerate(responses, start=1) if n != 5]
    assert all(responses[n - 1].status_code == 200 for n in ok)
    firsts = [n for n in ok if responses[n - 1].json()["inspection"] is not None]
    assert firsts == [11]
    assert len(sink.items) == 1


def test_ca20_console_latency(edge: EdgeEnv, run_client: Callable[..., TestClient]) -> None:
    script = [result(latency_ms=300) for _ in range(2)] + [
        result(latency_ms=100) for _ in range(18)
    ]
    client = run_client(ScriptedInferencer(script), InMemorySink())
    app = client.app

    assert latency_text(console_get(app).text) == "—"

    responses = send_frames(client, edge.token, 20)

    assert [r.status_code for r in responses] == [200] * 20
    text = latency_text(console_get(app).text)
    assert re.search(r"100 ms.*p95.*300 ms", text), text
    for response in responses:
        assert "p95" not in response.text
        assert "p95" not in response.json()


# =========================================================================== extras: state machine


def test_extra_idle_ignores_unknown() -> None:
    machine = LiveStateMachine()
    steps = feed_all(machine, [unknown() for _ in range(5)])
    assert [s.state for s in steps] == ["IDLE"] * 5
    assert all(s.stability == 0 and s.emit is None for s in steps)


def test_extra_stability_counts_the_most_frequent_pair_over_the_window() -> None:
    steps = feed_all(LiveStateMachine(), ca01_results())
    expected = [0.1, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.8]
    assert [s.stability for s in steps] == pytest.approx(expected)


def test_extra_confidence_mean_uses_only_the_frames_of_the_pair() -> None:
    results = [result("screw", "fair", 0.81) for _ in range(8)]
    results += [result("screw", "poor", 0.01) for _ in range(2)]
    steps = feed_all(LiveStateMachine(), results)
    assert emit_indexes(steps) == [10]


def test_extra_confidence_mean_exactly_at_the_threshold_emits() -> None:
    steps = feed_all(
        LiveStateMachine(min_confidence=0.75),
        [result("screw", "fair", 0.75) for _ in range(10)],
    )
    assert emit_indexes(steps) == [10]


def test_extra_nine_equal_frames_do_not_emit_before_the_window_is_full() -> None:
    steps = feed_all(LiveStateMachine(window=10, min_agree=3), [result() for _ in range(9)])
    assert emit_indexes(steps) == []


def test_extra_unknown_as_top_pair_blocks_a_known_pair_that_reaches_min_agree() -> None:
    """Section 4.2: the conditions apply to the most frequent pair: here, the empty table."""
    machine = LiveStateMachine(window=10, min_agree=3, empty_frames=10)
    pattern = [unknown(), unknown(), result()] * 3 + [unknown()]
    steps = feed_all(machine, pattern)
    assert emit_indexes(steps) == []


def test_extra_unknowns_must_be_consecutive_in_detecting() -> None:
    machine = LiveStateMachine()
    steps = feed_all(machine, [result(), unknown(), unknown(), result(), unknown(), unknown()])
    assert [s.state for s in steps] == ["DETECTING"] * 6


def test_extra_detecting_goes_back_to_idle_and_clears_the_window() -> None:
    machine = LiveStateMachine()
    feed_all(machine, [result() for _ in range(9)])
    steps = feed_all(machine, [unknown(), unknown(), unknown()])
    assert steps[-1].state == "IDLE"
    assert steps[-1].stability == 0
    steps = feed_all(machine, [result() for _ in range(10)])
    assert emit_indexes(steps) == [10]
    assert steps[0].stability == pytest.approx(0.1)


def test_extra_reset_clears_everything() -> None:
    machine = LiveStateMachine()
    feed_all(machine, [result() for _ in range(9)])
    machine.reset()
    steps = feed_all(machine, [result() for _ in range(10)])
    assert emit_indexes(steps) == [10]
    machine.reset()
    assert machine.feed(result(), b"x", T0).state == "DETECTING"


def test_extra_three_way_tie_at_the_smallest_window_does_not_emit() -> None:
    machine = LiveStateMachine(window=3, min_agree=1)
    steps = feed_all(
        machine, [result("screw", "fair"), result("screw", "poor"), result("nut", "good")]
    )
    assert emit_indexes(steps) == []
    assert steps[-1].stability == pytest.approx(1 / 3)


def test_extra_emit_window_with_the_same_type_and_other_grade_are_different_pairs() -> None:
    results = [result("screw", "fair") for _ in range(4)]
    results += [result("screw", "poor") for _ in range(4)]
    results += [result("nut", "fair"), result("nut", "fair")]
    assert emit_indexes(feed_all(LiveStateMachine(), results)) == []


def test_extra_wait_removal_keeps_stability_of_the_rolling_window() -> None:
    machine = LiveStateMachine()
    feed_all(machine, [result() for _ in range(10)])
    steps = feed_all(machine, [result("nut", "good") for _ in range(10)])
    assert all(s.state == "WAIT_REMOVAL" for s in steps)
    assert steps[-1].stability == pytest.approx(1.0)
    assert steps[-1].emit is None
    assert all(s.emit is None for s in steps)


@pytest.mark.parametrize(
    "lead, last",
    [
        pytest.param([], unknown(), id="unknown-in-idle"),
        pytest.param([result()], unknown(), id="unknown-in-detecting"),
        pytest.param([result() for _ in range(10)], result(), id="known-in-wait-removal"),
    ],
)
def test_extra_frames_that_cannot_be_emitted_are_not_kept(
    lead: list[InferenceResult], last: InferenceResult
) -> None:
    """Section 4.2: the bytes of ``unknown`` results and of ``WAIT_REMOVAL`` are not stored."""
    machine = LiveStateMachine()
    feed_all(machine, lead)
    frame = secrets.token_bytes(64)
    before = sys.getrefcount(frame)
    machine.feed(last, frame, T0)
    assert sys.getrefcount(frame) == before


def test_extra_reset_drops_the_frames_it_kept() -> None:
    machine = LiveStateMachine()
    frame = secrets.token_bytes(64)
    before = sys.getrefcount(frame)
    machine.feed(result(), frame, T0)
    assert sys.getrefcount(frame) > before, "the only frame that can be emitted was not kept"
    machine.reset()
    assert sys.getrefcount(frame) == before


def test_extra_frame_leaving_the_window_is_dropped() -> None:
    machine = LiveStateMachine(window=3, min_agree=3)
    frame = secrets.token_bytes(64)
    before = sys.getrefcount(frame)
    machine.feed(result("screw", "poor"), frame, T0)
    feed_all(machine, [result("screw", "fair"), result("nut", "good"), result("nut", "fair")])
    assert sys.getrefcount(frame) == before


# =========================================================================== extras: route


def test_extra_response_shape(edge: EdgeEnv, run_client: Callable[..., TestClient]) -> None:
    client = run_client(ScriptedInferencer(), InMemorySink())
    body = post_frame(client, edge.token).json()
    assert set(body) == {"state", "stability", "result", "inspection"}
    assert set(body["result"]) == {"object_type", "grade", "type_confidence", "labels_pt"}
    assert set(body["result"]["labels_pt"]) == {"object_type", "grade", "verdict"}
    assert body["state"] == "DETECTING"
    assert body["stability"] == pytest.approx(0.1)
    assert body["result"]["object_type"] == "screw"
    assert body["result"]["grade"] == "fair"
    assert body["result"]["type_confidence"] == pytest.approx(0.9)
    assert body["result"]["labels_pt"]["object_type"] == "parafuso"
    assert body["result"]["labels_pt"]["grade"] == "mediano"


def test_extra_route_saves_the_emitted_frame_not_the_current_one(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    script = [result("screw", "poor", 0.9, latency_ms=1)]
    script += [result("screw", "fair", 0.85, latency_ms=10 + n) for n in range(8)]
    script += [result("screw", "poor", 0.9, latency_ms=99)]
    sink = InMemorySink()
    clock = ManualClock()
    client = run_client(ScriptedInferencer(script), sink, clock=clock)

    images = [jpeg(seed=100 + n) for n in range(10)]
    responses = []
    for n, image in enumerate(images):
        clock.seconds = float(n)
        responses.append(post_frame(client, edge.token, image))

    assert [r.status_code for r in responses] == [200] * 10
    body = responses[9].json()
    assert body["state"] == "EMIT"
    assert body["result"]["grade"] == "poor"  # the current frame
    inspection = body["inspection"]
    assert inspection["grade"] == "fair"  # the emitted frame
    assert inspection["latency_ms"] == 17
    assert datetime.fromisoformat(inspection["inspected_at"]) == T0 + timedelta(seconds=8)
    files = edge.captures()
    assert len(files) == 1
    assert files[0].read_bytes() == images[8]
    assert files[0].parent.name == "2026-11-01"
    assert files[0].name == f"{inspection['inspection_id']}.jpg"


def test_extra_two_parts_two_inspections(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    script = [result() for _ in range(12)] + [unknown() for _ in range(3)]
    script += [result("nut", "good") for _ in range(10)]
    sink = InMemorySink()
    client = run_client(ScriptedInferencer(script), sink)

    responses = send_frames(client, edge.token, 25)

    assert [r.status_code for r in responses] == [200] * 25
    emitted = [n for n, r in enumerate(responses, 1) if r.json()["inspection"] is not None]
    assert emitted == [10, 25]
    ids = {str(i.inspection_id) for i in sink.items}
    assert len(ids) == 2
    assert {p.stem for p in edge.captures()} == ids


def test_extra_sessions_do_not_share_the_window(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    sink = InMemorySink()
    client = run_client(ScriptedInferencer(), sink)
    states = []
    for _ in range(9):
        states.append(post_frame(client, edge.token, session=SESSION_A).json()["inspection"])
        states.append(post_frame(client, edge.token, session=SESSION_B).json()["inspection"])
    assert all(s is None for s in states)
    assert post_frame(client, edge.token, session=SESSION_A).json()["inspection"] is not None
    assert post_frame(client, edge.token, session=SESSION_B).json()["inspection"] is not None
    assert len(sink.items) == 2


def test_extra_lot_change_after_emit_emits_again_for_the_same_part(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    """Section 4.3: changing the lot calls ``reset``, also from ``WAIT_REMOVAL``."""
    sink = InMemorySink()
    client = run_client(ScriptedInferencer(), sink)
    send_frames(client, edge.token, 12, lot_id="LOTE-A")
    after = send_frames(client, edge.token, 10, lot_id="LOTE-B")
    assert [r.json()["inspection"] is not None for r in after] == [False] * 9 + [True]
    assert [i.lot_id for i in sink.items] == ["LOTE-A", "LOTE-B"]


def test_extra_refused_frame_with_another_lot_does_not_reset_the_window(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    client = run_client(ScriptedInferencer(), InMemorySink())
    send_frames(client, edge.token, 9, lot_id="LOTE-A")
    assert post_frame(client, edge.token, lot_id="lote B").status_code == 422
    assert post_frame(client, edge.token, encoded("PNG"), lot_id="LOTE-B").status_code == 415
    emitted = post_frame(client, edge.token, lot_id="LOTE-A").json()["inspection"]
    assert emitted is not None


def test_extra_failed_inference_with_another_lot_changes_nothing(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    """Section 4.4: on ``InferenceError`` the state of the session does not change."""
    script: list[InferenceResult | Exception] = [result() for _ in range(9)]
    script += [InferenceError("acc failure"), result()]
    client = run_client(ScriptedInferencer(script), InMemorySink())
    send_frames(client, edge.token, 9, lot_id="LOTE-A")
    assert post_frame(client, edge.token, lot_id="LOTE-B").status_code == 500
    assert post_frame(client, edge.token, lot_id="LOTE-A").json()["inspection"] is not None


@pytest.mark.parametrize(
    "first_failure, status",
    [(SinkError("x"), 503), (RuntimeError("x"), 500)],
    ids=["sink-error", "other-error"],
)
def test_extra_failure_removes_the_photo_and_resets(
    edge: EdgeEnv,
    run_client: Callable[..., TestClient],
    first_failure: Exception,
    status: int,
) -> None:
    sink = FlakySink({1: first_failure})
    client = run_client(ScriptedInferencer(), sink)
    responses = send_frames(client, edge.token, 20)
    assert responses[9].status_code == status
    assert responses[9].json().get("detail")
    assert [r.json()["state"] for r in responses[10:11]] == ["DETECTING"]
    assert responses[10].json()["stability"] == pytest.approx(0.1)
    assert responses[19].json()["inspection"] is not None
    assert len(sink.items) == 1
    assert [p.stem for p in edge.captures()] == [str(sink.items[0].inspection_id)]


def test_extra_full_disk_answers_500_and_resets(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    sink = InMemorySink()
    client = run_client(ScriptedInferencer(), sink)
    responses = send_frames(client, edge.token, 9)
    # ``captures`` as a regular file: writing the photo fails with an OSError.
    captures = edge.data_dir / "captures"
    if captures.exists():
        captures.rmdir()
    captures.write_text("not a directory", encoding="utf-8")
    failing = post_frame(client, edge.token)
    assert failing.status_code == 500
    assert sink.items == []
    captures.unlink()
    responses = send_frames(client, edge.token, 10)
    assert [r.json()["inspection"] is not None for r in responses] == [False] * 9 + [True]
    assert len(sink.items) == 1


@pytest.mark.parametrize(
    "image",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"not an image", id="text"),
        pytest.param(jpeg()[:40], id="only-the-header"),
        pytest.param(jpeg(320, 240)[:-400], id="truncated"),
        pytest.param(b"\xff\xd8\xff\xe0" + b"\x00" * 200, id="corrupted"),
        pytest.param(encoded("BMP"), id="bmp"),
        pytest.param(encoded("WEBP"), id="webp"),
    ],
)
def test_extra_bad_images_are_refused_without_inference(
    edge: EdgeEnv, run_client: Callable[..., TestClient], image: bytes
) -> None:
    inferencer = ScriptedInferencer()
    client = run_client(inferencer, InMemorySink())
    response = post_frame(client, edge.token, image)
    assert response.status_code == 415, response.text
    assert inferencer.calls == 0
    assert edge.captures() == []


@pytest.mark.parametrize(
    "width, height, expected",
    [
        (1000, 1000, 200),
        (1001, 1000, 415),
        (1000, 1001, 415),
        (1100, 100, 415),  # within 1 M pixels, over the 10:1 ratio of ``load_image``
        (1000, 100, 200),  # exactly 10:1
    ],
)
def test_extra_pixel_limits(
    edge: EdgeEnv,
    run_client: Callable[..., TestClient],
    width: int,
    height: int,
    expected: int,
) -> None:
    inferencer = ScriptedInferencer()
    client = run_client(inferencer, InMemorySink())
    response = post_frame(client, edge.token, jpeg(width, height))
    assert response.status_code == expected, response.text
    assert inferencer.calls == (1 if expected == 200 else 0)


def test_extra_image_of_exactly_one_mib_is_accepted(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    client = run_client(ScriptedInferencer(), InMemorySink())
    response = post_frame(client, edge.token, padded_jpeg(1_048_576))
    assert response.status_code == 200, response.text


def test_extra_content_length_limit_applies_only_to_the_live_route(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    client = run_client(ScriptedInferencer(), InMemorySink())
    over = "1310721"
    assert post_frame(client, edge.token, headers={"Content-Length": over}).status_code == 413
    assert post_frame(client, edge.token, headers={"Content-Length": "1310720"}).status_code != 413
    capture = client.post(
        "/api/capture",
        headers={HEADER: edge.token, "Content-Length": over},
        data={"lot_id": LOT, "mode": "inspect"},
        files={"image": ("foto.jpg", jpeg(), "image/jpeg")},
    )
    assert capture.status_code != 413
    too_big = client.post(
        "/api/capture",
        headers={HEADER: edge.token, "Content-Length": "3670017"},
        data={"lot_id": LOT, "mode": "inspect"},
        files={"image": ("foto.jpg", jpeg(), "image/jpeg")},
    )
    assert too_big.status_code == 413


def test_extra_chunked_body_over_the_limit_is_refused_while_reading(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    inferencer = ScriptedInferencer()
    client = run_client(inferencer, InMemorySink())
    boundary = "acc-boundary"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="lot_id"\r\n\r\n{LOT}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="session"\r\n\r\n{SESSION_A}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="q.jpg"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()

    def body() -> Iterator[bytes]:
        yield head
        yield padded_jpeg(1_048_576)
        yield b"\x00" * 300_000
        yield tail

    response = client.post(
        ROUTE,
        headers={HEADER: edge.token, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        content=body(),
    )
    assert response.status_code == 413, response.text
    assert inferencer.calls == 0


@pytest.mark.parametrize(
    "session, expected",
    [
        ("a" * 15, 422),
        ("a" * 16, 200),
        ("a" * 64, 200),
        ("a" * 65, 422),
        ("A-b_" * 8, 200),
        ("a" * 16 + "\n", 422),
        ("sessão-com-acento-1234", 422),
        ("a" * 15 + "é", 422),
        ("a" * 8 + "/" + "a" * 8, 422),
        ("", 422),
    ],
    ids=[
        "15",
        "16",
        "64",
        "65",
        "dash-underscore",
        "trailing-newline",
        "accent",
        "accent-at-the-end",
        "slash",
        "empty",
    ],
)
def test_extra_session_format(
    edge: EdgeEnv, run_client: Callable[..., TestClient], session: str, expected: int
) -> None:
    client = run_client(ScriptedInferencer(), InMemorySink())
    response = post_frame(client, edge.token, session=session)
    assert response.status_code == expected, response.text


@pytest.mark.parametrize("missing", ["lot_id", "session", "image"])
def test_extra_missing_field_is_422(
    edge: EdgeEnv, run_client: Callable[..., TestClient], missing: str
) -> None:
    inferencer = ScriptedInferencer()
    client = run_client(inferencer, InMemorySink())
    data = {"lot_id": LOT, "session": SESSION_A}
    data.pop(missing, None)
    files = {} if missing == "image" else {"image": ("q.jpg", jpeg(), "image/jpeg")}
    response = client.post(
        ROUTE, headers={HEADER: edge.token}, data=data, files=files or {"x": ("x", b"x")}
    )
    assert response.status_code == 422, response.text
    assert inferencer.calls == 0


@pytest.mark.parametrize("lot", ["", "L" * 41, "lote\n", "lóte", "L;DROP"])
def test_extra_invalid_lot_is_422(
    edge: EdgeEnv, run_client: Callable[..., TestClient], lot: str
) -> None:
    inferencer = ScriptedInferencer()
    client = run_client(inferencer, InMemorySink())
    response = post_frame(client, edge.token, lot_id=lot)
    assert response.status_code == 422, response.text
    assert inferencer.calls == 0


def test_extra_error_order_token_size_fields(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    client = run_client(ScriptedInferencer(), InMemorySink())
    big = padded_jpeg(1_048_577)
    assert post_frame(client, None, big, session="curto").status_code == 401
    assert post_frame(client, "x" * 40, big, session="curto").status_code == 401
    assert post_frame(client, edge.token, big, session="curto").status_code == 413
    assert post_frame(client, edge.token, encoded("PNG"), session="curto").status_code == 422


def test_extra_token_in_query_string_does_not_authorize(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    client = run_client(ScriptedInferencer(), InMemorySink())
    response = client.post(
        ROUTE,
        params={"t": edge.token},
        data={"lot_id": LOT, "session": SESSION_A},
        files={"image": ("q.jpg", jpeg(), "image/jpeg")},
    )
    assert response.status_code == 401


def test_extra_no_model_is_503_after_the_image_check_and_before_the_sessions(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    edge.monkeypatch.setenv("LIVE_MAX_SESSIONS", "1")
    client = run_client(None, InMemorySink())
    assert post_frame(client, edge.token, encoded("PNG")).status_code == 415
    for session in (SESSION_A, SESSION_B):
        response = post_frame(client, edge.token, session=session)
        assert response.status_code == 503
        assert response.json() == {"detail": "model not loaded"}


def test_extra_too_many_sessions_does_not_call_the_model_nor_count_as_a_session(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    edge.monkeypatch.setenv("LIVE_MAX_SESSIONS", "1")
    inferencer = ScriptedInferencer()
    client = run_client(inferencer, InMemorySink())
    assert post_frame(client, edge.token, session=SESSION_A).status_code == 200
    assert inferencer.calls == 1
    assert post_frame(client, edge.token, session=SESSION_B).status_code == 429
    assert inferencer.calls == 1


def test_extra_session_expires_only_after_more_than_60_seconds(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    edge.monkeypatch.setenv("LIVE_MAX_SESSIONS", "1")
    clock = ManualClock()
    client = run_client(ScriptedInferencer(), InMemorySink(), clock=clock)
    assert post_frame(client, edge.token, session=SESSION_A).status_code == 200
    clock.seconds = 60
    assert post_frame(client, edge.token, session=SESSION_B).status_code == 429
    clock.seconds = 60.5
    assert post_frame(client, edge.token, session=SESSION_B).status_code == 200


def test_extra_refused_frames_do_not_refresh_a_session(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    edge.monkeypatch.setenv("LIVE_MAX_SESSIONS", "1")
    clock = ManualClock()
    client = run_client(ScriptedInferencer(), InMemorySink(), clock=clock)
    assert post_frame(client, edge.token, session=SESSION_A).status_code == 200
    clock.seconds = 50
    assert post_frame(client, edge.token, encoded("PNG"), session=SESSION_A).status_code == 415
    clock.seconds = 61
    assert post_frame(client, edge.token, session=SESSION_B).status_code == 200


def test_extra_expired_session_starts_a_new_window(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    clock = ManualClock()
    sink = InMemorySink()
    client = run_client(ScriptedInferencer(), sink, clock=clock)
    send_frames(client, edge.token, 9)
    clock.seconds = 61
    # A sweep may be triggered only by another session, so one more session arrives first.
    post_frame(client, edge.token, session=SESSION_B)
    response = post_frame(client, edge.token)
    assert response.json()["inspection"] is None
    assert response.json()["stability"] == pytest.approx(0.1)


def test_extra_limiter_is_shared_with_the_capture_and_comes_before_the_image_check(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    inferencer = BlockingInferencer()
    client = run_client(inferencer, InMemorySink(), max_concurrent_decodes=1, decode_wait_s=0.05)
    first: list[httpx.Response] = []
    worker = threading.Thread(target=lambda: first.append(post_frame(client, edge.token)))
    worker.start()
    try:
        assert inferencer.started.wait(10)
        busy = post_frame(client, edge.token, session=SESSION_B)
        assert busy.status_code == 503
        assert busy.json() == {"detail": "server busy"}
        # The limiter comes before the image check (415) and after the fields (422).
        assert post_frame(client, edge.token, encoded("PNG"), session=SESSION_B).status_code == 503
        assert post_frame(client, edge.token, session="curto").status_code == 422
        capture = client.post(
            "/api/capture",
            headers={HEADER: edge.token},
            data={"lot_id": LOT, "mode": "inspect"},
            files={"image": ("foto.jpg", jpeg(), "image/jpeg")},
        )
        assert capture.status_code == 503
        assert capture.json() == {"detail": "server busy"}
    finally:
        inferencer.release.set()
        worker.join(20)
    assert first[0].status_code == 200
    assert post_frame(client, edge.token).status_code == 200


def test_extra_simultaneous_requests_of_a_session_emit_once(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    class Slow(ScriptedInferencer):
        def infer(self, image: Image.Image) -> InferenceResult:
            time.sleep(0.005)
            return super().infer(image)

    sink = InMemorySink()
    client = run_client(Slow(), sink, max_concurrent_decodes=2, decode_wait_s=20)
    responses: list[httpx.Response] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(10):
            response = post_frame(client, edge.token)
            with lock:
                responses.append(response)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)

    assert len(responses) == 60
    assert [r.status_code for r in responses] == [200] * 60
    assert len(sink.items) == 1
    assert sum(r.json()["inspection"] is not None for r in responses) == 1
    assert len(edge.captures()) == 1


def test_extra_recording_stays_outside_the_session_lock(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    """Section 4.3: a slow ``put`` of one session does not hold the frames of another."""

    class Gate(InMemorySink):
        def __init__(self) -> None:
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()

        def put(self, inspection: InspectionCreate) -> None:
            self.entered.set()
            assert self.release.wait(20)
            super().put(inspection)

    sink = Gate()
    client = run_client(ScriptedInferencer(), sink, max_concurrent_decodes=2, decode_wait_s=5)
    send_frames(client, edge.token, 9)
    emitting: list[httpx.Response] = []
    worker = threading.Thread(target=lambda: emitting.append(post_frame(client, edge.token)))
    worker.start()
    try:
        assert sink.entered.wait(10)
        started = time.monotonic()
        other = post_frame(client, edge.token, session=SESSION_B)
        elapsed = time.monotonic() - started
    finally:
        sink.release.set()
        worker.join(20)
    assert other.status_code == 200
    assert elapsed < 3, elapsed
    assert emitting[0].json()["inspection"] is not None


def test_extra_provisional_unknown_keeps_the_suffix_and_the_null_grade(
    edge: EdgeEnv, dummy_model: Any, run_client: Callable[..., TestClient]
) -> None:
    client = run_client(edge.model(PROVISIONAL, dummy_model, **OTHER_PROBS), InMemorySink())
    body = post_frame(client, edge.token).json()
    assert body["result"]["labels_pt"]["grade"] is None
    assert body["result"]["labels_pt"]["object_type"] == "desconhecido"
    assert body["result"]["labels_pt"]["verdict"] == "desconhecido" + SUFFIX


def test_extra_tool_without_grade_emits_through_the_route(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    sink = InMemorySink()
    client = run_client(ScriptedInferencer([result("drill", None)]), sink)
    responses = send_frames(client, edge.token, 10)
    body = responses[9].json()
    assert body["inspection"]["object_type"] == "drill"
    assert body["inspection"]["grade"] is None
    assert body["result"]["grade"] is None
    assert body["result"]["labels_pt"]["grade"] is None
    assert len(sink.items) == 1


def test_extra_token_and_image_do_not_reach_the_logs(
    edge: EdgeEnv, run_client: Callable[..., TestClient], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    sink = FlakySink({1: SinkError("acc failure")})
    client = run_client(ScriptedInferencer(), sink)
    client.get("/live", params={"t": edge.token})
    send_frames(client, edge.token, 20)
    post_frame(client, edge.token, encoded("PNG"))
    post_frame(client, None)
    # ``httpx`` is the logger of the test client (the URL of the page), not of the edge.
    records = [record for record in caplog.records if record.name != "httpx"]
    assert records
    for record in records:
        assert edge.token not in record.getMessage()
        assert SESSION_A not in record.getMessage()


# =========================================================================== extras: latency


def test_extra_latency_keeps_only_the_last_100_frames(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    script = [result(latency_ms=1000) for _ in range(5)] + [result(latency_ms=10)]
    client = run_client(ScriptedInferencer(script), InMemorySink())
    send_frames(client, edge.token, 4)
    assert re.search(r"1000 ms.*p95.*1000 ms", latency_text(console_get(client.app).text))
    send_frames(client, edge.token, 101)
    text = latency_text(console_get(client.app).text)
    assert re.search(r"10 ms.*p95.*10 ms", text) and "1000" not in text, text


def test_extra_latency_rank_at_the_edge_of_the_formula(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    """21 frames: ``ceil(0.95 * 21) - 1 = 19`` selects the second highest of the sorted values."""
    script = [result(latency_ms=500), result(latency_ms=400)] + [result(latency_ms=7)]
    client = run_client(ScriptedInferencer(script), InMemorySink())
    send_frames(client, edge.token, 21)
    text = latency_text(console_get(client.app).text)
    assert re.search(r"7 ms.*p95.*400 ms", text), text


def test_extra_latency_is_shared_by_sessions_and_ignores_refused_frames(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    script: list[InferenceResult | Exception] = [
        result(latency_ms=11),
        result(latency_ms=22),
        InferenceError("acc failure"),
    ]
    client = run_client(ScriptedInferencer(script), InMemorySink())
    assert post_frame(client, edge.token, session=SESSION_A).status_code == 200
    assert post_frame(client, edge.token, session=SESSION_B).status_code == 200
    assert post_frame(client, edge.token, session=SESSION_B).status_code == 500
    assert post_frame(client, edge.token, encoded("PNG")).status_code == 415
    text = latency_text(console_get(client.app).text)
    assert re.search(r"22 ms.*p95.*22 ms", text), text


# =========================================================================== extras: page


def test_extra_page_gets_the_fps_and_the_script_has_the_section_rules(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    edge.monkeypatch.setenv("LIVE_FPS", "5")
    client = run_client(ScriptedInferencer(), InMemorySink())
    page = client.get("/live", params={"t": edge.token})
    assert re.search(r'fps[^>]*"5"', page.text, re.IGNORECASE)
    script = client.get("/static/live.js").text
    assert INSECURE_MESSAGE in script or INSECURE_MESSAGE in page.text
    assert "getRandomValues" in script
    assert "/api/live/frame" in script
    assert "environment" in script
    assert "640" in script
    assert "0.8" in script
    assert "image/jpeg" in script
    assert "canvas" in script.lower() or "canvas" in page.text.lower()
    # Nothing leaves the LAN (R-02), and neither file has a secret or a framework (section 4.5).
    for text in (page.text, script):
        assert not re.search(r"https?://(?!www\.w3\.org)", text)
        assert not re.search(r"<script[^>]+src=\"(?!/static/)", text)
    assert edge.token not in script


def test_extra_page_with_a_token_of_another_length_is_refused(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    client = run_client(ScriptedInferencer(), InMemorySink())
    for value in ("", "x", edge.token + "x", "ação"):
        response = client.get("/live", params={"t": value})
        assert response.status_code == 401, value
        assert_page_headers(response)


# =========================================================================== extras: configuration


@pytest.mark.parametrize(
    "env, expected",
    [
        ({"LIVE_WINDOW": "3", "LIVE_MIN_AGREE": "3"}, 0),
        ({"LIVE_WINDOW": "30"}, 0),
        ({"LIVE_WINDOW": "31"}, 2),
        ({"LIVE_WINDOW": "abc"}, 2),
        ({"LIVE_WINDOW": "10.5"}, 2),
        ({"LIVE_WINDOW": "5"}, 2),  # the default LIVE_MIN_AGREE of 8 is over the window
        ({"LIVE_MIN_AGREE": "1"}, 0),
        ({"LIVE_MIN_AGREE": "0"}, 2),
        ({"LIVE_MIN_AGREE": "10"}, 0),
        ({"LIVE_MIN_CONFIDENCE": "0.5"}, 0),
        ({"LIVE_MIN_CONFIDENCE": "0.99"}, 0),
        ({"LIVE_MIN_CONFIDENCE": "0.49"}, 2),
        ({"LIVE_MIN_CONFIDENCE": "1.0"}, 2),
        ({"LIVE_MIN_CONFIDENCE": "nan"}, 2),
        ({"LIVE_MIN_CONFIDENCE": "abc"}, 2),
        ({"LIVE_EMPTY_FRAMES": "1"}, 0),
        ({"LIVE_EMPTY_FRAMES": "10"}, 0),
        ({"LIVE_EMPTY_FRAMES": "0"}, 2),
        ({"LIVE_EMPTY_FRAMES": "11"}, 2),
        ({"LIVE_MAX_SESSIONS": "1"}, 0),
        ({"LIVE_MAX_SESSIONS": "8"}, 0),
        ({"LIVE_MAX_SESSIONS": "9"}, 2),
        ({"LIVE_FPS": "1"}, 0),
        ({"LIVE_FPS": "5"}, 0),
        ({"LIVE_FPS": "0"}, 2),
        ({"LIVE_FPS": "6"}, 2),
        ({"LIVE_FPS": "2.5"}, 2),
    ],
    ids=lambda v: "-".join(f"{k}={x}" for k, x in v.items()) if isinstance(v, dict) else str(v),
)
def test_extra_section_4_6_limits(
    edge: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    env: dict[str, str],
    expected: int,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    boot = boot_edge(monkeypatch, caplog, capsys)
    assert boot.code == expected, boot.text
    assert len(boot.calls) == (1 if expected == 0 else 0)
    if expected == 2:
        assert next(iter(env)) in boot.text or "LIVE_MIN_AGREE" in boot.text


@pytest.mark.parametrize(
    "mode, expected",
    [(0o600, 0), (0o400, 0), (0o640, 2), (0o604, 2), (0o660, 2), (0o610, 2), (0o601, 2)],
    ids=oct,
)
def test_extra_key_mode(
    edge: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    mode: int,
    expected: int,
) -> None:
    cert, key = tls_files(edge.tmp, key_mode=mode)
    monkeypatch.setenv("EDGE_TLS_CERT", str(cert))
    monkeypatch.setenv("EDGE_TLS_KEY", str(key))
    boot = boot_edge(monkeypatch, caplog, capsys)
    assert boot.code == expected, boot.text
    if expected == 2:
        assert "EDGE_TLS_KEY" in boot.text


def test_extra_directory_and_unreadable_file_are_refused(
    edge: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cert, key = tls_files(edge.tmp)
    monkeypatch.setenv("EDGE_TLS_CERT", str(edge.tmp))
    monkeypatch.setenv("EDGE_TLS_KEY", str(key))
    boot = boot_edge(monkeypatch, caplog, capsys)
    assert boot.code == 2
    assert "EDGE_TLS_CERT" in boot.text

    if os.geteuid() != 0:  # root opens everything
        cert.chmod(0o000)
        monkeypatch.setenv("EDGE_TLS_CERT", str(cert))
        boot = boot_edge(monkeypatch, caplog, capsys)
        assert boot.code == 2
        assert "EDGE_TLS_CERT" in boot.text
        cert.chmod(0o644)


def test_extra_console_with_tls_stays_on_loopback(
    edge: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    run_client: Callable[..., TestClient],
) -> None:
    cert, key = tls_files(edge.tmp)
    monkeypatch.setenv("EDGE_TLS_CERT", str(cert))
    monkeypatch.setenv("EDGE_TLS_KEY", str(key))
    client = run_client(ScriptedInferencer(), InMemorySink())
    app = client.app

    assert console_get(app, scheme="https", host=f"127.0.0.1:{PORT}").status_code == 200
    assert console_get(app, scheme="https", host=f"localhost:{PORT}").status_code == 200
    assert console_get(app, scheme="https", host=f"{LAN_IP}:{PORT}").status_code == 403
    assert console_get(app, scheme="https", host="attacker.example").status_code == 403
    # A LAN client is refused too, whatever the Host says.
    assert client.get("/").status_code == 403
    # With TLS, the Host without a port is only for 443; on 8000 it is refused.
    assert console_get(app, scheme="https", host="127.0.0.1").status_code == 403


def test_extra_stub_model_serves_the_route_without_an_outbox(
    edge: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Section 4.4: with ``--stub-model`` the route works and the sink is ``InMemorySink``."""
    monkeypatch.setenv("DEVICE_API_KEY", "acc-key-" + secrets.token_hex(8))
    monkeypatch.setenv("CLOUD_API_URL", "https://cloud.invalid")
    boot = boot_edge(monkeypatch, caplog, capsys, "--stub-model")
    assert boot.code == 0
    with TestClient(boot.calls[0][0][0]) as client:
        responses = send_frames(client, edge.token, 12)
    assert [r.status_code for r in responses] == [200] * 12
    assert sum(r.json()["inspection"] is not None for r in responses) == 1
    assert not list(edge.data_dir.rglob("*.sqlite3"))
    assert not list(edge.data_dir.rglob("*.db"))


# =========================================================================== extras: wiring


def test_extra_settings_reach_the_state_machine_of_the_route(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    edge.monkeypatch.setenv("LIVE_WINDOW", "3")
    edge.monkeypatch.setenv("LIVE_MIN_AGREE", "3")
    edge.monkeypatch.setenv("LIVE_EMPTY_FRAMES", "1")
    script = [result() for _ in range(3)] + [unknown()] + [result("nut", "good")]
    client = run_client(ScriptedInferencer(script), InMemorySink())
    responses = send_frames(client, edge.token, 7)
    states = [r.json()["state"] for r in responses]
    assert states == ["DETECTING", "DETECTING", "EMIT", "IDLE", "DETECTING", "DETECTING", "EMIT"]


def test_extra_min_confidence_setting_reaches_the_route(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    edge.monkeypatch.setenv("LIVE_MIN_CONFIDENCE", "0.95")
    sink = InMemorySink()
    client = run_client(ScriptedInferencer([result(confidence=0.9)]), sink)
    responses = send_frames(client, edge.token, 15)
    assert all(r.json()["inspection"] is None for r in responses)
    assert sink.items == []


def test_extra_emit_can_come_on_an_unknown_frame_and_brings_the_stable_frame(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    script = [result() for _ in range(8)] + [unknown(), unknown()]
    sink = InMemorySink()
    client = run_client(ScriptedInferencer(script), sink)
    images = [jpeg(seed=300 + n) for n in range(10)]
    responses = [post_frame(client, edge.token, image) for image in images]
    body = responses[9].json()
    assert body["state"] == "EMIT"
    assert body["result"]["object_type"] == "unknown"
    assert body["inspection"]["object_type"] == "screw"
    assert edge.captures()[0].read_bytes() == images[7]


def test_extra_emitted_inspection_appears_in_the_console(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    client = run_client(ScriptedInferencer(), InMemorySink())
    send_frames(client, edge.token, 10, lot_id="LOTE-CONSOLE")
    assert "LOTE-CONSOLE" in console_get(client.app).text


def test_extra_idle_session_is_dropped_without_a_new_request(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    """Section 4.2: the frames leave memory at the end of the session, even if no request comes."""
    edge.monkeypatch.setattr("qc_edge.app.LIVE_SWEEP_INTERVAL_S", 0.01)
    clock = ManualClock()
    client = run_client(ScriptedInferencer(), InMemorySink(), clock=clock)
    assert post_frame(client, edge.token).status_code == 200
    sessions = client.app.state.live_sessions
    assert len(sessions) == 1
    clock.seconds = 61
    deadline = time.monotonic() + 5
    while len(sessions) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(sessions) == 0


def test_extra_clock_going_backwards_does_not_hold_a_slot_forever(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    """Accepted decision 2 of the dev report (History of the SPEC, 2026-11-01)."""
    edge.monkeypatch.setenv("LIVE_MAX_SESSIONS", "1")
    clock = ManualClock()
    clock.seconds = 1000
    client = run_client(ScriptedInferencer(), InMemorySink(), clock=clock)
    assert post_frame(client, edge.token, session=SESSION_A).status_code == 200
    clock.seconds = 0
    assert post_frame(client, edge.token, session=SESSION_B).status_code == 429
    clock.seconds = 61
    assert post_frame(client, edge.token, session=SESSION_B).status_code == 200


def test_extra_session_limit_holds_under_concurrency(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    edge.monkeypatch.setenv("LIVE_MAX_SESSIONS", "2")
    client = run_client(ScriptedInferencer(), InMemorySink(), decode_wait_s=20)
    codes: list[int] = []
    lock = threading.Lock()

    def worker(n: int) -> None:
        response = post_frame(client, edge.token, session=f"sessao-{n:02d}-" + "x" * 16)
        with lock:
            codes.append(response.status_code)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(codes) == [200, 200] + [429] * 6
    assert len(client.app.state.live_sessions) == 2


# =========================================================================== extras: hostile input


def test_extra_mutated_jpegs_never_answer_500(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    client = run_client(ScriptedInferencer(), InMemorySink())
    rng = np.random.default_rng(19)
    base = bytearray(jpeg(128, 96))
    codes = set()
    for _ in range(150):
        mutated = bytearray(base)
        for position in rng.integers(0, len(base), size=int(rng.integers(1, 12))):
            mutated[int(position)] = int(rng.integers(0, 256))
        cut = int(rng.integers(2, len(base) + 1))
        data = bytes(mutated[:cut]) if rng.random() < 0.3 else bytes(mutated)
        response = post_frame(client, edge.token, data)
        codes.add(response.status_code)
        assert response.status_code in (200, 415), response.text
    assert 415 in codes


@pytest.mark.parametrize(
    "kind",
    [
        "urlencoded",
        "json",
        "no-boundary",
        "bad-multipart",
        "image-as-text-field",
        "two-images",
        "huge-session-field",
        "invalid-utf8-lot",
        "many-fields",
    ],
)
def test_extra_malformed_requests_are_client_errors(
    edge: EdgeEnv, run_client: Callable[..., TestClient], kind: str
) -> None:
    inferencer = ScriptedInferencer()
    client = run_client(inferencer, InMemorySink())
    headers = {HEADER: edge.token}
    fields = {"lot_id": LOT, "session": SESSION_A}
    image = ("q.jpg", jpeg(), "image/jpeg")
    boundary = "acc-boundary"
    multipart = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if kind == "urlencoded":
        response = client.post(ROUTE, headers=headers, data={**fields, "image": "x"})
    elif kind == "json":
        response = client.post(ROUTE, headers=headers, json=fields)
    elif kind == "no-boundary":
        response = client.post(
            ROUTE, headers={**headers, "Content-Type": "multipart/form-data"}, content=b"x"
        )
    elif kind == "bad-multipart":
        response = client.post(
            ROUTE, headers={**headers, **multipart}, content=f"--{boundary}\r\ngarbage".encode()
        )
    elif kind == "image-as-text-field":
        response = client.post(ROUTE, headers=headers, data={**fields, "image": "text"})
    elif kind == "two-images":
        response = client.post(
            ROUTE, headers=headers, data=fields, files=[("image", image), ("image", image)]
        )
    elif kind == "huge-session-field":
        response = client.post(
            ROUTE,
            headers=headers,
            data={"lot_id": LOT, "session": "a" * 1_100_000},
            files={"image": image},
        )
    elif kind == "invalid-utf8-lot":
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="lot_id"\r\n\r\n'.encode()
            + b"\xff\xfe"
            + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="session"\r\n\r\n'.encode()
            + SESSION_A.encode()
            + f"\r\n--{boundary}\r\n".encode()
            + b'Content-Disposition: form-data; name="image"; filename="q.jpg"\r\n'
            + b"Content-Type: image/jpeg\r\n\r\n"
            + jpeg()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        response = client.post(ROUTE, headers={**headers, **multipart}, content=body)
    else:
        many = {f"f{n}": "x" for n in range(100)}
        response = client.post(
            ROUTE, headers=headers, data={**fields, **many}, files={"image": image}
        )
    assert 400 <= response.status_code < 500, (kind, response.status_code, response.text)
    assert inferencer.calls == 0


def test_extra_other_image_kinds_of_a_valid_jpeg(
    edge: EdgeEnv, run_client: Callable[..., TestClient]
) -> None:
    client = run_client(ScriptedInferencer(), InMemorySink())
    base = Image.new("RGB", (64, 48), "steelblue")
    variants = {}
    for name, image, save in [
        ("gray", base.convert("L"), {}),
        ("cmyk", base.convert("CMYK"), {}),
        ("progressive", base, {"progressive": True}),
    ]:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", **save)
        variants[name] = buffer.getvalue()
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    base.save(buffer, format="JPEG", exif=exif.tobytes())
    variants["exif-rotation"] = buffer.getvalue()
    for name, data in variants.items():
        response = post_frame(client, edge.token, data)
        assert response.status_code == 200, (name, response.text)


# ================================================================== extras: console and docs


def test_extra_console_with_tls_uses_the_chosen_ip_in_both_urls(
    edge: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    run_client: Callable[..., TestClient],
) -> None:
    cert, key = tls_files(edge.tmp)
    monkeypatch.setenv("EDGE_TLS_CERT", str(cert))
    monkeypatch.setenv("EDGE_TLS_KEY", str(key))
    monkeypatch.setattr(qc_edge.netinfo, "detect_lan_ips", lambda: [LAN_IP, "10.0.0.7"])
    client = run_client(ScriptedInferencer(), InMemorySink())

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=client.app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(
            transport=transport, base_url=f"https://127.0.0.1:{PORT}"
        ) as c:
            return await c.get("/?ip=10.0.0.7")

    page = asyncio.run(go()).text
    assert f"https://10.0.0.7:{PORT}/capture?t={edge.token}" in page
    assert f"https://10.0.0.7:{PORT}/live?t={edge.token}" in page
    assert f"https://{LAN_IP}" not in page


@pytest.mark.parametrize(
    "port, host, expected",
    [(443, "127.0.0.1", 200), (443, "localhost", 200), (80, "127.0.0.1", 403)],
    ids=["443-ip", "443-name", "80-with-tls"],
)
def test_extra_host_without_port_with_tls(
    edge: EdgeEnv,
    monkeypatch: pytest.MonkeyPatch,
    run_client: Callable[..., TestClient],
    port: int,
    host: str,
    expected: int,
) -> None:
    """Accepted decision 7 of the dev report (History of the SPEC, 2026-11-01)."""
    cert, key = tls_files(edge.tmp)
    monkeypatch.setenv("EDGE_TLS_CERT", str(cert))
    monkeypatch.setenv("EDGE_TLS_KEY", str(key))
    monkeypatch.setenv("EDGE_PORT", str(port))
    client = run_client(ScriptedInferencer(), InMemorySink())
    assert console_get(client.app, scheme="https", host=host).status_code == expected


def test_extra_env_example_and_readme_document_the_section() -> None:
    root = Path(__file__).resolve().parents[3]
    example = (root / ".env.example").read_text(encoding="utf-8")
    for name in (
        "EDGE_TLS_CERT",
        "EDGE_TLS_KEY",
        "LIVE_WINDOW",
        "LIVE_MIN_AGREE",
        "LIVE_MIN_CONFIDENCE",
        "LIVE_EMPTY_FRAMES",
        "LIVE_MAX_SESSIONS",
        "LIVE_FPS",
    ):
        assert re.search(rf"^{name}=", example, re.MULTILINE), name
    assert re.search(r"^EDGE_TLS_KEY=$", example, re.MULTILINE)
    readme = (root / "edge" / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Vídeo ao vivo (HTTPS)", 1)[1]
    for needle in ("mkcert", "rootCA.pem", "edge/data/tls", "0600"):
        assert needle in section, needle
