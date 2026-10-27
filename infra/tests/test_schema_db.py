"""Schema of infra/migrations against the test PostgreSQL. All tests are marked `db`.

001_init.sql: SPEC-003 §4.1. 002_contract_checks.sql (checks that mirror the contract): SPEC-027
§4.1. 003_tool_object_types.sql (hand tools and the grade groups of ADR-021): SPEC-016 §4.2.
004_device_heartbeat.sql (last heartbeat of each device): SPEC-018 §4.2.
006_power_tool_object_types.sql (power tools, never graded): SPEC-021 §3.1. These at the end of
this file.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pydantic
import pytest
from psycopg import errors

from qc_contracts import (
    APP_VERSION_PATTERN,
    MAX_HEARTBEAT_COUNT,
    MODEL_VERSION_PATTERN,
    SHA256_PATTERN,
    Grade,
    InspectionCreate,
    ObjectType,
    Source,
    is_defective,
)

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
        ("last_heartbeat_at", "timestamp with time zone", "YES"),
        ("hb_sent_at", "timestamp with time zone", "YES"),
        ("hb_model_version", "text", "YES"),
        ("hb_model_sha256", "text", "YES"),
        ("hb_app_version", "text", "YES"),
        ("hb_uptime_s", "integer", "YES"),
        ("hb_outbox_pending", "integer", "YES"),
        ("hb_outbox_dead", "integer", "YES"),
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


# ---------- 002_contract_checks (SPEC-027 §4.1) ----------

UUID4_ADAPTER = pydantic.TypeAdapter(pydantic.UUID4)
HEX = "0123456789abcdef"


def _inserted(conn: psycopg.Connection, **overrides: Any) -> bool:
    """True when the insert works; False on ``CheckViolation`` (SQLSTATE 23514)."""
    try:
        with conn.transaction():
            _insert(conn, **overrides)
    except errors.CheckViolation as exc:
        assert exc.sqlstate == "23514"
        return False
    return True


def _pydantic_uuid4_accepts(text: str) -> bool:
    try:
        UUID4_ADAPTER.validate_python(text)
    except pydantic.ValidationError:
        return False
    return True


def test_contract_check_constraints_exist(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        "select conname, contype from pg_constraint where conrelid = 'inspections'::regclass"
    ).fetchall()
    types = dict(rows)
    for name in (
        "inspections_model_version_check",
        "inspections_inspection_id_v4_check",
        "inspections_inspected_at_range_check",
        "inspections_received_at_range_check",
    ):
        assert types[name] == "c"


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_version": "MODEL_X"},
        {"model_version": "ab"},
        {"model_version": "a" * 41},
        {"model_version": "sim-v0\n"},
        {"inspection_id": str(uuid.uuid1())},
        {"inspection_id": "00000000-0000-0000-0000-000000000000"},
        {"inspected_at": "infinity"},
        {"inspected_at": "-infinity"},
        {"inspected_at": "10000-01-01T00:00:00Z"},
        {"received_at": "infinity"},
        {"received_at": "-infinity"},
        {"received_at": "10000-01-01T00:00:00Z"},
    ],
    ids=repr,
)
def test_contract_checks_refuse(conn: psycopg.Connection, overrides: dict[str, Any]) -> None:
    assert not _inserted(conn, **overrides)
    assert _count(conn) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_version": "partqc-mnv3-v1", "inspection_id": str(uuid.uuid4())},
        {"inspected_at": "0001-01-01T00:00:00Z"},
        {"inspected_at": "9999-12-31T23:59:59.999999Z"},
        {"received_at": "0001-01-01T00:00:00Z"},
        {"received_at": "9999-12-31T23:59:59.999999Z"},
        {"inspection_id": "FFFFFFFF-FFFF-4FFF-BFFF-FFFFFFFFFFFF"},
    ],
    ids=repr,
)
def test_contract_checks_accept_limits(conn: psycopg.Connection, overrides: dict[str, Any]) -> None:
    assert _inserted(conn, **overrides)
    assert _count(conn) == 1


def test_inspection_id_check_mirrors_pydantic_uuid4(conn: psycopg.Connection) -> None:
    accepted: set[str] = set()
    for version in HEX:
        for variant in HEX:
            text = f"12345678-1234-{version}234-{variant}234-123456789abc"
            database = _inserted(conn, inspection_id=text)
            assert database == _pydantic_uuid4_accepts(text), text
            if database:
                accepted.add(version + variant)
    assert accepted == {"48", "49", "4a", "4b"}


@pytest.mark.parametrize(
    "value",
    ["abc", "a.b", "...", "a" * 40, "a" * 41, "ab", "ABC", "abc\n", "ab c", "ábc", "a_b"],
    ids=repr,
)
def test_model_version_check_mirrors_contract(conn: psycopg.Connection, value: str) -> None:
    expected = re.fullmatch(MODEL_VERSION_PATTERN, value) is not None
    assert _inserted(conn, model_version=value) == expected


# ---------- 003_tool_object_types (SPEC-016 §4.2) ----------

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
TOOLS_SQL = MIGRATIONS_DIR / "003_tool_object_types.sql"
POWER_TOOLS_SQL = MIGRATIONS_DIR / "006_power_tool_object_types.sql"
HAND_TOOLS = (
    "pliers",
    "adjustable_wrench",
    "allen_key",
    "flat_screwdriver",
    "phillips_screwdriver",
)
POWER_TOOLS = ("angle_grinder", "saw", "drill", "cordless_screwdriver")


@pytest.fixture
def rerun_003(conn: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """Connection for tests that run 003 again on the shared database.

    003 replaces both checks with its 8-value version, so the latest migration that replaces
    them (006) runs again at the end: the session keeps the checks of the contract 0.6.0.
    """
    try:
        yield conn
    finally:
        conn.execute(POWER_TOOLS_SQL.read_text(encoding="utf-8"))


def _contract_accepts(object_type: str, grade: str | None) -> bool:
    row = _row(object_type=object_type, grade=grade)
    if grade is None:
        row |= {"grade_score": None, "grade_confidence": None}
    payload = {
        key: (str(value) if isinstance(value, uuid.UUID) else value) for key, value in row.items()
    }
    payload["inspected_at"] = datetime.now(UTC).isoformat()
    try:
        InspectionCreate.model_validate(payload)
    except pydantic.ValidationError:
        return False
    return True


def _database_accepts(conn: psycopg.Connection, object_type: str, grade: str | None) -> bool:
    overrides: dict[str, Any] = {"object_type": object_type, "grade": grade}
    if grade is None:
        overrides |= {"grade_score": None, "grade_confidence": None}
    return _inserted(conn, **overrides)


@pytest.mark.parametrize("object_type", [member.value for member in ObjectType])
@pytest.mark.parametrize("grade", [None, *(member.value for member in Grade)])
def test_grade_groups_check_mirrors_the_contract(
    conn: psycopg.Connection, object_type: str, grade: str | None
) -> None:
    assert _database_accepts(conn, object_type, grade) == _contract_accepts(object_type, grade)


def test_every_tool_is_accepted_with_and_without_grade(conn: psycopg.Connection) -> None:
    tools = HAND_TOOLS
    for tool in tools:
        assert _database_accepts(conn, tool, None)
        assert _database_accepts(conn, tool, "poor")
    assert _count(conn) == 2 * len(tools)
    rows = conn.execute(
        "select grade, is_defective from inspections order by grade nulls first"
    ).fetchall()
    assert rows == [(None, False)] * len(tools) + [("poor", True)] * len(tools)


@pytest.mark.parametrize(
    "object_type", ["hammer", "Pliers", "pliers ", "Drill", "drill ", "grinder", "other"]
)
def test_values_outside_the_contract_are_refused(
    conn: psycopg.Connection, object_type: str
) -> None:
    with pytest.raises(errors.CheckViolation) as info:
        _insert(conn, object_type=object_type, grade=None, grade_score=None, grade_confidence=None)
    assert info.value.sqlstate == "23514"
    assert info.value.diag.constraint_name == "inspections_object_type_check"
    assert _count(conn) == 0


@pytest.mark.parametrize("grade", [None, "fair"])
def test_value_outside_the_enum_is_refused_only_by_the_enum_check(
    conn: psycopg.Connection, grade: str | None
) -> None:
    overrides: dict[str, Any] = {"object_type": "hammer", "grade": grade}
    if grade is None:
        overrides |= {"grade_score": None, "grade_confidence": None}
    with pytest.raises(errors.CheckViolation) as info:
        _insert(conn, **overrides)
    assert info.value.diag.constraint_name == "inspections_object_type_check"


SPEC_EXPRESSION = """
    (object_type in ('screw', 'nut') and grade is not null)
    or (
        object_type in ('unknown', 'angle_grinder', 'saw', 'drill', 'cordless_screwdriver')
        and grade is null
    )
    or object_type in (
        'pliers', 'adjustable_wrench', 'allen_key', 'flat_screwdriver', 'phillips_screwdriver'
    )
"""


def test_grade_check_equals_the_spec_expression_on_the_enum(conn: psycopg.Connection) -> None:
    """For the 12 x 6 pairs the enum check admits, the stored check is the expression of the
    SPEC-016 section 4.2 with the power tools in the grade-forbidden branch (SPEC-021)."""
    (definition,) = conn.execute(
        "select pg_get_constraintdef(oid) from pg_constraint "
        "where conname = 'inspections_grade_null_iff_unknown'"
    ).fetchone()
    stored = definition.removeprefix("CHECK ")
    pairs = [(t.value, g) for t in ObjectType for g in [None, *(m.value for m in Grade)]]
    rows = conn.execute(
        f"select object_type, grade, ({stored}) as stored, ({SPEC_EXPRESSION}) as spec "
        "from (values "
        + ", ".join("(%s::text, %s::text)" for _ in pairs)
        + ") as pairs (object_type, grade)",
        [value for pair in pairs for value in pair],
    ).fetchall()
    assert len(rows) == 72
    for object_type, grade, stored_value, spec_value in rows:
        assert stored_value is spec_value, (object_type, grade)


def test_grade_groups_check_names(conn: psycopg.Connection) -> None:
    with pytest.raises(errors.CheckViolation) as info:
        _insert(conn, object_type="nut", grade=None, grade_score=None, grade_confidence=None)
    assert info.value.diag.constraint_name == "inspections_grade_null_iff_unknown"
    with pytest.raises(errors.CheckViolation) as info:
        _insert(conn, object_type="unknown", grade="good")
    assert info.value.diag.constraint_name == "inspections_grade_null_iff_unknown"


def test_tool_migration_runs_again_without_error(rerun_003: psycopg.Connection) -> None:
    conn = rerun_003
    _insert(conn, object_type="pliers", grade=None, grade_score=None, grade_confidence=None)
    sql_text = TOOLS_SQL.read_text(encoding="utf-8")
    conn.execute(sql_text)
    conn.execute(sql_text)
    assert _constraint_values(conn, "inspections_object_type_check") == {
        member.value for member in ObjectType
    } - set(POWER_TOOLS)
    names = [
        row[0]
        for row in conn.execute(
            "select conname from pg_constraint where conrelid = 'inspections'::regclass "
            "and conname in ('inspections_object_type_check', "
            "'inspections_grade_null_iff_unknown')"
        )
    ]
    assert sorted(names) == ["inspections_grade_null_iff_unknown", "inspections_object_type_check"]
    assert _count(conn) == 1
    assert not _database_accepts(conn, "screw", None)


def test_tool_migration_keeps_mvp_rows_valid(rerun_003: psycopg.Connection) -> None:
    """Rows valid under 001/002 (screw, nut with grade; unknown without) survive a re-run."""
    conn = rerun_003
    _insert(conn)
    _insert(conn, object_type="nut", grade="unusable")
    _insert(conn, object_type="unknown", grade=None, grade_score=None, grade_confidence=None)
    conn.execute(TOOLS_SQL.read_text(encoding="utf-8"))
    assert _count(conn) == 3


# ---------- 004_device_heartbeat (SPEC-018 §4.2) ----------

HEARTBEAT_SQL = MIGRATIONS_DIR / "004_device_heartbeat.sql"


def _heartbeat_values(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "hb_sent_at": datetime(2026, 10, 24, 12, 0, tzinfo=UTC),
        "hb_model_version": "partqc-mnv3-v1",
        "hb_model_sha256": SHA,
        "hb_app_version": "0.0.0",
        "hb_uptime_s": 10,
        "hb_outbox_pending": 0,
        "hb_outbox_dead": 0,
    }
    values.update(overrides)
    return values


def _heartbeat_stored(conn: psycopg.Connection, **overrides: Any) -> bool:
    """True when the heartbeat update works; False on ``CheckViolation`` (SQLSTATE 23514)."""
    values = _heartbeat_values(**overrides)
    assignments = ", ".join(f"{name} = %({name})s" for name in values)
    try:
        with conn.transaction():
            conn.execute(
                f"update devices set last_heartbeat_at = now(), {assignments} "
                "where device_id = %(device_id)s",
                {**values, "device_id": DEVICE},
            )
    except errors.CheckViolation as exc:
        assert exc.sqlstate == "23514"
        return False
    return True


def test_new_device_has_null_heartbeat_columns(conn: psycopg.Connection) -> None:
    row = conn.execute(
        "select last_heartbeat_at, hb_sent_at, hb_model_version, hb_model_sha256, hb_app_version,"
        " hb_uptime_s, hb_outbox_pending, hb_outbox_dead from devices where device_id = %s",
        (DEVICE,),
    ).fetchone()
    assert row == (None,) * 8


def test_valid_heartbeat_is_stored(conn: psycopg.Connection) -> None:
    assert _heartbeat_stored(conn)
    assert _heartbeat_stored(conn, hb_model_version=None, hb_model_sha256=None)
    assert _heartbeat_stored(conn, hb_uptime_s=MAX_HEARTBEAT_COUNT, hb_outbox_dead=0)


@pytest.mark.parametrize("column", ["hb_uptime_s", "hb_outbox_pending", "hb_outbox_dead"])
def test_negative_counters_are_refused(conn: psycopg.Connection, column: str) -> None:
    assert not _heartbeat_stored(conn, **{column: -1})
    assert _heartbeat_stored(conn, **{column: 0})


@pytest.mark.parametrize(
    "overrides",
    [
        {"hb_model_version": "partqc-mnv3-v1", "hb_model_sha256": None},
        {"hb_model_version": None, "hb_model_sha256": SHA},
    ],
)
def test_model_pair_is_null_together(conn: psycopg.Connection, overrides: dict[str, Any]) -> None:
    with pytest.raises(errors.CheckViolation) as info, conn.transaction():
        values = _heartbeat_values(**overrides)
        conn.execute(
            "update devices set hb_model_version = %(hb_model_version)s, "
            "hb_model_sha256 = %(hb_model_sha256)s where device_id = %(device_id)s",
            {**values, "device_id": DEVICE},
        )
    assert info.value.sqlstate == "23514"
    assert info.value.diag.constraint_name == "devices_hb_model_pair_check"


@pytest.mark.parametrize(
    "value", ["partqc-mnv3-v1", "abc", "a" * 40, "ab", "a" * 41, "Partqc", "x_y", "abc\n"]
)
def test_hb_model_version_check_mirrors_contract(conn: psycopg.Connection, value: str) -> None:
    expected = re.fullmatch(MODEL_VERSION_PATTERN, value) is not None
    assert _heartbeat_stored(conn, hb_model_version=value) == expected


@pytest.mark.parametrize("value", [SHA, "0" * 64, "A" * 64, "a" * 63, "a" * 65, SHA + "\n"])
def test_hb_model_sha256_check_mirrors_contract(conn: psycopg.Connection, value: str) -> None:
    expected = re.fullmatch(SHA256_PATTERN, value) is not None
    assert _heartbeat_stored(conn, hb_model_sha256=value) == expected


@pytest.mark.parametrize(
    "value", ["0.0.0", "1.2.3+local", "v2-rc.1", "A" * 40, "", "A" * 41, "1 0", "1_0", "1.0\n"]
)
def test_hb_app_version_check_mirrors_contract(conn: psycopg.Connection, value: str) -> None:
    expected = re.fullmatch(APP_VERSION_PATTERN, value) is not None
    assert _heartbeat_stored(conn, hb_app_version=value) == expected


def test_heartbeat_migration_runs_again_without_error(conn: psycopg.Connection) -> None:
    assert _heartbeat_stored(conn)
    sql_text = HEARTBEAT_SQL.read_text(encoding="utf-8")
    before = conn.execute(
        "select conname, pg_get_constraintdef(oid) from pg_constraint "
        "where conrelid = 'devices'::regclass order by 1"
    ).fetchall()
    conn.execute(sql_text)
    conn.execute(sql_text)
    after = conn.execute(
        "select conname, pg_get_constraintdef(oid) from pg_constraint "
        "where conrelid = 'devices'::regclass order by 1"
    ).fetchall()
    assert after == before
    assert {name for name, _ in after} >= {
        "devices_hb_model_version_check",
        "devices_hb_model_sha256_check",
        "devices_hb_app_version_check",
        "devices_hb_uptime_s_check",
        "devices_hb_outbox_pending_check",
        "devices_hb_outbox_dead_check",
        "devices_hb_model_pair_check",
    }
    assert conn.execute(
        "select hb_uptime_s from devices where device_id = %s", (DEVICE,)
    ).fetchone() == (10,)


# ---------- 006_power_tool_object_types (SPEC-021 §3.1) ----------


def test_power_tool_migration_is_the_latest_grade_check_migration() -> None:
    """006 is the last file that replaces the object_type and grade checks (``rerun_003``)."""
    replacing = [
        path.name
        for path in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql"))
        if "inspections_grade_null_iff_unknown" in path.read_text(encoding="utf-8")
    ]
    assert replacing[-1] == POWER_TOOLS_SQL.name
    assert POWER_TOOLS_SQL.is_file()


@pytest.mark.parametrize("object_type", POWER_TOOLS)
def test_power_tool_is_accepted_only_without_grade(
    conn: psycopg.Connection, object_type: str
) -> None:
    assert _database_accepts(conn, object_type, None)
    for grade in Grade:
        with pytest.raises(errors.CheckViolation) as info:
            _insert(conn, object_type=object_type, grade=grade.value)
        assert info.value.sqlstate == "23514"
        assert info.value.diag.constraint_name == "inspections_grade_null_iff_unknown"
    assert _count(conn) == 1
    row = conn.execute("select grade, is_defective from inspections").fetchone()
    assert row == (None, False)


def test_power_tool_check_values(conn: psycopg.Connection) -> None:
    values = _constraint_values(conn, "inspections_object_type_check")
    assert values == {member.value for member in ObjectType}
    assert len(values) == 12
    assert set(POWER_TOOLS) <= _constraint_values(conn, "inspections_grade_null_iff_unknown")
    assert not set(HAND_TOOLS) & _constraint_values(conn, "inspections_grade_null_iff_unknown")


def test_power_tool_migration_runs_again_without_error(conn: psycopg.Connection) -> None:
    _insert(conn, object_type="drill", grade=None, grade_score=None, grade_confidence=None)
    _insert(conn, object_type="pliers", grade="poor")
    query = (
        "select conname, pg_get_constraintdef(oid) from pg_constraint "
        "where conrelid = 'inspections'::regclass order by 1"
    )
    before = conn.execute(query).fetchall()
    sql_text = POWER_TOOLS_SQL.read_text(encoding="utf-8")
    conn.execute(sql_text)
    conn.execute(sql_text)
    assert conn.execute(query).fetchall() == before
    assert _count(conn) == 2
    assert not _database_accepts(conn, "drill", "good")
    assert not _database_accepts(conn, "screw", None)


def test_power_tool_migration_keeps_older_rows_valid(conn: psycopg.Connection) -> None:
    """Every row valid under 001 to 005 (MVP types and hand tools) survives the migration."""
    _insert(conn)
    _insert(conn, object_type="nut", grade="unusable")
    _insert(conn, object_type="unknown", grade=None, grade_score=None, grade_confidence=None)
    for tool in HAND_TOOLS:
        _insert(conn, object_type=tool, grade=None, grade_score=None, grade_confidence=None)
        _insert(conn, object_type=tool, grade="fair")
    conn.execute(POWER_TOOLS_SQL.read_text(encoding="utf-8"))
    assert _count(conn) == 3 + 2 * len(HAND_TOOLS)
