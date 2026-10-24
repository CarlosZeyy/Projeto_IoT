"""Split grouped by physical item (``item_id``), with a frozen test set (SPEC-011 section 4.4).

R-11 and ADR-014: every image of an item lands in the same split; the test set of ``split_v1`` is
frozen (new items only go to train/val); ``rows_for`` is the only way to get the rows of a split.

ADR-020 and SPEC-035 section 4.4: every external image (``is_external_item``) goes to train in
every version, outside the strata; ``rows_for`` refuses one in val or test; the fraction of
external images in train has a ceiling (``max_external_fraction``, 30% by default).

ADR-022 and SPEC-016 section 4.7: a **new object type** (images in the dataset, no line in any
earlier split version) needs a decision once there is an earlier version: ``--extend-test-types``
(its non-external items are split 70/15/15, test included, once) or ``--defer-types`` (its images
stay out of the split). The rows of a type without any line in the split are ignored when the
split is read (``assign_splits``, ``rows_for``), with a ``deferred type images`` log line.

No torch here (SPEC-011 section 4.5).

CLI::

    python -m qc_ml.split --dataset-dir ml/data --splits-dir ml/splits --seed 42 \
        [--external-sources <file>] [--max-external-fraction 0.30] \
        [--extend-test-types <t1,...>] [--defer-types <t1,...>]
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
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import numpy as np
import pandas as pd

from qc_ml.data import (
    ITEM_ID_PATTERN,
    ITEM_PREFIX_TYPES,
    KNOWN_OBJECT_TYPES,
    SPLIT_NAMES,
    configure_logging,
    dominant_grade,
    is_external_item,
    item_type_letter,
    load_exclusions,
    load_manifest,
    print_problems,
)
from qc_ml.errors import ManifestError, SplitError, SplitIntegrityError

logger = logging.getLogger(__name__)

SPLIT_COLUMNS: tuple[str, str] = ("image_path", "split")
SPLIT_FILE_PATTERN = re.compile(r"split_v([1-9][0-9]*)\.csv")
# File name written by the collect mode (SPEC-010) and the importer (SPEC-036):
# <item_id>__<angle>__<ts>.jpg. The item_id part reuses qc_ml.data.ITEM_ID_PATTERN, the single
# definition of a valid item_id (SPEC-031 section 4.6, SPEC-035 section 4.1).
IMAGE_FILE_PATTERN = re.compile(
    "(" + ITEM_ID_PATTERN.pattern + r")__[0-4]__[0-9]{8}T[0-9]{6}Z\.jpg"
)
DEFAULT_RATIOS: tuple[float, float, float] = (0.70, 0.15, 0.15)
DEFAULT_MAX_EXTERNAL_FRACTION = 0.30  # ADR-020, decision 2
OUTDATED_MESSAGE = "split outdated: run qc_ml.split"
MIN_STRATUM_ITEMS = 3
MIN_EXTENSION_ITEMS = 3  # ADR-022, decision 3: fewer non-external items cannot have a test
NEW_TYPE_WITHOUT_DECISION = "new object type without decision: "
TOO_FEW_TO_EXTEND = "too few items to extend the test: "
TYPE_NOT_NEW = "object type is not new: "
TYPE_IN_BOTH_LISTS = "object type in both --extend-test-types and --defer-types: "
UNKNOWN_TYPE = "unknown object type: "
DEFERRED_LOG = "deferred type images: "

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
       ``ITEM_ID_PATTERN``; otherwise the image goes on to source 3;
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


def line_type_resolver(df: pd.DataFrame) -> Callable[[str], str | None]:
    """Resolve the ``object_type`` of an image of a split (SPEC-016 section 4.7).

    1. the row of ``df`` with that ``image_path``;
    2. the ``item_id`` from ``item_id_resolver(df)``, then the type of that item in ``df``, or the
       single type its letter allows (``S``, ``N``, ``O``; a ``T`` item outside ``df`` cannot be
       told apart among the tools).

    ``None`` when no source gives a type.
    """
    types = {str(p): str(t) for p, t in zip(df["image_path"], df["object_type"], strict=True)}
    item_types = {str(i): str(t) for i, t in zip(df["item_id"], df["object_type"], strict=True)}
    resolve_item = item_id_resolver(df)

    def resolve(image_path: str) -> str | None:
        if image_path in types:
            return types[image_path]
        item_id = resolve_item(image_path)
        if item_id is None:
            return None
        if item_id in item_types:
            return item_types[item_id]
        allowed = ITEM_PREFIX_TYPES.get(item_type_letter(item_id), frozenset())
        return next(iter(allowed)) if len(allowed) == 1 else None

    return resolve


def split_object_types(splits: Sequence[pd.DataFrame], df: pd.DataFrame) -> set[str]:
    """Object types with at least one line in any of ``splits`` (``line_type_resolver``)."""
    resolve = line_type_resolver(df)
    found: set[str] = set()
    for frame in splits:
        for image_path in frame["image_path"]:
            object_type = resolve(str(image_path))
            if object_type is not None:
                found.add(object_type)
    return found


def new_object_types(df: pd.DataFrame, splits: Sequence[pd.DataFrame]) -> list[str]:
    """Types with images in ``df`` and no line in any of ``splits`` (ADR-022, decision 1).

    In the order of ``KNOWN_OBJECT_TYPES`` (any other type after them, sorted).
    """
    seen = split_object_types(splits, df)
    present = {str(t) for t in df["object_type"]}
    ordered = [t for t in KNOWN_OBJECT_TYPES if t in present] + sorted(
        present - set(KNOWN_OBJECT_TYPES)
    )
    return [t for t in ordered if t not in seen]


def type_decision_problems(
    df: pd.DataFrame,
    splits: Sequence[pd.DataFrame],
    extend_test_types: Sequence[str] = (),
    defer_types: Sequence[str] = (),
) -> list[str]:
    """Problems of ``--extend-test-types`` / ``--defer-types`` (SPEC-016 section 4.7), one per line.

    ``splits`` are every earlier split version (empty for ``split_v1``). Every value must be in
    ``KNOWN_OBJECT_TYPES`` (also for ``split_v1``). With earlier versions: each new type must be
    in exactly one of the two lists (``new object type without decision: <type>``); a listed type
    that is not new is refused (``object type is not new: <type>``); an extended type needs at
    least 3 non-external items (``too few items to extend the test: <type>``). Without earlier
    versions the lists are not used. Empty list = no problem.
    """
    problems: list[str] = []
    extend, defer = list(extend_test_types), list(defer_types)
    for value in dict.fromkeys(extend + defer):
        if value not in KNOWN_OBJECT_TYPES:
            problems.append(UNKNOWN_TYPE + value)
    if problems or not splits:
        return problems
    new = new_object_types(df, splits)
    for object_type in dict.fromkeys(extend + defer):
        if object_type in extend and object_type in defer:
            problems.append(TYPE_IN_BOTH_LISTS + object_type)
        elif object_type not in new:
            problems.append(TYPE_NOT_NEW + object_type)
    problems += [NEW_TYPE_WITHOUT_DECISION + t for t in new if t not in extend and t not in defer]
    for object_type in dict.fromkeys(extend):
        if object_type in new and object_type not in defer:
            items = {
                str(i)
                for i, t in zip(df["item_id"], df["object_type"], strict=True)
                if t == object_type and not is_external_item(str(i))
            }
            if len(items) < MIN_EXTENSION_ITEMS:
                problems.append(TOO_FEW_TO_EXTEND + object_type)
    return problems


def item_history(splits: Sequence[pd.DataFrame], df: pd.DataFrame) -> dict[str, str]:
    """``item_id -> split`` over every split version in ``splits`` (SPEC-011 §4.4).

    Each frame is in the ``load_split`` format; the ``item_id`` of each ``image_path`` comes from
    ``item_id_resolver(df)``. No file is read and no hash is checked here.

    Raises:
        SplitIntegrityError: an item has images in two or more splits, over all rows of all
            frames (inside one frame too). The message has the ``item_id`` and, for each split,
            the files it came from (``attrs["split_file"]``, or ``#<index in the list>``). The
            conflict is never resolved here. Also when an external item (``is_external_item``)
            has an image in ``val`` or ``test`` in any version (SPEC-035 section 4.4).
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
    outside = [
        f"external item {item_id} is in {split} in {', '.join(seen[item_id][split])}"
        for item_id in sorted(seen)
        if is_external_item(item_id)
        for split in sorted(seen[item_id])
        if split != "train"
    ]
    if outside:
        raise SplitIntegrityError(
            "external images only go to train (ADR-020): " + " | ".join(outside)
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


def _check_max_external_fraction(value: float) -> Fraction:
    """``Fraction(str(value))``; ``ValueError`` outside ``0 < value <= 1``."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"max_external_fraction must be a number in (0, 1], got {value!r}")
    if not 0 < value <= 1:
        raise ValueError(f"max_external_fraction must be in (0, 1], got {value!r}")
    return Fraction(str(value))


def _check_external_history(
    previous_splits: Mapping[str, set[str]], history: Mapping[str, str]
) -> None:
    """An external item in ``val``/``test`` in ``previous`` or ``history`` breaks ADR-020."""
    problems = [
        f"external item {item_id} is in {split} in the previous split"
        for item_id in sorted(previous_splits)
        if is_external_item(item_id)
        for split in sorted(previous_splits[item_id])
        if split != "train"
    ]
    problems += [
        f"external item {item_id} is in {split} in the split history"
        for item_id, split in sorted(history.items())
        if is_external_item(item_id) and split != "train"
    ]
    if problems:
        raise SplitIntegrityError(
            "external images only go to train (ADR-020): " + " | ".join(problems)
        )


def make_split(
    df: pd.DataFrame,
    seed: int = 42,
    ratios: tuple[float, float, float] = DEFAULT_RATIOS,
    previous: pd.DataFrame | None = None,
    excluded: frozenset[str] = frozenset(),
    history: Mapping[str, str] | None = None,
    max_external_fraction: float = DEFAULT_MAX_EXTERNAL_FRACTION,
    extend_test_types: Sequence[str] = (),
    defer_types: Sequence[str] = (),
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

    External items (``is_external_item``, SPEC-035 section 4.4) always go to train, in every
    version. They are left out of the strata, the permutation and the rounding: the other items
    are allocated as if they did not exist, and ``small_stratum`` counts only the other items.
    After the allocation, the fraction of external images among the train images must not be
    above ``max_external_fraction`` (exact comparison with ``Fraction``).

    ADR-022 (SPEC-016 section 4.7), only with ``previous`` (ignored for ``split_v1``): the images
    of the ``defer_types`` leave ``df`` before anything else; the non-external items of each of
    the ``extend_test_types`` are split 70/15/15 by the procedure of ``split_v1`` (strata
    ``(type, dominant grade)``, a fresh ``numpy`` generator from ``seed`` for each type), with
    ``small_stratum`` warnings carrying ``"scope": "test_extension"``. The checks of the two
    lists over every earlier version are made by ``type_decision_problems`` (the CLI); here an
    extended type with an item already in ``previous`` or ``history``, or with fewer than 3
    non-external items, is a ``SplitError``.

    Raises:
        ValueError: ``max_external_fraction`` outside ``(0, 1]``.
        SplitError: invalid ratios, previous split or ``history`` value, ``history`` without
            ``previous``, a frozen test image is missing, or the external fraction in train is
            above ``max_external_fraction``.
        SplitIntegrityError: an item would end up in two splits, its images in ``previous`` are
            in two splits, ``history`` disagrees with ``previous`` for it, or an external item
            is in ``val``/``test`` in ``previous`` or in ``history``.
    """
    ceiling = _check_max_external_fraction(max_external_fraction)
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
    extended: set[str] = set()
    if previous is not None:
        listed = set(extend_test_types) | set(defer_types)
        unknown_types = sorted(listed - set(KNOWN_OBJECT_TYPES))
        if unknown_types:
            raise SplitError(f"unknown object types: {', '.join(unknown_types)}")
        both = sorted(set(extend_test_types) & set(defer_types))
        if both:
            raise SplitError(f"object types both extended and deferred: {', '.join(both)}")
        extended = set(extend_test_types)
        df = df[~df["object_type"].isin(list(defer_types))]
    df = df[~df["image_path"].isin(list(excluded))]
    external = df["item_id"].map(lambda i: is_external_item(str(i))).astype(bool)
    strata = item_strata(df[~external])  # external items stay out of the strata
    images_by_item: dict[str, list[str]] = defaultdict(list)
    types_by_item: dict[str, str] = {}
    for item_id, image_path, object_type in zip(
        df["item_id"], df["image_path"], df["object_type"], strict=True
    ):
        images_by_item[item_id].append(image_path)
        types_by_item[item_id] = str(object_type)

    warnings: list[dict[str, Any]] = []
    if previous is None:
        groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        for item_id, stratum in strata.items():
            groups[stratum].append(item_id)
        assignment, allocation_warnings = _allocate(groups, rng, r_val, r_test)
        warnings.extend(allocation_warnings)
        prev: dict[str, str] = {}
        for item_id in images_by_item:
            if is_external_item(item_id):
                assignment[item_id] = "train"
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
        _check_external_history(previous_splits, history)
        assignment = {}
        new_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        extension_groups: dict[str, dict[tuple[str, str], list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
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
            item_type = types_by_item[item_id]
            if item_type in extended and (earlier is not None or old):
                raise SplitError(f"object type is not new: {item_type} (item {item_id})")
            if is_external_item(item_id):
                assignment[item_id] = "train"  # ADR-020: always train, outside the strata
            elif earlier is not None:
                assignment[item_id] = earlier
            elif old:
                assignment[item_id] = old[0]
            elif item_type in extended:
                extension_groups[item_type][strata[item_id]].append(item_id)
            else:
                new_groups[strata[item_id]].append(item_id)
        new_assignment, allocation_warnings = _allocate(
            new_groups, rng, r_val / (r_train + r_val), None
        )
        assignment.update(new_assignment)
        warnings.extend(allocation_warnings)
        for object_type in sorted(extended):
            groups_of_type = extension_groups.get(object_type, {})
            n_items = sum(len(ids) for ids in groups_of_type.values())
            if n_items < MIN_EXTENSION_ITEMS:
                raise SplitError(TOO_FEW_TO_EXTEND + object_type)
            # ADR-022: the procedure of split_v1 (test included), its own generator per type.
            extension, extension_warnings = _allocate(
                dict(groups_of_type), np.random.default_rng(seed), r_val, r_test
            )
            assignment.update(extension)
            for warning in extension_warnings:
                warning["scope"] = "test_extension"
            warnings.extend(extension_warnings)

    splits = [assignment[item_id] for item_id in df["item_id"]]
    check_item_integrity(df, splits)
    for image_path, split in zip(df["image_path"], splits, strict=True):
        if image_path in prev and prev[image_path] != split:
            raise SplitIntegrityError(f"{image_path} would move from {prev[image_path]} to {split}")
    n_train = sum(1 for split in splits if split == "train")
    n_external_train = sum(
        1 for split, is_ext in zip(splits, external, strict=True) if is_ext and split == "train"
    )
    if n_train and Fraction(n_external_train, n_train) > ceiling:
        raise SplitError(
            f"external fraction in train {n_external_train}/{n_train} above {max_external_fraction}"
        )
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


def deferred_type_counts(df: pd.DataFrame, split_df: pd.DataFrame) -> dict[str, int]:
    """``object_type -> n images`` of ``df`` whose type has no line in ``split_df``.

    These are the images of a deferred (or not yet decided) type (SPEC-016 section 4.7, ADR-022):
    the readers of the split ignore them. In the order of ``KNOWN_OBJECT_TYPES``.
    """
    present = split_object_types([split_df], df)
    counts = Counter(str(t) for t in df["object_type"] if str(t) not in present)
    order = [t for t in KNOWN_OBJECT_TYPES if t in counts] + sorted(
        set(counts) - set(KNOWN_OBJECT_TYPES)
    )
    return {t: counts[t] for t in order}


def assign_splits(df: pd.DataFrame, split_df: pd.DataFrame) -> pd.Series:
    """Split of each row of ``df`` (same index).

    The rows of a type without any line in ``split_df`` (a deferred type, SPEC-016 section 4.7)
    get ``None`` and are left out of the outdated check; one ``deferred type images: <type>: <n>``
    warning is logged per type. For the types present in the split the check is unchanged.

    Raises:
        SplitError: an image of ``df`` has no split (``split outdated: run qc_ml.split``).
    """
    mapping = dict(zip(split_df["image_path"], split_df["split"], strict=True))
    deferred: dict[str, int] = {}
    if any(p not in mapping for p in df["image_path"]):  # every image in the split: none deferred
        deferred = deferred_type_counts(df, split_df)
    for object_type, n in deferred.items():
        logger.warning("%s%s: %d", DEFERRED_LOG, object_type, n)
    in_scope = [str(t) not in deferred for t in df["object_type"]]
    missing = [
        p for p, keep in zip(df["image_path"], in_scope, strict=True) if keep and p not in mapping
    ]
    if missing:
        shown = ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else "")
        raise SplitError(f"{OUTDATED_MESSAGE} ({len(missing)} images without split: {shown})")
    return pd.Series(
        [mapping[p] if keep else None for p, keep in zip(df["image_path"], in_scope, strict=True)],
        index=df.index,
        dtype=object,
    )


def rows_for(df: pd.DataFrame, split_df: pd.DataFrame, which: SplitName) -> pd.DataFrame:
    """The rows of ``df`` in split ``which``: the only way to get the rows of a split (R-11).

    The rows of a deferred type (no line in ``split_df``, SPEC-016 section 4.7) are never
    returned (``assign_splits``).

    Raises:
        ValueError: ``which`` is not ``train``, ``val`` or ``test``.
        SplitError: an image of ``df`` has no split (``split outdated: run qc_ml.split``).
        SplitIntegrityError: an item of ``df`` has images in two splits, or an external image
            (``is_external_item``) would be returned for ``val`` or ``test`` (SPEC-035 4.4): the
            thresholds, the early stopping and the evaluation never see an external image.
    """
    if which not in SPLIT_NAMES:
        raise ValueError(f"which must be one of {', '.join(SPLIT_NAMES)}, got {which!r}")
    splits = assign_splits(df, split_df)
    check_item_integrity(df, splits)
    rows = df[splits == which].reset_index(drop=True)
    if which != "train":
        external = sorted({str(i) for i in rows["item_id"] if is_external_item(str(i))})
        if external:
            raise SplitIntegrityError(f"external image in {which}: {', '.join(external)}")
    return rows


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
    external = dict.fromkeys(SPLIT_NAMES, 0)
    for image_path, split in zip(frame["image_path"], frame["split"], strict=True):
        item_id = items[image_path]
        item_sets[split].add(item_id)
        external[split] += int(is_external_item(str(item_id)))
    return {
        "images": images,
        "items": {s: len(item_sets[s]) for s in SPLIT_NAMES},
        "n_external_images": external,
    }


def external_fraction_train(counts: Mapping[str, Mapping[str, int]]) -> float | None:
    """``n_external_images.train / images.train`` of ``_counts``; ``None`` without train."""
    n_train = counts["images"]["train"]
    return counts["n_external_images"]["train"] / n_train if n_train else None


def write_split(
    splits_dir: Path,
    version: int,
    result: SplitResult,
    df: pd.DataFrame,
    *,
    seed: int,
    ratios: Sequence[float],
    max_external_fraction: float = DEFAULT_MAX_EXTERNAL_FRACTION,
    test_extended_types: Sequence[str] = (),
    deferred_types: Sequence[str] = (),
) -> Path:
    """Write ``split_v<N>.json``, ``.sha256`` and, last, ``.csv``; return the CSV path.

    The JSON has ``max_external_fraction`` (the ceiling used), ``external_fraction_train``
    (``null`` without train images) and ``counts.n_external_images`` by split (SPEC-035 4.4),
    and ``test_extended_types`` and ``deferred_types`` (lists, empty when not used; SPEC-016).
    """
    splits_dir.mkdir(parents=True, exist_ok=True)
    csv_name = f"split_v{version}.csv"
    csv_path = splits_dir / csv_name
    content = split_csv_bytes(result.frame)
    digest = hashlib.sha256(content).hexdigest()
    counts = _counts(result.frame, df)
    meta = {
        "split_file": csv_name,
        "seed": seed,
        "ratios": [float(r) for r in ratios],
        "parent": None if version == 1 else f"split_v{version - 1}",
        "manifest_sha256": df.attrs.get("manifest_sha256"),
        "max_external_fraction": float(max_external_fraction),
        "external_fraction_train": external_fraction_train(counts),
        "counts": counts,
        "warnings": result.warnings,
        "test_extended_types": list(test_extended_types),
        "deferred_types": list(deferred_types),
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


def recorded_deferred_types(csv_path: Path) -> list[str] | None:
    """``deferred_types`` of the ``split_v<N>.json`` next to ``csv_path``.

    ``[]`` for a JSON written before SPEC-016 (no key); ``None`` when the JSON is missing,
    unreadable or the key is not a list of strings.
    """
    try:
        meta = json.loads(csv_path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    value = meta.get("deferred_types", [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    return value


def _type_list(text: str) -> list[str]:
    """``argparse`` type of ``--extend-test-types``/``--defer-types``: ``t1,t2`` -> a list.

    Blank items are dropped and repetitions kept once; the values are checked by
    ``type_decision_problems`` (exit 2 for a value outside ``KNOWN_OBJECT_TYPES``).
    """
    return list(dict.fromkeys(v.strip() for v in text.split(",") if v.strip()))


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------


def _fraction_argument(text: str) -> float:
    """A decimal number in ``(0, 1]`` (``argparse`` type of ``--max-external-fraction``).

    The ceiling used is ``float(Decimal(text))``, checked again after the conversion (SPEC-037
    section 4.2): a text that underflows to ``0.0`` (e.g. ``1e-400``) is refused like any other
    value outside ``(0, 1]``. A text with more precision than a ``float`` is used rounded (e.g.
    ``0.30000000000000000001`` -> ``0.3``), and that rounded value goes to ``split_v<N>.json``.
    """
    try:
        value = Decimal(text.strip())
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"not a decimal number: {text!r}") from None
    if not value.is_finite() or not 0 < value <= 1:
        raise argparse.ArgumentTypeError(f"must be in (0, 1], got {text!r}")
    ceiling = float(value)
    if not 0 < ceiling <= 1:
        raise argparse.ArgumentTypeError(f"must be in (0, 1] as a float, got {text!r}")
    return ceiling


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qc_ml.split", description="Create or extend the item-grouped split."
    )
    parser.add_argument("--dataset-dir", type=Path, default=Path("ml/data"))
    parser.add_argument("--splits-dir", type=Path, default=Path("ml/splits"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--external-sources",
        type=Path,
        default=None,
        help="registry of the external sources (default: ml/external_sources.csv)",
    )
    parser.add_argument(
        "--max-external-fraction",
        type=_fraction_argument,
        default=DEFAULT_MAX_EXTERNAL_FRACTION,
        help="ceiling of the fraction of external images in train, in (0, 1] (default 0.30)",
    )
    parser.add_argument(
        "--extend-test-types",
        type=_type_list,
        default=[],
        help="new object types whose items get a test set once (ADR-022), comma-separated",
    )
    parser.add_argument(
        "--defer-types",
        type=_type_list,
        default=[],
        help="new object types left out of this split version (ADR-022), comma-separated",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; 0 when a split was written or nothing changed, 2 on any error.

    Steps of SPEC-011 §4.4: manifest and exclusions; list ``split_v<N>.csv``; require versions
    ``1..M`` without gaps; read all of them with ``load_split``; ``previous`` = version ``M`` and
    ``history = item_history(all versions)``; ``make_split``; write ``split_v{M+1}`` only if it
    changed. Nothing is written on any error.

    SPEC-016 section 4.7 (ADR-022): before ``make_split``, ``type_decision_problems`` over every
    version; each problem is printed alone on its own stderr line (e.g. ``new object type
    without decision: pliers``) and the exit is 2. A version whose CSV equals the previous one is
    still written when its ``deferred_types`` differ from the ones recorded in the previous
    ``split_v<M>.json`` (the decision itself is part of the split history).
    """
    configure_logging()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR

    try:
        df = load_manifest(args.dataset_dir, external_sources=args.external_sources)
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
    frames: list[pd.DataFrame] = []
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

    # SPEC-016 section 4.7: every new type needs a decision (ADR-022).
    problems = type_decision_problems(df, frames, args.extend_test_types, args.defer_types)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return EXIT_ERROR
    # Recorded in the order of KNOWN_OBJECT_TYPES (every value is known at this point).
    extend = [t for t in KNOWN_OBJECT_TYPES if versions and t in args.extend_test_types]
    defer = [t for t in KNOWN_OBJECT_TYPES if versions and t in args.defer_types]
    if not versions and (args.extend_test_types or args.defer_types):
        logger.warning(
            "--extend-test-types and --defer-types are not used for split_v1: every type "
            "present is split normally"
        )

    try:
        result = make_split(
            df,
            seed=args.seed,
            previous=previous,
            excluded=excluded,
            history=history,
            max_external_fraction=args.max_external_fraction,
            extend_test_types=extend,
            defer_types=defer,
        )
    except SplitError as exc:
        print(f"split error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if (
        previous is not None
        and _same_split(result.frame, previous)
        and recorded_deferred_types(args.splits_dir / f"split_v{versions[-1]}.csv") == defer
    ):
        print(f"split unchanged: split_v{versions[-1]}")
        return EXIT_OK
    version = versions[-1] + 1 if versions else 1
    path = write_split(
        args.splits_dir,
        version,
        result,
        df,
        seed=args.seed,
        ratios=DEFAULT_RATIOS,
        max_external_fraction=args.max_external_fraction,
        test_extended_types=extend,
        deferred_types=defer,
    )
    counts = _counts(result.frame, df)
    print(
        f"split written: {path.name} (images {counts['images']}, items {counts['items']}, "
        f"{len(result.warnings)} warnings)"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
