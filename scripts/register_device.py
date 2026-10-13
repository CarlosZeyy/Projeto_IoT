"""Register a device, or rotate its key (SPEC-004 section 4.6, docs/architecture.md section 4).

Usage::

    uv run --package qc-api python scripts/register_device.py --device-id edge-01
                                                              [--rotate] [--database-url URL]

The default URL comes from ``DATABASE_URL``. A new key is generated with
``secrets.token_urlsafe(32)``; only its SHA-256 (``qc_api.auth.hash_api_key``) is stored. The key
is the command's output: a single ``DEVICE_API_KEY=<key>`` line on stdout, shown only once.
Status messages go to stderr through ``logging`` and never contain the key nor the URL (R-03).

* Without ``--rotate``: the device must not exist yet.
* With ``--rotate``: the device must exist; its hash is replaced, so the old key stops working
  immediately.

Exit codes: ``0`` success; ``1`` device already exists / does not exist, or database failure;
``2`` invalid usage (``--device-id`` outside the contract regex, no URL, invalid URL).
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import secrets
import sys
from collections.abc import Sequence

import psycopg
from psycopg.conninfo import conninfo_to_dict

from qc_api.auth import hash_api_key
from qc_contracts import DEVICE_ID_PATTERN

logger = logging.getLogger("partqc.register_device")

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
CONNECT_TIMEOUT_S = 10

_INSERT_DEVICE = """
insert into devices (device_id, api_key_hash) values (%s, %s)
on conflict (device_id) do nothing
returning device_id
"""
_ROTATE_KEY = "update devices set api_key_hash = %s where device_id = %s returning device_id"


class DeviceStateError(Exception):
    """The device exists (register) or does not exist (rotate)."""


def generate_api_key() -> str:
    """Random device key (43 URL-safe characters)."""
    return secrets.token_urlsafe(32)


def store_key(conninfo: str, device_id: str, key_hash: str, *, rotate: bool) -> None:
    """Insert the device, or replace its hash with ``rotate``; commits before returning."""
    with psycopg.connect(
        conninfo, prepare_threshold=None, connect_timeout=CONNECT_TIMEOUT_S
    ) as conn:
        if rotate:
            row = conn.execute(_ROTATE_KEY, (key_hash, device_id)).fetchone()
            if row is None:
                raise DeviceStateError(f"device {device_id} does not exist (nothing to rotate)")
        else:
            row = conn.execute(_INSERT_DEVICE, (device_id, key_hash)).fetchone()
            if row is None:
                raise DeviceStateError(
                    f"device {device_id} already exists (use --rotate to replace its key)"
                )
        # Leaving the ``with`` block commits.


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="register_device.py",
        description="Register a device in the qc-api database, or rotate its API key.",
    )
    parser.add_argument("--device-id", required=True, help="device id, e.g. edge-01")
    parser.add_argument(
        "--rotate", action="store_true", help="replace the key of an existing device"
    )
    parser.add_argument(
        "--database-url",
        help="PostgreSQL connection URL (default: the DATABASE_URL environment variable)",
    )
    return parser


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the exit code."""
    args = _build_parser().parse_args(argv)  # exits with code 2 on invalid arguments
    _configure_logging()

    device_id: str = args.device_id
    # fullmatch, never match/search: "$" would accept a trailing "\n" (architecture.md 3.2).
    if re.fullmatch(DEVICE_ID_PATTERN, device_id) is None:
        logger.error("invalid --device-id: must match %s", DEVICE_ID_PATTERN)
        return EXIT_USAGE
    conninfo = (args.database_url or os.environ.get("DATABASE_URL", "")).strip()
    if not conninfo:
        logger.error("no database URL: set DATABASE_URL or pass --database-url")
        return EXIT_USAGE
    try:
        conninfo_to_dict(conninfo)
    except Exception:
        # The parser's message may echo the string (and a password): never show it.
        logger.error("invalid database URL (not shown)")
        return EXIT_USAGE

    key = generate_api_key()
    try:
        store_key(conninfo, device_id, hash_api_key(key), rotate=args.rotate)
    except DeviceStateError as exc:
        logger.error("%s", exc)
        return EXIT_FAILURE
    except psycopg.Error as exc:
        # Only the type: connection errors may describe the target.
        logger.error("database error: %s", type(exc).__name__)
        return EXIT_FAILURE

    logger.info("%s device %s; the key below is shown only once", _verb(args.rotate), device_id)
    # The key is the command's output (not a log record): stdout, one line.
    sys.stdout.write(f"DEVICE_API_KEY={key}\n")
    sys.stdout.flush()
    return EXIT_OK


def _verb(rotate: bool) -> str:
    return "rotated the key of" if rotate else "registered"


if __name__ == "__main__":
    sys.exit(main())
