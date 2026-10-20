"""Slow author test of the export warnings (SPEC-031 §4.3 item 2). Needs torch and onnx (extra
``train``); skipped in the CI."""

from __future__ import annotations

import importlib.util
import logging
import warnings
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("onnx")

from qc_ml import export as export_mod  # noqa: E402
from qc_ml.data import DEFAULT_LABELS  # noqa: E402

pytestmark = pytest.mark.slow

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_tiny_fixture.py"
MARKER = "spec031-deprecation-marker"


def _tiny_net() -> torch.nn.Module:
    spec = importlib.util.spec_from_file_location("make_tiny_fixture", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    torch.manual_seed(0)
    return module.TinyNet(len(DEFAULT_LABELS.object_types), len(DEFAULT_LABELS.grades)).eval()


@pytest.mark.parametrize("category", [DeprecationWarning, FutureWarning, UserWarning])
def test_export_logs_captured_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    category: type[Warning],
) -> None:
    original = torch.onnx.export

    def export_and_warn(*args, **kwargs):
        result = original(*args, **kwargs)
        warnings.warn(MARKER, category, stacklevel=1)
        return result

    monkeypatch.setattr(torch.onnx, "export", export_and_warn)
    caplog.set_level(logging.WARNING, logger="qc_ml.export")
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a re-emitted warning would raise here
        out = export_mod.export_onnx(_tiny_net(), tmp_path / "model.onnx")
    assert out.is_file()
    messages = [
        r.getMessage()
        for r in caplog.records
        if r.name == "qc_ml.export" and r.levelno == logging.WARNING
    ]
    if issubclass(category, DeprecationWarning):
        assert f"torch.onnx.export: {MARKER}" in messages
    else:  # not a deprecation: still logged (with its category), never re-emitted
        assert f"torch.onnx.export ({category.__name__}): {MARKER}" in messages
