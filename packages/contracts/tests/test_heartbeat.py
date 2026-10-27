"""``HeartbeatCreate`` and ``DeviceStatus`` (contract 0.5.0, SPEC-018 section 4.1)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

import qc_contracts
from qc_contracts import (
    APP_VERSION_PATTERN,
    MAX_HEARTBEAT_COUNT,
    MAX_LATENCY_MS,
    DeviceStatus,
    HeartbeatCreate,
    Source,
)

SHA = "b" * 64
BRT = timezone(timedelta(hours=-3))


def heartbeat(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "sent_at": (datetime.now(BRT) - timedelta(seconds=5)).isoformat(),
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "app_version": "0.0.0",
        "uptime_s": 120,
        "outbox_pending": 3,
        "outbox_dead": 1,
    }
    body.update(overrides)
    return body


def device_status(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "device_id": "edge-01",
        "last_seen_at": "2026-10-24T12:00:00+00:00",
        "last_heartbeat_at": "2026-10-24T12:00:00+00:00",
        "online": True,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "app_version": "0.0.0",
        "uptime_s": 7500,
        "outbox_pending": 2,
        "outbox_dead": 0,
        "last_source": "live",
    }
    body.update(overrides)
    return body


# ---------- HeartbeatCreate ----------


def test_valid_heartbeat_round_trip_and_utc() -> None:
    item = HeartbeatCreate.model_validate(heartbeat())
    assert item.sent_at.tzinfo is UTC
    assert HeartbeatCreate.model_validate_json(item.model_dump_json()) == item


def test_heartbeat_without_model() -> None:
    item = HeartbeatCreate.model_validate(heartbeat(model_version=None, model_sha256=None))
    assert item.model_version is None and item.model_sha256 is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_version": "partqc-mnv3-v1", "model_sha256": None},
        {"model_version": None, "model_sha256": SHA},
    ],
)
def test_model_fields_null_together(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="null if and only if"):
        HeartbeatCreate.model_validate(heartbeat(**overrides))


def test_extra_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        HeartbeatCreate.model_validate(heartbeat(image="AAAA"))


@pytest.mark.parametrize("field", ["uptime_s", "outbox_pending", "outbox_dead"])
@pytest.mark.parametrize("value", [-1, MAX_HEARTBEAT_COUNT + 1, 1.5, "abc", None])
def test_counters_out_of_range(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        HeartbeatCreate.model_validate(heartbeat(**{field: value}))


@pytest.mark.parametrize("field", ["uptime_s", "outbox_pending", "outbox_dead"])
@pytest.mark.parametrize("value", [0, MAX_HEARTBEAT_COUNT])
def test_counters_at_the_limits(field: str, value: int) -> None:
    assert getattr(HeartbeatCreate.model_validate(heartbeat(**{field: value})), field) == value


def test_max_heartbeat_count_is_the_integer_column_limit() -> None:
    assert MAX_HEARTBEAT_COUNT == 2**31 - 1 == MAX_LATENCY_MS


@pytest.mark.parametrize("value", ["0.0.0", "1.2.3+local", "v2-rc.1", "A" * 40, "1"])
def test_app_version_accepted(value: str) -> None:
    assert HeartbeatCreate.model_validate(heartbeat(app_version=value)).app_version == value


@pytest.mark.parametrize("value", ["", "1.0\n", "1.0 beta", "A" * 41, "1/0", "1_0", "versão"])
def test_app_version_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        HeartbeatCreate.model_validate(heartbeat(app_version=value))


def test_app_version_pattern_with_fullmatch() -> None:
    assert re.fullmatch(APP_VERSION_PATTERN, "1.0")
    assert re.fullmatch(APP_VERSION_PATTERN, "1.0\n") is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_version": "Partqc-v1", "model_sha256": SHA},
        {"model_version": "partqc-mnv3-v1", "model_sha256": "B" * 64},
        {"model_version": "partqc-mnv3-v1", "model_sha256": "b" * 63},
    ],
)
def test_model_fields_follow_the_contract_patterns(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        HeartbeatCreate.model_validate(heartbeat(**overrides))


def test_sent_at_without_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError):
        HeartbeatCreate.model_validate(heartbeat(sent_at="2026-10-24T12:00:00"))


def test_sent_at_more_than_five_minutes_in_the_future_is_rejected() -> None:
    future = datetime.now(UTC) + timedelta(minutes=6)
    with pytest.raises(ValidationError, match="5 minutes in the future"):
        HeartbeatCreate.model_validate(heartbeat(sent_at=future.isoformat()))


def test_sent_at_slightly_in_the_future_is_accepted() -> None:
    near = datetime.now(UTC) + timedelta(minutes=4)
    assert HeartbeatCreate.model_validate(heartbeat(sent_at=near.isoformat())).sent_at == near


def test_sent_at_out_of_range_after_utc_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        HeartbeatCreate.model_validate(heartbeat(sent_at="0001-01-01T00:00:00+05:00"))


def test_required_fields() -> None:
    for field in heartbeat():
        body = heartbeat()
        del body[field]
        with pytest.raises(ValidationError):
            HeartbeatCreate.model_validate(body)


# ---------- DeviceStatus ----------


def test_device_status_parses_and_ignores_extra_fields() -> None:
    item = DeviceStatus.model_validate(device_status(new_field_of_a_later_minor=1))
    assert item.last_source is Source.LIVE
    assert item.last_heartbeat_at is not None and item.last_heartbeat_at.tzinfo is UTC
    assert DeviceStatus.model_validate_json(item.model_dump_json()) == item


def test_device_status_without_heartbeat_or_inspection() -> None:
    item = DeviceStatus.model_validate(
        device_status(
            last_seen_at=None,
            last_heartbeat_at=None,
            online=False,
            model_version=None,
            model_sha256=None,
            app_version=None,
            uptime_s=None,
            outbox_pending=None,
            outbox_dead=None,
            last_source=None,
        )
    )
    assert item.online is False
    assert item.last_source is None


def test_device_status_rejects_unknown_source() -> None:
    with pytest.raises(ValidationError):
        DeviceStatus.model_validate(device_status(last_source="fake"))


def test_new_names_are_exported() -> None:
    for name in (
        "APP_VERSION_PATTERN",
        "MAX_HEARTBEAT_COUNT",
        "HeartbeatCreate",
        "DeviceStatus",
    ):
        assert name in qc_contracts.__all__
