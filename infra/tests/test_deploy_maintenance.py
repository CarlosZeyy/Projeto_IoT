"""Author tests of SPEC-038, Part B (security-devops): deploy maintenance.

* Section 4.9 (SEC-32-01): ``handle_errors`` in the ``:80`` site of ``infra/Caddyfile`` (ADR-023,
  SPEC-039), with the 6 header lines of the site and an empty ``respond`` that keeps the status of
  the original error.
* Section 4.10 (SEC-32-02): 9 photo and video extensions in ``.gitignore`` and in the build
  contexts of the api and the dashboard.
* Section 4.11 (SEC-32-03, RV-03 of SPEC-032): ``pids_limit`` of ``0``/``-1`` and the update
  procedure, only in documentation.

Static checks read the files as text. The tests marked ``docker`` run only with
``PARTQC_DOCKER_TESTS=1``; they build the Caddy image from a temporary copy of the tracked tree
(``build_image``), run every container with ``--network none`` and remove it at the end. The
fictitious host is ``partqc.example.org``.
"""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"
CADDYFILE = INFRA / "Caddyfile"
GITIGNORE = ROOT / ".gitignore"
ENV_EXAMPLE = ROOT / ".env.example"
PLAN = ROOT / "docs" / "deployment-plan.md"
DOCKERIGNORES = {
    name: INFRA / "docker" / f"{name}.Dockerfile.dockerignore" for name in ("api", "dashboard")
}
STATICRESP_URL = "https://github.com/caddyserver/caddy/blob/master/modules/caddyhttp/staticresp.go"

HEADER_LINES = [
    'Strict-Transport-Security "max-age=31536000"',
    'X-Content-Type-Options "nosniff"',
    'Referrer-Policy "no-referrer"',
    "Content-Security-Policy \"frame-ancestors 'self'\"",
    "-Server",
    "-Via",
]
HEADERS_SET = {
    "Strict-Transport-Security": ["max-age=31536000"],
    "X-Content-Type-Options": ["nosniff"],
    "Referrer-Policy": ["no-referrer"],
    "Content-Security-Policy": ["frame-ancestors 'self'"],
}
# The code lines (no comments, no blank lines) of infra/Caddyfile at the start of round r1: the
# site header block and the two handle blocks do not change (section 4.9, third item).
SITE_CODE_BEFORE = [
    ":80 {",
    "\theader {",
    *(f"\t\t{line}" for line in HEADER_LINES),
    "\t}",
    "\thandle /api/* {",
    "\t\treverse_proxy api:8000",
    "\t}",
    "\thandle {",
    "\t\treverse_proxy dashboard:8501",
    "\t}",
    "}",
]
EXTENSIONS = [
    "[hH][eE][iI][fF]",
    "[jJ][fF][iI][fF]",
    "[jJ][pP][eE]",
    "[tT][iI][fF]",
    "[tT][iI][fF][fF]",
    "[dD][nN][gG]",
    "[aA][vV][iI][fF]",
    "[mM][oO][vV]",
    "[mM][pP]4",
]
GITIGNORE_NEW = [f"*.{ext}" for ext in EXTENSIONS]
DOCKERIGNORE_NEW = [f"**/*.{ext}" for ext in EXTENSIONS]
# Every non-empty line of .gitignore at the start of round r1 (CA-15 copies it literally too).
GITIGNORE_BEFORE = [
    "# --- Python / uv ---",
    "__pycache__/",
    "*.py[cod]",
    ".venv/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".coverage",
    "htmlcov/",
    "*.egg-info/",
    "dist/",
    "build/",
    "# --- Segredos (R-03) ---",
    "# O Git no Linux diferencia maiúsculas nos padrões (core.ignorecase=false): cada padrão"
    " literal",
    "# tem ao lado uma variante com classes de caracteres (SPEC-032 §4.2, RV-04 da SPEC-015).",
    ".env",
    ".env.*",
    ".[eE][nN][vV]",
    ".[eE][nN][vV].*",
    "!.env.example",
    ".streamlit/secrets.toml",
    "*.pem",
    "*.key",
    "*.[pP][eE][mM]",
    "*.[kK][eE][yY]",
    "# --- Dados e imagens (R-02, R-14) ---",
    "ml/data/",
    "edge/data/",
    "data/",
    "*.jpg",
    "*.jpeg",
    "*.png",
    "*.[jJ][pP][gG]",
    "*.[jJ][pP][eE][gG]",
    "*.[pP][nN][gG]",
    "*.[hH][eE][iI][cC]",
    "*.[wW][eE][bB][pP]",
    "!docs/**/*.png",
    "!ml/reports/**/*.png",
    "!docs/**/*.[pP][nN][gG]",
    "!ml/reports/**/*.[pP][nN][gG]",
    "# --- Modelos (pesos vão em GitHub Releases) ---",
    "ml/models/**/*.onnx",
    "ml/models/**/*.pt",
    "ml/models/**/*.pth",
    "ml/models/**/*.[oO][nN][nN][xX]",
    "ml/models/**/*.[pP][tT]",
    "ml/models/**/*.[pP][tT][hH]",
    "ml/checkpoints/",
    "# --- Borda ---",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.[sS][qQ][lL][iI][tT][eE]",
    "*.[sS][qQ][lL][iI][tT][eE]3",
    "*.[dD][bB]",
    "# --- Notebooks / IDE / SO ---",
    ".ipynb_checkpoints/",
    ".vscode/",
    ".idea/",
    ".DS_Store",
    "# --- Claude Code (local) ---",
    ".claude/settings.local.json",
    ".claude/worktrees/",
]
# The rules (no comments) of both .dockerignore files at the start of round r1 (identical).
DOCKERIGNORE_BEFORE = [
    ".git",
    ".github",
    ".claude/",
    "notas-locais/",
    ".vscode/",
    ".idea/",
    "**/.env*",
    "**/.[eE][nN][vV]*",
    "!.env.example",
    ".streamlit/secrets.toml",
    "**/secrets.toml",
    "**/*.pem",
    "**/*.key",
    "**/*.[pP][eE][mM]",
    "**/*.[kK][eE][yY]",
    "ml/data/",
    "edge/data/",
    "data/",
    "**/*.jpg",
    "**/*.jpeg",
    "**/*.png",
    "**/*.heic",
    "**/*.webp",
    "**/*.[jJ][pP][gG]",
    "**/*.[jJ][pP][eE][gG]",
    "**/*.[pP][nN][gG]",
    "**/*.[hH][eE][iI][cC]",
    "**/*.[wW][eE][bB][pP]",
    "!ml/reports/**/*.png",
    "!ml/reports/**/*.[pP][nN][gG]",
    "ml/models/**/*.onnx",
    "ml/models/**/*.pt",
    "ml/models/**/*.pth",
    "ml/checkpoints/",
    "**/*.onnx",
    "**/*.pt",
    "**/*.pth",
    "**/*.npz",
    "**/*.[oO][nN][nN][xX]",
    "**/*.[pP][tT]",
    "**/*.[pP][tT][hH]",
    "**/*.[nN][pP][zZ]",
    "ml/notebooks/",
    "**/*.sqlite",
    "**/*.sqlite3",
    "**/*.db",
    "**/*.[sS][qQ][lL][iI][tT][eE]",
    "**/*.[sS][qQ][lL][iI][tT][eE]3",
    "**/*.[dD][bB]",
    "**/.venv",
    "**/__pycache__",
    "**/*.py[cod]",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".coverage",
    "htmlcov/",
    "**/*.egg-info",
    "docs/",
    "reviews/",
    "**/tests",
    "infra/",
]


def _code(path: Path) -> list[str]:
    """Non-empty, non-comment lines, without the trailing newline."""
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _block(code: list[str], opening: str) -> list[str]:
    """The lines inside the block that opens with the line ``opening`` (``caddy fmt`` tabs)."""
    start = code.index(opening)
    indent = opening[: len(opening) - len(opening.lstrip("\t"))]
    end = code.index(f"{indent}}}", start)
    return code[start + 1 : end]


def _errors_block() -> list[str]:
    return _block(_code(CADDYFILE), "\thandle_errors {")


# ============================================================ static: Caddyfile (section 4.9)


def test_one_handle_errors_without_status_codes_inside_the_site() -> None:
    code = _code(CADDYFILE)
    found = [line for line in code if re.match(r"\s*handle_errors\b", line)]
    assert found == ["\thandle_errors {"]  # one block, no status codes, one level inside :80
    assert code[0] == ":80 {" and code[-1] == "}"
    start = code.index("\thandle_errors {")
    assert 0 < start < len(code) - 1
    # The only site is :80 (SPEC-039 section 4.2): handle_errors cannot be in another site.
    assert [line for line in code if not line.startswith("\t") and line.endswith("{")] == [":80 {"]


def test_handle_errors_has_the_six_header_lines() -> None:
    block = _errors_block()
    assert [line.strip() for line in _block(block, "\t\theader {")] == HEADER_LINES


def test_handle_errors_responds_with_an_empty_body_and_no_status() -> None:
    block = _errors_block()
    header = _block(block, "\t\theader {")
    rest = [line for line in block if line not in header and line not in ("\t\theader {", "\t\t}")]
    # One argument that is not a 3-digit number is the body; no status -> the error's status.
    assert rest == ['\t\trespond ""']


@pytest.mark.parametrize("token", ["reverse_proxy", "file_server", "templates", "rewrite"])
def test_handle_errors_never_forwards_or_renders(token: str) -> None:
    assert not [line for line in _errors_block() if re.search(rf"\b{token}\b", line)]


def test_handle_errors_uses_no_error_placeholder_but_the_status_code() -> None:
    text = "\n".join(_errors_block())
    assert not re.search(r"\{err\.(?!status_code\})", text)


def test_the_rest_of_the_site_does_not_change() -> None:
    code = _code(CADDYFILE)
    start = code.index("\thandle_errors {")
    end = code.index("\t}", start)  # the inner header block closes with two tabs
    assert code[:start] + code[end + 1 :] == SITE_CODE_BEFORE


def test_site_header_block_keeps_the_six_lines() -> None:
    assert [line.strip() for line in _block(_code(CADDYFILE), "\theader {")] == HEADER_LINES


def test_caddyfile_comments_explain_handle_errors_without_a_domain() -> None:
    raw = CADDYFILE.read_text(encoding="utf-8")
    comments = "\n".join(line for line in raw.splitlines() if line.startswith("#"))
    for fragment in ("handle_errors", "SPEC-038", "SEC-32-01", "502", "corpo vazio"):
        assert fragment in comments, fragment
    assert "://" not in raw  # no URL, not even in a comment (the sources are in the plan)
    for n, line in enumerate(raw.splitlines(), 1):
        assert line == line.rstrip(), n
        assert " " not in line[: len(line) - len(line.lstrip())], n


ENV_PLACEHOLDER = re.compile(r"\{env\.|\{\$")


def _env_placeholders(path: Path) -> list[str]:
    """Code lines (comments out, as in CA-12) with ``{env.`` or ``{$`` (SEC-39-06)."""
    return [line for line in _code(path) if ENV_PLACEHOLDER.search(line)]


def test_caddyfile_has_no_environment_placeholder() -> None:
    """Section 4.9 (SEC-39-06, R-03): the Caddy container has READ_API_KEY and PUBLIC_HOST in
    its environment (ADR-023, amendment 1), so no ``{env.*}`` nor ``{$...}`` in the whole file."""
    assert _env_placeholders(CADDYFILE) == []


@pytest.mark.parametrize(
    "line",
    [
        "\t\trespond {env.READ_API_KEY}",
        '\t\trespond "{env.READ_API_KEY}" 502',
        "\t\trespond {$READ_API_KEY}",
        "\t\theader X-Key {$READ_API_KEY:padrao}",
        "\t\theader X-Key {env.PUBLIC_HOST}",
    ],
)
def test_control_an_environment_placeholder_is_detected(tmp_path: Path, line: str) -> None:
    """Negative control on a temporary copy (the real file is never written): the same
    Caddyfile with a placeholder inside handle_errors is caught; in a comment it is not code."""
    text = CADDYFILE.read_text(encoding="utf-8")
    assert '\t\trespond ""\n' in text
    leaking = tmp_path / "Caddyfile"
    leaking.write_text(text.replace('\t\trespond ""\n', f"{line}\n"), encoding="utf-8")
    assert _env_placeholders(leaking) == [line]
    commented = tmp_path / "Caddyfile.comment"
    commented.write_text(f"# {line.strip()}\n" + text, encoding="utf-8")
    assert _env_placeholders(commented) == []


# ============================================================ static: .gitignore (section 4.10)

IGNORED = [
    "entrada/IMG_0001.HEIF",
    "entrada/foto.heif",
    "fotos/a.JFIF",
    "fotos/a.jfif",
    "fotos/a.JPE",
    "fotos/a.jpe",
    "scan/a.TIF",
    "scan/a.tiff",
    "scan/a.Tiff",
    "scan/a.tIf",
    "raw/IMG_0001.DNG",
    "raw/x.dng",
    "fotos/a.avif",
    "fotos/A.AVIF",
    "entrada/IMG_0001.MOV",
    "entrada/v.mov",
    "entrada/v.MP4",
    "entrada/v.mp4",
    "docs/img/foto.tif",
    "docs/img/foto.HEIF",
    "ml/reports/v1/curva.tiff",
    "ml/reports/v1/demo.mp4",
    "a/b/c/d/IMG_0002.MoV",
]
NOT_IGNORED = [
    ".env.example",
    "docs/img/Arquitetura.PNG",
    "ml/reports/v1/grade_confusion.png",
    "edge/src/qc_edge/importer.py",
    "notas.movie",
    "video.mp4.txt",
    "README.md",
    "ml/tests/fixtures/tiny_model/model.onnx",
    "scan/a.tiffany",
    "fotos/a.jpeg2",
    "docs/heif.md",
]


def _check_ignore(paths: list[str]) -> set[str]:
    """The paths that the repository .gitignore ignores, case-sensitively, with no global file."""
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.excludesFile=/dev/null",
            "-c",
            "core.ignorecase=false",
            "check-ignore",
            "--no-index",
            "--stdin",
        ],
        input="\n".join(paths) + "\n",
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
        timeout=60,
    )
    assert result.returncode in (0, 1), result.stderr
    return set(result.stdout.splitlines())


def test_gitignore_ignores_the_new_photo_and_video_formats() -> None:
    assert _check_ignore(IGNORED) == set(IGNORED)


def test_gitignore_keeps_what_must_stay_tracked() -> None:
    assert _check_ignore(NOT_IGNORED) == set()


def test_gitignore_new_lines_sit_before_the_png_exceptions() -> None:
    lines = [line for line in GITIGNORE.read_text(encoding="utf-8").splitlines() if line.strip()]
    start = lines.index(GITIGNORE_NEW[0])
    assert lines[start : start + len(GITIGNORE_NEW)] == GITIGNORE_NEW
    assert lines[start - 1] == "*.[wW][eE][bB][pP]"
    assert lines[start + len(GITIGNORE_NEW)] == "!docs/**/*.png"
    # Only the character-class form: the literal form would be redundant.
    for literal in ("*.heif", "*.jfif", "*.jpe", "*.tif", "*.tiff", "*.dng", "*.avif", "*.mov"):
        assert literal not in lines
    assert "*.mp4" not in lines


def test_gitignore_keeps_every_line_of_the_start_of_the_round() -> None:
    lines = [line for line in GITIGNORE.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [line for line in lines if line not in GITIGNORE_NEW] == GITIGNORE_BEFORE


def test_no_tracked_file_is_ignored() -> None:
    result = subprocess.run(
        ["git", "-c", "core.excludesFile=/dev/null", "ls-files", "-ci", "--exclude-standard"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


# ============================================================ static: .dockerignore (section 4.10)


@pytest.mark.parametrize("component", sorted(DOCKERIGNORES))
def test_dockerignore_has_the_new_formats_before_the_exceptions(component: str) -> None:
    rules = _code(DOCKERIGNORES[component])
    start = rules.index(DOCKERIGNORE_NEW[0])
    assert rules[start : start + len(DOCKERIGNORE_NEW)] == DOCKERIGNORE_NEW
    assert rules[start - 1] == "**/*.[wW][eE][bB][pP]"
    assert rules[start + len(DOCKERIGNORE_NEW)] == "!ml/reports/**/*.png"
    for rule in DOCKERIGNORE_NEW:
        assert rules.index(rule) < rules.index("!ml/reports/**/*.png")
        assert rules.count(rule) == 1


@pytest.mark.parametrize("component", sorted(DOCKERIGNORES))
def test_dockerignore_keeps_every_rule_of_the_start_of_the_round(component: str) -> None:
    rules = _code(DOCKERIGNORES[component])
    assert [rule for rule in rules if rule not in DOCKERIGNORE_NEW] == DOCKERIGNORE_BEFORE


def test_caddy_dockerignore_is_unchanged() -> None:
    """The Caddy context already excludes everything but the Caddyfile (SPEC-038 top note)."""
    assert _code(INFRA / "docker" / "caddy.Dockerfile.dockerignore") == ["*", "!infra/Caddyfile"]


# ============================================================ static: docs (sections 4.9, 4.11)


def test_env_example_warns_against_zero_or_minus_one() -> None:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    i = lines.index("API_PIDS_LIMIT=256")
    assert lines[i - 1] == (
        "# Inteiro positivo: 0 ou -1 removem o limite (sem aviso do compose); nunca use."
    )
    assert lines.count("API_PIDS_LIMIT=256") == 1


def _plan_lines() -> list[str]:
    return PLAN.read_text(encoding="utf-8").splitlines()


def test_plan_pids_limit_item_forbids_zero_and_minus_one() -> None:
    (item,) = [line for line in _plan_lines() if line.startswith("- **Se um contêiner bater no")]
    assert "`0` ou `-1`" in item and "nunca" in item


def test_plan_update_step_3_points_to_the_hardening_diagnosis() -> None:
    lines = _plan_lines()
    start = next(i for i, line in enumerate(lines) if line.startswith("### Atualização"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("#"))
    (step,) = [line for line in lines[start:end] if line.startswith("3. ")]
    for fragment in (
        "Endurecimento dos contêineres",
        "Read-only file system",
        "can't start new thread",
        "§2",
    ):
        assert fragment in step, fragment


def test_plan_risk_9_describes_handle_errors_and_the_coolify_proxy() -> None:
    (risk,) = [line for line in _plan_lines() if line.startswith("9. **Respostas que não passam")]
    for fragment in (
        "handle_errors",
        "SPEC-038",
        "corpo vazio",
        "sem `Server`",
        STATICRESP_URL,
        "redirecionamento HTTP → HTTPS",
        "proxy do Coolify",
        "contêiner do Caddy parado",
    ):
        assert fragment in risk, fragment
    # The old wording of the plain-HTTP Caddy server is gone (ADR-023: port 80 is Coolify's).
    assert "308" not in risk and "servidor automático" not in risk


def test_plan_lists_the_caddy_error_sources_with_the_date() -> None:
    (row,) = [line for line in _plan_lines() if line.startswith("| Caddy: respostas de erro")]
    assert "caddyserver.com/docs/caddyfile/directives/handle_errors" in row
    assert STATICRESP_URL in row
    assert re.search(r"\| 20\d\d-\d\d-\d\d \|$", row)


def test_plan_manual_ca_18_uses_the_coolify_container_names() -> None:
    lines = _plan_lines()
    start = lines.index("### CA manual da SPEC-038 (respostas de erro do Caddy)")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    text = "\n".join(lines[start:end])
    for fragment in (
        "label=com.docker.compose.project=<uuid>",
        "docker stop <contêiner da api>",
        "docker start <contêiner da api>",
        "curl -sI https://<subdominio>/api/v1/health",
        "`502`",
        "60 s",
        "<subdominio>",
        "| SPEC-038 CA-18 |",
    ):
        assert fragment in text, fragment
    assert "compose -f infra/compose.yaml stop" not in text
    for line in lines[start:end]:
        if "coolify-proxy" in line:
            assert "Nunca" in line or "nunca" in line, line


# ============================================================ docker (sections 4.9 and 4.10)

docker = pytest.mark.docker
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
    "--pids-limit",
    "256",
]
STARTUP_TIMEOUT_S = 30


def _support():
    return sys.modules["partqc_docker_support"]


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _walk(node: object) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


@pytest.fixture(scope="module")
def caddy_image(build_image) -> str:
    return build_image("infra/docker/caddy.Dockerfile")


@docker
def test_caddy_adapt_puts_the_headers_in_the_error_routes(caddy_image: str) -> None:
    cmd = _support().docker_run_args(
        caddy_image,
        "adapt",
        "--config",
        "/etc/caddy/Caddyfile",
        "--adapter",
        "caddyfile",
        entrypoint="caddy",
    )
    result = _run(cmd)
    assert result.returncode == 0, result.stderr
    assert "formatted" not in result.stderr.lower()
    (server,) = json.loads(result.stdout)["apps"]["http"]["servers"].values()
    errors = list(_walk(server["errors"]["routes"]))
    (headers,) = [n["response"] for n in errors if n.get("handler") == "headers"]
    assert sorted(headers["delete"]) == ["Server", "Via"]
    assert headers["set"] == HEADERS_SET
    assert headers["deferred"] is True
    (static,) = [n for n in errors if n.get("handler") == "static_response"]
    assert static == {"handler": "static_response"}  # no status (the error's) and no body
    handlers = {n["handler"] for n in errors if "handler" in n}
    assert handlers == {"subroute", "headers", "static_response"}
    # The site routes keep one deferred headers handler and the two proxies (SPEC-032 CA-05).
    routes = list(_walk(server["routes"]))
    (site,) = [n["response"] for n in routes if n.get("handler") == "headers"]
    assert site["deferred"] is True and site["set"] == HEADERS_SET
    assert sorted(site["delete"]) == ["Server", "Via"]
    assert len([n for n in routes if n.get("handler") == "reverse_proxy"]) == 2


PROBE = (
    "for p in /api/v1/health /; do "
    "(printf 'GET %s HTTP/1.1\\r\\nHost: partqc.example.org\\r\\n\\r\\n' \"$p\"; sleep 2) "
    "| nc -w 5 127.0.0.1 80; echo; echo '=====PARTQC====='; done"
)


def _start_caddy(image: str, *mount: str) -> str:
    container = f"partqc-test-caddy-errors-{secrets.token_hex(4)}"
    cmd = ["docker", "run", "-d", "--name", container, "--network", "none", *CADDY_RUN_ARGS]
    result = _run([*cmd, *mount, image])
    assert result.returncode == 0, result.stderr
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        probe = _run(["docker", "exec", container, "nc", "-z", "127.0.0.1", "80"], timeout=30)
        if probe.returncode == 0:
            break
        time.sleep(0.5)
    return container


def _responses(container: str) -> list[tuple[str, dict[str, str], bytes]]:
    """Status line, headers and body of the two raw HTTP/1.1 answers of ``PROBE``."""
    # Bytes, not text: the text mode of subprocess would turn the CRLF of HTTP into LF.
    result = subprocess.run(
        ["docker", "exec", container, "sh", "-c", PROBE],
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    out = []
    for raw in result.stdout.split(b"\n=====PARTQC=====\n")[:2]:
        head, _, body = raw.partition(b"\r\n\r\n")
        status, *fields = head.lstrip(b"\n").decode("latin-1").split("\r\n")
        headers: dict[str, str] = {}
        for field in fields:
            name, _, value = field.partition(":")
            assert name.lower() not in headers, f"duplicated header {name}"
            headers[name.lower()] = value.strip()
        # ``echo`` after ``nc`` adds one LF to the output, never part of the HTTP body.
        out.append((status, headers, body.removesuffix(b"\n")))
    assert len(out) == 2, result.stdout
    return out


def _remove(container: str) -> None:
    _run(["docker", "rm", "-f", "-v", container], timeout=60)


@docker
def test_caddy_error_response_has_the_headers_and_an_empty_body(caddy_image: str) -> None:
    """CA-14 setting: the real Caddyfile, no api and no dashboard, so Caddy itself answers 502."""
    container = _start_caddy(caddy_image)
    try:
        for status, headers, body in _responses(container):
            assert status == "HTTP/1.1 502 Bad Gateway"
            assert headers["strict-transport-security"] == "max-age=31536000"
            assert headers["x-content-type-options"] == "nosniff"
            assert headers["referrer-policy"] == "no-referrer"
            assert headers["content-security-policy"] == "frame-ancestors 'self'"
            assert "server" not in headers and "via" not in headers
            assert headers["content-length"] == "0" and body == b""
        state = _run(["docker", "inspect", "-f", "{{.State.Status}}", container]).stdout
        assert state.strip() == "running"
        # The internal error (the DNS failure of the upstream) is logged, never sent.
        logs = _run(["docker", "logs", container], timeout=60)
        assert "read-only file system" not in (logs.stdout + logs.stderr).lower()
    finally:
        _remove(container)


@docker
def test_control_without_handle_errors_the_502_leaks_server(
    caddy_image: str, tmp_path: Path
) -> None:
    """Control: the same Caddyfile without the handle_errors block answers the 502 with
    ``Server: Caddy`` and none of the 4 headers, so the previous test detects a regression."""
    text = CADDYFILE.read_text(encoding="utf-8")
    start = text.index("\n\thandle_errors {")
    end = text.index("\n\t}\n", start) + len("\n\t}")
    stripped = tmp_path / "Caddyfile"
    stripped.write_text(text[:start] + text[end:], encoding="utf-8")
    stripped.chmod(0o444)
    container = _start_caddy(caddy_image, "-v", f"{stripped}:/etc/caddy/Caddyfile:ro")
    try:
        for status, headers, _body in _responses(container):
            assert status == "HTTP/1.1 502 Bad Gateway"
            assert headers.get("server") == "Caddy"
            assert "strict-transport-security" not in headers
            assert "referrer-policy" not in headers
    finally:
        _remove(container)
