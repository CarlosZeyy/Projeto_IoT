"""Contract schemas, Pydantic v2 (docs/architecture.md sections 3.2 to 3.4).

Input models (``InspectionCreate``, ``BatchCreate`` and, from 0.5.0, ``HeartbeatCreate``) reject
unknown fields (``extra="forbid"``).
Response models ignore unknown fields (``extra="ignore"``) so a reader tolerates fields added
by a later minor version of the contract.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    UUID4,
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from qc_contracts.enums import (
    GRADE_FORBIDDEN_OBJECT_TYPES,
    GRADE_REQUIRED_OBJECT_TYPES,
    Grade,
    ObjectType,
    Source,
)

# Public regexes, reused by the API and the scripts without redefinition.
DEVICE_ID_PATTERN = r"^[a-z0-9-]{3,32}$"
LOT_ID_PATTERN = r"^[A-Za-z0-9_-]{1,40}$"
MODEL_VERSION_PATTERN = r"^[a-z0-9.-]{3,40}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
# Version of the edge application in a heartbeat (SPEC-018, contract 0.5.0).
APP_VERSION_PATTERN = r"^[0-9A-Za-z.+-]{1,40}$"

# Maximum tolerated clock skew of ``inspected_at`` into the future (InspectionCreate only).
MAX_FUTURE_SKEW = timedelta(minutes=5)

MAX_BATCH_SIZE = 100

# Upper bound of ``latency_ms``: 2**31 - 1, the maximum of the ``integer`` column (section 5).
# A larger value would fail the insert with SQLSTATE 22003 instead of a validation error.
MAX_LATENCY_MS: int = 2_147_483_647

# Upper bound of the counters of a heartbeat (``uptime_s``, ``outbox_pending``, ``outbox_dead``):
# the same ``integer`` column limit as ``MAX_LATENCY_MS`` (SPEC-018 section 4.1).
MAX_HEARTBEAT_COUNT: int = 2_147_483_647


def _to_utc(value: datetime) -> datetime:
    # Pydantic only turns ValueError/AssertionError into a ValidationError. A datetime near
    # year 1 or 9999 can leave the supported range when shifted to UTC, and ``astimezone``
    # then raises OverflowError, which would escape validation (a 500 instead of a 422).
    try:
        return value.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError("datetime out of range after UTC normalization") from exc


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
"""Timezone-aware datetime (naive is rejected), normalized to ``datetime.UTC``."""

DeviceId = Annotated[str, Field(pattern=DEVICE_ID_PATTERN)]
LotId = Annotated[str, Field(pattern=LOT_ID_PATTERN)]
ModelVersion = Annotated[str, Field(pattern=MODEL_VERSION_PATTERN)]
Sha256Hex = Annotated[str, Field(pattern=SHA256_PATTERN)]
Probability = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
GradeScore = Annotated[float, Field(ge=0.0, le=4.0, allow_inf_nan=False)]
AppVersion = Annotated[str, Field(pattern=APP_VERSION_PATTERN)]
HeartbeatCount = Annotated[int, Field(ge=0, le=MAX_HEARTBEAT_COUNT)]


class _InspectionBase(BaseModel):
    """Fields and cross-field invariants shared by ``InspectionCreate`` and ``InspectionRead``."""

    inspection_id: UUID4
    device_id: DeviceId
    lot_id: LotId
    inspected_at: UtcDatetime
    object_type: ObjectType
    grade: Grade | None
    grade_score: GradeScore | None
    type_confidence: Probability
    grade_confidence: Probability | None
    needs_review: bool
    model_version: ModelVersion
    model_sha256: Sha256Hex
    latency_ms: Annotated[int, Field(ge=0, le=MAX_LATENCY_MS)]
    source: Source

    @model_validator(mode="after")
    def _check_grade_invariants(self) -> Self:
        # Grade groups of ADR-021: required (screw, nut), forbidden (unknown) or optional (the
        # hand tools). The messages name the rule, never the values.
        if self.grade is None and self.object_type in GRADE_REQUIRED_OBJECT_TYPES:
            raise ValueError("grade must not be null for a grade-required object_type")
        if self.grade is not None and self.object_type in GRADE_FORBIDDEN_OBJECT_TYPES:
            raise ValueError("grade must be null for a grade-forbidden object_type")
        if (self.grade_score is None) != (self.grade is None):
            raise ValueError("grade_score must be null if and only if grade is null")
        if (self.grade_confidence is None) != (self.grade is None):
            raise ValueError("grade_confidence must be null if and only if grade is null")
        return self


class InspectionCreate(_InspectionBase):
    """Inspection result sent by the edge to the API (section 3.2)."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("inspected_at", mode="after")
    @classmethod
    def _not_in_future(cls, value: datetime) -> datetime:
        if value > datetime.now(UTC) + MAX_FUTURE_SKEW:
            raise ValueError("inspected_at must not be more than 5 minutes in the future")
        return value


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class InspectionRead(_InspectionBase):
    """Stored inspection as returned by the API: ``InspectionCreate`` plus server fields."""

    model_config = ConfigDict(extra="ignore")

    received_at: UtcDatetime
    is_defective: bool


class InspectionCreated(_ResponseModel):
    inspection_id: UUID
    status: Literal["created", "duplicate"]


class BatchCreate(BaseModel):
    """1 to 100 inspections; any invalid item invalidates the whole batch."""

    model_config = ConfigDict(extra="forbid")

    items: Annotated[list[InspectionCreate], Field(min_length=1, max_length=MAX_BATCH_SIZE)]


class BatchResult(_ResponseModel):
    """One result per item, in the same order as ``BatchCreate.items``."""

    results: list[InspectionCreated]


class Page[T](_ResponseModel):
    items: list[T]
    total: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1)]
    offset: Annotated[int, Field(ge=0)]


class MetricsSummary(_ResponseModel):
    """Aggregates over the filtered inspections. Value semantics are defined by SPEC-005."""

    total: int
    defective: int
    defect_rate: float | None
    unknown_count: int
    needs_review_count: int
    by_grade: dict[Grade, int]
    by_object_type: dict[ObjectType, int]
    mean_type_confidence: float | None
    mean_grade_score: float | None


class TimeseriesPoint(_ResponseModel):
    bucket_start: UtcDatetime
    total: int
    defective: int
    defect_rate: float | None


class SpcPoint(_ResponseModel):
    lot_id: str
    started_at: UtcDatetime
    ended_at: UtcDatetime
    n: int
    defects: int
    p: float
    cl: float
    ucl: float
    lcl: float
    out_of_control: bool


class SpcExcludedLot(_ResponseModel):
    lot_id: str
    n: int


class SpcResponse(_ResponseModel):
    """p chart by lot (section 3.4, ADR-013), cut to the latest lots (ADR-017, SPEC-026).

    The three fields added in 0.3.0 are optional and ``None`` in a 0.2.0 response:
    ``max_points`` is the cap on ``points`` that was applied (``None`` when the chart was built
    without one); ``valid_lots_total`` and ``excluded_lots_total`` count the valid
    (``n >= min_lot_size``) and excluded lots before the cut.
    """

    baseline_lots: int
    min_lot_size: int
    source: Source
    p_bar: float | None
    points: list[SpcPoint]
    excluded_lots: list[SpcExcludedLot]
    message: str | None
    max_points: Annotated[int, Field(ge=1)] | None = None
    valid_lots_total: Annotated[int, Field(ge=0)] | None = None
    excluded_lots_total: Annotated[int, Field(ge=0)] | None = None


class LotSummary(_ResponseModel):
    """One lot. ``n`` includes ``unknown`` inspections; ``sources`` lists the distinct values in
    enum order. Value semantics are defined by SPEC-005."""

    lot_id: str
    n: int
    defects: int
    unknown_count: int
    started_at: UtcDatetime
    ended_at: UtcDatetime
    sources: list[Source]


class HealthResponse(_ResponseModel):
    """``status == "ok"`` if and only if ``db == "ok"``. HTTP behavior is defined by SPEC-004."""

    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    api_version: str
    contract_version: str

    @model_validator(mode="after")
    def _check_status_matches_db(self) -> Self:
        if (self.status == "ok") != (self.db == "ok"):
            raise ValueError("status must be 'ok' if and only if db is 'ok'")
        return self


class HeartbeatCreate(BaseModel):
    """Health of the edge gateway, sent every ``HEARTBEAT_INTERVAL_S`` (SPEC-018, 0.5.0).

    ``model_version`` and ``model_sha256`` are null together (no model loaded). ``sent_at`` is
    the edge clock, kept only for diagnosis: the API decides ``online`` by its own clock. No
    image and no personal data (R-02).
    """

    model_config = ConfigDict(extra="forbid")

    sent_at: UtcDatetime
    model_version: ModelVersion | None
    model_sha256: Sha256Hex | None
    app_version: AppVersion
    uptime_s: HeartbeatCount
    outbox_pending: HeartbeatCount
    outbox_dead: HeartbeatCount

    @field_validator("sent_at", mode="after")
    @classmethod
    def _not_in_future(cls, value: datetime) -> datetime:
        if value > datetime.now(UTC) + MAX_FUTURE_SKEW:
            raise ValueError("sent_at must not be more than 5 minutes in the future")
        return value

    @model_validator(mode="after")
    def _check_model_pair(self) -> Self:
        if (self.model_version is None) != (self.model_sha256 is None):
            raise ValueError("model_sha256 must be null if and only if model_version is null")
        return self


class DeviceStatus(_ResponseModel):
    """One device as returned by ``GET /api/v1/devices`` (SPEC-018 section 4.3, 0.5.0).

    ``last_heartbeat_at`` is the server time when the last heartbeat arrived, and ``online`` is
    computed by the server from it (less than 180 s ago). The heartbeat fields are null for a
    device that never sent one. ``last_source`` is the ``source`` of the most recently received
    inspection of the device, or null without inspections (R-06).
    """

    device_id: str
    last_seen_at: UtcDatetime | None
    last_heartbeat_at: UtcDatetime | None
    online: bool
    model_version: str | None
    model_sha256: str | None
    app_version: str | None
    uptime_s: int | None
    outbox_pending: int | None
    outbox_dead: int | None
    last_source: Source | None
