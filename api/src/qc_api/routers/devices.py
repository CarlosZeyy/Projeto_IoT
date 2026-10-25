"""Device heartbeat and device status routes (SPEC-018 section 4.3, docs/architecture.md §4).

* ``POST /api/v1/devices/{device_id}/heartbeat``: device key; 204 without body. Precedence for
  well-formed JSON, as in SPEC-004: 413 -> 503 -> 401 -> 422 (path ``device_id`` outside
  ``DEVICE_ID_PATTERN`` or a body outside ``HeartbeatCreate``) -> 403 (the key belongs to
  another device) -> 422 (a value the database refuses). The body is never logged, and no route
  accepts images or ``multipart/form-data`` (R-02).
* ``GET /api/v1/devices``: read key; at most 500 ``DeviceStatus`` in ``device_id`` order, with
  ``online`` computed by the server.

No rate limit of its own: each heartbeat is authenticated and costs one ``UPDATE``, like an
inspection (accepted risk of SPEC-004).
"""

from __future__ import annotations

import logging
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status

from qc_api.auth import require_device, require_read_key
from qc_api.errors import DETAIL_DEVICE_MISMATCH, DETAIL_VALUE_NOT_STORABLE
from qc_api.middleware import sqlstate_label
from qc_api.repositories import devices as repository
from qc_api.routers import API_PREFIX, READ_ERROR_RESPONSES
from qc_contracts import DEVICE_ID_PATTERN, DeviceStatus, HeartbeatCreate

logger = logging.getLogger("qc_api")

router = APIRouter(prefix=API_PREFIX, tags=["devices"])

KeyOwner = Annotated[str, Depends(require_device)]
PathDeviceId = Annotated[str, Path(pattern=DEVICE_ID_PATTERN)]

_HEARTBEAT_RESPONSES: dict[int | str, dict[str, str]] = {
    401: {"description": "Missing or invalid API key"},
    403: {"description": "device_id does not match API key"},
    413: {"description": "Request body too large"},
    422: {"description": "Invalid device_id or payload, or a value the database cannot store"},
    503: {"description": "Database unavailable"},
}


@router.post(
    "/devices/{device_id}/heartbeat",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_HEARTBEAT_RESPONSES,
)
def post_heartbeat(
    device_id: PathDeviceId, payload: HeartbeatCreate, request: Request, owner: KeyOwner
) -> Response:
    """Store the heartbeat of ``device_id`` (only its own key may send it)."""
    if device_id != owner:
        logger.warning("device_id mismatch for device %s", owner)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DETAIL_DEVICE_MISMATCH)
    try:
        repository.record_heartbeat(request.app.state.pool, owner, payload)
    except (psycopg.DataError, psycopg.IntegrityError) as exc:
        # Already rolled back. Only route, device and SQLSTATE: never the values nor the server
        # message (docs/architecture.md section 4, "Erros de banco no log").
        logger.warning(
            "value cannot be stored: route=%s device_id=%s sqlstate=%s",
            request.url.path,
            owner,
            sqlstate_label(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=DETAIL_VALUE_NOT_STORABLE
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/devices",
    response_model=list[DeviceStatus],
    responses=READ_ERROR_RESPONSES,
    dependencies=[Depends(require_read_key)],
)
def list_devices(request: Request) -> list[DeviceStatus]:
    """Every registered device (at most 500), ``online`` by the server clock."""
    return repository.list_devices(request.app.state.pool)
