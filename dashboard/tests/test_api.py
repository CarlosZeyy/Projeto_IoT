"""``qc_dashboard.api``: requests, error mapping and key secrecy (SPEC-013 section 4.1)."""

from __future__ import annotations

import logging
import pickle
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from qc_contracts import (
    HealthResponse,
    InspectionRead,
    LotSummary,
    MetricsSummary,
    Page,
    SpcResponse,
    TimeseriesPoint,
)
from qc_dashboard import api, config
from qc_dashboard.api import (
    ApiAuthError,
    ApiClient,
    ApiError,
    ApiUnavailable,
    Filters,
    InspectionPage,
)


def make_client(handler, key: str) -> tuple[ApiClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return ApiClient("https://api.test", key, transport=httpx.MockTransport(recording)), seen


def json_response(body: object) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, json=body)


def test_summary_request_and_model(factory) -> None:
    key = factory.new_key()
    body = factory.summary().model_dump(mode="json")
    client, seen = make_client(json_response(body), key)

    result = client.summary(Filters(source="live"))

    assert isinstance(result, MetricsSummary)
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert str(seen[0].url) == "https://api.test/api/v1/metrics/summary?source=live"
    assert seen[0].headers["X-API-Key"] == key


def test_base_url_trailing_slash_is_ignored(factory) -> None:
    body = factory.summary().model_dump(mode="json")
    seen: list[httpx.Request] = []
    client = ApiClient(
        "https://api.test/",
        factory.new_key(),
        transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, json=body)),
    )
    client.summary(Filters())
    assert str(seen[0].url) == "https://api.test/api/v1/metrics/summary"


def test_filters_to_query_with_every_field() -> None:
    local = timezone(timedelta(hours=-3))
    filters = Filters(
        source="simulated",
        from_=datetime(2026, 11, 1, 0, 0, tzinfo=local),
        to=datetime(2026, 11, 8, 0, 0, tzinfo=local),
        object_type="nut",
        lot_id="L-01",
        device_id="edge-01",
        grade="poor",
        defective=False,
    )
    assert filters.to_query() == {
        "source": "simulated",
        "from": "2026-11-01T03:00:00+00:00",
        "to": "2026-11-08T03:00:00+00:00",
        "object_type": "nut",
        "lot_id": "L-01",
        "device_id": "edge-01",
        "grade": "poor",
        "defective": "false",
    }
    assert Filters(defective=True).to_query() == {"defective": "true"}
    assert Filters().to_query() == {}


def test_filters_reject_invalid_values() -> None:
    with pytest.raises(ValueError):
        Filters(source="everything")
    with pytest.raises(ValueError):
        Filters(from_=datetime(2026, 11, 1))


def test_filters_are_hashable_and_equal_by_value() -> None:
    a = Filters(source="live", lot_id="L-1")
    b = Filters(source="live", lot_id="L-1")
    assert a == b
    assert hash(a) == hash(b)


def test_every_method_hits_its_route(factory) -> None:
    key = factory.new_key()
    item = factory.inspection().model_dump(mode="json")
    lot = LotSummary(
        lot_id="L-001",
        n=3,
        defects=1,
        unknown_count=0,
        started_at=datetime(2026, 11, 3, tzinfo=UTC),
        ended_at=datetime(2026, 11, 3, 1, tzinfo=UTC),
        sources=["live"],
    ).model_dump(mode="json")
    bodies = {
        "/api/v1/health": {
            "status": "ok",
            "db": "ok",
            "api_version": "0.1.0",
            "contract_version": "0.3.0",
        },
        "/api/v1/metrics/timeseries": [
            {"bucket_start": "2026-11-03T15:00:00Z", "total": 1, "defective": 0, "defect_rate": 0}
        ],
        "/api/v1/metrics/spc": factory.spc_response().model_dump(mode="json"),
        "/api/v1/inspections": {"items": [item], "total": 1, "limit": 25, "offset": 0},
        "/api/v1/lots": {"items": [lot], "total": 1, "limit": 50, "offset": 0},
    }
    client, seen = make_client(lambda r: httpx.Response(200, json=bodies[r.url.path]), key)

    assert isinstance(client.health(), HealthResponse)
    series = client.timeseries(Filters(source="live"), "day")
    assert isinstance(series[0], TimeseriesPoint)
    assert isinstance(client.spc("simulated", "nut", 20, 5, 10), SpcResponse)
    page = client.inspections(Filters(), 25, 50)
    assert isinstance(page, Page[InspectionRead])
    assert isinstance(page.items[0], InspectionRead)
    lots = client.lots(Filters(source="live"))
    assert isinstance(lots, Page[LotSummary])

    params = [dict(request.url.params) for request in seen]
    assert params[1] == {"source": "live", "bucket": "day"}
    assert params[2] == {
        "source": "simulated",
        "object_type": "nut",
        "baseline_lots": "20",
        "min_lot_size": "5",
        "max_points": "10",
    }
    assert params[3] == {"limit": "25", "offset": "50"}
    assert params[4] == {"source": "live"}
    assert all(request.headers["X-API-Key"] == key for request in seen)


def test_spc_without_object_type_omits_it(factory) -> None:
    body = factory.spc_response().model_dump(mode="json")
    client, seen = make_client(json_response(body), factory.new_key())
    client.spc("live", None, 20, 5, 100)
    assert "object_type" not in seen[0].url.params
    assert "from" not in seen[0].url.params


def test_default_timeout_is_ten_seconds(factory) -> None:
    client = ApiClient("https://api.test", factory.new_key())
    assert client.timeout == 10.0
    assert client._http.timeout == httpx.Timeout(10.0)


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("timed out"),
        httpx.ConnectTimeout("timed out"),
        httpx.ConnectError("refused"),
        httpx.RemoteProtocolError("closed"),
    ],
)
def test_transport_errors_are_unavailable(factory, error: Exception) -> None:
    def raising(request: httpx.Request) -> httpx.Response:
        error.request = request
        raise error

    client, _ = make_client(raising, factory.new_key())
    with pytest.raises(ApiUnavailable):
        client.summary(Filters())
    with pytest.raises(ApiUnavailable):
        client.spc("live", None, 20, 5, 100)


@pytest.mark.parametrize("status", [502, 503, 504])
def test_gateway_statuses_are_unavailable(factory, status: int) -> None:
    client, _ = make_client(lambda r: httpx.Response(status), factory.new_key())
    with pytest.raises(ApiUnavailable) as info:
        client.inspections(Filters(), 50, 0)
    assert info.value.status == status


@pytest.mark.parametrize("status", [401, 403])
def test_auth_statuses(factory, status: int) -> None:
    client, _ = make_client(
        lambda r: httpx.Response(status, json={"detail": "Invalid API key"}), factory.new_key()
    )
    with pytest.raises(ApiAuthError):
        client.summary(Filters())


@pytest.mark.parametrize("status", [400, 404, 422, 500])
def test_other_errors_keep_the_status(factory, status: int) -> None:
    error = httpx.Response(status, json={"detail": "x"})
    client, _ = make_client(lambda r: error, factory.new_key())
    with pytest.raises(ApiError) as info:
        client.summary(Filters())
    assert info.value.status == status
    assert not isinstance(info.value, ApiAuthError | ApiUnavailable)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"foo": 1}),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json=[1, 2]),
    ],
)
def test_invalid_body_is_api_error(factory, response: httpx.Response) -> None:
    client, _ = make_client(lambda r: response, factory.new_key())
    with pytest.raises(ApiError) as info:
        client.summary(Filters())
    assert info.value.status == 200


def test_key_never_in_logs_exceptions_or_repr(factory, caplog) -> None:
    key = factory.new_key()
    caplog.set_level(logging.DEBUG)
    body = factory.summary().model_dump(mode="json")
    ok, _ = make_client(json_response(body), key)
    ok.summary(Filters(source="live"))
    texts = [repr(ok)]
    for handler in (
        lambda r: httpx.Response(401),
        lambda r: httpx.Response(500),
        lambda r: httpx.Response(200, json={"foo": 1}),
    ):
        client, _ = make_client(handler, key)
        with pytest.raises(api.ApiClientError) as info:
            client.summary(Filters())
        texts += [str(info.value), repr(info.value)]

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client, _ = make_client(timeout, key)
    with pytest.raises(ApiUnavailable) as info:
        client.summary(Filters())
    texts += [str(info.value), repr(info.value)]
    assert info.value.__cause__ is None

    assert key not in caplog.text
    assert all(key not in text for text in texts)


def test_page_subclasses_survive_pickling(factory) -> None:
    page = InspectionPage(items=[factory.inspection()], total=1, limit=50, offset=0)
    restored = pickle.loads(pickle.dumps(page))
    assert restored == page
    assert isinstance(restored, Page[InspectionRead])


def test_get_client_reads_settings(monkeypatch, no_config_env, factory) -> None:
    key = factory.new_key()
    monkeypatch.setenv("API_BASE_URL", "https://api.example/")
    monkeypatch.setenv("READ_API_KEY", key)
    client = api.get_client()
    assert client.base_url == "https://api.example"
    assert client._http.headers["X-API-Key"] == key
    assert api.get_client() is client


def test_get_client_without_settings_raises_config_error(no_config_env) -> None:
    with pytest.raises(config.ConfigError) as info:
        api.get_client()
    assert "API_BASE_URL" in str(info.value)
