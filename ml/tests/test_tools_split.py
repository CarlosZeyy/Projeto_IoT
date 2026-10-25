"""Author tests of SPEC-016 section 4.7 (ADR-022): extension and deferral of the frozen test.

``--extend-test-types``, ``--defer-types``, the ``split_v<N>.json`` keys and the readers of the
split ignoring a deferred type. Synthetic data only, no torch.
"""

from __future__ import annotations

import csv
import json
import logging
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from qc_ml import split
from qc_ml.data import (
    GRADES,
    TOOL_OBJECT_TYPES,
    build_data_report,
    is_external_item,
    load_manifest,
    tool_grade_coverage,
)
from qc_ml.errors import SplitError
from qc_ml.split import (
    deferred_type_counts,
    load_split,
    make_split,
    new_object_types,
    rows_for,
    type_decision_problems,
)
from qc_ml.synthetic import add_synthetic_item, make_synthetic_dataset

TOOLS = ",".join(TOOL_OBJECT_TYPES)


def _cli(dataset: Path, splits: Path, *extra: str) -> int:
    argv = ["--dataset-dir", str(dataset), "--splits-dir", str(splits)]
    registry = dataset / "external_sources.csv"
    if registry.is_file():
        argv += ["--external-sources", str(registry)]
    return split.main([*argv, *extra])


def _split_map(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["image_path"]: row["split"] for row in csv.DictReader(fh)}


def _meta(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load(root: Path) -> pd.DataFrame:
    registry = root / "external_sources.csv"
    return load_manifest(root, external_sources=registry if registry.is_file() else None)


@pytest.fixture(scope="module")
def _ca15(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """``split_v1`` of the dataset without tools, and the same dataset with the tools added
    (4 items per tool x grade, 2 external items per tool)."""
    base = tmp_path_factory.mktemp("ca15")
    plain = make_synthetic_dataset(base / "plain", items_per_stratum=20, images_per_item=3)
    assert _cli(plain, base / "splits") == 0
    make_synthetic_dataset(
        base / "tools",
        items_per_stratum=20,
        images_per_item=3,
        tool_items_per_stratum=4,
        external_tool_items_per_type=2,
    )
    return base


@pytest.fixture
def ca15(_ca15: Path, tmp_path: Path) -> tuple[Path, Path]:
    base = Path(shutil.copytree(_ca15, tmp_path / "base"))
    return base / "tools", base / "splits"


def test_ca15a_new_types_need_a_decision(ca15: tuple[Path, Path], capsys) -> None:
    dataset, splits = ca15
    assert _cli(dataset, splits) == 2
    err = capsys.readouterr().err.splitlines()
    for tool in TOOL_OBJECT_TYPES:
        assert f"new object type without decision: {tool}" in err
    assert sorted(p.name for p in splits.iterdir()) == [
        "split_v1.csv",
        "split_v1.json",
        "split_v1.sha256",
    ]


def test_ca15_defer_extend_and_freeze(ca15: tuple[Path, Path], capsys) -> None:
    dataset, splits = ca15
    v1 = _split_map(splits / "split_v1.csv")
    # (b) deferred: no T image, the decision recorded, the CSV equal to v1
    assert _cli(dataset, splits, "--defer-types", TOOLS) == 0
    v2 = _split_map(splits / "split_v2.csv")
    assert not any("/T-" in p or "/XT-" in p for p in v2)
    assert v2 == v1
    meta2 = _meta(splits / "split_v2.json")
    assert meta2["deferred_types"] == list(TOOL_OBJECT_TYPES)
    assert meta2["test_extended_types"] == []
    # the same deferral again changes nothing
    capsys.readouterr()
    assert _cli(dataset, splits, "--defer-types", TOOLS) == 0
    assert "split unchanged: split_v2" in capsys.readouterr().out
    # (c) extension
    assert _cli(dataset, splits, "--extend-test-types", TOOLS) == 0
    v3 = _split_map(splits / "split_v3.csv")
    meta3 = _meta(splits / "split_v3.json")
    assert meta3["test_extended_types"] == list(TOOL_OBJECT_TYPES)
    assert meta3["deferred_types"] == []
    assert all(v3[p] == s for p, s in v1.items())
    df = _load(dataset)
    split_df = load_split(splits / "split_v3.csv")
    for tool in TOOL_OBJECT_TYPES:
        own = df[(df["object_type"] == tool) & ~df["item_id"].map(is_external_item)]
        assert {v3[p] for p in own["image_path"]} == {"train", "val", "test"}, tool
    # CA-20: no item in two splits, no external image outside train
    by_item: dict[str, set[str]] = {}
    for image_path, item_id in zip(df["image_path"], df["item_id"], strict=True):
        by_item.setdefault(item_id, set()).add(v3[image_path])
    assert all(len(s) == 1 for s in by_item.values())
    external = df[df["item_id"].str.startswith("XT-")]["image_path"]
    assert len(external) == 10 and all(v3[p] == "train" for p in external)
    assert len(rows_for(df, split_df, "test")) > len([p for p, s in v1.items() if s == "test"])
    # (d) a new pliers item after the extension never goes to test
    added = add_synthetic_item(dataset, "T-101", "pliers", "good", n_images=3)
    capsys.readouterr()
    assert _cli(dataset, splits) == 0
    v4 = _split_map(splits / "split_v4.csv")
    assert {v4[p] for p in added} <= {"train", "val"}
    assert all(v4[p] == s for p, s in v3.items())
    assert _meta(splits / "split_v4.json")["test_extended_types"] == []
    # an extended type is not new any more
    assert _cli(dataset, splits, "--extend-test-types", "pliers") == 2
    assert "object type is not new: pliers" in capsys.readouterr().err.splitlines()


def test_extension_is_the_split_v1_procedure_per_type(ca15: tuple[Path, Path]) -> None:
    """Extending one tool alone or the 5 together gives the same split of that tool."""
    dataset, splits = ca15
    df = _load(dataset)
    v1 = load_split(splits / "split_v1.csv")
    history = split.item_history([v1], df)
    one = make_split(
        df,
        previous=v1,
        history=history,
        extend_test_types=["allen_key"],
        defer_types=[t for t in TOOL_OBJECT_TYPES if t != "allen_key"],
    ).frame
    every = make_split(
        df, previous=v1, history=history, extend_test_types=list(TOOL_OBJECT_TYPES)
    ).frame
    allen = set(df[df["object_type"] == "allen_key"]["image_path"])

    def pick(frame: pd.DataFrame) -> dict[str, str]:
        pairs = zip(frame["image_path"], frame["split"], strict=True)
        return {p: s for p, s in pairs if p in allen}

    assert pick(one) == pick(every)
    # allen_key is ungraded (4 items x 3 images per grade): one stratum of 20 items -> 14/3/3
    own = df[(df["object_type"] == "allen_key") & ~df["item_id"].map(is_external_item)]
    splits_of = pick(one)
    pairs = zip(own["image_path"], own["item_id"], strict=True)
    per_item = {i: splits_of[p] for p, i in pairs}
    assert sorted(Counter(per_item.values()).items()) == [("test", 3), ("train", 14), ("val", 3)]


def _items_by_split(dataset: Path, split_csv: Path, tool: str) -> dict[str, Counter]:
    """grade -> Counter(split -> n items) of the non-external items of ``tool``."""
    df = _load(dataset)
    mapping = _split_map(split_csv)
    own = df[(df["object_type"] == tool) & ~df["item_id"].map(is_external_item)]
    result: dict[str, Counter] = {}
    for grade, part in own.groupby("grade"):
        items = {i: mapping[p] for p, i in zip(part["image_path"], part["item_id"], strict=True)}
        result[str(grade)] = Counter(items.values())
    return result


def _extend_after_v1(tmp_path: Path, **kwargs) -> tuple[Path, Path]:
    plain_kwargs = {k: v for k, v in kwargs.items() if k != "tool_items_per_stratum"}
    plain = make_synthetic_dataset(tmp_path / "plain", **plain_kwargs)
    assert _cli(plain, tmp_path / "splits") == 0
    tools = make_synthetic_dataset(tmp_path / "tools", **kwargs)
    assert _cli(tools, tmp_path / "splits", "--extend-test-types", TOOLS) == 0
    return tools, tmp_path / "splits" / "split_v2.csv"


def test_ca23_ungraded_tool_is_one_stratum(tmp_path: Path) -> None:
    dataset, split_csv = _extend_after_v1(tmp_path, tool_items_per_stratum=1)
    for tool in TOOL_OBJECT_TYPES:
        total = sum(_items_by_split(dataset, split_csv, tool).values(), Counter())
        assert total == Counter({"train": 3, "val": 1, "test": 1}), tool


def test_ca23_graded_tool_is_split_by_grade(tmp_path: Path) -> None:
    dataset, split_csv = _extend_after_v1(tmp_path, images_per_item=12, tool_items_per_stratum=5)
    for tool in TOOL_OBJECT_TYPES:
        by_grade = _items_by_split(dataset, split_csv, tool)
        assert sorted(by_grade) == sorted(GRADES)
        for grade, counts in by_grade.items():
            assert counts == Counter({"train": 3, "val": 1, "test": 1}), (tool, grade)


def test_graded_type_without_any_test_item_is_refused(tmp_path: Path) -> None:
    """A graded tool whose 5 items have 5 different dominant grades: 5 strata of 1 item, no
    test item -> ExtensionError (SPEC-016 4.7), even with 3 or more items."""
    dataset = make_synthetic_dataset(tmp_path / "ds")
    assert _cli(dataset, tmp_path / "splits") == 0
    df = _load(dataset)
    v1 = load_split(tmp_path / "splits" / "split_v1.csv")
    rows = []
    for k in range(5):  # item k: 12 images of every grade, plus 1 of grade k (its dominant)
        item = f"T-00{k + 1}"
        grades = [g for g in GRADES for _ in range(12)] + [GRADES[k]]
        rows += [
            {"image_path": f"raw/pliers/x/{item}__{j}.jpg", "item_id": item,
             "object_type": "pliers", "grade": g}
            for j, g in enumerate(grades)
        ]  # fmt: skip
    frame = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    assert tool_grade_coverage(frame)["pliers"]["graded"] is True
    with pytest.raises(split.ExtensionError) as excinfo:
        make_split(frame, previous=v1, extend_test_types=["pliers"])
    assert excinfo.value.lines == ["too few items to extend the test: pliers"]


def test_cli_prints_each_extension_error_alone(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = make_synthetic_dataset(tmp_path / "ds")
    assert _cli(dataset, tmp_path / "splits") == 0
    for k in range(3):
        add_synthetic_item(dataset, f"T-00{k + 1}", "allen_key", "good", seed=k)
    lines = ["too few items to extend the test: allen_key"]

    def refuse(*args, **kwargs):
        raise split.ExtensionError(lines)

    monkeypatch.setattr(split, "make_split", refuse)
    capsys.readouterr()
    assert _cli(dataset, tmp_path / "splits", "--extend-test-types", "allen_key") == 2
    assert capsys.readouterr().err.splitlines() == lines
    assert not (tmp_path / "splits" / "split_v2.csv").exists()


def test_ca15e_too_few_items_to_extend(tmp_path: Path, capsys) -> None:
    dataset = make_synthetic_dataset(tmp_path / "ds")
    assert _cli(dataset, tmp_path / "splits") == 0
    add_synthetic_item(dataset, "T-001", "allen_key", "good", n_images=2)
    add_synthetic_item(dataset, "T-002", "allen_key", "poor", n_images=2, seed=2)
    capsys.readouterr()
    assert _cli(dataset, tmp_path / "splits", "--extend-test-types", "allen_key") == 2
    assert "too few items to extend the test: allen_key" in capsys.readouterr().err
    assert not (tmp_path / "splits" / "split_v2.csv").exists()


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--defer-types", "hammer"], "unknown object type: hammer"),
        (["--extend-test-types", "screw"], "object type is not new: screw"),
        (
            ["--extend-test-types", "allen_key", "--defer-types", "allen_key"],
            "object type in both --extend-test-types and --defer-types: allen_key",
        ),
        (["--defer-types", "allen_key,pliers"], "object type is not new: pliers"),
    ],
)
def test_invalid_type_lists_exit_2(tmp_path: Path, capsys, extra: list[str], message: str) -> None:
    dataset = make_synthetic_dataset(tmp_path / "ds")
    assert _cli(dataset, tmp_path / "splits") == 0
    for k in range(3):
        add_synthetic_item(dataset, f"T-00{k + 1}", "allen_key", "good", seed=k)
    capsys.readouterr()
    assert _cli(dataset, tmp_path / "splits", *extra) == 2
    assert message in capsys.readouterr().err.splitlines()
    assert not (tmp_path / "splits" / "split_v2.csv").exists()


def test_unknown_type_exits_2_even_for_split_v1(tmp_path: Path, capsys) -> None:
    dataset = make_synthetic_dataset(tmp_path / "ds")
    assert _cli(dataset, tmp_path / "splits", "--extend-test-types", "bolt") == 2
    assert "unknown object type: bolt" in capsys.readouterr().err
    assert not (tmp_path / "splits").exists() or not any((tmp_path / "splits").iterdir())


def test_split_v1_ignores_the_lists(tmp_path: Path) -> None:
    dataset = make_synthetic_dataset(tmp_path / "ds", tool_items_per_stratum=1)
    assert _cli(dataset, tmp_path / "s1") == 0
    assert _cli(dataset, tmp_path / "s2", "--defer-types", TOOLS) == 0
    assert (tmp_path / "s1" / "split_v1.csv").read_bytes() == (
        tmp_path / "s2" / "split_v1.csv"
    ).read_bytes()
    meta = _meta(tmp_path / "s2" / "split_v1.json")
    assert meta["deferred_types"] == [] and meta["test_extended_types"] == []
    v1 = _split_map(tmp_path / "s1" / "split_v1.csv")
    assert any("/T-" in p for p in v1)


def test_new_object_types_and_decisions(ca15: tuple[Path, Path]) -> None:
    dataset, splits = ca15
    df = _load(dataset)
    v1 = load_split(splits / "split_v1.csv")
    assert new_object_types(df, [v1]) == list(TOOL_OBJECT_TYPES)
    assert new_object_types(df, []) == ["screw", "nut", "other", *TOOL_OBJECT_TYPES]
    assert type_decision_problems(df, [v1], defer_types=TOOL_OBJECT_TYPES) == []
    assert type_decision_problems(df, [], extend_test_types=["pliers"]) == []
    problems = type_decision_problems(df, [v1], extend_test_types=["pliers"])
    assert problems == [
        f"new object type without decision: {t}" for t in TOOL_OBJECT_TYPES if t != "pliers"
    ]


# ---------------------------------------------------------------------------------------------
# Readers of the split: deferred types are ignored (section 4.7, last item)
# ---------------------------------------------------------------------------------------------


def test_readers_ignore_a_deferred_type(ca15: tuple[Path, Path], caplog) -> None:
    dataset, splits = ca15
    assert _cli(dataset, splits, "--defer-types", TOOLS) == 0
    df = _load(dataset)
    split_df = load_split(splits / "split_v2.csv")
    counts = deferred_type_counts(df, split_df)
    assert list(counts) == list(TOOL_OBJECT_TYPES)
    assert counts["pliers"] == 4 * 5 * 3 + 2
    caplog.set_level(logging.WARNING, logger="qc_ml.split")
    train = rows_for(df, split_df, "train")
    assert not set(train["object_type"]) & set(TOOL_OBJECT_TYPES)
    messages = [r.getMessage() for r in caplog.records if r.name == "qc_ml.split"]
    assert f"deferred type images: pliers: {counts['pliers']}" in messages
    for which in ("val", "test"):
        assert not set(rows_for(df, split_df, which)["object_type"]) & set(TOOL_OBJECT_TYPES)
    report = build_data_report(df, split_df)
    assert report["counts"]["pliers"]["good"]["total"] == 4 * 3 + 1  # T- images + XT-0002
    assert sum(report["counts"]["pliers"]["good"][s] for s in ("train", "val", "test")) == 0


def test_present_type_with_new_images_is_still_outdated(ca15: tuple[Path, Path]) -> None:
    dataset, splits = ca15
    assert _cli(dataset, splits, "--extend-test-types", TOOLS) == 0
    add_synthetic_item(dataset, "T-101", "pliers", "good")
    df = _load(dataset)
    with pytest.raises(SplitError, match="split outdated"):
        rows_for(df, load_split(splits / "split_v2.csv"), "train")


def test_make_split_checks_the_extension(ca15: tuple[Path, Path]) -> None:
    dataset, splits = ca15
    df = _load(dataset)
    v1 = load_split(splits / "split_v1.csv")
    with pytest.raises(SplitError, match="not new: screw"):
        make_split(df, previous=v1, extend_test_types=["screw"])
    with pytest.raises(SplitError, match="unknown object types: bolt"):
        make_split(df, previous=v1, defer_types=["bolt"])
    with pytest.raises(SplitError, match="both extended and deferred"):
        make_split(df, previous=v1, extend_test_types=["pliers"], defer_types=["pliers"])
    small = df[~((df["object_type"] == "allen_key") & ~df["item_id"].isin(["T-041", "T-042"]))]
    with pytest.raises(SplitError, match="too few items to extend the test: allen_key"):
        make_split(small, previous=v1, extend_test_types=["allen_key"])
    # without previous (split_v1) the lists are not used
    frame = make_split(df, defer_types=list(TOOL_OBJECT_TYPES)).frame
    assert len(frame) == len(df)
