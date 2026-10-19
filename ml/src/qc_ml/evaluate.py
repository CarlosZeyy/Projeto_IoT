"""Final evaluation on the **test** split (SPEC-012 section 4.7, R-11).

This is the only module that asks ``split.rows_for(..., "test")``, once per run, and only after
``decision.json`` exists (the thresholds come from the validation split). Every metric is written
as measured: an undefined metric is ``null``, never omitted nor rounded. Small test sets are
flagged in ``warnings`` and the main grade metrics carry a 95% bootstrap interval that resamples
physical items (``item_id``).

No torch, no sklearn here (CA-27): the kappa and the confusion matrices are computed with numpy.

CLI::

    python -m qc_ml.evaluate --config ml/configs/partqc-mnv3-v1.json \
        [--latency-machine "notebook-borda"] [--latency-only]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qc_contracts import is_defective
from qc_ml import split
from qc_ml.artifacts import (
    DECISION_FILE,
    GRADE_CONFUSION_PNG,
    METRICS_FILE,
    TYPE_CONFUSION_PNG,
    labels_to_dict,
    write_json,
)
from qc_ml.config import TrainConfig, load_config
from qc_ml.data import GRADED_OBJECT_TYPES, ModelLabels, configure_logging, load_manifest
from qc_ml.decision import Thresholds, apply_decision, decided_grade_idx, load_decision
from qc_ml.errors import EvaluationError
from qc_ml.plots import confusion_png, grade_label_pt, type_label_pt
from qc_ml.predict import OnnxModel, Predictions
from qc_ml.steps import EXIT_ERROR, EXIT_OK, report_step_error

logger = logging.getLogger(__name__)

METRIC_KEYS: tuple[str, ...] = (
    "model_version",
    "model_sha256",
    "evaluated_at",
    "split_file",
    "split_sha256",
    "manifest_sha256",
    "labels",
    "decision",
    "type_accuracy",
    "type_confusion",
    "grade_qwk",
    "grade_mae",
    "grade_off_by_one_accuracy",
    "grade_confusion",
    "grade_per_class",
    "unusable_recall",
    "unusable_precision",
    "defective_recall",
    "defective_precision",
    "unknown_rate_on_other",
    "false_unknown_rate",
    "needs_review_rate",
    "latency_ms_p50",
    "latency_ms_p95",
    "latency_machine",
    "latency_runs",
    "counts",
    "grade_qwk_ci95",
    "unusable_recall_ci95",
    "defective_recall_ci95",
    "n_items_test_by_grade",
    "warnings",
)
LATENCY_KEYS: tuple[str, ...] = (
    "latency_ms_p50",
    "latency_ms_p95",
    "latency_machine",
    "latency_runs",
)

N_GRADES = 5
UNUSABLE_INDEX = 4
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 20261012
MIN_TEST_ITEMS_PER_GRADE = 2
LATENCY_WARMUP = 10
LATENCY_RUNS = 100
NO_DECISION_MESSAGE = "decision.json not found: run qc_ml.thresholds first"
NO_METRICS_MESSAGE = "metrics.json not found: run qc_ml.evaluate without --latency-only first"
GRADES: tuple[str, ...] = ("perfect", "good", "fair", "poor", "unusable")
DEFECTIVE_BY_INDEX = np.array([is_defective(g) for g in GRADES], dtype=bool)


# ---------------------------------------------------------------------------------------------
# Metrics (pure functions)
# ---------------------------------------------------------------------------------------------


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def confusion(true: Any, pred: Any, n_classes: int) -> np.ndarray:
    """``n x n`` counts, rows = true class, columns = predicted class."""
    matrix = np.zeros((n_classes, n_classes), dtype=np.int64)
    np.add.at(matrix, (np.asarray(true, dtype=np.int64), np.asarray(pred, dtype=np.int64)), 1)
    return matrix


def quadratic_weighted_kappa(true: Any, pred: Any, n_classes: int = N_GRADES) -> float | None:
    """Cohen's kappa with quadratic weights over the classes ``0..n-1``; ``None`` if undefined.

    Same value as ``sklearn.metrics.cohen_kappa_score(..., weights="quadratic", labels=...)``,
    computed with integers until the final division. Undefined (expected disagreement 0, e.g. a
    single class in both vectors, or no sample) -> ``None``.
    """
    true = np.asarray(true, dtype=np.int64)
    pred = np.asarray(pred, dtype=np.int64)
    n = len(true)
    if n == 0:
        return None
    observed = confusion(true, pred, n_classes)
    idx = np.arange(n_classes)
    weights = (idx[:, None] - idx[None, :]) ** 2
    hist_true = observed.sum(axis=1)
    hist_pred = observed.sum(axis=0)
    expected = int((weights * np.outer(hist_true, hist_pred)).sum())
    if expected == 0:
        return None
    disagreement = n * int((weights * observed).sum())
    return 1.0 - disagreement / expected


def _class_stats(matrix: np.ndarray, k: int) -> dict[str, float | int | None]:
    tp = int(matrix[k, k])
    support = int(matrix[k, :].sum())
    predicted = int(matrix[:, k].sum())
    precision = _ratio(tp, predicted)
    recall = _ratio(tp, support)
    # F1 = 2PR / (P + R) = 2 tp / (support + predicted); 0 when tp = 0 and both are defined.
    f1 = None if precision is None or recall is None else 2 * tp / (support + predicted)
    return {"precision": precision, "recall": recall, "f1": f1, "support": support}


def grade_metrics(true: Any, pred: Any) -> dict[str, Any]:
    """Grade metrics of SPEC-012 section 4.7 for grade indices ``0..4`` (``unusable`` = 4).

    ``defective`` is ``qc_contracts.is_defective`` (poor and unusable).
    """
    true = np.asarray(true, dtype=np.int64)
    pred = np.asarray(pred, dtype=np.int64)
    if true.shape != pred.shape or true.ndim != 1:
        raise ValueError("true and pred must be 1-D arrays of the same length")
    n = len(true)
    matrix = confusion(true, pred, N_GRADES)
    distance = np.abs(true - pred)
    true_defective = DEFECTIVE_BY_INDEX[true] if n else np.zeros(0, dtype=bool)
    pred_defective = DEFECTIVE_BY_INDEX[pred] if n else np.zeros(0, dtype=bool)
    unusable = _class_stats(matrix, UNUSABLE_INDEX)
    both_defective = int((true_defective & pred_defective).sum())
    return {
        "grade_qwk": quadratic_weighted_kappa(true, pred),
        "grade_mae": float(distance.mean()) if n else None,
        "grade_off_by_one_accuracy": _ratio(int((distance <= 1).sum()), n),
        "grade_confusion": matrix.tolist(),
        "grade_per_class": {GRADES[k]: _class_stats(matrix, k) for k in range(N_GRADES)},
        "unusable_recall": unusable["recall"],
        "unusable_precision": unusable["precision"],
        "defective_recall": _ratio(both_defective, int(true_defective.sum())),
        "defective_precision": _ratio(both_defective, int(pred_defective.sum())),
    }


def _unusable_recall(true: np.ndarray, pred: np.ndarray) -> float | None:
    is_true = true == UNUSABLE_INDEX
    return _ratio(int((is_true & (pred == UNUSABLE_INDEX)).sum()), int(is_true.sum()))


def _defective_recall(true: np.ndarray, pred: np.ndarray) -> float | None:
    is_true = DEFECTIVE_BY_INDEX[true]
    return _ratio(int((is_true & DEFECTIVE_BY_INDEX[pred]).sum()), int(is_true.sum()))


BOOTSTRAP_METRICS: dict[str, Callable[[np.ndarray, np.ndarray], float | None]] = {
    "grade_qwk": quadratic_weighted_kappa,
    "unusable_recall": _unusable_recall,
    "defective_recall": _defective_recall,
}


def bootstrap_ci(
    true: Any,
    pred: Any,
    items: Sequence[str],
    metric: Callable[[np.ndarray, np.ndarray], float | None],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[list[float] | None, int]:
    """95% percentile interval of ``metric`` resampling whole items with replacement.

    Each resample draws as many items as there are distinct ``items`` and takes all images of
    each drawn item. Resamples where the metric is undefined are left out and counted.
    Returns ``([low, high] or None, n_undefined)``; ``None`` when no resample is defined.
    """
    true = np.asarray(true, dtype=np.int64)
    pred = np.asarray(pred, dtype=np.int64)
    item_ids = sorted(set(items))
    if not item_ids:
        return None, resamples
    position = {item: k for k, item in enumerate(item_ids)}
    rows_by_item: list[list[int]] = [[] for _ in item_ids]
    for row, item in enumerate(items):
        rows_by_item[position[item]].append(row)
    index_arrays = [np.asarray(r, dtype=np.int64) for r in rows_by_item]
    rng = np.random.default_rng(seed)
    values: list[float] = []
    undefined = 0
    for _ in range(resamples):
        drawn = rng.integers(0, len(item_ids), size=len(item_ids))
        rows = np.concatenate([index_arrays[k] for k in drawn])
        value = metric(true[rows], pred[rows])
        if value is None:
            undefined += 1
        else:
            values.append(value)
    if not values:
        return None, undefined
    low, high = np.percentile(np.asarray(values), [2.5, 97.5])
    return [float(low), float(high)], undefined


# ---------------------------------------------------------------------------------------------
# Counts and warnings
# ---------------------------------------------------------------------------------------------


def split_counts(rows: pd.DataFrame, labels: ModelLabels) -> dict[str, Any]:
    """``n_images``, ``n_items`` and ``by_class`` (type -> n_images, n_items, by_grade)."""
    by_class: dict[str, Any] = {}
    for object_type in labels.object_types:
        part = rows[rows["object_type"] == object_type]
        by_grade: dict[str, Any] = {}
        if object_type in GRADED_OBJECT_TYPES:
            for grade in labels.grades:
                cell = part[part["grade"] == grade]
                by_grade[grade] = {
                    "n_images": len(cell),
                    "n_items": int(cell["item_id"].nunique()),
                }
        by_class[object_type] = {
            "n_images": len(part),
            "n_items": int(part["item_id"].nunique()),
            "by_grade": by_grade,
        }
    return {
        "n_images": len(rows),
        "n_items": int(rows["item_id"].nunique()),
        "by_class": by_class,
    }


def _split_warnings(split_file: Path) -> list[str]:
    """``excluded_previous_image`` of ``split_v<N>.json`` (docs/dataset-protocol.md section 7)."""
    meta_path = split_file.with_suffix(".json")
    if not meta_path.is_file():
        return []
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [f"{meta_path.name} could not be read: split warnings not checked"]
    excluded: dict[str, int] = {}
    for warning in meta.get("warnings") or []:
        if isinstance(warning, dict) and warning.get("code") == "excluded_previous_image":
            name = str(warning.get("split"))
            excluded[name] = excluded.get(name, 0) + 1
    return [
        f"{meta_path.name}: {count} image(s) of the {name} split of the previous split version "
        "were excluded (excluded_previous_image, docs/dataset-protocol.md section 7)"
        for name, count in sorted(excluded.items())
    ]


# ---------------------------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------------------------


def compute_metrics(
    predictions: Predictions,
    item_ids: Sequence[str],
    labels: ModelLabels,
    thresholds: Thresholds,
) -> dict[str, Any]:
    """Every model metric of section 4.7 over ``predictions`` (the test split) and the warnings.

    ``item_ids`` is aligned with ``predictions.image_paths``. Latency and the file metadata are
    added by ``run``.
    """
    if predictions.split != "test":
        raise EvaluationError(
            f"the final metrics are measured on the test split, got {predictions.split!r}"
        )
    n = len(predictions)
    n_types = len(labels.object_types)
    true_type = predictions.true_type_idx
    pred_type = np.argmax(predictions.type_probs, axis=1) if n else np.zeros(0, dtype=np.int64)
    other = labels.object_types.index("other")
    graded_types = [labels.object_types.index(t) for t in GRADED_OBJECT_TYPES]
    is_screw_nut = np.isin(true_type, graded_types)
    graded = is_screw_nut & (predictions.true_grade_idx >= 0)

    true_grade = predictions.true_grade_idx[graded]
    pred_grade = decided_grade_idx(predictions.grade_probs[graded], thresholds.unusable_threshold)
    metrics: dict[str, Any] = {
        "type_accuracy": _ratio(int((pred_type == true_type).sum()), n),
        "type_confusion": confusion(true_type, pred_type, n_types).tolist(),
        **grade_metrics(true_grade, pred_grade),
    }
    decisions = apply_decision(predictions.type_probs, predictions.grade_probs, labels, thresholds)
    is_other = true_type == other
    metrics["unknown_rate_on_other"] = _ratio(
        int((decisions.unknown & is_other).sum()), int(is_other.sum())
    )
    metrics["false_unknown_rate"] = _ratio(
        int((decisions.unknown & is_screw_nut).sum()), int(is_screw_nut.sum())
    )
    metrics["needs_review_rate"] = _ratio(int(decisions.needs_review.sum()), n)

    graded_items = [item for item, keep in zip(item_ids, graded, strict=True) if keep]
    warnings: list[str] = []
    for name, metric in BOOTSTRAP_METRICS.items():
        if metrics[name] is None:
            metrics[f"{name}_ci95"] = None
            warnings.append(f"{name} is undefined on the test split (null)")
            continue
        interval, undefined = bootstrap_ci(true_grade, pred_grade, graded_items, metric)
        metrics[f"{name}_ci95"] = interval
        if undefined:
            warnings.append(
                f"{name}_ci95: {name} was undefined in {undefined} of {BOOTSTRAP_RESAMPLES} "
                "bootstrap resamples, left out of the interval"
            )

    items_by_grade: dict[str, int] = {}
    for k, grade in enumerate(labels.grades):
        items = {item for item, g in zip(graded_items, true_grade, strict=True) if g == k}
        items_by_grade[grade] = len(items)
        if len(items) < MIN_TEST_ITEMS_PER_GRADE:
            warnings.append(
                f"grade {grade} has {len(items)} item(s) in the test split "
                f"(< {MIN_TEST_ITEMS_PER_GRADE}): its metrics are very uncertain"
            )
    metrics["n_items_test_by_grade"] = items_by_grade
    for name in ("type_accuracy", "unknown_rate_on_other", "false_unknown_rate"):
        if metrics[name] is None:
            warnings.append(f"{name} is undefined on the test split (null)")
    metrics["warnings"] = warnings
    return metrics


def measure_latency(
    model: OnnxModel,
    paths: Sequence[Path],
    *,
    warmup: int = LATENCY_WARMUP,
    runs: int = LATENCY_RUNS,
) -> dict[str, Any]:
    """p50/p95 of ``load_image`` + ``preprocess`` + ``run`` with batch 1 (ms), CPU provider.

    The images are taken in order, cycling over ``paths``; ``warmup`` runs are discarded.
    """
    if not paths:
        raise EvaluationError("no image to measure the latency")
    timings: list[float] = []
    for k in range(warmup + runs):
        path = paths[k % len(paths)]
        start = time.perf_counter()
        model.run(model.load_input(path))
        elapsed = (time.perf_counter() - start) * 1000.0
        if k >= warmup:
            timings.append(elapsed)
    p50, p95 = np.percentile(np.asarray(timings), [50, 95])
    return {"latency_ms_p50": float(p50), "latency_ms_p95": float(p95), "latency_runs": runs}


def default_latency_machine() -> str:
    """A description of this machine without its host name (used when none is given)."""
    cpus = os.cpu_count() or 0
    return f"unspecified ({platform.system()} {platform.machine()}, {cpus} CPUs)"


def _check_model_dir(config: TrainConfig) -> tuple[Thresholds, OnnxModel]:
    decision_path = config.model_dir / DECISION_FILE
    if not decision_path.is_file():
        raise EvaluationError(f"{NO_DECISION_MESSAGE} ({decision_path})")
    thresholds = load_decision(decision_path)
    return thresholds, OnnxModel(config.model_dir)


def _rewrite_latency(
    config: TrainConfig, model: OnnxModel, metrics_path: Path, machine: str
) -> dict[str, Any]:
    """``--latency-only``: measure again and rewrite only the 4 latency keys."""
    if not metrics_path.is_file():
        raise EvaluationError(f"{NO_METRICS_MESSAGE} ({metrics_path})")
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"{metrics_path} is not valid JSON: {exc}") from exc
    if not isinstance(metrics, dict) or metrics.get("model_sha256") != model.sha256:
        raise EvaluationError(
            "metrics.json is from another model (model_sha256 differs): run qc_ml.evaluate "
            "without --latency-only"
        )
    df = load_manifest(config.dataset_dir)
    split_df = split.load_split(config.split_file)
    test_rows = split.rows_for(df, split_df, "test")  # images to time; nothing is chosen here
    paths = [Path(config.dataset_dir) / p for p in test_rows["image_path"]]
    metrics.update(measure_latency(model, paths), latency_machine=machine)
    write_json(metrics_path, metrics)
    logger.info("latency rewritten in %s", metrics_path)
    return metrics


def run(
    config: TrainConfig, *, latency_machine: str | None = None, latency_only: bool = False
) -> dict[str, Any]:
    """Evaluate the model on the test split and write ``metrics.json`` and the 2 PNGs.

    With ``latency_only``, only the latency keys of an existing ``metrics.json`` are measured
    again and rewritten. Nothing is written when any check fails.

    Raises:
        EvaluationError: ``decision.json`` (or, with ``latency_only``, ``metrics.json``) missing.
        ModelArtifactError: ``model.onnx``/``model.sha256`` missing or different.
    """
    thresholds, model = _check_model_dir(config)
    metrics_path = config.model_dir / METRICS_FILE
    machine = latency_machine or default_latency_machine()
    if latency_only:
        return _rewrite_latency(config, model, metrics_path, machine)

    df = load_manifest(config.dataset_dir)
    split_df = split.load_split(config.split_file)

    counts = {
        "train": split_counts(split.rows_for(df, split_df, "train"), model.labels),
        "val": split_counts(split.rows_for(df, split_df, "val"), model.labels),
    }
    test_rows = split.rows_for(df, split_df, "test")  # the only request of the test split
    if test_rows.empty:
        raise EvaluationError("the test split has no image")
    counts["test"] = split_counts(test_rows, model.labels)
    predictions = model.predict(test_rows, config.dataset_dir, "test")
    measured = compute_metrics(
        predictions, [str(i) for i in test_rows["item_id"]], model.labels, thresholds
    )
    paths = [Path(config.dataset_dir) / p for p in test_rows["image_path"]]
    latency = measure_latency(model, paths)
    warnings = _split_warnings(Path(config.split_file)) + measured.pop("warnings")

    values: dict[str, Any] = {
        "model_version": config.model_version,
        "model_sha256": model.sha256,
        "evaluated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "split_file": split_df.attrs.get("split_file"),
        "split_sha256": split_df.attrs.get("split_sha256"),
        "manifest_sha256": df.attrs.get("manifest_sha256"),
        "labels": labels_to_dict(model.labels),
        "decision": thresholds.to_dict(),
        **measured,
        **latency,
        "latency_machine": machine,
        "counts": counts,
        "warnings": warnings,
    }
    metrics = {key: values[key] for key in METRIC_KEYS}
    reports_dir = config.reports_dir
    confusion_png(
        reports_dir / TYPE_CONFUSION_PNG,
        metrics["type_confusion"],
        [type_label_pt(t) for t in model.labels.object_types],
        f"Tipo - {config.model_version} (teste)",
    )
    confusion_png(
        reports_dir / GRADE_CONFUSION_PNG,
        metrics["grade_confusion"],
        [grade_label_pt(g) for g in model.labels.grades],
        f"Grau - {config.model_version} (teste, parafusos e porcas)",
    )
    write_json(metrics_path, metrics)
    logger.info("metrics written: %s", metrics_path)
    return metrics


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qc_ml.evaluate",
        description="Evaluate the model on the test split (needs decision.json).",
    )
    parser.add_argument("--config", required=True, help="ml/configs/<model_version>.json")
    parser.add_argument("--latency-machine", default=None, help="where the latency is measured")
    parser.add_argument(
        "--latency-only", action="store_true", help="measure and rewrite only the latency keys"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; 0 when ``metrics.json`` was written, 2 on any error (nothing written)."""
    configure_logging()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR
    try:
        run(
            load_config(args.config),
            latency_machine=args.latency_machine,
            latency_only=args.latency_only,
        )
    except Exception as exc:  # noqa: BLE001 - every failure is reported and exits with 2
        return report_step_error("evaluate", exc)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
