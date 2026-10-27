"""Pure parts of ``qc_dashboard.filters`` and the cache of ``qc_dashboard.data``.

SPEC-013 and SPEC-028 (§4.2 and §4.3).
"""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
import streamlit as st

from qc_contracts import (
    GRADE_OPTIONAL_OBJECT_TYPES,
    GRADE_REQUIRED_OBJECT_TYPES,
    ObjectType,
    Source,
)
from qc_dashboard import data, filters
from qc_dashboard.api import ApiUnavailable, Filters


def test_period_to_utc_uses_sao_paulo_days() -> None:
    from_, to = filters.period_to_utc(date(2026, 11, 1), date(2026, 11, 7))
    assert from_ == datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
    assert to == datetime(2026, 11, 8, 3, 0, tzinfo=UTC)
    assert filters.period_to_utc(date(2026, 11, 7), date(2026, 11, 1)) == (from_, to)


def test_period_bounds_while_editing() -> None:
    assert filters._period_bounds((date(2026, 11, 1),)) == (date(2026, 11, 1), date(2026, 11, 1))
    assert filters._period_bounds(date(2026, 11, 2)) == (date(2026, 11, 2), date(2026, 11, 2))
    assert filters._period_bounds(()) == filters.default_period()


def test_default_period_is_seven_days() -> None:
    start, end = filters.default_period()
    assert (end - start).days == 6
    assert end == filters.local_today()


@pytest.mark.parametrize(
    ("text", "valid"),
    [("L-01", True), ("a_b-9", True), ("L 01", False), ("L-01\n", False), ("x" * 41, False)],
)
def test_valid_lot_id(text: str, valid: bool) -> None:
    assert filters.valid_lot_id(text) is valid


def test_source_caption() -> None:
    assert filters.source_caption(Filters(source="live")) == "Origem dos dados: real"
    assert filters.source_caption(Filters(source="simulated")) == "Origem dos dados: simulado"
    assert filters.source_caption(Filters()) == "Origem dos dados: todas (real + simulado)"


def test_badge_real_and_simulated_need_no_request(mock_api) -> None:
    assert filters.needs_simulated_badge(Filters(source="live")) is False
    assert filters.needs_simulated_badge(Filters(source="simulated")) is True
    assert mock_api.requests == []


def test_badge_all_asks_for_simulated_with_same_filters(mock_api, factory) -> None:
    mock_api.summary_simulated = factory.summary(total=12)
    selected = Filters(lot_id="L-1", object_type="nut")
    assert filters.needs_simulated_badge(selected) is True
    (request,) = mock_api.requests
    expected = {"source": "simulated", "object_type": "nut", "lot_id": "L-1"}
    assert dict(request.url.params) == expected

    data.fetch_summary.clear()
    mock_api.summary_simulated = factory.summary(total=0)
    assert filters.needs_simulated_badge(selected) is False


def test_fetch_summary_is_cached(mock_api) -> None:
    selected = Filters(source="live")
    first = data.fetch_summary(selected)
    second = data.fetch_summary(Filters(source="live"))
    assert first == second
    assert len(mock_api.requests) == 1
    data.fetch_summary(Filters(source="simulated"))
    assert len(mock_api.requests) == 2
    st.cache_data.clear()
    data.fetch_summary(selected)
    assert len(mock_api.requests) == 3


def test_fetch_spc_and_inspections_are_cached(mock_api) -> None:
    for _ in range(2):
        data.fetch_spc("live", None, 20, 5, 100)
        data.fetch_inspections(Filters(), 50, 0)
    assert len(mock_api.to("/metrics/spc")) == 1
    assert len(mock_api.to("/inspections")) == 1


def test_errors_are_not_cached(mock_api, factory) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    mock_api.failure = timeout
    with pytest.raises(ApiUnavailable):
        data.fetch_summary(Filters())
    mock_api.failure = None
    assert data.fetch_summary(Filters()).total == 40
    assert len(mock_api.requests) == 2


# ---------- SPEC-028 §4.2 and §4.3 ----------


def test_chart_badge_follows_only_the_chart_origin(mock_api) -> None:
    assert filters.render_chart_badge(Source.SIMULATED) is True
    assert filters.render_chart_badge(Source.LIVE) is False
    assert mock_api.requests == []


def test_spc_origin_caption() -> None:
    assert filters.spc_origin_caption(Source.LIVE) == "Origem da carta: real"
    assert filters.spc_origin_caption("simulated") == "Origem da carta: simulado"


def test_badge_or_error_does_not_raise_and_is_conservative(mock_api) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    mock_api.failure = timeout
    assert filters.render_badge_or_error(Filters()) is True
    mock_api.failure = lambda request: httpx.Response(401, json={"detail": "x"})
    assert filters.render_badge_or_error(Filters()) is True
    mock_api.failure = None
    assert filters.render_badge_or_error(Filters()) is False
    assert filters.render_badge_or_error(Filters(source="simulated")) is True


def test_badge_or_error_without_configuration(no_config_env) -> None:
    assert filters.render_badge_or_error(Filters()) is True
    assert filters.render_badge_or_error(Filters(source="live")) is False


def test_retry_only_reruns(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(st.cache_data, "clear", lambda: calls.append("clear"))
    monkeypatch.setattr(st, "rerun", lambda: calls.append("rerun"))
    filters._retry()
    assert calls == ["rerun"]


def test_every_cached_read_has_max_entries() -> None:
    """Each ``@st.cache_data`` of ``data.py`` has ``ttl``, ``max_entries=256`` and no spinner."""
    tree = ast.parse(Path(data.__file__).read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert {f.name for f in functions} == {
        "fetch_health",
        "fetch_summary",
        "fetch_timeseries",
        "fetch_spc",
        "fetch_inspections",
        "fetch_devices",
        "fetch_lots",
    }
    for function in functions:
        (decorator,) = function.decorator_list
        assert ast.unparse(decorator.func) == "st.cache_data", function.name
        keywords = {k.arg: ast.unparse(k.value) for k in decorator.keywords}
        assert keywords == {
            "ttl": "CACHE_TTL_SECONDS",
            "max_entries": "CACHE_MAX_ENTRIES",
            "show_spinner": "False",
        }, function.name
    assert data.CACHE_MAX_ENTRIES == 256


def test_full_cache_drops_the_oldest_entry(mock_api) -> None:
    lots = [f"L-{i:03d}" for i in range(data.CACHE_MAX_ENTRIES + 1)]
    for lot in lots:
        data.fetch_summary(Filters(lot_id=lot))
    assert len(mock_api.requests) == 257
    data.fetch_summary(Filters(lot_id=lots[-1]))
    assert len(mock_api.requests) == 257
    data.fetch_summary(Filters(lot_id=lots[0]))
    assert len(mock_api.requests) == 258
    assert mock_api.requests[-1].url.params["lot_id"] == "L-000"


def test_spc_object_types_are_the_graded_groups_of_the_contract() -> None:
    """The members of the API's ``SpcObjectType`` (SPEC-016 section 4.3; ADR-021, decision 3)."""
    graded = GRADE_REQUIRED_OBJECT_TYPES | GRADE_OPTIONAL_OBJECT_TYPES
    assert tuple(t for t in ObjectType if t in graded) == filters.SPC_OBJECT_TYPES
    assert [t.value for t in filters.SPC_OBJECT_TYPES] == [
        "screw",
        "nut",
        "pliers",
        "adjustable_wrench",
        "allen_key",
        "flat_screwdriver",
        "phillips_screwdriver",
    ]


def test_sidebar_type_filter_has_every_type() -> None:
    assert len(filters.TYPE_OPTIONS) == 1 + len(ObjectType)
    assert filters.TYPE_BY_OPTION["chave Phillips"] is ObjectType.PHILLIPS_SCREWDRIVER
