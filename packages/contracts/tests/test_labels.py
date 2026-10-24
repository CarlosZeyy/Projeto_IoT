from types import MappingProxyType

import pytest

from qc_contracts import (
    CAPTURE_MODE_LABELS_PT,
    GRADE_LABELS_PT,
    OBJECT_TYPE_LABELS_PT,
    SOURCE_LABELS_PT,
    CaptureMode,
    Grade,
    ObjectType,
    Source,
)
from qc_contracts import labels as labels_module

CASES = [
    (GRADE_LABELS_PT, Grade, ["perfeito", "bom", "mediano", "ruim", "inutilizável"]),
    (
        OBJECT_TYPE_LABELS_PT,
        ObjectType,
        [
            "parafuso",
            "porca",
            "desconhecido",
            "alicate",
            "chave inglesa",
            "chave Allen",
            "chave de fenda",
            "chave Phillips",
        ],
    ),
    (SOURCE_LABELS_PT, Source, ["real", "simulado"]),
    (CAPTURE_MODE_LABELS_PT, CaptureMode, ["inspeção", "coleta"]),
]


@pytest.mark.parametrize(("mapping", "enum", "expected"), CASES)
def test_one_label_per_member(mapping, enum, expected) -> None:
    assert isinstance(mapping, MappingProxyType)
    assert list(mapping.keys()) == list(enum)
    assert [mapping[m] for m in enum] == expected


@pytest.mark.parametrize(("mapping", "enum", "expected"), CASES)
def test_labels_are_read_only(mapping, enum, expected) -> None:
    with pytest.raises(TypeError):
        mapping[next(iter(enum))] = "x"


def test_lookup_by_plain_string() -> None:
    assert GRADE_LABELS_PT["unusable"] == "inutilizável"  # type: ignore[index]


def test_labels_module_is_the_same_table() -> None:
    assert labels_module.GRADE_LABELS_PT is GRADE_LABELS_PT
