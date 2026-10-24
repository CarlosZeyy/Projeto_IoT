"""Durable outbox of the edge gateway (SPEC-009 section 4.1, docs/architecture.md section 6.2).

``SqliteOutbox`` implements the ``InspectionSink`` of SPEC-007: every accepted inspection is
committed to a SQLite file before the capture is answered, and the publish loop
(``qc_edge.publish_loop``) sends the pending rows to the cloud. Nothing here talks to the network
and no image is ever stored here (R-02): the ``payload`` column is the JSON of the contract's
``InspectionCreate``.

* One connection (``check_same_thread=False``) guarded by a ``threading.Lock``; WAL journal and
  ``synchronous=FULL``, so a committed ``put`` survives a crash of the process.
* Dates are ISO 8601 in UTC with a fixed width (``isoformat(timespec="microseconds")``, suffix
  ``+00:00``), so the text order of the columns is the time order.
* ``put`` is idempotent by ``inspection_id`` (R-05): a second ``put`` never changes the row.
* ``last_error`` is cut to 500 characters. The callers never put the device key in it (the HTTP
  publisher removes it from every message it builds, SPEC-009 section 4.1).
* ``dead_items`` and ``requeue_dead`` (SPEC-034 section 4.1) list the ``dead`` rows and put them
  back to ``pending``; ``open_existing`` opens a file that already exists without ever creating
  it, for the ``python -m qc_edge.requeue`` CLI.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote
from uuid import UUID

from qc_contracts import InspectionCreate
from qc_edge.fsutil import create_private_file, make_private_dirs
from qc_edge.sink import SinkError, SinkStats

if TYPE_CHECKING:
    from qc_edge.publish_loop import ConnectivityState

logger = logging.getLogger("qc_edge")

Clock = Callable[[], datetime]
"""Returns the current time, timezone-aware (converted to UTC here); injectable in tests."""

OUTBOX_FILE_NAME = "outbox.sqlite3"
MAX_LAST_ERROR = 500
DEFAULT_FETCH_LIMIT = 100
DEFAULT_MAX_DELAY_S = 60.0
"""Longest backoff delay (``MAX_DELAY_S`` of ``qc_edge.publish_loop``, SPEC-009 section 4.3)."""
REQUEUE_CHUNK = 100
"""Most ids per ``UPDATE`` of ``requeue_dead`` (SPEC-034 section 4.1)."""
OPEN_TIMEOUT_S = 5.0
"""Busy timeout of ``open_existing`` (SPEC-034 section 4.2)."""
OUTBOX_COLUMNS = (
    "inspection_id",
    "payload",
    "created_at",
    "attempts",
    "next_attempt_at",
    "sent_at",
    "status",
    "last_error",
)

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_DEAD = "dead"

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
  inspection_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT NOT NULL, sent_at TEXT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','sent','dead')), last_error TEXT NULL);
CREATE INDEX IF NOT EXISTS outbox_due ON outbox(status, next_attempt_at, created_at);
"""


def utc_now() -> datetime:
    """Current time, timezone-aware, in UTC."""
    return datetime.now(UTC)


def format_timestamp(value: datetime) -> str:
    """``value`` in UTC, ISO 8601 with microseconds and ``+00:00`` (fixed width).

    Raises:
        ValueError: ``value`` is naive.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("the outbox clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def parse_timestamp(value: str) -> datetime:
    """Inverse of ``format_timestamp``."""
    return datetime.fromisoformat(value).astimezone(UTC)


def cut_error(error: str) -> str:
    """``error`` cut to ``MAX_LAST_ERROR`` characters."""
    return error[:MAX_LAST_ERROR]


@dataclass(frozen=True)
class OutboxItem:
    """A pending row returned by ``SqliteOutbox.fetch_due``."""

    inspection_id: UUID
    payload: str
    created_at: datetime
    attempts: int
    next_attempt_at: datetime

    def to_inspection(self) -> InspectionCreate:
        """The stored ``InspectionCreate`` (validated again by the contract).

        Raises:
            pydantic.ValidationError: the payload is not a valid ``InspectionCreate``.
        """
        return InspectionCreate.model_validate_json(self.payload)


@dataclass(frozen=True)
class DeadItem:
    """A ``dead`` row returned by ``SqliteOutbox.dead_items`` (SPEC-034); never the payload."""

    inspection_id: UUID
    created_at: datetime
    attempts: int
    last_error: str | None


class NotAnOutboxError(Exception):
    """The file opened by ``SqliteOutbox.open_existing`` has no ``outbox`` table of SPEC-009."""


class SqliteOutbox:
    """Durable ``InspectionSink`` backed by a SQLite file (SPEC-009 section 4.1).

    ``connectivity`` is shared with the publish loop; without it (no loop), ``stats()`` reports
    ``connectivity="disabled"`` and no ``last_success_at``.

    Raises:
        sqlite3.Error, OSError: the file cannot be created or opened (the CLI exits with 2).
    """

    def __init__(
        self,
        path: Path,
        clock: Clock = utc_now,
        connectivity: ConnectivityState | None = None,
    ) -> None:
        self._setup(path, clock, connectivity)
        _prepare_file(self._path)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        try:
            mode = self._conn.execute("PRAGMA journal_mode=WAL").fetchone()
            if mode is None or str(mode[0]).lower() != "wal":
                logger.warning("outbox: the WAL journal is not available on this file system")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.executescript(SCHEMA)
        except BaseException:
            self._conn.close()
            raise

    def _setup(self, path: Path, clock: Clock, connectivity: ConnectivityState | None) -> None:
        self._path = Path(path)
        self._clock = clock
        self._connectivity = connectivity
        self._lock = threading.Lock()
        self._closed = False

    @classmethod
    def open_existing(
        cls,
        path: Path,
        *,
        clock: Clock = utc_now,
        read_only: bool = False,
        timeout_s: float = OPEN_TIMEOUT_S,
    ) -> SqliteOutbox:
        """Open an outbox file that already exists; the file is never created (SPEC-034).

        The SQLite URI uses ``mode=rw`` (or ``mode=ro`` with ``read_only``), so a missing file
        is an error instead of a new empty database. Nothing is written on open: no journal
        mode change and no ``CREATE TABLE``. ``timeout_s`` is the busy timeout, so a write
        waits for the ``qc-edge`` process (WAL) instead of failing at once. Without
        ``connectivity``, ``stats()`` reports ``disabled``.

        Raises:
            sqlite3.Error: the file cannot be opened or is not a SQLite database.
            NotAnOutboxError: the database has no ``outbox`` table with the SPEC-009 columns.
        """
        box = cls.__new__(cls)
        box._setup(path, clock, None)
        mode = "ro" if read_only else "rw"
        uri = f"file:{quote(str(box._path.absolute()))}?mode={mode}"
        box._conn = sqlite3.connect(uri, uri=True, timeout=timeout_s, check_same_thread=False)
        try:
            box._conn.execute("PRAGMA synchronous=FULL")
            columns = tuple(
                row[1] for row in box._conn.execute("PRAGMA table_info(outbox)").fetchall()
            )
            if columns != OUTBOX_COLUMNS:
                raise NotAnOutboxError("the file has no outbox table")
        except BaseException:
            box._conn.close()
            raise
        return box

    @property
    def path(self) -> Path:
        return self._path

    def _now(self) -> str:
        return format_timestamp(self._clock())

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Lock + transaction: commit on success, rollback on error."""
        with self._lock, self._conn:
            yield self._conn

    def put(self, inspection: InspectionCreate) -> None:
        """Insert ``inspection`` as ``pending``; a known ``inspection_id`` leaves the row as it is.

        Committed (and synced, ``synchronous=FULL``) before returning.

        Raises:
            SinkError: SQLite failed (the capture answers 503, SPEC-007).
        """
        payload = inspection.model_dump_json()
        now = self._now()
        try:
            with self._transaction() as conn:
                conn.execute(
                    "INSERT INTO outbox (inspection_id, payload, created_at, attempts, "
                    "next_attempt_at, sent_at, status, last_error) "
                    "VALUES (?, ?, ?, 0, ?, NULL, 'pending', NULL) "
                    "ON CONFLICT (inspection_id) DO NOTHING",
                    (str(inspection.inspection_id), payload, now, now),
                )
        except sqlite3.Error as exc:
            raise SinkError(f"outbox write failed ({type(exc).__name__})") from exc

    def fetch_due(
        self, limit: int = DEFAULT_FETCH_LIMIT, *, max_delay_s: float = DEFAULT_MAX_DELAY_S
    ) -> list[OutboxItem]:
        """Pending rows that are due, oldest ``created_at`` first (SPEC-030 section 4.2).

        A row is due when ``next_attempt_at <= now`` or ``next_attempt_at > now + max_delay_s``.
        The backoff never schedules more than ``max_delay_s`` ahead, so the second case only
        happens after the wall clock jumped back; without it the row would wait the delay plus
        the size of the jump. Rows with the same ``created_at`` keep their insertion order.
        """
        if limit < 1:
            return []
        now = self._clock()
        now_text = format_timestamp(now)
        horizon = format_timestamp(now + timedelta(seconds=max_delay_s))
        with self._lock:
            rows = self._conn.execute(
                "SELECT inspection_id, payload, created_at, attempts, next_attempt_at "
                "FROM outbox WHERE status = 'pending' "
                "AND (next_attempt_at <= ? OR next_attempt_at > ?) "
                "ORDER BY created_at, rowid LIMIT ?",
                (now_text, horizon, limit),
            ).fetchall()
        return [
            OutboxItem(
                inspection_id=UUID(row[0]),
                payload=row[1],
                created_at=parse_timestamp(row[2]),
                attempts=int(row[3]),
                next_attempt_at=parse_timestamp(row[4]),
            )
            for row in rows
        ]

    def mark_sent(self, ids: Sequence[UUID]) -> None:
        """``pending`` -> ``sent`` with ``sent_at = now``."""
        if not ids:
            return
        now = self._now()
        with self._transaction() as conn:
            conn.executemany(
                "UPDATE outbox SET status = 'sent', sent_at = ? "
                "WHERE inspection_id = ? AND status = 'pending'",
                [(now, str(inspection_id)) for inspection_id in ids],
            )

    def mark_retry(self, ids: Sequence[UUID], error: str, delay_s: Callable[[int], float]) -> None:
        """For each pending row: ``next_attempt_at = now + delay_s(attempts)``, ``attempts += 1``.

        ``delay_s`` receives the number of attempts *before* the increment.
        """
        if not ids:
            return
        now = self._clock()
        now_text = format_timestamp(now)
        message = cut_error(error)
        with self._transaction() as conn:
            for inspection_id in ids:
                row = conn.execute(
                    "SELECT attempts FROM outbox WHERE inspection_id = ? AND status = 'pending'",
                    (str(inspection_id),),
                ).fetchone()
                if row is None:
                    continue
                attempts = int(row[0])
                next_at = format_timestamp(now + timedelta(seconds=delay_s(attempts)))
                conn.execute(
                    "UPDATE outbox SET attempts = ?, next_attempt_at = ?, last_error = ? "
                    "WHERE inspection_id = ?",
                    (attempts + 1, max(next_at, now_text), message, str(inspection_id)),
                )

    def mark_dead(self, inspection_id: UUID, error: str) -> None:
        """``pending`` -> ``dead`` (never sent again) with ``last_error``."""
        with self._transaction() as conn:
            conn.execute(
                "UPDATE outbox SET status = 'dead', last_error = ? "
                "WHERE inspection_id = ? AND status = 'pending'",
                (cut_error(error), str(inspection_id)),
            )

    def dead_items(self) -> list[DeadItem]:
        """``dead`` rows, oldest ``created_at`` first (then insertion order); never the payload."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT inspection_id, created_at, attempts, last_error FROM outbox "
                "WHERE status = 'dead' ORDER BY created_at, rowid"
            ).fetchall()
        return [
            DeadItem(
                inspection_id=UUID(row[0]),
                created_at=parse_timestamp(row[1]),
                attempts=int(row[2]),
                last_error=row[3],
            )
            for row in rows
        ]

    def requeue_dead(self, ids: Sequence[UUID] | None = None) -> int:
        """``dead`` -> ``pending``: every ``dead`` row (``None``) or the ``dead`` rows in ``ids``.

        Each changed row gets ``attempts = 0``, ``next_attempt_at = now`` (the outbox clock) and
        ``last_error = NULL``; ``inspection_id``, ``payload``, ``created_at`` and ``sent_at``
        stay. Unknown ids and rows that are ``pending`` or ``sent`` are ignored: a ``sent`` row
        never comes back (R-05). One transaction, with ``ids`` sent in chunks of 100. Returns
        the number of changed rows.
        """
        now = self._now()
        update = (
            "UPDATE outbox SET status = 'pending', attempts = 0, next_attempt_at = ?, "
            "last_error = NULL WHERE status = 'dead'"
        )
        changed = 0
        with self._transaction() as conn:
            if ids is None:
                changed = conn.execute(update, (now,)).rowcount
            else:
                keys = [str(UUID(str(inspection_id))) for inspection_id in ids]
                for start in range(0, len(keys), REQUEUE_CHUNK):
                    chunk = keys[start : start + REQUEUE_CHUNK]
                    # Only placeholders go into the text; every value is a parameter.
                    marks = ", ".join(["?"] * len(chunk))
                    changed += conn.execute(
                        f"{update} AND inspection_id IN ({marks})", (now, *chunk)
                    ).rowcount
        return changed

    def stats(self) -> SinkStats:
        """Counts of ``pending`` and ``dead`` rows plus the connectivity of the publish loop.

        Raises:
            SinkError: SQLite failed.
        """
        try:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT status, count(*) FROM outbox WHERE status IN ('pending', 'dead') "
                    "GROUP BY status"
                ).fetchall()
        except sqlite3.Error as exc:
            raise SinkError(f"outbox read failed ({type(exc).__name__})") from exc
        counts = {status: int(count) for status, count in rows}
        if self._connectivity is None:
            connectivity, last_success_at = "disabled", None
        else:
            connectivity, last_success_at = self._connectivity.snapshot()
        return SinkStats(
            pending=counts.get(STATUS_PENDING, 0),
            dead=counts.get(STATUS_DEAD, 0),
            last_success_at=last_success_at,
            connectivity=connectivity,
        )

    def close(self) -> None:
        """Close the connection; idempotent. A later ``put`` raises ``SinkError``."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._conn.close()


def _prepare_file(path: Path) -> None:
    """Missing parent directories with ``0700``; a new database file with ``0600``.

    SQLite gives its ``-wal`` and ``-shm`` files the mode of the database file.
    """
    make_private_dirs(path.parent)
    try:
        fd = create_private_file(path)
    except FileExistsError:
        return
    os.close(fd)
