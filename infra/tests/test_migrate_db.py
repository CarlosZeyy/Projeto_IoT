"""Runner behaviour against the test PostgreSQL (SPEC-003 §4.2). All tests are marked `db`.

Tests that need an empty ``public`` schema use ``empty_schema``, which restores the migrated
schema afterwards so the session fixture ``migrated_db`` stays valid for the other tests.
"""

from __future__ import annotations

import hashlib
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from migrate import (
    DEFAULT_DIR,
    MigrationError,
    apply_migrations,
    pending_migrations,
)

pytestmark = pytest.mark.db

INIT_SQL = DEFAULT_DIR / "001_init.sql"


def _reset(conninfo: str) -> None:
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")


@pytest.fixture
def empty_schema(migrated_db: str) -> Iterator[str]:
    _reset(migrated_db)
    yield migrated_db
    _reset(migrated_db)
    apply_migrations(migrated_db)


def _query(conninfo: str, sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(conninfo) as conn:
        return conn.execute(sql, params).fetchall()


def _tables(conninfo: str) -> set[str]:
    rows = _query(
        conninfo,
        "select table_name from information_schema.tables where table_schema = 'public'",
    )
    return {row[0] for row in rows}


def _schema_snapshot(conninfo: str) -> dict[str, list[tuple]]:
    return {
        "columns": _query(
            conninfo,
            """
            select table_name, column_name, data_type, is_nullable, column_default,
                   is_generated, generation_expression
            from information_schema.columns where table_schema = 'public'
            order by table_name, column_name
            """,
        ),
        "constraints": _query(
            conninfo,
            """
            select conrelid::regclass::text, conname, pg_get_constraintdef(oid)
            from pg_constraint where connamespace = 'public'::regnamespace
            order by 1, 2
            """,
        ),
        "indexes": _query(
            conninfo,
            "select tablename, indexname, indexdef from pg_indexes "
            "where schemaname = 'public' order by 1, 2",
        ),
        "rls": _query(
            conninfo,
            "select relname, relrowsecurity, relforcerowsecurity from pg_class "
            "where relnamespace = 'public'::regnamespace and relkind = 'r' order by 1",
        ),
    }


def _copy_init(directory: Path) -> Path:
    target = directory / "001_init.sql"
    shutil.copyfile(INIT_SQL, target)
    return target


def test_apply_on_empty_schema(empty_schema: str) -> None:
    assert pending_migrations(empty_schema) == ["001"]
    assert apply_migrations(empty_schema) == ["001"]
    assert {"devices", "inspections", "schema_migrations"} <= _tables(empty_schema)
    rows = _query(empty_schema, "select version, filename, checksum from schema_migrations")
    assert rows == [("001", "001_init.sql", hashlib.sha256(INIT_SQL.read_bytes()).hexdigest())]
    assert pending_migrations(empty_schema) == []


def test_apply_is_idempotent(migrated_db: str) -> None:
    assert apply_migrations(migrated_db) == []
    assert _query(migrated_db, "select count(*) from schema_migrations") == [(1,)]


def test_running_sql_file_again_changes_nothing(migrated_db: str) -> None:
    before = _schema_snapshot(migrated_db)
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute(INIT_SQL.read_text(encoding="utf-8"))
    assert _schema_snapshot(migrated_db) == before


def test_manual_then_runner_does_not_fail(empty_schema: str) -> None:
    with psycopg.connect(empty_schema, autocommit=True) as conn:
        conn.execute(INIT_SQL.read_text(encoding="utf-8"))
    assert apply_migrations(empty_schema) == ["001"]


def test_failed_migration_is_rolled_back(empty_schema: str, tmp_path: Path) -> None:
    _copy_init(tmp_path)
    (tmp_path / "002_broken.sql").write_text(
        "create table t_ok(id int); select from nao_existe;\n", encoding="utf-8"
    )
    (tmp_path / "003_never.sql").write_text("create table t_never(id int);\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="migration 002"):
        apply_migrations(empty_schema, tmp_path)
    assert _query(empty_schema, "select version from schema_migrations") == [("001",)]
    tables = _tables(empty_schema)
    assert "t_ok" not in tables
    assert "t_never" not in tables
    assert pending_migrations(empty_schema, tmp_path) == ["002", "003"]


def test_checksum_mismatch_applies_nothing(migrated_db: str, tmp_path: Path) -> None:
    copy = _copy_init(tmp_path)
    copy.write_text(copy.read_text(encoding="utf-8") + "-- changed\n", encoding="utf-8")
    (tmp_path / "002_more.sql").write_text("create table t_more(id int);\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="checksum mismatch for 001"):
        apply_migrations(migrated_db, tmp_path)
    with pytest.raises(MigrationError, match="checksum mismatch for 001"):
        pending_migrations(migrated_db, tmp_path)
    assert "t_more" not in _tables(migrated_db)
    assert _query(migrated_db, "select count(*) from schema_migrations") == [(1,)]


def test_invalid_filename_touches_nothing(empty_schema: str, tmp_path: Path) -> None:
    _copy_init(tmp_path)
    (tmp_path / "abc.sql").write_text("select 1;\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="invalid migration filename"):
        apply_migrations(empty_schema, tmp_path)
    assert _tables(empty_schema) == set()


def test_duplicate_number_touches_nothing(empty_schema: str, tmp_path: Path) -> None:
    _copy_init(tmp_path)
    (tmp_path / "001_other.sql").write_text("select 1;\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="duplicate migration number 001"):
        apply_migrations(empty_schema, tmp_path)
    assert _tables(empty_schema) == set()


def test_new_migration_is_applied_after_existing_ones(empty_schema: str, tmp_path: Path) -> None:
    _copy_init(tmp_path)
    assert apply_migrations(empty_schema, tmp_path) == ["001"]
    (tmp_path / "002_extra.sql").write_text("create table t_extra(id int);\n", encoding="utf-8")
    assert pending_migrations(empty_schema, tmp_path) == ["002"]
    assert apply_migrations(empty_schema, tmp_path) == ["002"]
    rows = _query(empty_schema, "select version from schema_migrations order by version")
    assert rows == [("001",), ("002",)]


def test_control_table_has_rls_without_policies(migrated_db: str) -> None:
    assert _query(
        migrated_db,
        "select relrowsecurity, relforcerowsecurity from pg_class "
        "where oid = 'public.schema_migrations'::regclass",
    ) == [(True, False)]
    assert _query(
        migrated_db, "select count(*) from pg_policies where tablename = 'schema_migrations'"
    ) == [(0,)]


def test_control_table_columns(migrated_db: str) -> None:
    rows = _query(
        migrated_db,
        """
        select column_name, data_type, is_nullable from information_schema.columns
        where table_schema = 'public' and table_name = 'schema_migrations'
        order by ordinal_position
        """,
    )
    assert rows == [
        ("version", "text", "NO"),
        ("filename", "text", "NO"),
        ("checksum", "text", "NO"),
        ("applied_at", "timestamp with time zone", "NO"),
    ]


def test_concurrent_runs_apply_once(empty_schema: str) -> None:
    results: list[list[str]] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(apply_migrations(empty_schema))
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors == []
    assert sorted(results) == [[], [], [], ["001"]]
    assert _query(empty_schema, "select count(*) from schema_migrations") == [(1,)]


def test_advisory_lock_is_released(migrated_db: str) -> None:
    apply_migrations(migrated_db)
    assert _query(migrated_db, "select count(*) from pg_locks where locktype = 'advisory'") == [
        (0,)
    ]
