"""Read-route parameters and query composition without a database (SPEC-005 sections 4.1 to 4.3).

The "app without database" points to a closed local port: no mock of the database.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from qc_api.config import Settings
from qc_api.filters import InspectionFilters
from qc_api.main import create_app
from qc_api.repositories.inspections import where_clause
from qc_contracts import Grade, ObjectType, Source

READ_URLS = (
    "/api/v1/inspections",
    "/api/v1/metrics/summary",
    "/api/v1/metrics/timeseries",
    "/api/v1/lots",
    "/api/v1/metrics/spc",
)
API_SRC = Path(__file__).resolve().parents[1] / "src" / "qc_api"


@pytest.fixture
def client(no_db_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(no_db_settings)) as test_client:
        yield test_client


def test_where_clause_without_filters_is_true() -> None:
    condition, params = where_clause(InspectionFilters())
    assert condition.as_string() == "true"
    assert params == {}


def test_where_clause_combines_every_filter_with_placeholders() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    filters = InspectionFilters(
        device_id="edge-01",
        lot_id="L-A",
        object_type=ObjectType.SCREW,
        grade=Grade.POOR,
        source=Source.LIVE,
        defective=False,
        from_=start,
        to=start + timedelta(hours=1),
    )
    condition, params = where_clause(filters)
    text = condition.as_string()
    assert text == (
        "device_id = %(f_device_id)s and lot_id = %(f_lot_id)s"
        " and object_type = %(f_object_type)s and grade = %(f_grade)s"
        " and source = %(f_source)s and is_defective = %(f_defective)s"
        " and inspected_at >= %(f_from)s and inspected_at < %(f_to)s"
    )
    assert params == {
        "f_device_id": "edge-01",
        "f_lot_id": "L-A",
        "f_object_type": "screw",
        "f_grade": "poor",
        "f_source": "live",
        "f_defective": False,
        "f_from": start,
        "f_to": start + timedelta(hours=1),
    }
    assert "edge-01" not in text


def test_from_must_be_before_to() -> None:
    moment = datetime(2026, 10, 1, tzinfo=UTC)
    with pytest.raises(RequestValidationError):
        InspectionFilters(from_=moment, to=moment)
    InspectionFilters(from_=moment)
    InspectionFilters(to=moment)


@pytest.mark.parametrize("url", READ_URLS)
def test_read_routes_without_key_are_401_without_database(client: TestClient, url: str) -> None:
    for headers in ({}, {"X-API-Key": "errada"}):
        response = client.get(url, headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "Missing or invalid API key"}


def test_validation_does_not_need_the_database(client: TestClient) -> None:
    headers = {"X-API-Key": "r" * 32}
    response = client.get(
        "/api/v1/inspections",
        params={"from": "2026-10-01T12:00:00+00:00", "to": "2026-10-01T11:00:00Z"},
        headers=headers,
    )
    assert response.status_code == 422
    response = client.get("/api/v1/metrics/timeseries", params={"bucket": "week"}, headers=headers)
    assert response.status_code == 422
    for params in ({"object_type": "unknown"}, {"baseline_lots": 1}, {"min_lot_size": 501}):
        response = client.get("/api/v1/metrics/spc", params=params, headers=headers)
        assert response.status_code == 422, params


def test_openapi_documents_the_spc_parameters(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    operation = spec["paths"]["/api/v1/metrics/spc"]["get"]
    params = {p["name"]: p for p in operation["parameters"]}
    assert params["baseline_lots"]["schema"]["minimum"] == 2
    assert params["baseline_lots"]["schema"]["maximum"] == 100
    assert params["baseline_lots"]["schema"]["default"] == 20
    assert params["min_lot_size"]["schema"]["minimum"] == 1
    assert params["min_lot_size"]["schema"]["maximum"] == 500
    assert params["min_lot_size"]["schema"]["default"] == 5
    assert params["source"]["schema"]["default"] == "live"
    assert spec["components"]["schemas"]["SpcObjectType"]["enum"] == ["screw", "nut"]
    assert set(operation["responses"]) >= {"200", "401", "422", "503"}


def test_read_routes_without_database_are_503(client: TestClient) -> None:
    for url in READ_URLS:
        response = client.get(url, headers={"X-API-Key": "r" * 32})
        assert response.status_code == 503, url
        assert response.json() == {"detail": "Database unavailable"}


def test_openapi_documents_the_query_parameters(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    common = {"device_id", "lot_id", "object_type", "grade", "source", "defective", "from", "to"}
    expected = {
        "/api/v1/inspections": common | {"limit", "offset"},
        "/api/v1/metrics/summary": common,
        "/api/v1/metrics/timeseries": common | {"bucket"},
        "/api/v1/lots": common | {"limit", "offset"},
        "/api/v1/metrics/spc": {"source", "object_type", "baseline_lots", "min_lot_size"},
    }
    for path, names in expected.items():
        parameters = spec["paths"][path]["get"]["parameters"]
        assert {p["name"] for p in parameters if p["in"] == "query"} == names, path


_SQL_WORDS = re.compile(r"\b(select|where|insert)\b", re.IGNORECASE)


def _has_sql(node: ast.AST) -> bool:
    return any(
        isinstance(sub, ast.Constant)
        and isinstance(sub.value, str)
        and _SQL_WORDS.search(sub.value)
        for sub in ast.walk(node)
    )


def _is_sql_composition(node: ast.Call) -> bool:
    """``sql.SQL(...).format(...)`` (psycopg composition), which is allowed."""
    receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
    return (
        isinstance(receiver, ast.Call)
        and isinstance(receiver.func, ast.Attribute)
        and receiver.func.attr == "SQL"
    )


def test_sql_is_never_formatted_as_a_python_string() -> None:
    offenders: list[str] = []
    for path in sorted(API_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            bad = (
                (isinstance(node, ast.JoinedStr) and _has_sql(node))
                or (
                    isinstance(node, ast.BinOp)
                    and isinstance(node.op, ast.Mod)
                    and _has_sql(node.left)
                )
                or (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "format"
                    and not _is_sql_composition(node)
                    and _has_sql(node.func.value)
                )
            )
            if bad:
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
