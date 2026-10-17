"""``GET /api/v1/metrics/spc`` against the test PostgreSQL (SPEC-006 sections 4.2 and 4.4) and
the cut of SPEC-026 (sections 4.3 and 4.4: ``lot_selection`` and ``max_points``).

The lots of Example 1 are inserted with SQL (not through the API) as ``live`` screws: in each
lot, ``defects`` rows ``poor`` and the others ``good``, one minute apart. ``L-001`` also has 3
``unknown`` rows, and ``L-SIM`` is a ``simulated`` lot with ``n=10``, ``defects=9``. All tests
are marked ``db``.
"""

from __future__ import annotations

import random
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from qc_api.main import create_app
from qc_api.repositories import inspections as repository
from qc_api.services.spc import LotCounts, compute_p_chart, select_lots
from qc_contracts import ObjectType, Source, SpcResponse

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
        "max_points": 100,
        "valid_lots_total": 0,
        "excluded_lots_total": 0,
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


# --- SPEC-026: the cut ---------------------------------------------------------------------------

# One lot of ``n`` rows one second apart from ``start``: the first ``defects`` are ``poor``.
INSERT_LOT = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
)
select
    gen_random_uuid(), %(device_id)s, %(lot_id)s, %(start)s + make_interval(secs => i),
    %(object_type)s, case when i < %(defects)s then 'poor' else 'good' end, 1.0, 0.9, 0.8, false,
    'partqc-mnv3-v1', %(sha)s, 100, %(source)s
from generate_series(0, %(n)s - 1) as i
"""

# ``count`` lots ``<prefix><k>`` of one ``good`` row each, ``k`` seconds after ``start``.
INSERT_SINGLE_ROW_LOTS = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
)
select
    gen_random_uuid(), 'edge-01', %(prefix)s || k, %(start)s + make_interval(secs => k),
    'screw', 'good', 1.0, 0.9, 0.8, false, 'partqc-mnv3-v1', %(sha)s, 100, 'live'
from generate_series(1, %(count)s) as k
"""


def add_lot(
    db: psycopg.Connection,
    lot_id: str,
    start: datetime,
    n: int,
    defects: int,
    object_type: str = "screw",
    source: str = "live",
) -> LotCounts:
    """Inserts the lot with SQL and returns what the SPC should read for it."""
    db.execute(
        INSERT_LOT,
        {
            "device_id": "sim-01" if source == "simulated" else "edge-01",
            "lot_id": lot_id,
            "start": start,
            "n": n,
            "defects": defects,
            "object_type": object_type,
            "source": source,
            "sha": SHA,
        },
    )
    return LotCounts(lot_id, start, start + timedelta(seconds=n - 1), n, defects)


def cut_history(db: psycopg.Connection) -> list[LotCounts]:
    """130 valid lots ``C-0001..C-0130`` and 60 excluded lots ``X-001..X-060`` (CA-11)."""
    lots = [add_lot(db, f"C-{k:04d}", T0 + timedelta(minutes=k), 5, k % 3) for k in range(1, 131)]
    lots += [
        add_lot(db, f"X-{k:03d}", T0 + timedelta(minutes=k, seconds=30), 1, 0) for k in range(1, 61)
    ]
    return lots


def test_example_1_has_the_default_cap_and_totals(example_db, reader: TestClient) -> None:
    body = get_spc(reader, baseline_lots=3)
    assert_example_1(body)
    assert (body["max_points"], body["valid_lots_total"], body["excluded_lots_total"]) == (
        100,
        6,
        1,
    )


def test_route_cuts_to_the_latest_lots(
    device_keys, db: psycopg.Connection, reader: TestClient
) -> None:
    lots = cut_history(db)
    body = get_spc(reader)
    assert [point["lot_id"] for point in body["points"]] == [f"C-{k:04d}" for k in range(31, 131)]
    base = range(1, 21)
    assert body["p_bar"] == pytest.approx(sum(k % 3 for k in base) / (5 * len(base)))
    assert [item["lot_id"] for item in body["excluded_lots"]] == [
        f"X-{k:03d}" for k in range(11, 61)
    ]
    assert (body["max_points"], body["valid_lots_total"], body["excluded_lots_total"]) == (
        100,
        130,
        60,
    )
    expected = compute_p_chart(lots, 20, 5, source=Source.LIVE, max_points=100, max_excluded=50)
    assert body == expected.model_dump(mode="json")

    small = get_spc(reader, max_points=10)
    assert [point["lot_id"] for point in small["points"]] == [f"C-{k:04d}" for k in range(121, 131)]
    assert small["p_bar"] == body["p_bar"]
    assert small["points"] == body["points"][-10:]


def test_route_ties_use_the_c_collation(
    device_keys, db: psycopg.Connection, reader: TestClient
) -> None:
    lots = [
        add_lot(db, "a-1", T0, 10, 9),
        add_lot(db, "B-1", T0, 10, 1),
        add_lot(db, "_-1", T0, 10, 5),
    ]
    body = get_spc(reader, baseline_lots=2, max_points=2)
    assert [point["lot_id"] for point in body["points"]] == ["_-1", "a-1"]
    assert body["p_bar"] == pytest.approx(0.3)
    expected = compute_p_chart(lots, 2, 5, max_points=2, max_excluded=50)
    assert body == expected.model_dump(mode="json")


def test_route_simulated_lots_never_enter_the_live_cut(
    device_keys, db: psycopg.Connection, reader: TestClient
) -> None:
    cut_history(db)
    for k in range(1, 6):
        add_lot(db, f"S-{k}", T0 + timedelta(hours=10, minutes=k), 5, 1, source="simulated")
    live = get_spc(reader)
    shown = {p["lot_id"] for p in live["points"]} | {e["lot_id"] for e in live["excluded_lots"]}
    assert not any(lot_id.startswith("S-") for lot_id in shown)
    assert live["valid_lots_total"] == 130
    simulated = get_spc(reader, source="simulated")
    assert [p["lot_id"] for p in simulated["points"]] == [f"S-{k}" for k in range(1, 6)]
    assert (simulated["valid_lots_total"], simulated["excluded_lots_total"]) == (5, 0)
    assert simulated["source"] == "simulated"


def test_route_large_history_is_bounded(
    device_keys, db: psycopg.Connection, reader: TestClient
) -> None:
    db.execute(INSERT_SINGLE_ROW_LOTS, {"prefix": "V-", "start": T0, "count": 3000, "sha": SHA})
    for k in range(1, 151):
        add_lot(db, f"G-{k:03d}", T0 + timedelta(hours=2, minutes=k), 5, 0)
    response = reader.get(URL, headers=R)
    assert response.status_code == 200
    body = response.json()
    assert len(body["points"]) == 100
    assert len(body["excluded_lots"]) == 50
    assert (body["valid_lots_total"], body["excluded_lots_total"]) == (150, 3000)
    assert body["points"][-1]["lot_id"] == "G-150"
    assert body["excluded_lots"][-1]["lot_id"] == "V-3000"
    assert len(response.content) < 64 * 1024


@pytest.mark.parametrize("value", [0, 1, 501, "abc", 2.5, ""])
def test_invalid_max_points_is_422(example_db, reader: TestClient, value: Any) -> None:
    response = reader.get(URL, params={"max_points": value}, headers=R)
    assert response.status_code == 422, value
    assert isinstance(response.json()["detail"], list)
    assert "Traceback" not in response.text


@pytest.mark.parametrize("value", [2, 500])
def test_boundary_max_points_is_200(example_db, reader: TestClient, value: int) -> None:
    assert get_spc(reader, max_points=value)["max_points"] == value


def test_missing_key_is_401_before_max_points_validation(example_db, reader: TestClient) -> None:
    response = reader.get(URL, params={"max_points": 0})
    assert response.status_code == 401
    assert response.json() == {"detail": "Missing or invalid API key"}


# --- SPEC-026: lot_selection against select_lots ----------------------------------------------

LOT_ID_ALPHABET = "ABCXYZabcxyz0189_-"


def random_lots(rng: random.Random, count: int) -> list[tuple[str, datetime, int, int, str]]:
    """``(lot_id, start, n, defects, object_type)`` with distinct ids and frequent time ties."""
    used: set[str] = set()
    lots = []
    for _ in range(count):
        lot_id = "".join(rng.choice(LOT_ID_ALPHABET) for _ in range(rng.randint(1, 3)))
        if lot_id in used:
            continue
        used.add(lot_id)
        n = rng.randint(1, 12)
        start = T0 + timedelta(minutes=rng.randint(0, 15))
        lots.append((lot_id, start, n, rng.randint(0, n), rng.choice(["screw", "nut"])))
    return lots


@pytest.mark.parametrize("seed", range(4))
def test_lot_selection_matches_select_lots(
    seed: int, device_keys, db: psycopg.Connection, reader: TestClient
) -> None:
    rng = random.Random(seed)
    rows = random_lots(rng, 80)
    lots = [
        add_lot(db, lot_id, start, n, defects, object_type)
        for lot_id, start, n, defects, object_type in rows
    ]
    pool = reader.app.state.pool
    for _ in range(6):
        params = {
            "baseline_lots": rng.randint(1, 30),
            "min_lot_size": rng.randint(1, 8),
            "max_points": rng.choice([None, rng.randint(1, 40)]),
            "max_excluded": rng.choice([None, 0, rng.randint(1, 20)]),
        }
        got = repository.lot_selection(pool, Source.LIVE, None, **params)
        assert got == select_lots(lots, **params), params

    screws = [item for item, row in zip(lots, rows, strict=True) if row[4] == "screw"]
    params = {"baseline_lots": 5, "min_lot_size": 3, "max_points": 7, "max_excluded": 4}
    got = repository.lot_selection(pool, Source.LIVE, ObjectType.SCREW, **params)
    assert got == select_lots(screws, **params)
    assert repository.lot_selection(pool, Source.SIMULATED, None, **params) == select_lots(
        [], **params
    )


@pytest.mark.parametrize(
    "params",
    [
        {"baseline_lots": 0, "min_lot_size": 5, "max_points": 2, "max_excluded": 0},
        {"baseline_lots": 3, "min_lot_size": 0, "max_points": 2, "max_excluded": 0},
        {"baseline_lots": 3, "min_lot_size": 5, "max_points": 0, "max_excluded": 0},
        {"baseline_lots": 3, "min_lot_size": 5, "max_points": 2, "max_excluded": -1},
    ],
)
def test_lot_selection_rejects_invalid_parameters(reader: TestClient, params: dict) -> None:
    with pytest.raises(ValueError):
        repository.lot_selection(reader.app.state.pool, Source.LIVE, None, **params)


def test_rows_reaching_python_are_bounded(device_keys, db: psycopg.Connection) -> None:
    db.execute(INSERT_SINGLE_ROW_LOTS, {"prefix": "V-", "start": T0, "count": 500, "sha": SHA})
    for k in range(1, 41):
        add_lot(db, f"G-{k:03d}", T0 + timedelta(hours=1, minutes=k), 5, 1)
    where = sql.SQL("object_type <> %(unknown)s and source = %(f_source)s")
    query = sql.SQL(repository.SELECT_LOT_SELECTION).format(where=where)
    params = {
        "unknown": "unknown",
        "f_source": "live",
        "baseline_lots": 3,
        "min_lot_size": 5,
        "max_points": 7,
        "max_excluded": 11,
    }
    rows = db.execute(query, params).fetchall()
    assert len(rows) == 3 + 7 + 11 + 1


def test_lot_selection_sql_is_cut_in_the_database() -> None:
    text = repository.SELECT_LOT_SELECTION
    assert text.count("materialized") == 1
    assert text.count("from inspections") == 1  # one aggregation per request
    assert 'collate "C"' in text
    for name in ("baseline_lots", "max_points", "max_excluded"):
        assert re.search(rf"limit\s+%\({name}\)s", text), name
    assert "%(min_lot_size)s" in text
