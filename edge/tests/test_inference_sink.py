"""StubInferencer and InMemorySink (SPEC-007 section 4.2)."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

import pytest
from PIL import Image

from qc_contracts import Grade, InspectionCreate, ObjectType, Source
from qc_edge.inference import (
    DEFAULT_STUB_RESULT,
    InferenceResult,
    ModelInfo,
    StubInferencer,
)
from qc_edge.sink import InMemorySink, SinkStats


def _inspection(inspection_id: uuid.UUID | None = None) -> InspectionCreate:
    return InspectionCreate(
        inspection_id=inspection_id or uuid.uuid4(),
        device_id="edge-01",
        lot_id="L-001",
        inspected_at=datetime.now(UTC),
        object_type=ObjectType.SCREW,
        grade=Grade.GOOD,
        grade_score=1.0,
        type_confidence=0.9,
        grade_confidence=0.8,
        needs_review=False,
        model_version="stub-v0",
        model_sha256="0" * 64,
        latency_ms=1,
        source=Source.LIVE,
    )


def test_stub_defaults_and_call_count() -> None:
    stub = StubInferencer()
    assert stub.model_info == ModelInfo("stub-v0", "0" * 64)
    assert stub.calls == 0
    image = Image.new("RGB", (4, 4))
    assert stub.infer(image) == DEFAULT_STUB_RESULT
    assert stub.infer(image) == DEFAULT_STUB_RESULT
    assert stub.calls == 2


def test_stub_returns_the_configured_result() -> None:
    result = InferenceResult(
        object_type=ObjectType.UNKNOWN,
        grade=None,
        grade_score=None,
        type_confidence=0.3,
        grade_confidence=None,
        needs_review=True,
        latency_ms=12,
    )
    assert StubInferencer(result).infer(Image.new("RGB", (4, 4))) is result


def test_dataclasses_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_STUB_RESULT.latency_ms = 5  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        ModelInfo("a", "b").model_version = "c"  # type: ignore[misc]


def test_in_memory_sink_is_idempotent_and_reports_disabled() -> None:
    sink = InMemorySink()
    assert sink.stats() == SinkStats(
        pending=0, dead=0, last_success_at=None, connectivity="disabled"
    )
    first = _inspection()
    sink.put(first)
    sink.put(first)
    sink.put(_inspection(first.inspection_id))
    second = _inspection()
    sink.put(second)
    assert sink.items == [first, second]
    assert sink.stats().pending == 2


def test_in_memory_sink_items_is_a_copy() -> None:
    sink = InMemorySink()
    sink.put(_inspection())
    sink.items.clear()
    assert len(sink.items) == 1
