"""``OnnxInferencer`` inside ``qc-edge``: CLI, ``/api/status``, console and capture (SPEC-008
section 4.4)."""

from __future__ import annotations

import logging
import re
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from qc_edge import cli, netinfo
from qc_edge.app import create_app
from qc_edge.config import EdgeSettings
from qc_edge.inference import StubInferencer
from qc_edge.onnx_inferencer import OnnxInferencer
from qc_edge.sink import InMemorySink

LOCAL = ("127.0.0.1", 50000)
CONSOLE_URL = "http://127.0.0.1:8000"


class _UvicornSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, app: Any, **kwargs: Any) -> None:
        self.calls.append((app, kwargs))


@pytest.fixture
def uvicorn_spy(monkeypatch: pytest.MonkeyPatch) -> _UvicornSpy:
    spy = _UvicornSpy()
    monkeypatch.setattr(cli.uvicorn, "run", spy)
    return spy


@pytest.fixture
def edge_env(clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("EDGE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATASET_DIR", str(tmp_path / "dataset"))
    return data_dir


@pytest.fixture
def lan_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])


def _capture(client: TestClient, token: str, image: bytes) -> Any:
    return client.post(
        "/api/capture",
        headers={"X-Session-Token": token},
        data={"lot_id": "L-001", "mode": "inspect"},
        files={"image": ("a.jpg", image, "image/jpeg")},
    )


def _status(app: Any) -> dict[str, Any]:
    response = TestClient(app).get(
        "/api/status", headers={"X-Session-Token": app.state.session_token}
    )
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------- CLI


def test_model_dir_loads_the_onnx_model(
    edge_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_spy: _UvicornSpy,
    dummy_model: types.ModuleType,
    make_image: Any,
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models")
    sha = dummy_model.sha256_of(directory / "model.onnx")
    monkeypatch.setenv("MODEL_DIR", str(directory))
    monkeypatch.setenv("GRADE_REVIEW_THRESHOLD", "0.3")
    with caplog.at_level(logging.INFO, logger="qc_edge"):
        cli.main([])
    ((app, _),) = uvicorn_spy.calls
    assert f"model loaded: model_version=dummy-v1 sha256={sha[:12]}" in caplog.text
    assert "threshold grade_review_threshold=0.3 (source: env)" in caplog.text
    assert "threshold type_threshold=0.5 (source: decision.json)" in caplog.text
    model = _status(app)["model"]
    assert model["loaded"] is True
    assert model["model_version"] == "dummy-v1"
    assert model["model_sha256"] == sha
    assert model["thresholds"] == {
        "type_threshold": {"value": 0.5, "source": "decision.json"},
        "unusable_threshold": {"value": 0.4, "source": "decision.json"},
        "grade_review_threshold": {"value": 0.3, "source": "env"},
    }
    response = _capture(TestClient(app), app.state.session_token, make_image((1280, 960)))
    assert response.status_code == 200
    inspection = response.json()["inspection"]
    assert (inspection["object_type"], inspection["grade"]) == ("screw", "good")
    assert (inspection["model_version"], inspection["model_sha256"]) == ("dummy-v1", sha)
    assert inspection["source"] == "live"


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ({"sha256": "ab" * 32}, "expected abababababab, got "),
        ({"omit": ["decision.json"]}, "decision.json"),
        (
            {
                "decision": {
                    "type_threshold": 1.2,
                    "unusable_threshold": 0.4,
                    "grade_review_threshold": 0.6,
                }
            },
            "decision.json: type_threshold must be a number in [0, 1]",
        ),
        ({"object_types": ("screw", "pliers", "other")}, "labels.json"),
        ({"name": "Not_Valid"}, "MODEL_DIR"),
    ],
)
def test_invalid_model_dir_exits_2(
    edge_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_spy: _UvicornSpy,
    dummy_model: types.ModuleType,
    setup: dict[str, Any],
    expected: str,
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models", **setup)
    monkeypatch.setenv("MODEL_DIR", str(directory))
    with caplog.at_level(logging.INFO, logger="qc_edge"), pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2
    assert "cannot load the model" in caplog.text
    assert expected in caplog.text
    assert uvicorn_spy.calls == []


def test_missing_model_dir_exits_2(
    edge_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_spy: _UvicornSpy,
) -> None:
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "nowhere-v1"))
    with caplog.at_level(logging.INFO, logger="qc_edge"), pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2
    assert "MODEL_DIR: not a directory" in caplog.text
    assert str(tmp_path) not in caplog.text
    assert uvicorn_spy.calls == []


@pytest.mark.parametrize("value", ["1.5", "abc", "-0.1", "nan", "inf"])
@pytest.mark.parametrize("with_model", [True, False])
def test_invalid_threshold_variable_exits_2(
    edge_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_spy: _UvicornSpy,
    dummy_model: types.ModuleType,
    value: str,
    with_model: bool,
) -> None:  # CA-12
    if with_model:
        monkeypatch.setenv("MODEL_DIR", str(dummy_model.write_model_dir(tmp_path / "models")))
    monkeypatch.setenv("TYPE_THRESHOLD", value)
    with caplog.at_level(logging.INFO, logger="qc_edge"), pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2
    assert "TYPE_THRESHOLD" in caplog.text
    assert uvicorn_spy.calls == []


def test_stub_model_takes_precedence(
    edge_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_spy: _UvicornSpy,
    dummy_model: types.ModuleType,
) -> None:
    # Even an invalid directory is not loaded with --stub-model.
    directory = dummy_model.write_model_dir(tmp_path / "models", sha256="ab" * 32)
    monkeypatch.setenv("MODEL_DIR", str(directory))
    with caplog.at_level(logging.INFO, logger="qc_edge"):
        cli.main(["--stub-model"])
    ((app, _),) = uvicorn_spy.calls
    assert "--stub-model takes precedence: MODEL_DIR is not loaded" in caplog.text
    model = _status(app)["model"]
    assert model["model_version"] == "stub-v0"
    assert model["thresholds"] is None


def test_overrides_without_a_model_are_ignored(
    edge_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_spy: _UvicornSpy,
) -> None:
    monkeypatch.setenv("UNUSABLE_THRESHOLD", "0.3")
    monkeypatch.setenv("MODEL_DIR", "")  # empty counts as unset
    with caplog.at_level(logging.INFO, logger="qc_edge"):
        cli.main([])
    ((app, _),) = uvicorn_spy.calls
    assert "no MODEL_DIR: threshold overrides ignored (UNUSABLE_THRESHOLD)" in caplog.text
    assert _status(app)["model"]["loaded"] is False


def test_threshold_overrides_come_from_the_settings(
    clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TYPE_THRESHOLD", "0.55")
    monkeypatch.setenv("GRADE_REVIEW_THRESHOLD", "0")
    settings = EdgeSettings(EDGE_DATA_DIR=tmp_path / "d")
    assert cli._threshold_overrides(settings) == {
        "TYPE_THRESHOLD": 0.55,
        "GRADE_REVIEW_THRESHOLD": 0.0,
    }


# ---------------------------------------------------------------- app


def test_capture_with_invalid_model_output_is_500(
    settings: EdgeSettings,
    tmp_path: Path,
    dummy_model: types.ModuleType,
    make_image: Any,
    files_under: Any,
) -> None:  # CA-14
    directory = dummy_model.write_model_dir(tmp_path / "models", type_probs=(0.5, 0.5, 0.5))
    sink = InMemorySink()
    app = create_app(settings, OnnxInferencer(directory), sink)
    before = files_under()
    response = _capture(TestClient(app), app.state.session_token, make_image((1280, 960)))
    assert response.status_code == 500
    assert response.json() == {"detail": "inference failed"}
    assert sink.items == []
    assert files_under() == before


def test_unknown_result_goes_to_the_sink(
    settings: EdgeSettings, tmp_path: Path, dummy_model: types.ModuleType, make_image: Any
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models", type_probs=(0.1, 0.1, 0.8))
    sink = InMemorySink()
    app = create_app(settings, OnnxInferencer(directory), sink)
    response = _capture(TestClient(app), app.state.session_token, make_image())
    assert response.status_code == 200
    body = response.json()
    assert body["labels_pt"]["verdict"] == "desconhecido"
    (item,) = sink.items
    assert item.object_type.value == "unknown" and item.grade is None
    assert item.model_version == "dummy-v1"


def test_console_shows_the_model_and_the_thresholds(
    settings: EdgeSettings, tmp_path: Path, dummy_model: types.ModuleType, lan_ips: None
) -> None:  # CA-18
    directory = dummy_model.write_model_dir(tmp_path / "models", "partqc-mnv3-v1")
    sha = dummy_model.sha256_of(directory / "model.onnx")
    inferencer = OnnxInferencer(directory, overrides={"UNUSABLE_THRESHOLD": 0.35})
    app = create_app(settings, inferencer, InMemorySink())
    page = TestClient(app, client=LOCAL, base_url=CONSOLE_URL).get("/").text
    assert f"carregado: partqc-mnv3-v1 (sha256 {sha[:12]})" in page
    assert sha not in page  # only the first 12 characters
    items = dict(re.findall(r'<li id="threshold-(\w+)">(.*?)</li>', page))
    assert set(items) == {"type_threshold", "unusable_threshold", "grade_review_threshold"}
    assert "0.5, origem <code>decision.json</code>" in items["type_threshold"]
    assert "0.35, origem <code>env</code>" in items["unusable_threshold"]
    assert "0.6, origem <code>decision.json</code>" in items["grade_review_threshold"]


def test_console_without_thresholds(settings: EdgeSettings, lan_ips: None) -> None:
    for inferencer in (None, StubInferencer()):
        app = create_app(settings, inferencer, InMemorySink())
        page = TestClient(app, client=LOCAL, base_url=CONSOLE_URL).get("/").text
        assert re.search(r'id="model-thresholds">—<', page)
