"""Acceptance tests for SPEC-018 (database and qc-api: device heartbeat and device status).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-02 to CA-07. Tests named ``test_extra_*`` are exploratory edge cases
around SPEC-018 sections 4.2 and 4.3 that no CA spells out.

Every test uses the migrated test database of the ``db`` marker (``clean_db`` from SPEC-003);
devices are registered by hash with plain SQL, and the server clock is "moved" by writing
``last_heartbeat_at`` directly (SPEC-018 section 5, common context). Device keys are generated
at run time, never written as literals (R-03).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from qc_api.config import Settings
from qc_api.main import create_app
from qc_contracts import MAX_HEARTBEAT_COUNT, DeviceStatus

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "infra" / "migrations"

R = "r" * 32
SHA = "d" * 64
DEVICES_URL = "/api/v1/devices"
INSPECTIONS_URL = "/api/v1/inspections"
BATCH_URL = "/api/v1/inspections/batch"
HB_COLUMNS = {
    "last_heartbeat_at": "timestamp with time zone",
    "hb_sent_at": "timestamp with time zone",
    "hb_model_version": "text",
    "hb_model_sha256": "text",
    "hb_app_version": "text",
    "hb_uptime_s": "integer",
    "hb_outbox_pending": "integer",
    "hb_outbox_dead": "integer",
}


def hb_url(device_id: str) -> str:
    return f"{DEVICES_URL}/{device_id}/heartbeat"


def connect(conninfo: str) -> psycopg.Connection:
    return psycopg.connect(conninfo, autocommit=True, prepare_threshold=None)


def heartbeat(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "sent_at": (datetime.now(UTC) - timedelta(seconds=2)).isoformat(),
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "app_version": "0.0.0",
        "uptime_s": 600,
        "outbox_pending": 0,
        "outbox_dead": 0,
    }
    data.update(overrides)
    return data


def inspection(device_id: str, source: str) -> dict[str, Any]:
    return {
        "inspection_id": str(uuid.uuid4()),
        "device_id": device_id,
        "lot_id": "L-018",
        "inspected_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "object_type": "screw",
        "grade": "good",
        "grade_score": 1.0,
        "type_confidence": 0.9,
        "grade_confidence": 0.8,
        "needs_review": False,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "latency_ms": 30,
        "source": source,
    }


@dataclass
class Env:
    db: str
    client: TestClient
    keys: dict[str, str]

    def beat(self, device_id: str, body: Any, key_of: str | None = None) -> Any:
        key = self.keys[key_of or device_id]
        return self.client.post(hb_url(device_id), json=body, headers={"X-API-Key": key})

    def devices(self, key: str | None = R) -> Any:
        headers = {} if key is None else {"X-API-Key": key}
        return self.client.get(DEVICES_URL, headers=headers)

    def by_id(self) -> dict[str, dict[str, Any]]:
        resp = self.devices()
        assert resp.status_code == 200, resp.text
        return {item["device_id"]: item for item in resp.json()}

    def row(self, device_id: str) -> dict[str, Any]:
        with connect(self.db) as conn:
            cur = conn.execute("select * from devices where device_id = %s", (device_id,))
            names = [d.name for d in cur.description or []]
            values = cur.fetchone()
        assert values is not None
        return dict(zip(names, values, strict=True))


def register(conninfo: str, device_ids: list[str]) -> dict[str, str]:
    keys = {d: secrets.token_urlsafe(32) for d in device_ids}
    with connect(conninfo) as conn:
        for device_id, key in keys.items():
            conn.execute(
                "insert into devices (device_id, api_key_hash) values (%s, %s)",
                (device_id, hashlib.sha256(key.encode()).hexdigest()),
            )
    return keys


@pytest.fixture
def env(clean_db: str) -> Iterator[Env]:
    keys = register(clean_db, ["edge-01", "sim-01", "edge-02"])
    app = create_app(Settings(DATABASE_URL=clean_db, READ_API_KEY=R))
    with TestClient(app) as client:
        yield Env(clean_db, client, keys)


def set_heartbeat_age(env: Env, device_id: str, seconds: int) -> None:
    with connect(env.db) as conn:
        conn.execute(
            "update devices set last_heartbeat_at = now() - make_interval(secs => %s) "
            "where device_id = %s",
            (seconds, device_id),
        )


# --------------------------------------------------------------------------- CA-02


@pytest.mark.db
def test_ca02_heartbeat_204_and_listed_online(env: Env) -> None:
    resp = env.beat("edge-01", heartbeat(outbox_pending=3))
    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    listed = env.devices()
    assert listed.status_code == 200, listed.text
    items = {i["device_id"]: i for i in listed.json()}
    edge = items["edge-01"]
    assert edge["online"] is True
    assert edge["outbox_pending"] == 3
    assert edge["last_heartbeat_at"] is not None
    for item in listed.json():
        DeviceStatus.model_validate(item)


# --------------------------------------------------------------------------- CA-03


@pytest.mark.db
def test_ca03_key_of_another_device_is_403(env: Env) -> None:
    resp = env.beat("sim-01", heartbeat(), key_of="edge-01")
    assert resp.status_code == 403, resp.text
    assert env.row("sim-01")["last_heartbeat_at"] is None


@pytest.mark.db
def test_ca03_without_key_is_401(env: Env) -> None:
    resp = env.client.post(hb_url("edge-01"), json=heartbeat())
    assert resp.status_code == 401, resp.text


@pytest.mark.db
def test_ca03_invalid_key_is_401(env: Env) -> None:
    wrong = secrets.token_urlsafe(32)
    resp = env.client.post(hb_url("edge-01"), json=heartbeat(), headers={"X-API-Key": wrong})
    assert resp.status_code == 401, resp.text
    assert wrong not in resp.text


@pytest.mark.db
def test_ca03_extra_field_is_422_and_body_not_logged(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = "marker" + secrets.token_hex(8)
    app_marker = "appv" + secrets.token_hex(6)
    body = heartbeat(extra_field=marker, app_version=app_marker, uptime_s=987654)
    resp = env.beat("edge-01", body)
    assert resp.status_code == 422, resp.text
    assert env.row("edge-01")["last_heartbeat_at"] is None
    text = "\n".join(r.getMessage() for r in caplog.records) + caplog.text
    assert marker not in text
    assert app_marker not in text
    assert "987654" not in text
    assert json.dumps(body) not in text


@pytest.mark.db
def test_ca03_device_id_outside_pattern_is_422(env: Env) -> None:
    resp = env.client.post(
        hb_url("EDGE_01"), json=heartbeat(), headers={"X-API-Key": env.keys["edge-01"]}
    )
    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- CA-04


@pytest.mark.db
def test_ca04_online_window_179_and_181_seconds(env: Env) -> None:
    assert env.beat("edge-01", heartbeat()).status_code == 204
    set_heartbeat_age(env, "edge-01", 179)
    assert env.by_id()["edge-01"]["online"] is True
    set_heartbeat_age(env, "edge-01", 181)
    item = env.by_id()["edge-01"]
    assert item["online"] is False
    assert item["last_heartbeat_at"] is not None


@pytest.mark.db
def test_ca04_device_without_heartbeat_is_offline(env: Env) -> None:
    item = env.by_id()["edge-02"]
    assert item["online"] is False
    assert item["last_heartbeat_at"] is None


# --------------------------------------------------------------------------- CA-05


@pytest.mark.db
def test_ca05_last_source_is_the_most_recent_inspection(env: Env) -> None:
    post = env.client.post
    for device_id, source in (("edge-01", "simulated"), ("edge-01", "live")):
        resp = post(
            INSPECTIONS_URL,
            json=inspection(device_id, source),
            headers={"X-API-Key": env.keys[device_id]},
        )
        assert resp.status_code == 201, resp.text
    # Make "received before" unambiguous, whatever the clock resolution.
    with connect(env.db) as conn:
        conn.execute(
            "update inspections set received_at = received_at - interval '1 minute' "
            "where device_id = 'edge-01' and source = 'simulated'"
        )
    for _ in range(2):
        resp = post(
            INSPECTIONS_URL,
            json=inspection("sim-01", "simulated"),
            headers={"X-API-Key": env.keys["sim-01"]},
        )
        assert resp.status_code == 201, resp.text
    items = env.by_id()
    assert items["edge-01"]["last_source"] == "live"
    assert items["sim-01"]["last_source"] == "simulated"
    assert items["edge-02"]["last_source"] is None


# --------------------------------------------------------------------------- CA-06


@pytest.mark.db
def test_ca06_list_without_read_key_is_401(env: Env) -> None:
    assert env.devices(key=None).status_code == 401


@pytest.mark.db
def test_ca06_list_with_a_device_key_is_401(env: Env) -> None:
    resp = env.devices(key=env.keys["edge-01"])
    assert resp.status_code == 401, resp.text


# --------------------------------------------------------------------------- CA-07


@pytest.mark.db
def test_ca07_negative_uptime_is_refused_by_the_database(env: Env) -> None:
    with connect(env.db) as conn, pytest.raises(psycopg.Error) as info:
        conn.execute("update devices set hb_uptime_s = -1 where device_id = 'edge-01'")
    assert info.value.sqlstate == "23514"


@pytest.mark.db
def test_ca07_model_version_without_sha_is_refused_by_the_database(env: Env) -> None:
    with connect(env.db) as conn, pytest.raises(psycopg.Error) as info:
        conn.execute(
            "update devices set hb_model_version = 'partqc-mnv3-v1', hb_model_sha256 = null "
            "where device_id = 'edge-01'"
        )
    assert info.value.sqlstate == "23514"


# --------------------------------------------------------------------------- extras: §4.2


@pytest.mark.db
def test_extra_heartbeat_columns_are_nullable_with_the_spec_types(clean_db: str) -> None:
    with connect(clean_db) as conn:
        cols = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                """
                select a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull
                from pg_attribute a
                where a.attrelid = 'public.devices'::regclass and a.attnum > 0
                  and not a.attisdropped
                """
            )
        }
    for name, type_name in HB_COLUMNS.items():
        assert cols.get(name) == (type_name, False), (name, cols.get(name))
    assert set(cols) == {"device_id", "api_key_hash", "created_at", "last_seen_at", *HB_COLUMNS}


@pytest.mark.db
@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("hb_outbox_pending", -1),
        ("hb_outbox_dead", -1),
        ("hb_app_version", "1.0\n"),
        ("hb_app_version", ""),
        ("hb_app_version", "A" * 41),
        ("hb_app_version", "1.0 beta"),
        ("hb_app_version", "versão"),
        ("hb_app_version", "\uff11.0"),
    ],
)
def test_extra_database_checks_mirror_the_contract(env: Env, column: str, value: Any) -> None:
    with connect(env.db) as conn, pytest.raises(psycopg.Error) as info:
        conn.execute(
            f"update devices set {column} = %s where device_id = 'edge-01'",  # noqa: S608
            (value,),
        )
    assert info.value.sqlstate == "23514"


@pytest.mark.db
@pytest.mark.parametrize(
    ("version", "sha"),
    [
        ("PartQC-v1", SHA),
        ("partqc-mnv3-v1\n", SHA),
        ("partqc-mnv3-v1", "D" * 64),
        ("partqc-mnv3-v1", "d" * 63),
        (None, SHA),
    ],
)
def test_extra_database_model_checks(env: Env, version: str | None, sha: str) -> None:
    with connect(env.db) as conn, pytest.raises(psycopg.Error) as info:
        conn.execute(
            "update devices set hb_model_version = %s, hb_model_sha256 = %s "
            "where device_id = 'edge-01'",
            (version, sha),
        )
    assert info.value.sqlstate == "23514"


@pytest.mark.db
def test_extra_database_accepts_the_contract_limits(env: Env) -> None:
    with connect(env.db) as conn:
        conn.execute(
            "update devices set hb_uptime_s = %s, hb_outbox_pending = 0, hb_outbox_dead = %s, "
            "hb_app_version = %s, hb_model_version = null, hb_model_sha256 = null "
            "where device_id = 'edge-01'",
            (MAX_HEARTBEAT_COUNT, MAX_HEARTBEAT_COUNT, "A" * 40),
        )


def _heartbeat_migration() -> Path:
    (path,) = sorted(MIGRATIONS.glob("*_device_heartbeat.sql"))
    return path


@pytest.mark.db
def test_extra_heartbeat_migration_runs_again_without_error(env: Env) -> None:
    assert env.beat("edge-01", heartbeat(outbox_pending=4)).status_code == 204
    sql = _heartbeat_migration().read_text(encoding="utf-8")
    query = (
        "select count(*) from pg_constraint "
        "where conrelid = 'public.devices'::regclass and contype = 'c'"
    )
    with connect(env.db) as conn:
        before = conn.execute(query).fetchone()
        conn.execute(sql)
        conn.execute(sql)
        after = conn.execute(query).fetchone()
    assert before == after
    assert env.row("edge-01")["hb_outbox_pending"] == 4


def test_extra_heartbeat_migration_is_the_next_free_number() -> None:
    numbers = sorted(int(p.name.split("_", 1)[0]) for p in MIGRATIONS.glob("[0-9]*.sql"))
    assert numbers == list(range(1, len(numbers) + 1))
    assert _heartbeat_migration().name.startswith("004_")


# --------------------------------------------------------------------------- extras: §4.3


@pytest.mark.db
def test_extra_heartbeat_stores_the_body_and_server_times(env: Env) -> None:
    sent = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)  # far in the past: diagnostic only
    before = datetime.now(UTC)
    body = heartbeat(
        sent_at=sent.isoformat(), uptime_s=7500, outbox_pending=2, outbox_dead=1, app_version="1.2"
    )
    assert env.beat("edge-01", body).status_code == 204
    after = datetime.now(UTC)
    row = env.row("edge-01")
    slack = timedelta(seconds=2)
    assert before - slack <= row["last_heartbeat_at"] <= after + slack
    assert before - slack <= row["last_seen_at"] <= after + slack
    assert row["hb_sent_at"] == sent
    assert row["hb_model_version"] == "partqc-mnv3-v1"
    assert row["hb_model_sha256"] == SHA
    assert row["hb_app_version"] == "1.2"
    assert (row["hb_uptime_s"], row["hb_outbox_pending"], row["hb_outbox_dead"]) == (7500, 2, 1)

    item = env.by_id()["edge-01"]
    assert item["online"] is True  # server clock, not the old sent_at
    assert item["uptime_s"] == 7500
    assert item["outbox_dead"] == 1
    assert item["model_version"] == "partqc-mnv3-v1"
    assert item["app_version"] == "1.2"
    assert item["last_seen_at"] is not None
    assert item["last_source"] is None


@pytest.mark.db
def test_extra_second_heartbeat_overwrites_and_clears_the_model(env: Env) -> None:
    assert env.beat("edge-01", heartbeat(outbox_pending=5)).status_code == 204
    body = heartbeat(model_version=None, model_sha256=None, outbox_pending=0)
    assert env.beat("edge-01", body).status_code == 204
    row = env.row("edge-01")
    assert row["hb_model_version"] is None and row["hb_model_sha256"] is None
    assert row["hb_outbox_pending"] == 0
    item = env.by_id()["edge-01"]
    assert item["model_version"] is None and item["model_sha256"] is None


@pytest.mark.db
def test_extra_refused_heartbeats_do_not_touch_last_seen_at(env: Env) -> None:
    env.beat("edge-01", heartbeat(uptime_s=-1))  # 422
    env.beat("sim-01", heartbeat(), key_of="edge-01")  # 403
    env.client.post(hb_url("edge-01"), json=heartbeat())  # 401
    for device_id in ("edge-01", "sim-01"):
        row = env.row(device_id)
        assert row["last_seen_at"] is None and row["last_heartbeat_at"] is None, device_id


@pytest.mark.db
@pytest.mark.parametrize(
    "overrides",
    [
        {"sent_at": "2026-11-02T10:00:00"},
        {"uptime_s": MAX_HEARTBEAT_COUNT + 1},
        {"outbox_dead": -1},
        {"app_version": "1.0\n"},
        {"model_sha256": None},
        {"image": "AAAA"},
    ],
)
def test_extra_invalid_bodies_are_422(env: Env, overrides: dict[str, Any]) -> None:
    resp = env.beat("edge-01", heartbeat(**overrides))
    assert resp.status_code == 422, resp.text
    assert "Traceback" not in resp.text


@pytest.mark.db
def test_extra_future_sent_at_is_422(env: Env) -> None:
    future = (datetime.now(UTC) + timedelta(minutes=6)).isoformat()
    assert env.beat("edge-01", heartbeat(sent_at=future)).status_code == 422


@pytest.mark.db
def test_extra_not_json_is_422(env: Env) -> None:
    resp = env.client.post(
        hb_url("edge-01"),
        content=b"not json",
        headers={"X-API-Key": env.keys["edge-01"], "Content-Type": "application/json"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.db
def test_extra_authentication_comes_before_validation(env: Env) -> None:
    """SPEC-004 precedence: 401 before 422 before 403."""
    assert env.client.post(hb_url("edge-01"), json={"x": 1}).status_code == 401
    bad = env.client.post(
        hb_url("sim-01"), json={"x": 1}, headers={"X-API-Key": env.keys["edge-01"]}
    )
    assert bad.status_code == 422


@pytest.mark.db
def test_extra_body_limit_is_413(env: Env) -> None:
    body = heartbeat(app_version="x" * (300 * 1024))
    resp = env.beat("edge-01", body)
    assert resp.status_code == 413, resp.text
    assert env.row("edge-01")["last_heartbeat_at"] is None


@pytest.mark.db
@pytest.mark.parametrize("device_id", ["ab", "a" * 33, "edge_01", "edge-01%0A", "Edge-01"])
def test_extra_path_device_ids_outside_pattern(env: Env, device_id: str) -> None:
    resp = env.client.post(
        hb_url(device_id), json=heartbeat(), headers={"X-API-Key": env.keys["edge-01"]}
    )
    assert resp.status_code == 422, (device_id, resp.status_code, resp.text)


@pytest.mark.db
def test_extra_unregistered_device_in_path_is_403(env: Env) -> None:
    resp = env.beat("ghost-01", heartbeat(), key_of="edge-01")
    assert resp.status_code == 403, resp.text


@pytest.mark.db
def test_extra_read_key_cannot_send_heartbeat(env: Env) -> None:
    resp = env.client.post(hb_url("edge-01"), json=heartbeat(), headers={"X-API-Key": R})
    assert resp.status_code == 401, resp.text


@pytest.mark.db
def test_extra_wrong_read_key_is_401(env: Env) -> None:
    assert env.devices(key="s" * 32).status_code == 401
    assert env.devices(key="").status_code == 401


@pytest.mark.db
def test_extra_keys_never_reach_the_log(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    env.beat("edge-01", heartbeat())
    env.beat("sim-01", heartbeat(), key_of="edge-01")
    env.devices()
    text = caplog.text
    for key in env.keys.values():
        assert key not in text
        assert hashlib.sha256(key.encode()).hexdigest() not in text
    assert R not in text


@pytest.mark.db
def test_extra_list_is_sorted_by_device_id_and_capped_at_500(env: Env) -> None:
    with connect(env.db) as conn:
        for i in range(510):
            conn.execute(
                "insert into devices (device_id, api_key_hash) values (%s, %s)",
                (f"dev-{i:04d}", secrets.token_hex(32)),
            )
    resp = env.devices()
    assert resp.status_code == 200, resp.text
    ids = [i["device_id"] for i in resp.json()]
    assert len(ids) == 500
    assert ids == sorted(ids)
    everything = sorted([*(f"dev-{i:04d}" for i in range(510)), "edge-01", "edge-02", "sim-01"])
    assert ids == everything[:500]


@pytest.mark.db
def test_extra_empty_list(clean_db: str) -> None:
    with TestClient(create_app(Settings(DATABASE_URL=clean_db, READ_API_KEY=R))) as client:
        resp = client.get(DEVICES_URL, headers={"X-API-Key": R})
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.db
def test_extra_last_source_follows_received_at_not_inspected_at(env: Env) -> None:
    """A late live inspection (old ``inspected_at``) received last still wins."""
    old = inspection("edge-01", "live")
    old["inspected_at"] = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    new = inspection("edge-01", "simulated")
    headers = {"X-API-Key": env.keys["edge-01"]}
    assert env.client.post(INSPECTIONS_URL, json=new, headers=headers).status_code == 201
    with connect(env.db) as conn:
        conn.execute("update inspections set received_at = received_at - interval '1 minute'")
    assert env.client.post(INSPECTIONS_URL, json=old, headers=headers).status_code == 201
    assert env.by_id()["edge-01"]["last_source"] == "live"


@pytest.mark.db
def test_extra_batch_inspection_also_sets_last_source(env: Env) -> None:
    body = {"items": [inspection("edge-02", "simulated")]}
    resp = env.client.post(BATCH_URL, json=body, headers={"X-API-Key": env.keys["edge-02"]})
    assert resp.status_code == 200, resp.text
    item = env.by_id()["edge-02"]
    assert item["last_source"] == "simulated"
    assert item["online"] is False  # an inspection is not a heartbeat
    assert item["last_heartbeat_at"] is None
    assert item["last_seen_at"] is not None


@pytest.mark.db
def test_extra_heartbeat_routes_in_openapi(env: Env) -> None:
    spec = env.client.get("/openapi.json").json()
    paths = spec["paths"]
    hb = next(p for p in paths if re.fullmatch(r"/api/v1/devices/\{[a-z_]+\}/heartbeat", p))
    assert "post" in paths[hb]
    assert "get" in paths[DEVICES_URL]
    assert "204" in paths[hb]["post"]["responses"]
