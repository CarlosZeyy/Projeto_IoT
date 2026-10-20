"""Acceptance tests for SPEC-029 (dashboard and simulator maintenance), dashboard part.

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One ``test_caNN_*`` per CA (CA-01 to CA-04 here; CA-05, the simulator one, is in
``scripts/tests/acceptance/test_spec_029.py``). ``test_extra_*`` are exploratory edge cases
around SPEC-029 section 4.

Only the HTTP boundary is mocked: ``api.get_client`` is replaced by a real ``ApiClient`` over
``httpx.MockTransport`` (CA-03), or the real factory runs and ``httpx.HTTPTransport`` is
intercepted (CA-04, because the URL check lives in ``config.get_settings()``). ``st.secrets`` is
replaced by an object without a secrets file, except in CA-01, where the real ``st.secrets`` of a
child process reads ``T/.streamlit/secrets.toml``. Keys and markers are generated at run time,
never literals (R-03). No test touches the network. CA-01 and CA-02 run pytest in a subprocess
with an explicit file path only (``test_spec_013.py``, which runs no pytest in a subprocess),
without the database (``docs/architecture.md`` section 10); CA-05 does the same in its file.
"""

from __future__ import annotations

import ast
import os
import re
import secrets
import shutil
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from qc_contracts import MetricsSummary, SpcResponse
from qc_dashboard import api, config
from qc_dashboard.api import ApiClient

pytestmark = pytest.mark.acceptance

DASHBOARD = Path(__file__).resolve().parents[2]
REPO_ROOT = DASHBOARD.parent
VIEWS = DASHBOARD / "views"
OVERVIEW = VIEWS / "visao_geral.py"
SPC_PAGE = VIEWS / "controle_estatistico.py"
SPEC013 = DASHBOARD / "tests" / "acceptance" / "test_spec_013.py"
SPEC013_REL = "dashboard/tests/acceptance/test_spec_013.py"

BASE = "https://api.test"
PREFIX = "/api/v1"
BADGE = "Contém dados simulados"
INSECURE = "Configuração inválida: API_BASE_URL precisa usar https://"
CONFIG_VARS = ("API_BASE_URL", "READ_API_KEY", "MODEL_METRICS_PATH")
# Removed from the child pytest environment (CA-01; RV-08 of reviews/SPEC-025/r3).
CHILD_ENV_DROP = (
    "CI",
    "TEST_DATABASE_URL",
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "PYTEST_CURRENT_TEST",
)
# Tests collected from test_spec_013.py on `main` at 3ed113c (before SPEC-029), measured with
# `uv run pytest --collect-only -q` and recorded in reviews/SPEC-029/r1-test-report.md.
SPEC013_COUNT_ON_MAIN = 118

# CA-04: the 7 refused values (SPEC-029 section 5, text after SPEC_ISSUE-01 and -02).
REFUSED_URLS = (
    "https://api.example.org:abc",
    "https://api.example.org:99999",
    "http://localhost:abc",
    "http://local\thost:8001",
    "https://api.exa\nmple.org",
    "https://api.example.org\x7f",
    "https://api.exa\x85mple.org",
)
ACCEPTED_URLS = (
    "https://api.example.org:8443",
    "https://api.example.org",
    "http://localhost:8001",
    "http://127.0.0.1",
)


def new_key() -> str:
    return f"k-{secrets.token_hex(8)}"


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in CHILD_ENV_DROP}


def redact(text: str, marker: str) -> str:
    """Child output for an assertion message, never with the marker in it."""
    return text.replace(marker, "<marker>")[-4000:]


# --- contract builders ----------------------------------------------------------------------


def make_summary(**overrides: Any) -> MetricsSummary:
    values: dict[str, Any] = {
        "total": 40,
        "defective": 5,
        "defect_rate": 0.125,
        "unknown_count": 3,
        "needs_review_count": 4,
        "by_grade": {"perfect": 5, "good": 10, "fair": 12, "poor": 3, "unusable": 2},
        "by_object_type": {"screw": 20, "nut": 17, "unknown": 3},
        "mean_type_confidence": 0.91,
        "mean_grade_score": 1.8456,
    }
    values.update(overrides)
    return MetricsSummary.model_validate(values)


def make_point(lot_id: str, n: int, defects: int, hour: int) -> dict[str, Any]:
    p_bar = 0.18
    sigma = (p_bar * (1 - p_bar) / n) ** 0.5
    ucl, lcl = min(1.0, p_bar + 3 * sigma), max(0.0, p_bar - 3 * sigma)
    p = defects / n
    start = datetime(2026, 11, 1, 12, tzinfo=UTC) + timedelta(hours=hour)
    return {
        "lot_id": lot_id,
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(minutes=40)).isoformat(),
        "n": n,
        "defects": defects,
        "p": p,
        "cl": p_bar,
        "ucl": ucl,
        "lcl": lcl,
        "out_of_control": p > ucl or p < lcl,
    }


def make_spc(**overrides: Any) -> SpcResponse:
    values: dict[str, Any] = {
        "baseline_lots": 20,
        "min_lot_size": 5,
        "source": "live",
        "p_bar": 0.18,
        "points": [make_point("L-001", 25, 4, 0), make_point("L-002", 40, 7, 1)],
        "excluded_lots": [],
        "message": None,
        "max_points": 100,
        "valid_lots_total": 2,
        "excluded_lots_total": 0,
    }
    values.update(overrides)
    return SpcResponse.model_validate(values)


# --- the HTTP boundary ----------------------------------------------------------------------


class FakeApi:
    """Answers the ``/api/v1`` read routes and records every request.

    ``spc_source`` forces the ``source`` of the SPC body (``None`` echoes the query, as the real
    API does); every response is a valid ``SpcResponse``.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.spc_source: str | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        params = request.url.params
        if path == f"{PREFIX}/metrics/summary":
            return httpx.Response(200, json=make_summary().model_dump(mode="json"))
        if path == f"{PREFIX}/metrics/timeseries":
            return httpx.Response(200, json=[])
        if path == f"{PREFIX}/metrics/spc":
            origin = self.spc_source or params["source"]
            body = make_spc(source=origin).model_dump(mode="json")
            SpcResponse.model_validate(body)
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"detail": "Not Found"})

    def to(self, route: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == PREFIX + route]

    def reset(self) -> None:
        self.requests.clear()


class NoSecretsFile:
    """Behaves like ``st.secrets`` when there is no ``secrets.toml`` anywhere."""

    def __contains__(self, key: object) -> bool:
        raise FileNotFoundError("No secrets found")

    def __getitem__(self, key: str) -> object:
        raise FileNotFoundError("No secrets found")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """No config from the environment or a local secrets file; clean Streamlit caches."""
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
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeApi:
    mock = FakeApi()
    client = ApiClient(BASE, new_key(), transport=httpx.MockTransport(mock.handler))
    monkeypatch.setattr(api, "get_client", lambda: client)
    return mock


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Every request the real ``httpx`` stack would put on the wire (none is sent)."""
    seen: list[httpx.Request] = []

    def no_network(self: Any, request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(599, json={"detail": "network blocked in tests"})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    return seen


# --- AppTest helpers --------------------------------------------------------------------------


def page(path: Path) -> AppTest:
    return AppTest.from_file(str(path), default_timeout=60)


def run(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def values(elements: Any) -> list[str]:
    return [str(e.value) for e in elements]


def badges(at: AppTest) -> list[str]:
    return [w for w in values(at.warning) if BADGE in w]


def spc_page_with_sidebar(option: str) -> AppTest:
    at = run(page(SPC_PAGE))
    if option != "Real":
        at.sidebar.radio(key="flt_source").set_value(option)
        run(at)
    return at


def _spc_sources(fake: FakeApi) -> list[str | None]:
    return [r.url.params.get("source") for r in fake.to("/metrics/spc")]


# =============================================================================================
# CA-01: test_spec_013.py passes and does not print the key with a local secrets file
# =============================================================================================


def _project_with_secrets(tmp_path: Path, marker: str) -> Path:
    project = tmp_path / "project"
    (project / ".streamlit").mkdir(parents=True)
    (project / ".streamlit" / "secrets.toml").write_text(
        f'API_BASE_URL = "http://localhost:8001"\nREAD_API_KEY = "{marker}"\n', "utf-8"
    )
    return project


def test_ca01_spec013_suite_passes_and_hides_key_with_local_secrets(tmp_path: Path) -> None:
    marker = f"m{secrets.token_hex(16)}"
    project = _project_with_secrets(tmp_path, marker)
    assert REPO_ROOT not in project.parents  # T is outside the repository

    # Sanity: in T the real st.secrets of a child process does read the marker, so the run
    # below would see the key if the SPEC-013 tests were not isolated from it.
    probe = subprocess.run(  # noqa: S603 (fixed interpreter and code, no shell)
        [
            sys.executable,
            "-c",
            "import sys, streamlit as st; print(st.secrets['READ_API_KEY'] == sys.argv[1])",
            marker,
        ],
        cwd=project,
        env=child_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert probe.stdout.strip() == "True", redact(probe.stderr, marker)

    child = subprocess.run(  # noqa: S603 (fixed interpreter and explicit file path, no shell)
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(SPEC013)],
        cwd=project,
        env=child_env(),
        capture_output=True,
        text=True,
        timeout=900,
    )
    # Booleans, so that a failure here does not print the marker in this run's output.
    leaked_stdout = marker in child.stdout
    leaked_stderr = marker in child.stderr
    assert not leaked_stdout, "the marker was printed on the child stdout"
    assert not leaked_stderr, "the marker was printed on the child stderr"
    assert child.returncode == 0, redact(child.stdout + child.stderr, marker)
    assert re.search(r"\b\d+ passed\b", child.stdout), redact(child.stdout, marker)


# =============================================================================================
# CA-02: the retry comment no longer mentions clearing the cache; same collection as main
# =============================================================================================


def _function_source(path: Path, name: str) -> str:
    source = path.read_text("utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node, padded=False)
            assert segment is not None
            # get_source_segment drops comments outside the node span only; comments inside the
            # body are part of the segment.
            return segment
    raise AssertionError(f"{name} not found in {path.name}")


def _collected(path: Path, *extra: str) -> list[str]:
    out = subprocess.run(  # noqa: S603 (fixed interpreter and explicit file path, no shell)
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *extra]
        + [str(path)],
        cwd=REPO_ROOT,
        env=child_env(),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert out.returncode == 0, out.stdout[-3000:] + out.stderr[-3000:]
    ids = [line for line in out.stdout.splitlines() if "::" in line]
    summary = re.search(r"(\d+) tests? collected", out.stdout)
    assert summary, out.stdout[-2000:]
    assert int(summary.group(1)) == len(ids)
    return [i.split("::", 1)[1] for i in ids]


def _main_ref() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    for ref in ("main", "origin/main"):
        found = subprocess.run(  # noqa: S603 (fixed git command, no shell)
            [git, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if found.returncode == 0:
            return ref
    return None


def test_ca02_retry_comment_updated_and_same_collection_as_main(tmp_path: Path) -> None:
    body = _function_source(SPEC013, "test_extra_retry_while_still_down_is_bounded")
    assert "clearing the cache" not in body
    assert "assert len(fake.requests) <= 2" in body  # the assertion itself did not change

    here = _collected(SPEC013)
    assert len(here) == SPEC013_COUNT_ON_MAIN

    # Same node ids as main, when the main branch is available (CI checks out a single commit).
    ref = _main_ref()
    if ref is None:
        return
    git = shutil.which("git")
    assert git
    old = subprocess.run(  # noqa: S603 (fixed git command, no shell)
        [git, "show", f"{ref}:{SPEC013_REL}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    copy = tmp_path / "dashboard" / "tests" / "acceptance" / "test_spec_013.py"
    copy.parent.mkdir(parents=True)
    copy.write_text(old, "utf-8")
    on_main = _collected(copy, "-c", str(REPO_ROOT / "pyproject.toml"), "--rootdir", str(tmp_path))
    assert len(here) == len(on_main)
    assert sorted(here) == sorted(on_main)


# =============================================================================================
# CA-03: the p chart badge also follows the returned origin (R-06)
# =============================================================================================


def test_ca03_badge_when_the_returned_chart_is_simulated(fake: FakeApi) -> None:
    # (a) sidebar 'Real', request source=live, the API answers source=simulated.
    fake.spc_source = "simulated"
    at = spc_page_with_sidebar("Real")
    assert _spc_sources(fake) and set(_spc_sources(fake)) == {"live"}
    assert len(badges(at)) == 1, values(at.warning)
    assert "Origem da carta: simulado" in values(at.caption)
    assert fake.to("/metrics/summary") == []

    # (b) the API answers source=live: no badge.
    st.cache_data.clear()
    fake.reset()
    fake.spc_source = "live"
    at = spc_page_with_sidebar("Real")
    assert set(_spc_sources(fake)) == {"live"}
    assert badges(at) == [], values(at.warning)
    assert "Origem da carta: real" in values(at.caption)
    assert fake.to("/metrics/summary") == []

    # (c) sidebar 'Simulado', the API answers source=simulated: exactly one badge.
    st.cache_data.clear()
    fake.reset()
    fake.spc_source = "simulated"
    at = spc_page_with_sidebar("Simulado")
    assert _spc_sources(fake)[-1] == "simulated"
    assert len(badges(at)) == 1, values(at.warning)
    assert "Origem da carta: simulado" in values(at.caption)
    assert fake.to("/metrics/summary") == []


# =============================================================================================
# CA-04: API_BASE_URL with an invalid port or a control character is refused (SEC-28-02)
# =============================================================================================


def test_ca04_malformed_url_is_refused_with_one_constant_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("READ_API_KEY", new_key())
    messages: list[str] = []
    for url in REFUSED_URLS:
        monkeypatch.setenv("API_BASE_URL", url)
        with pytest.raises(config.InsecureApiUrlError) as raised:
            config.get_settings()
        message = str(raised.value)
        assert "API_BASE_URL" in message, repr(url)
        assert url not in message, repr(url)
        assert "example.org" not in message, repr(url)
        messages.append(message)
    assert len(set(messages)) == 1, messages


@pytest.mark.parametrize("url", REFUSED_URLS, ids=ascii)
def test_ca04_malformed_url_stops_the_overview(
    url: str, monkeypatch: pytest.MonkeyPatch, sent: list[httpx.Request]
) -> None:
    monkeypatch.setenv("READ_API_KEY", new_key())
    monkeypatch.setenv("API_BASE_URL", url)
    at = page(OVERVIEW).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(e.startswith(INSECURE) for e in values(at.error)), values(at.error)
    assert sent == []


@pytest.mark.parametrize("url", ACCEPTED_URLS)
def test_ca04_valid_url_is_still_accepted(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    read_key = new_key()
    monkeypatch.setenv("READ_API_KEY", read_key)
    monkeypatch.setenv("API_BASE_URL", url)
    settings = config.get_settings()
    assert settings.api_base_url == url
    assert settings.read_api_key == read_key


# =============================================================================================
# Exploratory extras (SPEC-029 section 4)
# =============================================================================================


def test_extra_ca03_sidebar_all_returned_simulated_shows_one_badge(fake: FakeApi) -> None:
    """Sidebar 'Todos' keeps the chart 'Real' (SPEC-028); a simulated answer still gets a badge."""
    fake.spc_source = "simulated"
    at = spc_page_with_sidebar("Todos")
    assert set(_spc_sources(fake)) == {"live"}
    assert len(badges(at)) == 1, values(at.warning)
    assert fake.to("/metrics/summary") == []


def test_extra_ca03_chart_radio_real_with_simulated_answer(fake: FakeApi) -> None:
    """Chart radio back to 'Real' (sidebar 'Simulado') and a simulated answer: one badge."""
    fake.spc_source = "simulated"
    at = spc_page_with_sidebar("Simulado")
    st.cache_data.clear()
    fake.reset()
    at.radio(key="spc_source").set_value("Real")
    run(at)
    assert set(_spc_sources(fake)) == {"live"}
    assert len(badges(at)) == 1, values(at.warning)
    assert fake.to("/metrics/summary") == []


def test_extra_ca03_no_extra_spc_request(fake: FakeApi) -> None:
    """The returned-origin badge uses the SPC answer already read: one SPC request per render."""
    fake.spc_source = "simulated"
    run(page(SPC_PAGE))
    assert len(fake.to("/metrics/spc")) == 1
    assert {r.url.path for r in fake.requests} == {f"{PREFIX}/metrics/spc"}


def test_extra_ca03_badge_is_above_the_chart(fake: FakeApi) -> None:
    """Same slot as the requested-origin badge: the warning comes before the p chart."""
    fake.spc_source = "simulated"
    at = run(page(SPC_PAGE))
    kinds: list[str] = []
    for node in _walk(at.main):
        kind = getattr(node, "type", None)
        if kind == "warning" and BADGE in str(getattr(node, "value", "")):
            kinds.append("badge")
        elif kind == "plotly_chart":
            kinds.append("chart")
    assert "badge" in kinds and "chart" in kinds, kinds
    assert kinds.index("badge") < kinds.index("chart")


def _walk(node: Any) -> Iterator[Any]:
    yield node
    children = getattr(node, "children", None)
    if isinstance(children, dict):
        for key in sorted(children):
            yield from _walk(children[key])


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.org:-1",
        "https://api.example.org:65536",
        "https://api.example.org:1e3",
        "https://api.exa\x00mple.org",
        "https://api.exa\x1bmple.org",
        "https://api.exa\x9fmple.org",
        "https://api.example.org/p\tath",
        "http://127.0.0.1:abc",
    ],
    ids=ascii,
)
def test_extra_ca04_more_malformed_values_are_refused(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert config.is_secure_api_url(url) is False
    if "\x00" in url:
        return  # NUL cannot be put in an environment variable
    monkeypatch.setenv("READ_API_KEY", new_key())
    monkeypatch.setenv("API_BASE_URL", url)
    with pytest.raises(config.InsecureApiUrlError) as raised:
        config.get_settings()
    assert url not in str(raised.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.org:0",
        "https://api.example.org:65535",
        "https://api.example.org:443/",
        "https://api.example.org/path?q=1",
        "http://localhost",
        "https://bücher.example",
    ],
    ids=ascii,
)
def test_extra_ca04_edge_values_still_accepted(url: str) -> None:
    assert config.is_secure_api_url(url) is True


@pytest.mark.parametrize("edge", ["\n", "\t", "\r\n", " \x85"], ids=ascii)
def test_extra_ca04_control_only_at_the_edges_is_trimmed(
    edge: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC-029 section 4.3: an edge Cc that str.strip() removes is trimmed before the check."""
    monkeypatch.setenv("READ_API_KEY", new_key())
    monkeypatch.setenv("API_BASE_URL", f"https://api.example.org{edge}")
    assert config.get_settings().api_base_url == "https://api.example.org"


def test_extra_ca04_malformed_url_from_the_secrets_object(
    monkeypatch: pytest.MonkeyPatch, sent: list[httpx.Request]
) -> None:
    """Same refusal when the value comes from st.secrets instead of the environment."""
    values_ = {"API_BASE_URL": "https://api.example.org:99999", "READ_API_KEY": new_key()}

    class FakeSecrets:
        def __contains__(self, key: object) -> bool:
            return key in values_

        def __getitem__(self, key: str) -> object:
            return values_[key]

        def get(self, key: str, default: object = None) -> object:
            return values_.get(key, default)

    monkeypatch.setattr(st, "secrets", FakeSecrets())
    with pytest.raises(config.InsecureApiUrlError):
        config.get_settings()
    at = page(OVERVIEW).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(e.startswith(INSECURE) for e in values(at.error)), values(at.error)
    assert sent == []
