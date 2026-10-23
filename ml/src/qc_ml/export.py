"""ONNX export of the best checkpoint and the files of the model directory (SPEC-012 §4.3).

Requires the ``train`` extra (torch, onnx). The exported module is ``ProbabilityWrapper`` in
``eval()``: input ``image`` float32 ``[N, 3, 224, 224]``, outputs ``type_probs [N, T]`` and
``grade_probs [N, 5]``, axis 0 dynamic. After writing ``model.onnx``, ``model.sha256``,
``labels.json``, ``preprocessing.json`` and ``parity_fixture.npz``, the parity is checked with
onnxruntime; a failure deletes ``model.onnx``.

The 8 parity inputs come from ``make_synthetic_dataset(seed=0)`` (never a real photo in Git,
R-02/R-14), preprocessed by ``qc_preprocess``.

CLI::

    python -m qc_ml.export --config ml/configs/partqc-mnv3-v1.json
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import warnings
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import onnx
import torch
from torch import nn

from qc_ml.artifacts import (
    LABELS_FILE,
    MODEL_FILE,
    PARITY_FILE,
    PREPROCESSING_FILE,
    sha256_file,
    write_labels,
    write_model_sha256,
)
from qc_ml.config import TrainConfig, load_config
from qc_ml.data import DEFAULT_LABELS, ModelLabels, configure_logging, load_manifest
from qc_ml.errors import ExportError, TrainError
from qc_ml.model import ProbabilityWrapper, build_model
from qc_ml.parity import check_parity
from qc_ml.steps import EXIT_ERROR, EXIT_OK, report_step_error
from qc_ml.synthetic import make_synthetic_dataset
from qc_preprocess import PreprocessParams, load_image, preprocess

logger = logging.getLogger(__name__)

OPSET = 17
N_PARITY_INPUTS = 8
MIN_TOP2_GAP = 1e-3
INPUT_NAME = "image"
OUTPUT_NAMES: tuple[str, str] = ("type_probs", "grade_probs")


def _log_export_warnings(caught: Sequence[warnings.WarningMessage]) -> None:
    """Log the warnings captured during ``torch.onnx.export`` as ``WARNING``; never re-emit.

    Each ``DeprecationWarning`` (or subclass) becomes ``torch.onnx.export: <message>``: the
    TorchScript exporter (``dynamo=False``) is deprecated upstream, and logging its notices keeps
    a change of that path visible in the training log (SPEC-031 section 4.3). Any other captured
    warning is logged too, with its category, so that capturing does not hide it.
    """
    for item in caught:
        if issubclass(item.category, DeprecationWarning):
            logger.warning("torch.onnx.export: %s", item.message)
        else:
            logger.warning("torch.onnx.export (%s): %s", item.category.__name__, item.message)


def export_onnx(model: nn.Module, out_path: Path | str, opset: int = OPSET) -> Path:
    """Export ``ProbabilityWrapper(model)`` (or ``model`` if already wrapped) to ``out_path``.

    Uses the TorchScript-based exporter (``dynamo=False``), which needs no extra dependency.
    The deprecation warnings emitted by ``torch.onnx.export`` are logged as ``WARNING`` on
    ``qc_ml.export`` (not re-emitted). ``onnx.checker.check_model`` runs on the result.

    Raises:
        ExportError: ``opset < 17`` or the checker rejects the model.
    """
    if opset < OPSET:
        raise ExportError(f"opset must be >= {OPSET}, got {opset}")
    wrapper = model if isinstance(model, ProbabilityWrapper) else ProbabilityWrapper(model)
    wrapper = wrapper.cpu().eval()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.zeros(1, 3, 224, 224, dtype=torch.float32)
    axes = {name: {0: "batch"} for name in (INPUT_NAME, *OUTPUT_NAMES)}
    with warnings.catch_warnings(record=True) as caught, torch.no_grad():
        warnings.simplefilter("always")  # record every warning, even under "error" filters
        torch.onnx.export(
            wrapper,
            (dummy,),
            str(out_path),
            input_names=[INPUT_NAME],
            output_names=list(OUTPUT_NAMES),
            dynamic_axes=axes,
            opset_version=opset,
            do_constant_folding=True,
            dynamo=False,
        )
    _log_export_warnings(caught)
    try:
        onnx.checker.check_model(onnx.load(str(out_path)))
    except onnx.checker.ValidationError as exc:
        out_path.unlink(missing_ok=True)
        raise ExportError(f"onnx.checker rejected the model: {exc}") from exc
    return out_path


def _top2_gap(probs: np.ndarray) -> float:
    ordered = np.sort(probs)
    return float(ordered[-1] - ordered[-2])


def parity_candidates(params: PreprocessParams) -> list[np.ndarray]:
    """Preprocessed synthetic inputs (``[1, 3, H, W]`` each), interleaving types and grades.

    ``make_synthetic_dataset(seed=0)`` in a temporary directory; the candidates alternate between
    the (type, grade) strata so that the 8 chosen inputs are varied.
    """
    with tempfile.TemporaryDirectory(prefix="qc_ml_parity_") as tmp:
        root = make_synthetic_dataset(Path(tmp) / "synthetic", seed=0)
        df = load_manifest(root)
        groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        for image_path, object_type, grade in zip(
            df["image_path"], df["object_type"], df["grade"], strict=True
        ):
            groups[(str(object_type), str(grade))].append(str(image_path))
        ordered: list[str] = []
        queues = [groups[key] for key in sorted(groups)]
        while any(queues):
            for queue in queues:
                if queue:
                    ordered.append(queue.pop(0))
        return [preprocess(load_image(root / p), params) for p in ordered]


def make_parity_fixture(
    model: nn.Module, path: Path, model_sha256: str, params: PreprocessParams | None = None
) -> dict[str, np.ndarray]:
    """Write ``parity_fixture.npz`` with 8 inputs and the torch outputs of ``model``.

    A candidate whose top-2 gap is below ``1e-3`` in either head is replaced by the next one.

    Raises:
        ExportError: fewer than 8 usable candidates.
    """
    params = params or PreprocessParams()
    wrapper = model if isinstance(model, ProbabilityWrapper) else ProbabilityWrapper(model)
    wrapper = wrapper.cpu().eval()
    chosen: list[np.ndarray] = []
    type_out: list[np.ndarray] = []
    grade_out: list[np.ndarray] = []
    with torch.no_grad():
        for candidate in parity_candidates(params):
            type_probs, grade_probs = wrapper(torch.from_numpy(candidate))
            t = type_probs.numpy()[0]
            g = grade_probs.numpy()[0]
            if _top2_gap(t) < MIN_TOP2_GAP or _top2_gap(g) < MIN_TOP2_GAP:
                continue
            chosen.append(candidate[0])
            type_out.append(t)
            grade_out.append(g)
            if len(chosen) == N_PARITY_INPUTS:
                break
    if len(chosen) < N_PARITY_INPUTS:
        raise ExportError(
            f"only {len(chosen)} synthetic inputs have a top-2 gap >= {MIN_TOP2_GAP} in both "
            f"heads; {N_PARITY_INPUTS} are needed"
        )
    inputs = np.stack(chosen).astype(np.float32)
    with torch.no_grad():  # outputs of the whole batch, as the ONNX model will see it
        type_probs, grade_probs = wrapper(torch.from_numpy(inputs))
    fixture = {
        "inputs": inputs,
        "type_probs": type_probs.numpy().astype(np.float32),
        "grade_probs": grade_probs.numpy().astype(np.float32),
        "model_sha256": np.array(model_sha256),
    }
    np.savez_compressed(path, **fixture)
    return fixture


def write_model_dir(
    model: nn.Module,
    model_dir: Path,
    labels: ModelLabels = DEFAULT_LABELS,
    params: PreprocessParams | None = None,
    opset: int = OPSET,
) -> str:
    """Write the exported files of ``model_dir`` and check the parity; return the SHA-256.

    Raises:
        ExportError: the export, the checker or the parity failed (``model.onnx`` deleted).
    """
    params = params or PreprocessParams()
    model_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = export_onnx(model, model_dir / MODEL_FILE, opset=opset)
    digest = sha256_file(onnx_path)
    write_model_sha256(model_dir, digest)
    write_labels(model_dir / LABELS_FILE, labels)
    params.to_json(model_dir / PREPROCESSING_FILE)
    try:
        make_parity_fixture(model, model_dir / PARITY_FILE, digest, params)
        result = check_parity(model_dir)
    except Exception:
        onnx_path.unlink(missing_ok=True)
        raise
    if not result.ok:
        onnx_path.unlink(missing_ok=True)
        raise ExportError(f"parity failed, {MODEL_FILE} deleted: {result.message}")
    logger.info("exported %s (sha256 %s; parity %s)", onnx_path, digest, result.message)
    return digest


def run(config: TrainConfig, model: nn.Module | None = None) -> str:
    """Export the best checkpoint of ``config`` (or ``model``) to ``<models_root>/<v>/``."""
    if model is None:
        best = config.checkpoints_dir / "best.pt"
        if not best.is_file():
            raise TrainError(f"{best} not found: run qc_ml.train first")
        model = build_model(
            config.backbone, len(DEFAULT_LABELS.object_types), config.grade_head, False
        )
        model.load_state_dict(torch.load(best, map_location="cpu", weights_only=True)["model"])
    return write_model_dir(model, config.model_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qc_ml.export", description="Export the best checkpoint to ONNX."
    )
    parser.add_argument("--config", required=True, help="ml/configs/<model_version>.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; 0 when the model directory was written and the parity holds, else 2."""
    configure_logging()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR
    try:
        run(load_config(args.config))
    except Exception as exc:  # noqa: BLE001 - every failure is reported and exits with 2
        return report_step_error("export", exc)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
