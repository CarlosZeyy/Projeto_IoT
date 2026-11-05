"""Acceptance tests for SPEC-044 (qc-contracts: hammer, wrench and spirit level, never graded).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-01 and CA-02. Tests named ``test_extra_*`` are exploratory edge cases
around SPEC-044 sections 3.1 and 4.1 that no CA spells out.

Per ``docs/architecture.md`` section 10 ("Expectativas de versão"), this file is the current
SPEC of ``qc-contracts``: the exact version comparison lives only in ``test_ca01_*`` here
(SPEC-044 introduces 0.7.0).
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
NEW_TOOLS = ["hammer", "wrench", "spirit_level"]
NEW_LABELS = {"hammer": "martelo", "wrench": "chave de aperto", "spirit_level": "nível"}
SPEC021_TYPES = ["screw", "nut", "unknown", *HAND_TOOLS, *POWER_TOOLS]
ALL_TYPES = [*SPEC021_TYPES, *NEW_TOOLS]
GRADE_SCORES = {"perfect": 0.0, "good": 1.0, "fair": 2.0, "poor": 3.0, "unusable": 4.0}


def base_payload(**overrides: Any) -> dict[str, Any]:
    """A valid ``InspectionCreate`` (``screw``/``good``), JSON-like."""
    data: dict[str, Any] = {
        "inspection_id": str(uuid.uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-044",
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


def test_ca01_contracts_version_is_0_7_0() -> None:
    assert qc_contracts.__version__ == importlib.metadata.version("qc-contracts") == "0.7.0"


def test_ca01_object_type_has_15_members_ending_with_the_new_tools() -> None:
    values = [m.value for m in ObjectType]
    assert len(values) == 15
    assert values[-3:] == NEW_TOOLS
    # Placed right after cordless_screwdriver (section 3.1): the 12 earlier values come first.
    assert values == ALL_TYPES


def test_ca01_new_tool_labels_pt() -> None:
    for value, label in NEW_LABELS.items():
        assert OBJECT_TYPE_LABELS_PT[ObjectType(value)] == label, value
    assert set(OBJECT_TYPE_LABELS_PT) == set(ObjectType)


def test_ca01_grade_forbidden_group_is_exactly_the_eight_types() -> None:
    expected = {
        ObjectType("unknown"),
        ObjectType("angle_grinder"),
        ObjectType("saw"),
        ObjectType("drill"),
        ObjectType("cordless_screwdriver"),
        ObjectType("hammer"),
        ObjectType("wrench"),
        ObjectType("spirit_level"),
    }
    assert expected == GRADE_FORBIDDEN_OBJECT_TYPES


def test_ca01_three_groups_are_disjoint_and_sum_the_enum() -> None:
    groups = (
        GRADE_REQUIRED_OBJECT_TYPES,
        GRADE_FORBIDDEN_OBJECT_TYPES,
        GRADE_OPTIONAL_OBJECT_TYPES,
    )
    for a, b in itertools.combinations(groups, 2):
        assert a.isdisjoint(b), (a, b)
    union = GRADE_REQUIRED_OBJECT_TYPES | GRADE_FORBIDDEN_OBJECT_TYPES | GRADE_OPTIONAL_OBJECT_TYPES
    assert union == set(ObjectType)
    assert sum(len(g) for g in groups) == 15
    assert {m.value for m in GRADE_REQUIRED_OBJECT_TYPES} == {"screw", "nut"}
    assert {m.value for m in GRADE_OPTIONAL_OBJECT_TYPES} == set(HAND_TOOLS)


def test_ca01_pyproject_and_readme_history() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    assert match is not None
    assert match.group(1) == qc_contracts.__version__
    rows = README.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("| 0.7.0 |") and "SPEC-044" in line for line in rows)


# --------------------------------------------------------------------------- CA-02


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_ca02_new_tool_without_grade_is_accepted(tool: str) -> None:
    insp = InspectionCreate.model_validate(ungraded(tool))
    assert insp.object_type == ObjectType(tool)
    assert insp.grade is None
    assert insp.grade_score is None
    assert insp.grade_confidence is None


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_ca02_new_tool_with_grade_is_rejected(tool: str) -> None:
    data = base_payload(object_type=tool, grade="good", grade_score=1.0, grade_confidence=0.8)
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(data)


# --------------------------------------------------------------------------- extras


@pytest.mark.parametrize("tool", NEW_TOOLS)
@pytest.mark.parametrize(
    ("grade", "score", "conf"),
    [(None, 2.0, None), (None, None, 0.7), (None, 2.0, 0.7), ("fair", None, None)],
    ids=["score-only", "conf-only", "score-and-conf", "grade-only"],
)
def test_extra_any_grade_field_on_a_new_tool_is_rejected(
    tool: str, grade: str | None, score: float | None, conf: float | None
) -> None:
    data = base_payload(object_type=tool, grade=grade, grade_score=score, grade_confidence=conf)
    assert _accepted(data) is False


@pytest.mark.parametrize("object_type", ALL_TYPES)
@pytest.mark.parametrize("grade", [None, *GRADE_SCORES])
def test_extra_invariant_matrix_of_the_15_types(object_type: str, grade: str | None) -> None:
    """90 pairs: the 12 earlier types keep their rule, the three new tools never take a grade."""
    if object_type in ("screw", "nut"):
        expected = grade is not None
    elif object_type == "unknown" or object_type in POWER_TOOLS or object_type in NEW_TOOLS:
        expected = grade is None
    else:
        expected = True
    data = ungraded(object_type) if grade is None else graded(object_type, grade)
    assert _accepted(data) is expected


@pytest.mark.parametrize("tool", NEW_TOOLS)
@pytest.mark.parametrize("grade", [None, *GRADE_SCORES])
def test_extra_inspection_read_follows_the_same_rule(tool: str, grade: str | None) -> None:
    data = ungraded(tool) if grade is None else graded(tool, grade)
    read = {**data, "received_at": datetime.now(UTC).isoformat(), "is_defective": False}
    try:
        InspectionRead.model_validate(read)
        ok = True
    except ValidationError:
        ok = False
    assert ok is (grade is None)


def test_extra_new_tool_messages_carry_no_values() -> None:
    marker_lot = "L-MARK044"
    data = base_payload(
        object_type="spirit_level",
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
        assert "unusable" not in msg and "spirit_level" not in msg, msg


@pytest.mark.parametrize(
    "value",
    [
        "Hammer",
        "HAMMER",
        "hammer ",
        "spirit-level",
        "spiritlevel",
        "level",
        "martelo",
        "nível",
        "chave de aperto",
        "Wrench",
        "wrenches",
    ],
)
def test_extra_variants_of_new_tools_are_not_object_types(value: str) -> None:
    assert _accepted(ungraded(value)) is False


def test_extra_json_round_trip_and_members_are_strings() -> None:
    for value in NEW_TOOLS:
        member = ObjectType(value)
        assert member == value and str(member) == value
        assert json.dumps({"t": member}) == json.dumps({"t": value})
        insp = InspectionCreate.model_validate_json(json.dumps(ungraded(value)))
        again = InspectionCreate.model_validate_json(insp.model_dump_json())
        assert again == insp
        dumped = again.model_dump(mode="json")
        assert dumped["object_type"] == value
        assert dumped["grade"] is None and dumped["grade_score"] is None


def test_extra_earlier_labels_did_not_change_and_all_are_distinct() -> None:
    earlier = {
        "screw": "parafuso",
        "nut": "porca",
        "unknown": "desconhecido",
        "pliers": "alicate",
        "adjustable_wrench": "chave inglesa",
        "allen_key": "chave Allen",
        "flat_screwdriver": "chave de fenda",
        "phillips_screwdriver": "chave Phillips",
        "angle_grinder": "esmerilhadeira",
        "saw": "serra",
        "drill": "furadeira",
        "cordless_screwdriver": "parafusadeira",
    }
    for value, label in earlier.items():
        assert OBJECT_TYPE_LABELS_PT[ObjectType(value)] == label
    assert len(set(OBJECT_TYPE_LABELS_PT.values())) == 15


def test_extra_grade_enum_and_defect_rule_unchanged() -> None:
    assert [g.value for g in Grade] == list(GRADE_SCORES)
    assert [is_defective(g) for g in Grade] == [False, False, False, True, True]
    read = InspectionRead.model_validate(
        {**ungraded("wrench"), "received_at": datetime.now(UTC).isoformat(), "is_defective": False}
    )
    assert read.is_defective is False and is_defective(read.grade) is False
