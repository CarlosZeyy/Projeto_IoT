"""Image loading with content validation (docs/architecture.md section 6.1)."""

import io
import warnings
from pathlib import Path

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

from qc_preprocess.errors import InvalidImageError

ACCEPTED_FORMATS: tuple[str, ...] = ("JPEG", "PNG")
MAX_PIXELS = 40_000_000
# Longest side at most MAX_ASPECT_RATIO times the shortest. ``preprocess`` resizes before it
# crops, so an extreme strip (e.g. 100x400000) would blow up memory during the resize.
MAX_ASPECT_RATIO: int = 10
# Upper bound on SOS markers (``FF DA``) in JPEG content (SEC-01 of the SPEC-023 security
# report): a progressive JPEG with repeated scans costs CPU proportional to scans x pixels.
# The count covers the whole file without parsing segments, so it never counts fewer scans
# than the decoder processes; it may count a few more (APPn/COM payloads, EXIF thumbnails,
# MPO or gain-map images after EOI). Standard scripts use at most 18 scans (CMYK progressive).
MAX_JPEG_SCANS: int = 64
# Signature Pillow uses to recognise JPEG content (JpegImagePlugin._accept).
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_JPEG_SOS_MARKER = b"\xff\xda"


def load_image(data: bytes | Path) -> Image.Image:
    """Decode JPEG/PNG bytes or file into an RGB image with EXIF orientation applied.

    The format is detected from the content, not from the file extension. The JPEG scan limit is
    checked on the raw bytes, before the image is opened; the pixel limit and the aspect ratio are
    checked from the header, before any pixel data is decoded.

    Raises:
        RuntimeError: ``PIL.ImageFile.LOAD_TRUNCATED_IMAGES`` is enabled in this process
            (checked first, on every call). This is a process configuration error, not an image
            defect, so it is not an ``InvalidImageError``; the flag is left untouched.
        FileNotFoundError: ``data`` is a ``Path`` that does not exist.
        InvalidImageError: empty data, JPEG content (``FF D8 FF`` signature) with more than
            ``MAX_JPEG_SCANS`` scan markers (``FF DA`` pairs anywhere in the file), not an image,
            a format other than JPEG/PNG, a truncated file, more than ``MAX_PIXELS`` pixels, a
            zero-sized image or an aspect ratio above ``MAX_ASPECT_RATIO``:1 (longest side over
            shortest side), or a decompression bomb.
        MemoryError: propagated as is; running out of memory is not an image defect.
    """
    # Read on every call: the flag is a module global that any code in the process may change.
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise RuntimeError(
            "PIL.ImageFile.LOAD_TRUNCATED_IMAGES is enabled; refusing to load images because "
            "truncated files would be accepted"
        )
    if isinstance(data, Path):
        if not data.is_file():
            raise FileNotFoundError(f"image file not found: {data}")
        data = data.read_bytes()
    if not isinstance(data, bytes):
        raise TypeError(f"data must be bytes or Path, got {type(data).__name__}")
    if not data:
        raise InvalidImageError("empty image data")
    if data.startswith(_JPEG_SIGNATURE):
        # Naive count over the whole file on purpose: no segment parsing, so a malformed segment
        # cannot make it undercount (libjpeg skips junk and keeps decoding).
        scans = data.count(_JPEG_SOS_MARKER)
        if scans > MAX_JPEG_SCANS:
            raise InvalidImageError(
                f"too many JPEG scans: {scans} scan markers, limit {MAX_JPEG_SCANS}"
            )

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            img = Image.open(io.BytesIO(data), formats=ACCEPTED_FORMATS)
        except UnidentifiedImageError as exc:
            raise InvalidImageError("content is not a JPEG or PNG image") from exc
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise InvalidImageError("image exceeds the pixel limit") from exc
        except (OSError, SyntaxError, ValueError) as exc:
            raise InvalidImageError(f"cannot read image header: {exc}") from exc

        width, height = img.size
        if width * height > MAX_PIXELS:
            raise InvalidImageError(
                f"image has {width}x{height} pixels, more than the limit of {MAX_PIXELS}"
            )
        # Integer arithmetic: exact at the 10:1 boundary, no float rounding.
        shortest, longest = min(width, height), max(width, height)
        if shortest == 0 or longest > MAX_ASPECT_RATIO * shortest:
            raise InvalidImageError(
                f"image is {width}x{height} pixels; aspect ratio above {MAX_ASPECT_RATIO}:1"
            )

        try:
            img.load()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise InvalidImageError("image exceeds the pixel limit") from exc
        except (OSError, SyntaxError, ValueError) as exc:
            raise InvalidImageError(f"cannot decode image: {exc}") from exc

    try:
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")
    except MemoryError:
        raise  # a server-side failure, not a property of the image
    except Exception as exc:  # malformed EXIF or unsupported mode conversion
        raise InvalidImageError(f"cannot normalize image: {exc}") from exc
