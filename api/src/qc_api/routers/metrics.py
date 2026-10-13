"""Aggregates for the dashboard (SPEC-005 section 4.3): ``/metrics/summary`` and
``/metrics/timeseries``. Read key only. The SPC route (``/metrics/spc``) belongs to SPEC-006.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from qc_api.auth import require_read_key
from qc_api.errors import DETAIL_TOO_MANY_BUCKETS
from qc_api.filters import InspectionFilters
from qc_api.repositories import inspections as repository
from qc_api.routers import API_PREFIX, READ_ERROR_RESPONSES
from qc_contracts import MetricsSummary, TimeseriesPoint

router = APIRouter(
    prefix=API_PREFIX,
    tags=["metrics"],
    dependencies=[Depends(require_read_key)],
    responses=READ_ERROR_RESPONSES,
)

Filters = Annotated[InspectionFilters, Depends()]


@router.get("/metrics/summary", response_model=MetricsSummary)
def metrics_summary(request: Request, filters: Filters) -> MetricsSummary:
    """Totals, defect rate, breakdowns by grade and type, and means of the matching rows."""
    return repository.summarize(request.app.state.pool, filters)


@router.get("/metrics/timeseries", response_model=list[TimeseriesPoint])
def metrics_timeseries(
    request: Request,
    filters: Filters,
    bucket: Annotated[repository.Bucket, Query()] = "hour",
) -> list[TimeseriesPoint]:
    """Points per UTC ``bucket`` with data, ascending; more than 5 000 buckets is a 422."""
    try:
        return repository.timeseries(request.app.state.pool, filters, bucket)
    except repository.TooManyBucketsError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=DETAIL_TOO_MANY_BUCKETS
        ) from None
