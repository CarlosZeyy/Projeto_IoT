"""Publish loop (SPEC-009 section 4.3): states, backoff, bisection, health, thread, RNF-04."""

from __future__ import annotations

import logging
import random
import secrets
import sqlite3
import threading
import time
import types
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from qc_contracts import InspectionCreate
from qc_edge.outbox import SqliteOutbox, parse_timestamp
from qc_edge.publish_loop import ConnectivityState, PublishLoop
from qc_edge.publisher import HttpPublisher, PublishResult


class Env:
    def __init__(self, tmp_path: Path, fc: types.ModuleType, **cloud: Any) -> None:
        self.fc = fc
        self.clock = fc.FakeClock()
        self.cloud = fc.FakeCloud(**cloud)
        self.key = "dk-" + secrets.token_urlsafe(24)
        self.state = ConnectivityState()
        self.path = tmp_path / "outbox.sqlite3"
        self.outbox = SqliteOutbox(self.path, clock=self.clock, connectivity=self.state)
        self.publisher = HttpPublisher(fc.BASE_URL, self.key, transport=self.cloud.transport)
        self.loop = PublishLoop(
            self.outbox, self.publisher, self.state, clock=self.clock, rng=random.Random(0)
        )

    def put(self, n: int) -> list[InspectionCreate]:
        items = [self.fc.make_inspection() for _ in range(n)]
        for item in items:
            self.outbox.put(item)
        return items

    def rows(self) -> dict[UUID, dict[str, Any]]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            return {
                UUID(row["inspection_id"]): dict(row)
                for row in conn.execute("SELECT * FROM outbox ORDER BY rowid")
            }
        finally:
            conn.close()

    def run_until_empty(self, step_s: float = 2.0, max_cycles: int = 2000) -> int:
        for cycle in range(max_cycles):
            if self.outbox.stats().pending == 0:
                return cycle
            self.loop.run_once()
            self.clock.advance(step_s)
        raise AssertionError("outbox not empty")


@pytest.fixture
def env(tmp_path: Path, fake_cloud: types.ModuleType) -> Iterator[Env]:
    environment = Env(tmp_path, fake_cloud)
    yield environment
    environment.publisher.close()
    environment.outbox.close()


def reject_containing(bad: set[str], body: dict[str, Any]) -> Any:
    def fail(request: httpx.Request, items: list[dict[str, Any]]) -> httpx.Response | None:
        if any(item["inspection_id"] in bad for item in items):
            return httpx.Response(422, json=body)
        return None

    return fail


# -- connectivity --------------------------------------------------------------------------------


def test_connectivity_state() -> None:
    state = ConnectivityState()
    assert state.snapshot() == ("disabled", None)
    state.connectivity = "offline"
    assert state.connectivity == "offline"
    assert state.last_success_at is None


def test_a_loop_turns_disabled_into_offline(env: Env) -> None:
    assert env.state.connectivity == "offline"
    kept = ConnectivityState("online")
    PublishLoop(env.outbox, env.publisher, kept)
    assert kept.connectivity == "online"


# -- success -------------------------------------------------------------------------------------


def test_150_items_in_two_batches(env: Env) -> None:
    items = env.put(150)
    env.loop.run_once()
    env.loop.run_once()
    assert [len(batch) for batch in env.cloud.batches] == [100, 50]
    sent_order = [item["inspection_id"] for batch in env.cloud.batches for item in batch]
    assert sent_order == [str(item.inspection_id) for item in items]
    rows = env.rows()
    assert all(row["status"] == "sent" and row["sent_at"] for row in rows.values())
    stats = env.outbox.stats()
    assert stats.pending == 0
    assert stats.connectivity == "online"
    assert stats.last_success_at == env.clock.now


def test_duplicates_are_sent(env: Env) -> None:
    items = env.put(3)
    for item in items[:2]:
        env.cloud.stored[item.inspection_id] = item.model_dump(mode="json")
    env.loop.run_once()
    assert all(row["status"] == "sent" for row in env.rows().values())
    assert env.cloud.writes == [items[2].inspection_id]


# -- transient errors and backoff ----------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("timed out"),
        httpx.Response(503, json={"detail": "down"}),
    ],
)
def test_transient_error_schedules_a_retry(env: Env, outcome: Any) -> None:
    env.cloud.fail = lambda request, items: outcome
    start = env.clock.now
    env.put(2)
    env.loop.run_once()
    for row in env.rows().values():
        assert row["status"] == "pending"
        assert row["attempts"] == 1
        assert row["last_error"]
        due = parse_timestamp(row["next_attempt_at"])
        assert start + timedelta(seconds=0.8) <= due <= start + timedelta(seconds=1.2)
    assert env.state.connectivity == "offline"
    assert len(env.cloud.requests) == 1
    env.clock.advance(0.5)
    env.loop.run_once()
    assert len(env.cloud.requests) == 1


def test_backoff_doubles_with_jitter_and_caps_at_60(env: Env) -> None:
    env.cloud.fail = lambda request, items: httpx.ConnectError("refused")
    (item,) = env.put(1)
    delays: list[float] = []
    for attempt in range(10):
        env.loop.run_once()
        row = env.rows()[item.inspection_id]
        assert row["attempts"] == attempt + 1
        due = parse_timestamp(row["next_attempt_at"])
        delays.append((due - env.clock.now).total_seconds())
        env.clock.now = due
    for n, delay in enumerate(delays):
        assert delay <= 60.0
        assert min(60.0, 0.8 * 2**n) - 1e-6 <= delay <= min(60.0, 1.2 * 2**n) + 1e-6
    assert delays[-1] == 60.0


def test_delay_s_formula(env: Env) -> None:
    for n in range(200):
        value = env.loop.delay_s(n)
        assert min(60.0, 0.8 * 2**n) <= value <= min(60.0, 1.2 * 2**n)
    assert env.loop.delay_s(10**6) == 60.0
    assert 0.8 <= env.loop.delay_s(-3) <= 1.2
    loop = PublishLoop(env.outbox, env.publisher, env.state, rng=random.Random(0))
    assert loop.delay_s(2) == pytest.approx(4 * random.Random(0).uniform(0.8, 1.2))


def test_a_transient_error_during_bisection_retries_everything_left(env: Env) -> None:
    items = env.put(4)
    bad = str(items[3].inspection_id)
    calls = {"n": 0}

    def fail(request: httpx.Request, batch: list[dict[str, Any]]) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(422, json={"detail": "Value cannot be stored"})
        return httpx.ConnectError("refused")

    env.cloud.fail = fail
    env.loop.run_once()
    rows = env.rows()
    assert len(env.cloud.batches) == 2  # whole batch, then the first half only
    assert all(row["status"] == "pending" and row["attempts"] == 1 for row in rows.values())
    assert bad in {str(i) for i in rows}
    assert env.state.connectivity == "offline"


# -- rejection and bisection ---------------------------------------------------------------------


def test_bisection_isolates_the_rejected_item(env: Env) -> None:
    items = env.put(8)
    bad = items[5].inspection_id
    env.cloud.fail = reject_containing({str(bad)}, {"detail": "Value cannot be stored"})
    env.run_until_empty()
    rows = env.rows()
    assert [rows[i.inspection_id]["status"] for i in items].count("sent") == 7
    assert rows[bad]["status"] == "dead"
    assert rows[bad]["last_error"] == "HTTP 422: Value cannot be stored"
    assert env.outbox.stats().dead == 1
    batches_before = len(env.cloud.batches)
    for _ in range(5):
        env.loop.run_once()
        env.clock.advance(2)
    later = env.cloud.batches[batches_before:]
    assert all(item["inspection_id"] != str(bad) for batch in later for item in batch)
    assert set(env.cloud.stored) == {i.inspection_id for i in items} - {bad}


def test_rejection_logs_only_the_summary(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    marker = "marker-" + secrets.token_hex(8)
    body = {
        "detail": [
            {"type": "missing", "loc": ["body", "items", 2], "msg": "x", "input": {"m": marker}},
            {"type": "x", "loc": ["body"], "msg": "y", "input": marker},
        ]
    }
    items = env.put(4)
    bad = items[2].inspection_id
    env.cloud.fail = reject_containing({str(bad)}, body)
    with caplog.at_level(logging.DEBUG):
        env.run_until_empty()
    rows = env.rows()
    assert rows[bad]["status"] == "dead"
    assert rows[bad]["last_error"] == "HTTP 422: 2 validation errors"
    assert sum(row["status"] == "sent" for row in rows.values()) == 3
    assert marker not in caplog.text
    assert all(marker not in (row["last_error"] or "") for row in rows.values())
    assert env.key not in caplog.text


def test_a_413_single_item_is_dead(env: Env) -> None:
    (item,) = env.put(1)
    env.cloud.fail = lambda request, items: httpx.Response(413, content=b"too big")
    env.loop.run_once()
    row = env.rows()[item.inspection_id]
    assert row["status"] == "dead"
    assert row["last_error"] == "HTTP 413"


# -- authentication ------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_auth_error_pauses_publishing(
    env: Env, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    env.cloud.fail = lambda request, items: httpx.Response(status, json={"detail": "no"})
    env.put(3)
    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            env.loop.run_once()
            env.clock.advance(120)
    assert len(env.cloud.requests) == 1
    assert all(row["attempts"] == 0 for row in env.rows().values())
    assert env.outbox.stats().connectivity == "auth_error"
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "DEVICE_API_KEY" in errors[0].getMessage()
    assert env.key not in caplog.text


# -- health --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cloud", "expected"),
    [
        ({"health_status": 200}, "online"),
        ({"health_status": 503}, "offline"),
        ({"health_error": httpx.ConnectError("refused")}, "offline"),
    ],
)
def test_health_check_when_idle(
    tmp_path: Path, fake_cloud: types.ModuleType, cloud: dict[str, Any], expected: str
) -> None:
    env = Env(tmp_path, fake_cloud, **cloud)
    try:
        env.loop.run_once()
        env.clock.advance(59)
        env.loop.run_once()
        assert env.cloud.requests == []
        env.clock.advance(2)
        env.loop.run_once()
        assert len(env.cloud.health_requests) == 1
        assert env.state.connectivity == expected
        env.loop.run_once()
        assert len(env.cloud.requests) == 1
    finally:
        env.publisher.close()
        env.outbox.close()


def test_no_health_check_in_auth_error(env: Env) -> None:
    env.state.connectivity = "auth_error"
    env.clock.advance(3600)
    env.loop.run_once()
    assert env.cloud.requests == []


def test_a_publish_attempt_counts_as_contact(env: Env) -> None:
    env.clock.advance(50)
    env.cloud.fail = lambda request, items: httpx.ConnectError("refused")
    (item,) = env.put(1)
    env.loop.run_once()  # contact at T+50 (a failed publication)
    env.outbox.mark_sent([item.inspection_id])  # nothing left to publish
    env.clock.advance(15)  # T+65: 65 s after the loop was built, 15 s after the contact
    env.loop.run_once()
    assert env.cloud.health_requests == []
    env.clock.advance(46)
    env.loop.run_once()
    assert len(env.cloud.health_requests) == 1


# -- unexpected errors ---------------------------------------------------------------------------


class _BrokenPublisher:
    def __init__(self) -> None:
        self.calls = 0

    def publish_batch(self, items: Any) -> list[PublishResult]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("bug")
        return [PublishResult(item.inspection_id, "created") for item in items]

    def check_health(self) -> bool:
        raise RuntimeError("health bug")


def test_an_unexpected_error_is_logged_and_retried(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    broken = _BrokenPublisher()
    loop = PublishLoop(env.outbox, broken, env.state, clock=env.clock, rng=random.Random(0))
    (item,) = env.put(1)
    with caplog.at_level(logging.ERROR):
        loop.run_once()
    row = env.rows()[item.inspection_id]
    assert row["attempts"] == 1
    assert row["last_error"] == "unexpected error: RuntimeError"
    assert any(record.exc_info for record in caplog.records)
    env.clock.advance(2)
    loop.run_once()
    assert env.rows()[item.inspection_id]["status"] == "sent"
    env.clock.advance(120)
    loop.run_once()  # health check raises: logged, no crash


def test_an_invalid_payload_becomes_dead(env: Env) -> None:
    good = env.put(1)[0]
    conn = sqlite3.connect(env.path)
    try:
        conn.execute(
            "INSERT INTO outbox (inspection_id, payload, created_at, attempts, next_attempt_at, "
            "status) VALUES ('11111111-1111-4111-8111-111111111111', '{\"x\": 1}', "
            "'2000-01-01T00:00:00.000000+00:00', 0, '2000-01-01T00:00:00.000000+00:00', "
            "'pending')"
        )
        conn.commit()
    finally:
        conn.close()
    env.loop.run_once()
    rows = env.rows()
    broken = rows[UUID("11111111-1111-4111-8111-111111111111")]
    assert broken["status"] == "dead"
    assert broken["last_error"].startswith("invalid payload")
    assert rows[good.inspection_id]["status"] == "sent"


def test_unexpected_storage_error_does_not_raise(env: Env) -> None:
    env.put(1)
    env.outbox.close()
    env.loop.run_once()  # fetch_due fails: logged, nothing raised


# -- thread --------------------------------------------------------------------------------------


def test_thread_publishes_and_stops(tmp_path: Path, fake_cloud: types.ModuleType) -> None:
    env = Env(tmp_path, fake_cloud)
    env.loop = PublishLoop(
        env.outbox, env.publisher, env.state, rng=random.Random(0), interval_s=0.05
    )
    env.put(5)
    env.loop.start()
    env.loop.start()  # already running: no second thread
    deadline = time.monotonic() + 5
    while env.outbox.stats().pending and time.monotonic() < deadline:
        time.sleep(0.02)
    started = time.monotonic()
    env.loop.stop()
    assert time.monotonic() - started < 10
    assert not any(t.name == "qc-edge-publisher" for t in threading.enumerate())
    assert env.outbox.stats().pending == 0
    assert len(env.cloud.stored) == 5
    env.loop.stop()  # idempotent
    env.outbox.close()
    conn = sqlite3.connect(env.path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_stop_without_start(env: Env) -> None:
    env.loop.stop()


def test_stop_in_the_middle_of_a_bisection_leaves_items_pending(env: Env) -> None:
    items = env.put(4)
    calls = {"n": 0}

    def fail(request: httpx.Request, batch: list[dict[str, Any]]) -> Any:
        calls["n"] += 1
        env.loop._stop_event.set()
        return httpx.Response(422, json={"detail": "x"})

    env.cloud.fail = fail
    env.loop.run_once()
    assert calls["n"] == 1
    assert all(row["status"] == "pending" and row["attempts"] == 0 for row in env.rows().values())
    assert {i.inspection_id for i in items} == set(env.rows())


# -- RNF-04 --------------------------------------------------------------------------------------


def test_outage_and_lost_response_deliver_exactly_once(env: Env) -> None:
    start = env.clock.now
    put_ids: list[UUID] = []
    lost = {"done": False}

    def fail(request: httpx.Request, batch: list[dict[str, Any]]) -> Any:
        elapsed = (env.clock.now - start).total_seconds()
        if 30 <= elapsed <= 150:
            return httpx.ConnectError("cloud down")
        if elapsed > 150 and not lost["done"]:
            lost["done"] = True
            env.cloud.store_then_raise = httpx.ReadTimeout("response lost")
        return None

    env.cloud.fail = fail
    began = time.monotonic()
    for second in range(200):
        put_ids.extend(item.inspection_id for item in env.put(1))
        if second % 2 == 0:
            env.loop.run_once()
        env.clock.advance(1)
    env.run_until_empty()
    assert time.monotonic() - began < 30
    assert lost["done"]
    assert sorted(env.cloud.writes) == sorted(put_ids)
    assert len(env.cloud.writes) == len(set(env.cloud.writes)) == 200
    assert set(env.cloud.stored) == set(put_ids)
    stats = env.outbox.stats()
    assert (stats.pending, stats.dead) == (0, 0)


def test_concurrent_puts_while_the_loop_publishes(env: Env) -> None:
    errors: list[BaseException] = []

    def producer() -> None:
        try:
            env.put(50)
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=producer) for _ in range(4)]
    for thread in threads:
        thread.start()
    while any(thread.is_alive() for thread in threads):
        env.loop.run_once()
    for thread in threads:
        thread.join()
    env.run_until_empty()
    assert errors == []
    assert len(env.rows()) == 200
    assert len(env.cloud.writes) == len(set(env.cloud.writes)) == 200


def test_app_lifespan_starts_and_stops_the_thread(
    tmp_path: Path, fake_cloud: types.ModuleType, settings: Any, jpeg_bytes: bytes
) -> None:
    from fastapi.testclient import TestClient

    from qc_edge.app import create_app
    from qc_edge.inference import StubInferencer

    env = Env(tmp_path, fake_cloud)
    loop = PublishLoop(env.outbox, env.publisher, env.state, rng=random.Random(0), interval_s=0.05)
    app = create_app(settings, StubInferencer(), env.outbox, background=[loop])
    with TestClient(app) as client:
        assert any(t.name == "qc-edge-publisher" for t in threading.enumerate())
        response = client.post(
            "/api/capture",
            headers={"X-Session-Token": app.state.session_token},
            data={"lot_id": "L-001", "mode": "inspect"},
            files={"image": ("a.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert response.status_code == 200
        inspection_id = UUID(response.json()["inspection"]["inspection_id"])
        deadline = time.monotonic() + 5
        while inspection_id not in env.cloud.stored and time.monotonic() < deadline:
            time.sleep(0.02)
        started = time.monotonic()
    assert time.monotonic() - started < 10
    assert not any(t.name == "qc-edge-publisher" for t in threading.enumerate())
    assert inspection_id in env.cloud.stored
    assert env.outbox.stats().connectivity == "online"
    env.publisher.close()
    env.outbox.close()
    conn = sqlite3.connect(env.path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


# -- SPEC-030: deadline as a transient error, wall clock jumping back -----------------------------


class _SlowStream(httpx.SyncByteStream):
    """200 whose body arrives 1 byte per chunk, each chunk 4 s later on the fake monotonic clock."""

    def __init__(self, monotonic: list[float]) -> None:
        self.monotonic = monotonic

    def __iter__(self) -> Any:
        for _ in range(10):
            self.monotonic[0] += 4.0
            yield b"x"


def test_a_deadline_is_a_retry_and_nothing_is_lost(
    tmp_path: Path, fake_cloud: types.ModuleType
) -> None:
    monotonic = [0.0]
    slow = {"on": True}
    cloud = fake_cloud.FakeCloud()

    def handler(request: httpx.Request) -> httpx.Response:
        if slow["on"]:
            cloud.requests.append(request)
            return httpx.Response(200, stream=_SlowStream(monotonic))
        return cloud.handle(request)

    env = Env(tmp_path, fake_cloud)
    env.publisher.close()
    env.publisher = HttpPublisher(
        fake_cloud.BASE_URL,
        env.key,
        transport=httpx.MockTransport(handler),
        monotonic=lambda: monotonic[0],
    )
    env.loop = PublishLoop(
        env.outbox, env.publisher, env.state, clock=env.clock, rng=random.Random(0)
    )
    try:
        items = env.put(3)
        env.loop.run_once()
        rows = env.rows()
        assert [rows[i.inspection_id]["status"] for i in items] == ["pending"] * 3
        assert [rows[i.inspection_id]["attempts"] for i in items] == [1] * 3
        assert {rows[i.inspection_id]["last_error"] for i in items} == {"request deadline exceeded"}
        assert env.state.connectivity == "offline"
        slow["on"] = False
        env.clock.advance(2)
        env.loop.run_once()
        assert env.outbox.stats().pending == 0
        assert len(cloud.stored) == 3
        assert set(cloud.stored) == {item.inspection_id for item in items}
    finally:
        env.publisher.close()
        env.outbox.close()


def test_a_retry_is_not_held_by_a_clock_jump_back(env: Env) -> None:
    env.cloud.fail = lambda request, items: httpx.ConnectError("refused")
    (item,) = env.put(1)
    env.loop.run_once()
    next_at = parse_timestamp(env.rows()[item.inspection_id]["next_attempt_at"])
    assert timedelta(seconds=0.8) <= next_at - env.clock.now <= timedelta(seconds=1.2)
    env.cloud.fail = None
    env.clock.advance(-3600)
    env.loop.run_once()
    assert env.rows()[item.inspection_id]["status"] == "sent"
    assert env.cloud.writes == [item.inspection_id]


def test_a_health_check_after_a_clock_jump_back(env: Env) -> None:
    env.loop._last_contact = None  # as after start(): the first idle cycle checks the cloud
    env.loop.run_once()  # health check at T (last contact T)
    assert len(env.cloud.health_requests) == 1
    env.clock.advance(-3600)
    env.loop.run_once()
    assert len(env.cloud.health_requests) == 2
    env.loop.run_once()  # same instant: 0 s since the last contact
    assert len(env.cloud.requests) == 2
    env.clock.advance(59)
    env.loop.run_once()
    assert len(env.cloud.requests) == 2
    env.clock.advance(1)
    env.loop.run_once()
    assert len(env.cloud.health_requests) == 3
