"""``python -m qc_edge.importer``: photos that did not come from the ``/capture`` page (SPEC-036).

ADR-020 admits in the dataset photos taken by acquaintances (origin ``contributor``) and
licensed external images (origin ``external``, ``item_id`` ``X<type>-NNNN``, only for training).
This CLI is the only way such a file enters ``DATASET_DIR``::

    python -m qc_edge.importer --dataset-dir <D> --inbox <I> --plan <P> --privacy-checked
                               [--external-sources <R>] [--dry-run]

* **Phase 1** validates the whole plan (a CSV filled in by the pair) before anything is
  written: every cell, every input file (inside ``--inbox``, regular, never a symlink, at most
  ``IMPORT_MAX_BYTES``), the rows against each other and against the dataset. Any problem exits
  with 2 and writes nothing; each problem is one ``plan line <n>: <code> (<column>)`` line on
  the stderr, never with the cell value. A row whose input SHA-256 is already in ``sources.csv``
  (and whose image is not in ``exclusions.csv``) is skipped, so a run interrupted halfway can
  simply be repeated.
* **Phase 2** normalises each image like the page does (``normalize_imported_image``: EXIF
  rotation applied, longest side up to 1280 px, JPEG q=90 without metadata, then checked), one
  image at a time and outside the lock, and stores it with the writers of the collect mode
  (``qc_edge.collect``): the same ``flock`` on ``manifest.csv.lock`` (per row, never for the
  whole plan), ``0700``/``0600`` modes whatever the ``umask``, temporary file, ``fsync`` and
  ``rename``. The manifest row is appended before the ``sources.csv`` row, and a failure of the
  second one rolls back the first (SPEC-036 section 4.4).

Since SPEC-038: the inbox and the plan are refused inside a Git repository (section 4.7); the
image is saved without the metadata inherited from the input (a PNG ``comment``, section 4.3);
the directories created for a row that fails are removed (section 4.5); a hash imported by
another run meanwhile is skipped under the lock (section 4.6); and the ``PIL`` logger stays at
``INFO`` at least (section 4.4).

The input files are only read: never changed, renamed nor deleted, and their bytes (with the
EXIF) are never written under ``DATASET_DIR`` nor printed; only their SHA-256 enters the dataset
(R-14). Nothing here opens a network connection (R-02). Every path printed goes through
``printable_path`` (SPEC-030 section 4.5), and an invalid command line is logged with option
names only (SPEC-025 section 4.5).
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import logging
import os
import re
import stat
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from PIL import Image

import qc_edge
from qc_edge import jpeg
from qc_edge.argv import (
    EXIT_USAGE_ERROR,
    ArgumentsError,
    QuietArgumentParser,
    describe_arguments,
    resolve_argv,
)
from qc_edge.collect import (
    CAPTURED_AT_FORMAT,
    FILE_TIMESTAMP_FORMAT,
    GRADE_VALUES,
    GRADED_DATASET_TYPES,
    LABELERS,
    MANIFEST_COLUMNS,
    MANIFEST_NAME,
    NO_GRADE_DIR,
    RAW_SUBDIR,
    CsvHeaderMismatchError,
    CsvUnreadableError,
    DatasetObjectType,
    DatasetWriteError,
    ItemTypeConflictError,
    ManifestEntry,
    ManifestHeaderMismatchError,
    ManifestUnreadableError,
    append_csv_row,
    has_forbidden_char,
    item_prefix_matches,
    manifest_file_lock,
    read_csv_rows,
    read_manifest_entries,
    rollback_append,
    valid_notes,
    write_private_file_atomically,
)
from qc_edge.fsutil import fsync_dir, make_private_dirs
from qc_edge.privacy import limit_pil_logging, printable_path
from qc_preprocess import InvalidImageError, PreprocessParams, load_image

logger = logging.getLogger("qc_edge.importer")

EXIT_OK = 0
EXIT_FAILED = 1

# ------------------------------------------------------------------------------------ formats

PLAN_COLUMNS: tuple[str, ...] = (
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
PLAN_MAX_BYTES = 5 * 1024 * 1024
PLAN_MAX_ROWS = 5000

# SPEC-035 section 4.2; equal to ``qc_ml.data`` (CA-15), which ``qc_edge`` does not import.
SOURCES_NAME = "sources.csv"
SOURCES_COLUMNS: tuple[str, ...] = (
    "image_path",
    "origin",
    "contributor",
    "source_id",
    "source_ref",
    "input_sha256",
)
# SPEC-035 section 4.3 (``ml/external_sources.csv``, in Git) and ADR-020, decision 3.
EXTERNAL_SOURCES_COLUMNS: tuple[str, ...] = (
    "source_id",
    "title",
    "url",
    "license",
    "license_url",
    "attribution",
    "retrieved_at",
)
ALLOWED_LICENSES: tuple[str, ...] = (
    "CC0-1.0",
    "PDDL-1.0",
    "CC-BY-4.0",
    "MIT",
    "Apache-2.0",
    "BSD-3-Clause",
)
# SPEC-011 section 4.1 (``docs/dataset-protocol.md`` section 8.1).
EXCLUSIONS_NAME = "exclusions.csv"
EXCLUSIONS_COLUMNS: tuple[str, ...] = ("image_path", "reason")

# ``edge/src/qc_edge/__init__.py`` -> repository root -> ``ml/external_sources.csv``.
DEFAULT_EXTERNAL_SOURCES = (
    Path(qc_edge.__file__).resolve().parents[3] / "ml" / "external_sources.csv"
)

ORIGIN_CONTRIBUTOR = "contributor"
ORIGIN_EXTERNAL = "external"
ORIGINS = frozenset({ORIGIN_CONTRIBUTOR, ORIGIN_EXTERNAL})
# Whole-string patterns, always with ``re.fullmatch`` (SPEC-036 section 4.2).
# ``T``/``XT``: hand tools (SPEC-016 section 4.4).
CONTRIBUTOR_ITEM_PATTERN = r"[SNOT]-[0-9]{3}"
EXTERNAL_ITEM_PATTERN = r"X[SNOT]-[0-9]{4}"
CONTRIBUTOR_PATTERN = r"c[0-9]{2}"
SOURCE_ID_PATTERN = r"[a-z0-9][a-z0-9-]{2,39}"
ANGLE_PATTERN = r"[0-4]"
SOURCE_REF_MAX_LENGTH = 200
FILE_MAX_LENGTH = 255
IMPORT_MAX_BYTES = 40 * 1024 * 1024
_OBJECT_TYPE_VALUES = frozenset(member.value for member in DatasetObjectType)
_GRADED_TYPES = frozenset(member.value for member in GRADED_DATASET_TYPES)

# ------------------------------------------------------------------------------ normalisation

MAX_LONG_SIDE = 1280
# The ``resize_shorter`` of ``preprocessing.json``: a smaller image would be upscaled.
MIN_SHORT_SIDE = PreprocessParams().resize_shorter
OUTPUT_JPEG_QUALITY = 90
# The table of ``ImageOps.exif_transpose``.
ORIENTATION_TRANSPOSE: dict[int, Image.Transpose] = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}

# ------------------------------------------------------------------------------------- writing

CAPTURE_DEVICE = "qc-edge-import"
NAME_ATTEMPTS = 3
RETRY_DELAY_S = 1.0

# Reasons of a ``failed <file>: <reason>`` line (SPEC-036 sections 4.3 and 4.4).
REASON_UNSUPPORTED_IMAGE = "unsupported image"
REASON_TOO_MANY_SCANS = "too many JPEG scans"
REASON_UNSUPPORTED_JPEG = "unsupported JPEG structure"
REASON_TOO_SMALL = "image too small"
REASON_CHECK_FAILED = "normalization check failed"
REASON_CAPTURE_EXISTS = "capture already exists"
REASON_ITEM_CONFLICT = ItemTypeConflictError.detail
REASON_WRITE_FAILED = DatasetWriteError.detail
REASON_INPUT_CHANGED = "input changed since validation"
_SCANS_TEXT = "JPEG scans"  # guaranteed in the message of the scan-limit error (SPEC-024)

# Fixed messages of the exit code 2 (never with a value of the command line or of the plan).
MISSING_PRIVACY_MESSAGE = (
    "missing --privacy-checked: check every photo by eye first "
    "(docs/dataset-protocol.md section 10.5)"
)
INBOX_NOT_DIR_MESSAGE = "--inbox must be an existing directory"
INBOX_INSIDE_MESSAGE = "inbox must be outside the dataset"
INBOX_IN_GIT_MESSAGE = "inbox must be outside any git repository"
PLAN_IN_GIT_MESSAGE = "plan must be outside any git repository"
GIT_ENTRY_NAME = ".git"
DATASET_NOT_DIR_MESSAGE = "--dataset-dir must be a directory"
PLAN_NOT_READABLE_MESSAGE = "cannot read --plan"
REGISTRY_NOT_FOUND_MESSAGE = "external sources registry not found"
REGISTRY_UNREADABLE_MESSAGE = "external sources registry unreadable"
MANIFEST_MISMATCH_MESSAGE = ManifestHeaderMismatchError.detail  # "manifest header mismatch"
MANIFEST_UNREADABLE_MESSAGE = ManifestUnreadableError.detail
SOURCES_MISMATCH_MESSAGE = "sources header mismatch"
SOURCES_UNREADABLE_MESSAGE = "sources unreadable"
EXCLUSIONS_MISMATCH_MESSAGE = "exclusions header mismatch"
EXCLUSIONS_UNREADABLE_MESSAGE = "exclusions unreadable"
DATASET_UNREADABLE_MESSAGE = "cannot read the dataset files"
# Column shown for a problem of the whole record or file (no single column).
NO_COLUMN = "-"


# ------------------------------------------------------------------------------------- errors


class ImageRejectedError(ValueError):
    """An image of one plan row that is not imported; the other rows go on (section 4.6).

    ``reason`` is one of the fixed ``REASON_*`` texts, never a value of the image.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class UsageError(Exception):
    """Exit code 2 before anything is written; ``message`` is one of the fixed texts above."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class PlanProblem:
    """One problem of phase 1 (section 4.2). ``line`` is the CSV record number (header = 1)."""

    line: int
    code: str
    column: str

    def __str__(self) -> str:
        return f"plan line {self.line}: {self.code} ({self.column})"


class PlanError(Exception):
    """Phase 1 found problems: exit code 2, nothing written."""

    def __init__(self, problems: Sequence[PlanProblem]) -> None:
        self.problems = list(problems)
        super().__init__(f"{len(self.problems)} plan problem(s)")


class _RowFailed(Exception):
    """One row is not imported, the others go on (exit code 1 at the end)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _AlreadyImported(Exception):
    """The input hash entered ``sources.csv`` after phase 1 (another run): the row is skipped."""


class _ImportStopped(Exception):
    """The import stops at once (I/O failure, header changed meanwhile): exit code 1."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# ------------------------------------------------------------------------------ normalisation


def normalize_imported_image(data: bytes) -> tuple[bytes, int, int]:
    """The image of ``data`` as the ``/capture`` page would store it (SPEC-036 section 4.3).

    A JPEG gets its EXIF orientation read first (it lives in the APP1), then its private
    segments removed structurally (APP1, APP13, COM and everything after the EOI, such as the
    video of a Motion Photo) before ``qc_preprocess.load_image`` (whose limits apply to the
    cleaned bytes), and the orientation applied with the table of ``ImageOps.exif_transpose``.
    Any other content goes to ``load_image`` as is (only PNG is accepted). The longest side is
    then reduced to ``MAX_LONG_SIDE`` (integer rounding, LANCZOS), and the image is encoded as
    JPEG q=90 without EXIF, ICC profile, progressive nor optimised coding, and checked.

    Returns:
        ``(jpeg, width, height)``.

    Raises:
        ImageRejectedError: ``unsupported image``, ``too many JPEG scans``,
            ``unsupported JPEG structure``, ``image too small`` or ``normalization check failed``.
    """
    if data.startswith(jpeg.JPEG_SIGNATURE):
        try:
            orientation = jpeg.exif_orientation(data)
            cleaned = jpeg.strip_private_segments(data)
        except jpeg.JpegStructureError:
            raise ImageRejectedError(REASON_UNSUPPORTED_JPEG) from None
        image = _load(cleaned)
        transpose = ORIENTATION_TRANSPOSE.get(orientation)
        if transpose is not None:
            image = image.transpose(transpose)
    else:
        image = _load(data)

    width, height = reduced_size(*image.size)
    if (width, height) != image.size:
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    if min(width, height) < MIN_SHORT_SIDE:
        raise ImageRejectedError(REASON_TOO_SMALL)

    buffer = io.BytesIO()
    # Nothing inherited from the input goes to the encoder, such as the ``comment`` of a PNG
    # text chunk, which Pillow would write as a COM segment (SPEC-038 section 4.3).
    image.info.clear()
    image.save(buffer, "JPEG", quality=OUTPUT_JPEG_QUALITY)
    output = buffer.getvalue()
    if not _output_is_clean(output, (width, height)):
        raise ImageRejectedError(REASON_CHECK_FAILED)
    return output, width, height


def _load(data: bytes) -> Image.Image:
    try:
        return load_image(data)
    except InvalidImageError as exc:
        reason = REASON_TOO_MANY_SCANS if _SCANS_TEXT in str(exc) else REASON_UNSUPPORTED_IMAGE
        raise ImageRejectedError(reason) from None


def reduced_size(width: int, height: int) -> tuple[int, int]:
    """``(width, height)`` with the longest side at most ``MAX_LONG_SIDE`` (section 4.3, step 2).

    With ``L`` the longest and ``C`` the shortest side and ``L > MAX_LONG_SIDE``, the longest
    becomes ``MAX_LONG_SIDE`` and the shortest ``(C * MAX_LONG_SIDE + L // 2) // L`` (integer
    arithmetic). Otherwise the size does not change.
    """
    longest, shortest = max(width, height), min(width, height)
    if longest <= MAX_LONG_SIDE:
        return width, height
    reduced = (shortest * MAX_LONG_SIDE + longest // 2) // longest
    return (MAX_LONG_SIDE, reduced) if width >= height else (reduced, MAX_LONG_SIDE)


def _output_is_clean(output: bytes, size: tuple[int, int]) -> bool:
    """Step 5: no private segment, no EXIF rotation and ``load_image`` gives the same size."""
    try:
        return (
            jpeg.jpeg_private_findings(output) == frozenset()
            and not jpeg.has_exif_rotation(output)
            and load_image(output).size == size
        )
    except (jpeg.JpegStructureError, InvalidImageError):
        return False


# ------------------------------------------------------------------------------------ phase 1


@dataclass(frozen=True)
class PlanRow:
    """A valid plan row, ready for phase 2."""

    line: int
    file: str
    path: Path  # ``realpath`` inside ``--inbox``
    item_id: str
    object_type: str
    grade: str
    labeler: str
    angle: int
    origin: str
    contributor: str
    source_id: str
    source_ref: str
    notes: str
    input_sha256: str
    skip: bool


def _read_input(path: Path) -> bytes:
    """The bytes of an input file: never through a symlink, only a regular file, bounded.

    ``O_NONBLOCK`` keeps a FIFO swapped in after the ``lstat`` from blocking the CLI.

    Raises:
        OSError: cannot open or read, not a regular file, or above ``IMPORT_MAX_BYTES``.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > IMPORT_MAX_BYTES:
            raise OSError("input is not a regular file within the size limit")
        data = handle.read(IMPORT_MAX_BYTES + 1)
    if len(data) > IMPORT_MAX_BYTES:
        raise OSError("input is above the size limit")
    return data


def _file_problem(value: str, inbox: Path) -> tuple[str | None, Path | None]:
    """The ``file`` rule of section 4.2: ``(code, None)`` or ``(None, realpath)``."""
    if (
        not value
        or len(value) > FILE_MAX_LENGTH
        or "\\" in value
        or "\x00" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        return "invalid_file", None
    candidate = os.path.join(inbox, value)
    try:
        info = os.lstat(candidate)
    except (FileNotFoundError, NotADirectoryError):
        return "file_not_found", None
    except OSError:
        return "invalid_file", None
    real = Path(os.path.realpath(candidate))
    if real == inbox or not real.is_relative_to(inbox):
        return "invalid_file", None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return "invalid_file", None
    if info.st_size > IMPORT_MAX_BYTES:
        return "file_too_large", None
    return None, real


def _item_formats(item_id: str) -> tuple[bool, bool]:
    """Whether ``item_id`` matches the contributor format and the external format."""
    own = re.fullmatch(CONTRIBUTOR_ITEM_PATTERN, item_id, re.ASCII) is not None
    external = re.fullmatch(EXTERNAL_ITEM_PATTERN, item_id, re.ASCII) is not None
    return own, external


def _item_problem(item_id: str, origin: str) -> str | None:
    own, external = _item_formats(item_id)
    if origin == ORIGIN_CONTRIBUTOR:
        expected, other = own, external
    elif origin == ORIGIN_EXTERNAL:
        expected, other = external, own
    else:  # ``invalid_origin`` is reported on its own column
        expected, other = own or external, False
    if expected:
        return None
    return "origin_item_mismatch" if other else "invalid_item_id"


def _object_type_problem(object_type: str, item_id: str) -> str | None:
    if object_type not in _OBJECT_TYPE_VALUES:
        return "invalid_object_type"
    own, external = _item_formats(item_id)
    if not own and not external:
        return None  # the item_id problem is already reported
    letter = item_id[1] if external else item_id[0]
    if not item_prefix_matches(letter, object_type):
        return "item_prefix_mismatch"
    return None


def _grade_problem(grade: str, object_type: str) -> str | None:
    if object_type == DatasetObjectType.OTHER.value:
        return "grade_on_other" if grade else None
    if object_type in _GRADED_TYPES:
        if not grade:
            return "missing_grade"
        return None if grade in GRADE_VALUES else "invalid_grade"
    return "invalid_grade" if grade and grade not in GRADE_VALUES else None


def _row_problems(cells: dict[str, str], registry: dict[str, str] | None) -> list[tuple[str, str]]:
    """``(column, code)`` of the cell rules of section 4.2 (``file`` aside), in column order."""
    problems: list[tuple[str, str]] = []

    def add(column: str, code: str | None) -> None:
        if code is not None:
            problems.append((column, code))

    origin = cells["origin"]
    item_id = cells["item_id"]
    object_type = cells["object_type"]
    add("item_id", _item_problem(item_id, origin))
    add("object_type", _object_type_problem(object_type, item_id))
    add("grade", _grade_problem(cells["grade"], object_type))
    add("labeler", None if cells["labeler"] in LABELERS else "invalid_labeler")
    add("angle", None if re.fullmatch(ANGLE_PATTERN, cells["angle"]) else "invalid_angle")
    add("origin", None if origin in ORIGINS else "invalid_origin")

    contributor, source_id, source_ref = (
        cells["contributor"],
        cells["source_id"],
        cells["source_ref"],
    )
    if origin == ORIGIN_CONTRIBUTOR:
        if not re.fullmatch(CONTRIBUTOR_PATTERN, contributor, re.ASCII):
            add("contributor", "invalid_contributor")
        if source_id:
            add("source_id", "source_fields_mismatch")
        if source_ref:
            add("source_ref", "source_fields_mismatch")
    elif origin == ORIGIN_EXTERNAL:
        if contributor:
            add("contributor", "invalid_contributor")
        add("source_id", _source_id_problem(source_id, registry or {}))
        if not 1 <= len(source_ref) <= SOURCE_REF_MAX_LENGTH or has_forbidden_char(source_ref):
            add("source_ref", "invalid_source_ref")
    add("notes", None if valid_notes(cells["notes"]) else "invalid_notes")
    return problems


def _source_id_problem(source_id: str, registry: dict[str, str]) -> str | None:
    if not re.fullmatch(SOURCE_ID_PATTERN, source_id, re.ASCII):
        return "invalid_source_id"
    license_id = registry.get(source_id)
    if license_id is None:
        return "unknown_source_id"
    if license_id not in ALLOWED_LICENSES:
        return "source_license_not_allowed"
    return None


def _load_registry(path: Path) -> dict[str, str]:
    """``source_id`` -> ``license`` of the registry (SPEC-035 section 4.3).

    Raises:
        UsageError: missing (``external sources registry not found``), or another header, rows
            with another number of fields, a repeated ``source_id`` or not UTF-8 CSV.
    """
    if not path.is_file():
        raise UsageError(REGISTRY_NOT_FOUND_MESSAGE)
    try:
        rows = read_csv_rows(path, EXTERNAL_SOURCES_COLUMNS)
    except (CsvHeaderMismatchError, CsvUnreadableError, OSError):
        raise UsageError(REGISTRY_UNREADABLE_MESSAGE) from None
    if rows is None:
        raise UsageError(REGISTRY_NOT_FOUND_MESSAGE)
    registry: dict[str, str] = {}
    for row in rows:
        if len(row) != len(EXTERNAL_SOURCES_COLUMNS) or row[0] in registry:
            raise UsageError(REGISTRY_UNREADABLE_MESSAGE)
        registry[row[0]] = row[3]
    return registry


@dataclass(frozen=True)
class _DatasetState:
    """What phase 1 reads from ``DATASET_DIR`` (nothing is created)."""

    manifest: list[ManifestEntry]
    imported_hashes: frozenset[str]


def _read_dataset(dataset_dir: Path) -> _DatasetState:
    """Headers of ``manifest.csv`` and ``sources.csv``, and the hashes already imported.

    A hash counts as imported when its ``sources.csv`` row is not of an image of
    ``exclusions.csv`` (a photo excluded by mistake can be imported again).

    Raises:
        UsageError: another header, unreadable rows or a read error.
    """
    try:
        manifest = read_manifest_entries(dataset_dir / MANIFEST_NAME)
        sources = _read_or_usage(
            dataset_dir / SOURCES_NAME,
            SOURCES_COLUMNS,
            SOURCES_MISMATCH_MESSAGE,
            SOURCES_UNREADABLE_MESSAGE,
        )
        exclusions = _read_or_usage(
            dataset_dir / EXCLUSIONS_NAME,
            EXCLUSIONS_COLUMNS,
            EXCLUSIONS_MISMATCH_MESSAGE,
            EXCLUSIONS_UNREADABLE_MESSAGE,
        )
    except ManifestHeaderMismatchError:
        raise UsageError(MANIFEST_MISMATCH_MESSAGE) from None
    except ManifestUnreadableError:
        raise UsageError(MANIFEST_UNREADABLE_MESSAGE) from None
    except OSError as exc:
        logger.error("cannot read the dataset: %s", exc.strerror or type(exc).__name__)
        raise UsageError(DATASET_UNREADABLE_MESSAGE) from None
    excluded = {row[0] for row in exclusions if row}
    imported = frozenset(
        row[5] for row in sources if len(row) == len(SOURCES_COLUMNS) and row[0] not in excluded
    )
    return _DatasetState(manifest=manifest, imported_hashes=imported)


def _read_or_usage(
    path: Path, columns: tuple[str, ...], mismatch: str, unreadable: str
) -> list[list[str]]:
    try:
        rows = read_csv_rows(path, columns)
    except CsvHeaderMismatchError:
        raise UsageError(mismatch) from None
    except CsvUnreadableError:
        raise UsageError(unreadable) from None
    return [] if rows is None else rows


def _read_plan(plan: Path) -> tuple[list[tuple[int, list[str]]], list[PlanProblem]]:
    """The data records of the plan with their record numbers, or the structural problems.

    Raises:
        UsageError: the plan cannot be opened.
    """
    try:
        with plan.open("rb") as handle:
            raw = handle.read(PLAN_MAX_BYTES + 1)
    except OSError:
        raise UsageError(PLAN_NOT_READABLE_MESSAGE) from None
    if len(raw) > PLAN_MAX_BYTES:
        return [], [PlanProblem(1, "unreadable_csv", NO_COLUMN)]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [], [PlanProblem(1, "unreadable_csv", NO_COLUMN)]

    records: list[tuple[int, list[str]]] = []
    reader = csv.reader(io.StringIO(text, newline=""))
    number = 0
    try:
        header = next(reader, None)
        number = 1
        if header != list(PLAN_COLUMNS):
            present = set(header or ())
            missing = [column for column in PLAN_COLUMNS if column not in present]
            return [], [PlanProblem(1, "missing_column", column) for column in missing] or [
                PlanProblem(1, "missing_column", NO_COLUMN)
            ]
        for record in reader:
            number += 1
            if number - 1 > PLAN_MAX_ROWS:
                return [], [PlanProblem(number, "too_many_rows", NO_COLUMN)]
            records.append((number, record))
    except csv.Error:
        return [], [PlanProblem(number + 1, "unreadable_csv", NO_COLUMN)]
    return records, []


def inside_git_repository(path: Path) -> bool:
    """Whether ``path`` or a directory above it, up to the root, has a ``.git`` entry.

    The entry may be a directory or a file (a worktree), checked with ``os.path.lexists``
    (SPEC-038 section 4.7). ``path`` is used as given: the caller resolves it first.
    """
    return any(os.path.lexists(directory / GIT_ENTRY_NAME) for directory in (path, *path.parents))


def load_plan(
    *, dataset_dir: Path, inbox: Path, plan: Path, external_sources: Path
) -> list[PlanRow]:
    """Phase 1 (SPEC-036 sections 4.1 and 4.2): validate everything, write nothing.

    Before the dataset and the plan are read, the inbox (after ``realpath``) and the directory
    of the plan (after the ``realpath`` of the plan) must be outside any Git repository
    (SPEC-038 section 4.7): a ``git add -A`` would publish photos of third parties with their
    EXIF. ``external_sources`` and ``dataset_dir`` are not checked.

    Raises:
        UsageError: a fixed message (exit code 2).
        PlanError: the problems of the plan (exit code 2).
    """
    if not inbox.is_dir():
        raise UsageError(INBOX_NOT_DIR_MESSAGE)
    inbox_real = Path(os.path.realpath(inbox))
    dataset_real = Path(os.path.realpath(dataset_dir))
    if inbox_real.is_relative_to(dataset_real) or dataset_real.is_relative_to(inbox_real):
        raise UsageError(INBOX_INSIDE_MESSAGE)
    if inside_git_repository(inbox_real):
        raise UsageError(INBOX_IN_GIT_MESSAGE)
    if inside_git_repository(Path(os.path.realpath(plan)).parent):
        raise UsageError(PLAN_IN_GIT_MESSAGE)
    if os.path.lexists(dataset_dir) and not dataset_dir.is_dir():
        raise UsageError(DATASET_NOT_DIR_MESSAGE)
    state = _read_dataset(dataset_dir)

    records, problems = _read_plan(plan)
    if problems:
        raise PlanError(problems)
    registry = None
    if any(
        len(record) == len(PLAN_COLUMNS) and record[PLAN_COLUMNS.index("origin")] == ORIGIN_EXTERNAL
        for _, record in records
    ):
        registry = _load_registry(external_sources)

    column_order = {column: index for index, column in enumerate(PLAN_COLUMNS)}
    found: list[tuple[int, int, PlanProblem]] = []

    def add(line: int, column: str, code: str) -> None:
        found.append(
            (line, column_order.get(column, len(column_order)), PlanProblem(line, code, column))
        )

    manifest_types: dict[str, set[str]] = {}
    for entry in state.manifest:
        manifest_types.setdefault(entry.item_id, set()).add(entry.object_type)
    plan_types: dict[str, str] = {}
    seen_files: set[str] = set()
    seen_hashes: set[str] = set()
    rows: list[PlanRow] = []

    for line, record in records:
        if len(record) != len(PLAN_COLUMNS):
            add(line, NO_COLUMN, "malformed_row")
            continue
        cells = dict(zip(PLAN_COLUMNS, record, strict=True))
        row_problems = _row_problems(cells, registry)
        for column, code in row_problems:
            add(line, column, code)

        file_code, path = _file_problem(cells["file"], inbox_real)
        digest = None
        if file_code is None and cells["file"] in seen_files:
            file_code = "duplicate_file"
        if cells["file"]:
            seen_files.add(cells["file"])
        if file_code is None and path is not None:
            try:
                digest = hashlib.sha256(_read_input(path)).hexdigest()
            except OSError:
                file_code = "invalid_file"
        if file_code is None and digest is not None:
            if digest in seen_hashes:
                file_code = "duplicate_input"
            seen_hashes.add(digest)
        if file_code is not None:
            add(line, "file", file_code)

        item_id, object_type = cells["item_id"], cells["object_type"]
        own, external = _item_formats(item_id)
        if (own or external) and object_type in _OBJECT_TYPE_VALUES:
            conflict = bool(manifest_types.get(item_id, set()) - {object_type})
            previous = plan_types.setdefault(item_id, object_type)
            if conflict or previous != object_type:
                add(line, "item_id", "item_type_conflict")

        if row_problems or file_code is not None or path is None or digest is None:
            continue
        rows.append(
            PlanRow(
                line=line,
                file=cells["file"],
                path=path,
                item_id=item_id,
                object_type=object_type,
                grade=cells["grade"],
                labeler=cells["labeler"],
                angle=int(cells["angle"]),
                origin=cells["origin"],
                contributor=cells["contributor"],
                source_id=cells["source_id"],
                source_ref=cells["source_ref"],
                notes=cells["notes"],
                input_sha256=digest,
                skip=digest in state.imported_hashes,
            )
        )
    if found:
        raise PlanError([problem for _, _, problem in sorted(found, key=lambda f: f[:2])])
    return rows


# ------------------------------------------------------------------------------------ phase 2


class _Importer:
    """Stores the normalised images of phase 2 under ``dataset_dir`` (section 4.4)."""

    def __init__(
        self,
        dataset_dir: Path,
        *,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
    ) -> None:
        self._root = dataset_dir
        self._clock = clock
        self._sleep = sleep

    @property
    def manifest_path(self) -> Path:
        return self._root / MANIFEST_NAME

    @property
    def sources_path(self) -> Path:
        return self._root / SOURCES_NAME

    def store(self, row: PlanRow, data: bytes) -> str:
        """Write the image and its two rows; returns the ``image_path``.

        Raises:
            _RowFailed: ``capture already exists`` or an ``item_id`` registered meanwhile with
                another ``object_type``.
            _ImportStopped: an I/O failure (everything of this row undone) or a header changed
                meanwhile.
        """
        try:
            make_private_dirs(self._root, sync=True, relative_to=self._root)
        except OSError as exc:
            raise self._stopped(exc) from None
        for attempt in range(1, NAME_ATTEMPTS + 1):
            try:
                with manifest_file_lock(self._root):
                    image_path = self._store_locked(row, data)
            except OSError as exc:
                raise self._stopped(exc) from None
            if image_path is not None:
                return image_path
            if attempt < NAME_ATTEMPTS:
                self._sleep(RETRY_DELAY_S)  # the lock is released while waiting
        raise _RowFailed(REASON_CAPTURE_EXISTS)

    @staticmethod
    def _stopped(exc: OSError) -> _ImportStopped:
        logger.error("dataset write failed: %s", exc.strerror or type(exc).__name__)
        return _ImportStopped(REASON_WRITE_FAILED)

    @property
    def exclusions_path(self) -> Path:
        return self._root / EXCLUSIONS_NAME

    def _check_headers(self) -> tuple[list[ManifestEntry], frozenset[str]]:
        """Step 2: the manifest entries and the input hashes already imported.

        A hash counts as imported when its ``sources.csv`` row is not of an image of
        ``exclusions.csv`` (the rule of phase 1, SPEC-038 section 4.6).
        """
        try:
            entries = read_manifest_entries(self.manifest_path)
            sources = read_csv_rows(self.sources_path, SOURCES_COLUMNS) or []
        except ManifestHeaderMismatchError:
            raise _ImportStopped(MANIFEST_MISMATCH_MESSAGE) from None
        except ManifestUnreadableError:
            raise _ImportStopped(MANIFEST_UNREADABLE_MESSAGE) from None
        except CsvHeaderMismatchError:
            raise _ImportStopped(SOURCES_MISMATCH_MESSAGE) from None
        except CsvUnreadableError:
            raise _ImportStopped(SOURCES_UNREADABLE_MESSAGE) from None
        try:
            exclusions = read_csv_rows(self.exclusions_path, EXCLUSIONS_COLUMNS) or []
        except CsvHeaderMismatchError:
            raise _ImportStopped(EXCLUSIONS_MISMATCH_MESSAGE) from None
        except CsvUnreadableError:
            raise _ImportStopped(EXCLUSIONS_UNREADABLE_MESSAGE) from None
        excluded = {line[0] for line in exclusions if line}
        imported = frozenset(
            line[5]
            for line in sources
            if len(line) == len(SOURCES_COLUMNS) and line[0] not in excluded
        )
        return entries, imported

    def _store_locked(self, row: PlanRow, data: bytes) -> str | None:
        """Steps 2 to 6 under the lock; ``None`` when the name is already taken (step 3).

        Raises:
            _AlreadyImported: the input hash entered ``sources.csv`` after phase 1.
        """
        entries, imported = self._check_headers()  # step 2
        if any(e.item_id == row.item_id and e.object_type != row.object_type for e in entries):
            raise _RowFailed(REASON_ITEM_CONFLICT)
        if row.input_sha256 in imported:  # another run imported it (SPEC-038 section 4.6)
            raise _AlreadyImported()

        ts = self._clock().astimezone(UTC)  # step 3
        grade_dir = row.grade or NO_GRADE_DIR
        file_name = f"{row.item_id}__{row.angle}__{ts.strftime(FILE_TIMESTAMP_FORMAT)}.jpg"
        image_path = f"{RAW_SUBDIR}/{row.object_type}/{grade_dir}/{file_name}"
        target = self._root / RAW_SUBDIR / row.object_type / grade_dir / file_name
        if os.path.lexists(target) or any(e.image_path == image_path for e in entries):
            return None

        created = make_private_dirs(target.parent, sync=True, relative_to=self._root)  # step 4
        try:
            self._write_row(row, data, target, image_path, ts)
        except BaseException:
            self._remove_dirs(created)  # SPEC-038 section 4.5
            raise
        return image_path

    def _write_row(
        self, row: PlanRow, data: bytes, target: Path, image_path: str, ts: datetime
    ) -> None:
        """Steps 4 (the image) to 6; on failure the image and the manifest row are undone."""
        write_private_file_atomically(target, lambda handle: handle.write(data), root=self._root)
        manifest_row = (
            image_path,
            row.item_id,
            row.object_type,
            row.grade,
            row.labeler,
            str(row.angle),
            ts.strftime(CAPTURED_AT_FORMAT),
            CAPTURE_DEVICE,
            row.notes,
        )
        try:  # step 5
            appended = append_csv_row(
                self.manifest_path, MANIFEST_COLUMNS, manifest_row, root=self._root
            )
        except BaseException:
            self._remove_image(target)
            raise
        source_row = (
            image_path,
            row.origin,
            row.contributor,
            row.source_id,
            row.source_ref,
            row.input_sha256,
        )
        try:  # step 6
            append_csv_row(self.sources_path, SOURCES_COLUMNS, source_row, root=self._root)
        except BaseException:
            try:
                rollback_append(appended, root=self._root)
            except OSError as exc:
                logger.error(
                    "cannot roll back the manifest: %s", exc.strerror or type(exc).__name__
                )
            self._remove_image(target)
            raise

    def _remove_image(self, target: Path) -> None:
        with contextlib.suppress(OSError):
            target.unlink(missing_ok=True)
        fsync_dir(target.parent, relative_to=self._root)

    def _remove_dirs(self, created: Sequence[Path]) -> None:
        """Remove the directories created for this row, innermost first (SPEC-038 section 4.5).

        ``created`` is the list of ``make_private_dirs`` (outermost first), so a directory that
        existed before the row is never touched. One that is not empty stays (``OSError``).
        """
        for directory in reversed(created):
            try:
                os.rmdir(directory)
            except OSError:
                continue
            fsync_dir(directory.parent, relative_to=self._root)


def _phase2_input(row: PlanRow) -> bytes:
    """The input bytes again, checked against the hash of phase 1."""
    try:
        data = _read_input(row.path)
    except OSError:
        raise ImageRejectedError(REASON_INPUT_CHANGED) from None
    if hashlib.sha256(data).hexdigest() != row.input_sha256:
        raise ImageRejectedError(REASON_INPUT_CHANGED)
    return data


def run_import(
    rows: Sequence[PlanRow],
    *,
    dataset_dir: Path,
    dry_run: bool,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None],
    out: TextIO,
) -> int:
    """Phase 2 (sections 4.3, 4.4 and 4.6); returns the exit code (0 or 1)."""
    importer = _Importer(dataset_dir, clock=clock, sleep=sleep)
    done = skipped = failed = 0
    for row in rows:
        shown = printable_path(row.file)
        if row.skip:
            out.write(f"skipped {shown}: already imported\n")
            skipped += 1
            continue
        try:
            normalized, _, _ = normalize_imported_image(_phase2_input(row))  # step 1
        except ImageRejectedError as exc:
            logger.warning("plan line %d not imported: %s", row.line, exc.reason)
            out.write(f"failed {shown}: {exc.reason}\n")
            failed += 1
            continue
        if dry_run:
            out.write(f"would import {shown}\n")
            done += 1
            continue
        try:
            image_path = importer.store(row, normalized)
        except _AlreadyImported:
            out.write(f"skipped {shown}: already imported\n")
            skipped += 1
            continue
        except _RowFailed as exc:
            logger.warning("plan line %d not imported: %s", row.line, exc.reason)
            out.write(f"failed {shown}: {exc.reason}\n")
            failed += 1
            continue
        except _ImportStopped as exc:
            logger.error("import stopped at plan line %d: %s", row.line, exc.reason)
            out.write(f"failed {shown}: {exc.reason}\n")
            failed += 1
            break
        out.write(f"imported {shown} -> {printable_path(image_path)}\n")
        done += 1
    verb = "would import" if dry_run else "imported"
    out.write(f"{verb} {done}, skipped {skipped}, failed {failed}\n")
    return EXIT_FAILED if failed else EXIT_OK


# ---------------------------------------------------------------------------------------- CLI


def _parser() -> QuietArgumentParser:
    parser = QuietArgumentParser(
        prog="python -m qc_edge.importer",
        description="Import photos that did not come from the /capture page (SPEC-036).",
        allow_abbrev=False,
    )
    parser.add_argument("--dataset-dir", required=True, type=Path, help="DATASET_DIR")
    parser.add_argument("--inbox", required=True, type=Path, help="folder with the received files")
    parser.add_argument("--plan", required=True, type=Path, help="import plan (CSV)")
    parser.add_argument(
        "--privacy-checked",
        action="store_true",
        help="every photo was checked by eye (docs/dataset-protocol.md section 10.5)",
    )
    parser.add_argument(
        "--external-sources",
        type=Path,
        default=None,
        help="registry of external sources (default: ml/external_sources.csv)",
    )
    parser.add_argument("--dry-run", action="store_true", help="validate and normalise only")
    return parser


def _configure_logging() -> None:
    if not logging.getLogger().handlers and not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], datetime] = _utc_now,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Entry point; returns the exit code (0, 1 or 2, section 4.6)."""
    _configure_logging()
    limit_pil_logging()
    arguments = resolve_argv(argv)
    try:
        args, unknown = _parser().parse_known_args(arguments)
    except ArgumentsError:
        logger.error("invalid command-line argument(s): %s", describe_arguments(arguments))
        return EXIT_USAGE_ERROR
    if unknown:
        logger.error("unknown command-line argument(s): %s", describe_arguments(unknown))
        return EXIT_USAGE_ERROR
    if not args.privacy_checked:
        sys.stderr.write(MISSING_PRIVACY_MESSAGE + "\n")
        return EXIT_USAGE_ERROR
    external_sources = (
        DEFAULT_EXTERNAL_SOURCES if args.external_sources is None else args.external_sources
    )
    try:
        rows = load_plan(
            dataset_dir=args.dataset_dir,
            inbox=args.inbox,
            plan=args.plan,
            external_sources=external_sources,
        )
    except UsageError as exc:
        sys.stderr.write(exc.message + "\n")
        return EXIT_USAGE_ERROR
    except PlanError as exc:
        for problem in exc.problems:
            sys.stderr.write(f"{problem}\n")
        logger.error("plan refused: %d problem(s), nothing written", len(exc.problems))
        return EXIT_USAGE_ERROR
    return run_import(
        rows,
        dataset_dir=args.dataset_dir,
        dry_run=args.dry_run,
        clock=clock,
        sleep=sleep,
        out=sys.stdout,
    )


if __name__ == "__main__":
    sys.exit(main())
