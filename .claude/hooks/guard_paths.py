#!/usr/bin/env python3
"""PreToolUse hook: path guard per subagent role (SPEC-001 §4.6, R-07).

Usage (from the `hooks:` field of each `.claude/agents/*.md`):

    python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_paths.py" --role <role>

Reads the PreToolUse event JSON from stdin, picks the path field from ``tool_name``
(SPEC-022 §4.1, case-sensitive): ``tool_input.file_path`` for Write, Edit and MultiEdit,
``tool_input.notebook_path`` for NotebookEdit; then decides whether ``<role>`` may write there.

* allowed -> exit 0, no output;
* denied  -> exit 2, reason on stderr (Claude Code shows it to the agent and blocks the call).

It fails closed (exit 2) on invalid JSON, missing/unknown role, a path outside the project root,
a path inside ``.git/`` and on every ambiguous event: no ``tool_input`` object, no ``tool_name``
string, a ``tool_name`` outside the map above, both ``file_path`` and ``notebook_path`` keys
present in ``tool_input`` (whatever their values), or the expected field missing, not a string,
empty or only whitespace.

KNOWN LIMITATION: this hook only sees Write/Edit/MultiEdit/NotebookEdit. Writes made through the
Bash tool (``echo > file``, ``uv lock``, ``git`` ...) are NOT intercepted. R-07 is still checked
by the reviewer with ``git log`` and the ``Agent:`` trailers (reviews/checklist.md §2).

GIT WORKTREES (SPEC-033 §4.1): Claude Code keeps ``$CLAUDE_PROJECT_DIR`` on the main checkout
when a session runs in a worktree under ``.claude/worktrees/<name>/``. A target there is judged
with its path relative to the root of that worktree, but only when ``<name>`` is a git worktree
of this repository: the main ``.git`` is a directory, ``<name>/.git`` is a small regular UTF-8
file (not a symlink) whose first line is ``gitdir: <dir>``, ``<dir>`` resolves to a direct child
of ``.git/worktrees/`` and that child's ``gitdir`` file points back to ``<name>/.git``. Any other
path under ``.claude/worktrees/`` (a plain folder, a nested clone, a worktree of another
repository, a fake or symlinked ``.git``, the worktree root itself, a worktree inside a worktree)
and any read error while checking it fail closed with "path is inside .claude/worktrees/ but not
inside a git worktree of this repository". No ``git`` executable and no subprocess are used.

Standard library only and compatible with Python >= 3.10: it runs with the system ``python3``,
without uv, so that it works before ``.venv`` exists (a missing interpreter would fail open).
"""

import argparse
import contextlib
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ACCEPTANCE = "**/tests/acceptance/**"

# Each role: "allow" globs, and "deny" rules as (glob, exceptions). A path is writable when it
# matches some "allow" glob and no "deny" rule, where a deny rule does not apply to paths that
# match one of its own exceptions. Deny always wins over allow.
ROLES: dict[str, dict[str, tuple]] = {
    "developer": {
        "allow": ("**",),
        "deny": (
            (ACCEPTANCE, ()),
            ("docs/specs/**", ()),
            ("docs/adr/**", ()),
            ("docs/rules.md", ()),
            ("ml/**", ()),
            (".claude/**", ()),
            ("reviews/**", ("reviews/SPEC-*/r*-dev-report.md",)),
        ),
    },
    "ml-engineer": {
        "allow": ("ml/**", "reviews/SPEC-*/r*-dev-report.md"),
        "deny": ((ACCEPTANCE, ()),),
    },
    "tester": {
        "allow": (ACCEPTANCE, "reviews/SPEC-*/r*-test-report.md"),
        "deny": (),
    },
    "reviewer": {
        "allow": ("reviews/SPEC-*/r*-review-report.md", "reviews/SPEC-*/r*-security-report.md"),
        "deny": (),
    },
    "security-devops": {
        "allow": (
            "infra/**",
            ".github/**",
            "dashboard/requirements.txt",
            ".streamlit/**",
            "scripts/smoke_test.py",
            ".env.example",
            ".gitignore",
            "pyproject.toml",
            "uv.lock",
            "docs/deployment-plan.md",
            "reviews/SPEC-*/r*-dev-report.md",
            "reviews/SPEC-*/r*-security-report.md",
        ),
        "deny": ((ACCEPTANCE, ()),),
    },
    "architect": {
        "allow": ("docs/**",),
        "deny": (("docs/rules.md", ()),),
    },
}


class GuardError(Exception):
    """Any condition that must block the tool call (fail closed)."""


def _segment_regex(segment: str) -> "re.Pattern[str]":
    """Compile one glob segment: `*` matches any run of characters except `/`."""
    parts = (re.escape(chunk) for chunk in segment.split("*"))
    return re.compile("[^/]*".join(parts))


def _match_segments(pattern: list, path: list) -> bool:
    if not pattern:
        return not path
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        # `**` matches zero or more whole segments.
        return any(_match_segments(rest, path[i:]) for i in range(len(path) + 1))
    if not path:
        return False
    return _segment_regex(head).fullmatch(path[0]) is not None and _match_segments(rest, path[1:])


def glob_match(pattern: str, rel_path: str) -> bool:
    """Match a POSIX path relative to the project root against a glob pattern.

    `*` matches inside a single segment; `**` matches zero or more whole segments.
    """
    return _match_segments(pattern.split("/"), rel_path.split("/"))


def is_allowed(role: str, rel_path: str) -> bool:
    rules = ROLES[role]
    if not any(glob_match(p, rel_path) for p in rules["allow"]):
        return False
    for pattern, exceptions in rules["deny"]:
        if glob_match(pattern, rel_path) and not any(glob_match(e, rel_path) for e in exceptions):
            return False
    return True


# Path field read for each tool (SPEC-022 §4.1). Exact, case-sensitive names: any other
# tool_name is denied.
PATH_FIELD_BY_TOOL: dict[str, str] = {
    "Write": "file_path",
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
}
# The field of the other kind of tool: none of the four tools sends it, so its key being present
# (with any value, even null or "") makes the event malformed.
OTHER_PATH_FIELD: dict[str, str] = {
    "file_path": "notebook_path",
    "notebook_path": "file_path",
}


def target_path(event: object) -> str:
    """Extract the raw target path from a PreToolUse event (SPEC-022 §4.1).

    Checks run in this order and the first failure raises GuardError: event not an object,
    no ``tool_input`` object, no ``tool_name`` string, unknown ``tool_name``, both path keys
    present, expected field missing/not a string/empty/whitespace.
    """
    if not isinstance(event, dict):
        raise GuardError("event is not a JSON object")
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        raise GuardError("event has no tool_input object")
    tool_name = event.get("tool_name")
    if not isinstance(tool_name, str):
        raise GuardError("event has no tool_name string")
    field = PATH_FIELD_BY_TOOL.get(tool_name)
    if field is None:
        raise GuardError(f"unknown tool_name {tool_name!r}")
    if OTHER_PATH_FIELD[field] in tool_input:
        raise GuardError("tool_input has both file_path and notebook_path")
    value = tool_input.get(field)
    if not isinstance(value, str) or not value.strip():
        raise GuardError(f"tool_input.{field} missing or empty for {tool_name}")
    return value


# Git worktrees of Claude Code sessions live in `.claude/worktrees/<name>/` (SPEC-033 §4.1).
WORKTREES_PREFIX = (".claude", "worktrees")
WORKTREE_ERROR = (
    "path is inside .claude/worktrees/ but not inside a git worktree of this repository"
)
GITFILE_MAX_BYTES = 4096


def _worktree_relative(rel_parts: list, real_root: str) -> str:
    """Map `.claude/worktrees/<name>/<rest>` to `<rest>` when `<name>` is a git worktree of root.

    Structural check of what `git worktree add` writes (SPEC-033 §4.1, conditions 1 to 5); any
    failed condition, nested worktree or read error raises GuardError (fail closed).
    """

    def read_first_line(file_path: str) -> str:
        # Regular file, not a symlink, at most GITFILE_MAX_BYTES, strict UTF-8.
        info = os.lstat(file_path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > GITFILE_MAX_BYTES:
            raise GuardError(WORKTREE_ERROR)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        with open(file_path, "rb", opener=lambda p, f: os.open(p, f | nofollow)) as handle:
            data = handle.read(GITFILE_MAX_BYTES + 1)
        if len(data) > GITFILE_MAX_BYTES:
            raise GuardError(WORKTREE_ERROR)
        return data.decode("utf-8").split("\n", 1)[0].rstrip("\r")

    if len(rel_parts) < 4:  # 1. something after `<name>`
        raise GuardError(WORKTREE_ERROR)
    worktree = os.path.join(real_root, *WORKTREES_PREFIX, rel_parts[2])
    try:
        # 2. the main checkout has a `.git` directory
        if not os.path.isdir(os.path.join(real_root, ".git")):
            raise GuardError(WORKTREE_ERROR)
        # 3. `<name>/.git` is a gitfile: `gitdir: <dir>`
        dot_git = os.path.join(worktree, ".git")
        line = read_first_line(dot_git)
        if not line.startswith("gitdir: ") or not line[len("gitdir: ") :]:
            raise GuardError(WORKTREE_ERROR)
        # 4. `<dir>` (relative to the worktree) is a direct child of `.git/worktrees/`
        gitdir = os.path.realpath(os.path.join(worktree, line[len("gitdir: ") :]))
        admin_dir = os.path.realpath(os.path.join(real_root, ".git", "worktrees"))
        if os.path.dirname(gitdir) != admin_dir or not os.path.isdir(gitdir):
            raise GuardError(WORKTREE_ERROR)
        # 5. `<dir>/gitdir` points back to `<name>/.git` (relative to `<dir>` if not absolute)
        back = read_first_line(os.path.join(gitdir, "gitdir"))
        if not back or os.path.realpath(os.path.join(gitdir, back)) != os.path.realpath(dot_git):
            raise GuardError(WORKTREE_ERROR)
    except (OSError, ValueError) as exc:  # ValueError includes UnicodeDecodeError
        raise GuardError(WORKTREE_ERROR) from exc
    rest = rel_parts[3:]
    if tuple(rest[:2]) == WORKTREES_PREFIX:  # 4.1 item 4: no worktree inside a worktree
        raise GuardError(WORKTREE_ERROR)
    return "/".join(rest)


def relative_to_root(raw_path: str, cwd: object, root: Path = PROJECT_ROOT) -> str:
    """Resolve the target (`..`, symlinks) and return it as a POSIX path relative to root.

    A target inside a git worktree in `.claude/worktrees/<name>/` is returned relative to that
    worktree's root (SPEC-033 §4.1); any other path under `.claude/worktrees/` is denied.
    """
    if "\x00" in raw_path:
        raise GuardError("path contains a NUL byte")
    path = raw_path
    if not os.path.isabs(path):
        if not isinstance(cwd, str) or not os.path.isabs(cwd):
            raise GuardError("relative path without an absolute cwd in the event")
        path = os.path.join(cwd, path)
    real = os.path.realpath(path)
    real_root = os.path.realpath(root)
    try:
        rel = os.path.relpath(real, real_root)
    except ValueError as exc:  # different drives on Windows
        raise GuardError("path is outside the project root") from exc
    rel_posix = PurePosixPath(*Path(rel).parts).as_posix()
    if rel_posix == "." or rel_posix == ".." or rel_posix.startswith("../"):
        raise GuardError("path is outside the project root")
    rel_parts = rel_posix.split("/")
    if tuple(rel_parts[:2]) == WORKTREES_PREFIX:
        rel_posix = _worktree_relative(rel_parts, real_root)
    if ".git" in rel_posix.split("/"):
        raise GuardError("path is inside .git/")
    return rel_posix


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise GuardError(f"invalid arguments: {message}")


def _parse_role(argv: list) -> str:
    parser = _Parser(prog="guard_paths.py", add_help=False)
    parser.add_argument("--role", required=True)
    args = parser.parse_args(argv)
    if args.role not in ROLES:
        raise GuardError(f"unknown role {args.role!r}")
    return args.role


def _deny(message: str) -> int:
    line = f"guard_paths: {message} (SPEC-001, R-07)\n"
    # Bytes in UTF-8: a non-UTF-8 locale must not crash the hook (a crash would fail open).
    with contextlib.suppress(OSError, ValueError):
        sys.stderr.buffer.write(line.encode("utf-8", "backslashreplace"))
        sys.stderr.flush()
    return 2


def main(argv: list | None = None) -> int:
    try:
        role = _parse_role(sys.argv[1:] if argv is None else argv)
        try:
            event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GuardError("stdin is not valid JSON") from exc
        raw = target_path(event)
        rel = relative_to_root(raw, event.get("cwd"))
    except GuardError as exc:
        return _deny(f"blocked: {exc}")
    except Exception as exc:  # any unexpected error must fail closed
        return _deny(f"blocked: unexpected error {type(exc).__name__}")
    if is_allowed(role, rel):
        return 0
    return _deny(f"role '{role}' may not write '{rel}'")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:  # fail closed even on KeyboardInterrupt or a bug in main()
        sys.exit(2)
