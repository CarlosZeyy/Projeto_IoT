"""Acceptance tests for SPEC-002 (qc-contracts).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-01 (qc-contracts part), CA-02 to CA-18 and CA-27. Tests named
``test_extra_*`` cover requirements of SPEC-002 section 4 that no CA spells out.
"""

from __future__ import annotations

import ast
import enum
import importlib.metadata
import json
import math
import re
import types
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import qc_contracts
from qc_contracts.defects import is_defective
from qc_contracts.enums import (
    GRADE_ORDER,
    CaptureMode,
    Grade,
    ObjectType,
    Source,
    grade_from_index,
    grade_index,
)
from qc_contracts.labels import (
    CAPTURE_MODE_LABELS_PT,
    GRADE_LABELS_PT,
    OBJECT_TYPE_LABELS_PT,
    SOURCE_LABELS_PT,
)
from qc_contracts.schemas import (
    DEVICE_ID_PATTERN,
    LOT_ID_PATTERN,
    MODEL_VERSION_PATTERN,
    SHA256_PATTERN,
    BatchCreate,
    BatchResult,
    HealthResponse,
    InspectionCreate,
    InspectionCreated,
    InspectionRead,
    LotSummary,
    MetricsSummary,
    Page,
    SpcExcludedLot,
    SpcPoint,
    SpcResponse,
    TimeseriesPoint,
)

pytestmark = pytest.mark.acceptance

PKG_ROOT = Path(__file__).resolve().parents[2]  # packages/contracts
README = PKG_ROOT / "README.md"
BRT = timezone(timedelta(hours=-3))
FIXED_ID = "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b"  # UUID version 4


def base_payload(**overrides: Any) -> dict[str, Any]:
    """Payload ``P`` of SPEC-002 section 5."""
    payload: dict[str, Any] = {
        "inspection_id": FIXED_ID,
        "device_id": "edge-01",
        "lot_id": "L-001",
        "inspected_at": (datetime.now(UTC) - timedelta(minutes=1)).astimezone(BRT),
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


def read_payload(**overrides: Any) -> dict[str, Any]:
    payload = base_payload(received_at=datetime.now(UTC), is_defective=False)
    payload.update(overrides)
    return payload


def unknown_payload(**overrides: Any) -> dict[str, Any]:
    payload = base_payload(
        object_type="unknown", grade=None, grade_score=None, grade_confidence=None
    )
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- CA-01


def test_ca01_contracts_version() -> None:
    v = qc_contracts.__version__
    assert qc_contracts.__version__ == importlib.metadata.version("qc-contracts")
    assert re.fullmatch(r"\d+\.\d+\.\d+", v)
    assert (0, 1, 0) <= tuple(int(p) for p in v.split(".")) < (1, 0, 0)


# --------------------------------------------------------------------------- CA-02


def test_ca02_enum_values_grade_order_and_patterns() -> None:
    # SPEC-016 section 4.1: the 5 hand tools come after the MVP members, in this order.
    assert [m.value for m in ObjectType][:3] == ["screw", "nut", "unknown"]
    assert [m.value for m in Grade] == ["perfect", "good", "fair", "poor", "unusable"]
    assert [m.value for m in Source] == ["live", "simulated"]
    assert [m.value for m in CaptureMode] == ["inspect", "collect"]

    # Members in upper case, StrEnum (SPEC-002 4.1).
    assert Grade.PERFECT == "perfect" and Grade.UNUSABLE == "unusable"
    assert ObjectType.SCREW == "screw" and ObjectType.UNKNOWN == "unknown"
    assert Source.LIVE == "live" and Source.SIMULATED == "simulated"
    assert CaptureMode.INSPECT == "inspect" and CaptureMode.COLLECT == "collect"
    for enum_cls in (ObjectType, Grade, Source, CaptureMode):
        assert issubclass(enum_cls, enum.StrEnum)

    assert isinstance(GRADE_ORDER, tuple)
    assert GRADE_ORDER == (Grade.PERFECT, Grade.GOOD, Grade.FAIR, Grade.POOR, Grade.UNUSABLE)
    assert list(GRADE_ORDER) == list(Grade)

    assert DEVICE_ID_PATTERN == r"^[a-z0-9-]{3,32}$"
    assert LOT_ID_PATTERN == r"^[A-Za-z0-9_-]{1,40}$"
    assert MODEL_VERSION_PATTERN == r"^[a-z0-9.-]{3,40}$"
    assert SHA256_PATTERN == r"^[0-9a-f]{64}$"
    for pattern in (DEVICE_ID_PATTERN, LOT_ID_PATTERN, MODEL_VERSION_PATTERN, SHA256_PATTERN):
        assert type(pattern) is str


# --------------------------------------------------------------------------- CA-03


def test_ca03_grade_index_round_trip_and_bounds() -> None:
    assert grade_index(Grade.FAIR) == 2
    assert grade_from_index(4) is Grade.UNUSABLE
    for i, grade in enumerate(GRADE_ORDER):
        assert grade_index(grade) == i
        assert grade_from_index(i) is grade
    with pytest.raises(ValueError):
        grade_from_index(5)
    with pytest.raises(ValueError):
        grade_from_index(-1)


# --------------------------------------------------------------------------- CA-04


def test_ca04_is_defective_rule() -> None:
    assert [is_defective(g) for g in GRADE_ORDER] == [False, False, False, True, True]
    assert is_defective(None) is False
    assert is_defective("poor") is True
    assert is_defective("unusable") is True
    assert is_defective("good") is False
    with pytest.raises(ValueError):
        is_defective("bogus")


# --------------------------------------------------------------------------- CA-05


def test_ca05_valid_payload_normalized_to_utc_and_round_trip() -> None:
    payload = base_payload()
    m = InspectionCreate.model_validate(payload)
    assert m.inspected_at.tzinfo == UTC
    assert m.inspected_at == payload["inspected_at"]  # same instant
    assert m.inspected_at.utcoffset() == timedelta(0)

    # Fixed example: 12:00-03:00 -> 15:00Z (past date, so it is not in the future).
    fixed = InspectionCreate.model_validate(base_payload(inspected_at="2026-01-10T12:00:00-03:00"))
    assert fixed.inspected_at == datetime(2026, 1, 10, 15, 0, tzinfo=UTC)
    assert fixed.inspected_at.tzinfo == UTC
    assert fixed.inspected_at.hour == 15

    # JSON round trip.
    again = InspectionCreate.model_validate(m.model_dump(mode="json"))
    assert again == m
    assert again.model_dump() == m.model_dump()


# --------------------------------------------------------------------------- CA-06


def test_ca06_naive_datetime_rejected() -> None:
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(base_payload(inspected_at="2026-10-20T12:00:00"))
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(base_payload(inspected_at=datetime(2026, 1, 10, 12, 0)))


# --------------------------------------------------------------------------- CA-07


def test_ca07_future_limit() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(
            base_payload(inspected_at=(now + timedelta(minutes=10)).astimezone(BRT))
        )
    ok = InspectionCreate.model_validate(
        base_payload(inspected_at=(now + timedelta(minutes=4)).astimezone(BRT))
    )
    assert ok.inspected_at > now


# --------------------------------------------------------------------------- CA-08


def test_ca08_grade_null_iff_unknown() -> None:
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(base_payload(object_type="unknown", grade="fair"))
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(
            base_payload(object_type="screw", grade=None, grade_score=None, grade_confidence=None)
        )


# --------------------------------------------------------------------------- CA-09


def test_ca09_score_and_confidence_null_iff_grade_null() -> None:
    m = InspectionCreate.model_validate(unknown_payload())
    assert m.object_type is ObjectType.UNKNOWN
    assert m.grade is None and m.grade_score is None and m.grade_confidence is None

    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(unknown_payload(grade_score=1.0))
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(unknown_payload(grade_confidence=0.5))
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(base_payload(grade="fair", grade_score=None))
    # Symmetric case of the same invariant (grade present, confidence null).
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(base_payload(grade="fair", grade_confidence=None))


# --------------------------------------------------------------------------- CA-10

_UUID_V1 = str(uuid.uuid1())

CA10_CASES = [
    ("type_confidence", 1.01),
    ("type_confidence", -0.01),
    ("grade_confidence", 1.5),
    ("grade_score", 4.01),
    ("grade_score", float("nan")),
    ("latency_ms", -1),
    ("device_id", "Edge_01"),
    ("device_id", "ab"),
    ("lot_id", ""),
    ("lot_id", "L 001"),
    ("lot_id", "L" * 41),
    ("model_version", "PartQC-V1"),
    ("model_sha256", "a" * 63),
    ("model_sha256", "A" * 64),
    ("inspection_id", _UUID_V1),
    ("source", "test"),
    ("object_type", "bolt"),
]


@pytest.mark.parametrize(
    ("field", "value"), CA10_CASES, ids=[f"{f}={v!r}"[:40] for f, v in CA10_CASES]
)
def test_ca10_invalid_field_values_rejected(field: str, value: Any) -> None:
    assert uuid.UUID(_UUID_V1).version == 1
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate(base_payload(**{field: value}))
    assert any(err["loc"][:1] == (field,) for err in exc.value.errors()), exc.value.errors()


# --------------------------------------------------------------------------- CA-11


def test_ca11_inclusive_limits_accepted() -> None:
    m = InspectionCreate.model_validate(
        base_payload(type_confidence=0.0, grade_confidence=1.0, grade_score=0.0, latency_ms=0)
    )
    assert m.type_confidence == 0.0
    assert m.grade_confidence == 1.0
    assert m.grade_score == 0.0
    assert m.latency_ms == 0
    # Other ends of the closed ranges.
    InspectionCreate.model_validate(
        base_payload(type_confidence=1.0, grade_confidence=0.0, grade_score=4.0)
    )


# --------------------------------------------------------------------------- CA-12


@pytest.mark.parametrize("extra", [{"image": "..."}, {"foo": 1}, {"is_defective": True}])
def test_ca12_extra_fields_forbidden(extra: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate(base_payload(**extra))
    errors = exc.value.errors()
    assert errors and all(err["type"] == "extra_forbidden" for err in errors), errors
    assert {err["loc"] for err in errors} == {(k,) for k in extra}


# --------------------------------------------------------------------------- CA-13


def _items(n: int) -> list[dict[str, Any]]:
    return [base_payload(inspection_id=str(uuid.uuid4())) for _ in range(n)]


def test_ca13_batch_size_and_error_location() -> None:
    for n in (0, 101):
        with pytest.raises(ValidationError):
            BatchCreate.model_validate({"items": _items(n)})

    for n in (1, 100):
        batch = BatchCreate.model_validate({"items": _items(n)})
        assert len(batch.items) == n
        assert all(isinstance(i, InspectionCreate) for i in batch.items)

    items = _items(100)
    items[56]["type_confidence"] = 2.0  # 57th item
    with pytest.raises(ValidationError) as exc:
        BatchCreate.model_validate({"items": items})
    errors = exc.value.errors()
    assert errors
    assert all(err["loc"][:2] == ("items", 56) for err in errors), errors


# --------------------------------------------------------------------------- CA-14


def test_ca14_inspection_read_tolerates_extra_and_future() -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    payload = read_payload(foo=1, inspected_at=future)
    m = InspectionRead.model_validate(payload)
    assert m.is_defective is False
    assert m.inspected_at == future
    assert m.received_at.tzinfo == UTC
    assert "foo" not in m.model_dump()
    assert not hasattr(m, "foo")
    assert not m.model_extra  # None or empty: the extra field was dropped


# --------------------------------------------------------------------------- CA-15


def test_ca15_inspection_created_status() -> None:
    for status in ("created", "duplicate"):
        m = InspectionCreated.model_validate({"inspection_id": FIXED_ID, "status": status})
        assert m.status == status
        assert m.inspection_id == uuid.UUID(FIXED_ID)
    with pytest.raises(ValidationError):
        InspectionCreated.model_validate({"inspection_id": FIXED_ID, "status": "ok"})


# --------------------------------------------------------------------------- CA-16

INSPECTION_READ_JSON: dict[str, Any] = {
    "inspection_id": FIXED_ID,
    "device_id": "edge-01",
    "lot_id": "L-001",
    "inspected_at": "2026-10-01T15:00:00Z",
    "object_type": "screw",
    "grade": "poor",
    "grade_score": 2.9,
    "type_confidence": 0.97,
    "grade_confidence": 0.66,
    "needs_review": False,
    "model_version": "partqc-mnv3-v1",
    "model_sha256": "0123456789abcdef" * 4,
    "latency_ms": 120,
    "source": "live",
    "received_at": "2026-10-01T15:00:02.500000Z",
    "is_defective": True,
}

INSPECTION_READ_UNKNOWN_JSON: dict[str, Any] = {
    **INSPECTION_READ_JSON,
    "inspection_id": "9d1c6f0a-2b3e-4c5d-9e8f-0a1b2c3d4e5f",
    "object_type": "unknown",
    "grade": None,
    "grade_score": None,
    "grade_confidence": None,
    "source": "simulated",
    "is_defective": False,
}

PAGE_JSON: dict[str, Any] = {
    "items": [INSPECTION_READ_JSON, INSPECTION_READ_UNKNOWN_JSON],
    "total": 42,
    "limit": 2,
    "offset": 10,
}

METRICS_JSON: dict[str, Any] = {
    "total": 10,
    "defective": 3,
    "defect_rate": 0.3333333333333333,
    "unknown_count": 1,
    "needs_review_count": 2,
    "by_grade": {"perfect": 2, "good": 2, "fair": 2, "poor": 2, "unusable": 1},
    "by_object_type": {"screw": 6, "nut": 3, "unknown": 1},
    "mean_type_confidence": 0.91,
    "mean_grade_score": 1.7,
}

METRICS_EMPTY_JSON: dict[str, Any] = {
    "total": 0,
    "defective": 0,
    "defect_rate": None,
    "unknown_count": 0,
    "needs_review_count": 0,
    "by_grade": {},
    "by_object_type": {},
    "mean_type_confidence": None,
    "mean_grade_score": None,
}

TIMESERIES_JSON: dict[str, Any] = {
    "bucket_start": "2026-10-01T15:00:00Z",
    "total": 8,
    "defective": 2,
    "defect_rate": 0.25,
}

TIMESERIES_EMPTY_JSON: dict[str, Any] = {
    "bucket_start": "2026-10-01T16:00:00Z",
    "total": 0,
    "defective": 0,
    "defect_rate": None,
}

# architecture.md section 3.4 example, with "..." replaced by real UTC timestamps.
SPC_JSON: dict[str, Any] = {
    "baseline_lots": 20,
    "min_lot_size": 5,
    "source": "live",
    "p_bar": 0.18,
    "points": [
        {
            "lot_id": "L-001",
            "started_at": "2026-10-01T12:00:00Z",
            "ended_at": "2026-10-01T12:30:00Z",
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

SPC_EMPTY_JSON: dict[str, Any] = {
    "baseline_lots": 20,
    "min_lot_size": 5,
    "source": "simulated",
    "p_bar": None,
    "points": [],
    "excluded_lots": [],
    "message": "fewer than 2 valid lots",
}

LOT_JSON: dict[str, Any] = {
    "lot_id": "L-001",
    "n": 12,
    "defects": 3,
    "unknown_count": 1,
    "started_at": "2026-10-01T12:00:00Z",
    "ended_at": "2026-10-01T12:45:00Z",
    "sources": ["live", "simulated"],
}

HEALTH_OK_JSON: dict[str, Any] = {
    "status": "ok",
    "db": "ok",
    "api_version": "0.1.0",
    "contract_version": "0.1.0",
}

HEALTH_DEGRADED_JSON: dict[str, Any] = {
    "status": "degraded",
    "db": "error",
    "api_version": "0.1.0",
    "contract_version": "0.1.0",
}

CA16_CASES = [
    ("page", Page[InspectionRead], PAGE_JSON),
    ("metrics", MetricsSummary, METRICS_JSON),
    ("metrics-empty", MetricsSummary, METRICS_EMPTY_JSON),
    ("timeseries", TimeseriesPoint, TIMESERIES_JSON),
    ("timeseries-empty", TimeseriesPoint, TIMESERIES_EMPTY_JSON),
    ("spc", SpcResponse, SPC_JSON),
    ("spc-empty", SpcResponse, SPC_EMPTY_JSON),
    ("lot", LotSummary, LOT_JSON),
    ("health-ok", HealthResponse, HEALTH_OK_JSON),
    ("health-degraded", HealthResponse, HEALTH_DEGRADED_JSON),
]


@pytest.mark.parametrize(
    ("model", "data"), [c[1:] for c in CA16_CASES], ids=[c[0] for c in CA16_CASES]
)
def test_ca16_response_models_json_round_trip(model: Any, data: dict[str, Any]) -> None:
    text = json.dumps(data)
    # SPEC-026 section 3.1, adjustment 3: the SPC cases dump the 3 optional cut fields as None.
    expected = data
    if model is SpcResponse:  # only the "spc" and "spc-empty" cases
        expected = {
            **data,
            "max_points": None,
            "valid_lots_total": None,
            "excluded_lots_total": None,
        }
    from_json = model.model_validate_json(text)
    assert from_json.model_dump(mode="json") == expected
    from_obj = model.model_validate(json.loads(text))
    assert from_obj.model_dump(mode="json") == expected


def test_ca16_health_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({**HEALTH_OK_JSON, "status": "up"})


def test_ca16_spc_types() -> None:
    spc = SpcResponse.model_validate_json(json.dumps(SPC_JSON))
    assert spc.source is Source.LIVE
    assert isinstance(spc.points[0], SpcPoint)
    assert isinstance(spc.excluded_lots[0], SpcExcludedLot)
    assert spc.points[0].started_at.tzinfo == UTC


# --------------------------------------------------------------------------- CA-17

EXPECTED_LABELS = [
    (
        GRADE_LABELS_PT,
        Grade,
        {
            "perfect": "perfeito",
            "good": "bom",
            "fair": "mediano",
            "poor": "ruim",
            "unusable": "inutilizável",
        },
    ),
    (
        OBJECT_TYPE_LABELS_PT,
        ObjectType,
        {
            "screw": "parafuso",
            "nut": "porca",
            "unknown": "desconhecido",
            # SPEC-016 section 4.1: labels of the 5 hand tools.
            "pliers": "alicate",
            "adjustable_wrench": "chave inglesa",
            "allen_key": "chave Allen",
            "flat_screwdriver": "chave de fenda",
            "phillips_screwdriver": "chave Phillips",
            # SPEC-021 section 3.1: labels of the 4 power tools.
            "angle_grinder": "esmerilhadeira",
            "saw": "serra",
            "drill": "furadeira",
            "cordless_screwdriver": "parafusadeira",
        },
    ),
    (SOURCE_LABELS_PT, Source, {"live": "real", "simulated": "simulado"}),
    (CAPTURE_MODE_LABELS_PT, CaptureMode, {"inspect": "inspeção", "collect": "coleta"}),
]


@pytest.mark.parametrize(
    ("mapping", "enum_cls", "expected"),
    EXPECTED_LABELS,
    ids=["grade", "object_type", "source", "capture_mode"],
)
def test_ca17_labels_match_enums_and_are_immutable(
    mapping: Any, enum_cls: Any, expected: dict[str, str]
) -> None:
    assert isinstance(mapping, types.MappingProxyType)
    assert len(mapping) == len(enum_cls)
    assert set(mapping.keys()) == set(enum_cls)
    for member in enum_cls:
        assert mapping[member] == expected[member.value]
    with pytest.raises(TypeError):
        mapping[next(iter(enum_cls))] = "x"


def test_ca17_grade_label_examples() -> None:
    assert GRADE_LABELS_PT[Grade.UNUSABLE] == "inutilizável"
    with pytest.raises(TypeError):
        GRADE_LABELS_PT[Grade.FAIR] = "x"  # type: ignore[index]
    assert GRADE_LABELS_PT[Grade.FAIR] == "mediano"


# --------------------------------------------------------------------------- CA-18

ALLOWED_IMPORTS = {
    "enum",
    "datetime",
    "uuid",
    "re",
    "math",
    "types",
    "typing",
    "collections.abc",
    "__future__",
    "pydantic",
    "annotated_types",
    "qc_contracts",
}


def _allowed(module: str) -> bool:
    if module in ALLOWED_IMPORTS:
        return True
    root = module.split(".")[0]
    # Submodules are allowed only for third-party/own packages, not for "collections".
    return root in {"pydantic", "annotated_types", "qc_contracts"}


def _requirement_names(dist: str) -> set[str]:
    names = set()
    for req in importlib.metadata.requires(dist) or []:
        if "extra ==" in req:
            continue
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
        assert match, req
        names.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
    return names


def test_ca18_contracts_imports_only_stdlib_without_io_and_pydantic() -> None:
    src = Path(qc_contracts.__file__).resolve().parent
    files = sorted(src.rglob("*.py"))
    assert {f.name for f in files} >= {
        "__init__.py",
        "enums.py",
        "defects.py",
        "schemas.py",
        "labels.py",
    }
    offenders: list[str] = []
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not _allowed(alias.name):
                        offenders.append(f"{file.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    continue  # relative import = qc_contracts itself
                module = node.module or ""
                if not _allowed(module):
                    offenders.append(f"{file.name}: from {module} import ...")
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in {
                "__import__",
                "open",
            }:
                offenders.append(f"{file.name}: call {node.func.id}")  # type: ignore[attr-defined]
    assert offenders == []
    assert _requirement_names("qc-contracts") == {"pydantic"}


# --------------------------------------------------------------------------- CA-27


def test_ca27_readme_version_history() -> None:
    text = README.read_text(encoding="utf-8")
    lines = text.splitlines()
    heading = [i for i, line in enumerate(lines) if "Histórico de versões" in line]
    assert heading, "README lacks 'Histórico de versões'"
    after = lines[heading[0] + 1 :]
    table_rows = [line for line in after if line.lstrip().startswith("|")]
    assert table_rows, "no table after 'Histórico de versões'"
    row = [r for r in table_rows if "0.1.0" in r]
    assert row, table_rows
    assert "2026-10" in row[0]
    assert "SPEC-002" in row[0]


# --------------------------------------------------------------------------- extras
# Requirements from SPEC-002 section 4 not covered by a specific CA.


def test_extra_public_api_reexported_from_package() -> None:
    for name in (
        "ObjectType",
        "Grade",
        "Source",
        "CaptureMode",
        "GRADE_ORDER",
        "grade_index",
        "grade_from_index",
        "is_defective",
        "InspectionCreate",
        "InspectionRead",
        "InspectionCreated",
        "BatchCreate",
        "BatchResult",
        "Page",
        "MetricsSummary",
        "TimeseriesPoint",
        "SpcPoint",
        "SpcExcludedLot",
        "SpcResponse",
        "LotSummary",
        "HealthResponse",
        "GRADE_LABELS_PT",
        "OBJECT_TYPE_LABELS_PT",
        "SOURCE_LABELS_PT",
        "CAPTURE_MODE_LABELS_PT",
        "DEVICE_ID_PATTERN",
        "LOT_ID_PATTERN",
        "MODEL_VERSION_PATTERN",
        "SHA256_PATTERN",
    ):
        assert hasattr(qc_contracts, name), name
    assert qc_contracts.is_defective is is_defective
    assert qc_contracts.InspectionCreate is InspectionCreate


def test_extra_health_status_ok_iff_db_ok() -> None:
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({**HEALTH_OK_JSON, "db": "error"})
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({**HEALTH_DEGRADED_JSON, "db": "ok"})
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({**HEALTH_OK_JSON, "db": "down"})


def test_extra_page_bounds() -> None:
    for bad in ({"total": -1}, {"limit": 0}, {"offset": -1}):
        with pytest.raises(ValidationError):
            Page[InspectionRead].model_validate({**PAGE_JSON, **bad})
    page = Page[InspectionRead].model_validate({**PAGE_JSON, "items": [], "limit": 1})
    assert page.items == [] and page.limit == 1


def test_extra_inspection_read_keeps_invariants_and_utc() -> None:
    with pytest.raises(ValidationError):
        InspectionRead.model_validate(read_payload(object_type="unknown"))
    with pytest.raises(ValidationError):
        InspectionRead.model_validate(read_payload(received_at="2026-10-01T12:00:00"))
    with pytest.raises(ValidationError):
        InspectionRead.model_validate(read_payload(type_confidence=1.5))
    for missing in ("received_at", "is_defective"):
        payload = read_payload()
        del payload[missing]
        with pytest.raises(ValidationError):
            InspectionRead.model_validate(payload)
    m = InspectionRead.model_validate(
        read_payload(received_at=datetime(2026, 10, 1, 12, 0, tzinfo=BRT))
    )
    assert m.received_at == datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
    assert m.received_at.tzinfo == UTC


def test_extra_batch_rejects_extra_and_result_round_trip() -> None:
    with pytest.raises(ValidationError) as exc:
        BatchCreate.model_validate({"items": _items(1), "foo": 1})
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())

    data = {
        "results": [
            {"inspection_id": FIXED_ID, "status": "created"},
            {"inspection_id": "9d1c6f0a-2b3e-4c5d-9e8f-0a1b2c3d4e5f", "status": "duplicate"},
        ]
    }
    result = BatchResult.model_validate_json(json.dumps(data))
    assert result.model_dump(mode="json") == data
    assert [r.status for r in result.results] == ["created", "duplicate"]


@pytest.mark.parametrize(
    "model",
    [MetricsSummary, TimeseriesPoint, SpcResponse, LotSummary, HealthResponse, InspectionCreated],
)
def test_extra_response_models_ignore_unknown_fields(model: Any) -> None:
    base = {
        MetricsSummary: METRICS_JSON,
        TimeseriesPoint: TIMESERIES_JSON,
        SpcResponse: SPC_JSON,
        LotSummary: LOT_JSON,
        HealthResponse: HEALTH_OK_JSON,
        InspectionCreated: {"inspection_id": FIXED_ID, "status": "created"},
    }[model]
    m = model.model_validate({**base, "new_field_from_minor": 1})
    assert "new_field_from_minor" not in m.model_dump()


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
@pytest.mark.parametrize("field", ["type_confidence", "grade_confidence", "grade_score"])
def test_extra_non_finite_floats_rejected(field: str, value: float) -> None:
    assert not math.isfinite(value)
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(base_payload(**{field: value}))


@pytest.mark.parametrize(
    "text", ['"NaN"', "NaN", "Infinity", "-Infinity", '"inf"', '"-inf"', '"nan"']
)
def test_extra_non_finite_floats_rejected_from_json(text: str) -> None:
    payload = base_payload()
    payload["inspected_at"] = payload["inspected_at"].isoformat()
    raw = json.dumps(payload).replace('"grade_score": 2.1', f'"grade_score": {text}')
    assert text in raw
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate_json(raw)


@pytest.mark.parametrize("value", [1.5, "abc", None])
def test_extra_latency_must_be_int(value: Any) -> None:
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(base_payload(latency_ms=value))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("device_id", "edge-01\n"),
        ("lot_id", "L-001\n"),
        ("model_version", "partqc-mnv3-v1\n"),
        ("model_sha256", "a" * 64 + "\n"),
        ("device_id", "é" * 5),
        ("lot_id", "Lóte"),
        ("device_id", "a" * 33),
        ("model_version", "a" * 41),
        ("model_version", "ab"),
    ],
)
def test_extra_pattern_edge_cases_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(base_payload(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("device_id", "abc"),
        ("device_id", "a" * 32),
        ("lot_id", "L"),
        ("lot_id", "A_z-9" * 8),
        ("model_version", "v.1"),
        ("model_version", "a" * 40),
        ("model_sha256", "0123456789abcdef" * 4),
    ],
)
def test_extra_pattern_boundaries_accepted(field: str, value: str) -> None:
    m = InspectionCreate.model_validate(base_payload(**{field: value}))
    assert getattr(m, field) == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("inspection_id", "00000000-0000-0000-0000-000000000000"),
        ("inspection_id", str(uuid.uuid3(uuid.NAMESPACE_DNS, "x"))),
        ("inspection_id", str(uuid.uuid5(uuid.NAMESPACE_DNS, "x"))),
        ("inspection_id", "not-a-uuid"),
        ("needs_review", "maybe"),
        ("grade", "excellent"),
        ("source", "LIVE"),
    ],
)
def test_extra_other_invalid_values(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(base_payload(**{field: value}))


@pytest.mark.parametrize("field", list(base_payload().keys()))
def test_extra_every_field_is_required(field: str) -> None:
    payload = base_payload()
    del payload[field]
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(payload)


def test_extra_inspected_at_in_other_offsets_and_z() -> None:
    m = InspectionCreate.model_validate(base_payload(inspected_at="2026-01-10T15:00:00Z"))
    assert m.inspected_at == datetime(2026, 1, 10, 15, 0, tzinfo=UTC)
    m2 = InspectionCreate.model_validate(base_payload(inspected_at="2026-01-10T20:30:00+05:30"))
    assert m2.inspected_at == datetime(2026, 1, 10, 15, 0, tzinfo=UTC)
    assert m2.inspected_at.tzinfo == UTC
    # Future check uses the instant, not the wall clock: now+4min written at +14:00 is accepted.
    plus14 = timezone(timedelta(hours=14))
    InspectionCreate.model_validate(
        base_payload(inspected_at=(datetime.now(UTC) + timedelta(minutes=4)).astimezone(plus14))
    )
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(
            base_payload(
                inspected_at=(datetime.now(UTC) + timedelta(minutes=6)).astimezone(
                    timezone(timedelta(hours=-12))
                )
            )
        )


def test_extra_grade_from_index_rejects_non_int() -> None:
    for bad in (True, 1.0, "1", None):
        with pytest.raises((ValueError, TypeError)):
            grade_from_index(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["POOR", "", " poor", "unknown"])
def test_extra_is_defective_rejects_non_grade_strings(bad: str) -> None:
    with pytest.raises(ValueError):
        is_defective(bad)  # type: ignore[arg-type]


def test_extra_models_validate_enum_members_directly() -> None:
    m = InspectionCreate.model_validate(
        base_payload(
            object_type=ObjectType.NUT,
            grade=Grade.UNUSABLE,
            source=Source.SIMULATED,
            inspection_id=uuid.UUID(FIXED_ID),
        )
    )
    assert m.object_type is ObjectType.NUT
    assert m.grade is Grade.UNUSABLE
    assert m.source is Source.SIMULATED
    assert is_defective(m.grade) is True
    dumped = m.model_dump(mode="json")
    assert dumped["source"] == "simulated" and dumped["grade"] == "unusable"


# --------------------------------------------------------------------------- T-01 (r1)
# Regression tests for bug T-01 (reviews/SPEC-002/r1-test-report.md, RV-01 in the r1
# review): a datetime that leaves the datetime range once shifted to UTC raised a raw
# OverflowError instead of a ValidationError. Section 4.3 requires every datetime to be
# validated and normalized to UTC. Fixed in r2; these were an xfail in r1.

YEAR1_PLUS5 = "0001-01-01T00:00:00+05:00"  # UTC instant is before year 1
YEAR9999_MINUS5 = "9999-12-31T23:59:59-05:00"  # UTC instant is after year 9999


def _json_ready(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in payload.items()}


T01_CASES = [
    ("create-inspected-year1", InspectionCreate, base_payload, "inspected_at", YEAR1_PLUS5),
    ("create-inspected-9999", InspectionCreate, base_payload, "inspected_at", YEAR9999_MINUS5),
    ("read-inspected-year1", InspectionRead, read_payload, "inspected_at", YEAR1_PLUS5),
    ("read-inspected-9999", InspectionRead, read_payload, "inspected_at", YEAR9999_MINUS5),
    ("read-received-year1", InspectionRead, read_payload, "received_at", YEAR1_PLUS5),
    ("read-received-9999", InspectionRead, read_payload, "received_at", YEAR9999_MINUS5),
    (
        "timeseries-bucket",
        TimeseriesPoint,
        lambda: dict(TIMESERIES_JSON),
        "bucket_start",
        YEAR1_PLUS5,
    ),
    ("spc-point-started", SpcPoint, lambda: dict(SPC_JSON["points"][0]), "started_at", YEAR1_PLUS5),
    ("spc-point-ended", SpcPoint, lambda: dict(SPC_JSON["points"][0]), "ended_at", YEAR9999_MINUS5),
    ("lot-started", LotSummary, lambda: dict(LOT_JSON), "started_at", YEAR1_PLUS5),
    ("lot-ended", LotSummary, lambda: dict(LOT_JSON), "ended_at", YEAR9999_MINUS5),
]


def _assert_single_value_error(exc: ValidationError, loc: tuple[Any, ...]) -> None:
    errors = exc.errors()
    assert len(errors) == 1, errors
    assert errors[0]["type"] == "value_error"
    assert errors[0]["loc"] == loc


@pytest.mark.parametrize("how", ["python", "json", "datetime-object"])
@pytest.mark.parametrize(
    ("model", "make", "field", "value"),
    [c[1:] for c in T01_CASES],
    ids=[c[0] for c in T01_CASES],
)
def test_extra_t01_out_of_range_after_utc_is_validation_error(
    model: Any, make: Any, field: str, value: str, how: str
) -> None:
    payload = make()
    payload[field] = datetime.fromisoformat(value) if how == "datetime-object" else value
    with pytest.raises(ValidationError) as info:
        if how == "json":
            model.model_validate_json(json.dumps(_json_ready(payload)))
        else:
            model.model_validate(payload)
    _assert_single_value_error(info.value, (field,))


def test_extra_t01_batch_points_to_the_bad_item_only() -> None:
    items = [_json_ready(base_payload(inspection_id=str(uuid.uuid4()))) for _ in range(3)]
    items[1]["inspected_at"] = YEAR1_PLUS5
    with pytest.raises(ValidationError) as info:
        BatchCreate.model_validate_json(json.dumps({"items": items}))
    _assert_single_value_error(info.value, ("items", 1, "inspected_at"))


def test_extra_t01_nested_spc_point_is_validation_error() -> None:
    data = json.loads(json.dumps(SPC_JSON))
    data["points"][0]["started_at"] = YEAR1_PLUS5
    with pytest.raises(ValidationError) as info:
        SpcResponse.model_validate_json(json.dumps(data))
    _assert_single_value_error(info.value, ("points", 0, "started_at"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0001-01-01T00:00:00Z", datetime(1, 1, 1, tzinfo=UTC)),
        ("0001-01-01T05:00:00+05:00", datetime(1, 1, 1, tzinfo=UTC)),
        ("9999-12-31T23:59:59Z", datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)),
        ("9999-12-31T18:59:59-05:00", datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)),
    ],
)
def test_extra_t01_extremes_inside_utc_range_still_accepted(value: str, expected: datetime) -> None:
    read = InspectionRead.model_validate(read_payload(received_at=value))
    assert read.received_at == expected
    assert read.received_at.tzinfo == UTC
    lot = LotSummary.model_validate({**LOT_JSON, "started_at": value})
    assert lot.started_at == expected
    if expected.year == 1:  # the 5-minute future rule rejects year 9999 in InspectionCreate
        create = InspectionCreate.model_validate(base_payload(inspected_at=value))
        assert create.inspected_at == expected
        assert create.inspected_at.tzinfo == UTC
