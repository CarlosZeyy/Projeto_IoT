"""Telegram alerts against the test PostgreSQL (SPEC-017 sections 4.1 to 4.5, migration 005).

Inspections are inserted with SQL and a controlled ``inspected_at``; ``run_check`` gets ``now``;
Telegram is an ``httpx.MockTransport`` that records the requests. "Out lot" is the scenario of
section 5: 4 ``live`` lots of 10 screws with 1 ``poor`` each, then ``L-005`` with 10 screws and 8
``poor``, its last inspection at ``T``. The bot token is random and built at run time (R-03).
All tests are marked ``db``.
"""

from __future__ import annotations

import json
import logging
import math
import secrets
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from qc_api.config import Settings
from qc_api.db import create_pool
from qc_api.main import create_app
from qc_api.repositories import inspections as repository
from qc_api.services.alerts import run_check

pytestmark = pytest.mark.db

READ_KEY = "r" * 32
SHA = "a" * 64
T = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
MIGRATION = Path(__file__).resolve().parents[2] / "infra" / "migrations" / "005_alerts.sql"

INSERT = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
)
values (%s, %s, %s, %s, 'screw', %s, 1.0, 0.9, 0.8, false, 'partqc-mnv3-v1', %s, 100, %s)
"""


def random_token() -> str:
    bot_id = 100_000 + secrets.randbelow(900_000)
    return f"{bot_id}:{secrets.token_urlsafe(32)[:35]}"


class Recorder:
    """``httpx.MockTransport`` handler: records every request and answers with ``respond``."""

    def __init__(self, respond: Callable[[httpx.Request], httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.respond = respond or (lambda _: httpx.Response(200, json={"ok": True}))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def texts(self) -> list[str]:
        return [json.loads(request.content)["text"] for request in self.requests]


def insert_lot(
    db: psycopg.Connection,
    lot_id: str,
    end: datetime,
    n: int,
    defects: int,
    source: str = "live",
) -> None:
    """``n`` screws one minute apart, the last at ``end``; the first ``defects`` are ``poor``."""
    device_id = "sim-01" if source == "simulated" else "edge-01"
    for i in range(n):
        grade = "poor" if i < defects else "good"
        inspected_at = end - timedelta(minutes=n - 1 - i)
        db.execute(INSERT, (str(uuid.uuid4()), device_id, lot_id, inspected_at, grade, SHA, source))


def insert_out_lot(db: psycopg.Connection, source: str = "live", end: datetime = T) -> None:
    for k in range(1, 5):
        insert_lot(db, f"L-00{k}", end - timedelta(hours=5 - k), 10, 1, source)
    insert_lot(db, "L-005", end, 10, 8, source)


@pytest.fixture
def token() -> str:
    return random_token()


@pytest.fixture
def db(clean_db: str, device_keys: dict[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(clean_db, autocommit=True, prepare_threshold=None) as conn:
        conn.execute("truncate alerts_sent")
        yield conn


@pytest.fixture
def pool(db: psycopg.Connection, clean_db: str) -> Iterator[ConnectionPool]:
    test_pool = create_pool(clean_db)
    test_pool.open(wait=True)
    try:
        yield test_pool
    finally:
        test_pool.close()


@pytest.fixture
def make_settings(clean_db: str, token: str) -> Callable[..., Settings]:
    def _make(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "DATABASE_URL": clean_db,
            "READ_API_KEY": READ_KEY,
            "TELEGRAM_BOT_TOKEN": token,
            "TELEGRAM_CHAT_ID": "-1001",
        }
        values.update(overrides)
        return Settings(**values)

    return _make


def rows(db: psycopg.Connection) -> list[tuple[str, str, str, bool]]:
    return db.execute(
        "select lot_id, source, kind, delivered from alerts_sent order by lot_id, source"
    ).fetchall()


def expected_text(lot_id: str, p: float, p_bar: float, n: int, defects: int, origin: str) -> str:
    spread = 3 * math.sqrt(p_bar * (1 - p_bar) / n)
    ucl, lcl = min(1.0, p_bar + spread), max(0.0, p_bar - spread)
    side = "acima do LSC" if p > ucl else "abaixo do LIC"

    def pct(value: float) -> str:
        return f"{value * 100:.1f}".replace(".", ",") + "%"

    return (
        f"Lote {lot_id} fora de controle ({side}): p = {pct(p)}, LSC = {pct(ucl)}, "
        f"LIC = {pct(lcl)}, n = {n}, defeituosas = {defects}. Origem: {origin}."
    )


# --------------------------------------------------------------------------- send and dedup


def test_out_lot_sends_one_message_and_marks_it_delivered(
    db: psycopg.Connection, pool: ConnectionPool, make_settings: Callable[..., Settings], token: str
) -> None:
    insert_out_lot(db)
    recorder = Recorder()
    sent = run_check(
        pool, make_settings(), now=T + timedelta(minutes=11), transport=recorder.transport()
    )
    assert sent == 1
    (request,) = recorder.requests
    assert request.method == "POST"
    assert request.url.path == f"/bot{token}/sendMessage"
    body = json.loads(request.content)
    assert body["chat_id"] == "-1001"
    assert body["text"] == expected_text("L-005", 0.8, 12 / 50, 10, 8, "real")
    assert body["text"] == (
        "Lote L-005 fora de controle (acima do LSC): p = 80,0%, LSC = 64,5%, LIC = 0,0%, "
        "n = 10, defeituosas = 8. Origem: real."
    )
    assert rows(db) == [("L-005", "live", "out_of_control", True)]
    created_at = db.execute("select created_at from alerts_sent").fetchone()
    assert created_at == (T + timedelta(minutes=11),)

    again = Recorder()
    second = run_check(
        pool, make_settings(), now=T + timedelta(minutes=12), transport=again.transport()
    )
    assert second == 0
    assert again.requests == []


def test_open_lot_and_old_lot_send_nothing(
    db: psycopg.Connection, pool: ConnectionPool, make_settings: Callable[..., Settings]
) -> None:
    insert_out_lot(db)
    recorder = Recorder()
    for now in (T + timedelta(minutes=5), T + timedelta(hours=25)):
        assert run_check(pool, make_settings(), now=now, transport=recorder.transport()) == 0
    assert recorder.requests == []
    assert rows(db) == []


def test_idle_and_lookback_settings_are_used(
    db: psycopg.Connection, pool: ConnectionPool, make_settings: Callable[..., Settings]
) -> None:
    insert_out_lot(db)
    recorder = Recorder()
    s = make_settings(ALERTS_LOT_IDLE_MINUTES="30", ALERTS_LOOKBACK_HOURS="1")
    assert run_check(pool, s, now=T + timedelta(minutes=20), transport=recorder.transport()) == 0
    assert run_check(pool, s, now=T + timedelta(minutes=61), transport=recorder.transport()) == 0
    assert run_check(pool, s, now=T + timedelta(minutes=45), transport=recorder.transport()) == 1
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("failure", ["500", "timeout", "429"])
def test_failed_send_is_kept_undelivered_and_never_retried(
    db: psycopg.Connection,
    pool: ConnectionPool,
    make_settings: Callable[..., Settings],
    failure: str,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(int(failure), json={"ok": False})

    insert_out_lot(db)
    recorder = Recorder(respond)
    now = T + timedelta(minutes=11)
    assert run_check(pool, make_settings(), now=now, transport=recorder.transport()) == 0
    assert rows(db) == [("L-005", "live", "out_of_control", False)]
    assert run_check(pool, make_settings(), now=now, transport=recorder.transport()) == 0
    assert len(recorder.requests) == 1


def test_token_never_reaches_the_logs(
    db: psycopg.Connection,
    pool: ConnectionPool,
    make_settings: Callable[..., Settings],
    token: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for name in (None, "httpx", "httpcore"):
        caplog.set_level(logging.DEBUG, logger=name)
    insert_out_lot(db)
    secret = token.split(":", 1)[1]

    def respond_500(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    def respond_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    for respond in (None, respond_500, respond_timeout):
        db.execute("truncate alerts_sent")
        recorder = Recorder(respond)
        run_check(
            pool, make_settings(), now=T + timedelta(minutes=11), transport=recorder.transport()
        )
        assert len(recorder.requests) == 1
    assert any("bot***" in record.getMessage() for record in caplog.records)
    for record in caplog.records:
        assert token not in record.getMessage()
        assert secret not in record.getMessage()


# --------------------------------------------------------------------------- simulated (R-06)


def test_simulated_needs_the_flag_and_is_marked(
    db: psycopg.Connection, pool: ConnectionPool, make_settings: Callable[..., Settings]
) -> None:
    insert_out_lot(db, source="simulated")
    now = T + timedelta(minutes=11)
    recorder = Recorder()
    assert run_check(pool, make_settings(), now=now, transport=recorder.transport()) == 0
    assert recorder.requests == []
    s = make_settings(ALERTS_INCLUDE_SIMULATED=True)
    assert run_check(pool, s, now=now, transport=recorder.transport()) == 1
    (text,) = recorder.texts()
    assert text.startswith("[SIMULADO] Lote L-005 fora de controle")
    assert text.endswith("Origem: simulado.")
    assert rows(db) == [("L-005", "simulated", "out_of_control", True)]


def test_live_and_simulated_lots_with_the_same_id_are_separate_alerts(
    db: psycopg.Connection, pool: ConnectionPool, make_settings: Callable[..., Settings]
) -> None:
    insert_out_lot(db, source="live")
    insert_out_lot(db, source="simulated")
    recorder = Recorder()
    s = make_settings(ALERTS_INCLUDE_SIMULATED="true")
    assert run_check(pool, s, now=T + timedelta(minutes=11), transport=recorder.transport()) == 2
    texts = recorder.texts()
    assert texts[0].endswith("Origem: real.") and texts[1].startswith("[SIMULADO]")
    assert [row[:2] for row in rows(db)] == [("L-005", "live"), ("L-005", "simulated")]


# --------------------------------------------------------------------------- cap (section 4.3)


def _other_alerts(db: psycopg.Connection, created_at: datetime, count: int = 10) -> None:
    for i in range(count):
        db.execute(
            "insert into alerts_sent (lot_id, source, kind, created_at, delivered) "
            "values (%s, 'live', 'out_of_control', %s, true)",
            (f"OLD-{i:02d}", created_at),
        )


def test_hourly_cap_skips_without_a_row(
    db: psycopg.Connection,
    pool: ConnectionPool,
    make_settings: Callable[..., Settings],
    caplog: pytest.LogCaptureFixture,
) -> None:
    insert_out_lot(db)
    now = T + timedelta(minutes=11)
    _other_alerts(db, now - timedelta(minutes=30))
    caplog.set_level(logging.WARNING, logger="qc_api")
    recorder = Recorder()
    assert run_check(pool, make_settings(), now=now, transport=recorder.transport()) == 0
    assert recorder.requests == []
    assert db.execute("select count(*) from alerts_sent where lot_id = 'L-005'").fetchone() == (0,)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("count=10" in r.getMessage() for r in warnings)


def test_hourly_cap_counts_only_the_last_hour(
    db: psycopg.Connection, pool: ConnectionPool, make_settings: Callable[..., Settings]
) -> None:
    insert_out_lot(db)
    now = T + timedelta(minutes=11)
    _other_alerts(db, now - timedelta(minutes=61))
    recorder = Recorder()
    assert run_check(pool, make_settings(), now=now, transport=recorder.transport()) == 1
    assert len(recorder.requests) == 1


def test_hourly_cap_setting(
    db: psycopg.Connection, pool: ConnectionPool, make_settings: Callable[..., Settings]
) -> None:
    insert_out_lot(db)
    now = T + timedelta(minutes=11)
    _other_alerts(db, now - timedelta(minutes=10), count=2)
    recorder = Recorder()
    s = make_settings(ALERTS_MAX_PER_HOUR=2)
    assert run_check(pool, s, now=now, transport=recorder.transport()) == 0
    s = make_settings(ALERTS_MAX_PER_HOUR=3)
    assert run_check(pool, s, now=now, transport=recorder.transport()) == 1


# --------------------------------------------------------------------------- below the LCL


def test_lot_below_the_lcl(
    db: psycopg.Connection, pool: ConnectionPool, make_settings: Callable[..., Settings]
) -> None:
    for k in range(1, 5):
        insert_lot(db, f"L-00{k}", T - timedelta(hours=5 - k), 20, 8)
    insert_lot(db, "L-009", T, 20, 0)
    recorder = Recorder()
    assert (
        run_check(
            pool, make_settings(), now=T + timedelta(minutes=11), transport=recorder.transport()
        )
        == 1
    )
    (text,) = recorder.texts()
    assert "(abaixo do LIC)" in text and "defeituosas = 0" in text
    assert text == expected_text("L-009", 0.0, 32 / 100, 20, 0, "real")


# --------------------------------------------------------------------------- bounded cost


def test_lot_selection_is_called_with_integer_caps(
    db: psycopg.Connection,
    pool: ConnectionPool,
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insert_out_lot(db)
    insert_out_lot(db, source="simulated")
    calls: list[dict[str, Any]] = []
    original = repository.lot_selection

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append({"args": args, **kwargs})
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "lot_selection", spy)
    s = make_settings(ALERTS_INCLUDE_SIMULATED=True)
    run_check(pool, s, now=T + timedelta(minutes=11), transport=Recorder().transport())
    assert len(calls) == 2
    for call in calls:
        assert type(call["max_points"]) is int and type(call["max_excluded"]) is int
        assert call["max_points"] == 3 and call["max_excluded"] == 0
        assert call["baseline_lots"] == 20 and call["min_lot_size"] == 5
        assert call["args"][2] is None  # every object type
    assert [call["args"][1].value for call in calls] == ["live", "simulated"]


def test_the_alert_lot_must_be_in_the_last_three_points(
    db: psycopg.Connection, pool: ConnectionPool, make_settings: Callable[..., Settings]
) -> None:
    """Accepted risk of section 4.1: an out lot followed by 3 newer lots is out of the window."""
    insert_out_lot(db, end=T - timedelta(hours=4))
    for k in range(6, 9):
        insert_lot(db, f"L-00{k}", T - timedelta(hours=8 - k), 10, 1)
    recorder = Recorder()
    assert (
        run_check(
            pool, make_settings(), now=T + timedelta(minutes=11), transport=recorder.transport()
        )
        == 0
    )


# --------------------------------------------------------------------------- migration 005


def test_alerts_sent_schema(db: psycopg.Connection) -> None:
    rls = db.execute(
        "select relrowsecurity, relforcerowsecurity from pg_class "
        "where oid = 'public.alerts_sent'::regclass"
    ).fetchone()
    assert rls == (True, False)
    policies = db.execute(
        "select count(*) from pg_policies where tablename = 'alerts_sent'"
    ).fetchone()
    assert policies == (0,)
    db.execute(
        "insert into alerts_sent (lot_id, source, kind) values ('L-001', 'live', 'out_of_control')"
    )
    row = db.execute("select delivered, created_at is not null from alerts_sent").fetchone()
    assert row == (False, True)
    with pytest.raises(psycopg.errors.UniqueViolation) as duplicate:
        db.execute(
            "insert into alerts_sent (lot_id, source, kind) "
            "values ('L-001', 'live', 'out_of_control')"
        )
    assert duplicate.value.sqlstate == "23505"


@pytest.mark.parametrize(
    ("lot_id", "source", "kind"),
    [
        ("L-001", "live", "other"),
        ("L-001", "real", "out_of_control"),
        ("L 001", "live", "out_of_control"),
        ("L-001\n", "live", "out_of_control"),
        ("L" * 41, "live", "out_of_control"),
        ("", "live", "out_of_control"),
    ],
)
def test_alerts_sent_checks(db: psycopg.Connection, lot_id: str, source: str, kind: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation) as refused:
        db.execute(
            "insert into alerts_sent (lot_id, source, kind) values (%s, %s, %s)",
            (lot_id, source, kind),
        )
    assert refused.value.sqlstate == "23514"


def test_migration_runs_again_without_changes(db: psycopg.Connection) -> None:
    query = (
        "select conname, pg_get_constraintdef(oid) from pg_constraint "
        "where conrelid = 'alerts_sent'::regclass order by 1"
    )
    before = db.execute(query).fetchall()
    db.execute(MIGRATION.read_text(encoding="utf-8"))
    assert db.execute(query).fetchall() == before


# --------------------------------------------------------------------------- app (CA-04)


def test_app_with_alerts_and_a_failing_telegram_still_ingests(
    db: psycopg.Connection,
    make_settings: Callable[..., Settings],
    make_payload: Callable[..., dict[str, Any]],
    device_keys: dict[str, str],
) -> None:
    """The loop checks at start (real clock): one failed send, then a 201 for the device."""
    insert_out_lot(db, end=datetime.now(UTC) - timedelta(minutes=11))
    recorder = Recorder(lambda _: httpx.Response(500, json={"ok": False}))
    s = make_settings(ALERTS_ENABLED="true")
    app = create_app(s, alerts_transport=recorder.transport())
    with TestClient(app) as client:
        deadline = time.monotonic() + 15
        while not recorder.requests and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(recorder.requests) == 1
        response = client.post(
            "/api/v1/inspections",
            json=make_payload(),
            headers={"X-API-Key": device_keys["edge-01"]},
        )
        assert response.status_code == 201
        assert s.TELEGRAM_BOT_TOKEN.get_secret_value() not in response.text
    for _ in range(100):
        if rows(db):
            break
        time.sleep(0.05)
    assert rows(db) == [("L-005", "live", "out_of_control", False)]
