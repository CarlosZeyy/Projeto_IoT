"""Manifest loading, label overrides, exclusions and the data report (SPEC-011 sections 4.1-4.2).

This is a module, not a package: the ``.gitignore`` ignores every ``data/`` directory.

The CSV files are read only with the ``csv`` module over text opened with ``newline=""``, never
by splitting lines (SEC-10-03): rows written before SPEC-025 may contain U+2028, U+2029 or U+0085
in ``notes`` or ``capture_device``, which ``str.splitlines()`` would count as line breaks. The
pipeline does not take the edge's ``manifest.csv.lock`` (SEC-10-06): it reads the manifest once.

No torch here (SPEC-011 section 4.5).

CLI::

    python -m qc_ml.data validate --dataset-dir ml/data
    python -m qc_ml.data report --dataset-dir ml/data --split ml/splits/split_v1.csv \
        --out ml/reports/data_report.json
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
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from qc_contracts import GRADE_ORDER
from qc_ml.errors import ManifestError, ManifestProblem, SplitError
from qc_preprocess import InvalidImageError, load_image

logger = logging.getLogger(__name__)

MANIFEST_FILE = "manifest.csv"
OVERRIDES_FILE = "labels_overrides.csv"
EXCLUSIONS_FILE = "exclusions.csv"
RAW_DIR = "raw"

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
RESULT_COLUMNS: tuple[str, ...] = (*MANIFEST_COLUMNS, "grade_original", "overridden")

KNOWN_OBJECT_TYPES: tuple[str, ...] = ("screw", "nut", "other")
GRADED_OBJECT_TYPES: tuple[str, ...] = ("screw", "nut")
GRADES: tuple[str, ...] = tuple(g.value for g in GRADE_ORDER)
NO_GRADE = "none"
SPLIT_NAMES: tuple[str, ...] = ("train", "val", "test")

ITEM_ID_PATTERN = re.compile(r"[SNOT]-[0-9]{3}")
ANGLE_PATTERN = re.compile(r"[0-4]")
ITEM_PREFIX_TYPES: dict[str, str] = {"S": "screw", "N": "nut", "O": "other"}

# SPEC-024 section 4.1 guarantees this text in the message of the scan-limit error.
JPEG_SCANS_TEXT = "JPEG scans"
MOTION_PHOTO_HINT = "motion photo? see docs/dataset-protocol.md section 3"

# docs/dataset-protocol.md section 4.
TARGET_IMAGES_PER_GRADE = 120
TARGET_ITEMS_PER_GRADE = 12
MINIMUM_ITEMS_PER_GRADE = 8

EXIT_OK = 0
EXIT_ERROR = 2


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


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_csv(data: bytes, file_name: str, required: Sequence[str]) -> CsvTable:
    """Parse CSV bytes with ``csv.reader``; record numbers count the header as 1.

    Blank records are skipped (as ``csv.DictReader`` does) and do not get a number.
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
        add("invalid_item_id", f"item_id must match ^[SNOT]-\\d{{3}}$, got {item_id!r}")
    elif object_type in KNOWN_OBJECT_TYPES and ITEM_PREFIX_TYPES.get(item_id[0]) != object_type:
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
    dataset_dir: Path | str, *, apply_overrides: bool = True, verify_images: bool = True
) -> pd.DataFrame:
    """Load and validate ``dataset_dir/manifest.csv`` (SPEC-011 section 4.1).

    Returns one row per kept image with the manifest columns plus ``grade_original`` and
    ``overridden``. An empty grade becomes ``None``; ``angle`` is an ``int``. ``df.attrs`` holds
    ``manifest_sha256`` and ``n_excluded`` (used by the data report) and ``excluded_items``
    (``image_path -> item_id`` of the excluded manifest rows, used by ``qc_ml.split`` so that an
    item whose old images were all excluded keeps its previous split).

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
    df = pd.DataFrame(columns, columns=list(RESULT_COLUMNS))
    df.attrs["manifest_sha256"] = _sha256_hex(manifest_bytes)
    df.attrs["n_excluded"] = n_excluded
    df.attrs["excluded_items"] = excluded_items
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


def build_data_report(df: pd.DataFrame, split_df: pd.DataFrame | None = None) -> dict[str, Any]:
    """Counts by type x grade x split, items per grade and images per item.

    ``manifest_sha256`` and ``n_excluded`` come from ``df.attrs`` (set by ``load_manifest``);
    ``split_file`` and ``split_sha256`` from ``split_df.attrs`` (set by ``qc_ml.split.load_split``).
    The report has no pixels and no absolute paths.

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
    for object_type in object_types:
        grade_keys = GRADES if object_type in GRADED_OBJECT_TYPES else (NO_GRADE,)
        counts[object_type] = {g: dict.fromkeys(split_keys, 0) for g in grade_keys}
        items[object_type] = {g: set() for g in grade_keys}

    for (object_type, grade, item_id), split in zip(
        df[["object_type", "grade", "item_id"]].itertuples(index=False, name=None),
        assigned,
        strict=True,
    ):
        key = _grade_key(grade)
        cell = counts[object_type].setdefault(key, dict.fromkeys(split_keys, 0))
        cell["total"] += 1
        if split is not None:
            cell[split] += 1
        items[object_type].setdefault(key, set()).add(item_id)

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
                "n_images": counts[object_type][grade]["total"],
                "n_items": items_per_grade[object_type][grade],
            }
            if (
                entry["n_images"] < TARGET_IMAGES_PER_GRADE
                or entry["n_items"] < TARGET_ITEMS_PER_GRADE
            ):
                below_target.append(entry)
            if entry["n_items"] < MINIMUM_ITEMS_PER_GRADE:
                below_minimum.append(dict(entry))

    per_item = list(Counter(df["item_id"]).values())
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
    validate = commands.add_parser("validate", help="validate manifest, overrides and exclusions")
    validate.add_argument("--dataset-dir", type=Path, default=Path("ml/data"))
    report = commands.add_parser("report", help="write the data report JSON")
    report.add_argument("--dataset-dir", type=Path, default=Path("ml/data"))
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
        df = load_manifest(args.dataset_dir)
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
