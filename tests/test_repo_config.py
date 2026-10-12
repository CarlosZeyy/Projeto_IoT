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
    assert "TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test" in lines


@pytest.mark.parametrize("name", [".env.example", "README.md"])
def test_no_postgres_password_material(name: str) -> None:
    """SPEC-022 §4.2: no password URL nor password variable, not even in comments."""
    # Built at run time so that this test file does not contain the sequences itself.
    forbidden = ["POSTGRES_" + "PASSWORD", "postgres:" + "postgres@"]
    text = (ROOT / name).read_text(encoding="utf-8")
    assert [s for s in forbidden if s in text] == []


def test_readme_local_postgres_is_trust_on_loopback() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert (
        "docker run -d --name partqc-pg -e POSTGRES_HOST_AUTH_METHOD=trust "
        "-e POSTGRES_DB=partqc_test -p 127.0.0.1:55432:5432 postgres:16"
    ) in text
    assert "export TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test" in text
    assert "docker rm -f partqc-pg" in text


def test_readme_workspace_trust_note_before_limitation() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("### Hook de guarda de caminhos (R-07)")
    section = text[start:]
    trust = section.index("**Workspace trust:**")
    assert trust < section.index("**Limitação:**")
    assert "uma sessão `claude -p` não conta como aceite" in section


def test_env_example_has_no_secret_values() -> None:
    secret_like = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if secret_like.search(name):
            assert value == "", f"{name} must be empty in .env.example"


def test_architect_commits_section_names_the_orchestrator() -> None:
    """SPEC-022 §4.3: the architect has no shell, so the orchestrator commits its files."""
    text = (ROOT / ".claude/agents/architect.md").read_text(encoding="utf-8")
    section = text.split("\n## Commits\n", 1)[1].split("\n## ", 1)[0].strip()
    assert section.startswith("Você não tem shell (`Bash`), então não faz commits.")
    assert "**orquestrador**" in section
    assert "`Agent: architect`" in section
    assert "Todo commit seu" not in section


def test_reviews_readme_documents_architect_commits() -> None:
    text = (ROOT / "reviews/README.md").read_text(encoding="utf-8")
    paragraphs = text.split("\n\n")
    tracking = next(i for i, p in enumerate(paragraphs) if p.startswith("**Rastreio de papéis:**"))
    assert paragraphs[tracking + 1].startswith("**Commits do architect:**")
    assert "`Agent: orchestrator`" in paragraphs[tracking + 1]
