"""Pure Plotly figures (SPEC-013 sections 4.3, 4.4 and 4.7). No Streamlit, no I/O.

The colors per grade are the same everywhere (``GRADE_COLORS``), and color is never the only
channel: bars carry their values and out-of-control points have their own symbol and label.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from qc_contracts import (
    GRADE_ORDER,
    SOURCE_LABELS_PT,
    Grade,
    ObjectType,
    SpcResponse,
    TimeseriesPoint,
)
from qc_dashboard.formatting import (
    DATETIME_FORMAT,
    fmt_datetime,
    fmt_int,
    fmt_pct,
    grade_label,
    object_type_label,
    to_local,
)

GRADE_COLORS: Mapping[Grade, str] = MappingProxyType(
    {
        Grade.PERFECT: "#1A9850",
        Grade.GOOD: "#66BD63",
        Grade.FAIR: "#E0B000",
        Grade.POOR: "#F46D43",
        Grade.UNUSABLE: "#A50026",
    }
)

# Parafuso and porca, then the hand tools (SPEC-016 section 4.5) and desconhecido last.
OBJECT_TYPE_ORDER: tuple[ObjectType, ...] = (
    ObjectType.SCREW,
    ObjectType.NUT,
    ObjectType.PLIERS,
    ObjectType.ADJUSTABLE_WRENCH,
    ObjectType.ALLEN_KEY,
    ObjectType.FLAT_SCREWDRIVER,
    ObjectType.PHILLIPS_SCREWDRIVER,
    ObjectType.UNKNOWN,
)
OBJECT_TYPE_COLORS: Mapping[ObjectType, str] = MappingProxyType(
    {
        ObjectType.SCREW: "#4C78A8",
        ObjectType.NUT: "#72B7B2",
        ObjectType.PLIERS: "#B279A2",
        ObjectType.ADJUSTABLE_WRENCH: "#9D755D",
        ObjectType.ALLEN_KEY: "#FF9DA6",
        ObjectType.FLAT_SCREWDRIVER: "#8CD17D",
        ObjectType.PHILLIPS_SCREWDRIVER: "#2F4B7C",
        ObjectType.UNKNOWN: "#9D9D9D",
    }
)

OUT_OF_CONTROL_COLOR = "#D62728"
LINE_COLOR = "#4C78A8"
LIMIT_COLOR = "#7F7F7F"

# PT-BR number separators in Plotly: decimal comma, thousands dot.
SEPARATORS = ",."

BUCKET_TITLES: Mapping[str, str] = MappingProxyType(
    {
        "minute": "por minuto (hora local)",
        "hour": "por hora (hora local)",
        "day": "por dia (UTC)",
    }
)

# Date axes in PT-BR (§4.7): numeric d3 formats, so Plotly never writes English month names
# (``Oct 16, 2026``). The directives are the same as ``formatting.DATETIME_FORMAT``.
DATE_FORMAT = "%d/%m/%Y"
BUCKET_DATE_FORMATS: Mapping[str, str] = MappingProxyType(
    {"minute": DATETIME_FORMAT, "hour": DATETIME_FORMAT, "day": DATE_FORMAT}
)
BUCKET_MS: Mapping[str, int] = MappingProxyType(
    {"minute": 60_000, "hour": 3_600_000, "day": 86_400_000}
)
# Up to this many buckets on the axis, ticks are pinned to one per bucket; otherwise Plotly
# could put ticks between buckets, and the label format (no seconds, no hours for ``day``)
# would repeat the same text on neighboring ticks.
MAX_PINNED_TICKS = 10

# ``config`` of every ``st.plotly_chart`` (SPEC-028 §4.5): no Plotly mode bar. On touch devices
# Streamlit shows it all the time, over the figure title (RV-08 of
# reviews/SPEC-013/r2-review-report.md). Zoom and PNG export are not required; the full-screen
# button belongs to the Streamlit element toolbar and stays.
PLOTLY_CONFIG: Mapping[str, bool] = MappingProxyType({"displayModeBar": False})


def plotly_config() -> dict[str, bool]:
    """A fresh copy of ``PLOTLY_CONFIG`` for ``st.plotly_chart(config=...)``."""
    return dict(PLOTLY_CONFIG)


# Right margins in px. The series needs room for half of its last ``dd/mm/aaaa HH:MM`` label,
# which is centered on the last tick (RV-09 of reviews/SPEC-013/r2-review-report.md, SPEC-028
# §4.5); the other figures keep the base margin.
MARGIN_RIGHT = 10
SERIES_MARGIN_RIGHT = 60


def _base_layout(fig: go.Figure, title: str) -> go.Figure:
    """Title on top and legend at the bottom of the figure, so the legend never covers the title.

    The legend is anchored to the bottom of the container (``yref="container"``), and Plotly
    reserves that space below the axes; on a narrow screen it wraps downwards, not over the
    title, which carries the origin of the p chart (§4.4, R-06).
    """
    fig.update_layout(
        title={"text": title},
        separators=SEPARATORS,
        margin={"l": 10, "r": MARGIN_RIGHT, "t": 50, "b": 10},
        legend={
            "orientation": "h",
            "xref": "paper",
            "x": 0,
            "xanchor": "left",
            "yref": "container",
            "y": 0,
            "yanchor": "bottom",
        },
    )
    return fig


def grade_distribution(by_grade: Mapping[Grade | str, int]) -> go.Figure:
    """Bars of the 5 grades, always perfeito -> inutilizável (zeros included)."""
    counts = [int(by_grade.get(grade, 0)) for grade in GRADE_ORDER]
    fig = go.Figure(
        go.Bar(
            name="Inspeções",
            x=[grade_label(grade) for grade in GRADE_ORDER],
            y=counts,
            marker={"color": [GRADE_COLORS[grade] for grade in GRADE_ORDER]},
            text=[fmt_int(count) for count in counts],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="Grau: %{x}<br>Inspeções: %{y}<extra></extra>",
        )
    )
    fig.update_xaxes(title={"text": "Grau"})
    fig.update_yaxes(title={"text": "Inspeções"}, rangemode="tozero")
    return _base_layout(fig, "Distribuição por grau")


def by_object_type(by_object_type: Mapping[ObjectType | str, int]) -> go.Figure:
    """Horizontal bars: parafuso, porca, the 5 hand tools and desconhecido."""
    counts = [int(by_object_type.get(object_type, 0)) for object_type in OBJECT_TYPE_ORDER]
    fig = go.Figure(
        go.Bar(
            name="Inspeções",
            orientation="h",
            x=counts,
            y=[object_type_label(object_type) for object_type in OBJECT_TYPE_ORDER],
            marker={"color": [OBJECT_TYPE_COLORS[t] for t in OBJECT_TYPE_ORDER]},
            text=[fmt_int(count) for count in counts],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="Tipo: %{y}<br>Inspeções: %{x}<extra></extra>",
        )
    )
    fig.update_xaxes(title={"text": "Inspeções"}, rangemode="tozero")
    fig.update_yaxes(title={"text": "Tipo"}, autorange="reversed")
    return _base_layout(fig, "Inspeções por tipo")


def volume_and_defect_rate(points: Sequence[TimeseriesPoint], bucket: str) -> go.Figure:
    """Two panels sharing the x axis: ``Inspeções`` (bars) and ``Taxa de defeito`` (line, %).

    Minute and hour buckets are shown in local time; day buckets keep the UTC date (the API
    truncates in UTC), and the title says ``(UTC)``.
    """
    if bucket == "day":
        x = [point.bucket_start.date() for point in points]
    else:
        x = [to_local(point.bucket_start).replace(tzinfo=None) for point in points]
    date_format = BUCKET_DATE_FORMATS.get(bucket, DATETIME_FORMAT)
    hover_date = f"%{{x|{date_format}}}"
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08)
    fig.add_trace(
        go.Bar(
            name="Inspeções",
            x=x,
            y=[point.total for point in points],
            marker={"color": LINE_COLOR},
            hovertemplate=f"{hover_date}<br>Inspeções: %{{y}}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            name="Taxa de defeito",
            mode="lines+markers",
            x=x,
            y=[point.defect_rate for point in points],
            line={"color": GRADE_COLORS[Grade.POOR]},
            hovertemplate=f"{hover_date}<br>Taxa de defeito: %{{y:.1%}}<extra></extra>",
        ),
        row=2,
        col=1,
    )
    # Both x axes (the shared one shows only the bottom ticks, but hover uses both).
    fig.update_xaxes(tickformat=date_format, hoverformat=date_format)
    pinned = _pinned_dtick(points, bucket)
    if pinned is not None:
        fig.update_xaxes(dtick=pinned)
    fig.update_yaxes(title={"text": "Inspeções"}, rangemode="tozero", row=1, col=1)
    fig.update_yaxes(
        title={"text": "Taxa de defeito (%)"}, tickformat=".0%", rangemode="tozero", row=2, col=1
    )
    title = f"Volume e taxa de defeito {BUCKET_TITLES.get(bucket, '')}".strip()
    _base_layout(fig, title)
    fig.update_layout(margin={"r": SERIES_MARGIN_RIGHT})
    return fig


def _pinned_dtick(points: Sequence[TimeseriesPoint], bucket: str) -> int | None:
    """One tick per bucket (in ms) when the axis spans few buckets; ``None`` lets Plotly choose."""
    step = BUCKET_MS.get(bucket)
    if step is None or not points:
        return None
    starts = [point.bucket_start for point in points]
    span_ms = (max(starts) - min(starts)).total_seconds() * 1000
    return step if span_ms <= step * MAX_PINNED_TICKS else None


def p_chart_title(spc: SpcResponse) -> str:
    return f"Carta p — origem: {SOURCE_LABELS_PT[spc.source]}"


def p_chart(spc: SpcResponse) -> go.Figure:
    """p chart of one source (ADR-013): p per lot, LC, LSC/LIC per lot and out-of-control points.

    The x axis is the ``lot_id`` in the order of ``spc.points`` (start order).
    """
    points = spc.points
    lots = [point.lot_id for point in points]
    hover = [
        [
            point.lot_id,
            fmt_int(point.n),
            fmt_int(point.defects),
            fmt_pct(point.p),
            fmt_pct(point.ucl),
            fmt_pct(point.lcl),
            fmt_datetime(point.started_at),
            fmt_datetime(point.ended_at),
        ]
        for point in points
    ]
    hovertemplate = (
        "Lote: %{customdata[0]}<br>n: %{customdata[1]}<br>Defeituosas: %{customdata[2]}"
        "<br>p: %{customdata[3]}<br>LSC: %{customdata[4]}<br>LIC: %{customdata[5]}"
        "<br>Início: %{customdata[6]}<br>Fim: %{customdata[7]}<extra></extra>"
    )
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            name="p do lote",
            mode="lines+markers",
            x=lots,
            y=[point.p for point in points],
            customdata=hover,
            hovertemplate=hovertemplate,
            line={"color": LINE_COLOR},
            marker={"color": LINE_COLOR, "symbol": "circle", "size": 7},
        )
    )
    fig.add_trace(
        go.Scatter(
            name="LC",
            mode="lines",
            x=lots,
            y=[point.cl for point in points],
            line={"color": "#2CA02C"},
            hovertemplate="LC: %{y:.1%}<extra></extra>",
        )
    )
    for name, values in (
        ("LSC", [point.ucl for point in points]),
        ("LIC", [point.lcl for point in points]),
    ):
        fig.add_trace(
            go.Scatter(
                name=name,
                mode="lines",
                x=lots,
                y=values,
                line={"color": LIMIT_COLOR, "dash": "dash", "shape": "hv"},
                hovertemplate=f"{name}: %{{y:.1%}}<extra></extra>",
            )
        )
    out = [(point, row) for point, row in zip(points, hover, strict=True) if point.out_of_control]
    fig.add_trace(
        go.Scatter(
            name="Fora de controle",
            mode="markers",
            x=[point.lot_id for point, _ in out],
            y=[point.p for point, _ in out],
            customdata=[row for _, row in out],
            hovertemplate=hovertemplate,
            marker={"color": OUT_OF_CONTROL_COLOR, "symbol": "diamond", "size": 12},
        )
    )
    for point, _ in out:
        fig.add_annotation(
            x=point.lot_id,
            y=point.p,
            text=point.lot_id,
            showarrow=True,
            arrowhead=2,
            ax=0,
            ay=-30,
            font={"color": OUT_OF_CONTROL_COLOR},
        )
    fig.update_xaxes(
        title={"text": "Lote (ordem de início)"},
        type="category",
        categoryorder="array",
        categoryarray=lots,
    )
    fig.update_yaxes(title={"text": "Proporção de defeituosos (p)"}, tickformat=".0%")
    return _base_layout(fig, p_chart_title(spc))
