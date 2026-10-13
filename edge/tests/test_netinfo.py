"""detect_lan_ips (SPEC-007 section 4.3). The socket and getaddrinfo are simulated."""

from __future__ import annotations

import logging
import socket
from typing import Any

import pytest

from qc_edge import netinfo
from qc_edge.netinfo import detect_lan_ips, is_fallback


class _FakeSocket:
    def __init__(self, address: str | None, connected: list[Any]) -> None:
        self._address = address
        self._connected = connected
        self.closed = False

    def connect(self, target: Any) -> None:
        self._connected.append(target)
        if self._address is None:
            raise OSError("Network is unreachable")

    def getsockname(self) -> tuple[str, int]:
        assert self._address is not None
        return (self._address, 40000)

    def close(self) -> None:
        self.closed = True


def _patch(
    monkeypatch: pytest.MonkeyPatch, udp: str | None, hostname: list[str] | Exception
) -> list[Any]:
    connected: list[Any] = []

    def fake_socket(*args: Any, **kwargs: Any) -> _FakeSocket:
        return _FakeSocket(udp, connected)

    def fake_getaddrinfo(*args: Any, **kwargs: Any) -> list[Any]:
        if isinstance(hostname, Exception):
            raise hostname
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in hostname]

    monkeypatch.setattr(netinfo.socket, "socket", fake_socket)
    monkeypatch.setattr(netinfo.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(netinfo.socket, "gethostname", lambda: "notebook")
    return connected


def test_udp_probe_comes_first(monkeypatch: pytest.MonkeyPatch) -> None:
    connected = _patch(monkeypatch, "192.168.0.42", ["10.0.0.7", "192.168.0.42"])
    assert detect_lan_ips() == ["192.168.0.42", "10.0.0.7"]
    assert connected == [("10.254.254.254", 1)]


def test_fallback_to_hostname_filters_loopback_and_link_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, None, ["127.0.1.1", "169.254.3.3", "10.0.0.7"])
    assert detect_lan_ips() == ["10.0.0.7"]


def test_unspecified_and_duplicates_are_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, "0.0.0.0", ["10.0.0.7", "10.0.0.7", "not-an-ip"])
    assert detect_lan_ips() == ["10.0.0.7"]


def test_no_candidate_falls_back_to_loopback_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch(monkeypatch, None, OSError("no name"))
    with caplog.at_level(logging.WARNING, logger="qc_edge"):
        ips = detect_lan_ips()
    assert ips == ["127.0.0.1"]
    assert is_fallback(ips)
    assert "no LAN IPv4 address detected" in caplog.text


def test_only_loopback_candidates_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, "127.0.0.1", ["127.0.1.1"])
    assert detect_lan_ips() == ["127.0.0.1"]


def test_socket_creation_failure_is_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, None, ["192.168.43.10"])

    def broken_socket(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no sockets")

    monkeypatch.setattr(netinfo.socket, "socket", broken_socket)
    assert detect_lan_ips() == ["192.168.43.10"]


def test_is_fallback() -> None:
    assert not is_fallback(["10.0.0.7"])
    assert not is_fallback(["127.0.0.1", "10.0.0.7"])
