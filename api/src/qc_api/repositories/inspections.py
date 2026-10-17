"""Listing and aggregate queries over ``inspections`` (SPEC-005 sections 4.2 to 4.4).

* Every value (filters, ``limit``/``offset``, the time bucket) is a psycopg parameter. The only
  composition is ``psycopg.sql``: the ``where`` clause is a join of fixed fragments, each with
  its own named placeholder (``%(f_<name>)s``).
* Aggregations run in SQL (``count(*) filter (...)``, ``avg``, ``group by``); only one row per
  page item, bucket or lot reaches Python.
* Every read runs in one ``repeatable read, read only`` transaction, so a page and its
  ``total`` (or a summary and its breakdowns) come from the same snapshot.
* ``lot_counts`` feeds the SPC (SPEC-006 section 4.2): one row per lot, ``unknown`` objects
  left out, a single ``source`` (never a mix, R-06).
* The defect rate is ``defective / (total - unknown)`` and ``null`` when the denominator is 0
  (``nullif``), never a division error. ``is_defective`` is the generated column that mirrors
  ``qc_contracts.is_defective`` (ADR-013, SPEC-003).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from qc_api.db import db_connection
from qc_api.filters import InspectionFilters
from qc_api.services.spc import LotCounts
from qc_contracts import (
    Grade,
    InspectionRead,
    LotSummary,
    MetricsSummary,
    ObjectType,
    Page,
    Source,
    TimeseriesPoint,
)

Bucket = Literal["minute", "hour", "day"]

MAX_BUCKETS = 5_000
# Largest value of a Postgres ``bigint``: a larger ``offset`` would be a SQLSTATE 22003 error.
# Any offset at or above it is past the last row anyway, so the result is the same.
MAX_SQL_OFFSET = 2**63 - 1
BUCKET_TIME_ZONE = "UTC"

READ_SNAPSHOT = "set transaction isolation level repeatable read, read only"

# Fixed parameters shared by the statements below.
_UNKNOWN = ObjectType.UNKNOWN.value

INSPECTION_COLUMNS = (
    "inspection_id",
    "device_id",
    "lot_id",
    "inspected_at",
    "object_type",
    "grade",
    "grade_score",
    "type_confidence",
    "grade_confidence",
    "needs_review",
    "model_version",
    "model_sha256",
    "latency_ms",
    "source",
    "received_at",
    "is_defective",
)

COUNT_INSPECTIONS = "select count(*) as total from inspections where {where}"

SELECT_INSPECTIONS_PAGE = """
select {columns}
from inspections
where {where}
order by inspected_at desc, inspection_id asc
limit %(limit)s offset %(offset)s
"""

SELECT_SUMMARY = """
with matched as (
    select object_type, grade, is_defective, needs_review, type_confidence, grade_score
    from inspections
    where {where}
)
select
    count(*) as total,
    count(*) filter (where is_defective) as defective,
    count(*) filter (where is_defective)::float8
        / nullif(count(*) filter (where object_type <> %(unknown)s), 0) as defect_rate,
    count(*) filter (where object_type = %(unknown)s) as unknown_count,
    count(*) filter (where needs_review) as needs_review_count,
    avg(type_confidence) as mean_type_confidence,
    avg(grade_score) as mean_grade_score,
    (
        select coalesce(jsonb_object_agg(by_grade.grade, by_grade.n), '{{}}'::jsonb)
        from (
            select grade, count(*) as n from matched where grade is not null group by grade
        ) as by_grade
    ) as by_grade,
    (
        select coalesce(jsonb_object_agg(by_type.object_type, by_type.n), '{{}}'::jsonb)
        from (select object_type, count(*) as n from matched group by object_type) as by_type
    ) as by_object_type
from matched
"""

SELECT_TIMESERIES = """
select
    date_trunc(%(bucket)s, inspected_at, %(time_zone)s) as bucket_start,
    count(*) as total,
    count(*) filter (where is_defective) as defective,
    count(*) filter (where is_defective)::float8
        / nullif(count(*) filter (where object_type <> %(unknown)s), 0) as defect_rate
from inspections
where {where}
group by 1
order by 1
limit %(max_rows)s
"""

COUNT_LOTS = "select count(distinct lot_id) as total from inspections where {where}"

SELECT_LOTS_PAGE = """
select
    lot_id,
    count(*) as n,
    count(*) filter (where is_defective) as defects,
    count(*) filter (where object_type = %(unknown)s) as unknown_count,
    min(inspected_at) as started_at,
    max(inspected_at) as ended_at,
    array_agg(distinct source) as sources
from inspections
where {where}
group by lot_id
order by started_at desc, lot_id asc
limit %(limit)s offset %(offset)s
"""

SELECT_LOT_COUNTS = """
select
    lot_id,
    count(*) as n,
    count(*) filter (where is_defective) as defects,
    min(inspected_at) as started_at,
    max(inspected_at) as ended_at
from inspections
where {where}
group by lot_id
order by started_at, lot_id
"""


class TooManyBucketsError(Exception):
    """The time series would have more than ``MAX_BUCKETS`` buckets."""


def where_clause(filters: InspectionFilters) -> tuple[sql.Composable, dict[str, Any]]:
    """``(condition, params)`` for ``filters``; ``true`` when nothing is filtered."""
    conditions: list[sql.Composable] = []
    params: dict[str, Any] = {}
    if filters.device_id is not None:
        conditions.append(sql.SQL("device_id = %(f_device_id)s"))
        params["f_device_id"] = filters.device_id
    if filters.lot_id is not None:
        conditions.append(sql.SQL("lot_id = %(f_lot_id)s"))
        params["f_lot_id"] = filters.lot_id
    if filters.object_type is not None:
        conditions.append(sql.SQL("object_type = %(f_object_type)s"))
        params["f_object_type"] = filters.object_type.value
    if filters.grade is not None:
        # Equality already excludes null grades.
        conditions.append(sql.SQL("grade = %(f_grade)s"))
        params["f_grade"] = filters.grade.value
    if filters.source is not None:
        conditions.append(sql.SQL("source = %(f_source)s"))
        params["f_source"] = filters.source.value
    if filters.defective is not None:
        conditions.append(sql.SQL("is_defective = %(f_defective)s"))
        params["f_defective"] = filters.defective
    if filters.from_ is not None:
        conditions.append(sql.SQL("inspected_at >= %(f_from)s"))
        params["f_from"] = filters.from_
    if filters.to is not None:
        conditions.append(sql.SQL("inspected_at < %(f_to)s"))
        params["f_to"] = filters.to
    if not conditions:
        return sql.SQL("true"), params
    return sql.SQL(" and ").join(conditions), params


@contextmanager
def _read_snapshot(pool: ConnectionPool) -> Iterator[psycopg.Cursor[dict[str, Any]]]:
    """Cursor with ``dict`` rows in a read-only, repeatable-read transaction.

    A database that cannot be reached becomes ``DatabaseUnavailableError`` (``db_connection``).
    """
    with db_connection(pool) as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(READ_SNAPSHOT)
        yield cursor


def _sql_offset(offset: int) -> int:
    return min(offset, MAX_SQL_OFFSET)


def list_inspections(
    pool: ConnectionPool, filters: InspectionFilters, limit: int, offset: int
) -> Page[InspectionRead]:
    """Inspections that match ``filters``, newest first (ties by ``inspection_id``)."""
    where, params = where_clause(filters)
    columns = sql.SQL(", ").join(sql.Identifier(column) for column in INSPECTION_COLUMNS)
    with _read_snapshot(pool) as cursor:
        cursor.execute(sql.SQL(COUNT_INSPECTIONS).format(where=where), params)
        total = _fetch_one(cursor)["total"]
        cursor.execute(
            sql.SQL(SELECT_INSPECTIONS_PAGE).format(columns=columns, where=where),
            {**params, "limit": limit, "offset": _sql_offset(offset)},
        )
        rows = cursor.fetchall()
    items = [InspectionRead.model_validate(row) for row in rows]
    return Page[InspectionRead](items=items, total=total, limit=limit, offset=offset)


def summarize(pool: ConnectionPool, filters: InspectionFilters) -> MetricsSummary:
    """Totals, breakdowns (every enum key present, 0 when absent) and means."""
    where, params = where_clause(filters)
    with _read_snapshot(pool) as cursor:
        cursor.execute(sql.SQL(SELECT_SUMMARY).format(where=where), {**params, "unknown": _UNKNOWN})
        row = _fetch_one(cursor)
    by_grade = {grade: 0 for grade in Grade}
    by_grade.update({Grade(key): int(value) for key, value in row["by_grade"].items()})
    by_object_type = {object_type: 0 for object_type in ObjectType}
    by_object_type.update(
        {ObjectType(key): int(value) for key, value in row["by_object_type"].items()}
    )
    return MetricsSummary(
        total=row["total"],
        defective=row["defective"],
        defect_rate=row["defect_rate"],
        unknown_count=row["unknown_count"],
        needs_review_count=row["needs_review_count"],
        by_grade=by_grade,
        by_object_type=by_object_type,
        mean_type_confidence=row["mean_type_confidence"],
        mean_grade_score=row["mean_grade_score"],
    )


def timeseries(
    pool: ConnectionPool, filters: InspectionFilters, bucket: Bucket
) -> list[TimeseriesPoint]:
    """One point per non-empty bucket (truncated in UTC), in ascending ``bucket_start`` order.

    Raises ``TooManyBucketsError`` when there would be more than ``MAX_BUCKETS`` points; at most
    ``MAX_BUCKETS + 1`` rows are fetched to find out.
    """
    where, params = where_clause(filters)
    query_params = {
        **params,
        "bucket": bucket,
        "time_zone": BUCKET_TIME_ZONE,
        "unknown": _UNKNOWN,
        "max_rows": MAX_BUCKETS + 1,
    }
    with _read_snapshot(pool) as cursor:
        cursor.execute(sql.SQL(SELECT_TIMESERIES).format(where=where), query_params)
        rows = cursor.fetchall()
    if len(rows) > MAX_BUCKETS:
        raise TooManyBucketsError
    return [TimeseriesPoint.model_validate(row) for row in rows]


def list_lots(
    pool: ConnectionPool, filters: InspectionFilters, limit: int, offset: int
) -> Page[LotSummary]:
    """One summary per ``lot_id`` among the matching rows, most recently started first."""
    where, params = where_clause(filters)
    with _read_snapshot(pool) as cursor:
        cursor.execute(sql.SQL(COUNT_LOTS).format(where=where), params)
        total = _fetch_one(cursor)["total"]
        cursor.execute(
            sql.SQL(SELECT_LOTS_PAGE).format(where=where),
            {**params, "unknown": _UNKNOWN, "limit": limit, "offset": _sql_offset(offset)},
        )
        rows = cursor.fetchall()
    items = [_lot_summary(row) for row in rows]
    return Page[LotSummary](items=items, total=total, limit=limit, offset=offset)


def lot_counts(
    pool: ConnectionPool, source: Source, object_type: ObjectType | None = None
) -> list[LotCounts]:
    """Per-lot ``n`` and ``defects`` of one ``source`` for the SPC, ``unknown`` objects excluded.

    ``object_type=None`` keeps every known type; otherwise only that type. Lots come ordered by
    ``(started_at, lot_id)``.
    """
    conditions = [
        sql.SQL("object_type <> %(unknown)s"),
        sql.SQL("source = %(f_source)s"),
    ]
    params: dict[str, Any] = {"unknown": _UNKNOWN, "f_source": source.value}
    if object_type is not None:
        conditions.append(sql.SQL("object_type = %(f_object_type)s"))
        params["f_object_type"] = object_type.value
    where = sql.SQL(" and ").join(conditions)
    with _read_snapshot(pool) as cursor:
        cursor.execute(sql.SQL(SELECT_LOT_COUNTS).format(where=where), params)
        rows = cursor.fetchall()
    return [LotCounts(**row) for row in rows]


def _lot_summary(row: dict[str, Any]) -> LotSummary:
    present = set(row["sources"])
    return LotSummary.model_validate(
        {**row, "sources": [source for source in Source if source.value in present]}
    )


def _fetch_one(cursor: psycopg.Cursor[dict[str, Any]]) -> dict[str, Any]:
    row = cursor.fetchone()
    if row is None:  # an aggregate without group by always returns one row
        raise RuntimeError("aggregate query returned no row")
    return row
