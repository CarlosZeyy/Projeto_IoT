"""``qc_dashboard.charts``: pure Plotly figures (SPEC-013 §4.3, §4.4, §4.7)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

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


# ---------- §4.7: dates in PT-BR and legend below the axes (r2: RV-01/T-02, RV-02/T-01) ----------


def _hourly(count: int, step: timedelta = timedelta(hours=1)) -> list[TimeseriesPoint]:
    start = datetime(2026, 10, 16, 21, tzinfo=UTC)
    return [
        TimeseriesPoint(bucket_start=start + k * step, total=10, defective=1, defect_rate=0.1)
        for k in range(count)
    ]


def _x_axes(fig) -> list:
    return [fig.layout[name] for name in fig.layout if name.startswith("xaxis")]


@pytest.mark.parametrize(
    ("bucket", "expected"),
    [("minute", "%d/%m/%Y %H:%M"), ("hour", "%d/%m/%Y %H:%M"), ("day", "%d/%m/%Y")],
)
def test_series_dates_are_numeric_pt_br(bucket: str, expected: str) -> None:
    fig = charts.volume_and_defect_rate(_hourly(6), bucket)
    axes = _x_axes(fig)
    assert len(axes) == 2  # both panels of the shared x axis
    for axis in axes:
        assert axis.tickformat == expected
        assert axis.hoverformat == expected
    for trace in fig.data:
        assert trace.hovertemplate.startswith(f"%{{x|{expected}}}<br>")
        assert "%{x}" not in trace.hovertemplate


def test_series_date_format_matches_table_format() -> None:
    # The chart and the tables (formatting.fmt_datetime) show the same dd/mm/aaaa HH:MM.
    assert charts.BUCKET_DATE_FORMATS["hour"] == charts.DATETIME_FORMAT == "%d/%m/%Y %H:%M"
    assert charts.DATE_FORMAT == "%d/%m/%Y"


@pytest.mark.parametrize(
    ("bucket", "step", "dtick"),
    [
        ("minute", timedelta(minutes=1), 60_000),
        ("hour", timedelta(hours=1), 3_600_000),
        ("day", timedelta(days=1), 86_400_000),
    ],
)
def test_series_few_buckets_pin_one_tick_per_bucket(
    bucket: str, step: timedelta, dtick: int
) -> None:
    # Without this, Plotly could tick every 30 s or 12 h and repeat the same label.
    fig = charts.volume_and_defect_rate(_hourly(3, step), bucket)
    assert [axis.dtick for axis in _x_axes(fig)] == [dtick, dtick]


def test_series_many_buckets_let_plotly_choose_ticks() -> None:
    fig = charts.volume_and_defect_rate(_hourly(charts.MAX_PINNED_TICKS + 2), "hour")
    assert [axis.dtick for axis in _x_axes(fig)] == [None, None]


def test_series_single_point_and_empty() -> None:
    assert [a.dtick for a in _x_axes(charts.volume_and_defect_rate(_hourly(1), "hour"))] == [
        3_600_000,
        3_600_000,
    ]
    empty = charts.volume_and_defect_rate([], "hour")
    assert [axis.dtick for axis in _x_axes(empty)] == [None, None]
    assert [axis.tickformat for axis in _x_axes(empty)] == ["%d/%m/%Y %H:%M"] * 2


def _assert_legend_below(fig) -> None:
    legend = fig.layout.legend
    assert legend.orientation == "h"
    assert legend.yref == "container"
    assert (legend.y, legend.yanchor) == (0, "bottom")
    assert (legend.xref, legend.x, legend.xanchor) == ("paper", 0, "left")


def test_legend_never_shares_the_title_band(factory) -> None:
    figures = [
        charts.p_chart(factory.spc_response()),
        charts.volume_and_defect_rate(_hourly(6), "hour"),
        charts.grade_distribution({"good": 1}),
        charts.by_object_type({"nut": 1}),
    ]
    for fig in figures:
        _assert_legend_below(fig)
        assert fig.layout.title.text


# ---------- SPEC-028 §4.5 ----------


def test_series_right_margin_fits_the_last_date_label(factory) -> None:
    points = [
        TimeseriesPoint(bucket_start=_utc(hour), total=1, defective=0, defect_rate=0.0)
        for hour in (1, 2, 3)
    ]
    for bucket in ("minute", "hour", "day"):
        fig = charts.volume_and_defect_rate(points, bucket)
        assert fig.layout.margin.r == 60
        assert (fig.layout.margin.l, fig.layout.margin.t, fig.layout.margin.b) == (10, 50, 10)
    assert charts.grade_distribution({}).layout.margin.r == 10
    assert charts.by_object_type({}).layout.margin.r == 10
    assert charts.p_chart(factory.spc_response()).layout.margin.r == 10


def test_plotly_config_hides_the_mode_bar() -> None:
    config = charts.plotly_config()
    assert config == {"displayModeBar": False}
    config["displayModeBar"] = True  # a copy: the constant does not change
    assert charts.plotly_config() == {"displayModeBar": False}
