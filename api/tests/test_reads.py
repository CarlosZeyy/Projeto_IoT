"""Read routes against the test PostgreSQL (SPEC-005 sections 4.1 to 4.4).

Dataset ``D`` of the SPEC is inserted with SQL (not through the API). All tests are marked
``db``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from qc_api.config import Settings
from qc_api.main import create_app
from qc_contracts import InspectionRead, LotSummary, MetricsSummary, TimeseriesPoint

pytestmark = pytest.mark.db

READ_KEY = "r" * 32
SHA = "a" * 64
R = {"X-API-Key": READ_KEY}
T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
INSPECTIONS = "/api/v1/inspections"
SUMMARY = "/api/v1/metrics/summary"
TIMESERIES = "/api/v1/metrics/timeseries"
LOTS = "/api/v1/lots"

# (device, lot, source, object_type, grade, grade_score, type_confidence, needs_review, minutes)
DATASET_D: list[tuple[Any, ...]] = [
    ("edge-01", "L-A", "live", "screw", "perfect", 0.2, 0.90, False, 5),
    ("edge-01", "L-A", "live", "screw", "good", 1.1, 0.80, False, 10),
    ("edge-01", "L-A", "live", "nut", "poor", 3.0, 0.70, True, 20),
    ("edge-01", "L-A", "live", "unknown", None, None, 0.40, True, 50),
    ("edge-01", "L-B", "live", "nut", "unusable", 3.9, 0.95, False, 70),
    ("edge-01", "L-B", "live", "screw", "fair", 2.0, 0.85, False, 75),
    ("sim-01", "L-S", "simulated", "screw", "poor", 3.2, 0.99, False, 120),
    ("sim-01", "L-S", "simulated", "nut", "good", 1.0, 0.99, False, 150),
]

INSERT = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'partqc-mnv3-v1', %s, 100, %s)
"""


def insert_row(
    db: psycopg.Connection,
    device: str,
    lot: str,
    source: str,
    object_type: str,
    grade: str | None,
    grade_score: float | None,
    type_confidence: float,
    needs_review: bool,
    inspected_at: datetime,
) -> str:
    inspection_id = str(uuid.uuid4())
    grade_confidence = None if grade is None else 0.7
    db.execute(
        INSERT,
        (
            inspection_id,
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
    return inspection_id


@pytest.fixture
def dataset(device_keys: dict[str, str], db: psycopg.Connection) -> dict[int, str]:
    """Dataset D; returns ``{row number: inspection_id}``."""
    ids: dict[int, str] = {}
    for number, row in enumerate(DATASET_D, start=1):
        *fields, minutes = row
        ids[number] = insert_row(db, *fields, T0 + timedelta(minutes=minutes))
    return ids


@pytest.fixture
def reader(clean_db: str, dataset: dict[int, str], settings_for) -> Iterator[TestClient]:
    with TestClient(create_app(settings_for(clean_db))) as test_client:
        yield test_client


def _ids(response_json: dict[str, Any]) -> list[str]:
    return [item["inspection_id"] for item in response_json["items"]]


# --- authentication ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [INSPECTIONS, SUMMARY, TIMESERIES, LOTS])
def test_read_routes_need_the_read_key(reader: TestClient, device_keys, url: str) -> None:
    for headers in ({}, {"X-API-Key": "errada"}, {"X-API-Key": device_keys["edge-01"]}):
        response = reader.get(url, headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "Missing or invalid API key"}


def test_missing_key_is_401_before_validation(reader: TestClient) -> None:
    assert reader.get(INSPECTIONS, params={"limit": 0}).status_code == 401
    assert reader.get(TIMESERIES, params={"bucket": "week"}).status_code == 401


# --- listing ----------------------------------------------------------------------------------


def test_listing_first_page(reader: TestClient, dataset: dict[int, str]) -> None:
    body = reader.get(INSPECTIONS, params={"limit": 3}, headers=R).json()
    assert (body["total"], body["limit"], body["offset"]) == (8, 3, 0)
    assert _ids(body) == [dataset[8], dataset[7], dataset[6]]
    items = [InspectionRead.model_validate(item) for item in body["items"]]
    assert items[1].is_defective is True
    assert items[1].source == "simulated"
    assert body["items"][0]["inspected_at"] == "2026-10-01T12:30:00Z"


def test_listing_default_page_and_offsets(reader: TestClient, dataset: dict[int, str]) -> None:
    body = reader.get(INSPECTIONS, headers=R).json()
    assert (body["total"], body["limit"], body["offset"]) == (8, 50, 0)
    assert _ids(body) == [dataset[n] for n in range(8, 0, -1)]
    body = reader.get(INSPECTIONS, params={"limit": 3, "offset": 6}, headers=R).json()
    assert _ids(body) == [dataset[2], dataset[1]]
    assert body["total"] == 8
    body = reader.get(INSPECTIONS, params={"offset": 8}, headers=R).json()
    assert (body["items"], body["total"]) == ([], 8)


def test_listing_huge_offset_is_an_empty_page(reader: TestClient) -> None:
    offset = 10**30
    response = reader.get(INSPECTIONS, params={"offset": offset}, headers=R)
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 8, "limit": 50, "offset": offset}
    response = reader.get(LOTS, params={"offset": offset}, headers=R)
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_listing_ties_are_ordered_by_id(reader: TestClient, db: psycopg.Connection) -> None:
    at = T0 + timedelta(days=1)
    tied = sorted(
        insert_row(db, "edge-01", "L-T", "live", "screw", "good", 1.0, 0.9, False, at)
        for _ in range(4)
    )
    body = reader.get(INSPECTIONS, params={"lot_id": "L-T"}, headers=R).json()
    assert _ids(body) == tied


@pytest.mark.parametrize(
    ("params", "rows"),
    [
        ({"source": "live"}, [6, 5, 4, 3, 2, 1]),
        ({"source": "simulated"}, [8, 7]),
        ({"lot_id": "L-A"}, [4, 3, 2, 1]),
        ({"grade": "poor"}, [7, 3]),
        ({"defective": "true"}, [7, 5, 3]),
        ({"defective": "false"}, [8, 6, 4, 2, 1]),
        ({"device_id": "sim-01"}, [8, 7]),
        ({"object_type": "unknown"}, [4]),
        ({"object_type": "unknown", "grade": "poor"}, []),
        ({"from": "2026-10-01T11:00:00Z", "to": "2026-10-01T12:00:00Z"}, [6, 5]),
        ({"from": "2026-10-01T09:00:00-03:00"}, [8, 7]),
        ({"to": "2026-10-01T10:10:00Z"}, [1]),
        ({"source": "live", "object_type": "screw", "defective": "false"}, [6, 2, 1]),
        ({"lot_id": "L-A", "foo": "bar"}, [4, 3, 2, 1]),
    ],
)
def test_listing_filters(
    reader: TestClient, dataset: dict[int, str], params: dict[str, str], rows: list[int]
) -> None:
    response = reader.get(INSPECTIONS, params=params, headers=R)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(rows)
    assert _ids(body) == [dataset[n] for n in rows]


INVALID_FILTERS: list[dict[str, str]] = [
    {"object_type": "bolt"},
    {"grade": "bad"},
    {"source": "test"},
    {"device_id": "Edge_01"},
    {"device_id": "edge-01\n"},
    {"lot_id": "L A"},
    {"defective": "maybe"},
    {"from": "2026-10-01T10:00:00"},
    {"to": "2026-10-01T10:00:00"},
    {"from": "2026-10-01T12:00:00Z", "to": "2026-10-01T11:00:00Z"},
    {"from": "2026-10-01T12:00:00Z", "to": "2026-10-01T12:00:00Z"},
]
INVALID_PAGES: list[dict[str, str]] = [{"limit": "0"}, {"limit": "501"}, {"offset": "-1"}]


@pytest.mark.parametrize(
    ("url", "params"),
    [
        (url, params)
        for url in (INSPECTIONS, SUMMARY, TIMESERIES, LOTS)
        for params in INVALID_FILTERS
    ]
    + [(url, params) for url in (INSPECTIONS, LOTS) for params in INVALID_PAGES],
)
def test_invalid_parameters_are_422(reader: TestClient, url: str, params: dict[str, str]) -> None:
    response = reader.get(url, params=params, headers=R)
    assert response.status_code == 422


def test_limit_500_is_accepted(reader: TestClient) -> None:
    assert reader.get(INSPECTIONS, params={"limit": 500}, headers=R).status_code == 200
    assert reader.get(LOTS, params={"limit": 500}, headers=R).status_code == 200


# --- summary ----------------------------------------------------------------------------------


def _summary(reader: TestClient, **params: str) -> MetricsSummary:
    response = reader.get(SUMMARY, params=params, headers=R)
    assert response.status_code == 200
    return MetricsSummary.model_validate(response.json())


def test_summary_without_filters(reader: TestClient) -> None:
    summary = _summary(reader)
    assert (summary.total, summary.defective, summary.unknown_count) == (8, 3, 1)
    assert summary.needs_review_count == 2
    assert summary.defect_rate == pytest.approx(3 / 7, rel=1e-6)
    assert summary.by_grade == {"perfect": 1, "good": 2, "fair": 1, "poor": 2, "unusable": 1}
    assert summary.by_object_type == {"screw": 4, "nut": 3, "unknown": 1}
    assert summary.mean_type_confidence == pytest.approx(0.8225, rel=1e-6)
    assert summary.mean_grade_score == pytest.approx(14.4 / 7, rel=1e-6)


def test_summary_json_keys(reader: TestClient) -> None:
    body = reader.get(SUMMARY, headers=R).json()
    assert list(body["by_grade"]) == ["perfect", "good", "fair", "poor", "unusable"]
    assert list(body["by_object_type"]) == ["screw", "nut", "unknown"]


def test_summary_by_source_and_lot(reader: TestClient) -> None:
    live = _summary(reader, source="live")
    assert (live.total, live.defective, live.unknown_count) == (6, 2, 1)
    assert live.defect_rate == pytest.approx(0.4, rel=1e-6)
    assert live.mean_type_confidence == pytest.approx(4.6 / 6, rel=1e-6)
    assert live.mean_grade_score == pytest.approx(2.04, rel=1e-6)
    simulated = _summary(reader, source="simulated")
    assert (simulated.total, simulated.defective) == (2, 1)
    assert simulated.defect_rate == pytest.approx(0.5, rel=1e-6)
    assert _summary(reader, lot_id="L-A").defect_rate == pytest.approx(1 / 3, rel=1e-6)


def test_summary_without_rows(reader: TestClient) -> None:
    summary = _summary(reader, lot_id="L-ZZZ")
    assert (summary.total, summary.defective, summary.unknown_count) == (0, 0, 0)
    assert summary.needs_review_count == 0
    assert summary.defect_rate is None
    assert summary.mean_type_confidence is None
    assert summary.mean_grade_score is None
    assert summary.by_grade == dict.fromkeys(("perfect", "good", "fair", "poor", "unusable"), 0)
    assert summary.by_object_type == dict.fromkeys(("screw", "nut", "unknown"), 0)


def test_summary_only_unknown(reader: TestClient) -> None:
    summary = _summary(reader, object_type="unknown")
    assert (summary.total, summary.defective) == (1, 0)
    assert summary.defect_rate is None
    assert summary.mean_grade_score is None
    assert summary.mean_type_confidence == pytest.approx(0.40, rel=1e-6)


# --- time series ------------------------------------------------------------------------------


def _points(reader: TestClient, **params: str) -> list[TimeseriesPoint]:
    response = reader.get(TIMESERIES, params=params, headers=R)
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)
    return [TimeseriesPoint.model_validate(point) for point in response.json()]


def test_timeseries_by_hour_is_the_default(reader: TestClient) -> None:
    points = _points(reader)
    assert points == _points(reader, bucket="hour")
    assert [p.bucket_start for p in points] == [
        T0,
        T0 + timedelta(hours=1),
        T0 + timedelta(hours=2),
    ]
    assert [(p.total, p.defective) for p in points] == [(4, 1), (2, 1), (2, 1)]
    assert points[0].defect_rate == pytest.approx(1 / 3, rel=1e-6)
    assert points[1].defect_rate == pytest.approx(0.5, rel=1e-6)
    raw = reader.get(TIMESERIES, headers=R).json()
    assert raw[0]["bucket_start"] == "2026-10-01T10:00:00Z"


def test_timeseries_day_minute_and_source(reader: TestClient) -> None:
    (day,) = _points(reader, bucket="day")
    assert day.bucket_start == datetime(2026, 10, 1, tzinfo=UTC)
    assert (day.total, day.defective) == (8, 3)
    assert day.defect_rate == pytest.approx(3 / 7, rel=1e-6)
    minutes = _points(reader, bucket="minute")
    assert len(minutes) == 8
    assert [p.bucket_start for p in minutes] == sorted(p.bucket_start for p in minutes)
    (simulated,) = _points(reader, bucket="hour", source="simulated")
    assert simulated.bucket_start == T0 + timedelta(hours=2)
    assert simulated.total == 2


def test_timeseries_bucket_with_only_unknown_has_null_rate(reader: TestClient) -> None:
    (point,) = _points(reader, bucket="hour", object_type="unknown")
    assert (point.total, point.defective, point.defect_rate) == (1, 0, None)


def test_timeseries_buckets_are_utc(
    reader: TestClient, db: psycopg.Connection, clean_db: str, settings_for
) -> None:
    local = datetime.fromisoformat("2026-10-01T23:30:00-03:00")
    insert_row(db, "edge-01", "L-C", "live", "screw", "good", 1.0, 0.9, False, local)
    (point,) = _points(reader, bucket="day", lot_id="L-C")
    assert point.bucket_start == datetime(2026, 10, 2, tzinfo=UTC)
    # Even when the API session runs in another time zone, buckets are truncated in UTC.
    local_session = make_conninfo(clean_db, options="-c TimeZone=America/Sao_Paulo")
    settings: Settings = settings_for(local_session)
    with TestClient(create_app(settings)) as local_reader:
        (point,) = _points(local_reader, bucket="day", lot_id="L-C")
        raw = local_reader.get(TIMESERIES, params={"lot_id": "L-C", "bucket": "day"}, headers=R)
    assert point.bucket_start == datetime(2026, 10, 2, tzinfo=UTC)
    assert raw.json()[0]["bucket_start"] == "2026-10-02T00:00:00Z"


@pytest.mark.parametrize("bucket", ["week", "hour;drop table inspections", "HOUR", ""])
def test_timeseries_invalid_bucket(reader: TestClient, db: psycopg.Connection, bucket: str) -> None:
    response = reader.get(TIMESERIES, params={"bucket": bucket}, headers=R)
    assert response.status_code == 422
    assert db.execute("select count(*) from inspections").fetchone()[0] == 8


def test_timeseries_bucket_limit(reader: TestClient, db: psycopg.Connection) -> None:
    db.execute("truncate inspections")
    db.execute(
        """
        insert into inspections (
            inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
            type_confidence, grade_confidence, needs_review, model_version, model_sha256,
            latency_ms, source
        )
        select gen_random_uuid(), 'edge-01', 'L-MANY',
               %s::timestamptz + make_interval(mins => i), 'screw', 'good', 1.0,
               0.9, 0.7, false, 'partqc-mnv3-v1', %s, 100, 'live'
        from generate_series(0, %s) as i
        """,
        (T0, SHA, 4_999),
    )
    assert len(_points(reader, bucket="minute")) == 5_000
    insert_row(
        db,
        "edge-01",
        "L-MANY",
        "live",
        "screw",
        "good",
        1.0,
        0.9,
        False,
        T0 + timedelta(minutes=5_000),
    )
    response = reader.get(TIMESERIES, params={"bucket": "minute"}, headers=R)
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Too many buckets; narrow the time range or use a larger bucket"
    }
    assert reader.get(TIMESERIES, params={"bucket": "day"}, headers=R).status_code == 200


# --- lots -------------------------------------------------------------------------------------


def _lots(reader: TestClient, **params: Any) -> dict[str, Any]:
    response = reader.get(LOTS, params=params, headers=R)
    assert response.status_code == 200, response.text
    return response.json()


def test_lots(reader: TestClient) -> None:
    body = _lots(reader)
    assert (body["total"], body["limit"], body["offset"]) == (3, 50, 0)
    lots = {item["lot_id"]: LotSummary.model_validate(item) for item in body["items"]}
    assert [item["lot_id"] for item in body["items"]] == ["L-S", "L-B", "L-A"]
    lot_a = lots["L-A"]
    assert (lot_a.n, lot_a.defects, lot_a.unknown_count) == (4, 1, 1)
    assert lot_a.started_at == T0 + timedelta(minutes=5)
    assert lot_a.ended_at == T0 + timedelta(minutes=50)
    assert lot_a.sources == ["live"]
    assert (lots["L-S"].n, lots["L-S"].defects, lots["L-S"].sources) == (2, 1, ["simulated"])
    assert (lots["L-B"].n, lots["L-B"].defects, lots["L-B"].unknown_count) == (2, 1, 0)
    assert body["items"][2]["started_at"] == "2026-10-01T10:05:00Z"


def test_lot_sources_in_enum_order_and_filters(reader: TestClient, db: psycopg.Connection) -> None:
    at = T0 + timedelta(minutes=30)
    insert_row(db, "sim-01", "L-A", "simulated", "screw", "good", 1.0, 0.9, False, at)
    (lot,) = _lots(reader, lot_id="L-A")["items"]
    assert (lot["n"], lot["sources"]) == (5, ["live", "simulated"])
    (lot,) = _lots(reader, lot_id="L-A", source="live")["items"]
    assert (lot["n"], lot["sources"]) == (4, ["live"])


def test_lots_pagination(reader: TestClient) -> None:
    body = _lots(reader, limit=1, offset=1)
    assert [item["lot_id"] for item in body["items"]] == ["L-B"]
    assert body["total"] == 3
    body = _lots(reader, offset=3)
    assert (body["items"], body["total"]) == ([], 3)
    assert reader.get(LOTS, params={"limit": 501}, headers=R).status_code == 422


def test_lots_ties_ordered_by_lot_id(reader: TestClient, db: psycopg.Connection) -> None:
    at = T0 + timedelta(days=2)
    for lot in ("L-Z", "L-M", "L-N"):
        insert_row(db, "edge-01", lot, "live", "screw", "good", 1.0, 0.9, False, at)
    body = _lots(reader, limit=3)
    assert [item["lot_id"] for item in body["items"]] == ["L-M", "L-N", "L-Z"]
    assert body["total"] == 6
