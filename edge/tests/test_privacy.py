"""``python -m qc_edge.privacy`` (SPEC-025 section 4.9).

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
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from qc_edge import privacy
from qc_edge.collect import MANIFEST_COLUMNS
from qc_edge.jpeg import jpeg_private_findings

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
    (other / "upper.JPG").write_bytes(b"not checked: only *.jpg")
    code = privacy.main(["--dataset-dir", str(root), "--fix"])
    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert out == [
        "raw/other/_/broken.jpg: invalid",
        "raw/other/_/gps.jpg: app1",
        "fixed raw/other/_/gps.jpg",
        "checked 2 images, 2 with private data",
    ]
    assert (other / "broken.jpg").read_bytes() == broken


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
