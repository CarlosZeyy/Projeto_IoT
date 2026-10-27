"""Dispositivos (SPEC-018 §4.5): client method, cache, ``formatting.device_rows`` and the page.

Only the HTTP boundary is mocked (``httpx.MockTransport``, fixtures ``mock_api``/``factory``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from qc_contracts import DeviceStatus
from qc_dashboard import api, data, formatting

TIMEOUT = 30
BADGE = "Contém dados simulados"


def no_heartbeat(factory, **overrides) -> DeviceStatus:
    values = {
        "device_id": "sim-01",
        "last_seen_at": None,
        "last_heartbeat_at": None,
        "online": False,
        "model_version": None,
        "model_sha256": None,
        "app_version": None,
        "uptime_s": None,
        "outbox_pending": None,
        "outbox_dead": None,
        "last_source": None,
    }
    values.update(overrides)
    return factory.device_status(**values)


def page(factory) -> Path:
    return factory.views / "dispositivos.py"


def run(path: Path) -> AppTest:
    return AppTest.from_file(str(path), default_timeout=TIMEOUT).run()


def texts(elements) -> list[str]:
    return [element.value for element in elements]


# ---------- formatting ----------


def test_device_rows_online_simulated_and_without_heartbeat(factory) -> None:
    online = factory.device_status(
        last_source="simulated",
        uptime_s=7500,
        last_heartbeat_at=datetime(2026, 11, 3, 15, 4, tzinfo=UTC),
    )
    first, second = formatting.device_rows([online, no_heartbeat(factory)])
    assert first == {
        "Dispositivo": "edge-01",
        "Situação": "online",
        "Origem": "simulado",
        "Último sinal": "03/11/2026 12:04",
        "Modelo": "partqc-mnv3-v1",
        "Versão": "0.0.0",
        "Pendentes": "2",
        "Com falha": "1",
        "Ligado há": "2 h 05 min",
    }
    assert second == {
        "Dispositivo": "sim-01",
        "Situação": "offline",
        "Origem": "—",
        "Último sinal": "nunca",
        "Modelo": "—",
        "Versão": "—",
        "Pendentes": "—",
        "Com falha": "—",
        "Ligado há": "—",
    }
    assert tuple(first) == formatting.DEVICE_COLUMNS


def test_device_rows_offline_with_an_old_heartbeat_keeps_the_last_values(factory) -> None:
    (row,) = formatting.device_rows([factory.device_status(online=False, last_source="live")])
    assert row["Situação"] == "offline"
    assert row["Origem"] == "real"
    assert row["Último sinal"] != "nunca"


def test_device_rows_heartbeat_without_model(factory) -> None:
    item = factory.device_status(model_version=None, model_sha256=None)
    assert formatting.device_rows([item])[0]["Modelo"] == "—"


def test_last_signal_is_the_heartbeat_not_the_last_inspection(factory) -> None:
    item = no_heartbeat(factory, last_seen_at="2026-11-03T15:00:00Z", last_source="simulated")
    (row,) = formatting.device_rows([item])
    assert row["Último sinal"] == "nunca"
    assert row["Origem"] == "simulado"


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (None, "—"),
        (0, "0 h 00 min"),
        (59, "0 h 00 min"),
        (60, "0 h 01 min"),
        (3599, "0 h 59 min"),
        (3600, "1 h 00 min"),
        (7500, "2 h 05 min"),
        (90_000, "25 h 00 min"),
        (2_147_483_647, "596.523 h 14 min"),
    ],
)
def test_fmt_uptime(seconds: int | None, text: str) -> None:
    assert formatting.fmt_uptime(seconds) == text


def test_has_simulated_device(factory) -> None:
    assert not formatting.has_simulated_device([])
    assert not formatting.has_simulated_device([factory.device_status(), no_heartbeat(factory)])
    assert formatting.has_simulated_device(
        [factory.device_status(), no_heartbeat(factory, last_source="simulated")]
    )


# ---------- client and cache ----------


def test_client_devices_parses_the_contract(mock_api, factory) -> None:
    mock_api.devices = [factory.device_status(), no_heartbeat(factory)]
    items = api.get_client().devices()
    assert [item.device_id for item in items] == ["edge-01", "sim-01"]
    assert all(isinstance(item, DeviceStatus) for item in items)
    (request,) = mock_api.to("/devices")
    assert request.method == "GET"
    assert request.headers[api.API_KEY_HEADER]
    assert request.url.query == b""


def test_client_devices_invalid_body_is_api_error(mock_api) -> None:
    mock_api.failure = lambda request: httpx.Response(200, json=[{"device_id": 1}])
    with pytest.raises(api.ApiError):
        api.get_client().devices()


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, api.ApiAuthError), (503, api.ApiUnavailable), (500, api.ApiError)],
)
def test_client_devices_errors(mock_api, status: int, error: type[Exception]) -> None:
    mock_api.failure = lambda request: httpx.Response(status, json={"detail": "x"})
    with pytest.raises(error):
        api.get_client().devices()


def test_fetch_devices_is_cached(mock_api) -> None:
    first = data.fetch_devices()
    second = data.fetch_devices()
    assert first == second
    assert len(mock_api.to("/devices")) == 1


# ---------- page ----------


def test_page_shows_the_table(mock_api, factory) -> None:
    mock_api.devices = [factory.device_status(), no_heartbeat(factory)]
    at = run(page(factory))
    assert len(at.exception) == 0, texts(at.exception)
    assert at.title[0].value == "Dispositivos"
    frame = at.dataframe[0].value
    assert list(frame.columns) == list(formatting.DEVICE_COLUMNS)
    assert list(frame["Situação"]) == ["online", "offline"]
    assert list(frame["Ligado há"]) == ["2 h 05 min", "—"]
    assert BADGE not in texts(at.warning)
    assert len(mock_api.to("/devices")) == 1


def test_page_badge_with_a_simulated_device(mock_api, factory) -> None:
    mock_api.devices = [factory.device_status(), no_heartbeat(factory, last_source="simulated")]
    at = run(page(factory))
    assert len(at.exception) == 0
    assert BADGE in texts(at.warning)
    assert BADGE in texts(at.sidebar.caption)
    assert list(at.dataframe[0].value["Origem"]) == ["real", "simulado"]


def test_page_without_devices(mock_api, factory) -> None:
    mock_api.devices = []
    at = run(page(factory))
    assert len(at.exception) == 0
    assert "Nenhum dispositivo registrado." in texts(at.info)
    assert len(at.dataframe) == 0


def test_page_api_unavailable(mock_api, factory) -> None:
    mock_api.failure = lambda request: httpx.Response(503, json={"detail": "Database unavailable"})
    at = run(page(factory))
    assert len(at.exception) == 0
    assert any("API acordando" in text for text in texts(at.warning))
    assert len(at.dataframe) == 0


def test_page_without_configuration(factory, no_config_env) -> None:
    at = run(page(factory))
    assert len(at.exception) == 0
    assert any("Configuração ausente" in text for text in texts(at.error))


def test_app_lists_the_page(factory, mock_api) -> None:
    source = factory.app.read_text("utf-8")
    assert 'st.Page(VIEWS / "dispositivos.py", title="Dispositivos")' in source
    at = AppTest.from_file(str(factory.app), default_timeout=TIMEOUT).run()
    at.switch_page("views/dispositivos.py").run()
    assert len(at.exception) == 0, texts(at.exception)
    assert at.title[0].value == "Dispositivos"
