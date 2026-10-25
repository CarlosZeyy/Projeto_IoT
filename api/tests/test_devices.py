"""Heartbeat and device status routes against the test PostgreSQL (SPEC-018 section 4.3).

Database tests are marked ``db``; the routes without a database at the end are not.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from qc_api.auth import hash_api_key
from qc_api.main import create_app
from qc_api.repositories import devices as repository
from qc_contracts import DeviceStatus

READ_KEY = "r" * 32
SHA = "c" * 64
DEVICES_URL = "/api/v1/devices"
INVALID_KEY = {"detail": "Missing or invalid API key"}
MISMATCH = {"detail": "device_id does not match API key"}
NOT_STORABLE = {"detail": "Value cannot be stored"}


def hb_url(device_id: str = "edge-01") -> str:
    return f"/api/v1/devices/{device_id}/heartbeat"


def heartbeat(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "sent_at": (datetime.now(UTC) - timedelta(seconds=2)).isoformat(),
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "app_version": "0.0.0",
        "uptime_s": 7500,
        "outbox_pending": 3,
        "outbox_dead": 1,
    }
    body.update(overrides)
    return body


def key(device_keys: dict[str, str], device_id: str = "edge-01") -> dict[str, str]:
    return {"X-API-Key": device_keys[device_id]}


def read_key() -> dict[str, str]:
    return {"X-API-Key": READ_KEY}


def device_row(db: psycopg.Connection, device_id: str = "edge-01") -> tuple[Any, ...]:
    return db.execute(
        "select last_heartbeat_at, last_seen_at, hb_sent_at, hb_model_version, hb_model_sha256,"
        " hb_app_version, hb_uptime_s, hb_outbox_pending, hb_outbox_dead"
        " from devices where device_id = %s",
        (device_id,),
    ).fetchone()


def by_id(response_json: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["device_id"]: item for item in response_json}


def insert_inspection(
    db: psycopg.Connection,
    device_id: str,
    source: str,
    received_at: datetime,
    inspected_at: datetime | None = None,
) -> None:
    db.execute(
        """
        insert into inspections (
            inspection_id, device_id, lot_id, inspected_at, received_at, object_type, grade,
            grade_score, type_confidence, grade_confidence, needs_review, model_version,
            model_sha256, latency_ms, source
        )
        values (%s, %s, 'L-001', %s, %s, 'screw', 'good', 1.0, 0.9, 0.8, false,
                'partqc-mnv3-v1', %s, 10, %s)
        """,
        (
            uuid.uuid4(),
            device_id,
            inspected_at or received_at,
            received_at,
            SHA,
            source,
        ),
    )


def register(db: psycopg.Connection, device_id: str) -> str:
    device_key = secrets.token_urlsafe(32)
    db.execute(
        "insert into devices (device_id, api_key_hash) values (%s, %s)",
        (device_id, hash_api_key(device_key)),
    )
    return device_key


# ---------- POST /devices/{device_id}/heartbeat ----------


@pytest.mark.db
def test_heartbeat_204_and_stored(client: TestClient, device_keys, db) -> None:
    before = datetime.now(UTC)
    body = heartbeat(outbox_pending=3)
    response = client.post(hb_url(), json=body, headers=key(device_keys))
    after = datetime.now(UTC)
    assert response.status_code == 204
    assert response.content == b""
    row = device_row(db)
    assert before - timedelta(seconds=1) <= row[0] <= after + timedelta(seconds=1)
    assert row[1] == row[0]  # last_seen_at and last_heartbeat_at: the same server now()
    assert row[2] == datetime.fromisoformat(body["sent_at"])
    assert row[3:] == ("partqc-mnv3-v1", SHA, "0.0.0", 7500, 3, 1)
    assert device_row(db, "sim-01") == (None,) * 9


@pytest.mark.db
def test_heartbeat_without_model_and_second_heartbeat_overwrites(
    client: TestClient, device_keys, db
) -> None:
    assert client.post(hb_url(), json=heartbeat(), headers=key(device_keys)).status_code == 204
    first = device_row(db)
    body = heartbeat(model_version=None, model_sha256=None, uptime_s=0, outbox_dead=0)
    assert client.post(hb_url(), json=body, headers=key(device_keys)).status_code == 204
    second = device_row(db)
    assert second[0] >= first[0]
    assert second[3:] == (None, None, "0.0.0", 0, 3, 0)
    assert db.execute("select count(*) from devices").fetchone() == (2,)


@pytest.mark.db
def test_sent_at_does_not_decide_the_heartbeat_time(client: TestClient, device_keys, db) -> None:
    old = datetime(2020, 1, 1, tzinfo=UTC)
    body = heartbeat(sent_at=old.isoformat())
    assert client.post(hb_url(), json=body, headers=key(device_keys)).status_code == 204
    row = device_row(db)
    assert row[2] == old
    assert row[0] > datetime.now(UTC) - timedelta(minutes=1)
    devices = by_id(client.get(DEVICES_URL, headers=read_key()).json())
    assert devices["edge-01"]["online"] is True


@pytest.mark.db
def test_heartbeat_for_another_device_is_403(client: TestClient, device_keys, db) -> None:
    response = client.post(hb_url("sim-01"), json=heartbeat(), headers=key(device_keys))
    assert response.status_code == 403
    assert response.json() == MISMATCH
    assert device_row(db, "sim-01") == (None,) * 9
    assert device_row(db) == (None,) * 9


@pytest.mark.db
def test_heartbeat_to_an_unregistered_device_with_a_valid_key_is_403(
    client: TestClient, device_keys
) -> None:
    response = client.post(hb_url("lab-99"), json=heartbeat(), headers=key(device_keys))
    assert response.status_code == 403


@pytest.mark.db
@pytest.mark.parametrize(
    "headers",
    [{}, {"X-API-Key": "wrong"}, {"X-API-Key": READ_KEY}, {"X-API-Key": "k" * 300}],
    ids=["missing", "invalid", "read-key", "too-long"],
)
def test_heartbeat_without_a_valid_device_key_is_401(
    client: TestClient, device_keys, db, headers: dict[str, str]
) -> None:
    response = client.post(hb_url(), json=heartbeat(), headers=headers)
    assert response.status_code == 401
    assert response.json() == INVALID_KEY
    assert device_row(db) == (None,) * 9


@pytest.mark.db
def test_authentication_comes_before_validation(client: TestClient, device_keys) -> None:
    response = client.post(hb_url("EDGE_01"), json={"uptime_s": -1})
    assert response.status_code == 401


@pytest.mark.db
@pytest.mark.parametrize(
    "body",
    [
        heartbeat(image="AAAA"),
        heartbeat(uptime_s=-1),
        heartbeat(outbox_pending=2_147_483_648),
        heartbeat(app_version="1.0\n"),
        heartbeat(sent_at="2026-10-24T12:00:00"),
        heartbeat(model_sha256=None),
        {},
    ],
    ids=["extra", "uptime", "pending", "app-version", "naive", "pair", "empty"],
)
def test_invalid_body_is_422_and_not_logged(
    client: TestClient, device_keys, db, caplog: pytest.LogCaptureFixture, body: dict[str, Any]
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = "marker-" + secrets.token_hex(6)
    sent = {**body, "app_version": marker} if "image" in body else body
    response = client.post(hb_url(), json=sent, headers=key(device_keys))
    assert response.status_code == 422
    assert "Traceback" not in response.text
    assert device_row(db) == (None,) * 9
    assert marker not in caplog.text
    assert "AAAA" not in caplog.text


@pytest.mark.db
@pytest.mark.parametrize("device_id", ["EDGE_01", "ed", "a" * 33, "edge-01%0A", "edge%2001"])
def test_path_device_id_outside_the_pattern_is_422(
    client: TestClient, device_keys, db, device_id: str
) -> None:
    response = client.post(hb_url(device_id), json=heartbeat(), headers=key(device_keys))
    assert response.status_code == 422
    assert device_row(db) == (None,) * 9


@pytest.mark.db
def test_heartbeat_body_limit_is_413(client: TestClient, device_keys) -> None:
    body = b'{"pad": "' + b"x" * 300_000 + b'"}'
    response = client.post(
        hb_url(),
        content=body,
        headers={**key(device_keys), "Content-Type": "application/json"},
    )
    assert response.status_code == 413


@pytest.mark.db
def test_heartbeat_value_refused_by_the_database_is_422(
    clean_db: str, device_keys, db, caplog: pytest.LogCaptureFixture
) -> None:
    db.execute("alter table devices drop constraint if exists extra_no_uptime")
    db.execute("alter table devices add constraint extra_no_uptime check (hb_uptime_s < 100)")
    try:
        caplog.set_level(logging.DEBUG)
        with TestClient(create_app(_settings(clean_db))) as client:
            response = client.post(hb_url(), json=heartbeat(), headers=key(device_keys))
        assert response.status_code == 422
        assert response.json() == NOT_STORABLE
        assert device_row(db) == (None,) * 9
        assert "sqlstate=23514" in caplog.text
        assert "extra_no_uptime" not in caplog.text
        assert "Failing row" not in caplog.text
    finally:
        db.execute("alter table devices drop constraint if exists extra_no_uptime")


@pytest.mark.db
def test_heartbeat_log_line_has_route_template_and_device(
    client: TestClient, device_keys, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="qc_api")
    assert client.post(hb_url(), json=heartbeat(), headers=key(device_keys)).status_code == 204
    lines = [r.getMessage() for r in caplog.records if r.name == "qc_api"]
    assert any(
        "POST /api/v1/devices/{device_id}/heartbeat 204 device_id=edge-01" in line for line in lines
    ), lines
    assert device_keys["edge-01"] not in caplog.text


# ---------- GET /devices ----------


@pytest.mark.db
def test_list_devices_after_a_heartbeat(client: TestClient, device_keys) -> None:
    client.post(hb_url(), json=heartbeat(outbox_pending=3), headers=key(device_keys))
    response = client.get(DEVICES_URL, headers=read_key())
    assert response.status_code == 200
    items = response.json()
    assert [item["device_id"] for item in items] == ["edge-01", "sim-01"]
    edge = DeviceStatus.model_validate(items[0])
    assert edge.online is True
    assert edge.outbox_pending == 3
    assert edge.last_heartbeat_at is not None
    assert edge.last_seen_at == edge.last_heartbeat_at
    assert (edge.model_version, edge.model_sha256, edge.app_version) == (
        "partqc-mnv3-v1",
        SHA,
        "0.0.0",
    )
    assert (edge.uptime_s, edge.outbox_dead, edge.last_source) == (7500, 1, None)
    sim = items[1]
    assert sim == {
        "device_id": "sim-01",
        "last_seen_at": None,
        "last_heartbeat_at": None,
        "online": False,
        "model_version": None,
        "model_sha256": None,
        "app_version": None,
        "uptime_s": None,
        "outbox_pending": None,
        "outbox_dead": None,
        "last_source": None,
    }


@pytest.mark.db
@pytest.mark.parametrize(("age_s", "online"), [(0, True), (179, True), (181, False), (3600, False)])
def test_online_window(client: TestClient, device_keys, db, age_s: int, online: bool) -> None:
    client.post(hb_url(), json=heartbeat(), headers=key(device_keys))
    db.execute(
        "update devices set last_heartbeat_at = now() - make_interval(secs => %s) "
        "where device_id = 'edge-01'",
        (age_s,),
    )
    devices = by_id(client.get(DEVICES_URL, headers=read_key()).json())
    assert devices["edge-01"]["online"] is online
    assert devices["sim-01"]["online"] is False


@pytest.mark.db
def test_last_source_is_the_most_recently_received(client: TestClient, device_keys, db) -> None:
    register(db, "edge-02")
    t0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    insert_inspection(db, "edge-01", "simulated", t0)
    insert_inspection(db, "edge-01", "live", t0 + timedelta(seconds=1))
    insert_inspection(db, "sim-01", "simulated", t0)
    insert_inspection(db, "sim-01", "simulated", t0 + timedelta(seconds=5))
    devices = by_id(client.get(DEVICES_URL, headers=read_key()).json())
    assert devices["edge-01"]["last_source"] == "live"
    assert devices["sim-01"]["last_source"] == "simulated"
    assert devices["edge-02"]["last_source"] is None


@pytest.mark.db
def test_last_source_uses_received_at_not_inspected_at(client: TestClient, device_keys, db) -> None:
    t0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    # The live one was inspected later but received first (an outbox resend).
    insert_inspection(db, "edge-01", "live", t0, inspected_at=t0 + timedelta(hours=1))
    insert_inspection(db, "edge-01", "simulated", t0 + timedelta(seconds=1), inspected_at=t0)
    devices = by_id(client.get(DEVICES_URL, headers=read_key()).json())
    assert devices["edge-01"]["last_source"] == "simulated"


@pytest.mark.db
def test_last_source_tie_on_received_at_uses_inspected_at(
    client: TestClient, device_keys, db
) -> None:
    t0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    insert_inspection(db, "edge-01", "simulated", t0, inspected_at=t0)
    insert_inspection(db, "edge-01", "live", t0, inspected_at=t0 + timedelta(seconds=1))
    devices = by_id(client.get(DEVICES_URL, headers=read_key()).json())
    assert devices["edge-01"]["last_source"] == "live"


@pytest.mark.db
def test_list_devices_order_and_cap(client: TestClient, device_keys, db) -> None:
    with db.cursor() as cursor:
        cursor.executemany(
            "insert into devices (device_id, api_key_hash) values (%s, %s)",
            [(f"d-{n:04d}", f"{n:064x}") for n in range(repository.MAX_DEVICES)],
        )
    # "ab-z" < "ab1" only in the order of a Python str (collate "C"); a locale collation that
    # ignores the hyphen would compare "abz" with "ab1" and put "ab1" first.
    register(db, "ab-z")
    register(db, "ab1")
    items = client.get(DEVICES_URL, headers=read_key()).json()
    ids = [item["device_id"] for item in items]
    assert len(ids) == repository.MAX_DEVICES == 500
    assert ids == sorted(ids)
    assert ids[:2] == ["ab-z", "ab1"]


@pytest.mark.db
@pytest.mark.parametrize(
    "headers",
    [{}, {"X-API-Key": "wrong"}, "device"],
    ids=["missing", "invalid", "device-key"],
)
def test_list_devices_requires_the_read_key(
    client: TestClient, device_keys, headers: dict[str, str] | str
) -> None:
    sent = key(device_keys) if headers == "device" else headers
    response = client.get(DEVICES_URL, headers=sent)
    assert response.status_code == 401
    assert response.json() == INVALID_KEY


# ---------- without a database ----------


def _settings(database_url: str) -> Any:
    from qc_api.config import Settings

    return Settings(DATABASE_URL=database_url, READ_API_KEY=READ_KEY)


@pytest.fixture
def no_db_client(no_db_url: str) -> Iterator[TestClient]:
    with TestClient(create_app(_settings(no_db_url))) as client:
        yield client


def test_routes_without_database_are_503(no_db_client: TestClient) -> None:
    unavailable = {"detail": "Database unavailable"}
    post = no_db_client.post(hb_url(), json=heartbeat(), headers={"X-API-Key": "any-key"})
    assert post.status_code == 503
    assert post.json() == unavailable
    get = no_db_client.get(DEVICES_URL, headers=read_key())
    assert get.status_code == 503
    assert get.json() == unavailable


def test_openapi_heartbeat_accepts_only_json(no_db_client: TestClient) -> None:
    paths = no_db_client.get("/openapi.json").json()["paths"]
    post = paths["/api/v1/devices/{device_id}/heartbeat"]["post"]
    assert list(post["requestBody"]["content"]) == ["application/json"]
    assert "204" in post["responses"]
    assert "get" in paths["/api/v1/devices"]
