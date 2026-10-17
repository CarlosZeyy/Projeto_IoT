"""qc_edge.collect: validation, paths, manifest, permissions, lock and coverage (SPEC-010)."""

from __future__ import annotations

import csv
import io
import logging
import os
import stat
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from qc_contracts import Grade
from qc_edge import collect as collect_module
from qc_edge.collect import (
    MANIFEST_COLUMNS,
    CaptureExistsError,
    CollectRequest,
    DatasetObjectType,
    DatasetWriteError,
    DatasetWriter,
    InvalidCollectFieldError,
    ItemTypeConflictError,
    ManifestHeaderMismatchError,
    ManifestUnreadableError,
    compute_coverage,
    empty_coverage,
)
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
        ({"item_id": "T-001"}, "item_id"),  # tools: SPEC-016
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
        ("other", None),
    ]
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
    assert len(rest) == 8 and all((c.images, c.items) == (0, 0) for c in rest)
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
