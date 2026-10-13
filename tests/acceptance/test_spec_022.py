"""Acceptance tests for SPEC-022 (setup maintenance: hook, passwordless CI DB, architect commits).

Written by the tester from the SPEC acceptance criteria (CA-01 to CA-16).
CA-17 (CI on the PR) and CA-18 (diff of .claude/) are manual and recorded in the test report.

Forbidden sequences (old URL with password, password variable) are built by concatenation at
runtime, so this file never contains them (SPEC-022 §4.2).
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "guard_paths.py"
SPEC = ROOT / "docs" / "specs" / "SPEC-022-manutencao-setup.md"

# The SPEC runs the hook as `python3 .claude/hooks/guard_paths.py`.
PYTHON3 = shutil.which("python3") or sys.executable

OLD_URL_FRAGMENT = "postgres" + ":" + "postgres" + "@"
PASSWORD_VAR = "POSTGRES_" + "PASSWORD"

NEW_LOCAL_URL = "postgresql://postgres@localhost:55432/partqc_test"
NEW_CI_URL = "postgresql://postgres@localhost:5432/partqc_test"

BOTH = "tool_input has both file_path and notebook_path"
NO_TOOL_NAME = "event has no tool_name string"

# Texts required literally by the SPEC (§4.3 and §4.4). test_texts_match_spec_quotes checks that
# they are exactly the quotes in the SPEC, so a typo here cannot hide a wrong implementation.
ARCHITECT_COMMITS = (
    "Você não tem shell (`Bash`), então não faz commits. Quem commita os seus arquivos é o "
    "**orquestrador** (sessão principal), com os trailers `Refs: SPEC-XXX` e `Agent: architect`, "
    "cada um em linha própria no fim da mensagem. Esse commit contém só os arquivos que você "
    "escreveu, sem misturar arquivos de outro papel. Sem esse trailer, o reviewer não consegue "
    "verificar a separação de papéis (R-07)."
)
REVIEWS_ARCHITECT = (
    "**Commits do architect:** o `architect` não tem shell, então quem commita os arquivos dele é "
    "o orquestrador, com `Agent: architect` e `Refs: SPEC-XXX`. Esse commit é esperado e não é "
    "desvio de papel, desde que contenha só arquivos de `docs/` (exceto `docs/rules.md` sem "
    "pedido explícito do humano) e nenhum arquivo de outro papel. As mudanças de status feitas "
    "pelo próprio orquestrador vão em commits separados, com `Agent: orchestrator`."
)
WORKSPACE_TRUST = (
    "**Workspace trust:** os hooks do frontmatter dos agentes de projeto só rodam se a pasta tiver "
    "a confiança (workspace trust) aceita no Claude Code. Numa máquina ou num clone novo, rode "
    "`claude` uma vez na pasta e aceite o diálogo de confiança; uma sessão `claude -p` não conta "
    "como aceite. Sem isso, o hook não roda e a escrita fora do papel passa (constatado no CA-23 "
    "da SPEC-001, em 2026-10-12)."
)

# Variables listed in CA-20 of SPEC-001 (pre-existing in .env.example).
PRE_EXISTING_ENV_VARS = [
    "EDGE_HOST",
    "EDGE_PORT",
    "EDGE_SESSION_TOKEN",
    "DEVICE_ID",
    "DEVICE_API_KEY",
    "CLOUD_API_URL",
    "MODEL_DIR",
    "EDGE_DATA_DIR",
    "DATASET_DIR",
    "OUTBOX_PATH",
    "TYPE_THRESHOLD",
    "UNUSABLE_THRESHOLD",
    "GRADE_REVIEW_THRESHOLD",
    "DATABASE_URL",
    "READ_API_KEY",
    "API_BASE_URL",
    "SIM_DEVICE_ID",
    "SIM_DEVICE_API_KEY",
    "DASHBOARD_URL",
    "QC_REAL_MODEL_DIR",
]
SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


# --------------------------------------------------------------------------- helpers


def _clean_env(**overrides: str | None) -> dict[str, str]:
    env = dict(os.environ)
    for key in ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST", "PYTEST_PLUGINS"):
        env.pop(key, None)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def _hook(event: object, role: str | None, *, python: str = PYTHON3) -> subprocess.CompletedProcess:
    """Run the hook as the SPEC says: event JSON on stdin, `--role <role>`.

    The process cwd is the hooks folder (not the root), so only absolute paths or the event's
    own `cwd` can resolve to the project.
    """
    stdin = event if isinstance(event, str) else json.dumps(event)
    args = [python, str(HOOK)]
    if role is not None:
        args += ["--role", role]
    return subprocess.run(
        args,
        input=stdin.encode("utf-8"),
        capture_output=True,
        timeout=30,
        cwd=HOOK.parent,
    )


def _assert_blocked(result: subprocess.CompletedProcess, message: str) -> None:
    stderr = result.stderr.decode("utf-8")
    assert result.returncode == 2, (result.returncode, stderr)
    assert f"guard_paths: blocked: {message}" in stderr, stderr


def _abs(rel: str) -> str:
    return f"{ROOT}/{rel}"


def _frontmatter_and_body(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end]), text[end + 5 :]


def _headings(lines: list[str]) -> list[int]:
    """Indexes of Markdown heading lines, ignoring lines inside fenced code blocks."""
    out: list[int] = []
    fenced = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced and re.match(r"^#{1,6} ", line):
            out.append(i)
    return out


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _run_pytest(args: list[str], **env: str | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=ROOT,
        env=_clean_env(**env),
        capture_output=True,
        text=True,
        timeout=900,
    )


# --------------------------------------------------------------------------- oracle check


def test_texts_match_spec_quotes() -> None:
    """The literal texts above are exactly the blockquotes of SPEC-022 §4.3/§4.4."""
    quotes = [
        line.strip()[2:]
        for line in SPEC.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("> ")
    ]
    for text in (ARCHITECT_COMMITS, REVIEWS_ARCHITECT, WORKSPACE_TRUST):
        assert text in quotes, text


# --------------------------------------------------------------------------- CA-01


def test_ca01_notebook_edit_with_allowed_file_path_is_denied() -> None:
    event = {
        "tool_name": "NotebookEdit",
        "tool_input": {
            "notebook_path": _abs("api/src/evil.ipynb"),
            "file_path": _abs("ml/x.ipynb"),
        },
    }
    _assert_blocked(_hook(event, "ml-engineer"), BOTH)


# --------------------------------------------------------------------------- CA-02


_NB_A = _abs("ml/a.ipynb")


@pytest.mark.parametrize(
    ("role", "tool", "tool_input"),
    [
        ("ml-engineer", "NotebookEdit", {"notebook_path": _NB_A, "file_path": "   "}),
        ("ml-engineer", "NotebookEdit", {"notebook_path": _NB_A, "file_path": 42}),
        ("ml-engineer", "NotebookEdit", {"notebook_path": _NB_A, "file_path": None}),
        (
            "ml-engineer",
            "Write",
            {"file_path": _abs("ml/a.py"), "notebook_path": _abs("api/b.ipynb")},
        ),
        (
            "developer",
            "Edit",
            {"file_path": _abs("api/src/qc_api/main.py"), "notebook_path": ""},
        ),
    ],
    ids=["nb-fp-spaces", "nb-fp-42", "nb-fp-null", "write-with-nb", "edit-nb-empty"],
)
def test_ca02_both_path_keys_present_are_denied(role: str, tool: str, tool_input: dict) -> None:
    _assert_blocked(_hook({"tool_name": tool, "tool_input": tool_input}, role), BOTH)


# --------------------------------------------------------------------------- CA-03

_MAIN = {"file_path": f"{ROOT}/api/src/qc_api/main.py"}


@pytest.mark.parametrize(
    "event",
    [
        {"tool_input": _MAIN},
        {"tool_name": 42, "tool_input": _MAIN},
        {"tool_name": None, "tool_input": _MAIN},
    ],
    ids=["absent", "42", "null"],
)
def test_ca03_tool_name_not_a_string(event: dict) -> None:
    _assert_blocked(_hook(event, "developer"), NO_TOOL_NAME)


@pytest.mark.parametrize(
    ("tool_name", "message"),
    [
        ("Bash", "unknown tool_name 'Bash'"),
        ("write", "unknown tool_name 'write'"),
        ("", "unknown tool_name ''"),
    ],
    ids=["Bash", "write", "empty"],
)
def test_ca03_unknown_tool_name(tool_name: str, message: str) -> None:
    _assert_blocked(_hook({"tool_name": tool_name, "tool_input": _MAIN}, "developer"), message)


# --------------------------------------------------------------------------- CA-04


@pytest.mark.parametrize(
    ("role", "tool", "tool_input", "message"),
    [
        (
            "ml-engineer",
            "NotebookEdit",
            {},
            "tool_input.notebook_path missing or empty for NotebookEdit",
        ),
        ("developer", "Write", {}, "tool_input.file_path missing or empty for Write"),
        ("developer", "Edit", {"file_path": ""}, "tool_input.file_path missing or empty for Edit"),
        (
            "developer",
            "Edit",
            {"file_path": "   "},
            "tool_input.file_path missing or empty for Edit",
        ),
        (
            "developer",
            "MultiEdit",
            {"file_path": 42},
            "tool_input.file_path missing or empty for MultiEdit",
        ),
        (
            "developer",
            "Write",
            {"file_path": None},
            "tool_input.file_path missing or empty for Write",
        ),
    ],
    ids=["nb-empty", "write-empty", "edit-blank", "edit-spaces", "multiedit-42", "write-null"],
)
def test_ca04_expected_field_missing_or_empty(
    role: str, tool: str, tool_input: dict, message: str
) -> None:
    _assert_blocked(_hook({"tool_name": tool, "tool_input": tool_input}, role), message)


# --------------------------------------------------------------------------- CA-05


@pytest.mark.parametrize(
    ("role", "tool", "field", "path", "cwd"),
    [
        ("developer", "Write", "file_path", _abs("api/src/qc_api/main.py"), None),
        ("developer", "Edit", "file_path", _abs("api/src/qc_api/main.py"), None),
        ("developer", "MultiEdit", "file_path", _abs("api/src/qc_api/main.py"), None),
        ("developer", "Write", "file_path", "api/src/qc_api/main.py", str(ROOT)),
        ("ml-engineer", "NotebookEdit", "notebook_path", _abs("ml/notebooks/train.ipynb"), None),
        ("ml-engineer", "Write", "file_path", _abs("ml/src/qc_ml/train.py"), None),
        ("tester", "Edit", "file_path", _abs("tests/acceptance/test_spec_022.py"), None),
        (
            "architect",
            "Write",
            "file_path",
            _abs("docs/specs/SPEC-022-manutencao-setup.md"),
            None,
        ),
    ],
    ids=[
        "dev-write",
        "dev-edit",
        "dev-multiedit",
        "dev-write-relative",
        "ml-notebook",
        "ml-write",
        "tester-edit",
        "architect-write",
    ],
)
def test_ca05_well_formed_events_allowed(
    role: str, tool: str, field: str, path: str, cwd: str | None
) -> None:
    event: dict[str, object] = {"tool_name": tool, "tool_input": {field: path}}
    if cwd is not None:
        event["cwd"] = cwd
    result = _hook(event, role)
    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert result.stderr == b""


# --------------------------------------------------------------------------- CA-06


def test_ca06_role_denial_unchanged() -> None:
    """CA-06: the role-denial message appears literally, in the unchanged SPEC-001 §4.6 format
    `guard_paths: role '<papel>' may not write '<caminho>' (SPEC-001, R-07)`, without "blocked:"
    (§5 preamble as fixed in afa4173, after SPEC_ISSUE-01).
    """
    event = {
        "tool_name": "NotebookEdit",
        "tool_input": {"notebook_path": _abs("ml/notebooks/train.ipynb")},
    }
    result = _hook(event, "developer")
    stderr = result.stderr.decode("utf-8")
    assert result.returncode == 2, (result.returncode, stderr)
    assert "role 'developer' may not write 'ml/notebooks/train.ipynb'" in stderr, stderr
    assert (
        "guard_paths: role 'developer' may not write 'ml/notebooks/train.ipynb' (SPEC-001, R-07)"
        in stderr
    ), stderr


# --------------------------------------------------------------------------- CA-07


def test_ca07_hook_imports_only_stdlib() -> None:
    tree = ast.parse(HOOK.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in hook"
            assert node.module is not None
            modules.add(node.module.split(".")[0])
    assert modules
    non_std = modules - set(sys.stdlib_module_names)
    assert not non_std, non_std


def test_ca07_spec001_hook_tests_still_pass() -> None:
    result = _run_pytest(
        [
            "-q",
            "tests/acceptance/test_spec_001.py",
            "-k",
            "ca11 or ca12 or ca13 or ca14 or ca15 or ca16 or ca17",
        ]
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert re.search(r"\b\d+ passed\b", out), out


# --------------------------------------------------------------------------- CA-08


def test_ca08_ci_postgres_trust_without_password() -> None:
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    jobs = wf["jobs"]
    pg = [
        (job, svc)
        for job in jobs.values()
        for svc in (job.get("services") or {}).values()
        if svc.get("image") == "postgres:16"
    ]
    assert len(pg) == 1, pg
    job, svc = pg[0]

    env = svc.get("env") or {}
    assert env["POSTGRES_HOST_AUTH_METHOD"] == "trust"
    assert env["POSTGRES_DB"] == "partqc_test"
    assert not [k for k in env if "PASSWORD" in str(k).upper()], env
    assert "pg_isready" in str(svc.get("options", "")), svc.get("options")

    job_env = {**(wf.get("env") or {}), **(job.get("env") or {})}
    assert job_env["TEST_DATABASE_URL"] == NEW_CI_URL


# --------------------------------------------------------------------------- CA-09


def test_ca09_env_example() -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert f"TEST_DATABASE_URL={NEW_LOCAL_URL}" in lines
    assert not [line for line in lines if OLD_URL_FRAGMENT in line]

    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    for var in PRE_EXISTING_ENV_VARS:
        assert var in values, f"{var} missing from .env.example"
    for key, value in values.items():
        if any(h in key for h in SECRET_HINTS):
            assert value == "", f"{key} has a value in .env.example"


# --------------------------------------------------------------------------- CA-10


def test_ca10_no_postgres_password_outside_docs_and_reviews() -> None:
    files = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.split(b"\0")
    offenders: list[str] = []
    scanned = 0
    for raw in files:
        if not raw:
            continue
        rel = raw.decode("utf-8")
        if rel.startswith(("docs/", "reviews/")):
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        for needle in (OLD_URL_FRAGMENT, PASSWORD_VAR):
            if needle in text:
                offenders.append(f"{rel}: {needle}")
    assert scanned > 20, scanned
    assert not offenders, offenders


# --------------------------------------------------------------------------- CA-11


def test_ca11_readme_local_postgres_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for needle in (
        "-e POSTGRES_HOST_AUTH_METHOD=trust",
        "-p 127.0.0.1:55432:5432",
        f"export TEST_DATABASE_URL={NEW_LOCAL_URL}",
        "docker rm -f partqc-pg",
    ):
        assert needle in readme, needle


# --------------------------------------------------------------------------- CA-12


def test_ca12_readme_workspace_trust_before_limitation() -> None:
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line == "### Hook de guarda de caminhos (R-07)"]
    assert len(starts) == 1, starts
    start = starts[0]
    following = [i for i in _headings(lines) if i > start]
    end = following[0] if following else len(lines)
    section = "\n".join(lines[start + 1 : end])

    assert WORKSPACE_TRUST in section
    assert "**Limitação:**" in section
    assert section.index(WORKSPACE_TRUST) < section.index("**Limitação:**")


# --------------------------------------------------------------------------- CA-13


def test_ca13_architect_commits_section_and_frontmatter() -> None:
    fm, body = _frontmatter_and_body(ROOT / ".claude" / "agents" / "architect.md")
    lines = body.splitlines()
    starts = [i for i, line in enumerate(lines) if line == "## Commits"]
    assert len(starts) == 1, starts
    start = starts[0]
    nxt = [i for i, line in enumerate(lines) if i > start and line.startswith("## ")]
    end = nxt[0] if nxt else len(lines)
    assert "\n".join(lines[start + 1 : end]).strip() == ARCHITECT_COMMITS

    assert fm["name"] == "architect"
    assert fm["tools"] == "Read, Grep, Glob, Write, Edit, WebSearch, WebFetch"
    assert fm["model"] == "inherit"
    assert fm["color"] == "purple"
    assert fm["skills"] == ["criar-spec", "criar-adr"]
    commands = [
        hook.get("command", "")
        for entry in fm["hooks"]["PreToolUse"]
        for hook in entry.get("hooks", [])
    ]
    assert any('guard_paths.py" --role architect' in c for c in commands), commands


# --------------------------------------------------------------------------- CA-14


def test_ca14_reviews_readme_architect_commits_after_role_tracking() -> None:
    text = (ROOT / "reviews" / "README.md").read_text(encoding="utf-8")
    paragraphs = _paragraphs(text)
    tracking = [i for i, p in enumerate(paragraphs) if p.startswith("**Rastreio de papéis:**")]
    commits = [i for i, p in enumerate(paragraphs) if p == REVIEWS_ARCHITECT]
    assert len(tracking) == 1, tracking
    assert len(commits) == 1, commits
    assert commits[0] > tracking[0]
    # §4.3: "logo depois" of the role-tracking paragraph.
    assert commits[0] == tracking[0] + 1


# --------------------------------------------------------------------------- CA-15


# CA-15: checked by CI and by the test-report, not by a test (docs/architecture.md section 10).


# --------------------------------------------------------------------------- CA-16


@pytest.mark.db
def test_ca16_db_smoke_with_passwordless_url() -> None:
    url = os.environ["TEST_DATABASE_URL"]
    parts = urlsplit(url)
    assert parts.scheme == "postgresql", url
    assert parts.username == "postgres", url
    assert parts.password is None, "TEST_DATABASE_URL must not carry a password (SPEC-022 §4.2)"
    assert parts.hostname == "localhost", url
    assert parts.path == "/partqc_test", url

    result = _run_pytest(["-q", "-rs", "tests/test_db_smoke.py"], TEST_DATABASE_URL=url)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "1 passed" in out, out
    assert "skipped" not in out.lower(), out
