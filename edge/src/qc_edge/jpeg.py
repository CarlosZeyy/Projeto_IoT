"""How an accepted capture becomes a ``.jpg`` file (SPEC-007 section 4.5, SPEC-010 section 4.2,
SPEC-025 section 4.8).

Shared by the inspect mode (``EDGE_DATA_DIR/captures``) and the collect mode (``DATASET_DIR``):
a JPEG is written with the bytes it is given; a PNG (the only other format ``load_image``
accepts) is re-encoded as JPEG with quality 90 (Pillow copies no metadata without ``exif``).

The collect mode first removes the private segments of a JPEG with ``strip_private_segments``:
APP1 (EXIF, XMP), APP13 (IPTC), COM and anything after the EOI (for example, the video of a
Motion Photo). It is a structural walk over the markers, never a search for loose bytes (an
``FF D9`` can appear inside an APPn, a COM or an EXIF thumbnail), and it never re-encodes: the
entropy-coded data is copied as is, so the decoded pixels do not change (R-14). The inspect mode
keeps writing the JPEG as received (``captures/`` never leaves the notebook).

The EXIF ``Orientation`` tag lives in the APP1, and ``qc_preprocess.load_image`` applies it
(``ImageOps.exif_transpose``). A JPEG with an EXIF rotation (``has_exif_rotation``) is therefore
never stripped: the collect mode refuses it and the privacy scan reports it, so that
``load_image`` gives the same image for the received bytes and for the stored file (ADR-004).
"""

from __future__ import annotations

import io
import re
from typing import BinaryIO

from PIL import Image

# Signature Pillow uses to recognise JPEG content.
JPEG_SIGNATURE = b"\xff\xd8\xff"
PNG_TO_JPEG_QUALITY = 90

_SOI = b"\xff\xd8"
_EOI_MARKER = 0xD9
_SOS_MARKER = 0xDA
_TEM_MARKER = 0x01
_RST_MARKERS = range(0xD0, 0xD8)
# Segments that are never copied, with the fixed name reported by ``jpeg_private_findings``.
_PRIVATE_SEGMENTS = {0xE1: "app1", 0xED: "app13", 0xFE: "com"}
FINDING_TRAILER = "trailer"
PRIVATE_FINDINGS = frozenset({*_PRIVATE_SEGMENTS.values(), FINDING_TRAILER})

_FILL = re.compile(rb"\xff+")

# EXIF tag 274 and the values ``ImageOps.exif_transpose`` applies (a ``dict.get`` lookup: the
# membership test below uses the same hash and equality, so ``6.0`` counts like ``6``).
_ORIENTATION_TAG = 0x0112
_ROTATION_VALUES = frozenset(range(2, 9))


class JpegStructureError(ValueError):
    """The bytes are not a JPEG this module can walk. The message never contains input bytes."""


def write_capture_jpeg(handle: BinaryIO, data: bytes, image: Image.Image) -> None:
    """Write ``data`` (JPEG) or ``image`` re-encoded as JPEG (PNG) to ``handle``.

    ``image`` is the result of ``load_capture_image(data)``, already RGB.
    """
    if data.startswith(JPEG_SIGNATURE):
        handle.write(data)
    else:
        image.save(handle, format="JPEG", quality=PNG_TO_JPEG_QUALITY)


def strip_private_segments(data: bytes) -> bytes:
    """``data`` without APP1, APP13, COM and the bytes after the EOI.

    With nothing to remove, the result is ``data`` itself, byte for byte.

    Raises:
        JpegStructureError: no SOI, a segment length below 2 or beyond the end, or the data
            ends before the EOI.
    """
    output, _ = _walk(data, keep_output=True)
    return bytes(output)


def jpeg_private_findings(data: bytes) -> frozenset[str]:
    """What ``strip_private_segments`` would remove: a subset of ``PRIVATE_FINDINGS``.

    Only the fixed names are returned, never the content of the segments.

    Raises:
        JpegStructureError: same cases as ``strip_private_segments``.
    """
    _, findings = _walk(data, keep_output=False)
    return frozenset(findings)


def has_exif_rotation(data: bytes) -> bool:
    """Whether ``qc_preprocess.load_image`` would rotate or flip ``data`` (SPEC-025 section 4.8).

    ``True`` if, and only if, the ``Orientation`` tag (274) of
    ``Image.open(..., formats=("JPEG",)).getexif()`` is one of the values 2 to 8 that
    ``ImageOps.exif_transpose`` applies. Pillow's ``getexif`` also reads the XMP
    ``tiff:Orientation`` when the EXIF has no such tag. Only the header is read (no ``load()``),
    and the value is never returned nor logged.

    Raises:
        JpegStructureError: any Pillow error (except ``MemoryError``), with a fixed message.
    """
    try:
        with Image.open(io.BytesIO(data), formats=("JPEG",)) as image:
            orientation = image.getexif().get(_ORIENTATION_TAG)
    except MemoryError:
        raise
    except Exception:
        raise JpegStructureError("cannot read the JPEG EXIF orientation") from None
    try:
        return orientation in _ROTATION_VALUES
    except TypeError:  # an unhashable value is never applied (exif_transpose would fail)
        return False


def _walk(data: bytes, *, keep_output: bool) -> tuple[bytearray, set[str]]:
    """Walk the markers from the SOI to the EOI; copy what is kept when ``keep_output``."""
    if not data.startswith(_SOI):
        raise JpegStructureError("data does not start with the JPEG SOI marker")
    size = len(data)
    output = bytearray(_SOI) if keep_output else bytearray()
    findings: set[str] = set()
    pos = len(_SOI)
    while True:
        # Marker: one or more 0xFF (all but the last one are fill bytes), then the marker code.
        fill = _FILL.match(data, pos)
        if fill is None:
            if pos >= size:
                raise JpegStructureError("data ends before the EOI marker")
            raise JpegStructureError("expected a marker")
        code_pos = fill.end()
        if code_pos >= size:
            raise JpegStructureError("data ends before the EOI marker")
        code = data[code_pos]
        if code == 0x00:
            raise JpegStructureError("expected a marker")
        if keep_output:
            output += data[pos : code_pos - 1]  # fill bytes, copied as they are
        pos = code_pos + 1

        if code == _EOI_MARKER:
            if keep_output:
                output += data[code_pos - 1 : pos]
            if pos < size:
                findings.add(FINDING_TRAILER)
            return output, findings

        if code in _RST_MARKERS or code == _TEM_MARKER:  # no length
            if keep_output:
                output += data[code_pos - 1 : pos]
            continue

        if pos + 2 > size:
            raise JpegStructureError("segment length beyond the end of data")
        length = int.from_bytes(data[pos : pos + 2], "big")
        if length < 2:
            raise JpegStructureError("segment length below 2")
        end = pos + length
        if end > size:
            raise JpegStructureError("segment length beyond the end of data")

        private = _PRIVATE_SEGMENTS.get(code)
        if private is not None:
            findings.add(private)
        elif keep_output:
            output += data[code_pos - 1 : end]
        pos = end

        if code == _SOS_MARKER:
            pos = _entropy_end(data, pos)
            if keep_output:
                output += data[end:pos]


def _entropy_end(data: bytes, pos: int) -> int:
    """Offset of the marker that ends the entropy-coded data starting at ``pos``.

    ``FF 00`` (stuffed byte) and ``FF D0``-``FF D7`` (RSTn) belong to the data; any other
    ``FF xx`` ends it.
    """
    size = len(data)
    while True:
        ff = data.find(b"\xff", pos)
        if ff < 0 or ff + 1 >= size:
            raise JpegStructureError("data ends before the EOI marker")
        following = data[ff + 1]
        if following == 0x00 or following in _RST_MARKERS:
            pos = ff + 2
            continue
        return ff
