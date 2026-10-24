"""qc_edge.jpeg: structural removal of the private JPEG segments (SPEC-025 section 4.8) and the
EXIF orientation of the import (SPEC-036 section 4.3)."""

from __future__ import annotations

import io
import logging
import struct
import types
from collections.abc import Callable

import numpy as np
import pytest
from PIL import Image

from qc_edge import jpeg as jpeg_module
from qc_edge.jpeg import (
    PRIVATE_FINDINGS,
    JpegStructureError,
    exif_orientation,
    has_exif_rotation,
    jpeg_private_findings,
    strip_private_segments,
)
from qc_preprocess import load_image


def test_metadata_jpeg_is_cleaned_without_changing_pixels(jpeg_tools: types.SimpleNamespace):
    data, marker = jpeg_tools.with_metadata()
    assert jpeg_private_findings(data) == frozenset({"app1", "app13", "com", "trailer"})
    assert {"app1", "app13", "com", "trailer"} == PRIVATE_FINDINGS
    clean = strip_private_segments(data)
    assert jpeg_private_findings(clean) == frozenset()
    for needle in (b"Exif\x00\x00", b"http://ns.adobe.com/xap/1.0/", b"Photoshop 3.0", marker):
        assert needle not in clean
    assert b"ftypmp42" not in clean
    assert clean.endswith(b"\xff\xd9")
    assert len(Image.open(io.BytesIO(clean)).getexif()) == 0
    assert np.array_equal(jpeg_tools.pixels(clean), jpeg_tools.pixels(data))
    # Every other segment (APP0, DQT, SOF, DHT, SOS) is kept, byte for byte and in order.
    kept = [m for m in jpeg_tools.markers(data) if m[1] not in (0xE1, 0xED, 0xFE)]
    assert jpeg_tools.markers(clean) == kept


def test_nothing_to_remove_gives_the_same_bytes(jpeg_tools: types.SimpleNamespace) -> None:
    for data in (
        jpeg_tools.pillow_jpeg(),
        jpeg_tools.pillow_jpeg((97, 61), progressive=True),
        jpeg_tools.pillow_jpeg((80, 80), subsampling=0, quality=95),
    ):
        assert jpeg_private_findings(data) == frozenset()
        assert strip_private_segments(data) == data


def test_ff_d9_inside_an_app1_does_not_end_the_walk(jpeg_tools: types.SimpleNamespace) -> None:
    base = jpeg_tools.pillow_jpeg()
    data = jpeg_tools.insert_after_soi(base, jpeg_tools.segment(0xE1, b"Exif\x00\x00ab\xff\xd9cd"))
    assert jpeg_private_findings(data) == frozenset({"app1"})
    assert strip_private_segments(data) == base


def test_ff_d9_inside_a_com_and_an_app13(jpeg_tools: types.SimpleNamespace) -> None:
    base = jpeg_tools.pillow_jpeg()
    data = jpeg_tools.insert_after_soi(
        base,
        jpeg_tools.segment(0xFE, b"\xff\xd9\xff\xd8"),
        jpeg_tools.segment(0xED, jpeg_tools.IPTC_PREFIX + b"\xff\xd9"),
    )
    assert jpeg_private_findings(data) == frozenset({"com", "app13"})
    assert strip_private_segments(data) == base


def test_icc_and_adobe_segments_are_kept(jpeg_tools: types.SimpleNamespace) -> None:
    base = jpeg_tools.pillow_jpeg()
    icc = jpeg_tools.segment(0xE2, b"ICC_PROFILE\x00\x01\x01" + b"\x00" * 20)
    adobe = jpeg_tools.segment(0xEE, b"Adobe\x00\x64\x00\x00\x00\x00\x01")
    data = jpeg_tools.insert_after_soi(base, icc, adobe)
    assert jpeg_private_findings(data) == frozenset()
    assert strip_private_segments(data) == data


def test_fill_bytes_are_copied(jpeg_tools: types.SimpleNamespace) -> None:
    base = jpeg_tools.pillow_jpeg()
    # Fill bytes before the APP0 (after the SOI) and before the EOI.
    filled = base[:2] + b"\xff\xff" + base[2:-2] + b"\xff\xff\xff\xd9"
    assert strip_private_segments(filled) == filled
    # Fill bytes before a removed segment stay (they become fill of the next marker).
    with_app1 = base[:2] + b"\xff\xff" + jpeg_tools.segment(0xE1, b"Exif\x00\x00x") + base[2:]
    assert strip_private_segments(with_app1) == base[:2] + b"\xff\xff" + base[2:]
    assert load_image(strip_private_segments(with_app1)).size == (64, 48)


def test_restart_markers_and_stuffed_bytes_stay_in_the_entropy_data(
    jpeg_tools: types.SimpleNamespace,
) -> None:
    image = jpeg_tools.noise_image((128, 96))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95, restart_marker_blocks=1)
    data = buffer.getvalue()
    sos = data.index(b"\xff\xda")
    entropy = data[sos:]
    assert any(bytes((0xFF, rst)) in entropy for rst in range(0xD0, 0xD8))
    assert b"\xff\x00" in entropy
    trailer_data = data + b"tail"
    assert jpeg_private_findings(trailer_data) == frozenset({"trailer"})
    assert strip_private_segments(trailer_data) == data
    assert np.array_equal(
        jpeg_tools.pixels(strip_private_segments(trailer_data)), jpeg_tools.pixels(data)
    )


def test_progressive_jpeg_with_many_scans(jpeg_tools: types.SimpleNamespace) -> None:
    data = jpeg_tools.pillow_jpeg((120, 90), progressive=True)
    assert data.count(b"\xff\xda") > 1
    dirty = jpeg_tools.insert_after_soi(data, jpeg_tools.segment(0xFE, b"comment")) + b"\x00" * 9
    clean = strip_private_segments(dirty)
    assert clean == data
    assert np.array_equal(jpeg_tools.pixels(clean), jpeg_tools.pixels(dirty))


def test_tem_marker_has_no_length(jpeg_tools: types.SimpleNamespace) -> None:
    base = jpeg_tools.pillow_jpeg()
    data = base[:2] + b"\xff\x01" + base[2:]
    assert strip_private_segments(data) == data


def test_metadata_only_after_the_first_scan(jpeg_tools: types.SimpleNamespace) -> None:
    base = jpeg_tools.pillow_jpeg()
    # A COM right before the EOI, after the entropy-coded data.
    data = base[:-2] + jpeg_tools.segment(0xFE, b"late") + base[-2:]
    assert jpeg_private_findings(data) == frozenset({"com"})
    assert strip_private_segments(data) == base


def _broken_samples(jpeg_tools: types.SimpleNamespace) -> dict[str, bytes]:
    base = jpeg_tools.pillow_jpeg()
    app0_length_1 = base[:2] + b"\xff\xe0\x00\x01" + base[2:]
    return {
        "not a jpeg": b"not a jpeg",
        "empty": b"",
        "soi only": b"\xff\xd8",
        "first 100 bytes": base[:100],
        "no eoi": base[:-2],
        "app0 length 1": app0_length_1,
        "app0 length 0": base[:2] + b"\xff\xe0\x00\x00" + base[2:],
        "length beyond the end": base[:2] + b"\xff\xe0\xff\xff" + base[4:40],
        "length cut": b"\xff\xd8\xff\xe0\x00",
        "marker cut": b"\xff\xd8\xff",
        "garbage between segments": base[:2] + b"\x00" + base[2:],
        "ff 00 outside a scan": base[:2] + b"\xff\x00" + base[2:],
        "lone ff at the end of a scan": base[:-2] + b"\xff",
        "png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 20,
    }


@pytest.mark.parametrize(
    "name",
    [
        "not a jpeg",
        "empty",
        "soi only",
        "first 100 bytes",
        "no eoi",
        "app0 length 1",
        "app0 length 0",
        "length beyond the end",
        "length cut",
        "marker cut",
        "garbage between segments",
        "ff 00 outside a scan",
        "lone ff at the end of a scan",
        "png",
    ],
)
def test_structure_errors_never_show_input_bytes(
    jpeg_tools: types.SimpleNamespace, name: str
) -> None:
    data = _broken_samples(jpeg_tools)[name]
    for function in (strip_private_segments, jpeg_private_findings):
        with pytest.raises(JpegStructureError) as excinfo:
            function(data)
        message = str(excinfo.value)
        assert "\\x" not in message and "b'" not in message
        if data:
            assert repr(data[:8])[2:-1] not in message


def test_structure_error_is_a_value_error() -> None:
    assert issubclass(JpegStructureError, ValueError)


def test_output_never_has_more_markers_than_the_input(jpeg_tools: types.SimpleNamespace) -> None:
    data, _ = jpeg_tools.with_metadata()
    clean = strip_private_segments(data)
    assert len(clean) < len(data)
    assert clean.count(b"\xff\xda") == data.count(b"\xff\xda")  # SOS headers are kept
    assert load_image(clean).size == load_image(data).size


# ------------------------------------------------------------------- EXIF rotation (section 4.8)


def _load_pixels(data: bytes) -> np.ndarray:
    return np.asarray(load_image(data))


def _parity(data: bytes) -> bool:
    """Whether ``load_image`` gives the same image for ``data`` and for the stripped bytes."""
    before, after = _load_pixels(data), _load_pixels(strip_private_segments(data))
    return before.shape == after.shape and np.array_equal(before, after)


@pytest.mark.parametrize("value", range(1, 9))
def test_orientation_values_1_to_8(jpeg_tools: types.SimpleNamespace, value: int) -> None:
    data = jpeg_tools.rotated_jpeg(value)
    assert has_exif_rotation(data) is (value != 1)
    # Exactly the cases where stripping the APP1 would change what load_image returns
    # (2 and 4 only flip: same size, other pixels).
    assert _parity(data) is (value == 1)


def test_rot6_is_portrait_for_load_image(jpeg_tools: types.SimpleNamespace) -> None:
    rot6 = jpeg_tools.rotated_jpeg(6)
    assert load_image(rot6).size == (48, 64)
    assert load_image(strip_private_segments(rot6)).size == (64, 48)


def test_no_exif_or_no_orientation_tag(jpeg_tools: types.SimpleNamespace) -> None:
    assert has_exif_rotation(jpeg_tools.pillow_jpeg()) is False
    assert has_exif_rotation(jpeg_tools.pillow_jpeg(exif=jpeg_tools.gps_exif())) is False
    data, _ = jpeg_tools.with_metadata()
    assert has_exif_rotation(data) is False
    assert _parity(data)


@pytest.mark.parametrize("element", [False, True])
@pytest.mark.parametrize(("value", "expected"), [(6, True), (3, True), (1, False), (0, False)])
def test_orientation_only_in_the_xmp(
    jpeg_tools: types.SimpleNamespace, element: bool, value: int, expected: bool
) -> None:
    data = jpeg_tools.xmp_orientation_jpeg(value, element=element)
    assert has_exif_rotation(data) is expected
    assert _parity(data) is not expected


def test_exif_orientation_1_wins_over_the_xmp(jpeg_tools: types.SimpleNamespace) -> None:
    xmp = jpeg_tools.segment(0xE1, jpeg_tools.XMP_PREFIX + b'<x:xmpmeta tiff:Orientation="6"/>')
    data = jpeg_tools.insert_after_soi(jpeg_tools.rotated_jpeg(1), xmp)
    assert has_exif_rotation(data) is False  # Pillow reads the XMP only without the EXIF tag
    assert _parity(data)


@pytest.mark.parametrize("value", [0, 9, 255, 65535])
def test_values_out_of_range_are_not_a_rotation(
    jpeg_tools: types.SimpleNamespace, value: int
) -> None:
    data = jpeg_tools.rotated_jpeg(value)
    assert has_exif_rotation(data) is False
    assert _parity(data)


@pytest.mark.parametrize(
    ("field_type", "value", "expected"),
    [
        (3, struct.pack("<H", 6), True),  # SHORT, the standard type
        (4, struct.pack("<I", 6), True),  # LONG
        (8, struct.pack("<h", 6), True),  # SSHORT
        (5, struct.pack("<II", 6, 1), True),  # RATIONAL 6/1: exif_transpose applies it
        (11, struct.pack("<f", 6.0), True),  # FLOAT 6.0: idem
        (12, struct.pack("<d", 8.0), True),  # DOUBLE 8.0: idem
        (5, struct.pack("<II", 13, 2), False),  # RATIONAL 6.5: not applied
        (2, b"6\x00", False),  # ASCII "6": not applied
        (1, b"\x06", False),  # BYTE: Pillow gives bytes, not applied
    ],
)
def test_odd_tiff_types_follow_exif_transpose(
    jpeg_tools: types.SimpleNamespace, field_type: int, value: bytes, expected: bool
) -> None:
    data = jpeg_tools.pillow_jpeg(exif=jpeg_tools.tiff_orientation_exif(field_type, value))
    assert has_exif_rotation(data) is expected
    assert _parity(data) is not expected


def test_rotation_is_read_from_the_header_only(jpeg_tools: types.SimpleNamespace) -> None:
    rot6 = jpeg_tools.rotated_jpeg(6)
    sos = rot6.index(b"\xff\xda")
    # Cut in the middle of the entropy-coded data: a load() would fail, the header is enough.
    assert has_exif_rotation(rot6[: sos + 40]) is True


@pytest.mark.parametrize("data", [b"not a jpeg", b"", b"\xff\xd8\xff\xe1\x00"])
def test_pillow_errors_become_structure_errors(data: bytes) -> None:
    with pytest.raises(JpegStructureError) as excinfo:
        has_exif_rotation(data)
    message = str(excinfo.value)
    assert message == "cannot read the JPEG EXIF orientation"
    assert excinfo.value.__cause__ is None


def test_png_is_not_read_as_jpeg(make_image: Callable[..., bytes]) -> None:
    png = make_image(fmt="PNG")
    with pytest.raises(JpegStructureError):
        has_exif_rotation(png)


@pytest.mark.parametrize("error", [OSError("boom"), ValueError("x"), SyntaxError("y")])
def test_any_pillow_exception_is_a_structure_error(
    jpeg_tools: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(jpeg_module.Image, "open", broken)
    with pytest.raises(JpegStructureError):
        has_exif_rotation(jpeg_tools.rotated_jpeg(6))


def test_memory_error_is_not_converted(
    jpeg_tools: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise MemoryError

    monkeypatch.setattr(jpeg_module.Image, "open", broken)
    with pytest.raises(MemoryError):
        has_exif_rotation(jpeg_tools.rotated_jpeg(6))


def test_rotation_check_logs_nothing(
    jpeg_tools: types.SimpleNamespace, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    for value in (1, 6):
        has_exif_rotation(jpeg_tools.rotated_jpeg(value))
    with pytest.raises(JpegStructureError):
        has_exif_rotation(b"not a jpeg")
    assert [r for r in caplog.records if r.name.startswith("qc_edge")] == []


# ------------------------------------------------------------ exif_orientation (SPEC-036 4.3)


@pytest.mark.parametrize("value", range(1, 9))
def test_exif_orientation_values_1_to_8(jpeg_tools: types.SimpleNamespace, value: int) -> None:
    data = jpeg_tools.rotated_jpeg(value)
    result = exif_orientation(data)
    assert result == value and type(result) is int
    assert has_exif_rotation(data) == (result in range(2, 9))


def test_exif_orientation_absent(jpeg_tools: types.SimpleNamespace) -> None:
    assert exif_orientation(jpeg_tools.pillow_jpeg()) == 1
    assert exif_orientation(jpeg_tools.pillow_jpeg(exif=jpeg_tools.gps_exif())) == 1
    assert exif_orientation(jpeg_tools.with_metadata()[0]) == 1


@pytest.mark.parametrize("value", [0, 9, 255, 65535])
def test_exif_orientation_out_of_range_is_1(jpeg_tools: types.SimpleNamespace, value: int) -> None:
    assert exif_orientation(jpeg_tools.rotated_jpeg(value)) == 1


@pytest.mark.parametrize(
    ("field_type", "value", "expected"),
    [
        (3, struct.pack("<H", 6), 6),
        (5, struct.pack("<II", 6, 1), 6),  # IFDRational(6, 1)
        (11, struct.pack("<f", 6.0), 6),  # 6.0
        (12, struct.pack("<d", 8.0), 8),
        (5, struct.pack("<II", 13, 2), 1),  # 6.5 is never applied
        (2, b"6\x00", 1),  # ASCII "6"
        (1, b"\x06", 1),  # BYTE
    ],
)
def test_exif_orientation_odd_types(
    jpeg_tools: types.SimpleNamespace, field_type: int, value: bytes, expected: int
) -> None:
    data = jpeg_tools.pillow_jpeg(exif=jpeg_tools.tiff_orientation_exif(field_type, value))
    result = exif_orientation(data)
    assert result == expected and type(result) is int
    assert has_exif_rotation(data) == (result in range(2, 9))


@pytest.mark.parametrize(("value", "expected"), [(6, 6), (3, 3), (1, 1), (0, 1)])
def test_exif_orientation_only_in_the_xmp(
    jpeg_tools: types.SimpleNamespace, value: int, expected: int
) -> None:
    assert exif_orientation(jpeg_tools.xmp_orientation_jpeg(value)) == expected


@pytest.mark.parametrize("data", [b"not a jpeg", b"", b"\xff\xd8\xff\xe1\x00"])
def test_exif_orientation_pillow_errors(data: bytes) -> None:
    with pytest.raises(JpegStructureError) as excinfo:
        exif_orientation(data)
    assert str(excinfo.value) == "cannot read the JPEG EXIF orientation"
    assert excinfo.value.__cause__ is None


def test_exif_orientation_memory_error_propagates(
    jpeg_tools: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise MemoryError

    monkeypatch.setattr(jpeg_module.Image, "open", broken)
    with pytest.raises(MemoryError):
        exif_orientation(jpeg_tools.rotated_jpeg(6))
