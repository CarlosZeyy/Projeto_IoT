"""POST /api/capture in inspect mode (SPEC-007 sections 4.5 to 4.7)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageFile

from qc_contracts import Grade, InspectionCreate, ObjectType
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import (
    InferenceError,
    InferenceResult,
    ModelInfo,
    StubInferencer,
)
from qc_edge.limits import CAPTURE_MAX_BYTES, CAPTURE_MAX_REQUEST_BYTES
from qc_edge.sink import InMemorySink, SinkError, SinkStats

FIXED_NOW = datetime(2026, 10, 1, 23, 59, 30, tzinfo=UTC)

CONTRACT_FIELDS = {
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


def _result(object_type: ObjectType, grade: Grade | None) -> InferenceResult:
    graded = grade is not None
    return InferenceResult(
        object_type=object_type,
        grade=grade,
        grade_score=2.5 if graded else None,
        type_confidence=0.7,
        grade_confidence=0.6 if graded else None,
        needs_review=not graded,
        latency_ms=42,
    )


class _FailingSink(InMemorySink):
    def put(self, inspection: InspectionCreate) -> None:
        raise SinkError("disk full")


class _CrashingSink(InMemorySink):
    def put(self, inspection: InspectionCreate) -> None:
        raise KeyError("bug")


class _FailingInferencer:
    model_info = ModelInfo("broken-v1", "a" * 64)

    def __init__(self) -> None:
        self.calls = 0

    def infer(self, image: Image.Image) -> InferenceResult:
        self.calls += 1
        raise InferenceError("onnx exploded")


class Harness:
    def __init__(
        self,
        settings: EdgeSettings,
        inferencer: Any = "stub",
        sink: InMemorySink | None = None,
        clock: Callable[[], datetime] = lambda: FIXED_NOW,
    ) -> None:
        self.stub = StubInferencer() if inferencer == "stub" else None
        self.inferencer = self.stub if inferencer == "stub" else inferencer
        self.sink = sink if sink is not None else InMemorySink()
        self.settings = settings
        self.app = create_app(settings, self.inferencer, self.sink, clock=clock)
        self.token: str = self.app.state.session_token
        self.client = TestClient(self.app)

    def post(
        self,
        image: bytes | None,
        lot_id: str | None = "L-001",
        mode: str | None = "inspect",
        token: str | None = "valid",
        filename: str = "photo.jpg",
    ) -> Any:
        headers = {}
        if token == "valid":
            headers["X-Session-Token"] = self.token
        elif token is not None:
            headers["X-Session-Token"] = token
        data = {key: value for key, value in (("lot_id", lot_id), ("mode", mode)) if value}
        files = {"image": (filename, image, "image/jpeg")} if image is not None else None
        if files is None:
            # Force multipart even without a file part.
            files = {"other": ("x.txt", b"x", "text/plain")}
        return self.client.post("/api/capture", headers=headers, data=data, files=files)

    def captures(self) -> list[Path]:
        root = self.settings.EDGE_DATA_DIR / "captures"
        return sorted(path for path in root.rglob("*") if path.is_file())


@pytest.fixture
def harness(settings: EdgeSettings) -> Iterator[Harness]:
    yield Harness(settings)


def test_success(harness: Harness, jpeg_bytes: bytes) -> None:
    response = harness.post(jpeg_bytes)
    assert response.status_code == 200
    body = response.json()
    inspection = body["inspection"]
    assert set(inspection) == CONTRACT_FIELDS
    assert inspection["source"] == "live"
    assert inspection["device_id"] == "edge-01"
    assert inspection["lot_id"] == "L-001"
    assert uuid.UUID(inspection["inspection_id"]).version == 4
    assert datetime.fromisoformat(inspection["inspected_at"]) == FIXED_NOW
    assert inspection["model_version"] == "stub-v0"
    assert body["approved"] is True
    assert body["labels_pt"] == {"object_type": "parafuso", "grade": "bom", "verdict": "aprovada"}
    path = harness.settings.EDGE_DATA_DIR / "captures" / "2026-10-01"
    assert harness.captures() == [path / f"{inspection['inspection_id']}.jpg"]
    assert harness.captures()[0].read_bytes() == jpeg_bytes  # JPEG kept as received
    assert [item.model_dump(mode="json") for item in harness.sink.items] == [inspection]


def test_png_is_saved_as_jpeg(harness: Harness, make_image: Callable[..., bytes]) -> None:
    response = harness.post(make_image((40, 30), fmt="PNG"), filename="x.png")
    assert response.status_code == 200
    (saved,) = harness.captures()
    assert saved.suffix == ".jpg"
    with Image.open(saved) as image:
        assert image.format == "JPEG"
        assert image.size == (40, 30)


@pytest.mark.parametrize(
    ("object_type", "grade", "approved", "labels"),
    [
        (ObjectType.NUT, Grade.POOR, False, ("porca", "ruim", "reprovada")),
        (ObjectType.SCREW, Grade.UNUSABLE, False, ("parafuso", "inutilizável", "reprovada")),
        (ObjectType.NUT, Grade.FAIR, True, ("porca", "mediano", "aprovada")),
        (ObjectType.UNKNOWN, None, None, ("desconhecido", None, "desconhecido")),
    ],
)
def test_verdicts(
    settings: EdgeSettings,
    jpeg_bytes: bytes,
    object_type: ObjectType,
    grade: Grade | None,
    approved: bool | None,
    labels: tuple[str, str | None, str],
) -> None:
    harness = Harness(settings, inferencer=StubInferencer(_result(object_type, grade)))
    body = harness.post(jpeg_bytes).json()
    assert body["approved"] is approved
    assert body["labels_pt"] == dict(zip(("object_type", "grade", "verdict"), labels, strict=True))
    assert body["inspection"]["grade"] == (grade.value if grade else None)
    assert body["inspection"]["latency_ms"] == 42


@pytest.mark.parametrize("token", [None, "wrong", "", "x" * 600])
def test_invalid_token_is_401(harness: Harness, jpeg_bytes: bytes, token: str | None) -> None:
    response = harness.post(jpeg_bytes, token=token)
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid session token"}
    assert harness.stub is not None and harness.stub.calls == 0
    assert harness.captures() == []


def test_token_is_checked_before_size_and_fields(harness: Harness) -> None:
    response = harness.post(b"\x00" * (CAPTURE_MAX_BYTES + 1), lot_id="bad lot", token=None)
    assert response.status_code == 401


def test_image_above_the_limit_is_413(harness: Harness) -> None:
    response = harness.post(b"\x00" * (CAPTURE_MAX_BYTES + 1), lot_id="bad lot")
    assert response.status_code == 413  # size before fields
    assert harness.stub is not None and harness.stub.calls == 0
    assert harness.captures() == []


def test_image_exactly_at_the_limit_is_accepted(harness: Harness, jpeg_bytes: bytes) -> None:
    padded = jpeg_bytes + b"\x00" * (CAPTURE_MAX_BYTES - len(jpeg_bytes))
    assert len(padded) == CAPTURE_MAX_BYTES
    assert harness.post(padded).status_code == 200


def test_declared_content_length_above_the_limit_is_413(harness: Harness) -> None:
    response = harness.client.post(
        "/api/capture",
        headers={
            "X-Session-Token": harness.token,
            "Content-Length": str(CAPTURE_MAX_REQUEST_BYTES + 1),
            "Content-Type": "multipart/form-data; boundary=x",
        },
        content=b"--x--\r\n",
    )
    assert response.status_code == 413
    assert harness.stub is not None and harness.stub.calls == 0


def test_chunked_body_above_the_limit_is_413(harness: Harness) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'--x\r\nContent-Disposition: form-data; name="image"; filename="a.jpg"\r\n\r\n'
        for _ in range(8):
            yield b"\x00" * 500_000

    response = harness.client.post(
        "/api/capture",
        headers={
            "X-Session-Token": harness.token,
            "Content-Type": "multipart/form-data; boundary=x",
        },
        content=chunks(),
    )
    assert response.status_code == 413
    assert harness.stub is not None and harness.stub.calls == 0


@pytest.mark.parametrize(
    ("lot_id", "mode"),
    [
        ("lote 1", "inspect"),
        ("../x", "inspect"),
        ("L-001\n", "inspect"),
        ("L" * 41, "inspect"),
        (None, "inspect"),
        ("L-001", "foo"),
        ("L-001", "inspect\n"),
        ("L-001", None),
    ],
)
def test_invalid_fields_are_422(
    harness: Harness, jpeg_bytes: bytes, lot_id: str | None, mode: str | None
) -> None:
    response = harness.post(jpeg_bytes, lot_id=lot_id, mode=mode)
    assert response.status_code == 422
    assert "detail" in response.json()
    assert harness.captures() == []


def test_lot_id_of_40_chars_is_accepted(harness: Harness, jpeg_bytes: bytes) -> None:
    assert harness.post(jpeg_bytes, lot_id="L" * 40).status_code == 200


def test_missing_image_is_422(harness: Harness) -> None:
    assert harness.post(None).status_code == 422


def test_image_sent_as_text_field_is_422(harness: Harness) -> None:
    response = harness.client.post(
        "/api/capture",
        headers={"X-Session-Token": harness.token},
        data={"image": "not a file", "lot_id": "L-001", "mode": "inspect"},
    )
    assert response.status_code == 422


def test_collect_mode_is_501(harness: Harness, jpeg_bytes: bytes) -> None:
    response = harness.post(jpeg_bytes, mode="collect")
    assert response.status_code == 501
    assert harness.captures() == []


@pytest.mark.parametrize(
    "kind", ["text", "gif", "truncated", "png-100x1001", "too-many-scans", "2001x2000"]
)
def test_invalid_images_are_415(
    harness: Harness, make_image: Callable[..., bytes], kind: str
) -> None:
    jpeg = make_image((64, 48))
    payload = {
        "text": b"hello, I am not a photo",
        "gif": make_image((8, 8), fmt="GIF"),
        "truncated": jpeg[:-100],
        "png-100x1001": make_image((100, 1001), fmt="PNG"),
        "too-many-scans": jpeg[:2]
        + b"\xff\xfe"
        + (128 + 2).to_bytes(2, "big")
        + b"\xff\xda" * 64
        + jpeg[2:],
        "2001x2000": make_image((2001, 2000)),
    }[kind]
    response = harness.post(payload)
    assert response.status_code == 415
    assert isinstance(response.json()["detail"], str)
    assert harness.stub is not None and harness.stub.calls == 0
    assert harness.captures() == []
    assert harness.sink.items == []


def test_2000x2000_is_accepted(harness: Harness, make_image: Callable[..., bytes]) -> None:
    assert harness.post(make_image((2000, 2000))).status_code == 200


def test_no_model_is_503_after_image_validation(settings: EdgeSettings, jpeg_bytes: bytes) -> None:
    harness = Harness(settings, inferencer=None)
    response = harness.post(jpeg_bytes)
    assert response.status_code == 503
    assert response.json() == {"detail": "model not loaded"}
    assert harness.post(b"text").status_code == 415  # image (415) before model (503)
    assert harness.captures() == []


def test_inference_error_is_500_without_side_effects(
    settings: EdgeSettings, jpeg_bytes: bytes
) -> None:
    inferencer = _FailingInferencer()
    harness = Harness(settings, inferencer=inferencer)
    response = harness.post(jpeg_bytes)
    assert response.status_code == 500
    assert response.json() == {"detail": "inference failed"}
    assert "Traceback" not in response.text
    assert harness.captures() == []
    assert harness.sink.items == []


def test_sink_error_is_503_and_the_photo_is_removed(
    settings: EdgeSettings, jpeg_bytes: bytes
) -> None:
    harness = Harness(settings, sink=_FailingSink())
    response = harness.post(jpeg_bytes)
    assert response.status_code == 503
    assert response.json() == {"detail": "failed to persist inspection"}
    root = settings.EDGE_DATA_DIR / "captures"
    assert list(root.rglob("*")) == []  # neither the photo nor its empty day directory


def test_unexpected_sink_failure_is_generic_500_and_the_photo_is_removed(
    settings: EdgeSettings, jpeg_bytes: bytes
) -> None:
    harness = Harness(settings, sink=_CrashingSink())
    response = harness.post(jpeg_bytes)
    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert harness.captures() == []


def test_invalid_inference_result_leaves_no_file(settings: EdgeSettings, jpeg_bytes: bytes) -> None:
    bad = InferenceResult(ObjectType.UNKNOWN, Grade.GOOD, 1.0, 0.5, 0.5, False, 3)
    harness = Harness(settings, inferencer=StubInferencer(bad))
    response = harness.post(jpeg_bytes)
    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert harness.captures() == []
    assert harness.sink.items == []


def test_flag_enabled_after_startup_is_500_not_415(
    harness: Harness, jpeg_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    response = harness.post(jpeg_bytes)
    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert harness.stub is not None and harness.stub.calls == 0


def test_client_filename_is_ignored(
    harness: Harness, jpeg_bytes: bytes, files_under: Callable[[], list[Path]]
) -> None:
    before = set(files_under())
    response = harness.post(jpeg_bytes, filename="../../evil.jpg")
    assert response.status_code == 200
    new = set(files_under()) - before
    inspection_id = response.json()["inspection"]["inspection_id"]
    expected = harness.settings.EDGE_DATA_DIR / "captures" / "2026-10-01" / f"{inspection_id}.jpg"
    assert new == {expected}


def test_day_directory_uses_the_utc_date(settings: EdgeSettings, jpeg_bytes: bytes) -> None:
    from datetime import timedelta, timezone

    local = datetime(2026, 10, 1, 22, 30, tzinfo=timezone(timedelta(hours=-3)))  # 01:30 UTC
    harness = Harness(settings, clock=lambda: local)
    body = harness.post(jpeg_bytes).json()
    assert body["inspection"]["inspected_at"].startswith("2026-10-02T01:30:00")
    assert harness.captures()[0].parent.name == "2026-10-02"


def test_sink_put_happens_before_the_response(settings: EdgeSettings, jpeg_bytes: bytes) -> None:
    seen: list[bool] = []

    class _CheckingSink(InMemorySink):
        def put(self, inspection: InspectionCreate) -> None:
            # The photo already exists when the inspection is handed to the sink.
            root = settings.EDGE_DATA_DIR / "captures"
            seen.append(any(root.rglob(f"{inspection.inspection_id}.jpg")))
            super().put(inspection)

        def stats(self) -> SinkStats:
            return super().stats()

    harness = Harness(settings, sink=_CheckingSink())
    assert harness.post(jpeg_bytes).status_code == 200
    assert seen == [True]
    assert len(harness.sink.items) == 1
