"""Claude Code config and `.env.example` delivered by SPEC-001 (§4.3, §4.6)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ["architect", "developer", "ml-engineer", "reviewer", "security-devops", "tester"]


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


@pytest.mark.parametrize("agent", AGENTS)
def test_agent_frontmatter_has_guard_hook(agent: str) -> None:
    front = _frontmatter(ROOT / ".claude/agents" / f"{agent}.md")
    assert front["name"] == agent
    for key in ("description", "tools", "model"):
        assert front[key], key
    assert "Agent" not in [t.strip() for t in str(front["tools"]).split(",")]
    entry = front["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Write|Edit|MultiEdit|NotebookEdit"
    (hook,) = entry["hooks"]
    assert hook["type"] == "command"
    assert f'guard_paths.py" --role {agent}' in hook["command"]
    assert "$CLAUDE_PROJECT_DIR" in hook["command"]


def test_settings_json() -> None:
    settings = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
    assert "hooks" not in settings
    assert set(settings["permissions"]["allow"]) == {
        "Bash(uv run *)",
        "Bash(uv sync *)",
        "Bash(uv tree *)",
        "Bash(git status)",
        "Bash(git diff *)",
        "Bash(git log *)",
    }
    assert settings["permissions"]["deny"] == ["Read(./.env)"]


def test_env_example_has_test_database_block() -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "# ---------- testes locais ----------" in lines
    assert "TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/partqc_test" in lines


def test_env_example_has_no_secret_values() -> None:
    secret_like = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if secret_like.search(name):
            assert value == "", f"{name} must be empty in .env.example"
