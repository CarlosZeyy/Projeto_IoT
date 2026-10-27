"""qc_edge.collect: validation, paths, manifest, permissions, lock and coverage (SPEC-010);
metadata removal, directory fsync and text filters (SPEC-025)."""

from __future__ import annotations

import csv
import errno
import io
import logging
import os
import stat
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from qc_contracts import GRADE_OPTIONAL_OBJECT_TYPES, Grade, ObjectType
from qc_edge import collect as collect_module
from qc_edge import jpeg as jpeg_module
from qc_edge.collect import (
    GRADED_DATASET_TYPES,
    ITEM_PREFIX_TYPES,
    MANIFEST_COLUMNS,
    TOOL_OBJECT_TYPES,
    CaptureExistsError,
    CollectRequest,
    DatasetObjectType,
    DatasetWriteError,
    DatasetWriter,
    ExifOrientationNotSupportedError,
    InvalidCollectFieldError,
    ItemTypeConflictError,
    ManifestHeaderMismatchError,
    ManifestUnreadableError,
    UnsupportedJpegStructureError,
    append_csv_row,
    capture_device_from_user_agent,
    compute_coverage,
    count_external_images,
    empty_coverage,
    item_prefix_matches,
    read_csv_rows,
    rollback_append,
)
from qc_edge.fsutil import fsync_dir
from qc_edge.jpeg import JpegStructureError, jpeg_private_findings, strip_private_segments
from qc_preprocess import load_image

NOW = datetime(2026, 10, 22, 14, 15, 3, tzinfo=UTC)
HEADER_LINE = ",".join(MANIFEST_COLUMNS) + "\n"
VALID = {
    "item_id": "S-012",
    "object_type": "screw",
    "grade": "fair",
    "labeler": "a",
    "angle": "2",
    "notes": "dúvida fair/poor",
}


def _fields(**changes: Any) -> dict[str, Any]:
    fields: dict[str, Any] = dict(VALID)
    for key, value in changes.items():
        if value is None:
            fields.pop(key, None)
        else:
            fields[key] = value
    return fields


def _request(**changes: Any) -> CollectRequest:
    return CollectRequest.from_fields(_fields(**changes))


def _encoded(fmt: str = "JPEG", size: tuple[int, int] = (64, 48)) -> tuple[bytes, Image.Image]:
    buffer = io.BytesIO()
    Image.new("RGB", size, "darkorange").save(buffer, format=fmt)
    data = buffer.getvalue()
    return data, load_image(data)


class _Clock:
    def __init__(self, now: datetime = NOW, step: timedelta = timedelta(0)) -> None:
        self.now = now
        self.step = step

    def __call__(self) -> datetime:
        current = self.now
        self.now += self.step
        return current


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "dataset"


@pytest.fixture
def make_writer(root: Path) -> Callable[..., DatasetWriter]:
    def _make(clock: Callable[[], datetime] | None = None) -> DatasetWriter:
        return DatasetWriter(root, clock=clock or _Clock())

    return _make


def _rows(root: Path) -> list[dict[str, str]]:
    with (root / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


# ------------------------------------------------------------------------------------ validation


def test_valid_fields() -> None:
    request = _request()
    assert request == CollectRequest(
        item_id="S-012",
        object_type=DatasetObjectType.SCREW,
        grade=Grade.FAIR,
        labeler="a",
        angle=2,
        notes="dúvida fair/poor",
    )


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"item_id": None}, "item_id"),
        ({"item_id": "S-12"}, "item_id"),
        ({"item_id": "s-012"}, "item_id"),
        ({"item_id": "S-0123"}, "item_id"),
        ({"item_id": "../S-001"}, "item_id"),
        ({"item_id": "S-012\n"}, "item_id"),
        ({"item_id": " S-012"}, "item_id"),
        ({"item_id": "S-٠١٢"}, "item_id"),  # Arabic-Indic digits: \d is ASCII only here
        ({"item_id": "N-001"}, "item_id"),  # prefix does not match screw
        ({"item_id": "T-001"}, "item_id"),  # T- only with a hand tool (SPEC-016)
        ({"object_type": "pliers"}, "item_id"),  # a hand tool only with T-
        ({"item_id": "T-001", "object_type": "other", "grade": ""}, "item_id"),
        ({"item_id": "T-001", "object_type": "pliers", "grade": ""}, "grade"),
        ({"item_id": "T-001", "object_type": "pliers", "grade": None}, "grade"),
        ({"item_id": "XT-0001", "object_type": "pliers"}, "item_id"),
        ({"object_type": None}, "object_type"),
        ({"object_type": "unknown"}, "object_type"),
        ({"object_type": "screw\n"}, "object_type"),
        ({"object_type": "Screw"}, "object_type"),
        ({"grade": None}, "grade"),
        ({"grade": ""}, "grade"),
        ({"grade": "excellent"}, "grade"),
        ({"grade": "fair "}, "grade"),
        ({"labeler": "c"}, "labeler"),
        ({"labeler": None}, "labeler"),
        ({"labeler": "a\n"}, "labeler"),
        ({"angle": "5"}, "angle"),
        ({"angle": "-1"}, "angle"),
        ({"angle": "x"}, "angle"),
        ({"angle": "2\n"}, "angle"),
        ({"angle": " 2"}, "angle"),
        ({"angle": "02"}, "angle"),
        ({"angle": "２"}, "angle"),  # fullwidth digit
        ({"angle": None}, "angle"),
        ({"notes": "x" * 201}, "notes"),
        ({"notes": "a\nb"}, "notes"),
        ({"notes": "a\rb"}, "notes"),
        ({"notes": "a\tb"}, "notes"),
        ({"notes": "a\x00b"}, "notes"),
        ({"notes": "a\x85b"}, "notes"),  # C1 control (NEL)
        ({"notes": "a\ud800b"}, "notes"),  # lone surrogate
    ],
)
def test_invalid_fields(changes: dict[str, Any], field: str) -> None:
    with pytest.raises(InvalidCollectFieldError) as excinfo:
        _request(**changes)
    assert excinfo.value.field == field
    assert excinfo.value.status_code == 422


def test_non_string_values_are_invalid() -> None:
    for name in ("item_id", "object_type", "grade", "labeler", "angle", "notes"):
        with pytest.raises(InvalidCollectFieldError):
            CollectRequest.from_fields({**VALID, name: object()})


def test_other_takes_no_grade() -> None:
    absent = _request(item_id="O-004", object_type="other", grade=None)
    empty = _request(item_id="O-004", object_type="other", grade="")
    assert absent.grade is None and empty.grade is None
    with pytest.raises(InvalidCollectFieldError) as excinfo:
        _request(item_id="O-004", object_type="other", grade="good")
    assert excinfo.value.field == "grade"


def test_notes_are_optional_and_kept_verbatim() -> None:
    assert _request(notes=None).notes == ""
    prefix = 'tem "aspas", vírgula; '
    text = prefix + "x" * (200 - len(prefix))
    assert _request(notes=text).notes == text


def test_every_angle_and_nut_prefix() -> None:
    assert [_request(angle=str(a)).angle for a in range(5)] == [0, 1, 2, 3, 4]
    nut = _request(item_id="N-001", object_type="nut", grade="unusable", labeler="b")
    assert (nut.object_type, nut.grade, nut.labeler) == (
        DatasetObjectType.NUT,
        Grade.UNUSABLE,
        "b",
    )


# ---------------------------------------------------------------------------------------- writer


def test_first_write_creates_image_and_manifest(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    data, image = _encoded()
    result = make_writer().write(_request(), data, image, "U" * 80)
    assert result.image_path == "raw/screw/fair/S-012__2__20261022T141503Z.jpg"
    assert (result.item_id, result.angle, result.item_images) == ("S-012", 2, 1)
    assert (root / result.image_path).read_bytes() == data  # JPEG saved as received
    raw = (root / "manifest.csv").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # no BOM
    assert raw.decode("utf-8").startswith(HEADER_LINE)
    assert b"\r" not in raw
    rows = _rows(root)
    assert rows == [
        {
            "image_path": result.image_path,
            "item_id": "S-012",
            "object_type": "screw",
            "grade": "fair",
            "labeler": "a",
            "angle": "2",
            "captured_at": "2026-10-22T14:15:03Z",
            "capture_device": "U" * 60,
            "notes": "dúvida fair/poor",
        }
    ]
    # No temporary file is left behind.
    assert _files(root) == ["manifest.csv", "manifest.csv.lock", result.image_path]


def test_other_goes_to_underscore_with_empty_grade(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    data, image = _encoded()
    request = _request(item_id="O-004", object_type="other", grade=None, angle="0")
    result = make_writer().write(request, data, image, "")
    assert result.image_path == "raw/other/_/O-004__0__20261022T141503Z.jpg"
    row = _rows(root)[0]
    assert row["grade"] == "" and row["capture_device"] == ""


def test_clock_is_converted_to_utc(make_writer: Callable[..., DatasetWriter], root: Path) -> None:
    local = NOW.astimezone(timezone(timedelta(hours=-3)))
    data, image = _encoded()
    result = make_writer(_Clock(local)).write(_request(), data, image, "")
    assert result.image_path.endswith("__20261022T141503Z.jpg")
    assert _rows(root)[0]["captured_at"] == "2026-10-22T14:15:03Z"


def test_png_is_reencoded_as_jpeg(make_writer: Callable[..., DatasetWriter], root: Path) -> None:
    data, image = _encoded("PNG")
    result = make_writer().write(_request(), data, image, "")
    saved = (root / result.image_path).read_bytes()
    assert saved.startswith(b"\xff\xd8\xff")
    with Image.open(io.BytesIO(saved)) as reopened:
        assert reopened.format == "JPEG"
        assert reopened.size == (64, 48)


def test_same_item_other_grade_counts_images(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    writer = make_writer(_Clock(step=timedelta(seconds=1)))
    data, image = _encoded()
    assert writer.write(_request(), data, image, "").item_images == 1
    assert writer.write(_request(grade="poor"), data, image, "").item_images == 2
    other_item = _request(item_id="S-013", angle="0")
    assert writer.write(other_item, data, image, "").item_images == 1
    assert writer.write(_request(angle="3"), data, image, "").item_images == 3
    assert len(_rows(root)) == 4


def test_same_second_is_409_and_nothing_changes(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    writer = make_writer()
    data, image = _encoded()
    writer.write(_request(), data, image, "")
    before = (root / "manifest.csv").read_bytes()
    with pytest.raises(CaptureExistsError) as excinfo:
        writer.write(_request(), data, image, "")
    assert (excinfo.value.status_code, excinfo.value.detail) == (
        409,
        "capture already exists, try again",
    )
    assert (root / "manifest.csv").read_bytes() == before
    assert len(list((root / "raw").rglob("*.jpg"))) == 1


def test_item_with_another_type_is_409(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    root.mkdir()
    manifest = root / "manifest.csv"
    manifest.write_text(
        HEADER_LINE + "raw/screw/fair/O-007__0__20261001T000000Z.jpg,O-007,screw,fair,a,0,"
        "2026-10-01T00:00:00Z,,\n",
        encoding="utf-8",
    )
    before = manifest.read_bytes()
    data, image = _encoded()
    request = _request(item_id="O-007", object_type="other", grade=None)
    with pytest.raises(ItemTypeConflictError) as excinfo:
        make_writer().write(request, data, image, "")
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "item_id already registered with another object_type"
    assert manifest.read_bytes() == before
    assert not (root / "raw").exists()


@pytest.mark.parametrize(
    "content",
    [
        "image_path,item_id\n",
        "﻿" + HEADER_LINE,  # BOM
        HEADER_LINE.replace("notes", "note"),
        "",  # empty file: no header at all
    ],
)
def test_header_mismatch_writes_nothing(
    make_writer: Callable[..., DatasetWriter], root: Path, content: str
) -> None:
    root.mkdir()
    manifest = root / "manifest.csv"
    manifest.write_text(content, encoding="utf-8")
    before = manifest.read_bytes()
    data, image = _encoded()
    with pytest.raises(ManifestHeaderMismatchError) as excinfo:
        make_writer().write(_request(), data, image, "")
    assert (excinfo.value.status_code, excinfo.value.detail) == (500, "manifest header mismatch")
    assert manifest.read_bytes() == before
    assert not (root / "raw").exists()


def test_invalid_utf8_header_is_a_mismatch(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    root.mkdir()
    (root / "manifest.csv").write_bytes(b"\xff\xfe" + HEADER_LINE.encode())
    data, image = _encoded()
    with pytest.raises(ManifestHeaderMismatchError):
        make_writer().write(_request(), data, image, "")


def test_unreadable_rows_are_500(make_writer: Callable[..., DatasetWriter], root: Path) -> None:
    root.mkdir()
    (root / "manifest.csv").write_bytes(HEADER_LINE.encode() + b"\xff\xfe,broken\n")
    data, image = _encoded()
    with pytest.raises(ManifestUnreadableError) as excinfo:
        make_writer().write(_request(), data, image, "")
    assert excinfo.value.status_code == 500
    assert not (root / "raw").exists()


def test_quoting_round_trips(make_writer: Callable[..., DatasetWriter], root: Path) -> None:
    notes = 'tem "aspas", vírgula'
    data, image = _encoded()
    make_writer().write(_request(notes=notes), data, image, 'Agent, "x"')
    text = (root / "manifest.csv").read_text(encoding="utf-8")
    assert '"tem ""aspas"", vírgula"' in text
    row = _rows(root)[0]
    assert row["notes"] == notes
    assert row["capture_device"] == 'Agent, "x"'


def test_hand_edited_manifest_without_final_newline(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    root.mkdir()
    existing = (
        "raw/nut/poor/N-001__0__20261001T000000Z.jpg,N-001,nut,poor,b,0,2026-10-01T00:00:00Z,,"
    )
    (root / "manifest.csv").write_text(HEADER_LINE + existing, encoding="utf-8")
    data, image = _encoded()
    make_writer().write(_request(), data, image, "")
    rows = _rows(root)
    assert [row["item_id"] for row in rows] == ["N-001", "S-012"]


def test_manifest_failure_removes_the_image(
    make_writer: Callable[..., DatasetWriter], root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = make_writer(_Clock(step=timedelta(seconds=1)))
    data, image = _encoded()
    writer.write(_request(), data, image, "")
    before = (root / "manifest.csv").read_bytes()

    real_write = os.write

    def failing_write(fd: int, payload: Any) -> int:
        written = real_write(fd, bytes(payload)[:5])  # a partial row, then the disk fills up
        if written:
            raise OSError(28, "No space left on device")
        return written

    monkeypatch.setattr(collect_module.os, "write", failing_write)
    with pytest.raises(DatasetWriteError) as excinfo:
        writer.write(_request(angle="3"), data, image, "")
    monkeypatch.undo()
    assert (excinfo.value.status_code, excinfo.value.detail) == (500, "failed to write dataset")
    assert (root / "manifest.csv").read_bytes() == before  # truncated back
    assert [p.name for p in (root / "raw").rglob("*.jpg")] == ["S-012__2__20261022T141503Z.jpg"]


def test_failure_creating_the_manifest_removes_it(
    make_writer: Callable[..., DatasetWriter], root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_write(fd: int, payload: Any) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(collect_module.os, "write", failing_write)
    data, image = _encoded()
    with pytest.raises(DatasetWriteError):
        make_writer().write(_request(), data, image, "")
    monkeypatch.undo()
    assert not (root / "manifest.csv").exists()
    assert list((root / "raw").rglob("*.jpg")) == []
    # The next capture starts a fresh manifest with its header.
    make_writer().write(_request(), data, image, "")
    assert len(_rows(root)) == 1


def test_image_failure_leaves_no_temporary_file(
    make_writer: Callable[..., DatasetWriter], root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_jpeg(handle: Any, data: bytes, image: Image.Image) -> None:
        handle.write(b"partial")
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(collect_module, "write_capture_jpeg", failing_jpeg)
    data, image = _encoded()
    with pytest.raises(DatasetWriteError):
        make_writer().write(_request(), data, image, "")
    assert [p for p in (root / "raw").rglob("*") if p.is_file()] == []
    assert not (root / "manifest.csv").exists()


def test_symlinked_manifest_is_not_followed(
    make_writer: Callable[..., DatasetWriter], root: Path, tmp_path: Path
) -> None:
    root.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text(HEADER_LINE, encoding="utf-8")
    (root / "manifest.csv").symlink_to(victim)
    data, image = _encoded()
    with pytest.raises(DatasetWriteError):
        make_writer().write(_request(), data, image, "")
    assert victim.read_text(encoding="utf-8") == HEADER_LINE
    assert list((root / "raw").rglob("*.jpg")) == []


def test_concurrent_writes_from_threads(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    writer = make_writer()
    data, image = _encoded()
    requests = [_request(item_id=f"S-{i:03d}", angle=str(i % 5)) for i in range(1, 9)] + [
        _request(item_id=f"N-{i:03d}", object_type="nut", grade="good") for i in range(1, 9)
    ]
    barrier = threading.Barrier(len(requests))
    errors: list[BaseException] = []

    def run(request: CollectRequest) -> None:
        barrier.wait()
        try:
            writer.write(request, data, image, "")
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(r,)) for r in requests]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    rows = _rows(root)
    assert sorted(row["item_id"] for row in rows) == sorted(r.item_id for r in requests)
    assert all(len(row) == len(MANIFEST_COLUMNS) and None not in row for row in rows)


def test_file_lock_is_taken(
    make_writer: Callable[..., DatasetWriter], root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, int]] = []
    real_flock = collect_module.fcntl.flock

    def recording_flock(fd: int, operation: int) -> None:
        calls.append((os.readlink(f"/proc/self/fd/{fd}"), operation))
        real_flock(fd, operation)

    monkeypatch.setattr(collect_module.fcntl, "flock", recording_flock)
    data, image = _encoded()
    make_writer().write(_request(), data, image, "")
    assert calls == [(str(root / "manifest.csv.lock"), collect_module.fcntl.LOCK_EX)]


# ----------------------------------------------------------------------------------- permissions


@pytest.fixture
def umask() -> Iterator[Callable[[int], None]]:
    original = os.umask(0o022)
    os.umask(original)

    def _set(value: int) -> None:
        os.umask(value)

    try:
        yield _set
    finally:
        os.umask(original)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


@pytest.mark.parametrize("mask", [0o022, 0o077, 0o000, 0o277])
def test_exact_modes_whatever_the_umask(
    make_writer: Callable[..., DatasetWriter],
    root: Path,
    umask: Callable[[int], None],
    mask: int,
) -> None:
    umask(mask)
    writer = make_writer(_Clock(step=timedelta(seconds=1)))
    jpeg, jpeg_image = _encoded()
    png, png_image = _encoded("PNG")
    first = writer.write(_request(), jpeg, jpeg_image, "")
    second = writer.write(
        _request(item_id="O-004", object_type="other", grade=None), png, png_image, ""
    )
    for directory in (
        root,
        root / "raw",
        root / "raw/screw",
        root / "raw/screw/fair",
        root / "raw/other",
        root / "raw/other/_",
    ):
        assert _mode(directory) == 0o700, directory
    for file in (
        root / first.image_path,
        root / second.image_path,
        root / "manifest.csv",
        root / "manifest.csv.lock",
    ):
        assert _mode(file) == 0o600, file


def test_missing_parents_of_dataset_dir_are_0700(
    tmp_path: Path, umask: Callable[[int], None]
) -> None:
    umask(0o022)
    root = tmp_path / "a" / "b" / "dataset"
    data, image = _encoded()
    DatasetWriter(root, clock=_Clock()).write(_request(), data, image, "")
    assert [_mode(p) for p in (tmp_path / "a", tmp_path / "a" / "b", root)] == [0o700] * 3


def test_existing_directories_and_files_are_not_changed(
    make_writer: Callable[..., DatasetWriter], root: Path, umask: Callable[[int], None]
) -> None:
    umask(0o022)
    (root / "raw" / "screw").mkdir(parents=True)
    for directory in (root, root / "raw", root / "raw" / "screw"):
        directory.chmod(0o755)
    manifest = root / "manifest.csv"
    manifest.write_text(HEADER_LINE, encoding="utf-8")
    manifest.chmod(0o644)
    data, image = _encoded()
    result = make_writer().write(_request(), data, image, "")
    assert [_mode(p) for p in (root, root / "raw", root / "raw" / "screw")] == [0o755] * 3
    assert _mode(manifest) == 0o644
    assert _mode(root / "raw" / "screw" / "fair") == 0o700  # created now
    assert _mode(root / result.image_path) == 0o600
    assert _mode(root / "manifest.csv.lock") == 0o600


def test_chmod_failure_is_a_warning(
    make_writer: Callable[..., DatasetWriter],
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failing_chmod(path: Any, mode: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    def failing_fchmod(fd: int, mode: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(collect_module.os, "chmod", failing_chmod)
    monkeypatch.setattr(collect_module.os, "fchmod", failing_fchmod)
    data, image = _encoded()
    with caplog.at_level(logging.WARNING, logger="qc_edge"):
        result = make_writer().write(_request(), data, image, "")
    assert (root / result.image_path).is_file()
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(str(root / "raw") in message for message in warnings)
    assert any("manifest.csv" in message for message in warnings)


# -------------------------------------------------------------------------------------- coverage


def _write_manifest(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    """``rows``: ``(item_id, object_type, grade, angle)``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(MANIFEST_COLUMNS)
        for i, (item_id, object_type, grade, angle) in enumerate(rows):
            image_path = f"raw/{object_type}/{grade or '_'}/{item_id}__{angle}__{i}.jpg"
            captured_at = "2026-10-22T00:00:00Z"
            writer.writerow(
                (image_path, item_id, object_type, grade, "a", angle, captured_at, "", "")
            )


def _cell(cells: list[Any], object_type: str, grade: str | None) -> Any:
    return next(c for c in cells if (c.object_type, c.grade) == (object_type, grade))


def test_coverage_of_a_missing_manifest(tmp_path: Path) -> None:
    cells = compute_coverage(tmp_path / "nothing" / "manifest.csv")
    assert cells == empty_coverage()
    assert [(c.object_type, c.grade) for c in cells] == [
        *[("screw", g.value) for g in Grade],
        *[("nut", g.value) for g in Grade],
        *[(tool, g.value) for tool in TOOLS for g in Grade],
        ("other", None),
    ]
    assert len(cells) == 36
    assert all(c.images == 0 and c.items == 0 for c in cells)


def test_coverage_counts_images_and_items(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    rows = [(f"S-{i % 9:03d}", "screw", "perfect", str(i % 5)) for i in range(130)]
    rows += [(f"N-{i % 3:03d}", "nut", "poor", "0") for i in range(40)]
    rows += [(f"O-{i:03d}", "other", "", "0") for i in range(10)]
    rows += [("T-001", "pliers", "", "0"), ("S-500", "screw", "", "0"), ("", "screw", "good", "0")]
    _write_manifest(manifest, rows)
    cells = compute_coverage(manifest)
    perfect = _cell(cells, "screw", "perfect")
    poor = _cell(cells, "nut", "poor")
    other = _cell(cells, "other", None)
    assert (perfect.images, perfect.items, perfect.target_images, perfect.target_items) == (
        130,
        9,
        120,
        12,
    )
    assert (poor.images, poor.items, poor.target_images, poor.target_items) == (40, 3, 120, 12)
    assert (other.images, other.items, other.target_images, other.target_items) == (
        10,
        10,
        150,
        30,
    )
    rest = [c for c in cells if c not in (perfect, poor, other)]
    assert len(rest) == 33 and all((c.images, c.items) == (0, 0) for c in rest)
    assert not perfect.complete


def test_coverage_cell_complete_needs_both_targets(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    rows = [(f"S-{i % 12:03d}", "screw", "good", "0") for i in range(120)]
    rows += [(f"N-{i % 11:03d}", "nut", "good", "0") for i in range(200)]
    _write_manifest(manifest, rows)
    cells = compute_coverage(manifest)
    assert _cell(cells, "screw", "good").complete
    assert not _cell(cells, "nut", "good").complete  # 11 items < 12


def test_writer_coverage_reads_its_manifest(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    writer = make_writer(_Clock(step=timedelta(seconds=1)))
    assert writer.coverage() == empty_coverage()
    data, image = _encoded()
    for angle in range(5):
        writer.write(_request(angle=str(angle)), data, image, "")
    fair = _cell(writer.coverage(), "screw", "fair")
    assert (fair.images, fair.items) == (5, 1)


def test_write_waits_for_the_file_lock_of_another_holder(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    # flock locks belong to the open file description: a second open() in this process stands
    # for another process holding the lock.
    root.mkdir()
    holder = os.open(root / "manifest.csv.lock", os.O_RDWR | os.O_CREAT, 0o600)
    collect_module.fcntl.flock(holder, collect_module.fcntl.LOCK_EX)
    data, image = _encoded()
    done = threading.Event()

    def run() -> None:
        make_writer().write(_request(), data, image, "")
        done.set()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert not done.wait(timeout=0.3)
        assert not (root / "manifest.csv").exists()
    finally:
        os.close(holder)  # releases the lock
    thread.join(timeout=5)
    assert done.is_set()
    assert len(_rows(root)) == 1


# ------------------------------------------------------ SPEC-025 sections 4.8, 4.10 and 4.11


@pytest.mark.parametrize("char", [" ", " ", "‪", "‮", "⁦", "⁩", "‎", "‏", "؜", "­", "﻿"])
def test_notes_refuse_separators_and_format_characters(char: str) -> None:
    with pytest.raises(InvalidCollectFieldError) as excinfo:
        _request(notes=f"dúvida {char} fair")
    assert excinfo.value.field == "notes"


def test_notes_keep_other_unicode_verbatim() -> None:
    text = "dúvida fair/poor — ç ã 日本 🙂  "
    assert _request(notes=text).notes == text


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        ("Phone\x85X\tY" + "z" * 70, "Phone X Y" + "z" * 51),
        ("A B C‮D­E", "A B C D E"),
        ("M" * 80, "M" * 60),
        ("", ""),
        ("Mozilla/5.0 (Linux; Android 14) ç", "Mozilla/5.0 (Linux; Android 14) ç"),
        ("\x00" * 70, " " * 60),
    ],
)
def test_capture_device_replaces_controls_before_the_cut(user_agent: str, expected: str) -> None:
    assert capture_device_from_user_agent(user_agent) == expected


def test_metadata_jpeg_is_stored_clean(
    make_writer: Callable[..., DatasetWriter], root: Path, jpeg_tools: Any
) -> None:
    data, marker = jpeg_tools.with_metadata()
    image = load_image(data)
    result = make_writer().write(_request(), data, image, "")
    stored = (root / result.image_path).read_bytes()
    assert stored == strip_private_segments(data)
    for needle in (b"Exif\x00\x00", b"ns.adobe.com", b"Photoshop 3.0", marker, b"ftypmp42"):
        assert needle not in stored
    assert jpeg_tools.pixels(stored).tolist() == jpeg_tools.pixels(data).tolist()


def test_clean_jpeg_is_stored_byte_for_byte(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    data, image = _encoded()
    result = make_writer().write(_request(), data, image, "")
    assert (root / result.image_path).read_bytes() == data


def test_unwalkable_jpeg_is_415_before_touching_the_disk(
    make_writer: Callable[..., DatasetWriter], root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(data: bytes) -> bytes:
        raise JpegStructureError("unsupported")

    monkeypatch.setattr(jpeg_module, "strip_private_segments", broken)
    data, image = _encoded()
    with pytest.raises(UnsupportedJpegStructureError) as excinfo:
        make_writer().write(_request(), data, image, "")
    assert excinfo.value.status_code == 415
    assert excinfo.value.detail == "invalid image: unsupported JPEG structure"
    assert not root.exists()


def test_png_is_never_walked(
    make_writer: Callable[..., DatasetWriter], root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(data: bytes) -> bytes:
        raise AssertionError("PNG must not be walked as JPEG")

    monkeypatch.setattr(jpeg_module, "strip_private_segments", broken)
    data, image = _encoded("PNG")
    result = make_writer().write(_request(), data, image, "")
    assert (root / result.image_path).read_bytes().startswith(b"\xff\xd8\xff")


def test_exif_rotated_jpeg_is_415_before_touching_the_disk(
    make_writer: Callable[..., DatasetWriter], root: Path, jpeg_tools: Any
) -> None:
    for data in (jpeg_tools.rotated_jpeg(6), jpeg_tools.xmp_orientation_jpeg(8)):
        with pytest.raises(ExifOrientationNotSupportedError) as excinfo:
            make_writer().write(_request(), data, load_image(data), "")
        assert excinfo.value.status_code == 415
        assert excinfo.value.detail == "invalid image: EXIF orientation not supported"
        assert not root.exists()


def test_orientation_1_is_stripped_and_keeps_the_load_image_result(
    make_writer: Callable[..., DatasetWriter], root: Path, jpeg_tools: Any
) -> None:
    data = jpeg_tools.rotated_jpeg(1)
    result = make_writer().write(_request(), data, load_image(data), "")
    stored = (root / result.image_path).read_bytes()
    assert stored == strip_private_segments(data)
    assert jpeg_private_findings(stored) == frozenset()
    assert load_image(stored).size == load_image(data).size == (64, 48)
    assert (np.asarray(load_image(stored)) == np.asarray(load_image(data))).all()


def test_rotation_check_comes_before_the_strip(
    make_writer: Callable[..., DatasetWriter],
    root: Path,
    jpeg_tools: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(data: bytes) -> bytes:
        raise AssertionError("a rotated JPEG must not be stripped")

    monkeypatch.setattr(jpeg_module, "strip_private_segments", never)
    data = jpeg_tools.rotated_jpeg(6)
    with pytest.raises(ExifOrientationNotSupportedError):
        make_writer().write(_request(), data, load_image(data), "")


def test_unreadable_orientation_is_an_unsupported_structure(
    make_writer: Callable[..., DatasetWriter], root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(data: bytes) -> bool:
        raise JpegStructureError("cannot read the JPEG EXIF orientation")

    monkeypatch.setattr(jpeg_module, "has_exif_rotation", broken)
    data, image = _encoded()
    with pytest.raises(UnsupportedJpegStructureError) as excinfo:
        make_writer().write(_request(), data, image, "")
    assert excinfo.value.status_code == 415
    assert not root.exists()


def test_png_orientation_is_applied_before_the_reencode(
    make_writer: Callable[..., DatasetWriter],
    root: Path,
    jpeg_tools: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(data: bytes) -> bool:
        raise AssertionError("a PNG is never checked as JPEG")

    monkeypatch.setattr(jpeg_module, "has_exif_rotation", never)
    buffer = io.BytesIO()
    jpeg_tools.noise_image().save(buffer, format="PNG", exif=jpeg_tools.orientation_exif(6))
    png = buffer.getvalue()
    image = load_image(png)
    assert image.size == (48, 64)
    result = make_writer().write(_request(), png, image, "")
    stored = (root / result.image_path).read_bytes()
    assert jpeg_private_findings(stored) == frozenset()
    assert load_image(stored).size == (48, 64)


class _FsyncSpy:
    """Records the path of every ``os.fsync``; optionally refuses directories."""

    def __init__(self, refuse_dirs: bool = False) -> None:
        self.paths: list[str] = []
        self.refuse_dirs = refuse_dirs
        self.original = os.fsync

    def __call__(self, fd: int) -> None:
        path = os.readlink(f"/proc/self/fd/{fd}")
        self.paths.append(path)
        if self.refuse_dirs and stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "Invalid argument")
        self.original(fd)


def test_directories_are_synced_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "dataset"
    spy = _FsyncSpy()
    monkeypatch.setattr(os, "fsync", spy)
    data, image = _encoded()
    result = DatasetWriter(root, clock=_Clock()).write(_request(), data, image, "")
    paths = [Path(p) for p in spy.paths]
    image_dir = root / "raw/screw/fair"
    created_parents = [tmp_path, root, root / "raw", root / "raw/screw"]
    assert paths[:4] == created_parents
    temp = paths[4]
    assert temp.parent == image_dir and temp.name.startswith(".")
    assert paths[5:] == [image_dir, root / "manifest.csv", root]
    assert (root / result.image_path).is_file()


def test_existing_manifest_is_not_followed_by_a_directory_sync(
    make_writer: Callable[..., DatasetWriter], root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = make_writer(_Clock(step=timedelta(seconds=1)))
    data, image = _encoded()
    writer.write(_request(), data, image, "")
    spy = _FsyncSpy()
    monkeypatch.setattr(os, "fsync", spy)
    writer.write(_request(angle="3"), data, image, "")
    paths = [Path(p) for p in spy.paths]
    assert paths[1:] == [root / "raw/screw/fair", root / "manifest.csv"]


def test_directory_sync_failures_are_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "dataset"
    spy = _FsyncSpy(refuse_dirs=True)
    monkeypatch.setattr(os, "fsync", spy)
    data, image = _encoded()
    with caplog.at_level(logging.WARNING, logger="qc_edge"):
        result = DatasetWriter(root, clock=_Clock()).write(_request(), data, image, "")
    assert (root / result.image_path).is_file()
    assert len(_rows(root)) == 1
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    fsync_warnings = [w for w in warnings if w.startswith("cannot fsync directory")]
    assert len(fsync_warnings) == 6  # parent, root, raw, raw/screw, raw/screw/fair, root
    assert all("Invalid argument" in w for w in fsync_warnings)
    assert "cannot fsync directory raw/screw/fair: Invalid argument" in fsync_warnings
    assert all(str(tmp_path) not in w for w in fsync_warnings)


def test_fsync_dir_open_failure_is_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="qc_edge"):
        fsync_dir(tmp_path / "missing", relative_to=tmp_path)
    assert "cannot fsync directory missing" in caplog.text


def test_manifest_has_one_line_per_record(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    data, image = _encoded()
    device = capture_device_from_user_agent("Phone\x85X Y\tZ")
    make_writer().write(_request(notes='a, "b" c'), data, image, device)
    text = (root / "manifest.csv").read_text(encoding="utf-8")
    assert len(text.splitlines()) == 2
    assert _rows(root)[0]["capture_device"] == "Phone X Y Z"


# ------------------------------------------------- external images and CSV helpers (SPEC-036)


def test_coverage_ignores_external_images(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    rows = [("S-001", "screw", "perfect", str(i)) for i in range(3)]
    rows += [(f"XS-{i:04d}", "screw", "perfect", "0") for i in range(1, 6)]
    rows += [("XO-0001", "other", "", "0"), ("XT-0001", "pliers", "", "0")]
    rows += [("XS-001", "screw", "perfect", "0")]  # not external: 3 digits, counted as usual
    _write_manifest(manifest, rows)
    perfect = _cell(compute_coverage(manifest), "screw", "perfect")
    assert (perfect.images, perfect.items) == (4, 2)
    assert _cell(compute_coverage(manifest), "other", None).images == 0
    assert count_external_images(manifest) == 7


def test_count_external_images_without_manifest(tmp_path: Path) -> None:
    assert count_external_images(tmp_path / "nothing" / "manifest.csv") == 0


def test_writer_external_images(make_writer: Callable[..., DatasetWriter], root: Path) -> None:
    writer = make_writer()
    assert writer.external_images() == 0
    _write_manifest(root / "manifest.csv", [("XN-0001", "nut", "good", "0")])
    assert writer.external_images() == 1


def test_read_csv_rows(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    assert read_csv_rows(path, ("a", "b")) is None
    path.write_bytes(b"a,b\n1,2\n3\n")
    assert read_csv_rows(path, ("a", "b")) == [["1", "2"], ["3"]]
    for content in (b"", b"\xef\xbb\xbfa,b\n", b"b,a\n", b"\xff\n"):
        path.write_bytes(content)
        with pytest.raises(collect_module.CsvHeaderMismatchError):
            read_csv_rows(path, ("a", "b"))
    path.write_bytes(b"a,b\n\xff\n")
    with pytest.raises(collect_module.CsvUnreadableError):
        read_csv_rows(path, ("a", "b"))


def test_append_and_rollback(tmp_path: Path) -> None:
    path = tmp_path / "s.csv"
    original = os.umask(0o077)
    try:
        first = append_csv_row(path, ("a", "b"), ("1", "2"), root=tmp_path)
    finally:
        os.umask(original)
    assert first.created and first.previous_size == 0
    assert path.read_bytes() == b"a,b\n1,2\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    second = append_csv_row(path, ("a", "b"), ("3", "x,y"), root=tmp_path)
    assert not second.created and second.previous_size == len(b"a,b\n1,2\n")
    assert path.read_bytes() == b'a,b\n1,2\n3,"x,y"\n'
    rollback_append(second, root=tmp_path)
    assert path.read_bytes() == b"a,b\n1,2\n"
    rollback_append(first, root=tmp_path)
    assert not path.exists()


def test_append_adds_a_missing_final_line_break(tmp_path: Path) -> None:
    path = tmp_path / "s.csv"
    path.write_bytes(b"a,b\n1,2")
    append_csv_row(path, ("a", "b"), ("3", "4"), root=tmp_path)
    assert path.read_bytes() == b"a,b\n1,2\n3,4\n"


TOOLS = ("pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver")


@pytest.mark.parametrize("tool", TOOLS)
def test_every_tool_with_t_prefix_and_grade_is_valid(tool: str) -> None:
    request = CollectRequest.from_fields(
        _fields(item_id="T-007", object_type=tool, grade="unusable")
    )
    assert request.object_type == tool
    assert request.grade is Grade.UNUSABLE


def test_tool_types_mirror_the_contract() -> None:
    """The hand tools of the collect mode are the grade-optional types of the contract."""
    assert [t.value for t in TOOL_OBJECT_TYPES] == [
        member.value for member in ObjectType if member in GRADE_OPTIONAL_OBJECT_TYPES
    ]
    assert {t.value for t in GRADED_DATASET_TYPES} == {"screw", "nut", *TOOLS}
    assert ITEM_PREFIX_TYPES["T"] == frozenset(TOOL_OBJECT_TYPES)


@pytest.mark.parametrize(
    ("letter", "object_type", "expected"),
    [
        ("T", "pliers", True),
        ("T", "phillips_screwdriver", True),
        ("T", "screw", False),
        ("T", "other", False),
        ("S", "pliers", False),
        ("S", "screw", True),
        ("O", "other", True),
        ("X", "pliers", False),
        ("T", "unknown", False),
    ],
)
def test_item_prefix_matches(letter: str, object_type: str, expected: bool) -> None:
    assert item_prefix_matches(letter, object_type) is expected


def test_tool_capture_goes_to_its_grade_directory(
    make_writer: Callable[..., DatasetWriter], root: Path
) -> None:
    writer = make_writer(_Clock(step=timedelta(seconds=1)))
    request = CollectRequest.from_fields(
        _fields(item_id="T-001", object_type="allen_key", grade="good")
    )
    result = writer.write(request, *_encoded(), "UA")
    assert result.image_path.startswith("raw/allen_key/good/T-001__")
    assert (root / result.image_path).is_file()
    assert [(r["item_id"], r["object_type"], r["grade"]) for r in _rows(root)] == [
        ("T-001", "allen_key", "good")
    ]


def test_coverage_counts_tool_rows(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    rows = [(f"T-{i % 5:03d}", "pliers", "fair", str(i % 5)) for i in range(60)]
    rows += [("T-010", "allen_key", "good", "0"), ("XT-0001", "pliers", "fair", "0")]
    rows += [("T-011", "allen_key", "", "0")]  # a tool without grade fits no cell
    _write_manifest(manifest, rows)
    cells = compute_coverage(manifest)
    pliers = _cell(cells, "pliers", "fair")
    assert (pliers.images, pliers.items, pliers.target_images, pliers.target_items) == (
        60,
        5,
        60,
        5,
    )
    assert pliers.complete
    allen = _cell(cells, "allen_key", "good")
    assert (allen.images, allen.items) == (1, 1) and not allen.complete
    assert sum(c.images for c in cells) == 61
