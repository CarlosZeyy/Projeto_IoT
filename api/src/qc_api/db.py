"""Database access: connection pool, idempotent writes (SPEC-004 sections 4.2 and 4.4, ADR-006).

psycopg 3 straight to Postgres (Supabase pooler in transaction mode), so every connection uses
``prepare_threshold=None``. All SQL is parameterized.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from qc_api.errors import DatabaseUnavailableError
from qc_contracts import InspectionCreate, InspectionCreated

POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 5
POOL_TIMEOUT_S = 5
CONNECT_TIMEOUT_S = 5

SELECT_DEVICE_BY_HASH = "select device_id, api_key_hash from devices where api_key_hash = %s"

INSERT_INSPECTION = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
on conflict (inspection_id) do nothing
returning inspection_id
"""

UPDATE_LAST_SEEN = "update devices set last_seen_at = now() where device_id = %s"


def create_pool(conninfo: str) -> ConnectionPool:
    """Pool that is not opened yet; the caller opens it with ``open(wait=False)``."""
    return ConnectionPool(
        conninfo,
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        timeout=POOL_TIMEOUT_S,
        open=False,
        kwargs={"prepare_threshold": None, "connect_timeout": CONNECT_TIMEOUT_S},
    )


@contextmanager
def db_connection(pool: ConnectionPool) -> Iterator[psycopg.Connection]:
    """Borrow a connection from the pool.

    On a normal exit the pool commits; on an exception it rolls back. ``PoolTimeout`` and
    ``OperationalError`` (also when raised by the caller's queries) become
    ``DatabaseUnavailableError``, without the original message.
    """
    try:
        with pool.connection() as conn:
            yield conn
    except (PoolTimeout, psycopg.OperationalError):
        raise DatabaseUnavailableError from None


def ping(pool: ConnectionPool) -> None:
    """``SELECT 1``; raises ``DatabaseUnavailableError`` when the database cannot answer."""
    with db_connection(pool) as conn:
        conn.execute("select 1")


def find_device_by_key_hash(pool: ConnectionPool, key_hash: str) -> tuple[str, str] | None:
    """``(device_id, api_key_hash)`` of the device that owns ``key_hash``, or ``None``."""
    with db_connection(pool) as conn:
        row = conn.execute(SELECT_DEVICE_BY_HASH, (key_hash,)).fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1])


def _insert_params(item: InspectionCreate) -> tuple[object, ...]:
    return (
        item.inspection_id,
        item.device_id,
        item.lot_id,
        item.inspected_at,
        item.object_type.value,
        item.grade.value if item.grade is not None else None,
        item.grade_score,
        item.type_confidence,
        item.grade_confidence,
        item.needs_review,
        item.model_version,
        item.model_sha256,
        item.latency_ms,
        item.source.value,
    )


def insert_inspections(
    pool: ConnectionPool, device_id: str, items: Sequence[InspectionCreate]
) -> list[InspectionCreated]:
    """Insert ``items`` in order, in a single transaction, and touch ``last_seen_at``.

    Idempotent by ``inspection_id`` (``ON CONFLICT DO NOTHING``, R-05): an existing ID (or one
    repeated earlier in ``items``) is reported as ``duplicate`` and the stored row is not changed.
    Any error rolls back everything, including ``last_seen_at``. ``psycopg.DataError`` (SQLSTATE
    class 22) and ``psycopg.IntegrityError`` (class 23) propagate to the caller unchanged.
    """
    results: list[InspectionCreated] = []
    with db_connection(pool) as conn, conn.transaction():
        for item in items:
            row = conn.execute(INSERT_INSPECTION, _insert_params(item)).fetchone()
            results.append(
                InspectionCreated(
                    inspection_id=item.inspection_id,
                    status="created" if row is not None else "duplicate",
                )
            )
        conn.execute(UPDATE_LAST_SEEN, (device_id,))
    return results
