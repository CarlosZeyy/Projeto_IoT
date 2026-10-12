"""Repository-wide pytest policy for the `db` marker (SPEC-001 §4.3).

* Without ``TEST_DATABASE_URL``, every test marked ``db`` is skipped.
* With ``CI=true`` and without ``TEST_DATABASE_URL``, the session fails before running any test,
  so CI can never be green with database tests skipped.

The variable comes only from the process environment; ``.env`` is never read here.
"""

from __future__ import annotations

import os

import pytest

DB_URL_ENV = "TEST_DATABASE_URL"
SKIP_REASON = "TEST_DATABASE_URL not set"
CI_ERROR = "TEST_DATABASE_URL is required when CI=true"


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
