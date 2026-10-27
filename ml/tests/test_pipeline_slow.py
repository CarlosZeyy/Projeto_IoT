"""Slow author tests of train -> export -> thresholds -> evaluate (SPEC-012; CA-07..10, CA-20).

Need torch and timm (extra ``train``); skipped in the CI. Synthetic data in ``tmp_path`` only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("timm")
onnx = pytest.importorskip("onnx")

import onnxruntime as ort  # noqa: E402

from qc_ml import pipeline as pipeline_mod  # noqa: E402
from qc_ml import split as split_mod  # noqa: E402
from qc_ml import train as train_mod  # noqa: E402
from qc_ml.config import load_config  # noqa: E402
from qc_ml.errors import ConfigError, ExportError  # noqa: E402
from qc_ml.parity import ParityResult  # noqa: E402
from qc_ml.synthetic import make_synthetic_dataset  # noqa: E402

pytestmark = pytest.mark.slow

MODEL_FILES = {
    "model.onnx",
    "model.sha256",
    "labels.json",
    "preprocessing.json",
    "decision.json",
    "metrics.json",
    "training_config.json",
    "parity_fixture.npz",
}
TRAINING_KEYS = {
    "model_version", "config", "deviations_from_defaults", "labels", "split_file",
    "split_sha256", "manifest_sha256", "grade_class_weights", "history", "best_epoch",
    "best_val_grade_qwk", "stopped_early", "versions", "device", "git_commit", "started_at",
    "finished_at", "smoke", "ungraded_object_types",
}  # fmt: skip
VERSION = "partqc-smoke-v1"


def _smoke_config(root: Path, data: Path, name: str = "run", **overrides) -> Path:
    config = {
        "model_version": VERSION,
        "dataset_dir": str(data / "ds"),
        "split_file": str(data / "splits" / "split_v1.csv"),
        "backbone": "mobilenetv3_small_050",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(root / name / "models"),
        "reports_root": str(root / name / "reports"),
        "checkpoints_root": str(root / name / "checkpoints"),
        **overrides,
    }
    path = root / f"{name}.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def smoke_data(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("smoke_data")
    make_synthetic_dataset(root / "ds", items_per_stratum=4)
    args = ["--dataset-dir", str(root / "ds"), "--splits-dir", str(root / "splits")]
    assert split_mod.main(args) == 0
    return root


@pytest.fixture(scope="module")
def smoke_run(smoke_data: Path, tmp_path_factory: pytest.TempPathFactory) -> dict:
    """One pipeline run with a spy on ``split.rows_for`` (CA-20)."""
    root = tmp_path_factory.mktemp("smoke_run")
    config_path = _smoke_config(root, smoke_data)
    config = load_config(config_path)
    calls: list[tuple[str, bool]] = []
    original = split_mod.rows_for

    def spy(df, split_df, which):
        calls.append((which, (config.model_dir / "decision.json").exists()))
        return original(df, split_df, which)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(split_mod, "rows_for", spy)
        assert pipeline_mod.main(["--config", str(config_path)]) == 0
    return {"config": config, "config_path": config_path, "calls": calls}


def test_ca07_every_artifact_exists(smoke_run: dict) -> None:
    config = smoke_run["config"]
    assert {p.name for p in config.model_dir.iterdir()} >= MODEL_FILES
    reports = {p.name for p in config.reports_dir.iterdir()}
    assert {"thresholds_report.json", "type_confusion.png", "grade_confusion.png"} <= reports
    assert (config.checkpoints_dir / "best.pt").is_file()
    assert (config.checkpoints_dir / "last.pt").is_file()


def test_ca08_training_config(smoke_run: dict, smoke_data: Path) -> None:
    config = smoke_run["config"]
    record = json.loads((config.model_dir / "training_config.json").read_text())
    assert set(record) == TRAINING_KEYS
    assert {"torch", "timm", "onnxruntime"} <= {k for k, v in record["versions"].items() if v}
    sha_line = (smoke_data / "splits" / "split_v1.sha256").read_text().split()[0]
    assert record["split_sha256"] == sha_line
    assert record["smoke"] is True and record["config"] == config.to_dict()
    assert [h["phase"] for h in record["history"]] == ["A", "B"]
    assert set(record["history"][0]) == {
        "epoch", "phase", "train_loss", "val_loss", "val_type_accuracy", "val_grade_qwk",
    }  # fmt: skip
    fields = {d["field"] for d in record["deviations_from_defaults"]}
    assert {"backbone", "pretrained", "epochs_a", "epochs_b_max", "smoke"} <= fields


def test_ca09_same_seed_same_history(smoke_run: dict, smoke_data: Path, tmp_path: Path) -> None:
    config_path = _smoke_config(tmp_path, smoke_data, name="again")
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    result = subprocess.run(
        [sys.executable, "-m", "qc_ml.pipeline", "--config", str(config_path)],
        capture_output=True, text=True, timeout=900, check=False, env=env,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]
    first = json.loads((smoke_run["config"].model_dir / "training_config.json").read_text())
    second = json.loads((load_config(config_path).model_dir / "training_config.json").read_text())
    for a, b in zip(first["history"], second["history"], strict=True):
        for key in ("train_loss", "val_loss", "val_grade_qwk"):
            if a[key] is None:
                assert b[key] is None
            else:
                assert a[key] == pytest.approx(b[key], abs=1e-6)


def test_ca10_onnx_model(smoke_run: dict) -> None:
    model_path = smoke_run["config"].model_dir / "model.onnx"
    model = onnx.load(str(model_path))
    onnx.checker.check_model(model)
    assert max(o.version for o in model.opset_import if o.domain in ("", "ai.onnx")) >= 17
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    assert [i.name for i in session.get_inputs()] == ["image"]
    assert [o.name for o in session.get_outputs()] == ["type_probs", "grade_probs"]
    for batch in (1, 3):
        x = np.random.default_rng(batch).normal(size=(batch, 3, 224, 224)).astype(np.float32)
        type_probs, grade_probs = session.run(None, {"image": x})
        assert type_probs.shape == (batch, 3) and grade_probs.shape == (batch, 5)
        assert np.allclose(type_probs.sum(axis=1), 1, atol=1e-5)
        assert np.allclose(grade_probs.sum(axis=1), 1, atol=1e-5)


def test_ca20_pipeline_requests_test_once(smoke_run: dict) -> None:
    calls = smoke_run["calls"]
    assert [c for c in calls if c[0] == "test"] == [("test", True)]
    first_test = calls.index(("test", True))
    assert all(which in ("train", "val") for which, _ in calls[:first_test])
    # train asks train + val, thresholds asks val: all before decision.json exists.
    assert calls[:3] == [("train", False), ("val", False), ("val", False)]


def test_resume_gives_the_same_history(smoke_data: Path, tmp_path: Path) -> None:
    overrides = {"epochs_b_max": 2}
    full = load_config(_smoke_config(tmp_path, smoke_data, "full", **overrides))
    expected = train_mod.train(full).training_config["history"]

    part = load_config(_smoke_config(tmp_path, smoke_data, "part", **overrides))
    original = train_mod.is_better

    class Stop(Exception):
        pass

    def interrupt(candidate, best):
        if candidate["epoch"] == 3:
            raise Stop  # dies before last.pt of epoch 3 is written
        return original(candidate, best)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(train_mod, "is_better", interrupt)
        with pytest.raises(Stop):
            train_mod.train(part)
    resumed = train_mod.train(part, resume=True).training_config["history"]
    assert [h["epoch"] for h in resumed] == [1, 2, 3]
    for a, b in zip(expected, resumed, strict=True):
        for key in ("train_loss", "val_loss"):
            assert a[key] == pytest.approx(b[key], abs=1e-6)

    other = load_config(_smoke_config(tmp_path, smoke_data, "part", epochs_b_max=3))
    with pytest.raises(ConfigError, match="same configuration"):
        train_mod.train(other, resume=True)


def test_export_parity_failure_deletes_the_model(
    smoke_run: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qc_ml import export as export_mod

    config = smoke_run["config"]
    target = tmp_path / "models" / VERSION
    shutil.copytree(config.checkpoints_dir, tmp_path / "checkpoints" / VERSION)
    data = json.loads(smoke_run["config_path"].read_text())
    data.update(
        models_root=str(tmp_path / "models"), checkpoints_root=str(tmp_path / "checkpoints")
    )
    config_path = tmp_path / "export.json"
    config_path.write_text(json.dumps(data))
    monkeypatch.setattr(
        export_mod, "check_parity", lambda _: ParityResult(False, 1.0, False, True, "forced")
    )
    assert export_mod.main(["--config", str(config_path)]) == 2
    assert not (target / "model.onnx").exists()
    with pytest.raises(ExportError, match="forced"):
        export_mod.run(load_config(config_path))
