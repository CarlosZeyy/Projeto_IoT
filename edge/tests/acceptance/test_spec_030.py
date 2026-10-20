"""Acceptance tests for SPEC-030 (qc-edge maintenance: publisher deadline and cap, clock jump,
privacy scan and tests).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One ``test_caNN_*`` per automatable CA, at least (CA-08 is manual and is recorded
in ``reviews/SPEC-030/r1-test-report.md``). Tests named ``test_extra_*`` are exploratory edge
cases around the SPEC (security tag) that no CA spells out.

Rules followed (``reviews/checklist.md`` and ``docs/architecture.md`` section 10):

* the only boundaries replaced are the ones the SPEC names: the cloud (``httpx.MockTransport``
  with a byte stream of its own), the wall clock, ``monotonic`` and the RNG; SQLite and the file
  system are real, always under ``tmp_path``;
* every key and marker is generated at run time (``secrets``), never a credential literal;
* images are synthetic and generated in memory (R-14);
* no test runs the test suite in a subprocess: CA-07 runs pytest on one explicit file over a
  scratch database of its own (name with ``test``), and CA-12 runs pytest on one explicit file,
  without the database; the only inner subprocess there is ``pytest --collect-only`` on two
  explicit files (CA-12 of SPEC-025), which never runs a test.
"""

from __future__ import annotations

import ast
import gzip
import io
import json
import logging
import os
import random
import re
import secrets
import sqlite3
import stat
import struct
import subprocess
import sys
import threading
import unicodedata
import uuid
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from PIL import ExifTags, Image

import qc_edge.privacy
from qc_contracts import Grade, InspectionCreate, ObjectType, Source
from qc_edge.jpeg import jpeg_private_findings
from qc_edge.outbox import SqliteOutbox
from qc_edge.privacy import printable_path
from qc_edge.publish_loop import MAX_DELAY_S, ConnectivityState, PublishLoop
from qc_edge.publisher import (
    HttpPublisher,
    PublishAuthError,
    PublishRejectedError,
    PublishTransientError,
)
from qc_preprocess import load_image

pytestmark = pytest.mark.acceptance

EDGE_ROOT = Path(__file__).resolve().parents[2]  # edge/
ROOT = EDGE_ROOT.parent  # repository root

BASE_URL = "https://cloud.test"
BATCH_PATH = "/api/v1/inspections/batch"
HEALTH_PATH = "/api/v1/health"
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
KIB = 1024
DEADLINE_MESSAGE = "request deadline exceeded"
TOO_LARGE_MESSAGE = "response too large"
ISO_FIXED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$")

CREDENTIAL_IN_URL = re.compile(r"://[^\s/@\"'{}]+:[^\s/@\"'{}]+@")  # CA-06, verbatim


def new_key() -> str:
    """A device key generated at run time (never a literal)."""
    return "acc_" + secrets.token_urlsafe(24)


def new_marker(prefix: str = "acc") -> str:
    return prefix + secrets.token_hex(12)


# =========================================================================== clocks and cloud


class ManualClock:
    """The fake wall clock of the SPEC (always UTC)."""

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


class FakeMonotonic:
    """The fake ``monotonic`` of the SPEC (seconds, only moves forward by ``advance``)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.value = start
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class Blocks(httpx.SyncByteStream):
    """A response body delivered block by block; counts the blocks and records ``close``.

    ``clock``/``step``: the fake ``monotonic`` advances ``step`` seconds before each block.
    """

    def __init__(
        self,
        blocks: Iterable[bytes],
        *,
        clock: FakeMonotonic | None = None,
        step: float = 0.0,
    ) -> None:
        self.blocks = list(blocks)
        self.clock = clock
        self.step = step
        self.delivered = 0
        self.closed = False
        self.closed_after = -1

    def __iter__(self) -> Iterator[bytes]:
        for block in self.blocks:
            if self.clock is not None:
                self.clock.advance(self.step)
            self.delivered += 1
            yield block

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.closed_after = self.delivered


def chunks(data: bytes, size: int) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


Responder = Callable[[httpx.Request], httpx.Response]


class FakeCloud:
    """Fake cloud with the SPEC-004 idempotency (a dict by ``inspection_id``).

    ``respond`` replaces the normal behaviour for every request while it is set (it may raise).
    """

    def __init__(self) -> None:
        self.stored: dict[str, dict[str, Any]] = {}
        self.writes: list[str] = []
        self.requests: list[httpx.Request] = []
        self.respond: Responder | None = None
        self.streams: list[Blocks] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        self.requests.append(request)
        if self.respond is not None:
            return self.respond(request)
        if request.url.path == HEALTH_PATH and request.method == "GET":
            return httpx.Response(200, json={"status": "ok", "db": "ok"})
        if request.url.path == BATCH_PATH and request.method == "POST":
            results = []
            for item in json.loads(body)["items"]:
                iid = item["inspection_id"]
                if iid in self.stored:
                    results.append({"inspection_id": iid, "status": "duplicate"})
                else:
                    self.stored[iid] = item
                    self.writes.append(iid)
                    results.append({"inspection_id": iid, "status": "created"})
            return httpx.Response(200, json={"results": results})
        return httpx.Response(404, json={"detail": "Not Found"})

    def stream_answer(
        self,
        status: int,
        blocks: Iterable[bytes],
        *,
        clock: FakeMonotonic | None = None,
        step: float = 0.0,
        headers: dict[str, str] | None = None,
    ) -> Responder:
        def answer(request: httpx.Request) -> httpx.Response:
            stream = Blocks(blocks, clock=clock, step=step)
            self.streams.append(stream)
            return httpx.Response(
                status, stream=stream, headers=headers or {"content-type": "application/json"}
            )

        return answer

    def batch_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == BATCH_PATH]

    def health_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == HEALTH_PATH]


def inspection() -> InspectionCreate:
    return InspectionCreate(
        inspection_id=uuid.uuid4(),
        device_id="edge-01",
        lot_id="L-030",
        inspected_at=T0,
        object_type=ObjectType.SCREW,
        grade=Grade.GOOD,
        grade_score=1.1,
        type_confidence=0.9,
        grade_confidence=0.8,
        needs_review=False,
        model_version="partqc-mnv3-v1",
        model_sha256="0" * 64,
        latency_ms=42,
        source=Source.LIVE,
    )


def publisher_for(
    cloud: FakeCloud, mono: FakeMonotonic, key: str | None = None, **kwargs: Any
) -> HttpPublisher:
    return HttpPublisher(
        BASE_URL,
        key or new_key(),
        transport=httpx.MockTransport(cloud),
        monotonic=mono,
        **kwargs,
    )


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.path = tmp_path / "outbox.sqlite3"
        assert tmp_path in self.path.parents
        self.clock = ManualClock()
        self.mono = FakeMonotonic()
        self.connectivity = ConnectivityState()
        self.outbox = SqliteOutbox(self.path, clock=self.clock, connectivity=self.connectivity)
        self.cloud = FakeCloud()
        self.key = new_key()
        self.publisher = publisher_for(self.cloud, self.mono, self.key)
        self.loop = PublishLoop(
            self.outbox,
            self.publisher,
            self.connectivity,
            clock=self.clock,
            rng=random.Random(0),
        )

    def put(self) -> InspectionCreate:
        item = inspection()
        self.outbox.put(item)
        return item

    def rows(self) -> list[dict[str, Any]]:
        con = sqlite3.connect(self.path)
        try:
            con.row_factory = sqlite3.Row
            cur = con.execute("SELECT * FROM outbox ORDER BY created_at, rowid")
            return [dict(row) for row in cur.fetchall()]
        finally:
            con.close()

    def set_next_attempt(self, inspection_id: str, value: datetime) -> None:
        """Test set-up only: writes ``next_attempt_at`` in the fixed-width format of the table."""
        text = value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
        assert ISO_FIXED.fullmatch(text)
        con = sqlite3.connect(self.path)
        try:
            con.execute(
                "UPDATE outbox SET next_attempt_at = ? WHERE inspection_id = ?",
                (text, inspection_id),
            )
            con.commit()
        finally:
            con.close()


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    r = Rig(tmp_path)
    try:
        yield r
    finally:
        r.outbox.close()


def ts(value: str) -> datetime:
    assert ISO_FIXED.fullmatch(value), value
    return datetime.fromisoformat(value)


def exception_texts(exc: BaseException) -> str:
    """``str`` and ``repr`` of the exception and of its whole chain."""
    parts: list[str] = []
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in seen:
        seen.append(current)
        parts.extend([str(current), repr(current), repr(current.args)])
        current = current.__cause__ or current.__context__
    return "\n".join(parts)


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    parts = [caplog.text]
    for record in caplog.records:
        parts.extend([record.getMessage(), str(record.msg), repr(record.args)])
    return "\n".join(parts)


def fastapi_422(n_errors: int, total_bytes: int) -> bytes:
    """A 422 in the default FastAPI format, padded with ``input`` echoes up to ``total_bytes``."""
    pad = total_bytes // n_errors
    body = {
        "detail": [
            {
                "type": "string_pattern_mismatch",
                "loc": ["body", "items", i, "lot_id"],
                "msg": "String should match pattern",
                "input": "y" * pad,
            }
            for i in range(n_errors)
        ]
    }
    data = json.dumps(body).encode()
    assert len(data) >= total_bytes
    return data


# =========================================================================== CA-01


def test_ca01_slow_body_exceeds_the_deadline(rig: Rig) -> None:
    rig.cloud.respond = rig.cloud.stream_answer(200, [b"x"] * 10, clock=rig.mono, step=4.0)
    with pytest.raises(PublishTransientError) as excinfo:
        rig.publisher.publish_batch([inspection()])
    exc = excinfo.value
    assert str(exc) == DEADLINE_MESSAGE
    (stream,) = rig.cloud.streams
    assert stream.delivered <= 5
    assert stream.closed  # the response is closed (SPEC section 4.1)
    text = exception_texts(exc)
    assert BASE_URL not in text and "cloud.test" not in text
    assert rig.key not in text


def test_extra_ca01_deadline_counts_from_before_the_request_is_sent(rig: Rig) -> None:
    """``inicio`` is taken before sending: a slow send plus one block already exceeds 15 s."""
    inner = rig.cloud.stream_answer(200, [b"x"])

    def slow_send(request: httpx.Request) -> httpx.Response:
        rig.mono.advance(16.0)  # connection + upload took 16 s (each under the 5 s per op)
        return inner(request)

    rig.cloud.respond = slow_send
    with pytest.raises(PublishTransientError, match=f"^{DEADLINE_MESSAGE}$"):
        rig.publisher.publish_batch([inspection()])


def test_extra_ca01_exactly_the_deadline_is_not_exceeded(rig: Rig) -> None:
    """``monotonic() - inicio > deadline_s``: exactly 15 s is still inside the deadline."""
    item = inspection()
    body = json.dumps(
        {"results": [{"inspection_id": str(item.inspection_id), "status": "created"}]}
    ).encode()
    blocks = chunks(body, len(body) // 3 + 1)
    rig.cloud.respond = rig.cloud.stream_answer(200, blocks, clock=rig.mono, step=5.0)
    results = rig.publisher.publish_batch([item])
    assert len(results) == 1
    assert rig.cloud.streams[-1].delivered == len(blocks) == 3


def test_extra_ca01_deadline_is_configurable_and_other_statuses_skip_the_body(
    rig: Rig,
) -> None:
    pub = publisher_for(rig.cloud, rig.mono, deadline_s=3.0)
    rig.cloud.respond = rig.cloud.stream_answer(200, [b"x"] * 10, clock=rig.mono, step=2.0)
    with pytest.raises(PublishTransientError, match=f"^{DEADLINE_MESSAGE}$"):
        pub.publish_batch([inspection()])
    assert rig.cloud.streams[-1].delivered == 2
    # 401/403, 3xx and other statuses: the body is never read (SPEC-009 section 4.2 kept)
    for status, error in (
        (401, PublishAuthError),
        (403, PublishAuthError),
        (503, None),
        (302, None),
    ):
        rig.cloud.respond = rig.cloud.stream_answer(status, [b"x"] * 10, clock=rig.mono, step=100.0)
        expected = error or PublishTransientError
        with pytest.raises(expected) as excinfo:
            rig.publisher.publish_batch([inspection()])
        assert str(excinfo.value) not in (DEADLINE_MESSAGE, TOO_LARGE_MESSAGE), status
        assert rig.cloud.streams[-1].delivered == 0, status


def test_extra_ca01_check_health_never_reads_the_body(rig: Rig) -> None:
    for status, expected in ((200, True), (503, False)):
        rig.cloud.respond = rig.cloud.stream_answer(
            status, [b"x" * (64 * KIB)] * 20, clock=rig.mono, step=100.0
        )
        assert rig.publisher.check_health() is expected
        assert rig.cloud.streams[-1].delivered == 0
        request = rig.cloud.requests[-1]
        assert (request.method, request.url.path) == ("GET", HEALTH_PATH)
        assert all(name.lower() != "x-api-key" for name in request.headers)


# =========================================================================== CA-02


def test_ca02_body_above_the_cap_is_too_large(rig: Rig) -> None:
    body = b"x" * (512 * KIB + 1)
    rig.cloud.respond = rig.cloud.stream_answer(200, chunks(body, 64 * KIB))
    with pytest.raises(PublishTransientError) as excinfo:
        rig.publisher.publish_batch([inspection()])
    assert str(excinfo.value) == TOO_LARGE_MESSAGE
    (stream,) = rig.cloud.streams
    assert stream.delivered <= 9
    assert stream.closed
    text = exception_texts(excinfo.value)
    assert BASE_URL not in text and rig.key not in text


def test_ca02_large_fastapi_422_keeps_the_summary(rig: Rig) -> None:
    body = fastapi_422(2, 300 * KIB)
    assert 300 * KIB <= len(body) < 512 * KIB
    rig.cloud.respond = rig.cloud.stream_answer(422, chunks(body, 64 * KIB))
    with pytest.raises(PublishRejectedError) as excinfo:
        rig.publisher.publish_batch([inspection()])
    assert excinfo.value.detail == "HTTP 422: 2 validation errors"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"deadline_s": 0},
        {"max_response_bytes": 0},
        {"deadline_s": -1.0},
        {"max_response_bytes": -1},
    ],
    ids=["deadline-0", "cap-0", "deadline-negative", "cap-negative"],
)
def test_ca02_non_positive_deadline_or_cap_is_value_error(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        HttpPublisher(BASE_URL, new_key(), transport=httpx.MockTransport(FakeCloud()), **kwargs)


def test_extra_ca02_exactly_the_cap_is_read(rig: Rig) -> None:
    item = inspection()
    answer = json.dumps(
        {"results": [{"inspection_id": str(item.inspection_id), "status": "created"}]}
    ).encode()
    body = answer + b" " * (512 * KIB - len(answer))  # valid JSON padded with whitespace
    assert len(body) == 512 * KIB
    rig.cloud.respond = rig.cloud.stream_answer(200, chunks(body, 64 * KIB))
    results = rig.publisher.publish_batch([item])
    assert len(results) == 1


@pytest.mark.parametrize("status", [413, 422])
def test_extra_ca02_refusal_above_the_cap_is_a_retry_not_dead(rig: Rig, status: int) -> None:
    """SPEC section 7: a body above the cap is a broken/hostile server: retry, never ``dead``."""
    marker = new_marker()
    body = json.dumps({"detail": marker + "z" * (600 * KIB)}).encode()
    rig.cloud.respond = rig.cloud.stream_answer(status, chunks(body, 64 * KIB))
    with pytest.raises(PublishTransientError) as excinfo:
        rig.publisher.publish_batch([inspection()])
    assert str(excinfo.value) == TOO_LARGE_MESSAGE
    assert marker not in exception_texts(excinfo.value)
    assert rig.cloud.streams[-1].delivered <= 9


def test_extra_ca02_cap_is_configurable_and_counts_decoded_bytes(rig: Rig) -> None:
    pub = publisher_for(rig.cloud, rig.mono, max_response_bytes=10)
    rig.cloud.respond = rig.cloud.stream_answer(200, [b"x" * 6, b"x" * 6, b"x" * 6])
    with pytest.raises(PublishTransientError, match=f"^{TOO_LARGE_MESSAGE}$"):
        pub.publish_batch([inspection()])
    assert rig.cloud.streams[-1].delivered == 2
    # a gzip body (author's note): the cap applies to the decoded bytes, so it is still refused
    data = gzip.compress(b"\x20" * (2 * 1024 * KIB))
    assert len(data) < 512 * KIB
    rig.cloud.respond = rig.cloud.stream_answer(
        200,
        chunks(data, 1024),
        headers={"content-type": "application/json", "content-encoding": "gzip"},
    )
    with pytest.raises(PublishTransientError, match=f"^{TOO_LARGE_MESSAGE}$"):
        rig.publisher.publish_batch([inspection()])


def test_extra_ca02_defaults_are_15_s_and_512_kib(rig: Rig) -> None:
    """Defaults (only ``monotonic`` injected): 512 KiB + 1 is refused; 15 s + 1 block too."""
    pub = HttpPublisher(
        BASE_URL, new_key(), transport=httpx.MockTransport(rig.cloud), monotonic=rig.mono
    )
    rig.cloud.respond = rig.cloud.stream_answer(200, chunks(b"x" * (512 * KIB + 1), 64 * KIB))
    with pytest.raises(PublishTransientError, match=f"^{TOO_LARGE_MESSAGE}$"):
        pub.publish_batch([inspection()])
    rig.cloud.respond = rig.cloud.stream_answer(200, [b"x"] * 20, clock=rig.mono, step=1.0)
    with pytest.raises(PublishTransientError, match=f"^{DEADLINE_MESSAGE}$"):
        pub.publish_batch([inspection()])
    assert rig.cloud.streams[-1].delivered == 16


# =========================================================================== CA-03


def test_ca03_deadline_is_a_retry_and_nothing_is_lost(rig: Rig) -> None:
    items = [rig.put() for _ in range(3)]
    rig.cloud.respond = rig.cloud.stream_answer(200, [b"x"] * 10, clock=rig.mono, step=4.0)
    t = T0 + timedelta(seconds=10)
    rig.clock.set(t)
    rig.loop.run_once()
    rows = rig.rows()
    assert len(rows) == 3
    for row in rows:
        assert row["status"] == "pending"
        assert row["attempts"] == 1
        assert row["last_error"] == DEADLINE_MESSAGE
    assert rig.outbox.stats().connectivity == "offline"
    latest_due = max(ts(r["next_attempt_at"]) for r in rows)

    rig.cloud.respond = None  # the cloud is back to normal
    rig.clock.set(latest_due + timedelta(seconds=0.001))
    rig.loop.run_once()
    rows = rig.rows()
    assert all(r["status"] == "sent" for r in rows)
    assert sorted(rig.cloud.stored) == sorted(str(i.inspection_id) for i in items)
    assert len(rig.cloud.writes) == len(set(rig.cloud.writes)) == 3
    assert rig.outbox.stats().connectivity == "online"


def test_extra_ca03_too_large_is_also_a_retry(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    rig.put()
    rig.cloud.respond = rig.cloud.stream_answer(200, chunks(b"x" * (600 * KIB), 64 * KIB))
    rig.loop.run_once()
    (row,) = rig.rows()
    assert (row["status"], row["attempts"], row["last_error"]) == (
        "pending",
        1,
        TOO_LARGE_MESSAGE,
    )
    assert rig.key not in log_text(caplog)


# =========================================================================== CA-04


def _connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def test_ca04_retry_is_not_held_by_a_clock_jump_back(rig: Rig) -> None:
    item = rig.put()
    rig.cloud.respond = _connect_error
    t = T0 + timedelta(seconds=30)
    rig.clock.set(t)
    rig.loop.run_once()
    (row,) = rig.rows()
    assert row["status"] == "pending" and row["attempts"] == 1
    due = ts(row["next_attempt_at"])
    assert t + timedelta(seconds=0.8) <= due <= t + timedelta(seconds=1.2)

    rig.cloud.respond = None
    rig.clock.set(t - timedelta(seconds=3600))
    before = len(rig.cloud.batch_requests())
    rig.loop.run_once()
    (row,) = rig.rows()
    assert row["status"] == "sent"
    assert len(rig.cloud.batch_requests()) == before + 1
    assert list(rig.cloud.stored) == [str(item.inspection_id)]


def test_ca04_exactly_max_delay_ahead_is_not_due(rig: Rig) -> None:
    item = rig.put()
    iid = str(item.inspection_id)
    now = T0 + timedelta(seconds=100)
    rig.clock.set(now)
    rig.set_next_attempt(iid, now + timedelta(seconds=60))
    assert rig.outbox.fetch_due(max_delay_s=60) == []
    # neighbours of the boundary: one microsecond later is a jumped row, and a due row is due
    rig.set_next_attempt(iid, now + timedelta(seconds=60, microseconds=1))
    assert [str(i.inspection_id) for i in rig.outbox.fetch_due(max_delay_s=60)] == [iid]
    rig.set_next_attempt(iid, now)
    assert [str(i.inspection_id) for i in rig.outbox.fetch_due(max_delay_s=60)] == [iid]
    rig.set_next_attempt(iid, now + timedelta(seconds=30))
    assert rig.outbox.fetch_due(max_delay_s=60) == []


def test_extra_ca04_loop_uses_max_delay_and_order_is_kept(rig: Rig) -> None:
    """Rows in the window ``(now, now + 60]`` wait; the others go in ``created_at`` order."""
    assert MAX_DELAY_S == 60.0
    ids = []
    for k in range(4):
        rig.clock.set(T0 + timedelta(seconds=k))
        ids.append(str(rig.put().inspection_id))
    now = T0 + timedelta(seconds=10)
    rig.clock.set(now)
    rig.set_next_attempt(ids[0], now + timedelta(hours=2))  # jumped
    rig.set_next_attempt(ids[1], now + timedelta(seconds=59))  # waiting (normal backoff)
    rig.set_next_attempt(ids[2], now - timedelta(seconds=1))  # due
    rig.set_next_attempt(ids[3], now + timedelta(seconds=61))  # jumped
    due = [str(i.inspection_id) for i in rig.outbox.fetch_due()]
    assert due == [ids[0], ids[2], ids[3]]
    rig.loop.run_once()
    (batch,) = rig.cloud.batch_requests()
    assert [i["inspection_id"] for i in json.loads(batch.read())["items"]] == due
    status = {r["inspection_id"]: r["status"] for r in rig.rows()}
    assert status == {ids[0]: "sent", ids[1]: "pending", ids[2]: "sent", ids[3]: "sent"}


def test_extra_ca04_sent_and_dead_rows_never_come_back_after_a_jump(rig: Rig) -> None:
    sent = rig.put()
    rig.loop.run_once()
    dead = rig.put()
    rig.outbox.mark_dead(dead.inspection_id, "HTTP 422: x")
    rig.clock.set(T0 - timedelta(days=30))
    assert rig.outbox.fetch_due() == []
    rig.loop.run_once()
    assert {r["inspection_id"]: r["status"] for r in rig.rows()} == {
        str(sent.inspection_id): "sent",
        str(dead.inspection_id): "dead",
    }


def test_extra_ca04_fetch_due_sql_is_parametrized(rig: Rig) -> None:
    """``max_delay_s`` is a number bound as a parameter: a hostile value does not reach SQL."""
    rig.put()
    with pytest.raises((TypeError, ValueError)):
        rig.outbox.fetch_due(max_delay_s="0); DROP TABLE outbox; --")  # type: ignore[arg-type]
    assert len(rig.rows()) == 1


# =========================================================================== CA-05


def test_ca05_health_check_after_a_clock_jump_back(rig: Rig) -> None:
    rig.clock.advance(61)
    rig.loop.run_once()  # health check at T: last contact T
    assert len(rig.cloud.health_requests()) == 1
    t = rig.clock()
    total = len(rig.cloud.requests)

    rig.clock.set(t - timedelta(seconds=3600))
    rig.loop.run_once()
    new = rig.cloud.requests[total:]
    assert [(r.method, r.url.path) for r in new] == [("GET", HEALTH_PATH)]

    total = len(rig.cloud.requests)
    rig.loop.run_once()  # same instant: no request
    assert len(rig.cloud.requests) == total


def test_extra_ca05_after_the_jump_the_normal_period_resumes(rig: Rig) -> None:
    rig.clock.advance(61)
    rig.loop.run_once()
    rig.clock.advance(-3600)
    rig.loop.run_once()
    assert len(rig.cloud.health_requests()) == 2
    rig.clock.advance(59)
    rig.loop.run_once()
    assert len(rig.cloud.health_requests()) == 2
    rig.clock.advance(2)
    rig.loop.run_once()
    assert len(rig.cloud.health_requests()) == 3


def test_extra_ca05_jump_back_with_a_failing_cloud_turns_offline(rig: Rig) -> None:
    rig.clock.advance(61)
    rig.loop.run_once()
    assert rig.outbox.stats().connectivity == "online"
    rig.cloud.respond = _connect_error
    rig.clock.advance(-120)
    rig.loop.run_once()
    assert rig.outbox.stats().connectivity == "offline"


# =========================================================================== CA-06


def _tracked_text_files(prefix: str) -> list[Path]:
    proc = subprocess.run(
        ["git", "ls-files", "-z", prefix],
        cwd=ROOT,
        capture_output=True,
        timeout=60,
        check=True,
    )
    names = [n for n in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if n]
    assert names, "git ls-files returned nothing"
    return [ROOT / n for n in names]


def test_ca06_no_credential_literal_in_edge_urls() -> None:
    offenders: list[str] = []
    checked = 0
    for path in _tracked_text_files("edge"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        checked += 1
        for number, line in enumerate(text.splitlines(), 1):
            if CREDENTIAL_IN_URL.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert checked > 50
    assert offenders == []


@pytest.mark.parametrize(
    ("line", "matches"),
    [
        # the two matching lines are built at run time, so this file itself stays clean
        ('url = "https://' + "u:" + secrets.token_hex(4) + '@h.example"', True),
        ("url = 'http://" + "a:" + secrets.token_hex(4) + "@h'", True),
        ('url = f"https://user:{password}@api.example"', False),
        ('url = "https://user:" + password + "@api.example"', False),
        ('url = "https://api.example:8001/x"', False),
    ],
    ids=["literal", "literal-single-quote", "f-string", "concatenation", "port"],
)
def test_extra_ca06_the_regex_behaves_as_the_spec_says(line: str, matches: bool) -> None:
    assert bool(CREDENTIAL_IN_URL.search(line)) is matches


# =========================================================================== CA-07

REAL_API_TEST = EDGE_ROOT / "tests" / "test_publisher_real_api.py"


def test_ca07_real_api_test_has_no_private_transport_attribute() -> None:
    tree = ast.parse(REAL_API_TEST.read_text(encoding="utf-8"))
    bad = [
        n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "_transport"
    ]
    assert bad == []


@pytest.fixture
def scratch_conninfo(db_conninfo: str) -> Iterator[str]:
    """A database of its own (name with ``test``), so the inner ``migrated_db`` never resets the
    schema of the outer session (``docs/architecture.md`` section 10)."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    base = str(conninfo_to_dict(db_conninfo)["dbname"])
    name = f"{base}_acc030"
    assert "test" in name
    ident = sql.Identifier(name)
    with psycopg.connect(db_conninfo, autocommit=True, prepare_threshold=None) as conn:
        conn.execute(sql.SQL("drop database if exists {} with (force)").format(ident))
        conn.execute(sql.SQL("create database {}").format(ident))
    try:
        yield make_conninfo(db_conninfo, dbname=name)
    finally:
        with psycopg.connect(db_conninfo, autocommit=True, prepare_threshold=None) as conn:
            conn.execute(sql.SQL("drop database if exists {} with (force)").format(ident))


def _pytest_env(**extra: str) -> dict[str, str]:
    env = dict(os.environ)
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_CURRENT_TEST", "TEST_DATABASE_URL"):
        env.pop(name, None)
    env.update(extra)
    return env


@pytest.mark.db
def test_ca07_real_api_test_passes_on_the_database(scratch_conninfo: str) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            str(REAL_API_TEST.relative_to(ROOT)),
        ],
        cwd=ROOT,
        env=_pytest_env(TEST_DATABASE_URL=scratch_conninfo, CI="true"),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(r"\b3 passed\b", proc.stdout), proc.stdout
    assert "failed" not in proc.stdout and "skipped" not in proc.stdout, proc.stdout


# =========================================================================== privacy helpers

SOI = b"\xff\xd8"
XMP_PREFIX = b"http://ns.adobe.com/xap/1.0/\x00"
PHOTOSHOP_PREFIX = b"Photoshop 3.0\x00"
MOTION_TRAILER = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20_000
LATITUDE = (23.0, 33.0, 47.25)
MANIFEST_HEADER = (
    "image_path,item_id,object_type,grade,labeler,angle,captured_at,capture_device,notes\n"
)


def encode(img: Image.Image, fmt: str, **kwargs: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def textured(seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, size=(48, 64, 3), dtype=np.uint8), "RGB")


def clean_jpeg(seed: int = 30, **kwargs: Any) -> bytes:
    return encode(textured(seed), "JPEG", quality=90, **kwargs)


def gps_jpeg(seed: int = 30) -> bytes:
    """The SPEC-025 "EXIF GPS" JPEG: only private segment is the EXIF APP1 with the GPS IFD."""
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "AccPhone"
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "S"
    gps[ExifTags.GPS.GPSLatitude] = LATITUDE
    data = clean_jpeg(seed, exif=exif)
    assert jpeg_private_findings(data) == frozenset({"app1"})
    return data


def segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def metadata_jpeg(seed: int = 30) -> bytes:
    """The SPEC-025 "JPEG com metadados": XMP + EXIF GPS APP1, APP13, COM and a trailer."""
    inserted = (
        segment(0xE1, XMP_PREFIX + b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>')
        + segment(0xED, PHOTOSHOP_PREFIX + b"8BIM\x04\x04\x00\x00\x00\x00\x00\x00")
        + segment(0xFE, new_marker("acc-com-").encode())
    )
    base = gps_jpeg(seed)
    data = base[:2] + inserted + base[2:] + MOTION_TRAILER
    assert jpeg_private_findings(data) == frozenset({"app1", "app13", "com", "trailer"})
    return data


def png_bytes() -> bytes:
    return encode(textured(3), "PNG")


class Dataset:
    def __init__(self, tmp_path: Path, name: str = "D") -> None:
        self.tmp = tmp_path
        self.root = tmp_path / name
        self.folder = self.root / "raw" / "screw" / "fair"
        self.folder.mkdir(parents=True)
        (self.root / "manifest.csv").write_text(MANIFEST_HEADER, encoding="utf-8")

    def write(self, name: str, data: bytes) -> Path:
        path = self.folder / name
        assert self.tmp in path.parents  # never outside tmp_path
        path.write_bytes(data)
        return path


def call_main(argv: list[str]) -> int:
    try:
        value = qc_edge.privacy.main(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return value if isinstance(value, int) else 0


def run_privacy(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = call_main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def loaded(path: Path) -> np.ndarray:
    return np.asarray(load_image(path))


# =========================================================================== CA-09


def test_ca09_any_case_jpeg_is_checked_and_other_files_are_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ds = Dataset(tmp_path)
    ds.write("a.jpg", clean_jpeg(31))
    ds.write("B.JPG", gps_jpeg(32))
    ds.write("c.Jpeg", gps_jpeg(33))
    ds.write("d.png", png_bytes())
    ds.write("e.heic", secrets.token_bytes(64))
    ds.write("f", secrets.token_bytes(64))
    ds.write(".g.jpg.abc123.tmp", secrets.token_bytes(64))
    (ds.folder / "h.jpg").mkdir()

    code, out, err = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    assert code == 1, out + err
    assert out.splitlines() == [
        "raw/screw/fair/B.JPG: app1",
        "raw/screw/fair/c.Jpeg: app1",
        "raw/screw/fair/d.png: invalid",
        "raw/screw/fair/e.heic: invalid",
        "raw/screw/fair/f: invalid",
        "checked 6 images, 5 with private data",
    ]
    assert ".g.jpg.abc123.tmp" not in out + err

    untouched = {
        n: (ds.folder / n).read_bytes() for n in ("d.png", "e.heic", "f", ".g.jpg.abc123.tmp")
    }
    before = {n: loaded(ds.folder / n) for n in ("B.JPG", "c.Jpeg")}
    code, out, err = run_privacy(["--dataset-dir", str(ds.root), "--fix"], capsys)
    assert code == 1, out + err
    lines = out.splitlines()
    assert "fixed raw/screw/fair/B.JPG" in lines
    assert "fixed raw/screw/fair/c.Jpeg" in lines
    for name in ("B.JPG", "c.Jpeg"):
        path = ds.folder / name
        assert jpeg_private_findings(path.read_bytes()) == frozenset()
        after = loaded(path)
        assert after.shape == before[name].shape
        assert np.array_equal(after, before[name])
    for name, data in untouched.items():
        assert (ds.folder / name).read_bytes() == data, name
    assert {p.name for p in ds.folder.iterdir()} == {
        "a.jpg",
        "B.JPG",
        "c.Jpeg",
        "d.png",
        "e.heic",
        "f",
        ".g.jpg.abc123.tmp",
        "h.jpg",
    }
    assert (ds.folder / "h.jpg").is_dir()

    code, out, _ = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    assert code == 1
    assert out.splitlines()[-1] == "checked 6 images, 3 with private data"


@pytest.mark.parametrize(
    "name", ["x.JPEG", "x.jPg", "x.JpEg", ".hidden.jpg", "x.jpg.JPG"], ids=lambda n: n
)
def test_extra_ca09_more_jpeg_spellings_are_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    ds = Dataset(tmp_path)
    ds.write(name, gps_jpeg(34))
    code, out, _ = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    assert code == 1
    assert out.splitlines() == [
        f"raw/screw/fair/{name}: app1",
        "checked 1 images, 1 with private data",
    ]


@pytest.mark.parametrize(
    "name",
    ["x.jpg.tmp", ".x.TMP", "x.tmp", "x.jpgx", "x.jpe", "x.jfif", "x.JPG.png", "x.gif", "x.webp"],
    ids=lambda n: n,
)
def test_extra_ca09_names_that_are_not_jpeg_nor_temporaries_are_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    ds = Dataset(tmp_path)
    data = gps_jpeg(35)  # even real JPEG bytes are not read under a non-JPEG name
    ds.write(name, data)
    code, out, _ = run_privacy(["--dataset-dir", str(ds.root), "--fix"], capsys)
    assert code == 1
    assert out.splitlines() == [
        f"raw/screw/fair/{name}: invalid",
        "checked 1 images, 1 with private data",
    ]
    assert (ds.folder / name).read_bytes() == data


@pytest.mark.parametrize("name", [".a.jpg.abc.tmp", ".tmp", ".x.tmp"], ids=lambda n: n)
def test_extra_ca09_edge_temporaries_are_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    ds = Dataset(tmp_path)
    ds.write("a.jpg", clean_jpeg(36))
    ds.write(name, gps_jpeg(37))
    code, out, err = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    assert code == 0, out + err
    assert out.splitlines() == ["checked 1 images, 0 with private data"]


def test_extra_ca09_nested_and_top_level_files_and_special_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ds = Dataset(tmp_path)
    (ds.root / "raw" / "readme.txt").write_bytes(b"x")
    deep = ds.root / "raw" / "nut" / "poor" / "sub"
    deep.mkdir(parents=True)
    (deep / "p.PNG").write_bytes(png_bytes())
    (ds.root / "outside.txt").write_bytes(b"x")  # outside raw/: not part of the scan
    target = tmp_path / "target.png"
    target.write_bytes(png_bytes())
    (ds.folder / "link.png").symlink_to(target)  # symlinks keep being ignored
    os.mkfifo(ds.folder / "fifo.jpg")  # special file: ignored (and never opened)
    (ds.folder / "empty.png").write_bytes(b"")
    code, out, _ = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    assert code == 1
    assert out.splitlines() == [
        "raw/nut/poor/sub/p.PNG: invalid",
        "raw/readme.txt: invalid",
        "raw/screw/fair/empty.png: invalid",
        "checked 3 images, 3 with private data",
    ]


def test_extra_ca09_unreadable_non_jpeg_is_invalid_not_unreadable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-JPEG is never read, so a mode 0o000 ``.png`` is ``invalid``, not ``unreadable``."""
    if os.geteuid() == 0:
        pytest.skip("root reads files with mode 0o000")
    ds = Dataset(tmp_path)
    path = ds.write("locked.png", png_bytes())
    path.chmod(0)
    try:
        code, out, _ = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert code == 1
    assert out.splitlines() == [
        "raw/screw/fair/locked.png: invalid",
        "checked 1 images, 1 with private data",
    ]


# =========================================================================== CA-10

HOSTILE = "x\nchecked 9 images, 0 with private data\x1b[8m.jpg"


def test_ca10_control_characters_are_escaped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ds = Dataset(tmp_path)
    ds.write(HOSTILE, metadata_jpeg(40))
    code, out, err = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    assert code == 1, out + err
    assert out.splitlines() == [
        "raw/screw/fair/x\\x0achecked 9 images, 0 with private data\\x1b[8m.jpg: "
        "app1, app13, com, trailer",
        "checked 1 images, 1 with private data",
    ]
    assert "\x1b" not in out
    assert out.count("\n") == 2 and out.endswith("\n")
    assert "\r" not in out


def test_ca10_a_name_that_is_not_utf8_is_escaped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ds = Dataset(tmp_path)
    raw_name = os.fsencode(ds.folder) + b"/n\xffame.jpg"
    try:
        with open(raw_name, "wb") as fh:
            fh.write(gps_jpeg(41))
    except OSError as exc:  # pragma: no cover - file system refuses non-UTF-8 names
        pytest.skip(f"file system refuses the name: {exc.strerror}")
    code, out, _ = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    assert code == 1
    lines = out.splitlines()
    assert len(lines) == 2
    assert "\\udcff" in lines[0]
    assert lines[0] == "raw/screw/fair/n\\udcffame.jpg: app1"
    assert "\udcff" not in out  # the lone surrogate itself never reaches the stream


def test_extra_ca10_real_stdout_with_hostile_and_non_utf8_names(tmp_path: Path) -> None:
    """``python -m qc_edge.privacy`` on a real pipe: no ``UnicodeEncodeError``, no ESC byte."""
    ds = Dataset(tmp_path)
    ds.write(HOSTILE, metadata_jpeg(42))
    with open(os.fsencode(ds.folder) + b"/n\xffame.jpg", "wb") as fh:
        fh.write(gps_jpeg(43))
    ds.write("peça-ção.jpg", gps_jpeg(44))
    for fix in (False, True):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("EDGE_", "DATASET_"))}
        proc = subprocess.run(
            [sys.executable, "-m", "qc_edge.privacy", "--dataset-dir", str(ds.root)]
            + (["--fix"] if fix else []),
            cwd=tmp_path,
            env=env,
            capture_output=True,
            timeout=120,
        )
        assert b"Traceback" not in proc.stderr, proc.stderr
        assert b"\x1b" not in proc.stdout + proc.stderr
        # 3 finding lines (+ 3 "fixed" lines with --fix) + the summary of what was found
        assert proc.stdout.count(b"\n") == (7 if fix else 4)
        text = proc.stdout.decode("utf-8")
        assert "peça-ção.jpg" in text  # accented letters are not escaped
        if fix:
            assert proc.returncode == 0
            assert "fixed raw/screw/fair/n\\udcffame.jpg" in text.splitlines()
        else:
            assert proc.returncode == 1
        assert text.splitlines()[-1] == "checked 3 images, 3 with private data"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("x\nchecked\x1b[8m.jpg", "x\\x0achecked\\x1b[8m.jpg"),
        ("a\\b.jpg", "a\\\\b.jpg"),
        ("tab\there", "tab\\x09here"),
        ("cr\rx", "cr\\x0dx"),
        ("del\x7f", "del\\x7f"),
        ("nel\x85", "nel\\x85"),
        ("bidi‮.gpj", "bidi\\u202e.gpj"),
        ("zw​j", "zw\\u200bj"),
        ("bom﻿", "bom\\ufeff"),
        ("ls ps ", "ls\\u2028ps\\u2029"),
        ("sur\udcff", "sur\\udcff"),
        ("tag\U000e0001", "tag\\U000e0001"),
        ("peça_ção é ü ñ.jpg", "peça_ção é ü ñ.jpg"),
        ("nbsp x", "nbsp x"),  # Zs is not escaped
        ("emoji\U0001f600", "emoji\U0001f600"),
        ("raw/screw/fair/a.jpg", "raw/screw/fair/a.jpg"),
        ("", ""),
    ],
)
def test_extra_ca10_printable_path_table(raw: str, expected: str) -> None:
    assert printable_path(raw) == expected


def test_extra_ca10_printable_path_never_leaves_an_escapable_character() -> None:
    escaped = {"Cc", "Cf", "Cs", "Zl", "Zp"}
    sample = "".join(chr(c) for c in range(0x0, 0x3000)) + "𐏿\U000e0020\U0010fffd"
    out = printable_path(sample)
    assert not [c for c in out if unicodedata.category(c) in escaped]
    # round trip: the escape is reversible, so two different names never print the same
    other = printable_path(sample.replace("\x01", "\\x01"))
    assert other != out


def test_extra_ca10_order_follows_the_original_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ds = Dataset(tmp_path)
    ds.write("a\x01.jpg", gps_jpeg(45))  # original "\x01" < "0"; escaped "\\" > "0"
    ds.write("a0.jpg", gps_jpeg(46))
    code, out, _ = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    assert code == 1
    assert out.splitlines() == [
        "raw/screw/fair/a\\x01.jpg: app1",
        "raw/screw/fair/a0.jpg: app1",
        "checked 2 images, 2 with private data",
    ]


def test_extra_ca10_fixed_lines_are_escaped_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ds = Dataset(tmp_path)
    ds.write("y\x1b]0;t\x07.jpg", gps_jpeg(47))
    code, out, _ = run_privacy(["--dataset-dir", str(ds.root), "--fix"], capsys)
    assert code == 0
    lines = out.splitlines()
    assert lines == [
        "raw/screw/fair/y\\x1b]0;t\\x07.jpg: app1",
        "fixed raw/screw/fair/y\\x1b]0;t\\x07.jpg",
        "checked 1 images, 1 with private data",
    ]
    assert "\x1b" not in out and "\x07" not in out


# =========================================================================== CA-11


def test_ca11_unreadable_file_is_listed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root reads files with mode 0o000")
    caplog.set_level(logging.DEBUG)
    ds = Dataset(tmp_path)
    ds.write("a.jpg", clean_jpeg(50))
    locked = ds.write("z.jpg", gps_jpeg(51))
    locked.chmod(0)
    try:
        code, out, err = run_privacy(["--dataset-dir", str(ds.root)], capsys)
    finally:
        locked.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert code == 1, out + err
    lines = out.splitlines()
    assert "raw/screw/fair/z.jpg: unreadable" in lines
    assert lines[-1] == "checked 1 images, 0 with private data"
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_extra_ca11_unreadable_in_fix_mode_and_escaped_in_the_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root reads files with mode 0o000")
    caplog.set_level(logging.DEBUG)
    ds = Dataset(tmp_path)
    ds.write("b.jpg", gps_jpeg(52))
    locked = ds.write("z\x1b[2J.jpg", gps_jpeg(53))
    locked.chmod(0)
    try:
        caplog.clear()
        code, out, err = run_privacy(["--dataset-dir", str(ds.root), "--fix"], capsys)
    finally:
        locked.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert code == 1
    lines = out.splitlines()
    assert "raw/screw/fair/z\\x1b[2J.jpg: unreadable" in lines
    assert "fixed raw/screw/fair/b.jpg" in lines
    assert lines[-1] == "checked 1 images, 1 with private data"  # b.jpg, found then fixed
    text = out + err + log_text(caplog)
    assert "\x1b" not in text
    assert str(ds.root) not in text


# =========================================================================== CA-12


def test_ca12_pytest_addopts_does_not_break_the_spec_025_count() -> None:
    target = EDGE_ROOT / "tests" / "acceptance" / "test_spec_025.py"
    env = _pytest_env(PYTEST_ADDOPTS="-k nao_existe_nenhum_teste")
    env.pop("CI", None)  # without the database (docs/architecture.md section 10)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            str(target.relative_to(ROOT)),
            "-k",
            "ca12",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(r"\b1 passed\b", proc.stdout), proc.stdout
    assert "failed" not in proc.stdout
