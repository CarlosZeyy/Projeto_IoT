"""Author tests for qc_ml.predict and qc_ml.artifacts (SPEC-012 §4.5). No torch."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from qc_ml import split as split_mod
from qc_ml.artifacts import load_labels, read_model_sha256, write_model_sha256
from qc_ml.data import load_manifest
from qc_ml.errors import ModelArtifactError
from qc_ml.predict import OnnxModel, Predictions

TINY = Path(__file__).resolve().parent / "fixtures" / "tiny_model"


def test_predict_val_rows(split_dataset: tuple[Path, Path]) -> None:
    dataset_dir, split_file = split_dataset
    df = load_manifest(dataset_dir)
    rows = split_mod.rows_for(df, split_mod.load_split(split_file), "val")
    model = OnnxModel(TINY)
    preds = model.predict(rows, dataset_dir, "val")
    assert preds.split == "val" and len(preds) == len(rows)
    assert preds.type_probs.shape == (len(rows), 3) and preds.grade_probs.shape == (len(rows), 5)
    assert np.allclose(preds.type_probs.sum(axis=1), 1, atol=1e-5)
    others = rows["object_type"].to_numpy() == "other"
    assert (preds.true_grade_idx[others] == -1).all()
    assert (preds.true_type_idx[others] == 2).all()
    single = model.predict(rows.iloc[:3], dataset_dir, "val", batch_size=1)
    assert np.allclose(single.type_probs, preds.type_probs[:3], atol=1e-6)


def test_onnx_model_checks_the_sha(tmp_path: Path) -> None:
    copy = Path(shutil.copytree(TINY, tmp_path / "m"))
    write_model_sha256(copy, "0" * 64)
    with pytest.raises(ModelArtifactError, match="does not match"):
        OnnxModel(copy)
    (copy / "model.sha256").unlink()
    with pytest.raises(ModelArtifactError, match="model.sha256 not found"):
        OnnxModel(copy)


def test_onnx_model_checks_labels_and_preprocessing(tmp_path: Path) -> None:
    copy = Path(shutil.copytree(TINY, tmp_path / "m"))
    (copy / "labels.json").write_text(json.dumps({"object_types": ["screw"], "grades": []}))
    with pytest.raises(ModelArtifactError):
        OnnxModel(copy)
    shutil.copy(TINY / "labels.json", copy / "labels.json")
    (copy / "preprocessing.json").write_text("{}")
    with pytest.raises(ModelArtifactError, match="preprocessing"):
        OnnxModel(copy)


def test_sha256_file_format(tmp_path: Path) -> None:
    assert read_model_sha256(TINY) == (TINY / "model.sha256").read_text().strip()
    (tmp_path / "model.sha256").write_text("a" * 64)  # no newline
    with pytest.raises(ModelArtifactError):
        read_model_sha256(tmp_path)
    with pytest.raises(ModelArtifactError):
        write_model_sha256(tmp_path, "xyz")
    assert load_labels(TINY / "labels.json").object_types == ("screw", "nut", "other")


def test_predictions_validation() -> None:
    ok = Predictions("val", ["a"], [[0.5, 0.3, 0.2]], [[1, 0, 0, 0, 0]], [0], [0])
    assert isinstance(ok.type_probs, np.ndarray) and ok.image_paths == ("a",)
    with pytest.raises(ValueError, match="split"):
        Predictions("holdout", ["a"], [[1, 0, 0]], [[1, 0, 0, 0, 0]], [0], [0])
    with pytest.raises(ValueError):
        Predictions("val", ["a", "b"], [[1, 0, 0]], [[1, 0, 0, 0, 0]], [0], [0])
    with pytest.raises(ValueError):
        Predictions("val", ["a"], [[1, 0, 0]], [[1, 0, 0, 0]], [0], [0])
