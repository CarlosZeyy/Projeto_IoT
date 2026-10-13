"""Query-string dependencies shared by the read routes (SPEC-005 sections 4.2 and 4.3).

* ``InspectionFilters``: the common filters (``device_id``, ``lot_id``, ``object_type``,
  ``grade``, ``source``, ``defective``, ``from``, ``to``), combined with ``AND``.
* ``Pagination``: ``limit`` (1 to 500, default 50) and ``offset`` (>= 0, default 0).

Invalid values are FastAPI's default 422. Unknown query parameters are ignored. The regexes and
the timezone-aware UTC datetime come from ``qc_contracts`` (validated by pydantic, a full match).

No ``from __future__ import annotations`` here: FastAPI reads the dataclass signatures at run
time and needs the real annotation objects.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Query
from fastapi.exceptions import RequestValidationError

from qc_contracts import DEVICE_ID_PATTERN, LOT_ID_PATTERN, Grade, ObjectType, Source
from qc_contracts.schemas import UtcDatetime

DEFAULT_LIMIT = 50
MAX_LIMIT = 500

FROM_NOT_BEFORE_TO = "'from' must be earlier than 'to'"


@dataclass(frozen=True)
class InspectionFilters:
    """Common filters of the read routes; ``None`` means "not filtered".

    ``from_`` is inclusive and ``to`` is exclusive (``inspected_at >= from`` and
    ``inspected_at < to``). Both must carry a timezone and are normalized to UTC; ``from >= to``
    is a 422. ``grade`` excludes rows whose grade is null (``unknown`` objects).
    """

    device_id: Annotated[str | None, Query(pattern=DEVICE_ID_PATTERN)] = None
    lot_id: Annotated[str | None, Query(pattern=LOT_ID_PATTERN)] = None
    object_type: Annotated[ObjectType | None, Query()] = None
    grade: Annotated[Grade | None, Query()] = None
    source: Annotated[Source | None, Query()] = None
    defective: Annotated[bool | None, Query()] = None
    from_: Annotated[UtcDatetime | None, Query(alias="from")] = None
    to: Annotated[UtcDatetime | None, Query()] = None

    def __post_init__(self) -> None:
        if self.from_ is not None and self.to is not None and self.from_ >= self.to:
            raise RequestValidationError(
                [{"type": "value_error", "loc": ("query", "to"), "msg": FROM_NOT_BEFORE_TO}]
            )


@dataclass(frozen=True)
class Pagination:
    """``limit``/``offset`` of the paginated read routes."""

    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT
    offset: Annotated[int, Query(ge=0)] = 0
