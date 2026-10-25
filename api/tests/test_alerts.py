"""Telegram alerts without a database (SPEC-017 sections 4.1 to 4.6).

The text, the concluded and window rules, the configuration, the token redaction, the send
(``httpx.MockTransport``, never the real Telegram) and the loop that survives an exception. The
bot token is random and built at run time: no credential appears as a literal (R-03).
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import secrets
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from qc_api.config import Settings
from qc_api.main import create_app
from qc_api.services import alerts
from qc_api.services.alerts import (
    AlertConfig,
    InvalidAlertConfigError,
    TokenRedactingFilter,
    alerts_enabled,
    alerts_loop,
    format_alert_text,
    format_percent,
    is_concluded,
    is_within_lookback,
    load_alert_config,
    send_message,
    start_alerts_task,
)
from qc_contracts import Source, SpcPoint

READ_KEY = "r" * 32
T = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def random_token() -> str:
    """A token with the shape of section 4.6, random on every call."""
    bot_id = 100_000 + secrets.randbelow(900_000)
    return f"{bot_id}:{secrets.token_urlsafe(32)[:35]}"


@pytest.fixture
def token() -> str:
    return random_token()


def settings(database_url: str = "postgresql://localhost/x_test", **overrides: Any) -> Settings:
    return Settings(DATABASE_URL=database_url, READ_API_KEY=READ_KEY, **overrides)


def alert_settings(token: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": "-1001"}
    values.update(overrides)
    return settings(**values)


def point(p: float, ucl: float, lcl: float, *, n: int = 10, lot_id: str = "L-005") -> SpcPoint:
    return SpcPoint(
        lot_id=lot_id,
        started_at=T - timedelta(minutes=9),
        ended_at=T,
        n=n,
        defects=round(p * n),
        p=p,
        cl=0.24,
        ucl=ucl,
        lcl=lcl,
        out_of_control=p > ucl or p < lcl,
    )


def config(token: str, **overrides: Any) -> AlertConfig:
    values: dict[str, Any] = {
        "token": token,
        "chat_id": "-1001",
        "lot_idle_minutes": 10,
        "lookback_hours": 24,
        "check_interval_s": 60,
        "max_per_hour": 10,
        "include_simulated": False,
    }
    values.update(overrides)
    return AlertConfig(**values)


# --------------------------------------------------------------------------- text (section 4.4)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.4, "40,0%"),
        (0.8, "80,0%"),
        (0.0, "0,0%"),
        (1.0, "100,0%"),
        (0.6452, "64,5%"),
        (0.123, "12,3%"),
        (0.0348, "3,5%"),
    ],
)
def test_format_percent(value: float, expected: str) -> None:
    assert format_percent(value) == expected


def test_text_above_the_ucl_live() -> None:
    text = format_alert_text(point(0.8, 0.6452, 0.0), Source.LIVE)
    assert text == (
        "Lote L-005 fora de controle (acima do LSC): p = 80,0%, LSC = 64,5%, LIC = 0,0%, "
        "n = 10, defeituosas = 8. Origem: real."
    )


def test_text_below_the_lcl() -> None:
    text = format_alert_text(point(0.0, 0.7286, 0.0714, n=20, lot_id="L-009"), Source.LIVE)
    assert text == (
        "Lote L-009 fora de controle (abaixo do LIC): p = 0,0%, LSC = 72,9%, LIC = 7,1%, "
        "n = 20, defeituosas = 0. Origem: real."
    )


def test_text_simulated_is_marked_at_both_ends() -> None:
    text = format_alert_text(point(0.8, 0.6452, 0.0), Source.SIMULATED)
    assert text.startswith("[SIMULADO] Lote L-005 fora de controle (acima do LSC)")
    assert text.endswith("Origem: simulado.")


def test_text_has_no_markup_nor_control_characters() -> None:
    text = format_alert_text(point(0.8, 0.6452, 0.0), Source.SIMULATED)
    assert text.isprintable()
    assert "<" not in text and "*" not in text


def test_text_refuses_a_point_inside_the_limits() -> None:
    with pytest.raises(ValueError, match="inside"):
        format_alert_text(point(0.3, 0.6452, 0.0), Source.LIVE)


# --------------------------------------------------------------------------- rules (section 4.1)


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(minutes=10), True),
        (timedelta(minutes=11), True),
        (timedelta(minutes=10) - timedelta(microseconds=1), False),
        (timedelta(minutes=5), False),
        (timedelta(minutes=-3), False),  # an edge clock ahead of the server
    ],
)
def test_concluded_after_the_idle_minutes(age: timedelta, expected: bool) -> None:
    assert is_concluded(T, T + age, 10) is expected


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(hours=24), True),
        (timedelta(hours=23), True),
        (timedelta(hours=24, microseconds=1), False),
        (timedelta(hours=25), False),
    ],
)
def test_lookback_window(age: timedelta, expected: bool) -> None:
    assert is_within_lookback(T, T + age, 24) is expected


def test_alertable_needs_the_three_conditions(token: str) -> None:
    cfg = config(token)
    out = point(0.8, 0.6452, 0.0)
    assert alerts.is_alertable(out, T + timedelta(minutes=11), cfg)
    assert not alerts.is_alertable(out, T + timedelta(minutes=5), cfg)
    assert not alerts.is_alertable(out, T + timedelta(hours=25), cfg)
    inside = point(0.3, 0.6452, 0.0)
    assert not alerts.is_alertable(inside, T + timedelta(minutes=11), cfg)


# --------------------------------------------------------------------------- configuration (4.6)


def test_defaults_and_settings_fields() -> None:
    s = settings()
    assert s.ALERTS_ENABLED is False
    assert s.TELEGRAM_BOT_TOKEN.get_secret_value() == ""
    assert s.TELEGRAM_CHAT_ID == ""
    assert alerts_enabled(s) is False


def test_valid_configuration_with_defaults(token: str) -> None:
    cfg = load_alert_config(alert_settings(token))
    assert cfg == config(token)


def test_values_from_the_environment(monkeypatch: pytest.MonkeyPatch, token: str) -> None:
    env = {
        "DATABASE_URL": "postgresql://localhost/x_test",
        "READ_API_KEY": READ_KEY,
        "ALERTS_ENABLED": "true",
        "TELEGRAM_BOT_TOKEN": token,
        "TELEGRAM_CHAT_ID": "123456789",
        "ALERTS_LOT_IDLE_MINUTES": "15",
        "ALERTS_LOOKBACK_HOURS": "168",
        "ALERTS_CHECK_INTERVAL_S": "30",
        "ALERTS_MAX_PER_HOUR": "60",
        "ALERTS_INCLUDE_SIMULATED": "TRUE",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    s = Settings()
    assert alerts_enabled(s) is True
    cfg = load_alert_config(s)
    assert (cfg.chat_id, cfg.lot_idle_minutes, cfg.lookback_hours) == ("123456789", 15, 168)
    assert (cfg.check_interval_s, cfg.max_per_hour, cfg.include_simulated) == (30, 60, True)


def test_blank_numbers_and_booleans_mean_the_default(token: str) -> None:
    s = alert_settings(
        token,
        ALERTS_ENABLED="",
        ALERTS_LOT_IDLE_MINUTES="",
        ALERTS_LOOKBACK_HOURS=" ",
        ALERTS_CHECK_INTERVAL_S="",
        ALERTS_MAX_PER_HOUR="",
        ALERTS_INCLUDE_SIMULATED="",
    )
    assert alerts_enabled(s) is False
    assert load_alert_config(s) == config(token)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TELEGRAM_BOT_TOKEN", ""),
        ("TELEGRAM_BOT_TOKEN", "abc"),
        ("TELEGRAM_BOT_TOKEN", "12:" + "A" * 35),  # bot id too short
        ("TELEGRAM_BOT_TOKEN", "123456:" + "A" * 19),  # secret part too short
        ("TELEGRAM_BOT_TOKEN", "123456:" + "A" * 35 + "\n"),
        ("TELEGRAM_BOT_TOKEN", "123456:" + "A" * 34 + "!"),
        ("TELEGRAM_CHAT_ID", ""),
        ("TELEGRAM_CHAT_ID", "x"),
        ("TELEGRAM_CHAT_ID", "-1001\n"),
        ("TELEGRAM_CHAT_ID", "1" * 21),
        ("TELEGRAM_CHAT_ID", "@channel"),
        ("ALERTS_LOT_IDLE_MINUTES", "0"),
        ("ALERTS_LOT_IDLE_MINUTES", "1441"),
        ("ALERTS_LOT_IDLE_MINUTES", "ten"),
        ("ALERTS_LOOKBACK_HOURS", "0"),
        ("ALERTS_LOOKBACK_HOURS", "169"),
        ("ALERTS_CHECK_INTERVAL_S", "29"),
        ("ALERTS_CHECK_INTERVAL_S", "3601"),
        ("ALERTS_CHECK_INTERVAL_S", "-60"),
        ("ALERTS_CHECK_INTERVAL_S", "60.5"),
        ("ALERTS_MAX_PER_HOUR", "0"),
        ("ALERTS_MAX_PER_HOUR", "61"),
        ("ALERTS_INCLUDE_SIMULATED", "maybe"),
    ],
)
def test_invalid_variable_is_named_without_its_value(token: str, name: str, value: Any) -> None:
    with pytest.raises(InvalidAlertConfigError) as info:
        load_alert_config(alert_settings(token, **{name: value}))
    assert info.value.names == (name,)
    assert name in str(info.value)
    if isinstance(value, str) and value.strip():
        assert value.strip() not in str(info.value)


def test_every_invalid_variable_is_named_in_table_order() -> None:
    s = settings(TELEGRAM_CHAT_ID="x", ALERTS_MAX_PER_HOUR="0", ALERTS_INCLUDE_SIMULATED="?")
    with pytest.raises(InvalidAlertConfigError) as info:
        load_alert_config(s)
    assert info.value.names == (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "ALERTS_MAX_PER_HOUR",
        "ALERTS_INCLUDE_SIMULATED",
    )


@pytest.mark.parametrize(
    ("value", "expected"), [(True, True), ("true", True), ("1", True), ("false", False)]
)
def test_alerts_enabled_values(value: Any, expected: bool) -> None:
    assert alerts_enabled(settings(ALERTS_ENABLED=value)) is expected


def test_alerts_enabled_invalid_is_named() -> None:
    with pytest.raises(InvalidAlertConfigError) as info:
        alerts_enabled(settings(ALERTS_ENABLED="maybe"))
    assert info.value.names == ("ALERTS_ENABLED",)


@pytest.mark.parametrize("name", ["ALERTS_MAX_PER_HOUR", "ALERTS_LOOKBACK_HOURS"])
def test_a_bool_is_never_read_as_an_int(name: str) -> None:
    with pytest.raises(ValidationError):
        settings(**{name: True})


def test_config_and_settings_repr_hide_the_token(token: str) -> None:
    s = alert_settings(token)
    secret = token.split(":", 1)[1]
    assert secret not in repr(s)
    assert secret not in repr(load_alert_config(s))


# --------------------------------------------------------------------------- redaction (4.5)


def test_filter_redacts_the_token_and_its_secret_part(token: str) -> None:
    redactor = TokenRedactingFilter()
    redactor.add_token(token)
    bot_id, secret = token.split(":", 1)
    record = logging.LogRecord(
        "httpx", logging.INFO, __file__, 1, "HTTP Request: %s %s", ("POST", f"/bot{token}/x"), None
    )
    assert redactor.filter(record) is True
    assert record.getMessage() == "HTTP Request: POST /bot***/x"
    alone = logging.LogRecord("httpx", logging.INFO, __file__, 1, "s=%s", (secret,), None)
    redactor.filter(alone)
    assert alone.getMessage() == "s=***"
    assert bot_id  # the bot id alone is not secret and may stay


def test_filter_keeps_other_records_untouched(token: str) -> None:
    redactor = TokenRedactingFilter()
    redactor.add_token(token)
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, "n=%d", (3,), None)
    assert redactor.filter(record) is True
    assert record.args == (3,)
    assert TokenRedactingFilter().filter(record) is True


def test_install_is_idempotent(token: str) -> None:
    alerts.install_token_redaction(token)
    alerts.install_token_redaction(token)
    for name in alerts.REDACTED_LOGGERS:
        filters = logging.getLogger(name).filters
        assert filters.count(alerts._REDACTING_FILTER) == 1


# --------------------------------------------------------------------------- send (4.5)


class Recorder:
    """``httpx.MockTransport`` handler that records the requests and answers ``respond``."""

    def __init__(self, respond: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self.respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})


def server_error(_: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"ok": False})


def timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("timed out", request=request)


def _send(token: str, handler: Callable[[httpx.Request], httpx.Response], **kw: Any) -> bool:
    return send_message(
        config(token), "Lote L-1 fora", transport=httpx.MockTransport(handler), **kw
    )


def test_send_posts_the_json_body_to_the_bot_path(token: str) -> None:
    recorder = Recorder(ok)
    assert send_message(config(token), "texto", transport=recorder.transport()) is True
    (request,) = recorder.requests
    assert request.method == "POST"
    assert request.url.host == "api.telegram.org"
    assert request.url.scheme == "https"
    assert request.url.path == f"/bot{token}/sendMessage"
    assert json.loads(request.content) == {"chat_id": "-1001", "text": "texto"}
    assert request.headers["content-type"] == "application/json"


@pytest.mark.parametrize(
    "handler",
    [
        server_error,
        timeout,
        lambda _: httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 5}}),
        lambda _: httpx.Response(200, json={"ok": False}),
        lambda _: httpx.Response(200, json={"ok": "true"}),
        lambda _: httpx.Response(200, json=[True]),
        lambda _: httpx.Response(200, content=b"not json"),
        lambda _: httpx.Response(200, content=b"\xff\xfe"),
        lambda _: httpx.Response(200, content=b"{" + b" " * alerts.MAX_RESPONSE_BYTES + b"}"),
        lambda _: httpx.Response(302, headers={"location": "https://example.invalid/"}),
    ],
    ids=["500", "timeout", "429", "ok-false", "ok-str", "list", "html", "binary", "big", "302"],
)
def test_send_failures(token: str, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    assert _send(token, handler) is False


def test_send_never_raises(token: str, caplog: pytest.LogCaptureFixture) -> None:
    def broken(_: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"unexpected {token}")

    caplog.set_level(logging.DEBUG)
    assert _send(token, broken) is False
    assert "telegram send failed: error=RuntimeError" in caplog.text
    assert token not in caplog.text


def test_send_deadline_is_total(token: str) -> None:
    ticks = iter([0.0, alerts.SEND_TIMEOUT_S + 0.1])
    assert _send(token, ok, monotonic=lambda: next(ticks)) is False


def test_send_logs_never_carry_the_token(token: str, caplog: pytest.LogCaptureFixture) -> None:
    alerts.install_token_redaction(token)
    secret = token.split(":", 1)[1]
    for name in ("", "httpx", "httpcore"):
        caplog.set_level(logging.DEBUG, logger=name or None)
    for handler in (ok, server_error, timeout):
        _send(token, handler)
    assert caplog.records, "httpx should have logged the requests"
    assert any("bot***" in record.getMessage() for record in caplog.records)
    for record in caplog.records:
        assert secret not in record.getMessage()
    assert secret not in caplog.text
    assert any("error=ConnectTimeout" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- run_check guards


class ExplodingPool:
    """Any use of the pool fails the test: ``run_check`` must refuse before a query."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"pool used: {name}")


def test_run_check_refuses_an_invalid_configuration_before_any_query() -> None:
    with pytest.raises(InvalidAlertConfigError):
        alerts.run_check(ExplodingPool(), settings(), now=T)  # type: ignore[arg-type]


def test_run_check_needs_an_aware_now(token: str) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        alerts.run_check(ExplodingPool(), alert_settings(token), now=T.replace(tzinfo=None))  # type: ignore[arg-type]


def test_run_check_ignores_alerts_enabled(token: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ALERTS_ENABLED`` belongs to the loop; ``run_check`` reads the lots anyway."""
    seen: list[datetime] = []

    def fake_find(pool: Any, cfg: AlertConfig, now: datetime) -> list[Any]:
        seen.append(now)
        return []

    monkeypatch.setattr(alerts, "find_alerts", fake_find)
    brt = timezone(timedelta(hours=-3))
    s = alert_settings(token, ALERTS_ENABLED=False)
    assert alerts.run_check(ExplodingPool(), s, now=T.astimezone(brt)) == 0  # type: ignore[arg-type]
    assert seen == [T] and seen[0].tzinfo is UTC


def test_inconsistent_point_is_dropped_before_the_reservation(
    token: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RV-03 (r1 review): the text is built first, so a point inside the limits leaves no row
    and does not abort the other alerts of the check."""
    inside = point(0.3, 0.645, 0.0, lot_id="L-001").model_copy(update={"out_of_control": True})
    lots = [alerts.Alert(Source.LIVE, inside), alerts.Alert(Source.LIVE, point(0.8, 0.645, 0.0))]
    reserved: list[str] = []
    delivered: list[str] = []
    monkeypatch.setattr(alerts, "find_alerts", lambda pool, cfg, now: lots)

    def fake_reserve(pool: Any, alert: alerts.Alert, now: datetime, max_per_hour: int) -> bool:
        reserved.append(alert.point.lot_id)
        return True

    monkeypatch.setattr(alerts, "reserve_alert", fake_reserve)
    monkeypatch.setattr(
        alerts, "mark_delivered", lambda pool, alert: delivered.append(alert.point.lot_id)
    )
    recorder = Recorder(ok)
    caplog.set_level(logging.WARNING, logger="qc_api.alerts")
    sent = alerts.run_check(
        ExplodingPool(),  # type: ignore[arg-type]
        alert_settings(token),
        now=T,
        transport=recorder.transport(),
    )
    assert sent == 1
    assert reserved == ["L-005"]
    assert delivered == ["L-005"]
    assert len(recorder.requests) == 1
    assert "alert skipped: point inside the control limits (lot_id=L-001, source=live)" in [
        record.getMessage() for record in caplog.records
    ]


# --------------------------------------------------------------------------- loop (4.2)


def _sqlstate_error() -> psycopg.Error:
    error = psycopg.errors.UndefinedTable("relation alerts_sent does not exist, row (secret)")
    return error


def test_loop_survives_exceptions_and_logs_only_the_class(
    token: str, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[datetime] = []
    outcomes: list[BaseException | int] = [
        RuntimeError(f"boom {token}"),
        _sqlstate_error(),
        2,
    ]

    def check(pool: Any, s: Settings, *, now: datetime, transport: Any) -> int:
        calls.append(now)
        outcome = outcomes[len(calls) - 1] if len(calls) <= len(outcomes) else 0
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def scenario() -> None:
        task = asyncio.create_task(
            alerts_loop(None, alert_settings(token), 0, check=check, clock=lambda: T)  # type: ignore[arg-type]
        )
        for _ in range(500):
            if len(calls) >= 4:
                break
            await asyncio.sleep(0.01)
        await alerts.stop_alerts_task(task)
        assert task.cancelled()

    caplog.set_level(logging.DEBUG)
    asyncio.run(scenario())
    assert len(calls) >= 4 and calls[0] == T
    messages = [r.getMessage() for r in caplog.records if r.name == "qc_api.alerts"]
    assert "alerts check failed: type=RuntimeError" in messages
    assert any(m.startswith("alerts check failed: type=UndefinedTable sqlstate=") for m in messages)
    assert token.split(":", 1)[1] not in caplog.text
    assert "secret" not in caplog.text


def test_start_task_disabled_creates_nothing(token: str) -> None:
    async def scenario() -> None:
        assert start_alerts_task(None, alert_settings(token)) is None  # type: ignore[arg-type]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("overrides", "name"),
    [
        ({"TELEGRAM_BOT_TOKEN": ""}, "TELEGRAM_BOT_TOKEN"),
        ({"TELEGRAM_BOT_TOKEN": "abc"}, "TELEGRAM_BOT_TOKEN"),
        ({"TELEGRAM_CHAT_ID": "x"}, "TELEGRAM_CHAT_ID"),
        ({"ALERTS_CHECK_INTERVAL_S": "5"}, "ALERTS_CHECK_INTERVAL_S"),
        ({"ALERTS_ENABLED": "sometimes"}, "ALERTS_ENABLED"),
    ],
)
def test_start_task_invalid_logs_one_error_without_the_value(
    token: str, caplog: pytest.LogCaptureFixture, overrides: dict[str, str], name: str
) -> None:
    values = {"ALERTS_ENABLED": "true", **overrides}

    async def scenario() -> None:
        assert start_alerts_task(None, alert_settings(token, **values)) is None  # type: ignore[arg-type]

    caplog.set_level(logging.DEBUG)
    asyncio.run(scenario())
    errors = [r for r in caplog.records if "alerts disabled: invalid configuration" in r.message]
    assert len(errors) == 1
    assert errors[0].levelno == logging.ERROR
    # The exact text: the variable name and nothing of its value.
    assert errors[0].getMessage() == f"alerts disabled: invalid configuration ({name})"


def test_start_task_valid_creates_and_stops_the_loop(
    token: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    started: list[float] = []

    async def fake_loop(pool: Any, s: Settings, interval: float, **kw: Any) -> None:
        started.append(interval)
        await asyncio.sleep(3600)

    monkeypatch.setattr(alerts, "alerts_loop", fake_loop)

    async def scenario() -> None:
        task = start_alerts_task(None, alert_settings(token, ALERTS_ENABLED=True))  # type: ignore[arg-type]
        assert isinstance(task, asyncio.Task)
        await asyncio.sleep(0)
        await alerts.stop_alerts_task(task)
        assert task.cancelled()

    caplog.set_level(logging.DEBUG)
    asyncio.run(scenario())
    assert started == [60]
    assert any(r.getMessage().startswith("alerts enabled: interval=60s") for r in caplog.records)
    assert token.split(":", 1)[1] not in caplog.text


# --------------------------------------------------------------------------- bounded cost (4.1)


def test_source_calls_lot_selection_only_with_integer_caps() -> None:
    """SEC-26-01: every ``lot_selection`` call names both caps, never as ``None``."""
    tree = ast.parse(Path(alerts.__file__).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute | ast.Name)
        and getattr(node.func, "attr", getattr(node.func, "id", None)) == "lot_selection"
    ]
    assert calls
    for call in calls:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        for name in ("max_points", "max_excluded"):
            value = keywords[name]
            assert not (isinstance(value, ast.Constant) and value.value is None)
    assert isinstance(alerts.ALERT_MAX_POINTS, int) and 2 <= alerts.ALERT_MAX_POINTS <= 10
    assert type(alerts.ALERT_MAX_EXCLUDED) is int and alerts.ALERT_MAX_EXCLUDED == 0


# --------------------------------------------------------------------------- app (lifespan)


@pytest.fixture
def no_db_app_settings(no_db_url: str) -> Callable[..., Settings]:
    def _make(**overrides: Any) -> Settings:
        return settings(no_db_url, **overrides)

    return _make


def test_app_without_alerts_has_no_task(no_db_app_settings: Callable[..., Settings]) -> None:
    recorder = Recorder(ok)
    app = create_app(no_db_app_settings(), alerts_transport=recorder.transport())
    with TestClient(app):
        assert app.state.alerts_task is None
    assert recorder.requests == []


def test_app_with_invalid_alerts_still_starts(
    no_db_app_settings: Callable[..., Settings], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    app = create_app(no_db_app_settings(ALERTS_ENABLED="true", TELEGRAM_CHAT_ID="-1001"))
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 503  # no database here
        assert app.state.alerts_task is None
    errors = [r for r in caplog.records if "alerts disabled" in r.getMessage()]
    assert [r.getMessage() for r in errors] == [
        "alerts disabled: invalid configuration (TELEGRAM_BOT_TOKEN)"
    ]


def test_app_with_alerts_starts_and_cancels_the_task(
    token: str, no_db_app_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def idle_loop(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(alerts, "alerts_loop", idle_loop)
    s = no_db_app_settings(ALERTS_ENABLED=True, TELEGRAM_BOT_TOKEN=token, TELEGRAM_CHAT_ID="-1")
    app = create_app(s)
    with TestClient(app):
        task = app.state.alerts_task
        assert isinstance(task, asyncio.Task)
        assert task.get_name() == "qc-api-alerts"
    assert task.cancelled()


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Guard: a client built without a transport must never reach the network."""

    def refuse(self: Any, request: httpx.Request) -> httpx.Response:
        raise AssertionError("real network used")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    yield
