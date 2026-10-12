"""Acceptance tests for SPEC-002 (qc-preprocess 0.1.0).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-01 (qc-preprocess part) and CA-19 to CA-26. Tests named
``test_extra_*`` cover requirements of SPEC-002 section 4.5 that no CA spells out.
All images are generated in memory; no binary file is committed.
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
import io
import json
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

import qc_preprocess
from qc_preprocess import InvalidImageError, PreprocessParams, load_image, preprocess

pytestmark = pytest.mark.acceptance

MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)


# --------------------------------------------------------------------------- helpers


def encode(img: Image.Image, fmt: str, **kwargs: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def formula_image(width: int = 64, height: int = 48) -> Image.Image:
    """Deterministic RGB test pattern (fixed formula, no randomness)."""
    y, x = np.mgrid[0:height, 0:width]
    arr = np.stack(
        [(x * 7 + y * 3) % 256, (x * x + 5 * y) % 256, (x * y + 11) % 256], axis=-1
    ).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def noise_image(width: int, height: int) -> Image.Image:
    rng = np.random.default_rng(1234)
    return Image.fromarray(rng.integers(0, 256, (height, width, 3), dtype=np.uint8), "RGB")


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def big_png(width: int, height: int) -> bytes:
    """A complete, valid 1-bit grayscale PNG (small on disk, huge in pixels)."""
    row = b"\x00" + b"\x00" * ((width + 7) // 8)
    idat = zlib.compress(row * height, 9)
    ihdr = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _requirement_names(dist: str) -> set[str]:
    names = set()
    for req in importlib.metadata.requires(dist) or []:
        if "extra ==" in req:
            continue
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
        assert match, req
        names.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
    return names


# --------------------------------------------------------------------------- CA-01


def test_ca01_preprocess_version() -> None:
    assert qc_preprocess.__version__ == "0.1.0"
    assert importlib.metadata.version("qc-preprocess") == "0.1.0"


# --------------------------------------------------------------------------- CA-19


def test_ca19_params_defaults_validation_and_json(tmp_path: Path) -> None:
    p = PreprocessParams()
    assert (p.resize_shorter, p.crop, tuple(p.mean), tuple(p.std)) == (256, 224, MEAN, STD)
    assert dataclasses.is_dataclass(p)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.crop = 100  # type: ignore[misc]

    with pytest.raises(ValueError):
        PreprocessParams(resize_shorter=200, crop=224)
    with pytest.raises(ValueError):
        PreprocessParams(std=(0.2, 0.0, 0.2))

    custom = PreprocessParams(resize_shorter=300, crop=200, mean=(0.1, 0.2, 0.3), std=MEAN)
    for params in (p, custom):
        path = tmp_path / f"pp_{params.crop}.json"
        params.to_json(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data) == {"resize_shorter", "crop", "mean", "std"}
        assert PreprocessParams.from_json(path) == params

    no_crop = tmp_path / "no_crop.json"
    no_crop.write_text(json.dumps({"resize_shorter": 256, "mean": MEAN, "std": STD}))
    with pytest.raises(ValueError):
        PreprocessParams.from_json(no_crop)

    extra = tmp_path / "extra.json"
    extra.write_text(
        json.dumps({"resize_shorter": 256, "crop": 224, "mean": MEAN, "std": STD, "resize": 1})
    )
    with pytest.raises(ValueError):
        PreprocessParams.from_json(extra)


# --------------------------------------------------------------------------- CA-20


def test_ca20_solid_color_values_shape_dtype_contiguity() -> None:
    img = Image.new("RGB", (300, 400), (255, 0, 51))
    out = preprocess(img)
    assert isinstance(out, np.ndarray)
    assert out.shape == (1, 3, 224, 224)
    assert out.dtype == np.float32
    assert out.flags["C_CONTIGUOUS"]
    expected = [2.2489083, -2.0357143, -0.9155556]
    for c, value in enumerate(expected):
        assert np.allclose(out[0, c], value, atol=0.02, rtol=0), (
            c,
            out[0, c].min(),
            out[0, c].max(),
        )


# --------------------------------------------------------------------------- CA-21


def test_ca21_exact_center_crop_without_resampling() -> None:
    arr = np.zeros((4, 4, 3), dtype=np.uint8)
    for y in range(4):
        for x in range(4):
            v = 16 * (4 * y + x)
            arr[y, x] = (v, 255 - v, 128)
    img = Image.fromarray(arr, mode="RGB")
    params = PreprocessParams(resize_shorter=4, crop=2, mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5))
    out = preprocess(img, params)
    assert out.shape == (1, 3, 2, 2)
    assert out.dtype == np.float32
    expected_r = np.array(
        [[80 / 255 * 2 - 1, 96 / 255 * 2 - 1], [144 / 255 * 2 - 1, 160 / 255 * 2 - 1]]
    )
    np.testing.assert_allclose(out[0, 0], expected_r, atol=1e-6, rtol=0)
    # The same crop origin for the other channels.
    expected_g = (255 - np.array([[80, 96], [144, 160]])) / 255 * 2 - 1
    np.testing.assert_allclose(out[0, 1], expected_g, atol=1e-6, rtol=0)
    np.testing.assert_allclose(out[0, 2], np.full((2, 2), 128 / 255 * 2 - 1), atol=1e-6, rtol=0)


# --------------------------------------------------------------------------- CA-22


def test_ca22_bit_identical_determinism() -> None:
    img = formula_image(64, 48)
    assert img.size == (64, 48)
    a = preprocess(img)
    b = preprocess(img)
    assert a.tobytes() == b.tobytes()

    png = encode(img, "PNG")
    c = preprocess(load_image(png))
    d = preprocess(load_image(png))
    assert c.tobytes() == d.tobytes()
    # PNG is lossless: the decoded image is the same, so is the tensor.
    assert c.tobytes() == a.tobytes()

    # Same with a non-default parameter set and a fresh copy of the image.
    params = PreprocessParams(resize_shorter=100, crop=96)
    assert preprocess(img.copy(), params).tobytes() == preprocess(img, params).tobytes()


# --------------------------------------------------------------------------- CA-23


def test_ca23_exif_orientation_and_modes_to_rgb() -> None:
    src = Image.new("RGB", (40, 20), (200, 10, 10))
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation = 6 (rotate 90 CW)
    jpeg = encode(src, "JPEG", exif=exif.tobytes(), quality=95)
    with Image.open(io.BytesIO(jpeg)) as check:
        assert check.size == (40, 20)
        assert check.getexif().get(0x0112) == 6

    out = load_image(jpeg)
    assert isinstance(out, Image.Image)
    assert out.size == (20, 40)
    assert out.mode == "RGB"

    rgba = encode(Image.new("RGBA", (10, 8), (1, 2, 3, 128)), "PNG")
    gray = encode(Image.new("L", (10, 8), 77), "PNG")
    for data in (rgba, gray):
        img = load_image(data)
        assert img.mode == "RGB"
        assert img.size == (10, 8)
    assert load_image(gray).getpixel((0, 0)) == (77, 77, 77)


# --------------------------------------------------------------------------- CA-24


def _invalid_inputs() -> list[tuple[str, bytes]]:
    jpeg = encode(noise_image(200, 150), "JPEG", quality=90)
    gif = encode(Image.new("RGB", (10, 10), (0, 255, 0)), "GIF")
    return [
        ("empty", b""),
        ("text", b"not an image"),
        ("truncated-jpeg", jpeg[: len(jpeg) // 2]),
        ("gif", gif),
        ("png-8000x8000", big_png(8000, 8000)),
    ]


@pytest.mark.parametrize(
    ("name", "data"), _invalid_inputs(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_ca24_invalid_images_rejected(name: str, data: bytes) -> None:
    if name == "gif":
        with Image.open(io.BytesIO(data)) as check:
            assert check.format == "GIF" and check.size == (10, 10)
    if name == "png-8000x8000":
        with Image.open(io.BytesIO(data)) as check:
            assert check.format == "PNG" and check.size == (8000, 8000)
    with pytest.raises(InvalidImageError):
        load_image(data)


def test_ca24_missing_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        load_image(Path("nao_existe.jpg"))


def test_ca24_invalid_image_error_is_value_error() -> None:
    assert issubclass(InvalidImageError, ValueError)


# --------------------------------------------------------------------------- CA-25


@pytest.mark.parametrize("mode", ["L", "RGBA", "P", "CMYK", "1"])
def test_ca25_preprocess_requires_rgb(mode: str) -> None:
    img = Image.new(mode, (32, 32))
    with pytest.raises(ValueError):
        preprocess(img)


# --------------------------------------------------------------------------- CA-26


def test_ca26_no_torch_and_only_numpy_pillow() -> None:
    code = (
        "import sys\n"
        "import qc_preprocess, qc_contracts\n"
        "bad = sorted(m for m in ('torch', 'torchvision', 'timm') if m in sys.modules)\n"
        "print(','.join(bad) or 'CLEAN')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "CLEAN"
    assert _requirement_names("qc-preprocess") == {"numpy", "pillow"}


# --------------------------------------------------------------------------- extras
# Requirements from SPEC-002 section 4.5 not covered by a specific CA.


def test_extra_preprocess_module_layout() -> None:
    import qc_preprocess.errors as errors
    import qc_preprocess.image as image
    import qc_preprocess.params as params
    import qc_preprocess.transform as transform

    assert params.PreprocessParams is PreprocessParams
    assert errors.InvalidImageError is InvalidImageError
    assert image.load_image is load_image
    assert transform.preprocess is preprocess


@pytest.mark.parametrize(
    "kwargs",
    [
        {"resize_shorter": 0},
        {"resize_shorter": -1},
        {"crop": 0},
        {"crop": -5},
        {"mean": (0.1, 0.2)},
        {"std": (0.1, 0.2, 0.3, 0.4)},
        {"std": (0.2, -0.1, 0.2)},
    ],
)
def test_extra_params_validation(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        PreprocessParams(**kwargs)


def test_extra_params_crop_equal_resize_accepted() -> None:
    p = PreprocessParams(resize_shorter=224, crop=224)
    out = preprocess(Image.new("RGB", (224, 300), (0, 0, 0)), p)
    assert out.shape == (1, 3, 224, 224)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json",
        "[]",
        '{"resize_shorter": 256, "crop": 224, "mean": [1, 2], "std": [1, 1, 1]}',
    ],
)
def test_extra_from_json_malformed(tmp_path: Path, content: str) -> None:
    path = tmp_path / "pp.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        PreprocessParams.from_json(path)


def test_extra_to_json_values(tmp_path: Path) -> None:
    path = tmp_path / "preprocessing.json"
    PreprocessParams().to_json(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"resize_shorter": 256, "crop": 224, "mean": list(MEAN), "std": list(STD)}


def test_extra_resize_truncation_and_center_crop_origin() -> None:
    # 300x401 -> shorter 300 -> 256; longer = int(401*256/300) = 342 (truncated).
    # Expected tensor = manual Pillow pipeline from the SPEC steps.
    img = formula_image(300, 401)
    resized = img.resize((256, int(401 * 256 / 300)), Image.Resampling.BILINEAR)
    assert resized.size == (256, 342)
    left, top = (256 - 224) // 2, (342 - 224) // 2
    crop = np.asarray(resized.crop((left, top, left + 224, top + 224)), dtype=np.float32)
    crop = crop / np.float32(255)
    crop = (crop - np.asarray(MEAN, dtype=np.float32)) / np.asarray(STD, dtype=np.float32)
    expected = crop.transpose(2, 0, 1)[None]
    out = preprocess(img)
    np.testing.assert_allclose(out, expected, atol=1e-6, rtol=0)


def test_extra_landscape_odd_crop_origin_without_resample() -> None:
    # Already at target size (shorter == resize_shorter): no resampling, crop origin floor.
    arr = np.arange(5 * 7 * 3, dtype=np.uint8).reshape(5, 7, 3)
    img = Image.fromarray(arr, "RGB")  # 7x5
    params = PreprocessParams(resize_shorter=5, crop=2, mean=(0.0, 0.0, 0.0), std=(1.0, 1.0, 1.0))
    out = preprocess(img, params)
    x0, y0 = (7 - 2) // 2, (5 - 2) // 2
    expected = arr[y0 : y0 + 2, x0 : x0 + 2].astype(np.float32) / np.float32(255)
    np.testing.assert_allclose(out[0], expected.transpose(2, 0, 1), atol=1e-7, rtol=0)


def test_extra_preprocess_does_not_mutate_input() -> None:
    img = formula_image(64, 48)
    before = img.tobytes()
    preprocess(img)
    assert img.tobytes() == before and img.size == (64, 48) and img.mode == "RGB"


def test_extra_load_image_from_path_and_content_not_extension(tmp_path: Path) -> None:
    png = encode(formula_image(20, 10), "PNG")
    path = tmp_path / "photo.jpg"  # wrong extension on purpose
    path.write_bytes(png)
    img = load_image(path)
    assert img.size == (20, 10) and img.mode == "RGB"

    gif_named_png = tmp_path / "fake.png"
    gif_named_png.write_bytes(encode(Image.new("RGB", (10, 10)), "GIF"))
    with pytest.raises(InvalidImageError):
        load_image(gif_named_png)

    text_named_jpg = tmp_path / "fake.jpg"
    text_named_jpg.write_bytes(b"hello")
    with pytest.raises(InvalidImageError):
        load_image(text_named_jpg)


@pytest.mark.parametrize("fmt", ["BMP", "WEBP", "TIFF", "ICO"])
def test_extra_other_formats_rejected(fmt: str) -> None:
    data = encode(Image.new("RGB", (16, 16), (9, 9, 9)), fmt)
    with pytest.raises(InvalidImageError):
        load_image(data)


def test_extra_truncated_png_rejected() -> None:
    png = encode(noise_image(120, 90), "PNG")
    with pytest.raises(InvalidImageError):
        load_image(png[: len(png) // 2])


def test_extra_pixel_limit_boundary() -> None:
    # 40 000 000 exactly is allowed ("mais de 40 000 000" is rejected).
    ok = big_png(8000, 5000)
    img = load_image(ok)
    assert img.size == (8000, 5000) and img.mode == "RGB"
    with pytest.raises(InvalidImageError):
        load_image(big_png(8000, 5001))


def test_extra_decompression_bomb_rejected() -> None:
    # 1 x 200 000 000 pixels: above Pillow's 2x MAX_IMAGE_PIXELS (DecompressionBombError).
    with pytest.raises(InvalidImageError):
        load_image(big_png(20000, 10000))


def test_extra_jpeg_cmyk_and_palette_png_to_rgb() -> None:
    cmyk = encode(Image.new("CMYK", (12, 6), (0, 0, 0, 0)), "JPEG")
    pal = encode(Image.new("RGB", (12, 6), (5, 6, 7)).convert("P"), "PNG")
    for data in (cmyk, pal):
        img = load_image(data)
        assert img.mode == "RGB" and img.size == (12, 6)


def test_extra_loaded_image_is_fully_decoded_and_independent() -> None:
    png = encode(formula_image(30, 20), "PNG")
    buf = bytearray(png)
    img = load_image(bytes(buf))
    buf[:] = b"\x00" * len(buf)
    assert np.asarray(img).shape == (20, 30, 3)


def test_extra_bytes_and_path_give_same_tensor(tmp_path: Path) -> None:
    jpeg = encode(formula_image(64, 48), "JPEG", quality=90)
    path = tmp_path / "x.jpeg"
    path.write_bytes(jpeg)
    a = preprocess(load_image(jpeg))
    b = preprocess(load_image(path))
    assert a.tobytes() == b.tobytes()


def test_extra_default_params_argument() -> None:
    img = formula_image(64, 48)
    assert preprocess(img).tobytes() == preprocess(img, PreprocessParams()).tobytes()
