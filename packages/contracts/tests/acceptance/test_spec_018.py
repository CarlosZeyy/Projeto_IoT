"""Acceptance tests for SPEC-018 (qc-contracts 0.5.0: ``HeartbeatCreate`` and ``DeviceStatus``).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-01. Tests named ``test_extra_*`` are exploratory edge cases around
SPEC-018 section 4.1 that no CA spells out.

Per ``docs/architecture.md`` section 10 ("Expectativas de versão"), this file is the current
SPEC of ``qc-contracts``: the exact version comparison lives only in ``test_ca01_*`` here.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import qc_contracts
from qc_contracts import (
    APP_VERSION_PATTERN,
    MAX_FUTURE_SKEW,
    MAX_HEARTBEAT_COUNT,
    DeviceStatus,
    HeartbeatCreate,
    InspectionCreate,
    Source,
)

pytestmark = pytest.mark.acceptance

PKG_ROOT = Path(__file__).resolve().parents[2]  # packages/contracts
README = PKG_ROOT / "README.md"
PYPROJECT = PKG_ROOT / "pyproject.toml"

SHA = "c" * 64
COUNTERS = ("uptime_s", "outbox_pending", "outbox_dead")
HEARTBEAT_FIELDS = {
    "sent_at",
    "model_version",
    "model_sha256",
    "app_version",
    "uptime_s",
    "outbox_pending",
    "outbox_dead",
}
DEVICE_STATUS_FIELDS = {
    "device_id",
    "last_seen_at",
    "last_heartbeat_at",
    "online",
    "model_version",
    "model_sha256",
    "app_version",
    "uptime_s",
    "outbox_pending",
    "outbox_dead",
    "last_source",
}
# docs/architecture.md section 3.2 (unchanged by SPEC-018).
INSPECTION_FIELDS = {
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


def heartbeat(**overrides: Any) -> dict[str, Any]:
    """A valid ``HeartbeatCreate`` body, JSON-like."""
    data: dict[str, Any] = {
        "sent_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "app_version": "0.0.0",
        "uptime_s": 120,
        "outbox_pending": 3,
        "outbox_dead": 1,
    }
    data.update(overrides)
    return data


def refused(data: dict[str, Any]) -> bool:
    try:
        HeartbeatCreate.model_validate(data)
    except ValidationError:
        return True
    return False


def status(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "device_id": "edge-01",
        "last_seen_at": "2026-11-02T10:00:00+00:00",
        "last_heartbeat_at": "2026-11-02T10:00:00+00:00",
        "online": True,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "app_version": "0.0.0",
        "uptime_s": 7500,
        "outbox_pending": 2,
        "outbox_dead": 1,
        "last_source": "live",
    }
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- CA-01


def test_ca01_contracts_version_is_0_5_0() -> None:
    assert qc_contracts.__version__ == importlib.metadata.version("qc-contracts") == "0.5.0"


def test_ca01_valid_heartbeat_round_trip() -> None:
    hb = HeartbeatCreate.model_validate(heartbeat())
    again = HeartbeatCreate.model_validate_json(hb.model_dump_json())
    assert again == hb
    assert set(json.loads(hb.model_dump_json())) == HEARTBEAT_FIELDS
    assert again.outbox_pending == 3


def test_ca01_valid_heartbeat_without_model_round_trip() -> None:
    hb = HeartbeatCreate.model_validate(heartbeat(model_version=None, model_sha256=None))
    again = HeartbeatCreate.model_validate_json(hb.model_dump_json())
    assert again == hb
    assert again.model_version is None and again.model_sha256 is None


def test_ca01_extra_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        HeartbeatCreate.model_validate(heartbeat(image="AAAA"))


def test_ca01_negative_uptime_is_refused() -> None:
    with pytest.raises(ValidationError):
        HeartbeatCreate.model_validate(heartbeat(uptime_s=-1))


def test_ca01_outbox_pending_above_max_is_refused() -> None:
    with pytest.raises(ValidationError):
        HeartbeatCreate.model_validate(heartbeat(outbox_pending=2_147_483_648))


def test_ca01_app_version_with_trailing_newline_is_refused() -> None:
    with pytest.raises(ValidationError):
        HeartbeatCreate.model_validate(heartbeat(app_version="1.0\n"))


def test_ca01_sent_at_without_timezone_is_refused() -> None:
    naive = (datetime.now(UTC) - timedelta(seconds=5)).replace(tzinfo=None).isoformat()
    with pytest.raises(ValidationError):
        HeartbeatCreate.model_validate(heartbeat(sent_at=naive))


def test_ca01_sent_at_six_minutes_in_the_future_is_refused() -> None:
    future = (datetime.now(UTC) + timedelta(minutes=6)).isoformat()
    with pytest.raises(ValidationError):
        HeartbeatCreate.model_validate(heartbeat(sent_at=future))


def test_ca01_model_version_without_sha_is_refused() -> None:
    with pytest.raises(ValidationError):
        HeartbeatCreate.model_validate(heartbeat(model_sha256=None))


def test_ca01_pyproject_and_readme_history() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    assert match is not None
    assert match.group(1) == qc_contracts.__version__
    rows = [line for line in README.read_text(encoding="utf-8").splitlines()]
    assert any(line.startswith("| 0.5.0 |") and "SPEC-018" in line for line in rows)


# --------------------------------------------------------------------------- extras: §4.1


def test_extra_public_constants() -> None:
    assert MAX_HEARTBEAT_COUNT == 2_147_483_647
    assert APP_VERSION_PATTERN == r"^[0-9A-Za-z.+-]{1,40}$"
    for name in (
        "HeartbeatCreate",
        "DeviceStatus",
        "MAX_HEARTBEAT_COUNT",
        "APP_VERSION_PATTERN",
    ):
        assert name in qc_contracts.__all__, name


def test_extra_sha_without_model_version_is_refused() -> None:
    assert refused(heartbeat(model_version=None))
    assert refused(heartbeat(model_version=None, model_sha256=SHA))


@pytest.mark.parametrize("field", COUNTERS)
def test_extra_counter_limits(field: str) -> None:
    assert not refused(heartbeat(**{field: 0}))
    assert not refused(heartbeat(**{field: MAX_HEARTBEAT_COUNT}))
    assert refused(heartbeat(**{field: -1}))
    assert refused(heartbeat(**{field: MAX_HEARTBEAT_COUNT + 1}))
    assert refused(heartbeat(**{field: 1.5}))
    assert refused(heartbeat(**{field: None}))


@pytest.mark.parametrize("field", sorted(HEARTBEAT_FIELDS))
def test_extra_every_field_is_required(field: str) -> None:
    """The SPEC writes no default for any field: omitting one is refused."""
    data = heartbeat()
    del data[field]
    assert refused(data)


@pytest.mark.parametrize(
    "value",
    ["0.0.0", "1", "1.0.0+build-7", "v2.3-rc.1", "A" * 40, "0.5.0+g1a2b3c"],
)
def test_extra_app_version_accepted(value: str) -> None:
    assert HeartbeatCreate.model_validate(heartbeat(app_version=value)).app_version == value


@pytest.mark.parametrize(
    "value",
    ["", "A" * 41, "1.0 beta", "1.0_0", "1.0/2", "versão", "1.0\t", "\n1.0", "1.0\x00", "１.0"],
)
def test_extra_app_version_refused(value: str) -> None:
    assert refused(heartbeat(app_version=value))
    assert re.fullmatch(APP_VERSION_PATTERN, value) is None


def test_extra_app_version_pattern_needs_fullmatch() -> None:
    """architecture.md §3.2: ``re.match`` would let a trailing newline through."""
    assert re.match(APP_VERSION_PATTERN, "1.0\n") is not None
    assert re.fullmatch(APP_VERSION_PATTERN, "1.0\n") is None


@pytest.mark.parametrize(
    ("version", "sha"),
    [
        ("PartQC-v1", SHA),  # uppercase is outside MODEL_VERSION_PATTERN
        ("ab", SHA),
        ("partqc-mnv3-v1", "C" * 64),
        ("partqc-mnv3-v1", "c" * 63),
        ("partqc-mnv3-v1", "g" * 64),
        ("partqc-mnv3-v1\n", SHA),
    ],
)
def test_extra_model_fields_follow_the_contract_patterns(version: str, sha: str) -> None:
    assert refused(heartbeat(model_version=version, model_sha256=sha))


def test_extra_sent_at_is_normalized_to_utc() -> None:
    local = datetime.now(timezone(timedelta(hours=-3))) - timedelta(seconds=10)
    hb = HeartbeatCreate.model_validate(heartbeat(sent_at=local.isoformat()))
    assert hb.sent_at.utcoffset() == timedelta(0)
    assert hb.sent_at == local


def test_extra_sent_at_future_skew_boundary_and_past() -> None:
    assert timedelta(minutes=5) == MAX_FUTURE_SKEW
    near = datetime.now(UTC) + timedelta(minutes=4)
    assert not refused(heartbeat(sent_at=near.isoformat()))
    old = datetime(2020, 1, 1, tzinfo=UTC)
    assert not refused(heartbeat(sent_at=old.isoformat()))


def test_extra_lax_bool_counter_is_accepted() -> None:
    """SPEC §7: the lax mode accepts ``True`` as ``1`` (no CA; documented behaviour)."""
    assert HeartbeatCreate.model_validate(heartbeat(outbox_dead=True)).outbox_dead == 1


def test_extra_heartbeat_has_no_image_or_device_field() -> None:
    """R-02: the body carries only health data; the device comes from the path."""
    assert set(HeartbeatCreate.model_fields) == HEARTBEAT_FIELDS


def test_extra_device_status_fields_and_round_trip() -> None:
    assert set(DeviceStatus.model_fields) == DEVICE_STATUS_FIELDS
    item = DeviceStatus.model_validate(status())
    again = DeviceStatus.model_validate_json(item.model_dump_json())
    assert again == item
    assert item.last_source == Source.LIVE
    assert item.last_heartbeat_at is not None
    assert item.last_heartbeat_at.utcoffset() == timedelta(0)


def test_extra_device_status_ignores_unknown_keys() -> None:
    item = DeviceStatus.model_validate(status(future_field="x"))
    assert not hasattr(item, "future_field")


def test_extra_device_status_without_heartbeat_or_inspection() -> None:
    nulls = dict.fromkeys(DEVICE_STATUS_FIELDS - {"device_id", "online"})
    item = DeviceStatus.model_validate(status(online=False, **nulls))
    assert item.online is False
    assert item.last_heartbeat_at is None and item.last_source is None


def test_extra_device_status_refuses_unknown_source() -> None:
    with pytest.raises(ValidationError):
        DeviceStatus.model_validate(status(last_source="fake"))


def test_extra_inspection_create_did_not_change() -> None:
    """§4.1: no existing schema changes."""
    assert set(InspectionCreate.model_fields) == INSPECTION_FIELDS
    assert InspectionCreate.model_config.get("extra") == "forbid"
    assert HeartbeatCreate.model_config.get("extra") == "forbid"
