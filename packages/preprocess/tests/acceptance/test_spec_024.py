"""Acceptance tests for SPEC-024 (qc-preprocess 0.3.0: limit of JPEG scans).

Written by the tester from the SPEC acceptance criteria (black box), before reading the
implementation. Covers CA-01 to CA-09. Tests named ``test_extra_*`` are exploratory edge cases
around SPEC-024 section 4.1 that no CA spells out. All images are generated in memory; no
binary file is committed.
"""

from __future__ import annotations

import importlib.metadata
import io
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageFile
from PIL.PngImagePlugin import PngInfo

import qc_preprocess
import qc_preprocess.image
from qc_preprocess import InvalidImageError, PreprocessParams, load_image, preprocess

pytestmark = pytest.mark.acceptance

PKG_ROOT = Path(__file__).resolve().parents[2]  # packages/preprocess
ROOT = PKG_ROOT.parents[1]  # repository root

SOS = b"\xff\xda"
EOI = b"\xff\xd9"
SCANS_MSG = "JPEG scans"


# --------------------------------------------------------------------------- helpers


def encode(img: Image.Image, fmt: str, **kwargs: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def formula_image(width: int, height: int, mode: str = "RGB") -> Image.Image:
    """Deterministic test pattern (fixed formula, no randomness)."""
    y, x = np.mgrid[0:height, 0:width]
    arr = np.stack(
        [(x * 7 + y * 3) % 256, (x * x + 5 * y) % 256, (x * y + 11) % 256], axis=-1
    ).astype(np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    return img if mode == "RGB" else img.convert(mode)


def baseline_jpeg() -> bytes:
    """Baseline RGB 64x48 JPEG with exactly one SOS marker."""
    data = encode(formula_image(64, 48), "JPEG", quality=90)
    assert data.count(SOS) == 1
    return data


def progressive_jpeg(width: int, height: int, mode: str = "RGB") -> bytes:
    return encode(formula_image(width, height, mode), "JPEG", quality=90, progressive=True)


def with_com(jpeg: bytes, pairs: int) -> bytes:
    """Insert, right after SOI, a COM segment whose payload is ``FF DA`` * ``pairs``."""
    assert jpeg[:2] == b"\xff\xd8"
    payload = SOS * pairs
    segment = b"\xff\xfe" + struct.pack(">H", len(payload) + 2) + payload
    return jpeg[:2] + segment + jpeg[2:]


def repeated_scans(jpeg: bytes, markers: int) -> bytes:
    """Repeat the last scan (last ``FF DA`` up to the final ``FF D9``) until ``markers`` SOS."""
    assert jpeg.endswith(EOI)
    start = jpeg.rindex(SOS)
    last_scan = jpeg[start:-2]
    assert last_scan.count(SOS) == 1
    base = jpeg.count(SOS)
    assert markers >= base
    out = jpeg[:-2] + last_scan * (markers - base) + EOI
    assert out.count(SOS) == markers
    return out


def com_only(pairs: int) -> bytes:
    """SOI + one COM segment, no frame and no image (CA-06)."""
    payload = SOS * pairs
    return b"\xff\xd8\xff\xfe" + struct.pack(">H", len(payload) + 2) + payload


def png_with_pairs(pairs: int) -> bytes:
    info = PngInfo()
    info.add_text("Comment", "\xff\xda" * pairs)
    data = encode(formula_image(64, 48), "PNG", pnginfo=info)
    assert data.count(SOS) >= pairs
    return data


def raises_scans(data: bytes | Path) -> str:
    with pytest.raises(InvalidImageError) as exc:
        load_image(data)
    message = str(exc.value)
    assert SCANS_MSG in message, message
    return message


# --------------------------------------------------------------------------- CA-01


def test_ca01_preprocess_version_and_contracts_unchanged() -> None:
    import qc_contracts

    assert qc_preprocess.__version__ == "0.3.0"
    assert importlib.metadata.version("qc-preprocess") == "0.3.0"
    assert qc_preprocess.__version__ == importlib.metadata.version("qc-preprocess")
    v = qc_contracts.__version__
    assert qc_contracts.__version__ == importlib.metadata.version("qc-contracts")
    assert re.fullmatch(r"\d+\.\d+\.\d+", v)
    assert (0, 2, 0) <= tuple(int(p) for p in v.split(".")) < (1, 0, 0)


# --------------------------------------------------------------------------- CA-02


def test_ca02_max_jpeg_scans_constant_and_unchanged_limits() -> None:
    assert qc_preprocess.MAX_JPEG_SCANS == qc_preprocess.image.MAX_JPEG_SCANS == 64
    assert type(qc_preprocess.MAX_JPEG_SCANS) is int
    assert qc_preprocess.MAX_PIXELS == 40_000_000
    assert qc_preprocess.MAX_ASPECT_RATIO == 10


# --------------------------------------------------------------------------- CA-03


@pytest.mark.parametrize(
    ("data", "size"),
    [
        (baseline_jpeg(), (64, 48)),
        (progressive_jpeg(640, 480, "RGB"), (640, 480)),
        (progressive_jpeg(640, 480, "L"), (640, 480)),
    ],
    ids=["baseline-rgb-64x48", "progressive-rgb-640x480", "progressive-gray-640x480"],
)
def test_ca03_common_jpegs_accepted(data: bytes, size: tuple[int, int]) -> None:
    img = load_image(data)
    assert img.mode == "RGB"
    assert img.size == size


def test_ca03_progressive_files_really_have_several_scans() -> None:
    # Guard on the CA-03 inputs: the progressive files are multi-scan (10 for YCbCr, 6 for gray).
    assert progressive_jpeg(640, 480, "RGB").count(SOS) == 10
    assert progressive_jpeg(640, 480, "L").count(SOS) == 6


# --------------------------------------------------------------------------- CA-04


def test_ca04_limit_64_markers_accepted_and_bit_identical() -> None:
    clean = baseline_jpeg()
    at_limit = with_com(clean, 63)
    assert at_limit.count(SOS) == 64
    params = PreprocessParams()
    got = preprocess(load_image(at_limit), params)
    ref = preprocess(load_image(clean), params)
    assert got.dtype == ref.dtype and got.shape == ref.shape
    assert got.tobytes() == ref.tobytes()


def test_ca04_65_markers_rejected() -> None:
    over = with_com(baseline_jpeg(), 64)
    assert over.count(SOS) == 65
    raises_scans(over)


# --------------------------------------------------------------------------- CA-05


@pytest.mark.parametrize("markers", [65, 1000])
def test_ca05_repeated_progressive_scans_rejected(markers: int) -> None:
    data = repeated_scans(progressive_jpeg(256, 256), markers)
    raises_scans(data)


def test_ca05_construction_is_decodable_at_limit() -> None:
    # Guard on the CA-05 construction (SPEC section 7): with 64 markers the same arranjo is a
    # file that the decoder accepts, so the 65/1000 rejections can only come from the scan rule.
    data = repeated_scans(progressive_jpeg(256, 256), 64)
    img = load_image(data)
    assert img.size == (256, 256)
    assert img.mode == "RGB"


# --------------------------------------------------------------------------- CA-06


def test_ca06_rule_runs_before_image_open() -> None:
    raises_scans(com_only(65))


def test_ca06_within_limit_fails_for_another_reason() -> None:
    with pytest.raises(InvalidImageError) as exc:
        load_image(com_only(10))
    assert SCANS_MSG not in str(exc.value)


# --------------------------------------------------------------------------- CA-07


def test_ca07_png_with_marker_pairs_accepted() -> None:
    data = png_with_pairs(100)
    img = load_image(data)
    assert img.size == (64, 48)
    assert img.mode == "RGB"


# --------------------------------------------------------------------------- CA-08


def test_ca08_truncated_flag_checked_before_scans(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    with pytest.raises(RuntimeError) as exc:
        load_image(with_com(baseline_jpeg(), 64))
    assert "LOAD_TRUNCATED_IMAGES" in str(exc.value)


def test_ca08_empty_checked_before_scans(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    with pytest.raises(InvalidImageError) as exc:
        load_image(b"")
    assert SCANS_MSG not in str(exc.value)
    assert "empty" in str(exc.value)


# --------------------------------------------------------------------------- CA-09


def test_ca09_old_preprocess_acceptance_files_pass() -> None:
    """Runs the two old acceptance files of qc-preprocess with explicit paths.

    ``test_ca12_spec002_acceptance_suites_still_pass`` of SPEC-023 is deselected here because it
    runs pytest in a subprocess itself (docs/architecture.md section 10: a subprocess run never
    includes another test that runs pytest in a subprocess). It still runs in the full suite.
    """
    env = dict(os.environ)
    for key in ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST", "PYTEST_PLUGINS"):
        env.pop(key, None)
    files = [
        "packages/preprocess/tests/acceptance/test_spec_002.py",
        "packages/preprocess/tests/acceptance/test_spec_023.py",
    ]
    nested = files[1] + "::test_ca12_spec002_acceptance_suites_still_pass"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            *files,
            "--deselect",
            nested,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out[-4000:]
    assert re.search(r"\b\d+ passed\b", out), out[-4000:]
    assert not re.search(r"\b\d+ (failed|errors?)\b", out), out[-4000:]
    text = "\n".join((ROOT / f).read_text(encoding="utf-8") for f in files)
    # The files still hold the numeric, determinism, dependency, aspect-ratio and flag CAs
    # (they really ran).
    for name in ("ca20", "ca21", "ca22", "ca24", "ca26", "ca07", "ca09", "ca10"):
        assert f"def test_{name}_" in text, name


# --------------------------------------------------------------------------- extras
# Exploratory edge cases around SPEC-024 section 4.1.


def test_extra_path_input_is_checked(tmp_path: Path) -> None:
    over = tmp_path / "over.jpg"
    over.write_bytes(with_com(baseline_jpeg(), 64))
    raises_scans(over)
    at_limit = tmp_path / "at_limit.jpg"
    at_limit.write_bytes(with_com(baseline_jpeg(), 63))
    assert load_image(at_limit).size == (64, 48)


def test_extra_markers_after_eoi_are_counted() -> None:
    # The count covers the whole file, including trailing bytes after EOI (SPEC 4.1).
    data = baseline_jpeg() + SOS * 64
    assert data.count(SOS) == 65
    raises_scans(data)


def test_extra_trailing_markers_up_to_limit_accepted() -> None:
    data = baseline_jpeg() + SOS * 63
    assert data.count(SOS) == 64
    assert load_image(data).size == (64, 48)


def test_extra_message_reports_count_and_limit() -> None:
    message = raises_scans(with_com(baseline_jpeg(), 99))
    assert "100" in message
    assert "64" in message


def test_extra_signature_must_be_at_start() -> None:
    # Without the FF D8 FF prefix the rule does not apply: the error, if any, is another one.
    for data in (
        b"\x00" + com_only(65),  # signature shifted by one byte
        b"\xff\xd8\x00" + SOS * 100,  # FF D8 not followed by FF
        b"hello " + SOS * 100,  # text with marker pairs
    ):
        with pytest.raises(InvalidImageError) as exc:
            load_image(data)
        assert SCANS_MSG not in str(exc.value), data[:8]


def test_extra_fill_bytes_do_not_add_markers() -> None:
    # Extra FF fill bytes before EOI create no new FF DA pair, so the count stays at 64.
    data = with_com(baseline_jpeg(), 63)
    data_ff = data[:-2] + b"\xff" * 10 + EOI  # extra FF bytes, no new FF DA pair
    assert data_ff.count(SOS) == 64
    # Decoders tolerate fill bytes before a marker; if not, the error must not be about scans.
    try:
        load_image(data_ff)
    except InvalidImageError as exc:
        assert SCANS_MSG not in str(exc)


def test_extra_cmyk_progressive_accepted() -> None:
    # CMYK progressive is the longest standard script for <= 4 components (18 scans, SPEC 1).
    data = encode(formula_image(64, 48).convert("CMYK"), "JPEG", quality=90, progressive=True)
    assert data.count(SOS) == 18
    img = load_image(data)
    assert img.mode == "RGB" and img.size == (64, 48)


def test_extra_exif_thumbnail_jpeg_accepted() -> None:
    # A phone-like JPEG: EXIF APP1 with an embedded JPEG thumbnail (1 extra SOS) is accepted.
    thumb = encode(formula_image(16, 12), "JPEG", quality=80)
    exif = Image.Exif()
    exif[0x0112] = 1
    raw = exif.tobytes()
    data = encode(formula_image(64, 48), "JPEG", quality=90, exif=raw)
    app1 = b"Exif\x00\x00" + raw + thumb  # thumbnail bytes inside APP1 (count only)
    data = data[:2] + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + data[2:]
    assert 2 <= data.count(SOS) <= 3
    assert load_image(data).size == (64, 48)


def test_extra_rejected_quickly_on_large_body() -> None:
    # 10 MiB of FF DA after a JPEG signature: rejected by counting, without decoding.
    data = com_only(1) + SOS * (5 * 1024 * 1024)
    t0 = time.perf_counter()
    raises_scans(data)
    assert time.perf_counter() - t0 < 2.0


def test_extra_repeated_rejection_is_stable() -> None:
    data = with_com(baseline_jpeg(), 64)
    first = raises_scans(data)
    for _ in range(5):
        assert raises_scans(data) == first
    # A good image still loads after rejections (no leaked state).
    assert load_image(baseline_jpeg()).size == (64, 48)


@pytest.mark.parametrize("mode", ["RGB", "L"])
def test_extra_progressive_preprocess_unchanged_by_limit(mode: str) -> None:
    # Accepted progressive images produce a deterministic, finite tensor (no value change).
    data = progressive_jpeg(320, 240, mode)
    a = preprocess(load_image(data), PreprocessParams())
    b = preprocess(load_image(data), PreprocessParams())
    assert a.shape == (1, 3, 224, 224)
    assert a.tobytes() == b.tobytes()
    assert np.isfinite(a).all()
