"""Acceptance tests for SPEC-016 (database and qc-api: hand tools, SPC and defect rate, ADR-021).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-03 (database), CA-04, CA-05 and CA-06 (API). Tests named
``test_extra_*`` are exploratory edge cases around SPEC-016 sections 4.2 and 4.3 that no CA
spells out.

Every test uses the migrated test database of the ``db`` marker (``clean_db`` from SPEC-003);
rows are inserted with plain SQL or through the public routes. Device keys are generated at run
time, never written as literals (R-03). The migration test creates, and drops, a separate
database whose name contains ``test``.
"""

from __future__ import annotations

import hashlib
import secrets
import shutil
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import ValidationError

from qc_api.config import Settings
from qc_api.main import create_app
from qc_contracts import InspectionCreate, MetricsSummary, ObjectType, SpcResponse

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "infra" / "migrations"

R = "r" * 32
SHA = "b" * 64
T0 = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
TOOLS = ["pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver"]
ALL_TYPES = ["screw", "nut", "unknown", *TOOLS]
GRADES = ["perfect", "good", "fair", "poor", "unusable"]
SCORES = {g: float(i) for i, g in enumerate(GRADES)}
SPC_ENUM = ["screw", "nut", *TOOLS]

URL_INSPECTIONS = "/api/v1/inspections"
URL_BATCH = "/api/v1/inspections/batch"
URL_SUMMARY = "/api/v1/metrics/summary"
URL_SERIES = "/api/v1/metrics/timeseries"
URL_SPC = "/api/v1/metrics/spc"
URL_HEALTH = "/api/v1/health"

INSERT_ROW = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
) values (%s, %s, %s, %s, %s, %s, %s, 0.9, %s, false, 'partqc-mnv3-v1', %s, 42, %s)
"""


def connect(conninfo: str) -> psycopg.Connection:
    return psycopg.connect(conninfo, autocommit=True, prepare_threshold=None)


def insert(
    conn: psycopg.Connection,
    *,
    lot_id: str,
    at: datetime,
    object_type: str = "screw",
    grade: str | None = "good",
    source: str = "live",
    device: str = "edge-01",
) -> None:
    score = None if grade is None else SCORES[grade]
    conf = None if grade is None else 0.8
    conn.execute(
        INSERT_ROW,
        (str(uuid.uuid4()), device, lot_id, at, object_type, grade, score, conf, SHA, source),
    )


def insert_many(
    conn: psycopg.Connection,
    lot_id: str,
    start: datetime,
    n: int,
    *,
    object_type: str = "screw",
    poor: int = 0,
    grade: str | None = "good",
) -> None:
    """``poor`` rows with grade ``poor``, the others with ``grade`` (``None`` = no grade)."""
    for i in range(n):
        g = "poor" if i < poor else grade
        insert(
            conn, lot_id=lot_id, at=start + timedelta(minutes=i), object_type=object_type, grade=g
        )


def payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-016",
        "inspected_at": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
        "object_type": "pliers",
        "grade": None,
        "grade_score": None,
        "type_confidence": 0.93,
        "grade_confidence": None,
        "needs_review": False,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "latency_ms": 40,
        "source": "live",
    }
    data.update(overrides)
    return data


@dataclass
class Env:
    db: str
    client: TestClient
    device_key: str

    def read(self, url: str, params: Any = None) -> Any:
        return self.client.get(url, params=params, headers={"X-API-Key": R})

    def write(self, url: str, body: Any) -> Any:
        return self.client.post(url, json=body, headers={"X-API-Key": self.device_key})


@pytest.fixture
def env(clean_db: str) -> Iterator[Env]:
    key = secrets.token_urlsafe(32)
    with connect(clean_db) as conn:
        conn.execute(
            "insert into devices (device_id, api_key_hash) values (%s, %s)",
            ("edge-01", hashlib.sha256(key.encode()).hexdigest()),
        )
    app = create_app(Settings(DATABASE_URL=clean_db, READ_API_KEY=R))
    with TestClient(app) as client:
        yield Env(clean_db, client, key)


def contract_accepts(object_type: str, grade: str | None) -> bool:
    data = payload(
        object_type=object_type,
        grade=grade,
        grade_score=None if grade is None else SCORES[grade],
        grade_confidence=None if grade is None else 0.8,
    )
    try:
        InspectionCreate.model_validate(data)
    except ValidationError:
        return False
    return True


# --------------------------------------------------------------------------- CA-03


@pytest.mark.db
def test_ca03_database_accepts_exactly_the_contract_pairs(env: Env) -> None:
    outcomes: dict[tuple[str, str | None], str | None] = {}
    with connect(env.db) as conn:
        for object_type in ALL_TYPES:
            for grade in [*GRADES, None]:
                try:
                    insert(conn, lot_id="L-CA03", at=T0, object_type=object_type, grade=grade)
                    outcomes[(object_type, grade)] = None
                except psycopg.Error as exc:
                    outcomes[(object_type, grade)] = exc.sqlstate
    assert len(outcomes) == 48
    for (object_type, grade), sqlstate in outcomes.items():
        if contract_accepts(object_type, grade):
            assert sqlstate is None, (object_type, grade, sqlstate)
        else:
            assert sqlstate == "23514", (object_type, grade, sqlstate)
    # Sanity of the expectation itself: 2*5 + 1 + 5*6 accepted pairs.
    assert sum(1 for s in outcomes.values() if s is None) == 41
    with connect(env.db) as conn:
        count = conn.execute("select count(*) from inspections").fetchone()
    assert count == (41,)


@pytest.mark.db
def test_ca03_hammer_is_refused_with_23514(env: Env) -> None:
    with connect(env.db) as conn:
        for grade in ("good", None):
            with pytest.raises(psycopg.errors.CheckViolation) as info:
                insert(conn, lot_id="L-CA03", at=T0, object_type="hammer", grade=grade)
            assert info.value.sqlstate == "23514"


# --------------------------------------------------------------------------- CA-04


@pytest.mark.db
def test_ca04_post_tool_without_grade_and_read_it_back(env: Env) -> None:
    body = payload()
    resp = env.write(URL_INSPECTIONS, body)
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"inspection_id": body["inspection_id"], "status": "created"}

    listed = env.read(URL_INSPECTIONS, {"object_type": "pliers"})
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert page["total"] == 1
    (item,) = page["items"]
    assert item["inspection_id"] == body["inspection_id"]
    assert item["object_type"] == "pliers"
    assert item["grade"] is None
    assert item["grade_score"] is None
    assert item["grade_confidence"] is None
    assert item["is_defective"] is False

    bad = env.read(URL_INSPECTIONS, {"object_type": "hammer"})
    assert bad.status_code == 422, bad.text
    assert "detail" in bad.json()


# --------------------------------------------------------------------------- CA-05


@pytest.fixture
def ca05_env(env: Env) -> Env:
    with connect(env.db) as conn:
        for i, (lot_id, poor) in enumerate((("L-01", 2), ("L-02", 3), ("L-03", 1))):
            insert_many(conn, lot_id, T0 + timedelta(hours=i), 10, poor=poor)
        insert_many(conn, "L-04", T0 + timedelta(hours=3), 10, object_type="pliers", grade=None)
        # 4 ungraded pliers inside L-01 (between its screw rows).
        insert_many(conn, "L-01", T0 + timedelta(seconds=30), 4, object_type="pliers", grade=None)
    return env


@pytest.mark.db
def test_ca05_spc_counts_only_graded_inspections(ca05_env: Env) -> None:
    resp = ca05_env.read(URL_SPC, {"source": "live"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    SpcResponse.model_validate(data)
    assert [p["lot_id"] for p in data["points"]] == ["L-01", "L-02", "L-03"]
    assert [p["n"] for p in data["points"]] == [10, 10, 10]
    assert [p["defects"] for p in data["points"]] == [2, 3, 1]
    assert all(e["lot_id"] != "L-04" for e in data["excluded_lots"])
    assert data["p_bar"] == pytest.approx(0.2)


@pytest.mark.db
def test_ca05_spc_filter_by_ungraded_tool_and_unknown(ca05_env: Env) -> None:
    resp = ca05_env.read(URL_SPC, {"source": "live", "object_type": "pliers"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["points"] == []
    assert resp.json()["p_bar"] is None

    bad = ca05_env.read(URL_SPC, {"source": "live", "object_type": "unknown"})
    assert bad.status_code == 422, bad.text


@pytest.mark.db
def test_ca05_openapi_declares_the_spc_object_type_enum(env: Env) -> None:
    resp = env.client.get("/openapi.json")
    assert resp.status_code == 200
    doc = resp.json()
    params = doc["paths"][URL_SPC]["get"]["parameters"]
    (param,) = [p for p in params if p["name"] == "object_type"]
    schema = param["schema"]
    # Optional parameter: the enum may sit behind anyOf / $ref.
    refs: list[dict[str, Any]] = [schema, *schema.get("anyOf", [])]
    enums: list[list[str]] = []
    for node in refs:
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            assert name == "SpcObjectType", name
            node = doc["components"]["schemas"][name]
        if "enum" in node:
            enums.append(node["enum"])
    assert enums == [SPC_ENUM], schema
    assert doc["components"]["schemas"]["SpcObjectType"]["enum"] == SPC_ENUM


# --------------------------------------------------------------------------- CA-06


@pytest.mark.db
def test_ca06_defect_rate_uses_only_graded_inspections(env: Env) -> None:
    with connect(env.db) as conn:
        insert_many(conn, "L-A", T0, 10, poor=2)
        insert_many(conn, "L-B", T0 + timedelta(hours=1), 5, object_type="pliers", grade=None)
        insert_many(conn, "L-C", T0 + timedelta(hours=2), 3, object_type="unknown", grade=None)
    resp = env.read(URL_SUMMARY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    MetricsSummary.model_validate(body)
    assert body["total"] == 18
    assert body["defective"] == 2
    assert body["unknown_count"] == 3
    assert body["defect_rate"] == pytest.approx(0.2)


# --------------------------------------------------------------------------- extras


@pytest.mark.db
def test_extra_summary_breakdowns_with_tools(env: Env) -> None:
    with connect(env.db) as conn:
        insert_many(conn, "L-A", T0, 4, poor=1)
        insert_many(conn, "L-B", T0 + timedelta(hours=1), 3, object_type="allen_key", grade=None)
        insert_many(conn, "L-C", T0 + timedelta(hours=2), 2, object_type="pliers", poor=1)
    body = env.read(URL_SUMMARY).json()
    assert body["by_object_type"] == {t.value: 0 for t in ObjectType} | {
        "screw": 4,
        "allen_key": 3,
        "pliers": 2,
    }
    assert sum(body["by_grade"].values()) == 6  # the 3 ungraded tools have no grade
    assert body["defective"] == 2  # a graded tool can be defective (poor)
    assert body["defect_rate"] == pytest.approx(2 / 6)
    assert body["unknown_count"] == 0


@pytest.mark.db
def test_extra_summary_of_only_ungraded_tools_has_null_rate(env: Env) -> None:
    with connect(env.db) as conn:
        insert_many(conn, "L-B", T0, 5, object_type="flat_screwdriver", grade=None)
    body = env.read(URL_SUMMARY).json()
    assert body["total"] == 5
    assert body["defective"] == 0
    assert body["defect_rate"] is None
    assert body["mean_grade_score"] is None
    by_tool = env.read(URL_SUMMARY, {"object_type": "flat_screwdriver"}).json()
    assert by_tool["total"] == 5 and by_tool["defect_rate"] is None


@pytest.mark.db
def test_extra_timeseries_defect_rate_uses_only_graded(env: Env) -> None:
    with connect(env.db) as conn:
        insert_many(conn, "L-A", T0, 10, poor=2)  # minutes 0..9 of hour 08
        insert_many(conn, "L-B", T0 + timedelta(minutes=20), 5, object_type="pliers", grade=None)
        insert_many(conn, "L-C", T0 + timedelta(hours=1), 4, object_type="pliers", grade=None)
    params = {
        "bucket": "hour",
        "from": T0.isoformat(),
        "to": (T0 + timedelta(hours=3)).isoformat(),
    }
    resp = env.read(URL_SERIES, params)
    assert resp.status_code == 200, resp.text
    points = {p["bucket_start"][:13]: p for p in resp.json()}
    first = points["2026-11-02T08"]
    assert (first["total"], first["defective"]) == (15, 2)
    assert first["defect_rate"] == pytest.approx(0.2)
    second = points["2026-11-02T09"]
    assert second["total"] == 4
    assert second["defect_rate"] is None


@pytest.mark.db
def test_extra_spc_filter_by_a_graded_tool(env: Env) -> None:
    with connect(env.db) as conn:
        for i, poor in enumerate((1, 4, 0)):
            insert_many(
                conn,
                f"L-P{i}",
                T0 + timedelta(hours=i),
                6,
                object_type="phillips_screwdriver",
                poor=poor,
            )
        insert_many(conn, "L-S", T0 + timedelta(hours=5), 10, poor=5)
    resp = env.read(URL_SPC, {"object_type": "phillips_screwdriver"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert [p["lot_id"] for p in data["points"]] == ["L-P0", "L-P1", "L-P2"]
    assert data["p_bar"] == pytest.approx(5 / 18)
    # Without the filter, the graded tool is pooled with the screws (ADR-021: no split by type).
    pooled = env.read(URL_SPC).json()
    assert [p["lot_id"] for p in pooled["points"]] == ["L-P0", "L-P1", "L-P2", "L-S"]


@pytest.mark.db
def test_extra_spc_filter_values(env: Env) -> None:
    for value in SPC_ENUM:
        resp = env.read(URL_SPC, {"object_type": value})
        assert resp.status_code == 200, (value, resp.text)
    for value in ("unknown", "other", "hammer", "Pliers", "pliers ", ""):
        resp = env.read(URL_SPC, {"object_type": value})
        assert resp.status_code == 422, (value, resp.text)
        assert "Traceback" not in resp.text


@pytest.mark.db
def test_extra_post_every_tool_with_and_without_grade_and_batch(env: Env) -> None:
    for tool in TOOLS:
        resp = env.write(URL_INSPECTIONS, payload(object_type=tool))
        assert resp.status_code == 201, (tool, resp.text)
        resp = env.write(
            URL_INSPECTIONS,
            payload(object_type=tool, grade="unusable", grade_score=4.0, grade_confidence=0.66),
        )
        assert resp.status_code == 201, (tool, resp.text)
    items = [payload(object_type=t, lot_id="L-BATCH") for t in TOOLS]
    resp = env.write(URL_BATCH, {"items": items})
    assert resp.status_code == 200, resp.text
    assert [r["status"] for r in resp.json()["results"]] == ["created"] * 5
    # Idempotency (R-05) unchanged for the tools.
    again = env.write(URL_BATCH, {"items": items})
    assert [r["status"] for r in again.json()["results"]] == ["duplicate"] * 5
    listed = env.read(URL_INSPECTIONS, {"limit": 500}).json()
    assert listed["total"] == 15
    defective = [i for i in listed["items"] if i["is_defective"]]
    assert len(defective) == 5 and {i["grade"] for i in defective} == {"unusable"}


@pytest.mark.db
def test_extra_invalid_tool_payloads_are_422_and_not_stored(env: Env) -> None:
    cases = [
        payload(object_type="pliers", grade="fair", grade_score=None, grade_confidence=0.7),
        payload(object_type="pliers", grade=None, grade_score=2.0, grade_confidence=None),
        payload(object_type="screw"),
        payload(object_type="unknown", grade="good", grade_score=1.0, grade_confidence=0.8),
        payload(object_type="hammer"),
    ]
    for body in cases:
        resp = env.write(URL_INSPECTIONS, body)
        assert resp.status_code == 422, (body["object_type"], resp.text)
    resp = env.write(URL_BATCH, {"items": [payload(), cases[0]]})
    assert resp.status_code == 422
    assert env.read(URL_INSPECTIONS).json()["total"] == 0


@pytest.mark.db
def test_extra_health_reports_contract_0_4_0(env: Env) -> None:
    body = env.client.get(URL_HEALTH).json()
    assert body["status"] == "ok"
    assert body["contract_version"] == "0.4.0"


@pytest.mark.db
def test_extra_list_filter_by_each_tool_and_by_grade(env: Env) -> None:
    with connect(env.db) as conn:
        for i, tool in enumerate(TOOLS):
            insert_many(
                conn, f"L-T{i}", T0 + timedelta(hours=i), i + 1, object_type=tool, grade=None
            )
        insert_many(conn, "L-G", T0 + timedelta(hours=9), 2, object_type="pliers", poor=2)
    for i, tool in enumerate(TOOLS):
        page = env.read(URL_INSPECTIONS, {"object_type": tool}).json()
        expected = i + 1 + (2 if tool == "pliers" else 0)
        assert page["total"] == expected, tool
    poor = env.read(URL_INSPECTIONS, {"object_type": "pliers", "grade": "poor"}).json()
    assert poor["total"] == 2
    defective = env.read(URL_INSPECTIONS, {"defective": "true"}).json()
    assert defective["total"] == 2


# --------------------------------------------------------------------------- migration


def _other_db(conninfo: str, name: str) -> str:
    return make_conninfo(conninfo, dbname=name)


@pytest.mark.db
def test_extra_tool_migration_keeps_mvp_rows_and_runs_again(
    db_conninfo: str, tmp_path: Path
) -> None:
    """Section 4.2: the new migration keeps every valid MVP row and can run again."""
    from migrate import apply_migrations

    name = f"partqc_test_spec016_{secrets.token_hex(3)}"
    assert "test" in name
    admin = _other_db(db_conninfo, conninfo_to_dict(db_conninfo).get("dbname") or "postgres")
    with connect(admin) as conn:
        conn.execute(f'create database "{name}"')
    target = _other_db(db_conninfo, name)
    try:
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_files = sorted(MIGRATIONS.glob("*.sql"))
        tool_files = [p for p in new_files if "tool_object_types" in p.name]
        assert len(tool_files) == 1, new_files
        for path in new_files:
            if path != tool_files[0]:
                shutil.copy(path, old_dir / path.name)
        apply_migrations(target, old_dir)
        with connect(target) as conn:
            conn.execute(
                "insert into devices (device_id, api_key_hash) values ('edge-01', %s)",
                (hashlib.sha256(b"x").hexdigest(),),
            )
            for grade in GRADES:
                insert(conn, lot_id="L-MVP", at=T0, object_type="screw", grade=grade)
                insert(conn, lot_id="L-MVP", at=T0, object_type="nut", grade=grade)
            insert(conn, lot_id="L-MVP", at=T0, object_type="unknown", grade=None)
            with pytest.raises(psycopg.errors.CheckViolation):
                insert(conn, lot_id="L-MVP", at=T0, object_type="pliers", grade=None)
        applied = apply_migrations(target, MIGRATIONS)
        assert len(applied) == 1, applied  # only the tool migration was pending
        sql = tool_files[0].read_text(encoding="utf-8")
        with connect(target) as conn:
            conn.execute(sql)  # second run of the same file: no error
            conn.execute(sql)
            assert conn.execute("select count(*) from inspections").fetchone() == (11,)
            defective = conn.execute(
                "select count(*) from inspections where is_defective"
            ).fetchone()
            assert defective == (4,)
            insert(conn, lot_id="L-NEW", at=T0, object_type="pliers", grade=None)
            insert(conn, lot_id="L-NEW", at=T0, object_type="allen_key", grade="poor")
            with pytest.raises(psycopg.errors.CheckViolation):
                insert(conn, lot_id="L-NEW", at=T0, object_type="screw", grade=None)
            with pytest.raises(psycopg.errors.CheckViolation):
                insert(conn, lot_id="L-NEW", at=T0, object_type="unknown", grade="good")
            with pytest.raises(psycopg.errors.CheckViolation):
                insert(conn, lot_id="L-NEW", at=T0, object_type="hammer", grade="good")
            tool_defect = conn.execute(
                "select is_defective from inspections where object_type = 'allen_key'"
            ).fetchone()
            assert tool_defect == (True,)
            checks = conn.execute(
                "select count(*) from pg_constraint where conrelid = 'inspections'::regclass "
                "and contype = 'c'"
            ).fetchone()
        # Running the whole migration set again changes nothing.
        assert apply_migrations(target, MIGRATIONS) == []
        with connect(target) as conn:
            again = conn.execute(
                "select count(*) from pg_constraint where conrelid = 'inspections'::regclass "
                "and contype = 'c'"
            ).fetchone()
        assert again == checks
    finally:
        with connect(admin) as conn:
            conn.execute(f'drop database if exists "{name}" with (force)')
