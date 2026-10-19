"""Author tests for qc_ml.config / TrainConfig (SPEC-012 section 4.2, CA-06); no torch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qc_ml.config import SKILL_DEFAULTS, TrainConfig, config_from_dict, load_config
from qc_ml.errors import ConfigError

ROOT = Path(__file__).resolve().parents[2]
BASE = {"model_version": "partqc-mnv3-v1", "dataset_dir": "ml/data", "split_file": "s.csv"}


def test_repository_config_loads_with_the_skill_defaults() -> None:
    config = load_config(ROOT / "ml" / "configs" / "partqc-mnv3-v1.json")
    assert config.model_version == "partqc-mnv3-v1"
    assert config.deviations_from_defaults == []
    assert config.model_dir == Path("ml/models/partqc-mnv3-v1")
    assert config.reports_dir == Path("ml/reports/partqc-mnv3-v1")


def test_defaults_match_the_spec() -> None:
    config = TrainConfig(**BASE)
    assert (config.backbone, config.pretrained, config.grade_head) == (
        "mobilenetv3_large_100",
        True,
        "ce",
    )
    assert (config.seed, config.batch_size, config.epochs_a, config.epochs_b_max) == (42, 32, 8, 30)
    assert (config.lr_a, config.lr_b, config.unfreeze_last_blocks) == (1e-3, 1e-4, 2)
    assert (config.patience, config.min_delta, config.label_smoothing) == (5, 1e-4, 0.1)
    assert (config.lambda_grade, config.weight_decay, config.num_workers) == (1.0, 1e-4, 2)
    assert (config.models_root, config.reports_root, config.checkpoints_root) == (
        "ml/models",
        "ml/reports",
        "ml/checkpoints",
    )
    assert config.smoke is False


def test_ca06_epochs_a_out_of_range_needs_smoke() -> None:
    with pytest.raises(ConfigError, match="epochs_a"):
        config_from_dict({**BASE, "epochs_a": 12})
    config = config_from_dict({**BASE, "epochs_a": 12, "smoke": True})
    assert config.epochs_a == 12
    assert {"field": "epochs_a", "default": 8, "value": 12} in config.deviations_from_defaults


def test_ca06_invalid_model_version() -> None:
    with pytest.raises(ConfigError, match="model_version"):
        config_from_dict({**BASE, "model_version": "PartQC v1"})


@pytest.mark.parametrize(
    "version",
    ["partqc-v1", "partqc-mnv3-v", "partqc-MNV3-v1", "partqc-mnv3_x-v1", "x-partqc-mnv3-v1",
     "partqc-" + "a" * 40 + "-v1", "partqc-mnv3-v1\n"],
)  # fmt: skip
def test_model_version_patterns(version: str) -> None:
    with pytest.raises(ConfigError):
        config_from_dict({**BASE, "model_version": version})


@pytest.mark.parametrize("version", ["partqc-mnv3-v1", "partqc-effb0-corn-v12", "partqc-a-v0"])
def test_valid_model_versions(version: str) -> None:
    assert config_from_dict({**BASE, "model_version": version}).model_version == version


def test_backbone_list_outside_smoke() -> None:
    with pytest.raises(ConfigError, match="backbone"):
        config_from_dict({**BASE, "backbone": "resnet50"})
    assert config_from_dict({**BASE, "backbone": "efficientnet_b0"}).backbone == "efficientnet_b0"
    smoke = config_from_dict({**BASE, "backbone": "mobilenetv3_small_050", "smoke": True})
    assert smoke.backbone == "mobilenetv3_small_050"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("grade_head", "ordinal"),
        ("batch_size", 0),
        ("lr_a", 0),
        ("label_smoothing", 1.0),
        ("patience", 0),
        ("seed", -1),
        ("pretrained", "yes"),
        ("epochs_a", 7.0),
        ("batch_size", True),
    ],
)
def test_invalid_values(key: str, value: object) -> None:
    with pytest.raises(ConfigError, match=key):
        config_from_dict({**BASE, key: value})


def test_unknown_and_missing_keys() -> None:
    with pytest.raises(ConfigError, match="unknown keys"):
        config_from_dict({**BASE, "learning_rate": 0.1})
    with pytest.raises(ConfigError, match="split_file"):
        config_from_dict({"model_version": "partqc-mnv3-v1", "dataset_dir": "d"})
    with pytest.raises(ConfigError):
        config_from_dict(["not", "an", "object"])


def test_load_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(bad)
    good = tmp_path / "good.json"
    good.write_text(json.dumps({**BASE, "lr_b": 1}), encoding="utf-8")
    assert load_config(good).lr_b == 1.0


def test_deviations_list_only_hyperparameters() -> None:
    config = config_from_dict({**BASE, "lr_b": 5e-5, "models_root": "/tmp/m", "num_workers": 0})
    assert config.deviations_from_defaults == [{"field": "lr_b", "default": 1e-4, "value": 5e-5}]
    assert set(SKILL_DEFAULTS) >= {"backbone", "epochs_a", "label_smoothing", "smoke"}
