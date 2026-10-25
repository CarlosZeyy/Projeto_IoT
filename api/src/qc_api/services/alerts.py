"""Telegram alerts for out-of-control lots (SPEC-017, RF-17, ADR-013, ADR-017, ADR-021).

* **Trigger** (section 4.1): a point of the p chart of SPEC-006 (``baseline_lots=20``,
  ``min_lot_size=5``, every object type, one ``source`` at a time) with ``out_of_control``, whose
  last inspection (``ended_at``) is at least ``ALERTS_LOT_IDLE_MINUTES`` old (the lot is
  concluded) and at most ``ALERTS_LOOKBACK_HOURS`` old. ``live`` always; ``simulated`` only with
  ``ALERTS_INCLUDE_SIMULATED``. Only inspections with a grade count (ADR-021, in
  ``lot_selection``).
* **Bounded cost** (ADR-017, SEC-06-01, SEC-26-01): each check reads, per source, the selection
  cut in SQL with integer caps (``max_points=3``, ``max_excluded=0``), never ``None``.
* **Dedup and cap** (section 4.3): ``alerts_sent`` gets the row (``ON CONFLICT DO NOTHING``)
  *before* the message is sent; no row back means the lot was already handled. At most one try
  per alert: a failure keeps ``delivered = false`` and is never retried. With
  ``ALERTS_MAX_PER_HOUR`` rows created in the last hour, the alert is skipped without a row.
* **Total timeout** (section 4.5): the whole send (client setup, name resolution, connect, write,
  status line, headers and body) runs in a daemon worker thread that the caller waits for at most
  ``SEND_TIMEOUT_S``; past that, the send is a failure and the worker is abandoned. While an
  abandoned send is still alive, no new alert is reserved nor sent (at most one stuck thread).
* **Secret** (section 4.5, R-03): the token goes only in the Telegram URL. It never reaches a
  log record (a filter on the ``httpx`` and ``httpcore`` loggers replaces it with ``***``), an
  API response or a logged exception message: ``httpx`` errors are logged only by class.
* **Loop** (section 4.2): ``start_alerts_task`` runs ``run_check`` in a thread
  (``asyncio.to_thread``) every ``ALERTS_CHECK_INTERVAL_S`` seconds, first at start; any error is
  logged (class and SQLSTATE) and the loop goes on. An invalid configuration logs one error with
  the variable names (never the values) and starts nothing: alerts never block the ingestion.

``now`` is always the server clock in UTC (``run_check`` takes it as a parameter for tests); the
``created_at`` of ``alerts_sent`` is that same ``now``, so the hourly cap and the windows use one
clock.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from psycopg_pool import ConnectionPool
from pydantic import TypeAdapter, ValidationError

from qc_api.config import Settings
from qc_api.db import db_connection
from qc_api.middleware import find_database_error, sqlstate_label
from qc_api.repositories import inspections as repository
from qc_api.services.spc import build_p_chart
from qc_contracts import Source, SpcPoint

logger = logging.getLogger("qc_api.alerts")

# The chart of the alert (section 4.1): the SPEC-006 defaults and the integer caps of ADR-017.
ALERT_BASELINE_LOTS = 20
ALERT_MIN_LOT_SIZE = 5
ALERT_MAX_POINTS = 3
ALERT_MAX_EXCLUDED = 0

ALERT_KIND = "out_of_control"

TELEGRAM_API_BASE = "https://api.telegram.org"
# Section 4.5: total timeout of the whole request, name resolution included.
SEND_TIMEOUT_S = 5.0
# How long a check waits for a send abandoned at its deadline to end before giving up the check.
ABANDONED_SEND_GRACE_S = 1.0
# Telegram answers a sendMessage with a small JSON; anything bigger is not a success.
MAX_RESPONSE_BYTES = 65_536
REDACTED = "***"
# Loggers that may print the request URL (and so the token): httpx logs it at INFO; the
# httpcore children trace each request at DEBUG. A logger filter applies only to the records
# created on that very logger, so every child is listed.
REDACTED_LOGGERS = (
    "httpx",
    "httpcore",
    "httpcore.connection",
    "httpcore.connection_pool",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
)

TOKEN_PATTERN = r"[0-9]{3,20}:[A-Za-z0-9_-]{20,100}"
CHAT_ID_PATTERN = r"-?[0-9]{1,20}"
_INT_PATTERN = r"[0-9]{1,9}"

# Section 4.6: (name, default, minimum, maximum).
_INT_RULES = (
    ("ALERTS_LOT_IDLE_MINUTES", 10, 1, 1_440),
    ("ALERTS_LOOKBACK_HOURS", 24, 1, 168),
    ("ALERTS_CHECK_INTERVAL_S", 60, 30, 3_600),
    ("ALERTS_MAX_PER_HOUR", 10, 1, 60),
)

INVALID_CONFIGURATION = "alerts disabled: invalid configuration (%s)"

# One transaction per alert. The advisory lock (transaction scoped, so valid on the pooler in
# transaction mode) serializes the cap check and the insert across uvicorn workers.
ALERTS_LOCK_KEY = 1_017_001
LOCK_ALERTS = "select pg_advisory_xact_lock(%s)"
ALERT_EXISTS = """
select exists (
    select 1 from alerts_sent where lot_id = %s and source = %s and kind = %s
) as already_sent
"""
COUNT_RECENT_ALERTS = (
    "select count(*) as recent from alerts_sent where created_at > %s - interval '1 hour'"
)
INSERT_ALERT = """
insert into alerts_sent (lot_id, source, kind, created_at)
values (%s, %s, %s, %s)
on conflict (lot_id, source, kind) do nothing
returning lot_id
"""
MARK_DELIVERED = (
    "update alerts_sent set delivered = true where lot_id = %s and source = %s and kind = %s"
)

_BOOL = TypeAdapter(bool)


class InvalidAlertConfigError(ValueError):
    """The alert configuration breaks a rule of section 4.6; carries only variable names."""

    def __init__(self, names: Iterable[str]) -> None:
        self.names = tuple(names)
        super().__init__(f"invalid alert configuration ({', '.join(self.names)})")


@dataclass(frozen=True)
class AlertConfig:
    """The validated alert settings (section 4.6). ``repr`` never shows the token."""

    token: str
    chat_id: str
    lot_idle_minutes: int
    lookback_hours: int
    check_interval_s: int
    max_per_hour: int
    include_simulated: bool

    def __repr__(self) -> str:
        return (
            f"AlertConfig(token={REDACTED!r}, lot_idle_minutes={self.lot_idle_minutes}, "
            f"lookback_hours={self.lookback_hours}, check_interval_s={self.check_interval_s}, "
            f"max_per_hour={self.max_per_hour}, include_simulated={self.include_simulated})"
        )


@dataclass(frozen=True)
class Alert:
    """One out-of-control lot to report."""

    source: Source
    point: SpcPoint


# --------------------------------------------------------------------------- configuration


def _is_blank(value: object) -> bool:
    return isinstance(value, str) and value.strip() == ""


def _parse_bool(value: object, default: bool) -> bool:
    """``bool`` or a ``str`` pydantic reads as a boolean; blank means ``default``."""
    if _is_blank(value):
        return default
    return _BOOL.validate_python(value)


def _parse_int(value: object, default: int) -> int:
    """``int`` (never ``bool``) or a ``str`` of digits; blank means ``default``."""
    if _is_blank(value):
        return default
    if isinstance(value, bool):
        raise ValueError("bool is not an int")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(_INT_PATTERN, value.strip()):
        return int(value.strip())
    raise ValueError("not an int")


def alerts_enabled(settings: Settings) -> bool:
    """``ALERTS_ENABLED`` as a boolean. Raises ``InvalidAlertConfigError`` when invalid."""
    try:
        return _parse_bool(settings.ALERTS_ENABLED, False)
    except (ValueError, ValidationError):
        raise InvalidAlertConfigError(["ALERTS_ENABLED"]) from None


def load_alert_config(settings: Settings) -> AlertConfig:
    """Validate the alert variables of ``settings`` (section 4.6), whatever ``ALERTS_ENABLED``.

    Raises ``InvalidAlertConfigError`` naming every invalid variable, in the order of the table
    of section 4.6; the values are never part of the error.
    """
    invalid: list[str] = []
    token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
    if not re.fullmatch(TOKEN_PATTERN, token):
        invalid.append("TELEGRAM_BOT_TOKEN")
    chat_id = settings.TELEGRAM_CHAT_ID
    if not re.fullmatch(CHAT_ID_PATTERN, chat_id):
        invalid.append("TELEGRAM_CHAT_ID")
    numbers: dict[str, int] = {}
    for name, default, minimum, maximum in _INT_RULES:
        try:
            value = _parse_int(getattr(settings, name), default)
        except ValueError:
            invalid.append(name)
            continue
        if not minimum <= value <= maximum:
            invalid.append(name)
            continue
        numbers[name] = value
    try:
        include_simulated = _parse_bool(settings.ALERTS_INCLUDE_SIMULATED, False)
    except (ValueError, ValidationError):
        invalid.append("ALERTS_INCLUDE_SIMULATED")
        include_simulated = False
    if invalid:
        raise InvalidAlertConfigError(invalid)
    return AlertConfig(
        token=token,
        chat_id=chat_id,
        lot_idle_minutes=numbers["ALERTS_LOT_IDLE_MINUTES"],
        lookback_hours=numbers["ALERTS_LOOKBACK_HOURS"],
        check_interval_s=numbers["ALERTS_CHECK_INTERVAL_S"],
        max_per_hour=numbers["ALERTS_MAX_PER_HOUR"],
        include_simulated=include_simulated,
    )


# --------------------------------------------------------------------------- token redaction


class TokenRedactingFilter(logging.Filter):
    """Replace every registered token (and its secret part) by ``***`` in a record's message.

    The message is formatted once (``getMessage``); when it changes, ``msg`` becomes the
    redacted text and ``args`` is cleared. A record is never dropped.
    """

    def __init__(self) -> None:
        super().__init__()
        self._secrets: tuple[str, ...] = ()

    def add_token(self, token: str) -> None:
        # The whole token first, then the part after ':' (the bot id alone is not secret).
        parts = [token]
        _, _, secret = token.partition(":")
        if secret:
            parts.append(secret)
        known = list(self._secrets)
        for part in parts:
            if part and part not in known:
                known.append(part)
        # Longest first, so the whole token is replaced before its secret part.
        self._secrets = tuple(sorted(known, key=len, reverse=True))

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        try:
            message = record.getMessage()
        except Exception:  # a broken format string: leave it to the handler
            return True
        redacted = self.redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


_REDACTING_FILTER = TokenRedactingFilter()


def install_token_redaction(token: str) -> None:
    """Register ``token`` and attach the redacting filter to ``REDACTED_LOGGERS`` (idempotent)."""
    _REDACTING_FILTER.add_token(token)
    for name in REDACTED_LOGGERS:
        target = logging.getLogger(name)
        if _REDACTING_FILTER not in target.filters:
            target.addFilter(_REDACTING_FILTER)


# --------------------------------------------------------------------------- rule and text


def _aware_utc(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")
    return now.astimezone(UTC)


def is_concluded(ended_at: datetime, now: datetime, idle_minutes: int) -> bool:
    """The last inspection is at least ``idle_minutes`` old (section 4.1)."""
    return now - ended_at >= timedelta(minutes=idle_minutes)


def is_within_lookback(ended_at: datetime, now: datetime, lookback_hours: int) -> bool:
    """The last inspection is at most ``lookback_hours`` old (section 4.1)."""
    return now - ended_at <= timedelta(hours=lookback_hours)


def is_alertable(point: SpcPoint, now: datetime, config: AlertConfig) -> bool:
    """Out of control, concluded and inside the window (section 4.1)."""
    return (
        point.out_of_control
        and is_concluded(point.ended_at, now, config.lot_idle_minutes)
        and is_within_lookback(point.ended_at, now, config.lookback_hours)
    )


def format_percent(value: float) -> str:
    """``0.4`` -> ``40,0%``: percent with one decimal and a decimal comma (section 4.4)."""
    return f"{value * 100:.1f}".replace(".", ",") + "%"


def format_alert_text(point: SpcPoint, source: Source) -> str:
    """The plain PT-BR text of section 4.4. Raises ``ValueError`` for a point inside the limits."""
    if point.p > point.ucl:
        side = "acima do LSC"
    elif point.p < point.lcl:
        side = "abaixo do LIC"
    else:
        raise ValueError("the point is inside the control limits")
    origin = "simulado" if source == Source.SIMULATED else "real"
    text = (
        f"Lote {point.lot_id} fora de controle ({side}): p = {format_percent(point.p)}, "
        f"LSC = {format_percent(point.ucl)}, LIC = {format_percent(point.lcl)}, "
        f"n = {point.n}, defeituosas = {point.defects}. Origem: {origin}."
    )
    if source == Source.SIMULATED:
        return f"[SIMULADO] {text}"
    return text


# --------------------------------------------------------------------------- database


def find_alerts(pool: ConnectionPool, config: AlertConfig, now: datetime) -> list[Alert]:
    """The out-of-control points to report, ``live`` first, each source in chart order."""
    sources = [Source.LIVE]
    if config.include_simulated:
        sources.append(Source.SIMULATED)
    alerts: list[Alert] = []
    for source in sources:
        selection = repository.lot_selection(
            pool,
            source,
            None,
            baseline_lots=ALERT_BASELINE_LOTS,
            min_lot_size=ALERT_MIN_LOT_SIZE,
            max_points=ALERT_MAX_POINTS,
            max_excluded=ALERT_MAX_EXCLUDED,
        )
        chart = build_p_chart(
            selection,
            ALERT_BASELINE_LOTS,
            ALERT_MIN_LOT_SIZE,
            source=source,
            max_points=ALERT_MAX_POINTS,
        )
        alerts.extend(
            Alert(source, point) for point in chart.points if is_alertable(point, now, config)
        )
    return alerts


def reserve_alert(pool: ConnectionPool, alert: Alert, now: datetime, max_per_hour: int) -> bool:
    """Insert the ``alerts_sent`` row of ``alert``; ``True`` when this call owns the send.

    ``False`` when the lot was already handled, or when ``max_per_hour`` rows were created in
    the hour before ``now`` (then a warning with the count is logged and no row is written).
    """
    key = (alert.point.lot_id, alert.source.value, ALERT_KIND)
    with db_connection(pool) as conn, conn.transaction():
        conn.execute(LOCK_ALERTS, (ALERTS_LOCK_KEY,))
        exists_row = conn.execute(ALERT_EXISTS, key).fetchone()
        if exists_row is not None and exists_row[0]:
            return False
        count_row = conn.execute(COUNT_RECENT_ALERTS, (now,)).fetchone()
        recent = int(count_row[0]) if count_row is not None else 0
        if recent >= max_per_hour:
            logger.warning(
                "alert skipped: hourly cap reached (count=%d, max=%d, lot_id=%s, source=%s)",
                recent,
                max_per_hour,
                alert.point.lot_id,
                alert.source.value,
            )
            return False
        inserted = conn.execute(INSERT_ALERT, (*key, now)).fetchone()
    return inserted is not None


def mark_delivered(pool: ConnectionPool, alert: Alert) -> None:
    with db_connection(pool) as conn:
        conn.execute(MARK_DELIVERED, (alert.point.lot_id, alert.source.value, ALERT_KIND))


# --------------------------------------------------------------------------- Telegram


_abandoned_lock = threading.Lock()
_abandoned_sends: list[threading.Thread] = []


def previous_send_running(grace_s: float = ABANDONED_SEND_GRACE_S) -> bool:
    """``True`` while a send abandoned at its deadline is still alive, after up to ``grace_s``.

    An abandoned worker cannot be interrupted (threads cannot be); it ends on its own when its
    network operation ends. Until then no new alert is reserved, so at most one thread is stuck.
    """
    with _abandoned_lock:
        threads = list(_abandoned_sends)
    limit = time.monotonic() + grace_s
    for thread in threads:
        thread.join(max(0.0, limit - time.monotonic()))
    with _abandoned_lock:
        _abandoned_sends[:] = [thread for thread in _abandoned_sends if thread.is_alive()]
        return bool(_abandoned_sends)


def _post(
    transport: httpx.BaseTransport | None,
    url: str,
    body: dict[str, str],
    cancelled: threading.Event,
    monotonic: Callable[[], float],
) -> tuple[bool, str]:
    """The request itself, run in the worker thread: ``(delivered, failure reason)``.

    Never raises and never logs (the caller logs, so an abandoned worker stays silent). The
    reason carries only integers and exception class names, never the token.
    """
    start = monotonic()
    try:
        with _client(transport) as client, client.stream("POST", url, json=body) as response:
            status = response.status_code
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES:
                    return False, f"response too large (status={status})"
                # The caller enforces the deadline; this only lets an abandoned worker end soon.
                if cancelled.is_set() or monotonic() - start > SEND_TIMEOUT_S:
                    return False, f"deadline exceeded (status={status})"
    except Exception as exc:  # httpx errors and anything else: one try, reported by class only
        return False, f"error={type(exc).__name__}"
    if status != 200:
        return False, f"status={status}"
    if not _telegram_ok(bytes(content)):
        return False, f"status={status} without ok=true"
    return True, ""


def send_message(
    config: AlertConfig,
    text: str,
    *,
    transport: httpx.BaseTransport | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> bool:
    """POST ``sendMessage``; ``True`` only for HTTP 200 with ``{"ok": true}`` (section 4.5).

    Every other outcome (status, 429, timeout, network error, a body that is not that JSON,
    larger than ``MAX_RESPONSE_BYTES``, any exception) is a failure, logged without the token:
    exceptions only by class. Never raises.

    The total timeout is ``SEND_TIMEOUT_S`` for the whole request: the client is built and used
    in a daemon worker thread (name resolution, connect, write, status line, headers and body all
    happen there), and this function waits for it at most ``SEND_TIMEOUT_S``. Past that, the send
    is a failure; the worker is abandoned and ends on its own (see ``previous_send_running``).
    ``monotonic`` is the worker's clock for its own deadline check between body chunks.
    """
    url = f"{TELEGRAM_API_BASE}/bot{config.token}/sendMessage"
    body = {"chat_id": config.chat_id, "text": text}
    outcome: list[tuple[bool, str]] = []
    cancelled = threading.Event()

    def work() -> None:
        outcome.append(_post(transport, url, body, cancelled, monotonic))

    worker = threading.Thread(target=work, name="qc-api-telegram-send", daemon=True)
    worker.start()
    worker.join(SEND_TIMEOUT_S)
    if not outcome:
        cancelled.set()
        if worker.is_alive():
            with _abandoned_lock:
                _abandoned_sends.append(worker)
        logger.warning("telegram send failed: deadline exceeded")
        return False
    delivered, reason = outcome[0]
    if not delivered:
        logger.warning("telegram send failed: %s", reason)
    return delivered


def _telegram_ok(content: bytes) -> bool:
    try:
        payload: Any = json.loads(content)
    except ValueError:  # also UnicodeDecodeError
        return False
    return isinstance(payload, dict) and payload.get("ok") is True


def _client(transport: httpx.BaseTransport | None) -> httpx.Client:
    # trust_env=False: no proxy variables nor .netrc; the request goes straight to Telegram.
    return httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(SEND_TIMEOUT_S),
        trust_env=False,
        follow_redirects=False,
    )


# --------------------------------------------------------------------------- check


def run_check(
    pool: ConnectionPool,
    settings: Settings,
    *,
    now: datetime,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """One alert check (sections 4.1 to 4.5); returns the number of messages accepted.

    ``ALERTS_ENABLED`` is not read here (that is the job of ``start_alerts_task``); every other
    alert variable must be valid, or ``InvalidAlertConfigError`` is raised before any query.
    ``now`` must be timezone-aware. Database errors propagate; a failed send never does.
    """
    config = load_alert_config(settings)
    install_token_redaction(config.token)
    now = _aware_utc(now)
    alerts = find_alerts(pool, config, now)
    if not alerts:
        return 0
    sent = 0
    for alert in alerts:
        try:  # before the reservation: an inconsistent point never leaves a row behind
            text = format_alert_text(alert.point, alert.source)
        except ValueError:
            logger.warning(
                "alert skipped: point inside the control limits (lot_id=%s, source=%s)",
                alert.point.lot_id,
                alert.source.value,
            )
            continue
        if previous_send_running():
            # Nothing reserved: the alert may go out in a later check, while still in the window.
            logger.warning("alerts check stopped: a previous send is still running")
            break
        if not reserve_alert(pool, alert, now, config.max_per_hour):
            continue
        if send_message(config, text, transport=transport):
            mark_delivered(pool, alert)
            sent += 1
            logger.info("alert sent: lot_id=%s source=%s", alert.point.lot_id, alert.source.value)
    return sent


# --------------------------------------------------------------------------- loop


def log_check_failure(exc: BaseException) -> None:
    """Log a failed check by class (and SQLSTATE for a database error), never the message."""
    database_error = find_database_error(exc)
    if database_error is not None:
        logger.error(
            "alerts check failed: type=%s sqlstate=%s",
            type(database_error).__name__,
            sqlstate_label(database_error),
        )
        return
    logger.error("alerts check failed: type=%s", type(exc).__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def alerts_loop(
    pool: ConnectionPool,
    settings: Settings,
    interval_s: float,
    *,
    transport: httpx.BaseTransport | None = None,
    check: Callable[..., int] = run_check,
    clock: Callable[[], datetime] = _utc_now,
) -> None:
    """Run ``check`` in a thread now and then every ``interval_s`` seconds, until cancelled."""
    while True:
        try:
            await asyncio.to_thread(check, pool, settings, now=clock(), transport=transport)
        except Exception as exc:
            log_check_failure(exc)
        await asyncio.sleep(interval_s)


def start_alerts_task(
    pool: ConnectionPool,
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
) -> asyncio.Task[None] | None:
    """Start the alert loop when ``ALERTS_ENABLED`` and the configuration are valid.

    Returns ``None`` (no task) when the alerts are off or the configuration is invalid; in the
    latter case, one error ``alerts disabled: invalid configuration (<names>)`` is logged,
    without the values. Must be called from a running event loop.
    """
    try:
        if not alerts_enabled(settings):
            return None
        config = load_alert_config(settings)
    except InvalidAlertConfigError as exc:
        logger.error(INVALID_CONFIGURATION, ", ".join(exc.names))
        return None
    install_token_redaction(config.token)
    logger.info(
        "alerts enabled: interval=%ds idle=%dmin lookback=%dh max_per_hour=%d simulated=%s",
        config.check_interval_s,
        config.lot_idle_minutes,
        config.lookback_hours,
        config.max_per_hour,
        config.include_simulated,
    )
    return asyncio.create_task(
        alerts_loop(pool, settings, config.check_interval_s, transport=transport),
        name="qc-api-alerts",
    )


async def stop_alerts_task(task: asyncio.Task[None] | None) -> None:
    """Cancel the alert loop and wait for the task to end.

    A check already running in its thread is not interrupted (threads cannot be): it finishes on
    its own, bounded by the pool timeout and by ``SEND_TIMEOUT_S`` per send, and is not awaited
    here. A send abandoned at its deadline runs in a daemon thread and never holds the exit.
    """
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
