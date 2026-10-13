"""Session token (SPEC-007 section 4.3)."""

from __future__ import annotations

import re

from qc_edge.config import EdgeSettings
from qc_edge.security import resolve_session_token, token_matches

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
