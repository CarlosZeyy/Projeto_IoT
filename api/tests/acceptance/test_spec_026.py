"""Acceptance tests for SPEC-026 (qc-api: p chart cut to the latest lots, ADR-017).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-03 to CA-16 (the contract CA-01 and CA-02 live in
``packages/contracts/tests/acceptance/test_spec_026.py``). Tests named ``test_extra_*`` are
exploratory edge cases around SPEC-026 section 4 that no CA spells out.

Database data (CA-10 to CA-14, CA-16 and the route extras) is inserted with plain SQL into the
migrated test database (``clean_db`` from SPEC-003), with ``edge-01`` and ``sim-01`` registered
by hash. Device keys and fake passwords are built at run time, never written as literals (R-03).
No test here runs pytest in a subprocess (``docs/architecture.md`` section 10).
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import random
import re
import secrets
import string
import tracemalloc
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any
from urllib.parse import urlunsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

import qc_api.repositories.inspections as repo
from qc_api.auth import hash_api_key
from qc_api.config import Settings
from qc_api.main import create_app
from qc_api.services import spc
from qc_api.services.spc import (
    MAX_EXCLUDED_LOTS,
    LotCounts,
    LotSelection,
    build_p_chart,
    compute_p_chart,
    select_lots,
)
from qc_contracts import LOT_ID_PATTERN, Source

pytestmark = pytest.mark.acceptance

URL = "/api/v1/metrics/spc"
R = "r" * 32
SHA = "a" * 64
TOL = 5e-5
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
BRT = timezone(timedelta(hours=-3))

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
# SPEC-006 section 4.4 table (Example 1, baseline_lots=3): lot -> (p, cl, ucl, lcl, ooc).
EXPECTED_1: dict[str, tuple[float, float, float, float, bool]] = {
    "L-001": (0.1000, 0.1385, 0.3702, 0.0000, False),
    "L-002": (0.1200, 0.1385, 0.3457, 0.0000, False),
    "L-004": (0.2000, 0.1385, 0.3702, 0.0000, False),
    "L-005": (0.6000, 0.1385, 0.3702, 0.0000, True),
    "L-006": (0.0000, 0.1385, 0.3457, 0.0000, False),
    "L-007": (0.0100, 0.1385, 0.2421, 0.0348, True),
}
P_BAR_1 = 0.1385

LOT_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + "_-"


# --------------------------------------------------------------------------- helpers


def close(actual: float | None, expected: float) -> bool:
    return actual is not None and abs(actual - expected) <= TOL


def lc(
    lot_id: str,
    n: int,
    defects: int,
    start: datetime,
    end: datetime | None = None,
) -> LotCounts:
    return LotCounts(lot_id=lot_id, started_at=start, ended_at=end or start, n=n, defects=defects)


def example_1() -> list[LotCounts]:
    return [
        lc(lot_id, n, d, T0 + timedelta(hours=h), T0 + timedelta(hours=h, minutes=30))
        for lot_id, h, n, d in EXAMPLE_1
    ]


def ids(items: Sequence[Any]) -> list[str]:
    return [x.lot_id if hasattr(x, "lot_id") else x["lot_id"] for x in items]


def assert_example_1(data: dict[str, Any]) -> None:
    """SPEC-006 CA-01 values on a JSON-like SpcResponse."""
    assert close(data["p_bar"], P_BAR_1), data["p_bar"]
    assert ids(data["points"]) == VALID_ORDER
    for point in data["points"]:
        p, cl, ucl, lcl, ooc = EXPECTED_1[point["lot_id"]]
        assert close(point["p"], p), point
        assert close(point["cl"], cl), point
        assert close(point["ucl"], ucl), point
        assert close(point["lcl"], lcl), point
        assert point["out_of_control"] is ooc, point
    assert data["excluded_lots"] == [{"lot_id": "L-003", "n": 4}]
    assert data["message"] is None


def no_traceback(resp: Any) -> None:
    text = resp.text
    assert "Traceback" not in text, text
    assert 'File "' not in text, text
    assert "psycopg" not in text.lower(), text


def connect(conninfo: str) -> psycopg.Connection:
    return psycopg.connect(conninfo, autocommit=True, prepare_threshold=None)


def no_db_url() -> str:
    """URL of a database on a closed local port; the fake password is built at run time."""
    password = "pw" + secrets.token_hex(4)
    return urlunsplit(("postgresql", f"u:{password}@127.0.0.1:1", "/x", "", ""))


# One statement per lot: ``n`` rows, the first ``defects`` of them ``poor`` (defective), one
# second apart from ``start``. ``unknown`` rows are inserted separately.
INSERT_LOT = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
)
select gen_random_uuid(), %(device)s, %(lot_id)s,
       %(start)s::timestamptz + make_interval(secs => i - 1), %(object_type)s,
       case when i <= %(defects)s then 'poor' else 'good' end, 1.0, 0.9, 0.8, false,
       'partqc-mnv3-v1', %(sha)s, 42, %(source)s
from generate_series(1, %(n)s) as i
"""


@dataclass(frozen=True)
class DbLot:
    lot_id: str
    start: datetime
    n: int
    defects: int
    source: str = "live"
    object_type: str = "screw"

    def counts(self) -> LotCounts:
        """``LotCounts`` as the database aggregates it (rows one second apart)."""
        return lc(self.lot_id, self.n, self.defects, self.start, self.start + _secs(self.n - 1))


def _secs(s: int) -> timedelta:
    return timedelta(seconds=s)


def insert_lots(conn: psycopg.Connection, lots: Sequence[DbLot]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            INSERT_LOT,
            [
                {
                    "device": "sim-01" if lot.source == "simulated" else "edge-01",
                    "lot_id": lot.lot_id,
                    "start": lot.start,
                    "object_type": lot.object_type,
                    "defects": lot.defects,
                    "sha": SHA,
                    "source": lot.source,
                    "n": lot.n,
                }
                for lot in lots
            ],
        )


def insert_unknown(conn: psycopg.Connection, lot_id: str, at: datetime) -> None:
    conn.execute(
        """
        insert into inspections (
            inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
            type_confidence, grade_confidence, needs_review, model_version, model_sha256,
            latency_ms, source
        ) values (gen_random_uuid(), 'edge-01', %s, %s, 'unknown', null, null, 0.4, null,
                  true, 'partqc-mnv3-v1', %s, 42, 'live')
        """,
        (lot_id, at, SHA),
    )


@dataclass
class Env:
    db: str
    client: TestClient

    def get(self, params: Any = None, key: str | None = R) -> Any:
        headers = {"X-API-Key": key} if key is not None else {}
        return self.client.get(URL, params=params, headers=headers)

    def insert(self, lots: Sequence[DbLot]) -> None:
        with connect(self.db) as conn:
            insert_lots(conn, lots)


@pytest.fixture
def empty_env(clean_db: str) -> Iterator[Env]:
    keys = {"edge-01": secrets.token_urlsafe(32), "sim-01": secrets.token_urlsafe(32)}
    with connect(clean_db) as conn:
        for device_id, key in keys.items():
            conn.execute(
                "insert into devices (device_id, api_key_hash) values (%s, %s)",
                (device_id, hash_api_key(key)),
            )
    with TestClient(create_app(Settings(DATABASE_URL=clean_db, READ_API_KEY=R))) as client:
        yield Env(clean_db, client)


EXAMPLE_1_DB = [DbLot(lot_id, T0 + timedelta(hours=h), n, d) for lot_id, h, n, d in EXAMPLE_1]


@pytest.fixture
def ca10_env(empty_env: Env) -> Env:
    """SPEC-006 CA-10 database: Example 1 live screw, 3 unknown rows in L-001, L-SIM simulated."""
    with connect(empty_env.db) as conn:
        insert_lots(conn, EXAMPLE_1_DB)
        for i in range(3):
            insert_unknown(conn, "L-001", T0 + timedelta(minutes=5 + i))
        insert_lots(conn, [DbLot("L-SIM", T0 + timedelta(hours=7), 10, 9, source="simulated")])
    return empty_env


def ca11_lots() -> list[DbLot]:
    valid = [DbLot(f"C-{k:04d}", T0 + timedelta(minutes=k), 5, k % 3) for k in range(1, 131)]
    excluded = [
        DbLot(f"X-{k:03d}", T0 + timedelta(minutes=k, seconds=30), 1, 0) for k in range(1, 61)
    ]
    return valid + excluded


@pytest.fixture
def ca11_env(empty_env: Env) -> Env:
    empty_env.insert(ca11_lots())
    return empty_env


# --------------------------------------------------------------------------- CA-03


@pytest.mark.parametrize(
    "overrides",
    [
        {"n": True},
        {"n": 5.0},
        {"defects": False},
        {"defects": 1.5},
        {"started_at": datetime(2026, 10, 1, 8, 0)},
        {"ended_at": datetime(2026, 10, 1, 9, 0)},
    ],
    ids=["n-true", "n-float", "defects-false", "defects-float", "naive-start", "naive-end"],
)
def test_ca03_lot_counts_rejects_wrong_types_and_naive_datetimes(
    overrides: dict[str, Any],
) -> None:
    kwargs: dict[str, Any] = {
        "lot_id": "L-001",
        "started_at": T0,
        "ended_at": T0 + timedelta(hours=1),
        "n": 5,
        "defects": 1,
    }
    kwargs.update(overrides)
    with pytest.raises(ValueError):
        LotCounts(**kwargs)


def test_ca03_lot_counts_accepts_minus_three_hours() -> None:
    start = datetime(2026, 10, 1, 5, 0, tzinfo=BRT)
    lot = LotCounts(
        lot_id="L-001", started_at=start, ended_at=start + timedelta(hours=1), n=5, defects=1
    )
    assert lot.started_at == T0
    assert lot.n == 5
    assert lot.defects == 1


# --------------------------------------------------------------------------- CA-04


def test_ca04_select_lots_cut_of_example_1() -> None:
    sel = select_lots(example_1(), 3, 5, max_points=2, max_excluded=0)
    assert isinstance(sel, LotSelection)
    assert ids(sel.baseline) == ["L-001", "L-002", "L-004"]
    assert ids(sel.window) == ["L-006", "L-007"]
    assert sel.excluded == ()
    assert sel.valid_lots_total == 6
    assert sel.excluded_lots_total == 1
    for part in (sel.baseline, sel.window, sel.excluded):
        assert isinstance(part, tuple)


def test_ca04_select_lots_without_caps() -> None:
    sel = select_lots(example_1(), 3, 5, max_points=None, max_excluded=None)
    assert ids(sel.baseline) == ["L-001", "L-002", "L-004"]
    assert ids(sel.window) == VALID_ORDER
    assert ids(sel.excluded) == ["L-003"]
    assert sel.valid_lots_total == 6
    assert sel.excluded_lots_total == 1


# --------------------------------------------------------------------------- CA-05


def test_ca05_cut_does_not_move_the_baseline() -> None:
    resp = compute_p_chart(
        example_1(), baseline_lots=3, min_lot_size=5, max_points=2, max_excluded=0
    )
    assert close(resp.p_bar, 0.1385)
    assert ids(resp.points) == ["L-006", "L-007"]
    l6, l7 = resp.points
    assert close(l6.p, 0.0) and close(l6.ucl, 0.3457) and close(l6.lcl, 0.0)
    assert l6.out_of_control is False
    assert close(l7.p, 0.01) and close(l7.ucl, 0.2421) and close(l7.lcl, 0.0348)
    assert l7.out_of_control is True
    assert resp.excluded_lots == []
    assert resp.max_points == 2
    assert resp.valid_lots_total == 6
    assert resp.excluded_lots_total == 1
    assert resp.message is None


# --------------------------------------------------------------------------- CA-06


def test_ca06_without_cut_is_the_spec_006_chart() -> None:
    resp = compute_p_chart(example_1(), baseline_lots=3, min_lot_size=5)
    assert_example_1(resp.model_dump(mode="json"))
    assert resp.max_points is None
    assert resp.valid_lots_total == 6
    assert resp.excluded_lots_total == 1

    six = compute_p_chart(example_1(), baseline_lots=3, min_lot_size=5, max_points=6)
    assert six.points == resp.points
    assert six.p_bar == resp.p_bar
    assert six.excluded_lots == resp.excluded_lots
    assert six.max_points == 6


# --------------------------------------------------------------------------- CA-07


def test_ca07_few_lots_keep_the_totals() -> None:
    lots = [
        lc("L-1", 20, 2, T0),
        lc("L-2", 3, 1, T0 + timedelta(hours=1)),
        lc("L-3", 2, 0, T0 + timedelta(hours=2)),
    ]
    resp = compute_p_chart(lots, min_lot_size=5, max_points=10, max_excluded=1)
    assert resp.points == []
    assert resp.p_bar is None
    assert resp.message is not None
    assert resp.message.endswith("(found 1)"), resp.message
    assert resp.model_dump(mode="json")["excluded_lots"] == [{"lot_id": "L-3", "n": 2}]
    assert resp.valid_lots_total == 1
    assert resp.excluded_lots_total == 2


# --------------------------------------------------------------------------- CA-08


@pytest.mark.parametrize(
    "caps",
    [{"max_points": 0, "max_excluded": None}, {"max_points": None, "max_excluded": -1}],
    ids=["max_points-0", "max_excluded--1"],
)
def test_ca08_invalid_caps_raise(caps: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        select_lots(example_1(), 3, 5, **caps)
    with pytest.raises(ValueError):
        compute_p_chart(example_1(), baseline_lots=3, min_lot_size=5, **caps)


def test_ca08_max_excluded_zero_is_valid() -> None:
    sel = select_lots(example_1(), 3, 5, max_points=None, max_excluded=0)
    assert sel.excluded == ()
    resp = compute_p_chart(example_1(), baseline_lots=3, min_lot_size=5, max_excluded=0)
    assert resp.excluded_lots == []
    assert resp.excluded_lots_total == 1


# --------------------------------------------------------------------------- CA-09


def random_history(rng: random.Random) -> list[LotCounts]:
    count = rng.randint(0, 300)
    used: set[str] = set()
    lots: list[LotCounts] = []
    # Few distinct instants -> frequent ties on started_at.
    instants = rng.randint(1, max(1, count // 3 + 1))
    while len(lots) < count:
        lot_id = "".join(rng.choice(LOT_ALPHABET) for _ in range(rng.randint(1, 4)))
        if lot_id in used:
            continue
        used.add(lot_id)
        n = rng.randint(1, 30)
        start = T0 + timedelta(minutes=rng.randint(0, instants))
        lots.append(lc(lot_id, n, rng.randint(0, n), start, start + timedelta(minutes=1)))
    return lots


@pytest.mark.parametrize("seed", range(200))
def test_ca09_cut_equals_uncut_chart_sliced(seed: int) -> None:
    rng = random.Random(seed)
    lots = random_history(rng)
    baseline_lots = rng.randint(1, 100)
    min_lot_size = rng.randint(1, 10)
    max_points = rng.randint(1, 50)
    max_excluded = rng.randint(0, 20)
    for lot in lots:
        assert re.fullmatch(LOT_ID_PATTERN, lot.lot_id)

    cut = compute_p_chart(
        lots, baseline_lots, min_lot_size, max_points=max_points, max_excluded=max_excluded
    )
    full = compute_p_chart(lots, baseline_lots, min_lot_size)

    assert cut.p_bar == full.p_bar
    assert cut.points == full.points[-max_points:]
    expected_excluded = full.excluded_lots[-max_excluded:] if max_excluded else []
    assert cut.excluded_lots == expected_excluded
    assert cut.message == full.message
    n_valid = sum(1 for lot in lots if lot.n >= min_lot_size)
    assert cut.valid_lots_total == full.valid_lots_total == n_valid
    assert cut.excluded_lots_total == full.excluded_lots_total == len(full.excluded_lots)


def test_ca09_generator_covers_the_spec_space() -> None:
    """The 200 histories really have ties, mixed case, ``_``/``-`` and the size range."""
    sizes, ties, chars = [], 0, set()
    for seed in range(200):
        lots = random_history(random.Random(seed))
        sizes.append(len(lots))
        starts = [lot.started_at for lot in lots]
        ties += len(starts) - len(set(starts))
        chars |= {c for lot in lots for c in lot.lot_id}
    assert min(sizes) <= 5 and max(sizes) >= 280
    assert ties > 1000
    assert {"_", "-"} <= chars
    assert chars & set(string.ascii_uppercase) and chars & set(string.ascii_lowercase)


# --------------------------------------------------------------------------- CA-10


@pytest.mark.db
def test_ca10_route_small_volume(ca10_env: Env) -> None:
    resp = ca10_env.get({"baseline_lots": 3})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert_example_1(data)
    assert data["source"] == "live"
    assert data["max_points"] == 100
    assert data["valid_lots_total"] == 6
    assert data["excluded_lots_total"] == 1
    assert data["points"][0]["n"] == 20  # L-001 without the 3 unknown rows


# --------------------------------------------------------------------------- CA-11


@pytest.mark.db
def test_ca11_route_cut(ca11_env: Env) -> None:
    resp = ca11_env.get()
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert ids(data["points"]) == [f"C-{k:04d}" for k in range(31, 131)]
    base = range(1, 21)
    p_bar = sum(k % 3 for k in base) / (5 * len(base))
    assert data["p_bar"] == pytest.approx(p_bar, abs=1e-12)
    assert ids(data["excluded_lots"]) == [f"X-{k:03d}" for k in range(11, 61)]
    assert all(x["n"] == 1 for x in data["excluded_lots"])
    assert data["valid_lots_total"] == 130
    assert data["excluded_lots_total"] == 60
    assert data["max_points"] == 100

    expected = compute_p_chart(
        [lot.counts() for lot in ca11_lots()],
        20,
        5,
        source=Source.LIVE,
        max_points=100,
        max_excluded=50,
    ).model_dump(mode="json")
    assert data == expected

    resp10 = ca11_env.get({"max_points": 10})
    assert resp10.status_code == 200, resp10.text
    data10 = resp10.json()
    assert ids(data10["points"]) == [f"C-{k:04d}" for k in range(121, 131)]
    assert data10["p_bar"] == data["p_bar"]
    assert data10["max_points"] == 10
    # Same limits per point as the 100-point chart (§2: cut does not move anything).
    by_lot = {p["lot_id"]: p for p in data["points"]}
    for point in data10["points"]:
        assert point == by_lot[point["lot_id"]]


# --------------------------------------------------------------------------- CA-12


CA12_LOTS = [
    DbLot("a-1", T0, 10, 9),
    DbLot("B-1", T0, 10, 1),
    DbLot("_-1", T0, 10, 5),
]


@pytest.mark.db
def test_ca12_ties_use_the_c_collation(empty_env: Env) -> None:
    empty_env.insert(CA12_LOTS)
    resp = empty_env.get({"baseline_lots": 2, "max_points": 2})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert ids(data["points"]) == ["_-1", "a-1"]
    assert data["p_bar"] == pytest.approx(0.3, abs=1e-12)
    expected = compute_p_chart(
        [lot.counts() for lot in CA12_LOTS], 2, 5, max_points=2, max_excluded=MAX_EXCLUDED_LOTS
    ).model_dump(mode="json")
    assert data == expected


# --------------------------------------------------------------------------- CA-13


@pytest.mark.db
@pytest.mark.parametrize("value", ["1", "501", "abc", "2.5"])
def test_ca13_invalid_max_points_is_422(ca10_env: Env, value: str) -> None:
    resp = ca10_env.get({"max_points": value})
    assert resp.status_code == 422, resp.text
    assert "detail" in resp.json()
    no_traceback(resp)


@pytest.mark.db
@pytest.mark.parametrize("value", [2, 500])
def test_ca13_boundary_max_points_is_200(ca10_env: Env, value: int) -> None:
    resp = ca10_env.get({"max_points": value})
    assert resp.status_code == 200, resp.text
    assert resp.json()["max_points"] == value


@pytest.mark.db
def test_ca13_missing_key_is_401_before_422(ca10_env: Env) -> None:
    resp = ca10_env.get({"max_points": 0}, key=None)
    assert resp.status_code == 401
    assert resp.json() == UNAUTHORIZED


# --------------------------------------------------------------------------- CA-14

CA14_SQL = """
insert into inspections (
    inspection_id, device_id, lot_id, inspected_at, object_type, grade, grade_score,
    type_confidence, grade_confidence, needs_review, model_version, model_sha256, latency_ms,
    source
)
select gen_random_uuid(), 'edge-01', 'S1-' || lpad(i::text, 6, '0'),
       %(t0)s::timestamptz + make_interval(secs => i), 'screw',
       case when i %% 7 = 0 then 'poor' else 'good' end, 1.0, 0.9, 0.8, false,
       'partqc-mnv3-v1', %(sha)s, 42, 'live'
from generate_series(1, 120000) as i
union all
select gen_random_uuid(), 'edge-01', 'V5-' || lpad(l::text, 4, '0'),
       %(t0)s::timestamptz + make_interval(secs => l * 200 + j), 'screw',
       case when j = 1 and l %% 4 = 0 then 'poor' else 'good' end, 1.0, 0.9, 0.8, false,
       'partqc-mnv3-v1', %(sha)s, 42, 'live'
from generate_series(1, 600) as l, generate_series(1, 5) as j
"""


@pytest.mark.db
@pytest.mark.slow
def test_ca14_memory_and_body_are_bounded(empty_env: Env) -> None:
    with connect(empty_env.db) as conn:
        conn.execute(CA14_SQL, {"t0": T0, "sha": SHA})
        conn.execute("analyze inspections")
        assert conn.execute("select count(*) from inspections").fetchone() == (123000,)

    warm = empty_env.get({"source": "simulated"})
    assert warm.status_code == 200, warm.text

    tracemalloc.start()
    try:
        resp = empty_env.get()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["points"]) == 100
    assert len(data["excluded_lots"]) == 50
    assert data["valid_lots_total"] == 600
    assert data["excluded_lots_total"] == 120000
    assert len(resp.content) < 64 * 1024, len(resp.content)
    assert peak < 20 * 1024 * 1024, peak
    # The window is the latest 100 five-inspection lots; the excluded are the latest 50.
    assert ids(data["points"]) == [f"V5-{k:04d}" for k in range(501, 601)]
    assert ids(data["excluded_lots"]) == [f"S1-{k:06d}" for k in range(119951, 120001)]


# --------------------------------------------------------------------------- CA-15


def _sql_text_of(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bytes):
        return obj.decode()
    if isinstance(obj, sql.Composable):
        try:
            return obj.as_string(None)
        except TypeError:  # pragma: no cover - older psycopg signature
            return repr(obj)
    return ""


def _lot_selection_sql() -> str:
    """Text of every module-level SQL object (str or psycopg.sql) used by ``lot_selection``.

    Walks the global names referenced by ``lot_selection`` and, transitively, by module-level
    functions of the same module it calls.
    """
    seen: set[str] = set()
    texts: list[str] = []
    stack = [repo.lot_selection]
    while stack:
        fn = stack.pop()
        code = fn.__code__
        names = set(code.co_names)
        for const in code.co_consts:
            if inspect.iscode(const):
                names |= set(const.co_names)
        for name in names:
            if name in seen or not hasattr(repo, name):
                continue
            seen.add(name)
            value = getattr(repo, name)
            if inspect.isfunction(value) and value.__module__ == repo.__name__:
                stack.append(value)
            else:
                text = _sql_text_of(value)
                if text:
                    texts.append(text)
    return "\n".join(texts)


def test_ca15_cut_is_in_the_sql() -> None:
    text = _lot_selection_sql()
    flat = " ".join(text.split())
    lower = flat.lower()
    assert "materialized" in lower, flat
    assert 'collate "C"' in flat, flat
    for param in ("baseline_lots", "max_points", "max_excluded", "min_lot_size"):
        assert f"%({param})s" in flat, param
    for param in ("baseline_lots", "max_points", "max_excluded"):
        assert re.search(rf"\blimit\s+%\({param}\)s", flat, re.IGNORECASE), param


# --------------------------------------------------------------------------- CA-16


@pytest.mark.db
def test_ca16_simulated_lots_never_enter_the_live_cut(ca11_env: Env) -> None:
    sim = [
        DbLot(f"S-{k}", T0 + timedelta(minutes=200 + k), 5, 1, source="simulated")
        for k in range(1, 6)
    ]
    ca11_env.insert(sim)

    live = ca11_env.get()
    assert live.status_code == 200, live.text
    data = live.json()
    assert not [x for x in ids(data["points"]) + ids(data["excluded_lots"]) if x.startswith("S-")]
    assert data["valid_lots_total"] == 130
    assert data["source"] == "live"

    simulated = ca11_env.get({"source": "simulated"})
    assert simulated.status_code == 200, simulated.text
    sdata = simulated.json()
    assert ids(sdata["points"]) == [f"S-{k}" for k in range(1, 6)]
    assert sdata["valid_lots_total"] == 5
    assert sdata["excluded_lots_total"] == 0
    assert sdata["excluded_lots"] == []
    assert sdata["source"] == "simulated"


# --------------------------------------------------------------------------- extras (pure)


def test_extra_max_excluded_lots_is_50() -> None:
    assert MAX_EXCLUDED_LOTS == 50
    assert type(MAX_EXCLUDED_LOTS) is int


def test_extra_lot_selection_is_frozen_with_the_spec_fields() -> None:
    names = [f.name for f in dataclasses.fields(LotSelection)]
    assert names == [
        "baseline",
        "window",
        "excluded",
        "valid_lots_total",
        "excluded_lots_total",
    ]
    sel = select_lots(example_1(), 3, 5, max_points=2, max_excluded=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        sel.valid_lots_total = 0  # type: ignore[misc]


def test_extra_new_parameters_are_keyword_only() -> None:
    for fn, kw in (
        (compute_p_chart, ("source", "max_points", "max_excluded")),
        (select_lots, ("max_points", "max_excluded")),
        (build_p_chart, ("source", "max_points")),
        (repo.lot_selection, ("baseline_lots", "min_lot_size", "max_points", "max_excluded")),
    ):
        params = inspect.signature(fn).parameters
        for name in kw:
            assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, (fn.__name__, name)
    with pytest.raises(TypeError):
        compute_p_chart(example_1(), 3, 5, Source.LIVE, 2)  # type: ignore[misc]


def test_extra_compute_defaults_unchanged() -> None:
    params = inspect.signature(compute_p_chart).parameters
    assert params["baseline_lots"].default == 20
    assert params["min_lot_size"].default == 5
    assert params["source"].default == Source.LIVE
    assert params["max_points"].default is None
    assert params["max_excluded"].default is None


def test_extra_select_lots_does_not_mutate_input_and_sorts_by_python_str() -> None:
    lots = [
        lc("a-1", 10, 9, T0),
        lc("_-1", 10, 5, T0),
        lc("B-1", 10, 1, T0),
        lc("0-1", 10, 0, T0),
    ]
    snapshot = list(lots)
    sel = select_lots(lots, 2, 5, max_points=None, max_excluded=None)
    assert ids(sel.window) == sorted(ids(lots)) == ["0-1", "B-1", "_-1", "a-1"]
    assert lots == snapshot


@pytest.mark.parametrize(
    ("args", "caps"),
    [
        ((0, 5), {"max_points": None, "max_excluded": None}),
        ((3, 0), {"max_points": None, "max_excluded": None}),
        ((3, 5), {"max_points": -5, "max_excluded": None}),
        ((3, 5), {"max_points": None, "max_excluded": -50}),
    ],
)
def test_extra_select_lots_validation(args: tuple[int, int], caps: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        select_lots(example_1(), *args, **caps)


def test_extra_build_p_chart_rejects_incoherent_selection() -> None:
    sel = LotSelection(
        baseline=(),
        window=tuple(example_1()[:2]),
        excluded=(),
        valid_lots_total=2,
        excluded_lots_total=0,
    )
    with pytest.raises(ValueError):
        build_p_chart(sel, 3, 5, source=Source.LIVE, max_points=2)


def test_extra_build_p_chart_matches_compute() -> None:
    lots = example_1()
    sel = select_lots(lots, 3, 5, max_points=2, max_excluded=1)
    built = build_p_chart(sel, 3, 5, source=Source.SIMULATED, max_points=2)
    computed = compute_p_chart(lots, 3, 5, source=Source.SIMULATED, max_points=2, max_excluded=1)
    assert built == computed
    assert built.source == Source.SIMULATED
    assert ids(built.excluded_lots) == ["L-003"]


def test_extra_caps_larger_than_history_and_empty_history() -> None:
    resp = compute_p_chart(example_1(), 3, 5, max_points=500, max_excluded=50)
    full = compute_p_chart(example_1(), 3, 5)
    assert resp.points == full.points and resp.excluded_lots == full.excluded_lots
    empty = compute_p_chart([], max_points=100, max_excluded=50)
    assert empty.points == [] and empty.excluded_lots == []
    assert empty.valid_lots_total == 0 and empty.excluded_lots_total == 0
    assert empty.message is not None and empty.message.endswith("(found 0)")


def test_extra_max_points_one_in_the_service() -> None:
    """The route needs 2..500, but the service accepts ``max_points=1`` (only ``< 1`` fails)."""
    resp = compute_p_chart(example_1(), 3, 5, max_points=1)
    assert ids(resp.points) == ["L-007"]
    assert resp.max_points == 1


@pytest.mark.parametrize("bad", [True, 5.0, "5", None])
def test_extra_lot_counts_more_wrong_types(bad: Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        LotCounts(lot_id="L-1", started_at=T0, ended_at=T0, n=bad, defects=0)
    with pytest.raises((ValueError, TypeError)):
        LotCounts(lot_id="L-1", started_at=T0, ended_at=T0, n=5, defects=bad)


def test_extra_lot_counts_tz_without_offset_is_rejected() -> None:
    class NoOffset(tzinfo):  # tzinfo whose utcoffset() is None
        def utcoffset(self, dt: datetime | None) -> None:
            return None

        def tzname(self, dt: datetime | None) -> str:
            return "X"

        def dst(self, dt: datetime | None) -> None:
            return None

    odd = datetime(2026, 10, 1, 8, 0, tzinfo=NoOffset())
    assert odd.tzinfo is not None and odd.utcoffset() is None
    with pytest.raises(ValueError):
        LotCounts(lot_id="L-1", started_at=odd, ended_at=T0, n=5, defects=0)
    with pytest.raises(ValueError):
        LotCounts(lot_id="L-1", started_at=T0, ended_at=odd, n=5, defects=0)


def test_extra_lot_counts_subclass_of_int_and_numpy_like() -> None:
    """An ``int`` subclass that is not ``bool`` is still an ``int``; it must be accepted."""

    class MyInt(int):
        pass

    lot = LotCounts(lot_id="L-1", started_at=T0, ended_at=T0, n=MyInt(5), defects=MyInt(1))
    assert lot.n == 5


def test_extra_service_module_stays_pure() -> None:
    src = inspect.getsource(spc)
    for banned in ("import psycopg", "import logging", "import os", "import time", ".now("):
        assert banned not in src, banned


# --------------------------------------------------------------------------- extras (route)


@pytest.mark.db
@pytest.mark.parametrize(
    "value", ["0", "-1", "", " ", "1e2", "99999999999999999999999", "５", "NaN", "inf"]
)
def test_extra_more_invalid_max_points(ca10_env: Env, value: str) -> None:
    resp = ca10_env.get({"max_points": value})
    assert resp.status_code == 422, (value, resp.status_code, resp.text)
    no_traceback(resp)


@pytest.mark.db
def test_extra_whitespace_or_plus_sign_max_points(ca10_env: Env) -> None:
    """Record of lenient parses (pydantic lax mode): if accepted, the value must be echoed."""
    for value, as_int in (("+5", 5), (" 5", 5), ("05", 5)):
        resp = ca10_env.get({"max_points": value})
        assert resp.status_code in (200, 422), resp.text
        if resp.status_code == 200:
            assert resp.json()["max_points"] == as_int


@pytest.mark.db
def test_extra_valid_key_with_bad_max_points_and_device_key(ca10_env: Env) -> None:
    resp = ca10_env.get({"max_points": 501}, key="d" * 32)
    assert resp.status_code == 401
    assert resp.json() == UNAUTHORIZED


@pytest.mark.db
def test_extra_max_points_500_with_130_lots_returns_everything(ca11_env: Env) -> None:
    resp = ca11_env.get({"max_points": 500, "baseline_lots": 100, "min_lot_size": 1})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # min_lot_size=1: the X lots are valid too.
    assert data["valid_lots_total"] == 190
    assert data["excluded_lots_total"] == 0
    assert len(data["points"]) == 190
    assert data["excluded_lots"] == []


@pytest.mark.db
def test_extra_excluded_ties_cut_with_c_collation(empty_env: Env) -> None:
    """53 small lots with the same start: the 50 kept are the last in Python ``str`` order."""
    names = ["a-0", "b-0", "Z-0", "_-0", "0-0"] + [f"m{i:02d}" for i in range(48)]
    lots = [DbLot(name, T0, 1, 0) for name in names]
    lots += [DbLot("V-1", T0 - timedelta(hours=1), 5, 1), DbLot("V-2", T0, 5, 0)]
    empty_env.insert(lots)
    resp = empty_env.get()
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert ids(data["excluded_lots"]) == sorted(names)[-50:]
    expected = compute_p_chart(
        [lot.counts() for lot in lots], max_points=100, max_excluded=MAX_EXCLUDED_LOTS
    ).model_dump(mode="json")
    assert data == expected


def _random_db_history(rng: random.Random, prefix_pool: str) -> list[DbLot]:
    used: set[str] = set()
    out: list[DbLot] = []
    count = rng.randint(40, 160)
    while len(out) < count:
        lot_id = "".join(rng.choice(prefix_pool) for _ in range(rng.randint(1, 3)))
        if lot_id in used:
            continue
        used.add(lot_id)
        n = rng.randint(1, 9)
        start = T0 + timedelta(minutes=rng.randint(0, 12))
        out.append(DbLot(lot_id, start, n, rng.randint(0, n)))
    return out


@pytest.mark.db
@pytest.mark.parametrize("seed", range(4))
def test_extra_route_equals_reference_on_random_histories(empty_env: Env, seed: int) -> None:
    rng = random.Random(1000 + seed)
    lots = _random_db_history(rng, LOT_ALPHABET)
    empty_env.insert(lots)
    baseline_lots = rng.randint(2, 30)
    min_lot_size = rng.randint(1, 6)
    max_points = rng.randint(2, 40)
    resp = empty_env.get(
        {"baseline_lots": baseline_lots, "min_lot_size": min_lot_size, "max_points": max_points}
    )
    assert resp.status_code == 200, resp.text
    expected = compute_p_chart(
        [lot.counts() for lot in lots],
        baseline_lots,
        min_lot_size,
        max_points=max_points,
        max_excluded=MAX_EXCLUDED_LOTS,
    ).model_dump(mode="json")
    assert resp.json() == expected


@pytest.mark.db
def test_extra_object_type_filter_with_cut(empty_env: Env) -> None:
    screws = [DbLot(f"S{k:03d}", T0 + timedelta(minutes=k), 5, 1) for k in range(1, 11)]
    nuts = [
        DbLot(f"N{k:03d}", T0 + timedelta(minutes=k, seconds=10), 5, 0, object_type="nut")
        for k in range(1, 6)
    ]
    empty_env.insert(screws + nuts)
    resp = empty_env.get({"object_type": "nut", "max_points": 3})
    data = resp.json()
    assert ids(data["points"]) == ["N003", "N004", "N005"]
    assert data["valid_lots_total"] == 5
    assert data["p_bar"] == 0.0
    both = empty_env.get({"max_points": 2}).json()
    assert both["valid_lots_total"] == 15
    # Latest two valid lots of both types: S009 (T0+9 min) and S010 (T0+10 min).
    assert ids(both["points"]) == ["S009", "S010"]


@pytest.mark.db
def test_extra_lot_with_only_unknown_rows_does_not_count(empty_env: Env) -> None:
    empty_env.insert(EXAMPLE_1_DB)
    with connect(empty_env.db) as conn:
        for i in range(10):
            insert_unknown(conn, "U-ONLY", T0 + timedelta(hours=9, minutes=i))
    data = empty_env.get().json()
    assert "U-ONLY" not in ids(data["points"]) + ids(data["excluded_lots"])
    assert data["valid_lots_total"] == 6
    assert data["excluded_lots_total"] == 1


@pytest.mark.db
def test_extra_empty_database_has_zero_totals(empty_env: Env) -> None:
    data = empty_env.get().json()
    assert data["points"] == [] and data["excluded_lots"] == []
    assert data["valid_lots_total"] == 0 and data["excluded_lots_total"] == 0
    assert data["max_points"] == 100
    assert data["message"].endswith("(found 0)")


@pytest.mark.db
def test_extra_repeated_calls_are_identical(ca11_env: Env) -> None:
    first = ca11_env.get({"max_points": 37}).content
    for _ in range(3):
        assert ca11_env.get({"max_points": 37}).content == first


@pytest.mark.db
def test_extra_lot_selection_direct_matches_select_lots(ca11_env: Env) -> None:
    """``lot_selection`` (SQL) and ``select_lots`` (Python) agree, including ``None`` caps."""
    from psycopg_pool import ConnectionPool

    reference_lots = [lot.counts() for lot in ca11_lots()]
    with ConnectionPool(ca11_env.db, min_size=1, max_size=1, open=True) as pool:
        for caps in (
            {"max_points": 7, "max_excluded": 3},
            {"max_points": 7, "max_excluded": 0},
            {"max_points": None, "max_excluded": None},
        ):
            got = repo.lot_selection(
                pool, Source.LIVE, None, baseline_lots=20, min_lot_size=5, **caps
            )
            want = select_lots(reference_lots, 20, 5, **caps)
            assert got == want, caps


def test_extra_route_no_database_is_503() -> None:
    app = create_app(Settings(DATABASE_URL=no_db_url(), READ_API_KEY=R))
    with TestClient(app) as client:
        resp = client.get(URL, params={"max_points": 50}, headers={"X-API-Key": R})
    assert resp.status_code == 503
    assert resp.json() == DB_DOWN


def test_extra_openapi_documents_max_points_bounds() -> None:
    app = create_app(Settings(DATABASE_URL=no_db_url(), READ_API_KEY=R))
    schema = app.openapi()
    params = {p["name"]: p for p in schema["paths"][URL]["get"]["parameters"]}
    mp = params["max_points"]["schema"]
    assert mp.get("minimum") == 2 and mp.get("maximum") == 500 and mp.get("default") == 100
    # Response schema advertises the 3 optional fields.
    text = json.dumps(schema["components"]["schemas"]["SpcResponse"])
    for field in ("max_points", "valid_lots_total", "excluded_lots_total"):
        assert field in text
