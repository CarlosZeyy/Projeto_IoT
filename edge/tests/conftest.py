"""Fixtures of the qc-edge unit tests (SPEC-007). Images are generated in memory, never stored."""

from __future__ import annotations

import io
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PIL import Image

from qc_edge.config import EdgeSettings

EDGE_ENV_VARS = (
    "EDGE_HOST",
    "EDGE_PORT",
    "EDGE_SESSION_TOKEN",
    "DEVICE_ID",
    "EDGE_DATA_DIR",
    "DEVICE_API_KEY",
    "CLOUD_API_URL",
    "MODEL_DIR",
    "DATASET_DIR",
    "OUTBOX_PATH",
    "TYPE_THRESHOLD",
    "UNUSABLE_THRESHOLD",
    "GRADE_REVIEW_THRESHOLD",
)


def encode_image(
    size: tuple[int, int] = (64, 48), fmt: str = "JPEG", color: str = "steelblue"
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.fixture
def make_image() -> Callable[..., bytes]:
    """``make_image(size=(64, 48), fmt="JPEG", color=...)`` -> encoded bytes."""
    return encode_image


@pytest.fixture
def jpeg_bytes() -> bytes:
    return encode_image()


@pytest.fixture
def clean_edge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every edge variable from the process environment for the test."""
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "edge-data"


@pytest.fixture
def settings(clean_edge_env: None, data_dir: Path) -> EdgeSettings:
    return EdgeSettings(EDGE_DATA_DIR=data_dir)


@pytest.fixture
def files_under(tmp_path: Path) -> Iterator[Callable[[], list[Path]]]:
    """Returns a function listing the regular files under ``tmp_path``."""

    def _list() -> list[Path]:
        return sorted(path for path in tmp_path.rglob("*") if path.is_file())

    yield _list
