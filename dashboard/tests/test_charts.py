"""``qc_dashboard.charts``: pure Plotly figures (SPEC-013 §4.3, §4.4, §4.7)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from qc_contracts import GRADE_ORDER, TimeseriesPoint
from qc_dashboard import charts


def test_grade_colors() -> None:
    assert list(charts.GRADE_COLORS) == list(GRADE_ORDER)
    assert list(charts.GRADE_COLORS.values()) == [
        "#1A9850",
        "#66BD63",
        "#E0B000",
        "#F46D43",
        "#A50026",
    ]


def test_grade_distribution_order_zeros_and_colors() -> None:
    fig = charts.grade_distribution({"good": 10, "perfect": 5})
    (bar,) = fig.data
    assert list(bar.x) == ["perfeito", "bom", "mediano", "ruim", "inutilizável"]
    assert list(bar.y) == [5, 10, 0, 0, 0]
    assert list(bar.marker.color) == [charts.GRADE_COLORS[g] for g in GRADE_ORDER]
    assert list(bar.text) == ["5", "10", "0", "0", "0"]
    assert fig.layout.separators == ",."


def test_by_object_type_is_horizontal() -> None:
    fig = charts.by_object_type({"nut": 4})
    (bar,) = fig.data
    assert bar.orientation == "h"
    assert list(bar.y) == ["parafuso", "porca", "desconhecido"]
    assert list(bar.x) == [0, 4, 0]
    assert list(bar.marker.color) == ["#4C78A8", "#72B7B2", "#9D9D9D"]


def _utc(hour: int) -> datetime:
    return datetime(2026, 11, 3, hour, tzinfo=UTC)


def _points() -> list[TimeseriesPoint]:
    return [
        TimeseriesPoint(bucket_start=_utc(1), total=4, defective=1, defect_rate=0.25),
        TimeseriesPoint(bucket_start=_utc(2), total=0, defective=0, defect_rate=None),
    ]


def test_volume_and_defect_rate_traces() -> None:
    fig = charts.volume_and_defect_rate(_points(), "hour")
    names = [trace.name for trace in fig.data]
    assert names == ["Inspeções", "Taxa de defeito"]
    assert fig.data[0].type == "bar"
    assert fig.data[1].type == "scatter"
    assert fig.data[1].mode == "lines+markers"
    assert list(fig.data[0].y) == [4, 0]
    # Hour buckets in local time (UTC-3): 01:00 UTC is 22:00 of the previous day.
    assert fig.data[0].x[0] == datetime(2026, 11, 2, 22, 0)
    assert fig.layout.xaxis.matches == "x2" or fig.layout.xaxis2.matches == "x"
    assert "(UTC)" not in fig.layout.title.text


def test_volume_and_defect_rate_day_uses_utc_date() -> None:
    fig = charts.volume_and_defect_rate(_points(), "day")
    assert fig.data[0].x[0] == date(2026, 11, 3)
    assert "(UTC)" in fig.layout.title.text


def test_p_chart(factory) -> None:
    spc = factory.spc_response()
    fig = charts.p_chart(spc)
    traces = {trace.name: trace for trace in fig.data}
    assert set(traces) == {"p do lote", "LC", "LSC", "LIC", "Fora de controle"}
    assert list(traces["p do lote"].x) == ["L-001", "L-002", "L-003", "L-004"]
    assert traces["p do lote"].mode == "lines+markers"
    out = traces["Fora de controle"]
    assert list(out.x) == ["L-003"]
    assert out.marker.color == "#D62728"
    assert out.marker.symbol == "diamond"
    assert out.marker.size == 12
    assert [a.text for a in fig.layout.annotations] == ["L-003"]
    for name, attr in (("LSC", "ucl"), ("LIC", "lcl")):
        assert traces[name].line.shape == "hv"
        assert traces[name].line.dash == "dash"
        assert list(traces[name].y) == [getattr(p, attr) for p in spc.points]
    assert list(traces["LC"].y) == [0.18] * 4
    assert fig.layout.title.text == "Carta p — origem: real"
    assert fig.layout.xaxis.title.text == "Lote (ordem de início)"
    assert fig.layout.yaxis.title.text == "Proporção de defeituosos (p)"
    assert fig.layout.yaxis.tickformat == ".0%"


def test_p_chart_title_follows_source(factory) -> None:
    fig = charts.p_chart(factory.spc_response(source="simulated"))
    assert fig.layout.title.text == "Carta p — origem: simulado"


def test_p_chart_without_out_of_control_has_no_annotation(factory) -> None:
    spc = factory.spc_response(points=[factory.spc_point("A"), factory.spc_point("B")])
    fig = charts.p_chart(spc)
    assert len(fig.layout.annotations) == 0
    out = next(trace for trace in fig.data if trace.name == "Fora de controle")
    assert list(out.x) == []
