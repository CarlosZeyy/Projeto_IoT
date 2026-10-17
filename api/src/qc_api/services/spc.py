"""p chart by lot (SPEC-006 section 4.1, ADR-013) with the cut of ADR-017 (SPEC-026 section 4.2).

Everything here is pure: no I/O, no clock, no logging, and the input is never mutated. Values
are not rounded.

* ``select_lots`` is the reference of the cut the route makes in SQL
  (``qc_api.repositories.inspections.lot_selection``): the first ``baseline_lots`` valid lots
  (the base of ``p_bar``), the last ``max_points`` valid lots (the points shown), the last
  ``max_excluded`` excluded lots, and the counts before the cut.
* ``build_p_chart`` turns a ``LotSelection`` into the ``SpcResponse``.
* ``compute_p_chart`` is both together; without ``max_points`` and ``max_excluded`` it is the
  chart of SPEC-006.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from qc_contracts import Source, SpcExcludedLot, SpcPoint, SpcResponse

SIGMA_MULTIPLIER = 3.0
MIN_VALID_LOTS = 2
# Cap on ``excluded_lots`` in the route (ADR-017, item 3): the most recent excluded lots.
MAX_EXCLUDED_LOTS = 50
INSUFFICIENT_DATA = (
    "insufficient data: need at least {need} lots with n >= {min_lot_size} (found {k})"
)


@dataclass(frozen=True)
class LotCounts:
    """Inspections of one lot (``unknown`` objects already left out): ``n`` and ``defects``.

    ``n`` and ``defects`` are ``int`` (never ``bool``), with ``n >= 1`` and
    ``0 <= defects <= n``; ``started_at`` and ``ended_at`` are timezone-aware ``datetime``.
    Anything else raises ``ValueError``.
    """

    lot_id: str
    started_at: datetime
    ended_at: datetime
    n: int
    defects: int

    def __post_init__(self) -> None:
        for name in ("n", "defects"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an int, got {type(value).__name__}")
        for name in ("started_at", "ended_at"):
            value = getattr(self, name)
            if not _is_aware(value):
                raise ValueError(f"{name} must be a timezone-aware datetime, got {value!r}")
        if self.n < 1:
            raise ValueError(f"n must be >= 1, got {self.n}")
        if not 0 <= self.defects <= self.n:
            raise ValueError(f"defects must be in 0..n ({self.n}), got {self.defects}")


@dataclass(frozen=True)
class LotSelection:
    """The lots a p chart needs, each tuple in ascending ``(started_at, lot_id)`` order.

    * ``baseline``: the first ``baseline_lots`` valid lots (``n >= min_lot_size``);
    * ``window``: the last ``max_points`` valid lots (all of them without a cap);
    * ``excluded``: the last ``max_excluded`` excluded lots (all of them without a cap);
    * ``valid_lots_total`` and ``excluded_lots_total``: the counts before the cut.
    """

    baseline: tuple[LotCounts, ...]
    window: tuple[LotCounts, ...]
    excluded: tuple[LotCounts, ...]
    valid_lots_total: int
    excluded_lots_total: int


def _is_aware(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _sort_key(lot: LotCounts) -> tuple[datetime, str]:
    return lot.started_at, lot.lot_id


def validate_selection_parameters(
    baseline_lots: int,
    min_lot_size: int,
    *,
    max_points: int | None,
    max_excluded: int | None,
) -> None:
    """Raise ``ValueError`` when ``baseline_lots < 1``, ``min_lot_size < 1``,
    ``max_points < 1`` or ``max_excluded < 0`` (``None`` means no cap and is always valid)."""
    if baseline_lots < 1:
        raise ValueError(f"baseline_lots must be >= 1, got {baseline_lots}")
    if min_lot_size < 1:
        raise ValueError(f"min_lot_size must be >= 1, got {min_lot_size}")
    if max_points is not None and max_points < 1:
        raise ValueError(f"max_points must be >= 1, got {max_points}")
    if max_excluded is not None and max_excluded < 0:
        raise ValueError(f"max_excluded must be >= 0, got {max_excluded}")


def _last(items: list[LotCounts], count: int | None) -> tuple[LotCounts, ...]:
    """The last ``count`` items (all of them with ``None``, none with ``0``)."""
    if count is None:
        return tuple(items)
    if count == 0:
        return ()
    return tuple(items[-count:])


def select_lots(
    lots: Sequence[LotCounts],
    baseline_lots: int,
    min_lot_size: int,
    *,
    max_points: int | None,
    max_excluded: int | None,
) -> LotSelection:
    """Pure reference of the cut made in SQL by ``lot_selection`` (SPEC-026 section 4.2).

    ``lots`` is sorted (a copy) by ``(started_at, lot_id)``, comparing ``lot_id`` as a Python
    ``str`` (the order of ``collate "C"``). Raises ``ValueError`` on invalid parameters
    (``validate_selection_parameters``).
    """
    validate_selection_parameters(
        baseline_lots, min_lot_size, max_points=max_points, max_excluded=max_excluded
    )
    ordered = sorted(lots, key=_sort_key)
    valid = [lot for lot in ordered if lot.n >= min_lot_size]
    excluded = [lot for lot in ordered if lot.n < min_lot_size]
    return LotSelection(
        baseline=tuple(valid[:baseline_lots]),
        window=_last(valid, max_points),
        excluded=_last(excluded, max_excluded),
        valid_lots_total=len(valid),
        excluded_lots_total=len(excluded),
    )


def build_p_chart(
    selection: LotSelection,
    baseline_lots: int,
    min_lot_size: int,
    *,
    source: Source,
    max_points: int | None,
) -> SpcResponse:
    """p chart of a ``LotSelection`` (SPEC-006 section 4.1, steps 4 to 8, over the selection).

    * With fewer than 2 valid lots in total: no points, ``p_bar = None`` and a ``message``.
    * Otherwise ``p_bar`` is the pooled defect rate of ``selection.baseline``, and each lot of
      ``selection.window`` gets ``p_bar +/- 3 sigma_i`` clipped to ``[0, 1]``; it is out of
      control when its ``p`` is strictly outside (rule 1 only).
    * ``excluded_lots`` is ``selection.excluded``.

    ``source`` and ``max_points`` are only copied to the response. Raises ``ValueError`` on
    invalid parameters and when the selection has no baseline but 2 or more valid lots.
    """
    validate_selection_parameters(
        baseline_lots, min_lot_size, max_points=max_points, max_excluded=None
    )
    excluded = [SpcExcludedLot(lot_id=lot.lot_id, n=lot.n) for lot in selection.excluded]
    common = {
        "baseline_lots": baseline_lots,
        "min_lot_size": min_lot_size,
        "source": source,
        "excluded_lots": excluded,
        "max_points": max_points,
        "valid_lots_total": selection.valid_lots_total,
        "excluded_lots_total": selection.excluded_lots_total,
    }

    if selection.valid_lots_total < MIN_VALID_LOTS:
        return SpcResponse(
            **common,
            p_bar=None,
            points=[],
            message=INSUFFICIENT_DATA.format(
                need=MIN_VALID_LOTS, min_lot_size=min_lot_size, k=selection.valid_lots_total
            ),
        )

    if not selection.baseline:
        raise ValueError(
            f"inconsistent selection: no baseline lots for {selection.valid_lots_total} valid lots"
        )
    p_bar = sum(lot.defects for lot in selection.baseline) / sum(
        lot.n for lot in selection.baseline
    )
    # 0 when p_bar is 0 or 1 (limits collapse onto p_bar); max() guards a tiny negative
    # floating-point result near those ends.
    variance = max(0.0, p_bar * (1.0 - p_bar))

    points = [_point(lot, p_bar, variance) for lot in selection.window]
    return SpcResponse(**common, p_bar=p_bar, points=points, message=None)


def compute_p_chart(
    lots: Sequence[LotCounts],
    baseline_lots: int = 20,
    min_lot_size: int = 5,
    *,
    source: Source = Source.LIVE,
    max_points: int | None = None,
    max_excluded: int | None = None,
) -> SpcResponse:
    """p chart of ``lots``: ``build_p_chart(select_lots(...), ...)``.

    * Lots with ``n < min_lot_size`` are excluded (listed in ``excluded_lots``).
    * ``p_bar`` comes from the first ``baseline_lots`` valid lots of the whole history, whatever
      the cut (ADR-017, item 2).
    * ``points`` are the last ``max_points`` valid lots and ``excluded_lots`` the last
      ``max_excluded`` excluded lots; ``None`` means no cap, which gives the chart of SPEC-006.

    ``source`` is only copied to the response: filtering by source is the caller's job.
    Raises ``ValueError`` on invalid parameters (``validate_selection_parameters``).
    """
    selection = select_lots(
        lots, baseline_lots, min_lot_size, max_points=max_points, max_excluded=max_excluded
    )
    return build_p_chart(
        selection, baseline_lots, min_lot_size, source=source, max_points=max_points
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
