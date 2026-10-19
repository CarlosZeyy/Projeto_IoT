"""Create the tiny model directory used by the CI tests (SPEC-012 section 4.10).

Run once, with the ``train`` extra (torch, onnx), from the repository root::

    uv run --package qc-ml python ml/scripts/make_tiny_fixture.py

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
from qc_ml.data import DEFAULT_LABELS
from qc_ml.decision import Thresholds, write_decision
from qc_ml.export import write_model_dir

DEFAULT_OUT = Path("ml/tests/fixtures/tiny_model")
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
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    torch.manual_seed(SEED)
    model = TinyNet(len(DEFAULT_LABELS.object_types), len(DEFAULT_LABELS.grades)).eval()
    args.out.mkdir(parents=True, exist_ok=True)
    digest = write_model_dir(model, args.out)
    write_decision(args.out / DECISION_FILE, TINY_DECISION)
    total = sum(p.stat().st_size for p in args.out.iterdir() if p.is_file())
    print(f"tiny model written to {args.out} (sha256 {digest}, {total} bytes)")
    if total >= MAX_TOTAL_BYTES:
        print(f"the fixture must stay below {MAX_TOTAL_BYTES} bytes", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
