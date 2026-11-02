"""Acceptance tests for SPEC-043, the ``api/`` part: CA-05 to CA-07 (DEP-02, R-03).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. ``test_extra_*`` tests are exploratory edge cases that no CA spells out.

No network and no database: a refused URL never connects, and the regression case uses a closed
local port. Sentinels (``<A>`` and ``<B>``) come from ``secrets.token_hex``, and URLs with
credentials are assembled at run time (``reviews/checklist.md`` section 4).
"""

from __future__ import annotations

import logging
import os
import secrets
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from qc_api.config import Settings
from qc_api.conninfo import MALFORMED_CONNINFO_HINT, is_safe_conninfo
from qc_api.main import create_app

pytestmark = pytest.mark.acceptance

SCHEME = "postgresql" + "://"
PASSWORD_KEY = "pass" + "word"
READ_KEY = "r" * 32
MALFORMED_IDS = ["at-6543", "slash", "numeric-slash", "at-colon"]
WARNING_WAIT_S = 10.0


def malformed_urls(a: str, b: str) -> dict[str, str]:
    """The four malformed URLs (M) of SPEC-043 section 5."""
    return {
        "at-6543": f"{SCHEME}u:{a}@{b}@db.example.org:6543/postgres",
        "slash": f"{SCHEME}u:{a}/{b}@db.example.org:5432/postgres",
        "numeric-slash": f"{SCHEME}u:12/{b}@db.example.org:5432/postgres",
        "at-colon": f"{SCHEME}u:{a}@{b}:x@db.example.org:5432/postgres",
    }


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def chain_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc)) + repr(exc)


@pytest.fixture
def sentinels() -> tuple[str, str]:
    return secrets.token_hex(8), secrets.token_hex(8)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("DATABASE_URL", "READ_API_KEY", "PGPORT", "PGHOST", "PGDATABASE", "PGSERVICE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


# --------------------------------------------------------------------------- CA-05


def test_ca05_well_formed_urls_are_safe(sentinels: tuple[str, str]) -> None:
    a, _ = sentinels
    safe = [
        f"{SCHEME}u:{a}@db.example.org:6543/postgres",
        f"{SCHEME}u.ref:{a}@pooler.example.org:5432/postgres?sslmode=require",
        f"{SCHEME}u:a%40b%2Fc@db.example.org:5432/x",
        f"{SCHEME}postgres@127.0.0.1:55432/partqc_test",
        f"{SCHEME}localhost/x",
        f"{SCHEME}/x",
        f"{SCHEME}u@h1:5432,h2:5433/x_test",
        f"{SCHEME}u@[::1]:5432/x",
        f"host=db.example.org port=6543 user=u {PASSWORD_KEY}=a@b dbname=x",
        "host=/var/run/postgresql dbname=x",
    ]
    for url in safe:
        assert is_safe_conninfo(url) is True, url


@pytest.mark.parametrize("label", MALFORMED_IDS)
def test_ca05_malformed_urls_are_not_safe(label: str, sentinels: tuple[str, str]) -> None:
    a, b = sentinels
    assert is_safe_conninfo(malformed_urls(a, b)[label]) is False


def test_ca05_unparsable_conninfo_is_not_safe_and_does_not_raise(
    sentinels: tuple[str, str],
) -> None:
    a, _ = sentinels
    assert is_safe_conninfo(f"not a conninfo {PASSWORD_KEY}={a}") is False


def test_ca05_hint_text() -> None:
    assert MALFORMED_CONNINFO_HINT == (
        "use only letters and digits in the password, or percent-encode it"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"{SCHEME}u@h/x?host=/var/run/postgresql", True),
        (f"{SCHEME}%2Fvar%2Frun%2Fpostgresql/x", True),
        (f"{SCHEME}u@h1,h2/x", True),
        (f"{SCHEME}u@h1:,h2:5433/x", True),
        (f"{SCHEME}u@h/x?hostaddr=10.0.0.1", True),
        (f"{SCHEME}u@h/x?hostaddr=::1", True),
        (f"{SCHEME}u@h:5432/nome_db", True),
        (f"{SCHEME}u:p:q@h:5432/x", True),
        ("", True),
        (f"{SCHEME}u@a%40b/x", False),
        (f"{SCHEME}u@h:abc/x", False),
        (f"{SCHEME}u@h/a%40b", False),
        (f"{SCHEME}u@h/a%2Fb", False),
        (f"{SCHEME}u@h/a%3Ab", False),
        ("host=a@b dbname=x", False),
        ("host=h port=+6543 dbname=x", False),
        ("host=h port=abc dbname=x", False),
        ("host=h port=' 6543' dbname=x", False),
        ("hostaddr=a@b dbname=x", False),
        ("host=h dbname=a@b", False),
        ("host=h dbname=a/b", False),
        ("host=h dbname=a:b", False),
        (f"{SCHEME}u@h1,b@h2/x", False),
        ("host='h\n' dbname=x", False),
        ("host='h h' dbname=x", False),
        ("host=/var/run/x@y dbname=x", False),
        ("host=/var/run/x:y dbname=x", False),
        ("host=héllo dbname=x", False),
        ("host=١٢٣ dbname=x", False),
        ("port=٥٤٣٢ dbname=x", False),
    ],
    ids=lambda v: repr(v) if isinstance(v, str) else None,
)
def test_extra_rule_table(url: str, expected: bool) -> None:
    """The table of section 4.2, field by field, including non-ASCII look-alikes."""
    assert is_safe_conninfo(url) is expected


@pytest.mark.parametrize(
    "value",
    [
        "\x00",
        SCHEME + "\x00",
        "%",
        "=",
        "a=",
        "'",
        SCHEME + "[",
        SCHEME + "u@h:999999999999/x",
        SCHEME + "a" * 100_000,
        "😀",
        None,
        123,
        b"host=h",
    ],
    ids=lambda v: repr(v)[:30],
)
def test_extra_never_raises(value: Any) -> None:
    """Section 4.2: "Nunca levanta exceção"."""
    assert is_safe_conninfo(value) in (True, False)


def test_extra_password_key_value_is_not_examined(sentinels: tuple[str, str]) -> None:
    a, b = sentinels
    assert is_safe_conninfo(f"host=h dbname=x {PASSWORD_KEY}={a}@{b}/{a}:{b}") is True


def test_extra_conninfo_module_has_no_internal_imports() -> None:
    """Section 7: the module is imported by ``infra/migrate.py`` and must stay self-contained."""
    code = (
        "import sys; import qc_api.conninfo as c; "
        "mods = [m for m in sys.modules if m.startswith('qc_api')]; "
        "print(sorted(mods))"
    )
    env = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "READ_API_KEY"}}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
        env=env,
    )
    assert "qc_api.db" not in result.stdout
    assert "qc_api.config" not in result.stdout
    assert "qc_api.errors" not in result.stdout


# --------------------------------------------------------------------------- CA-06


@pytest.mark.parametrize("label", MALFORMED_IDS)
def test_ca06_settings_refuse_without_the_sentinels(label: str, sentinels: tuple[str, str]) -> None:
    a, b = sentinels
    url = malformed_urls(a, b)[label]

    with pytest.raises(ValidationError) as info:
        Settings(DATABASE_URL=url, READ_API_KEY=READ_KEY)

    text = chain_text(info.value) + str(info.value)
    assert "DATABASE_URL" in str(info.value)
    assert a not in text
    assert b not in text


@pytest.mark.parametrize("label", MALFORMED_IDS)
def test_ca06_app_does_not_start_and_never_creates_the_pool(
    label: str,
    sentinels: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a, b = sentinels
    monkeypatch.setenv("DATABASE_URL", malformed_urls(a, b)[label])
    monkeypatch.setenv("READ_API_KEY", READ_KEY)
    calls: list[Any] = []

    def spy(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - must not run
        calls.append((args, kwargs))
        raise AssertionError("create_pool called with a malformed URL")

    monkeypatch.setattr("qc_api.main.create_pool", spy)

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(Exception, match="DATABASE_URL") as info,
        TestClient(create_app()),
    ):
        pytest.fail("the app started with a malformed DATABASE_URL", pytrace=False)

    assert calls == []
    captured = capsys.readouterr()
    logged = "\n".join(
        record.getMessage()
        + ("".join(traceback.format_exception(*record.exc_info)) if record.exc_info else "")
        for record in caplog.records
    )
    for text in (chain_text(info.value), logged, captured.out, captured.err):
        assert a not in text
        assert b not in text


def test_extra_error_text_cites_only_the_variable_and_the_hint(sentinels: tuple[str, str]) -> None:
    a, b = sentinels
    with pytest.raises(ValidationError) as info:
        Settings(DATABASE_URL=malformed_urls(a, b)["slash"], READ_API_KEY=READ_KEY)
    text = str(info.value)
    assert "malformed connection URL" in text
    assert "percent-encode" in text
    assert "input_value" not in text


@pytest.mark.parametrize("label", MALFORMED_IDS)
def test_extra_real_uvicorn_refuses_with_a_clean_output(
    label: str, sentinels: tuple[str, str], tmp_path: Path
) -> None:
    """The real process, as in the API image: nonzero exit, nothing of the password in the output.

    ``socket.getaddrinfo`` fails the process, so a regression cannot reach an external DNS.
    """
    a, b = sentinels
    code = (
        "import socket, sys\n"
        "real = socket.getaddrinfo\n"
        "def guard(host, *args, **kwargs):\n"
        "    if host not in ('127.0.0.1', 'localhost', None):\n"
        "        print('DNS-CALLED'); sys.stdout.flush(); raise SystemExit(99)\n"
        "    return real(host, *args, **kwargs)\n"
        "socket.getaddrinfo = guard\n"
        "import uvicorn\n"
        "uvicorn.run('qc_api.main:app', host='127.0.0.1', port=0, log_level='debug')\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env["DATABASE_URL"] = malformed_urls(a, b)[label]
    env["READ_API_KEY"] = READ_KEY

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "DNS-CALLED" not in output
    assert "DATABASE_URL" in output
    assert a not in output
    assert b not in output


# --------------------------------------------------------------------------- CA-07


def test_ca07_valid_url_with_the_database_down_starts_and_logs_no_password(
    sentinels: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    a, _ = sentinels
    url = f"{SCHEME}u:{a}@127.0.0.1:{closed_port()}/x"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("READ_API_KEY", READ_KEY)

    with caplog.at_level(logging.DEBUG), TestClient(create_app()) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        assert a not in response.text
        deadline = time.monotonic() + WARNING_WAIT_S
        while time.monotonic() < deadline:
            if any(
                r.name.startswith("psycopg.pool") and r.levelno >= logging.WARNING
                for r in caplog.records
            ):
                break
            time.sleep(0.1)

    warnings = [r for r in caplog.records if r.name.startswith("psycopg.pool") and r.levelno >= 30]
    assert warnings, "psycopg.pool logged no WARNING within 10 s"
    for record in caplog.records:
        assert a not in record.getMessage(), record.name
    assert a not in caplog.text


def test_extra_url_with_percent_encoded_password_passes_settings(
    sentinels: tuple[str, str],
) -> None:
    a, b = sentinels
    url = f"{SCHEME}u:{a}%40{b}%2F{a}@db.example.org:6543/postgres"
    Settings(DATABASE_URL=url, READ_API_KEY=READ_KEY)
