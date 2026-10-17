"""Write routes and device authentication against the test PostgreSQL (SPEC-004 section 4.4).

All tests are marked ``db``.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

import qc_contracts
from qc_api.auth import hash_api_key

pytestmark = pytest.mark.db

URL = "/api/v1/inspections"
BATCH_URL = "/api/v1/inspections/batch"
INVALID_KEY = {"detail": "Missing or invalid API key"}
MISMATCH = {"detail": "device_id does not match API key"}
NOT_STORABLE = {"detail": "Value cannot be stored"}


def _count(db: psycopg.Connection) -> int:
    return db.execute("select count(*) from inspections").fetchone()[0]


def _last_seen(db: psycopg.Connection, device_id: str = "edge-01") -> datetime | None:
    row = db.execute("select last_seen_at from devices where device_id = %s", (device_id,))
    return row.fetchone()[0]


def _key(device_keys: dict[str, str], device_id: str = "edge-01") -> dict[str, str]:
    return {"X-API-Key": device_keys[device_id]}


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "db": "ok",
        "api_version": "0.1.0",
        "contract_version": qc_contracts.__version__,
    }


def test_create_stores_utc_and_server_fields(
    client: TestClient, device_keys, make_payload, db
) -> None:
    inspection_id = str(uuid.uuid4())
    response = client.post(URL, json=make_payload(inspection_id), headers=_key(device_keys))
    assert response.status_code == 201
    assert response.json() == {"inspection_id": inspection_id, "status": "created"}
    row = db.execute(
        "select inspected_at, received_at, is_defective, object_type, grade, source"
        " from inspections where inspection_id = %s",
        (inspection_id,),
    ).fetchone()
    assert row[0] == datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
    assert row[1] is not None
    assert row[2] is False
    assert row[3:] == ("screw", "fair", "live")


def test_unknown_object_stores_nulls(client: TestClient, device_keys, make_payload, db) -> None:
    payload = make_payload(
        object_type="unknown", grade=None, grade_score=None, grade_confidence=None
    )
    assert client.post(URL, json=payload, headers=_key(device_keys)).status_code == 201
    row = db.execute("select grade, grade_score, grade_confidence from inspections").fetchone()
    assert row == (None, None, None)


def test_duplicate_does_not_change_original(
    client: TestClient, device_keys, make_payload, db
) -> None:
    inspection_id = str(uuid.uuid4())
    assert (
        client.post(URL, json=make_payload(inspection_id), headers=_key(device_keys)).status_code
        == 201
    )
    for lot in ("L-001", "L-002", "L-999"):
        response = client.post(
            URL, json=make_payload(inspection_id, lot_id=lot), headers=_key(device_keys)
        )
        assert response.status_code == 200
        assert response.json() == {"inspection_id": inspection_id, "status": "duplicate"}
    assert _count(db) == 1
    assert db.execute("select lot_id from inspections").fetchone()[0] == "L-001"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-API-Key": ""},
        {"X-API-Key": "errada"},
        {"X-API-Key": "r" * 32},
        {"X-API-Key": "k" * 300},
    ],
)
def test_invalid_keys_are_401(client: TestClient, make_payload, db, headers) -> None:
    response = client.post(URL, json=make_payload(), headers=headers)
    assert response.status_code == 401
    assert response.json() == INVALID_KEY
    assert _count(db) == 0


def test_key_of_257_chars_is_401_even_if_registered(client: TestClient, make_payload, db) -> None:
    long_key = "a" * 257
    db.execute(
        "insert into devices (device_id, api_key_hash) values ('long-01', %s)",
        (hash_api_key(long_key),),
    )
    payload = make_payload(device_id="long-01")
    assert client.post(URL, json=payload, headers={"X-API-Key": long_key}).status_code == 401


def test_auth_before_validation(client: TestClient, make_payload) -> None:
    payload = make_payload()
    del payload["lot_id"]
    assert client.post(URL, json=payload).status_code == 401
    assert client.post(BATCH_URL, json={"items": []}).status_code == 401


def test_device_mismatch_is_403(client: TestClient, device_keys, make_payload, db) -> None:
    response = client.post(URL, json=make_payload(device_id="sim-01"), headers=_key(device_keys))
    assert response.status_code == 403
    assert response.json() == MISMATCH
    assert _count(db) == 0
    assert _last_seen(db, "edge-01") is None
    assert _last_seen(db, "sim-01") is None


@pytest.mark.parametrize(
    "body",
    [
        "extra_image",
        "unknown_with_grade",
        "naive_datetime",
        "missing_lot",
        "latency_over_max",
        "not_json",
        "future",
    ],
)
def test_invalid_bodies_are_422(
    client: TestClient, device_keys, make_payload, db, body: str
) -> None:
    payload = make_payload()
    match body:
        case "extra_image":
            payload["image"] = "AAAA"
        case "unknown_with_grade":
            payload["object_type"] = "unknown"
        case "naive_datetime":
            payload["inspected_at"] = "2026-10-01T12:00:00"
        case "missing_lot":
            del payload["lot_id"]
        case "latency_over_max":
            payload["latency_ms"] = qc_contracts.MAX_LATENCY_MS + 1
        case "future":
            payload["inspected_at"] = "2999-01-01T00:00:00Z"
    content = b"not json" if body == "not_json" else json.dumps(payload).encode()
    response = client.post(
        URL, content=content, headers={**_key(device_keys), "Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "Traceback" not in response.text
    assert _count(db) == 0
    assert _last_seen(db) is None


def test_body_limit(client: TestClient, device_keys, make_payload, db) -> None:
    base = json.dumps(make_payload()).encode()
    exact = base[:-1] + b" " * (262_144 - len(base)) + b"}"
    assert len(exact) == 262_144
    headers = {**_key(device_keys), "Content-Type": "application/json"}
    response = client.post(URL, content=exact, headers=headers)
    assert response.status_code == 201
    over = base[:-1] + b" " * (262_145 - len(base)) + b"}"
    response = client.post(URL, content=over, headers=headers)
    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}

    def chunks():
        for _ in range(300):
            yield b" " * 1000

    response = client.post(URL, content=chunks(), headers=headers)
    assert response.status_code == 413
    assert _count(db) == 1


def test_last_seen_updates_only_on_success(
    client: TestClient, device_keys, make_payload, db
) -> None:
    inspection_id = str(uuid.uuid4())
    before = datetime.now(UTC)
    assert (
        client.post(URL, json=make_payload(inspection_id), headers=_key(device_keys)).status_code
        == 201
    )
    first = _last_seen(db)
    assert first is not None
    assert before <= first <= datetime.now(UTC)
    assert (
        client.post(URL, json=make_payload(inspection_id), headers=_key(device_keys)).status_code
        == 200
    )
    second = _last_seen(db)
    assert second >= first
    client.post(URL, json=make_payload(), headers={"X-API-Key": "errada"})
    client.post(URL, json=make_payload(device_id="sim-01"), headers=_key(device_keys))
    client.post(URL, json=make_payload(lot_id="bad lot"), headers=_key(device_keys))
    assert _last_seen(db) == second


def test_batch_created_in_order(client: TestClient, device_keys, make_payload, db) -> None:
    ids = [str(uuid.uuid4()) for _ in range(3)]
    response = client.post(
        BATCH_URL, json={"items": [make_payload(i) for i in ids]}, headers=_key(device_keys)
    )
    assert response.status_code == 200
    assert response.json() == {"results": [{"inspection_id": i, "status": "created"} for i in ids]}
    assert _count(db) == 3
    assert _last_seen(db) is not None


def test_batch_duplicates_inside_and_outside(
    client: TestClient, device_keys, make_payload, db
) -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    client.post(URL, json=make_payload(a), headers=_key(device_keys))
    response = client.post(
        BATCH_URL,
        json={"items": [make_payload(b), make_payload(a), make_payload(b, lot_id="L-2")]},
        headers=_key(device_keys),
    )
    assert response.status_code == 200
    assert [r["status"] for r in response.json()["results"]] == [
        "created",
        "duplicate",
        "duplicate",
    ]
    assert [r["inspection_id"] for r in response.json()["results"]] == [b, a, b]
    assert _count(db) == 2
    lot = db.execute("select lot_id from inspections where inspection_id = %s", (b,)).fetchone()
    assert lot[0] == "L-001"


@pytest.mark.parametrize("size", [0, 101])
def test_batch_size_limits(client: TestClient, device_keys, make_payload, size: int) -> None:
    items = [make_payload() for _ in range(size)]
    assert (
        client.post(BATCH_URL, json={"items": items}, headers=_key(device_keys)).status_code == 422
    )


def test_batch_with_invalid_item_writes_nothing(
    client: TestClient, device_keys, make_payload, db
) -> None:
    items = [make_payload(), make_payload(type_confidence=2), make_payload()]
    response = client.post(BATCH_URL, json={"items": items}, headers=_key(device_keys))
    assert response.status_code == 422
    assert _count(db) == 0


def test_batch_with_foreign_device_is_403(
    client: TestClient, device_keys, make_payload, db
) -> None:
    items = [make_payload(), make_payload(), make_payload(device_id="sim-01")]
    response = client.post(BATCH_URL, json={"items": items}, headers=_key(device_keys))
    assert response.status_code == 403
    assert response.json() == MISMATCH
    assert _count(db) == 0
    assert _last_seen(db) is None


def test_latency_limits(client: TestClient, device_keys, make_payload, db) -> None:
    x = str(uuid.uuid4())
    response = client.post(
        URL, json=make_payload(x, latency_ms=qc_contracts.MAX_LATENCY_MS), headers=_key(device_keys)
    )
    assert response.status_code == 201
    stored = db.execute("select latency_ms from inspections where inspection_id = %s", (x,))
    assert stored.fetchone()[0] == 2_147_483_647
    items = [make_payload(), make_payload(latency_ms=qc_contracts.MAX_LATENCY_MS + 1)]
    response = client.post(BATCH_URL, json={"items": items}, headers=_key(device_keys))
    assert response.status_code == 422
    assert "Traceback" not in response.text
    assert _count(db) == 1


def test_float4_underflow_is_422_and_rolls_back(
    client: TestClient, device_keys, make_payload, db, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    response = client.post(URL, json=make_payload(grade_score=1e-50), headers=_key(device_keys))
    assert response.status_code == 422
    assert response.json() == NOT_STORABLE
    items = [make_payload(), make_payload(type_confidence=5e-324)]
    response = client.post(BATCH_URL, json={"items": items}, headers=_key(device_keys))
    assert response.status_code == 422
    assert response.json() == NOT_STORABLE
    assert _count(db) == 0
    assert _last_seen(db) is None
    assert "1e-50" not in caplog.text
    assert "5e-324" not in caplog.text
    assert "sqlstate=22003" in caplog.text
    response = client.post(URL, json=make_payload(type_confidence=1e-40), headers=_key(device_keys))
    assert response.status_code == 201


def test_huge_json_integer_is_4xx(client: TestClient, device_keys, make_payload, db) -> None:
    text = json.dumps(make_payload(latency_ms=0)).replace(
        '"latency_ms": 0', '"latency_ms": ' + "9" * 5000
    )
    response = client.post(
        URL,
        content=text.encode(),
        headers={**_key(device_keys), "Content-Type": "application/json"},
    )
    assert response.status_code in {400, 422}
    assert "Traceback" not in response.text
    assert _count(db) == 0


@pytest.mark.parametrize("url", [URL, BATCH_URL])
def test_bodies_the_default_422_cannot_encode_are_422(
    client: TestClient, device_keys, db, caplog: pytest.LogCaptureFixture, url: str
) -> None:
    """T-01/T-02 of r1: binary, multipart and deeply nested bodies are 422, never 500 or logged."""
    caplog.set_level(logging.DEBUG)
    marker = "BODYMARK" + uuid.uuid4().hex
    jpeg = b"\xff\xd8\xff" + marker.encode() + b"\xff" * 8
    headers = _key(device_keys)
    responses = [
        client.post(url, files={"image": ("a.jpg", jpeg, "image/jpeg")}, headers=headers),
        client.post(
            url, content=jpeg, headers={**headers, "Content-Type": "application/octet-stream"}
        ),
        client.post(
            url,
            content=b"[" * 2000 + b"]" * 2000,
            headers={**headers, "Content-Type": "application/json"},
        ),
    ]
    for response in responses:
        assert response.status_code == 422, response.text
        assert all("input" not in error for error in response.json()["detail"])
    assert _count(db) == 0
    assert _last_seen(db) is None
    assert marker not in caplog.text
    assert "\\xff\\xd8\\xff" not in caplog.text


def _race(client: TestClient, payload: dict, headers: dict[str, str]) -> list[int]:
    """Send ``payload`` from two threads released together by a barrier."""
    barrier = threading.Barrier(2)
    statuses: list[int] = []

    def send() -> None:
        barrier.wait()
        statuses.append(client.post(URL, json=payload, headers=headers).status_code)

    threads = [threading.Thread(target=send) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return statuses


def test_concurrent_same_id_creates_one_row(
    client: TestClient, device_keys, make_payload, db
) -> None:
    for _ in range(10):
        payload = make_payload()
        assert sorted(_race(client, payload, _key(device_keys))) == [200, 201]
        row = db.execute(
            "select count(*) from inspections where inspection_id = %s",
            (payload["inspection_id"],),
        )
        assert row.fetchone()[0] == 1


def test_logs_have_no_keys(
    client: TestClient, device_keys, make_payload, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    key = device_keys["edge-01"]
    assert client.post(URL, json=make_payload(), headers=_key(device_keys)).status_code == 201
    assert client.post(URL, json=make_payload(), headers={"X-API-Key": "nope"}).status_code == 401
    messages = [record.getMessage() for record in caplog.records]
    assert any("POST /api/v1/inspections 201 device_id=edge-01" in m for m in messages)
    for secret in (key, hash_api_key(key), "r" * 32):
        assert secret not in caplog.text


@pytest.fixture
def stricter_lot_check(db: psycopg.Connection) -> Iterator[str]:
    """A database ``check`` stricter than the contract (a future migration that diverges)."""
    marker = "L-STRICT-" + uuid.uuid4().hex[:8].upper()
    db.execute(
        sql.SQL(
            "alter table inspections add constraint author_strict_lot check (lot_id <> {})"
        ).format(sql.Literal(marker))
    )
    try:
        yield marker
    finally:
        db.execute("alter table inspections drop constraint if exists author_strict_lot")


def test_integrity_error_is_422_and_rolls_back(
    client: TestClient,
    device_keys,
    make_payload,
    db,
    stricter_lot_check: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    response = client.post(
        URL, json=make_payload(lot_id=stricter_lot_check), headers=_key(device_keys)
    )
    assert response.status_code == 422
    assert response.json() == NOT_STORABLE
    items = [make_payload(), make_payload(lot_id=stricter_lot_check)]
    response = client.post(BATCH_URL, json={"items": items}, headers=_key(device_keys))
    assert response.status_code == 422
    assert response.json() == NOT_STORABLE
    assert _count(db) == 0
    assert _last_seen(db) is None
    assert "sqlstate=23514" in caplog.text
    assert stricter_lot_check not in caplog.text
    assert not any(r.exc_info for r in caplog.records)
    assert client.post(URL, json=make_payload(), headers=_key(device_keys)).status_code == 201


@pytest.mark.parametrize(
    ("error", "label"),
    [
        (psycopg.IntegrityError("x"), "-"),
        (psycopg.DataError("y"), "-"),
        (psycopg.errors.CheckViolation(), "23514"),
    ],
    ids=["integrity-without-sqlstate", "data-without-sqlstate", "check-violation"],
)
def test_write_log_uses_sqlstate_label(
    client: TestClient,
    device_keys,
    make_payload,
    db,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: psycopg.Error,
    label: str,
) -> None:
    """SPEC-027 section 4.2: same SQLSTATE rule as the middleware (``-`` when missing)."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr("qc_api.routers.inspections.insert_inspections", refuse)
    caplog.set_level(logging.DEBUG)
    response = client.post(URL, json=make_payload(), headers=_key(device_keys))
    assert response.status_code == 422
    assert response.json() == NOT_STORABLE
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and "value cannot be stored" in r.getMessage()
    ]
    assert warnings == [f"value cannot be stored: route={URL} device_id=edge-01 sqlstate={label}"]
    assert "sqlstate=None" not in caplog.text
    assert not any(r.exc_info for r in caplog.records)
    assert _count(db) == 0
