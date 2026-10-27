"""PartQC dashboard (SPEC-013): ``uv run --package qc-dashboard streamlit run dashboard/app.py``.

Five pages (Dispositivos from SPEC-018); Visão geral is the default. Every page reads the data
through ``qc-api`` with the read key (ADR-007), never the database.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

VIEWS = Path(__file__).resolve().parent / "views"

st.set_page_config(page_title="PartQC", layout="wide")

pages = [
    st.Page(VIEWS / "visao_geral.py", title="Visão geral", default=True),
    st.Page(VIEWS / "controle_estatistico.py", title="Controle estatístico"),
    st.Page(VIEWS / "historico.py", title="Histórico"),
    st.Page(VIEWS / "sobre_o_modelo.py", title="Sobre o modelo"),
    st.Page(VIEWS / "dispositivos.py", title="Dispositivos"),
]

st.navigation(pages).run()
