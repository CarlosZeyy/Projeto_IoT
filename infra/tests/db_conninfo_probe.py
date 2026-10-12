"""Probe run only by ``test_db_fixtures.py`` in a subprocess (not collected by the normal run).

It must never touch the database: the URLs used point to a closed port.
"""

from __future__ import annotations

import pytest


@pytest.mark.db
def test_probe_db_conninfo(db_conninfo: str) -> None:
    assert "test" in db_conninfo
