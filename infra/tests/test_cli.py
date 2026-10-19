"""CLI of infra/migrate.py through a subprocess (SPEC-003 §4.2). Database tests are marked `db`."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from migrate import DEFAULT_DIR, load_migrations

SCRIPT = Path(__file__).resolve().parents[1] / "migrate.py"
SECRET = "s3cr3t-pw"


def _run(
    *args: str, env_updates: dict[str, str | None] | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for key, value in (env_updates or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_missing_url_exits_2_and_names_the_variable() -> None:
    result = _run(env_updates={"DATABASE_URL": None})
    assert result.returncode == 2
    assert "DATABASE_URL" in result.stdout + result.stderr


def test_blank_url_counts_as_missing() -> None:
    result = _run(env_updates={"DATABASE_URL": "  "})
    assert result.returncode == 2
    assert "DATABASE_URL" in result.stdout + result.stderr


def test_invalid_argument_exits_2() -> None:
    result = _run("--no-such-flag", env_updates={"DATABASE_URL": None})
    assert result.returncode == 2


def test_malformed_url_exits_2_without_echoing_it() -> None:
    result = _run("--database-url", f"host=x password={SECRET} garbage")
    assert result.returncode == 2
    assert SECRET not in result.stdout + result.stderr


def test_missing_migrations_dir_exits_2(tmp_path: Path) -> None:
    result = _run(
        "--database-url",
        "postgresql://u@127.0.0.1:1/x",
        "--migrations-dir",
        str(tmp_path / "nope"),
    )
    assert result.returncode == 2


@pytest.mark.parametrize("extra", [[], ["--status"]])
def test_closed_port_exits_1_without_leaking_password(extra: list[str]) -> None:
    url = "postgresql://u:s3cr3t-pw@127.0.0.1:1/x"
    result = _run("--database-url", url, *extra)
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert SECRET not in output
    assert url not in output
    assert "127.0.0.1:1" in output
    assert "OperationalError" in output


def test_password_from_env_is_not_leaked() -> None:
    result = _run(env_updates={"DATABASE_URL": "postgresql://u:s3cr3t-pw@127.0.0.1:1/x"})
    assert result.returncode == 1
    assert SECRET not in result.stdout + result.stderr


def _reset(conninfo: str) -> None:
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")


@pytest.fixture
def empty_schema(migrated_db: str):
    _reset(migrated_db)
    yield migrated_db
    _reset(migrated_db)
    from migrate import apply_migrations

    apply_migrations(migrated_db)


@pytest.mark.db
def test_cli_apply_then_status(empty_schema: str) -> None:
    status_before = _run("--status", env_updates={"DATABASE_URL": empty_schema})
    assert status_before.returncode == 0, status_before.stderr
    assert "001 pending" in status_before.stdout

    applied = _run(env_updates={"DATABASE_URL": empty_schema})
    assert applied.returncode == 0, applied.stderr
    assert "applied migration 001" in applied.stdout
    assert "applied migration 002" in applied.stdout

    again = _run("--database-url", empty_schema)
    assert again.returncode == 0, again.stderr
    assert "no pending migrations" in again.stdout

    status_after = _run("--database-url", empty_schema, "--status")
    assert status_after.returncode == 0, status_after.stderr
    assert "001 applied" in status_after.stdout
    assert "002 applied" in status_after.stdout
    assert "0 pending" in status_after.stdout


@pytest.mark.db
def test_cli_status_does_not_create_control_table(empty_schema: str) -> None:
    result = _run("--database-url", empty_schema, "--status")
    assert result.returncode == 0, result.stderr
    with psycopg.connect(empty_schema) as conn:
        assert conn.execute("select to_regclass('schema_migrations')").fetchone() == (None,)


@pytest.mark.db
def test_cli_checksum_mismatch_exits_1(migrated_db: str, tmp_path: Path) -> None:
    changed = DEFAULT_DIR.joinpath("001_init.sql").read_text(encoding="utf-8") + "-- changed\n"
    (tmp_path / "001_init.sql").write_text(changed, encoding="utf-8")
    for extra in ([], ["--status"]):
        result = _run("--database-url", migrated_db, "--migrations-dir", str(tmp_path), *extra)
        assert result.returncode == 1
        assert "checksum mismatch for 001" in result.stderr


@pytest.mark.db
def test_cli_failed_migration_exits_1(migrated_db: str, tmp_path: Path) -> None:
    # Copies of every applied migration, plus a broken one with the next number.
    migrations = load_migrations()
    for migration in migrations:
        (tmp_path / migration.filename).write_bytes(migration.path.read_bytes())
    broken = f"{int(migrations[-1].version) + 1:03d}"
    (tmp_path / f"{broken}_broken.sql").write_text("select from nao_existe;\n", encoding="utf-8")
    result = _run("--database-url", migrated_db, "--migrations-dir", str(tmp_path))
    assert result.returncode == 1
    assert f"migration {broken}" in result.stderr
