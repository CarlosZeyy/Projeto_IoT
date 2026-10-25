"""``python -m qc_edge.privacy --dataset-dir <D> [--fix]`` (SPEC-025 section 4.9, SEC-10-01).

Checks the images already in the dataset, including the ones collected before SPEC-025 or copied
by hand into ``raw/``, for the segments the collect mode never stores (APP1 with EXIF or XMP,
APP13 with IPTC, COM and data after the EOI, such as the video of a Motion Photo), and for an
EXIF rotation (finding ``orientation``, ``qc_edge.jpeg.has_exif_rotation``). It runs before
every backup of the dataset to the Drive (``docs/dataset-protocol.md`` section 8).

* Without ``--fix`` it only reads: exit code 0 when no image has findings, 1 otherwise.
* With ``--fix``, holding the same ``flock`` as the collect mode, it rewrites every image with
  findings (except ``invalid`` and ``orientation``) without those segments, through a ``0600``
  temporary file, ``os.replace`` and ``fsync`` of the directory. ``manifest.csv`` never changes.
  Exit code 0 when only clean files remain, 1 when an ``invalid`` or ``orientation`` file (or a
  file that could not be fixed) remains. An ``orientation`` file is never stripped: without the
  APP1, ``qc_preprocess.load_image`` would no longer rotate it (ADR-004); the photo is taken
  again through the ``/capture`` page.
* An invalid ``--dataset-dir`` or an unknown argument exits with 2; only option names are
  logged, never a value (R-03).

Since SPEC-030 (sections 4.4 and 4.5):

* every regular file of ``raw/`` whose name ends with ``.jpg`` or ``.jpeg`` in any case is
  checked (and fixed, keeping its name); any other regular file (``.png``, ``.heic``, no
  extension...) gets the finding ``invalid`` without being read. The temporary files of the edge
  itself (name starting with ``.`` and ending with ``.tmp``) are ignored;
* every path written to stdout or to the log goes through ``printable_path``, which escapes the
  control, format, surrogate and line/paragraph separator characters, so a file name cannot
  forge an output line or drive the terminal;
* a file that cannot be read is listed as ``<path>: unreadable`` (besides the error log); it is
  not counted and makes the exit code 1.

The output (stdout) shows paths relative to ``<D>`` and the fixed finding names, never the
content of a segment (GPS, device, date) nor an absolute path. Errors go to ``logging``, with the
``PIL`` logger at ``INFO`` at least, so a root logger in ``DEBUG`` does not show the EXIF tags
(SPEC-038 section 4.4). Nothing here opens a network connection (R-02).
"""

from __future__ import annotations

import logging
import os
import stat
import sys
import unicodedata
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
FINDING_ORIENTATION = "orientation"
UNREADABLE = "unreadable"
# Findings that ``--fix`` never rewrites: the file stays and the exit code is 1.
UNFIXABLE_FINDINGS = frozenset({FINDING_INVALID, FINDING_ORIENTATION})
JPEG_SUFFIXES = (".jpg", ".jpeg")  # compared with the lowercase name
TEMPORARY_PREFIX = "."
TEMPORARY_SUFFIX = ".tmp"  # ``write_private_file_atomically`` (``mkstemp``) of ``qc_edge.collect``
_ESCAPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def printable_path(relative: str) -> str:
    """``relative`` safe for a terminal or a log line (SPEC-030 section 4.5).

    ``\\`` becomes ``\\\\``, and each character of the Unicode categories ``Cc``, ``Cf``,
    ``Cs``, ``Zl`` and ``Zp`` becomes ``\\xHH`` (code up to 0xFF), ``\\uHHHH`` (up to 0xFFFF) or
    ``\\UHHHHHHHH``, in lowercase hexadecimal. Every other character, accented letters included,
    is kept. A name with bytes that are not UTF-8 reaches Python with surrogates
    (``surrogateescape``, category ``Cs``) and comes out escaped.
    """
    parts: list[str] = []
    for char in relative:
        if char == "\\":
            parts.append("\\\\")
        elif unicodedata.category(char) in _ESCAPED_CATEGORIES:
            code = ord(char)
            if code <= 0xFF:
                parts.append(f"\\x{code:02x}")
            elif code <= 0xFFFF:
                parts.append(f"\\u{code:04x}")
            else:
                parts.append(f"\\U{code:08x}")
        else:
            parts.append(char)
    return "".join(parts)


@dataclass(frozen=True)
class ImageFinding:
    """An image of ``raw/`` with private data, an EXIF rotation or an ``invalid`` structure."""

    path: Path
    relative: str
    findings: frozenset[str]

    @property
    def line(self) -> str:
        return f"{printable_path(self.relative)}: {', '.join(sorted(self.findings))}"


def is_jpeg_name(name: str) -> bool:
    """``True`` for a name ending with ``.jpg`` or ``.jpeg`` in any case."""
    return name.lower().endswith(JPEG_SUFFIXES)


def is_edge_temporary(name: str) -> bool:
    """``True`` for a temporary file of the edge (``.<name>.<random>.tmp``)."""
    return name.startswith(TEMPORARY_PREFIX) and name.endswith(TEMPORARY_SUFFIX)


def _files(dataset_dir: Path) -> Iterator[tuple[Path, str]]:
    """Regular files under ``raw/``, in path order, except the edge temporaries.

    Symlinks, directories and special files are never followed nor returned.
    """
    raw = dataset_dir / RAW_SUBDIR
    found: list[tuple[str, Path]] = []
    for directory, _, files in os.walk(raw, followlinks=False):
        for name in files:
            if is_edge_temporary(name):
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
    """``jpeg_private_findings`` plus ``orientation``; any ``JpegStructureError`` is ``invalid``."""
    try:
        findings = jpeg.jpeg_private_findings(data)
        if jpeg.has_exif_rotation(data):
            findings |= {FINDING_ORIENTATION}
    except jpeg.JpegStructureError:
        return frozenset({FINDING_INVALID})
    return findings


def _fix(item: ImageFinding, data: bytes, dataset_dir: Path) -> bool:
    """Rewrite ``item`` without its private segments; ``False`` (and an error log) on failure."""
    try:
        clean = jpeg.strip_private_segments(data)
        write_private_file_atomically(
            item.path, lambda handle: handle.write(clean), root=dataset_dir
        )
    except (OSError, jpeg.JpegStructureError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else type(exc).__name__
        logger.error("cannot fix %s: %s", printable_path(item.relative), reason)
        return False
    return True


def scan(dataset_dir: Path, *, fix: bool, out: TextIO) -> int:
    """Check (and, with ``fix``, rewrite) the images of ``dataset_dir``; returns the exit code."""
    checked = 0
    with_findings = 0
    remaining = False
    for path, relative in _files(dataset_dir):
        shown = printable_path(relative)
        if is_jpeg_name(path.name):
            try:
                data = _read(path)
            except OSError as exc:
                logger.error("cannot read %s: %s", shown, exc.strerror or type(exc).__name__)
                out.write(f"{shown}: {UNREADABLE}\n")
                remaining = True
                continue
            findings = _findings(data)
        else:  # not a JPEG: never read (SPEC-030 section 4.4)
            data = b""
            findings = frozenset({FINDING_INVALID})
        checked += 1
        if not findings:
            continue
        with_findings += 1
        item = ImageFinding(path=path, relative=relative, findings=findings)
        out.write(f"{item.line}\n")
        if not fix or findings & UNFIXABLE_FINDINGS:
            remaining = True
            continue
        if _fix(item, data, dataset_dir):
            out.write(f"fixed {shown}\n")
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


def limit_pil_logging() -> None:
    """The ``PIL`` logger at ``INFO`` at least (SPEC-038 section 4.4).

    In ``DEBUG``, ``PIL.TiffImagePlugin`` logs the values of the EXIF tags (``Make``,
    ``Artist``) it reads for the orientation. A level above ``INFO`` is kept. Only the CLIs call
    this, never ``qc_edge.jpeg``, which the collect route also uses.
    """
    pil = logging.getLogger("PIL")
    if pil.getEffectiveLevel() < logging.INFO:
        pil.setLevel(logging.INFO)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; returns the exit code (0, 1 or 2)."""
    _configure_logging()
    limit_pil_logging()
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
