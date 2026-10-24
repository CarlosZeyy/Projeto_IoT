"""Hand tools of phase 2 on the edge (SPEC-016 section 4.4, ADR-021).

* ``labels.json`` may carry ``ungraded_object_types`` (default ``[]``), validated at load time.
* ``decide``: a decided type listed there has no grade, and ``needs_review`` depends only on the
  type confidence.
* The capture answers ``approved = null`` and ``verdict = "sem grau"`` for a tool without a
  grade, and the outbox stores a payload that ``InspectionCreate`` accepts.
* The collect page offers the 5 tools; the console shows ``sem grau`` and the tool rows.
"""

from __future__ import annotations

import json
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from qc_contracts import Grade, InspectionCreate, ObjectType
from qc_edge import netinfo
from qc_edge.app import DATASET_OBJECT_TYPE_LABELS_PT, VERDICT_UNGRADED, create_app
from qc_edge.config import EdgeSettings
from qc_edge.decision import ModelLabels, Thresholds, decide
from qc_edge.inference import InferenceResult, StubInferencer
from qc_edge.onnx_inferencer import ModelLoadError, OnnxInferencer
from qc_edge.outbox import SqliteOutbox
from qc_edge.sink import InMemorySink

GRADES = ("perfect", "good", "fair", "poor", "unusable")
TOOLS = ("pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver")
MODEL_TYPES = ("screw", "nut", "other", "pliers")
THRESHOLDS = Thresholds(type_threshold=0.5, unusable_threshold=0.4, grade_review_threshold=0.6)
GOOD = [0.05, 0.8, 0.05, 0.05, 0.05]
LOCAL = ("127.0.0.1", 50000)
CONSOLE_URL = "http://127.0.0.1:8000"


def _labels(ungraded: tuple[str, ...] = ("pliers",)) -> ModelLabels:
    return ModelLabels(object_types=MODEL_TYPES, grades=GRADES, ungraded_object_types=ungraded)


def _write_labels(directory: Path, labels: dict[str, Any]) -> None:
    (directory / "labels.json").write_text(json.dumps(labels), encoding="utf-8")


def _model_dir(dummy_model: types.ModuleType, root: Path, labels: dict[str, Any]) -> Path:
    directory = dummy_model.write_model_dir(
        root, type_probs=[0.05, 0.03, 0.02, 0.90], object_types=MODEL_TYPES
    )
    _write_labels(directory, labels)
    return directory


# ------------------------------------------------------------------------------- labels.json


@pytest.mark.parametrize(
    "ungraded",
    [None, [], ["pliers"]],
    ids=["absent", "empty", "pliers"],
)
def test_labels_with_valid_ungraded_types_load(
    tmp_path: Path, dummy_model: types.ModuleType, ungraded: list[str] | None
) -> None:
    labels: dict[str, Any] = {"object_types": list(MODEL_TYPES), "grades": list(GRADES)}
    if ungraded is not None:
        labels["ungraded_object_types"] = ungraded
    inferencer = OnnxInferencer(_model_dir(dummy_model, tmp_path, labels))
    assert inferencer.labels.object_types == MODEL_TYPES
    assert inferencer.labels.ungraded_object_types == tuple(ungraded or ())


@pytest.mark.parametrize(
    "ungraded",
    [
        ["screw"],
        ["nut"],
        ["other"],
        ["allen_key"],  # a tool that is not one of object_types
        ["pliers", "pliers"],
        "pliers",
        ["pliers", 1],
        [None],
        {"pliers": True},
        ["unknown"],
        ["Pliers"],
        None,
    ],
    ids=repr,
)
def test_labels_with_invalid_ungraded_types_are_refused(
    tmp_path: Path, dummy_model: types.ModuleType, ungraded: Any
) -> None:
    labels = {
        "object_types": list(MODEL_TYPES),
        "grades": list(GRADES),
        "ungraded_object_types": ungraded,
    }
    with pytest.raises(ModelLoadError) as info:
        OnnxInferencer(_model_dir(dummy_model, tmp_path, labels))
    message = str(info.value)
    assert message.startswith("labels.json: ungraded_object_types")
    assert "Pliers" not in message  # the message never echoes the value


def test_labels_ungraded_with_every_tool(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    object_types = ["screw", "nut", "other", *TOOLS]
    directory = dummy_model.write_model_dir(
        tmp_path,
        type_probs=[1.0 / 8] * 8,
        object_types=object_types,
        ungraded_object_types=["allen_key", "pliers"],
    )
    inferencer = OnnxInferencer(directory)
    assert inferencer.labels.object_types == tuple(object_types)
    assert inferencer.labels.ungraded_object_types == ("allen_key", "pliers")


def test_labels_unknown_key_is_still_refused(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    labels = {"object_types": list(MODEL_TYPES), "grades": list(GRADES), "graded": []}
    with pytest.raises(ModelLoadError, match=r"unknown keys \['graded'\]"):
        OnnxInferencer(_model_dir(dummy_model, tmp_path, labels))


def test_labels_hammer_is_still_outside_the_contract(
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    labels = {"object_types": ["screw", "hammer", "other"], "grades": list(GRADES)}
    directory = dummy_model.write_model_dir(
        tmp_path, type_probs=[0.4, 0.3, 0.3], object_types=("screw", "nut", "other")
    )
    _write_labels(directory, labels)
    with pytest.raises(ModelLoadError, match=r"labels\.json: object_types may only contain"):
        OnnxInferencer(directory)


def test_model_labels_store_tuples() -> None:
    labels = ModelLabels(
        object_types=["screw", "pliers"],  # type: ignore[arg-type]
        grades=list(GRADES),  # type: ignore[arg-type]
        ungraded_object_types=["pliers"],  # type: ignore[arg-type]
    )
    assert labels.object_types == ("screw", "pliers")
    assert labels.grades == GRADES
    assert labels.ungraded_object_types == ("pliers",)
    assert ModelLabels(("screw",), GRADES).ungraded_object_types == ()


# ------------------------------------------------------------------------------------ decision


def test_ungraded_tool_has_no_grade_and_no_review() -> None:
    decision = decide([0.05, 0.03, 0.02, 0.90], GOOD, _labels(), THRESHOLDS)
    assert decision.object_type is ObjectType.PLIERS
    assert decision.grade is None
    assert decision.grade_score is None
    assert decision.grade_confidence is None
    assert decision.type_confidence == pytest.approx(0.90)
    assert decision.needs_review is False


def test_ungraded_tool_with_low_margin_needs_review() -> None:
    decision = decide([0.2, 0.1, 0.15, 0.55], GOOD, _labels(), THRESHOLDS)
    assert decision.object_type is ObjectType.PLIERS
    assert decision.grade is None
    assert decision.needs_review is True  # 0.55 < 0.5 + 0.10


def test_ungraded_tool_ignores_a_low_grade_confidence() -> None:
    flat = [0.2, 0.2, 0.2, 0.2, 0.2]  # grade_confidence 0.2 < 0.6 would ask for review
    assert decide([0.0, 0.0, 0.0, 1.0], flat, _labels(), THRESHOLDS).needs_review is False
    graded = decide([0.0, 0.0, 0.0, 1.0], flat, _labels(()), THRESHOLDS)
    assert graded.grade is Grade.PERFECT and graded.needs_review is True


def test_graded_tool_follows_the_grade_rule() -> None:
    decision = decide([0.05, 0.03, 0.02, 0.90], GOOD, _labels(()), THRESHOLDS)
    assert decision.object_type is ObjectType.PLIERS
    assert decision.grade is Grade.GOOD
    assert decision.grade_confidence == pytest.approx(0.8)
    unusable = decide([0.05, 0.03, 0.02, 0.90], [0.1, 0.1, 0.1, 0.2, 0.5], _labels(()), THRESHOLDS)
    assert unusable.grade is Grade.UNUSABLE


def test_ungraded_tool_below_the_threshold_is_unknown() -> None:
    decision = decide([0.2, 0.2, 0.15, 0.45], GOOD, _labels(), THRESHOLDS)
    assert decision.object_type is ObjectType.UNKNOWN
    assert decision.grade is None and decision.needs_review is True


def test_other_stays_unknown_with_ungraded_tools() -> None:
    decision = decide([0.02, 0.03, 0.9, 0.05], GOOD, _labels(), THRESHOLDS)
    assert decision.object_type is ObjectType.UNKNOWN


def test_screw_is_still_graded_next_to_an_ungraded_tool() -> None:
    decision = decide([0.9, 0.03, 0.02, 0.05], GOOD, _labels(), THRESHOLDS)
    assert decision.object_type is ObjectType.SCREW and decision.grade is Grade.GOOD


@pytest.mark.parametrize("ungraded", [(), ("pliers",)])
def test_decisions_are_valid_contract_payloads(ungraded: tuple[str, ...]) -> None:
    decision = decide([0.05, 0.03, 0.02, 0.90], GOOD, _labels(ungraded), THRESHOLDS)
    InspectionCreate(
        inspection_id="3f1c2b4e-8d7a-4c5b-9e6f-1a2b3c4d5e6f",
        device_id="edge-01",
        lot_id="L-001",
        inspected_at="2026-10-01T12:00:00Z",
        object_type=decision.object_type,
        grade=decision.grade,
        grade_score=decision.grade_score,
        type_confidence=decision.type_confidence,
        grade_confidence=decision.grade_confidence,
        needs_review=decision.needs_review,
        model_version="dummy-v1",
        model_sha256="a" * 64,
        latency_ms=10,
        source="live",
    )


# ----------------------------------------------------------------------------- capture route


def _post_inspect(client: TestClient, token: str, image: bytes) -> Any:
    return client.post(
        "/api/capture",
        headers={"X-Session-Token": token},
        data={"lot_id": "L-001", "mode": "inspect"},
        files={"image": ("a.jpg", image, "image/jpeg")},
    )


def test_capture_of_an_ungraded_tool_goes_to_the_outbox(
    tmp_path: Path, dummy_model: types.ModuleType, settings: EdgeSettings, jpeg_bytes: bytes
) -> None:
    directory = dummy_model.write_model_dir(
        tmp_path / "models",
        type_probs=[0.05, 0.03, 0.02, 0.90],
        object_types=MODEL_TYPES,
        ungraded_object_types=["pliers"],
    )
    outbox = SqliteOutbox(tmp_path / "outbox.sqlite")
    try:
        app = create_app(settings, OnnxInferencer(directory), outbox)
        with TestClient(app) as client:
            response = _post_inspect(client, app.state.session_token, jpeg_bytes)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["approved"] is None
        assert body["labels_pt"] == {"object_type": "alicate", "grade": None, "verdict": "sem grau"}
        assert body["inspection"]["object_type"] == "pliers"
        assert body["inspection"]["grade"] is None
        (item,) = outbox.fetch_due(10)
        stored = item.to_inspection()
        assert InspectionCreate.model_validate(stored.model_dump(mode="json")) == stored
        assert stored.object_type is ObjectType.PLIERS
        assert stored.grade is None and stored.grade_score is None
        assert stored.grade_confidence is None
        assert stored.needs_review is False
    finally:
        outbox.close()


@pytest.mark.parametrize(
    ("object_type", "grade", "approved", "labels"),
    [
        (ObjectType.PLIERS, None, None, ("alicate", None, "sem grau")),
        (ObjectType.ALLEN_KEY, None, None, ("chave Allen", None, "sem grau")),
        (ObjectType.FLAT_SCREWDRIVER, Grade.GOOD, True, ("chave de fenda", "bom", "aprovada")),
        (
            ObjectType.PHILLIPS_SCREWDRIVER,
            Grade.POOR,
            False,
            ("chave Phillips", "ruim", "reprovada"),
        ),
        (ObjectType.UNKNOWN, None, None, ("desconhecido", None, "desconhecido")),
    ],
)
def test_tool_verdicts(
    settings: EdgeSettings,
    jpeg_bytes: bytes,
    object_type: ObjectType,
    grade: Grade | None,
    approved: bool | None,
    labels: tuple[str, str | None, str],
) -> None:
    graded = grade is not None
    result = InferenceResult(
        object_type=object_type,
        grade=grade,
        grade_score=3.0 if graded else None,
        type_confidence=0.9,
        grade_confidence=0.7 if graded else None,
        needs_review=False,
        latency_ms=12,
    )
    app = create_app(settings, StubInferencer(result), InMemorySink())
    body = _post_inspect(TestClient(app), app.state.session_token, jpeg_bytes).json()
    assert body["approved"] is approved
    assert body["labels_pt"] == dict(zip(("object_type", "grade", "verdict"), labels, strict=True))


def test_console_row_of_an_ungraded_tool(
    settings: EdgeSettings, jpeg_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])
    result = InferenceResult(
        object_type=ObjectType.PLIERS,
        grade=None,
        grade_score=None,
        type_confidence=0.9,
        grade_confidence=None,
        needs_review=False,
        latency_ms=12,
    )
    app = create_app(settings, StubInferencer(result), InMemorySink())
    assert _post_inspect(TestClient(app), app.state.session_token, jpeg_bytes).status_code == 200
    page = TestClient(app, client=LOCAL, base_url=CONSOLE_URL).get("/").text
    assert f"<td>alicate</td><td>{VERDICT_UNGRADED}</td></tr>" in page


# ------------------------------------------------------------------------------- collect page


def test_collect_selector_offers_the_tools(settings: EdgeSettings) -> None:
    app = create_app(settings, None, InMemorySink())
    page = TestClient(app).get("/capture", params={"t": app.state.session_token}).text
    expected = [
        ("screw", "parafuso"),
        ("nut", "porca"),
        ("pliers", "alicate"),
        ("adjustable_wrench", "chave inglesa"),
        ("allen_key", "chave Allen"),
        ("flat_screwdriver", "chave de fenda"),
        ("phillips_screwdriver", "chave Phillips"),
        ("other", "outro"),
    ]
    positions = [
        page.index(f'<option value="{value}">{label}</option>') for value, label in expected
    ]
    assert positions == sorted(positions)
    assert [(t.value, label) for t, label in DATASET_OBJECT_TYPE_LABELS_PT.items()] == expected


def test_collect_of_a_tool_through_the_route(settings: EdgeSettings, jpeg_bytes: bytes) -> None:
    app = create_app(settings, None, InMemorySink())
    client = TestClient(app)
    fields = {
        "mode": "collect",
        "item_id": "T-001",
        "object_type": "pliers",
        "grade": "good",
        "labeler": "a",
        "angle": "0",
    }

    def post(**changes: str) -> Any:
        return client.post(
            "/api/capture",
            headers={"X-Session-Token": app.state.session_token},
            data=fields | changes,
            files={"image": ("a.jpg", jpeg_bytes, "image/jpeg")},
        )

    for changes in (
        {"object_type": "screw"},
        {"item_id": "T-002", "object_type": "allen_key", "grade": ""},
        {"item_id": "S-001"},
    ):
        response = post(**changes)
        assert response.status_code == 422, changes
    assert not settings.DATASET_DIR.exists()
    response = post()
    assert response.status_code == 200, response.text
    assert response.json()["image_path"].startswith("raw/pliers/good/T-001__0__")
    manifest = (settings.DATASET_DIR / "manifest.csv").read_text(encoding="utf-8").splitlines()
    assert len(manifest) == 2 and manifest[1].split(",")[1:4] == ["T-001", "pliers", "good"]
