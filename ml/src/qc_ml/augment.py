"""Training augmentations with Pillow + numpy only (SPEC-011 section 4.5; skill ml-pipeline §3).

Applied to the training images only, **before** the shared ``qc_preprocess.preprocess``.
Validation, test and inference never go through this module. Nothing here may change the grade
(for example, no strong hue shift that would "erase" rust), so the hue jitter stays at 0.02.

No torch here.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

OUTPUT_SIZE = 256
ROTATION_DEGREES = 20.0
CROP_SCALE = (0.7, 1.0)
CROP_RATIO = (3 / 4, 4 / 3)
CROP_ATTEMPTS = 10
FLIP_PROBABILITY = 0.5
BRIGHTNESS = 0.3
CONTRAST = 0.3
SATURATION = 0.2
HUE = 0.02
BLUR_PROBABILITY = 0.2
BLUR_SIGMA = (0.1, 1.0)


def border_median(img: Image.Image) -> tuple[int, int, int]:
    """Median RGB of the pixels on the four edges of the image."""
    x = np.asarray(img.convert("RGB"))
    border = np.concatenate([x[0, :, :], x[-1, :, :], x[:, 0, :], x[:, -1, :]], axis=0)
    median = np.median(border, axis=0)
    return (int(round(median[0])), int(round(median[1])), int(round(median[2])))


def random_rotation(img: Image.Image, rng: np.random.Generator) -> Image.Image:
    """Uniform rotation in ±20°, filled with the border median (never black)."""
    angle = float(rng.uniform(-ROTATION_DEGREES, ROTATION_DEGREES))
    return img.rotate(
        angle, resample=Image.Resampling.BILINEAR, expand=False, fillcolor=border_median(img)
    )


def random_resized_crop(img: Image.Image, rng: np.random.Generator) -> Image.Image:
    """Crop with area scale 0.7-1.0 and aspect ratio 3/4-4/3, resized to 256x256 (bilinear).

    Same sampling as torchvision's ``RandomResizedCrop``: up to 10 attempts, then a central crop
    with the aspect ratio clamped to the allowed range.
    """
    width, height = img.size
    area = width * height
    log_ratio = (math.log(CROP_RATIO[0]), math.log(CROP_RATIO[1]))
    box: tuple[int, int, int, int] | None = None
    for _ in range(CROP_ATTEMPTS):
        target_area = area * float(rng.uniform(*CROP_SCALE))
        aspect = math.exp(float(rng.uniform(*log_ratio)))
        w = int(round(math.sqrt(target_area * aspect)))
        h = int(round(math.sqrt(target_area / aspect)))
        if 0 < w <= width and 0 < h <= height:
            top = int(rng.integers(0, height - h + 1))
            left = int(rng.integers(0, width - w + 1))
            box = (left, top, left + w, top + h)
            break
    if box is None:
        in_ratio = width / height
        if in_ratio < CROP_RATIO[0]:
            w, h = width, int(round(width / CROP_RATIO[0]))
        elif in_ratio > CROP_RATIO[1]:
            h, w = height, int(round(height * CROP_RATIO[1]))
        else:
            w, h = width, height
        left, top = (width - w) // 2, (height - h) // 2
        box = (left, top, left + w, top + h)
    return img.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.BILINEAR, box=box)


def adjust_hue(img: Image.Image, factor: float) -> Image.Image:
    """Shift the hue by ``factor`` of a full turn (``factor`` in [-0.5, 0.5])."""
    h, s, v = img.convert("HSV").split()
    shift = int(round(factor * 255))
    hue = ((np.asarray(h, dtype=np.int16) + shift) % 256).astype(np.uint8)
    return Image.merge("HSV", (Image.fromarray(hue), s, v)).convert("RGB")


def color_jitter(img: Image.Image, rng: np.random.Generator) -> Image.Image:
    """Brightness and contrast ±0.3, saturation ±0.2, hue ±0.02, in a random order."""
    factors = (
        float(rng.uniform(1 - BRIGHTNESS, 1 + BRIGHTNESS)),
        float(rng.uniform(1 - CONTRAST, 1 + CONTRAST)),
        float(rng.uniform(1 - SATURATION, 1 + SATURATION)),
        float(rng.uniform(-HUE, HUE)),
    )
    for op in rng.permutation(4):
        if op == 0:
            img = ImageEnhance.Brightness(img).enhance(factors[0])
        elif op == 1:
            img = ImageEnhance.Contrast(img).enhance(factors[1])
        elif op == 2:
            img = ImageEnhance.Color(img).enhance(factors[2])
        else:
            img = adjust_hue(img, factors[3])
    return img


def train_transform(img: Image.Image, rng: np.random.Generator) -> Image.Image:
    """Training augmentation; returns a 256x256 ``RGB`` image.

    In order: rotation ±20° (border-median fill); ``RandomResizedCrop`` to 256x256 (scale
    0.7-1.0, ratio 3/4-4/3); horizontal and vertical flips (p = 0.5 each); ``ColorJitter``
    (brightness and contrast 0.3, saturation 0.2, hue 0.02); Gaussian blur with p = 0.2 and sigma
    0.1-1.0. The same input and the same ``rng`` state give the same output.
    """
    img = img.convert("RGB")
    img = random_rotation(img, rng)
    img = random_resized_crop(img, rng)
    if rng.random() < FLIP_PROBABILITY:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if rng.random() < FLIP_PROBABILITY:
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    img = color_jitter(img, rng)
    if rng.random() < BLUR_PROBABILITY:
        # Pillow's GaussianBlur radius is the standard deviation of the kernel.
        img = img.filter(ImageFilter.GaussianBlur(radius=float(rng.uniform(*BLUR_SIGMA))))
    return img.convert("RGB")
