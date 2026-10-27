"""Acceptance tests for SPEC-008 (qc-edge: ONNX inference and the edge decision rule).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. One ``test_caNN_*`` per CA, at least; ``test_extra_*`` are exploratory edge
cases around the SPEC that no CA spells out.

Rules followed (``reviews/checklist.md`` and ``docs/architecture.md`` §10):

* the dummy ONNX models are built here with ``onnx.helper`` (opset 17, SPEC §6), in ``tmp_path``,
  without torch and without any binary in Git;
* images are synthetic and generated in memory (R-14), never photos;
* every token is built at run time (no credential literal in a URL or header);
* no test runs the test suite in a subprocess; CA-17 runs pytest on explicit file paths only
  (the author's decision tests and the decision CAs of this file, never itself);
* r2: the ``test_bug_t01_*`` of r1 were replaced by CA-19 and CA-20 (stricter: exact clamped
  values) and by a property test over real onnxruntime ``Softmax`` outputs; the r1
  ``test_extra_symlinked_model_dir_uses_the_link_name``, invalidated by §4.2 item 3, was
  rewritten as ``test_extra_symlinked_model_dir_uses_the_target_name`` (SPEC §6);
* the only boundaries replaced are ``uvicorn.run`` (spy), the LAN socket and, in CA-16, nothing:
  CA-16 is manual (``slow``) and is skipped without ``QC_REAL_MODEL_DIR``.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import math
import os
import re
import secrets
import statistics
import subprocess
import sys
import threading
import types
import uuid
from collections.abc import Callable, Sequence
from dataclasses import FrozenInstanceError, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import onnx
import onnxruntime as ort
import pytest
import uvicorn
from fastapi.testclient import TestClient
from onnx import TensorProto, helper
from PIL import Image, ImageFile

import qc_edge.cli
import qc_edge.netinfo
from qc_contracts import Grade, InspectionCreate, ObjectType
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.decision import (
    REVIEW_MARGIN,
    Decision,
    InvalidModelOutputError,
    ModelLabels,
    Thresholds,
    decide,
)
from qc_edge.inference import InferenceError, InferenceResult, ModelInfo
from qc_edge.onnx_inferencer import ModelIntegrityError, ModelLoadError, OnnxInferencer
from qc_edge.sink import InMemorySink
from qc_preprocess import PreprocessParams

pytestmark = pytest.mark.acceptance

EDGE_ROOT = Path(__file__).resolve().parents[2]  # edge/
ROOT = EDGE_ROOT.parent  # repository root

EDGE_ENV_VARS = (
    "EDGE_HOST",
    "EDGE_PORT",
    "EDGE_SESSION_TOKEN",
    "DEVICE_ID",
    "EDGE_DATA_DIR",
    "DEVICE_API_KEY",
    "CLOUD_API_URL",
    "MODEL_DIR",
    "DATASET_DIR",
    "OUTBOX_PATH",
    "TYPE_THRESHOLD",
    "UNUSABLE_THRESHOLD",
    "GRADE_REVIEW_THRESHOLD",
)
THRESHOLD_NAMES = ("type_threshold", "unusable_threshold", "grade_review_threshold")
SESSION_HEADER = "X-Session-Token"

GRADES = ("perfect", "good", "fair", "poor", "unusable")
CA_LABELS = ModelLabels(object_types=("screw", "nut", "other"), grades=GRADES)
CA_THRESHOLDS = Thresholds(type_threshold=0.5, unusable_threshold=0.4, grade_review_threshold=0.6)
CA_DECISION_JSON = {"type_threshold": 0.5, "unusable_threshold": 0.4, "grade_review_threshold": 0.6}

DUMMY_TYPE = [0.9, 0.05, 0.05]
DUMMY_GRADE = [0.05, 0.8, 0.05, 0.05, 0.05]
NEUTRAL_GRADE = [0.0, 0.7, 0.1, 0.1, 0.1]

FIXED_INPUT_SHAPE: tuple[int | str, ...] = ("N", 3, 224, 224)  # SPEC §6, default dummy input
DYNAMIC_INPUT_SHAPE: tuple[int | str, ...] = ("N", 3, "H", "W")  # CA-22 variant


# =========================================================================== dummy models


def build_dummy_onnx(
    type_probs: Sequence[float],
    grade_probs: Sequence[float],
    *,
    input_name: str = "image",
    type_name: str = "type_probs",
    grade_name: str = "grade_probs",
    input_shape: Sequence[int | str] = FIXED_INPUT_SHAPE,
) -> bytes:
    """Dummy model of SPEC §6: ReduceMean(input) → Reshape [N,1] → Mul 0 → Add constants.

    The outputs are the constants ``[1,T]`` and ``[1,5]`` broadcast over the batch, whatever the
    input (``ReduceMean`` works with any H×W, so the dynamic input of CA-22 is accepted). The
    constants are float32. ``ir_version`` 8 (opset 17) is fixed so the locked ``onnxruntime``
    accepts it (§7).
    """
    t = len(type_probs)
    g = len(grade_probs)
    inp = helper.make_tensor_value_info(input_name, TensorProto.FLOAT, list(input_shape))
    out_t = helper.make_tensor_value_info(type_name, TensorProto.FLOAT, ["N", t])
    out_g = helper.make_tensor_value_info(grade_name, TensorProto.FLOAT, ["N", g])
    inits = [
        helper.make_tensor("shape_n1", TensorProto.INT64, [2], [-1, 1]),
        helper.make_tensor("zero", TensorProto.FLOAT, [], [0.0]),
        helper.make_tensor("type_const", TensorProto.FLOAT, [1, t], list(type_probs)),
        helper.make_tensor("grade_const", TensorProto.FLOAT, [1, g], list(grade_probs)),
    ]
    nodes = [
        helper.make_node("ReduceMean", [input_name], ["mean"], axes=[1, 2, 3], keepdims=0),
        helper.make_node("Reshape", ["mean", "shape_n1"], ["mean_n1"]),
        helper.make_node("Mul", ["mean_n1", "zero"], ["zeros_n1"]),
        helper.make_node("Add", ["zeros_n1", "type_const"], [type_name]),
        helper.make_node("Add", ["zeros_n1", "grade_const"], [grade_name]),
    ]
    graph = helper.make_graph(nodes, "acc-dummy", [inp], [out_t, out_g], initializer=inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model.SerializeToString()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_model_dir(
    root: Path,
    name: str = "dummy-v1",
    *,
    type_probs: Sequence[float] = DUMMY_TYPE,
    grade_probs: Sequence[float] = DUMMY_GRADE,
    object_types: Sequence[str] = ("screw", "nut", "other"),
    grades: Sequence[str] = GRADES,
    decision: dict[str, Any] | None = None,
    model_bytes: bytes | None = None,
    sha_text: str | None = None,
    preprocessing: str | None = None,
    skip: Sequence[str] = (),
    input_shape: Sequence[int | str] = FIXED_INPUT_SHAPE,
) -> Path:
    """Model directory of ``architecture.md`` §7 (``model.onnx`` and the four JSON/hash files)."""
    d = root / name
    d.mkdir(parents=True, exist_ok=False)
    data = (
        model_bytes
        if model_bytes is not None
        else build_dummy_onnx(type_probs, grade_probs, input_shape=input_shape)
    )
    files = {
        "model.onnx": data,
        "model.sha256": (
            sha_text if sha_text is not None else f"{sha256_hex(data)}  model.onnx\n"
        ).encode(),
        "labels.json": json.dumps(
            {"object_types": list(object_types), "grades": list(grades)}
        ).encode(),
        "preprocessing.json": preprocessing.encode() if preprocessing is not None else None,
        "decision.json": json.dumps(
            decision if decision is not None else CA_DECISION_JSON
        ).encode(),
    }
    for fname, content in files.items():
        if fname in skip:
            continue
        if content is None:  # default preprocessing: PreprocessParams.to_json (SPEC-002)
            PreprocessParams().to_json(d / fname)
        else:
            (d / fname).write_bytes(content)
    return d


# =========================================================================== images


def synthetic_jpeg(width: int = 1280, height: int = 960, seed: int = 8) -> bytes:
    """Synthetic textured JPEG (gradient plus noise: no person, no real photo; R-14)."""
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 255, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 255, height, dtype=np.float32)[:, None]
    base = np.stack([x + 0 * y, y + 0 * x, (x + y) / 2], axis=-1)
    noise = rng.normal(0, 18, (height, width, 3))
    arr = np.clip(base + noise, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def open_jpeg(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img.convert("RGB")


# =========================================================================== edge fixtures


def new_token() -> str:
    value = secrets.token_urlsafe(30)
    assert len(value) == 40
    return value


@dataclass
class Edge:
    tmp: Path
    data_dir: Path
    token: str

    def captures(self) -> list[Path]:
        root = self.data_dir / "captures"
        return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


def fake_socket_module(probe_ip: str) -> Any:
    class FakeSocket:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> FakeSocket:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def settimeout(self, value: float | None) -> None:
            pass

        def setblocking(self, flag: bool) -> None:
            pass

        def setsockopt(self, *args: Any) -> None:
            pass

        def connect(self, address: Any) -> None:
            pass

        def getsockname(self) -> tuple[str, int]:
            return (probe_ip, 54321)

        def close(self) -> None:
            pass

    module = types.SimpleNamespace(**vars(__import__("socket")))
    module.socket = FakeSocket
    module.getaddrinfo = lambda *a, **k: []
    module.gethostname = lambda: "acc-notebook"
    return module


@pytest.fixture
def edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Edge:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    data_dir = tmp_path / "edge-data"
    token = new_token()
    monkeypatch.setenv("EDGE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    monkeypatch.setattr(qc_edge.netinfo, "socket", fake_socket_module("192.168.0.42"))
    return Edge(tmp=tmp_path, data_dir=data_dir, token=token)


@pytest.fixture
def models(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    root.mkdir()
    return root


class UvicornSpy:
    def __init__(self, on_call: Callable[[Any], None] | None = None) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.on_call = on_call

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))
        if self.on_call is not None:
            self.on_call(args[0] if args else kwargs.get("app"))


def run_main(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["qc-edge", *args])
    try:
        qc_edge.cli.main()
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return 0


def captured_text(caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> str:
    out = capsys.readouterr()
    return "\n".join([caplog.text, out.out, out.err])


def post_capture(client: TestClient, token: str, image: bytes, lot_id: str = "L-001") -> Any:
    return client.post(
        "/api/capture",
        headers={SESSION_HEADER: token},
        data={"lot_id": lot_id, "mode": "inspect"},
        files={"image": ("foto.jpg", image, "image/jpeg")},
    )


def asgi_get(app: Any, path: str = "/") -> httpx.Response:
    """Console GET from loopback (``Host: 127.0.0.1:<EDGE_PORT>``, SPEC-025)."""
    port = os.environ.get("EDGE_PORT", "8000")

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url=f"http://127.0.0.1:{port}") as c:
            return await c.get(path)

    return asyncio.run(go())


def ca_decide(type_probs: Sequence[float], grade_probs: Sequence[float]) -> Decision:
    return decide(type_probs, grade_probs, CA_LABELS, CA_THRESHOLDS)


def p95(values: Sequence[float]) -> float:
    """Nearest-rank 95th percentile."""
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


# =========================================================================== CA-01


def test_ca01_other_type_is_unknown_without_review() -> None:
    d = ca_decide([0.1, 0.1, 0.8], NEUTRAL_GRADE)
    assert d.object_type == ObjectType.UNKNOWN
    assert d.grade is None
    assert d.grade_score is None
    assert d.grade_confidence is None
    assert d.type_confidence == pytest.approx(0.8, abs=1e-12)
    assert d.needs_review is False


# =========================================================================== CA-02


def test_ca02_low_type_confidence_is_unknown_and_needs_review() -> None:
    d = ca_decide([0.45, 0.30, 0.25], NEUTRAL_GRADE)
    assert d.object_type == ObjectType.UNKNOWN
    assert d.needs_review is True
    assert d.grade is None and d.grade_score is None and d.grade_confidence is None
    assert d.type_confidence == pytest.approx(0.45, abs=1e-12)  # §4.1 item 2: always reported


# =========================================================================== CA-03


def test_ca03_type_threshold_is_strict() -> None:
    d = ca_decide([0.5, 0.3, 0.2], NEUTRAL_GRADE)
    assert d.object_type == ObjectType.SCREW
    assert d.needs_review is True  # 0.5 < 0.5 + 0.10
    assert d.type_confidence == pytest.approx(0.5, abs=1e-12)


# =========================================================================== CA-04


def test_ca04_review_margin_boundary_and_grade_score() -> None:
    assert REVIEW_MARGIN == 0.10
    d = ca_decide([0.6, 0.3, 0.1], [0.0, 0.7, 0.1, 0.1, 0.1])
    assert d.object_type == ObjectType.SCREW
    assert d.needs_review is False
    assert d.grade == Grade.GOOD
    assert d.grade_confidence == pytest.approx(0.7, abs=1e-12)
    assert d.grade_score == pytest.approx(1.6, abs=1e-9)


# =========================================================================== CA-05


def test_ca05_unusable_threshold_is_inclusive() -> None:
    d = ca_decide([0.05, 0.9, 0.05], [0.45, 0.05, 0.05, 0.05, 0.4])
    assert d.object_type == ObjectType.NUT
    assert d.grade == Grade.UNUSABLE
    assert d.grade_confidence == pytest.approx(0.4, abs=1e-12)

    below = ca_decide([0.05, 0.9, 0.05], [0.46, 0.05, 0.05, 0.05, 0.39])
    assert below.object_type == ObjectType.NUT
    assert below.grade == Grade.PERFECT
    assert below.grade_confidence == pytest.approx(0.46, abs=1e-12)


# =========================================================================== CA-06


def test_ca06_grade_review_threshold() -> None:
    at = ca_decide([0.9, 0.05, 0.05], [0.1, 0.6, 0.1, 0.1, 0.1])
    assert at.object_type == ObjectType.SCREW
    assert at.grade == Grade.GOOD
    assert at.grade_confidence == 0.6
    assert at.needs_review is False

    below = ca_decide([0.9, 0.05, 0.05], [0.11, 0.59, 0.1, 0.1, 0.1])
    assert below.grade == Grade.GOOD
    assert below.grade_confidence == pytest.approx(0.59, abs=1e-12)
    assert below.needs_review is True


# =========================================================================== CA-07


@pytest.mark.parametrize(
    ("type_probs", "grade_probs"),
    [
        ([0.5, 0.5, 0.5], NEUTRAL_GRADE),
        ([0.9, float("nan"), 0.1], NEUTRAL_GRADE),
        ([0.9, 0.05, 0.05], [float("nan"), 0.7, 0.1, 0.1, 0.1]),
        ([1.1, -0.1, 0.0], NEUTRAL_GRADE),
        ([0.9, 0.05, 0.05], [-0.1, 0.8, 0.1, 0.1, 0.1]),
        ([0.9, 0.05, 0.05], [0.25, 0.25, 0.25, 0.25]),
    ],
    ids=["sum-1.5", "nan-type", "nan-grade", "negative-type", "negative-grade", "four-grades"],
)
def test_ca07_invalid_outputs_raise(
    type_probs: Sequence[float], grade_probs: Sequence[float]
) -> None:
    with pytest.raises(InvalidModelOutputError):
        ca_decide(type_probs, grade_probs)
    assert issubclass(InvalidModelOutputError, InferenceError)  # SPEC-007 base class


# =========================================================================== CA-08


def test_ca08_infer_with_the_dummy_model(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1")
    sha = sha256_hex((d / "model.onnx").read_bytes())
    inf = OnnxInferencer(d)
    assert inf.model_info == ModelInfo("dummy-v1", sha)

    res = inf.infer(open_jpeg(synthetic_jpeg(1280, 960)))
    assert isinstance(res, InferenceResult)
    assert res.object_type == ObjectType.SCREW
    assert res.grade == Grade.GOOD
    assert isinstance(res.latency_ms, int) and not isinstance(res.latency_ms, bool)
    assert res.latency_ms >= 0
    assert res.type_confidence == pytest.approx(0.9, abs=1e-6)
    assert res.grade_confidence == pytest.approx(0.8, abs=1e-6)
    assert res.grade_score == pytest.approx(0.8 + 0.1 + 0.15 + 0.2, abs=1e-5)
    assert res.needs_review is False


def test_ca08_capture_route_with_the_dummy_model(edge: Edge, models: Path) -> None:
    d = make_model_dir(models, "dummy-v1")
    sha = sha256_hex((d / "model.onnx").read_bytes())
    sink = InMemorySink()
    app = create_app(EdgeSettings(), OnnxInferencer(d), sink)
    with TestClient(app) as client:
        r = post_capture(client, edge.token, synthetic_jpeg(1280, 960))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inspection"]["model_version"] == "dummy-v1"
    assert body["inspection"]["object_type"] == "screw"
    assert body["inspection"]["grade"] == "good"
    assert body["approved"] is True
    items = sink.items
    assert len(items) == 1
    insp = items[0]
    assert isinstance(insp, InspectionCreate)
    assert insp.model_version == "dummy-v1"
    assert insp.model_sha256 == sha
    assert insp.model_dump(mode="json") == body["inspection"]


def test_ca08_cli_loads_model_dir(
    edge: Edge, models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MODEL_DIR`` set → the CLI builds the ONNX inferencer (§4.4) and captures use it."""
    d = make_model_dir(models, "dummy-v1")
    sha = sha256_hex((d / "model.onnx").read_bytes())
    monkeypatch.setenv("MODEL_DIR", str(d))
    seen: dict[str, Any] = {}

    def drive(app: Any) -> None:
        with TestClient(app) as client:
            r = post_capture(client, edge.token, synthetic_jpeg(1280, 960))
            seen["capture"] = r
            seen["status"] = client.get("/api/status", headers={SESSION_HEADER: edge.token})

    monkeypatch.setattr(uvicorn, "run", UvicornSpy(drive))
    assert run_main(monkeypatch) == 0
    r = seen["capture"]
    assert r.status_code == 200, r.text
    insp = r.json()["inspection"]
    assert insp["model_version"] == "dummy-v1"
    assert insp["model_sha256"] == sha
    assert insp["source"] == "live"
    model = seen["status"].json()["model"]
    assert model["loaded"] is True
    assert model["model_version"] == "dummy-v1"


# =========================================================================== CA-09


def test_ca09_hash_mismatch_raises_integrity_error(models: Path) -> None:
    data = build_dummy_onnx(DUMMY_TYPE, DUMMY_GRADE)
    real = sha256_hex(data)
    wrong = sha256_hex(b"another model")
    d = make_model_dir(models, "dummy-v1", model_bytes=data, sha_text=f"{wrong}  model.onnx\n")
    with pytest.raises(ModelIntegrityError) as info:
        OnnxInferencer(d)
    msg = str(info.value)
    assert wrong[:12] in msg
    assert real[:12] in msg
    assert isinstance(info.value, ModelLoadError)


def test_ca09_cli_exits_2_on_hash_mismatch(
    edge: Edge,
    models: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = build_dummy_onnx(DUMMY_TYPE, DUMMY_GRADE)
    wrong = sha256_hex(b"another model")
    d = make_model_dir(models, "dummy-v1", model_bytes=data, sha_text=wrong + "\n")
    monkeypatch.setenv("MODEL_DIR", str(d))
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    caplog.set_level(logging.DEBUG)
    assert run_main(monkeypatch) == 2
    assert spy.calls == []
    text = captured_text(caplog, capsys)
    assert wrong[:12] in text and sha256_hex(data)[:12] in text


def test_ca09_real_process_exits_2(tmp_path: Path, models: Path) -> None:
    """The real ``qc-edge`` process (not the test suite) exits with code 2."""
    data = build_dummy_onnx(DUMMY_TYPE, DUMMY_GRADE)
    wrong = sha256_hex(b"another model")
    d = make_model_dir(models, "dummy-v1", model_bytes=data, sha_text=wrong + "\n")
    env = {k: v for k, v in os.environ.items() if k not in EDGE_ENV_VARS}
    env.update(
        EDGE_HOST="127.0.0.1",
        EDGE_PORT="1",  # never bound: the model check comes first
        EDGE_SESSION_TOKEN=new_token(),
        EDGE_DATA_DIR=str(tmp_path / "data"),
        MODEL_DIR=str(d),
    )
    proc = subprocess.run(
        [sys.executable, "-c", "from qc_edge.cli import main; main()"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert wrong[:12] in proc.stdout + proc.stderr


# =========================================================================== CA-10


@pytest.mark.parametrize(
    ("object_types", "grades"),
    [
        # SPEC-016 section 3.1: pliers is a valid label now; a value still outside the contract.
        (("screw", "hammer", "other"), GRADES),
        (("screw", "unknown"), GRADES),
        (("screw", "nut", "other"), ("good", "perfect", "fair", "poor", "unusable")),
        (("screw", "nut", "other"), ("perfect", "good", "fair", "unusable", "poor")),
    ],
    ids=["hammer", "unknown", "grades-swapped", "grades-swapped-tail"],
)
def test_ca10_invalid_labels(
    models: Path, object_types: Sequence[str], grades: Sequence[str]
) -> None:
    t = len(object_types)
    d = make_model_dir(
        models,
        "dummy-v1",
        type_probs=[1.0 / t] * t,
        object_types=object_types,
        grades=grades,
    )
    with pytest.raises(ModelLoadError) as info:
        OnnxInferencer(d)
    assert "labels.json" in str(info.value)


# =========================================================================== CA-11


def test_ca11_missing_decision_json(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1", skip=("decision.json",))
    with pytest.raises(ModelLoadError) as info:
        OnnxInferencer(d)
    assert "decision.json" in str(info.value)


def test_ca11_decision_threshold_out_of_range(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1", decision={**CA_DECISION_JSON, "type_threshold": 1.2})
    with pytest.raises(ModelLoadError) as info:
        OnnxInferencer(d)
    assert "decision.json" in str(info.value)


# =========================================================================== CA-12


def test_ca12_env_override_wins(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1", decision={**CA_DECISION_JSON, "type_threshold": 0.7})
    plain = OnnxInferencer(d)
    assert plain.thresholds.type_threshold == 0.7
    assert plain.threshold_sources["type_threshold"] == "decision.json"

    inf = OnnxInferencer(d, overrides={"TYPE_THRESHOLD": 0.55})
    assert inf.thresholds.type_threshold == 0.55
    assert inf.threshold_sources["type_threshold"] == "env"
    assert inf.thresholds.unusable_threshold == 0.4
    assert inf.threshold_sources["unusable_threshold"] == "decision.json"
    assert inf.thresholds.grade_review_threshold == 0.6
    assert inf.threshold_sources["grade_review_threshold"] == "decision.json"


def test_ca12_env_override_through_the_cli(
    edge: Edge, models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = make_model_dir(models, "dummy-v1", decision={**CA_DECISION_JSON, "type_threshold": 0.7})
    monkeypatch.setenv("MODEL_DIR", str(d))
    monkeypatch.setenv("TYPE_THRESHOLD", "0.55")
    seen: dict[str, Any] = {}

    def drive(app: Any) -> None:
        with TestClient(app) as client:
            seen["status"] = client.get("/api/status", headers={SESSION_HEADER: edge.token})

    monkeypatch.setattr(uvicorn, "run", UvicornSpy(drive))
    assert run_main(monkeypatch) == 0
    thresholds = seen["status"].json()["model"]["thresholds"]
    assert thresholds["type_threshold"] == {"value": 0.55, "source": "env"}
    assert thresholds["unusable_threshold"] == {"value": 0.4, "source": "decision.json"}


@pytest.mark.parametrize("value", ["1.5", "abc"])
def test_ca12_invalid_env_threshold_exits_2(
    edge: Edge,
    models: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    d = make_model_dir(models, "dummy-v1")
    monkeypatch.setenv("MODEL_DIR", str(d))
    monkeypatch.setenv("TYPE_THRESHOLD", value)
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    caplog.set_level(logging.DEBUG)
    assert run_main(monkeypatch) == 2
    assert spy.calls == []
    assert "TYPE_THRESHOLD" in captured_text(caplog, capsys)


# =========================================================================== CA-13


def test_ca13_type_output_shape_mismatch(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1", type_probs=[0.7, 0.1, 0.1, 0.1])  # [N,4], 3 labels
    with pytest.raises(ModelLoadError):
        OnnxInferencer(d)


def test_ca13_input_not_named_image(models: Path) -> None:
    data = build_dummy_onnx(DUMMY_TYPE, DUMMY_GRADE, input_name="input")
    d = make_model_dir(models, "dummy-v1", model_bytes=data)
    with pytest.raises(ModelLoadError):
        OnnxInferencer(d)


# =========================================================================== CA-14


def test_ca14_invalid_model_output_is_500_and_nothing_stored(edge: Edge, models: Path) -> None:
    d = make_model_dir(models, "dummy-v1", type_probs=[0.5, 0.5, 0.5])
    sink = InMemorySink()
    app = create_app(EdgeSettings(), OnnxInferencer(d), sink)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = post_capture(client, edge.token, synthetic_jpeg(640, 480))
    assert r.status_code == 500
    assert r.json() == {"detail": "inference failed"}
    assert sink.stats().pending == 0
    assert edge.captures() == []


# =========================================================================== CA-15


def test_ca15_latency_p95_with_the_dummy_model(models: Path) -> None:
    inf = OnnxInferencer(make_model_dir(models, "dummy-v1"))
    img = open_jpeg(synthetic_jpeg(1280, 960))
    latencies = [inf.infer(img).latency_ms for _ in range(50)]
    assert len(latencies) == 50
    assert all(isinstance(v, int) and v >= 0 for v in latencies)
    assert p95(latencies) <= 300, latencies


# =========================================================================== CA-16 (manual)

REAL_MODEL_ENV = "QC_REAL_MODEL_DIR"
FIXTURES_DIR = EDGE_ROOT / "tests" / "fixtures"


def ca16_images() -> list[Image.Image]:
    """Photos from ``edge/tests/fixtures/`` (CA-16, step 3) or, if there are none, synthetic.

    The fixtures folder is filled by the pair on the demo notebook; it never holds people (R-14).
    """
    paths = sorted(
        p
        for p in FIXTURES_DIR.glob("*")
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if paths:
        from qc_preprocess import load_image

        return [load_image(p.read_bytes()) for p in paths]
    return [open_jpeg(synthetic_jpeg(1280, 960, seed=s)) for s in range(5)]


@pytest.mark.slow
def test_ca16_real_model_latency(record_property: Callable[[str, object], None]) -> None:
    real = os.environ.get(REAL_MODEL_ENV, "").strip()
    if not real:
        pytest.skip(f"{REAL_MODEL_ENV} not set (manual CA-16, real model of SPEC-012)")
    inf = OnnxInferencer(Path(real))
    images = ca16_images()
    inf.infer(images[0])  # warm-up
    latencies = [inf.infer(images[i % len(images)]).latency_ms for i in range(50)]
    p50 = statistics.median(latencies)
    p95_value = p95(latencies)
    cpu = _cpu_name()
    record_property("p50_ms", p50)
    record_property("p95_ms", p95_value)
    record_property("cpu", cpu)
    sys.stderr.write(
        f"\nCA-16 {inf.model_info.model_version}: p50={p50} ms p95={p95_value} ms "
        f"images={len(images)} cpu={cpu}\n"
    )
    assert p95_value <= 300, latencies


def _cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    import platform

    return platform.processor() or platform.machine()


# =========================================================================== CA-17


def test_ca17_decision_coverage_at_least_80(tmp_path: Path) -> None:
    """Coverage of ``qc_edge.decision`` from the author's decision tests plus the decision CAs.

    Runs pytest on explicit file paths only (``architecture.md`` §10): the author's
    ``test_decision.py`` and the CA-01 to CA-07 and CA-19 tests of this file, never this test.
    A subset of the two suites gives a lower bound of the CA's coverage, so ≥ 80% here implies
    ≥ 80% for the full suites.
    """
    report = tmp_path / "cov.json"
    this = Path(__file__).relative_to(ROOT).as_posix()
    author = (EDGE_ROOT / "tests" / "test_decision.py").relative_to(ROOT).as_posix()
    env = dict(os.environ)
    env.pop("COV_CORE_SOURCE", None)
    decision_cas = [
        "test_ca01_other_type_is_unknown_without_review",
        "test_ca02_low_type_confidence_is_unknown_and_needs_review",
        "test_ca03_type_threshold_is_strict",
        "test_ca04_review_margin_boundary_and_grade_score",
        "test_ca05_unusable_threshold_is_inclusive",
        "test_ca06_grade_review_threshold",
        "test_ca07_invalid_outputs_raise",
        "test_ca19_a_softmax_unusable_score_is_clamped_to_4",
        "test_ca19_b_type_confidence_above_1_is_clamped",
        "test_ca19_c_grade_confidence_above_1_and_negative_score_are_clamped",
    ]
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--cov=qc_edge.decision",
        f"--cov-report=json:{report}",
        author,
        *(f"{this}::{name}" for name in decision_cas),
    ]
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    assert re.search(r"\b\d+ passed\b", proc.stdout), proc.stdout[-500:]
    data = json.loads(report.read_text())
    files = {k: v for k, v in data["files"].items() if k.endswith("qc_edge/decision.py")}
    assert len(files) == 1, list(data["files"])
    percent = next(iter(files.values()))["summary"]["percent_covered"]
    assert percent >= 80, percent


# =========================================================================== CA-18


def test_ca18_console_and_status_show_model_and_thresholds(
    edge: Edge, models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = make_model_dir(models, "dummy-v1")
    sha = sha256_hex((d / "model.onnx").read_bytes())
    monkeypatch.setenv("MODEL_DIR", str(d))
    monkeypatch.setenv("GRADE_REVIEW_THRESHOLD", "0.65")
    seen: dict[str, Any] = {}

    def drive(app: Any) -> None:
        with TestClient(app) as client:
            seen["status"] = client.get("/api/status", headers={SESSION_HEADER: edge.token})
        seen["console"] = asgi_get(app)

    monkeypatch.setattr(uvicorn, "run", UvicornSpy(drive))
    assert run_main(monkeypatch) == 0

    status = seen["status"]
    assert status.status_code == 200
    model = status.json()["model"]
    assert model["model_version"] == "dummy-v1"
    assert model["model_sha256"].startswith(sha[:12])
    assert model["thresholds"] == {
        "type_threshold": {"value": 0.5, "source": "decision.json"},
        "unusable_threshold": {"value": 0.4, "source": "decision.json"},
        "grade_review_threshold": {"value": 0.65, "source": "env"},
    }

    console = seen["console"]
    assert console.status_code == 200
    page = console.text
    assert "dummy-v1" in page
    assert sha[:12] in page
    for name in THRESHOLD_NAMES:
        assert name in page, name
    for value in ("0.5", "0.4", "0.65"):
        assert value in page or value.replace(".", ",") in page, value
    assert "decision.json" in page
    assert re.search(r"\benv\b", page)
    assert edge.token not in page.replace(f"capture?t={edge.token}", "")


# =========================================================================== extras


def test_extra_argmax_tie_goes_to_the_lowest_index() -> None:
    t = ca_decide([0.45, 0.45, 0.1], NEUTRAL_GRADE)
    assert t.type_confidence == pytest.approx(0.45)
    assert t.object_type == ObjectType.UNKNOWN  # below 0.5
    loose = decide([0.45, 0.45, 0.1], NEUTRAL_GRADE, CA_LABELS, Thresholds(0.4, 0.4, 0.6))
    assert loose.object_type == ObjectType.SCREW
    g = ca_decide([0.9, 0.05, 0.05], [0.0, 0.3, 0.3, 0.2, 0.2])
    assert g.grade == Grade.GOOD


@pytest.mark.parametrize(
    ("type_probs", "ok"),
    [
        ([0.9, 0.05, 0.0505], True),  # sum 1.0005 (inside 1 ± 1e-3)
        ([0.9, 0.05, 0.0495], True),  # sum 0.9995
        ([0.9, 0.05, 0.052], False),  # sum 1.002
        ([0.9, 0.05, 0.048], False),  # sum 0.998
        ([1.0 + 5e-7, 0.0, 0.0], True),  # 1e-6 tolerance on the range
        ([0.9, 0.05, float("inf")], False),
        ([0.9, 0.1], False),  # 2 types for 3 labels
    ],
)
def test_extra_tolerances(type_probs: list[float], ok: bool) -> None:
    if ok:
        ca_decide(type_probs, NEUTRAL_GRADE)
    else:
        with pytest.raises(InvalidModelOutputError):
            ca_decide(type_probs, NEUTRAL_GRADE)


def test_extra_numpy_inputs_and_frozen_dataclasses() -> None:
    d = ca_decide(np.array([0.9, 0.05, 0.05], dtype=np.float32), np.array(NEUTRAL_GRADE))
    assert d.object_type == ObjectType.SCREW and d.grade == Grade.GOOD
    with pytest.raises(FrozenInstanceError):
        d.needs_review = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        CA_THRESHOLDS.type_threshold = 0.1  # type: ignore[misc]


def test_extra_unknown_result_is_a_valid_inspection(edge: Edge, models: Path) -> None:
    d = make_model_dir(models, "dummy-v1", type_probs=[0.1, 0.1, 0.8])
    sink = InMemorySink()
    app = create_app(EdgeSettings(), OnnxInferencer(d), sink)
    with TestClient(app) as client:
        r = post_capture(client, edge.token, synthetic_jpeg(320, 240))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inspection"]["object_type"] == "unknown"
    assert body["inspection"]["grade"] is None
    assert body["approved"] is None


@pytest.mark.parametrize(
    "sha_text",
    ["{sha}", "{SHA}  model.onnx\n", "{sha} *model.onnx\n", "  {sha}\n"],
    ids=["bare", "upper-with-name", "binary-mode", "leading-space"],
)
def test_extra_sha256_file_formats(models: Path, sha_text: str) -> None:
    data = build_dummy_onnx(DUMMY_TYPE, DUMMY_GRADE)
    sha = sha256_hex(data)
    d = make_model_dir(
        models,
        "dummy-v1",
        model_bytes=data,
        sha_text=sha_text.format(sha=sha, SHA=sha.upper()),
    )
    inf = OnnxInferencer(d)
    assert inf.model_info.model_sha256 == sha  # always lowercase (contract)


def test_extra_sha256_file_empty(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1", sha_text="")
    with pytest.raises(ModelLoadError) as info:
        OnnxInferencer(d)
    assert "model.sha256" in str(info.value)


@pytest.mark.parametrize(
    "missing", ["model.onnx", "model.sha256", "labels.json", "preprocessing.json"]
)
def test_extra_each_missing_file(models: Path, missing: str) -> None:
    d = make_model_dir(models, "dummy-v1", skip=(missing,))
    with pytest.raises(ModelLoadError) as info:
        OnnxInferencer(d)
    assert missing in str(info.value)


@pytest.mark.parametrize("name", ["Dummy-V1", "ab", "dummy_v1", "modelo-ç1", "x" * 41])
def test_extra_invalid_model_version(models: Path, name: str) -> None:
    d = make_model_dir(models, name)
    with pytest.raises(ModelLoadError):
        OnnxInferencer(d)


def test_extra_corrupted_onnx_with_matching_hash(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1", model_bytes=b"\x08\x07garbage" * 50)
    with pytest.raises(ModelLoadError):
        OnnxInferencer(d)


def test_extra_invalid_preprocessing(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1", preprocessing='{"resize_shorter": "x"}')
    with pytest.raises(ModelLoadError) as info:
        OnnxInferencer(d)
    assert "preprocessing.json" in str(info.value)


@pytest.mark.parametrize(
    "decision",
    [
        {"type_threshold": 0.5, "unusable_threshold": 0.4},
        {**CA_DECISION_JSON, "unusable_threshold": -0.1},
        {**CA_DECISION_JSON, "grade_review_threshold": "0.6"},
        {**CA_DECISION_JSON, "type_threshold": float("nan")},
        {**CA_DECISION_JSON, "type_threshold": None},
    ],
    ids=["missing-key", "negative", "string", "nan", "null"],
)
def test_extra_invalid_decision_json(models: Path, decision: dict[str, Any]) -> None:
    d = make_model_dir(models, "dummy-v1", decision=decision)
    with pytest.raises(ModelLoadError) as info:
        OnnxInferencer(d)
    assert "decision.json" in str(info.value)


def test_extra_decision_json_boundaries_accepted(models: Path) -> None:
    d = make_model_dir(
        models,
        "dummy-v1",
        decision={"type_threshold": 0, "unusable_threshold": 1, "grade_review_threshold": 0.0},
    )
    inf = OnnxInferencer(d)
    assert inf.thresholds == Thresholds(0.0, 1.0, 0.0)


def test_extra_wrong_grade_output_shape(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1", grade_probs=[0.25, 0.25, 0.25, 0.25])
    with pytest.raises(ModelLoadError):
        OnnxInferencer(d)


def test_extra_wrong_output_name(models: Path) -> None:
    data = build_dummy_onnx(DUMMY_TYPE, DUMMY_GRADE, type_name="types")
    d = make_model_dir(models, "dummy-v1", model_bytes=data)
    with pytest.raises(ModelLoadError):
        OnnxInferencer(d)


def test_extra_infer_from_several_threads(models: Path) -> None:
    inf = OnnxInferencer(make_model_dir(models, "dummy-v1"))
    images = [open_jpeg(synthetic_jpeg(640, 480, seed=s)) for s in range(4)]
    errors: list[BaseException] = []
    results: list[InferenceResult] = []
    lock = threading.Lock()

    def work(img: Image.Image) -> None:
        try:
            for _ in range(5):
                res = inf.infer(img)
                with lock:
                    results.append(res)
        except BaseException as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(img,)) for img in images * 2]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == []
    assert len(results) == 40
    assert {(r.object_type, r.grade) for r in results} == {(ObjectType.SCREW, Grade.GOOD)}


def test_extra_png_and_small_images(models: Path) -> None:
    inf = OnnxInferencer(make_model_dir(models, "dummy-v1"))
    for size in [(1, 1), (224, 224), (3000, 300)]:
        res = inf.infer(Image.new("RGB", size, "gray"))
        assert res.object_type == ObjectType.SCREW


def test_extra_without_model_dir_the_edge_starts_without_model(
    edge: Edge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_DIR", "")
    seen: dict[str, Any] = {}

    def drive(app: Any) -> None:
        with TestClient(app) as client:
            seen["capture"] = post_capture(client, edge.token, synthetic_jpeg(320, 240))
            seen["status"] = client.get("/api/status", headers={SESSION_HEADER: edge.token})

    monkeypatch.setattr(uvicorn, "run", UvicornSpy(drive))
    assert run_main(monkeypatch) == 0
    assert seen["capture"].status_code == 503
    assert seen["capture"].json() == {"detail": "model not loaded"}
    assert seen["status"].json()["model"]["loaded"] is False


def test_extra_nonexistent_model_dir_exits_2(
    edge: Edge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "does-not-exist"))
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    assert run_main(monkeypatch) == 2
    assert spy.calls == []


def test_extra_stub_model_takes_precedence(
    edge: Edge,
    models: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    d = make_model_dir(models, "dummy-v1")
    monkeypatch.setenv("MODEL_DIR", str(d))
    seen: dict[str, Any] = {}

    def drive(app: Any) -> None:
        with TestClient(app) as client:
            seen["status"] = client.get("/api/status", headers={SESSION_HEADER: edge.token})

    monkeypatch.setattr(uvicorn, "run", UvicornSpy(drive))
    caplog.set_level(logging.DEBUG)
    assert run_main(monkeypatch, "--stub-model") == 0
    assert seen["status"].json()["model"]["model_version"] == "stub-v0"
    assert any(r.levelno >= logging.WARNING for r in caplog.records), caplog.text


def test_extra_model_dir_with_trailing_slash(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1")
    inf = OnnxInferencer(Path(str(d) + "/"))
    assert inf.model_info.model_version == "dummy-v1"


def test_extra_hash_checked_over_the_whole_file(models: Path) -> None:
    """A model file changed after the hash was written is refused (one flipped byte at the end)."""
    data = build_dummy_onnx(DUMMY_TYPE, DUMMY_GRADE)
    d = make_model_dir(models, "dummy-v1", model_bytes=data)
    changed = bytearray(data)
    changed[-1] ^= 0x01
    (d / "model.onnx").write_bytes(bytes(changed))
    with pytest.raises(ModelIntegrityError):
        OnnxInferencer(d)


@pytest.mark.parametrize(
    ("value", "expected"), [(" 0.55 ", 0.55), ("1e-1", 0.1), ("0", 0.0), ("1", 1.0)]
)
def test_extra_env_threshold_formats(
    edge: Edge, models: Path, monkeypatch: pytest.MonkeyPatch, value: str, expected: float
) -> None:
    monkeypatch.setenv("MODEL_DIR", str(make_model_dir(models, "dummy-v1")))
    monkeypatch.setenv("UNUSABLE_THRESHOLD", value)
    seen: dict[str, Any] = {}

    def drive(app: Any) -> None:
        with TestClient(app) as client:
            seen["status"] = client.get("/api/status", headers={SESSION_HEADER: edge.token})

    monkeypatch.setattr(uvicorn, "run", UvicornSpy(drive))
    assert run_main(monkeypatch) == 0
    entry = seen["status"].json()["model"]["thresholds"]["unusable_threshold"]
    assert entry == {"value": expected, "source": "env"}


@pytest.mark.parametrize("value", ["0,55", "nan", "-0.01", "inf"])
def test_extra_invalid_env_threshold_formats_exit_2(
    edge: Edge,
    models: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    monkeypatch.setenv("MODEL_DIR", str(make_model_dir(models, "dummy-v1")))
    monkeypatch.setenv("GRADE_REVIEW_THRESHOLD", value)
    monkeypatch.setattr(uvicorn, "run", UvicornSpy())
    caplog.set_level(logging.DEBUG)
    assert run_main(monkeypatch) == 2
    assert "GRADE_REVIEW_THRESHOLD" in captured_text(caplog, capsys)


# =========================================================================== CA-19

# Real float32 ``Softmax`` output for a very confident "unusable" grade, as written in CA-19 (a):
# p4 is exactly 1.0 and p3 > 0, so the raw Σ i·p_i is above 4 (the contract maximum).
CA19_SOFTMAX_UNUSABLE = [2.506e-10, 2.235e-10, 7.39e-11, 5.899e-08, 1.0]


def raw_grade_score(grade_probs: Sequence[float]) -> float:
    return sum(i * float(p) for i, p in enumerate(grade_probs))


def inspection_from(d: Decision) -> InspectionCreate:
    """``InspectionCreate`` built with the fields of the ``Decision`` plus a valid base payload."""
    return InspectionCreate(
        inspection_id=uuid.uuid4(),
        device_id="edge-acc-01",
        lot_id="L-001",
        inspected_at=datetime.now(UTC),
        object_type=d.object_type,
        grade=d.grade,
        grade_score=d.grade_score,
        type_confidence=d.type_confidence,
        grade_confidence=d.grade_confidence,
        needs_review=d.needs_review,
        model_version="dummy-v1",
        model_sha256=sha256_hex(b"acceptance model"),
        latency_ms=7,
        source="live",
    )


def test_ca19_a_softmax_unusable_score_is_clamped_to_4() -> None:
    assert raw_grade_score(CA19_SOFTMAX_UNUSABLE) > 4.0  # the case really goes past the range
    d = ca_decide([0.98, 0.01, 0.01], CA19_SOFTMAX_UNUSABLE)
    assert d.object_type == ObjectType.SCREW
    assert d.grade == Grade.UNUSABLE
    assert d.grade_score == 4.0
    assert d.grade_confidence == 1.0
    assert d.needs_review is False
    assert d.type_confidence == 0.98
    insp = inspection_from(d)
    assert insp.grade_score == 4.0 and insp.grade == Grade.UNUSABLE


def test_ca19_b_type_confidence_above_1_is_clamped() -> None:
    d = ca_decide([1.0000009, 0.0, 0.0], [0.05, 0.8, 0.05, 0.05, 0.05])
    assert d.object_type == ObjectType.SCREW
    assert d.type_confidence == 1.0
    assert d.grade == Grade.GOOD
    assert d.grade_confidence == 0.8
    assert d.needs_review is False
    insp = inspection_from(d)
    assert insp.type_confidence == 1.0


def test_ca19_c_grade_confidence_above_1_and_negative_score_are_clamped() -> None:
    assert raw_grade_score([1.0000005, -5e-7, 0.0, 0.0, 0.0]) < 0.0
    d = ca_decide([0.9, 0.05, 0.05], [1.0000005, -5e-7, 0.0, 0.0, 0.0])
    assert d.object_type == ObjectType.SCREW
    assert d.grade == Grade.PERFECT
    assert d.grade_confidence == 1.0
    assert d.grade_score == 0.0
    assert d.needs_review is False
    insp = inspection_from(d)
    assert insp.grade_score == 0.0 and insp.grade_confidence == 1.0


# =========================================================================== CA-20


def test_ca20_confident_unusable_output_through_the_route(edge: Edge, models: Path) -> None:
    # Precondition of SPEC §6: in float32, p4 stays exactly 1.0 and p3 > 0 (raw score > 4).
    as_f32 = np.asarray(CA19_SOFTMAX_UNUSABLE, dtype=np.float32)
    assert as_f32[4] == 1.0 and as_f32[3] > 0
    assert raw_grade_score(as_f32.astype(np.float64)) > 4.0

    d = make_model_dir(
        models, "dummy-v1", type_probs=[0.98, 0.01, 0.01], grade_probs=CA19_SOFTMAX_UNUSABLE
    )
    sink = InMemorySink()
    app = create_app(EdgeSettings(), OnnxInferencer(d), sink)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = post_capture(client, edge.token, synthetic_jpeg(1280, 960))
    assert r.status_code == 200, r.text
    insp = r.json()["inspection"]
    assert insp["grade"] == "unusable"
    assert insp["grade_score"] == 4.0
    assert insp["object_type"] == "screw"
    assert insp["model_version"] == "dummy-v1"
    assert len(sink.items) == 1
    assert sink.items[0].grade_score == 4.0
    assert len(edge.captures()) == 1


# =========================================================================== CA-21


def test_ca21_symlink_gives_the_name_of_the_target(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1")
    sha = sha256_hex((d / "model.onnx").read_bytes())
    link = models / "atual"
    link.symlink_to(d, target_is_directory=True)
    inf = OnnxInferencer(link)
    assert inf.model_info.model_version == "dummy-v1"
    assert inf.model_info == ModelInfo("dummy-v1", sha)


def test_ca21_symlink_to_a_target_with_an_invalid_name(tmp_path: Path) -> None:
    root = tmp_path / "models-invalid"
    root.mkdir()
    d = make_model_dir(root, "Dummy_V1")
    link = root / "atual"  # a valid name: only the target name decides
    link.symlink_to(d, target_is_directory=True)
    with pytest.raises(ModelLoadError):
        OnnxInferencer(link)


# =========================================================================== CA-22

CA22_PREPROCESSING = json.dumps(
    {
        "resize_shorter": 288,
        "crop": 256,
        "mean": list(PreprocessParams().mean),
        "std": list(PreprocessParams().std),
    }
)


def test_ca22_crop_incompatible_with_a_fixed_input_fails_at_load(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1", preprocessing=CA22_PREPROCESSING)
    with pytest.raises(ModelLoadError) as exc:
        OnnxInferencer(d)
    assert "model.onnx" in str(exc.value)


def test_ca22_dynamic_input_accepts_the_crop(models: Path) -> None:
    d = make_model_dir(
        models, "dummy-v1", preprocessing=CA22_PREPROCESSING, input_shape=DYNAMIC_INPUT_SHAPE
    )
    inf = OnnxInferencer(d)
    res = inf.infer(open_jpeg(synthetic_jpeg(1280, 960)))
    assert res.object_type == ObjectType.SCREW
    assert res.grade == Grade.GOOD
    assert res.type_confidence == pytest.approx(0.9, abs=1e-6)
    assert res.grade_confidence == pytest.approx(0.8, abs=1e-6)


# =========================================================================== CA-23


def test_ca23_blank_model_dir_exits_2(
    edge: Edge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.chdir(tmp_path)  # no "   " directory in the working directory
    monkeypatch.setenv("MODEL_DIR", "   ")
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    caplog.set_level(logging.DEBUG)
    assert run_main(monkeypatch) == 2
    assert spy.calls == []
    assert "MODEL_DIR" in caplog.text


# =========================================================================== extras (r2)


def test_extra_clamp_also_applies_to_an_unknown_type_confidence() -> None:
    """§4.1 item 6 has no exception for ``unknown``: ``type_confidence`` is clamped too."""
    d = ca_decide([0.0, 0.0, 1.0000009], NEUTRAL_GRADE)
    assert d.object_type == ObjectType.UNKNOWN
    assert d.type_confidence == 1.0
    assert (d.grade, d.grade_score, d.grade_confidence) == (None, None, None)
    inspection_from(d)


def test_extra_review_margin_compares_the_raw_type_confidence() -> None:
    """With ``type_threshold + REVIEW_MARGIN`` between 1.0 and the raw value, only the raw
    comparison gives ``needs_review = false`` (clamping first would give ``true``)."""
    thresholds = Thresholds(
        type_threshold=0.9000005, unusable_threshold=0.4, grade_review_threshold=0.6
    )
    limit = thresholds.type_threshold + REVIEW_MARGIN
    assert 1.0 < limit < 1.0000009
    d = decide([1.0000009, 0.0, 0.0], DUMMY_GRADE, CA_LABELS, thresholds)
    assert d.type_confidence == 1.0
    assert d.needs_review is False


def test_extra_unusable_threshold_compares_the_raw_probability() -> None:
    """``unusable_threshold = 0`` and a raw p4 of -5e-7: raw comparison → not ``unusable``."""
    thresholds = Thresholds(type_threshold=0.5, unusable_threshold=0.0, grade_review_threshold=0.6)
    d = decide([0.9, 0.05, 0.05], [1.0000005, 0.0, 0.0, 0.0, -5e-7], CA_LABELS, thresholds)
    assert d.grade == Grade.PERFECT
    assert d.grade_confidence == 1.0
    assert d.grade_score == 0.0


def _softmax_session() -> ort.InferenceSession:
    inp = helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["N", "K"])
    out = helper.make_tensor_value_info("probs", TensorProto.FLOAT, ["N", "K"])
    node = helper.make_node("Softmax", ["logits"], ["probs"], axis=-1)
    graph = helper.make_graph([node], "acc-softmax", [inp], [out])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    return ort.InferenceSession(model.SerializeToString(), providers=["CPUExecutionProvider"])


def _confident_logits(rng: np.random.Generator, n: int, k: int) -> np.ndarray:
    logits = rng.normal(0.0, 1.0, (n, k)).astype(np.float32)
    dominant = rng.integers(0, k, n)
    logits[np.arange(n), dominant] += rng.uniform(0.0, 25.0, n).astype(np.float32)
    return logits


def test_extra_onnxruntime_softmax_outputs_always_fit_the_contract() -> None:
    """3000 real float32 ``Softmax`` outputs of the locked onnxruntime (type and grade heads),
    many of them very confident: every one passes ``decide`` and ``InspectionCreate``."""
    session = _softmax_session()
    rng = np.random.default_rng(2026)
    n = 3000
    type_rows = session.run(["probs"], {"logits": _confident_logits(rng, n, 3)})[0]
    grade_rows = session.run(["probs"], {"logits": _confident_logits(rng, n, 5)})[0]
    above_4 = 0
    for type_probs, grade_probs in zip(type_rows, grade_rows, strict=True):
        if raw_grade_score(grade_probs.astype(np.float64)) > 4.0:
            above_4 += 1
        d = ca_decide(type_probs, grade_probs)
        assert 0.0 <= d.type_confidence <= 1.0
        if d.grade is not None:
            assert d.grade_score is not None and 0.0 <= d.grade_score <= 4.0
            assert d.grade_confidence is not None and 0.0 <= d.grade_confidence <= 1.0
        inspection_from(d)
    assert above_4 > 0  # the T-01 case of r1 really happens in the sample


def test_extra_symlinked_model_dir_uses_the_target_name(
    edge: Edge, models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rewrite of the r1 ``test_extra_symlinked_model_dir_uses_the_link_name``, invalidated by
    §4.2 item 3: through ``main()``, a link ``partqc-link-v2 → dummy-v1`` sends ``dummy-v1``."""
    d = make_model_dir(models, "dummy-v1")
    link = models / "partqc-link-v2"
    link.symlink_to(d, target_is_directory=True)
    monkeypatch.setenv("MODEL_DIR", str(link))
    seen: dict[str, Any] = {}

    def drive(app: Any) -> None:
        with TestClient(app) as client:
            seen["capture"] = post_capture(client, edge.token, synthetic_jpeg(320, 240))
            seen["status"] = client.get("/api/status", headers={SESSION_HEADER: edge.token})

    monkeypatch.setattr(uvicorn, "run", UvicornSpy(drive))
    assert run_main(monkeypatch) == 0
    assert seen["capture"].status_code == 200, seen["capture"].text
    assert seen["capture"].json()["inspection"]["model_version"] == "dummy-v1"
    assert seen["status"].json()["model"]["model_version"] == "dummy-v1"


def test_extra_swapping_the_link_changes_the_version(models: Path) -> None:
    """The motivation of §4.2 item 3: a fixed link name pointing to two models gives two names."""
    v1 = make_model_dir(models, "partqc-mnv3-v1")
    v2 = make_model_dir(models, "partqc-mnv3-v2", grade_probs=[0.8, 0.05, 0.05, 0.05, 0.05])
    link = models / "current"
    link.symlink_to(v1, target_is_directory=True)
    first = OnnxInferencer(link)
    link.unlink()
    link.symlink_to(v2, target_is_directory=True)
    second = OnnxInferencer(link)
    assert first.model_info.model_version == "partqc-mnv3-v1"
    assert second.model_info.model_version == "partqc-mnv3-v2"
    assert first.model_info.model_sha256 != second.model_info.model_sha256
    img = open_jpeg(synthetic_jpeg(320, 240))
    assert first.infer(img).grade == Grade.GOOD  # the first session keeps its own model
    assert second.infer(img).grade == Grade.PERFECT


def test_extra_chain_and_relative_links(models: Path) -> None:
    make_model_dir(models, "dummy-v1")
    rel = models / "rel-link"
    rel.symlink_to("dummy-v1", target_is_directory=True)  # relative target
    chain = models / "Chain_Link"  # invalid name: only the final target counts
    chain.symlink_to(rel, target_is_directory=True)
    assert OnnxInferencer(rel).model_info.model_version == "dummy-v1"
    assert OnnxInferencer(chain).model_info.model_version == "dummy-v1"
    assert OnnxInferencer(Path(str(chain) + "/")).model_info.model_version == "dummy-v1"


def test_extra_dot_dot_components_are_resolved(models: Path) -> None:
    d = make_model_dir(models, "dummy-v1")
    (d / "sub").mkdir()
    assert OnnxInferencer(d / "sub" / "..").model_info.model_version == "dummy-v1"
    assert OnnxInferencer(d / ".." / "dummy-v1").model_info.model_version == "dummy-v1"


@pytest.mark.parametrize("case", ["broken-link", "link-to-a-file", "plain-file"])
def test_extra_model_dir_that_is_not_a_directory(models: Path, case: str) -> None:
    target = models / "target-file"
    target.write_text("not a model", encoding="utf-8")
    path = models / "model-link"
    if case == "broken-link":
        path.symlink_to(models / "missing-dir", target_is_directory=True)
    elif case == "link-to-a-file":
        path.symlink_to(target)
    else:
        path = target
    with pytest.raises(ModelLoadError) as exc:
        OnnxInferencer(path)
    assert "MODEL_DIR" in str(exc.value)


def test_extra_link_loop_is_a_load_error(models: Path) -> None:
    a = models / "loop-a"
    b = models / "loop-b"
    a.symlink_to(b, target_is_directory=True)
    b.symlink_to(a, target_is_directory=True)
    with pytest.raises(ModelLoadError) as exc:
        OnnxInferencer(a)
    assert "MODEL_DIR" in str(exc.value)


def test_extra_fixed_input_of_256_loads_with_crop_256(models: Path) -> None:
    """Warm-up with the ``crop`` of ``preprocessing.json`` (§4.2 item 7): a fixed 256 input
    with ``crop=256`` loads and infers (with a fixed 224 warm-up it would fail at load)."""
    d = make_model_dir(
        models, "dummy-v1", preprocessing=CA22_PREPROCESSING, input_shape=("N", 3, 256, 256)
    )
    res = OnnxInferencer(d).infer(open_jpeg(synthetic_jpeg(1280, 960)))
    assert (res.object_type, res.grade) == (ObjectType.SCREW, Grade.GOOD)


def test_extra_fixed_input_of_256_fails_at_load_with_the_default_crop(models: Path) -> None:
    """The opposite case: input ``[N,3,256,256]`` with the default ``crop=224`` fails at load
    (in r1 it loaded and then failed every ``infer``)."""
    d = make_model_dir(models, "dummy-v1", input_shape=("N", 3, 256, 256))
    with pytest.raises(ModelLoadError) as exc:
        OnnxInferencer(d)
    assert "model.onnx" in str(exc.value)


def test_extra_crop_mismatch_exits_2_through_the_cli(
    edge: Edge,
    models: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    d = make_model_dir(models, "dummy-v1", preprocessing=CA22_PREPROCESSING)
    monkeypatch.setenv("MODEL_DIR", str(d))
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    caplog.set_level(logging.DEBUG)
    assert run_main(monkeypatch) == 2
    assert spy.calls == []
    assert "model.onnx" in caplog.text


@pytest.mark.parametrize("value", [" ", "\t", " \n "], ids=["1-space", "tab", "newline"])
def test_extra_whitespace_model_dir_values_exit_2(
    edge: Edge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    value: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODEL_DIR", value)
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    caplog.set_level(logging.DEBUG)
    assert run_main(monkeypatch) == 2
    assert spy.calls == []
    assert "MODEL_DIR" in caplog.text


@pytest.mark.parametrize("pad", ["leading", "trailing"])
def test_extra_model_dir_with_spaces_around_a_valid_path_is_not_stripped(
    edge: Edge,
    models: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    pad: str,
) -> None:
    """§4.4: the value is not stripped, so ``" <valid dir>"`` is another path (exit 2)."""
    d = make_model_dir(models, "dummy-v1")
    value = f" {d}" if pad == "leading" else f"{d} "
    monkeypatch.setenv("MODEL_DIR", value)
    spy = UvicornSpy()
    monkeypatch.setattr(uvicorn, "run", spy)
    caplog.set_level(logging.DEBUG)
    assert run_main(monkeypatch) == 2
    assert spy.calls == []
    assert "MODEL_DIR" in caplog.text
