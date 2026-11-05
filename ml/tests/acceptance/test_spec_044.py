"""Acceptance tests for SPEC-044 (qc-ml: hammer, wrench and spirit level, identification only).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-10 to CA-14 (part B). CA-15 is manual (production) and is recorded as
pending in the test report. Tests named ``test_extra_*`` are exploratory edge cases around
SPEC-044 section 3.1 (part B) that no CA spells out.

Rules followed (``docs/architecture.md`` §10, R-11, R-14): every dataset is synthetic
(``make_synthetic_dataset``) and lives under a temporary directory; nothing under ``ml/data/`` is
read; the split CLI runs as ``python -m qc_ml.split`` in a subprocess (never pytest).

"New tools added" (CA-13): ``split_v1`` reads the dataset generated without them, the extension
reads the dataset generated with the same parameters plus ``identified_tool_items_per_type``
(the fixture checks first that every row of the first dataset is in the second, same bytes).
"""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qc_ml import data as data_mod
from qc_ml.data import (
    GRADE_FORBIDDEN_DATASET_TYPES,
    IDENTIFIED_TOOL_OBJECT_TYPES,
    ITEM_PREFIX_TYPES,
    KNOWN_OBJECT_TYPES,
    POWER_TOOL_OBJECT_TYPES,
    build_data_report,
    derive_model_labels,
    grade_target,
    load_manifest,
    tool_grade_coverage,
)
from qc_ml.errors import ManifestError
from qc_ml.synthetic import make_synthetic_dataset

pytestmark = pytest.mark.acceptance

HAND_TOOLS = (
    "pliers",
    "adjustable_wrench",
    "allen_key",
    "flat_screwdriver",
    "phillips_screwdriver",
)
POWER_TOOLS = ("angle_grinder", "saw", "drill", "cordless_screwdriver")
NEW_TOOLS = ("hammer", "wrench", "spirit_level")
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


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


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


def load(root: Path):  # noqa: ANN201 - pandas DataFrame
    return load_manifest(root, external_sources=root / "external_sources.csv")


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


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["HF_HUB_OFFLINE"] = "1"
    return env


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
    return subprocess.run(
        [sys.executable, "-m", "qc_ml.split", *args],
        cwd=splits.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        env=_env(),
        check=False,
    )


def read_split(path: Path) -> dict[str, str]:
    return {r["image_path"]: r["split"] for r in read_csv_rows(path)}


def items_by_split(split_map: dict[str, str], object_type: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {w: set() for w in SPLITS}
    for path, which in split_map.items():
        if type_of(path) == object_type:
            out[which].add(item_of(path))
    return out


def gen(factory: pytest.TempPathFactory, name: str, **kwargs: Any) -> Path:
    return make_synthetic_dataset(factory.mktemp(name) / "ds", **kwargs)


def _codes(info: pytest.ExceptionInfo[ManifestError]) -> set[str]:
    return {p.code for p in info.value.problems}


def _edit_first(root: Path, object_type: str, **changes: str) -> None:
    rows = manifest_rows(root)
    idx = next(i for i, r in enumerate(rows) if r["object_type"] == object_type)
    rows[idx].update(changes)
    write_csv_rows(root / "manifest.csv", MANIFEST_HEADER, rows)


# --------------------------------------------------------------------------------------------
# Templates (generated once per module)
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def t_base(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(tmp_path_factory, "s044_base")


@pytest.fixture(scope="module")
def t_new3(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(tmp_path_factory, "s044_new3", identified_tool_items_per_type=3)


@pytest.fixture(scope="module")
def t_new6(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(tmp_path_factory, "s044_new6", identified_tool_items_per_type=6)


@pytest.fixture(scope="module")
def t_power3(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gen(tmp_path_factory, "s044_power3", power_tool_items_per_type=3)


# --------------------------------------------------------------------------------------------
# CA-10
# --------------------------------------------------------------------------------------------


def test_ca10_power_and_identified_tool_tuples() -> None:
    assert POWER_TOOL_OBJECT_TYPES == POWER_TOOLS
    assert IDENTIFIED_TOOL_OBJECT_TYPES == NEW_TOOLS


def test_ca10_new_tools_are_the_last_three_known_types() -> None:
    assert tuple(KNOWN_OBJECT_TYPES)[-3:] == NEW_TOOLS
    assert tuple(KNOWN_OBJECT_TYPES) == (
        "screw",
        "nut",
        "other",
        *HAND_TOOLS,
        *POWER_TOOLS,
        *NEW_TOOLS,
    )


def test_ca10_new_tools_in_the_t_prefix_and_grade_forbidden() -> None:
    t_types = ITEM_PREFIX_TYPES["T"]
    for tool in NEW_TOOLS:
        assert tool in t_types, (tool, t_types)
        assert tool in GRADE_FORBIDDEN_DATASET_TYPES, tool


def test_ca10_tool_grade_coverage_keys_are_the_hand_tools(t_new3: Path, t_base: Path) -> None:
    for root in (t_new3, t_base):
        coverage = tool_grade_coverage(load(root))
        assert set(coverage) == set(HAND_TOOLS), set(coverage)


# --------------------------------------------------------------------------------------------
# CA-11
# --------------------------------------------------------------------------------------------


def test_ca11_new_tools_load_with_9_t_items_in_no_grade_dirs(t_new3: Path) -> None:
    df = load(t_new3)
    new = df[df["object_type"].isin(NEW_TOOLS)]
    items = set(new["item_id"])
    assert len(items) == 9
    assert all(str(i).startswith("T-") for i in items)
    for tool in NEW_TOOLS:
        sub = new[new["object_type"] == tool]
        assert sub["item_id"].nunique() == 3, tool
        for path in sub["image_path"]:
            assert str(path).startswith(f"raw/{tool}/_/"), path
            assert (t_new3 / str(path)).is_file()
    grades = {g for g in new["grade"] if g is not None and g == g and g != ""}
    assert grades == set()


def test_ca11_hammer_with_grade_is_grade_on_other(t_new3: Path, tmp_path: Path) -> None:
    root = copy_dataset(t_new3, tmp_path / "ds")
    _edit_first(root, "hammer", grade="good")
    with pytest.raises(ManifestError) as info:
        load(root)
    assert "grade_on_other" in _codes(info)


def test_ca11_power_tools_alone_are_still_12_t_items(t_power3: Path) -> None:
    df = load(t_power3)
    t_items = {i for i in df["item_id"] if str(i).startswith("T-")}
    power = df[df["object_type"].isin(POWER_TOOLS)]
    power_items = set(power["item_id"])
    assert len(power_items) == 12
    assert all(str(i).startswith("T-") for i in power_items)
    assert df[df["object_type"].isin(NEW_TOOLS)].empty
    # The other T- items, if any, are hand tools of the default generator (SPEC-016).
    others = t_items - power_items
    assert set(df[df["item_id"].isin(others)]["object_type"]) <= set(HAND_TOOLS)


# --------------------------------------------------------------------------------------------
# CA-12
# --------------------------------------------------------------------------------------------


def test_ca12_model_labels_end_with_the_new_tools_all_ungraded(t_new3: Path) -> None:
    df = load(t_new3)
    labels = derive_model_labels(df, df)
    assert tuple(labels.object_types)[-3:] == NEW_TOOLS
    assert set(NEW_TOOLS) <= set(labels.ungraded_object_types)
    assert grade_target("hammer", "good", labels) is None


# --------------------------------------------------------------------------------------------
# CA-13
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ca13(tmp_path_factory: pytest.TempPathFactory, t_base: Path, t_new6: Path) -> SimpleNamespace:
    root = tmp_path_factory.mktemp("s044_ca13")
    base = copy_dataset(t_base, root / "base")
    new = copy_dataset(t_new6, root / "new")
    base_rows = {tuple(r.values()) for r in manifest_rows(base)}
    new_rows = {tuple(r.values()) for r in manifest_rows(new)}
    assert base_rows <= new_rows
    assert all(r[2] in NEW_TOOLS for r in new_rows - base_rows)
    for r in manifest_rows(base):
        assert (base / r["image_path"]).read_bytes() == (new / r["image_path"]).read_bytes()
    splits = root / "splits"
    v1 = split_cli(base, splits)
    assert v1.returncode == 0, v1.stdout + v1.stderr
    ext = split_cli(new, splits, "--extend-test-types", ",".join(NEW_TOOLS))
    return SimpleNamespace(root=root, base=base, new=new, splits=splits, ext=ext)


def test_ca13_extension_with_the_new_tools_exits_0(ca13: SimpleNamespace) -> None:
    assert ca13.ext.returncode == 0, ca13.ext.stdout + ca13.ext.stderr


def test_ca13_each_new_tool_in_train_val_and_test(ca13: SimpleNamespace) -> None:
    assert ca13.ext.returncode == 0, ca13.ext.stdout + ca13.ext.stderr
    v2 = read_split(ca13.splits / "split_v2.csv")
    for tool in NEW_TOOLS:
        by_split = items_by_split(v2, tool)
        assert all(by_split[w] for w in SPLITS), (tool, by_split)
        assert sum(len(s) for s in by_split.values()) == 6, tool
        # R-11: no item in two splits.
        assert not (by_split["train"] & by_split["val"]), tool
        assert not (by_split["train"] & by_split["test"]), tool
        assert not (by_split["val"] & by_split["test"]), tool


def test_ca13_no_small_stratum_warning_for_hammer_grades(ca13: SimpleNamespace) -> None:
    assert ca13.ext.returncode == 0
    texts = [ca13.ext.stdout, ca13.ext.stderr]
    meta_path = ca13.splits / "split_v2.json"
    if meta_path.exists():
        texts.append(meta_path.read_text(encoding="utf-8"))
    for text in texts:
        for line in text.splitlines():
            if "small_stratum" in line:
                for grade in GRADES:
                    assert f"hammer/{grade}" not in line, line


def test_ca13_split_v1_rows_keep_their_split(ca13: SimpleNamespace) -> None:
    assert ca13.ext.returncode == 0
    v1 = read_split(ca13.splits / "split_v1.csv")
    v2 = read_split(ca13.splits / "split_v2.csv")
    for path, which in v1.items():
        assert v2[path] == which, path


# --------------------------------------------------------------------------------------------
# CA-14
# --------------------------------------------------------------------------------------------


def test_ca14_defaults_are_byte_for_byte_the_same(tmp_path: Path) -> None:
    a = make_synthetic_dataset(tmp_path / "a")
    b = make_synthetic_dataset(
        tmp_path / "b",
        identified_tool_items_per_type=0,
        external_identified_tool_items_per_type=0,
    )
    snap_a, snap_b = snapshot(a), snapshot(b)
    assert snap_a and set(snap_a) == set(snap_b)
    for name in snap_a:
        assert snap_a[name] == snap_b[name], name


# --------------------------------------------------------------------------------------------
# Extras
# --------------------------------------------------------------------------------------------


def test_extra_ungraded_tools_are_the_grade_forbidden_group_but_unknown() -> None:
    from qc_contracts import GRADE_FORBIDDEN_OBJECT_TYPES

    contract = {m.value for m in GRADE_FORBIDDEN_OBJECT_TYPES} - {"unknown"}
    assert contract == set(POWER_TOOLS) | set(NEW_TOOLS)
    assert not set(NEW_TOOLS) & set(data_mod.TOOL_OBJECT_TYPES)


def test_extra_build_data_report_keeps_hand_tool_coverage(t_new3: Path) -> None:
    report = build_data_report(load(t_new3))
    assert set(report["tool_grade_coverage"]) == set(HAND_TOOLS)


@pytest.mark.parametrize("grade", GRADES)
@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_extra_any_grade_on_any_new_tool_is_grade_on_other(
    t_new3: Path, tmp_path: Path, tool: str, grade: str
) -> None:
    root = copy_dataset(t_new3, tmp_path / "ds")
    _edit_first(root, tool, grade=grade)
    with pytest.raises(ManifestError) as info:
        load(root)
    assert "grade_on_other" in _codes(info)


@pytest.mark.parametrize("prefix", ["S", "N", "O"])
def test_extra_new_tool_with_a_non_t_prefix_is_a_prefix_mismatch(
    t_new3: Path, tmp_path: Path, prefix: str
) -> None:
    root = copy_dataset(t_new3, tmp_path / "ds")
    rows = manifest_rows(root)
    idx = next(i for i, r in enumerate(rows) if r["object_type"] == "wrench")
    rows[idx]["object_type"] = {"S": "screw", "N": "nut", "O": "other"}[prefix]
    rows[idx]["grade"] = "" if prefix == "O" else "good"
    write_csv_rows(root / "manifest.csv", MANIFEST_HEADER, rows)
    with pytest.raises(ManifestError) as info:
        load(root)
    assert "item_prefix_mismatch" in _codes(info)


def test_extra_new_rows_come_after_every_earlier_row(t_base: Path, t_new3: Path) -> None:
    base = manifest_rows(t_base)
    new = manifest_rows(t_new3)
    assert new[: len(base)] == base
    assert all(r["object_type"] in NEW_TOOLS for r in new[len(base) :])


def test_extra_new_tools_come_after_the_power_tools(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds", power_tool_items_per_type=1, identified_tool_items_per_type=1
    )
    rows = manifest_rows(root)
    kinds = [r["object_type"] for r in rows]
    last_power = max(i for i, t in enumerate(kinds) if t in POWER_TOOLS)
    first_new = min(i for i, t in enumerate(kinds) if t in NEW_TOOLS)
    assert first_new > last_power
    power_nums = sorted(int(r["item_id"][2:]) for r in rows if r["object_type"] in POWER_TOOLS)
    new_nums = sorted(int(r["item_id"][2:]) for r in rows if r["object_type"] in NEW_TOOLS)
    assert new_nums[0] > power_nums[-1]
    load(root)


def test_extra_external_new_tools_are_xt_without_grade(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds",
        identified_tool_items_per_type=1,
        external_identified_tool_items_per_type=2,
    )
    df = load(root)
    new = df[df["object_type"].isin(NEW_TOOLS)]
    xt = {i for i in new["item_id"] if str(i).startswith("XT-")}
    t = {i for i in new["item_id"] if str(i).startswith("T-")}
    assert len(xt) == 6 and len(t) == 3
    for path in new["image_path"]:
        assert str(path).split("/")[2] == "_", path
    assert (root / "external_sources.csv").is_file()


def test_extra_labels_without_hammer_train_images_skip_it(t_new3: Path) -> None:
    df = load(t_new3)
    train = df[df["object_type"] != "hammer"]
    labels = derive_model_labels(df, train)
    assert "hammer" not in labels.object_types
    assert tuple(labels.object_types)[-2:] == ("wrench", "spirit_level")
    assert "hammer" not in labels.ungraded_object_types
    assert {"wrench", "spirit_level"} <= set(labels.ungraded_object_types)


def test_extra_new_tools_with_power_tools_are_all_ungraded(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds", power_tool_items_per_type=1, identified_tool_items_per_type=1
    )
    df = load(root)
    labels = derive_model_labels(df, df)
    assert tuple(labels.object_types)[-7:] == (*POWER_TOOLS, *NEW_TOOLS)
    assert set(POWER_TOOLS) | set(NEW_TOOLS) <= set(labels.ungraded_object_types)
    for tool in (*POWER_TOOLS, *NEW_TOOLS):
        assert grade_target(tool, None, labels) is None


@pytest.mark.parametrize("value", [-1, 1.5, "3"])
def test_extra_invalid_identified_tool_counts_are_refused(tmp_path: Path, value: Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        make_synthetic_dataset(tmp_path / "ds", identified_tool_items_per_type=value)


def test_extra_extension_with_two_hammers_is_refused(
    t_base: Path, t_new6: Path, tmp_path: Path
) -> None:
    base = copy_dataset(t_base, tmp_path / "base")
    new = copy_dataset(t_new6, tmp_path / "new")
    splits = tmp_path / "splits"
    assert split_cli(base, splits).returncode == 0
    rows = manifest_rows(new)
    hammers = sorted({r["item_id"] for r in rows if r["object_type"] == "hammer"})
    keep = set(hammers[:2])
    kept = [r for r in rows if r["object_type"] != "hammer" or r["item_id"] in keep]
    for r in rows:
        if r not in kept:
            (new / r["image_path"]).unlink()
    write_csv_rows(new / "manifest.csv", MANIFEST_HEADER, kept)
    before = snapshot(splits)
    proc = split_cli(new, splits, "--extend-test-types", ",".join(NEW_TOOLS))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "hammer" in proc.stderr
    assert snapshot(splits) == before


def test_extra_plot_labels_of_the_new_tools() -> None:
    """Section 3.1: ``qc_ml.plots`` needs no change; the PT-BR labels come from the contract."""
    from qc_ml import plots

    expected = {"hammer": "martelo", "wrench": "chave de aperto", "spirit_level": "nível"}
    for tool, label in expected.items():
        assert plots.type_label_pt(tool) == label, tool
