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


# SPEC-031 §4.2: probabilities must be finite and in [0, 1].


def _two_images(**overrides) -> dict:
    fields = {
        "split": "val",
        "image_paths": ["raw/S-001/a.jpg", "raw/N-002/b.jpg"],
        "type_probs": np.array([[0.7, 0.2, 0.1], [0.1, 0.8, 0.1]]),
        "grade_probs": np.array([[0.6, 0.1, 0.1, 0.1, 0.1], [0.1, 0.1, 0.1, 0.1, 0.6]]),
        "true_type_idx": [0, 1],
        "true_grade_idx": [0, 4],
    }
    fields.update(overrides)
    return fields


@pytest.mark.parametrize(
    ("field", "index", "value"),
    [
        ("type_probs", (0, 0), np.nan),
        ("grade_probs", (1, 2), np.inf),
        ("type_probs", (0, 1), -0.01),
        ("grade_probs", (0, 4), 1.01),
        ("type_probs", (1, 2), -np.inf),
        ("grade_probs", (1, 0), 1.0 + 1e-12),
        ("grade_probs", (0, 0), -1e-300),
    ],
)
def test_predictions_refuse_invalid_probabilities(field: str, index: tuple, value: float) -> None:
    fields = _two_images()
    probs = fields[field].copy()
    probs[index] = value
    fields[field] = probs
    with pytest.raises(ValueError, match=field) as info:
        Predictions(**fields)
    message = str(info.value)
    other = "grade_probs" if field == "type_probs" else "type_probs"
    assert other not in message
    assert "raw/" not in message and str(value) not in message


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_predictions_accept_exact_bounds(value: float) -> None:
    fields = _two_images()
    fields["type_probs"] = np.full((2, 3), value)
    fields["grade_probs"] = np.full((2, 5), value)
    preds = Predictions(**fields)
    assert len(preds) == 2 and preds.type_probs.dtype == np.float64


def test_predictions_accept_float32_softmax_rounding() -> None:
    logits = np.array([[50.0, -50.0, 0.0], [0.0, 0.0, 0.0]], dtype=np.float32)
    exp = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs = (exp / exp.sum(axis=1, keepdims=True)).astype(np.float32)
    preds = Predictions(**_two_images(type_probs=probs))
    assert preds.type_probs.max() <= 1.0


def test_predictions_accept_empty() -> None:
    preds = Predictions("test", [], np.zeros((0, 3)), np.zeros((0, 5)), [], [])
    assert len(preds) == 0
    preds = Predictions("test", [], [], [], [], [])
    assert preds.type_probs.shape == (0, 0) and preds.grade_probs.shape == (0, 5)
