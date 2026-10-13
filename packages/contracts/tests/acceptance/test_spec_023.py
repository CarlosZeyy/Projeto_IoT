"""Acceptance tests for SPEC-023 (qc-contracts 0.2.0: ceiling of ``latency_ms``).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-01 (qc-contracts part), CA-02 (qc-contracts part), CA-03 to CA-06
and CA-13. Tests named ``test_extra_*`` are exploratory edge cases around SPEC-023 section 4.1
that no CA spells out.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import qc_contracts
import qc_contracts.schemas
from qc_contracts.schemas import BatchCreate, InspectionCreate, InspectionRead

pytestmark = pytest.mark.acceptance

PKG_ROOT = Path(__file__).resolve().parents[2]  # packages/contracts
ROOT = PKG_ROOT.parents[1]  # repository root
README = PKG_ROOT / "README.md"
BRT = timezone(timedelta(hours=-3))
FIXED_ID = "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b"  # UUID version 4

INT_COLUMN_MAX = 2_147_483_647  # PostgreSQL ``integer`` upper bound (2**31 - 1)
ABOVE = [2_147_483_648, 2**63]


def base_payload(**overrides: Any) -> dict[str, Any]:
    """Payload ``P`` of SPEC-002 CA-05 (the base of SPEC-023 section 5)."""
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


def as_json(payload: dict[str, Any]) -> str:
    """JSON text of a payload; integers are written exactly (no float rounding)."""
    return json.dumps(payload, default=lambda v: v.isoformat())


def read_payload(**overrides: Any) -> dict[str, Any]:
    payload = base_payload(received_at=datetime.now(UTC), is_defective=False)
    payload.update(overrides)
    return payload


def assert_single_le_error(exc: pytest.ExceptionInfo[ValidationError], loc: tuple) -> None:
    errors = exc.value.errors()
    assert len(errors) == 1, errors
    assert errors[0]["type"] == "less_than_equal", errors
    assert errors[0]["loc"] == loc, errors


# --------------------------------------------------------------------------- CA-01


def test_ca01_contracts_version() -> None:
    assert qc_contracts.__version__ == "0.2.0"
    assert importlib.metadata.version("qc-contracts") == "0.2.0"


def test_ca01_both_packages_version() -> None:
    import qc_preprocess

    assert qc_preprocess.__version__ == "0.3.0"
    assert importlib.metadata.version("qc-preprocess") == "0.3.0"


# --------------------------------------------------------------------------- CA-02


def test_ca02_max_latency_constant() -> None:
    assert qc_contracts.MAX_LATENCY_MS == qc_contracts.schemas.MAX_LATENCY_MS
    assert qc_contracts.MAX_LATENCY_MS == 2**31 - 1 == 2147483647
    assert type(qc_contracts.MAX_LATENCY_MS) is int
    assert qc_contracts.MAX_LATENCY_MS is qc_contracts.schemas.MAX_LATENCY_MS
    assert "MAX_LATENCY_MS" in getattr(qc_contracts, "__all__", ["MAX_LATENCY_MS"])


# --------------------------------------------------------------------------- CA-03


def test_ca03_ceiling_accepted_from_dict_and_json() -> None:
    p = base_payload(latency_ms=INT_COLUMN_MAX)
    m = InspectionCreate.model_validate(p)
    assert m.latency_ms == 2147483647
    j = InspectionCreate.model_validate_json(as_json(p))
    assert j.latency_ms == 2147483647
    assert '"latency_ms":2147483647' in as_json(p).replace(" ", "")


@pytest.mark.parametrize("value", ABOVE, ids=["2**31", "2**63"])
def test_ca03_above_ceiling_rejected_from_dict(value: int) -> None:
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate(base_payload(latency_ms=value))
    assert_single_le_error(exc, ("latency_ms",))


@pytest.mark.parametrize("value", ABOVE, ids=["2**31", "2**63"])
def test_ca03_above_ceiling_rejected_from_json(value: int) -> None:
    raw = as_json(base_payload(latency_ms=value))
    assert f'"latency_ms": {value}' in raw  # exact integer in the JSON text
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate_json(raw)
    assert_single_le_error(exc, ("latency_ms",))


# --------------------------------------------------------------------------- CA-04


def test_ca04_inspection_read_ceiling() -> None:
    with pytest.raises(ValidationError) as exc:
        InspectionRead.model_validate(read_payload(latency_ms=2_147_483_648))
    locs = [err["loc"] for err in exc.value.errors()]
    assert locs == [("latency_ms",)], exc.value.errors()

    ok = InspectionRead.model_validate(read_payload(latency_ms=2_147_483_647))
    assert ok.latency_ms == 2_147_483_647
    assert ok.is_defective is False


# --------------------------------------------------------------------------- CA-05


def test_ca05_batch_points_to_second_item() -> None:
    items = [base_payload(inspection_id=str(uuid.uuid4())) for _ in range(3)]
    items[1]["latency_ms"] = 2_147_483_648
    with pytest.raises(ValidationError) as exc:
        BatchCreate.model_validate({"items": items})
    errors = exc.value.errors()
    assert len(errors) == 1, errors
    assert errors[0]["loc"] == ("items", 1, "latency_ms"), errors
    assert errors[0]["type"] == "less_than_equal", errors

    # Same batch with the 2nd item at the ceiling is accepted.
    items[1]["latency_ms"] = 2_147_483_647
    batch = BatchCreate.model_validate({"items": items})
    assert [i.latency_ms for i in batch.items] == [120, 2_147_483_647, 120]


# --------------------------------------------------------------------------- CA-06


def test_ca06_readme_version_history_and_max_latency() -> None:
    text = README.read_text(encoding="utf-8")
    lines = text.splitlines()
    heading = [i for i, line in enumerate(lines) if "Histórico de versões" in line]
    assert heading, "README lacks 'Histórico de versões'"
    # Rows of the first table after the heading.
    rows: list[str] = []
    for line in lines[heading[0] + 1 :]:
        if line.lstrip().startswith("|"):
            rows.append(line)
        elif rows:
            break
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    v020 = [c for c in cells if c and c[0] == "0.2.0"]
    v010 = [c for c in cells if c and c[0] == "0.1.0"]
    assert v020, rows
    assert any("SPEC-023" in " ".join(c) for c in v020), v020
    assert v010, rows
    assert "MAX_LATENCY_MS" in text


# --------------------------------------------------------------------------- CA-13


# CA-13: checked by CI and by the test-report, not by a test (docs/architecture.md section 10).


# --------------------------------------------------------------------------- extras
# Exploratory edge cases around SPEC-023 section 4.1.


def test_extra_lower_bound_unchanged() -> None:
    assert InspectionCreate.model_validate(base_payload(latency_ms=0)).latency_ms == 0
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate(base_payload(latency_ms=-1))
    assert [e["loc"] for e in exc.value.errors()] == [("latency_ms",)]
    assert exc.value.errors()[0]["type"] == "greater_than_equal"


@pytest.mark.parametrize(
    "value",
    ["2147483648", 2_147_483_648.0, "9223372036854775808", 10**30],
    ids=["str-2**31", "float-2**31", "str-2**63", "10**30"],
)
def test_extra_lax_coercion_cannot_bypass_ceiling(value: Any) -> None:
    """Lax mode (kept by section 4.4) must not open a path around the ceiling."""
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate(base_payload(latency_ms=value))
    assert [e["loc"] for e in exc.value.errors()] == [("latency_ms",)], exc.value.errors()


def test_extra_lax_coercion_at_ceiling_still_accepted() -> None:
    for value in ("2147483647", 2_147_483_647.0):
        m = InspectionCreate.model_validate(base_payload(latency_ms=value))
        assert m.latency_ms == 2_147_483_647
        assert type(m.latency_ms) is int


def test_extra_huge_json_integer_rejected_without_crash() -> None:
    raw = as_json(base_payload()).replace('"latency_ms": 120', '"latency_ms": ' + "9" * 400)
    with pytest.raises(ValidationError) as exc:
        InspectionCreate.model_validate_json(raw)
    assert [e["loc"] for e in exc.value.errors()] == [("latency_ms",)], exc.value.errors()


def test_extra_batch_two_bad_items_two_errors() -> None:
    items = [base_payload(inspection_id=str(uuid.uuid4())) for _ in range(5)]
    items[0]["latency_ms"] = 2_147_483_648
    items[4]["latency_ms"] = 2**63
    with pytest.raises(ValidationError) as exc:
        BatchCreate.model_validate_json(json.dumps({"items": items}, default=str))
    locs = sorted(e["loc"] for e in exc.value.errors())
    assert locs == [("items", 0, "latency_ms"), ("items", 4, "latency_ms")], exc.value.errors()


def test_extra_ceiling_round_trip_and_json_schema() -> None:
    m = InspectionCreate.model_validate(base_payload(latency_ms=INT_COLUMN_MAX))
    again = InspectionCreate.model_validate_json(m.model_dump_json())
    assert again == m and again.latency_ms == INT_COLUMN_MAX
    # The ceiling is visible in the JSON schema (what FastAPI publishes in OpenAPI).
    prop = InspectionCreate.model_json_schema()["properties"]["latency_ms"]
    assert prop.get("maximum") == INT_COLUMN_MAX, prop
    assert prop.get("minimum") == 0, prop
    assert prop.get("type") == "integer", prop


def test_extra_contract_fields_unchanged() -> None:
    assert set(InspectionCreate.model_fields) == {
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
    }
    assert qc_contracts.schemas.DEVICE_ID_PATTERN == r"^[a-z0-9-]{3,32}$"
    assert qc_contracts.schemas.LOT_ID_PATTERN == r"^[A-Za-z0-9_-]{1,40}$"
    assert qc_contracts.schemas.MODEL_VERSION_PATTERN == r"^[a-z0-9.-]{3,40}$"
    assert qc_contracts.schemas.SHA256_PATTERN == r"^[0-9a-f]{64}$"


def test_extra_readme_mentions_lax_mode_rule() -> None:
    text = README.read_text(encoding="utf-8")
    assert re.search(r"\blax\b", text), "README lacks the lax-mode rule (SPEC-023 4.1)"
    assert "2 147 483 647" in text or "2147483647" in text or "2_147_483_647" in text
