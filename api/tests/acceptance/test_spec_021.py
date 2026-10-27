"""Acceptance tests for SPEC-021 (database and qc-api: the 4 power tools, never in the SPC).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-03 (database) and CA-04 (API and SPC). Tests named ``test_extra_*``
are exploratory edge cases around SPEC-021 sections 3.1 and 4 that no CA spells out.

Every test uses the migrated test database of the ``db`` marker (``clean_db`` from SPEC-003);
rows are inserted with plain SQL or through the public routes. Device keys are generated at run
time, never written as literals (R-03). The migration test creates, and drops, a separate
database whose name contains ``test``; it never runs an older migration again on the shared
session database.
"""

from __future__ import annotations

import hashlib
import re
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
HAND_TOOLS = [
    "pliers",
    "adjustable_wrench",
    "allen_key",
    "flat_screwdriver",
    "phillips_screwdriver",
]
POWER_TOOLS = ["angle_grinder", "saw", "drill", "cordless_screwdriver"]
ALL_TYPES = ["screw", "nut", "unknown", *HAND_TOOLS, *POWER_TOOLS]
GRADES = ["perfect", "good", "fair", "poor", "unusable"]
SCORES = {g: float(i) for i, g in enumerate(GRADES)}
# The SpcObjectType enum of SPEC-016 (CA-05 there): unchanged by SPEC-021 (section 3.1).
SPC_ENUM_016 = ["screw", "nut", *HAND_TOOLS]

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
    source: str = "live",
) -> None:
    """``poor`` rows with grade ``poor``, the others with ``grade`` (``None`` = no grade)."""
    for i in range(n):
        g = "poor" if i < poor else grade
        insert(
            conn,
            lot_id=lot_id,
            at=start + timedelta(minutes=i),
            object_type=object_type,
            grade=g,
            source=source,
        )


def payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-021",
        "inspected_at": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
        "object_type": "drill",
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


def spc_enums(doc: dict[str, Any]) -> list[list[str]]:
    params = doc["paths"][URL_SPC]["get"]["parameters"]
    (param,) = [p for p in params if p["name"] == "object_type"]
    schema = param["schema"]
    enums: list[list[str]] = []
    for node in [schema, *schema.get("anyOf", [])]:
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            assert name == "SpcObjectType", name
            node = doc["components"]["schemas"][name]
        if "enum" in node:
            enums.append(node["enum"])
    return enums


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
    assert len(outcomes) == 72
    for (object_type, grade), sqlstate in outcomes.items():
        if contract_accepts(object_type, grade):
            assert sqlstate is None, (object_type, grade, sqlstate)
        else:
            assert sqlstate == "23514", (object_type, grade, sqlstate)
    # Sanity of the expectation itself: 2*5 (screw, nut) + 1*5 (unknown, power tools)
    # + 5*6 (hand tools) accepted pairs.
    assert sum(1 for s in outcomes.values() if s is None) == 45
    for tool in POWER_TOOLS:
        assert outcomes[(tool, None)] is None, tool
        assert all(outcomes[(tool, g)] == "23514" for g in GRADES), tool
    with connect(env.db) as conn:
        count = conn.execute("select count(*) from inspections").fetchone()
    assert count == (45,)


# --------------------------------------------------------------------------- CA-04


@pytest.mark.db
def test_ca04_post_drill_without_grade_is_201(env: Env) -> None:
    body = payload()
    resp = env.write(URL_INSPECTIONS, body)
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"inspection_id": body["inspection_id"], "status": "created"}
    listed = env.read(URL_INSPECTIONS, {"object_type": "drill"}).json()
    assert listed["total"] == 1
    (item,) = listed["items"]
    assert item["object_type"] == "drill"
    assert item["grade"] is None and item["grade_score"] is None
    assert item["grade_confidence"] is None
    assert item["is_defective"] is False


@pytest.fixture
def ca04_env(env: Env) -> Env:
    with connect(env.db) as conn:
        for i, lot_id in enumerate(("L-01", "L-02", "L-03")):
            insert_many(conn, lot_id, T0 + timedelta(hours=i), 10, poor=1)
        insert_many(conn, "L-04", T0 + timedelta(hours=3), 10, object_type="drill", grade=None)
    return env


@pytest.mark.db
def test_ca04_spc_leaves_the_drill_lot_out(ca04_env: Env) -> None:
    resp = ca04_env.read(URL_SPC, {"source": "live"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    SpcResponse.model_validate(data)
    assert all(p["lot_id"] != "L-04" for p in data["points"]), data["points"]
    assert all(e["lot_id"] != "L-04" for e in data["excluded_lots"]), data["excluded_lots"]
    assert [p["lot_id"] for p in data["points"]] == ["L-01", "L-02", "L-03"]
    assert [p["n"] for p in data["points"]] == [10, 10, 10]
    assert [p["defects"] for p in data["points"]] == [1, 1, 1]
    assert data["p_bar"] == pytest.approx(0.1)


@pytest.mark.db
def test_ca04_spc_filter_by_drill_is_422(ca04_env: Env) -> None:
    resp = ca04_env.read(URL_SPC, {"source": "live", "object_type": "drill"})
    assert resp.status_code == 422, resp.text
    assert "detail" in resp.json()


@pytest.mark.db
def test_ca04_openapi_spc_object_type_enum_is_the_spec016_one(env: Env) -> None:
    resp = env.client.get("/openapi.json")
    assert resp.status_code == 200
    doc = resp.json()
    assert spc_enums(doc) == [SPC_ENUM_016]
    assert doc["components"]["schemas"]["SpcObjectType"]["enum"] == SPC_ENUM_016


# --------------------------------------------------------------------------- extras


@pytest.mark.db
@pytest.mark.parametrize("tool", POWER_TOOLS)
def test_extra_spc_filter_by_any_power_tool_is_422(env: Env, tool: str) -> None:
    resp = env.read(URL_SPC, {"object_type": tool})
    assert resp.status_code == 422, (tool, resp.text)
    assert "Traceback" not in resp.text


@pytest.mark.db
def test_extra_post_power_tool_with_grade_is_422_and_not_stored(env: Env) -> None:
    cases = [
        payload(object_type=t, grade="good", grade_score=1.0, grade_confidence=0.8)
        for t in POWER_TOOLS
    ]
    cases.append(payload(object_type="saw", grade=None, grade_score=2.0))
    cases.append(payload(object_type="saw", grade=None, grade_confidence=0.6))
    for body in cases:
        resp = env.write(URL_INSPECTIONS, body)
        assert resp.status_code == 422, (body["object_type"], resp.text)
    # A batch with one graded power tool is refused whole (SPEC-004).
    resp = env.write(URL_BATCH, {"items": [payload(), cases[0]]})
    assert resp.status_code == 422, resp.text
    assert env.read(URL_INSPECTIONS).json()["total"] == 0


@pytest.mark.db
def test_extra_batch_of_power_tools_is_idempotent(env: Env) -> None:
    items = [payload(object_type=t, lot_id="L-BATCH") for t in POWER_TOOLS]
    resp = env.write(URL_BATCH, {"items": items})
    assert resp.status_code == 200, resp.text
    assert [r["status"] for r in resp.json()["results"]] == ["created"] * 4
    again = env.write(URL_BATCH, {"items": items})
    assert [r["status"] for r in again.json()["results"]] == ["duplicate"] * 4
    assert env.read(URL_INSPECTIONS, {"limit": 500}).json()["total"] == 4


@pytest.mark.db
def test_extra_summary_leaves_power_tools_out_of_the_defect_rate(env: Env) -> None:
    with connect(env.db) as conn:
        insert_many(conn, "L-A", T0, 10, poor=2)
        for i, tool in enumerate(POWER_TOOLS):
            insert_many(
                conn, f"L-P{i}", T0 + timedelta(hours=1 + i), i + 1, object_type=tool, grade=None
            )
    body = env.read(URL_SUMMARY).json()
    MetricsSummary.model_validate(body)
    assert body["total"] == 10 + 1 + 2 + 3 + 4
    assert body["defective"] == 2
    assert body["defect_rate"] == pytest.approx(0.2)
    assert body["unknown_count"] == 0  # a power tool is not "unknown"
    assert sum(body["by_grade"].values()) == 10
    assert body["by_object_type"] == {t.value: 0 for t in ObjectType} | {
        "screw": 10,
        "angle_grinder": 1,
        "saw": 2,
        "drill": 3,
        "cordless_screwdriver": 4,
    }
    only = env.read(URL_SUMMARY, {"object_type": "drill"}).json()
    assert only["total"] == 3 and only["defect_rate"] is None
    assert only["mean_grade_score"] is None


@pytest.mark.db
def test_extra_timeseries_defect_rate_ignores_power_tools(env: Env) -> None:
    with connect(env.db) as conn:
        insert_many(conn, "L-A", T0, 10, poor=5)
        insert_many(conn, "L-D", T0 + timedelta(minutes=20), 10, object_type="saw", grade=None)
    params = {"bucket": "hour", "from": T0.isoformat(), "to": (T0 + timedelta(hours=2)).isoformat()}
    resp = env.read(URL_SERIES, params)
    assert resp.status_code == 200, resp.text
    (point,) = [p for p in resp.json() if p["bucket_start"].startswith("2026-11-02T08")]
    assert (point["total"], point["defective"]) == (20, 5)
    assert point["defect_rate"] == pytest.approx(0.5)


@pytest.mark.db
def test_extra_power_tools_inside_a_screw_lot_do_not_change_n(env: Env) -> None:
    with connect(env.db) as conn:
        insert_many(conn, "L-01", T0, 10, poor=2)
        insert_many(conn, "L-02", T0 + timedelta(hours=1), 10, poor=1)
        insert_many(conn, "L-01", T0 + timedelta(seconds=20), 6, object_type="drill", grade=None)
        # A lot with only 4 screws plus 6 power tools stays below min_lot_size (5) for the SPC.
        insert_many(conn, "L-03", T0 + timedelta(hours=2), 4, poor=0)
        insert_many(
            conn, "L-03", T0 + timedelta(hours=2, seconds=30), 6, object_type="saw", grade=None
        )
    data = env.read(URL_SPC, {"source": "live"}).json()
    points = {p["lot_id"]: p for p in data["points"]}
    assert points["L-01"]["n"] == 10 and points["L-01"]["defects"] == 2
    assert "L-03" not in points
    excluded = {e["lot_id"]: e for e in data["excluded_lots"]}
    assert "L-03" in excluded, data["excluded_lots"]
    assert excluded["L-03"]["n"] == 4


@pytest.mark.db
def test_extra_simulated_power_tool_rows_keep_their_source(env: Env) -> None:
    """R-06: a simulated power tool stays simulated; the default SPC source is live."""
    resp = env.write(URL_INSPECTIONS, payload(source="simulated"))
    assert resp.status_code == 201, resp.text
    item = env.read(URL_INSPECTIONS, {"source": "simulated"}).json()["items"][0]
    assert item["source"] == "simulated" and item["object_type"] == "drill"
    assert env.read(URL_INSPECTIONS, {"source": "live"}).json()["total"] == 0


@pytest.mark.db
def test_extra_list_filter_by_each_power_tool(env: Env) -> None:
    with connect(env.db) as conn:
        for i, tool in enumerate(POWER_TOOLS):
            insert_many(
                conn, f"L-E{i}", T0 + timedelta(hours=i), i + 2, object_type=tool, grade=None
            )
    for i, tool in enumerate(POWER_TOOLS):
        page = env.read(URL_INSPECTIONS, {"object_type": tool}).json()
        assert page["total"] == i + 2, tool
        assert {it["grade"] for it in page["items"]} == {None}
    for value in ("Drill", "drill ", "furadeira", "lathe"):
        assert env.read(URL_INSPECTIONS, {"object_type": value}).status_code == 422, value
    graded = env.read(URL_INSPECTIONS, {"object_type": "drill", "grade": "good"}).json()
    assert graded["total"] == 0


@pytest.mark.db
def test_extra_health_reports_contract_at_least_0_6_0(env: Env) -> None:
    body = env.client.get(URL_HEALTH).json()
    assert body["status"] == "ok"
    v = body["contract_version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", v)
    assert (0, 6, 0) <= tuple(int(p) for p in v.split(".")) < (1, 0, 0)


# --------------------------------------------------------------------------- migration


def _other_db(conninfo: str, name: str) -> str:
    return make_conninfo(conninfo, dbname=name)


@pytest.mark.db
def test_extra_power_tool_migration_keeps_rows_and_runs_again(
    db_conninfo: str, tmp_path: Path
) -> None:
    """Section 3.1: the new migration keeps every valid earlier row and can run again."""
    from migrate import apply_migrations

    name = f"partqc_test_spec021_{secrets.token_hex(3)}"
    assert "test" in name
    admin = _other_db(db_conninfo, conninfo_to_dict(db_conninfo).get("dbname") or "postgres")
    with connect(admin) as conn:
        conn.execute(f'create database "{name}"')
    target = _other_db(db_conninfo, name)
    try:
        files = sorted(MIGRATIONS.glob("*.sql"))
        power = [p for p in files if p.name.endswith("_power_tool_object_types.sql")]
        assert len(power) == 1, files
        assert power[0] == files[-1] or all(
            "object_type" not in p.read_text(encoding="utf-8")
            for p in files[files.index(power[0]) + 1 :]
        )
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        for path in files[: files.index(power[0])]:
            shutil.copy(path, old_dir / path.name)
        apply_migrations(target, old_dir)
        with connect(target) as conn:
            conn.execute(
                "insert into devices (device_id, api_key_hash) values ('edge-01', %s)",
                (hashlib.sha256(b"x").hexdigest(),),
            )
            for grade in GRADES:
                insert(conn, lot_id="L-OLD", at=T0, object_type="screw", grade=grade)
                insert(conn, lot_id="L-OLD", at=T0, object_type="pliers", grade=grade)
            insert(conn, lot_id="L-OLD", at=T0, object_type="unknown", grade=None)
            insert(conn, lot_id="L-OLD", at=T0, object_type="allen_key", grade=None)
            with pytest.raises(psycopg.errors.CheckViolation):
                insert(conn, lot_id="L-OLD", at=T0, object_type="drill", grade=None)
        applied = apply_migrations(target, MIGRATIONS)
        assert len(applied) == len(files) - files.index(power[0]), applied
        sql = power[0].read_text(encoding="utf-8")
        with connect(target) as conn:
            conn.execute(sql)  # second and third run of the same file: no error
            conn.execute(sql)
            assert conn.execute("select count(*) from inspections").fetchone() == (12,)
            defective = conn.execute(
                "select count(*) from inspections where is_defective"
            ).fetchone()
            assert defective == (4,)  # screw and pliers, poor and unusable
            for tool in POWER_TOOLS:
                insert(conn, lot_id="L-NEW", at=T0, object_type=tool, grade=None)
                with pytest.raises(psycopg.errors.CheckViolation):
                    insert(conn, lot_id="L-NEW", at=T0, object_type=tool, grade="good")
            insert(conn, lot_id="L-NEW", at=T0, object_type="pliers", grade="fair")
            with pytest.raises(psycopg.errors.CheckViolation):
                insert(conn, lot_id="L-NEW", at=T0, object_type="nut", grade=None)
            with pytest.raises(psycopg.errors.CheckViolation):
                insert(conn, lot_id="L-NEW", at=T0, object_type="unknown", grade="poor")
            with pytest.raises(psycopg.errors.CheckViolation):
                insert(conn, lot_id="L-NEW", at=T0, object_type="lathe", grade=None)
            power_defect = conn.execute(
                "select bool_or(is_defective) from inspections where object_type = 'drill'"
            ).fetchone()
            assert power_defect == (False,)
            checks = conn.execute(
                "select count(*) from pg_constraint where conrelid = 'inspections'::regclass "
                "and contype = 'c'"
            ).fetchone()
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
