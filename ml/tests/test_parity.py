"""Author tests for qc_ml.parity and the tiny model fixture (SPEC-012 §4.4, §4.10; CA-11..14).

Run in the CI with onnxruntime only (no torch).
"""

from __future__ import annotations

import hashlib
import math
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


# SPEC-031 §4.1: non-finite values make the parity fail loud (a NaN used to vanish from max()).


def _copy_with(tmp_path: Path, edit) -> Path:
    copy = Path(shutil.copytree(TINY, tmp_path / "tiny"))
    with np.load(copy / "parity_fixture.npz", allow_pickle=False) as data:
        arrays = {k: data[k].copy() for k in data.files}
    edit(arrays)
    np.savez_compressed(copy / "parity_fixture.npz", **arrays)
    return copy


def _nan_at_argmax(arrays: dict[str, np.ndarray]) -> None:
    j = int(np.argmax(arrays["type_probs"][0]))
    arrays["type_probs"][0, j] = np.nan


def _nan_input_and_refs(arrays: dict[str, np.ndarray]) -> None:
    arrays["inputs"][0] = np.nan
    arrays["type_probs"][0, :] = np.nan
    arrays["grade_probs"][0, :] = np.nan


def _inf_grade_reference(arrays: dict[str, np.ndarray]) -> None:
    arrays["grade_probs"][3, 1] = np.inf


@pytest.mark.parametrize(
    "edit",
    [_nan_at_argmax, _nan_input_and_refs, _inf_grade_reference],
    ids=["nan-reference-at-argmax", "nan-both-sides", "inf-reference"],
)
def test_parity_non_finite_values_fail(
    tmp_path: Path, edit, capsys: pytest.CaptureFixture[str]
) -> None:
    copy = _copy_with(tmp_path, edit)
    result = check_parity(copy)
    assert result.ok is False
    assert result.max_abs_diff == math.inf
    assert result.argmax_equal is False
    assert result.sha256_match is True
    assert "non-finite values" in result.message
    assert parity_mod.main(["--model-dir", str(copy)]) == 2
    captured = capsys.readouterr()
    assert "non-finite values" in captured.err and captured.out == ""


class _NanOutputSession:
    """Real onnxruntime session whose ``grade_probs`` output gets one NaN (output side only)."""

    def __init__(self, *args, **kwargs) -> None:
        self._session = _REAL_SESSION(*args, **kwargs)

    def run(self, names, feeds):
        outputs = [np.array(o, copy=True) for o in self._session.run(names, feeds)]
        outputs[1][2, 0] = np.nan
        return outputs


_REAL_SESSION = parity_mod.ort.InferenceSession


def test_parity_non_finite_onnx_output_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    copy = Path(shutil.copytree(TINY, tmp_path / "tiny"))
    monkeypatch.setattr(parity_mod.ort, "InferenceSession", _NanOutputSession)
    result = check_parity(copy)
    assert result.ok is False and result.max_abs_diff == math.inf
    assert result.argmax_equal is False and "non-finite values" in result.message
    assert parity_mod.main(["--model-dir", str(copy)]) == 2
    assert "non-finite values" in capsys.readouterr().err


def test_parity_non_finite_with_fixture_of_another_model(tmp_path: Path) -> None:
    def edit(arrays: dict[str, np.ndarray]) -> None:
        _nan_at_argmax(arrays)
        arrays["model_sha256"] = np.array("f" * 64)

    result = check_parity(_copy_with(tmp_path, edit))
    assert result.ok is False and result.sha256_match is False
    assert "non-finite values" in result.message and "model_sha256 differs" in result.message


def test_parity_finite_result_unchanged() -> None:
    """With finite values, max_abs_diff is the plain maximum of |onnx - torch| (as before)."""
    import onnxruntime as ort

    from qc_ml.artifacts import read_verified_model

    data, _ = read_verified_model(TINY)
    with np.load(TINY / "parity_fixture.npz", allow_pickle=False) as fixture:
        inputs, want_t, want_g = fixture["inputs"], fixture["type_probs"], fixture["grade_probs"]
    got_t, got_g = ort.InferenceSession(data, providers=["CPUExecutionProvider"]).run(
        ["type_probs", "grade_probs"], {"image": inputs}
    )
    expected = max(
        float(np.max(np.abs(np.float64(got_t) - np.float64(want_t)))),
        float(np.max(np.abs(np.float64(got_g) - np.float64(want_g)))),
    )
    result = check_parity(TINY)
    assert result.ok and result.max_abs_diff == expected < 1e-4
