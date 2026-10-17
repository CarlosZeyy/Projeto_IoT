"""``GET /api/v1/metrics/spc`` against the test PostgreSQL (SPEC-006 sections 4.2 and 4.4).

The lots of Example 1 are inserted with SQL (not through the API) as ``live`` screws: in each
lot, ``defects`` rows ``poor`` and the others ``good``, one minute apart. ``L-001`` also has 3
``unknown`` rows, and ``L-SIM`` is a ``simulated`` lot with ``n=10``, ``defects=9``. All tests
are marked ``db``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from qc_api.main import create_app
from qc_contracts import SpcResponse

pytestmark = pytest.mark.db

READ_KEY = "r" * 32
SHA = "a" * 64
R = {"X-API-Key": READ_KEY}
URL = "/api/v1/metrics/spc"
TOL = 5e-5
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)

# (lot_id, hours after T0, n, defects): Example 1 of SPEC-006 section 4.4.
EXAMPLE_1 = [
    ("L-001", 0, 20, 2),
    ("L-002", 1, 25, 3),
    ("L-003", 2, 4, 1),
    ("L-004", 3, 20, 4),
    ("L-005", 4, 20, 12),
    ("L-006", 5, 25, 0),
    ("L-007", 6, 100, 1),
]

# (lot_id, p, cl, ucl, lcl, out_of_control)
EXPECTED_1 = [
    ("L-001", 0.1000, 0.1385, 0.3702, 0.0000, False),
    ("L-002", 0.1200, 0.1385, 0.3457, 0.0000, False),
    ("L-004", 0.2000, 0.1385, 0.3702, 0.0000, False),
    ("L-005", 0.6000, 0.1385, 0.3702, 0.0000, True),
    ("L-006", 0.0000, 0.1385, 0.3457, 0.0000, False),
    ("L-007", 0.0100, 0.1385, 0.2421, 0.0348, True),
]

INSERT = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
)
values (%s, %s, %s, %s, %s, %s, %s, 0.9, %s, false, 'partqc-mnv3-v1', %s, 100, %s)
"""


def insert(
    db: psycopg.Connection,
    lot_id: str,
    inspected_at: datetime,
    object_type: str = "screw",
    grade: str | None = "good",
    source: str = "live",
) -> None:
    device_id = "sim-01" if source == "simulated" else "edge-01"
    score = None if grade is None else 1.0
    confidence = None if grade is None else 0.8
    db.execute(
        INSERT,
        (
            str(uuid.uuid4()),
            device_id,
            lot_id,
            inspected_at,
            object_type,
            grade,
            score,
            confidence,
            SHA,
            source,
        ),
    )


def insert_lot(
    db: psycopg.Connection,
    lot_id: str,
    start: datetime,
    n: int,
    defects: int,
    object_type: str = "screw",
    source: str = "live",
) -> None:
    """``n`` rows one minute apart from ``start``: the first ``defects`` are ``poor``."""
    for i in range(n):
        grade = "poor" if i < defects else "good"
        insert(db, lot_id, start + timedelta(minutes=i), object_type, grade, source)


@pytest.fixture
def example_db(device_keys: dict[str, str], db: psycopg.Connection) -> psycopg.Connection:
    for lot_id, hours, n, defects in EXAMPLE_1:
        insert_lot(db, lot_id, T0 + timedelta(hours=hours), n, defects)
    for minute in (1, 2, 3):
        insert(db, "L-001", T0 + timedelta(minutes=minute), "unknown", None)
    insert_lot(db, "L-SIM", T0 + timedelta(minutes=30), 10, 9, source="simulated")
    return db


@pytest.fixture
def reader(clean_db: str, settings_for) -> Iterator[TestClient]:
    with TestClient(create_app(settings_for(clean_db))) as test_client:
        yield test_client


def get_spc(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get(URL, params=params, headers=R)
    assert response.status_code == 200, response.text
    return response.json()


def assert_example_1(body: dict[str, Any]) -> None:
    assert body["p_bar"] == pytest.approx(0.1385, abs=TOL)
    assert [point["lot_id"] for point in body["points"]] == [row[0] for row in EXPECTED_1]
    for point, (lot_id, p, cl, ucl, lcl, out) in zip(body["points"], EXPECTED_1, strict=True):
        assert point["p"] == pytest.approx(p, abs=TOL), lot_id
        assert point["cl"] == pytest.approx(cl, abs=TOL), lot_id
        assert point["ucl"] == pytest.approx(ucl, abs=TOL), lot_id
        assert point["lcl"] == pytest.approx(lcl, abs=TOL), lot_id
        assert point["out_of_control"] is out, lot_id
    assert body["excluded_lots"] == [{"lot_id": "L-003", "n": 4}]
    assert body["message"] is None


# --- Example 1 and 2 through the route --------------------------------------------------------


def test_example_1_from_the_database(example_db, reader: TestClient) -> None:
    body = get_spc(reader, baseline_lots=3)
    SpcResponse.model_validate(body)
    assert_example_1(body)
    assert (body["baseline_lots"], body["min_lot_size"], body["source"]) == (3, 5, "live")
    first = body["points"][0]
    assert (first["n"], first["defects"]) == (20, 2)  # without the 3 unknown rows
    assert "L-SIM" not in {point["lot_id"] for point in body["points"]}
    assert "L-SIM" not in {item["lot_id"] for item in body["excluded_lots"]}


def test_lot_period_comes_from_the_rows_in_utc(example_db, reader: TestClient) -> None:
    body = get_spc(reader, baseline_lots=3)
    by_lot = {point["lot_id"]: point for point in body["points"]}
    start = T0 + timedelta(hours=6)
    assert datetime.fromisoformat(by_lot["L-007"]["started_at"]) == start
    assert datetime.fromisoformat(by_lot["L-007"]["ended_at"]) == start + timedelta(minutes=99)
    assert by_lot["L-007"]["started_at"].endswith("Z")


def test_example_2_defaults(example_db, reader: TestClient) -> None:
    body = get_spc(reader)
    assert body["p_bar"] == pytest.approx(0.1048, abs=TOL)
    by_lot = {point["lot_id"]: point for point in body["points"]}
    assert by_lot["L-001"]["ucl"] == pytest.approx(0.3102, abs=TOL)
    assert by_lot["L-002"]["ucl"] == pytest.approx(0.2885, abs=TOL)
    assert by_lot["L-007"]["ucl"] == pytest.approx(0.1966, abs=TOL)
    assert by_lot["L-007"]["lcl"] == pytest.approx(0.0129, abs=TOL)
    assert [p["lot_id"] for p in body["points"] if p["out_of_control"]] == ["L-005", "L-007"]
    assert (body["baseline_lots"], body["min_lot_size"], body["source"]) == (20, 5, "live")


def test_simulated_only_with_explicit_source(example_db, reader: TestClient) -> None:
    body = get_spc(reader, source="simulated")
    assert body["points"] == []
    assert body["p_bar"] is None
    assert body["source"] == "simulated"
    assert body["excluded_lots"] == []
    assert body["message"].endswith("(found 1)")


def test_object_type_filter(example_db, reader: TestClient) -> None:
    nut = get_spc(reader, object_type="nut")
    assert nut["points"] == []
    assert nut["p_bar"] is None
    assert nut["message"].endswith("(found 0)")
    assert get_spc(reader, object_type="screw", baseline_lots=3) == get_spc(reader, baseline_lots=3)


def test_types_are_pooled_without_filter_and_split_with_it(
    device_keys, db: psycopg.Connection, reader: TestClient
) -> None:
    insert_lot(db, "L-A", T0, 10, 1)
    insert_lot(db, "L-A", T0 + timedelta(minutes=20), 10, 3, object_type="nut")
    insert_lot(db, "L-B", T0 + timedelta(hours=1), 10, 0)
    insert_lot(db, "L-B", T0 + timedelta(hours=1, minutes=20), 10, 4, object_type="nut")
    pooled = get_spc(reader)
    assert [(p["lot_id"], p["n"], p["defects"]) for p in pooled["points"]] == [
        ("L-A", 20, 4),
        ("L-B", 20, 4),
    ]
    screws = get_spc(reader, object_type="screw")
    assert [(p["n"], p["defects"]) for p in screws["points"]] == [(10, 1), (10, 0)]
    nuts = get_spc(reader, object_type="nut")
    assert [(p["n"], p["defects"]) for p in nuts["points"]] == [(10, 3), (10, 4)]
    assert datetime.fromisoformat(nuts["points"][0]["started_at"]) == T0 + timedelta(minutes=20)


def test_sources_are_never_mixed_in_one_lot(
    device_keys, db: psycopg.Connection, reader: TestClient
) -> None:
    """A lot with rows of both origins: each chart counts only its own rows (R-06)."""
    for lot_id, hours in (("L-A", 0), ("L-B", 1)):
        insert_lot(db, lot_id, T0 + timedelta(hours=hours), 10, 1)
        insert_lot(db, lot_id, T0 + timedelta(hours=hours, minutes=30), 5, 5, source="simulated")
    live = get_spc(reader)
    assert [(p["n"], p["defects"]) for p in live["points"]] == [(10, 1), (10, 1)]
    simulated = get_spc(reader, source="simulated")
    assert [(p["n"], p["defects"]) for p in simulated["points"]] == [(5, 5), (5, 5)]
    assert simulated["source"] == "simulated"


def test_lot_of_unknown_rows_only_does_not_appear(
    device_keys, db: psycopg.Connection, reader: TestClient
) -> None:
    for minute in range(6):
        insert(db, "L-U", T0 + timedelta(minutes=minute), "unknown", None)
    body = get_spc(reader)
    assert body["excluded_lots"] == []
    assert body["message"].endswith("(found 0)")


def test_empty_database(clean_db: str, reader: TestClient) -> None:
    body = get_spc(reader)
    assert body == {
        "baseline_lots": 20,
        "min_lot_size": 5,
        "source": "live",
        "p_bar": None,
        "points": [],
        "excluded_lots": [],
        "message": "insufficient data: need at least 2 lots with n >= 5 (found 0)",
    }


def test_min_lot_size_is_the_effective_one(example_db, reader: TestClient) -> None:
    body = get_spc(reader, min_lot_size=21, baseline_lots=2)
    assert [point["lot_id"] for point in body["points"]] == ["L-002", "L-006", "L-007"]
    assert [item["lot_id"] for item in body["excluded_lots"]] == [
        "L-001",
        "L-003",
        "L-004",
        "L-005",
    ]
    assert (body["baseline_lots"], body["min_lot_size"]) == (2, 21)
    assert body["p_bar"] == pytest.approx(3 / 50)


# --- parameters and authentication -------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {"baseline_lots": 1},
        {"baseline_lots": 101},
        {"baseline_lots": "x"},
        {"min_lot_size": 0},
        {"min_lot_size": 501},
        {"min_lot_size": 2.5},
        {"source": "all"},
        {"source": "LIVE"},
        {"object_type": "unknown"},
        {"object_type": "bolt"},
    ],
)
def test_invalid_parameters_are_422(example_db, reader: TestClient, params: dict) -> None:
    response = reader.get(URL, params=params, headers=R)
    assert response.status_code == 422, params
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize(
    "params",
    [{"baseline_lots": 2}, {"baseline_lots": 100}, {"min_lot_size": 1}, {"min_lot_size": 500}],
)
def test_boundary_parameters_are_200(example_db, reader: TestClient, params: dict) -> None:
    body = get_spc(reader, **params)
    for name, value in params.items():
        assert body[name] == value


def test_unknown_query_parameters_are_ignored(example_db, reader: TestClient) -> None:
    assert get_spc(reader, baseline_lots=3, foo="bar") == get_spc(reader, baseline_lots=3)


def test_needs_the_read_key(example_db, device_keys: dict[str, str], reader: TestClient) -> None:
    for headers in ({}, {"X-API-Key": "errada"}, {"X-API-Key": device_keys["edge-01"]}):
        response = reader.get(URL, headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "Missing or invalid API key"}


def test_missing_key_is_401_before_validation(example_db, reader: TestClient) -> None:
    response = reader.get(URL, params={"baseline_lots": 0})
    assert response.status_code == 401
