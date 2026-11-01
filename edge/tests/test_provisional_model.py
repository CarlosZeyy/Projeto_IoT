"""A provisional model on the edge (SPEC-041 section 4.7, ADR-024, R-06).

The name of the model decides: ``source=simulated``, the verdict suffix, the console notice and
the startup warning. The models are the dummy ONNX of SPEC-008, with the real outbox in
``tmp_path``; only the verdict table uses a fake inferencer, to reach every verdict.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from qc_contracts import Grade, InspectionCreate, ObjectType
from qc_edge import cli, netinfo
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import (
    InferenceResult,
    ModelInfo,
    StubInferencer,
    is_provisional_version,
)
from qc_edge.onnx_inferencer import OnnxInferencer
from qc_edge.outbox import SqliteOutbox
from qc_edge.sink import InMemorySink

PROVISIONAL = "partqc-mnv3-provisional-v1"
OFFICIAL = "partqc-mnv3-v1"
SUFFIX = " (modelo provisório)"
LOCAL = ("127.0.0.1", 50000)
CONSOLE_URL = "http://127.0.0.1:8000"
STARTUP_WARNING = "provisional model loaded: results are published as source=simulated (ADR-024)"
CONSOLE_NOTICE = " — PROVISÓRIO: resultados publicados como simulados (ADR-024)"
RESPONSE_KEYS = {"inspection", "labels_pt", "approved"}
LABELS_KEYS = {"object_type", "grade", "verdict"}


class _FixedInferencer:
    """Any ``model_version`` with any result, to reach the verdicts of ``_verdict``."""

    def __init__(self, model_version: str, result: InferenceResult) -> None:
        self.model_info = ModelInfo(model_version, "a" * 64)
        self._result = result

    def infer(self, image: Image.Image) -> InferenceResult:
        return self._result


def _result(object_type: ObjectType, grade: Grade | None) -> InferenceResult:
    graded = grade is not None
    return InferenceResult(
        object_type=object_type,
        grade=grade,
        grade_score=1.0 if graded else None,
        type_confidence=0.9,
        grade_confidence=0.8 if graded else None,
        needs_review=False,
        latency_ms=1,
    )


def _capture(app: Any, image: bytes) -> Any:
    client = TestClient(app)
    return client.post(
        "/api/capture",
        headers={"X-Session-Token": app.state.session_token},
        data={"lot_id": "ENSAIO-1", "mode": "inspect"},
        files={"image": ("a.jpg", image, "image/jpeg")},
    )


def _outbox_payloads(path: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT payload FROM outbox ORDER BY rowid").fetchall()
    finally:
        connection.close()
    return [json.loads(row[0]) for row in rows]


@pytest.fixture
def outbox(tmp_path: Path) -> Iterator[SqliteOutbox]:
    box = SqliteOutbox(tmp_path / "edge" / "outbox.sqlite3")
    yield box
    box.close()


@pytest.fixture
def lan_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])


# ------------------------------------------------------------------------------ the name decides


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        (PROVISIONAL, True),
        ("partqc-provisional-v1", True),
        (OFFICIAL, False),
        ("partqc-mnv3-corn-v2", False),
        ("stub-v0", False),
        # Only the whole marker counts: no hyphen on one of the sides is not provisional.
        ("provisional", False),
        ("provisional-v1", False),
        ("partqc-provisional", False),
        ("partqc-provisionalv1", False),
    ],
)
def test_is_provisional_version(version: str, expected: bool) -> None:
    assert is_provisional_version(version) is expected


# ------------------------------------------------------------------------- capture, with the ONNX


def test_provisional_model_is_simulated_in_the_answer_and_in_the_outbox(
    settings: EdgeSettings,
    outbox: SqliteOutbox,
    tmp_path: Path,
    dummy_model: types.ModuleType,
    make_image: Any,
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models", PROVISIONAL)
    app = create_app(settings, OnnxInferencer(directory), outbox)

    response = _capture(app, make_image((640, 480)))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESPONSE_KEYS
    assert set(body["labels_pt"]) == LABELS_KEYS
    assert body["inspection"]["source"] == "simulated"
    assert body["inspection"]["model_version"] == PROVISIONAL
    assert body["labels_pt"]["verdict"] == f"aprovada{SUFFIX}"
    assert body["approved"] is True
    [payload] = _outbox_payloads(outbox.path)
    assert payload["source"] == "simulated"
    assert payload["model_version"] == PROVISIONAL


def test_the_published_payload_is_only_the_contract(
    settings: EdgeSettings,
    outbox: SqliteOutbox,
    tmp_path: Path,
    dummy_model: types.ModuleType,
    make_image: Any,
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models", PROVISIONAL)
    app = create_app(settings, OnnxInferencer(directory), outbox)

    assert _capture(app, make_image((640, 480))).status_code == 200

    [payload] = _outbox_payloads(outbox.path)
    assert set(payload) == set(InspectionCreate.model_fields)  # no image data (R-02)
    assert InspectionCreate.model_validate(payload).source.value == "simulated"


def test_official_model_stays_live_without_the_suffix(
    settings: EdgeSettings,
    outbox: SqliteOutbox,
    tmp_path: Path,
    dummy_model: types.ModuleType,
    make_image: Any,
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models", OFFICIAL)
    app = create_app(settings, OnnxInferencer(directory), outbox)

    response = _capture(app, make_image((640, 480)))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESPONSE_KEYS
    assert body["inspection"]["source"] == "live"
    assert body["labels_pt"]["verdict"] == "aprovada"
    [payload] = _outbox_payloads(outbox.path)
    assert payload["source"] == "live"


def test_link_with_an_official_name_to_a_provisional_directory_is_simulated(
    settings: EdgeSettings,
    outbox: SqliteOutbox,
    tmp_path: Path,
    dummy_model: types.ModuleType,
    make_image: Any,
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models", PROVISIONAL)
    link = tmp_path / "models" / OFFICIAL
    link.symlink_to(directory, target_is_directory=True)
    app = create_app(settings, OnnxInferencer(link), outbox)

    body = _capture(app, make_image((640, 480))).json()

    assert body["inspection"]["model_version"] == PROVISIONAL
    assert body["inspection"]["source"] == "simulated"


# ------------------------------------------------------------------------------- the verdict cases


@pytest.mark.parametrize(
    ("object_type", "grade", "verdict", "approved"),
    [
        (ObjectType.SCREW, Grade.GOOD, "aprovada", True),
        (ObjectType.NUT, Grade.UNUSABLE, "reprovada", False),
        (ObjectType.UNKNOWN, None, "desconhecido", None),
        (ObjectType.DRILL, None, "sem grau", None),
    ],
)
def test_every_verdict_gets_the_suffix_and_keeps_approved(
    settings: EdgeSettings,
    make_image: Any,
    object_type: ObjectType,
    grade: Grade | None,
    verdict: str,
    approved: bool | None,
) -> None:
    result = _result(object_type, grade)
    sink = InMemorySink()
    provisional = create_app(settings, _FixedInferencer(PROVISIONAL, result), sink)
    official = create_app(settings, _FixedInferencer(OFFICIAL, result), sink)

    with_suffix = _capture(provisional, make_image((640, 480))).json()
    without_suffix = _capture(official, make_image((640, 480))).json()

    assert with_suffix["labels_pt"]["verdict"] == verdict + SUFFIX
    assert with_suffix["approved"] is approved
    assert with_suffix["inspection"]["source"] == "simulated"
    assert without_suffix["labels_pt"]["verdict"] == verdict
    assert without_suffix["approved"] is approved
    assert without_suffix["inspection"]["source"] == "live"
    assert [item.source.value for item in sink.items] == ["simulated", "live"]


def test_stub_model_does_not_change(settings: EdgeSettings, make_image: Any) -> None:
    app = create_app(settings, StubInferencer(), InMemorySink())

    body = _capture(app, make_image((640, 480))).json()

    assert body["inspection"]["source"] == "live"
    assert body["labels_pt"]["verdict"] == "aprovada"


def test_status_does_not_change_with_a_provisional_model(
    settings: EdgeSettings, tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    """``/api/status`` has the same keys for both models and says nothing about provisional."""

    def status_of(name: str) -> dict[str, Any]:
        directory = dummy_model.write_model_dir(tmp_path / "models", name)
        app = create_app(settings, OnnxInferencer(directory), InMemorySink())
        response = TestClient(app).get(
            "/api/status", headers={"X-Session-Token": app.state.session_token}
        )
        assert response.status_code == 200
        return response.json()

    provisional, official = status_of(PROVISIONAL), status_of(OFFICIAL)

    assert set(provisional) == set(official)
    assert set(provisional["model"]) == set(official["model"])
    assert provisional["model"]["model_version"] == PROVISIONAL
    assert provisional["model"]["thresholds"] == official["model"]["thresholds"]


# ------------------------------------------------------------------------------------ the console


def _console(app: Any) -> str:
    response = TestClient(app, base_url=CONSOLE_URL, client=LOCAL).get("/")
    assert response.status_code == 200
    return response.text


@pytest.mark.usefixtures("lan_ips")
def test_console_says_the_model_is_provisional(
    settings: EdgeSettings, tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models", PROVISIONAL)
    app = create_app(settings, OnnxInferencer(directory), InMemorySink())

    page = _console(app)

    assert f"carregado: {PROVISIONAL} (sha256 " in page
    assert CONSOLE_NOTICE in page


@pytest.mark.parametrize("name", [OFFICIAL, "partqc-mnv3-corn-v2"])
@pytest.mark.usefixtures("lan_ips")
def test_console_of_another_model_has_no_notice(
    settings: EdgeSettings, tmp_path: Path, dummy_model: types.ModuleType, name: str
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models", name)
    app = create_app(settings, OnnxInferencer(directory), InMemorySink())

    assert "PROVISÓRIO" not in _console(app)


@pytest.mark.usefixtures("lan_ips")
def test_console_without_a_model_has_no_notice(settings: EdgeSettings) -> None:
    assert "PROVISÓRIO" not in _console(create_app(settings, None, InMemorySink()))


# ---------------------------------------------------------------------------------------- the CLI


class _UvicornSpy:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __call__(self, app: Any, **kwargs: Any) -> None:
        self.calls.append(app)


@pytest.fixture
def uvicorn_spy(monkeypatch: pytest.MonkeyPatch) -> _UvicornSpy:
    spy = _UvicornSpy()
    monkeypatch.setattr(cli.uvicorn, "run", spy)
    return spy


@pytest.fixture
def edge_env(clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATASET_DIR", str(tmp_path / "dataset"))


@pytest.mark.usefixtures("edge_env", "lan_ips")
def test_cli_warns_about_a_provisional_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_spy: _UvicornSpy,
    dummy_model: types.ModuleType,
) -> None:
    monkeypatch.setenv("MODEL_DIR", str(dummy_model.write_model_dir(tmp_path / "m", PROVISIONAL)))

    with caplog.at_level(logging.INFO, logger="qc_edge"):
        cli.main([])

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert STARTUP_WARNING in warnings
    assert "PROVISÓRIO" in _console(uvicorn_spy.calls[0])


@pytest.mark.usefixtures("edge_env", "lan_ips")
def test_cli_does_not_warn_about_an_official_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_spy: _UvicornSpy,
    dummy_model: types.ModuleType,
) -> None:
    monkeypatch.setenv("MODEL_DIR", str(dummy_model.write_model_dir(tmp_path / "m", OFFICIAL)))

    with caplog.at_level(logging.INFO, logger="qc_edge"):
        cli.main([])

    assert "provisional model loaded" not in caplog.text
    assert "PROVISÓRIO" not in _console(uvicorn_spy.calls[0])


@pytest.mark.usefixtures("edge_env")
def test_stub_model_flag_takes_precedence_without_the_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_spy: _UvicornSpy,
    dummy_model: types.ModuleType,
) -> None:
    """``--stub-model`` does not load ``MODEL_DIR``: the model of the run is ``stub-v0``."""
    monkeypatch.setenv("MODEL_DIR", str(dummy_model.write_model_dir(tmp_path / "m", PROVISIONAL)))

    with caplog.at_level(logging.INFO, logger="qc_edge"):
        cli.main(["--stub-model"])

    assert "provisional model loaded" not in caplog.text
    assert len(uvicorn_spy.calls) == 1
