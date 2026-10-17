"""Shape of `.github/workflows/ci.yml` (SPEC-001 §4.4)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_GATE = (
    'uv run pytest api/tests -q -m "not db" --cov=qc_api.services'
    " --cov-report=term-missing --cov-fail-under=80"
)
EXPECTED_ORDER = [
    "uv sync --all-packages --frozen",
    "uv run ruff check .",
    "uv run ruff format --check .",
    "uv run pytest -q",
]


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def job(workflow: dict) -> dict:
    jobs = workflow["jobs"]
    assert len(jobs) == 1
    return next(iter(jobs.values()))


def test_triggers(workflow: dict) -> None:
    # YAML 1.1 reads a bare `on` key as boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert "pull_request" in triggers
    assert triggers["push"]["branches"] == ["main"]


def test_runner_and_postgres_service(job: dict) -> None:
    assert job["runs-on"] == "ubuntu-latest"
    services = list(job["services"].values())
    assert [s["image"] for s in services] == ["postgres:16"]
    service = services[0]
    assert service["env"]["POSTGRES_DB"] == "partqc_test"
    assert "pg_isready" in service["options"]


def test_postgres_service_uses_trust_without_password(job: dict) -> None:
    """SPEC-022 §4.2: the CI Postgres runs in `trust`, with no password key at all."""
    (service,) = job["services"].values()
    env = service["env"]
    assert env["POSTGRES_HOST_AUTH_METHOD"] == "trust"
    assert not [key for key in env if "PASSWORD" in key.upper()]


def test_ci_file_has_no_password_material() -> None:
    # Built at run time so that this test file does not contain the sequences itself.
    forbidden = ["POSTGRES_" + "PASSWORD", "postgres:" + "postgres@"]
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert [s for s in forbidden if s in text] == []


def test_env(job: dict) -> None:
    assert job["env"]["TEST_DATABASE_URL"] == "postgresql://postgres@localhost:5432/partqc_test"
    assert str(job["env"]["UV_FROZEN"]) == "1"


def test_steps_in_order(job: dict) -> None:
    runs = [step["run"].strip() for step in job["steps"] if "run" in step]
    positions = [runs.index(cmd) for cmd in EXPECTED_ORDER]
    assert positions == sorted(positions)
    assert runs.index("uv python install 3.12") < positions[0]


def test_services_coverage_gate_runs_after_pytest(job: dict) -> None:
    """SPEC-006 section 4.3 (RNF-09): coverage of ``qc_api.services`` >= 80%, without database."""
    runs = [step["run"].strip() for step in job["steps"] if "run" in step]
    assert runs.count(COVERAGE_GATE) == 1
    assert runs.index(COVERAGE_GATE) > runs.index("uv run pytest -q")


def test_actions_pinned_and_no_secrets(job: dict) -> None:
    uses = [step["uses"] for step in job["steps"] if "uses" in step]
    assert uses[0].startswith("actions/checkout@v")
    assert uses[1].startswith("astral-sh/setup-uv@v")
    assert all("@main" not in u and "@master" not in u for u in uses)
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "secrets." not in text
