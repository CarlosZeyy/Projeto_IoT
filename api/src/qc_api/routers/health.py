"""``GET /api/v1/health`` (SPEC-004 section 4.4).

Runs ``SELECT 1`` (which also keeps the Supabase project awake, SPEC-015). 200 when the
database answers, 503 otherwise. The database error message is never returned nor logged.
"""

from __future__ import annotations

import logging

import psycopg
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

import qc_api
import qc_contracts
from qc_api.db import ping
from qc_api.errors import DatabaseUnavailableError
from qc_api.routers import API_PREFIX
from qc_contracts import HealthResponse

logger = logging.getLogger("qc_api")

router = APIRouter(prefix=API_PREFIX, tags=["health"])


def _health(ok: bool) -> HealthResponse:
    return HealthResponse(
        status="ok" if ok else "degraded",
        db="ok" if ok else "error",
        api_version=qc_api.__version__,
        contract_version=qc_contracts.__version__,
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Database unavailable"}},
)
def health(request: Request) -> HealthResponse | JSONResponse:
    try:
        ping(request.app.state.pool)
    except (DatabaseUnavailableError, psycopg.Error) as exc:
        logger.warning("health check: database error (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_health(ok=False).model_dump(mode="json"),
        )
    return _health(ok=True)
