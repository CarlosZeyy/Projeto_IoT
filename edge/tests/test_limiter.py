"""Decode limiter (SPEC-007 section 4.6, SEC-02; SPEC-025 section 4.2, SEC-03)."""

from __future__ import annotations

import asyncio
import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from qc_edge import app as app_module
from qc_edge import limits as limits_module
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import (
    DEFAULT_STUB_RESULT,
    InferenceError,
    InferenceResult,
    ModelInfo,
    StubInferencer,
)
from qc_edge.sink import InMemorySink


class BlockingInferencer:
    """Records concurrent ``infer`` calls and blocks until ``release`` is set."""

    model_info = ModelInfo("block-v1", "b" * 64)

    def __init__(self, fail_first: bool = False) -> None:
        self.release = threading.Event()
        self.entered = threading.Semaphore(0)
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self.fail_first = fail_first

    def infer(self, image: Image.Image) -> InferenceResult:
        with self._lock:
            self.calls += 1
            call = self.calls
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.entered.release()
        try:
            if self.fail_first and call == 1:
                raise InferenceError("first call fails")
            self.release.wait(timeout=10)
            return DEFAULT_STUB_RESULT
        finally:
            with self._lock:
                self.active -= 1


def _post(client: TestClient, token: str, image: bytes) -> Any:
    return client.post(
        "/api/capture",
        headers={"X-Session-Token": token},
        data={"lot_id": "L-001", "mode": "inspect"},
        files={"image": ("a.jpg", image, "image/jpeg")},
    )


def _gif() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="GIF")
    return buffer.getvalue()


def _captures(settings: EdgeSettings) -> list[Any]:
    return [p for p in (settings.EDGE_DATA_DIR / "captures").rglob("*") if p.is_file()]


@pytest.mark.parametrize(
    ("max_concurrent_decodes", "decode_wait_s"),
    [(0, 1.0), (-1, 1.0), (1.5, 1.0), (True, 1.0), (1, 0), (1, -1.0), (1, float("inf"))],
)
def test_invalid_limiter_arguments(
    settings: EdgeSettings, max_concurrent_decodes: Any, decode_wait_s: Any
) -> None:
    with pytest.raises(ValueError):
        create_app(
            settings,
            None,
            InMemorySink(),
            max_concurrent_decodes=max_concurrent_decodes,
            decode_wait_s=decode_wait_s,
        )


def test_busy_slots_answer_503_and_do_nothing(settings: EdgeSettings, jpeg_bytes: bytes) -> None:
    inferencer = BlockingInferencer()
    sink = InMemorySink()
    app = create_app(settings, inferencer, sink, max_concurrent_decodes=2, decode_wait_s=0.3)
    token = app.state.session_token
    # One event loop for every thread (the anyio semaphore of the limiter is not
    # meant to be shared by several loops at the same time).
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=4) as pool:
        first = [pool.submit(_post, client, token, jpeg_bytes) for _ in range(2)]
        assert inferencer.entered.acquire(timeout=5) and inferencer.entered.acquire(timeout=5)
        busy = [pool.submit(_post, client, token, jpeg_bytes) for _ in range(2)]
        busy_responses = [future.result(timeout=10) for future in busy]
        inferencer.release.set()
        ok_responses = [future.result(timeout=10) for future in first]
    assert [r.status_code for r in busy_responses] == [503, 503]
    assert all(r.json() == {"detail": "server busy"} for r in busy_responses)
    assert [r.status_code for r in ok_responses] == [200, 200]
    assert inferencer.max_active == 2
    assert inferencer.calls == 2
    assert len(sink.items) == 2
    assert len(_captures(settings)) == 2


def test_waiting_requests_get_a_slot(settings: EdgeSettings, jpeg_bytes: bytes) -> None:
    inferencer = BlockingInferencer()
    app = create_app(
        settings, inferencer, InMemorySink(), max_concurrent_decodes=2, decode_wait_s=5
    )
    token = app.state.session_token
    # One event loop for every thread (the anyio semaphore of the limiter is not
    # meant to be shared by several loops at the same time).
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_post, client, token, jpeg_bytes) for _ in range(4)]
        time.sleep(0.3)
        inferencer.release.set()
        statuses = [future.result(timeout=10).status_code for future in futures]
    assert statuses == [200, 200, 200, 200]
    assert inferencer.max_active == 2


def test_slot_is_released_after_errors(
    settings: EdgeSettings, jpeg_bytes: bytes, make_image: Any
) -> None:
    inferencer = BlockingInferencer(fail_first=True)
    inferencer.release.set()
    app = create_app(
        settings, inferencer, InMemorySink(), max_concurrent_decodes=1, decode_wait_s=1
    )
    client = TestClient(app)
    token = app.state.session_token
    statuses = [_post(client, token, jpeg_bytes).status_code for _ in range(3)]
    assert statuses == [500, 200, 200]
    # A 415 (decode failure inside the slot) also releases it.
    assert _post(client, token, b"not an image").status_code == 415
    assert _post(client, token, jpeg_bytes).status_code == 200


def test_decode_happens_inside_the_slot(
    settings: EdgeSettings, jpeg_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(settings, None, InMemorySink(), max_concurrent_decodes=1, decode_wait_s=0.2)
    token = app.state.session_token
    inside = threading.Event()
    release = threading.Event()
    original = limits_module.load_capture_image

    def slow_load(data: bytes) -> Image.Image:
        inside.set()
        release.wait(timeout=10)
        return original(data)

    monkeypatch.setattr(limits_module, "load_capture_image", slow_load)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_post, client, token, jpeg_bytes)
        assert inside.wait(timeout=5)
        second = _post(client, token, jpeg_bytes)
        release.set()
        assert first.result(timeout=10).status_code == 503  # model not loaded, after decoding
    assert second.status_code == 503
    assert second.json() == {"detail": "server busy"}


def test_422_does_not_wait_for_a_slot(settings: EdgeSettings, jpeg_bytes: bytes) -> None:
    inferencer = BlockingInferencer()
    app = create_app(
        settings, inferencer, InMemorySink(), max_concurrent_decodes=1, decode_wait_s=5
    )
    token = app.state.session_token
    # One event loop for every thread (the anyio semaphore of the limiter is not
    # meant to be shared by several loops at the same time).
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        holder = pool.submit(_post, client, token, jpeg_bytes)
        assert inferencer.entered.acquire(timeout=5)
        started = time.monotonic()
        response = client.post(
            "/api/capture",
            headers={"X-Session-Token": token},
            data={"lot_id": "bad lot", "mode": "inspect"},
            files={"image": ("a.jpg", jpeg_bytes, "image/jpeg")},
        )
        elapsed = time.monotonic() - started
        inferencer.release.set()
        assert holder.result(timeout=10).status_code == 200
    assert response.status_code == 422
    assert elapsed < 2


# ------------------------------------------------- SPEC-025 section 4.2 (wait on the event loop)


class _LoopCheckingInferencer(BlockingInferencer):
    """Also records whether an event loop was running in the thread of each ``infer``."""

    def __init__(self) -> None:
        super().__init__()
        self.loop_running: list[bool] = []

    def infer(self, image: Image.Image) -> InferenceResult:
        try:
            asyncio.get_running_loop()
            self.loop_running.append(True)
        except RuntimeError:
            self.loop_running.append(False)
        return super().infer(image)


def _form(mode: str = "inspect", **fields: str) -> dict[str, str]:
    return {"lot_id": "L-001", "mode": mode, **fields}


async def _apost(client: httpx.AsyncClient, token: str, image: bytes, **data: str) -> Any:
    return await client.post(
        "/api/capture",
        headers={"X-Session-Token": token},
        data=data or _form(),
        files={"image": ("a.jpg", image, "image/jpeg")},
    )


def test_waiting_requests_do_not_block_status(settings: EdgeSettings, jpeg_bytes: bytes) -> None:
    inferencer = _LoopCheckingInferencer()
    sink = InMemorySink()
    app = create_app(settings, inferencer, sink, max_concurrent_decodes=1, decode_wait_s=1.5)
    token = app.state.session_token

    async def scenario() -> dict[str, Any]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000", timeout=30
        ) as client:
            holder = asyncio.create_task(_apost(client, token, jpeg_bytes))
            await asyncio.to_thread(inferencer.entered.acquire, True, 5)

            async def timed() -> tuple[float, Any]:
                start = time.monotonic()
                response = await _apost(client, token, jpeg_bytes)
                return time.monotonic() - start, response

            waiting = [asyncio.create_task(timed()) for _ in range(45)]
            await asyncio.sleep(0.5)
            started = time.monotonic()
            status = await client.get("/api/status", headers={"X-Session-Token": token})
            status_elapsed = time.monotonic() - started
            busy = await asyncio.gather(*waiting)
            inferencer.release.set()
            first = await holder
            return {
                "status": status,
                "status_elapsed": status_elapsed,
                "busy": busy,
                "first": first,
            }

    result = asyncio.run(scenario())
    assert result["status"].status_code == 200
    assert result["status_elapsed"] < 1.0
    for elapsed, response in result["busy"]:
        assert response.status_code == 503
        assert response.json() == {"detail": "server busy"}
        assert elapsed <= 1.5 + 2
    assert result["first"].status_code == 200
    assert inferencer.max_active == 1
    assert inferencer.loop_running == [False]
    assert len(sink.items) == 1
    assert len(_captures(settings)) == 1


def test_blocking_work_never_runs_on_the_event_loop(
    settings: EdgeSettings, jpeg_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []
    original = limits_module.load_capture_image

    def spy(data: bytes) -> Image.Image:
        try:
            asyncio.get_running_loop()
            seen.append(True)
        except RuntimeError:
            seen.append(False)
        return original(data)

    monkeypatch.setattr(limits_module, "load_capture_image", spy)
    app = create_app(settings, StubInferencer(), InMemorySink())
    token = app.state.session_token
    gif = _gif()
    collect = {
        "mode": "collect",
        "item_id": "S-012",
        "object_type": "screw",
        "grade": "fair",
        "labeler": "a",
        "angle": "2",
    }
    with TestClient(app) as client:
        assert _post(client, token, jpeg_bytes).status_code == 200
        assert _post(client, token, gif).status_code == 415
        response = client.post(
            "/api/capture",
            headers={"X-Session-Token": token},
            data=collect,
            files={"image": ("a.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert response.status_code == 200
    assert seen == [False, False, False]


def test_the_limiter_is_an_anyio_semaphore_shared_by_both_modes(
    settings: EdgeSettings, jpeg_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[tuple[int, int | None]] = []
    original = anyio.Semaphore

    def spy(initial_value: int, *, max_value: int | None = None) -> Any:
        created.append((initial_value, max_value))
        return original(initial_value, max_value=max_value)

    monkeypatch.setattr(app_module.anyio, "Semaphore", spy)
    create_app(settings, None, InMemorySink(), max_concurrent_decodes=3)
    assert created == [(3, 3)]
