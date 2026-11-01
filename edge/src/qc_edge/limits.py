"""Limits of the capture route, tighter than ``qc_preprocess.load_image`` (SPEC-007 section 4.7).

The ``/capture`` page always sends a JPEG of at most 1280 px on the longest side (at most
1 638 400 pixels). The ``load_image`` limits (10 MiB, 40 M pixels) exist for the ML pipeline,
which reads the original phone photos. The route only accepts what the page can produce, with
margin, which cuts the worst-case CPU and memory per decode (SEC-24-02).

Every accepted image still goes through the same ``load_image`` as training (ADR-004): the route
only rejects more images.

SPEC-019 section 4.4: ``POST /api/live/frame`` has its own limits. The page sends a JPEG of at most
640 px on the longest side (at most 409 600 pixels), and the route accepts only JPEG, by content:
the window keeps the bytes of the frame, not the decoded image that re-encoding a PNG needs.
"""

from __future__ import annotations

import io

from PIL import Image, ImageFile

from qc_preprocess import InvalidImageError, load_image

CAPTURE_MAX_BYTES: int = 3_145_728  # 3 MiB: the ``image`` field (413)
CAPTURE_MAX_REQUEST_BYTES: int = 3_670_016  # 3.5 MiB: request Content-Length (413, middleware)
CAPTURE_MAX_PIXELS: int = 4_000_000  # width x height (415)
LIVE_MAX_BYTES: int = 1_048_576  # 1 MiB: the ``image`` field of a live frame (413)
LIVE_MAX_REQUEST_BYTES: int = 1_310_720  # 1.25 MiB: request Content-Length (413, middleware)
LIVE_MAX_PIXELS: int = 1_000_000  # width x height (415)

_PROBE_FORMATS = ("JPEG", "PNG")
_LIVE_PROBE_FORMATS = ("JPEG",)


def _probe_size(data: bytes, formats: tuple[str, ...] = _PROBE_FORMATS) -> tuple[int, int]:
    """Width and height read from the header only; no pixel data is decoded.

    The image is closed when the ``with`` block ends, so nothing of the probe is kept.
    """
    try:
        with Image.open(io.BytesIO(data), formats=formats) as img:
            width, height = img.size
    except Exception as exc:
        # Hostile bytes make Pillow raise many exception types (UnidentifiedImageError,
        # OSError, SyntaxError, ValueError, DecompressionBombError, ...). All of them mean the
        # header cannot be read. This is the only broad ``except`` of the module (section 4.7).
        raise InvalidImageError(f"cannot read image header: {type(exc).__name__}") from exc
    return width, height


def load_capture_image(data: bytes) -> Image.Image:
    """Decode an uploaded capture into an RGB image, within the route limits.

    Order: the ``LOAD_TRUNCATED_IMAGES`` flag, then the header probe (``CAPTURE_MAX_PIXELS``),
    then ``qc_preprocess.load_image`` with all of its rules.

    Raises:
        RuntimeError: ``PIL.ImageFile.LOAD_TRUNCATED_IMAGES`` is enabled (server configuration
            error, never an image defect).
        InvalidImageError: unreadable header, more than ``CAPTURE_MAX_PIXELS`` pixels
            (``capture pixel limit``), or any rejection by ``load_image``.
    """
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise RuntimeError(
            "PIL.ImageFile.LOAD_TRUNCATED_IMAGES is enabled; refusing to load capture images "
            "because truncated files would be accepted"
        )
    width, height = _probe_size(data)
    if width * height > CAPTURE_MAX_PIXELS:
        raise InvalidImageError(
            f"image has {width}x{height} pixels, more than the capture pixel limit of "
            f"{CAPTURE_MAX_PIXELS}"
        )
    return load_image(data)


def load_live_image(data: bytes) -> Image.Image:
    """Decode a live frame into an RGB image, within the limits of SPEC-019 section 4.4.

    Same order as ``load_capture_image``, with ``LIVE_MAX_PIXELS`` and only JPEG in the probe.

    Raises:
        RuntimeError: ``PIL.ImageFile.LOAD_TRUNCATED_IMAGES`` is enabled (server configuration
            error, never an image defect).
        InvalidImageError: not a JPEG, unreadable header, more than ``LIVE_MAX_PIXELS`` pixels
            (``live pixel limit``), or any rejection by ``load_image``.
    """
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise RuntimeError(
            "PIL.ImageFile.LOAD_TRUNCATED_IMAGES is enabled; refusing to load live frames "
            "because truncated files would be accepted"
        )
    width, height = _probe_size(data, _LIVE_PROBE_FORMATS)
    if width * height > LIVE_MAX_PIXELS:
        raise InvalidImageError(
            f"image has {width}x{height} pixels, more than the live pixel limit of "
            f"{LIVE_MAX_PIXELS}"
        )
    return load_image(data)
