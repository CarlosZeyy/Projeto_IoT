import copy
import json
import math
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from qc_contracts import (
    DEVICE_ID_PATTERN,
    LOT_ID_PATTERN,
    MAX_LATENCY_MS,
    MODEL_VERSION_PATTERN,
    SHA256_PATTERN,
    BatchCreate,
    BatchResult,
    Grade,
    HealthResponse,
    InspectionCreate,
    InspectionCreated,
    InspectionRead,
    LotSummary,
    MetricsSummary,
    ObjectType,
    Page,
    SpcPoint,
    SpcResponse,
    TimeseriesPoint,
)

FIXED_ID = "3f1c2b4e-8d7a-4c5b-9e6f-1a2b3c4d5e6f"
BRT = timezone(timedelta(hours=-3))


def base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "inspection_id": FIXED_ID,
        "device_id": "edge-01",
        "lot_id": "L-001",
        "inspected_at": (datetime.now(BRT) - timedelta(minutes=1)).isoformat(),
        "object_type": "screw",
        "grade": "fair",
        "grade_score": 2.1,
        "type_confidence": 0.97,
        "grade_confidence": 0.66,
        "needs_review": False,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": "a" * 64,
        "latency_ms": 120,
        "source": "live",
    }
    payload.update(overrides)
    return payload


def unknown_payload(**overrides: Any) -> dict[str, Any]:
    return base_payload(
        object_type="unknown", grade=None, grade_score=None, grade_confidence=None, **overrides
    )


# --- patterns ---------------------------------------------------------------------------------


def test_pattern_constants() -> None:
    assert DEVICE_ID_PATTERN == r"^[a-z0-9-]{3,32}$"
    assert LOT_ID_PATTERN == r"^[A-Za-z0-9_-]{1,40}$"
    assert MODEL_VERSION_PATTERN == r"^[a-z0-9.-]{3,40}$"
    assert SHA256_PATTERN == r"^[0-9a-f]{64}$"


# --- InspectionCreate: valid payloads and normalization -----------------------------------------


def test_base_payload_is_valid() -> None:
    m = InspectionCreate.model_validate(base_payload())
    assert m.object_type is ObjectType.SCREW
    assert m.grade is Grade.FAIR
    assert isinstance(m.inspection_id, uuid.UUID)


def test_inspected_at_normalized_to_utc() -> None:
    local = datetime.now(BRT).replace(microsecond=0) - timedelta(hours=1)
    m = InspectionCreate.model_validate(base_payload(inspected_at=local.isoformat()))
    assert m.inspected_at.tzinfo == UTC
    assert m.inspected_at.tzinfo is UTC
    assert m.inspected_at == local
    assert m.inspected_at.hour == (local.hour + 3) % 24


def test_fixed_instant_conversion() -> None:
    m = InspectionCreate.model_validate(base_payload(inspected_at="2026-10-01T12:00:00-03:00"))
    assert m.inspected_at == datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
    assert m.model_dump(mode="json")["inspected_at"] == "2026-10-01T15:00:00Z"


def test_round_trip_json() -> None:
    m = InspectionCreate.model_validate(base_payload())
    assert InspectionCreate.model_validate(m.model_dump(mode="json")) == m
    assert InspectionCreate.model_validate_json(m.model_dump_json()) == m


def test_round_trip_unknown() -> None:
    m = InspectionCreate.model_validate(unknown_payload())
    dumped = m.model_dump(mode="json")
    assert dumped["grade"] is None and dumped["grade_score"] is None
    assert InspectionCreate.model_validate(dumped) == m


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(base_payload(inspected_at="2026-10-20T12:00:00"))


@pytest.mark.parametrize(("minutes", "ok"), [(10, False), (6, False), (4, True), (-60, True)])
def test_future_limit(minutes: int, ok: bool) -> None:
    when = (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()
    if ok:
        InspectionCreate.model_validate(base_payload(inspected_at=when))
    else:
        with pytest.raises(ValidationError, match="future"):
            InspectionCreate.model_validate(base_payload(inspected_at=when))


def test_future_limit_with_other_timezone() -> None:
    when = (datetime.now(BRT) + timedelta(minutes=10)).isoformat()
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(base_payload(inspected_at=when))


# --- InspectionCreate: invariants --------------------------------------------------------------


def test_unknown_with_grade_rejected() -> None:
    with pytest.raises(ValidationError, match="if and only if object_type"):
        InspectionCreate.model_validate(base_payload(object_type="unknown"))


def test_known_type_without_grade_rejected() -> None:
    with pytest.raises(ValidationError, match="if and only if object_type"):
        InspectionCreate.model_validate(
            base_payload(grade=None, grade_score=None, grade_confidence=None)
        )


def test_unknown_with_null_grade_fields_accepted() -> None:
    m = InspectionCreate.model_validate(unknown_payload())
    assert m.object_type is ObjectType.UNKNOWN
    assert m.grade is None and m.grade_score is None and m.grade_confidence is None


@pytest.mark.parametrize("field,value", [("grade_score", 1.0), ("grade_confidence", 0.5)])
def test_null_grade_with_score_or_confidence_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError, match=f"{field} must be null"):
        InspectionCreate.model_validate(unknown_payload() | {field: value})


@pytest.mark.parametrize("field", ["grade_score", "grade_confidence"])
def test_grade_without_score_or_confidence_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match=f"{field} must be null"):
        InspectionCreate.model_validate(base_payload(**{field: None}))


@pytest.mark.parametrize(
    "field",
    [
        "inspection_id",
        "device_id",
        "lot_id",
        "inspected_at",
        "object_type",
        "grade",
        "grade_score",
        "type_confidence",
        "grade_confidence",
        "needs_review",
        "model_version",
        "model_sha256",
        "latency_ms",
        "source",
    ],
)
def test_every_field_is_required(field: str) -> None:
    payload = base_payload()
    del payload[field]
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate(payload)
    assert any(e["type"] == "missing" and e["loc"] == (field,) for e in exc.value.errors())


# --- InspectionCreate: field rules -------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type_confidence", 1.01),
        ("type_confidence", -0.01),
        ("type_confidence", math.inf),
        ("grade_confidence", 1.5),
        ("grade_confidence", math.nan),
        ("grade_score", 4.01),
        ("grade_score", -0.01),
        ("grade_score", math.nan),
        ("grade_score", math.inf),
        ("grade_score", -math.inf),
        ("latency_ms", -1),
        ("latency_ms", 1.5),
        ("device_id", "Edge_01"),
        ("device_id", "ab"),
        ("device_id", "a" * 33),
        ("device_id", "edge-01\n"),
        ("lot_id", ""),
        ("lot_id", "L 001"),
        ("lot_id", "L" * 41),
        ("model_version", "PartQC-V1"),
        ("model_version", "v1"),
        ("model_version", "m" * 41),
        ("model_sha256", "a" * 63),
        ("model_sha256", "a" * 65),
        ("model_sha256", "A" * 64),
        ("model_sha256", "g" * 64),
        ("inspection_id", str(uuid.uuid1())),
        ("inspection_id", "not-a-uuid"),
        ("source", "test"),
        ("object_type", "bolt"),
        ("grade", "excellent"),
        ("needs_review", "maybe"),
    ],
)
def test_invalid_field_values(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(base_payload(**{field: value}))


def test_inclusive_limits() -> None:
    m = InspectionCreate.model_validate(
        base_payload(type_confidence=0.0, grade_confidence=1.0, grade_score=0.0, latency_ms=0)
    )
    assert (m.type_confidence, m.grade_confidence, m.grade_score, m.latency_ms) == (0, 1, 0, 0)
    InspectionCreate.model_validate(
        base_payload(type_confidence=1.0, grade_confidence=0.0, grade_score=4.0)
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("device_id", "abc"),
        ("device_id", "a" * 32),
        ("lot_id", "L"),
        ("lot_id", "Lote_A-" + "x" * 33),
        ("model_version", "v.1"),
        ("model_sha256", "0123456789abcdef" * 4),
    ],
)
def test_pattern_boundaries_accepted(field: str, value: str) -> None:
    InspectionCreate.model_validate(base_payload(**{field: value}))


@pytest.mark.parametrize("extra", [{"image": "..."}, {"foo": 1}, {"is_defective": True}])
def test_extra_fields_forbidden(extra: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate(base_payload() | extra)
    assert [e["type"] for e in exc.value.errors()] == ["extra_forbidden"]


# --- BatchCreate / BatchResult -----------------------------------------------------------------


def _items(n: int) -> list[dict[str, Any]]:
    return [base_payload(inspection_id=str(uuid.uuid4())) for _ in range(n)]


@pytest.mark.parametrize("n", [0, 101])
def test_batch_size_rejected(n: int) -> None:
    with pytest.raises(ValidationError):
        BatchCreate.model_validate({"items": _items(n)})


@pytest.mark.parametrize("n", [1, 100])
def test_batch_size_accepted(n: int) -> None:
    assert len(BatchCreate.model_validate({"items": _items(n)}).items) == n


def test_batch_error_points_to_item() -> None:
    items = _items(100)
    items[56]["device_id"] = "BAD"
    with pytest.raises(ValidationError) as exc:
        BatchCreate.model_validate({"items": items})
    locs = [e["loc"] for e in exc.value.errors()]
    assert locs and all(loc[:2] == ("items", 56) for loc in locs)


def test_batch_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        BatchCreate.model_validate({"items": _items(1), "x": 1})


def test_batch_result_round_trip() -> None:
    data = {
        "results": [
            {"inspection_id": str(uuid.uuid4()), "status": "created"},
            {"inspection_id": str(uuid.uuid1()), "status": "duplicate"},
        ]
    }
    assert BatchResult.model_validate(data).model_dump(mode="json") == data


# --- InspectionCreated -------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["created", "duplicate"])
def test_inspection_created_status(status: str) -> None:
    m = InspectionCreated.model_validate({"inspection_id": FIXED_ID, "status": status})
    assert m.status == status


def test_inspection_created_bad_status() -> None:
    with pytest.raises(ValidationError):
        InspectionCreated.model_validate({"inspection_id": FIXED_ID, "status": "ok"})


# --- InspectionRead ----------------------------------------------------------------------------


def read_payload(**overrides: Any) -> dict[str, Any]:
    return (
        base_payload(
            received_at="2026-10-01T15:00:01Z",
            is_defective=False,
            inspected_at="2026-10-01T15:00:00Z",
        )
        | overrides
    )


def test_read_tolerates_extra_and_future() -> None:
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    m = InspectionRead.model_validate(read_payload(foo=1, inspected_at=future))
    assert "foo" not in m.model_dump()
    assert not hasattr(m, "foo")


def test_read_keeps_invariants() -> None:
    with pytest.raises(ValidationError):
        InspectionRead.model_validate(read_payload(object_type="unknown"))
    with pytest.raises(ValidationError):
        InspectionRead.model_validate(read_payload(grade_score=None))
    with pytest.raises(ValidationError):
        InspectionRead.model_validate(read_payload(received_at="2026-10-01T15:00:01"))


def test_read_requires_server_fields() -> None:
    for field in ("received_at", "is_defective"):
        payload = read_payload()
        del payload[field]
        with pytest.raises(ValidationError):
            InspectionRead.model_validate(payload)


def test_read_normalizes_received_at() -> None:
    m = InspectionRead.model_validate(read_payload(received_at="2026-10-01T12:00:01-03:00"))
    assert m.received_at == datetime(2026, 10, 1, 15, 0, 1, tzinfo=UTC)
    assert m.received_at.tzinfo is UTC


def test_read_round_trip() -> None:
    data = InspectionRead.model_validate(read_payload()).model_dump(mode="json")
    assert InspectionRead.model_validate(data).model_dump(mode="json") == data


# --- other response models: JSON round trip ----------------------------------------------------


def _round_trip(model: Any, data: dict[str, Any]) -> None:
    original = copy.deepcopy(data)
    assert model.model_validate_json(json.dumps(data)).model_dump(mode="json") == original
    assert model.model_validate(data).model_dump(mode="json") == original


def test_page_of_inspection_read_round_trip() -> None:
    item = InspectionRead.model_validate(read_payload()).model_dump(mode="json")
    _round_trip(Page[InspectionRead], {"items": [item], "total": 1, "limit": 50, "offset": 0})


@pytest.mark.parametrize(
    "bad", [{"total": -1}, {"limit": 0}, {"offset": -1}, {"items": [{"x": 1}]}]
)
def test_page_rejects_invalid(bad: dict[str, Any]) -> None:
    data = {"items": [], "total": 0, "limit": 50, "offset": 0} | bad
    with pytest.raises(ValidationError):
        Page[InspectionRead].model_validate(data)


def test_metrics_summary_round_trip() -> None:
    _round_trip(
        MetricsSummary,
        {
            "total": 10,
            "defective": 2,
            "defect_rate": 0.25,
            "unknown_count": 2,
            "needs_review_count": 1,
            "by_grade": {"perfect": 3, "good": 2, "fair": 1, "poor": 1, "unusable": 1},
            "by_object_type": {"screw": 5, "nut": 3, "unknown": 2},
            "mean_type_confidence": 0.9,
            "mean_grade_score": 1.5,
        },
    )
    _round_trip(
        MetricsSummary,
        {
            "total": 0,
            "defective": 0,
            "defect_rate": None,
            "unknown_count": 0,
            "needs_review_count": 0,
            "by_grade": {},
            "by_object_type": {},
            "mean_type_confidence": None,
            "mean_grade_score": None,
        },
    )


def test_metrics_summary_rejects_unknown_grade_key() -> None:
    with pytest.raises(ValidationError):
        MetricsSummary.model_validate(
            {
                "total": 1,
                "defective": 0,
                "defect_rate": 0.0,
                "unknown_count": 0,
                "needs_review_count": 0,
                "by_grade": {"excellent": 1},
                "by_object_type": {},
                "mean_type_confidence": None,
                "mean_grade_score": None,
            }
        )


def test_timeseries_point_round_trip() -> None:
    _round_trip(
        TimeseriesPoint,
        {"bucket_start": "2026-10-01T15:00:00Z", "total": 4, "defective": 1, "defect_rate": 0.25},
    )
    _round_trip(
        TimeseriesPoint,
        {"bucket_start": "2026-10-01T15:00:00Z", "total": 0, "defective": 0, "defect_rate": None},
    )


SPC_EXAMPLE = {
    "baseline_lots": 20,
    "min_lot_size": 5,
    "source": "live",
    "p_bar": 0.18,
    "points": [
        {
            "lot_id": "L-001",
            "started_at": "2026-10-01T15:00:00Z",
            "ended_at": "2026-10-01T15:30:00Z",
            "n": 25,
            "defects": 4,
            "p": 0.16,
            "cl": 0.18,
            "ucl": 0.41,
            "lcl": 0.0,
            "out_of_control": False,
        }
    ],
    "excluded_lots": [{"lot_id": "L-009", "n": 3}],
    "message": None,
}


SPC_CUT_FIELDS = {"max_points": 100, "valid_lots_total": 130, "excluded_lots_total": 1}
SPC_NO_CUT_FIELDS = dict.fromkeys(SPC_CUT_FIELDS)
SPC_FIELDS_0_2_0 = {
    "baseline_lots",
    "min_lot_size",
    "source",
    "p_bar",
    "points",
    "excluded_lots",
    "message",
}


def test_spc_response_round_trip() -> None:
    _round_trip(SpcResponse, SPC_EXAMPLE | SPC_CUT_FIELDS)


def test_spc_response_empty_with_message() -> None:
    data = SPC_EXAMPLE | {"p_bar": None, "points": [], "message": "fewer than 2 valid lots"}
    _round_trip(SpcResponse, data | SPC_NO_CUT_FIELDS)


def test_spc_response_0_2_0_json_is_still_valid() -> None:
    """A 0.2.0 body (without the cut fields) validates, with the three fields ``None``."""
    response = SpcResponse.model_validate_json(json.dumps(SPC_EXAMPLE))
    assert response.model_dump(mode="json") == SPC_EXAMPLE | SPC_NO_CUT_FIELDS


def test_spc_response_fields_are_0_2_0_plus_the_cut_fields() -> None:
    assert set(SpcResponse.model_fields) == SPC_FIELDS_0_2_0 | set(SPC_CUT_FIELDS)
    assert list(SpcResponse.model_fields)[-3:] == list(SPC_CUT_FIELDS)
    for name in SPC_CUT_FIELDS:
        assert SpcResponse.model_fields[name].default is None, name


@pytest.mark.parametrize(
    "bad",
    [
        {"max_points": 0},
        {"max_points": -1},
        {"valid_lots_total": -1},
        {"excluded_lots_total": -1},
        {"max_points": 1.5},
        {"valid_lots_total": "x"},
    ],
)
def test_spc_response_rejects_bad_cut_fields(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SpcResponse.model_validate(SPC_EXAMPLE | bad)


def test_spc_response_cut_field_boundaries() -> None:
    data = SPC_EXAMPLE | {"max_points": 1, "valid_lots_total": 0, "excluded_lots_total": 0}
    _round_trip(SpcResponse, data)


def test_spc_response_reader_ignores_unknown_fields() -> None:
    """A newer minor version may add fields: a 0.3.0 reader ignores them (``extra="ignore"``)."""
    response = SpcResponse.model_validate(SPC_EXAMPLE | {"future_field": 1})
    assert "future_field" not in response.model_dump()


def test_spc_response_rejects_bad_source() -> None:
    with pytest.raises(ValidationError):
        SpcResponse.model_validate(SPC_EXAMPLE | {"source": "test"})


def test_lot_summary_round_trip() -> None:
    _round_trip(
        LotSummary,
        {
            "lot_id": "L-001",
            "n": 12,
            "defects": 3,
            "unknown_count": 1,
            "started_at": "2026-10-01T15:00:00Z",
            "ended_at": "2026-10-01T15:30:00Z",
            "sources": ["live", "simulated"],
        },
    )


@pytest.mark.parametrize(("status", "db"), [("ok", "ok"), ("degraded", "error")])
def test_health_response_valid(status: str, db: str) -> None:
    _round_trip(
        HealthResponse,
        {"status": status, "db": db, "api_version": "0.1.0", "contract_version": "0.1.0"},
    )


@pytest.mark.parametrize(
    ("status", "db"), [("up", "ok"), ("ok", "down"), ("ok", "error"), ("degraded", "ok")]
)
def test_health_response_invalid(status: str, db: str) -> None:
    with pytest.raises(ValidationError):
        HealthResponse.model_validate(
            {"status": status, "db": db, "api_version": "0.1.0", "contract_version": "0.1.0"}
        )


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (TimeseriesPoint, {"bucket_start": "2026-10-01T15:00:00", "total": 0, "defective": 0}),
        (
            LotSummary,
            {
                "lot_id": "L-1",
                "n": 1,
                "defects": 0,
                "unknown_count": 0,
                "started_at": "2026-10-01T15:00:00",
                "ended_at": "2026-10-01T15:00:00Z",
                "sources": [],
            },
        ),
    ],
)
def test_response_datetimes_require_timezone(model: Any, data: dict[str, Any]) -> None:
    data = data | {"defect_rate": None} if model is TimeseriesPoint else data
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_response_models_ignore_extra_fields() -> None:
    m = HealthResponse.model_validate(
        {
            "status": "ok",
            "db": "ok",
            "api_version": "0.1.0",
            "contract_version": "0.2.0",
            "uptime_s": 10,
        }
    )
    assert "uptime_s" not in m.model_dump()
    point = TimeseriesPoint.model_validate(
        {
            "bucket_start": "2026-10-01T12:00:00-03:00",
            "total": 1,
            "defective": 0,
            "defect_rate": 0.0,
            "new_field": "x",
        }
    )
    assert point.bucket_start.tzinfo is UTC
    assert point.bucket_start.hour == 15


# --- datetimes that overflow when normalized to UTC (r1 review RV-01 / test report T-01) -------

YEAR1_PLUS5 = "0001-01-01T00:00:00+05:00"
YEAR9999_MINUS5 = "9999-12-31T23:59:59-05:00"
OVERFLOWING = [YEAR1_PLUS5, YEAR9999_MINUS5]


def _assert_value_error_at(
    exc: pytest.ExceptionInfo[ValidationError], loc: tuple[Any, ...]
) -> None:
    errors = exc.value.errors()
    assert [e["loc"] for e in errors] == [loc]
    assert errors[0]["type"] == "value_error"
    assert "out of range" in errors[0]["msg"]


@pytest.mark.parametrize("value", OVERFLOWING)
def test_create_overflowing_datetime_is_validation_error(value: str) -> None:
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate(base_payload(inspected_at=value))
    _assert_value_error_at(exc, ("inspected_at",))
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate_json(json.dumps(base_payload(inspected_at=value)))
    _assert_value_error_at(exc, ("inspected_at",))


def test_create_overflowing_datetime_object_is_validation_error() -> None:
    value = datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=5)))
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate(base_payload(inspected_at=value))
    _assert_value_error_at(exc, ("inspected_at",))


def test_batch_with_overflowing_datetime_points_to_item() -> None:
    items = _items(3)
    items[1]["inspected_at"] = YEAR1_PLUS5
    with pytest.raises(ValidationError) as exc:
        BatchCreate.model_validate_json(json.dumps({"items": items}))
    _assert_value_error_at(exc, ("items", 1, "inspected_at"))


@pytest.mark.parametrize("field", ["received_at", "inspected_at"])
@pytest.mark.parametrize("value", OVERFLOWING)
def test_read_overflowing_datetime_is_validation_error(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as exc:
        InspectionRead.model_validate_json(json.dumps(read_payload(**{field: value})))
    _assert_value_error_at(exc, (field,))


SPC_POINT = {
    "lot_id": "L-1",
    "started_at": "2026-10-01T15:00:00Z",
    "ended_at": "2026-10-01T16:00:00Z",
    "n": 50,
    "defects": 2,
    "p": 0.04,
    "cl": 0.05,
    "ucl": 0.14,
    "lcl": 0.0,
    "out_of_control": False,
}
LOT_SUMMARY = {
    "lot_id": "L-1",
    "n": 1,
    "defects": 0,
    "unknown_count": 0,
    "started_at": "2026-10-01T15:00:00Z",
    "ended_at": "2026-10-01T15:00:00Z",
    "sources": ["live"],
}
TIMESERIES_POINT = {
    "bucket_start": "2026-10-01T15:00:00Z",
    "total": 0,
    "defective": 0,
    "defect_rate": None,
}


@pytest.mark.parametrize(
    ("model", "data", "field"),
    [
        (TimeseriesPoint, TIMESERIES_POINT, "bucket_start"),
        (SpcPoint, SPC_POINT, "started_at"),
        (SpcPoint, SPC_POINT, "ended_at"),
        (LotSummary, LOT_SUMMARY, "started_at"),
        (LotSummary, LOT_SUMMARY, "ended_at"),
    ],
)
@pytest.mark.parametrize("value", OVERFLOWING)
def test_response_overflowing_datetime_is_validation_error(
    model: Any, data: dict[str, Any], field: str, value: str
) -> None:
    with pytest.raises(ValidationError) as exc:
        model.model_validate(data | {field: value})
    _assert_value_error_at(exc, (field,))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0001-01-01T00:00:00Z", datetime(1, 1, 1, tzinfo=UTC)),
        ("0001-01-01T05:00:00+05:00", datetime(1, 1, 1, tzinfo=UTC)),
        ("9999-12-31T23:59:59Z", datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)),
        ("9999-12-31T18:59:59-05:00", datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)),
    ],
)
def test_extreme_datetimes_inside_utc_range_accepted(value: str, expected: datetime) -> None:
    m = TimeseriesPoint.model_validate(TIMESERIES_POINT | {"bucket_start": value})
    assert m.bucket_start == expected
    assert m.bucket_start.tzinfo is UTC


# --- latency_ms upper bound (SPEC-023 section 4.1) ---------------------------------------------

ABOVE_LATENCY = [MAX_LATENCY_MS + 1, 2**63]


def _assert_less_than_equal_at(
    exc: pytest.ExceptionInfo[ValidationError], loc: tuple[Any, ...]
) -> None:
    errors = exc.value.errors()
    assert [e["loc"] for e in errors] == [loc]
    assert errors[0]["type"] == "less_than_equal"


def test_max_latency_is_integer_column_max() -> None:
    assert MAX_LATENCY_MS == 2**31 - 1 == 2_147_483_647
    assert isinstance(MAX_LATENCY_MS, int)


def test_latency_at_max_accepted() -> None:
    payload = base_payload(latency_ms=MAX_LATENCY_MS)
    assert InspectionCreate.model_validate(payload).latency_ms == MAX_LATENCY_MS
    m = InspectionCreate.model_validate_json(json.dumps(payload))
    assert m.latency_ms == MAX_LATENCY_MS
    assert InspectionCreate.model_validate_json(m.model_dump_json()) == m


@pytest.mark.parametrize("value", ABOVE_LATENCY)
def test_latency_above_max_rejected(value: int) -> None:
    payload = base_payload(latency_ms=value)
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate(payload)
    _assert_less_than_equal_at(exc, ("latency_ms",))
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate_json(json.dumps(payload))
    _assert_less_than_equal_at(exc, ("latency_ms",))


@pytest.mark.parametrize("value", ABOVE_LATENCY)
def test_read_latency_above_max_rejected(value: int) -> None:
    with pytest.raises(ValidationError) as exc:
        InspectionRead.model_validate(read_payload(latency_ms=value))
    _assert_less_than_equal_at(exc, ("latency_ms",))


def test_read_latency_at_max_accepted() -> None:
    m = InspectionRead.model_validate(read_payload(latency_ms=MAX_LATENCY_MS))
    assert m.latency_ms == MAX_LATENCY_MS


def test_batch_latency_above_max_points_to_item() -> None:
    items = _items(3)
    items[1]["latency_ms"] = MAX_LATENCY_MS + 1
    with pytest.raises(ValidationError) as exc:
        BatchCreate.model_validate({"items": items})
    _assert_less_than_equal_at(exc, ("items", 1, "latency_ms"))
