"""Errors raised by the qc_ml data pipeline (SPEC-011 section 3.1)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ManifestProblem:
    """One problem found while validating the dataset (SPEC-011 section 4.1).

    ``file`` is the name of the CSV where the problem was found (``manifest.csv``,
    ``labels_overrides.csv`` or ``exclusions.csv``), never an absolute path. ``line`` is the CSV
    record number (header = 1), or ``None`` when the problem has no single record (for example
    ``orphan_image``).
    """

    code: str
    file: str
    line: int | None
    image_path: str | None
    message: str

    def __str__(self) -> str:
        where = self.file if self.line is None else f"{self.file}:{self.line}"
        subject = f" {self.image_path}:" if self.image_path else ""
        return f"{where}: {self.code}:{subject} {self.message}"


class ManifestError(ValueError):
    """The dataset has one or more problems; ``problems`` lists all of them."""

    def __init__(self, problems: Iterable[ManifestProblem]) -> None:
        self.problems: list[ManifestProblem] = list(problems)
        super().__init__("\n".join(str(p) for p in self.problems))


class SplitError(ValueError):
    """The split cannot be built, read or used (SPEC-011 section 4.4)."""


class SplitIntegrityError(SplitError):
    """A split was used against R-11 (an item in two splits, or the wrong split for a step)."""
