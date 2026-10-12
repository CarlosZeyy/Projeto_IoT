"""Image loading with content validation (docs/architecture.md section 6.1)."""

import io
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from qc_preprocess.errors import InvalidImageError

ACCEPTED_FORMATS: tuple[str, ...] = ("JPEG", "PNG")
MAX_PIXELS = 40_000_000


def load_image(data: bytes | Path) -> Image.Image:
    """Decode JPEG/PNG bytes or file into an RGB image with EXIF orientation applied.

    The format is detected from the content, not from the file extension.

    Raises:
        FileNotFoundError: ``data`` is a ``Path`` that does not exist.
        InvalidImageError: empty data, not an image, a format other than JPEG/PNG, a truncated
            file, more than ``MAX_PIXELS`` pixels, or a decompression bomb.
        MemoryError: propagated as is; running out of memory is not an image defect.
    """
    if isinstance(data, Path):
        if not data.is_file():
            raise FileNotFoundError(f"image file not found: {data}")
        data = data.read_bytes()
    if not isinstance(data, bytes):
        raise TypeError(f"data must be bytes or Path, got {type(data).__name__}")
    if not data:
        raise InvalidImageError("empty image data")

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
