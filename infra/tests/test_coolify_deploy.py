"""Author tests of SPEC-039: deploy through Coolify (ADR-023).

Static checks read the files as YAML or text. The tests marked ``docker`` run only with
``PARTQC_DOCKER_TESTS=1`` and use temporary copies of the tracked tree (``copy_tracked_tree`` and
``build_image``): the real working tree is never written. Fictitious credentials are built at run
time and keys come from ``secrets.token_urlsafe``.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"
COMPOSE = INFRA / "compose.yaml"
CADDYFILE = INFRA / "Caddyfile"
CADDY_DOCKERFILE = INFRA / "docker" / "caddy.Dockerfile"
CADDY_DOCKERIGNORE = INFRA / "docker" / "caddy.Dockerfile.dockerignore"
PLAN = ROOT / "docs" / "deployment-plan.md"
ENV_EXAMPLE = ROOT / ".env.example"

CADDY_BASE = "caddy:2.11.7@sha256:685ae3d7c34d9b5f8caeddc5d14051db7bbd88ff1f5a2fa0c16bd8ca328fb7af"
API_ENVIRONMENT = {
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
DASHBOARD_ENVIRONMENT = {
    "API_BASE_URL": "https://${PUBLIC_HOST:?}",
    "READ_API_KEY": "${READ_API_KEY:?}",
    "MODEL_METRICS_PATH": "${MODEL_METRICS_PATH:-}",
}
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
ENV_VALUE = re.compile(r"^(https://)?\$\{[A-Z_]+(:\?|:-[^}]*)\}$")
CADDY_HEADER_LINES = [
    'Strict-Transport-Security "max-age=31536000"',
    'X-Content-Type-Options "nosniff"',
    'Referrer-Policy "no-referrer"',
    "Content-Security-Policy \"frame-ancestors 'self'\"",
    "-Server",
    "-Via",
]
DOMAIN = re.compile(r"\b[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}\b")
IPV4 = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b")
ENV_BLOCK_TITLE = (
    "# ---------- Coolify (variáveis do recurso) e infra/.env (conferência local) ----------"
)


def _services() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def _code(path: Path) -> list[str]:
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _instructions(path: Path) -> list[str]:
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


# ============================================================ static: compose (section 4.1)


def test_compose_has_no_ports_networks_labels_or_volumes() -> None:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert "networks" not in compose and "volumes" not in compose
    for name, service in compose["services"].items():
        for key in ("ports", "networks", "env_file", "container_name"):
            assert key not in service, (name, key)
        labels = service.get("labels") or {}
        keys = labels if isinstance(labels, dict) else [str(i).split("=", 1)[0] for i in labels]
        assert not [k for k in keys if k.startswith(("traefik.", "coolify."))], name


def test_compose_caddy_is_built_stateless_and_without_healthcheck() -> None:
    caddy = _services()["caddy"]
    assert caddy["build"] == {"context": "..", "dockerfile": "infra/docker/caddy.Dockerfile"}
    for key in ("image", "environment", "volumes", "healthcheck"):
        assert key not in caddy, key
    assert caddy["expose"] == ["80"]
    assert caddy["tmpfs"] == ["/tmp:size=64m", "/data:size=16m", "/config:size=16m"]
    assert caddy["depends_on"] == ["api", "dashboard"]  # a list: no condition


def test_compose_environment_is_exactly_the_spec() -> None:
    services = _services()
    assert services["api"]["environment"] == API_ENVIRONMENT
    assert services["dashboard"]["environment"] == DASHBOARD_ENVIRONMENT
    for name, service in services.items():
        environment = service.get("environment") or {}
        assert isinstance(environment, dict), name
        if name != "api":
            assert "DATABASE_URL" not in environment, name
        for key, value in environment.items():
            assert ENV_VALUE.fullmatch(value), (name, key, value)


def test_compose_has_no_caddy_version_and_no_domain() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "caddy:2." not in text
    assert "coolify.io" not in text and "sslip.io" not in text
    assert not IPV4.search(text)


# ============================================================ static: Caddyfile (section 4.2)


def test_caddyfile_single_site_on_port_80() -> None:
    code = _code(CADDYFILE)
    openings = [line for line in code if not line.startswith(("\t", " ")) and line.endswith("{")]
    assert openings == [":80 {"]
    assert code[0] == ":80 {" and code[-1] == "}"
    assert not [line for line in code if line.strip() == "{"]  # no global options block


@pytest.mark.parametrize(
    "token",
    [
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
        "handle_errors",
    ],
)
def test_caddyfile_forbidden_token(token: str) -> None:
    assert token not in "\n".join(_code(CADDYFILE))


def test_caddyfile_routes_headers_and_no_literal_host() -> None:
    code = _code(CADDYFILE)
    text = "\n".join(code)
    assert "\thandle /api/* {\n\t\treverse_proxy api:8000\n\t}" in text
    assert "\thandle {\n\t\treverse_proxy dashboard:8501\n\t}" in text
    start = code.index("\theader {")
    end = code.index("\t}", start)
    assert [line.strip() for line in code[start + 1 : end]] == CADDY_HEADER_LINES
    assert not [line for line in code if DOMAIN.search(line)]
    assert not IPV4.search(text)


def test_caddyfile_comments_name_coolify_and_spec_038() -> None:
    comments = "\n".join(
        line for line in CADDYFILE.read_text(encoding="utf-8").splitlines() if line.startswith("#")
    )
    for fragment in ("Coolify", "ADR-023", "HTTP", "handle_errors", "SPEC-038"):
        assert fragment in comments, fragment


# ============================================================ static: Caddy image (section 4.3)


def test_caddy_dockerfile_instructions() -> None:
    assert _instructions(CADDY_DOCKERFILE) == [
        f"FROM {CADDY_BASE}",
        "COPY infra/Caddyfile /etc/caddy/Caddyfile",
        'LABEL partqc.component="caddy"',
    ]


def test_caddy_dockerignore_admits_only_the_caddyfile() -> None:
    assert _code(CADDY_DOCKERIGNORE) == ["*", "!infra/Caddyfile"]


@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_api_and_dashboard_dockerignore_keep_the_env_rules(component: str) -> None:
    """Section 4.6: the .env written by Coolify (infra/.env) stays out of every image."""
    rules = _code(INFRA / "docker" / f"{component}.Dockerfile.dockerignore")
    assert "**/.env*" in rules and "**/.[eE][nN][vV]*" in rules
    assert [rule for rule in rules if rule.startswith("!.env")] == ["!.env.example"]


# ============================================================ static: .env.example (section 4.4)


def _env_block() -> list[str]:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    start = lines.index(ENV_BLOCK_TITLE)
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("# ----------"))
    return lines[start:end]


def test_env_example_coolify_block() -> None:
    block = _env_block()
    text = "\n".join(block)
    for fragment in ("Coolify", "Locked", "Literal", "ALERTS_", "TELEGRAM_", "config --quiet"):
        assert fragment in text, fragment
    for line in (
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
        assert line in block, line
    assert "ajuste a variável no Coolify e faça Redeploy" in text


def test_env_example_no_longer_names_the_vps_env_files() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for gone in ("infra/.env.api", "infra/.env.dashboard", 'rode "up -d"'):
        assert gone not in text, gone
    flat = " ".join(line.lstrip("# ").strip() for line in text.splitlines())
    assert (
        "Na VPS, READ_API_KEY e MODEL_METRICS_PATH vêm das variáveis do recurso no Coolify, e "
        "API_BASE_URL vem do infra/compose.yaml"
    ) in flat


# ============================================================ static: plan (sections 4.5, 4.8)


def test_plan_names_the_coolify_interface() -> None:
    text = PLAN.read_text(encoding="utf-8")
    for fragment in (
        "Base Directory",
        "`/infra`",
        "Docker Compose Location",
        "`/compose.yaml`",
        "https://<subdominio>:80",
        "Domains",
        "Environment Variables",
        "Locked",
        "Literal",
        "Preserve repository",
        "Raw",
        "Connect to predefined network",
        "com.docker.compose.project=<uuid>",
        "Manual Git Webhooks",
        "Webhook secret",
        "Deploy on push",
        "Just the push event",
        "Enable SSL verification",
    ):
        assert fragment in text, fragment


def test_plan_line_rules() -> None:
    for line in PLAN.read_text(encoding="utf-8").splitlines():
        if "Webhook secret" in line or "segredo do webhook" in line:
            assert "Coolify" in line or "GitHub" in line, line
        assert not re.search(r"secrets\.\w*WEBHOOK", line), line
        if "coolify-proxy" in line and re.search(r"restart|reinici|stop|parar|editar", line):
            assert "Nunca" in line or "nunca" in line, line
        if "Raw" in line:
            assert "Nunca" in line or "nunca" in line or "não" in line, line


def test_plan_has_no_webhook_url_nor_panel_host() -> None:
    text = PLAN.read_text(encoding="utf-8")
    assert not re.search(r"https?://[^\s>)`]*/webhooks/", text)
    assert not IPV4.search(text.replace("0.0.0.0", ""))


# ============================================================ docker (sections 4.1 to 4.6)

docker = pytest.mark.docker


def _support():
    return sys.modules["partqc_docker_support"]


def _run(cmd: list[str], timeout: int = 300, env: dict | None = None):
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False, env=env
    )


def _clean_environ() -> dict[str, str]:
    """The process environment without the compose variables (they come from the env file)."""
    names = {"PUBLIC_HOST", "DATABASE_URL", "READ_API_KEY", "MODEL_METRICS_PATH"}
    names |= {"MAX_BODY_BYTES", "LOG_LEVEL", *ALERT_DEFAULTS}
    return {
        k: v
        for k, v in os.environ.items()
        if k not in names and not k.endswith(("_MEM_LIMIT", "_CPUS", "_PIDS_LIMIT"))
    }


class FakeEnv:
    """Fictitious values for the three mandatory variables, built at run time."""

    def __init__(self) -> None:
        self.password = secrets.token_urlsafe(18)
        self.database_url = "postgresql://" + f"partqc:{self.password}@db.example.org:6543/postgres"
        self.read_api_key = secrets.token_urlsafe(32)

    def content(self, drop: str | None = None) -> bytes:
        values = {
            "PUBLIC_HOST": "partqc.example.org",
            "DATABASE_URL": self.database_url,
            "READ_API_KEY": self.read_api_key,
        }
        return "".join(f"{k}={v}\n" for k, v in values.items() if k != drop).encode()


@docker
def test_compose_config_resolves_every_variable(tmp_path: Path) -> None:
    fake = FakeEnv()
    copy = _support().copy_tracked_tree(tmp_path / "copy", {"infra/.env": fake.content()})
    result = _run(
        ["docker", "compose", "-f", str(copy / "infra" / "compose.yaml")]
        + ["config", "--format", "json"],
        env=_clean_environ(),
    )
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    api, dashboard = services["api"]["environment"], services["dashboard"]["environment"]
    assert dashboard["API_BASE_URL"] == "https://partqc.example.org"
    assert api["DATABASE_URL"] == fake.database_url
    assert api["READ_API_KEY"] == dashboard["READ_API_KEY"] == fake.read_api_key
    assert (api["MAX_BODY_BYTES"], api["LOG_LEVEL"]) == ("262144", "INFO")
    assert dashboard["MODEL_METRICS_PATH"] == ""
    assert {k: api[k] for k in ALERT_DEFAULTS} == ALERT_DEFAULTS
    for name in ("dashboard", "caddy"):
        names = set(services[name].get("environment") or {})
        assert not [n for n in names if n.startswith(("ALERTS_", "TELEGRAM_"))], name
    assert not [name for name, s in services.items() if "ports" in s]
    assert int(services["api"]["mem_limit"]) == 512 * 1024**2


@docker
@pytest.mark.parametrize("missing", ["PUBLIC_HOST", "DATABASE_URL", "READ_API_KEY"])
def test_compose_config_fails_without_a_mandatory_variable(tmp_path: Path, missing: str) -> None:
    fake = FakeEnv()
    copy = _support().copy_tracked_tree(tmp_path / "copy", {"infra/.env": fake.content(missing)})
    result = _run(
        ["docker", "compose", "-f", str(copy / "infra" / "compose.yaml")]
        + ["config", "--format", "json"],
        env=_clean_environ(),
    )
    assert result.returncode != 0
    assert missing in result.stderr
    assert fake.read_api_key not in result.stderr + result.stdout
    assert fake.password not in result.stderr + result.stdout


@docker
def test_compose_config_in_the_coolify_invocation(tmp_path: Path) -> None:
    """``--env-file``, ``--project-name`` and ``--project-directory``, as Coolify runs it."""
    fake = FakeEnv()
    copy = _support().copy_tracked_tree(tmp_path / "copy")
    assert not (copy / "infra" / ".env").exists()
    env_file = tmp_path / "coolify.env"
    env_file.write_bytes(fake.content())
    result = _run(
        ["docker", "compose", "--env-file", str(env_file)]
        + ["--project-name", "partqc-coolify-test", "--project-directory", str(copy / "infra")]
        + ["-f", str(copy / "infra" / "compose.yaml"), "config", "--format", "json"],
        env=_clean_environ(),
    )
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config["name"] == "partqc-coolify-test"
    for name in ("api", "dashboard", "caddy"):
        build = config["services"][name]["build"]
        assert Path(build["context"]) == copy.resolve()
        assert build["dockerfile"].endswith(f"infra/docker/{name}.Dockerfile")
    dashboard = config["services"]["dashboard"]["environment"]
    assert dashboard["API_BASE_URL"] == "https://partqc.example.org"


@pytest.fixture(scope="module")
def caddy_image(build_image) -> str:
    return build_image("infra/docker/caddy.Dockerfile")


def _walk(node: object) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _routes_with_proxy(node: object, path: tuple = ()) -> Iterator[tuple[list, dict]]:
    """Each ``reverse_proxy`` handler with the ``match`` lists of the routes above it."""
    if isinstance(node, dict):
        here = path + (node["match"],) if "match" in node else path
        if node.get("handler") == "reverse_proxy":
            yield [m for level in here for m in level], node
        for value in node.values():
            yield from _routes_with_proxy(value, here)
    elif isinstance(node, list):
        for value in node:
            yield from _routes_with_proxy(value, path)


@docker
def test_caddy_image_adapts_without_public_host(caddy_image: str) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PUBLIC_HOST"}
    cmd = _support().docker_run_args(
        caddy_image,
        "adapt",
        "--config",
        "/etc/caddy/Caddyfile",
        "--adapter",
        "caddyfile",
        entrypoint="caddy",
    )
    result = _run(cmd, env=env)
    assert result.returncode == 0, result.stderr
    assert "formatted" not in result.stderr.lower()
    config = json.loads(result.stdout)
    assert "tls" not in config["apps"]
    (server,) = config["apps"]["http"]["servers"].values()
    assert server["listen"] == [":80"]
    assert not [m for n in _walk(config) for m in n.get("match", []) if "host" in m]
    proxies = list(_routes_with_proxy(config))
    assert len(proxies) == 2
    by_dial = {tuple(u["dial"] for u in h["upstreams"]): matches for matches, h in proxies}
    assert set(by_dial) == {("api:8000",), ("dashboard:8501",)}
    assert [m["path"] for m in by_dial[("api:8000",)] if "path" in m] == [["/api/*"]]
    assert not [m for m in by_dial[("dashboard:8501",)] if "path" in m]
    (headers,) = [n["response"] for n in _walk(config) if n.get("handler") == "headers"]
    assert sorted(headers["delete"]) == ["Server", "Via"]
    assert headers["set"] == {
        "Strict-Transport-Security": ["max-age=31536000"],
        "X-Content-Type-Options": ["nosniff"],
        "Referrer-Policy": ["no-referrer"],
        "Content-Security-Policy": ["frame-ancestors 'self'"],
    }


@docker
def test_caddy_image_embeds_the_caddyfile_and_keeps_the_base_command(caddy_image: str) -> None:
    cat = _run(_support().docker_run_args(caddy_image, "/etc/caddy/Caddyfile", entrypoint="cat"))
    assert cat.returncode == 0, cat.stderr
    assert cat.stdout.encode() == CADDYFILE.read_bytes()
    built = json.loads(_run(["docker", "image", "inspect", caddy_image]).stdout)[0]["Config"]
    assert built["Labels"]["partqc.component"] == "caddy"
    assert not built.get("Healthcheck")
    pulled = _run(["docker", "image", "inspect", CADDY_BASE])
    if pulled.returncode != 0:
        assert _run(["docker", "pull", CADDY_BASE], timeout=600).returncode == 0
        pulled = _run(["docker", "image", "inspect", CADDY_BASE])
    base = json.loads(pulled.stdout)[0]["Config"]
    assert built["Cmd"] == base["Cmd"]
    assert built.get("Entrypoint") == base.get("Entrypoint")
    assert built.get("User", "") == base.get("User", "")


# -------------------------------------------------- end to end on a test network (CA-12 style)

NETWORK_TIMEOUT_S = 90
CADDY_RUN_ARGS = [
    "--read-only",
    "--tmpfs",
    "/tmp:size=64m",
    "--tmpfs",
    "/data:size=16m",
    "--tmpfs",
    "/config:size=16m",
    "--cap-drop",
    "ALL",
    "--cap-add",
    "NET_BIND_SERVICE",
    "--security-opt",
    "no-new-privileges",
    "--pids-limit",
    "256",
]
PROBE = r"""
import http.client, json, socket, sys
out = {}
for path in ("/api/v1/health", "/_stcore/health", "/docs", "/openapi.json"):
    c = http.client.HTTPConnection("caddy", 80, timeout=20)
    c.request("GET", path, headers={"Host": "partqc.example.org"})
    r = c.getresponse()
    out[path] = {"status": r.status, "headers": {k.lower(): v for k, v in r.getheaders()},
                 "body": r.read().decode("utf-8", "replace")[:4000]}
    c.close()
s = socket.socket()
s.settimeout(5)
out["443"] = s.connect_ex(("caddy", 443))
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def app_images(build_image) -> dict[str, str]:
    return {name: build_image(f"infra/docker/{name}.Dockerfile") for name in ("api", "dashboard")}


@docker
def test_caddy_routes_on_a_private_network(caddy_image: str, app_images: dict[str, str]) -> None:
    suffix = secrets.token_hex(4)
    network = f"partqc-test-net-{suffix}"
    key = secrets.token_urlsafe(32)
    fake = FakeEnv()
    containers: list[str] = []

    def start(alias: str, image: str, *args: str, env: dict[str, str] | None = None) -> str:
        name = f"partqc-test-{alias}-{suffix}"
        cmd = ["docker", "run", "-d", "--name", name, "--network", network]
        cmd += ["--network-alias", alias]
        for k, v in (env or {}).items():
            cmd += ["-e", f"{k}={v}"]
        result = _run([*cmd, *args, image])
        assert result.returncode == 0, result.stderr
        containers.append(name)
        return name

    assert _run(["docker", "network", "create", network]).returncode == 0
    try:
        start(
            "api", app_images["api"], env={"DATABASE_URL": fake.database_url, "READ_API_KEY": key}
        )
        dashboard = start(
            "dashboard",
            app_images["dashboard"],
            env={"API_BASE_URL": "https://partqc.example.org", "READ_API_KEY": key},
        )
        caddy = start("caddy", caddy_image, *CADDY_RUN_ARGS)
        deadline = time.monotonic() + NETWORK_TIMEOUT_S
        status = ""
        while time.monotonic() < deadline:
            status = _run(["docker", "inspect", "-f", "{{.State.Health.Status}}", dashboard])
            status = status.stdout.strip()
            if status == "healthy":
                break
            time.sleep(2)
        assert status == "healthy"
        probe = _run(
            ["docker", "run", "--rm", "--network", network, "--entrypoint", "python"]
            + [app_images["api"], "-c", PROBE],
            timeout=180,
        )
        assert probe.returncode == 0, probe.stderr
        out = json.loads(probe.stdout)
        health, stcore = out["/api/v1/health"], out["/_stcore/health"]
        assert health["status"] in {200, 503}
        assert "status" in json.loads(health["body"])
        assert (stcore["status"], stcore["body"].strip()) == (200, "ok")
        for response in (health, stcore):
            headers = response["headers"]
            assert headers["strict-transport-security"] == "max-age=31536000"
            assert headers["x-content-type-options"] == "nosniff"
            assert headers["referrer-policy"] == "no-referrer"
            assert headers["content-security-policy"] == "frame-ancestors 'self'"
            assert "server" not in headers and "via" not in headers
        assert "swagger" not in out["/docs"]["body"].lower()
        assert '"openapi"' not in out["/openapi.json"]["body"]
        assert out["443"] != 0  # refused: nothing listens on 443
        logs = _run(["docker", "logs", caddy])
        assert "read-only file system" not in (logs.stdout + logs.stderr).lower()
        state = _run(["docker", "inspect", "-f", "{{.State.Status}}", caddy]).stdout.strip()
        assert state == "running"
    finally:
        if containers:
            _run(["docker", "rm", "-f", "-v", *containers], timeout=120)
        _run(["docker", "network", "rm", network], timeout=60)


# -------------------------------------------------- the Coolify .env stays out (section 4.6)


@docker
def test_env_sentinels_stay_out_of_every_image(build_image) -> None:
    marker = "sentinel-" + secrets.token_hex(12)
    extra = {path: f"DATABASE_URL={marker}\n".encode() for path in ("infra/.env", ".env")}
    for component in ("api", "dashboard"):
        image = build_image(f"infra/docker/{component}.Dockerfile", extra)
        script = (
            "test -e /app/infra/.env && echo present-infra; "
            "test -e /app/.env && echo present-root; "
            f"grep -rl {marker} /app 2>/dev/null; true"
        )
        result = _run(_support().docker_run_args(image, "-c", script, entrypoint="sh"))
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "", (component, result.stdout)
    image = build_image("infra/docker/caddy.Dockerfile", extra)
    script = "find / -xdev -name '.env*' 2>/dev/null; test -e /app && echo present-app; true"
    result = _run(_support().docker_run_args(image, "-c", script, entrypoint="sh"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
