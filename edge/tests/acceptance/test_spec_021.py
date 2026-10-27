"""Acceptance tests for SPEC-021 (qc-edge: the 4 power tools in the model, collect and import).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-05, CA-06 and CA-07. Tests named ``test_extra_*`` are exploratory edge
cases around SPEC-021 sections 3.1 and 4 that no CA spells out.

CA-07 is read as the architect clarified for this round: the plan is validated whole (SPEC-036
section 4.2, unchanged); "the first line enters" means it passes the validation (no problem is
reported for it) and, because the second line has a problem, nothing is written. The plan with
only the first line is imported (exit 0), as a contrast case.

Rules followed (``docs/architecture.md`` §10, R-03, R-14): the dummy ONNX models of SPEC-008 §6
are built here with ``onnx.helper`` in ``tmp_path`` (no torch, no binary in Git); every image is
synthetic and generated in memory; session tokens are built at run time; ``DATASET_DIR``, the
outbox and the import inbox always live under ``tmp_path``; no test runs pytest in a subprocess;
nothing is mocked besides the clock and the sleep of the importer (the boundaries its ``main``
accepts).
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import secrets
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import onnx
import pytest
from fastapi.testclient import TestClient
from onnx import TensorProto, helper
from PIL import Image, ImageFile

import qc_edge.importer
from qc_contracts import OBJECT_TYPE_LABELS_PT, InspectionCreate, ObjectType
from qc_edge.app import create_app
from qc_edge.collect import compute_coverage
from qc_edge.config import EdgeSettings
from qc_edge.decision import ModelLabels, Thresholds, decide
from qc_edge.onnx_inferencer import ModelLoadError, OnnxInferencer
from qc_edge.outbox import SqliteOutbox
from qc_edge.sink import InMemorySink
from qc_preprocess import PreprocessParams

pytestmark = pytest.mark.acceptance

SESSION_HEADER = "X-Session-Token"
GRADES = ("perfect", "good", "fair", "poor", "unusable")
HAND_TOOLS = (
    "pliers",
    "adjustable_wrench",
    "allen_key",
    "flat_screwdriver",
    "phillips_screwdriver",
)
POWER_TOOLS = ("angle_grinder", "saw", "drill", "cordless_screwdriver")
POWER_LABELS = ("esmerilhadeira", "serra", "furadeira", "parafusadeira")
CA_TYPES = ("screw", "nut", "other", "drill")
CA_TYPE_PROBS = (0.05, 0.03, 0.02, 0.90)
CA_DECISION_JSON = {"type_threshold": 0.5, "unusable_threshold": 0.4, "grade_review_threshold": 0.6}
CA_THRESHOLDS = Thresholds(type_threshold=0.5, unusable_threshold=0.4, grade_review_threshold=0.6)
GRADE_PROBS = (0.05, 0.1, 0.7, 0.1, 0.05)  # argmax fair, unusable below 0.4
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
PLAN_COLUMNS = (
    "file",
    "item_id",
    "object_type",
    "grade",
    "labeler",
    "angle",
    "origin",
    "contributor",
    "source_id",
    "source_ref",
    "notes",
)
SOURCES_COLUMNS = ("image_path", "origin", "contributor", "source_id", "source_ref", "input_sha256")
REGISTRY_HEADER = "source_id,title,url,license,license_url,attribution,retrieved_at"
REGISTRY_LINE = (
    "fonte-eletricas,Fonte de teste,https://example.org/eletricas,CC-BY-4.0,"
    "https://creativecommons.org/licenses/by/4.0/,Fonte de teste (example.org),2026-10-20"
)


# =========================================================================== dummy model


def build_dummy_onnx(type_probs: Sequence[float], grade_probs: Sequence[float]) -> bytes:
    """SPEC-008 §6 dummy: ReduceMean(image) -> Reshape [N,1] -> Mul 0 -> Add constants."""
    t, g = len(type_probs), len(grade_probs)
    inp = helper.make_tensor_value_info("image", TensorProto.FLOAT, ["N", 3, 224, 224])
    out_t = helper.make_tensor_value_info("type_probs", TensorProto.FLOAT, ["N", t])
    out_g = helper.make_tensor_value_info("grade_probs", TensorProto.FLOAT, ["N", g])
    inits = [
        helper.make_tensor("shape_n1", TensorProto.INT64, [2], [-1, 1]),
        helper.make_tensor("zero", TensorProto.FLOAT, [], [0.0]),
        helper.make_tensor("type_const", TensorProto.FLOAT, [1, t], list(type_probs)),
        helper.make_tensor("grade_const", TensorProto.FLOAT, [1, g], list(grade_probs)),
    ]
    nodes = [
        helper.make_node("ReduceMean", ["image"], ["mean"], axes=[1, 2, 3], keepdims=0),
        helper.make_node("Reshape", ["mean", "shape_n1"], ["mean_n1"]),
        helper.make_node("Mul", ["mean_n1", "zero"], ["zeros_n1"]),
        helper.make_node("Add", ["zeros_n1", "type_const"], ["type_probs"]),
        helper.make_node("Add", ["zeros_n1", "grade_const"], ["grade_probs"]),
    ]
    graph = helper.make_graph(nodes, "acc21-dummy", [inp], [out_t, out_g], initializer=inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model.SerializeToString()


_ABSENT = object()


def make_model_dir(
    root: Path,
    name: str = "partqc-acc21-v1",
    *,
    object_types: Sequence[str] = CA_TYPES,
    ungraded: Any = _ABSENT,
    type_probs: Sequence[float] = CA_TYPE_PROBS,
    grade_probs: Sequence[float] = GRADE_PROBS,
) -> Path:
    d = root / name
    d.mkdir(parents=True)
    data = build_dummy_onnx(type_probs, grade_probs)
    (d / "model.onnx").write_bytes(data)
    (d / "model.sha256").write_text(f"{hashlib.sha256(data).hexdigest()}  model.onnx\n")
    labels: dict[str, Any] = {"object_types": list(object_types), "grades": list(GRADES)}
    if ungraded is not _ABSENT:
        labels["ungraded_object_types"] = ungraded
    (d / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    PreprocessParams().to_json(d / "preprocessing.json")
    (d / "decision.json").write_text(json.dumps(CA_DECISION_JSON), encoding="utf-8")
    return d


def synthetic_jpeg(width: int = 400, height: int = 300, seed: int = 21) -> bytes:
    """Gradient plus noise: no person, no real photo (R-14)."""
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 255, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 255, height, dtype=np.float32)[:, None]
    base = np.stack([x + 0 * y, y + 0 * x, (x + y) / 2], axis=-1)
    arr = np.clip(base + rng.normal(0, 15, (height, width, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def solid_jpeg(color: str = "teal") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


# =========================================================================== edge fixture


@dataclass
class Edge:
    tmp: Path
    data_dir: Path
    dataset: Path
    token: str

    def app(self, inferencer: Any = None, sink: Any = None) -> Any:
        return create_app(EdgeSettings(), inferencer, sink if sink is not None else InMemorySink())

    @property
    def manifest(self) -> Path:
        return self.dataset / "manifest.csv"

    def rows(self) -> list[dict[str, str]]:
        with self.manifest.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def tree(self) -> set[str]:
        return {str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*")}


@pytest.fixture
def edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Edge:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    token = secrets.token_urlsafe(30)
    data_dir = tmp_path / "edge-data"
    dataset = tmp_path / "dataset"
    monkeypatch.setenv("EDGE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setenv("DATASET_DIR", str(dataset))
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    return Edge(tmp=tmp_path, data_dir=data_dir, dataset=dataset, token=token)


@pytest.fixture
def models(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    root.mkdir()
    return root


def post_capture(client: TestClient, token: str, lot_id: str = "L-021") -> Any:
    return client.post(
        "/api/capture",
        headers={SESSION_HEADER: token},
        data={"lot_id": lot_id, "mode": "inspect"},
        files={"image": ("foto.jpg", synthetic_jpeg(), "image/jpeg")},
    )


def collect_fields(**overrides: str | None) -> dict[str, str]:
    base: dict[str, str | None] = {
        "mode": "collect",
        "item_id": "T-010",
        "object_type": "drill",
        "grade": "",
        "labeler": "a",
        "angle": "1",
        "notes": "",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def post_collect(client: TestClient, token: str, data: dict[str, str]) -> Any:
    return client.post(
        "/api/capture",
        headers={SESSION_HEADER: token, "User-Agent": "acceptance-phone"},
        data=data,
        files={"image": ("foto.jpg", solid_jpeg(), "image/jpeg")},
    )


def outbox_payloads(path: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(path)
    try:
        return [json.loads(r[0]) for r in con.execute("SELECT payload FROM outbox")]
    finally:
        con.close()


# =========================================================================== CA-05


def test_ca05_model_with_drill_and_empty_ungraded_list_is_refused(models: Path) -> None:
    d = make_model_dir(models, ungraded=[])
    with pytest.raises(ModelLoadError):
        OnnxInferencer(d)


def test_ca05_model_with_drill_listed_as_ungraded_loads(models: Path) -> None:
    d = make_model_dir(models, ungraded=["drill"])
    inf = OnnxInferencer(d)
    assert inf.model_info.model_version == "partqc-acc21-v1"


def test_ca05_decision_of_a_drill_has_no_grade() -> None:
    labels = ModelLabels(object_types=CA_TYPES, grades=GRADES, ungraded_object_types=("drill",))
    d = decide(list(CA_TYPE_PROBS), GRADE_PROBS, labels, CA_THRESHOLDS)
    assert d.object_type == ObjectType.DRILL
    assert d.grade is None
    assert d.grade_score is None
    assert d.grade_confidence is None


# =========================================================================== CA-06


def test_ca06_drill_without_grade_is_collected_into_the_no_grade_dir(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        r = post_collect(client, edge.token, collect_fields())
    assert r.status_code == 200, r.text
    image_path = r.json()["image_path"]
    assert image_path.startswith("raw/drill/_/T-010__1__"), image_path
    assert (edge.dataset / image_path).is_file()
    files = [p for p in (edge.dataset / "raw").rglob("*") if p.is_file()]
    assert [str(p.relative_to(edge.dataset)) for p in files] == [image_path]
    (row,) = edge.rows()
    assert row["image_path"] == image_path
    assert (row["item_id"], row["object_type"], row["grade"]) == ("T-010", "drill", "")


def test_ca06_drill_with_grade_is_422_and_nothing_written(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        before = edge.tree()
        r = post_collect(client, edge.token, collect_fields(grade="good"))
        assert r.status_code == 422, r.text
        assert edge.tree() == before
    assert not edge.dataset.exists()


# =========================================================================== CA-07


@dataclass
class ImportEnv:
    tmp: Path
    capsys: pytest.CaptureFixture[str]
    caplog: pytest.LogCaptureFixture
    dataset: Path
    inbox: Path
    registry: Path
    plan: Path
    now: datetime = field(default_factory=lambda: datetime(2026, 11, 3, 14, 0, 0, tzinfo=UTC))

    def clock(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=max(seconds, 1.0))

    def put(self, name: str, data: bytes) -> str:
        (self.inbox / name).write_bytes(data)
        return name

    def write_registry(self) -> None:
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        self.registry.write_text(REGISTRY_HEADER + "\n" + REGISTRY_LINE + "\n", encoding="utf-8")

    def write_plan(self, rows: Sequence[Sequence[str]]) -> None:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(PLAN_COLUMNS)
        writer.writerows(rows)
        self.plan.write_bytes(buf.getvalue().encode("utf-8"))

    def run(self, *extra: str) -> tuple[int, str, str]:
        self.capsys.readouterr()
        argv = [
            "--dataset-dir",
            str(self.dataset),
            "--inbox",
            str(self.inbox),
            "--plan",
            str(self.plan),
            "--external-sources",
            str(self.registry),
            "--privacy-checked",
            *extra,
        ]
        with self.caplog.at_level(logging.DEBUG):
            try:
                code = qc_edge.importer.main(argv, clock=self.clock, sleep=self.sleep)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        out = self.capsys.readouterr()
        return code, out.out, out.err

    def snapshot(self) -> dict[str, bytes | None]:
        if not self.dataset.exists():
            return {}
        return {
            str(p.relative_to(self.dataset)): (None if p.is_dir() else p.read_bytes())
            for p in sorted(self.dataset.rglob("*"))
        }

    def manifest_rows(self) -> list[dict[str, str]]:
        with (self.dataset / "manifest.csv").open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def sources_rows(self) -> list[dict[str, str]]:
        with (self.dataset / "sources.csv").open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            assert tuple(reader.fieldnames or ()) == SOURCES_COLUMNS
            return list(reader)


@pytest.fixture
def imp(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> ImportEnv:
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    inbox = tmp_path / "entrada"
    inbox.mkdir()
    env = ImportEnv(
        tmp=tmp_path,
        capsys=capsys,
        caplog=caplog,
        dataset=tmp_path / "D",
        inbox=inbox,
        registry=tmp_path / "registro" / "external_sources.csv",
        plan=tmp_path / "plano.csv",
    )
    env.write_registry()
    return env


def plan_row(file: str, item_id: str, object_type: str, grade: str, origin: str) -> list[str]:
    if origin == "contributor":
        return [file, item_id, object_type, grade, "a", "0", origin, "c01", "", "", ""]
    ref = f"power/train/{item_id}.png"
    return [file, item_id, object_type, grade, "b", "0", origin, "", "fonte-eletricas", ref, ""]


def ca07_rows(imp: ImportEnv) -> list[list[str]]:
    return [
        plan_row(
            imp.put("xt10.jpg", synthetic_jpeg(seed=10)), "XT-0010", "angle_grinder", "", "external"
        ),
        plan_row(
            imp.put("xt11.jpg", synthetic_jpeg(seed=11)), "XT-0011", "saw", "good", "external"
        ),
    ]


def _problem_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith("plan line ")]


def test_ca07_plan_with_both_rows_refuses_the_saw_and_writes_nothing(imp: ImportEnv) -> None:
    """The CA plan: line 2 (angle grinder without grade) passes the validation, line 3 (saw with
    grade ``good``) is refused; the plan is validated whole, so nothing is written."""
    imp.write_plan(ca07_rows(imp))
    before = imp.snapshot()
    code, out, err = imp.run()
    assert code == 2, out + err
    problems = _problem_lines(err)
    assert problems, err
    assert all(line.startswith("plan line 3: ") for line in problems), problems
    assert any(line.endswith("(grade)") for line in problems), problems
    assert imp.snapshot() == before


def test_ca07_angle_grinder_row_alone_is_imported_without_grade(imp: ImportEnv) -> None:
    imp.write_plan(ca07_rows(imp)[:1])
    code, out, err = imp.run()
    assert code == 0, out + err
    (row,) = imp.manifest_rows()
    assert (row["item_id"], row["object_type"], row["grade"]) == ("XT-0010", "angle_grinder", "")
    assert row["image_path"].startswith("raw/angle_grinder/_/XT-0010__0__"), row["image_path"]
    assert (imp.dataset / row["image_path"]).is_file()
    (src,) = imp.sources_rows()
    assert (src["image_path"], src["origin"]) == (row["image_path"], "external")
    assert src["source_id"] == "fonte-eletricas"


def test_ca07_saw_row_with_grade_alone_is_refused(imp: ImportEnv) -> None:
    imp.write_plan(ca07_rows(imp)[1:])
    before = imp.snapshot()
    code, out, err = imp.run()
    assert code == 2, out + err
    problems = _problem_lines(err)
    assert problems and all(line.startswith("plan line 2: ") for line in problems), err
    assert any(line.endswith("(grade)") for line in problems), problems
    assert imp.snapshot() == before


# =========================================================================== extras: model


@pytest.mark.parametrize("tool", POWER_TOOLS)
def test_extra_each_power_tool_must_be_listed_as_ungraded(models: Path, tool: str) -> None:
    types = ("screw", "nut", "other", tool)
    with pytest.raises(ModelLoadError):
        OnnxInferencer(make_model_dir(models, "absent-v1", object_types=types))
    with pytest.raises(ModelLoadError):
        OnnxInferencer(make_model_dir(models, "empty-v1", object_types=types, ungraded=[]))
    OnnxInferencer(make_model_dir(models, "ok-v1", object_types=types, ungraded=[tool]))


def test_extra_model_with_the_12_types_needs_all_four_power_tools(models: Path) -> None:
    types = ("screw", "nut", "other", *HAND_TOOLS, *POWER_TOOLS)
    probs = [0.9, *([0.1 / 11] * 11)]
    ok = make_model_dir(
        models, "all-v1", object_types=types, ungraded=list(POWER_TOOLS), type_probs=probs
    )
    OnnxInferencer(ok)
    with_hand = make_model_dir(
        models,
        "hand-v1",
        object_types=types,
        ungraded=["allen_key", *POWER_TOOLS],
        type_probs=probs,
    )
    OnnxInferencer(with_hand)
    missing = make_model_dir(
        models, "missing-v1", object_types=types, ungraded=list(POWER_TOOLS[:3]), type_probs=probs
    )
    with pytest.raises(ModelLoadError):
        OnnxInferencer(missing)


@pytest.mark.parametrize(
    "ungraded",
    [["drill", "saw"], ["drill", "drill"], ["Drill"], ["drill", "screw"], ["drill", "other"]],
    ids=["outside-object-types", "repeated", "case", "with-screw", "with-other"],
)
def test_extra_invalid_ungraded_lists_with_a_power_tool(models: Path, ungraded: Any) -> None:
    with pytest.raises(ModelLoadError):
        OnnxInferencer(make_model_dir(models, ungraded=ungraded))


def test_extra_power_tool_load_error_does_not_echo_values(models: Path) -> None:
    marker = "zz" + secrets.token_hex(4)
    d = make_model_dir(models, ungraded=["drill", marker])
    with pytest.raises(ModelLoadError) as info:
        OnnxInferencer(d)
    assert marker not in str(info.value)


# =========================================================================== extras: decision


def test_extra_drill_decision_ignores_grade_probs_and_unusable() -> None:
    labels = ModelLabels(object_types=CA_TYPES, grades=GRADES, ungraded_object_types=("drill",))
    for grade_probs in ([0.0, 0.0, 0.0, 0.1, 0.9], [0.2] * 5):
        d = decide([0.01, 0.01, 0.01, 0.97], grade_probs, labels, CA_THRESHOLDS)
        assert d.object_type == ObjectType.DRILL
        assert d.grade is None and d.grade_confidence is None
        assert d.needs_review is False


def test_extra_drill_with_low_margin_needs_review_and_below_threshold_is_unknown() -> None:
    labels = ModelLabels(object_types=CA_TYPES, grades=GRADES, ungraded_object_types=("drill",))
    low = decide([0.2, 0.1, 0.15, 0.55], GRADE_PROBS, labels, CA_THRESHOLDS)
    assert low.object_type == ObjectType.DRILL and low.grade is None and low.needs_review is True
    below = decide([0.2, 0.15, 0.2, 0.45], GRADE_PROBS, labels, CA_THRESHOLDS)
    assert below.object_type == ObjectType.UNKNOWN and below.grade is None


# =========================================================================== extras: capture


def test_extra_capture_of_a_drill_is_ungraded_and_reaches_the_outbox(
    edge: Edge, models: Path
) -> None:
    """Section 4: the capture answer is the ungraded tool one (approved null, "sem grau")."""
    d = make_model_dir(models, ungraded=["drill"])
    outbox_path = edge.tmp / "outbox.sqlite3"
    outbox = SqliteOutbox(outbox_path)
    try:
        app = create_app(EdgeSettings(), OnnxInferencer(d), outbox)
        with TestClient(app) as client:
            r = post_capture(client, edge.token)
    finally:
        outbox.close()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approved"] is None
    assert body["labels_pt"]["verdict"] == "sem grau"
    assert body["labels_pt"]["object_type"] == "furadeira"
    assert body["labels_pt"]["grade"] is None
    assert body["inspection"]["object_type"] == "drill"
    assert body["inspection"]["grade"] is None
    (stored,) = outbox_payloads(outbox_path)
    insp = InspectionCreate.model_validate(stored)
    assert insp.object_type == ObjectType.DRILL
    assert insp.grade is None and insp.grade_score is None and insp.grade_confidence is None
    assert insp.model_dump(mode="json") == body["inspection"]


# =========================================================================== extras: collect


@pytest.mark.parametrize("tool", POWER_TOOLS)
def test_extra_every_power_tool_is_collected_without_grade(edge: Edge, tool: str) -> None:
    with TestClient(edge.app()) as client:
        for angle in range(3):
            r = post_collect(
                client,
                edge.token,
                collect_fields(item_id="T-020", object_type=tool, angle=str(angle)),
            )
            assert r.status_code == 200, (tool, r.text)
            assert r.json()["image_path"].startswith(f"raw/{tool}/_/T-020__{angle}__")
    assert [r["grade"] for r in edge.rows()] == ["", "", ""]


@pytest.mark.parametrize(
    "overrides",
    [
        {"grade": "perfect"},
        {"grade": "unusable"},
        {"grade": " "},
        {"grade": "sem grau"},
        {"item_id": "S-010"},
        {"item_id": "N-010"},
        {"item_id": "O-010"},
        {"item_id": "XT-0010"},
        {"object_type": "Drill"},
        {"object_type": "furadeira"},
        {"object_type": "drill "},
    ],
    ids=[
        "perfect",
        "unusable",
        "grade-space",
        "grade-text",
        "S-prefix",
        "N-prefix",
        "O-prefix",
        "XT-via-collect",
        "Drill",
        "label-instead-of-code",
        "trailing-space",
    ],
)
def test_extra_invalid_power_tool_collects(edge: Edge, overrides: dict[str, str | None]) -> None:
    with TestClient(edge.app()) as client:
        before = edge.tree()
        r = post_collect(client, edge.token, collect_fields(**overrides))
        assert r.status_code == 422, r.text
        assert edge.tree() == before


def test_extra_power_tool_item_cannot_change_type(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        ok = post_collect(client, edge.token, collect_fields())
        assert ok.status_code == 200, ok.text
        clash = post_collect(
            client, edge.token, collect_fields(object_type="cordless_screwdriver", angle="2")
        )
        clash_hand = post_collect(
            client, edge.token, collect_fields(object_type="pliers", grade="good", angle="3")
        )
    assert clash.status_code == 409, clash.text
    assert clash_hand.status_code == 409, clash_hand.text
    assert len(edge.rows()) == 1


def test_extra_capture_page_offers_the_power_tools(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        r = client.get("/capture", params={"t": edge.token})
    assert r.status_code == 200
    for tool, label in zip(POWER_TOOLS, POWER_LABELS, strict=True):
        assert f'value="{tool}"' in r.text, tool
        assert label in r.text, tool
        assert OBJECT_TYPE_LABELS_PT[ObjectType(tool)] == label


def test_extra_coverage_has_one_row_per_power_tool(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        for i in range(3):
            r = post_collect(client, edge.token, collect_fields(item_id=f"T-03{i}", angle=str(i)))
            assert r.status_code == 200, r.text
        r = post_collect(client, edge.token, collect_fields(item_id="T-030", angle="4"))
        assert r.status_code == 200, r.text
    cells = {(c.object_type, c.grade): c for c in compute_coverage(edge.manifest)}
    for tool in POWER_TOOLS:
        assert (tool, None) in cells, tool
        for grade in GRADES:
            assert (tool, grade) not in cells, (tool, grade)
    assert (cells[("drill", None)].images, cells[("drill", None)].items) == (4, 3)
    assert (cells[("saw", None)].images, cells[("saw", None)].items) == (0, 0)
    assert len(cells) == 11 + 25 + 4
    order = [c.object_type for c in compute_coverage(edge.manifest)]
    assert [t for t in dict.fromkeys(order) if t in POWER_TOOLS] == list(POWER_TOOLS)


def console_get(app: Any, path: str = "/") -> httpx.Response:
    """Console request from loopback, with a loopback ``Host`` (as in SPEC-010's acceptance)."""
    port = EdgeSettings().EDGE_PORT

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(transport=transport, base_url=base) as c:
            return await c.get(path)

    return asyncio.run(go())


def test_extra_console_shows_the_power_tool_rows(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        r = post_collect(client, edge.token, collect_fields())
        assert r.status_code == 200, r.text
    page = console_get(edge.app())
    assert page.status_code == 200, page.text
    start = page.text.index('<table id="coverage">')
    table = page.text[start : page.text.index("</table>", start)]
    for label in POWER_LABELS:
        assert label in table, label
    assert "power" not in table and "drill" not in table  # PT-BR labels only


# =========================================================================== extras: import


@pytest.mark.parametrize(
    ("row", "expected_column"),
    [
        (("T-501", "drill", "fair", "contributor"), "grade"),
        (("XT-0020", "cordless_screwdriver", "poor", "external"), "grade"),
        (("S-501", "drill", "", "contributor"), "object_type"),
        (("O-501", "saw", "", "contributor"), "object_type"),
        (("XS-0020", "angle_grinder", "", "external"), "object_type"),
        (("T-501", "Drill", "", "contributor"), "object_type"),
    ],
    ids=["T-graded", "XT-graded", "S-prefix", "O-prefix", "XS-prefix", "case"],
)
def test_extra_power_tool_plan_problems(
    imp: ImportEnv, row: tuple[str, str, str, str], expected_column: str
) -> None:
    item_id, object_type, grade, origin = row
    imp.write_plan(
        [plan_row(imp.put("x.jpg", synthetic_jpeg(seed=9)), item_id, object_type, grade, origin)]
    )
    before = imp.snapshot()
    code, out, err = imp.run()
    assert code == 2, out + err
    problems = _problem_lines(err)
    assert any(
        line.startswith("plan line 2: ") and line.endswith(f"({expected_column})")
        for line in problems
    ), err
    assert imp.snapshot() == before


def test_extra_graded_power_tool_problem_has_the_code_of_a_graded_other(imp: ImportEnv) -> None:
    """Same problem code as ``other`` with a grade (no new code invented, SPEC-036 §4.2)."""
    imp.write_plan(
        [
            plan_row(
                imp.put("o.jpg", synthetic_jpeg(seed=3)), "O-501", "other", "good", "contributor"
            )
        ]
    )
    _, _, err_other = imp.run()
    imp.write_plan(
        [
            plan_row(
                imp.put("d.jpg", synthetic_jpeg(seed=4)), "T-501", "drill", "good", "contributor"
            )
        ]
    )
    _, _, err_power = imp.run()
    assert _problem_lines(err_other) == _problem_lines(err_power), (err_other, err_power)


@pytest.mark.parametrize("tool", POWER_TOOLS)
def test_extra_every_power_tool_imports_with_t_and_xt(imp: ImportEnv, tool: str) -> None:
    rows = [
        plan_row(imp.put("c.jpg", synthetic_jpeg(seed=31)), "T-700", tool, "", "contributor"),
        plan_row(imp.put("e.jpg", synthetic_jpeg(seed=32)), "XT-0700", tool, "", "external"),
    ]
    imp.write_plan(rows)
    code, out, err = imp.run()
    assert code == 0, out + err
    manifest = imp.manifest_rows()
    assert manifest[0]["image_path"].startswith(f"raw/{tool}/_/T-700__0__")
    assert manifest[1]["image_path"].startswith(f"raw/{tool}/_/XT-0700__0__")
    assert [r["grade"] for r in manifest] == ["", ""]


def test_extra_power_tool_import_is_idempotent_and_dry_run_writes_nothing(imp: ImportEnv) -> None:
    imp.write_plan(ca07_rows(imp)[:1])
    code, out, err = imp.run("--dry-run")
    assert code == 0, out + err
    assert imp.snapshot() == {}
    assert imp.run()[0] == 0
    first = imp.snapshot()
    code, out, err = imp.run()
    assert code == 0, out + err
    assert imp.snapshot() == first
    assert len(imp.manifest_rows()) == 1
