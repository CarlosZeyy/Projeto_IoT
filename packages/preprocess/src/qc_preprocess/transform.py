"""Deterministic preprocessing: RGB image -> float32[1, 3, crop, crop] (architecture.md 6.2)."""

import numpy as np
from PIL import Image

from qc_preprocess.params import PreprocessParams

_DEFAULT_PARAMS = PreprocessParams()


def preprocess(img: Image.Image, params: PreprocessParams = _DEFAULT_PARAMS) -> np.ndarray:
    """Resize the shorter side (bilinear), center-crop, scale to [0, 1] and normalize.

    The same input and parameters give a bit-identical output with the Pillow version locked in
    ``uv.lock``. Training and the edge both call this function (ADR-004).

    Raises:
        ValueError: the image is not in ``RGB`` mode or is empty.
    """
    if not isinstance(img, Image.Image):
        raise TypeError(f"img must be a PIL.Image.Image, got {type(img).__name__}")
    if img.mode != "RGB":
        raise ValueError(f"image mode must be 'RGB', got {img.mode!r}")
    width, height = img.size
    if width == 0 or height == 0:
        raise ValueError("image is empty")

    target = params.resize_shorter
    if width <= height:
        size = (target, int(height * target / width))
    else:
        size = (int(width * target / height), target)
    if size != img.size:
        img = img.resize(size, Image.Resampling.BILINEAR)

    width, height = img.size
    left = (width - params.crop) // 2
    top = (height - params.crop) // 2
    img = img.crop((left, top, left + params.crop, top + params.crop))

    x = np.asarray(img, dtype=np.float32) / np.float32(255.0)
    mean = np.asarray(params.mean, dtype=np.float32)
    std = np.asarray(params.std, dtype=np.float32)
    x = (x - mean) / std
    return np.ascontiguousarray(x.transpose(2, 0, 1)[np.newaxis, ...], dtype=np.float32)
