"""Acceptance tests for SPEC-040 (consolidated maintenance), infra part: CA-16 and CA-17.

Written by the tester from the SPEC acceptance criteria (black box), before reading the changed
files. CA-16 keeps a literal copy of the lines that are not comments, as the CA asks. Tests named
``test_extra_*`` are exploratory checks of the requirements of section 4.10 that the CA does not
spell out. CA-18 is manual (VPS and edge) and is recorded in the test report.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.acceptance]

REPO_ROOT = Path(__file__).resolve().parents[3]
API_DOCKERFILE = REPO_ROOT / "infra" / "docker" / "api.Dockerfile"
DASHBOARD_DOCKERFILE = REPO_ROOT / "infra" / "docker" / "dashboard.Dockerfile"
STREAMLIT_CONFIG = REPO_ROOT / ".streamlit" / "config.toml"
PLAN = REPO_ROOT / "docs" / "deployment-plan.md"
TITLE = "**Quando o merge traz migração nova ou contrato novo**"
COOLIFY_URL = "https://coolify.io/docs/knowledge-base/proxy/traefik/custom-middlewares"
TRAEFIK_URL = (
    "https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/compress/"
)

# Not comments in infra/docker/api.Dockerfile at the start of the round (cf92f79), copied literally.
API_DOCKERFILE_LINES = [
    "",
    "FROM python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1",  # noqa: E501
    "",
    "COPY --from=ghcr.io/astral-sh/uv:0.13.2@sha256:b9fddcde095a7aeafd499024adb8927df6619c7c5672f5ff7126474715f62ba4 /uv /uvx /bin/",  # noqa: E501
    "",
    "ENV UV_PYTHON_DOWNLOADS=0 \\",
    "    UV_COMPILE_BYTECODE=1 \\",
    "    UV_LINK_MODE=copy \\",
    "    UV_CACHE_DIR=/root/.cache/uv \\",
    "    PYTHONUNBUFFERED=1 \\",
    "    HOME=/home/app",
    "",
    "RUN groupadd --system --gid 10001 app \\",
    "    && useradd --system --uid 10001 --gid 10001 --home-dir /home/app --create-home \\",
    "       --shell /usr/sbin/nologin app",
    "",
    "WORKDIR /app",
    "COPY . /app",
    "",
    "RUN --mount=type=cache,target=/root/.cache/uv \\",
    "    uv sync --package qc-api --frozen --no-dev",
    "",
    'ENV PATH="/app/.venv/bin:$PATH"',
    "",
    'LABEL partqc.component="api"',
    "",
    "USER 10001:10001",
    "",
    "EXPOSE 8000",
    "",
    "HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \\",
    '    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen(\'http://127.0.0.1:8000/api/v1/health\', timeout=5).status == 200 else 1)"]',  # noqa: E501
    "",
    'CMD ["uvicorn", "qc_api.main:app", "--host", "0.0.0.0", "--port", "8000"]',
]

# Not comments in infra/docker/dashboard.Dockerfile at the start of the round (cf92f79), literal.
DASHBOARD_DOCKERFILE_LINES = [
    "",
    "FROM python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1",  # noqa: E501
    "",
    "COPY --from=ghcr.io/astral-sh/uv:0.13.2@sha256:b9fddcde095a7aeafd499024adb8927df6619c7c5672f5ff7126474715f62ba4 /uv /uvx /bin/",  # noqa: E501
    "",
    "ENV UV_PYTHON_DOWNLOADS=0 \\",
    "    UV_COMPILE_BYTECODE=1 \\",
    "    UV_LINK_MODE=copy \\",
    "    UV_CACHE_DIR=/root/.cache/uv \\",
    "    PYTHONUNBUFFERED=1 \\",
    "    HOME=/home/app",
    "",
    "RUN groupadd --system --gid 10001 app \\",
    "    && useradd --system --uid 10001 --gid 10001 --home-dir /home/app --create-home \\",
    "       --shell /usr/sbin/nologin app",
    "",
    "WORKDIR /app",
    "COPY . /app",
    "",
    "RUN --mount=type=cache,target=/root/.cache/uv \\",
    "    uv sync --package qc-dashboard --frozen --no-dev",
    "",
    'ENV PATH="/app/.venv/bin:$PATH"',
    "",
    'LABEL partqc.component="dashboard"',
    "",
    "USER 10001:10001",
    "",
    "EXPOSE 8501",
    "",
    "HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \\",
    '    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen(\'http://127.0.0.1:8501/_stcore/health\', timeout=5).status == 200 else 1)"]',  # noqa: E501
    "",
    'CMD ["streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.fileWatcherType=none"]',  # noqa: E501
]

# Not comments in .streamlit/config.toml at the start of the round (cf92f79), copied literally.
STREAMLIT_LINES = [
    "",
    "[browser]",
    "gatherUsageStats = false",
    "",
    "[server]",
    "headless = true",
    "",
    "[client]",
    'showErrorDetails = "none"',
]

FILES = {
    "api": (API_DOCKERFILE, API_DOCKERFILE_LINES),
    "dashboard": (DASHBOARD_DOCKERFILE, DASHBOARD_DOCKERFILE_LINES),
    "streamlit": (STREAMLIT_CONFIG, STREAMLIT_LINES),
}


def top_comment(path: Path) -> str:
    """The first lines of the file that start with ``#``."""
    block: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            break
        block.append(line)
    assert block, path
    return "\n".join(block)


def not_comments(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if not line.startswith("#")]


@pytest.mark.parametrize("name", FILES)
def test_ca16_top_comment_follows_adr_023(name: str) -> None:
    path, _ = FILES[name]
    block = top_comment(path)
    for forbidden in ("env_file", ".env.dashboard", ".env.api"):
        assert forbidden not in block, forbidden
    assert "Coolify" in block


@pytest.mark.parametrize("name", FILES)
def test_ca16_other_lines_are_identical(name: str) -> None:
    path, literal = FILES[name]
    assert not_comments(path) == literal


@pytest.mark.parametrize("name", ["api", "dashboard"])
def test_extra_ca16_dockerfiles_keep_the_rule_and_name_the_path(name: str) -> None:
    block = " ".join(top_comment(FILES[name][0]).replace("#", " ").split())
    assert "(R-03)" in block
    assert "tempo de execução pelo environment do compose" in block
    assert "Environment Variables do recurso no Coolify" in block
    assert "ADR-023" in block


def test_extra_ca16_streamlit_names_only_the_web_resource() -> None:
    block = " ".join(top_comment(STREAMLIT_CONFIG).replace("#", " ").split())
    assert "nas Environment Variables do recurso `partqc-web` no Coolify (VPS, ADR-023)" in block
    assert "partqc-api" not in block


def _plan() -> str:
    return PLAN.read_text(encoding="utf-8")


def _is_title(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("#") or bool(re.fullmatch(r"\*\*[^*]+\*\*:?", stripped))


def update_block(text: str) -> str:
    """The text after the title, up to the next title (a heading or a whole line in bold)."""
    assert text.count(TITLE) == 1
    after = text.split(TITLE, 1)[1].splitlines()[1:]
    block: list[str] = []
    for line in after:
        if _is_title(line):
            break
        block.append(line)
    return "\n".join(block)


def test_ca17_update_block_has_the_order() -> None:
    block = update_block(_plan())
    for needed in ("infra/migrate.py --status", "0 pending", "contract_version"):
        assert needed in block, needed
    for needed in ("qc_edge.requeue", "--yes"):
        assert needed in block, needed
    assert (
        block.index("migrate.py --status")
        < block.index("contract_version")
        < block.index("qc_edge.requeue")
    )


@pytest.mark.parametrize(
    "needed",
    [
        "CDN",
        "SEC-39-05",
        "abandoned_for_s",
        "Restart",
        "Accept-Encoding: identity",
        "unsupported response encoding",
        COOLIFY_URL,
        TRAEFIK_URL,
        "CA manual da SPEC-040",
    ],
)
def test_ca17_plan_mentions(needed: str) -> None:
    assert needed in _plan()


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    level = len(heading) - len(heading.lstrip("#"))
    following = re.search(rf"^#{{1,{level}}} ", text[start + len(heading) :], re.M)
    return (
        text[start:]
        if following is None
        else text[start : start + len(heading) + following.start()]
    )


def test_extra_ca17_order_of_all_the_steps_of_the_update_block() -> None:
    block = update_block(_plan())
    steps = [
        "merge",
        "uv run --env-file .env.migrate --package qc-api python infra/migrate.py --status",
        "uv run --env-file .env.migrate --package qc-api python infra/migrate.py`",
        "0 pending",
        "RLS",
        "/api/v1/health",
        "contract_version",
        "borda",
        "python -m qc_edge.requeue --outbox-path",
        "--yes",
    ]
    positions = [block.lower().index(step.lower()) for step in steps]
    assert positions == sorted(positions), dict(zip(steps, positions, strict=True))


def test_extra_ca17_update_block_explains_the_window_and_the_rule() -> None:
    block = update_block(_plan())
    assert "500" in block
    assert "422" in block
    assert "só acrescentam" in block
    assert "decisão na SPEC" in block


def test_extra_ca17_update_section_repeats_the_manual_ca_after_a_coolify_update() -> None:
    section = _section(_plan(), "### Atualização")
    assert "atualizar o Coolify" in section
    assert re.search(r"CA-18 da SPEC-040[^.]*passos 1 a 3", section)


def test_extra_ca17_risks_have_the_compression_and_the_cdn() -> None:
    section = _section(_plan(), "## 7. Riscos aceitos")
    for needed in (
        "Accept-Encoding: identity",
        "unsupported response encoding",
        "unsupported content encoding",
        COOLIFY_URL,
        TRAEFIK_URL,
        "2026-10-26",
        "CDN",
        "SEC-39-05",
        "fora do repositório",
    ):
        assert needed in section, needed


def test_extra_ca17_dns_step_points_to_the_cdn_note() -> None:
    section = _section(_plan(), "### Passo 3. DNS")
    assert "CDN" in section
    assert "fora do repositório" in section


def test_extra_ca17_alerts_item_says_when_to_restart() -> None:
    section = _section(_plan(), "### 5. Alertas no Telegram")
    assert "alerts check stopped: a previous send is still running" in section
    assert "abandoned_for_s" in section
    assert "**Restart** só do `partqc-api`" in section


def test_extra_ca17_manual_ca_keeps_the_key_out_of_argv() -> None:
    section = _section(_plan(), "### CA manual da SPEC-040")
    assert "k=$(docker exec <contêiner do dashboard> printenv READ_API_KEY)" in section
    assert """-K <(printf 'header = "X-API-Key: %s"\\n' "$k")""" in section
    assert "unset k" in section
    assert "Accept-Encoding: gzip" in section
    assert "Accept-Encoding: identity" in section
    assert "SPEC_ISSUE" in section
    assert "<subdominio>" in section
    for line in section.splitlines():
        if re.match(r"\s*(curl|docker)\b", line):
            without_descriptor = re.sub(r"<\(printf '[^']*' \"\$k\"\)", "", line)
            assert "$k" not in without_descriptor, line
