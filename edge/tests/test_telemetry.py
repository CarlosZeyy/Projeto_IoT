"""Author tests of SPEC-042 Part B: ``import qc_edge`` and the root conftest turn the telemetry off.

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
ROOT = Path(__file__).resolve().parents[2]
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
import qc_edge.onnx_inferencer
print("onnxruntime did not load", flush=True)
"""
CHECK = (
    "import os, sys\n"
    "{load}\n"
    f"print(os.environ[{VARIABLE!r}])\n"
    "print('onnxruntime' in sys.modules)\n"
)


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
    result = _run(CHECK.format(load="import qc_edge"), tmp_path, inherited)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["1", "False"]


def test_variable_is_set_before_onnxruntime_loads(tmp_path: Path) -> None:
    result = _run(PROBE, tmp_path, inherited="0")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"


@pytest.mark.parametrize("inherited", [None, "0"], ids=["unset", "zero"])
def test_root_conftest_forces_the_variable_without_loading_onnxruntime(
    tmp_path: Path, inherited: str | None
) -> None:
    load = f"import runpy; runpy.run_path({str(ROOT / 'conftest.py')!r})"
    result = _run(CHECK.format(load=load), tmp_path, inherited)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["1", "False"]


def test_env_example_only_comments_the_variable() -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert [line for line in lines if VARIABLE in line] == [
        "# onnxruntime telemetry: the code sets ORT_DISABLE_TELEMETRY to 1 (SPEC-042); "
        "nothing to configure."
    ]
