"""Acceptance tests for SPEC-001 (repository setup and tooling).

Written by the tester from the SPEC acceptance criteria (CA-03 to CA-20).
CA-01, CA-02 and CA-21 to CA-23 are manual and recorded in the test report.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "guard_paths.py"
LOCK = ROOT / "uv.lock"

MEMBERS = {
    "packages/contracts": "qc-contracts",
    "packages/preprocess": "qc-preprocess",
    "api": "qc-api",
    "edge": "qc-edge",
    "dashboard": "qc-dashboard",
    "ml": "qc-ml",
}

FORBIDDEN_LIGHT = {"torch", "torchvision", "timm", "onnxruntime"}


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


def _run_db_smoke(extra_args: list[str], **env: str | None) -> subprocess.CompletedProcess[str]:
    """Run pytest only on tests/test_db_smoke.py (never the whole suite)."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *extra_args],
        cwd=ROOT,
        env=_clean_env(**env),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _hook(
    stdin: str | bytes,
    *args: str,
    hook: Path = HOOK,
    python: str = sys.executable,
) -> subprocess.CompletedProcess[bytes]:
    data = stdin.encode("utf-8") if isinstance(stdin, str) else stdin
    return subprocess.run(
        [python, str(hook), *args],
        input=data,
        capture_output=True,
        timeout=30,
        cwd=hook.parent,
    )


def _event(path: str, tool: str = "Write", cwd: str | None = None) -> str:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    event: dict[str, object] = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {key: path},
    }
    if cwd is not None:
        event["cwd"] = cwd
    return json.dumps(event)


def _load_lock() -> dict:
    with LOCK.open("rb") as fh:
        return tomllib.load(fh)


def _independent_closure(lock: dict, root: str, extras: tuple[str, ...] = ()) -> dict[str, list]:
    """Tester's own oracle: BFS over runtime deps in uv.lock, following requested extras."""
    by_name: dict[str, list[dict]] = {}
    for pkg in lock["package"]:
        by_name.setdefault(pkg["name"], []).append(pkg)

    def deps_of(name: str, wanted_extras: tuple[str, ...]) -> list[tuple[str, tuple[str, ...]]]:
        out: list[tuple[str, tuple[str, ...]]] = []
        for pkg in by_name.get(name, []):
            for dep in pkg.get("dependencies", []):
                out.append((dep["name"], tuple(dep.get("extra", []))))
            optional = pkg.get("optional-dependencies", {})
            for extra in wanted_extras:
                for dep in optional.get(extra, []):
                    out.append((dep["name"], tuple(dep.get("extra", []))))
        return out

    paths: dict[str, list] = {root: [root]}
    queue: list[tuple[str, tuple[str, ...]]] = [(root, extras)]
    seen: set[tuple[str, tuple[str, ...]]] = set()
    while queue:
        name, ex = queue.pop(0)
        if (name, ex) in seen:
            continue
        seen.add((name, ex))
        for dep, dep_extras in deps_of(name, ex):
            if dep not in paths:
                paths[dep] = [*paths[name], dep]
            queue.append((dep, dep_extras))
    return paths


def _load_lockgraph():
    path = ROOT / "tests" / "lockgraph.py"
    spec = importlib.util.spec_from_file_location("spec001_acceptance_lockgraph", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


# --------------------------------------------------------------------------- CA-03


def test_ca03_ruff_check_and_format_are_clean() -> None:
    check = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    fmt = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert fmt.returncode == 0, fmt.stdout + fmt.stderr


# --------------------------------------------------------------------------- CA-04..06


@pytest.mark.db
def test_ca04_db_smoke_passes_with_database_url() -> None:
    url = os.environ["TEST_DATABASE_URL"]
    result = _run_db_smoke(["-q", "-rs", "tests/test_db_smoke.py"], TEST_DATABASE_URL=url)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "1 passed" in out, out
    assert "skipped" not in out.lower(), out


def test_ca05_db_smoke_skipped_without_url_outside_ci() -> None:
    result = _run_db_smoke(["-q", "-rs", "tests/test_db_smoke.py"], TEST_DATABASE_URL=None, CI=None)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "1 skipped" in out, out
    assert "TEST_DATABASE_URL not set" in out, out
    assert "passed" not in out, out


def test_ca06_ci_without_url_fails_session() -> None:
    result = _run_db_smoke(["-q", "tests/test_db_smoke.py"], TEST_DATABASE_URL=None, CI="true")
    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    assert "TEST_DATABASE_URL is required when CI=true" in out, out
    assert "passed" not in out, out


# --------------------------------------------------------------------------- CA-07..09


def test_ca07_light_packages_have_no_ml_runtime_and_synthetic_path_is_reported() -> None:
    lockgraph = _load_lockgraph()
    lock = lockgraph.load_lock(LOCK)

    for root in ("qc-api", "qc-dashboard"):
        # Author's function on the real lock.
        found = lockgraph.find_forbidden(lock, root)
        assert not found, f"{root} reaches forbidden packages: {found}"
        # Independent oracle on the real lock (guards against a closure that walks nothing).
        mine = _independent_closure(_load_lock(), root)
        assert len(mine) > 10, f"oracle closure of {root} is suspiciously small"
        bad = {n for n in mine if n in FORBIDDEN_LIGHT or n.startswith("onnxruntime")}
        assert not bad, {n: mine[n] for n in bad}
        author = lockgraph.dependency_closure(lock, root)
        assert set(mine) <= set(author) | {root}, set(mine) - set(author)

    synthetic = {
        "version": 1,
        "package": [
            {
                "name": "qc-api",
                "version": "0.0.0",
                "source": {"editable": "api"},
                "dependencies": [{"name": "pkg-x"}],
            },
            {
                "name": "pkg-x",
                "version": "1.0",
                "source": {"registry": "https://pypi.org/simple"},
                "dependencies": [{"name": "torch"}],
            },
            {
                "name": "torch",
                "version": "2.0",
                "source": {"registry": "https://pypi.org/simple"},
            },
        ],
    }
    found = lockgraph.find_forbidden(synthetic, "qc-api")
    assert "torch" in found, found
    assert lockgraph.format_path(found["torch"]) == "qc-api → pkg-x → torch"


def test_ca08_ml_base_has_no_torch_and_train_extra_declares_stack() -> None:
    lockgraph = _load_lockgraph()
    lock = lockgraph.load_lock(LOCK)
    author = lockgraph.dependency_closure(lock, "qc-ml")
    mine = _independent_closure(_load_lock(), "qc-ml")
    for closure in (author, mine):
        assert "torch" not in closure
        assert "timm" not in closure

    train = {"torch", "torchvision", "timm", "onnx", "coral-pytorch"}

    pyproject = tomllib.loads((ROOT / "ml" / "pyproject.toml").read_text(encoding="utf-8"))
    declared = pyproject["project"]["optional-dependencies"]["train"]
    names = {
        d.split(";")[0].split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip().lower()
        for d in declared
    }
    assert train <= names, names

    ml_entries = [p for p in _load_lock()["package"] if p["name"] == "qc-ml"]
    assert len(ml_entries) == 1
    locked_train = {d["name"] for d in ml_entries[0]["optional-dependencies"]["train"]}
    assert train <= locked_train, locked_train


def test_ca09_python_312_everywhere() -> None:
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"
    files = [ROOT / "pyproject.toml"] + [ROOT / m / "pyproject.toml" for m in MEMBERS]
    assert len(files) == 7
    for f in files:
        data = tomllib.loads(f.read_text(encoding="utf-8"))
        assert data["project"]["requires-python"] == ">=3.12,<3.13", f


# --------------------------------------------------------------------------- CA-10


def test_ca10_ci_workflow_shape() -> None:
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    triggers = wf.get("on", wf.get(True))
    assert isinstance(triggers, dict), triggers
    assert "pull_request" in triggers
    assert triggers["push"]["branches"] == ["main"]

    jobs = wf["jobs"]
    assert len(jobs) == 1
    job = next(iter(jobs.values()))
    images = [svc.get("image") for svc in job.get("services", {}).values()]
    assert "postgres:16" in images

    env = {**wf.get("env", {}), **job.get("env", {})}
    assert "TEST_DATABASE_URL" in env

    runs = [step.get("run", "").strip() for step in job["steps"]]
    expected = [
        "uv sync --all-packages --frozen",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run pytest -q",
    ]
    positions = []
    for cmd in expected:
        matches = [i for i, r in enumerate(runs) if cmd in r.splitlines()]
        assert matches, f"step {cmd!r} missing; runs={runs}"
        positions.append(matches[0])
    assert positions == sorted(positions), list(zip(expected, positions, strict=True))


# --------------------------------------------------------------------------- CA-11..16


def test_ca11_tester_denied_on_production_code_with_message() -> None:
    event = json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": f"{ROOT}/api/src/qc_api/main.py"}}
    )
    result = _hook(event, "--role", "tester")
    assert result.returncode == 2
    stderr = result.stderr.decode("utf-8")
    assert "role 'tester' may not write 'api/src/qc_api/main.py'" in stderr, stderr


CA12_TABLE = [
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


@pytest.mark.parametrize(("role", "rel", "code"), CA12_TABLE)
def test_ca12_role_table(role: str, rel: str, code: int) -> None:
    result = _hook(_event(f"{ROOT}/{rel}"), "--role", role)
    assert result.returncode == code, result.stderr.decode("utf-8", "replace")
    if code == 0:
        assert result.stdout == b"" and result.stderr == b""
    else:
        msg = f"guard_paths: role '{role}' may not write '{rel}' (SPEC-001, R-07)"
        assert msg in result.stderr.decode("utf-8"), result.stderr


@pytest.mark.parametrize(
    "path",
    [f"{ROOT}/api/../docs/rules.md", "/tmp/x.py", f"{ROOT}/.git/config"],
    ids=["dotdot", "outside-root", "dot-git"],
)
def test_ca13_traversal_outside_and_git_are_denied(path: str) -> None:
    result = _hook(_event(path), "--role", "developer")
    assert result.returncode == 2, result.stderr


@pytest.mark.parametrize(
    ("stdin", "args"),
    [
        ("{not json", ("--role", "developer")),
        (json.dumps({"tool_name": "Write", "tool_input": {}}), ("--role", "developer")),
        (json.dumps({"tool_name": "Write"}), ("--role", "developer")),
        (_event(f"{ROOT}/api/src/qc_api/main.py"), ("--role", "admin")),
        (_event(f"{ROOT}/api/src/qc_api/main.py"), ()),
    ],
    ids=["invalid-json", "no-path-field", "no-tool-input", "role-admin", "role-missing"],
)
def test_ca14_bad_input_fails_closed(stdin: str, args: tuple[str, ...]) -> None:
    result = _hook(stdin, *args)
    assert result.returncode == 2, (result.returncode, result.stderr)


@pytest.mark.parametrize(("role", "code"), [("ml-engineer", 0), ("developer", 2)])
def test_ca15_notebook_edit_uses_notebook_path(role: str, code: int) -> None:
    event = _event(f"{ROOT}/ml/notebooks/train.ipynb", tool="NotebookEdit")
    result = _hook(event, "--role", role)
    assert result.returncode == code, result.stderr


def test_ca16_root_with_space_and_accent(tmp_path: Path) -> None:
    proj = tmp_path / "Área de trabalho" / "proj"
    hooks = proj / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    copied = hooks / "guard_paths.py"
    shutil.copy2(HOOK, copied)

    allowed = proj / "api" / "src" / "qc_api" / "main.py"
    result = _hook(_event(str(allowed)), "--role", "developer", hook=copied)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")

    # Sanity: the copied hook still denies inside that root, with the relative path.
    denied = _hook(_event(str(allowed)), "--role", "tester", hook=copied)
    assert denied.returncode == 2
    assert "may not write 'api/src/qc_api/main.py'" in denied.stderr.decode("utf-8")


# --------------------------------------------------------------------------- CA-17


def test_ca17_hook_imports_only_stdlib() -> None:
    tree = ast.parse(HOOK.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in hook"
            assert node.module is not None
            modules.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "__import__":
            pytest.fail("dynamic __import__ in hook")
    assert modules, "hook imports nothing?"
    non_std = modules - set(sys.stdlib_module_names) - {"__future__"}
    assert not non_std, non_std


# --------------------------------------------------------------------------- CA-18..20

AGENTS = {
    "architect": (
        "Arquiteto do PartQC. Use para criar ou alterar SPECs e ADRs, quebrar itens do PRD em "
        "entregas, resolver SPEC_ISSUE levantado no loop e manter a consistência entre PRD, "
        "architecture.md, ADRs e SPECs. Não escreve código.",
        "Read, Grep, Glob, Write, Edit, WebSearch, WebFetch",
    ),
    "developer": (
        "Desenvolvedor do PartQC. Use para implementar uma SPEC com status Ready nas áreas "
        "packages/, api/, edge/, dashboard/, scripts/ e infra/ (exceto ml/ e a SPEC de deploy). "
        "Recebe o caminho da SPEC e o número da rodada; entrega código, testes unitários "
        "próprios e o dev-report.",
        "Read, Grep, Glob, Write, Edit, Bash",
    ),
    "ml-engineer": (
        "Engenheiro de ML do PartQC. Use para implementar SPECs da pasta ml/ (manifest, split "
        "por item_id, augmentations, treino com duas saídas, avaliação, export ONNX, teste de "
        "paridade, relatórios de métricas) e para analisar resultados de treino. Recebe o "
        "caminho da SPEC e o número da rodada.",
        "Read, Grep, Glob, Write, Edit, Bash, NotebookEdit, WebSearch, WebFetch",
    ),
    "reviewer": (
        "Revisor de código do PartQC. Use depois de um test-report PASS para revisar o diff de "
        "uma SPEC contra a SPEC, os ADRs, as regras inegociáveis e o reviews/checklist.md. "
        "Emite APPROVED ou CHANGES_REQUESTED. Também faz o portão de segurança quando o autor "
        "da SPEC foi o security-devops. Nunca edita código.",
        "Read, Grep, Glob, Bash, Write",
    ),
    "security-devops": (
        "Segurança e DevOps do PartQC. Use (1) como portão de segurança para SPECs com tag "
        "security ou deploy, depois do reviewer, emitindo security-report PASS/FAIL; (2) como "
        "autor da SPEC-015 (deploy em Render, Supabase, Streamlit Community Cloud e keep-alive) "
        "e da manutenção de docs/deployment-plan.md.",
        "Read, Grep, Glob, Bash, Write, Edit, WebSearch, WebFetch",
    ),
    "tester": (
        "Testador do PartQC. Use depois que o autor (developer, ml-engineer ou security-devops) "
        "concluir uma rodada de uma SPEC. Escreve testes de aceite a partir dos critérios da "
        "SPEC, roda a suíte inteira, faz testes exploratórios e emite o test-report PASS/FAIL. "
        "Nunca altera código de produção.",
        "Read, Grep, Glob, Write, Edit, Bash",
    ),
}


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_ca18_agent_frontmatter_keeps_fields_and_has_hook(name: str) -> None:
    fm = _frontmatter(ROOT / ".claude" / "agents" / f"{name}.md")
    description, tools = AGENTS[name]
    assert fm["name"] == name
    assert fm["description"] == description
    assert fm["tools"] == tools
    assert fm["model"] == "inherit"

    entry = fm["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Write|Edit|MultiEdit|NotebookEdit"
    commands = [h["command"] for h in entry["hooks"] if h.get("type") == "command"]
    assert any(f"guard_paths.py --role {name}" in c.replace('"', "") for c in commands), commands
    assert any(f'guard_paths.py" --role {name}' in c for c in commands), commands


def test_ca19_settings_json() -> None:
    with (ROOT / ".claude" / "settings.json").open(encoding="utf-8") as fh:
        settings = json.load(fh)
    assert "Bash(uv run *)" in settings["permissions"]["allow"]
    assert "hooks" not in settings


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


def test_ca20_env_example() -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/partqc_test" in lines

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
    assert "<password>" in values["DATABASE_URL"], "DATABASE_URL must keep a placeholder"
