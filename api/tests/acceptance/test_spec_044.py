"""Acceptance tests for SPEC-044 (database and qc-api: hammer, wrench and spirit level).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-03 (database, migration 007) and CA-04 (API and SPC). Tests named
``test_extra_*`` are exploratory edge cases around SPEC-044 sections 3.1, 4.1 and 4.2 that no CA
spells out.

Every test uses the migrated test database of the ``db`` marker (``clean_db`` from SPEC-003);
rows are inserted with plain SQL or through the public routes. Device keys are generated at run
time, never written as literals (R-03). Migration 007 is the latest one, so running it again on
the session database (CA-03) leaves it as the session fixture built it. The migration extra
creates, and drops, a separate database whose name contains ``test``.
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
MIGRATION_007 = MIGRATIONS / "007_identified_tool_object_types.sql"
CHECK_NAMES = ("inspections_object_type_check", "inspections_grade_null_iff_unknown")

R = "r" * 32
SHA = "c" * 64
T0 = datetime(2026, 11, 4, 8, 0, tzinfo=UTC)
HAND_TOOLS = [
    "pliers",
    "adjustable_wrench",
    "allen_key",
    "flat_screwdriver",
    "phillips_screwdriver",
]
POWER_TOOLS = ["angle_grinder", "saw", "drill", "cordless_screwdriver"]
NEW_TOOLS = ["hammer", "wrench", "spirit_level"]
ALL_TYPES = ["screw", "nut", "unknown", *HAND_TOOLS, *POWER_TOOLS, *NEW_TOOLS]
GRADES = ["perfect", "good", "fair", "poor", "unusable"]
SCORES = {g: float(i) for i, g in enumerate(GRADES)}
# The SpcObjectType enum of SPEC-016 (CA-05 there), unchanged by SPEC-044 (section 3.1).
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
CONSTRAINT_DEFS = """
select conname, pg_get_constraintdef(oid) from pg_constraint
where conrelid = 'inspections'::regclass and conname = any(%s) order by conname
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
        "lot_id": "L-044",
        "inspected_at": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
        "object_type": "hammer",
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


def constraint_defs(conn: psycopg.Connection) -> list[tuple[str, str]]:
    return [tuple(r) for r in conn.execute(CONSTRAINT_DEFS, (list(CHECK_NAMES),)).fetchall()]


# --------------------------------------------------------------------------- CA-03


@pytest.mark.db
def test_ca03_database_accepts_exactly_the_contract_pairs(env: Env) -> None:
    assert [m.value for m in ObjectType] == ALL_TYPES
    outcomes: dict[tuple[str, str | None], str | None] = {}
    with connect(env.db) as conn:
        for object_type in ALL_TYPES:
            for grade in [*GRADES, None]:
                try:
                    insert(conn, lot_id="L-CA03", at=T0, object_type=object_type, grade=grade)
                    outcomes[(object_type, grade)] = None
                except psycopg.Error as exc:
                    outcomes[(object_type, grade)] = exc.sqlstate
    assert len(outcomes) == 90
    for (object_type, grade), sqlstate in outcomes.items():
        if contract_accepts(object_type, grade):
            assert sqlstate is None, (object_type, grade, sqlstate)
        else:
            assert sqlstate == "23514", (object_type, grade, sqlstate)
    # Sanity of the expectation itself: 2*5 (screw, nut) + 8*1 (unknown, power and new tools)
    # + 5*6 (hand tools) accepted pairs.
    assert sum(1 for s in outcomes.values() if s is None) == 48
    for tool in NEW_TOOLS:
        assert outcomes[(tool, None)] is None, tool
        assert all(outcomes[(tool, g)] == "23514" for g in GRADES), tool
    with connect(env.db) as conn:
        count = conn.execute("select count(*) from inspections").fetchone()
    assert count == (48,)


@pytest.mark.db
def test_ca03_migration_007_runs_again_without_changing_the_checks(env: Env) -> None:
    sql = MIGRATION_007.read_text(encoding="utf-8")
    with connect(env.db) as conn:
        before = constraint_defs(conn)
        assert [name for name, _ in before] == sorted(CHECK_NAMES)
        conn.execute(sql)
        after = constraint_defs(conn)
        conn.execute(sql)
        again = constraint_defs(conn)
    assert after == before
    assert again == before
    for _, definition in before:
        assert "spirit_level" in definition


# --------------------------------------------------------------------------- CA-04


@pytest.mark.db
def test_ca04_post_hammer_without_grade_is_201(env: Env) -> None:
    body = payload()
    resp = env.write(URL_INSPECTIONS, body)
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"inspection_id": body["inspection_id"], "status": "created"}
    listed = env.read(URL_INSPECTIONS, {"object_type": "hammer"}).json()
    assert listed["total"] == 1
    (item,) = listed["items"]
    assert item["object_type"] == "hammer"
    assert item["grade"] is None and item["grade_score"] is None
    assert item["grade_confidence"] is None
    assert item["is_defective"] is False


@pytest.mark.db
def test_ca04_post_hammer_with_grade_is_422_and_not_stored(env: Env) -> None:
    body = payload(grade="good", grade_score=1.0, grade_confidence=0.8)
    resp = env.write(URL_INSPECTIONS, body)
    assert resp.status_code == 422, resp.text
    assert env.read(URL_INSPECTIONS).json()["total"] == 0
    with connect(env.db) as conn:
        assert conn.execute("select count(*) from inspections").fetchone() == (0,)


@pytest.fixture
def ca04_env(env: Env) -> Env:
    with connect(env.db) as conn:
        for i, lot_id in enumerate(("L-01", "L-02", "L-03")):
            insert_many(conn, lot_id, T0 + timedelta(hours=i), 10, poor=1)
        insert_many(conn, "L-04", T0 + timedelta(hours=3), 10, object_type="wrench", grade=None)
    return env


@pytest.mark.db
def test_ca04_spc_leaves_the_wrench_lot_out(ca04_env: Env) -> None:
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
def test_ca04_spc_filter_by_wrench_is_422(ca04_env: Env) -> None:
    resp = ca04_env.read(URL_SPC, {"source": "live", "object_type": "wrench"})
    assert resp.status_code == 422, resp.text
    assert "detail" in resp.json()


@pytest.mark.db
def test_ca04_summary_counts_the_wrenches(ca04_env: Env) -> None:
    resp = ca04_env.read(URL_SUMMARY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    MetricsSummary.model_validate(body)
    assert body["by_object_type"]["wrench"] == 10
    assert body["total"] == 40
    assert body["defective"] == 3
    assert body["defect_rate"] == pytest.approx(0.1)


@pytest.mark.db
def test_ca04_list_filter_by_spirit_level_is_200(env: Env) -> None:
    resp = env.read(URL_INSPECTIONS, {"object_type": "spirit_level"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 0


@pytest.mark.db
def test_ca04_openapi_spc_object_type_enum_is_the_spec016_one(env: Env) -> None:
    resp = env.client.get("/openapi.json")
    assert resp.status_code == 200
    doc = resp.json()
    assert spc_enums(doc) == [SPC_ENUM_016]
    assert doc["components"]["schemas"]["SpcObjectType"]["enum"] == SPC_ENUM_016


@pytest.mark.db
def test_ca04_health_reports_contract_0_7_0(env: Env) -> None:
    resp = env.client.get(URL_HEALTH)
    assert resp.status_code == 200, resp.text
    assert resp.json()["contract_version"] == "0.7.0"


# --------------------------------------------------------------------------- extras


@pytest.mark.db
@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_extra_spc_filter_by_any_new_tool_is_422(env: Env, tool: str) -> None:
    resp = env.read(URL_SPC, {"object_type": tool})
    assert resp.status_code == 422, (tool, resp.text)
    assert "Traceback" not in resp.text


@pytest.mark.db
def test_extra_new_tool_payloads_with_grade_fields_are_422_and_batch_refused_whole(
    env: Env,
) -> None:
    cases = [
        payload(object_type=t, grade="perfect", grade_score=0.0, grade_confidence=0.9)
        for t in NEW_TOOLS
    ]
    cases.append(payload(object_type="wrench", grade_score=2.0))
    cases.append(payload(object_type="spirit_level", grade_confidence=0.6))
    for body in cases:
        resp = env.write(URL_INSPECTIONS, body)
        assert resp.status_code == 422, (body["object_type"], resp.text)
        assert "Traceback" not in resp.text
    resp = env.write(URL_BATCH, {"items": [payload(), cases[0]]})
    assert resp.status_code == 422, resp.text
    assert env.read(URL_INSPECTIONS).json()["total"] == 0


@pytest.mark.db
def test_extra_batch_of_new_tools_is_idempotent(env: Env) -> None:
    items = [payload(object_type=t, lot_id="L-BATCH") for t in NEW_TOOLS]
    resp = env.write(URL_BATCH, {"items": items})
    assert resp.status_code == 200, resp.text
    assert [r["status"] for r in resp.json()["results"]] == ["created"] * 3
    again = env.write(URL_BATCH, {"items": items})
    assert [r["status"] for r in again.json()["results"]] == ["duplicate"] * 3
    single = env.write(URL_INSPECTIONS, items[0])
    assert single.status_code in (200, 201), single.text
    assert single.json()["status"] == "duplicate"
    assert env.read(URL_INSPECTIONS, {"limit": 500}).json()["total"] == 3


@pytest.mark.db
def test_extra_summary_by_object_type_has_15_keys_and_new_tools_have_no_rate(env: Env) -> None:
    with connect(env.db) as conn:
        insert_many(conn, "L-A", T0, 10, poor=2)
        for i, tool in enumerate(NEW_TOOLS):
            insert_many(
                conn, f"L-N{i}", T0 + timedelta(hours=1 + i), i + 1, object_type=tool, grade=None
            )
    body = env.read(URL_SUMMARY).json()
    assert body["total"] == 10 + 1 + 2 + 3
    assert body["defective"] == 2
    assert body["defect_rate"] == pytest.approx(0.2)
    assert body["unknown_count"] == 0
    assert body["by_object_type"] == {t.value: 0 for t in ObjectType} | {
        "screw": 10,
        "hammer": 1,
        "wrench": 2,
        "spirit_level": 3,
    }
    assert len(body["by_object_type"]) == 15
    only = env.read(URL_SUMMARY, {"object_type": "spirit_level"}).json()
    assert only["total"] == 3
    assert only["defect_rate"] is None and only["mean_grade_score"] is None


@pytest.mark.db
def test_extra_timeseries_defect_rate_ignores_new_tools(env: Env) -> None:
    with connect(env.db) as conn:
        insert_many(conn, "L-A", T0, 10, poor=5)
        insert_many(conn, "L-H", T0 + timedelta(minutes=20), 10, object_type="hammer", grade=None)
    params = {"bucket": "hour", "from": T0.isoformat(), "to": (T0 + timedelta(hours=2)).isoformat()}
    resp = env.read(URL_SERIES, params)
    assert resp.status_code == 200, resp.text
    (point,) = [p for p in resp.json() if p["bucket_start"].startswith("2026-11-04T08")]
    assert (point["total"], point["defective"]) == (20, 5)
    assert point["defect_rate"] == pytest.approx(0.5)


@pytest.mark.db
def test_extra_new_tools_inside_a_screw_lot_do_not_change_n(env: Env) -> None:
    with connect(env.db) as conn:
        insert_many(conn, "L-01", T0, 10, poor=2)
        insert_many(conn, "L-02", T0 + timedelta(hours=1), 10, poor=1)
        insert_many(
            conn, "L-01", T0 + timedelta(seconds=20), 6, object_type="spirit_level", grade=None
        )
        insert_many(conn, "L-03", T0 + timedelta(hours=2), 4, poor=0)
        insert_many(
            conn, "L-03", T0 + timedelta(hours=2, seconds=30), 6, object_type="hammer", grade=None
        )
    data = env.read(URL_SPC, {"source": "live"}).json()
    points = {p["lot_id"]: p for p in data["points"]}
    assert points["L-01"]["n"] == 10 and points["L-01"]["defects"] == 2
    assert "L-03" not in points
    excluded = {e["lot_id"]: e for e in data["excluded_lots"]}
    assert "L-03" in excluded and excluded["L-03"]["n"] == 4


@pytest.mark.db
def test_extra_list_filter_by_each_new_tool_and_invalid_variants(env: Env) -> None:
    with connect(env.db) as conn:
        for i, tool in enumerate(NEW_TOOLS):
            insert_many(
                conn, f"L-E{i}", T0 + timedelta(hours=i), i + 2, object_type=tool, grade=None
            )
    for i, tool in enumerate(NEW_TOOLS):
        page = env.read(URL_INSPECTIONS, {"object_type": tool}).json()
        assert page["total"] == i + 2, tool
        assert {it["grade"] for it in page["items"]} == {None}
    for value in ("Hammer", "hammer ", "martelo", "level", "spirit-level", "nível"):
        resp = env.read(URL_INSPECTIONS, {"object_type": value})
        assert resp.status_code == 422, value
    graded = env.read(URL_INSPECTIONS, {"object_type": "wrench", "grade": "good"}).json()
    assert graded["total"] == 0


@pytest.mark.db
def test_extra_simulated_new_tool_keeps_its_source(env: Env) -> None:
    """R-06: a simulated new tool stays simulated."""
    resp = env.write(URL_INSPECTIONS, payload(object_type="wrench", source="simulated"))
    assert resp.status_code == 201, resp.text
    item = env.read(URL_INSPECTIONS, {"source": "simulated"}).json()["items"][0]
    assert item["source"] == "simulated" and item["object_type"] == "wrench"
    assert env.read(URL_INSPECTIONS, {"source": "live"}).json()["total"] == 0


@pytest.mark.db
def test_extra_database_rejects_out_of_enum_and_case_variants(env: Env) -> None:
    with connect(env.db) as conn:
        for value in ("Hammer", "level", "spirit-level", "lathe", "martelo"):
            with pytest.raises(psycopg.errors.CheckViolation):
                insert(conn, lot_id="L-X", at=T0, object_type=value, grade=None)
        insert(conn, lot_id="L-X", at=T0, object_type="wrench", grade=None)
        defect = conn.execute(
            "select is_defective from inspections where object_type = 'wrench'"
        ).fetchone()
    assert defect == (False,)


def test_extra_migration_007_has_the_shape_of_006() -> None:
    """Section 4.2: one DO block, no BEGIN/COMMIT, no credentials, the two check names."""
    text = MIGRATION_007.read_text(encoding="utf-8")
    code = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    lowered = code.lower()
    assert lowered.count("do $") + lowered.count("do\n$") >= 1
    assert not re.search(r"(?im)^\s*(begin|commit)\s*;", code)
    for name in CHECK_NAMES:
        assert name in code, name
    assert not re.search(r"(?i)(password|postgres(ql)?://|service_role|apikey)", code)
    for value in ALL_TYPES:
        assert f"'{value}'" in code, value


@pytest.mark.db
def test_extra_migration_007_keeps_older_rows_and_runs_again(
    db_conninfo: str, tmp_path: Path
) -> None:
    """Every row valid under 006 stays valid after 007, and 007 can run again."""
    from migrate import apply_migrations

    name = f"partqc_test_spec044_{secrets.token_hex(3)}"
    assert "test" in name
    admin = make_conninfo(
        db_conninfo, dbname=conninfo_to_dict(db_conninfo).get("dbname") or "postgres"
    )
    with connect(admin) as conn:
        conn.execute(f'create database "{name}"')
    target = make_conninfo(db_conninfo, dbname=name)
    try:
        files = sorted(MIGRATIONS.glob("*.sql"))
        assert MIGRATION_007 in files
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        for path in files[: files.index(MIGRATION_007)]:
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
            for value in ("unknown", "allen_key", *POWER_TOOLS):
                insert(conn, lot_id="L-OLD", at=T0, object_type=value, grade=None)
            with pytest.raises(psycopg.errors.CheckViolation):
                insert(conn, lot_id="L-OLD", at=T0, object_type="hammer", grade=None)
        applied = apply_migrations(target, MIGRATIONS)
        assert len(applied) == len(files) - files.index(MIGRATION_007), applied
        sql = MIGRATION_007.read_text(encoding="utf-8")
        with connect(target) as conn:
            defs = constraint_defs(conn)
            conn.execute(sql)
            conn.execute(sql)
            assert constraint_defs(conn) == defs
            assert conn.execute("select count(*) from inspections").fetchone() == (16,)
            for tool in NEW_TOOLS:
                insert(conn, lot_id="L-NEW", at=T0, object_type=tool, grade=None)
                with pytest.raises(psycopg.errors.CheckViolation):
                    insert(conn, lot_id="L-NEW", at=T0, object_type=tool, grade="fair")
            with pytest.raises(psycopg.errors.CheckViolation):
                insert(conn, lot_id="L-NEW", at=T0, object_type="nut", grade=None)
        assert apply_migrations(target, MIGRATIONS) == []
    finally:
        with connect(admin) as conn:
            conn.execute(f'drop database if exists "{name}" with (force)')
