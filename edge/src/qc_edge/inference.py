"""Inference interface of the edge (SPEC-007 section 4.2).

The real ``OnnxInferencer`` and the decision rule come with SPEC-008. Here there is only the
``Inferencer`` protocol and ``StubInferencer``, used by ``qc-edge --stub-model`` and by tests.
A stub result is never published to the cloud (R-06).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from PIL import Image

from qc_contracts import Grade, ObjectType

STUB_MODEL_VERSION = "stub-v0"
STUB_MODEL_SHA256 = "0" * 64


@dataclass(frozen=True)
class ModelInfo:
    """Identity of the loaded model, sent in every inspection."""

    model_version: str
    model_sha256: str


@dataclass(frozen=True)
class InferenceResult:
    """Model output after the decision rule, already in contract terms."""

    object_type: ObjectType
    grade: Grade | None
    grade_score: float | None
    type_confidence: float
    grade_confidence: float | None
    needs_review: bool
    latency_ms: int


class InferenceError(Exception):
    """The model could not produce a result for an image that was valid."""


class Inferencer(Protocol):
    @property
    def model_info(self) -> ModelInfo: ...

    def infer(self, image: Image.Image) -> InferenceResult:
        """Classify ``image``, already validated by ``qc_preprocess.load_image``."""
        ...


DEFAULT_STUB_RESULT = InferenceResult(
    object_type=ObjectType.SCREW,
    grade=Grade.GOOD,
    grade_score=1.0,
    type_confidence=0.9,
    grade_confidence=0.8,
    needs_review=False,
    latency_ms=0,
)


class StubInferencer:
    """Development inferencer: always returns the same result and counts its calls.

    ``model_info`` is ``ModelInfo("stub-v0", "0" * 64)``. ``calls`` is the number of ``infer``
    calls so far (thread-safe).
    """

    def __init__(self, result: InferenceResult | None = None) -> None:
        self._result = result if result is not None else DEFAULT_STUB_RESULT
        self._model_info = ModelInfo(STUB_MODEL_VERSION, STUB_MODEL_SHA256)
        self._calls = 0
        self._lock = threading.Lock()

    @property
    def model_info(self) -> ModelInfo:
        return self._model_info

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    def infer(self, image: Image.Image) -> InferenceResult:
        with self._lock:
            self._calls += 1
        return self._result
