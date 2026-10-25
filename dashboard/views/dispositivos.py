"""Dispositivos: each device online or offline, its gateway state and data origin (SPEC-018 §4.5).

The status comes from ``GET /api/v1/devices`` (read through the 30 s cache of ``data``): the API
decides ``online`` (last heartbeat less than 180 s ago, by the server clock). A device whose
latest inspection is ``simulated`` turns on the simulated-data badge of the other pages (R-06).
The global filters of the sidebar do not apply here.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from qc_dashboard import data, filters, formatting

ONLINE_CAPTION = (
    "Online: último heartbeat recebido há menos de 3 min, pela hora do servidor. "
    "Os filtros da barra lateral não se aplicam a esta página."
)
EMPTY_TEXT = "Nenhum dispositivo registrado."

st.title("Dispositivos")
filters.render_sidebar()
st.caption(ONLINE_CAPTION)

with filters.api_guard():
    devices = data.fetch_devices()

if formatting.has_simulated_device(devices):
    filters.show_badge()

if not devices:
    st.info(EMPTY_TEXT)
    st.stop()

st.dataframe(
    pd.DataFrame(formatting.device_rows(devices), columns=list(formatting.DEVICE_COLUMNS)),
    hide_index=True,
)
