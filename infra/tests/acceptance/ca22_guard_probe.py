"""Probe for SPEC-003 CA-22 (not collected by the normal run: the name does not match test_*.py).

``test_spec_003.py`` runs this file in a pytest subprocess, with ``TEST_DATABASE_URL`` pointing
at a database whose name does not contain ``test`` and a local TCP listener that counts
connection attempts.
"""

from __future__ import annotations


def test_probe_db_conninfo(db_conninfo: str) -> None:
    assert db_conninfo


def test_probe_clean_db(clean_db: str) -> None:
    assert clean_db
