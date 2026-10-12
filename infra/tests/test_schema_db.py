"""Schema of 001_init.sql against the test PostgreSQL (SPEC-003 §4.1). All tests are marked `db`."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from psycopg import errors

from qc_contracts import Grade, ObjectType, Source, is_defective

pytestmark = pytest.mark.db

DEVICE = "edge-01"
SHA = "a" * 64
INT4_MAX = 2_147_483_647
PROBE_ROLE = "partqc_rls_probe_dev"


@pytest.fixture
def conn(clean_db: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(clean_db, autocommit=True, prepare_threshold=None) as connection:
        connection.execute(
            "insert into devices (device_id, api_key_hash) values (%s, %s)", (DEVICE, "b" * 64)
        )
        yield connection


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "inspection_id": uuid.uuid4(),
        "device_id": DEVICE,
        "lot_id": "L-001",
        "inspected_at": datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
        "object_type": "screw",
        "grade": "fair",
        "grade_score": 2.1,
        "type_confidence": 0.97,
        "grade_confidence": 0.66,
        "needs_review": False,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "latency_ms": 120,
        "source": "live",
    }
    row.update(overrides)
    return row


def _insert(conn: psycopg.Connection, **overrides: Any) -> uuid.UUID:
    row = _row(**overrides)
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    conn.execute(f"insert into inspections ({columns}) values ({placeholders})", row)
    return row["inspection_id"]


def _count(conn: psycopg.Connection, table: str = "inspections") -> int:
    return conn.execute(f"select count(*) from {table}").fetchone()[0]


def _constraint_values(conn: psycopg.Connection, name: str) -> set[str]:
    (definition,) = conn.execute(
        "select pg_get_constraintdef(oid) from pg_constraint where conname = %s", (name,)
    ).fetchone()
    return set(re.findall(r"'([^']*)'", definition))


# ---------- structure ----------


def test_column_types(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        """
        select column_name, data_type, is_nullable from information_schema.columns
        where table_schema = 'public' and table_name = 'inspections'
        """
    ).fetchall()
    tz = "timestamp with time zone"
    assert {name: (dtype, nullable) for name, dtype, nullable in rows} == {
        "inspection_id": ("uuid", "NO"),
        "device_id": ("text", "NO"),
        "lot_id": ("text", "NO"),
        "inspected_at": (tz, "NO"),
        "received_at": (tz, "NO"),
        "object_type": ("text", "NO"),
        "grade": ("text", "YES"),
        "grade_score": ("real", "YES"),
        "type_confidence": ("real", "NO"),
        "grade_confidence": ("real", "YES"),
        "needs_review": ("boolean", "NO"),
        "model_version": ("text", "NO"),
        "model_sha256": ("text", "NO"),
        "latency_ms": ("integer", "NO"),
        "source": ("text", "NO"),
        "is_defective": ("boolean", "YES"),
    }


def test_device_columns(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        """
        select column_name, data_type, is_nullable from information_schema.columns
        where table_schema = 'public' and table_name = 'devices' order by ordinal_position
        """
    ).fetchall()
    assert rows == [
        ("device_id", "text", "NO"),
        ("api_key_hash", "text", "NO"),
        ("created_at", "timestamp with time zone", "NO"),
        ("last_seen_at", "timestamp with time zone", "YES"),
    ]


def test_indexes(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        "select indexname, indexdef from pg_indexes where tablename = 'inspections'"
    ).fetchall()
    defs = dict(rows)
    expected = {
        "inspections_inspected_at_idx": "(inspected_at)",
        "inspections_lot_id_idx": "(lot_id)",
        "inspections_source_inspected_at_idx": "(source, inspected_at)",
        "inspections_device_id_idx": "(device_id)",
    }
    for name, columns in expected.items():
        assert name in defs
        assert defs[name].endswith(f"USING btree {columns}")


def test_named_constraints_exist(conn: psycopg.Connection) -> None:
    names = {
        row[0]
        for row in conn.execute(
            "select conname from pg_constraint where conrelid = 'inspections'::regclass"
        )
    }
    assert {
        "inspections_object_type_check",
        "inspections_grade_check",
        "inspections_source_check",
        "inspections_grade_null_iff_unknown",
        "inspections_grade_fields_null_together",
        "inspections_ranges_check",
        "inspections_formats_check",
    } <= names


def test_enum_checks_match_contract(conn: psycopg.Connection) -> None:
    assert _constraint_values(conn, "inspections_object_type_check") == {
        m.value for m in ObjectType
    }
    assert _constraint_values(conn, "inspections_grade_check") == {m.value for m in Grade}
    assert _constraint_values(conn, "inspections_source_check") == {m.value for m in Source}


# ---------- constraints ----------


def test_valid_row_is_accepted(conn: psycopg.Connection) -> None:
    inspection_id = _insert(conn)
    received_at, score, conf = conn.execute(
        "select received_at, grade_score, type_confidence from inspections "
        "where inspection_id = %s",
        (inspection_id,),
    ).fetchone()
    assert received_at is not None
    assert score == pytest.approx(2.1, abs=1e-6)
    assert conf == pytest.approx(0.97, abs=1e-6)


@pytest.mark.parametrize(
    "overrides",
    [
        {"object_type": "bolt"},
        {"grade": "bad"},
        {"source": "test"},
        {"object_type": "unknown"},
        {"grade": None, "grade_score": None, "grade_confidence": None},
        {"grade_score": None},
        {"grade_confidence": None},
        {"object_type": "unknown", "grade": None, "grade_confidence": None},
        {"type_confidence": 1.5},
        {"type_confidence": -0.01},
        {"grade_confidence": 1.01},
        {"grade_score": 4.5},
        {"grade_score": -0.1},
        {"latency_ms": -1},
        {"model_sha256": "a" * 63},
        {"model_sha256": "A" * 64},
        {"model_sha256": "a" * 64 + "\n"},
        {"lot_id": "L 001"},
        {"lot_id": ""},
        {"lot_id": "L" * 41},
    ],
)
def test_check_violations(conn: psycopg.Connection, overrides: dict[str, Any]) -> None:
    with pytest.raises(errors.CheckViolation):
        _insert(conn, **overrides)
    assert _count(conn) == 0


def test_unknown_without_grade_fields_is_accepted(conn: psycopg.Connection) -> None:
    _insert(conn, object_type="unknown", grade=None, grade_score=None, grade_confidence=None)
    assert _count(conn) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"type_confidence": 0.0, "grade_confidence": 0.0, "grade_score": 0.0, "latency_ms": 0},
        {"type_confidence": 1.0, "grade_confidence": 1.0, "grade_score": 4.0},
        {"lot_id": "a" * 40, "model_sha256": "0123456789abcdef" * 4},
        {"lot_id": "Lot_A-9", "object_type": "nut", "source": "simulated"},
    ],
)
def test_inclusive_limits_accepted(conn: psycopg.Connection, overrides: dict[str, Any]) -> None:
    _insert(conn, **overrides)
    assert _count(conn) == 1


def test_not_null_columns(conn: psycopg.Connection) -> None:
    for column in ("device_id", "lot_id", "inspected_at", "needs_review", "model_version"):
        with pytest.raises(errors.NotNullViolation):
            _insert(conn, **{column: None})
    assert _count(conn) == 0


def test_latency_int4_ceiling(conn: psycopg.Connection) -> None:
    inspection_id = _insert(conn, latency_ms=INT4_MAX)
    assert conn.execute(
        "select latency_ms from inspections where inspection_id = %s", (inspection_id,)
    ).fetchone() == (INT4_MAX,)
    with pytest.raises(errors.NumericValueOutOfRange) as info:
        _insert(conn, latency_ms=INT4_MAX + 1)
    assert info.value.sqlstate == "22003"
    assert _count(conn) == 1


# ---------- generated column ----------


def test_is_defective_matches_contract(conn: psycopg.Connection) -> None:
    expected: dict[uuid.UUID, bool] = {}
    for grade in Grade:
        inspection_id = _insert(conn, grade=grade.value)
        expected[inspection_id] = is_defective(grade)
    inspection_id = _insert(
        conn, object_type="unknown", grade=None, grade_score=None, grade_confidence=None
    )
    expected[inspection_id] = is_defective(None)
    rows = dict(conn.execute("select inspection_id, is_defective from inspections").fetchall())
    assert len(rows) == len(Grade) + 1
    assert rows == expected


def test_is_defective_cannot_be_written(conn: psycopg.Connection) -> None:
    with pytest.raises(errors.GeneratedAlways):
        _insert(conn, is_defective=False)
    inspection_id = _insert(conn)
    with pytest.raises(errors.GeneratedAlways):
        conn.execute(
            "update inspections set is_defective = true where inspection_id = %s",
            (inspection_id,),
        )


# ---------- idempotency and foreign keys ----------


def test_duplicate_inspection_id(conn: psycopg.Connection) -> None:
    inspection_id = _insert(conn)
    with pytest.raises(errors.UniqueViolation):
        _insert(conn, inspection_id=inspection_id)
    row = _row(inspection_id=inspection_id)
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    returned = conn.execute(
        f"insert into inspections ({columns}) values ({placeholders}) "
        "on conflict (inspection_id) do nothing returning inspection_id",
        row,
    ).fetchall()
    assert returned == []
    assert _count(conn) == 1


def test_foreign_keys(conn: psycopg.Connection) -> None:
    with pytest.raises(errors.ForeignKeyViolation):
        _insert(conn, device_id="ghost-01")
    _insert(conn)
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute("delete from devices where device_id = %s", (DEVICE,))
    assert _count(conn, "devices") == 1


# ---------- devices ----------


@pytest.mark.parametrize(
    ("device_id", "api_key_hash", "error"),
    [
        ("Edge_01", "c" * 64, errors.CheckViolation),
        ("ed", "c" * 64, errors.CheckViolation),
        ("e" * 33, "c" * 64, errors.CheckViolation),
        ("edge-02", "c" * 10, errors.CheckViolation),
        ("edge-02", "C" * 64, errors.CheckViolation),
        ("edge-02", "b" * 64, errors.UniqueViolation),
        (DEVICE, "c" * 64, errors.UniqueViolation),
        ("edge-02", None, errors.NotNullViolation),
    ],
)
def test_device_rejections(
    conn: psycopg.Connection, device_id: str, api_key_hash: str | None, error: type
) -> None:
    with pytest.raises(error):
        conn.execute(
            "insert into devices (device_id, api_key_hash) values (%s, %s)",
            (device_id, api_key_hash),
        )
    assert _count(conn, "devices") == 1


def test_device_defaults(conn: psycopg.Connection) -> None:
    created_at, last_seen_at = conn.execute(
        "select created_at, last_seen_at from devices where device_id = %s", (DEVICE,)
    ).fetchone()
    assert created_at is not None
    assert created_at.tzinfo is not None
    assert last_seen_at is None


# ---------- RLS ----------


def test_rls_enabled_without_force_and_without_policies(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        """
        select relname, relrowsecurity, relforcerowsecurity from pg_class
        where oid in ('devices'::regclass, 'inspections'::regclass,
                      'schema_migrations'::regclass)
        order by relname
        """
    ).fetchall()
    assert rows == [
        ("devices", True, False),
        ("inspections", True, False),
        ("schema_migrations", True, False),
    ]
    assert conn.execute(
        "select count(*) from pg_policies "
        "where tablename in ('devices', 'inspections', 'schema_migrations')"
    ).fetchone() == (0,)


def _drop_probe_role(conn: psycopg.Connection) -> None:
    exists = conn.execute("select 1 from pg_roles where rolname = %s", (PROBE_ROLE,)).fetchone()
    if exists:
        conn.execute(f"drop owned by {PROBE_ROLE}")
        conn.execute(f"drop role {PROBE_ROLE}")


@pytest.fixture
def probe_role(conn: psycopg.Connection) -> Iterator[str]:
    _drop_probe_role(conn)  # tolerate a previous interrupted run
    conn.execute(f"create role {PROBE_ROLE} nologin nosuperuser nobypassrls")
    conn.execute(f"grant usage on schema public to {PROBE_ROLE}")
    conn.execute(f"grant select, insert on devices, inspections to {PROBE_ROLE}")
    try:
        yield PROBE_ROLE
    finally:
        _drop_probe_role(conn)


def test_rls_blocks_role_without_policies(conn: psycopg.Connection, probe_role: str) -> None:
    for _ in range(3):
        _insert(conn)
    assert _count(conn) == 3
    with conn.transaction():
        conn.execute(f"set local role {probe_role}")
        assert _count(conn, "inspections") == 0
        assert _count(conn, "devices") == 0
    with pytest.raises(errors.InsufficientPrivilege) as info, conn.transaction():
        conn.execute(f"set local role {probe_role}")
        _insert(conn)
    assert info.value.sqlstate == "42501"
    assert "row-level security" in str(info.value)
    # The owner still reads everything (no FORCE ROW LEVEL SECURITY).
    assert _count(conn) == 3
