"""Aggregates for the dashboard. Read key only.

* ``/metrics/summary`` and ``/metrics/timeseries`` (SPEC-005 section 4.3).
* ``/metrics/spc`` (SPEC-006 section 4.2, SPEC-026 section 4.4): the p chart by lot of a single
  ``source`` (``live`` by default, R-06), cut to the last ``max_points`` valid lots and the last
  ``MAX_EXCLUDED_LOTS`` excluded lots (ADR-017). The route only queries the selection, cut in
  SQL (``lot_selection``); the chart itself is the pure ``qc_api.services.spc.build_p_chart``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from qc_api.auth import require_read_key
from qc_api.errors import DETAIL_TOO_MANY_BUCKETS
from qc_api.filters import InspectionFilters
from qc_api.repositories import inspections as repository
from qc_api.routers import API_PREFIX, READ_ERROR_RESPONSES
from qc_api.services.spc import MAX_EXCLUDED_LOTS, build_p_chart
from qc_contracts import MetricsSummary, ObjectType, Source, SpcResponse, TimeseriesPoint

router = APIRouter(
    prefix=API_PREFIX,
    tags=["metrics"],
    dependencies=[Depends(require_read_key)],
    responses=READ_ERROR_RESPONSES,
)

Filters = Annotated[InspectionFilters, Depends()]

SPC_DEFAULT_BASELINE_LOTS = 20
SPC_MIN_BASELINE_LOTS = 2
SPC_MAX_BASELINE_LOTS = 100
SPC_DEFAULT_MIN_LOT_SIZE = 5
SPC_MAX_MIN_LOT_SIZE = 500
SPC_DEFAULT_MAX_POINTS = 100
SPC_MIN_MAX_POINTS = 2
SPC_MAX_MAX_POINTS = 500

# The object types the SPC accepts: every contract type except ``unknown``, which has no grade
# and never enters the chart (ADR-013). ``unknown`` is then a 422 like any other invalid value,
# and the OpenAPI schema lists only the accepted values.
SpcObjectType = StrEnum(
    "SpcObjectType",
    {member.name: member.value for member in ObjectType if member is not ObjectType.UNKNOWN},
)


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


@router.get("/metrics/spc", response_model=SpcResponse)
def metrics_spc(
    request: Request,
    source: Annotated[Source, Query()] = Source.LIVE,
    object_type: Annotated[SpcObjectType | None, Query()] = None,
    baseline_lots: Annotated[
        int, Query(ge=SPC_MIN_BASELINE_LOTS, le=SPC_MAX_BASELINE_LOTS)
    ] = SPC_DEFAULT_BASELINE_LOTS,
    min_lot_size: Annotated[int, Query(ge=1, le=SPC_MAX_MIN_LOT_SIZE)] = SPC_DEFAULT_MIN_LOT_SIZE,
    max_points: Annotated[
        int, Query(ge=SPC_MIN_MAX_POINTS, le=SPC_MAX_MAX_POINTS)
    ] = SPC_DEFAULT_MAX_POINTS,
) -> SpcResponse:
    """p chart by lot of one ``source``; ``unknown`` objects never count.

    Only the last ``max_points`` valid lots and the last ``MAX_EXCLUDED_LOTS`` excluded lots are
    returned, with the totals before the cut; ``p_bar`` still comes from the first
    ``baseline_lots`` valid lots of the whole history (ADR-017). More lots than the cap is not
    an error.
    """
    selection = repository.lot_selection(
        request.app.state.pool,
        source,
        ObjectType(object_type.value) if object_type is not None else None,
        baseline_lots=baseline_lots,
        min_lot_size=min_lot_size,
        max_points=max_points,
        max_excluded=MAX_EXCLUDED_LOTS,
    )
    return build_p_chart(
        selection, baseline_lots, min_lot_size, source=source, max_points=max_points
    )
