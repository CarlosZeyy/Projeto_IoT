"""Power tools of phase 3 in the API (SPEC-021 sections 3.1 and 4, ADR-021).

No API code changes: the write routes accept a power tool without a grade through the contract
0.6.0 (and refuse it with a grade), the database accepts it by migration 006, and the SPC and
the defect rate leave it out by the ``grade is not null`` rule of SPEC-016. ``SpcObjectType``
does not change, so ``object_type=drill`` on the SPC route is a 422.

Rows are inserted with SQL unless the test is about the write routes. The database tests are
marked ``db``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from qc_api.main import create_app
from qc_api.repositories import inspections as repository
from qc_api.routers.metrics import SpcObjectType
from qc_contracts import (
    GRADE_FORBIDDEN_OBJECT_TYPES,
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
POWER_TOOLS = ("angle_grinder", "saw", "drill", "cordless_screwdriver")
TOOLS = ("pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver")
# The enum of SPEC-016 (CA-05 there): SPEC-021 does not change it.
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


def insert_screw_lot(db: psycopg.Connection, lot_id: str, start: datetime, defects: int) -> None:
    for i in range(10):
        insert(db, lot_id, start + timedelta(minutes=i), "screw", "poor" if i < defects else "good")


def insert_power_tools(
    db: psycopg.Connection, lot_id: str, start: datetime, n: int, object_type: str = "drill"
) -> None:
    for i in range(n):
        insert(db, lot_id, start + timedelta(minutes=i), object_type, None)


def power_tool_payload(
    make_payload: Callable[..., dict[str, Any]], object_type: str = "drill", **overrides: Any
) -> dict[str, Any]:
    body = make_payload(
        object_type=object_type, grade=None, grade_score=None, grade_confidence=None
    )
    body.update(overrides)
    return body


# --- SpcObjectType (no database) ----------------------------------------------------------------


def test_spc_object_type_is_unchanged() -> None:
    assert [member.value for member in SpcObjectType] == SPC_ENUM


def test_no_grade_forbidden_type_enters_the_spc_filter() -> None:
    values = {member.value for member in SpcObjectType}
    assert not values & {member.value for member in GRADE_FORBIDDEN_OBJECT_TYPES}
    assert not values & set(POWER_TOOLS)


def test_openapi_spc_enum_is_unchanged(no_db_settings) -> None:
    with TestClient(create_app(no_db_settings)) as no_db_client:
        spec = no_db_client.get("/openapi.json").json()
    assert spec["components"]["schemas"]["SpcObjectType"]["enum"] == SPC_ENUM


def test_health_shows_the_contract_0_6_0(no_db_settings) -> None:
    with TestClient(create_app(no_db_settings)) as no_db_client:
        body = no_db_client.get("/api/v1/health").json()
    assert body["contract_version"] == "0.6.0"


# --- write and read routes ----------------------------------------------------------------------


@pytest.mark.db
@pytest.mark.parametrize("tool", POWER_TOOLS)
def test_post_power_tool_without_grade_is_created_and_listed(
    client: TestClient, device_keys: dict[str, str], make_payload, tool: str
) -> None:
    body = power_tool_payload(make_payload, tool)
    response = client.post(
        "/api/v1/inspections", json=body, headers={"X-API-Key": device_keys["edge-01"]}
    )
    assert response.status_code == 201, response.text
    assert response.json() == {"inspection_id": body["inspection_id"], "status": "created"}
    page = client.get("/api/v1/inspections", params={"object_type": tool}, headers=R).json()
    (item,) = page["items"]
    assert item["object_type"] == tool
    assert item["grade"] is None and item["grade_score"] is None
    assert item["grade_confidence"] is None and item["is_defective"] is False


@pytest.mark.db
@pytest.mark.parametrize("tool", POWER_TOOLS)
def test_post_power_tool_with_a_grade_is_422(
    client: TestClient, device_keys: dict[str, str], make_payload, tool: str
) -> None:
    body = make_payload(object_type=tool, grade="fair", grade_score=2.0, grade_confidence=0.7)
    response = client.post(
        "/api/v1/inspections", json=body, headers={"X-API-Key": device_keys["edge-01"]}
    )
    assert response.status_code == 422, response.text
    assert client.get("/api/v1/inspections", headers=R).json()["total"] == 0


@pytest.mark.db
def test_batch_with_power_tools(
    client: TestClient, device_keys: dict[str, str], make_payload
) -> None:
    items = [power_tool_payload(make_payload, tool) for tool in POWER_TOOLS]
    items.append(make_payload())
    response = client.post(
        "/api/v1/inspections/batch",
        json={"items": items},
        headers={"X-API-Key": device_keys["edge-01"]},
    )
    assert response.status_code == 200, response.text
    assert [r["status"] for r in response.json()["results"]] == ["created"] * 5


@pytest.mark.db
def test_batch_with_one_graded_power_tool_is_refused_whole(
    client: TestClient, device_keys: dict[str, str], make_payload
) -> None:
    items = [make_payload(), make_payload(object_type="saw")]
    response = client.post(
        "/api/v1/inspections/batch",
        json={"items": items},
        headers={"X-API-Key": device_keys["edge-01"]},
    )
    assert response.status_code == 422, response.text
    assert client.get("/api/v1/inspections", headers=R).json()["total"] == 0


@pytest.mark.db
def test_read_filters_accept_a_power_tool(
    device_keys, db: psycopg.Connection, client: TestClient
) -> None:
    insert_power_tools(db, "L-P", T0, 3)
    for url in ("/api/v1/inspections", "/api/v1/metrics/summary", "/api/v1/lots"):
        response = client.get(url, params={"object_type": "drill"}, headers=R)
        assert response.status_code == 200, url


# --- SPC ----------------------------------------------------------------------------------------


@pytest.fixture
def spc_db(device_keys: dict[str, str], db: psycopg.Connection) -> psycopg.Connection:
    """CA-04 of SPEC-021: L-01..L-03 with 10 screws (1 poor each), L-04 with 10 drills."""
    for k in range(3):
        insert_screw_lot(db, f"L-0{k + 1}", T0 + timedelta(hours=k), 1)
    insert_power_tools(db, "L-04", T0 + timedelta(hours=3), 10)
    return db


@pytest.mark.db
def test_spc_leaves_out_a_lot_of_power_tools(spc_db, client: TestClient) -> None:
    response = client.get("/api/v1/metrics/spc", params={"source": "live"}, headers=R)
    assert response.status_code == 200, response.text
    spc = SpcResponse.model_validate(response.json())
    assert [(p.lot_id, p.n, p.defects) for p in spc.points] == [
        ("L-01", 10, 1),
        ("L-02", 10, 1),
        ("L-03", 10, 1),
    ]
    assert "L-04" not in [lot.lot_id for lot in spc.excluded_lots]
    assert spc.excluded_lots == []
    assert spc.p_bar == pytest.approx(0.1)


@pytest.mark.db
@pytest.mark.parametrize("tool", POWER_TOOLS)
def test_spc_filter_by_a_power_tool_is_422(spc_db, client: TestClient, tool: str) -> None:
    response = client.get(
        "/api/v1/metrics/spc", params={"source": "live", "object_type": tool}, headers=R
    )
    assert response.status_code == 422, tool


@pytest.mark.db
def test_lot_selection_leaves_out_power_tools(spc_db, client: TestClient) -> None:
    selection = repository.lot_selection(
        client.app.state.pool,
        Source.LIVE,
        None,
        baseline_lots=20,
        min_lot_size=1,
        max_points=None,
        max_excluded=None,
    )
    assert [lot.lot_id for lot in selection.window] == ["L-01", "L-02", "L-03"]
    assert selection.excluded == ()


@pytest.mark.db
def test_power_tools_inside_a_screw_lot_do_not_change_n(
    device_keys, db: psycopg.Connection, client: TestClient
) -> None:
    insert_screw_lot(db, "L-01", T0, 2)
    insert_power_tools(db, "L-01", T0 + timedelta(minutes=30), 5, "angle_grinder")
    insert_screw_lot(db, "L-02", T0 + timedelta(hours=1), 0)
    body = client.get("/api/v1/metrics/spc", params={"source": "live"}, headers=R).json()
    assert [(p["lot_id"], p["n"], p["defects"]) for p in body["points"]] == [
        ("L-01", 10, 2),
        ("L-02", 10, 0),
    ]


# --- defect rate --------------------------------------------------------------------------------


@pytest.mark.db
def test_summary_leaves_power_tools_out_of_the_defect_rate(
    device_keys, db: psycopg.Connection, client: TestClient
) -> None:
    insert_screw_lot(db, "L-R", T0, 2)
    for k, tool in enumerate(POWER_TOOLS):
        insert_power_tools(db, "L-R", T0 + timedelta(minutes=20 + 5 * k), 2, tool)
    insert(db, "L-R", T0 + timedelta(minutes=50), "unknown", None)
    summary = MetricsSummary.model_validate(client.get("/api/v1/metrics/summary", headers=R).json())
    assert (summary.total, summary.defective, summary.unknown_count) == (19, 2, 1)
    assert summary.defect_rate == pytest.approx(0.2)
    for tool in POWER_TOOLS:
        assert summary.by_object_type[ObjectType(tool)] == 2
    assert sum(summary.by_grade.values()) == 10

    body = client.get("/api/v1/metrics/timeseries", params={"bucket": "hour"}, headers=R).json()
    (point,) = [TimeseriesPoint.model_validate(item) for item in body]
    assert (point.total, point.defective) == (19, 2)
    assert point.defect_rate == pytest.approx(0.2)


@pytest.mark.db
def test_summary_of_power_tools_only_has_null_rate(
    device_keys, db: psycopg.Connection, client: TestClient
) -> None:
    insert_power_tools(db, "L-P", T0, 4, "cordless_screwdriver")
    body = client.get(
        "/api/v1/metrics/summary", params={"object_type": "cordless_screwdriver"}, headers=R
    )
    summary = MetricsSummary.model_validate(body.json())
    assert (summary.total, summary.defective, summary.unknown_count) == (4, 0, 0)
    assert summary.defect_rate is None and summary.mean_grade_score is None
