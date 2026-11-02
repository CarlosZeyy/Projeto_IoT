"""A malformed URL never connects and never shows a piece of the password (SPEC-043 section 4.2).

``psycopg.connect`` is replaced, and the passwords are built at run time (R-03).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

import psycopg
import pytest
from migrate import (
    UNSUPPORTED_CONNECTION_MESSAGE,
    DatabaseConnectionError,
    UnsupportedConnectionError,
    _host_port,
    apply_migrations,
    main,
    pending_migrations,
)

# Split so that the repository secret scanner sees no credential in a URL (R-03).
SCHEME = "postgresql" + "://"
PORT_6543 = SCHEME + "u:{a}@{b}@db.example.org:6543/postgres"
OTHER_PORTS = (
    SCHEME + "u:{a}/{b}@db.example.org:5432/postgres",
    SCHEME + "u:12/{b}@db.example.org:5432/postgres",
    SCHEME + "u:{a}@{b}:x@db.example.org:5432/postgres",
)
FUNCTIONS: tuple[Callable[[str], list[str]], ...] = (apply_migrations, pending_migrations)


@pytest.fixture
def left() -> str:
    return secrets.token_hex(8)


@pytest.fixture
def right() -> str:
    return secrets.token_hex(8)


@pytest.fixture(autouse=True)
def no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("psycopg.connect must not be called")

    monkeypatch.setattr(psycopg, "connect", fail)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGPORT", raising=False)


def _assert_refused_without_pieces(exc: Exception, left: str, right: str) -> None:
    assert exc.__cause__ is None
    assert left not in str(exc)
    assert right not in str(exc)


@pytest.mark.parametrize("template", OTHER_PORTS)
@pytest.mark.parametrize("function", FUNCTIONS)
def test_functions_refuse_before_connecting(
    function: Callable[[str], list[str]], template: str, left: str, right: str
) -> None:
    with pytest.raises(DatabaseConnectionError, match="malformed URL") as info:
        function(template.format(a=left, b=right))
    _assert_refused_without_pieces(info.value, left, right)


@pytest.mark.parametrize("function", FUNCTIONS)
def test_port_6543_keeps_its_own_refusal(
    function: Callable[[str], list[str]], left: str, right: str
) -> None:
    with pytest.raises(UnsupportedConnectionError) as info:
        function(PORT_6543.format(a=left, b=right))
    _assert_refused_without_pieces(info.value, left, right)


@pytest.mark.parametrize("template", (PORT_6543, *OTHER_PORTS))
def test_host_port_is_unknown(template: str, left: str, right: str) -> None:
    assert _host_port(template.format(a=left, b=right)) == "unknown host"


def test_host_port_of_a_well_formed_url(left: str) -> None:
    assert _host_port(f"{SCHEME}u:{left}@db.example.org:5432/x") == "db.example.org:5432"
    assert _host_port("dbname=x") == "default host:default port"


@pytest.mark.parametrize("extra", ([], ["--status"]))
@pytest.mark.parametrize("template", OTHER_PORTS)
def test_main_exits_2_with_the_hint(
    template: str,
    extra: list[str],
    left: str,
    right: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", template.format(a=left, b=right))
    assert main(extra) == 2
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "invalid database URL (not shown)" in output
    assert "percent-encode" in output
    assert left not in output
    assert right not in output


@pytest.mark.parametrize("extra", ([], ["--status"]))
def test_main_keeps_the_port_6543_message(
    extra: list[str],
    left: str,
    right: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", PORT_6543.format(a=left, b=right))
    assert main(extra) == 2
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert UNSUPPORTED_CONNECTION_MESSAGE in output
    assert "invalid database URL" not in output
    assert left not in output
    assert right not in output


def test_main_refuses_a_non_numeric_port(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``port=abc`` is refused before connecting (SPEC-043 section 7)."""
    monkeypatch.setenv("DATABASE_URL", "host=127.0.0.1 port=abc user=u dbname=x_test")
    assert main([]) == 2
    assert "invalid database URL (not shown)" in capsys.readouterr().err
