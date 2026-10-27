"""Acceptance tests for SPEC-021 (qc-ml: the 4 power tools, identification only, ADR-021/ADR-022).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-09 to CA-13 (CA-14 is manual: photos of the power tools and real
training, recorded as pending in the test report). Tests named ``test_extra_*`` are exploratory
edge cases around SPEC-021 section 3.1 (part B) that no CA spells out.

Rules followed (``docs/architecture.md`` §10, R-11, R-14): every dataset is synthetic
(``make_synthetic_dataset``) and lives under a temporary directory; nothing under ``ml/data/`` is
read; the split CLI runs as ``python -m qc_ml.split`` in a subprocess (never pytest); the
evaluation uses the ONNX fixture ``tiny_model_power_tools`` (no torch).

"Power tools added" (CA-11, CA-12): the split versions are written in one ``splits`` directory;
``split_v1`` reads the dataset generated without tools, the next ones read the dataset generated
with the same parameters plus ``power_tool_items_per_type`` (each fixture checks first that every
row of the dataset without tools is in the dataset with the power tools, with the same bytes).
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from qc_ml import evaluate as evaluate_mod
from qc_ml import thresholds as thresholds_mod
from qc_ml.data import (
    KNOWN_OBJECT_TYPES,
    TOOL_OBJECT_TYPES,
    build_data_report,
    derive_model_labels,
    grade_target,
    load_manifest,
)
from qc_ml.errors import ManifestError
from qc_ml.synthetic import make_synthetic_dataset

pytestmark = pytest.mark.acceptance

REPO_ROOT = Path(__file__).resolve().parents[3]
ML_ROOT = REPO_ROOT / "ml"
TINY_POWER = ML_ROOT / "tests" / "fixtures" / "tiny_model_power_tools"
TINY_VERSION = "partqc-tiny021-v1"
HAND_TOOLS = (
    "pliers",
    "adjustable_wrench",
    "allen_key",
    "flat_screwdriver",
    "phillips_screwdriver",
)
POWER_TOOLS = ("angle_grinder", "saw", "drill", "cordless_screwdriver")
GRADES = ("perfect", "good", "fair", "poor", "unusable")
SPLITS = ("train", "val", "test")
MANIFEST_HEADER = [
    "image_path",
    "item_id",
    "object_type",
    "grade",
    "labeler",
    "angle",
    "captured_at",
    "capture_device",
    "notes",
]
SOURCES_HEADER = ["image_path", "origin", "contributor", "source_id", "source_ref", "input_sha256"]
# Top-level keys of metrics.json in SPEC-016 (SPEC-012 section 4.7 plus tool_grade_metrics).
METRIC_KEYS_016 = {
    "model_version",
    "model_sha256",
    "evaluated_at",
    "split_file",
    "split_sha256",
    "manifest_sha256",
    "labels",
    "decision",
    "type_accuracy",
    "type_confusion",
    "grade_qwk",
    "grade_mae",
    "grade_off_by_one_accuracy",
    "grade_confusion",
    "grade_per_class",
    "unusable_recall",
    "unusable_precision",
    "defective_recall",
    "defective_precision",
    "unknown_rate_on_other",
    "false_unknown_rate",
    "needs_review_rate",
    "latency_ms_p50",
    "latency_ms_p95",
    "latency_machine",
    "latency_runs",
    "counts",
    "grade_qwk_ci95",
    "unusable_recall_ci95",
    "defective_recall_ci95",
    "n_items_test_by_grade",
    "warnings",
    "tool_grade_metrics",
}


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


def _inside(path: Path, root: Path) -> Path:
    resolved = Path(path).resolve()
    assert resolved.is_relative_to(Path(root).resolve()), f"{resolved} is outside {root}"
    return resolved


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv_rows(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def manifest_rows(root: Path) -> list[dict[str, str]]:
    return read_csv_rows(root / "manifest.csv")


def item_of(image_path: str) -> str:
    return Path(image_path).name.split("__")[0]


def type_of(image_path: str) -> str:
    return image_path.split("/")[1]


def drop_rows(root: Path, keep) -> int:  # noqa: ANN001 - predicate over a manifest row
    """Remove from ``root`` the manifest rows where ``keep(row)`` is false (files and sources)."""
    rows = manifest_rows(root)
    kept = [r for r in rows if keep(r)]
    removed = {r["image_path"] for r in rows if not keep(r)}
    for rel in removed:
        _inside(root / rel, root).unlink()
    write_csv_rows(root / "manifest.csv", MANIFEST_HEADER, kept)
    sources = root / "sources.csv"
    if sources.exists():
        src_rows = [r for r in read_csv_rows(sources) if r["image_path"] not in removed]
        write_csv_rows(sources, SOURCES_HEADER, src_rows)
    return len(removed)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["HF_HUB_OFFLINE"] = "1"
    return env


def run_module(module: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        env=_env(),
        check=False,
    )


def split_cli(dataset: Path, splits: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    args = [
        "--dataset-dir",
        str(dataset),
        "--splits-dir",
        str(splits),
        "--seed",
        "42",
        "--external-sources",
        str(dataset / "external_sources.csv"),
        *extra,
    ]
    return run_module("qc_ml.split", args, cwd=splits.parent)


def read_split(path: Path) -> dict[str, str]:
    return {r["image_path"]: r["split"] for r in read_csv_rows(path)}


def items_by_split(split_map: dict[str, str], object_type: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {w: set() for w in SPLITS}
    for path, which in split_map.items():
        if type_of(path) == object_type:
            out[which].add(item_of(path))
    return out


def snapshot(path: Path) -> dict[str, bytes]:
    if not path.exists():
        return {}
    return {
        p.relative_to(path).as_posix(): p.read_bytes()
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def copy_dataset(template: Path, dest: Path) -> Path:
    return Path(shutil.copytree(template, dest))


def assert_power_dataset_extends(base: Path, power: Path) -> None:
    """Precondition of "power tools added": every base row is in the power dataset, same bytes."""
    base_rows = {tuple(r.values()) for r in manifest_rows(base)}
    power_rows = {tuple(r.values()) for r in manifest_rows(power)}
    assert base_rows <= power_rows
    extra = power_rows - base_rows
    assert extra and all(r[2] in POWER_TOOLS for r in extra)
    for r in manifest_rows(base):
        assert (base / r["image_path"]).read_bytes() == (power / r["image_path"]).read_bytes()


def load(root: Path):  # noqa: ANN201 - pandas DataFrame
    return load_manifest(root, external_sources=root / "external_sources.csv")


def gen(factory: pytest.TempPathFactory, name: str, **kwargs: Any) -> Path:
    return make_synthetic_dataset(factory.mktemp(name) / "ds", **kwargs)


# --------------------------------------------------------------------------------------------
# Templates (generated once per module)
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def t_base(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(tmp_path_factory, "s021_base")


@pytest.fixture(scope="module")
def t_power3(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(tmp_path_factory, "s021_power3", power_tool_items_per_type=3)


@pytest.fixture(scope="module")
def t_power6(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(tmp_path_factory, "s021_power6", power_tool_items_per_type=6)


# --------------------------------------------------------------------------------------------
# CA-09
# --------------------------------------------------------------------------------------------


def test_ca09_power_tools_load_with_12_t_items(t_power3: Path, tmp_path: Path) -> None:
    root = copy_dataset(t_power3, tmp_path / "ds")
    df = load(root)
    power = df[df["object_type"].isin(POWER_TOOLS)]
    items = set(power["item_id"])
    assert len(items) == 12
    assert all(str(i).startswith("T-") for i in items)
    for tool in POWER_TOOLS:
        assert power[power["object_type"] == tool]["item_id"].nunique() == 3, tool
    grades = {g for g in power["grade"] if g is not None and g == g and g != ""}
    assert grades == set()


def _problem_codes(excinfo: pytest.ExceptionInfo[ManifestError]) -> set[str]:
    return {p.code for p in excinfo.value.problems}


def _edit_first(root: Path, object_type: str, grade: str) -> None:
    rows = manifest_rows(root)
    idx = next(i for i, r in enumerate(rows) if r["object_type"] == object_type)
    rows[idx]["grade"] = grade
    write_csv_rows(root / "manifest.csv", MANIFEST_HEADER, rows)


def test_ca09_power_tool_with_grade_has_the_code_of_other_with_grade(
    t_power3: Path, tmp_path: Path
) -> None:
    other_root = copy_dataset(t_power3, tmp_path / "other")
    _edit_first(other_root, "other", "good")
    with pytest.raises(ManifestError) as other_info:
        load(other_root)
    power_root = copy_dataset(t_power3, tmp_path / "power")
    _edit_first(power_root, "drill", "good")
    with pytest.raises(ManifestError) as power_info:
        load(power_root)
    assert _problem_codes(power_info) == _problem_codes(other_info)
    assert len(power_info.value.problems) == len(other_info.value.problems)


# --------------------------------------------------------------------------------------------
# CA-10
# --------------------------------------------------------------------------------------------


def test_ca10_model_labels_end_with_the_power_tools_all_ungraded(t_power3: Path) -> None:
    df = load(t_power3)
    labels = derive_model_labels(df, df)
    assert tuple(labels.object_types)[-4:] == POWER_TOOLS
    assert set(POWER_TOOLS) <= set(labels.ungraded_object_types)
    assert grade_target("drill", None, labels) is None


# --------------------------------------------------------------------------------------------
# CA-11
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ca11(tmp_path_factory: pytest.TempPathFactory, t_base: Path, t_power6: Path) -> SimpleNamespace:
    root = tmp_path_factory.mktemp("s021_ca11")
    base = copy_dataset(t_base, root / "base")
    power = copy_dataset(t_power6, root / "power")
    assert_power_dataset_extends(base, power)
    splits = root / "splits"
    v1 = split_cli(base, splits)
    assert v1.returncode == 0, v1.stdout + v1.stderr
    ext = split_cli(power, splits, "--extend-test-types", ",".join(POWER_TOOLS))
    return SimpleNamespace(root=root, base=base, power=power, splits=splits, ext=ext)


def test_ca11_extend_the_test_with_the_power_tools(ca11: SimpleNamespace) -> None:
    assert ca11.ext.returncode == 0, ca11.ext.stdout + ca11.ext.stderr
    v1 = read_split(ca11.splits / "split_v1.csv")
    v2 = read_split(ca11.splits / "split_v2.csv")
    for tool in POWER_TOOLS:
        by_split = items_by_split(v2, tool)
        assert all(by_split[w] for w in SPLITS), (tool, by_split)
        assert sum(len(s) for s in by_split.values()) == 6, tool
    for path, which in v1.items():
        assert v2[path] == which, path
    meta = json.loads((ca11.splits / "split_v2.json").read_text(encoding="utf-8"))
    assert sorted(meta["test_extended_types"]) == sorted(POWER_TOOLS)


def test_ca11_power_tool_with_two_items_is_refused(
    t_base: Path, t_power6: Path, tmp_path: Path
) -> None:
    base = copy_dataset(t_base, tmp_path / "base")
    power = copy_dataset(t_power6, tmp_path / "power")
    splits = tmp_path / "splits"
    assert split_cli(base, splits).returncode == 0
    saws = sorted({r["item_id"] for r in manifest_rows(power) if r["object_type"] == "saw"})
    keep = set(saws[:2])
    drop_rows(power, lambda r: r["object_type"] != "saw" or r["item_id"] in keep)
    before = snapshot(splits)
    proc = split_cli(power, splits, "--extend-test-types", ",".join(POWER_TOOLS))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "too few items to extend the test" in proc.stderr
    assert "saw" in proc.stderr
    assert snapshot(splits) == before


# --------------------------------------------------------------------------------------------
# CA-12
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ca12(ca11: SimpleNamespace, tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    assert ca11.ext.returncode == 0, ca11.ext.stdout + ca11.ext.stderr
    root = tmp_path_factory.mktemp("s021_ca12")
    config = {
        "model_version": TINY_VERSION,
        "dataset_dir": str(ca11.power),
        "split_file": str(ca11.splits / "split_v2.csv"),
        "backbone": "tiny",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(root / "models"),
        "reports_root": str(root / "reports"),
        "checkpoints_root": str(root / "checkpoints"),
        "external_sources": str(ca11.power / "external_sources.csv"),
    }
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    model_dir = root / "models" / TINY_VERSION
    shutil.copytree(TINY_POWER, model_dir)
    rc_t = thresholds_mod.main(["--config", str(config_path)])
    rc_e = evaluate_mod.main(["--config", str(config_path)])
    metrics_path = model_dir / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    return SimpleNamespace(root=root, rc_t=rc_t, rc_e=rc_e, model_dir=model_dir, metrics=metrics)


def test_ca12_evaluate_with_the_power_tools(ca12: SimpleNamespace) -> None:
    assert ca12.rc_t == 0
    assert ca12.rc_e == 0
    m = ca12.metrics
    assert np.asarray(m["type_confusion"]).shape == (12, 12)
    assert set(POWER_TOOLS) <= set(m["labels"]["ungraded_object_types"])
    assert not set(m["tool_grade_metrics"]) & set(POWER_TOOLS), m["tool_grade_metrics"]
    assert set(m) == METRIC_KEYS_016, set(m) ^ METRIC_KEYS_016


# --------------------------------------------------------------------------------------------
# CA-13
# --------------------------------------------------------------------------------------------


def test_ca13_defaults_are_byte_for_byte_the_same(tmp_path: Path) -> None:
    a = make_synthetic_dataset(tmp_path / "a")
    b = make_synthetic_dataset(
        tmp_path / "b", power_tool_items_per_type=0, external_power_tool_items_per_type=0
    )
    snap_a, snap_b = snapshot(a), snapshot(b)
    assert snap_a and set(snap_a) == set(snap_b)
    for name in snap_a:
        assert snap_a[name] == snap_b[name], name


# --------------------------------------------------------------------------------------------
# Extras
# --------------------------------------------------------------------------------------------


def test_extra_known_types_and_hand_tool_group() -> None:
    assert ("screw", "nut", "other", *HAND_TOOLS, *POWER_TOOLS) == KNOWN_OBJECT_TYPES
    assert TOOL_OBJECT_TYPES == HAND_TOOLS


def test_extra_tool_grade_coverage_keeps_only_the_hand_tools(t_power3: Path) -> None:
    report = build_data_report(load(t_power3))
    assert set(report["tool_grade_coverage"]) == set(HAND_TOOLS)


def test_extra_power_tool_with_s_prefix_is_a_prefix_mismatch(
    t_power3: Path, tmp_path: Path
) -> None:
    root = copy_dataset(t_power3, tmp_path / "ds")
    rows = manifest_rows(root)
    idx = next(i for i, r in enumerate(rows) if r["object_type"] == "saw")
    rows[idx]["object_type"] = "screw"
    rows[idx]["grade"] = "good"
    write_csv_rows(root / "manifest.csv", MANIFEST_HEADER, rows)
    with pytest.raises(ManifestError) as info:
        load(root)
    assert "item_prefix_mismatch" in _problem_codes(info)


def test_extra_external_power_tools_are_xt_without_grade(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds", power_tool_items_per_type=1, external_power_tool_items_per_type=2
    )
    df = load(root)
    power = df[df["object_type"].isin(POWER_TOOLS)]
    xt = {i for i in power["item_id"] if str(i).startswith("XT-")}
    t = {i for i in power["item_id"] if str(i).startswith("T-")}
    assert len(xt) == 8 and len(t) == 4
    for path in power["image_path"]:
        assert str(path).split("/")[2] == "_", path


def test_extra_power_rows_come_after_every_earlier_row(t_base: Path, t_power3: Path) -> None:
    base = manifest_rows(t_base)
    power = manifest_rows(t_power3)
    assert power[: len(base)] == base
    assert all(r["object_type"] in POWER_TOOLS for r in power[len(base) :])


def test_extra_labels_without_power_train_images_skip_them(t_power3: Path) -> None:
    df = load(t_power3)
    train = df[~df["object_type"].isin(["saw"])]
    labels = derive_model_labels(df, train)
    assert "saw" not in labels.object_types
    assert tuple(labels.object_types)[-3:] == ("angle_grinder", "drill", "cordless_screwdriver")
    assert "saw" not in labels.ungraded_object_types


def test_extra_fixture_labels_have_the_12_types(tmp_path: Path) -> None:
    labels = json.loads((TINY_POWER / "labels.json").read_text(encoding="utf-8"))
    assert labels["object_types"] == ["screw", "nut", "other", *HAND_TOOLS, *POWER_TOOLS]
    assert sorted(labels["ungraded_object_types"]) == sorted(POWER_TOOLS)
