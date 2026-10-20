"""Controle estatístico: the p chart by lot of one origin (SPEC-013 §4.4, ADR-013, ADR-017).

One SPC request per render, with a single ``source``, and one figure (R-06): the ``live`` and
``simulated`` charts are never drawn together. The chart uses the whole history of the origin;
the sidebar period does not apply.

The badge follows only the chart origin, requested or returned (SPEC-029 §4.2), and the origin
is always written under the title, outside the figure (SPEC-028 §4.3). In a new session the
chart starts in ``Real``; it follows the sidebar (``Simulado`` there -> ``Simulado`` here;
``Real`` or ``Todos`` -> ``Real``), and the user can change it in the "Origem da carta" radio.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from qc_contracts import ObjectType, Source
from qc_dashboard import charts, data, filters, formatting

ORIGIN_REAL = "Real"
ORIGIN_SIMULATED = "Simulado"
ORIGIN_OPTIONS: tuple[str, ...] = (ORIGIN_REAL, ORIGIN_SIMULATED)
SOURCE_BY_ORIGIN = {ORIGIN_REAL: Source.LIVE, ORIGIN_SIMULATED: Source.SIMULATED}

ALL = "Todos"
TYPE_OPTIONS: tuple[str, ...] = (
    ALL,
    formatting.object_type_label(ObjectType.SCREW),
    formatting.object_type_label(ObjectType.NUT),
)
TYPE_BY_OPTION = {
    ALL: None,
    formatting.object_type_label(ObjectType.SCREW): ObjectType.SCREW,
    formatting.object_type_label(ObjectType.NUT): ObjectType.NUT,
}

# Ranges accepted by the API (SPEC-006, SPEC-026).
BASELINE_RANGE = (2, 100, 20)
MIN_LOT_SIZE_RANGE = (1, 500, 5)
MAX_POINTS_RANGE = (2, 500, 100)

KEY_ORIGIN = "spc_source"
KEY_TYPE = "spc_type"
KEY_BASELINE = "spc_baseline_lots"
KEY_MIN_LOT_SIZE = "spc_min_lot_size"
KEY_MAX_POINTS = "spc_max_points"
# Sidebar origin seen on the previous render of this page.
KEY_SIDEBAR_SEEN = "_spc_sidebar_source"

PERIOD_CAPTION = (
    "A carta p usa todo o histórico da origem escolhida; o período da barra lateral não se aplica."
)


def _sync_origin_with_sidebar(sidebar_source: Source | None) -> None:
    """The chart origin follows the sidebar: ``Simulado`` there -> ``Simulado`` here.

    Applied on the first render of the session and whenever the sidebar origin changes; a
    choice made on this page is kept while the sidebar origin stays the same.
    """
    follow = ORIGIN_SIMULATED if sidebar_source is Source.SIMULATED else ORIGIN_REAL
    seen = st.session_state.get(KEY_SIDEBAR_SEEN, "unset")
    if seen == "unset":
        if KEY_ORIGIN not in st.session_state:
            filters.remember(KEY_ORIGIN, follow)
    elif seen != sidebar_source:
        st.session_state[KEY_ORIGIN] = follow
        filters.remember(KEY_ORIGIN, follow)
    st.session_state[KEY_SIDEBAR_SEEN] = sidebar_source


def _number(label: str, key: str, bounds: tuple[int, int, int], column) -> int:
    low, high, default = bounds
    value = column.number_input(
        label,
        min_value=low,
        max_value=high,
        value=int(filters.recall(key, default)),
        step=1,
        key=key,
    )
    value = min(max(int(value), low), high)
    filters.remember(key, value)
    return value


st.title("Controle estatístico")
selected = filters.render_sidebar()
origin_caption_slot = st.empty()
badge_slot = st.container()
st.caption(PERIOD_CAPTION)
_sync_origin_with_sidebar(selected.source)

controls = st.columns(5)
# When the sidebar sync (or the widget itself) already put the value in the session state, that
# value rules and no ``index`` is passed: Streamlit logs a warning (with a stack) when a widget
# gets both a default and a value set through the Session State API.
origin_default = (
    {}
    if KEY_ORIGIN in st.session_state
    else {"index": filters.option_index(ORIGIN_OPTIONS, KEY_ORIGIN, ORIGIN_REAL)}
)
origin = controls[0].radio("Origem da carta", ORIGIN_OPTIONS, key=KEY_ORIGIN, **origin_default)
filters.remember(KEY_ORIGIN, origin)
type_option = controls[1].selectbox(
    "Tipo",
    TYPE_OPTIONS,
    index=filters.option_index(TYPE_OPTIONS, KEY_TYPE, ALL),
    key=KEY_TYPE,
)
filters.remember(KEY_TYPE, type_option)
baseline_lots = _number("Lotes da linha de base", KEY_BASELINE, BASELINE_RANGE, controls[2])
min_lot_size = _number("Tamanho mínimo do lote", KEY_MIN_LOT_SIZE, MIN_LOT_SIZE_RANGE, controls[3])
max_points = _number("Lotes na carta", KEY_MAX_POINTS, MAX_POINTS_RANGE, controls[4])

source = SOURCE_BY_ORIGIN[origin]

# Badge if, and only if, the chart is simulated; no badge check through the API (§4.3).
with badge_slot:
    badge_shown = filters.render_chart_badge(source)
origin_caption_slot.caption(filters.spc_origin_caption(source))

with filters.api_guard():
    spc = data.fetch_spc(
        source, TYPE_BY_OPTION[type_option], baseline_lots, min_lot_size, max_points
    )
origin_caption_slot.caption(filters.spc_origin_caption(spc.source))
# Defence in depth (SPEC-029 §4.2): the origin the API returned also decides the badge, from the
# response already read (no new request), and the badge is never shown twice.
if not badge_shown:
    with badge_slot:
        filters.render_chart_badge(spc.source)

if spc.excluded_lots:
    listed = ", ".join(f"{lot.lot_id} (n={lot.n})" for lot in spc.excluded_lots)
    message = f"Lotes excluídos (n < {spc.min_lot_size}): {listed}"
    total_excluded = spc.excluded_lots_total
    if total_excluded is not None and total_excluded > len(spc.excluded_lots):
        older = total_excluded - len(spc.excluded_lots)
        message += f" e mais {older} lote(s) excluído(s) mais antigo(s)."
    st.info(message)

if not spc.points:
    st.info(
        "Dados insuficientes para a carta p: são necessários pelo menos 2 lotes com "
        f"n ≥ {spc.min_lot_size}."
    )
    st.stop()

valid_total = spc.valid_lots_total
if valid_total is not None and valid_total > len(spc.points):
    st.caption(
        f"Mostrando os últimos {len(spc.points)} de {valid_total} lotes válidos. "
        f"A linha central usa os primeiros {spc.baseline_lots} lotes válidos do histórico."
    )

st.plotly_chart(charts.p_chart(spc), key="spc_chart", config=charts.plotly_config())
st.dataframe(
    pd.DataFrame(formatting.spc_rows(spc), columns=list(formatting.SPC_COLUMNS)),
    hide_index=True,
)
