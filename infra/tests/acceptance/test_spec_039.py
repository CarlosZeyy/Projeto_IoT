"""Acceptance tests for SPEC-039 (deploy through Coolify: compose without published ports,
Caddy as an internal router with its own image, secrets in the Coolify panel).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test (at least) per automated CA, named ``test_caNN_*`` (CA-01 to CA-13;
CA-14 to CA-18 are manual, on the VPS and in the Coolify panel); ``test_extra_*`` tests cover
requirements of section 4 that no CA spells out, plus exploratory edge cases.

The tests marked ``docker`` (CA-08 to CA-13) run only with ``PARTQC_DOCKER_TESTS=1`` (SPEC-015
section 4.14): compose projects and build contexts are temporary copies of the tracked tree
(``copy_tracked_tree`` / ``build_image``), the real working tree is never written, containers
never publish ports and every container and network created here is removed.

No credential appears as a literal: keys, passwords and markers are generated at run time
(``secrets``), and the fictitious database URL is assembled from them (``reviews/checklist.md``
section 4). The only host used is ``partqc.example.org``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.acceptance]

REPO_ROOT = Path(__file__).resolve().parents[3]
INFRA = REPO_ROOT / "infra"
COMPOSE = INFRA / "compose.yaml"
CADDYFILE = INFRA / "Caddyfile"
CADDY_DOCKERFILE_PATH = INFRA / "docker" / "caddy.Dockerfile"
CADDY_DOCKERIGNORE = INFRA / "docker" / "caddy.Dockerfile.dockerignore"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
PLAN = REPO_ROOT / "docs" / "deployment-plan.md"
DOCKER_SUPPORT_PATH = INFRA / "tests" / "docker_support.py"
ACC015_PATH = Path(__file__).resolve().parent / "test_spec_015.py"

API_DOCKERFILE = "infra/docker/api.Dockerfile"
DASHBOARD_DOCKERFILE = "infra/docker/dashboard.Dockerfile"
CADDY_DOCKERFILE = "infra/docker/caddy.Dockerfile"

TEST_HOST = "partqc.example.org"
SERVICES = ("caddy", "api", "dashboard")
CADDY_FROM = "caddy:2.11.7@sha256:685ae3d7c34d9b5f8caeddc5d14051db7bbd88ff1f5a2fa0c16bd8ca328fb7af"

# SPEC-039 section 4.1, items 6 and 7 (exact).
API_ENV = {
    "DATABASE_URL": "${DATABASE_URL:?}",
    "READ_API_KEY": "${READ_API_KEY:?}",
    "MAX_BODY_BYTES": "${MAX_BODY_BYTES:-262144}",
    "LOG_LEVEL": "${LOG_LEVEL:-INFO}",
    "ALERTS_ENABLED": "${ALERTS_ENABLED:-false}",
    "TELEGRAM_BOT_TOKEN": "${TELEGRAM_BOT_TOKEN:-}",
    "TELEGRAM_CHAT_ID": "${TELEGRAM_CHAT_ID:-}",
    "ALERTS_LOT_IDLE_MINUTES": "${ALERTS_LOT_IDLE_MINUTES:-10}",
    "ALERTS_LOOKBACK_HOURS": "${ALERTS_LOOKBACK_HOURS:-24}",
    "ALERTS_CHECK_INTERVAL_S": "${ALERTS_CHECK_INTERVAL_S:-60}",
    "ALERTS_MAX_PER_HOUR": "${ALERTS_MAX_PER_HOUR:-10}",
    "ALERTS_INCLUDE_SIMULATED": "${ALERTS_INCLUDE_SIMULATED:-false}",
}
DASHBOARD_ENV = {
    "API_BASE_URL": "https://${PUBLIC_HOST:?}",
    "READ_API_KEY": "${READ_API_KEY:?}",
    "MODEL_METRICS_PATH": "${MODEL_METRICS_PATH:-}",
}
ENV_VALUE_RE = re.compile(r"^(https://)?\$\{[A-Z_]+(:\?|:-[^}]*)\}$")
# Resolved defaults of the 8 alert variables (SPEC-017 section 4.6, CA-08).
ALERT_DEFAULTS = {
    "ALERTS_ENABLED": "false",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
    "ALERTS_LOT_IDLE_MINUTES": "10",
    "ALERTS_LOOKBACK_HOURS": "24",
    "ALERTS_CHECK_INTERVAL_S": "60",
    "ALERTS_MAX_PER_HOUR": "10",
    "ALERTS_INCLUDE_SIMULATED": "false",
}

# SPEC-015 section 4.12 item 4 and SPEC-032 section 4.4 (strings of the compose file).
LIMITS = {
    "api": ("${API_MEM_LIMIT:-512m}", "${API_CPUS:-1.0}", "${API_PIDS_LIMIT:-256}"),
    "dashboard": (
        "${DASHBOARD_MEM_LIMIT:-1g}",
        "${DASHBOARD_CPUS:-1.0}",
        "${DASHBOARD_PIDS_LIMIT:-256}",
    ),
    "caddy": ("${CADDY_MEM_LIMIT:-256m}", "${CADDY_CPUS:-0.5}", "${CADDY_PIDS_LIMIT:-256}"),
}
LOGGING = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}

# CA-04 of SPEC-032.
HEADER_LINES = [
    "-Server",
    "-Via",
    'Referrer-Policy "no-referrer"',
    "Content-Security-Policy \"frame-ancestors 'self'\"",
    'Strict-Transport-Security "max-age=31536000"',
    'X-Content-Type-Options "nosniff"',
]
EXPECTED_HEADERS = {
    "strict-transport-security": "max-age=31536000",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "content-security-policy": "frame-ancestors 'self'",
}
# CA-30 of SPEC-015.
DOMAIN_RE = re.compile(r"\b[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}\b")
IPV4_RE = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b")

ENV_TITLE = (
    "# ---------- Coolify (variáveis do recurso) e infra/.env (conferência local) ----------"
)


# ============================================================================================
# helpers
# ============================================================================================


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(_read(path))


def _services() -> dict[str, Any]:
    return _load_yaml(COMPOSE)["services"]


def _load_module(name: str, path: Path) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _acc015() -> ModuleType:
    """The SPEC-015 acceptance module, to re-check the conditions SPEC-039 keeps valid."""
    return _load_module("partqc_acc039_acc015", ACC015_PATH)


def _support() -> ModuleType:
    return _load_module("partqc_acc039_docker_support", DOCKER_SUPPORT_PATH)


def _git_status() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout


def _env_dict(env: Any) -> dict[str, Any]:
    if env is None:
        return {}
    if isinstance(env, dict):
        return env
    return dict(item.split("=", 1) if "=" in item else (item, None) for item in env)


def _label_keys(labels: Any) -> list[str]:
    if labels is None:
        return []
    if isinstance(labels, dict):
        return [str(k) for k in labels]
    return [str(item).split("=", 1)[0] for item in labels]


def _caddy_text() -> str:
    lines = [line for line in _read(CADDYFILE).splitlines() if not line.strip().startswith("#")]
    return "\n".join(lines)


def _top_level(text: str) -> list[str]:
    depth = 0
    top: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if depth == 0 and stripped:
            top.append(stripped)
        depth += stripped.count("{") - stripped.count("}")
    return top


def _block_after(text: str, header: str) -> str:
    start = text.index(header)
    open_at = text.index("{", start + len(header) - 1)
    depth = 0
    for pos in range(open_at, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at + 1 : pos]
    raise AssertionError(f"unbalanced block after {header!r}")


def _instructions(text: str) -> list[str]:
    """Dockerfile instructions: continuations joined, comments and blank lines dropped."""
    out: list[str] = []
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not current and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            current += line[:-1].strip() + " "
            continue
        current += line
        out.append(" ".join(current.split()))
        current = ""
    if current.strip():
        out.append(" ".join(current.split()))
    return out


def _meaningful_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in _read(path).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _walk(node: Any) -> Iterator[Any]:
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _docker(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def _bytes_of(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmgt]?)i?b?", text)
    assert m, value
    factor = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}[m.group(2)]
    return int(float(m.group(1)) * factor)


# ============================================================================================
# CA-01: infra/compose.yaml structure (section 4.1)
# ============================================================================================


def test_ca01_compose_structure() -> None:
    data = _load_yaml(COMPOSE)
    assert data["name"] == "partqc"
    services = data["services"]
    assert set(services) == set(SERVICES)

    for name, svc in services.items():
        for key in ("ports", "container_name", "network_mode", "privileged", "pid"):
            assert key not in svc, (name, key)
        assert "networks" not in svc, name
        assert "env_file" not in svc, name
        for key in _label_keys(svc.get("labels")):
            assert not key.startswith(("traefik.", "coolify.")), (name, key)
        for vol in svc.get("volumes", []) or []:
            assert "docker.sock" not in json.dumps(vol), (name, vol)

    for name, port in (("caddy", "80"), ("api", "8000"), ("dashboard", "8501")):
        assert [str(p) for p in services[name]["expose"]] == [port], name

    assert "networks" not in data
    assert "volumes" not in data

    caddy = services["caddy"]
    assert caddy["build"] == {"context": "..", "dockerfile": "infra/docker/caddy.Dockerfile"}
    for key in ("image", "environment", "volumes", "healthcheck"):
        assert key not in caddy, key
    assert caddy["tmpfs"] == ["/tmp:size=64m", "/data:size=16m", "/config:size=16m"]
    deps = caddy["depends_on"]
    assert set(deps) == {"api", "dashboard"}, deps
    if isinstance(deps, dict):
        for dep in deps.values():
            assert "condition" not in (dep or {}), deps

    for name in ("api", "dashboard"):
        assert services[name]["build"] == {
            "context": "..",
            "dockerfile": f"infra/docker/{name}.Dockerfile",
        }, name


# ============================================================================================
# CA-02: environment and secrets (R-03, section 4.1 items 6 to 8)
# ============================================================================================


def test_ca02_compose_environment_and_secrets() -> None:
    services = _services()
    assert _env_dict(services["api"].get("environment")) == API_ENV
    assert _env_dict(services["dashboard"].get("environment")) == DASHBOARD_ENV
    assert "environment" not in services["caddy"]
    for name, svc in services.items():
        env = _env_dict(svc.get("environment"))
        if name != "api":
            assert "DATABASE_URL" not in env, name
        for key, value in env.items():
            assert isinstance(value, str), (name, key, value)
            assert ENV_VALUE_RE.match(value), (name, key, value)
    api_env = _env_dict(services["api"]["environment"])
    assert api_env["DATABASE_URL"] == "${DATABASE_URL:?}"
    assert api_env["READ_API_KEY"] == "${READ_API_KEY:?}"
    assert _env_dict(services["dashboard"]["environment"])["READ_API_KEY"] == "${READ_API_KEY:?}"


def test_extra_compose_text_has_no_literal_secret_or_env_file() -> None:
    """Exploratory (R-03): the raw text has no ``env_file``, no ``.env.api``/``.env.dashboard``
    and every ``DATABASE_URL``/``READ_API_KEY`` occurrence is a ``${NAME:?}`` reference."""
    text = _read(COMPOSE)
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "env_file" not in code
    assert ".env.api" not in text and ".env.dashboard" not in text
    for m in re.finditer(r"(DATABASE_URL|READ_API_KEY)\s*:\s*(\S+)", code):
        assert m.group(2).strip("\"'") == "${" + m.group(1) + ":?}", m.group(0)
    assert "postgres" not in code.lower()


# ============================================================================================
# CA-03: hardening kept (section 4.1, SPEC-015 section 4.12 item 4, SPEC-032 section 4.4)
# ============================================================================================


def test_ca03_compose_hardening() -> None:
    services = _services()
    for name, svc in services.items():
        assert svc["restart"] == "unless-stopped", name
        assert "no-new-privileges:true" in svc["security_opt"], name
        assert svc["logging"] == LOGGING, name
        assert svc["read_only"] is True, name
        mem, cpus, pids = LIMITS[name]
        assert svc["mem_limit"] == mem, name
        assert svc["cpus"] == cpus, name
        assert svc["pids_limit"] == pids, name
        assert svc["cap_drop"] == ["ALL"], name
    assert services["caddy"]["cap_add"] == ["NET_BIND_SERVICE"]
    for name in ("api", "dashboard"):
        assert "cap_add" not in services[name], name
    assert services["api"]["tmpfs"] == services["dashboard"]["tmpfs"] == ["/tmp:size=64m"]


def test_extra_compose_no_dangerous_keys_anywhere() -> None:
    """Exploratory: no ``ports``/``labels``/``healthcheck`` text in the caddy service, no extra
    capabilities, no ``extra_hosts`` (the SPEC section 7 alternative needs a decision)."""
    text = _read(COMPOSE)
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for word in ("ports:", "labels:", "traefik", "NET_ADMIN", "SYS_ADMIN", "extra_hosts"):
        assert word not in code, word
    assert "docker.sock" not in text
    assert "healthcheck" not in json.dumps(_services()["caddy"])


# ============================================================================================
# CA-04: infra/Caddyfile (section 4.2, R-13)
# ============================================================================================


def test_ca04_caddyfile() -> None:
    text = _caddy_text()
    lines = text.splitlines()
    assert not any(line.strip() == "{" for line in lines), "global options block"
    assert _top_level(text) == [":80 {"], _top_level(text)

    for forbidden in (
        "PUBLIC_HOST",
        "http://",
        "https://",
        "tls",
        "auto_https",
        "trusted_proxies",
        "bind",
        "acme_ca",
        "local_certs",
        "handle_path",
        "log",
        "includeSubDomains",
        "preload",
        "/docs",
        "openapi",
    ):
        assert forbidden not in text, forbidden
    assert "includesubdomains" not in text.lower()

    assert "reverse_proxy api:8000" in _block_after(text, "handle /api/* {")
    bare = [m.start() for m in re.finditer(r"(?m)^\s*handle\s*\{", text)]
    assert len(bare) == 1, "exactly one `handle` without matcher"
    assert "reverse_proxy dashboard:8501" in _block_after(text[bare[0] :], "handle {")

    for expected in HEADER_LINES:
        assert expected in text, expected

    for token in text.split():
        assert not DOMAIN_RE.search(token.lower()), token
        assert not IPV4_RE.search(token), token
    assert not DOMAIN_RE.search(text.lower()), DOMAIN_RE.search(text.lower())
    assert not IPV4_RE.search(text)


def test_extra_caddyfile_comments_and_format() -> None:
    """Section 4.2: the comments name the Coolify proxy (ADR-023), HTTP on the resource network
    and SPEC-038 (``handle_errors``); the file keeps the ``caddy fmt`` indentation (tabs, no
    trailing spaces); the header block is site-wide, inside ``:80``."""
    raw = _read(CADDYFILE)
    comments = "\n".join(line for line in raw.splitlines() if line.strip().startswith("#"))
    assert "Coolify" in comments
    assert "ADR-023" in comments
    assert "SPEC-038" in comments
    assert "handle_errors" in comments
    assert "handle_errors" not in _caddy_text()
    for n, line in enumerate(raw.splitlines(), 1):
        assert line == line.rstrip(), n
        indent = line[: len(line) - len(line.lstrip())]
        assert " " not in indent, (n, "caddy fmt indents with tabs")
    site = _block_after(_caddy_text(), ":80 {")
    blocks = re.findall(r"(?m)^\s*header\s*\{", site)
    assert len(blocks) == 1, blocks
    assert "header {" not in _block_after(site, "handle /api/* {")


# ============================================================================================
# CA-05: caddy.Dockerfile and its .dockerignore (section 4.3)
# ============================================================================================


def test_ca05_caddy_dockerfile_and_dockerignore() -> None:
    assert _instructions(_read(CADDY_DOCKERFILE_PATH)) == [
        f"FROM {CADDY_FROM}",
        "COPY infra/Caddyfile /etc/caddy/Caddyfile",
        'LABEL partqc.component="caddy"',
    ]
    assert _meaningful_lines(CADDY_DOCKERIGNORE) == ["*", "!infra/Caddyfile"]
    assert "caddy:2." not in _read(COMPOSE)


def test_extra_caddy_dockerfile_has_no_forbidden_instruction() -> None:
    """Exploratory: the keywords forbidden by section 4.3 appear nowhere outside comments
    (case-insensitive), and the image is pinned by digest."""
    instrs = _instructions(_read(CADDY_DOCKERFILE_PATH))
    keywords = {i.split()[0].upper() for i in instrs}
    for bad in ("RUN", "USER", "ENV", "ARG", "EXPOSE", "HEALTHCHECK", "ENTRYPOINT", "CMD", "ADD"):
        assert bad not in keywords, bad
    assert re.search(r"@sha256:[0-9a-f]{64}$", instrs[0]), instrs[0]


# ============================================================================================
# CA-06: .env.example (section 4.4)
# ============================================================================================


def _env_block(lines: list[str]) -> list[str]:
    start = lines.index(ENV_TITLE)
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("# ----------")),
        len(lines),
    )
    return lines[start:end]


def test_ca06_env_example() -> None:
    text = _read(ENV_EXAMPLE)
    lines = text.splitlines()
    assert ENV_TITLE in lines
    block = _env_block(lines)
    joined = "\n".join(block)
    for needle in ("Coolify", "Locked", "Literal", "ALERTS_", "config --quiet"):
        assert needle in joined, needle
    for expected in (
        "PUBLIC_HOST=<subdominio>",
        "API_MEM_LIMIT=512m",
        "API_CPUS=1.0",
        "DASHBOARD_MEM_LIMIT=1g",
        "DASHBOARD_CPUS=1.0",
        "CADDY_MEM_LIMIT=256m",
        "CADDY_CPUS=0.5",
        "API_PIDS_LIMIT=256",
        "DASHBOARD_PIDS_LIMIT=256",
        "CADDY_PIDS_LIMIT=256",
    ):
        assert expected in block, expected
    for gone in ("infra/.env.api", "infra/.env.dashboard", 'rode "up -d"'):
        assert gone not in text, gone

    # CA-39 and CA-05 of SPEC-015 still hold.
    acc015 = _acc015()
    acc015.test_ca39_env_example()
    acc015.test_ca05_env_example_secrets_are_blank_or_markers()


def test_extra_env_example_coolify_wording() -> None:
    """Section 4.4, items 2 to 4: the panel phrases, the Redeploy hint of ``*_PIDS_LIMIT``,
    ``API_BASE_URL`` built by the compose, and the dashboard block sentence."""
    text = _read(ENV_EXAMPLE)
    lines = text.splitlines()
    joined = "\n".join(_env_block(lines))
    assert "Redeploy" in joined
    assert "API_BASE_URL" in joined and "PUBLIC_HOST" in joined
    assert "TELEGRAM_" in joined
    flat = " ".join(" ".join(line.lstrip("# ").split()) for line in lines if line.startswith("#"))
    assert (
        "Na VPS, READ_API_KEY e MODEL_METRICS_PATH vêm das variáveis do recurso no Coolify, "
        "e API_BASE_URL vem do infra/compose.yaml"
    ) in flat
    assert "infra/.env.dashboard" not in flat
    # one PUBLIC_HOST line, outside any fake value
    assert sum(1 for line in lines if line.startswith("PUBLIC_HOST=")) == 1


# ============================================================================================
# CA-07: docs/deployment-plan.md (section 4.5, 4.8)
# ============================================================================================


def test_ca07_deployment_plan() -> None:
    text = _read(PLAN)
    for needle in (
        "Base Directory",
        "`/infra`",
        "Docker Compose Location",
        "`/compose.yaml`",
        "https://<subdominio>:80",
        "Environment Variables",
        "Locked",
        "Literal",
        "Preserve repository",
        "Connect to predefined network",
        "com.docker.compose.project=<uuid>",
        "Manual Git Webhooks",
        "Deploy on push",
        "Just the push event",
        "Enable SSL verification",
    ):
        assert needle in text, needle

    webhook_secret_in_actions = re.compile(r"secrets\.[A-Za-z0-9_]*WEBHOOK", re.IGNORECASE)
    for line in text.splitlines():
        if "Webhook secret" in line or "segredo do webhook" in line:
            assert "Coolify" in line or "GitHub" in line, line
        assert not webhook_secret_in_actions.search(line), line
        lowered = line.lower()
        if "coolify-proxy" in line and any(
            w in lowered for w in ("restart", "reinici", "stop", "parar", "editar")
        ):
            assert "Nunca" in line or "nunca" in line, line
        if "Raw" in line:
            assert "Nunca" in line or "nunca" in line or "não" in line, line

    # CA-25, CA-27, CA-38 and CA-41 of SPEC-015 still hold.
    acc015 = _acc015()
    acc015.test_ca25_accepted_risks_and_register_device()
    acc015.test_ca27_statement_timeout_keys_render_and_simulator()
    acc015.test_ca38_operation_rules()
    acc015.test_ca41_no_ipv4_literal_in_deploy_files()
    acc015.test_ca41_public_urls_are_placeholders()


def test_extra_plan_has_no_panel_url_uuid_or_webhook_url() -> None:
    """Exploratory (R-13, section 4.8 item 4): no concrete Coolify webhook endpoint, no UUID
    and no ``sslip.io`` host; ``<uuid>`` is always a placeholder."""
    text = _read(PLAN)
    assert not re.search(r"/webhooks/source/github/events", text)
    uuid_re = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
    assert not uuid_re.search(text), uuid_re.search(text)
    assert "sslip.io" not in text.lower()
    for m in re.finditer(r"com\.docker\.compose\.project=(\S+)", text):
        assert m.group(1).startswith(("<uuid>", "...")), m.group(0)  # placeholder or ellipsis
    for line in text.splitlines():
        if "--project-name" in line:
            assert "<uuid>" in line or "partqc" in line, line


def test_extra_plan_and_repo_reference_no_coolify_api_token_in_actions() -> None:
    """Exploratory (section 3.2, ADR-023 decision 5): no workflow calls the Coolify API or
    reads a Coolify/webhook secret."""
    workflows = REPO_ROOT / ".github" / "workflows"
    for path in sorted(workflows.glob("*.y*ml")):
        text = _read(path).lower()
        assert "coolify" not in text, path.name
        assert "webhook" not in text, path.name


# ============================================================================================
# CA-08 .. CA-13: docker
# ============================================================================================


def _fake_db() -> tuple[str, str]:
    """A fictitious session URL of the Supabase pooler (transaction port) and its password."""
    password = "pw" + secrets.token_hex(12)
    user = "partqc_" + secrets.token_hex(4)
    return f"postgresql://{user}:{password}@db.example.org:6543/postgres", password


def _compose_env() -> dict[str, str]:
    """The process environment without any variable the compose interpolates."""
    drop = {"PUBLIC_HOST", "DATABASE_URL", "READ_API_KEY", "MAX_BODY_BYTES", "LOG_LEVEL"}
    drop |= {"MODEL_METRICS_PATH", "API_BASE_URL"}
    prefixes = ("API_", "DASHBOARD_", "CADDY_", "COMPOSE_", "ALERTS_", "TELEGRAM_")
    return {k: v for k, v in os.environ.items() if k not in drop and not k.startswith(prefixes)}


class ComposeCopy:
    def __init__(self, root: Path, db_url: str, db_password: str, read_key: str) -> None:
        self.root = root
        self.db_url = db_url
        self.db_password = db_password
        self.read_key = read_key

    @property
    def env_file(self) -> Path:
        return self.root / "infra" / ".env"

    def env_text(self, *, drop: str | None = None, extra: str = "") -> str:
        values = {
            "PUBLIC_HOST": TEST_HOST,
            "DATABASE_URL": self.db_url,
            "READ_API_KEY": self.read_key,
        }
        return "".join(f"{k}={v}\n" for k, v in values.items() if k != drop) + extra

    def config(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["docker", "compose", "-f", str(self.root / "infra" / "compose.yaml"), "config"]
            + list(args or ["--format", "json"]),
            env=_compose_env(),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )


@pytest.fixture
def compose_copy(tmp_path: Path) -> ComposeCopy:
    support = _support()
    if not support.docker_tests_enabled(os.environ):
        pytest.skip(support.SKIP_REASON)
    db_url, password = _fake_db()
    copy = ComposeCopy(tmp_path / "compose-copy", db_url, password, secrets.token_urlsafe(32))
    support.copy_tracked_tree(copy.root, {"infra/.env": copy.env_text().encode()})
    return copy


@pytest.mark.docker
def test_ca08_compose_config_resolves(compose_copy: ComposeCopy) -> None:
    before = _git_status()
    result = compose_copy.config()
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    api_env = services["api"]["environment"]
    dash_env = services["dashboard"]["environment"]
    assert dash_env["API_BASE_URL"] == f"https://{TEST_HOST}"
    assert api_env["DATABASE_URL"] == compose_copy.db_url
    assert api_env["READ_API_KEY"] == dash_env["READ_API_KEY"] == compose_copy.read_key
    assert api_env["MAX_BODY_BYTES"] == "262144"
    assert api_env["LOG_LEVEL"] == "INFO"
    assert dash_env["MODEL_METRICS_PATH"] == ""
    for key, value in ALERT_DEFAULTS.items():
        assert api_env[key] == value, key
    for name in ("dashboard", "caddy"):
        env = services[name].get("environment") or {}
        leaked = [k for k in env if k.startswith(("ALERTS_", "TELEGRAM_"))]
        assert not leaked, (name, leaked)
    for name, svc in services.items():
        assert not svc.get("ports"), (name, svc.get("ports"))
    assert _bytes_of(services["api"]["mem_limit"]) == 512 * 1024**2
    assert _git_status() == before
    assert not (REPO_ROOT / "infra" / ".env").exists()


@pytest.mark.docker
@pytest.mark.parametrize("missing", ["PUBLIC_HOST", "DATABASE_URL", "READ_API_KEY"])
def test_ca08_compose_config_requires_each_mandatory_variable(
    compose_copy: ComposeCopy, missing: str
) -> None:
    compose_copy.env_file.write_text(compose_copy.env_text(drop=missing), encoding="utf-8")
    result = compose_copy.config()
    assert result.returncode != 0
    assert missing in result.stderr, result.stderr
    output = result.stdout + result.stderr
    assert compose_copy.read_key not in output
    assert compose_copy.db_password not in output


@pytest.mark.docker
def test_extra_compose_config_quiet_with_limit_override_and_alerts(
    compose_copy: ComposeCopy,
) -> None:
    """Exploratory: ``config --quiet`` (the local check of section 4.1 item 10) passes; a panel
    override of a limit and of the alert variables reaches only the api; a non-numeric pids
    limit fails without echoing values."""
    assert compose_copy.config("--quiet").returncode == 0
    chat = str(secrets.randbelow(10**9))
    token = secrets.token_urlsafe(24)
    compose_copy.env_file.write_text(
        compose_copy.env_text(
            extra=(
                "API_MEM_LIMIT=768m\nDASHBOARD_PIDS_LIMIT=512\nALERTS_ENABLED=true\n"
                f"TELEGRAM_CHAT_ID={chat}\nTELEGRAM_BOT_TOKEN={token}\nLOG_LEVEL=DEBUG\n"
            )
        ),
        encoding="utf-8",
    )
    result = compose_copy.config()
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert _bytes_of(services["api"]["mem_limit"]) == 768 * 1024**2
    assert int(services["dashboard"]["pids_limit"]) == 512
    assert int(services["api"]["pids_limit"]) == 256
    api_env = services["api"]["environment"]
    assert api_env["ALERTS_ENABLED"] == "true"
    assert api_env["TELEGRAM_CHAT_ID"] == chat
    assert api_env["TELEGRAM_BOT_TOKEN"] == token
    assert api_env["LOG_LEVEL"] == "DEBUG"
    assert token not in json.dumps(services["dashboard"]) + json.dumps(services["caddy"])

    compose_copy.env_file.write_text(compose_copy.env_text(extra="API_PIDS_LIMIT=abc\n"))
    bad = compose_copy.config("--quiet")
    assert bad.returncode != 0
    assert compose_copy.read_key not in bad.stdout + bad.stderr


@pytest.mark.docker
def test_extra_compose_single_quoted_dollar_in_a_secret_is_literal(
    compose_copy: ComposeCopy,
) -> None:
    """Exploratory: a key with ``$`` in single quotes in the env file reaches the containers
    literally (``config`` prints it as ``$$``); unquoted, compose interpolates it. Coolify's
    "Literal" flag exists for this reason (section 4.1 item 6, CA-17)."""
    value = "ab$cd" + secrets.token_hex(6)
    compose_copy.env_file.write_text(
        compose_copy.env_text(drop="READ_API_KEY", extra=f"READ_API_KEY='{value}'\n")
    )
    result = compose_copy.config()
    assert result.returncode == 0, result.stderr
    env = json.loads(result.stdout)["services"]["api"]["environment"]
    assert env["READ_API_KEY"] == value.replace("$", "$$")


@pytest.mark.docker
def test_ca09_compose_config_in_the_coolify_invocation(tmp_path: Path) -> None:
    support = _support()
    copy = support.copy_tracked_tree(tmp_path / "coolify-copy")
    assert not (copy / "infra" / ".env").exists()
    db_url, _ = _fake_db()
    env_file = tmp_path / "coolify.env"
    env_file.write_text(
        f"PUBLIC_HOST={TEST_HOST}\nDATABASE_URL={db_url}\n"
        f"READ_API_KEY={secrets.token_urlsafe(32)}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(env_file)]
        + ["--project-name", "partqc-coolify-test"]
        + ["--project-directory", str(copy / "infra")]
        + ["-f", str(copy / "infra" / "compose.yaml"), "config", "--format", "json"],
        env=_compose_env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    cfg = json.loads(result.stdout)
    assert cfg["name"] == "partqc-coolify-test"
    root = Path(copy).resolve()
    for name in SERVICES:
        build = cfg["services"][name]["build"]
        assert Path(build["context"]).is_absolute(), build
        assert Path(build["context"]).resolve() == root, (name, build)
        assert build["dockerfile"].endswith(f"infra/docker/{name}.Dockerfile"), (name, build)
    assert cfg["services"]["dashboard"]["environment"]["API_BASE_URL"] == f"https://{TEST_HOST}"
    # exploratory: the Coolify form also resolves without ports, volumes or networks of its own
    for name, svc in cfg["services"].items():
        assert not svc.get("ports"), name
        assert not svc.get("volumes"), (name, svc.get("volumes"))
    assert not cfg.get("volumes"), cfg.get("volumes")


@pytest.mark.docker
def test_extra_coolify_invocation_fails_without_the_panel_variables(tmp_path: Path) -> None:
    """Exploratory: the same invocation with an empty ``--env-file`` (variables not created in
    the panel) fails and names a mandatory variable: the ``:?`` blocks the deploy."""
    copy = _support().copy_tracked_tree(tmp_path / "coolify-copy")
    env_file = tmp_path / "coolify.env"
    env_file.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(env_file), "--project-name", "partqc-c39"]
        + ["--project-directory", str(copy / "infra")]
        + ["-f", str(copy / "infra" / "compose.yaml"), "config", "--quiet"],
        env=_compose_env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != 0
    assert any(v in result.stderr for v in ("PUBLIC_HOST", "DATABASE_URL", "READ_API_KEY"))


@pytest.fixture(scope="module")
def caddy_image(build_image: Callable[..., str]) -> str:
    return build_image(CADDY_DOCKERFILE)


@pytest.fixture(scope="module")
def api_image(build_image: Callable[..., str]) -> str:
    return build_image(API_DOCKERFILE)


@pytest.fixture(scope="module")
def dashboard_image(build_image: Callable[..., str]) -> str:
    return build_image(DASHBOARD_DOCKERFILE)


def _adapt(image: str) -> subprocess.CompletedProcess:
    env_args: list[str] = []  # no PUBLIC_HOST in the container environment
    return _docker(
        "run", "--rm", "--network", "none", *env_args, image,
        "caddy", "adapt", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile",
        timeout=300,
    )  # fmt: skip


def _proxy_handlers(cfg: dict[str, Any]) -> list[tuple[dict[str, Any], list[Any]]]:
    found: list[tuple[dict[str, Any], list[Any]]] = []

    def visit(routes: list[dict[str, Any]], chain: list[Any]) -> None:
        for route in routes:
            here = [*chain, route.get("match") or []]
            for handler in route.get("handle", []):
                if handler.get("handler") == "reverse_proxy":
                    found.append((handler, here))
                if handler.get("handler") == "subroute":
                    visit(handler.get("routes", []), here)

    for server in cfg["apps"]["http"]["servers"].values():
        visit(server.get("routes", []), [])
    return found


@pytest.mark.docker
def test_ca10_caddy_adapt(caddy_image: str) -> None:
    result = _adapt(caddy_image)
    assert result.returncode == 0, result.stderr
    assert "not formatted" not in result.stderr.lower(), result.stderr
    assert "caddy fmt" not in result.stderr, result.stderr
    cfg = json.loads(result.stdout)

    servers = cfg["apps"]["http"]["servers"]
    assert len(servers) == 1, servers
    (server,) = servers.values()
    assert server["listen"] == [":80"], server["listen"]
    assert "tls" not in cfg["apps"], cfg["apps"].keys()

    hosts = [
        node
        for node in _walk(cfg)
        if isinstance(node, dict) and isinstance(node.get("match"), list)
        for matcher in node["match"]
        if "host" in matcher
    ]
    assert hosts == [], hosts

    handlers = _proxy_handlers(cfg)
    assert len(handlers) == 2, handlers
    api = [(h, c) for h, c in handlers if h.get("upstreams") == [{"dial": "api:8000"}]]
    dash = [(h, c) for h, c in handlers if h.get("upstreams") == [{"dial": "dashboard:8501"}]]
    assert len(api) == 1 and len(dash) == 1, handlers
    assert ["/api/*"] in [m.get("path") for sets in api[0][1] for m in sets], api[0][1]
    assert [m["path"] for sets in dash[0][1] for m in sets if "path" in m] == [], dash[0][1]

    expected_set = {
        "Referrer-Policy": ["no-referrer"],
        "Content-Security-Policy": ["frame-ancestors 'self'"],
        "Strict-Transport-Security": ["max-age=31536000"],
        "X-Content-Type-Options": ["nosniff"],
    }
    matching = []
    for handler in (n for n in _walk(cfg) if isinstance(n, dict) and n.get("handler") == "headers"):
        response = handler.get("response") or {}
        values = response.get("set") or {}
        if {"Server", "Via"} <= set(response.get("delete") or []) and all(
            values.get(k) == v for k, v in expected_set.items()
        ):
            matching.append(handler)
    assert matching, json.dumps(cfg, indent=1)


@pytest.mark.docker
def test_extra_caddy_adapt_has_no_automatic_https_and_no_redirect(caddy_image: str) -> None:
    """Exploratory: the adapted config has no ``automatic_https`` section, no ``tls_*`` key,
    no ``static_response`` redirect to https and only one deferred ``headers`` handler."""
    result = _adapt(caddy_image)
    assert result.returncode == 0, result.stderr
    cfg = json.loads(result.stdout)
    dumped = json.dumps(cfg)
    assert "automatic_https" not in dumped
    assert "tls_connection_policies" not in dumped
    assert "https://" not in dumped
    statics = [
        n for n in _walk(cfg) if isinstance(n, dict) and n.get("handler") == "static_response"
    ]
    assert statics == [], statics
    headers = [n for n in _walk(cfg) if isinstance(n, dict) and n.get("handler") == "headers"]
    assert len(headers) == 1 and headers[0]["response"].get("deferred") is True, headers


def _image_config(image: str) -> dict[str, Any]:
    result = _docker("image", "inspect", image)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)[0]["Config"]


@pytest.fixture(scope="module")
def base_caddy_config(caddy_image: str) -> dict[str, Any]:
    if _docker("image", "inspect", CADDY_FROM).returncode != 0:
        pulled = _docker("pull", CADDY_FROM, timeout=600)
        assert pulled.returncode == 0, pulled.stderr
    return _image_config(CADDY_FROM)


@pytest.mark.docker
def test_ca11_caddy_image_embeds_the_caddyfile(
    caddy_image: str, base_caddy_config: dict[str, Any]
) -> None:
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--entrypoint", "cat", caddy_image]
        + ["/etc/caddy/Caddyfile"],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == CADDYFILE.read_bytes()
    config = _image_config(caddy_image)
    assert config["Labels"]["partqc.component"] == "caddy"
    assert config.get("Healthcheck") is None, config.get("Healthcheck")
    assert config["Cmd"] == base_caddy_config["Cmd"], (config["Cmd"], base_caddy_config["Cmd"])


@pytest.mark.docker
def test_extra_caddy_image_keeps_the_base_user_entrypoint_env_and_ports(
    caddy_image: str, base_caddy_config: dict[str, Any]
) -> None:
    """Exploratory (section 4.3): no ``USER``/``ENV``/``EXPOSE``/``ENTRYPOINT`` of its own, and
    no traefik/coolify label baked into the image."""
    config = _image_config(caddy_image)
    for key in ("User", "Entrypoint", "Env", "ExposedPorts", "WorkingDir", "Volumes"):
        assert config.get(key) == base_caddy_config.get(key), key
    for key in config.get("Labels") or {}:
        assert not key.startswith(("traefik.", "coolify.")), key


@pytest.mark.docker
def test_extra_caddy_context_admits_only_the_caddyfile(build_image: Callable[..., str]) -> None:
    """Exploratory (section 4.3, R-02/R-14): with photos, git metadata, local notes and env files
    planted in the context, the Caddy image adds only ``/etc/caddy/Caddyfile`` to the base."""
    marker = "partqc-acc039-" + secrets.token_hex(8)
    planted = {
        "foto.jpg": marker.encode(),
        "edge/data/captures/x.jpg": marker.encode(),
        ".git/config": marker.encode(),
        "notas-locais/diario.md": marker.encode(),
        ".streamlit/secrets.toml": marker.encode(),
        "infra/.env.api": marker.encode(),
    }
    image = build_image(CADDY_DOCKERFILE, planted)
    script = (
        f"grep -rl {marker} / --exclude-dir=proc --exclude-dir=sys --exclude-dir=dev "
        "2>/dev/null; find / -xdev \\( -name 'foto.jpg' -o -name 'diario.md' "
        "-o -name 'secrets.toml' -o -name 'x.jpg' \\) -print"
    )
    result = _docker("run", "--rm", "--network", "none", "--entrypoint", "sh", image, "-c", script)
    assert result.stdout.strip() == "", result.stdout


# --------------------------------------------------------------------------------------------
# CA-12 (docker): Caddy routes on a private network, under the compose options
# --------------------------------------------------------------------------------------------


class Containers:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.networks: list[str] = []

    def run(self, image: str, *options: str) -> str:
        name = f"partqc-acc039-{uuid.uuid4().hex[:10]}"
        result = _docker("run", "-d", "--name", name, *options, image)
        assert result.returncode == 0, result.stderr
        self.names.append(name)
        return name

    def network(self) -> str:
        name = f"partqc-acc039-net-{uuid.uuid4().hex[:8]}"
        result = _docker("network", "create", "--internal", name)
        assert result.returncode == 0, result.stderr
        self.networks.append(name)
        return name

    def cleanup(self) -> None:
        if self.names:
            _docker("rm", "-f", "-v", *self.names)
        for net in self.networks:
            _docker("network", "rm", net)


@pytest.fixture
def containers() -> Iterator[Containers]:
    box = Containers()
    yield box
    box.cleanup()


def _inspect(name: str, fmt: str) -> str:
    return _docker("inspect", "--format", fmt, name).stdout.strip()


def _logs(name: str) -> str:
    result = _docker("logs", name)
    return result.stdout + result.stderr


def _wait(predicate: Callable[[], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(1)
    return predicate()


PROBE = (
    "import http.client, json, socket, sys\n"
    "out = []\n"
    "for path in sys.argv[3:]:\n"
    "    try:\n"
    "        conn = http.client.HTTPConnection(sys.argv[1], 80, timeout=30)\n"
    "        conn.request('GET', path, headers={'Host': sys.argv[2]})\n"
    "        r = conn.getresponse()\n"
    "        body = r.read().decode('utf-8', 'replace')[:4000]\n"
    "        out.append([path, r.status, [[k.lower(), v] for k, v in r.getheaders()], body,\n"
    "                    r.version])\n"
    "    except Exception as exc:\n"
    "        out.append([path, None, [], type(exc).__name__, None])\n"
    "s = socket.socket()\n"
    "s.settimeout(10)\n"
    "try:\n"
    "    s.connect((sys.argv[1], 443))\n"
    "    tls = 'open'\n"
    "except ConnectionRefusedError:\n"
    "    tls = 'refused'\n"
    "except Exception as exc:\n"
    "    tls = type(exc).__name__\n"
    "print(json.dumps({'responses': out, 'tls': tls}))\n"
)


def _probe(client_image: str, net: str, *paths: str, host: str = TEST_HOST) -> dict[str, Any]:
    result = _docker(
        "run", "--rm", "--network", net, "--entrypoint", "python", client_image,
        "-c", PROBE, "caddy", host, *paths,
        timeout=180,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip().splitlines()[-1])
    data["by_path"] = {
        path: {"status": status, "headers": dict(headers), "body": body, "version": version}
        for path, status, headers, body, version in data["responses"]
    }
    return data


def _hardened(service: str) -> list[str]:
    args = ["--read-only"]
    for item in _services()[service]["tmpfs"]:
        args += ["--tmpfs", item]
    args += ["--pids-limit", "256", "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    return args


@pytest.fixture
def routed_stack(
    api_image: str, dashboard_image: str, caddy_image: str, containers: Containers
) -> dict[str, str]:
    net = containers.network()
    db_url, _ = _fake_db()
    key = secrets.token_urlsafe(32)
    containers.run(
        api_image, "--network", net, "--network-alias", "api",
        "-e", f"DATABASE_URL={db_url}", "-e", f"READ_API_KEY={key}", *_hardened("api"),
    )  # fmt: skip
    dash = containers.run(
        dashboard_image, "--network", net, "--network-alias", "dashboard",
        "-e", f"API_BASE_URL=https://{TEST_HOST}", "-e", f"READ_API_KEY={key}",
        *_hardened("dashboard"),
    )  # fmt: skip
    caddy = containers.run(
        caddy_image, "--network", net, "--network-alias", "caddy",
        "--read-only",
        "--tmpfs", "/tmp:size=64m", "--tmpfs", "/data:size=16m", "--tmpfs", "/config:size=16m",
        "--cap-drop", "ALL", "--cap-add", "NET_BIND_SERVICE",
        "--security-opt", "no-new-privileges", "--pids-limit", "256",
    )  # fmt: skip

    def healthy() -> bool:
        assert _inspect(dash, "{{.State.Status}}") == "running", _logs(dash)
        return _inspect(dash, "{{.State.Health.Status}}") == "healthy"

    assert _wait(healthy, 90), _logs(dash)
    return {"net": net, "caddy": caddy, "dashboard": dash, "client": api_image}


@pytest.mark.docker
def test_ca12_caddy_routes_on_a_private_network(routed_stack: dict[str, str]) -> None:
    net, caddy, client = routed_stack["net"], routed_stack["caddy"], routed_stack["client"]
    paths = ("/api/v1/health", "/_stcore/health", "/docs", "/openapi.json")

    def answered() -> bool:
        status = _probe(client, net, "/api/v1/health")["by_path"]["/api/v1/health"]["status"]
        return status in (200, 503)

    assert _wait(answered, 90), _logs(caddy)
    data = _probe(client, net, *paths)
    resp = data["by_path"]

    health = resp["/api/v1/health"]
    assert health["status"] in (200, 503), health
    assert health["version"] == 11, health  # HTTP/1.1
    assert "status" in json.loads(health["body"]), health
    stcore = resp["/_stcore/health"]
    assert stcore["status"] == 200, stcore
    assert stcore["body"].strip() == "ok", stcore
    for path in ("/api/v1/health", "/_stcore/health"):
        headers = resp[path]["headers"]
        for key, value in EXPECTED_HEADERS.items():
            assert headers.get(key) == value, (path, key, headers)
        assert "server" not in headers, (path, headers)
        assert "via" not in headers, (path, headers)
    assert "swagger" not in resp["/docs"]["body"].lower(), resp["/docs"]
    assert '"openapi"' not in resp["/openapi.json"]["body"], resp["/openapi.json"]
    assert data["tls"] == "refused", data["tls"]

    assert "read-only file system" not in _logs(caddy).lower(), _logs(caddy)
    assert _inspect(caddy, "{{.State.Status}}") == "running", _logs(caddy)


@pytest.mark.docker
def test_extra_caddy_blocks_api_docs_variants_and_accepts_any_host(
    routed_stack: dict[str, str],
) -> None:
    """Exploratory: no Swagger/OpenAPI under ``/api/*`` either (``/api/docs``,
    ``/api/v1/docs``, ``/api/openapi.json``, ``/api/v1/openapi.json``, ``/redoc``); a request
    with another ``Host`` is still routed (section 7: only the Coolify proxy reaches Caddy)."""
    net, client, caddy = routed_stack["net"], routed_stack["client"], routed_stack["caddy"]
    assert _wait(
        lambda: (
            _probe(client, net, "/api/v1/health")["by_path"]["/api/v1/health"]["status"]
            in (200, 503)
        ),
        90,
    ), _logs(caddy)
    paths = (
        "/api/docs",
        "/api/v1/docs",
        "/api/openapi.json",
        "/api/v1/openapi.json",
        "/redoc",
        "/api/redoc",
        "/docs/oauth2-redirect",
    )
    resp = _probe(client, net, *paths)["by_path"]
    for path in paths:
        body = resp[path]["body"]
        assert "swagger" not in body.lower(), (path, resp[path]["status"])
        assert '"openapi"' not in body, (path, resp[path]["status"])
        assert "redoc.standalone" not in body.lower(), (path, resp[path]["status"])
    other = _probe(client, net, "/api/v1/health", host="outro.example.org")["by_path"]
    assert other["/api/v1/health"]["status"] in (200, 503), other


@pytest.mark.docker
def test_extra_caddy_runs_stateless_under_compose_options(
    caddy_image: str, containers: Containers
) -> None:
    """Exploratory (section 4.1 item 5): under the compose options, ``/data`` and ``/config``
    are 16m tmpfs mounts (writable), ``/etc`` stays read-only, ``pids.max`` is 256 and no
    anonymous volume is created from the image ``VOLUME`` lines."""
    name = containers.run(
        caddy_image, "--network", "none", "--read-only",
        "--tmpfs", "/tmp:size=64m", "--tmpfs", "/data:size=16m", "--tmpfs", "/config:size=16m",
        "--cap-drop", "ALL", "--cap-add", "NET_BIND_SERVICE",
        "--security-opt", "no-new-privileges", "--pids-limit", "256",
    )  # fmt: skip
    time.sleep(5)
    assert _inspect(name, "{{.State.Status}}") == "running", _logs(name)
    mounts = json.loads(_inspect(name, "{{json .Mounts}}") or "[]")
    assert mounts == [], mounts
    script = (
        "for d in /tmp /data /config /etc /etc/caddy; do "
        'if touch "$d/.probe" 2>/dev/null; then echo "$d rw"; else echo "$d ro"; fi; done; '
        "cat /sys/fs/cgroup/pids.max; "
        'awk \'$2=="/data" || $2=="/config" {print $2, $3, $4}\' /proc/mounts'
    )
    result = _docker("exec", name, "sh", "-c", script)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[:6] == ["/tmp rw", "/data rw", "/config rw", "/etc ro", "/etc/caddy ro", "256"]
    mounted = {line.split()[0]: line.split(" ", 2)[1:] for line in lines[6:]}
    for target in ("/data", "/config"):
        fstype, options = mounted[target]
        assert fstype == "tmpfs", (target, mounted)
        assert "size=16384k" in options, (target, options)
    assert "read-only file system" not in _logs(name).lower()


# --------------------------------------------------------------------------------------------
# CA-13 (docker): the Coolify .env never reaches an image (R-03, section 4.6)
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def env_marker() -> str:
    return "partqc-acc039-" + secrets.token_hex(12)


def _sentinels(marker: str) -> dict[str, bytes]:
    content = f"DATABASE_URL={marker}\n".encode()
    return {"infra/.env": content, ".env": content}


@pytest.mark.docker
@pytest.mark.parametrize("dockerfile", [API_DOCKERFILE, DASHBOARD_DOCKERFILE])
def test_ca13_env_sentinels_stay_out_of_api_and_dashboard(
    build_image: Callable[..., str], env_marker: str, dockerfile: str
) -> None:
    before = _git_status()
    image = build_image(dockerfile, _sentinels(env_marker))
    assert _git_status() == before
    for path in ("/app/infra/.env", "/app/.env"):
        result = _docker(
            "run", "--rm", "--network", "none", "--entrypoint", "test", image, "-e", path
        )
        assert result.returncode != 0, (dockerfile, path)
    grep = _docker(
        "run", "--rm", "--network", "none", "--entrypoint", "grep", image,
        "-rl", env_marker, "/app",
        timeout=600,
    )  # fmt: skip
    assert grep.stdout.strip() == "", grep.stdout
    assert grep.returncode == 1, (grep.returncode, grep.stderr)  # 1 = no match, 2 = error


@pytest.mark.docker
def test_ca13_env_sentinels_stay_out_of_the_caddy_image(
    build_image: Callable[..., str], env_marker: str
) -> None:
    image = build_image(CADDY_DOCKERFILE, _sentinels(env_marker))
    find = _docker(
        "run", "--rm", "--network", "none", "--entrypoint", "find", image,
        "/", "-xdev", "-name", ".env*",
    )  # fmt: skip
    assert find.stdout.strip() == "", find.stdout
    app = _docker("run", "--rm", "--network", "none", "--entrypoint", "test", image, "-e", "/app")
    assert app.returncode != 0
    grep = _docker(
        "run", "--rm", "--network", "none", "--entrypoint", "grep", image,
        "-rl", env_marker, "/etc", "/usr", "/srv", "/config", "/data",
    )  # fmt: skip
    assert grep.stdout.strip() == "", grep.stdout


@pytest.mark.docker
@pytest.mark.parametrize("dockerfile", [API_DOCKERFILE, DASHBOARD_DOCKERFILE])
def test_ca13_ca36_of_spec_015_still_holds(
    build_image: Callable[..., str], dockerfile: str
) -> None:
    _acc015().test_ca36_build_context_filters_sentinels(build_image, dockerfile)


def test_extra_dockerignores_keep_the_env_rules() -> None:
    """Section 4.6: the api and dashboard ``.dockerignore`` keep ``**/.env*`` (and the
    case variant of SPEC-032); the Caddy one starts by excluding everything."""
    for component in ("api", "dashboard"):
        lines = _meaningful_lines(INFRA / "docker" / f"{component}.Dockerfile.dockerignore")
        assert "**/.env*" in lines, component
        assert any(line.startswith("**/.[eE][nN][vV]") for line in lines), component
    assert _meaningful_lines(CADDY_DOCKERIGNORE)[0] == "*"
