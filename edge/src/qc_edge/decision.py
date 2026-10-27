"""Decision rule of the edge (SPEC-008 section 4.1, docs/architecture.md section 6.2, step 4).

``decide`` is a pure function: model probabilities + labels + thresholds -> ``Decision`` in
contract terms. The comparisons are exactly the ones of the SPEC (strict ``<`` for
``type_threshold``, ``>=`` for ``unusable_threshold``) and always use the raw probabilities, never
rounded nor clamped. Only after every comparison are the returned numbers clamped to the ranges of
the contract (section 4.1, item 6): the confidences to ``[0, 1]`` and ``grade_score`` to
``[0, 4]``. Item 1 accepts values slightly outside ``[0, 1]``, and a float32 ``Softmax`` alone
gives ``p4 == 1.0`` with ``p3 > 0`` (``sum(i * p_i) > 4``), which ``InspectionCreate`` would refuse.
The clamp never changes ``object_type``, ``grade`` nor ``needs_review``.

SPEC-016 section 4.4 (ADR-021): a decided type listed in ``labels.ungraded_object_types`` (a
hand tool the model does not grade, or a power tool, which is always listed there: SPEC-021 and
the load rule of ``OnnxInferencer``) comes out with ``grade``, ``grade_score`` and
``grade_confidence`` ``None``, and ``needs_review`` depends only on the type confidence. The
grade groups of the contract are checked again by ``InspectionCreate``.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Sequence
from dataclasses import dataclass, fields

from qc_contracts import Grade, ObjectType
from qc_edge.inference import InferenceError

REVIEW_MARGIN = 0.10
# Index of ``unusable`` in ``grade_probs`` (the grades are always in severity order).
UNUSABLE_INDEX = 4
GRADE_COUNT = 5
# Contract ranges of the returned numbers (docs/architecture.md section 3.2).
MAX_GRADE_SCORE = float(GRADE_COUNT - 1)
# Model class that always maps to ``ObjectType.UNKNOWN`` (docs/architecture.md section 3.1).
OTHER_LABEL = "other"
# Tolerances of the output validation (SPEC-008 section 4.1, item 1).
VALUE_TOLERANCE = 1e-6
SUM_TOLERANCE = 1e-3


class InvalidModelOutputError(InferenceError):
    """The model returned probabilities that break the rules of section 4.1, item 1."""


def _check_unit_interval(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{name} must be a number in [0, 1]")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be a number in [0, 1]")
    return number


@dataclass(frozen=True)
class Thresholds:
    """Decision thresholds, each one a finite number in ``[0, 1]`` (``ValueError`` otherwise)."""

    type_threshold: float
    unusable_threshold: float
    grade_review_threshold: float

    def __post_init__(self) -> None:
        for field in fields(self):
            value = _check_unit_interval(field.name, getattr(self, field.name))
            object.__setattr__(self, field.name, value)


THRESHOLD_NAMES: tuple[str, ...] = tuple(field.name for field in fields(Thresholds))


@dataclass(frozen=True)
class ModelLabels:
    """Class order of the model outputs (``labels.json``).

    ``ungraded_object_types`` lists the types of the model that it does not grade (ADR-021,
    SPEC-016 section 4.4); empty by default. A list given here is stored as a tuple. The rules
    of its content are checked when ``labels.json`` is loaded (``OnnxInferencer``).
    """

    object_types: tuple[str, ...]
    grades: tuple[str, ...]
    ungraded_object_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("object_types", "grades", "ungraded_object_types"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True)
class Decision:
    """Result of the decision rule, already in contract terms."""

    object_type: ObjectType
    grade: Grade | None
    grade_score: float | None
    type_confidence: float
    grade_confidence: float | None
    needs_review: bool


def _probabilities(name: str, values: Sequence[float], expected_len: int) -> list[float]:
    """Section 4.1, item 1: length, finite values in ``[0, 1]`` and sum ``1 +- 1e-3``."""
    try:
        size = len(values)
    except TypeError:
        raise InvalidModelOutputError(f"{name} is not a sequence") from None
    if size != expected_len:
        raise InvalidModelOutputError(f"{name} has {size} values, expected {expected_len}")
    try:
        probs = [float(value) for value in values]
    except (TypeError, ValueError):
        raise InvalidModelOutputError(f"{name} has a non-numeric value") from None
    for prob in probs:
        if not math.isfinite(prob):
            raise InvalidModelOutputError(f"{name} has a non-finite value")
        if prob < -VALUE_TOLERANCE or prob > 1.0 + VALUE_TOLERANCE:
            raise InvalidModelOutputError(f"{name} has a value outside [0, 1]")
    if abs(math.fsum(probs) - 1.0) > SUM_TOLERANCE:
        raise InvalidModelOutputError(f"{name} does not sum to 1")
    return probs


def _argmax(values: list[float]) -> int:
    """Index of the largest value; a tie goes to the smallest index."""
    best = 0
    for index in range(1, len(values)):
        if values[index] > values[best]:
            best = index
    return best


def _clamp(value: float, upper: float) -> float:
    """``value`` limited to ``[0, upper]`` (section 4.1, item 6)."""
    return min(upper, max(0.0, value))


def decide(
    type_probs: Sequence[float],
    grade_probs: Sequence[float],
    labels: ModelLabels,
    thresholds: Thresholds,
) -> Decision:
    """Apply the decision rule of SPEC-008 section 4.1 to one image.

    Raises:
        InvalidModelOutputError: a vector with the wrong length (``len(labels.object_types)``
            types, 5 grades), a non-finite value or one outside ``[0, 1]`` (tolerance 1e-6), or
            a sum outside ``1 +- 1e-3``.

    The thresholds are compared with the raw probabilities; only the returned ``type_confidence``,
    ``grade_confidence`` (``[0, 1]``) and ``grade_score`` (``[0, 4]``) are clamped afterwards.
    """
    types = _probabilities("type_probs", type_probs, len(labels.object_types))
    grades = _probabilities("grade_probs", grade_probs, GRADE_COUNT)

    type_index = _argmax(types)
    type_confidence = types[type_index]
    label = labels.object_types[type_index]

    if label == OTHER_LABEL or type_confidence < thresholds.type_threshold:
        object_type = ObjectType.UNKNOWN
        grade: Grade | None = None
        grade_score: float | None = None
        grade_confidence: float | None = None
    elif label in labels.ungraded_object_types:
        # A type the model does not grade (SPEC-016 section 4.4): known type, no grade.
        object_type = ObjectType(label)
        grade = None
        grade_score = None
        grade_confidence = None
    else:
        object_type = ObjectType(label)
        if grades[UNUSABLE_INDEX] >= thresholds.unusable_threshold:
            grade_index = UNUSABLE_INDEX
            grade = Grade.UNUSABLE
        else:
            grade_index = _argmax(grades)
            grade = Grade(labels.grades[grade_index])
        grade_confidence = grades[grade_index]
        grade_score = sum(index * prob for index, prob in enumerate(grades))

    needs_review = type_confidence < thresholds.type_threshold + REVIEW_MARGIN or (
        grade_confidence is not None and grade_confidence < thresholds.grade_review_threshold
    )
    # Section 4.1, item 6: clamp to the contract ranges only after every comparison above.
    return Decision(
        object_type=object_type,
        grade=grade,
        grade_score=None if grade_score is None else _clamp(grade_score, MAX_GRADE_SCORE),
        type_confidence=_clamp(type_confidence, 1.0),
        grade_confidence=None if grade_confidence is None else _clamp(grade_confidence, 1.0),
        needs_review=needs_review,
    )
