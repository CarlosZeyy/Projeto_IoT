"""Session token of the capture page (SPEC-007 section 4.3, docs/architecture.md section 6.1).

The token comes from ``EDGE_SESSION_TOKEN`` or is generated at startup with
``secrets.token_urlsafe(32)`` (43 URL-safe characters). It is compared in constant time and never
logged (R-03).
"""

from __future__ import annotations

import secrets

from qc_edge.config import EdgeSettings

SESSION_TOKEN_HEADER = "X-Session-Token"
SESSION_TOKEN_QUERY = "t"
GENERATED_TOKEN_BYTES = 32
# Longer values are refused before the comparison (a generated token has 43 characters).
MAX_TOKEN_LENGTH = 512


def resolve_session_token(settings: EdgeSettings) -> str:
    """``EDGE_SESSION_TOKEN`` when configured; otherwise a new random token."""
    if settings.EDGE_SESSION_TOKEN is not None:
        return settings.EDGE_SESSION_TOKEN.get_secret_value()
    return secrets.token_urlsafe(GENERATED_TOKEN_BYTES)


def token_matches(provided: str | None, expected: str) -> bool:
    """Constant-time comparison; a missing, empty or oversized value never matches."""
    if not provided or len(provided) > MAX_TOKEN_LENGTH:
        return False
    # Bytes, not str: compare_digest refuses non-ASCII str, and the value is client-controlled.
    return secrets.compare_digest(
        provided.encode("utf-8", "surrogatepass"), expected.encode("utf-8", "surrogatepass")
    )
