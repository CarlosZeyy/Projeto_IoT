"""Fixtures of the qc-edge unit tests (SPEC-007, SPEC-010, SPEC-025).

Images are generated in memory, never stored in the repository (R-14). The JPEG samples of
SPEC-025 (``jpeg_tools``) insert, right after the SOI of a Pillow JPEG, an EXIF APP1 with a GPS
IFD, an XMP APP1, an IPTC APP13 and a COM, and append a Motion-Photo-like trailer after the EOI;
the rotated samples carry an EXIF (or XMP) ``Orientation``. The ``dummy_model`` fixture
(SPEC-008) gives the helper that builds dummy ONNX models and model directories.
"""

from __future__ import annotations

import importlib.util
import io
import secrets
import struct
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, TiffImagePlugin

from qc_edge.config import EdgeSettings


def _load_dummy_model() -> types.ModuleType:
    """``edge/tests/dummy_model.py`` loaded by path (SPEC-008; not on ``sys.path``)."""
    name = "qc_edge_tests_dummy_model"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("dummy_model.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


XMP_PREFIX = b"http://ns.adobe.com/xap/1.0/\x00"
IPTC_PREFIX = b"Photoshop 3.0\x00"
TRAILER = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200_000
GPS_LATITUDE = ((22, 1), (54, 1), (3021, 100))  # 22 deg 54' 30.21"


def segment(marker: int, payload: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


def noise_image(size: tuple[int, int] = (64, 48), seed: int = 7) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8), "RGB")


def pillow_jpeg(
    size: tuple[int, int] = (64, 48), *, exif: bytes | None = None, **save: object
) -> bytes:
    buffer = io.BytesIO()
    options: dict[str, object] = {"quality": 90, **save}
    if exif is not None:
        options["exif"] = exif
    noise_image(size).save(buffer, format="JPEG", **options)
    return buffer.getvalue()


def gps_exif() -> bytes:
    exif = Image.Exif()
    latitude = tuple(TiffImagePlugin.IFDRational(*part) for part in GPS_LATITUDE)
    exif[0x8825] = {1: "S", 2: latitude}  # GPSInfo IFD: GPSLatitudeRef and GPSLatitude
    return exif.tobytes()


def orientation_exif(value: int, *, gps: bool = True) -> bytes:
    """EXIF with ``Orientation`` (tag 274) and, by default, the GPS IFD of ``gps_exif``."""
    exif = Image.Exif()
    exif[0x0112] = value
    if gps:
        latitude = tuple(TiffImagePlugin.IFDRational(*part) for part in GPS_LATITUDE)
        exif[0x8825] = {1: "S", 2: latitude}
    return exif.tobytes()


def rotated_jpeg(value: int = 6, size: tuple[int, int] = (64, 48), *, gps: bool = True) -> bytes:
    """Pillow JPEG (asymmetric noise) with ``Orientation=value`` in the EXIF."""
    return pillow_jpeg(size, exif=orientation_exif(value, gps=gps))


def xmp_orientation_jpeg(value: int, *, element: bool = False) -> bytes:
    """Pillow JPEG without EXIF and with ``tiff:Orientation`` only in an XMP APP1."""
    tag = (
        f"<tiff:Orientation>{value}</tiff:Orientation>"
        if element
        else f'<rdf:Description tiff:Orientation="{value}"/>'
    )
    payload = XMP_PREFIX + f"<x:xmpmeta>{tag}</x:xmpmeta>".encode()
    return insert_after_soi(pillow_jpeg(), segment(0xE1, payload))


def tiff_orientation_exif(field_type: int, value: bytes) -> bytes:
    """Hand-made little-endian EXIF whose only entry is tag 274 with ``field_type`` (TIFF type
    number) and ``value`` (at most 8 bytes, stored after the IFD when it has more than 4)."""
    count = 1
    if len(value) <= 4:
        entry = struct.pack("<HHI", 0x0112, field_type, count) + value.ljust(4, b"\x00")
        tail = b""
    else:
        offset = 8 + 2 + 12 + 4
        entry = struct.pack("<HHII", 0x0112, field_type, count, offset)
        tail = value
    return b"Exif\x00\x00II*\x00" + struct.pack("<IH", 8, 1) + entry + struct.pack("<I", 0) + tail


def insert_after_soi(data: bytes, *segments: bytes) -> bytes:
    assert data[:2] == b"\xff\xd8"
    return data[:2] + b"".join(segments) + data[2:]


def with_metadata(comment: bytes | None = None) -> tuple[bytes, bytes]:
    """``(jpeg, comment marker)``: EXIF GPS + XMP + IPTC + COM, then a trailer after the EOI."""
    marker = comment if comment is not None else b"note-" + secrets.token_hex(8).encode()
    base = pillow_jpeg(exif=gps_exif())
    data = insert_after_soi(
        base,
        segment(0xE1, XMP_PREFIX + b"<x:xmpmeta/>"),
        segment(0xED, IPTC_PREFIX + b"8BIM\x04\x04\x00\x00\x00\x00\x00\x00"),
        segment(0xFE, marker),
    )
    return data + TRAILER, marker


def pixels(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        return np.asarray(image.convert("RGB"))


def markers(data: bytes) -> list[bytes]:
    """Every length-carrying segment (marker + length + payload) up to the first SOS, plus SOS
    headers; used to compare the structure of two JPEGs."""
    found: list[bytes] = []
    pos = 2
    while pos < len(data):
        while data[pos] == 0xFF and data[pos + 1] == 0xFF:
            pos += 1
        code = data[pos + 1]
        if code == 0xD9:
            break
        if 0xD0 <= code <= 0xD7 or code == 0x01:
            pos += 2
            continue
        length = int.from_bytes(data[pos + 2 : pos + 4], "big")
        found.append(data[pos : pos + 2 + length])
        pos += 2 + length
        if code == 0xDA:
            while not (data[pos] == 0xFF and data[pos + 1] not in (0x00, *range(0xD0, 0xD8))):
                pos += 1
    return found


EDGE_ENV_VARS = (
    "EDGE_HOST",
    "EDGE_PORT",
    "EDGE_SESSION_TOKEN",
    "DEVICE_ID",
    "EDGE_DATA_DIR",
    "DEVICE_API_KEY",
    "CLOUD_API_URL",
    "MODEL_DIR",
    "DATASET_DIR",
    "OUTBOX_PATH",
    "TYPE_THRESHOLD",
    "UNUSABLE_THRESHOLD",
    "GRADE_REVIEW_THRESHOLD",
)


def encode_image(
    size: tuple[int, int] = (64, 48), fmt: str = "JPEG", color: str = "steelblue"
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.fixture
def make_image() -> Callable[..., bytes]:
    """``make_image(size=(64, 48), fmt="JPEG", color=...)`` -> encoded bytes."""
    return encode_image


@pytest.fixture
def jpeg_bytes() -> bytes:
    return encode_image()


@pytest.fixture
def clean_edge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every edge variable from the process environment for the test."""
    for name in EDGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "edge-data"


@pytest.fixture
def dataset_dir(tmp_path: Path) -> Path:
    """``DATASET_DIR`` of the tests; not created (the collect mode creates it)."""
    return tmp_path / "dataset"


@pytest.fixture
def settings(clean_edge_env: None, data_dir: Path, dataset_dir: Path) -> EdgeSettings:
    # DATASET_DIR always under tmp_path: the default (ml/data) is relative to the current
    # directory, which is the repository during the tests.
    return EdgeSettings(EDGE_DATA_DIR=data_dir, DATASET_DIR=dataset_dir)


@pytest.fixture
def files_under(tmp_path: Path) -> Iterator[Callable[[], list[Path]]]:
    """Returns a function listing the regular files under ``tmp_path``."""

    def _list() -> list[Path]:
        return sorted(path for path in tmp_path.rglob("*") if path.is_file())

    yield _list


@pytest.fixture
def jpeg_tools() -> types.SimpleNamespace:
    """Builders and readers of the SPEC-025 JPEG samples."""
    return types.SimpleNamespace(
        XMP_PREFIX=XMP_PREFIX,
        IPTC_PREFIX=IPTC_PREFIX,
        TRAILER=TRAILER,
        GPS_LATITUDE=GPS_LATITUDE,
        segment=segment,
        noise_image=noise_image,
        pillow_jpeg=pillow_jpeg,
        gps_exif=gps_exif,
        orientation_exif=orientation_exif,
        rotated_jpeg=rotated_jpeg,
        xmp_orientation_jpeg=xmp_orientation_jpeg,
        tiff_orientation_exif=tiff_orientation_exif,
        insert_after_soi=insert_after_soi,
        with_metadata=with_metadata,
        pixels=pixels,
        markers=markers,
    )


@pytest.fixture
def dummy_model() -> types.ModuleType:
    """The ``edge/tests/dummy_model.py`` helper (SPEC-008): ``build_model``, ``write_model_dir``,
    ``sha256_of`` and the default constants."""
    return _load_dummy_model()
