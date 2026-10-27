"""Acceptance tests for SPEC-036 (qc-edge: import of photos that do not come from ``/capture``).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One ``test_caNN_*`` per automatable CA, at least (CA-17 is manual and is recorded
in ``reviews/SPEC-036/r1-test-report.md``). Tests named ``test_extra_*`` are exploratory edge
cases around the SPEC (``security`` tag) that no CA spells out.

Rules followed (``reviews/checklist.md`` and ``docs/architecture.md`` section 10):

* the only boundaries replaced are the ones the SPEC names (section 6): the clock, ``sleep``,
  ``socket.socket`` (CA-11) and the file write in the error cases (CA-09, a spy on ``os.write``
  that recognises the target through ``/proc/self/fd``); the file system is real, always under
  ``tmp_path``;
* every image is generated in the test by Pillow, never a real photo (R-14);
* every marker is generated at run time (``secrets``), never a credential literal;
* the problem lines of the plan are looked up in ``err.splitlines()`` without requiring that they
  are the only lines there (the log handler may also write to ``stderr``, dev report, decision 4).
"""

from __future__ import annotations

import asyncio
import csv
import errno
import functools
import hashlib
import io
import logging
import os
import re
import secrets
import socket
import stat
import struct
import threading
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import ExifTags, Image, ImageFile

import qc_edge.importer
import qc_edge.privacy
from qc_edge.app import create_app
from qc_edge.collect import compute_coverage, count_external_images
from qc_edge.config import EdgeSettings
from qc_edge.jpeg import exif_orientation, has_exif_rotation, jpeg_private_findings
from qc_edge.sink import InMemorySink
from qc_preprocess import InvalidImageError, load_image

pytestmark = pytest.mark.acceptance

EDGE_ROOT = Path(__file__).resolve().parents[2]  # edge/
ROOT = EDGE_ROOT.parent

T0 = datetime(2026, 10, 22, 14, 15, 3, tzinfo=UTC)
STAMP0 = "20261022T141503Z"
STAMP1 = "20261022T141504Z"
MIB = 1024 * 1024
IMPORT_MAX_BYTES = 40 * MIB

PLAN_COLUMNS = (
    "file",
    "item_id",
    "object_type",
    "grade",
    "labeler",
    "angle",
    "origin",
    "contributor",
    "source_id",
    "source_ref",
    "notes",
)
MANIFEST_COLUMNS = (
    "image_path",
    "item_id",
    "object_type",
    "grade",
    "labeler",
    "angle",
    "captured_at",
    "capture_device",
    "notes",
)
SOURCES_COLUMNS = ("image_path", "origin", "contributor", "source_id", "source_ref", "input_sha256")
REGISTRY_HEADER = "source_id,title,url,license,license_url,attribution,retrieved_at"
REGISTRY_LINE = (
    "fonte-teste,Fonte de teste,https://example.org/fonte,CC-BY-4.0,"
    "https://creativecommons.org/licenses/by/4.0/,Fonte de teste (example.org),2026-10-20"
)
CONTRIBUTOR_CELLS = ("S-501", "screw", "fair", "a", "2", "contributor", "c01", "", "")
CONTRIBUTOR_NOTES = "dúvida fair/poor"
EXTERNAL_CELLS = (
    "XS-0001",
    "screw",
    "perfect",
    "b",
    "0",
    "external",
    "",
    "fonte-teste",
    "dataset/train/0001.png",
)
LATITUDE = (23.0, 33.0, 47.25)
PHONE_MAKE = "AccPhone36"
RED = (220, 30, 30)
GREY = (128, 128, 128)
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


def new_marker(prefix: str = "acc") -> str:
    return prefix + secrets.token_hex(12)


# =========================================================================== images (Pillow only)


def encode(img: Image.Image, fmt: str, **kwargs: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def textured(width: int, height: int, seed: int) -> Image.Image:
    """Smooth random texture (survives JPEG well) with a red block in the top-left corner."""
    rng = np.random.default_rng(seed)
    small = rng.integers(40, 216, size=(max(2, height // 40), max(2, width // 40), 3))
    img = Image.fromarray(small.astype(np.uint8), "RGB").resize(
        (width, height), Image.Resampling.BILINEAR
    )
    img.paste(RED, (0, 0, max(1, width // 4), max(1, height // 4)))
    return img


def jpeg(width: int = 800, height: int = 600, seed: int = 1, **kwargs: Any) -> bytes:
    kwargs.setdefault("quality", 90)
    return encode(textured(width, height, seed), "JPEG", **kwargs)


def gps_exif(orientation: int | None = None) -> Image.Exif:
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = PHONE_MAKE
    if orientation is not None:
        exif[ExifTags.Base.Orientation] = orientation
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "S"
    gps[ExifTags.GPS.GPSLatitude] = LATITUDE
    return exif


@functools.cache
def phone_photo() -> bytes:
    """The "foto de celular": shown image E 3000x4000, stored ROTATE_90, Orientation=6."""
    shown = Image.new("RGB", (3000, 4000), GREY)
    shown.paste(RED, (0, 0, 1500, 2000))
    stored = shown.transpose(Image.Transpose.ROTATE_90)
    assert stored.size == (4000, 3000)
    data = encode(stored, "JPEG", quality=90, exif=gps_exif(6))
    assert load_image(data).size == (3000, 4000)  # the loader applies the EXIF rotation
    gps = Image.open(io.BytesIO(data)).getexif().get_ifd(ExifTags.IFD.GPSInfo)
    assert ExifTags.GPS.GPSLatitude in gps  # the fixture really carries GPS
    return data


@functools.cache
def motion_photo() -> bytes:
    """CA-02: 1000x750 JPEG with GPS and Orientation=1, then a "motion photo" after the EOI."""
    base = encode(textured(1000, 750, 2), "JPEG", quality=90, exif=gps_exif(1))
    data = base + b"\x00\x00\x00\x18ftypmp42" + b"\xff\xda" * 100 + b"\x00" * MIB
    with pytest.raises(InvalidImageError, match="JPEG scans"):
        load_image(data)
    return data


@functools.cache
def rgba_png() -> bytes:
    """CA-03: RGBA PNG 2048x1024."""
    img = textured(2048, 1024, 3).convert("RGBA")
    img.putalpha(200)
    data = encode(img, "PNG")
    assert Image.open(io.BytesIO(data)).mode == "RGBA"
    return data


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mean_abs_diff(a: Image.Image, b: Image.Image) -> np.ndarray:
    left = np.asarray(a.convert("RGB"), dtype=np.int16)
    right = np.asarray(b.convert("RGB"), dtype=np.int16)
    assert left.shape == right.shape
    return np.abs(left - right).mean(axis=(0, 1))


# =========================================================================== clock, sleep, runner


class Clock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class SleepSpy:
    """``sleep`` spy; advances ``clock`` by ``step`` seconds per call (0 = clock never moves)."""

    def __init__(self, clock: Clock | None = None, step: float = 0.0) -> None:
        self.calls: list[float] = []
        self.clock = clock
        self.step = step

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self.clock is not None and self.step:
            self.clock.advance(self.step)


@dataclass
class Result:
    code: int
    out: str
    err: str
    log: str

    @property
    def out_lines(self) -> list[str]:
        return self.out.splitlines()

    @property
    def err_lines(self) -> list[str]:
        return self.err.splitlines()

    def everything(self) -> str:
        return self.out + self.err + self.log


@dataclass
class Env:
    tmp: Path
    capsys: pytest.CaptureFixture[str]
    caplog: pytest.LogCaptureFixture
    dataset: Path
    inbox: Path
    registry: Path
    plan: Path
    clock: Clock = field(default_factory=Clock)
    sleep: SleepSpy = field(default_factory=SleepSpy)

    # ------------------------------------------------------------------ inputs
    def put(self, name: str, data: bytes) -> str:
        path = self.inbox / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return name

    def write_registry(self, line: str = REGISTRY_LINE) -> None:
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        self.registry.write_text(REGISTRY_HEADER + "\n" + line + "\n", encoding="utf-8")

    def write_plan(
        self, rows: Sequence[Sequence[str]], header: Sequence[str] = PLAN_COLUMNS
    ) -> None:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
        self.plan.write_bytes(buf.getvalue().encode("utf-8"))

    def argv(self, *extra: str, privacy: bool = True, registry: Path | None = None) -> list[str]:
        args = [
            "--dataset-dir",
            str(self.dataset),
            "--inbox",
            str(self.inbox),
            "--plan",
            str(self.plan),
            "--external-sources",
            str(self.registry if registry is None else registry),
        ]
        if privacy:
            args.append("--privacy-checked")
        return args + list(extra)

    # ------------------------------------------------------------------ run
    def run(self, argv: list[str] | None = None, *extra: str) -> Result:
        self.capsys.readouterr()
        self.caplog.clear()
        args = self.argv(*extra) if argv is None else argv
        with self.caplog.at_level(logging.DEBUG):
            try:
                code = qc_edge.importer.main(args, clock=self.clock, sleep=self.sleep)
            except SystemExit as exc:  # argparse
                raw = exc.code
                code = raw if isinstance(raw, int) else (0 if raw is None else 1)
        out = self.capsys.readouterr()
        return Result(code, out.out, out.err, self.caplog.text)

    # ------------------------------------------------------------------ dataset
    @property
    def manifest(self) -> Path:
        return self.dataset / "manifest.csv"

    @property
    def sources(self) -> Path:
        return self.dataset / "sources.csv"

    def manifest_rows(self) -> list[dict[str, str]]:
        return read_csv(self.manifest, MANIFEST_COLUMNS)

    def sources_rows(self) -> list[dict[str, str]]:
        return read_csv(self.sources, SOURCES_COLUMNS)

    def images(self) -> list[str]:
        raw = self.dataset / "raw"
        if not raw.exists():
            return []
        return sorted(str(p.relative_to(self.dataset)) for p in raw.rglob("*") if p.is_file())

    def snapshot(self, root: Path | None = None) -> dict[str, bytes | None]:
        """Names and bytes of every entry under ``root`` (default ``DATASET_DIR``)."""
        base = self.dataset if root is None else root
        if not base.exists():
            return {}
        result: dict[str, bytes | None] = {}
        for path in sorted(base.rglob("*")):
            rel = str(path.relative_to(base))
            result[rel] = None if path.is_dir() else path.read_bytes()
        return result


def read_csv(path: Path, columns: Sequence[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        assert tuple(reader.fieldnames or ()) == tuple(columns)
        return list(reader)


def write_manifest(path: Path, rows: Sequence[Sequence[str]]) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(MANIFEST_COLUMNS)
    for row in rows:
        writer.writerow(row)
    data = buf.getvalue().encode("utf-8")
    path.write_bytes(data)
    return data


def manifest_row(item_id: str, object_type: str, grade: str, second: int = 0) -> list[str]:
    folder = grade or "_"
    stamp = f"20261020T1000{second:02d}Z"
    return [
        f"raw/{object_type}/{folder}/{item_id}__0__{stamp}.jpg",
        item_id,
        object_type,
        grade,
        "a",
        "0",
        f"2026-10-20T10:00:{second:02d}Z",
        "seed",
        "",
    ]


def contributor_row(file: str, **changes: str) -> list[str]:
    row = dict(zip(PLAN_COLUMNS, (file, *CONTRIBUTOR_CELLS, CONTRIBUTOR_NOTES), strict=True))
    row.update(changes)
    return [row[c] for c in PLAN_COLUMNS]


def external_row(file: str, **changes: str) -> list[str]:
    row = dict(zip(PLAN_COLUMNS, (file, *EXTERNAL_CELLS, ""), strict=True))
    row.update(changes)
    return [row[c] for c in PLAN_COLUMNS]


@pytest.fixture
def env(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> Env:
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)  # a relative write would land in tmp_path, never in the repository
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    inbox = tmp_path / "entrada"
    inbox.mkdir()
    clock = Clock()
    return Env(
        tmp=tmp_path,
        capsys=capsys,
        caplog=caplog,
        dataset=tmp_path / "D",
        inbox=inbox,
        registry=tmp_path / "registro" / "external_sources.csv",
        plan=tmp_path / "plano.csv",
        clock=clock,
        sleep=SleepSpy(clock, 0.0),
    )


# =========================================================================== CA-01


def test_ca01_phone_photo_is_rotated_reduced_and_clean(env: Env) -> None:
    original = phone_photo()
    name = env.put("IMG_0001.jpg", original)
    env.write_plan([contributor_row(name)])

    r = env.run()

    assert r.code == 0, r.everything()
    image_path = f"raw/screw/fair/S-501__2__{STAMP0}.jpg"
    assert f"imported {name} -> {image_path}" in r.out_lines
    assert r.out_lines[-1] == "imported 1, skipped 0, failed 0"

    stored = env.dataset / image_path
    data = stored.read_bytes()
    assert data[:3] == b"\xff\xd8\xff"
    with Image.open(stored) as img:
        assert img.format == "JPEG"
        assert img.size == (960, 1280)
        assert len(img.getexif()) == 0
        corner = np.asarray(img.convert("RGB"), dtype=np.float64)[:100, :100].mean(axis=(0, 1))
    assert corner[0] > 180 and corner[1] < 70 and corner[2] < 70, corner
    assert jpeg_private_findings(data) == frozenset()
    assert not has_exif_rotation(data)
    assert b"Exif\x00\x00" not in data

    expected = load_image(original).resize((960, 1280), Image.Resampling.LANCZOS)
    diff = mean_abs_diff(load_image(stored), expected)
    assert (diff <= 4).all(), diff

    rows = env.manifest_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["image_path"] == image_path
    assert row["captured_at"] == "2026-10-22T14:15:03Z"
    assert row["capture_device"] == "qc-edge-import"
    assert row["labeler"] == "a"
    assert row["angle"] == "2"
    assert row["notes"] == CONTRIBUTOR_NOTES

    header = env.sources.read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(SOURCES_COLUMNS)
    sources = env.sources_rows()
    assert len(sources) == 1
    src = sources[0]
    assert src["image_path"] == image_path
    assert src["origin"] == "contributor"
    assert src["contributor"] == "c01"
    assert src["source_id"] == ""
    assert src["source_ref"] == ""
    assert src["input_sha256"] == hashlib.sha256((env.inbox / name).read_bytes()).hexdigest()


# =========================================================================== CA-02


def test_ca02_motion_photo_trailer_is_dropped(env: Env) -> None:
    name = env.put("motion.jpg", motion_photo())  # the helper checks the JPEG scans refusal
    env.write_plan([contributor_row(name)])

    r = env.run()

    assert r.code == 0, r.everything()
    [image] = env.images()
    data = (env.dataset / image).read_bytes()
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (1000, 750)
    assert b"ftypmp42" not in data
    assert jpeg_private_findings(data) == frozenset()


# =========================================================================== CA-03


def test_ca03_external_png_is_imported(env: Env) -> None:
    env.write_registry()
    name = env.put("0001.png", rgba_png())
    env.write_plan([external_row(name)])

    r = env.run()

    assert r.code == 0, r.everything()
    image_path = f"raw/screw/perfect/XS-0001__0__{STAMP0}.jpg"
    assert env.images() == [image_path]
    with Image.open(env.dataset / image_path) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
        assert img.size == (1280, 640)
    [src] = env.sources_rows()
    assert src["image_path"] == image_path
    assert src["origin"] == "external"
    assert src["contributor"] == ""
    assert src["source_id"] == "fonte-teste"
    assert src["source_ref"] == "dataset/train/0001.png"


# =========================================================================== CA-04

PlanBuilder = Callable[[Env], tuple[list[list[str]], int]]


def _ok(env: Env, name: str = "ok.jpg", seed: int = 11) -> str:
    return env.put(name, jpeg(seed=seed))


def _symlink_out(env: Env) -> str:
    outside = env.tmp / "fora"
    outside.mkdir()
    target = outside / "real.jpg"
    target.write_bytes(jpeg(seed=12))
    (env.inbox / "link.jpg").symlink_to(target)
    return "link.jpg"


def _sparse(env: Env) -> str:
    path = env.inbox / "big.jpg"
    with path.open("wb") as fh:
        fh.write(jpeg(seed=13))
    os.truncate(path, IMPORT_MAX_BYTES + 1)
    assert path.stat().st_size == IMPORT_MAX_BYTES + 1
    return "big.jpg"


def _absolute(env: Env) -> str:
    return str(env.inbox / _ok(env, "abs.jpg"))


def _parent_escape(env: Env) -> str:
    (env.tmp / "fora.jpg").write_bytes(jpeg(seed=14))
    return "../fora.jpg"


CA04_CASES: list[tuple[str, PlanBuilder, str, str]] = [
    ("file_parent", lambda e: ([contributor_row(_parent_escape(e))], 2), "invalid_file", "file"),
    ("file_absolute", lambda e: ([contributor_row(_absolute(e))], 2), "invalid_file", "file"),
    ("file_symlink", lambda e: ([contributor_row(_symlink_out(e))], 2), "invalid_file", "file"),
    ("file_missing", lambda e: ([contributor_row("nao-existe.jpg")], 2), "file_not_found", "file"),
    ("file_sparse_big", lambda e: ([contributor_row(_sparse(e))], 2), "file_too_large", "file"),
    (
        "item_short",
        lambda e: ([contributor_row(_ok(e), item_id="S-50")], 2),
        "invalid_item_id",
        "item_id",
    ),
    (
        "item_external_short",
        lambda e: ([external_row(_ok(e), item_id="XS-001")], 2),
        "invalid_item_id",
        "item_id",
    ),
    (
        "item_tool",
        lambda e: ([contributor_row(_ok(e), item_id="T-001", object_type="other", grade="")], 2),
        # SPEC-016 section 4.4: T- is accepted with a tool; with other it is a prefix mismatch.
        "item_prefix_mismatch",
        "object_type",
    ),
    (
        "item_external_tool",
        lambda e: ([external_row(_ok(e), item_id="XT-0001", object_type="other", grade="")], 2),
        # SPEC-016 section 4.4: XT- is accepted with a tool; with other it is a prefix mismatch.
        "item_prefix_mismatch",
        "object_type",
    ),
    (
        "item_prefix",
        lambda e: ([contributor_row(_ok(e), item_id="N-501")], 2),
        "item_prefix_mismatch",
        "object_type",
    ),
    (
        "item_type_conflict",
        lambda e: ([contributor_row(_ok(e), item_id="S-500")], 2),
        "item_type_conflict",
        "item_id",
    ),
    (
        "external_with_contributor_id",
        lambda e: ([external_row(_ok(e), item_id="S-501")], 2),
        "origin_item_mismatch",
        "item_id",
    ),
    (
        "contributor_with_external_id",
        lambda e: ([contributor_row(_ok(e), item_id="XS-0001", grade="perfect")], 2),
        "origin_item_mismatch",
        "item_id",
    ),
    (
        "contributor_code",
        lambda e: ([contributor_row(_ok(e), contributor="c1")], 2),
        "invalid_contributor",
        "contributor",
    ),
    (
        "unknown_source",
        lambda e: ([external_row(_ok(e), source_id="nao-registrada")], 2),
        "unknown_source_id",
        "source_id",
    ),
    (
        "license_nd",
        lambda e: (
            (
                e.write_registry(REGISTRY_LINE.replace(",CC-BY-4.0,", ",CC-BY-ND-4.0,")),
                [external_row(_ok(e))],
            )[1:]
            + (2,)
        ),
        "source_license_not_allowed",
        "source_id",
    ),
    (
        "license_nc_sa",
        lambda e: (
            (
                e.write_registry(REGISTRY_LINE.replace(",CC-BY-4.0,", ",CC-BY-NC-SA-4.0,")),
                [external_row(_ok(e))],
            )[1:]
            + (2,)
        ),
        "source_license_not_allowed",
        "source_id",
    ),
    (
        "external_empty_ref",
        lambda e: ([external_row(_ok(e), source_ref="")], 2),
        "invalid_source_ref",
        "source_ref",
    ),
    (
        "contributor_with_ref",
        lambda e: ([contributor_row(_ok(e), source_ref="dataset/x.png")], 2),
        "source_fields_mismatch",
        "source_ref",
    ),
    (
        "angle_newline",
        lambda e: ([contributor_row(_ok(e), angle="2\n")], 2),
        "invalid_angle",
        "angle",
    ),
    (
        "notes_line_separator",
        lambda e: ([contributor_row(_ok(e), notes="antes depois")], 2),
        "invalid_notes",
        "notes",
    ),
    (
        "grade_on_other",
        lambda e: (
            [contributor_row(_ok(e), item_id="O-501", object_type="other", grade="good")],
            2,
        ),
        "grade_on_other",
        "grade",
    ),
    (
        "duplicate_file",
        lambda e: (
            [contributor_row(_ok(e)), contributor_row("ok.jpg", angle="3")],
            3,
        ),
        "duplicate_file",
        "file",
    ),
    (
        "duplicate_input",
        lambda e: (
            [
                contributor_row(e.put("um.jpg", jpeg(seed=15))),
                contributor_row(e.put("dois.jpg", jpeg(seed=15)), angle="3"),
            ],
            3,
        ),
        "duplicate_input",
        "file",
    ),
]


def _ca04_dataset(env: Env) -> None:
    env.write_registry()
    write_manifest(env.manifest, [manifest_row("S-500", "nut", "fair")])


@pytest.mark.parametrize(
    ("builder", "code", "column"),
    [pytest.param(b, c, col, id=i) for i, b, c, col in CA04_CASES],
)
def test_ca04_invalid_plan_is_refused_and_nothing_written(
    env: Env, builder: PlanBuilder, code: str, column: str
) -> None:
    _ca04_dataset(env)
    rows, line = builder(env)
    env.write_plan(rows)
    before = env.snapshot()

    r = env.run()

    assert r.code == 2, r.everything()
    expected = f"plan line {line}: {code} ({column})"
    assert expected in r.err_lines, r.err
    assert env.snapshot() == before


def test_ca04_plan_without_notes_column(env: Env) -> None:
    _ca04_dataset(env)
    name = _ok(env)
    env.write_plan([contributor_row(name)[:-1]], header=PLAN_COLUMNS[:-1])
    before = env.snapshot()

    r = env.run()

    assert r.code == 2, r.everything()
    assert "plan line 1: missing_column (notes)" in r.err_lines, r.err
    assert env.snapshot() == before


def test_ca04_bidi_source_ref_is_never_echoed(env: Env) -> None:
    _ca04_dataset(env)
    marker = new_marker("accref")
    env.write_plan([external_row(_ok(env), source_ref=marker + "‮")])
    before = env.snapshot()

    r = env.run()

    assert r.code == 2, r.everything()
    assert "plan line 2: invalid_source_ref (source_ref)" in r.err_lines, r.err
    assert marker not in r.out
    assert marker not in r.err
    assert marker not in r.log
    assert env.snapshot() == before


# =========================================================================== CA-05


def _seed_dataset(env: Env) -> None:
    write_manifest(env.manifest, [manifest_row("S-500", "nut", "fair")])


def test_ca05a_missing_privacy_checked(env: Env) -> None:
    env.plan = env.tmp / "plano-inexistente.csv"
    r = env.run(env.argv(privacy=False))
    assert r.code == 2
    assert "missing --privacy-checked" in r.err
    assert any(
        line.endswith(
            "missing --privacy-checked: check every photo by eye first "
            "(docs/dataset-protocol.md section 10.5)"
        )
        for line in r.err_lines
    ), r.err
    assert not env.dataset.exists()


def test_ca05b_unknown_argument_is_not_echoed(env: Env) -> None:
    _seed_dataset(env)
    env.write_plan([contributor_row(_ok(env))])
    before = env.snapshot()
    marker = new_marker("acctok")

    r = env.run(env.argv(f"--token={marker}"))

    assert r.code == 2
    assert marker not in r.out
    assert marker not in r.err
    assert marker not in r.log
    assert env.snapshot() == before


def test_ca05c_inbox_inside_the_dataset(env: Env) -> None:
    _seed_dataset(env)
    inner = env.dataset / "entrada"
    inner.mkdir()
    (inner / "a.jpg").write_bytes(jpeg(seed=21))
    env.inbox = inner
    env.write_plan([contributor_row("a.jpg")])
    before = env.snapshot()

    r = env.run()

    assert r.code == 2
    assert "inbox must be outside the dataset" in r.err
    assert env.snapshot() == before


def test_ca05d_dataset_inside_the_inbox(env: Env) -> None:
    env.dataset = env.inbox / "D"
    _seed_dataset(env)
    env.write_plan([contributor_row(_ok(env))])
    before = env.snapshot(env.inbox)

    r = env.run()

    assert r.code == 2
    assert "inbox must be outside the dataset" in r.err
    assert env.snapshot(env.inbox) == before


def test_ca05e_registry_not_found(env: Env) -> None:
    _seed_dataset(env)
    env.write_plan([external_row(_ok(env))])
    before = env.snapshot()

    r = env.run(env.argv(registry=env.tmp / "nao-existe" / "external_sources.csv"))

    assert r.code == 2
    assert "external sources registry not found" in r.err
    assert env.snapshot() == before


def test_ca05f_manifest_header_mismatch(env: Env) -> None:
    env.dataset.mkdir()
    env.manifest.write_text("image_path,item_id\n", encoding="utf-8")
    env.write_plan([contributor_row(_ok(env))])
    before = env.snapshot()

    r = env.run()

    assert r.code == 2
    assert "manifest header mismatch" in r.err
    assert env.snapshot() == before


def test_ca05g_sources_header_mismatch(env: Env) -> None:
    _seed_dataset(env)
    env.sources.write_text("image_path,origin\n", encoding="utf-8")
    env.write_plan([contributor_row(_ok(env))])
    before = env.snapshot()

    r = env.run()

    assert r.code == 2
    assert "sources header mismatch" in r.err
    assert env.snapshot() == before


# =========================================================================== CA-06


def test_ca06_rejected_images_do_not_stop_the_import(env: Env) -> None:
    first = env.put("um.jpg", jpeg(800, 600, seed=31))
    heic = env.put("x.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 100)
    small = env.put("pequena.jpg", jpeg(300, 200, seed=32))
    last = env.put("quatro.jpg", jpeg(800, 600, seed=33))
    env.write_plan(
        [
            contributor_row(first, angle="0"),
            contributor_row(heic, angle="1"),
            contributor_row(small, angle="2"),
            contributor_row(last, angle="3"),
        ]
    )

    r = env.run()

    assert r.code == 1, r.everything()
    assert "failed x.heic: unsupported image" in r.out_lines
    assert f"failed {small}: image too small" in r.out_lines
    imported = [line for line in r.out_lines if line.startswith("imported ") and "->" in line]
    assert len(imported) == 2
    assert r.out_lines[-1] == "imported 2, skipped 0, failed 2"
    assert len(env.manifest_rows()) == 2
    assert len(env.sources_rows()) == 2
    files = {str(p.relative_to(env.dataset)) for p in env.dataset.rglob("*") if p.is_file()}
    allowed = {"manifest.csv", "sources.csv", "manifest.csv.lock", *env.images()}
    assert files <= allowed, files - allowed
    assert len(env.images()) == 2
    assert not any(Path(f).name.startswith(".") or f.endswith(".tmp") for f in files)


# =========================================================================== CA-07


def test_ca07_rerun_skips_and_excluded_image_is_imported_again(env: Env) -> None:
    env.write_registry()
    name = env.put("0001.png", rgba_png())
    env.write_plan([external_row(name)])
    assert env.run().code == 0
    first_path = f"raw/screw/perfect/XS-0001__0__{STAMP0}.jpg"
    assert env.images() == [first_path]
    manifest_before = env.manifest.read_bytes()
    sources_before = env.sources.read_bytes()

    r = env.run()

    assert r.code == 0, r.everything()
    assert f"skipped {name}: already imported" in r.out_lines
    assert r.out_lines[-1] == "imported 0, skipped 1, failed 0"
    assert env.manifest.read_bytes() == manifest_before
    assert env.sources.read_bytes() == sources_before

    (env.dataset / first_path).unlink()
    (env.dataset / "exclusions.csv").write_text(
        f"image_path,reason\n{first_path},other\n", encoding="utf-8"
    )
    env.clock.now = T0  # the same instant of the first import
    env.sleep = SleepSpy(env.clock, 1.0)

    r = env.run()

    assert r.code == 0, r.everything()
    second_path = f"raw/screw/perfect/XS-0001__0__{STAMP1}.jpg"
    assert f"imported {name} -> {second_path}" in r.out_lines
    assert env.images() == [second_path]
    paths = [row["image_path"] for row in env.manifest_rows()]
    assert len(paths) == len(set(paths)) == 2
    assert second_path in paths


# =========================================================================== CA-08


def test_ca08_same_name_waits_one_second(env: Env) -> None:
    env.sleep = SleepSpy(env.clock, 1.0)
    a = env.put("a.jpg", jpeg(seed=41))
    b = env.put("b.jpg", jpeg(seed=42))
    env.write_plan([contributor_row(a, angle="0"), contributor_row(b, angle="0")])

    r = env.run()

    assert r.code == 0, r.everything()
    first = f"raw/screw/fair/S-501__0__{STAMP0}.jpg"
    second = f"raw/screw/fair/S-501__0__{STAMP1}.jpg"
    assert env.images() == [first, second]
    assert f"imported {b} -> {second}" in r.out_lines
    assert env.sleep.calls == [1.0]


def test_ca08_clock_that_never_moves(env: Env) -> None:
    env.sleep = SleepSpy(env.clock, 0.0)
    a = env.put("a.jpg", jpeg(seed=41))
    b = env.put("b.jpg", jpeg(seed=42))
    env.write_plan([contributor_row(a, angle="0"), contributor_row(b, angle="0")])

    r = env.run()

    assert r.code == 1, r.everything()
    assert f"failed {b}: capture already exists" in r.out_lines
    assert len(env.sleep.calls) == 2
    assert env.images() == [f"raw/screw/fair/S-501__0__{STAMP0}.jpg"]


# =========================================================================== CA-09


def _fd_name(fd: int) -> str:
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return ""


def _enospc_on(monkeypatch: pytest.MonkeyPatch, file_name: str) -> list[int]:
    hits: list[int] = []
    real_write = os.write

    def spy(fd: int, data: Any) -> int:
        if _fd_name(fd).endswith("/" + file_name):
            hits.append(fd)
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", spy)
    return hits


def raw_files(env: Env) -> dict[str, bytes]:
    """Every file (images and temporaries, hidden ones included) under ``raw/``."""
    raw = env.dataset / "raw"
    return {str(p.relative_to(raw)): p.read_bytes() for p in raw.rglob("*") if p.is_file()}


def _first_external_import(env: Env) -> None:
    env.write_registry()
    env.put("0001.png", rgba_png())
    env.write_plan([external_row("0001.png")])
    assert env.run().code == 0
    env.clock.advance(1)


def test_ca09_sources_write_failure_rolls_back(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    _first_external_import(env)
    env.write_plan([contributor_row(env.put("c.jpg", jpeg(seed=51)))])
    manifest_before = env.manifest.read_bytes()
    sources_before = env.sources.read_bytes()
    raw_before = raw_files(env)
    hits = _enospc_on(monkeypatch, "sources.csv")

    r = env.run()

    assert hits, "the spy never saw a write to sources.csv"
    assert r.code == 1, r.everything()
    assert env.manifest.read_bytes() == manifest_before
    assert raw_files(env) == raw_before  # no image nor temporary (empty dirs may stay)
    assert env.sources.read_bytes() == sources_before


def test_ca09_manifest_write_failure_removes_the_image(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _first_external_import(env)
    env.write_plan([contributor_row(env.put("c.jpg", jpeg(seed=52)))])
    manifest_before = env.manifest.read_bytes()
    sources_before = env.sources.read_bytes()
    raw_before = raw_files(env)
    hits = _enospc_on(monkeypatch, "manifest.csv")

    r = env.run()

    assert hits, "the spy never saw a write to manifest.csv"
    assert r.code == 1, r.everything()
    assert raw_files(env) == raw_before  # no image nor temporary (empty dirs may stay)
    assert env.sources.read_bytes() == sources_before
    assert env.manifest.read_bytes() == manifest_before


# =========================================================================== CA-10


def _ca10_plan(env: Env) -> None:
    env.write_registry()
    env.write_plan(
        [
            contributor_row(env.put("c.jpg", jpeg(seed=61))),
            external_row(env.put("0001.png", rgba_png())),
        ]
    )


def _run_with_umask(env: Env, umask: int) -> Result:
    old = os.umask(umask)
    try:
        return env.run()
    finally:
        os.umask(old)


@pytest.mark.parametrize("umask", [0o022, 0o277], ids=["umask022", "umask277"])
def test_ca10_exact_modes_whatever_the_umask(env: Env, umask: int) -> None:
    _ca10_plan(env)
    assert not env.dataset.exists()

    r = _run_with_umask(env, umask)

    assert r.code == 0, r.everything()
    d = env.dataset
    for directory in (d, d / "raw", d / "raw/screw", d / "raw/screw/fair", d / "raw/screw/perfect"):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700, directory
    images = env.images()
    assert len(images) == 2
    for name in (*images, "manifest.csv", "sources.csv", "manifest.csv.lock"):
        assert stat.S_IMODE((d / name).stat().st_mode) == 0o600, name


def test_ca10_existing_dataset_dir_keeps_its_mode(env: Env) -> None:
    _ca10_plan(env)
    env.dataset.mkdir()
    os.chmod(env.dataset, 0o755)

    r = _run_with_umask(env, 0o022)

    assert r.code == 0, r.everything()
    assert stat.S_IMODE(env.dataset.stat().st_mode) == 0o755


# =========================================================================== CA-11


def _no_socket(*args: Any, **kwargs: Any) -> Any:
    raise OSError(errno.ENETUNREACH, "network disabled by the acceptance test")


def _privacy(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    capsys.readouterr()
    try:
        code = qc_edge.privacy.main(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    return code, capsys.readouterr().out


def test_ca11_no_network_inputs_untouched_and_privacy_clean(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.write_registry()
    phone = env.put("IMG_0001.jpg", phone_photo())
    motion = env.put("motion.jpg", motion_photo())
    png = env.put("0001.png", rgba_png())
    inputs = {
        p: ((env.inbox / p).read_bytes(), (env.inbox / p).stat().st_mtime_ns)
        for p in (phone, motion, png)
    }
    real_socket = socket.socket
    monkeypatch.setattr(socket, "socket", _no_socket)

    for row in (contributor_row(phone), contributor_row(motion), external_row(png)):
        env.write_plan([row])
        r = env.run()
        assert r.code == 0, r.everything()
        env.clock.advance(1)

    monkeypatch.setattr(socket, "socket", real_socket)
    code, out = _privacy(["--dataset-dir", str(env.dataset)], env.capsys)
    assert code == 0, out
    assert out.splitlines()[-1] == "checked 3 images, 0 with private data"
    for p, (data, mtime) in inputs.items():
        assert (env.inbox / p).read_bytes() == data
        assert (env.inbox / p).stat().st_mtime_ns == mtime


# =========================================================================== CA-12


def test_ca12_dry_run_creates_nothing(env: Env) -> None:
    env.write_registry()
    env.write_plan(
        [
            contributor_row(env.put("IMG_0001.jpg", phone_photo())),
            contributor_row(env.put("motion.jpg", motion_photo())),
            external_row(env.put("0001.png", rgba_png())),
        ]
    )

    r = env.run(env.argv("--dry-run"))

    assert r.code == 0, r.everything()
    assert len([line for line in r.out_lines if line.startswith("would import ")]) == 4
    assert sum(1 for line in r.out_lines if re.fullmatch(r"would import \S+", line)) == 3
    assert r.out_lines[-1] == "would import 3, skipped 0, failed 0"
    assert not env.dataset.exists()


# =========================================================================== CA-13


@pytest.fixture
def edge_app_env(env: Env, monkeypatch: pytest.MonkeyPatch) -> Env:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EDGE_DATA_DIR", str(env.tmp / "edge-data"))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", secrets.token_urlsafe(30))
    monkeypatch.setenv("DATASET_DIR", str(env.dataset))
    return env


def _console(app: Any) -> httpx.Response:
    port = EdgeSettings().EDGE_PORT

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url=f"http://127.0.0.1:{port}") as c:
            return await c.get("/")

    return asyncio.run(go())


def test_ca13_coverage_ignores_external_images(edge_app_env: Env) -> None:
    env = edge_app_env
    rows = [manifest_row("S-001", "screw", "perfect", s) for s in range(3)]
    rows += [manifest_row(f"XS-{i:04d}", "screw", "perfect", 10 + i) for i in range(1, 6)]
    write_manifest(env.manifest, rows)

    cells = {(c.object_type, c.grade): c for c in compute_coverage(env.manifest)}
    cell = cells[("screw", "perfect")]
    assert (cell.images, cell.items) == (3, 1)
    assert count_external_images(env.manifest) == 5

    page = _console(create_app(EdgeSettings(), None, InMemorySink()))
    assert page.status_code == 200, page.text
    match = re.search(r'<p id="external-images">(.*?)</p>', page.text, re.S)
    assert match, page.text
    assert re.search(r"(?<!\d)5(?!\d)", match.group(1))


# =========================================================================== CA-14


def test_ca14_collect_route_refuses_an_external_item_id(edge_app_env: Env) -> None:
    env = edge_app_env
    token = os.environ["EDGE_SESSION_TOKEN"]
    app = create_app(EdgeSettings(), None, InMemorySink(), clock=env.clock)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post(
            "/api/capture",
            headers={"X-Session-Token": token, "User-Agent": "acceptance-phone"},
            data={
                "mode": "collect",
                "item_id": "XS-0001",
                "object_type": "screw",
                "grade": "fair",
                "labeler": "a",
                "angle": "2",
                "notes": CONTRIBUTOR_NOTES,
            },
            files={"image": ("foto.jpg", jpeg(64, 48, seed=71), "image/jpeg")},
        )
    assert r.status_code == 422, r.text
    assert env.images() == []
    assert not env.manifest.exists() or env.manifest_rows() == []


# =========================================================================== CA-15


def test_ca15_formats_equal_to_qc_ml(env: Env) -> None:
    data = pytest.importorskip("qc_ml.data")
    import qc_edge.collect

    assert qc_edge.importer.SOURCES_COLUMNS == data.SOURCE_COLUMNS
    assert qc_edge.importer.ALLOWED_LICENSES == data.ALLOWED_LICENSES
    assert qc_edge.collect.MANIFEST_COLUMNS == data.MANIFEST_COLUMNS

    env.write_registry()
    for row in (
        contributor_row(env.put("IMG_0001.jpg", phone_photo())),
        external_row(env.put("0001.png", rgba_png())),
    ):
        env.write_plan([row])
        assert env.run().code == 0
        env.clock.advance(1)

    df = data.load_manifest(env.dataset, external_sources=env.registry)
    origins = dict(zip(df["item_id"], df["origin"], strict=True))
    assert origins == {"S-501": "contributor", "XS-0001": "external"}


# =========================================================================== CA-16


def _section(markdown: str, title_part: str) -> str:
    lines = markdown.splitlines()
    in_fence = False
    start = level = None
    for index, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = re.match(r"(#{1,6})\s+(.*)", line)
        if not heading:
            continue
        depth = len(heading.group(1))
        if start is None:
            if title_part in heading.group(2):
                start, level = index, depth
        elif depth <= (level or 0):
            return "\n".join(lines[start:index])
    assert start is not None, f"no section with {title_part!r}"
    return "\n".join(lines[start:])


def test_ca16_readme_section() -> None:
    text = (EDGE_ROOT / "README.md").read_text(encoding="utf-8")
    section = _section(text, "Importar fotos de fora da página")
    for needle in (
        "python -m qc_edge.importer",
        "--privacy-checked",
        "--dry-run",
        "sources.csv",
        "python -m qc_edge.privacy",
        "dataset-protocol.md",
    ):
        assert needle in section, needle


# =========================================================================== extras: images


@pytest.mark.parametrize("orientation", range(1, 9))
def test_extra_every_exif_orientation_matches_exif_transpose(env: Env, orientation: int) -> None:
    original = encode(
        textured(600, 400, 80 + orientation), "JPEG", quality=95, exif=gps_exif(orientation)
    )
    assert exif_orientation(original) == orientation
    assert has_exif_rotation(original) == (orientation in range(2, 9))
    env.write_plan([contributor_row(env.put("o.jpg", original))])

    r = env.run()

    assert r.code == 0, r.everything()
    [image] = env.images()
    stored = env.dataset / image
    expected = load_image(original)  # exif_transpose applied by the project loader
    got = load_image(stored)
    assert got.size == expected.size
    assert (mean_abs_diff(got, expected) <= 4).all()
    assert not has_exif_rotation(stored.read_bytes())


def test_extra_exif_orientation_absent_or_out_of_range_is_one() -> None:
    assert exif_orientation(jpeg(64, 48)) == 1
    for bad in (0, 9, 300):
        data = encode(textured(64, 48, 5), "JPEG", quality=90, exif=gps_exif(bad))
        assert exif_orientation(data) == 1
        assert not has_exif_rotation(data)


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((2000, 1001), (1280, 641)),
        ((1001, 2000), (641, 1280)),
        ((1281, 1000), (1280, 999)),
        ((1280, 960), (1280, 960)),
        ((1280, 256), (1280, 256)),
        ((2560, 513), (1280, 257)),  # 512.5 -> rounds half up (integer arithmetic)
    ],
)
def test_extra_reduction_integer_rounding(
    env: Env, size: tuple[int, int], expected: tuple[int, int]
) -> None:
    env.write_plan([contributor_row(env.put("r.jpg", jpeg(*size, seed=90)))])
    r = env.run()
    assert r.code == 0, r.everything()
    [image] = env.images()
    with Image.open(env.dataset / image) as img:
        assert img.size == expected


def test_extra_short_side_255_after_reduction_is_too_small(env: Env) -> None:
    # 2560x510 -> 1280x255 (below the 256 of preprocessing.json)
    name = env.put("fina.jpg", jpeg(2560, 510, seed=91))
    env.write_plan([contributor_row(name)])
    r = env.run()
    assert r.code == 1
    assert f"failed {name}: image too small" in r.out_lines
    assert not env.dataset.exists() or env.images() == []


def _patch_sof(data: bytes, width: int, height: int) -> bytes:
    index = data.index(b"\xff\xc0")
    return data[: index + 5] + struct.pack(">HH", height, width) + data[index + 9 :]


def _patch_ihdr(data: bytes, width: int, height: int) -> bytes:
    index = data.index(b"IHDR")
    body = struct.pack(">II", width, height) + data[index + 12 : index + 17]
    crc = struct.pack(">I", zlib.crc32(b"IHDR" + body) & 0xFFFFFFFF)
    return data[: index + 4] + body + crc + data[index + 21 :]


@pytest.mark.parametrize(
    "kind",
    [
        "jpeg_huge_sof",
        "png_huge_ihdr",
        "truncated_jpeg",
        "garbage_jpeg_magic",
        "aspect_11_to_1",
        "gif",
        "empty",
    ],
)
def test_extra_hostile_images_fail_the_line_only(env: Env, kind: str) -> None:
    payloads = {
        "jpeg_huge_sof": lambda: _patch_sof(jpeg(64, 48, seed=92), 60000, 60000),
        "png_huge_ihdr": lambda: _patch_ihdr(encode(Image.new("L", (64, 48)), "PNG"), 50000, 50000),
        "truncated_jpeg": lambda: jpeg(800, 600, seed=93)[:5000],
        "garbage_jpeg_magic": lambda: b"\xff\xd8\xff" + secrets.token_bytes(4000),
        "aspect_11_to_1": lambda: jpeg(2816, 256, seed=94),
        "gif": lambda: encode(Image.new("P", (400, 400)), "GIF"),
        "empty": lambda: b"",
    }
    bad = env.put(f"bad-{kind}.jpg", payloads[kind]())
    good = env.put("good.jpg", jpeg(800, 600, seed=95))
    env.write_plan([contributor_row(bad, angle="0"), contributor_row(good, angle="1")])

    r = env.run()

    assert r.code == 1, r.everything()
    [failed] = [line for line in r.out_lines if line.startswith(f"failed {bad}: ")]
    reason = failed.split(": ", 1)[1]
    assert reason in {
        "unsupported image",
        "too many JPEG scans",
        "unsupported JPEG structure",
        "image too small",
    }, failed
    assert r.out_lines[-1] == "imported 1, skipped 0, failed 1"
    assert "Traceback" not in r.everything()
    assert len(env.images()) == 1


def test_extra_exactly_40_mib_with_zero_trailer_is_imported(env: Env) -> None:
    path = env.inbox / "grande.jpg"
    path.write_bytes(jpeg(800, 600, seed=96))
    os.truncate(path, IMPORT_MAX_BYTES)
    env.write_plan([contributor_row("grande.jpg")])

    r = env.run()

    assert r.code == 0, r.everything()
    [image] = env.images()
    data = (env.dataset / image).read_bytes()
    assert len(data) < MIB
    assert jpeg_private_findings(data) == frozenset()


@pytest.mark.parametrize("mode", ["L", "CMYK"])
def test_extra_grey_and_cmyk_jpeg(env: Env, mode: str) -> None:
    img = textured(800, 600, 97).convert(mode)
    env.write_plan([contributor_row(env.put("m.jpg", encode(img, "JPEG", quality=90)))])
    r = env.run()
    assert r.code == 0, r.everything()
    [image] = env.images()
    with Image.open(env.dataset / image) as out:
        assert out.size == (800, 600)
        assert out.mode in {"RGB", "L"}


def test_extra_no_metadata_in_the_output_or_on_disk(env: Env) -> None:
    env.write_plan([contributor_row(env.put("IMG_0001.jpg", phone_photo()))])
    r = env.run()
    assert r.code == 0
    blob = b"".join(p.read_bytes() for p in env.dataset.rglob("*") if p.is_file())
    assert PHONE_MAKE.encode() not in blob
    assert b"Exif" not in blob
    own_log = "\n".join(
        rec.getMessage() for rec in env.caplog.records if rec.name.startswith("qc_edge")
    )
    for text in ("47.25", PHONE_MAKE, "GPS", "Orientation"):
        assert text not in r.out
        assert text not in own_log


def test_extra_real_process_stderr_has_no_metadata(env: Env) -> None:
    """The CLI as a process (its own logging config): nothing of the EXIF on stdout/stderr."""
    import subprocess
    import sys

    env.write_plan([contributor_row(env.put("IMG_0001.jpg", phone_photo()))])
    proc = subprocess.run(
        [sys.executable, "-m", "qc_edge.importer", *env.argv()],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=env.tmp / "cwd",
    )
    assert proc.returncode == 0, proc.stderr
    for text in ("47.25", PHONE_MAKE, "GPS", "Orientation", str(env.tmp)):
        assert text not in proc.stdout
        assert text not in proc.stderr


def test_extra_other_without_grade_goes_to_underscore(env: Env) -> None:
    env.write_plan(
        [
            contributor_row(
                env.put("o.jpg", jpeg(seed=98)), item_id="O-501", object_type="other", grade=""
            )
        ]
    )
    r = env.run()
    assert r.code == 0, r.everything()
    assert env.images() == [f"raw/other/_/O-501__2__{STAMP0}.jpg"]
    assert env.manifest_rows()[0]["grade"] == ""


# =========================================================================== extras: plan


@pytest.mark.parametrize(
    "bad_file",
    ["./ok.jpg", "sub//ok.jpg", "sub\\ok.jpg", "", "a" * 252 + ".jpg", "sub/../ok.jpg", "/"],
    ids=["dot", "empty_component", "backslash", "empty", "256_chars", "dotdot_inside", "root"],
)
def test_extra_invalid_file_spellings(env: Env, bad_file: str) -> None:
    _ok(env)
    (env.inbox / "sub").mkdir()
    env.put("sub/ok.jpg", jpeg(seed=99))
    env.write_plan([contributor_row(bad_file)])
    r = env.run()
    assert r.code == 2, r.everything()
    assert "plan line 2: invalid_file (file)" in r.err_lines, r.err
    assert not env.dataset.exists()


def test_extra_255_chars_file_name_is_accepted(env: Env) -> None:
    name = "a" * 251 + ".jpg"
    assert len(name) == 255
    env.write_plan([contributor_row(env.put(name, jpeg(seed=100)))])
    r = env.run()
    assert r.code == 0, r.everything()


def test_extra_directory_symlink_component_leaving_the_inbox(env: Env) -> None:
    outside = env.tmp / "fora"
    outside.mkdir()
    (outside / "x.jpg").write_bytes(jpeg(seed=101))
    (env.inbox / "atalho").symlink_to(outside, target_is_directory=True)
    env.write_plan([contributor_row("atalho/x.jpg")])
    r = env.run()
    assert r.code == 2
    assert "plan line 2: invalid_file (file)" in r.err_lines, r.err


def test_extra_symlink_inside_the_inbox_is_refused_too(env: Env) -> None:
    target = env.inbox / "real.jpg"
    target.write_bytes(jpeg(seed=102))
    (env.inbox / "alias.jpg").symlink_to(target)
    env.write_plan([contributor_row("alias.jpg")])
    r = env.run()
    assert r.code == 2
    assert "plan line 2: invalid_file (file)" in r.err_lines, r.err


def test_extra_directory_as_file_is_invalid(env: Env) -> None:
    (env.inbox / "pasta.jpg").mkdir()
    env.write_plan([contributor_row("pasta.jpg")])
    r = env.run()
    assert r.code == 2
    assert "plan line 2: invalid_file (file)" in r.err_lines, r.err


def test_extra_fifo_as_file_never_blocks(env: Env) -> None:
    fifo = env.inbox / "fila.jpg"
    os.mkfifo(fifo)
    env.write_plan([contributor_row("fila.jpg")])
    box: dict[str, Result] = {}
    worker = threading.Thread(target=lambda: box.setdefault("r", env.run()), daemon=True)
    worker.start()
    worker.join(20)
    if worker.is_alive():  # unblock a reader stuck on open() and fail
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
        worker.join(5)
        pytest.fail("the importer blocked on a FIFO in the inbox")
    r = box["r"]
    assert r.code == 2
    assert "plan line 2: invalid_file (file)" in r.err_lines, r.err


def test_extra_hardlink_from_outside_is_a_regular_file(env: Env) -> None:
    """Observation: a hard link is a regular file inside the inbox (the SPEC only bans symlinks)."""
    outside = env.tmp / "fora"
    outside.mkdir()
    (outside / "h.jpg").write_bytes(jpeg(seed=103))
    os.link(outside / "h.jpg", env.inbox / "h.jpg")
    env.write_plan([contributor_row("h.jpg")])
    r = env.run()
    assert r.code == 0, r.everything()
    assert (outside / "h.jpg").read_bytes() == (env.inbox / "h.jpg").read_bytes()


@pytest.mark.parametrize(
    ("changes", "code", "column"),
    [
        ({"item_id": "S-５０１"}, "invalid_item_id", "item_id"),
        ({"angle": "٢"}, "invalid_angle", "angle"),
        ({"angle": " 2"}, "invalid_angle", "angle"),
        ({"angle": "5"}, "invalid_angle", "angle"),
        ({"contributor": "c٠١"}, "invalid_contributor", "contributor"),
        ({"contributor": "C01"}, "invalid_contributor", "contributor"),
        ({"labeler": "A"}, "invalid_labeler", "labeler"),
        ({"origin": "capture"}, "invalid_origin", "origin"),
        ({"object_type": "Screw"}, "invalid_object_type", "object_type"),
        ({"grade": ""}, "missing_grade", "grade"),
        ({"grade": "excellent"}, "invalid_grade", "grade"),
        ({"notes": "x" * 201}, "invalid_notes", "notes"),
        ({"notes": "tab\there"}, "invalid_notes", "notes"),
        ({"notes": "bidi‮abc"}, "invalid_notes", "notes"),
        ({"source_id": "fonte-teste"}, "source_fields_mismatch", "source_id"),
    ],
)
def test_extra_contributor_cell_rules(
    env: Env, changes: dict[str, str], code: str, column: str
) -> None:
    env.write_plan([contributor_row(_ok(env), **changes)])
    r = env.run()
    assert r.code == 2, r.everything()
    assert f"plan line 2: {code} ({column})" in r.err_lines, r.err


@pytest.mark.parametrize(
    ("changes", "code", "column"),
    [
        ({"source_id": "AB"}, "invalid_source_id", "source_id"),
        ({"source_id": ""}, "invalid_source_id", "source_id"),
        ({"source_ref": "r" * 201}, "invalid_source_ref", "source_ref"),
        ({"source_ref": "a­b"}, "invalid_source_ref", "source_ref"),
        ({"contributor": "c01"}, "invalid_contributor", "contributor"),
    ],
)
def test_extra_external_cell_rules(
    env: Env, changes: dict[str, str], code: str, column: str
) -> None:
    env.write_registry()
    env.write_plan([external_row(_ok(env), **changes)])
    r = env.run()
    assert r.code == 2, r.everything()
    assert f"plan line 2: {code} ({column})" in r.err_lines, r.err


def test_extra_source_ref_of_200_chars_is_accepted(env: Env) -> None:
    env.write_registry()
    env.write_plan([external_row(_ok(env), source_ref="r" * 200)])
    r = env.run()
    assert r.code == 0, r.everything()
    assert env.sources_rows()[0]["source_ref"] == "r" * 200


def test_extra_item_type_conflict_inside_the_plan(env: Env) -> None:
    env.write_plan(
        [
            contributor_row(_ok(env, "a.jpg", 104), item_id="O-777", object_type="other", grade=""),
            contributor_row(_ok(env, "b.jpg", 105), item_id="O-777", object_type="screw"),
        ]
    )
    r = env.run()
    assert r.code == 2
    problems = [line for line in r.err_lines if "item_type_conflict (item_id)" in line]
    assert problems, r.err


def test_extra_every_problem_is_listed_and_nothing_read_after(env: Env) -> None:
    env.write_plan(
        [
            contributor_row(_ok(env), labeler="z"),
            contributor_row("nao-existe.jpg", angle="9"),
        ]
    )
    r = env.run()
    assert r.code == 2
    for expected in (
        "plan line 2: invalid_labeler (labeler)",
        "plan line 3: file_not_found (file)",
        "plan line 3: invalid_angle (angle)",
    ):
        assert expected in r.err_lines, r.err


def test_extra_plan_structure_errors(env: Env) -> None:
    _ok(env)
    cases: list[tuple[bytes, str]] = []
    header = ",".join(PLAN_COLUMNS) + "\n"
    good = ",".join(contributor_row("ok.jpg")) + "\n"
    cases.append((("﻿" + header + good).encode(), r"plan line 1: missing_column \(file\)"))
    cases.append(
        ((header + good).encode("utf-16"), r"plan line 1: (unreadable_csv|missing_column) \(.+\)")
    )
    cases.append(
        (
            (header + good).encode("utf-8").replace(b"d\xc3\xbavida", b"d\xfavida"),
            r"plan line \d+: unreadable_csv \(-\)",
        )
    )
    cases.append(
        ((header + good.rstrip("\n") + ",extra\n").encode(), r"plan line 2: malformed_row \(-\)")
    )
    cases.append(
        ((header + ",".join(PLAN_COLUMNS[1:]) + "\n").encode(), r"plan line 2: malformed_row \(-\)")
    )
    shuffled = ",".join((PLAN_COLUMNS[1], PLAN_COLUMNS[0], *PLAN_COLUMNS[2:])) + "\n"
    cases.append(((shuffled + good).encode(), r"plan line 1: missing_column \(-\)"))
    cases.append(
        (
            (header.rstrip("\n") + ",extra\n" + good.rstrip("\n") + ",x\n").encode(),
            r"plan line 1: missing_column \(-\)",
        )
    )
    rows = "".join(
        ",".join(contributor_row("ok.jpg", angle=str(i % 5))) + "\n" for i in range(5001)
    )
    cases.append(((header + rows).encode(), r"plan line \d+: too_many_rows \(-\)"))
    cases.append(
        ((header + good + "#" * (5 * MIB)).encode(), r"plan line \d+: unreadable_csv \(-\)")
    )
    cases.append(
        (
            (header + good.replace("ok.jpg", "ok\x00.jpg")).encode(),
            r"plan line \d+: (unreadable_csv|invalid_file) \((-|file)\)",
        )
    )
    for content, pattern in cases:
        env.plan.write_bytes(content)
        r = env.run()
        assert r.code == 2, (pattern, r.everything()[:2000])
        assert any(re.fullmatch(pattern, line) for line in r.err_lines), (pattern, r.err[:2000])
        assert not env.dataset.exists()


def test_extra_exactly_5000_rows_is_not_too_many(env: Env) -> None:
    """5000 rows (all duplicate_file after the first) must not be refused as too_many_rows."""
    _ok(env)
    env.write_plan([contributor_row("ok.jpg") for _ in range(5000)])
    r = env.run()
    assert r.code == 2
    assert not any("too_many_rows" in line for line in r.err_lines)
    assert "plan line 5001: duplicate_file (file)" in r.err_lines


def test_extra_empty_plan_imports_nothing(env: Env) -> None:
    env.write_plan([])
    r = env.run()
    assert r.code == 0, r.everything()
    assert r.out_lines[-1] == "imported 0, skipped 0, failed 0"


def test_extra_formula_like_cells_are_stored_verbatim(env: Env) -> None:
    """Observation (SPEC section 7): spreadsheet formulas are not neutralised, only documented."""
    env.write_registry()
    env.write_plan(
        [
            contributor_row(_ok(env, "a.jpg", 106), notes='=HYPERLINK("x")'),
            external_row(_ok(env, "b.png", 107), source_ref="@SUM(1+1)"),
        ]
    )
    r = env.run()
    assert r.code == 0, r.everything()
    assert env.manifest_rows()[0]["notes"] == '=HYPERLINK("x")'
    assert env.sources_rows()[1]["source_ref"] == "@SUM(1+1)"


# =========================================================================== extras: echo, paths


@pytest.mark.parametrize(
    "name",
    ["esc\x1b[31m.jpg", "bidi\u202egpj.jpg", "nova\nlinha.jpg", "del\x7f.jpg", "cr\rx.jpg"],
    ids=["ansi", "rlo", "newline", "del", "cr"],
)
def test_extra_control_and_bidi_in_file_names_are_never_echoed_raw(env: Env, name: str) -> None:
    """Accepted (escaped echo) or refused as invalid_file: never a raw control/bidi character."""
    env.put(name, jpeg(seed=110))
    env.write_plan([contributor_row(name)])

    r = env.run()

    for ch in ("\x1b", "\u202e", "\x7f", "\r"):
        assert ch not in r.out and ch not in r.err, repr(r.everything())
    if r.code == 0:
        assert len(r.out_lines) == 2, r.out_lines
        assert re.fullmatch(r"imported \S.* -> raw/screw/fair/\S+\.jpg", r.out_lines[0])
        assert r.out_lines[1] == "imported 1, skipped 0, failed 0"
    else:
        assert r.code == 2, r.everything()
        assert "plan line 2: invalid_file (file)" in r.err_lines, r.err


def test_extra_output_never_has_absolute_paths_nor_cells(env: Env) -> None:
    env.write_registry()
    marker = new_marker("accnote")
    env.write_plan(
        [
            contributor_row(env.put("a.jpg", jpeg(seed=120)), notes=marker),
            contributor_row(env.put("b.jpg", jpeg(300, 200, seed=121)), angle="3"),
            external_row(env.put("c.png", rgba_png())),
        ]
    )
    r = env.run()
    assert r.code == 1
    assert str(env.tmp) not in r.everything()
    assert marker not in r.everything()
    assert "fonte-teste" not in r.out and "dataset/train/0001.png" not in r.out
    env.write_plan([contributor_row(str(env.inbox / "a.jpg"), notes=marker)])
    r = env.run()
    assert r.code == 2
    assert str(env.tmp) not in r.everything()
    assert marker not in r.everything()


def test_extra_unknown_positional_value_is_not_echoed(env: Env) -> None:
    marker = new_marker("accpos")
    for extra in (
        [marker],
        ["--x", marker],
        [f"--{marker}{marker}"],
        [f"--Token={marker}"],
        ["--dry-run=" + marker],
    ):
        r = env.run(env.argv(*extra))
        assert r.code == 2, extra
        assert marker not in r.everything(), extra


def test_extra_nothing_written_outside_dataset_dir(env: Env) -> None:
    env.write_registry()
    env.write_plan(
        [
            contributor_row(env.put("IMG_0001.jpg", phone_photo())),
            external_row(env.put("0001.png", rgba_png())),
        ]
    )
    outside_before = {k: v for k, v in env.snapshot(env.tmp).items() if not k.startswith("D")}
    inbox_mtime = env.inbox.stat().st_mtime_ns
    r = env.run()
    assert r.code == 0, r.everything()
    outside_after = {k: v for k, v in env.snapshot(env.tmp).items() if not k.startswith("D")}
    assert outside_after == outside_before
    assert env.inbox.stat().st_mtime_ns == inbox_mtime


def test_extra_inbox_or_dataset_through_symlinks(env: Env) -> None:
    _seed_dataset(env)
    inner = env.dataset / "entrada"
    inner.mkdir()
    link = env.tmp / "atalho-entrada"
    link.symlink_to(inner, target_is_directory=True)
    env.write_plan([])
    r = env.run(
        [
            "--dataset-dir",
            str(env.dataset),
            "--inbox",
            str(link),
            "--plan",
            str(env.plan),
            "--privacy-checked",
        ]
    )
    assert r.code == 2
    assert "inbox must be outside the dataset" in r.err
    dlink = env.tmp / "atalho-dataset"
    dlink.symlink_to(env.inbox, target_is_directory=True)
    r = env.run(
        [
            "--dataset-dir",
            str(dlink),
            "--inbox",
            str(env.inbox),
            "--plan",
            str(env.plan),
            "--privacy-checked",
        ]
    )
    assert r.code == 2
    assert "inbox must be outside the dataset" in r.err


def test_extra_existing_files_keep_their_modes(env: Env) -> None:
    env.dataset.mkdir(mode=0o750)
    os.chmod(env.dataset, 0o750)
    write_manifest(env.manifest, [manifest_row("S-500", "nut", "fair")])
    os.chmod(env.manifest, 0o640)
    env.write_plan([contributor_row(_ok(env))])
    r = env.run()
    assert r.code == 0, r.everything()
    assert stat.S_IMODE(env.dataset.stat().st_mode) == 0o750
    assert stat.S_IMODE(env.manifest.stat().st_mode) == 0o640
    assert stat.S_IMODE(env.sources.stat().st_mode) == 0o600
    assert len(env.manifest_rows()) == 2


def test_extra_sources_write_failure_without_previous_sources(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_manifest(env.manifest, [manifest_row("S-500", "nut", "fair")])
    manifest_before = env.manifest.read_bytes()
    env.write_plan([contributor_row(_ok(env))])
    hits = _enospc_on(monkeypatch, "sources.csv")
    r = env.run()
    assert hits
    assert r.code == 1
    assert env.manifest.read_bytes() == manifest_before
    assert env.images() == []
    assert not env.sources.exists() or env.sources.read_text(encoding="utf-8").count("\n") <= 1


def test_extra_io_failure_stops_and_rerun_resumes(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = [env.put(f"{i}.jpg", jpeg(seed=130 + i)) for i in range(3)]
    env.write_plan([contributor_row(n, angle=str(i)) for i, n in enumerate(names)])
    real_write = os.write

    def flaky(fd: int, data: Any) -> int:
        if _fd_name(fd).endswith("/manifest.csv") and b"S-501__1__" in bytes(data):
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", flaky)
    r = env.run()
    monkeypatch.setattr(os, "write", real_write)
    assert r.code == 1, r.everything()
    assert len(env.manifest_rows()) == len(env.sources_rows()) == len(env.images())
    imported_first = len(env.images())
    assert imported_first >= 1
    assert not any(line.startswith(f"imported {names[2]}") for line in r.out_lines)

    env.clock.advance(1)
    r = env.run()
    assert r.code == 0, r.everything()
    assert len(env.images()) == 3
    assert sum(1 for line in r.out_lines if line.endswith(": already imported")) == imported_first


def test_extra_dry_run_on_existing_dataset_changes_nothing(env: Env) -> None:
    env.write_plan([contributor_row(env.put("a.jpg", jpeg(seed=140)))])
    assert env.run().code == 0
    env.write_plan(
        [
            contributor_row("a.jpg"),
            contributor_row(env.put("b.jpg", jpeg(seed=141)), angle="4"),
            contributor_row(env.put("c.jpg", jpeg(200, 200, seed=142)), angle="1"),
        ]
    )
    before = env.snapshot()
    stats = {p: p.stat().st_mtime_ns for p in env.dataset.rglob("*")}
    r = env.run(env.argv("--dry-run"))
    assert r.code == 1, r.everything()
    assert "skipped a.jpg: already imported" in r.out_lines
    assert "would import b.jpg" in r.out_lines
    assert "failed c.jpg: image too small" in r.out_lines
    assert r.out_lines[-1] == "would import 1, skipped 1, failed 1"
    assert env.snapshot() == before
    assert {p: p.stat().st_mtime_ns for p in env.dataset.rglob("*")} == stats


# =========================================================================== extras: concurrency


def test_extra_concurrent_collect_route_and_import(edge_app_env: Env) -> None:
    env = edge_app_env
    names = [env.put(f"i{i}.jpg", jpeg(seed=150 + i)) for i in range(5)]
    env.write_plan([contributor_row(n, angle=str(i)) for i, n in enumerate(names)])
    token = os.environ["EDGE_SESSION_TOKEN"]
    app = create_app(EdgeSettings(), None, InMemorySink(), clock=Clock(T0 + timedelta(hours=1)))
    box: dict[str, Result] = {}
    statuses: list[int] = []
    with TestClient(app, raise_server_exceptions=False) as client:
        worker = threading.Thread(target=lambda: box.setdefault("r", env.run()))
        worker.start()
        for i in range(5):
            resp = client.post(
                "/api/capture",
                headers={"X-Session-Token": token, "User-Agent": "acceptance-phone"},
                data={
                    "mode": "collect",
                    "item_id": f"S-60{i}",
                    "object_type": "screw",
                    "grade": "good",
                    "labeler": "b",
                    "angle": "0",
                    "notes": "",
                },
                files={"image": ("f.jpg", jpeg(64, 48, seed=160 + i), "image/jpeg")},
            )
            statuses.append(resp.status_code)
        worker.join(60)
    assert box["r"].code == 0, box["r"].everything()
    assert statuses.count(200) + statuses.count(503) == 5, statuses
    rows = env.manifest_rows()
    assert len(rows) == 5 + statuses.count(200)
    assert env.manifest.read_text(encoding="utf-8").count("image_path,") == 1
    for row in rows:
        assert (env.dataset / row["image_path"]).is_file()
    manifest_paths = {row["image_path"] for row in rows}
    assert {s["image_path"] for s in env.sources_rows()} <= manifest_paths
    assert len(env.sources_rows()) == 5


def test_extra_module_entry_point_requires_privacy_flag(env: Env) -> None:
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "qc_edge.importer",
            "--dataset-dir",
            str(env.dataset),
            "--inbox",
            str(env.inbox),
            "--plan",
            str(env.plan),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=env.tmp,
    )
    assert proc.returncode == 2
    assert "missing --privacy-checked" in proc.stderr
    assert not env.dataset.exists()


@pytest.mark.parametrize("mode", ["I;16", "P", "LA", "1", "RGB"])
def test_extra_png_modes_become_rgb_jpeg(env: Env, mode: str) -> None:
    base = textured(700, 500, 170)
    if mode == "I;16":
        img = base.convert("L").point(lambda v: v * 256).convert("I;16")
    elif mode == "P":
        img = base.convert("P", palette=Image.Palette.ADAPTIVE)
        img.info["transparency"] = 0
    else:
        img = base.convert(mode)
    kwargs: dict[str, Any] = {"transparency": 0} if mode == "P" else {}
    env.write_plan([contributor_row(env.put("p.png", encode(img, "PNG", **kwargs)))])
    r = env.run()
    assert r.code == 0, r.everything()
    [image] = env.images()
    with Image.open(env.dataset / image) as out:
        assert out.format == "JPEG"
        assert out.size == (700, 500)
        assert out.mode in {"RGB", "L"}


def test_extra_inbox_must_exist_and_exclusions_header(env: Env) -> None:
    env.write_plan([])
    r = env.run(
        [
            "--dataset-dir",
            str(env.dataset),
            "--inbox",
            str(env.tmp / "nao-existe"),
            "--plan",
            str(env.plan),
            "--privacy-checked",
        ]
    )
    assert r.code == 2
    assert not env.dataset.exists()
    _seed_dataset(env)
    (env.dataset / "exclusions.csv").write_text("image_path\n", encoding="utf-8")
    before = env.snapshot()
    r = env.run()
    assert r.code == 2
    assert env.snapshot() == before
