"""Acceptance tests for SPEC-027 section 4.2 (SQLSTATE in the write log, RV-03 of SPEC-005).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. ``test_ca06_*`` covers CA-06; ``test_extra_*`` tests are exploratory.

Only the boundary is replaced (SPEC-027 section 6): ``insert_inspections`` as used in
``qc_api.routers.inspections`` is monkeypatched with a function that raises a client-built psycopg
exception (exceptions without SQLSTATE can only be built on the client; precedent: CA-21 of
SPEC-005). Authentication runs against the real test database (marker ``db``). Keys are generated
at run time; no credential appears as a literal.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

import qc_api.routers.inspections as inspections_router
from qc_api.config import Settings
from qc_api.main import create_app

pytestmark = [pytest.mark.acceptance, pytest.mark.db]

URL_ONE = "/api/v1/inspections"
URL_BATCH = "/api/v1/inspections/batch"
CANNOT_STORE = {"detail": "Value cannot be stored"}
SHA = "a" * 64


def _payload(**overrides: Any) -> dict[str, Any]:
    """``P(id)`` of SPEC-004 section 5: valid ``InspectionCreate`` for ``edge-01``."""
    body: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-001",
        "inspected_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        "object_type": "screw",
        "grade": "fair",
        "grade_score": 2.0,
        "type_confidence": 0.97,
        "grade_confidence": 0.81,
        "needs_review": False,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "latency_ms": 42,
        "source": "live",
    }
    body.update(overrides)
    return body


@dataclass
class Env:
    db: str
    client: TestClient
    key: str
    calls: list[Any]

    def post_one(self, body: dict[str, Any]) -> Any:
        return self.client.post(URL_ONE, json=body, headers={"X-API-Key": self.key})

    def post_batch(self, items: list[dict[str, Any]]) -> Any:
        return self.client.post(URL_BATCH, json={"items": items}, headers={"X-API-Key": self.key})


def _connect(conninfo: str) -> psycopg.Connection:
    return psycopg.connect(conninfo, autocommit=True, prepare_threshold=None)


@pytest.fixture
def env(clean_db: str) -> Iterator[Env]:
    key = secrets.token_urlsafe(32)
    with _connect(clean_db) as conn:
        conn.execute(
            "insert into devices (device_id, api_key_hash) values (%s, %s)",
            ("edge-01", hashlib.sha256(key.encode()).hexdigest()),
        )
    app = create_app(
        Settings(DATABASE_URL=clean_db, READ_API_KEY=secrets.token_urlsafe(32), LOG_LEVEL="DEBUG")
    )
    with TestClient(app) as client:
        yield Env(clean_db, client, key, [])


def _raiser(exc_factory: Callable[[], Exception], calls: list[Any]) -> Callable[..., Any]:
    def fake_insert(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        raise exc_factory()

    return fake_insert


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def _all_log_text(caplog: pytest.LogCaptureFixture) -> str:
    parts = [caplog.text]
    for rec in caplog.records:
        parts.append(rec.getMessage())
        parts.append(repr(rec.args))
        if rec.exc_text:
            parts.append(rec.exc_text)
    return "\n".join(parts)


CASES: list[tuple[str, Callable[[], Exception], str]] = [
    ("integrity-without-sqlstate", lambda: psycopg.IntegrityError("x"), "sqlstate=-"),
    ("data-without-sqlstate", lambda: psycopg.DataError("y"), "sqlstate=-"),
    ("check-violation", lambda: psycopg.errors.CheckViolation(), "sqlstate=23514"),
]


# --------------------------------------------------------------------------- CA-06


def test_ca06_write_log_uses_the_sqlstate_label(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    every_record: list[str] = []
    for case, factory, expected in CASES:
        monkeypatch.setattr(inspections_router, "insert_inspections", _raiser(factory, env.calls))
        caplog.clear()
        calls_before = len(env.calls)

        resp = env.post_one(_payload())

        assert len(env.calls) == calls_before + 1, f"{case}: the replaced function was not used"
        assert resp.status_code == 422, (case, resp.text)
        assert resp.json() == CANNOT_STORE, case
        warnings = _warnings(caplog)
        assert any(expected in m for m in warnings), (case, warnings)
        every_record.extend(r.getMessage() for r in caplog.records)
        assert "sqlstate=None" not in _all_log_text(caplog), case

    assert every_record, "nothing was logged: the checks above would be vacuous"
    assert not any("sqlstate=None" in m for m in every_record)


# --------------------------------------------------------------------------- extras


@pytest.mark.parametrize(("case", "factory", "expected"), CASES, ids=[c[0] for c in CASES])
def test_extra_batch_route_uses_the_same_label(
    env: Env,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case: str,
    factory: Callable[[], Exception],
    expected: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(inspections_router, "insert_inspections", _raiser(factory, env.calls))
    resp = env.post_batch([_payload(), _payload()])
    assert resp.status_code == 422, resp.text
    assert resp.json() == CANNOT_STORE
    assert any(expected in m for m in _warnings(caplog)), _warnings(caplog)
    assert "sqlstate=None" not in _all_log_text(caplog)


def test_extra_write_log_has_no_exception_message_nor_payload(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """SPEC-005 4.5 still holds: route, device_id and SQLSTATE only; no traceback."""
    caplog.set_level(logging.DEBUG)
    marker = "mk-" + secrets.token_hex(8)
    lot = "L-" + secrets.token_hex(4).upper()
    for factory in (
        lambda: psycopg.IntegrityError(marker),
        lambda: psycopg.DataError(marker),
        lambda: psycopg.errors.CheckViolation(marker),
        lambda: psycopg.errors.NumericValueOutOfRange(marker),
    ):
        monkeypatch.setattr(inspections_router, "insert_inspections", _raiser(factory, env.calls))
        caplog.clear()
        resp = env.post_one(_payload(lot_id=lot))
        assert resp.status_code == 422, resp.text
        assert resp.json() == CANNOT_STORE
        text = _all_log_text(caplog)
        assert marker not in text
        assert lot not in text
        assert env.key not in text
        assert "Traceback" not in text
        warnings = _warnings(caplog)
        assert warnings, "no WARNING record"
        assert any("edge-01" in m for m in warnings), warnings
        assert not [r for r in caplog.records if r.exc_info]


def test_extra_numeric_out_of_range_keeps_its_sqlstate(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(
        inspections_router,
        "insert_inspections",
        _raiser(lambda: psycopg.errors.NumericValueOutOfRange(), env.calls),
    )
    resp = env.post_one(_payload())
    assert resp.status_code == 422
    assert any("sqlstate=22003" in m for m in _warnings(caplog)), _warnings(caplog)


def test_extra_last_seen_not_updated_on_refused_write(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        inspections_router,
        "insert_inspections",
        _raiser(lambda: psycopg.IntegrityError("x"), env.calls),
    )
    resp = env.post_one(_payload())
    assert resp.status_code == 422
    with _connect(env.db) as conn:
        row = conn.execute(
            "select last_seen_at from devices where device_id = 'edge-01'"
        ).fetchone()
        count = conn.execute("select count(*) from inspections").fetchone()
    assert row is not None and row[0] is None
    assert count is not None and count[0] == 0
