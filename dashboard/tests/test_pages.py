"""Pages rendered with ``streamlit.testing.v1.AppTest`` and the mocked API (SPEC-013 §4.2-§4.6).

``api.get_client`` is replaced by a client on ``httpx.MockTransport`` (fixture ``mock_api``).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from qc_dashboard import filters

TIMEOUT = 30
BADGE = "Contém dados simulados"


def run(path: Path, **session: object) -> AppTest:
    at = AppTest.from_file(str(path), default_timeout=TIMEOUT)
    for key, value in session.items():
        at.session_state[key] = value
    return at.run()


def page(factory, name: str) -> Path:
    return factory.views / f"{name}.py"


def texts(elements) -> list[str]:
    return [element.value for element in elements]


def charts(at: AppTest) -> list:
    return at.get("plotly_chart")


def chart_spec(at: AppTest, index: int = 0) -> dict:
    return json.loads(charts(at)[index].proto.spec)


def assert_clean(at: AppTest) -> None:
    assert len(at.exception) == 0, texts(at.exception)


# ---------- app and configuration ----------


def test_app_without_configuration_shows_error(factory, no_config_env, monkeypatch) -> None:
    sent: list[httpx.Request] = []
    monkeypatch.setattr(httpx.Client, "send", lambda self, request, **kw: sent.append(request))
    at = run(factory.app)
    assert_clean(at)
    assert any("Configuração ausente" in text for text in texts(at.error))
    assert sent == []


def test_filters_persist_across_pages(factory, mock_api) -> None:
    at = AppTest.from_file(str(factory.app), default_timeout=TIMEOUT).run()
    assert_clean(at)
    at.sidebar.radio(key=filters.KEY_SOURCE).set_value("Simulado").run()
    at.sidebar.selectbox(key=filters.KEY_TYPE).set_value("porca").run()
    at.switch_page("views/historico.py").run()
    assert_clean(at)
    assert at.sidebar.radio(key=filters.KEY_SOURCE).value == "Simulado"
    assert at.sidebar.selectbox(key=filters.KEY_TYPE).value == "porca"
    assert "Origem dos dados: simulado" in texts(at.caption)
    last = mock_api.to("/inspections")[-1]
    assert last.url.params["source"] == "simulated"
    assert last.url.params["object_type"] == "nut"


# ---------- Visão geral ----------


def test_overview_defaults_to_live(factory, mock_api) -> None:
    at = run(page(factory, "visao_geral"))
    assert_clean(at)
    assert at.sidebar.radio(key=filters.KEY_SOURCE).value == "Real"
    assert mock_api.requests
    assert all(r.url.params["source"] == "live" for r in mock_api.requests)
    assert BADGE not in texts(at.warning)
    assert "Origem dos dados: real" in texts(at.caption)
    assert texts(at.metric) == ["40", "12,5%", "3", "4", "1,85"]
    assert len(charts(at)) == 3


def test_overview_all_sources_badge(factory, mock_api) -> None:
    mock_api.summary_simulated = factory.summary(total=12)
    at = run(page(factory, "visao_geral"), **{filters.KEY_SOURCE: "Todos"})
    assert_clean(at)
    assert BADGE in texts(at.warning)
    assert "Origem dos dados: todas (real + simulado)" in texts(at.caption)
    summaries = mock_api.to("/metrics/summary")
    assert {r.url.params.get("source") for r in summaries} == {None, "simulated"}


def test_overview_all_sources_without_simulated_data(factory, mock_api) -> None:
    at = run(page(factory, "visao_geral"), **{filters.KEY_SOURCE: "Todos"})
    assert_clean(at)
    assert BADGE not in texts(at.warning)


def test_overview_bucket_day(factory, mock_api) -> None:
    at = run(page(factory, "visao_geral"))
    at.radio(key="vg_bucket").set_value("Dia").run()
    assert_clean(at)
    assert mock_api.to("/metrics/timeseries")[-1].url.params["bucket"] == "day"
    spec = chart_spec(at, 2)
    assert [trace["name"] for trace in spec["data"]] == ["Inspeções", "Taxa de defeito"]
    assert [trace["type"] for trace in spec["data"]] == ["bar", "scatter"]


def test_overview_empty(factory, mock_api) -> None:
    mock_api.summary_live = factory.summary(
        total=0,
        defective=0,
        defect_rate=None,
        unknown_count=0,
        needs_review_count=0,
        by_grade={},
        by_object_type={},
        mean_grade_score=None,
    )
    at = run(page(factory, "visao_geral"))
    assert_clean(at)
    assert "Nenhuma inspeção encontrada para os filtros selecionados." in texts(at.info)
    assert charts(at) == []
    assert mock_api.to("/metrics/timeseries") == []


def test_overview_invalid_lot_is_ignored(factory, mock_api) -> None:
    at = run(page(factory, "visao_geral"), **{filters.KEY_LOT: "L 01"})
    assert_clean(at)
    assert "Lote inválido" in texts(at.sidebar.error)
    assert all("lot_id" not in r.url.params for r in mock_api.requests)


def test_overview_valid_lot_is_sent(factory, mock_api) -> None:
    run(page(factory, "visao_geral"), **{filters.KEY_LOT: " L-01 "})
    assert all(r.url.params["lot_id"] == "L-01" for r in mock_api.requests)


# ---------- errors ----------


def _timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


@pytest.mark.parametrize("name", ["visao_geral", "controle_estatistico", "historico"])
def test_timeout_then_retry(factory, mock_api, name: str) -> None:
    mock_api.failure = _timeout
    at = run(page(factory, name))
    assert_clean(at)
    assert "API acordando (free tier), tente em ~1 min" in texts(at.warning)
    assert [b.label for b in at.button] == ["Tentar novamente"]
    mock_api.failure = None
    at.button(key=filters.KEY_RETRY).click().run()
    assert_clean(at)
    assert "API acordando (free tier), tente em ~1 min" not in texts(at.warning)
    assert at.get("plotly_chart") or at.dataframe


def test_badge_check_timeout_on_model_page(factory, mock_api) -> None:
    mock_api.failure = _timeout
    at = run(page(factory, "sobre_o_modelo"), **{filters.KEY_SOURCE: "Todos"})
    assert_clean(at)
    assert "API acordando (free tier), tente em ~1 min" in texts(at.warning)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "Chave de leitura inválida ou ausente (READ_API_KEY)."),
        (403, "Chave de leitura inválida ou ausente (READ_API_KEY)."),
        (500, "Erro da API (HTTP 500)."),
        (422, "Erro da API (HTTP 422)."),
    ],
)
def test_error_messages(factory, mock_api, status: int, message: str) -> None:
    mock_api.failure = lambda request: httpx.Response(status, json={"detail": "x"})
    at = run(page(factory, "visao_geral"))
    assert_clean(at)
    assert texts(at.error) == [message]
    assert charts(at) == []


# ---------- Controle estatístico ----------


def test_spc_defaults(factory, mock_api) -> None:
    at = run(page(factory, "controle_estatistico"))
    assert_clean(at)
    (request,) = mock_api.to("/metrics/spc")
    assert dict(request.url.params) == {
        "source": "live",
        "baseline_lots": "20",
        "min_lot_size": "5",
        "max_points": "100",
    }
    assert len(charts(at)) == 1
    assert chart_spec(at)["layout"]["title"]["text"] == "Carta p — origem: real"
    assert any("período da barra lateral não se aplica" in t for t in texts(at.caption))
    assert BADGE not in texts(at.warning)
    table = at.dataframe[0].value
    assert len(table) == 4
    assert list(table["Fora de controle"]) == ["Não", "Não", "Sim", "Não"]
    assert any("L-009 (n=3)" in text for text in texts(at.info))
    assert not any("Mostrando os últimos" in t for t in texts(at.caption))


def test_spc_type_and_max_points(factory, mock_api) -> None:
    at = run(page(factory, "controle_estatistico"))
    at.selectbox(key="spc_type").set_value("porca").run()
    at.number_input(key="spc_max_points").set_value(10).run()
    assert_clean(at)
    last = mock_api.to("/metrics/spc")[-1]
    assert last.url.params["object_type"] == "nut"
    assert last.url.params["max_points"] == "10"
    widget = at.number_input(key="spc_max_points")
    assert (widget.min, widget.max) == (2, 500)
    assert at.selectbox(key="spc_type").options == ["Todos", "parafuso", "porca"]


def test_spc_simulated_origin(factory, mock_api) -> None:
    at = run(page(factory, "controle_estatistico"))
    at.radio(key="spc_source").set_value("Simulado").run()
    assert_clean(at)
    assert mock_api.to("/metrics/spc")[-1].url.params["source"] == "simulated"
    assert BADGE in texts(at.warning)
    assert len(charts(at)) == 1
    assert chart_spec(at)["layout"]["title"]["text"] == "Carta p — origem: simulado"


def test_spc_one_request_per_render_and_cache(factory, mock_api) -> None:
    at = run(page(factory, "controle_estatistico"))
    at.run()
    assert len(mock_api.to("/metrics/spc")) == 1


def test_spc_follows_simulated_sidebar(factory, mock_api) -> None:
    at = run(page(factory, "controle_estatistico"), **{filters.KEY_SOURCE: "Simulado"})
    assert_clean(at)
    assert [r.url.params["source"] for r in mock_api.to("/metrics/spc")] == ["simulated"]
    assert at.radio(key="spc_source").value == "Simulado"
    at.sidebar.radio(key=filters.KEY_SOURCE).set_value("Real").run()
    assert at.radio(key="spc_source").value == "Real"
    assert mock_api.to("/metrics/spc")[-1].url.params["source"] == "live"


def test_spc_origin_sync_does_not_pass_a_default_with_state(factory, mock_api, monkeypatch) -> None:
    """r2 (RV-03): no ``index`` on the origin radio when its value comes from the state.

    Streamlit logs a stack trace when a widget gets a default and also a value set through the
    Session State API (``check_session_state_rules``). The warning itself is shown once per
    process and needs a running server, so the test records the arguments of the check.
    """
    from streamlit.elements.lib import policies

    seen: list[object] = []
    original = policies.check_session_state_rules

    def spy(default_value, key, writes_allowed=True):
        if key == "spc_source":
            seen.append(default_value)
        return original(default_value, key, writes_allowed)

    monkeypatch.setattr(policies, "check_session_state_rules", spy)
    at = run(page(factory, "controle_estatistico"), **{filters.KEY_SOURCE: "Simulado"})
    assert at.radio(key="spc_source").value == "Simulado"
    seen.clear()
    # The sidebar change writes the radio value through the state (``_sync_origin_with_sidebar``).
    at.sidebar.radio(key=filters.KEY_SOURCE).set_value("Real").run()
    assert_clean(at)
    assert at.radio(key="spc_source").value == "Real"
    assert seen and all(value is None for value in seen)
    at.sidebar.radio(key=filters.KEY_SOURCE).set_value("Simulado").run()
    assert at.radio(key="spc_source").value == "Simulado"
    assert all(value is None for value in seen)
    # The simulated chart was cached on the first render, so no new request is needed.
    assert chart_spec(at)["layout"]["title"]["text"] == "Carta p — origem: simulado"


def test_spc_cut_notices(factory, mock_api) -> None:
    points = [factory.spc_point(f"L-{i:03d}") for i in range(100)]
    excluded = [{"lot_id": f"X-{i:03d}", "n": 1} for i in range(50)]
    mock_api.spc = factory.spc_response(
        points=points, excluded_lots=excluded, valid_lots_total=130, excluded_lots_total=60
    )
    at = run(page(factory, "controle_estatistico"))
    assert_clean(at)
    assert any(
        t.startswith(
            "Mostrando os últimos 100 de 130 lotes válidos. A linha central usa os "
            "primeiros 20 lotes válidos do histórico."
        )
        for t in texts(at.caption)
    )
    assert any(t.endswith(" e mais 10 lote(s) excluído(s) mais antigo(s).") for t in texts(at.info))


@pytest.mark.parametrize(("valid", "excluded"), [(100, 50), (None, None)])
def test_spc_no_cut_notices(factory, mock_api, valid, excluded) -> None:
    points = [factory.spc_point(f"L-{i:03d}") for i in range(100)]
    lots = [{"lot_id": f"X-{i:03d}", "n": 1} for i in range(50)]
    mock_api.spc = factory.spc_response(
        points=points, excluded_lots=lots, valid_lots_total=valid, excluded_lots_total=excluded
    )
    at = run(page(factory, "controle_estatistico"))
    assert_clean(at)
    assert not any("Mostrando os últimos" in t for t in texts(at.caption))
    assert not any("mais antigo(s)" in t for t in texts(at.info))


def test_spc_insufficient_data(factory, mock_api) -> None:
    mock_api.spc = factory.spc_response(
        points=[], p_bar=None, excluded_lots=[], message="Not enough lots", valid_lots_total=1
    )
    at = run(page(factory, "controle_estatistico"))
    assert_clean(at)
    assert any("pelo menos 2 lotes" in text for text in texts(at.info))
    assert not any("Not enough" in text for text in texts(at.info))
    assert charts(at) == []


# ---------- Histórico ----------


def test_history_table_pagination_and_csv(factory, mock_api) -> None:
    mock_api.inspections_total = 120
    at = run(page(factory, "historico"))
    assert_clean(at)
    assert any("Página 1 de 3" in t for t in texts(at.caption))
    assert "Origem dos dados: real" in texts(at.caption)
    table = at.dataframe[0].value
    assert list(table.columns) == [
        "Data/hora",
        "Lote",
        "Dispositivo",
        "Tipo",
        "Grau",
        "Nota de grau",
        "Conf. tipo",
        "Conf. grau",
        "Revisão",
        "Defeituosa",
        "Origem",
        "Modelo",
    ]
    assert mock_api.to("/inspections")[-1].url.params["offset"] == "0"
    assert mock_api.to("/inspections")[-1].url.params["limit"] == "50"
    at.button(key="hist_next").click().run()
    assert_clean(at)
    assert mock_api.to("/inspections")[-1].url.params["offset"] == "50"
    assert any("Página 2 de 3" in t for t in texts(at.caption))
    at.button(key="hist_prev").click().run()
    # Back to the first page: served by the cache, no new request.
    assert any("Página 1 de 3" in t for t in texts(at.caption))
    assert len(mock_api.to("/inspections")) == 2
    (download,) = at.get("download_button")
    assert download.proto.label == "Baixar CSV (página atual)"


def test_history_filter_change_resets_offset(factory, mock_api) -> None:
    mock_api.inspections_total = 120
    at = run(page(factory, "historico"))
    at.button(key="hist_next").click().run()
    at.selectbox(key="hist_grade").set_value("ruim").run()
    last = mock_api.to("/inspections")[-1]
    assert last.url.params["offset"] == "0"
    assert last.url.params["grade"] == "poor"
    at.selectbox(key="hist_defective").set_value("Sim").run()
    assert mock_api.to("/inspections")[-1].url.params["defective"] == "true"
    at.text_input(key="hist_device").set_value("edge-02").run()
    assert mock_api.to("/inspections")[-1].url.params["device_id"] == "edge-02"


def test_history_unknown_simulated_row(factory, mock_api) -> None:
    mock_api.inspections = [
        factory.inspection(
            object_type="unknown",
            grade=None,
            grade_score=None,
            grade_confidence=None,
            source="simulated",
        )
    ]
    at = run(page(factory, "historico"))
    row = at.dataframe[0].value.iloc[0]
    assert (row["Tipo"], row["Grau"], row["Origem"], row["Data/hora"]) == (
        "desconhecido",
        "—",
        "simulado",
        "03/11/2026 12:00",
    )


def test_history_empty(factory, mock_api) -> None:
    mock_api.inspections = []
    at = run(page(factory, "historico"))
    assert_clean(at)
    assert "Nenhuma inspeção encontrada." in texts(at.info)


def test_history_invalid_device_is_ignored(factory, mock_api) -> None:
    at = run(page(factory, "historico"), hist_device="Edge 01")
    assert_clean(at)
    assert "Dispositivo inválido" in texts(at.error)
    assert all("device_id" not in r.url.params for r in mock_api.requests)


# ---------- Sobre o modelo ----------


def test_model_page_valid(factory, no_config_env, monkeypatch, tmp_path) -> None:
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(factory.metrics_document()), encoding="utf-8")
    monkeypatch.setenv("MODEL_METRICS_PATH", str(path))
    at = run(page(factory, "sobre_o_modelo"))
    assert_clean(at)
    targets = at.dataframe[0].value.set_index("Métrica")
    assert targets.loc["Acurácia de tipo", "Status"] == "Atingida"
    assert targets.loc["QWK do grau", "Status"] == "Abaixo da meta"
    assert targets.loc["QWK do grau", "Valor"] == "0,7000"
    assert len(at.dataframe[2].value) == 5
    assert texts(at.caption).count("Imagem não disponível") == 2


def test_model_page_missing_and_invalid(factory, no_config_env, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MODEL_METRICS_PATH", str(tmp_path / "absent.json"))
    at = run(page(factory, "sobre_o_modelo"))
    assert_clean(at)
    assert any(t.startswith("Nenhum modelo avaliado ainda") for t in texts(at.info))

    bad = tmp_path / "bad.json"
    bad.write_text('{"x": 1}', encoding="utf-8")
    monkeypatch.setenv("MODEL_METRICS_PATH", str(bad))
    at = run(page(factory, "sobre_o_modelo"))
    assert_clean(at)
    assert any(t.startswith("metrics.json inválido") for t in texts(at.error))


def test_model_page_simulated_badge(factory, mock_api, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MODEL_METRICS_PATH", str(tmp_path / "absent.json"))
    at = run(page(factory, "sobre_o_modelo"), **{filters.KEY_SOURCE: "Simulado"})
    assert_clean(at)
    assert BADGE in texts(at.warning)
    assert mock_api.requests == []


# =============================================================================================
# SPEC-028
# =============================================================================================

WAKING = "API acordando (free tier), tente em ~1 min"
INSECURE = (
    "Configuração inválida: API_BASE_URL precisa usar https:// (http:// só em localhost ou "
    "127.0.0.1)."
)
API_PAGES = ("visao_geral", "controle_estatistico", "historico")


def _plotly_config(element) -> dict:
    return json.loads(element.proto.config)


# ---------- §4.1: https:// only ----------


@pytest.fixture
def recorded_sends(monkeypatch) -> list[httpx.Request]:
    """Requests that reached the real ``httpx`` client (none expected)."""
    sent: list[httpx.Request] = []

    def send(self, request, **kwargs):
        sent.append(request)
        raise AssertionError("no request expected")

    monkeypatch.setattr(httpx.Client, "send", send)
    return sent


@pytest.mark.parametrize("name", API_PAGES)
def test_insecure_url_stops_api_pages(factory, no_config_env, monkeypatch, recorded_sends, name):
    monkeypatch.setenv("API_BASE_URL", "http://api.example.org")
    monkeypatch.setenv("READ_API_KEY", factory.new_key())
    at = run(page(factory, name))
    assert_clean(at)
    assert texts(at.error) == [INSECURE]
    assert recorded_sends == []
    assert charts(at) == []
    assert not at.dataframe
    assert not any("example.org" in text for text in texts(at.error))


def test_insecure_url_on_the_app(factory, no_config_env, monkeypatch, recorded_sends) -> None:
    monkeypatch.setenv("API_BASE_URL", "ftp://api.example.org")
    monkeypatch.setenv("READ_API_KEY", factory.new_key())
    at = run(factory.app)
    assert_clean(at)
    assert texts(at.error) == [INSECURE]
    assert recorded_sends == []


def test_localhost_http_is_accepted_by_the_pages(factory, no_config_env, monkeypatch) -> None:
    mock = factory.MockApi()
    monkeypatch.setenv("API_BASE_URL", "http://localhost:8001")
    monkeypatch.setenv("READ_API_KEY", factory.new_key())
    original = httpx.Client.__init__

    def init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock.handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", init)
    at = run(page(factory, "visao_geral"))
    assert_clean(at)
    assert not at.error
    assert {r.url.host for r in mock.requests} == {"localhost"}


# ---------- §4.2: retry without clearing the cache ----------


def test_retry_keeps_the_cache(factory, mock_api, monkeypatch) -> None:
    import streamlit as st

    clears: list[None] = []
    original = st.cache_data.clear

    def spy() -> None:
        clears.append(None)
        original()

    monkeypatch.setattr(st.cache_data, "clear", spy)
    mock_api.timing_out = {"/metrics/timeseries"}
    at = run(page(factory, "visao_geral"))
    assert_clean(at)
    assert WAKING in texts(at.warning)
    assert len(charts(at)) == 2  # the two summary figures; the series failed
    mock_api.timing_out = set()
    mock_api.requests.clear()
    at.button(key=filters.KEY_RETRY).click().run()
    assert_clean(at)
    assert clears == []
    assert mock_api.to("/metrics/summary") == []
    assert len(mock_api.to("/metrics/timeseries")) == 1
    assert WAKING not in texts(at.warning)
    assert len(charts(at)) == 3


# ---------- §4.3: badge and origin of the p chart ----------


def _spc_page(factory, sidebar: str) -> AppTest:
    return run(page(factory, "controle_estatistico"), **{filters.KEY_SOURCE: sidebar})


def test_spc_badge_ignores_all_sources_sidebar(factory, mock_api) -> None:
    mock_api.summary_simulated = factory.summary(total=12)
    at = _spc_page(factory, "Todos")
    assert_clean(at)
    assert BADGE not in texts(at.warning)
    assert BADGE not in texts(at.sidebar.caption)
    assert "Origem da carta: real" in texts(at.caption)
    assert [r.url.params["source"] for r in mock_api.to("/metrics/spc")] == ["live"]
    assert mock_api.to("/metrics/summary") == []


def test_spc_badge_with_simulated_chart(factory, mock_api) -> None:
    mock_api.summary_simulated = factory.summary(total=12)
    at = _spc_page(factory, "Simulado")
    assert_clean(at)
    assert BADGE in texts(at.warning)
    assert BADGE in texts(at.sidebar.caption)
    assert "Origem da carta: simulado" in texts(at.caption)
    assert [r.url.params["source"] for r in mock_api.to("/metrics/spc")] == ["simulated"]
    assert mock_api.to("/metrics/summary") == []

    # The chart switched back to Real with the sidebar still in Simulado: no badge.
    at.radio(key="spc_source").set_value("Real").run()
    assert_clean(at)
    assert BADGE not in texts(at.warning)
    assert BADGE not in texts(at.sidebar.caption)
    assert "Origem da carta: real" in texts(at.caption)
    assert mock_api.to("/metrics/spc")[-1].url.params["source"] == "live"
    assert mock_api.to("/metrics/summary") == []


def test_spc_origin_caption_is_right_under_the_title(factory, mock_api) -> None:
    at = run(page(factory, "controle_estatistico"))
    assert_clean(at)
    assert at.main.children[0].value == "Controle estatístico"
    assert at.main.children[1].value == "Origem da carta: real"
    assert texts(at.caption).count("Origem da carta: real") == 1


def test_spc_origin_caption_stays_when_the_api_fails(factory, mock_api) -> None:
    mock_api.failure = _timeout
    at = run(page(factory, "controle_estatistico"), **{filters.KEY_SOURCE: "Simulado"})
    assert_clean(at)
    assert WAKING in texts(at.warning)
    assert BADGE in texts(at.warning)
    assert "Origem da carta: simulado" in texts(at.caption)


# ---------- §4.5: no Plotly mode bar ----------


def test_every_chart_hides_the_mode_bar(factory, mock_api) -> None:
    overview = run(page(factory, "visao_geral"))
    spc = run(page(factory, "controle_estatistico"))
    elements = [*charts(overview), *charts(spc)]
    assert (len(charts(overview)), len(charts(spc))) == (3, 1)
    for element in elements:
        assert _plotly_config(element)["displayModeBar"] is False


# ---------- §4.4: Sobre o modelo ----------


@pytest.fixture
def metrics_path(factory, monkeypatch, tmp_path) -> Path:
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(factory.metrics_document()), encoding="utf-8")
    monkeypatch.setenv("MODEL_METRICS_PATH", str(path))
    return path


def _assert_model_tables(at: AppTest) -> None:
    targets = at.dataframe[0].value.set_index("Métrica")
    assert targets.loc["Acurácia de tipo", "Status"] == "Atingida"
    assert len(at.dataframe[2].value) == 5
    assert any(text.startswith("**Versão**") for text in texts(at.markdown))


def test_model_page_without_api_timeout(factory, mock_api, metrics_path) -> None:
    mock_api.failure = _timeout
    at = run(page(factory, "sobre_o_modelo"), **{filters.KEY_SOURCE: "Todos"})
    assert_clean(at)
    assert WAKING in texts(at.warning)
    assert [b.label for b in at.button] == ["Tentar novamente"]
    assert BADGE in texts(at.warning)
    assert BADGE in texts(at.sidebar.caption)
    _assert_model_tables(at)
    assert len(mock_api.requests) == 1

    # Retry with the API back and no simulated data: no warning, no badge.
    mock_api.failure = None
    at.button(key=filters.KEY_RETRY).click().run()
    assert_clean(at)
    assert WAKING not in texts(at.warning)
    assert BADGE not in texts(at.warning)
    _assert_model_tables(at)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "Chave de leitura inválida ou ausente (READ_API_KEY)."),
        (500, "Erro da API (HTTP 500)."),
    ],
)
def test_model_page_without_api_errors(factory, mock_api, metrics_path, status, message) -> None:
    mock_api.failure = lambda request: httpx.Response(status, json={"detail": "x"})
    at = run(page(factory, "sobre_o_modelo"), **{filters.KEY_SOURCE: "Todos"})
    assert_clean(at)
    assert texts(at.error) == [message]
    assert BADGE in texts(at.warning)
    _assert_model_tables(at)


@pytest.mark.parametrize(
    ("url", "message"),
    [
        (None, "Configuração ausente: defina API_BASE_URL e READ_API_KEY."),
        ("http://api.example.org", INSECURE),
    ],
)
def test_model_page_without_configuration(
    factory, no_config_env, monkeypatch, recorded_sends, metrics_path, url, message
) -> None:
    if url is not None:
        monkeypatch.setenv("API_BASE_URL", url)
        monkeypatch.setenv("READ_API_KEY", factory.new_key())
    at = run(page(factory, "sobre_o_modelo"), **{filters.KEY_SOURCE: "Todos"})
    assert_clean(at)
    assert texts(at.error) == [message]
    assert BADGE in texts(at.warning)
    _assert_model_tables(at)
    assert recorded_sends == []


@pytest.mark.parametrize("source", ["Real", "Simulado"])
def test_model_page_real_or_simulated_needs_no_api(
    factory, no_config_env, recorded_sends, metrics_path, source
) -> None:
    at = run(page(factory, "sobre_o_modelo"), **{filters.KEY_SOURCE: source})
    assert_clean(at)
    assert not at.error
    assert (BADGE in texts(at.warning)) is (source == "Simulado")
    _assert_model_tables(at)
    assert recorded_sends == []


def test_model_page_display_rule(factory, no_config_env, monkeypatch, tmp_path) -> None:
    path = tmp_path / "metrics.json"
    document = factory.metrics_document(
        type_accuracy=0.93127,
        grade_qwk=0.75,
        grade_mae=0.12341,
        latency_ms_p95=120.00001,
        false_unknown_rate=0.02,
        grade_qwk_ci95=[0.61239, 0.78761],
    )
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setenv("MODEL_METRICS_PATH", str(path))
    at = run(page(factory, "sobre_o_modelo"))
    assert_clean(at)
    targets = at.dataframe[0].value.set_index("Métrica")
    assert list(targets.loc["Acurácia de tipo", ["Valor", "Status"]]) == [
        "0,9312",
        "Abaixo da meta",
    ]
    assert list(targets.loc["QWK do grau", ["Valor", "Status"]]) == ["0,7500", "Atingida"]
    assert list(targets.loc["Latência p95 (ms)", ["Valor", "Status"]]) == ["120,0001", "Atingida"]
    others = at.dataframe[1].value.set_index("Métrica")["Valor"]
    assert others["Erro absoluto médio do grau"] == "0,1235"
    assert others["Taxa de falso desconhecido"] == "0,0200"
    assert others["IC 95% do QWK do grau"] == "[0,6123; 0,7877]"


def test_model_page_missing_file_relative_path(factory, no_config_env, monkeypatch) -> None:
    from qc_dashboard import config

    relative = "ml/models/nao-existe-v0/metrics.json"
    monkeypatch.setenv("MODEL_METRICS_PATH", relative)
    at = run(page(factory, "sobre_o_modelo"))
    assert_clean(at)
    expected = f"Nenhum modelo avaliado ainda: metrics.json não encontrado em {relative}."
    assert texts(at.info) == [expected]
    assert not any(str(config.REPO_ROOT) in text for text in texts(at.info))


def test_model_page_missing_file_absolute_path(factory, no_config_env, monkeypatch, tmp_path):
    missing = tmp_path / "fora" / "metrics.json"
    monkeypatch.setenv("MODEL_METRICS_PATH", str(missing))
    at = run(page(factory, "sobre_o_modelo"))
    assert_clean(at)
    expected = f"Nenhum modelo avaliado ainda: metrics.json não encontrado em {missing}."
    assert texts(at.info) == [expected]


# ---------- SPEC-029 §4.2: badge also by the returned chart origin ----------

PERIOD_CAPTION = (
    "A carta p usa todo o histórico da origem escolhida; o período da barra lateral não se aplica."
)


@pytest.mark.parametrize(
    ("sidebar", "returned", "badges", "caption"),
    [
        ("Real", "simulated", 1, "Origem da carta: simulado"),
        ("Real", "live", 0, "Origem da carta: real"),
        ("Simulado", "simulated", 1, "Origem da carta: simulado"),
        ("Todos", "simulated", 1, "Origem da carta: simulado"),
    ],
)
def test_spc_badge_by_returned_origin(
    factory, mock_api, sidebar: str, returned: str, badges: int, caption: str
) -> None:
    from qc_contracts import Source

    mock_api.spc_source = Source(returned)
    at = _spc_page(factory, sidebar)
    assert_clean(at)
    assert texts(at.warning).count(BADGE) == badges
    assert texts(at.sidebar.caption).count(BADGE) == badges
    assert caption in texts(at.caption)
    assert len(mock_api.to("/metrics/spc")) == 1
    assert mock_api.to("/metrics/summary") == []


def test_spc_returned_badge_is_in_the_badge_slot(factory, mock_api) -> None:
    from qc_contracts import Source

    mock_api.spc_source = Source.SIMULATED
    at = run(page(factory, "controle_estatistico"))
    assert_clean(at)
    # Title, origin caption, then the badge slot, before the period caption and the controls.
    assert texts(at.main.children[2].warning) == [BADGE]
    assert at.main.children[3].value == PERIOD_CAPTION


# ---------- SPEC-029 §4.3: invalid port or control character on the pages ----------


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.org:abc",
        "https://api.example.org:99999",
        "http://localhost:abc",
        "http://local\thost:8001",
        "https://api.exa\nmple.org",
        "https://api.example.org\x7f",
        "https://api.exa\x85mple.org",
    ],
)
def test_malformed_url_stops_the_overview(
    factory, no_config_env, monkeypatch, recorded_sends, url: str
) -> None:
    monkeypatch.setenv("API_BASE_URL", url)
    monkeypatch.setenv("READ_API_KEY", factory.new_key())
    at = run(page(factory, "visao_geral"))
    assert_clean(at)
    assert texts(at.error) == [INSECURE]
    assert recorded_sends == []
    assert charts(at) == []
