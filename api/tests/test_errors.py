"""Validation error handler (SPEC-004 sections 4.2, 4.4, 4.5), minimal app, no database.

A body FastAPI's default handler cannot encode (non-UTF-8 bytes, JSON nested past the recursion
limit) must still be a 422, and its bytes must never reach the log.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qc_api.errors import _error_without_input, install_exception_handlers
from qc_api.middleware import RequestLogMiddleware, UnhandledErrorMiddleware
from qc_contracts import InspectionCreate

URL = "/inspections"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def _build_app(*, with_handlers: bool) -> FastAPI:
    app = FastAPI()

    @app.post(URL)
    def create(payload: InspectionCreate) -> dict[str, str]:
        return {"inspection_id": str(payload.inspection_id)}

    if with_handlers:
        install_exception_handlers(app)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestLogMiddleware)
    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(_build_app(with_handlers=True)) as test_client:
        yield test_client


@pytest.fixture
def default_client() -> Iterator[TestClient]:
    """Same app with FastAPI's default validation handler (the reference 422)."""
    with TestClient(_build_app(with_handlers=False)) as test_client:
        yield test_client


def _assert_422_without_input(response) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail
    for error in detail:
        assert set(error) == {"type", "loc", "msg"}
        assert isinstance(error["msg"], str)
        assert all(isinstance(part, str | int) for part in error["loc"])
    assert "Traceback" not in response.text


@pytest.mark.parametrize(
    "body",
    [b"not json", b'{"lot_id": "L-1"}', b"[]", b"[" * 500 + b"]" * 500],
    ids=["not-json", "missing-fields", "array", "nested-500"],
)
def test_encodable_errors_keep_the_default_422(
    client: TestClient, default_client: TestClient, body: bytes
) -> None:
    headers = {"Content-Type": "application/json"}
    response = client.post(URL, content=body, headers=headers)
    reference = default_client.post(URL, content=body, headers=headers)
    assert reference.status_code == 422
    assert response.status_code == 422
    assert response.json() == reference.json()


@pytest.mark.parametrize("content_type", ["application/octet-stream", "image/jpeg"])
def test_non_utf8_body_is_422(client: TestClient, content_type: str) -> None:
    # FastAPI's default handler would decode the bytes as UTF-8 and fail (a 500).
    response = client.post(URL, content=JPEG, headers={"Content-Type": content_type})
    _assert_422_without_input(response)


def test_multipart_image_is_422(client: TestClient) -> None:
    response = client.post(URL, files={"image": ("a.jpg", JPEG, "image/jpeg")})
    _assert_422_without_input(response)


@pytest.mark.parametrize("depth", [2000, 5000])
def test_deeply_nested_json_is_422(client: TestClient, depth: int) -> None:
    # FastAPI's default handler would recurse once per level and fail (a 500).
    body = b"[" * depth + b"]" * depth
    response = client.post(URL, content=body, headers={"Content-Type": "application/json"})
    _assert_422_without_input(response)


def test_request_body_never_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    marker = "BODYMARK" + secrets.token_hex(6)
    body = b"\xff\xd8\xff" + marker.encode() + b"\xff" * 8
    response = client.post(URL, content=body, headers={"Content-Type": "application/octet-stream"})
    assert response.status_code == 422
    nested = b"[" * 3000 + marker.encode().join([b'"', b'"']) + b"]" * 3000
    response = client.post(URL, content=nested, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert marker not in caplog.text
    assert "\\xff\\xd8\\xff" not in caplog.text
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert any("POST /inspections 422" in record.getMessage() for record in caplog.records)


def test_error_without_input_keeps_only_plain_fields() -> None:
    error = {
        "type": "model_attributes_type",
        "loc": ("body", 0, b"\xff"),
        "msg": "Input should be a valid dictionary",
        "input": b"\xff",
        "ctx": {"error": ValueError("x")},
    }
    assert _error_without_input(error) == {
        "type": "model_attributes_type",
        "loc": ["body", 0, "b'\\xff'"],
        "msg": "Input should be a valid dictionary",
    }
