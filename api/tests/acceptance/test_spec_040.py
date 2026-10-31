"""Acceptance tests for SPEC-040 (consolidated maintenance), API part: CA-09, CA-10 and the
``api/README.md`` part of CA-11.

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Tests named ``test_extra_*`` are exploratory edge cases around section 4.5.

The common context of the SPEC is the one of the SPEC-017 tests: a valid ``AlertConfig`` with a
token from ``secrets``, a fake transport or a local server in ``127.0.0.1``, the ``partqc_test``
database with migration ``005``, a chart with out-of-control concluded lots and no call to the
real Telegram. Each test that leaves an abandoned send waits for its thread before leaving, so
the limit of one abandoned send per process never leaks into another test.
"""

from __future__ import annotations

import gzip
import logging
import re
import secrets
import socket
import threading
import time
import tracemalloc
import uuid
import zlib
from collections.abc import Callable, Iterable, Iterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest

from qc_api.auth import hash_api_key
from qc_api.config import Settings
from qc_api.db import create_pool
from qc_api.services.alerts import (
    AlertConfig,
    install_token_redaction,
    run_check,
    send_message,
)

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
README = ROOT / "api" / "README.md"
MIB = 1024 * 1024
PEAK_LIMIT = 8 * MIB
READ_KEY = "r" * 32
CHAT_ID = "-1001"
DEVICE = "edge-01"
SHA = "e" * 64
OK_JSON = b'{"ok": true, "result": {"message_id": 1}}'
SENT_OK = b'{"ok":true,"result":{"message_id":1}}'
STOP_RE = re.compile(
    r"^alerts check stopped: a previous send is still running "
    r"\(abandoned_for_s=(\d+), lot_id=([^,]+), source=(live|simulated)\)$"
)


def random_token() -> str:
    return f"{secrets.randbelow(10**9) + 10**8}:{secrets.token_urlsafe(30)}"


def alert_config(token: str) -> AlertConfig:
    return AlertConfig(
        token=token,
        chat_id=CHAT_ID,
        lot_idle_minutes=10,
        lookback_hours=24,
        check_interval_s=120,
        max_per_hour=10,
        include_simulated=False,
    )


# --------------------------------------------------------------------------- bombs and transport


@pytest.fixture(scope="module")
def stacked_bomb() -> bytes:
    """The stacked bomb of Part A: ``gzip, gzip`` over 128 MiB, generated block by block."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, 31)
    inner = bytearray()
    for _ in range(128):
        inner += compressor.compress(b"\0" * MIB)
    inner += compressor.flush()
    return gzip.compress(bytes(inner), compresslevel=9)


class Blocks(httpx.SyncByteStream):
    """A body delivered block by block; nobody decodes it unless the client reads it."""

    def __init__(self, blocks: Iterable[bytes]) -> None:
        self.blocks = list(blocks)
        self.delivered = 0

    def __iter__(self) -> Iterator[bytes]:
        for block in self.blocks:
            self.delivered += 1
            yield block


class FakeTelegram:
    """Records every request and answers with the given status, body and headers."""

    def __init__(self, status: int = 200, body: bytes = OK_JSON, encoding: str | None = None):
        self.status = status
        self.body = body
        self.encoding = encoding
        self.requests: list[httpx.Request] = []
        self.streams: list[Blocks] = []
        self._lock = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        request.read()
        with self._lock:
            self.requests.append(request)
        headers = [("content-type", "application/json")]
        if self.encoding is not None:
            headers.append(("content-encoding", self.encoding))
        stream = Blocks([self.body[i : i + 65536] for i in range(0, len(self.body), 65536)])
        self.streams.append(stream)
        return httpx.Response(self.status, stream=stream, headers=headers)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def log_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    formatter = logging.Formatter("%(name)s %(levelname)s %(message)s")
    lines = [formatter.format(r) for r in caplog.records]
    return lines + [r.getMessage() for r in caplog.records]


def capture_everything(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="httpx")
    caplog.set_level(logging.DEBUG, logger="httpcore")


def assert_no_token(caplog: pytest.LogCaptureFixture, token: str) -> None:
    secret = token.split(":", 1)[1]
    for line in log_lines(caplog):
        assert token not in line
        assert secret not in line


def traced(call: Callable[[], Any]) -> tuple[Any, int]:
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        value = call()
        return value, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


# --------------------------------------------------------------------------- database helpers


def connect(conninfo: str) -> psycopg.Connection:
    return psycopg.connect(conninfo, autocommit=True, prepare_threshold=None)


def settings(conninfo: str, token: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "DATABASE_URL": conninfo,
        "READ_API_KEY": READ_KEY,
        "TELEGRAM_BOT_TOKEN": token,
        "TELEGRAM_CHAT_ID": CHAT_ID,
    }
    values.update(overrides)
    return Settings(**values)


def add_lot(
    conninfo: str, lot_id: str, end: datetime, n: int, defects: int, *, source: str = "live"
) -> None:
    rows = [
        (
            str(uuid.uuid4()),
            DEVICE,
            lot_id,
            end - timedelta(seconds=n - 1 - k),
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
        for k in range(n)
    ]
    with connect(conninfo) as conn, conn.cursor() as cur:
        cur.executemany(
            "insert into inspections (inspection_id, device_id, lot_id, inspected_at, "
            "object_type, grade, grade_score, type_confidence, grade_confidence, needs_review, "
            "model_version, model_sha256, latency_ms, source) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            rows,
        )


def add_out_lot(conninfo: str, t: datetime, *, source: str = "live", prefix: str = "L") -> str:
    """4 lots 10/1, then one 10/8 ending at ``t``; returns the ``lot_id`` that is out of control."""
    for i in range(1, 5):
        add_lot(conninfo, f"{prefix}-00{i}", t - timedelta(hours=5 - i), 10, 1, source=source)
    lot_id = f"{prefix}-005"
    add_lot(conninfo, lot_id, t, 10, 8, source=source)
    return lot_id


def alerts_rows(conninfo: str) -> list[tuple[str, str, str, bool]]:
    with connect(conninfo) as conn:
        return conn.execute(
            "select lot_id, source, kind, delivered from alerts_sent order by lot_id, source"
        ).fetchall()


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
    return datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=11)


# --------------------------------------------------------------------------- CA-09


def test_ca09_request_asks_for_identity() -> None:
    telegram = FakeTelegram()
    assert send_message(alert_config(random_token()), "x", transport=telegram.transport) is True
    assert len(telegram.requests) == 1
    assert telegram.requests[0].headers.get_list("accept-encoding") == ["identity"]


@pytest.mark.parametrize("case", ["a", "b", "c", "d"])
def test_ca09_compressed_answer_is_a_failure_without_reading(
    case: str, stacked_bomb: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    capture_everything(caplog)
    token = random_token()
    install_token_redaction(token)  # what run_check and the startup do before any send
    body, encoding = {
        "a": (gzip.compress(OK_JSON), "gzip"),
        "b": (stacked_bomb, "gzip, gzip"),
        "c": (zlib.compress(OK_JSON), "deflate"),
        "d": (b"opaque", "br"),
    }[case]
    telegram = FakeTelegram(body=body, encoding=encoding)
    config = alert_config(token)
    delivered, peak = traced(lambda: send_message(config, "x", transport=telegram.transport))
    assert delivered is False
    assert peak < PEAK_LIMIT, peak
    assert telegram.streams[0].delivered == 0
    assert any(
        r.getMessage() == "telegram send failed: unsupported content encoding (status=200)"
        for r in caplog.records
    ), log_lines(caplog)
    assert_no_token(caplog, token)


@pytest.mark.parametrize("encoding", [None, "identity"])
def test_ca09_plain_answer_is_delivered(encoding: str | None) -> None:
    telegram = FakeTelegram(encoding=encoding)
    assert send_message(alert_config(random_token()), "x", transport=telegram.transport) is True


@pytest.mark.db
def test_ca09_candidate_with_gzip_stays_undelivered_and_is_not_retried(
    db: str, pool: Any, t_end: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    capture_everything(caplog)
    token = random_token()
    app_settings = settings(db, token)
    add_out_lot(db, t_end)
    telegram = FakeTelegram(body=gzip.compress(OK_JSON), encoding="gzip")
    now = t_end + timedelta(minutes=11)
    assert run_check(pool, app_settings, now=now, transport=telegram.transport) == 0
    assert alerts_rows(db) == [("L-005", "live", "out_of_control", False)]
    assert len(telegram.requests) == 1
    later = now + timedelta(minutes=2)
    assert run_check(pool, app_settings, now=later, transport=telegram.transport) == 0
    assert len(telegram.requests) == 1
    assert alerts_rows(db) == [("L-005", "live", "out_of_control", False)]
    assert_no_token(caplog, token)


@pytest.mark.parametrize(
    "encoding", ["GZIP", "identity, gzip", "x-gzip", "zstd", "compress", "gzip, gzip"]
)
def test_extra_ca09_other_values_are_refused(
    encoding: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    telegram = FakeTelegram(encoding=encoding)
    assert send_message(alert_config(random_token()), "x", transport=telegram.transport) is False
    assert telegram.streams[0].delivered == 0
    assert "telegram send failed: unsupported content encoding (status=200)" in log_lines(caplog)


@pytest.mark.parametrize("encoding", ["Identity", " identity ", "", " , identity"])
def test_extra_ca09_spellings_of_identity_are_read(encoding: str) -> None:
    telegram = FakeTelegram(encoding=encoding)
    assert send_message(alert_config(random_token()), "x", transport=telegram.transport) is True


@pytest.mark.parametrize("status", [400, 429, 500])
def test_extra_ca09_any_status_with_a_compressed_body_is_not_decoded(
    status: int, stacked_bomb: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    telegram = FakeTelegram(status=status, body=stacked_bomb, encoding="gzip, gzip")
    config = alert_config(random_token())
    delivered, peak = traced(lambda: send_message(config, "x", transport=telegram.transport))
    assert delivered is False
    assert peak < PEAK_LIMIT, peak
    assert telegram.streams[0].delivered == 0


def test_extra_ca09_plain_body_above_the_cap_is_still_refused() -> None:
    telegram = FakeTelegram(body=b'{"ok": true, "pad": "' + b"x" * (2 * MIB) + b'"}')
    assert send_message(alert_config(random_token()), "x", transport=telegram.transport) is False


# --------------------------------------------------------------------------- CA-10


class RedirectTransport(httpx.BaseTransport):
    """Sends the request to a local socket instead of api.telegram.org (real httpcore path)."""

    def __init__(self, port: int) -> None:
        self.inner = httpx.HTTPTransport()
        self.port = port

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()


class HeaderDrip:
    """Local server that drips the headers, 1 byte per second, until ``release()``."""

    DRIP = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nX-Pad: " + b"a" * 1000 + b"\r\n"
    OK = (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(SENT_OK)}\r\nConnection: close\r\n\r\n".encode()
        + SENT_OK
    )

    def __init__(self) -> None:
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
        self.acceptor = threading.Thread(target=self._accept, name="tester-accept", daemon=True)

    def _accept(self) -> None:
        while not self.stopped.is_set():
            try:
                conn, _ = self.sock.accept()
            except (TimeoutError, OSError):
                continue
            self.connections += 1
            handler = threading.Thread(
                target=self._handle, args=(conn,), name="tester-conn", daemon=True
            )
            self.handlers.append(handler)
            handler.start()

    def _handle(self, conn: socket.socket) -> None:
        with conn, suppress(OSError):
            conn.settimeout(0.5)
            with suppress(TimeoutError):
                conn.recv(65536)
            if self.released.is_set():
                conn.sendall(self.OK)
                return
            for i in range(len(self.DRIP)):
                if self.released.wait(1.0) or self.stopped.is_set():
                    return
                conn.sendall(self.DRIP[i : i + 1])

    def __enter__(self) -> HeaderDrip:
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
    return [
        t
        for t in threading.enumerate()
        if t not in baseline and t.is_alive() and not t.name.startswith("tester-")
    ]


def wait_no_foreign_threads(baseline: set[threading.Thread], timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and foreign_threads(baseline):
        time.sleep(0.05)
    assert not foreign_threads(baseline)


def stop_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and r.getMessage().startswith("alerts check stopped")
    ]


@pytest.mark.db
@pytest.mark.slow
def test_ca10_warning_has_the_age_and_the_candidate_not_reserved(
    db: str, pool: Any, t_end: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    capture_everything(caplog)
    token = random_token()
    app_settings = settings(db, token, ALERTS_INCLUDE_SIMULATED=True)
    live_lot = add_out_lot(db, t_end)
    simulated_lot = add_out_lot(db, t_end, source="simulated", prefix="S")
    candidates = {(live_lot, "live"), (simulated_lot, "simulated")}
    baseline = set(threading.enumerate())
    now = t_end + timedelta(minutes=11)
    with HeaderDrip() as server:
        sent = run_check(pool, app_settings, now=now, transport=RedirectTransport(server.port))
        assert sent == 0
        assert server.connections == 1
        rows = alerts_rows(db)
        assert len(rows) == 1
        assert rows[0][2:] == ("out_of_control", False)
        assert "telegram send failed: deadline exceeded" in log_lines(caplog)
        warnings = stop_warnings(caplog)
        assert len(warnings) == 1, warnings
        match = STOP_RE.fullmatch(warnings[0])
        assert match, warnings[0]
        assert 0 <= int(match.group(1)) <= 3
        reserved = (rows[0][0], rows[0][1])
        assert reserved in candidates
        assert (match.group(2), match.group(3)) == next(iter(candidates - {reserved}))
    wait_no_foreign_threads(baseline)
    assert_no_token(caplog, token)


@pytest.mark.db
@pytest.mark.slow
def test_extra_ca10_age_grows_and_the_candidate_goes_out_after_the_thread_ends(
    db: str, pool: Any, t_end: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    capture_everything(caplog)
    token = random_token()
    app_settings = settings(db, token, ALERTS_INCLUDE_SIMULATED=True)
    add_out_lot(db, t_end)
    add_out_lot(db, t_end, source="simulated", prefix="S")
    baseline = set(threading.enumerate())
    now = t_end + timedelta(minutes=11)
    with HeaderDrip() as server:
        transport = RedirectTransport(server.port)
        assert run_check(pool, app_settings, now=now, transport=transport) == 0
        first = STOP_RE.fullmatch(stop_warnings(caplog)[-1])
        assert first
        time.sleep(2.2)
        later = now + timedelta(minutes=1)
        assert run_check(pool, app_settings, now=later, transport=transport) == 0
        second = STOP_RE.fullmatch(stop_warnings(caplog)[-1])
        assert second
        assert int(second.group(1)) >= int(first.group(1)) + 2
        # "the candidate not reserved in this check": the next check may name either of the two
        # (observation in the test report); it reserves nothing, whichever it names.
        assert (second.group(2), second.group(3)) in {("L-005", "live"), ("S-005", "simulated")}
        assert len(alerts_rows(db)) == 1
        assert server.connections == 1
        server.released.set()
        wait_no_foreign_threads(baseline)
        last = now + timedelta(minutes=2)
        assert run_check(pool, app_settings, now=last, transport=transport) == 1
        assert len(alerts_rows(db)) == 2
        assert len(stop_warnings(caplog)) == 2
    wait_no_foreign_threads(baseline)
    assert_no_token(caplog, token)


@pytest.mark.db
def test_extra_ca10_no_warning_without_an_abandoned_send(
    db: str, pool: Any, t_end: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    add_out_lot(db, t_end)
    telegram = FakeTelegram()
    now = t_end + timedelta(minutes=11)
    assert run_check(pool, settings(db, random_token()), now=now, transport=telegram.transport) == 1
    assert stop_warnings(caplog) == []


# --------------------------------------------------------------------------- CA-11 (api part)


def bash_blocks(text: str) -> list[str]:
    return re.findall(r"^[ \t]*```bash\n(.*?)^[ \t]*```", text, re.M | re.S)


TOKEN_EXPANSION = re.compile(r"\$\{?(?:t\b|TELEGRAM_BOT_TOKEN)")
TOKEN_LITERAL = re.compile(r"[0-9]{3,20}:[A-Za-z0-9_-]{20,100}")
ALLOWED_T_USE = re.compile(r"""<\(printf '[^']*' "\$t"\)""")


def token_argv_problems(block: str) -> list[str]:
    """The rule of the SPEC: the token only appears inside ``$t`` in the ``printf`` of a ``<()``."""
    problems = []
    for line in block.splitlines():
        rest = ALLOWED_T_USE.sub("", line)
        if TOKEN_EXPANSION.search(rest) or TOKEN_LITERAL.search(rest):
            problems.append(line)
    return problems


def test_ca11_api_readme_mentions_and_absences() -> None:
    text = README.read_text(encoding="utf-8")
    for forbidden in ("infra/.env.api", "sed -n", "compose -f infra/compose.yaml"):
        assert forbidden not in text, forbidden
    for required in (
        "partqc-api",
        "docker exec",
        "printenv TELEGRAM_BOT_TOKEN",
        "-K <(",
        "unset t",
        "deployment-plan.md",
        "abandoned_for_s",
        "Restart",
    ):
        assert required in text, required


def test_ca11_api_readme_bash_blocks_never_put_the_token_in_argv() -> None:
    blocks = bash_blocks(README.read_text(encoding="utf-8"))
    joined = "\n".join(blocks)
    assert "printenv TELEGRAM_BOT_TOKEN" in joined
    assert '"$t"' in joined  # the rule below has something to look at
    for block in blocks:
        assert token_argv_problems(block) == []


@pytest.mark.parametrize(
    "line",
    [
        'curl -s "https://api.telegram.org/bot$t/getUpdates"',
        'curl -s "https://api.telegram.org/bot${t}/getUpdates"',
        "curl -s https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates",
        'curl -s -d "token=$t" https://example.org',
        'echo "$t"',
    ],
)
def test_ca11_control_the_rule_detects_a_planted_line(line: str) -> None:
    assert token_argv_problems(line) == [line]


def _section() -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index("## Alertas no Telegram")
    following = text.find("\n## ", start + 1)
    return text[start:] if following < 0 else text[start:following]


def test_extra_ca11_readme_follows_the_six_items_of_section_4_5() -> None:
    section = _section()
    # 1: the token goes only to the partqc-api, as a runtime locked literal
    assert "@BotFather" in section
    assert "`TELEGRAM_BOT_TOKEN`" in section
    assert "Locked" in section
    assert "Literal" in section
    assert "`partqc-web`" in section
    # 2: on the VPS, from the environment of the container
    assert "t=$(docker exec <contêiner da api> printenv TELEGRAM_BOT_TOKEN)" in section
    assert "VPS" in section
    # 3: on, off and new token with a Redeploy or Restart of this resource only
    assert "Redeploy" in section
    # 4: the log by the panel or by docker logs
    assert (
        "docker logs --tail 200 <contêiner da api> 2>&1 | grep -E 'alerts (enabled|disabled)'"
        in section
    )
    # 5: where the token lives
    assert "Environment Variables do `partqc-api`" in section
    assert "Render" in section
    # 6: the warning that lasts for many minutes
    assert "alerts check stopped: a previous send is still running" in section


def test_extra_ca11_readme_has_no_manual_env_on_the_vps() -> None:
    section = _section()
    assert ".env.api" not in section
    assert "docker compose -f" not in section
    assert "git clone" not in section
    assert "git pull" not in section
