"""Sobre o modelo: metrics of the test set against the PRD targets (SPEC-013 §4.6).

Reads the versioned ``metrics.json`` (SPEC-012), not the API. A missing file is the normal state
before the first training, not an error.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from qc_dashboard import config, filters, model_info

st.title("Sobre o modelo")
selected = filters.render_sidebar()
with filters.api_guard():
    filters.render_badge(selected)

path = config.get_model_metrics_path()
try:
    metrics = model_info.load_metrics(path)
except FileNotFoundError:
    st.info(f"Nenhum modelo avaliado ainda: metrics.json não encontrado em {path}.")
    st.stop()
except model_info.MetricsFileError as exc:
    st.error(f"metrics.json inválido: {exc}")
    st.stop()

header = st.columns(4)
header[0].markdown(f"**Versão**  \n{metrics['model_version']}")
header[1].markdown(f"**sha256**  \n`{model_info.short_sha(metrics['model_sha256'])}`")
header[2].markdown(f"**Avaliado em**  \n{model_info.fmt_evaluated_at(metrics['evaluated_at'])}")
header[3].markdown(f"**Split**  \n{metrics['split_file']}")

st.subheader("Métricas × metas do PRD")
st.dataframe(pd.DataFrame(model_info.target_rows(metrics)), hide_index=True)

st.subheader("Demais métricas")
st.dataframe(pd.DataFrame(model_info.other_metric_rows(metrics)), hide_index=True)

st.subheader("Por grau")
st.dataframe(
    pd.DataFrame(model_info.grade_rows(metrics), columns=list(model_info.GRADE_TABLE_COLUMNS)),
    hide_index=True,
)

warnings = metrics.get("warnings")
if isinstance(warnings, list) and warnings:
    st.subheader("Avisos da avaliação")
    st.markdown("\n".join(f"- {text}" for text in warnings))

st.subheader("Matrizes de confusão")
images = st.columns(len(model_info.CONFUSION_IMAGES))
for column, name in zip(images, model_info.CONFUSION_IMAGES, strict=True):
    image = model_info.report_image(metrics["model_version"], name)
    if image is None:
        column.caption("Imagem não disponível")
    else:
        column.image(str(image))

st.caption(
    "Métricas medidas no conjunto de teste, que não é usado para nenhuma escolha (R-11). "
    "As metas do PRD são iniciais."
)
