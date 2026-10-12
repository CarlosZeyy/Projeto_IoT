"""Repository-wide pytest policy for the `db` marker (SPEC-001 §4.3) and shared DB fixtures.

* Without ``TEST_DATABASE_URL``, every test marked ``db`` is skipped.
* With ``CI=true`` and without ``TEST_DATABASE_URL``, the session fails before running any test,
  so CI can never be green with database tests skipped.

The variable comes only from the process environment; ``.env`` is never read here.

Database fixtures (SPEC-003 §4.4), reused by SPEC-004 to SPEC-006:

* ``db_conninfo`` (session): the ``TEST_DATABASE_URL`` conninfo, refused (before any connection)
  when the database name does not contain ``test``;
* ``migrated_db`` (session): resets the ``public`` schema and applies ``infra/migrations``;
* ``clean_db`` (function): truncates ``inspections`` and ``devices`` before the test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

DB_URL_ENV = "TEST_DATABASE_URL"
SKIP_REASON = "TEST_DATABASE_URL not set"
CI_ERROR = "TEST_DATABASE_URL is required when CI=true"
UNSAFE_DB_ERROR = "refusing to use a database whose name does not contain 'test'"


def _database_url() -> str:
    return os.environ.get(DB_URL_ENV, "").strip()


def _running_in_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() in {"true", "1"}


def pytest_configure(config: pytest.Config) -> None:
    if _running_in_ci() and not _database_url():
        raise pytest.UsageError(CI_ERROR)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _database_url():
        return
    skip_db = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if item.get_closest_marker("db") is not None:
            item.add_marker(skip_db)


def _database_name(conninfo: str) -> str:
    """Database name written in the conninfo (URL or key=value); ``""`` if absent or unparsable.

    Only what is written in the string counts (no ``PGDATABASE`` or user-name fallback), so a
    conninfo without an explicit name is refused by the safety guard.
    """
    from psycopg.conninfo import conninfo_to_dict

    try:
        return str(conninfo_to_dict(conninfo).get("dbname") or "")
    except Exception:
        return ""


@pytest.fixture(scope="session")
def db_conninfo() -> str:
    """Conninfo of the disposable test database (``TEST_DATABASE_URL``).

    Safety guard: fails, before any command reaches the server, when the database name does not
    contain ``test``.
    """
    conninfo = _database_url()
    if not conninfo:
        pytest.skip(SKIP_REASON)
    if "test" not in _database_name(conninfo):
        pytest.fail(UNSAFE_DB_ERROR, pytrace=False)
    return conninfo


@pytest.fixture(scope="session")
def migrated_db(db_conninfo: str) -> str:
    """Empty ``public`` schema with every migration applied; returns the conninfo."""
    import psycopg
    from migrate import apply_migrations

    with psycopg.connect(db_conninfo, autocommit=True, prepare_threshold=None) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
    apply_migrations(db_conninfo)
    return db_conninfo


@pytest.fixture
def clean_db(migrated_db: str) -> Iterator[str]:
    """Truncates ``inspections`` and ``devices`` before the test; yields the conninfo."""
    import psycopg

    with psycopg.connect(migrated_db, autocommit=True, prepare_threshold=None) as conn:
        conn.execute("truncate inspections, devices")
    yield migrated_db
