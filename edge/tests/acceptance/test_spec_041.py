"""Acceptance tests for SPEC-041 (provisional model and floor of ``split_v1``), edge part.

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. CAs 17 to 21 and 26 to 30 live here; the other automatable CAs live in
``ml/tests/acceptance/test_spec_041.py``. CA-22 is manual and stays pending. Tests named
``test_extra_*`` are exploratory edge cases that no CA spells out.

Rules followed (``docs/architecture.md`` section 10):

* the dummy models are the ones of the SPEC-008 tests (``dummy_model`` fixture), in ``tmp_path``;
* the outbox is real; the only boundaries replaced are ``uvicorn.run``, the LAN socket, the clock
  and ``sleep`` of the importer and, in one extra, the HTTP transport to the cloud;
* every image is generated here with Pillow, never a real photo (R-14), and every token at run time.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import random
import secrets
import sqlite3
import subprocess
import sys
import types
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import uvicorn
from fastapi.testclient import TestClient
from PIL import Image, ImageFile

import qc_edge.cli
import qc_edge.collect
import qc_edge.importer
import qc_edge.inference
import qc_edge.netinfo
from qc_contracts import GRADE_FORBIDDEN_OBJECT_TYPES, InspectionCreate
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.onnx_inferencer import OnnxInferencer
from qc_edge.outbox import SqliteOutbox
from qc_edge.publish_loop import ConnectivityState, PublishLoop
from qc_edge.publisher import HttpPublisher
from qc_edge.sink import InMemorySink

pytestmark = pytest.mark.acceptance

AGENT = "agent-suggestion"
PROVISIONAL = "partqc-mnv3-provisional-v1"
OFFICIAL = "partqc-mnv3-v1"
SUFFIX = " (modelo provisório)"
CONSOLE_NOTICE = " — PROVISÓRIO: resultados publicados como simulados (ADR-024)"
LOG_NOTICE = "provisional model loaded: results are published as source=simulated (ADR-024)"
SESSION_HEADER = "X-Session-Token"
CURRENT_VERDICTS = {"aprovada", "reprovada", "desconhecido", "sem grau"}
CONTRACT_FIELDS = set(InspectionCreate.model_fields)
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
    "HEARTBEAT_INTERVAL_S",
    "EDGE_PUBLISHER",
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
    "MQTT_RESPONSE_TIMEOUT_S",
)
VERSIONS_CA20 = [
    ("partqc-mnv3-provisional-v1", True),
    ("partqc-provisional-v1", True),
    ("partqc-mnv3-v1", False),
    ("partqc-mnv3-corn-v2", False),
    ("stub-v0", False),
    ("provisional", False),
]

SCREW_GOOD = {"type_probs": (0.9, 0.05, 0.05), "grade_probs": (0.05, 0.8, 0.05, 0.05, 0.05)}
NUT_POOR = {"type_probs": (0.05, 0.9, 0.05), "grade_probs": (0.05, 0.05, 0.05, 0.8, 0.05)}
OTHER = {"type_probs": (0.05, 0.05, 0.9), "grade_probs": (0.05, 0.8, 0.05, 0.05, 0.05)}
LOW_TYPE = {"type_probs": (0.4, 0.3, 0.3), "grade_probs": (0.05, 0.8, 0.05, 0.05, 0.05)}
SCREW_UNUSABLE = {"type_probs": (0.9, 0.05, 0.05), "grade_probs": (0.05, 0.05, 0.05, 0.05, 0.8)}


# =========================================================================== edge fixtures


def synthetic_jpeg(width: int = 640, height: int = 480, seed: int = 8) -> bytes:
    rng = np.random.default_rng(seed)
    small = rng.integers(40, 216, size=(max(2, height // 40), max(2, width // 40), 3))
    image = Image.fromarray(small.astype(np.uint8), "RGB").resize(
        (width, height), Image.Resampling.BILINEAR
    )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


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


@dataclass
class EdgeEnv:
    tmp: Path
    data_dir: Path
    dataset: Path
    token: str

    def outbox_rows(self, path: Path) -> list[dict[str, Any]]:
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute("SELECT * FROM outbox")]
        finally:
            con.close()


@pytest.fixture
def edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EdgeEnv:
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    data_dir = tmp_path / "edge-data"
    dataset = tmp_path / "dataset"
    token = secrets.token_urlsafe(30)
    monkeypatch.setenv("EDGE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATASET_DIR", str(dataset))
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    monkeypatch.setattr(qc_edge.netinfo, "socket", fake_socket_module("192.168.0.42"))
    return EdgeEnv(tmp=tmp_path, data_dir=data_dir, dataset=dataset, token=token)


def post_capture(client: TestClient, token: str, lot_id: str = "ENSAIO-01") -> httpx.Response:
    return client.post(
        "/api/capture",
        headers={SESSION_HEADER: token},
        data={"lot_id": lot_id, "mode": "inspect"},
        files={"image": ("foto.jpg", synthetic_jpeg(), "image/jpeg")},
    )


def capture_with(
    edge: EdgeEnv, dummy_model: Any, version: str, **probs: Any
) -> tuple[httpx.Response, list[dict[str, Any]]]:
    """A real inferencer in ``models/<version>`` and a real outbox; the response and its rows."""
    directory = dummy_model.write_model_dir(
        edge.tmp / f"models-{secrets.token_hex(4)}", version, **probs
    )
    inferencer = OnnxInferencer(directory)
    path = edge.tmp / f"outbox-{secrets.token_hex(4)}.sqlite3"
    outbox = SqliteOutbox(path)
    try:
        app = create_app(EdgeSettings(), inferencer, outbox)
        with TestClient(app) as client:
            response = post_capture(client, edge.token)
    finally:
        outbox.close()
    return response, edge.outbox_rows(path)


def asgi_get(app: Any, path: str = "/") -> httpx.Response:
    """Console GET from loopback (``Host: 127.0.0.1:<EDGE_PORT>``, SPEC-025)."""
    port = os.environ.get("EDGE_PORT", "8000")

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url=f"http://127.0.0.1:{port}") as c:
            return await c.get(path)

    return asyncio.run(go())


def run_cli(monkeypatch: pytest.MonkeyPatch, drive: Callable[[Any], None], *args: str) -> int:
    def spy(app: Any, *a: Any, **k: Any) -> None:
        drive(app)

    monkeypatch.setattr(uvicorn, "run", spy)
    monkeypatch.setattr(sys, "argv", ["qc-edge", *args])
    try:
        qc_edge.cli.main()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return 0


# =========================================================================== CA-17 and CA-18


def test_ca17_provisional_model_publishes_as_simulated(edge: EdgeEnv, dummy_model: Any) -> None:
    response, rows = capture_with(edge, dummy_model, PROVISIONAL)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["inspection"]["source"] == "simulated"
    assert body["inspection"]["model_version"] == PROVISIONAL
    assert len(rows) == 1
    assert json.loads(rows[0]["payload"])["source"] == "simulated"
    assert rows[0]["inspection_id"] == body["inspection"]["inspection_id"]
    assert body["labels_pt"]["verdict"].endswith(SUFFIX)
    # The page gets no new field.
    assert set(body) == {"inspection", "labels_pt", "approved"}
    assert set(body["labels_pt"]) == {"object_type", "grade", "verdict"}
    assert set(body["inspection"]) == CONTRACT_FIELDS


def test_ca18_official_model_stays_live_without_the_suffix(edge: EdgeEnv, dummy_model: Any) -> None:
    response, rows = capture_with(edge, dummy_model, OFFICIAL)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["inspection"]["source"] == "live"
    assert body["inspection"]["model_version"] == OFFICIAL
    assert json.loads(rows[0]["payload"])["source"] == "live"
    assert body["labels_pt"]["verdict"] in CURRENT_VERDICTS
    assert SUFFIX.strip() not in body["labels_pt"]["verdict"]
    assert set(body) == {"inspection", "labels_pt", "approved"}


@pytest.mark.parametrize(
    "probs, verdict, approved",
    [
        (SCREW_GOOD, "aprovada", True),
        (NUT_POOR, "reprovada", False),
        (SCREW_UNUSABLE, "reprovada", False),
        (OTHER, "desconhecido", None),
        (LOW_TYPE, "desconhecido", None),
    ],
    ids=["approved", "rejected-poor", "rejected-unusable", "other", "low-confidence"],
)
def test_extra_every_verdict_gets_the_suffix_and_only_that_changes(
    edge: EdgeEnv, dummy_model: Any, probs: dict[str, Any], verdict: str, approved: bool | None
) -> None:
    official, _ = capture_with(edge, dummy_model, OFFICIAL, **probs)
    provisional, _ = capture_with(edge, dummy_model, PROVISIONAL, **probs)
    assert official.status_code == provisional.status_code == 200

    left, right = official.json(), provisional.json()
    assert left["labels_pt"]["verdict"] == verdict
    assert right["labels_pt"]["verdict"] == verdict + SUFFIX
    assert left["approved"] is approved
    assert right["approved"] is approved
    assert left["labels_pt"]["object_type"] == right["labels_pt"]["object_type"]
    assert left["labels_pt"]["grade"] == right["labels_pt"]["grade"]
    for key in ("object_type", "grade", "needs_review", "type_confidence", "grade_confidence"):
        assert left["inspection"][key] == right["inspection"][key], key


def test_extra_verdict_without_grade_also_gets_the_suffix(edge: EdgeEnv, dummy_model: Any) -> None:
    tool = sorted(t.value for t in GRADE_FORBIDDEN_OBJECT_TYPES)[0]
    response, rows = capture_with(
        edge,
        dummy_model,
        PROVISIONAL,
        type_probs=(0.03, 0.03, 0.04, 0.9),
        object_types=("screw", "nut", "other", tool),
        ungraded_object_types=(tool,),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["labels_pt"]["verdict"] == "sem grau" + SUFFIX
    assert body["approved"] is None
    assert json.loads(rows[0]["payload"])["source"] == "simulated"


def test_extra_official_name_on_a_symlink_to_a_provisional_directory(
    edge: EdgeEnv, dummy_model: Any
) -> None:
    target = dummy_model.write_model_dir(edge.tmp / "models", PROVISIONAL)
    link = edge.tmp / "models" / OFFICIAL
    link.symlink_to(target)
    sink = InMemorySink()
    app = create_app(EdgeSettings(), OnnxInferencer(link), sink)
    with TestClient(app) as client:
        response = post_capture(client, edge.token)
    assert response.json()["inspection"]["source"] == "simulated"


def test_extra_relative_model_dir_uses_the_real_name(
    edge: EdgeEnv, dummy_model: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = dummy_model.write_model_dir(edge.tmp / "models", PROVISIONAL)
    monkeypatch.chdir(directory)
    app = create_app(EdgeSettings(), OnnxInferencer(Path(".")), InMemorySink())
    with TestClient(app) as client:
        response = post_capture(client, edge.token)
    assert response.json()["inspection"]["source"] == "simulated"


def test_extra_status_has_no_new_field(edge: EdgeEnv, dummy_model: Any) -> None:
    bodies: dict[str, Any] = {}
    for version in (OFFICIAL, PROVISIONAL):
        directory = dummy_model.write_model_dir(edge.tmp / "models", version)
        app = create_app(EdgeSettings(), OnnxInferencer(directory), InMemorySink())
        with TestClient(app) as client:
            response = client.get("/api/status", headers={SESSION_HEADER: edge.token})
        assert response.status_code == 200
        bodies[version] = response.json()
    assert set(bodies[OFFICIAL]) == set(bodies[PROVISIONAL])
    assert set(bodies[OFFICIAL]["model"]) == set(bodies[PROVISIONAL]["model"])
    assert PROVISIONAL not in json.dumps(bodies[OFFICIAL])


def test_extra_stub_model_flag_does_not_change(
    edge: EdgeEnv, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    seen: dict[str, Any] = {}

    def drive(app: Any) -> None:
        with TestClient(app) as client:
            seen["capture"] = post_capture(client, edge.token)
        seen["console"] = asgi_get(app)

    with caplog.at_level(logging.INFO):
        assert run_cli(monkeypatch, drive, "--stub-model") == 0
    body = seen["capture"].json()
    assert body["inspection"]["source"] == "live"
    assert not body["labels_pt"]["verdict"].endswith(SUFFIX)
    assert "PROVISÓRIO" not in seen["console"].text
    assert "provisional model loaded" not in caplog.text


# =========================================================================== CA-19


def _boot(
    edge: EdgeEnv,
    dummy_model: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    version: str,
) -> tuple[httpx.Response, str]:
    directory = dummy_model.write_model_dir(edge.tmp / "models", version)
    monkeypatch.setenv("MODEL_DIR", str(directory))
    seen: dict[str, httpx.Response] = {}

    def drive(app: Any) -> None:
        seen["console"] = asgi_get(app)

    with caplog.at_level(logging.INFO):
        assert run_cli(monkeypatch, drive) == 0
    out = capsys.readouterr()
    return seen["console"], "\n".join((caplog.text, out.out, out.err))


def test_ca19_console_and_log_say_the_model_is_provisional(
    edge: EdgeEnv,
    dummy_model: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    console, log = _boot(edge, dummy_model, monkeypatch, caplog, capsys, PROVISIONAL)

    assert console.status_code == 200
    assert "PROVISÓRIO" in console.text
    assert CONSOLE_NOTICE in console.text
    assert LOG_NOTICE in log
    warned = [r for r in caplog.records if LOG_NOTICE in r.getMessage()]
    assert warned and all(r.levelno == logging.WARNING for r in warned)


def test_ca19_official_model_has_neither(
    edge: EdgeEnv,
    dummy_model: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    console, log = _boot(edge, dummy_model, monkeypatch, caplog, capsys, OFFICIAL)

    assert console.status_code == 200
    assert OFFICIAL in console.text
    assert "PROVISÓRIO" not in console.text
    assert "provisional model loaded" not in log
    assert "model loaded" in log  # the log really was captured


def test_extra_console_without_a_model_has_no_notice(edge: EdgeEnv) -> None:
    app = create_app(EdgeSettings(), None, InMemorySink())
    console = asgi_get(app)
    assert console.status_code == 200
    assert "PROVISÓRIO" not in console.text


# =========================================================================== CA-20 and CA-21


@pytest.mark.parametrize("version, expected", VERSIONS_CA20)
def test_ca20_same_rule_in_both_packages(version: str, expected: bool) -> None:
    ml_config = pytest.importorskip("qc_ml.config")
    assert qc_edge.inference.is_provisional_version(version) is expected
    assert ml_config.is_provisional_version(version) is expected


def test_ca21_published_payload_is_only_the_contract(edge: EdgeEnv, dummy_model: Any) -> None:
    assert InspectionCreate.model_config["extra"] == "forbid"
    response, rows = capture_with(edge, dummy_model, PROVISIONAL)
    assert response.status_code == 200, response.text
    raw = rows[0]["payload"]

    payload = json.loads(raw)

    assert set(payload) == CONTRACT_FIELDS
    parsed = InspectionCreate.model_validate(payload)
    assert parsed.source.value == "simulated"
    assert not [
        k for k in payload if any(w in k.lower() for w in ("image", "photo", "jpeg", "b64"))
    ]
    assert len(raw) < 1500, "a payload of this size cannot carry a picture"
    assert "/9j/" not in raw  # base64 of the JPEG SOI


def test_extra_cloud_receives_simulated_and_no_image(
    edge: EdgeEnv, dummy_model: Any, fake_cloud: Any
) -> None:
    directory = dummy_model.write_model_dir(edge.tmp / "models", PROVISIONAL)
    path = edge.tmp / "outbox.sqlite3"
    connectivity = ConnectivityState()
    outbox = SqliteOutbox(path, connectivity=connectivity)
    cloud = fake_cloud.FakeCloud()
    key = "acc_" + secrets.token_urlsafe(24)
    publisher = HttpPublisher("https://cloud.test", key, transport=cloud.transport)
    loop = PublishLoop(outbox, publisher, connectivity, rng=random.Random(0))
    try:
        app = create_app(EdgeSettings(), OnnxInferencer(directory), outbox)
        with TestClient(app) as client:
            assert post_capture(client, edge.token).status_code == 200
        loop.run_once()
    finally:
        outbox.close()

    [request] = cloud.batch_requests
    assert b"/9j/" not in request.content
    [inspection] = json.loads(request.content)["items"]
    assert inspection["source"] == "simulated"
    assert inspection["model_version"] == PROVISIONAL
    assert set(inspection) == CONTRACT_FIELDS


# =========================================================================== importer helpers

T0 = datetime(2026, 10, 22, 14, 15, 3, tzinfo=UTC)
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
MANIFEST_COLUMNS = (
    "image_path",
    "item_id",
    "object_type",
    "grade",
    "labeler",
    "angle",
    "captured_at",
    "capture_device",
    "notes",
)
REGISTRY_HEADER = "source_id,title,url,license,license_url,attribution,retrieved_at"
REGISTRY_LINE = (
    "fonte-teste,Fonte de teste,https://example.org/fonte,CC-BY-4.0,"
    "https://creativecommons.org/licenses/by/4.0/,Fonte de teste (example.org),2026-10-20"
)
GIT_MESSAGE = "provisional set must be outside any git repository"
INBOX_MESSAGE = "inbox must be outside any git repository"
NOT_A_SET = "dataset is not a provisional set"


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def plan_row(file: str, item_id: str = "XS-0001", **changes: str) -> list[str]:
    row = {
        "file": file,
        "item_id": item_id,
        "object_type": "screw",
        "grade": "perfect",
        "labeler": AGENT,
        "angle": "0",
        "origin": "external",
        "contributor": "",
        "source_id": "fonte-teste",
        "source_ref": f"dataset/{file}",
        "notes": "",
    }
    row.update(changes)
    return [row[c] for c in PLAN_COLUMNS]


@dataclass
class Imports:
    tmp: Path
    capsys: pytest.CaptureFixture[str]
    dataset: Path
    inbox: Path
    plan: Path
    registry: Path
    clock: Clock = field(default_factory=Clock)

    def put(self, name: str, seed: int = 1) -> str:
        self.inbox.mkdir(parents=True, exist_ok=True)
        (self.inbox / name).write_bytes(synthetic_jpeg(800, 600, seed))
        return name

    def write_plan(self, rows: Sequence[Sequence[str]]) -> None:
        self.plan.parent.mkdir(parents=True, exist_ok=True)
        with self.plan.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(PLAN_COLUMNS)
            writer.writerows(rows)

    def run(self, *extra: str, privacy: bool = True) -> types.SimpleNamespace:
        args = [
            "--dataset-dir",
            str(self.dataset),
            "--inbox",
            str(self.inbox),
            "--plan",
            str(self.plan),
            "--external-sources",
            str(self.registry),
            *(("--privacy-checked",) if privacy else ()),
            *extra,
        ]
        self.capsys.readouterr()
        try:
            code = qc_edge.importer.main(args, clock=self.clock, sleep=lambda s: None)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        out = self.capsys.readouterr()
        return types.SimpleNamespace(code=code, out=out.out, err=out.err)

    def manifest_rows(self) -> list[dict[str, str]]:
        with (self.dataset / "manifest.csv").open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def sources_rows(self) -> list[dict[str, str]]:
        with (self.dataset / "sources.csv").open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def snapshot(self) -> dict[str, bytes | None]:
        if not self.dataset.exists():
            return {}
        return {
            str(p.relative_to(self.dataset)): (None if p.is_dir() else p.read_bytes())
            for p in sorted(self.dataset.rglob("*"))
        }

    def seed_manifest(self, *labelers: str) -> None:
        """A dataset with one real image per labeler."""
        self.dataset.mkdir(parents=True, exist_ok=True)
        with (self.dataset / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(MANIFEST_COLUMNS)
            for n, labeler in enumerate(labelers):
                image = f"raw/screw/perfect/XS-09{n:02d}__0__20261020T1000{n:02d}Z.jpg"
                path = self.dataset / image
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(synthetic_jpeg(320, 240, 50 + n))
                writer.writerow(
                    [
                        image,
                        f"XS-09{n:02d}",
                        "screw",
                        "perfect",
                        labeler,
                        "0",
                        f"2026-10-20T10:00:{n:02d}Z",
                        "qc-edge-import",
                        "",
                    ]
                )


@pytest.fixture
def imports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> Imports:
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)  # a relative write would land in tmp_path, never in the repository
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    registry = tmp_path / "registro" / "external_sources.csv"
    registry.parent.mkdir()
    registry.write_text(REGISTRY_HEADER + "\n" + REGISTRY_LINE + "\n", encoding="utf-8")
    return Imports(
        tmp=tmp_path,
        capsys=capsys,
        dataset=tmp_path / "D",
        inbox=tmp_path / "entrada",
        plan=tmp_path / "plano.csv",
        registry=registry,
    )


def git_init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    return path


# =========================================================================== CA-26


def test_ca26_constants_are_the_same_and_outside_the_collect_mode() -> None:
    ml_data = pytest.importorskip("qc_ml.data")
    assert qc_edge.importer.AGENT_SUGGESTION_LABELER == AGENT
    assert ml_data.AGENT_SUGGESTION_LABELER == AGENT
    assert AGENT not in qc_edge.collect.LABELERS
    assert set(qc_edge.collect.LABELERS) == {"a", "b"}


@pytest.mark.parametrize("labeler", [AGENT, "Agent-Suggestion", ""])
def test_ca26_collect_mode_refuses_the_suggestion(edge: EdgeEnv, labeler: str) -> None:
    app = create_app(EdgeSettings(), None, InMemorySink())
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/capture",
            headers={SESSION_HEADER: edge.token},
            data={
                "mode": "collect",
                "item_id": "S-012",
                "object_type": "screw",
                "grade": "fair",
                "labeler": labeler,
                "angle": "2",
                "notes": "",
            },
            files={"image": ("foto.jpg", synthetic_jpeg(), "image/jpeg")},
        )
    assert response.status_code == 422, response.text
    assert not edge.dataset.exists() or not [p for p in edge.dataset.rglob("*") if p.is_file()]
    captures = edge.data_dir / "captures"
    assert not captures.exists() or not [p for p in captures.rglob("*") if p.is_file()]


# =========================================================================== CA-27


def test_ca27_without_the_option_the_labeler_is_invalid(imports: Imports) -> None:
    imports.write_plan([plan_row(imports.put("a.jpg"))])

    r = imports.run()

    assert r.code == 2, r.out + r.err
    assert "invalid_labeler" in r.err
    assert imports.snapshot() == {}


def test_extra_without_the_option_a_git_dataset_stays_accepted(imports: Imports) -> None:
    imports.dataset = git_init(imports.tmp / "repo") / "ml" / "data"
    imports.write_plan([plan_row(imports.put("a.jpg"), labeler="a")])

    r = imports.run()

    assert r.code == 0, r.out + r.err
    assert GIT_MESSAGE not in r.err


# =========================================================================== CA-28


@pytest.mark.parametrize("inputs", ["outside", "inside"])
@pytest.mark.parametrize("target", ["ml/data", ".", "existing"])
def test_ca28_dataset_inside_a_repository_is_the_first_refusal(
    imports: Imports, inputs: str, target: str
) -> None:
    repo = git_init(imports.tmp / "repo")
    if target == "existing":
        (repo / target).mkdir()
    imports.dataset = repo / target
    if inputs == "inside":
        imports.inbox = repo / "entrada"
        imports.plan = repo / "plano.csv"
    imports.write_plan([plan_row(imports.put("a.jpg"))])
    before = sorted(p for p in repo.rglob("*") if ".git" not in p.parts)

    r = imports.run("--provisional-set")

    assert r.code == 2, r.out + r.err
    assert GIT_MESSAGE in r.err
    assert INBOX_MESSAGE not in r.err
    assert not (repo / "ml").exists()
    assert sorted(p for p in repo.rglob("*") if ".git" not in p.parts) == before


def test_extra_dataset_symlink_into_a_repository_is_refused(imports: Imports) -> None:
    repo = git_init(imports.tmp / "repo")
    (repo / "data").mkdir()
    link = imports.tmp / "link"
    link.symlink_to(repo / "data")
    imports.dataset = link
    imports.write_plan([plan_row(imports.put("a.jpg"))])

    r = imports.run("--provisional-set")

    assert r.code == 2, r.out + r.err
    assert GIT_MESSAGE in r.err
    assert list((repo / "data").iterdir()) == []


def test_extra_git_file_of_a_worktree_counts_as_a_repository(imports: Imports) -> None:
    repo = imports.tmp / "worktree"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: /nowhere\n", encoding="utf-8")
    imports.dataset = repo / "data"
    imports.write_plan([plan_row(imports.put("a.jpg"))])

    r = imports.run("--provisional-set")

    assert r.code == 2, r.out + r.err
    assert GIT_MESSAGE in r.err
    assert not imports.dataset.exists()


def test_extra_missing_inbox_comes_after_the_dataset_check(imports: Imports) -> None:
    repo = git_init(imports.tmp / "repo")
    imports.dataset = repo / "ml" / "data"
    imports.inbox = imports.tmp / "does-not-exist"

    r = imports.run("--provisional-set")

    assert r.code == 2, r.out + r.err
    assert GIT_MESSAGE in r.err


def test_extra_privacy_option_is_still_required(imports: Imports) -> None:
    imports.write_plan([plan_row(imports.put("a.jpg"))])

    r = imports.run("--provisional-set", privacy=False)

    assert r.code == 2, r.out + r.err
    assert "privacy" in r.err
    assert imports.snapshot() == {}


# =========================================================================== CA-29


def test_ca29_valid_plan_is_imported_and_a_second_run_adds_to_it(imports: Imports) -> None:
    imports.write_plan(
        [
            plan_row(imports.put("a.jpg", 1), "XS-0001"),
            plan_row(imports.put("b.jpg", 2), "XS-0002", grade="good"),
        ]
    )

    first = imports.run("--provisional-set")

    assert first.code == 0, first.out + first.err
    assert len(imports.manifest_rows()) == 2
    assert {r["labeler"] for r in imports.manifest_rows()} == {AGENT}
    assert {r["origin"] for r in imports.sources_rows()} == {"external"}

    imports.write_plan(
        [
            plan_row(imports.put("c.jpg", 3), "XN-0001", object_type="nut", grade="fair"),
            plan_row(imports.put("d.jpg", 4), "XO-0001", object_type="other", grade=""),
        ]
    )

    second = imports.run("--provisional-set")

    assert second.code == 0, second.out + second.err
    assert len(imports.manifest_rows()) == 4
    assert {r["labeler"] for r in imports.manifest_rows()} == {AGENT}
    assert len(imports.sources_rows()) == 4
    assert {r["origin"] for r in imports.sources_rows()} == {"external"}


def test_extra_header_only_manifest_is_a_provisional_set(imports: Imports) -> None:
    imports.seed_manifest()
    imports.write_plan([plan_row(imports.put("a.jpg"))])

    r = imports.run("--provisional-set")

    assert r.code == 0, r.out + r.err


def test_extra_repeating_the_plan_is_idempotent(imports: Imports) -> None:
    imports.write_plan([plan_row(imports.put("a.jpg"))])
    assert imports.run("--provisional-set").code == 0
    before = imports.snapshot()

    r = imports.run("--provisional-set")

    assert r.code == 0, r.out + r.err
    assert imports.snapshot() == before


def test_extra_dry_run_writes_nothing(imports: Imports) -> None:
    imports.write_plan([plan_row(imports.put("a.jpg"))])

    r = imports.run("--provisional-set", "--dry-run")

    assert r.code == 0, r.out + r.err
    assert imports.snapshot() == {}


def _whole_plan(imports: Imports) -> None:
    rows = []
    n = 0
    for object_type, letter in (("screw", "S"), ("nut", "N")):
        for grade in ("perfect", "good", "fair", "poor", "unusable"):
            n += 1
            name = imports.put(f"{n}.jpg", n)
            rows.append(plan_row(name, f"X{letter}-{n:04d}", object_type=object_type, grade=grade))
    n += 1
    rows.append(plan_row(imports.put(f"{n}.jpg", n), f"XO-{n:04d}", object_type="other", grade=""))
    imports.write_plan(rows)


def test_extra_imported_set_is_accepted_only_by_the_provisional_path(imports: Imports) -> None:
    ml_data = pytest.importorskip("qc_ml.data")
    errors = pytest.importorskip("qc_ml.errors")
    _whole_plan(imports)
    assert imports.run("--provisional-set").code == 0

    with pytest.raises(errors.ManifestError) as raised:
        ml_data.load_manifest(imports.dataset, external_sources=imports.registry)
    assert {p.code for p in raised.value.problems} == {"agent_suggestion_label"}
    assert len(raised.value.problems) == 11

    frame = ml_data.load_manifest(
        imports.dataset, external_sources=imports.registry, allow_agent_suggestion=True
    )
    assert len(frame) == 11


def test_extra_imported_set_reaches_the_training_of_the_provisional_cli(imports: Imports) -> None:
    pytest.importorskip("qc_ml.provisional")
    _whole_plan(imports)
    assert imports.run("--provisional-set").code == 0
    models = imports.tmp / "models"
    code = (
        "import sys\n"
        "sys.modules['torch'] = None\n"
        "import qc_ml.provisional\n"
        "sys.exit(qc_ml.provisional.main(sys.argv[1:]))\n"
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            "--dataset-dir",
            str(imports.dataset),
            "--models-root",
            str(models),
            "--external-sources",
            str(imports.registry),
            "--smoke",
        ],
        capture_output=True,
        text=True,
        cwd=imports.tmp,
        timeout=300,
        check=False,
    )

    assert proc.returncode == 2
    assert "training needs the train extra" in proc.stderr
    assert not models.exists()


def test_extra_imported_set_passes_the_privacy_check(imports: Imports) -> None:
    privacy = pytest.importorskip("qc_edge.privacy")
    _whole_plan(imports)
    assert imports.run("--provisional-set").code == 0
    imports.capsys.readouterr()

    code = privacy.main(["--dataset-dir", str(imports.dataset)])

    assert code == 0
    assert "0 with private data" in imports.capsys.readouterr().out


# =========================================================================== CA-30


@pytest.mark.parametrize("state", ["absent", "existing-set"])
def test_ca30_another_labeler_in_the_plan(imports: Imports, state: str) -> None:
    if state == "existing-set":
        imports.seed_manifest(AGENT)
    good = plan_row(imports.put("a.jpg", 1), "XS-0001")
    bad = plan_row(imports.put("b.jpg", 2), "XS-0002", labeler="a")
    imports.write_plan([good, bad])
    before = imports.snapshot()

    r = imports.run("--provisional-set")

    assert r.code == 2, r.out + r.err
    assert "invalid_labeler" in r.err
    assert imports.snapshot() == before


@pytest.mark.parametrize("state", ["absent", "existing-set"])
def test_ca30_another_origin_in_the_plan(imports: Imports, state: str) -> None:
    if state == "existing-set":
        imports.seed_manifest(AGENT)
    good = plan_row(imports.put("a.jpg", 1), "XS-0001")
    bad = plan_row(
        imports.put("b.jpg", 2),
        "S-501",
        origin="contributor",
        contributor="c01",
        source_id="",
        source_ref="",
    )
    imports.write_plan([good, bad])
    before = imports.snapshot()

    r = imports.run("--provisional-set")

    assert r.code == 2, r.out + r.err
    assert "invalid_origin" in r.err
    assert imports.snapshot() == before


@pytest.mark.parametrize("labelers", [("a",), (AGENT, "a"), (AGENT, "b", AGENT), ("",)])
def test_ca30_manifest_of_another_labeler(imports: Imports, labelers: tuple[str, ...]) -> None:
    imports.seed_manifest(*labelers)
    imports.write_plan([plan_row(imports.put("a.jpg"))])
    before = imports.snapshot()

    r = imports.run("--provisional-set")

    assert r.code == 2, r.out + r.err
    assert NOT_A_SET in r.err
    assert imports.snapshot() == before


@pytest.mark.parametrize("value", ["Agent-Suggestion", "agent_suggestion", " agent-suggestion", ""])
def test_extra_near_values_are_invalid_with_the_option(imports: Imports, value: str) -> None:
    imports.write_plan([plan_row(imports.put("a.jpg"), labeler=value)])

    r = imports.run("--provisional-set")

    assert r.code == 2, r.out + r.err
    assert "invalid_labeler" in r.err
    assert imports.snapshot() == {}


def test_extra_own_item_with_external_origin_is_refused(imports: Imports) -> None:
    imports.write_plan([plan_row(imports.put("a.jpg"), "S-001")])

    r = imports.run("--provisional-set")

    assert r.code == 2, r.out + r.err
    assert imports.snapshot() == {}
