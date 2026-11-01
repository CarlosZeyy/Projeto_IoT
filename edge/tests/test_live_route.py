"""Route, page and console of the live mode (SPEC-019 sections 4.3 to 4.5)."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import sqlite3
import stat
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from qc_contracts import Grade, InspectionCreate, ObjectType
from qc_edge import app as app_module
from qc_edge import cli, netinfo
from qc_edge.app import STATIC_DIR, TEMPLATES_DIR, create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import InferenceError, InferenceResult, ModelInfo
from qc_edge.limits import LIVE_MAX_BYTES, LIVE_MAX_REQUEST_BYTES
from qc_edge.middleware import BodySizeLimitMiddleware
from qc_edge.outbox import SqliteOutbox
from qc_edge.sink import InMemorySink, SinkError

LOCAL = ("127.0.0.1", 50000)
CONSOLE_URL = "http://127.0.0.1:8000"
OFFICIAL = "partqc-mnv3-v1"
PROVISIONAL = "partqc-mnv3-provisional-v1"
SUFFIX = " (modelo provisório)"
SESSION = "session-aaaaaaaaaaaa"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _result(
    object_type: ObjectType = ObjectType.SCREW,
    grade: Grade | None = Grade.FAIR,
    confidence: float = 0.9,
    latency_ms: int = 7,
) -> InferenceResult:
    graded = grade is not None
    return InferenceResult(
        object_type=object_type,
        grade=grade,
        grade_score=2.0 if graded else None,
        type_confidence=confidence,
        grade_confidence=0.8 if graded else None,
        needs_review=False,
        latency_ms=latency_ms,
    )


FAIR = _result()
POOR = _result(grade=Grade.POOR)
UNKNOWN = _result(ObjectType.UNKNOWN, None)


class _Scripted:
    """Returns the scripted results in order, then the last one; an exception is raised."""

    def __init__(self, *script: InferenceResult | Exception, version: str = OFFICIAL) -> None:
        self.model_info = ModelInfo(version, "a" * 64)
        self.script = list(script) or [FAIR]
        self.calls = 0

    def infer(self, image: Image.Image) -> InferenceResult:
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


class _Sink(InMemorySink):
    """``InMemorySink`` whose first ``put`` calls raise ``failures``, in order."""

    def __init__(self, *failures: Exception) -> None:
        super().__init__()
        self.failures = list(failures)

    def put(self, inspection: InspectionCreate) -> None:
        if self.failures:
            raise self.failures.pop(0)
        super().put(inspection)


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def at(self, seconds: float) -> None:
        self.now = T0 + timedelta(seconds=seconds)


def _jpeg(index: int = 0, size: tuple[int, int] = (32, 24)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (index % 256, 80, 120)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _encoded(fmt: str, size: tuple[int, int] = (16, 16)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, format=fmt)
    return buffer.getvalue()


class _Rig:
    def __init__(self, settings: EdgeSettings, inferencer: Any, sink: Any, **kwargs: Any) -> None:
        self.settings = settings
        self.inferencer = inferencer
        self.sink = sink
        self.app = create_app(settings, inferencer, sink, **kwargs)
        self.token = self.app.state.session_token
        self.client = TestClient(self.app, client=LOCAL, base_url=CONSOLE_URL)

    def frame(
        self,
        image: bytes | None = None,
        lot_id: str = "L-001",
        session: str = SESSION,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return self.client.post(
            "/api/live/frame",
            headers={"X-Session-Token": self.token} if headers is None else headers,
            data={"lot_id": lot_id, "session": session},
            files={"image": ("f.jpg", _jpeg() if image is None else image, "image/jpeg")},
        )

    def frames(self, count: int, **kwargs: Any) -> list[Any]:
        return [self.frame(_jpeg(i), **kwargs) for i in range(count)]

    def photos(self) -> list[Path]:
        root = self.settings.EDGE_DATA_DIR / "captures"
        return sorted(path for path in root.rglob("*") if path.is_file())


@pytest.fixture
def make_rig(settings: EdgeSettings) -> Callable[..., _Rig]:
    def _make(*script: InferenceResult | Exception, **kwargs: Any) -> _Rig:
        version = kwargs.pop("version", OFFICIAL)
        sink = kwargs.pop("sink", None) or InMemorySink()
        use = kwargs.pop("settings", settings)
        return _Rig(use, _Scripted(*script, version=version), sink, **kwargs)

    return _make


@pytest.fixture
def settings_factory(clean_edge_env: None, tmp_path: Path) -> Callable[..., EdgeSettings]:
    def _make(**values: Any) -> EdgeSettings:
        return EdgeSettings(EDGE_DATA_DIR=tmp_path / "d", DATASET_DIR=tmp_path / "ds", **values)

    return _make


@pytest.fixture
def lan_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])


@pytest.fixture
def tls_files(tmp_path: Path) -> tuple[Path, Path]:
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("certificate")
    key.write_text("private key content")
    key.chmod(0o600)
    return cert, key


# -------------------------------------------------------------------------------- errors, order


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        pytest.param({"headers": {}}, 401, id="no-token"),
        pytest.param({"headers": {"X-Session-Token": "wrong"}}, 401, id="wrong-token"),
        pytest.param({"image": b"\xff" * (LIVE_MAX_BYTES + 1)}, 413, id="image-too-large"),
        pytest.param({"session": "curto"}, 422, id="short-session"),
        pytest.param({"session": "a" * 65}, 422, id="long-session"),
        pytest.param({"session": "a" * 16 + "\n"}, 422, id="session-newline"),
        pytest.param({"session": "a" * 15 + "!"}, 422, id="session-charset"),
        pytest.param({"lot_id": "lote 1"}, 422, id="lot"),
        pytest.param({"lot_id": "L-1\n"}, 422, id="lot-newline"),
        pytest.param({"image": _encoded("GIF")}, 415, id="gif"),
        pytest.param({"image": _encoded("PNG")}, 415, id="png"),
        pytest.param({"image": _jpeg(size=(1001, 1000))}, 415, id="too-many-pixels"),
        pytest.param({"image": b"not an image"}, 415, id="garbage"),
    ],
)
def test_refusals_do_not_reach_the_model_nor_a_session(
    make_rig: Callable[..., _Rig], kwargs: dict[str, Any], code: int
) -> None:
    rig = make_rig()
    assert rig.frame(**kwargs).status_code == code
    assert rig.inferencer.calls == 0
    assert len(rig.app.state.live_sessions) == 0


def test_missing_fields_are_422(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    headers = {"X-Session-Token": rig.token}
    image = {"image": ("f.jpg", _jpeg(), "image/jpeg")}
    good = {"lot_id": "L-1", "session": SESSION}
    assert rig.client.post("/api/live/frame", headers=headers, data=good).status_code == 422
    for missing in good:
        data = {name: value for name, value in good.items() if name != missing}
        response = rig.client.post("/api/live/frame", headers=headers, data=data, files=image)
        assert response.status_code == 422, missing


def test_jpeg_at_the_limits_is_accepted(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    assert rig.frame(_jpeg(size=(1000, 1000))).status_code == 200


def test_content_length_limit_of_the_route_only(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    declared = {"Content-Length": str(LIVE_MAX_REQUEST_BYTES + 1)}
    live = rig.client.post("/api/live/frame", headers=declared, content=b"")
    assert live.status_code == 413
    at_limit = {"Content-Length": str(LIVE_MAX_REQUEST_BYTES)}
    assert (
        rig.client.post("/api/live/frame", headers=at_limit, content=b"").status_code == 401
    )  # the token comes after the middleware
    capture = rig.client.post("/api/capture", headers=declared, content=b"")
    assert capture.status_code == 401  # 1.25 MiB is well inside the 3.5 MiB of the capture


def test_middleware_counts_a_chunked_body_with_the_limit_of_the_path() -> None:
    def run(path: str) -> list[dict[str, Any]]:
        sent: list[dict[str, Any]] = []

        async def inner(scope: Any, receive: Any, send: Any) -> None:
            while (await receive()).get("more_body"):
                pass
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        chunks = iter([b"x" * 60, b"x" * 60])

        async def receive_chunks() -> dict[str, Any]:
            try:
                return {"type": "http.request", "body": next(chunks), "more_body": True}
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        middleware = BodySizeLimitMiddleware(inner, limit=1000, path_limits={"/small": 100})
        scope = {"type": "http", "path": path, "headers": []}
        asyncio.run(middleware(scope, receive_chunks, send))
        return sent

    assert run("/small")[0]["status"] == 413
    assert run("/other")[0]["status"] == 200


def test_image_is_refused_before_the_missing_model(settings: EdgeSettings) -> None:
    rig = _Rig(settings, None, InMemorySink())
    assert rig.frame(_encoded("PNG")).status_code == 415
    response = rig.frame()
    assert response.status_code == 503
    assert response.json() == {"detail": "model not loaded"}


def test_missing_model_comes_before_the_sessions(
    settings_factory: Callable[..., EdgeSettings],
) -> None:
    rig = _Rig(settings_factory(LIVE_MAX_SESSIONS=1), None, InMemorySink())
    assert rig.frame(session="a" * 16).status_code == 503
    assert rig.frame(session="b" * 16).status_code == 503
    assert len(rig.app.state.live_sessions) == 0


def test_busy_decode_slots_answer_503(settings: EdgeSettings) -> None:
    release = threading.Event()
    entered = threading.Event()

    class _Blocking(_Scripted):
        def infer(self, image: Image.Image) -> InferenceResult:
            entered.set()
            release.wait(timeout=10)
            return FAIR

    rig = _Rig(settings, _Blocking(), InMemorySink(), max_concurrent_decodes=1, decode_wait_s=0.2)
    with TestClient(rig.app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        rig.client = client
        first = pool.submit(rig.frame)
        assert entered.wait(timeout=5)
        busy = rig.frame(_encoded("PNG"))  # the limiter comes before the image
        release.set()
        assert first.result(timeout=10).status_code == 200
    assert busy.status_code == 503
    assert busy.json() == {"detail": "server busy"}


def test_failed_token_does_not_read_the_form(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    response = rig.client.post(
        "/api/live/frame", headers={"X-Session-Token": "x"}, content=b"not multipart"
    )
    assert response.status_code == 401


# ------------------------------------------------------------------------------------- emission


def test_one_inspection_per_part(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(FAIR)
    responses = rig.frames(30)
    assert all(response.status_code == 200 for response in responses)
    bodies = [response.json() for response in responses]
    assert all(body["result"] is not None for body in bodies)
    emitted = [i for i, body in enumerate(bodies) if body["inspection"] is not None]
    assert emitted == [9]
    assert bodies[9]["state"] == "EMIT"
    assert bodies[10]["state"] == "WAIT_REMOVAL"
    assert len(rig.sink.items) == 1
    inspection_id = bodies[9]["inspection"]["inspection_id"]
    assert str(rig.sink.items[0].inspection_id) == inspection_id
    assert [photo.name for photo in rig.photos()] == [f"{inspection_id}.jpg"]


def test_outbox_payload_has_the_contract_and_no_image(
    make_rig: Callable[..., _Rig], tmp_path: Path
) -> None:
    outbox = SqliteOutbox(tmp_path / "outbox.sqlite3")
    try:
        rig = make_rig(FAIR, sink=outbox)
        emitted = [r.json()["inspection"] for r in rig.frames(30) if r.json()["inspection"]]
    finally:
        outbox.close()
    connection = sqlite3.connect(tmp_path / "outbox.sqlite3")
    try:
        rows = connection.execute("SELECT payload FROM outbox").fetchall()
    finally:
        connection.close()
    assert len(rows) == len(emitted) == len(rig.photos()) == 1
    payload = json.loads(rows[0][0])
    assert set(payload) == set(InspectionCreate.model_fields)
    assert (
        str(InspectionCreate.model_validate(payload).inspection_id) == emitted[0]["inspection_id"]
    )


def test_capture_route_is_unchanged_without_tls(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(FAIR)
    response = rig.client.post(
        "/api/capture",
        headers={"X-Session-Token": rig.token},
        data={"lot_id": "L-1", "mode": "inspect"},
        files={"image": ("a.jpg", _jpeg(), "image/jpeg")},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"inspection", "labels_pt", "approved"}
    assert body["labels_pt"] == {
        "object_type": "parafuso",
        "grade": "mediano",
        "verdict": "aprovada",
    }
    assert body["approved"] is True
    assert str(rig.sink.items[0].inspection_id) == body["inspection"]["inspection_id"]
    # A capture does not go through a session.
    assert len(rig.app.state.live_sessions) == 0


def test_response_shape(make_rig: Callable[..., _Rig]) -> None:
    body = make_rig(FAIR).frame().json()
    assert set(body) == {"state", "stability", "result", "inspection"}
    assert body["state"] == "DETECTING"
    assert body["stability"] == 0.1
    assert body["inspection"] is None
    assert body["result"] == {
        "object_type": "screw",
        "grade": "fair",
        "type_confidence": 0.9,
        "labels_pt": {"object_type": "parafuso", "grade": "mediano", "verdict": "aprovada"},
    }


def test_emitted_frame_can_differ_from_the_current_one(make_rig: Callable[..., _Rig]) -> None:
    clock = _Clock()
    fair = _result(confidence=0.85, latency_ms=33)
    rig = make_rig(_result(grade=Grade.POOR, latency_ms=11), *[fair] * 8, POOR, clock=clock)
    frames = [_jpeg(i * 20) for i in range(10)]
    for index, frame in enumerate(frames):
        clock.at(index)
        response = rig.frame(frame)
    body = response.json()
    assert body["state"] == "EMIT"
    assert body["result"]["grade"] == "poor"
    assert body["result"]["labels_pt"]["verdict"] == "reprovada"
    assert body["inspection"]["grade"] == "fair"
    assert body["inspection"]["latency_ms"] == 33
    assert body["inspection"]["source"] == "live"
    assert datetime.fromisoformat(body["inspection"]["inspected_at"]) == T0 + timedelta(seconds=8)
    ((photo),) = rig.photos()
    assert photo.parent.name == "2026-11-01"
    assert photo.read_bytes() == frames[8]
    assert stat.S_IMODE(photo.stat().st_mode) == 0o600
    assert stat.S_IMODE(photo.parent.stat().st_mode) == 0o700


def test_emission_goes_to_the_console_table(make_rig: Callable[..., _Rig], lan_ips: None) -> None:
    rig = make_rig(FAIR)
    body = rig.frames(10)[-1].json()
    page = rig.client.get("/").text
    assert f'data-inspection-id="{body["inspection"]["inspection_id"]}"' in page


def test_unknown_result_has_null_grade_and_desconhecido(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(UNKNOWN)
    bodies = [response.json() for response in rig.frames(3)]
    for body in bodies:
        assert (body["state"], body["stability"], body["inspection"]) == ("IDLE", 0, None)
        result = body["result"]
        assert (result["object_type"], result["grade"]) == ("unknown", None)
        assert result["labels_pt"] == {
            "object_type": "desconhecido",
            "grade": None,
            "verdict": "desconhecido",
        }
    assert rig.sink.items == []
    assert rig.photos() == []


def test_new_lot_starts_the_window_over(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(FAIR)
    assert all(r.json()["inspection"] is None for r in rig.frames(9, lot_id="L-A"))
    responses = rig.frames(10, lot_id="L-B")
    assert all(r.json()["inspection"] is None for r in responses[:9])
    assert responses[9].json()["inspection"]["lot_id"] == "L-B"


def test_sessions_have_separate_windows(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(FAIR)
    rig.frames(9, session="a" * 16)
    assert rig.frames(1, session="b" * 16)[0].json()["stability"] == 0.1
    assert rig.frames(1, session="a" * 16)[0].json()["state"] == "EMIT"


# ------------------------------------------------------------------------------- failed recording


def test_sink_error_answers_503_removes_the_photo_and_emits_again(
    make_rig: Callable[..., _Rig],
) -> None:
    rig = make_rig(FAIR, sink=_Sink(SinkError("disk")))
    responses = rig.frames(30)
    codes = [response.status_code for response in responses]
    assert codes[9] == 503
    assert responses[9].json() == {"detail": "failed to persist inspection"}
    assert codes[:9] + codes[10:] == [200] * 29
    with_inspection = [
        i for i, r in enumerate(responses) if r.status_code == 200 and r.json()["inspection"]
    ]
    assert with_inspection == [19]
    inspection_id = responses[19].json()["inspection"]["inspection_id"]
    assert [str(item.inspection_id) for item in rig.sink.items] == [inspection_id]
    assert [photo.name for photo in rig.photos()] == [f"{inspection_id}.jpg"]


def test_other_recording_failure_answers_500_and_resets(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(FAIR, sink=_Sink(RuntimeError("boom")))
    responses = rig.frames(20)
    assert responses[9].status_code == 500
    assert responses[9].json() == {"detail": "internal server error"}
    assert rig.photos()[0].stem == responses[19].json()["inspection"]["inspection_id"]
    assert len(rig.photos()) == 1


def test_full_disk_answers_500_and_resets(
    make_rig: Callable[..., _Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(FAIR)
    failures = [OSError(28, "No space left on device")]

    def create(path: Path) -> int:
        if failures:
            raise failures.pop()
        return real_create(path)

    real_create = app_module.create_private_file
    monkeypatch.setattr(app_module, "create_private_file", create)
    responses = rig.frames(20)
    assert responses[9].status_code == 500
    assert responses[19].json()["inspection"] is not None
    assert len(rig.sink.items) == 1


def test_inference_error_does_not_enter_the_window(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(*[FAIR] * 4, InferenceError("x"), FAIR)
    responses = rig.frames(11)
    assert responses[4].status_code == 500
    assert responses[4].json() == {"detail": "inference failed"}
    with_inspection = [i for i, r in enumerate(responses) if i != 4 and r.json()["inspection"]]
    assert with_inspection == [10]


def test_inference_error_with_a_new_lot_does_not_reset(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(*[FAIR] * 9, InferenceError("x"), FAIR)
    rig.frames(9, lot_id="L-A")
    assert rig.frame(lot_id="L-B").status_code == 500
    assert rig.frame(lot_id="L-A").json()["state"] == "EMIT"


# ------------------------------------------------------------------------------------- sessions


def test_session_limit_and_expiry(settings_factory: Callable[..., EdgeSettings]) -> None:
    clock = _Clock()
    rig = _Rig(settings_factory(LIVE_MAX_SESSIONS=2), _Scripted(FAIR), InMemorySink(), clock=clock)
    assert rig.frame(session="a" * 16).status_code == 200
    clock.at(30)
    assert rig.frame(session="b" * 16).status_code == 200
    clock.at(31)
    refused = rig.frame(session="c" * 16)
    assert refused.status_code == 429
    assert refused.json() == {"detail": "too many live sessions"}
    clock.at(61)
    assert rig.frame(session="c" * 16).status_code == 200


def test_session_limit_comes_before_the_model_call(
    settings_factory: Callable[..., EdgeSettings],
) -> None:
    rig = _Rig(settings_factory(LIVE_MAX_SESSIONS=1), _Scripted(FAIR), InMemorySink())
    rig.frame(session="a" * 16)
    calls = rig.inferencer.calls
    assert rig.frame(session="b" * 16).status_code == 429
    assert rig.inferencer.calls == calls


def test_live_settings_reach_the_machine(settings_factory: Callable[..., EdgeSettings]) -> None:
    settings = settings_factory(
        LIVE_WINDOW=3, LIVE_MIN_AGREE=3, LIVE_MIN_CONFIDENCE=0.95, LIVE_EMPTY_FRAMES=1
    )
    rig = _Rig(
        settings,
        _Scripted(FAIR, FAIR, FAIR, UNKNOWN, *[_result(confidence=0.96)] * 3),
        InMemorySink(),
    )
    bodies = [response.json() for response in rig.frames(7)]
    assert all(body["inspection"] is None for body in bodies[:6])  # 0.9 < 0.95
    assert bodies[3]["state"] == "IDLE"  # a single unknown is enough
    assert bodies[6]["state"] == "EMIT"


def test_sweeper_runs_in_the_lifespan_and_shutdown_ends_the_sessions(
    make_rig: Callable[..., _Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "LIVE_SWEEP_INTERVAL_S", 0.01)
    clock = _Clock()
    rig = make_rig(FAIR, clock=clock)
    sessions = rig.app.state.live_sessions
    with TestClient(rig.app) as client:
        rig.client = client
        rig.frame()
        assert len(sessions) == 1
        clock.at(61)
        deadline = time.monotonic() + 5
        while len(sessions) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(sessions) == 0
        clock.at(62)
        rig.frame()
        assert len(sessions) == 1
    assert len(sessions) == 0


def test_sweeper_survives_a_failing_clock(
    make_rig: Callable[..., _Rig],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(app_module, "LIVE_SWEEP_INTERVAL_S", 0.01)
    clock = _Clock()
    rig = make_rig(FAIR, clock=clock)
    sessions = rig.app.state.live_sessions
    failing = threading.Event()
    real_sweep = sessions.sweep

    def sweep() -> None:
        if not failing.is_set():
            failing.set()
            raise RuntimeError("boom")
        real_sweep()

    monkeypatch.setattr(sessions, "sweep", sweep)
    with TestClient(rig.app) as client:
        rig.client = client
        rig.frame()
        assert failing.wait(timeout=5)
        clock.at(61)
        deadline = time.monotonic() + 5
        while len(sessions) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(sessions) == 0
    assert "live session sweep failed" in caplog.text


# ------------------------------------------------------------------------- provisional model (R-06)


def test_provisional_model_is_simulated_with_the_suffix(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(FAIR, version=PROVISIONAL)
    responses = rig.frames(10)
    assert all(r.json()["result"]["labels_pt"]["verdict"].endswith(SUFFIX) for r in responses)
    inspection = responses[-1].json()["inspection"]
    assert inspection["source"] == "simulated"
    assert inspection["model_version"] == PROVISIONAL
    assert rig.sink.items[0].source.value == "simulated"


def test_provisional_suffix_is_the_one_of_the_capture_also_on_unknown(
    make_rig: Callable[..., _Rig],
) -> None:
    rig = make_rig(UNKNOWN, version=PROVISIONAL)
    labels = rig.frame().json()["result"]["labels_pt"]
    assert labels["verdict"] == "desconhecido" + SUFFIX
    assert labels["object_type"] == "desconhecido"


def test_official_model_is_live_without_suffix(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(FAIR)
    responses = rig.frames(10)
    assert not any(SUFFIX in r.json()["result"]["labels_pt"]["verdict"] for r in responses)
    assert responses[-1].json()["inspection"]["source"] == "live"


def test_stub_model_keeps_everything_in_memory(
    clean_edge_env: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy: list[Any] = []
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OUTBOX_PATH", str(tmp_path / "outbox.sqlite3"))
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: spy.append(app))
    cli.main(["--stub-model"])
    app = spy[0]
    client = TestClient(app)
    for index in range(10):
        response = client.post(
            "/api/live/frame",
            headers={"X-Session-Token": app.state.session_token},
            data={"lot_id": "L-1", "session": SESSION},
            files={"image": ("f.jpg", _jpeg(index), "image/jpeg")},
        )
        assert response.status_code == 200
    assert response.json()["inspection"]["model_version"] == "stub-v0"
    assert not (tmp_path / "outbox.sqlite3").exists()


# ------------------------------------------------------------------------------------ latency


def _latency(page: str) -> str:
    match = re.search(r'id="live-latency">([^<]*)<', page)
    assert match is not None
    return match.group(1)


def test_console_latency(make_rig: Callable[..., _Rig], lan_ips: None) -> None:
    fast = _result(latency_ms=100)
    rig = make_rig(_result(latency_ms=300), _result(latency_ms=300), fast)
    assert _latency(rig.client.get("/").text) == "—"
    responses = rig.frames(20)
    assert _latency(rig.client.get("/").text) == "última 100 ms · p95 300 ms"
    assert not any("p95" in response.text for response in responses)


def test_failed_inference_records_no_latency(make_rig: Callable[..., _Rig], lan_ips: None) -> None:
    rig = make_rig(InferenceError("x"))
    rig.frame()
    assert _latency(rig.client.get("/").text) == "—"


def test_latency_of_all_sessions_counts(make_rig: Callable[..., _Rig], lan_ips: None) -> None:
    rig = make_rig(_result(latency_ms=10), _result(latency_ms=20))
    rig.frame(session="a" * 16)
    rig.frame(session="b" * 16)
    assert _latency(rig.client.get("/").text) == "última 20 ms · p95 20 ms"


# --------------------------------------------------------------------------------------- page


def test_page_requires_the_token_and_has_the_headers(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    for url, code in (("/live", 401), ("/live?t=wrong", 401), (f"/live?t={rig.token}", 200)):
        response = rig.client.get(url)
        assert response.status_code == code
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert rig.token not in response.text


def test_page_has_the_lot_the_script_and_the_fps(
    settings_factory: Callable[..., EdgeSettings],
) -> None:
    rig = _Rig(settings_factory(LIVE_FPS=5), _Scripted(), InMemorySink())
    page = rig.client.get(f"/live?t={rig.token}").text
    assert 'src="/static/live.js"' in page
    assert 'id="lot_id"' in page and 'name="lot_id"' in page
    assert 'data-fps="5"' in page
    assert "Sem pessoas no quadro" in page


def test_page_brings_the_labels_of_an_emitted_inspection(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(version=PROVISIONAL)
    page = rig.client.get(f"/live?t={rig.token}").text
    assert "&quot;fair&quot;: &quot;mediano&quot;" in page
    assert "&quot;screw&quot;: &quot;parafuso&quot;" in page
    assert f"&quot;poor&quot;: &quot;reprovada{SUFFIX}&quot;" in page
    assert f"&quot;&quot;: &quot;sem grau{SUFFIX}&quot;" in page


def test_page_without_a_model_still_renders(settings: EdgeSettings) -> None:
    rig = _Rig(settings, None, InMemorySink())
    page = rig.client.get(f"/live?t={rig.token}").text
    assert "&quot;good&quot;: &quot;aprovada&quot;" in page


def test_html_is_not_served_as_a_static_file(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    assert rig.client.get("/static/live.html").status_code == 404
    assert rig.client.get("/static/live.js").status_code == 200
    assert not (STATIC_DIR / "live.html").exists()


def test_page_files_are_self_contained_and_follow_the_section() -> None:
    script = (STATIC_DIR / "live.js").read_text(encoding="utf-8")
    template = (TEMPLATES_DIR / "live.html").read_text(encoding="utf-8")
    for text in (script, template):
        assert "http://" not in text and "https://" not in text
    for needle in (
        "isSecureContext",
        "getUserMedia",
        'facingMode: "environment"',
        "getRandomValues",
        "O vídeo ao vivo exige HTTPS (configure EDGE_TLS_CERT e EDGE_TLS_KEY).",
        "MAX_SIDE = 640",
        "JPEG_QUALITY = 0.8",
        "EMIT_SHOW_MS = 2000",
        '"X-Session-Token"',
        '"/api/live/frame"',
        '"image/jpeg"',
    ):
        assert needle in script, needle
    # The secure-context check comes before the camera is asked for.
    assert script.index("!window.isSecureContext") < script.index(".getUserMedia(")


def _js_function(script: str, name: str) -> str:
    """Source of a top-level function of ``live.js``: two-space indent, closed by ``  }``."""
    start = script.index(f"  function {name}(")
    return script[start : script.index("\n  }\n", start)]


def test_overlay_gives_the_verdict_its_own_line_and_fits_every_line() -> None:
    """RV-01 of SPEC-019: the provisional warning (R-06) must never be cut off the canvas.

    The suite runs no browser, so this only pins the shape of the code; the measures in a real
    browser are in the dev report of the round.
    """
    script = (STATIC_DIR / "live.js").read_text(encoding="utf-8")
    lines = _js_function(script, "resultLines")
    assert "labels.verdict," in lines
    assert "—" not in lines
    fit = _js_function(script, "fitFont")
    assert "ctx.measureText(line).width > maxWidth" in fit
    band = _js_function(script, "drawBand")
    assert "fitFont(ctx, line" in band
    assert "width - 2 * BAND_MARGIN" in band


def test_lot_of_the_frames_is_the_confirmed_one() -> None:
    """RV-03 of SPEC-019: a pause in the middle of the typing does not change the lot (ADR-013)."""
    script = (STATIC_DIR / "live.js").read_text(encoding="utf-8")
    assert 'form.append("lot_id", lot)' in script
    assert 'lotField.addEventListener("change", confirmLot)' in script
    for name in ("send", "tick"):
        assert "lotField" not in _js_function(script, name), name
    assert 'event.key === "Enter"' in script


def test_log_of_the_page_and_the_route_never_has_the_token(
    make_rig: Callable[..., _Rig], caplog: pytest.LogCaptureFixture
) -> None:
    rig = make_rig(FAIR)
    with caplog.at_level(logging.DEBUG, logger="qc_edge"):
        rig.client.get(f"/live?t={rig.token}")
        rig.frame()
    lines = "\n".join(r.getMessage() for r in caplog.records if r.name == "qc_edge")
    assert "GET /live 200" in lines
    assert "POST /api/live/frame 200" in lines
    assert rig.token not in lines


# ---------------------------------------------------------------------------------- console, TLS


def _console_urls(page: str) -> list[str]:
    return re.findall(r'class="url"[^>]*>(https?://[^<]+)<', page)


def test_console_without_tls_is_as_before(make_rig: Callable[..., _Rig], lan_ips: None) -> None:
    rig = make_rig()
    page = rig.client.get("/").text
    assert _console_urls(page) == [f"http://192.168.0.42:8000/capture?t={rig.token}"]
    assert "/live?" not in page
    assert page.count('class="qr"') == 1


def test_console_with_tls_has_two_https_qr_codes(
    clean_edge_env: None, tmp_path: Path, tls_files: tuple[Path, Path], lan_ips: None
) -> None:
    settings = EdgeSettings(
        EDGE_DATA_DIR=tmp_path / "d",
        DATASET_DIR=tmp_path / "ds",
        EDGE_TLS_CERT=tls_files[0],
        EDGE_TLS_KEY=tls_files[1],
    )
    rig = _Rig(settings, _Scripted(), InMemorySink())
    page = rig.client.get("/").text
    assert _console_urls(page) == [
        f"https://192.168.0.42:8000/capture?t={rig.token}",
        f"https://192.168.0.42:8000/live?t={rig.token}",
    ]
    assert page.count('class="qr"') == 2
    assert page.count("<svg") == 2
    # The console refuses a remote client and points to the https:// address.
    remote = TestClient(rig.app, client=("192.168.0.9", 1), base_url=CONSOLE_URL).get("/")
    assert remote.status_code == 403
    assert "https://127.0.0.1" in remote.text
