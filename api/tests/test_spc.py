"""``qc_api.services.spc`` without a database (SPEC-006 sections 4.1 and 4.4).

Numeric comparisons use an absolute tolerance of ``5e-5`` (4 decimal places), as in the SPEC.
"""

from __future__ import annotations

import ast
import math
import random
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from qc_api.services import spc as spc_module
from qc_api.services.spc import LotCounts, compute_p_chart
from qc_contracts import Source, SpcResponse

TOL = 5e-5
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
SPC_SOURCE = Path(spc_module.__file__)

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

# (lot_id, p, cl, ucl, lcl, out_of_control): the table of Example 1.
EXPECTED_1 = [
    ("L-001", 0.1000, 0.1385, 0.3702, 0.0000, False),
    ("L-002", 0.1200, 0.1385, 0.3457, 0.0000, False),
    ("L-004", 0.2000, 0.1385, 0.3702, 0.0000, False),
    ("L-005", 0.6000, 0.1385, 0.3702, 0.0000, True),
    ("L-006", 0.0000, 0.1385, 0.3457, 0.0000, False),
    ("L-007", 0.0100, 0.1385, 0.2421, 0.0348, True),
]


def lot(lot_id: str, hours: float, n: int, defects: int) -> LotCounts:
    started = T0 + timedelta(hours=hours)
    return LotCounts(
        lot_id=lot_id,
        started_at=started,
        ended_at=started + timedelta(minutes=30),
        n=n,
        defects=defects,
    )


def example_1() -> list[LotCounts]:
    return [lot(*row) for row in EXAMPLE_1]


def sequence(*counts: tuple[int, int]) -> list[LotCounts]:
    """Lots ``L-1, L-2, ...`` one hour apart with the given ``(n, defects)``."""
    return [lot(f"L-{i}", i, n, d) for i, (n, d) in enumerate(counts, start=1)]


# --- LotCounts -------------------------------------------------------------------------------


@pytest.mark.parametrize(("n", "defects"), [(5, 6), (5, -1), (0, 0), (-1, 0)])
def test_lot_counts_rejects_impossible_counts(n: int, defects: int) -> None:
    with pytest.raises(ValueError):
        lot("L-X", 0, n, defects)


@pytest.mark.parametrize(("n", "defects"), [(1, 0), (1, 1), (5, 0), (5, 5)])
def test_lot_counts_accepts_the_boundaries(n: int, defects: int) -> None:
    assert lot("L-X", 0, n, defects).defects == defects


def test_lot_counts_is_frozen() -> None:
    item = lot("L-X", 0, 5, 1)
    with pytest.raises(FrozenInstanceError):
        item.n = 6  # type: ignore[misc]


# --- examples of section 4.4 -----------------------------------------------------------------


def assert_example_1(result: SpcResponse) -> None:
    assert result.p_bar == pytest.approx(9 / 65, abs=1e-12)
    assert result.p_bar == pytest.approx(0.1385, abs=TOL)
    assert [point.lot_id for point in result.points] == [row[0] for row in EXPECTED_1]
    for point, (_, p, cl, ucl, lcl, out) in zip(result.points, EXPECTED_1, strict=True):
        assert point.p == pytest.approx(p, abs=TOL), point.lot_id
        assert point.cl == pytest.approx(cl, abs=TOL), point.lot_id
        assert point.ucl == pytest.approx(ucl, abs=TOL), point.lot_id
        assert point.lcl == pytest.approx(lcl, abs=TOL), point.lot_id
        assert point.out_of_control is out, point.lot_id
    assert [item.model_dump() for item in result.excluded_lots] == [{"lot_id": "L-003", "n": 4}]
    assert result.message is None


def test_example_1() -> None:
    result = compute_p_chart(example_1(), baseline_lots=3, min_lot_size=5)
    assert_example_1(result)
    assert result.baseline_lots == 3
    assert result.min_lot_size == 5
    assert result.source is Source.LIVE


def test_example_1_points_keep_counts_and_period() -> None:
    result = compute_p_chart(example_1(), baseline_lots=3, min_lot_size=5)
    first = result.points[0]
    assert (first.n, first.defects) == (20, 2)
    assert first.started_at == T0
    assert first.ended_at == T0 + timedelta(minutes=30)
    assert first.started_at.tzinfo == UTC


def test_example_1_values_are_not_rounded() -> None:
    result = compute_p_chart(example_1(), baseline_lots=3, min_lot_size=5)
    p_bar = 9 / 65
    assert result.points[-1].ucl == p_bar + 3 * math.sqrt(p_bar * (1 - p_bar) / 100)


def test_example_2_defaults() -> None:
    result = compute_p_chart(example_1())
    assert result.p_bar == pytest.approx(22 / 210, abs=1e-12)
    assert result.p_bar == pytest.approx(0.1048, abs=TOL)
    by_lot = {point.lot_id: point for point in result.points}
    assert by_lot["L-001"].ucl == pytest.approx(0.3102, abs=TOL)
    assert by_lot["L-002"].ucl == pytest.approx(0.2885, abs=TOL)
    assert by_lot["L-007"].ucl == pytest.approx(0.1966, abs=TOL)
    assert by_lot["L-007"].lcl == pytest.approx(0.0129, abs=TOL)
    for lot_id in ("L-001", "L-002", "L-004", "L-005", "L-006"):
        assert by_lot[lot_id].lcl == 0.0, lot_id
    assert [p.lot_id for p in result.points if p.out_of_control] == ["L-005", "L-007"]
    assert (result.baseline_lots, result.min_lot_size, result.source) == (20, 5, Source.LIVE)


def test_source_is_only_copied_to_the_response() -> None:
    live = compute_p_chart(example_1(), 3, 5)
    simulated = compute_p_chart(example_1(), 3, 5, source=Source.SIMULATED)
    assert simulated.source is Source.SIMULATED
    assert simulated.model_dump(exclude={"source"}) == live.model_dump(exclude={"source"})


# --- ordering and purity ---------------------------------------------------------------------


def test_shuffled_input_gives_the_same_chart_and_is_not_mutated() -> None:
    lots = example_1()
    random.Random(6).shuffle(lots)
    shuffled = list(lots)
    assert [item.lot_id for item in shuffled] != [row[0] for row in EXAMPLE_1]
    result = compute_p_chart(lots, baseline_lots=3, min_lot_size=5)
    assert_example_1(result)
    assert lots == shuffled


def test_tuple_input_is_accepted() -> None:
    assert_example_1(compute_p_chart(tuple(example_1()), baseline_lots=3, min_lot_size=5))


def test_ties_on_started_at_are_ordered_by_lot_id() -> None:
    lots = [lot("L-B", 0, 10, 1), lot("L-A", 0, 10, 2)]
    result = compute_p_chart(lots)
    assert [point.lot_id for point in result.points] == ["L-A", "L-B"]
    assert [item.lot_id for item in lots] == ["L-B", "L-A"]


def test_order_uses_instants_not_offsets() -> None:
    """``09:00-03:00`` (12:00 UTC) comes after ``11:00Z``."""
    brt = timezone(timedelta(hours=-3))
    late = LotCounts("L-A", datetime(2026, 10, 1, 9, tzinfo=brt), T0 + timedelta(hours=5), 10, 1)
    early = LotCounts("L-B", datetime(2026, 10, 1, 11, tzinfo=UTC), T0 + timedelta(hours=5), 10, 1)
    result = compute_p_chart([late, early])
    assert [point.lot_id for point in result.points] == ["L-B", "L-A"]
    assert result.points[1].started_at == datetime(2026, 10, 1, 12, tzinfo=UTC)


def test_excluded_lots_follow_the_chart_order() -> None:
    lots = [lot("L-9", 3, 2, 0), lot("L-1", 0, 10, 1), lot("L-5", 1, 3, 1), lot("L-2", 2, 10, 0)]
    result = compute_p_chart(lots)
    assert [item.model_dump() for item in result.excluded_lots] == [
        {"lot_id": "L-5", "n": 3},
        {"lot_id": "L-9", "n": 2},
    ]
    assert [point.lot_id for point in result.points] == ["L-1", "L-2"]


# --- baseline --------------------------------------------------------------------------------


def test_baseline_uses_the_first_valid_lots_only() -> None:
    lots = sequence((10, 1), (10, 1), (10, 9))
    result = compute_p_chart(lots, baseline_lots=2)
    assert result.p_bar == pytest.approx(0.1)
    assert [point.out_of_control for point in result.points] == [False, False, True]


def test_baseline_skips_excluded_lots() -> None:
    lots = sequence((10, 1), (3, 3), (10, 1), (10, 5))
    result = compute_p_chart(lots, baseline_lots=2)
    assert result.p_bar == pytest.approx(0.1)


def test_baseline_of_one_lot() -> None:
    result = compute_p_chart(sequence((10, 2), (10, 0)), baseline_lots=1)
    assert result.p_bar == pytest.approx(0.2)


def test_baseline_includes_out_of_control_lots() -> None:
    """No phase I recalculation (ADR-013): an out-of-control base lot still counts."""
    lots = sequence((20, 0), (20, 0), (20, 0), (20, 0), (20, 12))
    result = compute_p_chart(lots)
    assert result.p_bar == pytest.approx(12 / 100)
    assert result.points[-1].out_of_control is True


# --- edges -----------------------------------------------------------------------------------


def test_p_bar_zero_collapses_the_limits() -> None:
    result = compute_p_chart(sequence((10, 0), (10, 0), (10, 1)), baseline_lots=2)
    assert result.p_bar == 0
    assert all(point.ucl == 0.0 and point.lcl == 0.0 for point in result.points)
    assert [point.out_of_control for point in result.points] == [False, False, True]
    assert result.points[2].p == pytest.approx(0.1)


def test_p_bar_one_collapses_the_limits() -> None:
    result = compute_p_chart(sequence((5, 5), (5, 5), (5, 4)), baseline_lots=2)
    assert result.p_bar == 1
    assert all(point.ucl == 1.0 and point.lcl == 1.0 for point in result.points)
    assert [point.out_of_control for point in result.points] == [False, False, True]


def test_limits_are_clipped_to_zero_and_one() -> None:
    result = compute_p_chart(sequence((5, 4), (5, 4), (5, 5)), baseline_lots=2)
    assert result.p_bar == pytest.approx(0.8)
    assert all(point.ucl == 1.0 for point in result.points)
    assert all(0.0 <= point.lcl <= point.cl <= point.ucl <= 1.0 for point in result.points)
    assert not any(point.out_of_control for point in result.points)


def test_point_exactly_on_a_limit_is_in_control() -> None:
    """Strict inequalities: with ``p_bar = 0`` a lot with ``p = 0`` sits on both limits."""
    result = compute_p_chart(sequence((10, 0), (10, 0)))
    assert [point.out_of_control for point in result.points] == [False, False]


def test_min_lot_size_one_keeps_every_lot() -> None:
    result = compute_p_chart(sequence((1, 0), (1, 1)), min_lot_size=1)
    assert len(result.points) == 2
    assert result.excluded_lots == []
    assert result.p_bar == pytest.approx(0.5)


def test_lot_exactly_at_min_lot_size_is_valid() -> None:
    result = compute_p_chart(sequence((5, 1), (4, 1), (5, 0)), min_lot_size=5)
    assert [point.lot_id for point in result.points] == ["L-1", "L-3"]
    assert [item.lot_id for item in result.excluded_lots] == ["L-2"]


# --- insufficient data -----------------------------------------------------------------------


def test_one_valid_lot_is_insufficient() -> None:
    lots = [lot("L-1", 0, 20, 2), lot("L-2", 1, 3, 1)]
    result = compute_p_chart(lots, min_lot_size=5)
    assert result.points == []
    assert result.p_bar is None
    assert [item.model_dump() for item in result.excluded_lots] == [{"lot_id": "L-2", "n": 3}]
    assert result.message == "insufficient data: need at least 2 lots with n >= 5 (found 1)"


def test_no_lots_is_insufficient() -> None:
    result = compute_p_chart([])
    assert result.points == []
    assert result.p_bar is None
    assert result.excluded_lots == []
    assert result.message == "insufficient data: need at least 2 lots with n >= 5 (found 0)"
    assert (result.baseline_lots, result.min_lot_size, result.source) == (20, 5, Source.LIVE)


def test_insufficient_message_uses_the_effective_min_lot_size() -> None:
    result = compute_p_chart(sequence((20, 2), (20, 2)), min_lot_size=21, source=Source.SIMULATED)
    assert result.message == "insufficient data: need at least 2 lots with n >= 21 (found 0)"
    assert len(result.excluded_lots) == 2
    assert result.source is Source.SIMULATED


def test_insufficient_response_serializes_null_p_bar() -> None:
    body = compute_p_chart([]).model_dump(mode="json")
    assert body["p_bar"] is None
    assert body["source"] == "live"


# --- parameters ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs", [{"baseline_lots": 0}, {"min_lot_size": 0}, {"baseline_lots": -1}]
)
def test_invalid_parameters_raise(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        compute_p_chart(example_1(), **kwargs)


def test_source_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        compute_p_chart(example_1(), 20, 5, Source.LIVE)  # type: ignore[misc]


# --- purity (section 4.1) --------------------------------------------------------------------

FORBIDDEN_MODULES = {"psycopg", "psycopg_pool", "fastapi", "starlette", "logging", "os", "time"}


def test_spc_module_has_no_io_imports() -> None:
    tree = ast.parse(SPC_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
    assert imported & FORBIDDEN_MODULES == set()


def test_spc_module_does_not_read_the_clock() -> None:
    tree = ast.parse(SPC_SOURCE.read_text(encoding="utf-8"))
    clock = {"now", "utcnow", "today", "time", "monotonic", "perf_counter"}
    calls = [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in clock
    ]
    assert calls == []
