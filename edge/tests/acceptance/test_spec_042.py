"""Acceptance tests for SPEC-042, edge part (CA-08 and CA-09).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. The README is read from the repository; the page comes from the real ``create_app``
with a scripted inferencer and the in-memory sink, through the HTTP routes. The database is not
used. CA-01 to CA-07 are in ``tests/acceptance/test_spec_042.py``; CA-10 is a browser rehearsal
recorded in the test report; CA-11 is manual.

Tests named ``test_extra_*`` are exploratory edge cases that no CA spells out.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import InferenceError, ModelInfo
from qc_edge.sink import InMemorySink

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
README = ROOT / "edge" / "README.md"
AFTER = "### Depois da apresentação"
INSTALL = "### Instalar a CA nos celulares"
USE = "### Usar"
MKCERT_ERASE = 'rm -rf "$(mkcert -CAROOT)"'
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
    "EDGE_PUBLISHER",
    "EDGE_TLS_CERT",
    "EDGE_TLS_KEY",
)


# ========================================================================================== README


def headings(text: str) -> list[tuple[int, str]]:
    """Markdown headings as (line index, line), ignoring the ``#`` comments of code fences."""
    found: list[tuple[int, str]] = []
    fence = False
    for index, line in enumerate(text.splitlines()):
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence and re.match(r"#{1,6} ", line):
            found.append((index, line.strip()))
    return found


def section(text: str, title: str) -> str:
    """The body of the only section named ``title``, up to a heading of the same or higher level."""
    lines = text.splitlines()
    marks = headings(text)
    matches = [position for position, (_, line) in enumerate(marks) if line == title]
    assert len(matches) == 1, f"{title!r} appears {len(matches)} times among the headings"
    level = len(title) - len(title.lstrip("#"))
    start = marks[matches[0]][0]
    end = len(lines)
    for index, line in marks[matches[0] + 1 :]:
        if len(line) - len(line.lstrip("#")) <= level:
            end = index
            break
    return "\n".join(lines[start + 1 : end])


def numbered_steps(body: str) -> list[str]:
    """The numbered items of a section, in order, each with its continuation lines."""
    parts = re.split(r"(?m)^\d+\. ", body)
    return parts[1:]


@pytest.fixture
def readme() -> str:
    return README.read_text(encoding="utf-8")


def test_ca08_readme_after_the_presentation(readme: str) -> None:
    order = [line for _, line in headings(readme)]
    assert INSTALL in order
    assert AFTER in order
    assert USE in order
    assert order.index(INSTALL) < order.index(AFTER) < order.index(USE)

    body = section(readme, AFTER)
    for needed in (
        "iOS",
        "Android",
        "Credenciais do usuário",
        "Limpar credenciais",
        "mkcert -uninstall",
        "mkcert -CAROOT",
        "rootCA-key.pem",
        "EDGE_TLS_CERT",
        "EDGE_TLS_KEY",
        "edge/data/tls",
        "docs/dataset-protocol.md",
    ):
        assert needed in body, needed
    assert MKCERT_ERASE in body
    assert body.index("mkcert -uninstall") < body.index(MKCERT_ERASE)
    assert "Lote em uso" in section(readme, USE)


def test_extra_readme_steps_follow_the_spec_order(readme: str) -> None:
    """SPEC section 4.4: "com estes passos, nesta ordem"."""
    body = section(readme, AFTER)
    marks = [
        "rootCA-key.pem",
        "iOS",
        "Android",
        "mkcert -uninstall",
        MKCERT_ERASE,
        "rm -rf edge/data/tls",
        "EDGE_TLS_CERT",
        "docs/dataset-protocol.md",
    ]
    positions = [body.index(mark) for mark in marks]
    assert positions == sorted(positions), dict(zip(marks, positions, strict=True))


def test_extra_readme_warns_against_clearing_all_credentials(readme: str) -> None:
    body = section(readme, AFTER)
    line = next(item for item in body.splitlines() if "Limpar credenciais" in item)
    assert re.search(r"[Nn]ão use", line), line
    assert "mkcert" in section(readme, AFTER)


def test_extra_readme_explains_why_and_the_exit_code(readme: str) -> None:
    body = section(readme, AFTER)
    assert "sites públicos" in body
    steps = numbered_steps(body)
    assert len(steps) == 6, steps
    assert "código 2" in steps[4]


def test_extra_readme_use_steps_explain_the_lot(readme: str) -> None:
    """SPEC section 4.4: step 1 explains the line and the warning; step 3, the recorded lot."""
    steps = numbered_steps(section(readme, USE))
    assert len(steps) >= 3, steps
    assert "Lote em uso" in steps[0]
    assert "Enter" in steps[0]
    assert "faixa" in steps[2]
    assert "verde" in steps[2]
    assert "lote registrado" in steps[2]


# ============================================================================================ page


class Inferencer:
    """Never called by the GET routes; present because ``create_app`` needs one."""

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo("acc-model-v1", "a" * 64)

    def infer(self, image: Any) -> Any:
        raise InferenceError("not used by the page tests")


@pytest.fixture
def token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    value = secrets.token_urlsafe(30)
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "edge-data"))
    monkeypatch.setenv("DATASET_DIR", str(tmp_path / "dataset"))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", value)
    return value


@pytest.fixture
def client(token: str) -> Iterator[TestClient]:
    with TestClient(create_app(EdgeSettings(), Inferencer(), InMemorySink())) as started:
        yield started


def js_function(script: str, name: str) -> str:
    """A two-space-indented function of ``live.js``, up to its closing line (SPEC section 7)."""
    match = re.search(rf"(?ms)^  (?:async )?function {name}\(.*?^  }}$", script)
    assert match, f"function {name} not found with the two-space style of SPEC section 7"
    return match.group(0)


def test_ca09_page_shape(client: TestClient, token: str) -> None:
    page = client.get("/live", params={"t": token})
    script = client.get("/static/live.js")
    assert page.status_code == 200
    assert script.status_code == 200

    assert 'id="lot-in-use"' in page.text
    assert 'id="stage"' in page.text
    assert page.text.index('id="lot-in-use"') < page.text.index('id="stage"')

    for needed in (
        "Lote em uso: ",
        "nenhum",
        "pressione Enter para aplicar o lote digitado",
        'addEventListener("input", showLot)',
        "inspection.lot_id",
        "Lote: ",
    ):
        assert needed in script.text, needed
    assert "innerHTML" not in script.text


def test_extra_lot_line_is_empty_and_right_after_the_label(client: TestClient, token: str) -> None:
    """SPEC section 4.3: right after the lot ``<label>``, empty, with the ``status`` class."""
    page = client.get("/live", params={"t": token}).text
    assert re.search(r'</label>\s*<p id="lot-in-use" class="status"></p>', page), page


def test_extra_show_lot_runs_at_the_end_of_both_lot_functions(client: TestClient) -> None:
    """SPEC section 4.3: ``showLot()`` at the end of ``loadLot`` and of ``confirmLot``."""
    script = client.get("/static/live.js").text
    for name in ("loadLot", "confirmLot"):
        body = js_function(script, name)
        calls = body.rstrip().splitlines()
        assert calls[-2].strip() == "showLot();", (name, calls[-2:])


def test_extra_input_only_updates_the_text(client: TestClient) -> None:
    """SPEC section 7: ``showLot`` reads the field and does not confirm the lot."""
    script = client.get("/static/live.js").text
    body = js_function(script, "showLot")
    assert "textContent" in body
    assert "confirmLot" not in body
    assert "localStorage" not in body
    assert 'addEventListener("change", confirmLot)' in script


def test_extra_frames_still_do_not_read_the_field(client: TestClient) -> None:
    """SPEC section 7: ``send`` and ``tick`` keep ignoring ``lotField`` (rule of SPEC-019 §4.5)."""
    script = client.get("/static/live.js").text
    for name in ("send", "tick"):
        assert "lotField" not in js_function(script, name), name
