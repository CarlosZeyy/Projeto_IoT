"""Acceptance tests for SPEC-007 (qc-edge: gateway, capture page and pairing).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers the automatable CAs (CA-01 to CA-19 and CA-22 to CA-27); CA-20 and
CA-21 are manual (real phones) and are recorded in ``reviews/SPEC-007/r1-test-report.md``.
Tests named ``test_extra_*`` are exploratory edge cases around the SPEC that no CA spells out.

Rules followed (``reviews/checklist.md``): every token and key is built at run time (no
credential literal in a URL or header), images are generated in memory (no binary in Git),
no test runs the test suite in a subprocess, and the only boundaries mocked are the socket,
the clock, ``uvicorn.run`` and the inferencer (through the SPEC's own interfaces).
"""

from __future__ import annotations

import ast
import asyncio
import io
import json
import logging
import os
import re
import secrets
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import types
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from PIL import Image, ImageFile

import qc_edge.cli
import qc_edge.netinfo
from qc_contracts import Grade, InspectionCreate, ObjectType
from qc_edge import limits
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import (
    InferenceError,
    InferenceResult,
    ModelInfo,
    StubInferencer,
)
from qc_edge.limits import load_capture_image
from qc_edge.netinfo import detect_lan_ips
from qc_edge.sink import InMemorySink, SinkError, SinkStats
from qc_preprocess import InvalidImageError, load_image

pytestmark = pytest.mark.acceptance

EDGE_ROOT = Path(__file__).resolve().parents[2]  # edge/
ROOT = EDGE_ROOT.parent  # repository root
SRC = EDGE_ROOT / "src" / "qc_edge"

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

SESSION_HEADER = "X-Session-Token"
INVALID_SESSION_TEXT = "Sessão inválida. Leia o QR code no console."
FLAG = "LOAD_TRUNCATED_IMAGES"
SOI = b"\xff\xd8"
SOS = b"\xff\xda"
EOI = b"\xff\xd9"


def new_token() -> str:
    """40 URL-safe characters, generated at run time (never a literal)."""
    value = secrets.token_urlsafe(30)
    assert len(value) == 40
    return value


# --------------------------------------------------------------------------- images


def encode(img: Image.Image, fmt: str, **kwargs: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def solid_jpeg(width: int = 64, height: int = 48, color: str = "steelblue") -> bytes:
    return encode(Image.new("RGB", (width, height), color), "JPEG", quality=90)


def textured_jpeg(width: int = 256, height: int = 256) -> bytes:
    img = Image.new("RGB", (width, height))
    img.putdata(
        [
            ((x * 7 + y * 3) % 256, (x * x + 5 * y) % 256, (x * y + 11) % 256)
            for y in range(height)
            for x in range(width)
        ]
    )
    return encode(img, "JPEG", quality=95)


def solid_png(width: int, height: int, mode: str = "RGB") -> bytes:
    return encode(Image.new(mode, (width, height)), "PNG")


def gif_bytes() -> bytes:
    return encode(Image.new("P", (32, 32)), "GIF")


def jpeg_with_scan_com(pairs: int = 64) -> bytes:
    """Valid 64x48 JPEG with a COM segment right after SOI holding ``pairs`` ``FF DA``."""
    jpeg = solid_jpeg()
    payload = SOS * pairs
    segment = b"\xff\xfe" + struct.pack(">H", len(payload) + 2) + payload
    data = jpeg[:2] + segment + jpeg[2:]
    assert data.count(SOS) == pairs + 1
    return data


def truncated_jpeg() -> bytes:
    data = textured_jpeg()
    return data[: len(data) * 6 // 10]


def padded_jpeg(total: int) -> bytes:
    """Valid 64x48 JPEG followed by ``00`` bytes after EOI up to exactly ``total`` bytes."""
    jpeg = solid_jpeg()
    assert jpeg.endswith(EOI)
    return jpeg + b"\x00" * (total - len(jpeg))


# --------------------------------------------------------------------------- doubles


def result(
    object_type: ObjectType = ObjectType.SCREW,
    grade: Grade | None = Grade.GOOD,
    needs_review: bool = False,
) -> InferenceResult:
    graded = grade is not None
    return InferenceResult(
        object_type=object_type,
        grade=grade,
        grade_score=1.2 if graded else None,
        type_confidence=0.93,
        grade_confidence=0.81 if graded else None,
        needs_review=needs_review,
        latency_ms=17,
    )


class RecordingSink:
    """InspectionSink double that records every ``put`` (the SPEC's Protocol)."""

    def __init__(self, fail: bool = False) -> None:
        self.items: list[InspectionCreate] = []
        self.fail = fail
        self.calls = 0
        self.lock = threading.Lock()

    def put(self, inspection: InspectionCreate) -> None:
        with self.lock:
            self.calls += 1
            if self.fail:
                raise SinkError("disk full")
            self.items.append(inspection)

    def stats(self) -> SinkStats:
        return SinkStats(
            pending=len(self.items), dead=0, last_success_at=None, connectivity="disabled"
        )


class RaisingInferencer:
    """Raises ``InferenceError`` on the calls listed in ``fail_on`` (1-based)."""

    def __init__(self, fail_on: set[int] | None = None) -> None:
        self.fail_on = fail_on if fail_on is not None else {1}
        self.calls = 0
        self.lock = threading.Lock()

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo("acc-model-v1", "a" * 64)

    def infer(self, image: Image.Image) -> InferenceResult:
        with self.lock:
            self.calls += 1
            n = self.calls
        if n in self.fail_on:
            raise InferenceError("boom")
        return result()


class BlockingInferencer:
    """Records concurrent ``infer`` calls and blocks until ``release`` is set (CA-22/23)."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo("acc-model-v1", "b" * 64)

    def infer(self, image: Image.Image) -> InferenceResult:
        with self.lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            assert self.release.wait(timeout=15), "test event never released"
            return result()
        finally:
            with self.lock:
                self.active -= 1


@dataclass
class Clock:
    """Injected clock (boundary): a fixed instant, 1 minute in the past (never in the future)."""

    value: datetime = field(
        default_factory=lambda: (datetime.now(UTC) - timedelta(minutes=1)).replace(microsecond=0)
    )

    def __call__(self) -> datetime:
        return self.value


# --------------------------------------------------------------------------- fixtures


@dataclass
class Edge:
    tmp: Path
    data_dir: Path
    token: str
    monkeypatch: pytest.MonkeyPatch

    def settings(self) -> EdgeSettings:
        return EdgeSettings()

    def app(
        self,
        inferencer: Any = "stub",
        sink: Any = None,
        **kwargs: Any,
    ) -> tuple[Any, Any, Any]:
        inf = StubInferencer(result()) if inferencer == "stub" else inferencer
        snk = sink if sink is not None else InMemorySink()
        app = create_app(self.settings(), inf, snk, **kwargs)
        return app, inf, snk

    def files(self) -> list[Path]:
        return sorted(p for p in self.tmp.rglob("*") if p.is_file())

    def captures(self) -> list[Path]:
        root = self.data_dir / "captures"
        return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


@pytest.fixture
def edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Edge:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    data_dir = tmp_path / "edge-data"
    token = new_token()
    monkeypatch.setenv("EDGE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    return Edge(tmp=tmp_path, data_dir=data_dir, token=token, monkeypatch=monkeypatch)


@pytest.fixture
def lan(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Replace the socket boundary seen by ``qc_edge.netinfo``."""

    def _install(probe_ip: str | None, addrinfo: list[str] | None) -> None:
        monkeypatch.setattr(qc_edge.netinfo, "socket", fake_socket_module(probe_ip, addrinfo))

    return _install


def fake_socket_module(probe_ip: str | None, addrinfo: list[str] | None) -> Any:
    """Copy of the ``socket`` module where the UDP probe and ``getaddrinfo`` are simulated.

    ``probe_ip=None`` makes the UDP probe fail; ``addrinfo=None`` makes ``getaddrinfo`` fail.
    """

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
            if probe_ip is None:
                raise OSError(101, "Network is unreachable")

        def getsockname(self) -> tuple[str, int]:
            if probe_ip is None:
                raise OSError(107, "not connected")
            return (probe_ip, 54321)

        def close(self) -> None:
            pass

    def fake_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> list[Any]:
        if addrinfo is None:
            raise socket.gaierror(-2, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0)) for ip in addrinfo]

    module = types.SimpleNamespace(**vars(socket))
    module.socket = FakeSocket
    module.getaddrinfo = fake_getaddrinfo
    module.gethostname = lambda: "acc-notebook"
    return module


def post_capture(
    client: TestClient,
    token: str | None,
    image: bytes | None = None,
    *,
    lot_id: str | None = "L-001",
    mode: str | None = "inspect",
    filename: str = "foto.jpg",
    content_type: str = "image/jpeg",
) -> httpx.Response:
    headers = {SESSION_HEADER: token} if token is not None else {}
    data = {}
    if lot_id is not None:
        data["lot_id"] = lot_id
    if mode is not None:
        data["mode"] = mode
    files = {"image": (filename, image, content_type)} if image is not None else None
    if files is None:
        # force multipart even without a file
        files = {"other": ("x.txt", b"x", "text/plain")}
    return client.post("/api/capture", headers=headers, data=data, files=files)


def asgi_get(
    app: Any,
    path: str = "/",
    client: tuple[str, int] = ("127.0.0.1", 50000),
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET through ``httpx.ASGITransport`` with a simulated client address (SPEC §6)."""

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            return await c.get(path, headers=headers)

    return asyncio.run(go())


def run_main(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["qc-edge", *args])
    try:
        qc_edge.cli.main()
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return 0


class UvicornSpy:
    def __init__(self, on_call: Callable[[Any], None] | None = None) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.on_call = on_call

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))
        if self.on_call is not None:
            self.on_call(args[0] if args else kwargs.get("app"))

    @property
    def app(self) -> Any:
        args, kwargs = self.calls[-1]
        return args[0] if args else kwargs.get("app")


def captured_text(caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> str:
    out = capsys.readouterr()
    return "\n".join([caplog.text, out.out, out.err])


# =========================================================================== CA-01


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("EDGE_PORT", "70000"),
        ("DEVICE_ID", "Edge_01"),
        ("DEVICE_ID", "edge-01\n"),
        ("EDGE_SESSION_TOKEN", "short"),  # replaced by a 10-char runtime value below
    ],
    ids=["port-70000", "device-Edge_01", "device-trailing-newline", "token-10-chars"],
)
def test_ca01_invalid_configuration_exits_2_naming_the_variable(
    edge: Edge,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    variable: str,
    value: str,
) -> None:
    if variable == "EDGE_SESSION_TOKEN":
        value = secrets.token_hex(5)  # 10 characters
        assert len(value) == 10
    monkeypatch.setenv(variable, value)
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    caplog.set_level(logging.DEBUG)

    code = run_main(monkeypatch)

    assert code == 2
    assert spy.calls == []
    assert variable in captured_text(caplog, capsys)


# =========================================================================== CA-02


def _console_token(app: Any) -> str:
    response = asgi_get(app)
    assert response.status_code == 200
    match = re.search(r"/capture\?t=([^\s\"'<&]+)", response.text)
    assert match, "console has no pairing URL"
    return match.group(1)


def test_ca02_generated_tokens_are_long_urlsafe_and_distinct(
    edge: Edge, monkeypatch: pytest.MonkeyPatch, lan: Callable[..., None]
) -> None:
    lan("192.168.0.42", [])
    monkeypatch.delenv("EDGE_SESSION_TOKEN")

    tokens = []
    for _ in range(2):
        app, _, _ = edge.app()
        token = _console_token(app)
        tokens.append(token)
        assert len(token) >= 43
        assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
        with TestClient(app) as client:
            assert client.get("/api/status", headers={SESSION_HEADER: token}).status_code == 200
    assert tokens[0] != tokens[1]


def test_ca02_configured_40_char_token_is_the_one_accepted(edge: Edge) -> None:
    assert len(edge.token) == 40
    app, _, _ = edge.app()
    with TestClient(app) as client:
        assert client.get("/api/status", headers={SESSION_HEADER: edge.token}).status_code == 200
        other = new_token()
        assert client.get("/api/status", headers={SESSION_HEADER: other}).status_code == 401
        r = post_capture(client, edge.token, solid_jpeg())
        assert r.status_code == 200


# =========================================================================== CA-03


def test_ca03_successful_capture(edge: Edge) -> None:
    clock = Clock()
    sink = RecordingSink()
    stub = StubInferencer(result(ObjectType.SCREW, Grade.GOOD))
    app, _, _ = edge.app(stub, sink, clock=clock)
    with TestClient(app) as client:
        r = post_capture(client, edge.token, solid_jpeg(), lot_id="L-001", mode="inspect")

    assert r.status_code == 200, r.text
    body = r.json()
    insp = body["inspection"]
    assert set(insp) == CONTRACT_FIELDS
    assert insp["source"] == "live"
    assert insp["device_id"] == "edge-01"
    assert insp["lot_id"] == "L-001"
    assert insp["object_type"] == "screw"
    assert insp["grade"] == "good"
    assert insp["model_version"] == "stub-v0"
    assert insp["model_sha256"] == "0" * 64
    assert uuid.UUID(insp["inspection_id"]).version == 4
    inspected_at = datetime.fromisoformat(insp["inspected_at"].replace("Z", "+00:00"))
    assert inspected_at.utcoffset() == timedelta(0)
    assert inspected_at == clock.value
    assert body["approved"] is True
    assert body["labels_pt"] == {"object_type": "parafuso", "grade": "bom", "verdict": "aprovada"}

    day = clock.value.astimezone(UTC).date().isoformat()
    photo = edge.data_dir / "captures" / day / f"{insp['inspection_id']}.jpg"
    assert photo.is_file()
    assert edge.captures() == [photo]

    assert len(sink.items) == 1
    assert sink.items[0] == InspectionCreate.model_validate(insp)
    assert sink.items[0].model_dump(mode="json") == insp
    assert stub.calls == 1


def test_ca03_device_id_comes_from_the_configuration(
    edge: Edge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVICE_ID", "bancada-7")
    sink = InMemorySink()
    app, _, _ = edge.app(sink=sink, clock=Clock())
    with TestClient(app) as client:
        r = post_capture(client, edge.token, solid_jpeg())
    assert r.status_code == 200
    assert r.json()["inspection"]["device_id"] == "bancada-7"
    assert sink.stats().pending == 1


# =========================================================================== CA-04


@pytest.mark.parametrize(
    ("object_type", "grade", "approved", "labels"),
    [
        (
            ObjectType.NUT,
            Grade.POOR,
            False,
            {"object_type": "porca", "grade": "ruim", "verdict": "reprovada"},
        ),
        (
            ObjectType.UNKNOWN,
            None,
            None,
            {"object_type": "desconhecido", "grade": None, "verdict": "desconhecido"},
        ),
    ],
    ids=["nut-poor", "unknown"],
)
def test_ca04_verdicts(
    edge: Edge,
    object_type: ObjectType,
    grade: Grade | None,
    approved: bool | None,
    labels: dict[str, Any],
) -> None:
    app, _, _ = edge.app(StubInferencer(result(object_type, grade)))
    with TestClient(app) as client:
        r = post_capture(client, edge.token, solid_jpeg())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approved"] is approved
    assert body["labels_pt"] == labels
    assert body["labels_pt"]["verdict"] == labels["verdict"]
    if grade is None:
        assert body["labels_pt"]["grade"] is None
        assert body["inspection"]["grade"] is None


# =========================================================================== CA-05


def test_ca05_sink_error_is_503_and_nothing_is_kept(edge: Edge) -> None:
    sink = RecordingSink(fail=True)
    app, _, _ = edge.app(sink=sink)
    with TestClient(app) as client:
        r = post_capture(client, edge.token, solid_jpeg())
    assert r.status_code == 503
    assert r.json() == {"detail": "failed to persist inspection"}
    assert sink.calls == 1
    assert sink.items == []
    assert edge.captures() == []


# =========================================================================== CA-06


@pytest.mark.parametrize("token_kind", ["missing", "wrong"])
def test_ca06_missing_or_wrong_token_is_401(edge: Edge, token_kind: str) -> None:
    app, stub, sink = edge.app()
    token = None if token_kind == "missing" else new_token()
    before = edge.files()
    with TestClient(app) as client:
        r = post_capture(client, token, solid_jpeg())
        assert r.status_code == 401
        assert "detail" in r.json()
        headers = {SESSION_HEADER: token} if token else {}
        s = client.get("/api/status", headers=headers)
        assert s.status_code == 401
        # the token in the query string does not authenticate the API
        q = client.get("/api/status", params={"t": edge.token})
        assert q.status_code == 401
    assert stub.calls == 0
    assert sink.stats().pending == 0
    assert edge.files() == before


# =========================================================================== CA-07


def multipart_body(
    image: bytes, boundary: str, lot_id: str = "L-001", mode: str = "inspect"
) -> bytes:
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="lot_id"\r\n\r\n'.encode()
        + f"{lot_id}\r\n".encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="mode"\r\n\r\n'.encode()
        + f"{mode}\r\n".encode(),
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
            f'filename="foto.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
        ).encode()
        + image
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts)


@dataclass
class RawResponse:
    status: int
    body: bytes
    receive_calls: int


def raw_asgi_post(app: Any, headers: list[tuple[bytes, bytes]], chunks: list[bytes]) -> RawResponse:
    """Drive the ASGI app directly, counting how many times the body is read."""

    async def go() -> RawResponse:
        pending = list(chunks)
        state = {"receive": 0, "status": 0}
        body = bytearray()

        async def receive() -> dict[str, Any]:
            state["receive"] += 1
            if pending:
                chunk = pending.pop(0)
                return {"type": "http.request", "body": chunk, "more_body": bool(pending)}
            await asyncio.sleep(0)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/capture",
            "raw_path": b"/api/capture",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("192.168.0.77", 50001),
            "server": ("testserver", 8000),
        }
        await app(scope, receive, send)
        return RawResponse(state["status"], bytes(body), state["receive"])

    return asyncio.run(go())


def test_ca07_image_one_byte_above_3_mib_is_413(edge: Edge) -> None:
    app, stub, sink = edge.app()
    image = padded_jpeg(3_145_729)
    assert len(image) == 3_145_729
    with TestClient(app) as client:
        r = post_capture(client, edge.token, image)
    assert r.status_code == 413
    assert "detail" in r.json()
    assert stub.calls == 0
    assert sink.stats().pending == 0
    assert edge.captures() == []


def test_ca07_request_with_content_length_3670017_is_413(edge: Edge) -> None:
    app, stub, sink = edge.app()
    boundary = "acc" + secrets.token_hex(8)
    overhead = len(multipart_body(b"", boundary))
    body = multipart_body(padded_jpeg(3_670_017 - overhead), boundary)
    assert len(body) == 3_670_017
    with TestClient(app) as client:
        r = client.post(
            "/api/capture",
            content=body,
            headers={
                SESSION_HEADER: edge.token,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
    assert r.status_code == 413
    assert r.request.headers["content-length"] == "3670017"
    assert stub.calls == 0
    assert sink.stats().pending == 0
    assert edge.captures() == []


def test_ca07_declared_content_length_is_refused_before_reading_the_body(edge: Edge) -> None:
    app, stub, _ = edge.app()
    boundary = "acc" + secrets.token_hex(8)
    small = multipart_body(solid_jpeg(), boundary)
    res = raw_asgi_post(
        app,
        [
            (b"host", b"testserver"),
            (SESSION_HEADER.lower().encode(), edge.token.encode()),
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
            (b"content-length", b"3670017"),
        ],
        [small],
    )
    assert res.status == 413
    assert "detail" in json.loads(res.body)
    assert res.receive_calls == 0
    assert stub.calls == 0


def test_ca07_jpeg_padded_to_exactly_3_mib_is_accepted(edge: Edge) -> None:
    app, stub, sink = edge.app(clock=Clock())
    image = padded_jpeg(3_145_728)
    assert len(image) == 3_145_728
    with TestClient(app) as client:
        r = post_capture(client, edge.token, image)
    assert r.status_code == 200, r.text
    assert stub.calls == 1
    assert sink.stats().pending == 1
    [photo] = edge.captures()
    # §4.5 step 6: a JPEG is stored with the bytes as received
    assert photo.read_bytes() == image


# =========================================================================== CA-08


INVALID_IMAGES: dict[str, Callable[[], bytes]] = {
    "text-named-foto.jpg": lambda: "isto não é uma foto\n".encode() * 10,
    "gif": gif_bytes,
    "truncated-jpeg": truncated_jpeg,
    "png-100x1001": lambda: solid_png(100, 1001),
    "jpeg-65-scan-markers": jpeg_with_scan_com,
    "jpeg-2001x2000": lambda: solid_jpeg(2001, 2000),
}


@pytest.mark.parametrize("kind", list(INVALID_IMAGES))
def test_ca08_invalid_images_are_415(edge: Edge, kind: str) -> None:
    app, stub, sink = edge.app()
    data = INVALID_IMAGES[kind]()
    with TestClient(app) as client:
        r = post_capture(client, edge.token, data, filename="foto.jpg", content_type="image/jpeg")
    assert r.status_code == 415, r.text
    body = r.json()
    assert set(body) == {"detail"}
    assert stub.calls == 0
    assert sink.stats().pending == 0
    assert edge.captures() == []


# =========================================================================== CA-09


@pytest.mark.parametrize(
    ("lot_id", "mode", "with_image"),
    [
        ("lote 1", "inspect", True),
        ("../x", "inspect", True),
        ("L-001\n", "inspect", True),
        ("L" * 41, "inspect", True),
        ("L-001", "foo", True),
        ("L-001", "inspect", False),
        (None, "inspect", True),
        ("L-001", None, True),
    ],
    ids=[
        "space",
        "dotdot",
        "trailing-newline",
        "41-chars",
        "mode-foo",
        "no-image",
        "no-lot",
        "no-mode",
    ],
)
def test_ca09_invalid_fields_are_422(
    edge: Edge, lot_id: str | None, mode: str | None, with_image: bool
) -> None:
    app, stub, sink = edge.app()
    with TestClient(app) as client:
        r = post_capture(
            client, edge.token, solid_jpeg() if with_image else None, lot_id=lot_id, mode=mode
        )
    assert r.status_code == 422, r.text
    assert "detail" in r.json()
    assert stub.calls == 0
    assert sink.stats().pending == 0
    assert edge.captures() == []


# =========================================================================== CA-10


def test_ca10_no_model_is_503(edge: Edge) -> None:
    sink = RecordingSink()
    app, _, _ = edge.app(None, sink)
    with TestClient(app) as client:
        r = post_capture(client, edge.token, solid_jpeg(), mode="inspect")
    assert r.status_code == 503
    assert r.json() == {"detail": "model not loaded"}
    assert sink.items == []
    assert edge.captures() == []


# =========================================================================== CA-11


def test_ca11_inference_error_is_500_without_side_effects(edge: Edge) -> None:
    sink = RecordingSink()
    app, inf, _ = edge.app(RaisingInferencer(), sink)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = post_capture(client, edge.token, solid_jpeg())
    assert r.status_code == 500
    assert r.json() == {"detail": "inference failed"}
    assert "Traceback" not in r.text
    assert inf.calls == 1
    assert sink.items == []
    assert edge.captures() == []


# =========================================================================== CA-12


@pytest.mark.parametrize("filename", ["../../evil.jpg", "..\\..\\evil.jpg", "/etc/evil.jpg"])
def test_ca12_client_filename_is_ignored(edge: Edge, filename: str) -> None:
    app, _, _ = edge.app(clock=Clock())
    before = set(edge.files())
    with TestClient(app) as client:
        r = post_capture(client, edge.token, solid_jpeg(), filename=filename)
    assert r.status_code == 200, r.text
    insp = r.json()["inspection"]
    day = datetime.fromisoformat(insp["inspected_at"].replace("Z", "+00:00")).date().isoformat()
    new = set(edge.files()) - before
    assert new == {edge.data_dir / "captures" / day / f"{insp['inspection_id']}.jpg"}
    assert not list(edge.tmp.parent.glob("evil.jpg"))


# =========================================================================== CA-13


def test_ca13_console_from_loopback(edge: Edge, lan: Callable[..., None]) -> None:
    lan("192.168.0.42", [])
    app, _, sink = edge.app()
    with TestClient(app) as client:
        for i in range(1, 13):
            r = post_capture(client, edge.token, solid_jpeg(), lot_id=f"L-{i:03d}")
            assert r.status_code == 200
        response = asgi_get(app, client=("127.0.0.1", 50000))

    assert response.status_code == 200
    page = response.text
    assert "<svg" in page
    assert f"http://192.168.0.42:8000/capture?t={edge.token}" in page
    assert "stub-v0" in page  # model state
    assert sink.stats().pending == 12
    assert re.search(r"\b12\b", page)  # pending of the sink
    positions = [page.find(f"L-{i:03d}") for i in range(12, 2, -1)]
    assert all(p >= 0 for p in positions), positions
    assert positions == sorted(positions), "most recent first"
    assert "L-001" not in page and "L-002" not in page
    inspection_rows = re.findall(r'<tr class="inspection"[^>]*>.*?</tr>', page, flags=re.S)
    assert len(inspection_rows) == 10
    assert sum(row.count("parafuso") for row in inspection_rows) == 10
    assert '<meta http-equiv="refresh" content="5">' in page


# =========================================================================== CA-14


@pytest.mark.parametrize(
    ("client", "headers"),
    [
        (("192.168.1.50", 50000), None),
        (("127.0.0.1", 50000), {"X-Forwarded-For": "203.0.113.9"}),
        (("127.0.0.1", 50000), {"CF-Connecting-IP": "203.0.113.9"}),
        (("127.0.0.1", 50000), {"Forwarded": "for=203.0.113.9"}),
    ],
    ids=["lan-client", "x-forwarded-for", "cf-connecting-ip", "forwarded"],
)
def test_ca14_console_refuses_remote_or_proxied(
    edge: Edge, lan: Callable[..., None], client: tuple[str, int], headers: dict[str, str] | None
) -> None:
    lan("192.168.0.42", [])
    app, _, _ = edge.app()
    response = asgi_get(app, client=client, headers=headers)
    assert response.status_code == 403
    assert edge.token not in response.text


# =========================================================================== CA-15


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def parse_tags(html_text: str) -> list[tuple[str, dict[str, str | None]]]:
    parser = _Tags()
    parser.feed(html_text)
    return parser.tags


def test_ca15_capture_page(edge: Edge) -> None:
    app, _, _ = edge.app()
    with TestClient(app) as client:
        page = client.get("/capture", params={"t": edge.token})
        assert page.status_code == 200
        tags = parse_tags(page.text)

        files = [a for t, a in tags if t == "input" and a.get("type") == "file"]
        assert len(files) == 1
        assert files[0].get("accept") == "image/*"
        assert files[0].get("capture") == "environment"

        lot_fields = [
            a
            for t, a in tags
            if t == "input" and "lot" in ((a.get("name") or "") + (a.get("id") or "")).lower()
        ]
        assert lot_fields, "no lot field"

        collect = [a for t, a in tags if t in {"option", "input"} and a.get("value") == "collect"]
        assert collect  # enabled since SPEC-010 (CA-16); see reviews/SPEC-010/r1-test-report.md
        inspect_opt = [
            a for t, a in tags if t in {"option", "input"} and a.get("value") == "inspect"
        ]
        assert inspect_opt and all("disabled" not in a for a in inspect_opt)

        # every page file: the HTML plus the scripts and stylesheets it references
        refs = [a.get("src") for t, a in tags if t == "script" and a.get("src")]
        refs += [a.get("href") for t, a in tags if t == "link" and a.get("href")]
        assert "/static/capture.js" in refs
        sources = {"capture.html": page.text}
        for ref in refs:
            assert ref and ref.startswith("/"), ref
            r = client.get(ref)
            assert r.status_code == 200
            sources[ref] = r.text
        js = client.get("/static/capture.js")
        assert js.status_code == 200
        assert len(js.text.splitlines()) <= 200
        for name, text in sources.items():
            assert not re.search(r"https?://", text), f"{name} references an absolute URL"

        for params in ({"t": new_token()}, {}):
            bad = client.get("/capture", params=params)
            assert bad.status_code == 401
            assert INVALID_SESSION_TEXT in bad.text
            assert edge.token not in bad.text


# =========================================================================== CA-16


def test_ca16_status(edge: Edge) -> None:
    app, _, _ = edge.app()
    with TestClient(app) as client:
        r = client.get("/api/status", headers={SESSION_HEADER: edge.token})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"device_id", "contract_version", "model", "sink"}
    assert {"loaded", "model_version", "model_sha256"} <= set(body["model"])
    assert {"pending", "dead", "last_success_at", "connectivity"} <= set(body["sink"])
    assert body["sink"]["connectivity"] == "disabled"
    assert body["device_id"] == "edge-01"
    assert body["model"]["loaded"] is True
    assert body["model"]["model_version"] == "stub-v0"
    import qc_contracts

    assert body["contract_version"] == qc_contracts.__version__


# =========================================================================== CA-17


HTTP_CLIENT_MODULES = {"httpx", "requests", "urllib.request"}


def _imports_http_client(tree: ast.AST) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(
                    alias.name == m or alias.name.startswith(m + ".") for m in HTTP_CLIENT_MODULES
                ):
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if any(mod == m or mod.startswith(m + ".") for m in HTTP_CLIENT_MODULES):
                found.append(mod)
            if mod == "urllib" and any(a.name == "request" for a in node.names):
                found.append("urllib.request")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"__import__", "import_module"} and node.args:
                arg = node.args[0]
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and any(
                        arg.value == m or arg.value.startswith(m + ".") for m in HTTP_CLIENT_MODULES
                    )
                ):
                    found.append(arg.value)
    return found


def test_ca17_captures_are_never_served_and_payload_is_the_contract(edge: Edge) -> None:
    sink = RecordingSink()
    app, _, _ = edge.app(sink=sink, clock=Clock())
    with TestClient(app) as client:
        r = post_capture(client, edge.token, solid_jpeg())
        assert r.status_code == 200
        insp = r.json()["inspection"]
        [photo] = edge.captures()
        day = photo.parent.name
        name = photo.name
        paths = [
            f"/captures/{day}/{name}",
            f"/data/captures/{day}/{name}",
            f"/edge-data/captures/{day}/{name}",
            f"/static/../captures/{day}/{name}",
            f"/static/%2e%2e/captures/{day}/{name}",
            f"/static/..%2f..%2fcaptures/{day}/{name}",
        ]
        for path in paths:
            for headers in ({}, {SESSION_HEADER: edge.token}):
                resp = client.get(path, headers=headers)
                assert resp.status_code == 404, (path, resp.status_code)
                assert photo.read_bytes() not in resp.content
    assert len(sink.items) == 1
    assert isinstance(sink.items[0], InspectionCreate)
    assert set(sink.items[0].model_dump()) == CONTRACT_FIELDS
    assert insp["inspection_id"] == str(sink.items[0].inspection_id)


def test_ca17_no_http_client_import_outside_the_publisher() -> None:
    offenders = {}
    files = sorted(SRC.rglob("*.py"))
    assert files
    for path in files:
        rel = path.relative_to(SRC.parent)
        module = ".".join(rel.with_suffix("").parts)
        if module == "qc_edge.publisher" or module.startswith("qc_edge.publisher."):
            continue
        found = _imports_http_client(ast.parse(path.read_text(encoding="utf-8")))
        if found:
            offenders[module] = found
    assert offenders == {}


def test_ca17_static_checker_detects_violations() -> None:
    """Guard against a tautological CA-17: the checker must flag every import form."""
    for source in (
        "import httpx",
        "import requests.adapters",
        "import urllib.request",
        "from urllib import request",
        "from urllib.request import urlopen",
        "from httpx import Client",
        "import importlib\nimportlib.import_module('httpx')",
        "__import__('requests')",
    ):
        assert _imports_http_client(ast.parse(source)), source
    assert not _imports_http_client(ast.parse("from urllib.parse import quote"))


# =========================================================================== CA-18


def test_ca18_udp_probe_address_comes_first(lan: Callable[..., None]) -> None:
    lan("192.168.0.42", ["10.0.0.7"])
    ips = detect_lan_ips()
    assert ips[0] == "192.168.0.42"
    lan("192.168.0.42", None)
    assert detect_lan_ips()[0] == "192.168.0.42"


def test_ca18_fallback_filters_loopback_and_link_local(lan: Callable[..., None]) -> None:
    lan(None, ["127.0.1.1", "169.254.3.3", "10.0.0.7"])
    assert detect_lan_ips() == ["10.0.0.7"]


def test_ca18_no_candidate_falls_back_to_loopback_with_console_warning(
    edge: Edge, lan: Callable[..., None]
) -> None:
    lan(None, None)
    assert detect_lan_ips() == ["127.0.0.1"]
    lan(None, ["127.0.1.1", "169.254.3.3"])
    assert detect_lan_ips() == ["127.0.0.1"]

    app, _, _ = edge.app()
    warned = asgi_get(app).text
    lan("192.168.0.42", [])
    normal = asgi_get(app).text
    assert f"http://127.0.0.1:8000/capture?t={edge.token}" in warned
    assert re.search(r"nenhum ip", warned, re.IGNORECASE)
    assert not re.search(r"nenhum ip", normal, re.IGNORECASE)


# =========================================================================== CA-19


def test_ca19_logs_never_contain_the_token_or_the_device_key(
    edge: Edge,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    api_key = "acc-dk-" + secrets.token_hex(16)
    monkeypatch.setenv("DEVICE_API_KEY", api_key)
    records: list[logging.LogRecord] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    collector = Collector(level=logging.DEBUG)
    statuses: list[int] = []

    def drive(app: Any) -> None:
        logging.getLogger().addHandler(collector)
        try:
            with TestClient(app) as client:
                statuses.append(post_capture(client, edge.token, solid_jpeg()).status_code)
                statuses.append(post_capture(client, new_token(), solid_jpeg()).status_code)
                statuses.append(post_capture(client, edge.token, gif_bytes()).status_code)
                statuses.append(client.get("/capture", params={"t": edge.token}).status_code)
                statuses.append(
                    client.get("/api/status", headers={SESSION_HEADER: edge.token}).status_code
                )
        finally:
            logging.getLogger().removeHandler(collector)

    monkeypatch.setattr(uvicorn, "run", UvicornSpy(drive))
    caplog.set_level(logging.DEBUG)
    code = run_main(monkeypatch, "--stub-model")
    assert code == 0
    assert statuses == [200, 401, 415, 200, 200]

    # the httpx logger belongs to the test client, not to the server (dev-report note)
    server_lines = [
        r.getMessage() + " " + str(r.args)
        for r in [*caplog.records, *records]
        if not r.name.startswith("httpx")
    ]
    out = capsys.readouterr()
    text = "\n".join([*server_lines, out.out, out.err])
    assert "127.0.0.1:8000" in text, "startup log (console URL) was not captured"
    assert edge.token not in text
    assert api_key not in text


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.slow
def test_ca19_real_server_output_has_no_secrets(tmp_path: Path) -> None:
    """Run the real ``qc-edge`` (uvicorn on loopback) and read everything it prints."""
    token = new_token()
    api_key = "acc-dk-" + secrets.token_hex(16)
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k not in EDGE_ENV_VARS}
    env.update(
        EDGE_HOST="127.0.0.1",
        EDGE_PORT=str(port),
        EDGE_SESSION_TOKEN=token,
        DEVICE_API_KEY=api_key,
        EDGE_DATA_DIR=str(tmp_path / "data"),
        PYTHONUNBUFFERED="1",
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", "from qc_edge.cli import main; main()", "--stub-model"],
        env=env,
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    statuses: list[int] = []
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                httpx.get(base + "/static/capture.js", timeout=0.5)
                break
            except httpx.TransportError:
                assert proc.poll() is None, proc.stdout.read().decode() if proc.stdout else ""
                assert time.monotonic() < deadline, "server did not start"
                time.sleep(0.1)
        with httpx.Client(base_url=base, timeout=10) as c:
            for tok, img in (
                (token, solid_jpeg()),
                (new_token(), solid_jpeg()),
                (token, gif_bytes()),
            ):
                r = c.post(
                    "/api/capture",
                    headers={SESSION_HEADER: tok},
                    data={"lot_id": "L-001", "mode": "inspect"},
                    files={"image": ("foto.jpg", img, "image/jpeg")},
                )
                statuses.append(r.status_code)
            statuses.append(c.get("/capture", params={"t": token}).status_code)
            statuses.append(c.get("/").status_code)
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            output, _ = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            output, _ = proc.communicate()
    text = output.decode("utf-8", "replace")
    assert statuses == [200, 401, 415, 200, 200], text
    assert f"127.0.0.1:{port}" in text
    assert token not in text
    assert api_key not in text
    assert "Traceback" not in text


# =========================================================================== CA-22


def _parallel_posts(
    client: TestClient, token: str, n: int
) -> tuple[list[threading.Thread], list[httpx.Response], threading.Condition]:
    responses: list[httpx.Response] = []
    cond = threading.Condition()

    def worker(i: int) -> None:
        r = post_capture(client, token, solid_jpeg(), lot_id=f"P-{i}")
        with cond:
            responses.append(r)
            cond.notify_all()

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
    for t in threads:
        t.start()
    return threads, responses, cond


def test_ca22_busy_slots_answer_503(edge: Edge) -> None:
    inf = BlockingInferencer()
    sink = RecordingSink()
    app, _, _ = edge.app(inf, sink, max_concurrent_decodes=2, decode_wait_s=0.5)
    with TestClient(app) as client:
        threads, responses, cond = _parallel_posts(client, edge.token, 4)
        with cond:
            assert cond.wait_for(lambda: len(responses) >= 2, timeout=15)
        inf.release.set()
        for t in threads:
            t.join(timeout=15)
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 200, 503, 503]
    for r in responses:
        if r.status_code == 503:
            assert r.json() == {"detail": "server busy"}
    assert inf.max_active == 2
    assert inf.calls == 2
    assert len(sink.items) == 2
    assert len(edge.captures()) == 2


# =========================================================================== CA-23


def test_ca23_waiting_requests_get_a_slot(edge: Edge) -> None:
    inf = BlockingInferencer()
    sink = RecordingSink()
    app, _, _ = edge.app(inf, sink, max_concurrent_decodes=2, decode_wait_s=5)
    with TestClient(app) as client:
        threads, responses, _ = _parallel_posts(client, edge.token, 4)
        time.sleep(0.3)
        inf.release.set()
        for t in threads:
            t.join(timeout=15)
    assert [r.status_code for r in responses] == [200, 200, 200, 200]
    assert inf.max_active == 2
    assert len(sink.items) == 4


def test_ca23_slot_is_released_after_an_inference_error(edge: Edge) -> None:
    inf = RaisingInferencer(fail_on={1})
    app, _, _ = edge.app(inf, RecordingSink(), max_concurrent_decodes=1, decode_wait_s=1)
    with TestClient(app, raise_server_exceptions=False) as client:
        codes = [post_capture(client, edge.token, solid_jpeg()).status_code for _ in range(3)]
    assert codes == [500, 200, 200]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_concurrent_decodes": 0},
        {"decode_wait_s": 0},
        {"max_concurrent_decodes": -1},
        {"decode_wait_s": -0.5},
    ],
    ids=["slots-0", "wait-0", "slots-negative", "wait-negative"],
)
def test_ca23_invalid_limiter_arguments(edge: Edge, kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        edge.app(**kwargs)


# =========================================================================== CA-24


def test_ca24_cli_refuses_the_truncated_images_flag(
    edge: Edge,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    caplog.set_level(logging.DEBUG)
    code = run_main(monkeypatch)
    assert code == 1
    assert FLAG in captured_text(caplog, capsys)
    assert spy.calls == []


def test_ca24_cli_starts_with_the_flag_off(edge: Edge, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    assert run_main(monkeypatch) == 0
    assert len(spy.calls) == 1
    _, kwargs = spy.calls[0]
    assert kwargs.get("proxy_headers") is False
    assert kwargs.get("host") == "0.0.0.0"
    assert kwargs.get("port") == 8000


def test_ca24_lifespan_refuses_the_truncated_images_flag(
    edge: Edge, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[str] = []

    class Service:
        def start(self) -> None:
            started.append("start")

        def stop(self) -> None:
            started.append("stop")

    app, _, _ = edge.app(background=[Service()])
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    with pytest.raises(RuntimeError, match=FLAG), TestClient(app):
        pass
    assert started == []  # the flag is checked before any BackgroundService starts

    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    app, _, _ = edge.app(background=[Service()])
    with TestClient(app) as client:
        assert client.get("/api/status", headers={SESSION_HEADER: edge.token}).status_code == 200
    assert started == ["start", "stop"]


# =========================================================================== CA-25


def _tracked_python_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [ROOT / p for p in out.splitlines() if "tests" not in Path(p).parts]


def _flag_writes(tree: ast.AST) -> list[int]:
    lines = []

    def target_names(target: ast.AST) -> Iterator[str]:
        if isinstance(target, ast.Name):
            yield target.id
        elif isinstance(target, ast.Attribute):
            yield target.attr
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                yield from target_names(elt)
        elif isinstance(target, ast.Starred):
            yield from target_names(target.value)

    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        if any(name == FLAG for t in targets for name in target_names(t)):
            lines.append(node.lineno)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == FLAG
        ):
            lines.append(node.lineno)
    return lines


def test_ca25_no_production_code_assigns_the_flag() -> None:
    files = _tracked_python_files()
    assert any(p.parts[-2:] == ("qc_edge", "limits.py") for p in files)
    offenders = {}
    for path in files:
        if not path.exists():
            continue
        lines = _flag_writes(ast.parse(path.read_text(encoding="utf-8")))
        if lines:
            offenders[str(path.relative_to(ROOT))] = lines
    assert offenders == {}


def test_ca25_checker_detects_violations() -> None:
    for source in (
        "from PIL import ImageFile\nImageFile.LOAD_TRUNCATED_IMAGES = True",
        "LOAD_TRUNCATED_IMAGES = True",
        "ImageFile.LOAD_TRUNCATED_IMAGES |= True",
        "ImageFile.LOAD_TRUNCATED_IMAGES: bool = True",
        "setattr(ImageFile, 'LOAD_TRUNCATED_IMAGES', True)",
        "a, ImageFile.LOAD_TRUNCATED_IMAGES = 1, True",
    ):
        assert _flag_writes(ast.parse(source)), source
    assert not _flag_writes(ast.parse("x = ImageFile.LOAD_TRUNCATED_IMAGES"))


# =========================================================================== CA-26


def test_ca26_constants() -> None:
    assert limits.CAPTURE_MAX_BYTES == 3_145_728
    assert limits.CAPTURE_MAX_REQUEST_BYTES == 3_670_016
    assert limits.CAPTURE_MAX_PIXELS == 4_000_000


def test_ca26_pixel_limit_is_checked_before_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    ok = solid_jpeg(2000, 2000)
    over = solid_jpeg(2001, 2000)
    # both are accepted by the ML loader
    assert load_image(ok).size == (2000, 2000)
    assert load_image(over).size == (2001, 2000)

    img = load_capture_image(ok)
    assert img.mode == "RGB"
    assert img.size == (2000, 2000)

    original = ImageFile.ImageFile.load
    calls: list[int] = []

    def spy(self: ImageFile.ImageFile, *args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ImageFile.ImageFile, "load", spy)
    with pytest.raises(InvalidImageError, match="capture pixel limit"):
        load_capture_image(over)
    assert calls == []
    # sanity: the spy does see decodes
    load_capture_image(solid_jpeg(16, 16))
    assert calls


def test_ca26_route_accepts_2000x2000_and_refuses_2001x2000(edge: Edge) -> None:
    app, stub, _ = edge.app()
    with TestClient(app) as client:
        assert post_capture(client, edge.token, solid_jpeg(2000, 2000)).status_code == 200
        r = post_capture(client, edge.token, solid_jpeg(2001, 2000))
    assert r.status_code == 415
    assert stub.calls == 1


# =========================================================================== CA-27


@pytest.mark.parametrize("data", [b"not an image", b"", gif_bytes()], ids=["text", "empty", "gif"])
def test_ca27_unreadable_inputs_raise_invalid_image(
    monkeypatch: pytest.MonkeyPatch, data: bytes
) -> None:
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    with pytest.raises(InvalidImageError):
        load_capture_image(data)


def test_ca27_load_image_rules_still_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    with pytest.raises(InvalidImageError, match="JPEG scans"):
        load_capture_image(jpeg_with_scan_com())


def test_ca27_flag_is_checked_before_the_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    with pytest.raises(RuntimeError, match=FLAG):
        load_capture_image(solid_jpeg(2001, 2000))


# =========================================================================== extras


def test_extra_flag_enabled_after_startup_is_500_not_415(
    edge: Edge, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, stub, sink = edge.app()
    with TestClient(app, raise_server_exceptions=False) as client:
        monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
        r = post_capture(client, edge.token, solid_jpeg())
        monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    assert r.status_code == 500
    assert set(r.json()) == {"detail"}
    assert "Traceback" not in r.text and FLAG not in r.text
    assert stub.calls == 0
    assert sink.stats().pending == 0
    assert edge.captures() == []


def test_extra_png_is_stored_as_jpeg(edge: Edge) -> None:
    app, _, _ = edge.app(clock=Clock())
    with TestClient(app) as client:
        r = post_capture(
            client, edge.token, solid_png(120, 80), filename="x.png", content_type="image/png"
        )
    assert r.status_code == 200
    [photo] = edge.captures()
    data = photo.read_bytes()
    assert data.startswith(SOI)
    with Image.open(io.BytesIO(data)) as img:
        assert img.format == "JPEG" and img.size == (120, 80)


@pytest.mark.parametrize(
    "image",
    [
        lambda: solid_png(64, 48, "RGBA"),
        lambda: solid_png(64, 48, "L"),
        lambda: encode(Image.new("CMYK", (64, 48)), "JPEG"),
        lambda: encode(Image.new("L", (64, 48)), "JPEG"),
        lambda: solid_png(100, 1000),
        lambda: encode(Image.new("RGB", (64, 48)), "JPEG", progressive=True),
    ],
    ids=["png-rgba", "png-gray", "jpeg-cmyk", "jpeg-gray", "png-10to1", "jpeg-progressive"],
)
def test_extra_other_valid_images_are_accepted(edge: Edge, image: Callable[[], bytes]) -> None:
    app, _, _ = edge.app()
    with TestClient(app) as client:
        r = post_capture(client, edge.token, image())
    assert r.status_code == 200, r.text
    [photo] = edge.captures()
    assert photo.read_bytes().startswith(SOI)


def test_extra_png_decompression_bomb_is_415_fast(edge: Edge) -> None:
    bomb = solid_png(20_000, 20_000, "L")  # 400 M pixels in a few hundred KB
    assert len(bomb) < limits.CAPTURE_MAX_BYTES
    app, stub, _ = edge.app()
    with TestClient(app) as client:
        start = time.monotonic()
        r = post_capture(client, edge.token, bomb, filename="b.png", content_type="image/png")
        elapsed = time.monotonic() - start
    assert r.status_code == 415
    assert stub.calls == 0
    assert elapsed < 2.0


def test_extra_png_2001x2000_is_415(edge: Edge) -> None:
    app, stub, _ = edge.app()
    with TestClient(app) as client:
        r = post_capture(client, edge.token, solid_png(2001, 2000), content_type="image/png")
    assert r.status_code == 415
    assert stub.calls == 0


def test_extra_lot_id_boundaries(edge: Edge) -> None:
    app, _, _ = edge.app()
    with TestClient(app) as client:
        assert post_capture(client, edge.token, solid_jpeg(), lot_id="L" * 40).status_code == 200
        assert post_capture(client, edge.token, solid_jpeg(), lot_id="a_B-9").status_code == 200
        for bad in ("", "lóte", "L-001\r", " L-001", "L-001 ", "L\x00", "L/1", "%2e%2e"):
            r = post_capture(client, edge.token, solid_jpeg(), lot_id=bad)
            assert r.status_code == 422, (bad, r.status_code)
            assert bad not in r.text or bad == ""


def test_extra_collect_mode_without_collect_fields_is_422(edge: Edge) -> None:
    app, stub, _ = edge.app()
    with TestClient(app) as client:
        r = post_capture(client, edge.token, solid_jpeg(), mode="collect")
    assert r.status_code == 422
    assert stub.calls == 0
    assert edge.captures() == []


@pytest.mark.parametrize(
    "header",
    [" {t}", "{t} ", "{t}x", "{t}"[:-1], "Bearer {t}"],
    ids=["leading-space", "trailing-space", "suffix", "prefix-of-token", "bearer"],
)
def test_extra_token_variants_are_401(edge: Edge, header: str) -> None:
    app, stub, _ = edge.app()
    value = header.format(t=edge.token) if "{t}" in header else edge.token[:-1]
    with TestClient(app) as client:
        r = client.post(
            "/api/capture",
            headers={SESSION_HEADER: value},
            data={"lot_id": "L-001", "mode": "inspect"},
            files={"image": ("f.jpg", solid_jpeg(), "image/jpeg")},
        )
    assert r.status_code == 401
    assert stub.calls == 0


def test_extra_huge_or_non_ascii_token_is_401_not_500(edge: Edge) -> None:
    app, stub, _ = edge.app()
    with TestClient(app, raise_server_exceptions=False) as client:
        for value in ("x" * 20_000, edge.token + "é"):
            r = client.get("/api/status", headers={SESSION_HEADER: value.encode("utf-8")})
            assert r.status_code == 401, r.status_code
        r = client.get("/capture", params={"t": "é" * 5000})
        assert r.status_code == 401
    assert stub.calls == 0


def test_extra_oversized_body_without_token_never_reaches_the_inferencer(edge: Edge) -> None:
    app, stub, _ = edge.app()
    with TestClient(app) as client:
        r = post_capture(client, None, padded_jpeg(3_300_000))
    assert r.status_code in {401, 413}
    assert stub.calls == 0


def test_extra_chunked_body_above_the_limit_is_413(edge: Edge) -> None:
    app, stub, _ = edge.app()
    boundary = "acc" + secrets.token_hex(8)
    body = multipart_body(padded_jpeg(3_600_000), boundary)
    chunks = [body[i : i + 65536] for i in range(0, len(body), 65536)]
    res = raw_asgi_post(
        app,
        [
            (b"host", b"testserver"),
            (SESSION_HEADER.lower().encode(), edge.token.encode()),
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
            (b"transfer-encoding", b"chunked"),
        ],
        chunks,
    )
    assert res.status == 413
    assert stub.calls == 0
    assert edge.captures() == []


def test_extra_two_image_files_are_refused(edge: Edge) -> None:
    app, stub, _ = edge.app()
    with TestClient(app) as client:
        r = client.post(
            "/api/capture",
            headers={SESSION_HEADER: edge.token},
            data={"lot_id": "L-001", "mode": "inspect"},
            files=[
                ("image", ("a.jpg", solid_jpeg(), "image/jpeg")),
                ("image", ("b.jpg", solid_jpeg(), "image/jpeg")),
            ],
        )
    assert 400 <= r.status_code < 500, r.status_code
    assert stub.calls == 0


def test_extra_422_does_not_wait_for_a_busy_slot(edge: Edge) -> None:
    inf = BlockingInferencer()
    app, _, _ = edge.app(inf, RecordingSink(), max_concurrent_decodes=1, decode_wait_s=5)
    with TestClient(app) as client:
        threads, responses, _ = _parallel_posts(client, edge.token, 1)
        deadline = time.monotonic() + 5
        while inf.active == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        start = time.monotonic()
        r = post_capture(client, edge.token, solid_jpeg(), lot_id="bad lot")
        elapsed = time.monotonic() - start
        inf.release.set()
        for t in threads:
            t.join(timeout=10)
    assert r.status_code == 422
    assert elapsed < 2.0
    assert [x.status_code for x in responses] == [200]


def test_extra_nan_decode_wait_is_refused(edge: Edge) -> None:
    with pytest.raises(ValueError):
        edge.app(decode_wait_s=float("nan"))


def test_extra_inspected_at_is_normalized_to_utc_and_dir_uses_utc_date(edge: Edge) -> None:
    local = timezone(timedelta(hours=-3))
    value = (datetime.now(UTC) - timedelta(minutes=1)).astimezone(local)
    app, _, _ = edge.app(clock=lambda: value)
    with TestClient(app) as client:
        r = post_capture(client, edge.token, solid_jpeg())
    assert r.status_code == 200, r.text
    at = datetime.fromisoformat(r.json()["inspection"]["inspected_at"].replace("Z", "+00:00"))
    assert at.utcoffset() == timedelta(0)
    assert at == value
    [photo] = edge.captures()
    assert photo.parent.name == value.astimezone(UTC).date().isoformat()
    date.fromisoformat(photo.parent.name)


def test_extra_console_ip_parameter_only_accepts_detected_ips(
    edge: Edge, lan: Callable[..., None]
) -> None:
    lan("192.168.0.42", ["10.0.0.7"])
    app, _, _ = edge.app()
    page = asgi_get(app).text
    assert f"http://192.168.0.42:8000/capture?t={edge.token}" in page
    assert "/?ip=10.0.0.7" in page
    chosen = asgi_get(app, "/?ip=10.0.0.7")
    assert chosen.status_code == 200
    assert f"http://10.0.0.7:8000/capture?t={edge.token}" in chosen.text
    for bad in ("8.8.8.8", "<script>alert(1)</script>", "evil.example"):
        resp = asgi_get(app, "/?ip=" + bad)
        assert f"http://{bad}:8000" not in resp.text
        assert "<script>alert(1)</script>" not in resp.text


def test_extra_console_accepts_ipv6_loopback(edge: Edge, lan: Callable[..., None]) -> None:
    lan("192.168.0.42", [])
    app, _, _ = edge.app()
    assert asgi_get(app, client=("::1", 50000)).status_code == 200


def test_extra_capture_flow_opens_no_network_connection(
    edge: Edge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-02: an accepted capture never opens an outbound connection."""
    attempts: list[Any] = []
    real_connect = socket.socket.connect

    def spy(self: socket.socket, address: Any) -> Any:
        attempts.append(address)
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", spy)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: attempts.append(a))
    app, _, _ = edge.app()
    with TestClient(app) as client:
        r = post_capture(client, edge.token, solid_jpeg())
        s = client.get("/api/status", headers={SESSION_HEADER: edge.token})
    assert r.status_code == 200 and s.status_code == 200
    assert attempts == []
    assert solid_jpeg() not in r.content


def test_extra_cli_stub_model_flag_and_default(edge: Edge, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    assert run_main(monkeypatch) == 0
    with TestClient(spy.app) as client:
        r = post_capture(client, edge.token, solid_jpeg())
    assert r.status_code == 503
    assert r.json() == {"detail": "model not loaded"}

    assert run_main(monkeypatch, "--stub-model") == 0
    with TestClient(spy.app) as client:
        r = post_capture(client, edge.token, solid_jpeg())
    assert r.status_code == 200
    assert r.json()["inspection"]["model_version"] == "stub-v0"


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("EDGE_HOST", "localhost"),
        ("EDGE_HOST", "999.1.1.1"),
        ("EDGE_PORT", "0"),
        ("EDGE_PORT", "abc"),
        ("DEVICE_ID", "ed"),
        ("DEVICE_ID", "a" * 33),
        ("EDGE_SESSION_TOKEN", "31"),
    ],
)
def test_extra_more_invalid_configuration(
    edge: Edge,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    variable: str,
    value: str,
) -> None:
    if variable == "EDGE_SESSION_TOKEN":
        value = secrets.token_hex(16)[:31]
    monkeypatch.setenv(variable, value)
    monkeypatch.setattr(uvicorn, "run", UvicornSpy())
    caplog.set_level(logging.DEBUG)
    assert run_main(monkeypatch) == 2
    text = captured_text(caplog, capsys)
    assert variable in text
    if variable == "EDGE_SESSION_TOKEN":
        assert value not in text


def test_extra_configuration_boundaries_are_accepted(
    edge: Edge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGE_SESSION_TOKEN", secrets.token_hex(16))  # exactly 32
    monkeypatch.setenv("DEVICE_ID", "a" * 32)
    monkeypatch.setenv("EDGE_PORT", "65535")
    monkeypatch.setenv("EDGE_HOST", "::")
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    assert run_main(monkeypatch) == 0
    assert spy.calls[0][1]["port"] == 65535


def test_extra_data_dir_is_created(edge: Edge) -> None:
    assert not edge.data_dir.exists()
    edge.settings()
    assert edge.data_dir.is_dir()


def test_extra_in_memory_sink_is_idempotent_and_disabled(edge: Edge) -> None:
    sink = InMemorySink()
    app, _, _ = edge.app(sink=sink)
    with TestClient(app) as client:
        r = post_capture(client, edge.token, solid_jpeg())
    insp = InspectionCreate.model_validate(r.json()["inspection"])
    sink.put(insp)
    stats = sink.stats()
    assert stats.pending == 1
    assert stats.dead == 0
    assert stats.last_success_at is None
    assert stats.connectivity == "disabled"


def test_extra_stub_inferencer_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubInferencer()
    assert stub.model_info == ModelInfo("stub-v0", "0" * 64)
    assert stub.calls == 0
    stub.infer(Image.new("RGB", (8, 8)))
    assert stub.calls == 1
