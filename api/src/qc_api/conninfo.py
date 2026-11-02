"""Refuse a database URL that libpq would split inside the password (SPEC-043 section 4.2, R-03).

libpq ends the credentials at the first ``@`` or ``/`` of a URL, so a password with one of them
spills into ``host``, ``port`` or ``dbname``. Those fields show up in connection errors and in DNS
queries, which is how a piece of the password would leave the process.

This is a heuristic over what the parser returns: a password that happens to form a valid host and
port, with a clean dbname, cannot be told from a real URL. The deployment plan's rule (only letters
and digits in the password) is the main defense.

No dependency on other ``qc_api`` modules: ``infra/migrate.py`` and ``scripts/register_device.py``
import this one.
"""

from __future__ import annotations

import re

from psycopg.conninfo import conninfo_to_dict

__all__ = ["MALFORMED_CONNINFO_HINT", "is_safe_conninfo"]

MALFORMED_CONNINFO_HINT = "use only letters and digits in the password, or percent-encode it"

_HOST = re.compile(r"[A-Za-z0-9._:-]+|/[A-Za-z0-9._/-]*")
_PORT = re.compile(r"[0-9]+")
_DBNAME = re.compile(r"[^@/:]+")


def _pieces_match(value: str, pattern: re.Pattern[str]) -> bool:
    """Every comma-separated piece of ``value`` matches ``pattern``; an empty piece is accepted."""
    return all(not piece or pattern.fullmatch(piece) for piece in value.split(","))


def is_safe_conninfo(conninfo: str) -> bool:
    """False when a piece of the password could have landed in host, port or dbname.

    Never raises: a conninfo the parser refuses is simply not safe. A percent-encoded password is
    decoded by libpq and stays valid, and the password of a ``key=value`` conninfo is not examined.
    """
    try:
        params = conninfo_to_dict(conninfo)
    except Exception:
        return False
    dbname = params.get("dbname")
    return (
        _pieces_match(str(params.get("host") or ""), _HOST)
        and _pieces_match(str(params.get("hostaddr") or ""), _HOST)
        and _pieces_match(str(params.get("port") or ""), _PORT)
        and (not dbname or _DBNAME.fullmatch(str(dbname)) is not None)
    )
