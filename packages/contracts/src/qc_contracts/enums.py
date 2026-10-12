"""Contract enums (docs/architecture.md section 3.1)."""

from enum import StrEnum


class ObjectType(StrEnum):
    """Type of inspected object. The model class ``other`` always maps to ``UNKNOWN``."""

    SCREW = "screw"
    NUT = "nut"
    UNKNOWN = "unknown"


class Grade(StrEnum):
    """Condition grade. Definition order is severity order (0 = best, 4 = worst)."""

    PERFECT = "perfect"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    UNUSABLE = "unusable"


class Source(StrEnum):
    """Origin of an inspection record (R-06)."""

    LIVE = "live"
    SIMULATED = "simulated"


class CaptureMode(StrEnum):
    """Capture mode on the edge gateway (edge only)."""

    INSPECT = "inspect"
    COLLECT = "collect"


GRADE_ORDER: tuple[Grade, ...] = (
    Grade.PERFECT,
    Grade.GOOD,
    Grade.FAIR,
    Grade.POOR,
    Grade.UNUSABLE,
)


def grade_index(grade: Grade) -> int:
    """Return the severity index (0..4) of ``grade``.

    A string equal to a ``Grade`` value is accepted; any other value raises ``ValueError``.
    """
    return GRADE_ORDER.index(Grade(grade))


def grade_from_index(i: int) -> Grade:
    """Return the grade with severity index ``i`` (0..4); otherwise raise ``ValueError``."""
    if isinstance(i, bool) or not isinstance(i, int):
        raise ValueError(f"grade index must be an int in 0..{len(GRADE_ORDER) - 1}, got {i!r}")
    if not 0 <= i < len(GRADE_ORDER):
        raise ValueError(f"grade index must be in 0..{len(GRADE_ORDER) - 1}, got {i}")
    return GRADE_ORDER[i]
