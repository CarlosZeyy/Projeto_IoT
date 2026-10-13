"""``hash_api_key`` and ``require_read_key`` (SPEC-004 section 4.3), without a database."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from qc_api.auth import hash_api_key, require_read_key
from qc_api.config import Settings

READ_KEY = "R" * 16 + "r" * 16
INVALID = {"detail": "Missing or invalid API key"}


def test_hash_api_key_known_vector() -> None:
    assert hash_api_key("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_hash_api_key_is_lowercase_hex_sha256_of_utf8() -> None:
    key = "chave-ção"
    digest = hash_api_key(key)
    assert digest == hashlib.sha256(key.encode("utf-8")).hexdigest()
    assert len(digest) == 64
    assert digest == digest.lower()


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.state.settings = Settings(DATABASE_URL="postgresql://localhost/x", READ_API_KEY=READ_KEY)

    @app.get("/read")
    def read(_: Annotated[None, Depends(require_read_key)]) -> dict[str, str]:
        return {"ok": "yes"}

    with TestClient(app) as test_client:
        yield test_client


def test_read_key_accepted(client: TestClient) -> None:
    response = client.get("/read", headers={"X-API-Key": READ_KEY})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-API-Key": ""},
        {"X-API-Key": "wrong"},
        {"X-API-Key": READ_KEY + "x"},
        {"X-API-Key": READ_KEY[:-1]},
        {"X-API-Key": READ_KEY.lower()},
        # Non-ASCII header value (latin-1): compare_digest on str would raise TypeError.
        {"X-API-Key": "é".encode("latin-1")},
    ],
)
def test_read_key_refused(client: TestClient, headers: dict) -> None:
    response = client.get("/read", headers=headers)
    assert response.status_code == 401
    assert response.json() == INVALID
