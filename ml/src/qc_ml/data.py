"""Manifest loading, label overrides, exclusions and the data report (SPEC-011 sections 4.1-4.2).

This is a module, not a package: the ``.gitignore`` ignores every ``data/`` directory.

The CSV files are read only with the ``csv`` module over text opened with ``newline=""``, never
by splitting lines (SEC-10-03): rows written before SPEC-025 may contain U+2028, U+2029 or U+0085
in ``notes`` or ``capture_device``, which ``str.splitlines()`` would count as line breaks. The
pipeline does not take the edge's ``manifest.csv.lock`` (SEC-10-06): it reads the manifest once.

Origin of the images (SPEC-035, ADR-020): ``DATASET_DIR/sources.csv`` says which images were
imported (``contributor`` or ``external``) and the registry ``ml/external_sources.csv`` lists the
external sources with their licence. Whether an image is external is decided **only** by its
``item_id`` (``X<type>-NNNN``, ``is_external_item``), never by ``sources.csv``.

No torch here (SPEC-011 section 4.5).

CLI::

    python -m qc_ml.data validate --dataset-dir ml/data [--external-sources <file>]
    python -m qc_ml.data report --dataset-dir ml/data --split ml/splits/split_v1.csv \
        --out ml/reports/data_report.json [--external-sources <file>]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

import qc_ml
from qc_contracts import GRADE_ORDER
from qc_ml.errors import ManifestError, ManifestProblem, SplitError
from qc_preprocess import InvalidImageError, load_image

logger = logging.getLogger(__name__)

MANIFEST_FILE = "manifest.csv"
OVERRIDES_FILE = "labels_overrides.csv"
EXCLUSIONS_FILE = "exclusions.csv"
SOURCES_FILE = "sources.csv"
EXTERNAL_SOURCES_FILE = "external_sources.csv"
RAW_DIR = "raw"

# SPEC-035 section 4.2: the registry of the repository (also in Colab, which clones it).
DEFAULT_EXTERNAL_SOURCES = Path(qc_ml.__file__).resolve().parents[2] / EXTERNAL_SOURCES_FILE

# docs/dataset-protocol.md section 5 (same order as the edge writer, SPEC-010).
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
OVERRIDE_COLUMNS: tuple[str, ...] = ("image_path", "grade", "labeler", "reason")
EXCLUSION_COLUMNS: tuple[str, ...] = ("image_path", "reason")
EXCLUSION_REASONS: tuple[str, ...] = ("person", "other")
SOURCE_COLUMNS: tuple[str, ...] = (
    "image_path",
    "origin",
    "contributor",
    "source_id",
    "source_ref",
    "input_sha256",
)
EXTERNAL_SOURCE_COLUMNS: tuple[str, ...] = (
    "source_id",
    "title",
    "url",
    "license",
    "license_url",
    "attribution",
    "retrieved_at",
)
RESULT_COLUMNS: tuple[str, ...] = (
    *MANIFEST_COLUMNS,
    "grade_original",
    "overridden",
    "origin",
    "contributor",
    "source_id",
)

# Origins of an image (SPEC-035, ADR-020); ``capture`` = no line in sources.csv.
ORIGINS: tuple[str, ...] = ("capture", "contributor", "external")
IMPORTED_ORIGINS: tuple[str, ...] = ("contributor", "external")
# ADR-020, decision 3 (closed list; no NonCommercial, ShareAlike or NoDerivatives licence).
ALLOWED_LICENSES: tuple[str, ...] = (
    "CC0-1.0",
    "PDDL-1.0",
    "CC-BY-4.0",
    "MIT",
    "Apache-2.0",
    "BSD-3-Clause",
)
CONTRIBUTOR_PATTERN = re.compile(r"c[0-9]{2}")
SOURCE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,39}")
INPUT_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
URL_PREFIX = "https://"
URL_LENGTH: tuple[int, int] = (9, 300)
SOURCE_REF_MAX = 200
TITLE_MAX = 200
ATTRIBUTION_MAX = 500
# Unicode categories refused in the free texts (control, surrogate, format, line/paragraph sep.).
FORBIDDEN_CATEGORIES: frozenset[str] = frozenset({"Cc", "Cs", "Cf", "Zl", "Zp"})

KNOWN_OBJECT_TYPES: tuple[str, ...] = ("screw", "nut", "other")
GRADED_OBJECT_TYPES: tuple[str, ...] = ("screw", "nut")
GRADES: tuple[str, ...] = tuple(g.value for g in GRADE_ORDER)
NO_GRADE = "none"
SPLIT_NAMES: tuple[str, ...] = ("train", "val", "test")

# docs/architecture.md section 3.2; always used with ``fullmatch``. The single item_id regex of
# qc_ml (SPEC-031 section 4.6): own items ``S-012`` and external images ``XS-0001`` (SPEC-035).
ITEM_ID_PATTERN = re.compile(r"[SNOT]-[0-9]{3}|X[SNOT]-[0-9]{4}")
ANGLE_PATTERN = re.compile(r"[0-4]")
ITEM_PREFIX_TYPES: dict[str, str] = {"S": "screw", "N": "nut", "O": "other"}
EXTERNAL_PREFIX = "X"

# SPEC-024 section 4.1 guarantees this text in the message of the scan-limit error.
JPEG_SCANS_TEXT = "JPEG scans"
MOTION_PHOTO_HINT = "motion photo? see docs/dataset-protocol.md section 3"

# docs/dataset-protocol.md section 4.
TARGET_IMAGES_PER_GRADE = 120
TARGET_ITEMS_PER_GRADE = 12
MINIMUM_ITEMS_PER_GRADE = 8

EXIT_OK = 0
EXIT_ERROR = 2


def item_type_letter(item_id: str) -> str:
    """The type letter of an ``item_id``: ``item_id[1]`` after an ``X``, else ``item_id[0]``."""
    return item_id[1] if item_id.startswith(EXTERNAL_PREFIX) else item_id[0]


def is_external_item(item_id: str) -> bool:
    """``True`` if, and only if, ``item_id`` matches ``ITEM_ID_PATTERN`` and starts with ``X``.

    This alone decides that an image is external and stays in train (SPEC-035 section 4.1).
    """
    return (
        isinstance(item_id, str)
        and item_id.startswith(EXTERNAL_PREFIX)
        and ITEM_ID_PATTERN.fullmatch(item_id) is not None
    )


@dataclass(frozen=True)
class ModelLabels:
    """Class order of the model heads (``labels.json``, docs/architecture.md section 7)."""

    object_types: tuple[str, ...] = KNOWN_OBJECT_TYPES
    grades: tuple[str, ...] = GRADES


DEFAULT_LABELS = ModelLabels()


# ---------------------------------------------------------------------------------------------
# CSV reading
# ---------------------------------------------------------------------------------------------


@dataclass
class CsvTable:
    """A CSV file read with the ``csv`` module; ``rows`` are ``(record number, values)``."""

    header: list[str] = field(default_factory=list)
    rows: list[tuple[int, dict[str, str]]] = field(default_factory=list)
    problems: list[ManifestProblem] = field(default_factory=list)
    # Key column value (e.g. image_path) of the rows with a wrong number of fields.
    malformed_paths: list[str] = field(default_factory=list)


# Problems after which ``parse_csv`` reads no row (the file is not usable at all).
HEADER_PROBLEMS: frozenset[str] = frozenset(
    {"missing_column", "unexpected_header", "unreadable_csv"}
)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_csv(
    data: bytes, file_name: str, required: Sequence[str], *, exact_header: bool = False
) -> CsvTable:
    """Parse CSV bytes with ``csv.reader``; record numbers count the header as 1.

    Blank records are skipped (as ``csv.DictReader`` does) and do not get a number.

    A missing required column gives one ``missing_column`` per column. With ``exact_header``
    (only ``sources.csv`` and the registry, SPEC-037 section 4.4), a header with every required
    column that is not exactly ``required`` (extra, repeated or empty column, other order) gives
    one ``unexpected_header``. Either way no row is read.
    """
    table = CsvTable()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        table.problems.append(
            ManifestProblem("unreadable_csv", file_name, None, None, f"not valid UTF-8: {exc}")
        )
        return table
    try:
        records = [row for row in csv.reader(io.StringIO(text, newline="")) if row]
    except csv.Error as exc:
        table.problems.append(
            ManifestProblem("unreadable_csv", file_name, None, None, f"not valid CSV: {exc}")
        )
        return table

    table.header = records[0] if records else []
    missing = [c for c in required if c not in table.header]
    if missing:
        hint = " (the file starts with a BOM)" if text.startswith("\ufeff") else ""
        for column in missing:
            table.problems.append(
                ManifestProblem(
                    "missing_column", file_name, 1, None, f"missing column {column!r}{hint}"
                )
            )
        return table
    if exact_header and tuple(table.header) != tuple(required):
        # The header read is not echoed: it may carry anything (control characters included).
        table.problems.append(
            ManifestProblem(
                "unexpected_header",
                file_name,
                1,
                None,
                f"the header must be exactly {','.join(required)} (in this order, no other column)",
            )
        )
        return table

    for number, record in enumerate(records[1:], start=2):
        if len(record) != len(table.header):
            key_index = table.header.index(required[0])
            if len(record) > key_index:
                table.malformed_paths.append(record[key_index])
            table.problems.append(
                ManifestProblem(
                    "malformed_row",
                    file_name,
                    number,
                    None,
                    f"expected {len(table.header)} fields, got {len(record)}",
                )
            )
            continue
        values = dict(zip(table.header, record, strict=True))
        table.rows.append((number, {c: values[c] for c in required}))
    return table


def _valid_image_path(path: str) -> bool:
    """Relative POSIX path, without ``..``, ``.``, empty components, backslash or NUL."""
    if not path or "\\" in path or "\x00" in path or path.startswith("/"):
        return False
    parts = path.split("/")
    return all(part not in ("", ".", "..") for part in parts)


# ---------------------------------------------------------------------------------------------
# Exclusions (SEC-10-08, R-14)
# ---------------------------------------------------------------------------------------------


@dataclass
class _Exclusions:
    paths: dict[str, int] = field(default_factory=dict)  # image_path -> first record number
    problems: list[ManifestProblem] = field(default_factory=list)


def _read_exclusions(dataset_dir: Path) -> _Exclusions:
    """Read ``exclusions.csv`` (absent -> no exclusion) with the checks that need no manifest."""
    result = _Exclusions()
    path = dataset_dir / EXCLUSIONS_FILE
    if not path.is_file():
        return result
    table = parse_csv(path.read_bytes(), EXCLUSIONS_FILE, EXCLUSION_COLUMNS)
    result.problems.extend(table.problems)
    for line, row in table.rows:
        image_path, reason = row["image_path"], row["reason"]
        if not _valid_image_path(image_path):
            result.problems.append(
                ManifestProblem(
                    "invalid_image_path",
                    EXCLUSIONS_FILE,
                    line,
                    image_path or None,
                    "image_path must be a relative path inside the dataset directory",
                )
            )
            continue
        result.paths.setdefault(image_path, line)
        if reason not in EXCLUSION_REASONS:
            result.problems.append(
                ManifestProblem(
                    "exclusion_invalid_reason",
                    EXCLUSIONS_FILE,
                    line,
                    image_path,
                    f"reason must be one of {', '.join(EXCLUSION_REASONS)}, got {reason!r}",
                )
            )
        if os.path.lexists(dataset_dir / image_path):
            result.problems.append(
                ManifestProblem(
                    "excluded_file_present",
                    EXCLUSIONS_FILE,
                    line,
                    image_path,
                    "excluded image still on disk: delete it "
                    "(docs/dataset-protocol.md section 8.1)",
                )
            )
    return result


def load_exclusions(dataset_dir: Path | str) -> frozenset[str]:
    """Return the ``image_path`` values of ``dataset_dir/exclusions.csv`` (empty if absent).

    Raises:
        ManifestError: missing column, invalid ``reason``, invalid path or an excluded file that
            is still on disk. ``exclusion_unknown_image`` needs the manifest and is checked only by
            ``load_manifest``.
    """
    exclusions = _read_exclusions(Path(dataset_dir))
    if exclusions.problems:
        raise ManifestError(exclusions.problems)
    return frozenset(exclusions.paths)


# ---------------------------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------------------------


def _read_overrides(
    dataset_dir: Path, manifest_paths: set[str], excluded: Iterable[str]
) -> tuple[dict[str, str | None], list[ManifestProblem]]:
    """Return ``image_path -> grade`` (last valid line wins) and the problems found."""
    path = dataset_dir / OVERRIDES_FILE
    if not path.is_file():
        return {}, []
    excluded_set = set(excluded)
    table = parse_csv(path.read_bytes(), OVERRIDES_FILE, OVERRIDE_COLUMNS)
    problems = list(table.problems)
    overrides: dict[str, str | None] = {}
    for line, row in table.rows:
        image_path, grade = row["image_path"], row["grade"]
        if image_path in excluded_set:
            continue  # the image left the dataset; its correction no longer matters
        if image_path not in manifest_paths:
            problems.append(
                ManifestProblem(
                    "override_unknown_image",
                    OVERRIDES_FILE,
                    line,
                    image_path or None,
                    "override for an image_path that is not in the manifest",
                )
            )
            continue
        if not row["reason"].strip():
            problems.append(
                ManifestProblem(
                    "override_missing_reason",
                    OVERRIDES_FILE,
                    line,
                    image_path,
                    "override without a reason",
                )
            )
        if grade and grade not in GRADES:
            problems.append(
                ManifestProblem(
                    "invalid_grade",
                    OVERRIDES_FILE,
                    line,
                    image_path,
                    f"grade must be one of {', '.join(GRADES)}, got {grade!r}",
                )
            )
            continue
        overrides[image_path] = grade or None
    return overrides, problems


# ---------------------------------------------------------------------------------------------
# Registry of the external sources (SPEC-035 section 4.3)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExternalSource:
    """One line of ``ml/external_sources.csv``: a dataset or web page with an accepted licence."""

    source_id: str
    title: str
    url: str
    license: str
    license_url: str
    attribution: str
    retrieved_at: date


def _clean_text(value: str, max_length: int) -> bool:
    """1 to ``max_length`` characters, none in the forbidden Unicode categories."""
    return 1 <= len(value) <= max_length and not any(
        unicodedata.category(ch) in FORBIDDEN_CATEGORIES for ch in value
    )


def _valid_url(value: str) -> bool:
    """``https://``, 9 to 300 characters, visible ASCII only (``0x21``-``0x7E``)."""
    low, high = URL_LENGTH
    return (
        value.startswith(URL_PREFIX)
        and low <= len(value) <= high
        and all(0x21 <= ord(ch) <= 0x7E for ch in value)
    )


def _parse_date(value: str) -> date | None:
    if not DATE_PATTERN.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class _Registry:
    sources: dict[str, ExternalSource] = field(default_factory=dict)
    # source_id of every line with a well-formed id (valid or not otherwise): an image that uses
    # one of them is not reported again as unknown_source_id.
    known_ids: set[str] = field(default_factory=set)
    problems: list[ManifestProblem] = field(default_factory=list)
    sha256: str | None = None


def _registry_row_problems(line: int, row: dict[str, str]) -> list[ManifestProblem]:
    """Checks of one registry line, except the uniqueness of ``source_id``."""
    problems: list[ManifestProblem] = []

    def add(code: str, message: str) -> None:
        problems.append(ManifestProblem(code, EXTERNAL_SOURCES_FILE, line, None, message))

    if not SOURCE_ID_PATTERN.fullmatch(row["source_id"]):
        add("invalid_source_id", "source_id must match ^[a-z0-9][a-z0-9-]{2,39}$")
    if not _clean_text(row["title"], TITLE_MAX):
        add("invalid_text", f"title must have 1 to {TITLE_MAX} characters, no control ones")
    if not _valid_url(row["url"]):
        add("invalid_url", "url must be https://, 9 to 300 visible ASCII characters")
    if row["license"] not in ALLOWED_LICENSES:
        add(
            "invalid_license",
            f"license must be one of {', '.join(ALLOWED_LICENSES)} (ADR-020), "
            f"got {row['license']!r}",
        )
    if not _valid_url(row["license_url"]):
        add("invalid_url", "license_url must be https://, 9 to 300 visible ASCII characters")
    if not _clean_text(row["attribution"], ATTRIBUTION_MAX):
        add(
            "invalid_text",
            f"attribution must have 1 to {ATTRIBUTION_MAX} characters, no control ones",
        )
    if _parse_date(row["retrieved_at"]) is None:
        add("invalid_date", "retrieved_at must be a valid date YYYY-MM-DD")
    return problems


def _read_registry(path: Path | str) -> _Registry:
    """Read and validate the whole registry; an absent file is an empty registry."""
    result = _Registry()
    path = Path(path)
    if not path.is_file():
        return result
    data = path.read_bytes()
    result.sha256 = _sha256_hex(data)
    table = parse_csv(data, EXTERNAL_SOURCES_FILE, EXTERNAL_SOURCE_COLUMNS, exact_header=True)
    result.problems.extend(table.problems)
    for line, row in table.rows:
        line_problems = _registry_row_problems(line, row)
        source_id = row["source_id"]
        if SOURCE_ID_PATTERN.fullmatch(source_id):
            if source_id in result.known_ids:
                line_problems.append(
                    ManifestProblem(
                        "duplicate_source_id",
                        EXTERNAL_SOURCES_FILE,
                        line,
                        None,
                        f"source_id {source_id} repeated in the registry",
                    )
                )
            result.known_ids.add(source_id)
        result.problems.extend(line_problems)
        retrieved_at = _parse_date(row["retrieved_at"])
        if not line_problems and retrieved_at is not None:
            result.sources[source_id] = ExternalSource(
                source_id=source_id,
                title=row["title"],
                url=row["url"],
                license=row["license"],
                license_url=row["license_url"],
                attribution=row["attribution"],
                retrieved_at=retrieved_at,
            )
    return result


def load_external_sources(path: Path | str) -> dict[str, ExternalSource]:
    """Read ``ml/external_sources.csv`` (SPEC-035 section 4.3): ``source_id -> ExternalSource``.

    An absent file is an empty registry (``{}``), as in ``load_manifest``.

    Raises:
        ManifestError: any problem of the registry (``file="external_sources.csv"``).
    """
    registry = _read_registry(path)
    if registry.problems:
        raise ManifestError(registry.problems)
    return dict(registry.sources)


# ---------------------------------------------------------------------------------------------
# sources.csv (SPEC-035 section 4.2)
# ---------------------------------------------------------------------------------------------


@dataclass
class _Sources:
    present: bool = False  # the file exists
    readable: bool = True  # header and CSV are usable (no problem in HEADER_PROBLEMS)
    sha256: str | None = None
    # image_path -> row of the valid, non-excluded lines (first line of a repeated path).
    rows: dict[str, dict[str, str]] = field(default_factory=dict)
    # Every image_path with a line in the file (malformed lines and excluded lines included).
    listed: set[str] = field(default_factory=set)
    lines: dict[str, int] = field(default_factory=dict)  # image_path -> first record number
    problems: list[ManifestProblem] = field(default_factory=list)


def _source_row_problems(
    line: int, row: dict[str, str], known_ids: set[str]
) -> list[ManifestProblem]:
    """Checks of one line of ``sources.csv`` that need neither the manifest nor other lines."""
    problems: list[ManifestProblem] = []
    image_path = row["image_path"]

    def add(code: str, message: str) -> None:
        problems.append(ManifestProblem(code, SOURCES_FILE, line, image_path, message))

    origin, contributor = row["origin"], row["contributor"]
    source_id, source_ref = row["source_id"], row["source_ref"]
    if origin not in IMPORTED_ORIGINS:
        add("invalid_origin", f"origin must be one of {', '.join(IMPORTED_ORIGINS)}")
    elif origin == "contributor":
        if not CONTRIBUTOR_PATTERN.fullmatch(contributor):
            add("invalid_contributor", "contributor must be a code like c01 for origin=contributor")
        if source_id or source_ref:
            add("source_fields_mismatch", "source_id and source_ref must be empty for contributor")
    else:
        if contributor:
            add("invalid_contributor", "contributor must be empty for origin=external")
        if not source_id or source_id not in known_ids:
            add("unknown_source_id", "source_id of an external image must be in the registry")
        if not _clean_text(source_ref, SOURCE_REF_MAX):
            add(
                "invalid_source_ref",
                f"source_ref must have 1 to {SOURCE_REF_MAX} characters, no control ones",
            )
    if not INPUT_SHA256_PATTERN.fullmatch(row["input_sha256"]):
        add("invalid_input_sha256", "input_sha256 must be 64 lowercase hexadecimal digits")
    return problems


def _read_sources(dataset_dir: Path, known_ids: set[str], excluded: Iterable[str]) -> _Sources:
    """Read ``sources.csv`` with the checks that need no manifest.

    The lines of excluded images are skipped (no line problem, no ``duplicate_input``);
    ``duplicate_source_row`` is checked over the whole file.
    """
    result = _Sources()
    path = dataset_dir / SOURCES_FILE
    if not path.is_file():
        return result
    result.present = True
    data = path.read_bytes()
    result.sha256 = _sha256_hex(data)
    table = parse_csv(data, SOURCES_FILE, SOURCE_COLUMNS, exact_header=True)
    result.problems.extend(table.problems)
    if any(p.code in HEADER_PROBLEMS for p in table.problems):
        result.readable = False
        return result
    result.listed.update(table.malformed_paths)
    excluded_set = set(excluded)
    seen_inputs: set[str] = set()
    for line, row in table.rows:
        image_path = row["image_path"]
        if not _valid_image_path(image_path):
            result.problems.append(
                ManifestProblem(
                    "invalid_image_path",
                    SOURCES_FILE,
                    line,
                    image_path or None,
                    "image_path must be a relative path inside the dataset directory",
                )
            )
            continue
        if image_path in result.listed:
            result.problems.append(
                ManifestProblem(
                    "duplicate_source_row",
                    SOURCES_FILE,
                    line,
                    image_path,
                    "image_path repeated in sources.csv",
                )
            )
            continue
        result.listed.add(image_path)
        result.lines[image_path] = line
        if image_path in excluded_set:
            continue  # the image left the dataset; its origin no longer matters
        row_problems = _source_row_problems(line, row, known_ids)
        result.problems.extend(row_problems)
        input_sha256 = row["input_sha256"]
        if INPUT_SHA256_PATTERN.fullmatch(input_sha256):
            if input_sha256 in seen_inputs:
                result.problems.append(
                    ManifestProblem(
                        "duplicate_input",
                        SOURCES_FILE,
                        line,
                        image_path,
                        "the same received file (input_sha256) was imported twice",
                    )
                )
            seen_inputs.add(input_sha256)
        if not row_problems:
            result.rows[image_path] = row
    return result


def _sources_manifest_problems(
    sources: _Sources,
    manifest_paths: set[str],
    kept: list[tuple[int, dict[str, str]]],
) -> list[ManifestProblem]:
    """``source_unknown_image``, ``external_item_mismatch`` and ``missing_source``."""
    problems: list[ManifestProblem] = []
    if not sources.readable:
        return problems
    item_of = {row["image_path"]: row["item_id"] for _, row in kept}
    line_of = sources.lines
    for image_path, line in sorted(line_of.items(), key=lambda entry: entry[1]):
        if image_path in manifest_paths:
            continue
        problems.append(
            ManifestProblem(
                "source_unknown_image",
                SOURCES_FILE,
                line,
                image_path,
                "line for an image_path that is not in the manifest",
            )
        )
    for image_path, row in sources.rows.items():
        item_id = item_of.get(image_path)
        if item_id is None:
            continue
        external = is_external_item(item_id)
        if (row["origin"] == "external") != external:
            problems.append(
                ManifestProblem(
                    "external_item_mismatch",
                    SOURCES_FILE,
                    line_of.get(image_path),
                    image_path,
                    f"origin {row['origin']} does not match item_id {item_id} (external images "
                    "use X<type>-NNNN, every other image does not)",
                )
            )
    for line, row in kept:
        if is_external_item(row["item_id"]) and row["image_path"] not in sources.listed:
            problems.append(
                ManifestProblem(
                    "missing_source",
                    MANIFEST_FILE,
                    line,
                    row["image_path"],
                    f"external item {row['item_id']} without a line in sources.csv "
                    "(docs/dataset-protocol.md section 10.7)",
                )
            )
    return problems


def load_sources(dataset_dir: Path | str, registry: Mapping[str, ExternalSource]) -> pd.DataFrame:
    """Read ``dataset_dir/sources.csv`` (SPEC-035 section 4.2), one row per kept line.

    The columns are ``SOURCE_COLUMNS`` (``str``); the lines of the images in ``exclusions.csv``
    are left out. An absent file gives an empty frame. ``df.attrs["sources_sha256"]`` is the hash
    of the file read (``None`` without it). The checks that need the manifest
    (``source_unknown_image``, ``external_item_mismatch``, ``missing_source``) are made only by
    ``load_manifest``.

    Raises:
        ManifestError: a problem of ``sources.csv`` or of ``exclusions.csv``.
    """
    root = Path(dataset_dir)
    exclusions = _read_exclusions(root)
    sources = _read_sources(root, set(registry), exclusions.paths)
    problems = exclusions.problems + sources.problems
    if problems:
        raise ManifestError(problems)
    frame = pd.DataFrame(
        {
            column: pd.Series([row[column] for row in sources.rows.values()], dtype=object)
            for column in SOURCE_COLUMNS
        },
        columns=list(SOURCE_COLUMNS),
    )
    frame.attrs["sources_sha256"] = sources.sha256
    return frame


# ---------------------------------------------------------------------------------------------
# Orphan images (SEC-10-02)
# ---------------------------------------------------------------------------------------------


def find_raw_images(dataset_dir: Path | str) -> list[str]:
    """Relative paths of the regular ``*.jpg`` files under ``dataset_dir/raw/``, sorted.

    The walk is recursive and does not follow symbolic links below ``raw/``. The extension check
    is case-insensitive, so ``.JPG`` copies are also found.
    """
    root = Path(dataset_dir)
    raw_dir = root / RAW_DIR
    if not raw_dir.is_dir():
        return []
    found: list[str] = []
    stack = [raw_dir]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".jpg"):
                    found.append(Path(entry.path).relative_to(root).as_posix())
    return sorted(found)


# ---------------------------------------------------------------------------------------------
# load_manifest
# ---------------------------------------------------------------------------------------------


def _image_problem(dataset_dir: Path, line: int, image_path: str) -> ManifestProblem | None:
    """Decode the image with ``qc_preprocess.load_image``; ``None`` when it is readable."""
    try:
        load_image(dataset_dir / image_path)
    except InvalidImageError as exc:
        if JPEG_SCANS_TEXT in str(exc):
            return ManifestProblem(
                "too_many_jpeg_scans",
                MANIFEST_FILE,
                line,
                image_path,
                f"{exc}; {MOTION_PHOTO_HINT}",
            )
        return ManifestProblem("unreadable_image", MANIFEST_FILE, line, image_path, str(exc))
    except FileNotFoundError:
        return ManifestProblem("missing_file", MANIFEST_FILE, line, image_path, "file not found")
    except (MemoryError, RuntimeError):
        raise  # out of memory or a process configuration error, not an image defect
    except Exception as exc:  # any other failure to read the file
        return ManifestProblem(
            "unreadable_image", MANIFEST_FILE, line, image_path, f"{type(exc).__name__}: {exc}"
        )
    return None


def _row_problems(
    dataset_dir: Path, line: int, row: dict[str, str], grade: str | None, verify_images: bool
) -> list[ManifestProblem]:
    problems: list[ManifestProblem] = []
    image_path = row["image_path"]
    object_type, item_id, angle = row["object_type"], row["item_id"], row["angle"]

    def add(code: str, message: str) -> None:
        problems.append(ManifestProblem(code, MANIFEST_FILE, line, image_path or None, message))

    if object_type not in KNOWN_OBJECT_TYPES:
        add(
            "invalid_object_type",
            f"object_type must be one of {', '.join(KNOWN_OBJECT_TYPES)}, got {object_type!r}",
        )
    if not ITEM_ID_PATTERN.fullmatch(item_id):
        add(
            "invalid_item_id",
            f"item_id must match ^[SNOT]-\\d{{3}}$ or ^X[SNOT]-\\d{{4}}$, got {item_id!r}",
        )
    elif (
        object_type in KNOWN_OBJECT_TYPES
        and ITEM_PREFIX_TYPES.get(item_type_letter(item_id)) != object_type
    ):
        add("item_prefix_mismatch", f"item_id {item_id} does not match object_type {object_type}")
    if grade is not None and grade not in GRADES:
        add("invalid_grade", f"grade must be one of {', '.join(GRADES)}, got {grade!r}")
    if object_type == "other" and grade is not None:
        add("grade_on_other", f"grade must be empty for other, got {grade!r}")
    if object_type in GRADED_OBJECT_TYPES and grade is None:
        add("missing_grade", f"grade is required for {object_type}")
    if not ANGLE_PATTERN.fullmatch(angle):
        add("invalid_angle", f"angle must be an integer in 0..4, got {angle!r}")

    if not _valid_image_path(image_path):
        add("invalid_image_path", "image_path must be a relative path inside the dataset directory")
    elif not (dataset_dir / image_path).is_file():
        add("missing_file", "file not found")
    elif verify_images:
        problem = _image_problem(dataset_dir, line, image_path)
        if problem is not None:
            problems.append(problem)
    return problems


def _item_conflicts(rows: list[tuple[int, dict[str, str]]]) -> list[ManifestProblem]:
    by_item: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for line, row in rows:
        by_item[row["item_id"]].append((line, row["object_type"], row["image_path"]))
    problems = []
    for item_id, entries in by_item.items():
        types = sorted({object_type for _, object_type, _ in entries})
        if len(types) < 2:
            continue
        first_type = entries[0][1]
        line, _, image_path = next(e for e in entries if e[1] != first_type)
        lines = ", ".join(str(e[0]) for e in entries)
        problems.append(
            ManifestProblem(
                "item_type_conflict",
                MANIFEST_FILE,
                line,
                image_path or None,
                f"item {item_id} has more than one object_type: {', '.join(types)} (lines {lines})",
            )
        )
    return problems


def load_manifest(
    dataset_dir: Path | str,
    *,
    apply_overrides: bool = True,
    verify_images: bool = True,
    external_sources: Path | str | None = None,
) -> pd.DataFrame:
    """Load and validate ``dataset_dir/manifest.csv`` (SPEC-011 section 4.1, SPEC-035).

    Returns one row per kept image with the manifest columns plus ``grade_original``,
    ``overridden``, ``origin`` (``capture``, ``contributor`` or ``external``), ``contributor``
    and ``source_id`` (``None`` when not applicable). An empty grade becomes ``None``; ``angle``
    is an ``int``. ``df.attrs`` holds ``manifest_sha256`` and ``n_excluded`` (used by the data
    report), ``excluded_items`` (``image_path -> item_id`` of the excluded manifest rows, used by
    ``qc_ml.split`` so that an item whose old images were all excluded keeps its previous split),
    ``sources_sha256`` and ``external_sources_sha256`` (``None`` when the file is absent).

    ``external_sources`` is the registry of the external sources; ``None`` means
    ``DEFAULT_EXTERNAL_SOURCES`` (``ml/external_sources.csv``). An absent registry is an empty
    one; the registry is always validated in full.

    Raises:
        FileNotFoundError: ``manifest.csv`` does not exist.
        ManifestError: with every problem found (one exception, ``problems`` lists them all).
    """
    root = Path(dataset_dir)
    manifest_bytes = (root / MANIFEST_FILE).read_bytes()
    table = parse_csv(manifest_bytes, MANIFEST_FILE, MANIFEST_COLUMNS)
    if any(p.code in ("missing_column", "unreadable_csv") for p in table.problems):
        raise ManifestError(table.problems)  # aborts the other checks
    problems = list(table.problems)

    # Duplicates are checked on the whole manifest, excluded rows included.
    seen: set[str] = set()
    for line, row in table.rows:
        image_path = row["image_path"]
        if image_path in seen:
            problems.append(
                ManifestProblem(
                    "duplicate_image_path",
                    MANIFEST_FILE,
                    line,
                    image_path or None,
                    "image_path repeated in the manifest",
                )
            )
        seen.add(image_path)
    manifest_paths = seen | set(table.malformed_paths)

    exclusions = _read_exclusions(root)
    problems.extend(exclusions.problems)
    for image_path, line in exclusions.paths.items():
        if image_path not in manifest_paths:
            problems.append(
                ManifestProblem(
                    "exclusion_unknown_image",
                    EXCLUSIONS_FILE,
                    line,
                    image_path,
                    "exclusion for an image_path that is not in the manifest",
                )
            )
    excluded = set(exclusions.paths)
    kept = [(line, row) for line, row in table.rows if row["image_path"] not in excluded]
    n_excluded = len(excluded & seen)
    excluded_items = {
        row["image_path"]: row["item_id"] for _, row in table.rows if row["image_path"] in excluded
    }

    overrides: dict[str, str | None] = {}
    if apply_overrides:
        overrides, override_problems = _read_overrides(root, seen, excluded)
        problems.extend(override_problems)

    grades: list[str | None] = []
    for line, row in kept:
        grade = overrides[row["image_path"]] if row["image_path"] in overrides else row["grade"]
        grade = grade or None
        grades.append(grade)
        problems.extend(_row_problems(root, line, row, grade, verify_images))
    problems.extend(_item_conflicts(kept))

    registry = _read_registry(
        DEFAULT_EXTERNAL_SOURCES if external_sources is None else external_sources
    )
    problems.extend(registry.problems)
    sources = _read_sources(root, registry.known_ids, excluded)
    problems.extend(sources.problems)
    problems.extend(_sources_manifest_problems(sources, manifest_paths, kept))

    for image_path in find_raw_images(root):
        if image_path not in manifest_paths:
            problems.append(
                ManifestProblem(
                    "orphan_image",
                    MANIFEST_FILE,
                    None,
                    image_path,
                    "image file without a manifest row",
                )
            )

    if problems:
        raise ManifestError(problems)

    columns: dict[str, pd.Series] = {
        column: pd.Series([row[column] for _, row in kept], dtype=object)
        for column in MANIFEST_COLUMNS
    }
    columns["grade"] = pd.Series(grades, dtype=object)
    columns["angle"] = pd.Series([int(row["angle"]) for _, row in kept], dtype="int64")
    columns["grade_original"] = pd.Series([row["grade"] or None for _, row in kept], dtype=object)
    columns["overridden"] = pd.Series(
        [row["image_path"] in overrides for _, row in kept], dtype=bool
    )
    origin_rows = [sources.rows.get(row["image_path"]) for _, row in kept]
    columns["origin"] = pd.Series(
        [r["origin"] if r else "capture" for r in origin_rows], dtype=object
    )
    columns["contributor"] = pd.Series(
        [r["contributor"] if r and r["origin"] == "contributor" else None for r in origin_rows],
        dtype=object,
    )
    columns["source_id"] = pd.Series(
        [r["source_id"] if r and r["origin"] == "external" else None for r in origin_rows],
        dtype=object,
    )
    df = pd.DataFrame(columns, columns=list(RESULT_COLUMNS))
    df.attrs["manifest_sha256"] = _sha256_hex(manifest_bytes)
    df.attrs["n_excluded"] = n_excluded
    df.attrs["excluded_items"] = excluded_items
    df.attrs["sources_sha256"] = sources.sha256
    df.attrs["external_sources_sha256"] = registry.sha256
    return df


def manifest_sha256(dataset_dir: Path | str) -> str:
    """SHA-256 (hex) of ``dataset_dir/manifest.csv``."""
    return _sha256_hex((Path(dataset_dir) / MANIFEST_FILE).read_bytes())


def dominant_grade(grades: Iterable[str | None]) -> str:
    """Most frequent grade; a tie goes to the most severe; no grade at all -> ``"none"``."""
    counts = Counter(g for g in grades if g is not None and not pd.isna(g))
    if not counts:
        return NO_GRADE
    return max(counts, key=lambda g: (counts[g], GRADES.index(g)))


# ---------------------------------------------------------------------------------------------
# Data report (SPEC-011 section 4.2)
# ---------------------------------------------------------------------------------------------


def _grade_key(grade: Any) -> str:
    return NO_GRADE if grade is None or pd.isna(grade) else str(grade)


def image_origins(df: pd.DataFrame) -> list[str]:
    """Origin of each row: the ``origin`` column of ``load_manifest`` when present; otherwise
    ``external`` for an external ``item_id`` and ``capture`` for the others."""
    if "origin" in df:
        return [str(o) for o in df["origin"]]
    return ["external" if is_external_item(str(i)) else "capture" for i in df["item_id"]]


def _present(value: Any) -> bool:
    return value is not None and not (isinstance(value, float) and pd.isna(value))


def build_data_report(df: pd.DataFrame, split_df: pd.DataFrame | None = None) -> dict[str, Any]:
    """Counts by type x grade x split, items per grade, images per item and origins.

    ``manifest_sha256`` and ``n_excluded`` come from ``df.attrs`` (set by ``load_manifest``);
    ``split_file`` and ``split_sha256`` from ``split_df.attrs`` (set by ``qc_ml.split.load_split``).
    The report has no pixels and no absolute paths, and never the contributor codes.

    SPEC-035 section 4.5: ``items_per_grade``, ``images_per_item``, ``below_target`` and
    ``below_minimum`` count only the non-external images (the volume targets are of physical
    items); ``n_images``, ``n_items`` and ``counts`` count every image.

    Raises:
        SplitError: an image of ``df`` has no split (``split outdated: run qc_ml.split``).
    """
    split_keys: tuple[str, ...] = (*SPLIT_NAMES, "total") if split_df is not None else ("total",)
    if split_df is not None:
        from qc_ml.split import assign_splits  # lazy: qc_ml.split imports this module

        assigned = list(assign_splits(df, split_df))
    else:
        assigned = [None] * len(df)

    object_types = list(KNOWN_OBJECT_TYPES)
    object_types += sorted(set(df["object_type"]) - set(object_types))
    counts: dict[str, dict[str, dict[str, int]]] = {}
    items: dict[str, dict[str, set[str]]] = {}
    own_images: dict[str, dict[str, int]] = {}  # non-external images by type and grade
    for object_type in object_types:
        grade_keys = GRADES if object_type in GRADED_OBJECT_TYPES else (NO_GRADE,)
        counts[object_type] = {g: dict.fromkeys(split_keys, 0) for g in grade_keys}
        items[object_type] = {g: set() for g in grade_keys}
        own_images[object_type] = dict.fromkeys(grade_keys, 0)

    origins = image_origins(df)
    by_origin_images: dict[str, int] = dict.fromkeys(ORIGINS, 0)
    by_origin_items: dict[str, set[str]] = {o: set() for o in ORIGINS}
    by_origin_split: dict[str, dict[str, int]] = {o: dict.fromkeys(SPLIT_NAMES, 0) for o in ORIGINS}
    own_per_item: Counter[str] = Counter()
    n_external_train = n_train = 0
    for (object_type, grade, item_id), split, origin in zip(
        df[["object_type", "grade", "item_id"]].itertuples(index=False, name=None),
        assigned,
        origins,
        strict=True,
    ):
        key = _grade_key(grade)
        cell = counts[object_type].setdefault(key, dict.fromkeys(split_keys, 0))
        cell["total"] += 1
        if split is not None:
            cell[split] += 1
        external = is_external_item(str(item_id))
        if not external:
            items[object_type].setdefault(key, set()).add(item_id)
            own_images[object_type][key] = own_images[object_type].get(key, 0) + 1
            own_per_item[item_id] += 1
        by_origin_images.setdefault(origin, 0)
        by_origin_images[origin] += 1
        by_origin_items.setdefault(origin, set()).add(item_id)
        if split is not None:
            by_origin_split.setdefault(origin, dict.fromkeys(SPLIT_NAMES, 0))[split] += 1
        if split == "train":
            n_train += 1
            n_external_train += int(external)

    items_per_grade = {
        object_type: {g: len(ids) for g, ids in by_grade.items()}
        for object_type, by_grade in items.items()
    }
    below_target: list[dict[str, Any]] = []
    below_minimum: list[dict[str, Any]] = []
    for object_type in GRADED_OBJECT_TYPES:
        for grade in GRADES:
            entry = {
                "object_type": object_type,
                "grade": grade,
                "n_images": own_images[object_type][grade],
                "n_items": items_per_grade[object_type][grade],
            }
            if (
                entry["n_images"] < TARGET_IMAGES_PER_GRADE
                or entry["n_items"] < TARGET_ITEMS_PER_GRADE
            ):
                below_target.append(entry)
            if entry["n_items"] < MINIMUM_ITEMS_PER_GRADE:
                below_minimum.append(dict(entry))

    per_item = list(own_per_item.values())
    images_per_item: dict[str, float | int | None] = {
        "min": min(per_item) if per_item else None,
        "median": float(statistics.median(per_item)) if per_item else None,
        "mean": float(statistics.fmean(per_item)) if per_item else None,
        "max": max(per_item) if per_item else None,
    }

    split_attrs = split_df.attrs if split_df is not None else {}
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "manifest_sha256": df.attrs.get("manifest_sha256"),
        "split_file": split_attrs.get("split_file"),
        "split_sha256": split_attrs.get("split_sha256"),
        "n_images": len(df),
        "n_items": int(df["item_id"].nunique()),
        "n_overridden": int(df["overridden"].sum()) if "overridden" in df else 0,
        "n_excluded": int(df.attrs.get("n_excluded", 0)),
        "counts": counts,
        "items_per_grade": items_per_grade,
        "images_per_item": images_per_item,
        "below_target": below_target,
        "below_minimum": below_minimum,
        "counts_by_origin": {
            origin: {
                "n_images": by_origin_images[origin],
                "n_items": len(by_origin_items[origin]),
                "by_split": by_origin_split[origin] if split_df is not None else {},
            }
            for origin in by_origin_images
        },
        "n_contributors": (
            len({str(c) for c in df["contributor"] if _present(c)}) if "contributor" in df else 0
        ),
        "by_source": (
            dict(sorted(Counter(str(s) for s in df["source_id"] if _present(s)).items()))
            if "source_id" in df
            else {}
        ),
        "external_fraction_train": (
            n_external_train / n_train if split_df is not None and n_train else None
        ),
    }


def write_json(path: Path, data: Any) -> None:
    """Write ``data`` as indented UTF-8 JSON (parent directories created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------


def print_problems(problems: Sequence[ManifestProblem], out: Any = None) -> None:
    """One line per problem, then one ``count <code>: <n>`` line per code, alphabetically."""
    out = sys.stdout if out is None else out
    for problem in problems:
        print(problem, file=out)
    for code, n in sorted(Counter(p.code for p in problems).items()):
        print(f"count {code}: {n}", file=out)


def configure_logging() -> None:
    """Basic logging for the CLIs, unless the caller already configured it."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qc_ml.data", description="Validate the manifest or write the data report."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate", help="validate manifest, overrides, exclusions and sources"
    )
    report = commands.add_parser("report", help="write the data report JSON")
    for command in (validate, report):
        command.add_argument("--dataset-dir", type=Path, default=Path("ml/data"))
        command.add_argument(
            "--external-sources",
            type=Path,
            default=None,
            help="registry of the external sources (default: ml/external_sources.csv)",
        )
    report.add_argument("--split", type=Path, default=None, help="split_v<N>.csv")
    report.add_argument("--out", type=Path, default=Path("ml/reports/data_report.json"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; returns 0 on success and 2 on any problem."""
    configure_logging()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR

    try:
        df = load_manifest(args.dataset_dir, external_sources=args.external_sources)
    except ManifestError as exc:
        print_problems(exc.problems)
        return EXIT_ERROR
    except OSError as exc:
        print(f"cannot read the manifest: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.command == "validate":
        print(
            f"manifest ok: {len(df)} images, {df['item_id'].nunique()} items, "
            f"{df.attrs['n_excluded']} excluded, {int(df['overridden'].sum())} overridden"
        )
        return EXIT_OK

    split_df = None
    if args.split is not None:
        from qc_ml.split import load_split

        try:
            split_df = load_split(args.split)
        except (SplitError, OSError) as exc:
            print(f"cannot use the split: {exc}", file=sys.stderr)
            return EXIT_ERROR
    try:
        report = build_data_report(df, split_df)
    except SplitError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    write_json(args.out, report)
    print(f"data report written: {args.out}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
