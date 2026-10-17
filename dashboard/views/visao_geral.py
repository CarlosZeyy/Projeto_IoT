"""Visão geral: KPIs, grade and type distribution, volume and defect rate (SPEC-013 §4.3)."""

from __future__ import annotations

import streamlit as st

from qc_dashboard import charts, data, filters, formatting

BUCKET_OPTIONS: tuple[str, ...] = ("Minuto", "Hora", "Dia")
BUCKET_BY_OPTION = {"Minuto": "minute", "Hora": "hour", "Dia": "day"}
KEY_BUCKET = "vg_bucket"

st.title("Visão geral")
selected = filters.render_sidebar()
st.caption(filters.source_caption(selected))

with filters.api_guard():
    filters.render_badge(selected)
    summary = data.fetch_summary(selected)

if summary.total == 0:
    st.info("Nenhuma inspeção encontrada para os filtros selecionados.")
    st.stop()

columns = st.columns(5)
columns[0].metric("Inspeções", formatting.fmt_int(summary.total))
columns[1].metric("Taxa de defeito", formatting.fmt_pct(summary.defect_rate))
columns[2].metric("Desconhecidos", formatting.fmt_int(summary.unknown_count))
columns[3].metric("Para revisão", formatting.fmt_int(summary.needs_review_count))
columns[4].metric(
    "Grau médio",
    formatting.fmt_decimal(summary.mean_grade_score, 2),
    help="0 = perfeito … 4 = inutilizável",
)

left, right = st.columns(2)
left.plotly_chart(charts.grade_distribution(summary.by_grade), key="vg_grades")
right.plotly_chart(charts.by_object_type(summary.by_object_type), key="vg_types")

bucket_option = st.radio(
    "Granularidade",
    BUCKET_OPTIONS,
    index=filters.option_index(BUCKET_OPTIONS, KEY_BUCKET, "Hora"),
    horizontal=True,
    key=KEY_BUCKET,
)
filters.remember(KEY_BUCKET, bucket_option)
bucket = BUCKET_BY_OPTION[bucket_option]

with filters.api_guard():
    points = data.fetch_timeseries(selected, bucket)

st.plotly_chart(charts.volume_and_defect_rate(points, bucket), key="vg_series")
