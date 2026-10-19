"""HTTP publisher (SPEC-009 section 4.2): request shape, status mapping, refusal summary."""

from __future__ import annotations

import json
import secrets
import types
from typing import Any

import httpx
import pytest

from qc_contracts import BatchCreate
from qc_edge.publisher import (
    BATCH_PATH,
    HEALTH_PATH,
    HttpPublisher,
    PublishAuthError,
    PublishRejectedError,
    PublishResult,
    PublishTransientError,
    check_api_key,
    refusal_summary,
)

BASE = "https://cloud.test"


def device_key() -> str:
    """A fresh key built at run time (no literal credential in the repository)."""
    return "dk-" + secrets.token_urlsafe(24)


def publisher_for(handler: Any, key: str | None = None, base: str = BASE) -> HttpPublisher:
    return HttpPublisher(base, key or device_key(), transport=httpx.MockTransport(handler))


def respond(status: int, body: Any = None, content: bytes | None = None) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        if content is not None:
            return httpx.Response(status, content=content)
        return httpx.Response(status, json=body)

    return handler


# -- refusal summary -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (422, b'{"detail": "Value cannot be stored"}', "HTTP 422: Value cannot be stored"),
        (413, b'{"detail": "Request body too large"}', "HTTP 413: Request body too large"),
        (422, b'{"detail": [{"input": 1}, {"input": 2}]}', "HTTP 422: 2 validation errors"),
        (422, b'{"detail": []}', "HTTP 422: 0 validation errors"),
        (422, b"<html>bad</html>", "HTTP 422"),
        (413, b"", "HTTP 413"),
        (422, b'{"error": "x"}', "HTTP 422"),
        (422, b'{"detail": {"input": "x"}}', "HTTP 422"),
        (422, b'{"detail": 7}', "HTTP 422"),
        (422, b'["detail"]', "HTTP 422"),
        (422, b"\xff\xfe", "HTTP 422"),
        (422, b"[" * 100_000, "HTTP 422"),
    ],
)
def test_refusal_summary(status: int, body: bytes, expected: str) -> None:
    assert refusal_summary(status, body) == expected


def test_refusal_summary_cuts_and_replaces_control_characters() -> None:
    detail = "a\nb\tc\x00d\x7fe\x85f" + "z" * 300
    summary = refusal_summary(422, json.dumps({"detail": detail}).encode())
    assert summary == "HTTP 422: a?b?c?d?e?f" + "z" * (200 - 11)
    assert len(summary) == len("HTTP 422: ") + 200


# -- request shape -------------------------------------------------------------------------------


def test_publish_batch_request_and_results(fake_cloud: types.ModuleType) -> None:
    seen: list[httpx.Request] = []
    items = [fake_cloud.make_inspection() for _ in range(3)]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        results = [
            {"inspection_id": str(item.inspection_id), "status": status}
            for item, status in zip(items, ("created", "duplicate", "created"), strict=True)
        ]
        return httpx.Response(200, json={"results": results})

    key = device_key()
    results = publisher_for(handler, key, base=BASE + "/").publish_batch(items)
    assert results == [
        PublishResult(items[0].inspection_id, "created"),
        PublishResult(items[1].inspection_id, "duplicate"),
        PublishResult(items[2].inspection_id, "created"),
    ]
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == BASE + BATCH_PATH
    assert request.headers["x-api-key"] == key
    assert request.headers["content-type"] == "application/json"
    body = json.loads(request.content)
    assert BatchCreate.model_validate(body).items == items
    assert body == json.loads(BatchCreate(items=items).model_dump_json())
    assert set(body["items"][0]) == set(items[0].model_dump())


def test_a_201_with_a_valid_result_is_a_success(fake_cloud: types.ModuleType) -> None:
    item = fake_cloud.make_inspection()
    body = {"results": [{"inspection_id": str(item.inspection_id), "status": "created"}]}
    assert publisher_for(respond(201, body)).publish_batch([item])[0].status == "created"


@pytest.mark.parametrize("size", [0, 101])
def test_batch_size_is_1_to_100(size: int, fake_cloud: types.ModuleType) -> None:
    items = [fake_cloud.make_inspection() for _ in range(size)]
    with pytest.raises(ValueError, match="1 to 100"):
        publisher_for(respond(200, {})).publish_batch(items)


# -- status mapping ------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors(status: int, fake_cloud: types.ModuleType) -> None:
    with pytest.raises(PublishAuthError, match=f"HTTP {status}"):
        publisher_for(respond(status, {"detail": "x"})).publish_batch(
            [fake_cloud.make_inspection()]
        )


@pytest.mark.parametrize("status", [413, 422])
def test_rejections_carry_only_the_summary(status: int, fake_cloud: types.ModuleType) -> None:
    marker = "marker-" + secrets.token_hex(8)
    body = {"detail": [{"type": "x", "loc": ["body"], "msg": "bad", "input": marker}]}
    with pytest.raises(PublishRejectedError) as excinfo:
        publisher_for(respond(status, body)).publish_batch([fake_cloud.make_inspection()])
    assert excinfo.value.detail == f"HTTP {status}: 1 validation errors"
    assert str(excinfo.value) == excinfo.value.detail
    assert marker not in repr(excinfo.value)


@pytest.mark.parametrize("status", [301, 400, 404, 409, 429, 500, 502, 503, 504])
def test_other_statuses_are_transient(status: int, fake_cloud: types.ModuleType) -> None:
    with pytest.raises(PublishTransientError, match=f"HTTP {status}"):
        publisher_for(respond(status, {"detail": "x"})).publish_batch(
            [fake_cloud.make_inspection()]
        )


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("timed out"),
        httpx.ConnectTimeout(""),
        httpx.RemoteProtocolError("peer closed"),
    ],
)
def test_network_errors_are_transient(error: Exception, fake_cloud: types.ModuleType) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(PublishTransientError) as excinfo:
        publisher_for(handler).publish_batch([fake_cloud.make_inspection()])
    assert type(error).__name__ in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_the_key_is_redacted_from_network_errors(fake_cloud: types.ModuleType) -> None:
    key = device_key()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refused while sending {request.headers['x-api-key']}")

    with pytest.raises(PublishTransientError) as excinfo:
        publisher_for(handler, key).publish_batch([fake_cloud.make_inspection()])
    assert key not in str(excinfo.value)
    assert "***" in str(excinfo.value)


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b'{"results": "x"}',
        b'{"results": [{"inspection_id": "nope", "status": "created"}]}',
        b'{"results": [{"inspection_id": "8c8c8c8c-8c8c-4c8c-8c8c-8c8c8c8c8c8c", "status": "?"}]}',
    ],
)
def test_malformed_responses_are_transient(content: bytes, fake_cloud: types.ModuleType) -> None:
    with pytest.raises(PublishTransientError, match="malformed"):
        publisher_for(respond(200, content=content)).publish_batch([fake_cloud.make_inspection()])


def test_results_must_match_the_items(fake_cloud: types.ModuleType) -> None:
    a, b = fake_cloud.make_inspection(), fake_cloud.make_inspection()

    def results(*ids: Any) -> dict[str, Any]:
        return {"results": [{"inspection_id": str(i), "status": "created"} for i in ids]}

    for body in (
        results(a.inspection_id),  # fewer
        results(b.inspection_id, a.inspection_id),  # other order
        results(a.inspection_id, a.inspection_id),  # other ids
        results(a.inspection_id, b.inspection_id, a.inspection_id),  # more
    ):
        with pytest.raises(PublishTransientError, match="does not match"):
            publisher_for(respond(200, body)).publish_batch([a, b])


# -- health --------------------------------------------------------------------------------------


def test_check_health() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "ok"})

    assert publisher_for(handler).check_health() is True
    (request,) = seen
    assert request.method == "GET"
    assert str(request.url) == BASE + HEALTH_PATH
    assert "x-api-key" not in request.headers
    assert publisher_for(respond(503, {"status": "degraded"})).check_health() is False
    assert publisher_for(respond(204)).check_health() is False


def test_check_health_network_error_is_false(caplog: pytest.LogCaptureFixture) -> None:
    key = device_key()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused " + key)

    with caplog.at_level("DEBUG"):
        assert publisher_for(handler, key).check_health() is False
    assert key not in caplog.text


# -- configuration -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://api.exemplo.org",
        "ftp://api.exemplo.org",
        "https://",
        "api.exemplo.org",
        "http://192.168.0.10:8001",
        "http://localhost.evil.org",
    ],
)
def test_url_is_https_except_local_hosts(url: str) -> None:
    with pytest.raises(ValueError):
        HttpPublisher(url, device_key())


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:9000", "http://localhost:8001", "https://api.exemplo.org"]
)
def test_accepted_urls(url: str) -> None:
    HttpPublisher(url, device_key()).close()


@pytest.mark.parametrize("key", ["", "with space", "accentué", "tab\tkey", "nl\n"])
def test_invalid_keys_are_refused_without_echo(key: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        check_api_key(key)
    if key:
        assert key not in str(excinfo.value)
    with pytest.raises(ValueError):
        HttpPublisher(BASE, key)


@pytest.mark.parametrize("timeout", [0, -1.0])
def test_timeout_must_be_positive(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        HttpPublisher(BASE, device_key(), timeout_s=timeout)


def test_default_timeout_is_5_seconds() -> None:
    publisher = HttpPublisher(BASE, device_key())
    try:
        assert publisher._client.timeout == httpx.Timeout(5.0)
    finally:
        publisher.close()
