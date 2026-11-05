"""Hammer, wrench and spirit level in the dashboard (SPEC-044 section 3.1, ADR-025): labels,
order and colors of the chart by type, "sem grau" in the history. They never enter the SPC
filter (grade-forbidden, ADR-021)."""

from __future__ import annotations

import csv
import io

import pytest

from qc_contracts import GRADE_FORBIDDEN_OBJECT_TYPES, ObjectType
from qc_dashboard import charts, filters
from qc_dashboard import formatting as fm

LABELS = {"hammer": "martelo", "wrench": "chave de aperto", "spirit_level": "nível"}
# The SPC filter of SPEC-016 (the API's ``SpcObjectType``): SPEC-044 does not change it.
SPC_TYPES = (
    ObjectType.SCREW,
    ObjectType.NUT,
    ObjectType.PLIERS,
    ObjectType.ADJUSTABLE_WRENCH,
    ObjectType.ALLEN_KEY,
    ObjectType.FLAT_SCREWDRIVER,
    ObjectType.PHILLIPS_SCREWDRIVER,
)


def _ungraded(factory, object_type: str):
    return factory.inspection(
        object_type=object_type, grade=None, grade_score=None, grade_confidence=None
    )


@pytest.mark.parametrize(("object_type", "label"), LABELS.items())
def test_object_type_label_of_the_identified_tools(object_type: str, label: str) -> None:
    assert fm.object_type_label(object_type) == label
    assert fm.object_type_label(ObjectType(object_type)) == label


def test_history_rows_of_a_wrench_without_grade(factory) -> None:
    """CA-09 of SPEC-044 (history part)."""
    (row,) = fm.history_rows([_ungraded(factory, "wrench")])
    assert row["Tipo"] == "chave de aperto"
    assert row["Grau"] == "sem grau"
    assert row["Nota de grau"] == "—" and row["Conf. grau"] == "—"
    assert row["Defeituosa"] == "Não"


def test_history_rows_of_every_identified_tool(factory) -> None:
    rows = fm.history_rows([_ungraded(factory, tool) for tool in LABELS])
    assert [row["Tipo"] for row in rows] == list(LABELS.values())
    assert {row["Grau"] for row in rows} == {"sem grau"}


def test_history_csv_writes_sem_grau_for_a_spirit_level(factory) -> None:
    items = [_ungraded(factory, "spirit_level"), _ungraded(factory, "unknown")]
    text = fm.history_csv(items).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    assert [(row["Tipo"], row["Grau"]) for row in rows] == [
        ("nível", "sem grau"),
        ("desconhecido", ""),
    ]


def test_chart_order_has_every_type_once() -> None:
    """CA-09 of SPEC-044 (order part)."""
    order = charts.OBJECT_TYPE_ORDER
    assert len(order) == len(set(order)) == len(ObjectType) == 15
    assert set(order) == set(ObjectType)


def test_chart_order_puts_the_identified_tools_before_unknown() -> None:
    assert charts.OBJECT_TYPE_ORDER[-4:] == (
        ObjectType.HAMMER,
        ObjectType.WRENCH,
        ObjectType.SPIRIT_LEVEL,
        ObjectType.UNKNOWN,
    )
    order = charts.OBJECT_TYPE_ORDER
    assert order.index(ObjectType.CORDLESS_SCREWDRIVER) < order.index(ObjectType.HAMMER)


def test_chart_colors_are_15_distinct() -> None:
    """CA-09 of SPEC-044 (colors part)."""
    colors = charts.OBJECT_TYPE_COLORS
    assert set(colors) == set(ObjectType)
    assert len(colors) == 15
    assert len({value.upper() for value in colors.values()}) == 15
    assert charts.OUT_OF_CONTROL_COLOR.upper() not in {value.upper() for value in colors.values()}


def test_by_object_type_counts_the_identified_tools() -> None:
    (bar,) = charts.by_object_type({"wrench": 10, "hammer": 2, "screw": 1}).data
    counts = dict(zip(bar.y, bar.x, strict=True))
    assert counts["chave de aperto"] == 10 and counts["martelo"] == 2
    assert counts["nível"] == 0 and counts["parafuso"] == 1
    assert len(counts) == 15
    colors = dict(zip(bar.y, bar.marker.color, strict=True))
    assert colors["chave de aperto"] == charts.OBJECT_TYPE_COLORS[ObjectType.WRENCH]


def test_history_type_filter_offers_the_identified_tools() -> None:
    """CA-09 of SPEC-044 (filter part)."""
    for tool, label in LABELS.items():
        assert label in filters.TYPE_OPTIONS
        assert filters.TYPE_BY_OPTION[label] is ObjectType(tool)


def test_spc_filter_is_unchanged() -> None:
    """CA-09 of SPEC-044: ``SPC_OBJECT_TYPES`` is the one of SPEC-016."""
    assert filters.SPC_OBJECT_TYPES == SPC_TYPES
    assert not set(filters.SPC_OBJECT_TYPES) & GRADE_FORBIDDEN_OBJECT_TYPES
