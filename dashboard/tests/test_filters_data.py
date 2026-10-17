"""Pure parts of ``qc_dashboard.filters`` and the cache of ``qc_dashboard.data`` (SPEC-013)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest
import streamlit as st

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
