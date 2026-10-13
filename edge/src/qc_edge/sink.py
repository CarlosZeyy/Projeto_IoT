"""Where accepted inspections go before the response (SPEC-007 section 4.2).

``SqliteOutbox`` (the durable sink) and its publisher come with SPEC-009. Here there is only the
``InspectionSink`` protocol, the ``InMemorySink`` used by this SPEC and the ``BackgroundService``
protocol that the app starts and stops with its lifespan.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from qc_contracts import InspectionCreate

Connectivity = Literal["online", "offline", "auth_error", "disabled"]


@dataclass(frozen=True)
class SinkStats:
    pending: int
    dead: int
    last_success_at: datetime | None
    connectivity: Connectivity


class SinkError(Exception):
    """The inspection could not be stored; the capture is answered with 503."""


class InspectionSink(Protocol):
    def put(self, inspection: InspectionCreate) -> None:
        """Store ``inspection``; idempotent by ``inspection_id``; durable when it returns."""
        ...

    def stats(self) -> SinkStats: ...


class BackgroundService(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


class InMemorySink:
    """Keeps inspections in a list, in arrival order; nothing is ever sent anywhere.

    Not durable: everything is lost when the process stops. A second ``put`` with an
    ``inspection_id`` already stored is ignored.
    """

    def __init__(self) -> None:
        self._items: list[InspectionCreate] = []
        self._ids: set[UUID] = set()
        self._lock = threading.Lock()

    @property
    def items(self) -> list[InspectionCreate]:
        """Copy of the stored inspections, oldest first."""
        with self._lock:
            return list(self._items)

    def put(self, inspection: InspectionCreate) -> None:
        with self._lock:
            if inspection.inspection_id in self._ids:
                return
            self._ids.add(inspection.inspection_id)
            self._items.append(inspection)

    def stats(self) -> SinkStats:
        with self._lock:
            pending = len(self._items)
        return SinkStats(pending=pending, dead=0, last_success_at=None, connectivity="disabled")
