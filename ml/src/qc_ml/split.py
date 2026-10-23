"""Split grouped by physical item (``item_id``), with a frozen test set (SPEC-011 section 4.4).

R-11 and ADR-014: every image of an item lands in the same split; the test set of ``split_v1`` is
frozen (new items only go to train/val); ``rows_for`` is the only way to get the rows of a split.

No torch here (SPEC-011 section 4.5).

CLI::

    python -m qc_ml.split --dataset-dir ml/data --splits-dir ml/splits --seed 42
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import numpy as np
import pandas as pd

from qc_ml.data import (
    ITEM_ID_PATTERN,
    SPLIT_NAMES,
    configure_logging,
    dominant_grade,
    load_exclusions,
    load_manifest,
    print_problems,
)
from qc_ml.errors import ManifestError, SplitError, SplitIntegrityError

SPLIT_COLUMNS: tuple[str, str] = ("image_path", "split")
SPLIT_FILE_PATTERN = re.compile(r"split_v([1-9][0-9]*)\.csv")
# File name written by the collect mode (SPEC-010): <item_id>__<angle>__<ts>.jpg. The item_id
# part reuses qc_ml.data.ITEM_ID_PATTERN, the single definition of a valid item_id (SPEC-031).
IMAGE_FILE_PATTERN = re.compile(rf"({ITEM_ID_PATTERN.pattern})__[0-4]__[0-9]{{8}}T[0-9]{{6}}Z\.jpg")
DEFAULT_RATIOS: tuple[float, float, float] = (0.70, 0.15, 0.15)
OUTDATED_MESSAGE = "split outdated: run qc_ml.split"
MIN_STRATUM_ITEMS = 3

EXIT_OK = 0
EXIT_ERROR = 2

SplitName = Literal["train", "val", "test"]


@dataclass(frozen=True)
class SplitResult:
    """``frame`` has the columns ``image_path`` and ``split``, sorted by ``image_path``."""

    frame: pd.DataFrame
    warnings: list[dict[str, Any]] = field(default_factory=list)


def round_half_up(value: Decimal | float | int) -> int:
    """Round half away from zero for non-negative values (Python's ``round`` rounds to even)."""
    number = value if isinstance(value, Decimal) else Decimal(repr(value))
    return int(number.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _check_ratios(ratios: Sequence[float]) -> tuple[Decimal, Decimal, Decimal]:
    if len(ratios) != 3:
        raise SplitError(f"ratios must have 3 values (train, val, test), got {ratios!r}")
    values = tuple(Decimal(repr(float(r))) for r in ratios)
    if any(v <= 0 or v >= 1 for v in values) or abs(sum(values) - 1) > Decimal("1e-9"):
        raise SplitError(f"ratios must be in (0, 1) and add up to 1, got {ratios!r}")
    return values  # type: ignore[return-value]


def stratum_name(stratum: tuple[str, str]) -> str:
    """``("screw", "fair")`` -> ``"screw/fair"``."""
    return f"{stratum[0]}/{stratum[1]}"


def item_strata(df: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """``item_id`` -> ``(object_type, dominant grade)``; ``other`` has grade ``"none"``."""
    strata: dict[str, tuple[str, str]] = {}
    for item_id, group in df.groupby("item_id", sort=True):
        object_type = str(group["object_type"].iloc[0])
        strata[str(item_id)] = (object_type, dominant_grade(group["grade"]))
    return strata


def _allocate(
    groups: dict[tuple[str, str], list[str]],
    rng: np.random.Generator,
    val_ratio: Decimal,
    test_ratio: Decimal | None,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Allocate the items of each stratum; ``test_ratio=None`` -> train/val only.

    With ``test_ratio=None`` (only the new items of a frozen split), ``small_stratum`` carries
    ``"scope": "new_items"``: the stratum may be large; only its new items are fewer than 3.

    Strata in lexicographic order; inside each, sorted ``item_id`` permuted by the single ``rng``.
    The first ``n_test`` permuted items go to test, the next ``n_val`` to val, the rest to train.
    """
    assignment: dict[str, str] = {}
    warnings: list[dict[str, Any]] = []
    for stratum in sorted(groups):
        ids = sorted(groups[stratum])
        order = [ids[i] for i in rng.permutation(len(ids))]
        n = len(ids)
        if n < MIN_STRATUM_ITEMS:
            n_test = n_val = 0
            warning: dict[str, Any] = {
                "code": "small_stratum",
                "stratum": stratum_name(stratum),
                "n_items": n,
            }
            if test_ratio is None:
                warning["scope"] = "new_items"
            warnings.append(warning)
        else:
            n_test = 0 if test_ratio is None else max(1, round_half_up(test_ratio * n))
            n_val = max(1, round_half_up(val_ratio * n))
            while n_test + n_val > n - 1 and (n_val > 1 or n_test > 1):  # keep 1 in train
                if n_val > 1:
                    n_val -= 1
                else:
                    n_test -= 1
        for position, item_id in enumerate(order):
            if position < n_test:
                assignment[item_id] = "test"
            elif position < n_test + n_val:
                assignment[item_id] = "val"
            else:
                assignment[item_id] = "train"
    return assignment, warnings


def _previous_map(previous: pd.DataFrame) -> dict[str, str]:
    if list(previous.columns[:2]) != list(SPLIT_COLUMNS):
        raise SplitError(f"previous split must have the columns {', '.join(SPLIT_COLUMNS)}")
    mapping: dict[str, str] = {}
    for image_path, split in zip(previous["image_path"], previous["split"], strict=True):
        if split not in SPLIT_NAMES:
            raise SplitError(f"previous split has an invalid split {split!r} for {image_path}")
        if image_path in mapping:
            raise SplitError(f"previous split repeats {image_path}")
        mapping[str(image_path)] = str(split)
    return mapping


def item_id_resolver(df: pd.DataFrame) -> Callable[[str], str | None]:
    """Resolve the ``item_id`` of an image of a previous split (SPEC-011 §4.4, sources).

    The first source that gives a result wins:

    1. the row of ``df`` with that ``image_path``, including a row that is in ``excluded``;
    2. ``df.attrs["excluded_items"]`` (set by ``load_manifest``), only if the ``item_id`` matches
       ``[SNOT]-[0-9]{3}``; otherwise the image goes on to source 3;
    3. the SPEC-010 file name ``<item_id>__<angle>__<ts>.jpg`` (last path component).

    An image without any source resolves to ``None`` and is ignored by the callers.
    """
    rows = {str(p): str(i) for p, i in zip(df["image_path"], df["item_id"], strict=True)}
    excluded_items = df.attrs.get("excluded_items") or {}

    def resolve(image_path: str) -> str | None:
        if image_path in rows:
            return rows[image_path]
        item_id = excluded_items.get(image_path)
        if isinstance(item_id, str) and ITEM_ID_PATTERN.fullmatch(item_id):
            return item_id
        match = IMAGE_FILE_PATTERN.fullmatch(PurePosixPath(image_path).name)
        return match.group(1) if match else None

    return resolve


def item_history(splits: Sequence[pd.DataFrame], df: pd.DataFrame) -> dict[str, str]:
    """``item_id -> split`` over every split version in ``splits`` (SPEC-011 §4.4).

    Each frame is in the ``load_split`` format; the ``item_id`` of each ``image_path`` comes from
    ``item_id_resolver(df)``. No file is read and no hash is checked here.

    Raises:
        SplitIntegrityError: an item has images in two or more splits, over all rows of all
            frames (inside one frame too). The message has the ``item_id`` and, for each split,
            the files it came from (``attrs["split_file"]``, or ``#<index in the list>``). The
            conflict is never resolved here.
    """
    resolve = item_id_resolver(df)
    seen: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for index, frame in enumerate(splits):
        source = str(frame.attrs.get("split_file") or f"#{index}")
        for image_path, split in zip(frame["image_path"], frame["split"], strict=True):
            item_id = resolve(str(image_path))
            if item_id is None:
                continue
            files = seen[item_id].setdefault(str(split), [])
            if source not in files:
                files.append(source)
    conflicts = []
    for item_id in sorted(seen):
        by_split = seen[item_id]
        if len(by_split) > 1:
            where = "; ".join(
                f"{split} in {', '.join(by_split[split])}" for split in sorted(by_split)
            )
            conflicts.append(f"item {item_id} is in more than one split: {where}")
    if conflicts:
        raise SplitIntegrityError(
            "split history conflict (R-11; never resolved automatically): " + " | ".join(conflicts)
        )
    return {item_id: next(iter(by_split)) for item_id, by_split in seen.items()}


def check_item_integrity(df: pd.DataFrame, splits: Sequence[str] | pd.Series) -> None:
    """Raise ``SplitIntegrityError`` when an ``item_id`` has images in two or more splits."""
    seen: dict[str, str] = {}
    for item_id, split in zip(df["item_id"], splits, strict=True):
        if seen.setdefault(item_id, split) != split:
            raise SplitIntegrityError(
                f"item {item_id} is in more than one split ({seen[item_id]}, {split}); R-11"
            )


def make_split(
    df: pd.DataFrame,
    seed: int = 42,
    ratios: tuple[float, float, float] = DEFAULT_RATIOS,
    previous: pd.DataFrame | None = None,
    excluded: frozenset[str] = frozenset(),
    history: Mapping[str, str] | None = None,
) -> SplitResult:
    """Split ``df`` (from ``load_manifest``) by item, stratified by (type, dominant grade).

    Without ``previous``: per stratum, ``n_test = n_val = round_half_up(0.15 * n)`` (at least 1
    each with ``n >= 3``), the rest in train; ``n < 3`` -> all in train and ``small_stratum``.

    With ``previous`` (the last split): items already there keep their split, new images of an
    old item inherit it; new items go to train/val only (70:15 per stratum, same rules). An item
    is old when its ``item_id`` is in ``history`` (every earlier version, from ``item_history``)
    or when any image of ``previous`` resolves to it (``item_id_resolver``), so a re-photographed
    test item stays in test (R-11). A
    previous image in ``excluded`` leaves the split with ``excluded_previous_image``; any other
    previous image missing from ``df`` is a ``SplitError`` in test and ``missing_previous_image``
    in train/val.

    ``history`` (``item_id -> split``) is only accepted with ``previous``; the warnings and the
    error about missing images look only at ``previous``. A ``history`` entry without images in
    ``df`` is ignored.

    Raises:
        SplitError: invalid ratios, previous split or ``history`` value, ``history`` without
            ``previous``, or a frozen test image is missing.
        SplitIntegrityError: an item would end up in two splits, its images in ``previous`` are
            in two splits, or ``history`` disagrees with ``previous`` for it.
    """
    _, r_val, r_test = _check_ratios(ratios)
    r_train = Decimal(1) - r_val - r_test
    history = dict(history or {})
    if history and previous is None:
        raise SplitError("history needs previous: the split history starts at split_v1")
    invalid = sorted(f"{i}={s!r}" for i, s in history.items() if s not in SPLIT_NAMES)
    if invalid:
        raise SplitError(f"history has invalid splits: {', '.join(invalid)}")
    rng = np.random.default_rng(seed)
    resolve = item_id_resolver(df)  # before the excluded rows leave df (source 1)
    df = df[~df["image_path"].isin(list(excluded))]
    strata = item_strata(df)
    images_by_item: dict[str, list[str]] = defaultdict(list)
    for item_id, image_path in zip(df["item_id"], df["image_path"], strict=True):
        images_by_item[item_id].append(image_path)

    warnings: list[dict[str, Any]] = []
    if previous is None:
        groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        for item_id, stratum in strata.items():
            groups[stratum].append(item_id)
        assignment, allocation_warnings = _allocate(groups, rng, r_val, r_test)
        warnings.extend(allocation_warnings)
        prev: dict[str, str] = {}
    else:
        prev = _previous_map(previous)
        current = set(df["image_path"])
        missing_test: list[str] = []
        for image_path, split in sorted(prev.items()):
            if image_path in current:
                continue
            if image_path in excluded:
                warnings.append(
                    {"code": "excluded_previous_image", "image_path": image_path, "split": split}
                )
            elif split == "test":
                missing_test.append(image_path)
            else:
                warnings.append(
                    {"code": "missing_previous_image", "image_path": image_path, "split": split}
                )
        if missing_test:
            raise SplitError(
                "test images of the previous split are missing from the manifest (the test set "
                "is frozen, R-11; an image that had to leave the dataset goes to exclusions.csv): "
                + ", ".join(missing_test)
            )
        previous_splits: dict[str, set[str]] = defaultdict(set)
        for image_path, split in prev.items():
            item_id = resolve(image_path)
            if item_id is not None:
                previous_splits[item_id].add(split)
        assignment = {}
        new_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        for item_id in sorted(images_by_item):
            old = sorted(previous_splits.get(item_id, set()))
            if len(old) > 1:
                raise SplitIntegrityError(
                    f"item {item_id} is in more than one split of the previous split: "
                    f"{', '.join(old)}"
                )
            earlier = history.get(item_id)
            if earlier is not None and old and old[0] != earlier:
                raise SplitIntegrityError(
                    f"item {item_id} is in {earlier} in the split history but in {old[0]} in "
                    "the previous split"
                )
            if earlier is not None:
                assignment[item_id] = earlier
            elif old:
                assignment[item_id] = old[0]
            else:
                new_groups[strata[item_id]].append(item_id)
        new_assignment, allocation_warnings = _allocate(
            new_groups, rng, r_val / (r_train + r_val), None
        )
        assignment.update(new_assignment)
        warnings.extend(allocation_warnings)

    splits = [assignment[item_id] for item_id in df["item_id"]]
    check_item_integrity(df, splits)
    for image_path, split in zip(df["image_path"], splits, strict=True):
        if image_path in prev and prev[image_path] != split:
            raise SplitIntegrityError(f"{image_path} would move from {prev[image_path]} to {split}")
    frame = (
        pd.DataFrame(
            {
                "image_path": pd.Series(list(df["image_path"]), dtype=object),
                "split": pd.Series(splits, dtype=object),
            }
        )
        .sort_values("image_path", kind="stable")
        .reset_index(drop=True)
    )
    return SplitResult(frame=frame, warnings=warnings)


# ---------------------------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------------------------


def split_csv_bytes(frame: pd.DataFrame) -> bytes:
    """``image_path,split`` sorted by ``image_path``, UTF-8, ``\\n``, no index."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(SPLIT_COLUMNS)
    rows = sorted(zip(frame["image_path"], frame["split"], strict=True))
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _sha256_line(digest: str, csv_name: str) -> str:
    return f"{digest}  {csv_name}\n"


def load_split(path: Path | str) -> pd.DataFrame:
    """Read ``split_v<N>.csv`` after checking it against ``split_v<N>.sha256``.

    ``df.attrs`` holds ``split_file`` (file name only) and ``split_sha256``.

    Raises:
        SplitError: missing ``.sha256``, hash mismatch or an invalid file.
    """
    path = Path(path)
    data = path.read_bytes()
    sha_path = path.with_suffix(".sha256")
    if not sha_path.is_file():
        raise SplitError(f"{sha_path.name} not found next to {path.name}")
    tokens = sha_path.read_text(encoding="utf-8").split()
    expected = tokens[0].lower() if tokens else ""
    actual = hashlib.sha256(data).hexdigest()
    if expected != actual:
        raise SplitError(
            f"{path.name}: sha256 mismatch with {sha_path.name} (the split was edited after it "
            "was written; regenerate it with qc_ml.split instead of editing it)"
        )
    try:
        records = list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise SplitError(f"{path.name}: unreadable CSV: {exc}") from exc
    if not records or tuple(records[0]) != SPLIT_COLUMNS:
        raise SplitError(f"{path.name}: header must be {','.join(SPLIT_COLUMNS)}")
    paths: list[str] = []
    splits: list[str] = []
    for number, record in enumerate(records[1:], start=2):
        if len(record) != 2 or record[1] not in SPLIT_NAMES:
            raise SplitError(f"{path.name}:{number}: invalid row {record!r}")
        paths.append(record[0])
        splits.append(record[1])
    if len(set(paths)) != len(paths):
        raise SplitError(f"{path.name}: repeated image_path")
    frame = pd.DataFrame(
        {"image_path": pd.Series(paths, dtype=object), "split": pd.Series(splits, dtype=object)}
    )
    frame.attrs["split_file"] = path.name
    frame.attrs["split_sha256"] = actual
    return frame


def assign_splits(df: pd.DataFrame, split_df: pd.DataFrame) -> pd.Series:
    """Split of each row of ``df`` (same index).

    Raises:
        SplitError: an image of ``df`` has no split (``split outdated: run qc_ml.split``).
    """
    mapping = dict(zip(split_df["image_path"], split_df["split"], strict=True))
    missing = [p for p in df["image_path"] if p not in mapping]
    if missing:
        shown = ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else "")
        raise SplitError(f"{OUTDATED_MESSAGE} ({len(missing)} images without split: {shown})")
    return pd.Series([mapping[p] for p in df["image_path"]], index=df.index, dtype=object)


def rows_for(df: pd.DataFrame, split_df: pd.DataFrame, which: SplitName) -> pd.DataFrame:
    """The rows of ``df`` in split ``which``: the only way to get the rows of a split (R-11).

    Raises:
        ValueError: ``which`` is not ``train``, ``val`` or ``test``.
        SplitError: an image of ``df`` has no split (``split outdated: run qc_ml.split``).
        SplitIntegrityError: an item of ``df`` has images in two splits.
    """
    if which not in SPLIT_NAMES:
        raise ValueError(f"which must be one of {', '.join(SPLIT_NAMES)}, got {which!r}")
    splits = assign_splits(df, split_df)
    check_item_integrity(df, splits)
    return df[splits == which].reset_index(drop=True)


def split_versions(splits_dir: Path) -> list[int]:
    """Versions ``N`` of the ``split_v<N>.csv`` files in ``splits_dir``, ascending."""
    if not splits_dir.is_dir():
        return []
    versions = []
    for entry in splits_dir.iterdir():
        match = SPLIT_FILE_PATTERN.fullmatch(entry.name)
        if match and entry.is_file():
            versions.append(int(match.group(1)))
    return sorted(versions)


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _counts(frame: pd.DataFrame, df: pd.DataFrame) -> dict[str, dict[str, int]]:
    items = dict(zip(df["image_path"], df["item_id"], strict=True))
    images = {s: int((frame["split"] == s).sum()) for s in SPLIT_NAMES}
    item_sets: dict[str, set[str]] = {s: set() for s in SPLIT_NAMES}
    for image_path, split in zip(frame["image_path"], frame["split"], strict=True):
        item_sets[split].add(items[image_path])
    return {"images": images, "items": {s: len(item_sets[s]) for s in SPLIT_NAMES}}


def write_split(
    splits_dir: Path,
    version: int,
    result: SplitResult,
    df: pd.DataFrame,
    *,
    seed: int,
    ratios: Sequence[float],
) -> Path:
    """Write ``split_v<N>.json``, ``.sha256`` and, last, ``.csv``; return the CSV path."""
    splits_dir.mkdir(parents=True, exist_ok=True)
    csv_name = f"split_v{version}.csv"
    csv_path = splits_dir / csv_name
    content = split_csv_bytes(result.frame)
    digest = hashlib.sha256(content).hexdigest()
    meta = {
        "split_file": csv_name,
        "seed": seed,
        "ratios": [float(r) for r in ratios],
        "parent": None if version == 1 else f"split_v{version - 1}",
        "manifest_sha256": df.attrs.get("manifest_sha256"),
        "counts": _counts(result.frame, df),
        "warnings": result.warnings,
    }
    meta_bytes = (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_write(splits_dir / f"split_v{version}.json", meta_bytes)
    _atomic_write(splits_dir / f"split_v{version}.sha256", _sha256_line(digest, csv_name).encode())
    _atomic_write(csv_path, content)  # last: a CSV on disk always has its .sha256 and .json
    return csv_path


def _same_split(frame: pd.DataFrame, previous: pd.DataFrame) -> bool:
    return sorted(zip(frame["image_path"], frame["split"], strict=True)) == sorted(
        zip(previous["image_path"], previous["split"], strict=True)
    )


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qc_ml.split", description="Create or extend the item-grouped split."
    )
    parser.add_argument("--dataset-dir", type=Path, default=Path("ml/data"))
    parser.add_argument("--splits-dir", type=Path, default=Path("ml/splits"))
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; 0 when a split was written or nothing changed, 2 on any error.

    Steps of SPEC-011 §4.4: manifest and exclusions; list ``split_v<N>.csv``; require versions
    ``1..M`` without gaps; read all of them with ``load_split``; ``previous`` = version ``M`` and
    ``history = item_history(all versions)``; ``make_split``; write ``split_v{M+1}`` only if it
    changed. Nothing is written on any error.
    """
    configure_logging()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR

    try:
        df = load_manifest(args.dataset_dir)
        excluded = load_exclusions(args.dataset_dir)
    except ManifestError as exc:
        print_problems(exc.problems, sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"cannot read the dataset: {exc}", file=sys.stderr)
        return EXIT_ERROR

    versions = split_versions(args.splits_dir)
    previous: pd.DataFrame | None = None
    history: dict[str, str] | None = None
    if versions:
        # 3. Complete history: versions 1..M, no gap, no renumbering.
        missing = sorted(set(range(1, versions[-1] + 1)) - set(versions))
        if missing:
            names = ", ".join(f"split_v{k}.csv" for k in missing)
            print(
                f"split history incomplete: missing {names} (restore it from Git; old split "
                "versions are never deleted or renumbered)",
                file=sys.stderr,
            )
            return EXIT_ERROR
        # 4. Every version, hash checked.
        frames: list[pd.DataFrame] = []
        for version in versions:
            name = f"split_v{version}.csv"
            try:
                frames.append(load_split(args.splits_dir / name))
            except (SplitError, OSError) as exc:
                print(f"split error: {name}: {exc}", file=sys.stderr)
                return EXIT_ERROR
        # 5. previous = version M; history over all versions.
        previous = frames[-1]
        try:
            history = item_history(frames, df)
        except SplitIntegrityError as exc:
            print(f"split error: {exc}", file=sys.stderr)
            return EXIT_ERROR

    try:
        result = make_split(
            df, seed=args.seed, previous=previous, excluded=excluded, history=history
        )
    except SplitError as exc:
        print(f"split error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if previous is not None and _same_split(result.frame, previous):
        print(f"split unchanged: split_v{versions[-1]}")
        return EXIT_OK
    version = versions[-1] + 1 if versions else 1
    path = write_split(args.splits_dir, version, result, df, seed=args.seed, ratios=DEFAULT_RATIOS)
    counts = _counts(result.frame, df)
    print(
        f"split written: {path.name} (images {counts['images']}, items {counts['items']}, "
        f"{len(result.warnings)} warnings)"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
