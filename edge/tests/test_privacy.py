"""``python -m qc_edge.privacy`` (SPEC-025 section 4.9; SPEC-030 sections 4.4 and 4.5).

Every dataset here is built in ``tmp_path`` from images generated in memory (R-14).
"""

from __future__ import annotations

import fcntl
import logging
import os
import secrets
import socket
import stat
import subprocess
import sys
import threading
import time
import types
import unicodedata
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from qc_edge import jpeg as jpeg_module
from qc_edge import privacy
from qc_edge.collect import MANIFEST_COLUMNS
from qc_edge.jpeg import JpegStructureError, jpeg_private_findings
from qc_preprocess import load_image

HEADER = ",".join(MANIFEST_COLUMNS) + "\n"


@pytest.fixture
def restore_umask() -> Iterator[Callable[[int], int]]:
    original = os.umask(0o022)
    os.umask(original)
    try:
        yield os.umask
    finally:
        os.umask(original)


@pytest.fixture
def dataset(tmp_path: Path, jpeg_tools: types.SimpleNamespace) -> types.SimpleNamespace:
    """``a.jpg`` clean, ``b.jpg`` EXIF GPS only, ``c.jpg`` trailer only, ``d.jpg`` a symlink to a
    JPEG with metadata outside the dataset."""
    root = tmp_path / "dataset"
    fair = root / "raw" / "screw" / "fair"
    fair.mkdir(parents=True)
    (root / "manifest.csv").write_text(HEADER, encoding="utf-8")
    clean = jpeg_tools.pillow_jpeg()
    (fair / "a.jpg").write_bytes(clean)
    (fair / "b.jpg").write_bytes(jpeg_tools.pillow_jpeg(exif=jpeg_tools.gps_exif()))
    (fair / "c.jpg").write_bytes(clean + jpeg_tools.TRAILER)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(jpeg_tools.with_metadata()[0])
    (fair / "d.jpg").symlink_to(outside)
    return types.SimpleNamespace(root=root, fair=fair, outside=outside)


def _snapshot(root: Path, outside: Path) -> dict[str, bytes]:
    files = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}
    files["<outside>"] = outside
    return {name: path.read_bytes() for name, path in files.items()}


def test_scan_without_fix_only_reads(
    dataset: types.SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _snapshot(dataset.root, dataset.outside)
    code = privacy.main(["--dataset-dir", str(dataset.root)])
    out = capsys.readouterr().out
    assert code == 1
    assert out.splitlines() == [
        "raw/screw/fair/b.jpg: app1",
        "raw/screw/fair/c.jpg: trailer",
        "checked 3 images, 2 with private data",
    ]
    assert str(dataset.root) not in out
    assert "54" not in out and "30.21" not in out
    assert _snapshot(dataset.root, dataset.outside) == before
    assert not (dataset.root / "manifest.csv.lock").exists()


@pytest.mark.parametrize("mask", [0o022, 0o277])
def test_fix_rewrites_only_the_images_with_findings(
    dataset: types.SimpleNamespace,
    jpeg_tools: types.SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
    restore_umask: Callable[[int], int],
    mask: int,
) -> None:
    before = _snapshot(dataset.root, dataset.outside)
    pixels_before = {name: jpeg_tools.pixels(before[f"raw/screw/fair/{name}.jpg"]) for name in "bc"}
    restore_umask(mask)
    code = privacy.main(["--dataset-dir", str(dataset.root), "--fix"])
    out = capsys.readouterr().out.splitlines()
    restore_umask(0o022)
    assert code == 0
    assert "fixed raw/screw/fair/b.jpg" in out
    assert "fixed raw/screw/fair/c.jpg" in out
    assert out[-1] == "checked 3 images, 2 with private data"
    for name in "bc":
        path = dataset.fair / f"{name}.jpg"
        data = path.read_bytes()
        assert jpeg_private_findings(data) == frozenset()
        assert (jpeg_tools.pixels(data) == pixels_before[name]).all()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    after = _snapshot(dataset.root, dataset.outside)
    for unchanged in ("raw/screw/fair/a.jpg", "manifest.csv", "<outside>"):
        assert after[unchanged] == before[unchanged]
    assert (dataset.fair / "d.jpg").is_symlink()
    assert sorted(p.name for p in dataset.fair.iterdir()) == ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]
    lock = dataset.root / "manifest.csv.lock"
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600
    assert privacy.main(["--dataset-dir", str(dataset.root)]) == 0
    assert capsys.readouterr().out.splitlines() == ["checked 3 images, 0 with private data"]


def test_findings_are_sorted_and_comma_separated(
    tmp_path: Path, jpeg_tools: types.SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "d"
    (root / "raw" / "nut" / "good").mkdir(parents=True)
    (root / "raw" / "nut" / "good" / "x.jpg").write_bytes(jpeg_tools.with_metadata()[0])
    assert privacy.main(["--dataset-dir", str(root)]) == 1
    assert capsys.readouterr().out.splitlines()[0] == (
        "raw/nut/good/x.jpg: app1, app13, com, trailer"
    )


def test_invalid_images_are_reported_and_never_rewritten(
    tmp_path: Path, jpeg_tools: types.SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "d"
    other = root / "raw" / "other" / "_"
    other.mkdir(parents=True)
    broken = jpeg_tools.pillow_jpeg()[:100]
    (other / "broken.jpg").write_bytes(broken)
    (other / "gps.jpg").write_bytes(jpeg_tools.pillow_jpeg(exif=jpeg_tools.gps_exif()))
    (other / "notes.txt").write_bytes(b"not an image")
    (other / "upper.JPG").write_bytes(b"checked since SPEC-030: not a JPEG")
    code = privacy.main(["--dataset-dir", str(root), "--fix"])
    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert out == [
        "raw/other/_/broken.jpg: invalid",
        "raw/other/_/gps.jpg: app1",
        "fixed raw/other/_/gps.jpg",
        "raw/other/_/notes.txt: invalid",
        "raw/other/_/upper.JPG: invalid",
        "checked 4 images, 4 with private data",
    ]
    assert (other / "broken.jpg").read_bytes() == broken
    assert (other / "notes.txt").read_bytes() == b"not an image"


@pytest.fixture
def rotated(tmp_path: Path, jpeg_tools: types.SimpleNamespace) -> types.SimpleNamespace:
    """``e.jpg`` with ``Orientation=6`` (and GPS), ``f.jpg`` with ``Orientation=1`` (and GPS),
    ``g.jpg`` with ``tiff:Orientation="8"`` only in the XMP."""
    root = tmp_path / "rotated"
    fair = root / "raw" / "screw" / "fair"
    fair.mkdir(parents=True)
    (root / "manifest.csv").write_text(HEADER, encoding="utf-8")
    (fair / "e.jpg").write_bytes(jpeg_tools.rotated_jpeg(6))
    (fair / "f.jpg").write_bytes(jpeg_tools.rotated_jpeg(1))
    (fair / "g.jpg").write_bytes(jpeg_tools.xmp_orientation_jpeg(8))
    return types.SimpleNamespace(root=root, fair=fair)


def test_orientation_is_a_finding_without_fix(
    rotated: types.SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert privacy.main(["--dataset-dir", str(rotated.root)]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "raw/screw/fair/e.jpg: app1, orientation",
        "raw/screw/fair/f.jpg: app1",
        "raw/screw/fair/g.jpg: app1, orientation",
        "checked 3 images, 3 with private data",
    ]


@pytest.mark.parametrize("mask", [0o022, 0o277])
def test_fix_never_rewrites_an_orientation_finding(
    rotated: types.SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
    restore_umask: Callable[[int], int],
    mask: int,
) -> None:
    before = {name: (rotated.fair / name).read_bytes() for name in ("e.jpg", "f.jpg", "g.jpg")}
    restore_umask(mask)
    code = privacy.main(["--dataset-dir", str(rotated.root), "--fix"])
    restore_umask(0o022)
    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert out == [
        "raw/screw/fair/e.jpg: app1, orientation",
        "raw/screw/fair/f.jpg: app1",
        "fixed raw/screw/fair/f.jpg",
        "raw/screw/fair/g.jpg: app1, orientation",
        "checked 3 images, 3 with private data",
    ]
    for name in ("e.jpg", "g.jpg"):
        assert (rotated.fair / name).read_bytes() == before[name]
    fixed = rotated.fair / "f.jpg"
    assert jpeg_private_findings(fixed.read_bytes()) == frozenset()
    assert stat.S_IMODE(fixed.stat().st_mode) == 0o600
    assert load_image(fixed).size == load_image(before["f.jpg"]).size
    assert np.array_equal(np.asarray(load_image(fixed)), np.asarray(load_image(before["f.jpg"])))
    assert privacy.main(["--dataset-dir", str(rotated.root)]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "raw/screw/fair/e.jpg: app1, orientation",
        "raw/screw/fair/g.jpg: app1, orientation",
        "checked 3 images, 2 with private data",
    ]


def test_unreadable_orientation_is_only_invalid(
    rotated: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken(data: bytes) -> bool:
        raise JpegStructureError("cannot read the JPEG EXIF orientation")

    monkeypatch.setattr(jpeg_module, "has_exif_rotation", broken)
    before = (rotated.fair / "f.jpg").read_bytes()
    assert privacy.main(["--dataset-dir", str(rotated.root), "--fix"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "raw/screw/fair/e.jpg: invalid",
        "raw/screw/fair/f.jpg: invalid",
        "raw/screw/fair/g.jpg: invalid",
        "checked 3 images, 3 with private data",
    ]
    assert (rotated.fair / "f.jpg").read_bytes() == before


def test_rotation_is_not_checked_when_the_walk_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def never(data: bytes) -> bool:
        raise AssertionError("has_exif_rotation runs only after jpeg_private_findings")

    monkeypatch.setattr(jpeg_module, "has_exif_rotation", never)
    root = tmp_path / "d"
    (root / "raw").mkdir(parents=True)
    (root / "raw" / "x.jpg").write_bytes(b"not a jpeg")
    assert privacy.main(["--dataset-dir", str(root)]) == 1
    assert capsys.readouterr().out.splitlines()[0] == "raw/x.jpg: invalid"


def test_dataset_without_raw_is_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert privacy.main(["--dataset-dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "checked 0 images, 0 with private data\n"


def test_symlinked_directories_are_not_followed(
    tmp_path: Path, jpeg_tools: types.SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "d"
    (root / "raw").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "x.jpg").write_bytes(jpeg_tools.with_metadata()[0])
    (root / "raw" / "linked").symlink_to(elsewhere, target_is_directory=True)
    assert privacy.main(["--dataset-dir", str(root)]) == 0
    assert capsys.readouterr().out == "checked 0 images, 0 with private data\n"


def test_fix_failure_leaves_the_file_and_no_temporary(
    dataset: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    before = (dataset.fair / "b.jpg").read_bytes()

    def failing_replace(src: object, dst: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", failing_replace)
    with caplog.at_level(logging.ERROR):
        code = privacy.main(["--dataset-dir", str(dataset.root), "--fix"])
    out = capsys.readouterr().out
    assert code == 1
    assert "fixed" not in out
    assert (dataset.fair / "b.jpg").read_bytes() == before
    assert sorted(p.name for p in dataset.fair.iterdir()) == ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]
    assert "cannot fix raw/screw/fair/b.jpg: No space left on device" in caplog.text


def test_fix_waits_for_the_collect_lock(dataset: types.SimpleNamespace) -> None:
    lock_path = dataset.root / "manifest.csv.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    result: list[int] = []
    worker = threading.Thread(
        target=lambda: result.append(privacy.main(["--dataset-dir", str(dataset.root), "--fix"]))
    )
    try:
        worker.start()
        time.sleep(0.3)
        assert result == []  # still waiting for the flock
        assert jpeg_private_findings((dataset.fair / "b.jpg").read_bytes()) == {"app1"}
    finally:
        os.close(fd)
    worker.join(timeout=10)
    assert result == [0]


@pytest.mark.parametrize(
    "argv_builder",
    [
        lambda root, marker: ["--dataset-dir", str(root / "missing")],
        lambda root, marker: ["--dataset-dir", str(root / "manifest.csv")],
        lambda root, marker: ["--dataset-dir", str(root), f"--token={marker}"],
        lambda root, marker: ["--dataset-dir", str(root), marker],
        lambda root, marker: ["--dataset-dir", str(root), f"--fix={marker}"],
        lambda root, marker: [f"--dataset-dir={root}", f"--X{marker}"],
        lambda root, marker: [],
        lambda root, marker: ["--dataset-dir"],
    ],
    ids=["missing", "file", "token", "positional", "fix-value", "bad-option", "none", "no-value"],
)
def test_usage_errors_exit_2_without_echo(
    dataset: types.SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    argv_builder: Callable[[Path, str], list[str]],
) -> None:
    marker = "m" + secrets.token_hex(12)
    with caplog.at_level(logging.DEBUG):
        code = privacy.main(argv_builder(dataset.root, marker))
    captured = capsys.readouterr()
    assert code == 2
    for text in (captured.out, captured.err, caplog.text):
        assert marker not in text


def test_unknown_option_names_are_logged(
    dataset: types.SimpleNamespace, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        code = privacy.main(["--dataset-dir", str(dataset.root), "--token=hidden", "loose"])
    assert code == 2
    assert "unknown command-line argument(s): --token, 1 other" in caplog.text
    assert "hidden" not in caplog.text and "loose" not in caplog.text


def test_main_reads_sys_argv_by_default(
    dataset: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr("sys.argv", ["privacy", "--dataset-dir", str(dataset.root)])
    assert privacy.main() == 1
    assert capsys.readouterr().out.endswith("checked 3 images, 2 with private data\n")


def test_no_network_connection(
    dataset: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert privacy.main(["--dataset-dir", str(dataset.root), "--fix"]) == 0


def test_runs_as_a_module(dataset: types.SimpleNamespace) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "qc_edge.privacy", "--dataset-dir", str(dataset.root)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 1
    assert completed.stdout.endswith("checked 3 images, 2 with private data\n")


# -- SPEC-030 section 4.5: printable paths --------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("raw/screw/fair/a.jpg", "raw/screw/fair/a.jpg"),
        ("raw/porca/ótima/ação ç.jpg", "raw/porca/ótima/ação ç.jpg"),
        ("a\\b.jpg", "a\\\\b.jpg"),
        ("x\nchecked\x1b[8m.jpg", "x\\x0achecked\\x1b[8m.jpg"),
        ("\t\r\x00\x7f", "\\x09\\x0d\\x00\\x7f"),
        ("\x85\x9b", "\\x85\\x9b"),  # C1 controls (Cc)
        ("soft­hyphen", "soft\\xadhyphen"),  # Cf up to 0xFF
        ("rlo‮gpj.jpg", "rlo\\u202egpj.jpg"),  # Cf
        ("zw​﻿", "zw\\u200b\\ufeff"),  # Cf
        ("line para ", "line\\u2028para\\u2029"),  # Zl, Zp
        ("bad\udcff.jpg", "bad\\udcff.jpg"),  # Cs (surrogateescape)
        ("tag\U000e0001", "tag\\U000e0001"),  # Cf above 0xFFFF
        ("emoji \U0001f600 nbsp ", "emoji \U0001f600 nbsp "),  # So, Zs: kept
    ],
)
def test_printable_path(raw: str, expected: str) -> None:
    assert privacy.printable_path(raw) == expected


def test_printable_path_output_has_no_escapable_character() -> None:
    every = "".join(chr(code) for code in range(0x0, 0x3000)) + "\udc80\U000e007f\\"
    shown = privacy.printable_path(every)
    assert all(unicodedata.category(char) not in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in shown)
    shown.encode("utf-8")  # no lone surrogate left


# -- SPEC-030 section 4.4: extensions, other files and temporaries --------------------------------


def _png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def mixed(tmp_path: Path, jpeg_tools: types.SimpleNamespace) -> types.SimpleNamespace:
    root = tmp_path / "mixed"
    fair = root / "raw" / "screw" / "fair"
    fair.mkdir(parents=True)
    (root / "manifest.csv").write_text(HEADER, encoding="utf-8")
    gps = jpeg_tools.pillow_jpeg(exif=jpeg_tools.gps_exif())
    (fair / "a.jpg").write_bytes(jpeg_tools.pillow_jpeg())
    (fair / "B.JPG").write_bytes(gps)
    (fair / "c.Jpeg").write_bytes(gps)
    (fair / "d.png").write_bytes(_png())
    (fair / "e.heic").write_bytes(secrets.token_bytes(64))
    (fair / "f").write_bytes(secrets.token_bytes(16))
    (fair / ".g.jpg.abc123.tmp").write_bytes(secrets.token_bytes(32))
    (fair / "h.jpg").mkdir()
    return types.SimpleNamespace(root=root, fair=fair)


def test_any_case_jpeg_is_checked_and_other_files_are_invalid(
    mixed: types.SimpleNamespace,
    jpeg_tools: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opened: list[str] = []
    real_read = privacy._read

    def spy_read(path: Path) -> bytes:
        opened.append(path.name)
        return real_read(path)

    monkeypatch.setattr(privacy, "_read", spy_read)
    assert privacy.main(["--dataset-dir", str(mixed.root)]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "raw/screw/fair/B.JPG: app1",
        "raw/screw/fair/c.Jpeg: app1",
        "raw/screw/fair/d.png: invalid",
        "raw/screw/fair/e.heic: invalid",
        "raw/screw/fair/f: invalid",
        "checked 6 images, 5 with private data",
    ]
    assert sorted(opened) == ["B.JPG", "a.jpg", "c.Jpeg"]  # the other files are never read


def test_fix_keeps_names_and_leaves_other_files(
    mixed: types.SimpleNamespace,
    jpeg_tools: types.SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    others = ("d.png", "e.heic", "f", ".g.jpg.abc123.tmp")
    before = {name: (mixed.fair / name).read_bytes() for name in (*others, "B.JPG", "c.Jpeg")}
    code = privacy.main(["--dataset-dir", str(mixed.root), "--fix"])
    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert "fixed raw/screw/fair/B.JPG" in out
    assert "fixed raw/screw/fair/c.Jpeg" in out
    assert not any(line.startswith("fixed") and "fair/d" in line for line in out)
    for name in ("B.JPG", "c.Jpeg"):
        data = (mixed.fair / name).read_bytes()
        assert jpeg_private_findings(data) == frozenset()
        assert np.array_equal(np.asarray(load_image(data)), np.asarray(load_image(before[name])))
    for name in others:
        assert (mixed.fair / name).read_bytes() == before[name]
    assert sorted(p.name for p in mixed.fair.iterdir()) == sorted(
        [".g.jpg.abc123.tmp", "B.JPG", "a.jpg", "c.Jpeg", "d.png", "e.heic", "f", "h.jpg"]
    )
    assert privacy.main(["--dataset-dir", str(mixed.root)]) == 1
    assert capsys.readouterr().out.splitlines()[-1] == "checked 6 images, 3 with private data"


@pytest.mark.parametrize(
    ("name", "listed"),
    [
        (".x.jpg.k3j2.tmp", False),  # an edge temporary
        (".tmp", False),
        ("x.jpg.tmp", True),  # no leading dot: not an edge temporary
        (".x.jpg.TMP", True),  # mkstemp always uses the lowercase suffix
        (".hidden.jpg", True),  # checked as a JPEG
    ],
)
def test_only_edge_temporaries_are_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str, listed: bool
) -> None:
    root = tmp_path / "d"
    (root / "raw").mkdir(parents=True)
    (root / "raw" / name).write_bytes(b"not a jpeg")
    code = privacy.main(["--dataset-dir", str(root)])
    out = capsys.readouterr().out
    if listed:
        assert code == 1
        assert out == f"raw/{name}: invalid\nchecked 1 images, 1 with private data\n"
    else:
        assert code == 0
        assert out == "checked 0 images, 0 with private data\n"


def test_symlinks_to_other_files_are_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "d"
    (root / "raw").mkdir(parents=True)
    target = tmp_path / "notes.txt"
    target.write_bytes(b"outside")
    (root / "raw" / "notes.txt").symlink_to(target)
    os.mkfifo(root / "raw" / "pipe")
    assert privacy.main(["--dataset-dir", str(root)]) == 0
    assert capsys.readouterr().out == "checked 0 images, 0 with private data\n"


# -- SPEC-030 section 4.5: escaped output, unreadable files ---------------------------------------


def test_a_hostile_name_cannot_forge_lines(
    tmp_path: Path, jpeg_tools: types.SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "d"
    fair = root / "raw" / "screw" / "fair"
    fair.mkdir(parents=True)
    name = "x\nchecked 9 images, 0 with private data\x1b[8m.jpg"
    (fair / name).write_bytes(jpeg_tools.with_metadata()[0])
    assert privacy.main(["--dataset-dir", str(root), "--fix"]) == 0
    out = capsys.readouterr().out
    shown = "raw/screw/fair/x\\x0achecked 9 images, 0 with private data\\x1b[8m.jpg"
    assert out.splitlines() == [
        f"{shown}: app1, app13, com, trailer",
        f"fixed {shown}",
        "checked 1 images, 1 with private data",
    ]
    assert "\x1b" not in out
    assert out.count("\n") == 3
    assert jpeg_private_findings((fair / name).read_bytes()) == frozenset()


def test_a_name_that_is_not_utf8_is_escaped(
    tmp_path: Path, jpeg_tools: types.SimpleNamespace
) -> None:
    root = tmp_path / "d"
    fair = root / "raw" / "screw" / "fair"
    fair.mkdir(parents=True)
    target = os.fsencode(fair) + b"/bad\xff.jpg"
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT, 0o600)
    except OSError:
        pytest.skip("the file system refuses names that are not UTF-8")
    with os.fdopen(fd, "wb") as handle:
        handle.write(jpeg_tools.with_metadata()[0])
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    completed = subprocess.run(
        [sys.executable, "-m", "qc_edge.privacy", "--dataset-dir", str(root)],
        capture_output=True,
        timeout=60,
        check=False,
        env=env,
    )
    assert completed.returncode == 1
    assert completed.stdout.splitlines() == [
        b"raw/screw/fair/bad\\udcff.jpg: app1, app13, com, trailer",
        b"checked 1 images, 1 with private data",
    ]
    assert b"Traceback" not in completed.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file with mode 0o000")
def test_an_unreadable_file_is_listed(
    tmp_path: Path,
    jpeg_tools: types.SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    root = tmp_path / "d"
    fair = root / "raw" / "screw" / "fair"
    fair.mkdir(parents=True)
    (fair / "a.jpg").write_bytes(jpeg_tools.pillow_jpeg())
    blocked = fair / "z\x1b.jpg"
    blocked.write_bytes(jpeg_tools.with_metadata()[0])
    blocked.chmod(0o000)
    try:
        with caplog.at_level(logging.ERROR):
            code = privacy.main(["--dataset-dir", str(root)])
    finally:
        blocked.chmod(0o600)
    out = capsys.readouterr().out
    assert code == 1
    assert out.splitlines() == [
        "raw/screw/fair/z\\x1b.jpg: unreadable",
        "checked 1 images, 0 with private data",
    ]
    assert "cannot read raw/screw/fair/z\\x1b.jpg: Permission denied" in caplog.text
    assert "\x1b" not in caplog.text


def test_cannot_fix_logs_the_escaped_path(
    tmp_path: Path,
    jpeg_tools: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    root = tmp_path / "d"
    (root / "raw").mkdir(parents=True)
    (root / "raw" / "y .JPEG").write_bytes(jpeg_tools.with_metadata()[0])

    def failing_replace(src: object, dst: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", failing_replace)
    with caplog.at_level(logging.ERROR):
        assert privacy.main(["--dataset-dir", str(root), "--fix"]) == 1
    assert "cannot fix raw/y\\u2028.JPEG: No space left on device" in caplog.text
    assert " " not in caplog.text
    assert capsys.readouterr().out.splitlines()[0] == "raw/y\\u2028.JPEG: app1, app13, com, trailer"
