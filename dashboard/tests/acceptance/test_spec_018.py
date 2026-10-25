"""Acceptance tests for SPEC-018 (qc-dashboard: the "Dispositivos" page).

Written by the tester from the SPEC acceptance criteria. Covers CA-12. Tests named
``test_extra_*`` are exploratory edge cases around SPEC-018 section 4.5 (client, cache, page,
R-06 badge) that no CA spells out.

Pages are driven through ``streamlit.testing.v1.AppTest``; only the HTTP boundary is mocked
(``api.get_client`` returns a real ``ApiClient`` over ``httpx.MockTransport`` with contract
bodies). Read keys are generated at run time (R-03). No test touches the network nor runs pytest
in a subprocess (``docs/architecture.md`` section 10).
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from qc_contracts import SOURCE_LABELS_PT, DeviceStatus, Source
from qc_dashboard import api, data, formatting
from qc_dashboard.api import ApiClient

pytestmark = pytest.mark.acceptance

DASHBOARD = Path(__file__).resolve().parents[2]
PAGE = DASHBOARD / "views" / "dispositivos.py"
APP = DASHBOARD / "app.py"
BASE = "https://api.test"
PREFIX = "/api/v1"
SHA = "e" * 64
CONFIG_VARS = ("API_BASE_URL", "READ_API_KEY", "MODEL_METRICS_PATH")
BADGE = "Contém dados simulados"
COLUMNS = [
    "Dispositivo",
    "Situação",
    "Origem",
    "Último sinal",
    "Modelo",
    "Versão",
    "Pendentes",
    "Com falha",
    "Ligado há",
]


def device(**overrides: Any) -> DeviceStatus:
    values: dict[str, Any] = {
        "device_id": "edge-01",
        "last_seen_at": "2026-11-02T13:00:00Z",
        "last_heartbeat_at": "2026-11-02T13:00:00Z",
        "online": True,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": SHA,
        "app_version": "0.0.0",
        "uptime_s": 7500,
        "outbox_pending": 2,
        "outbox_dead": 1,
        "last_source": "simulated",
    }
    values.update(overrides)
    return DeviceStatus.model_validate(values)


def silent(**overrides: Any) -> DeviceStatus:
    """A device that never sent a heartbeat (and has no inspection)."""
    values: dict[str, Any] = {
        "device_id": "edge-02",
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
    return device(**values)


class FakeApi:
    def __init__(self, items: list[DeviceStatus]) -> None:
        self.items = items
        self.requests: list[httpx.Request] = []
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == f"{PREFIX}/devices":
            if self.status != 200:
                return httpx.Response(self.status, json={"detail": "nope"})
            return httpx.Response(200, json=[i.model_dump(mode="json") for i in self.items])
        return httpx.Response(404, json={"detail": "Not Found"})

    def device_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == f"{PREFIX}/devices"]


class NoSecretsFile:
    def __contains__(self, key: object) -> bool:
        raise FileNotFoundError("No secrets found")

    def __getitem__(self, key: str) -> object:
        raise FileNotFoundError("No secrets found")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    for name in CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(st, "secrets", NoSecretsFile())
    st.cache_data.clear()
    st.cache_resource.clear()
    yield
    st.cache_data.clear()
    st.cache_resource.clear()


@pytest.fixture
def key() -> str:
    return f"k-{secrets.token_hex(8)}"


def install(monkeypatch: pytest.MonkeyPatch, fake: FakeApi, key: str) -> None:
    client = ApiClient(BASE, key, transport=httpx.MockTransport(fake.handler))
    monkeypatch.setattr(api, "get_client", lambda: client)


def run_page(path: Path = PAGE) -> AppTest:
    at = AppTest.from_file(str(path), default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def page_text(at: AppTest) -> str:
    parts: list[str] = []
    for kind in ("warning", "info", "error", "caption", "markdown", "title", "success"):
        parts.extend(str(el.value) for el in getattr(at, kind))
    parts.extend(str(el.value) for el in at.sidebar.caption)
    return "\n".join(parts)


def table_rows(at: AppTest) -> list[dict[str, Any]]:
    frames = [el.value for el in [*at.dataframe, *at.table]]
    assert len(frames) == 1, frames
    return frames[0].to_dict("records")


# --------------------------------------------------------------------------- CA-12


def test_ca12_online_simulated_device_row() -> None:
    first, _ = formatting.device_rows([device(), silent()])
    assert first["Situação"] == "online"
    assert first["Origem"] == "simulado"
    assert first["Ligado há"] == "2 h 05 min"


def test_ca12_device_without_heartbeat_row() -> None:
    _, second = formatting.device_rows([device(), silent()])
    assert second["Situação"] == "offline"
    assert second["Último sinal"] == "nunca"
    assert second["Ligado há"] == "—"


# --------------------------------------------------------------------------- extras: rows


def test_extra_rows_have_the_spec_columns_as_text() -> None:
    rows = formatting.device_rows([device(), silent()])
    for row in rows:
        assert list(row) == COLUMNS
        assert all(isinstance(v, str) for v in row.values())
    first, second = rows
    assert first["Dispositivo"] == "edge-01"
    assert first["Modelo"] == "partqc-mnv3-v1"
    assert first["Versão"] == "0.0.0"
    assert first["Pendentes"] == "2"
    assert first["Com falha"] == "1"
    assert first["Último sinal"] not in ("nunca", "—", "")
    assert second["Origem"] == "—"


def test_extra_origin_uses_the_pt_labels() -> None:
    for source in Source:
        (row,) = formatting.device_rows([device(last_source=source.value)])
        assert row["Origem"] == SOURCE_LABELS_PT[source]
    (row,) = formatting.device_rows([device(last_source="live")])
    assert row["Origem"] == "real"


def test_extra_last_signal_is_local_time() -> None:
    """13:00 UTC is 10:00 in America/Sao_Paulo (UTC-3, no DST in 2026)."""
    (row,) = formatting.device_rows([device(last_heartbeat_at="2026-11-02T13:00:00Z")])
    assert "10:00" in row["Último sinal"]
    assert "13:00" not in row["Último sinal"]


def test_extra_offline_device_that_had_a_heartbeat() -> None:
    (row,) = formatting.device_rows([device(online=False)])
    assert row["Situação"] == "offline"
    assert row["Último sinal"] not in ("nunca", "—")


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0 h 00 min"),
        (59, "0 h 00 min"),
        (60, "0 h 01 min"),
        (3599, "0 h 59 min"),
        (3600, "1 h 00 min"),
        (7500, "2 h 05 min"),
        (90000, "25 h 00 min"),
    ],
)
def test_extra_uptime_format(seconds: int, text: str) -> None:
    (row,) = formatting.device_rows([device(uptime_s=seconds)])
    assert row["Ligado há"] == text


def test_extra_empty_list_has_no_rows() -> None:
    assert formatting.device_rows([]) == []


# ------------------------------------------------------------------- extras: client and cache


def test_extra_client_reads_the_devices_with_the_read_key(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    fake = FakeApi([device(), silent()])
    client = ApiClient(BASE, key, transport=httpx.MockTransport(fake.handler))
    items = client.devices()
    assert [i.device_id for i in items] == ["edge-01", "edge-02"]
    assert all(isinstance(i, DeviceStatus) for i in items)
    (request,) = fake.requests
    assert request.method == "GET"
    assert request.url.path == f"{PREFIX}/devices"
    assert request.headers["X-API-Key"] == key


def test_extra_fetch_devices_is_cached(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    fake = FakeApi([device()])
    install(monkeypatch, fake, key)
    first = data.fetch_devices()
    second = data.fetch_devices()
    assert [i.device_id for i in first] == [i.device_id for i in second] == ["edge-01"]
    assert len(fake.device_requests()) == 1


# --------------------------------------------------------------------------- extras: page


def test_extra_page_shows_the_table_and_the_simulated_badge(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    install(monkeypatch, FakeApi([device(), silent()]), key)
    at = run_page()
    rows = table_rows(at)
    assert [r["Dispositivo"] for r in rows] == ["edge-01", "edge-02"]
    assert list(rows[0]) == COLUMNS
    assert [r["Situação"] for r in rows] == ["online", "offline"]
    assert rows[0]["Origem"] == "simulado"
    assert rows[1]["Último sinal"] == "nunca"
    assert BADGE in [str(w.value) for w in at.warning]


def test_extra_page_without_simulated_device_has_no_badge(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    install(monkeypatch, FakeApi([device(last_source="live"), silent()]), key)
    at = run_page()
    assert BADGE not in page_text(at)
    assert [r["Origem"] for r in table_rows(at)] == ["real", "—"]


def test_extra_page_with_no_device(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    install(monkeypatch, FakeApi([]), key)
    at = run_page()
    assert [el.value for el in [*at.dataframe, *at.table]] == []
    assert at.info


@pytest.mark.parametrize("status", [401, 503])
def test_extra_page_api_error_shows_a_message_without_the_key(
    monkeypatch: pytest.MonkeyPatch, key: str, status: int
) -> None:
    fake = FakeApi([device()])
    fake.status = status
    install(monkeypatch, fake, key)
    at = run_page()
    assert at.error or at.warning  # 503 is the "API waking up" warning (SPEC-013)
    assert key not in page_text(at)
    assert [el.value for el in [*at.dataframe, *at.table]] == []


def test_extra_app_lists_the_dispositivos_page() -> None:
    source = APP.read_text(encoding="utf-8")
    assert "dispositivos.py" in source
    assert "Dispositivos" in source
    assert PAGE.is_file()


def test_extra_page_never_shows_raw_codes(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    install(monkeypatch, FakeApi([device(), device(device_id="edge-03", last_source="live")]), key)
    rows = table_rows(run_page())
    origins = {r["Origem"] for r in rows}
    assert origins == {"simulado", "real"}
    assert not origins & {"simulated", "live"}
    assert {r["Situação"] for r in rows} <= {"online", "offline"}


def test_extra_naive_time_is_never_produced() -> None:
    """The contract refuses a naive ``last_heartbeat_at`` (UTC with explicit offset)."""
    item = device(last_heartbeat_at=datetime(2026, 11, 2, 13, 0, tzinfo=UTC).isoformat())
    assert item.last_heartbeat_at is not None
    assert item.last_heartbeat_at.utcoffset() is not None
