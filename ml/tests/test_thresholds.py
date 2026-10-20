"""Author tests for qc_ml.thresholds (SPEC-012 §4.6; CA-15..CA-19). No torch."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from qc_ml import thresholds as thresholds_mod
from qc_ml.data import DEFAULT_LABELS
from qc_ml.errors import EvaluationError, SplitIntegrityError
from qc_ml.predict import Predictions
from qc_ml.thresholds import choose_thresholds

SCREW, NUT, OTHER = 0, 1, 2


def make_predictions(type_probs, grade_probs, true_type, true_grade, split="val") -> Predictions:
    n = len(type_probs)
    return Predictions(
        split=split,
        image_paths=[f"raw/x/{i}.jpg" for i in range(n)],
        type_probs=np.asarray(type_probs, dtype=np.float64),
        grade_probs=np.asarray(grade_probs, dtype=np.float64),
        true_type_idx=np.asarray(true_type),
        true_grade_idx=np.asarray(true_grade),
    )


def _screws(maxima, other_mask=None, grade=None) -> Predictions:
    type_probs = []
    for i, m in enumerate(maxima):
        rest = (1 - m) / 2
        if other_mask is not None and other_mask[i]:
            type_probs.append([rest, rest, m])
        else:
            type_probs.append([m, rest, rest])
    grade = grade if grade is not None else [[0.9, 0.025, 0.025, 0.025, 0.025]] * len(maxima)
    return make_predictions(type_probs, grade, [SCREW] * len(maxima), [0] * len(maxima))


@pytest.mark.parametrize("split", ["test", "train"])
def test_ca15_refuses_any_split_but_val(split: str, tmp_path: Path) -> None:
    preds = make_predictions([[0.9, 0.05, 0.05]], [[1, 0, 0, 0, 0]], [SCREW], [0], split=split)
    with pytest.raises(SplitIntegrityError):
        choose_thresholds(preds, DEFAULT_LABELS)
    assert list(tmp_path.iterdir()) == []


def test_empty_val_is_an_error() -> None:
    with pytest.raises(EvaluationError):
        choose_thresholds(make_predictions(np.zeros((0, 3)), np.zeros((0, 5)), [], []))


def test_ca16_type_threshold() -> None:
    maxima = [0.503 + 0.005 * i for i in range(100)]
    result = choose_thresholds(_screws(maxima), DEFAULT_LABELS)
    assert result.decision["type_threshold"] == 0.52
    assert result.report["type_threshold"]["false_unknown_rate"] == pytest.approx(0.04)
    assert "type_target_not_met" not in result.report["notes"]

    other = [i < 6 for i in range(100)]
    result = choose_thresholds(_screws(maxima, other_mask=other), DEFAULT_LABELS)
    assert result.decision["type_threshold"] == 0.50
    assert "type_target_not_met" in result.report["notes"]


def test_type_threshold_capped_at_085_and_nut_counts() -> None:
    preds = make_predictions([[0.01, 0.98, 0.01]] * 4, [[1, 0, 0, 0, 0]] * 4, [NUT] * 4, [0] * 4)
    assert choose_thresholds(preds).decision["type_threshold"] == 0.85


def test_no_screw_nut_in_val() -> None:
    preds = make_predictions([[0.1, 0.1, 0.8]] * 3, [[0.2] * 5] * 3, [OTHER] * 3, [-1] * 3)
    result = choose_thresholds(preds)
    assert result.decision["type_threshold"] == 0.50
    assert "no_screw_nut_in_val" in result.report["notes"]
    assert "type_target_not_met" not in result.report["notes"]  # SPEC-031 §4.4
    assert "no_unusable_in_val" in result.report["notes"]


def _unusable_preds(p_unusable) -> Predictions:
    grade = [[0.0, 0.0, 0.45 - p, 0.55, p] for p in p_unusable]
    n = len(grade)
    return make_predictions([[0.99, 0.005, 0.005]] * n, grade, [SCREW] * n, [4] * n)


def test_ca17_unusable_threshold() -> None:
    p_unusable = [0.45, 0.40, 0.35, 0.30, 0.25, 0.22, 0.18, 0.15, 0.125, 0.05]
    result = choose_thresholds(_unusable_preds(p_unusable), DEFAULT_LABELS)
    assert result.decision["unusable_threshold"] == 0.12
    assert result.report["unusable_threshold"]["unusable_recall"] == pytest.approx(0.9)
    assert "unusable_target_not_met" not in result.report["notes"]

    result = choose_thresholds(_unusable_preds([0.01] * 10), DEFAULT_LABELS)
    assert "unusable_target_not_met" in result.report["notes"]
    assert result.decision["unusable_threshold"] == 0.95  # recall 0 everywhere: tie -> larger u


def test_unusable_best_recall_when_target_unreachable() -> None:
    # Recall 0.8 at most (2 of 10 never reach 0.05): the largest u with that recall is chosen.
    p_unusable = [0.30] * 8 + [0.01, 0.01]
    result = choose_thresholds(_unusable_preds(p_unusable))
    assert result.decision["unusable_threshold"] == 0.30
    assert "unusable_target_not_met" in result.report["notes"]


def _review_preds(start: float) -> Predictions:
    grade = []
    for i in range(100):
        c = min(start + 0.005 * i, 1.0)  # a valid probability (SPEC-031 §4.2)
        rest = (1 - c) / 4
        grade.append([c, rest, rest, rest, rest])
    return make_predictions([[0.99, 0.005, 0.005]] * 100, grade, [SCREW] * 100, [0] * 100)


def test_ca18_review_threshold() -> None:
    result = choose_thresholds(_review_preds(0.3025), DEFAULT_LABELS)
    assert result.decision["type_threshold"] == 0.85
    assert result.decision["grade_review_threshold"] == 0.35
    assert result.report["grade_review_threshold"]["needs_review_rate"] == pytest.approx(0.10)
    assert "review_adjusted" in result.report["notes"]

    result = choose_thresholds(_review_preds(0.5525), DEFAULT_LABELS)
    assert result.decision["grade_review_threshold"] == 0.60
    assert "review_adjusted" not in result.report["notes"]


def test_values_have_two_decimals() -> None:
    rng = np.random.default_rng(5)
    n = 60
    type_probs = rng.dirichlet(np.ones(3), size=n)
    grade_probs = rng.dirichlet(np.ones(5), size=n)
    true_type = rng.integers(0, 3, size=n)
    true_grade = np.where(true_type == OTHER, -1, rng.integers(0, 5, size=n))
    result = choose_thresholds(make_predictions(type_probs, grade_probs, true_type, true_grade))
    for key, value in result.decision.items():
        assert value == round(value, 2), key
    assert 0.50 <= result.decision["type_threshold"] <= 0.85
    assert 0.05 <= result.decision["unusable_threshold"] <= 0.95
    assert 0.30 <= result.decision["grade_review_threshold"] <= 0.95


def test_ca19_cli_with_the_tiny_model(tiny_config: Path) -> None:
    assert thresholds_mod.main(["--config", str(tiny_config)]) == 0
    config = json.loads(tiny_config.read_text())
    decision = json.loads(
        (Path(config["models_root"]) / config["model_version"] / "decision.json").read_text()
    )
    assert set(decision) == {"type_threshold", "unusable_threshold", "grade_review_threshold"}
    grids = {
        "type_threshold": {k / 100 for k in range(50, 86)},
        "unusable_threshold": {k / 100 for k in range(5, 96)},
        "grade_review_threshold": {k / 100 for k in range(30, 96)},
    }
    for key, value in decision.items():
        assert value in grids[key], key
    report_path = Path(config["reports_root"]) / config["model_version"] / "thresholds_report.json"
    report = json.loads(report_path.read_text())
    assert report["n_val_images"] > 0 and report["split_sha256"]
    assert report["decision"] == decision


def test_cli_errors_exit_2(tiny_config: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = json.loads(tiny_config.read_text())
    model_dir = Path(config["models_root"]) / config["model_version"]
    (model_dir / "model.sha256").write_text("0" * 64 + "\n")
    (model_dir / "decision.json").unlink()
    assert thresholds_mod.main(["--config", str(tiny_config)]) == 2
    assert "does not match" in capsys.readouterr().err
    assert not (model_dir / "decision.json").exists()
    assert thresholds_mod.main(["--config", str(tiny_config.parent / "missing.json")]) == 2
    assert thresholds_mod.main([]) == 2
