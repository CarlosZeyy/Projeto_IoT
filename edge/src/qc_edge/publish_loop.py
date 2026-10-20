"""Background publication of the outbox (SPEC-009 section 4.3, docs/architecture.md section 6.2,
step 8, and section 8, "cloud down").

``PublishLoop`` implements the ``BackgroundService`` of SPEC-007: a daemon thread calls
``run_once`` every ``interval_s`` seconds. One cycle:

1. ``auth_error`` -> no request at all, until ``qc-edge`` restarts.
2. ``fetch_due(100, max_delay_s=60)``; nothing due -> a health check when ``health_every_s``
   passed since the last contact with the cloud, or when the wall clock is now before that
   contact (a jump back, SPEC-030 section 4.2) (``online``/``offline``); done.
3. ``publish_batch``:
   * success (``created`` or ``duplicate``) -> ``sent``, ``last_success_at = now``, ``online``;
   * transient error -> retry in ``min(60, 2**n * U(0.8, 1.2))`` s (``n`` = attempts before the
     increment), ``offline``;
   * rejected (422/413) -> bisection; a single rejected item becomes ``dead`` with the refusal
     summary, the others follow the rules above;
   * 401/403 -> ``auth_error``, attempts unchanged, one error log.
4. Unexpected exception -> logged with its traceback, the items not resolved yet get a retry, and
   the thread keeps running.

The loop depends only on the ``Publisher`` protocol (ADR-009), never on ``httpx``. The device key
is never logged: the messages come from the publisher, which removes it, and an unexpected
exception is stored in ``last_error`` only by its class name.
"""

from __future__ import annotations

import logging
import random
import threading
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from qc_contracts import InspectionCreate
from qc_edge.outbox import DEFAULT_FETCH_LIMIT, Clock, OutboxItem, SqliteOutbox, utc_now
from qc_edge.publisher import (
    PublishAuthError,
    Publisher,
    PublishRejectedError,
    PublishTransientError,
)
from qc_edge.sink import Connectivity

logger = logging.getLogger("qc_edge")

MAX_DELAY_S = 60.0
JITTER_LOW = 0.8
JITTER_HIGH = 1.2
# 2**6 * 0.8 = 51.2 < 60 <= 2**7 * 0.8: any larger exponent gives the cap.
_MAX_EXPONENT = 16
STOP_JOIN_TIMEOUT_S = 10.0
THREAD_NAME = "qc-edge-publisher"

AUTH_ERROR_MESSAGE = (
    "the cloud refused the device key (%s): check DEVICE_API_KEY and restart qc-edge; "
    "publishing is paused"
)


class ConnectivityState:
    """``connectivity`` and ``last_success_at`` shared by the loop and the outbox, with a lock."""

    def __init__(
        self, connectivity: Connectivity = "disabled", last_success_at: datetime | None = None
    ) -> None:
        self._lock = threading.Lock()
        self._connectivity: Connectivity = connectivity
        self._last_success_at = last_success_at

    @property
    def connectivity(self) -> Connectivity:
        with self._lock:
            return self._connectivity

    @connectivity.setter
    def connectivity(self, value: Connectivity) -> None:
        with self._lock:
            self._connectivity = value

    @property
    def last_success_at(self) -> datetime | None:
        with self._lock:
            return self._last_success_at

    def record_success(self, at: datetime) -> None:
        """``online`` and ``last_success_at = at``, atomically."""
        with self._lock:
            self._connectivity = "online"
            self._last_success_at = at

    def snapshot(self) -> tuple[Connectivity, datetime | None]:
        """``(connectivity, last_success_at)`` read together."""
        with self._lock:
            return self._connectivity, self._last_success_at


class _Stopped(Exception):
    """End of the cycle with the unresolved items left as they are (``stop()`` or 401/403)."""


class _Unreachable(Exception):
    """Transient failure: every unresolved item of the cycle gets a retry with ``error``."""

    def __init__(self, error: str) -> None:
        super().__init__(error)
        self.error = error


class PublishLoop:
    """Publishes the due rows of ``outbox`` through ``publisher`` (SPEC-009 section 4.3).

    A ``connectivity`` still ``disabled`` becomes ``offline`` here: a loop exists, and the state
    is only ``online`` after a contact with the cloud.
    """

    def __init__(
        self,
        outbox: SqliteOutbox,
        publisher: Publisher,
        connectivity: ConnectivityState,
        clock: Clock = utc_now,
        rng: random.Random | None = None,
        interval_s: float = 2.0,
        health_every_s: float = 60.0,
    ) -> None:
        self._outbox = outbox
        self._publisher = publisher
        self._connectivity = connectivity
        self._clock = clock
        self._rng = rng if rng is not None else random.Random()
        self._interval_s = interval_s
        self._health_every_s = health_every_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_contact: datetime | None = clock()
        if connectivity.connectivity == "disabled":
            connectivity.connectivity = "offline"

    # -- backoff -----------------------------------------------------------------------------

    def delay_s(self, attempts: int) -> float:
        """``min(60, 2**attempts * U(0.8, 1.2))`` seconds; ``attempts`` before the increment."""
        exponent = min(max(attempts, 0), _MAX_EXPONENT)
        return min(MAX_DELAY_S, (2.0**exponent) * self._rng.uniform(JITTER_LOW, JITTER_HIGH))

    # -- one cycle ---------------------------------------------------------------------------

    def run_once(self) -> None:
        """One full cycle, synchronous (used by the thread and by the tests)."""
        if self._connectivity.connectivity == "auth_error":
            return
        resolved: set[UUID] = set()
        items: list[OutboxItem] = []
        try:
            items = self._outbox.fetch_due(DEFAULT_FETCH_LIMIT, max_delay_s=MAX_DELAY_S)
            if not items:
                self._maybe_check_health()
                return
            inspections = self._load(items, resolved)
            if inspections:
                self._publish(inspections, resolved)
        except _Stopped:
            return
        except _Unreachable as exc:
            remaining = _unresolved(items, resolved)
            logger.warning("publish failed for %d item(s): %s", len(remaining), exc.error)
            self._connectivity.connectivity = "offline"
            self._retry(remaining, exc.error)
        except Exception as exc:
            logger.exception("publish cycle failed unexpectedly")
            self._retry(_unresolved(items, resolved), f"unexpected error: {type(exc).__name__}")

    def _retry(self, ids: list[UUID], error: str) -> None:
        try:
            self._outbox.mark_retry(ids, error, self.delay_s)
        except Exception:
            logger.exception("could not schedule the retry of %d item(s)", len(ids))

    def _load(self, items: Sequence[OutboxItem], resolved: set[UUID]) -> list[InspectionCreate]:
        """Payloads as ``InspectionCreate``; an invalid one becomes ``dead`` (the API would 422)."""
        inspections: list[InspectionCreate] = []
        for item in items:
            try:
                inspections.append(item.to_inspection())
            except ValidationError as exc:
                error = f"invalid payload ({exc.error_count()} validation errors)"
                logger.error("inspection %s marked dead: %s", item.inspection_id, error)
                self._outbox.mark_dead(item.inspection_id, error)
                resolved.add(item.inspection_id)
        return inspections

    def _maybe_check_health(self) -> None:
        """Health check after ``health_every_s`` without contact, or after a clock jump back."""
        now = self._clock()
        last = self._last_contact
        if last is not None and 0 <= (now - last).total_seconds() < self._health_every_s:
            return
        self._last_contact = now
        healthy = self._publisher.check_health()
        self._connectivity.connectivity = "online" if healthy else "offline"

    def _publish(self, items: list[InspectionCreate], resolved: set[UUID]) -> None:
        """Publish ``items``; bisection on a refusal. Raises ``_Stopped`` after ``stop()``."""
        if self._stop_event.is_set():
            raise _Stopped
        ids = [item.inspection_id for item in items]
        self._last_contact = self._clock()
        try:
            self._publisher.publish_batch(items)
        except PublishTransientError as exc:
            # The cloud is unreachable: no other half of a bisection is tried in this cycle.
            raise _Unreachable(str(exc) or type(exc).__name__) from None
        except PublishAuthError as exc:
            self._connectivity.connectivity = "auth_error"
            logger.error(AUTH_ERROR_MESSAGE, exc)
            raise _Stopped from None
        except PublishRejectedError as exc:
            logger.warning("cloud rejected a batch of %d item(s): %s", len(items), exc.detail)
            if len(items) == 1:
                logger.error("inspection %s marked dead: %s", ids[0], exc.detail)
                self._outbox.mark_dead(ids[0], exc.detail)
                resolved.add(ids[0])
                return
            middle = len(items) // 2
            self._publish(items[:middle], resolved)
            self._publish(items[middle:], resolved)
            return
        self._outbox.mark_sent(ids)
        resolved.update(ids)
        self._connectivity.record_success(self._clock())

    # -- thread ------------------------------------------------------------------------------

    def start(self) -> None:
        """Start the daemon thread; the first cycle checks the cloud right away when idle."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._last_contact = None
        self._thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the thread and wait for it (at most 10 s)."""
        self._stop_event.set()
        thread = self._thread
        if thread is None:
            return
        thread.join(STOP_JOIN_TIMEOUT_S)
        if thread.is_alive():
            logger.warning("publisher thread did not stop within %.0f s", STOP_JOIN_TIMEOUT_S)
        else:
            self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:  # run_once already catches; this keeps the thread alive anyway
                logger.exception("publish cycle failed unexpectedly")
            self._stop_event.wait(self._interval_s)


def _unresolved(items: Sequence[OutboxItem], resolved: set[UUID]) -> list[UUID]:
    return [item.inspection_id for item in items if item.inspection_id not in resolved]
