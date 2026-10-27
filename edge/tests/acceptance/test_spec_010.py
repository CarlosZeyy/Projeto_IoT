"""Acceptance tests for SPEC-010 (qc-edge: dataset collect mode).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers the automatable CAs (CA-01 to CA-16 and CA-18); CA-17 is manual (a real
phone) and is recorded in ``reviews/SPEC-010/r1-test-report.md``. Tests named ``test_extra_*``
are exploratory edge cases around the SPEC that no CA spells out.

Rules followed (``reviews/checklist.md`` and ``docs/architecture.md`` §10): the session token is
built at run time (no credential literal in a URL or header), images are generated in memory
(no binary in Git), ``DATASET_DIR`` always lives under ``tmp_path``, no test runs the test
suite in a subprocess, and the only boundaries mocked are the clock, the network (to prove that
nothing leaves the LAN) and the inferencer/sink doubles that the SPEC's own interfaces accept.
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
import re
import secrets
import socket
import stat
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageFile

from qc_contracts import GRADE_LABELS_PT, Grade, InspectionCreate, ObjectType
from qc_edge.app import create_app
from qc_edge.collect import compute_coverage
from qc_edge.config import EdgeSettings
from qc_edge.inference import InferenceResult, ModelInfo, StubInferencer
from qc_edge.sink import InMemorySink, SinkStats

pytestmark = pytest.mark.acceptance

EDGE_ROOT = Path(__file__).resolve().parents[2]  # edge/
ROOT = EDGE_ROOT.parent

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

SESSION_HEADER = "X-Session-Token"
HEADER = [
    "image_path",
    "item_id",
    "object_type",
    "grade",
    "labeler",
    "angle",
    "captured_at",
    "capture_device",
    "notes",
]
HEADER_LINE = ",".join(HEADER) + "\n"
CA01_INSTANT = datetime(2026, 10, 22, 14, 15, 3, tzinfo=UTC)
CA01_STAMP = "20261022T141503Z"
GRADES = ["perfect", "good", "fair", "poor", "unusable"]
# SPEC-016 section 4.4: the hand tools of the coverage table.
TOOLS_016 = ["pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver"]
POWER_021 = ["angle_grinder", "saw", "drill", "cordless_screwdriver"]
HEADER_MISMATCH = {"detail": "manifest header mismatch"}
TYPE_CONFLICT = {"detail": "item_id already registered with another object_type"}
CAPTURE_EXISTS = {"detail": "capture already exists, try again"}


def new_token() -> str:
    """40 URL-safe characters, generated at run time (never a literal)."""
    return secrets.token_urlsafe(30)


# --------------------------------------------------------------------------- images


def encode(img: Image.Image, fmt: str, **kwargs: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def solid_jpeg(width: int = 64, height: int = 48, color: str = "steelblue") -> bytes:
    return encode(Image.new("RGB", (width, height), color), "JPEG", quality=90)


def solid_png(width: int = 64, height: int = 48) -> bytes:
    return encode(Image.new("RGB", (width, height), "darkorange"), "PNG")


def padded_jpeg(total: int) -> bytes:
    """Valid small JPEG followed by ``00`` bytes after EOI up to exactly ``total`` bytes."""
    jpeg = solid_jpeg()
    return jpeg + b"\x00" * (total - len(jpeg))


# --------------------------------------------------------------------------- doubles


def stub_result() -> InferenceResult:
    return InferenceResult(
        object_type=ObjectType.SCREW,
        grade=Grade.GOOD,
        grade_score=1.0,
        type_confidence=0.9,
        grade_confidence=0.8,
        needs_review=False,
        latency_ms=5,
    )


class RecordingSink:
    """InspectionSink double that records every ``put`` (SPEC-007 Protocol)."""

    def __init__(self) -> None:
        self.items: list[InspectionCreate] = []
        self.calls = 0
        self.stats_calls = 0

    def put(self, inspection: InspectionCreate) -> None:
        self.calls += 1
        self.items.append(inspection)

    def stats(self) -> SinkStats:
        self.stats_calls += 1
        return SinkStats(pending=0, dead=0, last_success_at=None, connectivity="disabled")


class BlockingInferencer:
    """Holds a decode slot (inspect mode) until ``release`` is set."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo("acc-model-v1", "c" * 64)

    def infer(self, image: Image.Image) -> InferenceResult:
        self.started.set()
        assert self.release.wait(timeout=15), "test event never released"
        return stub_result()


@dataclass
class Clock:
    """Injected clock (boundary)."""

    value: datetime = CA01_INSTANT

    def __call__(self) -> datetime:
        return self.value


# --------------------------------------------------------------------------- fixtures


@dataclass
class Edge:
    tmp: Path
    data_dir: Path
    dataset: Path
    token: str
    clock: Clock = field(default_factory=Clock)

    def app(self, inferencer: Any = None, sink: Any = None, **kwargs: Any) -> Any:
        snk = sink if sink is not None else InMemorySink()
        kwargs.setdefault("clock", self.clock)
        return create_app(EdgeSettings(), inferencer, snk, **kwargs)

    @property
    def manifest(self) -> Path:
        return self.dataset / "manifest.csv"

    def rows(self) -> list[dict[str, str]]:
        with self.manifest.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == HEADER
            return list(reader)

    def images(self) -> list[Path]:
        raw = self.dataset / "raw"
        return sorted(p for p in raw.rglob("*") if p.is_file()) if raw.exists() else []

    def tree(self) -> set[str]:
        """Every path (files and directories) under ``tmp_path``."""
        return {str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*")}


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
    monkeypatch.setenv("EDGE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setenv("DATASET_DIR", str(dataset))
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    return Edge(tmp=tmp_path, data_dir=data_dir, dataset=dataset, token=token)


@pytest.fixture
def client(edge: Edge) -> Iterator[TestClient]:
    with TestClient(edge.app(), raise_server_exceptions=False) as c:
        yield c


def fields(**overrides: str | None) -> dict[str, Any]:
    """CA-01 form fields; an override of ``None`` removes the field."""
    base: dict[str, Any] = {
        "mode": "collect",
        "item_id": "S-012",
        "object_type": "screw",
        "grade": "fair",
        "labeler": "a",
        "angle": "2",
        "notes": "dúvida fair/poor",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def post_collect(
    client: TestClient,
    token: str | None,
    image: bytes | None = None,
    data: dict[str, Any] | None = None,
    *,
    user_agent: str | None = "acceptance-phone",
    filename: str = "foto.jpg",
    content_type: str = "image/jpeg",
) -> httpx.Response:
    headers: dict[str, str] = {}
    if token is not None:
        headers[SESSION_HEADER] = token
    if user_agent is not None:
        headers["User-Agent"] = user_agent
    body = solid_jpeg() if image is None else image
    return client.post(
        "/api/capture",
        headers=headers,
        data=fields() if data is None else data,
        files={"image": (filename, body, content_type)},
    )


def console_get(app: Any, path: str = "/") -> httpx.Response:
    """Console request from loopback, with a loopback ``Host`` (SPEC-025 ready)."""
    port = EdgeSettings().EDGE_PORT

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(transport=transport, base_url=base) as c:
            return await c.get(path)

    return asyncio.run(go())


def write_manifest(path: Path, rows: list[list[str]], header: str = HEADER_LINE) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    content = (header + buf.getvalue()).encode("utf-8")
    path.write_bytes(content)
    return content


def manifest_row(
    item_id: str, object_type: str, grade: str, angle: int = 0, second: int = 0
) -> list[str]:
    stamp = f"20261020T1000{second % 60:02d}Z"
    folder = grade or "_"
    return [
        f"raw/{object_type}/{folder}/{item_id}__{angle}__{stamp}.jpg",
        item_id,
        object_type,
        grade,
        "a",
        str(angle),
        f"2026-10-20T10:00:{second % 60:02d}Z",
        "seed",
        "",
    ]


# =========================================================================== CA-01


def test_ca01_valid_jpeg_creates_image_and_manifest_line(edge: Edge, client: TestClient) -> None:
    user_agent = "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 Chrome/1"
    user_agent = (user_agent + "x" * 80)[:80]
    assert len(user_agent) == 80
    image = solid_jpeg()

    r = post_collect(client, edge.token, image, user_agent=user_agent)

    assert r.status_code == 200, r.text
    expected_path = f"raw/screw/fair/S-012__2__{CA01_STAMP}.jpg"
    assert r.json() == {
        "mode": "collect",
        "image_path": expected_path,
        "item_id": "S-012",
        "angle": 2,
        "item_images": 1,
    }
    stored = edge.dataset / expected_path
    assert stored.is_file()
    assert stored.read_bytes() == image  # JPEG: the bytes as received
    assert edge.images() == [stored]

    raw = edge.manifest.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # UTF-8 without BOM
    assert b"\r" not in raw
    assert raw.decode("utf-8").splitlines()[0] + "\n" == HEADER_LINE
    rows = edge.rows()
    assert rows == [
        {
            "image_path": expected_path,
            "item_id": "S-012",
            "object_type": "screw",
            "grade": "fair",
            "labeler": "a",
            "angle": "2",
            "captured_at": "2026-10-22T14:15:03Z",
            "capture_device": user_agent[:60],
            "notes": "dúvida fair/poor",
        }
    ]
    assert len(rows[0]["capture_device"]) == 60


# =========================================================================== CA-02


@pytest.mark.parametrize("grade", ["", None], ids=["grade-empty", "grade-absent"])
def test_ca02_other_goes_to_underscore_with_empty_grade(
    edge: Edge, client: TestClient, grade: str | None
) -> None:
    data = fields(item_id="O-004", object_type="other", grade=grade, angle="0")
    r = post_collect(client, edge.token, data=data)

    assert r.status_code == 200, r.text
    expected_path = f"raw/other/_/O-004__0__{CA01_STAMP}.jpg"
    assert r.json()["image_path"] == expected_path
    assert (edge.dataset / expected_path).is_file()
    rows = edge.rows()
    assert len(rows) == 1
    assert rows[0]["grade"] == ""
    assert rows[0]["object_type"] == "other"
    assert rows[0]["item_id"] == "O-004"


# =========================================================================== CA-03


@pytest.mark.parametrize(
    "overrides",
    [
        {"item_id": "O-004", "object_type": "other", "grade": "good"},
        {"grade": None},
        {"grade": ""},
        {"grade": "excellent"},
    ],
    ids=["other-with-good", "screw-without-grade", "screw-empty-grade", "grade-excellent"],
)
def test_ca03_grade_rules_are_422_and_nothing_written(
    edge: Edge, client: TestClient, overrides: dict[str, str | None]
) -> None:
    before = edge.tree()
    r = post_collect(client, edge.token, data=fields(**overrides))
    assert r.status_code == 422, r.text
    assert "detail" in r.json()
    assert edge.tree() == before
    assert not edge.dataset.exists()


# =========================================================================== CA-04


@pytest.mark.parametrize(
    "overrides",
    [
        {"item_id": "N-001", "object_type": "screw"},
        {"item_id": "T-001", "object_type": "screw"},
        {"item_id": "T-001", "object_type": "nut", "grade": "good"},
        {"item_id": "T-001", "object_type": "other", "grade": ""},
        {"item_id": "S-001", "object_type": "unknown"},
        {"item_id": "S-001", "object_type": "nut"},
        {"item_id": "O-001", "object_type": "screw"},
        {"item_id": "S-001", "object_type": "other", "grade": ""},
    ],
    ids=[
        "N-as-screw",
        "T-as-screw",
        "T-as-nut",
        "T-as-other",
        "unknown-type",
        "S-as-nut",
        "O-as-screw",
        "S-as-other",
    ],
)
def test_ca04_prefix_and_type_rules_are_422(
    edge: Edge, client: TestClient, overrides: dict[str, str]
) -> None:
    before = edge.tree()
    r = post_collect(client, edge.token, data=fields(**overrides))
    assert r.status_code == 422, r.text
    assert edge.tree() == before


# =========================================================================== CA-05

CA05_CASES = [
    ("item_id", "S-12"),
    ("item_id", "s-012"),
    ("item_id", "S-0123"),
    ("item_id", "../S-001"),
    ("angle", "5"),
    ("angle", "-1"),
    ("angle", "x"),
    ("labeler", "c"),
    ("notes", "n" * 201),
    ("notes", "linha 1\nlinha 2"),
]
CA05_NEWLINE_CASES = [
    ("item_id", "S-012\n"),
    ("angle", "2\n"),
    ("object_type", "screw\n"),
]


@pytest.mark.parametrize(("name", "value"), CA05_CASES, ids=[repr(v) for _, v in CA05_CASES])
def test_ca05_invalid_fields_are_422_and_nothing_outside_dataset_dir(
    edge: Edge, client: TestClient, name: str, value: str
) -> None:
    edge.dataset.mkdir()
    before = edge.tree()
    r = post_collect(client, edge.token, data=fields(**{name: value}))
    assert r.status_code == 422, r.text
    assert edge.tree() == before  # nothing anywhere under tmp_path, in or out of DATASET_DIR
    assert list(edge.dataset.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "value"), CA05_NEWLINE_CASES, ids=[repr(v) for _, v in CA05_NEWLINE_CASES]
)
def test_ca05_trailing_newline_is_422_and_dataset_dir_stays_empty(
    edge: Edge, client: TestClient, name: str, value: str
) -> None:
    edge.dataset.mkdir()
    before = edge.tree()
    r = post_collect(client, edge.token, data=fields(**{name: value}))
    assert r.status_code == 422, r.text
    assert list(edge.dataset.iterdir()) == []  # no image, no manifest.csv
    assert edge.tree() == before


# =========================================================================== CA-06


def test_ca06_item_registered_with_another_type_is_409(edge: Edge, client: TestClient) -> None:
    original = write_manifest(edge.manifest, [manifest_row("O-007", "screw", "perfect")])
    data = fields(item_id="O-007", object_type="other", grade="", angle="1")

    r = post_collect(client, edge.token, data=data)

    assert r.status_code == 409, r.text
    assert r.json() == TYPE_CONFLICT
    assert edge.images() == []
    assert edge.manifest.read_bytes() == original


# =========================================================================== CA-07


def test_ca07_same_item_new_grade_is_allowed(edge: Edge, client: TestClient) -> None:
    first = post_collect(client, edge.token, data=fields(grade="fair"))
    assert first.status_code == 200, first.text
    assert first.json()["item_images"] == 1

    second = post_collect(client, edge.token, data=fields(grade="poor"))

    assert second.status_code == 200, second.text
    assert second.json()["item_images"] == 2
    assert second.json()["image_path"] == f"raw/screw/poor/S-012__2__{CA01_STAMP}.jpg"
    assert [row["grade"] for row in edge.rows()] == ["fair", "poor"]
    assert len(edge.images()) == 2


# =========================================================================== CA-08


def test_ca08_identical_requests_in_the_same_second(edge: Edge, client: TestClient) -> None:
    first = post_collect(client, edge.token)
    second = post_collect(client, edge.token, solid_jpeg(color="red"))

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert second.json() == CAPTURE_EXISTS
    assert len(edge.rows()) == 1
    images = edge.images()
    assert len(images) == 1
    assert images[0].read_bytes() == solid_jpeg()  # the first image was not overwritten


# =========================================================================== CA-09


def _concurrent_posts(
    clients: list[TestClient], token: str, datas: list[dict[str, Any]]
) -> list[httpx.Response]:
    barrier = threading.Barrier(len(datas))
    responses: list[httpx.Response | None] = [None] * len(datas)
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            barrier.wait(timeout=10)
            responses[i] = post_collect(clients[i % len(clients)], token, data=datas[i])
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(datas))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []
    assert all(r is not None for r in responses)
    return [r for r in responses if r is not None]


def test_ca09_two_concurrent_requests_give_two_valid_lines(edge: Edge) -> None:
    datas = [
        fields(item_id="S-001", object_type="screw", grade="good", angle="0", notes="um"),
        fields(item_id="N-001", object_type="nut", grade="poor", angle="3", notes="dois"),
    ]
    with TestClient(edge.app()) as client:
        responses = _concurrent_posts([client], edge.token, datas)

    assert [r.status_code for r in responses] == [200, 200]
    raw = edge.manifest.read_text(encoding="utf-8")
    assert raw.count(HEADER_LINE) == 1 and raw.startswith(HEADER_LINE)
    assert len(raw.splitlines()) == 3
    rows = edge.rows()
    assert len(rows) == 2
    assert all(len(row) == 9 and None not in row for row in rows)
    by_item = {row["item_id"]: row for row in rows}
    for data in datas:
        row = by_item[data["item_id"]]
        for key in ("object_type", "grade", "labeler", "angle", "notes"):
            assert row[key] == data[key]
        assert row["image_path"].startswith(f"raw/{data['object_type']}/{data['grade']}/")


# =========================================================================== CA-10


def test_ca10_notes_with_quotes_and_comma_round_trip(edge: Edge, client: TestClient) -> None:
    notes = 'tem "aspas", vírgula'
    r = post_collect(client, edge.token, data=fields(notes=notes))
    assert r.status_code == 200, r.text
    assert edge.rows()[0]["notes"] == notes
    line = edge.manifest.read_text(encoding="utf-8").splitlines()[1]
    assert line.endswith('"tem ""aspas"", vírgula"')


# =========================================================================== CA-11


@pytest.mark.parametrize(
    "header",
    [
        "image_path,item_id,object_type,grade,labeler,angle,captured_at,notes,capture_device\n",
        "image_path,item_id,object_type,grade,labeler,angle,captured_at,capture_device\n",
        HEADER_LINE.replace("\n", ",lot_id\n"),
        "path,item,type\n",
        "﻿" + HEADER_LINE,
    ],
    ids=["reordered", "missing-column", "extra-column", "other-csv", "bom"],
)
def test_ca11_header_mismatch_is_500_and_nothing_changes(
    edge: Edge, client: TestClient, header: str
) -> None:
    original = write_manifest(edge.manifest, [], header=header)
    r = post_collect(client, edge.token)
    assert r.status_code == 500, r.text
    assert r.json() == HEADER_MISMATCH
    assert edge.manifest.read_bytes() == original
    assert edge.images() == []


# =========================================================================== CA-12


def _three_collects(edge: Edge, client: TestClient) -> None:
    for i, angle in enumerate(["0", "1", "2"]):
        r = post_collect(client, edge.token, data=fields(angle=angle, notes=f"n{i}"))
        assert r.status_code == 200, r.text


def test_ca12_collect_without_model_never_reaches_the_sink(edge: Edge) -> None:
    sink = RecordingSink()
    with TestClient(edge.app(inferencer=None, sink=sink)) as client:
        _three_collects(edge, client)
    assert sink.calls == 0 and sink.items == []
    assert len(edge.rows()) == 3
    captures = edge.data_dir / "captures"
    assert not captures.exists() or not any(p.is_file() for p in captures.rglob("*"))


def test_ca12_collect_never_calls_the_stub_inferencer_nor_the_sink(edge: Edge) -> None:
    stub = StubInferencer(stub_result())
    sink = RecordingSink()
    with TestClient(edge.app(inferencer=stub, sink=sink)) as client:
        _three_collects(edge, client)
    assert stub.calls == 0
    assert sink.calls == 0 and sink.items == []
    assert len(edge.rows()) == 3


# =========================================================================== CA-13


def test_ca13_dataset_files_are_never_served(edge: Edge, client: TestClient) -> None:
    r = post_collect(client, edge.token)
    assert r.status_code == 200, r.text
    name = Path(r.json()["image_path"]).name
    paths = [
        f"/raw/screw/fair/{name}",
        "/ml/data/manifest.csv",
        "/manifest.csv",
    ]
    for path in paths:
        assert client.get(path).status_code == 404, path
        assert client.get(path, headers={SESSION_HEADER: edge.token}).status_code == 404, path


# =========================================================================== CA-14


def _assert_dataset_untouched(edge: Edge) -> None:
    assert edge.images() == []
    assert not edge.manifest.exists()


@pytest.mark.parametrize("token", ["missing", "wrong"])
def test_ca14_without_valid_token_is_401(edge: Edge, client: TestClient, token: str) -> None:
    value = None if token == "missing" else new_token()
    r = post_collect(client, value)
    assert r.status_code == 401, r.text
    _assert_dataset_untouched(edge)


def test_ca14_image_of_3_mib_plus_one_byte_is_413(edge: Edge, client: TestClient) -> None:
    image = padded_jpeg(3_145_729)
    assert len(image) == 3_145_729
    r = post_collect(client, edge.token, image)
    assert r.status_code == 413, r.text
    _assert_dataset_untouched(edge)


def test_ca14_text_renamed_to_jpg_is_415(edge: Edge, client: TestClient) -> None:
    r = post_collect(client, edge.token, "isto não é uma foto\n".encode() * 20)
    assert r.status_code == 415, r.text
    _assert_dataset_untouched(edge)


def test_ca14_jpeg_above_the_route_pixel_limit_is_415(edge: Edge, client: TestClient) -> None:
    image = encode(Image.new("RGB", (2001, 2000), "gray"), "JPEG", quality=50)
    assert len(image) <= 3_145_728
    r = post_collect(client, edge.token, image)
    assert r.status_code == 415, r.text
    _assert_dataset_untouched(edge)


# =========================================================================== CA-15


def _ca15_manifest(path: Path) -> None:
    rows: list[list[str]] = []
    for i in range(130):
        rows.append(manifest_row(f"S-{i % 9:03d}", "screw", "perfect", i % 5, i))
    for i in range(40):
        rows.append(manifest_row(f"N-{i % 3:03d}", "nut", "poor", i % 5, i))
    for i in range(10):
        rows.append(manifest_row(f"O-{i:03d}", "other", "", 0, i))
    write_manifest(path, rows)


def test_ca15_compute_coverage_counts_images_and_items(edge: Edge) -> None:
    _ca15_manifest(edge.manifest)

    cells = compute_coverage(edge.manifest)

    # SPEC-016 section 4.4: the table gains the rows of the 5 hand tools (5 grades each);
    # SPEC-021 section 3.1: and one row per power tool, without grade.
    assert len(cells) == 11 + 25 + 4
    by_key = {(c.object_type, c.grade): c for c in cells}
    expected_keys = {(t, g) for t in ("screw", "nut") for g in GRADES} | {("other", None)}
    assert set(by_key) == (
        expected_keys | {(t, g) for t in TOOLS_016 for g in GRADES} | {(t, None) for t in POWER_021}
    )
    for key, cell in by_key.items():
        if key == ("screw", "perfect"):
            assert (cell.images, cell.items) == (130, 9)
        elif key == ("nut", "poor"):
            assert (cell.images, cell.items) == (40, 3)
        elif key == ("other", None):
            assert (cell.images, cell.items) == (10, 10)
        else:
            assert (cell.images, cell.items) == (0, 0), key
        if key not in expected_keys:
            continue  # SPEC-016: the targets of the tool cells are not part of this CA
        targets = (150, 30) if key[0] == "other" else (120, 12)
        assert (cell.target_images, cell.target_items) == targets, key


def test_ca15_console_shows_the_coverage_table(edge: Edge) -> None:
    _ca15_manifest(edge.manifest)
    page = console_get(edge.app())
    assert page.status_code == 200, page.text
    assert '<table id="coverage">' in page.text
    table = _coverage_table(page.text)
    assert "130/120" in table
    assert "9/12" in table
    assert "40/120" in table
    assert "10/150" in table
    assert "10/30" in table
    assert re.search(r">\s*180\s*<", table)  # total of images (130 + 40 + 10)


def test_ca15_missing_manifest_is_an_empty_table(edge: Edge) -> None:
    cells = compute_coverage(edge.manifest)
    # SPEC-016 section 4.4: plus the 5 tools x 5 grades; SPEC-021: plus 4 power tool rows.
    assert len(cells) == 11 + 25 + 4
    assert all((c.images, c.items) == (0, 0) for c in cells)
    page = console_get(edge.app())
    assert page.status_code == 200
    table = _coverage_table(page.text)
    assert "0/120" in table and "0/12" in table and "0/150" in table and "0/30" in table
    assert not edge.dataset.exists()  # the console does not create DATASET_DIR


def _coverage_table(html: str) -> str:
    start = html.index('<table id="coverage">')
    end = html.index("</table>", start)
    return html[start:end]


# =========================================================================== CA-16


class FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.controls: list[tuple[str, dict[str, str | None]]] = []
        self.options: list[dict[str, str | None]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in {"input", "select", "textarea"}:
            self.controls.append((tag, a))
        if tag == "option":
            self.options.append(a)

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def test_ca16_capture_page_has_collect_fields_and_enabled_mode(
    edge: Edge, client: TestClient
) -> None:
    r = client.get("/capture", params={"t": edge.token})
    assert r.status_code == 200
    parser = FormParser()
    parser.feed(r.text)
    names = {a.get("name") for _, a in parser.controls} | {a.get("id") for _, a in parser.controls}
    for name in ("item_id", "object_type", "grade", "labeler", "angle", "notes"):
        assert name in names, name
    collect = [o for o in parser.options if o.get("value") == "collect"]
    assert collect, "mode selector has no collect option"
    assert all("disabled" not in o for o in collect)
    text = " ".join(parser.text)
    assert "coleta" in text
    for label in ("parafuso", "porca", "outro"):
        assert label in text, label
    for grade in Grade:
        assert GRADE_LABELS_PT[grade] in text, grade
    assert "Sem pessoas no quadro" in r.text


# =========================================================================== CA-18


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.parametrize("umask", [0o022, 0o077], ids=["umask-022", "umask-077"])
def test_ca18_exact_modes_whatever_the_umask(edge: Edge, umask: int) -> None:
    assert not edge.dataset.exists()
    jpeg = fields(item_id="S-012", object_type="screw", grade="fair", angle="0")
    png = fields(item_id="O-004", object_type="other", grade="", angle="0")
    old = os.umask(umask)
    try:
        with TestClient(edge.app()) as client:
            r1 = post_collect(client, edge.token, solid_jpeg(), jpeg)
            r2 = post_collect(
                client, edge.token, solid_png(), png, filename="f.png", content_type="image/png"
            )
    finally:
        os.umask(old)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    ds = edge.dataset
    for directory in (
        ds,
        ds / "raw",
        ds / "raw/screw",
        ds / "raw/screw/fair",
        ds / "raw/other",
        ds / "raw/other/_",
    ):
        assert _mode(directory) == 0o700, directory
    images = edge.images()
    assert len(images) == 2
    for path in [*images, edge.manifest]:
        assert _mode(path) == 0o600, path
    lock = ds / "manifest.csv.lock"
    if lock.exists():
        assert _mode(lock) == 0o600
    png_stored = ds / r2.json()["image_path"]
    assert png_stored.read_bytes()[:2] == b"\xff\xd8"  # PNG reencoded as JPEG
    with Image.open(png_stored) as img:
        assert img.format == "JPEG"


# =========================================================================== extras


def test_extra_existing_dataset_dir_and_files_keep_their_modes(edge: Edge) -> None:
    edge.dataset.mkdir()
    edge.dataset.chmod(0o755)
    write_manifest(edge.manifest, [manifest_row("S-001", "screw", "good")])
    edge.manifest.chmod(0o644)
    with TestClient(edge.app()) as client:
        r = post_collect(client, edge.token)
    assert r.status_code == 200, r.text
    assert _mode(edge.dataset) == 0o755
    assert _mode(edge.manifest) == 0o644
    assert _mode(edge.dataset / "raw") == 0o700
    assert _mode(edge.dataset / r.json()["image_path"]) == 0o600


@pytest.mark.parametrize("umask", [0o000, 0o277], ids=["umask-000", "umask-277"])
def test_extra_exact_modes_with_extreme_umasks(edge: Edge, umask: int) -> None:
    old = os.umask(umask)
    try:
        with TestClient(edge.app()) as client:
            r = post_collect(client, edge.token)
    finally:
        os.umask(old)
    assert r.status_code == 200, r.text
    assert _mode(edge.dataset / "raw/screw/fair") == 0o700
    assert _mode(edge.dataset / r.json()["image_path"]) == 0o600
    assert _mode(edge.manifest) == 0o600


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("item_id", "S-٠١٢"),  # Arabic-Indic digits match a non-ASCII \d
        ("item_id", " S-012"),
        ("item_id", "S-012 "),
        ("item_id", "S‐012"),  # Unicode hyphen
        ("item_id", "S-012/"),
        ("item_id", ""),
        ("item_id", None),
        ("angle", " 2"),
        ("angle", "02"),
        ("angle", "²"),
        ("angle", "٢"),
        ("angle", "2.0"),
        ("angle", ""),
        ("angle", None),
        ("object_type", "Screw"),
        ("object_type", " screw"),
        ("object_type", ""),
        ("grade", "Fair"),
        ("grade", "fair\n"),
        ("grade", " fair"),
        ("labeler", "A"),
        ("labeler", "a\n"),
        ("labeler", ""),
        ("labeler", None),
        ("notes", "tab\there"),
        ("notes", "cr\rhere"),
        ("notes", "nul\x00here"),
        ("notes", "del\x7fhere"),
        ("notes", "esc\x1bhere"),
        ("notes", "c1\x85here"),
        ("mode", "collect\n"),
        ("mode", "Collect"),
    ],
    ids=lambda v: repr(v),
)
def test_extra_more_invalid_fields_are_422(
    edge: Edge, client: TestClient, name: str, value: str | None
) -> None:
    edge.dataset.mkdir()
    before = edge.tree()
    r = post_collect(client, edge.token, data=fields(**{name: value}))
    assert r.status_code == 422, r.text
    assert edge.tree() == before


def test_extra_duplicate_item_id_field_is_not_a_path_trick(edge: Edge, client: TestClient) -> None:
    data = fields()
    data["item_id"] = ["S-012", "../../S-001"]
    r = post_collect(client, edge.token, data=data)
    assert r.status_code in {200, 422}, r.text
    for path in edge.tree():
        assert "S-001" not in path
    if r.status_code == 200:
        assert r.json()["item_id"] == "S-012"


@pytest.mark.parametrize(
    "notes",
    ["n" * 200, "ç" * 200, "", "  espaços nas pontas  ", "=SUM(A1)", "emoji 🔩 ok", "a;b|c"],
    ids=["200-ascii", "200-multibyte", "empty", "spaces", "formula", "emoji", "separators"],
)
def test_extra_valid_notes_are_kept_verbatim(edge: Edge, client: TestClient, notes: str) -> None:
    r = post_collect(client, edge.token, data=fields(notes=notes))
    assert r.status_code == 200, r.text
    assert edge.rows()[0]["notes"] == notes


def test_extra_notes_absent_is_accepted(edge: Edge, client: TestClient) -> None:
    r = post_collect(client, edge.token, data=fields(notes=None))
    assert r.status_code == 200, r.text
    assert edge.rows()[0]["notes"] == ""


def test_extra_lot_id_is_ignored_in_collect_mode(edge: Edge, client: TestClient) -> None:
    data = fields()
    data["lot_id"] = "lote inválido!! " * 10
    r = post_collect(client, edge.token, data=data)
    assert r.status_code == 200, r.text
    raw = edge.manifest.read_text(encoding="utf-8")
    assert "lote" not in raw


def test_extra_without_user_agent_capture_device_is_empty(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        client.headers.pop("user-agent", None)
        r = post_collect(client, edge.token, user_agent=None)
    assert r.status_code == 200, r.text
    assert edge.rows()[0]["capture_device"] == ""


def test_extra_user_agent_with_comma_and_quotes_round_trips(edge: Edge, client: TestClient) -> None:
    ua = 'Phone "X", build 7'
    r = post_collect(client, edge.token, user_agent=ua)
    assert r.status_code == 200, r.text
    assert edge.rows()[0]["capture_device"] == ua


def test_extra_non_utc_clock_is_written_in_utc(edge: Edge) -> None:
    edge.clock.value = datetime(
        2026, 10, 22, 11, 15, 3, 987654, tzinfo=timezone(timedelta(hours=-3))
    )
    with TestClient(edge.app()) as client:
        r = post_collect(client, edge.token)
    assert r.status_code == 200, r.text
    assert r.json()["image_path"] == f"raw/screw/fair/S-012__2__{CA01_STAMP}.jpg"
    assert edge.rows()[0]["captured_at"] == "2026-10-22T14:15:03Z"


def test_extra_png_is_reencoded_as_jpeg(edge: Edge, client: TestClient) -> None:
    r = post_collect(client, edge.token, solid_png(), filename="x.png", content_type="image/png")
    assert r.status_code == 200, r.text
    assert r.json()["image_path"].endswith(".jpg")
    with Image.open(edge.dataset / r.json()["image_path"]) as img:
        assert img.format == "JPEG"
        assert img.size == (64, 48)


def test_extra_image_of_exactly_3_mib_is_accepted(edge: Edge, client: TestClient) -> None:
    r = post_collect(client, edge.token, padded_jpeg(3_145_728))
    assert r.status_code == 200, r.text


def test_extra_no_temporary_files_left_after_success_and_conflicts(
    edge: Edge, client: TestClient
) -> None:
    assert post_collect(client, edge.token).status_code == 200
    assert post_collect(client, edge.token).status_code == 409
    leftovers = [
        p
        for p in edge.dataset.rglob("*")
        if p.is_file() and p.name not in {"manifest.csv", "manifest.csv.lock"}
    ]
    assert [p.suffix for p in leftovers] == [".jpg"]
    assert len(leftovers) == 1


def test_extra_hand_edited_manifest_without_final_newline(edge: Edge, client: TestClient) -> None:
    content = write_manifest(edge.manifest, [manifest_row("S-001", "screw", "good")])
    edge.manifest.write_bytes(content.rstrip(b"\n"))
    r = post_collect(client, edge.token)
    assert r.status_code == 200, r.text
    rows = edge.rows()
    assert [row["item_id"] for row in rows] == ["S-001", "S-012"]


def test_extra_ticking_clock_same_item_and_angle(edge: Edge, client: TestClient) -> None:
    assert post_collect(client, edge.token).status_code == 200
    edge.clock.value = CA01_INSTANT + timedelta(seconds=1)
    r = post_collect(client, edge.token)
    assert r.status_code == 200, r.text
    assert r.json()["item_images"] == 2


def test_extra_many_threads_two_apps_share_the_manifest(edge: Edge) -> None:
    """Two apps (two process locks) on one DATASET_DIR: only the file lock serializes them."""
    datas = []
    for i in range(24):
        kind = ("screw", "S", "good") if i % 2 == 0 else ("nut", "N", "fair")
        datas.append(
            fields(item_id=f"{kind[1]}-{i:03d}", object_type=kind[0], grade=kind[2], angle="0")
        )
    with TestClient(edge.app()) as c1, TestClient(edge.app()) as c2:
        responses = _concurrent_posts([c1, c2], edge.token, datas)
    assert [r.status_code for r in responses] == [200] * 24
    raw = edge.manifest.read_text(encoding="utf-8")
    assert raw.count(HEADER_LINE) == 1 and raw.startswith(HEADER_LINE)
    rows = edge.rows()
    assert len(rows) == 24
    assert {row["item_id"] for row in rows} == {d["item_id"] for d in datas}
    assert all(None not in row and len(row) == 9 for row in rows)
    assert len(edge.images()) == 24


def test_extra_concurrent_same_capture_one_wins(edge: Edge) -> None:
    datas = [fields() for _ in range(6)]
    with TestClient(edge.app()) as c1, TestClient(edge.app()) as c2:
        responses = _concurrent_posts([c1, c2], edge.token, datas)
    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [409] * 5
    assert len(edge.rows()) == 1
    assert len(edge.images()) == 1


def test_extra_collect_uses_the_shared_decode_limiter(edge: Edge) -> None:
    edge.clock.value = (datetime.now(UTC) - timedelta(minutes=1)).replace(microsecond=0)
    inf = BlockingInferencer()
    app = edge.app(inferencer=inf, max_concurrent_decodes=1, decode_wait_s=0.3)
    with TestClient(app) as client:
        holder: list[httpx.Response] = []
        t = threading.Thread(
            target=lambda: holder.append(
                client.post(
                    "/api/capture",
                    headers={SESSION_HEADER: edge.token},
                    data={"lot_id": "L-001", "mode": "inspect"},
                    files={"image": ("f.jpg", solid_jpeg(), "image/jpeg")},
                )
            )
        )
        t.start()
        assert inf.started.wait(timeout=10)
        busy = post_collect(client, edge.token)
        inf.release.set()
        t.join(timeout=15)
        after = post_collect(client, edge.token)
    assert busy.status_code == 503, busy.text
    assert busy.json() == {"detail": "server busy"}
    assert holder and holder[0].status_code == 200
    assert after.status_code == 200, after.text
    assert len(edge.rows()) == 1


def test_extra_collect_opens_no_network_connection(
    edge: Edge, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[Any] = []

    def refuse(*args: Any, **kwargs: Any) -> Any:
        attempts.append(args)
        raise OSError("network disabled by the test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    for angle in ("0", "1", "2"):
        r = post_collect(client, edge.token, data=fields(angle=angle))
        assert r.status_code == 200, r.text
    assert attempts == []


def test_extra_dataset_traversal_urls_are_404(edge: Edge, client: TestClient) -> None:
    assert post_collect(client, edge.token).status_code == 200
    for path in (
        "/static/../manifest.csv",
        "/static/%2e%2e/%2e%2e/manifest.csv",
        "/static/..%2f..%2fmanifest.csv",
        "/raw/",
        "/dataset/manifest.csv",
        "/data/manifest.csv",
    ):
        r = client.get(path)
        assert r.status_code == 404, path
        assert "image_path" not in r.text


def test_extra_compute_coverage_ignores_unknown_cells(edge: Edge) -> None:
    write_manifest(
        edge.manifest,
        [
            manifest_row("S-001", "screw", "good"),
            manifest_row("S-002", "screw", "bogus"),
            # SPEC-016 section 3.1: pliers is a valid cell now; a type still unknown instead.
            manifest_row("T-001", "hammer", "good"),
        ],
    )
    cells = {(c.object_type, c.grade): c for c in compute_coverage(edge.manifest)}
    # SPEC-016 section 4.4: plus the 5 tools x 5 grades; SPEC-021: plus 4 power tool rows.
    assert len(cells) == 11 + 25 + 4
    assert (cells[("screw", "good")].images, cells[("screw", "good")].items) == (1, 1)


def test_extra_console_highlights_only_complete_cells(edge: Edge) -> None:
    rows = [manifest_row(f"S-{i % 12:03d}", "screw", "good", i % 5, i) for i in range(120)]
    rows += [manifest_row(f"S-{100 + i % 11:03d}", "screw", "fair", i % 5, i) for i in range(130)]
    rows += [manifest_row(f"N-{i % 12:03d}", "nut", "perfect", i % 5, i) for i in range(119)]
    write_manifest(edge.manifest, rows)
    table = _coverage_table(console_get(edge.app()).text)
    tr = re.findall(r"<tr\b[^>]*>.*?</tr>", table, flags=re.S)
    complete = [row for row in tr if "120/120" in row and "12/12" in row]
    incomplete = [row for row in tr if "130/120" in row or "119/120" in row]
    assert len(complete) == 1 and len(incomplete) == 2

    def shape(row: str) -> list[str]:
        return re.findall(r"<t[dhr]\b[^>]*>", row)

    assert all(shape(complete[0]) != shape(row) for row in incomplete)
    assert shape(incomplete[0]) == shape(incomplete[1])


def test_extra_console_survives_an_unreadable_manifest(edge: Edge) -> None:
    edge.dataset.mkdir()
    edge.manifest.write_bytes(HEADER_LINE.encode() + b"\xff\xfe broken \xff\n")
    page = console_get(edge.app())
    assert page.status_code == 200
    assert '<table id="coverage">' in page.text


def test_extra_capture_script_strings_and_size(edge: Edge, client: TestClient) -> None:
    js = client.get("/static/capture.js")
    assert js.status_code == 200
    assert len(js.text.splitlines()) <= 200
    page = client.get("/capture", params={"t": edge.token}).text
    assert "Peça completa — troque o item_id" in page + js.text
    assert "Salvo:" in js.text
    assert "localStorage" in js.text


def test_extra_edge_readme_documents_ca17(edge: Edge) -> None:
    readme = (EDGE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Modo coleta" in readme
    assert "DATASET_DIR" in readme
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^DATASET_DIR=", env_example, flags=re.M)


def test_extra_default_dataset_dir_is_ml_data(edge: Edge, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATASET_DIR")
    assert Path("ml/data") == EdgeSettings().DATASET_DIR


def test_extra_inspect_mode_still_works_alongside_collect(edge: Edge) -> None:
    edge.clock.value = (datetime.now(UTC) - timedelta(minutes=1)).replace(microsecond=0)
    stub = StubInferencer(stub_result())
    sink = RecordingSink()
    with TestClient(edge.app(inferencer=stub, sink=sink)) as client:
        assert post_collect(client, edge.token).status_code == 200
        r = client.post(
            "/api/capture",
            headers={SESSION_HEADER: edge.token},
            data={"lot_id": "L-001", "mode": "inspect"},
            files={"image": ("f.jpg", solid_jpeg(), "image/jpeg")},
        )
    assert r.status_code == 200, r.text
    assert stub.calls == 1 and sink.calls == 1
    assert len(edge.rows()) == 1  # inspect mode never writes to the dataset


def test_extra_collect_timing_is_reasonable(edge: Edge, client: TestClient) -> None:
    start = time.monotonic()
    for angle in "01234":
        assert post_collect(client, edge.token, data=fields(angle=angle)).status_code == 200
    assert time.monotonic() - start < 10


def test_extra_manifest_append_failure_removes_the_image(edge: Edge, client: TestClient) -> None:
    """§4.2, step 5: a failure while appending to the manifest removes the image and is 500."""
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    original = write_manifest(edge.manifest, [manifest_row("S-001", "screw", "good")])
    edge.manifest.chmod(0o400)
    try:
        r = post_collect(client, edge.token)
    finally:
        edge.manifest.chmod(0o600)
    assert r.status_code == 500, r.text
    assert set(r.json()) == {"detail"}
    assert "Traceback" not in r.text
    assert edge.images() == []
    assert edge.manifest.read_bytes() == original
    leftovers = [p for p in (edge.dataset / "raw").rglob("*") if p.is_file()]
    assert leftovers == []


def test_extra_manifest_symlink_is_not_followed_on_write(edge: Edge, client: TestClient) -> None:
    outside = edge.tmp / "outside.csv"
    original = write_manifest(outside, [])
    edge.dataset.mkdir()
    edge.manifest.symlink_to(outside)
    r = post_collect(client, edge.token)
    assert r.status_code == 500, r.text
    assert outside.read_bytes() == original
    assert edge.images() == []


def test_extra_manifest_with_only_the_header(edge: Edge, client: TestClient) -> None:
    write_manifest(edge.manifest, [])
    r = post_collect(client, edge.token)
    assert r.status_code == 200, r.text
    assert r.json()["item_images"] == 1
    assert len(edge.rows()) == 1


def test_extra_empty_manifest_file_is_a_header_mismatch(edge: Edge, client: TestClient) -> None:
    edge.dataset.mkdir()
    edge.manifest.write_bytes(b"")
    r = post_collect(client, edge.token)
    assert r.status_code == 500, r.text
    assert r.json() == HEADER_MISMATCH
    assert edge.manifest.read_bytes() == b""
    assert edge.images() == []


def test_extra_crlf_header_is_accepted_and_rows_still_parse(edge: Edge, client: TestClient) -> None:
    edge.dataset.mkdir()
    edge.manifest.write_bytes(HEADER_LINE.replace("\n", "\r\n").encode())
    r = post_collect(client, edge.token)
    assert r.status_code == 200, r.text
    assert [row["item_id"] for row in edge.rows()] == ["S-012"]


def test_extra_dataset_dir_that_is_a_file_is_refused_by_the_settings(edge: Edge) -> None:
    edge.dataset.write_bytes(b"not a directory")
    with pytest.raises(ValueError, match="DATASET_DIR"):
        EdgeSettings()


def test_extra_manifest_rows_with_invalid_utf8(edge: Edge, client: TestClient) -> None:
    content = write_manifest(edge.manifest, [manifest_row("S-001", "screw", "good")])
    edge.manifest.write_bytes(content + b"\xff\xfe,broken\n")
    before = edge.manifest.read_bytes()
    r = post_collect(client, edge.token)
    assert r.status_code == 500, r.text
    assert edge.manifest.read_bytes() == before
    assert edge.images() == []
