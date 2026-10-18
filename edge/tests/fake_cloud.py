"""Fake cloud of the SPEC-009 unit tests: ``httpx.MockTransport`` with the SPEC-004 idempotency.

``FakeCloud`` keeps one record per ``inspection_id`` (``created`` the first time, ``duplicate``
after) and answers ``POST /api/v1/inspections/batch`` with a ``BatchResult``, all or nothing,
like the API (docs/architecture.md section 3.3). Failures are injected per request through
``fail``: a callable that receives the request and the parsed items and returns ``None`` (normal
handling), an ``httpx.Response`` or an exception to raise. ``store_then_raise`` stores the batch
and then raises (a "lost response").
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx

from qc_contracts import BatchCreate, Grade, InspectionCreate, ObjectType, Source

BATCH_PATH = "/api/v1/inspections/batch"
HEALTH_PATH = "/api/v1/health"
BASE_URL = "https://cloud.test"

Failure = Callable[[httpx.Request, list[dict[str, Any]]], httpx.Response | Exception | None]


def make_inspection(**overrides: Any) -> InspectionCreate:
    """A valid ``InspectionCreate`` (``inspected_at`` = real now, never in the future)."""
    fields: dict[str, Any] = {
        "inspection_id": uuid4(),
        "device_id": "edge-01",
        "lot_id": "L-001",
        "inspected_at": datetime.now(UTC),
        "object_type": ObjectType.SCREW,
        "grade": Grade.GOOD,
        "grade_score": 1.0,
        "type_confidence": 0.9,
        "grade_confidence": 0.8,
        "needs_review": False,
        "model_version": "partqc-test-v1",
        "model_sha256": "a" * 64,
        "latency_ms": 12,
        "source": Source.LIVE,
    }
    fields.update(overrides)
    return InspectionCreate(**fields)


@dataclass
class FakeCloud:
    fail: Failure | None = None
    health_status: int = 200
    health_error: Exception | None = None
    store_then_raise: Exception | None = None
    stored: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    writes: list[UUID] = field(default_factory=list)  # every first insert (duplicates excluded)
    requests: list[httpx.Request] = field(default_factory=list)
    batches: list[list[dict[str, Any]]] = field(default_factory=list)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @property
    def batch_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == BATCH_PATH]

    @property
    def health_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == HEALTH_PATH]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == HEALTH_PATH:
            if self.health_error is not None:
                raise self.health_error
            return httpx.Response(self.health_status, json={"status": "ok"})
        if request.url.path != BATCH_PATH or request.method != "POST":
            return httpx.Response(404, json={"detail": "Not Found"})
        items = json.loads(request.content)["items"]
        self.batches.append(items)
        if self.fail is not None:
            outcome = self.fail(request, items)
            if isinstance(outcome, Exception):
                raise outcome
            if outcome is not None:
                return outcome
        BatchCreate.model_validate({"items": items})  # what the API would accept
        results = []
        for item in items:
            inspection_id = UUID(item["inspection_id"])
            if inspection_id in self.stored:
                results.append({"inspection_id": str(inspection_id), "status": "duplicate"})
            else:
                self.stored[inspection_id] = item
                self.writes.append(inspection_id)
                results.append({"inspection_id": str(inspection_id), "status": "created"})
        if self.store_then_raise is not None:
            error, self.store_then_raise = self.store_then_raise, None
            raise error
        return httpx.Response(200, json={"results": results})


class FakeClock:
    """Manual UTC clock."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start if start is not None else datetime(2026, 11, 30, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self.now = self.now + timedelta(seconds=seconds)
