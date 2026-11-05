"""Acceptance tests for SPEC-044 (qc-dashboard: hammer, wrench and spirit level, never graded).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-09. Tests named ``test_extra_*`` are exploratory edge cases around
SPEC-044 section 3.1 (dashboard) that no CA spells out.

Pages are driven through ``streamlit.testing.v1.AppTest``; only the HTTP boundary is mocked
(``api.get_client`` returns a real ``ApiClient`` over ``httpx.MockTransport`` with contract
bodies). Read keys are generated at run time (R-03). No test touches the network nor runs pytest
in a subprocess (``docs/architecture.md`` section 10).
"""

from __future__ import annotations

import csv
import io
import re
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
from qc_dashboard import api, charts, filters, formatting
from qc_dashboard.api import ApiClient

pytestmark = pytest.mark.acceptance

DASHBOARD = Path(__file__).resolve().parents[2]
SPC_PAGE = DASHBOARD / "views" / "controle_estatistico.py"
HISTORY = DASHBOARD / "views" / "historico.py"
BASE = "https://api.test"
PREFIX = "/api/v1"
SHA = "e" * 64
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
NEW_TOOLS = ["hammer", "wrench", "spirit_level"]
NEW_LABELS = ["martelo", "chave de aperto", "nível"]
# The SPC type filter of SPEC-016 (CA-05 there: the SpcObjectType values), unchanged.
SPC_TYPES_016 = ["screw", "nut", *HAND_TOOLS]


def make_inspection(**overrides: Any) -> InspectionRead:
    values: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-044",
        "inspected_at": "2026-11-04T15:00:00Z",
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
        "received_at": "2026-11-04T15:00:01Z",
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


def _value(item: Any) -> str:
    """Code value of an ``ObjectType`` member or of a string."""
    return item.value if isinstance(item, ObjectType) else str(item)


def _strings(obj: Any) -> list[str]:
    """Every string inside ``obj`` (flattening tuples, lists, dicts and enum members)."""
    if isinstance(obj, ObjectType):
        return [obj.value]
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for k, v in obj.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(obj, list | tuple | set | frozenset):
        return [s for x in obj for s in _strings(x)]
    return [str(obj)]


class FakeApi:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.items: list[InspectionRead] = [
            ungraded("wrench"),
            ungraded("hammer", source="simulated"),
            ungraded("spirit_level"),
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


# --------------------------------------------------------------------------- CA-09


def test_ca09_history_row_of_a_wrench_without_grade() -> None:
    (row,) = formatting.history_rows([ungraded("wrench")])
    assert row["Tipo"] == "chave de aperto"
    assert row["Grau"] == "sem grau"


def test_ca09_chart_order_has_each_of_the_15_types_once() -> None:
    order = [_value(t) for t in charts.OBJECT_TYPE_ORDER]
    assert len(ObjectType) == 15
    assert len(order) == 15
    assert sorted(order) == sorted(m.value for m in ObjectType)


def test_ca09_chart_colors_have_15_keys_and_15_distinct_colors() -> None:
    colors = charts.OBJECT_TYPE_COLORS
    assert len(colors) == 15
    keys = {_value(k) for k in colors}
    labels = {OBJECT_TYPE_LABELS_PT[m] for m in ObjectType}
    assert keys == {m.value for m in ObjectType} or keys == labels, keys
    normalized = {str(c).strip().lower() for c in colors.values()}
    assert len(normalized) == 15


def test_ca09_history_type_filter_offers_the_new_labels() -> None:
    options = _strings(filters.TYPE_OPTIONS)
    for label in NEW_LABELS:
        assert label in options, (label, filters.TYPE_OPTIONS)


def test_ca09_spc_type_filter_is_the_spec016_one() -> None:
    assert [_value(t) for t in filters.SPC_OBJECT_TYPES] == SPC_TYPES_016


# --------------------------------------------------------------------------- extras


@pytest.mark.parametrize(("code", "label"), list(zip(NEW_TOOLS, NEW_LABELS, strict=True)))
def test_extra_every_new_tool_in_history_and_label(code: str, label: str) -> None:
    (row,) = formatting.history_rows([ungraded(code)])
    assert (row["Tipo"], row["Grau"]) == (label, "sem grau")
    assert row["Defeituosa"] == "Não"
    assert formatting.object_type_label(ObjectType(code)) == label
    assert formatting.object_type_label(code) == label


def test_extra_new_tools_come_after_the_power_tools_and_before_unknown() -> None:
    order = [_value(t) for t in charts.OBJECT_TYPE_ORDER]
    idx = [order.index(t) for t in NEW_TOOLS]
    assert idx == sorted(idx)
    assert idx[-1] - idx[0] == 2
    assert idx[0] > max(order.index(t) for t in POWER_TOOLS)
    assert idx[-1] < order.index("unknown")
    earlier = ["screw", "nut", *HAND_TOOLS, *POWER_TOOLS, "unknown"]
    assert [t for t in order if t in earlier] == earlier


def test_extra_new_colors_are_valid_and_distinct_from_the_earlier_ones() -> None:
    colors = {_value(k): str(v).strip().lower() for k, v in charts.OBJECT_TYPE_COLORS.items()}
    if set(colors) != {m.value for m in ObjectType}:  # keyed by PT-BR label
        by_label = {OBJECT_TYPE_LABELS_PT[m]: m.value for m in ObjectType}
        colors = {by_label[k]: v for k, v in colors.items()}
    for tool in NEW_TOOLS:
        assert re.fullmatch(r"#[0-9a-f]{6}", colors[tool]), colors[tool]
    earlier = {v for k, v in colors.items() if k not in NEW_TOOLS}
    assert not {colors[t] for t in NEW_TOOLS} & earlier


def test_extra_history_csv_of_a_spirit_level() -> None:
    text = formatting.history_csv([ungraded("spirit_level")]).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    row = dict(zip(rows[0], rows[1], strict=True))
    assert row["Tipo"] == "nível"
    assert row["Grau"] in ("sem grau", "")
    assert "spirit_level" not in rows[1]


def test_extra_by_object_type_chart_lists_the_new_tools() -> None:
    fig = charts.by_object_type({"screw": 3, "wrench": 2, "spirit_level": 1})
    bar = fig.data[0]
    values = dict(zip(list(bar.y), bar.x, strict=True))
    assert values["chave de aperto"] == 2 and values["nível"] == 1 and values["parafuso"] == 3
    assert values["martelo"] == 0
    assert not set(bar.y) & set(NEW_TOOLS)


def test_extra_history_page_shows_the_new_tools_and_the_source(fake: FakeApi) -> None:
    at = run(AppTest.from_file(str(HISTORY), default_timeout=60))
    frame = [el.value for el in [*at.dataframe, *at.table]][0]
    rows = frame.to_dict("records")
    assert [r["Tipo"] for r in rows] == ["chave de aperto", "martelo", "nível", "parafuso"]
    assert [r["Grau"] for r in rows] == ["sem grau", "sem grau", "sem grau", "ruim"]
    shown = " ".join(str(v) for r in rows for v in r.values())
    assert "simulad" in shown.lower()  # R-06
    for code in NEW_TOOLS:
        assert code not in " ".join(str(r["Tipo"]) for r in rows)


def test_extra_spc_page_type_filter_never_offers_a_new_tool(fake: FakeApi) -> None:
    at = run(AppTest.from_file(str(SPC_PAGE), default_timeout=60))
    options = list(at.selectbox(key="spc_type").options)
    assert options == ["Todos", "parafuso", "porca", *HAND_LABELS]
    for label in NEW_LABELS:
        assert label not in options
