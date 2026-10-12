"""Acceptance tests for SPEC-023 (qc-preprocess 0.2.0: aspect ratio and truncated-image flag).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-01 (qc-preprocess part), CA-02 (qc-preprocess part) and CA-07 to
CA-12. Tests named ``test_extra_*`` are exploratory edge cases around SPEC-023 section 4.2
that no CA spells out. All images are generated in memory; no binary file is committed.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import io
import os
import struct
import subprocess
import sys
import threading
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageFile

import qc_preprocess
import qc_preprocess.image
from qc_preprocess import InvalidImageError, PreprocessParams, load_image, preprocess

pytestmark = pytest.mark.acceptance

PKG_ROOT = Path(__file__).resolve().parents[2]  # packages/preprocess
ROOT = PKG_ROOT.parents[1]  # repository root

MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)


# --------------------------------------------------------------------------- helpers


def encode(img: Image.Image, fmt: str, **kwargs: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def formula_image(width: int, height: int) -> Image.Image:
    """Deterministic RGB test pattern (fixed formula, no randomness)."""
    y, x = np.mgrid[0:height, 0:width]
    arr = np.stack(
        [(x * 7 + y * 3) % 256, (x * x + 5 * y) % 256, (x * y + 11) % 256], axis=-1
    ).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def noise_jpeg(width: int, height: int) -> bytes:
    rng = np.random.default_rng(2023)
    img = Image.fromarray(rng.integers(0, 256, (height, width, 3), dtype=np.uint8), "RGB")
    return encode(img, "JPEG", quality=90)


def rgb_png(width: int, height: int) -> bytes:
    return encode(formula_image(width, height), "PNG")


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


def header_only_png(width: int, height: int) -> bytes:
    """PNG signature + valid IHDR (8-bit RGB) + IEND, without any IDAT chunk."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IEND", b"")


def exif_jpeg(width: int, height: int, orientation: int) -> bytes:
    exif = Image.Exif()
    exif[0x0112] = orientation
    return encode(Image.new("RGB", (width, height), (200, 10, 10)), "JPEG", exif=exif.tobytes())


def header_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        return img.size


# --------------------------------------------------------------------------- CA-01


def test_ca01_preprocess_version() -> None:
    assert qc_preprocess.__version__ == "0.2.0"
    assert importlib.metadata.version("qc-preprocess") == "0.2.0"


def test_ca01_both_packages_version() -> None:
    import qc_contracts

    assert qc_contracts.__version__ == "0.2.0"
    assert importlib.metadata.version("qc-contracts") == "0.2.0"


# --------------------------------------------------------------------------- CA-02


def test_ca02_aspect_ratio_and_pixel_constants() -> None:
    assert qc_preprocess.MAX_ASPECT_RATIO == qc_preprocess.image.MAX_ASPECT_RATIO == 10
    assert type(qc_preprocess.MAX_ASPECT_RATIO) is int
    assert qc_preprocess.MAX_PIXELS == 40_000_000


# --------------------------------------------------------------------------- CA-07


@pytest.mark.parametrize(
    ("data", "size"),
    [
        (rgb_png(100, 1000), (100, 1000)),
        (rgb_png(1000, 100), (1000, 100)),
        (encode(formula_image(40, 400), "JPEG", quality=90), (40, 400)),
    ],
    ids=["png-100x1000", "png-1000x100", "jpeg-40x400"],
)
def test_ca07_exact_10_to_1_accepted(data: bytes, size: tuple[int, int]) -> None:
    assert header_size(data) == size
    img = load_image(data)
    assert img.mode == "RGB"
    assert img.size == size


def test_ca07_preprocess_of_accepted_strip() -> None:
    out = preprocess(load_image(rgb_png(100, 1000)))
    assert out.shape == (1, 3, 224, 224)
    assert out.dtype == np.float32


# --------------------------------------------------------------------------- CA-08


@pytest.mark.parametrize(
    ("width", "height"),
    [(100, 1001), (1001, 100), (100, 400_000), (20, 2_000_000)],
    ids=["100x1001", "1001x100", "100x400000", "20x2000000"],
)
def test_ca08_above_10_to_1_rejected(width: int, height: int) -> None:
    if width * height > 1_000_000:
        data = big_png(width, height)
        assert width * height == 40_000_000  # exactly MAX_PIXELS, so only the ratio rejects
    else:
        data = rgb_png(width, height)
    assert header_size(data) == (width, height)
    with pytest.raises(InvalidImageError, match="aspect ratio"):
        load_image(data)


# --------------------------------------------------------------------------- CA-09


def test_ca09_ratio_comes_from_header_before_decoding() -> None:
    bad = header_only_png(100, 1001)
    assert header_size(bad) == (100, 1001)
    with pytest.raises(InvalidImageError, match="aspect ratio"):
        load_image(bad)

    ok_ratio = header_only_png(100, 1000)
    assert header_size(ok_ratio) == (100, 1000)
    with pytest.raises(InvalidImageError) as exc:
        load_image(ok_ratio)
    assert "aspect ratio" not in str(exc.value)


# --------------------------------------------------------------------------- CA-10


def test_ca10_exif_rotation_keeps_ratio_rule() -> None:
    ok = exif_jpeg(400, 40, 6)
    assert header_size(ok) == (400, 40)
    img = load_image(ok)
    assert img.size == (40, 400)
    assert img.mode == "RGB"

    bad = exif_jpeg(401, 40, 6)
    assert header_size(bad) == (401, 40)
    with pytest.raises(InvalidImageError, match="aspect ratio"):
        load_image(bad)


# --------------------------------------------------------------------------- CA-11


def test_ca11_truncated_images_flag_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    valid = noise_jpeg(64, 48)
    truncated = valid[: len(valid) // 2]
    assert load_image(valid).size == (64, 48)  # sanity: flag off, valid image accepted

    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    for arg in (valid, truncated, Path("nao_existe.jpg")):
        with pytest.raises(RuntimeError, match="LOAD_TRUNCATED_IMAGES") as exc:
            load_image(arg)
        assert not isinstance(exc.value, ValueError)
        assert not isinstance(exc.value, InvalidImageError)
        assert ImageFile.LOAD_TRUNCATED_IMAGES is True  # not changed by the function

    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    img = load_image(valid)
    assert img.size == (64, 48) and img.mode == "RGB"
    with pytest.raises(InvalidImageError):
        load_image(truncated)


# --------------------------------------------------------------------------- CA-12


def test_ca12_spec002_acceptance_suites_still_pass() -> None:
    env = dict(os.environ)
    for key in ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST", "PYTEST_PLUGINS"):
        env.pop(key, None)
    files = [
        "packages/contracts/tests/acceptance/test_spec_002.py",
        "packages/preprocess/tests/acceptance/test_spec_002.py",
    ]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *files],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out[-4000:]
    assert " passed" in out and "failed" not in out and "error" not in out.lower(), out[-4000:]
    for name in ("ca18", "ca20", "ca21", "ca22", "ca24", "ca26"):
        # Each named CA of SPEC-002 is present in those files (it really ran).
        text = "\n".join((ROOT / f).read_text(encoding="utf-8") for f in files)
        assert f"def test_{name}_" in text, name


# --------------------------------------------------------------------------- extras
# Exploratory edge cases around SPEC-023 section 4.2.


@pytest.mark.parametrize(
    ("width", "height", "accepted"),
    [
        (1, 1, True),
        (1, 10, True),
        (10, 1, True),
        (1, 11, False),
        (11, 1, False),
        (3, 30, True),
        (3, 31, False),
        (7, 70, True),
        (7, 71, False),
    ],
)
def test_extra_integer_boundaries(width: int, height: int, accepted: bool) -> None:
    data = rgb_png(width, height)
    if accepted:
        assert load_image(data).size == (width, height)
    else:
        with pytest.raises(InvalidImageError, match="aspect ratio"):
            load_image(data)


def test_extra_ratio_rule_applies_to_path_input(tmp_path: Path) -> None:
    path = tmp_path / "strip.png"
    path.write_bytes(rgb_png(5, 51))
    with pytest.raises(InvalidImageError, match="aspect ratio"):
        load_image(path)
    path.write_bytes(rgb_png(5, 50))
    assert load_image(path).size == (5, 50)


def test_extra_header_only_extreme_is_fast_and_rejected_by_ratio() -> None:
    # 20 x 2 000 000 header with no pixel data: the ratio rule fires without decoding.
    with pytest.raises(InvalidImageError, match="aspect ratio"):
        load_image(header_only_png(20, 2_000_000))
    with pytest.raises(InvalidImageError, match="aspect ratio"):
        load_image(header_only_png(2_000_000, 20))


def test_extra_pixel_limit_still_rejected_for_square_and_strip() -> None:
    with pytest.raises(InvalidImageError):
        load_image(big_png(8000, 5001))
    # Above MAX_PIXELS and above the ratio: still InvalidImageError.
    with pytest.raises(InvalidImageError):
        load_image(big_png(10, 4_000_001))


def test_extra_largest_valid_strip_preprocesses() -> None:
    data = big_png(1000, 10_000)  # 10 M pixels, exactly 10:1
    out = preprocess(load_image(data))
    assert out.shape == (1, 3, 224, 224) and out.dtype == np.float32


def test_extra_accepted_strip_matches_spec002_reference_pipeline() -> None:
    """Independent re-implementation of SPEC-002 section 4.4 on a 10:1 image."""
    src = formula_image(40, 400)
    out = preprocess(load_image(encode(src, "PNG")))
    p = PreprocessParams()
    # Resize shorter side to resize_size (bilinear), truncating the other side.
    w, h = src.size
    new_w, new_h = p.resize_shorter, int(h * p.resize_shorter / w)
    resized = src.resize((new_w, new_h), Image.Resampling.BILINEAR)
    left = (new_w - p.crop) // 2
    top = (new_h - p.crop) // 2
    crop = resized.crop((left, top, left + p.crop, top + p.crop))
    arr = np.asarray(crop, dtype=np.float32) / np.float32(255.0)
    arr = (arr - np.asarray(MEAN, dtype=np.float32)) / np.asarray(STD, dtype=np.float32)
    ref = np.ascontiguousarray(arr.transpose(2, 0, 1)[None, ...], dtype=np.float32)
    assert out.shape == ref.shape
    np.testing.assert_allclose(out, ref, rtol=0, atol=1e-6)


def test_extra_flag_read_on_every_call_and_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    data = rgb_png(16, 16)
    for value in (True, 1, "yes"):
        monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", value)
        with pytest.raises(RuntimeError, match="LOAD_TRUNCATED_IMAGES"):
            load_image(data)
        assert value == ImageFile.LOAD_TRUNCATED_IMAGES
        monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
        assert load_image(data).size == (16, 16)
    for value in (0, None, ""):
        monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", value)
        assert load_image(data).size == (16, 16)


def test_extra_flag_checked_before_type_and_empty_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    for arg in (b"", b"not an image", header_only_png(100, 1001), big_png(8000, 5001)):
        with pytest.raises(RuntimeError, match="LOAD_TRUNCATED_IMAGES"):
            load_image(arg)


def test_extra_concurrent_calls_do_not_touch_the_flag() -> None:
    assert ImageFile.LOAD_TRUNCATED_IMAGES is False
    data = rgb_png(64, 48)
    bad = rgb_png(10, 200)
    errors: list[BaseException] = []

    def worker() -> None:
        for _ in range(20):
            try:
                load_image(data)
                with contextlib.suppress(InvalidImageError):
                    load_image(bad)
            except BaseException as exc:  # collect anything unexpected
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert ImageFile.LOAD_TRUNCATED_IMAGES is False


_MEMORY_LIMIT_SCRIPT = """
import gc, resource, struct, sys, zlib
from qc_preprocess import InvalidImageError, load_image

def chunk(k, d):
    return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)

w, h = int(sys.argv[2]), int(sys.argv[3])
row = b"\\x00" + b"\\x00" * ((w + 7) // 8)
data = (b"\\x89PNG\\r\\n\\x1a\\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 1, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * h, 9)) + chunk(b"IEND", b""))
del row
gc.collect()
with open("/proc/self/status") as status:
    vm = next(int(line.split()[1]) * 1024 for line in status if line.startswith("VmSize"))
resource.setrlimit(resource.RLIMIT_AS, (vm + int(sys.argv[1]) * 2**20, resource.RLIM_INFINITY))
try:
    load_image(data)
except MemoryError:
    print("MemoryError")
except InvalidImageError as exc:
    print("InvalidImageError", "aspect ratio" in str(exc))
else:
    print("OK")
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs RLIMIT_AS and /proc")
@pytest.mark.parametrize(("width", "height"), [(100, 400_000), (20, 2_000_000)])
def test_extra_r_a_strip_rejected_under_tight_memory_limit(width: int, height: int) -> None:
    """SPEC-002 R-A reproduction: the strips that used 1.6 GB / 3 GB now fail in 64 MB."""
    proc = subprocess.run(
        [sys.executable, "-c", _MEMORY_LIMIT_SCRIPT, "64", str(width), str(height)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "InvalidImageError True"


@pytest.mark.parametrize("fmt", ["GIF", "BMP"])
def test_extra_unsupported_format_with_extreme_ratio_still_invalid(fmt: str) -> None:
    data = encode(Image.new("RGB", (2, 200), (1, 2, 3)), fmt)
    with pytest.raises(InvalidImageError):
        load_image(data)
