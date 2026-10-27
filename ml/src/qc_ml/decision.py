"""Decision rule of ``docs/architecture.md`` section 6.2, step 4, vectorized (SPEC-012 4.5).

The edge has its own copy (``qc_edge.decision``, SPEC-008); a cross test compares both on random
vectors. The comparisons always use the raw probabilities: strict ``<`` for ``type_threshold``
and the review margin, ``>=`` for ``unusable_threshold``. Only after every comparison are the
returned numbers clamped to the contract ranges (confidences to ``[0, 1]``, ``grade_score`` to
``[0, 4]``). Ties in an argmax go to the smallest index, as in the edge.

SPEC-016 (ADR-021), as on the edge (SPEC-016 section 4.4): a decided type listed in
``labels.ungraded_object_types`` has no grade, and its ``needs_review`` looks only at the type
margin.

No torch, no sklearn here (CA-27).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np

from qc_ml.artifacts import as_labels
from qc_ml.data import ModelLabels
from qc_ml.errors import ModelArtifactError

REVIEW_MARGIN = 0.10
OTHER_LABEL = "other"
UNKNOWN = "unknown"
UNUSABLE = "unusable"
NO_GRADE_INDEX = -1


@dataclass(frozen=True, eq=False)
class Thresholds(Mapping[str, float]):
    """The three thresholds of ``decision.json``; also a read-only mapping of them.

    ``thresholds["type_threshold"]`` and ``thresholds.type_threshold`` are the same value, and
    ``dict(thresholds)`` is exactly the content of ``decision.json``.
    """

    type_threshold: float
    unusable_threshold: float
    grade_review_threshold: float

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{f.name} must be a number in [0, 1], got {value!r}")
            number = float(value)
            if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                raise ValueError(f"{f.name} must be a number in [0, 1], got {value!r}")
            object.__setattr__(self, f.name, number)

    def __getitem__(self, key: str) -> float:
        if key not in THRESHOLD_KEYS:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(THRESHOLD_KEYS)

    def __len__(self) -> int:
        return len(THRESHOLD_KEYS)

    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={getattr(self, k)!r}" for k in THRESHOLD_KEYS)
        return f"Thresholds({inner})"

    def to_dict(self) -> dict[str, float]:
        return {k: getattr(self, k) for k in THRESHOLD_KEYS}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Thresholds:
        """Exactly the three keys (``ModelArtifactError`` otherwise)."""
        if not isinstance(data, Mapping) or set(data) != set(THRESHOLD_KEYS):
            keys = sorted(data) if isinstance(data, Mapping) else data
            raise ModelArtifactError(
                f"decision must have exactly the keys {', '.join(THRESHOLD_KEYS)}, got {keys}"
            )
        try:
            return cls(**{k: data[k] for k in THRESHOLD_KEYS})
        except ValueError as exc:
            raise ModelArtifactError(str(exc)) from exc


THRESHOLD_KEYS: tuple[str, ...] = ("type_threshold", "unusable_threshold", "grade_review_threshold")


def as_thresholds(value: Thresholds | Mapping[str, Any]) -> Thresholds:
    return value if isinstance(value, Thresholds) else Thresholds.from_mapping(value)


def load_decision(path: Path | str) -> Thresholds:
    """Read ``decision.json`` (exactly the three keys)."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ModelArtifactError(f"{path.name} not found in {path.parent}") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelArtifactError(f"{path.name} is not valid JSON: {exc}") from exc
    return Thresholds.from_mapping(data)


def write_decision(path: Path, thresholds: Thresholds | Mapping[str, Any]) -> None:
    """Write ``decision.json`` with exactly the three keys."""
    data = as_thresholds(thresholds).to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Decisions:
    """Decision for each of the ``N`` images (arrays of length ``N``).

    ``object_types`` holds contract values (``screw``, ``nut``, a tool or ``unknown``); ``grades``
    the grade or ``None``; ``grade_idx`` is ``-1`` and ``grade_confidence``/``grade_score`` are
    ``NaN`` when there is no grade (``unknown`` or an ungraded type). ``unknown`` is the boolean
    mask of ``object_type == unknown``.
    """

    type_idx: np.ndarray
    object_types: tuple[str, ...]
    unknown: np.ndarray
    type_confidence: np.ndarray
    grade_idx: np.ndarray
    grades: tuple[str | None, ...]
    grade_confidence: np.ndarray
    grade_score: np.ndarray
    needs_review: np.ndarray

    def __len__(self) -> int:
        return len(self.type_idx)

    def record(self, i: int) -> dict[str, Any]:
        """Image ``i`` as a dict with ``None`` for the missing grade fields."""
        has_grade = self.grade_idx[i] >= 0
        return {
            "object_type": self.object_types[i],
            "grade": self.grades[i],
            "grade_score": float(self.grade_score[i]) if has_grade else None,
            "type_confidence": float(self.type_confidence[i]),
            "grade_confidence": float(self.grade_confidence[i]) if has_grade else None,
            "needs_review": bool(self.needs_review[i]),
        }


def _as_matrix(name: str, values: Any, width: int) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 1:
        array = array[np.newaxis, :]
    if array.ndim != 2 or array.shape[1] != width:
        raise ValueError(f"{name} must have shape [N, {width}], got {np.shape(values)}")
    return array


def apply_decision(
    type_probs: Any,
    grade_probs: Any,
    labels: ModelLabels | Mapping[str, Any] | None,
    thresholds: Thresholds | Mapping[str, Any],
) -> Decisions:
    """Apply the decision rule to ``[N, T]`` and ``[N, 5]`` probabilities (or one ``[T]``/``[5]``).

    1. ``type = argmax(type_probs)``; ``unknown`` if it is ``other`` or ``max < type_threshold``;
       then no grade. A type of ``labels.ungraded_object_types`` keeps its type and has no grade
       either (SPEC-016).
    2. ``grade = unusable`` if ``p_unusable >= unusable_threshold``, else ``argmax(grade_probs)``.
    3. ``grade_confidence = grade_probs[grade]``, ``grade_score = sum(i * p_i)``.
    4. ``needs_review = type_confidence < type_threshold + 0.10 or grade_confidence <
       grade_review_threshold`` (the second term only for an image with a grade).
    5. Clamp the confidences to ``[0, 1]`` and ``grade_score`` to ``[0, 4]``.
    """
    labels = as_labels(labels)
    thresholds = as_thresholds(thresholds)
    types = _as_matrix("type_probs", type_probs, len(labels.object_types))
    grades_p = _as_matrix("grade_probs", grade_probs, len(labels.grades))
    if len(types) != len(grades_p):
        raise ValueError("type_probs and grade_probs must have the same number of rows")
    n = len(types)
    unusable_index = labels.grades.index(UNUSABLE)
    other_index = labels.object_types.index(OTHER_LABEL)

    type_idx = np.argmax(types, axis=1) if n else np.zeros(0, dtype=np.int64)
    type_conf = types[np.arange(n), type_idx]
    unknown = (type_idx == other_index) | (type_conf < thresholds.type_threshold)
    ungraded_index = [
        k for k, t in enumerate(labels.object_types) if t in labels.ungraded_object_types
    ]
    no_grade = unknown | np.isin(type_idx, ungraded_index)

    argmax_grade = np.argmax(grades_p, axis=1) if n else np.zeros(0, dtype=np.int64)
    chosen = np.where(
        grades_p[:, unusable_index] >= thresholds.unusable_threshold, unusable_index, argmax_grade
    )
    grade_idx = np.where(no_grade, NO_GRADE_INDEX, chosen).astype(np.int64)
    raw_grade_conf = grades_p[np.arange(n), chosen]
    weights = np.arange(len(labels.grades), dtype=np.float64)
    raw_score = grades_p @ weights
    grade_conf = np.where(no_grade, np.nan, raw_grade_conf)
    grade_score = np.where(no_grade, np.nan, raw_score)

    needs_review = (type_conf < thresholds.type_threshold + REVIEW_MARGIN) | (
        ~no_grade & (raw_grade_conf < thresholds.grade_review_threshold)
    )
    object_types = tuple(
        UNKNOWN if unknown[i] else labels.object_types[int(type_idx[i])] for i in range(n)
    )
    grade_names = tuple(
        None if grade_idx[i] < 0 else labels.grades[int(grade_idx[i])] for i in range(n)
    )
    max_score = float(len(labels.grades) - 1)
    return Decisions(
        type_idx=type_idx.astype(np.int64),
        object_types=object_types,
        unknown=unknown,
        type_confidence=np.clip(type_conf, 0.0, 1.0),
        grade_idx=grade_idx,
        grades=grade_names,
        grade_confidence=np.clip(grade_conf, 0.0, 1.0),
        grade_score=np.clip(grade_score, 0.0, max_score),
        needs_review=needs_review,
    )


def decided_grade_idx(grade_probs: Any, unusable_threshold: float) -> np.ndarray:
    """Grade of each row by the rule of step 2 only (``unusable`` threshold, else argmax).

    Used by the thresholds and the grade metrics, which look at the grade independently of the
    predicted type (SPEC-012 sections 4.6 and 4.7).
    """
    probs = np.asarray(grade_probs, dtype=np.float64)
    if probs.ndim != 2 or probs.shape[1] != 5:
        raise ValueError(f"grade_probs must have shape [N, 5], got {probs.shape}")
    if not len(probs):
        return np.zeros(0, dtype=np.int64)
    unusable_index = 4
    return np.where(
        probs[:, unusable_index] >= unusable_threshold, unusable_index, np.argmax(probs, axis=1)
    ).astype(np.int64)
