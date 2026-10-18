"""qc_edge.jpeg: structural removal of the private JPEG segments (SPEC-025 section 4.8)."""

from __future__ import annotations

import io
import types

import numpy as np
import pytest
from PIL import Image

from qc_edge.jpeg import (
    PRIVATE_FINDINGS,
    JpegStructureError,
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
