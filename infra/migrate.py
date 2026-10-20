"""Minimal SQL migration runner (SPEC-003 section 4.2, ADR-006).

Applies ``infra/migrations/NNN_slug.sql`` in order, each one in its own transaction together with
its row in ``schema_migrations`` (version, filename, SHA-256 checksum). Concurrent runs are
serialized with a session-level advisory lock, taken with ``pg_try_advisory_lock`` and a deadline
(SPEC-015 section 4.7). Connections use ``prepare_threshold=None``.

Production migrations go through the direct connection or the Supabase pooler in **session**
mode (port 5432), never through the transaction pooler (port 6543), which loses session-level
advisory locks between transactions: a conninfo whose effective port is 6543 is refused before
any connection (``UnsupportedConnectionError``). Read the URL from a local, git-ignored file::

    uv run --env-file .env.migrate --package qc-api python infra/migrate.py

Usage::

    uv run --package qc-api python infra/migrate.py [--database-url URL]
                                                    [--migrations-dir DIR] [--status]

The default URL comes from ``DATABASE_URL``. Exit codes: ``0`` success; ``1`` database,
migration or checksum failure; ``2`` invalid usage. The URL and its password are never logged
(R-03): connection errors show only the exception type and host/port.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from psycopg import pq
from psycopg.conninfo import conninfo_to_dict

__all__ = [
    "DEFAULT_DIR",
    "DatabaseConnectionError",
    "Migration",
    "MigrationError",
    "UnsupportedConnectionError",
    "apply_migrations",
    "ensure_supported_connection",
    "load_migrations",
    "main",
    "pending_migrations",
]

logger = logging.getLogger("partqc.migrate")

DEFAULT_DIR = Path(__file__).resolve().parent / "migrations"
# ASCII digits only: ``\d`` would also accept other Unicode digits (SPEC-015 section 4.7).
FILENAME_PATTERN = re.compile(r"^[0-9]{3}_[a-z0-9_]+\.sql$")
# Constant key of the advisory lock that serializes concurrent runs ("PQCMIG" in ASCII).
ADVISORY_LOCK_KEY = 0x5051_434D_4947
CONNECT_TIMEOUT_S = 10
# Default deadline for the migration lock and the interval between attempts (SPEC-015 4.7).
DEFAULT_LOCK_WAIT_S = 30.0
LOCK_RETRY_INTERVAL_S = 1.0
# Port of the Supabase transaction pooler, refused for migrations (SPEC-015 section 4.7).
TRANSACTION_POOLER_PORT = 6543
UNSUPPORTED_CONNECTION_MESSAGE = (
    "transaction pooler (port 6543) is not supported for migrations; "
    "use the direct connection or the session pooler (port 5432)"
)

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

_CREATE_CONTROL_TABLE = """
create table if not exists schema_migrations (
    version text primary key,
    filename text not null,
    checksum text not null,
    applied_at timestamptz not null default now()
)
"""
_ENABLE_CONTROL_TABLE_RLS = "alter table schema_migrations enable row level security"
_CONTROL_TABLE_EXISTS = "select to_regclass('schema_migrations') is not null"
_SELECT_APPLIED = "select version, filename, checksum from schema_migrations order by version"
_INSERT_APPLIED = "insert into schema_migrations (version, filename, checksum) values (%s, %s, %s)"


class MigrationError(Exception):
    """Invalid migration files, checksum mismatch or failure while applying a migration."""


class DatabaseConnectionError(MigrationError):
    """The database could not be reached. The message never contains the URL or the password."""


class UnsupportedConnectionError(MigrationError):
    """The conninfo targets the transaction pooler (port 6543). The URL is never in the message."""


@dataclass(frozen=True)
class Migration:
    """One migration file: ``version`` is the 3-digit prefix (e.g. ``"001"``)."""

    version: str
    path: Path
    checksum: str
    # The bytes read once by ``load_migrations``: the checksum and the SQL come from them.
    content: bytes = field(repr=False)

    @property
    def filename(self) -> str:
        return self.path.name

    def read_sql(self) -> str:
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError:
            raise MigrationError(f"migration {self.filename!r} is not valid UTF-8") from None


@dataclass(frozen=True)
class _AppliedRow:
    version: str
    filename: str
    checksum: str


def load_migrations(migrations_dir: Path = DEFAULT_DIR) -> list[Migration]:
    """Validate the ``.sql`` files of ``migrations_dir`` and return them ordered by number.

    Raises ``MigrationError`` (before anything touches the database) if a ``.sql`` file does not
    match ``NNN_slug.sql`` or if two files share the same number. Other files are ignored.
    """
    directory = Path(migrations_dir)
    if not directory.is_dir():
        raise MigrationError(f"migrations directory not found: {directory}")

    by_number: dict[int, Migration] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".sql":
            continue
        if FILENAME_PATTERN.fullmatch(path.name) is None:
            raise MigrationError(
                f"invalid migration filename: {path.name!r} (expected NNN_slug.sql, "
                "slug in lowercase letters, digits and underscores)"
            )
        version = path.name[:3]
        number = int(version)
        if number in by_number:
            raise MigrationError(
                f"duplicate migration number {version}: "
                f"{by_number[number].filename!r} and {path.name!r}"
            )
        content = path.read_bytes()  # the only read of the file (SPEC-015 section 4.7)
        by_number[number] = Migration(
            version=version,
            path=path,
            checksum=hashlib.sha256(content).hexdigest(),
            content=content,
        )
    return [by_number[number] for number in sorted(by_number)]


def _host_port(conninfo: str) -> str:
    """Return ``host:port`` of a conninfo for error messages, never the rest of it."""
    try:
        params = conninfo_to_dict(conninfo)
    except Exception:
        return "unknown host"
    host = params.get("host") or params.get("hostaddr") or "default host"
    port = params.get("port") or "default port"
    return f"{host}:{port}"


def _effective_ports(conninfo: str) -> list[str]:
    """Ports libpq would use for ``conninfo``: one per host, ``PGPORT`` when not written.

    Returns ``[]`` when the conninfo cannot be parsed (the connection would fail anyway).
    """
    try:
        params = conninfo_to_dict(conninfo)
    except psycopg.ProgrammingError:  # the only error of the conninfo parser
        return []
    fallback = os.environ.get("PGPORT", "").strip()
    written = str(params.get("port") or "")
    if not written:
        return [port.strip() for port in fallback.split(",")] if fallback else []
    # With several hosts the port is a comma-separated list; an empty item is the default port.
    return [port.strip() or fallback for port in written.split(",")]


def _is_transaction_pooler_port(port: str) -> bool:
    """``True`` for any spelling of 6543 (``"06543"``, ``"+6543"``...); a non-number is not."""
    try:
        return int(port) == TRANSACTION_POOLER_PORT
    except ValueError:
        return False


def ensure_supported_connection(conninfo: str) -> None:
    """Refuse, before any connection, a conninfo whose effective port is the transaction pooler.

    The port is compared as a number, so ``06543`` is refused too. Raises
    ``UnsupportedConnectionError``; the message never contains the URL (R-03).
    """
    if any(_is_transaction_pooler_port(port) for port in _effective_ports(conninfo)):
        raise UnsupportedConnectionError(UNSUPPORTED_CONNECTION_MESSAGE)


@contextmanager
def _connect(conninfo: str) -> Iterator[psycopg.Connection]:
    try:
        conn = psycopg.connect(
            conninfo,
            autocommit=True,
            prepare_threshold=None,
            connect_timeout=CONNECT_TIMEOUT_S,
        )
    except Exception as exc:
        # `from None`: the original exception (and its message) may echo the conninfo.
        raise DatabaseConnectionError(
            f"could not connect to the database at {_host_port(conninfo)} ({type(exc).__name__})"
        ) from None
    try:
        yield conn
    finally:
        conn.close()


def _applied_rows(conn: psycopg.Connection) -> dict[str, _AppliedRow]:
    exists = conn.execute(_CONTROL_TABLE_EXISTS).fetchone()
    if not exists or not exists[0]:
        return {}
    rows = conn.execute(_SELECT_APPLIED).fetchall()
    return {row[0]: _AppliedRow(*row) for row in rows}


def _plan(migrations: Sequence[Migration], applied: dict[str, _AppliedRow]) -> list[Migration]:
    """Check the checksums of the applied migrations and return the pending ones, in order."""
    files = {migration.version: migration for migration in migrations}
    for version, row in sorted(applied.items()):
        migration = files.get(version)
        if migration is None:
            logger.warning(
                "migration %s (%s) is recorded as applied but its file is missing",
                version,
                row.filename,
            )
            continue
        if migration.checksum != row.checksum:
            raise MigrationError(f"checksum mismatch for {version}")
    return [migration for migration in migrations if migration.version not in applied]


def pending_migrations(conninfo: str, migrations_dir: Path = DEFAULT_DIR) -> list[str]:
    """Return the versions not yet applied, in order, without changing the database.

    Raises ``MigrationError`` for invalid files or a checksum mismatch, like ``apply_migrations``.
    """
    ensure_supported_connection(conninfo)
    migrations = load_migrations(migrations_dir)
    with _connect(conninfo) as conn:
        applied = _applied_rows(conn)
    return [migration.version for migration in _plan(migrations, applied)]


def _ensure_control_table(conn: psycopg.Connection) -> None:
    with conn.transaction():
        conn.execute(_CREATE_CONTROL_TABLE)
        conn.execute(_ENABLE_CONTROL_TABLE_RLS)


def _current_xact_id(conn: psycopg.Connection) -> object:
    row = conn.execute("select pg_current_xact_id()").fetchone()
    return row[0] if row else None


def _ended_transaction_error(migration: Migration) -> MigrationError:
    return MigrationError(
        f"migration {migration.version} ({migration.filename}) ended the transaction "
        "(COMMIT/ROLLBACK/BEGIN in the file); statements before it may have been committed; "
        "fix the file and check the database by hand"
    )


def _apply_one(conn: psycopg.Connection, migration: Migration) -> None:
    sql = migration.read_sql()
    try:
        with conn.transaction():
            xact_before = _current_xact_id(conn)
            # No parameters: the file runs as-is through the simple query protocol, which
            # allows several statements. Nothing is interpolated into it.
            conn.execute(sql)
            # A COMMIT/ROLLBACK (and maybe a new BEGIN) inside the file ends our transaction:
            # never record such a migration as applied (RV-02 of SPEC-003, SPEC-015 4.7).
            if (
                conn.info.transaction_status != pq.TransactionStatus.INTRANS
                or _current_xact_id(conn) != xact_before
            ):
                raise _ended_transaction_error(migration)
            conn.execute(
                _INSERT_APPLIED, (migration.version, migration.filename, migration.checksum)
            )
    except psycopg.Error as exc:
        raise MigrationError(
            f"migration {migration.version} ({migration.filename}) failed and was rolled back: "
            f"{type(exc).__name__}: {str(exc).strip()}"
        ) from exc


def _acquire_lock(conn: psycopg.Connection, lock_wait_s: float) -> None:
    """Take the migration lock, trying every ``LOCK_RETRY_INTERVAL_S`` until the deadline."""
    deadline = time.monotonic() + lock_wait_s
    while True:
        row = conn.execute("select pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,)).fetchone()
        if row and row[0]:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MigrationError(
                f"could not acquire the migration lock within {lock_wait_s:g} s "
                "(another migration run may be in progress); nothing was applied"
            )
        time.sleep(min(LOCK_RETRY_INTERVAL_S, remaining))


def apply_migrations(
    conninfo: str,
    migrations_dir: Path = DEFAULT_DIR,
    *,
    lock_wait_s: float = DEFAULT_LOCK_WAIT_S,
) -> list[str]:
    """Apply the pending migrations in order and return the versions applied in this run.

    Each migration runs in its own transaction together with its ``schema_migrations`` row; on
    error it is rolled back, nothing is recorded and the following ones are not applied. An
    applied migration whose file changed raises ``checksum mismatch for <version>`` and nothing
    is applied. Without the migration lock within ``lock_wait_s`` seconds (> 0), raises
    ``MigrationError`` and applies nothing. A conninfo on port 6543 raises
    ``UnsupportedConnectionError`` before any connection.
    """
    if not lock_wait_s > 0:  # also refuses NaN
        raise ValueError("lock_wait_s must be greater than 0")
    ensure_supported_connection(conninfo)
    migrations = load_migrations(migrations_dir)
    applied_now: list[str] = []
    with _connect(conninfo) as conn:
        _acquire_lock(conn, lock_wait_s)
        try:
            _ensure_control_table(conn)
            pending = _plan(migrations, _applied_rows(conn))
            for migration in pending:
                _apply_one(conn, migration)
                applied_now.append(migration.version)
                logger.info("applied migration %s (%s)", migration.version, migration.filename)
        finally:
            if not conn.closed and not conn.broken:
                conn.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
    if not applied_now:
        logger.info("no pending migrations")
    return applied_now


def _status(conninfo: str, migrations_dir: Path) -> None:
    ensure_supported_connection(conninfo)
    migrations = load_migrations(migrations_dir)
    with _connect(conninfo) as conn:
        applied = _applied_rows(conn)
    pending = {migration.version for migration in _plan(migrations, applied)}
    for migration in migrations:
        state = "pending" if migration.version in pending else "applied"
        logger.info("%s %s %s", migration.version, state, migration.filename)
    for version, row in sorted(applied.items()):
        if all(migration.version != version for migration in migrations):
            logger.info("%s applied %s (file missing)", version, row.filename)
    logger.info("%d applied, %d pending", len(applied), len(pending))


class _MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def _configure_logging() -> None:
    """INFO goes to stdout (the command's output); warnings and errors go to stderr."""
    formatter = logging.Formatter("%(levelname)s %(message)s")
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.addFilter(_MaxLevelFilter(logging.INFO))
    stdout_handler.setFormatter(formatter)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)
    logger.handlers[:] = [stdout_handler, stderr_handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migrate.py",
        description="Apply the SQL migrations of infra/migrations to a PostgreSQL database.",
    )
    parser.add_argument(
        "--database-url",
        help="PostgreSQL connection URL (default: the DATABASE_URL environment variable)",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_DIR,
        help="directory with the NNN_slug.sql files (default: infra/migrations)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="list applied and pending migrations without applying anything",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)  # exits with code 2 on invalid arguments
    _configure_logging()

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
    try:
        ensure_supported_connection(conninfo)
    except UnsupportedConnectionError as exc:
        logger.error("%s", exc)
        return EXIT_USAGE
    if not Path(args.migrations_dir).is_dir():
        logger.error("migrations directory not found: %s", args.migrations_dir)
        return EXIT_USAGE

    try:
        if args.status:
            _status(conninfo, args.migrations_dir)
        else:
            apply_migrations(conninfo, args.migrations_dir)
    except MigrationError as exc:
        logger.error("%s", exc)
        return EXIT_FAILURE
    except psycopg.Error as exc:
        # Server-side errors (e.g. connection lost while running); the message comes from
        # the server and does not contain the connection string.
        logger.error("database error: %s", type(exc).__name__)
        return EXIT_FAILURE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
