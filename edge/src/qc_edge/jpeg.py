"""How an accepted capture becomes a ``.jpg`` file (SPEC-007 section 4.5, SPEC-010 section 4.2).

Shared by the inspect mode (``EDGE_DATA_DIR/captures``) and the collect mode (``DATASET_DIR``):
a JPEG is written with the bytes as received; a PNG (the only other format ``load_image``
accepts) is re-encoded as JPEG with quality 90.
"""

from __future__ import annotations

from typing import BinaryIO

from PIL import Image

# Signature Pillow uses to recognise JPEG content: those bytes are saved as received.
JPEG_SIGNATURE = b"\xff\xd8\xff"
PNG_TO_JPEG_QUALITY = 90


def write_capture_jpeg(handle: BinaryIO, data: bytes, image: Image.Image) -> None:
    """Write ``data`` (JPEG) or ``image`` re-encoded as JPEG (PNG) to ``handle``.

    ``image`` is the result of ``load_capture_image(data)``, already RGB.
    """
    if data.startswith(JPEG_SIGNATURE):
        handle.write(data)
    else:
        image.save(handle, format="JPEG", quality=PNG_TO_JPEG_QUALITY)
