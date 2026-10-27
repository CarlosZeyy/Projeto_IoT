"""Acceptance tests for SPEC-028 (dashboard maintenance: https, figures, p chart badge, metrics).

Written by the tester from the SPEC acceptance criteria (black box). One ``test_caNN_*`` per
automatable CA (CA-12 is manual and is left to the pair in the test report). ``test_extra_*``
are exploratory edge cases around SPEC-028 section 4.

Only the HTTP boundary is mocked: ``api.get_client`` is replaced by a real ``ApiClient`` over
``httpx.MockTransport`` (or, for CA-01, the real factory runs and ``httpx.HTTPTransport`` is
intercepted, because the scheme check lives in ``config.get_settings()``). ``st.secrets`` is
replaced by an object without a secrets file, so a local ``.streamlit/secrets.toml`` (the one
the README now recommends) never leaks into these tests. Keys are generated at run time, never
literals (R-03). No test touches the network or runs pytest in a subprocess.
"""

from __future__ import annotations

import json
import re
import secrets
import subprocess
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from qc_contracts import MetricsSummary, SpcResponse, TimeseriesPoint
from qc_dashboard import api, charts, config, data, model_info
from qc_dashboard.api import ApiClient, Filters

pytestmark = pytest.mark.acceptance

DASHBOARD = Path(__file__).resolve().parents[2]
REPO_ROOT = DASHBOARD.parent
VIEWS = DASHBOARD / "views"
OVERVIEW = VIEWS / "visao_geral.py"
SPC_PAGE = VIEWS / "controle_estatistico.py"
HISTORY = VIEWS / "historico.py"
MODEL_PAGE = VIEWS / "sobre_o_modelo.py"

BASE = "https://api.test"
PREFIX = "/api/v1"
GRADES = ("perfect", "good", "fair", "poor", "unusable")
GRADE_LABELS = ["perfeito", "bom", "mediano", "ruim", "inutilizável"]
BADGE = "Contém dados simulados"
WAKING = "API acordando (free tier), tente em ~1 min"
RETRY = "Tentar novamente"
INSECURE = "Configuração inválida: API_BASE_URL precisa usar https://"
INSECURE_FULL = (
    "Configuração inválida: API_BASE_URL precisa usar https:// "
    "(http:// só em localhost ou 127.0.0.1)."
)
AUTH_ERROR = "Chave de leitura inválida ou ausente (READ_API_KEY)."
CONFIG_VARS = ("API_BASE_URL", "READ_API_KEY", "MODEL_METRICS_PATH")

INSECURE_URLS = (
    "http://api.example.org",
    "http://[::1]:8001",
    "ftp://api.example.org",
    "api.example.org",
    "https://",
    "https:///x",
)
SECURE_URLS = (
    "https://api.example.org",
    "HTTPS://api.example.org/",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
)


def new_key() -> str:
    return f"k-{secrets.token_hex(8)}"


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


def make_point(lot_id: str, n: int, defects: int, hour: int) -> dict[str, Any]:
    p_bar = 0.18
    sigma = (p_bar * (1 - p_bar) / n) ** 0.5
    ucl, lcl = min(1.0, p_bar + 3 * sigma), max(0.0, p_bar - 3 * sigma)
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


def make_spc(**overrides: Any) -> SpcResponse:
    values: dict[str, Any] = {
        "baseline_lots": 20,
        "min_lot_size": 5,
        "source": "live",
        "p_bar": 0.18,
        "points": [make_point("L-001", 25, 4, 0), make_point("L-002", 40, 7, 1)],
        "excluded_lots": [],
        "message": None,
        "max_points": 100,
        "valid_lots_total": 2,
        "excluded_lots_total": 0,
    }
    values.update(overrides)
    return SpcResponse.model_validate(values)


def series(count: int = 3) -> list[TimeseriesPoint]:
    start = datetime(2026, 11, 3, 15, tzinfo=UTC)
    return [
        TimeseriesPoint(
            bucket_start=start + timedelta(hours=k), total=10, defective=2, defect_rate=0.2
        )
        for k in range(count)
    ]


def metrics_document(**overrides: Any) -> dict[str, Any]:
    """The valid ``metrics.json`` of SPEC-013 CA-23 (every key of SPEC-012 section 4.7)."""
    sha = "c" * 64
    doc: dict[str, Any] = {
        "model_version": "partqc-acceptance-v0",
        "model_sha256": "0123456789abcdef" * 4,
        "evaluated_at": "2026-11-20T13:30:00+00:00",
        "split_file": "ml/splits/split_v1.csv",
        "split_sha256": sha,
        "manifest_sha256": sha,
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
        self.series = series(2)
        self.spc = make_spc().model_dump(mode="json")
        self.failure: Callable[[httpx.Request], httpx.Response] | None = None
        self.timing_out: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure is not None:
            return self.failure(request)
        path = request.url.path
        params = request.url.params
        if path.removeprefix(PREFIX) in self.timing_out:
            raise httpx.ReadTimeout("timed out", request=request)
        if path == f"{PREFIX}/metrics/summary":
            body = self.summaries[params.get("source")]
            return httpx.Response(200, json=body.model_dump(mode="json"))
        if path == f"{PREFIX}/metrics/timeseries":
            return httpx.Response(200, json=[p.model_dump(mode="json") for p in self.series])
        if path == f"{PREFIX}/metrics/spc":
            return httpx.Response(200, json={**self.spc, "source": params["source"]})
        return httpx.Response(404, json={"detail": "Not Found"})

    def to(self, route: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == PREFIX + route]

    def reset(self) -> None:
        self.requests.clear()


def timeout_failure(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


class NoSecretsFile:
    """Behaves like ``st.secrets`` when there is no ``secrets.toml`` anywhere."""

    def __contains__(self, key: object) -> bool:
        raise FileNotFoundError("No secrets found")

    def __getitem__(self, key: str) -> object:
        raise FileNotFoundError("No secrets found")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """No config from the environment or a local secrets file; clean Streamlit caches."""
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
    mock = FakeApi()
    client = ApiClient(BASE, key, transport=httpx.MockTransport(mock.handler))
    monkeypatch.setattr(api, "get_client", lambda: client)
    return mock


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Every request the real ``httpx`` stack would put on the wire (none is sent)."""
    seen: list[httpx.Request] = []

    def no_network(self: Any, request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(599, json={"detail": "network blocked in tests"})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    return seen


@pytest.fixture
def metrics_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Callable[[Any], Path]:
    def write(content: Any) -> Path:
        path = tmp_path / "metrics.json"
        path.write_text(json.dumps(content), "utf-8")
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


def values(elements: Any) -> list[str]:
    return [str(e.value) for e in elements]


def contains(texts: list[str], needle: str) -> bool:
    return any(needle in t for t in texts)


def frames(at: AppTest) -> list[Any]:
    return [el.value for el in [*at.dataframe, *at.table]]


def cells(at: AppTest) -> list[list[str]]:
    """Every table row of the page as a list of strings."""
    rows: list[list[str]] = []
    for frame in frames(at):
        for record in frame.astype(str).to_dict("records"):
            rows.append(list(record.values()))
    return rows


def row_with(at: AppTest, needle: str) -> list[str]:
    found = [r for r in cells(at) if needle in r]
    assert len(found) == 1, (needle, cells(at))
    return found[0]


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
    return "\n".join(_protos(at.main) + _protos(at.sidebar))


def with_sidebar_source(path: Path, option: str) -> AppTest:
    at = run(page(path))
    at.sidebar.radio(key="flt_source").set_value(option)
    return run(at)


def grade_tables(at: AppTest) -> list[Any]:
    return [t for t in frames(at) if t.astype(str).isin(GRADE_LABELS).any().any()]


def type_accuracy_row(at: AppTest, value: str) -> list[str]:
    rows = [r for r in cells(at) if any("acur" in c.lower() and "tipo" in c.lower() for c in r)]
    rows = rows or [r for r in cells(at) if any("type_accuracy" in c for c in r)]
    rows = rows or [r for r in cells(at) if value in r]
    assert rows, cells(at)
    return rows[0]


# =============================================================================================
# CA-01: API_BASE_URL only with https:// (SEC-13-01)
# =============================================================================================


@pytest.mark.parametrize("url", INSECURE_URLS)
def test_ca01_insecure_api_base_url_is_refused(
    url: str, monkeypatch: pytest.MonkeyPatch, sent: list[httpx.Request]
) -> None:
    monkeypatch.setenv("READ_API_KEY", new_key())
    monkeypatch.setenv("API_BASE_URL", url)

    with pytest.raises(config.InsecureApiUrlError) as raised:
        config.get_settings()
    assert isinstance(raised.value, config.ConfigError)
    assert "API_BASE_URL" in str(raised.value)
    assert "example.org" not in str(raised.value)

    at = page(OVERVIEW).run()
    assert not at.exception
    assert contains(values(at.error), INSECURE)
    assert sent == []


@pytest.mark.parametrize("url", SECURE_URLS)
def test_ca01_secure_api_base_url_is_accepted(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    read_key = new_key()
    monkeypatch.setenv("READ_API_KEY", read_key)
    monkeypatch.setenv("API_BASE_URL", url)
    settings = config.get_settings()
    assert settings is not None


# =============================================================================================
# CA-02: no Plotly mode bar (RV-08)
# =============================================================================================


def test_ca02_every_chart_hides_the_mode_bar(fake: FakeApi) -> None:
    overview = run(page(OVERVIEW))
    spc = run(page(SPC_PAGE))
    charts_overview = overview.get("plotly_chart")
    charts_spc = spc.get("plotly_chart")
    assert len(charts_overview) == 3
    assert len(charts_spc) == 1
    for element in [*charts_overview, *charts_spc]:
        assert json.loads(element.proto.config)["displayModeBar"] is False


# =============================================================================================
# CA-03: right margin of the time series (RV-09)
# =============================================================================================


def test_ca03_series_right_margin() -> None:
    assert charts.volume_and_defect_rate(series(3), "hour").layout.margin.r == 60
    assert charts.grade_distribution(make_summary().by_grade).layout.margin.r == 10
    assert charts.by_object_type(make_summary().by_object_type).layout.margin.r == 10
    assert charts.p_chart(make_spc()).layout.margin.r == 10


# =============================================================================================
# CA-04: the p chart badge follows only the chart origin (R-06, RV-04)
# =============================================================================================


def _spc_sources(fake: FakeApi) -> list[str | None]:
    return [r.url.params.get("source") for r in fake.to("/metrics/spc")]


def test_ca04_spc_badge_follows_only_the_chart_origin(fake: FakeApi) -> None:
    fake.summaries["simulated"] = make_summary(total=12)

    # (a) sidebar 'Todos': chart stays 'Real', no badge.
    at = with_sidebar_source(SPC_PAGE, "Todos")
    assert not contains(values(at.warning), BADGE)
    assert "Origem da carta: real" in values(at.caption)
    assert _spc_sources(fake)[-1] == "live"
    assert fake.to("/metrics/summary") == []

    # (b) sidebar 'Simulado': chart 'Simulado', badge.
    st.cache_data.clear()
    fake.reset()
    at = with_sidebar_source(SPC_PAGE, "Simulado")
    assert contains(values(at.warning), BADGE)
    assert "Origem da carta: simulado" in values(at.caption)
    assert _spc_sources(fake)[-1] == "simulated"
    assert fake.to("/metrics/summary") == []

    # (c) sidebar 'Simulado', chart radio back to 'Real': no badge. The cache is cleared so
    # that the live read of the first render is requested again and can be checked.
    st.cache_data.clear()
    fake.reset()
    at.radio(key="spc_source").set_value("Real")
    run(at)
    assert not contains(values(at.warning), BADGE)
    assert "Origem da carta: real" in values(at.caption)
    assert _spc_sources(fake)[-1] == "live"
    assert fake.to("/metrics/summary") == []


# =============================================================================================
# CA-05: "Sobre o modelo" without the API (RV-05)
# =============================================================================================


def _model_tables_are_there(at: AppTest) -> None:
    assert "Atingida" in type_accuracy_row(at, "0,9600")
    tables = grade_tables(at)
    assert len(tables) == 1
    assert len(tables[0]) == 5


def test_ca05_model_page_without_the_api(
    fake: FakeApi, metrics_file: Callable[[Any], Path]
) -> None:
    metrics_file(metrics_document())

    fake.failure = timeout_failure
    at = with_sidebar_source(MODEL_PAGE, "Todos")
    assert not at.exception
    assert WAKING in values(at.warning)
    assert [b.label for b in at.button if b.label == RETRY] == [RETRY]
    assert contains(values(at.warning), BADGE)
    _model_tables_are_there(at)

    st.cache_data.clear()
    fake.failure = lambda r: httpx.Response(401, json={"detail": "Missing or invalid API key"})
    at = with_sidebar_source(MODEL_PAGE, "Todos")
    assert not at.exception
    assert AUTH_ERROR in values(at.error)
    _model_tables_are_there(at)


# =============================================================================================
# CA-06: display rule of the metrics (R-11, RV-07)
# =============================================================================================


def test_ca06_display_rule(fake: FakeApi, metrics_file: Callable[[Any], Path]) -> None:
    metrics_file(
        metrics_document(
            type_accuracy=0.93127,
            grade_qwk=0.75,
            grade_mae=0.12341,
            latency_ms_p95=120.00001,
            false_unknown_rate=0.02,
            grade_qwk_ci95=[0.61239, 0.78761],
        )
    )
    at = run(page(MODEL_PAGE))
    assert fake.requests == []  # origin 'Real': no request

    assert "Abaixo da meta" in row_with(at, "0,9312")
    qwk = [r for r in cells(at) if any("QWK" in c for c in r) and "0,7500" in r]
    assert len(qwk) == 1 and "Atingida" in qwk[0], cells(at)
    assert "Atingida" in row_with(at, "120,0001")
    flat = [c for r in cells(at) for c in r]
    texts = flat + values(at.markdown) + values(at.caption)
    assert contains(texts, "0,1235")
    assert contains(texts, "0,0200")
    assert contains(texts, "[0,6123; 0,7877]")
    for wrong in ("0,9313", "0,1234", "120,0000", "[0,6124; 0,7876]"):
        assert not contains(texts, wrong), wrong


# =============================================================================================
# CA-07: "Tentar novamente" keeps the cache (SEC-13-02)
# =============================================================================================


def test_ca07_retry_does_not_clear_the_cache(
    fake: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    clears: list[tuple[Any, ...]] = []
    original = st.cache_data.clear

    def spy(*args: Any, **kwargs: Any) -> None:
        clears.append(args)
        original(*args, **kwargs)

    monkeypatch.setattr(st.cache_data, "clear", spy)
    fake.timing_out = {"/metrics/timeseries"}
    at = page(OVERVIEW).run()
    assert not at.exception
    assert WAKING in values(at.warning)
    assert len(fake.to("/metrics/summary")) == 1

    fake.timing_out = set()
    fake.reset()
    [b for b in at.button if b.label == RETRY][0].click()
    run(at)

    assert clears == []
    assert fake.to("/metrics/summary") == []
    assert len(fake.to("/metrics/timeseries")) == 1
    assert len(at.get("plotly_chart")) == 3


# =============================================================================================
# CA-08: max_entries in the cache (SEC-13-05)
# =============================================================================================


def test_ca08_full_cache_drops_the_oldest_entry(fake: FakeApi) -> None:
    for k in range(257):
        data.fetch_summary(Filters(lot_id=f"L-{k:03d}"))
    assert len(fake.to("/metrics/summary")) == 257

    fake.reset()
    data.fetch_summary(Filters(lot_id="L-000"))
    assert len(fake.to("/metrics/summary")) == 1

    fake.reset()
    data.fetch_summary(Filters(lot_id="L-256"))
    assert fake.to("/metrics/summary") == []


# =============================================================================================
# CA-09: relative path in the public message (SEC-13-03)
# =============================================================================================


def test_ca09_missing_metrics_relative_and_absolute_path(
    fake: FakeApi, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MODEL_METRICS_PATH", "ml/models/nao-existe-v0/metrics.json")
    at = run(page(MODEL_PAGE))
    expected = (
        "Nenhum modelo avaliado ainda: metrics.json não encontrado em "
        "ml/models/nao-existe-v0/metrics.json."
    )
    assert expected in values(at.info)
    assert str(config.REPO_ROOT) not in dump(at)

    missing = tmp_path / "fora" / "metrics.json"
    monkeypatch.setenv("MODEL_METRICS_PATH", str(missing))
    at = run(page(MODEL_PAGE))
    assert f"Nenhum modelo avaliado ainda: metrics.json não encontrado em {missing}." in values(
        at.info
    )


# =============================================================================================
# CA-10: report_image stays inside ml/reports/ (SEC-13-08)
# =============================================================================================


def test_ca10_report_image_refuses_links_out_of_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    reports = root / "ml" / "reports"
    (reports / "partqc-ok-v1").mkdir(parents=True)
    (reports / "partqc-ok-v1" / "type_confusion.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "type_confusion.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (reports / "partqc-link-v1").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(config, "REPO_ROOT", root)

    ok = model_info.report_image("partqc-ok-v1", "type_confusion.png")
    assert ok is not None
    assert (
        config.resolve_repo_path(ok).resolve()
        == (reports / "partqc-ok-v1" / "type_confusion.png").resolve()
    )
    for version in ("partqc-link-v1", "...", "../x"):
        assert model_info.report_image(version, "type_confusion.png") is None, version


# =============================================================================================
# CA-11: local run with .streamlit/secrets.toml (SEC-13-04)
# =============================================================================================


def _code_block_lines(text: str) -> list[str]:
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            inside = not inside
            continue
        if inside:
            lines.append(line)
    return lines


def _check_ignore(path: str) -> int:
    return subprocess.run(  # noqa: S603 (fixed git command, no shell)
        ["git", "check-ignore", "-q", path],  # noqa: S607
        cwd=REPO_ROOT,
        check=False,
    ).returncode


def test_ca11_readme_env_example_and_gitignore() -> None:
    readme = (DASHBOARD / "README.md").read_text("utf-8")
    assert ".streamlit/secrets.toml" in readme
    assert not [line for line in _code_block_lines(readme) if "--env-file .env" in line]

    assert _check_ignore(".streamlit/secrets.toml") == 0
    assert _check_ignore(".streamlit/config.toml") == 1

    lines = (REPO_ROOT / ".env.example").read_text("utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("API_BASE_URL="))
    comments: list[str] = []
    for line in reversed(lines[:index]):
        if not line.startswith("#"):
            break
        comments.append(line)
    assert comments, "no comment right above API_BASE_URL="
    assert contains(comments, ".streamlit/secrets.toml")


# =============================================================================================
# Exploratory edge cases
# =============================================================================================


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost.example.org",
        "http://127.0.0.1.example.org:8001",
        "http://localhost:8001@example.org",
        "http://0.0.0.0:8001",
        "https:",
        "//example.org",
        "http://[::1",
        "javascript:alert(1)",
    ],
)
def test_extra_tricky_insecure_urls(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("READ_API_KEY", new_key())
    monkeypatch.setenv("API_BASE_URL", url)
    with pytest.raises(config.InsecureApiUrlError) as raised:
        config.get_settings()
    assert "example.org" not in str(raised.value)
    assert str(raised.value).startswith("API_BASE_URL")


@pytest.mark.parametrize("url", ["HTTP://LOCALHOST:8001", "  https://api.example.org  "])
def test_extra_case_and_spaces_accepted(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("READ_API_KEY", new_key())
    monkeypatch.setenv("API_BASE_URL", url)
    config.get_settings()


@pytest.mark.parametrize("path", [SPC_PAGE, HISTORY], ids=lambda p: p.stem)
def test_extra_insecure_url_on_other_api_pages(
    path: Path, monkeypatch: pytest.MonkeyPatch, sent: list[httpx.Request]
) -> None:
    monkeypatch.setenv("READ_API_KEY", new_key())
    monkeypatch.setenv("API_BASE_URL", "http://api.example.org")
    at = page(path).run()
    assert not at.exception
    assert INSECURE_FULL in values(at.error)
    assert sent == []
    assert "example.org" not in dump(at)


def test_extra_missing_key_wins_over_insecure_url(
    monkeypatch: pytest.MonkeyPatch, sent: list[httpx.Request]
) -> None:
    monkeypatch.setenv("API_BASE_URL", "http://api.example.org")
    at = page(OVERVIEW).run()
    assert not at.exception
    assert contains(values(at.error), "Configuração ausente")
    assert sent == []


def test_extra_model_page_with_insecure_url_and_all_sources(
    monkeypatch: pytest.MonkeyPatch,
    sent: list[httpx.Request],
    metrics_file: Callable[[Any], Path],
) -> None:
    """ConfigError on the badge check: message, badge and tables, without a request."""
    metrics_file(metrics_document())
    monkeypatch.setenv("READ_API_KEY", new_key())
    monkeypatch.setenv("API_BASE_URL", "http://api.example.org")
    at = with_sidebar_source(MODEL_PAGE, "Todos")
    assert INSECURE_FULL in values(at.error)
    assert contains(values(at.warning), BADGE)
    _model_tables_are_there(at)
    assert sent == []


def test_extra_model_page_server_error_keeps_tables(
    fake: FakeApi, metrics_file: Callable[[Any], Path]
) -> None:
    metrics_file(metrics_document())
    fake.failure = lambda r: httpx.Response(500, json={"detail": "Internal Server Error"})
    at = with_sidebar_source(MODEL_PAGE, "Todos")
    assert contains(values(at.error), "HTTP 500")
    assert contains(values(at.warning), BADGE)
    _model_tables_are_there(at)


def test_extra_model_page_retry_click_after_timeout(
    fake: FakeApi, metrics_file: Callable[[Any], Path]
) -> None:
    metrics_file(metrics_document())
    fake.failure = timeout_failure
    at = with_sidebar_source(MODEL_PAGE, "Todos")
    fake.failure = None
    fake.reset()
    [b for b in at.button if b.label == RETRY][0].click()
    run(at)
    assert WAKING not in values(at.warning)
    assert len(fake.to("/metrics/summary")) == 1
    assert not contains(values(at.warning), BADGE)  # simulated total is 0
    _model_tables_are_there(at)


@pytest.mark.parametrize("option", ["Real", "Simulado"])
def test_extra_model_page_real_or_simulated_without_requests(
    fake: FakeApi, metrics_file: Callable[[Any], Path], option: str
) -> None:
    metrics_file(metrics_document())
    fake.failure = timeout_failure
    at = run(page(MODEL_PAGE))
    if option != "Real":
        at.sidebar.radio(key="flt_source").set_value(option)
        run(at)
    assert fake.requests == []
    assert WAKING not in values(at.warning)


def test_extra_display_rule_float_noise_and_integers(
    fake: FakeApi, metrics_file: Callable[[Any], Path]
) -> None:
    """SPEC-028 section 7: 0.30000000000000004 in a lower-is-better metric shows 0,3001."""
    metrics_file(
        metrics_document(
            grade_mae=0.30000000000000004,
            needs_review_rate=0.1,
            latency_ms_p50=40.0,
            unusable_recall=0.89999,
            unusable_recall_ci95=[0.80009, 0.96001],
        )
    )
    at = run(page(MODEL_PAGE))
    flat = [c for r in cells(at) for c in r] + values(at.markdown) + values(at.caption)
    assert contains(flat, "0,3001")
    assert contains(flat, "0,1000")
    assert contains(flat, "40,0000")
    assert "Abaixo da meta" in row_with(at, "0,8999")  # 0.89999 < 0.90, floor
    assert contains(flat, "[0,8000; 0,9601]")
    assert contains(flat, "100")  # latency_runs, integer


def test_extra_spc_caption_right_under_title_and_after_failure(fake: FakeApi) -> None:
    at = run(page(SPC_PAGE))
    assert "Origem da carta: real" in values(at.caption)
    st.cache_data.clear()
    fake.failure = timeout_failure
    at = page(SPC_PAGE).run()
    assert not at.exception
    assert WAKING in values(at.warning)
    assert contains(values(at.caption), "Origem da carta:")


def test_extra_spc_badge_legend_not_in_sidebar_with_all(fake: FakeApi) -> None:
    fake.summaries["simulated"] = make_summary(total=12)
    at = with_sidebar_source(SPC_PAGE, "Todos")
    assert not contains(values(at.sidebar.caption), BADGE)
    assert not contains(values(at.sidebar.warning), BADGE)


def test_extra_overview_badge_rule_unchanged(fake: FakeApi) -> None:
    """SPEC-028 section 7: the overview keeps the badge from the global filters."""
    fake.summaries["simulated"] = make_summary(total=12)
    at = with_sidebar_source(OVERVIEW, "Todos")
    assert contains(values(at.main.warning), BADGE)


@pytest.mark.parametrize("version", ["..", ".", "....", "partqc-ok-v1/../x", "", None, 3])
def test_extra_report_image_bad_versions(
    version: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    (root / "ml" / "reports" / "partqc-ok-v1").mkdir(parents=True)
    (root / "ml" / "reports" / "type_confusion.png").write_bytes(b"x")
    monkeypatch.setattr(config, "REPO_ROOT", root)
    assert model_info.report_image(version, "type_confusion.png") is None


def test_extra_report_image_file_link_out_of_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    folder = root / "ml" / "reports" / "partqc-file-v1"
    folder.mkdir(parents=True)
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")
    (folder / "type_confusion.png").symlink_to(outside)
    monkeypatch.setattr(config, "REPO_ROOT", root)
    assert model_info.report_image("partqc-file-v1", "type_confusion.png") is None


def test_extra_every_cached_read_has_max_entries() -> None:
    source = (DASHBOARD / "src" / "qc_dashboard" / "data.py").read_text("utf-8")
    decorators = re.findall(r"@st\.cache_data\(([^)]*)\)", source)
    functions = re.findall(r"^def fetch_\w+", source, flags=re.MULTILINE)
    assert len(decorators) == len(functions) == 7
    for args in decorators:
        assert "max_entries" in args and "ttl" in args


def test_extra_no_secrets_toml_tracked() -> None:
    tracked = subprocess.run(  # noqa: S603
        ["git", "ls-files", ".streamlit/secrets.toml", "dashboard/.streamlit/secrets.toml"],  # noqa: S607
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert tracked.strip() == ""
