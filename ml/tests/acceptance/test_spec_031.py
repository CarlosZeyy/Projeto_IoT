"""Acceptance tests for SPEC-031 (ML maintenance: non-finite values, TorchScript export, ...).

Written by the tester from the SPEC acceptance criteria (black box), through the public
interface: ``check_parity`` and ``python -m qc_ml.parity``, ``Predictions``,
``choose_thresholds``, ``export_onnx``, the modules ``qc_ml.split``/``qc_ml.data`` and the files
on disk (``ml/pyproject.toml``, ``uv.lock``, ``ml/README.md``, the Colab notebook). One test per
CA (``test_caNN_*``); tests named ``test_extra_*`` are exploratory edge cases.

Rules followed (``docs/architecture.md`` §10, R-11, R-12, R-14):

- the tiny model fixture is only read; every change is made on a copy under ``tmp_path``;
- no network, no real photo and no test runs the test suite in a subprocess;
- the torch part of CA-05 is marked ``slow`` and skipped without torch (CI).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import math
import re
import shutil
import subprocess
import sys
import tomllib
import warnings
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from qc_ml import data as data_mod
from qc_ml import split as split_mod
from qc_ml.parity import check_parity
from qc_ml.parity import main as parity_main
from qc_ml.predict import Predictions
from qc_ml.thresholds import choose_thresholds

pytestmark = pytest.mark.acceptance

REPO_ROOT = Path(__file__).resolve().parents[3]
ML_ROOT = REPO_ROOT / "ml"
TINY_MODEL = ML_ROOT / "tests" / "fixtures" / "tiny_model"
NOTEBOOK = ML_ROOT / "notebooks" / "train_colab.ipynb"
README = ML_ROOT / "README.md"
EXPORT_PY = ML_ROOT / "src" / "qc_ml" / "export.py"
SPLIT_PY = ML_ROOT / "src" / "qc_ml" / "split.py"
TINY_SCRIPT = ML_ROOT / "scripts" / "make_tiny_fixture.py"
GRADES = ["perfect", "good", "fair", "poor", "unusable"]
LABELS = {"object_types": ["screw", "nut", "other"], "grades": GRADES}
TRAIN_NAMES = {"torch", "torchvision", "timm", "onnx", "coral-pytorch"}
ML_RUNTIME = {"torch", "torchvision", "timm", "onnxruntime"}


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    assert resolved.is_relative_to(root.resolve()), f"{resolved} escapes {root}"
    return path


def _tiny_copy(tmp_path: Path) -> Path:
    copy = _inside(tmp_path / "tiny_model", tmp_path)
    shutil.copytree(TINY_MODEL, copy)
    return copy


def _load_fixture(model_dir: Path) -> dict[str, np.ndarray]:
    with np.load(model_dir / "parity_fixture.npz", allow_pickle=False) as data:
        return {key: data[key].copy() for key in data.files}


def _save_fixture(model_dir: Path, arrays: dict[str, np.ndarray], root: Path) -> None:
    np.savez_compressed(_inside(model_dir / "parity_fixture.npz", root), **arrays)


def _run_parity_cli(model_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "qc_ml.parity", "--model-dir", str(model_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _valid_rows() -> tuple[np.ndarray, np.ndarray]:
    type_probs = np.array([[0.8, 0.15, 0.05], [0.1, 0.7, 0.2]], dtype=np.float64)
    grade_probs = np.array(
        [[0.1, 0.6, 0.2, 0.05, 0.05], [0.0, 0.1, 0.2, 0.3, 0.4]], dtype=np.float64
    )
    return type_probs, grade_probs


def _predictions(
    type_probs: Any,
    grade_probs: Any,
    split: str = "val",
    paths: tuple[str, ...] | None = None,
    true_type: Any = None,
    true_grade: Any = None,
) -> Predictions:
    n = len(type_probs)
    return Predictions(
        split=split,
        image_paths=paths if paths is not None else tuple(f"img_{i:03d}.jpg" for i in range(n)),
        type_probs=type_probs,
        grade_probs=grade_probs,
        true_type_idx=true_type if true_type is not None else np.zeros(n, dtype=np.int64),
        true_grade_idx=true_grade if true_grade is not None else np.ones(n, dtype=np.int64),
    )


def _source(cell: dict[str, Any]) -> str:
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else src


def _readme_section(text: str, needle: str) -> str:
    """Return the section whose heading contains ``needle``, up to the next heading of level <=.

    Lines inside fenced code blocks are never taken as headings (``# comment`` in bash).
    """
    lines = text.splitlines()
    start = level = None
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"(#{1,6})\s+(.*)", line)
        if not match:
            continue
        if start is None:
            if needle in match.group(2):
                start, level = i, len(match.group(1))
        elif len(match.group(1)) <= level:
            return "\n".join(lines[start:i])
    assert start is not None, f"no heading containing {needle!r}"
    return "\n".join(lines[start:])


def _lock() -> dict[str, Any]:
    return tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))


def _packages(lock: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [p for p in lock["package"] if p["name"] == name]


def _closure(lock: dict[str, Any], root: str) -> set[str]:
    """Names reachable from ``root`` through ``dependencies`` and the extras each edge asks for.

    The optional dependencies of ``root`` itself are not followed (a plain install).
    """
    by_name: dict[str, list[dict[str, Any]]] = {}
    for package in lock["package"]:
        by_name.setdefault(package["name"], []).append(package)
    seen: set[str] = set()
    queue: deque[tuple[str, tuple[str, ...]]] = deque([(root, ())])
    visited: set[tuple[str, tuple[str, ...]]] = set()
    while queue:
        name, extras = queue.popleft()
        if (name, extras) in visited:
            continue
        visited.add((name, extras))
        seen.add(name)
        for package in by_name.get(name, []):
            edges = list(package.get("dependencies", []))
            for extra in extras:
                edges += package.get("optional-dependencies", {}).get(extra, [])
            for dep in edges:
                queue.append((dep["name"], tuple(sorted(dep.get("extra", [])))))
    return seen


# ---------------------------------------------------------------------------------------------
# CA-01 and CA-02: parity with non-finite values (section 4.1)
# ---------------------------------------------------------------------------------------------


def test_ca01_nan_reference_at_argmax_fails_parity(tmp_path: Path) -> None:
    copy = _tiny_copy(tmp_path)
    arrays = _load_fixture(copy)
    j = int(np.argmax(arrays["type_probs"][0]))
    arrays["type_probs"][0, j] = np.nan
    _save_fixture(copy, arrays, tmp_path)

    result = check_parity(copy)
    assert result.ok is False
    assert result.max_abs_diff == math.inf
    assert "non-finite values" in result.message

    proc = _run_parity_cli(copy)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "non-finite values" in proc.stderr
    assert parity_main(["--model-dir", str(copy)]) == 2


def test_ca02_nan_input_and_references_fail_and_original_passes(tmp_path: Path) -> None:
    copy = _tiny_copy(tmp_path)
    arrays = _load_fixture(copy)
    arrays["inputs"][0] = np.nan
    arrays["type_probs"][0, :] = np.nan
    arrays["grade_probs"][0, :] = np.nan
    _save_fixture(copy, arrays, tmp_path)

    result = check_parity(copy)
    assert result.ok is False
    assert "non-finite values" in result.message

    original = check_parity(_tiny_copy(tmp_path / "orig"))
    assert original.ok is True
    assert original.max_abs_diff < 1e-4
    assert original.argmax_equal is True


# ---------------------------------------------------------------------------------------------
# CA-03: Predictions validates the probabilities (section 4.2)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "index", "value"),
    [
        ("type_probs", (0, 0), math.nan),
        ("grade_probs", (1, 2), math.inf),
        ("type_probs", (0, 1), -0.01),
        ("grade_probs", (0, 4), 1.01),
    ],
    ids=["type-nan", "grade-inf", "type-negative", "grade-above-one"],
)
def test_ca03_predictions_refuse_invalid_probabilities(
    field: str, index: tuple[int, int], value: float
) -> None:
    type_probs, grade_probs = _valid_rows()
    target = type_probs if field == "type_probs" else grade_probs
    target[index] = value
    with pytest.raises(ValueError) as exc:
        _predictions(type_probs, grade_probs)
    message = str(exc.value)
    assert field in message, message
    other = "grade_probs" if field == "type_probs" else "type_probs"
    assert other not in message, message


def test_ca03_predictions_accept_valid_bounds_and_empty() -> None:
    type_probs, grade_probs = _valid_rows()
    preds = _predictions(type_probs, grade_probs)
    assert len(preds) == 2

    exact = _predictions(
        np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
        np.array([[0.0, 0.0, 0.0, 0.0, 1.0], [1.0, 0.0, 0.0, 0.0, 0.0]]),
    )
    assert len(exact) == 2

    empty = Predictions(
        split="val",
        image_paths=(),
        type_probs=np.zeros((0, 3)),
        grade_probs=np.zeros((0, 5)),
        true_type_idx=np.zeros(0, dtype=np.int64),
        true_grade_idx=np.zeros(0, dtype=np.int64),
    )
    assert len(empty) == 0


# ---------------------------------------------------------------------------------------------
# CA-04: torch ceiling in the train extra and in uv.lock; R-12 still holds (section 4.3, item 1)
# ---------------------------------------------------------------------------------------------


def test_ca04_torch_ceiling_in_pyproject_and_lock() -> None:
    pyproject = tomllib.loads((ML_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    train = pyproject["project"]["optional-dependencies"]["train"]
    assert "torch<2.15" in train, train
    assert [d for d in train if re.match(r"torch(?![A-Za-z0-9._-])", d)] == ["torch<2.15"]

    lock = _lock()
    (torch_pkg,) = _packages(lock, "torch")
    assert torch_pkg["version"] == "2.14.1"

    (qc_ml,) = _packages(lock, "qc-ml")
    torch_reqs = [d for d in qc_ml["metadata"]["requires-dist"] if d["name"] == "torch"]
    assert len(torch_reqs) == 1, torch_reqs
    (req,) = torch_reqs
    assert req.get("specifier") == "<2.15", req
    assert re.fullmatch(r"extra\s*==\s*['\"]train['\"]", req.get("marker", "")), req
    assert "torch" in {d["name"] for d in qc_ml["optional-dependencies"]["train"]}
    assert "torch" not in {d["name"] for d in qc_ml.get("dependencies", [])}

    for package in ("qc-api", "qc-dashboard"):
        closure = _closure(lock, package)
        assert "qc-contracts" in closure, package  # the walk really follows the graph
        assert not closure & ML_RUNTIME, (package, closure & ML_RUNTIME)


# ---------------------------------------------------------------------------------------------
# CA-05: deprecation warnings of the export are logged, never ignored (section 4.3, item 2)
# ---------------------------------------------------------------------------------------------


def _ignore_filter_calls(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in {"simplefilter", "filterwarnings"}:
            continue
        values = [*node.args, *(kw.value for kw in node.keywords)]
        if any(isinstance(v, ast.Constant) and v.value == "ignore" for v in values):
            lines.append(node.lineno)
    return lines


def test_ca05_export_has_no_ignore_filter() -> None:
    tree = ast.parse(EXPORT_PY.read_text(encoding="utf-8"))
    assert _ignore_filter_calls(tree) == []
    # control: the detector does find the old form
    assert _ignore_filter_calls(ast.parse('warnings.simplefilter("ignore", DeprecationWarning)'))


def _tiny_net_class() -> type:
    spec = importlib.util.spec_from_file_location("partqc_tiny_fixture_031", TINY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TinyNet


@pytest.mark.slow
def test_ca05_export_logs_deprecation_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    torch = pytest.importorskip("torch")
    from qc_ml.export import export_onnx

    marker = "partqc-spec031-ca05-marker"
    original = torch.onnx.export

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        out = original(*args, **kwargs)
        warnings.warn(marker, DeprecationWarning, stacklevel=1)
        return out

    monkeypatch.setattr(torch.onnx, "export", wrapped)
    torch.manual_seed(0)
    model = _tiny_net_class()().eval()
    out = _inside(tmp_path / "export" / "model.onnx", tmp_path)
    caplog.set_level(logging.WARNING, logger="qc_ml.export")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        export_onnx(model, out)
    assert out.is_file() and out.stat().st_size > 0
    records = [
        r
        for r in caplog.records
        if r.name == "qc_ml.export"
        and r.levelno == logging.WARNING
        and f"torch.onnx.export: {marker}" in r.getMessage()
    ]
    assert records, [(r.name, r.levelname, r.getMessage()) for r in caplog.records]


# ---------------------------------------------------------------------------------------------
# CA-06: notebook checks the export and the split before the pipeline (sections 4.3 and 4.5)
# ---------------------------------------------------------------------------------------------


def test_ca06_notebook_export_check_and_split_before_pipeline() -> None:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cells = notebook["cells"]
    pipeline = [
        i
        for i, c in enumerate(cells)
        if c["cell_type"] == "code" and "python -m qc_ml.pipeline" in _source(c)
    ]
    assert pipeline, "no code cell runs python -m qc_ml.pipeline"
    first_pipeline = pipeline[0]
    export_check = [
        i
        for i, c in enumerate(cells)
        if c["cell_type"] == "code" and "make_tiny_fixture.py --out" in _source(c)
    ]
    assert export_check and export_check[0] < first_pipeline, (export_check, first_pipeline)
    split_md = [
        i
        for i, c in enumerate(cells[:first_pipeline])
        if c["cell_type"] == "markdown"
        and "split_v1" in _source(c)
        and "python -m qc_ml.split" in _source(c)
    ]
    assert split_md, "no markdown cell before the pipeline cites split_v1 and qc_ml.split"

    code_cells = [c for c in cells if c["cell_type"] == "code"]
    for cell in code_cells:
        source = _source(cell)
        assert cell.get("outputs") == [], source
        assert cell.get("execution_count") is None, source
        assert "def " not in source, source
        assert "class " not in source, source
        assert not re.search(r"ghp_|github_pat_|token\s*=\s*[\"']", source), source


# ---------------------------------------------------------------------------------------------
# CA-07: README, split_v1 is step 0 of "Do Colab ao Release" (section 4.5)
# ---------------------------------------------------------------------------------------------


def test_ca07_readme_split_v1_before_step_1() -> None:
    section = _readme_section(README.read_text(encoding="utf-8"), "Do Colab ao Release")
    assert "python -m qc_ml.split" in section
    assert "split_v1" in section
    split_pos = section.index("python -m qc_ml.split")
    step1 = re.search(r"(?m)^\s*1\.\s", section)
    assert step1 is not None, "no numbered list item 1. in the section"
    assert split_pos < step1.start(), (split_pos, step1.start())


# ---------------------------------------------------------------------------------------------
# CA-08: no screw/nut in validation -> type_threshold 0.50 and no_screw_nut_in_val (4.4)
# ---------------------------------------------------------------------------------------------


def test_ca08_no_screw_nut_in_val_note() -> None:
    n = 6
    type_probs = np.array([[0.05, 0.05, 0.9]] * n)
    grade_probs = np.array([[0.1, 0.2, 0.4, 0.2, 0.1]] * n)
    preds = _predictions(
        type_probs,
        grade_probs,
        true_type=np.full(n, 2, dtype=np.int64),
        true_grade=np.full(n, -1, dtype=np.int64),
    )
    result = choose_thresholds(preds, LABELS)
    assert result.decision["type_threshold"] == 0.5
    notes = result.report["notes"]
    assert "no_screw_nut_in_val" in notes
    assert "type_target_not_met" not in notes


# ---------------------------------------------------------------------------------------------
# CA-09: a single ITEM_ID_PATTERN (section 4.6)
# ---------------------------------------------------------------------------------------------


def test_ca09_item_id_pattern_defined_once() -> None:
    assert split_mod.ITEM_ID_PATTERN is data_mod.ITEM_ID_PATTERN
    tree = ast.parse(SPLIT_PY.read_text(encoding="utf-8"))
    offending = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_compile = (
            isinstance(func, ast.Attribute)
            and func.attr == "compile"
            and isinstance(func.value, ast.Name)
            and func.value.id == "re"
        )
        if not is_compile or not node.args:
            continue
        for sub in ast.walk(node.args[0]):
            if (
                isinstance(sub, ast.Constant)
                and isinstance(sub.value, str)
                and "[SNOT]" in sub.value
            ):
                offending.append(node.lineno)
    assert offending == [], offending


# ---------------------------------------------------------------------------------------------
# Exploratory edge cases
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "value"),
    [("type_probs", np.inf), ("grade_probs", -np.inf), ("grade_probs", np.nan)],
    ids=["type-inf", "grade-minus-inf", "grade-nan"],
)
def test_extra_parity_other_non_finite_references(tmp_path: Path, key: str, value: float) -> None:
    copy = _tiny_copy(tmp_path)
    arrays = _load_fixture(copy)
    arrays[key][3, 1] = value
    _save_fixture(copy, arrays, tmp_path)
    result = check_parity(copy)
    assert result.ok is False
    assert result.max_abs_diff == math.inf
    assert result.argmax_equal is False
    assert result.sha256_match is True
    assert "non-finite values" in result.message


def test_extra_parity_non_finite_onnx_output_only(tmp_path: Path) -> None:
    """A NaN input sample with finite references: only the ONNX side is non-finite."""
    copy = _tiny_copy(tmp_path)
    arrays = _load_fixture(copy)
    arrays["inputs"][2] = np.nan
    _save_fixture(copy, arrays, tmp_path)
    assert np.isfinite(arrays["type_probs"]).all()
    result = check_parity(copy)
    assert result.ok is False
    assert result.max_abs_diff == math.inf
    assert "non-finite values" in result.message
    proc = _run_parity_cli(copy)
    assert proc.returncode == 2
    assert "non-finite values" in proc.stderr
    assert proc.stdout == ""


def test_extra_parity_non_finite_with_other_sha(tmp_path: Path) -> None:
    copy = _tiny_copy(tmp_path)
    arrays = _load_fixture(copy)
    arrays["grade_probs"][0, 0] = np.nan
    arrays["model_sha256"] = np.asarray("e" * 64)
    _save_fixture(copy, arrays, tmp_path)
    result = check_parity(copy)
    assert result.ok is False
    assert result.sha256_match is False
    assert "non-finite values" in result.message


def test_extra_parity_shape_mismatch_still_refused(tmp_path: Path) -> None:
    copy = _tiny_copy(tmp_path)
    arrays = _load_fixture(copy)
    arrays["grade_probs"] = arrays["grade_probs"][:, :4]
    _save_fixture(copy, arrays, tmp_path)
    result = check_parity(copy)
    assert result.ok is False
    assert result.max_abs_diff == math.inf


def test_extra_parity_finite_perturbation_unchanged(tmp_path: Path) -> None:
    copy = _tiny_copy(tmp_path)
    arrays = _load_fixture(copy)
    arrays["grade_probs"][5, 3] -= 5e-3
    _save_fixture(copy, arrays, tmp_path)
    result = check_parity(copy)
    assert result.ok is False
    assert 4.9e-3 < result.max_abs_diff < 5.1e-3
    assert "non-finite" not in result.message


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type_probs", -math.inf),
        ("grade_probs", -1e-300),
        ("type_probs", 1.0 + 1e-12),
        ("grade_probs", math.nan),
    ],
)
def test_extra_predictions_message_hides_values_and_paths(field: str, value: float) -> None:
    type_probs, grade_probs = _valid_rows()
    target = type_probs if field == "type_probs" else grade_probs
    target[1, 0] = value
    secret_paths = ("raw/S-001/fotó_secreta_ç.jpg", "/home/user/private/N-002__1.jpg")
    with pytest.raises(ValueError) as exc:
        _predictions(type_probs, grade_probs, paths=secret_paths)
    message = str(exc.value)
    assert field in message
    for path in secret_paths:
        assert path not in message
        assert Path(path).name not in message
    assert repr(value) not in message and str(value) not in message
    assert "1e-300" not in message and "1e-12" not in message


def test_extra_predictions_accept_float32_negative_zero_and_lists() -> None:
    type32 = np.array([[0.5, 0.25, 0.25], [1.0, 0.0, 0.0]], dtype=np.float32)
    grade32 = np.array([[-0.0, 0.0, 0.5, 0.5, 0.0], [0.2] * 5], dtype=np.float32)
    assert len(_predictions(type32, grade32)) == 2
    as_lists = _predictions([[0.2, 0.3, 0.5]], [[0.2, 0.2, 0.2, 0.2, 0.2]])
    assert as_lists.type_probs.shape == (1, 3)


def test_extra_predictions_empty_one_dimensional_arrays() -> None:
    empty = Predictions(
        split="test",
        image_paths=(),
        type_probs=np.array([]),
        grade_probs=np.array([]),
        true_type_idx=np.array([], dtype=np.int64),
        true_grade_idx=np.array([], dtype=np.int64),
    )
    assert len(empty) == 0


def test_extra_split_patterns_behave_as_before() -> None:
    pattern = split_mod.ITEM_ID_PATTERN
    for good in ("S-001", "N-999", "O-123", "T-000"):
        assert pattern.fullmatch(good), good
    for bad in ("X-001", "S-01", "S-0001", "s-001", "S_001", "S-00a", "Ｓ-001", "S-٠٠١"):
        assert not pattern.fullmatch(bad), bad
    image = split_mod.IMAGE_FILE_PATTERN
    match = image.fullmatch("S-001__2__20261019T120000Z.jpg")
    assert match and match.group(1) == "S-001"
    for bad in (
        "S-001__5__20261019T120000Z.jpg",
        "X-001__2__20261019T120000Z.jpg",
        "S-001__2__20261019T120000Z.jpeg",
        "S-001__2__20261019T120000.jpg",
    ):
        assert not image.fullmatch(bad), bad


def test_extra_notebook_export_check_targets_tmp_and_follows_install() -> None:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cells = notebook["cells"]
    idx = next(
        i
        for i, c in enumerate(cells)
        if c["cell_type"] == "code" and "make_tiny_fixture.py --out" in _source(c)
    )
    source = _source(cells[idx])
    assert "!python ml/scripts/make_tiny_fixture.py --out /tmp/export_check" in source
    assert "ml/tests/fixtures" not in source  # never overwrites the versioned fixture
    previous = cells[idx - 1]
    assert previous["cell_type"] == "markdown", _source(previous)
    install = [
        i
        for i, c in enumerate(cells)
        if c["cell_type"] == "code" and re.search(r"pip install .*-e \"?ml\[train\]", _source(c))
    ]
    assert install and install[0] < idx, (install, idx)


def test_extra_readme_mentions_torch_download_with_step_0() -> None:
    section = _readme_section(README.read_text(encoding="utf-8"), "Do Colab ao Release")
    step1 = re.search(r"(?m)^\s*1\.\s", section)
    assert step1 is not None
    step0 = section[: step1.start()]
    for name in ("split_v1.csv", "split_v1.sha256", "split_v1.json"):
        assert name in step0, name
    assert "2.14" in section, "the expected torch 2.14.x download in Colab is not documented"
