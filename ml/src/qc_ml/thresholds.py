"""Decision thresholds chosen on the **validation** split only (SPEC-012 section 4.6, R-11).

``choose_thresholds`` refuses any ``Predictions`` that is not from ``val``
(``SplitIntegrityError``). Every threshold is a value of a fixed grid with 2 decimals; the rates
are compared with exact integer arithmetic, never with rounded floats.

SPEC-016 section 4.8: ``FU(t)`` counts the validation images of every type except ``other``
(screw, nut and the tools of the model). The validation images of the tools never enter the two
other thresholds, which keep the rule of SPEC-012 on the remaining images: ``unusable_threshold``
on the ``screw``/``nut`` images and ``grade_review_threshold`` on the ``needs_review`` fraction of
the ``screw``, ``nut`` and ``other`` images (the MVP data give the values of SPEC-012).

No torch, no sklearn here (CA-27).

CLI::

    python -m qc_ml.thresholds --config ml/configs/partqc-mnv3-v1.json
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

from qc_ml import split
from qc_ml.artifacts import DECISION_FILE, THRESHOLDS_REPORT_FILE, as_labels, write_json
from qc_ml.config import TrainConfig, load_config
from qc_ml.data import GRADED_OBJECT_TYPES, ModelLabels, configure_logging, load_manifest
from qc_ml.decision import Thresholds, apply_decision, decided_grade_idx, write_decision
from qc_ml.errors import EvaluationError, SplitIntegrityError
from qc_ml.predict import OnnxModel, Predictions
from qc_ml.steps import EXIT_ERROR, EXIT_OK, report_step_error

logger = logging.getLogger(__name__)

# Grids in hundredths (k / 100 is the double nearest to the 2-decimal value).
TYPE_GRID: tuple[int, ...] = tuple(range(50, 86))  # 0.50 .. 0.85 (skill ml-pipeline §6)
UNUSABLE_GRID: tuple[int, ...] = tuple(range(5, 96))  # 0.05 .. 0.95
REVIEW_GRID: tuple[int, ...] = tuple(range(30, 96))  # 0.30 .. 0.95
DEFAULT_TYPE = 50
DEFAULT_UNUSABLE = 50
DEFAULT_REVIEW = 60

NOTE_TYPE_NOT_MET = "type_target_not_met"
NOTE_NO_SCREW_NUT = "no_screw_nut_in_val"
NOTE_UNUSABLE_NOT_MET = "unusable_target_not_met"
NOTE_NO_UNUSABLE = "no_unusable_in_val"
NOTE_REVIEW_ADJUSTED = "review_adjusted"


def hundredths(k: int) -> float:
    return k / 100


@dataclass(frozen=True)
class ThresholdResult:
    """``decision`` is what goes to ``decision.json``; ``report`` the curves and the notes."""

    decision: Thresholds
    report: dict[str, Any]


def _rate(count: int, total: int) -> float | None:
    return count / total if total else None


def _screw_nut_mask(val: Predictions, labels: ModelLabels) -> np.ndarray:
    """``True`` for the validation images whose true type is ``screw`` or ``nut``."""
    types = list(labels.object_types)
    indices = [types.index(t) for t in GRADED_OBJECT_TYPES if t in types]
    return np.isin(val.true_type_idx, indices)


def _mvp_mask(val: Predictions, labels: ModelLabels) -> np.ndarray:
    """``True`` for the validation images whose true type is ``screw``, ``nut`` or ``other``."""
    types = list(labels.object_types)
    indices = [types.index(t) for t in (*GRADED_OBJECT_TYPES, "other") if t in types]
    return np.isin(val.true_type_idx, indices)


def _choose_type(val: Predictions, labels: ModelLabels) -> tuple[int, dict[str, Any], list[str]]:
    other = labels.object_types.index("other")
    known = val.true_type_idx != other  # SPEC-016 4.8: every type except other
    n = int(known.sum())
    type_idx = np.argmax(val.type_probs, axis=1) if len(val) else np.zeros(0, dtype=np.int64)
    type_conf = val.type_probs.max(axis=1) if len(val) else np.zeros(0)
    curve = []
    passing: list[int] = []
    for k in TYPE_GRID:
        unknown = (type_idx == other) | (type_conf < hundredths(k))
        count = int((unknown & known).sum())
        curve.append(
            {"threshold": hundredths(k), "n_unknown": count, "false_unknown_rate": _rate(count, n)}
        )
        if n and 20 * count <= n:  # count / n <= 0.05
            passing.append(k)
    notes: list[str] = []
    if n == 0:
        chosen = DEFAULT_TYPE
        notes.append(NOTE_NO_SCREW_NUT)
    elif passing:
        chosen = max(passing)
    else:
        chosen = DEFAULT_TYPE
        notes.append(NOTE_TYPE_NOT_MET)
    point = next(p for p in curve if p["threshold"] == hundredths(chosen))
    section = {
        "value": hundredths(chosen),
        "rule": "largest t in [0.50, 0.85] with false_unknown_rate <= 0.05 on the val images of "
        "every type except other",
        "n_images": n,
        "false_unknown_rate": point["false_unknown_rate"],
        "curve": curve,
    }
    return chosen, section, notes


def _choose_unusable(
    val: Predictions, labels: ModelLabels
) -> tuple[int, dict[str, Any], list[str]]:
    unusable = labels.grades.index("unusable")
    graded = _screw_nut_mask(val, labels) & (val.true_grade_idx >= 0)
    truth = val.true_grade_idx[graded]
    probs = val.grade_probs[graded]
    is_unusable = truth == unusable
    n = int(is_unusable.sum())
    curve = []
    passing: list[int] = []
    best_hits = -1
    best_k = DEFAULT_UNUSABLE
    for k in UNUSABLE_GRID:
        predicted = decided_grade_idx(probs, hundredths(k)) == unusable
        hits = int((predicted & is_unusable).sum())
        n_predicted = int(predicted.sum())
        curve.append(
            {
                "threshold": hundredths(k),
                "unusable_recall": _rate(hits, n),
                "unusable_precision": _rate(hits, n_predicted),
            }
        )
        if n and 10 * hits >= 9 * n:  # recall >= 0.90
            passing.append(k)
        if hits >= best_hits:  # ascending grid: a tie keeps the larger threshold
            best_hits, best_k = hits, k
    notes: list[str] = []
    if n == 0:
        chosen = DEFAULT_UNUSABLE
        notes.append(NOTE_NO_UNUSABLE)
    elif passing:
        chosen = max(passing)
    else:
        chosen = best_k
        notes.append(NOTE_UNUSABLE_NOT_MET)
    point = next(p for p in curve if p["threshold"] == hundredths(chosen))
    section = {
        "value": hundredths(chosen),
        "rule": "largest u with unusable_recall >= 0.90 on val screw/nut images with grade",
        "n_images": int(graded.sum()),
        "n_unusable": n,
        "unusable_recall": point["unusable_recall"],
        "unusable_precision": point["unusable_precision"],
        "curve": curve,
    }
    return chosen, section, notes


def _review_count(
    val: Predictions, labels: ModelLabels, scope: np.ndarray, t: int, u: int, r: int
) -> int:
    thresholds = Thresholds(hundredths(t), hundredths(u), hundredths(r))
    decisions = apply_decision(val.type_probs, val.grade_probs, labels, thresholds)
    return int((decisions.needs_review & scope).sum())


def _choose_review(
    val: Predictions, labels: ModelLabels, t: int, u: int
) -> tuple[int, dict[str, Any], list[str]]:
    scope = _mvp_mask(val, labels)  # SPEC-016 4.8: screw, nut and other (no tool)
    n = int(scope.sum())
    count_default = _review_count(val, labels, scope, t, u, DEFAULT_REVIEW)
    section: dict[str, Any] = {
        "rule": "0.60 if needs_review is in [5%, 15%] of the val screw/nut/other images; else the "
        "r closest to 10%",
        "n_images": n,
        "needs_review_rate_at_default": _rate(count_default, n),
    }
    if 20 * count_default >= n and 20 * count_default <= 3 * n:  # 5% <= rate <= 15%
        section.update(value=hundredths(DEFAULT_REVIEW), needs_review_rate=_rate(count_default, n))
        section["curve"] = []
        return DEFAULT_REVIEW, section, []
    curve = []
    best: tuple[int, int, int] | None = None
    chosen = DEFAULT_REVIEW
    for k in REVIEW_GRID:
        count = _review_count(val, labels, scope, t, u, k)
        curve.append({"threshold": hundredths(k), "needs_review_rate": _rate(count, n)})
        # |count/n - 0.10| ~ |10 count - n|; tie -> closest to 0.60; then the larger r (more
        # review is the safer side).
        key = (abs(10 * count - n), abs(k - DEFAULT_REVIEW), -k)
        if best is None or key < best:
            best, chosen = key, k
    point = next(p for p in curve if p["threshold"] == hundredths(chosen))
    section.update(
        value=hundredths(chosen), needs_review_rate=point["needs_review_rate"], curve=curve
    )
    return chosen, section, [NOTE_REVIEW_ADJUSTED]


def choose_thresholds(
    val: Predictions, labels: ModelLabels | Mapping[str, Any] | None = None
) -> ThresholdResult:
    """Choose ``type_threshold``, ``unusable_threshold`` and ``grade_review_threshold``.

    Raises:
        SplitIntegrityError: ``val.split`` is not ``"val"`` (R-11: never on train or test).
        EvaluationError: the validation split has no image.
    """
    if val.split != "val":
        raise SplitIntegrityError(
            f"thresholds are chosen on the validation split only (R-11), got {val.split!r}"
        )
    if len(val) == 0:
        raise EvaluationError("the validation split has no image: cannot choose thresholds")
    labels = as_labels(labels)
    t, type_section, notes = _choose_type(val, labels)
    u, unusable_section, unusable_notes = _choose_unusable(val, labels)
    r, review_section, review_notes = _choose_review(val, labels, t, u)
    notes += unusable_notes + review_notes
    decision = Thresholds(hundredths(t), hundredths(u), hundredths(r))
    report = {
        "n_val_images": len(val),
        "decision": decision.to_dict(),
        "notes": notes,
        "type_threshold": type_section,
        "unusable_threshold": unusable_section,
        "grade_review_threshold": review_section,
    }
    return ThresholdResult(decision=decision, report=report)


def run(config: TrainConfig) -> ThresholdResult:
    """Predict the validation split with the exported model and write the thresholds.

    Writes ``<models_root>/<v>/decision.json`` (exactly the 3 keys) and
    ``<reports_root>/<v>/thresholds_report.json``. Only ``rows_for(..., "val")`` is requested.
    """
    model = OnnxModel(config.model_dir)
    df = load_manifest(config.dataset_dir, external_sources=config.external_sources)
    split_df = split.load_split(config.split_file)
    val_rows = split.rows_for(df, split_df, "val")
    predictions = model.predict(val_rows, config.dataset_dir, "val")
    result = choose_thresholds(predictions, model.labels)
    report = {
        "model_version": config.model_version,
        "model_sha256": model.sha256,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "split_file": split_df.attrs.get("split_file"),
        "split_sha256": split_df.attrs.get("split_sha256"),
        "manifest_sha256": df.attrs.get("manifest_sha256"),
        **result.report,
    }
    write_json(config.reports_dir / THRESHOLDS_REPORT_FILE, report)
    write_decision(config.model_dir / DECISION_FILE, result.decision)
    logger.info(
        "thresholds written: %s %s (notes: %s)",
        config.model_dir / DECISION_FILE,
        result.decision.to_dict(),
        ", ".join(result.report["notes"]) or "none",
    )
    return ThresholdResult(decision=result.decision, report=report)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qc_ml.thresholds",
        description="Choose the decision thresholds on the validation split (R-11).",
    )
    parser.add_argument("--config", required=True, help="ml/configs/<model_version>.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; 0 when ``decision.json`` was written, 2 on any error."""
    configure_logging()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR
    try:
        run(load_config(args.config))
    except Exception as exc:  # noqa: BLE001 - every failure is reported and exits with 2
        return report_step_error("thresholds", exc)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
