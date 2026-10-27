import pytest

from qc_contracts import (
    GRADE_FORBIDDEN_OBJECT_TYPES,
    GRADE_OPTIONAL_OBJECT_TYPES,
    GRADE_ORDER,
    GRADE_REQUIRED_OBJECT_TYPES,
    CaptureMode,
    Grade,
    ObjectType,
    Source,
    grade_from_index,
    grade_index,
)


def test_enum_values() -> None:
    assert [m.value for m in ObjectType] == [
        "screw",
        "nut",
        "unknown",
        "pliers",
        "adjustable_wrench",
        "allen_key",
        "flat_screwdriver",
        "phillips_screwdriver",
        "angle_grinder",
        "saw",
        "drill",
        "cordless_screwdriver",
    ]
    assert [m.value for m in Grade] == ["perfect", "good", "fair", "poor", "unusable"]
    assert [m.value for m in Source] == ["live", "simulated"]
    assert [m.value for m in CaptureMode] == ["inspect", "collect"]


def test_enums_are_str() -> None:
    assert Grade.FAIR == "fair"
    assert ObjectType("nut") is ObjectType.NUT


def test_grade_order_matches_definition_order() -> None:
    assert tuple(Grade) == GRADE_ORDER
    assert GRADE_ORDER == (Grade.PERFECT, Grade.GOOD, Grade.FAIR, Grade.POOR, Grade.UNUSABLE)


@pytest.mark.parametrize("i", range(5))
def test_grade_index_round_trip(i: int) -> None:
    assert grade_index(grade_from_index(i)) == i


def test_grade_index_values() -> None:
    assert grade_index(Grade.FAIR) == 2
    assert grade_index("poor") == 3
    assert grade_from_index(4) is Grade.UNUSABLE


@pytest.mark.parametrize("i", [-1, 5, 100, True, 2.0, "2"])
def test_grade_from_index_rejects_out_of_range(i: object) -> None:
    with pytest.raises(ValueError):
        grade_from_index(i)  # type: ignore[arg-type]


def test_grade_index_rejects_unknown_string() -> None:
    with pytest.raises(ValueError):
        grade_index("bogus")  # type: ignore[arg-type]


def test_grade_groups() -> None:
    assert {ObjectType.SCREW, ObjectType.NUT} == GRADE_REQUIRED_OBJECT_TYPES
    assert {
        ObjectType.UNKNOWN,
        ObjectType.ANGLE_GRINDER,
        ObjectType.SAW,
        ObjectType.DRILL,
        ObjectType.CORDLESS_SCREWDRIVER,
    } == GRADE_FORBIDDEN_OBJECT_TYPES
    assert {
        ObjectType.PLIERS,
        ObjectType.ADJUSTABLE_WRENCH,
        ObjectType.ALLEN_KEY,
        ObjectType.FLAT_SCREWDRIVER,
        ObjectType.PHILLIPS_SCREWDRIVER,
    } == GRADE_OPTIONAL_OBJECT_TYPES


def test_grade_groups_partition_object_type() -> None:
    groups = (
        GRADE_REQUIRED_OBJECT_TYPES,
        GRADE_FORBIDDEN_OBJECT_TYPES,
        GRADE_OPTIONAL_OBJECT_TYPES,
    )
    for group in groups:
        assert isinstance(group, frozenset)
    assert not GRADE_REQUIRED_OBJECT_TYPES & GRADE_FORBIDDEN_OBJECT_TYPES
    assert not GRADE_REQUIRED_OBJECT_TYPES & GRADE_OPTIONAL_OBJECT_TYPES
    assert not GRADE_FORBIDDEN_OBJECT_TYPES & GRADE_OPTIONAL_OBJECT_TYPES
    assert frozenset().union(*groups) == set(ObjectType)
    assert sum(len(group) for group in groups) == len(ObjectType) == 12


POWER_TOOLS = (
    ObjectType.ANGLE_GRINDER,
    ObjectType.SAW,
    ObjectType.DRILL,
    ObjectType.CORDLESS_SCREWDRIVER,
)


def test_power_tools_come_last_in_order() -> None:
    assert tuple(ObjectType)[-4:] == POWER_TOOLS
    assert list(ObjectType).index(ObjectType.PHILLIPS_SCREWDRIVER) == len(ObjectType) - 5


def test_power_tools_are_never_graded() -> None:
    for object_type in POWER_TOOLS:
        assert object_type in GRADE_FORBIDDEN_OBJECT_TYPES
        assert object_type not in GRADE_OPTIONAL_OBJECT_TYPES
        assert object_type not in GRADE_REQUIRED_OBJECT_TYPES
