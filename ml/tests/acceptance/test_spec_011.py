"""Acceptance tests for SPEC-011 (qc-ml: manifest, grouped split, agreement and augmentations).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test per CA (``test_caNN_*``); tests named ``test_extra_*`` are exploratory
edge cases around the SPEC that no CA spells out.

Rules followed (``docs/architecture.md`` §10, R-11 and R-14): every dataset is synthetic and lives
under ``tmp_path`` (``make_synthetic_dataset`` plus images drawn here with Pillow); nothing under
``ml/data/`` is ever read; nothing is mocked besides the temporary file system; the CLIs are run
through ``main(argv)`` or ``python -m`` in a subprocess, and no test runs the test suite in a
subprocess. CA-25 needs torch and is skipped without it (CI).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from PIL import Image
from sklearn.metrics import cohen_kappa_score

from qc_contracts import Grade
from qc_ml import agreement as agreement_mod
from qc_ml import data as data_mod
from qc_ml import split as split_mod
from qc_ml.augment import train_transform
from qc_ml.data import build_data_report, load_exclusions, load_manifest
from qc_ml.errors import ManifestError, ManifestProblem, SplitError, SplitIntegrityError
from qc_ml.split import item_history, load_split, make_split, rows_for
from qc_ml.synthetic import make_synthetic_dataset
from qc_preprocess import PreprocessParams, load_image, preprocess

pytestmark = pytest.mark.acceptance

REPO_ROOT = Path(__file__).resolve().parents[3]
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
GRADES = [g.value for g in Grade]
REPORT_KEYS = {
    "generated_at",
    "manifest_sha256",
    "split_file",
    "split_sha256",
    "n_images",
    "n_items",
    "n_overridden",
    "n_excluded",
    "counts",
    "items_per_grade",
    "images_per_item",
    "below_target",
    "below_minimum",
}
AGREEMENT_KEYS = {
    "generated_at",
    "n_pairs",
    "qwk",
    "exact_agreement",
    "off_by_one_agreement",
    "confusion",
    "grades",
    "labeler_first",
    "labeler_second",
    "targets",
    "meets_minimum",
    "meets_desired",
    "first_sha256",
    "second_sha256",
}


# --------------------------------------------------------------------------------------------
# Helpers (synthetic data only, always under tmp_path)
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _template_small(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("spec011_small") / "ds"
    make_synthetic_dataset(root)
    return root


@pytest.fixture(scope="module")
def _template_large(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("spec011_large") / "ds"
    make_synthetic_dataset(root, items_per_stratum=20, images_per_item=3)
    return root


@pytest.fixture
def ds(_template_small: Path, tmp_path: Path) -> Path:
    """The CA-01 dataset: 5 grades x 4 items x 2 images (screw, nut) + 4 `other` items."""
    return Path(shutil.copytree(_template_small, tmp_path / "ds", symlinks=True))


@pytest.fixture
def ds_large(_template_large: Path, tmp_path: Path) -> Path:
    """The CA-12 dataset: items_per_stratum=20, images_per_item=3."""
    return Path(shutil.copytree(_template_large, tmp_path / "ds", symlinks=True))


def read_rows(root: Path) -> list[dict[str, str]]:
    with (root / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(root: Path, rows: list[dict[str, str]]) -> None:
    with (root / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_jpeg(path: Path, color: tuple[int, int, int] = (230, 230, 225)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (256, 256), color)
    for x in range(96, 160):
        for y in range(40, 216):
            img.putpixel((x, y), (120, 120, 130))
    img.save(path, format="JPEG", quality=90)


def add_image(root: Path, item_id: str, object_type: str, grade: str | None, angle: int, ts: str):
    """Append one image (file + manifest row) in the SPEC-010 layout. ``ts`` = 20261101T100000Z."""
    rel = f"raw/{object_type}/{grade or '_'}/{item_id}__{angle}__{ts}.jpg"
    write_jpeg(root / rel)
    captured = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[9:11]}:{ts[11:13]}:{ts[13:15]}Z"
    rows = read_rows(root)
    rows.append(
        {
            "image_path": rel,
            "item_id": item_id,
            "object_type": object_type,
            "grade": grade or "",
            "labeler": "a",
            "angle": str(angle),
            "captured_at": captured,
            "capture_device": "synthetic",
            "notes": "",
        }
    )
    write_rows(root, rows)
    return rel


def problems_of(excinfo: pytest.ExceptionInfo[ManifestError]) -> list[ManifestProblem]:
    problems = list(excinfo.value.problems)
    assert problems, "ManifestError without problems"
    return problems


def codes(problems: list[ManifestProblem]) -> list[str]:
    return [p.code for p in problems]


def call_main(main: Callable[[list[str]], int], argv: list[str], capsys) -> tuple[int, str]:
    """Run a CLI ``main(argv)``; returns (exit code, stdout + stderr)."""
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:  # tolerated: some CLIs may exit through argparse
        rc = exc.code if isinstance(exc.code, int) else 1
    out = capsys.readouterr()
    return rc, out.out + out.err


def run_module(module: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """``python -m <module> <args>`` in a subprocess (never pytest)."""
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def split_cli(dataset: Path, splits: Path, capsys, seed: int = 42) -> tuple[int, str]:
    argv = ["--dataset-dir", str(dataset), "--splits-dir", str(splits), "--seed", str(seed)]
    return call_main(split_mod.main, argv, capsys)


def read_split_csv(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["image_path"]: r["split"] for r in csv.DictReader(fh)}


def item_of(image_path: str) -> str:
    return Path(image_path).name.split("__")[0]


def item_splits(mapping: dict[str, str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path, which in mapping.items():
        out.setdefault(item_of(path), set()).add(which)
    return out


def tree_snapshot(path: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(path.iterdir()) if p.is_file()}


def fake_frame(items: list[tuple[str, str, list[str | None]]]) -> pd.DataFrame:
    """A manifest-shaped DataFrame (no files) for split-only checks: (item_id, type, grades)."""
    rows: list[dict[str, Any]] = []
    for item_id, object_type, grades in items:
        for angle, grade in enumerate(grades):
            rows.append(
                {
                    "image_path": f"raw/{object_type}/{grade or '_'}/{item_id}__{angle}__"
                    f"20261101T10{angle:02d}00Z.jpg",
                    "item_id": item_id,
                    "object_type": object_type,
                    "grade": grade,
                    "labeler": "a",
                    "angle": angle,
                    "captured_at": f"2026-11-01T10:{angle:02d}:00Z",
                    "capture_device": "synthetic",
                    "notes": "",
                    "grade_original": grade,
                    "overridden": False,
                }
            )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------------
# §4.1 load_manifest
# --------------------------------------------------------------------------------------------


def test_ca01_load_synthetic_manifest(ds: Path) -> None:
    df = load_manifest(ds)
    assert len(df) == 88
    assert set(MANIFEST_HEADER) | {"grade_original", "overridden"} <= set(df.columns)
    other = df[df["object_type"] == "other"]
    assert len(other) == 8
    assert all(g is None for g in other["grade"].tolist())
    graded = df[df["object_type"].isin(["screw", "nut"])]
    assert len(graded) == 80
    assert set(graded["grade"]) == set(GRADES)
    assert df["item_id"].nunique() == 44
    assert not df["overridden"].astype(bool).any()


def test_ca02_missing_file(ds: Path) -> None:
    victim = read_rows(ds)[5]["image_path"]
    (ds / victim).unlink()
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    problems = problems_of(excinfo)
    assert codes(problems) == ["missing_file"]
    assert problems[0].image_path == victim


def test_ca03_unreadable_image_only_with_verify(ds: Path) -> None:
    victim = read_rows(ds)[7]["image_path"]
    (ds / victim).write_bytes(b"not an image")
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    problems = problems_of(excinfo)
    assert codes(problems) == ["unreadable_image"]
    assert problems[0].image_path == victim
    df = load_manifest(ds, verify_images=False)
    assert len(df) == 88


def test_ca04_item_type_conflict(ds: Path) -> None:
    rows = read_rows(ds)
    idx = next(i for i, r in enumerate(rows) if r["item_id"] == "S-001")
    rows[idx]["object_type"] = "nut"
    write_rows(ds, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    problems = problems_of(excinfo)
    conflicts = [p for p in problems if p.code == "item_type_conflict"]
    assert conflicts
    assert any("S-001" in str(p) for p in conflicts)
    mismatches = [p for p in problems if p.code == "item_prefix_mismatch"]
    assert [p.line for p in mismatches] == [idx + 2]
    assert mismatches[0].image_path == rows[idx]["image_path"]


def test_ca05_grade_on_other_and_missing_grade_lines(ds: Path) -> None:
    rows = read_rows(ds)
    other_idx = next(i for i, r in enumerate(rows) if r["object_type"] == "other")
    screw_idx = next(i for i, r in enumerate(rows) if r["object_type"] == "screw" and i > 10)
    rows[other_idx]["grade"] = "fair"
    rows[screw_idx]["grade"] = ""
    write_rows(ds, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    problems = problems_of(excinfo)
    on_other = [p for p in problems if p.code == "grade_on_other"]
    missing = [p for p in problems if p.code == "missing_grade"]
    assert [p.line for p in on_other] == [other_idx + 2]  # header = record 1
    assert [p.line for p in missing] == [screw_idx + 2]
    assert on_other[0].image_path == rows[other_idx]["image_path"]
    assert missing[0].image_path == rows[screw_idx]["image_path"]


def test_ca06_invalid_values(ds: Path) -> None:
    rows = read_rows(ds)
    rows[0]["grade"] = "rusty"
    rows[3]["angle"] = "7"
    rows[9]["item_id"] = "X-1"
    write_rows(ds, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    found = codes(problems_of(excinfo))
    assert {"invalid_grade", "invalid_angle", "invalid_item_id"} <= set(found)


def test_ca07_all_problems_in_one_error_and_cli(ds: Path, capsys) -> None:
    rows = read_rows(ds)
    gone = rows[2]["image_path"]
    (ds / gone).unlink()
    other_idx = next(i for i, r in enumerate(rows) if r["object_type"] == "other")
    rows[other_idx]["grade"] = "fair"
    rows[20]["angle"] = "9"
    write_rows(ds, rows)

    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    problems = problems_of(excinfo)
    assert sorted(codes(problems)) == ["grade_on_other", "invalid_angle", "missing_file"]
    assert len(str(excinfo.value).strip().splitlines()) >= 3

    result = run_module("qc_ml.data", ["validate", "--dataset-dir", str(ds)], ds.parent)
    assert result.returncode == 2, result.stdout + result.stderr
    output = result.stdout + result.stderr
    problem_lines = [ln for ln in output.splitlines() if ln.strip() and "count " not in ln]
    for code, path in (
        ("missing_file", gone),
        ("grade_on_other", rows[other_idx]["image_path"]),
        ("invalid_angle", rows[20]["image_path"]),
    ):
        assert any(code in ln and path in ln for ln in problem_lines), (code, output)


def test_ca08_override_changes_the_grade(ds: Path) -> None:
    target = next(
        r["image_path"] for r in read_rows(ds) if r["item_id"] == "S-003" and r["grade"] == "fair"
    )
    write_csv(
        ds / "labels_overrides.csv",
        ["image_path", "grade", "labeler", "reason"],
        [[target, "poor", "b", "crosta"]],
    )
    df = load_manifest(ds)
    row = df[df["image_path"] == target].iloc[0]
    assert row["grade"] == "poor"
    assert row["grade_original"] == "fair"
    assert bool(row["overridden"]) is True
    others = df[df["image_path"] != target]
    assert not others["overridden"].astype(bool).any()
    assert len(df) == 88


def test_ca09_last_override_wins_and_unknown_image(ds: Path) -> None:
    target = next(r["image_path"] for r in read_rows(ds) if r["grade"] == "fair")
    header = ["image_path", "grade", "labeler", "reason"]
    write_csv(
        ds / "labels_overrides.csv",
        header,
        [[target, "good", "b", "first look"], [target, "poor", "b", "second look"]],
    )
    df = load_manifest(ds)
    assert df[df["image_path"] == target].iloc[0]["grade"] == "poor"

    write_csv(
        ds / "labels_overrides.csv",
        header,
        [["raw/screw/fair/S-777__0__20261022T141503Z.jpg", "poor", "b", "typo"]],
    )
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    assert "override_unknown_image" in codes(problems_of(excinfo))


def test_ca10_override_fills_missing_grade(ds: Path) -> None:
    rows = read_rows(ds)
    idx = next(i for i, r in enumerate(rows) if r["object_type"] == "screw")
    rows[idx]["grade"] = ""
    write_rows(ds, rows)
    write_csv(
        ds / "labels_overrides.csv",
        ["image_path", "grade", "labeler", "reason"],
        [[rows[idx]["image_path"], "good", "b", "missing in the manifest"]],
    )
    df = load_manifest(ds)
    row = df[df["image_path"] == rows[idx]["image_path"]].iloc[0]
    assert row["grade"] == "good"
    assert bool(row["overridden"]) is True


# --------------------------------------------------------------------------------------------
# §4.2 data report
# --------------------------------------------------------------------------------------------


def test_ca11_data_report(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    out_file = tmp_path / "reports" / "data_report.json"
    argv = [
        "report",
        "--dataset-dir",
        str(ds),
        "--split",
        str(splits / "split_v1.csv"),
        "--out",
        str(out_file),
    ]
    rc, out = call_main(data_mod.main, argv, capsys)
    assert rc == 0, out
    text = out_file.read_text(encoding="utf-8")
    report = json.loads(text)
    assert set(report) >= REPORT_KEYS
    assert report["n_images"] == 88
    assert report["n_items"] == 44
    assert report["n_overridden"] == 0
    assert report["n_excluded"] == 0
    assert (
        report["split_sha256"] == hashlib.sha256((splits / "split_v1.csv").read_bytes()).hexdigest()
    )
    assert (
        report["manifest_sha256"] == hashlib.sha256((ds / "manifest.csv").read_bytes()).hexdigest()
    )
    combos = {(e["object_type"], e["grade"]) for e in report["below_target"]}
    assert combos == {(t, g) for t in ("screw", "nut") for g in GRADES}
    assert len(report["below_target"]) == 10
    for entry in report["below_target"]:
        assert set(entry) >= {"object_type", "grade", "n_images", "n_items"}
        assert entry["n_images"] == 8
        assert entry["n_items"] == 4
    # 4 items per grade < 8 -> every screw/nut combination is below the minimum too
    assert len(report["below_minimum"]) == 10
    assert {"min", "median", "mean", "max"} <= set(report["images_per_item"])
    assert report["images_per_item"]["min"] == 2 and report["images_per_item"]["max"] == 2
    assert report["items_per_grade"]["screw"]["fair"] == 4
    # counts: type -> grade -> split -> n images; "none" for other
    assert "none" in report["counts"]["other"]
    total_split = sum(
        n
        for by_grade in report["counts"].values()
        for by_split in by_grade.values()
        for which, n in by_split.items()
        if which in ("train", "val", "test")
    )
    assert total_split == 88
    # no absolute paths (and no pixels) in the report
    assert str(tmp_path) not in text
    assert str(Path.home()) not in text


# --------------------------------------------------------------------------------------------
# §4.4 split
# --------------------------------------------------------------------------------------------


def test_ca12_items_never_cross_splits(ds_large: Path) -> None:
    df = load_manifest(ds_large)
    result = make_split(df, seed=42)
    frame = result.frame
    assert list(frame.columns)[:2] == ["image_path", "split"]
    assert set(frame["image_path"]) == set(df["image_path"])
    merged = df[["image_path", "item_id"]].merge(frame, on="image_path")
    per_split = {
        w: set(merged.loc[merged["split"] == w, "item_id"]) for w in ("train", "val", "test")
    }
    assert not per_split["train"] & per_split["val"]
    assert not per_split["train"] & per_split["test"]
    assert not per_split["val"] & per_split["test"]
    assert (merged.groupby("item_id")["split"].nunique() == 1).all()
    assert set(merged["split"]) == {"train", "val", "test"}


def test_ca13_each_stratum_14_3_3(ds_large: Path) -> None:
    df = load_manifest(ds_large)
    frame = make_split(df, seed=42).frame
    merged = df.merge(frame, on="image_path")
    items = merged.groupby("item_id").agg(
        object_type=("object_type", "first"),
        grade=("grade", "first"),
        split=("split", "first"),
    )
    items["grade"] = items["grade"].fillna("none")
    strata = items.groupby(["object_type", "grade"])
    assert len(strata) == 11  # 2 types x 5 grades + other
    for name, group in strata:
        counts = group["split"].value_counts().to_dict()
        assert counts == {"train": 14, "val": 3, "test": 3}, (name, counts)


def test_ca14_small_stratum_goes_to_train(ds: Path) -> None:
    df = load_manifest(ds)
    drop = {"S-001", "S-006"}  # 2 of the 4 screw items of one grade (round-robin grades)
    grade = df.loc[df["item_id"] == "S-001", "grade"].iloc[0]
    assert df.loc[df["item_id"] == "S-006", "grade"].iloc[0] == grade
    sub = df[~df["item_id"].isin(drop)].reset_index(drop=True)
    remaining = sorted(
        sub.loc[(sub["object_type"] == "screw") & (sub["grade"] == grade), "item_id"].unique()
    )
    assert len(remaining) == 2
    result = make_split(sub, seed=42)
    merged = sub.merge(result.frame, on="image_path")
    assert set(merged.loc[merged["item_id"].isin(remaining), "split"]) == {"train"}
    small = [w for w in result.warnings if "small_stratum" in json.dumps(w, default=str)]
    assert small, result.warnings
    assert any(
        "screw" in json.dumps(w, default=str) and grade in json.dumps(w, default=str) for w in small
    )


def test_ca15_cli_reproducible_and_seed_matters(ds: Path, tmp_path: Path) -> None:
    outs = []
    for name, seed in (("a", "42"), ("b", "42"), ("c", "7")):
        splits = tmp_path / f"splits_{name}"
        args = ["--dataset-dir", str(ds), "--splits-dir", str(splits), "--seed", seed]
        result = run_module("qc_ml.split", args, tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        outs.append(splits)
    a, b, c = (s / "split_v1.csv" for s in outs)
    assert a.read_bytes() == b.read_bytes()
    digest = hashlib.sha256(a.read_bytes()).hexdigest()
    sha_line = (outs[0] / "split_v1.sha256").read_text(encoding="utf-8")
    assert sha_line == f"{digest}  split_v1.csv\n"
    ia = {k: next(iter(v)) for k, v in item_splits(read_split_csv(a)).items()}
    ic = {k: next(iter(v)) for k, v in item_splits(read_split_csv(c)).items()}
    assert ia.keys() == ic.keys()
    assert any(ia[k] != ic[k] for k in ia)


def test_ca16_frozen_test_with_new_items_and_images(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    v1 = read_split_csv(splits / "split_v1.csv")
    test_item = sorted(
        {item_of(p) for p, w in v1.items() if w == "test" and item_of(p).startswith("S-")}
    )[0]
    grade = next(r["grade"] for r in read_rows(ds) if r["item_id"] == test_item)
    new_test_images = [
        add_image(ds, test_item, "screw", grade, 3, "20261101T100000Z"),
        add_image(ds, test_item, "screw", grade, 4, "20261101T100100Z"),
    ]
    new_items = [f"S-{n:03d}" for n in range(101, 106)]
    new_item_images = []
    for k, item in enumerate(new_items):
        for angle in (0, 1):
            new_item_images.append(
                add_image(ds, item, "screw", "fair", angle, f"20261101T11{k:02d}{angle:02d}Z")
            )
    load_manifest(ds)  # the enlarged manifest is valid

    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    assert (splits / "split_v2.csv").exists()
    v2 = read_split_csv(splits / "split_v2.csv")
    for path, which in v1.items():
        assert v2[path] == which, path
    for path in new_item_images:
        assert v2[path] in ("train", "val"), path
    assert {p for p, w in v2.items() if w == "test"} == {
        p for p, w in v1.items() if w == "test"
    } | set(new_test_images)
    assert set(v2) == set(v1) | set(new_test_images) | set(new_item_images)
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    assert meta["parent"] == "split_v1"
    load_split(splits / "split_v2.csv")  # hash matches


def test_ca17_unchanged_writes_nothing(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    before = tree_snapshot(splits)
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0
    assert "split unchanged: split_v1" in out
    assert not (splits / "split_v2.csv").exists()
    assert tree_snapshot(splits) == before


def test_ca18_missing_test_image_is_an_error(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    v1 = read_split_csv(splits / "split_v1.csv")
    victim = sorted(p for p, w in v1.items() if w == "test")[0]
    write_rows(ds, [r for r in read_rows(ds) if r["image_path"] != victim])
    (ds / victim).unlink()
    before = tree_snapshot(splits)
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 2
    assert victim in out
    assert tree_snapshot(splits) == before


def test_ca19_load_split_detects_hand_edits(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    path = splits / "split_v1.csv"
    assert len(load_split(path)) == 88
    lines = path.read_text(encoding="utf-8").split("\n")
    idx = next(i for i, ln in enumerate(lines) if ln.endswith(",test"))
    lines[idx] = lines[idx][: -len("test")] + "train"
    path.write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(SplitError):
        load_split(path)


def test_ca20_rows_for_outdated_split(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    df = load_manifest(ds)
    split_df = load_split(splits / "split_v1.csv")
    train = rows_for(df, split_df, "train")
    assert 0 < len(train) < 88
    add_image(ds, "S-201", "screw", "good", 0, "20261101T120000Z")
    df_new = load_manifest(ds)
    with pytest.raises(SplitError, match="split outdated"):
        rows_for(df_new, split_df, "train")


# --------------------------------------------------------------------------------------------
# §4.3 agreement
# --------------------------------------------------------------------------------------------


def _agreement_case(ds: Path, first: list[int], second: list[int]) -> Path:
    """Pick screw images whose manifest grades are ``first``; write labels_second.csv."""
    pool: dict[str, list[str]] = {g: [] for g in GRADES}
    for r in read_rows(ds):
        if r["object_type"] == "screw":
            pool[r["grade"]].append(r["image_path"])
    rows = []
    for a, b in zip(first, second, strict=True):
        rows.append([pool[GRADES[a]].pop(0), GRADES[b], "b"])
    path = ds.parent / "labels_second.csv"
    write_csv(path, ["image_path", "grade", "labeler"], rows)
    return path


def _agreement_cli(ds: Path, second: Path, out: Path, capsys) -> tuple[int, str]:
    argv = ["--first", str(ds / "manifest.csv"), "--second", str(second), "--out", str(out)]
    return call_main(agreement_mod.main, argv, capsys)


def test_ca21_agreement_known_values(ds: Path, tmp_path: Path, capsys) -> None:
    first = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
    second = [0, 1, 2, 3, 4, 1, 1, 3, 3, 3]
    labels = _agreement_case(ds, first, second)
    out = tmp_path / "reports" / "agreement.json"
    rc, text = _agreement_cli(ds, labels, out, capsys)
    assert rc == 0, text
    report = json.loads(out.read_text(encoding="utf-8"))
    assert set(report) >= AGREEMENT_KEYS
    assert report["n_pairs"] == 10
    expected = cohen_kappa_score(first, second, weights="quadratic", labels=[0, 1, 2, 3, 4])
    assert report["qwk"] == pytest.approx(32 / 35, abs=1e-4)
    assert report["qwk"] == pytest.approx(expected, abs=1e-9)
    assert report["exact_agreement"] == pytest.approx(0.7)
    assert report["off_by_one_agreement"] == pytest.approx(1.0)
    assert report["confusion"][0][1] == 1
    assert len(report["confusion"]) == 5 and all(len(r) == 5 for r in report["confusion"])
    assert sum(map(sum, report["confusion"])) == 10
    assert report["grades"] == GRADES
    assert report["targets"] == {"minimum": 0.6, "desired": 0.8}
    assert report["meets_minimum"] is True
    assert report["meets_desired"] is True
    assert report["first_sha256"] == hashlib.sha256((ds / "manifest.csv").read_bytes()).hexdigest()
    assert report["second_sha256"] == hashlib.sha256(labels.read_bytes()).hexdigest()


def test_ca22_agreement_inverted(ds: Path, tmp_path: Path, capsys) -> None:
    first = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
    second = [4, 4, 3, 3, 2, 2, 1, 1, 0, 0]
    labels = _agreement_case(ds, first, second)
    out = tmp_path / "agreement.json"
    rc, text = _agreement_cli(ds, labels, out, capsys)
    assert rc == 0, text
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["qwk"] == pytest.approx(-1.0, abs=1e-6)
    assert report["meets_minimum"] is False
    assert report["meets_desired"] is False


def test_ca23_agreement_unknown_image(ds: Path, tmp_path: Path, capsys) -> None:
    labels = _agreement_case(ds, [0, 1, 2], [0, 1, 2])
    with labels.open("a", encoding="utf-8", newline="") as fh:
        fh.write("raw/screw/good/S-888__0__20261022T141503Z.jpg,good,b\n")
    out = tmp_path / "agreement.json"
    rc, text = _agreement_cli(ds, labels, out, capsys)
    assert rc == 2
    assert "S-888" in text
    assert not out.exists()


# --------------------------------------------------------------------------------------------
# §4.5 augmentations and dataset
# --------------------------------------------------------------------------------------------


def _photo(w: int = 300, h: int = 200) -> Image.Image:
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[..., 0] = np.linspace(40, 220, w, dtype=np.uint8)[None, :]
    arr[..., 1] = np.linspace(200, 60, h, dtype=np.uint8)[:, None]
    arr[..., 2] = 150
    return Image.fromarray(arr, "RGB")


def test_ca24_train_transform_deterministic(tmp_path: Path) -> None:
    img = _photo()
    out1 = train_transform(img, np.random.default_rng(1))
    out2 = train_transform(img, np.random.default_rng(1))
    assert out1.size == (256, 256) and out2.size == (256, 256)
    assert out1.mode == "RGB" and out2.mode == "RGB"
    assert np.array_equal(np.asarray(out1), np.asarray(out2))
    assert img.size == (300, 200)  # input untouched


def test_ca25_parts_dataset_eval_items(ds: Path) -> None:
    torch = pytest.importorskip("torch")
    from qc_ml.dataset import PartsDataset

    df = load_manifest(ds).reset_index(drop=True)
    params = PreprocessParams()
    labels = SimpleNamespace(object_types=["screw", "nut", "other"], grades=GRADES)
    dataset = PartsDataset(df, ds, labels, params, train=False)
    assert len(dataset) == 88
    i_nut = int(df.index[(df["object_type"] == "nut") & (df["grade"] == "poor")][0])
    tensor, type_idx, grade_idx = dataset[i_nut]
    assert isinstance(tensor, torch.Tensor)
    assert tuple(tensor.shape) == (3, 224, 224)
    assert tensor.dtype == torch.float32
    expected = preprocess(load_image(ds / df.loc[i_nut, "image_path"]), params)[0]
    assert np.array_equal(tensor.numpy(), expected)
    assert type_idx == 1
    assert grade_idx == 3
    i_other = int(df.index[df["object_type"] == "other"][0])
    _, type_other, grade_other = dataset[i_other]
    assert type_other == 2
    assert grade_other == -1


def test_ca26_modules_import_without_torch(tmp_path: Path) -> None:
    code = (
        "import sys\n"
        "sys.modules['torch'] = None\n"
        "import qc_ml.data, qc_ml.split, qc_ml.agreement, qc_ml.augment, qc_ml.synthetic\n"
        "assert sys.modules['torch'] is None\n"
        "assert 'torchvision' not in sys.modules and 'timm' not in sys.modules\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
    assert "ImportError" not in result.stderr


def test_ca27_no_images_tracked_under_ml() -> None:
    result = subprocess.run(
        ["git", "ls-files", "ml"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    tracked = [p for p in result.stdout.splitlines() if p]
    assert tracked, "git ls-files ml returned nothing"
    images = [
        p
        for p in tracked
        if p.lower().endswith((".jpg", ".jpeg", ".png")) and not p.startswith("ml/reports/")
    ]
    assert images == []


# --------------------------------------------------------------------------------------------
# SEC-24-03, SEC-10-03, SEC-10-02, SEC-10-08
# --------------------------------------------------------------------------------------------


def test_ca28_too_many_jpeg_scans(ds: Path, capsys) -> None:
    rows = read_rows(ds)
    screws = [r["image_path"] for r in rows if r["object_type"] == "screw"]
    motion, broken = screws[1], screws[4]
    raw = (ds / motion).read_bytes()
    assert raw.endswith(b"\xff\xd9") and raw.count(b"\xff\xda") == 1  # baseline synthetic JPEG
    (ds / motion).write_bytes(raw + b"\xff\xda" * 64)
    (ds / broken).write_bytes(b"not an image")

    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    problems = problems_of(excinfo)
    scans = [p for p in problems if p.code == "too_many_jpeg_scans"]
    unreadable = [p for p in problems if p.code == "unreadable_image"]
    assert len(problems) == 2
    assert [p.image_path for p in scans] == [motion]
    assert "JPEG scans" in scans[0].message
    assert "dataset-protocol" in scans[0].message
    assert [p.image_path for p in unreadable] == [broken]

    rc, out = call_main(data_mod.main, ["validate", "--dataset-dir", str(ds)], capsys)
    assert rc == 2
    lines = out.splitlines()
    assert "count too_many_jpeg_scans: 1" in lines
    assert "count unreadable_image: 1" in lines
    assert lines.index("count too_many_jpeg_scans: 1") < lines.index("count unreadable_image: 1")

    assert len(load_manifest(ds, verify_images=False)) == 88


def test_ca29_manifest_read_as_csv_not_by_lines(ds: Path) -> None:
    notes = "a b c‮d"
    device = "Phone\x85X"
    rows = read_rows(ds)
    rows[10]["notes"] = notes
    rows[30]["capture_device"] = device
    with (ds / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(MANIFEST_HEADER)
        for r in rows:
            writer.writerow([r[c] for c in MANIFEST_HEADER])
    text = (ds / "manifest.csv").read_text(encoding="utf-8")
    assert len(text.splitlines()) > 89

    df = load_manifest(ds)
    assert len(df) == 88
    assert df[df["image_path"] == rows[10]["image_path"]].iloc[0]["notes"] == notes
    assert df[df["image_path"] == rows[30]["image_path"]].iloc[0]["capture_device"] == device


def test_ca30_orphan_image(ds: Path, capsys) -> None:
    orphan = "raw/screw/fair/S-099__0__20261022T141503Z.jpg"
    write_jpeg(ds / orphan)
    (ds / "raw/screw/fair/tmpab12cd").write_bytes(b"\xff\xd8 partial upload")
    for verify in (True, False):
        with pytest.raises(ManifestError) as excinfo:
            load_manifest(ds, verify_images=verify)
        problems = problems_of(excinfo)
        assert codes(problems) == ["orphan_image"], verify
        assert problems[0].image_path == orphan
        assert problems[0].line is None
    rc, out = call_main(data_mod.main, ["validate", "--dataset-dir", str(ds)], capsys)
    assert rc == 2
    assert "count orphan_image: 1" in out.splitlines()


def test_ca31_exclusions(ds: Path, tmp_path: Path, capsys) -> None:
    rows = read_rows(ds)
    excluded = next(r["image_path"] for r in rows if r["item_id"] == "S-002")
    excl_file = ds / "exclusions.csv"

    # the file is still on disk -> excluded_file_present
    write_csv(excl_file, ["image_path", "reason"], [[excluded, "person"]])
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    present = [p for p in problems_of(excinfo) if p.code == "excluded_file_present"]
    assert [p.image_path for p in present] == [excluded]

    # deleted file + exclusion -> no error, 87 rows
    (ds / excluded).unlink()
    df = load_manifest(ds)
    assert len(df) == 87
    assert excluded not in set(df["image_path"])
    assert load_exclusions(ds) == frozenset({excluded})
    assert len(load_manifest(ds, apply_overrides=False)) == 87
    assert build_data_report(df, None)["n_excluded"] == 1

    # an override for the excluded image is ignored without error
    write_csv(
        ds / "labels_overrides.csv",
        ["image_path", "grade", "labeler", "reason"],
        [[excluded, "unusable", "b", "should be ignored"]],
    )
    df = load_manifest(ds)
    assert len(df) == 87
    assert not df["overridden"].astype(bool).any()
    (ds / "labels_overrides.csv").unlink()

    # invalid reason
    write_csv(excl_file, ["image_path", "reason"], [[excluded, "selfie"]])
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    assert "exclusion_invalid_reason" in codes(problems_of(excinfo))

    # image_path absent from the manifest
    unknown = "raw/screw/good/S-555__0__20261022T141503Z.jpg"
    write_csv(excl_file, ["image_path", "reason"], [[excluded, "person"], [unknown, "other"]])
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    problems = problems_of(excinfo)
    assert [p.image_path for p in problems if p.code == "exclusion_unknown_image"] == [unknown]

    # agreement: excluded image + 9 other screw/nut images
    write_csv(excl_file, ["image_path", "reason"], [[excluded, "person"]])
    others = [
        r for r in rows if r["object_type"] in ("screw", "nut") and r["image_path"] != excluded
    ][:9]
    second = ds.parent / "labels_second.csv"
    write_csv(
        second,
        ["image_path", "grade", "labeler"],
        [[excluded, "good", "b"]] + [[r["image_path"], r["grade"], "b"] for r in others],
    )
    out = tmp_path / "agreement.json"
    rc, text = _agreement_cli(ds, second, out, capsys)
    assert rc == 0, text
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["n_pairs"] == 9
    assert report["n_excluded_pairs"] == 1


def test_ca32_excluded_test_image_leaves_the_split(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    v1 = read_split_csv(splits / "split_v1.csv")
    victim = sorted(p for p, w in v1.items() if w == "test")[0]
    (ds / victim).unlink()
    write_csv(ds / "exclusions.csv", ["image_path", "reason"], [[victim, "person"]])

    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    v2 = read_split_csv(splits / "split_v2.csv")
    assert victim not in v2
    assert {p: w for p, w in v1.items() if p != victim} == v2
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    hits = [
        w
        for w in meta["warnings"]
        if isinstance(w, dict)
        and "excluded_previous_image" in json.dumps(w)
        and w.get("image_path") == victim
        and w.get("split") == "test"
    ]
    assert len(hits) == 1, meta["warnings"]


# --------------------------------------------------------------------------------------------
# §4.4 split history (r3: SPEC_ISSUE-01 of r2, T-02)
# --------------------------------------------------------------------------------------------


def _write_hash(splits: Path, name: str) -> None:
    body = (splits / f"{name}.csv").read_bytes()
    (splits / f"{name}.sha256").write_text(
        f"{hashlib.sha256(body).hexdigest()}  {name}.csv\n", encoding="utf-8"
    )


def test_ca33_rephoto_after_an_intermediate_split(ds_large: Path, tmp_path: Path, capsys) -> None:
    ds = ds_large
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    v1 = read_split_csv(splits / "split_v1.csv")
    p_t = first_item_in(v1, "test", "screw")
    p_v = first_item_in(v1, "val", "nut")
    old_t = exclude_item(ds, p_t)
    old_v = exclude_item(ds, p_v)

    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    v2 = read_split_csv(splits / "split_v2.csv")
    assert not {item_of(p) for p in v2} & {p_t, p_v}

    new_t = [
        add_image(ds, p_t, "screw", old_t[0]["grade"], a, f"20261201T10000{a}Z") for a in (0, 1)
    ]
    new_v = [add_image(ds, p_v, "nut", old_v[0]["grade"], a, f"20261201T11000{a}Z") for a in (0, 1)]
    assert not set(new_t + new_v) & {r["image_path"] for r in old_t + old_v}
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    assert (splits / "split_v3.csv").exists()
    v3 = read_split_csv(splits / "split_v3.csv")
    assert [v3[p] for p in new_t] == ["test", "test"]
    assert [v3[p] for p in new_v] == ["val", "val"]
    for path, which in v2.items():
        assert v3[path] == which, path
    test_items = lambda v: {item_of(p) for p, w in v.items() if w == "test"}  # noqa: E731
    assert test_items(v3) == test_items(v1)


@pytest.fixture
def history_state(ds_large: Path, tmp_path: Path, capsys) -> tuple[Path, Path]:
    """CA-34 state: split_v1, split_v2 (5 new screw/fair items), then 1 more new item."""
    ds = ds_large
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    for k, item in enumerate(f"S-{n}" for n in range(201, 206)):
        for a in (0, 1):
            add_image(ds, item, "screw", "fair", a, f"20261202T10{k:02d}0{a}Z")
    assert split_cli(ds, splits, capsys)[0] == 0
    assert (splits / "split_v2.csv").exists()
    for a in (0, 1):
        add_image(ds, "S-206", "screw", "fair", a, f"20261202T11000{a}Z")
    return ds, splits


def _run_case(ds: Path, splits: Path, capsys) -> tuple[int, str]:
    before = tree_snapshot(splits)
    rc, out = split_cli(ds, splits, capsys)
    assert tree_snapshot(splits) == before  # names and bytes unchanged
    assert not list(splits.glob("split_v3.*"))
    return rc, out


def test_ca34_history_gap(history_state: tuple[Path, Path], capsys) -> None:
    ds, splits = history_state
    safe_unlink(splits, "split_v1.csv")  # .sha256 and .json kept
    rc, out = _run_case(ds, splits, capsys)
    assert rc == 2
    assert "split history incomplete" in out
    assert "split_v1.csv" in out


def test_ca34_hash_mismatch_in_an_old_version(history_state: tuple[Path, Path], capsys) -> None:
    ds, splits = history_state
    path = splits / "split_v1.csv"
    path.write_text(path.read_text(encoding="utf-8").replace(",test\n", ",train\n", 1), "utf-8")
    rc, out = _run_case(ds, splits, capsys)
    assert rc == 2
    assert "split_v1.csv" in out


def test_ca34_conflict_in_the_history(history_state: tuple[Path, Path], capsys) -> None:
    ds, splits = history_state
    path = splits / "split_v1.csv"
    v1 = read_split_csv(path)
    item = first_item_in(v1, "test")
    lines = path.read_text(encoding="utf-8").split("\n")
    lines = [
        ln[: -len("test")] + "val" if ln.endswith(",test") and item_of(ln) == item else ln
        for ln in lines
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    _write_hash(splits, "split_v1")  # re-hashed by hand: load_split accepts it
    assert (
        read_split_csv(splits / "split_v2.csv")[sorted(p for p in v1 if item_of(p) == item)[0]]
        == "test"
    )
    rc, out = _run_case(ds, splits, capsys)
    assert rc == 2
    assert item in out
    assert "split_v1.csv" in out
    assert "split_v2.csv" in out
    with pytest.raises(SplitIntegrityError, match=item):
        item_history(
            [load_split(splits / "split_v1.csv"), load_split(splits / "split_v2.csv")],
            load_manifest(ds),
        )


def test_ca35_make_split_with_history(ds_large: Path) -> None:
    df = load_manifest(ds_large)
    v1 = make_split(df, seed=42).frame
    mapping = dict(zip(v1["image_path"], v1["split"], strict=True))
    test_items = sorted({item_of(p) for p, w in mapping.items() if w == "test"})
    p_item, q_item = test_items[0], test_items[1]
    e_paths = set(df.loc[df["item_id"] == p_item, "image_path"])
    v2 = make_split(
        df[~df["image_path"].isin(e_paths)], seed=42, previous=v1, excluded=frozenset(e_paths)
    ).frame
    assert not set(v2["image_path"]) & e_paths
    p_rows = df[df["item_id"] == p_item].head(2).copy()
    p_rows["image_path"] = [
        f"{Path(p).parent.as_posix()}/{p_item}__{k}__20261203T10000{k}Z.jpg"
        for k, p in enumerate(p_rows["image_path"])
    ]
    df3 = pd.concat([df[~df["image_path"].isin(e_paths)], p_rows], ignore_index=True)

    result = make_split(df3, seed=42, previous=v2, history={p_item: "test"})
    got = dict(zip(result.frame["image_path"], result.frame["split"], strict=True))
    assert [got[p] for p in p_rows["image_path"]] == ["test", "test"]
    for path, which in zip(v2["image_path"], v2["split"], strict=True):
        assert got[path] == which

    with pytest.raises(SplitIntegrityError, match=q_item):
        make_split(df3, seed=42, previous=v2, history={p_item: "test", q_item: "train"})
    with pytest.raises(SplitError):
        make_split(df3, seed=42, previous=v2, history={p_item: "holdout"})
    with pytest.raises(SplitError):
        make_split(df3, seed=42, history={p_item: "test"})


# --------------------------------------------------------------------------------------------
# Exploratory (no CA): edge cases around the SPEC
# --------------------------------------------------------------------------------------------


def test_extra_split_files_format(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    raw = (splits / "split_v1.csv").read_bytes()
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    lines = text.rstrip("\n").split("\n")
    assert lines[0] == "image_path,split"
    paths = [ln.rsplit(",", 1)[0] for ln in lines[1:]]
    assert paths == sorted(paths)
    assert {ln.rsplit(",", 1)[1] for ln in lines[1:]} == {"train", "val", "test"}
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["seed"] == 42
    assert list(meta["ratios"]) == [0.70, 0.15, 0.15]
    assert meta["parent"] is None
    assert meta["manifest_sha256"] == hashlib.sha256((ds / "manifest.csv").read_bytes()).hexdigest()
    assert "warnings" in meta
    # split files carry no absolute paths
    for name in ("split_v1.csv", "split_v1.json", "split_v1.sha256"):
        assert str(tmp_path) not in (splits / name).read_text(encoding="utf-8")


def test_extra_round_half_up_and_minimums() -> None:
    def sizes(n: int) -> dict[str, int]:
        df = fake_frame([(f"S-{k:03d}", "screw", ["good"]) for k in range(1, n + 1)])
        frame = make_split(df, seed=42).frame
        return frame["split"].value_counts().to_dict()

    assert sizes(30) == {"train": 20, "val": 5, "test": 5}  # 4.5 -> 5 (round would give 4)
    assert sizes(10) == {"train": 6, "val": 2, "test": 2}  # 1.5 -> 2
    assert sizes(3) == {"train": 1, "val": 1, "test": 1}  # minimum 1 in val and test
    assert sizes(4) == {"train": 2, "val": 1, "test": 1}  # 0.6 -> 1
    assert sizes(2) == {"train": 2}


def test_extra_dominant_grade_tie_goes_to_the_most_severe() -> None:
    # S-001: good + poor (tie -> poor); S-002: poor. The poor stratum has 2 items -> small_stratum.
    df = fake_frame([("S-001", "screw", ["good", "poor"]), ("S-002", "screw", ["poor"])])
    warnings = make_split(df, seed=42).warnings
    text = json.dumps(warnings, default=str)
    assert "small_stratum" in text
    assert "poor" in text
    assert "good" not in text  # the tie did not create a "good" stratum


def test_extra_make_split_is_deterministic(ds_large: Path) -> None:
    df = load_manifest(ds_large)
    a = make_split(df, seed=42).frame.sort_values("image_path").reset_index(drop=True)
    b = make_split(df.sample(frac=1.0, random_state=3), seed=42).frame
    b = b.sort_values("image_path").reset_index(drop=True)
    pd.testing.assert_frame_equal(a[["image_path", "split"]], b[["image_path", "split"]])


def test_extra_split_versions_use_numeric_order(ds: Path, tmp_path: Path, capsys) -> None:
    """Versions 1..10 complete (r3: a gap exits 2, §4.4 step 3); v10 is the latest, not v9."""
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    body = (splits / "split_v1.csv").read_bytes()
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    for n in range(2, 11):
        (splits / f"split_v{n}.csv").write_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        (splits / f"split_v{n}.sha256").write_text(f"{digest}  split_v{n}.csv\n", encoding="utf-8")
        meta["parent"] = f"split_v{n - 1}"
        (splits / f"split_v{n}.json").write_text(json.dumps(meta), encoding="utf-8")
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    assert "split unchanged: split_v10" in out


def test_extra_third_version_has_parent_v2(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    add_image(ds, "S-301", "screw", "good", 0, "20261102T100000Z")
    assert split_cli(ds, splits, capsys)[0] == 0
    add_image(ds, "S-302", "screw", "good", 0, "20261102T110000Z")
    assert split_cli(ds, splits, capsys)[0] == 0
    meta = json.loads((splits / "split_v3.json").read_text(encoding="utf-8"))
    assert meta["parent"] == "split_v2"
    v2 = read_split_csv(splits / "split_v2.csv")
    v3 = read_split_csv(splits / "split_v3.csv")
    assert all(v3[p] == w for p, w in v2.items())
    assert v3["raw/screw/good/S-302__0__20261102T110000Z.jpg"] == "train"


def test_extra_split_cli_with_invalid_manifest(ds: Path, tmp_path: Path, capsys) -> None:
    (ds / read_rows(ds)[0]["image_path"]).unlink()
    splits = tmp_path / "splits"
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 2
    assert "missing_file" in out
    assert not splits.exists() or not any(splits.iterdir())


def test_extra_split_cli_with_missing_dataset(tmp_path: Path, capsys) -> None:
    rc, _ = split_cli(tmp_path / "nope", tmp_path / "splits", capsys)
    assert rc == 2


def test_extra_missing_train_val_image_is_a_warning(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    v1 = read_split_csv(splits / "split_v1.csv")
    victim = sorted(p for p, w in v1.items() if w == "train")[0]
    write_rows(ds, [r for r in read_rows(ds) if r["image_path"] != victim])
    (ds / victim).unlink()
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    assert "missing_previous_image" in json.dumps(meta["warnings"])
    assert victim not in read_split_csv(splits / "split_v2.csv")


def test_extra_load_split_without_sha256(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    (splits / "split_v1.sha256").unlink()
    with pytest.raises(SplitError):
        load_split(splits / "split_v1.csv")


def test_extra_rows_for_partitions_the_manifest(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    df = load_manifest(ds)
    split_df = load_split(splits / "split_v1.csv")
    parts = {w: rows_for(df, split_df, w) for w in ("train", "val", "test")}
    assert sum(len(p) for p in parts.values()) == 88
    seen: set[str] = set()
    for part in parts.values():
        assert not seen & set(part["item_id"])
        seen |= set(part["item_id"])
    assert set(MANIFEST_HEADER) <= set(parts["train"].columns)


def test_extra_rows_for_detects_item_in_two_splits(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    df = load_manifest(ds)
    split_df = load_split(splits / "split_v1.csv").copy()
    first = split_df.index[0]
    item = item_of(split_df.loc[first, "image_path"])
    sibling = split_df.index[
        (split_df["image_path"].map(item_of) == item) & (split_df.index != first)
    ][0]
    split_df.loc[sibling, "split"] = "test" if split_df.loc[first, "split"] != "test" else "train"
    with pytest.raises(SplitIntegrityError):
        rows_for(df, split_df, "train")


@pytest.mark.parametrize(
    ("column", "value", "code"),
    [
        ("object_type", "bolt", "invalid_object_type"),
        ("item_id", "T-001", "item_prefix_mismatch"),
        ("angle", "1.5", "invalid_angle"),
        ("angle", "-1", "invalid_angle"),
        ("item_id", "S-0001", "invalid_item_id"),
        ("item_id", "s-001", "invalid_item_id"),
        ("grade", "Fair", "invalid_grade"),
    ],
)
def test_extra_invalid_cells(ds: Path, column: str, value: str, code: str) -> None:
    rows = read_rows(ds)
    rows[4][column] = value
    write_rows(ds, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    assert code in codes(problems_of(excinfo))


def test_extra_duplicate_image_path(ds: Path) -> None:
    rows = read_rows(ds)
    rows.append(dict(rows[3]))
    write_rows(ds, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    assert "duplicate_image_path" in codes(problems_of(excinfo))


def test_extra_duplicate_detected_even_when_excluded(ds: Path) -> None:
    rows = read_rows(ds)
    rows.append(dict(rows[3]))
    write_rows(ds, rows)
    (ds / rows[3]["image_path"]).unlink()
    write_csv(ds / "exclusions.csv", ["image_path", "reason"], [[rows[3]["image_path"], "other"]])
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    assert "duplicate_image_path" in codes(problems_of(excinfo))


def test_extra_override_missing_reason(ds: Path) -> None:
    target = read_rows(ds)[0]["image_path"]
    write_csv(
        ds / "labels_overrides.csv",
        ["image_path", "grade", "labeler", "reason"],
        [[target, "poor", "b", ""]],
    )
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    assert "override_missing_reason" in codes(problems_of(excinfo))


def test_extra_overrides_off(ds: Path) -> None:
    target = next(r for r in read_rows(ds) if r["grade"] == "fair")
    write_csv(
        ds / "labels_overrides.csv",
        ["image_path", "grade", "labeler", "reason"],
        [[target["image_path"], "poor", "b", "x"]],
    )
    df = load_manifest(ds, apply_overrides=False)
    assert df[df["image_path"] == target["image_path"]].iloc[0]["grade"] == "fair"


def test_extra_missing_column_aborts(ds: Path) -> None:
    rows = read_rows(ds)
    with (ds / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        header = [c for c in MANIFEST_HEADER if c != "angle"]
        writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    assert codes(problems_of(excinfo)) == ["missing_column"]


def test_extra_crlf_manifest_is_accepted(ds: Path) -> None:
    rows = read_rows(ds)
    with (ds / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_HEADER, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    assert len(load_manifest(ds)) == 88


def test_extra_header_only_manifest(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    (root / "raw").mkdir(parents=True)
    write_csv(root / "manifest.csv", MANIFEST_HEADER, [])
    assert len(load_manifest(root)) == 0


def test_extra_unicode_notes_round_trip(ds: Path) -> None:
    rows = read_rows(ds)
    rows[1]["notes"] = 'dúvida fair/poor, "aspas" e emoji \U0001f529\nsegunda linha'
    rows[2]["notes"] = "=SUM(A1:A2)"
    write_rows(ds, rows)
    df = load_manifest(ds)
    assert df[df["image_path"] == rows[1]["image_path"]].iloc[0]["notes"] == rows[1]["notes"]
    assert df[df["image_path"] == rows[2]["image_path"]].iloc[0]["notes"] == "=SUM(A1:A2)"


def test_extra_line_numbers_are_records_not_physical_lines(ds: Path) -> None:
    rows = read_rows(ds)
    rows[1]["notes"] = "line one\nline two\nline three"
    rows[5]["grade"] = "rusty"
    write_rows(ds, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    bad = [p for p in problems_of(excinfo) if p.code == "invalid_grade"]
    assert [p.line for p in bad] == [7]


def test_extra_orphan_rules(ds: Path) -> None:
    # a .jpg outside raw/ is not an orphan; a symlinked .jpg under raw/ is not followed
    write_jpeg(ds / "elsewhere" / "S-500__0__20261022T141503Z.jpg")
    outside = ds.parent / "outside"
    write_jpeg(outside / "S-501__0__20261022T141503Z.jpg")
    (ds / "raw" / "linked").symlink_to(outside, target_is_directory=True)
    (ds / "raw" / "screw" / "fair" / "S-502__0__20261022T141503Z.jpg.part").write_bytes(b"x")
    assert len(load_manifest(ds)) == 88


def test_extra_orphan_is_relative_path(ds: Path) -> None:
    orphan = "raw/nut/poor/N-777__1__20261022T141503Z.jpg"
    write_jpeg(ds / orphan)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    (problem,) = problems_of(excinfo)
    assert problem.image_path == orphan
    assert str(ds) not in str(problem)


def test_extra_exclusion_empty_reason(ds: Path) -> None:
    victim = read_rows(ds)[0]["image_path"]
    (ds / victim).unlink()
    write_csv(ds / "exclusions.csv", ["image_path", "reason"], [[victim, ""]])
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    assert "exclusion_invalid_reason" in codes(problems_of(excinfo))


def test_extra_load_exclusions_without_file(ds: Path) -> None:
    assert load_exclusions(ds) == frozenset()


def test_extra_manifest_error_str_one_problem_per_line(ds: Path) -> None:
    rows = read_rows(ds)
    rows[0]["grade"] = "rusty"
    rows[1]["angle"] = "9"
    write_rows(ds, rows)
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    text = str(excinfo.value)
    assert any("invalid_grade" in ln for ln in text.splitlines())
    assert any("invalid_angle" in ln for ln in text.splitlines())
    assert not any("invalid_grade" in ln and "invalid_angle" in ln for ln in text.splitlines())


def test_extra_validate_ok_exit_zero(ds: Path, capsys) -> None:
    rc, _ = call_main(data_mod.main, ["validate", "--dataset-dir", str(ds)], capsys)
    assert rc == 0


def test_extra_validate_count_lines_alphabetical(ds: Path, capsys) -> None:
    rows = read_rows(ds)
    rows[0]["grade"] = "rusty"
    rows[1]["angle"] = "9"
    rows[2]["angle"] = "8"
    (ds / rows[3]["image_path"]).unlink()
    write_rows(ds, rows)
    rc, out = call_main(data_mod.main, ["validate", "--dataset-dir", str(ds)], capsys)
    assert rc == 2
    counts = [ln for ln in out.splitlines() if ln.startswith("count ")]
    assert counts == ["count invalid_angle: 2", "count invalid_grade: 1", "count missing_file: 1"]
    last_problem = max(i for i, ln in enumerate(out.splitlines()) if ln and "count " not in ln)
    first_count = out.splitlines().index(counts[0])
    assert last_problem < first_count


def test_extra_report_without_split(ds: Path, tmp_path: Path, capsys) -> None:
    df = load_manifest(ds)
    report = build_data_report(df, None)
    assert report["split_sha256"] is None
    assert report["n_images"] == 88
    json.dumps(report)  # serializable


def test_extra_agreement_no_pairs_and_invalid_grade(ds: Path, tmp_path: Path, capsys) -> None:
    other = next(r["image_path"] for r in read_rows(ds) if r["object_type"] == "other")
    second = ds.parent / "labels_second.csv"
    write_csv(second, ["image_path", "grade", "labeler"], [[other, "good", "b"]])
    out = tmp_path / "agreement.json"
    rc, _ = _agreement_cli(ds, second, out, capsys)
    assert rc == 2
    assert not out.exists()

    screw = next(r["image_path"] for r in read_rows(ds) if r["object_type"] == "screw")
    write_csv(second, ["image_path", "grade", "labeler"], [[screw, "rusty", "b"]])
    rc, _ = _agreement_cli(ds, second, out, capsys)
    assert rc == 2
    assert not out.exists()


def test_extra_agreement_ignores_overrides(ds: Path, tmp_path: Path, capsys) -> None:
    labels = _agreement_case(ds, [2, 2, 2], [2, 2, 2])
    first_path = next(csv.reader(io.StringIO(labels.read_text(encoding="utf-8").split("\n")[1])))[0]
    write_csv(
        ds / "labels_overrides.csv",
        ["image_path", "grade", "labeler", "reason"],
        [[first_path, "unusable", "b", "decided together"]],
    )
    out = tmp_path / "agreement.json"
    rc, text = _agreement_cli(ds, labels, out, capsys)
    assert rc == 0, text
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["exact_agreement"] == pytest.approx(1.0)


def test_extra_train_transform_variety_and_no_black_fill() -> None:
    img = Image.new("RGB", (300, 200), (235, 232, 228))
    outs = [np.asarray(train_transform(img, np.random.default_rng(s))) for s in range(30)]
    for arr in outs:
        assert arr.shape == (256, 256, 3)
        assert arr.min() > 60, "rotation fill looks black"
    photo = _photo()
    a = np.asarray(train_transform(photo, np.random.default_rng(1)))
    b = np.asarray(train_transform(photo, np.random.default_rng(2)))
    assert not np.array_equal(a, b)


@pytest.mark.parametrize("mode", ["L", "RGBA", "P"])
def test_extra_train_transform_other_modes(mode: str) -> None:
    img = _photo(120, 400).convert(mode)
    out = train_transform(img, np.random.default_rng(5))
    assert out.mode == "RGB" and out.size == (256, 256)


def test_extra_synthetic_dataset_layout(tmp_path: Path) -> None:
    root = tmp_path / "syn"
    make_synthetic_dataset(root, items_per_stratum=1, images_per_item=1, include_other=False)
    rows = read_rows(root)
    assert len(rows) == 10
    assert all(r["object_type"] in ("screw", "nut") for r in rows)
    for r in rows:
        parts = Path(r["image_path"]).parts
        assert parts[0] == "raw" and parts[1] == r["object_type"] and parts[2] == r["grade"]
        with Image.open(root / r["image_path"]) as im:
            assert im.format == "JPEG" and im.size == (256, 256)
    assert len(load_manifest(root)) == 10


def test_extra_report_cli_with_outdated_split(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    add_image(ds, "S-401", "screw", "poor", 0, "20261103T100000Z")
    out_file = tmp_path / "data_report.json"
    argv = ["report", "--dataset-dir", str(ds), "--split", str(splits / "split_v1.csv")]
    rc, out = call_main(data_mod.main, [*argv, "--out", str(out_file)], capsys)
    assert rc == 2
    assert "split outdated" in out
    assert not out_file.exists()


def test_extra_split_cli_refuses_edited_previous(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    path = splits / "split_v1.csv"
    path.write_text(path.read_text(encoding="utf-8").replace(",test\n", ",train\n", 1), "utf-8")
    add_image(ds, "S-402", "screw", "poor", 0, "20261103T110000Z")
    before = tree_snapshot(splits)
    rc, _ = split_cli(ds, splits, capsys)
    assert rc == 2
    assert tree_snapshot(splits) == before


def test_extra_validate_non_utf8_and_missing_manifest(ds: Path, tmp_path: Path, capsys) -> None:
    rc, _ = call_main(data_mod.main, ["validate", "--dataset-dir", str(tmp_path / "x")], capsys)
    assert rc == 2
    rows = read_rows(ds)
    rows[0]["notes"] = "dúvida"
    with (ds / "manifest.csv").open("w", encoding="latin-1", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    rc, _ = call_main(data_mod.main, ["validate", "--dataset-dir", str(ds)], capsys)
    assert rc == 2


@pytest.mark.parametrize(
    "bad_path", ["/etc/passwd", "../outside.jpg", "raw/../../outside.jpg", "raw//x.jpg"]
)
def test_extra_image_path_cannot_escape_the_dataset(ds: Path, bad_path: str) -> None:
    rows = read_rows(ds)
    original = ds / rows[0]["image_path"]
    rows[0]["image_path"] = bad_path
    write_rows(ds, rows)
    original.unlink()  # the original file of row 0 (inside tmp_path), so it is not an orphan
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(ds)
    assert any(p.image_path == bad_path for p in problems_of(excinfo))


# ---- RV-01 / T-01 (r2): re-photographed items keep the split of their old images ----------


def safe_unlink(root: Path, rel: str) -> None:
    """Delete ``root/rel`` only if it resolves inside ``root`` (always a tmp_path dataset)."""
    target = (root / rel).resolve()
    assert target.is_relative_to(root.resolve()), target
    target.unlink()


def exclude_item(ds: Path, item: str) -> list[dict[str, str]]:
    """Delete every image of ``item`` and append them to exclusions.csv (dataset-protocol §8.1)."""
    old_rows = [r for r in read_rows(ds) if r["item_id"] == item]
    assert old_rows
    for r in old_rows:
        safe_unlink(ds, r["image_path"])
    path = ds / "exclusions.csv"
    previous: list[list[str]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as fh:
            previous = [[r["image_path"], r["reason"]] for r in csv.DictReader(fh)]
    write_csv(
        path, ["image_path", "reason"], previous + [[r["image_path"], "person"] for r in old_rows]
    )
    return old_rows


def first_item_in(v: dict[str, str], which: str, object_type: str = "screw") -> str:
    return sorted(
        item_of(p) for p, w in v.items() if w == which and p.startswith(f"raw/{object_type}/")
    )[0]


def other_grade(grade: str) -> str:
    return GRADES[(GRADES.index(grade) + 1) % len(GRADES)]


def test_extra_t01_rephotographed_test_item_keeps_test(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    v1 = read_split_csv(splits / "split_v1.csv")
    item = first_item_in(v1, "test")
    old_rows = exclude_item(ds, item)
    grade = old_rows[0]["grade"]
    new = [
        add_image(ds, item, "screw", grade, 0, "20261104T100000Z"),
        add_image(ds, item, "screw", grade, 1, "20261104T100100Z"),
    ]
    assert split_cli(ds, splits, capsys)[0] == 0
    v2 = read_split_csv(splits / "split_v2.csv")
    assert [v2[p] for p in new] == ["test", "test"]


@pytest.mark.parametrize("which", ["test", "val", "train"])
def test_extra_rephotographed_item_keeps_its_split(
    ds: Path, tmp_path: Path, capsys, which: str
) -> None:
    """All old images excluded; re-photographed at a later corrosion stage (another grade)."""
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    v1 = read_split_csv(splits / "split_v1.csv")
    item = first_item_in(v1, which, "nut")
    old_rows = exclude_item(ds, item)
    grade = other_grade(old_rows[0]["grade"])
    new = [
        add_image(ds, item, "nut", grade, 2, "20261105T100000Z"),
        add_image(ds, item, "nut", grade, 3, "20261105T100100Z"),
        add_image(ds, item, "nut", grade, 4, "20261105T100200Z"),
    ]
    assert split_cli(ds, splits, capsys)[0] == 0
    v2 = read_split_csv(splits / "split_v2.csv")
    assert [v2[p] for p in new] == [which] * 3
    old_paths = {r["image_path"] for r in old_rows}
    assert {p: w for p, w in v1.items() if p not in old_paths} == {
        p: w for p, w in v2.items() if p not in new
    }
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    excluded_warnings = [w for w in meta["warnings"] if w.get("code") == "excluded_previous_image"]
    assert sorted(w["image_path"] for w in excluded_warnings) == sorted(old_paths)
    assert {w["split"] for w in excluded_warnings} == {which}
    # integrity of the new version (R-11)
    assert all(len(s) == 1 for s in item_splits(v2).values())


def test_extra_removed_without_exclusion_val_item_keeps_val(
    ds: Path, tmp_path: Path, capsys
) -> None:
    """Old val images removed from the manifest and the disk (no exclusion): file-name fallback."""
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    v1 = read_split_csv(splits / "split_v1.csv")
    item = first_item_in(v1, "val")
    old_rows = [r for r in read_rows(ds) if r["item_id"] == item]
    write_rows(ds, [r for r in read_rows(ds) if r["item_id"] != item])
    for r in old_rows:
        safe_unlink(ds, r["image_path"])
    new = add_image(ds, item, "screw", old_rows[0]["grade"], 0, "20261106T100000Z")
    assert split_cli(ds, splits, capsys)[0] == 0
    v2 = read_split_csv(splits / "split_v2.csv")
    assert v2[new] == "val"
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    missing = [w for w in meta["warnings"] if w.get("code") == "missing_previous_image"]
    assert sorted(w["image_path"] for w in missing) == sorted(r["image_path"] for r in old_rows)


def test_extra_removed_without_exclusion_test_item_still_errors(
    ds: Path, tmp_path: Path, capsys
) -> None:
    """Re-photographing does not legalize test images removed without exclusions.csv (CA-18)."""
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    v1 = read_split_csv(splits / "split_v1.csv")
    item = first_item_in(v1, "test")
    old_rows = [r for r in read_rows(ds) if r["item_id"] == item]
    write_rows(ds, [r for r in read_rows(ds) if r["item_id"] != item])
    for r in old_rows:
        safe_unlink(ds, r["image_path"])
    add_image(ds, item, "screw", old_rows[0]["grade"], 0, "20261106T110000Z")
    before = tree_snapshot(splits)
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 2
    assert old_rows[0]["image_path"] in out
    assert tree_snapshot(splits) == before


def test_extra_make_split_without_attrs_uses_file_names(ds: Path) -> None:
    df = load_manifest(ds)
    v1 = make_split(df, seed=42).frame
    mapping = dict(zip(v1["image_path"], v1["split"], strict=True))
    item = first_item_in(mapping, "test")
    old_rows = exclude_item(ds, item)
    add_image(ds, item, "screw", old_rows[0]["grade"], 0, "20261107T100000Z")
    df2 = load_manifest(ds)
    df2.attrs = {}  # a DataFrame built by hand: no excluded_items
    result = make_split(df2, seed=42, previous=v1, excluded=load_exclusions(ds))
    got = dict(zip(result.frame["image_path"], result.frame["split"], strict=True))
    assert got[f"raw/screw/{old_rows[0]['grade']}/{item}__0__20261107T100000Z.jpg"] == "test"


def test_extra_old_images_in_two_splits_is_an_integrity_error(ds: Path) -> None:
    """A (hand-made) previous split with the old images of one item in two splits."""
    df = load_manifest(ds)
    v1 = make_split(df, seed=42).frame.copy()
    mapping = dict(zip(v1["image_path"], v1["split"], strict=True))
    item = first_item_in(mapping, "train")
    paths = sorted(p for p in mapping if item_of(p) == item)
    v1.loc[v1["image_path"] == paths[0], "split"] = "val"
    # excluded image (manifest row kept) in val, the remaining one in train
    safe_unlink(ds, paths[0])
    write_csv(ds / "exclusions.csv", ["image_path", "reason"], [[paths[0], "person"]])
    df2 = load_manifest(ds)
    with pytest.raises(SplitIntegrityError):
        make_split(df2, seed=42, previous=v1, excluded=load_exclusions(ds))
    # same conflict through the file-name fallback (row removed, no exclusion)
    (ds / "exclusions.csv").unlink()
    write_rows(ds, [r for r in read_rows(ds) if r["image_path"] != paths[0]])
    df3 = load_manifest(ds)
    with pytest.raises(SplitIntegrityError):
        make_split(df3, seed=42, previous=v1)


def test_extra_split_cli_conflict_in_previous_exits_2(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    path = splits / "split_v1.csv"
    v1 = read_split_csv(path)
    item = first_item_in(v1, "train")
    paths = sorted(p for p in v1 if item_of(p) == item)
    lines = path.read_text(encoding="utf-8").split("\n")
    lines = [f"{paths[0]},val" if ln == f"{paths[0]},train" else ln for ln in lines]
    body = "\n".join(lines).encode("utf-8")
    path.write_bytes(body)  # a previous split edited and re-hashed by hand
    (splits / "split_v1.sha256").write_text(
        f"{hashlib.sha256(body).hexdigest()}  split_v1.csv\n", encoding="utf-8"
    )
    exclude_item(ds, item)
    add_image(ds, item, "screw", "good", 0, "20261108T100000Z")
    before = tree_snapshot(splits)
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 2
    assert item in out
    assert tree_snapshot(splits) == before


def test_extra_previous_image_with_foreign_name_is_ignored(ds: Path) -> None:
    df = load_manifest(ds)
    v1 = make_split(df, seed=42).frame
    legacy = pd.DataFrame({"image_path": ["raw/screw/good/legacy-photo.jpg"], "split": ["val"]})
    previous = pd.concat([v1, legacy], ignore_index=True)
    result = make_split(df, seed=42, previous=previous)
    assert "missing_previous_image" in json.dumps(result.warnings)
    assert "raw/screw/good/legacy-photo.jpg" not in set(result.frame["image_path"])


def test_extra_small_stratum_of_new_items_has_scope(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    add_image(ds, "S-150", "screw", "fair", 0, "20261109T100000Z")
    assert split_cli(ds, splits, capsys)[0] == 0
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    small = [w for w in meta["warnings"] if w.get("code") == "small_stratum"]
    assert small and all(w.get("scope") == "new_items" for w in small)
    # the split_v1 rule (CA-14) has no "new_items" scope
    df = fake_frame([("S-001", "screw", ["good"]), ("S-002", "screw", ["good"])])
    first = make_split(df, seed=42).warnings
    assert first and all(w.get("scope") != "new_items" for w in first)


def test_extra_t02_rephoto_after_an_intermediate_split_keeps_test(
    ds: Path, tmp_path: Path, capsys
) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    v1 = read_split_csv(splits / "split_v1.csv")
    item = first_item_in(v1, "test")
    old_rows = exclude_item(ds, item)
    assert split_cli(ds, splits, capsys)[0] == 0  # split_v2: the item left the test set
    new = [
        add_image(ds, item, "screw", old_rows[0]["grade"], 0, "20261110T100000Z"),
        add_image(ds, item, "screw", old_rows[0]["grade"], 1, "20261110T100100Z"),
    ]
    assert split_cli(ds, splits, capsys)[0] == 0
    v3 = read_split_csv(splits / "split_v3.csv")
    assert [v3[p] for p in new] == ["test", "test"]


def test_extra_parts_dataset_train_mode(ds: Path) -> None:
    pytest.importorskip("torch")
    from qc_ml.dataset import PartsDataset

    df = load_manifest(ds).reset_index(drop=True)
    params = PreprocessParams()
    labels = SimpleNamespace(object_types=["screw", "nut", "other"], grades=GRADES)
    dataset = PartsDataset(df, ds, labels, params, train=True, seed=7)
    i = 5
    expected = preprocess(
        train_transform(load_image(ds / df.loc[i, "image_path"]), np.random.default_rng([7, 0, i])),
        params,
    )[0]
    first = dataset[i][0].numpy()
    assert np.array_equal(first, expected)
    assert np.array_equal(dataset[i][0].numpy(), first)  # same epoch, same item -> same tensor
    dataset.set_epoch(1)
    assert not np.array_equal(dataset[i][0].numpy(), first)


# ---- r3: split history (§4.4), exploratory -----------------------------------------------


def _clone_version(splits: Path, src: int, dst: int, edit: Callable[[str], str] | None = None):
    """Write split_v<dst> from split_v<src> (optionally edited), with a matching .sha256."""
    text = (splits / f"split_v{src}.csv").read_text(encoding="utf-8")
    (splits / f"split_v{dst}.csv").write_text(edit(text) if edit else text, encoding="utf-8")
    _write_hash(splits, f"split_v{dst}")
    meta = json.loads((splits / f"split_v{src}.json").read_text(encoding="utf-8"))
    meta["parent"] = f"split_v{dst - 1}"
    (splits / f"split_v{dst}.json").write_text(json.dumps(meta), encoding="utf-8")


def test_extra_history_gap_in_the_middle(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    _clone_version(splits, 1, 2)
    _clone_version(splits, 1, 3)
    safe_unlink(splits, "split_v2.csv")
    add_image(ds, "S-501", "screw", "good", 0, "20261204T100000Z")
    before = tree_snapshot(splits)
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 2
    assert "split history incomplete" in out and "split_v2.csv" in out
    assert tree_snapshot(splits) == before


def test_extra_history_old_version_without_sha256(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    _clone_version(splits, 1, 2)
    safe_unlink(splits, "split_v1.sha256")
    before = tree_snapshot(splits)
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 2
    assert "split_v1" in out
    assert tree_snapshot(splits) == before


def test_extra_history_conflict_is_never_resolved(ds: Path, tmp_path: Path, capsys) -> None:
    """Item in test in v1 and v2, val in v3: the majority (and the newest) are not chosen."""
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    v1 = read_split_csv(splits / "split_v1.csv")
    item = first_item_in(v1, "test")
    _clone_version(splits, 1, 2)

    def to_val(text: str) -> str:
        return "\n".join(
            ln[: -len("test")] + "val" if ln.endswith(",test") and item_of(ln) == item else ln
            for ln in text.split("\n")
        )

    _clone_version(splits, 1, 3, to_val)
    before = tree_snapshot(splits)
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 2
    assert item in out and "split_v3.csv" in out
    assert tree_snapshot(splits) == before


def test_extra_item_history_conflict_inside_one_frame_without_attrs(ds: Path) -> None:
    df = load_manifest(ds)
    frame = make_split(df, seed=42).frame.copy()
    item = item_of(frame.loc[0, "image_path"])
    sibling = frame.index[(frame["image_path"].map(item_of) == item) & (frame.index != 0)][0]
    frame.loc[sibling, "split"] = "test" if frame.loc[0, "split"] != "test" else "train"
    frame.attrs = {}
    with pytest.raises(SplitIntegrityError) as excinfo:
        item_history([frame], df)
    assert item in str(excinfo.value)
    assert "#" in str(excinfo.value)  # position in the list when there is no split_file


def test_extra_item_history_values_and_unresolvable_images(ds: Path) -> None:
    df = load_manifest(ds)
    frame = make_split(df, seed=42).frame
    foreign = pd.DataFrame({"image_path": ["raw/screw/good/legacy-photo.jpg"], "split": ["test"]})
    history = item_history([frame, pd.concat([frame, foreign], ignore_index=True)], df)
    expected = {item_of(p): w for p, w in zip(frame["image_path"], frame["split"], strict=True)}
    assert history == expected
    assert item_history([], df) == {}


def test_extra_history_entry_without_images_is_ignored(ds: Path) -> None:
    df = load_manifest(ds)
    v1 = make_split(df, seed=42).frame
    result = make_split(df, seed=42, previous=v1, history={"S-999": "test"})
    pd.testing.assert_frame_equal(
        result.frame.reset_index(drop=True), v1[["image_path", "split"]].reset_index(drop=True)
    )
    assert make_split(df, seed=42, history={}).frame.shape[0] == 88  # empty history, no previous


@pytest.mark.parametrize("item_id", ["bogus", "S-1", "", "s-001"])
def test_extra_rv06_invalid_excluded_item_id_falls_back_to_the_file_name(
    ds: Path, item_id: str
) -> None:
    df = load_manifest(ds)
    v1 = make_split(df, seed=42).frame
    mapping = dict(zip(v1["image_path"], v1["split"], strict=True))
    item = first_item_in(mapping, "test")
    old = sorted(p for p in mapping if item_of(p) == item)
    rest = df[df["item_id"] != item].copy()
    new = df[df["item_id"] == item].head(1).copy()
    new["image_path"] = [f"{Path(old[0]).parent.as_posix()}/{item}__4__20261205T100000Z.jpg"]
    df2 = pd.concat([rest, new], ignore_index=True)
    df2.attrs["excluded_items"] = dict.fromkeys(old, item_id)
    result = make_split(df2, seed=42, previous=v1, excluded=frozenset(old))
    got = dict(zip(result.frame["image_path"], result.frame["split"], strict=True))
    assert got[new["image_path"].iloc[0]] == "test"


def test_extra_valid_excluded_item_id_wins_over_the_file_name(ds: Path) -> None:
    """Source 2 (excluded manifest row) has precedence over source 3 (file name)."""
    df = load_manifest(ds)
    v1 = make_split(df, seed=42).frame
    mapping = dict(zip(v1["image_path"], v1["split"], strict=True))
    item = first_item_in(mapping, "test")
    old = sorted(p for p in mapping if item_of(p) == item)
    rest = df[df["item_id"] != item].copy()
    new = df[df["item_id"] == item].head(1).copy()
    new["image_path"] = [f"{Path(old[0]).parent.as_posix()}/{item}__4__20261205T110000Z.jpg"]
    df2 = pd.concat([rest, new], ignore_index=True)
    df2.attrs["excluded_items"] = dict.fromkeys(old, "S-098")  # valid id, but another item
    result = make_split(df2, seed=42, previous=v1, excluded=frozenset(old))
    got = dict(zip(result.frame["image_path"], result.frame["split"], strict=True))
    assert got[new["image_path"].iloc[0]] in ("train", "val")  # the item counts as new


def test_extra_rv06_through_the_cli(ds: Path, tmp_path: Path, capsys) -> None:
    """Excluded rows with a broken item_id in the manifest: the file name still finds the item."""
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    v1 = read_split_csv(splits / "split_v1.csv")
    item = first_item_in(v1, "test")
    old_rows = exclude_item(ds, item)
    rows = read_rows(ds)
    for r in rows:
        if r["item_id"] == item:
            r["item_id"] = "X-1"  # excluded rows skip the row checks
    write_rows(ds, rows)
    load_manifest(ds)
    assert split_cli(ds, splits, capsys)[0] == 0
    new = add_image(ds, item, "screw", old_rows[0]["grade"], 0, "20261206T100000Z")
    assert split_cli(ds, splits, capsys)[0] == 0
    assert read_split_csv(splits / "split_v3.csv")[new] == "test"


def test_extra_stray_files_and_leading_zero_are_ignored(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    (splits / "split_v2.sha256").write_text("0" * 64 + "  split_v2.csv\n", encoding="utf-8")
    (splits / "split_v2.json").write_text("{}", encoding="utf-8")
    (splits / "split_v01.csv").write_bytes((splits / "split_v1.csv").read_bytes())
    (splits / "split_v0.csv").write_bytes((splits / "split_v1.csv").read_bytes())
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0, out
    assert "split unchanged: split_v1" in out


def test_extra_unchanged_with_a_longer_history(ds: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert split_cli(ds, splits, capsys)[0] == 0
    add_image(ds, "S-601", "screw", "good", 0, "20261207T100000Z")
    assert split_cli(ds, splits, capsys)[0] == 0
    before = tree_snapshot(splits)
    rc, out = split_cli(ds, splits, capsys)
    assert rc == 0
    assert "split unchanged: split_v2" in out
    assert tree_snapshot(splits) == before
