"""Acceptance tests for SPEC-012 (qc-ml: training, evaluation, thresholds, ONNX export, parity).

Written by the tester from the SPEC acceptance criteria (black box), through the public
interface: the CLIs (``python -m qc_ml.<module>`` in a subprocess or ``main(argv)``), the
functions and classes the SPEC names, and the artifacts on disk. One test per CA
(``test_caNN_*``); tests named ``test_extra_*`` are exploratory edge cases that no CA spells out.

Rules followed (``docs/architecture.md`` §10, R-11, R-14 and the ``ml-pipeline`` skill):

- every dataset is synthetic (``make_synthetic_dataset``) and lives under ``tmp_path``; nothing
  under ``ml/data/`` is ever read;
- every write or delete is checked to be inside the test's temporary directory first;
- no network (``pretrained=False``, ``HF_HUB_OFFLINE=1``) and no test runs the test suite in a
  subprocess;
- the *slow* tests (marked ``slow``) need torch and are skipped without it (CI); CA-28 is manual.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from PIL import Image

from qc_contracts import Grade, is_defective
from qc_ml import decision as decision_mod
from qc_ml import evaluate as evaluate_mod
from qc_ml import report as report_mod
from qc_ml import split as split_mod
from qc_ml import thresholds as thresholds_mod
from qc_ml.errors import ConfigError, SplitIntegrityError, TrainError
from qc_ml.evaluate import grade_metrics
from qc_ml.parity import check_parity
from qc_ml.predict import OnnxModel, Predictions
from qc_ml.synthetic import make_synthetic_dataset
from qc_ml.thresholds import choose_thresholds
from qc_ml.train import EarlyStopper, TrainConfig, grade_class_weights, load_config

pytestmark = pytest.mark.acceptance

REPO_ROOT = Path(__file__).resolve().parents[3]
ML_ROOT = REPO_ROOT / "ml"
TINY_MODEL = ML_ROOT / "tests" / "fixtures" / "tiny_model"
NOTEBOOK = ML_ROOT / "notebooks" / "train_colab.ipynb"
GRADES = [g.value for g in Grade]
OBJECT_TYPES = ["screw", "nut", "other"]
LABELS = {"object_types": OBJECT_TYPES, "grades": GRADES}
TINY_VERSION = "partqc-tinyacc-v1"
SMOKE_VERSION = "partqc-smoke-v1"
DECISION_KEYS = {"type_threshold", "unusable_threshold", "grade_review_threshold"}
TINY_FILES = {
    "model.onnx",
    "model.sha256",
    "labels.json",
    "preprocessing.json",
    "decision.json",
    "parity_fixture.npz",
}
METRIC_KEYS = {
    "model_version",
    "model_sha256",
    "evaluated_at",
    "split_file",
    "split_sha256",
    "manifest_sha256",
    "labels",
    "decision",
    "type_accuracy",
    "type_confusion",
    "grade_qwk",
    "grade_mae",
    "grade_off_by_one_accuracy",
    "grade_confusion",
    "grade_per_class",
    "unusable_recall",
    "unusable_precision",
    "defective_recall",
    "defective_precision",
    "unknown_rate_on_other",
    "false_unknown_rate",
    "needs_review_rate",
    "latency_ms_p50",
    "latency_ms_p95",
    "latency_machine",
    "latency_runs",
    "counts",
    "grade_qwk_ci95",
    "unusable_recall_ci95",
    "defective_recall_ci95",
    "n_items_test_by_grade",
    "warnings",
}
RATE_KEYS = (
    "type_accuracy",
    "grade_off_by_one_accuracy",
    "unusable_recall",
    "unusable_precision",
    "defective_recall",
    "defective_precision",
    "unknown_rate_on_other",
    "false_unknown_rate",
    "needs_review_rate",
)
LATENCY_KEYS = {"latency_ms_p50", "latency_ms_p95", "latency_machine", "latency_runs"}
TRAINING_CONFIG_KEYS = {
    "model_version",
    "config",
    "deviations_from_defaults",
    "labels",
    "split_file",
    "split_sha256",
    "manifest_sha256",
    "grade_class_weights",
    "history",
    "best_epoch",
    "best_val_grade_qwk",
    "stopped_early",
    "versions",
    "device",
    "git_commit",
    "started_at",
    "finished_at",
    "smoke",
}
HISTORY_KEYS = {"epoch", "phase", "train_loss", "val_loss", "val_type_accuracy", "val_grade_qwk"}
VERSION_LIBS = {
    "python",
    "torch",
    "torchvision",
    "timm",
    "numpy",
    "scikit-learn",
    "onnx",
    "onnxruntime",
    "coral-pytorch",
    "qc-preprocess",
    "qc-ml",
}


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _inside(path: Path, root: Path) -> Path:
    """Fail unless ``path`` is inside ``root`` (guard before any write or delete)."""
    resolved = Path(path).resolve()
    assert resolved.is_relative_to(Path(root).resolve()), f"{resolved} is outside {root}"
    return resolved


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["HF_HUB_OFFLINE"] = "1"
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(module: str, *args: str, cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=_env(),
        timeout=timeout,
        check=False,
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any, root: Path) -> Path:
    _inside(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _split_sha256(split_file: Path) -> str:
    return split_file.with_suffix(".sha256").read_text(encoding="utf-8").split()[0]


def _manifest_rows(dataset_dir: Path) -> list[dict[str, str]]:
    with (dataset_dir / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _split_map(split_file: Path) -> dict[str, str]:
    with split_file.open(encoding="utf-8", newline="") as fh:
        return {row["image_path"]: row["split"] for row in csv.DictReader(fh)}


def _all_files(root: Path) -> set[Path]:
    return {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()


def _make_config(
    root: Path, dataset_dir: Path, split_file: Path, version: str, **overrides: Any
) -> SimpleNamespace:
    config = {
        "model_version": version,
        "dataset_dir": str(dataset_dir),
        "split_file": str(split_file),
        "backbone": "tiny",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(root / "models"),
        "reports_root": str(root / "reports"),
        "checkpoints_root": str(root / "checkpoints"),
    }
    config.update(overrides)
    path = _write_json(root / f"{version}.json", config, root)
    return SimpleNamespace(
        config=path,
        root=root,
        model_dir=root / "models" / version,
        reports_dir=root / "reports" / version,
        checkpoints_dir=root / "checkpoints" / version,
        dataset_dir=dataset_dir,
        split_file=split_file,
    )


def _make_split_dataset(root: Path, **kwargs: Any) -> tuple[Path, Path]:
    dataset_dir = make_synthetic_dataset(root / "ds", **kwargs)
    splits_dir = root / "splits"
    assert split_mod.main(["--dataset-dir", str(dataset_dir), "--splits-dir", str(splits_dir)]) == 0
    return dataset_dir, splits_dir / "split_v1.csv"


@pytest.fixture(scope="session")
def _acc_split_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("acc012_template")
    _make_split_dataset(root, items_per_stratum=4)
    return root


@pytest.fixture
def acc_data(_acc_split_template: Path, tmp_path: Path) -> tuple[Path, Path]:
    """``(dataset_dir, split_v1.csv)`` copied into this test's ``tmp_path``."""
    target = _inside(tmp_path / "data", tmp_path)
    shutil.copytree(_acc_split_template, target)
    return target / "ds", target / "splits" / "split_v1.csv"


@pytest.fixture
def acc_tiny(acc_data: tuple[Path, Path], tmp_path: Path) -> SimpleNamespace:
    """Config whose model directory is a copy of ``ml/tests/fixtures/tiny_model``."""
    dataset_dir, split_file = acc_data
    env = _make_config(tmp_path, dataset_dir, split_file, TINY_VERSION)
    shutil.copytree(TINY_MODEL, _inside(env.model_dir, tmp_path))
    return env


def _preds(
    split: str,
    type_probs: list[list[float]],
    grade_probs: list[list[float]],
    true_type: list[int],
    true_grade: list[int],
) -> Predictions:
    return Predictions(
        split=split,
        image_paths=tuple(f"img_{i:03d}.jpg" for i in range(len(type_probs))),
        type_probs=np.asarray(type_probs, dtype=np.float64),
        grade_probs=np.asarray(grade_probs, dtype=np.float64),
        true_type_idx=np.asarray(true_type, dtype=np.int64),
        true_grade_idx=np.asarray(true_grade, dtype=np.int64),
    )


def _screw_type(m: float) -> list[float]:
    rest = (1.0 - m) / 2.0
    return [m, rest, rest]


def _one_grade(grade_idx: int, p: float) -> list[float]:
    rest = (1.0 - p) / 4.0
    return [p if k == grade_idx else rest for k in range(5)]


def _two_decimals(value: float) -> bool:
    return isinstance(value, float) and abs(value * 100 - round(value * 100)) < 1e-9


# ---------------------------------------------------------------------------------------------
# CA-01 to CA-03 (torch)
# ---------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_ca01_model_shapes_and_probabilities() -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("timm")
    from qc_ml.model import ProbabilityWrapper, build_model

    torch.manual_seed(0)
    x = torch.randn(2, 3, 224, 224)
    for head, n_grade_logits in (("ce", 5), ("corn", 4)):
        model = build_model("mobilenetv3_large_100", 3, head, pretrained=False).eval()
        with torch.no_grad():
            type_logits, grade_logits = model(x)
            type_probs, grade_probs = ProbabilityWrapper(model).eval()(x)
        assert tuple(type_logits.shape) == (2, 3), head
        assert tuple(grade_logits.shape) == (2, n_grade_logits), head
        assert tuple(type_probs.shape) == (2, 3), head
        assert tuple(grade_probs.shape) == (2, 5), head
        for probs in (type_probs, grade_probs):
            assert torch.allclose(probs.sum(dim=1), torch.ones(2), atol=1e-5), head
            assert bool((probs >= 0).all()), head


@pytest.mark.slow
def test_ca02_corn_zero_logits_to_probabilities() -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("timm")
    from qc_ml.model import ProbabilityWrapper, build_model

    expected = torch.tensor([0.5, 0.25, 0.125, 0.0625, 0.0625])
    # Through the exported module: a CORN model whose 4-logit grade head is zeroed.
    model = build_model("mobilenetv3_small_050", 3, "corn", pretrained=False).eval()
    heads = [m for m in model.modules() if isinstance(m, torch.nn.Linear) and m.out_features == 4]
    assert len(heads) == 1, "expected exactly one linear head with 4 outputs (CORN)"
    with torch.no_grad():
        heads[0].weight.zero_()
        heads[0].bias.zero_()
        _, grade_probs = ProbabilityWrapper(model).eval()(torch.randn(3, 3, 224, 224))
    for row in grade_probs:
        assert torch.allclose(row.double(), expected.double(), atol=1e-6), row


@pytest.mark.slow
def test_ca03_masked_grade_loss() -> None:
    torch = pytest.importorskip("torch")
    import torch.nn.functional as F  # noqa: N812

    from qc_ml.train import compute_loss

    torch.manual_seed(1)
    type_logits = torch.randn(6, 3)
    grade_logits = torch.randn(6, 5)
    type_idx = torch.tensor([0, 1, 2, 0, 1, 2])
    kwargs = {
        "grade_head": "ce",
        "label_smoothing": 0.1,
        "lambda_grade": 1.0,
        "grade_weights": None,
    }
    expected_type = F.cross_entropy(type_logits, type_idx, label_smoothing=0.1)

    no_grade = torch.full((6,), -1, dtype=torch.long)
    parts = compute_loss(type_logits, grade_logits, type_idx, no_grade, **kwargs)
    assert bool(torch.isfinite(parts.total))
    assert torch.allclose(parts.total, expected_type, atol=1e-7)

    mixed = torch.tensor([0, -1, 2, -1, 4, 1])
    mask = mixed >= 0
    expected_grade = F.cross_entropy(grade_logits[mask], mixed[mask], label_smoothing=0.1)
    parts = compute_loss(type_logits, grade_logits, type_idx, mixed, **kwargs)
    assert torch.allclose(parts.grade_loss, expected_grade, atol=1e-7)
    assert torch.allclose(parts.total, expected_type + expected_grade, atol=1e-6)


# ---------------------------------------------------------------------------------------------
# CA-04 to CA-06 (no torch)
# ---------------------------------------------------------------------------------------------


def test_ca04_grade_class_weights() -> None:
    counts = {"perfect": 100, "good": 100, "fair": 100, "poor": 100, "unusable": 40}
    weights = grade_class_weights(counts)
    assert weights is not None
    assert weights == pytest.approx([0.88, 0.88, 0.88, 0.88, 2.2], abs=1e-9)
    assert grade_class_weights({**counts, "unusable": 55}) is None
    with pytest.raises(TrainError):
        grade_class_weights({**counts, "unusable": 0})


def test_ca05_early_stopper() -> None:
    stopper = EarlyStopper(patience=5, min_delta=1e-4)
    decisions = [stopper.step(q) for q in [0.50, 0.60, 0.60, 0.60, 0.60, 0.60, 0.60]]
    assert decisions == [False] * 6 + [True]
    assert stopper.best_epoch == 2


def test_ca06_config_validation(tmp_path: Path) -> None:
    base = {"model_version": "partqc-mnv3-v1", "dataset_dir": "ds", "split_file": "s.csv"}

    def write(data: dict[str, Any]) -> Path:
        return _write_json(tmp_path / "cfg.json", data, tmp_path)

    with pytest.raises(ConfigError):
        load_config(write({**base, "epochs_a": 12, "smoke": False}))
    config = load_config(write({**base, "epochs_a": 12, "smoke": True}))
    assert config.epochs_a == 12
    assert config.smoke is True
    with pytest.raises(ConfigError):
        load_config(write({**base, "model_version": "PartQC v1"}))
    # The same rules hold for the dataclass itself.
    with pytest.raises(ConfigError):
        TrainConfig(model_version="PartQC v1", dataset_dir="ds", split_file="s.csv")


# ---------------------------------------------------------------------------------------------
# CA-07 to CA-10, CA-11 and CA-20 (slow): the smoke pipeline
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def smoke(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """Three smoke runs of the pipeline on the same synthetic dataset and split.

    ``a`` and ``b`` run ``python -m qc_ml.pipeline`` in subprocesses (CA-07 to CA-10); ``c`` runs
    ``pipeline.main`` in this process with a spy on ``qc_ml.split.rows_for`` (CA-20, slow).
    """
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    pytest.importorskip("onnx")
    root = tmp_path_factory.mktemp("acc012_smoke")
    dataset_dir, split_file = _make_split_dataset(root / "data", items_per_stratum=4)
    overrides = {"backbone": "mobilenetv3_small_050", "pretrained": False}
    runs: dict[str, SimpleNamespace] = {}
    for name in ("a", "b"):
        env = _make_config(root / name, dataset_dir, split_file, SMOKE_VERSION, **overrides)
        env.proc = _run("qc_ml.pipeline", "--config", str(env.config), cwd=root / name)
        runs[name] = env

    env = _make_config(root / "c", dataset_dir, split_file, SMOKE_VERSION, **overrides)
    calls: list[tuple[str, str, bool]] = []
    original = split_mod.rows_for
    decision_path = env.model_dir / "decision.json"

    def spy(df: Any, split_df: Any, which: str) -> Any:
        caller = sys._getframe(1).f_globals.get("__name__", "?")
        calls.append((which, caller, decision_path.exists()))
        return original(df, split_df, which)

    from qc_ml import pipeline as pipeline_mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HF_HUB_OFFLINE", "1")
        mp.setattr(split_mod, "rows_for", spy)
        env.code = pipeline_mod.main(["--config", str(env.config)])
    env.calls = calls
    runs["c"] = env
    return SimpleNamespace(**runs, dataset_dir=dataset_dir, split_file=split_file)


def _assert_ok(env: SimpleNamespace) -> None:
    proc = env.proc
    assert proc.returncode == 0, f"stdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-3000:]}"


@pytest.mark.slow
def test_ca07_pipeline_smoke_writes_every_artifact(smoke: SimpleNamespace) -> None:
    env = smoke.a
    _assert_ok(env)
    for name in (
        "model.onnx",
        "model.sha256",
        "labels.json",
        "preprocessing.json",
        "decision.json",
        "metrics.json",
        "training_config.json",
        "parity_fixture.npz",
    ):
        assert (env.model_dir / name).is_file(), name
    assert (env.reports_dir / "thresholds_report.json").is_file()
    for png in ("type_confusion.png", "grade_confusion.png"):
        with Image.open(env.reports_dir / png) as img:
            assert img.format == "PNG"
    # §4.2: checkpoints of the run.
    assert (env.checkpoints_dir / "last.pt").is_file()
    assert (env.checkpoints_dir / "best.pt").is_file()


@pytest.mark.slow
def test_ca08_training_config_contents(smoke: SimpleNamespace) -> None:
    env = smoke.a
    _assert_ok(env)
    tc = _read_json(env.model_dir / "training_config.json")
    assert set(tc) >= TRAINING_CONFIG_KEYS, TRAINING_CONFIG_KEYS - set(tc)
    assert tc["model_version"] == SMOKE_VERSION
    assert tc["smoke"] is True
    assert set(tc["versions"]) >= VERSION_LIBS, VERSION_LIBS - set(tc["versions"])
    for lib in ("torch", "timm", "onnxruntime"):
        assert isinstance(tc["versions"][lib], str) and tc["versions"][lib], lib
    assert tc["split_sha256"] == _split_sha256(smoke.split_file)
    expected_manifest = hashlib.sha256((smoke.dataset_dir / "manifest.csv").read_bytes())
    assert tc["manifest_sha256"] == expected_manifest.hexdigest()
    assert isinstance(tc["history"], list) and tc["history"]
    for entry in tc["history"]:
        assert set(entry) >= HISTORY_KEYS, entry
    assert {e["phase"] for e in tc["history"]} >= {"A", "B"} or len(tc["history"]) >= 2
    assert tc["best_epoch"] in {e["epoch"] for e in tc["history"]}
    assert isinstance(tc["deviations_from_defaults"], list)
    assert tc["labels"] == LABELS or tc["labels"] == {
        "object_types": tuple(OBJECT_TYPES),
        "grades": tuple(GRADES),
    }


@pytest.mark.slow
def test_ca09_same_seed_same_history(smoke: SimpleNamespace) -> None:
    _assert_ok(smoke.a)
    _assert_ok(smoke.b)
    first = _read_json(smoke.a.model_dir / "training_config.json")["history"]
    second = _read_json(smoke.b.model_dir / "training_config.json")["history"]
    assert len(first) == len(second)
    for e1, e2 in zip(first, second, strict=True):
        assert (e1["epoch"], e1["phase"]) == (e2["epoch"], e2["phase"])
        for key in ("val_grade_qwk", "train_loss", "val_loss"):
            if e1[key] is None or e2[key] is None:
                assert e1[key] is None and e2[key] is None, (key, e1, e2)
            else:
                assert e1[key] == pytest.approx(e2[key], abs=1e-6), (key, e1, e2)


@pytest.mark.slow
def test_ca10_onnx_model_contract(smoke: SimpleNamespace) -> None:
    onnx = pytest.importorskip("onnx")
    import onnxruntime as ort

    env = smoke.a
    _assert_ok(env)
    path = env.model_dir / "model.onnx"
    model = onnx.load(str(path))
    onnx.checker.check_model(model)
    opsets = {o.domain or "ai.onnx": o.version for o in model.opset_import}
    assert opsets.get("ai.onnx", 0) >= 17, opsets
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    assert [i.name for i in session.get_inputs()] == ["image"]
    assert [o.name for o in session.get_outputs()] == ["type_probs", "grade_probs"]
    rng = np.random.default_rng(0)
    for n in (1, 3):
        x = rng.standard_normal((n, 3, 224, 224)).astype(np.float32)
        type_probs, grade_probs = session.run(["type_probs", "grade_probs"], {"image": x})
        assert type_probs.shape == (n, 3)
        assert grade_probs.shape == (n, 5)
        assert np.allclose(type_probs.sum(axis=1), 1.0, atol=1e-5)
        assert np.allclose(grade_probs.sum(axis=1), 1.0, atol=1e-5)


@pytest.mark.slow
def test_ca11_smoke_model_sha256(smoke: SimpleNamespace) -> None:
    _assert_ok(smoke.a)
    _assert_sha_file(smoke.a.model_dir)
    # The parity fixture of the smoke export passes too (§4.3 runs check_parity after export).
    assert check_parity(smoke.a.model_dir).ok


@pytest.mark.slow
def test_ca20_pipeline_requests_test_once_from_evaluate(smoke: SimpleNamespace) -> None:
    env = smoke.c
    assert env.code == 0
    tests = [c for c in env.calls if c[0] == "test"]
    assert len(tests) == 1, env.calls
    which, caller, decision_exists = tests[0]
    assert caller == "qc_ml.evaluate", env.calls
    assert decision_exists, "the test split was requested before decision.json existed"
    for which, caller, _ in env.calls:
        if caller != "qc_ml.evaluate":
            assert which in {"train", "val"}, (which, caller)
    callers = {c[1] for c in env.calls}
    assert "qc_ml.train" in callers and "qc_ml.thresholds" in callers, callers


@pytest.mark.slow
def test_extra_in_process_run_matches_subprocess_history(smoke: SimpleNamespace) -> None:
    """A third smoke run (in process) gives the same history as the subprocess ones."""
    _assert_ok(smoke.a)
    assert smoke.c.code == 0
    first = _read_json(smoke.a.model_dir / "training_config.json")["history"]
    third = _read_json(smoke.c.model_dir / "training_config.json")["history"]
    for e1, e3 in zip(first, third, strict=True):
        for key in ("val_grade_qwk", "train_loss", "val_loss"):
            if e1[key] is not None:
                assert e1[key] == pytest.approx(e3[key], abs=1e-6), key


@pytest.mark.slow
def test_extra_smoke_metrics_json_is_complete(smoke: SimpleNamespace) -> None:
    env = smoke.a
    _assert_ok(env)
    metrics = _read_json(env.model_dir / "metrics.json")
    # SPEC-016 section 4.8: new top-level key tool_grade_metrics.
    assert set(metrics) == METRIC_KEYS | {"tool_grade_metrics"}
    assert metrics["model_sha256"] == (env.model_dir / "model.sha256").read_text().strip()
    assert metrics["decision"] == _read_json(env.model_dir / "decision.json")
    assert set(_read_json(env.model_dir / "decision.json")) == DECISION_KEYS


# ---------------------------------------------------------------------------------------------
# CA-11 to CA-14 (fixture and parity, CI)
# ---------------------------------------------------------------------------------------------


def _assert_sha_file(model_dir: Path) -> None:
    raw = (model_dir / "model.sha256").read_bytes()
    assert re.fullmatch(rb"[0-9a-f]{64}\n", raw), raw
    digest = hashlib.sha256((model_dir / "model.onnx").read_bytes()).hexdigest()
    assert raw.decode("ascii") == digest + "\n"


def _local_model_dirs() -> list[Path]:
    models = ML_ROOT / "models"
    if not models.is_dir():
        return []
    return sorted(p for p in models.iterdir() if (p / "model.onnx").is_file())


def test_ca11_model_sha256_matches_onnx() -> None:
    _assert_sha_file(TINY_MODEL)
    for model_dir in _local_model_dirs():
        _assert_sha_file(model_dir)


def test_ca12_parity_of_tiny_fixture(tmp_path: Path) -> None:
    copy = _inside(tmp_path / "tiny", tmp_path)
    shutil.copytree(TINY_MODEL, copy)
    result = check_parity(copy)
    assert result.ok is True
    assert result.max_abs_diff < 1e-4
    assert result.argmax_equal is True


def test_ca12_parity_of_local_models() -> None:
    dirs = _local_model_dirs()
    if not dirs:
        pytest.skip("no ml/models/*/model.onnx in this checkout")
    for model_dir in dirs:
        result = check_parity(model_dir)
        assert result.ok, (model_dir.name, result)
        assert result.max_abs_diff < 1e-4
        assert result.argmax_equal


def test_ca13_perturbed_fixture_fails_parity(tmp_path: Path) -> None:
    copy = _inside(tmp_path / "tiny", tmp_path)
    shutil.copytree(TINY_MODEL, copy)
    fixture_path = _inside(copy / "parity_fixture.npz", tmp_path)
    with np.load(fixture_path, allow_pickle=False) as data:
        arrays = {key: data[key].copy() for key in data.files}
    arrays["type_probs"][0, 0] += 1e-3
    np.savez_compressed(fixture_path, **arrays)
    result = check_parity(copy)
    assert result.ok is False
    # CA-13 (r2, SPEC_ISSUE-01): 1e-3 -/+ 1e-4, never an exact 1e-3 bound (float32 noise).
    assert 9e-4 < result.max_abs_diff < 1.1e-3, result.max_abs_diff


def test_ca14_tiny_fixture_files_size_and_git() -> None:
    names = {p.name for p in TINY_MODEL.iterdir() if p.is_file()}
    assert names >= TINY_FILES, TINY_FILES - names
    total = sum((TINY_MODEL / n).stat().st_size for n in TINY_FILES)
    assert total < 1_000_000, total
    for name in sorted(TINY_FILES):
        rel = (TINY_MODEL / name).relative_to(REPO_ROOT)
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", str(rel)], cwd=REPO_ROOT, check=False
        )
        assert ignored.returncode == 1, f"{rel} is ignored by git"
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(rel)],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
        assert tracked.returncode == 0, f"{rel} is not tracked"
    assert _read_json(TINY_MODEL / "decision.json") == {
        "type_threshold": 0.70,
        "unusable_threshold": 0.50,
        "grade_review_threshold": 0.60,
    }
    assert _read_json(TINY_MODEL / "labels.json") == LABELS


# ---------------------------------------------------------------------------------------------
# CA-15 to CA-19: thresholds on the validation split only
# ---------------------------------------------------------------------------------------------


def test_ca15_thresholds_refuse_test_and_train(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    before = _all_files(tmp_path)
    for split in ("test", "train"):
        preds = _preds(split, [[0.9, 0.05, 0.05]], [_one_grade(1, 0.9)], [0], [1])
        with pytest.raises(SplitIntegrityError):
            choose_thresholds(preds, LABELS)
    assert _all_files(tmp_path) == before


def test_ca16_type_threshold_max_with_false_unknown_at_most_5pct() -> None:
    ms = [0.503 + 0.005 * i for i in range(100)]
    type_probs = [_screw_type(m) for m in ms]
    grade_probs = [_one_grade(1, 0.8)] * 100
    preds = _preds("val", type_probs, grade_probs, [0] * 100, [1] * 100)
    result = choose_thresholds(preds, LABELS)
    assert result.decision["type_threshold"] == 0.52
    assert "type_target_not_met" not in result.report["notes"]

    for i in range(94, 100):  # 6 images now have argmax ``other``
        m = ms[i]
        type_probs[i] = [(1 - m) / 2, (1 - m) / 2, m]
    preds = _preds("val", type_probs, grade_probs, [0] * 100, [1] * 100)
    result = choose_thresholds(preds, LABELS)
    assert result.decision["type_threshold"] == 0.50
    assert "type_target_not_met" in result.report["notes"]


def test_ca17_unusable_threshold_for_recall_90pct() -> None:
    p_unusable = [0.45, 0.40, 0.35, 0.30, 0.25, 0.22, 0.18, 0.15, 0.125, 0.05]
    type_probs = [[0.99, 0.005, 0.005]] * 10
    grade_probs = [[0.0, 0.0, 1.0 - (0.55 + p), 0.55, p] for p in p_unusable]
    preds = _preds("val", type_probs, grade_probs, [0] * 10, [4] * 10)
    result = choose_thresholds(preds, LABELS)
    assert result.decision["unusable_threshold"] == 0.12
    assert "unusable_target_not_met" not in result.report["notes"]
    decided = decision_mod.apply_decision(type_probs, grade_probs, LABELS, result.decision)
    recall = sum(g == "unusable" for g in decided.grades) / 10
    assert recall == pytest.approx(0.9)

    low = [[0.0, 0.0, 0.44, 0.55, 0.01]] * 10
    preds = _preds("val", type_probs, low, [0] * 10, [4] * 10)
    result = choose_thresholds(preds, LABELS)
    assert "unusable_target_not_met" in result.report["notes"]


def test_ca18_review_threshold_targets_10pct() -> None:
    type_probs = [[0.99, 0.005, 0.005]] * 100

    conf = [0.3025 + 0.005 * i for i in range(100)]
    grade_probs = [_one_grade(1, c) for c in conf]
    preds = _preds("val", type_probs, grade_probs, [0] * 100, [1] * 100)
    result = choose_thresholds(preds, LABELS)
    assert result.decision["type_threshold"] == 0.85
    assert result.decision["grade_review_threshold"] == 0.35
    assert "review_adjusted" in result.report["notes"]
    decided = decision_mod.apply_decision(type_probs, grade_probs, LABELS, result.decision)
    assert float(np.mean(decided.needs_review)) == pytest.approx(0.10)

    conf = [min(0.5525 + 0.005 * i, 1.0) for i in range(100)]
    grade_probs = [_one_grade(1, c) for c in conf]
    preds = _preds("val", type_probs, grade_probs, [0] * 100, [1] * 100)
    result = choose_thresholds(preds, LABELS)
    assert result.decision["grade_review_threshold"] == 0.60
    assert "review_adjusted" not in result.report["notes"]


def test_ca19_thresholds_cli_writes_decision_and_report(acc_tiny: SimpleNamespace) -> None:
    decision_path = _inside(acc_tiny.model_dir / "decision.json", acc_tiny.root)
    decision_path.unlink()  # the fixture copy ships one; prove the CLI writes it
    proc = _run("qc_ml.thresholds", "--config", str(acc_tiny.config), cwd=acc_tiny.root)
    assert proc.returncode == 0, proc.stderr
    decision = _read_json(decision_path)
    assert set(decision) == DECISION_KEYS
    for key in DECISION_KEYS:
        assert _two_decimals(decision[key]), (key, decision[key])
    assert 0.50 <= decision["type_threshold"] <= 0.85
    assert 0.05 <= decision["unusable_threshold"] <= 0.95
    assert 0.30 <= decision["grade_review_threshold"] <= 0.95
    report = _read_json(acc_tiny.reports_dir / "thresholds_report.json")
    assert {"notes", "n_val_images", "split_sha256"} <= set(report), set(report)
    assert report["split_sha256"] == _split_sha256(acc_tiny.split_file)
    n_val = sum(1 for s in _split_map(acc_tiny.split_file).values() if s == "val")
    assert report["n_val_images"] == n_val
    assert not (acc_tiny.model_dir / "metrics.json").exists()


# ---------------------------------------------------------------------------------------------
# CA-20 to CA-24: evaluation (single consumer of the test split)
# ---------------------------------------------------------------------------------------------


def test_ca20_test_split_requested_once_by_evaluate(acc_tiny: SimpleNamespace, monkeypatch) -> None:
    decision_path = _inside(acc_tiny.model_dir / "decision.json", acc_tiny.root)
    decision_path.unlink()
    calls: list[tuple[str, str, bool]] = []
    original = split_mod.rows_for

    def spy(df: Any, split_df: Any, which: str) -> Any:
        caller = sys._getframe(1).f_globals.get("__name__", "?")
        calls.append((which, caller, decision_path.exists()))
        return original(df, split_df, which)

    monkeypatch.setattr(split_mod, "rows_for", spy)
    assert thresholds_mod.main(["--config", str(acc_tiny.config)]) == 0
    thresholds_calls = list(calls)
    assert thresholds_calls, "thresholds never asked for a split through qc_ml.split.rows_for"
    assert {c[0] for c in thresholds_calls} <= {"train", "val"}, thresholds_calls
    assert "val" in {c[0] for c in thresholds_calls}
    assert evaluate_mod.main(["--config", str(acc_tiny.config)]) == 0
    tests = [c for c in calls if c[0] == "test"]
    assert len(tests) == 1, calls
    assert tests[0][1] == "qc_ml.evaluate"
    assert tests[0][2] is True


def test_ca21_evaluate_without_decision_json(acc_tiny: SimpleNamespace) -> None:
    _inside(acc_tiny.model_dir / "decision.json", acc_tiny.root).unlink()
    before = _all_files(acc_tiny.root)
    proc = _run("qc_ml.evaluate", "--config", str(acc_tiny.config), cwd=acc_tiny.root)
    assert proc.returncode == 2
    assert "run qc_ml.thresholds first" in proc.stderr + proc.stdout
    assert not (acc_tiny.model_dir / "metrics.json").exists()
    assert _all_files(acc_tiny.root) == before


def _test_images_with_grade(dataset_dir: Path, split_file: Path) -> int:
    split = _split_map(split_file)
    return sum(
        1
        for row in _manifest_rows(dataset_dir)
        if split.get(row["image_path"]) == "test"
        and row["object_type"] in {"screw", "nut"}
        and row["grade"]
    )


def _check_metrics(metrics: dict[str, Any], dataset_dir: Path, split_file: Path) -> None:
    # SPEC-016 section 4.8: new top-level key tool_grade_metrics.
    expected_keys = METRIC_KEYS | {"tool_grade_metrics"}
    assert set(metrics) == expected_keys, set(metrics) ^ expected_keys
    for key in ("grade_qwk_ci95", "unusable_recall_ci95", "defective_recall_ci95"):
        ci = metrics[key]
        if ci is not None:
            assert isinstance(ci, list) and len(ci) == 2, (key, ci)
            assert all(isinstance(v, int | float) for v in ci), (key, ci)
            assert ci[0] <= ci[1], (key, ci)
    assert isinstance(metrics["warnings"], list)
    assert all(isinstance(w, str) for w in metrics["warnings"])
    tc = np.asarray(metrics["type_confusion"])
    assert tc.shape == (3, 3)
    gc = np.asarray(metrics["grade_confusion"])
    assert gc.shape == (5, 5)
    assert int(gc.sum()) == _test_images_with_grade(dataset_dir, split_file)
    assert set(metrics["grade_per_class"]) == set(GRADES)
    for grade, stats in metrics["grade_per_class"].items():
        assert {"precision", "recall", "f1", "support"} <= set(stats), grade
        if stats["support"] == 0:
            assert stats["recall"] is None, (grade, stats)
            assert stats["f1"] is None, (grade, stats)
        for k in ("precision", "recall", "f1"):
            assert stats[k] is None or 0.0 <= stats[k] <= 1.0, (grade, k, stats)
    for key in RATE_KEYS:
        value = metrics[key]
        assert value is None or 0.0 <= value <= 1.0, (key, value)
    assert metrics["grade_qwk"] is None or -1.0 <= metrics["grade_qwk"] <= 1.0
    assert set(metrics["n_items_test_by_grade"]) == set(GRADES)


def test_ca22_metrics_json_contents(acc_tiny: SimpleNamespace) -> None:
    assert evaluate_mod.main(["--config", str(acc_tiny.config)]) == 0
    metrics = _read_json(acc_tiny.model_dir / "metrics.json")
    _check_metrics(metrics, acc_tiny.dataset_dir, acc_tiny.split_file)
    # Total of the type confusion = every test image.
    n_test = sum(1 for s in _split_map(acc_tiny.split_file).values() if s == "test")
    assert int(np.asarray(metrics["type_confusion"]).sum()) == n_test
    for png in ("type_confusion.png", "grade_confusion.png"):
        with Image.open(acc_tiny.reports_dir / png) as img:
            assert img.format == "PNG"
            assert img.size[0] > 50 and img.size[1] > 50


def test_ca23_grade_metrics_example() -> None:
    m = grade_metrics([0, 1, 2, 3, 4, 0, 1, 2, 3, 4], [0, 1, 2, 4, 4, 0, 2, 2, 3, 4])
    assert m["grade_qwk"] == pytest.approx(20 / 21, abs=1e-4)
    assert m["grade_qwk"] == pytest.approx(0.9524, abs=1e-4)
    assert m["grade_mae"] == pytest.approx(0.2)
    assert m["grade_off_by_one_accuracy"] == pytest.approx(1.0)
    assert m["unusable_recall"] == pytest.approx(1.0)
    assert m["unusable_precision"] == pytest.approx(0.6667, abs=1e-4)
    assert m["defective_recall"] == pytest.approx(1.0)
    assert m["defective_precision"] == pytest.approx(1.0)


def test_ca24_latency_only_rewrites_only_latency(acc_tiny: SimpleNamespace) -> None:
    assert evaluate_mod.main(["--config", str(acc_tiny.config)]) == 0
    before = _read_json(acc_tiny.model_dir / "metrics.json")
    proc = _run(
        "qc_ml.evaluate",
        "--config",
        str(acc_tiny.config),
        "--latency-only",
        "--latency-machine",
        "notebook-borda",
        cwd=acc_tiny.root,
    )
    assert proc.returncode == 0, proc.stderr
    after = _read_json(acc_tiny.model_dir / "metrics.json")
    assert set(after) == set(before)
    changed = {k for k in before if before[k] != after[k]}
    assert changed <= LATENCY_KEYS, changed
    assert after["latency_runs"] == 100
    assert after["latency_machine"] == "notebook-borda"
    assert after["latency_ms_p50"] > 0 and after["latency_ms_p95"] >= after["latency_ms_p50"]


# ---------------------------------------------------------------------------------------------
# CA-25 to CA-27
# ---------------------------------------------------------------------------------------------


def _metrics_stub(**values: Any) -> dict[str, Any]:
    metrics: dict[str, Any] = dict.fromkeys(METRIC_KEYS)
    metrics.update(
        {
            "model_version": "partqc-mnv3-v1",
            "model_sha256": "0" * 64,
            "evaluated_at": "2026-10-18T12:00:00+00:00",
            "split_file": "split_v1.csv",
            "split_sha256": "1" * 64,
            "manifest_sha256": "2" * 64,
            "labels": LABELS,
            "decision": {
                "type_threshold": 0.7,
                "unusable_threshold": 0.5,
                "grade_review_threshold": 0.6,
            },
            "latency_machine": "notebook-borda",
            "latency_runs": 100,
            "warnings": [],
        }
    )
    metrics.update(values)
    return metrics


def _table_line(entry: str, needle: str) -> str:
    lines = [ln for ln in entry.splitlines() if ln.lstrip().startswith("|") and needle in ln]
    assert len(lines) == 1, (needle, lines, entry)
    return lines[0]


def test_ca25_changelog_display_rule(tmp_path: Path) -> None:
    model_dir = tmp_path / "models" / "partqc-mnv3-v1"
    metrics = _metrics_stub(type_accuracy=0.93127, grade_qwk=0.75, latency_ms_p95=120.00001)
    _write_json(model_dir / "metrics.json", metrics, tmp_path)
    proc = _run("qc_ml.report", "changelog", "--model-dir", str(model_dir), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    entry = proc.stdout
    assert re.search(r"^## partqc-mnv3-v1 — \d{4}-\d{2}-\d{2}\s*$", entry, re.M), entry
    assert "0,9313" not in entry
    accuracy = _table_line(entry, "0,9312")
    assert "≥ 0,95" in accuracy and "abaixo da meta" in accuracy, accuracy
    qwk = _table_line(entry, "0,7500")
    assert "≥ 0,75" in qwk and "atingida" in qwk and "abaixo" not in qwk, qwk
    latency = _table_line(entry, "120,0001")
    assert "≤ 300" in latency and "atingida" in latency and "abaixo" not in latency, latency
    assert "120,0000" not in entry
    assert "O que mudou" in entry and "Problemas conhecidos" in entry


def test_ca26_notebook_is_clean() -> None:
    notebook = _read_json(NOTEBOOK)
    code_cells = [c for c in notebook["cells"] if c["cell_type"] == "code"]
    assert code_cells
    sources = []
    for cell in code_cells:
        assert cell.get("outputs") == [], cell
        assert cell.get("execution_count") is None, cell
        source = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        assert "def " not in source, source
        assert "class " not in source, source
        assert not re.search(r"ghp_|github_pat_|token\s*=\s*[\"']", source), source
        sources.append(source)
    assert any("python -m qc_ml.pipeline" in s for s in sources)


def test_ca27_modules_import_without_torch() -> None:
    code = (
        "import importlib, sys\n"
        "sys.modules['torch'] = None\n"
        "for name in ('predict', 'decision', 'thresholds', 'evaluate', 'parity', 'report'):\n"
        "    importlib.import_module('qc_ml.' + name)\n"
        "assert sys.modules['torch'] is None\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=_env(), check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


# ---------------------------------------------------------------------------------------------
# Exploratory (no CA)
# ---------------------------------------------------------------------------------------------


def test_extra_evaluate_refuses_tampered_or_missing_model(acc_tiny: SimpleNamespace) -> None:
    """§4.7: without model.onnx or a valid model.sha256 the CLI exits 2 and writes nothing."""
    onnx_path = _inside(acc_tiny.model_dir / "model.onnx", acc_tiny.root)
    data = onnx_path.read_bytes()
    onnx_path.write_bytes(data + b"\x00")
    before = _all_files(acc_tiny.root)
    proc = _run("qc_ml.evaluate", "--config", str(acc_tiny.config), cwd=acc_tiny.root)
    assert proc.returncode == 2
    assert _all_files(acc_tiny.root) == before
    with pytest.raises(Exception):  # noqa: B017 - any error is fine, as long as it refuses
        OnnxModel(acc_tiny.model_dir)

    onnx_path.unlink()
    before = _all_files(acc_tiny.root)
    proc = _run("qc_ml.evaluate", "--config", str(acc_tiny.config), cwd=acc_tiny.root)
    assert proc.returncode == 2
    assert _all_files(acc_tiny.root) == before


def test_extra_bad_sha_file_format_is_refused(acc_tiny: SimpleNamespace) -> None:
    sha = _inside(acc_tiny.model_dir / "model.sha256", acc_tiny.root)
    sha.write_text(sha.read_text().strip().upper() + "\n")
    proc = _run("qc_ml.evaluate", "--config", str(acc_tiny.config), cwd=acc_tiny.root)
    assert proc.returncode == 2
    assert not (acc_tiny.model_dir / "metrics.json").exists()


def test_extra_latency_only_without_metrics(acc_tiny: SimpleNamespace) -> None:
    before = _all_files(acc_tiny.root)
    proc = _run(
        "qc_ml.evaluate", "--config", str(acc_tiny.config), "--latency-only", cwd=acc_tiny.root
    )
    assert proc.returncode == 2
    assert _all_files(acc_tiny.root) == before


def test_extra_evaluate_is_deterministic(acc_tiny: SimpleNamespace) -> None:
    """Fixed bootstrap seed: two evaluations give the same metrics except time and latency."""
    assert evaluate_mod.main(["--config", str(acc_tiny.config)]) == 0
    first = _read_json(acc_tiny.model_dir / "metrics.json")
    assert evaluate_mod.main(["--config", str(acc_tiny.config)]) == 0
    second = _read_json(acc_tiny.model_dir / "metrics.json")
    changed = {k for k in first if first[k] != second[k]}
    assert changed <= LATENCY_KEYS | {"evaluated_at"}, changed


def test_extra_metrics_counts_and_hashes(acc_tiny: SimpleNamespace) -> None:
    assert evaluate_mod.main(["--config", str(acc_tiny.config)]) == 0
    metrics = _read_json(acc_tiny.model_dir / "metrics.json")
    assert metrics["model_version"] == TINY_VERSION
    assert metrics["model_sha256"] == (acc_tiny.model_dir / "model.sha256").read_text().strip()
    assert metrics["split_sha256"] == _split_sha256(acc_tiny.split_file)
    manifest = hashlib.sha256((acc_tiny.dataset_dir / "manifest.csv").read_bytes()).hexdigest()
    assert metrics["manifest_sha256"] == manifest
    assert metrics["decision"] == _read_json(acc_tiny.model_dir / "decision.json")
    assert metrics["latency_runs"] == 100
    assert re.search(r"[+-]\d{2}:\d{2}$|Z$", metrics["evaluated_at"]), metrics["evaluated_at"]
    split = _split_map(acc_tiny.split_file)
    rows = _manifest_rows(acc_tiny.dataset_dir)
    for name in ("train", "val", "test"):
        in_split = [r for r in rows if split[r["image_path"]] == name]
        counts = metrics["counts"][name]
        assert counts["n_images"] == len(in_split)
        assert counts["n_items"] == len({r["item_id"] for r in in_split})
        for obj in {r["object_type"] for r in in_split}:
            of_type = [r for r in in_split if r["object_type"] == obj]
            assert counts["by_class"][obj]["n_images"] == len(of_type)
            assert counts["by_class"][obj]["n_items"] == len({r["item_id"] for r in of_type})
    test_rows = [r for r in rows if split[r["image_path"]] == "test" and r["grade"]]
    for grade in GRADES:
        items = {r["item_id"] for r in test_rows if r["grade"] == grade}
        assert metrics["n_items_test_by_grade"][grade] == len(items), grade
    # A grade with fewer than 2 test items must be flagged in ``warnings`` (skill §5).
    if any(metrics["n_items_test_by_grade"][g] < 2 for g in GRADES):
        assert metrics["warnings"], metrics["n_items_test_by_grade"]


def _write_custom_split(dataset_dir: Path, splits_dir: Path, assign: dict[str, str]) -> Path:
    """A split_v1 that keeps every item in one split (``assign``: item_id -> split)."""
    rows = _manifest_rows(dataset_dir)
    lines = ["image_path,split"]
    lines += [f"{r['image_path']},{assign[r['item_id']]}" for r in rows]
    data = ("\n".join(lines) + "\n").encode("utf-8")
    csv_path = _inside(splits_dir / "split_v1.csv", splits_dir.parent)
    splits_dir.mkdir(parents=True, exist_ok=True)
    csv_path.write_bytes(data)
    csv_path.with_suffix(".sha256").write_text(
        f"{hashlib.sha256(data).hexdigest()}  split_v1.csv\n", encoding="utf-8"
    )
    return csv_path


def test_extra_test_split_without_unusable_reports_null(tmp_path: Path) -> None:
    """No ``unusable`` item in test: its metrics are ``null`` and never omitted (§4.7)."""
    dataset_dir = make_synthetic_dataset(_inside(tmp_path / "ds", tmp_path), items_per_stratum=4)
    rows = _manifest_rows(dataset_dir)
    item_grade = {r["item_id"]: (r["object_type"], r["grade"]) for r in rows}
    assign: dict[str, str] = {}
    counter: dict[tuple[str, str], int] = {}
    for item, (obj, grade) in sorted(item_grade.items()):
        k = counter.get((obj, grade), 0)
        counter[(obj, grade)] = k + 1
        if grade == "unusable":
            assign[item] = "train" if k % 2 == 0 else "val"
        else:
            assign[item] = ("train", "val", "test", "train")[k % 4]
    split_file = _write_custom_split(dataset_dir, tmp_path / "splits", assign)
    env = _make_config(tmp_path, dataset_dir, split_file, TINY_VERSION)
    shutil.copytree(TINY_MODEL, _inside(env.model_dir, tmp_path))
    assert evaluate_mod.main(["--config", str(env.config)]) == 0
    metrics = _read_json(env.model_dir / "metrics.json")
    _check_metrics(metrics, dataset_dir, split_file)
    stats = metrics["grade_per_class"]["unusable"]
    assert stats["support"] == 0
    assert stats["recall"] is None
    assert metrics["unusable_recall"] is None
    assert metrics["unusable_recall_ci95"] is None
    assert metrics["n_items_test_by_grade"]["unusable"] == 0
    assert metrics["warnings"]


def test_extra_thresholds_cli_refuses_tampered_split(acc_tiny: SimpleNamespace) -> None:
    decision_path = _inside(acc_tiny.model_dir / "decision.json", acc_tiny.root)
    decision_path.unlink()
    split_csv = _inside(acc_tiny.split_file, acc_tiny.root)
    split_csv.write_text(split_csv.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    proc = _run("qc_ml.thresholds", "--config", str(acc_tiny.config), cwd=acc_tiny.root)
    assert proc.returncode == 2
    assert not decision_path.exists()
    assert not (acc_tiny.reports_dir / "thresholds_report.json").exists()


def test_extra_thresholds_cli_with_unicode_paths(tmp_path: Path) -> None:
    root = _inside(tmp_path / "Área de dados ç", tmp_path)
    dataset_dir, split_file = _make_split_dataset(root, items_per_stratum=4)
    env = _make_config(root, dataset_dir, split_file, TINY_VERSION)
    shutil.copytree(TINY_MODEL, _inside(env.model_dir, tmp_path))
    proc = _run("qc_ml.thresholds", "--config", str(env.config), cwd=root)
    assert proc.returncode == 0, proc.stderr
    assert set(_read_json(env.model_dir / "decision.json")) == DECISION_KEYS


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_version": "partqc-MNV3-v1"},
        {"model_version": "partqc-mnv3"},
        {"model_version": "partqc-" + "a" * 40 + "-v1"},
        {"model_version": "partqc-mnv3-v1 "},
        {"epochs_a": 4, "smoke": False},
        {"backbone": "resnet50", "smoke": False},
        {"unknown_key": 1},
    ],
)
def test_extra_config_rejects(tmp_path: Path, overrides: dict[str, Any]) -> None:
    base = {"model_version": "partqc-mnv3-v1", "dataset_dir": "ds", "split_file": "s.csv"}
    path = _write_json(tmp_path / "cfg.json", {**base, **overrides}, tmp_path)
    with pytest.raises(ConfigError):
        load_config(path)


def test_extra_config_accepts_bounds_and_effb0(tmp_path: Path) -> None:
    base = {"model_version": "partqc-effb0-v2", "dataset_dir": "ds", "split_file": "s.csv"}
    for epochs_a in (5, 10):
        path = _write_json(
            tmp_path / "cfg.json",
            {**base, "epochs_a": epochs_a, "backbone": "efficientnet_b0"},
            tmp_path,
        )
        assert load_config(path).epochs_a == epochs_a
    assert load_config(ML_ROOT / "configs" / "partqc-mnv3-v1.json").model_version == (
        "partqc-mnv3-v1"
    )


def test_extra_grade_class_weights_missing_grade_and_balanced() -> None:
    with pytest.raises(TrainError):
        grade_class_weights({"perfect": 10, "good": 10, "fair": 10, "poor": 10})
    assert grade_class_weights(dict.fromkeys(GRADES, 7)) is None


def test_extra_early_stopper_min_delta_and_undefined() -> None:
    stopper = EarlyStopper(patience=2, min_delta=1e-4)
    # Improvements smaller than min_delta do not reset the patience.
    assert [stopper.step(v) for v in (0.5, 0.50005, 0.50009)] == [False, False, True]
    assert stopper.best_epoch == 1
    stopper = EarlyStopper(patience=2, min_delta=1e-4)
    assert [stopper.step(v) for v in (None, 0.1, None, None)] == [False, False, False, True]
    assert stopper.best_epoch == 2


def test_extra_decision_rule_examples() -> None:
    thresholds = {"type_threshold": 0.70, "unusable_threshold": 0.30, "grade_review_threshold": 0.6}
    decided = decision_mod.apply_decision(
        [[0.9, 0.05, 0.05], [0.2, 0.2, 0.6], [0.65, 0.3, 0.05], [0.75, 0.2, 0.05]],
        [[0.1, 0.2, 0.2, 0.2, 0.3], [0.2] * 5, [0.2] * 5, [0.0, 0.9, 0.1, 0.0, 0.0]],
        LABELS,
        thresholds,
    )
    r0, r1, r2, r3 = (decided.record(i) for i in range(4))
    assert r0["object_type"] == "screw" and r0["grade"] == "unusable"
    assert r0["grade_confidence"] == pytest.approx(0.3)
    assert r0["grade_score"] == pytest.approx(0.2 + 0.4 + 0.6 + 1.2)
    assert r0["needs_review"] is True  # grade confidence 0.3 < 0.6
    assert r1["object_type"] == "unknown" and r1["grade"] is None  # argmax other
    assert r1["grade_score"] is None and r1["grade_confidence"] is None
    assert r2["object_type"] == "unknown" and r2["needs_review"] is True  # 0.65 < 0.70
    assert r3["object_type"] == "screw" and r3["grade"] == "good"
    assert r3["needs_review"] is True  # 0.75 < 0.70 + 0.10


def test_extra_decision_matches_edge_when_installed() -> None:
    """§6: qc_ml.decision and qc_edge.decision agree (the edge is part of this workspace)."""
    edge = pytest.importorskip("qc_edge.decision")
    rng = np.random.default_rng(7)
    raw = {"type_threshold": 0.6, "unusable_threshold": 0.35, "grade_review_threshold": 0.6}
    edge_labels = edge.ModelLabels(object_types=tuple(OBJECT_TYPES), grades=tuple(GRADES))
    edge_thresholds = edge.Thresholds(**raw)
    for _ in range(500):
        tp = rng.dirichlet(np.ones(3) * 0.7)
        gp = rng.dirichlet(np.ones(5) * 0.7)
        ours = decision_mod.apply_decision(tp, gp, LABELS, raw).record(0)
        theirs = edge.decide(tp.tolist(), gp.tolist(), edge_labels, edge_thresholds)
        assert getattr(theirs.object_type, "value", theirs.object_type) == ours["object_type"]
        assert getattr(theirs.grade, "value", theirs.grade) == ours["grade"]
        assert theirs.needs_review == ours["needs_review"]
        for key in ("grade_score", "grade_confidence", "type_confidence"):
            a, b = getattr(theirs, key), ours[key]
            assert (a is None) == (b is None), key
            if a is not None:
                assert a == pytest.approx(b, abs=1e-9), key


def test_extra_choose_thresholds_no_unusable_in_val() -> None:
    preds = _preds("val", [[0.99, 0.005, 0.005]] * 4, [_one_grade(1, 0.9)] * 4, [0] * 4, [1] * 4)
    result = choose_thresholds(preds, LABELS)
    assert result.decision["unusable_threshold"] == 0.50
    assert "no_unusable_in_val" in result.report["notes"]
    assert set(dict(result.decision)) == DECISION_KEYS


def test_extra_parity_rejects_other_model_sha(tmp_path: Path) -> None:
    copy = _inside(tmp_path / "tiny", tmp_path)
    shutil.copytree(TINY_MODEL, copy)
    fixture_path = _inside(copy / "parity_fixture.npz", tmp_path)
    with np.load(fixture_path, allow_pickle=False) as data:
        arrays = {key: data[key].copy() for key in data.files}
    arrays["model_sha256"] = np.asarray("f" * 64)
    np.savez_compressed(fixture_path, **arrays)
    assert check_parity(copy).ok is False


def test_extra_parity_fixture_shapes() -> None:
    with np.load(TINY_MODEL / "parity_fixture.npz", allow_pickle=False) as data:
        assert {"inputs", "type_probs", "grade_probs", "model_sha256"} <= set(data.files)
        assert data["inputs"].dtype == np.float32
        assert data["inputs"].shape == (8, 3, 224, 224)
        assert data["type_probs"].shape == (8, 3)
        assert data["grade_probs"].shape == (8, 5)
        assert str(data["model_sha256"]) == (TINY_MODEL / "model.sha256").read_text().strip()


def test_extra_changelog_null_previous_and_append(tmp_path: Path) -> None:
    current = tmp_path / "models" / "partqc-mnv3-v2"
    previous = tmp_path / "models" / "partqc-mnv3-v1"
    _write_json(
        current / "metrics.json",
        _metrics_stub(model_version="partqc-mnv3-v2", type_accuracy=0.97, grade_mae=0.12341),
        tmp_path,
    )
    _write_json(previous / "metrics.json", _metrics_stub(type_accuracy=0.9), tmp_path)
    changelog = _inside(tmp_path / "CHANGELOG.md", tmp_path)
    changelog.write_text("# CHANGELOG\n", encoding="utf-8")
    proc = _run(
        "qc_ml.report",
        "changelog",
        "--model-dir",
        str(current),
        "--previous",
        str(previous),
        "--append",
        str(changelog),
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    text = changelog.read_text(encoding="utf-8")
    assert text.startswith("# CHANGELOG\n")
    assert "## partqc-mnv3-v2 — 2026-10-18" in text
    accuracy = _table_line(text, "0,9700")
    assert "0,9000" in accuracy and "atingida" in accuracy, accuracy
    assert "0,1235" in text  # grade_mae: lower is better, rounded up
    qwk = [ln for ln in text.splitlines() if ln.startswith("|") and "≥ 0,75" in ln]
    assert len(qwk) == 1 and "n/d" in qwk[0], qwk  # grade_qwk null


def test_extra_changelog_ci_widened() -> None:
    entry = report_mod.changelog_entry(_metrics_stub(grade_qwk_ci95=[0.61239, 0.81231]))
    assert "0,6123" in entry and "0,8124" in entry, entry


def test_extra_notebook_python_check_and_secret_source() -> None:
    notebook = _read_json(NOTEBOOK)
    text = "\n".join(
        "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
        for c in notebook["cells"]
    )
    assert "sys.version_info[:2] == (3, 12)" in text
    assert "google.colab" in text and "userdata" in text
    assert not re.search(r"ghp_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}", text)
    assert "qc_ml.data validate" in text


def test_extra_readme_documents_colab_to_release_flow() -> None:
    readme = (ML_ROOT / "README.md").read_text(encoding="utf-8")
    for needle in (
        "gh release create",
        "gh release download",
        "sha256sum",
        "--latency-only",
        "qc_ml.report changelog",
    ):
        assert needle in readme, needle


def test_extra_defective_rule_matches_contracts() -> None:
    m = grade_metrics([3, 4, 2, 1], [2, 3, 4, 0])
    true_def = [is_defective(GRADES[g]) for g in (3, 4, 2, 1)]
    pred_def = [is_defective(GRADES[g]) for g in (2, 3, 4, 0)]
    both = sum(t and p for t, p in zip(true_def, pred_def, strict=True))
    assert m["defective_recall"] == pytest.approx(both / sum(true_def))
    assert m["defective_precision"] == pytest.approx(both / sum(pred_def))


def test_extra_grade_metrics_empty_is_null() -> None:
    m = grade_metrics([], [])
    for key in ("grade_qwk", "grade_mae", "unusable_recall", "defective_recall"):
        assert m[key] is None, key


@pytest.mark.slow
def test_extra_training_config_timestamps_are_utc(smoke: SimpleNamespace) -> None:
    _assert_ok(smoke.a)
    tc = _read_json(smoke.a.model_dir / "training_config.json")
    for key in ("started_at", "finished_at"):
        assert re.search(r"(\+00:00|Z)$", tc[key]), (key, tc[key])
    assert tc["started_at"] <= tc["finished_at"]
    assert tc["config"]["model_version"] == SMOKE_VERSION
    phases = [e["phase"] for e in tc["history"]]
    assert phases == sorted(phases), phases  # phase A epochs come before phase B


@pytest.mark.slow
def test_extra_corn_smoke_pipeline_exports_probabilities(tmp_path: Path) -> None:
    """Ablation head (CORN) end to end: ONNX grade output is already a probability vector."""
    pytest.importorskip("torch")
    pytest.importorskip("coral_pytorch")
    import onnxruntime as ort

    dataset_dir, split_file = _make_split_dataset(tmp_path / "data", items_per_stratum=4)
    env = _make_config(
        tmp_path,
        dataset_dir,
        split_file,
        "partqc-smokecorn-v2",
        backbone="mobilenetv3_small_050",
        grade_head="corn",
    )
    proc = _run("qc_ml.pipeline", "--config", str(env.config), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert check_parity(env.model_dir).ok
    session = ort.InferenceSession(
        str(env.model_dir / "model.onnx"), providers=["CPUExecutionProvider"]
    )
    x = np.random.default_rng(3).standard_normal((2, 3, 224, 224)).astype(np.float32)
    _, grade_probs = session.run(["type_probs", "grade_probs"], {"image": x})
    assert grade_probs.shape == (2, 5)
    assert np.allclose(grade_probs.sum(axis=1), 1.0, atol=1e-5)
    assert (grade_probs >= 0).all()
    # SPEC-016 section 4.8: new top-level key tool_grade_metrics.
    assert set(_read_json(env.model_dir / "metrics.json")) == METRIC_KEYS | {"tool_grade_metrics"}


@pytest.mark.slow
def test_extra_resume_with_other_config_is_refused(tmp_path: Path) -> None:
    """§4.2: ``--resume`` continues from last.pt; a different config is a ConfigError (exit 2)."""
    pytest.importorskip("torch")
    pytest.importorskip("timm")
    dataset_dir, split_file = _make_split_dataset(tmp_path / "data", items_per_stratum=4)
    env = _make_config(
        tmp_path, dataset_dir, split_file, SMOKE_VERSION, backbone="mobilenetv3_small_050"
    )
    assert _run("qc_ml.pipeline", "--config", str(env.config), cwd=tmp_path).returncode == 0
    history = _read_json(env.model_dir / "training_config.json")["history"]

    proc = _run("qc_ml.pipeline", "--config", str(env.config), "--resume", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr[-3000:]
    resumed = _read_json(env.model_dir / "training_config.json")["history"]
    assert len(resumed) == len(history)
    for e1, e2 in zip(history, resumed, strict=True):
        assert e1["train_loss"] == pytest.approx(e2["train_loss"], abs=1e-6)

    changed = _read_json(env.config)
    changed["lr_b"] = 5e-4
    _write_json(env.config, changed, tmp_path)
    proc = _run("qc_ml.pipeline", "--config", str(env.config), "--resume", cwd=tmp_path)
    assert proc.returncode == 2
    assert "config" in (proc.stderr + proc.stdout).lower()
