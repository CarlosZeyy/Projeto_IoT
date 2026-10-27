"""Power tools of phase 3 on the edge (SPEC-021 sections 3.1 and 4, ADR-021).

* ``labels.json``: a power tool present in ``object_types`` must be in ``ungraded_object_types``
  (the load rule of SPEC-016 section 4.4 now applies), so it always comes out without a grade.
* The capture answers ``approved = null`` and ``verdict = "sem grau"``, and the outbox stores a
  payload that ``InspectionCreate`` 0.6.0 accepts.
* Collect mode: ``T-`` with a power tool and an empty grade, stored in ``raw/<type>/_/``; with a
  grade, 422 and nothing written. The console coverage table has one row per power tool.
"""

from __future__ import annotations

import csv
import json
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from qc_contracts import GRADE_FORBIDDEN_OBJECT_TYPES, InspectionCreate, ObjectType
from qc_edge import netinfo
from qc_edge.app import VERDICT_UNGRADED, create_app
from qc_edge.collect import (
    MANIFEST_COLUMNS,
    NO_GRADE_DIR,
    POWER_TOOL_OBJECT_TYPES,
    POWER_TOOL_TARGET_IMAGES,
    POWER_TOOL_TARGET_ITEMS,
    UNGRADED_DATASET_TYPES,
    CollectRequest,
    DatasetObjectType,
    InvalidCollectFieldError,
    compute_coverage,
    item_prefix_matches,
)
from qc_edge.config import EdgeSettings
from qc_edge.decision import ModelLabels, Thresholds, decide
from qc_edge.inference import InferenceResult, StubInferencer
from qc_edge.onnx_inferencer import ModelLoadError, OnnxInferencer
from qc_edge.outbox import SqliteOutbox
from qc_edge.sink import InMemorySink

GRADES = ("perfect", "good", "fair", "poor", "unusable")
POWER_TOOLS = ("angle_grinder", "saw", "drill", "cordless_screwdriver")
POWER_TOOL_LABELS = {
    "angle_grinder": "esmerilhadeira",
    "saw": "serra",
    "drill": "furadeira",
    "cordless_screwdriver": "parafusadeira",
}
MODEL_TYPES = ("screw", "nut", "other", "drill")
THRESHOLDS = Thresholds(type_threshold=0.5, unusable_threshold=0.4, grade_review_threshold=0.6)
GOOD = [0.05, 0.8, 0.05, 0.05, 0.05]
LOCAL = ("127.0.0.1", 50000)
CONSOLE_URL = "http://127.0.0.1:8000"
STATIC_JS = Path(__file__).resolve().parents[1] / "src" / "qc_edge" / "static" / "capture.js"


def _model_dir(
    dummy_model: types.ModuleType,
    root: Path,
    ungraded: Any,
    object_types: tuple[str, ...] = MODEL_TYPES,
) -> Path:
    directory = dummy_model.write_model_dir(
        root,
        type_probs=[0.05, 0.03, 0.02, 0.90] + [0.0] * (len(object_types) - 4),
        object_types=object_types,
    )
    labels: dict[str, Any] = {"object_types": list(object_types), "grades": list(GRADES)}
    if ungraded is not None:
        labels["ungraded_object_types"] = ungraded
    (directory / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    return directory


# ----------------------------------------------------------------------------- collect constants


def test_power_tools_mirror_the_contract() -> None:
    """The power tools of the collect mode are the grade-forbidden types of the contract other
    than ``unknown``, in the order of ``ObjectType``."""
    assert [t.value for t in POWER_TOOL_OBJECT_TYPES] == [
        member.value
        for member in ObjectType
        if member in GRADE_FORBIDDEN_OBJECT_TYPES and member is not ObjectType.UNKNOWN
    ]
    assert [t.value for t in POWER_TOOL_OBJECT_TYPES] == list(POWER_TOOLS)
    assert {t.value for t in UNGRADED_DATASET_TYPES} == {"other", *POWER_TOOLS}
    assert [m.value for m in DatasetObjectType][-4:] == list(POWER_TOOLS)


@pytest.mark.parametrize(
    ("letter", "object_type", "expected"),
    [
        ("T", "drill", True),
        ("T", "angle_grinder", True),
        ("T", "saw", True),
        ("T", "cordless_screwdriver", True),
        ("S", "drill", False),
        ("N", "saw", False),
        ("O", "angle_grinder", False),
        ("T", "pliers", True),
        ("T", "screw", False),
    ],
)
def test_t_prefix_admits_the_power_tools(letter: str, object_type: str, expected: bool) -> None:
    assert item_prefix_matches(letter, object_type) is expected


# ------------------------------------------------------------------------------- labels.json


def test_model_with_a_power_tool_needs_it_in_ungraded(
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    """CA-05 of SPEC-021 (load part)."""
    for index, ungraded in enumerate((None, [])):
        with pytest.raises(ModelLoadError) as info:
            OnnxInferencer(_model_dir(dummy_model, tmp_path / str(index), ungraded))
        assert "must list every grade-forbidden type of object_types" in str(info.value)
        assert "drill" not in str(info.value)  # the message never echoes the value
    inferencer = OnnxInferencer(_model_dir(dummy_model, tmp_path / "ok", ["drill"]))
    assert inferencer.labels.object_types == MODEL_TYPES
    assert inferencer.labels.ungraded_object_types == ("drill",)


def test_model_with_every_power_tool_must_list_all_of_them(
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    object_types = ("screw", "nut", "other", "pliers", *POWER_TOOLS)
    with pytest.raises(ModelLoadError):
        OnnxInferencer(
            _model_dir(dummy_model, tmp_path / "partial", ["saw", "drill", "pliers"], object_types)
        )
    inferencer = OnnxInferencer(
        _model_dir(dummy_model, tmp_path / "all", list(POWER_TOOLS), object_types)
    )
    assert inferencer.labels.ungraded_object_types == POWER_TOOLS


def test_power_tool_outside_object_types_is_refused(
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    with pytest.raises(ModelLoadError, match="may only contain object_types"):
        OnnxInferencer(_model_dir(dummy_model, tmp_path, ["drill", "saw"]))


# ------------------------------------------------------------------------------------ decision


def test_decided_power_tool_has_no_grade() -> None:
    """CA-05 of SPEC-021 (decision part)."""
    labels = ModelLabels(object_types=MODEL_TYPES, grades=GRADES, ungraded_object_types=("drill",))
    decision = decide([0.05, 0.03, 0.02, 0.90], GOOD, labels, THRESHOLDS)
    assert decision.object_type is ObjectType.DRILL
    assert decision.grade is None and decision.grade_score is None
    assert decision.grade_confidence is None
    assert decision.needs_review is False
    low = decide([0.2, 0.1, 0.15, 0.55], GOOD, labels, THRESHOLDS)
    assert low.object_type is ObjectType.DRILL and low.needs_review is True
    below = decide([0.2, 0.2, 0.15, 0.45], GOOD, labels, THRESHOLDS)
    assert below.object_type is ObjectType.UNKNOWN


# ----------------------------------------------------------------------------- capture route


def _post_inspect(client: TestClient, token: str, image: bytes) -> Any:
    return client.post(
        "/api/capture",
        headers={"X-Session-Token": token},
        data={"lot_id": "L-001", "mode": "inspect"},
        files={"image": ("a.jpg", image, "image/jpeg")},
    )


def test_capture_of_a_power_tool_goes_to_the_outbox_without_grade(
    tmp_path: Path, dummy_model: types.ModuleType, settings: EdgeSettings, jpeg_bytes: bytes
) -> None:
    directory = _model_dir(dummy_model, tmp_path / "models", ["drill"])
    outbox = SqliteOutbox(tmp_path / "outbox.sqlite")
    try:
        app = create_app(settings, OnnxInferencer(directory), outbox)
        with TestClient(app) as client:
            response = _post_inspect(client, app.state.session_token, jpeg_bytes)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["approved"] is None
        assert body["labels_pt"] == {
            "object_type": "furadeira",
            "grade": None,
            "verdict": "sem grau",
        }
        (item,) = outbox.fetch_due(10)
        stored = item.to_inspection()
        assert InspectionCreate.model_validate(stored.model_dump(mode="json")) == stored
        assert stored.object_type is ObjectType.DRILL
        assert stored.grade is None and stored.grade_score is None
        assert stored.grade_confidence is None
    finally:
        outbox.close()


@pytest.mark.parametrize("tool", POWER_TOOLS)
def test_power_tool_verdict(settings: EdgeSettings, jpeg_bytes: bytes, tool: str) -> None:
    result = InferenceResult(
        object_type=ObjectType(tool),
        grade=None,
        grade_score=None,
        type_confidence=0.9,
        grade_confidence=None,
        needs_review=False,
        latency_ms=12,
    )
    app = create_app(settings, StubInferencer(result), InMemorySink())
    body = _post_inspect(TestClient(app), app.state.session_token, jpeg_bytes).json()
    assert body["approved"] is None
    assert body["labels_pt"] == {
        "object_type": POWER_TOOL_LABELS[tool],
        "grade": None,
        "verdict": VERDICT_UNGRADED,
    }


def test_console_row_of_a_power_tool(
    settings: EdgeSettings, jpeg_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])
    result = InferenceResult(
        object_type=ObjectType.SAW,
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
    assert f"<td>serra</td><td>{VERDICT_UNGRADED}</td></tr>" in page


# ---------------------------------------------------------------------------------- collect


def _fields(**changes: str) -> dict[str, str]:
    fields = {
        "item_id": "T-010",
        "object_type": "drill",
        "grade": "",
        "labeler": "a",
        "angle": "0",
    }
    fields.update(changes)
    return fields


@pytest.mark.parametrize("tool", POWER_TOOLS)
@pytest.mark.parametrize("grade", [None, ""])
def test_power_tool_with_empty_grade_is_valid(tool: str, grade: str | None) -> None:
    fields: dict[str, object] = dict(_fields(object_type=tool))
    fields["grade"] = grade
    request = CollectRequest.from_fields(fields)
    assert request.object_type == tool and request.grade is None


@pytest.mark.parametrize("tool", POWER_TOOLS)
@pytest.mark.parametrize("grade", [*GRADES, "great"])
def test_power_tool_with_a_grade_is_refused(tool: str, grade: str) -> None:
    with pytest.raises(InvalidCollectFieldError) as info:
        CollectRequest.from_fields(_fields(object_type=tool, grade=grade))
    assert info.value.field == "grade"
    assert info.value.status_code == 422


@pytest.mark.parametrize("item_id", ["S-010", "N-010", "O-010"])
def test_power_tool_needs_the_t_prefix(item_id: str) -> None:
    with pytest.raises(InvalidCollectFieldError) as info:
        CollectRequest.from_fields(_fields(item_id=item_id))
    assert info.value.field == "item_id"


def _post_collect(client: TestClient, token: str, image: bytes, fields: dict[str, str]) -> Any:
    return client.post(
        "/api/capture",
        headers={"X-Session-Token": token},
        data={"mode": "collect", **fields},
        files={"image": ("a.jpg", image, "image/jpeg")},
    )


def test_collect_of_a_power_tool_through_the_route(
    settings: EdgeSettings, jpeg_bytes: bytes
) -> None:
    """CA-06 of SPEC-021."""
    app = create_app(settings, None, InMemorySink())
    client = TestClient(app)
    token = app.state.session_token
    for changes in ({"grade": "good"}, {"item_id": "S-010"}, {"grade": "x"}):
        response = _post_collect(client, token, jpeg_bytes, _fields(**changes))
        assert response.status_code == 422, changes
    assert not settings.DATASET_DIR.exists()

    response = _post_collect(client, token, jpeg_bytes, _fields())
    assert response.status_code == 200, response.text
    image_path = response.json()["image_path"]
    assert image_path.startswith(f"raw/drill/{NO_GRADE_DIR}/T-010__0__")
    assert (settings.DATASET_DIR / image_path).is_file()
    with (settings.DATASET_DIR / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert (rows[0]["image_path"], rows[0]["item_id"], rows[0]["object_type"]) == (
        image_path,
        "T-010",
        "drill",
    )
    assert rows[0]["grade"] == ""

    # The same item_id with a grade afterwards: 422, nothing more written.
    files_before = sorted(
        p.relative_to(settings.DATASET_DIR) for p in settings.DATASET_DIR.rglob("*")
    )
    response = _post_collect(client, token, jpeg_bytes, _fields(grade="good"))
    assert response.status_code == 422
    files_after = sorted(
        p.relative_to(settings.DATASET_DIR) for p in settings.DATASET_DIR.rglob("*")
    )
    assert files_after == files_before


def test_collect_selector_lists_the_power_tools(settings: EdgeSettings) -> None:
    app = create_app(settings, None, InMemorySink())
    page = TestClient(app).get("/capture", params={"t": app.state.session_token}).text
    for value, label in POWER_TOOL_LABELS.items():
        assert f'<option value="{value}">{label}</option>' in page


def test_capture_script_knows_the_power_tools() -> None:
    script = STATIC_JS.read_text(encoding="utf-8")
    assert len(script.splitlines()) <= 200
    for tool in POWER_TOOLS:
        assert f'"{tool}"' in script
    assert 'NO_GRADE = ["other"].concat(POWER)' in script


# ---------------------------------------------------------------------------------- coverage


def _write_manifest(path: Path, rows: list[tuple[str, str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(MANIFEST_COLUMNS)
        for index, (item_id, object_type, grade) in enumerate(rows):
            folder = grade or NO_GRADE_DIR
            writer.writerow(
                (
                    f"raw/{object_type}/{folder}/{item_id}__0__{index}.jpg",
                    item_id,
                    object_type,
                    grade,
                    "a",
                    "0",
                    "",
                    "",
                    "",
                )
            )


def test_coverage_counts_power_tools_in_one_row_each(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    rows = [(f"T-{i % 4:03d}", "drill", "") for i in range(10)]
    rows += [("T-100", "saw", "")]
    rows += [("T-200", "angle_grinder", "good")]  # a grade on a power tool fits no cell
    rows += [("XT-0001", "drill", "")]  # external: never counted
    _write_manifest(manifest, rows)
    cells = {(c.object_type, c.grade): c for c in compute_coverage(manifest)}
    for tool in POWER_TOOLS:
        assert (tool, None) in cells
        assert not any((tool, grade) in cells for grade in GRADES)
    drill = cells[("drill", None)]
    assert (drill.images, drill.items) == (10, 4)
    assert (drill.target_images, drill.target_items) == (90, 6)
    assert (POWER_TOOL_TARGET_IMAGES, POWER_TOOL_TARGET_ITEMS) == (90, 6)
    assert (cells[("saw", None)].images, cells[("saw", None)].items) == (1, 1)
    assert (cells[("angle_grinder", None)].images, cells[("angle_grinder", None)].items) == (0, 0)


def test_console_coverage_has_a_row_per_power_tool(
    settings: EdgeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])
    app = create_app(settings, None, InMemorySink())
    page = TestClient(app, client=LOCAL, base_url=CONSOLE_URL).get("/").text
    for label in POWER_TOOL_LABELS.values():
        assert f"<tr><td>{label}</td><td>{VERDICT_UNGRADED}</td><td>0/90</td><td>0/6</td></tr>" in (
            page
        )
    assert "Ferramentas elétricas (sem grau): 90 imagens e 6 peças" in page
