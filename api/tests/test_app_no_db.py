"""App behavior that does not need a reachable database (SPEC-004 sections 4.2 to 4.5).

The "app without database" points to a closed local port: no mock of the database.
"""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import qc_contracts
from qc_api.config import Settings
from qc_api.main import create_app


@pytest.fixture
def client(no_db_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(no_db_settings)) as test_client:
        yield test_client


def test_startup_does_not_fail_and_health_is_503(no_db_settings: Settings) -> None:
    started = time.monotonic()
    with TestClient(create_app(no_db_settings)) as client:
        response = client.get("/api/v1/health")
        elapsed = time.monotonic() - started
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "db": "error",
        "api_version": "0.1.0",
        "contract_version": qc_contracts.__version__,
    }
    assert elapsed < 10


def test_write_without_database_is_503(client: TestClient, make_payload) -> None:
    response = client.post(
        "/api/v1/inspections",
        json=make_payload(),
        headers={"X-API-Key": secrets.token_urlsafe(32)},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_missing_key_without_database_is_401(client: TestClient, make_payload) -> None:
    """A missing key is refused before the lookup, so the database is not needed."""
    response = client.post("/api/v1/inspections", json=make_payload())
    assert response.status_code == 401


def test_declared_body_over_limit_is_413_before_auth(client: TestClient) -> None:
    response = client.post(
        "/api/v1/inspections",
        content=b"{}",
        headers={"Content-Length": "300000", "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}


def test_max_body_bytes_comes_from_settings(settings_for, no_db_url: str) -> None:
    with TestClient(create_app(settings_for(no_db_url, MAX_BODY_BYTES=5))) as client:
        response = client.post("/api/v1/inspections", content=b"123456")
    assert response.status_code == 413


def test_no_cors_headers(client: TestClient) -> None:
    origin = {"Origin": "https://evil.example"}
    preflight = client.options(
        "/api/v1/inspections", headers={**origin, "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in preflight.headers
    simple = client.get("/openapi.json", headers=origin)
    assert simple.status_code == 200
    assert "access-control-allow-origin" not in simple.headers


def test_openapi_only_json_bodies_and_docs(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    for path in ("/api/v1/inspections", "/api/v1/inspections/batch"):
        assert list(spec["paths"][path]["post"]["requestBody"]["content"]) == ["application/json"]
    for operations in spec["paths"].values():
        for operation in operations.values():
            content = operation.get("requestBody", {}).get("content", {})
            assert "multipart/form-data" not in content
    assert client.get("/docs").status_code == 200


def test_multipart_upload_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/inspections",
        files={"image": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    assert response.status_code in {401, 422}


def test_logs_have_no_password(
    no_db_settings: Settings, fake_password: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with TestClient(create_app(no_db_settings)) as client:
        client.get("/api/v1/health")
    assert caplog.records
    assert any(record.name == "psycopg.pool" for record in caplog.records)
    for record in caplog.records:
        assert fake_password not in record.getMessage()
    assert fake_password not in caplog.text


def test_settings_loaded_from_environment_at_startup(
    monkeypatch: pytest.MonkeyPatch, no_db_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", no_db_url)
    monkeypatch.setenv("READ_API_KEY", "e" * 32)
    monkeypatch.setenv("MAX_BODY_BYTES", "4")
    app = create_app()  # nothing is read here
    monkeypatch.setenv("MAX_BODY_BYTES", "3")
    with TestClient(app) as client:
        assert app.state.settings.MAX_BODY_BYTES == 3
        assert client.post("/api/v1/inspections", content=b"1234").status_code == 413


def test_startup_fails_without_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("READ_API_KEY", raising=False)
    app = create_app()
    with pytest.raises(Exception, match="DATABASE_URL"), TestClient(app):
        pass
