"""ONNX x torch parity from ``parity_fixture.npz``, with onnxruntime only (SPEC-012 section 4.4).

The fixture holds 8 preprocessed synthetic inputs and the probabilities computed by torch at
export time. Parity holds when the ONNX outputs differ by less than ``1e-4`` everywhere, the
argmax of both heads is identical on every input and the ``model_sha256`` of the fixture is the
one in ``model.sha256`` (which must match ``model.onnx``).

No torch here (CA-27); this is the test that runs in the CI.

CLI::

    python -m qc_ml.parity --model-dir ml/models/partqc-mnv3-v1
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort

from qc_ml.artifacts import PARITY_FILE, read_verified_model
from qc_ml.errors import ModelArtifactError
from qc_ml.predict import INPUT_NAME, OUTPUT_NAMES
from qc_ml.steps import EXIT_ERROR, EXIT_OK

TOLERANCE = 1e-4
FIXTURE_KEYS: tuple[str, ...] = ("inputs", "type_probs", "grade_probs", "model_sha256")


@dataclass(frozen=True)
class ParityResult:
    """``ok`` is ``max_abs_diff < 1e-4 and argmax_equal and sha256_match``."""

    ok: bool
    max_abs_diff: float
    argmax_equal: bool
    sha256_match: bool = True
    message: str = ""


def load_fixture(path: Path | str) -> dict[str, np.ndarray]:
    """The four arrays of ``parity_fixture.npz`` (no pickled objects are accepted)."""
    path = Path(path)
    if not path.is_file():
        raise ModelArtifactError(f"{path.name} not found in {path.parent}")
    with np.load(path, allow_pickle=False) as data:
        missing = [k for k in FIXTURE_KEYS if k not in data.files]
        if missing:
            raise ModelArtifactError(f"{path.name} lacks {', '.join(missing)}")
        return {k: data[k] for k in FIXTURE_KEYS}


def check_parity(model_dir: Path | str) -> ParityResult:
    """Run ``model.onnx`` (CPU) on the fixture inputs and compare with the torch outputs.

    Raises:
        ModelArtifactError: missing files, or ``model.onnx`` different from ``model.sha256``.
    """
    model_dir = Path(model_dir)
    data, digest = read_verified_model(model_dir)
    fixture = load_fixture(model_dir / PARITY_FILE)
    fixture_sha = str(fixture["model_sha256"])
    options = ort.SessionOptions()
    options.log_severity_level = 3
    session = ort.InferenceSession(data, sess_options=options, providers=["CPUExecutionProvider"])
    inputs = np.ascontiguousarray(fixture["inputs"], dtype=np.float32)
    outputs = session.run(list(OUTPUT_NAMES), {INPUT_NAME: inputs})
    expected = (fixture["type_probs"], fixture["grade_probs"])
    max_abs_diff = 0.0
    argmax_equal = True
    for got, want in zip(outputs, expected, strict=True):
        got = np.asarray(got, dtype=np.float64)
        want = np.asarray(want, dtype=np.float64)
        if got.shape != want.shape:
            return ParityResult(
                ok=False,
                max_abs_diff=float("inf"),
                argmax_equal=False,
                sha256_match=fixture_sha == digest,
                message=f"shape {got.shape} differs from the fixture {want.shape}",
            )
        max_abs_diff = max(max_abs_diff, float(np.max(np.abs(got - want))) if got.size else 0.0)
        argmax_equal = argmax_equal and bool(
            np.array_equal(np.argmax(got, axis=1), np.argmax(want, axis=1))
        )
    sha256_match = fixture_sha == digest
    ok = max_abs_diff < TOLERANCE and argmax_equal and sha256_match
    problems = []
    if not max_abs_diff < TOLERANCE:
        problems.append(f"max |onnx - torch| = {max_abs_diff:.3g} >= {TOLERANCE:g}")
    if not argmax_equal:
        problems.append("argmax differs")
    if not sha256_match:
        problems.append("the fixture was made for another model (model_sha256 differs)")
    return ParityResult(
        ok=ok,
        max_abs_diff=max_abs_diff,
        argmax_equal=argmax_equal,
        sha256_match=sha256_match,
        message="; ".join(problems) or "parity ok",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """0 when parity holds, 2 otherwise."""
    parser = argparse.ArgumentParser(prog="python -m qc_ml.parity", description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR
    try:
        result = check_parity(args.model_dir)
    except (ModelArtifactError, OSError, ValueError) as exc:
        print(f"parity failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    stream = sys.stdout if result.ok else sys.stderr
    print(f"{result.message} (max_abs_diff={result.max_abs_diff:.3g})", file=stream)
    return EXIT_OK if result.ok else EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
