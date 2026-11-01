"""Acceptance tests for SPEC-040 (consolidated maintenance), dashboard part: CA-07 and CA-08.

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Tests named ``test_extra_*`` are exploratory edge cases around section 4.4.

The common context of the SPEC: ``AppTest`` of the overview page, ``READ_API_KEY`` generated in
the test, ``httpx.HTTPTransport.handle_request`` and ``socket.getaddrinfo`` spied (nothing leaves
the machine), a handler on the root logger and an isolated ``st.secrets``. CA-08 replaces
``is_secure_api_url`` on purpose, to exercise the defense in depth (SPEC-040 section 6).
"""

from __future__ import annotations

import logging
import secrets
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from qc_dashboard import api, config
from qc_dashboard.config import INSECURE_API_URL_MESSAGE, is_secure_api_url

pytestmark = pytest.mark.acceptance

DASHBOARD = Path(__file__).resolve().parents[2]
OVERVIEW = DASHBOARD / "views" / "visao_geral.py"
CONFIG_VARS = ("API_BASE_URL", "READ_API_KEY", "MODEL_METRICS_PATH")

ZWSP = "​"  # Cf
SHY = "­"  # Cf
LS = " "  # Zl
NBSP = " "  # Zs
# The 5 URLs of the common context, spelled with escapes (the bytes of the SPEC were checked).
REFUSED_URLS = (
    f"https://api.exa{ZWSP}mple.org",
    f"https://api.exa{SHY}mple.org",
    f"https://api.example.org{LS}x",
    f"https://api.exa{NBSP}mple.org",
    "https://xn--zz.com",
)
ACCEPTED_URLS = (
    "https://api.example.org",
    "https://api.example.org:8443/base",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
    "https://bücher.example.org",
)
DEFENSE_URLS = ("https://xn--zz.com", f"https://api.exa{ZWSP}mple.org")
NOT_VALID_MESSAGE = "API_BASE_URL is not a valid URL"


class NoSecretsFile:
    """Behaves like ``st.secrets`` when there is no ``secrets.toml`` anywhere."""

    def __contains__(self, key: object) -> bool:
        raise FileNotFoundError("No secrets found")

    def __getitem__(self, key: str) -> object:
        raise FileNotFoundError("No secrets found")


class Boundary:
    """What would have left the machine, and everything the root logger received."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.dns: list[Any] = []
        self.records: list[logging.LogRecord] = []
        self.answer: httpx.Response | None = None

    def log_text(self) -> str:
        formatter = logging.Formatter("%(name)s %(levelname)s %(message)s")
        return "\n".join(formatter.format(r) for r in self.records)


class _Collect(logging.Handler):
    def __init__(self, sink: Boundary) -> None:
        super().__init__(logging.DEBUG)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self.sink.records.append(record)


@pytest.fixture(autouse=True)
def boundary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Boundary]:
    spy = Boundary()

    def transport(self: Any, request: httpx.Request) -> httpx.Response:
        spy.requests.append(request)
        return spy.answer or httpx.Response(599, json={"detail": "network blocked in tests"})

    def getaddrinfo(*args: Any, **kwargs: Any) -> Any:
        spy.dns.append(args)
        raise OSError("DNS blocked in tests")

    for name in CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(st, "secrets", NoSecretsFile())
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", transport)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    handler = _Collect(spy)
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    st.cache_data.clear()
    st.cache_resource.clear()
    try:
        yield spy
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)
        st.cache_data.clear()
        st.cache_resource.clear()


def new_key() -> str:
    return "k-" + secrets.token_hex(16)


def tree_text(at: AppTest) -> str:
    """Every element of the page, with its proto (labels, values, hidden fields)."""
    parts: list[str] = []

    def walk(node: Any) -> None:
        parts.append(repr(node))
        proto = getattr(node, "proto", None)
        if proto is not None:
            parts.append(str(proto))
        children = getattr(node, "children", None)
        if children:
            for child in children.values():
                walk(child)

    walk(at._tree)
    return "\n".join(parts)


def overview(url: str, key: str, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("READ_API_KEY", key)
    monkeypatch.setenv("API_BASE_URL", url)
    return AppTest.from_file(str(OVERVIEW), default_timeout=60).run()


# =========================================================================== CA-07


@pytest.mark.parametrize("url", REFUSED_URLS, ids=ascii)
def test_ca07_url_httpx_cannot_build_is_refused(url: str) -> None:
    assert is_secure_api_url(url) is False


@pytest.mark.parametrize("url", REFUSED_URLS, ids=ascii)
def test_ca07_overview_shows_the_message_and_sends_nothing(
    url: str, boundary: Boundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = new_key()
    at = overview(url, key, monkeypatch)
    assert not at.exception, [e.value for e in at.exception]
    assert INSECURE_API_URL_MESSAGE in [str(e.value) for e in at.error]
    assert boundary.requests == []
    assert boundary.dns == []
    tree = tree_text(at)
    assert INSECURE_API_URL_MESSAGE in tree  # the walker does see the page
    assert key not in tree
    assert key not in boundary.log_text()


@pytest.mark.parametrize("url", ACCEPTED_URLS, ids=ascii)
def test_ca07_urls_accepted_today_stay_accepted(url: str, boundary: Boundary) -> None:
    assert is_secure_api_url(url) is True
    assert boundary.requests == []
    assert boundary.dns == []  # the check itself never touches the network


@pytest.mark.parametrize("url", ACCEPTED_URLS, ids=ascii)
def test_extra_ca07_accepted_urls_reach_the_settings(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = new_key()
    monkeypatch.setenv("READ_API_KEY", key)
    monkeypatch.setenv("API_BASE_URL", url)
    settings = config.get_settings()
    assert settings.api_base_url == url
    assert settings.read_api_key == key


@pytest.mark.parametrize("url", REFUSED_URLS, ids=ascii)
def test_extra_ca07_get_settings_message_has_only_the_variable_name(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = new_key()
    monkeypatch.setenv("READ_API_KEY", key)
    monkeypatch.setenv("API_BASE_URL", url)
    with pytest.raises(config.InsecureApiUrlError) as raised:
        config.get_settings()
    message = str(raised.value)
    assert "API_BASE_URL" in message
    assert url not in message
    assert "example" not in message
    assert "xn--" not in message
    assert key not in message


MORE_URLS = (
    "https://api.exa‍mple.org",  # ZWJ
    "https://api.exa﻿mple.org",  # BOM
    "https://api.exa‮mple.org",  # RLO
    "https://api.example.org x",  # Zp
    "https://api.exa　mple.org",  # ideographic space
    "https://xn--a.com",
    "https://xn--.com",
    "https://" + "a" * 64 + ".example.org",
    "https://" + "ä" * 64 + ".example.org",
    "https://a..example.org",
    "https://[::1",
    "https://[not-ipv6]/",
    "https://api.example.org:8443:1",
    "https://",
    "http://",
    "ftp://api.example.org",
    "https://api.example.org/\x00",
    "https://\udc80.example.org",
    "https://\U000e0001.example.org",
)


def _httpx_builds(url: str) -> bool:
    try:
        httpx.Request("GET", url)
    except (httpx.InvalidURL, ValueError):
        return False
    return True


@pytest.mark.parametrize("url", MORE_URLS + REFUSED_URLS + ACCEPTED_URLS, ids=ascii)
def test_extra_ca07_accepted_implies_httpx_builds_it(url: str, boundary: Boundary) -> None:
    """The property of section 4.4: nothing accepted fails later when the request is built."""
    if is_secure_api_url(url):
        assert _httpx_builds(url), ascii(url)
    assert boundary.requests == []
    assert boundary.dns == []


# A NUL cannot be in an environment variable, so it is only checked by the function above.
@pytest.mark.parametrize("url", [u for u in MORE_URLS if "\x00" not in u], ids=ascii)
def test_extra_ca07_overview_never_has_an_exception(
    url: str, boundary: Boundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever the value, the page shows a message or the unavailable state, no exception."""
    key = new_key()
    at = overview(url, key, monkeypatch)
    assert not at.exception, ascii(url)
    assert key not in tree_text(at)
    assert key not in boundary.log_text()


VIEWS = sorted((DASHBOARD / "views").glob("*.py"))


@pytest.mark.parametrize("view", VIEWS, ids=lambda p: p.stem)
@pytest.mark.parametrize("through_defense", [False, True], ids=["check", "defense"])
def test_extra_ca07_every_page_stays_up(
    view: Path, through_defense: bool, boundary: Boundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 4.4 names the overview; the other pages use the same client and must hold too."""
    if through_defense:
        monkeypatch.setattr(config, "is_secure_api_url", lambda _url: True)
    key = new_key()
    monkeypatch.setenv("READ_API_KEY", key)
    monkeypatch.setenv("API_BASE_URL", "https://xn--zz.com")
    at = AppTest.from_file(str(view), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert boundary.requests == []
    assert boundary.dns == []
    assert key not in tree_text(at)
    assert key not in boundary.log_text()


# =========================================================================== CA-08


def _read(client: api.ApiClient) -> Any:
    return client.summary(api.Filters())


@pytest.mark.parametrize("url", DEFENSE_URLS, ids=ascii)
def test_ca08_build_or_read_raises_the_config_error(
    url: str, boundary: Boundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = new_key()
    monkeypatch.setenv("READ_API_KEY", key)
    monkeypatch.setenv("API_BASE_URL", url)
    monkeypatch.setattr(config, "is_secure_api_url", lambda _url: True)
    with pytest.raises(config.InsecureApiUrlError) as raised:
        _read(api.get_client())
    message = str(raised.value)
    assert message == NOT_VALID_MESSAGE
    assert url not in message
    assert key not in message
    assert boundary.requests == []
    assert boundary.dns == []


def test_ca08_body_that_is_not_json_keeps_its_exception(
    boundary: Boundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("READ_API_KEY", new_key())
    monkeypatch.setenv("API_BASE_URL", "https://api.example.org")
    monkeypatch.setattr(config, "is_secure_api_url", lambda _url: True)
    boundary.answer = httpx.Response(200, text="not json")
    with pytest.raises(api.ApiError) as raised:
        _read(api.get_client())
    assert not isinstance(raised.value, config.ConfigError)
    assert raised.value.status == 200
    assert str(raised.value) == "invalid API response body (HTTP 200)"
    assert len(boundary.requests) == 1


READERS = {
    "health": lambda c: c.health(),
    "summary": lambda c: c.summary(api.Filters()),
    "timeseries": lambda c: c.timeseries(api.Filters(), "hour"),
    "spc": lambda c: c.spc("live", None, 20, 5, 100),
    "inspections": lambda c: c.inspections(api.Filters(), 10, 0),
    "lots": lambda c: c.lots(api.Filters()),
    "devices": lambda c: c.devices(),
}


@pytest.mark.parametrize("reader", READERS.values(), ids=READERS.keys())
def test_extra_ca08_every_reader_converts_the_failure(
    reader: Any, boundary: Boundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("READ_API_KEY", new_key())
    monkeypatch.setenv("API_BASE_URL", "https://xn--zz.com")
    monkeypatch.setattr(config, "is_secure_api_url", lambda _url: True)
    with pytest.raises(config.InsecureApiUrlError):
        reader(api.get_client())
    assert boundary.requests == []
    assert boundary.dns == []


@pytest.mark.parametrize("url", DEFENSE_URLS, ids=ascii)
def test_extra_ca08_page_shows_the_same_message_through_the_defense(
    url: str, boundary: Boundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "is_secure_api_url", lambda _url: True)
    key = new_key()
    at = overview(url, key, monkeypatch)
    assert not at.exception, [e.value for e in at.exception]
    assert INSECURE_API_URL_MESSAGE in [str(e.value) for e in at.error]
    assert boundary.requests == []
    assert boundary.dns == []
    assert key not in tree_text(at)
    assert url not in boundary.log_text()
    assert key not in boundary.log_text()


@pytest.mark.parametrize("url", DEFENSE_URLS, ids=ascii)
def test_extra_ca08_exception_chain_is_not_shown(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """``raise ... from None``: a logged traceback does not carry the URL through ``__cause__``."""
    monkeypatch.setenv("READ_API_KEY", new_key())
    monkeypatch.setenv("API_BASE_URL", url)
    monkeypatch.setattr(config, "is_secure_api_url", lambda _url: True)
    with pytest.raises(config.InsecureApiUrlError) as raised:
        _read(api.get_client())
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_extra_ca08_network_errors_are_still_unavailable(
    boundary: Boundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only building the request is converted; sending stays ``ApiUnavailable``."""

    def refuse(self: Any, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    monkeypatch.setenv("READ_API_KEY", new_key())
    monkeypatch.setenv("API_BASE_URL", "https://api.example.org")
    with pytest.raises(api.ApiUnavailable):
        _read(api.get_client())


def test_extra_ca08_read_keeps_the_key_header_and_the_timeout(
    boundary: Boundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``build_request`` + ``send`` must keep what ``get`` did: key, timeout, query."""
    key = new_key()
    monkeypatch.setenv("READ_API_KEY", key)
    monkeypatch.setenv("API_BASE_URL", "https://api.example.org")
    boundary.answer = httpx.Response(503)
    with pytest.raises(api.ApiUnavailable):
        api.get_client().lots(api.Filters(lot_id="L-1"))
    request = boundary.requests[-1]
    assert request.headers["x-api-key"] == key
    assert request.url.params["lot_id"] == "L-1"
    assert request.extensions["timeout"]["read"] == api.DEFAULT_TIMEOUT
