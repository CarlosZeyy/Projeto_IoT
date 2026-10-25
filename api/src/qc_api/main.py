"""FastAPI application of the cloud API (SPEC-004 §4.2, SPEC-005, SPEC-018, architecture §4).

``uvicorn qc_api.main:app`` serves the module-level ``app``; its settings are read from the
environment when the server starts (``lifespan``), not at import time. The connection pool is
opened without waiting, so the API starts even with the database down (``/health`` then answers
503). There is no CORS middleware on purpose: the dashboard calls the API from its server.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import qc_api
from qc_api.config import Settings
from qc_api.db import create_pool
from qc_api.errors import install_exception_handlers
from qc_api.middleware import (
    BodySizeLimitMiddleware,
    RequestLogMiddleware,
    UnhandledErrorMiddleware,
)
from qc_api.routers import devices, health, inspections, lots, metrics

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

logger = logging.getLogger("qc_api")


def configure_logging(level: str) -> None:
    """Set the ``qc_api`` logger level; add a stderr handler only if nothing would print it."""
    logger.setLevel(level)
    if not logger.handlers and not logging.getLogger().handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API. With ``settings=None``, ``Settings()`` is loaded at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        current = settings if settings is not None else Settings()
        app.state.settings = current
        configure_logging(current.LOG_LEVEL)
        pool = create_pool(current.DATABASE_URL.get_secret_value())
        pool.open(wait=False)
        app.state.pool = pool
        logger.info("qc-api %s started", qc_api.__version__)
        try:
            yield
        finally:
            pool.close()
            logger.info("qc-api stopped")

    app = FastAPI(
        title="PartQC API",
        version=qc_api.__version__,
        docs_url="/docs",
        lifespan=lifespan,
    )
    if settings is not None:
        app.state.settings = settings

    install_exception_handlers(app)
    # Added last = outermost: the log sees every status, including 413 and 500.
    app.add_middleware(BodySizeLimitMiddleware, get_limit=lambda: app.state.settings.MAX_BODY_BYTES)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestLogMiddleware)

    app.include_router(health.router)
    app.include_router(inspections.router)
    app.include_router(metrics.router)
    app.include_router(lots.router)
    app.include_router(devices.router)
    return app


app = create_app()
