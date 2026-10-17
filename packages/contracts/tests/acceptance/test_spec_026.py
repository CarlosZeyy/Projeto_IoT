"""Acceptance tests for SPEC-026 (qc-contracts 0.3.0: cut fields of ``SpcResponse``).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-01 and CA-02. Tests named ``test_extra_*`` are exploratory edge cases
around SPEC-026 section 4.1 that no CA spells out.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import qc_contracts
from qc_contracts import SpcResponse

pytestmark = pytest.mark.acceptance

PKG_ROOT = Path(__file__).resolve().parents[2]  # packages/contracts
README = PKG_ROOT / "README.md"
PYPROJECT = PKG_ROOT / "pyproject.toml"

FIELDS_0_2_0 = {
    "baseline_lots",
    "min_lot_size",
    "source",
    "p_bar",
    "points",
    "excluded_lots",
    "message",
}
CUT_FIELDS = ("max_points", "valid_lots_total", "excluded_lots_total")

# Example of docs/architecture.md section 3.4 without the 3 new fields, with UTC datetimes in
# place of "...": a 0.2.0 response.
JSON_0_2_0: dict[str, Any] = {
    "baseline_lots": 20,
    "min_lot_size": 5,
    "source": "live",
    "p_bar": 0.18,
    "points": [
        {
            "lot_id": "L-001",
            "started_at": "2026-10-01T08:00:00Z",
            "ended_at": "2026-10-01T08:30:00Z",
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
CUT_VALUES = {"max_points": 100, "valid_lots_total": 250, "excluded_lots_total": 7}


def _with(**overrides: Any) -> dict[str, Any]:
    return {**json.loads(json.dumps(JSON_0_2_0)), **overrides}


# --------------------------------------------------------------------------- CA-01


def test_ca01_contracts_version_is_0_3_0() -> None:
    assert qc_contracts.__version__ == "0.3.0"
    assert importlib.metadata.version("qc-contracts") == "0.3.0"
    assert qc_contracts.__version__ == importlib.metadata.version("qc-contracts")


def test_ca01_pyproject_matches() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    assert match is not None
    assert match.group(1) == qc_contracts.__version__


def test_ca01_readme_history_row() -> None:
    lines = README.read_text(encoding="utf-8").splitlines()
    rows = [line for line in lines if line.startswith("| 0.3.0 |")]
    assert len(rows) == 1, rows
    assert "SPEC-026" in rows[0], rows[0]


# --------------------------------------------------------------------------- CA-02


def test_ca02_json_0_2_0_is_valid_with_none_cut_fields() -> None:
    resp = SpcResponse.model_validate_json(json.dumps(JSON_0_2_0))
    assert resp.max_points is None
    assert resp.valid_lots_total is None
    assert resp.excluded_lots_total is None
    dumped = resp.model_dump(mode="json")
    assert dumped == {**JSON_0_2_0, **dict.fromkeys(CUT_FIELDS)}


def test_ca02_cut_values_round_trip() -> None:
    data = _with(**CUT_VALUES)
    resp = SpcResponse.model_validate_json(json.dumps(data))
    dumped = resp.model_dump(mode="json")
    assert dumped["max_points"] == 100
    assert dumped["valid_lots_total"] == 250
    assert dumped["excluded_lots_total"] == 7
    assert dumped == data
    # Also from a Python dict, not only from JSON text.
    assert SpcResponse.model_validate(data).model_dump(mode="json") == data


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_points", 0), ("valid_lots_total", -1), ("excluded_lots_total", -1)],
)
def test_ca02_invalid_cut_values_are_rejected(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        SpcResponse.model_validate_json(json.dumps(_with(**{**CUT_VALUES, field: value})))
    with pytest.raises(ValidationError):
        SpcResponse.model_validate(_with(**{field: value}))


def test_ca02_fields_are_0_2_0_plus_cut_fields() -> None:
    assert set(SpcResponse.model_fields) == FIELDS_0_2_0 | set(CUT_FIELDS)
    # §4.1: the 3 fields come after ``message`` and default to None.
    names = list(SpcResponse.model_fields)
    assert names[-3:] == list(CUT_FIELDS), names
    for name in CUT_FIELDS:
        assert SpcResponse.model_fields[name].is_required() is False
        assert SpcResponse.model_fields[name].default is None


# --------------------------------------------------------------------------- extras


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_points", 1), ("valid_lots_total", 0), ("excluded_lots_total", 0)],
)
def test_extra_cut_field_lower_bounds_accepted(field: str, value: int) -> None:
    resp = SpcResponse.model_validate(_with(**{field: value}))
    assert getattr(resp, field) == value


@pytest.mark.parametrize("value", ["abc", 1.5, [1], {"a": 1}])
@pytest.mark.parametrize("field", CUT_FIELDS)
def test_extra_cut_fields_reject_non_integers(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        SpcResponse.model_validate_json(json.dumps(_with(**{field: value})))


@pytest.mark.parametrize("field", CUT_FIELDS)
def test_extra_explicit_null_is_none(field: str) -> None:
    resp = SpcResponse.model_validate_json(json.dumps(_with(**{field: None})))
    assert getattr(resp, field) is None


def test_extra_0_2_0_reader_shape_ignores_unknown_fields() -> None:
    """A response with extra unknown keys (a future 0.4.0 field) is still read (extra=ignore)."""
    data = _with(**CUT_VALUES, future_field="x")
    resp = SpcResponse.model_validate_json(json.dumps(data))
    assert "future_field" not in resp.model_dump(mode="json")
    assert resp.max_points == 100


def test_extra_a_0_3_0_body_is_readable_with_only_0_2_0_keys() -> None:
    """Compatibility with 0.2.0 clients: dropping the 3 keys of a 0.3.0 body leaves a valid
    0.2.0 body with the same values (the new fields never change the old ones)."""
    full = SpcResponse.model_validate(_with(**CUT_VALUES)).model_dump(mode="json")
    old = {k: v for k, v in full.items() if k in FIELDS_0_2_0}
    assert old == JSON_0_2_0
    assert SpcResponse.model_validate(old).model_dump(mode="json") == {
        **JSON_0_2_0,
        **dict.fromkeys(CUT_FIELDS),
    }
