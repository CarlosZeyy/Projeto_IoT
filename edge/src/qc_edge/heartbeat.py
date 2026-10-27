"""Heartbeat of the edge gateway (SPEC-018 section 4.4).

``HeartbeatLoop`` implements the ``BackgroundService`` of SPEC-007: a daemon thread sends one
``qc_contracts.HeartbeatCreate`` right after the start and then one every ``interval_s`` seconds
(``HEARTBEAT_INTERVAL_S``). Each heartbeat carries:

* ``model_version``/``model_sha256`` of the loaded model, or both ``None`` without a model;
* ``app_version = qc_edge.__version__``;
* ``uptime_s``: whole seconds of the monotonic clock since the loop was built (at the start of
  ``qc-edge``), capped at ``MAX_HEARTBEAT_COUNT``;
* ``outbox_pending``/``outbox_dead`` from the ``SinkStats`` of the sink, capped the same way.

The heartbeat never goes through the outbox. A failure to send is one ``WARNING`` with the
summary from the publisher (never a body, never the key) and the loop goes on; a
``PublishAuthError`` (401/403) is one ``ERROR`` and the loop stops until ``qc-edge`` restarts,
like the ``PublishLoop`` (SPEC-009 section 4.3). No exception ever leaves ``run_once``.

The loop only knows the ``HeartbeatPublisher`` protocol, never ``httpx`` (SPEC-007, CA-17). It is
registered by ``qc_edge.cli`` under the same conditions as the ``PublishLoop`` and only when
``HEARTBEAT_INTERVAL_S`` is not ``0``: never with ``--stub-model`` (R-06). The body has no image
and no personal data (R-02).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from pydantic import ValidationError

import qc_edge
from qc_contracts import MAX_HEARTBEAT_COUNT, HeartbeatCreate
from qc_edge.inference import Inferencer
from qc_edge.outbox import Clock, utc_now
from qc_edge.publisher import HeartbeatPublisher, PublishAuthError, PublishTransientError
from qc_edge.sink import InspectionSink, SinkError

logger = logging.getLogger("qc_edge")

THREAD_NAME = "qc-edge-heartbeat"
STOP_JOIN_TIMEOUT_S = 10.0

AUTH_ERROR_MESSAGE = (
    "the cloud refused the device key for the heartbeat (%s): check DEVICE_API_KEY and restart "
    "qc-edge; heartbeats are paused"
)


def _cap(value: int) -> int:
    return min(max(int(value), 0), MAX_HEARTBEAT_COUNT)


class HeartbeatLoop:
    """Sends the heartbeat of the gateway every ``interval_s`` seconds (SPEC-018 section 4.4).

    ``inferencer`` is the loaded model (``None`` without a model). ``clock`` (wall clock, for
    ``sent_at``) and ``monotonic`` (for ``uptime_s``) are injectable for the tests.

    Raises:
        ValueError: ``interval_s`` is not positive.
    """

    def __init__(
        self,
        publisher: HeartbeatPublisher,
        sink: InspectionSink,
        inferencer: Inferencer | None,
        *,
        interval_s: float,
        app_version: str = qc_edge.__version__,
        clock: Clock = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not interval_s > 0:
            raise ValueError("interval_s must be > 0")
        self._publisher = publisher
        self._sink = sink
        self._inferencer = inferencer
        self._interval_s = interval_s
        self._app_version = app_version
        self._clock = clock
        self._monotonic = monotonic
        self._started_at = monotonic()
        self._auth_error = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def interval_s(self) -> float:
        return self._interval_s

    @property
    def auth_error(self) -> bool:
        """``True`` after a 401/403: no heartbeat until ``qc-edge`` restarts."""
        return self._auth_error

    def build(self) -> HeartbeatCreate:
        """The heartbeat of now.

        Raises:
            SinkError: the outbox could not be read.
            pydantic.ValidationError: a value outside the contract.
        """
        stats = self._sink.stats()
        model = self._inferencer.model_info if self._inferencer is not None else None
        return HeartbeatCreate(
            sent_at=self._clock(),
            model_version=model.model_version if model is not None else None,
            model_sha256=model.model_sha256 if model is not None else None,
            app_version=self._app_version,
            uptime_s=_cap(self._monotonic() - self._started_at),
            outbox_pending=_cap(stats.pending),
            outbox_dead=_cap(stats.dead),
        )

    def run_once(self) -> None:
        """One heartbeat, synchronous (used by the thread and by the tests); never raises."""
        if self._auth_error:
            return
        try:
            heartbeat = self.build()
        except SinkError as exc:
            logger.warning("heartbeat skipped: %s", exc)
            return
        except ValidationError as exc:
            logger.warning("heartbeat skipped: %d validation errors", exc.error_count())
            return
        except Exception:
            logger.exception("heartbeat could not be built")
            return
        try:
            self._publisher.send_heartbeat(heartbeat)
        except PublishTransientError as exc:
            logger.warning("heartbeat failed: %s", str(exc) or type(exc).__name__)
        except PublishAuthError as exc:
            self._auth_error = True
            logger.error(AUTH_ERROR_MESSAGE, exc)
        except Exception as exc:
            # Only the class name: an unexpected message could carry anything.
            logger.warning("heartbeat failed unexpectedly: %s", type(exc).__name__)

    # -- thread ------------------------------------------------------------------------------

    def start(self) -> None:
        """Start the daemon thread; the first heartbeat is sent right away."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
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
            logger.warning("heartbeat thread did not stop within %.0f s", STOP_JOIN_TIMEOUT_S)
        else:
            self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            if self._auth_error:
                return  # paused until qc-edge restarts
            self._stop_event.wait(self._interval_s)
