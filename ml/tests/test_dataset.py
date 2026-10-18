"""Author tests for qc_ml.dataset.PartsDataset (SPEC-011 section 4.5); needs torch (extra train)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from qc_ml.data import DEFAULT_LABELS, load_manifest  # noqa: E402
from qc_ml.dataset import PartsDataset  # noqa: E402
from qc_preprocess import PreprocessParams, load_image, preprocess  # noqa: E402


def _index(df, **match) -> int:
    mask = np.ones(len(df), dtype=bool)
    for key, value in match.items():
        mask &= (df[key] == value).to_numpy()
    return int(np.flatnonzero(mask)[0])


def test_eval_items_are_the_shared_preprocessing(dataset: Path) -> None:
    df = load_manifest(dataset)
    params = PreprocessParams()
    ds = PartsDataset(df, dataset, DEFAULT_LABELS, params, train=False)
    i = _index(df, object_type="nut", grade="poor")
    x, type_idx, grade_idx = ds[i]
    assert x.shape == (3, 224, 224) and x.dtype == torch.float32
    expected = preprocess(load_image(dataset / df.loc[i, "image_path"]), params)[0]
    assert np.array_equal(x.numpy(), expected)
    assert (type_idx, grade_idx) == (1, 3)
    j = _index(df, object_type="other")
    assert ds[j][1:] == (2, -1)
    assert len(ds) == 88


def test_train_items_are_augmented_and_reproducible(dataset: Path) -> None:
    df = load_manifest(dataset)
    ds = PartsDataset(df, dataset, DEFAULT_LABELS, PreprocessParams(), train=True, seed=3)
    a, _, _ = ds[0]
    b, _, _ = ds[0]
    assert a.shape == (3, 224, 224) and torch.equal(a, b)
    ds.set_epoch(1)
    c, _, _ = ds[0]
    assert not torch.equal(a, c)
    plain = PartsDataset(df, dataset, DEFAULT_LABELS, PreprocessParams(), train=False)[0][0]
    assert not torch.equal(a, plain)


def test_unknown_type_and_bad_index(dataset: Path) -> None:
    df = load_manifest(dataset)

    class Labels:
        object_types = ("screw", "nut")

    with pytest.raises(ValueError):
        PartsDataset(df, dataset, Labels(), PreprocessParams(), train=False)
    ds = PartsDataset(df, dataset, DEFAULT_LABELS, PreprocessParams(), train=False)
    with pytest.raises(IndexError):
        ds[88]
    with pytest.raises(ValueError):
        ds.set_epoch(-1)
