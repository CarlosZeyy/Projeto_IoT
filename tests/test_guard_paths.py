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


# ---------------------------------------------------------------- SPEC-033 §4.1 (worktrees)

WORKTREE_ERROR = (
    "path is inside .claude/worktrees/ but not inside a git worktree of this repository"
)
# Identity and config local to each git command: never touch the repository identity (R-13).
GIT_ISOLATION = (
    "-c",
    "user.name=guard-test",
    "-c",
    "user.email=guard-test@example.invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "init.defaultBranch=main",
    "-c",
    "core.hooksPath=/dev/null",
)


def git(*args: str) -> None:
    subprocess.run(["git", *GIT_ISOLATION, *args], check=True, capture_output=True, timeout=60)


def make_repo(path: Path, *, with_hook: bool = True) -> Path:
    """Temporary git repository with one commit (and a copy of the hook, so PROJECT_ROOT=path)."""
    path.mkdir(parents=True)
    git("init", "-q", str(path))
    git("-C", str(path), "commit", "-q", "--allow-empty", "-m", "init")
    if with_hook:
        (path / ".claude/hooks").mkdir(parents=True)
        shutil.copy(HOOK, path / ".claude/hooks/guard_paths.py")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, Path]:
    """(R, W): repository R and its worktree W = R/.claude/worktrees/wt."""
    root = make_repo(tmp_path / "R")
    worktree = root / ".claude/worktrees/wt"
    git("-C", str(root), "worktree", "add", "-q", str(worktree), "-b", "wt")
    return root, worktree


def hook_of(root: Path) -> Path:
    return root / ".claude/hooks/guard_paths.py"


def assert_worktree_denied(result: subprocess.CompletedProcess[bytes]) -> None:
    assert_blocked(result, WORKTREE_ERROR)


WORKTREE_TABLE = [
    # (role, tool, path relative to W, expected exit code) — the cases of CA-01 and a few more
    ("developer", "Write", "api/src/qc_api/main.py", 0),
    ("developer", "Edit", "reviews/SPEC-033/r1-dev-report.md", 0),
    ("developer", "Write", "docs/specs/SPEC-001-setup-repositorio.md", 2),
    ("developer", "Write", ".claude/hooks/guard_paths.py", 2),
    ("developer", "Write", "edge/tests/acceptance/test_spec_030.py", 2),
    ("developer", "MultiEdit", "README.md", 0),
    ("developer", "Write", "ml/src/qc_ml/train.py", 2),
    ("tester", "Write", "edge/tests/acceptance/test_spec_030.py", 0),
    ("tester", "Write", "edge/src/qc_edge/app.py", 2),
    ("architect", "Edit", "docs/plan.md", 0),
    ("architect", "Edit", "docs/rules.md", 2),
    ("reviewer", "Write", "reviews/SPEC-030/r1-review-report.md", 0),
    ("ml-engineer", "NotebookEdit", "ml/notebooks/train_colab.ipynb", 0),
    ("security-devops", "Write", "infra/compose.yaml", 0),
]


@pytest.mark.parametrize(("role", "tool", "rel", "expected"), WORKTREE_TABLE)
def test_worktree_path_judged_relative_to_worktree_root(
    repo: tuple[Path, Path], role: str, tool: str, rel: str, expected: int
) -> None:
    root, worktree = repo
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    result = run_hook(event(str(worktree / rel), tool, key), role, hook_of(root))
    assert result.returncode == expected, result.stderr
    if expected == 0:
        assert (result.stdout, result.stderr) == (b"", b"")
    else:
        message = f"guard_paths: role '{role}' may not write '{rel}' (SPEC-001, R-07)"
        assert result.stderr.decode("utf-8").strip() == message


def test_worktree_relative_path_with_cwd(repo: tuple[Path, Path]) -> None:
    root, worktree = repo
    ok = run_hook(event("api/x.py", "Write", cwd=str(worktree)), "developer", hook_of(root))
    assert (ok.returncode, ok.stderr) == (0, b"")
    denied = run_hook(
        event("docs/specs/x.md", "Write", cwd=str(worktree)), "developer", hook_of(root)
    )
    assert denied.returncode == 2
    assert "role 'developer' may not write 'docs/specs/x.md'" in denied.stderr.decode("utf-8")


def test_main_checkout_unchanged_next_to_worktree(repo: tuple[Path, Path]) -> None:
    root, _ = repo
    assert run_hook(event(str(root / "api/x.py")), "developer", hook_of(root)).returncode == 0
    denied = run_hook(event(str(root / "docs/rules.md")), "developer", hook_of(root))
    assert "role 'developer' may not write 'docs/rules.md'" in denied.stderr.decode("utf-8")


ACCEPTANCE_TAIL = "x/tests/acceptance/t.py"


def test_plain_folder_under_worktrees_denied(repo: tuple[Path, Path]) -> None:
    root, _ = repo
    (root / ".claude/worktrees/comum/x").mkdir(parents=True)
    target = root / ".claude/worktrees/comum" / ACCEPTANCE_TAIL
    assert_worktree_denied(run_hook(event(str(target)), "tester", hook_of(root)))
    # a folder that does not exist yet (Write creating it) is denied too
    missing = root / ".claude/worktrees/nova" / ACCEPTANCE_TAIL
    assert_worktree_denied(run_hook(event(str(missing)), "tester", hook_of(root)))


def test_nested_clone_denied(repo: tuple[Path, Path]) -> None:
    root, _ = repo
    git("init", "-q", str(root / ".claude/worktrees/clone"))
    target = root / ".claude/worktrees/clone" / ACCEPTANCE_TAIL
    assert_worktree_denied(run_hook(event(str(target)), "tester", hook_of(root)))


def test_worktree_of_another_repository_denied(repo: tuple[Path, Path], tmp_path: Path) -> None:
    root, _ = repo
    other = make_repo(tmp_path / "R2", with_hook=False)
    git(
        "-C", str(other), "worktree", "add", "-q", str(root / ".claude/worktrees/alheia"), "-b", "a"
    )
    target = root / ".claude/worktrees/alheia" / ACCEPTANCE_TAIL
    assert_worktree_denied(run_hook(event(str(target)), "tester", hook_of(root)))


def test_fake_gitfile_pointing_to_another_worktree_denied(repo: tuple[Path, Path]) -> None:
    root, _ = repo
    fake = root / ".claude/worktrees/falsa"
    fake.mkdir()
    (fake / ".git").write_text(f"gitdir: {root / '.git/worktrees/wt'}\n", encoding="utf-8")
    target = fake / ACCEPTANCE_TAIL
    assert_worktree_denied(run_hook(event(str(target)), "tester", hook_of(root)))


def test_symlinked_gitfile_denied(repo: tuple[Path, Path]) -> None:
    root, worktree = repo
    link = root / ".claude/worktrees/link"
    link.mkdir()
    os.symlink(worktree / ".git", link / ".git")
    target = link / ACCEPTANCE_TAIL
    assert_worktree_denied(run_hook(event(str(target)), "tester", hook_of(root)))


def test_worktree_inside_worktree_denied(repo: tuple[Path, Path]) -> None:
    root, worktree = repo
    # even a real worktree of R placed inside W is refused
    git(
        "-C",
        str(root),
        "worktree",
        "add",
        "-q",
        str(worktree / ".claude/worktrees/outra"),
        "-b",
        "o",
    )
    target = worktree / ".claude/worktrees/outra" / ACCEPTANCE_TAIL
    assert_worktree_denied(run_hook(event(str(target)), "tester", hook_of(root)))
    plain = worktree / ".claude/worktrees/comum" / ACCEPTANCE_TAIL
    assert_worktree_denied(run_hook(event(str(plain)), "tester", hook_of(root)))


@pytest.mark.parametrize(
    "rel", [".claude/worktrees/wt", ".claude/worktrees/x.py", ".claude/worktrees"]
)
@pytest.mark.parametrize("role", ["tester", "developer"])
def test_worktree_root_and_loose_files_denied(repo: tuple[Path, Path], rel: str, role: str) -> None:
    root, _ = repo
    assert_worktree_denied(run_hook(event(str(root / rel)), role, hook_of(root)))


@pytest.mark.parametrize("rel", [".claude/worktrees/wt/.git", ".git/worktrees/wt/HEAD"])
def test_git_metadata_of_worktree_denied(repo: tuple[Path, Path], rel: str) -> None:
    root, _ = repo
    assert_blocked(
        run_hook(event(str(root / rel)), "developer", hook_of(root)), "path is inside .git/"
    )


def test_symlinks_inside_worktree_do_not_loosen(repo: tuple[Path, Path], tmp_path: Path) -> None:
    root, worktree = repo
    (root / "docs").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(root / "docs", worktree / "docs-link")
    os.symlink(outside, worktree / "fora")
    denied = run_hook(event(str(worktree / "docs-link/specs/x.md")), "developer", hook_of(root))
    assert denied.returncode == 2
    assert "role 'developer' may not write 'docs/specs/x.md'" in denied.stderr.decode("utf-8")
    assert_blocked(
        run_hook(event(str(worktree / "fora/x.py")), "developer", hook_of(root)),
        "path is outside the project root",
    )


def _write_gitfile(worktree: Path, content: bytes) -> None:
    gitfile = worktree / ".git"
    gitfile.unlink()
    gitfile.write_bytes(content)


@pytest.mark.parametrize(
    "content",
    [
        b"",  # empty
        b"\n",
        b"gitdir:\n",  # no path
        b"gitdir: \n",  # empty path
        b"GITDIR: x\n",  # wrong prefix
        b"\xff\xfegitdir: x\n",  # not UTF-8
        b"gitdir: x" + b" " * 4096 + b"\n",  # over 4096 bytes
        b"gitdir: ../../../.git\n",  # the main .git, not a child of .git/worktrees
        b"gitdir: ../../../.git/worktrees\n",  # the admin dir itself
        b"gitdir: ../../../.git/worktrees/nada\n",  # child that does not exist
        b"gitdir: /\x00x\n",  # NUL byte inside the path
    ],
)
def test_bad_gitfile_fails_closed(repo: tuple[Path, Path], content: bytes) -> None:
    root, worktree = repo
    _write_gitfile(worktree, content)
    target = worktree / "api/x.py"
    assert_worktree_denied(run_hook(event(str(target)), "developer", hook_of(root)))


def test_gitfile_directory_or_unreadable_fails_closed(repo: tuple[Path, Path]) -> None:
    root, worktree = repo
    gitfile = worktree / ".git"
    content = gitfile.read_bytes()
    gitfile.unlink()
    gitfile.mkdir()  # `.git` as a directory: a clone, not a worktree
    assert_worktree_denied(run_hook(event(str(worktree / "api/x.py")), "developer", hook_of(root)))
    gitfile.rmdir()
    gitfile.write_bytes(content)
    assert run_hook(event(str(worktree / "api/x.py")), "developer", hook_of(root)).returncode == 0
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root reads files without permission")
    gitfile.chmod(0)
    try:
        assert_worktree_denied(
            run_hook(event(str(worktree / "api/x.py")), "developer", hook_of(root))
        )
    finally:
        gitfile.chmod(0o644)


def _admin_dir(root: Path) -> Path:
    return root / ".git/worktrees/wt"


@pytest.mark.parametrize(
    "back",
    [
        None,  # gitdir file missing
        b"",
        b"/somewhere/else/.git\n",
        b"\xff\n",
    ],
)
def test_bad_back_pointer_fails_closed(repo: tuple[Path, Path], back: bytes | None) -> None:
    root, worktree = repo
    back_file = _admin_dir(root) / "gitdir"
    back_file.unlink()
    if back is not None:
        back_file.write_bytes(back)
    assert_worktree_denied(run_hook(event(str(worktree / "api/x.py")), "developer", hook_of(root)))


def test_symlinked_back_pointer_fails_closed(repo: tuple[Path, Path], tmp_path: Path) -> None:
    root, worktree = repo
    back_file = _admin_dir(root) / "gitdir"
    real = tmp_path / "gitdir-copy"
    real.write_bytes(back_file.read_bytes())
    back_file.unlink()
    os.symlink(real, back_file)
    assert_worktree_denied(run_hook(event(str(worktree / "api/x.py")), "developer", hook_of(root)))


def test_main_git_not_a_directory_fails_closed(repo: tuple[Path, Path], tmp_path: Path) -> None:
    """Condition 2: a project root whose `.git` is a file (itself a worktree) recognizes none."""
    root, _ = repo
    outer = tmp_path / "outer-wt"
    git("-C", str(root), "worktree", "add", "-q", str(outer), "-b", "outer")
    (outer / ".claude/hooks").mkdir(parents=True)
    shutil.copy(HOOK, hook_of(outer))
    inner = outer / ".claude/worktrees/inner"
    git("-C", str(root), "worktree", "add", "-q", str(inner), "-b", "inner")
    assert (outer / ".git").is_file()
    assert_worktree_denied(run_hook(event(str(inner / "api/x.py")), "developer", hook_of(outer)))


def test_relative_gitdir_paths_accepted(repo: tuple[Path, Path]) -> None:
    """`worktree.useRelativePaths`: gitfile relative to W, back-pointer relative to its dir."""
    root, worktree = repo
    _write_gitfile(worktree, b"gitdir: ../../../.git/worktrees/wt\n")
    (_admin_dir(root) / "gitdir").write_bytes(b"../../../.claude/worktrees/wt/.git\n")
    ok = run_hook(event(str(worktree / "api/x.py")), "developer", hook_of(root))
    assert (ok.returncode, ok.stderr) == (0, b"")
    denied = run_hook(event(str(worktree / "docs/rules.md")), "developer", hook_of(root))
    assert "may not write 'docs/rules.md'" in denied.stderr.decode("utf-8")


def test_gitfile_with_crlf_accepted(repo: tuple[Path, Path]) -> None:
    root, worktree = repo
    _write_gitfile(worktree, f"gitdir: {_admin_dir(root)}\r\n".encode())
    assert run_hook(event(str(worktree / "api/x.py")), "developer", hook_of(root)).returncode == 0


def test_worktree_with_space_and_accent(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "Área de trabalho" / "R")
    worktree = root / ".claude/worktrees/sessão um"
    git("-C", str(root), "worktree", "add", "-q", str(worktree), "-b", "s1")
    ok = run_hook(event(str(worktree / "api/ação.py")), "developer", hook_of(root))
    assert (ok.returncode, ok.stderr) == (0, b"")
    denied = run_hook(event(str(worktree / "api/ação.py")), "tester", hook_of(root))
    assert "may not write 'api/ação.py'" in denied.stderr.decode("utf-8")


def test_worktree_relative_in_process(repo: tuple[Path, Path]) -> None:
    import importlib.util

    root, worktree = repo
    spec = importlib.util.spec_from_file_location("guard_paths_worktree", hook_of(root))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.WORKTREE_ERROR == WORKTREE_ERROR
    assert module.relative_to_root(str(worktree / "api/a.py"), None) == "api/a.py"
    assert module.relative_to_root("b/c.py", str(worktree / "api")) == "api/b/c.py"
    with pytest.raises(module.GuardError, match="not inside a git worktree"):
        module.relative_to_root(str(root / ".claude/worktrees/nada/a.py"), None)
    # paths that merely start like the prefix are not worktree paths
    assert module.relative_to_root(str(root / ".claude/worktreesx/a.py"), None) == (
        ".claude/worktreesx/a.py"
    )
    assert module.relative_to_root(str(root / "x/.claude/worktrees/a.py"), None) == (
        "x/.claude/worktrees/a.py"
    )


def test_hook_does_not_import_subprocess() -> None:
    tree = ast.parse(HOOK.read_text(encoding="utf-8"))
    names = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "subprocess" not in names


def test_hook_documents_worktree_rule() -> None:
    doc = ast.get_docstring(ast.parse(HOOK.read_text(encoding="utf-8"))) or ""
    assert ".claude/worktrees/" in doc
    assert "but not\ninside a git worktree of this repository" in doc


def test_gitignore_and_readme_cover_worktrees() -> None:
    ignored = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "check-ignore",
            "--no-index",
            "-q",
            ".claude/worktrees/wt/api/x.py",
        ],
        timeout=30,
    )
    assert ignored.returncode == 0
    hook_ignored = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "check-ignore",
            "--no-index",
            "-q",
            ".claude/hooks/guard_paths.py",
        ],
        timeout=30,
    )
    assert hook_ignored.returncode == 1
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("### Hook de guarda de caminhos (R-07)", 1)[1]
    section = section.split("\n#", 1)[0]
    assert ".claude/worktrees/" in section
