"""Inter-rater agreement on the grade (SPEC-011 section 4.3, ADR-014).

The first rating is the **original** grade of the manifest (overrides do not apply: they result
from the disagreement); the second comes from ``labels_second.csv`` (``image_path,grade,labeler``).
Images listed in ``exclusions.csv`` (next to the manifest) leave both files before the pairs are
formed.

No torch here (SPEC-011 section 4.5).

CLI::

    python -m qc_ml.agreement --first ml/data/manifest.csv --second ml/data/labels_second.csv \
        --out ml/reports/agreement.json
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import math
import sys
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from qc_ml.data import (
    GRADED_OBJECT_TYPES,
    GRADES,
    configure_logging,
    load_exclusions,
    parse_csv,
    print_problems,
    write_json,
)
from qc_ml.errors import ManifestError

FIRST_COLUMNS: tuple[str, ...] = ("image_path", "object_type", "grade", "labeler")
SECOND_COLUMNS: tuple[str, ...] = ("image_path", "grade", "labeler")
logger = logging.getLogger(__name__)

TARGETS: dict[str, float] = {"minimum": 0.6, "desired": 0.8}
GRADE_LABELS: list[int] = list(range(len(GRADES)))

EXIT_OK = 0
EXIT_ERROR = 2


class AgreementError(ValueError):
    """The two label files cannot be compared; ``problems`` lists every reason."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


@dataclass(frozen=True)
class _Labels:
    rows: dict[str, dict[str, str]]  # image_path -> row
    sha256: str


def _read(path: Path, required: Sequence[str]) -> tuple[_Labels, list[str]]:
    data = path.read_bytes()
    table = parse_csv(data, path.name, required)
    problems = [str(p) for p in table.problems]
    rows: dict[str, dict[str, str]] = {}
    for line, row in table.rows:
        if row["image_path"] in rows:
            problems.append(f"{path.name}:{line}: duplicate image_path {row['image_path']}")
            continue
        rows[row["image_path"]] = row
    return _Labels(rows=rows, sha256=hashlib.sha256(data).hexdigest()), problems


def _join_labelers(values: list[str]) -> str | None:
    unique = sorted({v for v in values if v})
    return ",".join(unique) if unique else None


def compute_agreement(
    first_path: Path, second_path: Path, excluded: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Agreement JSON of SPEC-011 section 4.3 (``generated_at`` included).

    Raises:
        AgreementError: unreadable files, an ``image_path`` of the second file missing from the
            first, an invalid grade or no pair at all.
    """
    first, problems = _read(first_path, FIRST_COLUMNS)
    second, second_problems = _read(second_path, SECOND_COLUMNS)
    problems += second_problems
    if problems:
        raise AgreementError(problems)

    pairs: list[tuple[int, int]] = []
    labelers_first: list[str] = []
    labelers_second: list[str] = []
    n_excluded_pairs = 0
    for image_path, row2 in second.rows.items():
        if image_path in excluded:
            if image_path in first.rows:
                n_excluded_pairs += 1
            continue
        row1 = first.rows.get(image_path)
        if row1 is None:
            problems.append(f"{second_path.name}: {image_path}: not in {first_path.name}")
            continue
        grade1, grade2 = row1["grade"], row2["grade"]
        for name, grade in ((first_path.name, grade1), (second_path.name, grade2)):
            if grade and grade not in GRADES:
                problems.append(f"{name}: {image_path}: invalid grade {grade!r}")
        if row1["object_type"] not in GRADED_OBJECT_TYPES or not grade1 or not grade2:
            continue
        if grade1 not in GRADES or grade2 not in GRADES:
            continue
        pairs.append((GRADES.index(grade1), GRADES.index(grade2)))
        labelers_first.append(row1["labeler"])
        labelers_second.append(row2["labeler"])
    if problems:
        raise AgreementError(problems)
    if not pairs:
        raise AgreementError(["no pairs to compare (n_pairs = 0)"])

    # Imported here, not at module level: scipy (under sklearn) breaks at import time when
    # ``sys.modules["torch"] is None`` (its array-API check reads ``sys.modules["torch"]`` and only
    # handles a missing key), which is how CA-26 simulates a CI without torch. Without torch
    # installed, the key is absent and the import works either way.
    from sklearn.metrics import cohen_kappa_score, confusion_matrix

    a = np.array([p[0] for p in pairs])
    b = np.array([p[1] for p in pairs])
    with warnings.catch_warnings(), np.errstate(divide="ignore", invalid="ignore"):
        warnings.simplefilter("ignore")  # undefined kappa (one class only) is reported as null
        qwk_value = float(cohen_kappa_score(a, b, weights="quadratic", labels=GRADE_LABELS))
    qwk: float | None = qwk_value if math.isfinite(qwk_value) else None
    if qwk is None:
        logger.warning("qwk is undefined (a single grade in both ratings); written as null")
    confusion = confusion_matrix(a, b, labels=GRADE_LABELS)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_pairs": len(pairs),
        "n_excluded_pairs": n_excluded_pairs,
        "qwk": qwk,
        "exact_agreement": float(np.mean(a == b)),
        "off_by_one_agreement": float(np.mean(np.abs(a - b) <= 1)),
        "confusion": confusion.astype(int).tolist(),
        "grades": list(GRADES),
        "labeler_first": _join_labelers(labelers_first),
        "labeler_second": _join_labelers(labelers_second),
        "targets": dict(TARGETS),
        "meets_minimum": qwk is not None and qwk >= TARGETS["minimum"],
        "meets_desired": qwk is not None and qwk >= TARGETS["desired"],
        "first_sha256": first.sha256,
        "second_sha256": second.sha256,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qc_ml.agreement", description="Inter-rater agreement (QWK) on the grade."
    )
    parser.add_argument("--first", type=Path, required=True, help="manifest.csv")
    parser.add_argument("--second", type=Path, required=True, help="labels_second.csv")
    parser.add_argument("--out", type=Path, default=Path("ml/reports/agreement.json"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; 0 when ``agreement.json`` was written, 2 on any problem (nothing written)."""
    configure_logging()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR

    try:
        excluded = load_exclusions(args.first.parent)
        result = compute_agreement(args.first, args.second, excluded)
    except ManifestError as exc:
        print_problems(exc.problems, sys.stderr)
        return EXIT_ERROR
    except AgreementError as exc:
        for problem in exc.problems:
            print(problem, file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"cannot read the label files: {exc}", file=sys.stderr)
        return EXIT_ERROR

    write_json(args.out, result)
    qwk = "n/a" if result["qwk"] is None else f"{result['qwk']:.4f}"
    print(f"agreement written: {args.out} (n_pairs={result['n_pairs']}, qwk={qwk})")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
