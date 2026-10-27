"""Acceptance tests for SPEC-017 (qc-api: Telegram alerts for out-of-control lots).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-01 to CA-12 (CA-13 is manual, on the VPS). Tests named
``test_extra_*`` are exploratory edge cases around sections 4.1 to 4.6 that no CA spells out.

* Telegram is never called: every test hands a ``httpx.MockTransport`` (or a transport that
  redirects to a local socket) to ``run_check`` or ``create_app``, and records the requests.
* The bot token is built at run time. The CA token (``"123456:" + "A" * 35``) is fixed by the
  SPEC common context; the other ones come from ``secrets`` (R-03, no credential literal).
* Inspections are inserted with plain SQL and a controlled ``inspected_at``. ``T`` (the last
  inspection of ``L-005``) is the real clock minus 11 minutes, so ``now = T + 11 min`` is also
  the real clock, which keeps the tests that go through the app ``lifespan`` meaningful.
* ``clean_db`` does not empty ``alerts_sent``: the ``db`` fixture below truncates it.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import math
import re
import secrets
import socket
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlunsplit

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

import qc_api.repositories.inspections as inspections_repository
from qc_api.auth import hash_api_key
from qc_api.config import Settings
from qc_api.db import create_pool
from qc_api.main import create_app
from qc_api.services.alerts import run_check

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
ALERTS_SOURCE = ROOT / "api" / "src" / "qc_api" / "services" / "alerts.py"

READ_KEY = "r" * 32
SHA = "e" * 64
SECRET_PART = "A" * 35
TOKEN = "123456" + ":" + SECRET_PART  # SPEC-017 section 5, common context
CHAT_ID = "-1001"
INSPECTIONS_URL = "/api/v1/inspections"
SPC_URL = "/api/v1/metrics/spc"
HEALTH_URL = "/api/v1/health"
INVALID_CONFIG = "alerts disabled: invalid configuration"
INVALID_CONFIG_LINE = re.compile(r"alerts disabled: invalid configuration \(([A-Z_, ]+)\)")
DEVICE = "edge-01"


# --------------------------------------------------------------------------- helpers


def connect(conninfo: str) -> psycopg.Connection:
    return psycopg.connect(conninfo, autocommit=True, prepare_threshold=None)


def pct(value: float) -> str:
    """Percentage with 1 decimal and a decimal comma (SPEC-017 section 4.4)."""
    return f"{value * 100:.1f}".replace(".", ",") + "%"


def chart_limits(lots: list[tuple[int, int]], n: int) -> tuple[float, float]:
    """``(ucl, lcl)`` of docs/architecture.md section 3.4 for a lot of size ``n``."""
    p_bar = sum(d for _, d in lots) / sum(size for size, _ in lots)
    sigma = math.sqrt(p_bar * (1 - p_bar) / n)
    return min(1.0, p_bar + 3 * sigma), max(0.0, p_bar - 3 * sigma)


def closed_port_url(password: str) -> str:
    return urlunsplit(("postgresql", f"u:{password}@127.0.0.1:1", "/x", "", ""))


def random_token() -> str:
    return f"{secrets.randbelow(10**9) + 10**8}:{secrets.token_urlsafe(30)}"


def settings(conninfo: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "DATABASE_URL": conninfo,
        "READ_API_KEY": READ_KEY,
        "TELEGRAM_BOT_TOKEN": TOKEN,
        "TELEGRAM_CHAT_ID": CHAT_ID,
    }
    values.update(overrides)
    return Settings(**values)


class Telegram:
    """Fake Telegram Bot API behind a ``httpx.MockTransport``; records every request."""

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.requests: list[httpx.Request] = []
        self._lock = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        request.read()
        with self._lock:
            self.requests.append(request)
        if self.mode == "ok":
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        if self.mode == "500":
            return httpx.Response(500, json={"ok": False, "error_code": 500})
        if self.mode == "timeout":
            # The message carries the URL (with the token) on purpose: it must never be logged.
            raise httpx.ConnectTimeout(f"timed out connecting to {request.url}", request=request)
        if self.mode == "429":
            return httpx.Response(429, json={"ok": False, "error_code": 429})
        if self.mode == "ok-false":
            return httpx.Response(200, json={"ok": False, "error_code": 400})
        if self.mode == "not-json":
            return httpx.Response(200, text="<html>ok</html>")
        if self.mode == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.invalid/x"})
        raise AssertionError(self.mode)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def texts(self) -> list[str]:
        import json

        return [json.loads(r.content)["text"] for r in self.requests]


def add_lot(
    conninfo: str,
    lot_id: str,
    end: datetime,
    n: int,
    defects: int,
    *,
    source: str = "live",
    step: timedelta = timedelta(seconds=1),
) -> None:
    """``n`` ``screw`` inspections of ``lot_id``, the last one at ``end``; ``defects`` are poor."""
    rows = []
    for k in range(n):
        rows.append(
            (
                str(uuid.uuid4()),
                DEVICE,
                lot_id,
                end - step * (n - 1 - k),
                "screw",
                "poor" if k < defects else "good",
                1.0,
                0.9,
                0.8,
                False,
                "partqc-mnv3-v1",
                SHA,
                30,
                source,
            )
        )
    with connect(conninfo) as conn, conn.cursor() as cur:
        cur.executemany(
            "insert into inspections (inspection_id, device_id, lot_id, inspected_at, "
            "object_type, grade, grade_score, type_confidence, grade_confidence, needs_review, "
            "model_version, model_sha256, latency_ms, source) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            rows,
        )


def add_out_lot(conninfo: str, t: datetime, *, source: str = "live") -> None:
    """The "lote fora" of SPEC-017 section 5: 4 lots 10/1, then ``L-005`` 10/8 ending at ``t``."""
    for i in range(1, 5):
        add_lot(conninfo, f"L-00{i}", t - timedelta(hours=5 - i), 10, 1, source=source)
    add_lot(conninfo, "L-005", t, 10, 8, source=source)


def alerts_rows(conninfo: str) -> list[tuple[str, str, str, bool]]:
    with connect(conninfo) as conn:
        return conn.execute(
            "select lot_id, source, kind, delivered from alerts_sent order by lot_id, source"
        ).fetchall()


def add_alert_rows(conninfo: str, created_at: datetime, count: int = 10) -> None:
    with connect(conninfo) as conn:
        for i in range(count):
            conn.execute(
                "insert into alerts_sent (lot_id, source, kind, created_at, delivered) "
                "values (%s, 'live', 'out_of_control', %s, true)",
                (f"OLD-{i:03d}", created_at),
            )


def wait_for(predicate: Callable[[], bool], timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def record_texts(caplog: pytest.LogCaptureFixture) -> list[str]:
    formatter = logging.Formatter("%(name)s %(levelname)s %(message)s")
    return [formatter.format(r) for r in caplog.records]


def capture_everything(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="httpx")
    caplog.set_level(logging.DEBUG, logger="httpcore")


@contextmanager
def running_app(app_settings: Settings, transport: httpx.BaseTransport) -> Iterator[Any]:
    app = create_app(app_settings, alerts_transport=transport)
    with TestClient(app) as client:
        yield app, client


def alert_tasks(client: TestClient) -> list[str]:
    def names() -> list[str]:
        found = []
        for task in asyncio.all_tasks():
            label = f"{task.get_name()} {task.get_coro()!r}"
            if "alert" in label.lower():
                found.append(label)
        return found

    return client.portal.call(names)


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def db(clean_db: str) -> str:
    with connect(clean_db) as conn:
        conn.execute("truncate alerts_sent")
        conn.execute(
            "insert into devices (device_id, api_key_hash) values (%s, %s)",
            (DEVICE, hash_api_key(secrets.token_urlsafe(32))),
        )
    return clean_db


@pytest.fixture
def pool(db: str) -> Iterator[Any]:
    p = create_pool(db)
    p.open(wait=True)
    try:
        yield p
    finally:
        p.close()


@pytest.fixture
def t_end() -> datetime:
    """``T`` of the SPEC: the last inspection of ``L-005`` (real clock minus 11 minutes)."""
    return datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=11)


def expected_text(source: str = "live") -> str:
    ucl, lcl = chart_limits([(10, 1)] * 4 + [(10, 8)], 10)
    origin = "real" if source == "live" else "simulado"
    prefix = "[SIMULADO] " if source == "simulated" else ""
    return (
        f"{prefix}Lote L-005 fora de controle (acima do LSC): p = 80,0%, LSC = {pct(ucl)}, "
        f"LIC = {pct(lcl)}, n = 10, defeituosas = 8. Origem: {origin}."
    )


# --------------------------------------------------------------------------- CA-01


@pytest.mark.db
def test_ca01_out_lot_sends_one_message(db: str, pool: Any, t_end: datetime) -> None:
    add_out_lot(db, t_end)
    telegram = Telegram()
    sent = run_check(
        pool, settings(db), now=t_end + timedelta(minutes=11), transport=telegram.transport
    )
    assert sent == 1
    assert len(telegram.requests) == 1
    request = telegram.requests[0]
    assert request.method == "POST"
    assert request.url.scheme == "https"
    assert request.url.host == "api.telegram.org"
    assert request.url.path == f"/bot{TOKEN}/sendMessage"
    import json

    body = json.loads(request.content)
    assert body["chat_id"] in (-1001, "-1001")
    assert body["text"] == expected_text()
    assert alerts_rows(db) == [("L-005", "live", "out_of_control", True)]


@pytest.mark.db
def test_ca01_limits_match_the_spec006_chart(db: str, pool: Any, t_end: datetime) -> None:
    """``<ucl>`` and ``<lcl>`` of the text are the ones of the SPEC-006 chart for these lots."""
    add_out_lot(db, t_end)
    with TestClient(create_app(settings(db))) as client:
        resp = client.get(SPC_URL, params={"source": "live"}, headers={"X-API-Key": READ_KEY})
    assert resp.status_code == 200, resp.text
    (point,) = [p for p in resp.json()["points"] if p["lot_id"] == "L-005"]
    assert point["out_of_control"] is True
    telegram = Telegram()
    run_check(pool, settings(db), now=t_end + timedelta(minutes=11), transport=telegram.transport)
    (text,) = telegram.texts()
    assert f"LSC = {pct(point['ucl'])}, LIC = {pct(point['lcl'])}," in text


# --------------------------------------------------------------------------- CA-02


@pytest.mark.db
def test_ca02_second_check_sends_nothing(db: str, pool: Any, t_end: datetime) -> None:
    add_out_lot(db, t_end)
    first = Telegram()
    assert (
        run_check(pool, settings(db), now=t_end + timedelta(minutes=11), transport=first.transport)
        == 1
    )
    second = Telegram()
    sent = run_check(
        pool, settings(db), now=t_end + timedelta(minutes=12), transport=second.transport
    )
    assert sent == 0
    assert second.requests == []
    assert alerts_rows(db) == [("L-005", "live", "out_of_control", True)]


# --------------------------------------------------------------------------- CA-03


@pytest.mark.db
def test_ca03_open_lot_and_old_lot_send_nothing(db: str, pool: Any, t_end: datetime) -> None:
    add_out_lot(db, t_end)
    telegram = Telegram()
    assert (
        run_check(
            pool, settings(db), now=t_end + timedelta(minutes=5), transport=telegram.transport
        )
        == 0
    )
    assert telegram.requests == []
    assert alerts_rows(db) == []
    assert (
        run_check(pool, settings(db), now=t_end + timedelta(hours=25), transport=telegram.transport)
        == 0
    )
    assert telegram.requests == []
    assert alerts_rows(db) == []


# --------------------------------------------------------------------------- CA-04


@pytest.mark.db
@pytest.mark.parametrize("mode", ["500", "timeout"])
def test_ca04_telegram_failure_is_one_attempt(
    db: str, pool: Any, t_end: datetime, mode: str
) -> None:
    add_out_lot(db, t_end)
    telegram = Telegram(mode)
    sent = run_check(
        pool, settings(db), now=t_end + timedelta(minutes=11), transport=telegram.transport
    )
    assert sent == 0
    assert len(telegram.requests) == 1
    assert alerts_rows(db) == [("L-005", "live", "out_of_control", False)]
    again = run_check(
        pool, settings(db), now=t_end + timedelta(minutes=12), transport=telegram.transport
    )
    assert again == 0
    assert len(telegram.requests) == 1
    assert alerts_rows(db) == [("L-005", "live", "out_of_control", False)]


@pytest.mark.db
@pytest.mark.parametrize("mode", ["500", "timeout"])
def test_ca04_failing_telegram_does_not_affect_ingestion(
    db: str, t_end: datetime, mode: str
) -> None:
    add_out_lot(db, t_end)
    key = secrets.token_urlsafe(32)
    with connect(db) as conn:
        conn.execute(
            "insert into devices (device_id, api_key_hash) values ('edge-02', %s)",
            (hash_api_key(key),),
        )
    telegram = Telegram(mode)
    body = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-02",
        "lot_id": "L-006",
        "inspected_at": datetime.now(UTC).isoformat(),
        "object_type": "screw",
        "grade": "good",
        "grade_score": 1.0,
        "type_confidence": 0.9,
        "grade_confidence": 0.8,
        "needs_review": False,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "latency_ms": 30,
        "source": "live",
    }
    with running_app(settings(db, ALERTS_ENABLED=True), telegram.transport) as (_app, client):
        assert wait_for(lambda: len(telegram.requests) >= 1)  # the loop ran against the failure
        resp = client.post(INSPECTIONS_URL, json=body, headers={"X-API-Key": key})
        assert resp.status_code == 201, resp.text
        assert client.get(HEALTH_URL).status_code == 200


# --------------------------------------------------------------------------- CA-05


@pytest.mark.db
def test_ca05_token_never_in_logs_or_responses(
    db: str, pool: Any, t_end: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    capture_everything(caplog)
    add_out_lot(db, t_end)
    for i, mode in enumerate(["ok", "500", "timeout"]):
        with connect(db) as conn:
            conn.execute("truncate alerts_sent")
        telegram = Telegram(mode)
        run_check(
            pool, settings(db), now=t_end + timedelta(minutes=11 + i), transport=telegram.transport
        )
        assert len(telegram.requests) == 1, mode

    bodies = []
    with running_app(settings(db, ALERTS_ENABLED=True), Telegram().transport) as (_app, client):
        for method, url, kwargs in [
            ("GET", HEALTH_URL, {}),
            ("GET", SPC_URL, {"headers": {"X-API-Key": READ_KEY}}),
            ("GET", "/api/v1/lots", {"headers": {"X-API-Key": READ_KEY}}),
            ("GET", "/api/v1/devices", {"headers": {"X-API-Key": READ_KEY}}),
            ("GET", "/openapi.json", {}),
            ("GET", "/api/v1/nope", {}),
            ("POST", INSPECTIONS_URL, {"json": {"x": 1}}),
        ]:
            bodies.append(client.request(method, url, **kwargs).text)

    texts = record_texts(caplog)
    assert texts, "nothing was captured"
    for text in texts + bodies:
        assert TOKEN not in text
        assert SECRET_PART not in text


# --------------------------------------------------------------------------- CA-06


@pytest.mark.db
def test_ca06_simulated_needs_the_flag_and_is_marked(db: str, pool: Any, t_end: datetime) -> None:
    add_out_lot(db, t_end, source="simulated")
    now = t_end + timedelta(minutes=11)
    telegram = Telegram()
    assert run_check(pool, settings(db), now=now, transport=telegram.transport) == 0
    assert telegram.requests == []
    off = settings(db, ALERTS_INCLUDE_SIMULATED=False)
    assert run_check(pool, off, now=now, transport=telegram.transport) == 0
    assert telegram.requests == []

    on = settings(db, ALERTS_INCLUDE_SIMULATED=True)
    assert run_check(pool, on, now=now, transport=telegram.transport) == 1
    (text,) = telegram.texts()
    assert text.startswith("[SIMULADO] Lote L-005 fora de controle")
    assert text.endswith("Origem: simulado.")
    assert alerts_rows(db) == [("L-005", "simulated", "out_of_control", True)]


# --------------------------------------------------------------------------- CA-07


@pytest.mark.db
def test_ca07_disabled_creates_no_task(db: str, t_end: datetime) -> None:
    add_out_lot(db, t_end)
    telegram = Telegram()
    with running_app(settings(db, ALERTS_ENABLED=False), telegram.transport) as (app, client):
        assert client.get(HEALTH_URL).status_code == 200
        assert getattr(app.state, "alerts_task", None) is None
        assert alert_tasks(client) == []
        time.sleep(1.0)
        assert telegram.requests == []
    assert telegram.requests == []
    assert alerts_rows(db) == []


@pytest.mark.db
def test_ca07_default_settings_create_no_task(db: str, t_end: datetime) -> None:
    """``ALERTS_ENABLED`` defaults to ``false`` (section 4.6), even with a valid token."""
    add_out_lot(db, t_end)
    telegram = Telegram()
    with running_app(settings(db), telegram.transport) as (app, client):
        assert getattr(app.state, "alerts_task", None) is None
        assert alert_tasks(client) == []
        time.sleep(0.5)
    assert telegram.requests == []


# --------------------------------------------------------------------------- CA-08


@pytest.mark.db
def test_ca08_lot_selection_called_with_integer_caps(
    db: str, pool: Any, t_end: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_out_lot(db, t_end)
    add_out_lot(db, t_end, source="simulated")
    original = inspections_repository.lot_selection
    calls: list[dict[str, Any]] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append({"args": args, **kwargs})
        return original(*args, **kwargs)

    monkeypatch.setattr(inspections_repository, "lot_selection", spy)
    for flag in (False, True):
        run_check(
            pool,
            settings(db, ALERTS_INCLUDE_SIMULATED=flag),
            now=t_end + timedelta(minutes=11),
            transport=Telegram().transport,
        )
    assert calls, "lot_selection was never called through qc_api.repositories.inspections"
    for call in calls:
        assert type(call["max_points"]) is int
        assert type(call["max_excluded"]) is int
        assert 2 <= call["max_points"] <= 10
        assert call["max_excluded"] == 0


def test_ca08_ast_has_no_none_caps() -> None:
    tree = ast.parse(ALERTS_SOURCE.read_text(encoding="utf-8"))
    found = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "lot_selection":
            continue
        found += 1
        for keyword in node.keywords:
            if keyword.arg in {"max_points", "max_excluded"}:
                value = keyword.value
                assert not (isinstance(value, ast.Constant) and value.value is None), keyword.arg
    assert found >= 1


# --------------------------------------------------------------------------- CA-09


@pytest.mark.db
def test_ca09_hourly_cap_skips_without_a_row(
    db: str, pool: Any, t_end: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    add_out_lot(db, t_end)
    now = t_end + timedelta(minutes=11)
    add_alert_rows(db, now - timedelta(minutes=30))
    telegram = Telegram()
    sent = run_check(
        pool, settings(db, ALERTS_MAX_PER_HOUR=10), now=now, transport=telegram.transport
    )
    assert sent == 0
    assert telegram.requests == []
    assert [r for r in alerts_rows(db) if r[0] == "L-005"] == []
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(re.search(r"(?<!\d)10(?!\d)", m) for m in warnings), warnings


@pytest.mark.db
def test_ca09_rows_older_than_one_hour_do_not_count(db: str, pool: Any, t_end: datetime) -> None:
    add_out_lot(db, t_end)
    now = t_end + timedelta(minutes=11)
    add_alert_rows(db, now - timedelta(minutes=61))
    telegram = Telegram()
    sent = run_check(
        pool, settings(db, ALERTS_MAX_PER_HOUR=10), now=now, transport=telegram.transport
    )
    assert len(telegram.requests) == 1
    assert sent == 1


# --------------------------------------------------------------------------- CA-10


@pytest.mark.db
@pytest.mark.parametrize(
    ("variable", "overrides", "value"),
    [
        ("TELEGRAM_BOT_TOKEN", {"TELEGRAM_BOT_TOKEN": ""}, ""),
        ("TELEGRAM_BOT_TOKEN", {"TELEGRAM_BOT_TOKEN": "abc"}, "abc"),
        ("TELEGRAM_CHAT_ID", {"TELEGRAM_CHAT_ID": "x"}, "x"),
    ],
)
def test_ca10_invalid_configuration_keeps_the_api_up(
    db: str,
    t_end: datetime,
    caplog: pytest.LogCaptureFixture,
    variable: str,
    overrides: dict[str, str],
    value: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    add_out_lot(db, t_end)
    telegram = Telegram()
    with running_app(settings(db, ALERTS_ENABLED=True, **overrides), telegram.transport) as (
        app,
        client,
    ):
        assert client.get(HEALTH_URL).status_code == 200
        assert getattr(app.state, "alerts_task", None) is None
        time.sleep(0.5)
    errors = [r.getMessage() for r in caplog.records if INVALID_CONFIG in r.getMessage()]
    assert len(errors) == 1, errors
    match = INVALID_CONFIG_LINE.search(errors[0])
    assert match, errors[0]
    assert variable in match.group(1)
    if value:
        assert value not in match.group(1).split(", ")
        assert not re.search(rf"(?<![A-Za-z]){re.escape(value)}(?![A-Za-z])", errors[0])
    assert telegram.requests == []


# --------------------------------------------------------------------------- CA-11


@pytest.mark.db
def test_ca11_alerts_sent_table(db: str) -> None:
    with connect(db) as conn:
        row = conn.execute(
            "select relrowsecurity from pg_class where oid = 'public.alerts_sent'::regclass"
        ).fetchone()
        assert row == (True,)
        policies = conn.execute(
            "select count(*) from pg_policies "
            "where schemaname = 'public' and tablename = 'alerts_sent'"
        ).fetchone()
        assert policies == (0,)
        insert = "insert into alerts_sent (lot_id, source, kind) values (%s, %s, %s)"
        conn.execute(insert, ("L-001", "live", "out_of_control"))
        with pytest.raises(psycopg.Error) as dup:
            conn.execute(insert, ("L-001", "live", "out_of_control"))
        assert dup.value.sqlstate == "23505"
        with pytest.raises(psycopg.Error) as bad_kind:
            conn.execute(insert, ("L-002", "live", "other"))
        assert bad_kind.value.sqlstate == "23514"


# --------------------------------------------------------------------------- CA-12


@pytest.mark.db
def test_ca12_lot_below_the_lcl(db: str, pool: Any, t_end: datetime) -> None:
    for i in range(1, 5):
        add_lot(db, f"L-00{i}", t_end - timedelta(hours=5 - i), 20, 8)
    add_lot(db, "L-009", t_end, 20, 0)
    telegram = Telegram()
    sent = run_check(
        pool, settings(db), now=t_end + timedelta(minutes=11), transport=telegram.transport
    )
    assert sent == 1
    (text,) = telegram.texts()
    assert "(abaixo do LIC)" in text
    assert "defeituosas = 0" in text
    ucl, lcl = chart_limits([(20, 8)] * 4 + [(20, 0)], 20)
    assert text == (
        f"Lote L-009 fora de controle (abaixo do LIC): p = 0,0%, LSC = {pct(ucl)}, "
        f"LIC = {pct(lcl)}, n = 20, defeituosas = 0. Origem: real."
    )


# --------------------------------------------------------------------------- extras: 4.1


@pytest.mark.db
@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(minutes=10), 1),  # "pelo menos 10 minutos"
        (timedelta(minutes=9, seconds=59), 0),
        (timedelta(hours=23, minutes=59), 1),
        (timedelta(hours=24, minutes=1), 0),
    ],
)
def test_extra_idle_and_lookback_boundaries(
    db: str, pool: Any, t_end: datetime, delta: timedelta, expected: int
) -> None:
    add_out_lot(db, t_end)
    telegram = Telegram()
    assert (
        run_check(pool, settings(db), now=t_end + delta, transport=telegram.transport) == expected
    )
    assert len(telegram.requests) == expected


@pytest.mark.db
def test_extra_idle_and_lookback_settings_are_used(db: str, pool: Any, t_end: datetime) -> None:
    add_out_lot(db, t_end)
    telegram = Telegram()
    longer_idle = settings(db, ALERTS_LOT_IDLE_MINUTES=30)
    assert (
        run_check(
            pool, longer_idle, now=t_end + timedelta(minutes=11), transport=telegram.transport
        )
        == 0
    )
    shorter_window = settings(db, ALERTS_LOOKBACK_HOURS=1)
    assert (
        run_check(
            pool, shorter_window, now=t_end + timedelta(minutes=61), transport=telegram.transport
        )
        == 0
    )
    assert telegram.requests == []
    assert alerts_rows(db) == []


@pytest.mark.db
def test_extra_live_text_never_marked_simulated(db: str, pool: Any, t_end: datetime) -> None:
    """With the flag on, live and simulated lots with the same id are two separate alerts."""
    add_out_lot(db, t_end)
    add_out_lot(db, t_end, source="simulated")
    telegram = Telegram()
    on = settings(db, ALERTS_INCLUDE_SIMULATED=True)
    assert run_check(pool, on, now=t_end + timedelta(minutes=11), transport=telegram.transport) == 2
    assert sorted(telegram.texts()) == sorted([expected_text("live"), expected_text("simulated")])
    assert alerts_rows(db) == [
        ("L-005", "live", "out_of_control", True),
        ("L-005", "simulated", "out_of_control", True),
    ]


@pytest.mark.db
def test_extra_old_lots_do_not_fire_when_alerts_are_switched_on(db: str, pool: Any) -> None:
    """Section 4.1: a lot that ended 2 days ago never fires, only the recent one does."""
    old_t = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    for i in range(1, 5):
        add_lot(db, f"L-00{i}", old_t - timedelta(hours=10 - i), 10, 1)
    add_lot(db, "L-005", old_t, 10, 8)
    telegram = Telegram()
    assert run_check(pool, settings(db), now=datetime.now(UTC), transport=telegram.transport) == 0
    assert telegram.requests == []


@pytest.mark.db
def test_extra_unknown_and_ungraded_rows_do_not_count(db: str, pool: Any, t_end: datetime) -> None:
    """ADR-021: only inspections with a grade enter the chart (unknown rows do not dilute p)."""
    add_out_lot(db, t_end)
    with connect(db) as conn:
        for k in range(30):
            conn.execute(
                "insert into inspections (inspection_id, device_id, lot_id, inspected_at, "
                "object_type, grade, grade_score, type_confidence, grade_confidence, needs_review, "
                "model_version, model_sha256, latency_ms, source) values "
                "(%s, %s, 'L-005', %s, 'unknown', null, null, 0.3, null, true, "
                "'partqc-mnv3-v1', %s, 30, 'live')",
                (str(uuid.uuid4()), DEVICE, t_end - timedelta(seconds=30 + k), SHA),
            )
    telegram = Telegram()
    assert (
        run_check(
            pool, settings(db), now=t_end + timedelta(minutes=11), transport=telegram.transport
        )
        == 1
    )
    assert telegram.texts() == [expected_text()]


@pytest.mark.db
def test_extra_two_out_lots_in_one_check(db: str, pool: Any, t_end: datetime) -> None:
    """Two concluded out-of-control lots among the last 3: two messages, two rows."""
    for i in range(1, 5):
        add_lot(db, f"L-00{i}", t_end - timedelta(hours=5 - i), 10, 1)
    add_lot(db, "L-005", t_end - timedelta(minutes=30), 10, 8)
    add_lot(db, "L-006", t_end, 10, 8)
    telegram = Telegram()
    assert (
        run_check(
            pool, settings(db), now=t_end + timedelta(minutes=11), transport=telegram.transport
        )
        == 2
    )
    texts = telegram.texts()
    assert [t.split(" ", 2)[1] for t in texts] == ["L-005", "L-006"]
    assert all("(acima do LSC)" in t and t.endswith("Origem: real.") for t in texts)
    assert [r[0] for r in alerts_rows(db)] == ["L-005", "L-006"]


@pytest.mark.db
def test_extra_small_lot_never_alerts(db: str, pool: Any, t_end: datetime) -> None:
    """A lot below ``min_lot_size=5`` is excluded from the chart, even if all pieces are poor."""
    add_out_lot(db, t_end - timedelta(minutes=5))
    add_lot(db, "L-006", t_end, 4, 4)
    telegram = Telegram()
    assert (
        run_check(
            pool, settings(db), now=t_end + timedelta(minutes=11), transport=telegram.transport
        )
        == 1
    )
    (text,) = telegram.texts()
    assert text.startswith("Lote L-005 ")
    assert [r[0] for r in alerts_rows(db)] == ["L-005"]


@pytest.mark.db
def test_extra_lot_in_control_never_alerts(db: str, pool: Any, t_end: datetime) -> None:
    for i in range(1, 6):
        add_lot(db, f"L-00{i}", t_end - timedelta(hours=5 - i), 10, 1)
    telegram = Telegram()
    assert (
        run_check(
            pool, settings(db), now=t_end + timedelta(minutes=11), transport=telegram.transport
        )
        == 0
    )
    assert telegram.requests == []
    assert alerts_rows(db) == []


@pytest.mark.db
def test_extra_naive_now_is_refused_before_any_send(db: str, pool: Any, t_end: datetime) -> None:
    """Dates are UTC with an explicit zone (rules.md): a naive ``now`` never sends."""
    add_out_lot(db, t_end)
    telegram = Telegram()
    with pytest.raises(Exception):  # noqa: B017 - any refusal is fine, no send is the point
        run_check(
            pool,
            settings(db),
            now=(t_end + timedelta(minutes=11)).replace(tzinfo=None),
            transport=telegram.transport,
        )
    assert telegram.requests == []
    assert alerts_rows(db) == []


@pytest.mark.db
def test_extra_now_in_another_zone_is_the_same_instant(db: str, pool: Any, t_end: datetime) -> None:
    from datetime import timezone

    add_out_lot(db, t_end)
    telegram = Telegram()
    brt = timezone(timedelta(hours=-3))
    now = (t_end + timedelta(minutes=11)).astimezone(brt)
    assert run_check(pool, settings(db), now=now, transport=telegram.transport) == 1
    assert telegram.texts() == [expected_text()]


# --------------------------------------------------------------------------- extras: 4.3


@pytest.mark.db
def test_extra_several_workers_send_one_message(db: str, t_end: datetime) -> None:
    """Section 4.2: every uvicorn worker runs the check; the primary key keeps one message."""
    add_out_lot(db, t_end)
    telegram = Telegram()
    workers = 6
    pools = [create_pool(db) for _ in range(workers)]
    for p in pools:
        p.open(wait=True)
    barrier = threading.Barrier(workers)
    results: list[int] = []
    errors: list[BaseException] = []

    def work(p: Any) -> None:
        try:
            barrier.wait()
            results.append(
                run_check(
                    p, settings(db), now=t_end + timedelta(minutes=11), transport=telegram.transport
                )
            )
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(p,)) for p in pools]
    try:
        for th in threads:
            th.start()
        for th in threads:
            th.join(30)
    finally:
        for p in pools:
            p.close()
    assert errors == []
    assert sorted(results) == [0] * (workers - 1) + [1]
    assert len(telegram.requests) == 1
    assert alerts_rows(db) == [("L-005", "live", "out_of_control", True)]


@pytest.mark.db
def test_extra_hourly_cap_holds_with_several_workers(db: str, t_end: datetime) -> None:
    """9 rows in the last hour and 2 candidates (live and simulated): at most 1 more row."""
    add_out_lot(db, t_end)
    add_out_lot(db, t_end, source="simulated")
    now = t_end + timedelta(minutes=11)
    app_settings = settings(db, ALERTS_INCLUDE_SIMULATED=True)
    workers = 6
    pools = [create_pool(db) for _ in range(workers)]
    for p in pools:
        p.open(wait=True)
    try:
        for _round in range(5):
            with connect(db) as conn:
                conn.execute("truncate alerts_sent")
            add_alert_rows(db, now - timedelta(minutes=20), count=9)
            telegram = Telegram()
            barrier = threading.Barrier(workers)
            errors: list[BaseException] = []

            def work(
                p: Any,
                telegram: Telegram = telegram,
                barrier: threading.Barrier = barrier,
                errors: list[BaseException] = errors,
            ) -> None:
                try:
                    barrier.wait()
                    run_check(p, app_settings, now=now, transport=telegram.transport)
                except BaseException as exc:  # pragma: no cover - reported below
                    errors.append(exc)

            threads = [threading.Thread(target=work, args=(p,)) for p in pools]
            for th in threads:
                th.start()
            for th in threads:
                th.join(30)
            assert errors == []
            with connect(db) as conn:
                (count,) = conn.execute(
                    "select count(*) from alerts_sent where created_at > %s",
                    (now - timedelta(hours=1),),
                ).fetchone()
            assert count == 10
            assert len(telegram.requests) == 1
    finally:
        for p in pools:
            p.close()


@pytest.mark.db
@pytest.mark.parametrize("mode", ["429", "ok-false", "not-json", "redirect"])
def test_extra_other_telegram_results_are_failures(
    db: str, pool: Any, t_end: datetime, mode: str
) -> None:
    """Section 4.5: only HTTP 200 with ``{"ok": true}`` is a success; never retried."""
    add_out_lot(db, t_end)
    telegram = Telegram(mode)
    assert (
        run_check(
            pool, settings(db), now=t_end + timedelta(minutes=11), transport=telegram.transport
        )
        == 0
    )
    assert len(telegram.requests) == 1  # the redirect is not followed
    assert alerts_rows(db) == [("L-005", "live", "out_of_control", False)]
    assert (
        run_check(
            pool, settings(db), now=t_end + timedelta(minutes=13), transport=telegram.transport
        )
        == 0
    )
    assert len(telegram.requests) == 1


# --------------------------------------------------------------------------- extras: 4.4 / 4.5


@pytest.mark.db
def test_extra_request_carries_only_chat_and_text(db: str, pool: Any, t_end: datetime) -> None:
    """Plain text (no ``parse_mode``), no image, no other field, no credential header."""
    import json

    add_out_lot(db, t_end)
    telegram = Telegram()
    run_check(pool, settings(db), now=t_end + timedelta(minutes=11), transport=telegram.transport)
    (request,) = telegram.requests
    assert set(json.loads(request.content)) == {"chat_id", "text"}
    assert request.headers["content-type"].startswith("application/json")
    assert "authorization" not in request.headers
    assert "x-api-key" not in request.headers
    assert request.url.query == b""
    text = json.loads(request.content)["text"]
    assert DEVICE not in text
    assert not any(ord(c) < 32 for c in text)


@pytest.mark.db
def test_extra_random_token_never_logged_with_real_httpcore(
    db: str, pool: Any, t_end: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    """A real ``httpx.HTTPTransport`` (redirected to a local server) also logs through httpcore."""
    capture_everything(caplog)
    add_out_lot(db, t_end)
    token = random_token()
    secret = token.split(":", 1)[1]
    with local_server("ok") as port:
        transport = RedirectTransport(port)
        sent = run_check(
            pool,
            settings(db, TELEGRAM_BOT_TOKEN=token),
            now=t_end + timedelta(minutes=11),
            transport=transport,
        )
    assert sent == 1
    assert transport.paths == [f"/bot{token}/sendMessage"]
    texts = record_texts(caplog)
    assert any(t.startswith("httpcore") for t in texts), "httpcore did not log"
    for text in texts:
        assert token not in text
        assert secret not in text


def test_extra_settings_repr_hides_the_token() -> None:
    token = random_token()
    s = Settings(
        DATABASE_URL=closed_port_url("pw" + secrets.token_hex(4)),
        READ_API_KEY=READ_KEY,
        TELEGRAM_BOT_TOKEN=token,
    )
    assert token not in repr(s)
    assert token.split(":", 1)[1] not in str(s.model_dump())


# --------------------------------------------------------------------------- extras: timeout


class RedirectTransport(httpx.BaseTransport):
    """Sends the request to a local socket instead of api.telegram.org (real httpcore path)."""

    def __init__(self, port: int) -> None:
        self.inner = httpx.HTTPTransport()
        self.port = port
        self.paths: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()


@contextmanager
def local_server(mode: str) -> Iterator[int]:
    """``ok`` answers ``{"ok": true}``; ``silent`` never answers; ``trickle`` sends 1 byte/0.3 s."""
    stop = threading.Event()
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    server.settimeout(0.2)

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            with conn:
                conn.settimeout(0.5)
                with suppress(TimeoutError):
                    conn.recv(65536)
                if mode == "ok":
                    body = b'{"ok":true,"result":{"message_id":1}}'
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                        + body
                    )
                elif mode == "silent":
                    stop.wait(30)
                elif mode == "slow-headers":
                    if stop.wait(4.5):
                        continue
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        b"Content-Length: 100\r\n\r\n"
                    )
                    if not stop.wait(4.5):
                        with suppress(OSError):
                            conn.sendall(b" ")
                    stop.wait(2)
                elif mode == "trickle":
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        b"Content-Length: 100000\r\n\r\n"
                    )
                    try:
                        while not stop.wait(0.3):
                            conn.sendall(b" ")
                    except OSError:
                        pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield server.getsockname()[1]
    finally:
        stop.set()
        thread.join(5)
        server.close()


@pytest.mark.db
@pytest.mark.slow
@pytest.mark.parametrize("mode", ["silent", "trickle"])
def test_extra_total_timeout_of_5_seconds(db: str, pool: Any, t_end: datetime, mode: str) -> None:
    """Section 4.5: total timeout of 5 s, also against a server that trickles the body."""
    add_out_lot(db, t_end)
    start = time.monotonic()
    with local_server(mode) as port:
        sent = run_check(
            pool, settings(db), now=t_end + timedelta(minutes=11), transport=RedirectTransport(port)
        )
        elapsed = time.monotonic() - start
    assert sent == 0
    assert alerts_rows(db) == [("L-005", "live", "out_of_control", False)]
    assert 4.0 <= elapsed < 7.5, elapsed


@pytest.mark.db
@pytest.mark.slow
def test_extra_total_timeout_with_slow_headers(db: str, pool: Any, t_end: datetime) -> None:
    """Section 4.5 "timeout total de 5 s": headers after 4.5 s, one body byte 4.5 s later.

    T-01 of reviews/SPEC-017/r1-test-report.md (``xfail`` strict in r1), fixed in r2.
    """
    add_out_lot(db, t_end)
    start = time.monotonic()
    with local_server("slow-headers") as port:
        sent = run_check(
            pool, settings(db), now=t_end + timedelta(minutes=11), transport=RedirectTransport(port)
        )
        elapsed = time.monotonic() - start
    assert sent == 0
    assert elapsed < 6.0, elapsed


# --------------------------------------------------------------------------- extras: r2 deadline
#
# RV-01 of reviews/SPEC-017/r1-review-report.md: "timeout total de 5 s" (section 4.5) for the
# whole request: name resolution, connection, status line, headers and body. Each case below
# must end in about 5 s with ``delivered = false``, a single attempt and no token in any log
# record. A send that misses the deadline may leave one abandoned thread behind; every test
# releases its server (or its fake resolver) and waits for that thread before leaving, so the
# limit of one abandoned send per process never leaks into another test.

DEADLINE_MIN = 4.5
DEADLINE_MAX = 6.0
HEADER_DRIP = (
    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nX-Pad: " + b"a" * 100_000 + b"\r\n"
)
OK_BODY = b'{"ok":true,"result":{"message_id":1}}'
OK_RESPONSE = (
    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
    + f"Content-Length: {len(OK_BODY)}\r\nConnection: close\r\n\r\n".encode()
    + OK_BODY
)


class DripServer:
    """Local TCP server in ``127.0.0.1`` that holds every connection until ``release()``.

    ``header-drip`` sends the status line and headers 1 byte per second; ``body-drip`` sends
    the headers at once (``Content-Length: 100000``) and then 1 body byte per second;
    ``silent`` never answers. After ``release()`` the held connections are closed and any new
    connection gets a valid ``{"ok": true}`` answer. ``connections`` counts every attempt.
    """

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.connections = 0
        self.released = threading.Event()
        self.stopped = threading.Event()
        self.handlers: list[threading.Thread] = []
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(0.1)
        self.port = self.sock.getsockname()[1]
        self.acceptor = threading.Thread(target=self._accept, name="tester-drip-accept")
        self.acceptor.daemon = True

    def _accept(self) -> None:
        while not self.stopped.is_set():
            try:
                conn, _ = self.sock.accept()
            except (TimeoutError, OSError):
                continue
            self.connections += 1
            handler = threading.Thread(
                target=self._handle, args=(conn,), name="tester-drip-conn", daemon=True
            )
            self.handlers.append(handler)
            handler.start()

    def _hold(self, conn: socket.socket, chunks: Iterator[bytes]) -> None:
        for chunk in chunks:
            if self.released.wait(1.0) or self.stopped.is_set():
                return
            conn.sendall(chunk)

    def _handle(self, conn: socket.socket) -> None:
        with conn, suppress(OSError):
            conn.settimeout(0.5)
            with suppress(TimeoutError):
                conn.recv(65536)
            if self.released.is_set():
                conn.sendall(OK_RESPONSE)
                return
            if self.mode == "header-drip":
                self._hold(conn, (HEADER_DRIP[i : i + 1] for i in range(len(HEADER_DRIP))))
            elif self.mode == "body-drip":
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"Content-Length: 100000\r\n\r\n"
                )
                self._hold(conn, (b" " for _ in range(100_000)))
            elif self.mode == "silent":
                self.released.wait(60)
            else:
                raise AssertionError(self.mode)

    def release(self) -> None:
        self.released.set()

    def __enter__(self) -> DripServer:
        self.acceptor.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.released.set()
        self.stopped.set()
        self.acceptor.join(5)
        for handler in self.handlers:
            handler.join(5)
        self.sock.close()


def foreign_threads(baseline: set[threading.Thread]) -> list[threading.Thread]:
    """Live threads started after ``baseline`` that are not the tester's own servers."""
    return [
        t
        for t in threading.enumerate()
        if t not in baseline and t.is_alive() and not t.name.startswith("tester-")
    ]


def wait_no_foreign_threads(baseline: set[threading.Thread], timeout: float = 20.0) -> None:
    assert wait_for(lambda: not foreign_threads(baseline), timeout), foreign_threads(baseline)


def assert_no_token(caplog: pytest.LogCaptureFixture, token: str) -> None:
    secret = token.split(":", 1)[1]
    texts = record_texts(caplog)
    for text in texts:
        assert token not in text
        assert secret not in text


@pytest.mark.db
@pytest.mark.slow
@pytest.mark.parametrize("mode", ["header-drip", "body-drip", "silent"])
def test_extra_r2_total_deadline_against_a_dripping_server(
    db: str, pool: Any, t_end: datetime, caplog: pytest.LogCaptureFixture, mode: str
) -> None:
    """RV-01: headers or body 1 byte per second, or a mute server: the send ends in ~5 s."""
    capture_everything(caplog)
    token = random_token()
    app_settings = settings(db, TELEGRAM_BOT_TOKEN=token)
    add_out_lot(db, t_end)
    baseline = set(threading.enumerate())
    with DripServer(mode) as server:
        transport = RedirectTransport(server.port)
        start = time.monotonic()
        sent = run_check(pool, app_settings, now=t_end + timedelta(minutes=11), transport=transport)
        elapsed = time.monotonic() - start
        assert sent == 0
        assert DEADLINE_MIN <= elapsed < DEADLINE_MAX, elapsed
        assert alerts_rows(db) == [("L-005", "live", "out_of_control", False)]
        assert server.connections == 1
        assert transport.paths == [f"/bot{token}/sendMessage"]
        # The abandoned send dies once the server lets the connection go.
        server.release()
        wait_no_foreign_threads(baseline)
        # One attempt per alert: a later check (server now answering ok) sends nothing.
        again = run_check(
            pool, app_settings, now=t_end + timedelta(minutes=12), transport=transport
        )
        assert again == 0
        assert server.connections == 1
        assert alerts_rows(db) == [("L-005", "live", "out_of_control", False)]
    assert_no_token(caplog, token)


@pytest.mark.db
@pytest.mark.slow
def test_extra_r2_total_deadline_with_slow_name_resolution(
    db: str,
    pool: Any,
    t_end: datetime,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RV-01: ``getaddrinfo`` stuck on ``api.telegram.org`` (default transport): ends in ~5 s.

    Every non-local name lookup blocks and then fails, so the test never reaches the network.
    """
    capture_everything(caplog)
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(variable, raising=False)
    real_getaddrinfo = socket.getaddrinfo
    unblock = threading.Event()
    looked_up: list[str] = []

    def stuck_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        name = host.decode() if isinstance(host, bytes) else str(host)
        if name in ("127.0.0.1", "localhost", "::1"):
            return real_getaddrinfo(host, *args, **kwargs)
        looked_up.append(name)
        unblock.wait(60)
        raise socket.gaierror(socket.EAI_AGAIN, "name resolution blocked by the test")

    monkeypatch.setattr(socket, "getaddrinfo", stuck_getaddrinfo)
    token = random_token()
    app_settings = settings(db, TELEGRAM_BOT_TOKEN=token)
    add_out_lot(db, t_end)
    baseline = set(threading.enumerate())
    try:
        start = time.monotonic()
        sent = run_check(pool, app_settings, now=t_end + timedelta(minutes=11), transport=None)
        elapsed = time.monotonic() - start
        assert sent == 0
        assert DEADLINE_MIN <= elapsed < DEADLINE_MAX, elapsed
        assert looked_up == ["api.telegram.org"]
        assert alerts_rows(db) == [("L-005", "live", "out_of_control", False)]
    finally:
        unblock.set()
        wait_no_foreign_threads(baseline)
    again = run_check(pool, app_settings, now=t_end + timedelta(minutes=12), transport=None)
    assert again == 0
    assert looked_up == ["api.telegram.org"]  # no new attempt
    assert alerts_rows(db) == [("L-005", "live", "out_of_control", False)]
    assert_no_token(caplog, token)


@pytest.mark.db
@pytest.mark.slow
def test_extra_r2_at_most_one_abandoned_send_per_process(
    db: str, pool: Any, t_end: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    """RV-01 (option B): while an abandoned send is alive, a check stops before reserving.

    Two candidates (``L-005`` live and simulated). The first send hangs on header drip and is
    abandoned at 5 s; the second candidate is not reserved in that check nor in the next one,
    each check logs the warning, and no second thread is started. Once the abandoned send
    ends, the pending candidate goes out in a later check (it is still in the window).
    """
    capture_everything(caplog)
    token = random_token()
    app_settings = settings(db, TELEGRAM_BOT_TOKEN=token, ALERTS_INCLUDE_SIMULATED=True)
    add_out_lot(db, t_end)
    add_out_lot(db, t_end, source="simulated")
    baseline = set(threading.enumerate())
    with DripServer("header-drip") as server:
        transport = RedirectTransport(server.port)
        start = time.monotonic()
        sent = run_check(pool, app_settings, now=t_end + timedelta(minutes=11), transport=transport)
        elapsed = time.monotonic() - start
        assert sent == 0
        assert DEADLINE_MIN <= elapsed < DEADLINE_MAX + 1.5, elapsed  # 5 s + up to 1 s grace
        first_rows = alerts_rows(db)
        assert len(first_rows) == 1
        assert first_rows[0][2:] == ("out_of_control", False)
        assert server.connections == 1
        assert len(foreign_threads(baseline)) == 1  # the abandoned send

        def stop_warnings() -> list[logging.LogRecord]:
            return [
                r
                for r in caplog.records
                if r.levelno == logging.WARNING
                and "previous send is still running" in r.getMessage()
            ]

        assert len(stop_warnings()) == 1

        start = time.monotonic()
        again = run_check(
            pool, app_settings, now=t_end + timedelta(minutes=12), transport=transport
        )
        elapsed = time.monotonic() - start
        assert again == 0
        assert elapsed < 3.0, elapsed  # stops after the grace wait, no new 5 s send
        assert alerts_rows(db) == first_rows  # nothing reserved
        assert server.connections == 1
        assert len(foreign_threads(baseline)) == 1
        assert len(stop_warnings()) == 2

        server.release()
        wait_no_foreign_threads(baseline)
        third = run_check(
            pool, app_settings, now=t_end + timedelta(minutes=13), transport=transport
        )
        assert third == 1
        assert server.connections == 2
        rows = alerts_rows(db)
        assert len(rows) == 2
        assert {r[1] for r in rows} == {"live", "simulated"}
        assert [r for r in rows if r != first_rows[0]][0][3] is True
        assert first_rows[0] in rows  # the failed one stays undelivered, never retried
    wait_no_foreign_threads(baseline)
    assert_no_token(caplog, token)


@pytest.mark.db
def test_extra_r2_inconsistent_point_leaves_no_row(
    db: str,
    pool: Any,
    t_end: datetime,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RV-03: a point flagged out of control but inside the limits never reserves a row.

    Unreachable with the real chart (``out_of_control`` is ``p > ucl or p < lcl``), so the
    SPEC-006 chart builder (a dependency, not the unit under test) is wrapped to hand the
    ``live`` ``L-005`` back with ``p`` between the limits. The ``simulated`` alert of the same
    check still goes out.
    """
    import qc_api.services.alerts as alerts_module

    real_build = alerts_module.build_p_chart

    def inconsistent_build(*args: Any, **kwargs: Any) -> Any:
        chart = real_build(*args, **kwargs)
        if kwargs.get("source") is not None and kwargs["source"].value != "live":
            return chart
        points = [
            p.model_copy(update={"p": (p.ucl + p.lcl) / 2}) if p.lot_id == "L-005" else p
            for p in chart.points
        ]
        return chart.model_copy(update={"points": points})

    monkeypatch.setattr(alerts_module, "build_p_chart", inconsistent_build)
    caplog.set_level(logging.DEBUG)
    add_out_lot(db, t_end)
    add_out_lot(db, t_end, source="simulated")
    telegram = Telegram()
    sent = run_check(
        pool,
        settings(db, ALERTS_INCLUDE_SIMULATED=True),
        now=t_end + timedelta(minutes=11),
        transport=telegram.transport,
    )
    assert sent == 1
    assert telegram.texts() == [expected_text("simulated")]
    assert alerts_rows(db) == [("L-005", "simulated", "out_of_control", True)]
    assert any(r.levelno == logging.WARNING and "L-005" in r.getMessage() for r in caplog.records)


@pytest.mark.db
def test_extra_huge_response_is_not_read_unbounded(db: str, pool: Any, t_end: datetime) -> None:
    """A 200 with a huge ``{"ok": true, ...}`` body: the body is not read to the end."""
    add_out_lot(db, t_end)
    consumed = {"chunks": 0}

    def body() -> Iterator[bytes]:
        yield b'{"ok": true, "pad": "'
        for _ in range(100_000):  # up to ~100 MiB
            consumed["chunks"] += 1
            yield b"x" * 1024
        yield b'"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, content=body())

    run_check(
        pool,
        settings(db),
        now=t_end + timedelta(minutes=11),
        transport=httpx.MockTransport(handler),
    )
    assert consumed["chunks"] < 2048, consumed  # well below 2 MiB


# --------------------------------------------------------------------------- extras: 4.6 / 4.2

INVALID_ENV = [
    ("ALERTS_ENABLED", "sometimes"),
    ("TELEGRAM_BOT_TOKEN", "12:" + "a" * 20),
    ("TELEGRAM_BOT_TOKEN", "1" * 21 + ":" + "a" * 20),
    ("TELEGRAM_BOT_TOKEN", "123:" + "a" * 19),
    ("TELEGRAM_BOT_TOKEN", "123:" + "a" * 101),
    ("TELEGRAM_BOT_TOKEN", "123:" + "a" * 20 + "!"),
    ("TELEGRAM_BOT_TOKEN", "123" + "a" * 30),
    ("TELEGRAM_BOT_TOKEN", "123:" + "a" * 20 + "\n"),
    ("TELEGRAM_BOT_TOKEN", " 123:" + "a" * 20),
    ("TELEGRAM_CHAT_ID", "-1001\n"),
    ("TELEGRAM_CHAT_ID", "1" * 21),
    ("TELEGRAM_CHAT_ID", "--1"),
    ("TELEGRAM_CHAT_ID", "+1"),
    ("TELEGRAM_CHAT_ID", ""),
    ("ALERTS_LOT_IDLE_MINUTES", "0"),
    ("ALERTS_LOT_IDLE_MINUTES", "1441"),
    ("ALERTS_LOT_IDLE_MINUTES", "ten"),
    ("ALERTS_LOOKBACK_HOURS", "0"),
    ("ALERTS_LOOKBACK_HOURS", "169"),
    ("ALERTS_CHECK_INTERVAL_S", "29"),
    ("ALERTS_CHECK_INTERVAL_S", "3601"),
    ("ALERTS_CHECK_INTERVAL_S", "1.5e2"),
    ("ALERTS_MAX_PER_HOUR", "0"),
    ("ALERTS_MAX_PER_HOUR", "61"),
    ("ALERTS_MAX_PER_HOUR", "-5"),
    ("ALERTS_INCLUDE_SIMULATED", "maybe"),
]


def base_env(monkeypatch: pytest.MonkeyPatch, conninfo: str) -> None:
    monkeypatch.setenv("DATABASE_URL", conninfo)
    monkeypatch.setenv("READ_API_KEY", READ_KEY)
    monkeypatch.setenv("ALERTS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT_ID)


@pytest.mark.db
@pytest.mark.parametrize(("variable", "value"), INVALID_ENV)
def test_extra_invalid_environment_never_stops_the_api(
    db: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    variable: str,
    value: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    base_env(monkeypatch, db)
    monkeypatch.setenv(variable, value)
    telegram = Telegram()
    with running_app(Settings(), telegram.transport) as (app, client):
        assert client.get(HEALTH_URL).status_code == 200
        assert app.state.alerts_task is None
    errors = [r.getMessage() for r in caplog.records if INVALID_CONFIG in r.getMessage()]
    assert len(errors) == 1, errors
    match = INVALID_CONFIG_LINE.search(errors[0])
    assert match and variable in match.group(1), errors[0]
    assert set(match.group(1).split(", ")) <= {name for name, _ in INVALID_ENV}
    if len(value) >= 3:
        for text in record_texts(caplog):
            assert value not in text, text
    assert telegram.requests == []


VALID_ENV = [
    ("TELEGRAM_BOT_TOKEN", "123:" + "a" * 20),
    ("TELEGRAM_BOT_TOKEN", "1" * 20 + ":" + "Z_-" * 33 + "Z"),
    ("TELEGRAM_CHAT_ID", "1" * 20),
    ("TELEGRAM_CHAT_ID", "42"),
    ("ALERTS_LOT_IDLE_MINUTES", "1"),
    ("ALERTS_LOT_IDLE_MINUTES", "1440"),
    ("ALERTS_LOOKBACK_HOURS", "168"),
    ("ALERTS_CHECK_INTERVAL_S", "30"),
    ("ALERTS_CHECK_INTERVAL_S", "3600"),
    ("ALERTS_MAX_PER_HOUR", "1"),
    ("ALERTS_MAX_PER_HOUR", "60"),
    ("ALERTS_INCLUDE_SIMULATED", "true"),
    ("ALERTS_INCLUDE_SIMULATED", "false"),
]


@pytest.mark.db
@pytest.mark.parametrize(("variable", "value"), VALID_ENV)
def test_extra_valid_boundaries_start_the_loop(
    db: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    variable: str,
    value: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    base_env(monkeypatch, db)
    monkeypatch.setenv(variable, value)
    telegram = Telegram()
    with running_app(Settings(), telegram.transport) as (app, client):
        assert client.get(HEALTH_URL).status_code == 200
        task = app.state.alerts_task
        assert task is not None
        assert alert_tasks(client) != []
    assert task.done()  # cancelled at shutdown
    assert not [r for r in caplog.records if INVALID_CONFIG in r.getMessage()]
    assert telegram.requests == []  # no lot in the database


@pytest.mark.db
@pytest.mark.parametrize(
    ("value", "started"),
    [("true", True), ("TRUE", True), ("1", True), ("false", False), ("0", False)],
)
def test_extra_alerts_enabled_values(
    db: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    value: str,
    started: bool,
) -> None:
    caplog.set_level(logging.DEBUG)
    base_env(monkeypatch, db)
    monkeypatch.setenv("ALERTS_ENABLED", value)
    with running_app(Settings(), Telegram().transport) as (app, client):
        assert client.get(HEALTH_URL).status_code == 200
        assert (app.state.alerts_task is not None) is started
    assert not [r for r in caplog.records if INVALID_CONFIG in r.getMessage()]


@pytest.mark.db
def test_extra_enabled_loop_sends_at_startup(db: str, t_end: datetime) -> None:
    """Positive control of CA-07: with the flag on, the loop exists and alerts the out lot."""
    add_out_lot(db, t_end)
    telegram = Telegram()
    with running_app(settings(db, ALERTS_ENABLED=True), telegram.transport) as (app, client):
        assert app.state.alerts_task is not None
        assert alert_tasks(client) != []
        assert wait_for(lambda: len(telegram.requests) == 1)
        assert wait_for(lambda: alerts_rows(db) == [("L-005", "live", "out_of_control", True)])
    assert app.state.alerts_task.done()
    assert len(telegram.requests) == 1


def test_extra_loop_survives_a_database_failure(caplog: pytest.LogCaptureFixture) -> None:
    """Section 4.2: an exception in a check is logged by class and the task keeps running."""
    caplog.set_level(logging.DEBUG)
    password = "pw" + secrets.token_hex(6)
    telegram = Telegram()
    app_settings = settings(closed_port_url(password), ALERTS_ENABLED=True)
    with running_app(app_settings, telegram.transport) as (app, client):
        assert client.get(HEALTH_URL).status_code == 503
        task = app.state.alerts_task
        assert task is not None

        def alert_error_logged() -> bool:
            return any(r.levelno >= logging.WARNING and "alert" in r.name for r in caplog.records)

        assert wait_for(alert_error_logged, timeout=30)
        assert not task.done()
    for text in record_texts(caplog):
        assert password not in text
        assert TOKEN not in text
    assert telegram.requests == []


# --------------------------------------------------------------------------- extras: docs


def test_extra_env_example_documents_the_variables_without_values() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in [
        "ALERTS_ENABLED",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "ALERTS_LOT_IDLE_MINUTES",
        "ALERTS_LOOKBACK_HOURS",
        "ALERTS_CHECK_INTERVAL_S",
        "ALERTS_MAX_PER_HOUR",
        "ALERTS_INCLUDE_SIMULATED",
    ]:
        assert re.search(rf"^{name}=", text, re.M), name
    assert re.search(r"^TELEGRAM_BOT_TOKEN=\s*$", text, re.M)
    assert re.search(r"^TELEGRAM_CHAT_ID=\s*$", text, re.M)
    assert not re.search(r"[0-9]{3,20}:[A-Za-z0-9_-]{20,100}", text)


def test_extra_docs_never_put_the_token_in_argv() -> None:
    """The bot setup commands must not expand the token into a command line (curl argv)."""
    for path in [ROOT / "api" / "README.md", ROOT / "docs" / "deployment-plan.md"]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"[0-9]{3,20}:[A-Za-z0-9_-]{20,100}", text), path
        for line in text.splitlines():
            if "api.telegram.org/bot" in line and re.search(r"\$\{?TELEGRAM_BOT_TOKEN", line):
                assert not re.match(r"\s*(curl|wget|http)\b", line), (path, line)
