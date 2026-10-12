"""Defect rule (ADR-013). This is the only implementation of the rule in the project."""

from qc_contracts.enums import Grade

_DEFECTIVE_GRADES: frozenset[Grade] = frozenset({Grade.POOR, Grade.UNUSABLE})


def is_defective(grade: Grade | None) -> bool:
    """Return ``True`` only for ``poor`` and ``unusable``; ``None`` (unknown object) is ``False``.

    A string equal to a ``Grade`` value is accepted (``Grade`` is a ``StrEnum``); any other
    value raises ``ValueError``.
    """
    if grade is None:
        return False
    return Grade(grade) in _DEFECTIVE_GRADES
