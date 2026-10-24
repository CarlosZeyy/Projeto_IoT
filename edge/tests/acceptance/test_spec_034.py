"""Acceptance tests for SPEC-034 (qc-edge: requeue of ``dead`` outbox items).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One ``test_caNN_*`` per CA. Tests named ``test_extra_*`` are exploratory edge
cases around the SPEC (security tag): files that are not an outbox, symbolic links, permissions,
a concurrent writer and a running publisher, control and bidi characters in ``last_error``,
invalid or huge ids, no file creation, no write without ``--yes`` and the requeued payload being
revalidated by the current contract.

Rules followed (``reviews/checklist.md`` and ``docs/architecture.md`` section 10):

* the only boundaries replaced are the ones the SPEC names: the cloud (``httpx.MockTransport``
  with a fake cloud that implements the SPEC-004 idempotency), the clock, the RNG and the socket
  spies of CA-08; SQLite and the file system are real, always under ``tmp_path``;
* every key and marker is generated at run time (``secrets``), never a credential literal;
* no test runs the test suite in a subprocess: CA-07 (and a few extras) run
  ``python -m qc_edge.requeue`` only.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import random
import re
import secrets
import socket
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

import qc_edge.requeue
from qc_contracts import Grade, InspectionCreate, ObjectType, Source
from qc_edge.outbox import DeadItem, SqliteOutbox
from qc_edge.publish_loop import ConnectivityState, PublishLoop
from qc_edge.publisher import HttpPublisher

pytestmark = pytest.mark.acceptance

EDGE_ROOT = Path(__file__).resolve().parents[2]  # edge/
ROOT = EDGE_ROOT.parent  # repository root

BASE_URL = "https://cloud.test"
BATCH_PATH = "/api/v1/inspections/batch"
HEALTH_PATH = "/api/v1/health"
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
ISO_FIXED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$")
SUMMARY = re.compile(r"^(\d+) dead item\(s\); run again with --yes to requeue$")
REQUEUED = re.compile(r"^requeued (\d+) item\(s\)$")
REJECT_ERROR = "HTTP 422: Value cannot be stored"
BAD_CATEGORIES = {"Cc", "Cf", "Cs", "Zl", "Zp"}

OUTBOX_COLUMNS = [
    "inspection_id",
    "payload",
    "created_at",
    "attempts",
    "next_attempt_at",
    "sent_at",
    "status",
    "last_error",
]


def new_marker() -> str:
    return "mk-" + secrets.token_hex(12)


def new_key() -> str:
    """A device key generated at run time (never a literal)."""
    return "acc_" + secrets.token_urlsafe(24)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


# =========================================================================== domain helpers


def inspection(*, lot_id: str = "L-034", device_id: str = "edge-01") -> InspectionCreate:
    return InspectionCreate(
        inspection_id=uuid.uuid4(),
        device_id=device_id,
        lot_id=lot_id,
        inspected_at=T0,
        object_type=ObjectType.SCREW,
        grade=Grade.GOOD,
        grade_score=1.1,
        type_confidence=0.9,
        grade_confidence=0.8,
        needs_review=False,
        model_version="partqc-mnv3-v1",
        model_sha256=hashlib.sha256(b"acceptance-model-034").hexdigest(),
        latency_ms=42,
        source=Source.LIVE,
    )


class ManualClock:
    """The fake clock of the SPEC (always UTC)."""

    def __init__(self, start: datetime = T0) -> None:
        self.now = start
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self.now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.now += timedelta(seconds=seconds)

    def set(self, value: datetime) -> None:
        with self._lock:
            self.now = value


class FakeCloud:
    """Fake cloud with the SPEC-004 idempotency: a dict by ``inspection_id``.

    ``reject_all`` answers 422 to any batch; ``reject_ids`` answers 422 to a batch that contains
    one of them (nothing stored), like the real API (single transaction).
    """

    def __init__(self) -> None:
        self.stored: dict[str, dict[str, Any]] = {}
        self.writes: list[str] = []
        self.batches: list[list[str]] = []
        self.bodies: list[bytes] = []
        self.reject_all = False
        self.reject_ids: set[str] = set()
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            body = request.read()
            self.bodies.append(body)
            if request.url.path == HEALTH_PATH and request.method == "GET":
                return httpx.Response(200, json={"status": "ok", "db": "ok"})
            if request.url.path == BATCH_PATH and request.method == "POST":
                items = json.loads(body)["items"]
                ids = [item["inspection_id"] for item in items]
                self.batches.append(ids)
                if self.reject_all or any(i in self.reject_ids for i in ids):
                    return httpx.Response(422, json={"detail": "Value cannot be stored"})
                results = []
                for item in items:
                    iid = item["inspection_id"]
                    if iid in self.stored:
                        results.append({"inspection_id": iid, "status": "duplicate"})
                    else:
                        self.stored[iid] = item
                        self.writes.append(iid)
                        results.append({"inspection_id": iid, "status": "created"})
                return httpx.Response(200, json={"results": results})
            return httpx.Response(404, json={"detail": "Not Found"})

    def sent_ids(self) -> list[str]:
        with self._lock:
            return [i for batch in self.batches for i in batch]


@dataclasses.dataclass
class Rig:
    path: Path
    clock: ManualClock
    connectivity: ConnectivityState
    outbox: SqliteOutbox
    cloud: FakeCloud
    loop: PublishLoop

    def drain(self, *, step_s: float = 2.0, max_cycles: int = 2000) -> int:
        cycles = 0
        while self.outbox.stats().pending > 0:
            assert cycles < max_cycles, "outbox did not drain"
            self.loop.run_once()
            self.clock.advance(step_s)
            cycles += 1
        return cycles


def make_rig(tmp_path: Path, *, start: datetime = T0, name: str = "outbox.sqlite3") -> Rig:
    path = tmp_path / name
    clock = ManualClock(start)
    connectivity = ConnectivityState()
    outbox = SqliteOutbox(path, clock=clock, connectivity=connectivity)
    cloud = FakeCloud()
    publisher = HttpPublisher(BASE_URL, new_key(), transport=httpx.MockTransport(cloud))
    loop = PublishLoop(outbox, publisher, connectivity, clock=clock, rng=random.Random(0))
    return Rig(path, clock, connectivity, outbox, cloud, loop)


def read_rows(path: Path) -> dict[str, dict[str, Any]]:
    con = sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM outbox")
        return {row["inspection_id"]: dict(row) for row in cur.fetchall()}
    finally:
        con.close()


def sql(path: Path, statement: str, params: Sequence[Any] = ()) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute(statement, params)
        con.commit()
    finally:
        con.close()


@dataclasses.dataclass
class Mixed:
    """3 ``dead``, 2 ``pending`` (one of them after a retry) and 1 ``sent``."""

    dead: list[InspectionCreate]
    pending: list[InspectionCreate]
    sent: InspectionCreate


def build_mixed(outbox: SqliteOutbox, clock: ManualClock) -> Mixed:
    """Built only with ``put`` and the ``mark_*`` of SPEC-009."""
    items = []
    for _ in range(6):
        item = inspection()
        outbox.put(item)
        items.append(item)
        clock.advance(1.5)
    dead, pending, sent = items[:3], items[3:5], items[5]
    # one dead row with attempts > 0 (retried first, then rejected)
    outbox.mark_retry([dead[0].inspection_id], "HTTP 503", lambda n: 7.0)
    clock.advance(3)
    for item in dead:
        outbox.mark_dead(item.inspection_id, REJECT_ERROR)
        clock.advance(0.5)
    outbox.mark_retry([pending[1].inspection_id], "HTTP 503", lambda n: 30.0)
    clock.advance(2)
    outbox.mark_sent([sent.inspection_id])
    clock.advance(2)
    return Mixed(dead, pending, sent)


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    r = make_rig(tmp_path)
    try:
        yield r
    finally:
        r.outbox.close()


# =========================================================================== CLI helpers


def run_cli(argv: list[str]) -> int:
    """Call ``qc_edge.requeue.main`` in-process; ``SystemExit`` is folded into the code."""
    try:
        value = qc_edge.requeue.main(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    assert isinstance(value, int), f"main must return int, got {value!r}"
    return value


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Every visible part of every record: message, raw msg, args and formatted exception."""
    formatter = logging.Formatter()
    parts = [caplog.text]
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(str(record.msg))
        parts.append(repr(record.args))
        if record.exc_info:
            parts.append(formatter.formatException(record.exc_info))
        if record.exc_text:
            parts.append(record.exc_text)
    return "\n".join(parts)


def subprocess_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in {"DEVICE_API_KEY", "CLOUD_API_URL"}}
    env.update(extra)
    return env


def run_module(args: list[str], *, timeout: float = 60, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "qc_edge.requeue", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=subprocess_env(**env),
        cwd=str(EDGE_ROOT),
        check=False,
    )


def file_state(path: Path) -> tuple[bytes, dict[str, dict[str, Any]]]:
    return path.read_bytes(), read_rows(path)


def dir_listing(directory: Path) -> set[str]:
    return {p.name for p in directory.iterdir()}


def make_dead_outbox(
    tmp_path: Path, n: int = 2, *, lot_id: str = "L-034", name: str = "outbox.sqlite3"
) -> tuple[Path, list[InspectionCreate]]:
    """A closed outbox file with ``n`` dead items (built through the public API)."""
    path = tmp_path / name
    clock = ManualClock()
    outbox = SqliteOutbox(path, clock=clock, connectivity=ConnectivityState())
    items = []
    try:
        for _ in range(n):
            item = inspection(lot_id=lot_id)
            outbox.put(item)
            items.append(item)
            clock.advance(1)
        for item in items:
            outbox.mark_dead(item.inspection_id, REJECT_ERROR)
    finally:
        outbox.close()
    return path, items


# =========================================================================== CA-01


def test_ca01_requeue_all_changes_only_dead_rows(rig: Rig) -> None:
    mixed = build_mixed(rig.outbox, rig.clock)
    before = read_rows(rig.path)
    dead_ids = {str(i.inspection_id) for i in mixed.dead}
    assert {r["status"] for k, r in before.items() if k in dead_ids} == {"dead"}
    assert before[str(mixed.dead[0].inspection_id)]["attempts"] > 0  # the reset is visible

    t = rig.clock() + timedelta(minutes=17, microseconds=123)
    rig.clock.set(t)
    assert rig.outbox.requeue_dead() == 3

    after = read_rows(rig.path)
    assert set(after) == set(before)
    for iid, row in after.items():
        old = before[iid]
        if iid in dead_ids:
            assert row["status"] == "pending"
            assert row["attempts"] == 0
            assert ISO_FIXED.fullmatch(row["next_attempt_at"]), row["next_attempt_at"]
            assert row["next_attempt_at"] == iso(t)
            assert datetime.fromisoformat(row["next_attempt_at"]) == t
            assert row["last_error"] is None
            for col in ("inspection_id", "payload", "created_at", "sent_at"):
                assert row[col] == old[col], col
        else:
            assert row == old, f"row {iid} changed"
    assert rig.outbox.stats().dead == 0
    assert rig.outbox.stats().pending == 5


# =========================================================================== CA-02


def test_ca02_requeue_by_id_only_touches_dead_ids(rig: Rig) -> None:
    mixed = build_mixed(rig.outbox, rig.clock)
    before = read_rows(rig.path)
    t = rig.clock() + timedelta(seconds=40)
    rig.clock.set(t)

    ids = [
        mixed.dead[0].inspection_id,
        mixed.pending[0].inspection_id,
        mixed.sent.inspection_id,
        uuid.uuid4(),
    ]
    assert rig.outbox.requeue_dead(ids) == 1

    after = read_rows(rig.path)
    target = str(mixed.dead[0].inspection_id)
    for iid, row in after.items():
        if iid == target:
            assert row["status"] == "pending"
            assert row["attempts"] == 0
            assert row["next_attempt_at"] == iso(t)
            assert row["last_error"] is None
            assert row["payload"] == before[iid]["payload"]
        else:
            assert row == before[iid], f"row {iid} changed"
    sent_row = after[str(mixed.sent.inspection_id)]
    assert sent_row["status"] == "sent"
    assert sent_row["sent_at"] is not None
    assert sent_row["sent_at"] == before[str(mixed.sent.inspection_id)]["sent_at"]


# =========================================================================== CA-03


def test_ca03_requeued_items_are_sent_once_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEVICE_API_KEY", raising=False)
    # The CLI opens its own outbox with the real clock; the rig clock starts at the real time so
    # that ``next_attempt_at = now`` written by the CLI is due for the publish loop.
    r = make_rig(tmp_path, start=datetime.now(UTC) - timedelta(minutes=10))
    try:
        items = []
        for _ in range(4):
            item = inspection()
            r.outbox.put(item)
            items.append(item)
            r.clock.advance(0.25)
        r.cloud.reject_all = True
        r.drain()
        rows = read_rows(r.path)
        assert {row["status"] for row in rows.values()} == {"dead"}
        assert len(rows) == 4
        assert r.cloud.stored == {}

        r.cloud.reject_all = False
        assert run_cli(["--outbox-path", str(r.path), "--yes"]) == 0
        r.clock.set(datetime.now(UTC) + timedelta(seconds=1))
        r.drain()

        rows = read_rows(r.path)
        assert {row["status"] for row in rows.values()} == {"sent"}
        original = {str(i.inspection_id) for i in items}
        assert set(r.cloud.stored) == original
        assert len(r.cloud.writes) == 4
        assert len(set(r.cloud.writes)) == 4  # 0 duplicated writes
        assert r.outbox.stats().dead == 0
        assert r.outbox.stats().pending == 0
        # the payload that reached the cloud is the stored one
        for item in items:
            stored = r.cloud.stored[str(item.inspection_id)]
            assert InspectionCreate.model_validate(stored) == item
    finally:
        r.outbox.close()


# =========================================================================== CA-04


def test_ca04_item_still_refused_goes_back_to_dead_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEVICE_API_KEY", raising=False)
    r = make_rig(tmp_path, start=datetime.now(UTC) - timedelta(minutes=10))
    try:
        item = inspection()
        r.outbox.put(item)
        iid = str(item.inspection_id)
        r.cloud.reject_ids.add(iid)
        r.drain()
        assert read_rows(r.path)[iid]["status"] == "dead"

        assert run_cli(["--outbox-path", str(r.path), "--yes"]) == 0
        assert read_rows(r.path)[iid]["status"] == "pending"
        r.clock.set(datetime.now(UTC) + timedelta(seconds=1))
        sent_before = r.cloud.sent_ids().count(iid)
        r.drain()
        assert r.cloud.sent_ids().count(iid) > sent_before  # it was really sent again

        row = read_rows(r.path)[iid]
        assert row["status"] == "dead"
        assert row["last_error"]
        assert row["last_error"].strip()

        count = r.cloud.sent_ids().count(iid)
        for _ in range(5):
            r.clock.advance(120)
            r.loop.run_once()
        assert r.cloud.sent_ids().count(iid) == count
        assert read_rows(r.path)[iid]["status"] == "dead"
        assert r.cloud.stored == {}
    finally:
        r.outbox.close()


# =========================================================================== CA-05


def test_ca05_listing_hides_secrets_and_changes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    lot_marker = new_marker()
    key_marker = new_marker()
    path, items = make_dead_outbox(tmp_path, 2, lot_id=lot_marker)
    monkeypatch.setenv("DEVICE_API_KEY", key_marker)
    before = file_state(path)
    caplog.set_level(logging.DEBUG)

    code = run_cli(["--outbox-path", str(path)])
    out, err = capsys.readouterr()

    assert code == 0
    lines = out.splitlines()
    assert len(lines) == 3, out
    assert lines[2] == "2 dead item(s); run again with --yes to requeue"
    ids = {str(i.inspection_id) for i in items}
    seen = set()
    for line in lines[:2]:
        first = line.split(" ", 1)[0]
        assert first in ids
        seen.add(first)
        assert line.startswith(first)
    assert seen == ids
    logs = log_text(caplog)
    for marker in (lot_marker, key_marker):
        assert marker not in out
        assert marker not in err
        assert marker not in logs
    # other payload fields never show up either
    assert "edge-01" not in out
    assert "0.9" not in out and "0.8" not in out
    assert file_state(path) == before


def test_ca05_line_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The item line format of section 4.2, ordered by ``created_at``."""
    monkeypatch.delenv("DEVICE_API_KEY", raising=False)
    path, items = make_dead_outbox(tmp_path, 3)
    assert run_cli(["--outbox-path", str(path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 4
    rows = read_rows(path)
    for item, line in zip(items, lines[:3], strict=True):
        iid = str(item.inspection_id)
        m = re.fullmatch(r"(\S+) (\S+) attempts=(\d+) (.+)", line)
        assert m, line
        assert m.group(1) == iid
        created = datetime.fromisoformat(m.group(2).replace("Z", "+00:00"))
        assert created.utcoffset() == timedelta(0)
        assert created == datetime.fromisoformat(rows[iid]["created_at"])
        assert int(m.group(3)) == rows[iid]["attempts"]
        assert m.group(4) == REJECT_ERROR
    assert SUMMARY.fullmatch(lines[3]).group(1) == "3"


# =========================================================================== CA-06


@pytest.mark.parametrize("yes", [False, True])
def test_ca06_missing_file_is_not_created(
    tmp_path: Path,
    yes: bool,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    folder = tmp_path / "data"
    folder.mkdir()
    target = folder / "outbox.sqlite3"
    argv = ["--outbox-path", str(target)] + (["--yes"] if yes else [])
    assert run_cli(argv) == 2
    assert not target.exists()
    assert dir_listing(folder) == set()  # no -wal, -shm or journal either


@pytest.mark.parametrize(
    "build",
    [
        lambda m: ["--id", f"nao-e-uuid-{m}"],
        lambda m: [f"--id=nao-e-uuid-{m}"],
        lambda m: [f"--token={m}"],
        lambda m: ["--token", m],
    ],
    ids=["id-separate", "id-equals", "token-equals", "token-separate"],
)
@pytest.mark.parametrize("yes", [False, True])
def test_ca06_bad_arguments_are_not_echoed(
    tmp_path: Path,
    build: Callable[[str], list[str]],
    yes: bool,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    path, _ = make_dead_outbox(tmp_path, 1)
    before = file_state(path)
    marker = new_marker()
    caplog.set_level(logging.DEBUG)
    argv = ["--outbox-path", str(path), *build(marker)] + (["--yes"] if yes else [])
    assert run_cli(argv) == 2
    out, err = capsys.readouterr()
    logs = log_text(caplog)
    assert marker not in out
    assert marker not in err
    assert marker not in logs
    assert file_state(path) == before


# =========================================================================== CA-07


def test_ca07_subprocess_requeue_while_outbox_is_open(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite3"
    clock = ManualClock()
    outbox = SqliteOutbox(path, clock=clock, connectivity=ConnectivityState())
    try:
        items = [inspection(), inspection()]
        for item in items:
            outbox.put(item)
            clock.advance(1)
        for item in items:
            outbox.mark_dead(item.inspection_id, REJECT_ERROR)
        assert outbox.stats().pending == 0
        assert outbox.stats().dead == 2

        proc = run_module(["--outbox-path", str(path), "--yes"])
        assert proc.returncode == 0, proc.stderr
        assert REQUEUED.fullmatch(proc.stdout.strip()).group(1) == "2"

        assert outbox.stats().pending == 2
        assert outbox.stats().dead == 0
        con = sqlite3.connect(path)
        try:
            assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            con.close()
    finally:
        outbox.close()


# =========================================================================== CA-08


class SocketSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []


@pytest.fixture
def socket_spy(monkeypatch: pytest.MonkeyPatch) -> SocketSpy:
    spy = SocketSpy()
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def connect(self: socket.socket, *args: Any, **kwargs: Any) -> Any:
        spy.calls.append("connect")
        return real_connect(self, *args, **kwargs)

    def getaddrinfo(*args: Any, **kwargs: Any) -> Any:
        spy.calls.append("getaddrinfo")
        return real_getaddrinfo(*args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return spy


@pytest.mark.parametrize("yes", [False, True])
def test_ca08_no_network(
    tmp_path: Path, socket_spy: SocketSpy, yes: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVICE_API_KEY", new_key())
    monkeypatch.setenv("CLOUD_API_URL", BASE_URL)
    path, _ = make_dead_outbox(tmp_path, 2)
    argv = ["--outbox-path", str(path)] + (["--yes"] if yes else [])
    assert run_cli(argv) == 0
    assert socket_spy.calls == []
    assert read_rows(path) and all(
        r["status"] == ("pending" if yes else "dead") for r in read_rows(path).values()
    )


# =========================================================================== extras: outbox API


def test_extra_requeue_empty_ids_is_not_all(rig: Rig) -> None:
    """``requeue_dead([])`` selects nothing; only ``None`` means all."""
    build_mixed(rig.outbox, rig.clock)
    before = read_rows(rig.path)
    assert rig.outbox.requeue_dead([]) == 0
    assert read_rows(rig.path) == before
    assert rig.outbox.requeue_dead(()) == 0
    assert read_rows(rig.path) == before


def test_extra_requeue_twice_and_sent_never_returns(rig: Rig) -> None:
    mixed = build_mixed(rig.outbox, rig.clock)
    assert rig.outbox.requeue_dead() == 3
    assert rig.outbox.requeue_dead() == 0
    assert rig.outbox.requeue_dead([mixed.sent.inspection_id]) == 0
    assert read_rows(rig.path)[str(mixed.sent.inspection_id)]["status"] == "sent"


def test_extra_requeue_more_than_100_ids(rig: Rig) -> None:
    dead = []
    for _ in range(230):
        item = inspection()
        rig.outbox.put(item)
        dead.append(item)
    for item in dead:
        rig.outbox.mark_dead(item.inspection_id, REJECT_ERROR)
    chosen = [i.inspection_id for i in dead[:205]]
    noise = [uuid.uuid4() for _ in range(60)]
    ids = chosen[:100] + noise + chosen[100:] + chosen[:5]  # duplicates and unknowns mixed in
    assert rig.outbox.requeue_dead(ids) == 205
    rows = read_rows(rig.path)
    chosen_s = {str(i) for i in chosen}
    for iid, row in rows.items():
        assert row["status"] == ("pending" if iid in chosen_s else "dead")


def test_extra_requeue_accepts_generators_and_tuples(rig: Rig) -> None:
    mixed = build_mixed(rig.outbox, rig.clock)
    assert rig.outbox.requeue_dead(tuple(i.inspection_id for i in mixed.dead[:1])) == 1
    assert rig.outbox.requeue_dead([mixed.dead[1].inspection_id, mixed.dead[1].inspection_id]) == 1


def test_extra_dead_items_fields_order_and_no_payload(rig: Rig) -> None:
    mixed = build_mixed(rig.outbox, rig.clock)
    items = rig.outbox.dead_items()
    assert [d.inspection_id for d in items] == [i.inspection_id for i in mixed.dead]
    rows = read_rows(rig.path)
    for d in items:
        assert isinstance(d, DeadItem)
        assert isinstance(d.inspection_id, uuid.UUID)
        assert d.created_at.tzinfo is not None
        assert d.created_at.utcoffset() == timedelta(0)
        row = rows[str(d.inspection_id)]
        assert d.created_at == datetime.fromisoformat(row["created_at"])
        assert d.attempts == row["attempts"]
        assert d.last_error == REJECT_ERROR
    fields = {f.name for f in dataclasses.fields(DeadItem)}
    assert fields == {"inspection_id", "created_at", "attempts", "last_error"}
    assert "payload" not in fields
    with pytest.raises(dataclasses.FrozenInstanceError):
        items[0].attempts = 99  # type: ignore[misc]
    assert rig.outbox.requeue_dead() == 3
    assert rig.outbox.dead_items() == []


def test_extra_requeued_item_is_due_for_fetch(rig: Rig) -> None:
    mixed = build_mixed(rig.outbox, rig.clock)
    rig.clock.advance(1000)
    assert rig.outbox.requeue_dead([mixed.dead[2].inspection_id]) == 1
    due = {item.inspection_id for item in rig.outbox.fetch_due(100)}
    assert mixed.dead[2].inspection_id in due


# =========================================================================== extras: CLI


def test_extra_cli_yes_prints_requeued_and_zero_is_ok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, items = make_dead_outbox(tmp_path, 3)
    assert run_cli(["--outbox-path", str(path), "--yes"]) == 0
    assert capsys.readouterr().out.splitlines() == ["requeued 3 item(s)"]
    assert run_cli(["--outbox-path", str(path), "--yes"]) == 0
    assert capsys.readouterr().out.splitlines() == ["requeued 0 item(s)"]
    assert run_cli(["--outbox-path", str(path)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "0 dead item(s); run again with --yes to requeue"
    ]


def test_extra_cli_id_filter_listing_and_requeue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, items = make_dead_outbox(tmp_path, 3)
    a, b = str(items[0].inspection_id), str(items[2].inspection_id)
    other = str(uuid.uuid4())
    before = file_state(path)
    assert run_cli(["--outbox-path", str(path), "--id", a, "--id", other, "--id", b]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [ln.split(" ", 1)[0] for ln in lines[:-1]] == [a, b]
    assert lines[-1] == "2 dead item(s); run again with --yes to requeue"
    assert file_state(path) == before

    assert run_cli(["--outbox-path", str(path), "--id", a.upper(), "--yes"]) == 0
    assert capsys.readouterr().out.splitlines() == ["requeued 1 item(s)"]
    rows = read_rows(path)
    assert rows[a]["status"] == "pending"
    assert rows[b]["status"] == "dead"
    assert rows[str(items[1].inspection_id)]["status"] == "dead"


def test_extra_cli_150_ids(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path, items = make_dead_outbox(tmp_path, 160)
    argv = ["--outbox-path", str(path), "--yes"]
    for item in items[:150]:
        argv += ["--id", str(item.inspection_id)]
    assert run_cli(argv) == 0
    assert capsys.readouterr().out.splitlines() == ["requeued 150 item(s)"]
    statuses = [row["status"] for row in read_rows(path).values()]
    assert statuses.count("pending") == 150
    assert statuses.count("dead") == 10


def test_extra_cli_without_outbox_path_is_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert run_cli([]) == 2
    assert run_cli(["--yes"]) == 2
    assert run_cli(["--outbox-path", "", "--yes"]) == 2
    assert dir_listing(tmp_path) == set()


@pytest.mark.parametrize("size", [10_000, 200_000])
def test_extra_cli_huge_id_is_rejected_without_echo(
    tmp_path: Path,
    size: int,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    path, _ = make_dead_outbox(tmp_path, 1)
    before = file_state(path)
    marker = new_marker()
    caplog.set_level(logging.DEBUG)
    value = marker + "a" * size
    assert run_cli(["--outbox-path", str(path), "--id", value, "--yes"]) == 2
    out, err = capsys.readouterr()
    assert marker not in out + err + log_text(caplog)
    assert len(out) + len(err) < 4000
    assert file_state(path) == before


@pytest.mark.parametrize(
    "bad",
    [
        "' OR 1=1 --",
        "00000000-0000-0000-0000-00000000000g",
        "‮00000000-0000-0000-0000-000000000000",
        "00000000-0000-0000-0000-000000000000\n",
        "",
    ],
    ids=["sql", "non-hex", "bidi", "newline", "empty"],
)
def test_extra_cli_odd_ids_are_usage_errors(
    tmp_path: Path, bad: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path, _ = make_dead_outbox(tmp_path, 1)
    before = file_state(path)
    code = run_cli(["--outbox-path", str(path), "--id", bad, "--yes"])
    out, err = capsys.readouterr()
    if bad.endswith("\n"):
        # ``uuid.UUID`` strips surrounding whitespace; accepting it is harmless (nil uuid).
        assert code in (0, 2)
        assert file_state(path)[1] == before[1]
    else:
        assert code == 2
        assert file_state(path) == before
    if bad:
        assert bad.strip() not in err


def test_extra_cli_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_cli(["--help"]) == 0
    assert "--outbox-path" in capsys.readouterr().out


@pytest.mark.parametrize(
    "variant",
    [["--ye"], ["-y"], ["--YES"], ["--yes=1"], ["--y"], ["yes"]],
    ids=["abbrev", "short", "upper", "with-value", "prefix", "positional"],
)
def test_extra_cli_yes_lookalikes_never_write(
    tmp_path: Path, variant: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Only the exact ``--yes`` writes: abbreviations and look-alikes are usage errors."""
    path, _ = make_dead_outbox(tmp_path, 2)
    before = file_state(path)
    assert run_cli(["--outbox-path", str(path), *variant]) == 2
    assert "requeued" not in capsys.readouterr().out
    assert file_state(path) == before


@pytest.mark.parametrize(
    "build",
    [
        lambda d: str(d / "a\x01b"),
        lambda d: str(d / ("a" * 5000)),
        lambda d: str(d / "loop"),
        lambda d: "\x00",
    ],
    ids=["control-char", "too-long", "symlink-loop", "nul"],
)
def test_extra_cli_odd_paths_are_usage_errors(tmp_path: Path, build: Callable[[Path], str]) -> None:
    (tmp_path / "loop").symlink_to(tmp_path / "loop")
    before = dir_listing(tmp_path)
    for yes in (False, True):
        assert run_cli(["--outbox-path", build(tmp_path)] + (["--yes"] if yes else [])) == 2
    assert dir_listing(tmp_path) == before


@pytest.mark.parametrize("yes", [False, True])
def test_extra_cli_corrupted_database_file(tmp_path: Path, yes: bool) -> None:
    """A file with the SQLite header and garbage pages: refused, never rewritten."""
    path, _ = make_dead_outbox(tmp_path, 2)
    data = bytearray(path.read_bytes())
    data[200:] = random.Random(34).randbytes(len(data) - 200)
    path.write_bytes(bytes(data))
    assert run_cli(["--outbox-path", str(path)] + (["--yes"] if yes else [])) != 0
    assert path.read_bytes() == bytes(data)


# =========================================================================== extras: files


def test_extra_cli_rejects_directory(tmp_path: Path) -> None:
    folder = tmp_path / "dir.sqlite3"
    folder.mkdir()
    for yes in (False, True):
        assert run_cli(["--outbox-path", str(folder)] + (["--yes"] if yes else [])) == 2
    assert dir_listing(folder) == set()


def test_extra_cli_rejects_dev_null() -> None:
    assert run_cli(["--outbox-path", os.devnull, "--yes"]) == 2


def test_extra_cli_fifo_does_not_hang(tmp_path: Path) -> None:
    fifo = tmp_path / "outbox.fifo"
    os.mkfifo(fifo)
    proc = run_module(["--outbox-path", str(fifo), "--yes"], timeout=20)
    assert proc.returncode == 2
    assert stat.S_ISFIFO(fifo.lstat().st_mode)


@pytest.mark.parametrize(
    "content",
    [
        b"just some text, not a database\n",
        b"",
        "sqlite-empty",
        "sqlite-other-table",
        "sqlite-outbox-missing-column",
    ],
    ids=["text", "empty-file", "sqlite-empty", "other-table", "missing-column"],
)
@pytest.mark.parametrize("yes", [False, True])
def test_extra_cli_file_that_is_not_an_outbox(
    tmp_path: Path, content: bytes | str, yes: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "notes.sqlite3"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        con = sqlite3.connect(path)
        if content == "sqlite-other-table":
            con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
            con.execute("INSERT INTO notes (body) VALUES ('keep me')")
        elif content == "sqlite-outbox-missing-column":
            con.execute("CREATE TABLE outbox (inspection_id TEXT PRIMARY KEY, status TEXT)")
            con.execute("INSERT INTO outbox VALUES ('x', 'dead')")
        con.commit()
        con.close()
    before_bytes = path.read_bytes()
    before_dir = dir_listing(tmp_path)
    code = run_cli(["--outbox-path", str(path)] + (["--yes"] if yes else []))
    capsys.readouterr()
    assert code != 0
    assert path.read_bytes() == before_bytes
    assert dir_listing(tmp_path) == before_dir


def test_extra_cli_dangling_symlink_target_not_created(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "outbox.sqlite3"
    (tmp_path / "missing").mkdir()
    link = tmp_path / "link.sqlite3"
    link.symlink_to(target)
    for yes in (False, True):
        assert run_cli(["--outbox-path", str(link)] + (["--yes"] if yes else [])) == 2
    assert not target.exists()
    assert dir_listing(tmp_path / "missing") == set()


def test_extra_cli_symlink_to_directory_rejected(tmp_path: Path) -> None:
    folder = tmp_path / "real-dir"
    folder.mkdir()
    link = tmp_path / "link.sqlite3"
    link.symlink_to(folder, target_is_directory=True)
    assert run_cli(["--outbox-path", str(link), "--yes"]) == 2
    assert dir_listing(folder) == set()


def test_extra_cli_symlink_to_outbox_behaviour(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A link to a real outbox: either accepted (as the target) or refused with 2, never both
    halves (the target and a new file at the link) touched."""
    path, _ = make_dead_outbox(tmp_path, 2)
    link = tmp_path / "link.sqlite3"
    link.symlink_to(path)
    code = run_cli(["--outbox-path", str(link), "--yes"])
    capsys.readouterr()
    assert code in (0, 2)
    assert link.is_symlink()
    statuses = {r["status"] for r in read_rows(path).values()}
    assert statuses == ({"pending"} if code == 0 else {"dead"})


@pytest.mark.parametrize(
    "name",
    [
        "out box.sqlite3",
        "outbox?mode=rwc.sqlite3",
        "outbox#frag.sqlite3",
        "outbox%3Fmode%3Drwc.sqlite3",
        "saída-ção-日本.sqlite3",
    ],
    ids=["space", "query", "hash", "percent", "unicode"],
)
def test_extra_cli_uri_characters_in_path(
    tmp_path: Path, name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "a?b#c%25d"
    folder.mkdir()
    path, items = make_dead_outbox(folder, 2, name=name)
    before_dir = dir_listing(folder)
    assert run_cli(["--outbox-path", str(path)]) == 0
    assert capsys.readouterr().out.splitlines()[-1].startswith("2 dead item(s)")
    assert run_cli(["--outbox-path", str(path), "--yes"]) == 0
    assert capsys.readouterr().out.splitlines() == ["requeued 2 item(s)"]
    assert {r["status"] for r in read_rows(path).values()} == {"pending"}
    # no extra database file appeared (only SQLite side files of the same name, if any)
    extra = dir_listing(folder) - before_dir
    assert all(e.startswith(name) and e[len(name) :] in {"-wal", "-shm"} for e in extra), extra


@pytest.mark.parametrize(
    "name",
    ["outbox.sqlite3?mode=rwc", "outbox.sqlite3#x", "out%20box.sqlite3"],
    ids=["query-rwc", "hash", "percent-space"],
)
def test_extra_cli_uri_injection_creates_nothing(tmp_path: Path, name: str) -> None:
    """A missing path whose name looks like URI syntax never creates a file."""
    for yes in (False, True):
        assert run_cli(["--outbox-path", str(tmp_path / name)] + (["--yes"] if yes else [])) == 2
    assert dir_listing(tmp_path) == set()


def test_extra_cli_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_dead_outbox(tmp_path, 1)
    monkeypatch.chdir(tmp_path)
    assert run_cli(["--outbox-path", "outbox.sqlite3", "--yes"]) == 0
    assert capsys.readouterr().out.splitlines() == ["requeued 1 item(s)"]


def test_extra_cli_read_only_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path, _ = make_dead_outbox(tmp_path, 2)
    os.chmod(path, 0o400)
    try:
        before = file_state(path)
        assert run_cli(["--outbox-path", str(path)]) == 0
        assert capsys.readouterr().out.splitlines()[-1].startswith("2 dead item(s)")
        code = run_cli(["--outbox-path", str(path), "--yes"])
        out, _ = capsys.readouterr()
        assert code != 0
        assert "requeued" not in out
        assert file_state(path) == before
    finally:
        os.chmod(path, 0o600)


def test_extra_cli_unreadable_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path, _ = make_dead_outbox(tmp_path, 1)
    os.chmod(path, 0)
    try:
        for yes in (False, True):
            code = run_cli(["--outbox-path", str(path)] + (["--yes"] if yes else []))
            assert code != 0
        capsys.readouterr()
    finally:
        os.chmod(path, 0o600)
    assert {r["status"] for r in read_rows(path).values()} == {"dead"}


def test_extra_cli_keeps_file_mode(tmp_path: Path) -> None:
    path, _ = make_dead_outbox(tmp_path, 1)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert run_cli(["--outbox-path", str(path), "--yes"]) == 0
    assert stat.S_IMODE(path.stat().st_mode) == mode
    for side in ("-wal", "-shm"):
        p = path.with_name(path.name + side)
        if p.exists():
            assert stat.S_IMODE(p.stat().st_mode) & 0o077 == mode & 0o077


def test_extra_cli_listing_writes_nothing_even_with_a_wal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without ``--yes`` nothing is written, even with committed data still in the ``-wal``."""
    path = tmp_path / "outbox.sqlite3"
    clock = ManualClock()
    outbox = SqliteOutbox(path, clock=clock, connectivity=ConnectivityState())
    try:
        items = [inspection() for _ in range(3)]
        for item in items:
            outbox.put(item)
            outbox.mark_dead(item.inspection_id, REJECT_ERROR)
        main_before = path.read_bytes()
        rows_before = read_rows(path)
        assert run_cli(["--outbox-path", str(path)]) == 0
        assert capsys.readouterr().out.splitlines()[-1].startswith("3 dead item(s)")
        assert path.read_bytes() == main_before
        assert read_rows(path) == rows_before
        assert outbox.stats().dead == 3
    finally:
        outbox.close()


# =========================================================================== extras: last_error


@pytest.mark.parametrize(
    "text",
    [
        "HTTP 422: line one\nfake-uuid 2026-01-01T00:00:00+00:00 attempts=0 -",
        "HTTP 422: \x1b[31mred\x1b[0m\x07bell\r",
        "HTTP 422: ‮desrever‬ and ⁦isolate⁩ ​zero",
        "HTTP 422: line sep para\x85nel",
        "HTTP 422: \ud800lone",
    ],
    ids=["newline", "ansi", "bidi", "unicode-separators", "surrogate"],
)
def test_extra_cli_last_error_controls_are_neutralised(
    tmp_path: Path, text: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path, items = make_dead_outbox(tmp_path, 2)
    victim = str(items[0].inspection_id)
    # a last_error written by an old version or by hand (the publisher already sanitises)
    con = sqlite3.connect(path)
    try:
        con.execute(
            "UPDATE outbox SET last_error = CAST(? AS TEXT) WHERE inspection_id = ?",
            (text.encode("utf-8", "surrogatepass").decode("utf-8", "replace"), victim),
        )
        con.commit()
    finally:
        con.close()
    assert run_cli(["--outbox-path", str(path)]) == 0
    out = capsys.readouterr().out
    lines = out.split("\n")
    assert lines[-1] == ""
    lines = lines[:-1]
    assert len(lines) == 3, lines
    for line in lines:
        bad = [c for c in line if unicodedata.category(c) in BAD_CATEGORIES]
        assert not bad, (line, bad)
    assert lines[0].startswith(victim)


def test_extra_cli_last_error_null_or_empty_prints_dash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, items = make_dead_outbox(tmp_path, 2)
    sql(
        path,
        "UPDATE outbox SET last_error = NULL WHERE inspection_id = ?",
        (str(items[0].inspection_id),),
    )
    sql(
        path,
        "UPDATE outbox SET last_error = '' WHERE inspection_id = ?",
        (str(items[1].inspection_id),),
    )
    assert run_cli(["--outbox-path", str(path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].endswith(" -")
    assert lines[1].endswith(" -")


def test_extra_cli_long_last_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Exploratory: a 20 000-character last_error written by hand stays on one line."""
    path, items = make_dead_outbox(tmp_path, 1)
    sql(path, "UPDATE outbox SET last_error = ?", ("HTTP 422: " + "x" * 20_000,))
    assert run_cli(["--outbox-path", str(path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2


def test_extra_mark_dead_with_controls_then_listing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``mark_dead`` with a hostile error text: the listing still has one line per item."""
    path = tmp_path / "outbox.sqlite3"
    outbox = SqliteOutbox(path, clock=ManualClock(), connectivity=ConnectivityState())
    try:
        item = inspection()
        outbox.put(item)
        outbox.mark_dead(item.inspection_id, "HTTP 422: a\nb\x1b[2J‮c")
    finally:
        outbox.close()
    assert run_cli(["--outbox-path", str(path)]) == 0
    lines = capsys.readouterr().out.split("\n")[:-1]
    assert len(lines) == 2
    assert not [c for c in "".join(lines) if unicodedata.category(c) in BAD_CATEGORIES]


# =========================================================================== extras: payload


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: {**p, "unexpected_field": "x"},
        lambda p: {**p, "grade_score": 9.5},
        lambda p: {**p, "source": "made-up"},
    ],
    ids=["extra-field", "out-of-range", "bad-enum"],
)
def test_extra_requeued_payload_is_revalidated(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], dict[str, Any]]
) -> None:
    """A stored payload that the current contract refuses never reaches the cloud after the
    requeue, and the loop does not keep retrying it forever."""
    r = make_rig(tmp_path)
    try:
        good, bad = inspection(), inspection()
        r.outbox.put(good)
        r.clock.advance(1)
        r.outbox.put(bad)
        bad_id = str(bad.inspection_id)
        r.outbox.mark_dead(bad.inspection_id, REJECT_ERROR)
        payload = json.loads(read_rows(r.path)[bad_id]["payload"])
        sql(
            r.path,
            "UPDATE outbox SET payload = ? WHERE inspection_id = ?",
            (json.dumps(mutate(payload)), bad_id),
        )
        assert r.outbox.requeue_dead() == 1
        for _ in range(40):
            r.loop.run_once()
            r.clock.advance(61)
        assert str(good.inspection_id) in r.cloud.stored
        assert bad_id not in r.cloud.stored
        for body in r.cloud.bodies:
            assert b"unexpected_field" not in body
            assert b"made-up" not in body
        status = read_rows(r.path)[bad_id]["status"]
        assert status in {"dead", "pending"}
        sends = r.cloud.sent_ids().count(bad_id)
        assert sends == 0, f"invalid payload sent {sends} times"
    finally:
        r.outbox.close()


# =========================================================================== extras: concurrency


def test_extra_listing_not_blocked_by_writer_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, _ = make_dead_outbox(tmp_path, 2)
    SqliteOutbox(path, clock=ManualClock(), connectivity=ConnectivityState()).close()  # WAL
    holder = sqlite3.connect(path, isolation_level=None)
    try:
        holder.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        assert run_cli(["--outbox-path", str(path)]) == 0
        assert time.monotonic() - started < 3
        assert capsys.readouterr().out.splitlines()[-1].startswith("2 dead item(s)")
    finally:
        holder.execute("ROLLBACK")
        holder.close()


def test_extra_requeue_waits_for_a_short_writer_lock(tmp_path: Path) -> None:
    path, _ = make_dead_outbox(tmp_path, 2)
    holder = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")

    def release() -> None:
        time.sleep(1.0)
        holder.execute("COMMIT")

    t = threading.Thread(target=release)
    t.start()
    try:
        proc = run_module(["--outbox-path", str(path), "--yes"])
    finally:
        t.join()
        holder.close()
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "requeued 2 item(s)"


@pytest.mark.slow
def test_extra_requeue_gives_up_on_a_held_writer_lock(tmp_path: Path) -> None:
    path, _ = make_dead_outbox(tmp_path, 2)
    before = read_rows(path)
    holder = sqlite3.connect(path, isolation_level=None)
    try:
        holder.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        proc = run_module(["--outbox-path", str(path), "--yes"], timeout=30)
        elapsed = time.monotonic() - started
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert proc.returncode not in (0, 2), (proc.returncode, proc.stdout, proc.stderr)
    assert "requeued" not in proc.stdout
    assert 4.0 <= elapsed < 20, elapsed
    assert "Traceback" not in proc.stderr
    assert read_rows(path) == before


def test_extra_requeue_with_running_publish_thread(tmp_path: Path) -> None:
    """The ``qc-edge`` publish thread running (real clock), the CLI in a subprocess."""
    path = tmp_path / "outbox.sqlite3"
    connectivity = ConnectivityState()
    outbox = SqliteOutbox(path, connectivity=connectivity)
    cloud = FakeCloud()
    publisher = HttpPublisher(BASE_URL, new_key(), transport=httpx.MockTransport(cloud))
    loop = PublishLoop(outbox, publisher, connectivity, rng=random.Random(0), interval_s=0.05)
    items = [inspection() for _ in range(30)]
    cloud.reject_all = True
    for item in items:
        outbox.put(item)
    loop.start()
    try:
        deadline = time.monotonic() + 30
        while outbox.stats().dead < 30:
            assert time.monotonic() < deadline, outbox.stats()
            time.sleep(0.05)
        cloud.reject_all = False
        proc = run_module(["--outbox-path", str(path), "--yes"])
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "requeued 30 item(s)"
        deadline = time.monotonic() + 30
        while outbox.stats().pending or outbox.stats().dead:
            assert time.monotonic() < deadline, outbox.stats()
            time.sleep(0.05)
    finally:
        loop.stop()
        outbox.close()
    assert set(cloud.stored) == {str(i.inspection_id) for i in items}
    assert len(cloud.writes) == 30
    con = sqlite3.connect(path)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


def test_extra_parallel_requeue_processes_count_once(tmp_path: Path) -> None:
    path, _ = make_dead_outbox(tmp_path, 50)
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "qc_edge.requeue", "--outbox-path", str(path), "--yes"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=subprocess_env(),
            cwd=str(EDGE_ROOT),
        )
        for _ in range(4)
    ]
    total = 0
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
        total += int(REQUEUED.fullmatch(out.strip()).group(1))
    assert total == 50
    assert {r["status"] for r in read_rows(path).values()} == {"pending"}


# =========================================================================== extras: static


def test_extra_requeue_module_imports_no_network_library() -> None:
    """R-02: run in a fresh interpreter, importing the CLI loads no HTTP client."""
    code = (
        "import sys, qc_edge.requeue\n"
        "bad = [m for m in ('httpx', 'requests', 'urllib3', 'http.client', 'PIL') "
        "if m in sys.modules]\n"
        "print(','.join(bad))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(EDGE_ROOT),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_extra_readme_explains_the_requeue() -> None:
    text = (EDGE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "python -m qc_edge.requeue" in text
    assert "--outbox-path" in text
    assert "--yes" in text
    assert "dead" in text
    assert "inspection_id" in text
    assert "SPEC futura" not in text or "requeue" in text
