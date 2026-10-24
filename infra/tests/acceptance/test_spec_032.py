"""Acceptance tests for SPEC-032 (deploy maintenance: smoke parser, case-insensitive
``.gitignore``, Caddy headers and container hardening).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test per automatable CA at least (``test_caNN_*``, CA-01 to CA-08; CA-09 is
manual, on the VPS); ``test_extra_*`` tests cover requirements of SPEC-032 section 4 that no CA
spells out, plus exploratory edge cases.

The tests marked ``docker`` run only with ``PARTQC_DOCKER_TESTS=1`` (SPEC-015 section 4.14):
images are built from a temporary copy of the tracked tree (``build_image``), the real working
tree is never written, and every container, network and volume created here is removed. No
credential appears as a literal: keys and markers are generated at run time; the database URL
uses the ``<user>:<password>`` markers of the SPEC-015 docker tests.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import yaml

import qc_contracts

REPO_ROOT = Path(__file__).resolve().parents[3]
INFRA = REPO_ROOT / "infra"
GITIGNORE = REPO_ROOT / ".gitignore"
CADDYFILE = INFRA / "Caddyfile"
COMPOSE = INFRA / "compose.yaml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
PLAN = REPO_ROOT / "docs" / "deployment-plan.md"
SMOKE_PATH = REPO_ROOT / "scripts" / "smoke_test.py"
DOCKER_SUPPORT_PATH = INFRA / "tests" / "docker_support.py"
API_DOCKERFILE = "infra/docker/api.Dockerfile"
DASHBOARD_DOCKERFILE = "infra/docker/dashboard.Dockerfile"

TEST_HOST = "partqc.example.org"
TEST_URL = f"https://{TEST_HOST}"
SERVICES = ("caddy", "api", "dashboard")
PIDS_LIMIT = {
    "api": "${API_PIDS_LIMIT:-256}",
    "dashboard": "${DASHBOARD_PIDS_LIMIT:-256}",
    "caddy": "${CADDY_PIDS_LIMIT:-256}",
}
# Fictitious database URL of the SPEC-015 docker tests (markers, never a credential).
FAKE_DB_URL = "postgresql://<user>:<password>@db.example.org:6543/postgres"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(_read(path))


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


def _git_status() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout


# ============================================================================================
# CA-01: smoke_test.py refuses abbreviations without echoing values (section 4.1)
# ============================================================================================


@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    return _load_module("partqc_acc032_smoke_test", SMOKE_PATH)


@pytest.fixture
def smoke_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    env = {
        "READ_API_KEY": secrets.token_urlsafe(32),
        "SIM_DEVICE_ID": "sim-01",
        "SIM_DEVICE_API_KEY": secrets.token_urlsafe(32),
        "CLOUD_API_URL": TEST_URL,
        "DASHBOARD_URL": TEST_URL,
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return env


class RecordingCloud:
    """API + dashboard of ``partqc.example.org`` behind an ``httpx.MockTransport``.

    Behaves as a correct deployment (SPEC-015 CA-08): open health, write and read protected by
    their keys, no CORS header, dashboard root and ``/_stcore/health`` answering ``ok``.
    """

    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.requests: list[httpx.Request] = []
        self.written: list[dict[str, Any]] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == TEST_HOST, request.url
        path = request.url.path
        key = request.headers.get("x-api-key")
        if path == "/api/v1/health" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "db": "ok",
                    "api_version": "0.0.0",
                    "contract_version": qc_contracts.__version__,
                },
            )
        if path == "/api/v1/inspections" and request.method == "POST":
            if key != self.env["SIM_DEVICE_API_KEY"]:
                return httpx.Response(401, json={"detail": "Invalid or missing API key"})
            payload = json.loads(request.content)
            item = qc_contracts.InspectionCreate.model_validate(payload)
            if item.device_id != self.env["SIM_DEVICE_ID"]:
                return httpx.Response(403, json={"detail": "forbidden"})
            self.written.append(payload)
            return httpx.Response(
                201, json={"inspection_id": str(item.inspection_id), "status": "created"}
            )
        if path == "/api/v1/inspections" and request.method == "GET":
            if key != self.env["READ_API_KEY"]:
                return httpx.Response(401, json={"detail": "Invalid or missing API key"})
            params = request.url.params
            items = [
                {**w, "received_at": w["inspected_at"], "is_defective": False}
                for w in self.written
                if ("lot_id" not in params or w["lot_id"] == params["lot_id"])
                and ("source" not in params or w["source"] == params["source"])
            ]
            return httpx.Response(
                200, json={"items": items, "total": len(items), "limit": 50, "offset": 0}
            )
        if path.startswith("/api/"):
            return httpx.Response(404, json={"detail": "Not Found"})
        if path.endswith("/_stcore/health"):
            return httpx.Response(200, text="ok")
        return httpx.Response(200, text="<html><body>PartQC</body></html>")


def _call_main(smoke: ModuleType, argv: list[str], cloud: RecordingCloud) -> int:
    try:
        code = smoke.main(argv, transport=cloud.transport)
    except SystemExit as exc:  # argparse may exit instead of returning
        code = exc.code
    return code


def _abbreviated_cases(marker: str) -> list[list[str]]:
    return [
        ["--=" + marker],
        ["--api=https://" + marker + ".example.org"],
        ["--dash", "https://" + marker + ".example.org"],
    ]


def test_ca01_smoke_refuses_abbreviations_without_echo(smoke, smoke_env, capsys) -> None:
    marker = "mk" + secrets.token_hex(10)
    for argv in _abbreviated_cases(marker):
        cloud = RecordingCloud(smoke_env)
        code = _call_main(smoke, argv, cloud)
        out, err = capsys.readouterr()
        assert code == 2, (argv, out, err)
        assert cloud.requests == [], argv
        assert marker not in out, argv
        assert marker not in err, argv

    cloud = RecordingCloud(smoke_env)
    argv = ["--api-url", TEST_URL, "--dashboard-url", TEST_URL]
    code = _call_main(smoke, argv, cloud)
    out, err = capsys.readouterr()
    assert code == 0, (out, err)
    assert len(cloud.written) == 1
    for value in (smoke_env["READ_API_KEY"], smoke_env["SIM_DEVICE_API_KEY"]):
        assert value not in out + err


def test_extra_smoke_abbreviation_message_cites_only_the_count(smoke, smoke_env, capsys) -> None:
    """Section 4.1: the output cites only the count (``(not shown)``), never ``ambiguous``."""
    marker = "mk" + secrets.token_hex(10)
    for argv in _abbreviated_cases(marker):
        _call_main(smoke, argv, RecordingCloud(smoke_env))
        out, err = capsys.readouterr()
        text = out + err
        assert "(not shown)" in text, (argv, text)
        assert "ambiguous" not in text.lower(), (argv, text)


@pytest.mark.parametrize(
    "build",
    [
        lambda m: ["--api-u", "https://" + m + ".example.org"],
        lambda m: ["--api-url=" + TEST_URL, "--dashboard=https://" + m + ".example.org"],
        lambda m: ["--dashboard-u", "https://" + m + ".example.org"],
        lambda m: ["--d=" + m],
        lambda m: ["--a", m],
        lambda m: ["--=" + m, "--api-url", TEST_URL, "--dashboard-url", TEST_URL],
        lambda m: ["--api-url", TEST_URL, "--dashboard-url", TEST_URL, "--dash=" + m],
        lambda m: ["--h=" + m],
        lambda m: ["--he", m],
        lambda m: ["--API-URL", "https://" + m + ".example.org"],
        lambda m: ["--=" + "\u00e7\u00e3o-" + m],
        lambda m: ["--", m],
    ],
    ids=[
        "api-u",
        "dashboard-eq",
        "dashboard-u",
        "d-eq",
        "a-space",
        "empty-name-plus-valid",
        "valid-plus-dash-eq",
        "h-eq",
        "he-space",
        "uppercase",
        "unicode",
        "double-dash-separator",
    ],
)
def test_extra_smoke_more_abbreviations_are_refused(smoke, smoke_env, capsys, build) -> None:
    marker = "mk" + secrets.token_hex(10)
    argv = build(marker)
    cloud = RecordingCloud(smoke_env)
    code = _call_main(smoke, argv, cloud)
    out, err = capsys.readouterr()
    assert code == 2, (argv, out, err)
    assert cloud.requests == [], argv
    assert marker not in out + err, argv


def test_extra_smoke_full_names_with_equals_still_work(smoke, smoke_env, capsys) -> None:
    cloud = RecordingCloud(smoke_env)
    code = _call_main(smoke, ["--api-url=" + TEST_URL, "--dashboard-url=" + TEST_URL], cloud)
    out, err = capsys.readouterr()
    assert code == 0, (out, err)


def test_extra_smoke_help_still_works(smoke, smoke_env, capsys) -> None:
    code = _call_main(smoke, ["--help"], RecordingCloud(smoke_env))
    out, _ = capsys.readouterr()
    assert code == 0
    assert "--api-url" in out and "--dashboard-url" in out


def test_extra_smoke_cli_subprocess_refuses_abbreviations(tmp_path: Path) -> None:
    """The real entry point (``python scripts/smoke_test.py``), not only ``main``."""
    marker = "mk" + secrets.token_hex(10)
    env = dict(os.environ)
    env.update(
        {
            "READ_API_KEY": secrets.token_urlsafe(16),
            "SIM_DEVICE_ID": "sim-01",
            "SIM_DEVICE_API_KEY": secrets.token_urlsafe(16),
            "CLOUD_API_URL": TEST_URL,
            "DASHBOARD_URL": TEST_URL,
        }
    )
    for argv in _abbreviated_cases(marker):
        result = subprocess.run(
            ["python", str(SMOKE_PATH), *argv],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 2, (argv, result.stderr)
        assert marker not in result.stdout + result.stderr, argv
        assert "Traceback" not in result.stderr, argv


def test_extra_smoke_parser_source_disables_abbreviations() -> None:
    assert "allow_abbrev=False" in _read(SMOKE_PATH)


# ============================================================================================
# CA-02 and CA-03: .gitignore in any case (section 4.2)
# ============================================================================================

# The .gitignore before SPEC-032 (commit a544d0a), kept literally: every line must still exist.
PREVIOUS_GITIGNORE = """\
# --- Python / uv ---
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/
*.egg-info/
dist/
build/

# --- Segredos (R-03) ---
.env
.env.*
!.env.example
.streamlit/secrets.toml
*.pem
*.key

# --- Dados e imagens (R-02, R-14) ---
ml/data/
edge/data/
data/
*.jpg
*.jpeg
*.png
!docs/**/*.png
!ml/reports/**/*.png

# --- Modelos (pesos vão em GitHub Releases) ---
ml/models/**/*.onnx
ml/models/**/*.pt
ml/models/**/*.pth
ml/checkpoints/

# --- Borda ---
*.sqlite
*.sqlite3
*.db

# --- Notebooks / IDE / SO ---
.ipynb_checkpoints/
.vscode/
.idea/
.DS_Store

# --- Claude Code (local) ---
.claude/settings.local.json
.claude/worktrees/
"""

CA02_IGNORED = [
    "ml/data/raw/screw/fair/IMG_0001.JPG",
    "fotos/FOTO.JPEG",
    "fotos/Foto.Png",
    "fotos/IMG_0002.HEIC",
    "fotos/a.heic",
    "fotos/a.WEBP",
    "ml/models/v1/MODEL.ONNX",
    "ml/models/v1/best.PT",
    "edge/OUTBOX.SQLITE3",
    "x/LOCAL.DB",
    "CERT.PEM",
    "id.KEY",
    ".ENV",
    ".Env.prod",
    "infra/.ENV.API",
]
CA02_KEPT = [
    ".env.example",
    ".streamlit/config.toml",
    "ml/reports/v1/grade_confusion.png",
    "ml/reports/v1/GRADE_CONFUSION.PNG",
    "docs/img/Arquitetura.PNG",
    "ml/tests/fixtures/tiny_model/model.onnx",
]

# Only the repository .gitignore: no global excludes file, Linux case sensitivity.
GIT_ISOLATED = ["git", "-c", "core.excludesFile=/dev/null", "-c", "core.ignorecase=false"]


def _ignored(path: str) -> bool:
    result = subprocess.run(
        [*GIT_ISOLATED, "check-ignore", "--no-index", "-q", path],
        cwd=REPO_ROOT,
        check=False,
        timeout=60,
    )
    assert result.returncode in (0, 1), result
    return result.returncode == 0


@pytest.mark.parametrize("path", CA02_IGNORED)
def test_ca02_gitignore_ignores_in_any_case(path: str) -> None:
    assert _ignored(path), path


@pytest.mark.parametrize("path", CA02_KEPT)
def test_ca02_gitignore_keeps(path: str) -> None:
    assert not _ignored(path), path


def test_ca02_previous_gitignore_lines_unchanged() -> None:
    current = _read(GITIGNORE).splitlines()
    missing = [line for line in PREVIOUS_GITIGNORE.splitlines() if line and line not in current]
    assert missing == [], missing


def test_extra_previous_gitignore_lines_keep_their_order() -> None:
    current = _read(GITIGNORE).splitlines()
    previous = [line for line in PREVIOUS_GITIGNORE.splitlines() if line]
    positions = [current.index(line) for line in previous]
    assert positions == sorted(positions), list(zip(previous, positions, strict=True))


VARIANTS = {
    ".env": ".[eE][nN][vV]",
    ".env.*": ".[eE][nN][vV].*",
    "*.pem": "*.[pP][eE][mM]",
    "*.key": "*.[kK][eE][yY]",
    "*.jpg": "*.[jJ][pP][gG]",
    "*.jpeg": "*.[jJ][pP][eE][gG]",
    "*.png": "*.[pP][nN][gG]",
    "ml/models/**/*.onnx": "ml/models/**/*.[oO][nN][nN][xX]",
    "ml/models/**/*.pt": "ml/models/**/*.[pP][tT]",
    "ml/models/**/*.pth": "ml/models/**/*.[pP][tT][hH]",
    "*.sqlite": "*.[sS][qQ][lL][iI][tT][eE]",
    "*.sqlite3": "*.[sS][qQ][lL][iI][tT][eE]3",
    "*.db": "*.[dD][bB]",
}


def test_extra_gitignore_variants_and_exception_order() -> None:
    """Section 4.2 table and its rule: exceptions after every exclusion of their group."""
    lines = [line.strip() for line in _read(GITIGNORE).splitlines()]
    for literal, variant in VARIANTS.items():
        assert literal in lines, literal
        assert variant in lines, variant
    for photo in ("*.[hH][eE][iI][cC]", "*.[wW][eE][bB][pP]"):
        assert photo in lines, photo
    env_rules = [lines.index(p) for p in (".env", ".env.*", ".[eE][nN][vV]", ".[eE][nN][vV].*")]
    assert lines.index("!.env.example") > max(env_rules)
    photos = {"*.jpg", "*.jpeg", "*.png", "*.heic", "*.webp"}
    photo_rules = [
        n
        for n, line in enumerate(lines)
        if re.sub(r"\[([a-z])[A-Z]\]", r"\1", line).lower() in photos
    ]
    assert len(photo_rules) == 8, photo_rules
    for exception in (
        "!docs/**/*.png",
        "!ml/reports/**/*.png",
        "!docs/**/*.[pP][nN][gG]",
        "!ml/reports/**/*.[pP][nN][gG]",
    ):
        assert exception in lines, exception
        assert lines.index(exception) > max(photo_rules), exception


@pytest.mark.parametrize(
    "path",
    [
        ".eNv",
        "sub/dir/.ENV.local",
        ".env.Example",  # not the literal exception: stays ignored (the safe side)
        ".ENV.EXAMPLE",
        "a.JpG",
        "deep/x/y/z.jPeG",
        "Captura.WebP",
        "IMG.Heic",
        "docs/img/foto.JPG",  # only PNG is re-included under docs/
        "ml/models/a/b/c/w.Pth",
        "ml/models/a/m.OnNx",
        "x.Sqlite",
        "x.SQLite3",
        "server.Key",
        "chain.Pem",
        "entrada/IMG_1234.JPG",
        "entrada/a.HEIC",
    ],
)
def test_extra_gitignore_more_case_variants_ignored(path: str) -> None:
    assert _ignored(path), path


@pytest.mark.parametrize(
    "path",
    [
        "docs/img/A.PnG",
        "ml/reports/x/Curve.pNg",
        "ml/onnx_export.py",
        "edge/src/qc_edge/db.py",
        "api/src/qc_api/keys.py",
        "notes.keynote",
        "README.md",
        "foto.jpg.txt",
        "ml/MODEL.ONNX",  # weights are only ignored under ml/models/
    ],
)
def test_extra_gitignore_does_not_overreach(path: str) -> None:
    assert not _ignored(path), path


VARIANT_LINE = re.compile(r"\[[a-z][A-Z]\]")


def _ls_files_ignored(exclude_from: Path) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.excludesFile=/dev/null",
            "ls-files",
            "-ci",
            f"--exclude-from={exclude_from}",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return result.stdout


def test_ca03_variants_do_not_ignore_tracked_files(tmp_path: Path) -> None:
    text = _read(GITIGNORE)
    without = [line for line in text.splitlines() if not VARIANT_LINE.search(line)]
    assert len(without) < len(text.splitlines()), "no variant line found"
    assert "*.py[cod]" in without  # the existing class is not a variant of this SPEC
    copy = tmp_path / "gitignore-without-variants"
    copy.write_text("\n".join(without) + "\n", encoding="utf-8")
    assert _ls_files_ignored(GITIGNORE) == _ls_files_ignored(copy)


def test_extra_no_tracked_file_is_ignored() -> None:
    """Exploratory: today no tracked file is ignored by the current .gitignore at all."""
    assert _ls_files_ignored(GITIGNORE) == ""


# ============================================================================================
# CA-04: Caddyfile headers (section 4.3)
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


HEADER_LINES = [
    "-Server",
    "-Via",
    'Referrer-Policy "no-referrer"',
    "Content-Security-Policy \"frame-ancestors 'self'\"",
    'Strict-Transport-Security "max-age=31536000"',
    'X-Content-Type-Options "nosniff"',
]


def test_ca04_caddyfile_headers() -> None:
    text = _caddy_text()
    for expected in HEADER_LINES:
        assert expected in text, expected

    # CA-30 of SPEC-015 still holds.
    lines = text.splitlines()
    assert not any(line.strip() == "{" for line in lines), "global options block"
    depth = 0
    top_level = []
    for line in lines:
        stripped = line.strip()
        if depth == 0 and stripped:
            top_level.append(stripped)
        depth += stripped.count("{") - stripped.count("}")
    assert top_level == ["{$PUBLIC_HOST} {"], top_level
    domain = re.compile(r"\b[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}\b")
    assert not domain.search(text.lower()), domain.search(text.lower())
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text)
    assert "reverse_proxy api:8000" in _block_after(text, "handle /api/* {")
    bare = [m.start() for m in re.finditer(r"(?m)^\s*handle\s*\{", text)]
    assert len(bare) == 1, "exactly one `handle` without matcher"
    assert "reverse_proxy dashboard:8501" in _block_after(text[bare[0] :], "handle {")
    for forbidden in ("handle_path", "tls internal", "acme_ca", "local_certs", "/docs", "openapi"):
        assert forbidden not in text, forbidden
    assert "includesubdomains" not in text.lower()
    assert "preload" not in text.lower()


def test_extra_caddyfile_headers_are_in_one_header_block_and_no_full_csp() -> None:
    text = _caddy_text()
    blocks = [m.start() for m in re.finditer(r"(?m)^\s*header\s*\{", text)]
    assert len(blocks) == 1, blocks
    block = _block_after(text[blocks[0] :], "header {")
    for expected in HEADER_LINES:
        assert expected in block, expected
    # Section 3.2: only frame-ancestors, no full Content-Security-Policy.
    for directive in ("default-src", "script-src", "connect-src", "style-src", "img-src"):
        assert directive not in text, directive
    assert text.count("Content-Security-Policy") == 1
    # The header block applies to the whole site, not only to one route.
    assert "header {" not in _block_after(text, "handle /api/* {")


def test_extra_caddyfile_has_no_trailing_whitespace_or_tabs_mixing() -> None:
    """Cheap proxy of ``caddy fmt`` (the docker CA-05 checks the real warning)."""
    for n, line in enumerate(_read(CADDYFILE).splitlines(), 1):
        assert line == line.rstrip(), n
        indent = line[: len(line) - len(line.lstrip())]
        assert " " not in indent, (n, "caddy fmt indents with tabs")


# ============================================================================================
# CA-05 (docker): caddy adapt
# ============================================================================================


def _walk(node: Any) -> Iterator[Any]:
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _caddy_image() -> str:
    return _load_yaml(COMPOSE)["services"]["caddy"]["image"]


def _docker(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


@pytest.mark.docker
def test_ca05_caddy_adapt_headers(tmp_path: Path) -> None:
    caddyfile = tmp_path / "Caddyfile"
    shutil.copy(CADDYFILE, caddyfile)
    caddyfile.chmod(0o444)
    result = _docker(
        "run",
        "--rm",
        "--network",
        "none",
        "-e",
        f"PUBLIC_HOST={TEST_HOST}",
        "-v",
        f"{caddyfile}:/etc/caddy/Caddyfile:ro",
        _caddy_image(),
        "caddy",
        "adapt",
        "--config",
        "/etc/caddy/Caddyfile",
        timeout=600,
    )
    assert result.returncode == 0, result.stderr
    assert "not formatted" not in result.stderr.lower(), result.stderr
    assert "caddy fmt" not in result.stderr, result.stderr
    cfg = json.loads(result.stdout)
    handlers = [n for n in _walk(cfg) if isinstance(n, dict) and n.get("handler") == "headers"]
    expected_set = {
        "Referrer-Policy": ["no-referrer"],
        "Content-Security-Policy": ["frame-ancestors 'self'"],
        "Strict-Transport-Security": ["max-age=31536000"],
        "X-Content-Type-Options": ["nosniff"],
    }
    matching = []
    for handler in handlers:
        response = handler.get("response") or {}
        deleted = set(response.get("delete") or [])
        values = response.get("set") or {}
        if {"Server", "Via"} <= deleted and all(
            values.get(name) == value for name, value in expected_set.items()
        ):
            matching.append(handler)
    assert matching, json.dumps(handlers, indent=1)


@pytest.mark.docker
def test_extra_caddy_adapt_single_header_handler_is_deferred(tmp_path) -> None:
    """One site-wide ``headers`` handler, deferred: the deletion runs after ``reverse_proxy``."""
    caddyfile = tmp_path / "Caddyfile"
    shutil.copy(CADDYFILE, caddyfile)
    caddyfile.chmod(0o444)
    result = _docker(
        "run", "--rm", "--network", "none", "-e", f"PUBLIC_HOST={TEST_HOST}",
        "-v", f"{caddyfile}:/etc/caddy/Caddyfile:ro", _caddy_image(),
        "caddy", "adapt", "--config", "/etc/caddy/Caddyfile",
        timeout=600,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    cfg = json.loads(result.stdout)
    handlers = [n for n in _walk(cfg) if isinstance(n, dict) and n.get("handler") == "headers"]
    assert len(handlers) == 1, handlers
    assert handlers[0]["response"].get("deferred") is True, handlers[0]


# ============================================================================================
# CA-06: compose hardening (section 4.4)
# ============================================================================================


def _size_bytes(value: str) -> int:
    m = re.fullmatch(r"(\d+)([kmg]?)", value.strip().lower())
    assert m, value
    return int(m.group(1)) * {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[m.group(2)]


def _tmpfs_items(svc: dict[str, Any]) -> list[str]:
    tmpfs = svc.get("tmpfs")
    assert tmpfs is not None
    return [tmpfs] if isinstance(tmpfs, str) else list(tmpfs)


def _tmpfs_size(item: str) -> str | None:
    _, _, options = item.partition(":")
    for opt in options.split(","):
        if opt.startswith("size="):
            return opt[len("size=") :]
    return None


def test_ca06_compose_hardening() -> None:
    services = _load_yaml(COMPOSE)["services"]
    assert set(services) == set(SERVICES)
    for name, svc in services.items():
        assert svc.get("read_only") is True, name
        assert svc.get("pids_limit") == PIDS_LIMIT[name], (name, svc.get("pids_limit"))
        items = _tmpfs_items(svc)
        assert any(item.startswith("/tmp") for item in items), (name, items)
        for item in items:
            size = _tmpfs_size(item)
            assert size is not None, (name, item)
            assert _size_bytes(size) <= 64 * 1024**2, (name, item)
            assert item.startswith(("/tmp", "/home/app")), (name, item)
            if item.startswith("/home/app"):
                assert name in ("api", "dashboard"), (name, item)


def test_extra_compose_tmpfs_mount_points_are_exact() -> None:
    """``/tmpfoo`` or ``/home/application`` would pass a bare ``startswith``."""
    services = _load_yaml(COMPOSE)["services"]
    for name, svc in services.items():
        for item in _tmpfs_items(svc):
            target = item.split(":", 1)[0]
            assert target in ("/tmp", "/home/app"), (name, target)
        targets = [i.split(":", 1)[0] for i in _tmpfs_items(svc)]
        assert len(targets) == len(set(targets)), (name, targets)


def test_extra_compose_keeps_caddy_volumes_writable() -> None:
    caddy = _load_yaml(COMPOSE)["services"]["caddy"]
    assert "caddy_data:/data" in caddy["volumes"]
    assert "caddy_config:/config" in caddy["volumes"]
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in caddy["volumes"]


def test_extra_env_example_pids_variables_in_the_infra_block() -> None:
    lines = _read(ENV_EXAMPLE).splitlines()
    start = next(
        n
        for n, line in enumerate(lines)
        if line.startswith("# ----------") and "infra/.env" in line
    )
    end = next(n for n in range(start + 1, len(lines)) if lines[n].startswith("# ----------"))
    block = lines[start:end]
    for var in ("API_PIDS_LIMIT", "DASHBOARD_PIDS_LIMIT", "CADDY_PIDS_LIMIT"):
        assert f"{var}=256" in block, var
        assert sum(1 for line in lines if line.startswith(f"{var}=")) == 1, var


def test_extra_deployment_plan_documents_limits_and_diagnosis() -> None:
    text = _read(PLAN)
    for needle in (
        "pids_limit",
        "read_only",
        "Read-only file system",
        "API_PIDS_LIMIT",
        "DASHBOARD_PIDS_LIMIT",
        "CADDY_PIDS_LIMIT",
        "up -d",
        "Referrer-Policy",
        "frame-ancestors",
    ):
        assert needle in text, needle


def _compose_env() -> dict[str, str]:
    prefixes = ("API_", "DASHBOARD_", "CADDY_", "COMPOSE_")
    drop = {"PUBLIC_HOST", "DATABASE_URL", "READ_API_KEY"}
    return {k: v for k, v in os.environ.items() if k not in drop and not k.startswith(prefixes)}


@pytest.fixture
def compose_copy(tmp_path: Path) -> Path:
    support = _load_module("partqc_acc032_docker_support", DOCKER_SUPPORT_PATH)
    read_key = secrets.token_urlsafe(32)
    return support.copy_tracked_tree(
        tmp_path / "compose-copy",
        {
            "infra/.env": f"PUBLIC_HOST={TEST_HOST}\n".encode(),
            # SPEC-015 section 4.12: env_file entries are required; fictitious values.
            "infra/.env.api": f"DATABASE_URL={FAKE_DB_URL}\nREAD_API_KEY={read_key}\n".encode(),
            "infra/.env.dashboard": f"READ_API_KEY={read_key}\n".encode(),
        },
    )


def _compose(copy: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", str(copy / "infra" / "compose.yaml"), *args],
        env=_compose_env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.docker
def test_ca06_compose_config_quiet(compose_copy: Path) -> None:
    before = _git_status()
    result = _compose(compose_copy, "config", "--quiet")
    assert result.returncode == 0, result.stderr
    assert _git_status() == before
    assert not (REPO_ROOT / "infra" / ".env").exists()


@pytest.mark.docker
def test_extra_compose_config_resolves_pids_and_override(compose_copy: Path) -> None:
    result = _compose(compose_copy, "config", "--format", "json")
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    for name in SERVICES:
        assert int(services[name]["pids_limit"]) == 256, name
        assert services[name]["read_only"] is True, name
    env_file = compose_copy / "infra" / ".env"
    env_file.write_text(f"PUBLIC_HOST={TEST_HOST}\nDASHBOARD_PIDS_LIMIT=512\n", encoding="utf-8")
    result = _compose(compose_copy, "config", "--format", "json")
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert int(services["dashboard"]["pids_limit"]) == 512
    assert int(services["api"]["pids_limit"]) == 256
    env_file.write_text(f"PUBLIC_HOST={TEST_HOST}\nAPI_PIDS_LIMIT=abc\n", encoding="utf-8")
    result = _compose(compose_copy, "config", "--quiet")
    assert result.returncode != 0
    assert "abc" not in result.stdout


# ============================================================================================
# CA-07 / CA-08 (docker): containers under the compose security options
# ============================================================================================


@pytest.fixture(scope="module")
def api_image(build_image: Callable[..., str]) -> str:
    return build_image(API_DOCKERFILE)


@pytest.fixture(scope="module")
def dashboard_image(build_image: Callable[..., str]) -> str:
    return build_image(DASHBOARD_DOCKERFILE)


def _tmpfs_args(service: str) -> list[str]:
    svc = _load_yaml(COMPOSE)["services"][service]
    args: list[str] = []
    for item in _tmpfs_items(svc):
        args += ["--tmpfs", item]
    return args


def _hardened_run(service: str) -> list[str]:
    return [
        "--read-only",
        *_tmpfs_args(service),
        "--pids-limit",
        "256",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "10001:10001",
    ]


class Containers:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.networks: list[str] = []

    def run(self, image: str, *options: str, args: tuple[str, ...] = ()) -> str:
        name = f"partqc-acc032-{uuid.uuid4().hex[:10]}"
        result = _docker("run", "-d", "--name", name, *options, image, *args)
        assert result.returncode == 0, result.stderr
        self.names.append(name)
        return name

    def network(self) -> str:
        name = f"partqc-acc032-net-{uuid.uuid4().hex[:8]}"
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


HTTP_PROBE = (
    "import sys, urllib.request, urllib.error\n"
    "try:\n"
    "    r = urllib.request.urlopen(sys.argv[1], timeout=10)\n"
    "    print(r.status); print(r.read().decode()[:200])\n"
    "except urllib.error.HTTPError as e:\n"
    "    print(e.code); print(e.read().decode()[:200])\n"
)


def _http_in(name: str, url: str) -> tuple[int | None, str]:
    result = _docker("exec", name, "python", "-c", HTTP_PROBE, url, timeout=60)
    lines = result.stdout.splitlines()
    if result.returncode != 0 or not lines or not lines[0].isdigit():
        return None, result.stdout + result.stderr
    return int(lines[0]), "\n".join(lines[1:])


FORBIDDEN_LOG = ("Read-only file system", "EROFS", "PermissionError")


def _assert_write_rules(name: str) -> None:
    tmp = _docker("exec", name, "touch", "/tmp/x")
    assert tmp.returncode == 0, tmp.stderr
    app = _docker("exec", name, "touch", "/app/x")
    assert app.returncode != 0, "/app is writable"


@pytest.mark.docker
def test_ca07_dashboard_runs_read_only(dashboard_image: str, containers: Containers) -> None:
    name = containers.run(dashboard_image, "--network", "none", *_hardened_run("dashboard"))

    def healthy() -> bool:
        status = _inspect(name, "{{.State.Health.Status}}")
        assert _inspect(name, "{{.State.Status}}") == "running", _logs(name)
        return status == "healthy"

    assert _wait(healthy, 90), _logs(name)
    status, body = _http_in(name, "http://127.0.0.1:8501/_stcore/health")
    assert status == 200, body
    assert body.strip() == "ok", body
    logs = _logs(name)
    for needle in FORBIDDEN_LOG:
        assert needle not in logs, (needle, logs)
    _assert_write_rules(name)


@pytest.mark.docker
def test_ca07_api_runs_read_only(api_image: str, containers: Containers) -> None:
    env = ["-e", f"DATABASE_URL={FAKE_DB_URL}", "-e", f"READ_API_KEY={secrets.token_urlsafe(32)}"]
    name = containers.run(api_image, "--network", "none", *env, *_hardened_run("api"))
    answered: dict[str, Any] = {}

    def responds() -> bool:
        assert _inspect(name, "{{.State.Status}}") == "running", _logs(name)
        status, body = _http_in(name, "http://127.0.0.1:8000/api/v1/health")
        answered.update(status=status, body=body)
        return status is not None

    assert _wait(responds, 90), (answered, _logs(name))
    assert answered["status"] in (200, 503), answered
    logs = _logs(name)
    for needle in FORBIDDEN_LOG:
        assert needle not in logs, (needle, logs)
    _assert_write_rules(name)


@pytest.mark.docker
@pytest.mark.parametrize("component", ["api", "dashboard"])
def test_extra_hardening_is_effective_inside(request, containers: Containers, component) -> None:
    """Exploratory: root fs read-only, /tmp a 64m noexec tmpfs, pids.max 256, /home/app ro."""
    image = request.getfixturevalue(f"{component}_image")
    env = ["-e", f"DATABASE_URL={FAKE_DB_URL}", "-e", "READ_API_KEY=x" + secrets.token_hex(16)]
    name = containers.run(image, "--network", "none", *env, *_hardened_run(component))
    script = (
        "cat /sys/fs/cgroup/pids.max; "
        "awk '$2==\"/tmp\"{print $3, $4}' /proc/mounts; "
        "awk '$2==\"/\"{print $4}' /proc/mounts | cut -d, -f1; "
        "id -u; "
        "if touch /home/app/x 2>/dev/null; then echo home-writable; else echo home-ro; fi"
    )
    result = _docker("exec", name, "sh", "-c", script)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "256", lines
    fstype, options = lines[1].split(" ", 1)
    assert fstype == "tmpfs", lines
    assert "size=65536k" in options, options
    assert "noexec" in options and "nosuid" in options, options
    assert lines[2] == "ro", lines
    assert lines[3] == "10001", lines
    assert lines[4] == "home-ro", lines


@pytest.mark.docker
def test_ca08_caddy_runs_read_only(containers: Containers) -> None:
    caddy = _load_yaml(COMPOSE)["services"]["caddy"]
    name = containers.run(
        caddy["image"],
        "--read-only",
        *_tmpfs_args("caddy"),
        "-v",
        "/data",
        "-v",
        "/config",
        "--pids-limit",
        "256",
        "--network",
        "none",
        "-v",
        f"{CADDYFILE}:/etc/caddy/Caddyfile:ro",
        "-e",
        f"PUBLIC_HOST={TEST_HOST}",
    )
    time.sleep(10)
    assert _inspect(name, "{{.State.Status}}") == "running", _logs(name)
    assert "read-only file system" not in _logs(name).lower(), _logs(name)


@pytest.mark.docker
def test_extra_caddy_with_compose_capabilities_writes_only_volumes(containers) -> None:
    """Exploratory: same as CA-08 plus the compose ``cap_drop``/``cap_add``; /etc stays ro."""
    caddy = _load_yaml(COMPOSE)["services"]["caddy"]
    name = containers.run(
        caddy["image"],
        "--read-only", *_tmpfs_args("caddy"), "-v", "/data", "-v", "/config",
        "--pids-limit", "256", "--network", "none",
        "--cap-drop", "ALL", "--cap-add", "NET_BIND_SERVICE",
        "--security-opt", "no-new-privileges",
        "-v", f"{CADDYFILE}:/etc/caddy/Caddyfile:ro", "-e", f"PUBLIC_HOST={TEST_HOST}",
    )  # fmt: skip
    time.sleep(10)
    assert _inspect(name, "{{.State.Status}}") == "running", _logs(name)
    assert "read-only file system" not in _logs(name).lower(), _logs(name)
    script = (
        "for d in /tmp /data /config /etc; do "
        'if touch "$d/.probe" 2>/dev/null; then echo "$d rw"; else echo "$d ro"; fi; done; '
        "cat /sys/fs/cgroup/pids.max"
    )
    result = _docker("exec", name, "sh", "-c", script)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split("\n")[:5] == ["/tmp rw", "/data rw", "/config rw", "/etc ro", "256"]


# ============================================================================================
# Exploratory (docker): headers on real responses through reverse_proxy
# ============================================================================================


HEADERS_PROBE = (
    "import http.client, json, sys\n"
    "conn = http.client.HTTPConnection(sys.argv[1], int(sys.argv[4]), timeout=30)\n"
    "conn.request('GET', sys.argv[2], headers={'Host': sys.argv[3]})\n"
    "resp = conn.getresponse()\n"
    "print(json.dumps([resp.status, [[k.lower(), v] for k, v in resp.getheaders()]]))\n"
)


def _headers_via_caddy(
    client_image: str, net: str, path: str, target: str = "edge", port: int = 80
) -> tuple[int, dict[str, str]]:
    """Status and headers (lower-case names) of ``GET path`` sent to ``target`` (Caddy).

    The client is a throwaway container of the API image (its Python) on the same internal
    network: busybox ``wget -S`` hides the headers of a non-2xx response.
    """
    result = _docker(
        "run", "--rm", "--network", net, "--entrypoint", "python", client_image,
        "-c", HEADERS_PROBE, target, path, TEST_HOST, str(port),
        timeout=90,
    )  # fmt: skip
    if result.returncode != 0:
        return 0, {}
    status, pairs = json.loads(result.stdout.strip().splitlines()[-1])
    return status, {key: value for key, value in pairs}


@pytest.mark.docker
def test_extra_headers_through_reverse_proxy(api_image, dashboard_image, containers) -> None:
    """The real Caddyfile in front of the real images, on an internal network.

    ``PUBLIC_HOST=http://partqc.example.org`` makes the same site block plain HTTP, so the
    response can be read without a certificate; the header block is unchanged.
    """
    net = containers.network()
    env = ["-e", f"DATABASE_URL={FAKE_DB_URL}", "-e", "READ_API_KEY=x" + secrets.token_hex(16)]
    containers.run(
        api_image, "--network", net, "--network-alias", "api", *env, *_hardened_run("api")
    )
    dash = containers.run(
        dashboard_image, "--network", net, "--network-alias", "dashboard",
        *_hardened_run("dashboard"),
    )  # fmt: skip
    caddy = containers.run(
        _caddy_image(), "--network", net, "--network-alias", "edge",
        "--read-only", *_tmpfs_args("caddy"),
        "-v", "/data", "-v", "/config", "--pids-limit", "256",
        "-v", f"{CADDYFILE}:/etc/caddy/Caddyfile:ro", "-e", f"PUBLIC_HOST=http://{TEST_HOST}",
    )  # fmt: skip
    probe = _headers_via_caddy
    assert _wait(lambda: probe(api_image, net, "/api/v1/health")[0] in (200, 503), 90), _logs(caddy)
    assert _wait(lambda: _inspect(dash, "{{.State.Health.Status}}") == "healthy", 90)
    # The origins do identify themselves, so the absence below is Caddy's doing.
    assert "server" in probe(api_image, net, "/api/v1/health", "api", 8000)[1]
    assert "server" in probe(api_image, net, "/_stcore/health", "dashboard", 8501)[1]
    expected = {
        "referrer-policy": "no-referrer",
        "content-security-policy": "frame-ancestors 'self'",
        "strict-transport-security": "max-age=31536000",
        "x-content-type-options": "nosniff",
    }
    for path in ("/api/v1/health", "/_stcore/health", "/"):
        status, headers = probe(api_image, net, path)
        assert status in (200, 503), (path, status, headers)
        assert "server" not in headers, (path, headers)
        assert "via" not in headers, (path, headers)
        for key, value in expected.items():
            assert headers.get(key) == value, (path, key, headers)
