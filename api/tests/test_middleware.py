"""ASGI middlewares (SPEC-004 sections 4.2 and 4.5, SPEC-005 section 4.5), on minimal apps,
without a database."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qc_api.middleware import (
    BodySizeLimitMiddleware,
    RequestLogMiddleware,
    UnhandledErrorMiddleware,
    find_database_error,
    sqlstate_label,
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


def _db_error_app(markers: dict[str, str]) -> FastAPI:
    app = FastAPI()

    @app.get("/db-error")
    def db_error() -> None:
        raise psycopg.errors.UndefinedTable(markers["direct"])

    @app.get("/wrapped/{item}")
    def wrapped(item: str) -> None:
        raise RuntimeError("wrapper") from psycopg.errors.CheckViolation(markers["wrapped"])

    @app.get("/context")
    def context() -> None:
        try:
            raise psycopg.errors.UniqueViolation(markers["context"])
        except psycopg.Error:
            raise ValueError("while handling") from None

    @app.get("/no-sqlstate")
    def no_sqlstate() -> None:
        raise psycopg.DatabaseError(markers["plain"])

    @app.get("/plain")
    def plain() -> None:
        raise ValueError(markers["plain"])

    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestLogMiddleware)
    return app


@pytest.fixture
def markers() -> dict[str, str]:
    return {
        name: f"MARK-{name}-{uuid.uuid4().hex}"
        for name in ("direct", "wrapped", "context", "plain")
    }


@pytest.fixture
def db_error_client(markers: dict[str, str]) -> Iterator[TestClient]:
    with TestClient(_db_error_app(markers), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/db-error", "route=/db-error type=UndefinedTable sqlstate=42P01"),
        ("/wrapped/x", "route=/wrapped/{item} type=CheckViolation sqlstate=23514"),
        ("/context", "route=/context type=UniqueViolation sqlstate=23505"),
        ("/no-sqlstate", "route=/no-sqlstate type=DatabaseError sqlstate=-"),
    ],
)
def test_database_error_is_logged_without_message(
    db_error_client: TestClient,
    markers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    path: str,
    expected: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    response = db_error_client.get(path)
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert [r.getMessage() for r in errors] == [f"unhandled database error: {expected}"]
    assert all(r.exc_info is None for r in caplog.records)
    for marker in markers.values():
        assert marker not in caplog.text
        assert marker not in response.text


def test_other_exceptions_keep_the_traceback(
    db_error_client: TestClient, markers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    response = db_error_client.get("/plain")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert any(r.exc_info for r in caplog.records)
    assert markers["plain"] not in response.text


def test_find_database_error_follows_chain_and_groups() -> None:
    inner = psycopg.errors.CheckViolation("x")
    outer = RuntimeError("a")
    outer.__cause__ = ValueError("b")
    outer.__cause__.__context__ = inner
    assert find_database_error(outer) is inner
    group = ExceptionGroup("g", [ValueError("c"), KeyError("d")])
    group.exceptions[1].__context__ = inner
    assert find_database_error(group) is inner
    assert find_database_error(ValueError("e")) is None


def test_find_database_error_survives_cycles() -> None:
    first, second = ValueError("a"), ValueError("b")
    first.__context__ = second
    second.__context__ = first
    assert find_database_error(first) is None


def test_sqlstate_label_rejects_odd_values() -> None:
    error = psycopg.DatabaseError("x")
    error.sqlstate = "bad\nvalue"
    assert sqlstate_label(error) == "-"
    assert sqlstate_label(psycopg.errors.NumericValueOutOfRange("x")) == "22003"
