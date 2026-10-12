"""Fixtures of the qc-api author tests (SPEC-004).

Database fixtures build on ``migrated_db``/``clean_db`` from the root ``conftest.py``. Keys and
fake passwords are generated at run time: no credential appears as a literal (R-03).
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlunsplit

import psycopg
import pytest
from fastapi.testclient import TestClient

from qc_api.auth import hash_api_key
from qc_api.config import Settings
from qc_api.main import create_app

READ_KEY = "r" * 32
SHA = "a" * 64


def closed_port_url(password: str) -> str:
    """URL of a database on a closed local port (the "app without database" of the SPEC)."""
    return urlunsplit(("postgresql", f"u:{password}@127.0.0.1:1", "/x", "", ""))


def make_settings(database_url: str, **overrides: Any) -> Settings:
    return Settings(DATABASE_URL=database_url, READ_API_KEY=READ_KEY, **overrides)


@pytest.fixture
def settings_for() -> Callable[..., Settings]:
    """``Settings(DATABASE_URL=<url>, READ_API_KEY="r"*32, **overrides)``."""
    return make_settings


@pytest.fixture
def fake_password() -> str:
    return "pw" + secrets.token_hex(6)


@pytest.fixture
def no_db_url(fake_password: str) -> str:
    """URL of the "app without database" (closed port, password ``fake_password``)."""
    return closed_port_url(fake_password)


@pytest.fixture
def no_db_settings(no_db_url: str) -> Settings:
    return make_settings(no_db_url)


@pytest.fixture
def make_payload() -> Callable[..., dict[str, Any]]:
    """``P(id)`` of the SPEC: a valid ``InspectionCreate`` body for ``edge-01``, grade ``fair``."""

    def _make(inspection_id: str | None = None, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "inspection_id": inspection_id or str(uuid.uuid4()),
            "device_id": "edge-01",
            "lot_id": "L-001",
            "inspected_at": "2026-10-01T12:00:00-03:00",
            "object_type": "screw",
            "grade": "fair",
            "grade_score": 2.1,
            "type_confidence": 0.97,
            "grade_confidence": 0.66,
            "needs_review": False,
            "model_version": "partqc-mnv3-v1",
            "model_sha256": SHA,
            "latency_ms": 120,
            "source": "live",
        }
        body.update(overrides)
        return body

    return _make


@pytest.fixture
def device_keys(clean_db: str) -> dict[str, str]:
    """``edge-01`` and ``sim-01`` registered by hash; returns ``{device_id: key}``."""
    keys = {"edge-01": secrets.token_urlsafe(32), "sim-01": secrets.token_urlsafe(32)}
    with psycopg.connect(clean_db, autocommit=True, prepare_threshold=None) as conn:
        for device_id, key in keys.items():
            conn.execute(
                "insert into devices (device_id, api_key_hash) values (%s, %s)",
                (device_id, hash_api_key(key)),
            )
    return keys


@pytest.fixture
def client(clean_db: str, device_keys: dict[str, str]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(clean_db))) as test_client:
        yield test_client


@pytest.fixture
def db(clean_db: str) -> Iterator[psycopg.Connection]:
    """Autocommit connection to inspect the test database."""
    with psycopg.connect(clean_db, autocommit=True, prepare_threshold=None) as conn:
        yield conn
