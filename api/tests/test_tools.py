"""Hand tools of phase 2 in the API (SPEC-016 section 4.3, ADR-021).

* The write routes accept a tool with or without a grade through the contract, with no new code.
* The SPC (``lot_selection``) and the defect rate (summary and time series) count only the
  inspections with a grade (``grade is not null``); ``unknown_count`` still counts only
  ``unknown``.
* ``SpcObjectType`` is a declared ``StrEnum``: ``screw``, ``nut`` and the 5 tools.

Rows are inserted with SQL (not through the API) unless the test is about the write routes. The
database tests are marked ``db``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from qc_api.main import create_app
from qc_api.repositories import inspections as repository
from qc_api.routers.metrics import SpcObjectType
from qc_contracts import (
    GRADE_OPTIONAL_OBJECT_TYPES,
    GRADE_REQUIRED_OBJECT_TYPES,
    MetricsSummary,
    ObjectType,
    Source,
    SpcResponse,
    TimeseriesPoint,
)

READ_KEY = "r" * 32
SHA = "a" * 64
R = {"X-API-Key": READ_KEY}
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
TOOLS = ("pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver")
SPC_ENUM = ["screw", "nut", *TOOLS]

INSERT = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
)
values (%s, 'edge-01', %s, %s, %s, %s, %s, 0.9, %s, false, 'partqc-mnv3-v1', %s, 100, 'live')
"""


def insert(
    db: psycopg.Connection,
    lot_id: str,
    inspected_at: datetime,
    object_type: str = "screw",
    grade: str | None = "good",
) -> None:
    score = None if grade is None else 1.0
    confidence = None if grade is None else 0.8
    db.execute(
        INSERT,
        (str(uuid.uuid4()), lot_id, inspected_at, object_type, grade, score, confidence, SHA),
    )


def insert_lot(
    db: psycopg.Connection, lot_id: str, start: datetime, n: int, defects: int, object_type: str
) -> None:
    """``n`` rows one minute apart from ``start``: the first ``defects`` are ``poor``."""
    for i in range(n):
        grade = "poor" if i < defects else "good"
        insert(db, lot_id, start + timedelta(minutes=i), object_type, grade)


def insert_ungraded(
    db: psycopg.Connection, lot_id: str, start: datetime, n: int, object_type: str = "pliers"
) -> None:
    for i in range(n):
        insert(db, lot_id, start + timedelta(minutes=i), object_type, None)


def tool_payload(make_payload: Callable[..., dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    body = make_payload(object_type="pliers", grade=None, grade_score=None, grade_confidence=None)
    body.update(overrides)
    return body


# --- SpcObjectType (no database) ----------------------------------------------------------------


def test_spc_object_type_is_a_declared_enum() -> None:
    assert issubclass(SpcObjectType, StrEnum)
    assert [member.value for member in SpcObjectType] == SPC_ENUM
    assert "UNKNOWN" not in SpcObjectType.__members__
    assert SpcObjectType.__module__ == "qc_api.routers.metrics"


def test_spc_object_type_is_the_graded_groups_of_the_contract() -> None:
    """ADR-021, decision 3: the grade-required and grade-optional types, in contract order."""
    graded = GRADE_REQUIRED_OBJECT_TYPES | GRADE_OPTIONAL_OBJECT_TYPES
    assert [member.value for member in SpcObjectType] == [
        member.value for member in ObjectType if member in graded
    ]


def test_spc_object_type_members_are_contract_values() -> None:
    for member in SpcObjectType:
        assert ObjectType(member.value).value == member.value


# --- write and read routes ----------------------------------------------------------------------


@pytest.mark.db
def test_post_tool_without_grade_is_created_and_listed(
    client: TestClient, device_keys: dict[str, str], make_payload
) -> None:
    body = tool_payload(make_payload)
    response = client.post(
        "/api/v1/inspections", json=body, headers={"X-API-Key": device_keys["edge-01"]}
    )
    assert response.status_code == 201, response.text
    assert response.json() == {"inspection_id": body["inspection_id"], "status": "created"}

    page = client.get("/api/v1/inspections", params={"object_type": "pliers"}, headers=R).json()
    assert page["total"] == 1
    (item,) = page["items"]
    assert item["object_type"] == "pliers"
    assert item["grade"] is None and item["grade_score"] is None
    assert item["is_defective"] is False


@pytest.mark.db
@pytest.mark.parametrize("tool", TOOLS)
def test_post_every_tool_with_a_grade(
    client: TestClient, device_keys: dict[str, str], make_payload, tool: str
) -> None:
    body = make_payload(object_type=tool, grade="unusable", grade_score=3.9)
    response = client.post(
        "/api/v1/inspections", json=body, headers={"X-API-Key": device_keys["edge-01"]}
    )
    assert response.status_code == 201, response.text
    (item,) = client.get("/api/v1/inspections", params={"object_type": tool}, headers=R).json()[
        "items"
    ]
    assert item["grade"] == "unusable" and item["is_defective"] is True


@pytest.mark.db
def test_batch_with_tools(client: TestClient, device_keys: dict[str, str], make_payload) -> None:
    items = [tool_payload(make_payload, object_type=tool) for tool in TOOLS]
    items.append(make_payload())
    response = client.post(
        "/api/v1/inspections/batch",
        json={"items": items},
        headers={"X-API-Key": device_keys["edge-01"]},
    )
    assert response.status_code == 200, response.text
    assert [r["status"] for r in response.json()["results"]] == ["created"] * 6


@pytest.mark.db
@pytest.mark.parametrize(
    "overrides",
    [
        {"object_type": "hammer"},
        {"object_type": "screw"},  # screw without a grade
        {"object_type": "unknown", "grade": "good", "grade_score": 1.0, "grade_confidence": 0.8},
        {"grade": "fair", "grade_score": None, "grade_confidence": 0.7},
    ],
)
def test_post_invalid_tool_combinations_are_422(
    client: TestClient, device_keys: dict[str, str], make_payload, overrides: dict[str, Any]
) -> None:
    body = tool_payload(make_payload, **overrides)
    response = client.post(
        "/api/v1/inspections", json=body, headers={"X-API-Key": device_keys["edge-01"]}
    )
    assert response.status_code == 422, response.text


@pytest.mark.db
def test_unknown_object_type_filter_is_422(client: TestClient) -> None:
    for url in ("/api/v1/inspections", "/api/v1/metrics/summary", "/api/v1/lots"):
        response = client.get(url, params={"object_type": "hammer"}, headers=R)
        assert response.status_code == 422, url


# --- SPC ----------------------------------------------------------------------------------------


@pytest.fixture
def spc_db(device_keys: dict[str, str], db: psycopg.Connection) -> psycopg.Connection:
    """CA-05 of SPEC-016: L-01..L-03 with 10 screws (2, 3, 1 poor), L-04 with 10 pliers without a
    grade, and 4 more pliers without a grade inside L-01."""
    for k, defects in enumerate((2, 3, 1)):
        insert_lot(db, f"L-0{k + 1}", T0 + timedelta(hours=k), 10, defects, "screw")
    insert_ungraded(db, "L-01", T0 + timedelta(minutes=30), 4)
    insert_ungraded(db, "L-04", T0 + timedelta(hours=3), 10)
    return db


@pytest.mark.db
def test_spc_counts_only_graded_inspections(spc_db, client: TestClient) -> None:
    response = client.get("/api/v1/metrics/spc", params={"source": "live"}, headers=R)
    assert response.status_code == 200, response.text
    spc = SpcResponse.model_validate(response.json())
    assert [(p.lot_id, p.n) for p in spc.points] == [("L-01", 10), ("L-02", 10), ("L-03", 10)]
    assert spc.excluded_lots == []
    assert spc.p_bar == pytest.approx(0.2)
    assert (spc.valid_lots_total, spc.excluded_lots_total) == (3, 0)


@pytest.mark.db
def test_spc_filter_by_a_tool_without_grade_is_empty(spc_db, client: TestClient) -> None:
    response = client.get(
        "/api/v1/metrics/spc", params={"source": "live", "object_type": "pliers"}, headers=R
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["points"] == [] and body["excluded_lots"] == []
    assert body["p_bar"] is None


@pytest.mark.db
def test_spc_filter_by_a_graded_tool(device_keys, db: psycopg.Connection, client) -> None:
    insert_lot(db, "T-A", T0, 6, 3, "allen_key")
    insert_lot(db, "T-B", T0 + timedelta(hours=1), 6, 0, "allen_key")
    insert_ungraded(db, "T-B", T0 + timedelta(hours=1, minutes=30), 5, "allen_key")
    insert_lot(db, "S-A", T0, 6, 6, "screw")
    body = client.get("/api/v1/metrics/spc", params={"object_type": "allen_key"}, headers=R).json()
    assert [(p["lot_id"], p["n"], p["defects"]) for p in body["points"]] == [
        ("T-A", 6, 3),
        ("T-B", 6, 0),
    ]
    assert body["p_bar"] == pytest.approx(0.25)


@pytest.mark.db
@pytest.mark.parametrize("value", ["unknown", "hammer", "PLIERS", "other"])
def test_spc_filter_outside_the_enum_is_422(client: TestClient, value: str) -> None:
    response = client.get("/api/v1/metrics/spc", params={"object_type": value}, headers=R)
    assert response.status_code == 422, value


@pytest.mark.db
def test_lot_selection_leaves_out_tools_without_grade(spc_db, client: TestClient) -> None:
    pool = client.app.state.pool
    selection = repository.lot_selection(
        pool,
        Source.LIVE,
        None,
        baseline_lots=20,
        min_lot_size=1,
        max_points=None,
        max_excluded=None,
    )
    assert [lot.lot_id for lot in selection.window] == ["L-01", "L-02", "L-03"]
    assert [lot.n for lot in selection.window] == [10, 10, 10]
    assert selection.excluded == ()
    pliers = repository.lot_selection(
        pool,
        Source.LIVE,
        ObjectType.PLIERS,
        baseline_lots=20,
        min_lot_size=1,
        max_points=None,
        max_excluded=None,
    )
    assert (pliers.valid_lots_total, pliers.excluded_lots_total) == (0, 0)


def test_openapi_lists_the_declared_spc_enum(no_db_settings) -> None:
    with TestClient(create_app(no_db_settings)) as no_db_client:
        spec = no_db_client.get("/openapi.json").json()
    assert spec["components"]["schemas"]["SpcObjectType"]["enum"] == SPC_ENUM


# --- defect rate --------------------------------------------------------------------------------


@pytest.fixture
def rate_db(device_keys: dict[str, str], db: psycopg.Connection) -> psycopg.Connection:
    """CA-06 of SPEC-016: 10 screws (2 poor), 5 pliers without a grade and 3 unknown."""
    insert_lot(db, "L-R", T0, 10, 2, "screw")
    insert_ungraded(db, "L-R", T0 + timedelta(minutes=20), 5)
    for i in range(3):
        insert(db, "L-R", T0 + timedelta(minutes=40 + i), "unknown", None)
    return db


@pytest.mark.db
def test_summary_defect_rate_counts_only_graded(rate_db, client: TestClient) -> None:
    summary = MetricsSummary.model_validate(client.get("/api/v1/metrics/summary", headers=R).json())
    assert (summary.total, summary.defective, summary.unknown_count) == (18, 2, 3)
    assert summary.defect_rate == pytest.approx(0.2)
    assert summary.by_object_type[ObjectType.PLIERS] == 5
    assert summary.by_object_type[ObjectType.ALLEN_KEY] == 0
    assert sum(summary.by_grade.values()) == 10


@pytest.mark.db
def test_summary_of_tools_without_grade_has_null_rate(rate_db, client: TestClient) -> None:
    body = client.get("/api/v1/metrics/summary", params={"object_type": "pliers"}, headers=R)
    summary = MetricsSummary.model_validate(body.json())
    assert (summary.total, summary.defective, summary.unknown_count) == (5, 0, 0)
    assert summary.defect_rate is None
    assert summary.mean_grade_score is None


@pytest.mark.db
def test_timeseries_defect_rate_counts_only_graded(rate_db, client: TestClient) -> None:
    body = client.get("/api/v1/metrics/timeseries", params={"bucket": "hour"}, headers=R).json()
    (point,) = [TimeseriesPoint.model_validate(item) for item in body]
    assert (point.total, point.defective) == (18, 2)
    assert point.defect_rate == pytest.approx(0.2)


@pytest.mark.db
def test_timeseries_bucket_of_tools_without_grade_has_null_rate(
    device_keys, db: psycopg.Connection, client: TestClient
) -> None:
    insert_ungraded(db, "L-T", T0, 3, "phillips_screwdriver")
    insert_lot(db, "L-T", T0 + timedelta(hours=2), 4, 1, "phillips_screwdriver")
    body = client.get("/api/v1/metrics/timeseries", params={"bucket": "hour"}, headers=R).json()
    points = [TimeseriesPoint.model_validate(item) for item in body]
    assert [(p.total, p.defective, p.defect_rate) for p in points] == [
        (3, 0, None),
        (4, 1, 0.25),
    ]


@pytest.mark.db
def test_lot_summary_is_unchanged_by_the_rule(rate_db, client: TestClient) -> None:
    """``/lots`` keeps ``n`` with every row and ``unknown_count`` with only ``unknown``."""
    (lot,) = client.get("/api/v1/lots", headers=R).json()["items"]
    assert (lot["n"], lot["defects"], lot["unknown_count"]) == (18, 2, 3)
