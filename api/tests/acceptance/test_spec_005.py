"""Acceptance tests for SPEC-005 (qc-api: read routes and metrics).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test per CA (``test_caNN_*``); ``test_extra_*`` tests are exploratory edge
cases around SPEC-005 section 4 that no CA spells out.

Data set D (SPEC-005 section 5) is inserted with plain SQL into the migrated test database
(``clean_db`` from SPEC-003), with ``edge-01`` and ``sim-01`` registered by hash. The app is
``create_app(Settings(DATABASE_URL=<test>, READ_API_KEY="r"*32))`` inside a ``TestClient`` block.
Device keys and fake passwords are built at run time, never written as literals (R-03).
"""

from __future__ import annotations

import ast
import hashlib
import logging
import math
import re
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlunsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from qc_api.config import Settings
from qc_api.main import create_app
from qc_contracts import (
    Grade,
    InspectionRead,
    LotSummary,
    MetricsSummary,
    ObjectType,
    Page,
    TimeseriesPoint,
)

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
API_SRC = ROOT / "api" / "src" / "qc_api"

R = "r" * 32
WRONG_KEY = "err" + "ada"  # the CA-01 value, assembled at run time (no literal key)
T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
SHA = "a" * 64

URL_LIST = "/api/v1/inspections"
URL_BATCH = "/api/v1/inspections/batch"
URL_SUMMARY = "/api/v1/metrics/summary"
URL_SERIES = "/api/v1/metrics/timeseries"
URL_LOTS = "/api/v1/lots"
READ_URLS = (URL_LIST, URL_SUMMARY, URL_SERIES, URL_LOTS)

UNAUTHORIZED = {"detail": "Missing or invalid API key"}
DB_DOWN = {"detail": "Database unavailable"}
TOO_MANY_BUCKETS = {"detail": "Too many buckets; narrow the time range or use a larger bucket"}
CANNOT_STORE = {"detail": "Value cannot be stored"}
INTERNAL = {"detail": "Internal server error"}

REL = 1e-6

# Data set D: (row, device, lot, source, object_type, grade, grade_score, type_confidence,
# needs_review, minutes after T0).
D_ROWS: tuple[tuple[int, str, str, str, str, str | None, float | None, float, bool, int], ...] = (
    (1, "edge-01", "L-A", "live", "screw", "perfect", 0.2, 0.90, False, 5),
    (2, "edge-01", "L-A", "live", "screw", "good", 1.1, 0.80, False, 10),
    (3, "edge-01", "L-A", "live", "nut", "poor", 3.0, 0.70, True, 20),
    (4, "edge-01", "L-A", "live", "unknown", None, None, 0.40, True, 50),
    (5, "edge-01", "L-B", "live", "nut", "unusable", 3.9, 0.95, False, 70),
    (6, "edge-01", "L-B", "live", "screw", "fair", 2.0, 0.85, False, 75),
    (7, "sim-01", "L-S", "simulated", "screw", "poor", 3.2, 0.99, False, 120),
    (8, "sim-01", "L-S", "simulated", "nut", "good", 1.0, 0.99, False, 150),
)


# --------------------------------------------------------------------------- helpers


def approx(value: float) -> Any:
    return pytest.approx(value, rel=REL)


def key_header(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


READ = key_header(R)


def connect(conninfo: str) -> psycopg.Connection:
    return psycopg.connect(conninfo, autocommit=True, prepare_threshold=None)


def no_db_url() -> str:
    """URL of a database on a closed local port; the fake password is built at run time."""
    password = "pw" + secrets.token_hex(4)
    return urlunsplit(("postgresql", f"u:{password}@127.0.0.1:1", "/x", "", ""))


def register(conn: psycopg.Connection, device_id: str, key: str) -> None:
    conn.execute(
        "insert into devices (device_id, api_key_hash) values (%s, %s)",
        (device_id, hashlib.sha256(key.encode()).hexdigest()),
    )


INSERT_ROW = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'partqc-mnv3-v1', %s, 42, %s)
"""


def insert_row(
    conn: psycopg.Connection,
    *,
    device: str,
    lot: str,
    source: str,
    object_type: str,
    grade: str | None,
    grade_score: float | None,
    type_confidence: float,
    needs_review: bool,
    inspected_at: datetime,
    inspection_id: str | None = None,
) -> str:
    iid = inspection_id or str(uuid.uuid4())
    grade_confidence = None if grade is None else 0.8
    conn.execute(
        INSERT_ROW,
        (
            iid,
            device,
            lot,
            inspected_at,
            object_type,
            grade,
            grade_score,
            type_confidence,
            grade_confidence,
            needs_review,
            SHA,
            source,
        ),
    )
    return iid


def count_rows(conninfo: str) -> int:
    with connect(conninfo) as conn:
        return conn.execute("select count(*) from inspections").fetchone()[0]


def parse_utc(value: str) -> datetime:
    """Parses an ISO datetime from a response; it must carry an explicit UTC offset."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, value
    assert parsed.utcoffset() == timedelta(0), value
    return parsed


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Every captured record: formatted text, message, raw args and exception text."""
    parts: list[str] = [caplog.text]
    for rec in caplog.records:
        parts.append(rec.getMessage())
        parts.append(repr(rec.args))
        if rec.exc_text:
            parts.append(rec.exc_text)
        if rec.exc_info and rec.exc_info[1] is not None:
            parts.append(repr(rec.exc_info[1]))
    return "\n".join(parts)


@dataclass
class DEnv:
    db: str
    client: TestClient
    keys: dict[str, str]
    ids: dict[int, str] = field(default_factory=dict)

    def get(self, url: str, params: Any = None, key: str | None = R) -> Any:
        headers = key_header(key) if key is not None else {}
        return self.client.get(url, params=params, headers=headers)

    def rows(self, *numbers: int) -> list[str]:
        return [self.ids[n] for n in numbers]


def insert_d(conn: psycopg.Connection) -> dict[int, str]:
    ids: dict[int, str] = {}
    for row, device, lot, source, otype, grade, score, conf, review, minutes in D_ROWS:
        ids[row] = insert_row(
            conn,
            device=device,
            lot=lot,
            source=source,
            object_type=otype,
            grade=grade,
            grade_score=score,
            type_confidence=conf,
            needs_review=review,
            inspected_at=T0 + timedelta(minutes=minutes),
        )
    return ids


def setup_devices(conninfo: str) -> dict[str, str]:
    keys = {"edge-01": secrets.token_urlsafe(32), "sim-01": secrets.token_urlsafe(32)}
    with connect(conninfo) as conn:
        for device_id, key in keys.items():
            register(conn, device_id, key)
    return keys


@pytest.fixture
def empty_env(clean_db: str) -> Iterator[DEnv]:
    """Devices registered, no inspections."""
    keys = setup_devices(clean_db)
    app = create_app(Settings(DATABASE_URL=clean_db, READ_API_KEY=R))
    with TestClient(app) as client:
        yield DEnv(clean_db, client, keys)


@pytest.fixture
def d_env(empty_env: DEnv) -> DEnv:
    """Data set D inserted with plain SQL."""
    with connect(empty_env.db) as conn:
        empty_env.ids = insert_d(conn)
    return empty_env


def item_ids(resp: Any) -> list[str]:
    return [item["inspection_id"] for item in resp.json()["items"]]


def series(resp: Any) -> list[tuple[datetime, int, int, float | None]]:
    data = resp.json()
    assert isinstance(data, list), data
    return [
        (parse_utc(p["bucket_start"]), p["total"], p["defective"], p["defect_rate"]) for p in data
    ]


# --------------------------------------------------------------------------- CA-01


@pytest.mark.db
def test_ca01_read_routes_reject_missing_wrong_and_device_keys(d_env: DEnv) -> None:
    for url in READ_URLS:
        for key in (None, WRONG_KEY, "wrong-" + secrets.token_hex(4), d_env.keys["edge-01"]):
            resp = d_env.get(url, key=key)
            assert resp.status_code == 401, (url, key is None, resp.text)
            assert resp.json() == UNAUTHORIZED, (url, resp.text)
        # control: the read key works on the same route
        assert d_env.get(url).status_code == 200, url


# --------------------------------------------------------------------------- CA-02


@pytest.mark.db
def test_ca02_first_page_order_and_items(d_env: DEnv) -> None:
    resp = d_env.get(URL_LIST, {"limit": 3})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 8
    assert body["limit"] == 3
    assert body["offset"] == 0
    assert item_ids(resp) == d_env.rows(8, 7, 6)
    page = Page[InspectionRead].model_validate(body)
    for raw in body["items"]:
        InspectionRead.model_validate(raw)
    item7 = page.items[1]
    assert str(item7.inspection_id) == d_env.ids[7]
    assert item7.is_defective is True
    assert body["items"][1]["source"] == "simulated"


# --------------------------------------------------------------------------- CA-03


@pytest.mark.db
def test_ca03_offset_pages_and_offset_past_total(d_env: DEnv) -> None:
    resp = d_env.get(URL_LIST, {"limit": 3, "offset": 6})
    assert resp.status_code == 200, resp.text
    assert item_ids(resp) == d_env.rows(2, 1)
    assert resp.json()["total"] == 8

    resp = d_env.get(URL_LIST, {"limit": 3, "offset": 8})
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 8


# --------------------------------------------------------------------------- CA-04


@pytest.mark.db
def test_ca04_invalid_parameters_are_422(d_env: DEnv) -> None:
    raw_queries = (
        "limit=0",
        "limit=501",
        "offset=-1",
        "object_type=bolt",
        "grade=bad",
        "source=test",
        "device_id=Edge_01",
        "lot_id=L%20A",
        "from=2026-10-01T10:00:00",
        "from=2026-10-01T12:00:00Z&to=2026-10-01T11:00:00Z",
    )
    for query in raw_queries:
        resp = d_env.client.get(f"{URL_LIST}?{query}", headers=READ)
        assert resp.status_code == 422, (query, resp.text)
        assert "Traceback" not in resp.text
    resp = d_env.get(URL_LIST, {"limit": 500})
    assert resp.status_code == 200, resp.text
    assert resp.json()["limit"] == 500
    assert len(resp.json()["items"]) == 8


# --------------------------------------------------------------------------- CA-05


@pytest.mark.db
def test_ca05_listing_filters(d_env: DEnv) -> None:
    def listing(params: dict[str, Any]) -> Any:
        resp = d_env.get(URL_LIST, params)
        assert resp.status_code == 200, (params, resp.text)
        return resp

    assert listing({"source": "live"}).json()["total"] == 6
    assert listing({"lot_id": "L-A"}).json()["total"] == 4
    resp = listing({"grade": "poor"})
    assert item_ids(resp) == d_env.rows(7, 3)
    assert resp.json()["total"] == 2
    assert listing({"defective": "true"}).json()["total"] == 3
    assert listing({"device_id": "sim-01"}).json()["total"] == 2
    resp = listing({"object_type": "unknown", "grade": "poor"})
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []
    resp = listing({"from": "2026-10-01T11:00:00Z", "to": "2026-10-01T12:00:00Z"})
    assert item_ids(resp) == d_env.rows(6, 5)
    assert resp.json()["total"] == 2


# --------------------------------------------------------------------------- CA-06


@pytest.mark.db
def test_ca06_summary_without_filters(d_env: DEnv) -> None:
    resp = d_env.get(URL_SUMMARY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    MetricsSummary.model_validate(body)
    assert body["total"] == 8
    assert body["defective"] == 3
    assert body["unknown_count"] == 1
    assert body["needs_review_count"] == 2
    assert body["defect_rate"] == approx(3 / 7)
    assert body["by_grade"] == {"perfect": 1, "good": 2, "fair": 1, "poor": 2, "unusable": 1}
    # SPEC-016 section 4.1: every ObjectType key (the 5 hand tools too), 0 when absent.
    assert body["by_object_type"] == {o.value: 0 for o in ObjectType} | {
        "screw": 4,
        "nut": 3,
        "unknown": 1,
    }
    assert body["mean_type_confidence"] == approx(0.8225)
    assert body["mean_grade_score"] == approx(14.4 / 7)


# --------------------------------------------------------------------------- CA-07


@pytest.mark.db
def test_ca07_summary_filtered_by_source_and_lot(d_env: DEnv) -> None:
    live = d_env.get(URL_SUMMARY, {"source": "live"}).json()
    assert live["total"] == 6
    assert live["defective"] == 2
    assert live["unknown_count"] == 1
    assert live["defect_rate"] == approx(0.4)
    assert live["mean_type_confidence"] == approx(4.6 / 6)
    assert live["mean_grade_score"] == approx(2.04)

    sim = d_env.get(URL_SUMMARY, {"source": "simulated"}).json()
    assert sim["total"] == 2
    assert sim["defective"] == 1
    assert sim["defect_rate"] == approx(0.5)

    lot_a = d_env.get(URL_SUMMARY, {"lot_id": "L-A"}).json()
    assert lot_a["defect_rate"] == approx(1 / 3)


# --------------------------------------------------------------------------- CA-08


@pytest.mark.db
def test_ca08_summary_without_rows(d_env: DEnv) -> None:
    resp = d_env.get(URL_SUMMARY, {"lot_id": "L-ZZZ"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["defective"] == 0
    assert body["defect_rate"] is None
    assert body["mean_type_confidence"] is None
    assert body["mean_grade_score"] is None
    assert body["by_grade"] == {g.value: 0 for g in Grade}
    assert len(body["by_grade"]) == 5
    assert body["by_object_type"] == {o.value: 0 for o in ObjectType}
    assert len(body["by_object_type"]) == 3 + 5  # SPEC-016 section 4.1: plus the 5 hand tools


# --------------------------------------------------------------------------- CA-09


@pytest.mark.db
def test_ca09_summary_only_unknown_has_null_rate(d_env: DEnv) -> None:
    resp = d_env.get(URL_SUMMARY, {"object_type": "unknown"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["defective"] == 0
    assert body["defect_rate"] is None
    assert body["mean_grade_score"] is None
    assert body["mean_type_confidence"] == approx(0.40)


# --------------------------------------------------------------------------- CA-10


@pytest.mark.db
def test_ca10_timeseries_hour_day_minute(d_env: DEnv) -> None:
    resp = d_env.get(URL_SERIES, {"bucket": "hour"})
    assert resp.status_code == 200, resp.text
    for point in resp.json():
        TimeseriesPoint.model_validate(point)
    points = series(resp)
    assert [p[0] for p in points] == [
        datetime(2026, 10, 1, 10, tzinfo=UTC),
        datetime(2026, 10, 1, 11, tzinfo=UTC),
        datetime(2026, 10, 1, 12, tzinfo=UTC),
    ]
    assert [(p[1], p[2]) for p in points] == [(4, 1), (2, 1), (2, 1)]
    assert points[0][3] == approx(1 / 3)
    assert points[1][3] == approx(0.5)
    assert points[2][3] == approx(0.5)

    day = series(d_env.get(URL_SERIES, {"bucket": "day"}))
    assert len(day) == 1
    assert day[0][0] == datetime(2026, 10, 1, tzinfo=UTC)
    assert (day[0][1], day[0][2]) == (8, 3)
    assert day[0][3] == approx(3 / 7)

    minute = series(d_env.get(URL_SERIES, {"bucket": "minute"}))
    assert len(minute) == 8
    assert [p[0] for p in minute] == sorted(p[0] for p in minute)


# --------------------------------------------------------------------------- CA-11


@pytest.mark.db
def test_ca11_day_bucket_is_utc_not_local(d_env: DEnv) -> None:
    local = datetime.fromisoformat("2026-10-01T23:30:00-03:00")
    with connect(d_env.db) as conn:
        insert_row(
            conn,
            device="edge-01",
            lot="L-C",
            source="live",
            object_type="screw",
            grade="good",
            grade_score=1.0,
            type_confidence=0.9,
            needs_review=False,
            inspected_at=local,
        )
    resp = d_env.get(URL_SERIES, {"bucket": "day", "lot_id": "L-C"})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1
    assert resp.json()[0]["bucket_start"] in ("2026-10-02T00:00:00Z", "2026-10-02T00:00:00+00:00")
    assert parse_utc(resp.json()[0]["bucket_start"]) == datetime(2026, 10, 2, tzinfo=UTC)


# --------------------------------------------------------------------------- CA-12


@pytest.mark.db
def test_ca12_invalid_bucket_and_injection_attempt(d_env: DEnv) -> None:
    for bucket in ("week", "hour;drop table inspections"):
        resp = d_env.get(URL_SERIES, {"bucket": bucket})
        assert resp.status_code == 422, (bucket, resp.text)
    assert count_rows(d_env.db) == 8

    points = series(d_env.get(URL_SERIES, {"bucket": "hour", "source": "simulated"}))
    assert len(points) == 1
    assert points[0][0] == datetime(2026, 10, 1, 12, tzinfo=UTC)
    assert points[0][1] == 2


# --------------------------------------------------------------------------- CA-13

BULK_INSERT = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
)
select gen_random_uuid(), 'edge-01', 'L-BULK',
       %(start)s::timestamptz + make_interval(mins => g),
       'screw', 'good', 1.0, 0.9, 0.9, false, 'partqc-mnv3-v1', %(sha)s, 42, 'live'
from generate_series(0, %(n)s - 1) as g
"""


def bulk_insert(conninfo: str, n: int, start: datetime) -> None:
    with connect(conninfo) as conn:
        conn.execute(BULK_INSERT, {"start": start, "sha": SHA, "n": n})


@pytest.mark.db
def test_ca13_more_than_5000_buckets_is_422(empty_env: DEnv) -> None:
    bulk_insert(empty_env.db, 5001, datetime(2026, 9, 1, tzinfo=UTC))
    assert count_rows(empty_env.db) == 5001
    resp = empty_env.get(URL_SERIES, {"bucket": "minute"})
    assert resp.status_code == 422, resp.text[:300]
    assert resp.json() == TOO_MANY_BUCKETS
    resp = empty_env.get(URL_SERIES, {"bucket": "day"})
    assert resp.status_code == 200, resp.text[:300]
    assert sum(p["total"] for p in resp.json()) == 5001


# --------------------------------------------------------------------------- CA-14


@pytest.mark.db
def test_ca14_lots_listing(d_env: DEnv) -> None:
    resp = d_env.get(URL_LOTS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    Page[LotSummary].model_validate(body)
    assert body["total"] == 3
    assert [lot["lot_id"] for lot in body["items"]] == ["L-S", "L-B", "L-A"]
    lots = {lot["lot_id"]: lot for lot in body["items"]}
    lot_a = lots["L-A"]
    assert lot_a["n"] == 4
    assert lot_a["defects"] == 1
    assert lot_a["unknown_count"] == 1
    assert parse_utc(lot_a["started_at"]) == datetime(2026, 10, 1, 10, 5, tzinfo=UTC)
    assert parse_utc(lot_a["ended_at"]) == datetime(2026, 10, 1, 10, 50, tzinfo=UTC)
    assert lot_a["sources"] == ["live"]
    lot_s = lots["L-S"]
    assert lot_s["n"] == 2
    assert lot_s["defects"] == 1
    assert lot_s["sources"] == ["simulated"]


# --------------------------------------------------------------------------- CA-15


@pytest.mark.db
def test_ca15_lot_with_two_sources(d_env: DEnv) -> None:
    with connect(d_env.db) as conn:
        insert_row(
            conn,
            device="sim-01",
            lot="L-A",
            source="simulated",
            object_type="screw",
            grade="good",
            grade_score=1.0,
            type_confidence=0.9,
            needs_review=False,
            inspected_at=T0 + timedelta(minutes=30),
        )
    body = d_env.get(URL_LOTS, {"lot_id": "L-A"}).json()
    assert body["total"] == 1
    assert body["items"][0]["sources"] == ["live", "simulated"]
    assert body["items"][0]["n"] == 5

    body = d_env.get(URL_LOTS, {"source": "live", "lot_id": "L-A"}).json()
    assert body["items"][0]["n"] == 4
    assert body["items"][0]["sources"] == ["live"]


# --------------------------------------------------------------------------- CA-16


@pytest.mark.db
def test_ca16_lots_pagination(d_env: DEnv) -> None:
    resp = d_env.get(URL_LOTS, {"limit": 1, "offset": 1})
    assert resp.status_code == 200, resp.text
    assert [lot["lot_id"] for lot in resp.json()["items"]] == ["L-B"]
    assert resp.json()["total"] == 3
    assert d_env.get(URL_LOTS, {"limit": 501}).status_code == 422


# --------------------------------------------------------------------------- CA-17


def test_ca17_database_unavailable_is_503() -> None:
    app = create_app(Settings(DATABASE_URL=no_db_url(), READ_API_KEY=R))
    with TestClient(app) as client:
        for url in READ_URLS:
            resp = client.get(url, headers=READ)
            assert resp.status_code == 503, (url, resp.text)
            assert resp.json() == DB_DOWN, url


# --------------------------------------------------------------------------- CA-18


@pytest.mark.db
def test_ca18_unknown_query_parameters_are_ignored(d_env: DEnv) -> None:
    resp = d_env.get(URL_LIST, {"lot_id": "L-A", "foo": "bar"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 4


# --------------------------------------------------------------------------- CA-19

SQL_WORDS = re.compile(r"\b(select|where|insert)\b", re.IGNORECASE)


def _string_constants(tree: ast.AST) -> dict[str, str]:
    """Names bound to string literals anywhere in the module (module, class or function)."""
    consts: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        consts[target.id] = node.value.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            consts[node.target.id] = node.value.value
    return consts


def _text_of(node: ast.AST, consts: dict[str, str]) -> str | None:
    """Literal text of a string expression (constant, known name, f-string or ``+``)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _text_of(node.left, consts)
        right = _text_of(node.right, consts)
        if left is not None or right is not None:
            return (left or "") + (right or "")
    return None


def sql_formatting_findings(source: str) -> list[int]:
    """Lines where SQL text is formatted as a Python string (f-string, ``%`` or ``.format``)."""
    tree = ast.parse(source)
    consts = _string_constants(tree)
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and any(
            not isinstance(v, ast.Constant) for v in node.values
        ):
            text = _text_of(node, consts) or ""
            if SQL_WORDS.search(text):
                lines.append(node.lineno)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            text = _text_of(node.left, consts) or ""
            if SQL_WORDS.search(text):
                lines.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"
        ):
            # sql.SQL(...).format(...) has a Call as receiver: _text_of returns None.
            text = _text_of(node.func.value, consts) or ""
            if SQL_WORDS.search(text):
                lines.append(node.lineno)
    return sorted(set(lines))


def test_ca19_sql_is_never_formatted_as_a_python_string() -> None:
    # Self-check: the scanner flags the three forbidden forms and accepts psycopg.sql.
    probe = (
        "from psycopg import sql\n"
        "Q = 'select * from t where a = {}'\n"
        "a = f'select * from t where x = {v}'\n"
        "b = 'insert into t values (%s)' % v\n"
        "c = Q.format(v)\n"
        "d = sql.SQL('select * from t where {w}').format(w=sql.SQL('true'))\n"
        "e = sql.SQL(Q).format(sql.Literal(1))\n"
        "f = 'nothing here {}'.format(v)\n"
    )
    assert sql_formatting_findings(probe) == [3, 4, 5]

    files = sorted(API_SRC.rglob("*.py"))
    assert files, API_SRC
    findings = {
        str(path.relative_to(ROOT)): lines
        for path in files
        if (lines := sql_formatting_findings(path.read_text(encoding="utf-8")))
    }
    assert findings == {}


# --------------------------------------------------------------------------- CA-20


def ca20_payload(inspection_id: str, **overrides: Any) -> dict[str, Any]:
    """``P(id)`` of SPEC-004 section 5: valid ``InspectionCreate`` for ``edge-01``."""
    body: dict[str, Any] = {
        "inspection_id": inspection_id,
        "device_id": "edge-01",
        "lot_id": "L-001",
        "inspected_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        "object_type": "screw",
        "grade": "fair",
        "grade_score": 2.0,
        "type_confidence": 0.97,
        "grade_confidence": 0.81,
        "needs_review": False,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "latency_ms": 42,
        "source": "live",
    }
    body.update(overrides)
    return body


MARK_LOT = "L-INTEG-MARK"


@pytest.fixture
def marker_constraint(clean_db: str) -> Iterator[str]:
    with connect(clean_db) as conn:
        conn.execute("alter table inspections drop constraint if exists ca20_marker")
        conn.execute(
            "alter table inspections add constraint ca20_marker check (lot_id <> 'L-INTEG-MARK')"
        )
    try:
        yield clean_db
    finally:
        with connect(clean_db) as conn:
            conn.execute("alter table inspections drop constraint if exists ca20_marker")


def last_seen(conninfo: str, device_id: str) -> datetime | None:
    with connect(conninfo) as conn:
        row = conn.execute(
            "select last_seen_at from devices where device_id = %s", (device_id,)
        ).fetchone()
    assert row is not None
    return row[0]


@pytest.mark.db
def test_ca20_integrity_error_is_422_without_values_in_log(
    marker_constraint: str, caplog: pytest.LogCaptureFixture
) -> None:
    db = marker_constraint
    keys = setup_devices(db)
    ke = keys["edge-01"]
    assert last_seen(db, "edge-01") is None
    app = create_app(Settings(DATABASE_URL=db, READ_API_KEY=R, LOG_LEVEL="DEBUG"))
    x, a, b = (str(uuid.uuid4()) for _ in range(3))
    with TestClient(app) as client:
        caplog.set_level(logging.DEBUG)
        single = client.post(
            URL_LIST, json=ca20_payload(x, lot_id=MARK_LOT), headers=key_header(ke)
        )
        batch = client.post(
            URL_BATCH,
            json={"items": [ca20_payload(a), ca20_payload(b, lot_id=MARK_LOT)]},
            headers=key_header(ke),
        )
    for resp in (single, batch):
        assert resp.status_code == 422, resp.text
        assert resp.json() == CANNOT_STORE
        assert MARK_LOT not in resp.text
    assert count_rows(db) == 0
    assert last_seen(db, "edge-01") is None
    assert caplog.records, "nothing was logged: the checks below would be vacuous"
    assert any("sqlstate=23514" in rec.getMessage() for rec in caplog.records)
    assert MARK_LOT not in log_text(caplog)


# --------------------------------------------------------------------------- CA-21


def test_ca21_generic_500_hides_database_messages(caplog: pytest.LogCaptureFixture) -> None:
    import psycopg.errors as pe

    m1, m2, m3 = (f"mk{i}-" + secrets.token_hex(8) for i in (1, 2, 3))

    def undefined_table() -> None:
        raise pe.UndefinedTable(m1)

    def wrapped_check() -> None:
        raise RuntimeError("wrapper") from pe.CheckViolation(m2)

    def plain_value_error() -> None:
        raise ValueError(m3)

    app = create_app(Settings(DATABASE_URL=no_db_url(), READ_API_KEY=R))
    app.add_api_route("/ca21/undefined-table", undefined_table, methods=["GET"])
    app.add_api_route("/ca21/wrapped-check", wrapped_check, methods=["GET"])
    app.add_api_route("/ca21/value-error", plain_value_error, methods=["GET"])

    with TestClient(app, raise_server_exceptions=False) as client:
        caplog.set_level(logging.DEBUG)
        for path, sqlstate in (
            ("/ca21/undefined-table", "42P01"),
            ("/ca21/wrapped-check", "23514"),
        ):
            caplog.clear()
            resp = client.get(path)
            assert resp.status_code == 500, (path, resp.text)
            assert resp.json() == INTERNAL
            errors = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert any(f"sqlstate={sqlstate}" in r.getMessage() for r in errors), (
                path,
                [r.getMessage() for r in caplog.records],
            )
            text = log_text(caplog)
            assert m1 not in text, path
            assert m2 not in text, path
            assert not [r for r in caplog.records if r.exc_info], path
            assert m1 not in resp.text and m2 not in resp.text

        caplog.clear()
        resp = client.get("/ca21/value-error")
        assert resp.status_code == 500, resp.text
        assert resp.json() == INTERNAL
        assert [r for r in caplog.records if r.exc_info], "non-database errors keep exc_info"


# =========================================================================== exploratory


@pytest.mark.db
def test_extra_read_key_cannot_write(d_env: DEnv) -> None:
    body = ca20_payload(str(uuid.uuid4()))
    resp = d_env.client.post(URL_LIST, json=body, headers=READ)
    assert resp.status_code == 401, resp.text
    assert resp.json() == UNAUTHORIZED
    resp = d_env.client.post(URL_BATCH, json={"items": [body]}, headers=READ)
    assert resp.status_code == 401, resp.text
    assert count_rows(d_env.db) == 8


@pytest.mark.db
def test_extra_other_bad_keys_on_read_routes(d_env: DEnv) -> None:
    bad_keys = (
        "",
        " " + R,
        R + " ",
        R.upper(),
        R[:-1],
        R + "r",
        d_env.keys["sim-01"],
        hashlib.sha256(d_env.keys["edge-01"].encode()).hexdigest(),
    )
    for url in READ_URLS:
        for key in bad_keys:
            resp = d_env.client.get(url, headers={"X-API-Key": key})
            assert resp.status_code == 401, (url, repr(key)[:12], resp.text)
            assert resp.json() == UNAUTHORIZED
    # header name is case-insensitive in HTTP
    assert d_env.client.get(URL_LIST, headers={"x-api-key": R}).status_code == 200


@pytest.mark.db
def test_extra_missing_key_wins_over_invalid_params(d_env: DEnv) -> None:
    for url in READ_URLS:
        resp = d_env.client.get(f"{url}?limit=0&source=test&bucket=week")
        assert resp.status_code == 401, (url, resp.text)


@pytest.mark.db
@pytest.mark.parametrize("offset", [9, 10**6, 2**31, 2**63 - 1, 2**63, 2**64, 10**40])
def test_extra_huge_offsets_are_empty_pages(d_env: DEnv, offset: int) -> None:
    for url in (URL_LIST, URL_LOTS):
        resp = d_env.get(url, {"offset": offset})
        assert resp.status_code == 200, (url, offset, resp.text)
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == (8 if url == URL_LIST else 3)
        assert body["offset"] == offset


@pytest.mark.db
def test_extra_non_integer_paging_is_422(d_env: DEnv) -> None:
    for query in ("limit=abc", "limit=1.5", "offset=1e3", "limit=", "offset=x", "limit=-5"):
        for url in (URL_LIST, URL_LOTS):
            resp = d_env.client.get(f"{url}?{query}", headers=READ)
            assert resp.status_code == 422, (url, query, resp.text)


@pytest.mark.db
def test_extra_default_paging(d_env: DEnv) -> None:
    for url in (URL_LIST, URL_LOTS):
        body = d_env.get(url).json()
        assert body["limit"] == 50
        assert body["offset"] == 0


@pytest.mark.db
def test_extra_from_inclusive_to_exclusive_bounds(d_env: DEnv) -> None:
    exact = (T0 + timedelta(minutes=5)).isoformat()
    resp = d_env.get(URL_LIST, {"from": exact})
    assert resp.json()["total"] == 8
    resp = d_env.get(URL_LIST, {"to": exact})
    assert resp.json()["total"] == 0
    resp = d_env.get(URL_LIST, {"to": (T0 + timedelta(minutes=5, microseconds=1)).isoformat()})
    assert item_ids(resp) == d_env.rows(1)


@pytest.mark.db
def test_extra_offsets_other_than_utc_are_normalized(d_env: DEnv) -> None:
    # 11:00Z..12:00Z written as -03:00 and +14:00
    for start, end in (
        ("2026-10-01T08:00:00-03:00", "2026-10-01T09:00:00-03:00"),
        ("2026-10-02T01:00:00+14:00", "2026-10-02T02:00:00+14:00"),
    ):
        resp = d_env.get(URL_LIST, {"from": start, "to": end})
        assert resp.status_code == 200, resp.text
        assert item_ids(resp) == d_env.rows(6, 5)
        resp = d_env.get(URL_SUMMARY, {"from": start, "to": end})
        assert resp.json()["total"] == 2


@pytest.mark.db
def test_extra_bad_datetimes_are_422(d_env: DEnv) -> None:
    bad = (
        "from=2026-10-01T10:00:00Z&to=2026-10-01T10:00:00Z",  # from == to
        "to=2026-10-01",  # date only, no tz
        "from=yesterday",
        "from=2026-13-01T00:00:00Z",
        "from=0001-01-01T00:00:00%2B14:00",  # leaves the datetime range in UTC
        "to=9999-12-31T23:59:59-14:00",
        "from=2026-10-01T10:00:00%2B25:00",
    )
    for url in READ_URLS:
        for query in bad:
            resp = d_env.client.get(f"{url}?{query}", headers=READ)
            assert resp.status_code == 422, (url, query, resp.status_code, resp.text[:200])


@pytest.mark.db
def test_extra_extreme_but_valid_datetimes(d_env: DEnv) -> None:
    params = {"from": "0001-01-01T00:00:00Z", "to": "9999-12-31T23:59:59Z"}
    for url in READ_URLS:
        resp = d_env.get(url, params)
        assert resp.status_code == 200, (url, resp.text[:200])
    assert d_env.get(URL_LIST, params).json()["total"] == 8


@pytest.mark.db
def test_extra_injection_and_unicode_in_filters_are_422(d_env: DEnv) -> None:
    bad = (
        {"lot_id": "L-A' or '1'='1"},
        {"lot_id": "L-ção"},
        {"lot_id": "a" * 41},
        {"lot_id": ""},
        {"lot_id": "L-A\n"},
        {"device_id": "edge-01\n"},
        {"device_id": "edge-01' --"},
        {"device_id": "ed"},
        {"grade": "POOR"},
        {"object_type": "Screw"},
        {"source": "LIVE"},
        {"defective": "maybe"},
    )
    for url in READ_URLS:
        for params in bad:
            resp = d_env.get(url, params)
            assert resp.status_code == 422, (url, params, resp.text[:200])
    assert count_rows(d_env.db) == 8


@pytest.mark.db
def test_extra_max_length_ids_are_accepted(d_env: DEnv) -> None:
    assert d_env.get(URL_LIST, {"lot_id": "a" * 40}).json()["total"] == 0
    assert d_env.get(URL_LIST, {"device_id": "a" * 32}).json()["total"] == 0


@pytest.mark.db
def test_extra_defective_false_and_grade_excludes_null(d_env: DEnv) -> None:
    assert d_env.get(URL_LIST, {"defective": "false"}).json()["total"] == 5
    by_grade = {g.value: d_env.get(URL_LIST, {"grade": g.value}).json()["total"] for g in Grade}
    assert by_grade == {"perfect": 1, "good": 2, "fair": 1, "poor": 2, "unusable": 1}
    assert sum(by_grade.values()) == 7  # the unknown row (#4) has no grade


@pytest.mark.db
def test_extra_unknown_is_listed_and_not_defective(d_env: DEnv) -> None:
    resp = d_env.get(URL_LIST, {"object_type": "unknown"})
    items = resp.json()["items"]
    assert [i["inspection_id"] for i in items] == d_env.rows(4)
    assert items[0]["grade"] is None
    assert items[0]["grade_score"] is None
    assert items[0]["is_defective"] is False


@pytest.mark.db
def test_extra_r06_source_visible_everywhere(d_env: DEnv) -> None:
    items = d_env.get(URL_LIST).json()["items"]
    sources = {i["inspection_id"]: i["source"] for i in items}
    assert {sources[d_env.ids[n]] for n in (7, 8)} == {"simulated"}
    assert {sources[d_env.ids[n]] for n in range(1, 7)} == {"live"}
    # summary/timeseries without `source` mix both origins; with it, only that origin
    assert d_env.get(URL_SUMMARY).json()["total"] == 8
    assert d_env.get(URL_SUMMARY, {"source": "live"}).json()["total"] == 6


@pytest.mark.db
def test_extra_combined_filters_are_and(d_env: DEnv) -> None:
    resp = d_env.get(
        URL_LIST,
        {"lot_id": "L-A", "defective": "false", "source": "live", "object_type": "screw"},
    )
    assert item_ids(resp) == d_env.rows(2, 1)
    lots = d_env.get(URL_LOTS, {"device_id": "edge-01"}).json()
    assert [lot["lot_id"] for lot in lots["items"]] == ["L-B", "L-A"]
    assert lots["total"] == 2
    lots = d_env.get(URL_LOTS, {"defective": "true"}).json()
    assert {lot["lot_id"]: lot["n"] for lot in lots["items"]} == {"L-S": 1, "L-B": 1, "L-A": 1}


@pytest.mark.db
def test_extra_stable_order_on_equal_timestamps(empty_env: DEnv) -> None:
    ids = sorted(str(uuid.uuid4()) for _ in range(6))
    with connect(empty_env.db) as conn:
        for iid in reversed(ids):
            insert_row(
                conn,
                device="edge-01",
                lot="L-T",
                source="live",
                object_type="nut",
                grade="good",
                grade_score=1.0,
                type_confidence=0.9,
                needs_review=False,
                inspected_at=T0,
                inspection_id=iid,
            )
    pages = [item_ids(empty_env.get(URL_LIST, {"limit": 2, "offset": off})) for off in (0, 2, 4)]
    assert [i for page in pages for i in page] == ids


@pytest.mark.db
def test_extra_lot_ties_ordered_by_lot_id(empty_env: DEnv) -> None:
    with connect(empty_env.db) as conn:
        for lot in ("L-Z", "L-M", "L-A"):
            insert_row(
                conn,
                device="edge-01",
                lot=lot,
                source="live",
                object_type="nut",
                grade="good",
                grade_score=1.0,
                type_confidence=0.9,
                needs_review=False,
                inspected_at=T0,
            )
    lots = empty_env.get(URL_LOTS).json()["items"]
    assert [lot["lot_id"] for lot in lots] == ["L-A", "L-M", "L-Z"]


@pytest.mark.db
def test_extra_empty_database(empty_env: DEnv) -> None:
    body = empty_env.get(URL_LIST).json()
    assert (body["items"], body["total"]) == ([], 0)
    body = empty_env.get(URL_LOTS).json()
    assert (body["items"], body["total"]) == ([], 0)
    assert empty_env.get(URL_SERIES).json() == []
    summary = empty_env.get(URL_SUMMARY).json()
    assert summary["total"] == 0
    assert summary["defect_rate"] is None


@pytest.mark.db
def test_extra_timeseries_default_bucket_is_hour(d_env: DEnv) -> None:
    assert d_env.get(URL_SERIES).json() == d_env.get(URL_SERIES, {"bucket": "hour"}).json()


@pytest.mark.db
def test_extra_timeseries_bucket_values_are_exact(d_env: DEnv) -> None:
    for bucket in ("Hour", "HOUR", " hour", "hour ", "", "hours", "second", "month", "'hour'"):
        resp = d_env.get(URL_SERIES, {"bucket": bucket})
        assert resp.status_code == 422, (bucket, resp.text[:200])


@pytest.mark.db
def test_extra_timeseries_unknown_only_bucket_has_null_rate(d_env: DEnv) -> None:
    resp = d_env.get(URL_SERIES, {"bucket": "minute", "object_type": "unknown"})
    points = series(resp)
    assert len(points) == 1
    assert points[0][0] == datetime(2026, 10, 1, 10, 50, tzinfo=UTC)
    assert (points[0][1], points[0][2], points[0][3]) == (1, 0, None)


@pytest.mark.db
def test_extra_timeseries_sums_match_summary(d_env: DEnv) -> None:
    for params in ({}, {"source": "live"}, {"lot_id": "L-B"}, {"defective": "true"}):
        summary = d_env.get(URL_SUMMARY, params).json()
        for bucket in ("minute", "hour", "day"):
            points = d_env.get(URL_SERIES, {**params, "bucket": bucket}).json()
            assert sum(p["total"] for p in points) == summary["total"], (params, bucket)
            assert sum(p["defective"] for p in points) == summary["defective"]


@pytest.mark.db
def test_extra_bucket_limit_boundary_5000_is_ok(empty_env: DEnv) -> None:
    bulk_insert(empty_env.db, 5000, datetime(2026, 9, 1, tzinfo=UTC))
    resp = empty_env.get(URL_SERIES, {"bucket": "minute"})
    assert resp.status_code == 200, resp.text[:300]
    assert len(resp.json()) == 5000


@pytest.mark.db
def test_extra_bucket_limit_respects_filters(empty_env: DEnv) -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    bulk_insert(empty_env.db, 6000, start)
    resp = empty_env.get(URL_SERIES, {"bucket": "minute"})
    assert resp.status_code == 422
    assert resp.json() == TOO_MANY_BUCKETS
    params = {
        "bucket": "minute",
        "from": start.isoformat(),
        "to": (start + timedelta(minutes=100)).isoformat(),
    }
    resp = empty_env.get(URL_SERIES, params)
    assert resp.status_code == 200, resp.text[:300]
    assert len(resp.json()) == 100
    assert empty_env.get(URL_SERIES, {"bucket": "hour"}).status_code == 200


@pytest.mark.db
@pytest.mark.parametrize("tz", ["America/Sao_Paulo", "Pacific/Kiritimati", "Asia/Kathmandu"])
def test_extra_buckets_are_utc_whatever_the_session_timezone(clean_db: str, tz: str) -> None:
    setup_devices(clean_db)
    with connect(clean_db) as conn:
        insert_d(conn)
        insert_row(
            conn,
            device="edge-01",
            lot="L-C",
            source="live",
            object_type="screw",
            grade="good",
            grade_score=1.0,
            type_confidence=0.9,
            needs_review=False,
            inspected_at=datetime.fromisoformat("2026-10-01T23:30:00-03:00"),
        )
    conninfo = make_conninfo(clean_db, options=f"-c TimeZone={tz}")
    app = create_app(Settings(DATABASE_URL=conninfo, READ_API_KEY=R))
    with TestClient(app) as client:
        day = client.get(URL_SERIES, params={"bucket": "day", "lot_id": "L-C"}, headers=READ)
        assert [parse_utc(p["bucket_start"]) for p in day.json()] == [
            datetime(2026, 10, 2, tzinfo=UTC)
        ]
        hour = client.get(
            URL_SERIES, params={"bucket": "hour", "source": "simulated"}, headers=READ
        )
        assert [parse_utc(p["bucket_start"]) for p in hour.json()] == [
            datetime(2026, 10, 1, 12, tzinfo=UTC)
        ]
        lots = client.get(URL_LOTS, params={"lot_id": "L-A"}, headers=READ).json()["items"]
        assert lots[0]["started_at"] in ("2026-10-01T10:05:00Z", "2026-10-01T10:05:00+00:00")
        items = client.get(URL_LIST, params={"lot_id": "L-C"}, headers=READ).json()["items"]
        assert parse_utc(items[0]["inspected_at"]) == datetime(2026, 10, 2, 2, 30, tzinfo=UTC)


@pytest.mark.db
def test_extra_items_echo_stored_values(d_env: DEnv) -> None:
    items = {i["inspection_id"]: i for i in d_env.get(URL_LIST).json()["items"]}
    for row, device, lot, source, otype, grade, score, conf, review, minutes in D_ROWS:
        item = items[d_env.ids[row]]
        assert item["device_id"] == device
        assert item["lot_id"] == lot
        assert item["source"] == source
        assert item["object_type"] == otype
        assert item["grade"] == grade
        assert item["needs_review"] is review
        assert item["type_confidence"] == approx(conf)
        if score is None:
            assert item["grade_score"] is None
        else:
            assert item["grade_score"] == approx(score)
        assert parse_utc(item["inspected_at"]) == T0 + timedelta(minutes=minutes)
        parse_utc(item["received_at"])
        assert item["is_defective"] is (grade in ("poor", "unusable"))


@pytest.mark.db
def test_extra_summary_values_are_finite_numbers(d_env: DEnv) -> None:
    body = d_env.get(URL_SUMMARY).json()
    for key in ("defect_rate", "mean_type_confidence", "mean_grade_score"):
        assert isinstance(body[key], float), key
        assert math.isfinite(body[key])
    for key in ("total", "defective", "unknown_count", "needs_review_count"):
        assert isinstance(body[key], int) and not isinstance(body[key], bool), key


@pytest.mark.db
def test_extra_read_routes_reject_other_methods(d_env: DEnv) -> None:
    for url in (URL_SUMMARY, URL_SERIES, URL_LOTS):
        for method in ("POST", "PUT", "DELETE"):
            resp = d_env.client.request(method, url, headers=READ)
            assert resp.status_code == 405, (method, url, resp.status_code)


@pytest.mark.db
def test_extra_read_database_error_is_500_without_message_in_log(
    d_env: DEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """A real psycopg error inside a read route (table renamed for the duration of the test)."""
    caplog.set_level(logging.DEBUG)
    with connect(d_env.db) as conn:
        conn.execute("alter table inspections rename to inspections_ca_extra")
    try:
        caplog.clear()
        resp = d_env.get(URL_SUMMARY)
    finally:
        with connect(d_env.db) as conn:
            conn.execute("alter table inspections_ca_extra rename to inspections")
    assert resp.status_code == 500, resp.text
    assert resp.json() == INTERNAL
    text = log_text(caplog)
    assert "does not exist" not in text
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert errors == [
        "unhandled database error: route=/api/v1/metrics/summary type=UndefinedTable sqlstate=42P01"
    ], errors
    assert not [r for r in caplog.records if r.exc_info]


@pytest.mark.db
def test_extra_reads_do_not_write(d_env: DEnv) -> None:
    with connect(d_env.db) as conn:
        before = conn.execute("select device_id, last_seen_at from devices order by 1").fetchall()
    for url in READ_URLS:
        d_env.get(url)
    with connect(d_env.db) as conn:
        after = conn.execute("select device_id, last_seen_at from devices order by 1").fetchall()
    assert before == after
    assert count_rows(d_env.db) == 8


def test_extra_database_error_log_line_format(caplog: pytest.LogCaptureFixture) -> None:
    """Section 4.5 item 2: route template, class of the first psycopg error, SQLSTATE or ``-``."""
    import psycopg.errors as pe

    marker = "mk-" + secrets.token_hex(8)

    def no_sqlstate() -> None:
        raise psycopg.Error(marker)

    def in_context() -> None:
        try:
            raise pe.UniqueViolation(marker)
        except pe.UniqueViolation:
            raise KeyError("while handling") from None

    def item_route(item_id: int) -> None:
        raise pe.NumericValueOutOfRange(marker + str(item_id))

    app = create_app(Settings(DATABASE_URL=no_db_url(), READ_API_KEY=R))
    app.add_api_route("/x/no-sqlstate", no_sqlstate, methods=["GET"])
    app.add_api_route("/x/in-context", in_context, methods=["GET"])
    app.add_api_route("/x/items/{item_id}", item_route, methods=["GET"])
    expected = {
        "/x/no-sqlstate": "route=/x/no-sqlstate type=Error sqlstate=-",
        "/x/in-context": "route=/x/in-context type=UniqueViolation sqlstate=23505",
        "/x/items/7": "route=/x/items/{item_id} type=NumericValueOutOfRange sqlstate=22003",
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        caplog.set_level(logging.DEBUG)
        for path, tail in expected.items():
            caplog.clear()
            resp = client.get(path)
            assert resp.status_code == 500, path
            assert resp.json() == INTERNAL
            errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
            assert errors == [f"unhandled database error: {tail}"], (path, errors)
            assert marker not in log_text(caplog), path
            assert not [r for r in caplog.records if r.exc_info], path


@pytest.fixture
def strict_devices(clean_db: str) -> Iterator[str]:
    """A ``devices`` check that refuses any ``last_seen_at``: the ``update devices`` fails."""
    with connect(clean_db) as conn:
        conn.execute("alter table devices drop constraint if exists extra_no_last_seen")
    keys = setup_devices(clean_db)
    with connect(clean_db) as conn:
        conn.execute(
            "alter table devices add constraint extra_no_last_seen check (last_seen_at is null)"
        )
    try:
        yield keys["edge-01"]
    finally:
        with connect(clean_db) as conn:
            conn.execute("alter table devices drop constraint if exists extra_no_last_seen")


@pytest.mark.db
def test_extra_integrity_error_in_device_update_is_422(
    clean_db: str, strict_devices: str, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(Settings(DATABASE_URL=clean_db, READ_API_KEY=R, LOG_LEVEL="DEBUG"))
    lot = "L-DEV-" + secrets.token_hex(4)
    with TestClient(app) as client:
        caplog.set_level(logging.DEBUG)
        single = client.post(
            URL_LIST,
            json=ca20_payload(str(uuid.uuid4()), lot_id=lot),
            headers=key_header(strict_devices),
        )
        batch = client.post(
            URL_BATCH,
            json={"items": [ca20_payload(str(uuid.uuid4()), lot_id=lot)]},
            headers=key_header(strict_devices),
        )
    for resp in (single, batch):
        assert resp.status_code == 422, resp.text
        assert resp.json() == CANNOT_STORE
    assert count_rows(clean_db) == 0
    assert last_seen(clean_db, "edge-01") is None
    assert any("sqlstate=23514" in r.getMessage() for r in caplog.records)
    text = log_text(caplog)
    assert lot not in text
    assert "extra_no_last_seen" not in text
    assert "Failing row" not in text


@pytest.mark.db
def test_extra_ca20_constraint_does_not_block_other_lots(marker_constraint: str) -> None:
    """Control for CA-20: with the extra check in place, an ordinary payload is still stored."""
    keys = setup_devices(marker_constraint)
    app = create_app(Settings(DATABASE_URL=marker_constraint, READ_API_KEY=R))
    with TestClient(app) as client:
        resp = client.post(
            URL_LIST, json=ca20_payload(str(uuid.uuid4())), headers=key_header(keys["edge-01"])
        )
    assert resp.status_code == 201, resp.text
    assert count_rows(marker_constraint) == 1
    assert last_seen(marker_constraint, "edge-01") is not None
