"""Acceptance tests for SPEC-043, the ``edge/`` part: CA-13 to CA-15 (E2E-02).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. ``test_extra_*`` tests are exploratory edge cases that no CA spells out.

The console is read with ``httpx.ASGITransport`` from ``127.0.0.1`` (as in the SPEC-025 acceptance
tests), and ``qc_edge.netinfo.detect_lan_ips`` is the spied boundary. The session token is
generated at run time, and ``EDGE_DATA_DIR`` and ``DATASET_DIR`` live under ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

import qc_edge.netinfo
from qc_contracts import Grade, InspectionCreate, ObjectType
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import InferenceResult, StubInferencer
from qc_edge.sink import SinkStats

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
EDGE_README = ROOT / "edge" / "README.md"
PORT = 8000
LAN = ["192.168.0.42", "10.0.0.7"]
LOOPBACK_WARNING = (
    '<p class="warning" id="loopback-warning">A borda escuta só neste notebook (EDGE_HOST em '
    "loopback): o celular não vai conseguir abrir. Para parear, use EDGE_HOST=0.0.0.0 e reinicie "
    "o qc-edge.</p>"
)
EDGE_ENV_VARS = (
    "EDGE_HOST",
    "EDGE_PORT",
    "EDGE_SESSION_TOKEN",
    "DEVICE_ID",
    "EDGE_DATA_DIR",
    "DEVICE_API_KEY",
    "CLOUD_API_URL",
    "MODEL_DIR",
    "DATASET_DIR",
    "OUTBOX_PATH",
    "EDGE_TLS_CERT",
    "EDGE_TLS_KEY",
)


class NullSink:
    def put(self, inspection: InspectionCreate) -> None:
        raise AssertionError("the console stores nothing")

    def stats(self) -> SinkStats:
        return SinkStats(pending=0, dead=0, last_success_at=None, connectivity="disabled")


def result() -> InferenceResult:
    return InferenceResult(
        object_type=ObjectType.SCREW,
        grade=Grade.GOOD,
        grade_score=1.2,
        type_confidence=0.93,
        grade_confidence=0.81,
        needs_review=False,
        latency_ms=17,
    )


@dataclass
class Edge:
    tmp: Path
    token: str
    monkeypatch: pytest.MonkeyPatch
    spy_calls: list[int]

    def host(self, value: str) -> None:
        self.monkeypatch.setenv("EDGE_HOST", value)

    def tls(self) -> None:
        cert = self.tmp / "cert.pem"
        key = self.tmp / "key.pem"
        cert.write_text("fake pem", encoding="utf-8")
        key.write_text("fake pem", encoding="utf-8")
        key.chmod(0o600)
        self.monkeypatch.setenv("EDGE_TLS_CERT", str(cert))
        self.monkeypatch.setenv("EDGE_TLS_KEY", str(key))

    def app(self) -> Any:
        return create_app(EdgeSettings(), StubInferencer(result()), NullSink())

    def lan(self, ips: list[str]) -> None:
        def spy() -> list[str]:
            self.spy_calls.append(1)
            return list(ips)

        self.monkeypatch.setattr(qc_edge.netinfo, "detect_lan_ips", spy)

    def get(self, app: Any, path: str = "/", *, scheme: str = "http") -> httpx.Response:
        async def go() -> httpx.Response:
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
            async with httpx.AsyncClient(
                transport=transport, base_url=f"{scheme}://127.0.0.1:{PORT}"
            ) as client:
                return await client.get(path)

        return asyncio.run(go())


@pytest.fixture
def edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Edge:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    token = secrets.token_urlsafe(30)
    monkeypatch.setenv("EDGE_PORT", str(PORT))
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "edge-data"))
    monkeypatch.setenv("DATASET_DIR", str(tmp_path / "dataset"))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    state = Edge(tmp=tmp_path, token=token, monkeypatch=monkeypatch, spy_calls=[])
    state.lan(LAN)
    return state


def assert_no_lan(text: str) -> None:
    for ip in LAN:
        assert ip not in text, ip
    assert "Outros IPs" not in text


# --------------------------------------------------------------------------- CA-13


@pytest.mark.parametrize("path", ["/", "/?ip=192.168.0.42"], ids=["plain", "forged-ip"])
def test_ca13_loopback_warns_and_offers_only_loopback(edge: Edge, path: str) -> None:
    edge.host("127.0.0.1")

    response = edge.get(edge.app(), path)

    assert response.status_code == 200, response.text
    body = response.text
    assert 'id="loopback-warning"' in body
    assert "EDGE_HOST=0.0.0.0" in body
    assert f"http://127.0.0.1:{PORT}/capture?t=" in body
    assert_no_lan(body)
    assert "no-lan-warning" not in body
    assert edge.spy_calls == []


def test_ca13_exact_warning_of_section_4_4(edge: Edge) -> None:
    edge.host("127.0.0.1")
    assert LOOPBACK_WARNING in edge.get(edge.app()).text


def test_ca13_with_tls_the_live_url_stays_on_loopback(edge: Edge) -> None:
    edge.host("127.0.0.1")
    edge.tls()

    response = edge.get(edge.app(), scheme="https")

    assert response.status_code == 200, response.text
    body = response.text
    assert f"https://127.0.0.1:{PORT}/live?t=" in body
    assert f"https://127.0.0.1:{PORT}/capture?t=" in body
    assert_no_lan(body)
    assert edge.spy_calls == []


# --------------------------------------------------------------------------- CA-14


def test_ca14_specific_host_offers_only_itself(edge: Edge) -> None:
    edge.host("192.168.0.99")

    response = edge.get(edge.app())

    assert response.status_code == 200, response.text
    body = response.text
    assert f"http://192.168.0.99:{PORT}/capture?t=" in body
    assert "loopback-warning" not in body
    assert "no-lan-warning" not in body
    assert_no_lan(body)
    assert edge.spy_calls == []


# --------------------------------------------------------------------------- CA-15


def test_ca15_all_interfaces_is_as_before(edge: Edge) -> None:
    edge.host("0.0.0.0")

    body = edge.get(edge.app()).text

    assert f"http://192.168.0.42:{PORT}/capture?t=" in body
    assert "Outros IPs" in body
    assert "10.0.0.7" in body
    assert "loopback-warning" not in body
    assert edge.spy_calls, "the console must use detect_lan_ips with 0.0.0.0"


def test_ca15_default_host_is_all_interfaces(edge: Edge) -> None:
    body = edge.get(edge.app()).text

    assert f"http://192.168.0.42:{PORT}/capture?t=" in body
    assert "Outros IPs" in body
    assert edge.spy_calls


def test_ca15_fallback_keeps_only_the_no_lan_warning(edge: Edge) -> None:
    edge.host("0.0.0.0")
    edge.lan(["127.0.0.1"])

    body = edge.get(edge.app()).text

    assert "no-lan-warning" in body
    assert "loopback-warning" not in body


def test_ca15_readme_line_of_edge_host() -> None:
    lines = [
        line
        for line in EDGE_README.read_text(encoding="utf-8").splitlines()
        if line.startswith("| `EDGE_HOST`")
    ]
    assert len(lines) == 1
    assert "0.0.0.0" in lines[0]
    assert "loopback" in lines[0]


# --------------------------------------------------------------------------- extras


@pytest.mark.parametrize(
    ("host", "warned"),
    [
        ("127.0.0.2", True),
        ("127.255.255.254", True),
        ("10.20.30.40", False),
        ("172.16.0.1", False),
        ("203.0.113.7", False),
    ],
)
def test_extra_table_of_section_4_4(edge: Edge, host: str, warned: bool) -> None:
    edge.host(host)

    body = edge.get(edge.app()).text

    assert f"http://{host}:{PORT}/capture?t=" in body
    assert ('id="loopback-warning"' in body) is warned
    assert "no-lan-warning" not in body
    assert_no_lan(body)
    assert edge.spy_calls == []


@pytest.mark.parametrize(
    "query",
    ["?ip=", "?ip=127.0.0.1", "?ip=<script>", "?ip=10.0.0.7&ip=192.168.0.42", "?ip=%00"],
)
def test_extra_ip_query_cannot_escape_the_listening_address(edge: Edge, query: str) -> None:
    edge.host("127.0.0.1")

    response = edge.get(edge.app(), "/" + query)

    assert response.status_code == 200
    assert f"http://127.0.0.1:{PORT}/capture?t=" in response.text
    assert "<script>" not in re.sub(r"<script\b[^>]*>.*?</script>", "", response.text, flags=re.S)
    assert_no_lan(response.text)


def test_extra_ip_query_still_selects_among_lan_addresses(edge: Edge) -> None:
    edge.host("0.0.0.0")

    body = edge.get(edge.app(), "/?ip=10.0.0.7").text

    assert f"http://10.0.0.7:{PORT}/capture?t=" in body
    assert "192.168.0.42" in body


def test_extra_ip_query_cannot_add_an_address_with_all_interfaces(edge: Edge) -> None:
    edge.host("0.0.0.0")

    body = edge.get(edge.app(), "/?ip=172.16.9.9").text

    assert f"http://192.168.0.42:{PORT}/capture?t=" in body
    assert "172.16.9.9" not in body


def test_extra_the_qr_follows_the_chosen_address(edge: Edge, monkeypatch: Any) -> None:
    """Section 4.4: the QR code has the same URL: two hosts give two different SVGs."""

    def svgs(host: str) -> list[str]:
        edge.host(host)
        body = edge.get(edge.app()).text
        return re.findall(r"<svg.*?</svg>", body, flags=re.S)

    loopback = svgs("127.0.0.1")
    other = svgs("192.168.0.99")
    assert loopback
    assert other
    assert loopback[0] != other[0]


def test_extra_console_ips_public_function(edge: Edge) -> None:
    from qc_edge.netinfo import console_ips

    assert console_ips("127.0.0.1") == ["127.0.0.1"]
    assert console_ips("192.168.0.99") == ["192.168.0.99"]
    assert edge.spy_calls == []
    assert console_ips("0.0.0.0") == LAN
    assert edge.spy_calls == [1]


def test_extra_each_render_recomputes_with_all_interfaces(edge: Edge) -> None:
    edge.host("0.0.0.0")
    app = edge.app()

    edge.get(app)
    edge.lan(["172.16.0.5"])
    body = edge.get(app).text

    assert f"http://172.16.0.5:{PORT}/capture?t=" in body


def test_extra_refused_host_header_still_comes_first(edge: Edge) -> None:
    """SPEC-025: the access rule does not change with a specific host."""
    edge.host("192.168.0.99")

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=edge.app(), client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://127.0.0.1:{PORT}"
        ) as client:
            return await client.get("/", headers={"Host": "attacker.example:8000"})

    assert asyncio.run(go()).status_code in {400, 403, 404, 421}
    assert edge.spy_calls == []


def test_extra_console_from_another_client_is_still_refused(edge: Edge) -> None:
    """SPEC-025: the console stays local even when EDGE_HOST is a LAN address."""
    edge.host("192.168.0.99")

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=edge.app(), client=("192.168.0.50", 50000))
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://192.168.0.99:{PORT}"
        ) as client:
            return await client.get("/")

    response = asyncio.run(go())
    assert response.status_code == 403
    assert edge.token not in response.text
