"""Path guard hook `.claude/hooks/guard_paths.py` (SPEC-001 §4.6), run as a subprocess."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude/hooks/guard_paths.py"


def run_hook(
    stdin: str | bytes, role: str | None, hook: Path = HOOK
) -> subprocess.CompletedProcess[bytes]:
    args = [sys.executable, str(hook)]
    if role is not None:
        args += ["--role", role]
    data = stdin.encode("utf-8") if isinstance(stdin, str) else stdin
    return subprocess.run(args, input=data, capture_output=True, timeout=30)


def event(path: str, tool: str = "Edit", key: str = "file_path", cwd: str | None = None) -> str:
    payload: dict = {"tool_name": tool, "tool_input": {key: path}}
    if cwd is not None:
        payload["cwd"] = cwd
    return json.dumps(payload)


def check(role: str, rel: str, tool: str = "Edit", key: str = "file_path") -> int:
    return run_hook(event(str(ROOT / rel), tool, key), role).returncode


ROLE_TABLE = [
    # (role, path relative to root, expected exit code) — table of CA-12
    ("developer", "api/src/qc_api/main.py", 0),
    ("developer", "api/tests/acceptance/test_spec_004.py", 2),
    ("developer", "tests/acceptance/test_spec_001.py", 2),
    ("developer", "docs/specs/SPEC-004-api-ingestao.md", 2),
    ("developer", "docs/rules.md", 2),
    ("developer", "ml/src/qc_ml/train.py", 2),
    ("developer", "reviews/SPEC-004/r1-dev-report.md", 0),
    ("developer", "reviews/SPEC-004/r1-test-report.md", 2),
    ("developer", ".claude/agents/developer.md", 2),
    ("ml-engineer", "ml/src/qc_ml/train.py", 0),
    ("ml-engineer", "ml/tests/acceptance/test_spec_011.py", 2),
    ("ml-engineer", "api/src/qc_api/main.py", 2),
    ("tester", "packages/contracts/tests/acceptance/test_spec_002.py", 0),
    ("tester", "reviews/SPEC-002/r2-test-report.md", 0),
    ("tester", "packages/contracts/tests/test_schemas.py", 2),
    ("reviewer", "reviews/SPEC-004/r1-review-report.md", 0),
    ("reviewer", "reviews/SPEC-004/r1-security-report.md", 0),
    ("reviewer", "api/src/qc_api/main.py", 2),
    ("security-devops", "infra/render.yaml", 0),
    ("security-devops", ".github/workflows/keepalive.yml", 0),
    ("security-devops", "docs/deployment-plan.md", 0),
    ("security-devops", "api/src/qc_api/main.py", 2),
    ("architect", "docs/architecture.md", 0),
    ("architect", "docs/rules.md", 2),
    ("architect", "README.md", 2),
]

EXTRA_TABLE = [
    # more cases derived from §4.6
    ("developer", "README.md", 0),
    ("developer", "pyproject.toml", 0),
    ("developer", "docs/adr/ADR-010-python-312-uv-workspace.md", 2),
    ("developer", "docs/architecture.md", 0),
    ("developer", "reviews/README.md", 2),
    ("developer", "reviews/SPEC-004/notes.md", 2),
    ("developer", ".claude/settings.json", 2),
    ("developer", "edge/tests/test_x.py", 0),
    ("developer", "packages/contracts/tests/acceptance/deep/x.py", 2),
    ("ml-engineer", "reviews/SPEC-011/r1-dev-report.md", 0),
    ("ml-engineer", "reviews/SPEC-011/r1-test-report.md", 2),
    ("tester", "tests/acceptance/test_spec_001.py", 0),
    ("tester", "reviews/SPEC-002/r2-dev-report.md", 2),
    ("tester", "api/tests/acceptance_helpers.py", 2),
    ("reviewer", "reviews/SPEC-004/r1-test-report.md", 2),
    ("security-devops", "pyproject.toml", 0),
    ("security-devops", "api/pyproject.toml", 2),
    ("security-devops", "uv.lock", 0),
    ("security-devops", ".env.example", 0),
    ("security-devops", "infra/tests/acceptance/test_spec_015.py", 2),
    ("security-devops", "dashboard/requirements.txt", 0),
    ("security-devops", "dashboard/app.py", 2),
    ("architect", "docs/specs/SPEC-004-api-ingestao.md", 0),
    ("architect", "docs/adr/ADR-016-x.md", 0),
    ("architect", "api/src/qc_api/main.py", 2),
]


@pytest.mark.parametrize(("role", "rel", "expected"), ROLE_TABLE + EXTRA_TABLE)
def test_role_table(role: str, rel: str, expected: int) -> None:
    assert check(role, rel) == expected


def test_denied_message_format() -> None:
    result = run_hook(event(str(ROOT / "api/src/qc_api/main.py")), "tester")
    assert result.returncode == 2
    assert result.stdout == b""
    stderr = result.stderr.decode("utf-8")
    assert "role 'tester' may not write 'api/src/qc_api/main.py'" in stderr
    assert stderr.strip() == (
        "guard_paths: role 'tester' may not write 'api/src/qc_api/main.py' (SPEC-001, R-07)"
    )


def test_allowed_is_silent() -> None:
    result = run_hook(event(str(ROOT / "api/src/qc_api/main.py")), "developer")
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


@pytest.mark.parametrize(
    "raw",
    [
        str(ROOT / "api/../docs/rules.md"),
        "/tmp/x.py",
        str(ROOT / ".git/config"),
        str(ROOT / "api/../../outside.py"),
        str(ROOT),
    ],
)
def test_traversal_outside_root_and_git_are_blocked(raw: str) -> None:
    assert run_hook(event(raw), "developer").returncode == 2


@pytest.mark.parametrize(
    "stdin",
    [
        "not json",
        "",
        "[]",
        json.dumps({"tool_name": "Edit"}),
        json.dumps({"tool_name": "Edit", "tool_input": {}}),
        json.dumps({"tool_name": "Edit", "tool_input": {"file_path": ""}}),
        json.dumps({"tool_name": "Edit", "tool_input": {"file_path": 42}}),
        json.dumps({"tool_name": "Edit", "tool_input": {"command": "ls"}}),
    ],
)
def test_bad_events_fail_closed(stdin: str) -> None:
    assert run_hook(stdin, "developer").returncode == 2


def test_invalid_utf8_fails_closed() -> None:
    assert run_hook(b"\xff\xfe{", "developer").returncode == 2


@pytest.mark.parametrize("role", ["admin", None, ""])
def test_unknown_or_missing_role_fails_closed(role: str | None) -> None:
    assert run_hook(event(str(ROOT / "README.md")), role).returncode == 2


def test_notebook_edit_uses_notebook_path() -> None:
    nb = "ml/notebooks/train.ipynb"
    assert check("ml-engineer", nb, tool="NotebookEdit", key="notebook_path") == 0
    assert check("developer", nb, tool="NotebookEdit", key="notebook_path") == 2


def test_relative_path_resolved_from_event_cwd() -> None:
    assert run_hook(event("api/x.py", cwd=str(ROOT)), "developer").returncode == 0
    assert run_hook(event("docs/rules.md", cwd=str(ROOT)), "developer").returncode == 2
    assert run_hook(event("../x.py", cwd=str(ROOT / "api")), "developer").returncode == 0
    # relative path without cwd: fail closed
    assert run_hook(event("api/x.py"), "developer").returncode == 2


def test_symlink_escaping_root_is_blocked(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    (proj / ".claude/hooks").mkdir(parents=True)
    hook = proj / ".claude/hooks/guard_paths.py"
    shutil.copy(HOOK, hook)
    outside = tmp_path / "outside"
    outside.mkdir()
    (proj / "api").mkdir()
    os.symlink(outside, proj / "api/link")
    os.symlink(proj / "docs", proj / "api/docs-link")
    assert run_hook(event(str(proj / "api/link/x.py")), "developer", hook).returncode == 2
    # a symlink inside the root pointing to docs/ is judged by its real target
    assert run_hook(event(str(proj / "api/docs-link/rules.md")), "developer", hook).returncode == 2
    assert run_hook(event(str(proj / "api/x.py")), "developer", hook).returncode == 0


def test_root_with_space_and_accent(tmp_path: Path) -> None:
    proj = tmp_path / "Área de trabalho" / "proj"
    (proj / ".claude/hooks").mkdir(parents=True)
    hook = proj / ".claude/hooks/guard_paths.py"
    shutil.copy(HOOK, hook)
    allowed = proj / "api/src/qc_api/main.py"
    assert run_hook(event(str(allowed)), "developer", hook).returncode == 0
    denied = run_hook(event(str(proj / "docs/rules.md")), "developer", hook)
    assert denied.returncode == 2
    assert "may not write 'docs/rules.md'" in denied.stderr.decode("utf-8")
    accented = run_hook(event(str(proj / "api/ação.py")), "tester", hook)
    assert "'api/ação.py'" in accented.stderr.decode("utf-8")


def test_hook_imports_only_stdlib() -> None:
    tree = ast.parse(HOOK.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative imports are not allowed"
            modules.add((node.module or "").split(".")[0])
    assert modules, "no imports found"
    assert modules <= set(sys.stdlib_module_names), modules - set(sys.stdlib_module_names)


def test_hook_documents_bash_limitation() -> None:
    header = HOOK.read_text(encoding="utf-8")[:2000]
    assert "Bash" in header and "NOT intercepted" in header


def test_glob_semantics_in_process() -> None:
    """`*` stays inside one segment; `**` spans zero or more whole segments."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("guard_paths_under_test", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    match = module.glob_match
    assert match("**/tests/acceptance/**", "tests/acceptance/x.py")
    assert match("**/tests/acceptance/**", "api/tests/acceptance/x.py")
    assert match("**/tests/acceptance/**", "a/b/tests/acceptance/c/d.py")
    assert not match("**/tests/acceptance/**", "api/tests/acceptance_x/x.py")
    assert match("reviews/SPEC-*/r*-dev-report.md", "reviews/SPEC-004/r1-dev-report.md")
    assert not match("reviews/SPEC-*/r*-dev-report.md", "reviews/SPEC-004/x/r1-dev-report.md")
    assert not match("docs/*", "docs/specs/SPEC-001.md")
    assert match("docs/**", "docs/specs/SPEC-001.md")
    assert match("pyproject.toml", "pyproject.toml")
    assert not match("pyproject.toml", "api/pyproject.toml")
    assert match("**", "README.md")
