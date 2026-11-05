"""Floor of ``split_v1`` in the split CLI (SPEC-041 section 4.6, ADR-024). Synthetic data only."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from qc_ml import evaluate, split
from qc_ml.data import MANIFEST_COLUMNS, load_manifest
from qc_ml.synthetic import add_synthetic_item, make_synthetic_dataset

TINY_MODEL = Path(__file__).resolve().parent / "fixtures" / "tiny_model"
TINY_VERSION = "partqc-tiny-v1"


def read_rows(root: Path) -> list[dict[str, str]]:
    with (root / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(root: Path, rows: list[dict[str, str]]) -> None:
    with (root / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANIFEST_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture(scope="module")
def floor_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """33 items, 99 images: the numbers of the ADR-024 annex."""
    return make_synthetic_dataset(
        tmp_path_factory.mktemp("floor") / "ds", items_per_stratum=3, images_per_item=3
    )


@pytest.fixture
def floor_dataset(floor_template: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(floor_template, tmp_path / "ds"))


def _drop_item(root: Path, item_id: str) -> None:
    rows = read_rows(root)
    for row in rows:
        if row["item_id"] == item_id:
            (root / row["image_path"]).unlink()
    write_rows(root, [row for row in rows if row["item_id"] != item_id])


def _item_of(root: Path, object_type: str, grade: str) -> str:
    rows = read_rows(root)
    return next(
        r["item_id"] for r in rows if r["object_type"] == object_type and r["grade"] == grade
    )


def _cli(root: Path, splits: Path, *extra: str) -> int:
    return split.main(["--dataset-dir", str(root), "--splits-dir", str(splits), *extra])


def _external_registry(root: Path) -> tuple[str, str]:
    return "--external-sources", str(root / "external_sources.csv")


def test_ca01_exact_floor_passes_without_warnings(floor_dataset: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    assert _cli(floor_dataset, splits) == 0
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["counts"]["items"] == {"train": 11, "val": 11, "test": 11}
    assert meta["counts"]["images"] == {"train": 33, "val": 33, "test": 33}
    assert meta["warnings"] == []


def test_floor_problems_empty_at_the_floor(floor_dataset: Path) -> None:
    df = load_manifest(floor_dataset)
    assert split.floor_problems(df, split.make_split(df).frame) == []


def test_floor_problems_sorted_and_counts_only_own_items(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds", items_per_stratum=1, images_per_item=1, external_items_per_stratum=3
    )
    df = load_manifest(root, external_sources=root / "external_sources.csv")
    result = split.make_split(df, max_external_fraction=1.0)
    problems = split.floor_problems(df, result.frame)
    # SPEC-045 section 4.1: the floor is screw x 5 grades and other/none (no nut stratum)
    assert len(problems) == 6
    assert problems == sorted(problems)
    assert problems[0] == "other/none"
    assert not [p for p in problems if p.startswith("nut/")]


def test_floor_problems_uses_the_dominant_grade(tmp_path: Path) -> None:
    """A tied item counts only in the most severe grade: screw/perfect stays below the floor."""
    root = make_synthetic_dataset(tmp_path / "ds", items_per_stratum=3, images_per_item=2)
    rows = read_rows(root)
    for row in rows:
        if row["object_type"] == "screw" and row["grade"] == "perfect" and row["angle"] == "1":
            row["grade"] = "good"
    write_rows(root, rows)
    df = load_manifest(root)
    assert "screw/perfect" in split.floor_problems(df, split.make_split(df).frame)


def test_ca02_below_floor_refused_and_nothing_written(
    floor_dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    _drop_item(floor_dataset, _item_of(floor_dataset, "screw", "fair"))  # SPEC-045: no nut
    splits = tmp_path / "splits"
    assert _cli(floor_dataset, splits) == 2
    assert "split_v1 below the floor: screw/fair" in capfd.readouterr().err.splitlines()
    assert not list(splits.glob("split_v1.*"))


def test_ca03_flag_writes_the_warnings(floor_dataset: Path, tmp_path: Path) -> None:
    _drop_item(floor_dataset, _item_of(floor_dataset, "screw", "fair"))  # SPEC-045: no nut
    splits = tmp_path / "splits"
    assert _cli(floor_dataset, splits, "--allow-below-floor") == 0
    warnings = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))["warnings"]
    assert {"code": "below_floor", "stratum": "screw/fair"} in warnings
    assert {"code": "small_stratum", "stratum": "screw/fair", "n_items": 2} in warnings


def test_ca03_later_versions_ignore_the_floor(floor_dataset: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    assert _cli(floor_dataset, splits) == 0
    add_synthetic_item(floor_dataset, "N-901", "nut", "fair", n_images=1)
    assert _cli(floor_dataset, splits) == 0
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    assert not [w for w in meta["warnings"] if w["code"] == "below_floor"]


def test_flag_ignored_after_split_v1_with_a_log_warning(
    floor_dataset: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    splits = tmp_path / "splits"
    assert _cli(floor_dataset, splits) == 0
    add_synthetic_item(floor_dataset, "N-901", "nut", "fair", n_images=1)
    with caplog.at_level("WARNING", logger="qc_ml.split"):
        assert _cli(floor_dataset, splits, "--allow-below-floor") == 0
    assert "--allow-below-floor has no effect" in caplog.text
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    assert not [w for w in meta["warnings"] if w["code"] == "below_floor"]


def test_make_split_does_not_check_the_floor(tmp_path: Path) -> None:
    root = make_synthetic_dataset(tmp_path / "ds", items_per_stratum=1, images_per_item=1)
    assert not (split.make_split(load_manifest(root)).frame["split"] == "test").any()


def test_ca04_external_items_at_and_above_the_ceiling(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    one = make_synthetic_dataset(
        tmp_path / "one", items_per_stratum=3, images_per_item=3, external_items_per_stratum=1
    )
    assert _cli(one, tmp_path / "s1", *_external_registry(one)) == 0
    meta = json.loads((tmp_path / "s1" / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["external_fraction_train"] == 0.25

    two = make_synthetic_dataset(
        tmp_path / "two", items_per_stratum=3, images_per_item=3, external_items_per_stratum=2
    )
    capfd.readouterr()
    assert _cli(two, tmp_path / "s2", *_external_registry(two)) == 2
    assert "external fraction in train 22/55" in capfd.readouterr().err
    assert not list((tmp_path / "s2").glob("split_v1.*"))


def _tiny_config(tmp_path: Path, root: Path, splits: Path) -> Path:
    models_root = tmp_path / "models"
    shutil.copytree(TINY_MODEL, models_root / TINY_VERSION)
    config = {
        "model_version": TINY_VERSION,
        "dataset_dir": str(root),
        "split_file": str(splits / "split_v1.csv"),
        "backbone": "tiny",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(models_root),
        "reports_root": str(tmp_path / "reports"),
        "checkpoints_root": str(tmp_path / "checkpoints"),
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _metrics_at_the_floor(tmp_path: Path, root: Path) -> dict:
    from qc_ml import thresholds

    splits = tmp_path / "splits"
    assert _cli(root, splits) == 0
    config = _tiny_config(tmp_path, root, splits)
    assert thresholds.main(["--config", str(config)]) == 0
    assert evaluate.main(["--config", str(config)]) == 0
    metrics = tmp_path / "models" / TINY_VERSION / "metrics.json"
    return json.loads(metrics.read_text(encoding="utf-8"))


def test_ca05_metrics_exist_at_the_floor(floor_dataset: Path, tmp_path: Path) -> None:
    metrics = _metrics_at_the_floor(tmp_path, floor_dataset)
    assert set(metrics["n_items_test_by_grade"].values()) == {2}
    assert len(metrics["n_items_test_by_grade"]) == 5
    for key in (
        "grade_qwk",
        "grade_off_by_one_accuracy",
        "type_accuracy",
        "unusable_recall",
        "defective_recall",
        "unknown_rate_on_other",
        "false_unknown_rate",
    ):
        assert metrics[key] is not None, key
    assert "few test items for other: 1" in metrics["warnings"]
    assert not [w for w in metrics["warnings"] if w.startswith("grade ") and " has" in w]


def test_ca05_ten_other_objects_clear_the_warning(floor_dataset: Path, tmp_path: Path) -> None:
    for number in range(4, 11):
        add_synthetic_item(floor_dataset, f"O-{number:03d}", "other", None, n_images=3, seed=number)
    metrics = _metrics_at_the_floor(tmp_path, floor_dataset)
    assert not [w for w in metrics["warnings"] if w.startswith("few test items for other")]


@pytest.mark.slow
def test_ca06_pipeline_with_a_last_batch_of_one_image(floor_dataset: Path, tmp_path: Path) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    pytest.importorskip("onnx")
    from qc_ml import pipeline

    splits = tmp_path / "splits"
    assert _cli(floor_dataset, splits) == 0
    config = {
        "model_version": "partqc-smoke-v1",
        "dataset_dir": str(floor_dataset),
        "split_file": str(splits / "split_v1.csv"),
        "backbone": "mobilenetv3_small_050",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "batch_size": 32,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(tmp_path / "models"),
        "reports_root": str(tmp_path / "reports"),
        "checkpoints_root": str(tmp_path / "checkpoints"),
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    assert pipeline.main(["--config", str(path)]) == 0
    assert (tmp_path / "models" / "partqc-smoke-v1" / "metrics.json").is_file()
