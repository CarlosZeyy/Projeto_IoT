"""Author tests for qc_ml.parity and the tiny model fixture (SPEC-012 §4.4, §4.10; CA-11..14).

Run in the CI with onnxruntime only (no torch).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from qc_ml import parity as parity_mod
from qc_ml.errors import ModelArtifactError
from qc_ml.parity import check_parity

ROOT = Path(__file__).resolve().parents[2]
TINY = Path(__file__).resolve().parent / "fixtures" / "tiny_model"
FIXTURE_FILES = {
    "model.onnx",
    "model.sha256",
    "labels.json",
    "preprocessing.json",
    "decision.json",
    "parity_fixture.npz",
}
LOCAL_MODELS = sorted(p.parent for p in (ROOT / "ml" / "models").glob("*/model.onnx"))


def _check_sha(model_dir: Path) -> None:
    text = (model_dir / "model.sha256").read_bytes().decode("ascii")
    assert re.fullmatch(r"[0-9a-f]{64}\n", text)
    assert text[:64] == hashlib.sha256((model_dir / "model.onnx").read_bytes()).hexdigest()


def test_ca11_fixture_sha256() -> None:
    _check_sha(TINY)


def test_ca12_tiny_fixture_parity() -> None:
    result = check_parity(TINY)
    assert result.ok and result.max_abs_diff < 1e-4 and result.argmax_equal
    assert result.sha256_match


@pytest.mark.parametrize("model_dir", LOCAL_MODELS or [None], ids=lambda p: p.name if p else "none")
def test_ca12_local_models_parity(model_dir: Path | None) -> None:
    if model_dir is None:
        pytest.skip("no local ml/models/*/model.onnx (the real model is not in Git)")
    _check_sha(model_dir)
    result = check_parity(model_dir)
    assert result.ok, result.message


def test_ca13_perturbed_fixture_fails(tmp_path: Path) -> None:
    copy = Path(shutil.copytree(TINY, tmp_path / "tiny"))
    with np.load(copy / "parity_fixture.npz", allow_pickle=False) as data:
        arrays = {k: data[k] for k in data.files}
    arrays["type_probs"] = arrays["type_probs"].copy()
    arrays["type_probs"][0, 0] += 1e-3
    np.savez_compressed(copy / "parity_fixture.npz", **arrays)
    result = check_parity(copy)
    # 1e-3 -/+ 1e-4: float32 rounding and the |onnx - torch| noise of the runner's CPU
    # can leave the measured diff slightly below 1e-3 (SPEC-012 CA-13, SPEC_ISSUE-01).
    assert result.ok is False
    assert 9e-4 < result.max_abs_diff < 1.1e-3
    assert parity_mod.main(["--model-dir", str(copy)]) == 2


def test_parity_with_fixture_of_another_model(tmp_path: Path) -> None:
    copy = Path(shutil.copytree(TINY, tmp_path / "tiny"))
    with np.load(copy / "parity_fixture.npz", allow_pickle=False) as data:
        arrays = {k: data[k] for k in data.files}
    arrays["model_sha256"] = np.array("f" * 64)
    np.savez_compressed(copy / "parity_fixture.npz", **arrays)
    result = check_parity(copy)
    assert result.ok is False and result.sha256_match is False and result.argmax_equal


def test_parity_refuses_a_model_that_differs_from_its_sha(tmp_path: Path) -> None:
    copy = Path(shutil.copytree(TINY, tmp_path / "tiny"))
    (copy / "model.sha256").write_text("a" * 64 + "\n")
    with pytest.raises(ModelArtifactError, match="does not match"):
        check_parity(copy)
    (copy / "model.sha256").write_text("A" * 64 + "\n")
    with pytest.raises(ModelArtifactError, match="64 lowercase"):
        check_parity(copy)
    (copy / "parity_fixture.npz").unlink()
    (copy / "model.sha256").write_text(
        hashlib.sha256((copy / "model.onnx").read_bytes()).hexdigest() + "\n"
    )
    with pytest.raises(ModelArtifactError, match="parity_fixture.npz"):
        check_parity(copy)


def test_parity_cli_ok() -> None:
    assert parity_mod.main(["--model-dir", str(TINY)]) == 0


def test_ca14_fixture_files_size_and_git() -> None:
    files = {p.name for p in TINY.iterdir() if p.is_file()}
    assert files == FIXTURE_FILES
    assert sum((TINY / name).stat().st_size for name in files) < 1_000_000
    with np.load(TINY / "parity_fixture.npz", allow_pickle=False) as data:
        assert data["inputs"].shape == (8, 3, 224, 224) and data["inputs"].dtype == np.float32
        assert data["type_probs"].shape == (8, 3) and data["grade_probs"].shape == (8, 5)
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    paths = [str((TINY / name).relative_to(ROOT)) for name in sorted(files)]
    ignored = subprocess.run(
        [git, "check-ignore", *paths], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert ignored.returncode == 1, ignored.stdout  # 1 = none of the paths is ignored
