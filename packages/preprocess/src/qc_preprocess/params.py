"""Preprocessing parameters, saved as ``preprocessing.json`` (architecture.md section 7)."""

import json
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


def _check_positive_int(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive int, got {value!r}")


def _as_triple(name: str, value: Any) -> tuple[float, float, float]:
    if isinstance(value, str | bytes) or not hasattr(value, "__len__") or len(value) != 3:
        raise ValueError(f"{name} must have exactly 3 values, got {value!r}")
    triple = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float) or not math.isfinite(item):
            raise ValueError(f"{name} values must be finite numbers, got {value!r}")
        triple.append(float(item))
    return (triple[0], triple[1], triple[2])


@dataclass(frozen=True)
class PreprocessParams:
    """Resize shorter side to ``resize_shorter``, center-crop ``crop``, normalize per channel."""

    resize_shorter: int = 256
    crop: int = 224
    mean: tuple[float, float, float] = (0.485, 0.456, 0.406)
    std: tuple[float, float, float] = (0.229, 0.224, 0.225)

    def __post_init__(self) -> None:
        _check_positive_int("resize_shorter", self.resize_shorter)
        _check_positive_int("crop", self.crop)
        if self.crop > self.resize_shorter:
            raise ValueError(
                f"crop ({self.crop}) must be <= resize_shorter ({self.resize_shorter})"
            )
        mean = _as_triple("mean", self.mean)
        std = _as_triple("std", self.std)
        if any(s <= 0 for s in std):
            raise ValueError(f"std values must be > 0, got {std!r}")
        # Normalize sequences (e.g. JSON lists) to tuples of float so equality is by value.
        object.__setattr__(self, "mean", mean)
        object.__setattr__(self, "std", std)

    @classmethod
    def from_json(cls, path: Path) -> "PreprocessParams":
        """Load from JSON. A missing or unknown key raises ``ValueError``."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a JSON object")
        expected = {f.name for f in fields(cls)}
        missing = sorted(expected - data.keys())
        unknown = sorted(data.keys() - expected)
        if missing or unknown:
            raise ValueError(f"{path}: missing keys {missing}, unknown keys {unknown}")
        return cls(**data)

    def to_json(self, path: Path) -> None:
        """Write ``{"resize_shorter", "crop", "mean", "std"}`` as JSON."""
        data = asdict(self)
        data["mean"] = list(self.mean)
        data["std"] = list(self.std)
        Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
