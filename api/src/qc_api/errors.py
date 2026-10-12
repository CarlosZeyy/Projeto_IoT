"""Error bodies and exception handlers (SPEC-004 sections 4.3 to 4.5).

Every error body is ``{"detail": ...}`` without stack traces (docs/architecture.md section 3.3).
Validation errors keep FastAPI's default 422 (``{"detail": [...]}``).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger("qc_api")

DETAIL_INVALID_KEY = "Missing or invalid API key"
DETAIL_DEVICE_MISMATCH = "device_id does not match API key"
DETAIL_BODY_TOO_LARGE = "Request body too large"
DETAIL_DB_UNAVAILABLE = "Database unavailable"
DETAIL_VALUE_NOT_STORABLE = "Value cannot be stored"
DETAIL_INTERNAL = "Internal server error"


class DatabaseUnavailableError(Exception):
    """The database could not be reached (``OperationalError`` or ``PoolTimeout``).

    Carries no message: the original error may describe the connection and is never exposed.
    """


class BodyTooLargeError(HTTPException):
    """Raised while reading a request body that exceeds ``MAX_BODY_BYTES``.

    An ``HTTPException`` so FastAPI re-raises it from body parsing (instead of turning it into
    a 400) and the exception middleware renders it as 413.
    """

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=DETAIL_BODY_TOO_LARGE
        )


def unauthorized() -> HTTPException:
    """The single 401 of the API: same body whatever the reason (section 4.3)."""
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=DETAIL_INVALID_KEY)


def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": DETAIL_DB_UNAVAILABLE},
    )


def install_exception_handlers(app: FastAPI) -> None:
    """Register the handlers of the API's own exceptions."""
    app.add_exception_handler(DatabaseUnavailableError, _database_unavailable)
