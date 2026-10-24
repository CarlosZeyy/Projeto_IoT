"""Requeue of ``dead`` outbox items (SPEC-034): ``dead_items``, ``requeue_dead`` and the CLI."""

from __future__ import annotations

import hashlib
import logging
import os
import random
import secrets
import socket
import sqlite3
import subprocess
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qc_edge import requeue
from qc_edge.outbox import (
    DeadItem,
    NotAnOutboxError,
    SqliteOutbox,
    format_timestamp,
)
from qc_edge.publish_loop import ConnectivityState, PublishLoop
from qc_edge.publisher import HttpPublisher

EDGE_SRC = Path(__file__).resolve().parents[1] / "src"
CONTRACTS_SRC = Path(__file__).resolve().parents[2] / "packages" / "contracts" / "src"
SUMMARY = "dead item(s); run again with --yes to requeue"


@pytest.fixture
def clock(fake_cloud: types.ModuleType) -> Any:
    return fake_cloud.FakeClock()


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "outbox.sqlite3"


@pytest.fixture
def outbox(path: Path, clock: Any) -> Iterator[SqliteOutbox]:
    box = SqliteOutbox(path, clock=clock)
    yield box
    box.close()


def rows(path: Path) -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return {row["inspection_id"]: dict(row) for row in conn.execute("SELECT * FROM outbox")}
    finally:
        conn.close()


def put(box: SqliteOutbox, fake_cloud: types.ModuleType, **overrides: Any) -> UUID:
    inspection = fake_cloud.make_inspection(**overrides)
    box.put(inspection)
    return inspection.inspection_id


def mixed(box: SqliteOutbox, fake_cloud: types.ModuleType, clock: Any) -> dict[str, list[UUID]]:
    """3 ``dead`` (with retries before), 2 ``pending`` (one with a retry) and 1 ``sent``."""
    ids = {name: [] for name in ("dead", "pending", "sent")}
    for _ in range(3):
        ids["dead"].append(put(box, fake_cloud))
        clock.advance(1)
    for _ in range(2):
        ids["pending"].append(put(box, fake_cloud))
        clock.advance(1)
    ids["sent"].append(put(box, fake_cloud))
    box.mark_retry([*ids["dead"], ids["pending"][0]], "HTTP 503", lambda attempts: 30.0)
    clock.advance(1)
    for number, inspection_id in enumerate(ids["dead"]):
        box.mark_dead(inspection_id, f"HTTP 422: refused {number}")
    box.mark_sent(ids["sent"])
    clock.advance(10)
    return ids


# -- dead_items -----------------------------------------------------------------------------------


def test_dead_items_lists_only_dead_rows_in_created_order_without_payload(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType, clock: Any
) -> None:
    ids = mixed(outbox, fake_cloud, clock)
    items = outbox.dead_items()
    assert [item.inspection_id for item in items] == ids["dead"]
    assert all(isinstance(item, DeadItem) for item in items)
    assert items[0].attempts == 1
    assert items[0].last_error == "HTTP 422: refused 0"
    assert items[0].created_at.utcoffset() is not None
    assert not hasattr(items[0], "payload")


def test_dead_items_ties_on_created_at_keep_insertion_order(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType
) -> None:
    ids = [put(outbox, fake_cloud) for _ in range(5)]  # same clock: same created_at
    for inspection_id in reversed(ids):
        outbox.mark_dead(inspection_id, "HTTP 422")
    assert [item.inspection_id for item in outbox.dead_items()] == ids


def test_dead_items_empty(outbox: SqliteOutbox) -> None:
    assert outbox.dead_items() == []


# -- requeue_dead ---------------------------------------------------------------------------------


def test_requeue_all_changes_only_dead_rows(
    outbox: SqliteOutbox, path: Path, fake_cloud: types.ModuleType, clock: Any
) -> None:
    ids = mixed(outbox, fake_cloud, clock)
    before = rows(path)
    assert outbox.requeue_dead() == 3
    after = rows(path)
    for inspection_id in ids["dead"]:
        old, new = before[str(inspection_id)], after[str(inspection_id)]
        assert new["status"] == "pending"
        assert new["attempts"] == 0
        assert new["next_attempt_at"] == format_timestamp(clock.now)
        assert new["last_error"] is None
        for column in ("payload", "created_at", "sent_at"):
            assert new[column] == old[column]
    for inspection_id in [*ids["pending"], *ids["sent"]]:
        assert after[str(inspection_id)] == before[str(inspection_id)]
    assert outbox.stats().dead == 0
    assert outbox.stats().pending == 5


def test_requeue_by_id_ignores_unknown_pending_and_sent(
    outbox: SqliteOutbox, path: Path, fake_cloud: types.ModuleType, clock: Any
) -> None:
    ids = mixed(outbox, fake_cloud, clock)
    before = rows(path)
    chosen = [ids["dead"][0], ids["pending"][0], ids["sent"][0], uuid4()]
    assert outbox.requeue_dead(chosen) == 1
    after = rows(path)
    changed = {key for key in before if before[key] != after[key]}
    assert changed == {str(ids["dead"][0])}
    assert after[str(ids["sent"][0])]["status"] == "sent"
    assert after[str(ids["sent"][0])]["sent_at"] == before[str(ids["sent"][0])]["sent_at"]


def test_requeue_with_empty_ids_or_without_dead_rows_returns_zero(
    outbox: SqliteOutbox, path: Path, fake_cloud: types.ModuleType, clock: Any
) -> None:
    assert outbox.requeue_dead() == 0
    ids = mixed(outbox, fake_cloud, clock)
    before = rows(path)
    assert outbox.requeue_dead([]) == 0
    assert outbox.requeue_dead([ids["sent"][0], ids["sent"][0]]) == 0
    assert rows(path) == before


def test_requeue_more_than_100_ids_in_chunks(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType
) -> None:
    ids = [put(outbox, fake_cloud) for _ in range(150)]
    for inspection_id in ids:
        outbox.mark_dead(inspection_id, "HTTP 422")
    statements: list[str] = []
    outbox._conn.set_trace_callback(statements.append)
    chosen = [*ids[:130], *(uuid4() for _ in range(80)), ids[0]]  # 211 ids, one repeated
    assert outbox.requeue_dead(chosen) == 130
    outbox._conn.set_trace_callback(None)
    updates = [s for s in statements if s.startswith("UPDATE outbox")]
    assert len(updates) == 3  # 100 + 100 + 11
    assert statements.count("COMMIT") == 1
    assert outbox.stats().dead == 20
    assert {item.inspection_id for item in outbox.dead_items()} == set(ids[130:])


class FailOnSecondUpdate:
    """Wraps the outbox connection; the second ``UPDATE`` raises (a failure mid-transaction)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.updates = 0

    def __enter__(self) -> FailOnSecondUpdate:
        self.conn.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self.conn.__exit__(*exc)

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        if sql.startswith("UPDATE outbox"):
            self.updates += 1
            if self.updates == 2:
                raise sqlite3.OperationalError("disk I/O error")
        return self.conn.execute(sql, parameters)


def test_requeue_rolls_back_every_chunk_on_failure(
    outbox: SqliteOutbox, path: Path, fake_cloud: types.ModuleType
) -> None:
    ids = [put(outbox, fake_cloud) for _ in range(120)]
    for inspection_id in ids:
        outbox.mark_dead(inspection_id, "HTTP 422")
    real = outbox._conn
    wrapper = FailOnSecondUpdate(real)
    outbox._conn = wrapper  # type: ignore[assignment]
    try:
        with pytest.raises(sqlite3.OperationalError):
            outbox.requeue_dead(ids)
    finally:
        outbox._conn = real
    assert wrapper.updates == 2
    assert outbox.stats().dead == 120
    assert all(row["status"] == "dead" for row in rows(path).values())


def test_requeued_item_is_returned_by_fetch_due(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType, clock: Any
) -> None:
    inspection_id = put(outbox, fake_cloud)
    outbox.mark_dead(inspection_id, "HTTP 422")
    assert outbox.fetch_due() == []
    clock.advance(3600)
    assert outbox.requeue_dead([inspection_id]) == 1
    due = outbox.fetch_due()
    assert [item.inspection_id for item in due] == [inspection_id]
    assert due[0].attempts == 0
    assert due[0].next_attempt_at == clock.now


# -- open_existing --------------------------------------------------------------------------------


def test_open_existing_never_creates_the_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite3"
    for read_only in (False, True):
        with pytest.raises(sqlite3.OperationalError):
            SqliteOutbox.open_existing(missing, read_only=read_only)
    assert list(tmp_path.iterdir()) == []


def test_open_existing_rejects_a_database_without_the_outbox_table(tmp_path: Path) -> None:
    other = tmp_path / "other.sqlite3"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE things (x)")
    conn.commit()
    conn.close()
    with pytest.raises(NotAnOutboxError):
        SqliteOutbox.open_existing(other)
    text = tmp_path / "text.txt"
    text.write_text("not a database " * 100)
    with pytest.raises(sqlite3.DatabaseError):
        SqliteOutbox.open_existing(text)


def test_open_existing_read_only_cannot_write(
    outbox: SqliteOutbox, path: Path, fake_cloud: types.ModuleType
) -> None:
    inspection_id = put(outbox, fake_cloud)
    outbox.mark_dead(inspection_id, "HTTP 422")
    reader = SqliteOutbox.open_existing(path, read_only=True)
    try:
        assert [item.inspection_id for item in reader.dead_items()] == [inspection_id]
        with pytest.raises(sqlite3.OperationalError):
            reader.requeue_dead()
        assert reader.stats().connectivity == "disabled"
    finally:
        reader.close()
    assert outbox.stats().dead == 1


def test_open_existing_with_spaces_and_uri_characters_in_the_path(
    tmp_path: Path, fake_cloud: types.ModuleType
) -> None:
    path = tmp_path / "pasta com espaço?#%" / "out box.sqlite3"
    box = SqliteOutbox(path)
    inspection_id = put(box, fake_cloud)
    box.mark_dead(inspection_id, "HTTP 422")
    box.close()
    other = SqliteOutbox.open_existing(path)
    try:
        assert other.requeue_dead() == 1
    finally:
        other.close()
    assert rows(path)[str(inspection_id)]["status"] == "pending"


# -- CLI ------------------------------------------------------------------------------------------


def dead_outbox(
    path: Path, fake_cloud: types.ModuleType, count: int, **overrides: Any
) -> list[UUID]:
    box = SqliteOutbox(path)
    try:
        ids = [put(box, fake_cloud, **overrides) for _ in range(count)]
        for inspection_id in ids:
            box.mark_dead(inspection_id, "HTTP 422: 2 validation errors")
    finally:
        box.close()
    return ids


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_lists_without_changing_anything(
    path: Path,
    fake_cloud: types.ModuleType,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lot_marker = "lot-" + secrets.token_hex(8)
    key_marker = "key-" + secrets.token_hex(16)
    monkeypatch.setenv("DEVICE_API_KEY", key_marker)
    ids = dead_outbox(path, fake_cloud, 2, lot_id=lot_marker)
    before_rows, before_bytes = rows(path), digest(path)
    caplog.set_level(logging.DEBUG)
    assert requeue.main(["--outbox-path", str(path)]) == 0
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert len(lines) == 3
    assert lines[-1] == f"2 {SUMMARY}"
    assert rows(path) == before_rows
    assert digest(path) == before_bytes
    reader = SqliteOutbox.open_existing(path, read_only=True)
    try:
        created = {item.inspection_id: item for item in reader.dead_items()}
    finally:
        reader.close()
    for line, inspection_id in zip(lines[:2], ids, strict=True):
        item = created[inspection_id]
        assert line == (
            f"{inspection_id} {format_timestamp(item.created_at)} attempts=0 "
            "HTTP 422: 2 validation errors"
        )
    for marker in (lot_marker, key_marker, "edge-01", "partqc-test-v1"):
        assert marker not in captured.out
        assert marker not in captured.err
        assert marker not in caplog.text


def test_cli_list_and_requeue_by_id(
    path: Path, fake_cloud: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = dead_outbox(path, fake_cloud, 3)
    unknown = uuid4()
    argv = ["--outbox-path", str(path), "--id", str(ids[1]), "--id", str(unknown)]
    assert requeue.main(argv) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(f"{ids[1]} ")
    assert lines[1] == f"1 {SUMMARY}"
    assert requeue.main([*argv, "--yes"]) == 0
    assert capsys.readouterr().out == "requeued 1 item(s)\n"
    statuses = {key: row["status"] for key, row in rows(path).items()}
    assert statuses == {str(ids[0]): "dead", str(ids[1]): "pending", str(ids[2]): "dead"}


def test_cli_requeue_all_and_zero(
    path: Path, fake_cloud: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    dead_outbox(path, fake_cloud, 2)
    assert requeue.main(["--outbox-path", str(path), "--yes"]) == 0
    assert capsys.readouterr().out == "requeued 2 item(s)\n"
    assert requeue.main(["--outbox-path", str(path), "--yes"]) == 0
    assert capsys.readouterr().out == "requeued 0 item(s)\n"
    assert requeue.main(["--outbox-path", str(path)]) == 0
    assert capsys.readouterr().out == f"0 {SUMMARY}\n"


def test_cli_shows_a_dash_without_error_and_hides_control_characters(
    path: Path, fake_cloud: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    box = SqliteOutbox(path)
    first, second = put(box, fake_cloud), put(box, fake_cloud)
    box.mark_dead(first, "HTTP 422: line\nforged 0000\x1b[2J‮end")
    box.close()
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE outbox SET status = 'dead', last_error = NULL WHERE inspection_id = ?",
        (str(second),),
    )
    conn.commit()
    conn.close()
    assert requeue.main(["--outbox-path", str(path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert lines[0].endswith("attempts=0 HTTP 422: line?forged 0000?[2J?end")
    assert lines[1].endswith("attempts=0 -")


@pytest.mark.parametrize("yes", [False, True])
def test_cli_missing_file_is_never_created(
    tmp_path: Path, yes: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "outbox.sqlite3"
    argv = ["--outbox-path", str(missing)] + (["--yes"] if yes else [])
    assert requeue.main(argv) == 2
    assert not missing.exists()
    assert list(tmp_path.iterdir()) == []
    assert capsys.readouterr().out == ""


def test_cli_rejects_a_directory_and_a_file_that_is_not_an_outbox(tmp_path: Path) -> None:
    assert requeue.main(["--outbox-path", str(tmp_path)]) == 2
    text = tmp_path / "notes.txt"
    text.write_text("not a database " * 100)
    before = digest(text)
    assert requeue.main(["--outbox-path", str(text), "--yes"]) == 2
    empty = tmp_path / "empty.sqlite3"
    empty.write_bytes(b"")
    assert requeue.main(["--outbox-path", str(empty), "--yes"]) == 2
    assert digest(text) == before
    assert empty.read_bytes() == b""


@pytest.mark.parametrize(
    "extra",
    [
        ["--id", "nao-e-uuid-{marker}"],
        ["--id=nao-e-uuid-{marker}"],
        ["--token={marker}"],
        ["{marker}"],
        ["--id"],
    ],
)
def test_cli_usage_errors_never_echo_values(
    path: Path,
    fake_cloud: types.ModuleType,
    extra: list[str],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    dead_outbox(path, fake_cloud, 1)
    marker = secrets.token_hex(12)
    caplog.set_level(logging.DEBUG)
    argv = ["--outbox-path", str(path), *(part.format(marker=marker) for part in extra)]
    assert requeue.main(argv) == 2
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err + caplog.text
    assert rows(path)[next(iter(rows(path)))]["status"] == "dead"


def test_cli_without_outbox_path_is_a_usage_error() -> None:
    assert requeue.main([]) == 2
    assert requeue.main(["--yes"]) == 2


def test_cli_sqlite_failure_exits_with_1(
    path: Path, fake_cloud: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    dead_outbox(path, fake_cloud, 1)

    def broken(self: SqliteOutbox, ids: Any = None) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(SqliteOutbox, "requeue_dead", broken)
    assert requeue.main(["--outbox-path", str(path), "--yes"]) == 1


def test_cli_waits_for_a_writer_lock_up_to_the_timeout(
    path: Path, fake_cloud: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    dead_outbox(path, fake_cloud, 1)
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    original = SqliteOutbox.open_existing.__func__  # type: ignore[attr-defined]

    def quick(cls: type, p: Path, **kwargs: Any) -> SqliteOutbox:
        kwargs["timeout_s"] = 0.2
        return original(cls, p, **kwargs)

    monkeypatch.setattr(SqliteOutbox, "open_existing", classmethod(quick))
    try:
        assert requeue.main(["--outbox-path", str(path), "--yes"]) == 1
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert requeue.main(["--outbox-path", str(path), "--yes"]) == 0


def test_cli_opens_no_socket(
    path: Path, fake_cloud: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    dead_outbox(path, fake_cloud, 2)
    calls: list[Any] = []
    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def spy_connect(self: socket.socket, *args: Any) -> Any:
        calls.append(args)
        return real_connect(self, *args)

    def spy_getaddrinfo(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return real_getaddrinfo(*args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", spy_connect)
    monkeypatch.setattr(socket, "getaddrinfo", spy_getaddrinfo)
    assert requeue.main(["--outbox-path", str(path)]) == 0
    assert requeue.main(["--outbox-path", str(path), "--yes"]) == 0
    assert calls == []


def test_cli_in_a_subprocess_while_the_outbox_is_open(
    path: Path, fake_cloud: types.ModuleType
) -> None:
    box = SqliteOutbox(path)
    try:
        ids = [put(box, fake_cloud) for _ in range(2)]
        for inspection_id in ids:
            box.mark_dead(inspection_id, "HTTP 422")
        assert box.stats().pending == 0
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(EDGE_SRC), str(CONTRACTS_SRC)])
        result = subprocess.run(
            [sys.executable, "-m", "qc_edge.requeue", "--outbox-path", str(path), "--yes"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "requeued 2 item(s)\n"
        assert box.stats().pending == 2
        assert box.stats().dead == 0
        assert len(box.fetch_due()) == 2
    finally:
        box.close()
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_requeue_then_publish_loop_sends_once_each(
    path: Path, fake_cloud: types.ModuleType, clock: Any
) -> None:
    refuse = {"on": True}

    def fail(request: httpx.Request, items: list[dict[str, Any]]) -> httpx.Response | None:
        if refuse["on"]:
            return httpx.Response(422, json={"detail": [{"msg": "x"}] * len(items)})
        return None

    cloud = fake_cloud.FakeCloud(fail=fail)
    box = SqliteOutbox(path, clock=clock)
    publisher = HttpPublisher(fake_cloud.BASE_URL, secrets.token_hex(16), transport=cloud.transport)
    loop = PublishLoop(box, publisher, ConnectivityState(), clock=clock, rng=random.Random(0))
    try:
        ids = {put(box, fake_cloud) for _ in range(4)}
        for _ in range(10):
            loop.run_once()
            clock.advance(61)
        assert box.stats().dead == 4
        refuse["on"] = False
        assert requeue.main(["--outbox-path", str(path), "--yes"]) == 0
        for _ in range(10):
            if box.stats().pending == 0:
                break
            loop.run_once()
            clock.advance(61)
        assert box.stats().pending == 0
        assert box.stats().dead == 0
        assert set(cloud.stored) == ids
        assert len(cloud.writes) == 4
        assert {row["status"] for row in rows(path).values()} == {"sent"}
    finally:
        box.close()
