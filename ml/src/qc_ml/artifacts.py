"""Files of a model directory (``docs/architecture.md`` section 7), without torch.

Names of the files, the ``model.sha256`` format (64 lowercase hex digits + ``\\n``) and the
``labels.json`` reader and writer, shared by ``export``, ``predict``, ``parity``, ``thresholds``
and ``evaluate``.

SPEC-016 section 4.8 (ADR-021): ``labels.json`` may have ``ungraded_object_types`` (a list,
``[]`` when absent); the export always writes it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from qc_contracts import GRADE_FORBIDDEN_OBJECT_TYPES, GRADE_OPTIONAL_OBJECT_TYPES
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
UNGRADED_KEY = "ungraded_object_types"
OPTIONAL_LABEL_KEYS: tuple[str, ...] = (UNGRADED_KEY,)
# ADR-021, decision 4: only these types may be listed as ungraded.
UNGRADABLE_TYPES: frozenset[str] = frozenset(
    member.value for member in GRADE_OPTIONAL_OBJECT_TYPES | GRADE_FORBIDDEN_OBJECT_TYPES
)


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
    """The ``labels.json`` content: ``object_types``, ``grades`` and ``ungraded_object_types``."""
    return {
        "object_types": list(labels.object_types),
        "grades": list(labels.grades),
        UNGRADED_KEY: list(labels.ungraded_object_types),
    }


def head_labels_to_dict(labels: ModelLabels) -> dict[str, list[str]]:
    """Only the class order of the two heads (``object_types`` and ``grades``).

    The ``labels`` of ``training_config.json`` keep this SPEC-012 shape; the ungraded types go to
    its own top-level key ``ungraded_object_types`` (SPEC-016 section 4.8).
    """
    return {"object_types": list(labels.object_types), "grades": list(labels.grades)}


def _string_tuple(name: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
        raise ModelArtifactError(f"labels {name} must be a list of strings")
    return tuple(value)


def as_labels(labels: ModelLabels | Mapping[str, Any] | None) -> ModelLabels:
    """A ``ModelLabels`` from a ``ModelLabels``, a ``labels.json`` mapping or ``None`` (default).

    A mapping must have ``object_types`` and ``grades`` and may have ``ungraded_object_types``
    (absent = ``[]``); any other key is refused.
    """
    if labels is None:
        return DEFAULT_LABELS
    if isinstance(labels, ModelLabels):
        return labels
    if isinstance(labels, Mapping):
        keys = set(labels)
        if not set(LABEL_KEYS) <= keys or keys - set(LABEL_KEYS) - set(OPTIONAL_LABEL_KEYS):
            raise ModelArtifactError(
                f"labels must have the keys {', '.join(LABEL_KEYS)} and may have "
                f"{', '.join(OPTIONAL_LABEL_KEYS)}"
            )
        return ModelLabels(
            object_types=tuple(str(v) for v in labels["object_types"]),
            grades=tuple(str(v) for v in labels["grades"]),
            ungraded_object_types=_string_tuple(UNGRADED_KEY, labels.get(UNGRADED_KEY, [])),
        )
    object_types = getattr(labels, "object_types", None)
    grades = getattr(labels, "grades", None)
    if object_types is None or grades is None:
        raise ModelArtifactError(f"not a labels object: {labels!r}")
    ungraded = getattr(labels, UNGRADED_KEY, ())
    return ModelLabels(tuple(object_types), tuple(grades), tuple(ungraded))


def check_labels(labels: ModelLabels) -> ModelLabels:
    """The grades must be the 5 contract grades in order and the types must include ``other``.

    ``ungraded_object_types`` (SPEC-016, ADR-021): no repetition, every value one of the model
    types and of the grade-optional or grade-forbidden groups of the contract (never ``other``,
    ``screw`` or ``nut``). The messages name the rule, never the values.
    """
    if tuple(labels.grades) != DEFAULT_LABELS.grades:
        raise ModelArtifactError(f"grades must be {list(DEFAULT_LABELS.grades)}")
    if "other" not in labels.object_types or len(set(labels.object_types)) != len(
        labels.object_types
    ):
        raise ModelArtifactError("object_types must be unique and include 'other'")
    ungraded = labels.ungraded_object_types
    if len(set(ungraded)) != len(ungraded):
        raise ModelArtifactError("ungraded_object_types must not repeat a type")
    if not set(ungraded) <= set(labels.object_types):
        raise ModelArtifactError("ungraded_object_types must be types of object_types")
    if not set(ungraded) <= UNGRADABLE_TYPES:
        raise ModelArtifactError(
            "ungraded_object_types may only list types whose grade is optional or forbidden in "
            "the contract (ADR-021)"
        )
    return labels


def write_labels(path: Path, labels: ModelLabels = DEFAULT_LABELS) -> None:
    path.write_text(json.dumps(labels_to_dict(labels), indent=2) + "\n", encoding="utf-8")


def load_labels(path: Path | str) -> ModelLabels:
    """Read ``labels.json`` (``object_types``, ``grades`` and the optional ungraded types)."""
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
