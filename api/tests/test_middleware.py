"""ASGI middlewares (SPEC-004 sections 4.2 and 4.5), on a minimal app, without a database."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qc_api.middleware import (
    BodySizeLimitMiddleware,
    RequestLogMiddleware,
    UnhandledErrorMiddleware,
)

LIMIT = 10
TOO_LARGE = {"detail": "Request body too large"}


def _build_app(calls: list[str]) -> FastAPI:
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        calls.append("echo")
        return {"size": len(await request.body())}

    @app.post("/json")
    def json_route(payload: dict) -> dict:
        calls.append("json")
        return payload

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret detail of the failure")

    @app.get("/device")
    def device(request: Request) -> dict[str, str]:
        request.state.device_id = "edge-01"
        return {}

    app.add_middleware(BodySizeLimitMiddleware, get_limit=lambda: LIMIT)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestLogMiddleware)
    return app


@pytest.fixture
def calls() -> list[str]:
    return []


@pytest.fixture
def client(calls: list[str]) -> Iterator[TestClient]:
    with TestClient(_build_app(calls)) as test_client:
        yield test_client


def _chunks(total: int, size: int = 3) -> Iterator[bytes]:
    sent = 0
    while sent < total:
        chunk = b"x" * min(size, total - sent)
        sent += len(chunk)
        yield chunk


def test_body_at_limit_passes(client: TestClient) -> None:
    response = client.post("/echo", content=b"x" * LIMIT)
    assert response.status_code == 200
    assert response.json() == {"size": LIMIT}


def test_body_over_limit_is_413(client: TestClient, calls: list[str]) -> None:
    response = client.post("/echo", content=b"x" * (LIMIT + 1))
    assert response.status_code == 413
    assert response.json() == TOO_LARGE
    assert calls == []


def test_declared_length_over_limit_is_413_without_reaching_the_app(
    client: TestClient, calls: list[str]
) -> None:
    response = client.post("/echo", content=b"x", headers={"Content-Length": "300000"})
    assert response.status_code == 413
    assert response.json() == TOO_LARGE
    assert calls == []


def test_chunked_body_over_limit_is_413(client: TestClient) -> None:
    response = client.post("/echo", content=_chunks(LIMIT * 3))
    assert response.status_code == 413
    assert response.json() == TOO_LARGE


def test_chunked_body_under_limit_passes(client: TestClient) -> None:
    response = client.post("/echo", content=_chunks(LIMIT))
    assert response.status_code == 200
    assert response.json() == {"size": LIMIT}


def test_chunked_json_body_over_limit_is_413_not_400(client: TestClient, calls: list[str]) -> None:
    """FastAPI turns body-reading errors into 400; the 413 must survive its body parsing."""
    response = client.post(
        "/json", content=_chunks(LIMIT * 3), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json() == TOO_LARGE
    assert calls == []


def test_unhandled_exception_is_generic_500(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR, logger="qc_api")
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "Traceback" not in response.text
    assert "secret detail" not in response.text
    assert any(record.exc_info for record in caplog.records)


def test_request_log_line(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="qc_api")
    client.get("/device")
    client.post("/echo", content=b"x" * (LIMIT + 1))
    messages = [record.getMessage() for record in caplog.records]
    assert any(m.startswith("GET /device 200 device_id=edge-01 ") for m in messages), messages
    assert any(m.startswith("POST '/echo' 413 device_id=- ") for m in messages), messages


def test_request_log_unmatched_path_is_escaped(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="qc_api")
    client.get("/nope%0Aforged")
    (message,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("GET")]
    assert "\n" not in message
    assert " 404 " in message
