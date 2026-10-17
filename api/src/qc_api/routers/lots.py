"""``GET /api/v1/lots`` (SPEC-005 section 4.3): one summary per lot, paginated. Read key only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from qc_api.auth import require_read_key
from qc_api.filters import InspectionFilters, Pagination
from qc_api.repositories import inspections as repository
from qc_api.routers import API_PREFIX, READ_ERROR_RESPONSES
from qc_contracts import LotSummary, Page

router = APIRouter(
    prefix=API_PREFIX,
    tags=["lots"],
    dependencies=[Depends(require_read_key)],
    responses=READ_ERROR_RESPONSES,
)


@router.get("/lots", response_model=Page[LotSummary])
def list_lots(
    request: Request,
    filters: Annotated[InspectionFilters, Depends()],
    page: Annotated[Pagination, Depends()],
) -> Page[LotSummary]:
    """Lots among the matching rows, ``started_at desc, lot_id asc``."""
    return repository.list_lots(
        request.app.state.pool, filters, limit=page.limit, offset=page.offset
    )
