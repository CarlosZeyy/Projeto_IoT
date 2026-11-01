"""Author tests of SPEC-042 Part A: ``import qc_ml`` turns the onnxruntime telemetry off.

Each test runs in a subprocess with an environment built from scratch (``PATH`` and a temporary
``HOME``), so no ``CI``-like variable can hide a failure. None of them creates an onnxruntime
session: the real measurement of the network and of the queue is in the acceptance tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

VARIABLE = "ORT_DISABLE_TELEMETRY"
# Stops the process as soon as onnxruntime is about to load, and prints the variable at that point.
PROBE = """\
import os
import sys


class Probe:
    def find_spec(self, name, path=None, target=None):
        if name == "onnxruntime":
            print(os.environ.get("ORT_DISABLE_TELEMETRY"), flush=True)
            os._exit(0)
        return None


sys.meta_path.insert(0, Probe())
import {module}
"""


def _run(code: str, home: Path, inherited: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    if inherited is not None:
        env[VARIABLE] = inherited
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )


@pytest.mark.parametrize("inherited", [None, "", "0", "1"], ids=["unset", "empty", "zero", "one"])
def test_import_forces_the_variable_without_loading_onnxruntime(
    tmp_path: Path, inherited: str | None
) -> None:
    code = (
        "import os, sys\n"
        "import qc_ml\n"
        f"print(os.environ[{VARIABLE!r}])\n"
        "print('onnxruntime' in sys.modules)\n"
    )
    result = _run(code, tmp_path, inherited)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["1", "False"]


@pytest.mark.parametrize("module", ["qc_ml.parity", "qc_ml.predict"])
def test_variable_is_set_before_onnxruntime_loads(tmp_path: Path, module: str) -> None:
    result = _run(PROBE.format(module=module), tmp_path, inherited="0")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"
