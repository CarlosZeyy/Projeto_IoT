"""The ``labeler`` ``agent-suggestion`` is barred from every official dataset (SPEC-041 4.9).

Synthetic data only, in ``tmp_path``.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from qc_ml import data, evaluate, split, thresholds
from qc_ml.data import (
    AGENT_SUGGESTION_LABELER,
    EXCLUSION_COLUMNS,
    MANIFEST_COLUMNS,
    OVERRIDE_COLUMNS,
    load_manifest,
)
from qc_ml.errors import ManifestError
from qc_ml.synthetic import make_synthetic_dataset

CODE = "agent_suggestion_label"
MESSAGE = "agent-suggested labels are only allowed in the provisional set (ADR-024)"
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


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _mark_first_row(root: Path) -> dict[str, str]:
    rows = read_rows(root)
    rows[0]["labeler"] = AGENT_SUGGESTION_LABELER
    write_rows(root, rows)
    return rows[0]


def _write_override(root: Path, row: dict[str, str]) -> None:
    write_csv(
        root / "labels_overrides.csv",
        list(OVERRIDE_COLUMNS),
        [[row["image_path"], "good", AGENT_SUGGESTION_LABELER, "second look"]],
    )


def _exclude(root: Path, row: dict[str, str]) -> None:
    (root / row["image_path"]).unlink()
    write_csv(root / "exclusions.csv", list(EXCLUSION_COLUMNS), [[row["image_path"], "other"]])


def test_constant_value() -> None:
    assert AGENT_SUGGESTION_LABELER == "agent-suggestion"


def test_manifest_row_is_refused_by_default(dataset: Path) -> None:
    row = _mark_first_row(dataset)
    with pytest.raises(ManifestError) as info:
        load_manifest(dataset)
    problems = [p for p in info.value.problems if p.code == CODE]
    assert len(problems) == 1
    assert problems[0].file == "manifest.csv"
    assert problems[0].image_path == row["image_path"]
    assert problems[0].message == MESSAGE


def test_manifest_row_is_accepted_with_the_argument(dataset: Path) -> None:
    _mark_first_row(dataset)
    df = load_manifest(dataset, allow_agent_suggestion=True)
    assert AGENT_SUGGESTION_LABELER in set(df["labeler"])


def test_excluded_manifest_row_is_not_a_problem(dataset: Path) -> None:
    row = _mark_first_row(dataset)
    _exclude(dataset, row)
    assert row["image_path"] not in set(load_manifest(dataset)["image_path"])


def test_override_line_is_refused_with_its_file(dataset: Path) -> None:
    _write_override(dataset, read_rows(dataset)[0])
    with pytest.raises(ManifestError) as info:
        load_manifest(dataset)
    problems = [p for p in info.value.problems if p.code == CODE]
    assert [p.file for p in problems] == ["labels_overrides.csv"]


def test_override_line_of_an_unknown_image_keeps_both_problems(dataset: Path) -> None:
    write_csv(
        dataset / "labels_overrides.csv",
        list(OVERRIDE_COLUMNS),
        [["raw/screw/good/none.jpg", "good", AGENT_SUGGESTION_LABELER, "second look"]],
    )
    with pytest.raises(ManifestError) as info:
        load_manifest(dataset)
    assert {p.code for p in info.value.problems} == {CODE, "override_unknown_image"}


def test_override_line_is_accepted_with_the_argument(dataset: Path) -> None:
    row = next(r for r in read_rows(dataset) if r["grade"] == "perfect")
    _write_override(dataset, row)
    df = load_manifest(dataset, allow_agent_suggestion=True)
    assert df.loc[df["image_path"] == row["image_path"], "grade"].item() == "good"


def test_validate_prints_on_stdout_and_split_on_stderr(
    dataset: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    _mark_first_row(dataset)
    assert data.main(["validate", "--dataset-dir", str(dataset)]) == 2
    assert CODE in capfd.readouterr().out
    splits = tmp_path / "splits"
    assert split.main(["--dataset-dir", str(dataset), "--splits-dir", str(splits)]) == 2
    assert CODE in capfd.readouterr().err
    assert not list(splits.glob("split_v*"))


def test_validate_passes_after_section_8_1(dataset: Path) -> None:
    row = read_rows(dataset)[0]
    _write_override(dataset, row)
    assert data.main(["validate", "--dataset-dir", str(dataset)]) == 2
    _exclude(dataset, row)
    assert data.main(["validate", "--dataset-dir", str(dataset)]) == 0


def test_thresholds_and_evaluate_refuse(
    tiny_config: Path, split_dataset: tuple[Path, Path], capfd: pytest.CaptureFixture[str]
) -> None:
    dataset_dir, _ = split_dataset
    _mark_first_row(dataset_dir)
    config = json.loads(tiny_config.read_text(encoding="utf-8"))
    model_dir = Path(config["models_root"]) / TINY_VERSION
    shutil.copy(TINY_MODEL / "decision.json", model_dir / "decision.json")
    (model_dir / "metrics.json").unlink(missing_ok=True)
    assert thresholds.main(["--config", str(tiny_config)]) == 2
    assert CODE in capfd.readouterr().err
    assert evaluate.main(["--config", str(tiny_config)]) == 2
    assert CODE in capfd.readouterr().err
    assert not (model_dir / "metrics.json").exists()


@pytest.mark.slow
def test_pipeline_refuses(tiny_config: Path, split_dataset: tuple[Path, Path]) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    pytest.importorskip("onnx")
    from qc_ml import pipeline

    dataset_dir, _ = split_dataset
    _mark_first_row(dataset_dir)
    assert pipeline.main(["--config", str(tiny_config)]) == 2


def test_synthetic_labeler_goes_to_every_row(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds", items_per_stratum=1, images_per_item=1, labeler=AGENT_SUGGESTION_LABELER
    )
    with (root / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        assert {row["labeler"] for row in csv.DictReader(fh)} == {AGENT_SUGGESTION_LABELER}


def test_synthetic_only_external(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds", items_per_stratum=0, external_items_per_stratum=1
    )
    assert {row["item_id"][0] for row in read_rows(root)} == {"X"}
    with pytest.raises(ValueError, match="items_per_stratum"):
        make_synthetic_dataset(tmp_path / "no", items_per_stratum=0)
    with pytest.raises(ValueError, match="items_per_stratum"):
        make_synthetic_dataset(tmp_path / "ne", items_per_stratum=-1, external_items_per_stratum=1)


def test_synthetic_defaults_are_byte_identical(tmp_path: Path) -> None:
    plain = make_synthetic_dataset(tmp_path / "a", items_per_stratum=1, images_per_item=1)
    explicit = make_synthetic_dataset(
        tmp_path / "b", items_per_stratum=1, images_per_item=1, labeler="a"
    )
    assert (plain / "manifest.csv").read_bytes() == (explicit / "manifest.csv").read_bytes()
