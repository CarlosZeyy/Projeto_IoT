"""``X-API-Key`` authentication (SPEC-004 section 4.3, docs/architecture.md section 4).

* Device keys: only the SHA-256 of the key is stored (``devices.api_key_hash``).
* Read key: a single ``READ_API_KEY`` (used by the dashboard, SPEC-005).

Every failure is the same 401 (``Missing or invalid API key``), whatever the reason. Keys and
their hashes are never logged (R-03).
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader

from qc_api.db import find_device_by_key_hash
from qc_api.errors import unauthorized

API_KEY_HEADER = "X-API-Key"
MAX_API_KEY_LENGTH = 256

_api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)
ApiKey = Annotated[str | None, Depends(_api_key_header)]


def hash_api_key(key: str) -> str:
    """SHA-256 of the UTF-8 key, in lowercase hex (what ``devices.api_key_hash`` stores)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def require_device(request: Request, api_key: ApiKey) -> str:
    """Return the ``device_id`` that owns the ``X-API-Key``; 401 otherwise.

    A missing, empty or oversized key is refused before touching the database. A database
    failure during the lookup becomes 503 (``DatabaseUnavailableError``).
    """
    if not api_key or len(api_key) > MAX_API_KEY_LENGTH:
        raise unauthorized()
    key_hash = hash_api_key(api_key)
    row = find_device_by_key_hash(request.app.state.pool, key_hash)
    if row is None:
        raise unauthorized()
    device_id, stored_hash = row
    if not secrets.compare_digest(stored_hash.encode("ascii"), key_hash.encode("ascii")):
        raise unauthorized()
    # Read by the request-log middleware (the owner of the key, never the key itself).
    request.state.device_id = device_id
    return device_id


def require_read_key(request: Request, api_key: ApiKey) -> None:
    """Accept only ``READ_API_KEY`` (constant-time comparison); 401 otherwise."""
    if not api_key:
        raise unauthorized()
    expected = request.app.state.settings.READ_API_KEY.get_secret_value()
    # Bytes, not str: compare_digest refuses non-ASCII str, and the header is client-controlled.
    if not secrets.compare_digest(api_key.encode("utf-8"), expected.encode("utf-8")):
        raise unauthorized()
