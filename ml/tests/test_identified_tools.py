"""Author tests of SPEC-044 part B: hammer, wrench and spirit level in ``qc-ml``.

Identification-only tools (ADR-025), never graded, like the power tools of SPEC-021: constants,
prefix ``T``/``XT`` and the empty grade (CA-10, CA-11), ``derive_model_labels`` (CA-12), the
extension of the frozen test (CA-13) and the generator (CA-14). Synthetic data only; no torch.
"""

from __future__ import annotations

import csv
import filecmp
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from qc_contracts import GRADE_FORBIDDEN_OBJECT_TYPES, OBJECT_TYPE_LABELS_PT, ObjectType
from qc_ml import data
from qc_ml import report as report_mod
from qc_ml import split as split_mod
from qc_ml.artifacts import labels_to_dict, load_labels
from qc_ml.data import (
    GRADE_FORBIDDEN_DATASET_TYPES,
    GRADE_REQUIRED_DATASET_TYPES,
    IDENTIFIED_TOOL_OBJECT_TYPES,
    ITEM_PREFIX_TYPES,
    KNOWN_OBJECT_TYPES,
    POWER_TOOL_OBJECT_TYPES,
    TOOL_OBJECT_TYPES,
    UNGRADED_TOOL_OBJECT_TYPES,
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
from qc_ml.plots import type_label_pt
from qc_ml.split import item_strata, load_split
from qc_ml.synthetic import add_synthetic_item, make_synthetic_dataset

IDENTIFIED = ("hammer", "wrench", "spirit_level")
POWER = ("angle_grinder", "saw", "drill", "cordless_screwdriver")
HAND = ("pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver")
FIFTEEN = ["screw", "nut", "other", *HAND, *POWER, *IDENTIFIED]


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


def _set_grade(root: Path, object_type: str, grade: str) -> None:
    rows = _rows(root)
    index = next(i for i, r in enumerate(rows) if r["object_type"] == object_type)
    rows[index]["grade"] = grade
    _write(root, rows)


@pytest.fixture(scope="module")
def _ident3(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_synthetic_dataset(
        tmp_path_factory.mktemp("ident3") / "ds", identified_tool_items_per_type=3
    )


@pytest.fixture
def ident3(_ident3: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(_ident3, tmp_path / "ds"))


# ---------------------------------------------------------------------------------------------
# CA-10: constants
# ---------------------------------------------------------------------------------------------


def test_ca10_constants() -> None:
    assert POWER_TOOL_OBJECT_TYPES == POWER
    assert IDENTIFIED_TOOL_OBJECT_TYPES == IDENTIFIED
    assert (*POWER, *IDENTIFIED) == UNGRADED_TOOL_OBJECT_TYPES
    assert list(KNOWN_OBJECT_TYPES) == FIFTEEN
    assert KNOWN_OBJECT_TYPES[-3:] == IDENTIFIED
    assert set(IDENTIFIED) <= ITEM_PREFIX_TYPES["T"]
    assert set(IDENTIFIED) <= set(GRADE_FORBIDDEN_DATASET_TYPES)
    assert ("other", *POWER, *IDENTIFIED) == GRADE_FORBIDDEN_DATASET_TYPES
    assert not set(IDENTIFIED) & set(GRADE_REQUIRED_DATASET_TYPES)
    assert TOOL_OBJECT_TYPES == HAND


def test_known_types_follow_the_object_type_of_the_contract() -> None:
    """The dataset types are the contract types but ``unknown``, with ``other`` after ``nut``."""
    contract = [m.value for m in ObjectType if m is not ObjectType.UNKNOWN]
    assert sorted(KNOWN_OBJECT_TYPES) == sorted([*contract, "other"])
    assert [t for t in KNOWN_OBJECT_TYPES if t != "other"] == contract


def test_ungraded_tools_are_the_grade_forbidden_group_of_the_contract_but_unknown() -> None:
    forbidden = {m.value for m in GRADE_FORBIDDEN_OBJECT_TYPES} - {ObjectType.UNKNOWN.value}
    assert set(UNGRADED_TOOL_OBJECT_TYPES) == forbidden


def test_identified_tools_mirror_the_edge_lists() -> None:
    collect = pytest.importorskip("qc_edge.collect")
    assert tuple(collect.IDENTIFIED_TOOL_OBJECT_TYPES) == IDENTIFIED
    assert tuple(collect.POWER_TOOL_OBJECT_TYPES) == POWER


def test_ca10_grade_coverage_keeps_the_hand_tools_only(ident3: Path) -> None:
    df = load_manifest(ident3)
    assert list(tool_grade_coverage(df)) == list(HAND)
    report = build_data_report(df)
    assert list(report["tool_grade_coverage"]) == list(HAND)
    for tool in IDENTIFIED:
        assert report["counts"][tool] == {"none": {"total": 6}}
        assert report["items_per_grade"][tool] == {"none": 3}


@pytest.mark.parametrize(
    ("item_id", "object_type", "ok"),
    [
        ("T-010", "hammer", True),
        ("XT-0010", "wrench", True),
        ("T-501", "spirit_level", True),
        ("S-010", "hammer", False),
        ("N-010", "wrench", False),
        ("O-010", "spirit_level", False),
        ("XN-0010", "hammer", False),
    ],
)
def test_item_prefix_matches_identified_tools(item_id: str, object_type: str, ok: bool) -> None:
    assert item_prefix_matches(item_id, object_type) is ok


# ---------------------------------------------------------------------------------------------
# CA-11: data
# ---------------------------------------------------------------------------------------------


def test_ca11_identified_tools_load_without_error(ident3: Path) -> None:
    df = load_manifest(ident3)
    tools = df[df["object_type"].isin(IDENTIFIED)]
    items = sorted(tools["item_id"].unique())
    assert len(items) == 9 and all(i.startswith("T-") for i in items)
    assert tools["grade"].isna().all()
    for object_type, path in zip(tools["object_type"], tools["image_path"], strict=True):
        assert path.startswith(f"raw/{object_type}/_/")


@pytest.mark.parametrize("object_type", IDENTIFIED)
def test_ca11_identified_tool_with_grade_is_grade_on_other(ident3: Path, object_type: str) -> None:
    _set_grade(ident3, object_type, "good")
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ident3, verify_images=False)
    assert [p.code for p in excinfo.value.problems] == ["grade_on_other"]
    assert object_type in excinfo.value.problems[0].message


def test_override_with_a_grade_on_an_identified_tool_is_refused(ident3: Path) -> None:
    path = next(r["image_path"] for r in _rows(ident3) if r["object_type"] == "wrench")
    (ident3 / "labels_overrides.csv").write_text(
        f"image_path,grade,labeler,reason\n{path},fair,b,test\n", encoding="utf-8"
    )
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ident3, verify_images=False)
    assert {p.code for p in excinfo.value.problems} == {"grade_on_other"}


def test_identified_tool_with_o_prefix_is_a_prefix_mismatch(ident3: Path) -> None:
    rows = _rows(ident3)
    index = next(i for i, r in enumerate(rows) if r["object_type"] == "spirit_level")
    rows[index]["item_id"] = "O-900"
    _write(ident3, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ident3, verify_images=False)
    assert "item_prefix_mismatch" in {p.code for p in excinfo.value.problems}


def test_ca11_power_tools_alone_are_still_12_items(tmp_path: Path) -> None:
    df = load_manifest(make_synthetic_dataset(tmp_path / "ds", power_tool_items_per_type=3))
    tools = df[df["item_id"].str.startswith("T-")]
    assert set(tools["object_type"]) == set(POWER)
    assert tools["item_id"].nunique() == 12


# ---------------------------------------------------------------------------------------------
# CA-12: model labels and the grade target
# ---------------------------------------------------------------------------------------------


def test_ca12_identified_tools_are_always_ungraded(ident3: Path) -> None:
    df = load_manifest(ident3)
    labels = derive_model_labels(df, df)
    assert list(labels.object_types) == ["screw", "nut", "other", *IDENTIFIED]
    assert labels.object_types[-3:] == IDENTIFIED
    assert labels.ungraded_object_types == IDENTIFIED
    assert grade_target("hammer", "good", labels) is None
    assert grade_target("wrench", None, labels) is None
    assert grade_target("screw", "good", labels) == 1


def test_all_15_types_next_to_a_graded_hand_tool(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds",
        images_per_item=12,
        tool_items_per_stratum=5,
        power_tool_items_per_type=1,
        identified_tool_items_per_type=1,
    )
    df = load_manifest(root, verify_images=False)
    assert all(entry["graded"] for entry in tool_grade_coverage(df).values())
    labels = derive_model_labels(df, df)
    assert list(labels.object_types) == FIFTEEN
    assert labels.ungraded_object_types == (*POWER, *IDENTIFIED)
    assert grade_target("pliers", "good", labels) == 1


def test_identified_tool_without_train_images_is_not_a_model_type(ident3: Path) -> None:
    df = load_manifest(ident3)
    labels = derive_model_labels(df, df[df["object_type"] != "wrench"])
    assert "wrench" not in labels.object_types
    assert labels.ungraded_object_types == ("hammer", "spirit_level")


def test_labels_with_the_identified_tools_round_trip(tmp_path: Path) -> None:
    labels = ModelLabels(object_types=FIFTEEN, ungraded_object_types=(*POWER, *IDENTIFIED))
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(labels_to_dict(labels)), encoding="utf-8")
    assert load_labels(path) == labels


# ---------------------------------------------------------------------------------------------
# CA-13: extension of the frozen test
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _ca13(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """``split_v1`` without tools, and the same dataset with 6 items per identified tool and 2
    external images per identified tool."""
    base = tmp_path_factory.mktemp("ca13")
    plain = make_synthetic_dataset(base / "plain")
    assert _cli(plain, base / "splits") == 0
    make_synthetic_dataset(
        base / "ident",
        identified_tool_items_per_type=6,
        external_identified_tool_items_per_type=2,
    )
    return base


@pytest.fixture
def ca13(_ca13: Path, tmp_path: Path) -> tuple[Path, Path]:
    base = Path(shutil.copytree(_ca13, tmp_path / "base"))
    return base / "ident", base / "splits"


def test_ca13_identified_tools_need_a_decision(ca13: tuple[Path, Path], capsys) -> None:
    dataset, splits = ca13
    assert _cli(dataset, splits) == 2
    err = capsys.readouterr().err.splitlines()
    for tool in IDENTIFIED:
        assert f"new object type without decision: {tool}" in err


def test_ca13_extension_of_the_identified_tools(ca13: tuple[Path, Path]) -> None:
    dataset, splits = ca13
    v1 = _split_map(splits / "split_v1.csv")
    assert _cli(dataset, splits, "--extend-test-types", ",".join(IDENTIFIED)) == 0
    v2 = _split_map(splits / "split_v2.csv")
    assert all(v2[p] == s for p, s in v1.items())
    df = _load(dataset)
    for tool in IDENTIFIED:
        own = df[(df["object_type"] == tool) & ~df["item_id"].map(is_external_item)]
        by_split: dict[str, set[str]] = {}
        for image_path, item_id in zip(own["image_path"], own["item_id"], strict=True):
            by_split.setdefault(v2[image_path], set()).add(item_id)
        # one stratum per type: 6 items -> 4 train, 1 val, 1 test
        assert {s: len(i) for s, i in by_split.items()} == {"train": 4, "val": 1, "test": 1}
        external = df[(df["object_type"] == tool) & df["item_id"].map(is_external_item)]
        assert len(external) == 2 and all(v2[p] == "train" for p in external["image_path"])
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    assert meta["test_extended_types"] == list(IDENTIFIED)
    assert meta["deferred_types"] == []
    for warning in meta["warnings"]:
        stratum = str(warning.get("stratum", ""))
        assert not any(stratum.startswith(f"{tool}/") for tool in IDENTIFIED), warning
    assert len(load_split(splits / "split_v2.csv")) == len(df)


def test_identified_tool_extension_stratum_is_the_whole_type(ca13: tuple[Path, Path]) -> None:
    dataset, splits = ca13
    df = _load(dataset)
    own = df[~df["item_id"].map(is_external_item)]
    strata = item_strata(own[own["object_type"].isin(IDENTIFIED)])
    assert set(strata.values()) == {(tool, "none") for tool in IDENTIFIED}
    previous = load_split(splits / "split_v1.csv")
    result = split_mod.make_split(df, seed=42, previous=previous, extend_test_types=IDENTIFIED)
    by_type = result.frame.merge(df[["image_path", "object_type"]], on="image_path")
    for tool in IDENTIFIED:
        assert set(by_type[by_type["object_type"] == tool]["split"]) == {"train", "val", "test"}
    assert not any(str(w.get("stratum", "")).startswith(IDENTIFIED) for w in result.warnings), (
        result.warnings
    )


def test_identified_tool_with_two_items_is_refused(ca13: tuple[Path, Path], capsys) -> None:
    dataset, splits = ca13
    # wrench: T-007..T-012 (after the 6 hammers); keep T-007 and T-008 only
    removed = {f"T-{n:03d}" for n in range(9, 13)}
    _write(dataset, [r for r in _rows(dataset) if r["item_id"] not in removed])
    for path in (dataset / "raw" / "wrench" / "_").iterdir():
        if path.name.split("__")[0] in removed:
            path.unlink()
    own = {r["item_id"] for r in _rows(dataset) if r["object_type"] == "wrench"}
    assert {i for i in own if i.startswith("T-")} == {"T-007", "T-008"}
    assert _cli(dataset, splits, "--extend-test-types", ",".join(IDENTIFIED)) == 2
    assert "too few items to extend the test: wrench" in capsys.readouterr().err.splitlines()
    assert not (splits / "split_v2.csv").exists()


def test_identified_tools_can_be_deferred(ca13: tuple[Path, Path]) -> None:
    dataset, splits = ca13
    v1 = _split_map(splits / "split_v1.csv")
    assert _cli(dataset, splits, "--defer-types", ",".join(IDENTIFIED)) == 0
    assert _split_map(splits / "split_v2.csv") == v1
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    assert meta["deferred_types"] == list(IDENTIFIED)


# ---------------------------------------------------------------------------------------------
# CA-14 and the generator
# ---------------------------------------------------------------------------------------------


def test_ca14_defaults_are_byte_for_byte_the_same(tmp_path: Path) -> None:
    a = make_synthetic_dataset(tmp_path / "a")
    b = make_synthetic_dataset(
        tmp_path / "b", identified_tool_items_per_type=0, external_identified_tool_items_per_type=0
    )
    files_a = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    assert files_a == files_b
    _, mismatch, errors = filecmp.cmpfiles(a, b, [str(p) for p in files_a], shallow=False)
    assert mismatch == [] and errors == []


def test_identified_tools_come_after_the_power_tools(tmp_path: Path) -> None:
    kwargs = {
        "tool_items_per_stratum": 1,
        "external_tool_items_per_type": 1,
        "power_tool_items_per_type": 1,
        "external_power_tool_items_per_type": 1,
    }
    a = make_synthetic_dataset(tmp_path / "a", **kwargs)
    b = make_synthetic_dataset(
        tmp_path / "b",
        **kwargs,
        identified_tool_items_per_type=2,
        external_identified_tool_items_per_type=1,
    )
    rows_a, rows_b = _rows(a), _rows(b)
    assert rows_b[: len(rows_a)] == rows_a
    for row in rows_a:
        assert (a / row["image_path"]).read_bytes() == (b / row["image_path"]).read_bytes()
    extra = rows_b[len(rows_a) :]
    assert [r["object_type"] for r in extra] == [t for t in IDENTIFIED for _ in range(4)] + list(
        IDENTIFIED
    )
    own = [r["item_id"] for r in extra if not r["item_id"].startswith("X")]
    assert own[0] == "T-030" and own[-1] == "T-035"  # after 25 hand and 4 power tool items
    assert [r["item_id"] for r in extra if r["item_id"].startswith("X")] == [
        "XT-0010",
        "XT-0011",
        "XT-0012",
    ]
    assert all(r["grade"] == "" for r in extra)
    assert all(r["image_path"].split("/")[2] == "_" for r in extra)
    with (b / "sources.csv").open(encoding="utf-8", newline="") as fh:
        sources = {r["image_path"]: r for r in csv.DictReader(fh)}
    for row in extra:
        if row["item_id"].startswith("X"):
            assert sources[row["image_path"]]["origin"] == "external"
        else:
            assert row["image_path"] not in sources
    _load(b)  # valid


def test_external_identified_tools_alone_write_the_registry(tmp_path: Path) -> None:
    root = make_synthetic_dataset(tmp_path / "ds", external_identified_tool_items_per_type=1)
    assert (root / "external_sources.csv").is_file()
    df = _load(root)
    assert sorted(df[df["item_id"].str.startswith("XT-")]["object_type"]) == sorted(IDENTIFIED)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"identified_tool_items_per_type": -1},
        {"external_identified_tool_items_per_type": -1},
        {"identified_tool_items_per_type": 334},  # 1002 T- items
        {"power_tool_items_per_type": 248, "identified_tool_items_per_type": 3},  # 992 + 9
        {"tool_items_per_stratum": 39, "identified_tool_items_per_type": 9},  # 975 + 27
        {"external_power_tool_items_per_type": 2499, "external_identified_tool_items_per_type": 2},
    ],
)
def test_generator_checks_the_identified_tool_counts(tmp_path: Path, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        make_synthetic_dataset(tmp_path / "ds", **kwargs)


@pytest.mark.parametrize("object_type", IDENTIFIED)
def test_add_synthetic_item_draws_an_identified_tool(ident3: Path, object_type: str) -> None:
    paths = add_synthetic_item(ident3, "T-900", object_type, None, n_images=2)
    assert all(p.startswith(f"raw/{object_type}/_/T-900__") for p in paths)
    assert len(load_manifest(ident3)) == len(_rows(ident3))


def test_identified_tool_silhouettes_differ() -> None:
    """Each identified tool has its own drawing (not the circle of ``other``)."""
    from qc_ml.synthetic import TOOL_POLYGONS

    shapes = [TOOL_POLYGONS[t] for t in IDENTIFIED]
    assert len({repr(s) for s in shapes}) == 3
    assert not {repr(s) for s in shapes} & {repr(TOOL_POLYGONS[t]) for t in (*HAND, *POWER)}


# ---------------------------------------------------------------------------------------------
# Plots and CHANGELOG
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("member", [ObjectType(t) for t in IDENTIFIED])
def test_confusion_labels_of_the_identified_tools(member: ObjectType) -> None:
    assert type_label_pt(member.value) == OBJECT_TYPE_LABELS_PT[member]


def test_confusion_labels_in_pt_br() -> None:
    assert [type_label_pt(t) for t in IDENTIFIED] == ["martelo", "chave de aperto", "nível"]


def test_changelog_lists_a_model_with_identified_tools_only() -> None:
    labels = ModelLabels(
        object_types=("screw", "nut", "other", *IDENTIFIED), ungraded_object_types=IDENTIFIED
    )
    metrics = {
        "model_version": "partqc-mnv3-v4",
        "model_sha256": "a" * 64,
        "evaluated_at": "2026-11-25T13:00:00+00:00",
        "type_accuracy": 0.9,
        "labels": labels_to_dict(labels),
    }
    lines = report_mod.changelog_entry(metrics).splitlines()
    types_line = (
        "- Tipos do modelo: screw, nut, other, hammer, wrench, spirit_level; "
        "sem grau: hammer, wrench, spirit_level."
    )
    assert types_line in lines
    assert report_mod.TYPE_ACCURACY_NOTE in lines
