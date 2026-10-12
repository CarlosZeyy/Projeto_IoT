"""Policy of the `db` marker, exercised through a pytest subprocess (SPEC-001 §4.3).

Only ``tests/test_db_smoke.py`` is run in the subprocess, never the whole suite (no recursion).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_smoke(env_updates: dict[str, str | None]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    for key, value in env_updates.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-rs",
            "-p",
            "no:cacheprovider",
            "tests/test_db_smoke.py",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_db_tests_are_skipped_without_url_outside_ci() -> None:
    result = _run_smoke({"TEST_DATABASE_URL": None, "CI": None})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 skipped" in result.stdout
    assert "TEST_DATABASE_URL not set" in result.stdout


def test_empty_url_counts_as_not_set() -> None:
    result = _run_smoke({"TEST_DATABASE_URL": "", "CI": None})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TEST_DATABASE_URL not set" in result.stdout


def test_ci_without_url_fails_before_running_tests() -> None:
    result = _run_smoke({"TEST_DATABASE_URL": None, "CI": "true"})
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "TEST_DATABASE_URL is required when CI=true" in output
    assert "passed" not in output
    assert "skipped" not in output


def test_conftest_does_not_read_dotenv() -> None:
    source = (ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "dotenv" not in source
    assert '.env"' not in source and ".env'" not in source
