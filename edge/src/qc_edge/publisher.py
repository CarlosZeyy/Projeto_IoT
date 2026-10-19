"""Publication of inspections to the cloud (SPEC-009 section 4.2, ADR-009).

``HttpPublisher`` posts batches to ``POST {CLOUD_API_URL}/api/v1/inspections/batch`` (SPEC-004)
with the device key in ``X-API-Key`` and checks ``GET /api/v1/health``. The body is always the
JSON of ``qc_contracts.BatchCreate``: never an image, never multipart (R-02). This is the only
``qc_edge`` module that imports ``httpx`` (SPEC-007, CA-17); the outbox and the publish loop only
know the ``Publisher`` protocol.

Errors map to three exceptions:

* ``PublishTransientError``: network, timeout, 5xx, 429, any other unexpected status, or a
  malformed response; the loop retries later.
* ``PublishAuthError``: 401 or 403; the loop pauses until ``qc-edge`` restarts.
* ``PublishRejectedError``: 413 or 422; ``.detail`` is a summary of the refusal (status plus the
  ``detail`` text or the number of validation errors), never the body. FastAPI's default 422
  echoes the ``input`` that was sent (SEC-04-04 of ``reviews/SPEC-004/r2-security-report.md``),
  so the body never reaches a log, ``last_error`` or an exception message.

The device key never appears in a message built here: it is replaced by ``***`` in any text that
comes from ``httpx`` (R-03).
"""

from __future__ import annotations

import json
import logging
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

import httpx
from pydantic import ValidationError

from qc_contracts import MAX_BATCH_SIZE, BatchCreate, BatchResult, InspectionCreate
from qc_edge.config import check_cloud_api_url

logger = logging.getLogger("qc_edge")

API_KEY_HEADER = "X-API-Key"
BATCH_PATH = "/api/v1/inspections/batch"
HEALTH_PATH = "/api/v1/health"
DEFAULT_TIMEOUT_S = 5.0
MAX_DETAIL_CHARS = 200
REDACTED = "***"

AUTH_STATUSES = frozenset({401, 403})
REJECTED_STATUSES = frozenset({413, 422})


@dataclass(frozen=True)
class PublishResult:
    inspection_id: UUID
    status: Literal["created", "duplicate"]


class PublishTransientError(Exception):
    """Network, timeout, 5xx, 429, other unexpected 4xx or a malformed response."""


class PublishAuthError(Exception):
    """The cloud refused the device key (401 or 403)."""


class PublishRejectedError(Exception):
    """The cloud refused the batch (422 or 413). ``detail`` is the refusal summary."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class Publisher(Protocol):
    def publish_batch(self, items: Sequence[InspectionCreate]) -> list[PublishResult]: ...

    def check_health(self) -> bool: ...


def refusal_summary(status_code: int, body: bytes) -> str:
    """Summary of a 413/422 body (SPEC-009 section 4.2); the body itself is never returned.

    * JSON with a string ``detail``: ``HTTP <status>: <detail>``, the detail cut to 200
      characters and every control character replaced by ``?``;
    * JSON with a list ``detail``: ``HTTP <status>: <n> validation errors``;
    * anything else: ``HTTP <status>``.
    """
    prefix = f"HTTP {status_code}"
    try:
        document = json.loads(body)
    except (ValueError, RecursionError):
        return prefix
    if not isinstance(document, dict):
        return prefix
    detail = document.get("detail")
    if isinstance(detail, str):
        cut = detail[:MAX_DETAIL_CHARS]
        clean = "".join("?" if unicodedata.category(char) == "Cc" else char for char in cut)
        return f"{prefix}: {clean}"
    if isinstance(detail, list):
        return f"{prefix}: {len(detail)} validation errors"
    return prefix


def check_api_key(api_key: str) -> None:
    """Raises ``ValueError`` (without the value) unless the key is non-empty visible ASCII."""
    # A header value outside visible ASCII can never authenticate, and the error httpx would
    # raise while encoding it could quote the key.
    if not api_key or any(not 0x21 <= ord(char) <= 0x7E for char in api_key):
        raise ValueError("the device API key must be non-empty visible ASCII")


class HttpPublisher:
    """``Publisher`` over HTTPS (``http://`` only for ``localhost`` and ``127.0.0.1``).

    Raises:
        ValueError: ``base_url`` is not accepted by ``check_cloud_api_url``, the key is empty or
            not visible ASCII, or ``timeout_s`` is not positive. The messages never contain the
            key.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = check_cloud_api_url(base_url)
        check_api_key(api_key)
        if not timeout_s > 0:
            raise ValueError("timeout_s must be > 0")
        self._api_key = api_key
        self._client = httpx.Client(timeout=timeout_s, transport=transport, follow_redirects=False)

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, REDACTED)

    def publish_batch(self, items: Sequence[InspectionCreate]) -> list[PublishResult]:
        """Post ``items`` (1 to 100) as one ``BatchCreate``; one result per item, same order.

        Raises:
            ValueError: no items or more than 100.
            PublishTransientError, PublishAuthError, PublishRejectedError: see the module.
        """
        if not 1 <= len(items) <= MAX_BATCH_SIZE:
            raise ValueError(f"a batch has 1 to {MAX_BATCH_SIZE} items, got {len(items)}")
        body = BatchCreate(items=list(items)).model_dump_json()
        try:
            response = self._client.post(
                self._base_url + BATCH_PATH,
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/json", API_KEY_HEADER: self._api_key},
            )
        except httpx.HTTPError as exc:
            raise PublishTransientError(self._describe(exc)) from None

        status_code = response.status_code
        if status_code in AUTH_STATUSES:
            raise PublishAuthError(f"HTTP {status_code}")
        if status_code in REJECTED_STATUSES:
            raise PublishRejectedError(refusal_summary(status_code, response.content))
        if not 200 <= status_code < 300:
            raise PublishTransientError(f"HTTP {status_code}")
        return _parse_results(response.content, items)

    def check_health(self) -> bool:
        """``GET /api/v1/health`` (no key); ``True`` only with 200."""
        try:
            response = self._client.get(self._base_url + HEALTH_PATH)
        except httpx.HTTPError as exc:
            logger.info("cloud health check failed: %s", self._describe(exc))
            return False
        return response.status_code == 200

    def close(self) -> None:
        self._client.close()

    def _describe(self, exc: httpx.HTTPError) -> str:
        message = str(exc).strip()
        name = type(exc).__name__
        return self._redact(f"{name}: {message}" if message else name)


def _parse_results(content: bytes, items: Sequence[InspectionCreate]) -> list[PublishResult]:
    """``BatchResult`` with the ids of ``items`` in the same order; else transient."""
    try:
        result = BatchResult.model_validate_json(content)
    except ValidationError:
        raise PublishTransientError("malformed batch response") from None
    expected = [item.inspection_id for item in items]
    received = [entry.inspection_id for entry in result.results]
    if received != expected:
        raise PublishTransientError("batch response does not match the items sent")
    return [
        PublishResult(inspection_id=entry.inspection_id, status=entry.status)
        for entry in result.results
    ]
