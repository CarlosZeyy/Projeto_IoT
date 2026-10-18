"""Real inferencer of the edge: ``onnxruntime`` on the CPU (SPEC-008 sections 4.2 and 4.3).

``OnnxInferencer(model_dir)`` loads a model directory with the artifacts of
docs/architecture.md section 7 (``model.onnx``, ``model.sha256``, ``labels.json``,
``preprocessing.json`` and ``decision.json``) and implements the ``Inferencer`` protocol of
SPEC-007. Every load failure is a ``ModelLoadError`` whose message names the file (only its name,
never the full path); ``qc-edge`` logs it and exits with code 2.

The model bytes are read once, in blocks: the SHA-256 is computed over those bytes and the same
bytes are given to ``onnxruntime``, so the file that runs is the one that was checked even if it
changes on disk in between. ``model_version`` is the name of the model directory
(docs/architecture.md section 7).

``infer`` is safe to call from several threads: ``InferenceSession.run`` is thread-safe, and the
preprocessing and the decision are pure functions over immutable state.
"""

from __future__ import annotations

import hashlib
import json
import math
import numbers
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import numpy as np
import onnxruntime
from PIL import Image

from qc_contracts import GRADE_ORDER, MODEL_VERSION_PATTERN, ObjectType
from qc_edge.decision import (
    GRADE_COUNT,
    OTHER_LABEL,
    THRESHOLD_NAMES,
    InvalidModelOutputError,
    ModelLabels,
    Thresholds,
    decide,
)
from qc_edge.inference import InferenceError, InferenceResult, ModelInfo, short_sha
from qc_preprocess import PreprocessParams, preprocess

ThresholdSource = Literal["decision.json", "env"]

MODEL_FILE = "model.onnx"
SHA256_FILE = "model.sha256"
LABELS_FILE = "labels.json"
PREPROCESSING_FILE = "preprocessing.json"
DECISION_FILE = "decision.json"
REQUIRED_FILES = (MODEL_FILE, SHA256_FILE, LABELS_FILE, PREPROCESSING_FILE, DECISION_FILE)

INPUT_NAME = "image"
TYPE_OUTPUT = "type_probs"
GRADE_OUTPUT = "grade_probs"
OUTPUT_NAMES = [TYPE_OUTPUT, GRADE_OUTPUT]
WARMUP_SHAPE = (1, 3, 224, 224)
PROVIDERS = ["CPUExecutionProvider"]

# Environment variable of each threshold override (docs/architecture.md section 6.4).
THRESHOLD_ENV_VARS: dict[str, str] = {
    "type_threshold": "TYPE_THRESHOLD",
    "unusable_threshold": "UNUSABLE_THRESHOLD",
    "grade_review_threshold": "GRADE_REVIEW_THRESHOLD",
}
SOURCE_DECISION_JSON: ThresholdSource = "decision.json"
SOURCE_ENV: ThresholdSource = "env"

EXPECTED_GRADES = [grade.value for grade in GRADE_ORDER]
ALLOWED_OBJECT_TYPES = frozenset(
    {OTHER_LABEL} | {member.value for member in ObjectType if member is not ObjectType.UNKNOWN}
)
_HEX64 = re.compile(r"[0-9a-fA-F]{64}")
_READ_BLOCK = 1 << 20
# model.sha256 is one line (``<hash>  model.onnx``); anything bigger is not a hash file.
_MAX_SHA256_FILE_BYTES = 4096


class ModelLoadError(Exception):
    """The model directory is incomplete or invalid; the message names the file."""


class ModelIntegrityError(ModelLoadError):
    """``model.onnx`` does not match ``model.sha256``."""


def _read_model(path: Path) -> tuple[bytes, str]:
    """``(bytes, sha256 hex)`` of ``model.onnx``, read in blocks."""
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(_READ_BLOCK), b""):
                digest.update(block)
                chunks.append(block)
    except OSError as exc:
        raise ModelLoadError(f"{MODEL_FILE}: cannot read ({exc.strerror or exc})") from None
    return b"".join(chunks), digest.hexdigest()


def _expected_sha256(path: Path) -> str:
    """First token of ``model.sha256`` (``<hash>`` or ``<hash>  model.onnx``), in lowercase."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(_MAX_SHA256_FILE_BYTES + 1)
    except OSError as exc:
        raise ModelLoadError(f"{SHA256_FILE}: cannot read ({exc.strerror or exc})") from None
    if len(raw) > _MAX_SHA256_FILE_BYTES:
        raise ModelLoadError(f"{SHA256_FILE}: too large for a hash file")
    try:
        tokens = raw.decode("ascii").split()
    except UnicodeDecodeError:
        raise ModelLoadError(f"{SHA256_FILE}: not an ASCII text file") from None
    if not tokens or _HEX64.fullmatch(tokens[0]) is None:
        raise ModelLoadError(f"{SHA256_FILE}: the first token must be a 64-character hex SHA-256")
    return tokens[0].lower()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ModelLoadError(f"{path.name}: cannot read ({exc.strerror or exc})") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ModelLoadError(f"{path.name}: not valid UTF-8 JSON") from None


def _require_keys(name: str, data: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    """A JSON object with exactly ``keys`` (an unknown key is refused, like a missing one)."""
    if not isinstance(data, dict):
        raise ModelLoadError(f"{name}: expected a JSON object")
    missing = sorted(set(keys) - data.keys())
    unknown = sorted(data.keys() - set(keys))
    if missing or unknown:
        raise ModelLoadError(f"{name}: missing keys {missing}, unknown keys {unknown}")
    return data


def _load_labels(path: Path) -> ModelLabels:
    """Section 4.2, item 4."""
    data = _require_keys(LABELS_FILE, _read_json(path), ("object_types", "grades"))
    grades = data["grades"]
    if grades != EXPECTED_GRADES:
        raise ModelLoadError(f"{LABELS_FILE}: grades must be exactly {EXPECTED_GRADES}")
    object_types = data["object_types"]
    if not isinstance(object_types, list) or not object_types:
        raise ModelLoadError(f"{LABELS_FILE}: object_types must be a non-empty list")
    for label in object_types:
        if not isinstance(label, str) or label not in ALLOWED_OBJECT_TYPES:
            raise ModelLoadError(
                f"{LABELS_FILE}: object_types may only contain {sorted(ALLOWED_OBJECT_TYPES)}"
            )
    if len(set(object_types)) != len(object_types):
        raise ModelLoadError(f"{LABELS_FILE}: object_types has repeated labels")
    return ModelLabels(object_types=tuple(object_types), grades=tuple(grades))


def _load_preprocessing(path: Path) -> PreprocessParams:
    """Section 4.2, item 5 (``PreprocessParams.from_json`` of SPEC-002)."""
    try:
        return PreprocessParams.from_json(path)
    except OSError as exc:
        raise ModelLoadError(f"{PREPROCESSING_FILE}: cannot read ({exc.strerror or exc})") from None
    except (ValueError, TypeError) as exc:
        # ``from_json`` messages start with the full path; only the file name is kept.
        reason = str(exc).replace(str(path), PREPROCESSING_FILE)
        raise ModelLoadError(f"{PREPROCESSING_FILE}: invalid ({reason})") from None


def _unit_interval(value: Any) -> float | None:
    """``value`` as a float when it is a finite real number in ``[0, 1]``; else ``None``."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        return None
    return number


def _load_decision(path: Path) -> dict[str, float]:
    """Section 4.2, item 6, first half: the three thresholds of ``decision.json``."""
    data = _require_keys(DECISION_FILE, _read_json(path), THRESHOLD_NAMES)
    values: dict[str, float] = {}
    for name in THRESHOLD_NAMES:
        number = _unit_interval(data[name])
        if number is None:
            raise ModelLoadError(f"{DECISION_FILE}: {name} must be a number in [0, 1]")
        values[name] = number
    return values


def _override_name(key: str) -> str:
    """Threshold name of an override key: the variable (``TYPE_THRESHOLD``) or the threshold name
    (``type_threshold``)."""
    for name, variable in THRESHOLD_ENV_VARS.items():
        if key in (name, variable):
            return name
    raise ModelLoadError(
        f"unknown threshold override (expected one of {sorted(THRESHOLD_ENV_VARS.values())})"
    )


def _override_value(variable: str, value: Any) -> float:
    """A number, or a numeric string as in the environment; it must end up in ``[0, 1]``."""
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            value = None
    number = _unit_interval(value)
    if number is None:
        raise ModelLoadError(f"{variable}: must be a number in [0, 1]")
    return number


def _apply_overrides(
    values: dict[str, float], overrides: Mapping[str, Any] | None
) -> dict[str, ThresholdSource]:
    """Section 4.2, item 6, second half; returns the source of each threshold."""
    sources: dict[str, ThresholdSource] = dict.fromkeys(THRESHOLD_NAMES, SOURCE_DECISION_JSON)
    for key, value in (overrides or {}).items():
        name = _override_name(key)
        variable = THRESHOLD_ENV_VARS[name]
        if sources[name] == SOURCE_ENV:
            raise ModelLoadError(f"{variable}: given twice")
        values[name] = _override_value(variable, value)
        sources[name] = SOURCE_ENV
    return sources


def _model_version(model_dir: Path) -> str:
    """Section 4.2, item 3: the directory name (``.`` and ``..`` resolved, links not followed)."""
    name = Path(os.path.abspath(model_dir)).name
    if re.fullmatch(MODEL_VERSION_PATTERN, name) is None:
        raise ModelLoadError(
            f"MODEL_DIR: the directory name is the model_version and must match "
            f"{MODEL_VERSION_PATTERN}"
        )
    return name


def _create_session(model: bytes, type_count: int) -> onnxruntime.InferenceSession:
    """Section 4.2, item 7: CPU session, names, and a warm-up run that checks the shapes."""
    try:
        session = onnxruntime.InferenceSession(model, providers=PROVIDERS)
    except Exception as exc:  # onnxruntime raises its own types, all derived from Exception
        raise ModelLoadError(f"{MODEL_FILE}: onnxruntime cannot load it ({_brief(exc)})") from None
    inputs = [node.name for node in session.get_inputs()]
    if inputs != [INPUT_NAME]:
        raise ModelLoadError(f"{MODEL_FILE}: expected one input named {INPUT_NAME!r}, got {inputs}")
    outputs = {node.name for node in session.get_outputs()}
    missing = [name for name in OUTPUT_NAMES if name not in outputs]
    if missing:
        raise ModelLoadError(f"{MODEL_FILE}: missing outputs {missing}")
    try:
        type_out, grade_out = session.run(
            OUTPUT_NAMES, {INPUT_NAME: np.zeros(WARMUP_SHAPE, dtype=np.float32)}
        )
    except Exception as exc:
        raise ModelLoadError(f"{MODEL_FILE}: warm-up inference failed ({_brief(exc)})") from None
    expected = {TYPE_OUTPUT: (1, type_count), GRADE_OUTPUT: (1, GRADE_COUNT)}
    for name, value in ((TYPE_OUTPUT, type_out), (GRADE_OUTPUT, grade_out)):
        shape = tuple(np.shape(value))
        if shape != expected[name]:
            raise ModelLoadError(
                f"{MODEL_FILE}: {name} has shape {list(shape)} for a batch of 1, expected "
                f"{list(expected[name])} ({LABELS_FILE} has {type_count} object types)"
            )
    return session


def _brief(exc: BaseException) -> str:
    """Exception type and the first line of its message, at most 200 characters."""
    lines = str(exc).strip().splitlines()
    text = f"{type(exc).__name__}: {lines[0]}" if lines else type(exc).__name__
    return text[:200]


def _single_row(name: str, value: Any) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 2 or array.shape[0] != 1:
        raise InvalidModelOutputError(f"{name} has shape {list(array.shape)}, expected [1, n]")
    return array[0]


class OnnxInferencer:
    """``onnxruntime`` (CPU) inferencer over a model directory (SPEC-008).

    Attributes:
        model_info: ``ModelInfo(<directory name>, <sha256 of model.onnx, lowercase>)``.
        labels: class order of the outputs (``labels.json``).
        thresholds: the effective thresholds (``decision.json``, then the overrides).
        threshold_sources: ``{threshold name: "decision.json" | "env"}``.

    ``overrides`` maps ``TYPE_THRESHOLD``, ``UNUSABLE_THRESHOLD`` and ``GRADE_REVIEW_THRESHOLD``
    (or the threshold names, ``type_threshold`` ...) to a number in ``[0, 1]``; a numeric string,
    as read from the environment, is accepted too. The error of an invalid override names the
    variable.

    Raises:
        ModelLoadError: any check of section 4.2 fails (``ModelIntegrityError`` for a hash that
            does not match).
    """

    def __init__(self, model_dir: Path, overrides: dict[str, float] | None = None) -> None:
        model_dir = Path(model_dir)
        if not model_dir.is_dir():
            raise ModelLoadError("MODEL_DIR: not a directory")
        # 1. Every artifact is there.
        missing = [name for name in REQUIRED_FILES if not (model_dir / name).is_file()]
        if missing:
            raise ModelLoadError(f"missing file(s) in MODEL_DIR: {', '.join(missing)}")
        # 2. Integrity, over the very bytes that onnxruntime will load.
        expected = _expected_sha256(model_dir / SHA256_FILE)
        model, actual = _read_model(model_dir / MODEL_FILE)
        if actual != expected:
            raise ModelIntegrityError(
                f"{MODEL_FILE} does not match {SHA256_FILE}: expected {short_sha(expected)}, "
                f"got {short_sha(actual)}"
            )
        # 3. model_version = directory name.
        model_version = _model_version(model_dir)
        # 4 to 6. Labels, preprocessing and thresholds.
        labels = _load_labels(model_dir / LABELS_FILE)
        params = _load_preprocessing(model_dir / PREPROCESSING_FILE)
        values = _load_decision(model_dir / DECISION_FILE)
        sources = _apply_overrides(values, overrides)
        # 7. onnxruntime session and warm-up.
        session = _create_session(model, len(labels.object_types))

        self.model_info = ModelInfo(model_version=model_version, model_sha256=actual)
        self.labels = labels
        self.thresholds = Thresholds(**values)
        self.threshold_sources: dict[str, ThresholdSource] = sources
        self._params = params
        self._session = session

    def infer(self, image: Image.Image) -> InferenceResult:
        """Preprocess, run the model and apply ``decide`` (SPEC-008 section 4.3).

        ``latency_ms`` covers the preprocessing, the model and the decision, not the decoding of
        the image.

        Raises:
            InferenceError: the preprocessing or ``onnxruntime`` failed.
            InvalidModelOutputError: the outputs break the rules of ``decide``.
        """
        start = time.perf_counter()
        try:
            x = preprocess(image, self._params)
        except (TypeError, ValueError) as exc:
            raise InferenceError(f"preprocessing failed ({_brief(exc)})") from None
        try:
            type_out, grade_out = self._session.run(OUTPUT_NAMES, {INPUT_NAME: x})
        except Exception as exc:
            raise InferenceError(f"onnxruntime failed ({_brief(exc)})") from None
        decision = decide(
            _single_row(TYPE_OUTPUT, type_out),
            _single_row(GRADE_OUTPUT, grade_out),
            self.labels,
            self.thresholds,
        )
        latency_ms = round((time.perf_counter() - start) * 1000)
        return InferenceResult(
            object_type=decision.object_type,
            grade=decision.grade,
            grade_score=decision.grade_score,
            type_confidence=decision.type_confidence,
            grade_confidence=decision.grade_confidence,
            needs_review=decision.needs_review,
            latency_ms=latency_ms,
        )
