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
]
SENTINELS_DASHBOARD = [
    "ml/models/partqc-sentinel-v0/metrics.json",
    "ml/reports/partqc-sentinel-v0/type_confusion.png",
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
        if k != "PUBLIC_HOST" and not k.endswith(("_MEM_LIMIT", "_CPUS"))
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
