"""Acceptance tests for SPEC-003 (Supabase schema, migrations and RLS).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test per CA (``test_caNN_*``); ``test_extra_*`` tests cover requirements of
SPEC-003 sections 4.1 to 4.4 that no CA spells out, plus exploratory edge cases.

Every test here is marked ``db`` and runs against the PostgreSQL 16 test server in
``TEST_DATABASE_URL``. Tests that need an empty ``public`` schema use a scratch database
(``<test db name>_acc003``) created on the same server and dropped at the end of the module, so
the session-wide ``migrated_db`` fixture is never disturbed.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import traceback
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from migrate import apply_migrations, pending_migrations
from psycopg import errors, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

import qc_contracts
from qc_contracts import Grade, ObjectType, Source

pytestmark = [pytest.mark.acceptance, pytest.mark.db]

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "infra" / "migrations"
INIT_SQL = MIGRATIONS_DIR / "001_init.sql"
MIGRATE_SCRIPT = REPO_ROOT / "infra" / "migrate.py"
PROBE_FILE = Path(__file__).resolve().parent / "ca22_guard_probe.py"

GUARD_MESSAGE = "refusing to use a database whose name does not contain 'test'"
SECRET = "s3cr3t-pw"
RLS_ROLE = "partqc_rls_probe"
EDGE_HASH = hashlib.sha256(b"edge-01-key").hexdigest()


# --------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------


def _connect(conninfo: str, *, autocommit: bool = True) -> psycopg.Connection:
    return psycopg.connect(conninfo, autocommit=autocommit, prepare_threshold=None)


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


def _insert_sql(table: str, row: dict[str, Any], suffix: str = "") -> sql.Composed:
    cols = list(row)
    return sql.SQL("insert into {} ({}) values ({}){}").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(c) for c in cols),
        sql.SQL(", ").join(sql.Placeholder(c) for c in cols),
        sql.SQL(suffix),
    )


def _insert(conn: psycopg.Connection, table: str, row: dict[str, Any]) -> None:
    conn.execute(_insert_sql(table, row), row)


def _add_device(conn: psycopg.Connection, device_id: str = "edge-01", key_hash: str = EDGE_HASH):
    _insert(conn, "devices", {"device_id": device_id, "api_key_hash": key_hash})


def _count(conn: psycopg.Connection, table: str) -> int:
    row = conn.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table))).fetchone()
    assert row is not None
    return int(row[0])


def _table_exists(conn: psycopg.Connection, name: str) -> bool:
    row = conn.execute("select to_regclass(%s) is not null", (f"public.{name}",)).fetchone()
    assert row is not None
    return bool(row[0])


def _applied_versions(conn: psycopg.Connection) -> list[str]:
    if not _table_exists(conn, "schema_migrations"):
        return []
    return [r[0] for r in conn.execute("select version from schema_migrations order by version")]


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


def _run_cli(*args: str, env_extra: dict[str, str] | None = None, drop: tuple[str, ...] = ()):
    env = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", *drop}}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _drop_probe_role(conn: psycopg.Connection) -> None:
    exists = conn.execute("select 1 from pg_roles where rolname = %s", (RLS_ROLE,)).fetchone()
    if exists:
        conn.execute(sql.SQL("drop owned by {}").format(sql.Identifier(RLS_ROLE)))
        conn.execute(sql.SQL("drop role {}").format(sql.Identifier(RLS_ROLE)))


class _Listener:
    """Local TCP listener that counts accepted connections (CA-22: 'no command reaches the DB')."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.accepted = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self.accepted += 1
            client.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.sock.close()


# --------------------------------------------------------------------------------------------
# fixtures (scratch database for tests that need an empty public schema)
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def scratch_conninfo(db_conninfo: str) -> Iterator[str]:
    base = conninfo_to_dict(db_conninfo)["dbname"]
    name = f"{base}_acc003"
    assert "test" in name
    ident = sql.Identifier(name)
    with _connect(db_conninfo) as conn:
        conn.execute(sql.SQL("drop database if exists {} with (force)").format(ident))
        conn.execute(sql.SQL("create database {}").format(ident))
    yield make_conninfo(db_conninfo, dbname=name)
    with _connect(db_conninfo) as conn:
        conn.execute(sql.SQL("drop database if exists {} with (force)").format(ident))


@pytest.fixture
def empty_db(scratch_conninfo: str) -> str:
    """Scratch database with an empty ``public`` schema."""
    with _connect(scratch_conninfo) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
    return scratch_conninfo


@pytest.fixture
def ca01_db(empty_db: str) -> str:
    """The database of CA-01 (migrations applied once to an empty schema)."""
    assert apply_migrations(empty_db) == ["001"]
    return empty_db


@pytest.fixture
def db(clean_db: str) -> Iterator[psycopg.Connection]:
    """Migrated, truncated database with device ``edge-01`` registered."""
    with _connect(clean_db) as conn:
        _add_device(conn)
        yield conn


@pytest.fixture
def rls_probe_role(clean_db: str) -> Iterator[str]:
    with _connect(clean_db) as conn:
        _drop_probe_role(conn)  # leftover from an interrupted run
    yield RLS_ROLE
    with _connect(clean_db) as conn:
        _drop_probe_role(conn)


# --------------------------------------------------------------------------------------------
# CA-01 .. CA-03: runner and idempotent DDL
# --------------------------------------------------------------------------------------------


def test_ca01_apply_on_empty_schema(empty_db: str) -> None:
    with _connect(empty_db) as conn:
        assert _table_exists(conn, "devices") is False

    assert apply_migrations(empty_db) == ["001"]

    with _connect(empty_db) as conn:
        for table in ("devices", "inspections", "schema_migrations"):
            assert _table_exists(conn, table), table
        rows = conn.execute("select version, checksum from schema_migrations").fetchall()
    assert rows == [("001", hashlib.sha256(INIT_SQL.read_bytes()).hexdigest())]


def test_ca02_second_apply_is_noop(ca01_db: str) -> None:
    assert apply_migrations(ca01_db) == []
    with _connect(ca01_db) as conn:
        assert _count(conn, "schema_migrations") == 1


def test_ca03_rerunning_sql_file_changes_nothing(ca01_db: str) -> None:
    with _connect(ca01_db) as conn:
        before = _schema_snapshot(conn)
        migrations_before = conn.execute("select * from schema_migrations").fetchall()

    # Simulates the Supabase SQL Editor: the whole file in one transaction.
    with _connect(ca01_db, autocommit=False) as conn:
        conn.execute(INIT_SQL.read_text(encoding="utf-8"))
        conn.commit()

    with _connect(ca01_db) as conn:
        assert _schema_snapshot(conn) == before
        assert conn.execute("select * from schema_migrations").fetchall() == migrations_before
    assert before["columns"] and before["constraints"] and before["indexes"]


# --------------------------------------------------------------------------------------------
# CA-04 .. CA-15, CA-23: schema
# --------------------------------------------------------------------------------------------


def test_ca04_indexes_and_column_types(clean_db: str) -> None:
    with _connect(clean_db) as conn:
        indexes = dict(
            conn.execute(
                "select indexname, indexdef from pg_indexes "
                "where schemaname = 'public' and tablename = 'inspections'"
            ).fetchall()
        )
        columns = dict(
            conn.execute(
                """
                select a.attname, format_type(a.atttypid, a.atttypmod)
                from pg_attribute a
                where a.attrelid = 'public.inspections'::regclass and a.attnum > 0
                  and not a.attisdropped
                """
            ).fetchall()
        )

    expected_indexes = {
        "inspections_inspected_at_idx": "(inspected_at)",
        "inspections_lot_id_idx": "(lot_id)",
        "inspections_source_inspected_at_idx": "(source, inspected_at)",
        "inspections_device_id_idx": "(device_id)",
    }
    for name, cols in expected_indexes.items():
        assert name in indexes, f"missing index {name}"
        assert indexes[name].endswith(cols), indexes[name]

    tz = "timestamp with time zone"
    assert columns == {
        "inspection_id": "uuid",
        "device_id": "text",
        "lot_id": "text",
        "inspected_at": tz,
        "received_at": tz,
        "object_type": "text",
        "grade": "text",
        "grade_score": "real",
        "type_confidence": "real",
        "grade_confidence": "real",
        "needs_review": "boolean",
        "model_version": "text",
        "model_sha256": "text",
        "latency_ms": "integer",
        "source": "text",
        "is_defective": "boolean",
    }


@pytest.mark.parametrize(
    ("constraint", "enum"),
    [
        ("inspections_object_type_check", ObjectType),
        ("inspections_grade_check", Grade),
        ("inspections_source_check", Source),
    ],
)
def test_ca05_enum_checks_match_contract(clean_db: str, constraint: str, enum: type) -> None:
    with _connect(clean_db) as conn:
        row = conn.execute(
            """
            select pg_get_constraintdef(oid) from pg_constraint
            where conname = %s and conrelid = 'public.inspections'::regclass and contype = 'c'
            """,
            (constraint,),
        ).fetchone()
    assert row is not None, f"constraint {constraint} not found"
    literals = set(re.findall(r"'([^']*)'", row[0]))
    assert literals == {m.value for m in enum}


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"object_type": "bolt"}, "inspections_object_type_check"),
        ({"grade": "bad"}, "inspections_grade_check"),
        ({"source": "test"}, "inspections_source_check"),
    ],
)
def test_ca06_enum_values_outside_contract_rejected(
    db: psycopg.Connection, overrides: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(errors.CheckViolation) as exc:
        _insert(db, "inspections", _valid_row(**overrides))
    assert exc.value.sqlstate == "23514"
    assert exc.value.diag.constraint_name == constraint
    assert _count(db, "inspections") == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"object_type": "unknown", "grade": "fair"},
        {"object_type": "screw", "grade": None, "grade_score": None, "grade_confidence": None},
    ],
    ids=["unknown-with-grade", "screw-without-grade"],
)
def test_ca07_grade_null_iff_unknown_rejected(
    db: psycopg.Connection, overrides: dict[str, Any]
) -> None:
    with pytest.raises(errors.CheckViolation):
        _insert(db, "inspections", _valid_row(**overrides))
    assert _count(db, "inspections") == 0


def test_ca07_unknown_without_grade_fields_accepted(db: psycopg.Connection) -> None:
    row = _valid_row(object_type="unknown", grade=None, grade_score=None, grade_confidence=None)
    _insert(db, "inspections", row)
    assert _count(db, "inspections") == 1


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"grade_score": None}, "inspections_grade_fields_null_together"),
        ({"type_confidence": 1.5}, "inspections_ranges_check"),
        ({"grade_score": 4.5}, "inspections_ranges_check"),
        ({"latency_ms": -1}, "inspections_ranges_check"),
        ({"model_sha256": "a" * 63}, "inspections_formats_check"),
        ({"lot_id": "L 001"}, "inspections_formats_check"),
    ],
    ids=[
        "grade_score-null",
        "type_conf-1.5",
        "grade_score-4.5",
        "latency-neg",
        "sha-63",
        "lot-space",
    ],
)
def test_ca08_ranges_and_formats_rejected(
    db: psycopg.Connection, overrides: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(errors.CheckViolation) as exc:
        _insert(db, "inspections", _valid_row(**overrides))
    assert exc.value.diag.constraint_name == constraint
    assert _count(db, "inspections") == 0


def test_ca09_is_defective_matches_contract(db: psycopg.Connection) -> None:
    expected: dict[str, bool] = {}
    for index, grade in enumerate(Grade):
        row = _valid_row(grade=grade.value, grade_score=float(index))
        _insert(db, "inspections", row)
        expected[row["inspection_id"]] = qc_contracts.is_defective(grade)
    unknown = _valid_row(object_type="unknown", grade=None, grade_score=None, grade_confidence=None)
    _insert(db, "inspections", unknown)
    expected[unknown["inspection_id"]] = qc_contracts.is_defective(None)

    got = {str(i): d for i, d in db.execute("select inspection_id, is_defective from inspections")}
    assert len(got) == len(Grade) + 1 == 6
    assert got == expected


@pytest.mark.parametrize("value", [True, False])
def test_ca10_is_defective_cannot_be_written(db: psycopg.Connection, value: bool) -> None:
    with pytest.raises(psycopg.Error):
        _insert(db, "inspections", _valid_row(is_defective=value))
    assert _count(db, "inspections") == 0


def test_ca11_duplicate_inspection_id(db: psycopg.Connection) -> None:
    row = _valid_row()
    _insert(db, "inspections", row)

    with pytest.raises(errors.UniqueViolation):
        _insert(db, "inspections", _valid_row(inspection_id=row["inspection_id"]))

    again = _valid_row(inspection_id=row["inspection_id"])
    cur = db.execute(
        _insert_sql(
            "inspections", again, " on conflict (inspection_id) do nothing returning inspection_id"
        ),
        again,
    )
    assert cur.fetchone() is None
    assert _count(db, "inspections") == 1


def test_ca12_foreign_keys(db: psycopg.Connection) -> None:
    with pytest.raises(errors.ForeignKeyViolation):
        _insert(db, "inspections", _valid_row(device_id="ghost-01"))

    _insert(db, "inspections", _valid_row())
    with pytest.raises(errors.ForeignKeyViolation):
        db.execute("delete from devices where device_id = 'edge-01'")
    assert _count(db, "devices") == 1
    assert _count(db, "inspections") == 1


@pytest.mark.parametrize(
    ("device", "expected_error"),
    [
        ({"device_id": "Edge_01", "api_key_hash": "b" * 64}, errors.CheckViolation),
        ({"device_id": "edge-02", "api_key_hash": "b" * 10}, errors.CheckViolation),
        ({"device_id": "edge-02", "api_key_hash": EDGE_HASH}, errors.UniqueViolation),
    ],
    ids=["uppercase-underscore-id", "short-hash", "reused-hash"],
)
def test_ca13_device_rejections(
    db: psycopg.Connection, device: dict[str, str], expected_error: type[Exception]
) -> None:
    with pytest.raises(expected_error):
        _insert(db, "devices", device)
    assert _count(db, "devices") == 1


def test_ca13_device_defaults(db: psycopg.Connection) -> None:
    before = db.execute("select now()").fetchone()[0]
    _add_device(db, "edge-02", "c" * 64)
    created_at, last_seen_at = db.execute(
        "select created_at, last_seen_at from devices where device_id = 'edge-02'"
    ).fetchone()
    assert created_at is not None and created_at.tzinfo is not None
    assert created_at >= before
    assert last_seen_at is None


def test_ca14_rls_enabled_without_force_and_policies(clean_db: str) -> None:
    tables = ("devices", "inspections", "schema_migrations")
    with _connect(clean_db) as conn:
        rows = conn.execute(
            """
            select c.relname, c.relrowsecurity, c.relforcerowsecurity
            from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relname = any(%s)
            """,
            (list(tables),),
        ).fetchall()
        policies = conn.execute(
            "select count(*) from pg_policies where schemaname = 'public' and tablename = any(%s)",
            (list(tables),),
        ).fetchone()[0]
    assert sorted(rows) == [(t, True, False) for t in sorted(tables)]
    assert policies == 0


def test_ca15_rls_blocks_role_without_policies(clean_db: str, rls_probe_role: str) -> None:
    role = sql.Identifier(rls_probe_role)
    with _connect(clean_db) as conn:
        _add_device(conn)
        for _ in range(3):
            _insert(conn, "inspections", _valid_row())
        conn.execute(sql.SQL("create role {} nologin nosuperuser nobypassrls").format(role))
        conn.execute(sql.SQL("grant usage on schema public to {}").format(role))
        conn.execute(sql.SQL("grant select, insert on inspections, devices to {}").format(role))

    with _connect(clean_db, autocommit=False) as conn:
        conn.execute(sql.SQL("set local role {}").format(role))
        assert conn.execute("select current_user").fetchone()[0] == rls_probe_role
        assert conn.execute("select count(*) from inspections").fetchone()[0] == 0
        assert conn.execute("select count(*) from devices").fetchone()[0] == 0
        with pytest.raises(psycopg.Error) as exc:
            _insert(conn, "inspections", _valid_row())
        assert exc.value.sqlstate == "42501"
        conn.rollback()

    with _connect(clean_db) as conn:
        assert _count(conn, "inspections") == 3  # the owner still sees everything


def test_ca23_latency_ms_int4_ceiling(db: psycopg.Connection) -> None:
    ok = _valid_row(latency_ms=2147483647)
    _insert(db, "inspections", ok)
    got = db.execute(
        "select latency_ms from inspections where inspection_id = %s", (ok["inspection_id"],)
    ).fetchone()[0]
    assert got == 2147483647

    with pytest.raises(errors.NumericValueOutOfRange) as exc:
        _insert(db, "inspections", _valid_row(latency_ms=2147483648))
    assert exc.value.sqlstate == "22003"
    assert _count(db, "inspections") == 1


# --------------------------------------------------------------------------------------------
# CA-16 .. CA-18: rollback, checksum, file names
# --------------------------------------------------------------------------------------------


def test_ca16_failed_migration_rolls_back(empty_db: str, tmp_path: Path) -> None:
    shutil.copy(INIT_SQL, tmp_path / "001_init.sql")
    (tmp_path / "002_broken.sql").write_text(
        "create table t_ok(id int); select from nao_existe;\n", encoding="utf-8"
    )

    with pytest.raises(Exception):  # noqa: B017 - the SPEC only requires "levanta erro"
        apply_migrations(empty_db, tmp_path)

    with _connect(empty_db) as conn:
        assert _applied_versions(conn) == ["001"]
        assert _table_exists(conn, "t_ok") is False


def test_ca17_checksum_mismatch(empty_db: str, tmp_path: Path) -> None:
    copy = tmp_path / "001_init.sql"
    shutil.copy(INIT_SQL, copy)
    assert apply_migrations(empty_db, tmp_path) == ["001"]

    copy.write_text(copy.read_text(encoding="utf-8") + "\n-- edited later\n", encoding="utf-8")
    with pytest.raises(Exception, match="checksum mismatch for 001"):
        apply_migrations(empty_db, tmp_path)


def test_ca18_invalid_file_name_rejected_before_applying(empty_db: str, tmp_path: Path) -> None:
    shutil.copy(INIT_SQL, tmp_path / "001_init.sql")
    (tmp_path / "abc.sql").write_text("create table t_abc(id int);\n", encoding="utf-8")

    with pytest.raises(Exception):  # noqa: B017 - the SPEC only requires "levanta erro"
        apply_migrations(empty_db, tmp_path)

    with _connect(empty_db) as conn:
        assert _applied_versions(conn) == []
        assert _table_exists(conn, "devices") is False
        assert _table_exists(conn, "t_abc") is False


# --------------------------------------------------------------------------------------------
# CA-19 .. CA-21: CLI
# --------------------------------------------------------------------------------------------


def test_ca19_cli_without_url_exits_2() -> None:
    result = _run_cli()
    assert result.returncode == 2, result
    assert "DATABASE_URL" in result.stdout + result.stderr


def test_ca20_cli_closed_port_does_not_leak_password() -> None:
    result = _run_cli("--database-url", f"postgresql://u:{SECRET}@127.0.0.1:1/x")
    assert result.returncode == 1, result
    assert SECRET not in result.stdout
    assert SECRET not in result.stderr


def test_ca21_cli_status_lists_applied(ca01_db: str) -> None:
    result = _run_cli("--database-url", ca01_db, "--status")
    assert result.returncode == 0, result
    output = result.stdout + result.stderr
    lines_001 = [line for line in output.splitlines() if "001" in line]
    assert lines_001, output
    assert any("applied" in line.lower() for line in lines_001), output
    assert not any("pending" in line.lower() for line in lines_001), output
    assert pending_migrations(ca01_db) == []


# --------------------------------------------------------------------------------------------
# CA-22: safety guard of db_conninfo
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("probe", ["test_probe_db_conninfo", "test_probe_clean_db"])
def test_ca22_guard_refuses_non_test_database(probe: str) -> None:
    listener = _Listener()
    try:
        env = {k: v for k, v in os.environ.items() if k not in {"CI", "TEST_DATABASE_URL"}}
        env["TEST_DATABASE_URL"] = f"postgresql://postgres@127.0.0.1:{listener.port}/partqc_prod"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"{PROBE_FILE}::{probe}",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        listener.close()

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert GUARD_MESSAGE in output, output
    assert re.search(r"\b1 (failed|error)\b", output), output
    assert "passed" not in output, output
    assert listener.accepted == 0, "a connection reached the database"


# --------------------------------------------------------------------------------------------
# extras: requirements of sections 4.1 to 4.4 without a CA, and exploratory cases
# --------------------------------------------------------------------------------------------


def test_extra_sql_file_has_no_transaction_control_force_or_policies() -> None:
    text = INIT_SQL.read_text(encoding="utf-8")
    code = "\n".join(line.split("--", 1)[0] for line in text.splitlines()).lower()
    assert not re.search(r"\b(begin|commit|rollback)\s*;", code)
    assert "force row level security" not in code
    assert "create policy" not in code
    assert "password" not in code


def test_extra_inspection_nullability_defaults_and_generated(clean_db: str) -> None:
    with _connect(clean_db) as conn:
        cols = {
            r[0]: r[1:]
            for r in conn.execute(
                """
                select column_name, is_nullable, column_default, is_generated
                from information_schema.columns
                where table_schema = 'public' and table_name = 'inspections'
                """
            )
        }
        pk = conn.execute(
            """
            select a.attname from pg_index i
            join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
            where i.indrelid = 'public.inspections'::regclass and i.indisprimary
            """
        ).fetchall()
    not_null = {
        "inspection_id", "lot_id", "inspected_at", "received_at", "object_type",
        "type_confidence", "needs_review", "model_version", "model_sha256", "latency_ms", "source",
    }  # fmt: skip
    for col in not_null:
        assert cols[col][0] == "NO", col
    for col in ("grade", "grade_score", "grade_confidence"):
        assert cols[col][0] == "YES", col
    assert "now()" in (cols["received_at"][1] or "")
    assert cols["is_defective"][2] == "ALWAYS"
    assert pk == [("inspection_id",)]


def test_extra_devices_columns(clean_db: str) -> None:
    with _connect(clean_db) as conn:
        cols = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                """
                select a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull
                from pg_attribute a
                where a.attrelid = 'public.devices'::regclass and a.attnum > 0
                  and not a.attisdropped
                """
            )
        }
    tz = "timestamp with time zone"
    assert cols == {
        "device_id": ("text", True),
        "api_key_hash": ("text", True),
        "created_at": (tz, True),
        "last_seen_at": (tz, False),
    }


def test_extra_named_constraints_exist(clean_db: str) -> None:
    names = {
        "inspections_object_type_check",
        "inspections_grade_check",
        "inspections_source_check",
        "inspections_grade_null_iff_unknown",
        "inspections_grade_fields_null_together",
        "inspections_ranges_check",
        "inspections_formats_check",
    }
    with _connect(clean_db) as conn:
        found = {
            r[0]
            for r in conn.execute(
                "select conname from pg_constraint "
                "where conrelid = 'public.inspections'::regclass and contype = 'c'"
            )
        }
    assert names <= found


@pytest.mark.parametrize(
    "overrides",
    [
        {"type_confidence": 0.0},
        {"type_confidence": 1.0},
        {"grade_confidence": 0.0},
        {"grade_confidence": 1.0},
        {"grade_score": 0.0},
        {"grade_score": 4.0},
        {"latency_ms": 0},
        {"lot_id": "A" * 40},
        {"lot_id": "a_b-C9"},
        {"object_type": "nut"},
        {"source": "simulated"},
    ],
)
def test_extra_inclusive_limits_accepted(db: psycopg.Connection, overrides: dict[str, Any]) -> None:
    _insert(db, "inspections", _valid_row(**overrides))
    assert _count(db, "inspections") == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"type_confidence": -0.01},
        {"grade_confidence": 1.01},
        {"grade_confidence": -0.5},
        {"grade_score": -0.1},
        {"lot_id": "A" * 41},
        {"lot_id": ""},
        {"lot_id": "Lóte1"},
        {"lot_id": "L001\n"},
        {"model_sha256": "A" * 64},
        {"model_sha256": "a" * 65},
        {"model_sha256": "g" * 64},
        {"grade_confidence": None},
        {"object_type": "Screw"},
        {"source": "LIVE"},
        {"type_confidence": float("nan")},
        {"grade_score": float("nan")},
    ],
)
def test_extra_out_of_contract_values_rejected(
    db: psycopg.Connection, overrides: dict[str, Any]
) -> None:
    with pytest.raises(errors.CheckViolation):
        _insert(db, "inspections", _valid_row(**overrides))
    assert _count(db, "inspections") == 0


@pytest.mark.parametrize("device_id", ["ab", "a" * 33, "edge 01", "edge-01\n", "édge-01", ""])
def test_extra_bad_device_ids_rejected(db: psycopg.Connection, device_id: str) -> None:
    with pytest.raises(errors.CheckViolation):
        _add_device(db, device_id, "d" * 64)


@pytest.mark.parametrize("device_id", ["abc", "a" * 32, "0-9"])
def test_extra_device_id_limits_accepted(db: psycopg.Connection, device_id: str) -> None:
    _add_device(db, device_id, "d" * 64)


def test_extra_is_defective_cannot_be_updated(db: psycopg.Connection) -> None:
    _insert(db, "inspections", _valid_row())
    with pytest.raises(psycopg.Error):
        db.execute("update inspections set is_defective = true")


def test_extra_is_defective_follows_grade_update(db: psycopg.Connection) -> None:
    row = _valid_row(grade="fair")
    _insert(db, "inspections", row)
    db.execute(
        "update inspections set grade = 'poor' where inspection_id = %s", (row["inspection_id"],)
    )
    assert db.execute("select is_defective from inspections").fetchone()[0] is True


def test_extra_received_at_default_is_utc_aware(db: psycopg.Connection) -> None:
    _insert(db, "inspections", _valid_row())
    received_at = db.execute("select received_at from inspections").fetchone()[0]
    assert received_at.tzinfo is not None


def test_extra_schema_migrations_columns(ca01_db: str) -> None:
    with _connect(ca01_db) as conn:
        cols = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                """
                select a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull
                from pg_attribute a
                where a.attrelid = 'public.schema_migrations'::regclass and a.attnum > 0
                  and not a.attisdropped
                """
            )
        }
        row = conn.execute("select filename, applied_at from schema_migrations").fetchone()
    assert cols == {
        "version": ("text", True),
        "filename": ("text", True),
        "checksum": ("text", True),
        "applied_at": ("timestamp with time zone", True),
    }
    assert row[0] == "001_init.sql"
    assert row[1].tzinfo is not None


def test_extra_manual_then_runner(empty_db: str) -> None:
    """4.1: applying the file by hand first and then running migrate.py must not break."""
    with _connect(empty_db, autocommit=False) as conn:
        conn.execute(INIT_SQL.read_text(encoding="utf-8"))
        conn.commit()
    assert apply_migrations(empty_db) == ["001"]
    assert pending_migrations(empty_db) == []


def test_extra_pending_on_empty_schema(empty_db: str) -> None:
    assert pending_migrations(empty_db) == ["001"]
    with _connect(empty_db) as conn:
        assert _table_exists(conn, "devices") is False


def test_extra_order_by_number(empty_db: str, tmp_path: Path) -> None:
    shutil.copy(INIT_SQL, tmp_path / "001_init.sql")
    (tmp_path / "010_uses_t_a.sql").write_text("alter table t_a add column b int;\n", "utf-8")
    (tmp_path / "002_t_a.sql").write_text("create table t_a(id int);\n", "utf-8")
    assert pending_migrations(empty_db, tmp_path) == ["001", "002", "010"]
    assert apply_migrations(empty_db, tmp_path) == ["001", "002", "010"]
    assert pending_migrations(empty_db, tmp_path) == []


def test_extra_new_migration_after_existing(ca01_db: str, tmp_path: Path) -> None:
    shutil.copy(INIT_SQL, tmp_path / "001_init.sql")
    (tmp_path / "002_more.sql").write_text("create table t_more(id int);\n", "utf-8")
    assert pending_migrations(ca01_db, tmp_path) == ["002"]
    assert apply_migrations(ca01_db, tmp_path) == ["002"]
    with _connect(ca01_db) as conn:
        assert _applied_versions(conn) == ["001", "002"]


def test_extra_failure_stops_following_migrations(empty_db: str, tmp_path: Path) -> None:
    shutil.copy(INIT_SQL, tmp_path / "001_init.sql")
    (tmp_path / "002_broken.sql").write_text("select from nao_existe;\n", "utf-8")
    (tmp_path / "003_after.sql").write_text("create table t_after(id int);\n", "utf-8")
    with pytest.raises(Exception):  # noqa: B017
        apply_migrations(empty_db, tmp_path)
    with _connect(empty_db) as conn:
        assert _applied_versions(conn) == ["001"]
        assert _table_exists(conn, "t_after") is False


def test_extra_checksum_mismatch_applies_nothing(empty_db: str, tmp_path: Path) -> None:
    copy = tmp_path / "001_init.sql"
    shutil.copy(INIT_SQL, copy)
    apply_migrations(empty_db, tmp_path)
    copy.write_bytes(copy.read_bytes() + b"\n-- changed\n")
    (tmp_path / "002_new.sql").write_text("create table t_new(id int);\n", "utf-8")
    with pytest.raises(Exception, match="checksum mismatch for 001"):
        apply_migrations(empty_db, tmp_path)
    with _connect(empty_db) as conn:
        assert _applied_versions(conn) == ["001"]
        assert _table_exists(conn, "t_new") is False


@pytest.mark.parametrize(
    "names",
    [
        ["002_a.sql", "002_b.sql"],
        ["2_short.sql"],
        ["003_Upper.sql"],
        ["004-dash.sql"],
        ["0005_four_digits.sql"],
        ["006_ação.sql"],
        ["007_.sql"],
    ],
)
def test_extra_bad_names_or_duplicates_touch_nothing(
    empty_db: str, tmp_path: Path, names: list[str]
) -> None:
    shutil.copy(INIT_SQL, tmp_path / "001_init.sql")
    for name in names:
        (tmp_path / name).write_text("create table t_x(id int);\n", "utf-8")
    with pytest.raises(Exception):  # noqa: B017
        apply_migrations(empty_db, tmp_path)
    with _connect(empty_db) as conn:
        assert _applied_versions(conn) == []
        assert _table_exists(conn, "devices") is False


def test_extra_concurrent_runs_apply_once(empty_db: str) -> None:
    results: list[Any] = []
    barrier = threading.Barrier(4)

    def worker() -> None:
        barrier.wait()
        try:
            results.append(apply_migrations(empty_db))
        except Exception as exc:  # noqa: BLE001
            results.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(map(repr, results)) == sorted([repr(["001"])] + [repr([])] * 3)
    with _connect(empty_db) as conn:
        assert _count(conn, "schema_migrations") == 1


def test_extra_advisory_lock_released(empty_db: str) -> None:
    apply_migrations(empty_db)
    with _connect(empty_db) as conn:
        held = conn.execute("select count(*) from pg_locks where locktype = 'advisory'").fetchone()
    assert held[0] == 0


@pytest.mark.parametrize(
    "conninfo",
    [
        f"postgresql://u:{SECRET}@127.0.0.1:1/x_test",
        f"host=127.0.0.1 port=1 user=u password={SECRET} dbname=x_test",
        f"postgresql://u:{SECRET}@127.0.0.1:1/x_test?connect_timeout=2",
    ],
)
def test_extra_function_errors_do_not_leak_password(conninfo: str) -> None:
    for func in (apply_migrations, pending_migrations):
        with pytest.raises(Exception) as exc:  # noqa: B017
            func(conninfo)
        text = "".join(traceback.format_exception(exc.value))
        assert SECRET not in text
        assert conninfo not in text


def test_extra_cli_password_in_env_not_leaked() -> None:
    result = _run_cli(env_extra={"DATABASE_URL": f"postgresql://u:{SECRET}@127.0.0.1:1/x"})
    assert result.returncode == 1, result
    assert SECRET not in result.stdout + result.stderr


def test_extra_cli_missing_database_on_real_server_not_leaked(db_conninfo: str) -> None:
    url = make_conninfo(db_conninfo, dbname="partqc_test_does_not_exist", password=SECRET)
    result = _run_cli("--database-url", url)
    assert result.returncode == 1, result
    out = result.stdout + result.stderr
    assert SECRET not in out
    assert url not in out


def test_extra_cli_apply_success_hides_url(empty_db: str) -> None:
    # The local test server uses trust auth, so a password in the URL is ignored but present.
    url = make_conninfo(empty_db, password=SECRET)
    result = _run_cli("--database-url", url)
    assert result.returncode == 0, result
    out = result.stdout + result.stderr
    assert "001" in out
    assert SECRET not in out
    with _connect(empty_db) as conn:
        assert _applied_versions(conn) == ["001"]


def test_extra_cli_uses_database_url_env(empty_db: str) -> None:
    result = _run_cli(env_extra={"DATABASE_URL": empty_db})
    assert result.returncode == 0, result
    with _connect(empty_db) as conn:
        assert _applied_versions(conn) == ["001"]


def test_extra_cli_status_applies_nothing(empty_db: str) -> None:
    result = _run_cli("--database-url", empty_db, "--status")
    assert result.returncode == 0, result
    out = result.stdout + result.stderr
    assert any("001" in line and "pending" in line.lower() for line in out.splitlines()), out
    with _connect(empty_db) as conn:
        assert _applied_versions(conn) == []
        assert _table_exists(conn, "devices") is False


def test_extra_cli_checksum_mismatch_exits_1(empty_db: str, tmp_path: Path) -> None:
    copy = tmp_path / "001_init.sql"
    shutil.copy(INIT_SQL, copy)
    apply_migrations(empty_db, tmp_path)
    copy.write_bytes(copy.read_bytes() + b"\n-- changed\n")
    result = _run_cli("--database-url", empty_db, "--migrations-dir", str(tmp_path))
    assert result.returncode == 1, result
    assert "checksum mismatch for 001" in result.stdout + result.stderr


def test_extra_cli_failed_migration_exits_1(empty_db: str, tmp_path: Path) -> None:
    shutil.copy(INIT_SQL, tmp_path / "001_init.sql")
    (tmp_path / "002_broken.sql").write_text("select from nao_existe;\n", "utf-8")
    result = _run_cli("--database-url", empty_db, "--migrations-dir", str(tmp_path))
    assert result.returncode == 1, result


@pytest.mark.parametrize("args", [["--bogus"], ["--status", "extra-positional"]])
def test_extra_cli_invalid_arguments_exit_2(args: list[str]) -> None:
    result = _run_cli(*args, env_extra={"DATABASE_URL": "postgresql://u@127.0.0.1:1/x"})
    assert result.returncode == 2, result


def test_extra_cli_blank_url_counts_as_missing() -> None:
    result = _run_cli(env_extra={"DATABASE_URL": "   "})
    assert result.returncode == 2, result
    assert "DATABASE_URL" in result.stdout + result.stderr


def test_extra_clean_db_truncates(clean_db: str) -> None:
    with _connect(clean_db) as conn:
        _add_device(conn)
        _insert(conn, "inspections", _valid_row())


def test_extra_clean_db_truncates_check(clean_db: str) -> None:
    """Runs after the previous test: clean_db must have emptied both tables."""
    with _connect(clean_db) as conn:
        assert _count(conn, "inspections") == 0
        assert _count(conn, "devices") == 0


def test_extra_migration_content_is_not_interpolated(empty_db: str, tmp_path: Path) -> None:
    """4.3: the file runs as-is; ``%`` placeholders-like text is not touched."""
    shutil.copy(INIT_SQL, tmp_path / "001_init.sql")
    (tmp_path / "002_pct.sql").write_text(
        "create table t_p(v text); insert into t_p values ('100%'), ('%s'), ('%(x)s');\n", "utf-8"
    )
    assert apply_migrations(empty_db, tmp_path) == ["001", "002"]
    with _connect(empty_db) as conn:
        rows = {r[0] for r in conn.execute("select v from t_p")}
    assert rows == {"100%", "%s", "%(x)s"}
