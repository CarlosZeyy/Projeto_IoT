"""Acceptance tests for SPEC-006 (qc-api: p chart by lot, ``GET /api/v1/metrics/spc``).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test per CA (``test_caNN_*``); ``test_extra_*`` tests are exploratory edge
cases around SPEC-006 section 4 that no CA spells out.

Reference values were recomputed by hand (``EXPECTED_*`` below) and compared with the SPEC
tables with the absolute tolerance of the SPEC (``5e-5``, 4 decimal places).

The CA-10 database is inserted with plain SQL into the migrated test database (``clean_db`` from
SPEC-003), with ``edge-01`` and ``sim-01`` registered by hash. Device keys and fake passwords are
built at run time, never written as literals (R-03).

CA-16 (coverage gate): per ``docs/architecture.md`` section 10, no test runs a whole
``testpaths`` directory in a subprocess. The test below checks that the step exists in
``ci.yml`` after the pytest step; the command itself is run by hand and recorded in the test
report.
"""

from __future__ import annotations

import ast
import hashlib
import math
import random
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlunsplit

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient

from qc_api.config import Settings
from qc_api.main import create_app
from qc_api.services.spc import LotCounts, compute_p_chart
from qc_contracts import Source, SpcResponse

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
SPC_MODULE = ROOT / "api" / "src" / "qc_api" / "services" / "spc.py"
CI_FILE = ROOT / ".github" / "workflows" / "ci.yml"

URL = "/api/v1/metrics/spc"
R = "r" * 32
SHA = "a" * 64
TOL = 5e-5
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)

UNAUTHORIZED = {"detail": "Missing or invalid API key"}
DB_DOWN = {"detail": "Database unavailable"}

# Example 1 of SPEC-006 section 4.4: (lot_id, hours after T0, n, defects).
EXAMPLE_1: tuple[tuple[str, int, int, int], ...] = (
    ("L-001", 0, 20, 2),
    ("L-002", 1, 25, 3),
    ("L-003", 2, 4, 1),
    ("L-004", 3, 20, 4),
    ("L-005", 4, 20, 12),
    ("L-006", 5, 25, 0),
    ("L-007", 6, 100, 1),
)
VALID_ORDER = ["L-001", "L-002", "L-004", "L-005", "L-006", "L-007"]

# Table of section 4.4 (Example 1, baseline_lots=3): lot -> (p, cl, ucl, lcl, out_of_control).
EXPECTED_1: dict[str, tuple[float, float, float, float, bool]] = {
    "L-001": (0.1000, 0.1385, 0.3702, 0.0000, False),
    "L-002": (0.1200, 0.1385, 0.3457, 0.0000, False),
    "L-004": (0.2000, 0.1385, 0.3702, 0.0000, False),
    "L-005": (0.6000, 0.1385, 0.3702, 0.0000, True),
    "L-006": (0.0000, 0.1385, 0.3457, 0.0000, False),
    "L-007": (0.0100, 0.1385, 0.2421, 0.0348, True),
}
P_BAR_1 = 0.1385
# Example 2 (defaults): p_bar, ucl per n and lcl(n=100).
P_BAR_2 = 0.1048
UCL_2 = {"L-001": 0.3102, "L-002": 0.2885, "L-004": 0.3102, "L-005": 0.3102, "L-006": 0.2885}
UCL_2["L-007"] = 0.1966
LCL_2 = {lot: 0.0 for lot in VALID_ORDER} | {"L-007": 0.0129}


# --------------------------------------------------------------------------- helpers


def close(actual: float | None, expected: float) -> bool:
    return actual is not None and abs(actual - expected) <= TOL


def lot(lot_id: str, n: int, defects: int, hours: float = 0.0) -> LotCounts:
    start = T0 + timedelta(hours=hours)
    return LotCounts(
        lot_id=lot_id,
        started_at=start,
        ended_at=start + timedelta(minutes=30),
        n=n,
        defects=defects,
    )


def example_1() -> list[LotCounts]:
    return [lot(lot_id, n, d, hours) for lot_id, hours, n, d in EXAMPLE_1]


def as_dict(resp: SpcResponse) -> dict[str, Any]:
    return resp.model_dump(mode="json")


def points_by_lot(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["lot_id"]: p for p in data["points"]}


def assert_example_1(data: dict[str, Any]) -> None:
    """``data`` is a JSON-like SpcResponse; asserts every CA-01 value."""
    assert close(data["p_bar"], P_BAR_1), data["p_bar"]
    assert [p["lot_id"] for p in data["points"]] == VALID_ORDER
    for point in data["points"]:
        p, cl, ucl, lcl, ooc = EXPECTED_1[point["lot_id"]]
        assert close(point["p"], p), point
        assert close(point["cl"], cl), point
        assert close(point["ucl"], ucl), point
        assert close(point["lcl"], lcl), point
        assert point["out_of_control"] is ooc, point
    assert data["excluded_lots"] == [{"lot_id": "L-003", "n": 4}]
    assert data["message"] is None


def assert_example_2(data: dict[str, Any]) -> None:
    assert close(data["p_bar"], P_BAR_2), data["p_bar"]
    pts = points_by_lot(data)
    assert [p["lot_id"] for p in data["points"]] == VALID_ORDER
    for lot_id in VALID_ORDER:
        assert close(pts[lot_id]["ucl"], UCL_2[lot_id]), pts[lot_id]
        assert close(pts[lot_id]["lcl"], LCL_2[lot_id]), pts[lot_id]
    assert [p["lot_id"] for p in data["points"] if p["out_of_control"]] == ["L-005", "L-007"]
    assert data["baseline_lots"] == 20
    assert data["min_lot_size"] == 5
    assert data["source"] == "live"
    assert data["excluded_lots"] == [{"lot_id": "L-003", "n": 4}]
    assert data["message"] is None


def key_header(key: str | None) -> dict[str, str]:
    return {"X-API-Key": key} if key is not None else {}


def connect(conninfo: str) -> psycopg.Connection:
    return psycopg.connect(conninfo, autocommit=True, prepare_threshold=None)


def no_db_url() -> str:
    """URL of a database on a closed local port; the fake password is built at run time."""
    password = "pw" + secrets.token_hex(4)
    return urlunsplit(("postgresql", f"u:{password}@127.0.0.1:1", "/x", "", ""))


INSERT_ROW = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
) values (%s, %s, %s, %s, %s, %s, %s, 0.9, %s, false, 'partqc-mnv3-v1', %s, 42, %s)
"""


def insert(
    conn: psycopg.Connection,
    *,
    lot_id: str,
    at: datetime,
    object_type: str = "screw",
    grade: str | None = "good",
    source: str = "live",
    device: str | None = None,
) -> None:
    device = device or ("sim-01" if source == "simulated" else "edge-01")
    score = None if grade is None else 1.0
    conf = None if grade is None else 0.8
    conn.execute(
        INSERT_ROW,
        (str(uuid.uuid4()), device, lot_id, at, object_type, grade, score, conf, SHA, source),
    )


def insert_lot(
    conn: psycopg.Connection,
    lot_id: str,
    start: datetime,
    n: int,
    defects: int,
    *,
    object_type: str = "screw",
    source: str = "live",
) -> None:
    """``defects`` rows ``poor`` and ``n - defects`` rows ``good``, one minute apart."""
    for i in range(n):
        grade = "poor" if i < defects else "good"
        insert(
            conn,
            lot_id=lot_id,
            at=start + timedelta(minutes=i % 50, seconds=i // 50),
            object_type=object_type,
            grade=grade,
            source=source,
        )


@dataclass
class Env:
    db: str
    client: TestClient
    keys: dict[str, str]

    def get(self, params: Any = None, key: str | None = R) -> Any:
        return self.client.get(URL, params=params, headers=key_header(key))


@pytest.fixture
def empty_env(clean_db: str) -> Iterator[Env]:
    keys = {"edge-01": secrets.token_urlsafe(32), "sim-01": secrets.token_urlsafe(32)}
    with connect(clean_db) as conn:
        for device_id, key in keys.items():
            conn.execute(
                "insert into devices (device_id, api_key_hash) values (%s, %s)",
                (device_id, hashlib.sha256(key.encode()).hexdigest()),
            )
    app = create_app(Settings(DATABASE_URL=clean_db, READ_API_KEY=R))
    with TestClient(app) as client:
        yield Env(clean_db, client, keys)


@pytest.fixture
def ca10_env(empty_env: Env) -> Env:
    """Example 1 as live screw inspections, 3 unknown rows in L-001 and L-SIM simulated."""
    with connect(empty_env.db) as conn:
        for lot_id, hours, n, defects in EXAMPLE_1:
            insert_lot(conn, lot_id, T0 + timedelta(hours=hours), n, defects)
        for i in range(3):
            insert(
                conn,
                lot_id="L-001",
                at=T0 + timedelta(minutes=5 + i),
                object_type="unknown",
                grade=None,
            )
        insert_lot(conn, "L-SIM", T0 + timedelta(hours=7), 10, 9, source="simulated")
    return empty_env


# --------------------------------------------------------------------------- CA-01


def test_ca01_example_1_with_baseline_3() -> None:
    resp = compute_p_chart(example_1(), baseline_lots=3, min_lot_size=5)
    assert isinstance(resp, SpcResponse)
    assert resp.p_bar is not None
    assert abs(resp.p_bar - P_BAR_1) <= TOL
    assert resp.baseline_lots == 3
    assert resp.min_lot_size == 5
    assert resp.source == Source.LIVE
    assert_example_1(as_dict(resp))
    # The points carry the lot counts unchanged.
    by_lot = {p.lot_id: p for p in resp.points}
    for lot_id, _hours, n, defects in EXAMPLE_1:
        if lot_id in by_lot:
            assert (by_lot[lot_id].n, by_lot[lot_id].defects) == (n, defects)


# --------------------------------------------------------------------------- CA-02


def test_ca02_example_2_defaults() -> None:
    resp = compute_p_chart(example_1())
    assert_example_2(as_dict(resp))
    # Exact base of Example 2: 22/210 (the 6 valid lots).
    assert resp.p_bar == pytest.approx(22 / 210, abs=1e-12)


# --------------------------------------------------------------------------- CA-03


def test_ca03_shuffled_input_same_result_and_not_mutated() -> None:
    reference = as_dict(compute_p_chart(example_1(), baseline_lots=3, min_lot_size=5))
    for seed in range(5):
        lots = example_1()
        random.Random(seed).shuffle(lots)
        snapshot = list(lots)
        result = as_dict(compute_p_chart(lots, baseline_lots=3, min_lot_size=5))
        assert result == reference, seed
        assert_example_1(result)
        assert lots == snapshot, seed
        assert [a is b for a, b in zip(lots, snapshot, strict=True)] == [True] * len(lots)
    # reversed order (deterministic worst case)
    lots = list(reversed(example_1()))
    snapshot = list(lots)
    assert as_dict(compute_p_chart(lots, baseline_lots=3, min_lot_size=5)) == reference
    assert lots == snapshot


# --------------------------------------------------------------------------- CA-04


def test_ca04_ties_on_started_at_are_ordered_by_lot_id() -> None:
    lots = [lot("L-B", 10, 1), lot("L-A", 10, 2)]
    resp = compute_p_chart(lots)
    assert [p.lot_id for p in resp.points] == ["L-A", "L-B"]
    assert [p.lot_id for p in lots] == ["L-B", "L-A"]


# --------------------------------------------------------------------------- CA-05


def test_ca05_p_bar_zero_collapses_limits() -> None:
    lots = [lot("L-1", 10, 0, 0), lot("L-2", 10, 0, 1), lot("L-3", 10, 1, 2)]
    resp = compute_p_chart(lots, baseline_lots=2)
    assert resp.p_bar == 0
    assert len(resp.points) == 3
    for point in resp.points:
        assert point.ucl == 0
        assert point.lcl == 0
        assert point.cl == 0
    assert resp.points[2].p == pytest.approx(0.1, abs=1e-12)
    assert [p.out_of_control for p in resp.points] == [False, False, True]
    assert resp.message is None


# --------------------------------------------------------------------------- CA-06


def test_ca06_p_bar_one_collapses_limits() -> None:
    lots = [lot("L-1", 5, 5, 0), lot("L-2", 5, 5, 1), lot("L-3", 5, 4, 2)]
    resp = compute_p_chart(lots, baseline_lots=2)
    assert resp.p_bar == 1
    for point in resp.points:
        assert point.ucl == 1
        assert point.lcl == 1
        assert point.cl == 1
    assert resp.points[2].p == pytest.approx(0.8, abs=1e-12)
    assert [p.out_of_control for p in resp.points] == [False, False, True]


# --------------------------------------------------------------------------- CA-07


def test_ca07_insufficient_data() -> None:
    resp = compute_p_chart([lot("L-1", 20, 2, 0), lot("L-2", 3, 1, 1)], min_lot_size=5)
    assert resp.points == []
    assert resp.p_bar is None
    assert as_dict(resp)["excluded_lots"] == [{"lot_id": "L-2", "n": 3}]
    assert resp.message == "insufficient data: need at least 2 lots with n >= 5 (found 1)"
    assert as_dict(resp)["p_bar"] is None

    empty = compute_p_chart([])
    assert empty.points == []
    assert empty.p_bar is None
    assert empty.excluded_lots == []
    assert empty.message is not None
    assert empty.message.endswith("(found 0)")
    assert empty.message == "insufficient data: need at least 2 lots with n >= 5 (found 0)"


# --------------------------------------------------------------------------- CA-08


def test_ca08_limits_are_clipped_to_unit_interval() -> None:
    lots = [lot("L-1", 5, 4, 0), lot("L-2", 5, 4, 1), lot("L-3", 5, 5, 2)]
    resp = compute_p_chart(lots, baseline_lots=2)
    assert resp.p_bar == pytest.approx(0.8, abs=1e-12)
    # Unclipped, p_bar + 3 sigma = 0.8 + 3*sqrt(0.16/5) > 1.
    assert 0.8 + 3 * math.sqrt(0.8 * 0.2 / 5) > 1
    assert len(resp.points) == 3
    for point in resp.points:
        assert point.ucl <= 1.0
        assert point.lcl >= 0.0
        assert point.ucl == 1.0
        assert abs(point.lcl - (0.8 - 3 * math.sqrt(0.16 / 5))) <= TOL
    # p = 1.0 equals the clipped ucl: strict inequality, so it is in control.
    assert [p.out_of_control for p in resp.points] == [False, False, False]


# --------------------------------------------------------------------------- CA-09


@pytest.mark.parametrize(("n", "defects"), [(5, 6), (5, -1), (0, 0)])
def test_ca09_invalid_lot_counts_raise(n: int, defects: int) -> None:
    with pytest.raises(ValueError):
        LotCounts(lot_id="L-X", started_at=T0, ended_at=T0, n=n, defects=defects)


@pytest.mark.parametrize("kwargs", [{"baseline_lots": 0}, {"min_lot_size": 0}])
def test_ca09_invalid_parameters_raise(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        compute_p_chart(example_1(), **kwargs)
    # Also with an empty list: the parameters are checked first (step 1).
    with pytest.raises(ValueError):
        compute_p_chart([], **kwargs)


# --------------------------------------------------------------------------- CA-10


@pytest.mark.db
def test_ca10_route_example_1_live_without_unknown_and_simulated(ca10_env: Env) -> None:
    resp = ca10_env.get({"baseline_lots": 3})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    SpcResponse.model_validate(data)
    assert_example_1(data)
    assert data["source"] == "live"
    assert data["baseline_lots"] == 3
    assert data["min_lot_size"] == 5
    pts = points_by_lot(data)
    assert pts["L-001"]["n"] == 20
    assert pts["L-001"]["defects"] == 2
    assert "L-SIM" not in pts
    assert all(e["lot_id"] != "L-SIM" for e in data["excluded_lots"])
    for lot_id, _hours, n, defects in EXAMPLE_1:
        if lot_id in pts:
            assert (pts[lot_id]["n"], pts[lot_id]["defects"]) == (n, defects), lot_id


# --------------------------------------------------------------------------- CA-11


@pytest.mark.db
def test_ca11_route_defaults_match_example_2(ca10_env: Env) -> None:
    resp = ca10_env.get()
    assert resp.status_code == 200, resp.text
    assert_example_2(resp.json())


# --------------------------------------------------------------------------- CA-12


@pytest.mark.db
def test_ca12_source_and_object_type_filters(ca10_env: Env) -> None:
    resp = ca10_env.get({"source": "simulated"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["points"] == []
    assert data["p_bar"] is None
    assert data["source"] == "simulated"
    assert data["message"].endswith("(found 1)")
    assert data["excluded_lots"] == []

    resp = ca10_env.get({"object_type": "nut"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["points"] == []
    assert data["p_bar"] is None
    assert data["message"].endswith("(found 0)")
    assert data["source"] == "live"

    reference = ca10_env.get({"baseline_lots": 3})
    resp = ca10_env.get({"object_type": "screw", "baseline_lots": 3})
    assert resp.status_code == 200, resp.text
    assert resp.json() == reference.json()
    assert_example_1(resp.json())


# --------------------------------------------------------------------------- CA-13


@pytest.mark.db
def test_ca13_parameter_validation(ca10_env: Env) -> None:
    for params in (
        {"baseline_lots": 1},
        {"baseline_lots": 101},
        {"min_lot_size": 0},
        {"min_lot_size": 501},
        {"source": "all"},
        {"object_type": "unknown"},
    ):
        resp = ca10_env.get(params)
        assert resp.status_code == 422, (params, resp.text)
        assert "detail" in resp.json()
        assert "Traceback" not in resp.text
    for params, field_name in (
        ({"baseline_lots": 2}, "baseline_lots"),
        ({"baseline_lots": 100}, "baseline_lots"),
        ({"min_lot_size": 1}, "min_lot_size"),
        ({"min_lot_size": 500}, "min_lot_size"),
    ):
        resp = ca10_env.get(params)
        assert resp.status_code == 200, (params, resp.text)
        assert resp.json()[field_name] == params[field_name]


# --------------------------------------------------------------------------- CA-14


@pytest.mark.db
def test_ca14_auth_401(ca10_env: Env) -> None:
    for key in (None, ca10_env.keys["edge-01"], ca10_env.keys["sim-01"]):
        resp = ca10_env.get(key=key)
        assert resp.status_code == 401, resp.text
        assert resp.json() == UNAUTHORIZED
    assert ca10_env.get().status_code == 200


def test_ca14_without_database_401_and_503() -> None:
    app = create_app(Settings(DATABASE_URL=no_db_url(), READ_API_KEY=R))
    with TestClient(app) as client:
        resp = client.get(URL)
        assert resp.status_code == 401, resp.text
        assert resp.json() == UNAUTHORIZED
        resp = client.get(URL, headers=key_header(R))
        assert resp.status_code == 503, resp.text
        assert resp.json() == DB_DOWN


# --------------------------------------------------------------------------- CA-15


FORBIDDEN_MODULES = {"psycopg", "fastapi", "logging", "os", "time"}


def test_ca15_spc_module_is_pure() -> None:
    source = SPC_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 or node.module is not None
            if node.module:
                imported.add(node.module.split(".")[0])
            # ``from datetime import now``-like tricks and ``from x import os`` too.
            imported.update(alias.name.split(".")[0] for alias in node.names)
    assert not imported & FORBIDDEN_MODULES, imported & FORBIDDEN_MODULES
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "utcnow", "today"}, ast.unparse(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"__import__", "open", "print", "eval", "exec"}
    assert "datetime.now" not in source
    assert "__import__" not in source
    assert "importlib" not in source


# --------------------------------------------------------------------------- CA-16


GATE = (
    'uv run pytest api/tests -q -m "not db" --cov=qc_api.services '
    "--cov-report=term-missing --cov-fail-under=80"
)


def _ci_runs() -> list[str]:
    workflow = yaml.safe_load(CI_FILE.read_text(encoding="utf-8"))
    runs: list[str] = []
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if "run" in step:
                runs.append(" ".join(str(step["run"]).split()))
    return runs


def test_ca16_coverage_gate_step_in_ci_after_pytest() -> None:
    runs = _ci_runs()
    assert GATE in runs, runs
    # The CA-16 command (without --cov-report) is contained in the step.
    assert GATE.startswith('uv run pytest api/tests -q -m "not db" --cov=qc_api.services ')
    assert GATE.endswith(" --cov-fail-under=80")
    assert "uv run pytest -q" in runs
    assert runs.index(GATE) > runs.index("uv run pytest -q")
    assert runs.index(GATE) > runs.index("uv sync --all-packages --frozen")


def test_ca16_pytest_cov_is_available() -> None:
    """The gate needs ``pytest-cov`` in the environment CI syncs."""
    import pytest_cov  # noqa: F401


# --------------------------------------------------------------------------- exploratory


def test_extra_points_carry_period_and_counts() -> None:
    lots = [
        LotCounts("L-1", T0, T0 + timedelta(minutes=9), 10, 1),
        LotCounts("L-2", T0 + timedelta(hours=1), T0 + timedelta(hours=2), 12, 3),
    ]
    resp = compute_p_chart(lots)
    first = resp.points[0]
    assert first.started_at == T0
    assert first.ended_at == T0 + timedelta(minutes=9)
    assert (first.n, first.defects) == (10, 1)
    assert first.p == pytest.approx(0.1, abs=1e-12)


def test_extra_orders_by_instant_not_by_offset() -> None:
    minus3 = timezone(timedelta(hours=-3))
    # L-A at 06:00-03:00 = 09:00Z; L-B at 08:30Z: L-B comes first.
    lots = [
        LotCounts(
            "L-A", datetime(2026, 10, 1, 6, 0, tzinfo=minus3), T0 + timedelta(hours=2), 10, 1
        ),
        LotCounts("L-B", datetime(2026, 10, 1, 8, 30, tzinfo=UTC), T0 + timedelta(hours=1), 10, 1),
    ]
    assert [p.lot_id for p in compute_p_chart(lots).points] == ["L-B", "L-A"]


def test_extra_baseline_uses_first_valid_lots_skipping_excluded() -> None:
    # baseline_lots=2 counts valid lots only: L-1 and L-3 (L-2 is excluded).
    lots = [lot("L-1", 10, 1, 0), lot("L-2", 2, 2, 1), lot("L-3", 10, 3, 2), lot("L-4", 10, 9, 3)]
    resp = compute_p_chart(lots, baseline_lots=2)
    assert resp.p_bar == pytest.approx(4 / 20, abs=1e-12)
    assert [e.lot_id for e in resp.excluded_lots] == ["L-2"]
    assert [p.cl for p in resp.points] == [pytest.approx(0.2, abs=1e-12)] * 3


def test_extra_excluded_lots_follow_sorted_order() -> None:
    lots = [lot("L-Z", 1, 0, 3), lot("L-1", 10, 1, 0), lot("L-Y", 2, 1, 1), lot("L-2", 10, 1, 2)]
    resp = compute_p_chart(lots)
    assert [(e.lot_id, e.n) for e in resp.excluded_lots] == [("L-Y", 2), ("L-Z", 1)]


def test_extra_lot_at_min_lot_size_is_valid_and_min_one_keeps_all() -> None:
    resp = compute_p_chart(example_1(), min_lot_size=4)
    assert "L-003" in [p.lot_id for p in resp.points]
    assert resp.excluded_lots == []
    resp = compute_p_chart(example_1(), min_lot_size=1)
    assert len(resp.points) == 7
    resp = compute_p_chart(example_1(), min_lot_size=21)
    assert [p.lot_id for p in resp.points] == ["L-002", "L-006", "L-007"]


def test_extra_source_is_only_copied_and_keyword_only() -> None:
    live = as_dict(compute_p_chart(example_1()))
    sim = as_dict(compute_p_chart(example_1(), source=Source.SIMULATED))
    assert sim["source"] == "simulated"
    assert {k: v for k, v in sim.items() if k != "source"} == {
        k: v for k, v in live.items() if k != "source"
    }
    with pytest.raises(TypeError):
        compute_p_chart(example_1(), 20, 5, Source.LIVE)  # type: ignore[misc]


def test_extra_not_rounded() -> None:
    resp = compute_p_chart(example_1(), baseline_lots=3)
    assert resp.p_bar == pytest.approx(9 / 65, abs=1e-12)
    ucl = 9 / 65 + 3 * math.sqrt((9 / 65) * (56 / 65) / 20)
    assert resp.points[0].ucl == pytest.approx(ucl, abs=1e-12)


def test_extra_lot_counts_frozen_and_boundaries() -> None:
    item = LotCounts("L-1", T0, T0, 1, 0)
    with pytest.raises(FrozenInstanceError):
        item.n = 2  # type: ignore[misc]
    LotCounts("L-1", T0, T0, 1, 1)
    LotCounts("L-1", T0, T0, 7, 7)


def test_extra_tuple_input_and_many_lots() -> None:
    lots = tuple(lot(f"L-{i:04d}", 50, i % 7, i) for i in range(2000))
    resp = compute_p_chart(lots)
    assert len(resp.points) == 2000
    for point in resp.points:
        assert 0.0 <= point.lcl <= point.cl <= point.ucl <= 1.0
        assert point.out_of_control == (point.p > point.ucl or point.p < point.lcl)


def test_extra_tiny_p_bar_does_not_break_sqrt() -> None:
    big = 10**12
    lots = [lot("L-1", big, 1, 0), lot("L-2", big, 0, 1), lot("L-3", big, big, 2)]
    resp = compute_p_chart(lots, baseline_lots=2)
    for point in resp.points:
        assert math.isfinite(point.ucl)
        assert math.isfinite(point.lcl)
    assert resp.points[2].out_of_control is True


def test_extra_naive_datetimes_are_not_silently_accepted() -> None:
    """Records how a naive ``started_at`` behaves (the SPEC does not say; see the report)."""
    naive = datetime(2026, 10, 1, 8, 0)
    try:
        lots = [LotCounts("L-1", naive, naive, 10, 1), LotCounts("L-2", naive, naive, 10, 1)]
        resp = compute_p_chart(lots)
    except (ValueError, TypeError):
        return
    for point in resp.points:
        assert point.started_at.tzinfo is not None


@pytest.mark.db
def test_extra_route_unknown_rows_do_not_move_started_at(empty_env: Env) -> None:
    with connect(empty_env.db) as conn:
        insert_lot(conn, "L-1", T0, 10, 1)
        insert_lot(conn, "L-2", T0 + timedelta(hours=1), 10, 2)
        # unknown row earlier than the lot's first graded row
        insert(conn, lot_id="L-1", at=T0 - timedelta(hours=5), object_type="unknown", grade=None)
        # a lot made only of unknown rows does not appear at all
        for i in range(6):
            insert(
                conn,
                lot_id="L-U",
                at=T0 + timedelta(hours=3, minutes=i),
                object_type="unknown",
                grade=None,
            )
    data = empty_env.get().json()
    assert [p["lot_id"] for p in data["points"]] == ["L-1", "L-2"]
    first = data["points"][0]
    started = datetime.fromisoformat(first["started_at"].replace("Z", "+00:00"))
    assert started == T0
    assert started.utcoffset() == timedelta(0)
    assert first["n"] == 10
    assert data["excluded_lots"] == []


@pytest.mark.db
def test_extra_route_same_lot_id_in_both_sources_is_never_mixed(empty_env: Env) -> None:
    with connect(empty_env.db) as conn:
        insert_lot(conn, "L-1", T0, 10, 1)
        insert_lot(conn, "L-2", T0 + timedelta(hours=1), 10, 1)
        insert_lot(conn, "L-1", T0 + timedelta(hours=2), 10, 10, source="simulated")
        insert_lot(conn, "L-9", T0 + timedelta(hours=3), 10, 0, source="simulated")
    live = empty_env.get().json()
    assert [(p["lot_id"], p["n"], p["defects"]) for p in live["points"]] == [
        ("L-1", 10, 1),
        ("L-2", 10, 1),
    ]
    sim = empty_env.get({"source": "simulated"}).json()
    assert sim["source"] == "simulated"
    assert [(p["lot_id"], p["n"], p["defects"]) for p in sim["points"]] == [
        ("L-1", 10, 10),
        ("L-9", 10, 0),
    ]
    assert sim["p_bar"] == pytest.approx(0.5, abs=1e-12)


@pytest.mark.db
def test_extra_route_pools_types_without_filter_and_splits_with_it(empty_env: Env) -> None:
    with connect(empty_env.db) as conn:
        insert_lot(conn, "L-1", T0, 6, 1)
        insert_lot(conn, "L-1", T0 + timedelta(minutes=55), 4, 3, object_type="nut")
        insert_lot(conn, "L-2", T0 + timedelta(hours=1), 10, 0, object_type="nut")
    pooled = empty_env.get().json()
    assert [(p["lot_id"], p["n"], p["defects"]) for p in pooled["points"]] == [
        ("L-1", 10, 4),
        ("L-2", 10, 0),
    ]
    # nut: L-1 has 4 nut rows (excluded), L-2 has 10 -> one valid lot only.
    nut = empty_env.get({"object_type": "nut"}).json()
    assert nut["points"] == []
    assert nut["excluded_lots"] == [{"lot_id": "L-1", "n": 4}]
    assert nut["message"].endswith("(found 1)")
    # screw: L-1 has 6 screw rows (valid), no other screw lot.
    screw = empty_env.get({"object_type": "screw"}).json()
    assert screw["points"] == []
    assert screw["excluded_lots"] == []
    assert screw["message"].endswith("(found 1)")


@pytest.mark.db
def test_extra_route_orders_by_time_not_by_lot_id(empty_env: Env) -> None:
    with connect(empty_env.db) as conn:
        insert_lot(conn, "Z-first", T0, 10, 1)
        insert_lot(conn, "A-second", T0 + timedelta(hours=1), 10, 1)
    data = empty_env.get().json()
    assert [p["lot_id"] for p in data["points"]] == ["Z-first", "A-second"]


@pytest.mark.db
def test_extra_route_min_lot_size_one_keeps_small_lot(ca10_env: Env) -> None:
    data = ca10_env.get({"min_lot_size": 1}).json()
    assert "L-003" in [p["lot_id"] for p in data["points"]]
    assert data["excluded_lots"] == []
    assert data["min_lot_size"] == 1


@pytest.mark.db
def test_extra_route_empty_database(empty_env: Env) -> None:
    resp = empty_env.get()
    assert resp.status_code == 200
    data = resp.json()
    assert data["points"] == []
    assert data["excluded_lots"] == []
    assert data["p_bar"] is None
    assert data["message"] == "insufficient data: need at least 2 lots with n >= 5 (found 0)"


@pytest.mark.db
def test_extra_route_more_invalid_parameters(ca10_env: Env) -> None:
    for query in (
        "baseline_lots=abc",
        "baseline_lots=2.5",
        "min_lot_size=",
        "source=LIVE",
        "object_type=SCREW",
        "object_type=screw'%20or%201=1--",
        "baseline_lots=-5",
    ):
        resp = ca10_env.client.get(f"{URL}?{query}", headers=key_header(R))
        assert resp.status_code == 422, (query, resp.text)
        assert "Traceback" not in resp.text


@pytest.mark.db
def test_extra_route_wrong_key_is_401_before_validation(ca10_env: Env) -> None:
    resp = ca10_env.get({"baseline_lots": 1}, key="wrong-" + secrets.token_hex(4))
    assert resp.status_code == 401
    assert resp.json() == UNAUTHORIZED
