"""Acceptance tests for SPEC-025 (qc-edge maintenance: console Host, network, limiter,
permissions, CLI and collect-mode privacy).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-01 to CA-19 (round r2 adjusted CA-11, CA-13 and CA-15 and added
CA-19, after SPEC_ISSUE-01 of the r1 review). Tests named ``test_extra_*`` are exploratory edge
cases around the SPEC that no CA spells out.

Rules followed (``reviews/checklist.md`` and ``docs/architecture.md`` §10): the session token and
every marker are built at run time (no credential literal in a URL or header), images are
generated in memory (no binary in Git, no real photo, R-14), ``EDGE_DATA_DIR`` and
``DATASET_DIR`` always live under ``tmp_path``, no test runs the test suite in a subprocess
(CA-12 runs ``pytest --collect-only`` on two explicit files, without the database), and the only
boundaries mocked are the ones the SPEC names: ``detect_lan_ips`` (socket), ``uvicorn.run``, the
inferencer/sink doubles and, in CA-08, CA-16 and CA-17, the spies on ``load_capture_image``,
``strip_private_segments`` and ``os.fsync``.
"""

from __future__ import annotations

import ast
import asyncio
import csv
import errno
import fcntl
import io
import logging
import os
import re
import secrets
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import uvicorn
from fastapi.testclient import TestClient
from PIL import ExifTags, Image, ImageFile

import qc_edge.cli
import qc_edge.jpeg
import qc_edge.limits
import qc_edge.netinfo
import qc_edge.privacy
from qc_contracts import Grade, InspectionCreate, ObjectType
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import InferenceError, InferenceResult, ModelInfo, StubInferencer
from qc_edge.jpeg import (
    JpegStructureError,
    has_exif_rotation,
    jpeg_private_findings,
    strip_private_segments,
)
from qc_edge.security import is_allowed_console_host
from qc_edge.sink import SinkStats
from qc_preprocess import load_image

pytestmark = pytest.mark.acceptance

EDGE_ROOT = Path(__file__).resolve().parents[2]  # edge/
ROOT = EDGE_ROOT.parent  # repository root

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

PORT = 8000
SESSION_HEADER = "X-Session-Token"
BUSY = {"detail": "server busy"}
UNSUPPORTED = {"detail": "invalid image: unsupported JPEG structure"}
ORIENTATION_REFUSED = {"detail": "invalid image: EXIF orientation not supported"}
REFUSAL_LOG = "console refused: host not allowed"

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
XMP_PREFIX = b"http://ns.adobe.com/xap/1.0/\x00"
PHOTOSHOP_PREFIX = b"Photoshop 3.0\x00"
MOTION_TRAILER = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200_000
LATITUDE = (23.0, 33.0, 47.25)
# EXIF header + TIFF with an empty IFD0: whatever follows (a thumbnail) is opaque to Pillow.
EMPTY_TIFF = b"Exif\x00\x00" + b"MM\x00\x2a\x00\x00\x00\x08" + b"\x00\x00" + b"\x00" * 4
LATITUDE_TEXTS = ("47.25", "23.0, 33.0", "(23, 33")

MANIFEST_HEADER = (
    "image_path,item_id,object_type,grade,labeler,angle,captured_at,capture_device,notes\n"
)


def new_token() -> str:
    """40 URL-safe characters, generated at run time (never a literal)."""
    return secrets.token_urlsafe(30)


def new_marker(prefix: str = "acc") -> str:
    """Alphanumeric marker generated at run time (never starts with ``-``)."""
    return prefix + secrets.token_hex(12)


# --------------------------------------------------------------------------- images


def encode(img: Image.Image, fmt: str, **kwargs: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def textured(width: int = 64, height: int = 48, seed: int = 25) -> Image.Image:
    """Noise image: any change of the entropy data would change the decoded pixels."""
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8), "RGB")


def clean_jpeg(seed: int = 25, **kwargs: Any) -> bytes:
    """Pillow JPEG without APP1, APP13, COM or trailer."""
    kwargs.setdefault("quality", 90)
    return encode(textured(seed=seed), "JPEG", **kwargs)


def png_bytes() -> bytes:
    return encode(textured(seed=3), "PNG")


def gif_bytes() -> bytes:
    return encode(Image.new("P", (32, 32)), "GIF")


def segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def gps_exif() -> Image.Exif:
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "AccPhone"
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "S"
    gps[ExifTags.GPS.GPSLatitude] = LATITUDE
    return exif


def exif_jpeg(seed: int = 25) -> bytes:
    """Pillow JPEG whose only private segment is the EXIF APP1 with the GPS IFD."""
    data = clean_jpeg(seed, exif=gps_exif())
    ifd = Image.open(io.BytesIO(data)).getexif().get_ifd(ExifTags.IFD.GPSInfo)
    assert ifd[ExifTags.GPS.GPSLatitude] == LATITUDE  # the fixture really carries GPS
    return data


def metadata_jpeg(seed: int = 25) -> tuple[bytes, bytes]:
    """The SPEC's "JPEG com metadados" and the COM marker generated for it."""
    com_marker = new_marker("acc-com-").encode()
    inserted = (
        segment(0xE1, XMP_PREFIX + b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>')
        + segment(0xED, PHOTOSHOP_PREFIX + b"8BIM\x04\x04\x00\x00\x00\x00\x00\x00")
        + segment(0xFE, com_marker)
    )
    base = exif_jpeg(seed)
    return base[:2] + inserted + base[2:] + MOTION_TRAILER, com_marker


def pixels(data: bytes | Path) -> np.ndarray:
    source = data if isinstance(data, Path) else io.BytesIO(data)
    with Image.open(source) as img:
        return np.asarray(img.convert("RGB"))


def loaded(data: bytes | Path) -> np.ndarray:
    """Pixels through the project loader (EXIF orientation applied, ADR-004)."""
    return np.asarray(load_image(data))


def same_loaded(a: bytes | Path, b: bytes | Path) -> bool:
    """Same size and same pixels through ``qc_preprocess.load_image``."""
    left, right = loaded(a), loaded(b)
    return left.shape == right.shape and np.array_equal(left, right)


def oriented_jpeg(orientation: int, seed: int = 25) -> bytes:
    """CA-19: Pillow JPEG 64x48 whose EXIF has ``Orientation`` and the GPS IFD."""
    exif = gps_exif()
    exif[ExifTags.Base.Orientation] = orientation
    data = clean_jpeg(seed, exif=exif)
    with Image.open(io.BytesIO(data)) as img:
        assert img.getexif()[ExifTags.Base.Orientation] == orientation
    return data


def parse_segments(data: bytes) -> list[tuple[int, bytes]]:
    """Independent structural walk: ``(marker, bytes)``; ``-1`` is entropy-coded data."""
    assert data[:2] == SOI
    out: list[tuple[int, bytes]] = [(0xD8, SOI)]
    i = 2
    while True:
        assert data[i] == 0xFF, f"no marker at {i}"
        j = i
        while data[j + 1] == 0xFF:  # fill bytes
            j += 1
        marker = data[j + 1]
        if marker == 0xD9:
            out.append((marker, EOI))
            return out
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out.append((marker, data[j : j + 2]))
            i = j + 2
            continue
        length = int.from_bytes(data[j + 2 : j + 4], "big")
        out.append((marker, data[j : j + 2 + length]))
        i = j + 2 + length
        if marker == 0xDA:
            k = i
            while not (data[k] == 0xFF and data[k + 1] != 0x00 and not 0xD0 <= data[k + 1] <= 0xD7):
                k += 1
            out.append((-1, data[i:k]))
            i = k


IMAGE_MARKERS = {0xDB, 0xC4, 0xDA, -1} | {
    m for m in range(0xC0, 0xD0) if m not in (0xC4, 0xC8, 0xCC)
}


def image_segments(data: bytes) -> list[bytes]:
    """DQT, SOFn, DHT, SOS and entropy data, in order."""
    return [seg for marker, seg in parse_segments(data) if marker in IMAGE_MARKERS]


# --------------------------------------------------------------------------- doubles


def result() -> InferenceResult:
    return InferenceResult(
        object_type=ObjectType.SCREW,
        grade=Grade.GOOD,
        grade_score=1.2,
        type_confidence=0.93,
        grade_confidence=0.81,
        needs_review=False,
        latency_ms=17,
    )


def loop_running() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class RecordingSink:
    """InspectionSink double (SPEC-007 Protocol), thread safe."""

    def __init__(self) -> None:
        self.items: list[InspectionCreate] = []
        self.lock = threading.Lock()

    def put(self, inspection: InspectionCreate) -> None:
        with self.lock:
            self.items.append(inspection)

    def stats(self) -> SinkStats:
        return SinkStats(
            pending=len(self.items), dead=0, last_success_at=None, connectivity="disabled"
        )


class BlockingInferencer:
    """CA-07 inferencer: max concurrency, loop check and a blocking event."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self.loop_seen: list[bool] = []

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo("acc-model-v1", "b" * 64)

    def infer(self, image: Image.Image) -> InferenceResult:
        with self.lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.loop_seen.append(loop_running())
        self.started.set()
        try:
            assert self.release.wait(timeout=30), "test event never released"
            return result()
        finally:
            with self.lock:
                self.active -= 1


class RaisingInferencer:
    """Raises ``InferenceError`` on the first call only."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo("acc-model-v1", "a" * 64)

    def infer(self, image: Image.Image) -> InferenceResult:
        self.calls += 1
        if self.calls == 1:
            raise InferenceError("acc failure")
        return result()


# --------------------------------------------------------------------------- fixtures


@dataclass
class Edge:
    tmp: Path
    data_dir: Path
    dataset: Path
    token: str

    def app(self, inferencer: Any = "stub", sink: Any = None, **kwargs: Any) -> Any:
        inf = StubInferencer(result()) if inferencer == "stub" else inferencer
        return create_app(
            EdgeSettings(), inf, sink if sink is not None else RecordingSink(), **kwargs
        )

    @property
    def manifest(self) -> Path:
        return self.dataset / "manifest.csv"

    def captures(self) -> list[Path]:
        root = self.data_dir / "captures"
        return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []

    def images(self) -> list[Path]:
        raw = self.dataset / "raw"
        return sorted(p for p in raw.rglob("*") if p.is_file()) if raw.exists() else []

    def rows(self) -> list[dict[str, str]]:
        with self.manifest.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))


@pytest.fixture
def edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Edge:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)  # a relative write would land in tmp_path, never in the repository
    data_dir = tmp_path / "edge-data"
    dataset = tmp_path / "dataset"
    token = new_token()
    monkeypatch.setenv("EDGE_PORT", str(PORT))
    monkeypatch.setenv("EDGE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setenv("DATASET_DIR", str(dataset))
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    return Edge(tmp=tmp_path, data_dir=data_dir, dataset=dataset, token=token)


@pytest.fixture
def lan_spy(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Spy on ``qc_edge.netinfo.detect_lan_ips`` (the socket boundary)."""
    calls: list[int] = []

    def spy() -> list[str]:
        calls.append(1)
        return ["192.168.0.42"]

    monkeypatch.setattr(qc_edge.netinfo, "detect_lan_ips", spy)
    return calls


@pytest.fixture
def umask_guard() -> Iterator[Callable[[int], None]]:
    """Set the process umask; the original value is restored in a ``finally``."""
    original = os.umask(0o022)
    os.umask(original)
    try:
        yield lambda value: os.umask(value)
    finally:
        os.umask(original)


# --------------------------------------------------------------------------- requests


def console(
    app: Any,
    host: str | None = None,
    *,
    client: tuple[str, int] = ("127.0.0.1", 50000),
    port: int = PORT,
    path: str = "/",
) -> httpx.Response:
    """Console request through ``httpx.ASGITransport`` (SPEC "console de loopback")."""

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(transport=transport, base_url=f"http://127.0.0.1:{port}") as c:
            return await c.get(path, headers={"Host": host} if host is not None else None)

    return asyncio.run(go())


@dataclass
class RawResponse:
    status: int
    headers: list[tuple[bytes, bytes]]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


def raw_asgi(
    app: Any,
    method: str,
    path: str,
    headers: list[tuple[bytes, bytes]],
    body: bytes = b"",
    *,
    client: tuple[str, int] = ("127.0.0.1", 50000),
    query: bytes = b"",
) -> RawResponse:
    """Drive the ASGI app with exactly the given header list (no header added)."""

    async def go() -> RawResponse:
        sent = False
        state: dict[str, Any] = {"status": 0, "headers": []}
        out = bytearray()

        async def receive() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                state["headers"] = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                out.extend(message.get("body", b""))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query,
            "root_path": "",
            "headers": headers,
            "client": client,
            "server": ("127.0.0.1", PORT),
        }
        await app(scope, receive, send)
        return RawResponse(state["status"], state["headers"], bytes(out))

    return asyncio.run(go())


def collect_fields(**overrides: str) -> dict[str, str]:
    """SPEC "coleta válida": the CA-01 fields of SPEC-010."""
    base = {
        "mode": "collect",
        "item_id": "S-012",
        "object_type": "screw",
        "grade": "fair",
        "labeler": "a",
        "angle": "2",
    }
    base.update(overrides)
    return base


def inspect_fields(lot_id: str = "L-001") -> dict[str, str]:
    return {"lot_id": lot_id, "mode": "inspect"}


def post(
    client: Any,
    token: str,
    image: bytes,
    data: dict[str, str],
    *,
    content_type: str = "image/jpeg",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    all_headers = {SESSION_HEADER: token, **(headers or {})}
    return client.post(
        "/api/capture",
        headers=all_headers,
        data=data,
        files={"image": ("foto.jpg", image, content_type)},
    )


def multipart(data: dict[str, str], image: bytes, boundary: str) -> bytes:
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, v in data.items()
    ]
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
            'filename="foto.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
        ).encode()
        + image
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


def raw_collect(
    app: Any, token: str, user_agent: bytes, image: bytes, **overrides: str
) -> RawResponse:
    boundary = "acc" + secrets.token_hex(8)
    body = multipart(collect_fields(**overrides), image, boundary)
    headers = [
        (b"host", f"192.168.0.42:{PORT}".encode()),
        (b"x-session-token", token.encode()),
        (b"user-agent", user_agent),
        (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
        (b"content-length", str(len(body)).encode()),
    ]
    return raw_asgi(app, "POST", "/api/capture", headers, body, client=("192.168.0.50", 50000))


def call_main(main: Callable[[list[str]], Any], argv: list[str]) -> int:
    """Exit code of a CLI ``main(argv)``, returned or raised as ``SystemExit``."""
    try:
        value = main(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return value if isinstance(value, int) else 0


class UvicornSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Message and arguments of every record (the formatted text and the raw parts)."""
    parts = [caplog.text]
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(str(record.msg))
        parts.append(repr(record.args))
    return "\n".join(parts)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# =========================================================================== CA-01


@pytest.mark.parametrize(
    "host", ["127.0.0.1:8000", "localhost:8000", "LOCALHOST:8000", "[::1]:8000"]
)
def test_ca01_console_answers_loopback_hosts(edge: Edge, lan_spy: list[int], host: str) -> None:
    app = edge.app()
    response = console(app, host)
    assert response.status_code == 200, response.text
    assert "<svg" in response.text
    assert f"/capture?t={edge.token}" in response.text  # the pairing URL is still there
    assert lan_spy, "the detect_lan_ips spy was not used by the console"


# =========================================================================== CA-02


REFUSED_HOSTS = [
    "attacker.example:8000",
    "127.0.0.1",
    "127.0.0.1:8001",
    "localhost.:8000",
    "127.0.0.1.nip.io:8000",
    "192.168.0.42:8000",
]
RAW_HOST_HEADERS: dict[str, list[tuple[bytes, bytes]]] = {
    "empty": [(b"host", b"")],
    "absent": [],
    "two": [(b"host", b"127.0.0.1:8000"), (b"host", b"attacker.example:8000")],
}


def test_ca02_console_refuses_other_hosts_before_detecting_ips(
    edge: Edge, lan_spy: list[int], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    app = edge.app()
    responses: list[tuple[str, int, str]] = []
    for host in REFUSED_HOSTS:
        r = console(app, host)
        responses.append((host, r.status_code, r.text))
    for name, headers in RAW_HOST_HEADERS.items():
        raw = raw_asgi(app, "GET", "/", headers)
        responses.append((f"raw-{name}", raw.status, raw.text))

    for host, status_code, body in responses:
        assert status_code == 403, host
        assert edge.token not in body, host
    assert lan_spy == [], "detect_lan_ips ran before the Host check"
    assert "attacker.example" not in log_text(caplog)

    # control: the spy is effective (a loopback Host reaches detect_lan_ips)
    assert console(app, "127.0.0.1:8000").status_code == 200
    assert lan_spy


# =========================================================================== CA-03


def test_ca03_port_80_accepts_hosts_without_port(
    edge: Edge, lan_spy: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGE_PORT", "80")
    app = edge.app()
    for host in ("127.0.0.1", "localhost", "[::1]", "127.0.0.1:80"):
        r = console(app, host, port=80)
        assert r.status_code == 200, host
        assert "<svg" in r.text
    refused = console(app, "attacker.example", port=80)
    assert refused.status_code == 403
    assert edge.token not in refused.text
    assert is_allowed_console_host(None, 8000) is False
    assert is_allowed_console_host("", 80) is False


# =========================================================================== CA-04


def _start_real_edge(tmp_path: Path, token: str, port: int) -> subprocess.Popen[bytes]:
    env = {k: v for k, v in os.environ.items() if k not in EDGE_ENV_VARS}
    env.update(
        EDGE_HOST="127.0.0.1",
        EDGE_PORT=str(port),
        EDGE_SESSION_TOKEN=token,
        EDGE_DATA_DIR=str(tmp_path / "data"),
        DATASET_DIR=str(tmp_path / "dataset"),
        PYTHONUNBUFFERED="1",
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", "from qc_edge.cli import main; main()", "--stub-model"],
        env=env,
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 20
    while True:
        try:
            httpx.get(f"http://127.0.0.1:{port}/static/capture.js", timeout=0.5)
            return proc
        except httpx.TransportError:
            if proc.poll() is not None:
                out = proc.stdout.read().decode() if proc.stdout else ""
                raise AssertionError(f"server exited: {out}") from None
            if time.monotonic() > deadline:
                proc.kill()
                raise AssertionError("server did not start") from None
            time.sleep(0.1)


def _stop(proc: subprocess.Popen[bytes]) -> str:
    proc.terminate()
    try:
        output, _ = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        output, _ = proc.communicate()
    return output.decode("utf-8", "replace")


def _raw_http(port: int, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(request)
        chunks = []
        while True:
            try:
                chunk = s.recv(65536)
            except TimeoutError:
                break
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


@pytest.mark.slow
def test_ca04_real_server_refuses_a_rebound_host(tmp_path: Path) -> None:
    token = new_token()
    port = free_port()
    proc = _start_real_edge(tmp_path, token, port)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=10) as c:
            rebound = c.get("/", headers={"Host": f"attacker.example:{port}"})
            normal = c.get("/")
            by_name = c.get("/", headers={"Host": f"localhost:{port}"})
        # exploratory, same server: two Host headers and HTTP/1.0 without Host
        two_hosts = _raw_http(
            port,
            f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nHost: attacker.example:{port}\r\n"
            "Connection: close\r\n\r\n".encode(),
        )
        no_host = _raw_http(port, b"GET / HTTP/1.0\r\n\r\n")
    finally:
        output = _stop(proc)
    assert proc.returncode is not None
    assert rebound.status_code == 403, output
    assert token not in rebound.text
    assert normal.status_code == 200
    assert "<svg" in normal.text
    assert by_name.status_code == 200
    assert two_hosts.split(b"\r\n", 1)[0] in (
        b"HTTP/1.1 403 Forbidden",
        b"HTTP/1.1 400 Bad Request",
    )
    assert token.encode() not in two_hosts
    assert no_host.split(b"\r\n", 1)[0].split(b" ")[1] in (b"400", b"403")
    assert token.encode() not in no_host
    assert "attacker.example" not in output
    assert token not in output


# =========================================================================== CA-05


def test_ca05_token_routes_do_not_check_the_host(edge: Edge) -> None:
    app = edge.app()

    async def go() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app, client=("192.168.0.50", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://192.168.0.42:8000") as c:
            page = await c.get(
                "/capture", params={"t": edge.token}, headers={"Host": "192.168.0.42:8000"}
            )
            capture = await c.post(
                "/api/capture",
                headers={SESSION_HEADER: edge.token, "Host": "10.0.0.7:8000"},
                data=inspect_fields(),
                files={"image": ("foto.jpg", clean_jpeg(), "image/jpeg")},
            )
            return page, capture

    page, capture = asyncio.run(go())
    assert page.status_code == 200
    assert capture.status_code == 200, capture.text


# =========================================================================== CA-06


@pytest.mark.parametrize("value", ["::", "::1", "fe80::1", "localhost"])
def test_ca06_edge_host_must_be_ipv4(
    edge: Edge,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    monkeypatch.setenv("EDGE_HOST", value)
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    caplog.set_level(logging.DEBUG)
    assert call_main(qc_edge.cli.main, []) == 2
    out = capsys.readouterr()
    text = "\n".join([log_text(caplog), out.out, out.err])
    assert "EDGE_HOST" in text
    assert spy.calls == []
    # SPEC §4.3: the message cites EDGE_HOST without the value
    for line in text.splitlines():
        if "EDGE_HOST" in line:
            assert value not in line.replace("EDGE_HOST", ""), line


@pytest.mark.parametrize("value", ["0.0.0.0", "127.0.0.1", "192.168.0.10"])
def test_ca06_ipv4_edge_host_is_passed_to_uvicorn(
    edge: Edge, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("EDGE_HOST", value)
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    assert call_main(qc_edge.cli.main, []) == 0
    assert len(spy.calls) == 1
    assert spy.calls[0][1]["host"] == value


# =========================================================================== CA-07


async def _apost(c: httpx.AsyncClient, token: str, lot_id: str) -> httpx.Response:
    return await c.post(
        "/api/capture",
        headers={SESSION_HEADER: token},
        data=inspect_fields(lot_id),
        files={"image": ("foto.jpg", clean_jpeg(), "image/jpeg")},
    )


def test_ca07_waiting_requests_do_not_block_the_status(edge: Edge) -> None:
    inf = BlockingInferencer()
    sink = RecordingSink()
    app = edge.app(inf, sink, max_concurrent_decodes=1, decode_wait_s=3)

    async def scenario() -> dict[str, Any]:
        transport = httpx.ASGITransport(app=app, client=("192.168.0.50", 50000))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://192.168.0.42:8000", timeout=30
        ) as c:
            first = asyncio.create_task(_apost(c, edge.token, "L-FIRST"))
            t0 = time.monotonic()
            while not inf.started.is_set():
                assert time.monotonic() - t0 < 10, "the first capture never reached infer"
                await asyncio.sleep(0.01)

            async def timed(i: int) -> tuple[httpx.Response, float]:
                sent = time.monotonic()
                r = await _apost(c, edge.token, f"P-{i}")
                return r, time.monotonic() - sent

            waiting = [asyncio.create_task(timed(i)) for i in range(45)]
            await asyncio.sleep(0.5)
            s0 = time.monotonic()
            status = await c.get("/api/status", headers={SESSION_HEADER: edge.token})
            status_elapsed = time.monotonic() - s0
            busy = await asyncio.gather(*waiting)
            inf.release.set()
            return {
                "status": status,
                "status_elapsed": status_elapsed,
                "busy": busy,
                "first": await first,
            }

    try:
        out = asyncio.run(scenario())
    finally:
        inf.release.set()
    assert out["status"].status_code == 200
    assert out["status_elapsed"] < 1.0, out["status_elapsed"]
    for response, elapsed in out["busy"]:
        assert response.status_code == 503
        assert response.json() == BUSY
        assert elapsed <= 5.0, elapsed
    assert out["first"].status_code == 200, out["first"].text
    assert inf.max_active == 1
    assert inf.loop_seen == [False]
    assert len(sink.items) == 1
    jpgs = [p for p in edge.captures() if p.suffix == ".jpg"]
    assert len(jpgs) == 1
    assert edge.captures() == jpgs


def test_extra_ca07_with_threads_and_a_test_client(edge: Edge) -> None:
    """Same CA-07 scenario with the other form the SPEC allows (threads + ``TestClient``)."""
    inf = BlockingInferencer()
    sink = RecordingSink()
    app = edge.app(inf, sink, max_concurrent_decodes=1, decode_wait_s=3)
    busy: list[tuple[int, float]] = []
    lock = threading.Lock()
    with TestClient(app) as client:
        first: list[httpx.Response] = []
        t_first = threading.Thread(
            target=lambda: first.append(
                post(client, edge.token, clean_jpeg(), inspect_fields("L-FIRST"))
            ),
            daemon=True,
        )
        t_first.start()
        assert inf.started.wait(10)

        def worker(i: int) -> None:
            sent = time.monotonic()
            r = post(client, edge.token, clean_jpeg(), inspect_fields(f"P-{i}"))
            with lock:
                busy.append((r.status_code, time.monotonic() - sent))

        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(45)]
        for t in threads:
            t.start()
        time.sleep(0.5)
        s0 = time.monotonic()
        status = client.get("/api/status", headers={SESSION_HEADER: edge.token})
        status_elapsed = time.monotonic() - s0
        for t in threads:
            t.join(timeout=15)
        inf.release.set()
        t_first.join(timeout=15)
    assert status.status_code == 200
    assert status_elapsed < 1.0, status_elapsed
    assert len(busy) == 45
    assert all(code == 503 and elapsed <= 5.0 for code, elapsed in busy), busy
    assert first[0].status_code == 200
    assert inf.max_active == 1
    assert len(sink.items) == 1
    assert len(edge.captures()) == 1


class _ServerThread:
    """Real uvicorn server on loopback, in a thread, with an app built by the test."""

    def __init__(self, app: Any, port: int) -> None:
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> _ServerThread:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            assert time.monotonic() < deadline, "server did not start"
            time.sleep(0.05)
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)


@pytest.mark.slow
def test_extra_ca07_real_server_keeps_the_status_fast(
    edge: Edge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-03 measured as in the report: real uvicorn, 45 waiting captures, 40 threads."""
    port = free_port()
    monkeypatch.setenv("EDGE_PORT", str(port))  # the console checks the Host against it
    inf = BlockingInferencer()
    app = edge.app(inf, RecordingSink(), max_concurrent_decodes=1, decode_wait_s=3)
    busy: list[tuple[int, float]] = []
    lock = threading.Lock()
    with _ServerThread(app, port):
        base = f"http://127.0.0.1:{port}"
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=100)
        with httpx.Client(base_url=base, timeout=30, limits=limits) as c:
            first: list[int] = []
            t_first = threading.Thread(
                target=lambda: first.append(
                    post(c, edge.token, clean_jpeg(), inspect_fields("L-FIRST")).status_code
                ),
                daemon=True,
            )
            t_first.start()
            assert inf.started.wait(10)

            def worker(i: int) -> None:
                sent = time.monotonic()
                code = post(c, edge.token, clean_jpeg(), inspect_fields(f"P-{i}")).status_code
                with lock:
                    busy.append((code, time.monotonic() - sent))

            threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(45)]
            for t in threads:
                t.start()
            time.sleep(0.5)
            s0 = time.monotonic()
            status = c.get("/api/status", headers={SESSION_HEADER: edge.token})
            status_elapsed = time.monotonic() - s0
            console_ok = c.get("/").status_code
            for t in threads:
                t.join(timeout=15)
            inf.release.set()
            t_first.join(timeout=15)
    assert status.status_code == 200
    assert status_elapsed < 1.0, status_elapsed
    assert console_ok == 200
    assert len(busy) == 45
    assert all(code == 503 and elapsed <= 5.0 for code, elapsed in busy), sorted(busy)[-3:]
    assert first == [200]
    assert inf.max_active == 1


# =========================================================================== CA-08


def test_ca08_blocking_work_never_runs_on_the_event_loop(
    edge: Edge, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = qc_edge.limits.load_capture_image
    seen: list[bool] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(loop_running())
        return original(*args, **kwargs)

    monkeypatch.setattr(qc_edge.limits, "load_capture_image", spy)
    app = edge.app()
    with TestClient(app, raise_server_exceptions=False) as client:
        ok = post(client, edge.token, clean_jpeg(), inspect_fields())
        gif = post(client, edge.token, gif_bytes(), inspect_fields(), content_type="image/gif")
        collected = post(client, edge.token, clean_jpeg(), collect_fields())
    assert (ok.status_code, gif.status_code, collected.status_code) == (200, 415, 200)
    assert seen == [False, False, False]


def test_ca08_slot_is_released_after_an_inference_error(edge: Edge) -> None:
    inf = RaisingInferencer()
    app = edge.app(inf, RecordingSink(), max_concurrent_decodes=1, decode_wait_s=1)
    with TestClient(app, raise_server_exceptions=False) as client:
        codes = [
            post(client, edge.token, clean_jpeg(), inspect_fields()).status_code for _ in "abc"
        ]
    assert codes == [500, 200, 200]


class SleepingInferencer:
    """Short ``infer`` that records the maximum concurrency."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo("acc-model-v1", "d" * 64)

    def infer(self, image: Image.Image) -> InferenceResult:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.seconds)
            return result()
        finally:
            with self.lock:
                self.active -= 1


@pytest.mark.parametrize("slots", [1, 2])
def test_extra_limiter_timeouts_racing_with_releases_never_leak_a_slot(
    edge: Edge, slots: int
) -> None:
    """Many waits time out while slots are being released: no 500, no leak, no over-release."""
    inf = SleepingInferencer(0.01)
    app = edge.app(inf, RecordingSink(), max_concurrent_decodes=slots, decode_wait_s=0.02)

    async def burst() -> list[int]:
        transport = httpx.ASGITransport(app=app, client=("192.168.0.50", 50000))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://192.168.0.42:8000", timeout=30
        ) as c:
            first = await asyncio.gather(*(_apost(c, edge.token, f"B-{i}") for i in range(150)))
            # afterwards every slot is free again: ``slots`` slow captures run together
            inf.seconds = 0.3
            inf.max_active = 0
            again = await asyncio.gather(*(_apost(c, edge.token, f"A-{i}") for i in range(slots)))
            return [r.status_code for r in [*first, *again]]

    codes = asyncio.run(burst())
    assert set(codes[:150]) <= {200, 503}, sorted(set(codes))
    assert 200 in codes[:150]
    assert codes[150:] == [200] * slots
    assert inf.max_active == slots


def test_extra_one_app_survives_successive_test_clients(edge: Edge) -> None:
    """SPEC §7: several ``TestClient`` (one event loop each, in sequence) share the semaphore."""
    app = edge.app(max_concurrent_decodes=1, decode_wait_s=1)
    codes = []
    for _ in range(3):
        with TestClient(app) as client:
            codes.append(post(client, edge.token, clean_jpeg(), inspect_fields()).status_code)
    plain = TestClient(app)
    codes += [post(plain, edge.token, clean_jpeg(), inspect_fields()).status_code for _ in "ab"]
    assert codes == [200] * 5


# =========================================================================== CA-09


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.parametrize("umask", [0o022, 0o077, 0o000, 0o277], ids=oct)
def test_ca09_capture_modes_are_exact_whatever_the_umask(
    edge: Edge, umask_guard: Callable[[int], None], umask: int
) -> None:
    assert not edge.data_dir.exists()
    umask_guard(umask)
    settings = EdgeSettings()  # loading the config creates EDGE_DATA_DIR
    assert edge.data_dir.is_dir()
    app = create_app(settings, StubInferencer(result()), RecordingSink())
    with TestClient(app) as client:
        r_jpeg = post(client, edge.token, clean_jpeg(), inspect_fields())
        r_png = post(client, edge.token, png_bytes(), inspect_fields(), content_type="image/png")
    umask_guard(0o022)
    assert (r_jpeg.status_code, r_png.status_code) == (200, 200), (r_jpeg.text, r_png.text)
    captures = edge.data_dir / "captures"
    days = [p for p in captures.iterdir() if p.is_dir()]
    files = edge.captures()
    assert len(days) >= 1
    assert len(files) == 2
    assert all(p.suffix == ".jpg" for p in files)
    assert _mode(edge.data_dir) == 0o700
    assert _mode(captures) == 0o700
    assert all(_mode(d) == 0o700 for d in days)
    assert [_mode(p) for p in files] == [0o600, 0o600]


def test_ca09_existing_dirs_keep_data_dir_and_fix_captures(
    edge: Edge, umask_guard: Callable[[int], None]
) -> None:
    captures = edge.data_dir / "captures"
    captures.mkdir(parents=True)
    os.chmod(edge.data_dir, 0o755)
    os.chmod(captures, 0o755)
    app = edge.app()
    with TestClient(app):
        pass
    assert _mode(captures) == 0o700
    assert _mode(edge.data_dir) == 0o755


def test_extra_ca09_nested_data_dir_with_owner_bits_removed(
    edge: Edge, monkeypatch: pytest.MonkeyPatch, umask_guard: Callable[[int], None]
) -> None:
    nested = edge.tmp / "a" / "b" / "edge-data"
    monkeypatch.setenv("EDGE_DATA_DIR", str(nested))
    umask_guard(0o277)
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, clean_jpeg(), inspect_fields())
    umask_guard(0o022)
    assert r.status_code == 200, r.text
    assert _mode(nested) == 0o700
    files = sorted(p for p in (nested / "captures").rglob("*") if p.is_file())
    assert [_mode(p) for p in files] == [0o600]


# =========================================================================== CA-10


def test_ca10_unknown_arguments_exit_2_without_values(
    edge: Edge,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    caplog.set_level(logging.DEBUG)
    token_marker = new_marker()
    positional_marker = new_marker()

    assert call_main(qc_edge.cli.main, ["--stub-modle"]) == 2
    first_log = log_text(caplog)
    assert "--stub-modle" in first_log
    assert call_main(qc_edge.cli.main, [f"--token={token_marker}"]) == 2
    assert call_main(qc_edge.cli.main, [positional_marker]) == 2
    assert spy.calls == []
    out = capsys.readouterr()
    text = "\n".join([log_text(caplog), out.out, out.err])
    assert token_marker not in text
    assert positional_marker not in text

    assert call_main(qc_edge.cli.main, []) == 0
    assert len(spy.calls) == 1
    assert call_main(qc_edge.cli.main, ["--stub-model"]) == 0
    assert len(spy.calls) == 2


# =========================================================================== CA-11


def _markdown_lines(text: str) -> list[tuple[str, bool]]:
    """``(line, inside_code_block)``; fence lines themselves count as code."""
    out: list[tuple[str, bool]] = []
    inside = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
            out.append((line, True))
            continue
        out.append((line, inside))
    return out


def _section(text: str, matches: Callable[[str], bool]) -> str:
    """Body of the first heading (outside code) accepted by ``matches``, up to the next heading
    of the same or a higher level."""
    lines = _markdown_lines(text)
    for idx, (line, code) in enumerate(lines):
        heading = re.match(r"(#+) ", line)
        if code or not heading or not matches(line):
            continue
        level = len(heading.group(1))
        body = []
        for nxt, nxt_code in lines[idx + 1 :]:
            other = re.match(r"(#+) ", nxt)
            if not nxt_code and other and len(other.group(1)) <= level:
                break
            body.append(nxt)
        return "\n".join(body)
    raise AssertionError("section not found")


def test_ca11_readme_and_env_example() -> None:
    text = (EDGE_ROOT / "README.md").read_text(encoding="utf-8")
    lines = _markdown_lines(text)
    code_lines = [line for line, code in lines if code]

    opening = [
        line
        for line in code_lines
        if "ufw allow" in line
        or ("firewall-cmd" in line and "--add-" in line)
        or "nft add rule" in line
        or "nft insert rule" in line
    ]
    assert opening, "no firewall command found in the README code blocks"
    for line in opening:
        assert "from " in line or "source address=" in line or "saddr" in line, line
    assert not [line for line in code_lines if "--permanent" in line]
    assert "ip -4 route show scope link" in text

    security = _section(text, lambda line: line.strip() == "## Segurança na operação")
    for needle in ("EDGE_SESSION_TOKEN", "WPA2", "172.17."):
        assert needle in security, needle

    edge_host = [line for line in text.splitlines() if line.startswith("| `EDGE_HOST` ")]
    assert len(edge_host) == 1
    assert "IPv4" in edge_host[0]
    assert "ou IPv6" not in edge_host[0]

    collect = _section(text, lambda line: "Modo coleta" in line)
    for needle in ("python -m qc_edge.privacy", "--fix", "orientation", "dataset-protocol.md"):
        assert needle in collect, needle

    env_lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    idx = next(i for i, line in enumerate(env_lines) if line.startswith("EDGE_HOST="))
    assert env_lines[idx - 1].startswith("#")
    assert "IPv4" in env_lines[idx - 1]


def test_extra_ca11_readme_other_items_of_section_4_6() -> None:
    """§4.6 items that CA-11 does not spell out: undo commands, persistence and campus."""
    text = (EDGE_ROOT / "README.md").read_text(encoding="utf-8")
    code = "\n".join(line for line, inside in _markdown_lines(text) if inside)
    assert "ufw delete allow proto tcp from" in code
    assert "--remove-rich-rule" in code
    assert "handle" in text
    assert "persiste" in text
    assert "campus" in text
    assert "http://127.0.0.1:" in text and "http://localhost:" in text
    assert "403" in text
    assert "WPA3" in text
    # no command opens the port without an origin
    for line in code.splitlines():
        assert not re.search(r"ufw allow 8000", line), line
        assert "--add-port" not in line, line
        if "dport 8000 accept" in line:
            assert "saddr" in line, line


# =========================================================================== CA-12


SPEC_022 = ROOT / "tests" / "acceptance" / "test_spec_022.py"
SPEC_023 = ROOT / "packages" / "contracts" / "tests" / "acceptance" / "test_spec_023.py"
# Counted on `main` (8392a8e) with `pytest --collect-only -q <file>` before this SPEC.
MAIN_COLLECTED = {SPEC_022: 38, SPEC_023: 22}


def _collected(path: Path) -> int:
    # `--collect-only` never touches the database: drop both variables of the SPEC-001 policy,
    # so the count is the same with or without `CI=true` / `TEST_DATABASE_URL` (r3 fix).
    env = {k: v for k, v in os.environ.items() if k not in ("TEST_DATABASE_URL", "CI")}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            str(path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    match = re.search(r"(\d+) tests? collected", proc.stdout)
    assert match, proc.stdout
    return int(match.group(1))


def test_ca12_docstrings_of_spec_022_and_023() -> None:
    doc_022 = ast.get_docstring(ast.parse(SPEC_022.read_text(encoding="utf-8"))) or ""
    doc_023 = ast.get_docstring(ast.parse(SPEC_023.read_text(encoding="utf-8"))) or ""
    assert "CA-01 to CA-16" not in doc_022
    assert "CA-15 is checked by CI" in doc_022
    assert "and CA-13" not in doc_023
    assert "CA-13 is checked by CI" in doc_023
    for path, expected in MAIN_COLLECTED.items():
        assert _collected(path) == expected, path


# =========================================================================== CA-13


def test_ca13_collect_stores_the_jpeg_without_private_segments(edge: Edge) -> None:
    data, com_marker = metadata_jpeg()
    clean = clean_jpeg(seed=31)
    app = edge.app()
    with TestClient(app) as client:
        r_meta = post(client, edge.token, data, collect_fields())
        r_clean = post(client, edge.token, clean, collect_fields(angle="3"))
        r_inspect = post(client, edge.token, data, inspect_fields())
    assert r_meta.status_code == 200, r_meta.text
    assert r_clean.status_code == 200, r_clean.text
    assert r_inspect.status_code == 200, r_inspect.text

    stored_meta = edge.dataset / r_meta.json()["image_path"]
    stored = stored_meta.read_bytes()
    for forbidden in (b"Exif\x00\x00", b"http://ns.adobe.com/xap/1.0/", b"Photoshop 3.0"):
        assert forbidden not in stored, forbidden
    assert com_marker not in stored
    assert b"ftypmp42" not in stored
    assert stored.endswith(EOI)
    with Image.open(stored_meta) as img:
        assert len(img.getexif()) == 0
    assert np.array_equal(pixels(stored_meta), pixels(data))
    assert same_loaded(stored_meta, data)  # also through the project loader (r2, ADR-004)

    assert (edge.dataset / r_clean.json()["image_path"]).read_bytes() == clean

    captures = edge.captures()
    assert len(captures) == 1
    assert captures[0].read_bytes() == data  # inspect mode keeps the JPEG as received


# =========================================================================== CA-14


def _assert_no_input_bytes(message: str, data: bytes) -> None:
    assert "\\x" not in message, message
    assert "b'" not in message and 'b"' not in message, message
    assert data[:10].decode("latin-1") not in message, message
    assert data[2:8].hex() not in message.lower().replace(" ", ""), message


def test_ca14_findings_and_strip_of_the_metadata_jpeg() -> None:
    data, _ = metadata_jpeg()
    assert jpeg_private_findings(data) == frozenset({"app1", "app13", "com", "trailer"})
    assert jpeg_private_findings(strip_private_segments(data)) == frozenset()


def test_ca14_eoi_inside_app1_is_not_the_end() -> None:
    thumbnail = clean_jpeg(seed=4)
    app1 = segment(0xE1, EMPTY_TIFF + thumbnail + b"tail")
    assert EOI in app1[4:-4]
    base = clean_jpeg(seed=5, progressive=True)
    data = base[:2] + app1 + base[2:]
    out = strip_private_segments(data)
    assert image_segments(out) == image_segments(data)
    assert len(image_segments(data)) > 6
    assert np.array_equal(pixels(out), pixels(data))
    assert jpeg_private_findings(data) == frozenset({"app1"})


@pytest.mark.parametrize("kind", ["not-a-jpeg", "first-100-bytes", "app0-length-1"])
def test_ca14_structural_errors(kind: str) -> None:
    valid = clean_jpeg()
    if kind == "not-a-jpeg":
        data = b"not a jpeg"
    elif kind == "first-100-bytes":
        data = valid[:100]
        assert EOI not in data
    else:
        data = SOI + b"\xff\xe0\x00\x01" + valid[2:]
    for func in (strip_private_segments, jpeg_private_findings):
        with pytest.raises(JpegStructureError) as excinfo:
            func(data)
        assert isinstance(excinfo.value, ValueError)
        _assert_no_input_bytes(str(excinfo.value), data)


# =========================================================================== CA-15


@dataclass
class Dataset:
    root: Path
    outside: Path
    snapshot_before: dict[str, bytes] = field(default_factory=dict)

    @property
    def folder(self) -> Path:
        return self.root / "raw" / "screw" / "fair"

    def files(self) -> dict[str, bytes]:
        out = {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file() and not p.is_symlink()
        }
        out["<outside>"] = self.outside.read_bytes()
        return out

    def names(self) -> set[str]:
        return {p.name for p in self.folder.iterdir()}


def make_dataset(tmp_path: Path, name: str = "D") -> Dataset:
    root = tmp_path / name
    folder = root / "raw" / "screw" / "fair"
    folder.mkdir(parents=True)
    (root / "manifest.csv").write_text(
        MANIFEST_HEADER
        + "raw/screw/fair/a.jpg,S-001,screw,fair,a,0,2026-10-20T10:00:00Z,seed,\n"
        + "raw/screw/fair/b.jpg,S-001,screw,fair,a,1,2026-10-20T10:00:01Z,seed,\n"
        + "raw/screw/fair/c.jpg,S-001,screw,fair,a,2,2026-10-20T10:00:02Z,seed,\n",
        encoding="utf-8",
    )
    (folder / "a.jpg").write_bytes(clean_jpeg(seed=11))
    (folder / "b.jpg").write_bytes(exif_jpeg(seed=12))
    (folder / "c.jpg").write_bytes(clean_jpeg(seed=13) + MOTION_TRAILER)
    outside = tmp_path / f"{name}-outside.jpg"
    outside.write_bytes(metadata_jpeg(seed=14)[0])
    (folder / "d.jpg").symlink_to(outside)
    return Dataset(root=root, outside=outside)


def run_privacy(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = call_main(qc_edge.privacy.main, argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_ca15_scan_reports_without_changing_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    ds = make_dataset(tmp_path)
    caplog.clear()  # Pillow logs the EXIF tags at DEBUG while the test builds b.jpg
    before = ds.files()
    code, out, err = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    assert code == 1
    lines = out.splitlines()
    assert lines == [
        "raw/screw/fair/b.jpg: app1",
        "raw/screw/fair/c.jpg: trailer",
        "checked 3 images, 2 with private data",
    ]
    for text in (out, err, log_text(caplog)):
        assert str(ds.root) not in text
        for latitude in LATITUDE_TEXTS:
            assert latitude not in text
    assert ds.files() == before


@pytest.mark.parametrize("umask", [0o022, 0o277], ids=oct)
def test_ca15_fix_rewrites_only_the_private_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    umask_guard: Callable[[int], None],
    umask: int,
) -> None:
    ds = make_dataset(tmp_path)
    before = ds.files()
    pixels_before = {n: pixels(ds.folder / n) for n in ("b.jpg", "c.jpg")}
    loaded_before = {n: loaded(ds.folder / n) for n in ("b.jpg", "c.jpg")}
    assert run_privacy(["--dataset-dir", str(ds.root)], capsys)[0] == 1

    umask_guard(umask)
    try:
        code, out, _ = run_privacy(["--dataset-dir", str(ds.root), "--fix"], capsys)
    finally:
        umask_guard(0o022)
    assert code == 0, out
    lines = out.splitlines()
    assert "fixed raw/screw/fair/b.jpg" in lines
    assert "fixed raw/screw/fair/c.jpg" in lines
    for name in ("b.jpg", "c.jpg"):
        path = ds.folder / name
        assert jpeg_private_findings(path.read_bytes()) == frozenset()
        assert np.array_equal(pixels(path), pixels_before[name])
        assert loaded(path).shape == loaded_before[name].shape
        assert np.array_equal(loaded(path), loaded_before[name])
        assert _mode(path) == 0o600
    after = ds.files()
    for key in ("raw/screw/fair/a.jpg", "manifest.csv", "<outside>"):
        assert after[key] == before[key], key
    assert ds.names() == {"a.jpg", "b.jpg", "c.jpg", "d.jpg"}  # no temporary left
    assert {p.name for p in ds.root.iterdir()} <= {"raw", "manifest.csv", "manifest.csv.lock"}
    assert (ds.folder / "d.jpg").is_symlink()

    code, out, _ = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    assert code == 0
    assert out.splitlines() == ["checked 3 images, 0 with private data"]


@pytest.mark.parametrize("kind", ["missing-dir", "token-argument"])
def test_ca15_usage_errors_exit_2_without_echo(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    kind: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = new_marker()
    if kind == "missing-dir":
        argv = ["--dataset-dir", str(tmp_path / marker)]
    else:
        ds = make_dataset(tmp_path)
        argv = ["--dataset-dir", str(ds.root), f"--token={marker}"]
    caplog.clear()
    code, out, err = run_privacy(argv, capsys)
    assert code == 2
    for text in (out, err, log_text(caplog)):
        assert marker not in text


# =========================================================================== CA-16


def test_ca16_unwalkable_jpeg_is_415_and_releases_the_slot(
    edge: Edge, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def refuse(data: bytes) -> bytes:
        calls.append(len(data))
        raise JpegStructureError("acc unsupported structure")

    monkeypatch.setattr(qc_edge.jpeg, "strip_private_segments", refuse)
    app = edge.app(max_concurrent_decodes=1, decode_wait_s=1)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = post(client, edge.token, clean_jpeg(), collect_fields())
        after = post(client, edge.token, clean_jpeg(), inspect_fields())
    assert r.status_code == 415
    assert r.json() == UNSUPPORTED
    assert calls, "the strip_private_segments spy was never called"
    assert edge.images() == []
    assert not edge.manifest.exists() or edge.rows() == []
    assert after.status_code == 200, after.text


# =========================================================================== CA-17


def _fd_path(fd: int) -> str:
    return os.readlink(f"/proc/self/fd/{fd}")


def _subsequence(needles: list[Callable[[str], bool]], haystack: list[str]) -> bool:
    it = iter(haystack)
    return all(any(needle(item) for item in it) for needle in needles)


def test_ca17_directories_are_synced_in_order(edge: Edge, monkeypatch: pytest.MonkeyPatch) -> None:
    real_fsync = os.fsync
    paths: list[str] = []

    def spy(fd: int) -> None:
        paths.append(_fd_path(fd))
        return real_fsync(fd)

    assert not edge.dataset.exists()
    monkeypatch.setattr(os, "fsync", spy)
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, clean_jpeg(), collect_fields())
    monkeypatch.setattr(os, "fsync", real_fsync)
    assert r.status_code == 200, r.text

    d = str(edge.dataset)
    parents = {str(edge.dataset.parent), d, f"{d}/raw", f"{d}/raw/screw"}
    first_file = next(
        i
        for i, p in enumerate(paths)
        if p.startswith(f"{d}/raw/screw/fair/") and p != f"{d}/raw/screw/fair"
    )
    assert parents <= set(paths[:first_file]), paths
    assert _subsequence(
        [
            lambda p: p.startswith(f"{d}/raw/screw/fair/"),
            lambda p: p == f"{d}/raw/screw/fair",
            lambda p: p == f"{d}/manifest.csv",
            lambda p: p == d,
        ],
        paths[first_file:],
    ), paths


def test_ca17_directory_sync_errors_are_warnings(
    edge: Edge, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real_fsync = os.fsync
    refused: list[str] = []

    def spy(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            refused.append(_fd_path(fd))
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))
        return real_fsync(fd)

    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(os, "fsync", spy)
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, clean_jpeg(), collect_fields())
    monkeypatch.setattr(os, "fsync", real_fsync)
    assert r.status_code == 200, r.text
    rows = edge.rows()
    assert len(rows) == 1
    assert (edge.dataset / rows[0]["image_path"]).is_file()
    assert refused, "no directory fsync was attempted"
    warnings = [
        rec
        for rec in caplog.records
        if rec.levelno == logging.WARNING and rec.name.startswith("qc_edge")
    ]
    assert len(warnings) == len(refused), ([w.getMessage() for w in warnings], refused)
    assert all(os.strerror(errno.EINVAL) in w.getMessage() for w in warnings)


# =========================================================================== CA-18


@pytest.mark.parametrize(
    "char",
    ["\u2028", "\u2029", "\u202e", "\u2066", "\u200f", "\u00ad"],
    ids=lambda c: f"U+{ord(c):04X}",
)
def test_ca18_notes_with_separators_or_format_chars_are_422(edge: Edge, char: str) -> None:
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, clean_jpeg(), collect_fields(notes=f"dúvida{char}fair"))
    assert r.status_code == 422, r.text
    assert "detail" in r.json()
    assert not edge.dataset.exists() or list(edge.dataset.rglob("*")) == []


def test_ca18_valid_notes_are_stored_unchanged(edge: Edge) -> None:
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, clean_jpeg(), collect_fields(notes="dúvida fair/poor"))
    assert r.status_code == 200, r.text
    assert edge.rows()[0]["notes"] == "dúvida fair/poor"


def test_ca18_user_agent_controls_become_spaces_before_the_cut(edge: Edge) -> None:
    app = edge.app()
    raw = raw_collect(app, edge.token, b"Phone\x85X\tY" + b"z" * 70, clean_jpeg())
    assert raw.status == 200, raw.text
    device = edge.rows()[0]["capture_device"]
    assert device == "Phone X Y" + "z" * 51
    assert len(device) == 60
    assert len(edge.manifest.read_text(encoding="utf-8").splitlines()) == 2


# =========================================================================== CA-19


def _assert_collect_wrote_nothing(edge: Edge) -> None:
    assert edge.images() == []
    assert not edge.manifest.exists() or edge.rows() == []


def test_ca19_rot6_is_portrait_for_load_image() -> None:
    """Precondition of CA-19: the project loader applies the EXIF rotation of ``rot6``."""
    rot6 = oriented_jpeg(6)
    assert load_image(rot6).size == (48, 64)
    assert load_image(oriented_jpeg(1)).size == (64, 48)


def test_ca19_rotated_jpeg_is_415_in_collect_and_kept_in_inspect(edge: Edge) -> None:
    rot6 = oriented_jpeg(6)
    assert load_image(rot6).size == (48, 64)
    app = edge.app(max_concurrent_decodes=1, decode_wait_s=1)
    with TestClient(app) as client:
        refused = post(client, edge.token, rot6, collect_fields())
        inspected = post(client, edge.token, rot6, inspect_fields())
    assert refused.status_code == 415, refused.text
    assert refused.json() == ORIENTATION_REFUSED
    _assert_collect_wrote_nothing(edge)
    assert inspected.status_code == 200, inspected.text
    captures = edge.captures()
    assert len(captures) == 1
    assert captures[0].read_bytes() == rot6  # inspect mode keeps the JPEG as received


def test_ca19_orientation_1_is_stored_without_private_data(edge: Edge) -> None:
    rot1 = oriented_jpeg(1)
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, rot1, collect_fields())
    assert r.status_code == 200, r.text
    stored = edge.dataset / r.json()["image_path"]
    assert jpeg_private_findings(stored.read_bytes()) == frozenset()
    assert load_image(stored).size == load_image(rot1).size
    assert np.array_equal(loaded(stored), loaded(rot1))


def test_ca19_has_exif_rotation() -> None:
    assert has_exif_rotation(oriented_jpeg(6)) is True
    assert has_exif_rotation(oriented_jpeg(1)) is False
    assert has_exif_rotation(clean_jpeg()) is False
    with pytest.raises(JpegStructureError):
        has_exif_rotation(b"not a jpeg")


def _orientation_dataset(tmp_path: Path) -> tuple[Path, Path, bytes]:
    root = tmp_path / "D19"
    folder = root / "raw" / "screw" / "fair"
    folder.mkdir(parents=True)
    (root / "manifest.csv").write_text(
        MANIFEST_HEADER
        + "raw/screw/fair/e.jpg,S-001,screw,fair,a,0,2026-10-20T10:00:00Z,seed,\n"
        + "raw/screw/fair/f.jpg,S-001,screw,fair,a,1,2026-10-20T10:00:01Z,seed,\n",
        encoding="utf-8",
    )
    rot6 = oriented_jpeg(6, seed=41)
    (folder / "e.jpg").write_bytes(rot6)
    (folder / "f.jpg").write_bytes(oriented_jpeg(1, seed=42))
    return root, folder, rot6


def test_ca19_fix_never_rewrites_an_orientation_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, folder, rot6 = _orientation_dataset(tmp_path)
    f_before = loaded(folder / "f.jpg")
    code, out, _ = run_privacy(["--dataset-dir", str(root), "--fix"], capsys)
    assert code == 1, out
    lines = out.splitlines()
    assert "raw/screw/fair/e.jpg: app1, orientation" in lines
    assert "raw/screw/fair/f.jpg: app1" in lines
    assert "fixed raw/screw/fair/f.jpg" in lines
    assert "fixed raw/screw/fair/e.jpg" not in lines
    assert lines[-1] == "checked 2 images, 2 with private data"
    assert (folder / "e.jpg").read_bytes() == rot6
    assert jpeg_private_findings((folder / "f.jpg").read_bytes()) == frozenset()
    assert np.array_equal(loaded(folder / "f.jpg"), f_before)  # f.jpg had Orientation=1

    code, out, _ = run_privacy(["--dataset-dir", str(root)], capsys)
    assert code == 1
    lines = out.splitlines()
    assert [line for line in lines if not line.startswith("checked ")] == [
        "raw/screw/fair/e.jpg: app1, orientation"
    ]
    assert lines[-1] == "checked 2 images, 1 with private data"


# --------------------------------------------------------------------------- CA-19 extras


def xmp_jpeg(body: bytes, seed: int = 25, exif: Image.Exif | None = None) -> bytes:
    """Pillow JPEG with one XMP APP1 right after the SOI (and the given EXIF, if any)."""
    base = clean_jpeg(seed, exif=exif) if exif is not None else clean_jpeg(seed)
    packet = (
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        b'<rdf:Description xmlns:tiff="http://ns.adobe.com/tiff/1.0/" ' + body + b"</rdf:RDF>"
        b"</x:xmpmeta>"
    )
    return base[:2] + segment(0xE1, XMP_PREFIX + packet) + base[2:]


def xmp_attr(value: int) -> bytes:
    return b'tiff:Orientation="%d"/>' % value


def xmp_element(value: int) -> bytes:
    return b"><tiff:Orientation>%d</tiff:Orientation></rdf:Description>" % value


# TIFF field types: (code, payload bytes, count). Payloads longer than 4 bytes go to an offset.
TIFF_ORIENTATIONS: dict[str, tuple[int, bytes, int]] = {
    "byte-6": (1, b"\x06", 1),
    "ascii-6": (2, b"6\x00", 2),
    "short-6": (3, struct.pack(">H", 6), 1),
    "short-6-6": (3, struct.pack(">HH", 6, 6), 2),
    "long-6": (4, struct.pack(">I", 6), 1),
    "rational-6/1": (5, struct.pack(">II", 6, 1), 1),
    "rational-12/2": (5, struct.pack(">II", 12, 2), 1),
    "rational-13/2": (5, struct.pack(">II", 13, 2), 1),
    "sshort-6": (8, struct.pack(">h", 6), 1),
    "sshort-minus-6": (8, struct.pack(">h", -6), 1),
    "slong-8": (9, struct.pack(">i", 8), 1),
    "srational-3/1": (10, struct.pack(">ii", 3, 1), 1),
    "float-6": (11, struct.pack(">f", 6.0), 1),
    "float-6.5": (11, struct.pack(">f", 6.5), 1),
    "double-8": (12, struct.pack(">d", 8.0), 1),
    "short-0": (3, struct.pack(">H", 0), 1),
    "short-9": (3, struct.pack(">H", 9), 1),
    "short-65535": (3, struct.pack(">H", 65535), 1),
}


def tiff_orientation_jpeg(kind: str, seed: int = 25) -> bytes:
    """Hand-built EXIF APP1 whose IFD0 has only tag 274 with the given TIFF type."""
    type_code, payload, count = TIFF_ORIENTATIONS[kind]
    header = b"MM\x00\x2a" + struct.pack(">I", 8)
    ifd_size = 2 + 12 + 4
    if len(payload) <= 4:
        value_field, extra = payload.ljust(4, b"\x00"), b""
    else:
        value_field, extra = struct.pack(">I", 8 + ifd_size), payload
    ifd = struct.pack(">H", 1) + struct.pack(">HHI", 274, type_code, count) + value_field
    tiff = header + ifd + struct.pack(">I", 0) + extra
    base = clean_jpeg(seed)
    return base[:2] + segment(0xE1, b"Exif\x00\x00" + tiff) + base[2:]


def rotates_in_load_image(data: bytes) -> bool:
    """Whether the project loader gives a different image once the APP1 is gone (ADR-004)."""
    return not same_loaded(data, strip_private_segments(data))


@pytest.mark.parametrize("orientation", range(2, 9))
def test_extra_every_exif_rotation_is_refused_and_flagged(
    edge: Edge, tmp_path: Path, capsys: pytest.CaptureFixture[str], orientation: int
) -> None:
    data = oriented_jpeg(orientation, seed=50 + orientation)
    assert rotates_in_load_image(data)  # the 64x48 noise image makes every transpose visible
    assert has_exif_rotation(data) is True
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, data, collect_fields())
    assert r.status_code == 415, r.text
    assert r.json() == ORIENTATION_REFUSED
    _assert_collect_wrote_nothing(edge)

    root = tmp_path / "scan"
    (root / "raw" / "nut" / "good").mkdir(parents=True)
    (root / "manifest.csv").write_text(MANIFEST_HEADER, encoding="utf-8")
    target = root / "raw" / "nut" / "good" / "r.jpg"
    target.write_bytes(data)
    code, out, _ = run_privacy(["--dataset-dir", str(root), "--fix"], capsys)
    assert code == 1
    assert out.splitlines() == [
        "raw/nut/good/r.jpg: app1, orientation",
        "checked 1 images, 1 with private data",
    ]
    assert target.read_bytes() == data


@pytest.mark.parametrize("form", ["attribute", "element"])
@pytest.mark.parametrize("orientation", [2, 6, 8])
def test_extra_orientation_only_in_the_xmp_is_refused_and_flagged(
    edge: Edge, tmp_path: Path, capsys: pytest.CaptureFixture[str], form: str, orientation: int
) -> None:
    body = xmp_attr(orientation) if form == "attribute" else xmp_element(orientation)
    data = xmp_jpeg(body, seed=60 + orientation)
    assert ExifTags.Base.Orientation not in Image.open(io.BytesIO(data)).getexif().get_ifd(
        ExifTags.IFD.Exif
    )
    assert rotates_in_load_image(data)
    assert has_exif_rotation(data) is True
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, data, collect_fields())
    assert r.status_code == 415, r.text
    assert r.json() == ORIENTATION_REFUSED
    _assert_collect_wrote_nothing(edge)

    root = tmp_path / "scan"
    (root / "raw" / "nut" / "good").mkdir(parents=True)
    target = root / "raw" / "nut" / "good" / "x.jpg"
    target.write_bytes(data)
    code, out, _ = run_privacy(["--dataset-dir", str(root), "--fix"], capsys)
    assert code == 1
    assert "raw/nut/good/x.jpg: app1, orientation" in out.splitlines()
    assert target.read_bytes() == data


def _non_rotating_cases() -> dict[str, bytes]:
    exif1 = gps_exif()
    exif1[ExifTags.Base.Orientation] = 1
    return {
        "exif-0": oriented_jpeg(0, seed=71),
        "exif-9": oriented_jpeg(9, seed=72),
        "xmp-1": xmp_jpeg(xmp_attr(1), seed=73),
        "xmp-9": xmp_jpeg(xmp_attr(9), seed=74),
        "exif-1-wins-over-xmp-6": xmp_jpeg(xmp_attr(6), seed=75, exif=exif1),
        "gps-without-orientation": exif_jpeg(seed=76),
    }


@pytest.mark.parametrize("kind", list(_non_rotating_cases()))
def test_extra_orientation_values_that_do_not_rotate_are_stored_with_load_image_parity(
    edge: Edge, kind: str
) -> None:
    data = _non_rotating_cases()[kind]
    assert not rotates_in_load_image(data)
    assert has_exif_rotation(data) is False
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, data, collect_fields())
    assert r.status_code == 200, r.text
    stored = edge.dataset / r.json()["image_path"]
    assert jpeg_private_findings(stored.read_bytes()) == frozenset()
    assert same_loaded(stored, data)


@pytest.mark.filterwarnings("ignore:Metadata Warning:UserWarning")
@pytest.mark.parametrize("kind", list(TIFF_ORIENTATIONS))
def test_extra_odd_tiff_types_follow_the_loader(
    edge: Edge, tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    """Decision 1 of the r2 dev report: a rotation is whatever ``exif_transpose`` applies.

    Invariant checked (§4.8, ADR-004): the collect refuses exactly the JPEGs whose loader result
    would change without the APP1, every accepted JPEG keeps the loader result, and the scan
    flags ``orientation`` on exactly the same files (and ``--fix`` keeps their loader result).
    """
    data = tiff_orientation_jpeg(kind, seed=80)
    rotates = rotates_in_load_image(data)
    assert has_exif_rotation(data) is rotates
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, data, collect_fields())
    if rotates:
        assert r.status_code == 415, r.text
        assert r.json() == ORIENTATION_REFUSED
        _assert_collect_wrote_nothing(edge)
    else:
        assert r.status_code == 200, r.text
        assert same_loaded(edge.dataset / r.json()["image_path"], data)

    root = tmp_path / "scan"
    (root / "raw" / "nut" / "good").mkdir(parents=True)
    target = root / "raw" / "nut" / "good" / "t.jpg"
    target.write_bytes(data)
    code, out, _ = run_privacy(["--dataset-dir", str(root), "--fix"], capsys)
    expected = "raw/nut/good/t.jpg: app1, orientation" if rotates else "raw/nut/good/t.jpg: app1"
    assert expected in out.splitlines()
    if rotates:
        assert code == 1
        assert target.read_bytes() == data
    else:
        assert code == 0
        assert same_loaded(target, data)


def _mpo(orientation: int | None) -> bytes:
    kwargs: dict[str, Any] = {"save_all": True, "append_images": [textured(seed=102)]}
    if orientation is not None:
        exif = gps_exif()
        exif[ExifTags.Base.Orientation] = orientation
        kwargs["exif"] = exif
    return encode(textured(seed=101), "MPO", quality=90, **kwargs)


def _odd_structures() -> dict[str, bytes]:
    base = clean_jpeg(seed=103)
    gps_app1 = [s for m, s in parse_segments(exif_jpeg(seed=103)) if m == 0xE1][0]
    rot6_app1 = [s for m, s in parse_segments(oriented_jpeg(6, seed=103)) if m == 0xE1][0]
    progressive = clean_jpeg(seed=104, progressive=True)
    first_sos = progressive.index(b"\xff\xda")
    second_sos = progressive.index(b"\xff\xda", first_sos + 2)
    return {
        "mpo-two-frames": _mpo(None),
        "mpo-rot1": _mpo(1),
        "mpo-rot6": _mpo(6),
        "two-exif-gps-then-rot6": base[:2] + gps_app1 + rot6_app1 + base[2:],
        "two-exif-rot6-then-gps": base[:2] + rot6_app1 + gps_app1 + base[2:],
        "rot6-exif-between-progressive-scans": (
            progressive[:second_sos] + rot6_app1 + progressive[second_sos:]
        ),
        "xmp-orientation-60": xmp_jpeg(b'tiff:Orientation="60"/>', seed=105),
        "xmp-6-and-exif-without-orientation": xmp_jpeg(xmp_attr(6), seed=106, exif=gps_exif()),
    }


@pytest.mark.parametrize("kind", list(_odd_structures()))
def test_extra_odd_structures_keep_the_load_image_parity(
    edge: Edge, tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    """ADR-004 as a property: whatever Pillow reads as the orientation, the collect refuses
    exactly what the loader would rotate, stores the rest with the same loader result, and the
    scan flags ``orientation`` on the same files."""
    data = _odd_structures()[kind]
    rotates = rotates_in_load_image(data)
    assert has_exif_rotation(data) is rotates
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, data, collect_fields())
    if rotates:
        assert r.status_code == 415, r.text
        assert r.json() == ORIENTATION_REFUSED
        _assert_collect_wrote_nothing(edge)
    else:
        assert r.status_code == 200, r.text
        stored = edge.dataset / r.json()["image_path"]
        assert same_loaded(stored, data)
        assert jpeg_private_findings(stored.read_bytes()) == frozenset()

    root = tmp_path / "scan"
    (root / "raw" / "nut" / "good").mkdir(parents=True)
    target = root / "raw" / "nut" / "good" / "o.jpg"
    target.write_bytes(data)
    code, out, _ = run_privacy(["--dataset-dir", str(root), "--fix"], capsys)
    first = out.splitlines()[0]
    assert ("orientation" in first) is rotates, out
    if rotates:
        assert code == 1
        assert target.read_bytes() == data
    else:
        assert code == 0, out
        assert same_loaded(target, data)


def _accepted_collect_images() -> dict[str, bytes]:
    cmyk = encode(textured(seed=91).convert("CMYK"), "JPEG", quality=90)
    gray = encode(textured(seed=92).convert("L"), "JPEG", quality=90)
    return {
        "clean": clean_jpeg(seed=90),
        "metadata": metadata_jpeg(seed=93)[0],
        "rot1": oriented_jpeg(1, seed=94),
        "progressive-exif": clean_jpeg(seed=95, progressive=True, exif=gps_exif()),
        "restart-markers": clean_jpeg(seed=96, restart_marker_blocks=1, exif=gps_exif()),
        "cmyk-adobe": cmyk,
        "gray": gray,
        "exif-thumbnail-with-eoi": (
            clean_jpeg(seed=97)[:2]
            + segment(0xE1, EMPTY_TIFF + clean_jpeg(seed=98) + b"tail")
            + clean_jpeg(seed=97)[2:]
        ),
    }


@pytest.mark.parametrize("kind", list(_accepted_collect_images()))
def test_extra_every_accepted_jpeg_keeps_the_load_image_result(edge: Edge, kind: str) -> None:
    """ADR-004: ``load_image`` gives the same image for the received bytes and the stored file."""
    data = _accepted_collect_images()[kind]
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, data, collect_fields())
    assert r.status_code == 200, r.text
    stored = edge.dataset / r.json()["image_path"]
    assert same_loaded(stored, data)
    assert np.array_equal(pixels(stored), pixels(data))
    assert jpeg_private_findings(stored.read_bytes()) == frozenset()


@pytest.mark.parametrize("orientation", [1, 6, 8])
def test_extra_png_with_exif_orientation_keeps_the_loaded_size(
    edge: Edge, orientation: int
) -> None:
    """A PNG is re-encoded from the already rotated image (§4.8): same size through the loader,
    no private data and no orientation left in the stored JPEG."""
    exif = gps_exif()
    exif[ExifTags.Base.Orientation] = orientation
    data = encode(textured(seed=99), "PNG", exif=exif)
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, data, collect_fields(), content_type="image/png")
    assert r.status_code == 200, r.text
    stored = edge.dataset / r.json()["image_path"]
    assert load_image(stored).size == load_image(data).size
    assert jpeg_private_findings(stored.read_bytes()) == frozenset()
    assert has_exif_rotation(stored.read_bytes()) is False


def test_extra_has_exif_rotation_reads_only_the_header_and_never_logs_the_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rot6 = oriented_jpeg(6)
    truncated = rot6[: len(rot6) // 2]  # entropy data cut: a full decode would fail
    caplog.set_level(logging.DEBUG, logger="qc_edge")
    assert has_exif_rotation(truncated) is True
    for bad in (b"", SOI, png_bytes(), gif_bytes(), b"\xff\xd8\xff\xe1\x00\x02garbage"):
        with pytest.raises(JpegStructureError) as excinfo:
            has_exif_rotation(bad)
        _assert_no_input_bytes(str(excinfo.value), bad + b"\x00" * 10)
    qc_records = [r for r in caplog.records if r.name.startswith("qc_edge")]
    assert all("Orientation" not in r.getMessage() for r in qc_records)


def test_extra_rotated_collect_releases_the_slot_and_logs_no_gps(
    edge: Edge, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="qc_edge")
    app = edge.app(max_concurrent_decodes=1, decode_wait_s=1)
    with TestClient(app) as client:
        codes = [
            post(client, edge.token, oriented_jpeg(6, seed=s), collect_fields()).status_code
            for s in range(3)
        ]
        ok = post(client, edge.token, oriented_jpeg(1), collect_fields())
    assert codes == [415, 415, 415]
    assert ok.status_code == 200, ok.text
    assert len(edge.rows()) == 1
    qc_text = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("qc_edge"))
    for latitude in LATITUDE_TEXTS:
        assert latitude not in qc_text


def test_extra_rotation_check_runs_inside_the_slot_off_the_event_loop(
    edge: Edge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-08 with a rotated JPEG: the image is still decoded once, off the event loop."""
    seen: list[bool] = []
    original = qc_edge.limits.load_capture_image

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(loop_running())
        return original(*args, **kwargs)

    monkeypatch.setattr(qc_edge.limits, "load_capture_image", spy)
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, oriented_jpeg(6), collect_fields())
    assert r.status_code == 415
    assert seen == [False]


# =========================================================================== extras


def test_extra_refusal_log_is_a_warning_with_only_the_reason(
    edge: Edge, lan_spy: list[int], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = new_marker()
    app = edge.app()
    assert console(app, f"{marker}.example:8000").status_code == 403
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r.getMessage() for r in warnings] == [REFUSAL_LOG]
    assert marker not in log_text(caplog)


@pytest.mark.parametrize(
    "host",
    [
        " 127.0.0.1:8000",
        "127.0.0.1:8000 ",
        "127.0.0.1:08000",
        "127.0.0.1:8000/",
        "127.0.0.1:8000.",
        "localhost:8000:8000",
        "user@127.0.0.1:8000",
        "[::1]",
        "::1:8000",
        "[::ffff:127.0.0.1]:8000",
        "127.1:8000",
        "2130706433:8000",
        "0.0.0.0:8000",
        "LOCALHOST.:8000",
        "lоcalhost:8000",  # Cyrillic o
        "localhost\x00:8000",
    ],
)
def test_extra_host_variants_are_refused(host: str) -> None:
    assert is_allowed_console_host(host, PORT) is False


def test_extra_console_still_refuses_remote_and_proxied_with_a_loopback_host(
    edge: Edge, lan_spy: list[int]
) -> None:
    app = edge.app()
    assert console(app, "127.0.0.1:8000", client=("192.168.0.50", 50000)).status_code == 403
    for header in ("X-Forwarded-For", "Forwarded", "CF-Connecting-IP"):
        raw = raw_asgi(
            app,
            "GET",
            "/",
            [(b"host", b"127.0.0.1:8000"), (header.lower().encode(), b"for=1.2.3.4")],
        )
        assert raw.status == 403, header
        assert edge.token not in raw.text
    assert lan_spy == []


def test_extra_console_refusal_keeps_the_page_headers(edge: Edge, lan_spy: list[int]) -> None:
    app = edge.app()
    allowed = console(app, "127.0.0.1:8000")
    refused = console(app, "attacker.example:8000")
    lan_refused = console(app, "127.0.0.1:8000", client=("192.168.0.50", 50000))
    assert refused.text == lan_refused.text  # same FORBIDDEN_HTML as the SPEC-007 refusal
    for name in ("content-security-policy", "x-frame-options", "cache-control", "referrer-policy"):
        if name in allowed.headers:
            assert refused.headers.get(name) == allowed.headers[name], name


@pytest.mark.parametrize(
    "value", [" 127.0.0.1", "127.0.0.01", "::ffff:127.0.0.1", "0", "127.0.0.1\n", "1.2.3.4/32"]
)
def test_extra_more_edge_host_values_exit_2(
    edge: Edge, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("EDGE_HOST", value)
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    assert call_main(qc_edge.cli.main, []) == 2
    assert spy.calls == []


def test_extra_empty_edge_host_is_the_default(edge: Edge, monkeypatch: pytest.MonkeyPatch) -> None:
    """``env_ignore_empty`` (SPEC-007): an empty ``EDGE_HOST=`` means "unset", so 0.0.0.0."""
    monkeypatch.setenv("EDGE_HOST", "")
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    assert call_main(qc_edge.cli.main, []) == 0
    assert spy.calls[0][1]["host"] == "0.0.0.0"


@pytest.mark.parametrize(
    "argv",
    [
        ["--stub-model={m}"],
        ["--Token={m}"],
        ["-{M}"],
        ["--{M}"],
        ["--", "{m}"],
        ["--stub-model", "{m}"],
        ["--tökén={m}"],
        ["--" + "a" * 40 + "={m}"],
    ],
    ids=[
        "flag-with-value",
        "uppercase",
        "short",
        "long-marker",
        "double-dash",
        "extra-positional",
        "unicode-name",
        "long-name",
    ],
)
def test_extra_cli_never_echoes_odd_arguments(
    edge: Edge,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    caplog.set_level(logging.DEBUG)
    marker = new_marker()
    upper = new_marker("ACC").upper()  # outside --?[a-z][a-z0-9-]{0,30}: only counted
    args = [a.replace("{m}", marker).replace("{M}", upper) for a in argv]
    assert call_main(qc_edge.cli.main, args) == 2
    out = capsys.readouterr()
    text = "\n".join([log_text(caplog), out.out, out.err])
    assert marker not in text
    assert upper not in text
    assert "a" * 31 not in text
    assert spy.calls == []


def test_extra_cli_list_format_and_help(
    edge: Edge,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    caplog.set_level(logging.DEBUG)
    marker = new_marker()
    assert call_main(qc_edge.cli.main, ["--stub-modle", f"--token={marker}", marker]) == 2
    text = log_text(caplog)
    assert "unknown command-line argument(s):" in text
    assert "--stub-modle" in text and "--token" in text
    assert "1 other" in text
    assert marker not in text
    capsys.readouterr()
    assert call_main(qc_edge.cli.main, ["--help"]) == 0
    assert "--stub-model" in capsys.readouterr().out
    assert call_main(qc_edge.cli.main, ["-h"]) == 0
    # documented by §4.5: a lowercase option-shaped word up to 31 characters is logged as a name
    caplog.clear()
    shaped = "--" + new_marker()[:29]
    assert call_main(qc_edge.cli.main, [shaped]) == 2
    assert shaped in log_text(caplog)
    assert spy.calls == []


def test_extra_cli_without_argv_reads_sys_argv(edge: Edge, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    monkeypatch.setattr(sys, "argv", ["qc-edge", "--stub-modle"])
    with pytest.raises(SystemExit) as excinfo:
        qc_edge.cli.main()
    assert excinfo.value.code == 2
    assert spy.calls == []


# --------------------------------------------------------------------------- JPEG walk extras


def _with_after_soi(base: bytes, *segments: bytes) -> bytes:
    return base[:2] + b"".join(segments) + base[2:]


def test_extra_pillow_variants_are_unchanged_byte_for_byte() -> None:
    icc = b"\x00" * 128  # opaque ICC-like payload; Pillow only copies it into APP2
    cmyk = encode(Image.new("CMYK", (40, 30), (10, 200, 30, 5)), "JPEG", quality=85)
    variants = {
        "baseline": clean_jpeg(),
        "progressive": clean_jpeg(progressive=True),
        "optimized": clean_jpeg(optimize=True),
        "restart": encode(textured(), "JPEG", quality=90, restart_marker_blocks=1),
        "gray": encode(textured().convert("L"), "JPEG", quality=90),
        "subsampling-0": clean_jpeg(subsampling=0),
        "icc": clean_jpeg(icc_profile=icc),
        "cmyk-adobe": cmyk,
    }
    for name, data in variants.items():
        assert jpeg_private_findings(data) == frozenset(), name
        assert strip_private_segments(data) == data, name
    assert b"\xff\xd0" in variants["restart"]
    assert b"\xff\xee" in cmyk[:200]  # APP14 Adobe kept


def test_extra_private_segments_anywhere_before_the_scan() -> None:
    base = clean_jpeg()
    marker = new_marker().encode()
    com = segment(0xFE, marker)
    app13 = segment(0xED, PHOTOSHOP_PREFIX + marker)
    empty_app1 = b"\xff\xe1\x00\x02"
    app2 = segment(0xE2, b"ICC_PROFILE\x00" + b"\x01\x01" + b"\x00" * 16)
    app14 = segment(0xEE, b"Adobe\x00\x64\x00\x00\x00\x00\x01")
    sos = base.index(b"\xff\xda")
    data = base[:sos] + com + app2 + empty_app1 + app13 + app14 + base[sos:]
    assert jpeg_private_findings(data) == frozenset({"app1", "app13", "com"})
    out = strip_private_segments(data)
    assert marker not in out
    assert app2 in out and app14 in out
    assert out == base[:sos] + app2 + app14 + base[sos:]
    assert np.array_equal(pixels(out), pixels(base))


def test_extra_fill_bytes_and_com_between_progressive_scans() -> None:
    base = clean_jpeg(progressive=True)
    marker = new_marker().encode()
    segs = parse_segments(base)
    second_sos = [i for i, (m, _) in enumerate(segs) if m == 0xDA][1]
    rebuilt = b""
    for i, (_, seg) in enumerate(segs):
        if i == second_sos:
            rebuilt += segment(0xFE, marker) + b"\xff\xff\xff"  # COM between scans, then fill
        rebuilt += seg
    assert jpeg_private_findings(rebuilt) == frozenset({"com"})
    out = strip_private_segments(rebuilt)
    assert marker not in out
    assert b"\xff\xff\xff\xff\xda" in out  # fill bytes copied as they are
    assert np.array_equal(pixels(out), pixels(base))
    assert image_segments(out) == image_segments(base)


def test_extra_trailer_that_is_another_jpeg_is_removed() -> None:
    first = clean_jpeg(seed=1)
    second = exif_jpeg(seed=2)
    data = first + second
    assert jpeg_private_findings(data) == frozenset({"trailer"})
    assert strip_private_segments(data) == first


@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "soi-only",
        "length-beyond-end",
        "app1-length-0",
        "sos-without-eoi",
        "eoi-cut",
        "ff-at-end",
    ],
)
def test_extra_more_structural_errors(kind: str) -> None:
    valid = clean_jpeg()
    data = {
        "empty": b"",
        "soi-only": SOI,
        "length-beyond-end": SOI + b"\xff\xe1\xff\xff" + b"Exif\x00\x00",
        "app1-length-0": SOI + b"\xff\xe1\x00\x00" + valid[2:],
        "sos-without-eoi": valid[:-2],
        "eoi-cut": valid[:-1],
        "ff-at-end": SOI + b"\xff",
    }[kind]
    for func in (strip_private_segments, jpeg_private_findings):
        with pytest.raises(JpegStructureError):
            func(data)


def test_extra_findings_never_contain_content() -> None:
    data, com_marker = metadata_jpeg()
    findings = jpeg_private_findings(data)
    assert all(f in {"app1", "app13", "com", "trailer"} for f in findings)
    assert com_marker.decode() not in repr(findings)


def test_extra_strip_is_idempotent_and_fast_on_the_max_route_size() -> None:
    data, _ = metadata_jpeg()
    once = strip_private_segments(data)
    assert strip_private_segments(once) == once
    big = clean_jpeg() + b"\x00" * (3 * 1024 * 1024 - len(clean_jpeg()))
    t0 = time.monotonic()
    assert jpeg_private_findings(big) == frozenset({"trailer"})
    assert time.monotonic() - t0 < 2.0


# --------------------------------------------------------------------------- collect-mode extras


def test_extra_collect_eoi_inside_app1_keeps_the_pixels(edge: Edge) -> None:
    app1 = segment(0xE1, EMPTY_TIFF + clean_jpeg(seed=8) + b"tail")
    sent = _with_after_soi(clean_jpeg(seed=9), app1)
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, sent, collect_fields())
    assert r.status_code == 200, r.text
    stored = edge.dataset / r.json()["image_path"]
    assert stored.read_bytes() == clean_jpeg(seed=9)
    assert np.array_equal(pixels(stored), pixels(sent))


def test_extra_collect_png_is_reencoded_without_metadata(edge: Edge) -> None:
    exif = gps_exif()
    png = encode(textured(seed=6), "PNG", exif=exif.tobytes())
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, png, collect_fields(), content_type="image/png")
    assert r.status_code == 200, r.text
    stored = (edge.dataset / r.json()["image_path"]).read_bytes()
    assert jpeg_private_findings(stored) == frozenset()
    assert b"Exif\x00\x00" not in stored


def test_extra_collect_with_garbage_between_segments(edge: Edge) -> None:
    """Pillow tolerates stray bytes between segments; the walk must not store private data."""
    base = exif_jpeg(seed=10)
    app0_end = 2 + 2 + int.from_bytes(base[4:6], "big")
    sent = base[:app0_end] + b"\x00\x00" + base[app0_end:]
    app = edge.app(max_concurrent_decodes=1, decode_wait_s=1)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = post(client, edge.token, sent, collect_fields())
        after = post(client, edge.token, clean_jpeg(), inspect_fields())
    assert after.status_code == 200
    if r.status_code == 200:
        stored = (edge.dataset / r.json()["image_path"]).read_bytes()
        assert b"Exif\x00\x00" not in stored
    else:
        assert r.status_code == 415, r.text
        assert edge.images() == []


def test_extra_truncated_collect_jpeg_is_refused_and_writes_nothing(edge: Edge) -> None:
    data, _ = metadata_jpeg()
    cut = data[: data.index(EOI + b"\x00\x00\x00\x18ftyp")]  # no EOI at all
    app = edge.app()
    with TestClient(app, raise_server_exceptions=False) as client:
        r = post(client, edge.token, cut, collect_fields())
    assert r.status_code == 415, r.text
    assert edge.images() == []


@pytest.mark.parametrize(
    "char",
    ["\u061c", "\u200e", "\ufeff", "\u2069", "\u202a", "\r", "\x85", "\U000e0001"],
    ids=lambda c: f"U+{ord(c):04X}",
)
def test_extra_more_forbidden_note_characters(edge: Edge, char: str) -> None:
    assert unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"}
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, clean_jpeg(), collect_fields(notes=f"ok{char}ok"))
    assert r.status_code == 422, r.text
    assert edge.images() == []


@pytest.mark.parametrize("notes", ["peça 🔩 com rosca", "a\u00a0b", "日本語", "ação/ok"])
def test_extra_allowed_unicode_notes(edge: Edge, notes: str) -> None:
    app = edge.app()
    with TestClient(app) as client:
        r = post(client, edge.token, clean_jpeg(), collect_fields(notes=notes))
    assert r.status_code == 200, r.text
    assert edge.rows()[0]["notes"] == notes


def test_extra_user_agent_with_every_category_and_a_long_tail(edge: Edge) -> None:
    """Latin-1 bytes of the raw header: C0, DEL, C1 (``Cc``) and the soft hyphen (``Cf``)."""
    app = edge.app()
    ua = b"A\x00B\x1bC\x7fD\x85E\xadF\xa0G" + b"q" * 80
    raw = raw_collect(app, edge.token, ua, clean_jpeg(seed=2), angle="3")
    assert raw.status == 200, raw.text
    device = edge.rows()[-1]["capture_device"]
    assert device == "A B C D E F\u00a0G" + "q" * 47  # U+00A0 is Zs: kept
    assert len(device) == 60
    assert len(edge.manifest.read_text(encoding="utf-8").splitlines()) == 2


def test_extra_collect_permissions_with_umask_0o277(
    edge: Edge, umask_guard: Callable[[int], None]
) -> None:
    app = edge.app()
    data, _ = metadata_jpeg()
    umask_guard(0o277)
    try:
        with TestClient(app) as client:
            r = post(client, edge.token, data, collect_fields())
    finally:
        umask_guard(0o022)
    assert r.status_code == 200, r.text
    stored = edge.dataset / r.json()["image_path"]
    assert _mode(stored) == 0o600
    assert _mode(edge.dataset) == 0o700
    assert _mode(stored.parent) == 0o700
    assert _mode(edge.manifest) == 0o600


# --------------------------------------------------------------------------- privacy CLI extras


def test_extra_privacy_fix_waits_for_the_collect_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ds = make_dataset(tmp_path)
    lock_path = ds.root / "manifest.csv.lock"
    before = (ds.folder / "b.jpg").read_bytes()
    codes: list[int] = []
    with lock_path.open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        worker = threading.Thread(
            target=lambda: codes.append(
                call_main(qc_edge.privacy.main, ["--dataset-dir", str(ds.root), "--fix"])
            ),
            daemon=True,
        )
        worker.start()
        time.sleep(0.6)
        assert worker.is_alive(), "--fix did not wait for the lock"
        assert (ds.folder / "b.jpg").read_bytes() == before
        fcntl.flock(fh, fcntl.LOCK_UN)
    worker.join(timeout=15)
    assert codes == [0]
    assert jpeg_private_findings((ds.folder / "b.jpg").read_bytes()) == frozenset()


def test_extra_privacy_fix_creates_the_lock_with_0600(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], umask_guard: Callable[[int], None]
) -> None:
    ds = make_dataset(tmp_path)
    umask_guard(0o000)
    try:
        code, _, _ = run_privacy(["--dataset-dir", str(ds.root), "--fix"], capsys)
    finally:
        umask_guard(0o022)
    assert code == 0
    assert _mode(ds.root / "manifest.csv.lock") == 0o600
    assert _mode(ds.folder / "b.jpg") == 0o600


def test_extra_privacy_fix_syncs_the_temp_file_then_the_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ds = make_dataset(tmp_path)
    real_fsync, real_replace = os.fsync, os.replace
    events: list[tuple[str, str]] = []

    def fsync_spy(fd: int) -> None:
        events.append(("fsync", _fd_path(fd)))
        return real_fsync(fd)

    def replace_spy(src: Any, dst: Any, **kwargs: Any) -> None:
        events.append(("replace", str(dst)))
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "fsync", fsync_spy)
    monkeypatch.setattr(os, "replace", replace_spy)
    code = call_main(qc_edge.privacy.main, ["--dataset-dir", str(ds.root), "--fix"])
    monkeypatch.setattr(os, "fsync", real_fsync)
    monkeypatch.setattr(os, "replace", real_replace)
    assert code == 0
    folder = str(ds.folder)
    for name in ("b.jpg", "c.jpg"):
        target = f"{folder}/{name}"
        idx = events.index(("replace", target))
        before, after = events[:idx], events[idx + 1 :]
        assert any(
            kind == "fsync" and p.startswith(folder + "/") and p != target for kind, p in before
        ), events
        assert ("fsync", folder) in after, events


def test_extra_privacy_invalid_file_and_odd_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ds = make_dataset(tmp_path)
    (ds.folder / "e.jpg").write_bytes(b"not a jpeg at all")
    (ds.folder / "upper.JPG").write_bytes(exif_jpeg(seed=20))
    (ds.folder / "dir.jpg").mkdir()
    (ds.folder / "notes.txt").write_bytes(b"x")
    code, out, _ = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    assert code == 1
    assert "raw/screw/fair/e.jpg: invalid" in out.splitlines()
    assert out.splitlines()[-1] == "checked 4 images, 3 with private data"
    code, out, _ = run_privacy(["--dataset-dir", str(ds.root), "--fix"], capsys)
    assert code == 1  # an invalid file is left for the pair to delete
    assert "fixed raw/screw/fair/e.jpg" not in out
    assert (ds.folder / "e.jpg").read_bytes() == b"not a jpeg at all"


@pytest.mark.parametrize("kind", ["file", "no-raw", "empty-raw"])
def test_extra_privacy_dataset_dir_shapes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    root = tmp_path / "D"
    if kind == "file":
        root.write_bytes(b"x")
        assert run_privacy(["--dataset-dir", str(root)], capsys)[0] == 2
        return
    root.mkdir()
    if kind == "empty-raw":
        (root / "raw").mkdir()
    code, out, _ = run_privacy(["--dataset-dir", str(root)], capsys)
    assert code == 0
    assert out.splitlines() == ["checked 0 images, 0 with private data"]


def test_extra_privacy_paths_with_control_characters_keep_code_and_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A hand-copied file name with a newline: the exit code and the last line stay right."""
    ds = make_dataset(tmp_path)
    (ds.folder / "x\nchecked 0 images, 0 with private data\n.jpg").write_bytes(exif_jpeg(seed=21))
    code, out, _ = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    assert code == 1
    assert out.splitlines()[-1] == "checked 4 images, 3 with private data"
    # the name itself is printed raw (observation O-01 of the r1 test report); not asserted here


def test_extra_privacy_module_runs_with_python_m(tmp_path: Path) -> None:
    ds = make_dataset(tmp_path)
    env = {k: v for k, v in os.environ.items() if k not in EDGE_ENV_VARS}
    proc = subprocess.run(
        [sys.executable, "-m", "qc_edge.privacy", "--dataset-dir", str(ds.root)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1, proc.stderr
    assert proc.stdout.splitlines()[-1] == "checked 3 images, 2 with private data"
    assert str(ds.root) not in proc.stdout + proc.stderr


# --------------------------------------------------------------------------- R-02


def test_extra_r02_nothing_new_opens_a_network_connection(
    edge: Edge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    attempts: list[Any] = []
    real_connect = socket.socket.connect

    def spy(self: socket.socket, address: Any) -> Any:
        attempts.append(address)
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", spy)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: attempts.append(a))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: attempts.append(a) or [])
    data, _ = metadata_jpeg()
    app = edge.app()
    with TestClient(app) as client:
        assert post(client, edge.token, data, collect_fields()).status_code == 200
        assert post(client, edge.token, data, inspect_fields()).status_code == 200
    ds = make_dataset(tmp_path, "R02")
    assert call_main(qc_edge.privacy.main, ["--dataset-dir", str(ds.root), "--fix"]) == 0
    assert attempts == []


def test_extra_r02_no_route_serves_images_and_privacy_has_no_http_client(edge: Edge) -> None:
    app = edge.app()
    paths = sorted({getattr(r, "path", "") for r in app.routes})
    assert all(not p.startswith(("/captures", "/dataset", "/raw", "/data")) for p in paths), paths
    tree = ast.parse((EDGE_ROOT / "src" / "qc_edge" / "privacy.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"httpx", "requests", "urllib", "http", "socket", "aiohttp"}, imported
