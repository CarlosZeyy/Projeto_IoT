"""Acceptance tests for SPEC-033 (path guard hook inside git worktrees in `.claude/worktrees/`).

Written by the tester from the SPEC acceptance criteria (CA-01 to CA-07). CA-08 is manual and is
recorded in the test report.

As the §5 preamble says, every hook test builds a temporary git repository `R` (with one commit)
outside the project, copies `.claude/hooks/guard_paths.py` to `R/.claude/hooks/guard_paths.py`
(so `PROJECT_ROOT` is `R`), creates the worktree `W = R/.claude/worktrees/wt` with
`git -C R worktree add R/.claude/worktrees/wt -b wt` and runs `python3 <copy> --role <role>` with
the event on stdin. Everything lives under pytest's `tmp_path`; `_inside()` checks it before any
write, symlink or deletion. Git runs with a command-local identity and without the user's global
or system config (R-13, SPEC-033 §6).

The `test_extra_*` tests cover §4.1 requirements that have no CA of their own (size limit, UTF-8,
`lstat`, read errors, fail closed) and the "nothing else changes" rule of §2.
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

import pytest

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "guard_paths.py"

# The SPEC runs the hook as `python3 .../guard_paths.py`.
PYTHON3 = shutil.which("python3") or sys.executable

WORKTREE_ERROR = (
    "path is inside .claude/worktrees/ but not inside a git worktree of this repository"
)
GIT_ERROR = "path is inside .git/"
OUTSIDE_ERROR = "path is outside the project root"


# --------------------------------------------------------------------------- helpers


def _inside(base: Path, path: Path) -> Path:
    """Refuse to touch anything that is not under `base` (the test's tmp_path)."""
    resolved_base = base.resolve()
    parent = path.parent.resolve()
    assert parent == resolved_base or resolved_base in parent.parents, (base, path)
    return path


def _git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(*args: str | Path) -> subprocess.CompletedProcess[str]:
    cmd = [
        "git",
        "-c",
        "user.name=PartQC Test",
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "init.defaultBranch=main",
        "-c",
        "commit.gpgsign=false",
        *[str(a) for a in args],
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=_git_env(), timeout=60)
    assert result.returncode == 0, (cmd, result.stdout, result.stderr)
    return result


def _make_repo(base: Path, path: Path) -> Path:
    """`git init` + one commit (README.md and docs/plan.md) at `path`, under `base`."""
    _inside(base, path)
    path.mkdir(parents=True)
    _git("init", "-q", path)
    (path / "README.md").write_text("temp\n", encoding="utf-8")
    (path / "docs").mkdir()
    (path / "docs" / "plan.md").write_text("plan\n", encoding="utf-8")
    _git("-C", path, "add", "README.md", "docs/plan.md")
    _git("-C", path, "commit", "-q", "-m", "init")
    return path


def _make_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return (R, W, copied hook) as described in the §5 preamble."""
    repo = _make_repo(tmp_path, tmp_path / "R")
    hooks = _inside(tmp_path, repo / ".claude" / "hooks" / "guard_paths.py").parent
    hooks.mkdir(parents=True)
    hook = hooks / "guard_paths.py"
    shutil.copy2(HOOK, hook)
    worktree = repo / ".claude" / "worktrees" / "wt"
    _inside(tmp_path, worktree)
    _git("-C", repo, "worktree", "add", "-q", worktree, "-b", "wt")
    assert (worktree / ".git").is_file()
    return repo, worktree, hook


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path, Path]:
    return _make_project(tmp_path)


def _event(tool: str, path: str, cwd: str | None = None) -> dict[str, object]:
    field = "notebook_path" if tool == "NotebookEdit" else "file_path"
    event: dict[str, object] = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {field: path},
    }
    if cwd is not None:
        event["cwd"] = cwd
    return event


def _run_hook(
    hook: Path, role: str, event: dict[str, object], *, timeout: float = 30
) -> subprocess.CompletedProcess[bytes]:
    # The process cwd is the hooks folder, so only absolute paths or the event cwd resolve.
    return subprocess.run(
        [PYTHON3, str(hook), "--role", role],
        input=json.dumps(event).encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        cwd=hook.parent,
    )


def _assert_allowed(result: subprocess.CompletedProcess[bytes]) -> None:
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, (result.returncode, stderr)
    assert result.stderr == b"", stderr


def _assert_blocked(result: subprocess.CompletedProcess[bytes], message: str) -> None:
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 2, (result.returncode, stderr)
    assert f"guard_paths: blocked: {message}" in stderr, stderr


def _assert_role_denied(result: subprocess.CompletedProcess[bytes], message: str) -> None:
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 2, (result.returncode, stderr)
    assert message in stderr, stderr
    # Unchanged SPEC-001 §4.6 format (SPEC-022 §5 convention: no "blocked:" for role denials).
    assert f"guard_paths: {message} (SPEC-001, R-07)" in stderr, stderr


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


def _run_pytest(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run pytest on explicit files, without the database (SPEC-033 §6, architecture §10)."""
    env = dict(os.environ)
    for key in (
        "PYTEST_ADDOPTS",
        "PYTEST_CURRENT_TEST",
        "PYTEST_PLUGINS",
        "CI",
        "TEST_DATABASE_URL",
    ):
        env.pop(key, None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


# --------------------------------------------------------------------------- CA-01

CA01_CASES = [
    ("developer", "Write", "api/src/qc_api/main.py", None),
    ("developer", "Edit", "reviews/SPEC-033/r1-dev-report.md", None),
    (
        "developer",
        "Write",
        "docs/specs/SPEC-001-setup-repositorio.md",
        "role 'developer' may not write 'docs/specs/SPEC-001-setup-repositorio.md'",
    ),
    (
        "developer",
        "Write",
        ".claude/hooks/guard_paths.py",
        "role 'developer' may not write '.claude/hooks/guard_paths.py'",
    ),
    (
        "developer",
        "Write",
        "edge/tests/acceptance/test_spec_030.py",
        "role 'developer' may not write 'edge/tests/acceptance/test_spec_030.py'",
    ),
    ("tester", "Write", "edge/tests/acceptance/test_spec_030.py", None),
    (
        "tester",
        "Write",
        "edge/src/qc_edge/app.py",
        "role 'tester' may not write 'edge/src/qc_edge/app.py'",
    ),
    ("architect", "Edit", "docs/plan.md", None),
    ("architect", "Edit", "docs/rules.md", "role 'architect' may not write 'docs/rules.md'"),
    ("reviewer", "Write", "reviews/SPEC-030/r1-review-report.md", None),
    ("ml-engineer", "NotebookEdit", "ml/notebooks/train_colab.ipynb", None),
    ("security-devops", "Write", "infra/compose.yaml", None),
]


@pytest.mark.parametrize(
    ("role", "tool", "rel", "message"),
    CA01_CASES,
    ids=[f"{role}-{tool}-{rel}" for role, tool, rel, _ in CA01_CASES],
)
def test_ca01_worktree_paths_judged_by_role_table(
    project: tuple[Path, Path, Path], role: str, tool: str, rel: str, message: str | None
) -> None:
    _, worktree, hook = project
    result = _run_hook(hook, role, _event(tool, f"{worktree}/{rel}"))
    if message is None:
        _assert_allowed(result)
    else:
        _assert_role_denied(result, message)


# --------------------------------------------------------------------------- CA-02


def test_ca02_relative_path_with_cwd_in_worktree(project: tuple[Path, Path, Path]) -> None:
    _, worktree, hook = project
    allowed = _run_hook(hook, "developer", _event("Write", "api/x.py", cwd=str(worktree)))
    _assert_allowed(allowed)

    denied = _run_hook(hook, "developer", _event("Write", "docs/specs/x.md", cwd=str(worktree)))
    _assert_role_denied(denied, "role 'developer' may not write 'docs/specs/x.md'")


# --------------------------------------------------------------------------- CA-03


def _setup_comum(tmp_path: Path, repo: Path, worktree: Path) -> str:
    folder = _inside(tmp_path, repo / ".claude" / "worktrees" / "comum")
    folder.mkdir()
    return f"{folder}/x/tests/acceptance/t.py"


def _setup_clone(tmp_path: Path, repo: Path, worktree: Path) -> str:
    folder = _inside(tmp_path, repo / ".claude" / "worktrees" / "clone")
    _git("init", "-q", folder)
    assert (folder / ".git").is_dir()
    return f"{folder}/x/tests/acceptance/t.py"


def _setup_alheia(tmp_path: Path, repo: Path, worktree: Path) -> str:
    other = _make_repo(tmp_path, tmp_path / "R2")
    folder = _inside(tmp_path, repo / ".claude" / "worktrees" / "alheia")
    _git("-C", other, "worktree", "add", "-q", folder, "-b", "alheia")
    assert (folder / ".git").is_file()
    return f"{folder}/x/tests/acceptance/t.py"


def _setup_falsa(tmp_path: Path, repo: Path, worktree: Path) -> str:
    folder = _inside(tmp_path, repo / ".claude" / "worktrees" / "falsa")
    folder.mkdir()
    gitfile = _inside(tmp_path, folder / ".git")
    gitfile.write_text(f"gitdir: {repo}/.git/worktrees/wt\n", encoding="utf-8")
    return f"{folder}/x/tests/acceptance/t.py"


def _setup_link(tmp_path: Path, repo: Path, worktree: Path) -> str:
    folder = _inside(tmp_path, repo / ".claude" / "worktrees" / "link")
    folder.mkdir()
    _inside(tmp_path, folder / ".git").symlink_to(worktree / ".git")
    return f"{folder}/x/tests/acceptance/t.py"


def _setup_nested_path(tmp_path: Path, repo: Path, worktree: Path) -> str:
    return f"{worktree}/.claude/worktrees/outra/x/tests/acceptance/t.py"


def _setup_nested_real(tmp_path: Path, repo: Path, worktree: Path) -> str:
    # Same path as item 6, but `outra` is a real git worktree of R created inside W.
    folder = _inside(tmp_path, worktree / ".claude" / "worktrees" / "outra")
    _git("-C", repo, "worktree", "add", "-q", folder, "-b", "outra")
    assert (folder / ".git").is_file()
    return f"{folder}/x/tests/acceptance/t.py"


def _setup_root(tmp_path: Path, repo: Path, worktree: Path) -> str:
    return str(worktree)


def _setup_loose(tmp_path: Path, repo: Path, worktree: Path) -> str:
    return f"{repo}/.claude/worktrees/x.py"


CA03_SETUPS = {
    "1-comum": _setup_comum,
    "2-clone": _setup_clone,
    "3-alheia": _setup_alheia,
    "4-falsa": _setup_falsa,
    "5-link": _setup_link,
    "6-nested-path": _setup_nested_path,
    "6-nested-real-worktree": _setup_nested_real,
    "7-worktree-root": _setup_root,
    "7-loose-file": _setup_loose,
}


@pytest.mark.parametrize("case", list(CA03_SETUPS), ids=list(CA03_SETUPS))
def test_ca03_not_a_worktree_of_this_repo_fails_closed(tmp_path: Path, case: str) -> None:
    repo, worktree, hook = _make_project(tmp_path)
    target = CA03_SETUPS[case](tmp_path, repo, worktree)
    result = _run_hook(hook, "tester", _event("Write", target))
    _assert_blocked(result, WORKTREE_ERROR)


# --------------------------------------------------------------------------- CA-04


@pytest.mark.parametrize("rel", ["W/.git", "R/.git/worktrees/wt/HEAD"])
def test_ca04_worktree_git_metadata_denied(project: tuple[Path, Path, Path], rel: str) -> None:
    repo, worktree, hook = project
    base = worktree if rel.startswith("W/") else repo
    target = f"{base}/{rel[2:]}"
    _assert_blocked(_run_hook(hook, "developer", _event("Write", target)), GIT_ERROR)


# --------------------------------------------------------------------------- CA-05


def test_ca05_symlinks_inside_worktree_do_not_loosen(tmp_path: Path) -> None:
    repo, worktree, hook = _make_project(tmp_path)
    outside = _inside(tmp_path, tmp_path / "outside-dir")
    outside.mkdir()
    _inside(tmp_path, worktree / "docs-link").symlink_to(repo / "docs", target_is_directory=True)
    _inside(tmp_path, worktree / "fora").symlink_to(outside, target_is_directory=True)

    via_docs = _run_hook(hook, "developer", _event("Write", f"{worktree}/docs-link/specs/x.md"))
    _assert_role_denied(via_docs, "role 'developer' may not write 'docs/specs/x.md'")

    via_fora = _run_hook(hook, "developer", _event("Write", f"{worktree}/fora/x.py"))
    _assert_blocked(via_fora, OUTSIDE_ERROR)


# --------------------------------------------------------------------------- CA-06


def test_ca06_spec001_hook_tests_still_pass() -> None:
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


def test_ca06_spec022_hook_tests_still_pass() -> None:
    result = _run_pytest(
        [
            "-q",
            "tests/acceptance/test_spec_022.py",
            "-k",
            "ca01 or ca02 or ca03 or ca04 or ca05 or ca06",
        ]
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert re.search(r"\b\d+ passed\b", out), out


def test_ca06_hook_imports_only_stdlib_and_no_subprocess() -> None:
    tree = ast.parse(HOOK.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in hook"
            assert node.module is not None
            modules.add(node.module)
    assert modules
    tops = {m.split(".")[0] for m in modules}
    assert not tops - set(sys.stdlib_module_names), tops - set(sys.stdlib_module_names)
    assert "subprocess" not in tops, modules
    # Dynamic imports would dodge the check above.
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "__import__" not in names | attrs
    assert "import_module" not in names | attrs


# --------------------------------------------------------------------------- CA-07


def _check_ignore(rel: str) -> int:
    return subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", rel],
        cwd=ROOT,
        capture_output=True,
        timeout=30,
    ).returncode


def test_ca07_gitignore_and_readme() -> None:
    assert _check_ignore(".claude/worktrees/wt/api/x.py") == 0
    assert _check_ignore(".claude/hooks/guard_paths.py") == 1

    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line == "### Hook de guarda de caminhos (R-07)"]
    assert len(starts) == 1, starts
    start = starts[0]
    following = [i for i in _headings(lines) if i > start]
    end = following[0] if following else len(lines)
    section = "\n".join(lines[start + 1 : end])
    assert ".claude/worktrees/" in section, section


# --------------------------------------------------------------------------- extras (§4.1, §2)


def _fake_worktree(tmp_path: Path, repo: Path, name: str) -> Path:
    folder = _inside(tmp_path, repo / ".claude" / "worktrees" / name)
    folder.mkdir()
    return folder


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"gitdir:",
        b"gitdir: ",
        b"GITDIR: {admin}",
        b"\xff\xfe\x00binary",
        b"gitdir: {admin}\x00",
        b"gitdir: {repo}/.git",
        b"gitdir: {repo}/.git/worktrees",
        b"gitdir: {repo}/.git/worktrees/does-not-exist",
        b"gitdir: /",
        b"gitdir: /dev/null",
    ],
    ids=[
        "empty",
        "gitdir-colon-only",
        "gitdir-empty-path",
        "uppercase-prefix",
        "binary",
        "nul-byte",
        "main-git",
        "admin-dir-itself",
        "missing-child",
        "root",
        "dev-null",
    ],
)
def test_extra_bad_gitfile_fails_closed(tmp_path: Path, content: bytes) -> None:
    """§4.1 items 2.3, 2.4 and 5: anything but a valid gitfile pair is denied (tester role)."""
    repo, worktree, hook = _make_project(tmp_path)
    folder = _fake_worktree(tmp_path, repo, "bad")
    data = content.replace(b"{admin}", f"{repo}/.git/worktrees/wt".encode()).replace(
        b"{repo}", str(repo).encode()
    )
    _inside(tmp_path, folder / ".git").write_bytes(data)
    result = _run_hook(hook, "tester", _event("Write", f"{folder}/x/tests/acceptance/t.py"))
    _assert_blocked(result, WORKTREE_ERROR)


def test_extra_gitfile_size_limit_4096(tmp_path: Path) -> None:
    """§4.1 item 2.3: at most 4096 bytes. A real worktree whose `.git` is padded to exactly 4096
    bytes is still accepted; one byte more is denied."""
    repo, worktree, hook = _make_project(tmp_path)
    gitfile = _inside(tmp_path, worktree / ".git")
    first = gitfile.read_bytes().split(b"\n", 1)[0] + b"\n"
    target = f"{worktree}/api/x.py"

    gitfile.write_bytes(first + b"#" * (4096 - len(first)))
    assert gitfile.stat().st_size == 4096
    _assert_allowed(_run_hook(hook, "developer", _event("Write", target)))

    gitfile.write_bytes(first + b"#" * (4097 - len(first)))
    assert gitfile.stat().st_size == 4097
    _assert_blocked(_run_hook(hook, "developer", _event("Write", target)), WORKTREE_ERROR)


def test_extra_huge_gitfile_fails_closed_fast(tmp_path: Path) -> None:
    repo, worktree, hook = _make_project(tmp_path)
    gitfile = _inside(tmp_path, worktree / ".git")
    first = gitfile.read_bytes().split(b"\n", 1)[0] + b"\n"
    with gitfile.open("wb") as handle:
        handle.write(first)
        handle.truncate(64 * 1024 * 1024)  # sparse 64 MiB file
    result = _run_hook(hook, "developer", _event("Write", f"{worktree}/api/x.py"), timeout=10)
    _assert_blocked(result, WORKTREE_ERROR)


def test_extra_gitfile_as_directory_or_fifo_fails_closed(tmp_path: Path) -> None:
    """`W/.git` must be a regular file (`os.lstat`); a FIFO must not hang the hook."""
    repo, worktree, hook = _make_project(tmp_path)
    as_dir = _fake_worktree(tmp_path, repo, "gitdir-as-dir")
    _inside(tmp_path, as_dir / ".git").mkdir()
    result = _run_hook(hook, "tester", _event("Write", f"{as_dir}/x/tests/acceptance/t.py"))
    _assert_blocked(result, WORKTREE_ERROR)

    if not hasattr(os, "mkfifo"):
        pytest.skip("no FIFOs on this platform")
    fifo = _fake_worktree(tmp_path, repo, "fifo")
    os.mkfifo(_inside(tmp_path, fifo / ".git"))
    result = _run_hook(
        hook, "tester", _event("Write", f"{fifo}/x/tests/acceptance/t.py"), timeout=10
    )
    _assert_blocked(result, WORKTREE_ERROR)


def test_extra_unreadable_gitfile_fails_closed(tmp_path: Path) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root ignores file permissions")
    repo, worktree, hook = _make_project(tmp_path)
    gitfile = _inside(tmp_path, worktree / ".git")
    gitfile.chmod(0)
    try:
        result = _run_hook(hook, "developer", _event("Write", f"{worktree}/api/x.py"))
    finally:
        gitfile.chmod(0o644)
    _assert_blocked(result, WORKTREE_ERROR)


def test_extra_back_pointer_must_match(tmp_path: Path) -> None:
    """§4.1 item 2.5: a gitdir whose back pointer does not name `W/.git` is refused, even when
    `W/.git` itself is a byte-for-byte copy of a real worktree's `.git`."""
    repo, worktree, hook = _make_project(tmp_path)
    copy = _fake_worktree(tmp_path, repo, "copia")
    shutil.copyfile(worktree / ".git", _inside(tmp_path, copy / ".git"))
    result = _run_hook(hook, "developer", _event("Write", f"{copy}/api/x.py"))
    _assert_blocked(result, WORKTREE_ERROR)

    # Hard link of the real gitfile: still a regular file, still not the back pointer's target.
    hard = _fake_worktree(tmp_path, repo, "hardlink")
    os.link(worktree / ".git", _inside(tmp_path, hard / ".git"))
    result = _run_hook(hook, "developer", _event("Write", f"{hard}/api/x.py"))
    _assert_blocked(result, WORKTREE_ERROR)


def test_extra_main_git_not_a_directory_fails_closed(tmp_path: Path) -> None:
    """§4.1 item 2.2: when the main checkout is itself a worktree (`.git` file), nothing under
    `.claude/worktrees/` is accepted."""
    repo, worktree, hook = _make_project(tmp_path)
    # Run the copy of the hook that lives inside W (PROJECT_ROOT = W, whose .git is a file).
    inner_hooks = _inside(tmp_path, worktree / ".claude" / "hooks" / "guard_paths.py").parent
    inner_hooks.mkdir(parents=True)
    inner = inner_hooks / "guard_paths.py"
    shutil.copy2(HOOK, inner)
    nested = _inside(tmp_path, worktree / ".claude" / "worktrees" / "inner")
    _git("-C", worktree, "worktree", "add", "-q", nested, "-b", "inner")
    result = _run_hook(inner, "developer", _event("Write", f"{nested}/api/x.py"))
    _assert_blocked(result, WORKTREE_ERROR)

    # A session opened in W itself (scope §3.2) keeps the old behavior relative to W.
    _assert_allowed(_run_hook(inner, "developer", _event("Write", f"{worktree}/api/x.py")))
    _assert_role_denied(
        _run_hook(inner, "developer", _event("Write", f"{worktree}/docs/rules.md")),
        "role 'developer' may not write 'docs/rules.md'",
    )
    _assert_blocked(_run_hook(inner, "developer", _event("Write", f"{worktree}/.git")), GIT_ERROR)


def test_extra_stale_worktree_fails_closed(tmp_path: Path) -> None:
    """The worktree folder was deleted but `.git/worktrees/<id>` is still there."""
    repo, worktree, hook = _make_project(tmp_path)
    stale = _inside(tmp_path, repo / ".claude" / "worktrees" / "stale")
    _git("-C", repo, "worktree", "add", "-q", stale, "-b", "stale")
    assert (repo / ".git" / "worktrees" / "stale").is_dir()
    shutil.rmtree(_inside(tmp_path, stale))
    result = _run_hook(hook, "developer", _event("Write", f"{stale}/api/x.py"))
    _assert_blocked(result, WORKTREE_ERROR)


def test_extra_suffixed_admin_dir_and_unicode_name_accepted(tmp_path: Path) -> None:
    """§7: `.git/worktrees/<id>` may carry a numeric suffix; names may have spaces/accents."""
    repo, worktree, hook = _make_project(tmp_path)
    elsewhere = _inside(tmp_path, tmp_path / "elsewhere" / "dup")
    elsewhere.parent.mkdir()
    _git("-C", repo, "worktree", "add", "-q", elsewhere, "-b", "dup-a")
    dup = _inside(tmp_path, repo / ".claude" / "worktrees" / "dup")
    _git("-C", repo, "worktree", "add", "-q", dup, "-b", "dup-b")
    admin = (dup / ".git").read_text(encoding="utf-8").split("gitdir: ", 1)[1].strip()
    assert Path(admin).name != "dup", admin  # git picked a suffixed id
    _assert_allowed(_run_hook(hook, "developer", _event("Write", f"{dup}/api/x.py")))
    _assert_role_denied(
        _run_hook(hook, "developer", _event("Write", f"{dup}/docs/rules.md")),
        "role 'developer' may not write 'docs/rules.md'",
    )

    accented = _inside(tmp_path, repo / ".claude" / "worktrees" / "inspeção ç")
    _git("-C", repo, "worktree", "add", "-q", accented, "-b", "accented")
    _assert_allowed(_run_hook(hook, "developer", _event("Write", f"{accented}/api/ação.py")))
    _assert_role_denied(
        _run_hook(hook, "tester", _event("Write", f"{accented}/api/ação.py")),
        "role 'tester' may not write 'api/ação.py'",
    )

    # The worktree outside `.claude/worktrees/` stays "outside the project root" (§3.2).
    _assert_blocked(
        _run_hook(hook, "developer", _event("Write", f"{elsewhere}/api/x.py")), OUTSIDE_ERROR
    )


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("{W}/../wt/api/x.py", None),
        ("{W}/api/../../../../docs/specs/x.md", "role 'developer' may not write 'docs/specs/x.md'"),
        ("{W}/api/../../../../api/x.py", None),
        ("{W}/../comum/../wt/docs/rules.md", "role 'developer' may not write 'docs/rules.md'"),
        ("{W}/../../../../outside.py", OUTSIDE_ERROR),
        ("{W}/../x.py", WORKTREE_ERROR),
        ("{W}/api/../.git/config", GIT_ERROR),
        ("{W}/api/../.claude/worktrees/wt/api/x.py", WORKTREE_ERROR),
    ],
    ids=[
        "dotdot-back-into-wt",
        "dotdot-to-main-docs-specs",
        "dotdot-to-main-api",
        "dotdot-through-missing-folder",
        "dotdot-outside-root",
        "dotdot-to-worktrees-folder",
        "dotdot-to-git",
        "dotdot-to-nested",
    ],
)
def test_extra_dotdot_resolved_before_rules(
    project: tuple[Path, Path, Path], template: str, expected: str | None
) -> None:
    _, worktree, hook = project
    result = _run_hook(hook, "developer", _event("Write", template.format(W=worktree)))
    if expected is None:
        _assert_allowed(result)
    elif expected.startswith("role "):
        _assert_role_denied(result, expected)
    else:
        _assert_blocked(result, expected)


ROLE_PROBES = [
    "api/src/qc_api/main.py",
    "edge/tests/acceptance/test_spec_030.py",
    "tests/acceptance/test_spec_033.py",
    "reviews/SPEC-033/r1-test-report.md",
    "reviews/SPEC-033/r1-dev-report.md",
    "reviews/SPEC-033/r1-review-report.md",
    "docs/specs/SPEC-033-hook-worktree.md",
    "docs/rules.md",
    "docs/plan.md",
    "ml/notebooks/train_colab.ipynb",
    ".claude/hooks/guard_paths.py",
    ".claude/hooks/tests/acceptance/t.py",
    "infra/compose.yaml",
    ".gitignore",
]


@pytest.mark.parametrize(
    "role", ["developer", "ml-engineer", "tester", "reviewer", "security-devops", "architect"]
)
def test_extra_worktree_rights_equal_main_checkout_rights(
    project: tuple[Path, Path, Path], role: str
) -> None:
    """§2 "nada mais muda": inside a valid worktree each role gets exactly the decision it gets
    for the same relative path in the main checkout, no more and no less."""
    repo, worktree, hook = project
    for rel in ROLE_PROBES:
        main = _run_hook(hook, role, _event("Write", f"{repo}/{rel}"))
        wt = _run_hook(hook, role, _event("Write", f"{worktree}/{rel}"))
        assert main.returncode in (0, 2), (rel, main.stderr)
        assert wt.returncode == main.returncode, (role, rel, main.stderr, wt.stderr)
        assert wt.stderr == main.stderr, (role, rel, main.stderr, wt.stderr)


def test_extra_tester_acceptance_loophole_closed(tmp_path: Path) -> None:
    """§1: the tester no longer passes in any `.claude/worktrees/<x>/**/tests/acceptance/**`, but
    keeps `**/tests/acceptance/**` in the main checkout and in a real worktree."""
    repo, worktree, hook = _make_project(tmp_path)
    for target in (
        f"{repo}/.claude/worktrees/nope/tests/acceptance/t.py",
        f"{repo}/.claude/worktrees/nope/a/b/tests/acceptance/t.py",
        f"{repo}/.claude/worktrees/tests/acceptance/t.py",
        f"{worktree}/.claude/worktrees/tests/acceptance/t.py",
    ):
        _assert_blocked(_run_hook(hook, "tester", _event("Write", target)), WORKTREE_ERROR)
    for target in (
        f"{repo}/tests/acceptance/t.py",
        f"{repo}/edge/tests/acceptance/t.py",
        f"{worktree}/tests/acceptance/t.py",
        f"{worktree}/edge/tests/acceptance/t.py",
    ):
        _assert_allowed(_run_hook(hook, "tester", _event("Write", target)))
    # Lookalike prefixes are not worktree paths: judged by the role table as before.
    for rel in (".claude/worktreesx/a/tests/acceptance/t.py", "x/.claude/worktrees/a/t.py"):
        main = _run_hook(hook, "tester", _event("Write", f"{repo}/{rel}"))
        assert WORKTREE_ERROR not in main.stderr.decode("utf-8"), (rel, main.stderr)
