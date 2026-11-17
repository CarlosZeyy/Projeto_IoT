"""Console template rules: visual refresh with inline CSS only (SPEC-047 sections 4.1 to 4.3)."""

from __future__ import annotations

import re
from string import Template

import pytest
from fastapi.testclient import TestClient

from qc_edge import netinfo
from qc_edge.app import TEMPLATES_DIR, create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import StubInferencer
from qc_edge.sink import InMemorySink, SinkStats

LOCAL = ("127.0.0.1", 50000)
CONSOLE_URL = "http://127.0.0.1:8000"
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
# Section 4.2, item 9: old tests assert their absence (or their presence as proof of a state).
NEVER_IN_TEMPLATE = (
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
)
EXTERNAL_OR_SCRIPT = (
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
)
# Section 4.2, item 7 and 8: nothing that blinks or resets on the 5 s reload, light theme only.
FORBIDDEN_CSS = (
    "<details",
    "animation",
    "transition",
    "@keyframes",
    "prefers-color-scheme",
    "filter",
    "mix-blend-mode",
    "opacity",
    "transform",
)
GENERIC_FONTS = {"system-ui", "ui-sans-serif", "sans-serif", "ui-monospace", "monospace"}


@pytest.fixture(scope="module")
def source() -> str:
    return (TEMPLATES_DIR / "console.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css(source: str) -> str:
    match = re.search(r"<style>(.*?)</style>", source, re.S)
    assert match is not None
    return match.group(1)


def _rules(css: str) -> dict[str, str]:
    """Selector -> declarations of each rule (the template has no nested at-rules)."""
    return {selector.strip(): body for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)}


def _px(value: str) -> float:
    number = re.fullmatch(r"([\d.]+)(px|rem|em)", value.strip())
    assert number is not None, value
    return float(number.group(1)) * (1 if number.group(2) == "px" else 16)


def test_no_external_resource_nor_script(source: str):
    lowered = source.lower()
    for fragment in EXTERNAL_OR_SCRIPT:
        assert fragment not in lowered, fragment
    assert source.count("<style") == 1
    assert source.count("</style>") == 1


def test_nothing_that_blinks_on_reload(source: str):
    lowered = source.lower()
    for fragment in FORBIDDEN_CSS:
        assert fragment not in lowered, fragment
    assert not re.search(r"overflow[^;]*:\s*(auto|scroll)", lowered)


def test_placeholders_are_exactly_the_17_of_the_spec(source: str):
    template = Template(source)
    assert template.is_valid()
    assert set(template.get_identifiers()) == PLACEHOLDERS
    # Every "$" is a placeholder: a stray one would turn every console request into a 500.
    assert len(re.findall(r"\$", source)) == len(re.findall(r"\$[a-z_]+", source))


def test_texts_the_old_tests_rely_on_never_appear(source: str):
    for fragment in NEVER_IN_TEMPLATE:
        assert fragment not in source, fragment
    assert "nenhum ip" not in source.lower()
    assert source.count('class="qr"') == 1
    assert source.count('data-connectivity="') == 1


def test_fonts_are_only_generic_families(css: str):
    assert not re.search(r"(^|[;{\s])font\s*:", css)
    families = re.findall(r"font-family\s*:\s*([^;}]+)", css)
    assert families
    for value in families:
        tokens = {token.strip() for token in value.split(",")}
        assert tokens <= GENERIC_FONTS, value


def test_readable_on_a_projector(css: str):
    rules = _rules(css)
    body_size = re.search(r"font-size\s*:\s*([^;]+)", rules["body"])
    assert body_size is not None
    assert _px(body_size.group(1)) >= 18
    h1_size = re.search(r"font-size\s*:\s*([\d.]+)em", rules[".topbar h1"])
    assert h1_size is not None and float(h1_size.group(1)) > 1
    assert re.search(r"max-width\s*:\s*1200px", rules["main"])


def test_qr_keeps_its_size_and_white_background(css: str):
    rules = _rules(css)
    qr_svg = rules[".qr svg"]
    assert _px(re.search(r"width\s*:\s*([^;]+)", qr_svg).group(1)) >= 260
    assert _px(re.search(r"height\s*:\s*([^;]+)", qr_svg).group(1)) >= 260
    assert re.search(r"background\s*:\s*(#fff|#ffffff|white)\s*(;|$)", qr_svg)
    assert re.search(r"padding\s*:", rules[".qr"])


def test_complete_coverage_cells_stay_green(css: str):
    rules = _rules(css)
    complete = [body for selector, body in rules.items() if "tr.complete" in selector]
    assert any(re.search(r"background\s*:\s*#d7f2dd", body) for body in complete)
    zebra = [selector for selector in rules if "nth-child(even)" in selector]
    assert zebra and all(":not(.complete)" in selector for selector in zebra)


def test_badge_selectors_are_present(css: str):
    for selector in (
        "[data-connectivity=online]",
        "[data-connectivity=offline]",
        "[data-connectivity^=auth]",
        "[data-connectivity=disabled]",
        '[data-count="0"]',
    ):
        assert selector in css, selector


@pytest.fixture
def lan_ips(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    ips = ["192.168.0.42", "10.0.0.7"]
    monkeypatch.setattr(netinfo, "detect_lan_ips", lambda: list(ips))
    return ips


@pytest.mark.parametrize(
    ("connectivity", "label"),
    [
        ("online", "online"),
        ("offline", "offline"),
        (
            "auth_error",
            "erro de autenticação (envio pausado: confira o DEVICE_API_KEY e reinicie o qc-edge)",
        ),
        ("disabled", "desativada (nada é enviado à nuvem)"),
    ],
)
def test_rendered_console_has_the_cards_and_badges(
    settings: EdgeSettings, lan_ips: list[str], connectivity: str, label: str
):
    class _Sink(InMemorySink):
        def stats(self) -> SinkStats:
            return SinkStats(pending=3, dead=2, last_success_at=None, connectivity=connectivity)

    app = create_app(settings, StubInferencer(), _Sink())
    token = app.state.session_token
    response = TestClient(app, client=LOCAL, base_url=CONSOLE_URL).get("/")
    assert response.status_code == 200
    page = response.text
    for fragment in (
        '<header class="topbar">',
        "<h2>Pareamento</h2>",
        "<h2>Estado</h2>",
        '<table class="inspections">',
        '<table id="coverage">',
        "A página atualiza sozinha a cada 5 s.",
        '<dd data-count="3" id="sink-pending">3</dd>',
        '<dd data-count="2" id="sink-dead">2</dd>',
        f'<dd id="sink-connectivity" data-connectivity="{connectivity}">{label}</dd>',
    ):
        assert fragment in page, fragment
    assert page.count('data-connectivity="') == 1
    assert ("auth_error" in page) is (connectivity == "auth_error")
    assert page.count("<svg") == 1
    assert "<script" not in page
    # The first QR stays inside the pairing card, before the state card.
    assert page.index("<h2>Pareamento</h2>") < page.index("<svg") < page.index("<h2>Estado</h2>")
    # The token only appears in the pairing URL (R-03).
    assert page.replace("capture?t=" + token, "").count(token) == 0


def test_zero_counts_render_as_neutral_badges(settings: EdgeSettings, lan_ips: list[str]):
    app = create_app(settings, StubInferencer(), InMemorySink())
    page = TestClient(app, client=LOCAL, base_url=CONSOLE_URL).get("/").text
    assert '<dd data-count="0" id="sink-pending">0</dd>' in page
    assert '<dd data-count="0" id="sink-dead">0</dd>' in page
