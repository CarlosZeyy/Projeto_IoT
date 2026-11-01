"""Provisional model and the guards of the official path (SPEC-041 sections 4.1 to 4.5).

Synthetic data only, in ``tmp_path``. The slow tests train the smoke backbone on the CPU
(``pretrained=False``, no internet).
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from qc_ml import config as config_mod
from qc_ml import evaluate, provisional, report, thresholds
from qc_ml import pipeline as pipeline_mod
from qc_ml.config import is_provisional_version, load_config
from qc_ml.data import (
    AGENT_SUGGESTION_LABELER,
    EXCLUSION_COLUMNS,
    MANIFEST_COLUMNS,
    OVERRIDE_COLUMNS,
)
from qc_ml.errors import ConfigError
from qc_ml.evaluate import METRIC_KEYS
from qc_ml.synthetic import make_synthetic_dataset

VERSION = "partqc-mnv3-provisional-v1"
# SPEC_ISSUE-06 of reviews/SPEC-041/r1-dev-report.md: with the smoke backbone the outputs are almost
# uniform, and at the default seed (42) the parity inputs fall below the top-2 gap of the export.
SMOKE_SEED = "0"
FILES = {
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


def read_rows(root: Path) -> list[dict[str, str]]:
    with (root / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(root: Path, rows: list[dict[str, str]]) -> None:
    with (root / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANIFEST_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


@pytest.fixture(scope="module")
def _external_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_synthetic_dataset(
        tmp_path_factory.mktemp("provisional") / "ds",
        items_per_stratum=0,
        external_items_per_stratum=1,
        labeler=AGENT_SUGGESTION_LABELER,
    )


@pytest.fixture
def external_dataset(_external_template: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(_external_template, tmp_path / "ds"))


def _args(root: Path, models: Path, *extra: str) -> list[str]:
    return [
        "--dataset-dir",
        str(root),
        "--models-root",
        str(models),
        "--external-sources",
        str(root / "external_sources.csv"),
        *extra,
    ]


def _refused(
    capfd: pytest.CaptureFixture[str], root: Path, models: Path, text: str, *extra: str
) -> str:
    capfd.readouterr()
    assert provisional.main(_args(root, models, *extra)) == 2
    err = capfd.readouterr().err
    assert text in err
    assert not models.exists() or not list(models.iterdir())
    return err


def _drop_rows(root: Path, predicate) -> None:
    rows = read_rows(root)
    for row in rows:
        if predicate(row):
            (root / row["image_path"]).unlink()
    write_rows(root, [row for row in rows if not predicate(row)])
    sources = root / "sources.csv"
    kept = {row["image_path"] for row in read_rows(root)}
    lines = sources.read_text(encoding="utf-8").splitlines()
    body = [line for line in lines[1:] if line.split(",")[0] in kept]
    sources.write_text("\n".join([lines[0], *body]) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("partqc-mnv3-provisional-v1", True),
        ("partqc-provisional-v1", True),
        ("partqc-mnv3-v1", False),
        ("partqc-mnv3-corn-v2", False),
        ("stub-v0", False),
        ("provisional", False),
    ],
)
def test_is_provisional_version(version: str, expected: bool) -> None:
    assert is_provisional_version(version) is expected
    assert config_mod.is_provisional_version is is_provisional_version


@pytest.mark.parametrize(
    "version", ["partqc-mnv3-v1", "partqc-../-provisional-v1", "Partqc-provisional-v1"]
)
def test_version_refused(
    external_dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str], version: str
) -> None:
    _refused(
        capfd,
        external_dataset,
        tmp_path / "models",
        "not a provisional model version",
        "--model-version",
        version,
    )


@pytest.mark.parametrize("which", ["dataset", "models"])
@pytest.mark.parametrize("subfolder", [False, True])
def test_paths_inside_git_refused(
    external_dataset: Path,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    which: str,
    subfolder: bool,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    inner = repository / "ml" / "data" if subfolder else repository
    inner.mkdir(parents=True, exist_ok=True)
    root, models = external_dataset, tmp_path / "models"
    if which == "dataset":
        root = Path(shutil.copytree(external_dataset, inner / "ds"))
    else:
        models = inner / "models"
    _args_list = _args(root, models)
    capfd.readouterr()
    assert provisional.main(_args_list) == 2
    assert "provisional paths must be outside a Git repository" in capfd.readouterr().err
    assert not models.exists()


def test_symlink_into_a_repository_refused(
    external_dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    repository = tmp_path / "repo"
    (repository / ".git").mkdir(parents=True)
    link = tmp_path / "models-link"
    link.symlink_to(repository, target_is_directory=True)
    capfd.readouterr()
    assert provisional.main(_args(external_dataset, link)) == 2
    assert "provisional paths must be outside a Git repository" in capfd.readouterr().err


def test_existing_model_dir_refused_untouched(
    external_dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    models = tmp_path / "models"
    (models / VERSION).mkdir(parents=True)
    kept = models / VERSION / "keep.txt"
    kept.write_text("kept", encoding="utf-8")
    capfd.readouterr()
    assert provisional.main(_args(external_dataset, models)) == 2
    assert "model directory already exists" in capfd.readouterr().err
    assert kept.read_text(encoding="utf-8") == "kept"


def test_model_dir_as_a_symlink_refused(
    external_dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    empty = tmp_path / "empty"
    empty.mkdir()
    (models / VERSION).symlink_to(empty, target_is_directory=True)
    capfd.readouterr()
    assert provisional.main(_args(external_dataset, models)) == 2
    assert "model directory already exists" in capfd.readouterr().err


def test_invalid_manifest_goes_to_stderr(
    external_dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    rows = read_rows(external_dataset)
    (external_dataset / rows[0]["image_path"]).unlink()
    captured = _refused(capfd, external_dataset, tmp_path / "models", "missing_file")
    assert "count missing_file: 1" in captured


def test_missing_manifest_exits_2(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "empty").mkdir()
    assert (
        provisional.main(
            ["--dataset-dir", str(tmp_path / "empty"), "--models-root", str(tmp_path / "m")]
        )
        == 2
    )
    assert "provisional failed" in capfd.readouterr().err


def test_own_images_refused(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=1,
        images_per_item=2,
        external_items_per_stratum=1,
        labeler=AGENT_SUGGESTION_LABELER,
    )
    own = sum(1 for row in read_rows(root) if not row["item_id"].startswith("X"))
    assert own == 22
    _refused(capfd, root, tmp_path / "models", f"provisional dataset has own images: {own}")


def test_other_labeler_in_the_manifest_refused(
    external_dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    rows = read_rows(external_dataset)
    rows[0]["labeler"] = "a"
    write_rows(external_dataset, rows)
    _refused(capfd, external_dataset, tmp_path / "m", "provisional dataset has other labelers: 1")


def _override_a(root: Path) -> dict[str, str]:
    row = next(r for r in read_rows(root) if r["grade"] and r["object_type"] == "screw")
    write_csv(
        root / "labels_overrides.csv",
        list(OVERRIDE_COLUMNS),
        [[row["image_path"], "good", "a", "second look"]],
    )
    return row


def test_other_labeler_in_the_overrides_refused(
    external_dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    _override_a(external_dataset)
    _refused(capfd, external_dataset, tmp_path / "m", "provisional dataset has other labelers: 1")


def test_other_labelers_sum_both_files(
    external_dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    override = _override_a(external_dataset)
    rows = read_rows(external_dataset)
    next(r for r in rows if r["image_path"] != override["image_path"])["labeler"] = "b"
    write_rows(external_dataset, rows)
    _refused(capfd, external_dataset, tmp_path / "m", "provisional dataset has other labelers: 2")


def test_excluded_override_is_not_counted(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """A dataset with two images in the stratum of the excluded one, so the grade stays."""
    root = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=0,
        external_items_per_stratum=2,
        labeler=AGENT_SUGGESTION_LABELER,
    )
    row = _override_a(root)
    (root / row["image_path"]).unlink()
    write_csv(root / "exclusions.csv", list(EXCLUSION_COLUMNS), [[row["image_path"], "other"]])
    err = _refused(capfd, root, tmp_path / "m", "epochs must be in [5, 10]", "--epochs", "12")
    assert "other labelers" not in err


def test_other_types_refused(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=0,
        external_items_per_stratum=1,
        external_tool_items_per_type=1,
        labeler=AGENT_SUGGESTION_LABELER,
    )
    err = _refused(capfd, root, tmp_path / "m", "provisional dataset has other types: ")
    assert "pliers" in err


def test_missing_type_refused(
    external_dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    _drop_rows(external_dataset, lambda r: r["object_type"] == "nut")
    err = _refused(
        capfd, external_dataset, tmp_path / "m", "provisional dataset needs the types: nut"
    )
    assert err.strip().endswith("types: nut")


def test_grade_without_images_refused(
    external_dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    _drop_rows(external_dataset, lambda r: r["grade"] == "unusable")
    _refused(capfd, external_dataset, tmp_path / "m", "no training image with grade unusable")


def test_epochs_out_of_range_refused(
    external_dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    for epochs in ("4", "11", "12"):
        _refused(
            capfd,
            external_dataset,
            tmp_path / "m",
            "epochs must be in [5, 10]",
            "--epochs",
            epochs,
        )


def test_refusal_order_own_images_before_labelers_before_types(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=1,
        images_per_item=1,
        external_items_per_stratum=1,
        external_tool_items_per_type=1,
    )
    err = _refused(capfd, root, tmp_path / "m", "provisional dataset has own images")
    assert "other labelers" not in err


NO_TORCH = """
import sys
sys.modules["torch"] = None
import qc_ml.provisional as provisional
assert sys.modules["torch"] is None
sys.exit(provisional.main(sys.argv[1:]))
"""


def _no_torch(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", NO_TORCH, *args],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=dict(os.environ),
    )


def test_without_torch_the_error_is_the_extra(external_dataset: Path, tmp_path: Path) -> None:
    result = _no_torch(_args(external_dataset, tmp_path / "models"))
    assert result.returncode == 2, result.stderr
    assert "training needs the train extra" in result.stderr
    assert "other labelers" not in result.stderr
    assert not (tmp_path / "models").exists()


def test_without_torch_the_labelers_are_refused_first(
    external_dataset: Path, tmp_path: Path
) -> None:
    rows = read_rows(external_dataset)
    rows[0]["labeler"] = "a"
    write_rows(external_dataset, rows)
    result = _no_torch(_args(external_dataset, tmp_path / "models"))
    assert result.returncode == 2
    assert "provisional dataset has other labelers: 1" in result.stderr


def test_module_does_not_import_torch_or_a_split_reader() -> None:
    source = Path(provisional.__file__).read_text(encoding="utf-8")
    head = source.split("def inside_git_repository", 1)[0]
    assert "import torch" not in head
    code = source.split('"""', 2)[2]
    for name in ("load_split", "rows_for", "make_split", "qc_ml.split", "qc_ml.evaluate"):
        assert name not in code, name


# ---------------------------------------------------------------------------------------------
# Guards of the official path (section 4.5)
# ---------------------------------------------------------------------------------------------


def _config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "model_version": VERSION,
                "dataset_dir": str(tmp_path / "ds"),
                "split_file": str(tmp_path / "split_v1.csv"),
            }
        ),
        encoding="utf-8",
    )
    return path


def test_train_config_refuses_a_provisional_version(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="provisional model versions are not allowed"):
        load_config(_config_file(tmp_path))


@pytest.mark.parametrize("module", [pipeline_mod, thresholds, evaluate])
def test_official_steps_exit_2(tmp_path: Path, capfd: pytest.CaptureFixture[str], module) -> None:
    assert module.main(["--config", str(_config_file(tmp_path))]) == 2
    assert "provisional model versions are not allowed" in capfd.readouterr().err


def _planted_dir(tmp_path: Path, name: str = VERSION) -> Path:
    model_dir = tmp_path / name
    model_dir.mkdir()
    (model_dir / "metrics.json").write_text(
        json.dumps({"model_version": name, "evaluated_at": "2026-11-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    (model_dir / "model.sha256").write_text("0" * 64 + "\n", encoding="ascii")
    return model_dir


def test_changelog_refuses_and_writes_nothing(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    model_dir = _planted_dir(tmp_path)
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("old\n", encoding="utf-8")
    code = report.main(["changelog", "--model-dir", str(model_dir), "--append", str(changelog)])
    assert code == 2
    captured = capfd.readouterr()
    assert "provisional model: no official report" in captured.err
    assert captured.out == ""
    assert changelog.read_text(encoding="utf-8") == "old\n"


def test_release_notes_refuses_and_writes_nothing(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    model_dir = _planted_dir(tmp_path)
    output = tmp_path / "notes.md"
    code = report.main(["release-notes", "--model-dir", str(model_dir), "--output", str(output)])
    assert code == 2
    assert "provisional model: no official report" in capfd.readouterr().err
    assert not output.exists()


def test_report_refuses_before_reading_metrics(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    model_dir = tmp_path / VERSION
    model_dir.mkdir()
    assert report.main(["changelog", "--model-dir", str(model_dir)]) == 2
    assert "provisional model: no official report" in capfd.readouterr().err


def test_report_refuses_dot_and_a_symlink_with_an_official_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    model_dir = _planted_dir(tmp_path)
    link = tmp_path / "partqc-mnv3-v1"
    link.symlink_to(model_dir, target_is_directory=True)
    assert report.main(["changelog", "--model-dir", str(link)]) == 2
    monkeypatch.chdir(model_dir)
    assert report.main(["changelog", "--model-dir", "."]) == 2
    assert capfd.readouterr().err.count("provisional model: no official report") == 2


def test_report_still_accepts_an_official_name(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    model_dir = _planted_dir(tmp_path, "partqc-mnv3-v1")
    assert report.main(["changelog", "--model-dir", str(model_dir)]) == 0
    assert "partqc-mnv3-v1" in capfd.readouterr().out


# ---------------------------------------------------------------------------------------------
# Training (slow, smoke backbone)
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def smoke_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, dict]:
    """The whole CLI once, with spies on the split functions (R-11)."""
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    pytest.importorskip("onnx")
    from qc_ml import split as split_mod

    base = tmp_path_factory.mktemp("smoke")
    root = make_synthetic_dataset(
        base / "ds",
        items_per_stratum=0,
        external_items_per_stratum=4,
        labeler=AGENT_SUGGESTION_LABELER,
    )
    calls: dict[str, int] = {}
    saved = {name: getattr(split_mod, name) for name in ("load_split", "rows_for", "make_split")}

    def spy(name: str):
        def wrapper(*args, **kwargs):
            calls[name] = calls.get(name, 0) + 1
            return saved[name](*args, **kwargs)

        return wrapper

    for name in saved:
        setattr(split_mod, name, spy(name))
    try:
        code = provisional.main(_args(root, base / "models", "--smoke", "--seed", SMOKE_SEED))
    finally:
        for name, function in saved.items():
            setattr(split_mod, name, function)
    assert code == 0
    return root, base / "models" / VERSION, calls


@pytest.mark.slow
def test_smoke_writes_exactly_the_files(smoke_run: tuple[Path, Path, dict]) -> None:
    _, model_dir, _ = smoke_run
    assert {p.name for p in model_dir.iterdir()} == FILES


@pytest.mark.slow
def test_smoke_decision_and_parity(smoke_run: tuple[Path, Path, dict]) -> None:
    from qc_ml.parity import check_parity

    _, model_dir, _ = smoke_run
    assert json.loads((model_dir / "decision.json").read_text(encoding="utf-8")) == {
        "type_threshold": 0.50,
        "unusable_threshold": 0.50,
        "grade_review_threshold": 0.60,
    }
    assert check_parity(model_dir).ok


@pytest.mark.slow
def test_smoke_edge_loads_the_directory(smoke_run: tuple[Path, Path, dict]) -> None:
    onnx_inferencer = pytest.importorskip("qc_edge.onnx_inferencer")
    _, model_dir, _ = smoke_run
    inferencer = onnx_inferencer.OnnxInferencer(model_dir)
    assert inferencer.model_info.model_version == VERSION


@pytest.mark.slow
def test_smoke_never_reads_a_split(smoke_run: tuple[Path, Path, dict]) -> None:
    root, model_dir, calls = smoke_run
    assert calls == {}
    assert not list(root.rglob("split_v*"))
    assert not list(model_dir.parent.rglob("split_v*"))


@pytest.mark.slow
def test_smoke_report(smoke_run: tuple[Path, Path, dict]) -> None:
    from qc_ml.artifacts import read_model_sha256
    from qc_ml.data import manifest_sha256

    root, model_dir, _ = smoke_run
    data = json.loads((model_dir / "provisional_report.json").read_text(encoding="utf-8"))
    assert set(data) == REPORT_KEYS
    assert data["provisional"] is True
    assert data["notice"] == NOTICE
    assert data["model_version"] == VERSION
    assert data["model_sha256"] == read_model_sha256(model_dir)
    assert data["manifest_sha256"] == manifest_sha256(root)
    assert data["decision_source"] == "fixed_defaults"
    assert data["epochs"] == 1
    assert data["smoke"] is True
    assert len(data["train_loss_by_epoch"]) == 1
    assert data["n_images"] == 44
    assert data["n_items"] == 44
    assert data["by_source"] == {"synthetic": 44}
    assert data["images_by_type_grade"]["other"] == {"none": 4}
    assert data["images_by_type_grade"]["nut"]["fair"] == 4
    assert set(data) & set(METRIC_KEYS) == {"model_version", "model_sha256", "manifest_sha256"}
    assert not [key for key in data if key.startswith("val_")]
    assert data["created_at"].endswith("+00:00")


@pytest.mark.slow
def test_smoke_labels(smoke_run: tuple[Path, Path, dict]) -> None:
    _, model_dir, _ = smoke_run
    labels = json.loads((model_dir / "labels.json").read_text(encoding="utf-8"))
    assert labels["object_types"] == ["screw", "nut", "other"]
    assert labels["ungraded_object_types"] == []


@pytest.mark.slow
def test_failure_after_writing_deletes_the_model_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    pytest.importorskip("onnx")
    from qc_ml import export as export_mod
    from qc_ml.errors import ExportError

    root = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=0,
        external_items_per_stratum=4,
        labeler=AGENT_SUGGESTION_LABELER,
    )
    real = export_mod.write_model_dir

    def broken(model, model_dir, labels):
        real(model, model_dir, labels)
        raise ExportError("parity failed for the test")

    monkeypatch.setattr(export_mod, "write_model_dir", broken)
    models = tmp_path / "deep" / "models"
    assert provisional.main(_args(root, models, "--smoke", "--seed", SMOKE_SEED)) == 2
    assert "parity failed for the test" in capfd.readouterr().err
    assert not (tmp_path / "deep").exists()


@pytest.mark.slow
def test_empty_model_dir_is_accepted(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    pytest.importorskip("onnx")
    root = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=0,
        external_items_per_stratum=4,
        labeler=AGENT_SUGGESTION_LABELER,
    )
    (tmp_path / "models" / VERSION).mkdir(parents=True)
    assert provisional.main(_args(root, tmp_path / "models", "--smoke", "--seed", SMOKE_SEED)) == 0
    assert {p.name for p in (tmp_path / "models" / VERSION).iterdir()} == FILES
