"""Acceptance tests for SPEC-016 (qc-edge: hand tools in the model, decision, collect and import).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-07 to CA-11. Tests named ``test_extra_*`` are exploratory edge cases
around SPEC-016 section 4.4 that no CA spells out.

Rules followed (``docs/architecture.md`` §10, R-03, R-14): the dummy ONNX models of SPEC-008 §6
are built here with ``onnx.helper`` in ``tmp_path`` (no torch, no binary in Git); every image is
synthetic and generated in memory; session tokens are built at run time; ``DATASET_DIR``, the
outbox and the import inbox always live under ``tmp_path``; no test runs pytest in a subprocess;
nothing is mocked besides the clock and the sleep of the importer (the boundaries its ``main``
accepts).
"""

from __future__ import annotations

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

import numpy as np
import onnx
import pytest
from fastapi.testclient import TestClient
from onnx import TensorProto, helper
from PIL import Image, ImageFile

import qc_edge.importer
from qc_contracts import (
    GRADE_LABELS_PT,
    OBJECT_TYPE_LABELS_PT,
    Grade,
    InspectionCreate,
    ObjectType,
)
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
TOOLS = ("pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver")
CA_TYPES = ("screw", "nut", "other", "pliers")
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
MANIFEST_COLUMNS = [
    "image_path",
    "item_id",
    "object_type",
    "grade",
    "labeler",
    "angle",
    "captured_at",
    "capture_device",
    "notes",
]
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
    "fonte-ferramentas,Fonte de teste,https://example.org/ferramentas,CC-BY-4.0,"
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
    graph = helper.make_graph(nodes, "acc16-dummy", [inp], [out_t, out_g], initializer=inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model.SerializeToString()


_ABSENT = object()


def make_model_dir(
    root: Path,
    name: str = "partqc-acc16-v1",
    *,
    object_types: Sequence[str] = CA_TYPES,
    ungraded: Any = _ABSENT,
    type_probs: Sequence[float] = (0.05, 0.03, 0.02, 0.90),
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


def synthetic_jpeg(width: int = 400, height: int = 300, seed: int = 16) -> bytes:
    """Gradient plus noise: no person, no real photo (R-14)."""
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 255, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 255, height, dtype=np.float32)[:, None]
    base = np.stack([x + 0 * y, y + 0 * x, (x + y) / 2], axis=-1)
    arr = np.clip(base + rng.normal(0, 15, (height, width, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def solid_jpeg(color: str = "steelblue") -> bytes:
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


def post_capture(client: TestClient, token: str, lot_id: str = "L-016") -> Any:
    return client.post(
        "/api/capture",
        headers={SESSION_HEADER: token},
        data={"lot_id": lot_id, "mode": "inspect"},
        files={"image": ("foto.jpg", synthetic_jpeg(), "image/jpeg")},
    )


def collect_fields(**overrides: str | None) -> dict[str, str]:
    base: dict[str, str | None] = {
        "mode": "collect",
        "item_id": "T-001",
        "object_type": "pliers",
        "grade": "good",
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


def ca_labels(ungraded: Sequence[str]) -> ModelLabels:
    return ModelLabels(object_types=CA_TYPES, grades=GRADES, ungraded_object_types=tuple(ungraded))


# =========================================================================== CA-07


@pytest.mark.parametrize(
    "ungraded",
    [_ABSENT, ["pliers"]],
    ids=["absent", "pliers"],
)
def test_ca07_valid_ungraded_lists_load(models: Path, ungraded: Any) -> None:
    d = make_model_dir(models, ungraded=ungraded)
    inf = OnnxInferencer(d)
    assert inf.model_info.model_version == "partqc-acc16-v1"


@pytest.mark.parametrize(
    "ungraded",
    [["screw"], ["other"], ["allen_key"], ["pliers", "pliers"], "pliers"],
    ids=["screw", "other", "outside-object-types", "repeated", "text-not-list"],
)
def test_ca07_invalid_ungraded_lists_are_refused(models: Path, ungraded: Any) -> None:
    d = make_model_dir(models, ungraded=ungraded)
    with pytest.raises(ModelLoadError):
        OnnxInferencer(d)


# =========================================================================== CA-08


def test_ca08_ungraded_tool_has_no_grade_and_no_review() -> None:
    d = decide([0.05, 0.03, 0.02, 0.90], GRADE_PROBS, ca_labels(["pliers"]), CA_THRESHOLDS)
    assert d.object_type == ObjectType.PLIERS
    assert d.grade is None
    assert d.grade_score is None
    assert d.grade_confidence is None
    assert d.needs_review is False


def test_ca08_ungraded_tool_with_low_margin_needs_review() -> None:
    d = decide([0.2, 0.1, 0.15, 0.55], GRADE_PROBS, ca_labels(["pliers"]), CA_THRESHOLDS)
    assert d.object_type == ObjectType.PLIERS
    assert d.grade is None
    assert d.needs_review is True


def test_ca08_graded_tool_follows_the_grade_rule() -> None:
    d = decide([0.05, 0.03, 0.02, 0.90], GRADE_PROBS, ca_labels([]), CA_THRESHOLDS)
    assert d.object_type == ObjectType.PLIERS
    assert d.grade == Grade(GRADES[int(np.argmax(GRADE_PROBS))])
    assert d.grade == Grade.FAIR
    assert d.grade_confidence == pytest.approx(0.7)
    assert d.grade_score == pytest.approx(sum(i * p for i, p in enumerate(GRADE_PROBS)))


# =========================================================================== CA-09


def test_ca09_capture_of_ungraded_tool_reaches_the_outbox(edge: Edge, models: Path) -> None:
    d = make_model_dir(models, ungraded=["pliers"])
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
    assert body["labels_pt"]["grade"] is None
    assert body["inspection"]["object_type"] == "pliers"
    assert body["inspection"]["grade"] is None
    (stored,) = outbox_payloads(outbox_path)
    insp = InspectionCreate.model_validate(stored)
    assert insp.object_type == ObjectType.PLIERS
    assert insp.grade is None
    assert insp.grade_score is None and insp.grade_confidence is None
    assert insp.model_dump(mode="json") == body["inspection"]


# =========================================================================== CA-10


def test_ca10_tool_is_collected_into_its_grade_directory(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        r = post_collect(client, edge.token, collect_fields())
    assert r.status_code == 200, r.text
    image_path = r.json()["image_path"]
    assert image_path.startswith("raw/pliers/good/T-001__1__")
    assert (edge.dataset / image_path).is_file()
    files = [p for p in (edge.dataset / "raw").rglob("*") if p.is_file()]
    assert [str(p.relative_to(edge.dataset)) for p in files] == [image_path]
    (row,) = edge.rows()
    assert row["image_path"] == image_path
    assert (row["item_id"], row["object_type"], row["grade"]) == ("T-001", "pliers", "good")


@pytest.mark.parametrize(
    "overrides",
    [
        {"item_id": "T-001", "object_type": "screw", "grade": "good"},
        {"item_id": "T-002", "object_type": "allen_key", "grade": ""},
        {"item_id": "S-001", "object_type": "pliers", "grade": "good"},
    ],
    ids=["T-with-screw", "tool-without-grade", "S-with-pliers"],
)
def test_ca10_invalid_tool_collects_are_422_and_nothing_written(
    edge: Edge, overrides: dict[str, str]
) -> None:
    with TestClient(edge.app()) as client:
        before = edge.tree()
        r = post_collect(client, edge.token, collect_fields(**overrides))
        assert r.status_code == 422, r.text
        assert edge.tree() == before
    assert not edge.dataset.exists()


# =========================================================================== CA-11


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
    ref = f"tools/train/{item_id}.png"
    return [file, item_id, object_type, grade, "b", "0", origin, "", "fonte-ferramentas", ref, ""]


def ca11_rows(imp: ImportEnv) -> list[list[str]]:
    return [
        plan_row(
            imp.put("t501.jpg", synthetic_jpeg(seed=1)),
            "T-501",
            "flat_screwdriver",
            "good",
            "contributor",
        ),
        plan_row(
            imp.put("xt1.jpg", synthetic_jpeg(seed=2)), "XT-0001", "pliers", "fair", "external"
        ),
        plan_row(
            imp.put("xt2.jpg", synthetic_jpeg(seed=3)), "XT-0002", "screw", "good", "external"
        ),
    ]


def test_ca11_t_and_xt_tool_rows_are_imported(imp: ImportEnv) -> None:
    """CA-11 (a): a plan with only the first two rows: exit 0, both rows written."""
    rows = ca11_rows(imp)
    imp.write_plan(rows[:2])
    code, out, err = imp.run()
    assert code == 0, out + err
    manifest = imp.manifest_rows()
    assert [(r["item_id"], r["object_type"], r["grade"]) for r in manifest] == [
        ("T-501", "flat_screwdriver", "good"),
        ("XT-0001", "pliers", "fair"),
    ]
    assert manifest[0]["image_path"].startswith("raw/flat_screwdriver/good/T-501__0__")
    assert manifest[1]["image_path"].startswith("raw/pliers/fair/XT-0001__0__")
    for r in manifest:
        assert (imp.dataset / r["image_path"]).is_file()
    sources = imp.sources_rows()
    assert [(s["image_path"], s["origin"]) for s in sources] == [
        (manifest[0]["image_path"], "contributor"),
        (manifest[1]["image_path"], "external"),
    ]
    assert sources[0]["contributor"] == "c01"
    assert sources[1]["source_id"] == "fonte-ferramentas"


def test_ca11_xt_with_screw_is_refused_with_the_prefix_problem(imp: ImportEnv) -> None:
    """CA-11 (b): a plan with only the third row: exit 2, prefix problem, nothing written."""
    rows = ca11_rows(imp)
    imp.write_plan([rows[2]])
    before = imp.snapshot()
    code, out, err = imp.run()
    assert code == 2, out + err
    assert "plan line 2: item_prefix_mismatch (object_type)" in err.splitlines(), err
    assert imp.snapshot() == before


def test_ca11_three_line_plan_follows_the_whole_plan_rule_of_spec036(imp: ImportEnv) -> None:
    """CA-11 (c): the plan with the 3 rows. SPEC-036 §4.2 (phase 1, unchanged by SPEC-016)
    refuses the whole plan when any row has a problem: exit 2, nothing written, not even the
    first two rows (CA-11 text after SPEC_ISSUE-T1, commit 6d25aaf)."""
    imp.write_plan(ca11_rows(imp))
    before = imp.snapshot()
    code, out, err = imp.run()
    assert code == 2, out + err
    assert "plan line 4: item_prefix_mismatch (object_type)" in err.splitlines(), err
    assert imp.snapshot() == before


# =========================================================================== extras: labels


@pytest.mark.parametrize("tool", TOOLS)
def test_extra_each_tool_can_be_ungraded(models: Path, tool: str) -> None:
    d = make_model_dir(
        models,
        object_types=("screw", "nut", "other", tool),
        ungraded=[tool],
    )
    OnnxInferencer(d)


def test_extra_all_five_tools_ungraded_and_empty_list(models: Path) -> None:
    types = ("screw", "nut", "other", *TOOLS)
    probs = [0.9, *([0.1 / 7] * 7)]
    OnnxInferencer(
        make_model_dir(
            models, "dummy-a-v1", object_types=types, ungraded=list(TOOLS), type_probs=probs
        )
    )
    OnnxInferencer(
        make_model_dir(models, "dummy-b-v1", object_types=types, ungraded=[], type_probs=probs)
    )


@pytest.mark.parametrize(
    "ungraded",
    [None, ["nut"], ["unknown"], [1], [["pliers"]], {"pliers": True}, ["PLIERS"], [""]],
    ids=["null", "nut", "unknown", "int", "nested", "object", "upper", "empty-string"],
)
def test_extra_more_invalid_ungraded_values(models: Path, ungraded: Any) -> None:
    d = make_model_dir(models, ungraded=ungraded)
    with pytest.raises(ModelLoadError):
        OnnxInferencer(d)


def test_extra_ungraded_error_does_not_echo_the_value(models: Path) -> None:
    marker = "zz" + secrets.token_hex(4)
    d = make_model_dir(models, ungraded=[marker])
    with pytest.raises(ModelLoadError) as info:
        OnnxInferencer(d)
    assert marker not in str(info.value)


def test_extra_ungraded_types_of_the_loaded_model(models: Path) -> None:
    d = make_model_dir(models, ungraded=["pliers"])
    inf = OnnxInferencer(d)
    result = inf.infer(Image.open(io.BytesIO(synthetic_jpeg())).convert("RGB"))
    assert result.object_type == ObjectType.PLIERS
    assert result.grade is None


# =========================================================================== extras: decision


def test_extra_ungraded_tool_below_type_threshold_is_unknown() -> None:
    d = decide([0.2, 0.15, 0.2, 0.45], GRADE_PROBS, ca_labels(["pliers"]), CA_THRESHOLDS)
    assert d.object_type == ObjectType.UNKNOWN
    assert d.grade is None
    assert d.needs_review is True


def test_extra_ungraded_tool_ignores_unusable_and_low_grade_confidence() -> None:
    for grade_probs in ([0.0, 0.0, 0.0, 0.1, 0.9], [0.2, 0.2, 0.2, 0.2, 0.2]):
        d = decide([0.01, 0.01, 0.01, 0.97], grade_probs, ca_labels(["pliers"]), CA_THRESHOLDS)
        assert d.grade is None and d.grade_confidence is None
        assert d.needs_review is False


def test_extra_review_margin_boundary_for_ungraded_tool() -> None:
    # needs_review = type_confidence < type_threshold + 0.10 (0.6): 0.6 exactly is not review.
    at = decide([0.1, 0.1, 0.2, 0.6], GRADE_PROBS, ca_labels(["pliers"]), CA_THRESHOLDS)
    assert at.needs_review is False
    below = decide([0.1, 0.1, 0.21, 0.59], GRADE_PROBS, ca_labels(["pliers"]), CA_THRESHOLDS)
    assert below.needs_review is True


def test_extra_screw_decision_unchanged_with_an_ungraded_tool() -> None:
    d = decide([0.9, 0.05, 0.03, 0.02], GRADE_PROBS, ca_labels(["pliers"]), CA_THRESHOLDS)
    assert d.object_type == ObjectType.SCREW
    assert d.grade == Grade.FAIR
    assert d.needs_review is False


# =========================================================================== extras: capture


def test_extra_capture_of_a_graded_tool(edge: Edge, models: Path) -> None:
    d = make_model_dir(models, ungraded=[])
    sink = InMemorySink()
    with TestClient(create_app(EdgeSettings(), OnnxInferencer(d), sink)) as client:
        r = post_capture(client, edge.token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inspection"]["object_type"] == "pliers"
    assert body["inspection"]["grade"] == "fair"
    assert body["approved"] is True
    assert body["labels_pt"] == {
        "object_type": OBJECT_TYPE_LABELS_PT[ObjectType.PLIERS],
        "grade": GRADE_LABELS_PT[Grade.FAIR],
        "verdict": "aprovada",
    }


def test_extra_capture_of_ungraded_tool_labels_and_review(edge: Edge, models: Path) -> None:
    d = make_model_dir(models, ungraded=["pliers"], type_probs=(0.2, 0.1, 0.15, 0.55))
    sink = InMemorySink()
    with TestClient(create_app(EdgeSettings(), OnnxInferencer(d), sink)) as client:
        r = post_capture(client, edge.token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["labels_pt"]["object_type"] == "alicate"
    assert body["labels_pt"]["verdict"] == "sem grau"
    assert body["inspection"]["needs_review"] is True
    (item,) = sink.items
    assert item.grade is None and item.needs_review is True


def test_extra_unknown_capture_still_says_desconhecido(edge: Edge, models: Path) -> None:
    d = make_model_dir(models, ungraded=["pliers"], type_probs=(0.05, 0.05, 0.85, 0.05))
    with TestClient(create_app(EdgeSettings(), OnnxInferencer(d), InMemorySink())) as client:
        r = post_capture(client, edge.token)
    body = r.json()
    assert body["inspection"]["object_type"] == "unknown"
    assert body["approved"] is None
    assert body["labels_pt"]["verdict"] == "desconhecido"


# =========================================================================== extras: collect


@pytest.mark.parametrize("tool", TOOLS)
def test_extra_every_tool_and_grade_is_collected(edge: Edge, tool: str) -> None:
    with TestClient(edge.app()) as client:
        for i, grade in enumerate(GRADES):
            r = post_collect(
                client,
                edge.token,
                collect_fields(item_id="T-010", object_type=tool, grade=grade, angle=str(i)),
            )
            assert r.status_code == 200, (tool, grade, r.text)
            assert r.json()["image_path"].startswith(f"raw/{tool}/{grade}/T-010__{i}__")
    assert len(edge.rows()) == 5


@pytest.mark.parametrize(
    "overrides",
    [
        {"item_id": "XT-0001"},
        {"item_id": "T-001", "object_type": "other", "grade": ""},
        {"item_id": "T-001", "object_type": "nut"},
        {"item_id": "T-01"},
        {"item_id": "t-001"},
        {"item_id": "N-001", "object_type": "allen_key"},
        {"item_id": "O-001", "object_type": "phillips_screwdriver"},
        {"grade": None},
        {"grade": "broken"},
        {"object_type": "hammer"},
        {"object_type": "Pliers"},
        {"object_type": "unknown", "grade": ""},
    ],
    ids=[
        "XT-via-collect",
        "T-with-other",
        "T-with-nut",
        "T-short",
        "t-lower",
        "N-with-tool",
        "O-with-tool",
        "tool-grade-absent",
        "tool-grade-invalid",
        "hammer",
        "Pliers",
        "unknown",
    ],
)
def test_extra_more_invalid_tool_collects(edge: Edge, overrides: dict[str, str | None]) -> None:
    with TestClient(edge.app()) as client:
        before = edge.tree()
        r = post_collect(client, edge.token, collect_fields(**overrides))
        assert r.status_code == 422, r.text
        assert edge.tree() == before


def test_extra_tool_item_cannot_change_type(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        ok = post_collect(client, edge.token, collect_fields())
        assert ok.status_code == 200, ok.text
        clash = post_collect(client, edge.token, collect_fields(object_type="allen_key", angle="2"))
    assert clash.status_code == 409, clash.text
    assert len(edge.rows()) == 1


def test_extra_coverage_has_the_tool_rows(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        for i in range(3):
            r = post_collect(
                client, edge.token, collect_fields(item_id=f"T-00{i + 1}", angle=str(i))
            )
            assert r.status_code == 200, r.text
    cells = {(c.object_type, c.grade): c for c in compute_coverage(edge.manifest)}
    for tool in TOOLS:
        for grade in GRADES:
            assert (tool, grade) in cells, (tool, grade)
    assert (cells[("pliers", "good")].images, cells[("pliers", "good")].items) == (3, 3)
    assert (cells[("allen_key", "poor")].images, cells[("allen_key", "poor")].items) == (0, 0)
    assert ("other", None) in cells
    assert len(cells) == 11 + 25 + 4  # SPEC-021 section 3.1: plus one row per power tool


def test_extra_capture_page_offers_the_tools(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        r = client.get("/capture", params={"t": edge.token})
    assert r.status_code == 200
    for tool in TOOLS:
        assert f'value="{tool}"' in r.text, tool
        assert OBJECT_TYPE_LABELS_PT[ObjectType(tool)] in r.text, tool


# =========================================================================== extras: import


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (("T-501", "screw", "good", "contributor"), "item_prefix_mismatch (object_type)"),
        (("S-501", "pliers", "good", "contributor"), "item_prefix_mismatch (object_type)"),
        (("XT-0003", "nut", "good", "external"), "item_prefix_mismatch (object_type)"),
        (("XT-0003", "other", "", "external"), "item_prefix_mismatch (object_type)"),
        (("T-501", "pliers", "", "contributor"), "missing_grade (grade)"),
        (("XT-0004", "allen_key", "", "external"), "missing_grade (grade)"),
        (("T-0001", "pliers", "good", "contributor"), "invalid_item_id (item_id)"),
        (("XT-001", "pliers", "good", "external"), "invalid_item_id (item_id)"),
        (("XT-0005", "pliers", "good", "contributor"), "origin_item_mismatch (item_id)"),
        (("T-502", "pliers", "good", "external"), "origin_item_mismatch (item_id)"),
    ],
    ids=[
        "T-screw",
        "S-pliers",
        "XT-nut",
        "XT-other",
        "T-no-grade",
        "XT-no-grade",
        "T-4-digits",
        "XT-3-digits",
        "contributor-with-XT",
        "external-with-T",
    ],
)
def test_extra_tool_plan_problems(
    imp: ImportEnv, row: tuple[str, str, str, str], expected: str
) -> None:
    item_id, object_type, grade, origin = row
    imp.write_plan(
        [plan_row(imp.put("x.jpg", synthetic_jpeg(seed=9)), item_id, object_type, grade, origin)]
    )
    before = imp.snapshot()
    code, out, err = imp.run()
    assert code == 2, out + err
    assert f"plan line 2: {expected}" in err.splitlines(), err
    assert imp.snapshot() == before


@pytest.mark.parametrize("tool", TOOLS)
def test_extra_every_tool_imports_with_t_and_xt(imp: ImportEnv, tool: str) -> None:
    rows = [
        plan_row(imp.put("c.jpg", synthetic_jpeg(seed=21)), "T-600", tool, "poor", "contributor"),
        plan_row(
            imp.put("e.jpg", synthetic_jpeg(seed=22)), "XT-0600", tool, "unusable", "external"
        ),
    ]
    imp.write_plan(rows)
    code, out, err = imp.run()
    assert code == 0, out + err
    paths = [r["image_path"] for r in imp.manifest_rows()]
    assert paths[0].startswith(f"raw/{tool}/poor/T-600__0__")
    assert paths[1].startswith(f"raw/{tool}/unusable/XT-0600__0__")


def test_extra_import_dry_run_with_tools_writes_nothing(imp: ImportEnv) -> None:
    imp.write_plan(ca11_rows(imp)[:2])
    code, out, err = imp.run("--dry-run")
    assert code == 0, out + err
    assert imp.snapshot() == {}


def test_extra_imported_tool_conflicts_with_collected_type(imp: ImportEnv) -> None:
    """A ``T-`` item already in the manifest with another tool type is refused."""
    imp.write_plan([ca11_rows(imp)[0]])
    assert imp.run()[0] == 0
    imp.write_plan(
        [
            plan_row(
                imp.put("again.jpg", synthetic_jpeg(seed=31)),
                "T-501",
                "pliers",
                "good",
                "contributor",
            )
        ]
    )
    before = imp.snapshot()
    code, out, err = imp.run()
    assert code == 2, out + err
    assert "plan line 2: item_type_conflict (item_id)" in err.splitlines(), err
    assert imp.snapshot() == before
