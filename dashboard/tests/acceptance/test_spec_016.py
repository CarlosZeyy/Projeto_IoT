"""Acceptance tests for SPEC-016 (qc-dashboard: hand tools, "sem grau" and the SPC type filter).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-12. Tests named ``test_extra_*`` are exploratory edge cases around
SPEC-016 section 4.5 that no CA spells out.

Pages are driven through ``streamlit.testing.v1.AppTest``; only the HTTP boundary is mocked
(``api.get_client`` returns a real ``ApiClient`` over ``httpx.MockTransport`` with contract
bodies). Read keys are generated at run time (R-03). No test touches the network nor runs pytest
in a subprocess (``docs/architecture.md`` section 10).
"""

from __future__ import annotations

import csv
import io
import secrets
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from qc_contracts import (
    OBJECT_TYPE_LABELS_PT,
    InspectionRead,
    MetricsSummary,
    ObjectType,
    Page,
    SpcResponse,
)
from qc_dashboard import api, charts, formatting
from qc_dashboard.api import ApiClient

pytestmark = pytest.mark.acceptance

DASHBOARD = Path(__file__).resolve().parents[2]
SPC_PAGE = DASHBOARD / "views" / "controle_estatistico.py"
HISTORY = DASHBOARD / "views" / "historico.py"
BASE = "https://api.test"
PREFIX = "/api/v1"
SHA = "d" * 64
CONFIG_VARS = ("API_BASE_URL", "READ_API_KEY", "MODEL_METRICS_PATH")
TOOLS = ["pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver"]
TOOL_LABELS = ["alicate", "chave inglesa", "chave Allen", "chave de fenda", "chave Phillips"]


def make_inspection(**overrides: Any) -> InspectionRead:
    values: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-016",
        "inspected_at": "2026-11-03T15:00:00Z",
        "object_type": "screw",
        "grade": "poor",
        "grade_score": 2.9,
        "type_confidence": 0.9,
        "grade_confidence": 0.7,
        "needs_review": False,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "latency_ms": 30,
        "source": "live",
        "received_at": "2026-11-03T15:00:01Z",
        "is_defective": True,
    }
    values.update(overrides)
    return InspectionRead.model_validate(values)


def ungraded(object_type: str, **overrides: Any) -> InspectionRead:
    return make_inspection(
        object_type=object_type,
        grade=None,
        grade_score=None,
        grade_confidence=None,
        is_defective=False,
        **overrides,
    )


def ca12_items() -> list[InspectionRead]:
    return [ungraded("pliers"), ungraded("unknown"), make_inspection()]


class FakeApi:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.items: list[InspectionRead] = ca12_items()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        params = request.url.params
        if path == f"{PREFIX}/metrics/spc":
            body = SpcResponse.model_validate(
                {
                    "baseline_lots": 20,
                    "min_lot_size": 5,
                    "source": params.get("source", "live"),
                    "p_bar": None,
                    "points": [],
                    "excluded_lots": [],
                    "message": "insufficient data: at least 2 valid lots (found 0)",
                    "max_points": 100,
                    "valid_lots_total": 0,
                    "excluded_lots_total": 0,
                }
            )
            return httpx.Response(200, json=body.model_dump(mode="json"))
        if path == f"{PREFIX}/metrics/summary":
            summary = MetricsSummary.model_validate(
                {
                    "total": 0,
                    "defective": 0,
                    "defect_rate": None,
                    "unknown_count": 0,
                    "needs_review_count": 0,
                    "by_grade": {},
                    "by_object_type": {},
                    "mean_type_confidence": None,
                    "mean_grade_score": None,
                }
            )
            return httpx.Response(200, json=summary.model_dump(mode="json"))
        if path == f"{PREFIX}/inspections":
            page = Page[InspectionRead](
                items=self.items,
                total=len(self.items),
                limit=int(params["limit"]),
                offset=int(params["offset"]),
            )
            return httpx.Response(200, json=page.model_dump(mode="json"))
        return httpx.Response(404, json={"detail": "Not Found"})

    def spc_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == f"{PREFIX}/metrics/spc"]


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
    key = f"k-{secrets.token_hex(8)}"
    client = ApiClient(BASE, key, transport=httpx.MockTransport(mock.handler))
    monkeypatch.setattr(api, "get_client", lambda: client)
    return mock


def run(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


# --------------------------------------------------------------------------- CA-12


def test_ca12_history_rows_type_and_grade_columns() -> None:
    rows = formatting.history_rows(ca12_items())
    assert [r["Tipo"] for r in rows] == ["alicate", "desconhecido", "parafuso"]
    assert [r["Grau"] for r in rows] == ["sem grau", "—", "ruim"]


def test_ca12_object_type_label_of_each_tool() -> None:
    for tool, label in zip(TOOLS, TOOL_LABELS, strict=True):
        assert formatting.object_type_label(ObjectType(tool)) == label
        assert formatting.object_type_label(tool) == label
        assert label == OBJECT_TYPE_LABELS_PT[ObjectType(tool)]


# --------------------------------------------------------------------------- extras


def test_extra_object_type_label_covers_the_8_types() -> None:
    for member in ObjectType:
        assert formatting.object_type_label(member) == OBJECT_TYPE_LABELS_PT[member]


@pytest.mark.parametrize("tool", TOOLS)
def test_extra_every_tool_with_and_without_grade_in_history(tool: str) -> None:
    rows = formatting.history_rows(
        [ungraded(tool), make_inspection(object_type=tool, grade="good", is_defective=False)]
    )
    label = OBJECT_TYPE_LABELS_PT[ObjectType(tool)]
    assert [r["Tipo"] for r in rows] == [label, label]
    assert [r["Grau"] for r in rows] == ["sem grau", "bom"]
    assert rows[0]["Defeituosa"] == "Não"


def test_extra_history_csv_of_an_ungraded_tool() -> None:
    text = formatting.history_csv([ungraded("allen_key"), ungraded("unknown")]).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    header = rows[0]
    tool = dict(zip(header, rows[1], strict=True))
    unknown = dict(zip(header, rows[2], strict=True))
    assert tool["Tipo"] == "chave Allen"
    assert tool["Grau"] in ("sem grau", "")
    assert unknown["Grau"] == ""  # SPEC-013 CA-20 unchanged for unknown


def test_extra_object_type_order_and_colors() -> None:
    order = [ObjectType(t).value for t in charts.OBJECT_TYPE_ORDER]
    # SPEC-021 section 3.1: the 4 power tools also have a place in the order (between the
    # hand tools and unknown); the relative order of these 8 types is unchanged.
    power = {"angle_grinder", "saw", "drill", "cordless_screwdriver"}
    assert set(order) == {m.value for m in ObjectType}
    assert [t for t in order if t not in power] == ["screw", "nut", *TOOLS, "unknown"]
    colors = charts.OBJECT_TYPE_COLORS
    keys = {ObjectType(k).value if not isinstance(k, str) else k for k in colors}
    labels = {OBJECT_TYPE_LABELS_PT[ObjectType(t)] for t in order}
    assert set(order) <= keys or labels <= keys, colors
    assert len(set(colors.values())) == len(colors)


def test_extra_by_object_type_chart_lists_the_tools() -> None:
    fig = charts.by_object_type({"screw": 3, "pliers": 2, "allen_key": 1})
    bar = fig.data[0]
    labels = list(bar.y)
    assert "alicate" in labels and "chave Allen" in labels
    values = dict(zip(labels, bar.x, strict=True))
    assert values["alicate"] == 2 and values["chave Allen"] == 1 and values["parafuso"] == 3


def test_extra_history_page_shows_sem_grau(fake: FakeApi) -> None:
    at = run(AppTest.from_file(str(HISTORY), default_timeout=60))
    frame = [el.value for el in [*at.dataframe, *at.table]][0]
    rows = frame.to_dict("records")
    assert [r["Tipo"] for r in rows] == ["alicate", "desconhecido", "parafuso"]
    assert [r["Grau"] for r in rows] == ["sem grau", "—", "ruim"]


def test_extra_spc_type_filter_offers_the_spc_object_types(fake: FakeApi) -> None:
    at = run(AppTest.from_file(str(SPC_PAGE), default_timeout=60))
    options = list(at.selectbox(key="spc_type").options)
    assert options == ["Todos", "parafuso", "porca", *TOOL_LABELS]
    assert "desconhecido" not in options


@pytest.mark.parametrize(("label", "code"), list(zip(TOOL_LABELS, TOOLS, strict=True)))
def test_extra_spc_type_filter_sends_the_tool_code(fake: FakeApi, label: str, code: str) -> None:
    at = run(AppTest.from_file(str(SPC_PAGE), default_timeout=60))
    fake.requests.clear()
    at.selectbox(key="spc_type").set_value(label)
    run(at)
    sent = [dict(r.url.params) for r in fake.spc_requests()]
    assert len(sent) == 1, sent
    assert sent[0]["object_type"] == code
    assert sent[0]["source"] == "live"


def test_extra_ui_never_shows_raw_tool_codes(fake: FakeApi) -> None:
    at = run(AppTest.from_file(str(HISTORY), default_timeout=60))
    frame = [el.value for el in [*at.dataframe, *at.table]][0]
    shown = " ".join(str(v) for v in frame["Tipo"].tolist())
    for code in TOOLS:
        assert code not in shown
