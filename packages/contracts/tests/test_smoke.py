import tomllib
from importlib.metadata import requires, version
from pathlib import Path

import qc_contracts

PACKAGE_DIR = Path(__file__).resolve().parents[1]


def test_import_and_version() -> None:
    assert qc_contracts.__version__ == "0.2.0"
    assert version("qc-contracts") == qc_contracts.__version__


def test_pyproject_version_matches_dunder_version() -> None:
    pyproject = tomllib.loads((PACKAGE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == qc_contracts.__version__


def test_only_pydantic_dependency() -> None:
    reqs = requires("qc-contracts") or []
    assert [r.split(">")[0].split("=")[0].strip() for r in reqs] == ["pydantic"]


def test_readme_has_version_history_row() -> None:
    readme = (PACKAGE_DIR / "README.md").read_text(encoding="utf-8")
    assert "## Histórico de versões" in readme
    assert "| 0.1.0 |" in readme
    assert "| 0.2.0 |" in readme
    assert "MAX_LATENCY_MS" in readme


def test_public_api_is_exported() -> None:
    for name in qc_contracts.__all__:
        assert hasattr(qc_contracts, name), name
