import subprocess
import sys
import tomllib
from importlib.metadata import requires, version
from pathlib import Path

import qc_preprocess

PACKAGE_DIR = Path(__file__).resolve().parents[1]


def test_import_and_version() -> None:
    assert qc_preprocess.__version__ == "0.1.0"
    assert version("qc-preprocess") == qc_preprocess.__version__


def test_pyproject_version_matches_dunder_version() -> None:
    pyproject = tomllib.loads((PACKAGE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == qc_preprocess.__version__


def test_only_numpy_and_pillow_dependencies() -> None:
    reqs = requires("qc-preprocess") or []
    names = sorted(r.split(">")[0].split("=")[0].split("<")[0].strip().lower() for r in reqs)
    assert names == ["numpy", "pillow"]


def test_import_does_not_load_torch() -> None:
    code = (
        "import sys, qc_preprocess, qc_contracts; "
        "bad = [m for m in ('torch', 'torchvision', 'timm', 'onnxruntime') if m in sys.modules]; "
        "assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
