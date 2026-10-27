"""``PartsDataset``: manifest rows -> tensors for training (SPEC-011 section 4.5).

Requires the ``train`` extra (torch). Training: ``qc_ml.augment.train_transform`` with
``rng = np.random.default_rng([seed, epoch, i])``, then ``qc_preprocess.preprocess``. Evaluation
(``train=False``): **only** ``qc_preprocess.preprocess`` (ADR-004), bit-identical to the edge.

SPEC-016 section 4.8: the grade index is ``qc_ml.data.grade_target`` (``-1`` for ``other``, for
the types of ``labels.ungraded_object_types`` and for a row without grade).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

from qc_contracts import GRADE_ORDER
from qc_ml.augment import train_transform
from qc_ml.data import ModelLabels, grade_target
from qc_preprocess import PreprocessParams, load_image, preprocess

NO_GRADE_INDEX = -1
GRADE_VALUES: tuple[str, ...] = tuple(g.value for g in GRADE_ORDER)


class LabelsLike(Protocol):
    """Anything with the class order of the type head (e.g. ``qc_ml.data.ModelLabels``).

    ``ungraded_object_types`` is optional (``()`` when the object has no such attribute).
    """

    object_types: tuple[str, ...] | list[str]


class PartsDataset(Dataset):
    """Items are ``(float32 tensor [3, crop, crop], type_idx, grade_idx)``.

    ``type_idx`` is the position of ``object_type`` in ``labels.object_types``; ``grade_idx`` the
    position of the grade in ``qc_contracts.Grade`` order, or ``-1`` when the grade loss ignores
    the row (the mask of SPEC-012; ``grade_target`` of SPEC-016).
    """

    def __init__(
        self,
        frame: pd.DataFrame,
        dataset_dir: Path | str,
        labels: LabelsLike,
        params: PreprocessParams,
        *,
        train: bool,
        seed: int = 42,
    ) -> None:
        self.frame = frame.reset_index(drop=True)
        self.dataset_dir = Path(dataset_dir)
        self.object_types = list(labels.object_types)
        self.labels = ModelLabels(
            object_types=tuple(labels.object_types),
            grades=GRADE_VALUES,
            ungraded_object_types=tuple(getattr(labels, "ungraded_object_types", ())),
        )
        self.params = params
        self.train = train
        self.seed = seed
        self.epoch = 0
        unknown = sorted(set(self.frame["object_type"]) - set(self.object_types))
        if unknown:
            raise ValueError(f"object types not in labels: {', '.join(unknown)}")

    def set_epoch(self, epoch: int) -> None:
        """Select the augmentation stream of ``epoch`` (training only)."""
        if epoch < 0:
            raise ValueError("epoch must be >= 0")
        self.epoch = epoch

    def __len__(self) -> int:
        return len(self.frame)

    def grade_index(self, i: int) -> int:
        grade = self.frame.at[i, "grade"]
        if grade is not None and pd.isna(grade):
            grade = None
        target = grade_target(str(self.frame.at[i, "object_type"]), grade, self.labels)
        return NO_GRADE_INDEX if target is None else target

    def __getitem__(self, i: int) -> tuple[torch.Tensor, int, int]:
        if not 0 <= i < len(self.frame):
            raise IndexError(i)
        row = self.frame.iloc[i]
        img = load_image(self.dataset_dir / str(row["image_path"]))
        if self.train:
            img = train_transform(img, np.random.default_rng([self.seed, self.epoch, i]))
        x = preprocess(img, self.params)[0]
        tensor = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))
        type_idx = self.object_types.index(str(row["object_type"]))
        return tensor, type_idx, self.grade_index(i)
