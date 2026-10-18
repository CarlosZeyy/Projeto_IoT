"""``OnnxInferencer``: model loading and inference (SPEC-008 sections 4.2 and 4.3).

Every model is a dummy built with ``onnx.helper`` in ``tmp_path`` (``edge/tests/dummy_model.py``).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from qc_contracts import Grade, ObjectType
from qc_edge import onnx_inferencer
from qc_edge.decision import InvalidModelOutputError, ModelLabels, Thresholds
from qc_edge.inference import InferenceError, Inferencer, ModelInfo
from qc_edge.onnx_inferencer import (
    ModelIntegrityError,
    ModelLoadError,
    OnnxInferencer,
)
from qc_preprocess import PreprocessParams, load_image


@pytest.fixture
def photo() -> Image.Image:
    """A 1280x960 JPEG decoded by ``load_image``, as the capture route does."""
    rng = np.random.default_rng(3)
    buffer = io.BytesIO()
    Image.fromarray(rng.integers(0, 256, (960, 1280, 3), dtype=np.uint8), "RGB").save(
        buffer, format="JPEG", quality=90
    )
    return load_image(buffer.getvalue())


def _load(directory: Path, **kwargs: Any) -> OnnxInferencer:
    return OnnxInferencer(directory, **kwargs)


# ---------------------------------------------------------------- loading: success


def test_loads_a_valid_directory(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    directory = dummy_model.write_model_dir(tmp_path)
    inferencer = _load(directory)
    sha = dummy_model.sha256_of(directory / "model.onnx")
    assert inferencer.model_info == ModelInfo("dummy-v1", sha)
    assert inferencer.labels == ModelLabels(
        ("screw", "nut", "other"), ("perfect", "good", "fair", "poor", "unusable")
    )
    assert inferencer.thresholds == Thresholds(0.5, 0.4, 0.6)
    assert inferencer.threshold_sources == {
        "type_threshold": "decision.json",
        "unusable_threshold": "decision.json",
        "grade_review_threshold": "decision.json",
    }
    protocol: Inferencer = inferencer  # structural: model_info and infer
    assert protocol.model_info is inferencer.model_info


@pytest.mark.parametrize(
    "content",
    [
        "{sha}",
        "{sha}\n",
        "{sha}  model.onnx\n",
        "{sha} *model.onnx\n",
        "  {sha}\tmodel.onnx",
        "{upper}  model.onnx\n",
    ],
)
def test_sha256_file_formats(tmp_path: Path, dummy_model: types.ModuleType, content: str) -> None:
    data = dummy_model.build_model().SerializeToString()
    sha = hashlib.sha256(data).hexdigest()
    directory = dummy_model.write_model_dir(
        tmp_path, model=data, sha256=content.format(sha=sha, upper=sha.upper())
    )
    assert _load(directory).model_info.model_sha256 == sha  # always lowercase


@pytest.mark.parametrize("name", ["partqc-mnv3-v1", "abc", "v1.2.3", "a" * 40])
def test_model_version_is_the_directory_name(
    tmp_path: Path, dummy_model: types.ModuleType, name: str
) -> None:
    directory = dummy_model.write_model_dir(tmp_path, name)
    assert _load(directory).model_info.model_version == name


def test_relative_dot_directory_and_trailing_slash(
    tmp_path: Path, dummy_model: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = dummy_model.write_model_dir(tmp_path, "dummy-v2")
    monkeypatch.chdir(directory)
    assert _load(Path(".")).model_info.model_version == "dummy-v2"
    assert OnnxInferencer(Path(str(directory) + "/")).model_info.model_version == "dummy-v2"


def test_symlink_gives_the_name_of_the_target(  # CA-21
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models")
    link = tmp_path / "atual"
    link.symlink_to(directory, target_is_directory=True)
    inferencer = _load(link)
    assert inferencer.model_info == ModelInfo(
        "dummy-v1", dummy_model.sha256_of(directory / "model.onnx")
    )
    # A chain of links, a trailing slash and a relative link all resolve to the same target.
    chain = tmp_path / "current"
    chain.symlink_to(link, target_is_directory=True)
    relative = tmp_path / "rel"
    relative.symlink_to(Path("models") / "dummy-v1", target_is_directory=True)
    assert _load(chain).model_info.model_version == "dummy-v1"
    assert OnnxInferencer(Path(str(link) + "/")).model_info.model_version == "dummy-v1"
    assert _load(relative).model_info.model_version == "dummy-v1"


def test_symlink_to_a_directory_with_an_invalid_name(  # CA-21
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models", "Dummy_V1")
    link = tmp_path / "atual"
    link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ModelLoadError, match="MODEL_DIR: the directory name is the model_version"):
        _load(link)


def test_valid_link_name_does_not_rescue_an_invalid_target(
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models", "ab")
    link = tmp_path / "partqc-link-v2"
    link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ModelLoadError, match="MODEL_DIR"):
        _load(link)


def test_dot_dot_components_are_resolved(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    dummy_model.write_model_dir(tmp_path / "models")
    (tmp_path / "other").mkdir()
    path = tmp_path / "other" / ".." / "models" / "dummy-v1" / "."
    assert _load(path).model_info.model_version == "dummy-v1"


def test_files_are_read_from_the_resolved_directory(
    tmp_path: Path, dummy_model: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = dummy_model.write_model_dir(tmp_path / "models")
    link = tmp_path / "atual"
    link.symlink_to(directory, target_is_directory=True)
    opened: list[Path] = []
    original_open = Path.open

    def _spy(self: Path, *args: Any, **kwargs: Any) -> Any:
        opened.append(self)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _spy)
    _load(link)
    assert opened  # model.onnx, model.sha256 and the JSON files are opened through Path.open
    assert all(path.parent == directory.resolve() for path in opened)


def test_broken_link_or_link_loop_names_model_dir(tmp_path: Path) -> None:
    broken = tmp_path / "broken-v1"
    broken.symlink_to(tmp_path / "nowhere", target_is_directory=True)
    loop_a, loop_b = tmp_path / "loop-a", tmp_path / "loop-b"
    loop_a.symlink_to(loop_b, target_is_directory=True)
    loop_b.symlink_to(loop_a, target_is_directory=True)
    for path in (broken, loop_a, Path(str(tmp_path) + "/nul\x00-v1")):
        with pytest.raises(ModelLoadError, match="^MODEL_DIR: not a directory$"):
            _load(path)


def test_model_with_type_labels_of_any_order(tmp_path: Path, dummy_model: types.ModuleType):
    directory = dummy_model.write_model_dir(
        tmp_path, object_types=("nut", "screw"), type_probs=(0.2, 0.8)
    )
    inferencer = _load(directory)
    assert inferencer.labels.object_types == ("nut", "screw")


# ---------------------------------------------------------------- loading: failures


@pytest.mark.parametrize(
    "missing",
    ["model.onnx", "model.sha256", "labels.json", "preprocessing.json", "decision.json"],
)
def test_missing_file(tmp_path: Path, dummy_model: types.ModuleType, missing: str) -> None:
    directory = dummy_model.write_model_dir(tmp_path, omit=[missing])
    with pytest.raises(ModelLoadError, match=missing.replace(".", r"\.")):
        _load(directory)


def test_missing_directory_or_a_file(tmp_path: Path) -> None:
    with pytest.raises(ModelLoadError, match="MODEL_DIR"):
        _load(tmp_path / "nope-v1")
    (tmp_path / "file-v1").write_text("x")
    with pytest.raises(ModelLoadError, match="MODEL_DIR"):
        _load(tmp_path / "file-v1")


def test_artifact_that_is_a_directory(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    directory = dummy_model.write_model_dir(tmp_path, omit=["decision.json"])
    (directory / "decision.json").mkdir()
    with pytest.raises(ModelLoadError, match=r"decision\.json"):
        _load(directory)


def test_hash_mismatch(tmp_path: Path, dummy_model: types.ModuleType) -> None:  # CA-09
    wrong = "ab" * 32
    directory = dummy_model.write_model_dir(tmp_path, sha256=f"{wrong}  model.onnx\n")
    actual = dummy_model.sha256_of(directory / "model.onnx")
    with pytest.raises(ModelIntegrityError) as excinfo:
        _load(directory)
    message = str(excinfo.value)
    assert wrong[:12] in message
    assert actual[:12] in message
    assert wrong not in message and actual not in message  # only 12 characters of each
    assert isinstance(excinfo.value, ModelLoadError)


def test_model_changed_after_the_hash(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    directory = dummy_model.write_model_dir(tmp_path)
    (directory / "model.onnx").write_bytes(
        dummy_model.build_model(type_probs=(0.1, 0.1, 0.8)).SerializeToString()
    )
    with pytest.raises(ModelIntegrityError):
        _load(directory)


@pytest.mark.parametrize(
    "content",
    ["", "\n", "not-a-hash  model.onnx", "a" * 63, "a" * 65, "g" * 64, "é" * 64, "a" * 5000],
)
def test_malformed_sha256_file(tmp_path: Path, dummy_model: types.ModuleType, content: str) -> None:
    directory = dummy_model.write_model_dir(tmp_path, sha256=content)
    with pytest.raises(ModelLoadError, match=r"model\.sha256") as excinfo:
        _load(directory)
    assert not isinstance(excinfo.value, ModelIntegrityError)


def test_integrity_is_checked_before_the_other_files(
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    directory = dummy_model.write_model_dir(
        tmp_path, "Bad_Name", sha256="cd" * 32, decision={"type_threshold": 2}
    )
    with pytest.raises(ModelIntegrityError):
        _load(directory)


@pytest.mark.parametrize("name", ["ab", "Dummy-v1", "dummy_v1", "a" * 41, "dummy v1"])
def test_invalid_model_version(tmp_path: Path, dummy_model: types.ModuleType, name: str) -> None:
    directory = dummy_model.write_model_dir(tmp_path, name)
    with pytest.raises(ModelLoadError, match="model_version"):
        _load(directory)


@pytest.mark.parametrize(
    "labels",
    [
        {
            "object_types": ["screw", "pliers", "other"],
            "grades": list(onnx_inferencer.EXPECTED_GRADES),
        },
        {"object_types": ["screw", "unknown"], "grades": list(onnx_inferencer.EXPECTED_GRADES)},
        {
            "object_types": ["screw", "nut", "other"],
            "grades": ["good", "perfect", "fair", "poor", "unusable"],
        },
        {"object_types": ["screw", "nut", "other"], "grades": ["perfect", "good", "fair", "poor"]},
        {"object_types": ["screw", "nut", "other"], "grades": "perfect,good,fair,poor,unusable"},
        {
            "object_types": ["screw", "screw", "other"],
            "grades": list(onnx_inferencer.EXPECTED_GRADES),
        },
        {"object_types": [], "grades": list(onnx_inferencer.EXPECTED_GRADES)},
        {"object_types": "screw", "grades": list(onnx_inferencer.EXPECTED_GRADES)},
        {"object_types": ["screw", 1, "other"], "grades": list(onnx_inferencer.EXPECTED_GRADES)},
        {
            "object_types": ["Screw", "nut", "other"],
            "grades": list(onnx_inferencer.EXPECTED_GRADES),
        },
        {"object_types": ["screw", "nut", "other"]},
        {"grades": list(onnx_inferencer.EXPECTED_GRADES)},
        {
            "object_types": ["screw", "nut", "other"],
            "grades": list(onnx_inferencer.EXPECTED_GRADES),
            "extra": 1,
        },
        ["screw", "nut", "other"],
    ],
)
def test_invalid_labels(tmp_path: Path, dummy_model: types.ModuleType, labels: Any) -> None:
    directory = dummy_model.write_model_dir(tmp_path, labels={"_": 0})
    (directory / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    with pytest.raises(ModelLoadError, match=r"labels\.json"):
        _load(directory)


@pytest.mark.parametrize("content", [b"{not json", b"\xff\xfe\x00", b""])
def test_unreadable_json(tmp_path: Path, dummy_model: types.ModuleType, content: bytes) -> None:
    for name in ("labels.json", "decision.json"):
        directory = dummy_model.write_model_dir(tmp_path / name)
        (directory / name).write_bytes(content)
        with pytest.raises(ModelLoadError, match=name.replace(".", r"\.")):
            _load(directory)


@pytest.mark.parametrize(
    "preprocessing",
    [
        {"resize_shorter": 256, "crop": 224, "mean": [0.485, 0.456, 0.406]},
        {"resize_shorter": 256, "crop": 300, "mean": [0, 0, 0], "std": [1, 1, 1]},
        {"resize_shorter": 256, "crop": 224, "mean": [0, 0, 0], "std": [0, 1, 1]},
        {"resize_shorter": "256", "crop": 224, "mean": [0, 0, 0], "std": [1, 1, 1]},
        {"resize_shorter": 256, "crop": 224, "mean": [0, 0, 0], "std": [1, 1, 1], "x": 1},
    ],
)
def test_invalid_preprocessing(
    tmp_path: Path, dummy_model: types.ModuleType, preprocessing: dict[str, Any]
) -> None:
    directory = dummy_model.write_model_dir(tmp_path, preprocessing=preprocessing)
    with pytest.raises(ModelLoadError, match=r"preprocessing\.json") as excinfo:
        _load(directory)
    assert str(tmp_path) not in str(excinfo.value)  # only the file name, never the path


def test_unparsable_preprocessing(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    directory = dummy_model.write_model_dir(tmp_path)
    (directory / "preprocessing.json").write_text("[1, 2", encoding="utf-8")
    with pytest.raises(ModelLoadError, match=r"preprocessing\.json"):
        _load(directory)


def test_preprocessing_params_are_used(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    params = {"resize_shorter": 230, "crop": 224, "mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5]}
    directory = dummy_model.write_model_dir(tmp_path, preprocessing=params)
    assert _load(directory)._params == PreprocessParams(**params)


@pytest.mark.parametrize(
    "decision",
    [
        {"type_threshold": 1.2, "unusable_threshold": 0.4, "grade_review_threshold": 0.6},
        {"type_threshold": 0.5, "unusable_threshold": -0.1, "grade_review_threshold": 0.6},
        {"type_threshold": 0.5, "unusable_threshold": 0.4, "grade_review_threshold": "0.6"},
        {"type_threshold": 0.5, "unusable_threshold": 0.4, "grade_review_threshold": True},
        {"type_threshold": 0.5, "unusable_threshold": 0.4, "grade_review_threshold": None},
        {"type_threshold": 0.5, "unusable_threshold": 0.4},
        {"type_threshold": 0.5, "unusable_threshold": 0.4, "grade_review_threshold": 0.6, "x": 1},
    ],
)
def test_invalid_decision(
    tmp_path: Path, dummy_model: types.ModuleType, decision: dict[str, Any]
) -> None:  # CA-11
    directory = dummy_model.write_model_dir(tmp_path, decision=decision)
    with pytest.raises(ModelLoadError, match=r"decision\.json"):
        _load(directory)


@pytest.mark.parametrize("constant", ["NaN", "Infinity"])
def test_decision_with_non_finite_constants(
    tmp_path: Path, dummy_model: types.ModuleType, constant: str
) -> None:
    directory = dummy_model.write_model_dir(tmp_path)
    text = '{"type_threshold": CONST, "unusable_threshold": 0.4, "grade_review_threshold": 0.6}'
    (directory / "decision.json").write_text(text.replace("CONST", constant), encoding="utf-8")
    with pytest.raises(ModelLoadError, match="type_threshold"):
        _load(directory)


def test_decision_bounds_are_accepted(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    directory = dummy_model.write_model_dir(
        tmp_path,
        decision={"type_threshold": 0, "unusable_threshold": 1, "grade_review_threshold": 0.0},
    )
    assert _load(directory).thresholds == Thresholds(0.0, 1.0, 0.0)


# ---------------------------------------------------------------- overrides


def test_override_takes_precedence(tmp_path: Path, dummy_model: types.ModuleType) -> None:  # CA-12
    directory = dummy_model.write_model_dir(
        tmp_path,
        decision={"type_threshold": 0.7, "unusable_threshold": 0.4, "grade_review_threshold": 0.6},
    )
    inferencer = _load(directory, overrides={"TYPE_THRESHOLD": 0.55})
    assert inferencer.thresholds.type_threshold == 0.55
    assert inferencer.threshold_sources["type_threshold"] == "env"
    assert inferencer.threshold_sources["unusable_threshold"] == "decision.json"
    assert inferencer.thresholds.unusable_threshold == 0.4


def test_every_override_and_threshold_names(tmp_path: Path, dummy_model: types.ModuleType):
    directory = dummy_model.write_model_dir(tmp_path)
    inferencer = _load(
        directory,
        overrides={"type_threshold": 0.3, "UNUSABLE_THRESHOLD": "0.2", "GRADE_REVIEW_THRESHOLD": 1},
    )
    assert inferencer.thresholds == Thresholds(0.3, 0.2, 1.0)
    assert set(inferencer.threshold_sources.values()) == {"env"}


@pytest.mark.parametrize("value", [1.5, -0.1, "abc", "", float("nan"), float("inf"), True, None])
def test_invalid_override_names_the_variable(
    tmp_path: Path, dummy_model: types.ModuleType, value: Any
) -> None:
    directory = dummy_model.write_model_dir(tmp_path)
    with pytest.raises(ModelLoadError, match="UNUSABLE_THRESHOLD"):
        _load(directory, overrides={"unusable_threshold": value})


def test_unknown_or_repeated_override(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    directory = dummy_model.write_model_dir(tmp_path)
    with pytest.raises(ModelLoadError, match="unknown threshold override"):
        _load(directory, overrides={"REVIEW": 0.5})
    with pytest.raises(ModelLoadError, match="TYPE_THRESHOLD: given twice"):
        _load(directory, overrides={"TYPE_THRESHOLD": 0.5, "type_threshold": 0.6})


def test_empty_overrides(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    directory = dummy_model.write_model_dir(tmp_path)
    assert set(_load(directory, overrides={}).threshold_sources.values()) == {"decision.json"}


# ---------------------------------------------------------------- session checks


def test_wrong_type_output_shape(tmp_path: Path, dummy_model: types.ModuleType) -> None:  # CA-13
    model = dummy_model.build_model(type_probs=(0.7, 0.1, 0.1, 0.1))
    directory = dummy_model.write_model_dir(tmp_path, model=model)
    with pytest.raises(ModelLoadError, match=r"type_probs has shape \[1, 4\]"):
        _load(directory)


def test_wrong_grade_output_shape(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    model = dummy_model.build_model(grade_probs=(0.25, 0.25, 0.25, 0.25))
    directory = dummy_model.write_model_dir(tmp_path, model=model)
    with pytest.raises(ModelLoadError, match=r"grade_probs has shape \[1, 4\]"):
        _load(directory)


def test_wrong_input_name(tmp_path: Path, dummy_model: types.ModuleType) -> None:  # CA-13
    directory = dummy_model.write_model_dir(
        tmp_path, model=dummy_model.build_model(input_name="input")
    )
    with pytest.raises(ModelLoadError, match="input named 'image'"):
        _load(directory)


def test_wrong_output_name(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    directory = dummy_model.write_model_dir(
        tmp_path, model=dummy_model.build_model(grade_output="grade")
    )
    with pytest.raises(ModelLoadError, match="missing outputs"):
        _load(directory)


def test_not_an_onnx_file(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    directory = dummy_model.write_model_dir(tmp_path, model=b"not an onnx model")
    with pytest.raises(ModelLoadError, match=r"model\.onnx: onnxruntime cannot load it"):
        _load(directory)


def test_ir_version_too_new_for_the_locked_runtime(
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    model = dummy_model.build_model()
    model.ir_version = 99
    directory = dummy_model.write_model_dir(tmp_path, model=model.SerializeToString())
    with pytest.raises(ModelLoadError, match=r"model\.onnx"):
        _load(directory)


def test_warm_up_failure(tmp_path: Path, dummy_model: types.ModuleType) -> None:
    from onnx import TensorProto, helper

    model = dummy_model.build_model()
    # The graph now expects a float64 input: the float32 warm-up run fails.
    model.graph.input[0].type.tensor_type.elem_type = TensorProto.DOUBLE
    model.graph.node.insert(0, helper.make_node("Cast", ["image"], ["image_f"], to=1))
    model.graph.node[1].input[0] = "image_f"
    directory = dummy_model.write_model_dir(tmp_path, model=model.SerializeToString())
    with pytest.raises(ModelLoadError, match="warm-up inference failed"):
        _load(directory)


def test_the_hashed_bytes_are_the_ones_loaded(
    tmp_path: Path, dummy_model: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = dummy_model.write_model_dir(tmp_path)
    expected = (directory / "model.onnx").read_bytes()
    seen: list[Any] = []
    original = onnx_inferencer.onnxruntime.InferenceSession

    def _spy(model: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append((model, kwargs.get("providers")))
        return original(model, *args, **kwargs)

    monkeypatch.setattr(onnx_inferencer.onnxruntime, "InferenceSession", _spy)
    _load(directory)
    assert seen == [(expected, ["CPUExecutionProvider"])]


# ---------------------------------------------------------------- crop of preprocessing.json

CROP_256 = {
    "resize_shorter": 288,
    "crop": 256,
    "mean": [0.485, 0.456, 0.406],
    "std": [0.229, 0.224, 0.225],
}


def test_crop_incompatible_with_a_fixed_input_fails_at_load(  # CA-22
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    directory = dummy_model.write_model_dir(tmp_path, preprocessing=CROP_256)
    with pytest.raises(ModelLoadError, match=r"model\.onnx: warm-up inference failed"):
        _load(directory)


def test_warm_up_uses_the_crop_of_preprocessing(
    tmp_path: Path, dummy_model: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = dummy_model.build_model(input_shape=dummy_model.DYNAMIC_INPUT_SHAPE)
    directory = dummy_model.write_model_dir(tmp_path, model=model, preprocessing=CROP_256)
    shapes: list[tuple[int, ...]] = []
    original = onnx_inferencer.onnxruntime.InferenceSession

    class _Session:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._session = original(*args, **kwargs)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._session, name)

        def run(self, names: Any, feeds: dict[str, Any]) -> Any:
            shapes.append(tuple(feeds["image"].shape))
            return self._session.run(names, feeds)

    monkeypatch.setattr(onnx_inferencer.onnxruntime, "InferenceSession", _Session)
    _load(directory)
    assert shapes == [(1, 3, 256, 256)]


def test_dynamic_input_accepts_any_crop(  # CA-22
    tmp_path: Path, dummy_model: types.ModuleType, photo: Image.Image
) -> None:
    model = dummy_model.build_model(input_shape=dummy_model.DYNAMIC_INPUT_SHAPE)
    directory = dummy_model.write_model_dir(tmp_path, model=model, preprocessing=CROP_256)
    inferencer = _load(directory)
    result = inferencer.infer(photo)
    assert (result.object_type, result.grade) == (ObjectType.SCREW, Grade.GOOD)


def test_fixed_input_with_the_default_crop_still_loads(
    tmp_path: Path, dummy_model: types.ModuleType, photo: Image.Image
) -> None:
    params = {**CROP_256, "resize_shorter": 256, "crop": 224}
    directory = dummy_model.write_model_dir(tmp_path, preprocessing=params)
    assert _load(directory).infer(photo).object_type is ObjectType.SCREW


# ---------------------------------------------------------------- inference


def test_infer(tmp_path: Path, dummy_model: types.ModuleType, photo: Image.Image) -> None:  # CA-08
    inferencer = _load(dummy_model.write_model_dir(tmp_path))
    result = inferencer.infer(photo)
    assert result.object_type is ObjectType.SCREW
    assert result.grade is Grade.GOOD
    assert result.type_confidence == pytest.approx(0.9, abs=1e-6)
    assert result.grade_confidence == pytest.approx(0.8, abs=1e-6)
    assert result.grade_score == pytest.approx(1.25, abs=1e-6)
    assert result.needs_review is False
    assert isinstance(result.latency_ms, int) and result.latency_ms >= 0


def test_infer_unknown(tmp_path: Path, dummy_model: types.ModuleType, photo: Image.Image) -> None:
    directory = dummy_model.write_model_dir(tmp_path, type_probs=(0.1, 0.1, 0.8))
    result = _load(directory).infer(photo)
    assert result.object_type is ObjectType.UNKNOWN
    assert result.grade is None and result.grade_score is None and result.grade_confidence is None


def test_infer_invalid_output(
    tmp_path: Path, dummy_model: types.ModuleType, photo: Image.Image
) -> None:  # CA-14
    directory = dummy_model.write_model_dir(tmp_path, type_probs=(0.5, 0.5, 0.5))
    inferencer = _load(directory)  # the warm-up only checks the shapes
    with pytest.raises(InvalidModelOutputError):
        inferencer.infer(photo)


def test_infer_with_override(
    tmp_path: Path, dummy_model: types.ModuleType, photo: Image.Image
) -> None:
    directory = dummy_model.write_model_dir(tmp_path)
    result = _load(directory, overrides={"TYPE_THRESHOLD": 0.95}).infer(photo)
    assert result.object_type is ObjectType.UNKNOWN


def test_infer_latency_covers_preprocess_model_and_decision(
    tmp_path: Path,
    dummy_model: types.ModuleType,
    photo: Image.Image,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inferencer = _load(dummy_model.write_model_dir(tmp_path))
    ticks = iter([10.0, 10.2374])
    monkeypatch.setattr(onnx_inferencer.time, "perf_counter", lambda: next(ticks))
    assert inferencer.infer(photo).latency_ms == 237


def test_onnxruntime_error_is_an_inference_error(
    tmp_path: Path, dummy_model: types.ModuleType, photo: Image.Image
) -> None:
    inferencer = _load(dummy_model.write_model_dir(tmp_path))

    class _Broken:
        def run(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

    inferencer._session = _Broken()  # type: ignore[assignment]
    with pytest.raises(InferenceError, match="onnxruntime failed") as excinfo:
        inferencer.infer(photo)
    assert not isinstance(excinfo.value, InvalidModelOutputError)


def test_output_with_an_unexpected_batch_shape(
    tmp_path: Path, dummy_model: types.ModuleType, photo: Image.Image
) -> None:
    inferencer = _load(dummy_model.write_model_dir(tmp_path))

    class _Flat:
        def run(self, *args: Any, **kwargs: Any) -> Any:
            return [np.asarray([0.9, 0.05, 0.05]), np.asarray([[0.05, 0.8, 0.05, 0.05, 0.05]])]

    inferencer._session = _Flat()  # type: ignore[assignment]
    with pytest.raises(InvalidModelOutputError, match="type_probs has shape"):
        inferencer.infer(photo)


def test_preprocess_error_is_an_inference_error(
    tmp_path: Path, dummy_model: types.ModuleType
) -> None:
    inferencer = _load(dummy_model.write_model_dir(tmp_path))
    with pytest.raises(InferenceError, match="preprocessing failed"):
        inferencer.infer(Image.new("L", (300, 300)))


def test_infer_from_several_threads(
    tmp_path: Path, dummy_model: types.ModuleType, photo: Image.Image
) -> None:
    inferencer = _load(dummy_model.write_model_dir(tmp_path))
    expected = inferencer.infer(photo)
    barrier = threading.Barrier(4)

    def _run(_: int) -> Any:
        barrier.wait()
        return [inferencer.infer(photo) for _ in range(5)]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [item for batch in pool.map(_run, range(4)) for item in batch]
    assert len(results) == 20
    for result in results:
        assert (result.object_type, result.grade, result.grade_score) == (
            expected.object_type,
            expected.grade,
            expected.grade_score,
        )


def test_latency_p95(tmp_path: Path, dummy_model: types.ModuleType, photo: Image.Image) -> None:
    inferencer = _load(dummy_model.write_model_dir(tmp_path))
    latencies = sorted(inferencer.infer(photo).latency_ms for _ in range(50))
    assert latencies[int(np.ceil(0.95 * 50)) - 1] <= 300


def test_onnx_is_not_imported_by_production_code() -> None:
    root = Path(onnx_inferencer.__file__).parent
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import onnx\n" not in text and "from onnx " not in text, path
    assert os.sep + "tests" + os.sep not in str(root)
