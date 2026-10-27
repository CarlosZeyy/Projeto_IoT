"""Author tests of SPEC-016 sections 4.6 and 4.9: hand tools in the data and the generator.

Prefixes ``T``/``XT``, the required grade, the grade criterion (``tool_grade_coverage``), the
data report and ``make_synthetic_dataset`` with tools. Synthetic data only, no torch.
"""

from __future__ import annotations

import csv
import filecmp
import json
import shutil
from pathlib import Path

import pytest

from qc_contracts import GRADE_OPTIONAL_OBJECT_TYPES, ObjectType
from qc_ml import data
from qc_ml.data import (
    GRADES,
    KNOWN_OBJECT_TYPES,
    TOOL_GRADE_MIN_IMAGES,
    TOOL_GRADE_MIN_ITEMS,
    TOOL_OBJECT_TYPES,
    build_data_report,
    item_prefix_matches,
    load_manifest,
    tool_grade_coverage,
)
from qc_ml.errors import ManifestError
from qc_ml.synthetic import add_synthetic_item, make_synthetic_dataset

TOOLS = (
    "pliers",
    "adjustable_wrench",
    "allen_key",
    "flat_screwdriver",
    "phillips_screwdriver",
)


def _rows(root: Path) -> list[dict[str, str]]:
    with (root / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write(root: Path, rows: list[dict[str, str]]) -> None:
    with (root / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(data.MANIFEST_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _codes(excinfo: pytest.ExceptionInfo[ManifestError]) -> set[str]:
    return {p.code for p in excinfo.value.problems}


@pytest.fixture(scope="module")
def _tools1(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("tools1") / "ds"
    return make_synthetic_dataset(root, tool_items_per_stratum=1)


@pytest.fixture
def tools1(_tools1: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(_tools1, tmp_path / "ds"))


# ---------------------------------------------------------------------------------------------
# Constants (section 4.6)
# ---------------------------------------------------------------------------------------------


def test_tool_types_are_the_grade_optional_types_of_the_contract() -> None:
    assert TOOL_OBJECT_TYPES == TOOLS
    assert set(TOOL_OBJECT_TYPES) == {m.value for m in GRADE_OPTIONAL_OBJECT_TYPES}
    order = [m.value for m in ObjectType]
    assert list(TOOL_OBJECT_TYPES) == sorted(TOOL_OBJECT_TYPES, key=order.index)
    assert tuple(KNOWN_OBJECT_TYPES) == ("screw", "nut", "other", *TOOLS)
    assert (TOOL_GRADE_MIN_IMAGES, TOOL_GRADE_MIN_ITEMS) == (60, 5)
    assert data.DEFAULT_LABELS.object_types == ("screw", "nut", "other")
    assert data.DEFAULT_LABELS.ungraded_object_types == ()


@pytest.mark.parametrize(
    ("item_id", "object_type", "ok"),
    [
        ("T-001", "pliers", True),
        ("T-999", "phillips_screwdriver", True),
        ("XT-0001", "allen_key", True),
        ("T-001", "screw", False),
        ("T-001", "other", False),
        ("XT-0001", "nut", False),
        ("S-001", "pliers", False),
        ("O-001", "flat_screwdriver", False),
        ("S-001", "screw", True),
        ("XN-0001", "nut", True),
        ("O-001", "other", True),
    ],
)
def test_item_prefix_matches(item_id: str, object_type: str, ok: bool) -> None:
    assert item_prefix_matches(item_id, object_type) is ok


# ---------------------------------------------------------------------------------------------
# load_manifest (CA-13)
# ---------------------------------------------------------------------------------------------


def test_ca13_tools_load_without_error(tools1: Path) -> None:
    df = load_manifest(tools1)
    tool_items = {i for i in df["item_id"] if i.startswith("T-")}
    assert len(tool_items) == 25
    assert set(df[df["item_id"].isin(tool_items)]["object_type"]) == set(TOOLS)
    assert df[df["item_id"].isin(tool_items)]["grade"].notna().all()


def test_ca13_t_item_with_screw_is_a_prefix_mismatch(tools1: Path) -> None:
    rows = _rows(tools1)
    row = next(r for r in rows if r["item_id"] == "T-001")
    row["object_type"] = "screw"
    _write(tools1, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(tools1)
    assert "item_prefix_mismatch" in _codes(excinfo)


def test_ca13_tool_without_grade_is_missing_grade(tools1: Path) -> None:
    rows = _rows(tools1)
    row = next(r for r in rows if r["object_type"] == "allen_key")
    row["grade"] = ""
    _write(tools1, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(tools1)
    assert "missing_grade" in _codes(excinfo)


@pytest.mark.parametrize("object_type", ["screw", "nut", "other"])
def test_t_prefix_with_a_mvp_type_is_refused(tools1: Path, object_type: str) -> None:
    rows = _rows(tools1)
    row = next(r for r in rows if r["item_id"] == "T-002")
    for other_row in rows:
        if other_row["item_id"] == "T-002":
            other_row["object_type"] = object_type
            other_row["grade"] = "" if object_type == "other" else other_row["grade"]
    assert row["object_type"] == object_type
    _write(tools1, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(tools1)
    assert "item_prefix_mismatch" in _codes(excinfo)


def test_tool_with_s_prefix_is_refused(dataset: Path) -> None:
    rows = _rows(dataset)
    for row in rows:
        if row["item_id"] == "S-001":
            row["object_type"] = "pliers"
    _write(dataset, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(dataset)
    assert "item_prefix_mismatch" in _codes(excinfo)


def test_two_tool_types_for_one_item_conflict(tools1: Path) -> None:
    """Two tool types for one item stay an item_type_conflict (the T letter allows both)."""
    add_synthetic_item(tools1, "T-001", "pliers", "perfect", n_images=1)
    rows = _rows(tools1)
    rows[-1]["object_type"] = "allen_key"
    _write(tools1, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(tools1)
    assert "item_type_conflict" in _codes(excinfo)


# ---------------------------------------------------------------------------------------------
# Grade criterion and data report (CA-14)
# ---------------------------------------------------------------------------------------------


def _criterion_dataset(root: Path) -> Path:
    """pliers: 5 items per grade x 12 images (60); allen_key: the same minus 1 image (59) in
    ``fair``; flat_screwdriver: 30 external images; phillips: 4 items per grade x 15 images."""
    make_synthetic_dataset(root, items_per_stratum=1, images_per_item=1)
    number = 0
    for tool, missing in (("pliers", None), ("allen_key", "fair")):
        for grade in GRADES:
            for k in range(TOOL_GRADE_MIN_ITEMS):
                number += 1
                n = 12 - (1 if grade == missing and k == 0 else 0)
                add_synthetic_item(root, f"T-{number:03d}", tool, grade, n_images=n, seed=number)
    for grade in GRADES:
        for _ in range(4):
            number += 1
            item = f"T-{number:03d}"
            add_synthetic_item(root, item, "phillips_screwdriver", grade, n_images=15, seed=number)
    return root


@pytest.fixture(scope="module")
def criterion_df(tmp_path_factory: pytest.TempPathFactory):
    root = _criterion_dataset(tmp_path_factory.mktemp("criterion") / "ds")
    df = load_manifest(root, verify_images=False)
    # 30 external flat_screwdriver images, added to the frame (the criterion ignores them).
    import pandas as pd

    extra = pd.DataFrame(
        {
            "image_path": [f"raw/flat_screwdriver/good/XT-{k:04d}__0__x.jpg" for k in range(30)],
            "item_id": [f"XT-{k + 1:04d}" for k in range(30)],
            "object_type": ["flat_screwdriver"] * 30,
            "grade": [GRADES[k % 5] for k in range(30)],
        }
    )
    return pd.concat([df, extra], ignore_index=True)


def test_ca14_tool_grade_criterion(criterion_df) -> None:
    coverage = tool_grade_coverage(criterion_df)
    assert list(coverage) == list(TOOLS)
    for tool in TOOLS:
        assert list(coverage[tool]["by_grade"]) == list(GRADES)
        for cell in coverage[tool]["by_grade"].values():
            assert set(cell) == {"n_images", "n_items"}
    assert coverage["pliers"]["graded"] is True
    assert coverage["pliers"]["by_grade"]["poor"] == {"n_images": 60, "n_items": 5}
    assert coverage["allen_key"]["graded"] is False
    assert coverage["allen_key"]["by_grade"]["fair"] == {"n_images": 59, "n_items": 5}
    # 60 images per grade but only 4 items: not graded
    assert coverage["phillips_screwdriver"]["by_grade"]["good"] == {"n_images": 60, "n_items": 4}
    assert coverage["phillips_screwdriver"]["graded"] is False
    # external images never count
    assert all(
        cell == {"n_images": 0, "n_items": 0}
        for cell in coverage["flat_screwdriver"]["by_grade"].values()
    )
    assert coverage["adjustable_wrench"]["graded"] is False


def test_criterion_without_tools_has_the_5_tools_with_zeros(dataset: Path) -> None:
    coverage = tool_grade_coverage(load_manifest(dataset))
    assert list(coverage) == list(TOOLS)
    assert not any(entry["graded"] for entry in coverage.values())
    assert all(
        cell == {"n_images": 0, "n_items": 0}
        for entry in coverage.values()
        for cell in entry["by_grade"].values()
    )


def test_criterion_ignores_excluded_images(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds", items_per_stratum=1, images_per_item=1, tool_items_per_stratum=1
    )
    df = load_manifest(root)
    victim = df[df["object_type"] == "pliers"]["image_path"].iloc[0]
    (root / victim).unlink()
    (root / "exclusions.csv").write_text(f"image_path,reason\n{victim},other\n", encoding="utf-8")
    coverage = tool_grade_coverage(load_manifest(root))
    assert sum(c["n_images"] for c in coverage["pliers"]["by_grade"].values()) == 4


def test_data_report_has_the_tool_coverage(tools1: Path, tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    assert data.main(["report", "--dataset-dir", str(tools1), "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    coverage = report["tool_grade_coverage"]
    assert list(coverage) == list(TOOLS)
    assert coverage["pliers"]["by_grade"]["good"] == {"n_images": 2, "n_items": 1}
    assert coverage["pliers"]["graded"] is False
    # counts and items per grade of the tools are by grade, like screw/nut
    assert set(report["counts"]["pliers"]) == set(GRADES)
    assert report["items_per_grade"]["allen_key"]["fair"] == 1
    # the volume targets stay those of screw/nut (docs/dataset-protocol.md section 4)
    assert {e["object_type"] for e in report["below_target"]} == {"screw", "nut"}


def test_build_data_report_lists_every_known_type(dataset: Path) -> None:
    report = build_data_report(load_manifest(dataset))
    assert list(report["counts"]) == list(KNOWN_OBJECT_TYPES)
    assert report["counts"]["other"] == {"none": {"total": 8}}


# ---------------------------------------------------------------------------------------------
# Generator (section 4.9, CA-19)
# ---------------------------------------------------------------------------------------------


def _same_tree(a: Path, b: Path) -> None:
    files_a = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    assert files_a == files_b
    _, mismatch, errors = filecmp.cmpfiles(a, b, [str(p) for p in files_a], shallow=False)
    assert mismatch == [] and errors == []


def test_ca19_defaults_are_byte_for_byte_the_same(tmp_path: Path) -> None:
    a = make_synthetic_dataset(tmp_path / "a")
    b = make_synthetic_dataset(
        tmp_path / "b", tool_items_per_stratum=0, external_tool_items_per_type=0
    )
    _same_tree(a, b)
    items = {r["item_id"] for r in _rows(a)}
    assert not any(i.startswith(("T-", "XT-")) for i in items)
    assert not (a / "sources.csv").exists() and not (a / "external_sources.csv").exists()


def test_tools_come_after_the_own_items(tmp_path: Path) -> None:
    """The rows and images without tools are a prefix of the ones with tools (CA-15 setup)."""
    plain = make_synthetic_dataset(tmp_path / "plain", items_per_stratum=2)
    tools = make_synthetic_dataset(
        tmp_path / "tools", items_per_stratum=2, tool_items_per_stratum=1
    )
    rows_plain, rows_tools = _rows(plain), _rows(tools)
    assert rows_tools[: len(rows_plain)] == rows_plain
    for row in rows_plain:
        assert (plain / row["image_path"]).read_bytes() == (tools / row["image_path"]).read_bytes()


def test_tool_numbering_and_layout(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds",
        items_per_stratum=1,
        images_per_item=2,
        tool_items_per_stratum=2,
        external_tool_items_per_type=3,
    )
    rows = _rows(root)
    own = [r for r in rows if r["item_id"].startswith("T-")]
    order = list(dict.fromkeys((r["item_id"], r["object_type"], r["grade"]) for r in own))
    expected = []
    number = 0
    for tool in TOOLS:
        for grade in GRADES:
            for _ in range(2):
                number += 1
                expected.append((f"T-{number:03d}", tool, grade))
    assert order == expected
    assert all(r["image_path"].startswith(f"raw/{r['object_type']}/{r['grade']}/") for r in own)
    assert len(own) == 50 * 2
    external = [r for r in rows if r["item_id"].startswith("XT-")]
    assert [(r["item_id"], r["object_type"], r["grade"]) for r in external[:4]] == [
        ("XT-0001", "pliers", "perfect"),
        ("XT-0002", "pliers", "good"),
        ("XT-0003", "pliers", "fair"),
        ("XT-0004", "adjustable_wrench", "perfect"),
    ]
    assert len(external) == 15 and all(r["angle"] == "0" for r in external)
    with (root / "sources.csv").open(encoding="utf-8", newline="") as fh:
        sources = list(csv.DictReader(fh))
    assert {s["image_path"] for s in sources} == {r["image_path"] for r in external}
    assert {(s["origin"], s["source_id"]) for s in sources} == {("external", "synthetic")}
    df = load_manifest(root, external_sources=root / "external_sources.csv")
    assert set(df[df["item_id"].str.startswith("XT-")]["origin"]) == {"external"}
    assert set(df[df["item_id"].str.startswith("T-")]["origin"]) == {"capture"}
    stamps = [r["captured_at"] for r in rows]
    assert len(set(stamps)) == len(stamps)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tool_items_per_stratum": -1},
        {"external_tool_items_per_type": -1},
        {"tool_items_per_stratum": 40},  # 40 x 25 = 1000 > 999
        {"external_tool_items_per_type": 2000},  # 2000 x 5 = 10000 > 9999
    ],
)
def test_generator_refuses_invalid_tool_counts(tmp_path: Path, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        make_synthetic_dataset(tmp_path / "ds", **kwargs)
    assert not (tmp_path / "ds" / "manifest.csv").exists()


def test_add_synthetic_item_draws_a_tool(tools1: Path) -> None:
    paths = add_synthetic_item(tools1, "T-026", "phillips_screwdriver", "poor", n_images=2)
    assert all(p.startswith("raw/phillips_screwdriver/poor/T-026__") for p in paths)
    df = load_manifest(tools1)
    assert set(df[df["item_id"] == "T-026"]["grade"]) == {"poor"}
