import json
from pathlib import Path

import pytest

from qc_preprocess import PreprocessParams


def test_defaults() -> None:
    p = PreprocessParams()
    assert (p.resize_shorter, p.crop, p.mean, p.std) == (
        256,
        224,
        (0.485, 0.456, 0.406),
        (0.229, 0.224, 0.225),
    )


def test_frozen() -> None:
    with pytest.raises(AttributeError):
        PreprocessParams().crop = 100  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"resize_shorter": 200, "crop": 224},
        {"resize_shorter": 0, "crop": 0},
        {"crop": 0},
        {"crop": -1},
        {"resize_shorter": 256.0},
        {"crop": True},
        {"crop": "224"},
        {"std": (0.2, 0.0, 0.2)},
        {"std": (0.2, -0.1, 0.2)},
        {"std": (0.2, 0.2)},
        {"mean": (0.5, 0.5, 0.5, 0.5)},
        {"mean": "abc"},
        {"mean": (0.5, float("nan"), 0.5)},
        {"std": (0.2, float("inf"), 0.2)},
        {"mean": (0.5, "0.5", 0.5)},
    ],
)
def test_invalid_params(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        PreprocessParams(**kwargs)


def test_crop_equal_to_resize_is_valid() -> None:
    assert PreprocessParams(resize_shorter=224, crop=224).crop == 224


def test_sequences_normalized_to_float_tuples() -> None:
    p = PreprocessParams(mean=[0, 0.5, 1], std=[1, 1, 1])  # type: ignore[arg-type]
    assert p.mean == (0.0, 0.5, 1.0) and isinstance(p.mean, tuple)
    assert p == PreprocessParams(mean=(0.0, 0.5, 1.0), std=(1.0, 1.0, 1.0))


def test_json_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "preprocessing.json"
    for params in (PreprocessParams(), PreprocessParams(300, 256, (0.1, 0.2, 0.3), (1, 2, 3))):
        params.to_json(path)
        assert PreprocessParams.from_json(path) == params


def test_json_format(tmp_path: Path) -> None:
    path = tmp_path / "preprocessing.json"
    PreprocessParams().to_json(path)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "resize_shorter": 256,
        "crop": 224,
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
    }


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "data",
    [
        {"resize_shorter": 256, "mean": [0.5] * 3, "std": [0.5] * 3},
        {"resize_shorter": 256, "crop": 224, "mean": [0.5] * 3, "std": [0.5] * 3, "resize": 1},
        {"resize_shorter": 256, "crop": 224, "mean": [0.5] * 3, "std": [0.5, 0.5]},
        [256, 224],
    ],
)
def test_from_json_invalid(tmp_path: Path, data: object) -> None:
    with pytest.raises(ValueError):
        PreprocessParams.from_json(_write(tmp_path / "p.json", data))


def test_from_json_not_json(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        PreprocessParams.from_json(path)
