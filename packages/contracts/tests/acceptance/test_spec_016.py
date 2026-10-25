"""Acceptance tests for SPEC-016 (qc-contracts 0.4.0: hand tools and the grade groups, ADR-021).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-01 and CA-02. Tests named ``test_extra_*`` are exploratory edge cases
around SPEC-016 section 4.1 that no CA spells out.

Per ``docs/architecture.md`` section 10 ("Expectativas de versão"), this file is the current
SPEC of ``qc-contracts``: the exact version comparison lives only in ``test_ca01_*`` here.
"""

from __future__ import annotations

import importlib.metadata
import itertools
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import qc_contracts
from qc_contracts import (
    GRADE_FORBIDDEN_OBJECT_TYPES,
    GRADE_OPTIONAL_OBJECT_TYPES,
    GRADE_REQUIRED_OBJECT_TYPES,
    OBJECT_TYPE_LABELS_PT,
    Grade,
    InspectionCreate,
    InspectionRead,
    ObjectType,
    is_defective,
)

pytestmark = pytest.mark.acceptance

PKG_ROOT = Path(__file__).resolve().parents[2]  # packages/contracts
README = PKG_ROOT / "README.md"
PYPROJECT = PKG_ROOT / "pyproject.toml"

TOOLS = [
    "pliers",
    "adjustable_wrench",
    "allen_key",
    "flat_screwdriver",
    "phillips_screwdriver",
]
ALL_TYPES = ["screw", "nut", "unknown", *TOOLS]
TOOL_LABELS = {
    ObjectType.PLIERS: "alicate",
    ObjectType.ADJUSTABLE_WRENCH: "chave inglesa",
    ObjectType.ALLEN_KEY: "chave Allen",
    ObjectType.FLAT_SCREWDRIVER: "chave de fenda",
    ObjectType.PHILLIPS_SCREWDRIVER: "chave Phillips",
}
GRADE_SCORES = {"perfect": 0.0, "good": 1.0, "fair": 2.0, "poor": 3.0, "unusable": 4.0}


def base_payload(**overrides: Any) -> dict[str, Any]:
    """A valid ``InspectionCreate`` (``screw``/``good``), JSON-like."""
    data: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-016",
        "inspected_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "object_type": "screw",
        "grade": "good",
        "grade_score": 1.0,
        "type_confidence": 0.91,
        "grade_confidence": 0.8,
        "needs_review": False,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": "a" * 64,
        "latency_ms": 42,
        "source": "live",
    }
    data.update(overrides)
    return data


def ungraded(object_type: str) -> dict[str, Any]:
    return base_payload(
        object_type=object_type, grade=None, grade_score=None, grade_confidence=None
    )


def graded(object_type: str, grade: str) -> dict[str, Any]:
    return base_payload(
        object_type=object_type,
        grade=grade,
        grade_score=GRADE_SCORES[grade],
        grade_confidence=0.7,
    )


def _accepted(data: dict[str, Any]) -> bool:
    try:
        InspectionCreate.model_validate(data)
    except ValidationError:
        return False
    return True


# --------------------------------------------------------------------------- CA-01


def test_ca01_contracts_version_is_0_4_0() -> None:
    v = qc_contracts.__version__
    assert qc_contracts.__version__ == importlib.metadata.version("qc-contracts")
    assert re.fullmatch(r"\d+\.\d+\.\d+", v)
    assert (0, 4, 0) <= tuple(int(p) for p in v.split(".")) < (1, 0, 0)


def test_ca01_object_type_members_in_order() -> None:
    assert [m.value for m in ObjectType] == ALL_TYPES


def test_ca01_tool_labels_pt() -> None:
    for member, label in TOOL_LABELS.items():
        assert OBJECT_TYPE_LABELS_PT[member] == label, member
    # The MVP labels did not change.
    assert OBJECT_TYPE_LABELS_PT[ObjectType.SCREW] == "parafuso"
    assert OBJECT_TYPE_LABELS_PT[ObjectType.NUT] == "porca"
    assert OBJECT_TYPE_LABELS_PT[ObjectType.UNKNOWN] == "desconhecido"
    assert set(OBJECT_TYPE_LABELS_PT) == set(ObjectType)


def test_ca01_grade_groups_are_disjoint_and_cover_the_enum() -> None:
    groups = (
        GRADE_REQUIRED_OBJECT_TYPES,
        GRADE_FORBIDDEN_OBJECT_TYPES,
        GRADE_OPTIONAL_OBJECT_TYPES,
    )
    for a, b in itertools.combinations(groups, 2):
        assert a.isdisjoint(b), (a, b)
    union = GRADE_REQUIRED_OBJECT_TYPES | GRADE_FORBIDDEN_OBJECT_TYPES | GRADE_OPTIONAL_OBJECT_TYPES
    assert union == set(ObjectType)
    assert sum(len(g) for g in groups) == 8
    assert {m.value for m in GRADE_REQUIRED_OBJECT_TYPES} == {"screw", "nut"}
    assert {m.value for m in GRADE_FORBIDDEN_OBJECT_TYPES} == {"unknown"}
    assert {m.value for m in GRADE_OPTIONAL_OBJECT_TYPES} == set(TOOLS)


def test_ca01_pyproject_and_readme_history() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    assert match is not None
    assert match.group(1) == qc_contracts.__version__
    rows = [line for line in README.read_text(encoding="utf-8").splitlines() if "0.4.0" in line]
    assert any(line.startswith("| 0.4.0 |") and "SPEC-016" in line for line in rows), rows


# --------------------------------------------------------------------------- CA-02


def test_ca02_case_a_tool_without_grade_is_accepted() -> None:
    insp = InspectionCreate.model_validate(ungraded("pliers"))
    assert insp.object_type == ObjectType.PLIERS
    assert insp.grade is None
    assert insp.grade_score is None
    assert insp.grade_confidence is None


def test_ca02_case_b_tool_with_grade_is_accepted() -> None:
    data = base_payload(object_type="pliers", grade="fair", grade_score=2.0, grade_confidence=0.7)
    insp = InspectionCreate.model_validate(data)
    assert insp.grade == Grade.FAIR
    assert insp.grade_score == pytest.approx(2.0)
    assert insp.grade_confidence == pytest.approx(0.7)


def test_ca02_case_c_screw_without_grade_is_rejected() -> None:
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(ungraded("screw"))


def test_ca02_case_d_unknown_with_grade_is_rejected() -> None:
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(
            base_payload(object_type="unknown", grade="good", grade_score=1.0, grade_confidence=0.8)
        )


def test_ca02_case_e_tool_with_grade_and_null_score_is_rejected() -> None:
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(
            base_payload(object_type="pliers", grade="fair", grade_score=None, grade_confidence=0.7)
        )


def test_ca02_inspection_read_with_tool_without_grade() -> None:
    data = {**ungraded("pliers"), "received_at": datetime.now(UTC).isoformat()}
    data["is_defective"] = False
    read = InspectionRead.model_validate(data)
    assert read.object_type == ObjectType.PLIERS
    assert read.grade is None
    assert read.is_defective is False


# --------------------------------------------------------------------------- extras


@pytest.mark.parametrize("object_type", ALL_TYPES)
@pytest.mark.parametrize("grade", [None, *GRADE_SCORES])
def test_extra_invariant_matrix_follows_the_groups(object_type: str, grade: str | None) -> None:
    """Every (type, grade or null) pair follows section 4.1, in both schemas."""
    member = ObjectType(object_type)
    if member in GRADE_REQUIRED_OBJECT_TYPES:
        expected = grade is not None
    elif member in GRADE_FORBIDDEN_OBJECT_TYPES:
        expected = grade is None
    else:
        expected = True
    data = ungraded(object_type) if grade is None else graded(object_type, grade)
    assert _accepted(data) is expected
    read = {**data, "received_at": datetime.now(UTC).isoformat(), "is_defective": False}
    try:
        InspectionRead.model_validate(read)
        read_ok = True
    except ValidationError:
        read_ok = False
    assert read_ok is expected


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize(
    ("score", "conf"),
    [(2.0, None), (None, 0.7), (2.0, 0.7)],
    ids=["score-only", "conf-only", "both"],
)
def test_extra_tool_without_grade_needs_both_nulls(
    tool: str, score: float | None, conf: float | None
) -> None:
    """``grade_score`` and ``grade_confidence`` are null iff ``grade`` is null (section 4.1)."""
    data = base_payload(object_type=tool, grade=None, grade_score=score, grade_confidence=conf)
    assert _accepted(data) is False


@pytest.mark.parametrize("tool", TOOLS)
def test_extra_tool_with_grade_and_null_confidence_is_rejected(tool: str) -> None:
    data = base_payload(object_type=tool, grade="good", grade_score=1.0, grade_confidence=None)
    assert _accepted(data) is False


def test_extra_invariant_messages_carry_no_values() -> None:
    """Section 4.1: the messages cite the rule, without values."""
    marker_lot = "L-MARK016"
    cases = [
        ungraded("screw"),
        base_payload(object_type="unknown", grade="poor", grade_score=3.0, grade_confidence=0.9),
        base_payload(object_type="pliers", grade="poor", grade_score=None, grade_confidence=0.9),
    ]
    for data in cases:
        data["lot_id"] = marker_lot
        with pytest.raises(ValidationError) as info:
            InspectionCreate.model_validate(data)
        for err in info.value.errors():
            msg = str(err["msg"])
            assert marker_lot not in msg
            assert "poor" not in msg and "screw" not in msg and "pliers" not in msg, msg


def test_extra_groups_are_frozensets_of_the_enum_at_the_root() -> None:
    for name in (
        "GRADE_REQUIRED_OBJECT_TYPES",
        "GRADE_FORBIDDEN_OBJECT_TYPES",
        "GRADE_OPTIONAL_OBJECT_TYPES",
    ):
        group = getattr(qc_contracts, name)
        assert isinstance(group, frozenset), name
        assert all(isinstance(m, ObjectType) for m in group), name
        assert name in qc_contracts.__all__, name


def test_extra_tool_members_are_strings_with_the_code_value() -> None:
    for value in TOOLS:
        member = ObjectType(value)
        assert member == value
        assert str(member) == value
        assert json.dumps({"t": member}) == json.dumps({"t": value})


def test_extra_hammer_and_case_variants_are_not_object_types() -> None:
    for value in ("hammer", "Pliers", "PLIERS", "pliers ", "allen-key", "other", ""):
        assert _accepted(base_payload(object_type=value, grade="good")) is False, value


def test_extra_is_defective_rule_unchanged() -> None:
    assert [is_defective(g) for g in Grade] == [False, False, False, True, True]
    assert is_defective(None) is False


def test_extra_json_round_trip_of_tool_payloads() -> None:
    for data in (ungraded("allen_key"), graded("phillips_screwdriver", "unusable")):
        insp = InspectionCreate.model_validate_json(json.dumps(data))
        again = InspectionCreate.model_validate_json(insp.model_dump_json())
        assert again == insp
        assert again.model_dump(mode="json")["object_type"] == data["object_type"]


def test_extra_extra_fields_still_forbidden_for_tools() -> None:
    assert _accepted({**ungraded("pliers"), "ungraded": True}) is False
