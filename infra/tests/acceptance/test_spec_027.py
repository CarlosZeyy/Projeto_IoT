"""Acceptance tests for SPEC-027 section 4.1 (migration ``002_contract_checks.sql``).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test per CA (``test_caNN_*``, CA-01 to CA-05); ``test_extra_*`` tests cover
requirements of SPEC-027 section 4.1 that no CA spells out, plus exploratory edge cases.

Every test here is marked ``db``. Tests that need an empty ``public`` schema use a scratch
database (``<test db name>_acc027``) on the same server, dropped at the end of the module, so the
session-wide ``migrated_db`` fixture is never disturbed. No credential appears as a literal.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pydantic
import pytest
from migrate import MigrationError, apply_migrations, load_migrations, pending_migrations
from psycopg import errors, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

import qc_contracts

pytestmark = [pytest.mark.acceptance, pytest.mark.db]

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "infra" / "migrations"
INIT_SQL = MIGRATIONS_DIR / "001_init.sql"
CHECKS_SQL = MIGRATIONS_DIR / "002_contract_checks.sql"

NEW_CHECKS = {
    "inspections_model_version_check": "model_version",
    "inspections_inspection_id_v4_check": "inspection_id",
    "inspections_inspected_at_range_check": "inspected_at",
    "inspections_received_at_range_check": "received_at",
}
EDGE_HASH = hashlib.sha256(b"edge-01-acc027").hexdigest()
HEX = "0123456789abcdef"
REFUSAL_HEAD = "migration 002: {total} row(s) of inspections violate the new checks"
REFUSAL = (
    "migration 002: {total} row(s) of inspections violate the new checks "
    "(model_version={a}, inspection_id={b}, inspected_at={c}, received_at={d}); "
    "fix or delete them before migrating"
)


# --------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------


def _connect(conninfo: str, *, autocommit: bool = True) -> psycopg.Connection:
    return psycopg.connect(conninfo, autocommit=autocommit, prepare_threshold=None)


def _default_versions() -> list[str]:
    """Versions of the files in ``infra/migrations/`` (computed, never a literal list)."""
    return [m.version for m in load_migrations(MIGRATIONS_DIR)]


def _valid_row(**overrides: Any) -> dict[str, Any]:
    """'Linha válida' of SPEC-003 section 5."""
    row: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L001",
        "inspected_at": datetime.now(UTC),
        "object_type": "screw",
        "grade": "fair",
        "grade_score": 2.1,
        "type_confidence": 0.97,
        "grade_confidence": 0.66,
        "needs_review": False,
        "model_version": "v1.0.0",
        "model_sha256": "a" * 64,
        "latency_ms": 120,
        "source": "live",
    }
    row.update(overrides)
    return row


def _insert(conn: psycopg.Connection, table: str, row: dict[str, Any]) -> None:
    cols = list(row)
    query = sql.SQL("insert into {} ({}) values ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(c) for c in cols),
        sql.SQL(", ").join(sql.Placeholder(c) for c in cols),
    )
    conn.execute(query, row)


def _add_device(conn: psycopg.Connection) -> None:
    _insert(conn, "devices", {"device_id": "edge-01", "api_key_hash": EDGE_HASH})


def _count(conn: psycopg.Connection, table: str) -> int:
    row = conn.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table))).fetchone()
    assert row is not None
    return int(row[0])


def _applied(conn: psycopg.Connection) -> list[tuple[str, str]]:
    return conn.execute(
        "select version, checksum from schema_migrations order by version"
    ).fetchall()


def _check_constraints(conn: psycopg.Connection) -> dict[str, tuple[str, str, bool]]:
    """``conname -> (contype, pg_get_constraintdef, convalidated)`` of ``inspections``."""
    rows = conn.execute(
        """
        select conname, contype::text, pg_get_constraintdef(oid), convalidated
        from pg_constraint where conrelid = 'public.inspections'::regclass
        """
    ).fetchall()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def _constraint_set(conn: psycopg.Connection) -> set[tuple[str, str]]:
    rows = conn.execute(
        "select conname, pg_get_constraintdef(oid) from pg_constraint "
        "where conrelid = 'public.inspections'::regclass"
    ).fetchall()
    return {(r[0], r[1]) for r in rows}


def _schema_snapshot(conn: psycopg.Connection) -> dict[str, list[tuple[Any, ...]]]:
    """Columns, constraints, indexes, RLS flags and policies of the public schema."""
    return {
        "columns": conn.execute(
            """
            select table_name, column_name, data_type, is_nullable, column_default,
                   is_generated, generation_expression
            from information_schema.columns where table_schema = 'public'
            order by table_name, column_name
            """
        ).fetchall(),
        "constraints": conn.execute(
            """
            select c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid)
            from pg_constraint c join pg_namespace n on n.oid = c.connamespace
            where n.nspname = 'public' order by 1, 2
            """
        ).fetchall(),
        "indexes": conn.execute(
            "select tablename, indexname, indexdef from pg_indexes "
            "where schemaname = 'public' order by 1, 2"
        ).fetchall(),
        "rls": conn.execute(
            """
            select c.relname, c.relrowsecurity, c.relforcerowsecurity
            from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relkind = 'r' order by 1
            """
        ).fetchall(),
        "policies": conn.execute(
            "select tablename, policyname from pg_policies where schemaname = 'public' order by 1"
        ).fetchall(),
    }


def _run_file(conninfo: str, path: Path) -> None:
    """Simulates the Supabase SQL Editor: the whole file in one transaction."""
    with _connect(conninfo, autocommit=False) as conn:
        conn.execute(path.read_text(encoding="utf-8"))
        conn.commit()


def _only_init_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "only001"
    directory.mkdir()
    shutil.copy(INIT_SQL, directory / INIT_SQL.name)
    return directory


def _init_and_checks_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "with002"
    directory.mkdir()
    shutil.copy(INIT_SQL, directory / INIT_SQL.name)
    shutil.copy(CHECKS_SQL, directory / CHECKS_SQL.name)
    return directory


# --------------------------------------------------------------------------------------------
# fixtures (scratch database)
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def scratch_conninfo(db_conninfo: str) -> Iterator[str]:
    base = conninfo_to_dict(db_conninfo)["dbname"]
    name = f"{base}_acc027"
    assert "test" in name
    ident = sql.Identifier(name)
    with _connect(db_conninfo) as conn:
        conn.execute(sql.SQL("drop database if exists {} with (force)").format(ident))
        conn.execute(sql.SQL("create database {}").format(ident))
    try:
        yield make_conninfo(db_conninfo, dbname=name)
    finally:
        with _connect(db_conninfo) as conn:
            conn.execute(sql.SQL("drop database if exists {} with (force)").format(ident))


@pytest.fixture
def empty_db(scratch_conninfo: str) -> str:
    with _connect(scratch_conninfo) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
    return scratch_conninfo


@pytest.fixture
def migrated(empty_db: str) -> str:
    """The database of CA-01: every migration of the default directory applied once."""
    assert apply_migrations(empty_db) == _default_versions()
    return empty_db


@pytest.fixture
def db(migrated: str) -> Iterator[psycopg.Connection]:
    with _connect(migrated) as conn:
        _add_device(conn)
        yield conn


@pytest.fixture
def only_001(empty_db: str, tmp_path: Path) -> tuple[str, Path]:
    """CA-05: a database where only ``001`` was applied, and a dir with copies of 001 and 002."""
    assert apply_migrations(empty_db, _only_init_dir(tmp_path)) == ["001"]
    with _connect(empty_db) as conn:
        _add_device(conn)
    return empty_db, _init_and_checks_dir(tmp_path)


# --------------------------------------------------------------------------------------------
# CA-01 .. CA-05
# --------------------------------------------------------------------------------------------


def test_ca01_apply_on_empty_schema(empty_db: str) -> None:
    expected = sorted(p.name[:3] for p in MIGRATIONS_DIR.glob("*.sql"))
    assert expected[:2] == ["001", "002"]

    result = apply_migrations(empty_db)

    assert result == expected
    assert result[:2] == ["001", "002"]
    with _connect(empty_db) as conn:
        rows = dict(_applied(conn))
        constraints = _check_constraints(conn)
    assert sorted(rows) == expected  # one row per version
    assert rows["001"] == hashlib.sha256(INIT_SQL.read_bytes()).hexdigest()
    assert rows["002"] == hashlib.sha256(CHECKS_SQL.read_bytes()).hexdigest()
    for name in NEW_CHECKS:
        assert name in constraints, name
        assert constraints[name][0] == "c", (name, constraints[name])


def test_ca02_idempotent_runner_and_sql_editor(migrated: str) -> None:
    assert apply_migrations(migrated) == []

    with _connect(migrated) as conn:
        before = _constraint_set(conn)
        applied_before = _applied(conn)
    for _ in range(2):
        _run_file(migrated, CHECKS_SQL)
    with _connect(migrated) as conn:
        assert _constraint_set(conn) == before
        assert _applied(conn) == applied_before
    assert {name for name, _ in before} >= set(NEW_CHECKS)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"model_version": "MODEL_X"}, "inspections_model_version_check"),
        ({"model_version": "ab"}, "inspections_model_version_check"),
        ({"model_version": "a" * 41}, "inspections_model_version_check"),
        ({"model_version": "sim-v0\n"}, "inspections_model_version_check"),
        ({"inspection_id": str(uuid.uuid1())}, "inspections_inspection_id_v4_check"),
        (
            {"inspection_id": "00000000-0000-0000-0000-000000000000"},
            "inspections_inspection_id_v4_check",
        ),
        ({"inspected_at": "infinity"}, "inspections_inspected_at_range_check"),
        ({"inspected_at": "-infinity"}, "inspections_inspected_at_range_check"),
        ({"inspected_at": "10000-01-01T00:00:00Z"}, "inspections_inspected_at_range_check"),
        ({"received_at": "infinity"}, "inspections_received_at_range_check"),
    ],
    ids=[
        "mv-upper",
        "mv-2-chars",
        "mv-41-chars",
        "mv-newline",
        "id-uuid1",
        "id-nil",
        "at-infinity",
        "at-minus-infinity",
        "at-year-10000",
        "received-infinity",
    ],
)
def test_ca03_refusals(db: psycopg.Connection, overrides: dict[str, Any], constraint: str) -> None:
    with pytest.raises(errors.CheckViolation) as exc:
        _insert(db, "inspections", _valid_row(**overrides))
    assert exc.value.sqlstate == "23514"
    assert exc.value.diag.constraint_name == constraint
    assert _count(db, "inspections") == 0


@pytest.mark.parametrize("inspected_at", ["0001-01-01T00:00:00Z", "9999-12-31T23:59:59.999999Z"])
def test_ca03_limits_accepted(db: psycopg.Connection, inspected_at: str) -> None:
    row = _valid_row(
        model_version="partqc-mnv3-v1", inspection_id=str(uuid.uuid4()), inspected_at=inspected_at
    )
    _insert(db, "inspections", row)
    assert _count(db, "inspections") == 1


def test_ca04_inspection_id_check_mirrors_pydantic_uuid4(db: psycopg.Connection) -> None:
    adapter = pydantic.TypeAdapter(pydantic.UUID4)
    accepted_by_db: set[tuple[str, str]] = set()
    accepted_by_pydantic: set[tuple[str, str]] = set()
    for v in HEX:
        for w in HEX:
            text = f"12345678-1234-{v}234-{w}234-123456789abc"
            try:
                adapter.validate_python(text)
            except pydantic.ValidationError:
                pass
            else:
                accepted_by_pydantic.add((v, w))
            try:
                _insert(db, "inspections", _valid_row(inspection_id=text))
            except errors.CheckViolation as exc:
                assert exc.diag.constraint_name == "inspections_inspection_id_v4_check", text
            else:
                accepted_by_db.add((v, w))

    assert accepted_by_db == accepted_by_pydantic
    assert accepted_by_pydantic == {("4", w) for w in "89ab"}
    assert _count(db, "inspections") == 4


def test_ca04_model_version_check_mirrors_contract(db: psycopg.Connection) -> None:
    values = ["abc", "a.b", "...", "a" * 40, "a" * 41, "ab", "ABC", "abc\n", "ab c", "ábc", "a_b"]
    outcome: dict[str, tuple[bool, bool]] = {}
    for value in values:
        expected = re.fullmatch(qc_contracts.MODEL_VERSION_PATTERN, value) is not None
        try:
            _insert(db, "inspections", _valid_row(model_version=value))
        except errors.CheckViolation as exc:
            assert exc.diag.constraint_name == "inspections_model_version_check", value
            stored = False
        else:
            stored = True
        outcome[value] = (stored, expected)

    assert all(stored == expected for stored, expected in outcome.values()), outcome
    # Sanity: the list has both accepted and refused values, so the test is not vacuous.
    assert {expected for _, expected in outcome.values()} == {True, False}


def test_ca05_refuses_invalid_rows_with_counts_only(only_001: tuple[str, Path]) -> None:
    conninfo, directory = only_001
    v1 = str(uuid.uuid1())
    with _connect(conninfo) as conn:
        _insert(conn, "inspections", _valid_row(model_version="MODEL_X"))
        _insert(conn, "inspections", _valid_row(inspection_id=v1))
        _insert(conn, "inspections", _valid_row(inspected_at="infinity"))

    with pytest.raises(MigrationError) as exc:
        apply_migrations(conninfo, directory)

    message = str(exc.value)
    assert REFUSAL_HEAD.format(total=3) in message
    assert "model_version=1" in message
    assert "MODEL_X" not in message
    assert v1 not in message
    with _connect(conninfo) as conn:
        assert [v for v, _ in _applied(conn)] == ["001"]
        assert not set(_check_constraints(conn)) & set(NEW_CHECKS)
        assert _count(conn, "inspections") == 3

        conn.execute("delete from inspections")
    assert apply_migrations(conninfo, directory) == ["002"]


# --------------------------------------------------------------------------------------------
# extras: section 4.1 requirements without a CA, and exploratory cases
# --------------------------------------------------------------------------------------------


def test_extra_refusal_message_is_the_exact_format(only_001: tuple[str, Path]) -> None:
    conninfo, directory = only_001
    with _connect(conninfo) as conn:
        _insert(conn, "inspections", _valid_row(model_version="MODEL_X"))
        _insert(conn, "inspections", _valid_row(inspection_id=str(uuid.uuid1())))
        _insert(conn, "inspections", _valid_row(inspected_at="infinity"))

    with pytest.raises(MigrationError) as exc:
        apply_migrations(conninfo, directory)
    assert REFUSAL.format(total=3, a=1, b=1, c=1, d=0) in str(exc.value)


def test_extra_row_violating_two_rules_counts_once_in_the_total(
    only_001: tuple[str, Path],
) -> None:
    """Total = rows that violate some rule; each per-rule count counts that rule."""
    conninfo, directory = only_001
    with _connect(conninfo) as conn:
        _insert(
            conn,
            "inspections",
            _valid_row(model_version="BAD", inspected_at="-infinity", received_at="infinity"),
        )
        _insert(conn, "inspections", _valid_row(inspection_id=str(uuid.uuid1())))
        _insert(conn, "inspections", _valid_row())  # valid row: not counted

    with pytest.raises(MigrationError) as exc:
        apply_migrations(conninfo, directory)
    assert REFUSAL.format(total=2, a=1, b=1, c=1, d=1) in str(exc.value)
    with _connect(conninfo) as conn:
        assert [v for v, _ in _applied(conn)] == ["001"]
        assert _count(conn, "inspections") == 3


def test_extra_refusal_message_has_no_row_values(only_001: tuple[str, Path]) -> None:
    conninfo, directory = only_001
    marker = "mk-" + uuid.uuid4().hex[:12]
    v1 = str(uuid.uuid1())
    with _connect(conninfo) as conn:
        _insert(conn, "inspections", _valid_row(model_version=marker.upper(), lot_id=marker))
        _insert(conn, "inspections", _valid_row(inspection_id=v1, lot_id=marker))
    with pytest.raises(MigrationError) as exc:
        apply_migrations(conninfo, directory)
    text = repr(exc.value) + str(exc.value) + repr(exc.value.__cause__)
    assert marker not in text.lower()
    assert v1 not in text
    assert "Failing row" not in text
    assert "edge-01" not in text


def test_extra_valid_rows_are_kept_when_migrating(only_001: tuple[str, Path]) -> None:
    conninfo, directory = only_001
    with _connect(conninfo) as conn:
        for _ in range(3):
            _insert(conn, "inspections", _valid_row(model_version="partqc-mnv3-v1"))
    assert apply_migrations(conninfo, directory) == ["002"]
    with _connect(conninfo) as conn:
        assert _count(conn, "inspections") == 3
        assert set(NEW_CHECKS) <= set(_check_constraints(conn))


def test_extra_sql_editor_run_over_invalid_rows_leaves_nothing_half_done(
    only_001: tuple[str, Path],
) -> None:
    conninfo, _ = only_001
    with _connect(conninfo) as conn:
        _insert(conn, "inspections", _valid_row(received_at="infinity"))
        before = _schema_snapshot(conn)

    # Both in an explicit transaction (SQL Editor) and in autocommit (implicit transaction).
    with pytest.raises(psycopg.errors.RaiseException) as exc:
        _run_file(conninfo, CHECKS_SQL)
    assert REFUSAL.format(total=1, a=0, b=0, c=0, d=1) in str(exc.value)
    with _connect(conninfo) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute(CHECKS_SQL.read_text(encoding="utf-8"))

    with _connect(conninfo) as conn:
        assert _schema_snapshot(conn) == before
        assert [v for v, _ in _applied(conn)] == ["001"]


def test_extra_file_has_no_transaction_control() -> None:
    text = CHECKS_SQL.read_text(encoding="utf-8")
    code = "\n".join(line.split("--", 1)[0] for line in text.splitlines()).lower()
    assert not re.search(r"\b(begin|commit|rollback)\s*;", code)
    assert "start transaction" not in code


def test_extra_no_other_schema_change(empty_db: str, tmp_path: Path) -> None:
    """4.1.3: columns, indexes, RLS and the 001 constraints stay the same."""
    apply_migrations(empty_db, _only_init_dir(tmp_path))
    with _connect(empty_db) as conn:
        before = _schema_snapshot(conn)
    assert apply_migrations(empty_db, _init_and_checks_dir(tmp_path)) == ["002"]
    with _connect(empty_db) as conn:
        after = _schema_snapshot(conn)

    for key in ("columns", "indexes", "rls", "policies"):
        assert after[key] == before[key], key
    added = set(after["constraints"]) - set(before["constraints"])
    assert set(before["constraints"]) <= set(after["constraints"])
    assert {(t, n) for t, n, _ in added} == {("inspections", n) for n in NEW_CHECKS}


def test_extra_constraints_are_validated_and_reference_their_column(migrated: str) -> None:
    with _connect(migrated) as conn:
        constraints = _check_constraints(conn)
    for name, column in NEW_CHECKS.items():
        contype, definition, validated = constraints[name]
        assert contype == "c"
        assert validated is True, f"{name} is NOT VALID"
        assert column in definition, (name, definition)


def test_extra_existing_constraint_with_the_same_name_is_kept(
    only_001: tuple[str, Path],
) -> None:
    """4.1.2: each constraint is created only if no constraint with that name exists."""
    conninfo, directory = only_001
    with _connect(conninfo) as conn:
        conn.execute(
            "alter table inspections add constraint inspections_model_version_check "
            "check (length(model_version) > 0)"
        )
    assert apply_migrations(conninfo, directory) == ["002"]
    with _connect(conninfo) as conn:
        defs = _check_constraints(conn)
        assert "length(model_version)" in defs["inspections_model_version_check"][1]
        assert set(NEW_CHECKS) <= set(defs)


def test_extra_manual_001_and_002_then_runner(empty_db: str) -> None:
    _run_file(empty_db, INIT_SQL)
    _run_file(empty_db, CHECKS_SQL)
    assert apply_migrations(empty_db) == _default_versions()
    assert pending_migrations(empty_db) == []
    with _connect(empty_db) as conn:
        assert set(NEW_CHECKS) <= set(_check_constraints(conn))


def test_extra_pending_after_only_001(only_001: tuple[str, Path]) -> None:
    conninfo, directory = only_001
    assert pending_migrations(conninfo, directory) == ["002"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"inspected_at": "0001-01-01T00:00:00Z"},
        {"inspected_at": "9999-12-31T23:59:59.999999Z"},
        {"received_at": "0001-01-01T00:00:00Z"},
        {"received_at": "9999-12-31T23:59:59.999999Z"},
    ],
)
def test_extra_limits_hold_in_a_non_utc_session(migrated: str, overrides: dict[str, Any]) -> None:
    """The check compares instants, so the session TimeZone does not change the outcome."""
    with _connect(migrated) as conn:
        _add_device(conn)
        conn.execute("set time zone 'America/Sao_Paulo'")
        _insert(conn, "inspections", _valid_row(**overrides))
        assert _count(conn, "inspections") == 1


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"received_at": "-infinity"}, "inspections_received_at_range_check"),
        ({"received_at": "10000-01-01T00:00:00Z"}, "inspections_received_at_range_check"),
        (
            {"inspected_at": "0001-12-31T23:59:59.999999Z BC"},
            "inspections_inspected_at_range_check",
        ),
        # 0001-01-01T00:00:00+01:00 is 1 BC in UTC: just below the lower limit.
        ({"inspected_at": "0001-01-01T00:00:00+01:00"}, "inspections_inspected_at_range_check"),
        ({"inspected_at": "10000-01-01T00:00:00-01:00"}, "inspections_inspected_at_range_check"),
        # 9999-12-31T23:59:59.999999-03:00 is 10000-01-01T02:59:59.999999Z: out of the range.
        (
            {"inspected_at": "9999-12-31T23:59:59.999999-03:00"},
            "inspections_inspected_at_range_check",
        ),
        ({"model_version": "a" * 39 + "\t"}, "inspections_model_version_check"),
        ({"model_version": "abc "}, "inspections_model_version_check"),
        ({"model_version": ""}, "inspections_model_version_check"),
        (
            {"inspection_id": "ffffffff-ffff-ffff-ffff-ffffffffffff"},
            "inspections_inspection_id_v4_check",
        ),
        (
            {"inspection_id": "12345678-1234-4234-c234-123456789abc"},
            "inspections_inspection_id_v4_check",
        ),
    ],
)
def test_extra_more_refusals(
    db: psycopg.Connection, overrides: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(errors.CheckViolation) as exc:
        _insert(db, "inspections", _valid_row(**overrides))
    assert exc.value.diag.constraint_name == constraint


@pytest.mark.parametrize(
    "overrides",
    [
        {"inspection_id": "12345678-1234-4234-A234-123456789ABC"},  # uppercase input
        {"inspection_id": "{12345678-1234-4234-8234-123456789abc}"},  # braces input
        {"inspected_at": "0001-01-01T03:00:00+03:00"},  # 0001-01-01T00:00Z: the lower limit
        {"model_version": "a" * 40},
        {"model_version": "0.0"},
    ],
    ids=["id-uppercase", "id-braces", "at-lower-limit-with-offset", "mv-40", "mv-3"],
)
def test_extra_exploratory_inputs(db: psycopg.Connection, overrides: dict[str, Any]) -> None:
    """Exploratory: edge inputs that the contract accepts are accepted by the database."""
    _insert(db, "inspections", _valid_row(**overrides))
    assert _count(db, "inspections") == 1
