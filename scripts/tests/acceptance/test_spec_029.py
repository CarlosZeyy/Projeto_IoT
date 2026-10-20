"""Acceptance tests for SPEC-029 section 4.4 (simulator author test: the IDNA case).

Written by the tester from the SPEC acceptance criteria (black box). CA-05 runs pytest in a
subprocess with an explicit file path only (``scripts/tests/test_simulate.py``, which runs no
pytest in a subprocess), without the database and without the variables that would leak the
outer session into it (``docs/architecture.md`` section 10). The ``test_extra_*`` test checks
the premise of the case (``raw_host`` vs ``.host`` under the ``idna`` codec) without the network.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[3]
AUTHOR_TESTS = ROOT / "scripts" / "tests" / "test_simulate.py"
SELECTION = "visible_ascii_api_url_still_sends and xn--1-zhc"
IDNA_URL = "https://xn--1-zhc.com"
CHILD_ENV_DROP = (
    "CI",
    "TEST_DATABASE_URL",
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "PYTEST_CURRENT_TEST",
)


def _pytest(*args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in CHILD_ENV_DROP}
    return subprocess.run(  # noqa: S603 (fixed interpreter and explicit file path, no shell)
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_ca05_idna_case_in_the_author_test_is_collected_once_and_passes() -> None:
    listed = _pytest("--collect-only", "-q", str(AUTHOR_TESTS), "-k", SELECTION)
    assert listed.returncode == 0, listed.stdout[-3000:] + listed.stderr[-3000:]
    ids = [line for line in listed.stdout.splitlines() if "::" in line]
    assert len(ids) == 1, ids
    assert "test_visible_ascii_api_url_still_sends[" in ids[0]
    assert IDNA_URL in ids[0]

    ran = _pytest("-q", str(AUTHOR_TESTS), "-k", SELECTION)
    assert ran.returncode == 0, ran.stdout[-3000:] + ran.stderr[-3000:]
    summary = ran.stdout.strip().splitlines()[-1]
    assert re.match(r"1 passed\b", summary), summary
    assert not re.search(r"\b(failed|error|errors|skipped|xfailed|xpassed)\b", summary), summary


def test_extra_idna_case_tells_raw_host_from_host() -> None:
    """The premise of SPEC-029 section 4.4: idna accepts raw_host and refuses .host."""
    url = httpx.URL(IDNA_URL)
    assert url.raw_host.decode("ascii").encode("idna") == b"xn--1-zhc.com"
    with pytest.raises(UnicodeError):
        url.host.encode("idna")
