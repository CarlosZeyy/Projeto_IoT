"""Runner behaviour against the test PostgreSQL (SPEC-003 §4.2). All tests are marked `db`.

Tests that need an empty ``public`` schema use ``empty_schema``, which restores the migrated
schema afterwards so the session fixture ``migrated_db`` stays valid for the other tests.
"""

from __future__ import annotations

import hashlib
import shutil
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from migrate import (
    DEFAULT_DIR,
    MigrationError,
    apply_migrations,
    load_migrations,
    pending_migrations,
)

pytestmark = pytest.mark.db

INIT_SQL = DEFAULT_DIR / "001_init.sql"
CHECKS_SQL = DEFAULT_DIR / "002_contract_checks.sql"
# Every version of infra/migrations, computed (not hard-coded) so a new migration does not
# break these tests (SPEC-027 section 3.1).
ALL_VERSIONS = [migration.version for migration in load_migrations()]
CONTRACT_CHECKS = {
    "inspections_model_version_check",
    "inspections_inspection_id_v4_check",
    "inspections_inspected_at_range_check",
    "inspections_received_at_range_check",
}


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


def _check_constraints(conninfo: str) -> set[str]:
    rows = _query(
        conninfo,
        "select conname from pg_constraint "
        "where conrelid = 'inspections'::regclass and contype = 'c'",
    )
    return {row[0] for row in rows}


def test_default_dir_starts_with_init_and_contract_checks() -> None:
    assert ALL_VERSIONS[:2] == ["001", "002"]


def test_apply_on_empty_schema(empty_schema: str) -> None:
    assert pending_migrations(empty_schema) == ALL_VERSIONS
    assert apply_migrations(empty_schema) == ALL_VERSIONS
    assert {"devices", "inspections", "schema_migrations"} <= _tables(empty_schema)
    rows = _query(
        empty_schema,
        "select version, filename, checksum from schema_migrations order by version",
    )
    assert rows == [
        (m.version, m.filename, hashlib.sha256(m.path.read_bytes()).hexdigest())
        for m in load_migrations()
    ]
    assert rows[1] == (
        "002",
        "002_contract_checks.sql",
        hashlib.sha256(CHECKS_SQL.read_bytes()).hexdigest(),
    )
    assert pending_migrations(empty_schema) == []


def test_apply_is_idempotent(migrated_db: str) -> None:
    assert apply_migrations(migrated_db) == []
    assert _query(migrated_db, "select count(*) from schema_migrations") == [(len(ALL_VERSIONS),)]


@pytest.mark.parametrize("migration", load_migrations(), ids=lambda m: m.filename)
def test_running_sql_file_again_changes_nothing(migrated_db: str, migration) -> None:
    """Running a file again (twice) and then every later file again gives the same schema.

    A later migration may replace a check of an earlier one (006 replaces the object_type and
    grade checks of 003, SPEC-021): running only the earlier file again brings its older check
    back, and the later files, run again in order, restore the current one. For the last file,
    and for every file that no later file supersedes, this is the plain "runs again and
    changes nothing".
    """
    before = _schema_snapshot(migrated_db)
    later = [m for m in load_migrations() if m.version > migration.version]
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute(migration.read_sql())
        conn.execute(migration.read_sql())
        for next_migration in later:
            conn.execute(next_migration.read_sql())
    assert _schema_snapshot(migrated_db) == before


def test_power_tool_migration_supersedes_the_hand_tool_checks(migrated_db: str) -> None:
    """Running 003 alone again brings back its 8-value check; 006 restores the 12 values."""
    by_name = {m.filename: m for m in load_migrations()}
    query = (
        "select pg_get_constraintdef(oid) from pg_constraint "
        "where conname = 'inspections_object_type_check'"
    )
    (current,) = _query(migrated_db, query)
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute(by_name["003_tool_object_types.sql"].read_sql())
        (older,) = conn.execute(query).fetchall()
        conn.execute(by_name["006_power_tool_object_types.sql"].read_sql())
    assert "drill" not in older[0] and "drill" in current[0]
    assert _query(migrated_db, query) == [current]


def test_manual_then_runner_does_not_fail(empty_schema: str) -> None:
    with psycopg.connect(empty_schema, autocommit=True) as conn:
        conn.execute(INIT_SQL.read_text(encoding="utf-8"))
    assert apply_migrations(empty_schema) == ALL_VERSIONS


def test_manual_001_and_002_then_runner_does_not_fail(empty_schema: str) -> None:
    with psycopg.connect(empty_schema, autocommit=True) as conn:
        conn.execute(INIT_SQL.read_text(encoding="utf-8"))
        conn.execute(CHECKS_SQL.read_text(encoding="utf-8"))
    assert apply_migrations(empty_schema) == ALL_VERSIONS
    assert _check_constraints(empty_schema) >= CONTRACT_CHECKS


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
    assert _query(migrated_db, "select count(*) from schema_migrations") == [(len(ALL_VERSIONS),)]


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
    assert sorted(results) == [[], [], [], ALL_VERSIONS]
    assert _query(empty_schema, "select count(*) from schema_migrations") == [(len(ALL_VERSIONS),)]


def test_advisory_lock_is_released(migrated_db: str) -> None:
    apply_migrations(migrated_db)
    assert _query(migrated_db, "select count(*) from pg_locks where locktype = 'advisory'") == [
        (0,)
    ]


# ---------- 002_contract_checks: check of the existing rows (SPEC-027 section 4.1) ----------


def _copy_init_and_checks(directory: Path) -> None:
    _copy_init(directory)
    shutil.copyfile(CHECKS_SQL, directory / CHECKS_SQL.name)


def _insert_raw(conninfo: str, **overrides: object) -> None:
    """One inspection written by plain SQL (as the SQL Editor would), bypassing the API."""
    row: dict[str, object] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-001",
        "inspected_at": "2026-10-12T12:00:00Z",
        "object_type": "screw",
        "grade": "fair",
        "grade_score": 2.0,
        "type_confidence": 0.9,
        "grade_confidence": 0.8,
        "needs_review": False,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": "a" * 64,
        "latency_ms": 100,
        "source": "live",
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(
            "insert into devices (device_id, api_key_hash) values ('edge-01', %s) "
            "on conflict do nothing",
            ("b" * 64,),
        )
        conn.execute(f"insert into inspections ({columns}) values ({placeholders})", row)


@pytest.fixture
def only_001(empty_schema: str, tmp_path: Path) -> Path:
    """Schema with only 001 applied; ``tmp_path`` holds copies of 001 and 002."""
    _copy_init(tmp_path)
    assert apply_migrations(empty_schema, tmp_path) == ["001"]
    shutil.copyfile(CHECKS_SQL, tmp_path / CHECKS_SQL.name)
    return tmp_path


def test_002_creates_the_four_check_constraints(migrated_db: str) -> None:
    rows = _query(
        migrated_db,
        "select conname, contype from pg_constraint "
        "where conrelid = 'inspections'::regclass and conname = any(%s)",
        (sorted(CONTRACT_CHECKS),),
    )
    assert sorted(rows) == sorted((name, "c") for name in CONTRACT_CHECKS)


def test_002_applies_over_valid_rows(empty_schema: str, only_001: Path) -> None:
    for _ in range(3):
        _insert_raw(empty_schema)
    assert apply_migrations(empty_schema, only_001) == ["002"]
    assert _check_constraints(empty_schema) >= CONTRACT_CHECKS
    assert _query(empty_schema, "select count(*) from inspections") == [(3,)]


def test_002_refuses_invalid_rows_with_counts_only(empty_schema: str, only_001: Path) -> None:
    v1 = str(uuid.uuid1())
    _insert_raw(empty_schema, model_version="MODEL_X")
    _insert_raw(empty_schema, inspection_id=v1)
    _insert_raw(empty_schema, inspected_at="infinity")
    # One row breaking two rules counts once in the total.
    _insert_raw(empty_schema, model_version="BAD", received_at="-infinity")
    with pytest.raises(MigrationError) as info:
        apply_migrations(empty_schema, only_001)
    message = str(info.value)
    assert (
        "migration 002: 4 row(s) of inspections violate the new checks (model_version=2, "
        "inspection_id=1, inspected_at=1, received_at=1); fix or delete them before migrating"
    ) in message
    for value in ("MODEL_X", "BAD", v1, "infinity"):
        assert value not in message
    assert _query(empty_schema, "select version from schema_migrations") == [("001",)]
    assert CONTRACT_CHECKS.isdisjoint(_check_constraints(empty_schema))
    assert _query(empty_schema, "select count(*) from inspections") == [(4,)]

    with psycopg.connect(empty_schema, autocommit=True) as conn:
        conn.execute("delete from inspections")
    assert apply_migrations(empty_schema, only_001) == ["002"]
    assert _check_constraints(empty_schema) >= CONTRACT_CHECKS


def test_002_file_run_by_hand_also_refuses_invalid_rows(empty_schema: str, only_001: Path) -> None:
    _insert_raw(empty_schema, inspected_at="infinity")
    with (
        psycopg.connect(empty_schema, autocommit=True) as conn,
        pytest.raises(psycopg.errors.RaiseException, match=r"migration 002: 1 row\(s\)"),
    ):
        conn.execute(CHECKS_SQL.read_text(encoding="utf-8"))
    # One DO block: the refusal leaves no constraint behind, even without a transaction.
    assert CONTRACT_CHECKS.isdisjoint(_check_constraints(empty_schema))


def test_002_keeps_an_existing_constraint_with_the_same_name(
    empty_schema: str, only_001: Path
) -> None:
    with psycopg.connect(empty_schema, autocommit=True) as conn:
        conn.execute(
            "alter table inspections add constraint inspections_model_version_check "
            "check (length(model_version) > 0)"
        )
    assert apply_migrations(empty_schema, only_001) == ["002"]
    (definition,) = _query(
        empty_schema,
        "select pg_get_constraintdef(oid) from pg_constraint "
        "where conrelid = 'inspections'::regclass and conname = 'inspections_model_version_check'",
    )
    assert "length" in definition[0]
    assert _check_constraints(empty_schema) >= CONTRACT_CHECKS
