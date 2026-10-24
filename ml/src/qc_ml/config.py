"""Training configuration (``TrainConfig``, SPEC-012 section 4.2), without torch.

``qc_ml.train`` re-exports everything here. The class lives in its own module so that the steps
that run without torch (``thresholds``, ``evaluate``, ``pipeline``) can read the same JSON in the
CI, where torch is not installed.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from qc_contracts import MODEL_VERSION_PATTERN
from qc_ml.errors import ConfigError

__all__ = [
    "ALLOWED_BACKBONES",
    "BACKBONE_ACRONYMS",
    "GRADE_HEADS",
    "SKILL_DEFAULTS",
    "ConfigError",
    "TrainConfig",
    "load_config",
]

# N-01 / ADR-004: backbones allowed outside the smoke mode, with the acronym of the version name.
BACKBONE_ACRONYMS: dict[str, str] = {"mobilenetv3_large_100": "mnv3", "efficientnet_b0": "effb0"}
ALLOWED_BACKBONES: tuple[str, ...] = tuple(BACKBONE_ACRONYMS)
GRADE_HEADS: tuple[str, ...] = ("ce", "corn")
EPOCHS_A_RANGE: tuple[int, int] = (5, 10)  # skill ml-pipeline §4, phase A: 5 to 10 epochs

VERSION_NAME_PATTERN = re.compile(r"partqc-[a-z0-9]+(-[a-z0-9]+)*-v[0-9]+")
CONTRACT_VERSION_PATTERN = re.compile(MODEL_VERSION_PATTERN.strip("^$"))

# Fields that have a default in the skill ml-pipeline / SPEC-012 §4.2; a different value is
# allowed and listed in ``deviations_from_defaults``. Paths and the version name are not here.
HYPERPARAMETER_FIELDS: tuple[str, ...] = (
    "backbone",
    "pretrained",
    "grade_head",
    "seed",
    "batch_size",
    "epochs_a",
    "lr_a",
    "epochs_b_max",
    "lr_b",
    "unfreeze_last_blocks",
    "patience",
    "min_delta",
    "label_smoothing",
    "lambda_grade",
    "weight_decay",
    "smoke",
)
REQUIRED_FIELDS: tuple[str, ...] = ("model_version", "dataset_dir", "split_file")


@dataclass(frozen=True)
class TrainConfig:
    """One training run; the JSON lives in ``ml/configs/<model_version>.json``.

    ``__post_init__`` validates every field (``ConfigError``). Paths are kept as given (relative
    paths are relative to the working directory, the repository root in the CLIs).
    """

    model_version: str
    dataset_dir: str
    split_file: str
    backbone: str = "mobilenetv3_large_100"
    pretrained: bool = True
    grade_head: str = "ce"
    seed: int = 42
    batch_size: int = 32
    epochs_a: int = 8
    lr_a: float = 1e-3
    epochs_b_max: int = 30
    lr_b: float = 1e-4
    unfreeze_last_blocks: int = 2
    patience: int = 5
    min_delta: float = 1e-4
    label_smoothing: float = 0.1
    lambda_grade: float = 1.0
    weight_decay: float = 1e-4
    num_workers: int = 2
    models_root: str = "ml/models"
    reports_root: str = "ml/reports"
    checkpoints_root: str = "ml/checkpoints"
    smoke: bool = False
    # SPEC-035 section 4.6: registry passed to load_manifest by train, thresholds and evaluate
    # (None = ml/external_sources.csv). A path, not a hyperparameter.
    external_sources: str | None = None

    def __post_init__(self) -> None:
        problems: list[str] = []
        self._check_types(problems)
        if problems:
            raise ConfigError("; ".join(problems))
        self._check_values(problems)
        if problems:
            raise ConfigError("; ".join(problems))

    # -- validation ------------------------------------------------------------------------

    def _check_types(self, problems: list[str]) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if f.type == "bool":
                ok = isinstance(value, bool)
            elif f.type == "int":
                ok = isinstance(value, int) and not isinstance(value, bool)
            elif f.type == "float":
                ok = isinstance(value, int | float) and not isinstance(value, bool)
                if ok:
                    object.__setattr__(self, f.name, float(value))
            elif f.type == "str | None":
                ok = value is None or isinstance(value, str)
            else:
                ok = isinstance(value, str)
            if not ok:
                problems.append(f"{f.name} must be {f.type}, got {value!r}")

    def _check_values(self, problems: list[str]) -> None:
        if not (
            VERSION_NAME_PATTERN.fullmatch(self.model_version)
            and CONTRACT_VERSION_PATTERN.fullmatch(self.model_version)
        ):
            problems.append(
                "model_version must match ^partqc-[a-z0-9]+(-[a-z0-9]+)*-v\\d+$ and "
                f"{MODEL_VERSION_PATTERN}, got {self.model_version!r}"
            )
        if self.grade_head not in GRADE_HEADS:
            problems.append(f"grade_head must be one of {', '.join(GRADE_HEADS)}")
        if not self.smoke:
            if self.backbone not in ALLOWED_BACKBONES:
                problems.append(
                    f"backbone must be one of {', '.join(ALLOWED_BACKBONES)} (N-01) outside the "
                    f"smoke mode, got {self.backbone!r}"
                )
            low, high = EPOCHS_A_RANGE
            if not low <= self.epochs_a <= high:
                problems.append(
                    f"epochs_a must be in [{low}, {high}] outside the smoke mode, "
                    f"got {self.epochs_a}"
                )
        if not self.backbone:
            problems.append("backbone must not be empty")
        for name in ("batch_size", "patience", "unfreeze_last_blocks"):
            if getattr(self, name) < 1:
                problems.append(f"{name} must be >= 1")
        for name in ("seed", "epochs_a", "epochs_b_max", "num_workers"):
            if getattr(self, name) < 0:
                problems.append(f"{name} must be >= 0")
        if self.epochs_a + self.epochs_b_max < 1:
            problems.append("epochs_a + epochs_b_max must be >= 1")
        for name in ("lr_a", "lr_b"):
            if not getattr(self, name) > 0:
                problems.append(f"{name} must be > 0")
        for name in ("min_delta", "lambda_grade", "weight_decay"):
            if not getattr(self, name) >= 0:
                problems.append(f"{name} must be >= 0")
        if not 0 <= self.label_smoothing < 1:
            problems.append("label_smoothing must be in [0, 1)")
        for name in ("dataset_dir", "split_file", "models_root", "reports_root"):
            if not getattr(self, name):
                problems.append(f"{name} must not be empty")
        if not self.checkpoints_root:
            problems.append("checkpoints_root must not be empty")
        if self.external_sources is not None and not self.external_sources:
            problems.append("external_sources must not be empty (use null for the default)")

    # -- helpers ----------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def deviations_from_defaults(self) -> list[dict[str, Any]]:
        """``[{field, default, value}]`` for every hyperparameter different from its default."""
        defaults = SKILL_DEFAULTS
        return [
            {"field": name, "default": defaults[name], "value": getattr(self, name)}
            for name in HYPERPARAMETER_FIELDS
            if getattr(self, name) != defaults[name]
        ]

    @property
    def model_dir(self) -> Path:
        return Path(self.models_root) / self.model_version

    @property
    def reports_dir(self) -> Path:
        return Path(self.reports_root) / self.model_version

    @property
    def checkpoints_dir(self) -> Path:
        return Path(self.checkpoints_root) / self.model_version


SKILL_DEFAULTS: dict[str, Any] = {
    f.name: f.default for f in fields(TrainConfig) if f.name in HYPERPARAMETER_FIELDS
}


def config_from_dict(data: Any) -> TrainConfig:
    """Build a ``TrainConfig`` from a JSON object; unknown or missing required keys fail."""
    if not isinstance(data, dict):
        raise ConfigError("the configuration must be a JSON object")
    known = {f.name for f in fields(TrainConfig)}
    unknown = sorted(set(data) - known)
    missing = [name for name in REQUIRED_FIELDS if name not in data]
    if unknown or missing:
        raise ConfigError(f"unknown keys {unknown}, missing keys {missing}")
    return TrainConfig(**data)


def load_config(path: Path | str) -> TrainConfig:
    """Read and validate ``path`` (``ConfigError`` for an unreadable or invalid file)."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read the configuration {path}: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    return config_from_dict(data)
