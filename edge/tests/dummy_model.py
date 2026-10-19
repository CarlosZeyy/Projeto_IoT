"""Dummy ONNX models and model directories for the qc-edge tests (SPEC-008 section 6).

Built with ``onnx.helper`` (opset 17), never with torch: ``ReduceMean`` of the input over
``[1, 2, 3]`` -> ``Reshape [N, 1]`` -> ``Mul`` by 0 -> ``Add`` of the constants ``[1, T]`` and
``[1, 5]``. The outputs are therefore constant (``type_probs`` and ``grade_probs`` given here),
for any image and any batch size.

``ir_version`` is pinned to 8 (the IR of opset 17): ``onnx`` 1.23 writes IR 14 by default, and
the ``onnxruntime`` locked in ``uv.lock`` (1.31) only reads up to IR 13.

This module is not a test file. The tests reach it through the ``dummy_model`` fixture of
``edge/tests/conftest.py`` (``--import-mode=importlib`` does not put ``edge/tests`` on
``sys.path``), which also serves ``edge/tests/acceptance/``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

OPSET = 17
IR_VERSION = 8
OBJECT_TYPES = ("screw", "nut", "other")
GRADES = ("perfect", "good", "fair", "poor", "unusable")
TYPE_PROBS = (0.9, 0.05, 0.05)
GRADE_PROBS = (0.05, 0.8, 0.05, 0.05, 0.05)
DECISION = {"type_threshold": 0.5, "unusable_threshold": 0.4, "grade_review_threshold": 0.6}
# Input shapes: spatial dimensions fixed at 224 (default) or dynamic (SPEC-008 section 6, CA-22).
FIXED_INPUT_SHAPE: tuple[str | int, ...] = ("N", 3, 224, 224)
DYNAMIC_INPUT_SHAPE: tuple[str | int, ...] = ("N", 3, "H", "W")
PREPROCESSING = {
    "resize_shorter": 256,
    "crop": 224,
    "mean": [0.485, 0.456, 0.406],
    "std": [0.229, 0.224, 0.225],
}


def build_model(
    type_probs: Sequence[float] = TYPE_PROBS,
    grade_probs: Sequence[float] = GRADE_PROBS,
    *,
    input_name: str = "image",
    type_output: str = "type_probs",
    grade_output: str = "grade_probs",
    opset: int = OPSET,
    ir_version: int = IR_VERSION,
    input_shape: Sequence[str | int] = FIXED_INPUT_SHAPE,
) -> onnx.ModelProto:
    """Model with input ``input_shape`` and constant outputs ``[N, T]`` and ``[N, G]``.

    ``T`` and ``G`` are the lengths of ``type_probs`` and ``grade_probs``: a vector of the wrong
    length gives a model of the wrong shape (CA-13). The input is ``[N, 3, 224, 224]`` by default;
    ``DYNAMIC_INPUT_SHAPE`` declares dynamic spatial dimensions (``ReduceMean`` takes any size).
    """
    types = np.asarray([list(type_probs)], dtype=np.float32)
    grades = np.asarray([list(grade_probs)], dtype=np.float32)
    nodes = [
        helper.make_node("ReduceMean", [input_name], ["mean"], axes=[1, 2, 3], keepdims=0),
        helper.make_node("Reshape", ["mean", "column"], ["mean_column"]),
        helper.make_node("Mul", ["mean_column", "zero"], ["zeros"]),
        helper.make_node("Add", ["zeros", "type_const"], [type_output]),
        helper.make_node("Add", ["zeros", "grade_const"], [grade_output]),
    ]
    initializers = [
        numpy_helper.from_array(np.asarray([-1, 1], dtype=np.int64), "column"),
        numpy_helper.from_array(np.asarray(0.0, dtype=np.float32), "zero"),
        numpy_helper.from_array(types, "type_const"),
        numpy_helper.from_array(grades, "grade_const"),
    ]
    graph = helper.make_graph(
        nodes,
        "partqc-dummy",
        [helper.make_tensor_value_info(input_name, TensorProto.FLOAT, list(input_shape))],
        [
            helper.make_tensor_value_info(type_output, TensorProto.FLOAT, ["N", types.shape[1]]),
            helper.make_tensor_value_info(grade_output, TensorProto.FLOAT, ["N", grades.shape[1]]),
        ],
        initializers,
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", opset)], ir_version=ir_version
    )
    onnx.checker.check_model(model)
    return model


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def write_model_dir(
    root: Path,
    name: str = "dummy-v1",
    *,
    type_probs: Sequence[float] = TYPE_PROBS,
    grade_probs: Sequence[float] = GRADE_PROBS,
    model: onnx.ModelProto | bytes | None = None,
    sha256: str | None = None,
    labels: Mapping[str, Any] | None = None,
    object_types: Sequence[str] = OBJECT_TYPES,
    preprocessing: Mapping[str, Any] | None = None,
    decision: Mapping[str, Any] | None = None,
    omit: Sequence[str] = (),
) -> Path:
    """Write a complete model directory ``root/name`` and return its path.

    Defaults: the dummy model of CA-08 (``screw`` 0.9, ``good`` 0.8), ``labels.json`` with
    ``object_types`` and the 5 grades, the default ``preprocessing.json`` and the thresholds of
    the CAs (0.5 / 0.4 / 0.6). ``model`` replaces the ONNX (a ``ModelProto`` or raw bytes);
    ``sha256`` replaces the content of ``model.sha256`` (default: the real hash and the file
    name, as ``sha256sum`` writes it); ``labels``, ``preprocessing`` and ``decision`` replace the
    JSON objects; ``omit`` lists files that are not written.
    """
    directory = Path(root) / name
    directory.mkdir(parents=True, exist_ok=True)
    if model is None:
        model = build_model(type_probs, grade_probs)
    data = model if isinstance(model, bytes) else model.SerializeToString()
    files: dict[str, Any] = {
        "labels.json": (
            dict(labels)
            if labels is not None
            else {"object_types": list(object_types), "grades": list(GRADES)}
        ),
        "preprocessing.json": dict(preprocessing) if preprocessing is not None else PREPROCESSING,
        "decision.json": dict(decision) if decision is not None else DECISION,
    }
    if "model.onnx" not in omit:
        (directory / "model.onnx").write_bytes(data)
    if "model.sha256" not in omit:
        text = sha256 if sha256 is not None else f"{hashlib.sha256(data).hexdigest()}  model.onnx\n"
        (directory / "model.sha256").write_text(text, encoding="utf-8")
    for file_name, content in files.items():
        if file_name not in omit:
            _write_json(directory / file_name, content)
    return directory
