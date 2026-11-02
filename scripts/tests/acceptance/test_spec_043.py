"""Acceptance tests for SPEC-043, the ``scripts/`` part: CA-01 to CA-04 and CA-10.

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. ``test_extra_*`` tests are exploratory edge cases that no CA spells out.

No network: the simulator talks to an ``httpx.MockTransport``, and ``psycopg.connect`` is replaced
on the refused paths. The database test (CA-04, marker ``db``) forwards the transport to the real
``qc_api`` app on ``clean_db``. Keys and password sentinels are generated at run time, and URLs
with credentials are assembled from them (``reviews/checklist.md`` section 4).
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import psycopg
import pytest

import qc_contracts

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
SIMULATE = ROOT / "scripts" / "simulate.py"
REGISTER = ROOT / "scripts" / "register_device.py"

API_URL = "https://api.partqc.test"
URL_HEALTH = "/api/v1/health"
URL_BATCH = "/api/v1/inspections/batch"
NOW = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)
SCHEME = "postgresql" + "://"
TIMEOUT_PHASES = {"connect", "read", "write", "pool"}
EXHAUSTED = (
    "batch failed after 4 attempts (last: ReadTimeout); the API may have stored it: "
    "run again with the same seed, stored items come back as duplicate (R-05)"
)


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sim = _load("simulate_spec043_acceptance", SIMULATE)
register = _load("register_device_spec043_acceptance", REGISTER)


def new_key() -> str:
    return "k" + secrets.token_urlsafe(24)


def malformed_urls(a: str, b: str) -> dict[str, str]:
    """The four malformed URLs (M) of SPEC-043 section 5."""
    return {
        "at-6543": f"{SCHEME}u:{a}@{b}@db.example.org:6543/postgres",
        "slash": f"{SCHEME}u:{a}/{b}@db.example.org:5432/postgres",
        "numeric-slash": f"{SCHEME}u:12/{b}@db.example.org:5432/postgres",
        "at-colon": f"{SCHEME}u:{a}@{b}:x@db.example.org:5432/postgres",
    }


MALFORMED_IDS = ["at-6543", "slash", "numeric-slash", "at-colon"]


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# --------------------------------------------------------------------------- fake API


class SlowApi:
    """Fake API whose batch takes ``needed_read_s``: a shorter ``read`` budget times out.

    The transport raises ``httpx.ReadTimeout`` when the request's ``read`` timeout is below the
    limit, as the production batch did with the old 10 s. ``None`` means it always times out.
    """

    def __init__(self, key: str, needed_read_s: float | None) -> None:
        self.key = key
        self.needed_read_s = needed_read_s
        self.store: dict[str, dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []
        self.health_status = 200
        self.batch_status: int | None = None

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def batches(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "POST" and r.url.path == URL_BATCH]

    def healths(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "GET" and r.url.path == URL_HEALTH]

    def handler(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if request.url.path == URL_HEALTH:
            return httpx.Response(
                self.health_status,
                json={
                    "status": "ok" if self.health_status == 200 else "degraded",
                    "db": "ok" if self.health_status == 200 else "error",
                    "api_version": "0.1.0",
                    "contract_version": qc_contracts.__version__,
                },
            )
        assert request.url.path == URL_BATCH, request.url
        if self.batch_status is not None:
            return httpx.Response(self.batch_status, json={"detail": "x"})
        read = request.extensions["timeout"]["read"]
        if self.needed_read_s is None or read < self.needed_read_s:
            raise httpx.ReadTimeout("timed out", request=request)
        results = []
        for item in json.loads(request.content)["items"]:
            status = "duplicate" if item["inspection_id"] in self.store else "created"
            self.store[item["inspection_id"]] = item
            results.append({"inspection_id": item["inspection_id"], "status": status})
        return httpx.Response(200, json={"results": results})


@dataclass
class Run:
    code: int
    out: str
    err: str
    sleeps: list[float] = field(default_factory=list)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "CLOUD_API_URL",
        "SIM_DEVICE_ID",
        "SIM_DEVICE_API_KEY",
        "DATABASE_URL",
        "PGPORT",
        "PGHOST",
        "PGDATABASE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Device key in the environment (SIM_DEVICE_API_KEY), as the CA-03 asks."""
    value = new_key()
    monkeypatch.setenv("CLOUD_API_URL", API_URL)
    monkeypatch.setenv("SIM_DEVICE_ID", "sim-01")
    monkeypatch.setenv("SIM_DEVICE_API_KEY", value)
    return value


@pytest.fixture
def simulate(capsys: pytest.CaptureFixture[str]) -> Callable[..., Run]:
    def _run(transport: httpx.BaseTransport, *argv: str, now: datetime = NOW) -> Run:
        sleeps: list[float] = []
        capsys.readouterr()
        code = sim.main(list(argv), transport=transport, sleep=sleeps.append, now=now)
        captured = capsys.readouterr()
        return Run(code, captured.out, captured.err, sleeps)

    return _run


def batch_sizes(api: SlowApi) -> list[int]:
    return [len(json.loads(r.content)["items"]) for r in api.batches()]


# --------------------------------------------------------------------------- CA-01


def test_ca01_three_lots_survive_the_measured_13_s(key: str, simulate: Callable[..., Run]) -> None:
    api = SlowApi(key, needed_read_s=13)

    result = simulate(api.transport, "--lots", "3", "--seed", "42")

    assert result.code == 0, result.err
    assert "sent=75 created=75 duplicate=0" in result.out
    assert batch_sizes(api) == [75]
    assert result.sleeps == []
    batch_timeout = api.batches()[0].extensions["timeout"]
    assert set(batch_timeout) == TIMEOUT_PHASES
    assert all(batch_timeout[phase] == 60.0 for phase in TIMEOUT_PHASES), batch_timeout
    health_timeout = api.healths()[0].extensions["timeout"]
    assert set(health_timeout) == TIMEOUT_PHASES
    assert all(health_timeout[phase] == 90.0 for phase in TIMEOUT_PHASES), health_timeout


# --------------------------------------------------------------------------- CA-02


def test_ca02_ten_lots_of_fifty_survive_18_s_per_full_batch(
    key: str, simulate: Callable[..., Run]
) -> None:
    api = SlowApi(key, needed_read_s=18)

    result = simulate(api.transport, "--lots", "10", "--lot-size", "50", "--seed", "42")

    assert result.code == 0, result.err
    assert "sent=500 created=500 duplicate=0" in result.out
    assert batch_sizes(api) == [100] * 5
    assert result.sleeps == []
    assert len(api.store) == 500
    assert {item["source"] for item in api.store.values()} == {"simulated"}


# --------------------------------------------------------------------------- CA-03


def test_ca03_exhausted_batch_says_to_repeat_with_the_same_seed(
    key: str, simulate: Callable[..., Run]
) -> None:
    api = SlowApi(key, needed_read_s=None)

    result = simulate(api.transport, "--lots", "3", "--seed", "42")

    assert result.code == 5
    assert len(api.batches()) == 4
    assert result.sleeps == [2, 4, 8]
    assert "batch failed after 4 attempts (last: ReadTimeout)" in result.err
    assert "same seed" in result.err
    assert "seed=42" in result.err
    assert key not in result.out + result.err


def test_ca03_exact_message_of_section_4_1(key: str, simulate: Callable[..., Run]) -> None:
    api = SlowApi(key, needed_read_s=None)
    result = simulate(api.transport, "--lots", "3", "--seed", "42")
    assert EXHAUSTED in result.err


def test_ca03_health_503_exits_5_without_the_seed_advice(
    key: str, simulate: Callable[..., Run]
) -> None:
    api = SlowApi(key, needed_read_s=60)
    api.health_status = 503

    result = simulate(api.transport, "--lots", "3", "--seed", "42")

    assert result.code == 5
    assert api.batches() == []
    assert "same seed" not in result.err
    assert key not in result.out + result.err


def test_ca03_batch_401_exits_3_without_the_seed_advice(
    key: str, simulate: Callable[..., Run]
) -> None:
    api = SlowApi(key, needed_read_s=60)
    api.batch_status = 401

    result = simulate(api.transport, "--lots", "3", "--seed", "42")

    assert result.code == 3
    assert "same seed" not in result.err
    assert key not in result.out + result.err


@pytest.mark.parametrize(("status", "code"), [(403, 3), (422, None), (400, None), (404, None)])
def test_extra_other_batch_codes_do_not_get_the_advice(
    key: str, simulate: Callable[..., Run], status: int, code: int | None
) -> None:
    """Section 4.1: the message exists only in the exhaustion path."""
    api = SlowApi(key, needed_read_s=60)
    api.batch_status = status

    result = simulate(api.transport, "--lots", "1", "--lot-size", "3", "--seed", "42")

    assert result.code != 0
    if code is not None:
        assert result.code == code
    assert "same seed" not in result.err


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_extra_exhausted_5xx_also_gets_the_advice(
    key: str, simulate: Callable[..., Run], status: int
) -> None:
    """The 5xx path retries too: it ends in the same exhaustion, with the status as last error."""
    api = SlowApi(key, needed_read_s=60)
    api.batch_status = status

    result = simulate(api.transport, "--lots", "1", "--lot-size", "3", "--seed", "42")

    assert result.code == 5
    assert len(api.batches()) == 4
    assert result.sleeps == [2, 4, 8]
    assert "batch failed after 4 attempts" in result.err
    assert "same seed" in result.err


def test_extra_connect_error_keeps_the_key_out_of_the_message(
    key: str, simulate: Callable[..., Run]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == URL_HEALTH:
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "db": "ok",
                    "api_version": "0.1.0",
                    "contract_version": qc_contracts.__version__,
                },
            )
        raise httpx.ConnectError(f"refused {key}", request=request)

    result = simulate(httpx.MockTransport(handler), "--lots", "1", "--lot-size", "3", "--seed", "7")

    assert result.code == 5
    assert "(last: ConnectError)" in result.err
    assert key not in result.out + result.err


def test_extra_the_timeout_budget_is_the_only_change(
    key: str, simulate: Callable[..., Run]
) -> None:
    """A batch that needs just under 60 s passes; one that needs more than 60 s does not."""
    below = SlowApi(key, needed_read_s=60)
    above = SlowApi(key, needed_read_s=60.01)

    assert simulate(below.transport, "--lots", "1", "--seed", "1").code == 0
    assert simulate(above.transport, "--lots", "1", "--seed", "1").code == 5


def test_extra_same_seed_regenerates_the_same_ids_at_another_time(
    key: str, simulate: Callable[..., Run]
) -> None:
    """CA-18, step 4, repeats later than the first run: the clock must not change the ids."""
    api = SlowApi(key, needed_read_s=13)

    first = simulate(api.transport, "--lots", "3", "--seed", "42")
    later = simulate(api.transport, "--lots", "3", "--seed", "42", now=NOW + timedelta(hours=6))

    assert "sent=75 created=75 duplicate=0" in first.out
    assert "sent=75 created=0 duplicate=75" in later.out


# --------------------------------------------------------------------------- CA-04


@pytest.fixture
def real_api(clean_db: str) -> Iterator[tuple[httpx.MockTransport, str, list[int]]]:
    """The real API on Postgres: the first POST is stored and then the client gets ReadTimeout."""
    from fastapi.testclient import TestClient

    from qc_api.auth import hash_api_key
    from qc_api.config import Settings
    from qc_api.main import create_app

    device_key = new_key()
    with psycopg.connect(clean_db, autocommit=True, prepare_threshold=None) as conn:
        conn.execute(
            "insert into devices (device_id, api_key_hash) values (%s, %s)",
            ("sim-01", hash_api_key(device_key)),
        )
    app = create_app(Settings(DATABASE_URL=clean_db, READ_API_KEY=secrets.token_urlsafe(32)))
    posts: list[int] = []

    with TestClient(app) as client:

        def forward(request: httpx.Request) -> httpx.Response:
            request.read()
            response = client.request(
                request.method,
                request.url.path,
                content=request.content,
                headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            )
            if request.method == "POST" and request.url.path == URL_BATCH:
                posts.append(response.status_code)
                if len(posts) == 1:
                    assert response.status_code == 200, response.text
                    raise httpx.ReadTimeout("stored, but the client never knew", request=request)
            return httpx.Response(response.status_code, content=response.content)

        yield httpx.MockTransport(forward), device_key, posts


def _rows(conninfo: str) -> tuple[int, int, int, str]:
    with psycopg.connect(conninfo, autocommit=True, prepare_threshold=None) as conn:
        row = conn.execute(
            "select count(*), count(distinct inspection_id), count(distinct source), "
            "min(source::text) from inspections"
        ).fetchone()
    assert row is not None
    return row


@pytest.mark.db
def test_ca04_stored_batch_is_not_duplicated_by_the_retry_or_the_repeat(
    real_api: tuple[httpx.MockTransport, str, list[int]],
    clean_db: str,
    key: str,
    monkeypatch: pytest.MonkeyPatch,
    simulate: Callable[..., Run],
) -> None:
    transport, device_key, posts = real_api
    monkeypatch.setenv("SIM_DEVICE_API_KEY", device_key)

    first = simulate(transport, "--lots", "3", "--seed", "42")

    assert first.code == 0, first.err
    assert "sent=75 created=0 duplicate=75" in first.out
    assert posts == [200, 200]
    assert first.sleeps == [2]
    assert _rows(clean_db) == (75, 75, 1, "simulated")

    # A repeat happens later: only the seed and the sizes keep the ids.
    second = simulate(transport, "--lots", "3", "--seed", "42", now=NOW + timedelta(hours=2))

    assert second.code == 0, second.err
    assert "created=0 duplicate=75" in second.out
    assert _rows(clean_db) == (75, 75, 1, "simulated")


# --------------------------------------------------------------------------- CA-10


@pytest.fixture
def sentinels() -> tuple[str, str]:
    return secrets.token_hex(8), secrets.token_hex(8)


@pytest.fixture
def no_connect(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """``psycopg.connect`` that fails the test: the refused URL must never reach it."""
    calls: list[Any] = []

    def refuse(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - must not run
        calls.append((args, kwargs))
        pytest.fail("psycopg.connect called with a malformed URL", pytrace=False)

    monkeypatch.setattr(psycopg, "connect", refuse)
    return calls


@pytest.mark.parametrize("label", MALFORMED_IDS)
def test_ca10_register_device_refuses_malformed_url(
    label: str,
    sentinels: tuple[str, str],
    no_connect: list[Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    a, b = sentinels
    monkeypatch.setenv("DATABASE_URL", malformed_urls(a, b)[label])

    with caplog.at_level(logging.DEBUG):
        code = register.main(["--device-id", "edge-01"])

    captured = capsys.readouterr()
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert code == 2
    assert captured.out == ""
    assert "invalid database URL (not shown)" in captured.err + logged
    assert no_connect == []
    for text in (captured.out, captured.err, logged):
        assert a not in text
        assert b not in text


def test_ca10_register_device_closed_port_exits_1_without_the_password(
    sentinels: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    a, _ = sentinels
    url = f"{SCHEME}u:{a}@127.0.0.1:{closed_port()}/x?connect_timeout=2"
    monkeypatch.setenv("DATABASE_URL", url)

    with caplog.at_level(logging.DEBUG):
        code = register.main(["--device-id", "edge-01"])

    captured = capsys.readouterr()
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert code == 1
    assert captured.out == ""
    assert "database error: OperationalError" in captured.err + logged
    assert a not in captured.out + captured.err + logged


# The real stderr of the script: the in-process tests above may share it with pytest's logging.
_CONNECT_GUARD = """
import runpy, sys
import psycopg
def refuse(*a, **k):
    print('CONNECT-CALLED', file=sys.stderr)
    raise SystemExit(99)
psycopg.connect = refuse
sys.argv = [sys.argv[1], '--device-id', 'edge-01']
runpy.run_path(sys.argv[0], run_name='__main__')
"""


@pytest.mark.parametrize("label", MALFORMED_IDS)
def test_extra_register_device_process_output(
    label: str, sentinels: tuple[str, str], tmp_path: Path
) -> None:
    """The script as a process: stderr has the refusal, stdout stays empty, exit code 2."""
    a, b = sentinels
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env["DATABASE_URL"] = malformed_urls(a, b)[label]

    result = subprocess.run(
        [sys.executable, "-c", _CONNECT_GUARD, str(REGISTER)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 2, result.stderr
    assert result.stdout == ""
    assert "invalid database URL (not shown)" in result.stderr
    assert "percent-encode" in result.stderr
    assert "CONNECT-CALLED" not in result.stderr
    assert a not in result.stderr
    assert b not in result.stderr


@pytest.mark.parametrize("rotate", [False, True], ids=["create", "rotate"])
def test_extra_register_device_refuses_before_any_key_also_when_rotating(
    rotate: bool,
    sentinels: tuple[str, str],
    no_connect: list[Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a, b = sentinels
    monkeypatch.setenv("DATABASE_URL", malformed_urls(a, b)["slash"])
    argv = ["--device-id", "sim-01"] + (["--rotate"] if rotate else [])

    assert register.main(argv) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert not re.search(r"[A-Za-z0-9_-]{32,}", captured.err)
