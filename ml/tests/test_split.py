"""Author tests for qc_ml.split: grouping, strata, rounding, freezing and files (SPEC-011 §4.4)."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from qc_ml import split
from qc_ml.data import load_manifest
from qc_ml.errors import SplitError, SplitIntegrityError
from qc_ml.split import (
    item_history,
    item_id_resolver,
    item_strata,
    load_split,
    make_split,
    round_half_up,
    rows_for,
    split_csv_bytes,
)
from qc_ml.synthetic import add_synthetic_item


def _items_by_split(df: pd.DataFrame, frame: pd.DataFrame) -> dict[str, set[str]]:
    items = dict(zip(df["image_path"], df["item_id"], strict=True))
    out: dict[str, set[str]] = {"train": set(), "val": set(), "test": set()}
    for image_path, name in zip(frame["image_path"], frame["split"], strict=True):
        out[name].add(items[image_path])
    return out


def _run(dataset: Path, splits_dir: Path, *extra: str) -> int:
    return split.main(["--dataset-dir", str(dataset), "--splits-dir", str(splits_dir), *extra])


def _split_map(path: Path) -> dict[str, str]:
    frame = load_split(path)
    return dict(zip(frame["image_path"], frame["split"], strict=True))


# ---------- rounding ----------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.5, 1), (1.5, 2), (2.5, 3), (0.45, 0), (0.6, 1), (Decimal("4.5"), 5), (0, 0)],
)
def test_round_half_up(value, expected) -> None:
    assert round_half_up(value) == expected


# ---------- allocation ----------


def test_items_never_cross_splits(large_dataset: Path) -> None:
    df = load_manifest(large_dataset)
    result = make_split(df, seed=42)
    by_split = _items_by_split(df, result.frame)
    assert not by_split["train"] & by_split["val"]
    assert not by_split["train"] & by_split["test"]
    assert not by_split["val"] & by_split["test"]
    merged = df.merge(result.frame, on="image_path")
    assert (merged.groupby("item_id")["split"].nunique() == 1).all()
    assert len(result.frame) == len(df)


def test_each_stratum_has_14_3_3(large_dataset: Path) -> None:
    df = load_manifest(large_dataset)
    result = make_split(df, seed=42)
    strata = item_strata(df)
    by_split = _items_by_split(df, result.frame)
    for stratum in set(strata.values()):
        members = {i for i, s in strata.items() if s == stratum}
        counts = tuple(len(members & by_split[n]) for n in ("train", "val", "test"))
        assert counts == (14, 3, 3), stratum
    assert result.warnings == []


def test_small_stratum_goes_to_train(dataset: Path) -> None:
    df = load_manifest(dataset)
    df = df[~df["item_id"].isin(["O-003", "O-004"])]  # other/none keeps 2 items
    result = make_split(df, seed=42)
    by_split = _items_by_split(df, result.frame)
    assert {"O-001", "O-002"} <= by_split["train"]
    assert {"code": "small_stratum", "stratum": "other/none", "n_items": 2} in result.warnings


def test_three_items_get_one_each(dataset: Path) -> None:
    df = load_manifest(dataset)
    df = df[df["item_id"] != "O-004"]
    by_split = _items_by_split(df, make_split(df, seed=1).frame)
    others = [{i for i in s if i.startswith("O-")} for s in by_split.values()]
    assert [len(s) for s in others] == [1, 1, 1]


def test_dominant_grade_defines_the_stratum(dataset: Path) -> None:
    df = load_manifest(dataset)
    rows = df[df["item_id"] == "S-001"].index
    df.loc[rows[0], "grade"] = "poor"  # perfect + poor -> tie -> poor
    assert item_strata(df)["S-001"] == ("screw", "poor")
    assert item_strata(df)["O-001"] == ("other", "none")


def test_same_seed_same_split_other_seed_differs(large_dataset: Path) -> None:
    df = load_manifest(large_dataset)
    a = make_split(df, seed=42).frame
    b = make_split(df, seed=42).frame
    c = make_split(df, seed=7).frame
    assert a.equals(b)
    assert not a.equals(c)


def test_invalid_ratios(dataset: Path) -> None:
    df = load_manifest(dataset)
    with pytest.raises(SplitError):
        make_split(df, ratios=(0.7, 0.2, 0.2))
    with pytest.raises(SplitError):
        make_split(df, ratios=(1.0, 0.0, 0.0))


# ---------- CLI and files ----------


def test_cli_files_are_reproducible(dataset: Path, tmp_path: Path, capsys) -> None:
    assert _run(dataset, tmp_path / "a") == 0
    assert _run(dataset, tmp_path / "b") == 0
    a = (tmp_path / "a/split_v1.csv").read_bytes()
    assert a == (tmp_path / "b/split_v1.csv").read_bytes()
    digest = hashlib.sha256(a).hexdigest()
    assert (tmp_path / "a/split_v1.sha256").read_text() == f"{digest}  split_v1.csv\n"
    lines = a.decode().split("\n")
    assert lines[0] == "image_path,split" and lines[-1] == ""
    assert lines[1:-1] == sorted(lines[1:-1])
    assert b"\r" not in a
    meta = json.loads((tmp_path / "a/split_v1.json").read_text())
    assert meta["seed"] == 42 and meta["ratios"] == [0.7, 0.15, 0.15] and meta["parent"] is None
    assert (
        meta["manifest_sha256"]
        == hashlib.sha256((dataset / "manifest.csv").read_bytes()).hexdigest()
    )
    assert sum(meta["counts"]["images"].values()) == 88
    assert sum(meta["counts"]["items"].values()) == 44
    assert meta["warnings"] == []
    assert _run(dataset, tmp_path / "c", "--seed", "7") == 0
    assert _split_map(tmp_path / "c/split_v1.csv") != _split_map(tmp_path / "a/split_v1.csv")


def test_freeze_with_new_items_and_new_images(dataset: Path, tmp_path: Path) -> None:
    splits_dir = tmp_path / "splits"
    assert _run(dataset, splits_dir) == 0
    v1 = _split_map(splits_dir / "split_v1.csv")
    df = load_manifest(dataset)
    items = dict(zip(df["image_path"], df["item_id"], strict=True))
    test_item = sorted(items[p] for p, s in v1.items() if s == "test" and "/screw/" in p)[0]
    new_paths = []
    for k in range(5):
        new_paths += add_synthetic_item(dataset, f"S-{101 + k}", "screw", "fair", seed=k)
    extra = add_synthetic_item(dataset, test_item, "screw", "poor", seed=9)

    assert _run(dataset, splits_dir) == 0
    v2 = _split_map(splits_dir / "split_v2.csv")
    assert all(v2[p] == s for p, s in v1.items())
    assert {v2[p] for p in new_paths} <= {"train", "val"}
    assert "val" in {v2[p] for p in new_paths}  # 5 items -> round_half_up(5 * 15/85) = 1
    assert {p for p, s in v2.items() if s == "test"} == {
        p for p, s in v1.items() if s == "test"
    } | set(extra)
    meta = json.loads((splits_dir / "split_v2.json").read_text())
    assert meta["parent"] == "split_v1"


def test_unchanged_writes_nothing(dataset: Path, tmp_path: Path, capsys) -> None:
    splits_dir = tmp_path / "splits"
    assert _run(dataset, splits_dir) == 0
    capsys.readouterr()
    assert _run(dataset, splits_dir) == 0
    assert "split unchanged: split_v1" in capsys.readouterr().out
    assert not (splits_dir / "split_v2.csv").exists()


def test_missing_test_image_is_an_error(dataset: Path, tmp_path: Path, rows_io, capsys) -> None:
    read_rows, write_rows, _ = rows_io
    splits_dir = tmp_path / "splits"
    assert _run(dataset, splits_dir) == 0
    victim = next(p for p, s in _split_map(splits_dir / "split_v1.csv").items() if s == "test")
    write_rows(dataset, [r for r in read_rows(dataset) if r["image_path"] != victim])
    (dataset / victim).unlink()
    capsys.readouterr()
    assert _run(dataset, splits_dir) == 2
    assert victim in capsys.readouterr().err
    assert sorted(p.name for p in splits_dir.iterdir()) == [
        "split_v1.csv",
        "split_v1.json",
        "split_v1.sha256",
    ]


def test_missing_train_image_is_a_warning(dataset: Path, tmp_path: Path) -> None:
    df = load_manifest(dataset)
    first = make_split(df, seed=42).frame
    victim = first[first["split"] == "train"]["image_path"].iloc[0]
    result = make_split(df[df["image_path"] != victim], seed=42, previous=first)
    assert {"code": "missing_previous_image", "image_path": victim, "split": "train"} in (
        result.warnings
    )
    kept = first[first["image_path"] != victim].reset_index(drop=True)
    assert result.frame.equals(kept)


def test_excluded_test_image_leaves_the_split(dataset: Path, tmp_path: Path, rows_io) -> None:
    _, _, write_csv = rows_io
    splits_dir = tmp_path / "splits"
    assert _run(dataset, splits_dir) == 0
    v1 = _split_map(splits_dir / "split_v1.csv")
    victim = next(p for p, s in v1.items() if s == "test")
    (dataset / victim).unlink()
    write_csv(dataset / "exclusions.csv", ["image_path", "reason"], [[victim, "person"]])
    assert _run(dataset, splits_dir) == 0
    v2 = _split_map(splits_dir / "split_v2.csv")
    assert victim not in v2
    assert v2 == {p: s for p, s in v1.items() if p != victim}
    meta = json.loads((splits_dir / "split_v2.json").read_text())
    assert {"code": "excluded_previous_image", "image_path": victim, "split": "test"} in (
        meta["warnings"]
    )


def test_previous_with_item_in_two_splits(dataset: Path) -> None:
    df = load_manifest(dataset)
    frame = make_split(df, seed=42).frame.copy()
    paths = df[df["item_id"] == "S-001"]["image_path"].tolist()
    frame.loc[frame["image_path"] == paths[0], "split"] = "train"
    frame.loc[frame["image_path"] == paths[1], "split"] = "test"
    with pytest.raises(SplitIntegrityError):
        make_split(df, previous=frame)


# ---------- load_split / rows_for ----------


def test_load_split_detects_edits(dataset: Path, tmp_path: Path) -> None:
    splits_dir = tmp_path / "splits"
    assert _run(dataset, splits_dir) == 0
    path = splits_dir / "split_v1.csv"
    frame = load_split(path)
    assert frame.attrs["split_file"] == "split_v1.csv"
    text = path.read_text()
    path.write_text(text.replace(",test\n", ",train\n", 1))
    with pytest.raises(SplitError, match="sha256"):
        load_split(path)
    (splits_dir / "split_v1.sha256").unlink()
    with pytest.raises(SplitError):
        load_split(path)


def test_rows_for(dataset: Path) -> None:
    df = load_manifest(dataset)
    frame = make_split(df, seed=42).frame
    parts = {w: rows_for(df, frame, w) for w in ("train", "val", "test")}
    assert sum(len(p) for p in parts.values()) == 88
    assert list(parts["train"].columns) == list(df.columns)
    with pytest.raises(SplitError, match="split outdated"):
        rows_for(df, frame.iloc[1:], "train")
    with pytest.raises(ValueError):
        rows_for(df, frame, "all")  # type: ignore[arg-type]
    broken = frame.copy()
    first_item = df[df["item_id"] == "S-001"]["image_path"].tolist()
    broken.loc[broken["image_path"] == first_item[0], "split"] = "train"
    broken.loc[broken["image_path"] == first_item[1], "split"] = "test"
    with pytest.raises(SplitIntegrityError):
        rows_for(df, broken, "train")


def test_split_csv_bytes_quotes_when_needed() -> None:
    frame = pd.DataFrame({"image_path": ["b,c.jpg", "a.jpg"], "split": ["val", "train"]})
    assert split_csv_bytes(frame) == b'image_path,split\na.jpg,train\n"b,c.jpg",val\n'


def test_cli_with_invalid_manifest(dataset: Path, tmp_path: Path) -> None:
    (dataset / "manifest.csv").write_text("nothing\n", encoding="utf-8")
    assert _run(dataset, tmp_path / "s") == 2
    assert not (tmp_path / "s").exists()


# ---------- items re-photographed after all their images left (RV-01 of the r1 review) ----------


def _item_in(v1: dict[str, str], df: pd.DataFrame, which: str, kind: str) -> str:
    items = dict(zip(df["image_path"], df["item_id"], strict=True))
    return sorted(items[p] for p, s in v1.items() if s == which and f"/{kind}/" in p)[0]


def _rows_of(read_rows, dataset: Path, item_id: str) -> list[dict[str, str]]:
    return [r for r in read_rows(dataset) if r["item_id"] == item_id]


def test_rephotographed_items_keep_their_split(dataset: Path, tmp_path: Path, rows_io) -> None:
    read_rows, _, write_csv = rows_io
    splits_dir = tmp_path / "splits"
    assert _run(dataset, splits_dir) == 0
    v1 = _split_map(splits_dir / "split_v1.csv")
    df = load_manifest(dataset)
    test_item = _item_in(v1, df, "test", "screw")
    val_item = _item_in(v1, df, "val", "nut")
    old = _rows_of(read_rows, dataset, test_item) + _rows_of(read_rows, dataset, val_item)
    for row in old:
        (dataset / row["image_path"]).unlink()
    write_csv(
        dataset / "exclusions.csv",
        ["image_path", "reason"],
        [[r["image_path"], "person"] for r in old],
    )
    assert load_manifest(dataset).attrs["excluded_items"] == {
        r["image_path"]: r["item_id"] for r in old
    }
    new_test = add_synthetic_item(dataset, test_item, "screw", old[0]["grade"], seed=3)
    new_val = add_synthetic_item(dataset, val_item, "nut", old[-1]["grade"], seed=4)

    assert _run(dataset, splits_dir) == 0
    v2 = _split_map(splits_dir / "split_v2.csv")
    assert [v2[p] for p in new_test] == ["test", "test"]
    assert [v2[p] for p in new_val] == ["val", "val"]
    assert all(r["image_path"] not in v2 for r in old)
    assert {p: s for p, s in v2.items() if p in v1} == {
        p: s for p, s in v1.items() if p not in {r["image_path"] for r in old}
    }


def test_removed_without_exclusion_uses_the_file_name(dataset: Path) -> None:
    df = load_manifest(dataset)
    first = make_split(df, seed=42).frame
    v1 = dict(zip(first["image_path"], first["split"], strict=True))
    item = _item_in(v1, df, "val", "screw")
    paths = df[df["item_id"] == item]["image_path"].tolist()
    renamed = df.copy()
    # The old rows leave the manifest (no exclusion); new photos of the item arrive.
    renamed.loc[renamed["item_id"] == item, "image_path"] = [p + ".new.jpg" for p in paths]
    result = make_split(renamed, seed=42, previous=first)
    new = dict(zip(result.frame["image_path"], result.frame["split"], strict=True))
    assert [new[p + ".new.jpg"] for p in paths] == ["val", "val"]
    codes = [w["code"] for w in result.warnings]
    assert codes == ["missing_previous_image", "missing_previous_image"]


def test_excluded_images_without_attrs_use_the_rows_of_df(dataset: Path) -> None:
    df = load_manifest(dataset)
    first = make_split(df, seed=42).frame
    v1 = dict(zip(first["image_path"], first["split"], strict=True))
    item = _item_in(v1, df, "test", "nut")
    old = df[df["item_id"] == item]
    added = old.assign(image_path=[f"raw/x/{item}-{k}.jpg" for k in range(len(old))])
    bare = pd.concat([df, added], ignore_index=True)  # no attrs: rows of df are the source
    bare.attrs = {}
    result = make_split(bare, seed=42, previous=first, excluded=frozenset(old["image_path"]))
    new = dict(zip(result.frame["image_path"], result.frame["split"], strict=True))
    assert {new[p] for p in added["image_path"]} == {"test"}


def test_old_images_of_an_item_in_two_splits_is_an_integrity_error(dataset: Path) -> None:
    df = load_manifest(dataset)
    first = make_split(df, seed=42).frame.copy()
    paths = df[df["item_id"] == "S-001"]["image_path"].tolist()
    first.loc[first["image_path"] == paths[0], "split"] = "train"
    first.loc[first["image_path"] == paths[1], "split"] = "val"
    kept = df[df["image_path"] != paths[0]]
    kept.attrs = {"excluded_items": {paths[0]: "S-001"}}
    with pytest.raises(SplitIntegrityError):
        make_split(kept, seed=42, previous=first, excluded=frozenset({paths[0]}))


def test_small_stratum_of_new_items_has_a_scope(dataset: Path) -> None:
    df = load_manifest(dataset)
    first = make_split(df, seed=42).frame
    grown = pd.concat(
        [df, df[df["item_id"] == "S-001"].assign(item_id="S-201", image_path=["a.jpg", "b.jpg"])],
        ignore_index=True,
    )
    result = make_split(grown, seed=42, previous=first)
    assert result.warnings == [
        {"code": "small_stratum", "stratum": "screw/perfect", "n_items": 1, "scope": "new_items"}
    ]


# ---------- split history (SPEC-011 §4.4, r3) ----------


def _frame(rows: list[tuple[str, str]], name: str | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(
        {"image_path": [r[0] for r in rows], "split": [r[1] for r in rows]}, dtype=object
    )
    if name is not None:
        frame.attrs["split_file"] = name
    return frame


def _df(rows: list[tuple[str, str]], excluded_items: dict | None = None) -> pd.DataFrame:
    df = pd.DataFrame({"image_path": [r[0] for r in rows], "item_id": [r[1] for r in rows]})
    if excluded_items is not None:
        df.attrs["excluded_items"] = excluded_items
    return df


SPEC010 = "raw/screw/good/S-007__0__20261022T140000Z.jpg"


def test_resolver_sources_and_precedence() -> None:
    df = _df(
        [("raw/a.jpg", "S-001"), (SPEC010, "N-002")],
        excluded_items={
            "raw/a.jpg": "S-009",  # source 1 wins over source 2
            "raw/b.jpg": "N-003",
            "raw/screw/good/S-008__1__20261022T140000Z.jpg": "N-004",  # 2 wins over 3
            "raw/screw/good/S-005__1__20261022T140000Z.jpg": "X-1",  # invalid -> source 3
            "raw/c.jpg": "bad",  # invalid, no file-name match -> None
        },
    )
    resolve = item_id_resolver(df)
    assert resolve("raw/a.jpg") == "S-001"
    assert resolve(SPEC010) == "N-002"  # source 1 wins over the file name
    assert resolve("raw/b.jpg") == "N-003"
    assert resolve("raw/screw/good/S-008__1__20261022T140000Z.jpg") == "N-004"
    assert resolve("raw/screw/good/S-005__1__20261022T140000Z.jpg") == "S-005"
    assert resolve("raw/c.jpg") is None
    assert resolve("raw/other/_/O-001__9__20261022T140000Z.jpg") is None  # angle 9
    assert resolve("raw/other/_/O-001__0__20261022T140000Z.JPG") is None  # SPEC-010 is .jpg
    assert item_id_resolver(_df([]))("raw/x/T-010__4__20261022T140000Z.jpg") == "T-010"


def test_item_history_one_and_three_versions() -> None:
    df = _df([("raw/a.jpg", "S-001"), ("raw/b.jpg", "S-002")])
    v1 = _frame([("raw/a.jpg", "test"), (SPEC010, "val")], "split_v1.csv")
    assert item_history([v1], df) == {"S-001": "test", "S-007": "val"}
    v2 = _frame([("raw/a.jpg", "test")], "split_v2.csv")  # S-007 left the split
    v3 = _frame([("raw/a.jpg", "test"), ("raw/b.jpg", "train")], "split_v3.csv")
    assert item_history([v1, v2, v3], df) == {"S-001": "test", "S-007": "val", "S-002": "train"}
    assert item_history([], df) == {}


def test_item_history_conflicts_are_never_resolved() -> None:
    df = _df([("raw/a.jpg", "S-001"), ("raw/b.jpg", "S-001")])
    inside = _frame([("raw/a.jpg", "test"), ("raw/b.jpg", "train")], "split_v1.csv")
    with pytest.raises(SplitIntegrityError, match="S-001") as info:
        item_history([inside], df)
    assert "split_v1.csv" in str(info.value)
    v1 = _frame([("raw/a.jpg", "test")], "split_v1.csv")
    v2 = _frame([("raw/a.jpg", "test"), ("raw/b.jpg", "val")], "split_v2.csv")
    with pytest.raises(SplitIntegrityError) as info:
        item_history([v1, v2], df)
    message = str(info.value)
    assert "S-001" in message and "split_v1.csv" in message and "split_v2.csv" in message
    with pytest.raises(SplitIntegrityError) as info:
        item_history([_frame([("raw/a.jpg", "test")]), _frame([("raw/b.jpg", "val")])], df)
    assert "#0" in str(info.value) and "#1" in str(info.value)


def _history_case(large_dataset: Path) -> tuple[pd.DataFrame, pd.DataFrame, str, str, list[str]]:
    df = load_manifest(large_dataset)
    v1 = make_split(df, seed=42).frame
    items = dict(zip(df["image_path"], df["item_id"], strict=True))
    pairs = zip(v1["image_path"], v1["split"], strict=True)
    tests = sorted({items[p] for p, s in pairs if s == "test"})
    p_item, q_item = tests[0], tests[1]
    e = list(df[df["item_id"] == p_item]["image_path"])
    v2 = make_split(df[~df["image_path"].isin(e)], seed=42, previous=v1, excluded=frozenset(e))
    rows = df[df["item_id"] == p_item].iloc[:2]
    new = rows.assign(image_path=["raw/new/p-1.jpg", "raw/new/p-2.jpg"])
    df3 = pd.concat([df[~df["image_path"].isin(e)], new], ignore_index=True)
    return df3, v2.frame, p_item, q_item, list(new["image_path"])


def test_make_split_with_history(large_dataset: Path) -> None:
    df3, v2, p_item, q_item, new = _history_case(large_dataset)
    result = make_split(df3, seed=42, previous=v2, history={p_item: "test"})
    got = dict(zip(result.frame["image_path"], result.frame["split"], strict=True))
    assert [got[p] for p in new] == ["test", "test"]
    assert all(got[p] == s for p, s in zip(v2["image_path"], v2["split"], strict=True))
    # Without history the item would be new (v2 has none of its images): train/val only.
    plain = make_split(df3, seed=42, previous=v2)
    plain_map = dict(zip(plain.frame["image_path"], plain.frame["split"], strict=True))
    assert {plain_map[p] for p in new} <= {"train", "val"}
    # History entries without images in df are ignored; history never adds warnings.
    extra = make_split(df3, seed=42, previous=v2, history={p_item: "test", "S-999": "val"})
    assert extra.frame.equals(result.frame) and extra.warnings == result.warnings


def test_make_split_history_validation(large_dataset: Path) -> None:
    df3, v2, p_item, q_item, _ = _history_case(large_dataset)
    with pytest.raises(SplitIntegrityError, match=q_item):
        make_split(df3, seed=42, previous=v2, history={p_item: "test", q_item: "train"})
    with pytest.raises(SplitError):
        make_split(df3, seed=42, previous=v2, history={p_item: "holdout"})
    with pytest.raises(SplitError):
        make_split(df3, seed=42, history={p_item: "test"})
    assert make_split(df3, seed=42, history={}).frame.equals(make_split(df3, seed=42).frame)


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


def test_cli_rephoto_after_an_intermediate_split(
    large_dataset: Path, tmp_path: Path, rows_io
) -> None:
    read_rows, _, write_csv = rows_io
    splits_dir = tmp_path / "splits"
    assert _run(large_dataset, splits_dir) == 0
    v1 = _split_map(splits_dir / "split_v1.csv")
    df = load_manifest(large_dataset)
    p_t = _item_in(v1, df, "test", "screw")
    p_v = _item_in(v1, df, "val", "nut")
    old = _rows_of(read_rows, large_dataset, p_t) + _rows_of(read_rows, large_dataset, p_v)
    for row in old:
        (large_dataset / row["image_path"]).unlink()
    write_csv(
        large_dataset / "exclusions.csv",
        ["image_path", "reason"],
        [[r["image_path"], "person"] for r in old],
    )
    assert _run(large_dataset, splits_dir) == 0  # split_v2 without P_t and P_v
    v2 = _split_map(splits_dir / "split_v2.csv")
    new_t = add_synthetic_item(large_dataset, p_t, "screw", old[0]["grade"], seed=5)
    new_v = add_synthetic_item(large_dataset, p_v, "nut", old[-1]["grade"], seed=6)
    assert _run(large_dataset, splits_dir) == 0
    v3 = _split_map(splits_dir / "split_v3.csv")
    assert [v3[p] for p in new_t] == ["test", "test"]
    assert [v3[p] for p in new_v] == ["val", "val"]
    assert all(v3[p] == s for p, s in v2.items())
    items = {r["image_path"]: r["item_id"] for r in read_rows(large_dataset)}
    assert {items[p] for p, s in v3.items() if s == "test"} == {
        items[p] for p, s in v1.items() if s == "test"
    }


def _two_versions(dataset: Path, splits_dir: Path) -> None:
    assert _run(dataset, splits_dir) == 0
    for k in range(5):
        add_synthetic_item(dataset, f"S-{101 + k}", "screw", "fair", seed=k)
    assert _run(dataset, splits_dir) == 0
    add_synthetic_item(dataset, "S-120", "screw", "fair", seed=20)  # something to write


@pytest.mark.parametrize("gone", [1, 2])
def test_cli_gap_in_the_history(dataset: Path, tmp_path: Path, capsys, gone: int) -> None:
    splits_dir = tmp_path / "splits"
    _two_versions(dataset, splits_dir)
    if gone == 2:  # a gap in the middle: v1, v3 present, v2 missing
        (splits_dir / "split_v2.csv").rename(splits_dir / "split_v3.csv")
        (splits_dir / "split_v2.sha256").unlink()
    else:
        (splits_dir / "split_v1.csv").unlink()  # .sha256 and .json stay
    before = _snapshot(splits_dir)
    capsys.readouterr()
    assert _run(dataset, splits_dir) == 2
    err = capsys.readouterr().err
    assert "split history incomplete" in err and f"split_v{gone}.csv" in err
    assert _snapshot(splits_dir) == before


def test_cli_hash_mismatch_in_an_old_version(dataset: Path, tmp_path: Path, capsys) -> None:
    splits_dir = tmp_path / "splits"
    _two_versions(dataset, splits_dir)
    path = splits_dir / "split_v1.csv"
    path.write_text(path.read_text().replace(",test\n", ",train\n", 1))
    before = _snapshot(splits_dir)
    capsys.readouterr()
    assert _run(dataset, splits_dir) == 2
    assert "split_v1.csv" in capsys.readouterr().err
    assert _snapshot(splits_dir) == before


def test_cli_conflict_in_the_history(dataset: Path, tmp_path: Path, capsys) -> None:
    splits_dir = tmp_path / "splits"
    _two_versions(dataset, splits_dir)
    v1 = _split_map(splits_dir / "split_v1.csv")
    df = load_manifest(dataset)
    item = _item_in(v1, df, "test", "screw")
    paths = set(df[df["item_id"] == item]["image_path"])
    edited = {p: ("val" if p in paths else s) for p, s in v1.items()}
    frame = pd.DataFrame({"image_path": list(edited), "split": list(edited.values())})
    content = split_csv_bytes(frame)
    (splits_dir / "split_v1.csv").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    (splits_dir / "split_v1.sha256").write_text(f"{digest}  split_v1.csv\n")
    before = _snapshot(splits_dir)
    capsys.readouterr()
    assert _run(dataset, splits_dir) == 2
    err = capsys.readouterr().err
    assert item in err and "split_v1.csv" in err and "split_v2.csv" in err
    assert _snapshot(splits_dir) == before
    with pytest.raises(SplitIntegrityError, match=item):
        item_history(
            [load_split(splits_dir / "split_v1.csv"), load_split(splits_dir / "split_v2.csv")],
            load_manifest(dataset),
        )
