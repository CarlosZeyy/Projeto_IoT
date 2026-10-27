"""Acceptance tests for SPEC-013 (qc-dashboard: Streamlit dashboard).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One ``test_caNN_*`` per automatable CA (CA-26 is manual and is recorded in the
test report). Tests named ``test_extra_*`` are exploratory edge cases around SPEC-013 section 4
that no CA spells out.

Pages are driven through ``streamlit.testing.v1.AppTest``. Only the HTTP boundary is mocked:
``api.get_client`` is replaced by a real ``ApiClient`` over ``httpx.MockTransport``, whose
bodies are built with the ``qc_contracts`` models and which records every request. Read keys
are generated at run time, never written as literals (R-03). No test touches the network, and
no test runs pytest in a subprocess (``docs/architecture.md`` section 10).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import secrets
import shutil
import subprocess
import sys
import traceback
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import plotly.graph_objects as go
import pytest
import streamlit as st
from streamlit.runtime.caching import cache_utils
from streamlit.testing.v1 import AppTest

from qc_contracts import (
    GRADE_LABELS_PT,
    HealthResponse,
    InspectionRead,
    LotSummary,
    MetricsSummary,
    Page,
    SpcResponse,
    TimeseriesPoint,
)
from qc_dashboard import api, charts, data, formatting, model_info
from qc_dashboard.api import ApiAuthError, ApiClient, ApiError, ApiUnavailable
from qc_dashboard.filters import Filters

pytestmark = pytest.mark.acceptance

DASHBOARD = Path(__file__).resolve().parents[2]
REPO_ROOT = DASHBOARD.parent
APP = DASHBOARD / "app.py"
VIEWS = DASHBOARD / "views"
OVERVIEW = VIEWS / "visao_geral.py"
SPC_PAGE = VIEWS / "controle_estatistico.py"
HISTORY = VIEWS / "historico.py"
MODEL_PAGE = VIEWS / "sobre_o_modelo.py"
API_PAGES = (OVERVIEW, SPC_PAGE, HISTORY)

BASE = "https://api.test"
PREFIX = "/api/v1"
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
SHA = "c" * 64
GRADES = ("perfect", "good", "fair", "poor", "unusable")
GRADE_LABELS = ["perfeito", "bom", "mediano", "ruim", "inutilizável"]
GRADE_HEX = ["#1A9850", "#66BD63", "#E0B000", "#F46D43", "#A50026"]
HISTORY_COLUMNS = [
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
SPC_COLUMNS = ["Lote", "Início", "Fim", "n", "Defeituosas", "p", "LC", "LSC", "LIC"]
SPC_COLUMNS = [*SPC_COLUMNS, "Fora de controle"]
BADGE = "Contém dados simulados"
WAKING = "API acordando (free tier), tente em ~1 min"
RETRY = "Tentar novamente"
PERIOD_NOTE = (
    "A carta p usa todo o histórico da origem escolhida; o período da barra lateral não se aplica."
)
CONFIG_VARS = ("API_BASE_URL", "READ_API_KEY", "MODEL_METRICS_PATH")
FORBIDDEN_DEPS = ("torch", "torchvision", "timm", "onnxruntime", "qc-ml", "psycopg", "supabase")


def new_key(prefix: str = "k") -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


# --- contract builders ----------------------------------------------------------------------


def make_summary(**overrides: Any) -> MetricsSummary:
    values: dict[str, Any] = {
        "total": 40,
        "defective": 5,
        "defect_rate": 0.125,
        "unknown_count": 3,
        "needs_review_count": 4,
        "by_grade": {"perfect": 5, "good": 10, "fair": 12, "poor": 3, "unusable": 2},
        "by_object_type": {"screw": 20, "nut": 17, "unknown": 3},
        "mean_type_confidence": 0.91,
        "mean_grade_score": 1.8456,
    }
    values.update(overrides)
    return MetricsSummary.model_validate(values)


def make_inspection(**overrides: Any) -> InspectionRead:
    values: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-001",
        "inspected_at": "2026-11-03T15:00:00Z",
        "object_type": "nut",
        "grade": "poor",
        "grade_score": 2.75,
        "type_confidence": 0.875,
        "grade_confidence": 0.61,
        "needs_review": True,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "latency_ms": 37,
        "source": "live",
        "received_at": "2026-11-03T15:00:02Z",
        "is_defective": True,
    }
    values.update(overrides)
    return InspectionRead.model_validate(values)


def _limits(p_bar: float, n: int) -> tuple[float, float]:
    sigma = (p_bar * (1 - p_bar) / n) ** 0.5
    return min(1.0, p_bar + 3 * sigma), max(0.0, p_bar - 3 * sigma)


def make_point(lot_id: str, n: int, defects: int, *, p_bar: float = 0.18, hour: int = 0) -> dict:
    ucl, lcl = _limits(p_bar, n)
    p = defects / n
    start = datetime(2026, 11, 1, 12, tzinfo=UTC) + timedelta(hours=hour)
    return {
        "lot_id": lot_id,
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(minutes=40)).isoformat(),
        "n": n,
        "defects": defects,
        "p": p,
        "cl": p_bar,
        "ucl": ucl,
        "lcl": lcl,
        "out_of_control": p > ucl or p < lcl,
    }


def four_points() -> list[dict]:
    """L-001..L-004 with p_bar=0.18; only L-003 (25/30) is above its UCL."""
    return [
        make_point("L-001", 25, 4, hour=0),
        make_point("L-002", 40, 7, hour=1),
        make_point("L-003", 30, 25, hour=2),
        make_point("L-004", 20, 3, hour=3),
    ]


def make_spc(**overrides: Any) -> SpcResponse:
    values: dict[str, Any] = {
        "baseline_lots": 20,
        "min_lot_size": 5,
        "source": "live",
        "p_bar": 0.18,
        "points": four_points(),
        "excluded_lots": [{"lot_id": "L-009", "n": 3}],
        "message": None,
        "max_points": 100,
        "valid_lots_total": 4,
        "excluded_lots_total": 1,
    }
    values.update(overrides)
    return SpcResponse.model_validate(values)


def metrics_document(**overrides: Any) -> dict[str, Any]:
    """Every top-level key of SPEC-012 section 4.7, nothing else."""
    doc: dict[str, Any] = {
        "model_version": "partqc-acceptance-v0",
        "model_sha256": "0123456789abcdef" * 4,
        "evaluated_at": "2026-11-20T13:30:00+00:00",
        "split_file": "ml/splits/split_v1.csv",
        "split_sha256": SHA,
        "manifest_sha256": SHA,
        "labels": {"object_types": ["screw", "nut", "other"], "grades": list(GRADES)},
        "decision": {
            "type_threshold": 0.7,
            "unusable_threshold": 0.5,
            "grade_review_threshold": 0.6,
        },
        "type_accuracy": 0.96,
        "type_confusion": [[9, 1, 0], [0, 10, 0], [0, 0, 10]],
        "grade_qwk": 0.70,
        "grade_mae": 0.31,
        "grade_off_by_one_accuracy": 0.93,
        "grade_confusion": [[2 if i == j else 0 for j in range(5)] for i in range(5)],
        "grade_per_class": {
            g: {"precision": 0.8, "recall": 0.75, "f1": 0.7742, "support": 8} for g in GRADES
        },
        "unusable_recall": 0.9,
        "unusable_precision": 0.85,
        "defective_recall": 0.88,
        "defective_precision": 0.9,
        "unknown_rate_on_other": 0.95,
        "false_unknown_rate": 0.02,
        "needs_review_rate": 0.1,
        "latency_ms_p50": 40.5,
        "latency_ms_p95": 120.0,
        "latency_machine": "notebook-borda",
        "latency_runs": 100,
        "counts": {},
        "grade_qwk_ci95": [0.6, 0.78],
        "unusable_recall_ci95": [0.8, 0.97],
        "defective_recall_ci95": None,
        "n_items_test_by_grade": {g: 4 for g in GRADES},
        "warnings": [],
    }
    doc.update(overrides)
    return doc


# --- the HTTP boundary ----------------------------------------------------------------------


class FakeApi:
    """Answers the ``/api/v1`` read routes with contract bodies and records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.summaries: dict[str | None, MetricsSummary] = {
            None: make_summary(),
            "live": make_summary(),
            "simulated": make_summary(total=0, defective=0, defect_rate=None),
        }
        self.series: list[TimeseriesPoint] = [
            TimeseriesPoint(
                bucket_start=datetime(2026, 11, 3, 15, tzinfo=UTC),
                total=10,
                defective=2,
                defect_rate=0.2,
            ),
            TimeseriesPoint(
                bucket_start=datetime(2026, 11, 3, 16, tzinfo=UTC),
                total=6,
                defective=0,
                defect_rate=0.0,
            ),
        ]
        self.spc: dict[str, Any] = make_spc().model_dump(mode="json")
        self.echo_spc_source = True
        self.items: list[InspectionRead] = [make_inspection()]
        self.items_total: int | None = None
        self.failure: Callable[[httpx.Request], httpx.Response] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure is not None:
            return self.failure(request)
        path = request.url.path
        params = request.url.params
        if path == f"{PREFIX}/health":
            body = HealthResponse(
                status="ok", db="ok", api_version="0.1.0", contract_version="0.3.0"
            )
            return httpx.Response(200, json=body.model_dump(mode="json"))
        if path == f"{PREFIX}/metrics/summary":
            return httpx.Response(
                200, json=self.summaries[params.get("source")].model_dump(mode="json")
            )
        if path == f"{PREFIX}/metrics/timeseries":
            return httpx.Response(200, json=[p.model_dump(mode="json") for p in self.series])
        if path == f"{PREFIX}/metrics/spc":
            body = dict(self.spc)
            if self.echo_spc_source:
                body["source"] = params["source"]
            return httpx.Response(200, json=body)
        if path == f"{PREFIX}/inspections":
            page = Page[InspectionRead](
                items=self.items,
                total=len(self.items) if self.items_total is None else self.items_total,
                limit=int(params["limit"]),
                offset=int(params["offset"]),
            )
            return httpx.Response(200, json=page.model_dump(mode="json"))
        if path == f"{PREFIX}/lots":
            lot = LotSummary(
                lot_id="L-001",
                n=10,
                defects=1,
                unknown_count=0,
                started_at=datetime(2026, 11, 3, 15, tzinfo=UTC),
                ended_at=datetime(2026, 11, 3, 16, tzinfo=UTC),
                sources=["live"],
            )
            page = Page[LotSummary](items=[lot], total=1, limit=50, offset=0)
            return httpx.Response(200, json=page.model_dump(mode="json"))
        return httpx.Response(404, json={"detail": "Not Found"})

    def to(self, route: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == PREFIX + route]

    def reset(self) -> None:
        self.requests.clear()


def timeout_failure(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


class NoSecretsFile:
    """Behaves like ``st.secrets`` when there is no ``secrets.toml`` anywhere (SPEC-029 §4.1).

    Same pattern as ``NoSecretsFile`` in ``test_spec_028.py``, copied so that this file does not
    import another test module.
    """

    def __contains__(self, key: object) -> bool:
        raise FileNotFoundError("No secrets found")

    def __getitem__(self, key: str) -> object:
        raise FileNotFoundError("No secrets found")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """No config from the environment, no secrets file, clean Streamlit caches."""
    for name in CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(st, "secrets", NoSecretsFile())
    st.cache_data.clear()
    st.cache_resource.clear()
    yield
    st.cache_data.clear()
    st.cache_resource.clear()


@pytest.fixture
def key() -> str:
    return new_key()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, key: str) -> FakeApi:
    """A ``FakeApi`` behind the single client factory ``api.get_client``."""
    mock = FakeApi()
    client = ApiClient(BASE, key, transport=httpx.MockTransport(mock.handler))
    monkeypatch.setattr(api, "get_client", lambda: client)
    return mock


@pytest.fixture
def metrics_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Callable[[Any], Path]:
    def write(content: Any) -> Path:
        path = tmp_path / "metrics.json"
        path.write_text(content if isinstance(content, str) else json.dumps(content), "utf-8")
        monkeypatch.setenv("MODEL_METRICS_PATH", str(path))
        return path

    return write


# --- AppTest helpers --------------------------------------------------------------------------


def page(path: Path) -> AppTest:
    return AppTest.from_file(str(path), default_timeout=60)


def run(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def with_sidebar_source(path: Path, option: str, fake: FakeApi) -> AppTest:
    """First render with defaults, then pick ``option`` in the sidebar; requests reset."""
    at = run(page(path))
    fake.reset()
    at.sidebar.radio(key="flt_source").set_value(option)
    return run(at)


def values(elements: Any) -> list[str]:
    return [str(e.value) for e in elements]


def plotly_figures(at: AppTest) -> list[dict[str, Any]]:
    return [json.loads(el.proto.spec) for el in at.get("plotly_chart")]


def figure_title(fig: dict[str, Any]) -> str:
    title = fig["layout"].get("title", {})
    return title.get("text", "") if isinstance(title, dict) else str(title)


def frames(at: AppTest) -> list[Any]:
    return [el.value for el in [*at.dataframe, *at.table]]


def _protos(node: Any) -> list[str]:
    out: list[str] = []
    proto = getattr(node, "proto", None)
    if proto is not None:
        out.append(str(proto))
    children = getattr(node, "children", None)
    if isinstance(children, dict):
        for child in children.values():
            out.extend(_protos(child))
    return out


def dump(at: AppTest) -> str:
    """Every element of the page (main and sidebar) as protobuf text."""
    return "\n".join(_protos(at.main) + _protos(at.sidebar))


def all_text(at: AppTest) -> list[str]:
    """Visible texts from the usual elements (markdown, captions, alerts, metrics)."""
    texts: list[str] = []
    for kind in ("markdown", "caption", "info", "warning", "error", "success", "title"):
        texts.extend(values(getattr(at, kind)))
    texts.extend(values(at.header))
    texts.extend(values(at.subheader))
    return texts


def contains(texts: list[str], needle: str) -> bool:
    return any(needle in t for t in texts)


# =============================================================================================
# CA-01 to CA-04: API client
# =============================================================================================


def test_ca01_summary_request_url_header_and_model(key: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=make_summary().model_dump(mode="json"))

    client = ApiClient("https://api.test", key, transport=httpx.MockTransport(handler))
    result = client.summary(Filters(source="live"))

    assert len(seen) == 1
    request = seen[0]
    assert request.method == "GET"
    assert str(request.url) == "https://api.test/api/v1/metrics/summary?source=live"
    assert request.headers["X-API-Key"] == key
    assert isinstance(result, MetricsSummary)
    assert result == make_summary()


def _all_calls(client: ApiClient) -> dict[str, Callable[[], Any]]:
    return {
        "health": client.health,
        "summary": lambda: client.summary(Filters(source="live")),
        "timeseries": lambda: client.timeseries(Filters(), "hour"),
        "spc": lambda: client.spc("live", None, 20, 5, 100),
        "inspections": lambda: client.inspections(Filters(), 50, 0),
        "lots": lambda: client.lots(Filters()),
    }


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(timeout_failure, id="read-timeout"),
        pytest.param(lambda r: httpx.Response(503, json={"detail": "Service"}), id="503"),
    ],
)
def test_ca02_timeout_and_503_are_unavailable(key: str, failure: Callable) -> None:
    client = ApiClient(BASE, key, transport=httpx.MockTransport(failure))
    for name, call in _all_calls(client).items():
        with pytest.raises(ApiUnavailable):
            call()
        assert name  # every method maps the failure


def test_ca02_client_timeout_is_ten_seconds(key: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=make_summary().model_dump(mode="json"))

    client = ApiClient(BASE, key, transport=httpx.MockTransport(handler))
    client.summary(Filters())
    # The timeout httpx applied to the request itself (connect/read/write/pool).
    assert seen[0].extensions["timeout"] == {
        "connect": 10.0,
        "read": 10.0,
        "write": 10.0,
        "pool": 10.0,
    }


def test_ca03_auth_server_error_and_invalid_body(key: str) -> None:
    def client_for(response: httpx.Response) -> ApiClient:
        return ApiClient(BASE, key, transport=httpx.MockTransport(lambda r: response))

    with pytest.raises(ApiAuthError):
        client_for(httpx.Response(401, json={"detail": "Missing or invalid API key"})).summary(
            Filters()
        )
    with pytest.raises(ApiError) as server:
        client_for(httpx.Response(500, json={"detail": "Internal Server Error"})).summary(Filters())
    assert server.value.status == 500
    assert not isinstance(server.value, ApiAuthError | ApiUnavailable)
    with pytest.raises(ApiError) as body:
        client_for(httpx.Response(200, json={"foo": 1})).summary(Filters())
    assert not isinstance(body.value, ApiAuthError | ApiUnavailable)


def _chain_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc)) + repr(exc) + str(exc) + repr(exc.args)


def test_ca04_key_never_in_logs_or_exceptions(caplog: pytest.LogCaptureFixture) -> None:
    secret = new_key("k-secret")
    caplog.set_level(logging.DEBUG)
    ok = ApiClient(
        BASE,
        secret,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=make_summary().model_dump(mode="json"))
        ),
    )
    ok.summary(Filters(source="live"))
    denied = ApiClient(
        BASE,
        secret,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(401, json={"detail": "Missing or invalid API key"})
        ),
    )
    with pytest.raises(ApiAuthError) as info:
        denied.summary(Filters(source="live"))

    assert secret not in caplog.text
    for record in caplog.records:
        assert secret not in record.getMessage()
        assert secret not in repr(record.args)
    assert secret not in str(info.value)
    assert secret not in _chain_text(info.value)
    assert secret not in repr(ok)
    assert secret not in repr(denied)


# =============================================================================================
# CA-05 to CA-08: configuration, default origin and the simulated badge (R-06)
# =============================================================================================


def test_ca05_missing_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # no .streamlit/secrets.toml here nor in HOME
    sent: list[httpx.Request] = []

    def no_network(self: Any, request: httpx.Request) -> httpx.Response:
        sent.append(request)
        raise AssertionError("no request expected")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    at = AppTest.from_file(str(APP), default_timeout=60).run()

    assert not at.exception
    assert contains(values(at.error), "Configuração ausente")
    assert values(at.error) == ["Configuração ausente: defina API_BASE_URL e READ_API_KEY."]
    assert sent == []
    assert not at.get("plotly_chart")


def test_ca06_new_session_defaults_to_live_without_badge(fake: FakeApi) -> None:
    at = run(page(OVERVIEW))

    assert at.sidebar.radio(key="flt_source").value == "Real"
    assert fake.requests, "the overview must read the API"
    for request in fake.requests:
        assert request.url.params.get("source") == "live", str(request.url)
    assert not contains(values(at.warning), BADGE)
    assert BADGE not in dump(at)


def test_ca07_all_sources_badge_depends_on_simulated_total(fake: FakeApi) -> None:
    fake.summaries["simulated"] = make_summary(total=12, defective=1, defect_rate=1 / 12)
    at = with_sidebar_source(OVERVIEW, "Todos", fake)
    assert contains(values(at.main.warning), BADGE)
    badge_checks = [
        r for r in fake.to("/metrics/summary") if r.url.params.get("source") == "simulated"
    ]
    assert badge_checks, "the badge must be decided by summary(source=simulated)"
    # The badge check uses the same filters as the page (only source changes).
    shown = [r for r in fake.to("/metrics/summary") if "source" not in r.url.params]
    assert shown
    same = dict(shown[0].url.params)
    assert dict(badge_checks[0].url.params) == {**same, "source": "simulated"}

    st.cache_data.clear()
    fake.summaries["simulated"] = make_summary(total=0, defective=0, defect_rate=None)
    at = with_sidebar_source(OVERVIEW, "Todos", fake)
    assert not contains(values(at.warning), BADGE)


@pytest.mark.parametrize("path", API_PAGES, ids=lambda p: p.stem)
def test_ca08_simulated_sidebar_on_every_api_page(fake: FakeApi, path: Path) -> None:
    at = with_sidebar_source(path, "Simulado", fake)

    assert contains(values(at.main.warning), BADGE)
    assert fake.requests, f"{path.stem} must read the API"
    for request in fake.requests:
        assert request.url.params.get("source") == "simulated", str(request.url)


# =============================================================================================
# CA-09 to CA-12: overview
# =============================================================================================


def test_ca09_kpis(fake: FakeApi) -> None:
    fake.summaries["live"] = make_summary(
        total=40,
        defective=5,
        defect_rate=0.125,
        unknown_count=3,
        needs_review_count=4,
        mean_grade_score=1.8456,
    )
    at = run(page(OVERVIEW))

    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {
        "Inspeções": "40",
        "Taxa de defeito": "12,5%",
        "Desconhecidos": "3",
        "Para revisão": "4",
        "Grau médio": "1,85",
    }
    assert [m.value for m in at.metric] == ["40", "12,5%", "3", "4", "1,85"]


def test_ca10_grade_distribution_order_values_and_colors() -> None:
    fig = charts.grade_distribution({"good": 10, "perfect": 5})

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    bar = fig.data[0]
    assert bar.type == "bar"
    assert list(bar.x) == GRADE_LABELS
    assert list(bar.y) == [5, 10, 0, 0, 0]
    assert [c.upper() for c in bar.marker.color] == GRADE_HEX
    expected = [charts.GRADE_COLORS[g] for g in charts.GRADE_COLORS]
    assert [c.upper() for c in expected] == GRADE_HEX


def test_ca11_day_bucket_request_and_traces(fake: FakeApi) -> None:
    at = run(page(OVERVIEW))
    fake.reset()
    at.radio(key="vg_bucket").set_value("Dia")
    run(at)

    series = fake.to("/metrics/timeseries")
    assert len(series) == 1
    assert series[0].url.params["bucket"] == "day"
    traces = [t for fig in plotly_figures(at) for t in fig["data"]]
    by_name = {t.get("name"): t for t in traces}
    assert by_name["Inspeções"]["type"] == "bar"
    assert by_name["Taxa de defeito"]["type"] == "scatter"
    assert "lines" in by_name["Taxa de defeito"].get("mode", "lines")


def test_ca12_empty_overview(fake: FakeApi) -> None:
    fake.summaries["live"] = make_summary(
        total=0,
        defective=0,
        defect_rate=None,
        unknown_count=0,
        needs_review_count=0,
        by_grade={},
        by_object_type={},
        mean_type_confidence=None,
        mean_grade_score=None,
    )
    at = run(page(OVERVIEW))

    assert "Nenhuma inspeção encontrada para os filtros selecionados." in values(at.info)
    assert not at.get("plotly_chart")


# =============================================================================================
# CA-13: API waking up (timeout), retry button, no loop
# =============================================================================================


@pytest.mark.parametrize("path", API_PAGES, ids=lambda p: p.stem)
def test_ca13_timeout_shows_waking_and_retry_recovers(fake: FakeApi, path: Path) -> None:
    fake.failure = timeout_failure
    at = page(path).run()

    assert not at.exception
    assert WAKING in values(at.warning)
    retry = [b for b in at.button if b.label == RETRY]
    assert len(retry) == 1
    # One attempt per render: the page does not retry in a loop.
    assert len(fake.requests) == 1
    assert not at.get("plotly_chart")
    assert "Traceback" not in dump(at)

    fake.failure = None
    fake.reset()
    retry[0].click()
    at.run()
    assert not at.exception
    assert WAKING not in values(at.warning)
    assert fake.requests
    if path == HISTORY:
        assert frames(at) and len(frames(at)[0]) == 1
    else:
        assert at.get("plotly_chart")


def test_ca13_model_page_badge_check_timeout(
    fake: FakeApi, metrics_file: Callable[[Any], Path]
) -> None:
    """'Sobre o modelo' only reads the API for the badge with origin 'Todos'."""
    metrics_file(metrics_document())
    at = run(page(MODEL_PAGE))
    fake.failure = timeout_failure
    fake.reset()
    at.sidebar.radio(key="flt_source").set_value("Todos")
    at.run()

    assert not at.exception
    assert WAKING in values(at.warning)
    assert [b.label for b in at.button if b.label == RETRY] == [RETRY]
    assert len(fake.requests) == 1


# =============================================================================================
# CA-14 to CA-17, CA-27, CA-29 to CA-31: statistical control page
# =============================================================================================


def test_ca14_p_chart_figure() -> None:
    spc = make_spc(source="live")
    fig = charts.p_chart(spc)
    traces = {t.name: t for t in fig.data}

    ooc = traces["Fora de controle"]
    assert list(ooc.x) == ["L-003"]
    assert ooc.marker.color.upper() == "#D62728"
    annotations = list(fig.layout.annotations)
    assert len(annotations) == 1
    assert annotations[0].text == "L-003"
    for name, attr in (("LSC", "ucl"), ("LIC", "lcl")):
        assert traces[name].line.shape == "hv"
        expected = [getattr(p, attr) for p in spc.points]
        assert list(traces[name].y) == pytest.approx(expected)
    assert all(y == pytest.approx(0.18) for y in traces["LC"].y)
    assert len(list(traces["LC"].y)) == 4
    assert list(traces["p do lote"].x) == ["L-001", "L-002", "L-003", "L-004"]
    assert fig.layout.title.text == "Carta p — origem: real"


def test_ca15_default_controls_request(fake: FakeApi) -> None:
    at = run(page(SPC_PAGE))

    spc_requests = fake.to("/metrics/spc")
    assert len(spc_requests) == 1
    assert dict(spc_requests[0].url.params) == {
        "source": "live",
        "baseline_lots": "20",
        "min_lot_size": "5",
        "max_points": "100",
    }

    fake.reset()
    at.selectbox(key="spc_type").set_value("porca")
    run(at)
    spc_requests = fake.to("/metrics/spc")
    assert len(spc_requests) == 1
    params = dict(spc_requests[0].url.params)
    assert params["object_type"] == "nut"
    assert params["source"] == "live"
    assert "from" not in params and "to" not in params


def test_ca16_insufficient_data(fake: FakeApi) -> None:
    fake.spc = make_spc(
        p_bar=None,
        points=[],
        excluded_lots=[],
        message="At least 2 lots with n >= 5 are needed",
        valid_lots_total=0,
        excluded_lots_total=0,
    ).model_dump(mode="json")
    at = run(page(SPC_PAGE))

    assert contains(values(at.info), "pelo menos 2 lotes")
    assert (
        "Dados insuficientes para a carta p: são necessários pelo menos 2 lotes com n ≥ 5."
        in values(at.info)
    )
    assert not at.get("plotly_chart")
    assert not contains(all_text(at), "At least 2 lots")


def test_ca17_excluded_lots_and_table(fake: FakeApi) -> None:
    at = run(page(SPC_PAGE))

    assert contains(values(at.info), "L-009 (n=3)")
    assert contains(values(at.info), "Lotes excluídos (n < 5): L-009 (n=3)")
    tables = [f for f in frames(at) if "Fora de controle" in list(f.columns)]
    assert len(tables) == 1
    table = tables[0]
    assert list(table.columns) == SPC_COLUMNS
    assert len(table) == 4
    flags = dict(zip(table["Lote"], table["Fora de controle"], strict=True))
    assert flags == {"L-001": "Não", "L-002": "Não", "L-003": "Sim", "L-004": "Não"}


def _cut_response(valid_total: int | None, excluded_total: int | None) -> dict[str, Any]:
    points = [make_point(f"L-{i:03d}", 25, 4, hour=i) for i in range(31, 131)]
    excluded = [{"lot_id": f"X-{i:03d}", "n": 2} for i in range(50)]
    return make_spc(
        points=points,
        excluded_lots=excluded,
        baseline_lots=20,
        valid_lots_total=valid_total,
        excluded_lots_total=excluded_total,
    ).model_dump(mode="json")


def test_ca27_cut_chart_notices(fake: FakeApi) -> None:
    fake.spc = _cut_response(130, 60)
    at = run(page(SPC_PAGE))

    assert contains(values(at.caption), "Mostrando os últimos 100 de 130 lotes válidos")
    assert (
        "Mostrando os últimos 100 de 130 lotes válidos. A linha central usa os primeiros 20 "
        "lotes válidos do histórico." in values(at.caption)
    )
    excluded = [t for t in values(at.info) if t.startswith("Lotes excluídos")]
    assert len(excluded) == 1
    assert excluded[0].endswith(" e mais 10 lote(s) excluído(s) mais antigo(s).")


@pytest.mark.parametrize(
    ("valid_total", "excluded_total"), [(100, 50), (None, None)], ids=["equal", "null"]
)
def test_ca27_no_cut_notices(
    fake: FakeApi, valid_total: int | None, excluded_total: int | None
) -> None:
    fake.spc = _cut_response(valid_total, excluded_total)
    at = run(page(SPC_PAGE))

    assert not contains(all_text(at), "Mostrando os últimos")
    assert not contains(all_text(at), "e mais")
    assert contains(values(at.info), "Lotes excluídos (n < 5): X-000 (n=2)")


def test_ca29_one_chart_one_origin(fake: FakeApi) -> None:
    at = run(page(SPC_PAGE))
    fake.reset()
    at.radio(key="spc_source").set_value("Simulado")
    run(at)

    spc_requests = fake.to("/metrics/spc")
    assert len(spc_requests) == 1
    assert spc_requests[0].url.params["source"] == "simulated"
    figures = plotly_figures(at)
    assert len(figures) == 1
    assert figure_title(figures[0]) == "Carta p — origem: simulado"
    assert PERIOD_NOTE in values(at.caption)
    assert contains(values(at.main.warning), BADGE)


def test_ca30_spc_cached_between_renders(fake: FakeApi) -> None:
    at = run(page(SPC_PAGE))
    run(at)
    assert len(fake.to("/metrics/spc")) == 1

    st.cache_data.clear()
    run(at)
    assert len(fake.to("/metrics/spc")) == 2


def test_ca31_max_points_control(fake: FakeApi) -> None:
    at = run(page(SPC_PAGE))
    control = at.number_input(key="spc_max_points")
    assert control.value == 100
    assert (control.proto.has_min, control.proto.min) == (True, 2)
    assert (control.proto.has_max, control.proto.max) == (True, 500)

    fake.reset()
    control.set_value(10)
    run(at)
    spc_requests = fake.to("/metrics/spc")
    assert len(spc_requests) == 1
    assert spc_requests[0].url.params["max_points"] == "10"

    # Out of range: never reaches the API.
    for bad in (1, 501):
        fake.reset()
        at.number_input(key="spc_max_points").set_value(bad)
        at.run()
        sent = {r.url.params.get("max_points") for r in fake.to("/metrics/spc")}
        assert str(bad) not in sent


# =============================================================================================
# CA-18 to CA-21: history, CSV and lot validation
# =============================================================================================


def test_ca18_pagination_and_columns(fake: FakeApi) -> None:
    fake.items = [make_inspection(lot_id=f"L-{i:03d}") for i in range(50)]
    fake.items_total = 120
    at = run(page(HISTORY))

    first = fake.to("/inspections")
    assert len(first) == 1
    assert first[0].url.params["limit"] == "50"
    assert first[0].url.params["offset"] == "0"
    assert contains(all_text(at), "Página 1 de 3")
    assert contains(all_text(at), "Página 1 de 3 — 120 inspeções")
    table = frames(at)[0]
    assert list(table.columns) == HISTORY_COLUMNS

    fake.reset()
    at.button(key="hist_next").click()
    run(at)
    nxt = fake.to("/inspections")
    assert len(nxt) == 1
    assert nxt[0].url.params["offset"] == "50"
    assert nxt[0].url.params["limit"] == "50"
    assert contains(all_text(at), "Página 2 de 3")


def test_ca19_unknown_simulated_row(fake: FakeApi) -> None:
    fake.items = [
        make_inspection(
            object_type="unknown",
            grade=None,
            grade_score=None,
            grade_confidence=None,
            source="simulated",
            inspected_at="2026-11-03T15:00:00Z",
            is_defective=False,
            needs_review=False,
        )
    ]
    at = run(page(HISTORY))

    row = frames(at)[0].iloc[0].to_dict()
    assert row["Tipo"] == "desconhecido"
    assert row["Grau"] == "—"
    assert row["Origem"] == "simulado"
    assert row["Data/hora"] == "03/11/2026 12:00"
    assert row["Nota de grau"] == "—"
    assert row["Conf. grau"] == "—"
    assert row["Defeituosa"] == "Não"


def test_ca20_history_csv() -> None:
    items = [
        make_inspection(type_confidence=0.875, inspected_at="2026-11-03T15:00:00Z"),
        make_inspection(
            object_type="unknown",
            grade=None,
            grade_score=None,
            grade_confidence=None,
            type_confidence=0.5,
            inspected_at="2026-11-04T02:30:00Z",
            is_defective=False,
        ),
    ]
    raw = formatting.history_csv(items)

    assert isinstance(raw, bytes)
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    assert lines[0] == ";".join(HISTORY_COLUMNS)
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert len(rows) == 3
    first = dict(zip(rows[0], rows[1], strict=True))
    assert first["Conf. tipo"] == "0,875"
    assert first["Data/hora"] == "2026-11-03T12:00:00-03:00"
    assert "0,875" in text
    assert "2026-11-03T12:00:00-03:00" in text
    second = dict(zip(rows[0], rows[2], strict=True))
    assert second["Grau"] == ""  # empty instead of the em dash
    assert "—" not in text
    assert second["Data/hora"] == "2026-11-03T23:30:00-03:00"


@pytest.mark.parametrize("path", API_PAGES, ids=lambda p: p.stem)
def test_ca21_invalid_lot_is_ignored(fake: FakeApi, path: Path) -> None:
    at = run(page(path))
    fake.reset()
    st.cache_data.clear()  # an ignored filter repeats the same (cached) reads otherwise
    at.sidebar.text_input(key="flt_lot").set_value("L 01")
    run(at)

    assert "Lote inválido" in values(at.sidebar.error)
    assert fake.requests, f"{path.stem} must read the API"
    for request in fake.requests:
        assert "lot_id" not in request.url.params, str(request.url)


# =============================================================================================
# CA-22, CA-28: cache and origin caption
# =============================================================================================


def test_ca22_fetch_summary_cache(fake: FakeApi) -> None:
    filters = Filters(source="live", object_type="screw")
    first = data.fetch_summary(filters)
    second = data.fetch_summary(Filters(source="live", object_type="screw"))

    assert len(fake.to("/metrics/summary")) == 1
    assert first == second
    st.cache_data.clear()
    data.fetch_summary(filters)
    assert len(fake.to("/metrics/summary")) == 2


ORIGIN_CAPTIONS = {
    "Real": "Origem dos dados: real",
    "Simulado": "Origem dos dados: simulado",
    "Todos": "Origem dos dados: todas (real + simulado)",
}


@pytest.mark.parametrize("path", (OVERVIEW, HISTORY), ids=lambda p: p.stem)
def test_ca28_origin_caption_always_visible(fake: FakeApi, path: Path) -> None:
    fake.summaries["simulated"] = make_summary(total=0, defective=0, defect_rate=None)
    at = run(page(path))
    assert ORIGIN_CAPTIONS["Real"] in values(at.main.caption)

    for option in ("Simulado", "Todos"):
        at.sidebar.radio(key="flt_source").set_value(option)
        run(at)
        assert ORIGIN_CAPTIONS[option] in values(at.main.caption), option
    # 'Todos' with no simulated data: no badge, the caption is still there.
    assert not contains(values(at.warning), BADGE)


# =============================================================================================
# CA-23, CA-24: about the model
# =============================================================================================


def _row_with(table: Any, needle: str) -> dict[str, str]:
    rows = [
        {k: str(v) for k, v in r.items()}
        for r in table.to_dict("records")
        if any(needle.lower() in str(v).lower() for v in r.values())
    ]
    assert len(rows) == 1, (needle, table.to_dict("records"))
    return rows[0]


def test_ca23_metrics_against_targets(fake: FakeApi, metrics_file: Callable[[Any], Path]) -> None:
    doc = metrics_document(type_accuracy=0.96, grade_qwk=0.70)
    assert not (REPO_ROOT / "ml" / "reports" / doc["model_version"]).exists()
    metrics_file(doc)
    at = run(page(MODEL_PAGE))

    tables = frames(at)
    targets = [t for t in tables if t.astype(str).isin(["Atingida"]).any().any()]
    assert len(targets) == 1
    target = targets[0]
    type_row = (
        _row_with(target, "type_accuracy")
        if target.astype(str).apply(lambda c: c.str.contains("type_accuracy")).any().any()
        else _row_with(target, "0,9600")
    )
    assert "Atingida" in type_row.values()
    qwk = _row_with(target, "qwk")
    assert "Abaixo da meta" in qwk.values()
    assert "0,7000" in qwk.values()

    grade_tables = [t for t in tables if t.astype(str).isin(GRADE_LABELS).any().any()]
    assert len(grade_tables) == 1
    assert len(grade_tables[0]) == 5
    assert contains(values(at.caption), "Imagem não disponível")
    assert not at.exception


def test_ca24_missing_and_invalid_metrics(
    fake: FakeApi, metrics_file: Callable[[Any], Path], tmp_path: Path, monkeypatch: Any
) -> None:
    missing = tmp_path / "nowhere" / "metrics.json"
    monkeypatch.setenv("MODEL_METRICS_PATH", str(missing))
    at = run(page(MODEL_PAGE))
    assert contains(values(at.info), "Nenhum modelo avaliado ainda")
    assert f"Nenhum modelo avaliado ainda: metrics.json não encontrado em {missing}." in values(
        at.info
    )

    metrics_file({"x": 1})
    at = run(page(MODEL_PAGE))
    assert contains(values(at.error), "metrics.json inválido")
    assert "Traceback" not in dump(at)


# =============================================================================================
# CA-25: dependencies (R-12)
# =============================================================================================


def test_ca25_no_ml_or_database_dependencies() -> None:
    uv = shutil.which("uv")
    assert uv, "uv is required (CI installs it)"
    exported = subprocess.run(
        [uv, "export", "--package", "qc-dashboard", "--frozen", "--no-hashes"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout
    assert "streamlit" in exported  # sanity: the export is the dashboard one
    for name in FORBIDDEN_DEPS:
        assert name not in exported, name

    grep = shutil.which("grep")
    assert grep
    found = subprocess.run(
        [
            grep,
            "-rIE",
            "psycopg|DATABASE_URL|supabase|onnxruntime|import torch",
            "dashboard",
            "--exclude-dir=tests",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert found.returncode == 1, found.stdout
    assert found.stdout == ""


# =============================================================================================
# Exploratory (no CA spells these out)
# =============================================================================================


def test_extra_key_never_on_page_nor_in_log(
    fake: FakeApi, key: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    for path in API_PAGES:
        at = run(page(path))
        assert key not in dump(at), path.stem
    fake.failure = lambda r: httpx.Response(401, json={"detail": "Missing or invalid API key"})
    st.cache_data.clear()
    at = page(OVERVIEW).run()
    assert not at.exception
    assert values(at.error) == ["Chave de leitura inválida ou ausente (READ_API_KEY)."]
    assert key not in dump(at)
    assert key not in caplog.text


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (500, "Erro da API (HTTP 500)."),
        (422, "Erro da API (HTTP 422)."),
        (403, "Chave de leitura inválida ou ausente (READ_API_KEY)."),
    ],
)
def test_extra_error_messages_without_stack_trace(
    fake: FakeApi, status: int, expected: str
) -> None:
    fake.failure = lambda r: httpx.Response(status, json={"detail": "boom"})
    at = page(SPC_PAGE).run()

    assert not at.exception
    assert values(at.error) == [expected]
    assert "Traceback" not in dump(at)
    assert len(fake.requests) == 1


@pytest.mark.parametrize("status", [502, 503, 504])
def test_extra_gateway_statuses_wake_up_warning(fake: FakeApi, status: int) -> None:
    fake.failure = lambda r: httpx.Response(status, text="<html>bad gateway</html>")
    at = page(HISTORY).run()

    assert not at.exception
    assert WAKING in values(at.warning)
    assert len(fake.requests) == 1
    assert "bad gateway" not in dump(at)


def test_extra_connect_error_is_unavailable(key: str) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = ApiClient(BASE, key, transport=httpx.MockTransport(refuse))
    with pytest.raises(ApiUnavailable):
        client.summary(Filters())


def test_extra_non_json_body_is_api_error(key: str) -> None:
    client = ApiClient(
        BASE, key, transport=httpx.MockTransport(lambda r: httpx.Response(200, text="\x00<html>"))
    )
    with pytest.raises(ApiError):
        client.summary(Filters())


def test_extra_errors_are_not_cached(fake: FakeApi) -> None:
    fake.failure = timeout_failure
    with pytest.raises(ApiUnavailable):
        data.fetch_summary(Filters(source="live"))
    fake.failure = None
    assert data.fetch_summary(Filters(source="live")).total == 40
    assert len(fake.to("/metrics/summary")) == 2


def test_extra_cache_expires_after_30_seconds(
    fake: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(cache_utils, "TTLCACHE_TIMER", lambda: now[0])
    st.cache_data.clear()
    data.fetch_summary(Filters(source="live"))
    now[0] += 29.0
    data.fetch_summary(Filters(source="live"))
    assert len(fake.to("/metrics/summary")) == 1
    now[0] += 2.0  # 31 s after the first call
    data.fetch_summary(Filters(source="live"))
    assert len(fake.to("/metrics/summary")) == 2


def test_extra_default_period_is_last_7_local_days(fake: FakeApi) -> None:
    run(page(OVERVIEW))
    request = fake.to("/metrics/summary")[0]
    start = datetime.fromisoformat(request.url.params["from"])
    end = datetime.fromisoformat(request.url.params["to"])
    today = datetime.now(SAO_PAULO).date()
    expected_end = datetime.combine(today + timedelta(days=1), time(0), SAO_PAULO)
    assert end == expected_end
    assert end.utcoffset() == timedelta(0)
    assert start.astimezone(SAO_PAULO).time() == time(0)
    days = (end - start).days
    assert days == 7, f"period has {days} days"


def test_extra_sidebar_type_filter_and_valid_lot(fake: FakeApi) -> None:
    at = run(page(OVERVIEW))
    fake.reset()
    at.sidebar.selectbox(key="flt_type").set_value("porca")
    at.sidebar.text_input(key="flt_lot").set_value("L_01-a")
    run(at)
    for request in fake.requests:
        assert request.url.params["object_type"] == "nut"
        assert request.url.params["lot_id"] == "L_01-a"
    assert "Lote inválido" not in values(at.sidebar.error)


@pytest.mark.parametrize("lot", ["Lóte", "x" * 41, "L/01", "L 01", "L-01;DROP", "١٢٣"])
def test_extra_lot_regex_edges(fake: FakeApi, lot: str) -> None:
    at = run(page(OVERVIEW))
    fake.reset()
    st.cache_data.clear()
    at.sidebar.text_input(key="flt_lot").set_value(lot)
    run(at)
    assert "Lote inválido" in values(at.sidebar.error)
    assert fake.requests
    assert all("lot_id" not in r.url.params for r in fake.requests)


@pytest.mark.parametrize("lot", ["L-01\n", " L-01 ", "\tL-01"])
def test_extra_lot_surrounding_whitespace_is_stripped(fake: FakeApi, lot: str) -> None:
    """Observed: the sidebar strips the text before the regex; only the clean id is sent."""
    at = run(page(OVERVIEW))
    fake.reset()
    at.sidebar.text_input(key="flt_lot").set_value(lot)
    run(at)
    sent = {r.url.params.get("lot_id") for r in fake.requests}
    assert sent == {"L-01"}
    assert "Lote inválido" not in values(at.sidebar.error)


def test_extra_retry_while_still_down_is_bounded(fake: FakeApi) -> None:
    fake.failure = timeout_failure
    at = page(OVERVIEW).run()
    fake.reset()
    at.button(key="api_retry").click()
    at.run()
    assert not at.exception
    assert WAKING in values(at.warning)
    # The click rerun and the st.rerun() of the button: 2 attempts, then it stops.
    assert len(fake.requests) <= 2
    fake.reset()
    at.run()
    assert len(fake.requests) == 1


def test_extra_badge_legend_also_in_sidebar(fake: FakeApi) -> None:
    at = with_sidebar_source(OVERVIEW, "Simulado", fake)
    sidebar = "\n".join(_protos(at.sidebar))
    assert BADGE.encode("utf-8").decode("latin-1") in sidebar or BADGE in sidebar


def test_extra_spc_controls_never_offer_all_or_unknown(fake: FakeApi) -> None:
    at = run(page(SPC_PAGE))
    assert list(at.radio(key="spc_source").options) == ["Real", "Simulado"]
    # SPEC-016 section 4.5: the filter offers the members of SpcObjectType (still no unknown).
    assert list(at.selectbox(key="spc_type").options) == [
        "Todos",
        "parafuso",
        "porca",
        "alicate",
        "chave inglesa",
        "chave Allen",
        "chave de fenda",
        "chave Phillips",
    ]
    baseline = at.number_input(key="spc_baseline_lots")
    assert (baseline.value, baseline.proto.min, baseline.proto.max) == (20, 2, 100)
    size = at.number_input(key="spc_min_lot_size")
    assert (size.value, size.proto.min, size.proto.max) == (5, 1, 500)
    assert PERIOD_NOTE in values(at.caption)
    # The global source 'Todos' never reaches the SPC route.
    fake.reset()
    at.sidebar.radio(key="flt_source").set_value("Todos")
    run(at)
    for request in fake.to("/metrics/spc"):
        assert request.url.params["source"] in {"live", "simulated"}
    assert len(plotly_figures(at)) == 1


def test_extra_spc_period_change_does_not_refetch(fake: FakeApi) -> None:
    at = run(page(SPC_PAGE))
    fake.reset()
    today = datetime.now(SAO_PAULO).date()
    at.sidebar.date_input(key="flt_period").set_value((today - timedelta(days=2), today))
    run(at)
    assert all("from" not in r.url.params for r in fake.to("/metrics/spc"))
    assert len(fake.to("/metrics/spc")) == 0  # same SPC parameters: served by the cache


def test_extra_spc_response_without_030_fields(fake: FakeApi) -> None:
    body = make_spc().model_dump(mode="json")
    for name in ("max_points", "valid_lots_total", "excluded_lots_total"):
        body.pop(name)
    fake.spc = body
    at = run(page(SPC_PAGE))
    assert len(plotly_figures(at)) == 1
    assert not contains(all_text(at), "Mostrando os últimos")
    assert not contains(all_text(at), "e mais")


def test_extra_p_chart_details() -> None:
    fig = charts.p_chart(make_spc(source="simulated"))
    traces = {t.name: t for t in fig.data}
    assert fig.layout.title.text == "Carta p — origem: simulado"
    assert traces["Fora de controle"].marker.symbol == "diamond"
    assert traces["Fora de controle"].marker.size == 12
    assert "markers" in traces["p do lote"].mode and "lines" in traces["p do lote"].mode
    for name in ("LSC", "LIC"):
        assert traces[name].line.dash in {"dash", "dot", "dashdot", "longdash"}
    assert fig.layout.xaxis.title.text == "Lote (ordem de início)"
    assert fig.layout.yaxis.title.text == "Proporção de defeituosos (p)"
    assert "%" in (fig.layout.yaxis.tickformat or "")


def test_extra_p_chart_without_out_of_control() -> None:
    points = [make_point(f"L-00{i}", 25, 4, hour=i) for i in range(1, 4)]
    fig = charts.p_chart(make_spc(points=points))
    ooc = [t for t in fig.data if t.name == "Fora de controle"]
    assert all(len(t.x or ()) == 0 for t in ooc)
    assert len(fig.layout.annotations) == 0


def test_extra_by_object_type_and_series_charts() -> None:
    fig = charts.by_object_type({"screw": 3, "nut": 1})
    bar = fig.data[0]
    assert bar.orientation == "h"
    # SPEC-016 section 4.5: the bars include the 5 hand tools.
    assert set(bar.y) == {
        "parafuso",
        "porca",
        "alicate",
        "chave inglesa",
        "chave Allen",
        "chave de fenda",
        "chave Phillips",
        "desconhecido",
    }
    series = [
        TimeseriesPoint(
            bucket_start=datetime(2026, 11, 3, 1, tzinfo=UTC),
            total=4,
            defective=1,
            defect_rate=0.25,
        )
    ]
    day = charts.volume_and_defect_rate(series, "day")
    assert "(UTC)" in (day.layout.title.text or "")
    names = {t.name: t.type for t in day.data}
    assert names == {"Inspeções": "bar", "Taxa de defeito": "scatter"}


def test_extra_overview_null_mean_grade_and_help(fake: FakeApi) -> None:
    fake.summaries["live"] = make_summary(mean_grade_score=None, defect_rate=None)
    at = run(page(OVERVIEW))
    metrics = {m.label: m for m in at.metric}
    assert metrics["Grau médio"].value == "—"
    assert metrics["Taxa de defeito"].value == "—"
    assert "0 = perfeito" in metrics["Grau médio"].proto.help
    assert "4 = inutilizável" in metrics["Grau médio"].proto.help


@pytest.mark.parametrize(("option", "bucket"), [("Minuto", "minute"), ("Hora", "hour")])
def test_extra_bucket_options(fake: FakeApi, option: str, bucket: str) -> None:
    at = run(page(OVERVIEW))
    assert at.radio(key="vg_bucket").value == "Hora"
    fake.reset()
    at.radio(key="vg_bucket").set_value(option)
    run(at)
    sent = [r.url.params["bucket"] for r in fake.to("/metrics/timeseries")]
    assert sent in ([bucket], [])  # 'Hora' is the default and may come from the cache


def test_extra_history_page_filters_and_reset(fake: FakeApi) -> None:
    fake.items_total = 300
    at = run(page(HISTORY))
    at.button(key="hist_next").click()
    run(at)
    fake.reset()
    at.selectbox(key="hist_grade").set_value("ruim")
    run(at)
    req = fake.to("/inspections")[-1]
    assert req.url.params["grade"] == "poor"
    assert req.url.params["offset"] == "0"

    fake.reset()
    at.selectbox(key="hist_defective").set_value("Sim")
    run(at)
    assert fake.to("/inspections")[-1].url.params["defective"] == "true"

    fake.reset()
    at.selectbox(key="hist_page_size").set_value(25)
    run(at)
    req = fake.to("/inspections")[-1]
    assert req.url.params["limit"] == "25"
    assert req.url.params["offset"] == "0"


def test_extra_history_empty_and_download(fake: FakeApi) -> None:
    fake.items = []
    fake.items_total = 0
    at = run(page(HISTORY))
    assert "Nenhuma inspeção encontrada." in values(at.info)

    fake.items = [make_inspection()]
    fake.items_total = 1
    st.cache_data.clear()
    at = run(page(HISTORY))
    buttons = at.get("download_button")
    assert len(buttons) == 1
    assert buttons[0].proto.label == "Baixar CSV (página atual)"


def test_extra_history_device_filter(fake: FakeApi) -> None:
    at = run(page(HISTORY))
    fake.reset()
    at.text_input(key="hist_device").set_value("edge-02")
    run(at)
    assert fake.to("/inspections")[-1].url.params["device_id"] == "edge-02"


def test_extra_filters_persist_across_pages(fake: FakeApi) -> None:
    at = run(AppTest.from_file(str(APP), default_timeout=60))
    at.sidebar.radio(key="flt_source").set_value("Simulado")
    run(at)
    fake.reset()
    at.switch_page("views/historico.py")
    run(at)
    assert fake.to("/inspections")
    assert all(r.url.params.get("source") == "simulated" for r in fake.requests)
    assert contains(values(at.main.warning), BADGE)


def test_extra_model_page_header_and_fixed_legend(
    fake: FakeApi, metrics_file: Callable[[Any], Path]
) -> None:
    doc = metrics_document(warnings=["poucos itens no grau ruim"])
    metrics_file(doc)
    at = run(page(MODEL_PAGE))
    text = "\n".join(all_text(at)) + dump(at)
    assert "partqc-acceptance-v0" in text
    assert "0123456789ab" in text
    assert "0123456789abc" not in "\n".join(all_text(at))
    assert "ml/splits/split_v1.csv" in text
    assert "20/11/2026 10:30" in text  # 13:30 UTC in Sao Paulo
    assert contains(
        all_text(at),
        "Métricas medidas no conjunto de teste, que não é usado para nenhuma escolha (R-11). "
        "As metas do PRD são iniciais.",
    )
    assert "poucos itens no grau ruim" in "\n".join(all_text(at)) + dump(at)


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (0.95999, "0,9599"),
        (0.70, "0,7000"),
        (0.29, "0,2900"),
        (0.57, "0,5700"),
        (1.0, "1,0000"),
        (0.30000000000000004, "0,3000"),
        (0.12345, "0,1234"),
    ],
)
def test_extra_four_places_never_rounded_up(
    fake: FakeApi, metrics_file: Callable[[Any], Path], value: float, shown: str
) -> None:
    metrics_file(metrics_document(grade_qwk=value))
    at = run(page(MODEL_PAGE))
    targets = [t for t in frames(at) if t.astype(str).isin(["Atingida"]).any().any()]
    qwk = _row_with(targets[0], "qwk")
    assert shown in qwk.values(), qwk


def test_extra_target_boundaries_and_null() -> None:
    metrics = metrics_document(
        type_accuracy=0.95, latency_ms_p95=300.0, defective_recall=None, grade_qwk=0.7499
    )
    rows = model_info.target_rows(metrics)
    text = json.dumps(rows, ensure_ascii=False)
    assert text.count("Atingida") >= 2  # 0.95 >= 0.95 and 300 <= 300
    assert "Abaixo da meta" in text
    assert "—" in text  # defective_recall null


@pytest.mark.parametrize("content", ["{not json", "[]", '{"model_version": "x"}'])
def test_extra_invalid_metrics_variants(
    fake: FakeApi, metrics_file: Callable[[Any], Path], content: str
) -> None:
    metrics_file(content)
    at = page(MODEL_PAGE).run()
    assert not at.exception
    assert contains(values(at.error), "metrics.json inválido")


def test_extra_metrics_missing_one_new_key(
    fake: FakeApi, metrics_file: Callable[[Any], Path]
) -> None:
    doc = metrics_document()
    doc.pop("n_items_test_by_grade")
    metrics_file(doc)
    at = page(MODEL_PAGE).run()
    assert not at.exception
    assert contains(values(at.error), "metrics.json inválido")


def test_extra_model_version_path_traversal(
    fake: FakeApi, metrics_file: Callable[[Any], Path]
) -> None:
    metrics_file(metrics_document(model_version="../../etc"))
    at = page(MODEL_PAGE).run()
    assert not at.exception
    assert not at.get("imgs") and not at.get("image")


def test_extra_to_local_and_formatting() -> None:
    assert formatting.fmt_pct(0.125) == "12,5%"
    utc = datetime(2026, 11, 3, 15, tzinfo=UTC)
    local = formatting.to_local(utc)
    assert local.utcoffset() == timedelta(hours=-3)
    assert (local.hour, local.minute) == (12, 0)


def test_extra_import_does_not_load_ml_or_db_modules() -> None:
    code = (
        "import sys\n"
        "import qc_dashboard.api, qc_dashboard.charts, qc_dashboard.config\n"
        "import qc_dashboard.data, qc_dashboard.filters, qc_dashboard.formatting\n"
        "import qc_dashboard.model_info\n"
        "bad = [m for m in ('torch', 'onnxruntime', 'timm', 'psycopg', 'qc_ml', 'supabase')"
        " if m in sys.modules]\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120
    )
    assert out.stdout.strip() == ""


def test_extra_app_navigation_titles(fake: FakeApi) -> None:
    at = run(AppTest.from_file(str(APP), default_timeout=60))
    # Default page is the overview.
    assert {m.label for m in at.metric} >= {"Inspeções", "Taxa de defeito"}
    source = APP.read_text("utf-8")
    for title in ("Visão geral", "Controle estatístico", "Histórico", "Sobre o modelo"):
        assert title in source
    assert 'page_title="PartQC"' in source
    assert 'layout="wide"' in source


def test_extra_settings_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from qc_dashboard import config

    monkeypatch.chdir(tmp_path)
    secret = new_key()
    monkeypatch.setenv("API_BASE_URL", "http://localhost:8001")
    monkeypatch.setenv("READ_API_KEY", secret)
    settings = config.get_settings()
    assert settings.api_base_url == "http://localhost:8001"
    assert settings.read_api_key == secret
    assert secret not in repr(settings)
    expected = REPO_ROOT / "ml/models/partqc-mnv3-v1/metrics.json"
    assert Path(settings.model_metrics_path).resolve() == expected.resolve()
    monkeypatch.delenv("READ_API_KEY")
    with pytest.raises(config.ConfigError):
        config.get_settings()


def test_extra_grade_labels_come_from_contract() -> None:
    assert [GRADE_LABELS_PT[g] for g in charts.GRADE_COLORS] == GRADE_LABELS


def test_extra_key_not_logged_by_the_real_http_stack(caplog: pytest.LogCaptureFixture) -> None:
    """CA-04 again over a real local socket (httpx + httpcore loggers), not a MockTransport."""
    import http.server
    import threading

    body = json.dumps(make_summary().model_dump(mode="json")).encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib name)
            status = 401 if "summary" not in self.path else 200
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body if status == 200 else b'{"detail": "no"}')

        def log_message(self, *args: Any) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    secret = new_key("k-secret")
    try:
        caplog.set_level(logging.DEBUG)
        client = ApiClient(f"http://127.0.0.1:{server.server_address[1]}", secret)
        assert client.summary(Filters(source="live")).total == 40
        with pytest.raises(ApiAuthError) as info:
            client.lots(Filters())
        client.close()
    finally:
        server.shutdown()
        server.server_close()
    assert caplog.records, "the http stack logs at DEBUG"
    assert secret not in caplog.text
    assert secret not in _chain_text(info.value)


# --- the real qc-api in process, over the test database (CA-26 steps 1 to 4, automated) -----


@pytest.fixture
def real_api(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """qc-api (``create_app``) over the migrated test database, behind ``api.get_client``.

    ``edge-01`` sends 6 live lots (``L-005`` out of control) and ``sim-01`` 3 simulated lots,
    all through ``POST /api/v1/inspections/batch``.
    """
    import psycopg
    from fastapi.testclient import TestClient

    from qc_api.auth import hash_api_key
    from qc_api.config import Settings
    from qc_api.main import create_app

    read_key = secrets.token_urlsafe(32)
    device_keys = {"edge-01": secrets.token_urlsafe(32), "sim-01": secrets.token_urlsafe(32)}
    with psycopg.connect(clean_db, autocommit=True, prepare_threshold=None) as conn:
        for device_id, device_key in device_keys.items():
            conn.execute(
                "insert into devices (device_id, api_key_hash) values (%s, %s)",
                (device_id, hash_api_key(device_key)),
            )
    settings = Settings(DATABASE_URL=clean_db, READ_API_KEY=read_key)
    now = datetime.now(UTC).replace(microsecond=0)

    def lot(device: str, lot_id: str, source: str, defects: int, start: datetime) -> list[dict]:
        items = []
        for i in range(10):
            bad = i < defects
            items.append(
                {
                    "inspection_id": str(uuid.uuid4()),
                    "device_id": device,
                    "lot_id": lot_id,
                    "inspected_at": (start + timedelta(seconds=i)).isoformat(),
                    "object_type": "screw",
                    "grade": "poor" if bad else "good",
                    "grade_score": 3.0 if bad else 1.0,
                    "type_confidence": 0.95,
                    "grade_confidence": 0.8,
                    "needs_review": False,
                    "model_version": "partqc-mnv3-v1",
                    "model_sha256": SHA,
                    "latency_ms": 50,
                    "source": source,
                }
            )
        return items

    live = []
    for k in range(6):
        defects = 9 if k == 4 else 1
        live += lot("edge-01", f"L-00{k + 1}", "live", defects, now - timedelta(hours=12 - k))
    simulated = []
    for k in range(3):
        simulated += lot("sim-01", f"S-00{k + 1}", "simulated", 2, now - timedelta(hours=5 - k))

    with TestClient(create_app(settings)) as test_client:
        for device, items in (("edge-01", live), ("sim-01", simulated)):
            response = test_client.post(
                "/api/v1/inspections/batch",
                json={"items": items},
                headers={"X-API-Key": device_keys[device]},
            )
            assert response.status_code == 200, response.text

        requests: list[httpx.Request] = []

        def forward(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            response = test_client.request(
                request.method,
                request.url.raw_path.decode("ascii"),
                headers=dict(request.headers),
            )
            return httpx.Response(response.status_code, content=response.content)

        client = ApiClient("http://testserver", read_key, transport=httpx.MockTransport(forward))
        monkeypatch.setattr(api, "get_client", lambda: client)
        yield {"requests": requests, "read_key": read_key}


@pytest.mark.db
def test_extra_real_api_end_to_end(
    real_api: dict[str, Any], metrics_file: Callable[[Any], Path]
) -> None:
    metrics_file(metrics_document())

    at = run(page(OVERVIEW))
    assert {m.label: m.value for m in at.metric}["Inspeções"] == "60"
    assert not contains(values(at.warning), BADGE)
    at.sidebar.radio(key="flt_source").set_value("Todos")
    run(at)
    assert {m.label: m.value for m in at.metric}["Inspeções"] == "90"
    assert contains(values(at.main.warning), BADGE)
    assert ORIGIN_CAPTIONS["Todos"] in values(at.main.caption)

    # Step 3: with 'Todos', the badge is on every page but the p chart one, whose chart stays
    # 'Real' (SPEC-028 section 4.3: there the badge follows only the chart origin).
    for path in (SPC_PAGE, HISTORY, MODEL_PAGE):
        st.cache_data.clear()
        at = run(page(path))
        at.sidebar.radio(key="flt_source").set_value("Todos")
        run(at)
        if path == SPC_PAGE:
            assert not contains(values(at.main.warning), BADGE), path.stem
            assert "Origem da carta: real" in values(at.main.caption), path.stem
        else:
            assert contains(values(at.main.warning), BADGE), path.stem

    # Step 4: the live p chart has one red, annotated point (L-005).
    st.cache_data.clear()
    real_api["requests"].clear()
    at = run(page(SPC_PAGE))
    spc_requests = [r for r in real_api["requests"] if r.url.path.endswith("/metrics/spc")]
    assert len(spc_requests) == 1
    figure = plotly_figures(at)[0]
    assert figure_title(figure) == "Carta p — origem: real"
    ooc = [t for t in figure["data"] if t.get("name") == "Fora de controle"]
    assert ooc[0]["x"] == ["L-005"]
    assert ooc[0]["marker"]["color"].upper() == "#D62728"
    assert [a["text"] for a in figure["layout"]["annotations"]] == ["L-005"]
    lots = [t for t in figure["data"] if t.get("name") == "p do lote"][0]["x"]
    assert lots == [f"L-00{k}" for k in range(1, 7)]  # live only, never the S-* lots

    # The simulated chart, alone.
    at.radio(key="spc_source").set_value("Simulado")
    run(at)
    figures = plotly_figures(at)
    assert len(figures) == 1
    lots = [t for t in figures[0]["data"] if t.get("name") == "p do lote"][0]["x"]
    assert lots == ["S-001", "S-002", "S-003"]
    assert figure_title(figures[0]) == "Carta p — origem: simulado"

    # History: live rows only by default, with PT-BR labels; the key is not on any page.
    st.cache_data.clear()
    at = run(page(HISTORY))
    table = frames(at)[0]
    assert len(table) == 50
    assert set(table["Origem"]) == {"real"}
    assert contains(all_text(at), "Página 1 de 2 — 60 inspeções")
    assert real_api["read_key"] not in dump(at)


# --- r2: fixes of T-02 (RV-01), T-01 (RV-02) and O-02 (RV-03) ------------------------------

# SPEC-013 section 4.7: dates as ``dd/mm/aaaa HH:MM`` in the interface; with ``bucket=day`` the
# axis shows the UTC date (no time of day). Only numeric d3 directives: Plotly writes English
# month names (``Oct 16, 2026``) for ``%b``/``%B`` and for its default date ticks.
SERIES_DATE_FORMATS = {"minute": "%d/%m/%Y %H:%M", "hour": "%d/%m/%Y %H:%M", "day": "%d/%m/%Y"}
SERIES_STEPS = {
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
}
X_PLACEHOLDER = re.compile(r"%\{x(?:\|([^}]*))?\}")


def _series(bucket: str, count: int = 6) -> list[TimeseriesPoint]:
    start = datetime(2026, 10, 16, 21, tzinfo=UTC)
    if bucket == "day":
        start = datetime(2026, 10, 14, tzinfo=UTC)
    return [
        TimeseriesPoint(
            bucket_start=start + SERIES_STEPS[bucket] * k,
            total=10 + k,
            defective=1,
            defect_rate=0.1,
        )
        for k in range(count)
    ]


def _x_axes(fig: go.Figure) -> list[Any]:
    return [fig.layout[name] for name in fig.layout if re.fullmatch(r"xaxis\d*", name)]


@pytest.mark.parametrize("count", [3, 6, 30])
@pytest.mark.parametrize("bucket", ["minute", "hour", "day"])
def test_extra_t02_series_date_axis_in_pt_br(bucket: str, count: int) -> None:
    """T-02 fixed (was ``xfail``): every x axis of the series formats dates as section 4.7 says."""
    fig = charts.volume_and_defect_rate(_series(bucket, count), bucket)
    axes = _x_axes(fig)
    assert len(axes) == 2  # the two shared panels
    expected = SERIES_DATE_FORMATS[bucket]
    for axis in axes:
        assert axis.tickformat == expected
        assert axis.hoverformat == expected
        assert axis.tickformatstops in (None, ())  # nothing overrides the numeric format
        assert not re.search(r"%[bBaAcxXp]", axis.tickformat)


@pytest.mark.parametrize("bucket", ["minute", "hour", "day"])
def test_extra_t02_series_hover_in_pt_br(bucket: str) -> None:
    """The hover of both traces shows the date as ``dd/mm/aaaa[ HH:MM]``, never ``%{x}`` raw."""
    fig = charts.volume_and_defect_rate(_series(bucket), bucket)
    expected = SERIES_DATE_FORMATS[bucket]
    assert {t.name for t in fig.data} == {"Inspeções", "Taxa de defeito"}
    for trace in fig.data:
        template = trace.hovertemplate or ""
        placeholders = X_PLACEHOLDER.findall(template)
        assert placeholders, template  # the date is in the hover
        assert placeholders == [expected], template
        assert "%{x}" not in template
    # The hover text after the date is PT-BR, and the rate is a percentage.
    templates = {t.name: t.hovertemplate for t in fig.data}
    assert "Inspeções: %{y}" in templates["Inspeções"]
    assert "Taxa de defeito: %{y:.1%}" in templates["Taxa de defeito"]


@pytest.mark.parametrize("bucket", ["minute", "hour"])
def test_extra_t02_series_x_is_local_wall_clock(bucket: str) -> None:
    """Minute/hour: the x values are the Sao Paulo wall clock (21:00Z -> 18:00), with no offset.

    Plotly drops a UTC offset from the date string, so an aware value would be drawn as UTC.
    """
    fig = charts.volume_and_defect_rate(_series(bucket, 2), bucket)
    for trace in fig.data:
        first = trace.x[0]
        if isinstance(first, str):
            first = datetime.fromisoformat(first)
        assert first.tzinfo is None
        assert (first.day, first.hour, first.minute) == (16, 18, 0)


def test_extra_t02_series_day_is_the_utc_date() -> None:
    """``bucket=day``: the axis shows the UTC date and the title says ``(UTC)``."""
    points = [
        TimeseriesPoint(
            bucket_start=datetime(2026, 10, 17, tzinfo=UTC),  # 16/10 21:00 in Sao Paulo
            total=3,
            defective=0,
            defect_rate=0.0,
        )
    ]
    fig = charts.volume_and_defect_rate(points, "day")
    assert "(UTC)" in (fig.layout.title.text or "")
    for trace in fig.data:
        assert str(trace.x[0])[:10] == "2026-10-17"


def _legend_below_plot_area(fig: go.Figure) -> bool:
    """The legend sits under the axes, never in the top band where Plotly draws the title."""
    legend = fig.layout.legend
    y, anchor, ref = legend.y, legend.yanchor, legend.yref or "paper"
    if y is None:  # Plotly default: vertical legend on the right, outside the title band
        return legend.orientation in (None, "v")
    if ref == "container":
        return y <= 0.1 and anchor in ("bottom", "auto", None)
    return y <= 0 and anchor in ("top", "auto", None)


def test_extra_t01_legend_never_in_the_title_band() -> None:
    """T-01 fixed: in every figure of the dashboard the legend is below the plot area."""
    figures = {
        "grades": charts.grade_distribution({"good": 10, "perfect": 5}),
        "types": charts.by_object_type({"screw": 3, "nut": 1}),
        "series_hour": charts.volume_and_defect_rate(_series("hour", 30), "hour"),
        "series_day": charts.volume_and_defect_rate(_series("day", 3), "day"),
        "p_chart": charts.p_chart(make_spc()),
    }
    for name, fig in figures.items():
        assert fig.layout.title.text, name  # the title is still there
        if fig.layout.showlegend is False:
            continue
        assert _legend_below_plot_area(fig), (name, fig.layout.legend)
    # The p chart title keeps the origin (section 4.4), now with nothing over it.
    assert figures["p_chart"].layout.title.text == "Carta p — origem: real"


@pytest.fixture
def widget_state_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture Streamlit's "default value but also set via the Session State API" warning.

    Streamlit only checks that rule when a server runtime exists, and logs it once per process.
    The test pretends a runtime exists (framework boundary, not the page under test) and resets
    the once-per-process flag, so every offending render is seen.
    """
    from streamlit.elements.lib import policies

    seen: list[str] = []
    # Only the policies module sees a runtime; the cache and AppTest keep the real answer.
    monkeypatch.setattr(policies, "runtime", SimpleNamespace(exists=lambda: True))
    monkeypatch.setattr(policies, "_shown_default_value_warning", False)

    def warning(msg: str, *args: Any, **kwargs: Any) -> None:
        seen.append(msg % args if args else msg)
        policies._shown_default_value_warning = False

    monkeypatch.setattr(policies._LOGGER, "warning", warning)
    return seen


def test_extra_rv03_spc_origin_sync_logs_no_widget_state_warning(
    fake: FakeApi, widget_state_warnings: list[str]
) -> None:
    """O-02/RV-03 fixed: syncing the chart origin with the sidebar logs no Streamlit warning."""
    at = run(page(SPC_PAGE))
    for option in ("Simulado", "Todos", "Real", "Simulado"):
        at.sidebar.radio(key="flt_source").set_value(option)
        run(at)
        expected = "Simulado" if option == "Simulado" else "Real"
        assert at.radio(key="spc_source").value == expected
    at.radio(key="spc_source").set_value("Real")
    run(at)
    assert at.radio(key="spc_source").value == "Real"  # a choice on the page is kept
    at.number_input(key="spc_max_points").set_value(10)
    run(at)
    assert at.radio(key="spc_source").value == "Real"
    assert fake.to("/metrics/spc")[-1].url.params["source"] == "live"
    assert widget_state_warnings == []


def test_extra_rv03_warning_spy_detects_the_r1_pattern(
    widget_state_warnings: list[str], tmp_path: Path
) -> None:
    """Control for the test above: the r1 pattern (state set + ``index=1``) is caught by the spy."""
    script = tmp_path / "r1_pattern.py"
    script.write_text(
        "import streamlit as st\n"
        "st.session_state['k'] = 'b'\n"
        "st.radio('r', ['a', 'b'], index=1, key='k')\n",
        "utf-8",
    )
    at = AppTest.from_file(str(script), default_timeout=30).run()
    assert not at.exception
    assert any('"k"' in w and "Session State API" in w for w in widget_state_warnings)
