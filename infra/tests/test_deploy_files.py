"""Static checks of the deploy files (SPEC-015 sections 4.1 to 4.4 and 4.10 to 4.14).

No Docker, network or database: the files are read as YAML, TOML or text.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"
WORKFLOWS = ROOT / ".github" / "workflows"
DOCKERFILES = {
    "api": INFRA / "docker" / "api.Dockerfile",
    "dashboard": INFRA / "docker" / "dashboard.Dockerfile",
}
PUBLIC_HOST_REQUIRED = re.compile(r"^\$\{PUBLIC_HOST:\?[^}]*\}$")


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML (YAML 1.1) reads the key `on` as the boolean True.
    return workflow.get("on", workflow.get(True))


# ---------------------------------------------------------------- render.yaml (section 4.1)


def test_render_blueprint_is_the_free_cold_standby() -> None:
    blueprint = _yaml(INFRA / "render.yaml")
    (service,) = blueprint["services"]
    assert service["type"] == "web"
    assert service["plan"] == "free"
    assert service["runtime"] == "python"
    assert service["name"] == "partqc-api"
    assert service["branch"] == "main"
    assert service["buildCommand"] == (
        "pip install uv && uv sync --package qc-api --frozen --no-dev"
    )
    assert service["startCommand"] == (
        "uv run --package qc-api uvicorn qc_api.main:app --host 0.0.0.0 --port $PORT"
    )
    assert service["healthCheckPath"] == "/api/v1/health"
    env = {item["key"]: item for item in service["envVars"]}
    for name in ("DATABASE_URL", "READ_API_KEY"):
        assert env[name].get("sync") is False
        assert "value" not in env[name]


def test_render_python_version_matches_the_image_base() -> None:
    blueprint = _yaml(INFRA / "render.yaml")
    env = {item["key"]: item for item in blueprint["services"][0]["envVars"]}
    version = env["PYTHON_VERSION"]["value"]
    assert re.fullmatch(r"3\.12\.\d+", version)
    for dockerfile in DOCKERFILES.values():
        assert f"FROM python:{version}-slim-" in dockerfile.read_text(encoding="utf-8")


# ---------------------------------------------------------------- keepalive.yml (section 4.2)


def test_keepalive_workflow() -> None:
    text = (WORKFLOWS / "keepalive.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    triggers = _triggers(workflow)
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["schedule"] == [{"cron": "17 9 */3 * *"}]
    assert workflow["permissions"] == {}
    (job,) = workflow["jobs"].values()
    assert job["timeout-minutes"] == 10
    assert job["runs-on"] == "ubuntu-latest"
    (step,) = job["steps"]
    assert step["env"]["KEEPALIVE_URL"] == "${{ secrets.KEEPALIVE_URL }}"
    assert "curl -fsS --retry 5 --retry-delay 30" in step["run"]
    assert '"${KEEPALIVE_URL}/api/v1/health"' in step["run"]
    assert "http://" not in text and "https://" not in text


# ---------------------------------------------------------------- docker.yml (section 4.14)


def test_docker_workflow() -> None:
    text = (WORKFLOWS / "docker.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    triggers = _triggers(workflow)
    assert set(triggers) == {"pull_request", "push"}
    assert triggers["push"] == {"branches": ["main"]}
    assert workflow["permissions"] == {"contents": "read"}
    (job,) = workflow["jobs"].values()
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] <= 30
    assert job["services"]["postgres"]["image"] == "postgres:16"
    assert job["env"]["PARTQC_DOCKER_TESTS"] == "1"
    ci = _yaml(WORKFLOWS / "ci.yml")
    assert job["env"]["TEST_DATABASE_URL"] == ci["jobs"]["test"]["env"]["TEST_DATABASE_URL"]
    uses = [step["uses"] for step in job["steps"] if "uses" in step]
    assert uses[0].startswith("actions/checkout@v")
    assert uses[1].startswith("astral-sh/setup-uv@v")
    assert not any(ref.endswith(("@main", "@master")) for ref in uses)
    runs = [step.get("run", "") for step in job["steps"]]
    assert runs.index("uv sync --all-packages --frozen") < runs.index("uv run pytest -m docker -q")
    for forbidden in ("secrets.", "docker login", "docker push"):
        assert forbidden not in text
    assert len(ci["jobs"]) == 1


# ---------------------------------------------------------------- .streamlit/config.toml (4.4)


def test_streamlit_config() -> None:
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert config["browser"]["gatherUsageStats"] is False
    assert config["server"]["headless"] is True
    assert config["client"]["showErrorDetails"] in {"none", "type"}
    for key in ("address", "port", "baseUrlPath", "fileWatcherType"):
        assert key not in config["server"]
    for key in ("enableCORS", "enableXsrfProtection"):
        assert config["server"].get(key, True) is True
    keys = [f"{section}.{key}" for section, values in config.items() for key in values]
    assert not [k for k in keys if re.search("key|secret|token", k, re.IGNORECASE)]


# ---------------------------------------------------------------- Dockerfiles (section 4.10)


def _instructions(path: Path) -> list[str]:
    """Dockerfile instructions with the line continuations joined, comments dropped."""
    lines: list[str] = []
    current = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not current and (not stripped or stripped.startswith("#")):
            continue
        if stripped.endswith("\\"):
            current += stripped[:-1].strip() + " "
            continue
        lines.append(current + stripped)
        current = ""
    return lines


@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_dockerfile_rules(component: str) -> None:
    path = DOCKERFILES[component]
    text = path.read_text(encoding="utf-8")
    instructions = _instructions(path)
    froms = [line for line in instructions if line.startswith("FROM ")]
    assert froms
    for line in froms:
        assert re.fullmatch(
            r"FROM python:3\.12\.\d+-slim-(bookworm|trixie)(@sha256:[0-9a-f]{64})?( AS \w+)?", line
        )
    uv_copies = [line for line in instructions if "ghcr.io/astral-sh/uv:" in line]
    assert len(uv_copies) == 1
    assert re.search(r"uv:\d+\.\d+\.\d+(@sha256:[0-9a-f]{64})? /uv /uvx /bin/", uv_copies[0])
    package = "qc-api" if component == "api" else "qc-dashboard"
    runs = [i for i, line in enumerate(instructions) if line.startswith("RUN ")]
    assert any(f"uv sync --package {package} --frozen --no-dev" in instructions[i] for i in runs)
    assert "UV_PYTHON_DOWNLOADS=0" in text
    assert "WORKDIR /app" in instructions
    for forbidden in (
        "--no-editable",
        "--extra",
        "--all-extras",
        "--all-packages",
        "pip install",
        "latest",
    ):
        assert forbidden not in text
    users = [i for i, line in enumerate(instructions) if line.startswith("USER ")]
    assert instructions[users[-1]] == "USER 10001:10001"
    assert users[-1] > runs[-1]
    healthchecks = [line for line in instructions if line.startswith("HEALTHCHECK ")]
    assert len(healthchecks) == 1
    assert "--interval=60s" in healthchecks[0]
    health_path = "/api/v1/health" if component == "api" else "/_stcore/health"
    assert health_path in healthchecks[0]
    (cmd,) = [line for line in instructions if line.startswith("CMD ")]
    expected = {
        "api": ["uvicorn", "qc_api.main:app", "--host", "0.0.0.0", "--port", "8000"],
        "dashboard": [
            "streamlit",
            "run",
            "dashboard/app.py",
            "--server.address=0.0.0.0",
            "--server.port=8501",
            "--server.fileWatcherType=none",
        ],
    }[component]
    assert json.loads(cmd.removeprefix("CMD ")) == expected
    assert f'LABEL partqc.component="{component}"' in instructions
    for line in instructions:
        if line.startswith(("ENV ", "ARG ")):
            names = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=", line.split(" ", 1)[1]) or [
                line.split()[1]
            ]
            for name in names:
                assert not re.search("DATABASE_URL|API_KEY|TOKEN|PASSWORD|SECRET", name)


def test_both_dockerfiles_use_the_same_uv_and_base() -> None:
    def pins(path: Path) -> tuple[str, str]:
        text = path.read_text(encoding="utf-8")
        uv = re.search(r"ghcr\.io/astral-sh/uv:(\S+)", text)
        base = re.search(r"^FROM (\S+)", text, re.MULTILINE)
        assert uv and base
        return uv.group(1), base.group(1)

    assert pins(DOCKERFILES["api"]) == pins(DOCKERFILES["dashboard"])


# ---------------------------------------------------------------- .dockerignore (section 4.11)

REQUIRED_IGNORES = [
    ".git",
    "**/.env*",
    ".streamlit/secrets.toml",
    ".claude/",
    "notas-locais/",
    "ml/data/",
    "edge/data/",
    "data/",
    "**/*.jpg",
    "**/*.jpeg",
    "**/*.png",
    "**/*.heic",
    "**/*.webp",
    "ml/models/**/*.onnx",
    "ml/models/**/*.pt",
    "ml/models/**/*.pth",
    "ml/checkpoints/",
    "**/*.sqlite",
    "**/*.sqlite3",
    "**/*.db",
    "**/.venv",
    "**/__pycache__",
    ".pytest_cache",
    ".ruff_cache",
]


@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_dockerignore_rules(component: str) -> None:
    path = INFRA / "docker" / f"{component}.Dockerfile.dockerignore"
    rules = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for rule in REQUIRED_IGNORES:
        assert rule in rules, rule
    exceptions = [rule for rule in rules if rule.startswith("!")]
    assert set(exceptions) <= {
        "!.env.example",
        "!ml/reports/**/*.png",
        "!ml/reports/**/*.[pP][nN][gG]",
    }
    # RV-04 (r1): the patterns are case-sensitive, so each sensitive extension and .env also
    # appear with character classes, before their exceptions.
    for rule in (
        "**/.[eE][nN][vV]*",
        "**/*.[jJ][pP][gG]",
        "**/*.[jJ][pP][eE][gG]",
        "**/*.[pP][nN][gG]",
        "**/*.[hH][eE][iI][cC]",
        "**/*.[wW][eE][bB][pP]",
        "**/*.[oO][nN][nN][xX]",
        "**/*.[sS][qQ][lL][iI][tT][eE]",
        "**/*.[sS][qQ][lL][iI][tT][eE]3",
        "**/*.[dD][bB]",
    ):
        assert rule in rules, rule
    assert rules.index("!.env.example") > rules.index("**/.[eE][nN][vV]*")
    assert rules.index("!ml/reports/**/*.[pP][nN][gG]") > rules.index("**/*.[pP][nN][gG]")
    # The exception must come after the exclusion it opens (the last matching rule wins).
    assert rules.index("!ml/reports/**/*.png") > rules.index("**/*.png")
    assert rules.index("!.env.example") > rules.index("**/.env*")
    for kept in ("pyproject.toml", "uv.lock", "packages/", "ml/reports/", ".streamlit/"):
        assert kept not in rules and kept.rstrip("/") not in rules


def test_no_root_dockerignore() -> None:
    assert not (ROOT / ".dockerignore").exists()


# ---------------------------------------------------------------- compose.yaml (section 4.12)

LIMITS = {
    "api": ("${API_MEM_LIMIT:-512m}", "${API_CPUS:-1.0}"),
    "dashboard": ("${DASHBOARD_MEM_LIMIT:-1g}", "${DASHBOARD_CPUS:-1.0}"),
    "caddy": ("${CADDY_MEM_LIMIT:-256m}", "${CADDY_CPUS:-0.5}"),
}


def test_compose_structure() -> None:
    compose = _yaml(INFRA / "compose.yaml")
    services = compose["services"]
    assert compose["name"] == "partqc"
    assert set(services) == {"caddy", "api", "dashboard"}
    assert services["caddy"]["ports"] == ["80:80", "443:443", "443:443/udp"]
    assert "ports" not in services["api"] and "ports" not in services["dashboard"]
    assert services["api"]["expose"] == ["8000"]
    assert services["dashboard"]["expose"] == ["8501"]
    for name, service in services.items():
        for key in ("privileged", "network_mode", "pid", "container_name"):
            assert key not in service, (name, key)
        assert not [v for v in service.get("volumes", []) if "docker.sock" in str(v)]
        assert service["restart"] == "unless-stopped"
        assert "no-new-privileges:true" in service["security_opt"]
        assert service["logging"] == {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "3"},
        }
        assert (service["mem_limit"], service["cpus"]) == LIMITS[name]
        assert service["cap_drop"] == ["ALL"]
        assert not {"DATABASE_URL", "READ_API_KEY"} & set(service.get("environment") or {})
    for name in ("api", "dashboard"):
        assert services[name]["build"] == {
            "context": "..",
            "dockerfile": f"infra/docker/{name}.Dockerfile",
        }
        assert services[name]["env_file"] == [f".env.{name}"]
    assert re.fullmatch(
        r"https://\$\{PUBLIC_HOST:\?[^}]*\}", services["dashboard"]["environment"]["API_BASE_URL"]
    )
    caddy = services["caddy"]
    assert PUBLIC_HOST_REQUIRED.fullmatch(caddy["environment"]["PUBLIC_HOST"])
    (alias,) = caddy["networks"]["partqc"]["aliases"]
    assert PUBLIC_HOST_REQUIRED.fullmatch(alias)
    assert re.fullmatch(r"caddy:2\.\d+\.\d+(-alpine)?(@sha256:[0-9a-f]{64})?", caddy["image"])
    assert set(caddy["volumes"]) >= {
        "./Caddyfile:/etc/caddy/Caddyfile:ro",
        "caddy_data:/data",
        "caddy_config:/config",
    }
    assert set(compose["volumes"]) == {"caddy_data", "caddy_config"}
    assert caddy["cap_add"] == ["NET_BIND_SERVICE"]
    assert caddy["depends_on"] == ["api", "dashboard"]
    assert compose["networks"]["partqc"].get("internal") is not True


def test_compose_caddy_version_matches_nothing_floating() -> None:
    image = _yaml(INFRA / "compose.yaml")["services"]["caddy"]["image"]
    assert not image.endswith((":latest", ":2", ":alpine"))


# ---------------------------------------------------------------- Caddyfile (section 4.13)


def _caddy_code() -> list[str]:
    return [
        line
        for line in (INFRA / "Caddyfile").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_caddyfile_routes_and_headers() -> None:
    code = _caddy_code()
    text = "\n".join(code)
    assert code[0] == "{$PUBLIC_HOST} {"
    assert not [line for line in code if line.strip() == "{"]
    assert "\thandle /api/* {\n\t\treverse_proxy api:8000\n\t}" in text
    assert "\thandle {\n\t\treverse_proxy dashboard:8501\n\t}" in text
    for forbidden in (
        "handle_path",
        "tls internal",
        "acme_ca",
        "local_certs",
        "includeSubDomains",
        "preload",
        "/docs",
        "openapi",
    ):
        assert forbidden not in text
    assert not re.search(r"^\s*log\b", text, re.MULTILINE)
    assert 'Strict-Transport-Security "max-age=31536000"' in text
    assert 'X-Content-Type-Options "nosniff"' in text
    domain = re.compile(r"\b[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}\b")
    assert not [line for line in code if domain.search(line)]
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text)


# ---------------------------------------------------------------- R-13: no IPv4 literal (4.12)

R13_FILES = [
    INFRA / "compose.yaml",
    INFRA / "Caddyfile",
    INFRA / "render.yaml",
    WORKFLOWS / "docker.yml",
    WORKFLOWS / "keepalive.yml",
    ROOT / ".env.example",
    *sorted((INFRA / "docker").iterdir()),
]
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


@pytest.mark.parametrize("path", R13_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_ipv4_literal(path: Path) -> None:
    found = set(IPV4.findall(path.read_text(encoding="utf-8")))
    assert found <= {"0.0.0.0", "127.0.0.1"}


# ---------------------------------------------------------------- .env.example and .gitignore


def test_env_example_vps_block() -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    for line in (
        "PUBLIC_HOST=<subdominio>",
        "API_MEM_LIMIT=512m",
        "API_CPUS=1.0",
        "DASHBOARD_MEM_LIMIT=1g",
        "DASHBOARD_CPUS=1.0",
        "CADDY_MEM_LIMIT=256m",
        "CADDY_CPUS=0.5",
        "CLOUD_API_URL=https://<subdominio>",
        "# ---------- Segredos fora do .env (GitHub Secrets) ----------",
    ):
        assert line in lines, line
    text = "\n".join(lines)
    assert "onrender.com" not in text
    assert "Streamlit Community Cloud" not in text
    assert "Streamlit Secrets" not in text


def test_env_example_compose_values_match_the_compose_defaults() -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    values = dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))
    for mem, cpus in LIMITS.values():
        for expr in (mem, cpus):
            name, default = re.fullmatch(r"\$\{(\w+):-([^}]+)\}", expr).groups()
            assert values[name] == default


@pytest.mark.parametrize(
    ("path", "ignored"),
    [
        (".env", True),
        (".env.prod", True),
        (".env.migrate", True),
        ("infra/.env", True),
        ("infra/.env.api", True),
        ("infra/.env.dashboard", True),
        (".streamlit/secrets.toml", True),
        (".env.example", False),
        (".streamlit/config.toml", False),
    ],
)
def test_gitignore_covers_the_vps_env_files(path: str, ignored: bool) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT, check=False, timeout=30
    )
    assert (result.returncode == 0) is ignored


# ---------------------------------------------------------------- R-03: secret scan (CA-05)

# Built at run time, so that this file does not match the patterns itself.
# Patterns with no exception (CA-05, first item).
STRICT_SECRET_PATTERNS = [
    re.compile("ey" + r"J[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),
    re.compile("-----BEGIN " + r"[A-Z ]*PRIVATE KEY-----"),
    re.compile("service" + r"_role\s*[:=]\s*\S{20,}"),
]
# Postgres URL with credentials (CA-05, second item), accepted only by one of the three rules.
POSTGRES_URL = re.compile("postgres(ql)?" + r"://(?P<user>[^\s:/@]+):(?P<password>[^\s@]+)@")
DOC_MARKER = re.compile(r"^<[a-z][a-z_-]*>$")
RUNTIME_VALUE = re.compile(r"^\$?\{[A-Za-z_][A-Za-z0-9_]*\}$")
ELLIPSIS = "\u2026"
KNOWN_FICTITIOUS = (
    "u:pw@" + "127.0.0.1",
    "u:s3cr3t-pw@" + "127.0.0.1",
    "postgres:" + "postgres@localhost",
    "postgres:" + "postgres@...",
    "u:senha@" + ELLIPSIS,
)


def postgres_url_allowed(text: str, match: re.Match[str]) -> bool:
    """Rules 1 to 3 of CA-05 for one occurrence of ``POSTGRES_URL`` in ``text``."""
    password = match.group("password")
    if DOC_MARKER.fullmatch(password) or password in {ELLIPSIS, "..."}:
        return True  # 1. documentation marker
    if RUNTIME_VALUE.fullmatch(password):
        return True  # 2. value built at run time (the file holds a variable name)
    after_scheme = text[match.start() + match.group(0).index("://") + 3 :]
    return after_scheme.startswith(KNOWN_FICTITIOUS)  # 3. known fictitious credential


def secret_findings(text: str) -> list[str]:
    found = [p.pattern for p in STRICT_SECRET_PATTERNS if p.search(text)]
    found += [m.group(0) for m in POSTGRES_URL.finditer(text) if not postgres_url_allowed(text, m)]
    return found


def _ca05_files() -> list[Path]:
    """Every tracked file outside ``docs/`` that exists in the working tree (none skipped)."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True, timeout=30
    ).stdout.decode("utf-8")
    paths = [ROOT / rel for rel in out.split("\0") if rel and not rel.startswith("docs/")]
    return [path for path in paths if path.is_file()]


def test_no_secret_material_in_tracked_files() -> None:
    found: list[str] = []
    for path in _ca05_files():
        text = path.read_bytes().decode("utf-8", errors="replace")
        found += [f"{path.relative_to(ROOT)}: {item}" for item in secret_findings(text)]
    assert found == []


@pytest.mark.parametrize(
    ("sample", "allowed"),
    [
        ("postgresql://" + "<user>:<password>@<host>:6543/postgres", True),
        ("postgres://" + ELLIPSIS + ":" + ELLIPSIS + "@", True),
        ("postgresql://" + "postgres:<senha>@host", True),
        ("postgresql://" + "u:{SECRET}@127.0.0.1:1/x", True),
        ("postgresql://" + "u:${DB_PASSWORD}@db", True),
        ("postgresql://" + "u:s3cr3t-pw@127.0.0.1:6543/x_test", True),
        ("postgresql://" + "postgres:" + "postgres@localhost:55432/partqc_test", True),
        ("postgresql://" + "u:senha@" + ELLIPSIS, True),
        ("postgresql://" + "u:s3cr3t-pw@db.example.org/x", False),
        ("postgresql://" + "postgres.abc:Real" + "Pass123@aws-0-sa-east-1.pooler", False),
        ("postgresql://" + "u:{SECRET}x@db", False),
        ("postgresql://" + "u:<Password>@db", False),
    ],
)
def test_ca05_rules(sample: str, allowed: bool) -> None:
    assert (secret_findings(sample) == []) is allowed


def test_ca05_strict_patterns_have_no_exception() -> None:
    jwt = "ey" + "J" + "a" * 24 + "." + "b" * 24
    key = "-----BEGIN " + "RSA PRIVATE KEY-----"
    role = "service" + "_role = " + "x" * 24
    for sample in (jwt, key, role):
        assert secret_findings(sample) != []


# ---------------------------------------------------------------- docs/deployment-plan.md

PLAN = ROOT / "docs" / "deployment-plan.md"


def _plan_lines() -> list[str]:
    return PLAN.read_text(encoding="utf-8").splitlines()


def _section(title_fragment: str) -> list[str]:
    lines = _plan_lines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("## ") and title_fragment in line
    )
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


def test_plan_accepted_risks() -> None:
    risks = _section("Riscos aceitos")
    text = "\n".join(risks)
    assert any("pool" in line and "503" in line for line in risks)
    assert any("psycopg.pool" in line for line in risks)
    for url in (
        "caddyserver.com/docs/caddyfile/directives",
        "letsencrypt.org/docs/ct-logs",
        "letsencrypt.org/docs/rate-limits",
    ):
        assert url in text
    (timeout_line,) = [line for line in risks if "57014" in line]
    assert "503" in timeout_line and "Database unavailable" in timeout_line
    assert "500 genérico" not in timeout_line


def test_plan_operation_rules() -> None:
    lines = _plan_lines()
    text = "\n".join(lines)
    for fragment in (
        "statement_timeout",
        "rolconfig",
        "token_urlsafe(32)",
        "docker compose -f infra/compose.yaml up -d --build",
        "git pull --ff-only",
        "free -h",
        "nproc",
        "chmod 600",
        "<subdominio>",
        "--filter label=partqc.component",
    ):
        assert fragment in text, fragment
    for line in lines:
        if "register_device.py" in line:
            assert "--env-file" in line and "--database-url" not in line, line
        if "simulate.py" in line:
            assert "--env-file" in line, line
        if "docker compose" in line and re.search(r"(^|\s)config(\s|$|`)", line):
            assert "--quiet" in line, line
        if any(
            danger in line
            for danger in (
                "ufw reset",
                "ufw default",
                "ufw delete",
                "ufw --force",
                "iptables -F",
                "docker system prune",
                "volume prune",
                "down -v",
            )
        ):
            assert "Nunca" in line or "nunca" in line, line
    (render,) = [line for line in lines if line.startswith("| Render")]
    for fragment in ("512 MB", "0,1 CPU", "render.com/docs/compute-plans"):
        assert fragment in render
    assert "não confirmado" not in render
    table = _section("Serviços e limites")
    outside = [line for line in lines if line not in table]
    assert not [line for line in outside if "streamlit.app" in line or "Koyeb" in line]


@pytest.mark.parametrize("path", [PLAN, ROOT / ".env.example"], ids=["plan", "env-example"])
def test_public_urls_are_placeholders(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for match in re.finditer(r"PUBLIC_HOST=(\S*)", text):
        assert match.group(1) == "<subdominio>"
    for match in re.finditer(r"(CLOUD_API_URL|DASHBOARD_URL|KEEPALIVE_URL)=(\S*)", text):
        value = match.group(2).strip("`")
        if value:
            assert value.startswith(("https://<subdominio>", "https://<servico>.onrender.com"))
