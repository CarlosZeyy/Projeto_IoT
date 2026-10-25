"""Author tests of SPEC-016 section 4.8 (and 4.10): model types, masked grade, thresholds,
evaluation, decision, ``labels.json`` and the CHANGELOG with hand tools.

No torch: the evaluation uses the ``tiny_model_tools`` fixture with onnxruntime only.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qc_ml import evaluate as evaluate_mod
from qc_ml import report as report_mod
from qc_ml import split as split_mod
from qc_ml import thresholds as thresholds_mod
from qc_ml.artifacts import as_labels, check_labels, labels_to_dict, load_labels
from qc_ml.data import (
    DEFAULT_LABELS,
    GRADES,
    KNOWN_OBJECT_TYPES,
    TOOL_OBJECT_TYPES,
    ModelLabels,
    derive_model_labels,
    grade_target,
    load_manifest,
)
from qc_ml.decision import Thresholds, apply_decision
from qc_ml.errors import ModelArtifactError, TrainError
from qc_ml.evaluate import METRIC_KEYS, TOOL_GRADE_METRIC_KEYS, tool_grade_metrics
from qc_ml.predict import Predictions
from qc_ml.synthetic import make_synthetic_dataset
from qc_ml.thresholds import choose_thresholds
from qc_ml.train import graded_training_counts, model_labels_for

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TINY_TOOLS = FIXTURES / "tiny_model_tools"
TOOLS_LABELS = ModelLabels(KNOWN_OBJECT_TYPES, GRADES, ("allen_key",))
EIGHT = list(KNOWN_OBJECT_TYPES)


def _predictions(type_probs, grade_probs, true_type, true_grade, split="val") -> Predictions:
    n = len(type_probs)
    return Predictions(
        split=split,
        image_paths=[f"raw/x/{i}.jpg" for i in range(n)],
        type_probs=np.asarray(type_probs, dtype=np.float64),
        grade_probs=np.asarray(grade_probs, dtype=np.float64),
        true_type_idx=np.asarray(true_type),
        true_grade_idx=np.asarray(true_grade),
    )


def _type_row(index: int, confidence: float, n_types: int = 8) -> list[float]:
    rest = (1 - confidence) / (n_types - 1)
    return [confidence if k == index else rest for k in range(n_types)]


# ---------------------------------------------------------------------------------------------
# derive_model_labels and grade_target (CA-16)
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ca16_df(tmp_path_factory: pytest.TempPathFactory) -> pd.DataFrame:
    root = make_synthetic_dataset(
        tmp_path_factory.mktemp("ca16") / "ds", tool_items_per_stratum=5, images_per_item=12
    )
    df = load_manifest(root, verify_images=False)
    victim = df[(df["object_type"] == "allen_key") & (df["grade"] == "fair")]["image_path"].iloc[0]
    (root / victim).unlink()
    (root / "exclusions.csv").write_text(f"image_path,reason\n{victim},other\n", encoding="utf-8")
    return load_manifest(root, verify_images=False)


def test_ca16_model_labels_with_tools(ca16_df: pd.DataFrame) -> None:
    labels = derive_model_labels(ca16_df, ca16_df)
    assert labels.object_types == (
        "screw",
        "nut",
        "other",
        "pliers",
        "adjustable_wrench",
        "allen_key",
        "flat_screwdriver",
        "phillips_screwdriver",
    )
    assert labels.ungraded_object_types == ("allen_key",)
    assert labels.grades == GRADES


def test_ca16_model_labels_of_the_mvp(dataset: Path) -> None:
    df = load_manifest(dataset)
    labels = derive_model_labels(df, df)
    assert labels.object_types == DEFAULT_LABELS.object_types
    assert labels.grades == DEFAULT_LABELS.grades
    assert labels.ungraded_object_types == ()
    assert labels == DEFAULT_LABELS


def test_model_labels_use_only_the_train_rows_for_the_types(ca16_df: pd.DataFrame) -> None:
    train = ca16_df[ca16_df["object_type"].isin(["screw", "other", "phillips_screwdriver"])]
    labels = derive_model_labels(ca16_df, train)
    assert labels.object_types == ("screw", "other", "phillips_screwdriver")
    assert labels.ungraded_object_types == ()  # phillips is graded by the criterion on df


def test_ca16_grade_target() -> None:
    assert grade_target("allen_key", "good", TOOLS_LABELS) is None
    assert grade_target("other", None, TOOLS_LABELS) is None
    assert grade_target("pliers", "fair", TOOLS_LABELS) == 2
    assert grade_target("screw", "unusable", TOOLS_LABELS) == 4
    assert grade_target("screw", None, TOOLS_LABELS) is None
    assert grade_target("allen_key", "good", DEFAULT_LABELS) == 1


def test_graded_training_counts_leave_out_the_masked_rows() -> None:
    rows = pd.DataFrame(
        {
            "object_type": ["screw", "allen_key", "pliers", "other", "nut"],
            "grade": ["good", "good", "poor", None, "good"],
        }
    )
    assert graded_training_counts(rows, TOOLS_LABELS) == {
        "perfect": 0,
        "good": 2,
        "fair": 0,
        "poor": 1,
        "unusable": 0,
    }


def test_model_labels_need_other_in_train(ca16_df: pd.DataFrame) -> None:
    with pytest.raises(TrainError, match="other"):
        model_labels_for(ca16_df, ca16_df[ca16_df["object_type"] != "other"])
    assert model_labels_for(ca16_df, ca16_df).ungraded_object_types == ("allen_key",)


# ---------------------------------------------------------------------------------------------
# labels.json (section 4.8)
# ---------------------------------------------------------------------------------------------


def test_labels_dict_has_the_ungraded_types() -> None:
    assert labels_to_dict(TOOLS_LABELS) == {
        "object_types": EIGHT,
        "grades": list(GRADES),
        "ungraded_object_types": ["allen_key"],
    }
    assert labels_to_dict(DEFAULT_LABELS)["ungraded_object_types"] == []
    assert as_labels({"object_types": ["screw", "nut", "other"], "grades": list(GRADES)}) == (
        DEFAULT_LABELS
    )


def test_fixture_labels_json_has_the_ungraded_types() -> None:
    data = json.loads((TINY_TOOLS / "labels.json").read_text(encoding="utf-8"))
    assert data == labels_to_dict(TOOLS_LABELS)
    assert load_labels(TINY_TOOLS / "labels.json") == TOOLS_LABELS
    # the fixture of SPEC-012 keeps its labels.json without the key (read as [])
    assert load_labels(FIXTURES / "tiny_model" / "labels.json") == DEFAULT_LABELS


@pytest.mark.parametrize(
    "ungraded",
    [
        ["screw"],
        ["other"],
        ["nut"],
        ["pliers", "pliers"],
        ["hammer"],
    ],
)
def test_invalid_ungraded_types_are_refused(ungraded: list[str]) -> None:
    labels = {"object_types": EIGHT, "grades": list(GRADES), "ungraded_object_types": ungraded}
    with pytest.raises(ModelArtifactError):
        check_labels(as_labels(labels))


def test_ungraded_type_outside_the_model_is_refused() -> None:
    labels = {
        "object_types": ["screw", "nut", "other", "pliers"],
        "grades": list(GRADES),
        "ungraded_object_types": ["allen_key"],
    }
    with pytest.raises(ModelArtifactError, match="object_types"):
        check_labels(as_labels(labels))


@pytest.mark.parametrize("value", ["allen_key", None, [1], {"a": 1}])
def test_ungraded_types_must_be_a_list_of_strings(value: object) -> None:
    labels = {"object_types": EIGHT, "grades": list(GRADES), "ungraded_object_types": value}
    with pytest.raises(ModelArtifactError):
        as_labels(labels)


def test_unknown_labels_key_is_still_refused() -> None:
    with pytest.raises(ModelArtifactError):
        as_labels({"object_types": EIGHT, "grades": list(GRADES), "extra": []})


# ---------------------------------------------------------------------------------------------
# Decision with an ungraded type (as the edge, SPEC-016 section 4.4)
# ---------------------------------------------------------------------------------------------

T = Thresholds(0.70, 0.50, 0.60)


def test_ungraded_tool_has_no_grade_and_only_the_type_margin() -> None:
    grade = [0.4, 0.3, 0.1, 0.1, 0.1]  # grade confidence 0.4 < 0.60
    sure = apply_decision(_type_row(5, 0.90), grade, TOOLS_LABELS, T).record(0)
    assert sure == {
        "object_type": "allen_key",
        "grade": None,
        "grade_score": None,
        "type_confidence": pytest.approx(0.90),
        "grade_confidence": None,
        "needs_review": False,
    }
    unsure = apply_decision(_type_row(5, 0.75), grade, TOOLS_LABELS, T).record(0)
    assert unsure["grade"] is None and unsure["needs_review"] is True
    graded = apply_decision(_type_row(3, 0.90), grade, TOOLS_LABELS, T).record(0)
    assert graded["object_type"] == "pliers"
    assert graded["grade"] == "perfect" and graded["needs_review"] is True


def test_same_result_as_the_edge_decision_with_ungraded_types() -> None:
    edge = pytest.importorskip("qc_edge.decision")
    rng = np.random.default_rng(16)
    labels = edge.ModelLabels(
        TOOLS_LABELS.object_types, TOOLS_LABELS.grades, TOOLS_LABELS.ungraded_object_types
    )
    for _ in range(1000):
        sharp = rng.uniform(0.2, 5.0)
        type_probs = rng.dirichlet(np.full(8, 1 / sharp))
        grade_probs = rng.dirichlet(np.full(5, 1 / sharp))
        t, u, r = (round(float(v), 2) for v in rng.uniform([0.5, 0.05, 0.3], [0.85, 0.95, 0.95]))
        mine = apply_decision(type_probs, grade_probs, TOOLS_LABELS, Thresholds(t, u, r)).record(0)
        theirs = edge.decide(
            type_probs.tolist(), grade_probs.tolist(), labels, edge.Thresholds(t, u, r)
        )
        assert mine["object_type"] == theirs.object_type.value
        assert mine["grade"] == (None if theirs.grade is None else theirs.grade.value)
        assert mine["needs_review"] == theirs.needs_review
        for key in ("grade_confidence", "grade_score"):
            value = getattr(theirs, key)
            assert (mine[key] is None) == (value is None)
            if value is not None:
                assert mine[key] == pytest.approx(value, abs=1e-12)


# ---------------------------------------------------------------------------------------------
# Thresholds (CA-17)
# ---------------------------------------------------------------------------------------------


def test_ca17_false_unknown_counts_every_type_but_other() -> None:
    pliers, screw = 3, 0
    type_probs = [_type_row(pliers, 0.55)] * 2 + [_type_row(pliers, 0.95)] * 8
    type_probs += [_type_row(screw, 0.95)] * 10
    grade = [[0.9, 0.025, 0.025, 0.025, 0.025]] * 20
    preds = _predictions(type_probs, grade, [pliers] * 10 + [screw] * 10, [0] * 20)
    result = choose_thresholds(preds, TOOLS_LABELS)
    section = result.report["type_threshold"]
    assert section["n_images"] == 20
    # 2 of 20 = 10% above 0.55, so the largest t with FU <= 5% is 0.55
    assert result.decision.type_threshold == 0.55
    assert section["false_unknown_rate"] == 0.0
    point = next(p for p in section["curve"] if p["threshold"] == 0.56)
    assert point["n_unknown"] == 2 and point["false_unknown_rate"] == 0.1


def test_unusable_and_review_thresholds_ignore_the_tools() -> None:
    """Graded tools in val never move the unusable or the review threshold (ADR-022)."""
    screw, pliers = 0, 3
    screws = [_type_row(screw, 0.99)] * 10
    screw_grades = [[0.02, 0.02, 0.02, 0.04, 0.90]] * 5 + [[0.9, 0.025, 0.025, 0.025, 0.025]] * 5
    base = _predictions(screws, screw_grades, [screw] * 10, [4] * 5 + [0] * 5)
    tools = [_type_row(pliers, 0.99)] * 10
    tool_grades = [[0.5, 0.0, 0.0, 0.0, 0.5]] * 10  # unusable truth, low confidence
    mixed = _predictions(
        screws + tools,
        screw_grades + tool_grades,
        [screw] * 10 + [pliers] * 10,
        [4] * 5 + [0] * 5 + [4] * 10,
    )
    alone = choose_thresholds(base, TOOLS_LABELS)
    with_tools = choose_thresholds(mixed, TOOLS_LABELS)
    assert with_tools.decision.unusable_threshold == alone.decision.unusable_threshold
    assert with_tools.decision.grade_review_threshold == alone.decision.grade_review_threshold
    assert with_tools.report["unusable_threshold"]["n_images"] == 10
    assert with_tools.report["grade_review_threshold"]["n_images"] == 10


def test_review_threshold_counts_screw_nut_and_other() -> None:
    """SPEC-016 4.8 (SPEC_ISSUE-1): other enters the review fraction, as in SPEC-012."""
    screw, other, pliers = 0, 2, 3
    type_probs = [_type_row(screw, 0.99)] * 10 + [_type_row(other, 0.99)] * 10
    type_probs += [_type_row(pliers, 0.99)] * 5
    grades = [[0.5, 0.2, 0.1, 0.1, 0.1]] * 2 + [[0.95, 0.02, 0.01, 0.01, 0.01]] * 8
    grades += [[0.2] * 5] * 15
    truth = [screw] * 10 + [other] * 10 + [pliers] * 5
    preds = _predictions(type_probs, grades, truth, [0] * 10 + [-1] * 10 + [0] * 5)
    result = choose_thresholds(preds, TOOLS_LABELS)
    section = result.report["grade_review_threshold"]
    assert section["n_images"] == 20  # 10 screw + 10 other; the 5 pliers left out
    assert section["needs_review_rate_at_default"] == 0.1
    assert result.decision.grade_review_threshold == 0.60
    assert "review_adjusted" not in result.report["notes"]


def test_ca22_review_threshold_example() -> None:
    """The CA-22 example: 2/20 = 10% with screw and other; the tools are out."""
    labels = ModelLabels(("screw", "nut", "other", "pliers"), GRADES)
    low, high = [0.50, 0.20, 0.10, 0.10, 0.10], [0.95, 0.02, 0.01, 0.01, 0.01]
    type_probs = [[0.97, 0.01, 0.01, 0.01]] * 10 + [[0.01, 0.01, 0.97, 0.01]] * 10
    type_probs += [[0.01, 0.01, 0.01, 0.97]] * 20
    grades = [low] * 2 + [high] * 8 + [high] * 10 + [low] * 20
    truth = [0] * 10 + [2] * 10 + [3] * 20
    preds = _predictions(type_probs, grades, truth, [0] * 10 + [-1] * 10 + [0] * 20)
    result = choose_thresholds(preds, labels)
    assert result.decision.type_threshold == 0.85
    assert result.decision.grade_review_threshold == 0.60
    assert "review_adjusted" not in result.report["notes"]


def test_thresholds_of_the_mvp_labels_are_unchanged() -> None:
    """Without tools, FU(t) counts screw/nut exactly as SPEC-012 (other left out)."""
    type_probs = [[0.99, 0.005, 0.005]] * 10 + [[0.005, 0.005, 0.99]] * 5
    preds = _predictions(
        type_probs,
        [[0.9, 0.025, 0.025, 0.025, 0.025]] * 15,
        [0] * 10 + [2] * 5,
        [0] * 10 + [-1] * 5,
    )
    result = choose_thresholds(preds, DEFAULT_LABELS)
    assert result.report["type_threshold"]["n_images"] == 10
    assert result.decision.type_threshold == 0.85


# ---------------------------------------------------------------------------------------------
# Evaluation (CA-18) with the tiny_model_tools fixture
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _tools_env(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("tools_env")
    plain = make_synthetic_dataset(base / "plain")
    argv = ["--splits-dir", str(base / "splits")]
    assert split_mod.main(["--dataset-dir", str(plain), *argv]) == 0
    tools = make_synthetic_dataset(base / "ds", tool_items_per_stratum=3)
    extend = ["--extend-test-types", ",".join(TOOL_OBJECT_TYPES)]
    assert split_mod.main(["--dataset-dir", str(tools), *argv, *extend]) == 0
    return base


@pytest.fixture
def tools_config(_tools_env: Path, tmp_path: Path) -> Path:
    base = Path(shutil.copytree(_tools_env, tmp_path / "env"))
    shutil.copytree(TINY_TOOLS, tmp_path / "models" / "partqc-tinytools-v1")
    config = {
        "model_version": "partqc-tinytools-v1",
        "dataset_dir": str(base / "ds"),
        "split_file": str(base / "splits" / "split_v2.csv"),
        "backbone": "tiny",
        "pretrained": False,
        "epochs_a": 1,
        "epochs_b_max": 1,
        "num_workers": 0,
        "smoke": True,
        "models_root": str(tmp_path / "models"),
        "reports_root": str(tmp_path / "reports"),
        "checkpoints_root": str(tmp_path / "checkpoints"),
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_ca18_evaluate_with_tools(tools_config: Path) -> None:
    assert thresholds_mod.main(["--config", str(tools_config)]) == 0
    assert evaluate_mod.main(["--config", str(tools_config), "--latency-machine", "ci"]) == 0
    model_dir = tools_config.parent / "models" / "partqc-tinytools-v1"
    metrics = json.loads((model_dir / "metrics.json").read_text(encoding="utf-8"))
    assert list(metrics) == list(METRIC_KEYS)
    assert np.asarray(metrics["type_confusion"]).shape == (8, 8)
    assert metrics["labels"]["object_types"] == EIGHT
    assert metrics["labels"]["ungraded_object_types"] == ["allen_key"]
    tool_metrics = metrics["tool_grade_metrics"]
    assert list(tool_metrics) == [
        "pliers",
        "adjustable_wrench",
        "flat_screwdriver",
        "phillips_screwdriver",
    ]
    for entry in tool_metrics.values():
        assert list(entry) == list(TOOL_GRADE_METRIC_KEYS)
        # 15 items per tool, ungraded by the criterion: one stratum -> 2 test items (SPEC-016 4.7)
        assert entry["n_images_test"] == 4 and entry["n_items_test"] == 2
    # grade metrics stay on screw/nut (ADR-022, decision 6)
    assert int(np.asarray(metrics["grade_confusion"]).sum()) == sum(
        metrics["counts"]["test"]["by_class"][t]["n_images"] for t in ("screw", "nut")
    )
    assert set(metrics["counts"]["test"]["by_class"]["pliers"]["by_grade"]) == set(GRADES)
    assert (
        tools_config.parent / "reports" / "partqc-tinytools-v1" / "type_confusion.png"
    ).is_file()


def test_few_test_items_warning_per_model_type(tools_config: Path) -> None:
    assert thresholds_mod.main(["--config", str(tools_config)]) == 0
    assert evaluate_mod.main(["--config", str(tools_config)]) == 0
    model_dir = tools_config.parent / "models" / "partqc-tinytools-v1"
    warnings = json.loads((model_dir / "metrics.json").read_text())["warnings"]
    # 4 items of other -> 1 in test; every tool has 2 test items
    assert "few test items for other: 1" in warnings
    assert not any(w.startswith("few test items for pliers") for w in warnings)


def test_tool_grade_metrics_values() -> None:
    labels = ModelLabels(("screw", "nut", "other", "pliers", "allen_key"), GRADES, ("allen_key",))
    eye = np.eye(5)
    grade_probs = [eye[0], eye[1], eye[2], eye[2], eye[4], eye[3]]
    preds = _predictions(
        [[0, 0, 0, 1, 0]] * 4 + [[0, 0, 0, 0, 1]] * 2,
        grade_probs,
        [3, 3, 3, 3, 4, 4],
        [0, 1, 2, 3, 4, 3],
        split="test",
    )
    result = tool_grade_metrics(
        preds, ["T-001", "T-001", "T-002", "T-003", "T-004", "T-005"], labels, 0.5
    )
    assert list(result) == ["pliers"]
    entry = result["pliers"]
    assert entry["n_images_test"] == 4 and entry["n_items_test"] == 3
    assert entry["grade_mae"] == 0.25
    assert entry["grade_off_by_one_accuracy"] == 1.0
    assert entry["grade_qwk"] is not None and 0 < entry["grade_qwk"] < 1
    empty = tool_grade_metrics(preds, ["x"] * 6, DEFAULT_LABELS, 0.5)
    assert empty == {}


def test_tool_grade_metrics_without_test_images_are_null() -> None:
    labels = ModelLabels(("screw", "nut", "other", "pliers"), GRADES)
    preds = _predictions([[1, 0, 0, 0]], [np.eye(5)[0]], [0], [0], split="test")
    assert tool_grade_metrics(preds, ["S-001"], labels, 0.5) == {
        "pliers": {
            "grade_qwk": None,
            "grade_mae": None,
            "grade_off_by_one_accuracy": None,
            "n_images_test": 0,
            "n_items_test": 0,
        }
    }


# ---------------------------------------------------------------------------------------------
# CHANGELOG (section 4.8)
# ---------------------------------------------------------------------------------------------

BASE_METRICS = {
    "model_version": "partqc-mnv3-v2",
    "model_sha256": "a" * 64,
    "evaluated_at": "2026-11-20T13:00:00+00:00",
    "type_accuracy": 0.9,
}


def test_changelog_lists_the_model_types_before_the_table() -> None:
    metrics = {**BASE_METRICS, "labels": labels_to_dict(TOOLS_LABELS)}
    lines = report_mod.changelog_entry(metrics).splitlines()
    types_line = (
        "- Tipos do modelo: screw, nut, other, pliers, adjustable_wrench, allen_key, "
        "flat_screwdriver, phillips_screwdriver; sem grau: allen_key."
    )
    assert types_line in lines
    table = next(k for k, line in enumerate(lines) if line.startswith("| Métrica"))
    assert lines.index(types_line) < table
    assert report_mod.TYPE_ACCURACY_NOTE in lines[:table]
    graded = {**metrics, "labels": {**metrics["labels"], "ungraded_object_types": []}}
    assert any(
        line.endswith("sem grau: nenhum.")
        for line in report_mod.changelog_entry(graded).splitlines()
    )


def test_changelog_without_tools_has_no_types_line() -> None:
    for metrics in (
        {**BASE_METRICS, "labels": labels_to_dict(DEFAULT_LABELS)},
        {**BASE_METRICS, "labels": {"object_types": ["screw", "nut", "other"], "grades": []}},
        dict(BASE_METRICS),
    ):
        text = report_mod.changelog_entry(metrics)
        assert "Tipos do modelo" not in text
        assert report_mod.TYPE_ACCURACY_NOTE not in text


@pytest.mark.parametrize(
    "labels",
    [
        {"object_types": ["screw", "pliers", "other\n- forged"], "ungraded_object_types": []},
        {"object_types": ["screw", "pliers"], "ungraded_object_types": "pliers"},
        {"object_types": "pliers"},
        ["pliers"],
    ],
)
def test_changelog_refuses_invalid_labels(labels: object, tmp_path: Path, capsys) -> None:
    metrics = {**BASE_METRICS, "labels": labels}
    with pytest.raises(ValueError, match="invalid labels"):
        report_mod.changelog_entry(metrics)
    model_dir = tmp_path / "m"
    model_dir.mkdir()
    (model_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    assert report_mod.main(["changelog", "--model-dir", str(model_dir)]) == 2
    assert "forged" not in capsys.readouterr().err
