"""HTTP client of the read routes of ``qc-api`` (SPEC-013 section 4.1, ADR-007).

Every call sends the read key in the ``X-API-Key`` header and returns the ``qc_contracts``
models. Errors are mapped to three exceptions:

* timeout, connection error and HTTP 502/503/504 -> ``ApiUnavailable`` (the free tier cold
  start, SPEC-013 section 7);
* HTTP 401/403 -> ``ApiAuthError``;
* any other status >= 400, or a body that is not the expected model -> ``ApiError(status)``.

The key is never logged nor included in an exception message (R-03). ``get_client()`` is the
only place that builds the client; callers use it as ``api.get_client()`` (module attribute) so
tests can replace it with a client on ``httpx.MockTransport``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
import streamlit as st
from pydantic import TypeAdapter, ValidationError

from qc_contracts import (
    DeviceStatus,
    Grade,
    HealthResponse,
    InspectionRead,
    LotSummary,
    MetricsSummary,
    ObjectType,
    Page,
    Source,
    SpcResponse,
    TimeseriesPoint,
)
from qc_dashboard import config

logger = logging.getLogger("qc_dashboard")

API_PREFIX = "/api/v1"
DEFAULT_TIMEOUT = 10.0
API_KEY_HEADER = "X-API-Key"
UNAVAILABLE_STATUSES = frozenset({502, 503, 504})
AUTH_STATUSES = frozenset({401, 403})

Bucket = Literal["minute", "hour", "day"]


class ApiClientError(Exception):
    """Base of the client errors. ``status`` is the HTTP status, or ``None`` without response."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ApiUnavailable(ApiClientError):
    """Timeout, connection error or HTTP 502/503/504."""


class ApiAuthError(ApiClientError):
    """HTTP 401/403: missing or invalid read key."""


class ApiError(ApiClientError):
    """Any other HTTP status >= 400, or an invalid response body."""

    def __init__(self, status: int | None, message: str | None = None) -> None:
        super().__init__(message or f"API error (HTTP {status})", status)


# Subclasses of the generic pages: a parametrized ``Page[T]`` cannot be pickled, and
# ``st.cache_data`` pickles what it stores. Instances are still ``Page[T]`` instances.
class InspectionPage(Page[InspectionRead]):
    """``Page[InspectionRead]``."""


class LotPage(Page[LotSummary]):
    """``Page[LotSummary]``."""


@dataclass(frozen=True)
class Filters:
    """Filters of the read routes (``docs/architecture.md`` section 4). ``None`` = not filtered.

    ``from_`` is inclusive and ``to`` exclusive, both timezone-aware (normalized to UTC). Enum
    fields accept their string values. Hashable: the cached functions of ``data`` take it.
    """

    source: Source | None = None
    from_: datetime | None = None
    to: datetime | None = None
    object_type: ObjectType | None = None
    lot_id: str | None = None
    device_id: str | None = None
    grade: Grade | None = None
    defective: bool | None = None

    def __post_init__(self) -> None:
        for name, enum in (("source", Source), ("object_type", ObjectType), ("grade", Grade)):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, enum(value))
        for name in ("from_", "to"):
            value = getattr(self, name)
            if value is not None:
                if value.tzinfo is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))

    def to_query(self) -> dict[str, str]:
        """Query string parameters, only for the fields that are set."""
        query: dict[str, str] = {}
        if self.source is not None:
            query["source"] = self.source.value
        if self.from_ is not None:
            query["from"] = self.from_.isoformat()
        if self.to is not None:
            query["to"] = self.to.isoformat()
        if self.object_type is not None:
            query["object_type"] = self.object_type.value
        if self.lot_id is not None:
            query["lot_id"] = self.lot_id
        if self.device_id is not None:
            query["device_id"] = self.device_id
        if self.grade is not None:
            query["grade"] = self.grade.value
        if self.defective is not None:
            query["defective"] = "true" if self.defective else "false"
        return query


class ApiClient:
    """Synchronous client of the read routes. ``transport`` is for tests (``MockTransport``)."""

    def __init__(
        self,
        base_url: str,
        read_api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={API_KEY_HEADER: read_api_key},
            timeout=timeout,
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"ApiClient(base_url={self.base_url!r}, timeout={self.timeout})"

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str, params: dict[str, str] | None = None) -> tuple[int, Any]:
        """``(status, decoded JSON)`` of ``GET /api/v1<path>``; raises the mapped errors."""
        try:
            response = self._http.get(API_PREFIX + path, params=params)
        except httpx.TimeoutException:
            logger.warning("API timeout: GET %s", path)
            raise ApiUnavailable("API timeout") from None
        except httpx.TransportError as exc:
            logger.warning("API connection error: GET %s (%s)", path, type(exc).__name__)
            raise ApiUnavailable("API connection error") from None
        status = response.status_code
        logger.debug("GET %s -> HTTP %s", path, status)
        if status in UNAVAILABLE_STATUSES:
            raise ApiUnavailable(f"API unavailable (HTTP {status})", status)
        if status in AUTH_STATUSES:
            raise ApiAuthError(f"API refused the read key (HTTP {status})", status)
        if status >= 400:
            raise ApiError(status)
        try:
            return status, response.json()
        except ValueError:
            raise self._invalid_body(status, path) from None

    @staticmethod
    def _invalid_body(status: int, path: str) -> ApiError:
        logger.warning("API response does not match the contract: GET %s", path)
        return ApiError(status, f"invalid API response body (HTTP {status})")

    def _get_model[M](self, path: str, adapter: TypeAdapter[M], params: dict[str, str]) -> M:
        status, body = self._get(path, params)
        try:
            return adapter.validate_python(body)
        except ValidationError:
            raise self._invalid_body(status, path) from None

    def health(self) -> HealthResponse:
        return self._get_model("/health", _HEALTH, {})

    def summary(self, params: Filters) -> MetricsSummary:
        return self._get_model("/metrics/summary", _SUMMARY, params.to_query())

    def timeseries(self, params: Filters, bucket: Bucket) -> list[TimeseriesPoint]:
        query = {**params.to_query(), "bucket": bucket}
        return self._get_model("/metrics/timeseries", _TIMESERIES, query)

    def spc(
        self,
        source: Source | str,
        object_type: ObjectType | str | None,
        baseline_lots: int,
        min_lot_size: int,
        max_points: int,
    ) -> SpcResponse:
        query = {"source": Source(source).value}
        if object_type is not None:
            query["object_type"] = ObjectType(object_type).value
        query["baseline_lots"] = str(baseline_lots)
        query["min_lot_size"] = str(min_lot_size)
        query["max_points"] = str(max_points)
        return self._get_model("/metrics/spc", _SPC, query)

    def inspections(self, params: Filters, limit: int, offset: int) -> InspectionPage:
        query = {**params.to_query(), "limit": str(limit), "offset": str(offset)}
        return self._get_model("/inspections", _INSPECTION_PAGE, query)

    def lots(self, params: Filters) -> LotPage:
        return self._get_model("/lots", _LOT_PAGE, params.to_query())

    def devices(self) -> list[DeviceStatus]:
        """``GET /api/v1/devices`` (SPEC-018): every device, ``online`` computed by the API."""
        return self._get_model("/devices", _DEVICES, {})


_HEALTH = TypeAdapter(HealthResponse)
_TIMESERIES = TypeAdapter(list[TimeseriesPoint])
_SUMMARY = TypeAdapter(MetricsSummary)
_SPC = TypeAdapter(SpcResponse)
_INSPECTION_PAGE = TypeAdapter(InspectionPage)
_LOT_PAGE = TypeAdapter(LotPage)
_DEVICES = TypeAdapter(list[DeviceStatus])


@st.cache_resource(show_spinner=False)
def get_client() -> ApiClient:
    """The single ``ApiClient`` of the process, built from ``config.get_settings()``.

    Raises ``config.ConfigError`` when ``API_BASE_URL`` or ``READ_API_KEY`` is missing (the
    exception is not cached, so the next call reads the settings again).
    """
    settings = config.get_settings()
    return ApiClient(settings.api_base_url, settings.read_api_key)
