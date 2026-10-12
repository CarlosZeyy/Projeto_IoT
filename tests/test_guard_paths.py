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


# ---------------------------------------------------------------- SPEC-022 §4.1 (RV-01)

BLOCKED = "guard_paths: blocked: "
BOTH = "tool_input has both file_path and notebook_path"
MAIN_PY = str(ROOT / "api/src/qc_api/main.py")


def raw_event(tool_input: object, tool_name: object = None, *, omit_tool: bool = False) -> str:
    payload: dict = {"tool_input": tool_input}
    if not omit_tool:
        payload["tool_name"] = tool_name
    return json.dumps(payload)


def assert_blocked(result: subprocess.CompletedProcess[bytes], message: str) -> None:
    assert result.returncode == 2, result.stderr
    assert result.stdout == b""
    assert result.stderr.decode("utf-8").strip() == f"{BLOCKED}{message} (SPEC-001, R-07)"


def test_notebook_edit_ignores_allowed_file_path_rv01() -> None:
    """CA-01: the forbidden notebook_path can no longer hide behind an allowed file_path."""
    stdin = raw_event(
        {"notebook_path": str(ROOT / "api/src/evil.ipynb"), "file_path": str(ROOT / "ml/x.ipynb")},
        "NotebookEdit",
    )
    assert_blocked(run_hook(stdin, "ml-engineer"), BOTH)


@pytest.mark.parametrize(
    ("role", "tool", "tool_input"),
    [
        ("ml-engineer", "NotebookEdit", {"notebook_path": "ml/a.ipynb", "file_path": "   "}),
        ("ml-engineer", "NotebookEdit", {"notebook_path": "ml/a.ipynb", "file_path": 42}),
        ("ml-engineer", "NotebookEdit", {"notebook_path": "ml/a.ipynb", "file_path": None}),
        ("ml-engineer", "Write", {"file_path": "ml/a.py", "notebook_path": "api/b.ipynb"}),
        ("developer", "Edit", {"file_path": "api/src/qc_api/main.py", "notebook_path": ""}),
        ("developer", "MultiEdit", {"file_path": "api/src/qc_api/main.py", "notebook_path": None}),
        ("ml-engineer", "NotebookEdit", {"notebook_path": "ml/a.ipynb", "file_path": "ml/b.py"}),
    ],
)
def test_both_path_keys_present_fail_closed(role: str, tool: str, tool_input: dict) -> None:
    """CA-02: the other field's key being present is enough, whatever its value."""
    absolute = {
        k: str(ROOT / v) if isinstance(v, str) and v.strip() else v for k, v in tool_input.items()
    }
    assert_blocked(run_hook(raw_event(absolute, tool), role), BOTH)


@pytest.mark.parametrize(
    ("tool_name", "omit", "message"),
    [
        (None, True, "event has no tool_name string"),
        (42, False, "event has no tool_name string"),
        (None, False, "event has no tool_name string"),
        (["Write"], False, "event has no tool_name string"),
        ("Bash", False, "unknown tool_name 'Bash'"),
        ("write", False, "unknown tool_name 'write'"),
        ("", False, "unknown tool_name ''"),
        ("WRITE", False, "unknown tool_name 'WRITE'"),
        (" Write", False, "unknown tool_name ' Write'"),
        ("Read", False, "unknown tool_name 'Read'"),
    ],
)
def test_tool_name_missing_or_unknown_fail_closed(
    tool_name: object, omit: bool, message: str
) -> None:
    """CA-03: tool_name must be one of the four exact, case-sensitive names."""
    stdin = raw_event({"file_path": MAIN_PY}, tool_name, omit_tool=omit)
    assert_blocked(run_hook(stdin, "developer"), message)


@pytest.mark.parametrize(
    ("role", "tool", "tool_input", "message"),
    [
        ("ml-engineer", "NotebookEdit", {}, "tool_input.notebook_path missing or empty for "),
        ("ml-engineer", "NotebookEdit", {"notebook_path": " \t"}, "tool_input.notebook_path "),
        ("developer", "Write", {}, "tool_input.file_path missing or empty for "),
        ("developer", "Edit", {"file_path": ""}, "tool_input.file_path missing or empty for "),
        ("developer", "Edit", {"file_path": "   "}, "tool_input.file_path missing or empty for "),
        ("developer", "MultiEdit", {"file_path": 42}, "tool_input.file_path missing or empty for "),
        ("developer", "Write", {"file_path": None}, "tool_input.file_path missing or empty for "),
        ("developer", "Write", {"command": "ls"}, "tool_input.file_path missing or empty for "),
    ],
)
def test_expected_field_missing_or_empty_fail_closed(
    role: str, tool: str, tool_input: dict, message: str
) -> None:
    """CA-04: the expected field must be a non-blank string."""
    result = run_hook(raw_event(tool_input, tool), role)
    assert result.returncode == 2, result.stderr
    stderr = result.stderr.decode("utf-8").strip()
    assert stderr.startswith(f"{BLOCKED}{message}")
    assert stderr.endswith(f" for {tool} (SPEC-001, R-07)")


@pytest.mark.parametrize(
    ("event_order", "message"),
    [
        # rule 2 before rule 3: no tool_input wins over a missing tool_name
        ({"tool_name": None}, "event has no tool_input object"),
        # rule 3 before rule 5: a bad tool_name wins over both path keys
        (
            {"tool_input": {"file_path": MAIN_PY, "notebook_path": MAIN_PY}, "tool_name": 1},
            "event has no tool_name string",
        ),
        # rule 4 before rule 5
        (
            {"tool_input": {"file_path": MAIN_PY, "notebook_path": MAIN_PY}, "tool_name": "Bash"},
            "unknown tool_name 'Bash'",
        ),
        # rule 5 before rule 6: both keys, expected one empty
        ({"tool_input": {"file_path": "", "notebook_path": ""}, "tool_name": "Write"}, BOTH),
    ],
)
def test_checks_run_in_spec_order(event_order: dict, message: str) -> None:
    assert_blocked(run_hook(json.dumps(event_order), "developer"), message)


@pytest.mark.parametrize(
    ("role", "tool", "key", "path", "cwd"),
    [
        ("developer", "Write", "file_path", MAIN_PY, None),
        ("developer", "Edit", "file_path", MAIN_PY, None),
        ("developer", "MultiEdit", "file_path", MAIN_PY, None),
        ("developer", "Write", "file_path", "api/src/qc_api/main.py", str(ROOT)),
        (
            "ml-engineer",
            "NotebookEdit",
            "notebook_path",
            str(ROOT / "ml/notebooks/train.ipynb"),
            None,
        ),
        ("ml-engineer", "Write", "file_path", str(ROOT / "ml/src/qc_ml/train.py"), None),
        ("tester", "Edit", "file_path", str(ROOT / "tests/acceptance/test_spec_022.py"), None),
        (
            "architect",
            "Write",
            "file_path",
            str(ROOT / "docs/specs/SPEC-022-manutencao-setup.md"),
            None,
        ),
    ],
)
def test_well_formed_events_still_allowed(
    role: str, tool: str, key: str, path: str, cwd: str | None
) -> None:
    """CA-05: only the expected field, allowed path -> exit 0, silent."""
    result = run_hook(event(path, tool, key, cwd), role)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


def test_role_denial_unchanged_for_well_formed_notebook_edit() -> None:
    """CA-06: the per-role denial message did not change."""
    stdin = event(str(ROOT / "ml/notebooks/train.ipynb"), "NotebookEdit", "notebook_path")
    result = run_hook(stdin, "developer")
    assert result.returncode == 2
    assert "role 'developer' may not write 'ml/notebooks/train.ipynb'" in result.stderr.decode()


def test_target_path_in_process() -> None:
    """Direct calls to target_path(): field by tool_name, GuardError on ambiguity."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("guard_paths_target", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.target_path({"tool_name": "Edit", "tool_input": {"file_path": "a"}}) == "a"
    nb = {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "b.ipynb"}}
    assert module.target_path(nb) == "b.ipynb"
    with pytest.raises(module.GuardError, match="missing or empty for NotebookEdit"):
        module.target_path({"tool_name": "NotebookEdit", "tool_input": {"path": "b.ipynb"}})
    with pytest.raises(module.GuardError, match="both file_path and notebook_path"):
        module.target_path(
            {"tool_name": "Edit", "tool_input": {"file_path": "a", "notebook_path": None}}
        )
    assert set(module.PATH_FIELD_BY_TOOL) == {"Write", "Edit", "MultiEdit", "NotebookEdit"}


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
