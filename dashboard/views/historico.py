"""Histórico: paginated inspections, page filters and CSV of the current page (SPEC-013 §4.5)."""

from __future__ import annotations

import math
import re
from dataclasses import replace

import pandas as pd
import streamlit as st

from qc_contracts import DEVICE_ID_PATTERN, GRADE_ORDER
from qc_dashboard import data, filters, formatting

ALL = "Todos"
GRADE_OPTIONS: tuple[str, ...] = (ALL, *(formatting.grade_label(g) for g in GRADE_ORDER))
GRADE_BY_OPTION = {ALL: None, **{formatting.grade_label(g): g for g in GRADE_ORDER}}
DEFECTIVE_OPTIONS: tuple[str, ...] = (ALL, formatting.YES, formatting.NO)
DEFECTIVE_BY_OPTION = {ALL: None, formatting.YES: True, formatting.NO: False}
PAGE_SIZES: tuple[int, ...] = (25, 50, 100)
DEFAULT_PAGE_SIZE = 50

KEY_GRADE = "hist_grade"
KEY_DEFECTIVE = "hist_defective"
KEY_DEVICE = "hist_device"
KEY_PAGE_SIZE = "hist_page_size"
KEY_OFFSET = "hist_offset"
KEY_QUERY = "hist_query"


def _previous_page(limit: int) -> None:
    st.session_state[KEY_OFFSET] = max(0, st.session_state.get(KEY_OFFSET, 0) - limit)


def _next_page(limit: int) -> None:
    st.session_state[KEY_OFFSET] = st.session_state.get(KEY_OFFSET, 0) + limit


st.title("Histórico")
selected = filters.render_sidebar()
st.caption(filters.source_caption(selected))
badge_slot = st.container()

controls = st.columns(4)
grade_option = controls[0].selectbox(
    "Grau",
    GRADE_OPTIONS,
    index=filters.option_index(GRADE_OPTIONS, KEY_GRADE, ALL),
    key=KEY_GRADE,
)
filters.remember(KEY_GRADE, grade_option)
defective_option = controls[1].selectbox(
    "Defeituosa",
    DEFECTIVE_OPTIONS,
    index=filters.option_index(DEFECTIVE_OPTIONS, KEY_DEFECTIVE, ALL),
    key=KEY_DEFECTIVE,
)
filters.remember(KEY_DEFECTIVE, defective_option)
device_text = controls[2].text_input(
    "Dispositivo", value=filters.recall(KEY_DEVICE, ""), placeholder="ex.: edge-01", key=KEY_DEVICE
)
filters.remember(KEY_DEVICE, device_text)
page_size = controls[3].selectbox(
    "Itens por página",
    PAGE_SIZES,
    index=filters.option_index(PAGE_SIZES, KEY_PAGE_SIZE, DEFAULT_PAGE_SIZE),
    key=KEY_PAGE_SIZE,
)
filters.remember(KEY_PAGE_SIZE, page_size)

device_text = (device_text or "").strip()
device_id = None
if device_text:
    if re.fullmatch(DEVICE_ID_PATTERN, device_text):
        device_id = device_text
    else:
        st.error("Dispositivo inválido")

query = replace(
    selected,
    grade=GRADE_BY_OPTION[grade_option],
    defective=DEFECTIVE_BY_OPTION[defective_option],
    device_id=device_id,
)

# Any filter change (global or of this page, or the page size) goes back to the first page.
if st.session_state.get(KEY_QUERY) != (query, page_size):
    st.session_state[KEY_QUERY] = (query, page_size)
    st.session_state[KEY_OFFSET] = 0
offset = st.session_state.get(KEY_OFFSET, 0)

with filters.api_guard():
    with badge_slot:
        filters.render_badge(query)
    page = data.fetch_inspections(query, page_size, offset)

if not page.items and page.total > 0 and offset > 0:
    # The data shrank under the current page: go back to the first one.
    st.session_state[KEY_OFFSET] = 0
    st.rerun()

if not page.items:
    st.info("Nenhuma inspeção encontrada.")
    st.stop()

page_number = offset // page_size + 1
page_count = max(1, math.ceil(page.total / page_size))
st.caption(f"Página {page_number} de {page_count} — {formatting.fmt_int(page.total)} inspeções")

st.dataframe(
    pd.DataFrame(formatting.history_rows(page.items), columns=list(formatting.HISTORY_COLUMNS)),
    hide_index=True,
)

navigation = st.columns([1, 1, 4])
navigation[0].button(
    "Anterior", disabled=offset == 0, on_click=_previous_page, args=(page_size,), key="hist_prev"
)
navigation[1].button(
    "Próxima",
    disabled=offset + page_size >= page.total,
    on_click=_next_page,
    args=(page_size,),
    key="hist_next",
)
navigation[2].download_button(
    "Baixar CSV (página atual)",
    data=formatting.history_csv(page.items),
    file_name=f"partqc_historico_p{page_number}.csv",
    mime="text/csv",
    key="hist_csv",
)
