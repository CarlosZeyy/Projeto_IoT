"""Author tests for the torch-free helpers of qc_ml.train (SPEC-012 §4.2; CA-04, CA-05)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from qc_ml.errors import TrainError
from qc_ml.train import EarlyStopper, grade_class_weights, is_better, library_versions

COUNTS = {"perfect": 100, "good": 100, "fair": 100, "poor": 100}


def test_ca04_weights_when_a_grade_is_below_60_percent_of_the_mean() -> None:
    weights = grade_class_weights({**COUNTS, "unusable": 40})
    assert weights == pytest.approx([0.88, 0.88, 0.88, 0.88, 2.2], abs=1e-9)
    assert grade_class_weights({**COUNTS, "unusable": 55}) is None
    with pytest.raises(TrainError):
        grade_class_weights({**COUNTS, "unusable": 0})


def test_weights_missing_or_unknown_grade() -> None:
    with pytest.raises(TrainError, match="unusable"):
        grade_class_weights(COUNTS)
    with pytest.raises(TrainError, match="unknown"):
        grade_class_weights({**COUNTS, "unusable": 10, "broken": 3})


def test_ca05_early_stopper() -> None:
    stopper = EarlyStopper(patience=5, min_delta=1e-4)
    decisions = [stopper.step(q) for q in [0.50, 0.60, 0.60, 0.60, 0.60, 0.60, 0.60]]
    assert decisions == [False] * 6 + [True]
    assert stopper.best_epoch == 2
    assert stopper.best_value == pytest.approx(0.60)


def test_early_stopper_min_delta_and_undefined_qwk() -> None:
    stopper = EarlyStopper(patience=2, min_delta=0.01)
    assert stopper(None) is False  # -1
    assert stopper(0.005) is False  # improvement over -1
    assert stopper(0.010) is False  # +0.005 <= min_delta: no improvement
    assert stopper(0.012) is True
    assert stopper.best_epoch == 2
    restored = EarlyStopper.from_state(stopper.state_dict())
    assert restored.state_dict() == stopper.state_dict()
    with pytest.raises(ValueError):
        EarlyStopper(patience=0)


def test_best_epoch_rule() -> None:
    a = {"epoch": 1, "val_grade_qwk": 0.5, "val_loss": 1.0}
    assert is_better(a, None)
    assert is_better({"epoch": 2, "val_grade_qwk": 0.6, "val_loss": 9.0}, a)
    assert is_better({"epoch": 2, "val_grade_qwk": 0.5, "val_loss": 0.9}, a)  # tie -> lower loss
    assert not is_better({"epoch": 2, "val_grade_qwk": 0.5, "val_loss": 1.0}, a)  # -> earlier
    assert not is_better({"epoch": 2, "val_grade_qwk": None, "val_loss": 0.1}, a)  # None = -1
    assert is_better(
        {"epoch": 2, "val_grade_qwk": -0.5, "val_loss": 1.0}, {**a, "val_grade_qwk": None}
    )


def test_library_versions_keys() -> None:
    versions = library_versions()
    assert set(versions) == {
        "python", "torch", "torchvision", "timm", "numpy", "scikit-learn", "onnx",
        "onnxruntime", "coral-pytorch", "qc-preprocess", "qc-ml",
    }  # fmt: skip
    assert versions["numpy"] and versions["qc-ml"]


def test_train_helpers_import_without_torch() -> None:
    code = (
        "import sys\n"
        "sys.modules['torch'] = None\n"
        "from qc_ml.train import TrainConfig, ConfigError, TrainError, EarlyStopper\n"
        "from qc_ml.train import grade_class_weights, train\n"
        "counts = dict.fromkeys(['perfect', 'good', 'fair', 'poor', 'unusable'], 1)\n"
        "assert grade_class_weights(counts) is None\n"
        "try:\n"
        "    train(None)\n"
        "except TrainError as exc:\n"
        "    assert 'train extra' in str(exc)\n"
        "else:\n"
        "    raise AssertionError('no TrainError')\n"
        "print('ok')\n"
    )  # fmt: skip
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
