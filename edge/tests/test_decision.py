"""Decision rule ``qc_edge.decision.decide`` (SPEC-008 section 4.1)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from qc_contracts import Grade, InspectionCreate, ObjectType
from qc_edge.decision import (
    REVIEW_MARGIN,
    THRESHOLD_NAMES,
    Decision,
    InvalidModelOutputError,
    ModelLabels,
    Thresholds,
    decide,
)
from qc_edge.inference import InferenceError

LABELS = ModelLabels(
    object_types=("screw", "nut", "other"),
    grades=("perfect", "good", "fair", "poor", "unusable"),
)
THRESHOLDS = Thresholds(type_threshold=0.5, unusable_threshold=0.4, grade_review_threshold=0.6)
GOOD = [0.05, 0.8, 0.05, 0.05, 0.05]


def _decide(type_probs, grade_probs=GOOD, labels=LABELS, thresholds=THRESHOLDS) -> Decision:
    return decide(type_probs, grade_probs, labels, thresholds)


def test_review_margin() -> None:
    assert REVIEW_MARGIN == 0.10
    assert THRESHOLD_NAMES == ("type_threshold", "unusable_threshold", "grade_review_threshold")


def test_other_is_unknown_even_with_high_confidence() -> None:  # CA-01
    decision = _decide([0.1, 0.1, 0.8])
    assert decision == Decision(
        object_type=ObjectType.UNKNOWN,
        grade=None,
        grade_score=None,
        type_confidence=0.8,
        grade_confidence=None,
        needs_review=False,
    )


def test_low_type_confidence_is_unknown_and_needs_review() -> None:  # CA-02
    decision = _decide([0.45, 0.30, 0.25])
    assert decision.object_type is ObjectType.UNKNOWN
    assert decision.grade is None and decision.grade_score is None
    assert decision.grade_confidence is None
    assert decision.type_confidence == 0.45
    assert decision.needs_review is True


def test_type_threshold_is_strict() -> None:  # CA-03
    decision = _decide([0.5, 0.3, 0.2])
    assert decision.object_type is ObjectType.SCREW
    assert decision.needs_review is True  # 0.5 < 0.6


def test_review_margin_boundary_and_grade_score() -> None:  # CA-04
    decision = _decide([0.6, 0.3, 0.1], [0.0, 0.7, 0.1, 0.1, 0.1])
    assert decision.needs_review is False
    assert decision.grade is Grade.GOOD
    assert decision.grade_confidence == 0.7
    assert decision.grade_score == pytest.approx(1.6, abs=1e-9)


def test_unusable_threshold_is_inclusive() -> None:  # CA-05
    decision = _decide([0.05, 0.9, 0.05], [0.45, 0.05, 0.05, 0.05, 0.4])
    assert decision.object_type is ObjectType.NUT
    assert decision.grade is Grade.UNUSABLE
    assert decision.grade_confidence == 0.4
    # grade_confidence 0.4 < 0.6: an unusable decided by the threshold is reviewed.
    assert decision.needs_review is True
    decision = _decide([0.05, 0.9, 0.05], [0.46, 0.05, 0.05, 0.05, 0.39])
    assert decision.grade is Grade.PERFECT
    assert decision.grade_confidence == 0.46


@pytest.mark.parametrize(("confidence", "review"), [(0.6, False), (0.59, True)])
def test_grade_review_threshold(confidence: float, review: bool) -> None:  # CA-06
    rest = (1.0 - confidence) / 4
    decision = _decide([0.9, 0.05, 0.05], [rest, confidence, rest, rest, rest])
    assert decision.grade is Grade.GOOD
    assert decision.grade_confidence == confidence
    assert decision.needs_review is review


@pytest.mark.parametrize(
    ("type_probs", "grade_probs"),
    [
        ([0.5, 0.5, 0.5], GOOD),  # sum 1.5
        ([math.nan, 0.5, 0.5], GOOD),
        ([0.9, 0.05, 0.05], [0.05, math.nan, 0.05, 0.05, 0.85]),
        ([math.inf, 0.0, 0.0], GOOD),
        ([-0.1, 0.6, 0.5], GOOD),
        ([1.1, -0.05, -0.05], GOOD),
        ([0.9, 0.05, 0.05], [0.1, 0.8, 0.05, 0.05]),  # 4 grades
        ([0.9, 0.05, 0.05], [0.1, 0.8, 0.05, 0.05, 0.0, 0.0]),  # 6 grades
        ([0.9, 0.1], GOOD),  # 2 types for 3 labels
        ([0.9, 0.05, 0.05, 0.0], GOOD),
        ([0.5, 0.3, 0.1], GOOD),  # sum 0.9
        ([0.9, 0.05, 0.05], [0.2, 0.8, 0.2, 0.0, 0.0]),  # grade sum 1.2
        ([0.9, 0.05, "x"], GOOD),
        (0.9, GOOD),  # not a sequence
        ([[0.9, 0.05, 0.05]], GOOD),  # a [1, 3] batch, not a vector
    ],
)
def test_invalid_outputs(type_probs, grade_probs) -> None:  # CA-07
    with pytest.raises(InvalidModelOutputError):
        _decide(type_probs, grade_probs)


def test_invalid_output_is_an_inference_error() -> None:
    assert issubclass(InvalidModelOutputError, InferenceError)


@pytest.mark.parametrize(
    "type_probs",
    [
        [1.0 + 0.9e-6, 0.0, 0.0],  # within the 1e-6 value tolerance (sum within 1e-3)
        [0.9995, 0.0, 0.0],  # sum 1 - 5e-4
        [0.9, 0.05, 0.0509],  # sum 1 + 9e-4
        [1.0, -0.9e-6, 0.0],
    ],
)
def test_tolerances_accept(type_probs: list[float]) -> None:
    assert _decide(type_probs).object_type is ObjectType.SCREW


@pytest.mark.parametrize(
    "type_probs",
    [
        [1.0 + 2e-6, -1e-6, -1e-6],  # value above 1 + 1e-6
        [0.998, 0.0, 0.0],  # sum 1 - 2e-3
        [0.9, 0.05, 0.052],  # sum 1 + 2e-3
    ],
)
def test_tolerances_refuse(type_probs: list[float]) -> None:
    with pytest.raises(InvalidModelOutputError):
        _decide(type_probs)


def test_type_tie_goes_to_the_smallest_index() -> None:
    decision = _decide([0.45, 0.45, 0.1], thresholds=Thresholds(0.4, 0.4, 0.6))
    assert decision.object_type is ObjectType.SCREW
    decision = _decide([0.1, 0.45, 0.45], thresholds=Thresholds(0.4, 0.4, 0.6))
    assert decision.object_type is ObjectType.NUT


def test_other_tie_with_screw_picks_screw_first() -> None:
    labels = ModelLabels(object_types=("other", "screw"), grades=LABELS.grades)
    decision = _decide([0.5, 0.5], labels=labels)
    assert decision.object_type is ObjectType.UNKNOWN  # index 0 is "other"


def test_grade_tie_goes_to_the_smallest_index() -> None:
    decision = _decide([0.9, 0.05, 0.05], [0.0, 0.0, 0.4, 0.4, 0.2])
    assert decision.grade is Grade.FAIR
    assert decision.grade_confidence == 0.4


def test_unusable_by_argmax_below_the_threshold() -> None:
    thresholds = Thresholds(0.5, 0.9, 0.6)
    decision = _decide([0.9, 0.05, 0.05], [0.0, 0.1, 0.1, 0.1, 0.7], thresholds=thresholds)
    assert decision.grade is Grade.UNUSABLE
    assert decision.grade_confidence == 0.7


def test_grade_score_is_the_expected_value() -> None:
    probs = [0.1, 0.2, 0.3, 0.25, 0.15]
    decision = _decide([0.9, 0.05, 0.05], probs, thresholds=Thresholds(0.5, 0.9, 0.0))
    assert decision.grade_score == pytest.approx(sum(i * p for i, p in enumerate(probs)), abs=1e-12)
    assert decision.grade is Grade.FAIR
    assert decision.needs_review is False


def test_type_confidence_is_kept_for_unknown() -> None:
    decision = _decide([0.4, 0.35, 0.25])
    assert decision.object_type is ObjectType.UNKNOWN
    assert decision.type_confidence == 0.4


def test_numpy_float32_vectors() -> None:
    decision = _decide(
        np.asarray([0.9, 0.05, 0.05], dtype=np.float32),
        np.asarray(GOOD, dtype=np.float32),
    )
    assert decision.object_type is ObjectType.SCREW
    assert decision.grade is Grade.GOOD
    assert type(decision.type_confidence) is float
    assert type(decision.grade_confidence) is float
    assert type(decision.grade_score) is float


def test_label_order_comes_from_labels() -> None:
    labels = ModelLabels(object_types=("nut", "other", "screw"), grades=LABELS.grades)
    assert _decide([0.05, 0.05, 0.9], labels=labels).object_type is ObjectType.SCREW
    assert _decide([0.9, 0.05, 0.05], labels=labels).object_type is ObjectType.NUT


# Section 4.1, item 6: the returned numbers are clamped to the contract ranges (CA-19).
SOFTMAX_UNUSABLE = [2.506e-10, 2.235e-10, 7.39e-11, 5.899e-08, 1.0]


def test_float32_softmax_unusable_is_clamped_to_4() -> None:  # CA-19 (a)
    assert sum(index * prob for index, prob in enumerate(SOFTMAX_UNUSABLE)) > 4.0
    decision = _decide([0.98, 0.01, 0.01], SOFTMAX_UNUSABLE)
    assert decision.object_type is ObjectType.SCREW
    assert decision.grade is Grade.UNUSABLE
    assert decision.grade_score == 4.0
    assert decision.grade_confidence == 1.0
    assert decision.needs_review is False


def test_float32_softmax_unusable_from_numpy_is_clamped() -> None:
    decision = _decide(
        np.asarray([0.98, 0.01, 0.01], dtype=np.float32),
        np.asarray(SOFTMAX_UNUSABLE, dtype=np.float32),
    )
    assert decision.grade is Grade.UNUSABLE
    assert decision.grade_score == 4.0
    assert type(decision.grade_score) is float


def test_type_confidence_above_1_is_clamped() -> None:  # CA-19 (b)
    decision = _decide([1.0000009, 0.0, 0.0])
    assert decision.object_type is ObjectType.SCREW
    assert decision.type_confidence == 1.0
    assert decision.grade is Grade.GOOD


def test_grade_confidence_above_1_and_negative_score_are_clamped() -> None:  # CA-19 (c)
    decision = _decide([0.9, 0.05, 0.05], [1.0000005, -5e-7, 0.0, 0.0, 0.0])
    assert decision.grade is Grade.PERFECT
    assert decision.grade_confidence == 1.0
    assert decision.grade_score == 0.0


def test_type_confidence_above_1_is_clamped_for_unknown() -> None:
    decision = _decide([0.0, 0.0, 1.0000009])
    assert decision.object_type is ObjectType.UNKNOWN
    assert decision.type_confidence == 1.0
    assert decision.grade_score is None and decision.grade_confidence is None


def test_comparisons_use_the_raw_values() -> None:
    # unusable_threshold = 0 and a raw p4 of -5e-7: -5e-7 >= 0 is false, so the grade comes from
    # the argmax. Comparing with the clamped value (0 >= 0) would give ``unusable``.
    thresholds = Thresholds(type_threshold=0.5, unusable_threshold=0.0, grade_review_threshold=0.6)
    decision = _decide([0.9, 0.05, 0.05], [1.0000005, 0.0, 0.0, 0.0, -5e-7], thresholds=thresholds)
    assert decision.grade is Grade.PERFECT
    assert decision.grade_confidence == 1.0
    assert decision.grade_score == 0.0


def test_values_inside_the_ranges_are_not_changed() -> None:  # CA-04 values stay exact
    decision = _decide([0.6, 0.3, 0.1], [0.0, 0.7, 0.1, 0.1, 0.1])
    assert decision.type_confidence == 0.6
    assert decision.grade_confidence == 0.7
    assert decision.grade_score == pytest.approx(1.6, abs=1e-9)


@pytest.mark.parametrize(
    ("type_probs", "grade_probs"),
    [
        ([0.98, 0.01, 0.01], SOFTMAX_UNUSABLE),
        ([1.0000009, 0.0, 0.0], GOOD),
        ([0.9, 0.05, 0.05], [1.0000005, -5e-7, 0.0, 0.0, 0.0]),
        ([0.0, 0.0, 1.0000009], GOOD),
        ([0.1, 0.1, 0.8], GOOD),
        ([0.45, 0.30, 0.25], GOOD),
        ([0.9, 0.05, 0.05], [0.45, 0.05, 0.05, 0.05, 0.4]),
        ([0.05, 0.9, 0.05], GOOD),
    ],
)
def test_decision_is_accepted_by_the_contract(type_probs, grade_probs) -> None:
    decision = _decide(type_probs, grade_probs)
    InspectionCreate(
        inspection_id="6f1c3c8e-4b8a-4f57-9a2c-1a2b3c4d5e6f",
        device_id="edge-01",
        lot_id="L-001",
        inspected_at="2026-10-01T12:00:00+00:00",
        object_type=decision.object_type,
        grade=decision.grade,
        grade_score=decision.grade_score,
        type_confidence=decision.type_confidence,
        grade_confidence=decision.grade_confidence,
        needs_review=decision.needs_review,
        model_version="dummy-v1",
        model_sha256="a" * 64,
        latency_ms=3,
        source="live",
    )


@pytest.mark.parametrize(
    "values",
    [
        (1.2, 0.4, 0.6),
        (0.5, -0.01, 0.6),
        (0.5, 0.4, math.nan),
        (0.5, 0.4, math.inf),
        (True, 0.4, 0.6),
        ("0.5", 0.4, 0.6),
        (None, 0.4, 0.6),
    ],
)
def test_thresholds_must_be_in_the_unit_interval(values: tuple) -> None:
    with pytest.raises(ValueError, match="must be a number in"):
        Thresholds(*values)


def test_thresholds_accept_the_bounds_and_store_floats() -> None:
    thresholds = Thresholds(0, 1, np.float32(0.5))
    assert thresholds == Thresholds(0.0, 1.0, 0.5)
    assert all(type(getattr(thresholds, name)) is float for name in THRESHOLD_NAMES)
