"""Acceptance tests for SPEC-044 (qc-edge: hammer, wrench and spirit level, identification only).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-05 (model and decision), CA-06 (collect), CA-07 (import) and CA-08
(capture page and console). Tests named ``test_extra_*`` are exploratory edge cases around
SPEC-044 sections 3.1 and 4.3 that no CA spells out.

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
import html as html_mod
import io
import json
import logging
import re
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
POWER_TOOLS = ("angle_grinder", "saw", "drill", "cordless_screwdriver")
NEW_TOOLS = ("hammer", "wrench", "spirit_level")
NEW_LABELS = ("martelo", "chave de aperto", "nível")
CA_TYPES = ("screw", "other", "hammer")
CA_TYPE_PROBS = (0.05, 0.05, 0.90)
CA_DECISION_JSON = {"type_threshold": 0.5, "unusable_threshold": 0.4, "grade_review_threshold": 0.6}
CA_THRESHOLDS = Thresholds(type_threshold=0.5, unusable_threshold=0.4, grade_review_threshold=0.6)
GRADE_PROBS = (0.05, 0.1, 0.7, 0.1, 0.05)
MSG_IDENTIFIED = "grade must be empty for an identification-only tool"
MSG_POWER = "grade must be empty for a power tool"
MSG_OTHER = "grade must be empty for other"
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
REGISTRY_HEADER = "source_id,title,url,license,license_url,attribution,retrieved_at"
REGISTRY_LINE = (
    "fonte-ferramentas,Fonte de teste,https://example.org/ferramentas,CC-BY-4.0,"
    "https://creativecommons.org/licenses/by/4.0/,Fonte de teste (example.org),2026-11-01"
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
    graph = helper.make_graph(nodes, "acc44-dummy", [inp], [out_t, out_g], initializer=inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model.SerializeToString()


_ABSENT = object()


def make_model_dir(
    root: Path,
    name: str = "partqc-acc44-v1",
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


def synthetic_jpeg(width: int = 400, height: int = 300, seed: int = 44) -> bytes:
    """Gradient plus noise: no person, no real photo (R-14)."""
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 255, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 255, height, dtype=np.float32)[:, None]
    base = np.stack([x + 0 * y, y + 0 * x, (x + y) / 2], axis=-1)
    arr = np.clip(base + rng.normal(0, 15, (height, width, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def solid_jpeg(color: str = "olive") -> bytes:
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
        if not self.manifest.exists():
            return []
        with self.manifest.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def files(self) -> set[str]:
        raw = self.dataset / "raw"
        if not raw.exists():
            return set()
        return {str(p.relative_to(self.dataset)) for p in raw.rglob("*") if p.is_file()}

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


def post_capture(client: TestClient, token: str, lot_id: str = "L-044") -> Any:
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
        "object_type": "spirit_level",
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


def console_get(app: Any, path: str = "/") -> httpx.Response:
    """Console request from loopback, with a loopback ``Host`` (as in SPEC-010's acceptance)."""
    port = EdgeSettings().EDGE_PORT

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(transport=transport, base_url=base) as c:
            return await c.get(path)

    return asyncio.run(go())


def coverage_rows(page: str) -> list[list[str]]:
    """Cells (tags removed, unescaped, stripped) of every ``<tr>`` of ``table#coverage``."""
    start = page.index('<table id="coverage">')
    table = page[start : page.index("</table>", start)]
    rows = []
    for tr in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", table):
        cells = re.findall(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>", tr)
        rows.append([html_mod.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in cells])
    return rows


# =========================================================================== CA-05


def test_ca05_model_with_hammer_and_empty_ungraded_list_is_refused(models: Path) -> None:
    d = make_model_dir(models, ungraded=[])
    with pytest.raises(ModelLoadError):
        OnnxInferencer(d)


def test_ca05_model_with_hammer_listed_as_ungraded_loads(models: Path) -> None:
    d = make_model_dir(models, ungraded=["hammer"])
    inf = OnnxInferencer(d)
    assert inf.model_info.model_version == "partqc-acc44-v1"


def test_ca05_decision_of_a_hammer_has_no_grade() -> None:
    labels = ModelLabels(object_types=CA_TYPES, grades=GRADES, ungraded_object_types=("hammer",))
    d = decide(list(CA_TYPE_PROBS), GRADE_PROBS, labels, CA_THRESHOLDS)
    assert d.object_type == ObjectType.HAMMER
    assert d.grade is None
    assert d.grade_score is None
    assert d.grade_confidence is None


def test_ca05_capture_of_a_hammer_is_ungraded_with_pt_br_labels(edge: Edge, models: Path) -> None:
    d = make_model_dir(models, ungraded=["hammer"])
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
    assert body["labels_pt"]["object_type"] == "martelo"
    assert body["inspection"]["object_type"] == "hammer"
    assert body["inspection"]["grade"] is None
    assert body["inspection"]["grade_score"] is None
    assert body["inspection"]["grade_confidence"] is None
    (stored,) = outbox_payloads(outbox_path)
    insp = InspectionCreate.model_validate(stored)
    assert insp.object_type == ObjectType.HAMMER and insp.grade is None


# =========================================================================== CA-06


def test_ca06_spirit_level_without_grade_is_collected(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        r = post_collect(client, edge.token, collect_fields())
    assert r.status_code == 200, r.text
    image_path = r.json()["image_path"]
    assert image_path.startswith("raw/spirit_level/_/T-010__1__"), image_path
    assert (edge.dataset / image_path).is_file()
    assert edge.files() == {image_path}
    (row,) = edge.rows()
    assert row["image_path"] == image_path
    assert (row["item_id"], row["object_type"], row["grade"]) == ("T-010", "spirit_level", "")


def test_ca06_hammer_with_grade_is_422_with_its_own_message(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        ok = post_collect(client, edge.token, collect_fields())
        assert ok.status_code == 200, ok.text
        files, rows = edge.files(), edge.rows()
        r = post_collect(
            client, edge.token, collect_fields(item_id="T-011", object_type="hammer", grade="good")
        )
    assert r.status_code == 422, r.text
    assert r.json() == {"detail": MSG_IDENTIFIED}
    assert edge.files() == files
    assert edge.rows() == rows


def test_ca06_hammer_with_o_prefix_is_422_and_nothing_written(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        before = edge.tree()
        r = post_collect(client, edge.token, collect_fields(item_id="O-012", object_type="hammer"))
        assert r.status_code == 422, r.text
        assert edge.tree() == before
    assert edge.files() == set() and edge.rows() == []


def test_ca06_drill_with_grade_keeps_the_power_tool_message(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        r = post_collect(
            client, edge.token, collect_fields(item_id="T-013", object_type="drill", grade="good")
        )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == MSG_POWER
    assert edge.files() == set()


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
    now: datetime = field(default_factory=lambda: datetime(2026, 11, 4, 14, 0, 0, tzinfo=UTC))

    def clock(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=max(seconds, 1.0))

    def put(self, name: str, data: bytes) -> str:
        (self.inbox / name).write_bytes(data)
        return name

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
    registry = tmp_path / "registro" / "external_sources.csv"
    registry.parent.mkdir()
    registry.write_text(REGISTRY_HEADER + "\n" + REGISTRY_LINE + "\n", encoding="utf-8")
    return ImportEnv(
        tmp=tmp_path,
        capsys=capsys,
        caplog=caplog,
        dataset=tmp_path / "D",
        inbox=inbox,
        registry=registry,
        plan=tmp_path / "plano.csv",
    )


def plan_row(file: str, item_id: str, object_type: str, grade: str, origin: str) -> list[str]:
    if origin == "contributor":
        return [file, item_id, object_type, grade, "a", "0", origin, "c01", "", "", ""]
    ref = f"tools/{item_id}.png"
    return [file, item_id, object_type, grade, "b", "0", origin, "", "fonte-ferramentas", ref, ""]


def _problem_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith("plan line ")]


def _t601(imp: ImportEnv) -> list[str]:
    return plan_row(
        imp.put("t601.jpg", synthetic_jpeg(seed=601)), "T-601", "hammer", "", "contributor"
    )


def test_ca07_hammer_without_grade_is_imported(imp: ImportEnv) -> None:
    imp.write_plan([_t601(imp)])
    code, out, err = imp.run()
    assert code == 0, out + err
    (row,) = imp.manifest_rows()
    assert (row["item_id"], row["object_type"], row["grade"]) == ("T-601", "hammer", "")
    assert row["image_path"].startswith("raw/hammer/_/T-601__0__"), row["image_path"]
    assert (imp.dataset / row["image_path"]).is_file()


def test_ca07_wrench_with_grade_refuses_the_whole_plan(imp: ImportEnv) -> None:
    rows = [
        _t601(imp),
        plan_row(
            imp.put("t602.jpg", synthetic_jpeg(seed=602)), "T-602", "wrench", "good", "contributor"
        ),
    ]
    imp.write_plan(rows)
    before = imp.snapshot()
    code, out, err = imp.run()
    assert code == 2, out + err
    assert "plan line 3: grade_on_other (grade)" in err, err
    assert all(line.startswith("plan line 3: ") for line in _problem_lines(err)), err
    assert imp.snapshot() == before


def test_ca07_spirit_level_with_o_prefix_is_a_prefix_mismatch(imp: ImportEnv) -> None:
    rows = [
        _t601(imp),
        plan_row(
            imp.put("o603.jpg", synthetic_jpeg(seed=603)),
            "O-603",
            "spirit_level",
            "",
            "contributor",
        ),
    ]
    imp.write_plan(rows)
    before = imp.snapshot()
    code, out, err = imp.run()
    assert code == 2, out + err
    assert "item_prefix_mismatch (object_type)" in err, err
    assert imp.snapshot() == before


# =========================================================================== CA-08


def test_ca08_capture_page_has_the_three_options(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        r = client.get("/capture", params={"t": edge.token})
    assert r.status_code == 200, r.text
    for tool, label in zip(NEW_TOOLS, NEW_LABELS, strict=True):
        assert f'<option value="{tool}">{label}</option>' in r.text, tool


def _js_t_prefix_list(js: str) -> list[str] | None:
    """``PREFIX_TYPES.T`` of the served script, evaluated by Node (``None`` without Node).

    Only the top-level declarations of the script (from ``"use strict";`` to the first
    ``function``) are evaluated: they need no DOM. Without Node, the caller keeps the static check.
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        return None
    start = js.index('"use strict";')
    head = js[start : js.index("function ", start)]
    script = (
        "const src = require('fs').readFileSync(0, 'utf8');"
        "const out = new Function(src + ';return PREFIX_TYPES;')();"
        "process.stdout.write(JSON.stringify(out));"
    )
    proc = subprocess.run(
        [node, "-e", script], input=head, capture_output=True, text=True, timeout=30, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return list(json.loads(proc.stdout)["T"])


def test_ca08_capture_script_has_the_three_in_the_t_prefix(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        js = client.get("/static/capture.js")
    assert js.status_code == 200
    assert "PREFIX_TYPES" in js.text
    for tool in NEW_TOOLS:
        assert f'"{tool}"' in js.text or f"'{tool}'" in js.text, tool
    t_list = _js_t_prefix_list(js.text)
    if t_list is not None:
        for tool in NEW_TOOLS:
            assert tool in t_list, (tool, t_list)
        assert "other" not in t_list and "screw" not in t_list, t_list
        for tool in POWER_TOOLS:
            assert tool in t_list, (tool, t_list)


def test_ca08_console_coverage_has_one_row_per_new_tool(edge: Edge) -> None:
    page = console_get(edge.app())
    assert page.status_code == 200, page.text
    rows = coverage_rows(page.text)
    for label in NEW_LABELS:
        matching = [r for r in rows if label in r]
        assert len(matching) == 1, (label, matching)
        assert "sem grau" in matching[0], matching[0]


# =========================================================================== extras: model


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_extra_each_new_tool_must_be_listed_as_ungraded(models: Path, tool: str) -> None:
    types = ("screw", "other", tool)
    with pytest.raises(ModelLoadError):
        OnnxInferencer(make_model_dir(models, "absent-v1", object_types=types))
    with pytest.raises(ModelLoadError):
        OnnxInferencer(make_model_dir(models, "empty-v1", object_types=types, ungraded=[]))
    OnnxInferencer(make_model_dir(models, "ok-v1", object_types=types, ungraded=[tool]))


def test_extra_model_with_the_15_types_needs_all_ungraded_tools(models: Path) -> None:
    hand = ("pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver")
    types = ("screw", "nut", "other", *hand, *POWER_TOOLS, *NEW_TOOLS)
    probs = [0.9, *([0.1 / 14] * 14)]
    ungraded = [*POWER_TOOLS, *NEW_TOOLS]
    OnnxInferencer(
        make_model_dir(models, "all-v1", object_types=types, ungraded=ungraded, type_probs=probs)
    )
    missing = make_model_dir(
        models, "missing-v1", object_types=types, ungraded=ungraded[:-1], type_probs=probs
    )
    with pytest.raises(ModelLoadError):
        OnnxInferencer(missing)


@pytest.mark.parametrize(
    "ungraded",
    [["hammer", "wrench"], ["hammer", "hammer"], ["Hammer"], ["hammer", "screw"], ["level"]],
    ids=["outside-object-types", "repeated", "case", "with-screw", "level"],
)
def test_extra_invalid_ungraded_lists_with_a_new_tool(models: Path, ungraded: Any) -> None:
    with pytest.raises(ModelLoadError):
        OnnxInferencer(make_model_dir(models, ungraded=ungraded))


def test_extra_hammer_decision_ignores_unusable_and_low_type_is_unknown() -> None:
    labels = ModelLabels(object_types=CA_TYPES, grades=GRADES, ungraded_object_types=("hammer",))
    d = decide([0.01, 0.01, 0.98], [0.0, 0.0, 0.0, 0.1, 0.9], labels, CA_THRESHOLDS)
    assert d.object_type == ObjectType.HAMMER and d.grade is None and d.needs_review is False
    below = decide([0.3, 0.25, 0.45], GRADE_PROBS, labels, CA_THRESHOLDS)
    assert below.object_type == ObjectType.UNKNOWN and below.grade is None


@pytest.mark.parametrize(("tool", "label"), list(zip(NEW_TOOLS, NEW_LABELS, strict=True)))
def test_extra_capture_of_each_new_tool(edge: Edge, models: Path, tool: str, label: str) -> None:
    d = make_model_dir(models, object_types=("screw", "other", tool), ungraded=[tool])
    with TestClient(create_app(EdgeSettings(), OnnxInferencer(d), InMemorySink())) as client:
        r = post_capture(client, edge.token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approved"] is None
    assert body["labels_pt"] == body["labels_pt"] | {"verdict": "sem grau", "object_type": label}
    assert body["labels_pt"].get("grade") is None
    assert OBJECT_TYPE_LABELS_PT[ObjectType(tool)] == label


# =========================================================================== extras: collect


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_extra_every_new_tool_is_collected_without_grade(edge: Edge, tool: str) -> None:
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


@pytest.mark.parametrize("tool", NEW_TOOLS)
@pytest.mark.parametrize("grade", GRADES)
def test_extra_every_grade_on_every_new_tool_has_the_new_message(
    edge: Edge, tool: str, grade: str
) -> None:
    with TestClient(edge.app()) as client:
        r = post_collect(client, edge.token, collect_fields(object_type=tool, grade=grade))
    assert r.status_code == 422, r.text
    assert r.json() == {"detail": MSG_IDENTIFIED}
    assert edge.files() == set()


def test_extra_other_keeps_its_own_message(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        r = post_collect(
            client, edge.token, collect_fields(item_id="O-001", object_type="other", grade="good")
        )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == MSG_OTHER


@pytest.mark.parametrize(
    "overrides",
    [
        {"grade": " "},
        {"grade": "sem grau"},
        {"item_id": "S-010"},
        {"item_id": "N-010"},
        {"item_id": "XT-0010"},
        {"object_type": "Hammer"},
        {"object_type": "martelo"},
        {"object_type": "spirit_level "},
        {"object_type": "level"},
    ],
    ids=[
        "grade-space",
        "grade-text",
        "S-prefix",
        "N-prefix",
        "XT-via-collect",
        "case",
        "label-instead-of-code",
        "trailing-space",
        "level",
    ],
)
def test_extra_invalid_new_tool_collects(edge: Edge, overrides: dict[str, str | None]) -> None:
    with TestClient(edge.app()) as client:
        before = edge.tree()
        r = post_collect(client, edge.token, collect_fields(**overrides))
        assert r.status_code == 422, r.text
        assert edge.tree() == before


def test_extra_new_tool_item_cannot_change_type(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        ok = post_collect(client, edge.token, collect_fields(object_type="wrench"))
        assert ok.status_code == 200, ok.text
        clash = post_collect(client, edge.token, collect_fields(object_type="hammer", angle="2"))
        clash_power = post_collect(client, edge.token, collect_fields(object_type="saw", angle="3"))
    assert clash.status_code == 409, clash.text
    assert clash_power.status_code == 409, clash_power.text
    assert len(edge.rows()) == 1


# =========================================================================== extras: page/console


def test_extra_options_come_after_the_power_tools(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        page = client.get("/capture", params={"t": edge.token}).text
    values = re.findall(r'<option value="([a-z_]+)"', page)
    for tool in NEW_TOOLS:
        assert tool in values, tool
    last_power = max(values.index(t) for t in POWER_TOOLS)
    idx = [values.index(t) for t in NEW_TOOLS]
    assert idx == sorted(idx)
    assert idx[0] > last_power


def test_extra_coverage_counts_new_tools_one_row_each(edge: Edge) -> None:
    with TestClient(edge.app()) as client:
        for i, tool in enumerate(NEW_TOOLS):
            for angle in range(i + 1):
                r = post_collect(
                    client,
                    edge.token,
                    collect_fields(item_id=f"T-05{i}", object_type=tool, angle=str(angle)),
                )
                assert r.status_code == 200, r.text
    cells = {(c.object_type, c.grade): c for c in compute_coverage(edge.manifest)}
    for i, tool in enumerate(NEW_TOOLS):
        assert (cells[(tool, None)].images, cells[(tool, None)].items) == (i + 1, 1)
        for grade in GRADES:
            assert (tool, grade) not in cells
    order = [c.object_type for c in compute_coverage(edge.manifest)]
    seen = list(dict.fromkeys(order))
    assert [t for t in seen if t in NEW_TOOLS] == list(NEW_TOOLS)
    assert seen.index("hammer") > max(seen.index(t) for t in POWER_TOOLS)


def test_extra_console_targets_text_and_pt_br_only(edge: Edge) -> None:
    page = console_get(edge.app())
    assert page.status_code == 200
    text = html_mod.unescape(re.sub(r"<[^>]+>", " ", page.text))
    text = re.sub(r"\s+", " ", text)
    assert "Ferramentas só identificadas (sem grau): martelo, chave de aperto e nível" in text
    start = page.text.index('<table id="coverage">')
    table = page.text[start : page.text.index("</table>", start)]
    for tool in NEW_TOOLS:
        assert f">{tool}<" not in table, tool  # PT-BR labels only
    for label in NEW_LABELS:
        (row,) = [r for r in coverage_rows(page.text) if label in r]
        assert row == [label, "sem grau", "0/90", "0/6"], row
    assert "(mínimo 3)" in text.split("Ferramentas só identificadas", 1)[1].split(".", 1)[0]


# =========================================================================== extras: import


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_extra_every_new_tool_imports_with_t_and_xt(imp: ImportEnv, tool: str) -> None:
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


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (("XT-0020", "spirit_level", "poor", "external"), "grade_on_other (grade)"),
        (("S-501", "hammer", "", "contributor"), "item_prefix_mismatch (object_type)"),
        (("XS-0020", "wrench", "", "external"), "item_prefix_mismatch (object_type)"),
        (("T-501", "Hammer", "", "contributor"), "(object_type)"),
    ],
    ids=["XT-graded", "S-prefix", "XS-prefix", "case"],
)
def test_extra_new_tool_plan_problems(
    imp: ImportEnv, row: tuple[str, str, str, str], expected: str
) -> None:
    item_id, object_type, grade, origin = row
    imp.write_plan(
        [plan_row(imp.put("x.jpg", synthetic_jpeg(seed=9)), item_id, object_type, grade, origin)]
    )
    before = imp.snapshot()
    code, out, err = imp.run()
    assert code == 2, out + err
    assert any(
        line.startswith("plan line 2: ") and line.endswith(expected) for line in _problem_lines(err)
    ), err
    assert imp.snapshot() == before


def test_extra_new_tool_import_is_idempotent_and_dry_run_writes_nothing(imp: ImportEnv) -> None:
    imp.write_plan([_t601(imp)])
    code, out, err = imp.run("--dry-run")
    assert code == 0, out + err
    assert imp.snapshot() == {}
    assert imp.run()[0] == 0
    first = imp.snapshot()
    code, out, err = imp.run()
    assert code == 0, out + err
    assert imp.snapshot() == first
    assert len(imp.manifest_rows()) == 1
