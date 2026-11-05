"""Acceptance tests for SPEC-041 (provisional model and floor of ``split_v1``), ML part.

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One ``test_caNN_*`` per CA, at least: CAs 01 to 16, 20 and 23 to 26 live here, and
CAs 17 to 21 and 26 to 30 live in ``edge/tests/acceptance/test_spec_041.py``. CA-22 is manual and
stays pending. Tests named ``test_extra_*`` are exploratory edge cases that no CA spells out.

Rules followed (``docs/architecture.md`` section 10, R-11 and R-14):

* every dataset is synthetic (``make_synthetic_dataset``) and lives under ``tmp_path``, outside any
  Git repository unless the test creates one there with ``git init``; nothing under ``ml/data/`` is
  read and no real photo is used;
* the CLIs run through ``python -m`` in a subprocess. The exceptions are the spies of CA-08, which
  need the same process, and the no-torch runner of CA-14 and CA-25, which blocks the import with
  ``sys.modules["torch"] = None`` as the CA says;
* the slow tests use ``--smoke`` (``pretrained=False``), with no network (``HF_HUB_OFFLINE=1``).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

import qc_ml.config
import qc_ml.data
import qc_ml.provisional  # noqa: F401  (CA-14: importable with no torch installed)
from qc_ml import split as split_mod
from qc_ml.data import MANIFEST_COLUMNS, load_manifest
from qc_ml.errors import ConfigError, ManifestError
from qc_ml.evaluate import METRIC_KEYS
from qc_ml.split import floor_problems, make_split
from qc_ml.synthetic import make_synthetic_dataset
from qc_ml.train import load_config

pytestmark = pytest.mark.acceptance

REPO_ROOT = Path(__file__).resolve().parents[3]
TINY_MODEL = REPO_ROOT / "ml" / "tests" / "fixtures" / "tiny_model"
AGENT = "agent-suggestion"
VERSION = "partqc-mnv3-provisional-v1"
OFFICIAL_VERSION = "partqc-tinyacc-v1"
SEVEN_FILES = {
    "model.onnx",
    "model.sha256",
    "labels.json",
    "preprocessing.json",
    "decision.json",
    "parity_fixture.npz",
    "provisional_report.json",
}
REPORT_KEYS = {
    "model_version",
    "model_sha256",
    "provisional",
    "created_at",
    "manifest_sha256",
    "n_images",
    "n_items",
    "images_by_type_grade",
    "by_source",
    "epochs",
    "seed",
    "smoke",
    "train_loss_by_epoch",
    "decision_source",
    "versions",
    "git_commit",
    "notice",
}
NOTICE = (
    "Provisional model for rehearsal only (ADR-024). Grades are agent suggestions, not human "
    "labels. No validation or test split; no quality metric exists for this model."
)
GRADES = ("perfect", "good", "fair", "poor", "unusable")
FLOOR_STRATA = sorted([*(f"screw/{g}" for g in GRADES), "other/none"])
VERSIONS_CA20 = [
    ("partqc-mnv3-provisional-v1", True),
    ("partqc-provisional-v1", True),
    ("partqc-mnv3-v1", False),
    ("partqc-mnv3-corn-v2", False),
    ("stub-v0", False),
    ("provisional", False),
]
NO_TORCH_RUNNER = """\
import sys

sys.modules["torch"] = None
import qc_ml.provisional

sys.exit(qc_ml.provisional.main(sys.argv[1:]))
"""


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["HF_HUB_OFFLINE"] = "1"
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_module(
    module: str, *args: object, cwd: Path, timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *(str(a) for a in args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        env=_env(),
        timeout=timeout,
        check=False,
    )


def run_without_torch(*args: object, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", NO_TORCH_RUNNER, *(str(a) for a in args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        env=_env(),
        timeout=300,
        check=False,
    )


def read_rows(ds: Path) -> list[dict[str, str]]:
    with (ds / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(ds: Path, rows: Iterable[dict[str, str]]) -> None:
    with (ds / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANIFEST_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def drop_rows(ds: Path, should_drop: Callable[[dict[str, str]], bool]) -> list[dict[str, str]]:
    """Remove matching images from the manifest, from ``sources.csv`` and from the disk."""
    rows = read_rows(ds)
    dropped = [r for r in rows if should_drop(r)]
    assert dropped, "the predicate matched no manifest row"
    write_rows(ds, [r for r in rows if not should_drop(r)])
    gone = {r["image_path"] for r in dropped}
    for path in gone:
        (ds / path).unlink()
    sources = ds / "sources.csv"
    if sources.exists():
        with sources.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            header = list(reader.fieldnames or ())
            keep = [[r[c] for c in header] for r in reader if r["image_path"] not in gone]
        write_csv(sources, header, keep)
    return dropped


def relabel_first(ds: Path, labeler: str, match: Callable[[dict[str, str]], bool]) -> str:
    rows = read_rows(ds)
    row = next(r for r in rows if match(r))
    row["labeler"] = labeler
    write_rows(ds, rows)
    return row["image_path"]


def write_override(ds: Path, image_path: str, labeler: str) -> None:
    rows = read_rows(ds)
    grade = next(r["grade"] for r in rows if r["image_path"] == image_path)
    other = "poor" if grade != "poor" else "fair"
    write_csv(
        ds / "labels_overrides.csv",
        ["image_path", "grade", "labeler", "reason"],
        [[image_path, other, labeler, "second look"]],
    )


def exclude(ds: Path, image_path: str) -> None:
    """Section 8.1 of the protocol: file deleted and one line in ``exclusions.csv``."""
    (ds / image_path).unlink()
    write_csv(ds / "exclusions.csv", ["image_path", "reason"], [[image_path, "person"]])


def snapshot(root: Path) -> dict[str, bytes | None]:
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): (None if p.is_dir() else p.read_bytes())
        for p in sorted(root.rglob("*"))
    }


def split_files(root: Path) -> list[Path]:
    return sorted(root.rglob("split_v*"))


def git_init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    return path


def item_map(ds: Path) -> dict[str, str]:
    return {r["image_path"]: r["item_id"] for r in read_rows(ds)}


def read_split(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["image_path"]: r["split"] for r in csv.DictReader(fh)}


def split_cli(ds: Path, splits: Path, *extra: object) -> subprocess.CompletedProcess[str]:
    return run_module(
        "qc_ml.split",
        "--dataset-dir",
        ds,
        "--splits-dir",
        splits,
        "--external-sources",
        ds / "external_sources.csv",
        *extra,
        cwd=ds.parent,
    )


def provisional_args(ds: Path, models: Path, *extra: object) -> list[object]:
    return [
        "--dataset-dir",
        ds,
        "--models-root",
        models,
        "--external-sources",
        ds / "external_sources.csv",
        *extra,
    ]


def provisional_cli(ds: Path, models: Path, *extra: object) -> subprocess.CompletedProcess[str]:
    return run_module(
        "qc_ml.provisional", *provisional_args(ds, models, *extra), cwd=models.parent, timeout=1800
    )


def assert_refused(
    proc: subprocess.CompletedProcess[str],
    models: Path,
    message: str,
    *absent: str,
) -> None:
    """Exit 2, ``message`` in the stderr, and no file nor directory under ``models``."""
    assert proc.returncode == 2, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert message in proc.stderr, proc.stderr
    assert not models.exists(), f"something was written: {snapshot(models).keys()}"
    assert "Traceback" not in proc.stderr, proc.stderr
    for text in absent:
        assert text not in proc.stderr, proc.stderr


def tiny_config(root: Path, ds: Path, split_file: Path, **overrides: Any) -> SimpleNamespace:
    """Config whose model directory is a copy of the ``tiny_model`` fixture."""
    version = overrides.get("model_version", OFFICIAL_VERSION)
    config = {
        "model_version": version,
        "dataset_dir": str(ds),
        "split_file": str(split_file),
        "backbone": "tiny",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(root / "models"),
        "reports_root": str(root / "reports"),
        "checkpoints_root": str(root / "checkpoints"),
        **overrides,
    }
    path = root / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    model_dir = root / "models" / version
    return SimpleNamespace(config=path, model_dir=model_dir, root=root)


def thresholds_and_evaluate(env: SimpleNamespace) -> dict[str, Any]:
    shutil.copytree(TINY_MODEL, env.model_dir)
    for module in ("qc_ml.thresholds", "qc_ml.evaluate"):
        proc = run_module(module, "--config", env.config, cwd=env.root)
        assert proc.returncode == 0, f"{module}\n{proc.stdout}\n{proc.stderr}"
    return json.loads((env.model_dir / "metrics.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _floor_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("acc041_floor")
    return make_synthetic_dataset(root / "ds", items_per_stratum=3, images_per_item=3)


@pytest.fixture
def floor_ds(_floor_template: Path, tmp_path: Path) -> Path:
    """The CA-01 dataset: 33 items, 99 images."""
    return Path(shutil.copytree(_floor_template, tmp_path / "ds"))


@pytest.fixture(scope="session")
def _external_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("acc041_external")
    return make_synthetic_dataset(
        root / "ds", items_per_stratum=0, external_items_per_stratum=4, labeler=AGENT
    )


@pytest.fixture
def external_ds(_external_template: Path, tmp_path: Path) -> Path:
    """The CA-07 dataset: only external images, with ``labeler=agent-suggestion``."""
    return Path(shutil.copytree(_external_template, tmp_path / "ds"))


@pytest.fixture
def models(tmp_path: Path) -> Path:
    """``--models-root``, not created: a refusal must leave it absent."""
    return tmp_path / "models"


@pytest.fixture(scope="session")
def provisional_run(_external_template: Path, tmp_path_factory: pytest.TempPathFactory) -> Any:
    """CA-07, once per session, because it trains a network."""
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    pytest.importorskip("onnx")
    root = tmp_path_factory.mktemp("acc041_run")
    ds = Path(shutil.copytree(_external_template, root / "ds"))
    before = snapshot(ds)
    args = ["--smoke", "--seed", "0"]
    proc = provisional_cli(ds, root / "models", *args)
    return SimpleNamespace(
        proc=proc,
        root=root,
        ds=ds,
        before=before,
        model_dir=root / "models" / VERSION,
    )


@pytest.fixture
def run_ok(provisional_run: Any) -> Any:
    proc = provisional_run.proc
    assert proc.returncode == 0, f"stdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-3000:]}"
    return provisional_run


# ---------------------------------------------------------------------------------------------
# Floor: CA-01 to CA-06
# ---------------------------------------------------------------------------------------------


def test_ca01_dataset_at_the_floor_gives_11_items_33_images_per_split(
    floor_ds: Path, tmp_path: Path
) -> None:
    assert len(read_rows(floor_ds)) == 99
    assert len({r["item_id"] for r in read_rows(floor_ds)}) == 33
    splits = tmp_path / "splits"

    proc = split_cli(floor_ds, splits)

    assert proc.returncode == 0, proc.stderr
    assignment = read_split(splits / "split_v1.csv")
    items = item_map(floor_ds)
    for which in ("train", "val", "test"):
        images = [path for path, value in assignment.items() if value == which]
        assert len(images) == 33, which
        assert len({items[path] for path in images}) == 11, which
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["warnings"] == []


def test_ca02_missing_stratum_is_refused_and_nothing_is_written(
    floor_ds: Path, tmp_path: Path
) -> None:
    item = next(
        r["item_id"]
        for r in read_rows(floor_ds)
        if r["object_type"] == "screw" and r["grade"] == "fair"
    )
    drop_rows(floor_ds, lambda r: r["item_id"] == item)
    assert len({r["item_id"] for r in read_rows(floor_ds)}) == 32
    splits = tmp_path / "splits"

    proc = split_cli(floor_ds, splits)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "split_v1 below the floor: screw/fair" in proc.stderr.splitlines()
    assert [ln for ln in proc.stderr.splitlines() if "below the floor" in ln] == [
        "split_v1 below the floor: screw/fair"
    ]
    assert split_files(tmp_path) == []


def _below_floor_ds(floor_ds: Path) -> Path:
    item = next(
        r["item_id"]
        for r in read_rows(floor_ds)
        if r["object_type"] == "screw" and r["grade"] == "fair"
    )
    drop_rows(floor_ds, lambda r: r["item_id"] == item)
    return floor_ds


def test_ca03_allow_below_floor_records_the_warning(floor_ds: Path, tmp_path: Path) -> None:
    ds = _below_floor_ds(floor_ds)
    splits = tmp_path / "splits"

    proc = split_cli(ds, splits, "--allow-below-floor")

    assert proc.returncode == 0, proc.stderr
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert {"code": "below_floor", "stratum": "screw/fair"} in meta["warnings"]
    small = [w for w in meta["warnings"] if w.get("code") == "small_stratum"]
    assert any("screw/fair" in json.dumps(w) for w in small), meta["warnings"]


def _second_split_setup(tmp_path: Path) -> tuple[Path, Path]:
    """A ``split_v1`` of 1 item per stratum, then 1 new item per stratum: still below the floor."""
    full = make_synthetic_dataset(tmp_path / "full", items_per_stratum=2, images_per_item=3)
    ds = Path(shutil.copytree(full, tmp_path / "ds"))
    first_items = {f"{letter}-{n:03d}" for letter in "SN" for n in range(1, 6)} | {"O-001"}
    drop_rows(ds, lambda r: r["item_id"] not in first_items)
    splits = tmp_path / "splits"
    first = split_cli(ds, splits, "--allow-below-floor")
    assert first.returncode == 0, first.stderr
    shutil.rmtree(ds)
    shutil.copytree(full, ds)
    return ds, splits


def test_ca03_existing_split_v1_ignores_the_floor(tmp_path: Path) -> None:
    ds, splits = _second_split_setup(tmp_path)

    second = split_cli(ds, splits)

    assert second.returncode == 0, second.stderr
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    assert [w for w in meta["warnings"] if w.get("code") == "below_floor"] == []
    assert "below the floor" not in second.stderr


def test_ca04_external_fraction_at_the_floor(tmp_path: Path) -> None:
    ds = make_synthetic_dataset(
        tmp_path / "ds", items_per_stratum=3, images_per_item=3, external_items_per_stratum=1
    )
    external = [r for r in read_rows(ds) if r["item_id"].startswith("X")]
    assert len(external) == 11
    assert len({r["item_id"] for r in external}) == 11
    splits = tmp_path / "splits"

    proc = split_cli(ds, splits)

    assert proc.returncode == 0, proc.stderr
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["external_fraction_train"] == 0.25


def test_ca04_external_fraction_above_the_ceiling_is_refused(tmp_path: Path) -> None:
    ds = make_synthetic_dataset(
        tmp_path / "ds", items_per_stratum=3, images_per_item=3, external_items_per_stratum=2
    )

    proc = split_cli(ds, tmp_path / "splits")

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "external fraction in train 22/55" in proc.stderr
    assert split_files(tmp_path) == []


def test_ca05_metrics_at_the_floor_are_defined(floor_ds: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    assert split_cli(floor_ds, splits).returncode == 0
    env = tiny_config(tmp_path, floor_ds, splits / "split_v1.csv")

    metrics = thresholds_and_evaluate(env)

    assert metrics["n_items_test_by_grade"] == dict.fromkeys(GRADES, 2)
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
    for grade in GRADES:
        assert not [w for w in metrics["warnings"] if f"grade {grade} has" in w], grade


def test_ca05_ten_other_objects_have_no_warning(tmp_path: Path) -> None:
    ds = make_synthetic_dataset(tmp_path / "ds", items_per_stratum=10, images_per_item=3)
    numbers = {"S": 15, "N": 15, "O": 10}
    drop_rows(ds, lambda r: int(r["item_id"].split("-")[1]) > numbers[r["item_id"].split("-")[0]])
    assert len({r["item_id"] for r in read_rows(ds) if r["object_type"] == "other"}) == 10
    splits = tmp_path / "splits"
    proc = split_cli(ds, splits)
    assert proc.returncode == 0, proc.stderr
    env = tiny_config(tmp_path, ds, splits / "split_v1.csv")

    metrics = thresholds_and_evaluate(env)

    assert not [w for w in metrics["warnings"] if "few test items for other" in w]
    assert metrics["n_items_test_by_grade"] == dict.fromkeys(GRADES, 2)


@pytest.mark.slow
def test_ca06_pipeline_at_the_floor_with_a_one_image_batch(floor_ds: Path, tmp_path: Path) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    pytest.importorskip("onnx")
    splits = tmp_path / "splits"
    assert split_cli(floor_ds, splits).returncode == 0
    assignment = read_split(splits / "split_v1.csv")
    train = sum(1 for value in assignment.values() if value == "train")
    assert train == 33 and train % 32 == 1  # the last batch of the training has 1 image
    env = tiny_config(
        tmp_path,
        floor_ds,
        splits / "split_v1.csv",
        model_version="partqc-floorsmoke-v1",
        backbone="mobilenetv3_small_050",
        batch_size=32,
    )

    proc = run_module("qc_ml.pipeline", "--config", env.config, cwd=tmp_path, timeout=1800)

    assert proc.returncode == 0, f"stdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-3000:]}"
    assert (env.model_dir / "metrics.json").is_file()


# ---------------------------------------------------------------------------------------------
# Provisional model: CA-07 to CA-14
# ---------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_ca07_smoke_writes_exactly_the_seven_files(run_ok: Any) -> None:
    from qc_ml.parity import check_parity

    assert {p.name for p in run_ok.model_dir.iterdir()} == SEVEN_FILES
    decision = json.loads((run_ok.model_dir / "decision.json").read_text(encoding="utf-8"))
    assert decision == {
        "type_threshold": 0.50,
        "unusable_threshold": 0.50,
        "grade_review_threshold": 0.60,
    }
    assert check_parity(run_ok.model_dir).ok is True
    inferencer_mod = pytest.importorskip("qc_edge.onnx_inferencer")
    inferencer = inferencer_mod.OnnxInferencer(run_ok.model_dir)
    assert inferencer.model_info.model_version == VERSION


@pytest.mark.slow
def test_ca08_no_split_function_is_called_and_no_split_is_created(
    _external_template: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    pytest.importorskip("onnx")
    ds = Path(shutil.copytree(_external_template, tmp_path / "ds"))
    calls: list[str] = []
    for name in ("load_split", "rows_for", "make_split"):
        original = getattr(split_mod, name)

        def spy(*args: Any, _name: str = name, **kwargs: Any) -> Any:
            calls.append(_name)
            raise AssertionError(f"{_name} was called")

        # Also the names bound by a ``from qc_ml.split import ...`` in any loaded module.
        for module_name, module in list(sys.modules.items()):
            if module_name.startswith("qc_ml") and getattr(module, name, None) is original:
                monkeypatch.setattr(module, name, spy)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.chdir(tmp_path)
    args = provisional_args(ds, tmp_path / "models", "--smoke", "--seed", "0")

    code = qc_ml.provisional.main([str(a) for a in args])

    assert code == 0
    assert calls == []
    assert split_files(tmp_path) == []
    assert not list(tmp_path.rglob("thresholds*"))
    assert not list(tmp_path.rglob("metrics.json"))


@pytest.mark.slow
def test_ca09_report_has_exactly_the_keys_and_no_quality_metric(run_ok: Any) -> None:
    report = json.loads((run_ok.model_dir / "provisional_report.json").read_text(encoding="utf-8"))
    assert set(report) == REPORT_KEYS
    assert report["provisional"] is True
    assert report["notice"] == NOTICE
    assert set(report) & set(METRIC_KEYS) == {"model_version", "model_sha256", "manifest_sha256"}
    assert not [key for key in report if key.startswith("val_")]


@pytest.mark.slow
def test_extra_report_values_are_the_real_ones(run_ok: Any) -> None:
    model_dir = run_ok.model_dir
    report = json.loads((model_dir / "provisional_report.json").read_text(encoding="utf-8"))
    onnx_sha = hashlib.sha256((model_dir / "model.onnx").read_bytes()).hexdigest()
    manifest_sha = hashlib.sha256((run_ok.ds / "manifest.csv").read_bytes()).hexdigest()
    assert report["model_version"] == VERSION
    assert report["model_sha256"] == onnx_sha
    assert (model_dir / "model.sha256").read_text(encoding="utf-8").split()[0] == onnx_sha
    assert report["manifest_sha256"] == manifest_sha
    assert report["n_images"] == 44
    assert report["n_items"] == 44
    assert report["images_by_type_grade"] == {
        "screw": dict.fromkeys(GRADES, 4),
        "nut": dict.fromkeys(GRADES, 4),
        "other": {"none": 4},
    }
    assert report["by_source"] == {"synthetic": 44}
    assert report["epochs"] == 1
    assert report["seed"] == 0
    assert report["smoke"] is True
    assert len(report["train_loss_by_epoch"]) == 1
    assert report["decision_source"] == "fixed_defaults"
    assert report["git_commit"] is None or isinstance(report["git_commit"], str)
    created = datetime.fromisoformat(report["created_at"].replace("Z", "+00:00"))
    assert created.utcoffset() == timedelta(0)


@pytest.mark.slow
def test_extra_run_writes_nothing_else_and_keeps_the_dataset(run_ok: Any) -> None:
    assert snapshot(run_ok.ds) == run_ok.before
    assert sorted(p.name for p in run_ok.root.iterdir()) == ["ds", "models"]
    assert [p.name for p in (run_ok.root / "models").iterdir()] == [VERSION]


@pytest.mark.slow
def test_extra_default_seed_either_works_or_leaves_no_directory(
    external_ds: Path, models: Path
) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    pytest.importorskip("onnx")

    proc = provisional_cli(external_ds, models, "--smoke")

    # SPEC_ISSUE-06: seed 42 may exit 2 on the parity check; section 4.3 still applies.
    assert proc.returncode in (0, 2), proc.stderr
    if proc.returncode == 0:
        assert {p.name for p in (models / VERSION).iterdir()} == SEVEN_FILES
    else:
        assert "Traceback" not in proc.stderr
        assert not (models / VERSION).exists()


@pytest.mark.slow
def test_extra_real_provisional_model_is_simulated_at_the_edge(
    run_ok: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    pytest.importorskip("qc_edge")
    from fastapi.testclient import TestClient

    from qc_edge.app import create_app
    from qc_edge.config import EdgeSettings
    from qc_edge.onnx_inferencer import OnnxInferencer
    from qc_edge.sink import InMemorySink

    token = "t" * 40
    for name in ("MODEL_DIR", "DATASET_DIR", "OUTBOX_PATH", "EDGE_PUBLISHER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "edge"))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    buffer = io.BytesIO()
    Image.new("RGB", (300, 300), "steelblue").save(buffer, format="JPEG")
    app = create_app(EdgeSettings(), OnnxInferencer(run_ok.model_dir), InMemorySink())

    with TestClient(app) as client:
        response = client.post(
            "/api/capture",
            headers={"X-Session-Token": token},
            data={"lot_id": "ENSAIO-1", "mode": "inspect"},
            files={"image": ("foto.jpg", buffer.getvalue(), "image/jpeg")},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["inspection"]["source"] == "simulated"
    assert body["inspection"]["model_version"] == VERSION
    assert body["labels_pt"]["verdict"].endswith(" (modelo provisório)")


def _one_own_item(tmp_path: Path) -> Path:
    ds = make_synthetic_dataset(
        tmp_path / "ds", items_per_stratum=1, external_items_per_stratum=4, labeler=AGENT
    )
    drop_rows(ds, lambda r: not r["item_id"].startswith("X") and r["item_id"] != "S-001")
    return ds


def test_ca10_own_item_is_refused(tmp_path: Path, models: Path) -> None:
    ds = _one_own_item(tmp_path)
    own = [r for r in read_rows(ds) if r["item_id"] == "S-001"]
    assert len(own) == 2
    before = snapshot(ds)

    proc = provisional_cli(ds, models, "--smoke")

    assert_refused(proc, models, f"provisional dataset has own images: {len(own)}")
    assert snapshot(ds) == before


@pytest.mark.parametrize("which", ["dataset", "models"])
@pytest.mark.parametrize("nested", [False, True], ids=["root", "subfolder"])
def test_ca11_paths_inside_a_git_repository_are_refused(
    external_ds: Path, tmp_path: Path, which: str, nested: bool
) -> None:
    repo = git_init(tmp_path / "repo")
    inside = repo / "a" / "b" if nested else repo
    inside.mkdir(parents=True, exist_ok=True)
    ds = external_ds
    models_root = tmp_path / "outside-models"
    if which == "dataset":
        ds = Path(shutil.move(str(external_ds), str(inside / "ds")))
    else:
        models_root = inside / "models"

    proc = provisional_cli(ds, models_root, "--smoke")

    assert_refused(proc, models_root, "provisional paths must be outside a Git repository")


def test_extra_git_symlink_is_resolved_first(external_ds: Path, tmp_path: Path) -> None:
    repo = git_init(tmp_path / "repo")
    target = repo / "models"
    target.mkdir()
    link = tmp_path / "link-models"
    link.symlink_to(target)

    proc = provisional_cli(external_ds, link, "--smoke")

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "provisional paths must be outside a Git repository" in proc.stderr
    assert snapshot(target) == {}


def test_ca12_official_version_name_is_refused(external_ds: Path, models: Path) -> None:
    proc = provisional_cli(external_ds, models, "--model-version", "partqc-mnv3-v1", "--smoke")

    assert_refused(proc, models, "not a provisional model version")


def test_ca12_non_empty_model_directory_is_refused_untouched(
    external_ds: Path, models: Path
) -> None:
    target = models / VERSION
    target.mkdir(parents=True)
    (target / "keep.txt").write_bytes(b"conteudo anterior\n")
    before = snapshot(models)

    proc = provisional_cli(external_ds, models, "--smoke")

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "model directory already exists" in proc.stderr
    assert snapshot(models) == before


def test_ca13_type_missing_is_refused(external_ds: Path, models: Path) -> None:
    drop_rows(external_ds, lambda r: r["object_type"] == "nut")

    proc = provisional_cli(external_ds, models, "--smoke")

    assert_refused(proc, models, "provisional dataset needs the types: nut")


def test_ca13_grade_missing_is_refused(external_ds: Path, models: Path) -> None:
    drop_rows(external_ds, lambda r: r["grade"] == "unusable")

    proc = provisional_cli(external_ds, models, "--smoke")

    assert_refused(proc, models, "no training image with grade unusable")


def test_ca13_tool_is_refused(tmp_path: Path, models: Path) -> None:
    ds = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=0,
        external_items_per_stratum=4,
        external_tool_items_per_type=1,
        labeler=AGENT,
    )
    assert [r for r in read_rows(ds) if r["item_id"].startswith("XT-")]

    proc = provisional_cli(ds, models, "--smoke")

    assert_refused(proc, models, "provisional dataset has other types")


def test_ca13_epochs_out_of_range_is_refused(external_ds: Path, models: Path) -> None:
    proc = provisional_cli(external_ds, models, "--epochs", "12")

    assert_refused(proc, models, "epochs must be in [5, 10]")


def test_ca14_without_torch_the_error_is_the_extra(external_ds: Path, tmp_path: Path) -> None:
    models = tmp_path / "models"

    proc = run_without_torch(*provisional_args(external_ds, models, "--smoke"), cwd=tmp_path)

    assert_refused(proc, models, "training needs the train extra")


def test_ca14_module_can_be_imported_without_torch(tmp_path: Path) -> None:
    code = (
        "import sys\n"
        "sys.modules['torch'] = None\n"
        "import qc_ml.provisional\n"
        "assert sys.modules['torch'] is None\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=_env(),
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


# Exploratory: section 4.3 says "nesta ordem". Each pair below breaks two consecutive refusals at
# once, and the first of the pair must win.


def _make_invalid(ds: Path) -> None:
    (ds / read_rows(ds)[0]["image_path"]).unlink()


def _other_types(tmp_path: Path) -> Path:
    return make_synthetic_dataset(
        tmp_path / "ds2",
        items_per_stratum=0,
        external_items_per_stratum=4,
        external_tool_items_per_type=1,
        labeler=AGENT,
    )


def test_extra_order_version_before_git(external_ds: Path, tmp_path: Path) -> None:
    repo = git_init(tmp_path / "repo")
    proc = provisional_cli(external_ds, repo / "models", "--model-version", "partqc-mnv3-v1")
    assert proc.returncode == 2
    assert "not a provisional model version" in proc.stderr
    assert "Git repository" not in proc.stderr


def test_extra_order_git_before_existing_directory(external_ds: Path, tmp_path: Path) -> None:
    repo = git_init(tmp_path / "repo")
    target = repo / "models" / VERSION
    target.mkdir(parents=True)
    (target / "x").write_bytes(b"x")
    proc = provisional_cli(external_ds, repo / "models")
    assert proc.returncode == 2
    assert "provisional paths must be outside a Git repository" in proc.stderr
    assert "model directory already exists" not in proc.stderr


def test_extra_order_existing_directory_before_manifest(external_ds: Path, models: Path) -> None:
    _make_invalid(external_ds)
    target = models / VERSION
    target.mkdir(parents=True)
    (target / "x").write_bytes(b"x")
    proc = provisional_cli(external_ds, models)
    assert proc.returncode == 2
    assert "model directory already exists" in proc.stderr


def test_extra_order_manifest_before_own_images(tmp_path: Path, models: Path) -> None:
    ds = _one_own_item(tmp_path)
    _make_invalid(ds)
    registry = ds / "external_sources.csv"
    with pytest.raises(ManifestError) as raised:
        load_manifest(ds, external_sources=registry, allow_agent_suggestion=True)

    proc = provisional_cli(ds, models)

    assert_refused(proc, models, raised.value.problems[0].code, "own images")
    assert str(raised.value.problems[0].message) in proc.stderr


def test_extra_order_own_images_before_other_labelers(tmp_path: Path, models: Path) -> None:
    ds = _one_own_item(tmp_path)
    relabel_first(ds, "a", lambda r: r["item_id"] == "S-001")
    proc = provisional_cli(ds, models)
    assert_refused(proc, models, "provisional dataset has own images: 2", "other labelers")


def test_extra_order_other_labelers_before_other_types(tmp_path: Path, models: Path) -> None:
    ds = _other_types(tmp_path)
    relabel_first(ds, "b", lambda r: r["item_id"].startswith("XT-"))
    proc = provisional_cli(ds, models)
    assert_refused(proc, models, "provisional dataset has other labelers: 1", "other types")


def test_extra_order_other_types_before_needed_types(tmp_path: Path, models: Path) -> None:
    ds = _other_types(tmp_path)
    drop_rows(ds, lambda r: r["object_type"] == "nut")
    proc = provisional_cli(ds, models)
    assert_refused(proc, models, "provisional dataset has other types", "needs the types")


def test_extra_order_needed_types_before_grade(external_ds: Path, models: Path) -> None:
    drop_rows(external_ds, lambda r: r["object_type"] == "nut" or r["grade"] == "unusable")
    proc = provisional_cli(external_ds, models)
    assert_refused(proc, models, "provisional dataset needs the types: nut", "no training image")


def test_extra_order_grade_before_epochs(external_ds: Path, models: Path) -> None:
    drop_rows(external_ds, lambda r: r["grade"] == "unusable")
    proc = provisional_cli(external_ds, models, "--epochs", "12")
    assert_refused(proc, models, "no training image with grade unusable", "epochs must be")


def test_extra_order_epochs_before_torch(external_ds: Path, tmp_path: Path) -> None:
    models = tmp_path / "models"
    args = provisional_args(external_ds, models, "--epochs", "12")
    proc = run_without_torch(*args, cwd=tmp_path)
    assert_refused(proc, models, "epochs must be in [5, 10]", "train extra")


@pytest.mark.parametrize("value", ["4", "11", "0", "-1"])
def test_extra_epochs_refused_outside_the_limits(
    external_ds: Path, tmp_path: Path, value: str
) -> None:
    models = tmp_path / "models"
    args = provisional_args(external_ds, models, f"--epochs={value}")
    proc = run_without_torch(*args, cwd=tmp_path)
    assert_refused(proc, models, "epochs must be in [5, 10]")


@pytest.mark.parametrize("value", ["5", "10"])
def test_extra_epochs_accepted_at_the_limits(external_ds: Path, tmp_path: Path, value: str) -> None:
    models = tmp_path / "models"
    args = provisional_args(external_ds, models, "--epochs", value)
    proc = run_without_torch(*args, cwd=tmp_path)
    assert_refused(proc, models, "training needs the train extra", "epochs must be")


def test_extra_smoke_is_not_limited_by_the_epochs_range(external_ds: Path, tmp_path: Path) -> None:
    models = tmp_path / "models"
    args = provisional_args(external_ds, models, "--smoke", "--epochs", "12")
    proc = run_without_torch(*args, cwd=tmp_path)
    assert_refused(proc, models, "training needs the train extra", "epochs must be")


@pytest.mark.parametrize(
    "version",
    [
        "partqc-provisional",
        "-provisional-",
        "PARTQC-provisional-v1",
        "../evil-provisional-v1",
        "a/b-provisional-v1",
        "partqc-provisional-v1\n",
        "partqc mnv3-provisional-v1",
        "partqc-provisional-vü",
        "x" * 41 + "-provisional-v1",
        "",
    ],
)
def test_extra_bad_version_names_are_refused(
    external_ds: Path, tmp_path: Path, version: str
) -> None:
    models = tmp_path / "models"
    proc = provisional_cli(external_ds, models, f"--model-version={version}", "--smoke")
    assert_refused(proc, models, "not a provisional model version")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ds"]


def test_extra_empty_model_directory_is_allowed(external_ds: Path, tmp_path: Path) -> None:
    models = tmp_path / "models"
    (models / VERSION).mkdir(parents=True)
    args = provisional_args(external_ds, models, "--smoke")
    proc = run_without_torch(*args, cwd=tmp_path)
    assert proc.returncode == 2
    assert "training needs the train extra" in proc.stderr
    assert "model directory already exists" not in proc.stderr


@pytest.mark.parametrize(
    "case",
    ["missing-dataset", "corrupt-image", "corrupt-manifest", "missing-registry", "root-is-file"],
)
def test_extra_broken_inputs_exit_2_without_traceback(
    external_ds: Path, tmp_path: Path, case: str
) -> None:
    models = tmp_path / "models"
    ds = external_ds
    args: list[object] = []
    if case == "missing-dataset":
        ds = tmp_path / "nope"
        args = ["--external-sources", external_ds / "external_sources.csv"]
    elif case == "corrupt-image":
        (ds / read_rows(ds)[0]["image_path"]).write_bytes(b"not a jpeg")
    elif case == "corrupt-manifest":
        (ds / "manifest.csv").write_bytes(b"\xff\xfe\x00broken\n")
    elif case == "missing-registry":
        args = ["--external-sources", tmp_path / "nope.csv"]
    else:
        models.write_bytes(b"a file, not a directory")

    full = ["--dataset-dir", ds, "--models-root", models]
    full += args or ["--external-sources", ds / "external_sources.csv"]
    proc = run_without_torch(*full, "--smoke", cwd=tmp_path)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stderr.strip()
    assert "Traceback" not in proc.stderr, proc.stderr
    if case != "root-is-file":
        assert not models.exists()


def test_extra_unicode_paths_work(external_ds: Path, tmp_path: Path) -> None:
    ds = Path(shutil.move(str(external_ds), str(tmp_path / "Área de trabalho ção")))
    models = tmp_path / "módulos ção"
    proc = run_without_torch(*provisional_args(ds, models, "--smoke"), cwd=tmp_path)
    assert_refused(proc, models, "training needs the train extra")


# ---------------------------------------------------------------------------------------------
# Official path guards: CA-15 and CA-16
# ---------------------------------------------------------------------------------------------


def _provisional_config(tmp_path: Path) -> Path:
    config = {
        "model_version": VERSION,
        "dataset_dir": str(tmp_path / "ds"),
        "split_file": str(tmp_path / "split_v1.csv"),
        "backbone": "tiny",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(tmp_path / "models"),
        "reports_root": str(tmp_path / "reports"),
        "checkpoints_root": str(tmp_path / "checkpoints"),
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_ca15_load_config_refuses_a_provisional_version(tmp_path: Path) -> None:
    config = _provisional_config(tmp_path)
    with pytest.raises(ConfigError, match="provisional model versions are not allowed"):
        load_config(config)


@pytest.mark.parametrize("module", ["pipeline", "thresholds", "evaluate", "train"])
def test_ca15_official_steps_exit_2(tmp_path: Path, module: str) -> None:
    config = _provisional_config(tmp_path)

    proc = run_module(f"qc_ml.{module}", "--config", config, cwd=tmp_path)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    expected = "provisional model versions are not allowed in the official pipeline"
    assert expected in proc.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.json"]


def test_extra_export_with_the_train_extra_exits_2(tmp_path: Path) -> None:
    # Section 4.5 also names ``export``, which is not in CA-15. The module imports torch at the top
    # (SPEC-012, unchanged here), so it only runs with the train extra, whatever the version.
    pytest.importorskip("torch")
    pytest.importorskip("onnx")
    config = _provisional_config(tmp_path)

    proc = run_module("qc_ml.export", "--config", config, cwd=tmp_path)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    expected = "provisional model versions are not allowed in the official pipeline"
    assert expected in proc.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.json"]


def test_extra_official_guard_uses_the_name_not_the_smoke_flag(tmp_path: Path) -> None:
    config = json.loads(_provisional_config(tmp_path).read_text(encoding="utf-8"))
    config.update(smoke=False, backbone="mobilenetv3_large_100", epochs_a=5, epochs_b_max=30)
    path = tmp_path / "other.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ConfigError, match="provisional model versions are not allowed"):
        load_config(path)


@pytest.fixture
def valid_metrics(floor_ds: Path, tmp_path: Path) -> SimpleNamespace:
    """A real ``metrics.json``, from ``thresholds`` and ``evaluate`` with ``tiny_model``."""
    splits = tmp_path / "splits"
    assert split_cli(floor_ds, splits).returncode == 0
    env = tiny_config(tmp_path, floor_ds, splits / "split_v1.csv")
    metrics = thresholds_and_evaluate(env)
    planted = tmp_path / "planted" / VERSION
    shutil.copytree(env.model_dir, planted)
    metrics["model_version"] = VERSION
    (planted / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return SimpleNamespace(official=env.model_dir, provisional=planted, root=tmp_path)


def test_ca16_changelog_refuses_and_writes_nothing(valid_metrics: SimpleNamespace) -> None:
    root = valid_metrics.root
    target = root / "CHANGELOG.md"
    target.write_bytes(b"# CHANGELOG\n\nantes\n")
    before = snapshot(valid_metrics.provisional)
    args = ("changelog", "--model-dir", valid_metrics.official, "--append", target)
    control = run_module("qc_ml.report", *args, cwd=root)
    assert control.returncode == 0, control.stderr  # the metrics.json really is valid
    target.write_bytes(b"# CHANGELOG\n\nantes\n")

    args = ("changelog", "--model-dir", valid_metrics.provisional, "--append", target)
    proc = run_module("qc_ml.report", *args, cwd=root)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "provisional model: no official report" in proc.stderr
    assert proc.stdout == ""
    assert target.read_bytes() == b"# CHANGELOG\n\nantes\n"
    assert snapshot(valid_metrics.provisional) == before


def test_ca16_release_notes_refuses_and_writes_nothing(valid_metrics: SimpleNamespace) -> None:
    root = valid_metrics.root
    target = root / "notes.md"
    before = snapshot(valid_metrics.provisional)
    args = ("release-notes", "--model-dir", valid_metrics.official, "--output", target)
    control = run_module("qc_ml.report", *args, cwd=root)
    assert control.returncode == 0, control.stderr  # the metrics.json really is valid
    target.unlink()

    args = ("release-notes", "--model-dir", valid_metrics.provisional, "--output", target)
    proc = run_module("qc_ml.report", *args, cwd=root)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "provisional model: no official report" in proc.stderr
    assert proc.stdout == ""
    assert not target.exists()
    assert snapshot(valid_metrics.provisional) == before


@pytest.mark.parametrize("command", ["changelog", "release-notes"])
@pytest.mark.parametrize("state", ["missing", "corrupt"])
def test_extra_report_refuses_before_reading_metrics(
    tmp_path: Path, command: str, state: str
) -> None:
    model_dir = tmp_path / VERSION
    model_dir.mkdir()
    if state == "corrupt":
        (model_dir / "metrics.json").write_text("{not json", encoding="utf-8")

    proc = run_module("qc_ml.report", command, "--model-dir", model_dir, cwd=tmp_path)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "provisional model: no official report" in proc.stderr


# ---------------------------------------------------------------------------------------------
# CA-20: the name decides
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("version, expected", VERSIONS_CA20)
def test_ca20_same_rule_in_both_packages(version: str, expected: bool) -> None:
    edge_inference = pytest.importorskip("qc_edge.inference")
    assert qc_ml.config.is_provisional_version(version) is expected
    assert edge_inference.is_provisional_version(version) is expected


@pytest.mark.parametrize(
    "version, expected",
    [
        ("-provisional-", True),
        ("a-provisional-", True),
        ("-provisional-a", True),
        ("x-PROVISIONAL-y", False),
        ("x-provisional", False),
        ("provisional-y", False),
        ("x_provisional_y", False),
        ("", False),
        ("modelo-provisional-ção", True),
    ],
)
def test_extra_substring_rule(version: str, expected: bool) -> None:
    edge_inference = pytest.importorskip("qc_edge.inference")
    assert qc_ml.config.is_provisional_version(version) is expected
    assert edge_inference.is_provisional_version(version) is expected


# ---------------------------------------------------------------------------------------------
# CA-23 to CA-26: labeler of a suggestion
# ---------------------------------------------------------------------------------------------


def _problems(ds: Path) -> list[Any]:
    with pytest.raises(ManifestError) as raised:
        load_manifest(ds)
    return [p for p in raised.value.problems if p.code == "agent_suggestion_label"]


def test_ca23_manifest_line_is_refused_everywhere(floor_ds: Path, tmp_path: Path) -> None:
    relabel_first(floor_ds, AGENT, lambda r: True)

    found = _problems(floor_ds)
    assert len(found) == 1
    assert found[0].file == "manifest.csv"

    validate = run_module("qc_ml.data", "validate", "--dataset-dir", floor_ds, cwd=tmp_path)
    assert validate.returncode == 2, validate.stdout + validate.stderr
    assert "agent_suggestion_label" in validate.stdout

    splits = tmp_path / "splits"
    split = split_cli(floor_ds, splits)
    assert split.returncode == 2, split.stdout + split.stderr
    assert "agent_suggestion_label" in split.stderr
    assert split_files(tmp_path) == []


def test_ca23_override_line_is_refused(floor_ds: Path, tmp_path: Path) -> None:
    image = read_rows(floor_ds)[0]["image_path"]
    write_override(floor_ds, image, AGENT)

    found = _problems(floor_ds)
    assert len(found) == 1
    assert found[0].file == "labels_overrides.csv"

    validate = run_module("qc_ml.data", "validate", "--dataset-dir", floor_ds, cwd=tmp_path)
    assert validate.returncode == 2
    assert "agent_suggestion_label" in validate.stdout
    assert "labels_overrides.csv" in validate.stdout


def test_ca23_excluded_override_validates(floor_ds: Path, tmp_path: Path) -> None:
    image = read_rows(floor_ds)[0]["image_path"]
    write_override(floor_ds, image, AGENT)
    exclude(floor_ds, image)

    validate = run_module("qc_ml.data", "validate", "--dataset-dir", floor_ds, cwd=tmp_path)

    assert validate.returncode == 0, validate.stdout + validate.stderr


def test_extra_message_is_the_fixed_one(floor_ds: Path) -> None:
    relabel_first(floor_ds, AGENT, lambda r: True)
    [problem] = _problems(floor_ds)
    expected = "agent-suggested labels are only allowed in the provisional set (ADR-024)"
    assert problem.message == expected


def test_extra_excluded_manifest_line_gives_no_problem(floor_ds: Path) -> None:
    image = relabel_first(floor_ds, AGENT, lambda r: True)
    exclude(floor_ds, image)
    assert len(load_manifest(floor_ds)) == 98


def test_extra_allow_flag_loads_the_provisional_set(external_ds: Path) -> None:
    registry = external_ds / "external_sources.csv"
    with pytest.raises(ManifestError):
        load_manifest(external_ds, external_sources=registry)
    frame = load_manifest(external_ds, external_sources=registry, allow_agent_suggestion=True)
    assert len(frame) == 44


@pytest.mark.parametrize("value", ["Agent-Suggestion", "agent_suggestion", " agent-suggestion"])
def test_extra_near_values_count_as_other_labelers(
    external_ds: Path, models: Path, value: str
) -> None:
    # Section 4.9 compares the exact value, and the provisional set accepts only that value.
    relabel_first(external_ds, value, lambda r: True)

    proc = provisional_cli(external_ds, models, "--smoke")

    assert_refused(proc, models, "provisional dataset has other labelers: 1")


def _split_with_agent_line(root: Path) -> tuple[Path, Path]:
    ds = make_synthetic_dataset(root / "ds", items_per_stratum=3, images_per_item=3)
    splits = root / "splits"
    assert split_cli(ds, splits).returncode == 0
    relabel_first(ds, AGENT, lambda r: True)
    return ds, splits / "split_v1.csv"


@pytest.mark.parametrize("module", ["qc_ml.thresholds", "qc_ml.evaluate"])
def test_ca24_official_steps_refuse_a_suggested_label(tmp_path: Path, module: str) -> None:
    ds, split_file = _split_with_agent_line(tmp_path)
    env = tiny_config(tmp_path, ds, split_file)
    shutil.copytree(TINY_MODEL, env.model_dir)

    proc = run_module(module, "--config", env.config, cwd=tmp_path)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "agent_suggestion_label" in proc.stderr
    assert list(tmp_path.rglob("metrics.json")) == []


@pytest.mark.slow
def test_ca24_pipeline_refuses_a_suggested_label(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    pytest.importorskip("onnx")
    ds, split_file = _split_with_agent_line(tmp_path)
    env = tiny_config(
        tmp_path,
        ds,
        split_file,
        model_version="partqc-floorsmoke-v1",
        backbone="mobilenetv3_small_050",
    )

    proc = run_module("qc_ml.pipeline", "--config", env.config, cwd=tmp_path, timeout=1800)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "agent_suggestion_label" in proc.stderr
    assert list(tmp_path.rglob("metrics.json")) == []


@pytest.mark.slow
def test_extra_train_refuses_a_suggested_label(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    ds, split_file = _split_with_agent_line(tmp_path)
    env = tiny_config(
        tmp_path,
        ds,
        split_file,
        model_version="partqc-floorsmoke-v1",
        backbone="mobilenetv3_small_050",
    )

    proc = run_module("qc_ml.train", "--config", env.config, cwd=tmp_path, timeout=1800)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "agent_suggestion_label" in proc.stderr


def test_ca25_one_manifest_line_of_another_labeler(external_ds: Path, models: Path) -> None:
    relabel_first(external_ds, "a", lambda r: True)

    proc = provisional_cli(external_ds, models, "--smoke")

    assert_refused(proc, models, "provisional dataset has other labelers: 1")


def test_ca25_one_override_line_of_another_labeler(external_ds: Path, models: Path) -> None:
    write_override(external_ds, read_rows(external_ds)[0]["image_path"], "a")

    proc = provisional_cli(external_ds, models, "--smoke")

    assert_refused(proc, models, "provisional dataset has other labelers: 1")


def test_ca25_excluded_override_is_not_counted(external_ds: Path, models: Path) -> None:
    image = read_rows(external_ds)[0]["image_path"]
    write_override(external_ds, image, "a")
    exclude(external_ds, image)

    proc = provisional_cli(external_ds, models, "--epochs", "12")

    assert_refused(proc, models, "epochs must be in [5, 10]", "other labelers")


def test_ca25_without_torch_the_error_is_not_about_the_labeler(
    external_ds: Path, tmp_path: Path
) -> None:
    models = tmp_path / "models"

    proc = run_without_torch(*provisional_args(external_ds, models, "--smoke"), cwd=tmp_path)

    assert_refused(proc, models, "training needs the train extra", "other labelers", "labeler")


def test_extra_other_labelers_sum_both_files(external_ds: Path, models: Path) -> None:
    rows = read_rows(external_ds)
    relabel_first(external_ds, "a", lambda r: r["image_path"] == rows[0]["image_path"])
    relabel_first(external_ds, "b", lambda r: r["image_path"] == rows[1]["image_path"])
    write_override(external_ds, rows[2]["image_path"], "a")

    proc = provisional_cli(external_ds, models, "--smoke")

    assert_refused(proc, models, "provisional dataset has other labelers: 3")


def test_extra_excluded_manifest_line_of_another_labeler_is_not_counted(
    external_ds: Path, models: Path
) -> None:
    image = relabel_first(external_ds, "a", lambda r: True)
    exclude(external_ds, image)

    proc = provisional_cli(external_ds, models, "--epochs", "12")

    assert_refused(proc, models, "epochs must be in [5, 10]", "other labelers")


def test_ca26_constants_are_the_same_and_outside_the_collect_mode() -> None:
    importer = pytest.importorskip("qc_edge.importer")
    collect = pytest.importorskip("qc_edge.collect")
    assert qc_ml.data.AGENT_SUGGESTION_LABELER == AGENT
    assert importer.AGENT_SUGGESTION_LABELER == AGENT
    assert AGENT not in collect.LABELERS
    assert set(collect.LABELERS) == {"a", "b"}


# ---------------------------------------------------------------------------------------------
# Exploratory: floor
# ---------------------------------------------------------------------------------------------


def test_extra_many_strata_are_listed_in_lexicographic_order(
    floor_ds: Path, tmp_path: Path
) -> None:
    drop_rows(
        floor_ds,
        lambda r: r["item_id"] in {"S-005", "O-001", "S-003", "S-002"},
    )
    proc = split_cli(floor_ds, tmp_path / "splits")
    assert proc.returncode == 2
    lines = [ln for ln in proc.stderr.splitlines() if ln.startswith("split_v1 below the floor: ")]
    strata = [ln.removeprefix("split_v1 below the floor: ") for ln in lines]
    assert strata == ["other/none", "screw/fair", "screw/good", "screw/unusable"]


def test_extra_allow_flag_above_the_floor_adds_no_warning(floor_ds: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    proc = split_cli(floor_ds, splits, "--allow-below-floor")
    assert proc.returncode == 0, proc.stderr
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["warnings"] == []


def test_extra_flag_with_an_existing_split_is_ignored_with_a_log(tmp_path: Path) -> None:
    ds, splits = _second_split_setup(tmp_path)

    proc = split_cli(ds, splits, "--allow-below-floor")

    assert proc.returncode == 0, proc.stderr
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    assert [w for w in meta["warnings"] if w.get("code") == "below_floor"] == []
    assert "--allow-below-floor" in proc.stderr + proc.stdout


def test_extra_every_stratum_is_listed_when_only_externals_exist(
    external_ds: Path, tmp_path: Path
) -> None:
    write_rows(
        external_ds,
        [{**r, "labeler": "a"} for r in read_rows(external_ds)],
    )
    proc = split_cli(external_ds, tmp_path / "splits", "--max-external-fraction", "1.0")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    lines = [ln for ln in proc.stderr.splitlines() if ln.startswith("split_v1 below the floor: ")]
    assert [ln.removeprefix("split_v1 below the floor: ") for ln in lines] == FLOOR_STRATA
    assert split_files(tmp_path) == []


def test_extra_floor_problems_do_not_count_externals(tmp_path: Path) -> None:
    ds = make_synthetic_dataset(
        tmp_path / "ds", items_per_stratum=1, images_per_item=1, external_items_per_stratum=20
    )
    frame = load_manifest(ds, external_sources=ds / "external_sources.csv")
    result = make_split(frame, seed=42, max_external_fraction=1)
    assert floor_problems(frame, result.frame) == FLOOR_STRATA


def test_extra_floor_problems_empty_at_the_floor(floor_ds: Path) -> None:
    frame = load_manifest(floor_ds)
    result = make_split(frame, seed=42)
    assert floor_problems(frame, result.frame) == []


def test_extra_three_photos_per_item_are_not_checked_here(tmp_path: Path) -> None:
    ds = make_synthetic_dataset(tmp_path / "ds", items_per_stratum=3, images_per_item=1)
    splits = tmp_path / "splits"
    proc = split_cli(ds, splits)
    assert proc.returncode == 0, proc.stderr
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["warnings"] == []


def test_extra_contributor_items_count_for_the_floor(tmp_path: Path) -> None:
    ds = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=1,
        contributor_items_per_stratum=2,
        images_per_item=3,
    )
    splits = tmp_path / "splits"
    proc = split_cli(ds, splits)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (splits / "split_v1.csv").is_file()


def test_extra_excluded_item_counts_as_missing(floor_ds: Path, tmp_path: Path) -> None:
    rows = [r for r in read_rows(floor_ds) if r["object_type"] == "screw" and r["grade"] == "fair"]
    item = rows[0]["item_id"]
    gone = [r["image_path"] for r in rows if r["item_id"] == item]
    for image in gone:
        (floor_ds / image).unlink()
    write_csv(
        floor_ds / "exclusions.csv",
        ["image_path", "reason"],
        [[image, "person"] for image in gone],
    )
    proc = split_cli(floor_ds, tmp_path / "splits")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "split_v1 below the floor: screw/fair" in proc.stderr.splitlines()


def test_extra_synthetic_zero_items_still_needs_externals(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        make_synthetic_dataset(tmp_path / "ds", items_per_stratum=0)


def test_extra_synthetic_labeler_is_applied_to_every_line(tmp_path: Path) -> None:
    ds = make_synthetic_dataset(
        tmp_path / "ds", items_per_stratum=1, external_items_per_stratum=1, labeler=AGENT
    )
    assert {r["labeler"] for r in read_rows(ds)} == {AGENT}


def test_extra_dominant_grade_decides_the_stratum(floor_ds: Path, tmp_path: Path) -> None:
    # Section 7, "Grau dominante": 2 of the 3 images of each screw/fair item become poor, so no
    # item is in screw/fair any more, although every one still has a fair image.
    rows = read_rows(floor_ds)
    fair = sorted(
        {r["item_id"] for r in rows if r["object_type"] == "screw" and r["grade"] == "fair"}
    )
    changed = [
        [path, "poor", "a", "second look"]
        for item in fair
        for path in [r["image_path"] for r in rows if r["item_id"] == item][:2]
    ]
    write_csv(
        floor_ds / "labels_overrides.csv", ["image_path", "grade", "labeler", "reason"], changed
    )

    proc = split_cli(floor_ds, tmp_path / "splits")

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "split_v1 below the floor: screw/fair" in proc.stderr.splitlines()
    assert split_files(tmp_path) == []


def test_extra_running_again_with_the_same_data_writes_no_new_version(
    floor_ds: Path, tmp_path: Path
) -> None:
    ds = _below_floor_ds(floor_ds)
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, "--allow-below-floor").returncode == 0
    before = snapshot(splits)

    proc = split_cli(ds, splits)

    assert proc.returncode == 0, proc.stderr
    assert snapshot(splits) == before


def test_extra_data_report_also_refuses_a_suggested_label(floor_ds: Path, tmp_path: Path) -> None:
    relabel_first(floor_ds, AGENT, lambda r: True)
    out = tmp_path / "report.json"

    proc = run_module("qc_ml.data", "report", "--dataset-dir", floor_ds, "--out", out, cwd=tmp_path)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "agent_suggestion_label" in proc.stdout + proc.stderr
    assert not out.exists()


def test_extra_suggested_override_is_accepted_in_the_provisional_set(
    external_ds: Path, tmp_path: Path
) -> None:
    write_override(external_ds, read_rows(external_ds)[0]["image_path"], AGENT)
    models = tmp_path / "models"

    proc = run_without_torch(*provisional_args(external_ds, models, "--smoke"), cwd=tmp_path)

    assert_refused(proc, models, "training needs the train extra", "other labelers")


@pytest.mark.parametrize(
    "args",
    [["--epochs", "abc"], ["--seed", "abc"], ["--unknown"], ["--models-root"]],
    ids=["epochs-text", "seed-text", "unknown-option", "missing-value"],
)
def test_extra_bad_command_lines_exit_2(external_ds: Path, models: Path, args: list[str]) -> None:
    base = ["--dataset-dir", external_ds, "--models-root", models]
    proc = run_module("qc_ml.provisional", *base, *args, cwd=models.parent)
    assert_refused(proc, models, "usage")


def test_extra_required_paths_are_required(tmp_path: Path) -> None:
    proc = run_module("qc_ml.provisional", cwd=tmp_path)
    assert proc.returncode == 2
    assert "--dataset-dir" in proc.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == []


@pytest.mark.slow
@pytest.mark.parametrize("seed", ["-1", "99999999999"])
def test_extra_seed_out_of_range_exits_2_without_a_directory(
    external_ds: Path, models: Path, seed: str
) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    pytest.importorskip("onnx")

    proc = provisional_cli(external_ds, models, "--smoke", f"--seed={seed}")

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stderr.strip()
    assert not (models / VERSION).exists()
