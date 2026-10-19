"""Production adjustments of infra/migrate.py (SPEC-015 section 4.7).

* refusal of the transaction pooler (port 6543) before any connection;
* deadline of the migration lock (``pg_try_advisory_lock``, ``lock_wait_s``);
* detection of COMMIT/ROLLBACK/BEGIN inside a migration file;
* ASCII-only digits in the file name;
* each file read exactly once.

Database tests are marked ``db`` and use an empty ``public`` schema that is restored afterwards.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from migrate import (
    ADVISORY_LOCK_KEY,
    DEFAULT_DIR,
    MigrationError,
    UnsupportedConnectionError,
    apply_migrations,
    load_migrations,
    pending_migrations,
)

SCRIPT = Path(__file__).resolve().parents[1] / "migrate.py"
INIT_SQL = DEFAULT_DIR / "001_init.sql"
SECRET = "s3cr3t-pw"
MESSAGE = "transaction pooler (port 6543) is not supported for migrations"


# ---------------------------------------------------------------- port 6543 (no database)


class Listener:
    """A TCP listener on 127.0.0.1 that counts accepted connections."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.accepted = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            self.accepted += 1
            conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.sock.close()


@pytest.fixture
def listener() -> Iterator[Listener]:
    server = Listener()
    yield server
    server.close()


def _refused_conninfos(port: int) -> list[tuple[str, dict[str, str]]]:
    """Conninfos whose effective port is 6543; ``port`` is where a real attempt would go."""
    return [
        ("postgresql://u:s3cr3t-pw@127.0.0.1:6543/x_test", {}),
        (f"postgresql://u@127.0.0.1:{port},127.0.0.1:6543/x_test", {}),
        (f"host=127.0.0.1 port=6543 user=u password={SECRET} dbname=x_test", {}),
        ("postgresql://u@127.0.0.1/x_test", {"PGPORT": "6543"}),
    ]


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("func", [apply_migrations, pending_migrations])
def test_functions_refuse_port_6543_before_connecting(
    listener: Listener, monkeypatch: pytest.MonkeyPatch, func, index: int
) -> None:
    conninfo, env = _refused_conninfos(listener.port)[index]
    monkeypatch.delenv("PGPORT", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(UnsupportedConnectionError) as info:
        func(conninfo)
    assert isinstance(info.value, MigrationError)
    assert str(info.value) == (
        "transaction pooler (port 6543) is not supported for migrations; "
        "use the direct connection or the session pooler (port 5432)"
    )
    assert SECRET not in str(info.value)
    assert listener.accepted == 0


@pytest.mark.parametrize("status", [False, True])
@pytest.mark.parametrize("index", range(4))
def test_cli_refuses_port_6543_with_exit_2(listener: Listener, status: bool, index: int) -> None:
    conninfo, extra = _refused_conninfos(listener.port)[index]
    env = {k: v for k, v in os.environ.items() if k not in {"PGPORT", "DATABASE_URL"}}
    env.update(extra)
    args = [sys.executable, str(SCRIPT), "--database-url", conninfo]
    if status:
        args.append("--status")
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 2
    assert MESSAGE in result.stderr
    assert SECRET not in result.stdout + result.stderr
    assert listener.accepted == 0


def test_other_ports_are_not_refused_by_the_check(listener: Listener) -> None:
    # Port of the local listener (not PostgreSQL): the check lets it through and the
    # connection attempt reaches the listener, so the refusal above is specific to 6543.
    with pytest.raises(MigrationError) as info:
        pending_migrations(f"postgresql://u@127.0.0.1:{listener.port}/x_test?connect_timeout=2")
    assert not isinstance(info.value, UnsupportedConnectionError)
    deadline = time.monotonic() + 2
    while listener.accepted == 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert listener.accepted >= 1


@pytest.mark.parametrize("value", [0, -1, float("nan")])
def test_lock_wait_must_be_positive(value: float) -> None:
    with pytest.raises(ValueError):
        apply_migrations("postgresql://u@127.0.0.1:1/x_test", lock_wait_s=value)


def test_lock_wait_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        apply_migrations("postgresql://u@127.0.0.1:1/x_test", DEFAULT_DIR, 1.0)  # type: ignore[misc]


# ---------------------------------------------------------------- file name and single read


def test_non_ascii_digits_are_an_invalid_name(tmp_path: Path) -> None:
    shutil.copyfile(INIT_SQL, tmp_path / "001_init.sql")
    (tmp_path / "١٢٣_x.sql").write_text("select 1;\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="invalid migration filename"):
        load_migrations(tmp_path)


def test_each_file_is_read_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.copyfile(INIT_SQL, tmp_path / "001_init.sql")
    calls: list[Path] = []
    original = Path.read_bytes

    def spy(self: Path) -> bytes:
        calls.append(self)
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    (migration,) = load_migrations(tmp_path)
    assert migration.read_sql() == INIT_SQL.read_text(encoding="utf-8")
    assert calls.count(tmp_path / "001_init.sql") == 1
    assert migration.checksum == hashlib.sha256(migration.content).hexdigest()
    assert "content" not in repr(migration)


# ---------------------------------------------------------------- database (db)


def _reset(conninfo: str) -> None:
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")


@pytest.fixture
def empty_schema(migrated_db: str) -> Iterator[str]:
    _reset(migrated_db)
    yield migrated_db
    _reset(migrated_db)
    apply_migrations(migrated_db)


def _query(conninfo: str, sql: str) -> list[tuple]:
    with psycopg.connect(conninfo) as conn:
        return conn.execute(sql).fetchall()


def _versions(conninfo: str) -> list[str]:
    exists = _query(conninfo, "select to_regclass('schema_migrations') is not null")[0][0]
    if not exists:
        return []
    return [row[0] for row in _query(conninfo, "select version from schema_migrations order by 1")]


@pytest.mark.db
def test_lock_deadline(empty_schema: str, tmp_path: Path) -> None:
    shutil.copyfile(INIT_SQL, tmp_path / "001_init.sql")
    with psycopg.connect(empty_schema, autocommit=True) as holder:
        holder.execute("select pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        started = time.monotonic()
        with pytest.raises(MigrationError) as info:
            apply_migrations(empty_schema, tmp_path, lock_wait_s=1)
        elapsed = time.monotonic() - started
        assert str(info.value).startswith("could not acquire the migration lock within")
        assert elapsed < 5
        assert _query(empty_schema, "select to_regclass('schema_migrations')") == [(None,)]
        holder.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
    assert apply_migrations(empty_schema, tmp_path, lock_wait_s=1) == ["001"]


@pytest.mark.db
def test_lock_is_taken_when_released_within_the_deadline(empty_schema: str, tmp_path: Path) -> None:
    shutil.copyfile(INIT_SQL, tmp_path / "001_init.sql")
    holder = psycopg.connect(empty_schema, autocommit=True)
    holder.execute("select pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
    timer = threading.Timer(1.5, holder.close)  # closing the session releases its lock
    timer.start()
    try:
        assert apply_migrations(empty_schema, tmp_path, lock_wait_s=10) == ["001"]
    finally:
        timer.join()
    assert _query(empty_schema, "select count(*) from pg_locks where locktype = 'advisory'") == [
        (0,)
    ]


@pytest.mark.db
@pytest.mark.parametrize(
    "body",
    [
        "create table t_tx(id int); commit;",
        "create table t_tx2(id int); commit; begin;",
        "create table t_tx3(id int); rollback;",
    ],
)
def test_transaction_control_in_the_file_is_detected(
    empty_schema: str, tmp_path: Path, body: str
) -> None:
    shutil.copyfile(INIT_SQL, tmp_path / "001_init.sql")
    (tmp_path / "002_tx.sql").write_text(body + "\n", encoding="utf-8")
    with pytest.raises(MigrationError) as info:
        apply_migrations(empty_schema, tmp_path)
    assert "ended the transaction" in str(info.value)
    assert "002" in str(info.value)
    assert _versions(empty_schema) == ["001"]
    # The lock is released even after this error.
    assert _query(empty_schema, "select count(*) from pg_locks where locktype = 'advisory'") == [
        (0,)
    ]


@pytest.mark.db
def test_checksum_recorded_is_the_sha256_of_the_single_read(
    empty_schema: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copyfile(INIT_SQL, tmp_path / "001_init.sql")
    target = tmp_path / "001_init.sql"
    seen: list[bytes] = []
    original = Path.read_bytes

    def spy(self: Path) -> bytes:
        data = original(self)
        if self == target:
            seen.append(data)
        return data

    monkeypatch.setattr(Path, "read_bytes", spy)
    assert apply_migrations(empty_schema, tmp_path) == ["001"]
    assert len(seen) == 1
    checksum = _query(empty_schema, "select checksum from schema_migrations")[0][0]
    assert checksum == hashlib.sha256(seen[0]).hexdigest()
