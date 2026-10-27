"""Author tests for qc_ml.evaluate (SPEC-012 §4.7; CA-20..CA-24). No torch."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pytest

from qc_ml import evaluate as evaluate_mod
from qc_ml import split as split_mod
from qc_ml import thresholds as thresholds_mod
from qc_ml.evaluate import (
    METRIC_KEYS,
    bootstrap_ci,
    grade_metrics,
    quadratic_weighted_kappa,
)


def _paths(config_path: Path) -> tuple[dict, Path, Path]:
    config = json.loads(config_path.read_text())
    model_dir = Path(config["models_root"]) / config["model_version"]
    reports_dir = Path(config["reports_root"]) / config["model_version"]
    return config, model_dir, reports_dir


def test_ca23_grade_metrics() -> None:
    true = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
    pred = [0, 1, 2, 4, 4, 0, 2, 2, 3, 4]
    m = grade_metrics(true, pred)
    assert m["grade_qwk"] == pytest.approx(20 / 21, abs=1e-4)
    assert m["grade_mae"] == pytest.approx(0.2)
    assert m["grade_off_by_one_accuracy"] == 1.0
    assert m["unusable_recall"] == 1.0
    assert m["unusable_precision"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["defective_recall"] == 1.0 and m["defective_precision"] == 1.0
    assert np.asarray(m["grade_confusion"]).sum() == 10
    assert m["grade_per_class"]["good"] == {
        "precision": 1.0,
        "recall": 0.5,
        "f1": pytest.approx(2 / 3),
        "support": 2,
    }


def test_qwk_matches_sklearn() -> None:
    from sklearn.metrics import cohen_kappa_score

    rng = np.random.default_rng(3)
    for _ in range(50):
        n = int(rng.integers(2, 40))
        true = rng.integers(0, 5, size=n)
        pred = np.clip(true + rng.integers(-2, 3, size=n), 0, 4)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # sklearn warns when the kappa is undefined (nan)
            expected = cohen_kappa_score(true, pred, weights="quadratic", labels=list(range(5)))
        got = quadratic_weighted_kappa(true, pred)
        if np.isnan(expected):
            assert got is None
        else:
            assert got == pytest.approx(expected, abs=1e-12)
    assert quadratic_weighted_kappa([2, 2], [2, 2]) is None
    assert quadratic_weighted_kappa([0, 1], [1, 0]) == -1.0
    assert quadratic_weighted_kappa([], []) is None


def test_undefined_metrics_are_null_not_omitted() -> None:
    m = grade_metrics([0, 0, 1], [0, 1, 1])
    assert m["unusable_recall"] is None and m["defective_recall"] is None
    assert m["unusable_precision"] is None
    stats = m["grade_per_class"]["unusable"]
    assert stats == {"precision": None, "recall": None, "f1": None, "support": 0}
    assert set(m["grade_per_class"]) == {"perfect", "good", "fair", "poor", "unusable"}
    empty = grade_metrics([], [])
    assert empty["grade_qwk"] is None and empty["grade_mae"] is None
    assert empty["grade_confusion"] == [[0] * 5 for _ in range(5)]


def test_bootstrap_ci_resamples_items() -> None:
    true = np.array([0, 0, 4, 4, 3, 3])
    pred = np.array([0, 1, 4, 4, 3, 2])
    items = ["S-001", "S-001", "S-002", "S-002", "S-003", "S-003"]
    first, undefined = bootstrap_ci(true, pred, items, quadratic_weighted_kappa)
    again, _ = bootstrap_ci(true, pred, items, quadratic_weighted_kappa)
    assert first == again and first[0] <= first[1] and undefined >= 0
    recall = evaluate_mod.BOOTSTRAP_METRICS["unusable_recall"]
    interval, undefined = bootstrap_ci(true, pred, items, recall)
    assert interval == [1.0, 1.0]
    assert 0 < undefined < 1000  # resamples without S-002 have no unusable image
    assert bootstrap_ci([], [], [], recall) == (None, 1000)


def test_ca21_without_decision_json(tiny_config: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, model_dir, reports_dir = _paths(tiny_config)
    (model_dir / "decision.json").unlink()
    assert evaluate_mod.main(["--config", str(tiny_config)]) == 2
    assert "run qc_ml.thresholds first" in capsys.readouterr().err
    assert not (model_dir / "metrics.json").exists()
    assert not reports_dir.exists()


def test_evaluate_refuses_a_model_that_differs_from_its_sha(tiny_config: Path) -> None:
    _, model_dir, _ = _paths(tiny_config)
    (model_dir / "model.onnx").write_bytes((model_dir / "model.onnx").read_bytes() + b"\0")
    assert evaluate_mod.main(["--config", str(tiny_config)]) == 2
    assert not (model_dir / "metrics.json").exists()
    (model_dir / "model.onnx").unlink()
    assert evaluate_mod.main(["--config", str(tiny_config)]) == 2


def _is_rate(value: object) -> bool:
    return value is None or (isinstance(value, float) and 0.0 <= value <= 1.0)


def test_ca22_metrics_file(tiny_config: Path) -> None:
    assert thresholds_mod.main(["--config", str(tiny_config)]) == 0
    assert evaluate_mod.main(["--config", str(tiny_config), "--latency-machine", "ci"]) == 0
    _, model_dir, reports_dir = _paths(tiny_config)
    metrics = json.loads((model_dir / "metrics.json").read_text())
    assert list(metrics) == list(METRIC_KEYS)
    assert len(METRIC_KEYS) == 33  # SPEC-012's 32 + tool_grade_metrics (SPEC-016)
    assert metrics["tool_grade_metrics"] == {}  # model without tools
    for key in ("grade_qwk_ci95", "unusable_recall_ci95", "defective_recall_ci95"):
        value = metrics[key]
        assert value is None or (len(value) == 2 and value[0] <= value[1])
    assert isinstance(metrics["warnings"], list)
    assert all(isinstance(w, str) for w in metrics["warnings"])
    assert np.asarray(metrics["type_confusion"]).shape == (3, 3)
    assert np.asarray(metrics["grade_confusion"]).shape == (5, 5)
    per_class = metrics["grade_per_class"]
    assert list(per_class) == ["perfect", "good", "fair", "poor", "unusable"]
    for stats in per_class.values():
        assert set(stats) == {"precision", "recall", "f1", "support"}
        if stats["support"] == 0:
            assert stats["recall"] is None and stats["f1"] is None
    test_counts = metrics["counts"]["test"]
    graded_images = sum(
        test_counts["by_class"][t]["by_grade"][g]["n_images"]
        for t in ("screw", "nut")
        for g in per_class
    )
    assert np.asarray(metrics["grade_confusion"]).sum() == graded_images
    assert np.asarray(metrics["type_confusion"]).sum() == test_counts["n_images"]
    for key in (
        "type_accuracy",
        "grade_off_by_one_accuracy",
        "unusable_recall",
        "unusable_precision",
        "defective_recall",
        "defective_precision",
        "unknown_rate_on_other",
        "false_unknown_rate",
        "needs_review_rate",
    ):
        assert _is_rate(metrics[key]), key
    assert set(metrics["counts"]) == {"train", "val", "test"}
    assert set(metrics["n_items_test_by_grade"]) == set(per_class)
    assert metrics["latency_runs"] == 100 and metrics["latency_machine"] == "ci"
    assert metrics["latency_ms_p50"] <= metrics["latency_ms_p95"]
    assert metrics["decision"] == json.loads((model_dir / "decision.json").read_text())
    assert metrics["model_sha256"] == (model_dir / "model.sha256").read_text().strip()
    for name in ("type_confusion.png", "grade_confusion.png"):
        assert (reports_dir / name).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_warning_for_grades_with_few_test_items(tiny_config: Path) -> None:
    assert thresholds_mod.main(["--config", str(tiny_config)]) == 0
    assert evaluate_mod.main(["--config", str(tiny_config)]) == 0
    _, model_dir, _ = _paths(tiny_config)
    metrics = json.loads((model_dir / "metrics.json").read_text())
    # 4 items per (type, grade): 1 screw + 1 nut per grade in the test split -> 2 items.
    assert all(n >= 2 for n in metrics["n_items_test_by_grade"].values())
    assert not any("item(s) in the test split" in w for w in metrics["warnings"])
    assert metrics["latency_machine"].startswith("unspecified (")


def test_ca24_latency_only(tiny_config: Path) -> None:
    assert evaluate_mod.main(["--config", str(tiny_config)]) == 0
    _, model_dir, _ = _paths(tiny_config)
    before = json.loads((model_dir / "metrics.json").read_text())
    args = ["--config", str(tiny_config), "--latency-only", "--latency-machine", "notebook-borda"]
    assert evaluate_mod.main(args) == 0
    after = json.loads((model_dir / "metrics.json").read_text())
    changed = {k for k in METRIC_KEYS if before[k] != after[k]}
    assert changed <= set(evaluate_mod.LATENCY_KEYS)
    assert after["latency_machine"] == "notebook-borda" and after["latency_runs"] == 100
    assert list(after) == list(METRIC_KEYS)


def test_latency_only_needs_metrics(tiny_config: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert evaluate_mod.main(["--config", str(tiny_config), "--latency-only"]) == 2
    assert "metrics.json not found" in capsys.readouterr().err


def test_ca20_test_split_requested_once_after_decision(
    tiny_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, model_dir, _ = _paths(tiny_config)
    (model_dir / "decision.json").unlink()
    calls: list[tuple[str, bool]] = []
    original = split_mod.rows_for

    def spy(df, split_df, which):
        calls.append((which, (model_dir / "decision.json").exists()))
        return original(df, split_df, which)

    monkeypatch.setattr(split_mod, "rows_for", spy)
    assert thresholds_mod.main(["--config", str(tiny_config)]) == 0
    threshold_calls = list(calls)
    assert threshold_calls == [("val", False)]
    assert evaluate_mod.main(["--config", str(tiny_config)]) == 0
    test_calls = [c for c in calls if c[0] == "test"]
    assert test_calls == [("test", True)]


def test_split_warnings_are_cited(tiny_config: Path) -> None:
    config, model_dir, _ = _paths(tiny_config)
    meta_path = Path(config["split_file"]).with_suffix(".json")
    meta = json.loads(meta_path.read_text())
    meta["warnings"] = [
        {"code": "excluded_previous_image", "image_path": "raw/a.jpg", "split": "test"}
    ]
    meta_path.write_text(json.dumps(meta))
    assert evaluate_mod.main(["--config", str(tiny_config)]) == 0
    metrics = json.loads((model_dir / "metrics.json").read_text())
    assert any("excluded_previous_image" in w for w in metrics["warnings"])
