"""Author tests of SPEC-021 part B: the power tools in ``qc-ml`` (identification only).

Prefix ``T``/``XT`` and the empty grade (CA-09), ``derive_model_labels`` (CA-10), the extension of
the frozen test (CA-11), the evaluation with ``tiny_model_power_tools`` (CA-12) and the generator
(CA-13). Synthetic data only; the fixture regeneration test needs torch.
"""

from __future__ import annotations

import csv
import filecmp
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qc_contracts import GRADE_FORBIDDEN_OBJECT_TYPES, OBJECT_TYPE_LABELS_PT, ObjectType
from qc_ml import data
from qc_ml import evaluate as evaluate_mod
from qc_ml import report as report_mod
from qc_ml import split as split_mod
from qc_ml import thresholds as thresholds_mod
from qc_ml.artifacts import labels_to_dict, load_labels
from qc_ml.data import (
    KNOWN_OBJECT_TYPES,
    POWER_TOOL_OBJECT_TYPES,
    TOOL_OBJECT_TYPES,
    ModelLabels,
    build_data_report,
    derive_model_labels,
    grade_target,
    is_external_item,
    item_prefix_matches,
    load_manifest,
    tool_grade_coverage,
)
from qc_ml.errors import ManifestError
from qc_ml.evaluate import METRIC_KEYS
from qc_ml.plots import type_label_pt
from qc_ml.split import item_strata, load_split
from qc_ml.synthetic import add_synthetic_item, make_synthetic_dataset

ML = Path(__file__).resolve().parents[1]
TINY_POWER = ML / "tests" / "fixtures" / "tiny_model_power_tools"
POWER = ("angle_grinder", "saw", "drill", "cordless_screwdriver")
HAND = ("pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver")
TWELVE = ["screw", "nut", "other", *HAND, *POWER]


def _rows(root: Path) -> list[dict[str, str]]:
    with (root / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write(root: Path, rows: list[dict[str, str]]) -> None:
    with (root / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(data.MANIFEST_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _load(root: Path) -> pd.DataFrame:
    registry = root / "external_sources.csv"
    return load_manifest(root, external_sources=registry if registry.is_file() else None)


def _cli(dataset: Path, splits: Path, *extra: str) -> int:
    argv = ["--dataset-dir", str(dataset), "--splits-dir", str(splits)]
    registry = dataset / "external_sources.csv"
    if registry.is_file():
        argv += ["--external-sources", str(registry)]
    return split_mod.main([*argv, *extra])


def _split_map(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["image_path"]: row["split"] for row in csv.DictReader(fh)}


@pytest.fixture(scope="module")
def _power3(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_synthetic_dataset(
        tmp_path_factory.mktemp("power3") / "ds", power_tool_items_per_type=3
    )


@pytest.fixture
def power3(_power3: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(_power3, tmp_path / "ds"))


# ---------------------------------------------------------------------------------------------
# Constants and prefixes
# ---------------------------------------------------------------------------------------------


def test_power_tools_are_the_grade_forbidden_types_of_the_contract_but_unknown() -> None:
    assert POWER_TOOL_OBJECT_TYPES == POWER
    assert set(POWER) == {m.value for m in GRADE_FORBIDDEN_OBJECT_TYPES} - {"unknown"}
    assert list(KNOWN_OBJECT_TYPES) == TWELVE
    assert TOOL_OBJECT_TYPES == HAND  # tool_grade_coverage stays on the 5 hand tools
    assert ("other", *POWER) == data.GRADE_FORBIDDEN_DATASET_TYPES
    assert not set(POWER) & set(data.GRADE_REQUIRED_DATASET_TYPES)


@pytest.mark.parametrize(
    ("item_id", "object_type", "ok"),
    [
        ("T-010", "drill", True),
        ("XT-0010", "angle_grinder", True),
        ("T-501", "cordless_screwdriver", True),
        ("T-010", "pliers", True),
        ("S-010", "drill", False),
        ("N-010", "saw", False),
        ("O-010", "angle_grinder", False),
        ("XS-0010", "drill", False),
        ("T-010", "other", False),
    ],
)
def test_item_prefix_matches_power_tools(item_id: str, object_type: str, ok: bool) -> None:
    assert item_prefix_matches(item_id, object_type) is ok


# ---------------------------------------------------------------------------------------------
# CA-09: data
# ---------------------------------------------------------------------------------------------


def test_ca09_power_tools_load_without_error(power3: Path) -> None:
    df = load_manifest(power3)
    power = df[df["object_type"].isin(POWER)]
    items = sorted(power["item_id"].unique())
    assert len(items) == 12 and all(i.startswith("T-") for i in items)
    assert power["grade"].isna().all()
    assert all(p.split("/")[2] == "_" for p in power["image_path"])


def _set_grade(root: Path, object_type: str, grade: str) -> None:
    rows = _rows(root)
    index = next(i for i, r in enumerate(rows) if r["object_type"] == object_type)
    rows[index]["grade"] = grade
    _write(root, rows)


@pytest.mark.parametrize("object_type", POWER)
def test_ca09_power_tool_with_grade_has_the_code_of_other(power3: Path, object_type: str) -> None:
    _set_grade(power3, object_type, "good")
    with pytest.raises(ManifestError) as power_error:
        load_manifest(power3, verify_images=False)
    other_root = make_synthetic_dataset(power3.parent / "other")
    _set_grade(other_root, "other", "good")
    with pytest.raises(ManifestError) as other_error:
        load_manifest(other_root, verify_images=False)
    codes = [p.code for p in power_error.value.problems]
    assert codes == [p.code for p in other_error.value.problems] == ["grade_on_other"]
    assert object_type in power_error.value.problems[0].message


def test_override_with_a_grade_on_a_power_tool_is_refused(power3: Path) -> None:
    path = next(r["image_path"] for r in _rows(power3) if r["object_type"] == "drill")
    (power3 / "labels_overrides.csv").write_text(
        f"image_path,grade,labeler,reason\n{path},fair,b,test\n", encoding="utf-8"
    )
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(power3, verify_images=False)
    assert {p.code for p in excinfo.value.problems} == {"grade_on_other"}


def test_power_tool_with_s_prefix_is_a_prefix_mismatch(power3: Path) -> None:
    rows = _rows(power3)
    index = next(i for i, r in enumerate(rows) if r["object_type"] == "saw")
    rows[index]["item_id"] = "S-900"
    _write(power3, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(power3, verify_images=False)
    assert "item_prefix_mismatch" in {p.code for p in excinfo.value.problems}


def test_power_tools_stay_out_of_the_grade_criterion(power3: Path) -> None:
    df = load_manifest(power3)
    assert list(tool_grade_coverage(df)) == list(HAND)
    report = build_data_report(df)
    assert list(report["tool_grade_coverage"]) == list(HAND)
    for tool in POWER:
        assert report["counts"][tool] == {"none": {"total": 6}}
        assert report["items_per_grade"][tool] == {"none": 3}


# ---------------------------------------------------------------------------------------------
# CA-10: model labels and the grade target
# ---------------------------------------------------------------------------------------------


def test_ca10_power_tools_are_always_ungraded(power3: Path) -> None:
    df = load_manifest(power3)
    labels = derive_model_labels(df, df)
    assert list(labels.object_types) == ["screw", "nut", "other", *POWER]
    assert labels.ungraded_object_types == POWER
    assert grade_target("drill", None, labels) is None


def test_power_tools_are_ungraded_next_to_a_graded_hand_tool(tmp_path: Path) -> None:
    """A hand tool graded by the criterion stays graded; the power tools never are."""
    root = make_synthetic_dataset(
        tmp_path / "ds",
        images_per_item=12,
        tool_items_per_stratum=5,
        power_tool_items_per_type=1,
        include_other=True,
    )
    df = load_manifest(root, verify_images=False)
    assert all(entry["graded"] for entry in tool_grade_coverage(df).values())
    labels = derive_model_labels(df, df)
    assert list(labels.object_types) == TWELVE
    assert labels.ungraded_object_types == POWER
    assert grade_target("pliers", "good", labels) == 1


def test_power_tool_without_train_images_is_not_a_model_type(power3: Path) -> None:
    df = load_manifest(power3)
    train = df[df["object_type"] != "saw"]
    labels = derive_model_labels(df, train)
    assert "saw" not in labels.object_types
    assert labels.ungraded_object_types == ("angle_grinder", "drill", "cordless_screwdriver")


def test_ungraded_power_tools_pass_the_labels_checks(tmp_path: Path) -> None:
    labels = ModelLabels(object_types=TWELVE, ungraded_object_types=POWER)
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(labels_to_dict(labels)), encoding="utf-8")
    assert load_labels(path) == labels


# ---------------------------------------------------------------------------------------------
# CA-11: extension of the frozen test
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _ca11(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """``split_v1`` without tools, and the same dataset with 6 items per power tool and 2
    external images per power tool."""
    base = tmp_path_factory.mktemp("ca11")
    plain = make_synthetic_dataset(base / "plain")
    assert _cli(plain, base / "splits") == 0
    make_synthetic_dataset(
        base / "power", power_tool_items_per_type=6, external_power_tool_items_per_type=2
    )
    return base


@pytest.fixture
def ca11(_ca11: Path, tmp_path: Path) -> tuple[Path, Path]:
    base = Path(shutil.copytree(_ca11, tmp_path / "base"))
    return base / "power", base / "splits"


def test_ca11_power_tools_need_a_decision(ca11: tuple[Path, Path], capsys) -> None:
    dataset, splits = ca11
    assert _cli(dataset, splits) == 2
    err = capsys.readouterr().err.splitlines()
    for tool in POWER:
        assert f"new object type without decision: {tool}" in err


def test_ca11_extension_of_the_power_tools(ca11: tuple[Path, Path]) -> None:
    dataset, splits = ca11
    v1 = _split_map(splits / "split_v1.csv")
    assert _cli(dataset, splits, "--extend-test-types", ",".join(POWER)) == 0
    v2 = _split_map(splits / "split_v2.csv")
    assert all(v2[p] == s for p, s in v1.items())
    df = _load(dataset)
    for tool in POWER:
        own = df[(df["object_type"] == tool) & ~df["item_id"].map(is_external_item)]
        by_split: dict[str, set[str]] = {}
        for image_path, item_id in zip(own["image_path"], own["item_id"], strict=True):
            by_split.setdefault(v2[image_path], set()).add(item_id)
        # one stratum per type: 6 items -> 4 train, 1 val, 1 test
        assert {s: len(i) for s, i in by_split.items()} == {"train": 4, "val": 1, "test": 1}
        external = df[(df["object_type"] == tool) & df["item_id"].map(is_external_item)]
        assert len(external) == 2 and all(v2[p] == "train" for p in external["image_path"])
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    assert meta["test_extended_types"] == list(POWER)
    assert meta["deferred_types"] == []
    assert len(load_split(splits / "split_v2.csv")) == len(df)


def test_ca11_power_tool_with_two_items_is_refused(ca11: tuple[Path, Path], capsys) -> None:
    dataset, splits = ca11
    # drill: T-013..T-018 (after angle_grinder and saw); keep T-013 and T-014 only
    removed = {f"T-{n:03d}" for n in range(15, 19)}
    _write(dataset, [r for r in _rows(dataset) if r["item_id"] not in removed])
    for path in (dataset / "raw" / "drill" / "_").iterdir():
        if path.name.split("__")[0] in removed:
            path.unlink()
    own = {r["item_id"] for r in _rows(dataset) if r["object_type"] == "drill"}
    assert {i for i in own if i.startswith("T-")} == {"T-013", "T-014"}
    assert _cli(dataset, splits, "--extend-test-types", ",".join(POWER)) == 2
    assert "too few items to extend the test: drill" in capsys.readouterr().err.splitlines()
    assert not (splits / "split_v2.csv").exists()


def test_power_tools_can_be_deferred(ca11: tuple[Path, Path]) -> None:
    dataset, splits = ca11
    v1 = _split_map(splits / "split_v1.csv")
    assert _cli(dataset, splits, "--defer-types", ",".join(POWER)) == 0
    assert _split_map(splits / "split_v2.csv") == v1
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    assert meta["deferred_types"] == list(POWER)


def test_power_tool_extension_stratum_is_the_whole_type(ca11: tuple[Path, Path]) -> None:
    dataset, splits = ca11
    df = _load(dataset)
    own = df[~df["item_id"].map(is_external_item)]
    strata = item_strata(own[own["object_type"].isin(POWER)])
    assert set(strata.values()) == {(tool, "none") for tool in POWER}
    previous = load_split(splits / "split_v1.csv")
    result = split_mod.make_split(df, seed=42, previous=previous, extend_test_types=POWER)
    by_type = result.frame.merge(df[["image_path", "object_type"]], on="image_path")
    for tool in POWER:
        assert set(by_type[by_type["object_type"] == tool]["split"]) == {"train", "val", "test"}


# ---------------------------------------------------------------------------------------------
# CA-12: evaluation with the tiny_model_power_tools fixture (no torch)
# ---------------------------------------------------------------------------------------------


def test_fixture_labels_have_the_12_types_and_the_4_power_tools_ungraded() -> None:
    labels = load_labels(TINY_POWER / "labels.json")
    assert list(labels.object_types) == TWELVE
    assert labels.ungraded_object_types == POWER
    files = {p.name for p in TINY_POWER.iterdir() if p.is_file()}
    assert files == {p.name for p in (ML / "tests" / "fixtures" / "tiny_model").iterdir()}
    assert sum((TINY_POWER / name).stat().st_size for name in files) < 1_000_000


def test_fixture_parity_with_onnxruntime() -> None:
    from qc_ml.parity import check_parity

    result = check_parity(TINY_POWER)
    assert result.ok, result.message


@pytest.fixture
def power_config(_ca11: Path, tmp_path: Path) -> Path:
    base = Path(shutil.copytree(_ca11, tmp_path / "env"))
    assert _cli(base / "power", base / "splits", "--extend-test-types", ",".join(POWER)) == 0
    shutil.copytree(TINY_POWER, tmp_path / "models" / "partqc-tinypower-v1")
    config = {
        "model_version": "partqc-tinypower-v1",
        "dataset_dir": str(base / "power"),
        "split_file": str(base / "splits" / "split_v2.csv"),
        "backbone": "tiny",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(tmp_path / "models"),
        "reports_root": str(tmp_path / "reports"),
        "checkpoints_root": str(tmp_path / "checkpoints"),
        "external_sources": str(base / "power" / "external_sources.csv"),
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_ca12_evaluate_with_power_tools(power_config: Path) -> None:
    assert thresholds_mod.main(["--config", str(power_config)]) == 0
    assert evaluate_mod.main(["--config", str(power_config), "--latency-machine", "ci"]) == 0
    model_dir = power_config.parent / "models" / "partqc-tinypower-v1"
    metrics = json.loads((model_dir / "metrics.json").read_text(encoding="utf-8"))
    assert list(metrics) == list(METRIC_KEYS)
    assert np.asarray(metrics["type_confusion"]).shape == (12, 12)
    assert metrics["labels"]["object_types"] == TWELVE
    assert metrics["labels"]["ungraded_object_types"] == list(POWER)
    assert not set(metrics["tool_grade_metrics"]) & set(POWER)
    for tool in POWER:
        counts = metrics["counts"]["test"]["by_class"][tool]
        assert counts["n_items"] == 1 and counts["by_grade"] == {}
    # grade metrics stay on screw/nut (ADR-022, decision 6)
    assert int(np.asarray(metrics["grade_confusion"]).sum()) == sum(
        metrics["counts"]["test"]["by_class"][t]["n_images"] for t in ("screw", "nut")
    )
    assert "few test items for drill: 1" in metrics["warnings"]


# ---------------------------------------------------------------------------------------------
# CA-13 and the generator
# ---------------------------------------------------------------------------------------------


def test_ca13_defaults_are_byte_for_byte_the_same(tmp_path: Path) -> None:
    a = make_synthetic_dataset(tmp_path / "a")
    b = make_synthetic_dataset(
        tmp_path / "b", power_tool_items_per_type=0, external_power_tool_items_per_type=0
    )
    files_a = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    assert files_a == files_b
    _, mismatch, errors = filecmp.cmpfiles(a, b, [str(p) for p in files_a], shallow=False)
    assert mismatch == [] and errors == []


def test_power_tools_come_after_every_other_item(tmp_path: Path) -> None:
    kwargs = {"tool_items_per_stratum": 1, "external_tool_items_per_type": 1}
    a = make_synthetic_dataset(tmp_path / "a", **kwargs)
    b = make_synthetic_dataset(
        tmp_path / "b", **kwargs, power_tool_items_per_type=2, external_power_tool_items_per_type=1
    )
    rows_a, rows_b = _rows(a), _rows(b)
    assert rows_b[: len(rows_a)] == rows_a
    for row in rows_a:
        assert (a / row["image_path"]).read_bytes() == (b / row["image_path"]).read_bytes()
    extra = rows_b[len(rows_a) :]
    assert [r["object_type"] for r in extra] == [t for t in POWER for _ in range(4)] + list(POWER)
    own = [r["item_id"] for r in extra if not r["item_id"].startswith("X")]
    assert own[0] == "T-026" and own[-1] == "T-033"  # after the 25 hand tool items
    assert [r["item_id"] for r in extra if r["item_id"].startswith("X")] == [
        "XT-0006",
        "XT-0007",
        "XT-0008",
        "XT-0009",
    ]
    assert all(r["grade"] == "" for r in extra)
    with (b / "sources.csv").open(encoding="utf-8", newline="") as fh:
        sources = {r["image_path"]: r for r in csv.DictReader(fh)}
    for row in extra:
        if row["item_id"].startswith("X"):
            assert sources[row["image_path"]]["origin"] == "external"
        else:
            assert row["image_path"] not in sources
    _load(b)  # valid


def test_external_power_tools_alone_write_the_registry(tmp_path: Path) -> None:
    root = make_synthetic_dataset(tmp_path / "ds", external_power_tool_items_per_type=1)
    assert (root / "external_sources.csv").is_file()
    df = _load(root)
    assert sorted(df[df["item_id"].str.startswith("XT-")]["object_type"]) == sorted(POWER)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"power_tool_items_per_type": -1},
        {"external_power_tool_items_per_type": -1},
        {"power_tool_items_per_type": 250},  # 1000 T- items
        {"tool_items_per_stratum": 39, "power_tool_items_per_type": 7},  # 975 + 28 T- items
        {"external_tool_items_per_type": 1600, "external_power_tool_items_per_type": 500},
    ],
)
def test_generator_checks_the_power_tool_counts(tmp_path: Path, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        make_synthetic_dataset(tmp_path / "ds", **kwargs)


def test_add_synthetic_item_draws_a_power_tool(power3: Path) -> None:
    paths = add_synthetic_item(power3, "T-900", "drill", None, n_images=2)
    assert all(p.startswith("raw/drill/_/T-900__") for p in paths)
    assert len(load_manifest(power3)) == len(_rows(power3))


# ---------------------------------------------------------------------------------------------
# Plots and CHANGELOG
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("member", [ObjectType(t) for t in POWER])
def test_confusion_labels_of_the_power_tools(member: ObjectType) -> None:
    assert type_label_pt(member.value) == OBJECT_TYPE_LABELS_PT[member]
    assert type_label_pt("drill") == "furadeira"


def test_changelog_lists_a_model_with_power_tools_only() -> None:
    labels = ModelLabels(
        object_types=("screw", "nut", "other", *POWER), ungraded_object_types=POWER
    )
    metrics = {
        "model_version": "partqc-mnv3-v3",
        "model_sha256": "a" * 64,
        "evaluated_at": "2026-11-25T13:00:00+00:00",
        "type_accuracy": 0.9,
        "labels": labels_to_dict(labels),
    }
    lines = report_mod.changelog_entry(metrics).splitlines()
    types_line = (
        "- Tipos do modelo: screw, nut, other, angle_grinder, saw, drill, cordless_screwdriver; "
        "sem grau: angle_grinder, saw, drill, cordless_screwdriver."
    )
    assert types_line in lines
    assert report_mod.TYPE_ACCURACY_NOTE in lines


# ---------------------------------------------------------------------------------------------
# Fixture regeneration (torch)
# ---------------------------------------------------------------------------------------------


def test_make_tiny_fixture_with_power_tools(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("onnx")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    for option, expected in (("--with-power-tools", TINY_POWER), ("--with-tools", None)):
        out = tmp_path / option.strip("-")
        proc = subprocess.run(
            [
                sys.executable,
                str(ML / "scripts" / "make_tiny_fixture.py"),
                option,
                "--out",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        labels = json.loads((out / "labels.json").read_text(encoding="utf-8"))
        if expected is not None:
            assert (out / "labels.json").read_bytes() == (expected / "labels.json").read_bytes()
        else:  # SPEC-016: still the 8 types, without the power tools
            assert labels["object_types"] == TWELVE[:8]
            assert labels["ungraded_object_types"] == ["allen_key"]
    both = subprocess.run(
        [
            sys.executable,
            str(ML / "scripts" / "make_tiny_fixture.py"),
            "--with-tools",
            "--with-power-tools",
            "--out",
            str(tmp_path / "both"),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
        check=False,
    )
    assert both.returncode == 2
