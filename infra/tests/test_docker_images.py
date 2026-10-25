"""Docker smoke tests of the deploy (SPEC-015 sections 4.10 to 4.13). Marked ``docker``.

They run only with ``PARTQC_DOCKER_TESTS=1`` (workflow ``docker`` in the CI). Builds use a
temporary copy of the tracked tree (``build_image``), containers run with ``--network none``,
and the compose project is a temporary copy too: the real working tree is never written.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
support = sys.modules["partqc_docker_support"]

SENTINELS_ABSENT = [
    ".env",
    ".env.prod",
    ".env.migrate",
    "infra/.env",
    "infra/.env.api",
    "infra/.env.dashboard",
    ".streamlit/secrets.toml",
    ".claude/settings.local.json",
    "notas-locais/diario.md",
    ".venv/sentinela-do-host",
    "ml/data/raw/screw/good/S-001__a__x.jpg",
    "edge/data/outbox.sqlite3",
    "foto.jpg",
    "foto.png",
    "ml/models/partqc-sentinel-v0/model.onnx",
    # RV-04 (r1): the same files with upper-case names or extensions
    "infra/.ENV.API",
    "FOTO.JPG",
    "IMG_0001.HEIC",
    "Foto.Png",
    "edge/data/OUTBOX.SQLITE3",
    "ml/models/partqc-sentinel-v0/MODEL.ONNX",
]
SENTINELS_DASHBOARD = [
    "ml/models/partqc-sentinel-v0/metrics.json",
    "ml/reports/partqc-sentinel-v0/type_confusion.png",
    "ml/reports/partqc-sentinel-v0/GRADE_CONFUSION.PNG",
]
EXTRA_FILES = {path: b"sentinel\n" for path in SENTINELS_ABSENT + SENTINELS_DASHBOARD}
FORBIDDEN_MODULES = ["torch", "torchvision", "timm", "onnx", "onnxruntime"]


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


@pytest.fixture(scope="module")
def images(build_image) -> dict[str, str]:
    return {
        name: build_image(f"infra/docker/{name}.Dockerfile", EXTRA_FILES)
        for name in ("api", "dashboard")
    }


@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_image_has_no_ml_and_only_its_package(images: dict[str, str], component: str) -> None:
    names = FORBIDDEN_MODULES + ["qc_api", "qc_dashboard", "qc_contracts", "streamlit", "psycopg"]
    script = (
        "import importlib.util as u, json, sys; "
        f"names = {names!r}; "
        "print(json.dumps({'py': list(sys.version_info[:2]), "
        "'found': {n: u.find_spec(n) is not None for n in names}}))"
    )
    result = _run(support.docker_run_args(images[component], "-c", script, entrypoint="python"))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["py"] == [3, 12]
    found = report["found"]
    assert not [m for m in FORBIDDEN_MODULES if found[m]]
    assert found["qc_contracts"]
    if component == "api":
        assert found["qc_api"] and not found["streamlit"]
    else:
        assert found["qc_dashboard"] and found["streamlit"] and not found["psycopg"]


@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_build_context_filters_secrets_data_and_weights(
    images: dict[str, str], component: str
) -> None:
    checks = " ; ".join(f'test -e "/app/{p}" && echo "present {p}"' for p in SENTINELS_ABSENT)
    result = _run(
        support.docker_run_args(images[component], "-c", checks + " ; true", entrypoint="sh")
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
    if component == "dashboard":
        kept = SENTINELS_DASHBOARD + [".streamlit/config.toml"]
        checks = " && ".join(f'test -f "/app/{p}"' for p in kept)
        assert (
            _run(
                support.docker_run_args(images[component], "-c", checks, entrypoint="sh")
            ).returncode
            == 0
        )


@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_image_config(images: dict[str, str], component: str) -> None:
    result = _run(["docker", "image", "inspect", images[component]])
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)[0]["Config"]
    assert config["User"] == "10001:10001"
    assert config["WorkingDir"] == "/app"
    assert config["Labels"]["partqc.component"] == component
    health = config["Healthcheck"]
    assert health["Test"][0] == "CMD"
    assert ("/api/v1/health" if component == "api" else "/_stcore/health") in " ".join(
        health["Test"]
    )
    assert health["Interval"] == 60_000_000_000
    assert not {"uv", "uvx"} & set((config.get("Entrypoint") or []) + (config.get("Cmd") or []))
    uid = _run(support.docker_run_args(images[component], "-u", entrypoint="id"))
    assert uid.stdout.strip() == "10001"


@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_uv_cache_is_not_in_the_image(images: dict[str, str], component: str) -> None:
    """RV-01 (r1): the uv cache stays in the BuildKit cache mount, not in a layer."""
    script = "test ! -e /home/app/.cache && test ! -e /root/.cache/uv && echo clean"
    result = _run(support.docker_run_args(images[component], "-c", script, entrypoint="sh"))
    assert result.stdout.strip() == "clean", result.stdout + result.stderr


def test_dashboard_repo_root_is_app(images: dict[str, str]) -> None:
    script = (
        "from qc_dashboard import config; "
        "print(config.REPO_ROOT); print(config.get_model_metrics_path())"
    )
    result = _run(support.docker_run_args(images["dashboard"], "-c", script, entrypoint="python"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["/app", "/app/ml/models/partqc-mnv3-v1/metrics.json"]


# ---------------------------------------------------------------- compose config (section 4.12)


def _compose_copy(tmp_path: Path, env: bytes | None, with_api_env: bool = True) -> Path:
    extra = {
        "infra/.env.dashboard": b"READ_API_KEY=" + secrets.token_urlsafe(32).encode() + b"\n",
    }
    if env is not None:
        extra["infra/.env"] = env
    if with_api_env:
        extra["infra/.env.api"] = (
            b"DATABASE_URL=postgresql://<user>:<password>@db.example.org:6543/postgres\n"
            b"READ_API_KEY=" + secrets.token_urlsafe(32).encode() + b"\n"
        )
    return support.copy_tracked_tree(tmp_path / "copy", extra) / "infra" / "compose.yaml"


def _compose_config(compose: Path) -> subprocess.CompletedProcess:
    env = {
        k: v
        for k, v in os.environ.items()
        if k != "PUBLIC_HOST" and not k.endswith(("_MEM_LIMIT", "_CPUS", "_PIDS_LIMIT"))
    }
    return subprocess.run(
        ["docker", "compose", "-f", str(compose), "config", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )


def test_compose_resolves_host_and_limits(tmp_path: Path) -> None:
    result = _compose_config(_compose_copy(tmp_path, b"PUBLIC_HOST=partqc.example.org\n"))
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert services["dashboard"]["environment"]["API_BASE_URL"] == "https://partqc.example.org"
    assert services["caddy"]["networks"]["partqc"]["aliases"] == ["partqc.example.org"]
    assert int(services["api"]["mem_limit"]) == 512 * 1024**2
    assert int(services["dashboard"]["mem_limit"]) == 1024**3
    for service in services.values():  # SPEC-032 section 4.4
        assert int(service["pids_limit"]) == 256
        assert service["read_only"] is True
        assert service["tmpfs"] == ["/tmp:size=64m"]


def test_compose_config_quiet_with_the_hardening(tmp_path: Path) -> None:
    """CA-06 of SPEC-032: ``config --quiet`` accepts the interpolated pids_limit."""
    compose = _compose_copy(tmp_path, b"PUBLIC_HOST=partqc.example.org\n")
    env = {k: v for k, v in os.environ.items() if not k.endswith("_PIDS_LIMIT")}
    env.pop("PUBLIC_HOST", None)
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose), "config", "--quiet"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_compose_pids_limit_override(tmp_path: Path) -> None:
    env = b"PUBLIC_HOST=partqc.example.org\nDASHBOARD_PIDS_LIMIT=512\n"
    result = _compose_config(_compose_copy(tmp_path, env))
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert int(services["dashboard"]["pids_limit"]) == 512
    assert int(services["api"]["pids_limit"]) == 256


def test_compose_limit_override(tmp_path: Path) -> None:
    env = b"PUBLIC_HOST=partqc.example.org\nAPI_MEM_LIMIT=768m\n"
    result = _compose_config(_compose_copy(tmp_path, env))
    assert result.returncode == 0, result.stderr
    assert int(json.loads(result.stdout)["services"]["api"]["mem_limit"]) == 768 * 1024**2


def test_compose_requires_public_host(tmp_path: Path) -> None:
    result = _compose_config(_compose_copy(tmp_path, b"API_CPUS=1.0\n"))
    assert result.returncode != 0
    assert "PUBLIC_HOST" in result.stderr


def test_compose_requires_the_api_env_file(tmp_path: Path) -> None:
    compose = _compose_copy(tmp_path, b"PUBLIC_HOST=partqc.example.org\n", with_api_env=False)
    assert _compose_config(compose).returncode != 0


# ---------------------------------------------------------------- Caddyfile (section 4.13)


def _walk(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_caddy_adapts_the_caddyfile() -> None:
    image = yaml.safe_load((ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8"))[
        "services"
    ]["caddy"]["image"]
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-e",
        "PUBLIC_HOST=partqc.example.org",
        "-v",
        f"{ROOT / 'infra' / 'Caddyfile'}:/etc/caddy/Caddyfile:ro",
        image,
        "caddy",
        "adapt",
        "--config",
        "/etc/caddy/Caddyfile",
        "--adapter",
        "caddyfile",
    ]
    result = _run(cmd)
    assert result.returncode == 0, result.stderr
    assert "formatted" not in result.stderr.lower()
    config = json.loads(result.stdout)
    nodes = list(_walk(config))
    hosts = {h for n in nodes for m in n.get("match", []) for h in m.get("host", [])}
    assert hosts == {"partqc.example.org"}
    dials = [
        u["dial"] for n in nodes if n.get("handler") == "reverse_proxy" for u in n["upstreams"]
    ]
    assert sorted(dials) == ["api:8000", "dashboard:8501"]
    headers = [n for n in nodes if n.get("handler") == "headers"]
    assert any(
        h["response"]["set"].get("Strict-Transport-Security") == ["max-age=31536000"]
        for h in headers
    )
    # SPEC-032 section 4.3: one deferred handler deletes Server and Via and sets the 4 headers.
    (response,) = [h["response"] for h in headers]
    assert response["deferred"] is True
    assert sorted(response["delete"]) == ["Server", "Via"]
    assert response["set"] == {
        "Strict-Transport-Security": ["max-age=31536000"],
        "X-Content-Type-Options": ["nosniff"],
        "Referrer-Policy": ["no-referrer"],
        "Content-Security-Policy": ["frame-ancestors 'self'"],
    }


def _caddy_image() -> str:
    compose = yaml.safe_load((ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8"))
    return compose["services"]["caddy"]["image"]


def _site_header_block() -> str:
    text = (ROOT / "infra" / "Caddyfile").read_text(encoding="utf-8")
    start = text.index("\theader {")
    return text[start : text.index("\n\t}\n", start) + len("\n\t}\n")]


def test_caddy_header_block_strips_server_and_via_behind_the_proxy(tmp_path: Path) -> None:
    """The real header block of infra/Caddyfile, behind a reverse_proxy whose upstream answers
    with ``Server: uvicorn`` (SPEC-032 section 4.3): no Server, no Via, and the 4 headers."""
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text(
        "{\n\tauto_https off\n\tadmin off\n}\n\n"
        ":8080 {\n" + _site_header_block() + "\treverse_proxy 127.0.0.1:9000\n}\n\n"
        ':9000 {\n\theader Server uvicorn\n\trespond "ok"\n}\n',
        encoding="utf-8",
    )
    script = (
        "caddy start --config /etc/caddy/Caddyfile >/dev/null 2>&1; "
        "for i in 1 2 3 4 5 6 7 8 9 10; do "
        "wget -S -O /dev/null http://127.0.0.1:8080/ 2>/tmp/h && break; sleep 0.5; done; "
        "cat /tmp/h"
    )
    result = _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{caddyfile}:/etc/caddy/Caddyfile:ro",
            "--entrypoint",
            "sh",
            _caddy_image(),
            "-c",
            script,
        ]
    )
    assert result.returncode == 0, result.stderr
    headers = {
        line.strip().split(":", 1)[0].lower(): line.strip().split(":", 1)[1].strip()
        for line in result.stdout.splitlines()
        if ":" in line and not line.strip().startswith(("Connecting", "HTTP/"))
    }
    assert "200 OK" in result.stdout
    assert "server" not in headers and "via" not in headers
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["content-security-policy"] == "frame-ancestors 'self'"
    assert headers["strict-transport-security"] == "max-age=31536000"
    assert headers["x-content-type-options"] == "nosniff"


# -------------------------------------------------------- read_only and pids_limit (SPEC-032)

READ_ONLY_ERRORS = ("read-only file system", "erofs", "permissionerror")
RUN_TIMEOUT_S = 90


def _service(name: str) -> dict:
    return yaml.safe_load((ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8"))[
        "services"
    ][name]


def _hardening_args(name: str) -> list[str]:
    """``docker run`` options equivalent to the compose security settings of ``name``."""
    service = _service(name)
    assert service["read_only"] is True
    args = ["--read-only", "--pids-limit", "256", "--cap-drop", "ALL"]
    args += ["--security-opt", "no-new-privileges"]
    for item in service["tmpfs"]:
        args += ["--tmpfs", item]
    for cap in service.get("cap_add", []):
        args += ["--cap-add", cap]
    return args


def _start(name: str, image: str, *args: str, env: dict[str, str] | None = None) -> str:
    container = f"partqc-test-{name}-{secrets.token_hex(4)}"
    cmd = ["docker", "run", "-d", "--name", container, "--network", "none"]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    result = _run([*cmd, *args, image])
    assert result.returncode == 0, result.stderr
    return container


def _remove(container: str) -> None:
    _run(["docker", "rm", "-f", "-v", container], timeout=60)


def _inspect(container: str, template: str) -> str:
    return _run(["docker", "inspect", "-f", template, container]).stdout.strip()


def _exec(container: str, *cmd: str) -> subprocess.CompletedProcess:
    return _run(["docker", "exec", container, *cmd], timeout=60)


def _logs(container: str) -> str:
    result = _run(["docker", "logs", container], timeout=60)
    return result.stdout + result.stderr


def _http_get(container: str, url: str) -> subprocess.CompletedProcess:
    script = (
        "import sys, urllib.request as u, urllib.error as e\n"
        "try:\n"
        f"    r = u.urlopen({url!r}, timeout=5); print(r.status, r.read().decode().strip())\n"
        "except e.HTTPError as x:\n"
        "    print(x.code)\n"
    )
    return _exec(container, "python", "-c", script)


def _wait(predicate, timeout: float = RUN_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(2)
    return False


def _assert_read_only_layout(container: str) -> None:
    assert _exec(container, "touch", "/tmp/x").returncode == 0
    assert _exec(container, "touch", "/app/x").returncode != 0
    assert _exec(container, "cat", "/sys/fs/cgroup/pids.max").stdout.strip() == "256"
    logs = _logs(container).lower()
    assert not [error for error in READ_ONLY_ERRORS if error in logs], logs[-2000:]


def test_dashboard_runs_read_only(images: dict[str, str]) -> None:
    """CA-07 of SPEC-032 (dashboard): healthy, /_stcore/health ok, nothing written outside /tmp."""
    container = _start(
        "dashboard-ro",
        images["dashboard"],
        *_hardening_args("dashboard"),
        "--user",
        "10001:10001",
        env={
            "API_BASE_URL": "https://partqc.example.org",
            "READ_API_KEY": secrets.token_urlsafe(32),
        },
    )
    try:
        assert _wait(lambda: _inspect(container, "{{.State.Health.Status}}") == "healthy"), _logs(
            container
        )[-2000:]
        assert _http_get(container, "http://127.0.0.1:8501/_stcore/health").stdout.split() == [
            "200",
            "ok",
        ]
        _assert_read_only_layout(container)
    finally:
        _remove(container)


def test_api_runs_read_only(images: dict[str, str]) -> None:
    """CA-07 of SPEC-032 (api): /api/v1/health answers (503 without a database)."""
    container = _start(
        "api-ro",
        images["api"],
        *_hardening_args("api"),
        "--user",
        "10001:10001",
        env={
            "DATABASE_URL": "postgresql://<user>:<password>@db.example.org:6543/postgres",
            "READ_API_KEY": secrets.token_urlsafe(32),
        },
    )
    try:

        def answered() -> bool:
            out = _http_get(container, "http://127.0.0.1:8000/api/v1/health").stdout.split()
            return bool(out) and out[0] in {"200", "503"}

        assert _wait(answered), _logs(container)[-2000:]
        assert _inspect(container, "{{.State.Status}}") == "running"
        _assert_read_only_layout(container)
    finally:
        _remove(container)


def test_caddy_runs_read_only() -> None:
    """CA-08 of SPEC-032: Caddy with --read-only, /tmp tmpfs, temporary /data and /config."""
    container = _start(
        "caddy-ro",
        _service("caddy")["image"],
        *_hardening_args("caddy"),
        "-v",
        "/data",
        "-v",
        "/config",
        "-v",
        f"{ROOT / 'infra' / 'Caddyfile'}:/etc/caddy/Caddyfile:ro",
        env={"PUBLIC_HOST": "partqc.example.org"},
    )
    try:
        time.sleep(10)
        assert _inspect(container, "{{.State.Status}}") == "running", _logs(container)[-2000:]
        assert "read-only file system" not in _logs(container).lower()
        assert _exec(container, "touch", "/tmp/x").returncode == 0
        assert _exec(container, "touch", "/etc/x").returncode != 0
        assert _exec(container, "touch", "/data/x").returncode == 0
        assert _exec(container, "cat", "/sys/fs/cgroup/pids.max").stdout.strip() == "256"
    finally:
        _remove(container)
