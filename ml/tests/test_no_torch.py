"""The CI has no torch: the data modules (SPEC-011 §4.5) and the evaluation modules (SPEC-012
CA-27) must import without it; R-02/R-14."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULES = ("qc_ml.data", "qc_ml.split", "qc_ml.agreement", "qc_ml.augment", "qc_ml.synthetic")
# SPEC-012 CA-27, plus the torch-free helpers they use and the pipeline entry point.
EVALUATION_MODULES = (
    "qc_ml.predict",
    "qc_ml.decision",
    "qc_ml.thresholds",
    "qc_ml.evaluate",
    "qc_ml.parity",
    "qc_ml.report",
    "qc_ml.config",
    "qc_ml.artifacts",
    "qc_ml.plots",
    "qc_ml.steps",
    "qc_ml.pipeline",
    "qc_ml.train",
)


@pytest.mark.parametrize("modules", [MODULES, EVALUATION_MODULES], ids=["spec011", "spec012"])
def test_modules_import_without_torch(modules: tuple[str, ...]) -> None:
    code = (
        "import sys\n"
        "sys.modules['torch'] = None\n"
        "import importlib\n"
        f"for name in {modules!r}:\n"
        "    importlib.import_module(name)\n"
        "assert sys.modules['torch'] is None\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_no_images_tracked_under_ml() -> None:
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(
        [git, "ls-files", "ml"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    images = [
        p
        for p in tracked
        if p.lower().endswith((".jpg", ".jpeg", ".png")) and not p.startswith("ml/reports/")
    ]
    assert images == []
