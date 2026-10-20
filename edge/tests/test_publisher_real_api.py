"""Publisher against the real ``qc-api`` on the test database (SPEC-009 section 4.2, SPEC-004).

The ``qc_api`` app runs in process (a ``TestClient``, never the network) over
``TEST_DATABASE_URL`` (``db`` marker: skipped without it). The publisher reaches it through
``TestClientTransport``, which uses only the public API of the ``TestClient`` (SPEC-030 section
4.3), so it works whether Starlette builds the ``TestClient`` on ``httpx`` or on ``httpx2`` (the
``train`` extra installs the latter). It checks what the fake cloud of the
other tests only imitates: the ``BatchResult`` of the real route, ``duplicate`` on a resend, 401
for an unknown key, and the real 422 ``Value cannot be stored`` (a ``real`` column underflow)
isolated by the bisection.
"""

from __future__ import annotations

import random
import secrets
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("qc_api")

import httpx  # noqa: E402
import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from qc_api.auth import hash_api_key  # noqa: E402
from qc_api.config import Settings  # noqa: E402
from qc_api.main import create_app  # noqa: E402
from qc_edge.outbox import SqliteOutbox  # noqa: E402
from qc_edge.publish_loop import ConnectivityState, PublishLoop  # noqa: E402
from qc_edge.publisher import HttpPublisher, PublishAuthError  # noqa: E402

pytestmark = pytest.mark.db

BASE = "http://127.0.0.1:8001"


@pytest.fixture
def api(clean_db: str) -> Iterator[tuple[TestClient, str]]:
    key = secrets.token_urlsafe(32)
    with psycopg.connect(clean_db, autocommit=True, prepare_threshold=None) as conn:
        conn.execute(
            "insert into devices (device_id, api_key_hash) values (%s, %s)",
            ("edge-01", hash_api_key(key)),
        )
    settings = Settings(DATABASE_URL=clean_db, READ_API_KEY=secrets.token_urlsafe(32))
    with TestClient(create_app(settings)) as client:
        yield client, key


# Headers that describe the connection or the encoding of one hop, not the message.
_HOP_HEADERS = frozenset(
    {"host", "connection", "content-length", "content-encoding", "transfer-encoding"}
)


class TestClientTransport(httpx.BaseTransport):
    """``httpx`` transport that forwards each request to a ``TestClient`` by its public API.

    The response comes back as an ``httpx.Response`` with the status, the headers and the body
    the app returned (already decoded, hence without ``content-encoding``).
    """

    __test__ = False  # not a test class, despite the name

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        headers = {
            name: value
            for name, value in request.headers.items()
            if name.lower() not in _HOP_HEADERS
        }
        answer: Any = self._client.request(
            request.method,
            str(request.url),
            headers=headers,
            content=request.read(),
            follow_redirects=False,
        )
        response_headers = [
            (name, value)
            for name, value in answer.headers.items()
            if name.lower() not in _HOP_HEADERS
        ]
        return httpx.Response(answer.status_code, headers=response_headers, content=answer.content)


def publisher(client: TestClient, key: str) -> HttpPublisher:
    return HttpPublisher(BASE, key, transport=TestClientTransport(client))


def stored_ids(conninfo: str) -> set[str]:
    with psycopg.connect(conninfo, autocommit=True, prepare_threshold=None) as conn:
        return {str(row[0]) for row in conn.execute("select inspection_id from inspections")}


def test_batch_created_then_duplicate(
    api: tuple[TestClient, str], fake_cloud: types.ModuleType, clean_db: str
) -> None:
    client, key = api
    items = [fake_cloud.make_inspection() for _ in range(3)]
    pub = publisher(client, key)
    assert [r.status for r in pub.publish_batch(items)] == ["created"] * 3
    assert [r.status for r in pub.publish_batch(items)] == ["duplicate"] * 3
    assert stored_ids(clean_db) == {str(item.inspection_id) for item in items}
    assert pub.check_health() is True


def test_unknown_key_is_an_auth_error(
    api: tuple[TestClient, str], fake_cloud: types.ModuleType
) -> None:
    client, _ = api
    with pytest.raises(PublishAuthError, match="HTTP 401"):
        publisher(client, secrets.token_urlsafe(32)).publish_batch([fake_cloud.make_inspection()])


def test_loop_isolates_the_value_the_database_refuses(
    api: tuple[TestClient, str], fake_cloud: types.ModuleType, clean_db: str, tmp_path: Path
) -> None:
    client, key = api
    items = [fake_cloud.make_inspection() for _ in range(4)]
    # Accepted by the contract (0..1), refused by the ``real`` column (underflow, SQLSTATE 22003).
    items[2] = fake_cloud.make_inspection(type_confidence=1e-50)
    state = ConnectivityState()
    outbox = SqliteOutbox(tmp_path / "outbox.sqlite3", connectivity=state)
    try:
        for item in items:
            outbox.put(item)
        loop = PublishLoop(outbox, publisher(client, key), state, rng=random.Random(0))
        loop.run_once()
        stats = outbox.stats()
        assert (stats.pending, stats.dead, stats.connectivity) == (0, 1, "online")
        row = outbox._conn.execute(
            "select status, last_error from outbox where inspection_id = ?",
            (str(items[2].inspection_id),),
        ).fetchone()
        assert row == ("dead", "HTTP 422: Value cannot be stored")
    finally:
        outbox.close()
    expected = {str(item.inspection_id) for i, item in enumerate(items) if i != 2}
    assert stored_ids(clean_db) == expected
