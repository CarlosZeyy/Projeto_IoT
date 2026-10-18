"""Author tests for qc_ml.augment (SPEC-011 section 4.5)."""

from __future__ import annotations

import numpy as np
from PIL import Image

from qc_ml import augment
from qc_ml.augment import border_median, train_transform


def _image() -> Image.Image:
    rng = np.random.default_rng(0)
    pixels = rng.integers(0, 256, size=(200, 300, 3), dtype=np.uint8)
    return Image.fromarray(pixels)


def test_deterministic_size_and_mode() -> None:
    img = _image()
    a = train_transform(img, np.random.default_rng(1))
    b = train_transform(img, np.random.default_rng(1))
    assert a.size == (256, 256) and a.mode == "RGB"
    assert np.array_equal(np.asarray(a), np.asarray(b))
    c = train_transform(img, np.random.default_rng(2))
    assert not np.array_equal(np.asarray(a), np.asarray(c))


def test_input_is_not_modified() -> None:
    img = _image()
    before = np.asarray(img).copy()
    train_transform(img, np.random.default_rng(3))
    assert np.array_equal(before, np.asarray(img))


def test_rotation_fill_is_the_border_median_never_black() -> None:
    img = Image.new("RGB", (100, 100), (230, 225, 220))
    assert border_median(img) == (230, 225, 220)
    for seed in range(20):
        out = np.asarray(augment.random_rotation(img, np.random.default_rng(seed)))
        assert out.min() >= 200  # nothing black came from the corners


def test_grayscale_input_becomes_rgb() -> None:
    out = train_transform(Image.new("L", (300, 200), 128), np.random.default_rng(0))
    assert out.mode == "RGB" and out.size == (256, 256)


def test_crop_fallback_for_extreme_aspect() -> None:
    img = Image.new("RGB", (1000, 100), (10, 20, 30))
    out = augment.random_resized_crop(img, np.random.default_rng(0))
    assert out.size == (256, 256)


def test_hue_shift_is_small() -> None:
    orange = Image.new("RGB", (32, 32), (196, 98, 34))
    for factor in (-augment.HUE, augment.HUE):
        out = np.asarray(augment.adjust_hue(orange, factor)).astype(int)
        r, g, b = out[0, 0]
        assert r > g > b  # still orange: the jitter never "erases" rust


def test_parameters_are_the_skill_values() -> None:
    assert augment.ROTATION_DEGREES == 20
    assert augment.CROP_SCALE == (0.7, 1.0)
    assert (augment.BRIGHTNESS, augment.CONTRAST, augment.SATURATION, augment.HUE) == (
        0.3,
        0.3,
        0.2,
        0.02,
    )
    assert augment.BLUR_PROBABILITY == 0.2 and augment.BLUR_SIGMA == (0.1, 1.0)
