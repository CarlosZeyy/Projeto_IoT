"""Files of a model directory (``docs/architecture.md`` section 7), without torch.

Names of the files, the ``model.sha256`` format (64 lowercase hex digits + ``\\n``) and the
``labels.json`` reader and writer, shared by ``export``, ``predict``, ``parity``, ``thresholds``
and ``evaluate``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from qc_ml.data import DEFAULT_LABELS, ModelLabels
from qc_ml.errors import ModelArtifactError

MODEL_FILE = "model.onnx"
SHA256_FILE = "model.sha256"
LABELS_FILE = "labels.json"
PREPROCESSING_FILE = "preprocessing.json"
DECISION_FILE = "decision.json"
METRICS_FILE = "metrics.json"
TRAINING_CONFIG_FILE = "training_config.json"
PARITY_FILE = "parity_fixture.npz"
THRESHOLDS_REPORT_FILE = "thresholds_report.json"
TYPE_CONFUSION_PNG = "type_confusion.png"
GRADE_CONFUSION_PNG = "grade_confusion.png"

SHA256_TEXT_PATTERN = re.compile(r"[0-9a-f]{64}\n")
LABEL_KEYS: tuple[str, ...] = ("object_types", "grades")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_model_sha256(model_dir: Path, digest: str) -> Path:
    """Write ``model.sha256`` as exactly 64 lowercase hex digits and ``\\n``."""
    text = f"{digest.lower()}\n"
    if not SHA256_TEXT_PATTERN.fullmatch(text):
        raise ModelArtifactError(f"not a SHA-256 hex digest: {digest!r}")
    path = Path(model_dir) / SHA256_FILE
    path.write_text(text, encoding="ascii", newline="")
    return path


def read_model_sha256(model_dir: Path | str) -> str:
    """The digest in ``model.sha256`` (``ModelArtifactError`` if missing or malformed)."""
    path = Path(model_dir) / SHA256_FILE
    try:
        text = path.read_bytes().decode("ascii")
    except FileNotFoundError:
        raise ModelArtifactError(f"{SHA256_FILE} not found in {model_dir}") from None
    except UnicodeDecodeError:
        raise ModelArtifactError(f"{SHA256_FILE} is not ASCII") from None
    if not SHA256_TEXT_PATTERN.fullmatch(text):
        raise ModelArtifactError(
            f"{SHA256_FILE} must hold 64 lowercase hex digits followed by a newline"
        )
    return text[:64]


def read_verified_model(model_dir: Path | str) -> tuple[bytes, str]:
    """``(bytes of model.onnx, digest)`` after checking them against ``model.sha256``.

    The file is read once and the same bytes are hashed and returned, so the model that runs is
    the one that was checked (no time-of-check/time-of-use gap).

    Raises:
        ModelArtifactError: ``model.onnx`` or ``model.sha256`` is missing, malformed or differs.
    """
    model_dir = Path(model_dir)
    model_path = model_dir / MODEL_FILE
    if not model_path.is_file():
        raise ModelArtifactError(f"{MODEL_FILE} not found in {model_dir}")
    expected = read_model_sha256(model_dir)
    data = model_path.read_bytes()
    actual = sha256_bytes(data)
    if actual != expected:
        raise ModelArtifactError(
            f"{MODEL_FILE} does not match {SHA256_FILE} (expected {expected}, got {actual})"
        )
    return data, actual


def labels_to_dict(labels: ModelLabels) -> dict[str, list[str]]:
    return {"object_types": list(labels.object_types), "grades": list(labels.grades)}


def as_labels(labels: ModelLabels | Mapping[str, Any] | None) -> ModelLabels:
    """A ``ModelLabels`` from a ``ModelLabels``, a ``labels.json`` mapping or ``None`` (default)."""
    if labels is None:
        return DEFAULT_LABELS
    if isinstance(labels, ModelLabels):
        return labels
    if isinstance(labels, Mapping):
        if set(labels) != set(LABEL_KEYS):
            raise ModelArtifactError(f"labels must have exactly the keys {', '.join(LABEL_KEYS)}")
        return ModelLabels(
            object_types=tuple(str(v) for v in labels["object_types"]),
            grades=tuple(str(v) for v in labels["grades"]),
        )
    object_types = getattr(labels, "object_types", None)
    grades = getattr(labels, "grades", None)
    if object_types is None or grades is None:
        raise ModelArtifactError(f"not a labels object: {labels!r}")
    return ModelLabels(tuple(object_types), tuple(grades))


def check_labels(labels: ModelLabels) -> ModelLabels:
    """The grades must be the 5 contract grades in order and the types must include ``other``."""
    if tuple(labels.grades) != DEFAULT_LABELS.grades:
        raise ModelArtifactError(f"grades must be {list(DEFAULT_LABELS.grades)}")
    if "other" not in labels.object_types or len(set(labels.object_types)) != len(
        labels.object_types
    ):
        raise ModelArtifactError("object_types must be unique and include 'other'")
    return labels


def write_labels(path: Path, labels: ModelLabels = DEFAULT_LABELS) -> None:
    path.write_text(json.dumps(labels_to_dict(labels), indent=2) + "\n", encoding="utf-8")


def load_labels(path: Path | str) -> ModelLabels:
    """Read ``labels.json`` (exactly ``object_types`` and ``grades``)."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ModelArtifactError(f"{path.name} not found in {path.parent}") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelArtifactError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ModelArtifactError(f"{path.name} must be a JSON object")
    return check_labels(as_labels(data))


def write_json(path: Path, data: Any) -> None:
    """Indented UTF-8 JSON; parent directories are created. ``NaN`` is refused (never JSON)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path.write_text(text, encoding="utf-8")
