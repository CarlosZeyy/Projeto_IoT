"""``python -m qc_edge.importer`` (SPEC-036): plan validation, normalisation, writing, rollback.

Every image is generated here by Pillow (R-14); the dataset, the inbox and the registry live in
``tmp_path``. Only the boundaries are replaced: the clock, ``sleep``, ``socket.socket`` and the
low-level write that fails.
"""

from __future__ import annotations

import csv
import errno
import hashlib
import io
import logging
import os
import secrets
import socket
import stat
import struct
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageOps, TiffImagePlugin

from qc_edge import importer, privacy
from qc_edge import jpeg as jpeg_module
from qc_edge.collect import MANIFEST_COLUMNS, compute_coverage
from qc_edge.importer import (
    ALLOWED_LICENSES,
    IMPORT_MAX_BYTES,
    PLAN_COLUMNS,
    SOURCES_COLUMNS,
    ImageRejectedError,
    normalize_imported_image,
    reduced_size,
)
from qc_edge.jpeg import has_exif_rotation, jpeg_private_findings
from qc_preprocess import InvalidImageError, load_image

NOW = datetime(2026, 10, 22, 14, 15, 3, tzinfo=UTC)
REGISTRY_ROW = (
    "fonte-teste",
    "Fonte de teste",
    "https://example.org/fonte",
    "CC-BY-4.0",
    "https://creativecommons.org/licenses/by/4.0/",
    "Fonte de teste (example.org)",
    "2026-10-20",
)
REGISTRY_HEADER = (
    "source_id",
    "title",
    "url",
    "license",
    "license_url",
    "attribution",
    "retrieved_at",
)
GPS_LATITUDE = ((22, 1), (54, 1), (3021, 100))
CONTRIBUTOR = {
    "item_id": "S-501",
    "object_type": "screw",
    "grade": "fair",
    "labeler": "a",
    "angle": "2",
    "origin": "contributor",
    "contributor": "c01",
    "source_id": "",
    "source_ref": "",
    "notes": "dúvida fair/poor",
}
EXTERNAL = {
    "item_id": "XS-0001",
    "object_type": "screw",
    "grade": "perfect",
    "labeler": "b",
    "angle": "0",
    "origin": "external",
    "contributor": "",
    "source_id": "fonte-teste",
    "source_ref": "dataset/train/0001.png",
    "notes": "",
}


# ------------------------------------------------------------------------------------ helpers


class Clock:
    """Fake clock; ``sleep`` records the calls and, with ``advance``, moves the clock."""

    def __init__(self, *, advance: bool = True) -> None:
        self.now = NOW
        self.advance = advance
        self.sleeps: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if self.advance:
            self.now += timedelta(seconds=seconds)


def encode(image: Image.Image, fmt: str = "JPEG", **save: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **save)
    return buffer.getvalue()


def gps_orientation_exif(orientation: int | None) -> bytes:
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    exif[0x8825] = {1: "S", 2: tuple(TiffImagePlugin.IFDRational(*p) for p in GPS_LATITUDE)}
    return exif.tobytes()


def phone_photo() -> bytes:
    """Displayed 3000x4000 (red top-left quadrant), stored 4000x3000 with ``Orientation=6``."""
    shown = Image.new("RGB", (3000, 4000), (128, 128, 128))
    shown.paste((220, 30, 30), (0, 0, 1500, 2000))
    stored = shown.transpose(Image.Transpose.ROTATE_90)
    return encode(stored, quality=90, exif=gps_orientation_exif(6))


def noise(size: tuple[int, int], seed: int = 3) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8), "RGB")


def plain_jpeg(size: tuple[int, int] = (800, 600), color: tuple[int, int, int] = (90, 120, 150)):
    return encode(Image.new("RGB", size, color), quality=90)


def segment(marker: int, payload: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


def write_csv(path: Path, header: tuple[str, ...] | list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def snapshot(root: Path) -> dict[str, bytes | None]:
    if not root.exists():
        return {}
    return {
        p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.inbox = tmp_path / "inbox"
        self.inbox.mkdir()
        self.dataset = tmp_path / "dataset"
        self.plan = tmp_path / "plan.csv"
        self.registry = tmp_path / "external_sources.csv"
        write_csv(self.registry, REGISTRY_HEADER, [list(REGISTRY_ROW)])
        self.clock = Clock()

    def add_file(self, name: str, data: bytes) -> str:
        path = self.inbox / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return name

    def write_plan(self, rows: list[dict[str, str]], header: tuple[str, ...] = PLAN_COLUMNS):
        write_csv(self.plan, header, [[row.get(c, "") for c in header] for row in rows])

    def run(self, *extra: str, privacy_checked: bool = True, **kwargs: Any) -> int:
        argv = [
            "--dataset-dir",
            str(self.dataset),
            "--inbox",
            str(self.inbox),
            "--plan",
            str(self.plan),
            "--external-sources",
            str(self.registry),
            *extra,
        ]
        if privacy_checked:
            argv.append("--privacy-checked")
        kwargs.setdefault("clock", self.clock)
        kwargs.setdefault("sleep", self.clock.sleep)
        return importer.main(argv, **kwargs)

    def manifest(self) -> list[dict[str, str]]:
        return read_rows(self.dataset / "manifest.csv")

    def sources(self) -> list[dict[str, str]]:
        return read_rows(self.dataset / "sources.csv")


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def restore_umask() -> Iterator[None]:
    original = os.umask(0o022)
    os.umask(original)
    try:
        yield
    finally:
        os.umask(original)


def contributor_row(name: str, /, **changes: str) -> dict[str, str]:
    return {"file": name, **CONTRIBUTOR, **changes}


def external_row(name: str, /, **changes: str) -> dict[str, str]:
    return {"file": name, **EXTERNAL, **changes}


# ----------------------------------------------------------------------------- normalisation


def test_phone_photo_is_rotated_reduced_and_clean() -> None:
    original = phone_photo()
    output, width, height = normalize_imported_image(original)
    assert (width, height) == (960, 1280)
    assert output.startswith(b"\xff\xd8\xff")
    assert jpeg_private_findings(output) == frozenset()
    assert not has_exif_rotation(output)
    assert b"Exif\x00\x00" not in output
    with Image.open(io.BytesIO(output)) as image:
        assert image.size == (960, 1280)
        assert len(image.getexif()) == 0
        assert image.info.get("icc_profile") is None
        assert not image.info.get("progressive")
    pixels = np.asarray(load_image(output), dtype=np.int16)
    red = pixels[:100, :100].reshape(-1, 3).mean(axis=0)
    assert red[0] > 180 and red[1] < 70 and red[2] < 70
    reference = load_image(original).resize((960, 1280), Image.Resampling.LANCZOS)
    diff = np.abs(pixels - np.asarray(reference, dtype=np.int16)).reshape(-1, 3).mean(axis=0)
    assert (diff <= 4).all()


@pytest.mark.parametrize("orientation", range(1, 9))
def test_rotation_table_matches_exif_transpose(orientation: int) -> None:
    source = noise((320, 280))
    data = encode(source, quality=95, exif=gps_orientation_exif(orientation))
    output, width, height = normalize_imported_image(data)
    with Image.open(io.BytesIO(data)) as raw:
        expected = ImageOps.exif_transpose(raw).convert("RGB")
    assert (width, height) == expected.size
    got = np.asarray(load_image(output), dtype=np.int16)
    diff = np.abs(got - np.asarray(expected, dtype=np.int16)).mean()
    assert diff < 8  # only the JPEG re-encode separates them
    assert importer.ORIENTATION_TRANSPOSE.get(orientation) is {
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_270,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_90,
    }.get(orientation)


def test_orientation_only_in_the_xmp_is_applied() -> None:
    base = encode(noise((400, 300)), quality=95)
    xmp = segment(0xE1, b'http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta tiff:Orientation="6"/>')
    data = base[:2] + xmp + base[2:]
    _, width, height = normalize_imported_image(data)
    assert (width, height) == (300, 400)


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((4000, 3000), (1280, 960)),
        ((3000, 4000), (960, 1280)),
        ((1280, 700), (1280, 700)),
        ((900, 1280), (900, 1280)),
        ((2000, 2000), (1280, 1280)),
        ((3001, 2000), (1280, (2000 * 1280 + 3001 // 2) // 3001)),
        ((2048, 1024), (1280, 640)),
        ((1281, 1000), (1280, 999)),  # 999.21... rounds down
        ((1283, 1001), (1280, 999)),  # (1001 * 1280 + 641) // 1283 = 999
    ],
)
def test_reduced_size_integer_rounding(size: tuple[int, int], expected: tuple[int, int]) -> None:
    assert reduced_size(*size) == expected


def test_reduced_size_rounds_half_up() -> None:
    # 1000 * 1280 / 2560 = 500 exactly; 1001 * 1280 / 2560 = 500.5 -> 501 (half up).
    assert reduced_size(2560, 1000) == (1280, 500)
    assert reduced_size(2560, 1001) == (1280, 501)


@pytest.mark.parametrize("size", [(300, 200), (2560, 500), (255, 255)])
def test_image_too_small(size: tuple[int, int]) -> None:
    with pytest.raises(ImageRejectedError) as excinfo:
        normalize_imported_image(plain_jpeg(size))
    assert excinfo.value.reason == "image too small"


def test_smallest_side_of_256_is_accepted() -> None:
    _, width, height = normalize_imported_image(plain_jpeg((2560, 512)))
    assert (width, height) == (1280, 256)


def test_motion_photo_trailer_is_dropped_before_load_image() -> None:
    base = encode(noise((1000, 750)), quality=90, exif=gps_orientation_exif(1))
    data = base + b"\x00\x00\x00\x18ftypmp42" + b"\xff\xda" * 100 + b"\x00" * (1024 * 1024)
    with pytest.raises(InvalidImageError, match="JPEG scans"):
        load_image(data)
    output, width, height = normalize_imported_image(data)
    assert (width, height) == (1000, 750)
    assert b"ftypmp42" not in output
    assert jpeg_private_findings(output) == frozenset()


def test_png_rgba_becomes_rgb_jpeg() -> None:
    data = encode(Image.new("RGBA", (2048, 1024), (10, 200, 30, 128)), "PNG")
    output, width, height = normalize_imported_image(data)
    assert (width, height) == (1280, 640)
    with Image.open(io.BytesIO(output)) as image:
        assert image.format == "JPEG" and image.mode == "RGB"


def test_icc_profile_is_not_copied() -> None:
    data = encode(noise((600, 400)), quality=90, icc_profile=b"\x00" * 128)
    output, _, _ = normalize_imported_image(data)
    assert b"ICC_PROFILE" not in output


@pytest.mark.parametrize(
    "data",
    [b"\x00\x00\x00\x18ftypheic" + b"\x00" * 100, b"GIF89a" + b"\x00" * 50, b""],
)
def test_unsupported_images(data: bytes) -> None:
    with pytest.raises(ImageRejectedError) as excinfo:
        normalize_imported_image(data)
    assert excinfo.value.reason == "unsupported image"


def test_too_many_scans_after_the_cleaning() -> None:
    base = encode(noise((600, 400)), quality=90)
    # An APP2 is kept by the structural cleaning, so these markers still count (SPEC-011 sec. 7).
    data = base[:2] + segment(0xE2, b"\xff\xda" * 70) + base[2:]
    with pytest.raises(ImageRejectedError) as excinfo:
        normalize_imported_image(data)
    assert excinfo.value.reason == "too many JPEG scans"


@pytest.mark.parametrize("data", [b"\xff\xd8\xff\xe1\x00", b"\xff\xd8\xff\xe0\x00\x10JFIF"])
def test_unsupported_jpeg_structure(data: bytes) -> None:
    with pytest.raises(ImageRejectedError) as excinfo:
        normalize_imported_image(data)
    assert excinfo.value.reason == "unsupported JPEG structure"


@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("jpeg_private_findings", frozenset({"com"})),
        ("has_exif_rotation", True),
    ],
)
def test_normalization_check_failed(
    monkeypatch: pytest.MonkeyPatch, target: str, value: object
) -> None:
    monkeypatch.setattr(jpeg_module, target, lambda data: value)
    with pytest.raises(ImageRejectedError) as excinfo:
        normalize_imported_image(encode(Image.new("RGB", (600, 400)), "PNG"))
    assert excinfo.value.reason == "normalization check failed"


def test_normalization_check_compares_the_size(monkeypatch: pytest.MonkeyPatch) -> None:
    output = plain_jpeg((300, 300))
    assert importer._output_is_clean(output, (300, 300)) is True
    monkeypatch.setattr(importer, "load_image", lambda data: Image.new("RGB", (10, 10)))
    assert importer._output_is_clean(output, (300, 300)) is False


# ----------------------------------------------------------------------------- the CLI: runs


def test_contributor_photo_is_imported(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    original = phone_photo()
    env.add_file("foto.jpg", original)
    env.write_plan([contributor_row("foto.jpg")])
    assert env.run() == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "imported foto.jpg -> raw/screw/fair/S-501__2__20261022T141503Z.jpg",
        "imported 1, skipped 0, failed 0",
    ]
    stored = env.dataset / "raw/screw/fair/S-501__2__20261022T141503Z.jpg"
    assert Image.open(stored).size == (960, 1280)
    (manifest_row,) = env.manifest()
    assert manifest_row == {
        "image_path": "raw/screw/fair/S-501__2__20261022T141503Z.jpg",
        "item_id": "S-501",
        "object_type": "screw",
        "grade": "fair",
        "labeler": "a",
        "angle": "2",
        "captured_at": "2026-10-22T14:15:03Z",
        "capture_device": "qc-edge-import",
        "notes": "dúvida fair/poor",
    }
    lines = (env.dataset / "sources.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(SOURCES_COLUMNS)
    (source,) = env.sources()
    assert source == {
        "image_path": manifest_row["image_path"],
        "origin": "contributor",
        "contributor": "c01",
        "source_id": "",
        "source_ref": "",
        "input_sha256": hashlib.sha256(original).hexdigest(),
    }


def test_external_png_is_imported(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.add_file("ext/0001.png", encode(Image.new("RGBA", (2048, 1024), (1, 2, 3, 4)), "PNG"))
    env.write_plan([external_row("ext/0001.png")])
    assert env.run() == 0
    stored = env.dataset / "raw/screw/perfect/XS-0001__0__20261022T141503Z.jpg"
    with Image.open(stored) as image:
        assert (image.format, image.mode, image.size) == ("JPEG", "RGB", (1280, 640))
    (source,) = env.sources()
    assert (source["origin"], source["contributor"], source["source_id"]) == (
        "external",
        "",
        "fonte-teste",
    )
    assert source["source_ref"] == "dataset/train/0001.png"
    assert "imported 1, skipped 0, failed 0" in capsys.readouterr().out


def test_other_without_grade_goes_to_the_underscore_directory(env: Env) -> None:
    env.add_file("o.jpg", plain_jpeg())
    env.write_plan([contributor_row("o.jpg", item_id="O-501", object_type="other", grade="")])
    assert env.run() == 0
    assert (env.dataset / "raw/other/_/O-501__2__20261022T141503Z.jpg").is_file()
    assert env.manifest()[0]["grade"] == ""


TOOLS = ("pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver")


def test_tools_are_imported_with_t_and_xt(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    """SPEC-016 section 4.4: ``T-`` (contributor) and ``XT-`` (external), each with its grade."""
    env.add_file("chave.jpg", plain_jpeg(color=(10, 20, 30)))
    env.add_file("ext/alicate.png", encode(Image.new("RGB", (900, 700), (40, 50, 60)), "PNG"))
    env.write_plan(
        [
            contributor_row(
                "chave.jpg", item_id="T-501", object_type="flat_screwdriver", grade="good"
            ),
            external_row("ext/alicate.png", item_id="XT-0001", object_type="pliers", grade="fair"),
        ]
    )
    assert env.run() == 0
    assert capsys.readouterr().out.splitlines()[-1] == "imported 2, skipped 0, failed 0"
    assert [(r["item_id"], r["object_type"], r["grade"]) for r in env.manifest()] == [
        ("T-501", "flat_screwdriver", "good"),
        ("XT-0001", "pliers", "fair"),
    ]
    assert [r["image_path"] for r in env.manifest()] == [
        "raw/flat_screwdriver/good/T-501__2__20261022T141503Z.jpg",
        "raw/pliers/fair/XT-0001__0__20261022T141503Z.jpg",
    ]
    assert [(r["origin"], r["source_id"]) for r in env.sources()] == [
        ("contributor", ""),
        ("external", "fonte-teste"),
    ]
    for row in env.manifest():
        assert (env.dataset / row["image_path"]).is_file()


@pytest.mark.parametrize("tool", TOOLS)
def test_every_tool_is_accepted_with_t(env: Env, tool: str) -> None:
    env.add_file("t.jpg", plain_jpeg())
    env.write_plan([contributor_row("t.jpg", item_id="T-502", object_type=tool, grade="poor")])
    assert env.run() == 0
    assert env.manifest()[0]["object_type"] == tool


def test_xt_with_screw_is_refused_and_nothing_is_written(
    seeded: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    """CA-11 of SPEC-016: the third line (``XT-0002`` ``screw``) has the prefix problem."""
    seeded.add_file("a.jpg", plain_jpeg(color=(1, 2, 3)))
    seeded.add_file("b.jpg", plain_jpeg(color=(4, 5, 6)))
    seeded.write_plan(
        [
            contributor_row(
                "ok.jpg", item_id="T-501", object_type="flat_screwdriver", grade="good"
            ),
            external_row("a.jpg", item_id="XT-0001", object_type="pliers", grade="fair"),
            external_row("b.jpg", item_id="XT-0002", object_type="screw", grade="good"),
        ]
    )
    _expect_plan_problem(seeded, capsys, 4, "item_prefix_mismatch", "object_type")


def test_rerun_skips_and_excluded_image_is_imported_again(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.add_file("a.png", encode(Image.new("RGB", (2048, 1024)), "PNG"))
    env.write_plan([external_row("a.png")])
    assert env.run() == 0
    manifest_before = (env.dataset / "manifest.csv").read_bytes()
    sources_before = (env.dataset / "sources.csv").read_bytes()
    capsys.readouterr()

    assert env.run() == 0
    assert capsys.readouterr().out.splitlines() == [
        "skipped a.png: already imported",
        "imported 0, skipped 1, failed 0",
    ]
    assert (env.dataset / "manifest.csv").read_bytes() == manifest_before
    assert (env.dataset / "sources.csv").read_bytes() == sources_before

    first = env.manifest()[0]["image_path"]
    (env.dataset / first).unlink()
    write_csv(env.dataset / "exclusions.csv", ("image_path", "reason"), [[first, "other"]])
    env.clock.now = NOW
    assert env.run() == 0
    paths = [row["image_path"] for row in env.manifest()]
    assert len(paths) == 2 and len(set(paths)) == 2
    assert paths[1] == "raw/screw/perfect/XS-0001__0__20261022T141504Z.jpg"
    assert env.clock.sleeps == [1.0]
    assert (env.dataset / paths[1]).is_file()


def test_same_name_waits_one_second(env: Env) -> None:
    env.add_file("a.jpg", plain_jpeg())
    env.add_file("b.jpg", plain_jpeg(color=(10, 10, 10)))
    env.write_plan([contributor_row("a.jpg", angle="0"), contributor_row("b.jpg", angle="0")])
    assert env.run() == 0
    names = sorted(p.name for p in (env.dataset / "raw/screw/fair").iterdir())
    assert names == ["S-501__0__20261022T141503Z.jpg", "S-501__0__20261022T141504Z.jpg"]
    assert env.clock.sleeps == [1.0]


def test_name_still_taken_after_three_attempts(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.clock.advance = False
    env.add_file("a.jpg", plain_jpeg())
    env.add_file("b.jpg", plain_jpeg(color=(10, 10, 10)))
    env.write_plan([contributor_row("a.jpg", angle="0"), contributor_row("b.jpg", angle="0")])
    assert env.run() == 1
    out = capsys.readouterr().out.splitlines()
    assert "failed b.jpg: capture already exists" in out
    assert out[-1] == "imported 1, skipped 0, failed 1"
    assert env.clock.sleeps == [1.0, 1.0]
    assert len(env.manifest()) == 1 and len(env.sources()) == 1


def test_rejected_images_do_not_stop_the_import(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.add_file("1.jpg", plain_jpeg())
    env.add_file("x.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 100)
    env.add_file("3.jpg", plain_jpeg((300, 200)))
    env.add_file("4.jpg", plain_jpeg(color=(1, 1, 1)))
    env.write_plan(
        [
            contributor_row("1.jpg", angle="0"),
            contributor_row("x.heic", angle="1"),
            contributor_row("3.jpg", angle="2"),
            contributor_row("4.jpg", angle="3"),
        ]
    )
    assert env.run() == 1
    out = capsys.readouterr().out.splitlines()
    assert "failed x.heic: unsupported image" in out
    assert "failed 3.jpg: image too small" in out
    assert (
        sum(line.startswith("imported 1.jpg") or line.startswith("imported 4.jpg") for line in out)
        == 2
    )
    assert out[-1] == "imported 2, skipped 0, failed 2"
    assert len(env.manifest()) == 2 and len(env.sources()) == 2
    assert not [p for p in env.dataset.rglob("*") if p.name.endswith(".tmp")]


def test_dry_run_creates_nothing(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.add_file("a.jpg", phone_photo())
    env.add_file("b.png", encode(Image.new("RGB", (2048, 1024)), "PNG"))
    env.add_file("c.jpg", plain_jpeg((300, 200)))
    env.write_plan([contributor_row("a.jpg"), external_row("b.png"), contributor_row("c.jpg")])
    assert env.run("--dry-run") == 1
    assert capsys.readouterr().out.splitlines() == [
        "would import a.jpg",
        "would import b.png",
        "failed c.jpg: image too small",
        "would import 2, skipped 0, failed 1",
    ]
    assert not env.dataset.exists()


def test_dry_run_on_an_existing_dataset_changes_nothing(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.add_file("a.jpg", plain_jpeg())
    env.write_plan([contributor_row("a.jpg")])
    assert env.run() == 0
    env.add_file("b.jpg", plain_jpeg(color=(5, 5, 5)))
    env.write_plan([contributor_row("a.jpg"), contributor_row("b.jpg", angle="1")])
    before = snapshot(env.dataset)
    capsys.readouterr()
    assert env.run("--dry-run") == 0
    assert capsys.readouterr().out.splitlines() == [
        "skipped a.jpg: already imported",
        "would import b.jpg",
        "would import 1, skipped 1, failed 0",
    ]
    assert snapshot(env.dataset) == before


def test_printed_file_names_are_escaped(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    name = "a‮b.jpg"
    env.add_file(name, plain_jpeg())
    env.write_plan([contributor_row(name)])
    assert env.run() == 0
    out = capsys.readouterr().out
    assert "‮" not in out
    assert "imported a\\u202eb.jpg -> raw/" in out


def test_inputs_are_never_changed_and_no_network(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_network(*args: object, **kwargs: object) -> None:
        raise OSError("network disabled in this test")

    monkeypatch.setattr(socket, "socket", no_network)
    env.add_file("a.jpg", phone_photo())
    env.add_file("b.png", encode(Image.new("RGB", (2048, 1024)), "PNG"))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in env.inbox.iterdir()}
    env.write_plan([contributor_row("a.jpg"), external_row("b.png")])
    assert env.run() == 0
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in env.inbox.iterdir()}
    assert after == before
    capsys.readouterr()
    assert privacy.main(["--dataset-dir", str(env.dataset)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "checked 2 images, 0 with private data"


@pytest.mark.parametrize("umask", [0o022, 0o277])
def test_modes_whatever_the_umask(env: Env, restore_umask: None, umask: int) -> None:
    env.add_file("a.jpg", plain_jpeg())
    env.add_file("b.png", encode(Image.new("RGB", (2048, 1024)), "PNG"))
    env.write_plan([contributor_row("a.jpg"), external_row("b.png")])
    os.umask(umask)
    assert env.run() == 0
    root = env.dataset
    dirs = [root, root / "raw", root / "raw/screw", root / "raw/screw/fair"]
    dirs.append(root / "raw/screw/perfect")
    for directory in dirs:
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700, directory
    files = [*root.glob("raw/screw/*/*.jpg"), root / "manifest.csv", root / "sources.csv"]
    files.append(root / "manifest.csv.lock")
    assert len(files) == 5
    for path in files:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path


def test_existing_dataset_dir_keeps_its_mode(env: Env, restore_umask: None) -> None:
    os.umask(0)
    env.dataset.mkdir(mode=0o755)
    env.add_file("a.jpg", plain_jpeg())
    env.write_plan([contributor_row("a.jpg")])
    assert env.run() == 0
    assert stat.S_IMODE(env.dataset.stat().st_mode) == 0o755


# ---------------------------------------------------------------------------- the CLI: rollback


def _fail_writes_to(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    real_write = os.write

    def write(fd: int, data: Any) -> int:
        if os.readlink(f"/proc/self/fd/{fd}").endswith("/" + name):
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", write)


@pytest.mark.parametrize("existing", [False, True])
def test_sources_write_failure_rolls_back_the_manifest(
    env: Env,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    existing: bool,
) -> None:
    if existing:
        env.add_file("first.jpg", plain_jpeg(color=(7, 7, 7)))
        env.write_plan([contributor_row("first.jpg", angle="4")])
        assert env.run() == 0
    manifest_before = snapshot(env.dataset).get("manifest.csv")
    sources_before = snapshot(env.dataset).get("sources.csv")
    images_before = sorted(env.dataset.glob("raw/**/*.jpg"))
    env.add_file("a.jpg", plain_jpeg())
    env.add_file("b.jpg", plain_jpeg(color=(9, 9, 9)))
    env.write_plan([contributor_row("a.jpg"), contributor_row("b.jpg", angle="1")])
    _fail_writes_to(monkeypatch, "sources.csv")
    capsys.readouterr()
    assert env.run() == 1
    out = capsys.readouterr().out.splitlines()
    assert out == ["failed a.jpg: failed to write dataset", "imported 0, skipped 0, failed 1"]
    assert snapshot(env.dataset).get("manifest.csv") == manifest_before
    assert snapshot(env.dataset).get("sources.csv") == sources_before
    assert sorted(env.dataset.glob("raw/**/*.jpg")) == images_before
    assert not [p for p in env.dataset.rglob("*") if p.name.endswith(".tmp")]


def test_manifest_write_failure_removes_the_image(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.add_file("first.jpg", plain_jpeg(color=(7, 7, 7)))
    env.write_plan([contributor_row("first.jpg", angle="4")])
    assert env.run() == 0
    before = snapshot(env.dataset)
    env.add_file("a.jpg", plain_jpeg())
    env.write_plan([contributor_row("a.jpg")])
    _fail_writes_to(monkeypatch, "manifest.csv")
    assert env.run() == 1
    assert snapshot(env.dataset) == before


def test_image_write_failure_stops(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    monkeypatch.setattr(importer, "write_private_file_atomically", broken)
    env.add_file("a.jpg", plain_jpeg())
    env.add_file("b.jpg", plain_jpeg(color=(3, 3, 3)))
    env.write_plan([contributor_row("a.jpg"), contributor_row("b.jpg", angle="1")])
    assert env.run() == 1
    assert not (env.dataset / "manifest.csv").exists()


def test_io_error_log_has_no_absolute_path(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    env.add_file("a.jpg", plain_jpeg())
    env.write_plan([contributor_row("a.jpg")])
    _fail_writes_to(monkeypatch, "sources.csv")
    with caplog.at_level(logging.INFO):
        assert env.run() == 1
    assert str(env.tmp) not in caplog.text


def test_header_changed_between_validation_and_writing_stops(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env.add_file("a.jpg", plain_jpeg())
    env.add_file("b.jpg", plain_jpeg(color=(4, 4, 4)))
    env.write_plan([contributor_row("a.jpg"), contributor_row("b.jpg", angle="1")])
    real = importer.normalize_imported_image
    calls = []

    def normalize(data: bytes) -> tuple[bytes, int, int]:
        calls.append(1)
        if len(calls) == 2:
            (env.dataset / "sources.csv").write_text("other,header\n", encoding="utf-8")
        return real(data)

    monkeypatch.setattr(importer, "normalize_imported_image", normalize)
    assert env.run() == 1
    out = capsys.readouterr().out.splitlines()
    assert out[1] == "failed b.jpg: sources header mismatch"
    assert len(env.manifest()) == 1


def test_item_type_registered_meanwhile_fails_the_row(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env.add_file("a.jpg", plain_jpeg())
    env.add_file("b.jpg", plain_jpeg(color=(4, 4, 4)))
    env.write_plan([contributor_row("a.jpg", item_id="S-600"), contributor_row("b.jpg")])
    real = importer.normalize_imported_image

    def normalize(data: bytes) -> tuple[bytes, int, int]:
        result = real(data)
        if not (env.dataset / "manifest.csv").exists():
            env.dataset.mkdir(exist_ok=True)
            write_csv(
                env.dataset / "manifest.csv",
                MANIFEST_COLUMNS,
                [["raw/nut/good/S-600__0__x.jpg", "S-600", "nut", "good", "a", "0", "", "", ""]],
            )
        return result

    monkeypatch.setattr(importer, "normalize_imported_image", normalize)
    assert env.run() == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "failed a.jpg: item_id already registered with another object_type"
    assert out[1].startswith("imported b.jpg -> ")


def test_input_changed_after_validation(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env.add_file("a.jpg", plain_jpeg())
    env.write_plan([contributor_row("a.jpg")])
    real = importer.load_plan

    def load_plan(**kwargs: Any) -> Any:
        rows = real(**kwargs)
        (env.inbox / "a.jpg").write_bytes(plain_jpeg(color=(0, 0, 0)))
        return rows

    monkeypatch.setattr(importer, "load_plan", load_plan)
    assert env.run() == 1
    assert "failed a.jpg: input changed since validation" in capsys.readouterr().out


# ---------------------------------------------------------------------- the CLI: plan problems


def _expect_plan_problem(
    env: Env, capsys: pytest.CaptureFixture[str], line: int, code: str, column: str
) -> None:
    before = snapshot(env.dataset)
    assert env.run() == 2
    captured = capsys.readouterr()
    assert f"plan line {line}: {code} ({column})" in captured.err.splitlines()
    assert captured.out == ""
    assert snapshot(env.dataset) == before


@pytest.fixture
def seeded(env: Env) -> Env:
    """A dataset with one hand-written manifest row (``S-500`` as ``nut``)."""
    env.dataset.mkdir()
    write_csv(
        env.dataset / "manifest.csv",
        MANIFEST_COLUMNS,
        [
            [
                "raw/nut/good/S-500__0__20261001T000000Z.jpg",
                "S-500",
                "nut",
                "good",
                "a",
                "0",
                "",
                "",
                "",
            ]
        ],
    )
    env.add_file("ok.jpg", plain_jpeg())
    return env


ROW_CASES: list[tuple[str, dict[str, str], str, str]] = [
    ("abs-not-allowed", {"file": "/etc/hostname"}, "invalid_file", "file"),
    ("dotdot", {"file": "../fora.jpg"}, "invalid_file", "file"),
    ("dot", {"file": "./ok.jpg"}, "invalid_file", "file"),
    ("empty-component", {"file": "a//ok.jpg"}, "invalid_file", "file"),
    ("backslash", {"file": "a\\ok.jpg"}, "invalid_file", "file"),
    ("empty", {"file": ""}, "invalid_file", "file"),
    ("long", {"file": "a" * 256}, "invalid_file", "file"),
    ("missing", {"file": "nao-existe.jpg"}, "file_not_found", "file"),
    ("short-id", {"item_id": "S-50"}, "invalid_item_id", "item_id"),
    ("ext-3-digits", {"item_id": "XS-001", "origin": "external"}, "invalid_item_id", "item_id"),
    ("tool-prefix-screw", {"item_id": "T-001"}, "item_prefix_mismatch", "object_type"),
    (
        "tool-prefix-other",
        {"item_id": "T-001", "object_type": "other", "grade": ""},
        "item_prefix_mismatch",
        "object_type",
    ),
    ("screw-prefix-tool", {"object_type": "pliers"}, "item_prefix_mismatch", "object_type"),
    (
        "tool-no-grade",
        {"item_id": "T-501", "object_type": "allen_key", "grade": ""},
        "missing_grade",
        "grade",
    ),
    ("ext-tools", {"item_id": "XT-0001"}, "origin_item_mismatch", "item_id"),
    ("prefix", {"item_id": "N-501"}, "item_prefix_mismatch", "object_type"),
    ("conflict-manifest", {"item_id": "S-500"}, "item_type_conflict", "item_id"),
    ("contrib-ext-id", {"item_id": "XS-0001"}, "origin_item_mismatch", "item_id"),
    ("bad-type", {"object_type": "bolt"}, "invalid_object_type", "object_type"),
    ("bad-grade", {"grade": "great"}, "invalid_grade", "grade"),
    ("no-grade", {"grade": ""}, "missing_grade", "grade"),
    (
        "grade-other",
        {"item_id": "O-501", "object_type": "other", "grade": "good"},
        "grade_on_other",
        "grade",
    ),
    ("labeler", {"labeler": "c"}, "invalid_labeler", "labeler"),
    ("angle-newline", {"angle": "2\n"}, "invalid_angle", "angle"),
    ("angle-5", {"angle": "5"}, "invalid_angle", "angle"),
    ("angle-arabic", {"angle": "٢"}, "invalid_angle", "angle"),
    ("origin", {"origin": "capture"}, "invalid_origin", "origin"),
    ("contributor", {"contributor": "c1"}, "invalid_contributor", "contributor"),
    ("contributor-empty", {"contributor": ""}, "invalid_contributor", "contributor"),
    ("contrib-source-id", {"source_id": "fonte-teste"}, "source_fields_mismatch", "source_id"),
    ("contrib-source-ref", {"source_ref": "x.png"}, "source_fields_mismatch", "source_ref"),
    ("notes-ls", {"notes": "a b"}, "invalid_notes", "notes"),
    ("notes-long", {"notes": "n" * 201}, "invalid_notes", "notes"),
]


@pytest.mark.parametrize(
    ("changes", "code", "column"), [c[1:] for c in ROW_CASES], ids=[c[0] for c in ROW_CASES]
)
def test_contributor_row_problems(
    seeded: Env,
    capsys: pytest.CaptureFixture[str],
    changes: dict[str, str],
    code: str,
    column: str,
) -> None:
    seeded.write_plan([contributor_row("ok.jpg", **changes)])
    _expect_plan_problem(seeded, capsys, 2, code, column)


EXTERNAL_CASES: list[tuple[str, dict[str, str], str, str]] = [
    ("own-id", {"item_id": "S-501"}, "origin_item_mismatch", "item_id"),
    ("contributor-filled", {"contributor": "c01"}, "invalid_contributor", "contributor"),
    ("unknown-source", {"source_id": "nao-registrada"}, "unknown_source_id", "source_id"),
    ("bad-source-id", {"source_id": "AB"}, "invalid_source_id", "source_id"),
    ("empty-source-id", {"source_id": ""}, "invalid_source_id", "source_id"),
    ("empty-ref", {"source_ref": ""}, "invalid_source_ref", "source_ref"),
    ("long-ref", {"source_ref": "r" * 201}, "invalid_source_ref", "source_ref"),
    ("bidi-ref", {"source_ref": "x‮"}, "invalid_source_ref", "source_ref"),
    ("ext-prefix", {"item_id": "XN-0001"}, "item_prefix_mismatch", "object_type"),
    ("ext-tool-screw", {"item_id": "XT-0002"}, "item_prefix_mismatch", "object_type"),
    (
        "ext-tool-no-grade",
        {"item_id": "XT-0003", "object_type": "pliers", "grade": ""},
        "missing_grade",
        "grade",
    ),
    (
        "ext-tool-short",
        {"item_id": "XT-001", "object_type": "pliers"},
        "invalid_item_id",
        "item_id",
    ),
]


@pytest.mark.parametrize(
    ("changes", "code", "column"),
    [c[1:] for c in EXTERNAL_CASES],
    ids=[c[0] for c in EXTERNAL_CASES],
)
def test_external_row_problems(
    seeded: Env,
    capsys: pytest.CaptureFixture[str],
    changes: dict[str, str],
    code: str,
    column: str,
) -> None:
    seeded.write_plan([external_row("ok.jpg", **changes)])
    _expect_plan_problem(seeded, capsys, 2, code, column)


@pytest.mark.parametrize("license_id", ["CC-BY-ND-4.0", "CC-BY-NC-SA-4.0", "CC-BY-SA-4.0", ""])
def test_registry_license_not_allowed(
    seeded: Env, capsys: pytest.CaptureFixture[str], license_id: str
) -> None:
    row = list(REGISTRY_ROW)
    row[3] = license_id
    write_csv(seeded.registry, REGISTRY_HEADER, [row])
    seeded.write_plan([external_row("ok.jpg")])
    _expect_plan_problem(seeded, capsys, 2, "source_license_not_allowed", "source_id")


def test_symlink_in_the_inbox(seeded: Env, capsys: pytest.CaptureFixture[str]) -> None:
    outside = seeded.tmp / "fora.jpg"
    outside.write_bytes(plain_jpeg())
    (seeded.inbox / "link.jpg").symlink_to(outside)
    (seeded.inbox / "inner.jpg").symlink_to(seeded.inbox / "ok.jpg")
    seeded.write_plan([contributor_row("link.jpg"), contributor_row("inner.jpg", angle="1")])
    _expect_plan_problem(seeded, capsys, 2, "invalid_file", "file")
    seeded.write_plan([contributor_row("inner.jpg")])
    _expect_plan_problem(seeded, capsys, 2, "invalid_file", "file")


def test_directory_symlink_leaving_the_inbox(
    seeded: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = seeded.tmp / "outside"
    outside.mkdir()
    (outside / "x.jpg").write_bytes(plain_jpeg())
    (seeded.inbox / "dir").symlink_to(outside, target_is_directory=True)
    seeded.write_plan([contributor_row("dir/x.jpg")])
    _expect_plan_problem(seeded, capsys, 2, "invalid_file", "file")


def test_directory_and_fifo_are_invalid(seeded: Env, capsys: pytest.CaptureFixture[str]) -> None:
    (seeded.inbox / "sub").mkdir()
    os.mkfifo(seeded.inbox / "pipe.jpg")
    seeded.write_plan([contributor_row("sub")])
    _expect_plan_problem(seeded, capsys, 2, "invalid_file", "file")
    seeded.write_plan([contributor_row("pipe.jpg")])
    _expect_plan_problem(seeded, capsys, 2, "invalid_file", "file")


def test_file_too_large_is_never_read(seeded: Env, capsys: pytest.CaptureFixture[str]) -> None:
    big = seeded.inbox / "big.jpg"
    with big.open("wb") as handle:
        handle.write(b"\xff\xd8\xff")
    os.truncate(big, IMPORT_MAX_BYTES + 1)
    seeded.write_plan([contributor_row("big.jpg")])
    _expect_plan_problem(seeded, capsys, 2, "file_too_large", "file")


def test_cross_row_problems(seeded: Env, capsys: pytest.CaptureFixture[str]) -> None:
    seeded.add_file("copy.jpg", (seeded.inbox / "ok.jpg").read_bytes())
    seeded.write_plan([contributor_row("ok.jpg"), contributor_row("ok.jpg", angle="1")])
    _expect_plan_problem(seeded, capsys, 3, "duplicate_file", "file")
    seeded.write_plan([contributor_row("ok.jpg"), contributor_row("copy.jpg", angle="1")])
    _expect_plan_problem(seeded, capsys, 3, "duplicate_input", "file")
    seeded.add_file("n.jpg", plain_jpeg(color=(1, 2, 3)))
    seeded.write_plan(
        [
            contributor_row("ok.jpg", item_id="O-777", object_type="other", grade=""),
            contributor_row("n.jpg", item_id="O-777", object_type="screw"),
        ]
    )
    before = snapshot(seeded.dataset)
    assert seeded.run() == 2
    err = capsys.readouterr().err.splitlines()
    assert "plan line 3: item_prefix_mismatch (object_type)" in err
    assert snapshot(seeded.dataset) == before


def test_item_type_conflict_inside_the_plan(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.add_file("a.jpg", plain_jpeg())
    env.add_file("b.jpg", plain_jpeg(color=(1, 2, 3)))
    env.add_file("c.jpg", plain_jpeg(color=(3, 2, 1)))
    env.write_plan(
        [
            external_row("a.jpg", item_id="XO-0001", object_type="other", grade=""),
            external_row("b.jpg", item_id="XO-0001", object_type="other", grade=""),
            external_row("c.jpg", item_id="XO-0001", object_type="screw"),
        ]
    )
    assert env.run() == 2
    err = capsys.readouterr().err.splitlines()
    assert "plan line 4: item_type_conflict (item_id)" in err
    assert "plan line 3: item_type_conflict (item_id)" not in err
    assert not env.dataset.exists()


def test_every_problem_is_listed_once_per_line(
    seeded: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    seeded.write_plan(
        [
            contributor_row("ok.jpg", labeler="z", angle="9"),
            contributor_row("nao.jpg", notes="\x00"),
        ]
    )
    assert seeded.run() == 2
    err = capsys.readouterr().err.splitlines()
    assert [line for line in err if line.startswith("plan line")] == [
        "plan line 2: invalid_labeler (labeler)",
        "plan line 2: invalid_angle (angle)",
        "plan line 3: file_not_found (file)",
        "plan line 3: invalid_notes (notes)",
    ]


def test_missing_column(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.add_file("a.jpg", plain_jpeg())
    env.write_plan([contributor_row("a.jpg")], header=PLAN_COLUMNS[:-1])
    _expect_plan_problem(env, capsys, 1, "missing_column", "notes")


def test_reordered_header(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.write_plan([], header=(PLAN_COLUMNS[1], PLAN_COLUMNS[0], *PLAN_COLUMNS[2:]))
    _expect_plan_problem(env, capsys, 1, "missing_column", "-")


def test_header_with_bom(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.plan.write_bytes(b"\xef\xbb\xbf" + ",".join(PLAN_COLUMNS).encode() + b"\n")
    _expect_plan_problem(env, capsys, 1, "missing_column", "file")


def test_plan_not_utf8(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.plan.write_bytes(",".join(PLAN_COLUMNS).encode() + b"\n\xff\xfe\n")
    _expect_plan_problem(env, capsys, 1, "unreadable_csv", "-")


def test_plan_above_5_mib(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.plan.write_bytes(",".join(PLAN_COLUMNS).encode() + b"\n" + b"#" * (5 * 1024 * 1024))
    _expect_plan_problem(env, capsys, 1, "unreadable_csv", "-")


def test_malformed_row(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.add_file("a.jpg", plain_jpeg())
    write_csv(env.plan, PLAN_COLUMNS, [["a.jpg", "S-501"]])
    _expect_plan_problem(env, capsys, 2, "malformed_row", "-")


def test_too_many_rows(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    write_csv(env.plan, PLAN_COLUMNS, [["x"] * len(PLAN_COLUMNS)] * 5001)
    _expect_plan_problem(env, capsys, 5002, "too_many_rows", "-")


def test_empty_plan_imports_nothing(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.write_plan([])
    assert env.run() == 0
    assert capsys.readouterr().out == "imported 0, skipped 0, failed 0\n"
    assert not env.dataset.exists()


def test_cell_values_are_never_echoed(
    seeded: Env, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    marker = "ref-" + secrets.token_hex(8)
    seeded.write_plan([external_row("ok.jpg", source_ref=marker + "‮")])
    with caplog.at_level(logging.DEBUG):
        assert seeded.run() == 2
    captured = capsys.readouterr()
    assert "plan line 2: invalid_source_ref (source_ref)" in captured.err
    assert marker not in captured.out + captured.err + caplog.text


# ---------------------------------------------------------------------- the CLI: usage errors


def test_privacy_checked_is_required_before_reading(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.plan = env.tmp / "nao-existe.csv"
    assert env.run(privacy_checked=False) == 2
    assert capsys.readouterr().err.startswith(
        "missing --privacy-checked: check every photo by eye first "
        "(docs/dataset-protocol.md section 10.5)"
    )
    assert not env.dataset.exists()


def test_unknown_argument_is_not_echoed(
    env: Env, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    marker = "tok-" + secrets.token_hex(8)
    env.write_plan([])
    with caplog.at_level(logging.DEBUG):
        assert env.run(f"--token={marker}") == 2
        assert env.run(marker) == 2
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err + caplog.text
    assert "--token" in caplog.text
    assert not env.dataset.exists()


@pytest.mark.parametrize("where", ["inside", "same", "contains"])
def test_inbox_must_be_outside_the_dataset(
    env: Env, capsys: pytest.CaptureFixture[str], where: str
) -> None:
    env.write_plan([])
    if where == "inside":
        env.inbox = env.dataset / "entrada"
        env.inbox.mkdir(parents=True)
    elif where == "same":
        env.dataset.mkdir()
        env.inbox = env.dataset
    else:
        env.dataset = env.inbox / "dataset"
    before = snapshot(env.tmp / "dataset")
    assert env.run() == 2
    assert "inbox must be outside the dataset" in capsys.readouterr().err
    assert snapshot(env.tmp / "dataset") == before


def test_inbox_through_a_symlink_into_the_dataset(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    (env.dataset / "entrada").mkdir(parents=True)
    link = env.tmp / "link"
    link.symlink_to(env.dataset / "entrada", target_is_directory=True)
    env.inbox = link
    env.write_plan([])
    assert env.run() == 2
    assert "inbox must be outside the dataset" in capsys.readouterr().err


def test_inbox_must_exist(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.inbox = env.tmp / "nao-existe"
    env.write_plan([])
    assert env.run() == 2
    assert "--inbox must be an existing directory" in capsys.readouterr().err


def test_dataset_dir_that_is_a_file(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.dataset.write_text("x", encoding="utf-8")
    env.write_plan([])
    assert env.run() == 2
    assert "--dataset-dir must be a directory" in capsys.readouterr().err


def test_registry_missing_only_matters_with_external_rows(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.registry = env.tmp / "nao-existe.csv"
    env.add_file("a.jpg", plain_jpeg())
    env.write_plan([contributor_row("a.jpg")])
    assert env.run("--dry-run") == 0
    env.write_plan([contributor_row("a.jpg"), external_row("a.jpg")])
    assert env.run() == 2
    assert "external sources registry not found" in capsys.readouterr().err
    assert not env.dataset.exists()


@pytest.mark.parametrize(
    "content",
    [
        b"source_id,title\nfonte-teste,x\n",
        b"\xef\xbb\xbf" + ",".join(REGISTRY_HEADER).encode() + b"\n",
        ",".join(REGISTRY_HEADER).encode() + b"\nfonte-teste,x\n",
        ",".join(REGISTRY_HEADER).encode() + b"\n" + (",".join(REGISTRY_ROW).encode() + b"\n") * 2,
    ],
)
def test_registry_unreadable(env: Env, capsys: pytest.CaptureFixture[str], content: bytes) -> None:
    env.registry.write_bytes(content)
    env.add_file("a.jpg", plain_jpeg())
    env.write_plan([external_row("a.jpg")])
    assert env.run() == 2
    assert "external sources registry unreadable" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("manifest.csv", b"image_path,item_id\n", "manifest header mismatch"),
        ("manifest.csv", b"", "manifest header mismatch"),
        ("sources.csv", b"image_path,origin\n", "sources header mismatch"),
        ("exclusions.csv", b"path\n", "exclusions header mismatch"),
        (
            "manifest.csv",
            ",".join(MANIFEST_COLUMNS).encode() + b"\n\xff\xfe\n",
            "manifest unreadable",
        ),
    ],
)
def test_dataset_headers(
    env: Env, capsys: pytest.CaptureFixture[str], name: str, content: bytes, message: str
) -> None:
    env.dataset.mkdir()
    (env.dataset / name).write_bytes(content)
    env.add_file("a.jpg", plain_jpeg())
    env.write_plan([contributor_row("a.jpg")])
    before = snapshot(env.dataset)
    assert env.run() == 2
    assert message in capsys.readouterr().err
    assert snapshot(env.dataset) == before


def test_help_exits_with_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        importer.main(["--help"])
    assert excinfo.value.code == 0
    assert "--privacy-checked" in capsys.readouterr().out


# ----------------------------------------------------------------------- formats and coverage


def test_default_registry_is_the_one_of_the_repository() -> None:
    root = Path(__file__).resolve().parents[2]
    assert root / "ml" / "external_sources.csv" == importer.DEFAULT_EXTERNAL_SOURCES
    assert importer.DEFAULT_EXTERNAL_SOURCES.is_file()


def test_formats_equal_to_qc_ml(env: Env) -> None:
    data = pytest.importorskip("qc_ml.data")
    assert SOURCES_COLUMNS == data.SOURCE_COLUMNS
    assert ALLOWED_LICENSES == data.ALLOWED_LICENSES
    assert MANIFEST_COLUMNS == data.MANIFEST_COLUMNS
    assert importer.EXTERNAL_SOURCES_COLUMNS == data.EXTERNAL_SOURCE_COLUMNS
    assert importer.EXCLUSIONS_COLUMNS == data.EXCLUSION_COLUMNS
    env.add_file("a.jpg", phone_photo())
    env.add_file("b.png", encode(Image.new("RGB", (2048, 1024)), "PNG"))
    env.write_plan([contributor_row("a.jpg"), external_row("b.png")])
    assert env.run() == 0
    frame = data.load_manifest(env.dataset, external_sources=env.registry)
    assert sorted(frame["origin"]) == ["contributor", "external"]


def test_imported_externals_stay_out_of_the_coverage(env: Env) -> None:
    env.add_file("a.jpg", plain_jpeg())
    env.add_file("b.png", encode(Image.new("RGB", (2048, 1024)), "PNG"))
    env.write_plan([contributor_row("a.jpg"), external_row("b.png")])
    assert env.run() == 0
    cells = {(c.object_type, c.grade): c for c in compute_coverage(env.dataset / "manifest.csv")}
    assert (cells["screw", "fair"].images, cells["screw", "fair"].items) == (1, 1)
    assert cells["screw", "perfect"].images == 0


def test_module_entry_point(env: Env, tmp_path: Path) -> None:
    import subprocess
    import sys

    env.write_plan([])
    result = subprocess.run(
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
            "--privacy-checked",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == "imported 0, skipped 0, failed 0\n"
