"""Acceptance tests for SPEC-038, Part B (Caddy error responses, photo and video formats in
``.gitignore`` and in the ``.dockerignore`` files, ``pids_limit`` notes).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One test (at least) per automated CA, named ``test_caNN_*`` (CA-12 to CA-17;
CA-18 is manual, on the VPS); ``test_extra_*`` tests are exploratory edge cases around the SPEC
(``security`` tag). Part B follows the top note of the SPEC (ADR-023): the site is ``:80``, the
image is built from ``infra/docker/caddy.Dockerfile`` and runs with the options of CA-12 of
SPEC-039.

The tests marked ``docker`` run only with ``PARTQC_DOCKER_TESTS=1`` (SPEC-015 section 4.14):
images are built from a temporary copy of the tracked tree (``build_image``), the real working
tree is never written, containers run with ``--network none`` and are removed at the end. The
only host used is ``partqc.example.org``; markers are generated at run time.
"""

from __future__ import annotations

import importlib.util
import json
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

pytestmark = pytest.mark.acceptance

REPO_ROOT = Path(__file__).resolve().parents[3]
INFRA = REPO_ROOT / "infra"
CADDYFILE = INFRA / "Caddyfile"
GITIGNORE = REPO_ROOT / ".gitignore"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
PLAN = REPO_ROOT / "docs" / "deployment-plan.md"
DOCKERIGNORES = {
    "api": INFRA / "docker" / "api.Dockerfile.dockerignore",
    "dashboard": INFRA / "docker" / "dashboard.Dockerfile.dockerignore",
}
CADDY_DOCKERIGNORE = INFRA / "docker" / "caddy.Dockerfile.dockerignore"
ACC_DIR = Path(__file__).resolve().parent

API_DOCKERFILE = "infra/docker/api.Dockerfile"
DASHBOARD_DOCKERFILE = "infra/docker/dashboard.Dockerfile"
CADDY_DOCKERFILE = "infra/docker/caddy.Dockerfile"

TEST_HOST = "partqc.example.org"
STATICRESP_URL = "https://github.com/caddyserver/caddy/blob/master/modules/caddyhttp/staticresp.go"

# Section 4.9 / SPEC-032 section 4.3: the 6 lines of the header block.
HEADER_LINES = [
    'Strict-Transport-Security "max-age=31536000"',
    'X-Content-Type-Options "nosniff"',
    'Referrer-Policy "no-referrer"',
    "Content-Security-Policy \"frame-ancestors 'self'\"",
    "-Server",
    "-Via",
]
EXPECTED_SET = {
    "Strict-Transport-Security": ["max-age=31536000"],
    "X-Content-Type-Options": ["nosniff"],
    "Referrer-Policy": ["no-referrer"],
    "Content-Security-Policy": ["frame-ancestors 'self'"],
}
EXPECTED_HEADERS = {
    "strict-transport-security": "max-age=31536000",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "content-security-policy": "frame-ancestors 'self'",
}

# Section 4.10: the 9 lines, only in the character-class form.
NEW_PATTERNS = [
    "*.[hH][eE][iI][fF]",
    "*.[jJ][fF][iI][fF]",
    "*.[jJ][pP][eE]",
    "*.[tT][iI][fF]",
    "*.[tT][iI][fF][fF]",
    "*.[dD][nN][gG]",
    "*.[aA][vV][iI][fF]",
    "*.[mM][oO][vV]",
    "*.[mM][pP]4",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_module(name: str, path: Path) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _docker(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def _walk(node: Any) -> Iterator[Any]:
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


# ============================================================================================
# Caddyfile as text (comments removed by the Caddyfile rule)
# ============================================================================================


def strip_comments(text: str) -> str:
    """Remove Caddyfile comments: a ``#`` at the start of a token (line start or after
    whitespace), outside a quoted or backtick token, comments out the rest of the line."""
    out: list[str] = []
    for line in text.splitlines():
        quote: str | None = None
        cut = len(line)
        prev = " "
        for pos, char in enumerate(line):
            if quote:
                if char == quote and prev != "\\":
                    quote = None
            elif char in '"`':
                quote = char
            elif char == "#" and prev.isspace():
                cut = pos
                break
            prev = char
        kept = line[:cut].rstrip()
        if kept.strip():
            out.append(kept)
    return "\n".join(out)


def caddy_text() -> str:
    return strip_comments(_read(CADDYFILE))


def block_body(text: str, open_at: int) -> tuple[int, int]:
    """Start and end (exclusive) of the body of the block whose ``{`` is at ``open_at``."""
    assert text[open_at] == "{"
    depth = 0
    for pos in range(open_at, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return open_at + 1, pos
    raise AssertionError("unbalanced block")


def directive_blocks(text: str, name: str) -> list[tuple[str, int, int]]:
    """``(rest of the line, body start, body end)`` of each block opened by ``name``."""
    found = []
    for m in re.finditer(rf"(?m)^[ \t]*{re.escape(name)}\b([^\n{{]*)\{{[ \t]*$", text):
        start, end = block_body(text, m.start() + m.group(0).rindex("{"))
        found.append((m.group(1).strip(), start, end))
    return found


def depth_at(text: str, pos: int) -> int:
    return text[:pos].count("{") - text[:pos].count("}")


def block_lines(body: str) -> list[str]:
    return [line.strip() for line in body.splitlines() if line.strip()]


ENV_PLACEHOLDER = re.compile(r"\{env\.|\{\$")
ERR_PLACEHOLDER = re.compile(r"\{err\.(?!status_code\})")


def env_placeholders(raw: str) -> list[str]:
    return ENV_PLACEHOLDER.findall(strip_comments(raw))


def site_and_errors(text: str) -> tuple[str, str, str]:
    """``(site body, handle_errors body, site body without the handle_errors block)``."""
    sites = directive_blocks(text, ":80")
    assert len(sites) == 1, sites
    _, s_start, s_end = sites[0]
    site = text[s_start:s_end]
    errors = directive_blocks(site, "handle_errors")
    assert len(errors) == 1, errors
    _, e_start, e_end = errors[0]
    without = site[: site.rfind("handle_errors", 0, e_start)] + site[e_end + 1 :]
    return site, site[e_start:e_end], without


# ============================================================================================
# CA-12: Caddyfile (section 4.9, SEC-39-06)
# ============================================================================================


def _acc(name: str) -> ModuleType:
    return _load_module(f"partqc_acc038_{name}", ACC_DIR / f"test_{name}.py")


def test_ca12_previous_caddyfile_conditions_still_hold() -> None:
    """CA-30 of SPEC-015, CA-04 of SPEC-032 and CA-04 of SPEC-039 (top note of SPEC-038)."""
    _acc("spec_015").test_ca30_caddyfile()
    _acc("spec_032").test_ca04_caddyfile_headers()
    _acc("spec_039").test_ca04_caddyfile()


def test_ca12_one_handle_errors_without_argument_inside_the_site() -> None:
    text = caddy_text()
    handles = [m for m in re.finditer(r"(?m)^[ \t]*handle_errors\b(.*)$", text)]
    assert len(handles) == 1, [m.group(0) for m in handles]
    assert handles[0].group(1).strip() == "{", handles[0].group(0)  # no status codes
    (site_open,) = [m.end() - 1 for m in re.finditer(r"(?m)^:80 \{$", text)]
    s_start, s_end = block_body(text, site_open)
    assert s_start < handles[0].start() < s_end
    assert depth_at(text, handles[0].start()) == 1  # a direct child of the :80 site


def test_ca12_handle_errors_has_the_six_header_lines() -> None:
    _, errors, _ = site_and_errors(caddy_text())
    headers = directive_blocks(errors, "header")
    assert len(headers) == 1, headers
    _, h_start, h_end = headers[0]
    lines = block_lines(errors[h_start:h_end])
    assert sorted(lines) == sorted(HEADER_LINES), lines


@pytest.mark.parametrize("token", ["reverse_proxy", "file_server", "templates", "rewrite"])
def test_ca12_handle_errors_never_forwards_or_renders(token: str) -> None:
    _, errors, _ = site_and_errors(caddy_text())
    assert token not in errors


def test_ca12_handle_errors_uses_no_err_placeholder_but_the_status_code() -> None:
    _, errors, _ = site_and_errors(caddy_text())
    assert ERR_PLACEHOLDER.findall(errors) == []


def test_ca12_site_header_block_outside_handle_errors_has_the_six_lines() -> None:
    _, _, without = site_and_errors(caddy_text())
    headers = directive_blocks(without, "header")
    assert len(headers) == 1, headers
    _, h_start, h_end = headers[0]
    assert sorted(block_lines(without[h_start:h_end])) == sorted(HEADER_LINES)


def test_ca12_no_environment_placeholder_in_the_whole_file() -> None:
    raw = _read(CADDYFILE)
    text = strip_comments(raw)
    assert "{env." not in text
    assert "{$" not in text
    assert "PUBLIC_HOST" not in text


@pytest.mark.parametrize(
    "line",
    [
        "\t\trespond {env.READ_API_KEY}",
        '\t\trespond "{$READ_API_KEY}"',
        "\t\theader X-K {$READ_API_KEY:padrao}",
        "\t\theader X-H {env.PUBLIC_HOST}",
        "\t\trespond `{$X}`",
    ],
)
def test_ca12_control_the_placeholder_check_detects_a_planted_line(line: str) -> None:
    """Negative control of the CA-12 detector on a modified copy (never the real file)."""
    raw = _read(CADDYFILE)
    planted = raw.replace(":80 {\n", ":80 {\n" + line + "\n", 1)
    assert planted != raw
    assert env_placeholders(planted), line
    commented = raw.replace(":80 {\n", ":80 {\n\t# " + line.strip() + "\n", 1)
    assert env_placeholders(commented) == []


# ============================================================================================
# CA-13 (docker): caddy adapt
# ============================================================================================


@pytest.fixture(scope="module")
def caddy_image(build_image: Callable[..., str]) -> str:
    return build_image(CADDY_DOCKERFILE)


def _adapt(image: str) -> subprocess.CompletedProcess:
    # top note of SPEC-038, CA-13: no PUBLIC_HOST in the environment
    return _docker(
        "run", "--rm", "--network", "none", image,
        "caddy", "adapt", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile",
        timeout=300,
    )  # fmt: skip


def _matching_headers(node: Any) -> list[dict[str, Any]]:
    found = []
    for handler in (
        n for n in _walk(node) if isinstance(n, dict) and n.get("handler") == "headers"
    ):
        response = handler.get("response") or {}
        values = response.get("set") or {}
        if {"Server", "Via"} <= set(response.get("delete") or []) and all(
            values.get(k) == v for k, v in EXPECTED_SET.items()
        ):
            found.append(handler)
    return found


@pytest.mark.docker
def test_ca13_caddy_adapt_puts_the_headers_in_the_error_routes(caddy_image: str) -> None:
    result = _adapt(caddy_image)
    assert result.returncode == 0, result.stderr
    assert "not formatted" not in result.stderr.lower(), result.stderr
    assert "caddy fmt" not in result.stderr, result.stderr
    cfg = json.loads(result.stdout)
    servers = cfg["apps"]["http"]["servers"]
    assert servers
    for name, server in servers.items():
        error_routes = (server.get("errors") or {}).get("routes")
        assert error_routes, (name, server.keys())
        assert _matching_headers(error_routes), json.dumps(error_routes, indent=1)
        proxies = [
            n
            for n in _walk(error_routes)
            if isinstance(n, dict) and n.get("handler") == "reverse_proxy"
        ]
        assert proxies == [], proxies
        # CA-05 of SPEC-032 still holds in the routes of the server
        assert _matching_headers(server.get("routes", [])), json.dumps(server, indent=1)


# ============================================================================================
# CA-14 (docker): the error response generated by Caddy
# ============================================================================================


class Containers:
    def __init__(self) -> None:
        self.names: list[str] = []

    def run(self, image: str, *options: str) -> str:
        name = f"partqc-test-acc038-{uuid.uuid4().hex[:10]}"
        result = _docker("run", "-d", "--name", name, *options, image)
        assert result.returncode == 0, result.stderr
        self.names.append(name)
        return name

    def cleanup(self) -> None:
        if self.names:
            _docker("rm", "-f", "-v", *self.names)


@pytest.fixture
def containers() -> Iterator[Containers]:
    box = Containers()
    yield box
    box.cleanup()


# CA-12 of SPEC-039 (top note of SPEC-038, CA-14)
HARDENED = (
    "--network", "none", "--read-only",
    "--tmpfs", "/tmp", "--tmpfs", "/data", "--tmpfs", "/config",
    "--cap-drop", "ALL", "--cap-add", "NET_BIND_SERVICE", "--pids-limit", "256",
)  # fmt: skip


def _inspect(name: str, fmt: str) -> str:
    return _docker("inspect", "--format", fmt, name).stdout.strip()


# The client keeps its side of the connection open until the response headers arrive: a
# client that half-closes right after the request (``printf ... | nc``) makes Caddy cancel the
# request and answer 499 instead of the 502 (Go's server sees the EOF), which is a property of
# that client, not of the Caddyfile.
PROBE_SH = r"""
d=$(mktemp -d /tmp/acc038.XXXXXX); mkfifo "$d/in"
nc 127.0.0.1 80 < "$d/in" > "$d/out" 2>/dev/null & pid=$!
exec 3>"$d/in"
printf '%b' "$1" >&3
i=0
while [ "$i" -lt 150 ]; do
  if tr -d '\r' < "$d/out" | grep -qx ''; then sleep 0.5; break; fi
  sleep 0.1; i=$((i+1))
done
kill "$pid" 2>/dev/null; exec 3>&-
cat "$d/out"; rm -rf "$d"
"""


def raw_request(container: str, request: str) -> bytes:
    """Raw HTTP/1.1 from inside the container to ``127.0.0.1:80`` (busybox ``nc``)."""
    assert "%" not in request and "\\" not in request
    escaped = request.replace("\r", "\\r").replace("\n", "\\n")
    result = subprocess.run(
        ["docker", "exec", "-i", container, "sh", "-s", escaped],
        input=PROBE_SH.encode("ascii"),
        capture_output=True,
        timeout=60,
        check=False,
    )
    return result.stdout


def get(container: str, path: str, *, method: str = "GET", host: str = TEST_HOST) -> bytes:
    request = (
        f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: acc038\r\n"
        "Connection: close\r\n\r\n"
    )
    return raw_request(container, request)


def parse(raw: bytes) -> tuple[int, list[tuple[str, str]], bytes]:
    head, sep, body = raw.partition(b"\r\n\r\n")
    assert sep, raw[:500]
    lines = head.decode("iso-8859-1").split("\r\n")
    status_line = lines[0].split(" ", 2)
    assert status_line[0] == "HTTP/1.1", lines[0]
    headers = [
        (k.strip().lower(), v.strip()) for k, v in (line.split(":", 1) for line in lines[1:])
    ]
    if ("transfer-encoding", "chunked") in headers:
        decoded = b""
        rest = body
        while True:
            size_line, _, rest = rest.partition(b"\r\n")
            size = int(size_line.split(b";")[0], 16)
            if size == 0:
                break
            decoded += rest[:size]
            rest = rest[size + 2 :]
        body = decoded
    return int(status_line[1]), headers, body


def _wait_until_listening(name: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        assert _inspect(name, "{{.State.Status}}") == "running", _docker("logs", name).stderr
        if get(name, "/").startswith(b"HTTP/1.1"):
            return
        time.sleep(1)
    raise AssertionError("caddy did not answer on :80")


@pytest.fixture
def caddy_alone(caddy_image: str, containers: Containers) -> str:
    """The Caddy image with the real Caddyfile and without ``api`` and ``dashboard``."""
    name = containers.run(caddy_image, *HARDENED)
    _wait_until_listening(name)
    return name


def assert_error_response(raw: bytes, status: int = 502) -> list[tuple[str, str]]:
    code, headers, body = parse(raw)
    assert code == status, raw[:600]
    names = [k for k, _ in headers]
    for header, value in EXPECTED_HEADERS.items():
        assert (header, value) in headers, (header, headers)
    assert "server" not in names, headers
    assert "via" not in names, headers
    assert body == b"", body
    return headers


@pytest.mark.docker
def test_ca14_502_from_caddy_has_the_headers_and_an_empty_body(caddy_alone: str) -> None:
    for path in ("/api/v1/health", "/"):
        assert_error_response(get(caddy_alone, path))
    assert _inspect(caddy_alone, "{{.State.Status}}") == "running"


# ============================================================================================
# CA-15: .gitignore (section 4.10)
# ============================================================================================

CA15_IGNORED = [
    "entrada/IMG_0001.HEIF",
    "entrada/foto.heif",
    "fotos/a.JFIF",
    "fotos/a.jfif",
    "fotos/a.JPE",
    "fotos/a.jpe",
    "scan/a.TIF",
    "scan/a.tiff",
    "scan/a.Tiff",
    "raw/IMG_0001.DNG",
    "fotos/a.avif",
    "fotos/A.AVIF",
    "entrada/IMG_0001.MOV",
    "entrada/v.mov",
    "entrada/v.MP4",
    "entrada/v.mp4",
    "docs/img/foto.tif",
    "ml/reports/v1/curva.tiff",
]
CA15_KEPT = [
    ".env.example",
    "docs/img/Arquitetura.PNG",
    "ml/reports/v1/grade_confusion.png",
    "edge/src/qc_edge/importer.py",
    "notas.movie",
    "video.mp4.txt",
    "README.md",
    "ml/tests/fixtures/tiny_model/model.onnx",
]

# The .gitignore of the start of round r1 (before the Part B commit), copied literally.
START_GITIGNORE = """\
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
# O Git no Linux diferencia maiúsculas nos padrões (core.ignorecase=false): cada padrão literal
# tem ao lado uma variante com classes de caracteres (SPEC-032 §4.2, RV-04 da SPEC-015).
.env
.env.*
.[eE][nN][vV]
.[eE][nN][vV].*
!.env.example
.streamlit/secrets.toml
*.pem
*.key
*.[pP][eE][mM]
*.[kK][eE][yY]

# --- Dados e imagens (R-02, R-14) ---
ml/data/
edge/data/
data/
*.jpg
*.jpeg
*.png
*.[jJ][pP][gG]
*.[jJ][pP][eE][gG]
*.[pP][nN][gG]
*.[hH][eE][iI][cC]
*.[wW][eE][bB][pP]
!docs/**/*.png
!ml/reports/**/*.png
!docs/**/*.[pP][nN][gG]
!ml/reports/**/*.[pP][nN][gG]

# --- Modelos (pesos vão em GitHub Releases) ---
ml/models/**/*.onnx
ml/models/**/*.pt
ml/models/**/*.pth
ml/models/**/*.[oO][nN][nN][xX]
ml/models/**/*.[pP][tT]
ml/models/**/*.[pP][tT][hH]
ml/checkpoints/

# --- Borda ---
*.sqlite
*.sqlite3
*.db
*.[sS][qQ][lL][iI][tT][eE]
*.[sS][qQ][lL][iI][tT][eE]3
*.[dD][bB]

# --- Notebooks / IDE / SO ---
.ipynb_checkpoints/
.vscode/
.idea/
.DS_Store

# --- Claude Code (local) ---
.claude/settings.local.json
.claude/worktrees/
"""

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


@pytest.mark.parametrize("path", CA15_IGNORED)
def test_ca15_gitignore_ignores_the_new_formats(path: str) -> None:
    assert _ignored(path), path


@pytest.mark.parametrize("path", CA15_KEPT)
def test_ca15_gitignore_keeps(path: str) -> None:
    assert not _ignored(path), path


def test_ca15_lines_of_the_start_of_the_round_kept_in_order() -> None:
    current = _read(GITIGNORE).splitlines()
    previous = [line for line in START_GITIGNORE.splitlines() if line]
    missing = [line for line in previous if line not in current]
    assert missing == [], missing
    positions = [current.index(line) for line in previous]
    assert positions == sorted(positions), list(zip(previous, positions, strict=True))


def test_ca15_no_tracked_file_is_ignored() -> None:
    result = subprocess.run(
        ["git", "-c", "core.excludesFile=/dev/null", "ls-files", "-ci", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert result.stdout == ""


def test_extra_gitignore_new_lines_only_class_form_before_the_png_exceptions() -> None:
    """Section 4.10: one line per extension, only the class form, in "Dados e imagens",
    before the PNG exceptions; no literal duplicate."""
    lines = [line.strip() for line in _read(GITIGNORE).splitlines()]
    group = lines.index("# --- Dados e imagens (R-02, R-14) ---")
    first_exception = lines.index("!docs/**/*.png")
    for pattern in NEW_PATTERNS:
        assert lines.count(pattern) == 1, pattern
        assert group < lines.index(pattern) < first_exception, pattern
    for literal in ("*.heif", "*.jfif", "*.jpe", "*.tif", "*.tiff", "*.dng", "*.avif", "*.mov"):
        assert literal not in lines, literal
    assert "*.mp4" not in lines


@pytest.mark.parametrize(
    "path",
    ["x.HeIf", "a/b/c/d/e.mP4", "IMG.DnG", "x.TiFf", "y.JfIf", "deep/z.AvIf", "docs/img/a.mov"],
)
def test_extra_gitignore_more_variants(path: str) -> None:
    assert _ignored(path), path


@pytest.mark.parametrize(
    "path", ["x.mp3", "x.heifx", "a.tiffany", "movie.txt", "docs/img/a.png", "x.mpeg"]
)
def test_extra_gitignore_does_not_overreach(path: str) -> None:
    assert not _ignored(path), path


# ============================================================================================
# CA-16: .dockerignore (section 4.10)
# ============================================================================================

DOCKER_PATTERNS = ["**/" + p for p in NEW_PATTERNS]


@pytest.mark.parametrize("component", sorted(DOCKERIGNORES))
def test_ca16_dockerignore_has_the_nine_lines_before_the_exception(component: str) -> None:
    lines = [line.strip() for line in _read(DOCKERIGNORES[component]).splitlines()]
    exception = lines.index("!ml/reports/**/*.png")
    for pattern in DOCKER_PATTERNS:
        assert pattern in lines, (component, pattern)
        assert lines.index(pattern) < exception, (component, pattern)


CA16_SENTINELS = [
    "foto.HEIF",
    "foto.jfif",
    "foto.JPE",
    "scan.tif",
    "scan.TIFF",
    "raw.dng",
    "foto.AVIF",
    "IMG_0001.MOV",
    "video.mp4",
]
# exploratory: the same names inside folders that the Dockerfiles copy
CA16_NESTED = [
    "api/foto.HEIF",
    "dashboard/IMG_0001.MOV",
    "packages/contracts/scan.tif",
    "ml/reports/v1/curva.TIFF",
]


def _existing(image: str, paths: list[str]) -> set[str]:
    script = 'for p in "$@"; do if test -e "/app/$p"; then echo "Y $p"; fi; done'
    result = _docker(
        "run", "--rm", "--network", "none", "--entrypoint", "sh", image,
        "-c", script, "sh", *paths,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    return {line[2:] for line in result.stdout.splitlines() if line.startswith("Y ")}


@pytest.mark.docker
@pytest.mark.parametrize("dockerfile", [API_DOCKERFILE, DASHBOARD_DOCKERFILE])
def test_ca16_sentinels_never_reach_the_images(
    build_image: Callable[..., str], dockerfile: str
) -> None:
    marker = b"partqc-acc038-" + secrets.token_hex(8).encode()
    files = {rel: marker for rel in CA16_SENTINELS + CA16_NESTED}
    image = build_image(dockerfile, files)
    # control: the image does have /app with the copied tree
    assert _existing(image, ["pyproject.toml"]) == {"pyproject.toml"}
    assert _existing(image, CA16_SENTINELS + CA16_NESTED) == set()


@pytest.mark.docker
@pytest.mark.parametrize("dockerfile", [API_DOCKERFILE, DASHBOARD_DOCKERFILE])
def test_ca16_ca36_of_spec_015_still_holds(
    build_image: Callable[..., str], dockerfile: str
) -> None:
    _acc("spec_015").test_ca36_build_context_filters_sentinels(build_image, dockerfile)


# The rules (no comments, no blank lines) of both .dockerignore files at the start of round r1,
# copied literally (identical in the api and dashboard files).
START_DOCKERIGNORE_RULES = """\
.git
.github
.claude/
notas-locais/
.vscode/
.idea/
**/.env*
**/.[eE][nN][vV]*
!.env.example
.streamlit/secrets.toml
**/secrets.toml
**/*.pem
**/*.key
**/*.[pP][eE][mM]
**/*.[kK][eE][yY]
ml/data/
edge/data/
data/
**/*.jpg
**/*.jpeg
**/*.png
**/*.heic
**/*.webp
**/*.[jJ][pP][gG]
**/*.[jJ][pP][eE][gG]
**/*.[pP][nN][gG]
**/*.[hH][eE][iI][cC]
**/*.[wW][eE][bB][pP]
!ml/reports/**/*.png
!ml/reports/**/*.[pP][nN][gG]
ml/models/**/*.onnx
ml/models/**/*.pt
ml/models/**/*.pth
ml/checkpoints/
**/*.onnx
**/*.pt
**/*.pth
**/*.npz
**/*.[oO][nN][nN][xX]
**/*.[pP][tT]
**/*.[pP][tT][hH]
**/*.[nN][pP][zZ]
ml/notebooks/
**/*.sqlite
**/*.sqlite3
**/*.db
**/*.[sS][qQ][lL][iI][tT][eE]
**/*.[sS][qQ][lL][iI][tT][eE]3
**/*.[dD][bB]
**/.venv
**/__pycache__
**/*.py[cod]
.pytest_cache
.ruff_cache
.mypy_cache
.coverage
htmlcov/
**/*.egg-info
docs/
reviews/
**/tests
infra/
"""


@pytest.mark.parametrize("component", sorted(DOCKERIGNORES))
def test_extra_dockerignore_keeps_every_rule_of_the_start_of_the_round(component: str) -> None:
    """Section 4.10: no existing line leaves, changes or moves; only the 9 lines are new."""
    current = [
        line.strip()
        for line in _read(DOCKERIGNORES[component]).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    previous = START_DOCKERIGNORE_RULES.splitlines()
    missing = [line for line in previous if line not in current]
    assert missing == [], missing
    positions = [current.index(line) for line in previous]
    assert positions == sorted(positions)
    assert sorted(set(current) - set(previous)) == sorted(DOCKER_PATTERNS)
    group_start = current.index("**/*.[wW][eE][bB][pP]")
    assert current[group_start + 1 : group_start + 10] == DOCKER_PATTERNS


def test_extra_caddy_dockerignore_still_excludes_everything() -> None:
    """Top note, section 4.10: the Caddy ``.dockerignore`` (``*`` and ``!infra/Caddyfile``)
    already excludes every extension and does not receive the 9 lines."""
    lines = [
        line.strip()
        for line in _read(CADDY_DOCKERIGNORE).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines == ["*", "!infra/Caddyfile"], lines


# ============================================================================================
# CA-17: documentation (section 4.11)
# ============================================================================================


def _list_item(text: str, prefix: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith(prefix):
            indent = len(line) - len(line.lstrip())
            item = [line]
            for nxt in lines[index + 1 :]:
                if not nxt.strip() or nxt.lstrip().startswith("#"):
                    break
                nxt_indent = len(nxt) - len(nxt.lstrip())
                if nxt_indent <= indent and re.match(r"\s*(-|\d+\.)\s", nxt):
                    break
                item.append(nxt)
            return "\n".join(item)
    raise AssertionError(f"no item starting with {prefix!r}")


def _section(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    start = level = None
    for index, line in enumerate(lines):
        m = re.match(r"(#{1,6})\s+(.*)", line)
        if not m:
            continue
        title = line.strip()
        if start is None and (title == heading or title.startswith(heading + " ")):
            start, level = index, len(m.group(1))
        elif start is not None and len(m.group(1)) <= (level or 0):
            return "\n".join(lines[start:index])
    assert start is not None, heading
    return "\n".join(lines[start:])


def test_ca17_env_example_warns_against_zero_or_minus_one() -> None:
    lines = _read(ENV_EXAMPLE).splitlines()
    index = lines.index("API_PIDS_LIMIT=256")
    above = "\n".join(lines[max(0, index - 3) : index])
    assert "Inteiro positivo: 0 ou -1 removem o limite" in above, above


def test_ca17_deployment_plan() -> None:
    text = _read(PLAN)
    item = _list_item(text, "- **Se um contêiner bater no")
    assert "`0` ou `-1`" in item, item
    update = _section(text, "### Atualização")
    step3 = _list_item(update, "3.")
    assert "Endurecimento dos contêineres" in step3, step3
    assert "Read-only file system" in step3, step3
    assert "handle_errors" in text
    assert STATICRESP_URL in text


def test_extra_env_example_exact_line_of_section_4_11() -> None:
    lines = _read(ENV_EXAMPLE).splitlines()
    index = lines.index("API_PIDS_LIMIT=256")
    expected = "# Inteiro positivo: 0 ou -1 removem o limite (sem aviso do compose); nunca use."
    assert expected in lines[max(0, index - 3) : index]


def test_extra_plan_risk_text_follows_the_top_note() -> None:
    """Top note, section 4.9: the risk cites the Coolify proxy instead of the 308 of port 80."""
    text = _read(PLAN)
    assert "o redirecionamento HTTP → HTTPS e os erros gerados pelo próprio proxy do Coolify" in (
        " ".join(text.split())
    )


# ============================================================================================
# Exploratory (docker): more requests to the Caddy without upstreams
# ============================================================================================


@pytest.mark.docker
def test_extra_error_responses_never_duplicate_headers_nor_leak(caddy_alone: str) -> None:
    for path, host in (
        ("/api/v1/inspections?limit=1", TEST_HOST),
        ("/_stcore/health", TEST_HOST),
        ("/qualquer/coisa", "outro.example.org"),
        ("/api/v1/health", "127.0.0.1"),
    ):
        raw = get(caddy_alone, path, host=host)
        headers = assert_error_response(raw)
        names = [k for k, _ in headers]
        assert len(names) == len(set(names)), headers
        lowered = raw.lower()
        for leak in (b"dial tcp", b"lookup", b"api:8000", b"dashboard:8501", b"caddy"):
            assert leak not in lowered, (path, leak)
    head = get(caddy_alone, "/api/v1/health", method="HEAD")
    code, headers, _ = parse(head)
    assert code == 502
    assert "server" not in [k for k, _ in headers]
    assert _inspect(caddy_alone, "{{.State.Status}}") == "running"


@pytest.mark.docker
def test_extra_many_errors_in_a_row_keep_caddy_running(caddy_alone: str) -> None:
    for _ in range(15):
        assert parse(get(caddy_alone, "/"))[0] == 502
    assert _inspect(caddy_alone, "{{.State.Status}}") == "running"
    logs = _docker("logs", caddy_alone)
    assert "panic" not in (logs.stdout + logs.stderr).lower()


@pytest.mark.docker
def test_extra_caddyfile_is_already_formatted(caddy_image: str) -> None:
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", caddy_image]
        + ["caddy", "fmt", "/etc/caddy/Caddyfile"],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == CADDYFILE.read_bytes()


@pytest.mark.docker
@pytest.mark.parametrize(("value", "expected"), [("0", None), ("-1", -1), ("256", 256)])
def test_extra_pids_limit_zero_or_minus_one_resolve_without_warning(
    tmp_path: Path, value: str, expected: int | None
) -> None:
    """SEC-32-03: with ``pids_limit: "${P:-256}"``, ``0`` drops the limit and ``-1`` keeps
    "unlimited", both without a warning; this is what the notes of section 4.11 warn about."""
    compose = tmp_path / "compose.yaml"
    compose.write_text(
        'services:\n  x:\n    image: busybox\n    pids_limit: "${P:-256}"\n', encoding="utf-8"
    )
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose), "config", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "P": value, "HOME": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    assert "warn" not in result.stderr.lower(), result.stderr
    svc = json.loads(result.stdout)["services"]["x"]
    assert svc.get("pids_limit") == expected, svc


@pytest.mark.docker
def test_extra_control_without_handle_errors_the_502_keeps_server(
    caddy_image: str, containers: Containers, tmp_path: Path
) -> None:
    """Negative control of CA-14 (and of this probe): the same Caddyfile without the
    ``handle_errors`` block answers the 502 with ``Server: Caddy`` and none of the headers."""
    raw = _read(CADDYFILE)
    text = raw.splitlines(keepends=True)
    start = next(i for i, line in enumerate(text) if line.strip() == "handle_errors {")
    indent = text[start][: len(text[start]) - len(text[start].lstrip())]
    end = next(i for i in range(start + 1, len(text)) if text[i] == indent + "}\n")
    copy = tmp_path / "Caddyfile"
    copy.write_text("".join(text[:start] + text[end + 1 :]), encoding="utf-8")
    copy.chmod(0o444)
    assert "handle_errors" not in strip_comments(_read(copy))
    name = containers.run(caddy_image, *HARDENED, "-v", f"{copy}:/etc/caddy/Caddyfile:ro")
    _wait_until_listening(name)
    code, headers, _ = parse(get(name, "/api/v1/health"))
    assert code == 502
    names = [k for k, _ in headers]
    assert "server" in names, headers
    assert "strict-transport-security" not in names, headers
