"""p chart by lot (SPEC-006 section 4.1, ADR-013, docs/architecture.md section 3.4).

``compute_p_chart`` is a pure function: no I/O, no clock, no logging, and the input is never
mutated. The route (``GET /api/v1/metrics/spc``) only queries the per-lot counts and serializes
the result. Values are not rounded.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from qc_contracts import Source, SpcExcludedLot, SpcPoint, SpcResponse

SIGMA_MULTIPLIER = 3.0
MIN_VALID_LOTS = 2
INSUFFICIENT_DATA = (
    "insufficient data: need at least {need} lots with n >= {min_lot_size} (found {k})"
)


@dataclass(frozen=True)
class LotCounts:
    """Inspections of one lot (``unknown`` objects already left out): ``n`` and ``defects``."""

    lot_id: str
    started_at: datetime
    ended_at: datetime
    n: int
    defects: int

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ValueError(f"n must be >= 1, got {self.n}")
        if not 0 <= self.defects <= self.n:
            raise ValueError(f"defects must be in 0..n ({self.n}), got {self.defects}")


def _sort_key(lot: LotCounts) -> tuple[datetime, str]:
    return lot.started_at, lot.lot_id


def compute_p_chart(
    lots: Sequence[LotCounts],
    baseline_lots: int = 20,
    min_lot_size: int = 5,
    *,
    source: Source = Source.LIVE,
) -> SpcResponse:
    """p chart of ``lots``, ordered by ``(started_at, lot_id)``.

    * Lots with ``n < min_lot_size`` are listed in ``excluded_lots`` and left out.
    * With fewer than 2 valid lots: no points, ``p_bar = None`` and an explanatory ``message``.
    * ``p_bar`` is the pooled defect rate of the first ``baseline_lots`` valid lots (all of them
      when there are fewer); each valid lot gets ``p_bar +/- 3 sigma_i`` clipped to ``[0, 1]``,
      and is out of control when its ``p`` is strictly outside (rule 1 only).

    ``source`` is only copied to the response: filtering by source is the caller's job.
    Raises ``ValueError`` when ``baseline_lots < 1`` or ``min_lot_size < 1``.
    """
    if baseline_lots < 1:
        raise ValueError(f"baseline_lots must be >= 1, got {baseline_lots}")
    if min_lot_size < 1:
        raise ValueError(f"min_lot_size must be >= 1, got {min_lot_size}")

    ordered = sorted(lots, key=_sort_key)
    valid = [lot for lot in ordered if lot.n >= min_lot_size]
    excluded = [
        SpcExcludedLot(lot_id=lot.lot_id, n=lot.n) for lot in ordered if lot.n < min_lot_size
    ]

    if len(valid) < MIN_VALID_LOTS:
        return SpcResponse(
            baseline_lots=baseline_lots,
            min_lot_size=min_lot_size,
            source=source,
            p_bar=None,
            points=[],
            excluded_lots=excluded,
            message=INSUFFICIENT_DATA.format(
                need=MIN_VALID_LOTS, min_lot_size=min_lot_size, k=len(valid)
            ),
        )

    baseline = valid[:baseline_lots]
    p_bar = sum(lot.defects for lot in baseline) / sum(lot.n for lot in baseline)
    # 0 when p_bar is 0 or 1 (limits collapse onto p_bar); max() guards a tiny negative
    # floating-point result near those ends.
    variance = max(0.0, p_bar * (1.0 - p_bar))

    points = [_point(lot, p_bar, variance) for lot in valid]
    return SpcResponse(
        baseline_lots=baseline_lots,
        min_lot_size=min_lot_size,
        source=source,
        p_bar=p_bar,
        points=points,
        excluded_lots=excluded,
        message=None,
    )


def _point(lot: LotCounts, p_bar: float, variance: float) -> SpcPoint:
    p = lot.defects / lot.n
    spread = SIGMA_MULTIPLIER * math.sqrt(variance / lot.n)
    ucl = min(1.0, p_bar + spread)
    lcl = max(0.0, p_bar - spread)
    return SpcPoint(
        lot_id=lot.lot_id,
        started_at=lot.started_at,
        ended_at=lot.ended_at,
        n=lot.n,
        defects=lot.defects,
        p=p,
        cl=p_bar,
        ucl=ucl,
        lcl=lcl,
        out_of_control=p > ucl or p < lcl,
    )
