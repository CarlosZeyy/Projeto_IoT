"""load_capture_image and the route limits (SPEC-007 section 4.7)."""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

import pytest
from PIL import Image, ImageFile

from qc_edge import limits
from qc_edge.limits import (
    CAPTURE_MAX_BYTES,
    CAPTURE_MAX_PIXELS,
    CAPTURE_MAX_REQUEST_BYTES,
    load_capture_image,
)
from qc_preprocess import InvalidImageError


def _gif() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="GIF")
    return buffer.getvalue()


def _with_scan_markers(jpeg: bytes, pairs: int) -> bytes:
    """Insert a COM segment holding ``pairs`` ``FF DA`` pairs right after SOI."""
    payload = b"\xff\xda" * pairs
    segment = b"\xff\xfe" + (len(payload) + 2).to_bytes(2, "big") + payload
    return jpeg[:2] + segment + jpeg[2:]


@pytest.fixture
def load_spy(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Counts ``ImageFile.load`` calls (pixel decoding), calling the original."""
    calls: list[Any] = []
    original = ImageFile.ImageFile.load

    def spy(self: ImageFile.ImageFile, *args: Any, **kwargs: Any) -> Any:
        calls.append(self.size)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ImageFile.ImageFile, "load", spy)
    return calls


def test_constants() -> None:
    assert CAPTURE_MAX_BYTES == 3_145_728
    assert CAPTURE_MAX_REQUEST_BYTES == 3_670_016
    assert CAPTURE_MAX_PIXELS == 4_000_000


@pytest.mark.parametrize("size", [(2000, 2000), (2500, 1600), (64, 48)])
def test_up_to_the_pixel_limit_is_decoded(
    make_image: Callable[..., bytes], size: tuple[int, int]
) -> None:
    image = load_capture_image(make_image(size))
    assert image.mode == "RGB"
    assert image.size == size


@pytest.mark.parametrize("size", [(2001, 2000), (2000, 2001), (4001, 1000)])
def test_above_the_pixel_limit_is_refused_before_decoding(
    make_image: Callable[..., bytes], size: tuple[int, int], load_spy: list[Any]
) -> None:
    data = make_image(size)
    with pytest.raises(InvalidImageError, match="capture pixel limit"):
        load_capture_image(data)
    assert load_spy == []


def test_png_above_the_limit_is_refused(make_image: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidImageError, match="capture pixel limit"):
        load_capture_image(make_image((2001, 2000), fmt="PNG"))


def test_png_is_accepted(make_image: Callable[..., bytes]) -> None:
    assert load_capture_image(make_image((30, 20), fmt="PNG")).size == (30, 20)


@pytest.mark.parametrize(
    "data",
    [b"not an image", b"", b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20],
    ids=["text", "empty", "jpeg-signature-only", "png-signature-only"],
)
def test_unreadable_header_is_invalid_image(data: bytes) -> None:
    with pytest.raises(InvalidImageError):
        load_capture_image(data)


def test_gif_is_invalid_image() -> None:
    with pytest.raises(InvalidImageError):
        load_capture_image(_gif())


def test_probe_exceptions_become_invalid_image(monkeypatch: pytest.MonkeyPatch) -> None:
    def hostile_open(*args: Any, **kwargs: Any) -> Any:
        raise SyntaxError("broken header")

    monkeypatch.setattr(limits.Image, "open", hostile_open)
    with pytest.raises(InvalidImageError) as excinfo:
        load_capture_image(b"\xff\xd8\xffanything")
    assert isinstance(excinfo.value.__cause__, SyntaxError)


def test_load_image_rules_still_apply(make_image: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidImageError, match="JPEG scans"):
        load_capture_image(_with_scan_markers(make_image((64, 48)), 64))
    # 64 pairs + the real SOS = 65 markers; 63 pairs + 1 = 64 is still accepted.
    assert load_capture_image(_with_scan_markers(make_image((64, 48)), 63)).size == (64, 48)
    with pytest.raises(InvalidImageError):
        load_capture_image(make_image((100, 1001), fmt="PNG"))  # aspect ratio above 10:1
    truncated = make_image((64, 48))[:-200]
    with pytest.raises(InvalidImageError):
        load_capture_image(truncated)


def test_flag_is_checked_before_the_probe(
    monkeypatch: pytest.MonkeyPatch, make_image: Callable[..., bytes]
) -> None:
    probes: list[bytes] = []
    monkeypatch.setattr(limits, "_probe_size", lambda data: probes.append(data) or (1, 1))
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    with pytest.raises(RuntimeError, match="LOAD_TRUNCATED_IMAGES"):
        load_capture_image(make_image((2001, 2000)))
    with pytest.raises(RuntimeError, match="LOAD_TRUNCATED_IMAGES"):
        load_capture_image(b"not an image")
    assert probes == []


def test_probe_keeps_no_pixel_data(make_image: Callable[..., bytes], load_spy: list[Any]) -> None:
    assert limits._probe_size(make_image((300, 200))) == (300, 200)
    assert load_spy == []
