"""Author tests of SPEC-045 section 3.1 (ADR-025): the model trained without nuts.

``FLOOR_STRATA`` without nuts (section 4.1), ``split_stratum`` in ``split_v1`` and in the test
extension (section 4.2), ``--defer-types`` in ``split_v1`` (section 4.3), the generator with
``include_nut=False``, the ``tiny_model_no_nut`` fixture and the evaluation without nuts (section
4.4). Synthetic data in ``tmp_path`` only (R-02, R-14); only the fixture regeneration needs torch.
"""

from __future__ import annotations

import csv
import filecmp
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

from qc_ml import evaluate as evaluate_mod
from qc_ml import split
from qc_ml import thresholds as thresholds_mod
from qc_ml.artifacts import load_labels
from qc_ml.data import (
    GRADES,
    IDENTIFIED_TOOL_OBJECT_TYPES,
    MANIFEST_COLUMNS,
    TOOL_OBJECT_TYPES,
    derive_model_labels,
    load_manifest,
    tool_grade_coverage,
)
from qc_ml.errors import SplitError
from qc_ml.split import (
    FLOOR_STRATA,
    floor_problems,
    item_strata,
    load_split,
    make_split,
    split_stratum,
    type_decision_problems,
)
from qc_ml.synthetic import add_synthetic_item, make_synthetic_dataset

ML = Path(__file__).resolve().parents[1]
ROOT = ML.parent
TINY = ML / "tests" / "fixtures" / "tiny_model"
TINY_NO_NUT = ML / "tests" / "fixtures" / "tiny_model_no_nut"
NO_NUT_TYPES = ["screw", "other", "hammer", "wrench", "spirit_level"]
VERSION = "partqc-tinynonut-v1"


def _cli(dataset: Path, splits: Path, *extra: str) -> int:
    argv = ["--dataset-dir", str(dataset), "--splits-dir", str(splits)]
    registry = dataset / "external_sources.csv"
    if registry.is_file():
        argv += ["--external-sources", str(registry)]
    return split.main([*argv, *extra])


def _rows(root: Path) -> list[dict[str, str]]:
    with (root / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_rows(root: Path, rows: list[dict[str, str]]) -> None:
    with (root / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANIFEST_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _split_map(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["image_path"]: row["split"] for row in csv.DictReader(fh)}


def _meta(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _items_by_split(root: Path, splits_csv: Path) -> dict[str, dict[str, set[str]]]:
    """``object_type -> split -> item_ids``."""
    mapping = _split_map(splits_csv)
    found: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in _rows(root):
        if row["image_path"] in mapping:
            found[row["object_type"]][mapping[row["image_path"]]].add(row["item_id"])
    return found


@pytest.fixture(scope="module")
def _no_nut(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """CA-02: 18 items (screw x 5 grades and other, 3 each), 3 images each."""
    return make_synthetic_dataset(
        tmp_path_factory.mktemp("no_nut") / "ds",
        items_per_stratum=3,
        images_per_item=3,
        include_nut=False,
    )


@pytest.fixture
def no_nut(_no_nut: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(_no_nut, tmp_path / "ds"))


@pytest.fixture(scope="module")
def _with_tools(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """CA-06: the dataset of CA-02 plus 5 items per hand tool (one per grade) and 3 per
    identification-only tool."""
    return make_synthetic_dataset(
        tmp_path_factory.mktemp("with_tools") / "ds",
        items_per_stratum=3,
        images_per_item=3,
        include_nut=False,
        tool_items_per_stratum=1,
        identified_tool_items_per_type=3,
    )


@pytest.fixture(scope="module")
def _identified(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """CA-08 to CA-10: the dataset of CA-02 plus 3 items per identification-only tool."""
    return make_synthetic_dataset(
        tmp_path_factory.mktemp("identified") / "ds",
        items_per_stratum=3,
        images_per_item=3,
        include_nut=False,
        identified_tool_items_per_type=3,
    )


@pytest.fixture
def identified(_identified: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(_identified, tmp_path / "ds"))


# ---------------------------------------------------------------------------------------------
# Section 4.1: the floor
# ---------------------------------------------------------------------------------------------


def test_floor_strata_is_the_fixed_list_without_nuts() -> None:
    assert FLOOR_STRATA == (
        ("screw", "perfect"),
        ("screw", "good"),
        ("screw", "fair"),
        ("screw", "poor"),
        ("screw", "unusable"),
        ("other", "none"),
    )
    assert not [s for s in FLOOR_STRATA if s[0] == "nut"]


def test_split_v1_without_nuts_at_the_floor(no_nut: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    assert _cli(no_nut, splits) == 0
    assert {p.name for p in splits.iterdir()} == {
        "split_v1.csv",
        "split_v1.sha256",
        "split_v1.json",
    }
    meta = _meta(splits / "split_v1.json")
    assert meta["counts"]["items"] == {"train": 6, "val": 6, "test": 6}
    assert meta["counts"]["images"] == {"train": 18, "val": 18, "test": 18}
    assert not [w for w in meta["warnings"] if w["code"] == "below_floor"]
    assert meta["deferred_types"] == [] and meta["test_extended_types"] == []


def test_below_the_floor_cites_the_screw_stratum(
    no_nut: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    rows = _rows(no_nut)
    fair = [r["item_id"] for r in rows if (r["object_type"], r["grade"]) == ("screw", "fair")]
    dropped = fair[0]
    for row in rows:
        if row["item_id"] == dropped:
            (no_nut / row["image_path"]).unlink()
    _write_rows(no_nut, [r for r in rows if r["item_id"] != dropped])
    splits = tmp_path / "splits"
    assert _cli(no_nut, splits) == 2
    below = [ln for ln in capfd.readouterr().err.splitlines() if "below the floor" in ln]
    assert below == ["split_v1 below the floor: screw/fair"]
    assert not list(splits.glob("split_v1.*"))
    assert _cli(no_nut, splits, "--allow-below-floor") == 0
    warnings = _meta(splits / "split_v1.json")["warnings"]
    assert {"code": "below_floor", "stratum": "screw/fair"} in warnings
    assert {"code": "small_stratum", "stratum": "screw/fair", "n_items": 2} in warnings


def test_a_nut_is_split_but_is_not_part_of_the_floor(no_nut: Path, tmp_path: Path) -> None:
    added = add_synthetic_item(no_nut, "N-001", "nut", "fair", n_images=3)
    splits = tmp_path / "splits"
    assert _cli(no_nut, splits) == 0
    meta = _meta(splits / "split_v1.json")
    assert {"code": "small_stratum", "stratum": "nut/fair", "n_items": 1} in meta["warnings"]
    assert not [w for w in meta["warnings"] if w["code"] == "below_floor"]
    mapping = _split_map(splits / "split_v1.csv")
    assert [mapping[p] for p in added] == ["train"] * 3


def test_floor_problems_ignore_the_nut_strata(tmp_path: Path) -> None:
    """With nuts (the default generator) but 1 item per stratum, only the 6 strata of the floor
    are cited; 3 items per stratum clear them, whatever the nuts."""
    root = make_synthetic_dataset(tmp_path / "one", items_per_stratum=1, images_per_item=1)
    df = load_manifest(root)
    problems = floor_problems(df, make_split(df).frame)
    assert problems == sorted(split.stratum_name(s) for s in FLOOR_STRATA)


def test_deferring_screw_or_other_is_below_the_floor(
    no_nut: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    assert _cli(no_nut, tmp_path / "s1", "--defer-types", "screw") == 2
    err = capfd.readouterr().err.splitlines()
    assert [ln for ln in err if "below the floor" in ln] == [
        f"split_v1 below the floor: screw/{grade}" for grade in sorted(GRADES)
    ]
    assert not (tmp_path / "s1").exists() or not list((tmp_path / "s1").iterdir())
    assert _cli(no_nut, tmp_path / "s2", "--defer-types", "other") == 2
    assert "split_v1 below the floor: other/none" in capfd.readouterr().err.splitlines()


# ---------------------------------------------------------------------------------------------
# Section 4.2: split_stratum
# ---------------------------------------------------------------------------------------------


def _coverage(pliers_graded: bool) -> dict[str, dict]:
    return {
        tool: {"graded": pliers_graded and tool == "pliers", "by_grade": {}}
        for tool in TOOL_OBJECT_TYPES
    }


def test_split_stratum_cases() -> None:
    ungraded = _coverage(False)
    graded = _coverage(True)
    assert split_stratum("pliers", ("pliers", "good"), {"pliers": {"graded": False}}) == (
        "pliers",
        "none",
    )
    assert split_stratum("pliers", ("pliers", "good"), ungraded) == ("pliers", "none")
    assert split_stratum("pliers", ("pliers", "good"), graded) == ("pliers", "good")
    assert split_stratum("allen_key", ("allen_key", "poor"), graded) == ("allen_key", "none")
    for coverage in (ungraded, graded, {}):
        assert split_stratum("hammer", ("hammer", "none"), coverage) == ("hammer", "none")
        assert split_stratum("drill", ("drill", "none"), coverage) == ("drill", "none")
        assert split_stratum("screw", ("screw", "fair"), coverage) == ("screw", "fair")
        assert split_stratum("nut", ("nut", "poor"), coverage) == ("nut", "poor")
        assert split_stratum("other", ("other", "none"), coverage) == ("other", "none")
    # a hand tool missing from coverage counts as not graded
    assert split_stratum("pliers", ("pliers", "good"), {}) == ("pliers", "none")


def test_split_stratum_keeps_the_strata_of_screw_and_other(_with_tools: Path) -> None:
    """``floor_problems`` uses ``item_strata``: for the types of the floor it is the stratum of
    the allocation too."""
    df = load_manifest(_with_tools)
    coverage = tool_grade_coverage(df)
    for item_id, stratum in item_strata(df).items():
        if stratum[0] in ("screw", "other"):
            assert split_stratum(stratum[0], stratum, coverage) == stratum, item_id


def test_tools_in_split_v1_by_whole_type(_with_tools: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    assert _cli(_with_tools, splits) == 0
    found = _items_by_split(_with_tools, splits / "split_v1.csv")
    for tool in TOOL_OBJECT_TYPES:
        sizes = {s: len(found[tool][s]) for s in ("train", "val", "test")}
        assert sizes == {"train": 3, "val": 1, "test": 1}, tool
    for tool in IDENTIFIED_TOOL_OBJECT_TYPES:
        sizes = {s: len(found[tool][s]) for s in ("train", "val", "test")}
        assert sizes == {"train": 1, "val": 1, "test": 1}, tool
    meta = _meta(splits / "split_v1.json")
    small = [w["stratum"] for w in meta["warnings"] if w["code"] == "small_stratum"]
    assert not [s for s in small if s.split("/")[0] in TOOL_OBJECT_TYPES]
    assert not [w for w in meta["warnings"] if w["code"] == "below_floor"]


def test_graded_hand_tool_keeps_the_grade_strata(_with_tools: Path, monkeypatch) -> None:
    """A graded hand tool (coverage says so) is stratified by grade, as before."""
    df = load_manifest(_with_tools)
    coverage = tool_grade_coverage(df)
    coverage["pliers"]["graded"] = True
    monkeypatch.setattr(split, "tool_grade_coverage", lambda _df: coverage)
    result = make_split(df)
    small = {w["stratum"] for w in result.warnings if w["code"] == "small_stratum"}
    assert {f"pliers/{grade}" for grade in GRADES} <= small
    assert not {s for s in small if s.startswith("flat_screwdriver/")}


# Values computed with the code of the base commit of SPEC-045 (merge-base with the main,
# 555c4b64e9f597756a3ea614d5e3ecaeb24590a6; same qc_ml code as c6134f1), seed 42.
BASE_SPLIT_V1_SHA256 = {
    "items3_images3": (
        {"items_per_stratum": 3, "images_per_item": 3},
        "7f18e97f68e275e26be2ae8042f0473467afce6d478f7fbb43f0d420bc6eddc9",
    ),
    "default": ({}, "6c516727e74b3929eca8bc801641c36e9840476fcfed53a680f931e5bab21dfe"),
    "power_and_identified": (
        {
            "items_per_stratum": 3,
            "images_per_item": 3,
            "power_tool_items_per_type": 2,
            "identified_tool_items_per_type": 3,
        },
        "f42adc28bb696dcf10a0d9e39782dddd745009aae1d2cf734decfa85d8f1feb5",
    ),
    "external_and_contributor": (
        {
            "items_per_stratum": 3,
            "images_per_item": 1,
            "external_items_per_stratum": 1,
            "contributor_items_per_stratum": 1,
        },
        "b3af80aa899797a0d7395925dbaf806bb50cc0a93fe949bc7c61187ef5d594b5",
    ),
}


@pytest.mark.parametrize("case", sorted(BASE_SPLIT_V1_SHA256))
def test_split_v1_unchanged_without_hand_tools(case: str, tmp_path: Path) -> None:
    """Section 4.2, last item: without hand tools the split_v1 is the one of before SPEC-045."""
    kwargs, expected = BASE_SPLIT_V1_SHA256[case]
    root = make_synthetic_dataset(tmp_path / "ds", **kwargs)
    extra = ["--allow-below-floor"]
    if (root / "external_sources.csv").is_file():
        extra += ["--max-external-fraction", "1"]
    assert _cli(root, tmp_path / "splits", *extra) == 0
    digest = hashlib.sha256((tmp_path / "splits" / "split_v1.csv").read_bytes()).hexdigest()
    assert digest == expected


def test_extension_uses_split_stratum(tmp_path: Path) -> None:
    """The extension of ADR-022 keeps the whole type as stratum for an ungraded hand tool."""
    plain = make_synthetic_dataset(tmp_path / "plain", items_per_stratum=3, images_per_item=1)
    assert _cli(plain, tmp_path / "splits") == 0
    tools = make_synthetic_dataset(
        tmp_path / "tools", items_per_stratum=3, images_per_item=1, tool_items_per_stratum=1
    )
    others = ",".join(t for t in TOOL_OBJECT_TYPES if t != "pliers")
    assert (
        _cli(tools, tmp_path / "splits", "--extend-test-types", "pliers", "--defer-types", others)
        == 0
    )
    found = _items_by_split(tools, tmp_path / "splits" / "split_v2.csv")
    assert {s: len(found["pliers"][s]) for s in ("train", "val", "test")} == {
        "train": 3,
        "val": 1,
        "test": 1,
    }


# ---------------------------------------------------------------------------------------------
# Section 4.3: --defer-types in split_v1
# ---------------------------------------------------------------------------------------------


def test_defer_types_in_split_v1_then_extend(
    identified: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    splits = tmp_path / "splits"
    assert _cli(identified, splits, "--defer-types", "spirit_level") == 0
    v1 = _split_map(splits / "split_v1.csv")
    assert not [p for p in v1 if p.startswith("raw/spirit_level/")]
    assert [p for p in v1 if p.startswith("raw/hammer/")]
    meta = _meta(splits / "split_v1.json")
    assert meta["deferred_types"] == ["spirit_level"]
    assert meta["test_extended_types"] == []
    # the readers ignore the deferred images
    df = load_manifest(identified)
    rows = split.rows_for(df, load_split(splits / "split_v1.csv"), "train")
    assert "spirit_level" not in set(rows["object_type"])
    # still a new type in the next version (ADR-022, decision 4)
    capfd.readouterr()
    assert _cli(identified, splits) == 2
    assert "new object type without decision: spirit_level" in capfd.readouterr().err.splitlines()
    assert not (splits / "split_v2.csv").exists()
    assert _cli(identified, splits, "--extend-test-types", "spirit_level") == 0
    v2 = _split_map(splits / "split_v2.csv")
    assert all(v2[p] == s for p, s in v1.items())
    found = _items_by_split(identified, splits / "split_v2.csv")
    assert {s: len(found["spirit_level"][s]) for s in ("train", "val", "test")} == {
        "train": 1,
        "val": 1,
        "test": 1,
    }


def test_defer_types_order_of_known_object_types(identified: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    assert _cli(identified, splits, "--defer-types", "spirit_level,hammer") == 0
    assert _meta(splits / "split_v1.json")["deferred_types"] == ["hammer", "spirit_level"]


def test_deferred_type_without_images_in_split_v1(
    no_nut: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    splits = tmp_path / "splits"
    assert _cli(no_nut, splits, "--defer-types", "nut") == 2
    assert "deferred type without images: nut" in capfd.readouterr().err.splitlines()
    assert not splits.exists() or not list(splits.iterdir())
    assert _cli(no_nut, splits, "--defer-types", "bolt") == 2
    assert "unknown object type: bolt" in capfd.readouterr().err.splitlines()
    assert not splits.exists() or not list(splits.iterdir())


def test_extend_test_types_has_no_effect_in_split_v1(
    identified: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert _cli(identified, tmp_path / "plain") == 0
    with caplog.at_level(logging.WARNING, logger="qc_ml.split"):
        assert _cli(identified, tmp_path / "ext", "--extend-test-types", "hammer") == 0
    assert "--extend-test-types is not used for split_v1" in caplog.text
    assert (tmp_path / "plain" / "split_v1.csv").read_bytes() == (
        tmp_path / "ext" / "split_v1.csv"
    ).read_bytes()
    meta = _meta(tmp_path / "ext" / "split_v1.json")
    assert meta["test_extended_types"] == [] and meta["deferred_types"] == []
    # in both lists in split_v1: the type is deferred (extend has no effect)
    both = tmp_path / "both"
    assert _cli(identified, both, "--extend-test-types", "hammer", "--defer-types", "hammer") == 0
    assert _meta(both / "split_v1.json")["deferred_types"] == ["hammer"]


def test_type_decision_problems_for_split_v1(_identified: Path) -> None:
    df = load_manifest(_identified)
    assert type_decision_problems(df, [], defer_types=["hammer"]) == []
    assert type_decision_problems(df, [], defer_types=["nut", "pliers", "hammer"]) == [
        "deferred type without images: nut",
        "deferred type without images: pliers",
    ]
    assert type_decision_problems(df, [], ["nut"]) == []  # extend is not used for split_v1
    assert type_decision_problems(df, [], defer_types=["bolt", "nut"]) == [
        "unknown object type: bolt"
    ]


def test_make_split_defers_in_split_v1(_identified: Path) -> None:
    df = load_manifest(_identified)
    frame = make_split(df, defer_types=["wrench"]).frame
    kept = set(frame["image_path"])
    wrench = set(df.loc[df["object_type"] == "wrench", "image_path"])
    assert not kept & wrench
    assert kept == set(df["image_path"]) - wrench
    # the other items are allocated as without the wrenches
    without = df[df["object_type"] != "wrench"]
    assert make_split(without).frame.equals(frame)
    with pytest.raises(SplitError, match="unknown object types: bolt"):
        make_split(df, defer_types=["bolt"])


# ---------------------------------------------------------------------------------------------
# Generator (include_nut)
# ---------------------------------------------------------------------------------------------


def _files(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_include_nut_true_is_the_default_byte_for_byte(tmp_path: Path) -> None:
    a = make_synthetic_dataset(tmp_path / "a", items_per_stratum=1, images_per_item=1)
    b = make_synthetic_dataset(
        tmp_path / "b", items_per_stratum=1, images_per_item=1, include_nut=True
    )
    assert _files(a) == _files(b)
    _, mismatch, errors = filecmp.cmpfiles(a, b, _files(a), shallow=False)
    assert mismatch == [] and errors == []


def test_include_nut_false_keeps_the_other_ids_and_names(tmp_path: Path) -> None:
    kwargs = {
        "items_per_stratum": 1,
        "images_per_item": 2,
        "contributor_items_per_stratum": 1,
        "external_items_per_stratum": 1,
        "identified_tool_items_per_type": 1,
    }
    with_nut = make_synthetic_dataset(tmp_path / "a", **kwargs)
    without = make_synthetic_dataset(tmp_path / "b", include_nut=False, **kwargs)
    rows_a, rows_b = _rows(with_nut), _rows(without)
    assert not [r for r in rows_b if r["item_id"].startswith(("N-", "XN-"))]
    assert not [r for r in rows_b if r["object_type"] == "nut"]
    # the same rows (paths, ids, timestamps), only the nut rows are gone
    assert rows_b == [r for r in rows_a if r["object_type"] != "nut"]
    assert not (without / "raw" / "nut").exists()
    sources = (without / "sources.csv").read_text(encoding="utf-8")
    assert "/nut/" not in sources
    load_manifest(without, external_sources=without / "external_sources.csv")  # valid


# ---------------------------------------------------------------------------------------------
# Section 4.4: model labels, thresholds and evaluation without nuts (no torch)
# ---------------------------------------------------------------------------------------------


def test_derive_model_labels_without_nuts(_identified: Path) -> None:
    df = load_manifest(_identified)
    labels = derive_model_labels(df, df)
    assert labels.object_types == tuple(NO_NUT_TYPES)
    assert labels.ungraded_object_types == ("hammer", "wrench", "spirit_level")


def test_fixture_no_nut_files_labels_and_parity() -> None:
    from qc_ml.parity import check_parity

    labels = load_labels(TINY_NO_NUT / "labels.json")
    assert list(labels.object_types) == NO_NUT_TYPES
    assert labels.ungraded_object_types == ("hammer", "wrench", "spirit_level")
    assert labels.grades == tuple(GRADES)
    files = {p.name for p in TINY_NO_NUT.iterdir() if p.is_file()}
    assert files == {p.name for p in TINY.iterdir() if p.is_file()}
    assert sum((TINY_NO_NUT / name).stat().st_size for name in files) < 1_000_000
    digest = hashlib.sha256((TINY_NO_NUT / "model.onnx").read_bytes()).hexdigest()
    assert (TINY_NO_NUT / "model.sha256").read_text(encoding="utf-8").split()[0] == digest
    decision = json.loads((TINY_NO_NUT / "decision.json").read_text(encoding="utf-8"))
    assert set(decision) == {"type_threshold", "unusable_threshold", "grade_review_threshold"}
    result = check_parity(TINY_NO_NUT)
    assert result.ok, result.message


@pytest.fixture
def no_nut_config(_identified: Path, tmp_path: Path) -> Path:
    dataset = Path(shutil.copytree(_identified, tmp_path / "ds"))
    splits = tmp_path / "splits"
    assert _cli(dataset, splits) == 0
    shutil.copytree(TINY_NO_NUT, tmp_path / "models" / VERSION)
    config = {
        "model_version": VERSION,
        "dataset_dir": str(dataset),
        "split_file": str(splits / "split_v1.csv"),
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


def test_thresholds_and_evaluate_without_nuts(no_nut_config: Path) -> None:
    assert thresholds_mod.main(["--config", str(no_nut_config)]) == 0
    assert evaluate_mod.main(["--config", str(no_nut_config), "--latency-machine", "ci"]) == 0
    model_dir = no_nut_config.parent / "models" / VERSION
    decision = json.loads((model_dir / "decision.json").read_text(encoding="utf-8"))
    assert set(decision) == {"type_threshold", "unusable_threshold", "grade_review_threshold"}
    metrics = json.loads((model_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["labels"]["object_types"] == NO_NUT_TYPES
    assert np.asarray(metrics["type_confusion"]).shape == (5, 5)
    assert metrics["grade_qwk"] is not None and metrics["type_accuracy"] is not None
    assert metrics["n_items_test_by_grade"] == dict.fromkeys(GRADES, 1)
    assert "nut" not in metrics["counts"]["test"]["by_class"]
    # every test image counted in the type confusion, none of a nut
    test_images = sum(c["n_images"] for c in metrics["counts"]["test"]["by_class"].values())
    assert int(np.asarray(metrics["type_confusion"]).sum()) == test_images
    assert set(metrics["counts"]["test"]["by_class"]) == set(NO_NUT_TYPES)


# ---------------------------------------------------------------------------------------------
# Fixture regeneration (torch)
# ---------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_make_tiny_fixture_identified_tools_no_nut(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("onnx")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    script = str(ML / "scripts" / "make_tiny_fixture.py")
    out = tmp_path / "no_nut"
    proc = subprocess.run(
        [sys.executable, script, "--identified-tools-no-nut", "--out", str(out)],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (out / "labels.json").read_bytes() == (TINY_NO_NUT / "labels.json").read_bytes()
    both = subprocess.run(
        [sys.executable, script, "--identified-tools-no-nut", "--with-tools", "--out", str(out)],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
        check=False,
    )
    assert both.returncode == 2
