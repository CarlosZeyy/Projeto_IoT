"""ONNX inference over the rows of one split (SPEC-012 section 4.5).

``OnnxModel`` checks ``model.onnx`` against ``model.sha256`` and runs it with onnxruntime on the
CPU. The images go through ``qc_preprocess`` only (``load_image`` + ``preprocess`` with the
``preprocessing.json`` of the model), exactly as on the edge (ADR-004).

No torch here (CA-27).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import onnxruntime as ort
import pandas as pd

from qc_ml.artifacts import (
    LABELS_FILE,
    PREPROCESSING_FILE,
    load_labels,
    read_verified_model,
)
from qc_ml.data import ModelLabels
from qc_ml.errors import ModelArtifactError
from qc_preprocess import PreprocessParams, load_image, preprocess

SplitName = Literal["train", "val", "test"]
SPLITS: tuple[str, ...] = ("train", "val", "test")
INPUT_NAME = "image"
OUTPUT_NAMES: tuple[str, str] = ("type_probs", "grade_probs")
DEFAULT_BATCH = 16


@dataclass(frozen=True)
class Predictions:
    """Model outputs and true labels of the images of one split.

    ``type_probs`` is ``[N, T]`` and ``grade_probs`` ``[N, 5]`` (float64); ``true_type_idx`` is
    the position of the true ``object_type`` in ``labels.object_types``; ``true_grade_idx`` the
    position of the true grade, or ``-1`` without grade. The constructor converts sequences to
    numpy arrays and checks the shapes; every probability must be finite and in ``[0, 1]``
    (``ValueError`` otherwise, naming only the field).
    """

    split: str
    image_paths: tuple[str, ...]
    type_probs: np.ndarray
    grade_probs: np.ndarray
    true_type_idx: np.ndarray
    true_grade_idx: np.ndarray

    def __post_init__(self) -> None:
        if self.split not in SPLITS:
            raise ValueError(f"split must be one of {', '.join(SPLITS)}, got {self.split!r}")
        paths = tuple(str(p) for p in self.image_paths)
        type_probs = np.asarray(self.type_probs, dtype=np.float64)
        grade_probs = np.asarray(self.grade_probs, dtype=np.float64)
        true_type = np.asarray(self.true_type_idx, dtype=np.int64).reshape(-1)
        true_grade = np.asarray(self.true_grade_idx, dtype=np.int64).reshape(-1)
        n = len(paths)
        if n == 0 and type_probs.ndim == 1:
            type_probs = type_probs.reshape(0, 0)
        if n == 0 and grade_probs.ndim == 1:
            grade_probs = grade_probs.reshape(0, 5)
        if type_probs.ndim != 2 or type_probs.shape[0] != n:
            raise ValueError(f"type_probs must have shape [{n}, T], got {type_probs.shape}")
        if grade_probs.ndim != 2 or grade_probs.shape != (n, 5):
            raise ValueError(f"grade_probs must have shape [{n}, 5], got {grade_probs.shape}")
        if true_type.shape != (n,) or true_grade.shape != (n,):
            raise ValueError("true_type_idx and true_grade_idx must have one value per image")
        for name, probs in (("type_probs", type_probs), ("grade_probs", grade_probs)):
            # Fail loud before thresholds/metrics are computed from a broken model (SPEC-031).
            if not np.isfinite(probs).all():
                raise ValueError(f"{name} has non-finite values")
            if probs.size and (probs.min() < 0.0 or probs.max() > 1.0):
                raise ValueError(f"{name} has values outside [0, 1]")
        object.__setattr__(self, "image_paths", paths)
        object.__setattr__(self, "type_probs", type_probs)
        object.__setattr__(self, "grade_probs", grade_probs)
        object.__setattr__(self, "true_type_idx", true_type)
        object.__setattr__(self, "true_grade_idx", true_grade)

    def __len__(self) -> int:
        return len(self.image_paths)


def true_indices(frame: pd.DataFrame, labels: ModelLabels) -> tuple[np.ndarray, np.ndarray]:
    """``(true_type_idx, true_grade_idx)`` of the rows of ``frame`` (``-1`` without grade)."""
    object_types = list(labels.object_types)
    grades = list(labels.grades)
    unknown = sorted(set(frame["object_type"]) - set(object_types))
    if unknown:
        raise ValueError(f"object types not in labels: {', '.join(map(str, unknown))}")
    type_idx = [object_types.index(str(t)) for t in frame["object_type"]]
    grade_idx = [
        -1 if g is None or (isinstance(g, float) and np.isnan(g)) else grades.index(str(g))
        for g in frame["grade"]
    ]
    return np.asarray(type_idx, dtype=np.int64), np.asarray(grade_idx, dtype=np.int64)


class OnnxModel:
    """A model directory loaded for inference on the CPU.

    Raises:
        ModelArtifactError: ``model.onnx``/``model.sha256`` missing or different, or invalid
            ``labels.json``/``preprocessing.json``.
    """

    def __init__(self, model_dir: Path | str) -> None:
        self.model_dir = Path(model_dir)
        data, digest = read_verified_model(self.model_dir)
        self.sha256 = digest
        self.labels = load_labels(self.model_dir / LABELS_FILE)
        try:
            self.params = PreprocessParams.from_json(self.model_dir / PREPROCESSING_FILE)
        except FileNotFoundError:
            raise ModelArtifactError(f"{PREPROCESSING_FILE} not found in {model_dir}") from None
        except ValueError as exc:
            raise ModelArtifactError(f"invalid {PREPROCESSING_FILE}: {exc}") from exc
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(
            data, sess_options=options, providers=["CPUExecutionProvider"]
        )
        inputs = [i.name for i in self.session.get_inputs()]
        outputs = [o.name for o in self.session.get_outputs()]
        if inputs != [INPUT_NAME] or sorted(outputs) != sorted(OUTPUT_NAMES):
            raise ModelArtifactError(
                f"the model must have the input {INPUT_NAME!r} and the outputs "
                f"{', '.join(OUTPUT_NAMES)}; got {inputs} -> {outputs}"
            )

    def run(self, batch: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``(type_probs, grade_probs)`` of a preprocessed ``float32 [N, 3, H, W]`` batch."""
        type_probs, grade_probs = self.session.run(
            list(OUTPUT_NAMES), {INPUT_NAME: np.ascontiguousarray(batch, dtype=np.float32)}
        )
        return type_probs, grade_probs

    def load_input(self, path: Path | str) -> np.ndarray:
        """``float32 [1, 3, crop, crop]`` of one image file (``qc_preprocess`` only)."""
        return preprocess(load_image(Path(path)), self.params)

    def predict_paths(
        self, paths: Sequence[Path | str], batch_size: int = DEFAULT_BATCH
    ) -> tuple[np.ndarray, np.ndarray]:
        n_types = len(self.labels.object_types)
        type_out: list[np.ndarray] = [np.zeros((0, n_types))]
        grade_out: list[np.ndarray] = [np.zeros((0, 5))]
        for start in range(0, len(paths), batch_size):
            chunk = paths[start : start + batch_size]
            batch = np.concatenate([self.load_input(p) for p in chunk], axis=0)
            type_probs, grade_probs = self.run(batch)
            type_out.append(type_probs.astype(np.float64))
            grade_out.append(grade_probs.astype(np.float64))
        return np.concatenate(type_out, axis=0), np.concatenate(grade_out, axis=0)

    def predict(
        self,
        frame: pd.DataFrame,
        dataset_dir: Path | str,
        split: SplitName,
        batch_size: int = DEFAULT_BATCH,
    ) -> Predictions:
        """Predictions for the rows of ``frame`` (the rows of ``split``, from ``rows_for``)."""
        dataset_dir = Path(dataset_dir)
        image_paths = [str(p) for p in frame["image_path"]]
        type_probs, grade_probs = self.predict_paths(
            [dataset_dir / p for p in image_paths], batch_size=batch_size
        )
        true_type, true_grade = true_indices(frame, self.labels)
        return Predictions(
            split=split,
            image_paths=tuple(image_paths),
            type_probs=type_probs,
            grade_probs=grade_probs,
            true_type_idx=true_type,
            true_grade_idx=true_grade,
        )
