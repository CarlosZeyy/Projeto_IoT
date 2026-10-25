"""Acceptance tests for SPEC-015 (deploy on the personal VPS, Supabase database, keep-alive).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test (at least) per automated CA, named ``test_caNN_*``; ``test_extra_*``
tests cover requirements of section 4 that no CA spells out, plus exploratory edge cases.

* CA-21 to CA-24 are marked ``db`` (PostgreSQL test server in ``TEST_DATABASE_URL``). Tests that
  need an empty schema use a scratch database ``<test db name>_acc015``, created on the same
  server and dropped at the end of the module.
* CA-33 to CA-37 are marked ``docker`` and run only with ``PARTQC_DOCKER_TESTS=1``. They use
  temporary copies of the tracked tree (``copy_tracked_tree``) and the ``build_image`` fixture of
  ``infra/tests/conftest.py``; containers run with ``--network none`` and never publish ports.
* Manual CAs (CA-13 to CA-19, CA-26, CA-40, CA-42, CA-43) are not automated here.

No test reaches the internet, the VPS or a real service. Keys are generated with ``secrets``;
example credentials, secrets and IP addresses are assembled at run time, so this file does not
match the patterns it scans for (SPEC-015 section 7, CA-05 rule 2, CA-10 of SPEC-022).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import secrets
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import tomllib
import traceback
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import psycopg
import pytest
import yaml
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

import qc_contracts

pytestmark = [pytest.mark.acceptance]

REPO_ROOT = Path(__file__).resolve().parents[3]
INFRA = REPO_ROOT / "infra"
MIGRATIONS_DIR = INFRA / "migrations"
INIT_SQL = MIGRATIONS_DIR / "001_init.sql"
MIGRATE_SCRIPT = INFRA / "migrate.py"
SMOKE_PATH = REPO_ROOT / "scripts" / "smoke_test.py"
DOCKER_SUPPORT_PATH = INFRA / "tests" / "docker_support.py"
MARKER_PROBE = Path(__file__).resolve().parent / "ca32_docker_marker_probe.py"
API_DOCKERFILE = "infra/docker/api.Dockerfile"
DASHBOARD_DOCKERFILE = "infra/docker/dashboard.Dockerfile"
PLAN = REPO_ROOT / "docs" / "deployment-plan.md"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
COMPOSE = INFRA / "compose.yaml"
CADDYFILE = INFRA / "Caddyfile"
RENDER = INFRA / "render.yaml"
KEEPALIVE = REPO_ROOT / ".github" / "workflows" / "keepalive.yml"
DOCKER_WF = REPO_ROOT / ".github" / "workflows" / "docker.yml"
CI_WF = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Assembled at run time: no literal IPv4 address or credential in this file.
LOOPBACK = ".".join(("127", "0", "0", "1"))
SECRET = "s3cr3t-" + "pw"
TEST_HOST = "partqc.example.org"
PORT_6543_MESSAGE = (
    "transaction pooler (port 6543) is not supported for migrations; "
    "use the direct connection or the session pooler (port 5432)"
)
SMOKE_CHECKS = [
    "health",
    "write_requires_key",
    "write",
    "read_requires_key",
    "read",
    "cors_closed",
    "dashboard",
    "dashboard_health",
]


# ============================================================================================
# generic helpers
# ============================================================================================


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(_read(path))


def _triggers(workflow: dict[str, Any]) -> Any:
    """``on:`` of a workflow (PyYAML 1.1 loads the bare key ``on`` as ``True``)."""
    if "on" in workflow:
        return workflow["on"]
    return workflow[True]


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True, timeout=60
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def _git_status() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sections_level2(text: str) -> dict[str, list[str]]:
    """``{title of a '## ' heading: lines until the next '## ' heading}``."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _section(text: str, needle: str) -> list[str]:
    matches = [lines for title, lines in _sections_level2(text).items() if needle in title]
    assert matches, f"no level-2 section whose title contains {needle!r}"
    return matches[0]


# ============================================================================================
# CA-01: infra/render.yaml (cold standby)
# ============================================================================================


def test_ca01_render_blueprint() -> None:
    data = _load_yaml(RENDER)
    services = data["services"]
    assert len(services) == 1
    svc = services[0]
    assert svc["type"] == "web"
    assert svc["plan"] == "free"
    assert svc["runtime"] == "python"
    assert svc["buildCommand"] == "pip install uv && uv sync --package qc-api --frozen --no-dev"
    assert svc["startCommand"] == (
        "uv run --package qc-api uvicorn qc_api.main:app --host 0.0.0.0 --port $PORT"
    )
    assert svc["healthCheckPath"] == "/api/v1/health"
    env = {item["key"]: item for item in svc["envVars"]}
    for key in ("DATABASE_URL", "READ_API_KEY"):
        assert key in env, key
        assert env[key].get("sync") is False, env[key]
        assert "value" not in env[key], key


def test_extra_render_name_branch_and_python_version_match_the_image() -> None:
    svc = _load_yaml(RENDER)["services"][0]
    assert svc["name"] == "partqc-api"
    assert svc["branch"] == "main"
    env = {item["key"]: item for item in svc["envVars"]}
    version = str(env["PYTHON_VERSION"]["value"])
    assert re.fullmatch(r"3\.12\.\d+", version), version
    base = re.search(r"FROM python:(3\.12\.\d+)-slim", _read(INFRA / "docker" / "api.Dockerfile"))
    assert base is not None
    assert version == base.group(1)
    assert svc.get("region"), "the region choice must be explicit (section 4.1)"


# ============================================================================================
# CA-02: keepalive.yml
# ============================================================================================


def test_ca02_keepalive_workflow() -> None:
    text = _read(KEEPALIVE)
    wf = yaml.safe_load(text)
    on = _triggers(wf)
    assert set(on) == {"schedule", "workflow_dispatch"}
    assert on["schedule"] == [{"cron": "17 9 */3 * *"}]
    assert wf["permissions"] == {}
    jobs = wf["jobs"]
    assert len(jobs) == 1
    job = next(iter(jobs.values()))
    assert job["timeout-minutes"] == 10
    step_texts = [json.dumps(step) for step in job["steps"]]
    assert any(
        "secrets.KEEPALIVE_URL" in s and "curl -fsS --retry 5 --retry-delay 30" in s
        for s in step_texts
    ), step_texts
    assert "http://" not in text
    assert "https://" not in text


def test_extra_keepalive_job_shape() -> None:
    wf = _load_yaml(KEEPALIVE)
    assert list(wf["jobs"]) == ["ping"]
    job = wf["jobs"]["ping"]
    assert str(job["runs-on"]).startswith("ubuntu-")
    assert len(job["steps"]) == 1


def _keepalive_step_run(tmp_path: Path, url: str, curl_exit: int) -> subprocess.CompletedProcess:
    """Run the keepalive step with bash (GitHub's default shell) and a fake ``curl``.

    The fake ``curl`` records its arguments and, on failure, writes the host to stderr, like a
    real DNS or connection error would.
    """
    job = _load_yaml(KEEPALIVE)["jobs"]["ping"]
    step = job["steps"][0]
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "curl-args.txt"
    fake = bindir / "curl"
    fake.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{log}"\n'
        f'if [ {curl_exit} -ne 0 ]; then echo "curl: (6) Could not resolve host: '
        f'partqc-hidden.example" >&2; fi\n'
        f"exit {curl_exit}\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    def subst(value: str) -> str:
        return re.sub(r"\$\{\{\s*secrets\.KEEPALIVE_URL\s*\}\}", url, value)

    env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    workflow_env = _load_yaml(KEEPALIVE).get("env") or {}
    for scope in (workflow_env, job.get("env") or {}, step.get("env") or {}):
        env.update({k: subst(str(v)) for k, v in scope.items()})
    script = subst(step["run"])
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    result.curl_args = log.read_text(encoding="utf-8").splitlines() if log.exists() else None  # type: ignore[attr-defined]
    return result


def test_extra_keepalive_fails_with_message_when_secret_is_empty(tmp_path: Path) -> None:
    result = _keepalive_step_run(tmp_path, "", 0)
    assert result.returncode != 0
    assert (result.stdout + result.stderr).strip(), "the failure needs a message"
    assert result.curl_args is None, "curl must not run without the secret"  # type: ignore[attr-defined]


def test_extra_keepalive_pings_health_and_hides_the_host(tmp_path: Path) -> None:
    url = "https://partqc-hidden.example"
    (tmp_path / "ok").mkdir()
    ok = _keepalive_step_run(tmp_path / "ok", url, 0)
    assert ok.returncode == 0, ok
    assert f"{url}/api/v1/health" in ok.curl_args  # type: ignore[attr-defined]
    args = ok.curl_args  # type: ignore[attr-defined]
    for flag in ("-fsS", "--retry", "5", "--retry-delay", "30"):
        assert flag in args, args
    (tmp_path / "ko").mkdir()
    ko = _keepalive_step_run(tmp_path / "ko", url, 6)
    assert ko.returncode != 0
    assert "partqc-hidden" not in ko.stdout + ko.stderr


# ============================================================================================
# CA-05: secret material in tracked files (R-03)
# ============================================================================================

STRICT_PATTERNS = [
    re.compile("eyJ" + r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),
    re.compile("-----" + "BEGIN [A-Z ]*PRIVATE KEY" + "-----"),
    re.compile("service_" + r"role\s*[:=]\s*\S{20,}"),
]
PG_URL = re.compile("postgres(ql)?:" + r"//(?P<user>[^\s:/@]+):(?P<password>[^\s@]+)@")
MARKER_RE = re.compile(r"<[a-z][a-z_-]*>")
RUNTIME_RE = re.compile(r"\$?\{[A-Za-z_][A-Za-z0-9_]*\}")
FICTITIOUS_PREFIXES = (
    "u:pw@" + LOOPBACK,
    "u:" + SECRET + "@" + LOOPBACK,
    "postgres" + ":" + "postgres" + "@localhost",
    "postgres" + ":" + "postgres" + "@...",
    "u:senha@" + "\u2026",
)


def _pg_occurrence_allowed(text: str, match: re.Match[str]) -> bool:
    password = match.group("password")
    if MARKER_RE.fullmatch(password) or password in ("\u2026", "..."):
        return True  # rule 1
    if RUNTIME_RE.fullmatch(password):
        return True  # rule 2
    after = text[text.index("://", match.start()) + 3 :]
    return after.startswith(FICTITIOUS_PREFIXES)  # rule 3


def _secret_findings(rel: str, text: str) -> list[str]:
    findings = []
    for pattern in STRICT_PATTERNS:
        for m in pattern.finditer(text):
            findings.append(f"{rel}: strict pattern at {m.start()}")
    for m in PG_URL.finditer(text):
        if not _pg_occurrence_allowed(text, m):
            line = text.count("\n", 0, m.start()) + 1
            findings.append(f"{rel}:{line}: postgres URL with a password outside the rules")
    return findings


def test_ca05_no_secret_material_outside_docs() -> None:
    scanned = 0
    findings: list[str] = []
    for rel in _tracked_files():
        if rel.startswith("docs/"):
            continue
        path = REPO_ROOT / rel
        if not path.exists() or not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8", errors="replace")
        scanned += 1
        findings.extend(_secret_findings(rel, text))
    assert scanned > 300, scanned
    assert not findings, findings


def test_ca05_scope_includes_reviews_and_acceptance_suites() -> None:
    scoped = [p for p in _tracked_files() if not p.startswith("docs/")]
    assert any(p.startswith("reviews/") for p in scoped)
    assert any("/tests/acceptance/" in p for p in scoped)


def test_ca05_env_example_secrets_are_blank_or_markers() -> None:
    names = ("DEVICE_API_KEY", "READ_API_KEY", "SIM_DEVICE_API_KEY", "DATABASE_URL")
    names += ("EDGE_SESSION_TOKEN",)
    seen = set()
    for line in _read(ENV_EXAMPLE).splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if not m or m.group(1) not in names:
            continue
        seen.add(m.group(1))
        value = m.group(2).strip().strip("'\"")
        if value == "" or re.fullmatch(r"<[^<>]+>", value):
            continue
        # "marcadores <...>" (plural): a URL whose credential and host parts are all markers.
        url = re.fullmatch(r"postgres(?:ql)?://(<[^<>]+>):(<[^<>]+>)@(<[^<>]+>)(:\d+)?/\w+", value)
        assert url is not None, line
    assert seen, "no secret variable found in .env.example"


def test_extra_ca05_scanner_flags_planted_credentials() -> None:
    """Self-check of the CA-05 scanner: real-looking values are flagged, the rules accept only
    what they say (values assembled at run time)."""
    scheme = "postgres" + "ql://"
    pooler = "aws-0-sa-east-1.pooler." + "supabase.com:6543/postgres"
    bad = [
        scheme + "postgres.abcdefgh:" + "Xk29dLq" + "p@" + pooler,
        scheme + "u:" + "{SECRET}x@" + LOOPBACK,
        scheme + "u:" + "pw@" + "10.0.0.1",
        scheme + "postgres:" + "postgres@db.example.org",
        "eyJ" + "a" * 24 + "." + "b" * 24,
        "-----" + "BEGIN RSA PRIVATE KEY" + "-----",
        "service_" + "role = " + "x" * 30,
    ]
    for sample in bad:
        assert _secret_findings("sample", sample), sample
    good = [
        scheme + "<user>:" + "<password>@db.example.org",
        scheme + "u:" + "{SECRET}@" + LOOPBACK,
        scheme + "u:" + "${DB_PASS}@host",
        scheme + "\u2026:\u2026@host",
        scheme + "u:...@host",
        scheme + FICTITIOUS_PREFIXES[2] + ":5432/x",
    ]
    for sample in good:
        assert not _secret_findings("sample", sample), sample


# ============================================================================================
# CA-06: .gitignore
# ============================================================================================


def _ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path], cwd=REPO_ROOT, check=False, timeout=60
    )
    assert result.returncode in (0, 1), result
    return result.returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.prod",
        ".env.migrate",
        "infra/.env",
        "infra/.env.api",
        "infra/.env.dashboard",
        ".streamlit/secrets.toml",
    ],
)
def test_ca06_gitignore_ignores(path: str) -> None:
    assert _ignored(path), path


@pytest.mark.parametrize("path", [".env.example", ".streamlit/config.toml"])
def test_ca06_gitignore_keeps(path: str) -> None:
    assert not _ignored(path), path


def test_extra_no_env_file_tracked() -> None:
    tracked = [p for p in _tracked_files() if Path(p).name.startswith(".env")]
    assert tracked == [".env.example"], tracked


# ============================================================================================
# CA-07: .streamlit/config.toml
# ============================================================================================


def _all_keys(data: dict[str, Any], prefix: str = "") -> list[str]:
    keys = []
    for key, value in data.items():
        full = f"{prefix}{key}"
        keys.append(full)
        if isinstance(value, dict):
            keys.extend(_all_keys(value, f"{full}."))
    return keys


def test_ca07_streamlit_config() -> None:
    cfg = tomllib.loads(_read(REPO_ROOT / ".streamlit" / "config.toml"))
    assert cfg["browser"]["gatherUsageStats"] is False
    assert cfg["server"]["headless"] is True
    assert cfg["client"]["showErrorDetails"] in {"none", "type"}
    server = cfg.get("server", {})
    for key in ("address", "port", "baseUrlPath", "fileWatcherType"):
        assert key not in server, key
    for key in ("enableCORS", "enableXsrfProtection"):
        if key in server:
            assert server[key] is True, key
    for key in _all_keys(cfg):
        low = key.lower()
        assert "key" not in low and "secret" not in low and "token" not in low, key


# ============================================================================================
# CA-08 .. CA-12: scripts/smoke_test.py
# ============================================================================================


@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    return _load_module("partqc_acc015_smoke_test", SMOKE_PATH)


class FakeCloud:
    """Fake API + dashboard behind an ``httpx.MockTransport``.

    Correct by default; each keyword switches one behaviour to a broken one.
    """

    def __init__(
        self,
        *,
        api_host: str,
        dash_host: str,
        read_key: str,
        device_id: str,
        device_key: str,
        read_open: bool = False,
        write_open: bool = False,
        acao: str | None = None,
        health_db: str = "ok",
        health_status: int | None = None,
        contract_version: str | None = None,
        dash_health_status: int = 200,
        dash_health_body: str = "ok",
        dash_root_redirect: bool = False,
        error: Callable[[httpx.Request], Exception] | None = None,
    ) -> None:
        self.api_host = api_host
        self.dash_host = dash_host
        self.read_key = read_key
        self.device_id = device_id
        self.device_key = device_key
        self.read_open = read_open
        self.write_open = write_open
        self.acao = acao
        self.health_db = health_db
        self.health_status = health_status
        self.contract_version = contract_version or qc_contracts.__version__
        self.dash_health_status = dash_health_status
        self.dash_health_body = dash_health_body
        self.dash_root_redirect = dash_root_redirect
        self.error = error
        self.requests: list[httpx.Request] = []
        self.written: list[dict[str, Any]] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error(request)
        path = request.url.path
        if path.startswith("/api/"):
            assert request.url.host == self.api_host, request.url
            response = self._api(request, path)
            if self.acao is not None:
                response.headers["access-control-allow-origin"] = self.acao
            return response
        assert request.url.host == self.dash_host, request.url
        return self._dashboard(request, path)

    def _api(self, request: httpx.Request, path: str) -> httpx.Response:
        key = request.headers.get("x-api-key")
        if request.method == "GET" and path == "/api/v1/health":
            body = {
                "status": "ok" if self.health_db == "ok" else "degraded",
                "db": self.health_db,
                "api_version": "0.0.0",
                "contract_version": self.contract_version,
            }
            status = self.health_status or (200 if self.health_db == "ok" else 503)
            return httpx.Response(status, json=body)
        if request.method == "POST" and path == "/api/v1/inspections":
            if not self.write_open and key != self.device_key:
                return httpx.Response(401, json={"detail": "Invalid or missing API key"})
            payload = json.loads(request.content)
            try:
                item = qc_contracts.InspectionCreate.model_validate(payload)
            except Exception:
                return httpx.Response(422, json={"detail": "invalid"})
            if key is not None and item.device_id != self.device_id:
                return httpx.Response(403, json={"detail": "forbidden"})
            self.written.append(payload)
            return httpx.Response(
                201, json={"inspection_id": str(item.inspection_id), "status": "created"}
            )
        if request.method == "GET" and path == "/api/v1/inspections":
            if not self.read_open and key != self.read_key:
                return httpx.Response(401, json={"detail": "Invalid or missing API key"})
            params = request.url.params
            items = [
                w
                for w in self.written
                if ("lot_id" not in params or w["lot_id"] == params["lot_id"])
                and ("source" not in params or w["source"] == params["source"])
            ]
            if key == self.read_key:
                extra = {"is_defective": False}
                items = [{**w, "received_at": w["inspected_at"], **extra} for w in items]
            else:
                items = []
            return httpx.Response(
                200, json={"items": items, "total": len(items), "limit": 50, "offset": 0}
            )
        return httpx.Response(404, json={"detail": "Not Found"})

    def _dashboard(self, request: httpx.Request, path: str) -> httpx.Response:
        if path.rstrip("/").endswith("/_stcore/health") or path == "/_stcore/health":
            return httpx.Response(self.dash_health_status, text=self.dash_health_body)
        if self.dash_root_redirect and "landed" not in request.url.query.decode():
            target = str(request.url.copy_with(query=b"landed=1"))
            return httpx.Response(302, headers={"location": target})
        return httpx.Response(200, text="<html><body>PartQC</body></html>")


@pytest.fixture
def smoke_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    env = {
        "READ_API_KEY": secrets.token_urlsafe(32),
        "SIM_DEVICE_ID": "sim-01",
        "SIM_DEVICE_API_KEY": secrets.token_urlsafe(32),
    }
    for name in ("CLOUD_API_URL", "DASHBOARD_URL", *env):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return env


API_URL = "https://api.partqc.example.org"
DASH_URL = "https://painel.partqc.example.org"


def _fake(env: dict[str, str], api_url: str = API_URL, dash_url: str = DASH_URL, **kw: Any):
    return FakeCloud(
        api_host=httpx.URL(api_url).host,
        dash_host=httpx.URL(dash_url).host,
        read_key=env["READ_API_KEY"],
        device_id=env["SIM_DEVICE_ID"],
        device_key=env["SIM_DEVICE_API_KEY"],
        **kw,
    )


def _run(
    smoke: ModuleType,
    fake: FakeCloud,
    capsys: pytest.CaptureFixture[str],
    api_url: str = API_URL,
    dash_url: str = DASH_URL,
    extra: tuple[str, ...] = (),
) -> tuple[int, str, str]:
    argv = ["--api-url", api_url, "--dashboard-url", dash_url, *extra]
    code = smoke.main(argv, transport=fake.transport)
    out, err = capsys.readouterr()
    return code, out, err


def _verdicts(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith(("PASS ", "FAIL "))]


def test_ca08_all_checks_pass_in_order(smoke, smoke_env, capsys) -> None:
    fake = _fake(smoke_env)
    code, out, _ = _run(smoke, fake, capsys)
    assert code == 0, out
    assert _verdicts(out) == [f"PASS {name}" for name in SMOKE_CHECKS], out
    assert len(fake.written) == 1
    sent = fake.written[0]
    assert sent["source"] == "simulated"
    assert re.fullmatch(r"SMOKE-\d{8}T\d{6}Z", sent["lot_id"]), sent["lot_id"]
    assert sent["model_version"] == "smoke-v0"
    assert sent["model_sha256"] == "0" * 64
    assert sent["device_id"] == smoke_env["SIM_DEVICE_ID"]


def test_extra_smoke_request_details(smoke, smoke_env, capsys) -> None:
    fake = _fake(smoke_env)
    code, out, _ = _run(smoke, fake, capsys)
    assert code == 0, out
    reqs = [(r.method, r.url.host, r.url.path) for r in fake.requests]
    api, dash = fake.api_host, fake.dash_host
    assert ("GET", api, "/api/v1/health") in reqs
    assert ("GET", dash, "/_stcore/health") in reqs
    reads = [r for r in fake.requests if r.method == "GET" and r.url.path == "/api/v1/inspections"]
    keyed = [r for r in reads if r.headers.get("x-api-key") == smoke_env["READ_API_KEY"]]
    assert keyed, "read must use READ_API_KEY"
    params = keyed[-1].url.params
    assert params["source"] == "simulated"
    assert params["lot_id"] == fake.written[0]["lot_id"]
    origin = [r for r in fake.requests if r.headers.get("origin") == "https://example.org"]
    assert origin and origin[0].url.path == "/api/v1/health"


@pytest.mark.parametrize("broken", ["read", "write"])
def test_ca09_open_endpoint_fails(smoke, smoke_env, capsys, broken: str) -> None:
    fake = _fake(smoke_env, read_open=broken == "read", write_open=broken == "write")
    code, out, _ = _run(smoke, fake, capsys)
    assert code == 1, out
    assert f"FAIL {broken}_requires_key" in "\n".join(_verdicts(out)), out


@pytest.mark.parametrize(
    ("kwargs", "check"),
    [
        ({"acao": "*"}, "cors_closed"),
        ({"health_db": "error"}, "health"),
        ({"health_db": "error", "health_status": 200}, "health"),
        ({"contract_version": "9.9.9"}, "health"),
        ({"dash_health_body": "nope"}, "dashboard_health"),
        ({"dash_health_status": 502, "dash_health_body": "Bad Gateway"}, "dashboard_health"),
    ],
)
def test_ca10_broken_service_fails(smoke, smoke_env, capsys, kwargs, check: str) -> None:
    fake = _fake(smoke_env, **kwargs)
    code, out, _ = _run(smoke, fake, capsys)
    assert code == 1, out
    verdicts = _verdicts(out)
    assert any(v.startswith(f"FAIL {check}") for v in verdicts), out
    assert f"PASS {check}" not in verdicts


@pytest.mark.parametrize(
    ("api_url", "dash_url", "drop"),
    [
        ("http://api.exemplo.org", DASH_URL, None),
        (API_URL, "http://painel.exemplo.org", None),
        (API_URL, DASH_URL, "READ_API_KEY"),
    ],
)
def test_ca11_invalid_input_exits_2_without_requests(
    smoke, smoke_env, capsys, monkeypatch, api_url, dash_url, drop
) -> None:
    if drop:
        monkeypatch.delenv(drop)
    fake = _fake(smoke_env)
    code, out, err = _run(smoke, fake, capsys, api_url, dash_url)
    assert code == 2, out + err
    assert fake.requests == []


@pytest.mark.parametrize(
    ("api_url", "dash_url"),
    [
        ("http://localhost.evil.example", DASH_URL),
        ("http://127.0.0.1.nip.io", DASH_URL),
        ("ftp://api.exemplo.org", DASH_URL),
        ("api.exemplo.org", DASH_URL),
        ("", DASH_URL),
        ("https://", DASH_URL),
        (API_URL, "javascript:alert(1)"),
    ],
)
def test_extra_smoke_refuses_lookalike_and_malformed_urls(
    smoke, smoke_env, capsys, api_url, dash_url
) -> None:
    fake = _fake(smoke_env, api_url="https://x.example", dash_url="https://y.example")
    argv = ["--api-url", api_url, "--dashboard-url", dash_url]
    try:
        code = smoke.main(argv, transport=fake.transport)
    except SystemExit as exc:  # argparse-style exit is acceptable if the code is 2
        code = exc.code
    capsys.readouterr()
    assert code == 2
    assert fake.requests == []


@pytest.mark.parametrize("drop", ["SIM_DEVICE_ID", "SIM_DEVICE_API_KEY"])
def test_extra_smoke_missing_device_vars_exit_2(smoke, smoke_env, capsys, monkeypatch, drop):
    monkeypatch.delenv(drop)
    fake = _fake(smoke_env)
    code, _, _ = _run(smoke, fake, capsys)
    assert code == 2
    assert fake.requests == []


@pytest.mark.parametrize("host", ["localhost", LOOPBACK])
def test_extra_smoke_accepts_http_loopback(smoke, smoke_env, capsys, host: str) -> None:
    api = f"http://{host}:8000"
    dash = f"http://{host}:8501"
    fake = _fake(smoke_env, api_url=api, dash_url=dash)
    fake.dash_host = fake.api_host  # same host, routed by path
    code, out, _ = _run(smoke, fake, capsys, api, dash)
    assert code == 0, out


def test_extra_smoke_reads_urls_from_environment(smoke, smoke_env, capsys, monkeypatch) -> None:
    monkeypatch.setenv("CLOUD_API_URL", API_URL)
    monkeypatch.setenv("DASHBOARD_URL", DASH_URL)
    fake = _fake(smoke_env)
    code = smoke.main([], transport=fake.transport)
    out, _ = capsys.readouterr()
    assert code == 0, out


def test_extra_smoke_trailing_slash_and_base_path(smoke, smoke_env, capsys) -> None:
    fake = _fake(smoke_env)
    code, out, _ = _run(smoke, fake, capsys, API_URL + "/", DASH_URL + "/")
    assert code == 0, out
    paths = [r.url.path for r in fake.requests]
    assert not any("//" in p for p in paths), paths
    assert "/_stcore/health" in paths


def test_extra_smoke_dashboard_follows_redirects(smoke, smoke_env, capsys) -> None:
    fake = _fake(smoke_env, dash_root_redirect=True)
    code, out, _ = _run(smoke, fake, capsys)
    assert code == 0, out


def test_extra_smoke_garbage_health_is_a_fail_not_a_crash(smoke, smoke_env, capsys) -> None:
    fake = _fake(smoke_env)
    original = fake._api

    def garbage(request: httpx.Request, path: str) -> httpx.Response:
        if path == "/api/v1/health":
            return httpx.Response(200, text="<html>not json</html>")
        return original(request, path)

    fake._api = garbage  # type: ignore[method-assign]
    code, out, _ = _run(smoke, fake, capsys)
    assert code == 1
    assert any(v.startswith("FAIL health") for v in _verdicts(out)), out


SECRET_HOST_API = "https://api.host-secreto-15.example"
SECRET_HOST_DASH = "https://painel.host-secreto-15.example"


def _connect_error(request: httpx.Request) -> Exception:
    return httpx.ConnectError(f"cannot connect to {request.url}", request=request)


def _timeout_error(request: httpx.Request) -> Exception:
    return httpx.ReadTimeout(f"timed out reading {request.url}", request=request)


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"read_open": True, "acao": "*", "dash_health_status": 502},
        {"health_db": "error"},
        {"error": _connect_error},
        {"error": _timeout_error},
    ],
    ids=["success", "status-failures", "db-error", "connect-error", "read-timeout"],
)
def test_ca12_no_key_or_host_in_output(smoke, smoke_env, capsys, kwargs) -> None:
    fake = _fake(smoke_env, api_url=SECRET_HOST_API, dash_url=SECRET_HOST_DASH, **kwargs)
    code, out, err = _run(smoke, fake, capsys, SECRET_HOST_API, SECRET_HOST_DASH)
    assert code in (0, 1)
    text = out + err
    assert smoke_env["READ_API_KEY"] not in text
    assert smoke_env["SIM_DEVICE_API_KEY"] not in text
    assert "host-secreto-15" not in text, text
    assert len(_verdicts(out)) == len(SMOKE_CHECKS), out


def test_ca12_source_has_no_verify_false() -> None:
    assert "verify=False" not in _read(SMOKE_PATH)


def test_extra_smoke_usage_errors_do_not_echo_values(smoke, smoke_env, capsys) -> None:
    password = secrets.token_hex(8)
    secret_url = "http://user:" + password + "@api.host-secreto-15.example"
    fake = _fake(smoke_env)
    code, out, err = _run(smoke, fake, capsys, secret_url, DASH_URL)
    assert code == 2
    assert password not in out + err
    assert "host-secreto-15" not in out + err


def _unknown_argument_cases(value: str) -> list[list[str]]:
    """Mistyped command lines carrying ``value`` (r2: RV-02 / T-01 of r1)."""
    key_opt = "--api-" + "key"
    urls = ["--api-url", API_URL, "--dashboard-url", DASH_URL]
    return [
        [key_opt + "=" + value],
        [key_opt, value],
        [value],
        [*urls, key_opt + "=" + value],
        [*urls, "--read-api-" + "key", value],
        [*urls, value, value + "x"],
        ["--api-url-typo", value],
        ["--api-url", API_URL, "--dashboard-url"],
        ["--dashboard-url=" + "https://" + value + ".host-secreto-15.example", "--zzz=" + value],
    ]


def test_extra_smoke_unknown_arguments_are_never_echoed(smoke, smoke_env, capsys) -> None:
    value = secrets.token_urlsafe(24)
    for argv in _unknown_argument_cases(value):
        fake = _fake(smoke_env)
        try:
            code = smoke.main(argv, transport=fake.transport)
        except SystemExit as exc:
            code = exc.code
        out, err = capsys.readouterr()
        assert code == 2, (argv, out, err)
        assert value not in out + err, argv
        assert "host-secreto-15" not in out + err, argv
        assert fake.requests == [], argv


def test_extra_smoke_cli_subprocess_never_echoes(tmp_path: Path) -> None:
    """The real entry point (``python scripts/smoke_test.py``), not only ``main``."""
    value = secrets.token_urlsafe(24)
    env = {k: v for k, v in os.environ.items() if k not in {"CLOUD_API_URL", "DASHBOARD_URL"}}
    env.update(
        {
            "READ_API_KEY": secrets.token_urlsafe(16),
            "SIM_DEVICE_ID": "sim-01",
            "SIM_DEVICE_API_KEY": secrets.token_urlsafe(16),
        }
    )
    for argv in _unknown_argument_cases(value):
        result = subprocess.run(
            [sys.executable, str(SMOKE_PATH), *argv],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 2, (argv, result)
        assert value not in result.stdout + result.stderr, argv


# ============================================================================================
# CA-20: migrate.py refuses the transaction pooler (port 6543) before connecting
# ============================================================================================


class _Listener:
    """TCP listener on loopback that counts accepted connections."""

    def __init__(self, port: int = 0) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((LOOPBACK, port))
        self.sock.listen(16)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.accepted = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self.accepted += 1
            client.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.sock.close()


@pytest.fixture
def listeners() -> Iterator[tuple[_Listener, _Listener]]:
    """A listener on port 6543 and one on a free port (the first host of a multi-host URL)."""
    try:
        on_6543 = _Listener(6543)
    except OSError as exc:  # pragma: no cover - environment problem, not a product failure
        pytest.fail(f"port 6543 is busy on loopback, CA-20 cannot be verified: {exc}")
    other = _Listener()
    yield on_6543, other
    on_6543.close()
    other.close()


def _refused_cases(other_port: int) -> list[tuple[str, dict[str, str]]]:
    return [
        (f"postgresql://u:{SECRET}@{LOOPBACK}:6543/x_test", {}),
        (f"postgresql://u@{LOOPBACK}:{other_port},{LOOPBACK}:6543/x_test", {}),
        (f"postgresql://u:{SECRET}@{LOOPBACK}/x_test", {"PGPORT": "6543"}),
    ]


def _run_migrate_cli(*args: str, env_extra: dict[str, str] | None = None):
    env = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "PGPORT"}}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("status", [False, True], ids=["apply", "status"])
def test_ca20_cli_refuses_port_6543(listeners, status: bool) -> None:
    on_6543, other = listeners
    for url, env in _refused_cases(other.port):
        args = ["--database-url", url] + (["--status"] if status else [])
        result = _run_migrate_cli(*args, env_extra=env)
        assert result.returncode == 2, (url, result)
        assert "transaction pooler (port 6543) is not supported for migrations" in result.stderr
        assert SECRET not in result.stdout + result.stderr
        assert url not in result.stdout + result.stderr
    assert on_6543.accepted == 0
    assert other.accepted == 0


def test_ca20_cli_spec_literal_multi_host() -> None:
    result = _run_migrate_cli("--database-url", "postgresql://u@h1:5432,h2:6543/x_test")
    assert result.returncode == 2, result
    assert "transaction pooler (port 6543) is not supported for migrations" in result.stderr


def test_ca20_functions_raise_before_connecting(listeners, monkeypatch) -> None:
    from migrate import (
        MigrationError,
        UnsupportedConnectionError,
        apply_migrations,
        pending_migrations,
    )

    assert issubclass(UnsupportedConnectionError, MigrationError)
    on_6543, other = listeners
    cases = [*_refused_cases(other.port), ("postgresql://u@h1:5432,h2:6543/x_test", {})]
    for url, env in cases:
        monkeypatch.delenv("PGPORT", raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        for func in (apply_migrations, pending_migrations):
            with pytest.raises(UnsupportedConnectionError) as exc:
                func(url)
            assert isinstance(exc.value, MigrationError)
            assert str(exc.value) == PORT_6543_MESSAGE
            full = "".join(traceback.format_exception(exc.value))
            assert SECRET not in full
    assert on_6543.accepted == 0
    assert other.accepted == 0


@pytest.mark.parametrize(
    ("template", "env"),
    [
        ("host={lo} port=6543 user=u password={pw} dbname=x_test", {}),
        ("postgresql://u:{pw}@{lo}/x_test?port=6543", {}),
        ("postgresql://u:{pw}@[::1]:6543/x_test", {}),
        ("postgresql://u:{pw}@{lo},{lo}/x_test", {"PGPORT": "6543"}),
        ("postgresql://u:{pw}@{lo}:,{lo}:6543/x_test", {}),
        ("postgresql://u:{pw}@{lo}:06543/x_test", {}),
        ("host={lo} port=+6543 user=u password={pw} dbname=x_test", {}),
        ("host={lo} port=' 06543' user=u password={pw} dbname=x_test", {}),
        ("postgresql://u:{pw}@{lo}/x_test", {"PGPORT": "06543"}),
        ("postgresql://u:{pw}@{lo}:5432,{lo}:006543/x_test", {}),
    ],
    ids=[
        "key-value",
        "query-param",
        "ipv6",
        "multi-host-pgport",
        "empty-port-item",
        "leading-zero",
        "plus-sign",
        "space-and-zero",
        "pgport-leading-zero",
        "multi-host-zeros",
    ],
)
def test_extra_port_6543_variants_refused(listeners, monkeypatch, template, env) -> None:
    from migrate import UnsupportedConnectionError, apply_migrations

    url = template.format(lo=LOOPBACK, pw=SECRET)
    monkeypatch.delenv("PGPORT", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(UnsupportedConnectionError) as exc:
        apply_migrations(url)
    assert SECRET not in "".join(traceback.format_exception(exc.value))
    result = _run_migrate_cli("--database-url", url, env_extra=env)
    assert result.returncode == 2, result
    assert SECRET not in result.stdout + result.stderr
    assert listeners[0].accepted == 0


def test_extra_cli_database_url_env_with_6543_exits_2(listeners) -> None:
    url = f"postgresql://u:{SECRET}@{LOOPBACK}:6543/x_test"
    result = _run_migrate_cli(env_extra={"DATABASE_URL": url})
    assert result.returncode == 2, result
    assert SECRET not in result.stdout + result.stderr
    assert listeners[0].accepted == 0


def test_extra_session_pooler_port_is_not_refused(listeners) -> None:
    """Port 5432 (session pooler / direct) is not refused: the CLI tries to connect (exit 1)."""
    port = listeners[1].port
    url = f"postgresql://u:{SECRET}@{LOOPBACK}:{port}/x_test?connect_timeout=2"
    result = _run_migrate_cli("--database-url", url)
    assert result.returncode == 1, result
    assert "6543" not in result.stderr
    assert SECRET not in result.stdout + result.stderr


# ============================================================================================
# CA-21 .. CA-24: migration runner against the test database (db)
# ============================================================================================


def _connect(conninfo: str) -> psycopg.Connection:
    return psycopg.connect(conninfo, autocommit=True, prepare_threshold=None)


@pytest.fixture(scope="module")
def scratch_conninfo(db_conninfo: str) -> Iterator[str]:
    name = f"{conninfo_to_dict(db_conninfo)['dbname']}_acc015"
    assert "test" in name
    ident = sql.Identifier(name)
    with _connect(db_conninfo) as conn:
        conn.execute(sql.SQL("drop database if exists {} with (force)").format(ident))
        conn.execute(sql.SQL("create database {}").format(ident))
    yield make_conninfo(db_conninfo, dbname=name)
    with _connect(db_conninfo) as conn:
        conn.execute(sql.SQL("drop database if exists {} with (force)").format(ident))


@pytest.fixture
def empty_db(scratch_conninfo: str) -> str:
    with _connect(scratch_conninfo) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
    return scratch_conninfo


def _table_exists(conninfo: str, name: str) -> bool:
    with _connect(conninfo) as conn:
        row = conn.execute("select to_regclass(%s) is not null", (f"public.{name}",)).fetchone()
    assert row is not None
    return bool(row[0])


def _applied(conninfo: str) -> list[str]:
    if not _table_exists(conninfo, "schema_migrations"):
        return []
    with _connect(conninfo) as conn:
        rows = conn.execute("select version from schema_migrations order by version").fetchall()
    return [r[0] for r in rows]


def _dir_with_001(tmp_path: Path) -> Path:
    target = tmp_path / "migrations"
    target.mkdir()
    shutil.copy(INIT_SQL, target / "001_init.sql")
    return target


@pytest.mark.db
def test_ca21_lock_deadline(empty_db: str, tmp_path: Path) -> None:
    from migrate import ADVISORY_LOCK_KEY, MigrationError, apply_migrations

    folder = _dir_with_001(tmp_path)
    holder = _connect(empty_db)
    try:
        holder.execute("select pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        start = time.monotonic()
        with pytest.raises(MigrationError) as exc:
            apply_migrations(empty_db, folder, lock_wait_s=1)
        elapsed = time.monotonic() - start
        assert str(exc.value).startswith("could not acquire the migration lock within"), exc.value
        assert elapsed < 5, elapsed
        assert not _table_exists(empty_db, "schema_migrations")
    finally:
        holder.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
        holder.close()
    assert apply_migrations(empty_db, folder, lock_wait_s=1) == ["001"]


@pytest.mark.db
@pytest.mark.parametrize("value", [0, -1, -0.5, math.nan])
def test_ca21_lock_wait_must_be_positive(empty_db: str, tmp_path: Path, value: float) -> None:
    from migrate import apply_migrations

    with pytest.raises(ValueError):
        apply_migrations(empty_db, _dir_with_001(tmp_path), lock_wait_s=value)
    assert not _table_exists(empty_db, "schema_migrations")


@pytest.mark.db
def test_extra_lock_wait_is_keyword_only_and_defaults_to_30() -> None:
    import inspect

    from migrate import apply_migrations

    param = inspect.signature(apply_migrations).parameters["lock_wait_s"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default == 30.0


@pytest.mark.db
def test_extra_lock_taken_when_released_within_the_deadline(empty_db: str, tmp_path: Path) -> None:
    from migrate import ADVISORY_LOCK_KEY, apply_migrations

    folder = _dir_with_001(tmp_path)
    holder = _connect(empty_db)
    holder.execute("select pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
    timer = threading.Timer(1.5, lambda: holder.execute("select pg_advisory_unlock_all()"))
    timer.start()
    try:
        assert apply_migrations(empty_db, folder, lock_wait_s=10) == ["001"]
    finally:
        timer.join()
        holder.close()
    with _connect(empty_db) as conn:
        held = conn.execute("select count(*) from pg_locks where locktype = 'advisory'").fetchone()
    assert held is not None and held[0] == 0


@pytest.mark.db
@pytest.mark.parametrize(
    ("body", "table"),
    [
        ("create table t_tx(id int); commit;", "t_tx"),
        ("create table t_tx2(id int); commit; begin;", "t_tx2"),
        ("create table t_tx3(id int); rollback;", "t_tx3"),
        ("create table t_tx4(id int); rollback; begin;", "t_tx4"),
    ],
    ids=["commit", "commit-begin", "extra-rollback", "extra-rollback-begin"],
)
def test_ca22_transaction_control_in_file(empty_db: str, tmp_path: Path, body: str, table: str):
    from migrate import MigrationError, apply_migrations

    folder = _dir_with_001(tmp_path)
    (folder / "002_tx.sql").write_text(body + "\n", encoding="utf-8")
    with pytest.raises(MigrationError) as exc:
        apply_migrations(empty_db, folder)
    message = str(exc.value)
    assert "ended the transaction" in message, message
    assert "002" in message, message
    assert _applied(empty_db) == ["001"]


@pytest.mark.db
def test_ca23_non_ascii_digits_are_an_invalid_name(empty_db: str, tmp_path: Path) -> None:
    from migrate import MigrationError, apply_migrations

    folder = _dir_with_001(tmp_path)
    (folder / "\u0661\u0662\u0663_x.sql").write_text("create table t_ar(id int);\n", "utf-8")
    with pytest.raises(MigrationError):
        apply_migrations(empty_db, folder)
    assert _applied(empty_db) == []
    assert not _table_exists(empty_db, "devices")
    assert not _table_exists(empty_db, "t_ar")


@pytest.mark.db
@pytest.mark.parametrize(
    "name", ["\u0661\u0662\u0663_x.sql", "00\u0661_x.sql", "\uff10\uff10\uff12_x.sql"]
)
def test_extra_unicode_digit_names_refused_by_load_migrations(
    empty_db: str, tmp_path: Path, name: str
):
    from migrate import MigrationError, load_migrations

    folder = _dir_with_001(tmp_path)
    (folder / name).write_text("select 1;\n", "utf-8")
    with pytest.raises(MigrationError):
        load_migrations(folder)


@pytest.mark.db
def test_ca24_each_file_read_once(empty_db: str, tmp_path: Path, monkeypatch) -> None:
    from migrate import apply_migrations

    folder = _dir_with_001(tmp_path)
    target = (folder / "001_init.sql").resolve()
    calls: dict[Path, int] = {}
    returned: list[bytes] = []
    original = Path.read_bytes

    def spy(self: Path) -> bytes:
        data = original(self)
        resolved = Path(self).resolve()
        calls[resolved] = calls.get(resolved, 0) + 1
        if resolved == target:
            returned.append(data)
        return data

    monkeypatch.setattr(Path, "read_bytes", spy)
    assert apply_migrations(empty_db, folder) == ["001"]
    monkeypatch.undo()
    assert calls.get(target) == 1, calls
    with _connect(empty_db) as conn:
        query = "select checksum from schema_migrations where version = '001'"
        row = conn.execute(query).fetchone()
    assert row is not None
    assert row[0] == hashlib.sha256(returned[0]).hexdigest()


@pytest.mark.db
def test_extra_migration_content_field_is_bytes_and_not_in_repr() -> None:
    from migrate import load_migrations

    migrations = load_migrations(MIGRATIONS_DIR)
    first = migrations[0]
    assert isinstance(first.content, bytes)
    assert first.read_sql() == first.content.decode("utf-8")
    assert "create table" not in repr(first).lower()


# ============================================================================================
# CA-25, CA-27, CA-38: docs/deployment-plan.md
# ============================================================================================


def test_ca25_accepted_risks_and_register_device() -> None:
    text = _read(PLAN)
    risks = _section(text, "Riscos aceitos")
    pool_lines = [i for i, line in enumerate(risks) if "pool" in line and "503" in line]
    psy_lines = [i for i, line in enumerate(risks) if "psycopg.pool" in line]
    assert pool_lines and psy_lines, risks
    assert any(a != b for a in pool_lines for b in psy_lines), "two distinct lines expected"
    joined = "\n".join(risks)
    for url in (
        "caddyserver.com/docs/caddyfile/directives",
        "letsencrypt.org/docs/ct-logs",
        "letsencrypt.org/docs/rate-limits",
    ):
        assert url in joined, url
    lines = [line for line in text.splitlines() if "register_device.py" in line]
    assert lines
    for line in lines:
        assert "--env-file" in line, line
        assert "--database-url" not in line, line


def test_ca27_statement_timeout_keys_render_and_simulator() -> None:
    text = _read(PLAN)
    for needle in ("statement_timeout", "rolconfig", "token_urlsafe(32)"):
        assert needle in text, needle
    section2 = _section(text, "2.")
    render = [line for line in section2 if line.startswith("| Render")]
    assert render, "no '| Render' row in section 2"
    for line in render:
        assert "512 MB" in line and "0,1 CPU" in line, line
        assert "render.com/docs/compute-plans" in line, line
        assert "não confirmado" not in line, line
    sim = [line for line in text.splitlines() if "simulate.py" in line]
    assert sim
    for line in sim:
        assert "--env-file" in line, line
    risks = _section(text, "Riscos aceitos")
    lines_57014 = [line for line in risks if "57014" in line]
    assert lines_57014
    for line in lines_57014:
        assert "503" in line and "Database unavailable" in line, line
        assert "500 genérico" not in line, line


def test_ca38_operation_rules() -> None:
    text = _read(PLAN)
    for needle in (
        "docker compose -f infra/compose.yaml up -d --build",
        "git pull --ff-only",
        "free -h",
        "nproc",
        "chmod 600",
        "<subdominio>",
        "--filter label=partqc.component",
    ):
        assert needle in text, needle
    config_word = re.compile(r"(?<=\s)config(?=$|[\s`'\",;:)])")
    dangerous = (
        "ufw reset",
        "ufw default",
        "ufw delete",
        "ufw --force",
        "iptables -F",
        "docker system prune",
        "volume prune",
        "down -v",
    )
    lines = text.splitlines()
    for line in lines:
        if "docker compose" in line and config_word.search(line):
            assert "--quiet" in line, line
        if any(d in line for d in dangerous):
            assert "Nunca" in line or "nunca" in line, line
    section2 = set(_section(text, "2."))
    for line in lines:
        if "streamlit.app" in line or "Koyeb" in line:
            assert line in section2 and line.startswith("|"), line
            if "Koyeb" in line:
                assert "não usado" in line.lower(), line  # "**Não usado**" says "não usado"


def test_extra_plan_never_runs_migrations_in_actions_or_vps_with_argv_url() -> None:
    text = _read(PLAN)
    for line in text.splitlines():
        if "migrate.py" in line and "uv run" in line:
            assert "--env-file .env.migrate" in line, line
            assert "--database-url" not in line, line


# ============================================================================================
# CA-28: Dockerfiles as text
# ============================================================================================


def _instructions(text: str) -> list[str]:
    out: list[str] = []
    buf = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("#") or (not buf and not stripped):
            continue
        if stripped.endswith("\\"):
            buf += stripped[:-1].strip() + " "
            continue
        buf += stripped
        out.append(" ".join(buf.split()))
        buf = ""
    if buf.strip():
        out.append(" ".join(buf.split()))
    return out


def _keyword(instr: str) -> str:
    return instr.split(" ", 1)[0].upper()


DOCKERFILES = {
    "api": {
        "file": INFRA / "docker" / "api.Dockerfile",
        "sync": "uv sync --package qc-api --frozen --no-dev",
        "health": "/api/v1/health",
        "cmd": ["uvicorn", "qc_api.main:app", "--host", "0.0.0.0", "--port", "8000"],
        "port": "8000",
    },
    "dashboard": {
        "file": INFRA / "docker" / "dashboard.Dockerfile",
        "sync": "uv sync --package qc-dashboard --frozen --no-dev",
        "health": "/_stcore/health",
        "cmd": [
            "streamlit",
            "run",
            "dashboard/app.py",
            "--server.address=0.0.0.0",
            "--server.port=8501",
            "--server.fileWatcherType=none",
        ],
        "port": "8501",
    },
}
FROM_RE = re.compile(
    r"^FROM python:3\.12\.\d+-slim-(bookworm|trixie)(@sha256:[0-9a-f]{64})?( AS \w+)?$"
)
UV_RE = re.compile(r"uv:(\d+\.\d+\.\d+)(@sha256:[0-9a-f]{64})? /uv /uvx /bin/")


def _env_arg_names(instr: str) -> list[str]:
    kw, _, rest = instr.partition(" ")
    if kw.upper() == "ARG":
        return [rest.split("=", 1)[0].strip()]
    tokens = shlex.split(rest)
    if tokens and "=" in tokens[0]:
        return [t.split("=", 1)[0] for t in tokens if "=" in t]
    return tokens[:1]


@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_ca28_dockerfile_rules(component: str) -> None:
    spec = DOCKERFILES[component]
    text = _read(spec["file"])
    instrs = _instructions(text)
    kws = [_keyword(i) for i in instrs]

    froms = [i for i in instrs if _keyword(i) == "FROM"]
    assert froms
    for instr in froms:
        assert FROM_RE.match(instr), instr

    uv_copies = [i for i in instrs if "COPY --from=ghcr.io/astral-sh/uv:" in i]
    assert len(uv_copies) == 1, uv_copies
    assert UV_RE.search(uv_copies[0]), uv_copies[0]

    runs = [i for i in instrs if _keyword(i) == "RUN"]
    assert any(spec["sync"] in i for i in runs), runs
    assert "UV_PYTHON_DOWNLOADS=0" in text
    assert "WORKDIR /app" in text

    for forbidden in ("--no-editable", "--extra", "--all-extras", "--all-packages", "pip install"):
        assert forbidden not in text, forbidden
    assert "latest" not in text

    user_idx = [n for n, k in enumerate(kws) if k == "USER"]
    run_idx = [n for n, k in enumerate(kws) if k == "RUN"]
    assert user_idx and instrs[user_idx[-1]] == "USER 10001:10001"
    assert user_idx[-1] > run_idx[-1]

    health = [i for i in instrs if _keyword(i) == "HEALTHCHECK"]
    assert len(health) == 1, health
    assert "--interval=60s" in health[0] and spec["health"] in health[0], health[0]

    cmds = [i for i in instrs if _keyword(i) == "CMD"]
    assert cmds
    cmd = json.loads(cmds[-1].split(" ", 1)[1])
    assert cmd == spec["cmd"]
    assert "uv" not in cmd and "uvx" not in cmd

    assert any(_keyword(i) == "LABEL" and f'partqc.component="{component}"' in i for i in instrs), (
        instrs
    )

    for instr in instrs:
        if _keyword(instr) in ("ENV", "ARG"):
            for name in _env_arg_names(instr):
                upper = name.upper()
                for bad in ("DATABASE_URL", "API_KEY", "TOKEN", "PASSWORD", "SECRET"):
                    assert bad not in upper, instr


def test_ca28_same_uv_version_in_both() -> None:
    versions = set()
    for spec in DOCKERFILES.values():
        m = UV_RE.search(" ".join(_instructions(_read(spec["file"]))))
        assert m
        versions.add(m.group(1))
    assert len(versions) == 1, versions


@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_extra_dockerfile_table_rows(component: str) -> None:
    spec = DOCKERFILES[component]
    text = _read(spec["file"])
    instrs = _instructions(text)
    for env in ("UV_COMPILE_BYTECODE=1", "UV_LINK_MODE=copy", "PYTHONUNBUFFERED=1"):
        assert env in text, env
    assert any(i.startswith("ENV PATH=") and "/app/.venv/bin" in i for i in instrs), instrs
    assert any(i == "COPY . /app" or i.endswith(" . /app") for i in instrs if i.startswith("COPY"))
    assert f"EXPOSE {spec['port']}" in instrs
    assert "10001" in text and "/home/app" in text
    health = next(i for i in instrs if i.startswith("HEALTHCHECK"))
    for flag in ("--timeout=10s", "--start-period=30s", "--retries=3"):
        assert flag in health, flag
    assert re.search(r"CMD \[", health), "healthcheck must be in exec form"
    assert not re.search(r"^ADD\s+https?://", text, re.M)
    assert not re.search(r"curl[^\n]*\|\s*(ba)?sh", text)


# ============================================================================================
# CA-29: infra/compose.yaml
# ============================================================================================

PUBLIC_HOST_RE = re.compile(r"^\$\{PUBLIC_HOST:\?[^}]*\}$")
LIMITS = {
    "api": ("${API_MEM_LIMIT:-512m}", "${API_CPUS:-1.0}"),
    "dashboard": ("${DASHBOARD_MEM_LIMIT:-1g}", "${DASHBOARD_CPUS:-1.0}"),
    "caddy": ("${CADDY_MEM_LIMIT:-256m}", "${CADDY_CPUS:-0.5}"),
}


def _env_dict(env: Any) -> dict[str, Any]:
    if env is None:
        return {}
    if isinstance(env, dict):
        return env
    return dict(item.split("=", 1) if "=" in item else (item, None) for item in env)


def _env_file_paths(value: Any) -> list[tuple[str, Any]]:
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        if isinstance(item, str):
            out.append((item, True))
        else:
            out.append((item["path"], item.get("required", True)))
    return out


def test_ca29_compose_structure() -> None:
    data = _load_yaml(COMPOSE)
    assert data["name"] == "partqc"
    services = data["services"]
    assert set(services) == {"caddy", "api", "dashboard"}

    assert "ports" not in services["caddy"]  # SPEC-039 section 4.1 item 2
    for name, port in (("caddy", "80"), ("api", "8000"), ("dashboard", "8501")):
        assert "ports" not in services[name], name
        assert [str(p) for p in services[name]["expose"]] == [port], name

    for name, svc in services.items():
        for key in ("privileged", "network_mode", "pid", "container_name"):
            assert key not in svc, (name, key)
        for vol in svc.get("volumes", []) or []:
            assert "docker.sock" not in json.dumps(vol), (name, vol)

    for name in ("api", "dashboard"):
        assert services[name]["build"] == {
            "context": "..",
            "dockerfile": f"infra/docker/{name}.Dockerfile",
        }
        assert "env_file" not in services[name], name  # SPEC-039 section 4.1 items 6 and 7

    dash_env = _env_dict(services["dashboard"].get("environment"))
    assert re.match(r"^https://\$\{PUBLIC_HOST:\?[^}]*\}$", dash_env["API_BASE_URL"])
    caddy = services["caddy"]
    assert "environment" not in caddy  # SPEC-039 section 4.1 item 5
    assert "networks" not in caddy  # SPEC-039 section 4.1 item 4 (no alias)
    for name, svc in services.items():
        env = _env_dict(svc.get("environment"))
        # SPEC-039 section 4.1 item 8: only the mandatory ${NAME:?} references, never a value
        if "DATABASE_URL" in env:
            assert name == "api" and env["DATABASE_URL"] == "${DATABASE_URL:?}", name
        if "READ_API_KEY" in env:
            assert env["READ_API_KEY"] == "${READ_API_KEY:?}", name

    assert "image" not in caddy  # SPEC-039 section 4.1 item 5 and section 4.3
    assert caddy["build"] == {"context": "..", "dockerfile": "infra/docker/caddy.Dockerfile"}
    assert "volumes" not in caddy and "volumes" not in data  # SPEC-039 section 4.1 items 5, 9
    assert caddy["cap_drop"] == ["ALL"]
    assert caddy["cap_add"] == ["NET_BIND_SERVICE"]
    deps = caddy["depends_on"]
    assert set(deps) == {"api", "dashboard"}
    if isinstance(deps, dict):
        for dep in deps.values():
            assert (dep or {}).get("condition") != "service_healthy", deps

    for name in ("api", "dashboard"):
        assert services[name]["cap_drop"] == ["ALL"], name

    for name, svc in services.items():
        assert svc["restart"] == "unless-stopped", name
        assert "no-new-privileges:true" in svc["security_opt"], name
        assert svc["logging"] == {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "3"},
        }, name
        mem, cpus = LIMITS[name]
        assert svc["mem_limit"] == mem, name
        assert svc["cpus"] == cpus, name

    assert "networks" not in data  # SPEC-039 section 4.1 item 4: default project network
    for name, svc in services.items():
        assert "networks" not in svc, name


def test_extra_compose_network_is_bridge_and_no_extra_capabilities() -> None:
    data = _load_yaml(COMPOSE)
    # SPEC-039 section 4.1 item 4: no networks key, so the project default (bridge) network
    assert "networks" not in data
    for name in ("api", "dashboard"):
        assert "cap_add" not in data["services"][name], name
        assert "volumes" not in data["services"][name], name
    text = _read(COMPOSE)
    assert "NET_ADMIN" not in text
    assert "SYS_ADMIN" not in text


# ============================================================================================
# CA-30: infra/Caddyfile
# ============================================================================================


def _caddy_text() -> str:
    lines = [line for line in _read(CADDYFILE).splitlines() if not line.strip().startswith("#")]
    return "\n".join(lines)


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


def test_ca30_caddyfile() -> None:
    text = _caddy_text()
    lines = text.splitlines()
    assert not any(line.strip() == "{" for line in lines), "global options block"
    depth = 0
    top_level = []
    for line in lines:
        stripped = line.strip()
        if depth == 0 and stripped:
            top_level.append(stripped)
        depth += stripped.count("{") - stripped.count("}")
        # the `{$PUBLIC_HOST}` placeholder opens and closes on the same line
    assert top_level == [":80 {"], top_level  # SPEC-039 section 4.2

    domain = re.compile(r"\b[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}\b")
    assert not domain.search(text), domain.search(text)
    assert not domain.search(text.lower()), domain.search(text.lower())
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text)

    api_block = _block_after(text, "handle /api/* {")
    assert "reverse_proxy api:8000" in api_block
    bare = [m.start() for m in re.finditer(r"(?m)^\s*handle\s*\{", text)]
    assert len(bare) == 1, "exactly one `handle` without matcher"
    dash_block = _block_after(text[bare[0] :], "handle {")
    assert "reverse_proxy dashboard:8501" in dash_block

    for forbidden in ("handle_path", "tls internal", "acme_ca", "local_certs", "/docs", "openapi"):
        assert forbidden not in text, forbidden
    assert "includesubdomains" not in text.lower()
    assert "preload" not in text.lower()
    assert 'Strict-Transport-Security "max-age=31536000"' in text
    assert 'X-Content-Type-Options "nosniff"' in text


def test_extra_caddyfile_no_log_email_or_debug() -> None:
    words = set(re.findall(r"(?m)^\s*([a-z_]+)\b", _caddy_text()))
    for directive in ("log", "email", "debug", "tls", "acme_dns", "basicauth", "rewrite"):
        assert directive not in words, directive


# ============================================================================================
# CA-31: .github/workflows/docker.yml
# ============================================================================================


def test_ca31_docker_workflow() -> None:
    text = _read(DOCKER_WF)
    wf = yaml.safe_load(text)
    on = _triggers(wf)
    assert set(on) == {"pull_request", "push"}
    assert on["push"]["branches"] == ["main"]
    assert wf["permissions"] == {"contents": "read"}
    jobs = wf["jobs"]
    assert len(jobs) == 1
    job = next(iter(jobs.values()))
    assert job["runs-on"] == "ubuntu-latest"
    assert int(job["timeout-minutes"]) <= 30
    images = [svc.get("image") for svc in (job.get("services") or {}).values()]
    assert "postgres:16" in images, images
    steps = job["steps"]
    uses = [s["uses"] for s in steps if "uses" in s]
    assert any(u.startswith("actions/checkout@v") for u in uses), uses
    assert any(u.startswith("astral-sh/setup-uv@v") for u in uses), uses
    for u in uses:
        assert not u.endswith(("@main", "@master")), u
    runs = [(n, s.get("run", "")) for n, s in enumerate(steps)]
    sync = [n for n, r in runs if "uv sync --all-packages --frozen" in r]
    test = [n for n, r in runs if "uv run pytest -m docker -q" in r]
    assert sync and test and min(sync) < max(test), runs
    step_env = steps[max(test)].get("env") or {}
    job_env = job.get("env") or {}
    value = step_env.get("PARTQC_DOCKER_TESTS", job_env.get("PARTQC_DOCKER_TESTS"))
    assert value == "1", (step_env, job_env)
    for forbidden in ("secrets.", "docker login", "docker push"):
        assert forbidden not in text, forbidden
    assert len(_load_yaml(CI_WF)["jobs"]) == 1


def test_extra_docker_workflow_matches_ci_database_and_has_no_build_network_override() -> None:
    def db_url(wf: dict[str, Any]) -> str | None:
        job = next(iter(wf["jobs"].values()))
        for scope in (wf.get("env") or {}, job.get("env") or {}):
            if "TEST_DATABASE_URL" in scope:
                return scope["TEST_DATABASE_URL"]
        for step in job["steps"]:
            if "TEST_DATABASE_URL" in (step.get("env") or {}):
                return step["env"]["TEST_DATABASE_URL"]
        return None

    docker_wf = _load_yaml(DOCKER_WF)
    assert db_url(docker_wf) is not None
    assert db_url(docker_wf) == db_url(_load_yaml(CI_WF))
    assert "PARTQC_DOCKER_BUILD_NETWORK" not in _read(DOCKER_WF)
    steps = next(iter(docker_wf["jobs"].values()))["steps"]
    assert any("uv python install 3.12" in (s.get("run") or "") for s in steps)


# ============================================================================================
# CA-32: docker marker and docker_support
# ============================================================================================


@pytest.fixture(scope="module")
def support() -> ModuleType:
    return _load_module("partqc_acc015_docker_support", DOCKER_SUPPORT_PATH)


def test_ca32_marker_declared() -> None:
    cfg = tomllib.loads(_read(REPO_ROOT / "pyproject.toml"))
    markers = cfg["tool"]["pytest"]["ini_options"]["markers"]
    assert any(m.startswith("docker:") for m in markers), markers


def test_ca32_docker_tests_enabled(support: ModuleType) -> None:
    assert support.docker_tests_enabled({}) is False
    assert support.docker_tests_enabled({"PARTQC_DOCKER_TESTS": "true"}) is False
    assert support.docker_tests_enabled({"PARTQC_DOCKER_TESTS": "0"}) is False
    assert support.docker_tests_enabled({"PARTQC_DOCKER_TESTS": "1"}) is True
    for odd in (" 1", "1 ", "01", "yes", "TRUE"):
        assert support.docker_tests_enabled({"PARTQC_DOCKER_TESTS": odd}) is False, odd


def test_ca32_check_docker(support: ModuleType) -> None:
    calls: list[list[str]] = []

    def compose_fails(cmd: list[str]) -> int:
        calls.append(cmd)
        return 1 if cmd == ["docker", "compose", "version"] else 0

    with pytest.raises(support.DockerUnavailableError) as exc:
        support.check_docker(run=compose_fails)
    assert "compose" in str(exc.value)

    ok_calls: list[list[str]] = []

    def all_ok(cmd: list[str]) -> int:
        ok_calls.append(cmd)
        return 0

    assert support.check_docker(run=all_ok) is None
    assert ["docker", "version"] in ok_calls
    assert ["docker", "compose", "version"] in ok_calls
    assert ["docker", "buildx", "version"] in ok_calls


def test_extra_check_docker_missing_executable(support: ModuleType) -> None:
    def missing(cmd: list[str]) -> int:
        raise FileNotFoundError(2, "No such file or directory", cmd[0])

    with pytest.raises(support.DockerUnavailableError) as exc:
        support.check_docker(run=missing)
    assert "docker" in str(exc.value)


def test_ca32_copy_tracked_tree(support: ModuleType, tmp_path: Path) -> None:
    before = _git_status()
    ctx = support.copy_tracked_tree(tmp_path / "ctx", {"x/y.txt": b"z"})
    assert Path(ctx) == (tmp_path / "ctx").resolve() or Path(ctx) == tmp_path / "ctx"
    assert (tmp_path / "ctx" / "pyproject.toml").is_file()
    assert (tmp_path / "ctx" / "uv.lock").is_file()
    assert (tmp_path / "ctx" / "x" / "y.txt").read_bytes() == b"z"
    assert _git_status() == before


@pytest.mark.parametrize("rel", ["../escape.txt", "/abs.txt", "a/../../b.txt"])
def test_extra_copy_tracked_tree_refuses_escaping_paths(support, tmp_path: Path, rel: str) -> None:
    with pytest.raises(ValueError):
        support.copy_tracked_tree(tmp_path / "ctx", {rel: b"x"})
    assert not (tmp_path / "escape.txt").exists()


def test_extra_copy_tracked_tree_refuses_destination_inside_repo(support) -> None:
    before = _git_status()
    with pytest.raises(ValueError):
        support.copy_tracked_tree(Path(__file__).resolve().parent / "_ctx_should_not_exist")
    assert not (Path(__file__).resolve().parent / "_ctx_should_not_exist").exists()
    assert _git_status() == before


def _run_probe(env_extra: dict[str, str], path: str | None = None):
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"CI", "TEST_DATABASE_URL", "PARTQC_DOCKER_TESTS", "PYTEST_ADDOPTS"}
    }
    env.update(env_extra)
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", str(MARKER_PROBE)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_extra_docker_marker_hook_skips_without_the_variable() -> None:
    result = _run_probe({})
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "1 skipped" in output, output
    assert "set PARTQC_DOCKER_TESTS=1 to run" in output, output


def test_extra_docker_marker_hook_usage_error_without_docker(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "docker"
    fake.write_text(
        '#!/bin/sh\nif [ "$1" = "compose" ]; then exit 1; fi\nexit 0\n', encoding="utf-8"
    )
    fake.chmod(0o755)
    git = shutil.which("git")
    assert git is not None
    os.symlink(git, bindir / "git")
    result = _run_probe({"PARTQC_DOCKER_TESTS": "1"}, path=str(bindir))
    output = result.stdout + result.stderr
    assert result.returncode == 4, output  # pytest.UsageError
    assert "compose" in output, output
    assert "passed" not in output


# ============================================================================================
# CA-33 .. CA-37: docker
# ============================================================================================


def _bytes_of(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmgt]?)i?b?", text)
    assert m, value
    factor = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}[m.group(2)]
    return int(float(m.group(1)) * factor)


def _compose_env() -> dict[str, str]:
    drop = {"PUBLIC_HOST", "COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_PROFILES"}
    drop |= {"API_MEM_LIMIT", "API_CPUS", "DASHBOARD_MEM_LIMIT", "DASHBOARD_CPUS"}
    drop |= {"CADDY_MEM_LIMIT", "CADDY_CPUS", "DATABASE_URL", "READ_API_KEY"}
    return {k: v for k, v in os.environ.items() if k not in drop}


@pytest.fixture(scope="module")
def compose_copy(tmp_path_factory: pytest.TempPathFactory, support: ModuleType) -> Path:
    if not support.docker_tests_enabled(os.environ):
        pytest.skip(support.SKIP_REASON)
    read_key = secrets.token_urlsafe(32)
    db = "postgresql://<user>:<password>@db.example.org:6543/postgres"
    return support.copy_tracked_tree(
        tmp_path_factory.mktemp("compose-copy"),
        {
            # SPEC-039 section 4.1 items 6 and 7: every variable in the single infra/.env
            "infra/.env": (
                f"PUBLIC_HOST={TEST_HOST}\nDATABASE_URL={db}\nREAD_API_KEY={read_key}\n"
            ).encode(),
        },
    )


def _compose_config(copy: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", str(copy / "infra" / "compose.yaml"), "config"]
        + ["--format", "json"],
        env=_compose_env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.docker
def test_ca33_compose_config_resolves(compose_copy: Path) -> None:
    before = _git_status()
    env_file = compose_copy / "infra" / ".env"
    original_env = env_file.read_bytes()
    try:
        result = _compose_config(compose_copy)
        assert result.returncode == 0, result.stderr
        cfg = json.loads(result.stdout)
        services = cfg["services"]
        assert services["dashboard"]["environment"]["API_BASE_URL"] == f"https://{TEST_HOST}"
        assert "networks" not in services["caddy"] or set(services["caddy"]["networks"]) == {
            "default"
        }  # SPEC-039 section 4.1 item 4: no alias, project default network only
        assert _bytes_of(services["api"]["mem_limit"]) == 512 * 1024**2
        assert _bytes_of(services["dashboard"]["mem_limit"]) == 1024**3
        assert _bytes_of(services["caddy"]["mem_limit"]) == 256 * 1024**2
        assert float(services["api"]["cpus"]) == 1.0
        assert float(services["caddy"]["cpus"]) == 0.5
        assert "DATABASE_URL" not in services["dashboard"].get("environment", {})

        env_file.write_bytes(original_env + b"API_MEM_LIMIT=768m\n")
        result = _compose_config(compose_copy)
        assert result.returncode == 0, result.stderr
        api = json.loads(result.stdout)["services"]["api"]
        assert _bytes_of(api["mem_limit"]) == 768 * 1024**2

        without_host = b"".join(
            line for line in original_env.splitlines(True) if not line.startswith(b"PUBLIC_HOST=")
        )
        env_file.write_bytes(without_host + b"API_MEM_LIMIT=768m\n")
        result = _compose_config(compose_copy)
        assert result.returncode != 0
        assert "PUBLIC_HOST" in result.stderr

        # SPEC-039 section 4.1: no DATABASE_URL in infra/.env replaces the missing infra/.env.api
        env_file.write_bytes(
            b"".join(
                line
                for line in original_env.splitlines(True)
                if not line.startswith(b"DATABASE_URL=")
            )
        )
        result = _compose_config(compose_copy)
        assert result.returncode != 0
    finally:
        env_file.write_bytes(original_env)
    assert _git_status() == before
    assert not (REPO_ROOT / "infra" / ".env").exists()


@pytest.mark.docker
def test_extra_compose_single_quoted_dollar_is_literal(compose_copy: Path) -> None:
    """Section 4.12: a value with ``$`` in single quotes stays literal; unquoted, it is
    interpolated. ``config`` prints a literal ``$`` escaped as ``$$`` (valid compose syntax)."""
    api_env = compose_copy / "infra" / ".env"  # SPEC-039 section 4.1: single infra/.env
    original = api_env.read_bytes()
    value = "ab$cd" + secrets.token_hex(4)
    try:
        api_env.write_bytes(original + f"LOG_LEVEL='{value}'\n".encode())
        result = _compose_config(compose_copy)
        assert result.returncode == 0, result.stderr
        quoted = json.loads(result.stdout)["services"]["api"]["environment"]["LOG_LEVEL"]
        assert quoted == value.replace("$", "$$")

        api_env.write_bytes(original + f"LOG_LEVEL={value}\n".encode())
        result = _compose_config(compose_copy)
        assert result.returncode == 0, result.stderr
        unquoted = json.loads(result.stdout)["services"]["api"]["environment"]["LOG_LEVEL"]
        assert unquoted == "ab", unquoted  # the $cd... part was interpolated (empty)
    finally:
        api_env.write_bytes(original)


def _caddy_image() -> str:
    # SPEC-039 section 4.3: the FROM of infra/docker/caddy.Dockerfile (Caddyfile mounted)
    dockerfile = _read(INFRA / "docker" / "caddy.Dockerfile")
    return re.search(r"(?m)^FROM\s+(\S+)", dockerfile).group(1)  # type: ignore[union-attr]


def _walk(node: Any) -> Iterator[Any]:
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


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
def test_ca34_caddy_adapt(tmp_path: Path) -> None:
    caddyfile = tmp_path / "Caddyfile"
    shutil.copy(CADDYFILE, caddyfile)
    caddyfile.chmod(0o444)
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "none"]  # SPEC-039 section 4.2: no PUBLIC_HOST
        + ["-v", f"{caddyfile}:/etc/caddy/Caddyfile:ro", _caddy_image()]
        + ["caddy", "adapt", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "not formatted" not in result.stderr.lower(), result.stderr
    assert "caddy fmt" not in result.stderr, result.stderr
    cfg = json.loads(result.stdout)

    hosts = [
        host
        for node in _walk(cfg)
        if isinstance(node, dict) and isinstance(node.get("match"), list)
        for matcher in node["match"]
        for host in matcher.get("host", [])
    ]
    assert hosts == [], hosts  # SPEC-039 section 4.2: site :80, no match.host

    handlers = _proxy_handlers(cfg)
    api = [(h, c) for h, c in handlers if h.get("upstreams") == [{"dial": "api:8000"}]]
    dash = [(h, c) for h, c in handlers if h.get("upstreams") == [{"dial": "dashboard:8501"}]]
    assert len(api) == 1 and len(dash) == 1, handlers
    api_paths = [m.get("path") for sets in api[0][1] for m in sets]
    assert ["/api/*"] in api_paths, api[0][1]
    dash_paths = [m.get("path") for sets in dash[0][1] for m in sets if "path" in m]
    assert dash_paths == [], dash[0][1]
    dials = [n["dial"] for n in _walk(cfg) if isinstance(n, dict) and "dial" in n]
    assert sorted(dials) == ["api:8000", "dashboard:8501"], dials

    hsts = [
        n["Strict-Transport-Security"]
        for h in _walk(cfg)
        if isinstance(h, dict) and h.get("handler") == "headers"
        for n in _walk(h)
        if isinstance(n, dict) and "Strict-Transport-Security" in n
    ]
    assert ["max-age=31536000"] in hsts, hsts


@pytest.fixture(scope="module")
def api_image(build_image: Callable[..., str]) -> str:
    return build_image(API_DOCKERFILE)


@pytest.fixture(scope="module")
def dashboard_image(build_image: Callable[..., str]) -> str:
    return build_image(DASHBOARD_DOCKERFILE)


def _docker(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def _run_in(image: str, entrypoint: str, *args: str) -> subprocess.CompletedProcess:
    return _docker("run", "--rm", "--network", "none", "--entrypoint", entrypoint, image, *args)


PROBE_SCRIPT = (
    "import importlib, importlib.util, json, sys\n"
    "absent = {m: importlib.util.find_spec(m) is None for m in sys.argv[1].split(',')}\n"
    "imported = {}\n"
    "for m in sys.argv[2].split(','):\n"
    "    try:\n"
    "        importlib.import_module(m)\n"
    "        imported[m] = True\n"
    "    except Exception as exc:\n"
    "        imported[m] = type(exc).__name__\n"
    "print(json.dumps({'v': list(sys.version_info[:2]), 'absent': absent, 'imported': imported}))\n"
)
ML_MODULES = ["torch", "torchvision", "timm", "onnx", "onnxruntime"]


@pytest.mark.docker
@pytest.mark.parametrize(
    ("component", "absent", "present"),
    [
        ("api", ["streamlit"], ["qc_api", "qc_contracts"]),
        ("dashboard", ["psycopg"], ["qc_dashboard", "qc_contracts", "streamlit"]),
    ],
)
def test_ca35_images_without_ml(request, component: str, absent: list[str], present: list[str]):
    image = request.getfixturevalue(f"{component}_image")
    modules = ",".join(ML_MODULES + absent)
    result = _run_in(image, "python", "-c", PROBE_SCRIPT, modules, ",".join(present))
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["v"] == [3, 12]
    assert all(data["absent"].values()), data["absent"]
    assert all(v is True for v in data["imported"].values()), data["imported"]


SENTINELS_ENV = [
    ".env",
    ".env.prod",
    ".env.migrate",
    "infra/.env",
    "infra/.env.api",
    "infra/.env.dashboard",
    ".streamlit/secrets.toml",
]
SENTINELS_GIT = [
    ".git/config",
    ".claude/settings.local.json",
    "notas-locais/diario.md",
    ".venv/sentinela-do-host",
]
SENTINELS_DATA = [
    "ml/data/raw/screw/good/S-001__a__x.jpg",
    "edge/data/captures/2026-10-18/x.jpg",
    "edge/data/outbox.sqlite3",
    "foto.jpg",
    "foto.jpeg",
    "foto.png",
    "foto.heic",
    "foto.webp",
]
SENTINEL_ONNX = "ml/models/partqc-sentinel-v0/model.onnx"
SENTINELS_KEPT = [
    "ml/models/partqc-sentinel-v0/metrics.json",
    "ml/reports/partqc-sentinel-v0/type_confusion.png",
]
EXTRA_EXCLUDED = [  # exploratory: other names that must not reach an image
    "dashboard/.streamlit/secrets.toml",
    "edge/.env",
    "ml/models/partqc-sentinel-v0/model.pt",
    "ml/models/partqc-sentinel-v0/model.pth",
    "ml/checkpoints/last.ckpt",
    "data/x.csv",
    "api/local.db",
    "notas-locais/resumo.md",
    ".claude/agents/x.md",
    "api/.venv/pyvenv.cfg",
    "api/src/qc_api/__pycache__/x.cpython-312.pyc",
    ".pytest_cache/v/cache/lastfailed",
    ".ruff_cache/x",
    # r2 (RV-04 / T-03 of r1): the same names with upper-case extensions
    "FOTO.JPG",
    "a/IMG_0001.HEIC",
    "b/Foto.Png",
    "c/x.Jpeg",
    "d/y.WEBP",
    "OUTBOX.SQLITE3",
    "edge/local.DB",
    "infra/.ENV.API",
    "secrets/.Env",
    "ml/models/partqc-sentinel-v0/MODEL.ONNX",
    "ml/models/partqc-sentinel-v0/model.PT",
    "certs/server.PEM",
    "certs/server.Key",
]
SENTINEL_KEPT_UPPER = "ml/reports/partqc-sentinel-v0/GRADE_CONFUSION.PNG"


def _sentinel_files() -> dict[str, bytes]:
    files = {}
    for rel in SENTINELS_ENV + SENTINELS_GIT + SENTINELS_DATA + [SENTINEL_ONNX] + EXTRA_EXCLUDED:
        files[rel] = b"partqc-sentinel " + rel.encode()
    files[SENTINELS_KEPT[0]] = b'{"sentinel": true}\n'
    files[SENTINELS_KEPT[1]] = b"\x89PNG\r\n\x1a\nsentinel"
    files[SENTINEL_KEPT_UPPER] = b"\x89PNG\r\n\x1a\nsentinel-upper"
    return files


def _existing(image: str, paths: list[str]) -> set[str]:
    script = 'for p in "$@"; do if test -e "/app/$p"; then echo "Y $p"; fi; done'
    result = _run_in(image, "sh", "-c", script, "sh", *paths)
    assert result.returncode == 0, result.stderr
    return {line[2:] for line in result.stdout.splitlines() if line.startswith("Y ")}


@pytest.mark.docker
@pytest.mark.parametrize("dockerfile", [API_DOCKERFILE, DASHBOARD_DOCKERFILE])
def test_ca36_build_context_filters_sentinels(build_image, dockerfile: str) -> None:
    before = _git_status()
    image = build_image(dockerfile, _sentinel_files())
    assert _git_status() == before
    excluded = SENTINELS_ENV + SENTINELS_GIT + SENTINELS_DATA + [SENTINEL_ONNX]
    kept = [*SENTINELS_KEPT, SENTINEL_KEPT_UPPER, ".streamlit/config.toml"]
    present = _existing(image, excluded + EXTRA_EXCLUDED + kept)
    leaked = sorted(set(excluded) & present)
    assert not leaked, leaked
    leaked_extra = sorted(set(EXTRA_EXCLUDED) & present)
    assert not leaked_extra, leaked_extra
    if dockerfile == DASHBOARD_DOCKERFILE:
        for rel in [*SENTINELS_KEPT, ".streamlit/config.toml"]:
            assert rel in present, rel
        # exploratory (r2, RV-04): an upper-case report PNG is kept like the lower-case one
        assert SENTINEL_KEPT_UPPER in present


@pytest.mark.docker
@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_extra_uv_cache_is_not_in_the_image(request, component: str) -> None:
    """r2 (RV-01): the uv cache stays in the BuildKit cache mount, outside the layers."""
    image = request.getfixturevalue(f"{component}_image")
    script = (
        "for p in /home/app/.cache /root/.cache/uv /root/.cache; do "
        'if test -e "$p"; then echo "PRESENT $p"; fi; done; '
        "find / -xdev -type d -name 'archive-v0' -path '*uv*' 2>/dev/null; "
        "du -sm /home/app | cut -f1"
    )
    result = _run_in(image, "sh", "-c", script)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.split()
    assert not [line for line in result.stdout.splitlines() if line.startswith(("PRESENT", "/"))]
    assert int(lines[-1]) <= 1, lines  # /home/app only has the useradd skeleton


@pytest.mark.docker
@pytest.mark.parametrize(
    ("component", "health"), [("api", "/api/v1/health"), ("dashboard", "/_stcore/health")]
)
def test_ca37_image_config(request, component: str, health: str) -> None:
    image = request.getfixturevalue(f"{component}_image")
    result = _docker("image", "inspect", image)
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)[0]["Config"]
    assert config["User"] == "10001:10001"
    assert config["WorkingDir"] == "/app"
    assert config["Labels"]["partqc.component"] == component
    test = config["Healthcheck"]["Test"]
    assert test[0] == "CMD", test
    assert any(health in part for part in test), test
    assert config["Healthcheck"]["Interval"] == 60_000_000_000
    for item in (config.get("Entrypoint") or []) + (config.get("Cmd") or []):
        assert item not in ("uv", "uvx"), item
    uid = _run_in(image, "id", "-u")
    assert uid.returncode == 0 and uid.stdout.strip() == "10001", uid


@pytest.mark.docker
def test_ca37_dashboard_repo_root_is_app(dashboard_image: str) -> None:
    code = (
        "from qc_dashboard import config; print(config.REPO_ROOT); "
        "print(config.get_model_metrics_path())"
    )
    result = _docker(
        "run", "--rm", "--network", "none", "--entrypoint", "python", dashboard_image, "-c", code
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[-2:] == ["/app", "/app/ml/models/partqc-mnv3-v1/metrics.json"], lines


@pytest.mark.docker
@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_extra_image_hardening(request, component: str) -> None:
    image = request.getfixturevalue(f"{component}_image")
    script = (
        'echo "gid=$(id -g)"; echo "home=$HOME"; '
        "if touch /app/.write-probe 2>/dev/null; then echo writable; else echo readonly; fi; "
        'echo "owner=$(stat -c %u /app/.venv)"; '
        "find /app -maxdepth 3 -name '.env*' -print"
    )
    result = _run_in(image, "sh", "-c", script)
    assert result.returncode == 0, result.stderr
    out = result.stdout.splitlines()
    assert "gid=10001" in out
    assert "home=/home/app" in out
    assert "readonly" in out, out
    assert "owner=0" in out, out
    envs = [line for line in out if line.startswith("/app")]
    assert set(envs) <= {"/app/.env.example"}, envs
    inspect = json.loads(_docker("image", "inspect", image).stdout)[0]["Config"]
    names = [item.split("=", 1)[0] for item in inspect.get("Env") or []]
    for name in names:
        for bad in ("DATABASE_URL", "API_KEY", "TOKEN", "PASSWORD", "SECRET"):
            assert bad not in name.upper(), name
    assert set(inspect.get("ExposedPorts") or {}) == {
        "8000/tcp" if component == "api" else "8501/tcp"
    }


@pytest.mark.docker
@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_extra_image_has_no_tests_docs_or_reviews(request, component: str) -> None:
    image = request.getfixturevalue(f"{component}_image")
    script = (
        "test -e /app/pyproject.toml && test -e /app/uv.lock && echo ok; "
        "find /app -path /app/.venv -prune -o \\( -name '*.onnx' -o -name '*.jpg' "
        "-o -name '*.sqlite3' \\) -print"
    )
    result = _run_in(image, "sh", "-c", script)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert "ok" in lines
    assert [line for line in lines if line != "ok"] == [], lines


# ============================================================================================
# CA-39: .env.example
# ============================================================================================


def test_ca39_env_example() -> None:
    text = _read(ENV_EXAMPLE)
    lines = text.splitlines()
    for expected in (
        "PUBLIC_HOST=<subdominio>",
        "API_MEM_LIMIT=512m",
        "API_CPUS=1.0",
        "DASHBOARD_MEM_LIMIT=1g",
        "DASHBOARD_CPUS=1.0",
        "CADDY_MEM_LIMIT=256m",
        "CADDY_CPUS=0.5",
    ):
        assert expected in lines, expected
    cloud = [line for line in lines if line.startswith("CLOUD_API_URL=")]
    assert cloud == ["CLOUD_API_URL=https://<subdominio>"], cloud
    assert "onrender.com" not in text
    assert "Streamlit Community Cloud" not in text
    idx = next(n for n, line in enumerate(lines) if line.startswith("API_BASE_URL="))
    comments = []
    n = idx - 1
    while n >= 0 and lines[n].lstrip().startswith("#"):
        comments.append(lines[n])
        n -= 1
    assert comments, "no comment right above API_BASE_URL="
    assert ".streamlit/secrets.toml" in "\n".join(comments)


def test_extra_env_example_matches_compose_defaults() -> None:
    lines = _read(ENV_EXAMPLE).splitlines()
    values = dict(line.split("=", 1) for line in lines if re.match(r"^[A-Z_]+=", line))
    for service, (mem, cpus) in LIMITS.items():
        mem_var, mem_default = re.fullmatch(r"\$\{(\w+):-([^}]+)\}", mem).groups()  # type: ignore[union-attr]
        cpu_var, cpu_default = re.fullmatch(r"\$\{(\w+):-([^}]+)\}", cpus).groups()  # type: ignore[union-attr]
        assert values[mem_var] == mem_default, service
        assert values[cpu_var] == cpu_default, service


# ============================================================================================
# CA-41: no IPv4 literal, placeholders for public URLs (R-13)
# ============================================================================================


def test_ca41_no_ipv4_literal_in_deploy_files() -> None:
    files = [
        COMPOSE,
        CADDYFILE,
        RENDER,
        DOCKER_WF,
        KEEPALIVE,
        ENV_EXAMPLE,
        *sorted((INFRA / "docker").iterdir()),
    ]
    assert len(files) >= 10
    ipv4 = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b")
    allowed = {"0.0.0.0", LOOPBACK}
    for path in files:
        for m in ipv4.finditer(_read(path)):
            assert m.group(0) in allowed, (path.name, m.group(0))


def test_ca41_public_urls_are_placeholders() -> None:
    for path in (PLAN, ENV_EXAMPLE):
        text = _read(path)
        for m in re.finditer(r"PUBLIC_HOST=", text):
            context = text[m.start() : m.end() + 30]
            assert text[m.end() :].startswith("<subdominio>"), (path.name, context)
        for m in re.finditer(r"\b(CLOUD_API_URL|DASHBOARD_URL|KEEPALIVE_URL)=(\S*)", text):
            value = m.group(2).strip("`'\"")
            if not value:
                continue
            assert value.startswith(("https://<subdominio>", "https://<servico>.onrender.com")), (
                path.name,
                m.group(0),
            )


def test_extra_no_real_host_hints_in_deploy_files() -> None:
    """The public files never carry a concrete domain other than example/documentation hosts."""
    domain = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|app|br|me|xyz|cloud)\b")
    allowed_suffixes = (
        "example.org",
        "example.com",
        "github.com",
        "docker.com",
        "supabase.com",
        "render.com",
        "onrender.com",
        "caddyserver.com",
        "letsencrypt.org",
        "astral.sh",
        "ghcr.io",
        "streamlit.io",
        "python.org",
    )
    for path in (COMPOSE, CADDYFILE, RENDER, KEEPALIVE, DOCKER_WF, *(INFRA / "docker").iterdir()):
        for m in domain.finditer(_read(path).lower()):
            assert m.group(0).endswith(allowed_suffixes), (path.name, m.group(0))


# ============================================================================================
# misc exploratory: scope guards of section 3
# ============================================================================================


def test_extra_no_root_dockerignore_and_no_dashboard_requirements() -> None:
    tracked = set(_tracked_files())
    assert ".dockerignore" not in tracked
    assert "dashboard/requirements.txt" not in tracked
    assert not (REPO_ROOT / ".dockerignore").exists()


@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_extra_dockerignore_mandatory_patterns(component: str) -> None:
    lines = [
        line.strip()
        for line in _read(INFRA / "docker" / f"{component}.Dockerfile.dockerignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    required = [
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
    normal = {line.rstrip("/") for line in lines}
    missing = [p for p in required if p.rstrip("/") not in normal]
    assert not missing, missing
    forbidden = ["pyproject.toml", "uv.lock", "packages", "packages/", "ml/reports", "ml/reports/"]
    forbidden += [".streamlit/config.toml", "ml/models/**/*.json", "*.toml", "**/*.json"]
    assert not [p for p in lines if p in forbidden], lines
    # the png exception must come after the png exclusion
    png = lines.index("**/*.png")
    keep = lines.index("!ml/reports/**/*.png")
    assert keep > png
    # r2 (RV-04): case-insensitive variants, with every exception after every exclusion it opens
    for variant in ("**/*.[jJ][pP][gG]", "**/*.[pP][nN][gG]", "**/*.[hH][eE][iI][cC]"):
        assert variant in lines, variant
    assert any(line.startswith("**/.[eE][nN][vV]") for line in lines), lines
    last_png_exclusion = max(
        n for n, line in enumerate(lines) if line in {"**/*.png", "**/*.[pP][nN][gG]"}
    )
    first_png_exception = min(n for n, line in enumerate(lines) if line.startswith("!ml/reports/"))
    assert first_png_exception > last_png_exclusion
    last_env_exclusion = max(
        n
        for n, line in enumerate(lines)
        if line.startswith("**/.") and "nN" in line or line == "**/.env*"
    )
    assert lines.index("!.env.example") > last_env_exclusion
