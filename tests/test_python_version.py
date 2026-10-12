"""ADR-010 / R-12: Python 3.12 pinned at the root and in every workspace member."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ["packages/contracts", "packages/preprocess", "api", "edge", "dashboard", "ml"]
REQUIRES_PYTHON = ">=3.12,<3.13"


def _pyproject(folder: str) -> dict:
    return tomllib.loads((ROOT / folder / "pyproject.toml").read_text(encoding="utf-8"))


def test_python_version_file_is_312() -> None:
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"


@pytest.mark.parametrize("folder", [".", *MEMBERS])
def test_requires_python(folder: str) -> None:
    assert _pyproject(folder)["project"]["requires-python"] == REQUIRES_PYTHON


def test_workspace_members_match_spec() -> None:
    root = _pyproject(".")
    assert root["tool"]["uv"]["workspace"]["members"] == MEMBERS
    assert root["tool"]["uv"]["package"] is False
    assert root["tool"]["uv"]["required-version"] == ">=0.8"


@pytest.mark.parametrize("folder", MEMBERS)
def test_members_build_with_hatchling(folder: str) -> None:
    assert _pyproject(folder)["build-system"]["build-backend"] == "hatchling.build"
