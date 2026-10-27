"""Total timeout of the Telegram send (SPEC-017 section 4.5, RV-01 of the r1 review).

"Timeout total de 5 s": the whole request (name resolution, connect, write, status line,
headers and body) ends within ``SEND_TIMEOUT_S``, whatever the server does. Each case runs the
real ``httpx.HTTPTransport`` against a local socket on ``127.0.0.1`` (the request to
``api.telegram.org`` is redirected), or the default transport with a fake name resolution:
nothing here reaches the network nor the real Telegram. The bot token is random (R-03).
"""

from __future__ import annotations

import logging
import secrets
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from qc_api.config import Settings
from qc_api.services import alerts
from qc_api.services.alerts import AlertConfig, send_message
from qc_contracts import Source, SpcPoint

pytestmark = pytest.mark.slow

# The deadline is total: a little scheduling slack, never another per-operation timeout.
SLACK_S = 0.75

Script = Callable[[socket.socket, threading.Event], None]


def random_token() -> str:
    bot_id = 100_000 + secrets.randbelow(900_000)
    return f"{bot_id}:{secrets.token_urlsafe(32)[:35]}"


def config(token: str) -> AlertConfig:
    return AlertConfig(
        token=token,
        chat_id="-1001",
        lot_idle_minutes=10,
        lookback_hours=24,
        check_interval_s=60,
        max_per_hour=10,
        include_simulated=False,
    )


class LocalServer:
    """A TCP server on ``127.0.0.1`` that reads the request and then runs ``script``."""

    def __init__(self, script: Script) -> None:
        self.script = script
        self.stop = threading.Event()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.sock.settimeout(0.2)
        self.port: int = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except TimeoutError:
                continue
            with conn:
                conn.settimeout(0.5)
                with suppress(TimeoutError):
                    conn.recv(65536)
                with suppress(OSError):
                    self.script(conn, self.stop)

    def close(self) -> None:
        self.stop.set()
        self.thread.join(5)
        self.sock.close()


class RedirectTransport(httpx.BaseTransport):
    """The real ``httpx.HTTPTransport``, with the request sent to the local server."""

    def __init__(self, port: int) -> None:
        self.inner = httpx.HTTPTransport()
        self.port = port

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()


@pytest.fixture
def serve() -> Iterator[Callable[[Script], RedirectTransport]]:
    """Start local servers; at teardown, stop them and check no abandoned send is left."""
    servers: list[LocalServer] = []

    def start(script: Script) -> RedirectTransport:
        server = LocalServer(script)
        servers.append(server)
        return RedirectTransport(server.port)

    yield start
    for server in servers:
        server.close()
    assert not alerts.previous_send_running(grace_s=5.0), "the abandoned send did not end"


def timed_send(token: str, transport: httpx.BaseTransport | None) -> tuple[bool, float]:
    start = time.monotonic()
    delivered = send_message(config(token), "Lote L-1 fora", transport=transport)
    return delivered, time.monotonic() - start


def assert_deadline(caplog: pytest.LogCaptureFixture, token: str, elapsed: float) -> None:
    assert alerts.SEND_TIMEOUT_S - 0.1 <= elapsed < alerts.SEND_TIMEOUT_S + SLACK_S, elapsed
    messages = [record.getMessage() for record in caplog.records]
    assert "telegram send failed: deadline exceeded" in messages
    secret = token.split(":", 1)[1]
    assert not any(secret in message for message in messages)


# --------------------------------------------------------------------------- server scripts

HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n"


def slow_headers_then_slow_byte(conn: socket.socket, stop: threading.Event) -> None:
    """The case of T-01: headers after 4.5 s, one body byte 4.5 s later."""
    if stop.wait(4.5):
        return
    conn.sendall(HEAD)
    if not stop.wait(4.5):
        conn.sendall(b" ")
    stop.wait(5)


def header_drip(conn: socket.socket, stop: threading.Event) -> None:
    """One byte of the status line and headers per second: no read ever times out alone."""
    endless = b"HTTP/1.1 200 OK\r\nX-Pad: " + b"a" * 1000
    for byte in endless:
        if stop.wait(1.0):
            return
        conn.sendall(bytes([byte]))


def body_drip(conn: socket.socket, stop: threading.Event) -> None:
    """Headers at once, then one body byte every 0.3 s."""
    conn.sendall(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100000\r\n\r\n"
    )
    while not stop.wait(0.3):
        conn.sendall(b" ")


def error_status_with_slow_body(conn: socket.socket, stop: threading.Event) -> None:
    """A 500 whose body never completes: the status alone does not end the request."""
    conn.sendall(b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 100\r\n\r\n")
    while not stop.wait(4.0):
        conn.sendall(b" ")


def silent(conn: socket.socket, stop: threading.Event) -> None:
    stop.wait(30)


def answers_ok(conn: socket.socket, stop: threading.Event) -> None:
    body = b'{"ok":true,"result":{"message_id":1}}'
    conn.sendall(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
        + body
    )


# --------------------------------------------------------------------------- cases


@pytest.mark.parametrize(
    "script",
    [slow_headers_then_slow_byte, header_drip, body_drip, error_status_with_slow_body, silent],
    ids=["slow-headers", "header-drip", "body-drip", "500-slow-body", "silent"],
)
def test_send_ends_at_the_total_deadline(
    serve: Callable[[Script], RedirectTransport],
    caplog: pytest.LogCaptureFixture,
    script: Script,
) -> None:
    caplog.set_level(logging.DEBUG)
    token = random_token()
    alerts.install_token_redaction(token)
    delivered, elapsed = timed_send(token, serve(script))
    assert delivered is False
    assert_deadline(caplog, token, elapsed)


def test_send_with_slow_name_resolution_ends_at_the_deadline(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The default transport (production): ``getaddrinfo`` that hangs is bounded too."""
    caplog.set_level(logging.DEBUG)
    release = threading.Event()
    resolving = threading.Event()
    real_getaddrinfo = socket.getaddrinfo

    def hanging_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host == "api.telegram.org":
            resolving.set()
            release.wait(30)
            raise socket.gaierror(socket.EAI_AGAIN, "fake resolver")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", hanging_getaddrinfo)
    token = random_token()
    try:
        delivered, elapsed = timed_send(token, None)
        assert resolving.is_set(), "the request did not resolve the Telegram host"
        assert delivered is False
        assert_deadline(caplog, token, elapsed)
        # The worker is still in the resolver: abandoned, a daemon, and it blocks new sends.
        with alerts._abandoned_lock:
            stuck = list(alerts._abandoned_sends)
        assert stuck and all(thread.daemon for thread in stuck)
        assert alerts.previous_send_running(grace_s=0.0)
    finally:
        release.set()
    assert not alerts.previous_send_running(grace_s=5.0)


def test_fast_answer_is_delivered_without_waiting(
    serve: Callable[[Script], RedirectTransport],
) -> None:
    delivered, elapsed = timed_send(random_token(), serve(answers_ok))
    assert delivered is True
    assert elapsed < 2.0, elapsed


def test_check_stops_while_an_abandoned_send_is_alive(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A stuck send never leads to a second stuck thread: the next alert is not even reserved."""
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    def point(lot_id: str) -> SpcPoint:
        return SpcPoint(
            lot_id=lot_id,
            started_at=now - timedelta(minutes=30),
            ended_at=now - timedelta(minutes=20),
            n=10,
            defects=8,
            p=0.8,
            cl=0.24,
            ucl=0.645,
            lcl=0.0,
            out_of_control=True,
        )

    lots = [alerts.Alert(Source.LIVE, point("L-001")), alerts.Alert(Source.LIVE, point("L-002"))]
    reserved: list[str] = []
    monkeypatch.setattr(alerts, "find_alerts", lambda pool, cfg, now: lots)

    def fake_reserve(pool: Any, alert: alerts.Alert, now: datetime, max_per_hour: int) -> bool:
        reserved.append(alert.point.lot_id)
        return True

    monkeypatch.setattr(alerts, "reserve_alert", fake_reserve)
    monkeypatch.setattr(alerts, "mark_delivered", lambda pool, alert: None)
    release = threading.Event()
    requests: list[str] = []

    def hanging(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        release.wait(30)
        return httpx.Response(200, json={"ok": True})

    caplog.set_level(logging.WARNING, logger="qc_api.alerts")
    token = random_token()
    s = Settings(
        DATABASE_URL="postgresql://localhost/x_test",
        READ_API_KEY="r" * 32,
        TELEGRAM_BOT_TOKEN=token,
        TELEGRAM_CHAT_ID="-1001",
    )
    start = time.monotonic()
    try:
        sent = alerts.run_check(
            None,  # type: ignore[arg-type]
            s,
            now=now,
            transport=httpx.MockTransport(hanging),
        )
        elapsed = time.monotonic() - start
        assert sent == 0
        assert reserved == ["L-001"]
        assert len(requests) == 1
        messages = [record.getMessage() for record in caplog.records]
        assert "telegram send failed: deadline exceeded" in messages
        assert "alerts check stopped: a previous send is still running" in messages
        # The deadline, then the grace for the stuck send, and nothing more.
        assert elapsed < alerts.SEND_TIMEOUT_S + alerts.ABANDONED_SEND_GRACE_S + SLACK_S, elapsed
    finally:
        release.set()
    assert not alerts.previous_send_running(grace_s=5.0)
