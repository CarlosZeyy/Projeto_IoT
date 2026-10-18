"""Session token (SPEC-007 section 4.3) and console Host rule (SPEC-025 section 4.1)."""

from __future__ import annotations

import re

import pytest

from qc_edge.config import EdgeSettings
from qc_edge.security import is_allowed_console_host, resolve_session_token, token_matches

URLSAFE = re.compile(r"[A-Za-z0-9_-]+")


def test_generated_tokens_are_long_urlsafe_and_distinct(settings: EdgeSettings) -> None:
    first = resolve_session_token(settings)
    second = resolve_session_token(settings)
    assert len(first) >= 43 and len(second) >= 43
    assert URLSAFE.fullmatch(first) and URLSAFE.fullmatch(second)
    assert first != second


def test_configured_token_is_used(settings: EdgeSettings) -> None:
    token = "c" * 40
    configured = EdgeSettings(EDGE_DATA_DIR=settings.EDGE_DATA_DIR, EDGE_SESSION_TOKEN=token)
    assert resolve_session_token(configured) == token


def test_token_matches() -> None:
    expected = "e" * 43
    assert token_matches(expected, expected)
    assert not token_matches(None, expected)
    assert not token_matches("", expected)
    assert not token_matches(expected[:-1], expected)
    assert not token_matches(expected + "e", expected)
    assert not token_matches("é" * 43, expected)
    assert not token_matches("\ud800", expected)  # lone surrogate: no exception
    assert not token_matches("e" * 10_000, expected)


@pytest.mark.parametrize(
    ("host", "port", "allowed"),
    [
        ("127.0.0.1:8000", 8000, True),
        ("localhost:8000", 8000, True),
        ("LOCALHOST:8000", 8000, True),
        ("LocalHost:8000", 8000, True),
        ("[::1]:8000", 8000, True),
        ("127.0.0.1:8123", 8123, True),
        ("127.0.0.1", 80, True),
        ("localhost", 80, True),
        ("[::1]", 80, True),
        ("127.0.0.1:80", 80, True),
        ("127.0.0.1", 8000, False),
        ("localhost", 8000, False),
        ("127.0.0.1:8001", 8000, False),
        ("127.0.0.1:08000", 8000, False),
        ("127.0.0.1:8000 ", 8000, False),
        (" 127.0.0.1:8000", 8000, False),
        ("127.0.0.1:8000.", 8000, False),
        ("localhost.:8000", 8000, False),
        ("127.0.0.1.nip.io:8000", 8000, False),
        ("attacker.example:8000", 8000, False),
        ("192.168.0.42:8000", 8000, False),
        ("::1:8000", 8000, False),
        ("[::1]", 8000, False),
        ("[0:0:0:0:0:0:0:1]:8000", 8000, False),
        ("127.1:8000", 8000, False),
        ("sub.localhost:8000", 8000, False),
        ("localhost:8000@attacker.example", 8000, False),
        ("attacker.example", 80, False),
        ("127.0.0.1:", 80, False),
        ("", 80, False),
        ("", 8000, False),
        (None, 8000, False),
        ("ＬＯＣＡＬＨＯＳＴ:8000", 8000, False),  # fullwidth letters: not ASCII
        ("localhost:8000\x00", 8000, False),
    ],
)
def test_is_allowed_console_host(host: str | None, port: int, allowed: bool) -> None:
    assert is_allowed_console_host(host, port) is allowed
