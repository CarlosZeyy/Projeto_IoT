"""Acceptance tests for SPEC-043, the ``dashboard/`` part: CA-11 (E2E-01) and CA-19 (OBS-01).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. ``test_extra_*`` tests are exploratory edge cases that no CA spells out. CA-12 is
a rehearsal outside the suite, recorded in the test report.

Pages are driven through ``streamlit.testing.v1.AppTest``. Only the HTTP boundary is mocked:
``api.get_client`` returns a real ``ApiClient`` over ``httpx.MockTransport``. Read keys are
generated at run time (R-03). No test touches the network.
"""

from __future__ import annotations

import csv
import io
import json
import secrets
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from qc_contracts import HealthResponse, InspectionRead, LotSummary, MetricsSummary, Page
from qc_dashboard import api, formatting
from qc_dashboard.api import ApiClient

pytestmark = pytest.mark.acceptance

DASHBOARD = Path(__file__).resolve().parents[2]
VIEWS = DASHBOARD / "views"
OVERVIEW = VIEWS / "visao_geral.py"
HISTORY = VIEWS / "historico.py"
SPC_PAGE = VIEWS / "controle_estatistico.py"
BASE = "https://api.test"
PREFIX = "/api/v1"
MODEL = "partqc-mnv3-provisional-v1"
BADGE = "Contém dados simulados"
RETRY = "Tentar novamente"
AUTH_ERROR = "Chave de leitura inválida ou ausente (READ_API_KEY)."
UNAVAILABLE = (
    "API indisponível: pode ser uma queda da API ou do banco. "
    "Tente de novo em ~1 min; se continuar, confira o servidor."
)
CONFIG_VARS = ("API_BASE_URL", "READ_API_KEY", "MODEL_METRICS_PATH")
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


def make_inspection(**overrides: Any) -> InspectionRead:
    values: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "sim-01",
        "lot_id": "SIM-20261102-001",
        "inspected_at": "2026-11-02T15:00:00Z",
        "object_type": "nut",
        "grade": "poor",
        "grade_score": 2.75,
        "type_confidence": 0.875,
        "grade_confidence": 0.61,
        "needs_review": True,
        "model_version": MODEL,
        "model_sha256": "c" * 64,
        "latency_ms": 37,
        "source": "simulated",
        "received_at": "2026-11-02T15:00:02Z",
        "is_defective": True,
    }
    values.update(overrides)
    return InspectionRead.model_validate(values)


def make_summary() -> MetricsSummary:
    return MetricsSummary.model_validate(
        {
            "total": 1,
            "defective": 1,
            "defect_rate": 1.0,
            "unknown_count": 0,
            "needs_review_count": 1,
            "by_grade": {"perfect": 0, "good": 0, "fair": 0, "poor": 1, "unusable": 0},
            "by_object_type": {"screw": 0, "nut": 1, "unknown": 0},
            "mean_type_confidence": 0.875,
            "mean_grade_score": 2.75,
        }
    )


class FakeApi:
    """Answers the read routes with contract bodies; ``failure`` replaces every answer."""

    def __init__(self) -> None:
        self.items: list[InspectionRead] = [make_inspection()]
        self.requests: list[httpx.Request] = []
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
            return httpx.Response(200, json=make_summary().model_dump(mode="json"))
        if path == f"{PREFIX}/metrics/timeseries":
            return httpx.Response(200, json=[])
        if path == f"{PREFIX}/inspections":
            page = Page[InspectionRead](
                items=self.items,
                total=len(self.items),
                limit=int(params["limit"]),
                offset=int(params["offset"]),
            )
            return httpx.Response(200, json=page.model_dump(mode="json"))
        if path == f"{PREFIX}/lots":
            page = Page[LotSummary](items=[], total=0, limit=50, offset=0)
            return httpx.Response(200, json=page.model_dump(mode="json"))
        return httpx.Response(404, json={"detail": "Not Found"})


class NoSecretsFile:
    def __contains__(self, key: object) -> bool:
        raise FileNotFoundError("No secrets found")

    def __getitem__(self, key: str) -> object:
        raise FileNotFoundError("No secrets found")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
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
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeApi:
    mock = FakeApi()
    client = ApiClient(
        BASE, "k-" + secrets.token_hex(8), transport=httpx.MockTransport(mock.handler)
    )
    monkeypatch.setattr(api, "get_client", lambda: client)
    return mock


def page(path: Path) -> AppTest:
    return AppTest.from_file(str(path), default_timeout=60)


def run(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def values(elements: Any) -> list[str]:
    return [str(e.value) for e in elements]


def history_as_simulated(fake: FakeApi) -> AppTest:
    at = run(page(HISTORY))
    at.sidebar.radio(key="flt_source").set_value("Simulado")
    return run(at)


def raise_read_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


def raise_connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


def answer(status: int) -> Callable[[httpx.Request], httpx.Response]:
    def _answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": "x"})

    return _answer


FAILURES = {
    "read-timeout": raise_read_timeout,
    "connect-error": raise_connect_error,
    "http-503": answer(503),
}


# --------------------------------------------------------------------------- CA-11


def test_ca11_model_column_is_240_px_with_everything_else_intact(fake: FakeApi) -> None:
    at = history_as_simulated(fake)

    assert len(at.dataframe) >= 1
    frame = at.dataframe[0]
    columns = json.loads(frame.proto.columns)
    assert columns["Modelo"]["width"] == 240
    assert list(frame.value.columns) == list(formatting.HISTORY_COLUMNS)
    assert list(formatting.HISTORY_COLUMNS) == HISTORY_COLUMNS
    row = frame.value.iloc[0]
    assert row["Modelo"] == MODEL
    assert row["Origem"] == "simulado"
    assert any(BADGE in text for text in values(at.main.warning))


def test_extra_width_constant_and_only_the_model_column_is_configured(fake: FakeApi) -> None:
    """Section 4.3: "Nada mais muda"."""
    at = history_as_simulated(fake)

    assert formatting.MODEL_COLUMN_WIDTH_PX == 240
    # "_index" is the hide_index setting, which already existed.
    assert set(json.loads(at.dataframe[0].proto.columns)) - {"_index"} == {"Modelo"}


def test_extra_the_csv_is_unchanged_by_the_width() -> None:
    """The CSV keeps its columns and order, with the model whole (section 4.3)."""
    text = formatting.history_csv([make_inspection()]).decode("utf-8-sig")

    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert rows[0] == HISTORY_COLUMNS
    assert rows[1][HISTORY_COLUMNS.index("Modelo")] == MODEL
    assert rows[1][HISTORY_COLUMNS.index("Origem")] == "simulado"


def test_extra_model_column_with_the_longest_contract_name_stays_whole(fake: FakeApi) -> None:
    """The contract allows 40 characters: the value stays whole in the frame."""
    long_name = "partqc-" + "x" * 33
    fake.items = [make_inspection(model_version=long_name)]

    at = history_as_simulated(fake)

    assert at.dataframe[0].value.iloc[0]["Modelo"] == long_name


# --------------------------------------------------------------------------- CA-19


@pytest.mark.parametrize("failure", list(FAILURES))
@pytest.mark.parametrize("path", [OVERVIEW, HISTORY], ids=lambda p: p.stem)
def test_ca19_unavailable_notice_and_retry_recovers(
    fake: FakeApi, path: Path, failure: str
) -> None:
    fake.failure = FAILURES[failure]

    at = page(path).run()

    assert not at.exception, [e.value for e in at.exception]
    assert UNAVAILABLE in values(at.warning)
    retry = [b for b in at.button if b.label == RETRY]
    assert len(retry) == 1

    fake.failure = None
    fake.requests.clear()
    retry[0].click()
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert UNAVAILABLE not in values(at.warning)
    assert fake.requests, "the retry did not read the API"
    if path == HISTORY:
        assert len(at.dataframe) == 1
        assert at.dataframe[0].value.iloc[0]["Modelo"] == MODEL
    else:
        assert at.get("plotly_chart") or at.metric, "the overview shows no data after the retry"


@pytest.mark.parametrize("path", [OVERVIEW, HISTORY], ids=lambda p: p.stem)
def test_ca19_401_shows_the_key_message_without_the_notice(fake: FakeApi, path: Path) -> None:
    fake.failure = answer(401)

    at = page(path).run()

    assert not at.exception, [e.value for e in at.exception]
    assert AUTH_ERROR in values(at.error)
    assert UNAVAILABLE not in values(at.warning)
    assert not any(b.label == RETRY for b in at.button)


@pytest.mark.parametrize(
    "relative",
    ["src/qc_dashboard/filters.py", "README.md"],
)
def test_ca19_the_old_words_are_gone(relative: str) -> None:
    text = (DASHBOARD / relative).read_text(encoding="utf-8").lower()
    assert "acordando" not in text
    assert "free tier" not in text


def test_ca19_constant_has_the_exact_value() -> None:
    from qc_dashboard import filters

    assert filters.API_UNAVAILABLE_TEXT == UNAVAILABLE
    assert not hasattr(filters, "API_WAKING_TEXT")


def test_ca19_readme_cites_the_new_text() -> None:
    assert UNAVAILABLE in (DASHBOARD / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("status", [502, 504])
@pytest.mark.parametrize("path", [OVERVIEW, HISTORY, SPC_PAGE], ids=lambda p: p.stem)
def test_extra_other_gateway_statuses_show_the_same_notice(
    fake: FakeApi, path: Path, status: int
) -> None:
    fake.failure = answer(status)

    at = page(path).run()

    assert not at.exception, [e.value for e in at.exception]
    assert UNAVAILABLE in values(at.warning)
    assert [b.label for b in at.button if b.label == RETRY] == [RETRY]


def test_extra_no_automatic_retry(fake: FakeApi) -> None:
    fake.failure = raise_read_timeout

    page(HISTORY).run()

    assert len(fake.requests) == 1


def test_extra_retry_while_still_down_keeps_the_notice(fake: FakeApi) -> None:
    fake.failure = answer(503)
    at = page(HISTORY).run()
    [b for b in at.button if b.label == RETRY][0].click()
    at.run()

    assert not at.exception
    assert UNAVAILABLE in values(at.warning)


def test_extra_no_page_source_still_uses_the_old_name() -> None:
    for path in [*VIEWS.rglob("*.py"), *(DASHBOARD / "src").rglob("*.py"), DASHBOARD / "app.py"]:
        text = path.read_text(encoding="utf-8")
        assert "API_WAKING_TEXT" not in text, path
        assert "acordando" not in text.lower(), path
