"""``python -m qc_edge.privacy --dataset-dir <D> [--fix]`` (SPEC-025 section 4.9, SEC-10-01).

Checks the images already in the dataset, including the ones collected before SPEC-025 or copied
by hand into ``raw/``, for the segments the collect mode never stores (APP1 with EXIF or XMP,
APP13 with IPTC, COM and data after the EOI, such as the video of a Motion Photo). It runs before
every backup of the dataset to the Drive (``docs/dataset-protocol.md`` section 8).

* Without ``--fix`` it only reads: exit code 0 when no image has findings, 1 otherwise.
* With ``--fix``, holding the same ``flock`` as the collect mode, it rewrites every image with
  findings (except ``invalid``) without those segments, through a ``0600`` temporary file,
  ``os.replace`` and ``fsync`` of the directory. ``manifest.csv`` never changes. Exit code 0 when
  only clean files remain, 1 when an ``invalid`` file (or a file that could not be fixed)
  remains.
* An invalid ``--dataset-dir`` or an unknown argument exits with 2; only option names are
  logged, never a value (R-03).

The output (stdout) shows paths relative to ``<D>`` and the fixed finding names, never the
content of a segment (GPS, device, date) nor an absolute path. Errors go to ``logging``. Nothing
here opens a network connection (R-02).
"""

from __future__ import annotations

import logging
import os
import stat
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from qc_edge import jpeg
from qc_edge.argv import (
    EXIT_USAGE_ERROR,
    ArgumentsError,
    QuietArgumentParser,
    describe_arguments,
    resolve_argv,
)
from qc_edge.collect import RAW_SUBDIR, manifest_file_lock, write_private_file_atomically

logger = logging.getLogger("qc_edge.privacy")

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
FINDING_INVALID = "invalid"
IMAGE_SUFFIX = ".jpg"


@dataclass(frozen=True)
class ImageFinding:
    """An image of ``raw/`` with private data (or an ``invalid`` structure)."""

    path: Path
    relative: str
    findings: frozenset[str]

    @property
    def line(self) -> str:
        return f"{self.relative}: {', '.join(sorted(self.findings))}"


def _images(dataset_dir: Path) -> Iterator[tuple[Path, str]]:
    """Regular ``*.jpg`` files under ``raw/``, in path order; symlinks are never followed."""
    raw = dataset_dir / RAW_SUBDIR
    found: list[tuple[str, Path]] = []
    for directory, _, files in os.walk(raw, followlinks=False):
        for name in files:
            if not name.endswith(IMAGE_SUFFIX):
                continue
            path = Path(directory) / name
            try:
                mode = os.lstat(path).st_mode
            except OSError:
                continue
            if stat.S_ISREG(mode):  # symlinks and special files are ignored
                found.append((path.relative_to(dataset_dir).as_posix(), path))
    for relative, path in sorted(found):
        yield path, relative


def _read(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        return handle.read()


def _findings(data: bytes) -> frozenset[str]:
    try:
        return jpeg.jpeg_private_findings(data)
    except jpeg.JpegStructureError:
        return frozenset({FINDING_INVALID})


def _fix(item: ImageFinding, data: bytes, dataset_dir: Path) -> bool:
    """Rewrite ``item`` without its private segments; ``False`` (and an error log) on failure."""
    try:
        clean = jpeg.strip_private_segments(data)
        write_private_file_atomically(
            item.path, lambda handle: handle.write(clean), root=dataset_dir
        )
    except (OSError, jpeg.JpegStructureError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else type(exc).__name__
        logger.error("cannot fix %s: %s", item.relative, reason)
        return False
    return True


def scan(dataset_dir: Path, *, fix: bool, out: TextIO) -> int:
    """Check (and, with ``fix``, rewrite) the images of ``dataset_dir``; returns the exit code."""
    checked = 0
    with_findings = 0
    remaining = False
    for path, relative in _images(dataset_dir):
        try:
            data = _read(path)
        except OSError as exc:
            logger.error("cannot read %s: %s", relative, exc.strerror or type(exc).__name__)
            remaining = True
            continue
        checked += 1
        findings = _findings(data)
        if not findings:
            continue
        with_findings += 1
        item = ImageFinding(path=path, relative=relative, findings=findings)
        out.write(f"{item.line}\n")
        if not fix or FINDING_INVALID in findings:
            remaining = True
            continue
        if _fix(item, data, dataset_dir):
            out.write(f"fixed {relative}\n")
        else:
            remaining = True
    out.write(f"checked {checked} images, {with_findings} with private data\n")
    return EXIT_FINDINGS if remaining else EXIT_CLEAN


def _parser() -> QuietArgumentParser:
    parser = QuietArgumentParser(
        prog="python -m qc_edge.privacy",
        description="Check the dataset images for EXIF, XMP, IPTC, comments and trailers.",
        allow_abbrev=False,
    )
    parser.add_argument("--dataset-dir", required=True, type=Path, help="DATASET_DIR")
    parser.add_argument(
        "--fix", action="store_true", help="rewrite the images without the private segments"
    )
    return parser


def _configure_logging() -> None:
    if not logging.getLogger().handlers and not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; returns the exit code (0, 1 or 2)."""
    _configure_logging()
    arguments = resolve_argv(argv)
    try:
        args, unknown = _parser().parse_known_args(arguments)
    except ArgumentsError:
        logger.error("invalid command-line argument(s): %s", describe_arguments(arguments))
        return EXIT_USAGE_ERROR
    if unknown:
        logger.error("unknown command-line argument(s): %s", describe_arguments(unknown))
        return EXIT_USAGE_ERROR
    dataset_dir: Path = args.dataset_dir
    if not dataset_dir.is_dir():
        logger.error("--dataset-dir must be an existing directory")
        return EXIT_USAGE_ERROR
    if not args.fix:
        return scan(dataset_dir, fix=False, out=sys.stdout)
    try:
        with manifest_file_lock(dataset_dir):
            return scan(dataset_dir, fix=True, out=sys.stdout)
    except OSError as exc:
        logger.error("cannot lock the dataset manifest: %s", exc.strerror or type(exc).__name__)
        return EXIT_FINDINGS


if __name__ == "__main__":
    sys.exit(main())
