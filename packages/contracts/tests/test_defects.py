import pytest

from qc_contracts import Grade, is_defective


@pytest.mark.parametrize(
    ("grade", "expected"),
    [
        (Grade.PERFECT, False),
        (Grade.GOOD, False),
        (Grade.FAIR, False),
        (Grade.POOR, True),
        (Grade.UNUSABLE, True),
        (None, False),
    ],
)
def test_is_defective(grade: Grade | None, expected: bool) -> None:
    assert is_defective(grade) is expected


@pytest.mark.parametrize(
    ("value", "expected"), [("poor", True), ("unusable", True), ("good", False)]
)
def test_is_defective_accepts_grade_strings(value: str, expected: bool) -> None:
    assert is_defective(value) is expected  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["bogus", "POOR", "", 3])
def test_is_defective_rejects_unknown_values(value: object) -> None:
    with pytest.raises(ValueError):
        is_defective(value)  # type: ignore[arg-type]
