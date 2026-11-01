"""Dataset, split, training, evaluation and ONNX export."""

import os

# SEC-19-01: only this variable, set before onnxruntime loads, stops its telemetry (SPEC-042).
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

__version__ = "0.0.0"
