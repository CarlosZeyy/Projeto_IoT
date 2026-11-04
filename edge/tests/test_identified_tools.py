"""Hammer, wrench and spirit level on the edge (SPEC-044 sections 3.1 and 4.3, ADR-025).

* ``labels.json``: an identification-only tool present in ``object_types`` must be in
  ``ungraded_object_types`` (the load rule of SPEC-016 section 4.4, derived from the contract), so
  it always comes out without a grade.
* The capture answers ``approved = null`` and ``verdict = "sem grau"``, and the outbox stores a
  payload that ``InspectionCreate`` 0.7.0 accepts.
* Collect mode: ``T-`` with one of the three and an empty grade, stored in ``raw/<type>/_/``; with
  a grade, 422 with its own message and nothing written. The power tools and ``other`` keep their
  messages.
* The capture page offers the three in the collect selector, ``capture.js`` admits them with
  ``T-`` and the console coverage table has one row per tool, with ``sem grau``.
"""

from __future__ import annotations

import csv
import json
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from qc_contracts import (
    GRADE_FORBIDDEN_OBJECT_TYPES,
    OBJECT_TYPE_LABELS_PT,
    InspectionCreate,
    ObjectType,
)
from qc_edge import netinfo
from qc_edge.app import DATASET_OBJECT_TYPE_LABELS_PT, VERDICT_UNGRADED, create_app
from qc_edge.collect import (
    IDENTIFIED_TOOL_MIN_ITEMS,
    IDENTIFIED_TOOL_OBJECT_TYPES,
    IDENTIFIED_TOOL_TARGET_IMAGES,
    IDENTIFIED_TOOL_TARGET_ITEMS,
    ITEM_PREFIX_TYPES,
    MANIFEST_COLUMNS,
    NO_GRADE_DIR,
    POWER_TOOL_OBJECT_TYPES,
    UNGRADED_DATASET_TYPES,
    CollectRequest,
    DatasetObjectType,
    InvalidCollectFieldError,
    compute_coverage,
    empty_coverage,
    item_prefix_matches,
)
from qc_edge.config import EdgeSettings
from qc_edge.decision import ModelLabels, Thresholds, decide
from qc_edge.inference import InferenceResult, StubInferencer
from qc_edge.onnx_inferencer import ModelLoadError, OnnxInferencer
from qc_edge.outbox import SqliteOutbox
from qc_edge.sink import InMemorySink

GRADES = ("perfect", "good", "fair", "poor", "unusable")
IDENTIFIED_TOOLS = ("hammer", "wrench", "spirit_level")
LABELS = {"hammer": "martelo", "wrench": "chave de aperto", "spirit_level": "nível"}
POWER_TOOLS = ("angle_grinder", "saw", "drill", "cordless_screwdriver")
# CA-05 of SPEC-044: a model without nut, with the hammer.
MODEL_TYPES = ("screw", "other", "hammer")
HAMMER_PROBS = [0.05, 0.05, 0.90]
THRESHOLDS = Thresholds(type_threshold=0.5, unusable_threshold=0.4, grade_review_threshold=0.6)
GOOD = [0.05, 0.8, 0.05, 0.05, 0.05]
LOCAL = ("127.0.0.1", 50000)
CONSOLE_URL = "http://127.0.0.1:8000"
STATIC_JS = Path(__file__).resolve().parents[1] / "src" / "qc_edge" / "static" / "capture.js"
IDENTIFIED_MESSAGE = "grade must be empty for an identification-only tool"


def _model_dir(
    dummy_model: types.ModuleType,
    root: Path,
    ungraded: Any,
    object_types: tuple[str, ...] = MODEL_TYPES,
    type_probs: list[float] = HAMMER_PROBS,
) -> Path:
    directory = dummy_model.write_model_dir(root, type_probs=type_probs, object_types=object_types)
    labels: dict[str, Any] = {"object_types": list(object_types), "grades": list(GRADES)}
    if ungraded is not None:
        labels["ungraded_object_types"] = ungraded
    (directory / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    return directory


# ----------------------------------------------------------------------------- collect constants


def test_identified_tools_mirror_the_contract() -> None:
    """The three are grade-forbidden types of the contract, the last members of ``ObjectType``
    and of ``DatasetObjectType``, in this order."""
    assert [t.value for t in IDENTIFIED_TOOL_OBJECT_TYPES] == list(IDENTIFIED_TOOLS)
    assert [m.value for m in ObjectType][-3:] == list(IDENTIFIED_TOOLS)
    assert [m.value for m in DatasetObjectType][-3:] == list(IDENTIFIED_TOOLS)
    assert all(ObjectType(tool) in GRADE_FORBIDDEN_OBJECT_TYPES for tool in IDENTIFIED_TOOLS)
    assert {t.value for t in UNGRADED_DATASET_TYPES} == {"other", *POWER_TOOLS, *IDENTIFIED_TOOLS}
    assert {m.value for m in GRADE_FORBIDDEN_OBJECT_TYPES if m is not ObjectType.UNKNOWN} == {
        t.value for t in (*POWER_TOOL_OBJECT_TYPES, *IDENTIFIED_TOOL_OBJECT_TYPES)
    }


def test_identified_tools_are_in_the_t_prefix() -> None:
    assert set(IDENTIFIED_TOOL_OBJECT_TYPES) <= ITEM_PREFIX_TYPES["T"]
    for letter in ("S", "N", "O"):
        assert not set(IDENTIFIED_TOOL_OBJECT_TYPES) & ITEM_PREFIX_TYPES[letter]


@pytest.mark.parametrize("tool", IDENTIFIED_TOOLS)
@pytest.mark.parametrize(("letter", "expected"), [("T", True), ("S", False), ("N", False)])
def test_t_prefix_admits_the_identified_tools(tool: str, letter: str, expected: bool) -> None:
    assert item_prefix_matches(letter, tool) is expected
    assert item_prefix_matches("O", tool) is False


def test_targets_are_those_of_the_power_tools() -> None:
    assert (IDENTIFIED_TOOL_TARGET_IMAGES, IDENTIFIED_TOOL_TARGET_ITEMS) == (90, 6)
    assert IDENTIFIED_TOOL_MIN_ITEMS == 3


# ------------------------------------------------------------------------------- labels.json


def test_model_with_a_hammer_needs_it_in_ungraded(
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    """CA-05 of SPEC-044 (load part): a model without nut, with the hammer."""
    for index, ungraded in enumerate((None, [])):
        with pytest.raises(ModelLoadError) as info:
            OnnxInferencer(_model_dir(dummy_model, tmp_path / str(index), ungraded))
        assert "must list every grade-forbidden type of object_types" in str(info.value)
        assert "hammer" not in str(info.value)  # the message never echoes the value
    inferencer = OnnxInferencer(_model_dir(dummy_model, tmp_path / "ok", ["hammer"]))
    assert inferencer.labels.object_types == MODEL_TYPES
    assert inferencer.labels.ungraded_object_types == ("hammer",)


def test_model_with_the_three_must_list_all_of_them(
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    object_types = ("screw", "other", "drill", *IDENTIFIED_TOOLS)
    probs = [0.05, 0.05, 0.05, 0.75, 0.05, 0.05]
    partial = ["drill", "hammer", "wrench"]
    with pytest.raises(ModelLoadError):
        OnnxInferencer(_model_dir(dummy_model, tmp_path / "partial", partial, object_types, probs))
    inferencer = OnnxInferencer(
        _model_dir(dummy_model, tmp_path / "all", ["drill", *IDENTIFIED_TOOLS], object_types, probs)
    )
    assert inferencer.labels.ungraded_object_types == ("drill", *IDENTIFIED_TOOLS)


# ------------------------------------------------------------------------------------ decision


def test_decided_hammer_has_no_grade() -> None:
    """CA-05 of SPEC-044 (decision part)."""
    labels = ModelLabels(object_types=MODEL_TYPES, grades=GRADES, ungraded_object_types=("hammer",))
    decision = decide(HAMMER_PROBS, GOOD, labels, THRESHOLDS)
    assert decision.object_type is ObjectType.HAMMER
    assert decision.grade is None and decision.grade_score is None
    assert decision.grade_confidence is None
    assert decision.needs_review is False
    below = decide([0.3, 0.25, 0.45], GOOD, labels, THRESHOLDS)
    assert below.object_type is ObjectType.UNKNOWN


# ----------------------------------------------------------------------------- capture route


def _post_inspect(client: TestClient, token: str, image: bytes) -> Any:
    return client.post(
        "/api/capture",
        headers={"X-Session-Token": token},
        data={"lot_id": "L-001", "mode": "inspect"},
        files={"image": ("a.jpg", image, "image/jpeg")},
    )


def test_capture_of_a_hammer_goes_to_the_outbox_without_grade(
    tmp_path: Path, dummy_model: types.ModuleType, settings: EdgeSettings, jpeg_bytes: bytes
) -> None:
    """CA-05 of SPEC-044 (capture part), with the real ONNX inferencer."""
    directory = _model_dir(dummy_model, tmp_path / "models", ["hammer"])
    outbox = SqliteOutbox(tmp_path / "outbox.sqlite")
    try:
        app = create_app(settings, OnnxInferencer(directory), outbox)
        with TestClient(app) as client:
            response = _post_inspect(client, app.state.session_token, jpeg_bytes)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["approved"] is None
        assert body["labels_pt"] == {"object_type": "martelo", "grade": None, "verdict": "sem grau"}
        (item,) = outbox.fetch_due(10)
        stored = item.to_inspection()
        assert InspectionCreate.model_validate(stored.model_dump(mode="json")) == stored
        assert stored.object_type is ObjectType.HAMMER
        assert stored.grade is None and stored.grade_score is None
        assert stored.grade_confidence is None
    finally:
        outbox.close()


@pytest.mark.parametrize("tool", IDENTIFIED_TOOLS)
def test_identified_tool_verdict(settings: EdgeSettings, jpeg_bytes: bytes, tool: str) -> None:
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
        "object_type": LABELS[tool],
        "grade": None,
        "verdict": VERDICT_UNGRADED,
    }
    assert LABELS[tool] == OBJECT_TYPE_LABELS_PT[ObjectType(tool)]


def test_console_row_of_a_spirit_level(
    settings: EdgeSettings, jpeg_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])
    result = InferenceResult(
        object_type=ObjectType.SPIRIT_LEVEL,
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
    assert f"<td>nível</td><td>{VERDICT_UNGRADED}</td></tr>" in page


# ---------------------------------------------------------------------------------- collect


def _fields(**changes: str) -> dict[str, str]:
    fields = {
        "item_id": "T-010",
        "object_type": "spirit_level",
        "grade": "",
        "labeler": "a",
        "angle": "0",
    }
    fields.update(changes)
    return fields


@pytest.mark.parametrize("tool", IDENTIFIED_TOOLS)
@pytest.mark.parametrize("grade", [None, ""])
def test_identified_tool_with_empty_grade_is_valid(tool: str, grade: str | None) -> None:
    fields: dict[str, object] = dict(_fields(object_type=tool))
    fields["grade"] = grade
    request = CollectRequest.from_fields(fields)
    assert request.object_type == tool and request.grade is None


@pytest.mark.parametrize("tool", IDENTIFIED_TOOLS)
@pytest.mark.parametrize("grade", [*GRADES, "great"])
def test_identified_tool_with_a_grade_is_refused(tool: str, grade: str) -> None:
    with pytest.raises(InvalidCollectFieldError) as info:
        CollectRequest.from_fields(_fields(object_type=tool, grade=grade))
    assert info.value.field == "grade"
    assert info.value.status_code == 422
    assert info.value.detail == IDENTIFIED_MESSAGE


@pytest.mark.parametrize(
    ("object_type", "message"),
    [
        ("drill", "grade must be empty for a power tool"),
        ("cordless_screwdriver", "grade must be empty for a power tool"),
        ("other", "grade must be empty for other"),
    ],
)
def test_other_ungraded_types_keep_their_messages(object_type: str, message: str) -> None:
    item_id = "O-010" if object_type == "other" else "T-010"
    with pytest.raises(InvalidCollectFieldError) as info:
        CollectRequest.from_fields(_fields(item_id=item_id, object_type=object_type, grade="good"))
    assert info.value.detail == message


@pytest.mark.parametrize("tool", IDENTIFIED_TOOLS)
@pytest.mark.parametrize("item_id", ["S-010", "N-010", "O-010"])
def test_identified_tool_needs_the_t_prefix(tool: str, item_id: str) -> None:
    with pytest.raises(InvalidCollectFieldError) as info:
        CollectRequest.from_fields(_fields(item_id=item_id, object_type=tool))
    assert info.value.field == "item_id"


def _post_collect(client: TestClient, token: str, image: bytes, fields: dict[str, str]) -> Any:
    return client.post(
        "/api/capture",
        headers={"X-Session-Token": token},
        data={"mode": "collect", **fields},
        files={"image": ("a.jpg", image, "image/jpeg")},
    )


def _files(root: Path) -> list[Path]:
    return sorted(p.relative_to(root) for p in root.rglob("*")) if root.exists() else []


def _manifest_rows(root: Path) -> list[dict[str, str]]:
    with (root / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_collect_of_the_identified_tools_through_the_route(
    settings: EdgeSettings, jpeg_bytes: bytes
) -> None:
    """CA-06 of SPEC-044."""
    app = create_app(settings, None, InMemorySink())
    client = TestClient(app)
    token = app.state.session_token
    root = settings.DATASET_DIR

    response = _post_collect(client, token, jpeg_bytes, _fields(item_id="T-010"))
    assert response.status_code == 200, response.text
    image_path = response.json()["image_path"]
    assert image_path.startswith(f"raw/spirit_level/{NO_GRADE_DIR}/T-010__0__")
    assert (root / image_path).is_file()
    (row,) = _manifest_rows(root)
    assert (row["image_path"], row["item_id"], row["object_type"], row["grade"]) == (
        image_path,
        "T-010",
        "spirit_level",
        "",
    )

    before = _files(root)
    manifest_before = (root / "manifest.csv").read_bytes()
    response = _post_collect(
        client, token, jpeg_bytes, _fields(item_id="T-011", object_type="hammer", grade="good")
    )
    assert response.status_code == 422
    assert response.json() == {"detail": IDENTIFIED_MESSAGE}
    response = _post_collect(
        client, token, jpeg_bytes, _fields(item_id="O-012", object_type="hammer")
    )
    assert response.status_code == 422
    response = _post_collect(
        client, token, jpeg_bytes, _fields(item_id="T-013", object_type="drill", grade="good")
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "grade must be empty for a power tool"}
    assert _files(root) == before
    assert (root / "manifest.csv").read_bytes() == manifest_before


@pytest.mark.parametrize("tool", IDENTIFIED_TOOLS)
def test_collect_of_each_identified_tool_goes_to_its_no_grade_folder(
    settings: EdgeSettings, jpeg_bytes: bytes, tool: str
) -> None:
    app = create_app(settings, None, InMemorySink())
    response = _post_collect(
        TestClient(app), app.state.session_token, jpeg_bytes, _fields(object_type=tool)
    )
    assert response.status_code == 200, response.text
    assert response.json()["image_path"].startswith(f"raw/{tool}/_/T-010__0__")


# -------------------------------------------------------------------------- page and script


def test_collect_selector_lists_the_identified_tools(settings: EdgeSettings) -> None:
    """CA-08 of SPEC-044 (page part): after the power tools, before "outro"."""
    app = create_app(settings, None, InMemorySink())
    page = TestClient(app).get("/capture", params={"t": app.state.session_token}).text
    options = [
        '<option value="cordless_screwdriver">parafusadeira</option>',
        '<option value="hammer">martelo</option>',
        '<option value="wrench">chave de aperto</option>',
        '<option value="spirit_level">nível</option>',
        '<option value="other">outro</option>',
    ]
    positions = [page.index(option) for option in options]
    assert positions == sorted(positions)
    for tool, label in LABELS.items():
        assert DATASET_OBJECT_TYPE_LABELS_PT[DatasetObjectType(tool)] == label


def _array(script: str, start: str) -> list[str]:
    body = script.split(start, 1)[1].split("]", 1)[0]
    return [part.strip().strip('"') for part in body.replace("\n", " ").split(",")]


def test_capture_script_knows_the_identified_tools(settings: EdgeSettings) -> None:
    """CA-08 of SPEC-044 (script part): the three in the ``T`` list and with no grade."""
    script = STATIC_JS.read_text(encoding="utf-8")
    assert len(script.splitlines()) <= 200
    no_grade = _array(script, "var NO_GRADE = [")
    assert no_grade == ["other", *POWER_TOOLS, *IDENTIFIED_TOOLS]
    assert "concat(NO_GRADE.slice(1))" in script  # T: the hand tools and every ungraded tool
    app = create_app(settings, None, InMemorySink())
    served = TestClient(app).get("/static/capture.js")
    assert served.status_code == 200
    assert served.text == script


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


def test_coverage_counts_identified_tools_in_one_row_each(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    rows = [(f"T-{i % 3:03d}", "hammer", "") for i in range(7)]
    rows += [("T-100", "wrench", "")]
    rows += [("T-200", "spirit_level", "good")]  # a grade on an ungraded tool fits no cell
    rows += [("XT-0001", "hammer", "")]  # external: never counted
    _write_manifest(manifest, rows)
    cells = {(c.object_type, c.grade): c for c in compute_coverage(manifest)}
    for tool in IDENTIFIED_TOOLS:
        assert (tool, None) in cells
        assert not any((tool, grade) in cells for grade in GRADES)
    hammer = cells[("hammer", None)]
    assert (hammer.images, hammer.items) == (7, 3)
    assert (hammer.target_images, hammer.target_items) == (90, 6)
    assert (cells[("wrench", None)].images, cells[("wrench", None)].items) == (1, 1)
    level = cells[("spirit_level", None)]
    assert (level.images, level.items) == (0, 0)


def test_coverage_order_puts_the_identified_tools_before_other() -> None:
    keys = [(c.object_type, c.grade) for c in empty_coverage()]
    assert len(keys) == 43
    assert keys[-4:] == [*[(tool, None) for tool in IDENTIFIED_TOOLS], ("other", None)]
    assert keys[-8:-4] == [(tool, None) for tool in POWER_TOOLS]


def test_console_coverage_has_a_row_per_identified_tool(
    settings: EdgeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-08 of SPEC-044 (console part)."""
    monkeypatch.setattr(netinfo, "detect_lan_ips", lambda: ["192.168.0.42"])
    app = create_app(settings, None, InMemorySink())
    page = TestClient(app, client=LOCAL, base_url=CONSOLE_URL).get("/").text
    table = page.split('<table id="coverage">', 1)[1].split("</table>", 1)[0]
    for label in LABELS.values():
        row = f"<tr><td>{label}</td><td>{VERDICT_UNGRADED}</td><td>0/90</td><td>0/6</td></tr>"
        assert table.count(row) == 1
    assert table.count("<tr><td>") == 43
    assert (
        "Ferramentas só identificadas (sem grau): martelo, chave de aperto e nível, 90 imagens e "
        "6 peças por ferramenta (mínimo 3)."
    ) in page
    assert "Ferramentas elétricas (sem grau): 90 imagens e 6 peças" in page
