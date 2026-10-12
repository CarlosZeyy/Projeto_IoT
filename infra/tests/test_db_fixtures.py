"""Shared DB fixtures of the root conftest.py (SPEC-003 §4.4).

The safety guard of ``db_conninfo`` is exercised in a pytest subprocess that runs only the probe
file ``db_conninfo_probe.py`` (its name does not match ``test_*.py``, so the normal collection
ignores it). The probe URLs point to a closed port: the guard must decide without connecting.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).resolve().parent / "db_conninfo_probe.py"
GUARD_MESSAGE = "refusing to use a database whose name does not contain 'test'"


def _run_probe(url: str | None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("CI", None)
    if url is None:
        env.pop("TEST_DATABASE_URL", None)
    else:
        env["TEST_DATABASE_URL"] = url
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", str(PROBE)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres@127.0.0.1:1/partqc_prod",
        "postgresql://postgres@127.0.0.1:1/postgres",
        "postgresql://postgres@127.0.0.1:1",
        "host=127.0.0.1 port=1 dbname=partqc_prod",
    ],
)
def test_guard_refuses_database_without_test_in_name(url: str) -> None:
    result = _run_probe(url)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert GUARD_MESSAGE in output
    assert "1 error" in output


@pytest.mark.parametrize(
    "url",
    ["postgresql://postgres@127.0.0.1:1/partqc_test", "host=127.0.0.1 port=1 dbname=test_x"],
)
def test_guard_accepts_test_database_without_connecting(url: str) -> None:
    result = _run_probe(url)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_fixture_skips_without_url() -> None:
    result = _run_probe(None)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TEST_DATABASE_URL not set" in result.stdout


@pytest.mark.db
def test_migrated_db_has_tables(migrated_db: str) -> None:
    with psycopg.connect(migrated_db) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "select table_name from information_schema.tables where table_schema = 'public'"
            )
        }
    assert {"devices", "inspections", "schema_migrations"} <= names


@pytest.mark.db
def test_clean_db_truncates(migrated_db: str, request: pytest.FixtureRequest) -> None:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute(
            "insert into devices (device_id, api_key_hash) values ('fixture-01', %s)",
            ("f" * 64,),
        )
        assert conn.execute("select count(*) from devices").fetchone()[0] >= 1
    clean = request.getfixturevalue("clean_db")
    assert clean == migrated_db
    with psycopg.connect(clean) as conn:
        assert conn.execute("select count(*) from devices").fetchone() == (0,)
        assert conn.execute("select count(*) from inspections").fetchone() == (0,)
