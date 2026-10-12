"""Smoke test of the PostgreSQL used by the `db` tests (SPEC-001 §4.3)."""

from __future__ import annotations

import os

import psycopg
import pytest


@pytest.mark.db
def test_select_one() -> None:
    with psycopg.connect(os.environ["TEST_DATABASE_URL"], connect_timeout=10) as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)
