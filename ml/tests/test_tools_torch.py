"""Author tests of SPEC-016 section 4.8 that need torch (extra ``train``): the masked grade
target of ``PartsDataset``, the labels of the export and a smoke pipeline with hand tools.

Skipped in the CI (no torch). Synthetic data in ``tmp_path`` only.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("timm")
pytest.importorskip("onnx")

from qc_ml import export as export_mod  # noqa: E402
from qc_ml import pipeline as pipeline_mod  # noqa: E402
from qc_ml import split as split_mod  # noqa: E402
from qc_ml.config import load_config  # noqa: E402
from qc_ml.data import (  # noqa: E402
    DEFAULT_LABELS,
    GRADES,
    KNOWN_OBJECT_TYPES,
    TOOL_OBJECT_TYPES,
    ModelLabels,
    load_manifest,
)
from qc_ml.dataset import PartsDataset  # noqa: E402
from qc_ml.errors import ExportError  # noqa: E402
from qc_ml.synthetic import make_synthetic_dataset  # noqa: E402
from qc_preprocess import PreprocessParams  # noqa: E402

pytestmark = pytest.mark.slow

TOOLS_LABELS = ModelLabels(KNOWN_OBJECT_TYPES, GRADES, ("allen_key",))
VERSION = "partqc-smoketools-v1"


@pytest.fixture(scope="module")
def tools_data(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("tools_data")
    make_synthetic_dataset(root / "ds", items_per_stratum=4, tool_items_per_stratum=3)
    args = ["--dataset-dir", str(root / "ds"), "--splits-dir", str(root / "splits")]
    assert split_mod.main(args) == 0
    return root


def _index(df, object_type: str) -> int:
    return int(np.flatnonzero((df["object_type"] == object_type).to_numpy())[0])


def test_parts_dataset_masks_the_ungraded_tools(tools_data: Path) -> None:
    df = load_manifest(tools_data / "ds")
    ds = PartsDataset(df, tools_data / "ds", TOOLS_LABELS, PreprocessParams(), train=False)
    i = _index(df, "allen_key")
    _, type_idx, grade_idx = ds[i]
    assert type_idx == KNOWN_OBJECT_TYPES.index("allen_key") and grade_idx == -1
    j = _index(df, "pliers")
    assert ds.grade_index(j) == GRADES.index(df.at[j, "grade"])
    assert ds.grade_index(_index(df, "other")) == -1
    with pytest.raises(ValueError, match="not in labels"):
        PartsDataset(df, tools_data / "ds", DEFAULT_LABELS, PreprocessParams(), train=False)


def _config(root: Path, data: Path) -> Path:
    config = {
        "model_version": VERSION,
        "dataset_dir": str(data / "ds"),
        "split_file": str(data / "splits" / "split_v1.csv"),
        "backbone": "mobilenetv3_small_050",
        "pretrained": False,
        "epochs_a": 3,  # more than the SPEC-012 smoke: 8 types need distinct top-2 outputs
        "epochs_b_max": 2,
        "lr_a": 0.01,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(root / "models"),
        "reports_root": str(root / "reports"),
        "checkpoints_root": str(root / "checkpoints"),
    }
    path = root / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def tools_run(tools_data: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("tools_run")
    config_path = _config(root, tools_data)
    assert pipeline_mod.main(["--config", str(config_path)]) == 0
    return config_path


def test_pipeline_with_tools_records_the_model_types(tools_run: Path) -> None:
    config = load_config(tools_run)
    record = json.loads((config.model_dir / "training_config.json").read_text())
    # 3 items per tool x grade: no tool meets the grade criterion
    assert record["labels"] == {"object_types": list(KNOWN_OBJECT_TYPES), "grades": list(GRADES)}
    assert record["ungraded_object_types"] == list(TOOL_OBJECT_TYPES)
    labels = json.loads((config.model_dir / "labels.json").read_text())
    assert labels == {
        "object_types": list(KNOWN_OBJECT_TYPES),
        "grades": list(GRADES),
        "ungraded_object_types": list(TOOL_OBJECT_TYPES),
    }
    metrics = json.loads((config.model_dir / "metrics.json").read_text())
    assert np.asarray(metrics["type_confusion"]).shape == (8, 8)
    assert metrics["labels"] == labels
    assert metrics["tool_grade_metrics"] == {}
    best = torch.load(config.checkpoints_dir / "best.pt", map_location="cpu", weights_only=True)
    assert best["labels"] == labels


def test_standalone_export_reads_the_labels_of_the_checkpoint(tools_run: Path) -> None:
    config = load_config(tools_run)
    (config.model_dir / "labels.json").unlink()
    (config.model_dir / "training_config.json").rename(config.model_dir / "tc.json")
    export_mod.run(config)
    labels = json.loads((config.model_dir / "labels.json").read_text())
    assert labels["ungraded_object_types"] == list(TOOL_OBJECT_TYPES)
    (config.model_dir / "tc.json").rename(config.model_dir / "training_config.json")


def test_training_labels_sources(tools_run: Path, tmp_path: Path) -> None:
    config = load_config(tools_run)
    record = json.loads((config.model_dir / "training_config.json").read_text())
    # from training_config.json when the checkpoint has no labels (written before SPEC-016)
    assert export_mod.training_labels(config, {"model": {}}).ungraded_object_types == tuple(
        TOOL_OBJECT_TYPES
    )
    assert export_mod.training_labels(config, {"labels": dict(record["labels"])}) == ModelLabels(
        KNOWN_OBJECT_TYPES, GRADES
    )
    with pytest.raises(ExportError, match="invalid labels"):
        export_mod.training_labels(
            config, {"labels": {**record["labels"], "ungraded_object_types": ["screw"]}}
        )
    other = load_config(tools_run).__class__(
        **{**config.to_dict(), "models_root": str(tmp_path / "none")}
    )
    assert export_mod.training_labels(other, {"model": {}}) == DEFAULT_LABELS
