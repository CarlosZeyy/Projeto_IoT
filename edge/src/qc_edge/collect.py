"""Collect mode: building the dataset on the notebook (SPEC-010, docs/architecture.md section 6.3).

Each accepted photo becomes one file,
``DATASET_DIR/raw/<object_type>/<grade or _>/<item_id>__<angle>__<ts>.jpg``, and one row of
``DATASET_DIR/manifest.csv`` (``docs/dataset-protocol.md`` section 5). Nothing here runs inference
or talks to the network: images and manifest stay on this machine (R-02, R-14).

Every field that becomes part of a file name or path is validated with ``re.fullmatch`` or exact
equality, before anything touches the disk (``docs/architecture.md`` section 3.2). Everything this
module creates under ``DATASET_DIR`` gets an exact mode, whatever the ``umask``: ``0700`` for
directories and ``0600`` for files (SEC-06, R-14).
"""

from __future__ import annotations

import contextlib
import csv
import fcntl
import io
import logging
import os
import re
import tempfile
import threading
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from PIL import Image

from qc_contracts import GRADE_ORDER, Grade
from qc_edge.jpeg import write_capture_jpeg

logger = logging.getLogger("qc_edge")

MANIFEST_NAME = "manifest.csv"
MANIFEST_LOCK_NAME = "manifest.csv.lock"
RAW_SUBDIR = "raw"
NO_GRADE_DIR = "_"
# docs/dataset-protocol.md section 5, in this exact order.
MANIFEST_COLUMNS: tuple[str, ...] = (
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

# Whole-string patterns, always used with ``re.fullmatch`` (``$`` would accept a trailing "\n").
ITEM_ID_PATTERN = r"[SNOT]-\d{3}"
ANGLE_PATTERN = r"[0-4]"
LABELERS = frozenset({"a", "b"})
GRADE_VALUES = frozenset(grade.value for grade in Grade)
NOTES_MAX_LENGTH = 200
CAPTURE_DEVICE_MAX_LENGTH = 60
# Unicode categories refused in ``notes``: control characters (C0, DEL, C1, including "\r", "\n"
# and "\t") and lone surrogates (they cannot be written as UTF-8).
_FORBIDDEN_NOTE_CATEGORIES = frozenset({"Cc", "Cs"})

DIR_MODE = 0o700
FILE_MODE = 0o600

FILE_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
CAPTURED_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Coverage targets (docs/dataset-protocol.md section 4).
GRADED_TARGET_IMAGES = 120
GRADED_TARGET_ITEMS = 12
GRADED_MIN_ITEMS = 8  # shown on the console only; the target stays 12
OTHER_TARGET_IMAGES = 150
OTHER_TARGET_ITEMS = 30


class DatasetObjectType(StrEnum):
    """Classes of the model's type head. ``other`` is mapped to ``unknown`` only in the contract."""

    SCREW = "screw"
    NUT = "nut"
    OTHER = "other"


# Prefix of ``item_id`` -> object type. ``T`` (tools, phase 2) is refused until SPEC-016.
ITEM_PREFIX_TYPES: Mapping[str, DatasetObjectType] = {
    "S": DatasetObjectType.SCREW,
    "N": DatasetObjectType.NUT,
    "O": DatasetObjectType.OTHER,
}
_OBJECT_TYPE_VALUES = frozenset(member.value for member in DatasetObjectType)


# --------------------------------------------------------------------------------------- errors


class CollectError(Exception):
    """A collect request that cannot be stored. ``status_code`` and ``detail`` are the response."""

    status_code: int = 500
    detail: str = "collect failed"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class InvalidCollectFieldError(CollectError):
    """422: a form field breaks section 4.1; raised before the disk is touched."""

    status_code = 422

    def __init__(self, field: str, detail: str | None = None) -> None:
        self.field = field
        super().__init__(detail if detail is not None else f"missing or invalid {field}")


class ManifestHeaderMismatchError(CollectError):
    status_code = 500
    detail = "manifest header mismatch"


class ManifestUnreadableError(CollectError):
    status_code = 500
    detail = "manifest unreadable"


class ItemTypeConflictError(CollectError):
    status_code = 409
    detail = "item_id already registered with another object_type"


class CaptureExistsError(CollectError):
    status_code = 409
    detail = "capture already exists, try again"


class DatasetWriteError(CollectError):
    status_code = 500
    detail = "failed to write dataset"


# -------------------------------------------------------------------------------------- request


@dataclass(frozen=True)
class CollectRequest:
    """Validated collect-mode fields of ``POST /api/capture`` (section 4.1)."""

    item_id: str
    object_type: DatasetObjectType
    grade: Grade | None
    labeler: str
    angle: int
    notes: str = ""

    @classmethod
    def from_fields(cls, fields: Mapping[str, object]) -> CollectRequest:
        """Validate the raw form values (``None`` for an absent field).

        ``lot_id`` is not read. Raises:
            InvalidCollectFieldError: any rule of section 4.1 is broken.
        """
        item_id = fields.get("item_id")
        if not isinstance(item_id, str) or not re.fullmatch(ITEM_ID_PATTERN, item_id, re.ASCII):
            raise InvalidCollectFieldError("item_id")

        raw_type = fields.get("object_type")
        if not isinstance(raw_type, str) or raw_type not in _OBJECT_TYPE_VALUES:
            raise InvalidCollectFieldError("object_type")
        object_type = DatasetObjectType(raw_type)
        if ITEM_PREFIX_TYPES.get(item_id[0]) is not object_type:
            raise InvalidCollectFieldError("item_id", "item_id prefix does not match object_type")

        grade = _parse_grade(fields.get("grade"), object_type)

        labeler = fields.get("labeler")
        if not isinstance(labeler, str) or labeler not in LABELERS:
            raise InvalidCollectFieldError("labeler")

        raw_angle = fields.get("angle")
        if not isinstance(raw_angle, str) or not re.fullmatch(ANGLE_PATTERN, raw_angle):
            raise InvalidCollectFieldError("angle")

        notes = fields.get("notes")
        if notes is None:
            notes = ""
        if not isinstance(notes, str) or not _valid_notes(notes):
            raise InvalidCollectFieldError("notes")

        return cls(
            item_id=item_id,
            object_type=object_type,
            grade=grade,
            labeler=labeler,
            angle=int(raw_angle),
            notes=notes,
        )


def _parse_grade(value: object, object_type: DatasetObjectType) -> Grade | None:
    """Absent or empty for ``other``; one of the 5 ``Grade`` values for ``screw``/``nut``."""
    if value is not None and not isinstance(value, str):
        raise InvalidCollectFieldError("grade")
    if object_type is DatasetObjectType.OTHER:
        if value:
            raise InvalidCollectFieldError("grade", "grade must be empty for other")
        return None
    if value not in GRADE_VALUES:
        raise InvalidCollectFieldError("grade")
    return Grade(value)


def _valid_notes(notes: str) -> bool:
    if len(notes) > NOTES_MAX_LENGTH:
        return False
    return not any(unicodedata.category(char) in _FORBIDDEN_NOTE_CATEGORIES for char in notes)


@dataclass(frozen=True)
class CollectResult:
    """What a stored capture answers (section 4.2, item 3)."""

    image_path: str
    item_id: str
    angle: int
    item_images: int


# ------------------------------------------------------------------------------------- coverage


@dataclass(frozen=True)
class CoverageCell:
    """One row of the console coverage table (section 4.4)."""

    object_type: str
    grade: str | None
    images: int
    items: int
    target_images: int
    target_items: int

    @property
    def complete(self) -> bool:
        """Both targets reached."""
        return self.images >= self.target_images and self.items >= self.target_items


_CellKey = tuple[str, str | None]


def _coverage_keys() -> list[_CellKey]:
    graded = [
        (object_type.value, grade.value)
        for object_type in (DatasetObjectType.SCREW, DatasetObjectType.NUT)
        for grade in GRADE_ORDER
    ]
    return [*graded, (DatasetObjectType.OTHER.value, None)]


def _cells(
    images: Mapping[_CellKey, int], items: Mapping[_CellKey, set[str]]
) -> list[CoverageCell]:
    cells = []
    for key in _coverage_keys():
        is_other = key[1] is None
        cells.append(
            CoverageCell(
                object_type=key[0],
                grade=key[1],
                images=images.get(key, 0),
                items=len(items.get(key, ())),
                target_images=OTHER_TARGET_IMAGES if is_other else GRADED_TARGET_IMAGES,
                target_items=OTHER_TARGET_ITEMS if is_other else GRADED_TARGET_ITEMS,
            )
        )
    return cells


def empty_coverage() -> list[CoverageCell]:
    """The 11 cells with zero images and items."""
    return _cells({}, {})


def compute_coverage(manifest_path: Path) -> list[CoverageCell]:
    """Images and distinct ``item_id`` per cell: ``screw`` x 5 grades, ``nut`` x 5, ``other``.

    A missing manifest gives the zeroed table. Rows that fit no cell (unknown type, missing or
    unknown grade for ``screw``/``nut``, no ``item_id``) are not counted; any ``other`` row
    counts in the ``other`` cell.

    Raises:
        OSError, UnicodeDecodeError, csv.Error: the manifest exists but cannot be read.
    """
    images: dict[_CellKey, int] = {}
    items: dict[_CellKey, set[str]] = {}
    try:
        handle = manifest_path.open(encoding="utf-8", newline="")
    except FileNotFoundError:
        return empty_coverage()
    with handle:
        for row in csv.DictReader(handle):
            key = _coverage_key(row)
            if key is None:
                continue
            images[key] = images.get(key, 0) + 1
            items.setdefault(key, set()).add(row["item_id"])
    return _cells(images, items)


def _coverage_key(row: Mapping[str, str | None]) -> _CellKey | None:
    if not row.get("item_id"):
        return None
    object_type = row.get("object_type")
    if object_type == DatasetObjectType.OTHER.value:
        return (object_type, None)
    grade = row.get("grade")
    if object_type in _OBJECT_TYPE_VALUES and grade in GRADE_VALUES:
        return (object_type, grade)
    return None


# --------------------------------------------------------------------------------------- writer


def _set_mode(path: Path, mode: int, fd: int | None = None) -> None:
    """Exact mode on something this module created; a failure is a WARNING, not an error."""
    try:
        if fd is None:
            os.chmod(path, mode)
        else:
            os.fchmod(fd, mode)
    except OSError as exc:
        logger.warning("cannot set mode %s on %s: %s", oct(mode), path, exc.strerror or exc)


def _make_dirs(path: Path) -> None:
    """Create ``path`` and its missing parents; only the ones created here get ``0700``."""
    missing: list[Path] = []
    current = path
    while not os.path.lexists(current):
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=DIR_MODE)
        except FileExistsError:  # created meanwhile by someone else: not ours, left as it is
            continue
        _set_mode(directory, DIR_MODE)


def _open_file(path: Path, flags: int) -> tuple[int, bool]:
    """Open ``path`` (never through a symlink), creating it with ``0600`` when missing.

    Returns the descriptor and whether this call created the file.
    """
    try:
        fd = os.open(path, flags | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, FILE_MODE)
    except FileExistsError:
        return os.open(path, flags | os.O_NOFOLLOW), False
    _set_mode(path, FILE_MODE, fd)
    return fd, True


def _csv_line(values: tuple[str, ...]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\n").writerow(values)
    return buffer.getvalue()


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        view = view[written:]


class DatasetWriter:
    """Stores collect-mode captures under ``dataset_dir`` (section 4.2).

    One instance per app. A ``threading.Lock`` serialises the threads of this process and an
    ``fcntl.flock`` on ``manifest.csv.lock`` serialises processes (POSIX only).
    """

    def __init__(self, dataset_dir: Path, *, clock: Callable[[], datetime]) -> None:
        self._root = dataset_dir
        self._clock = clock
        self._lock = threading.Lock()

    @property
    def manifest_path(self) -> Path:
        return self._root / MANIFEST_NAME

    def coverage(self) -> list[CoverageCell]:
        """``compute_coverage`` of the manifest, never in the middle of a write of this process."""
        with self._lock:
            return compute_coverage(self.manifest_path)

    def write(
        self, request: CollectRequest, data: bytes, image: Image.Image, capture_device: str
    ) -> CollectResult:
        """Save the image and append its manifest row.

        ``data`` is the uploaded file and ``image`` its decoded form (``load_capture_image``):
        a JPEG is written as received, a PNG re-encoded as JPEG q=90.

        Raises:
            ManifestHeaderMismatchError, ManifestUnreadableError: 500, nothing written.
            ItemTypeConflictError, CaptureExistsError: 409, nothing written.
            DatasetWriteError: 500; an image already written is removed.
        """
        try:
            with self._lock:
                _make_dirs(self._root)
                with self._file_lock():
                    return self._write_locked(request, data, image, capture_device)
        except OSError as exc:
            logger.error("collect not stored: %s (%s)", type(exc).__name__, exc.strerror or exc)
            raise DatasetWriteError() from exc

    @contextlib.contextmanager
    def _file_lock(self) -> Iterator[None]:
        fd, _ = _open_file(self._root / MANIFEST_LOCK_NAME, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)  # also releases the flock

    def _write_locked(
        self, request: CollectRequest, data: bytes, image: Image.Image, capture_device: str
    ) -> CollectResult:
        rows = self._read_manifest()  # 1. header
        if any(  # 2. same item_id with another object_type
            item_id == request.item_id and object_type != request.object_type.value
            for item_id, object_type in rows
        ):
            raise ItemTypeConflictError()

        ts = self._clock().astimezone(UTC)  # 3. path
        grade_dir = request.grade.value if request.grade is not None else NO_GRADE_DIR
        file_name = f"{request.item_id}__{request.angle}__{ts.strftime(FILE_TIMESTAMP_FORMAT)}.jpg"
        image_path = f"{RAW_SUBDIR}/{request.object_type.value}/{grade_dir}/{file_name}"
        target = self._root / RAW_SUBDIR / request.object_type.value / grade_dir / file_name
        if os.path.lexists(target):
            raise CaptureExistsError()

        _make_dirs(target.parent)
        self._save_image(target, data, image)  # 4. image
        row = (
            image_path,
            request.item_id,
            request.object_type.value,
            request.grade.value if request.grade is not None else "",
            request.labeler,
            str(request.angle),
            ts.strftime(CAPTURED_AT_FORMAT),
            capture_device[:CAPTURE_DEVICE_MAX_LENGTH],
            request.notes,
        )
        try:
            self._append(row)  # 5. manifest
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        item_images = 1 + sum(1 for item_id, _ in rows if item_id == request.item_id)
        logger.info(
            "collect saved image_path=%s item_id=%s item_images=%d",
            image_path,
            request.item_id,
            item_images,
        )
        return CollectResult(
            image_path=image_path,
            item_id=request.item_id,
            angle=request.angle,
            item_images=item_images,
        )

    def _read_manifest(self) -> list[tuple[str, str]]:
        """``(item_id, object_type)`` of every row; ``[]`` when the manifest does not exist.

        Raises:
            ManifestHeaderMismatchError: the first line is not the header of section 4.2
                (including a BOM, an empty file or a first line that is not UTF-8).
            ManifestUnreadableError: the rows are not valid UTF-8 CSV.
        """
        try:
            raw = self.manifest_path.read_bytes()
        except FileNotFoundError:
            return []
        first_line, _, rest = raw.partition(b"\n")
        try:
            header = next(csv.reader([first_line.decode("utf-8")]), None)
        except (UnicodeDecodeError, csv.Error):
            raise ManifestHeaderMismatchError() from None
        if header != list(MANIFEST_COLUMNS):
            raise ManifestHeaderMismatchError()
        try:
            reader = csv.reader(io.StringIO(rest.decode("utf-8"), newline=""))
            return [(row[1], row[2]) for row in reader if len(row) >= 3]
        except (UnicodeDecodeError, csv.Error):
            raise ManifestUnreadableError() from None

    def _save_image(self, target: Path, data: bytes, image: Image.Image) -> None:
        """Temporary file (``0600``) in the same directory, then ``rename`` (keeps the mode)."""
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                _set_mode(tmp, FILE_MODE, handle.fileno())
                write_capture_jpeg(handle, data, image)
                handle.flush()
                os.fsync(handle.fileno())
            os.rename(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _append(self, row: tuple[str, ...]) -> None:
        """Append ``row``; creates the manifest (``0600``, with the header) when missing.

        On failure the manifest goes back to its previous size (or is removed when this call
        created it), so a half-written row never stays behind.
        """
        line = _csv_line(row)
        fd, created = _open_file(self.manifest_path, os.O_RDWR | os.O_APPEND)
        size = 0
        try:
            size = os.fstat(fd).st_size
            if created:
                line = _csv_line(MANIFEST_COLUMNS) + line
            elif size > 0 and os.pread(fd, 1, size - 1) != b"\n":
                line = "\n" + line  # a hand-edited manifest without the final line break
            _write_all(fd, line.encode("utf-8"))
            os.fsync(fd)
        except BaseException:
            if created:
                self.manifest_path.unlink(missing_ok=True)
            else:
                with contextlib.suppress(OSError):
                    os.ftruncate(fd, size)
            raise
        finally:
            os.close(fd)
