"""Acceptance tests for SPEC-004 (qc-api: ingestion and device authentication).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test per CA (``test_caNN_*``); ``test_extra_*`` tests are exploratory edge
cases around SPEC-004 section 4 that no CA spells out.

Common context (SPEC-004 section 5): migrated test database (``migrated_db``/``clean_db`` from
SPEC-003), devices ``edge-01`` (key ``KE``) and ``sim-01`` (key ``KS``) registered by hash, and
the app built with ``create_app(Settings(DATABASE_URL=<test>, READ_API_KEY="r"*32))`` inside a
``TestClient`` block (lifespan active). The "app without database" points to a closed local
port. Keys and passwords are built at run time, never written as literals (R-03).
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlunsplit

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import qc_api
import qc_contracts
from qc_api.auth import hash_api_key
from qc_api.config import Settings
from qc_api.main import create_app

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "register_device.py"

READ_KEY = "r" * 32
URL_ONE = "/api/v1/inspections"
URL_BATCH = "/api/v1/inspections/batch"
URL_HEALTH = "/api/v1/health"

UNAUTHORIZED = {"detail": "Missing or invalid API key"}
FORBIDDEN = {"detail": "device_id does not match API key"}
TOO_LARGE = {"detail": "Request body too large"}
DB_DOWN = {"detail": "Database unavailable"}
CANNOT_STORE = {"detail": "Value cannot be stored"}

MAX_BODY = 262_144
NO_DB_PASSWORD = "p" + "w"  # the fake password of the SPEC, assembled at run time


# --------------------------------------------------------------------------- helpers


def no_db_url(password: str = NO_DB_PASSWORD) -> str:
    """URL of the "app without database": user ``u``, closed port 1 on 127.0.0.1, db ``x``."""
    return urlunsplit(("postgresql", f"u:{password}@127.0.0.1:1", "/x", "", ""))


def payload(inspection_id: str | None = None, **overrides: Any) -> dict[str, Any]:
    """``P(id)``: a valid ``InspectionCreate`` body for ``edge-01`` with grade ``fair``."""
    body: dict[str, Any] = {
        "inspection_id": inspection_id or str(uuid.uuid4()),
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
        "model_sha256": "a" * 64,
        "latency_ms": 42,
        "source": "live",
    }
    body.update(overrides)
    return body


def key_header(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


def new_id() -> str:
    return str(uuid.uuid4())


def connect(conninfo: str) -> psycopg.Connection:
    return psycopg.connect(conninfo, autocommit=True, prepare_threshold=None)


def count_rows(conninfo: str) -> int:
    with connect(conninfo) as conn:
        return conn.execute("select count(*) from inspections").fetchone()[0]


def ids_in_table(conninfo: str) -> set[str]:
    with connect(conninfo) as conn:
        rows = conn.execute("select inspection_id::text from inspections").fetchall()
    return {r[0] for r in rows}


def last_seen(conninfo: str, device_id: str) -> datetime | None:
    with connect(conninfo) as conn:
        row = conn.execute(
            "select last_seen_at from devices where device_id = %s", (device_id,)
        ).fetchone()
    assert row is not None, device_id
    return row[0]


def register(conninfo: str, device_id: str, key: str) -> None:
    with connect(conninfo) as conn:
        conn.execute(
            "insert into devices (device_id, api_key_hash) values (%s, %s)",
            (device_id, hashlib.sha256(key.encode()).hexdigest()),
        )


def assert_no_traceback(resp: Any) -> None:
    assert "Traceback" not in resp.text, resp.text


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Every captured record: formatted text, message, raw args and exception text."""
    parts: list[str] = [caplog.text]
    for rec in caplog.records:
        parts.append(rec.getMessage())
        parts.append(repr(rec.args))
        if rec.exc_text:
            parts.append(rec.exc_text)
        if rec.exc_info and rec.exc_info[1] is not None:
            parts.append(repr(rec.exc_info[1]))
    return "\n".join(parts)


class Env:
    """Database, keys and client of the common context."""

    def __init__(self, conninfo: str, client: TestClient, ke: str, ks: str) -> None:
        self.db = conninfo
        self.client = client
        self.ke = ke
        self.ks = ks

    def post(self, body: Any, key: str | None = None, url: str = URL_ONE) -> Any:
        headers = key_header(key) if key is not None else {}
        return self.client.post(url, json=body, headers=headers)


@pytest.fixture
def env(clean_db: str) -> Iterator[Env]:
    ke = secrets.token_urlsafe(32)
    ks = secrets.token_urlsafe(32)
    register(clean_db, "edge-01", ke)
    register(clean_db, "sim-01", ks)
    app = create_app(Settings(DATABASE_URL=clean_db, READ_API_KEY=READ_KEY))
    with TestClient(app) as client:
        yield Env(clean_db, client, ke, ks)


@pytest.fixture
def no_db_client() -> Iterator[TestClient]:
    app = create_app(Settings(DATABASE_URL=no_db_url(), READ_API_KEY=READ_KEY))
    with TestClient(app) as client:
        yield client


def run_script(*args: str, database_url: str | None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def parse_key(result: subprocess.CompletedProcess[str]) -> str:
    """The key of a successful run: stdout is exactly one ``DEVICE_API_KEY=<k>`` line."""
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 1, result.stdout
    assert result.stdout in (lines[0], lines[0] + "\n"), repr(result.stdout)
    m = re.fullmatch(r"DEVICE_API_KEY=(\S+)", lines[0])
    assert m, lines[0]
    return m.group(1)


# --------------------------------------------------------------------------- CA-01


@pytest.mark.db
def test_ca01_health_ok(env: Env) -> None:
    resp = env.client.get(URL_HEALTH)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "status": "ok",
        "db": "ok",
        "api_version": "0.1.0",
        "contract_version": qc_contracts.__version__,
    }


# --------------------------------------------------------------------------- CA-02


@pytest.mark.db
def test_ca02_starts_without_database_and_health_is_503() -> None:
    start = time.monotonic()
    app = create_app(Settings(DATABASE_URL=no_db_url(), READ_API_KEY=READ_KEY))
    with TestClient(app) as client:
        resp = client.get(URL_HEALTH)
    elapsed = time.monotonic() - start
    assert resp.status_code == 503, resp.text
    assert resp.json() == {
        "status": "degraded",
        "db": "error",
        "api_version": qc_api.__version__,
        "contract_version": qc_contracts.__version__,
    }
    assert elapsed < 10, elapsed


# --------------------------------------------------------------------------- CA-03


@pytest.mark.db
def test_ca03_create_stores_utc_and_server_fields(env: Env) -> None:
    x = new_id()
    resp = env.post(payload(x, inspected_at="2026-10-01T12:00:00-03:00"), env.ke)
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"inspection_id": x, "status": "created"}
    with connect(env.db) as conn:
        rows = conn.execute(
            "select inspection_id::text, inspected_at, received_at, is_defective from inspections"
        ).fetchall()
    assert len(rows) == 1, rows
    rid, inspected_at, received_at, is_defective = rows[0]
    assert rid == x
    assert inspected_at == datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
    assert received_at is not None
    assert is_defective is False


# --------------------------------------------------------------------------- CA-04


@pytest.mark.db
def test_ca04_duplicates_do_not_change_original(env: Env) -> None:
    x = new_id()
    assert env.post(payload(x), env.ke).status_code == 201
    for i in range(3):
        body = payload(x, lot_id="L-999") if i == 2 else payload(x)
        resp = env.post(body, env.ke)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"inspection_id": x, "status": "duplicate"}
    with connect(env.db) as conn:
        rows = conn.execute("select lot_id from inspections").fetchall()
    assert rows == [("L-001",)]


# --------------------------------------------------------------------------- CA-05


@pytest.mark.db
def test_ca05_invalid_keys_are_401(env: Env) -> None:
    x = new_id()
    wrong = "wrong-" + secrets.token_hex(4)
    for key in (None, wrong, READ_KEY, "k" * 300):
        resp = env.post(payload(x), key)
        assert resp.status_code == 401, (key and len(key), resp.text)
        assert resp.json() == UNAUTHORIZED
    assert count_rows(env.db) == 0


# --------------------------------------------------------------------------- CA-06


@pytest.mark.db
def test_ca06_auth_before_validation(env: Env) -> None:
    body = payload(new_id())
    del body["lot_id"]
    resp = env.post(body)
    assert resp.status_code == 401, resp.text
    assert resp.json() == UNAUTHORIZED


# --------------------------------------------------------------------------- CA-07


@pytest.mark.db
def test_ca07_device_mismatch_is_403(env: Env) -> None:
    resp = env.post(payload(new_id(), device_id="sim-01"), env.ke)
    assert resp.status_code == 403, resp.text
    assert resp.json() == FORBIDDEN
    assert count_rows(env.db) == 0
    assert last_seen(env.db, "edge-01") is None
    assert last_seen(env.db, "sim-01") is None


# --------------------------------------------------------------------------- CA-08


@pytest.mark.db
def test_ca08_invalid_bodies_are_422(env: Env) -> None:
    x = new_id()
    no_lot = payload(x)
    del no_lot["lot_id"]
    bodies: list[dict[str, Any]] = [
        payload(x, image="AAAA"),
        payload(x, object_type="unknown", grade="fair"),
        payload(x, inspected_at="2026-10-01T12:00:00"),
        no_lot,
        payload(x, latency_ms=2_147_483_648),
    ]
    for body in bodies:
        resp = env.post(body, env.ke)
        assert resp.status_code == 422, (body, resp.text)
        assert_no_traceback(resp)
    resp = env.client.post(
        URL_ONE,
        content=b"not json",
        headers={**key_header(env.ke), "Content-Type": "application/json"},
    )
    assert resp.status_code == 422, resp.text
    assert_no_traceback(resp)
    assert count_rows(env.db) == 0


# --------------------------------------------------------------------------- CA-09


def padded_body(inspection_id: str, size: int) -> bytes:
    """Valid JSON of ``P(id)`` padded with trailing whitespace to exactly ``size`` bytes."""
    raw = json.dumps(payload(inspection_id)).encode()
    assert len(raw) < size
    return raw + b" " * (size - len(raw))


@pytest.mark.db
def test_ca09_body_limit(env: Env) -> None:
    headers = {**key_header(env.ke), "Content-Type": "application/json"}
    a = new_id()
    exact = padded_body(a, MAX_BODY)
    assert len(exact) == 262_144
    resp = env.client.post(URL_ONE, content=exact, headers=headers)
    assert resp.status_code != 413, resp.text
    assert resp.status_code == 201, resp.text

    b = new_id()
    resp = env.client.post(URL_ONE, content=padded_body(b, MAX_BODY + 1), headers=headers)
    assert resp.status_code == 413, resp.text
    assert resp.json() == TOO_LARGE

    small = json.dumps(payload(b)).encode()
    resp = env.client.post(URL_ONE, content=small, headers={**headers, "Content-Length": "300000"})
    assert resp.status_code == 413, resp.text
    assert resp.json() == TOO_LARGE

    big = padded_body(b, 300_000)

    def chunks() -> Iterator[bytes]:
        for i in range(0, len(big), 16_384):
            yield big[i : i + 16_384]

    resp = env.client.post(URL_ONE, content=chunks(), headers=headers)
    assert resp.status_code == 413, resp.text
    assert resp.json() == TOO_LARGE

    assert ids_in_table(env.db) == {a}


# --------------------------------------------------------------------------- CA-10


@pytest.mark.db
def test_ca10_last_seen_only_on_success(env: Env) -> None:
    assert last_seen(env.db, "edge-01") is None
    x = new_id()
    before = datetime.now(UTC)
    resp = env.post(payload(x), env.ke)
    after = datetime.now(UTC)
    assert resp.status_code == 201, resp.text
    first = last_seen(env.db, "edge-01")
    assert first is not None
    assert before <= first <= after, (before, first, after)

    time.sleep(0.01)
    resp = env.post(payload(x), env.ke)
    assert resp.status_code == 200, resp.text
    second = last_seen(env.db, "edge-01")
    assert second is not None
    assert second >= first
    assert second > first, "a duplicate (200) must update last_seen_at again"

    assert env.post(payload(new_id()), "wrong-" + secrets.token_hex(4)).status_code == 401
    assert env.post(payload(new_id()), None).status_code == 401
    assert env.post(payload(new_id(), device_id="sim-01"), env.ke).status_code == 403
    assert env.post(payload(new_id(), type_confidence=2), env.ke).status_code == 422
    assert last_seen(env.db, "edge-01") == second
    assert last_seen(env.db, "sim-01") is None


# --------------------------------------------------------------------------- CA-11


@pytest.mark.db
def test_ca11_batch_created_in_order(env: Env) -> None:
    a, b, c = new_id(), new_id(), new_id()
    resp = env.post({"items": [payload(a), payload(b), payload(c)]}, env.ke, URL_BATCH)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "results": [
            {"inspection_id": a, "status": "created"},
            {"inspection_id": b, "status": "created"},
            {"inspection_id": c, "status": "created"},
        ]
    }
    assert ids_in_table(env.db) == {a, b, c}


# --------------------------------------------------------------------------- CA-12


@pytest.mark.db
def test_ca12_batch_duplicates_inside_and_outside(env: Env) -> None:
    a, b = new_id(), new_id()
    assert env.post(payload(a), env.ke).status_code == 201
    resp = env.post({"items": [payload(b), payload(a), payload(b)]}, env.ke, URL_BATCH)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "results": [
            {"inspection_id": b, "status": "created"},
            {"inspection_id": a, "status": "duplicate"},
            {"inspection_id": b, "status": "duplicate"},
        ]
    }
    assert count_rows(env.db) == 2


# --------------------------------------------------------------------------- CA-13


@pytest.mark.db
def test_ca13_invalid_batch_is_422_and_writes_nothing(env: Env) -> None:
    items = [payload(new_id()), payload(new_id(), type_confidence=2), payload(new_id())]
    resp = env.post({"items": items}, env.ke, URL_BATCH)
    assert resp.status_code == 422, resp.text
    assert count_rows(env.db) == 0

    resp = env.post({"items": []}, env.ke, URL_BATCH)
    assert resp.status_code == 422, resp.text
    resp = env.post({"items": [payload(new_id()) for _ in range(101)]}, env.ke, URL_BATCH)
    assert resp.status_code == 422, resp.text
    assert count_rows(env.db) == 0


# --------------------------------------------------------------------------- CA-14


@pytest.mark.db
def test_ca14_batch_with_foreign_device_is_403(env: Env) -> None:
    items = [payload(new_id()), payload(new_id()), payload(new_id(), device_id="sim-01")]
    resp = env.post({"items": items}, env.ke, URL_BATCH)
    assert resp.status_code == 403, resp.text
    assert resp.json() == FORBIDDEN
    assert count_rows(env.db) == 0


# --------------------------------------------------------------------------- CA-15


@pytest.mark.db
def test_ca15_concurrent_same_id_creates_one_row(env: Env) -> None:
    def race(x: str) -> tuple[list[int], list[BaseException]]:
        barrier = threading.Barrier(2)
        statuses: list[int] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def send() -> None:
            try:
                barrier.wait(timeout=10)
                resp = env.post(payload(x), env.ke)
                with lock:
                    statuses.append(resp.status_code)
            except BaseException as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=send) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        return statuses, errors

    ids = [new_id() for _ in range(10)]
    for x in ids:
        statuses, errors = race(x)
        assert not errors, errors
        assert sorted(statuses) == [200, 201], (x, statuses)
    with connect(env.db) as conn:
        rows = conn.execute(
            "select inspection_id::text, count(*) from inspections group by 1"
        ).fetchall()
    assert dict(rows) == dict.fromkeys(ids, 1)


# --------------------------------------------------------------------------- CA-16


@pytest.mark.db
def test_ca16_write_without_database_is_503(no_db_client: TestClient) -> None:
    any_key = secrets.token_urlsafe(32)
    resp = no_db_client.post(URL_ONE, json=payload(new_id()), headers=key_header(any_key))
    assert resp.status_code == 503, resp.text
    assert resp.json() == DB_DOWN


# --------------------------------------------------------------------------- CA-17


def test_ca17_no_cors_headers(no_db_client: TestClient) -> None:
    origin = {"Origin": "https://evil.example"}
    resp = no_db_client.options(
        URL_ONE, headers={**origin, "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in resp.headers, dict(resp.headers)
    resp = no_db_client.get(URL_HEALTH, headers=origin)
    assert "access-control-allow-origin" not in resp.headers, dict(resp.headers)


# --------------------------------------------------------------------------- CA-18


@pytest.mark.db
@pytest.mark.parametrize("log_level", [None, "DEBUG"])
def test_ca18_logs_have_no_secrets(
    clean_db: str, caplog: pytest.LogCaptureFixture, log_level: str | None
) -> None:
    caplog.set_level(logging.DEBUG)
    extra = {"LOG_LEVEL": log_level} if log_level else {}
    ke = secrets.token_urlsafe(32)
    register(clean_db, "edge-01", ke)

    no_db = create_app(Settings(DATABASE_URL=no_db_url(), READ_API_KEY=READ_KEY, **extra))
    with TestClient(no_db):
        time.sleep(0.5)  # let the pool try (and fail) to connect in the background

    app = create_app(Settings(DATABASE_URL=clean_db, READ_API_KEY=READ_KEY, **extra))
    bad = "bad-" + secrets.token_hex(8)
    with TestClient(app) as client:
        assert (
            client.post(URL_ONE, json=payload(new_id()), headers=key_header(ke)).status_code == 201
        )
        assert client.post(URL_ONE, json=payload(new_id())).status_code == 401
        assert (
            client.post(URL_ONE, json=payload(new_id()), headers=key_header(bad)).status_code == 401
        )

    assert caplog.records, "nothing was logged: the check below would be vacuous"
    text = log_text(caplog)
    for secret in (ke, hash_api_key(ke), NO_DB_PASSWORD, READ_KEY, bad, hash_api_key(bad)):
        assert secret not in text, secret[:4]


# --------------------------------------------------------------------------- CA-19


def test_ca19_openapi_only_json_and_docs(no_db_client: TestClient) -> None:
    spec = no_db_client.get("/openapi.json").json()
    paths = spec["paths"]
    for route in (URL_ONE, URL_BATCH):
        content = paths[route]["post"]["requestBody"]["content"]
        assert set(content) == {"application/json"}, (route, content)
    assert "multipart/form-data" not in json.dumps(spec)
    for route, ops in paths.items():
        for op in ops.values():
            body = op.get("requestBody", {}).get("content", {})
            assert "multipart/form-data" not in body, route
    assert no_db_client.get("/docs").status_code == 200


# --------------------------------------------------------------------------- CA-20


def test_ca20_settings_validation_hides_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATABASE_URL", "READ_API_KEY", "MAX_BODY_BYTES", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    url = no_db_url("pw" + secrets.token_hex(6))
    short = "s" * 31
    with pytest.raises(ValidationError) as exc:
        Settings(DATABASE_URL=url, READ_API_KEY=short)
    msg = str(exc.value)
    assert short not in msg
    assert url not in msg
    assert "READ_API_KEY" in msg

    long_key = "q" + secrets.token_hex(20)
    with pytest.raises(ValidationError) as exc:
        Settings(READ_API_KEY=long_key)
    msg = str(exc.value)
    assert long_key not in msg
    assert "DATABASE_URL" in msg


# --------------------------------------------------------------------------- CA-21


@pytest.mark.db
def test_ca21_register_device(env: Env) -> None:
    result = run_script("--device-id", "lab-02", database_url=env.db)
    k = parse_key(result)
    assert len(k) >= 43
    assert k not in result.stderr
    with connect(env.db) as conn:
        row = conn.execute(
            "select api_key_hash, d::text from devices d where device_id = 'lab-02'"
        ).fetchone()
        everything = "\n".join(r[0] for r in conn.execute("select d::text from devices d"))
    assert row is not None
    assert row[0] == hashlib.sha256(k.encode()).hexdigest()
    assert k not in row[1]
    assert k not in everything
    resp = env.post(payload(new_id(), device_id="lab-02"), k)
    assert resp.status_code == 201, resp.text


# --------------------------------------------------------------------------- CA-22


@pytest.mark.db
def test_ca22_rotate(env: Env) -> None:
    def lab02_hash() -> str:
        with connect(env.db) as conn:
            return conn.execute(
                "select api_key_hash from devices where device_id = 'lab-02'"
            ).fetchone()[0]

    k1 = parse_key(run_script("--device-id", "lab-02", database_url=env.db))
    h1 = lab02_hash()

    again = run_script("--device-id", "lab-02", database_url=env.db)
    assert again.returncode == 1, (again.stdout, again.stderr)
    assert "DEVICE_API_KEY=" not in again.stdout
    assert lab02_hash() == h1

    k2 = parse_key(run_script("--rotate", "--device-id", "lab-02", database_url=env.db))
    assert k2 != k1
    assert lab02_hash() == hashlib.sha256(k2.encode()).hexdigest()
    resp = env.post(payload(new_id(), device_id="lab-02"), k1)
    assert resp.status_code == 401, resp.text
    assert resp.json() == UNAUTHORIZED
    resp = env.post(payload(new_id(), device_id="lab-02"), k2)
    assert resp.status_code == 201, resp.text


# --------------------------------------------------------------------------- CA-23


@pytest.mark.db
def test_ca23_script_errors(clean_db: str) -> None:
    def devices() -> list[tuple]:
        with connect(clean_db) as conn:
            return conn.execute("select * from devices order by device_id").fetchall()

    before = devices()
    cases = [
        (["--rotate", "--device-id", "ghost-01"], clean_db, 1),
        (["--device-id", "Edge_01"], clean_db, 2),
        (["--device-id", "edge-01\n"], clean_db, 2),
        (["--device-id", "edge-01"], None, 2),
    ]
    for args, url, code in cases:
        result = run_script(*args, database_url=url)
        assert result.returncode == code, (args, result.returncode, result.stderr)
        assert "DEVICE_API_KEY=" not in result.stdout, args
        assert devices() == before, args


# --------------------------------------------------------------------------- CA-24


@pytest.mark.db
def test_ca24_latency_limits(env: Env) -> None:
    assert qc_contracts.MAX_LATENCY_MS == 2_147_483_647
    x = new_id()
    resp = env.post(payload(x, latency_ms=qc_contracts.MAX_LATENCY_MS), env.ke)
    assert resp.status_code == 201, resp.text
    with connect(env.db) as conn:
        assert conn.execute("select latency_ms from inspections").fetchall() == [(2_147_483_647,)]

    a, b = new_id(), new_id()
    resp = env.post(
        {"items": [payload(a), payload(b, latency_ms=2_147_483_648)]}, env.ke, URL_BATCH
    )
    assert resp.status_code == 422, resp.text
    assert_no_traceback(resp)
    assert ids_in_table(env.db) == {x}


# --------------------------------------------------------------------------- CA-25


@pytest.mark.db
def test_ca25_float4_underflow_is_422(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    x = new_id()
    resp = env.post(payload(x, grade_score=1e-50), env.ke)
    assert resp.status_code == 422, resp.text
    assert resp.json() == CANNOT_STORE

    a, b = new_id(), new_id()
    resp = env.post({"items": [payload(a), payload(b, type_confidence=5e-324)]}, env.ke, URL_BATCH)
    assert resp.status_code == 422, resp.text
    assert resp.json() == CANNOT_STORE

    assert count_rows(env.db) == 0
    assert last_seen(env.db, "edge-01") is None
    text = log_text(caplog)
    assert "1e-50" not in text
    assert "5e-324" not in text

    y = new_id()
    resp = env.post(payload(y, type_confidence=1e-40), env.ke)
    assert resp.status_code == 201, resp.text
    assert ids_in_table(env.db) == {y}


# --------------------------------------------------------------------------- CA-26


@pytest.mark.db
def test_ca26_huge_json_integer_is_4xx(env: Env) -> None:
    x = new_id()
    text = json.dumps(payload(x, latency_ms=424242))
    assert text.count("424242") == 1
    body = text.replace("424242", "9" * 5000).encode()
    assert len(body) < MAX_BODY
    resp = env.client.post(
        URL_ONE,
        content=body,
        headers={**key_header(env.ke), "Content-Type": "application/json"},
    )
    assert resp.status_code in (400, 422), resp.text
    assert_no_traceback(resp)
    assert count_rows(env.db) == 0


# --------------------------------------------------------------------------- CA-27

SPEC022 = "tests/acceptance/test_spec_022.py"
SPEC023_CONTRACTS = "packages/contracts/tests/acceptance/test_spec_023.py"
SPEC002_CONTRACTS = "packages/contracts/tests/acceptance/test_spec_002.py"
SPEC002_PREPROCESS = "packages/preprocess/tests/acceptance/test_spec_002.py"
SPEC023_PREPROCESS = "packages/preprocess/tests/acceptance/test_spec_023.py"
SPEC024_PREPROCESS = "packages/preprocess/tests/acceptance/test_spec_024.py"
SPEC026_CONTRACTS = "packages/contracts/tests/acceptance/test_spec_026.py"

# Tests collected per file on `main` (dad1880), measured with `pytest --collect-only -q`.
MAIN_COUNTS = {
    SPEC022: 39,
    SPEC023_CONTRACTS: 23,
    SPEC002_CONTRACTS: 165,
    SPEC002_PREPROCESS: 50,
    SPEC023_PREPROCESS: 36,
    SPEC024_PREPROCESS: 29,
}
REMOVED = {
    SPEC022: ("test_ca15_ruff_and_full_suite_without_ci_and_db_url", "CA-15"),
    SPEC023_CONTRACTS: ("test_ca13_ruff_and_full_suite", "CA-13"),
}


def collect(*files: str) -> tuple[subprocess.CompletedProcess[str], dict[str, list[str]]]:
    """``pytest --collect-only -q`` on explicit files (never the whole suite, section 10)."""
    env = dict(os.environ)
    for key in ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST", "PYTEST_PLUGINS"):
        env.pop(key, None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *files],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    per_file: dict[str, list[str]] = {f: [] for f in files}
    for line in result.stdout.splitlines():
        path, sep, rest = line.partition("::")
        if sep and path in per_file:
            per_file[path].append(rest)
    return result, per_file


def _test_functions(path: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
    }


def test_ca27_meta_tests_removed() -> None:
    result, per_file = collect(SPEC022, SPEC023_CONTRACTS)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out[-4000:]
    for path, (removed, ca) in REMOVED.items():
        assert removed not in out, removed
        assert removed not in _test_functions(path), removed
        assert len(per_file[path]) == MAIN_COUNTS[path] - 1, (path, len(per_file[path]))
        collected = {c.split("[", 1)[0] for c in per_file[path]}
        assert collected == _test_functions(path), path
        comment = (
            f"# {ca}: checked by CI and by the test-report, not by a test "
            "(docs/architecture.md section 10)."
        )
        lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
        assert lines.count(comment) == 1, (path, comment)


# --------------------------------------------------------------------------- CA-28

# Packages whose version each file of the table of section 3.1 verified before the migration.
VERSION_FILES = {
    SPEC002_PREPROCESS: {"qc_preprocess"},
    SPEC023_PREPROCESS: {"qc_preprocess", "qc_contracts"},
    SPEC024_PREPROCESS: {"qc_preprocess", "qc_contracts"},
    SPEC002_CONTRACTS: {"qc_contracts"},
    SPEC023_CONTRACTS: {"qc_contracts", "qc_preprocess"},
}
MODULE_OF = {"qc-preprocess": "qc_preprocess", "qc-contracts": "qc_contracts"}
ALLOWED_EXACT = {
    (SPEC024_PREPROCESS, "qc_preprocess", "0.3.0"),
    (SPEC026_CONTRACTS, "qc_contracts", "0.3.0"),
}


def _version_source(node: ast.AST) -> str | None:
    """Module whose version ``node`` reads (``<mod>.__version__`` or ``...version("<dist>")``)."""
    if isinstance(node, ast.Attribute) and node.attr == "__version__":
        return ast.unparse(node.value)
    if isinstance(node, ast.Call) and ast.unparse(node.func) in (
        "importlib.metadata.version",
        "metadata.version",
        "version",
    ):
        if node.args and isinstance(node.args[0], ast.Constant):
            dist = node.args[0].value
            return MODULE_OF.get(dist, f"<dist {dist}>")
        return "<dynamic>"
    return None


def _owners(tree: ast.Module) -> dict[ast.AST, str]:
    """Innermost enclosing function name of every node."""
    owner: dict[ast.AST, str] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            for sub in ast.walk(fn):
                owner[sub] = fn.name
    return owner


def _exact_comparisons(path: str) -> list[tuple[str, str, str]]:
    """``(function, module, literal)`` of every ``==`` between a version and a str literal."""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    owner = _owners(tree)
    found: list[tuple[str, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        for i, op in enumerate(node.ops):
            if not isinstance(op, ast.Eq):
                continue
            pair = (operands[i], operands[i + 1])
            for ver, lit in (pair, pair[::-1]):
                mod = _version_source(ver)
                if mod and isinstance(lit, ast.Constant) and isinstance(lit.value, str):
                    found.append((owner.get(node, "<module>"), mod, lit.value))
    return found


def _coherence_checks(path: str) -> set[str]:
    """Modules with ``<mod>.__version__ == importlib.metadata.version("<dist>")``, that form."""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)
        ):
            continue
        left, right = node.left, node.comparators[0]
        if (
            isinstance(left, ast.Attribute)
            and left.attr == "__version__"
            and isinstance(right, ast.Call)
            and ast.unparse(right.func) == "importlib.metadata.version"
            and len(right.args) == 1
            and isinstance(right.args[0], ast.Constant)
            and MODULE_OF.get(right.args[0].value) == ast.unparse(left.value)
        ):
            mods.add(ast.unparse(left.value))
    return mods


def test_ca28_version_expectations_migrated() -> None:
    files = sorted(
        str(p.relative_to(ROOT)) for p in ROOT.glob("packages/*/tests/acceptance/test_spec_*.py")
    )
    assert set(VERSION_FILES) <= set(files), files

    # (a) exact comparisons only in the CA-01 of the current SPEC of each package.
    seen: set[tuple[str, str, str]] = set()
    for path in files:
        for func, mod, literal in _exact_comparisons(path):
            assert (path, mod, literal) in ALLOWED_EXACT, (path, func, mod, literal)
            assert func.startswith("test_ca01_"), (path, func)
            seen.add((path, mod, literal))
    assert seen == ALLOWED_EXACT, seen

    # (b) the coherence check for every package each file verified before.
    for path, mods in VERSION_FILES.items():
        assert mods <= _coherence_checks(path), (path, _coherence_checks(path))

    # (c) module docstrings of both test_spec_002.py cite no version number.
    for path in (SPEC002_PREPROCESS, SPEC002_CONTRACTS):
        doc = ast.get_docstring(ast.parse((ROOT / path).read_text(encoding="utf-8"))) or ""
        assert not re.search(r"\d+\.\d+\.\d+", doc), (path, doc)

    # (d) the substring check on "error" is gone.
    text = (ROOT / SPEC024_PREPROCESS).read_text(encoding="utf-8")
    assert '"error" not in out.lower()' not in text

    # Same number of collected tests as main, except the contracts SPEC-023 file (CA-27).
    result, per_file = collect(*VERSION_FILES)
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    for path in VERSION_FILES:
        expected = MAIN_COUNTS[path] - (1 if path == SPEC023_CONTRACTS else 0)
        assert len(per_file[path]) == expected, (path, len(per_file[path]))


# --------------------------------------------------------------------------- extras
# Exploratory edge cases around SPEC-004 section 4.


def test_extra_hash_api_key_is_sha256_lower_hex() -> None:
    for key in ("", "abc", "ção-ü", "k" * 256):
        h = hash_api_key(key)
        assert h == hashlib.sha256(key.encode("utf-8")).hexdigest()
        assert re.fullmatch(r"[0-9a-f]{64}", h)


def test_extra_module_level_app_without_environment() -> None:
    """``uvicorn qc_api.main:app`` imports with no settings in the environment (§4.2)."""
    env = dict(os.environ)
    for name in ("DATABASE_URL", "READ_API_KEY"):
        env.pop(name, None)
    code = "import qc_api.main as m; from fastapi import FastAPI; assert isinstance(m.app, FastAPI)"
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr


def test_extra_no_cors_middleware() -> None:
    app = create_app(Settings(DATABASE_URL=no_db_url(), READ_API_KEY=READ_KEY))
    names = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" not in names, names


@pytest.mark.db
def test_extra_key_length_boundaries(env: Env) -> None:
    """Empty key → 401; a registered key of 256 chars works; 257 chars → 401 even if registered."""
    resp = env.post(payload(new_id()), "")
    assert resp.status_code == 401, resp.text
    assert resp.json() == UNAUTHORIZED
    k256 = secrets.token_hex(128)
    k257 = k256 + "x"
    register(env.db, "len-256", k256)
    register(env.db, "len-257", k257)
    resp = env.post(payload(new_id(), device_id="len-256"), k256)
    assert resp.status_code == 201, resp.text
    resp = env.post(payload(new_id(), device_id="len-257"), k257)
    assert resp.status_code == 401, resp.text
    assert resp.json() == UNAUTHORIZED


@pytest.mark.db
def test_extra_non_ascii_key_is_401_not_500(env: Env) -> None:
    raw = "ção" + secrets.token_hex(4)
    resp = env.client.post(
        URL_ONE, json=payload(new_id()), headers=[(b"X-API-Key", raw.encode("utf-8"))]
    )
    assert resp.status_code == 401, resp.text
    assert resp.json() == UNAUTHORIZED


@pytest.mark.db
@pytest.mark.parametrize("url", [URL_ONE, URL_BATCH])
def test_extra_binary_non_json_body_is_4xx_not_500(env: Env, url: str) -> None:
    """T-01: an image upload (multipart) or raw binary body is a client error, never a 500.

    The routes list 401, 403, 413, 422 and 503 as their errors (SPEC-004 section 4.4), and
    validation errors use the default 422 (section 4.5).
    """
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 16
    resp = env.client.post(
        url, files={"image": ("a.jpg", jpeg, "image/jpeg")}, headers=key_header(env.ke)
    )
    assert resp.status_code in (400, 415, 422), resp.text
    assert_no_traceback(resp)
    for ctype in ("application/octet-stream", "image/jpeg"):
        resp = env.client.post(
            url, content=jpeg, headers={**key_header(env.ke), "Content-Type": ctype}
        )
        assert resp.status_code in (400, 415, 422), (ctype, resp.text)
        assert_no_traceback(resp)
    assert count_rows(env.db) == 0
    assert last_seen(env.db, "edge-01") is None


@pytest.mark.db
@pytest.mark.parametrize("depth", [500, 2000])
def test_extra_deeply_nested_json_is_4xx_not_500(env: Env, depth: int) -> None:
    """T-01 (second trigger): well-formed JSON nested ``depth`` levels is a client error."""
    body = b"[" * depth + b"]" * depth
    assert len(body) < MAX_BODY
    resp = env.client.post(
        URL_ONE, content=body, headers={**key_header(env.ke), "Content-Type": "application/json"}
    )
    assert resp.status_code in (400, 422), resp.text
    assert_no_traceback(resp)
    assert count_rows(env.db) == 0


@pytest.mark.db
def test_extra_request_body_never_logged(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    """T-02: section 4.2 forbids logging the request body, whatever the request."""
    caplog.set_level(logging.DEBUG)
    marker = "BODYMARK" + secrets.token_hex(6)
    lot_marker = "L" + secrets.token_hex(6)
    # a JSON body refused by validation (422)
    resp = env.post(payload(new_id(), lot_id=lot_marker, type_confidence=2), env.ke)
    assert resp.status_code == 422
    # a non-UTF-8 binary body (an "image" sent by mistake)
    body = b"\xff\xd8\xff" + marker.encode() + b"\xff" * 8
    env.client.post(
        URL_ONE,
        content=body,
        headers={**key_header(env.ke), "Content-Type": "application/octet-stream"},
    )
    text = log_text(caplog)
    assert lot_marker not in text
    assert marker not in text
    assert "\\xff\\xd8\\xff" not in text


@pytest.mark.db
def test_extra_duplicate_of_id_owned_by_other_device(env: Env) -> None:
    """§7: a duplicate of an ID owned by another device answers ``duplicate`` (no 409)."""
    x = new_id()
    assert env.post(payload(x, device_id="sim-01"), env.ks).status_code == 201
    resp = env.post(payload(x), env.ke)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"inspection_id": x, "status": "duplicate"}
    with connect(env.db) as conn:
        assert conn.execute("select device_id from inspections").fetchall() == [("sim-01",)]


@pytest.mark.db
def test_extra_batch_of_100_with_unknown(env: Env) -> None:
    items = [payload(new_id()) for _ in range(99)]
    items.append(
        payload(
            new_id(), object_type="unknown", grade=None, grade_score=None, grade_confidence=None
        )
    )
    resp = env.post({"items": items}, env.ke, URL_BATCH)
    assert resp.status_code == 200, resp.text
    assert [r["status"] for r in resp.json()["results"]] == ["created"] * 100
    assert count_rows(env.db) == 100


@pytest.mark.db
def test_extra_wrong_methods_and_unknown_route(env: Env) -> None:
    assert env.client.put(URL_ONE, headers=key_header(env.ke)).status_code == 405
    assert env.client.delete(URL_ONE, headers=key_header(env.ke)).status_code == 405
    assert env.client.post(URL_HEALTH).status_code == 405
    resp = env.client.get("/api/v1/nope")
    assert resp.status_code == 404
    assert_no_traceback(resp)


@pytest.mark.db
def test_extra_non_object_json_bodies(env: Env) -> None:
    for body in ([], None, "x", 1):
        resp = env.post(body, env.ke)
        assert resp.status_code == 422, (body, resp.text)
        assert_no_traceback(resp)
    resp = env.post([], env.ke, URL_BATCH)
    assert resp.status_code == 422, resp.text
    assert count_rows(env.db) == 0


@pytest.mark.db
def test_extra_invalid_lot_ids_rejected(env: Env) -> None:
    for lot in ("L-ção", "L 1", "L-1\n", "a" * 41, ""):
        resp = env.post(payload(new_id(), lot_id=lot), env.ke)
        assert resp.status_code == 422, (lot, resp.text)
    assert count_rows(env.db) == 0


@pytest.mark.db
def test_extra_future_inspected_at_rejected(env: Env) -> None:
    future = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    resp = env.post(payload(new_id(), inspected_at=future), env.ke)
    assert resp.status_code == 422, resp.text
    assert count_rows(env.db) == 0


def test_extra_413_precedes_db_and_auth(no_db_client: TestClient) -> None:
    """413 comes before 503 and 401 (precedence of §4.5), without waiting for the pool."""
    body = b"{" + b" " * MAX_BODY + b"}"
    start = time.monotonic()
    resp = no_db_client.post(URL_ONE, content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 413, resp.text
    assert resp.json() == TOO_LARGE
    assert time.monotonic() - start < 4


@pytest.mark.db
def test_extra_batch_success_updates_last_seen(env: Env) -> None:
    assert last_seen(env.db, "edge-01") is None
    before = datetime.now(UTC)
    resp = env.post({"items": [payload(new_id())]}, env.ke, URL_BATCH)
    after = datetime.now(UTC)
    assert resp.status_code == 200, resp.text
    seen = last_seen(env.db, "edge-01")
    assert seen is not None and before <= seen <= after


@pytest.mark.db
def test_extra_underflow_log_has_sqlstate_only(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    """Section 4.5: the log records the route, the device_id and the SQLSTATE."""
    caplog.set_level(logging.DEBUG)
    resp = env.post(payload(new_id(), grade_score=1e-50), env.ke)
    assert resp.status_code == 422, resp.text
    text = log_text(caplog)
    assert "22003" in text
    assert "edge-01" in text
    assert "underflow" not in text.lower()  # the server message is not logged


@pytest.mark.db
def test_extra_underflow_in_middle_item_rolls_back_whole_batch(env: Env) -> None:
    a, b, c = new_id(), new_id(), new_id()
    resp = env.post(
        {"items": [payload(a), payload(b, grade_confidence=1e-46), payload(c)]},
        env.ke,
        URL_BATCH,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json() == CANNOT_STORE
    assert count_rows(env.db) == 0
    assert last_seen(env.db, "edge-01") is None
    # the pool connection is usable after the rollback
    assert env.post(payload(a), env.ke).status_code == 201


@pytest.mark.db
def test_extra_script_invalid_url_does_not_print_key(clean_db: str) -> None:
    bad = run_script("--device-id", "lab-04", "--database-url", "not a url ::", database_url=None)
    assert bad.returncode in (1, 2), bad.stderr
    assert "DEVICE_API_KEY=" not in bad.stdout
    with connect(clean_db) as conn:
        assert conn.execute("select count(*) from devices").fetchone()[0] == 0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _raw_request(port: int, head: bytes, chunks: list[bytes]) -> bytes:
    """Send ``head`` and ``chunks`` on a raw socket; return what the server answered."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        try:
            sock.sendall(head)
            for chunk in chunks:
                sock.sendall(chunk)
        except OSError:
            pass  # the server may answer 413 and close before the body ends
        data = b""
        try:
            while b"\r\n\r\n" not in data:
                part = sock.recv(65_536)
                if not part:
                    break
                data += part
        except OSError:
            pass
    return data


def test_extra_real_server_413_for_declared_and_chunked_bodies() -> None:
    """Over a real socket (uvicorn), the 413 does not depend on the TestClient buffering."""
    port = _free_port()
    env = dict(os.environ)
    env.update(DATABASE_URL=no_db_url(), READ_API_KEY=READ_KEY, LOG_LEVEL="DEBUG")
    cmd = [sys.executable, "-m", "uvicorn", "qc_api.main:app", "--port", str(port)]
    proc = subprocess.Popen(
        cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                assert proc.poll() is None, "uvicorn exited"
                assert time.monotonic() < deadline, "uvicorn did not start"
                time.sleep(0.2)

        # Declared Content-Length over the limit, no body sent: answered without reading it.
        head = (
            b"POST /api/v1/inspections HTTP/1.1\r\nHost: t\r\n"
            b"Content-Type: application/json\r\nContent-Length: 300000\r\n\r\n"
        )
        start = time.monotonic()
        answer = _raw_request(port, head, [])
        assert answer.startswith(b"HTTP/1.1 413"), answer[:200]
        assert time.monotonic() - start < 4

        # Chunked body of 300 000 bytes, no Content-Length.
        head = (
            b"POST /api/v1/inspections HTTP/1.1\r\nHost: t\r\n"
            b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
        )
        piece = b" " * 16_384
        chunks = [b"%x\r\n" % len(piece) + piece + b"\r\n" for _ in range(19)]
        chunks.append(b"0\r\n\r\n")
        answer = _raw_request(port, head, chunks)
        assert answer.startswith(b"HTTP/1.1 413"), answer[:200]
    finally:
        proc.terminate()
        out, _ = proc.communicate(timeout=20)
    log = out.decode("utf-8", "replace")
    assert NO_DB_PASSWORD + "@" not in log
    assert READ_KEY not in log


# --------------------------------------------------------------------------- r2 extras
# Variations of T-01 (500 instead of 4xx) and T-02 (request body in the log) of
# reviews/SPEC-004/r1-test-report.md: other bodies and content types that the default 422
# handler cannot encode, and other ways for the body to reach the server log.


def _assert_rejected_quietly(
    env: Env, caplog: pytest.LogCaptureFixture, resp: Any, marker: str, statuses: tuple[int, ...]
) -> None:
    """4xx with a ``{"detail": ...}`` body, nothing written, no error log, no body in the log."""
    assert resp.status_code in statuses, resp.text[:500]
    assert "detail" in resp.json()
    assert_no_traceback(resp)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    text = log_text(caplog)
    assert marker not in text
    assert "\\xff\\xd8\\xff" not in text
    assert count_rows(env.db) == 0
    assert last_seen(env.db, "edge-01") is None


def _unencodable_body(kind: str, marker: bytes) -> tuple[bytes, dict[str, str]]:
    jpeg = b"\xff\xd8\xff" + marker + b"\xff" * 8
    json_ct = {"Content-Type": "application/json"}
    if kind.startswith("ct:"):
        ctype = kind[3:]
        return jpeg, ({"Content-Type": ctype} if ctype else {})
    if kind == "deep-list-5000":
        return b"[" * 5000 + b'"' + marker + b'"' + b"]" * 5000, json_ct
    if kind == "deep-object-3000":
        return b'{"a":' * 3000 + b'"' + marker + b'"' + b"}" * 3000, json_ct
    if kind == "deep-in-extra-field":
        head = json.dumps(payload(new_id()))[:-1].encode()
        return head + b', "x": ' + b"[" * 3000 + b'"' + marker + b'"' + b"]" * 3000 + b"}", json_ct
    if kind == "deep-batch-item":
        return b'{"items": [' + b"[" * 3000 + b'"' + marker + b'"' + b"]" * 3000 + b"]}", json_ct
    raise AssertionError(kind)


UNENCODABLE_KINDS = [
    "ct:application/octet-stream",
    "ct:image/jpeg",
    "ct:image/png",
    "ct:text/plain",
    "ct:application/x-www-form-urlencoded",
    "ct:application/xml",
    "ct:",  # no Content-Type at all
    "deep-list-5000",
    "deep-object-3000",
    "deep-in-extra-field",
    "deep-batch-item",
]


@pytest.mark.db
@pytest.mark.parametrize("url", [URL_ONE, URL_BATCH])
@pytest.mark.parametrize("kind", UNENCODABLE_KINDS)
def test_extra_r2_unencodable_bodies_are_422_and_not_logged(
    env: Env, caplog: pytest.LogCaptureFixture, url: str, kind: str
) -> None:
    """T-01/T-02 variations: every body the default 422 cannot echo is a 422, never logged."""
    caplog.set_level(logging.DEBUG)
    marker = "BODYMARK" + secrets.token_hex(6)
    body, headers = _unencodable_body(kind, marker.encode())
    assert len(body) < MAX_BODY
    resp = env.client.post(url, content=body, headers={**key_header(env.ke), **headers})
    _assert_rejected_quietly(env, caplog, resp, marker, (422,))
    assert isinstance(resp.json()["detail"], list)  # the shape of the default 422 (§4.5)


@pytest.mark.db
@pytest.mark.parametrize("url", [URL_ONE, URL_BATCH])
def test_extra_r2_multipart_with_json_and_image_parts(
    env: Env, caplog: pytest.LogCaptureFixture, url: str
) -> None:
    """A multipart upload with a JSON-looking part and a binary image part is a quiet 422."""
    caplog.set_level(logging.DEBUG)
    marker = "BODYMARK" + secrets.token_hex(6)
    files = {
        "payload": (None, json.dumps(payload(new_id())), "application/json"),
        "image": ("a.jpg", b"\xff\xd8\xff" + marker.encode() + b"\xff" * 8, "image/jpeg"),
    }
    resp = env.client.post(url, files=files, headers=key_header(env.ke))
    _assert_rejected_quietly(env, caplog, resp, marker, (422,))


@pytest.mark.db
@pytest.mark.parametrize("url", [URL_ONE, URL_BATCH])
def test_extra_r2_nesting_sweep_around_recursion_limit(
    env: Env, caplog: pytest.LogCaptureFixture, url: str
) -> None:
    """Nesting depths around ``sys.getrecursionlimit()`` and far above it: never a 500."""
    caplog.set_level(logging.DEBUG)
    limit = sys.getrecursionlimit()
    depths = [*range(limit - 150, limit + 151, 25), 20_000, 40_000]
    for depth in depths:
        for body in (b"[" * depth + b"]" * depth, b'{"a":' * depth + b"1" + b"}" * depth):
            assert len(body) < MAX_BODY
            resp = env.client.post(
                url,
                content=body,
                headers={**key_header(env.ke), "Content-Type": "application/json"},
            )
            assert resp.status_code in (400, 422), (depth, resp.text[:300])
            assert_no_traceback(resp)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert count_rows(env.db) == 0
    assert last_seen(env.db, "edge-01") is None


@pytest.mark.db
def test_extra_r2_non_finite_numbers_are_422(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    """``json.loads`` accepts NaN/Infinity and turns 1e400 into inf, which ``json.dumps``
    (``allow_nan=False``) cannot echo back: still a quiet 422, on both routes."""
    caplog.set_level(logging.DEBUG)
    base = json.dumps(payload(new_id()))
    variants = [
        base.replace('"type_confidence": 0.97', '"type_confidence": NaN'),
        base.replace('"grade_score": 2.0', '"grade_score": Infinity'),
        base.replace('"grade_confidence": 0.81', '"grade_confidence": -Infinity'),
        base.replace('"grade_score": 2.0', '"grade_score": 1e400'),
        base.replace('"latency_ms": 42', '"latency_ms": NaN'),
        base[:-1] + ', "x": NaN}',
        "NaN",
    ]
    for text in variants:
        assert text != base
        for url, body in ((URL_ONE, text), (URL_BATCH, '{"items": [' + text + "]}")):
            resp = env.client.post(
                url,
                content=body.encode(),
                headers={**key_header(env.ke), "Content-Type": "application/json"},
            )
            assert resp.status_code == 422, (url, text[-60:], resp.text[:300])
            assert_no_traceback(resp)
    resp = env.client.post(
        URL_BATCH,
        content=b'{"items": NaN}',
        headers={**key_header(env.ke), "Content-Type": "application/json"},
    )
    assert resp.status_code == 422, resp.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert count_rows(env.db) == 0
    assert last_seen(env.db, "edge-01") is None


@pytest.mark.db
def test_extra_r2_lone_surrogates_and_nul_are_422(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    """JSON escapes that decode to strings UTF-8 cannot encode (lone surrogates) or to NUL,
    in values and in unknown keys: 422, never a 500, and nothing written."""
    caplog.set_level(logging.DEBUG)
    base = json.dumps(payload(new_id()))
    variants = [
        base[:-1] + ', "\\ud800x": 1}',
        base[:-1] + ', "\\u0000x": 1}',
        base.replace('"lot_id": "L-001"', '"lot_id": "L-\\udfff"'),
        base.replace('"lot_id": "L-001"', '"lot_id": "L-\\u0000"'),
        base.replace('"object_type": "screw"', '"object_type": "\\ud83d"'),
        re.sub(r'"inspection_id": "[^"]+"', '"inspection_id": "0\\\\ud800"', base),
        base.replace('"source": "live"', '"source": "live\\u0000"'),
    ]
    for text in variants:
        assert text != base
        for url, body in ((URL_ONE, text), (URL_BATCH, '{"items": [' + text + "]}")):
            resp = env.client.post(
                url,
                content=body.encode(),
                headers={**key_header(env.ke), "Content-Type": "application/json"},
            )
            assert resp.status_code == 422, (url, text[-80:], resp.text[:300])
            assert_no_traceback(resp)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert count_rows(env.db) == 0
    assert last_seen(env.db, "edge-01") is None


@pytest.mark.db
def test_extra_r2_encodable_422_is_still_the_default(env: Env) -> None:
    """§4.5: when the input can be encoded, the 422 is FastAPI's default (``input`` echoed)."""
    body = payload(new_id())
    del body["lot_id"]
    resp = env.post(body, env.ke)
    assert resp.status_code == 422, resp.text
    errors = resp.json()["detail"]
    assert errors and errors[0]["type"] == "missing"
    assert errors[0]["loc"] == ["body", "lot_id"]
    assert "input" in errors[0]
    resp = env.client.post(
        URL_ONE,
        content=b"not json",
        headers={**key_header(env.ke), "Content-Type": "application/json"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["type"] == "json_invalid"


@pytest.mark.db
def test_extra_r2_real_server_unencodable_bodies_are_422_and_not_logged(clean_db: str) -> None:
    """T-01/T-02 over a real socket (uvicorn, main-thread stack) with the test database:
    422 (or 400 for nesting ``json.loads`` refuses) and the body never in the server log."""
    ke = secrets.token_urlsafe(32)
    register(clean_db, "edge-01", ke)
    port = _free_port()
    proc_env = dict(os.environ)
    proc_env.update(DATABASE_URL=clean_db, READ_API_KEY=READ_KEY, LOG_LEVEL="DEBUG")
    cmd = [sys.executable, "-m", "uvicorn", "qc_api.main:app", "--port", str(port)]
    proc = subprocess.Popen(
        cmd, env=proc_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT
    )
    marker = ("BODYMARK" + secrets.token_hex(6)).encode()
    jpeg = b"\xff\xd8\xff" + marker + b"\xff" * 8
    statuses: list[tuple[str, str, int]] = []
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                assert proc.poll() is None, "uvicorn exited"
                assert time.monotonic() < deadline, "uvicorn did not start"
                time.sleep(0.2)
        headers = key_header(ke)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            for url in (URL_ONE, URL_BATCH):
                resp = client.post(
                    url, files={"image": ("a.jpg", jpeg, "image/jpeg")}, headers=headers
                )
                statuses.append((url, "multipart", resp.status_code))
                resp = client.post(
                    url,
                    content=jpeg,
                    headers={**headers, "Content-Type": "application/octet-stream"},
                )
                statuses.append((url, "octet-stream", resp.status_code))
                for depth in (1000, 2000, 5000, 50_000):
                    body = b"[" * depth + b'"' + marker + b'"' + b"]" * depth
                    resp = client.post(
                        url, content=body, headers={**headers, "Content-Type": "application/json"}
                    )
                    statuses.append((url, f"deep-{depth}", resp.status_code))
    finally:
        proc.terminate()
        out, _ = proc.communicate(timeout=20)
    log = out.decode("utf-8", "replace")
    for url, kind, code in statuses:
        expected = (400, 422) if kind == "deep-50000" else (422,)
        assert code in expected, (url, kind, code)
    assert marker.decode() not in log
    assert "Traceback" not in log
    assert " ERROR " not in log
    assert ke not in log
    assert count_rows(clean_db) == 0
    assert last_seen(clean_db, "edge-01") is None
