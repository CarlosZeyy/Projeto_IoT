"""Acceptance tests for SPEC-042, telemetry part (CA-01 to CA-07).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Nothing is mocked: every test runs a real subprocess, with the environment of SPEC
section 4.2 built from scratch (only ``PATH`` and ``HOME=<tmp_path>``), so ``CI``,
``ORT_RUNNING_UNIT_TESTS`` and ``ORT_DISABLE_TELEMETRY`` never leak in. The real home folder is
never used.

CA-01 is the real network measurement: it only runs with ``PARTQC_TELEMETRY_TESTS=1``, inside
``unshare --user --map-root-user --net`` and under ``strace``, and it fails (never skips) when the
variable is set and the tools or the namespace are missing. Its control fires the telemetry on
purpose, which is why it does not run in CI. CA-02 and CA-03 check the variable before creating a
session and exit with code 3 when it is not ``1``, so wrong code cannot fire the telemetry on a CI
runner. The check runs right after importing the package and before ``onnxruntime`` loads, because
the tester measured that ``import onnxruntime`` alone already fires it (r1 test report). CA-08 and
CA-09 are in ``edge/tests/acceptance/test_spec_042.py``; CA-10 is a browser rehearsal recorded in
the test report; CA-11 is manual.

Tests named ``test_extra_*`` are exploratory edge cases that no CA spells out.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[2]
TINY_MODEL_DIR = ROOT / "ml" / "tests" / "fixtures" / "tiny_model"
TINY_MODEL = TINY_MODEL_DIR / "model.onnx"
ENV_EXAMPLE = ROOT / ".env.example"
ROOT_CONFTEST = ROOT / "conftest.py"
VARIABLE = "ORT_DISABLE_TELEMETRY"
GATE = "PARTQC_TELEMETRY_TESTS"
WINDOW_S = 35
RUN_TIMEOUT_S = 120
CONTROL_TIMEOUT_S = WINDOW_S + 60
MEASURED_TIMEOUT_S = WINDOW_S + 60
QUEUE_NAMES = {"onnxruntime.db", ".onnxruntime"}
# SPEC section 4.2: "htons(53)", "io.systemd.Resolve" or the name "mobile.events", with dots or in
# the DNS label format, as strace prints it (a backslash and the label length).
QUERY_RE = re.compile(r"htons\(53\)|io\.systemd\.Resolve|mobile\.events|\\6mobile\\6events")
ISOLATION = ("--user", "--map-root-user", "--net")
STRACE_ARGS = ("-f", "-qq", "-s", "256", "-e", "trace=network")
INVENTORY_DIRS = ("api", "dashboard", "edge", "ml", "packages", "scripts", "infra")
INVENTORY = {
    "edge/src/qc_edge/onnx_inferencer.py",
    "ml/src/qc_ml/predict.py",
    "ml/src/qc_ml/parity.py",
}

# Scripts: argv[1] is the model (or its directory). In the project scripts, the check comes before
# onnxruntime loads, and so before any session: the import alone already fires the telemetry.
CONTROL_SCRIPT = f"""
import json, os, sys, time
import onnxruntime
if "{VARIABLE}" in os.environ:
    sys.exit(4)
session = onnxruntime.InferenceSession(sys.argv[1], providers=["CPUExecutionProvider"])
start = time.monotonic()
time.sleep({WINDOW_S})
print(json.dumps({{"window_s": time.monotonic() - start}}))
"""

EDGE_SESSION_SCRIPT = f"""
import json, os, sys, time
import qc_edge
if os.environ.get("{VARIABLE}") != "1":
    sys.exit(3)
import qc_edge.onnx_inferencer
session = qc_edge.onnx_inferencer.onnxruntime.InferenceSession(
    sys.argv[1], providers=["CPUExecutionProvider"]
)
start = time.monotonic()
time.sleep({WINDOW_S})
print(json.dumps({{"window_s": time.monotonic() - start}}))
"""

TRAIN_PARITY_SCRIPT = f"""
import json, os, pathlib, sys, time
import qc_ml
if os.environ.get("{VARIABLE}") != "1":
    sys.exit(3)
import qc_ml.parity
result = qc_ml.parity.check_parity(pathlib.Path(sys.argv[1]))
start = time.monotonic()
time.sleep({WINDOW_S})
print(json.dumps({{"window_s": time.monotonic() - start, "ok": result.ok}}))
"""

EDGE_INFERENCE_SCRIPT = f"""
import json, os, sys
import numpy as np
import qc_edge
if os.environ.get("{VARIABLE}") != "1":
    sys.exit(3)
import qc_edge.onnx_inferencer
session = qc_edge.onnx_inferencer.onnxruntime.InferenceSession(
    sys.argv[1], providers=["CPUExecutionProvider"]
)
model_input = session.get_inputs()[0]
shape = [dim if isinstance(dim, int) and dim > 0 else 1 for dim in model_input.shape]
outputs = session.run(None, {{model_input.name: np.zeros(shape, dtype=np.float32)}})
print(json.dumps({{"outputs": len(outputs)}}))
"""

TRAIN_SCRIPT = f"""
import json, os, pathlib, sys
import qc_ml
if os.environ.get("{VARIABLE}") != "1":
    sys.exit(3)
import qc_ml.parity
result = qc_ml.parity.check_parity(pathlib.Path(sys.argv[1]))
print(json.dumps({{"ok": result.ok}}))
"""

ENV_PROBE_SCRIPT = f"""
import json, os, sys
{{statement}}
print(json.dumps({{{{
    "value": os.environ.get("{VARIABLE}"),
    "onnxruntime_loaded": "onnxruntime" in sys.modules,
}}}}))
"""


def clean_env(home: Path, **extra: str) -> dict[str, str]:
    """The clean environment of SPEC section 4.2, built from scratch."""
    return {"PATH": os.environ["PATH"], "HOME": str(home), **extra}


def new_home(tmp_path: Path, name: str = "home") -> Path:
    home = tmp_path / name
    home.mkdir()
    return home


def queue_in(home: Path) -> list[str]:
    """Any ``onnxruntime.db`` or ``.onnxruntime`` folder under the temporary home."""
    return sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.name in QUEUE_NAMES)


def run_python(
    code: str, home: Path, *args: str, **extra_env: str
) -> subprocess.CompletedProcess[str]:
    """Runs ``code`` in the clean environment, outside the repository and without ``unshare``."""
    return subprocess.run(
        [sys.executable, "-c", code, *args],
        env=clean_env(home, **extra_env),
        cwd=home.parent,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_S,
        check=False,
    )


def describe(process: subprocess.CompletedProcess[str]) -> str:
    return f"code={process.returncode}\nstdout={process.stdout}\nstderr={process.stderr}"


def last_json(stdout: str) -> dict[str, object]:
    """The JSON line of a script; the last one, so a stray library line cannot break the parsing."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, f"the script printed nothing: {stdout!r}"
    return json.loads(lines[-1])


# =============================================================================== CA-01 machinery


@dataclass
class Measurement:
    label: str
    code: int | None
    log_lines: list[str]
    query_lines: list[str]
    queue: list[str]
    stdout: str
    stderr: str
    stopped_early: bool

    def summary(self) -> str:
        return (
            f"{self.label}: code={self.code} log_lines={len(self.log_lines)} "
            f"queries={len(self.query_lines)} queue={self.queue} "
            f"stopped_early={self.stopped_early}"
        )

    def details(self) -> str:
        sample = "\n".join(self.query_lines[:5])
        return (
            f"{self.summary()}\nqueries (first 5):\n{sample}\n"
            f"stdout={self.stdout}\nstderr={self.stderr}"
        )


def tool(name: str) -> str:
    """SPEC section 4.2: a missing tool fails, so it cannot become a silent skip."""
    path = shutil.which(name)
    if path is None:
        pytest.fail(f"{GATE}=1 and `{name}` is not on PATH", pytrace=False)
    return path


def isolated_command(log: Path, *command: str) -> list[str]:
    return [
        tool("unshare"),
        *ISOLATION,
        tool("strace"),
        *STRACE_ARGS,
        "-o",
        str(log),
        *command,
    ]


def read_log(log: Path) -> list[str]:
    if not log.exists():
        return []
    return log.read_text(encoding="utf-8", errors="replace").splitlines()


def queries(lines: list[str]) -> list[str]:
    return [line for line in lines if QUERY_RE.search(line)]


def stop(process: subprocess.Popen[bytes]) -> None:
    """Stops the whole process group, so no traced child outlives the measurement."""
    for sig, wait_s in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=wait_s)
            return
        except subprocess.TimeoutExpired:
            continue


def measure(
    label: str,
    script: str,
    target: Path,
    workdir: Path,
    *,
    stop_on_evidence: bool,
) -> Measurement:
    """Runs one process under the isolation and strace of SPEC section 4.2 and reads the evidence.

    With ``stop_on_evidence``, the process ends as soon as the log has a query and the queue exists
    (the control may do it, section 4.2). Otherwise, it lives through the whole window.
    """
    workdir.mkdir()
    home = new_home(workdir)
    log = workdir / "strace.log"
    stdout_path = workdir / "stdout.txt"
    stderr_path = workdir / "stderr.txt"
    command = isolated_command(log, sys.executable, "-c", script, str(target))
    timeout_s = CONTROL_TIMEOUT_S if stop_on_evidence else MEASURED_TIMEOUT_S
    stopped_early = False
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            command,
            env=clean_env(home),
            cwd=workdir,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout_s
        try:
            while process.poll() is None:
                if time.monotonic() > deadline:
                    pytest.fail(f"{label}: still running after {timeout_s} s", pytrace=False)
                if stop_on_evidence and queries(read_log(log)) and queue_in(home):
                    stopped_early = True
                    break
                time.sleep(0.2)
        finally:
            stop(process)
    lines = read_log(log)
    return Measurement(
        label=label,
        code=process.returncode,
        log_lines=lines,
        query_lines=queries(lines),
        queue=queue_in(home),
        stdout=stdout_path.read_text(encoding="utf-8", errors="replace"),
        stderr=stderr_path.read_text(encoding="utf-8", errors="replace"),
        stopped_early=stopped_early,
    )


def check_isolation(tmp_path: Path) -> None:
    """The namespace exists, has no interface with a way out, and strace sees a query inside it.

    The probe only calls ``connect`` on a UDP socket for a documentation address (RFC 5737), port
    53: no packet is sent, and there is no route anyway. A detector that cannot see this line would
    turn the "0 queries" of (b) and (c) into a proof of nothing.
    """
    log = tmp_path / "probe.log"
    probe = (
        "import json, socket\n"
        "names = [name for _, name in socket.if_nameindex()]\n"
        "sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        "code = sock.connect_ex(('192.0.2.1', 53))\n"
        "print(json.dumps({'interfaces': names, 'connect': code}))\n"
    )
    home = new_home(tmp_path, "probe-home")
    done = subprocess.run(
        isolated_command(log, sys.executable, "-c", probe),
        env=clean_env(home),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_S,
        check=False,
    )
    if done.returncode != 0:
        pytest.fail(
            f"could not create the namespace or run strace:\n{describe(done)}", pytrace=False
        )
    answer = last_json(done.stdout)
    assert answer["interfaces"] == ["lo"], f"the namespace has a way out: {answer}"
    assert answer["connect"] != 0, f"a connect inside the namespace reached a route: {answer}"
    assert queries(read_log(log)), (
        "strace did not record the probe query, so it would prove nothing"
    )
    print(f"isolation probe: {answer}")


@pytest.mark.slow
def test_ca01_real_network_measurement_with_control(tmp_path: Path) -> None:
    if os.environ.get(GATE) != "1":
        pytest.skip(f"real network measurement: only runs with {GATE}=1")
    check_isolation(tmp_path)

    control = measure(
        "(a) control",
        CONTROL_SCRIPT,
        TINY_MODEL,
        tmp_path / "control",
        stop_on_evidence=True,
    )
    print(control.summary())
    assert control.query_lines, (
        f"the control made no query: the measurement proves nothing\n{control.details()}"
    )
    assert control.queue, f"the control created no queue in the temp home\n{control.details()}"

    edge = measure(
        "(b) edge",
        EDGE_SESSION_SCRIPT,
        TINY_MODEL,
        tmp_path / "edge",
        stop_on_evidence=False,
    )
    print(edge.summary())
    train = measure(
        "(c) train",
        TRAIN_PARITY_SCRIPT,
        TINY_MODEL_DIR,
        tmp_path / "train",
        stop_on_evidence=False,
    )
    print(train.summary())

    for measured in (edge, train):
        assert measured.code == 0, measured.details()
        answer = last_json(measured.stdout)
        assert float(str(answer["window_s"])) >= WINDOW_S, measured.details()
        assert measured.query_lines == [], measured.details()
        assert measured.queue == [], measured.details()
    assert last_json(train.stdout)["ok"] is True, train.details()


# ================================================================================ CA-02 to CA-05


def test_ca02_edge_session_and_inference_create_no_queue(tmp_path: Path) -> None:
    home = new_home(tmp_path)
    done = run_python(EDGE_INFERENCE_SCRIPT, home, str(TINY_MODEL))
    assert done.returncode == 0, describe(done)
    assert last_json(done.stdout)["outputs"] > 0  # type: ignore[operator]
    assert queue_in(home) == []


def test_ca03_train_parity_creates_no_queue(tmp_path: Path) -> None:
    home = new_home(tmp_path)
    done = run_python(TRAIN_SCRIPT, home, str(TINY_MODEL_DIR))
    assert done.returncode == 0, describe(done)
    assert last_json(done.stdout)["ok"] is True
    assert queue_in(home) == []


@pytest.mark.parametrize("package", ["qc_edge", "qc_ml"])
def test_ca04_inherited_zero_does_not_turn_it_back_on(tmp_path: Path, package: str) -> None:
    home = new_home(tmp_path)
    code = ENV_PROBE_SCRIPT.format(statement=f"import {package}")
    done = run_python(code, home, **{VARIABLE: "0"})
    assert done.returncode == 0, describe(done)
    answer = last_json(done.stdout)
    assert answer["value"] == "1"
    assert answer["onnxruntime_loaded"] is False


def test_ca05_root_conftest_sets_the_variable(tmp_path: Path) -> None:
    home = new_home(tmp_path)
    statement = f"import runpy; runpy.run_path({str(ROOT_CONFTEST)!r})"
    done = run_python(ENV_PROBE_SCRIPT.format(statement=statement), home)
    assert done.returncode == 0, describe(done)
    answer = last_json(done.stdout)
    assert answer["value"] == "1"
    assert answer["onnxruntime_loaded"] is False


# ================================================================================ CA-06 and CA-07


def imports_onnxruntime(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] if node.level == 0 else []
        else:
            continue
        if any(name == "onnxruntime" or name.startswith("onnxruntime.") for name in names):
            return True
    return False


def inventory_files() -> list[Path]:
    found: list[Path] = []
    for directory in INVENTORY_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            relative = path.relative_to(ROOT)
            if "tests" in relative.parts or ".venv" in relative.parts:
                continue
            found.append(path)
    return found


def test_ca06_onnxruntime_inventory() -> None:
    files = inventory_files()
    assert files, "the inventory scanned nothing"
    found = {
        path.relative_to(ROOT).as_posix()
        for path in files
        if imports_onnxruntime(path.read_text(encoding="utf-8"))
    }
    assert found == INVENTORY


def test_ca07_env_example_only_comments_the_variable() -> None:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("#") and VARIABLE in line for line in lines)
    assert not any(line.startswith(f"{VARIABLE}=") for line in lines)


# ===================================================================================== exploratory


def test_extra_env_example_has_the_exact_comment() -> None:
    comment = (
        "# onnxruntime telemetry: the code sets ORT_DISABLE_TELEMETRY to 1 (SPEC-042); "
        "nothing to configure."
    )
    assert comment in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("package", ["qc_edge", "qc_ml"])
@pytest.mark.parametrize("inherited", [None, "", "0", "false", "off", "1"])
def test_extra_any_inherited_value_ends_as_one(
    tmp_path: Path, package: str, inherited: str | None
) -> None:
    home = new_home(tmp_path)
    extra = {} if inherited is None else {VARIABLE: inherited}
    done = run_python(ENV_PROBE_SCRIPT.format(statement=f"import {package}"), home, **extra)
    assert done.returncode == 0, describe(done)
    assert last_json(done.stdout) == {"value": "1", "onnxruntime_loaded": False}


@pytest.mark.parametrize(
    "module",
    ["qc_edge.onnx_inferencer", "qc_edge.cli", "qc_edge.app", "qc_ml.parity", "qc_ml.predict"],
)
def test_extra_variable_is_already_one_when_onnxruntime_starts_to_load(
    tmp_path: Path, module: str
) -> None:
    """A finder sees the variable at the moment ``onnxruntime`` would load, and stops the process.

    No session is ever created, so this cannot fire the telemetry. A module that does not load
    ``onnxruntime`` at import time ends with code 0 and the variable already checked.
    """
    code = f"""
import os, sys
class Sentinel:
    def find_spec(self, name, path=None, target=None):
        if name == "onnxruntime":
            sys.stdout.write(os.environ.get("{VARIABLE}", "<absent>"))
            sys.stdout.flush()
            os._exit(42)
        return None
sys.meta_path.insert(0, Sentinel())
import {module}
sys.stdout.write(os.environ.get("{VARIABLE}", "<absent>"))
"""
    done = run_python(code, new_home(tmp_path), **{VARIABLE: "0"})
    assert done.returncode in {0, 42}, describe(done)
    assert done.stdout == "1", describe(done)


@pytest.mark.parametrize("package", ["qc_edge", "qc_ml"])
def test_extra_assignment_reaches_the_c_environment(tmp_path: Path, package: str) -> None:
    """SPEC section 7: the assignment must reach ``getenv`` in C, what onnxruntime reads."""
    code = f"""
import ctypes, sys
import {package}
libc = ctypes.CDLL(None)
libc.getenv.restype = ctypes.c_char_p
value = libc.getenv(b"{VARIABLE}")
sys.stdout.write(value.decode() if value is not None else "<absent>")
"""
    done = run_python(code, new_home(tmp_path), **{VARIABLE: "0"})
    assert done.returncode == 0, describe(done)
    assert done.stdout == "1", describe(done)


def test_extra_production_inferencer_creates_no_queue(tmp_path: Path) -> None:
    """The path the edge really uses: ``OnnxInferencer`` over the tiny model, with a real image."""
    code = f"""
import json, os, pathlib, sys
from PIL import Image
import qc_edge
if os.environ.get("{VARIABLE}") != "1":
    sys.exit(3)
from qc_edge.onnx_inferencer import OnnxInferencer
inferencer = OnnxInferencer(pathlib.Path(sys.argv[1]))
answer = inferencer.infer(Image.new("RGB", (64, 48), "steelblue"))
print(json.dumps({{"type": str(answer.object_type)}}))
"""
    home = new_home(tmp_path)
    # The directory name is the model_version, and the fixture's name has an underscore.
    model_dir = tmp_path / "partqc-tiny-v1"
    shutil.copytree(TINY_MODEL_DIR, model_dir)
    done = run_python(code, home, str(model_dir))
    assert done.returncode == 0, describe(done)
    assert queue_in(home) == []


def test_extra_nobody_calls_disable_telemetry_events() -> None:
    """SPEC sections 3.2 and 4.1: that call does not stop the telemetry, so it stays out."""
    for path in inventory_files():
        assert "disable_telemetry_events" not in path.read_text(encoding="utf-8"), str(path)


def test_extra_variable_is_not_edge_or_train_configuration() -> None:
    """SPEC section 4.1: the variable is not read from ``.env`` and is not project configuration."""
    for path in inventory_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in {"edge/src/qc_edge/__init__.py", "ml/src/qc_ml/__init__.py"}:
            continue
        assert VARIABLE not in path.read_text(encoding="utf-8"), relative
