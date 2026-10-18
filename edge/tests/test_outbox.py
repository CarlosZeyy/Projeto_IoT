"""SQLite outbox (SPEC-009 section 4.1): schema, idempotency, order, retries, durability."""

from __future__ import annotations

import os
import signal
import sqlite3
import stat
import subprocess
import sys
import threading
import types
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from qc_contracts import InspectionCreate
from qc_edge.outbox import (
    MAX_LAST_ERROR,
    OutboxItem,
    SqliteOutbox,
    format_timestamp,
    parse_timestamp,
    utc_now,
)
from qc_edge.publish_loop import ConnectivityState
from qc_edge.sink import SinkError, SinkStats

EDGE_SRC = Path(__file__).resolve().parents[1] / "src"
CONTRACTS_SRC = Path(__file__).resolve().parents[2] / "packages" / "contracts" / "src"


@pytest.fixture
def clock(fake_cloud: types.ModuleType) -> Any:
    return fake_cloud.FakeClock()


@pytest.fixture
def outbox(tmp_path: Path, clock: Any) -> Iterator[SqliteOutbox]:
    box = SqliteOutbox(tmp_path / "data" / "outbox.sqlite3", clock=clock)
    yield box
    box.close()


def rows(path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM outbox ORDER BY rowid")]
    finally:
        conn.close()


def test_schema_and_pragmas(outbox: SqliteOutbox) -> None:
    conn = sqlite3.connect(outbox.path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        columns = [row[1] for row in conn.execute("PRAGMA table_info(outbox)")]
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(outbox)")}
    finally:
        conn.close()
    assert columns == [
        "inspection_id",
        "payload",
        "created_at",
        "attempts",
        "next_attempt_at",
        "sent_at",
        "status",
        "last_error",
    ]
    assert "outbox_due" in indexes
    # synchronous is a per-connection setting: FULL (2) on the outbox's own connection.
    assert outbox._conn.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_status_check_constraint(outbox: SqliteOutbox) -> None:
    conn = sqlite3.connect(outbox.path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO outbox (inspection_id, payload, created_at, next_attempt_at, status) "
                "VALUES ('x', '{}', 'a', 'a', 'lost')"
            )
    finally:
        conn.close()


def test_file_and_new_parent_are_private(tmp_path: Path) -> None:
    path = tmp_path / "new" / "outbox.sqlite3"
    box = SqliteOutbox(path)
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    finally:
        box.close()


def test_reopening_an_existing_file_keeps_the_rows(
    tmp_path: Path, fake_cloud: types.ModuleType
) -> None:
    path = tmp_path / "outbox.sqlite3"
    first = SqliteOutbox(path)
    first.put(fake_cloud.make_inspection())
    first.close()
    second = SqliteOutbox(path)
    try:
        assert second.stats().pending == 1
    finally:
        second.close()


def test_put_three_times_keeps_one_pending_row(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType, clock: Any
) -> None:
    inspection = fake_cloud.make_inspection()
    for _ in range(3):
        outbox.put(inspection)
    assert outbox.stats() == SinkStats(
        pending=1, dead=0, last_success_at=None, connectivity="disabled"
    )
    (row,) = rows(outbox.path)
    assert row["inspection_id"] == str(inspection.inspection_id)
    assert row["status"] == "pending"
    assert row["attempts"] == 0
    assert row["sent_at"] is None
    assert row["last_error"] is None
    assert row["created_at"] == row["next_attempt_at"] == format_timestamp(clock.now)
    assert row["payload"] == inspection.model_dump_json()
    assert InspectionCreate.model_validate_json(row["payload"]) == inspection


def test_put_never_changes_a_sent_row(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType, clock: Any
) -> None:
    inspection = fake_cloud.make_inspection()
    outbox.put(inspection)
    outbox.mark_sent([inspection.inspection_id])
    before = rows(outbox.path)
    clock.advance(30)
    outbox.put(inspection)
    assert rows(outbox.path) == before
    assert before[0]["status"] == "sent"


def test_timestamps_are_fixed_width_utc() -> None:
    minus3 = timezone(timedelta(hours=-3))
    value = datetime(2026, 11, 30, 9, 0, tzinfo=minus3)
    assert format_timestamp(value) == "2026-11-30T12:00:00.000000+00:00"
    assert parse_timestamp(format_timestamp(value)) == value
    assert parse_timestamp(format_timestamp(value)).tzinfo == UTC
    with pytest.raises(ValueError, match="timezone-aware"):
        format_timestamp(datetime(2026, 11, 30, 12, 0))
    assert utc_now().tzinfo == UTC


def test_a_clock_in_another_zone_is_stored_in_utc(
    tmp_path: Path, fake_cloud: types.ModuleType
) -> None:
    plus2 = timezone(timedelta(hours=2))
    box = SqliteOutbox(
        tmp_path / "o.sqlite3", clock=lambda: datetime(2026, 1, 1, 2, 0, 0, 5, tzinfo=plus2)
    )
    try:
        box.put(fake_cloud.make_inspection())
        assert rows(box.path)[0]["created_at"] == "2026-01-01T00:00:00.000005+00:00"
    finally:
        box.close()


def test_fetch_due_order_limit_and_filters(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType, clock: Any
) -> None:
    same_time = [fake_cloud.make_inspection() for _ in range(3)]
    for inspection in same_time:
        outbox.put(inspection)  # same created_at: insertion order
    clock.advance(1)
    later = fake_cloud.make_inspection()
    outbox.put(later)
    clock.advance(1)
    sent, dead, waiting = (fake_cloud.make_inspection() for _ in range(3))
    for inspection in (sent, dead, waiting):
        outbox.put(inspection)
    outbox.mark_sent([sent.inspection_id])
    outbox.mark_dead(dead.inspection_id, "HTTP 422")
    outbox.mark_retry([waiting.inspection_id], "HTTP 503", lambda n: 10.0)

    due = outbox.fetch_due()
    expected = [i.inspection_id for i in same_time] + [later.inspection_id]
    assert [item.inspection_id for item in due] == expected
    assert [item.inspection_id for item in outbox.fetch_due(2)] == expected[:2]
    assert outbox.fetch_due(0) == []
    first = due[0]
    assert isinstance(first, OutboxItem)
    assert first.attempts == 0
    assert first.created_at == first.next_attempt_at
    assert first.created_at.tzinfo == UTC
    assert first.to_inspection() == same_time[0]

    clock.advance(10)
    assert waiting.inspection_id in {item.inspection_id for item in outbox.fetch_due()}


def test_fetch_due_respects_next_attempt_at_exactly(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType, clock: Any
) -> None:
    inspection = fake_cloud.make_inspection()
    outbox.put(inspection)
    outbox.mark_retry([inspection.inspection_id], "boom", lambda n: 1.0)
    clock.advance(0.999999)
    assert outbox.fetch_due() == []
    clock.advance(0.000001)
    assert [item.inspection_id for item in outbox.fetch_due()] == [inspection.inspection_id]


def test_mark_sent_sets_sent_at(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType, clock: Any
) -> None:
    inspections = [fake_cloud.make_inspection() for _ in range(3)]
    for inspection in inspections:
        outbox.put(inspection)
    clock.advance(5)
    outbox.mark_sent([inspections[0].inspection_id, inspections[2].inspection_id])
    outbox.mark_sent([])
    by_id = {row["inspection_id"]: row for row in rows(outbox.path)}
    for inspection, status in zip(inspections, ("sent", "pending", "sent"), strict=True):
        row = by_id[str(inspection.inspection_id)]
        assert row["status"] == status
        assert (row["sent_at"] is not None) == (status == "sent")
    assert by_id[str(inspections[0].inspection_id)]["sent_at"] == format_timestamp(clock.now)
    assert outbox.stats().pending == 1


def test_mark_retry_uses_attempts_before_the_increment(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType, clock: Any
) -> None:
    inspection = fake_cloud.make_inspection()
    outbox.put(inspection)
    seen: list[int] = []

    def delay(attempts: int) -> float:
        seen.append(attempts)
        return 2.5

    for _ in range(3):
        outbox.mark_retry([inspection.inspection_id], "HTTP 503", delay)
    assert seen == [0, 1, 2]
    (row,) = rows(outbox.path)
    assert row["attempts"] == 3
    assert row["status"] == "pending"
    assert row["last_error"] == "HTTP 503"
    assert row["next_attempt_at"] == format_timestamp(clock.now + timedelta(seconds=2.5))


def test_mark_retry_cuts_the_error_and_skips_other_rows(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType
) -> None:
    pending, sent = fake_cloud.make_inspection(), fake_cloud.make_inspection()
    outbox.put(pending)
    outbox.put(sent)
    outbox.mark_sent([sent.inspection_id])
    outbox.mark_retry([pending.inspection_id, sent.inspection_id, uuid4()], "x" * 900, lambda n: 1)
    outbox.mark_retry([], "ignored", lambda n: 1)
    by_id = {row["inspection_id"]: row for row in rows(outbox.path)}
    assert by_id[str(pending.inspection_id)]["last_error"] == "x" * MAX_LAST_ERROR
    assert by_id[str(sent.inspection_id)]["attempts"] == 0
    assert by_id[str(sent.inspection_id)]["last_error"] is None


def test_mark_dead_is_final(outbox: SqliteOutbox, fake_cloud: types.ModuleType) -> None:
    inspection = fake_cloud.make_inspection()
    outbox.put(inspection)
    outbox.mark_dead(inspection.inspection_id, "HTTP 422: " + "y" * 800)
    (row,) = rows(outbox.path)
    assert row["status"] == "dead"
    assert len(row["last_error"]) == MAX_LAST_ERROR
    assert outbox.fetch_due() == []
    outbox.mark_sent([inspection.inspection_id])  # only pending rows become sent
    assert rows(outbox.path)[0]["status"] == "dead"
    assert outbox.stats().dead == 1
    assert outbox.stats().pending == 0


def test_stats_reads_the_shared_connectivity(tmp_path: Path, fake_cloud: types.ModuleType) -> None:
    at = datetime(2026, 11, 30, 12, 0, tzinfo=UTC)
    state = ConnectivityState("online", at)
    box = SqliteOutbox(tmp_path / "o.sqlite3", connectivity=state)
    try:
        box.put(fake_cloud.make_inspection())
        assert box.stats() == SinkStats(
            pending=1, dead=0, last_success_at=at, connectivity="online"
        )
        state.connectivity = "auth_error"
        assert box.stats().connectivity == "auth_error"
    finally:
        box.close()


def test_sqlite_failures_are_sink_errors(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType
) -> None:
    outbox.close()
    outbox.close()  # idempotent
    with pytest.raises(SinkError, match="outbox write failed"):
        outbox.put(fake_cloud.make_inspection())
    with pytest.raises(SinkError, match="outbox read failed"):
        outbox.stats()


def test_a_read_only_database_is_a_sink_error(tmp_path: Path, fake_cloud: types.ModuleType) -> None:
    path = tmp_path / "o.sqlite3"
    SqliteOutbox(path).close()
    box = SqliteOutbox(path)
    try:
        box._conn.execute("PRAGMA query_only = ON")
        with pytest.raises(SinkError) as excinfo:
            box.put(fake_cloud.make_inspection())
        assert "payload" not in str(excinfo.value)
    finally:
        box.close()


def test_an_unopenable_path_raises(tmp_path: Path) -> None:
    directory = tmp_path / "a-directory"
    directory.mkdir()
    with pytest.raises((sqlite3.Error, OSError)):
        SqliteOutbox(directory)


def test_concurrent_puts_and_publication(
    outbox: SqliteOutbox, fake_cloud: types.ModuleType
) -> None:
    errors: list[BaseException] = []
    put_ids: list[UUID] = []
    lock = threading.Lock()
    done = threading.Event()

    def producer() -> None:
        try:
            for _ in range(50):
                inspection = fake_cloud.make_inspection()
                outbox.put(inspection)
                with lock:
                    put_ids.append(inspection.inspection_id)
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    def consumer() -> None:
        try:
            while not done.is_set():
                due = outbox.fetch_due(10)
                outbox.mark_sent([item.inspection_id for item in due])
                outbox.stats()
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=producer) for _ in range(4)]
    reader = threading.Thread(target=consumer)
    reader.start()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    done.set()
    reader.join()
    assert errors == []
    assert len(rows(outbox.path)) == 200
    assert {UUID(row["inspection_id"]) for row in rows(outbox.path)} == set(put_ids)


CHILD = """
import os, signal, sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from qc_contracts import InspectionCreate
from qc_edge.outbox import SqliteOutbox

box = SqliteOutbox(Path(sys.argv[1]))
for i in range(20):
    box.put(InspectionCreate(
        inspection_id=uuid4(), device_id="edge-01", lot_id="L-001",
        inspected_at=datetime.now(UTC), object_type="screw", grade="good", grade_score=1.0,
        type_confidence=0.9, grade_confidence=0.8, needs_review=False,
        model_version="partqc-test-v1", model_sha256="a" * 64, latency_ms=1, source="live",
    ))
os.kill(os.getpid(), signal.SIGKILL)
"""


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="POSIX only")
def test_committed_puts_survive_sigkill(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite3"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(EDGE_SRC), str(CONTRACTS_SRC)])
    result = subprocess.run(
        [sys.executable, "-c", CHILD, str(path)], env=env, timeout=60, check=False
    )
    assert result.returncode == -signal.SIGKILL
    box = SqliteOutbox(path)
    try:
        assert box.stats().pending == 20
        assert len(box.fetch_due()) == 20
    finally:
        box.close()
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
