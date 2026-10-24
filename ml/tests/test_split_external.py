"""Author tests of SPEC-035 section 4.4: external images always in train, integrity, the
``rows_for`` guard and the ceiling of the external fraction. Synthetic data only, no torch."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from qc_ml import split
from qc_ml.data import (
    EXTERNAL_SOURCE_COLUMNS,
    GRADES,
    MANIFEST_COLUMNS,
    SOURCE_COLUMNS,
    is_external_item,
    load_manifest,
)
from qc_ml.errors import SplitError, SplitIntegrityError
from qc_ml.split import item_history, item_strata, load_split, make_split, rows_for
from qc_ml.synthetic import add_synthetic_item, make_synthetic_dataset

SYNTHETIC_SOURCE = [
    "synthetic",
    "Synthetic dataset",
    "https://example.org/synthetic",
    "CC0-1.0",
    "https://creativecommons.org/publicdomain/zero/1.0/",
    "Synthetic test images",
    "2026-10-20",
]


def _template(factory: pytest.TempPathFactory, name: str, **kwargs) -> Path:
    return make_synthetic_dataset(
        factory.mktemp(name) / "ds", items_per_stratum=20, images_per_item=3, **kwargs
    )


@pytest.fixture(scope="module")
def _ext1(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _template(tmp_path_factory, "ext1", external_items_per_stratum=1)


@pytest.fixture(scope="module")
def _ext2(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _template(tmp_path_factory, "ext2", external_items_per_stratum=2)


@pytest.fixture
def ext1(_ext1: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(_ext1, tmp_path / "ds"))


def _load(root: Path) -> pd.DataFrame:
    return load_manifest(root, external_sources=root / "external_sources.csv")


def _cli(root: Path, splits: Path, *extra: str) -> int:
    args = ["--dataset-dir", str(root), "--splits-dir", str(splits)]
    return split.main([*args, "--external-sources", str(root / "external_sources.csv"), *extra])


def _snapshot(directory: Path) -> dict[str, bytes]:
    if not directory.exists():
        return {}
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


def _external_mask(df: pd.DataFrame) -> pd.Series:
    return df["item_id"].map(is_external_item).astype(bool)


def _edit_split(path: Path, image_path: str, new_split: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    lines = [f"{image_path},{new_split}" if ln.startswith(image_path + ",") else ln for ln in lines]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")


# ---------- CA-07 ----------


def test_ca07_externals_in_train_and_own_split_unchanged(_ext2: Path) -> None:
    df = _load(_ext2)
    external = _external_mask(df)
    assert external.sum() == 22
    result = make_split(df, seed=42)
    mapping = dict(zip(result.frame["image_path"], result.frame["split"], strict=True))
    assert {mapping[p] for p in df.loc[external, "image_path"]} == {"train"}
    own = make_split(df[~external], seed=42)
    own_map = dict(zip(own.frame["image_path"], own.frame["split"], strict=True))
    assert own_map == {p: s for p, s in mapping.items() if p in own_map}
    strata = item_strata(df[~external])
    items = dict(zip(df["image_path"], df["item_id"], strict=True))
    for stratum in set(strata.values()):
        members = {i for i, s in strata.items() if s == stratum}
        counts = {name: set() for name in ("train", "val", "test")}
        for image_path, name in mapping.items():
            if items[image_path] in members:
                counts[name].add(items[image_path])
        assert tuple(len(counts[n]) for n in ("train", "val", "test")) == (14, 3, 3), stratum
    assert result.warnings == own.warnings == []


def test_small_stratum_counts_only_own_items(tmp_path: Path) -> None:
    root = make_synthetic_dataset(
        tmp_path / "ds", items_per_stratum=2, images_per_item=1, external_items_per_stratum=3
    )
    result = make_split(_load(root), seed=1, max_external_fraction=1.0)
    small = [w for w in result.warnings if w["code"] == "small_stratum"]
    assert len(small) == 11 and {w["n_items"] for w in small} == {2}


# ---------- CA-08 ----------


def _append_external(root: Path, item_id: str, object_type: str, grade: str | None) -> None:
    paths = add_synthetic_item(root, item_id, object_type, grade, n_images=1, seed=7)
    digest = hashlib.sha256((root / paths[0]).read_bytes()).hexdigest()
    sources = root / "sources.csv"
    new = not sources.exists()
    with sources.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        if new:
            writer.writerow(SOURCE_COLUMNS)
        writer.writerow([paths[0], "external", "", "synthetic", f"synthetic/{item_id}.png", digest])


def test_ca08_new_externals_go_to_train(large_dataset: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    assert _cli(large_dataset, splits) == 0
    v1_frame = load_split(splits / "split_v1.csv")
    v1 = dict(zip(v1_frame["image_path"], v1_frame["split"], strict=True))
    with (large_dataset / "external_sources.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(EXTERNAL_SOURCE_COLUMNS)
        writer.writerow(SYNTHETIC_SOURCE)
    numbers = {"S": 0, "N": 0, "O": 0}
    strata = [(t, g) for t in ("screw", "nut") for g in GRADES] + [("other", None)]
    for object_type, grade in strata:
        letter = {"screw": "S", "nut": "N", "other": "O"}[object_type]
        numbers[letter] += 1
        _append_external(large_dataset, f"X{letter}-{numbers[letter]:04d}", object_type, grade)
    assert _cli(large_dataset, splits) == 0
    v2_frame = load_split(splits / "split_v2.csv")
    v2 = dict(zip(v2_frame["image_path"], v2_frame["split"], strict=True))
    assert all(v2[p] == s for p, s in v1.items())
    new = set(v2) - set(v1)
    assert len(new) == 11 and {v2[p] for p in new} == {"train"}
    meta = json.loads((splits / "split_v2.json").read_text(encoding="utf-8"))
    assert meta["counts"]["n_external_images"] == {"train": 11, "val": 0, "test": 0}
    assert meta["max_external_fraction"] == 0.3
    assert meta["external_fraction_train"] == 11 / meta["counts"]["images"]["train"]


# ---------- CA-09 ----------


def _external_image(df: pd.DataFrame, item_id: str = "XS-0001") -> str:
    return str(df.loc[df["item_id"] == item_id, "image_path"].iloc[0])


def test_ca09a_cli_refuses_external_in_test(ext1: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert _cli(ext1, splits) == 0
    df = _load(ext1)
    _edit_split(splits / "split_v1.csv", _external_image(df), "test")
    add_synthetic_item(ext1, "S-900", "screw", "fair", n_images=2)
    before = _snapshot(splits)
    capsys.readouterr()
    assert _cli(ext1, splits) == 2
    assert "XS-0001" in capsys.readouterr().err
    assert _snapshot(splits) == before


def test_ca09b_c_make_split_and_rows_for(ext1: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    assert _cli(ext1, splits) == 0
    df = _load(ext1)
    original = load_split(splits / "split_v1.csv")
    image = _external_image(df)
    for name in ("test", "val"):
        edited = original.copy()
        edited.loc[edited["image_path"] == image, "split"] = name
        with pytest.raises(SplitIntegrityError, match="XS-0001"):
            make_split(df, seed=42, previous=edited)
        with pytest.raises(SplitIntegrityError, match=f"external image in {name}: XS-0001"):
            rows_for(df, edited, name)
    train = rows_for(df, original, "train")
    assert _external_mask(train).sum() == 11
    assert _external_mask(rows_for(df, original, "val")).sum() == 0
    assert _external_mask(rows_for(df, original, "test")).sum() == 0


def test_ca09_history_and_item_history(ext1: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    assert _cli(ext1, splits) == 0
    df = _load(ext1)
    original = load_split(splits / "split_v1.csv")
    with pytest.raises(SplitIntegrityError, match="XS-0001"):
        make_split(df, seed=42, previous=original, history={"XS-0001": "val"})
    # history of an external item that is no longer in df is checked too
    with pytest.raises(SplitIntegrityError, match="XN-0099"):
        make_split(df, seed=42, previous=original, history={"XN-0099": "test"})
    edited = original.copy()
    edited.loc[edited["image_path"] == _external_image(df), "split"] = "test"
    edited.attrs["split_file"] = "split_v1.csv"
    with pytest.raises(SplitIntegrityError, match="external item XS-0001 is in test in split_v1"):
        item_history([edited], df)
    assert item_history([original], df)["XS-0001"] == "train"
    # with a consistent history the externals stay in train and nothing moves
    result = make_split(df, seed=42, previous=original, history=item_history([original], df))
    assert split._same_split(result.frame, original)


def test_external_of_previous_resolved_by_file_name(ext1: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    assert _cli(ext1, splits) == 0
    df = _load(ext1)
    previous = load_split(splits / "split_v1.csv")
    ghost = "raw/screw/perfect/XS-0777__0__20261022T150000Z.jpg"
    previous = pd.concat(
        [previous, pd.DataFrame({"image_path": [ghost], "split": ["val"]})], ignore_index=True
    )
    with pytest.raises(SplitIntegrityError, match="XS-0777"):
        make_split(df, seed=42, previous=previous)


# ---------- CA-10: ceiling ----------


@pytest.fixture(scope="module")
def _ext18(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _template(tmp_path_factory, "ext18", external_items_per_stratum=18)


@pytest.fixture(scope="module")
def _ext19(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _template(tmp_path_factory, "ext19", external_items_per_stratum=19)


def test_ca10_ceiling_is_accepted(_ext18: Path, tmp_path: Path) -> None:
    splits = tmp_path / "splits"
    assert _cli(_ext18, splits) == 0
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["max_external_fraction"] == 0.3
    assert meta["external_fraction_train"] == 0.3
    assert meta["counts"]["n_external_images"]["train"] == 198
    assert meta["counts"]["images"]["train"] == 660


def test_ca10_above_ceiling(_ext19: Path, tmp_path: Path, capsys) -> None:
    splits = tmp_path / "splits"
    assert _cli(_ext19, splits) == 2
    err = capsys.readouterr().err
    assert "external fraction in train 209/671 above 0.3" in err
    assert not splits.exists() or _snapshot(splits) == {}
    with pytest.raises(SplitError, match="209/671"):
        make_split(_load(_ext19), seed=42)
    assert _cli(_ext19, splits, "--max-external-fraction", "0.35") == 0
    meta = json.loads((splits / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["max_external_fraction"] == 0.35
    assert meta["external_fraction_train"] == pytest.approx(209 / 671, abs=1e-12)


@pytest.mark.parametrize("value", ["0", "1.5", "abc", "-0.1", "nan", "inf", ""])
def test_ca10_invalid_ceiling_argument(dataset: Path, tmp_path: Path, value: str) -> None:
    splits = tmp_path / "splits"
    assert _cli(dataset, splits, "--max-external-fraction", value) == 2
    assert _snapshot(splits) == {}


def test_ceiling_argument_accepts_one(dataset: Path, tmp_path: Path) -> None:
    assert _cli(dataset, tmp_path / "s", "--max-external-fraction", "1") == 0
    meta = json.loads((tmp_path / "s" / "split_v1.json").read_text(encoding="utf-8"))
    assert meta["max_external_fraction"] == 1.0
    assert meta["external_fraction_train"] == 0.0
    assert meta["counts"]["n_external_images"] == {"train": 0, "val": 0, "test": 0}


@pytest.mark.parametrize("value", [0, -0.1, 1.0000001, float("nan"), True, "0.3"])
def test_make_split_rejects_invalid_ceiling(value, _ext18: Path) -> None:
    with pytest.raises(ValueError, match="max_external_fraction"):
        make_split(_load(_ext18).head(4), max_external_fraction=value)


def test_ceiling_comparison_is_exact() -> None:
    # 3 external images and 7 own items in one stratum (1 test, 1 val, 5 train): 3/8 in train.
    # 0.375 is the exact ceiling (accepted); 0.374 and the default 0.3 are below it.
    rows = []
    for k in range(3):
        rows.append(
            (f"raw/screw/perfect/XS-{k + 1:04d}.jpg", f"XS-{k + 1:04d}", "screw", "perfect")
        )
    for k in range(7):
        rows.append((f"raw/screw/perfect/S-{k + 1:03d}.jpg", f"S-{k + 1:03d}", "screw", "perfect"))
    df = pd.DataFrame(rows, columns=["image_path", "item_id", "object_type", "grade"])
    with pytest.raises(SplitError, match="3/8 above 0.3"):
        make_split(df, seed=0)
    assert make_split(df, seed=0, max_external_fraction=0.375).frame is not None
    with pytest.raises(SplitError, match="3/8 above 0.374"):
        make_split(df, seed=0, max_external_fraction=0.374)


def test_no_train_images_no_ceiling() -> None:
    df = pd.DataFrame(columns=list(MANIFEST_COLUMNS))
    assert make_split(df, seed=0).frame.empty
