"""Contract enums (docs/architecture.md section 3.1)."""

from enum import StrEnum


class ObjectType(StrEnum):
    """Type of inspected object. The model class ``other`` always maps to ``UNKNOWN``.

    The hand tools (phase 2, SPEC-016) come after the MVP members, and the power tools (phase 3,
    SPEC-021, identification only) after the hand tools. Every member belongs to exactly one of
    the grade groups below (ADR-021).
    """

    SCREW = "screw"
    NUT = "nut"
    UNKNOWN = "unknown"
    PLIERS = "pliers"
    ADJUSTABLE_WRENCH = "adjustable_wrench"
    ALLEN_KEY = "allen_key"
    FLAT_SCREWDRIVER = "flat_screwdriver"
    PHILLIPS_SCREWDRIVER = "phillips_screwdriver"
    ANGLE_GRINDER = "angle_grinder"
    SAW = "saw"
    DRILL = "drill"
    CORDLESS_SCREWDRIVER = "cordless_screwdriver"


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


# Grade groups of ADR-021 (contract 0.4.0; power tools from 0.6.0): disjoint, and together equal
# to ``set(ObjectType)``. A grade-required type always has a grade; a grade-forbidden type never
# has one (``unknown`` and the power tools, whose inner state is out of scope, PRD section 4.4);
# a grade-optional type may have it or not (the model says which types it grades, in the
# ``ungraded_object_types`` of its ``labels.json``).
GRADE_REQUIRED_OBJECT_TYPES: frozenset[ObjectType] = frozenset({ObjectType.SCREW, ObjectType.NUT})
GRADE_FORBIDDEN_OBJECT_TYPES: frozenset[ObjectType] = frozenset(
    {
        ObjectType.UNKNOWN,
        ObjectType.ANGLE_GRINDER,
        ObjectType.SAW,
        ObjectType.DRILL,
        ObjectType.CORDLESS_SCREWDRIVER,
    }
)
GRADE_OPTIONAL_OBJECT_TYPES: frozenset[ObjectType] = frozenset(
    {
        ObjectType.PLIERS,
        ObjectType.ADJUSTABLE_WRENCH,
        ObjectType.ALLEN_KEY,
        ObjectType.FLAT_SCREWDRIVER,
        ObjectType.PHILLIPS_SCREWDRIVER,
    }
)


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
