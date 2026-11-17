"""Acceptance tests for SPEC-047 (edge console visual, presentation only): CA-01 to CA-10.

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. CA-11 is manual (the human looks at the page) and has no automated test.
``test_extra_*`` tests are exploratory edge cases taken from SPEC §4.1/§4.2 that no CA spells out.

Common setup (SPEC §5): ``create_app`` with the stub (``stub-v0``), ``EDGE_PORT=8000``,
``EDGE_HOST=0.0.0.0``, ``qc_edge.netinfo.detect_lan_ips`` replaced by
``["192.168.0.42", "10.0.0.7"]`` (the network boundary), and the console read in process through
``httpx.ASGITransport`` from ``("127.0.0.1", 50000)`` with the base URL ``http://127.0.0.1:8000``.
The session token ``T`` is generated at run time. No server is started on the LAN, and there is
no network nor database. The TLS pair is the same fake pair the SPEC-019/043 acceptance tests use
(the console only checks that both files exist and the key is private).
"""

from __future__ import annotations

import asyncio
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from string import Template
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import qc_edge.netinfo
from qc_contracts import Grade, InspectionCreate, ObjectType
from qc_edge.app import TEMPLATES_DIR, create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import InferenceResult, StubInferencer
from qc_edge.sink import InMemorySink, SinkStats

pytestmark = pytest.mark.acceptance

PORT = 8000
LAN = ["192.168.0.42", "10.0.0.7"]
LAN_IP = LAN[0]
SESSION_HEADER = "X-Session-Token"
CONSOLE_FILE = TEMPLATES_DIR / "console.html"
FORBIDDEN_TEXT = "O console só abre no próprio notebook (http://127.0.0.1)."

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
    "TYPE_THRESHOLD",
    "UNUSABLE_THRESHOLD",
    "GRADE_REVIEW_THRESHOLD",
)

PLACEHOLDERS = {
    "device_id",
    "ip_warning",
    "qr_svg",
    "capture_url",
    "other_ips",
    "live_pairing",
    "model_state",
    "thresholds",
    "sink_pending",
    "sink_dead",
    "connectivity_code",
    "connectivity",
    "last_success_at",
    "live_latency",
    "dataset_dir",
    "rows",
    "coverage",
}

CONNECTIVITY_LABELS = {
    "online": "online",
    "offline": "offline",
    "auth_error": (
        "erro de autenticação (envio pausado: confira o DEVICE_API_KEY e reinicie o qc-edge)"
    ),
    "disabled": "desativada (nada é enviado à nuvem)",
}

GENERIC_FONTS = {"system-ui", "ui-sans-serif", "sans-serif", "ui-monospace", "monospace"}


# --------------------------------------------------------------------------- doubles


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


class FixedStatsSink:
    """Sink whose ``stats()`` is controlled by the test (SPEC §6, mocks)."""

    def __init__(self, pending: int, dead: int, connectivity: str) -> None:
        self._stats = SinkStats(
            pending=pending,
            dead=dead,
            last_success_at=datetime(2026, 11, 17, 12, 0, tzinfo=UTC),
            connectivity=connectivity,  # type: ignore[arg-type]
        )

    def put(self, inspection: InspectionCreate) -> None:
        raise AssertionError("the console stores nothing")

    def stats(self) -> SinkStats:
        return self._stats


def jpeg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 48), "steelblue").save(buf, format="JPEG")
    return buf.getvalue()


# --------------------------------------------------------------------------- fixtures


@dataclass
class Edge:
    tmp: Path
    token: str
    monkeypatch: pytest.MonkeyPatch

    def tls(self) -> None:
        cert = self.tmp / "cert.pem"
        key = self.tmp / "key.pem"
        cert.write_text("fake pem", encoding="utf-8")
        key.write_text("fake pem", encoding="utf-8")
        cert.chmod(0o644)
        key.chmod(0o600)
        self.monkeypatch.setenv("EDGE_TLS_CERT", str(cert))
        self.monkeypatch.setenv("EDGE_TLS_KEY", str(key))

    def app(self, sink: Any = None) -> Any:
        snk = sink if sink is not None else InMemorySink()
        return create_app(EdgeSettings(), StubInferencer(result()), snk)


@pytest.fixture
def edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Edge:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    token = secrets.token_urlsafe(30)
    monkeypatch.setenv("EDGE_PORT", str(PORT))
    monkeypatch.setenv("EDGE_HOST", "0.0.0.0")
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "edge-data"))
    monkeypatch.setenv("DATASET_DIR", str(tmp_path / "dataset"))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setattr(qc_edge.netinfo, "detect_lan_ips", lambda: list(LAN))
    return Edge(tmp=tmp_path, token=token, monkeypatch=monkeypatch)


def get(
    app: Any,
    path: str = "/",
    *,
    client: tuple[str, int] = ("127.0.0.1", 50000),
    base_url: str = f"http://127.0.0.1:{PORT}",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as c:
            return await c.get(path, headers=headers)

    return asyncio.run(go())


# --------------------------------------------------------------------------- template helpers


def template_text() -> str:
    return CONSOLE_FILE.read_text(encoding="utf-8")


def style_text() -> str:
    text = template_text()
    match = re.search(r"<style[^>]*>(.*?)</style>", text, flags=re.S | re.I)
    assert match, "no <style> in console.html"
    return re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.S)


def css_rules() -> list[tuple[list[str], dict[str, str]]]:
    """Innermost ``selector { declarations }`` blocks, with the selector list split by comma."""
    rules: list[tuple[list[str], dict[str, str]]] = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", style_text()):
        selectors = [" ".join(s.split()) for s in selector.split(",")]
        decls: dict[str, str] = {}
        for decl in body.split(";"):
            if ":" not in decl:
                continue
            prop, value = decl.split(":", 1)
            decls[prop.strip().lower()] = " ".join(value.split()).lower()
        rules.append((selectors, decls))
    return rules


def px(value: str) -> float | None:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)px", value.strip())
    return float(match.group(1)) if match else None


def font_size_ok(value: str) -> bool:
    value = value.replace("!important", "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(px|rem)", value)
    if not match:
        return False
    number, unit = float(match.group(1)), match.group(2)
    return number >= 18 if unit == "px" else number >= 1.125


def strip_tokens(page: str, token: str, *, live: bool) -> str:
    rest = page.replace(f"capture?t={token}", "")
    if live:
        rest = rest.replace(f"live?t={token}", "")
    return rest


def assert_page_headers(response: httpx.Response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"


# =========================================================================== CA-01


def test_ca01_no_external_resource_no_script_nothing_that_blinks() -> None:
    text = template_text()
    lower = text.lower()
    for piece in (
        "http://",
        "https://",
        "<script",
        "<link",
        "<img",
        "<iframe",
        "<object",
        "<embed",
        "@import",
        "@font-face",
        "url(",
    ):
        assert piece not in lower, piece
    assert text.count("<style") == 1
    assert text.count("</style>") == 1
    for piece in ("<details", "animation", "transition", "@keyframes", "prefers-color-scheme"):
        assert piece not in text, piece
    assert "filter" not in text


# =========================================================================== CA-02


def test_ca02_template_is_valid_with_exactly_the_17_placeholders() -> None:
    template = Template(template_text())
    assert template.is_valid()
    identifiers = template.get_identifiers()
    assert set(identifiers) == PLACEHOLDERS
    assert len(PLACEHOLDERS) == 17


# =========================================================================== CA-03


def test_ca03_texts_old_tests_rely_on_never_appear() -> None:
    text = template_text()
    for piece in (
        "loopback-warning",
        "no-lan-warning",
        "coverage-warning",
        "Outros IPs",
        "PROVISÓRIO",
        "provisório",
        "p95",
        "/live?",
        "capture?t=",
        "auth_error",
        "<svg",
        "L-0",
    ):
        assert piece not in text, piece
    assert "nenhum ip" not in text.lower()
    assert text.count('class="qr"') == 1
    assert text.count('data-connectivity="') == 1


# =========================================================================== CA-04


def test_ca04_style_rules() -> None:
    rules = css_rules()

    # body: font-size >= 18px or 1.125rem, on a rule whose selector is exactly "body"
    body_sizes = [d["font-size"] for sels, d in rules if sels == ["body"] and "font-size" in d]
    assert body_sizes, "no 'body' rule with font-size"
    assert font_size_ok(body_sizes[-1]), body_sizes

    # every font-family only has generic families
    families = [d["font-family"] for _, d in rules if "font-family" in d]
    assert families, "no font-family declared"
    for value in families:
        tokens = [t.strip() for t in value.replace("!important", "").split(",")]
        assert set(tokens) <= GENERIC_FONTS, value
    assert not re.search(r"(^|[;{\s])font\s*:", style_text()), "font: shorthand is not allowed"

    # .qr svg: width/height >= 260px and a white background
    qr_svg: dict[str, str] = {}
    for sels, d in rules:
        if ".qr svg" in sels:
            qr_svg.update(d)
    assert qr_svg, "no '.qr svg' rule"
    width, height = px(qr_svg.get("width", "")), px(qr_svg.get("height", ""))
    assert width is not None and width >= 260, qr_svg
    assert height is not None and height >= 260, qr_svg
    background = qr_svg.get("background", qr_svg.get("background-color", ""))
    assert background in {"#fff", "#ffffff", "white"}, qr_svg

    # tr.complete stays green
    assert any(
        any("tr.complete" in s for s in sels)
        and "#d7f2dd" in d.get("background", d.get("background-color", ""))
        for sels, d in rules
    ), "no tr.complete rule with background #d7f2dd"

    # badge selectors
    css = style_text()
    for selector in (
        "[data-connectivity=online]",
        "[data-connectivity=offline]",
        "[data-connectivity^=auth]",
        "[data-connectivity=disabled]",
        '[data-count="0"]',
    ):
        assert selector in css, selector


# =========================================================================== CA-05


def test_ca05_rendered_console_keeps_texts_and_gains_the_cards(edge: Edge) -> None:
    response = get(edge.app())
    assert response.status_code == 200
    page = response.text
    for piece in (
        '<html lang="pt-BR">',
        '<meta http-equiv="refresh" content="5">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>PartQC — console da borda</title>",
        "PartQC — console da borda (<span>",
        "<h2>Pareamento</h2>",
        "Leia o QR code com o celular na mesma rede ou abra:",
        "<h2>Estado</h2>",
        "<h2>Últimas inspeções desta sessão</h2>",
        "<h2>Cobertura do dataset</h2>",
        "<dt>Modelo</dt>",
        "<dt>Limiares de decisão</dt>",
        "<dt>Pendentes</dt>",
        "<dt>Com falha definitiva</dt>",
        "<dt>Conectividade com a nuvem</dt>",
        "<dt>Último envio</dt>",
        "<dt>Latência por quadro (vídeo ao vivo)</dt>",
        "<dt>Dataset (modo coleta)</dt>",
        "<thead><tr><th>Hora</th><th>Lote</th><th>Tipo</th><th>Grau</th></tr></thead>",
        '<table id="coverage">',
        '<p id="external-images">',
        "A página atualiza sozinha a cada 5 s.",
    ):
        assert piece in page, piece
    assert page.count("<style") == 1
    for piece in ("<script", "<link", "<img", "<iframe", "@import"):
        assert piece not in page, piece


# =========================================================================== CA-06


def test_ca06_counts_model_and_last_ten_inspections(edge: Edge) -> None:
    app = edge.app(InMemorySink())
    with TestClient(app) as client:
        for i in range(12):
            r = client.post(
                "/api/capture",
                headers={SESSION_HEADER: edge.token},
                data={"lot_id": f"L-{i:03d}", "mode": "inspect"},
                files={"image": ("foto.jpg", jpeg(), "image/jpeg")},
            )
            assert r.status_code == 200, r.text
        response = get(app)

    assert response.status_code == 200
    page = response.text
    assert '<dd data-count="12" id="sink-pending">12</dd>' in page
    assert '<dd data-count="0" id="sink-dead">0</dd>' in page
    assert re.search(r'id="model-thresholds">—<', page)
    assert "carregado: stub-v0 (sha256 000000000000)" in page

    rows = re.findall(r'<tr class="inspection"[^>]*>.*?</tr>', page, flags=re.S)
    assert len(rows) == 10
    lots = [re.search(r"L-\d{3}", row).group(0) for row in rows]  # type: ignore[union-attr]
    assert lots == [f"L-{i:03d}" for i in range(11, 1, -1)]


# =========================================================================== CA-07


@pytest.mark.parametrize("code", ["online", "offline", "auth_error", "disabled"])
def test_ca07_connectivity_and_count_badges(edge: Edge, code: str) -> None:
    response = get(edge.app(FixedStatsSink(pending=3, dead=2, connectivity=code)))
    assert response.status_code == 200
    page = response.text
    label = CONNECTIVITY_LABELS[code]
    assert f'<dd id="sink-connectivity" data-connectivity="{code}">{label}</dd>' in page
    assert page.count('data-connectivity="') == 1
    assert '<dd data-count="3" id="sink-pending">3</dd>' in page
    assert '<dd data-count="2" id="sink-dead">2</dd>' in page
    if code != "auth_error":
        assert "auth_error" not in page


# =========================================================================== CA-08


def test_ca08_one_qr_without_tls(edge: Edge) -> None:
    response = get(edge.app())
    assert response.status_code == 200
    page = response.text
    assert page.count("<svg") == 1
    assert page.count('class="qr"') == 1
    assert f"http://{LAN_IP}:{PORT}/capture?t={edge.token}" in page
    assert "/live?" not in page


def test_ca08_two_qrs_with_tls(edge: Edge) -> None:
    edge.tls()
    response = get(edge.app(), base_url=f"https://127.0.0.1:{PORT}")
    assert response.status_code == 200
    page = response.text
    assert page.count("<svg") == 2
    assert page.count('class="qr"') == 2
    assert 'id="live-qr"' in page
    assert f"https://{LAN_IP}:{PORT}/capture?t={edge.token}" in page
    assert f"https://{LAN_IP}:{PORT}/live?t={edge.token}" in page


# =========================================================================== CA-09


@pytest.mark.parametrize("tls", [False, True], ids=["no-tls", "tls"])
def test_ca09_token_only_in_the_pairing_urls(edge: Edge, tls: bool) -> None:
    scheme = "http"
    if tls:
        edge.tls()
        scheme = "https"
    response = get(edge.app(), base_url=f"{scheme}://127.0.0.1:{PORT}")
    assert response.status_code == 200
    assert edge.token in response.text  # sanity: the token is on the page at all
    rest = strip_tokens(response.text, edge.token, live=tls)
    assert edge.token not in rest


# =========================================================================== CA-10


@pytest.mark.parametrize(
    ("client", "base_url", "headers"),
    [
        (("192.168.0.50", 50000), f"http://{LAN_IP}:{PORT}", None),
        (("127.0.0.1", 50000), f"http://127.0.0.1:{PORT}", {"Host": f"attacker.example:{PORT}"}),
        (("127.0.0.1", 50000), f"http://127.0.0.1:{PORT}", {"X-Forwarded-For": "203.0.113.9"}),
    ],
    ids=["lan-client", "foreign-host", "x-forwarded-for"],
)
def test_ca10_refusals_keep_text_and_headers(
    edge: Edge,
    client: tuple[str, int],
    base_url: str,
    headers: dict[str, str] | None,
) -> None:
    response = get(edge.app(), client=client, base_url=base_url, headers=headers)
    assert response.status_code == 403
    assert FORBIDDEN_TEXT in response.text
    assert edge.token not in response.text
    assert "<style" not in response.text
    assert_page_headers(response)


def test_ca10_ip_parameter_with_markup_is_not_reflected(edge: Edge) -> None:
    response = get(edge.app(), "/?ip=<script>alert(1)</script>")
    assert response.status_code == 200
    assert "<script" not in response.text


def test_ca10_console_headers_on_200(edge: Edge) -> None:
    response = get(edge.app())
    assert response.status_code == 200
    assert_page_headers(response)
    assert "content-security-policy" not in response.headers
    assert "set-cookie" not in response.headers


# =========================================================================== extras (§4.1, §4.2)


def test_extra_every_dollar_is_a_placeholder() -> None:
    """§4.2 item 10: a stray ``$`` would make ``substitute`` raise on every request."""
    text = template_text()
    names = "|".join(sorted(PLACEHOLDERS, key=len, reverse=True))
    rest = re.sub(rf"\$(?:{names})(?![A-Za-z0-9_])|\$\{{(?:{names})\}}", "", text)
    assert "$" not in rest


def test_extra_qr_has_no_visual_effect_and_keeps_a_white_margin() -> None:
    """§4.2 item 4: no filter/opacity/transform/mix-blend-mode on .qr, and padding on .qr."""
    qr_decls: dict[str, str] = {}
    for sels, d in css_rules():
        if any(s == ".qr" or s.startswith(".qr ") for s in sels):
            for prop in ("filter", "opacity", "transform", "mix-blend-mode"):
                assert prop not in d, (sels, prop)
        if ".qr" in sels:
            qr_decls.update(d)
    assert "padding" in qr_decls, qr_decls
    background = qr_decls.get("background", qr_decls.get("background-color", ""))
    assert background in {"#fff", "#ffffff", "white"}, qr_decls


def test_extra_no_internal_scroll() -> None:
    """§4.2 item 7: no ``overflow: auto`` or ``scroll`` (position lost on each reload)."""
    for sels, d in css_rules():
        for prop in ("overflow", "overflow-x", "overflow-y"):
            value = d.get(prop, "")
            assert "auto" not in value and "scroll" not in value, (sels, prop, value)


def test_extra_complete_cells_are_not_overridden_by_the_zebra() -> None:
    """§4.2 item 6: the zebra must not override the green of ``tr.complete``."""
    for sels, d in css_rules():
        for sel in sels:
            if "nth-child" in sel and "complete" not in sel:
                bg = d.get("background", d.get("background-color"))
                # a zebra rule with a background must exclude the complete rows
                assert bg is None or ":not(.complete)" in sel, (sel, bg)


def test_extra_id_is_the_last_attribute_of_the_dd() -> None:
    """§4.1: the ``id`` is the last attribute before ``>`` (old regexes such as
    ``id="sink-pending">12<``), except ``sink-connectivity``, which is unchanged."""
    text = template_text()
    for dd_id in ("model-state", "model-thresholds", "sink-pending", "sink-dead"):
        assert re.search(rf'id="{dd_id}">\$', text), dd_id
    assert (
        '<dd id="sink-connectivity" data-connectivity="$connectivity_code">$connectivity</dd>'
        in text
    )
    assert '<dd data-count="$sink_pending" id="sink-pending">$sink_pending</dd>' in text
    assert '<dd data-count="$sink_dead" id="sink-dead">$sink_dead</dd>' in text


def test_extra_live_pairing_stays_inside_the_pairing_container() -> None:
    """§4.1: ``$live_pairing`` stays in the same container as ``<div class="qr">$qr_svg</div>``."""
    text = template_text()
    start = text.index('<div class="pairing">')
    qr = text.index('<div class="qr">$qr_svg</div>')
    live = text.index("$live_pairing")
    assert start < qr < live
    # the .pairing div is still open at $live_pairing: count div opens/closes in between
    between = text[start:live]
    assert between.count("<div") - between.count("</div>") >= 1


def test_extra_only_the_two_new_visible_texts(edge: Edge) -> None:
    """§4.1: exactly ``Pareamento`` and the 5 s note are new; the header is in the body."""
    page = get(edge.app()).text
    assert page.count("<h2>Pareamento</h2>") == 1
    assert page.count("A página atualiza sozinha a cada 5 s.") == 1
    assert "PartQC — console da borda (<span>" in page


def test_extra_long_auth_error_badge_can_wrap() -> None:
    """§7.2: the ~90-character auth_error label must wrap inside the card."""
    for sels, d in css_rules():
        if any("data-connectivity" in s or "sink-connectivity" in s for s in sels):
            assert d.get("white-space", "normal") not in {"nowrap", "pre"}, (sels, d)
