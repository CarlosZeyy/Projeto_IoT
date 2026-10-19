"""Author tests for qc_ml.decision (SPEC-012 §4.5; docs/architecture.md §6.2, step 4)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from qc_ml.data import DEFAULT_LABELS
from qc_ml.decision import Thresholds, apply_decision, load_decision, write_decision
from qc_ml.errors import ModelArtifactError

T = Thresholds(type_threshold=0.70, unusable_threshold=0.50, grade_review_threshold=0.60)


def _one(type_probs, grade_probs, thresholds=T) -> dict:
    return apply_decision(type_probs, grade_probs, DEFAULT_LABELS, thresholds).record(0)


def test_known_type_with_grade() -> None:
    d = _one([0.9, 0.05, 0.05], [0.1, 0.7, 0.1, 0.05, 0.05])
    assert d["object_type"] == "screw" and d["grade"] == "good"
    assert d["grade_confidence"] == pytest.approx(0.7)
    assert d["grade_score"] == pytest.approx(0.7 + 0.2 + 0.15 + 0.2)
    assert d["needs_review"] is False


def test_other_or_low_confidence_is_unknown() -> None:
    other = _one([0.1, 0.1, 0.8], [0.2] * 5)
    assert other["object_type"] == "unknown"
    assert other["grade"] is None and other["grade_score"] is None
    assert other["grade_confidence"] is None
    low = _one([0.69, 0.31, 0.0], [0.0, 0.0, 0.0, 0.0, 1.0])
    assert low["object_type"] == "unknown" and low["needs_review"] is True
    exact = _one([0.70, 0.30, 0.0], [1.0, 0.0, 0.0, 0.0, 0.0])
    assert exact["object_type"] == "screw"  # strict < type_threshold


def test_unusable_threshold_overrides_the_argmax() -> None:
    d = _one([0.95, 0.05, 0.0], [0.0, 0.0, 0.0, 0.5, 0.5])
    assert d["grade"] == "unusable"  # >= unusable_threshold
    d = _one([0.95, 0.05, 0.0], [0.0, 0.0, 0.0, 0.51, 0.49])
    assert d["grade"] == "poor"


def test_needs_review_rules() -> None:
    assert _one([0.79, 0.21, 0.0], [1.0, 0, 0, 0, 0])["needs_review"] is True  # < 0.70 + 0.10
    assert _one([0.81, 0.19, 0.0], [1.0, 0, 0, 0, 0])["needs_review"] is False
    assert _one([0.95, 0.05, 0.0], [0.59, 0.41, 0, 0, 0])["needs_review"] is True


def test_clamp_after_comparisons() -> None:
    d = _one([1.0000001, 0.0, 0.0], [0.0, 0.0, 0.0, 6e-8, 1.0])
    assert d["type_confidence"] == 1.0 and d["grade_confidence"] == 1.0
    assert d["grade_score"] == 4.0


def test_batch_shapes_and_errors() -> None:
    decisions = apply_decision(np.full((3, 3), 1 / 3), np.full((3, 5), 0.2), DEFAULT_LABELS, T)
    assert len(decisions) == 3 and decisions.object_types == ("unknown",) * 3
    empty = apply_decision(np.zeros((0, 3)), np.zeros((0, 5)), DEFAULT_LABELS, T)
    assert len(empty) == 0
    with pytest.raises(ValueError):
        apply_decision(np.zeros((2, 4)), np.zeros((2, 5)), DEFAULT_LABELS, T)
    with pytest.raises(ValueError):
        apply_decision(np.zeros((2, 3)), np.zeros((3, 5)), DEFAULT_LABELS, T)


def test_thresholds_mapping_and_files(tmp_path: Path) -> None:
    assert T["type_threshold"] == T.type_threshold == 0.70
    assert dict(T) == {
        "type_threshold": 0.70,
        "unusable_threshold": 0.50,
        "grade_review_threshold": 0.60,
    }
    assert dict(T) == T
    path = tmp_path / "decision.json"
    write_decision(path, T)
    assert json.loads(path.read_text()) == dict(T)
    assert load_decision(path) == T
    path.write_text(json.dumps({**dict(T), "extra": 1}))
    with pytest.raises(ModelArtifactError, match="exactly"):
        load_decision(path)
    with pytest.raises(ValueError):
        Thresholds(1.5, 0.5, 0.5)
    with pytest.raises(ValueError):
        Thresholds(math.nan, 0.5, 0.5)


def test_same_result_as_the_edge_decision() -> None:
    """SPEC-012 §6: qc_ml.decision and qc_edge.decision agree on 1,000 random vectors."""
    edge = pytest.importorskip("qc_edge.decision")
    rng = np.random.default_rng(12)
    labels = edge.ModelLabels(DEFAULT_LABELS.object_types, DEFAULT_LABELS.grades)
    for _ in range(1000):
        sharp = rng.uniform(0.2, 5.0)
        type_probs = rng.dirichlet(np.full(3, 1 / sharp))
        grade_probs = rng.dirichlet(np.full(5, 1 / sharp))
        t, u, r = (round(float(v), 2) for v in rng.uniform([0.5, 0.05, 0.3], [0.85, 0.95, 0.95]))
        mine = _one(type_probs, grade_probs, Thresholds(t, u, r))
        theirs = edge.decide(
            type_probs.tolist(), grade_probs.tolist(), labels, edge.Thresholds(t, u, r)
        )
        assert mine["object_type"] == theirs.object_type.value
        assert mine["grade"] == (None if theirs.grade is None else theirs.grade.value)
        assert mine["needs_review"] == theirs.needs_review
        assert mine["type_confidence"] == pytest.approx(theirs.type_confidence, abs=1e-12)
        for key in ("grade_confidence", "grade_score"):
            value = getattr(theirs, key)
            if value is None:
                assert mine[key] is None
            else:
                assert mine[key] == pytest.approx(value, abs=1e-12)
