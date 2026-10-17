"""Cached reads of the API (SPEC-013 section 4.1): one function per endpoint.

Pages read API data **only** through these functions, so every read goes through the 30 s
cache and the dashboard does not repeat the aggregations on every interaction (they compete
with the ingestion for the API pool: SEC-05-01 of SPEC-005, SEC-06-01 of SPEC-006). The
arguments are hashable values only, never the read key. Exceptions are not cached.
"""

from __future__ import annotations

import streamlit as st

from qc_contracts import (
    HealthResponse,
    MetricsSummary,
    ObjectType,
    Source,
    SpcResponse,
    TimeseriesPoint,
)
from qc_dashboard import api
from qc_dashboard.api import Bucket, Filters, InspectionPage, LotPage

CACHE_TTL_SECONDS = 30


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_health() -> HealthResponse:
    return api.get_client().health()


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_summary(filters: Filters) -> MetricsSummary:
    return api.get_client().summary(filters)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_timeseries(filters: Filters, bucket: Bucket) -> list[TimeseriesPoint]:
    return api.get_client().timeseries(filters, bucket)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_spc(
    source: Source,
    object_type: ObjectType | None,
    baseline_lots: int,
    min_lot_size: int,
    max_points: int,
) -> SpcResponse:
    return api.get_client().spc(source, object_type, baseline_lots, min_lot_size, max_points)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_inspections(filters: Filters, limit: int, offset: int) -> InspectionPage:
    return api.get_client().inspections(filters, limit, offset)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_lots(filters: Filters) -> LotPage:
    return api.get_client().lots(filters)
