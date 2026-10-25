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

Besides the ``httpx`` timeout of 5 s per operation (connect, write, each read), every batch
request has a total deadline of 15 s and reads at most 512 KiB of response (SPEC-030 section
4.1): the body is streamed, and only read for 2xx, 413 and 422; after each chunk, an elapsed time
above the deadline or a total above the cap closes the response and raises
``PublishTransientError`` with a fixed message, so the loop retries later. The deadline uses
``time.monotonic`` (injectable), never the wall clock. ``check_health`` never reads the body.

SPEC-018: ``send_heartbeat`` posts a ``qc_contracts.HeartbeatCreate`` to
``POST {CLOUD_API_URL}/api/v1/devices/{device_id}/heartbeat`` (``device_id`` given to the
constructor), with the same timeout, deadline and byte cap. 204 is a success; 401/403 raise
``PublishAuthError``; anything else raises ``PublishTransientError`` with the summary above
(``HTTP <status>``, the refusal summary of a 413/422, or the redacted ``httpx`` error), never the
body. The heartbeat carries no image and no personal data (R-02).
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

import httpx
from pydantic import ValidationError

from qc_contracts import (
    DEVICE_ID_PATTERN,
    MAX_BATCH_SIZE,
    BatchCreate,
    BatchResult,
    HeartbeatCreate,
    InspectionCreate,
)
from qc_edge.config import check_cloud_api_url

logger = logging.getLogger("qc_edge")

API_KEY_HEADER = "X-API-Key"
BATCH_PATH = "/api/v1/inspections/batch"
HEALTH_PATH = "/api/v1/health"
HEARTBEAT_PATH = "/api/v1/devices/{device_id}/heartbeat"
DEFAULT_TIMEOUT_S = 5.0
REQUEST_DEADLINE_S = 15.0
MAX_RESPONSE_BYTES = 512 * 1024  # above the 256 KB of input that the API echoes in a 422
DEADLINE_EXCEEDED = "request deadline exceeded"
RESPONSE_TOO_LARGE = "response too large"
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


class HeartbeatPublisher(Protocol):
    """What the heartbeat loop needs (SPEC-018 section 4.4)."""

    def send_heartbeat(self, heartbeat: HeartbeatCreate) -> None: ...


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

    ``deadline_s`` (total time of a request, checked after each chunk of the response body)
    and ``max_response_bytes`` (cap of the body read) come from SPEC-030 section 4.1;
    ``monotonic`` is injectable for the tests. ``device_id`` (``DEVICE_ID_PATTERN``) is the
    device of the heartbeat path (SPEC-018); without it, ``send_heartbeat`` raises
    ``ValueError``.

    Raises:
        ValueError: ``base_url`` is not accepted by ``check_cloud_api_url``, the key is empty or
            not visible ASCII, ``device_id`` is outside ``DEVICE_ID_PATTERN``, or ``timeout_s``,
            ``deadline_s`` or ``max_response_bytes`` is not positive. The messages never contain
            the key.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
        *,
        deadline_s: float = REQUEST_DEADLINE_S,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        monotonic: Callable[[], float] = time.monotonic,
        device_id: str | None = None,
    ) -> None:
        self._base_url = check_cloud_api_url(base_url)
        check_api_key(api_key)
        if device_id is not None and re.fullmatch(DEVICE_ID_PATTERN, device_id) is None:
            raise ValueError("device_id must match DEVICE_ID_PATTERN")
        if not timeout_s > 0:
            raise ValueError("timeout_s must be > 0")
        if not deadline_s > 0:
            raise ValueError("deadline_s must be > 0")
        if not max_response_bytes > 0:
            raise ValueError("max_response_bytes must be > 0")
        self._api_key = api_key
        self._deadline_s = deadline_s
        self._max_response_bytes = max_response_bytes
        self._monotonic = monotonic
        self._device_id = device_id
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
        start = self._monotonic()
        content: bytes | None = None
        try:
            with self._client.stream(
                "POST",
                self._base_url + BATCH_PATH,
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/json", API_KEY_HEADER: self._api_key},
            ) as response:
                status_code = response.status_code
                if status_code in REJECTED_STATUSES or 200 <= status_code < 300:
                    content = self._read_body(response, start)
        except httpx.HTTPError as exc:
            raise PublishTransientError(self._describe(exc)) from None

        # The response is closed here: the body (when needed) was read inside the block.
        if status_code in AUTH_STATUSES:
            raise PublishAuthError(f"HTTP {status_code}")
        if status_code in REJECTED_STATUSES:
            raise PublishRejectedError(refusal_summary(status_code, content or b""))
        if not 200 <= status_code < 300:
            raise PublishTransientError(f"HTTP {status_code}")
        return _parse_results(content or b"", items)

    def _read_body(self, response: httpx.Response, start: float) -> bytes:
        """The body of ``response``, chunk by chunk, within the deadline and the byte cap.

        Raises:
            PublishTransientError: ``request deadline exceeded`` or ``response too large``
                (fixed messages, without URL, key or body); the response is closed first.
            httpx.HTTPError: a network error while reading.
        """
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if self._monotonic() - start > self._deadline_s:
                response.close()
                raise PublishTransientError(DEADLINE_EXCEEDED)
            if total > self._max_response_bytes:
                response.close()
                raise PublishTransientError(RESPONSE_TOO_LARGE)
            chunks.append(chunk)
        return b"".join(chunks)

    def send_heartbeat(self, heartbeat: HeartbeatCreate) -> None:
        """Post ``heartbeat`` for the ``device_id`` of this publisher (SPEC-018 section 4.4).

        The body is read only for 204 and 413/422, within the deadline and the byte cap.

        Raises:
            ValueError: the publisher was built without ``device_id``.
            PublishAuthError: 401 or 403.
            PublishTransientError: network, timeout, deadline, byte cap or any other status.
        """
        if self._device_id is None:
            raise ValueError("device_id is required to send a heartbeat")
        body = heartbeat.model_dump_json()
        url = self._base_url + HEARTBEAT_PATH.format(device_id=self._device_id)
        start = self._monotonic()
        content: bytes | None = None
        try:
            with self._client.stream(
                "POST",
                url,
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/json", API_KEY_HEADER: self._api_key},
            ) as response:
                status_code = response.status_code
                if status_code == 204 or status_code in REJECTED_STATUSES:
                    content = self._read_body(response, start)
        except httpx.HTTPError as exc:
            raise PublishTransientError(self._describe(exc)) from None

        if status_code == 204:
            return
        if status_code in AUTH_STATUSES:
            raise PublishAuthError(f"HTTP {status_code}")
        if status_code in REJECTED_STATUSES:
            raise PublishTransientError(refusal_summary(status_code, content or b""))
        raise PublishTransientError(f"HTTP {status_code}")

    def check_health(self) -> bool:
        """``GET /api/v1/health`` (no key); ``True`` only with 200. The body is never read."""
        try:
            with self._client.stream("GET", self._base_url + HEALTH_PATH) as response:
                return response.status_code == 200
        except httpx.HTTPError as exc:
            logger.info("cloud health check failed: %s", self._describe(exc))
            return False

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
