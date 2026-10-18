"""The CI has no torch: the data modules must import without it (SPEC-011 §4.5); R-02/R-14."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULES = ("qc_ml.data", "qc_ml.split", "qc_ml.agreement", "qc_ml.augment", "qc_ml.synthetic")


def test_modules_import_without_torch() -> None:
    code = (
        "import sys\n"
        "sys.modules['torch'] = None\n"
        "import importlib\n"
        f"for name in {MODULES!r}:\n"
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
