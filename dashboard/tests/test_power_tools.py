"""Power tools of phase 3 in the dashboard (SPEC-021 section 3.1): labels, colors and
"sem grau". They never enter the SPC filter (grade-forbidden, ADR-021)."""

from __future__ import annotations

import csv
import io

import pytest

from qc_contracts import GRADE_FORBIDDEN_OBJECT_TYPES, ObjectType
from qc_dashboard import charts, filters
from qc_dashboard import formatting as fm

POWER_TOOL_LABELS = {
    "angle_grinder": "esmerilhadeira",
    "saw": "serra",
    "drill": "furadeira",
    "cordless_screwdriver": "parafusadeira",
}


def _ungraded(factory, object_type: str):
    return factory.inspection(
        object_type=object_type, grade=None, grade_score=None, grade_confidence=None
    )


@pytest.mark.parametrize(("object_type", "label"), POWER_TOOL_LABELS.items())
def test_object_type_label_of_the_power_tools(object_type: str, label: str) -> None:
    assert fm.object_type_label(object_type) == label
    assert fm.object_type_label(ObjectType(object_type)) == label


def test_history_rows_of_a_drill_without_grade(factory) -> None:
    """CA-08 of SPEC-021."""
    (row,) = fm.history_rows([_ungraded(factory, "drill")])
    assert row["Tipo"] == "furadeira"
    assert row["Grau"] == "sem grau"
    assert row["Nota de grau"] == "—" and row["Conf. grau"] == "—"
    assert row["Defeituosa"] == "Não"


def test_history_rows_of_every_power_tool(factory) -> None:
    rows = fm.history_rows([_ungraded(factory, tool) for tool in POWER_TOOL_LABELS])
    assert [row["Tipo"] for row in rows] == list(POWER_TOOL_LABELS.values())
    assert {row["Grau"] for row in rows} == {"sem grau"}


def test_history_csv_writes_sem_grau_for_a_power_tool(factory) -> None:
    items = [_ungraded(factory, "saw"), _ungraded(factory, "unknown")]
    text = fm.history_csv(items).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    assert [(row["Tipo"], row["Grau"]) for row in rows] == [
        ("serra", "sem grau"),
        ("desconhecido", ""),
    ]


def test_chart_order_puts_the_power_tools_before_unknown() -> None:
    order = charts.OBJECT_TYPE_ORDER
    assert order[-5:] == (
        ObjectType.ANGLE_GRINDER,
        ObjectType.SAW,
        ObjectType.DRILL,
        ObjectType.CORDLESS_SCREWDRIVER,
        ObjectType.UNKNOWN,
    )
    assert order.index(ObjectType.PHILLIPS_SCREWDRIVER) < order.index(ObjectType.ANGLE_GRINDER)
    for tool in POWER_TOOL_LABELS:
        assert ObjectType(tool) in charts.OBJECT_TYPE_COLORS


def test_by_object_type_counts_power_tools() -> None:
    (bar,) = charts.by_object_type({"drill": 5, "angle_grinder": 2, "screw": 1}).data
    counts = dict(zip(bar.y, bar.x, strict=True))
    assert counts["furadeira"] == 5 and counts["esmerilhadeira"] == 2
    assert counts["serra"] == 0 and counts["parafusadeira"] == 0 and counts["parafuso"] == 1
    colors = dict(zip(bar.y, bar.marker.color, strict=True))
    assert colors["furadeira"] == charts.OBJECT_TYPE_COLORS[ObjectType.DRILL]


def test_spc_filter_never_offers_a_power_tool() -> None:
    assert not set(filters.SPC_OBJECT_TYPES) & GRADE_FORBIDDEN_OBJECT_TYPES
    assert len(filters.SPC_OBJECT_TYPES) == 7


def test_history_type_filter_offers_the_power_tools() -> None:
    for tool, label in POWER_TOOL_LABELS.items():
        assert label in filters.TYPE_OPTIONS
        assert filters.TYPE_BY_OPTION[label] is ObjectType(tool)
