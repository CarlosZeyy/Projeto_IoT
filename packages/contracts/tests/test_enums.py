import pytest

from qc_contracts import (
    GRADE_ORDER,
    CaptureMode,
    Grade,
    ObjectType,
    Source,
    grade_from_index,
    grade_index,
)


def test_enum_values() -> None:
    assert [m.value for m in ObjectType] == ["screw", "nut", "unknown"]
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
