"""Shared fixtures of the qc-ml author tests: synthetic datasets in tmp_path, never real data."""

from __future__ import annotations

import csv
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from qc_ml.data import MANIFEST_COLUMNS
from qc_ml.synthetic import make_synthetic_dataset


@pytest.fixture(scope="session")
def _template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_synthetic_dataset(tmp_path_factory.mktemp("template") / "ds")


@pytest.fixture(scope="session")
def _template_large(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_synthetic_dataset(
        tmp_path_factory.mktemp("template_large") / "ds", items_per_stratum=20, images_per_item=3
    )


@pytest.fixture
def dataset(_template: Path, tmp_path: Path) -> Path:
    """CA-01 dataset: 5 grades x 4 items x 2 images for screw and nut, 4 other items (88 rows)."""
    return Path(shutil.copytree(_template, tmp_path / "ds"))


@pytest.fixture
def large_dataset(_template_large: Path, tmp_path: Path) -> Path:
    """20 items per stratum, 3 images per item (CA-12, CA-13)."""
    return Path(shutil.copytree(_template_large, tmp_path / "ds"))


def read_rows(root: Path) -> list[dict[str, str]]:
    with (root / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(root: Path, rows: list[dict[str, str]]) -> None:
    with (root / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANIFEST_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


@pytest.fixture
def rows_io() -> tuple[Callable, Callable, Callable]:
    """``(read_rows, write_rows, write_csv)`` helpers."""
    return read_rows, write_rows, write_csv
