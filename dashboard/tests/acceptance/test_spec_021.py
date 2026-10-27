"""Acceptance tests for SPEC-021 (qc-dashboard: labels, colors and "sem grau" of the power tools).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-08. Tests named ``test_extra_*`` are exploratory edge cases around
SPEC-021 sections 3.1 and 4 that no CA spells out.

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
HAND_TOOLS = [
    "pliers",
    "adjustable_wrench",
    "allen_key",
    "flat_screwdriver",
    "phillips_screwdriver",
]
HAND_LABELS = ["alicate", "chave inglesa", "chave Allen", "chave de fenda", "chave Phillips"]
POWER_TOOLS = ["angle_grinder", "saw", "drill", "cordless_screwdriver"]
POWER_LABELS = ["esmerilhadeira", "serra", "furadeira", "parafusadeira"]


def make_inspection(**overrides: Any) -> InspectionRead:
    values: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-021",
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


class FakeApi:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.items: list[InspectionRead] = [
            ungraded("drill"),
            ungraded("angle_grinder", source="simulated"),
            make_inspection(),
        ]

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


# --------------------------------------------------------------------------- CA-08


def test_ca08_history_row_of_a_drill_without_grade() -> None:
    (row,) = formatting.history_rows([ungraded("drill")])
    assert row["Tipo"] == "furadeira"
    assert row["Grau"] == "sem grau"


# --------------------------------------------------------------------------- extras


@pytest.mark.parametrize(("code", "label"), list(zip(POWER_TOOLS, POWER_LABELS, strict=True)))
def test_extra_every_power_tool_in_history_and_label(code: str, label: str) -> None:
    (row,) = formatting.history_rows([ungraded(code)])
    assert (row["Tipo"], row["Grau"]) == (label, "sem grau")
    assert row["Defeituosa"] == "Não"
    assert formatting.object_type_label(ObjectType(code)) == label
    assert formatting.object_type_label(code) == label
    assert OBJECT_TYPE_LABELS_PT[ObjectType(code)] == label


def test_extra_object_type_label_covers_the_12_types() -> None:
    assert len(ObjectType) == 12
    for member in ObjectType:
        assert formatting.object_type_label(member) == OBJECT_TYPE_LABELS_PT[member]


def test_extra_history_csv_of_a_power_tool() -> None:
    text = formatting.history_csv([ungraded("saw"), ungraded("unknown")]).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    header = rows[0]
    saw = dict(zip(header, rows[1], strict=True))
    unknown = dict(zip(header, rows[2], strict=True))
    assert saw["Tipo"] == "serra"
    assert saw["Grau"] in ("sem grau", "")
    assert "saw" not in rows[1]
    assert unknown["Grau"] == ""  # SPEC-013 CA-20 unchanged for unknown


def test_extra_chart_order_and_distinct_colors_with_the_power_tools() -> None:
    order = [ObjectType(t).value for t in charts.OBJECT_TYPE_ORDER]
    assert set(order) == {m.value for m in ObjectType}
    assert len(order) == 12
    # The SPEC-016 relative order is kept and the power tools come together after the hand tools.
    assert [t for t in order if t not in POWER_TOOLS] == ["screw", "nut", *HAND_TOOLS, "unknown"]
    idx = [order.index(t) for t in POWER_TOOLS]
    assert idx == sorted(idx) and idx[-1] - idx[0] == 3
    assert idx[0] > order.index("phillips_screwdriver")
    colors = charts.OBJECT_TYPE_COLORS
    keys = {ObjectType(k).value if not isinstance(k, str) else k for k in colors}
    labels = {OBJECT_TYPE_LABELS_PT[ObjectType(t)] for t in order}
    assert set(order) <= keys or labels <= keys, colors
    assert len(set(colors.values())) == len(colors)


def test_extra_by_object_type_chart_lists_the_power_tools() -> None:
    fig = charts.by_object_type({"screw": 3, "drill": 2, "cordless_screwdriver": 1})
    bar = fig.data[0]
    values = dict(zip(list(bar.y), bar.x, strict=True))
    assert values["furadeira"] == 2 and values["parafusadeira"] == 1 and values["parafuso"] == 3
    assert values["serra"] == 0 and values["esmerilhadeira"] == 0
    assert not set(bar.y) & set(POWER_TOOLS)


def test_extra_history_page_shows_the_power_tools_and_the_source(fake: FakeApi) -> None:
    at = run(AppTest.from_file(str(HISTORY), default_timeout=60))
    frame = [el.value for el in [*at.dataframe, *at.table]][0]
    rows = frame.to_dict("records")
    assert [r["Tipo"] for r in rows] == ["furadeira", "esmerilhadeira", "parafuso"]
    assert [r["Grau"] for r in rows] == ["sem grau", "sem grau", "ruim"]
    shown = " ".join(str(v) for r in rows for v in r.values())
    assert "simulad" in shown.lower()  # R-06: the simulated power tool stays visible as such
    for code in POWER_TOOLS:
        assert code not in " ".join(str(r["Tipo"]) for r in rows)


def test_extra_spc_type_filter_never_offers_a_power_tool(fake: FakeApi) -> None:
    at = run(AppTest.from_file(str(SPC_PAGE), default_timeout=60))
    options = list(at.selectbox(key="spc_type").options)
    assert options == ["Todos", "parafuso", "porca", *HAND_LABELS]
    for label in POWER_LABELS:
        assert label not in options
