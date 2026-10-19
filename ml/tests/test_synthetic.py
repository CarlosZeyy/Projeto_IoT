"""Author tests for qc_ml.synthetic (SPEC-011 section 4.6)."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from qc_ml.data import load_manifest
from qc_ml.synthetic import add_synthetic_item, make_synthetic_dataset, make_synthetic_image
from qc_preprocess import load_image

FILE_NAME = re.compile(r"[SNO]-\d{3}__[0-4]__\d{8}T\d{6}Z\.jpg")


def test_layout_and_manifest(dataset: Path, rows_io) -> None:
    read_rows, _, _ = rows_io
    rows = read_rows(dataset)
    assert len(rows) == 88
    for row in rows:
        folder = row["grade"] or "_"
        prefix = f"raw/{row['object_type']}/{folder}/"
        assert row["image_path"].startswith(prefix)
        assert FILE_NAME.fullmatch(row["image_path"].removeprefix(prefix))
        assert row["image_path"].split("/")[-1].startswith(row["item_id"] + "__")
    ids = {r["item_id"] for r in rows}
    assert {f"S-{k:03d}" for k in range(1, 21)} <= ids
    assert {f"O-{k:03d}" for k in range(1, 5)} <= ids
    assert {r["grade"] for r in rows if r["item_id"] == "S-003"} == {"fair"}


def test_images_are_baseline_jpeg_256(dataset: Path, rows_io) -> None:
    read_rows, _, _ = rows_io
    path = dataset / read_rows(dataset)[0]["image_path"]
    raw = path.read_bytes()
    assert raw.startswith(b"\xff\xd8\xff") and raw.count(b"\xff\xda") == 1
    assert load_image(path).size == (256, 256)


def test_same_seed_same_bytes(tmp_path: Path) -> None:
    a = make_synthetic_dataset(tmp_path / "a", items_per_stratum=1, images_per_item=1)
    b = make_synthetic_dataset(tmp_path / "b", items_per_stratum=1, images_per_item=1)
    assert (a / "manifest.csv").read_bytes() == (b / "manifest.csv").read_bytes()
    for path in (a / "raw").rglob("*.jpg"):
        assert path.read_bytes() == (b / path.relative_to(a)).read_bytes()


def test_rust_grows_with_grade() -> None:
    def orange_fraction(grade: str) -> float:
        x = np.asarray(make_synthetic_image("screw", grade, np.random.default_rng(5))).astype(int)
        return float(((x[..., 0] - x[..., 2]) > 100).mean())

    fractions = [orange_fraction(g) for g in ("perfect", "good", "fair", "poor", "unusable")]
    assert fractions[0] == 0
    assert fractions == sorted(fractions)


def test_options_and_errors(tmp_path: Path) -> None:
    root = make_synthetic_dataset(tmp_path / "x", items_per_stratum=1, include_other=False)
    df = load_manifest(root)
    assert len(df) == 20 and "other" not in set(df["object_type"])
    with pytest.raises(FileExistsError):
        make_synthetic_dataset(root)
    with pytest.raises(ValueError):
        make_synthetic_dataset(tmp_path / "y", items_per_stratum=0)


def test_add_item_keeps_the_manifest_valid(dataset: Path) -> None:
    new = add_synthetic_item(dataset, "N-101", "nut", "poor", n_images=3)
    again = add_synthetic_item(dataset, "N-101", "nut", "poor", n_images=2)
    df = load_manifest(dataset)
    assert len(df) == 93
    assert set(new + again) <= set(df["image_path"])
