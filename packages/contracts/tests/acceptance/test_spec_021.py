"""Acceptance tests for SPEC-021 (qc-contracts: the 4 power tools, always without grade, ADR-021).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-01 and CA-02. Tests named ``test_extra_*`` are exploratory edge cases
around SPEC-021 sections 3.1 and 4 that no CA spells out.

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

HAND_TOOLS = [
    "pliers",
    "adjustable_wrench",
    "allen_key",
    "flat_screwdriver",
    "phillips_screwdriver",
]
POWER_TOOLS = ["angle_grinder", "saw", "drill", "cordless_screwdriver"]
SPEC016_TYPES = ["screw", "nut", "unknown", *HAND_TOOLS]
ALL_TYPES = [*SPEC016_TYPES, *POWER_TOOLS]
POWER_LABELS = {
    "angle_grinder": "esmerilhadeira",
    "saw": "serra",
    "drill": "furadeira",
    "cordless_screwdriver": "parafusadeira",
}
GRADE_SCORES = {"perfect": 0.0, "good": 1.0, "fair": 2.0, "poor": 3.0, "unusable": 4.0}


def base_payload(**overrides: Any) -> dict[str, Any]:
    """A valid ``InspectionCreate`` (``screw``/``good``), JSON-like."""
    data: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-021",
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


def test_ca01_contracts_version_is_0_6_0() -> None:
    assert qc_contracts.__version__ == importlib.metadata.version("qc-contracts") == "0.6.0"


def test_ca01_last_four_object_types_are_the_power_tools_in_order() -> None:
    values = [m.value for m in ObjectType]
    assert values[-4:] == POWER_TOOLS
    # Placed right after phillips_screwdriver (section 3.1): the 8 earlier values come first.
    assert values == ALL_TYPES
    assert len(values) == 12


def test_ca01_power_tool_labels_pt() -> None:
    for value, label in POWER_LABELS.items():
        assert OBJECT_TYPE_LABELS_PT[ObjectType(value)] == label, value
    assert set(OBJECT_TYPE_LABELS_PT) == set(ObjectType)


def test_ca01_grade_forbidden_group_is_unknown_and_the_power_tools() -> None:
    assert {
        ObjectType.UNKNOWN,
        ObjectType.ANGLE_GRINDER,
        ObjectType.SAW,
        ObjectType.DRILL,
        ObjectType.CORDLESS_SCREWDRIVER,
    } == GRADE_FORBIDDEN_OBJECT_TYPES


def test_ca01_pyproject_and_readme_history() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    assert match is not None
    assert match.group(1) == qc_contracts.__version__
    rows = README.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("| 0.6.0 |") and "SPEC-021" in line for line in rows)


# --------------------------------------------------------------------------- CA-02


def test_ca02_drill_without_grade_is_accepted() -> None:
    insp = InspectionCreate.model_validate(ungraded("drill"))
    assert insp.object_type == ObjectType.DRILL
    assert insp.grade is None
    assert insp.grade_score is None
    assert insp.grade_confidence is None


def test_ca02_drill_with_grade_is_rejected() -> None:
    data = base_payload(object_type="drill", grade="fair", grade_score=2.0, grade_confidence=0.7)
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(data)


# --------------------------------------------------------------------------- extras


def test_extra_three_groups_are_disjoint_and_sum_the_12_members() -> None:
    """Section 4: the three groups stay disjoint and sum the 12 members."""
    groups = (
        GRADE_REQUIRED_OBJECT_TYPES,
        GRADE_FORBIDDEN_OBJECT_TYPES,
        GRADE_OPTIONAL_OBJECT_TYPES,
    )
    for a, b in itertools.combinations(groups, 2):
        assert a.isdisjoint(b), (a, b)
    assert sum(len(g) for g in groups) == 12
    union = GRADE_REQUIRED_OBJECT_TYPES | GRADE_FORBIDDEN_OBJECT_TYPES | GRADE_OPTIONAL_OBJECT_TYPES
    assert union == set(ObjectType)
    # The other two groups did not change (SPEC-016).
    assert {m.value for m in GRADE_REQUIRED_OBJECT_TYPES} == {"screw", "nut"}
    assert {m.value for m in GRADE_OPTIONAL_OBJECT_TYPES} == set(HAND_TOOLS)


@pytest.mark.parametrize("object_type", POWER_TOOLS)
@pytest.mark.parametrize("grade", [None, *GRADE_SCORES])
def test_extra_every_power_tool_only_without_grade(object_type: str, grade: str | None) -> None:
    data = ungraded(object_type) if grade is None else graded(object_type, grade)
    expected = grade is None
    assert _accepted(data) is expected
    read = {**data, "received_at": datetime.now(UTC).isoformat(), "is_defective": False}
    try:
        InspectionRead.model_validate(read)
        read_ok = True
    except ValidationError:
        read_ok = False
    assert read_ok is expected


@pytest.mark.parametrize("object_type", ALL_TYPES)
@pytest.mark.parametrize("grade", [None, *GRADE_SCORES])
def test_extra_invariant_matrix_of_the_12_types(object_type: str, grade: str | None) -> None:
    """72 pairs: the earlier 8 types keep the SPEC-016 rule, the power tools never take a grade."""
    if object_type in ("screw", "nut"):
        expected = grade is not None
    elif object_type == "unknown" or object_type in POWER_TOOLS:
        expected = grade is None
    else:
        expected = True
    data = ungraded(object_type) if grade is None else graded(object_type, grade)
    assert _accepted(data) is expected


@pytest.mark.parametrize("tool", POWER_TOOLS)
@pytest.mark.parametrize(
    ("score", "conf"),
    [(2.0, None), (None, 0.7), (2.0, 0.7)],
    ids=["score-only", "conf-only", "both"],
)
def test_extra_power_tool_with_score_or_confidence_is_rejected(
    tool: str, score: float | None, conf: float | None
) -> None:
    data = base_payload(object_type=tool, grade=None, grade_score=score, grade_confidence=conf)
    assert _accepted(data) is False


def test_extra_power_tool_messages_carry_no_values() -> None:
    marker_lot = "L-MARK021"
    data = base_payload(
        object_type="cordless_screwdriver",
        grade="unusable",
        grade_score=4.0,
        grade_confidence=0.9,
        lot_id=marker_lot,
    )
    with pytest.raises(ValidationError) as info:
        InspectionCreate.model_validate(data)
    for err in info.value.errors():
        msg = str(err["msg"])
        assert marker_lot not in msg
        assert "unusable" not in msg and "cordless_screwdriver" not in msg, msg


def test_extra_power_tool_members_are_strings_with_the_code_value() -> None:
    for value in POWER_TOOLS:
        member = ObjectType(value)
        assert member == value
        assert str(member) == value
        assert json.dumps({"t": member}) == json.dumps({"t": value})


@pytest.mark.parametrize(
    "value",
    [
        "Drill",
        "DRILL",
        "drill ",
        "angle-grinder",
        "circular_saw",
        "screwdriver",
        "furadeira",
        "lathe",
    ],
)
def test_extra_variants_of_power_tools_are_not_object_types(value: str) -> None:
    assert _accepted(ungraded(value)) is False


def test_extra_json_round_trip_of_power_tool_payloads() -> None:
    for value in POWER_TOOLS:
        data = ungraded(value)
        insp = InspectionCreate.model_validate_json(json.dumps(data))
        again = InspectionCreate.model_validate_json(insp.model_dump_json())
        assert again == insp
        dumped = again.model_dump(mode="json")
        assert dumped["object_type"] == value
        assert dumped["grade"] is None and dumped["grade_score"] is None


def test_extra_inspection_read_of_a_power_tool_is_not_defective() -> None:
    data = {**ungraded("saw"), "received_at": datetime.now(UTC).isoformat()}
    data["is_defective"] = False
    read = InspectionRead.model_validate(data)
    assert read.object_type == ObjectType.SAW
    assert read.grade is None
    assert read.is_defective is False
    assert is_defective(read.grade) is False


def test_extra_earlier_labels_did_not_change() -> None:
    expected = {
        "screw": "parafuso",
        "nut": "porca",
        "unknown": "desconhecido",
        "pliers": "alicate",
        "adjustable_wrench": "chave inglesa",
        "allen_key": "chave Allen",
        "flat_screwdriver": "chave de fenda",
        "phillips_screwdriver": "chave Phillips",
    }
    for value, label in expected.items():
        assert OBJECT_TYPE_LABELS_PT[ObjectType(value)] == label
    assert len(set(OBJECT_TYPE_LABELS_PT.values())) == 12  # one distinct label per type


def test_extra_grade_enum_and_defect_rule_unchanged() -> None:
    assert [g.value for g in Grade] == list(GRADE_SCORES)
    assert [is_defective(g) for g in Grade] == [False, False, False, True, True]
