"""Write routes used by the edge outbox and the simulator (SPEC-004 sections 4.4 and 4.5).

Precedence for well-formed JSON: 413 -> 503 -> 401 -> 422 (contract) -> 403 -> 422 (a value the
database refuses: SQLSTATE classes 22 and 23, SPEC-005 section 4.5). Writes are idempotent by
``inspection_id`` (R-05). No route accepts images or ``multipart/form-data`` (R-02): the bodies
are the JSON contract models only.

``GET /api/v1/inspections`` (SPEC-005) lives here too: same path, read key.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from qc_api.auth import require_device, require_read_key
from qc_api.db import insert_inspections
from qc_api.errors import DETAIL_DEVICE_MISMATCH, DETAIL_VALUE_NOT_STORABLE
from qc_api.filters import InspectionFilters, Pagination
from qc_api.repositories import inspections as repository
from qc_api.routers import API_PREFIX, READ_ERROR_RESPONSES
from qc_contracts import (
    BatchCreate,
    BatchResult,
    InspectionCreate,
    InspectionCreated,
    InspectionRead,
    Page,
)

logger = logging.getLogger("qc_api")

router = APIRouter(prefix=API_PREFIX, tags=["inspections"])

DeviceId = Annotated[str, Depends(require_device)]

_ERROR_RESPONSES: dict[int | str, dict[str, str]] = {
    401: {"description": "Missing or invalid API key"},
    403: {"description": "device_id does not match API key"},
    413: {"description": "Request body too large"},
    422: {"description": "Invalid payload, or a value the database cannot store"},
    503: {"description": "Database unavailable"},
}


def _write(
    request: Request, device_id: str, items: Sequence[InspectionCreate]
) -> list[InspectionCreated]:
    """Check ownership (403) and write everything in one transaction.

    A value the database refuses (``DataError``, SQLSTATE class 22, or ``IntegrityError``, class
    23) becomes 422 ``Value cannot be stored``; the transaction is already rolled back.
    """
    if any(item.device_id != device_id for item in items):
        logger.warning("device_id mismatch for device %s", device_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DETAIL_DEVICE_MISMATCH)
    try:
        return insert_inspections(request.app.state.pool, device_id, items)
    except (psycopg.DataError, psycopg.IntegrityError) as exc:
        # Already rolled back. Log only route, device and SQLSTATE: never values nor the
        # server message, which may echo them ("Failing row contains (...)").
        logger.warning(
            "value cannot be stored: route=%s device_id=%s sqlstate=%s",
            request.url.path,
            device_id,
            exc.sqlstate,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=DETAIL_VALUE_NOT_STORABLE
        ) from None


@router.post(
    "/inspections",
    status_code=status.HTTP_201_CREATED,
    response_model=InspectionCreated,
    responses={200: {"model": InspectionCreated, "description": "Duplicate"}, **_ERROR_RESPONSES},
)
def create_inspection(
    payload: InspectionCreate, request: Request, response: Response, device_id: DeviceId
) -> InspectionCreated:
    """Create one inspection: 201 ``created``, or 200 ``duplicate`` for a known ID."""
    (result,) = _write(request, device_id, [payload])
    if result.status == "duplicate":
        response.status_code = status.HTTP_200_OK
    return result


@router.post("/inspections/batch", response_model=BatchResult, responses=_ERROR_RESPONSES)
def create_inspections_batch(
    payload: BatchCreate, request: Request, device_id: DeviceId
) -> BatchResult:
    """Create 1 to 100 inspections in one transaction; results in the same order."""
    return BatchResult(results=_write(request, device_id, payload.items))


@router.get(
    "/inspections",
    response_model=Page[InspectionRead],
    responses=READ_ERROR_RESPONSES,
    dependencies=[Depends(require_read_key)],
)
def list_inspections(
    request: Request,
    filters: Annotated[InspectionFilters, Depends()],
    page: Annotated[Pagination, Depends()],
) -> Page[InspectionRead]:
    """Filtered inspections, ``inspected_at desc, inspection_id asc`` (SPEC-005 section 4.3)."""
    return repository.list_inspections(
        request.app.state.pool, filters, limit=page.limit, offset=page.offset
    )
