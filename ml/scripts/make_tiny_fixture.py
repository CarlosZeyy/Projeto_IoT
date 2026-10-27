"""Create the tiny model directory used by the CI tests (SPEC-012 section 4.10).

Run once, with the ``train`` extra (torch, onnx), from the repository root::

    uv run --package qc-ml python ml/scripts/make_tiny_fixture.py
    uv run --package qc-ml python ml/scripts/make_tiny_fixture.py --with-tools
    uv run --package qc-ml python ml/scripts/make_tiny_fixture.py --with-power-tools

``--with-tools`` (SPEC-016 section 4.10) writes ``ml/tests/fixtures/tiny_model_tools/`` instead:
the same structure, with a type head of 8 classes (``screw``, ``nut``, ``other`` and the 5 hand
tools) and ``labels.json`` with ``ungraded_object_types = ["allen_key"]``.

``--with-power-tools`` (SPEC-021 section 3.1) writes ``ml/tests/fixtures/tiny_model_power_tools/``:
a type head of 12 classes (the 8 above and the 4 power tools) and ``labels.json`` with
``ungraded_object_types`` equal to the 4 power tools.

The network is minimal (conv 3->8, global average pooling, two linear heads) and goes through the
same ``ProbabilityWrapper`` and ``export_onnx`` as the real model, so the CI can test the parity,
the thresholds and the evaluation with onnxruntime only. The parity inputs are synthetic
(``make_synthetic_dataset(seed=0)``); no real photo is used (R-02, R-14). Total < 1 MB.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
from torch import nn

from qc_ml.artifacts import DECISION_FILE
from qc_ml.data import (
    DEFAULT_LABELS,
    KNOWN_OBJECT_TYPES,
    MVP_OBJECT_TYPES,
    POWER_TOOL_OBJECT_TYPES,
    TOOL_OBJECT_TYPES,
    ModelLabels,
)
from qc_ml.decision import Thresholds, write_decision
from qc_ml.export import write_model_dir

DEFAULT_OUT = Path("ml/tests/fixtures/tiny_model")
TOOLS_OUT = Path("ml/tests/fixtures/tiny_model_tools")
# The 8 types of SPEC-016 (not KNOWN_OBJECT_TYPES, which gained the power tools in SPEC-021).
TOOLS_LABELS = ModelLabels(
    object_types=(*MVP_OBJECT_TYPES, *TOOL_OBJECT_TYPES),
    grades=DEFAULT_LABELS.grades,
    ungraded_object_types=("allen_key",),
)
POWER_TOOLS_OUT = Path("ml/tests/fixtures/tiny_model_power_tools")
POWER_TOOLS_LABELS = ModelLabels(
    object_types=KNOWN_OBJECT_TYPES,
    grades=DEFAULT_LABELS.grades,
    ungraded_object_types=POWER_TOOL_OBJECT_TYPES,
)
TINY_DECISION = Thresholds(
    type_threshold=0.70, unusable_threshold=0.50, grade_review_threshold=0.60
)
MAX_TOTAL_BYTES = 1_000_000
SEED = 0


class TinyNet(nn.Module):
    """conv 3->8 (3x3, stride 4) + ReLU + global average pooling + ``type``/``grade`` heads."""

    grade_head_kind = "ce"

    def __init__(self, n_types: int = 3, n_grades: int = 5) -> None:
        super().__init__()
        self.conv = nn.Conv2d(3, 8, kernel_size=3, stride=4, padding=1)
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.type_head = nn.Linear(8, n_types)
        self.grade_head = nn.Linear(8, n_grades)
        with torch.no_grad():  # larger weights: probabilities far from uniform
            for head in (self.type_head, self.grade_head):
                head.weight.normal_(0.0, 3.0)
                head.bias.normal_(0.0, 0.5)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        features = self.pool(torch.relu(self.conv(x))).flatten(1)
        return self.type_head(features), self.grade_head(features)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None)
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument(
        "--with-tools",
        action="store_true",
        help="8 types (the 5 hand tools included) and allen_key ungraded (SPEC-016)",
    )
    kind.add_argument(
        "--with-power-tools",
        action="store_true",
        help="12 types (hand and power tools) and the 4 power tools ungraded (SPEC-021)",
    )
    args = parser.parse_args(argv)
    if args.with_power_tools:
        labels, default_out = POWER_TOOLS_LABELS, POWER_TOOLS_OUT
    elif args.with_tools:
        labels, default_out = TOOLS_LABELS, TOOLS_OUT
    else:
        labels, default_out = DEFAULT_LABELS, DEFAULT_OUT
    out = args.out or default_out
    torch.manual_seed(SEED)
    model = TinyNet(len(labels.object_types), len(labels.grades)).eval()
    out.mkdir(parents=True, exist_ok=True)
    digest = write_model_dir(model, out, labels)
    write_decision(out / DECISION_FILE, TINY_DECISION)
    total = sum(p.stat().st_size for p in out.iterdir() if p.is_file())
    print(f"tiny model written to {out} (sha256 {digest}, {total} bytes)")
    if total >= MAX_TOTAL_BYTES:
        print(f"the fixture must stay below {MAX_TOTAL_BYTES} bytes", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
