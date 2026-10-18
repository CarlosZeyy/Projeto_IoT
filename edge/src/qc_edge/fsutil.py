"""Private files and directories of the edge gateway (SPEC-010 section 4.2, SPEC-025 sections 4.4
and 4.10).

Everything ``qc_edge`` creates to hold photos gets an exact mode, whatever the ``umask``: ``0700``
for directories and ``0600`` for files (R-14). The ``umask`` only removes bits, so the mode is set
with an explicit ``chmod``/``fchmod`` after creation. A failure to set it (for example, on a file
system without POSIX permissions) is a ``WARNING``, never an error: the photos never leave this
machine anyway (R-02).

``fsync_dir`` makes a ``rename`` or a new directory entry durable (SEC-10-02); a file system that
cannot ``fsync`` a directory also gets a ``WARNING``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("qc_edge")

DIR_MODE = 0o700
FILE_MODE = 0o600


def set_mode(path: Path, mode: int, fd: int | None = None) -> None:
    """Exact ``mode`` on ``path`` (through ``fd`` when given); a failure is a ``WARNING``."""
    try:
        if fd is None:
            os.chmod(path, mode)
        else:
            os.fchmod(fd, mode)
    except OSError as exc:
        logger.warning("cannot set mode %s on %s: %s", oct(mode), path, exc.strerror or exc)


def fsync_dir(path: Path, *, relative_to: Path | None = None) -> None:
    """``fsync`` of the directory ``path``; an ``OSError`` is a ``WARNING`` (SPEC-025 section 4.10).

    The warning shows ``path`` relative to ``relative_to`` when given.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        _fsync_warning(path, relative_to, exc)
        return
    try:
        os.fsync(fd)
    except OSError as exc:
        _fsync_warning(path, relative_to, exc)
    finally:
        os.close(fd)


def _fsync_warning(path: Path, relative_to: Path | None, exc: OSError) -> None:
    shown = os.path.relpath(path, relative_to) if relative_to is not None else str(path)
    logger.warning("cannot fsync directory %s: %s", shown, exc.strerror or exc)


def make_private_dirs(
    path: Path, *, sync: bool = False, relative_to: Path | None = None
) -> list[Path]:
    """Create ``path`` and its missing parents; only the ones created here get ``0700``.

    A directory created meanwhile by someone else is left as it is. With ``sync``, the parent of
    every directory created here gets ``fsync_dir`` (SPEC-025 section 4.10). Returns the
    directories created, outermost first.
    """
    missing: list[Path] = []
    current = path
    while not os.path.lexists(current):
        missing.append(current)
        current = current.parent
    created: list[Path] = []
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=DIR_MODE)
        except FileExistsError:
            continue
        set_mode(directory, DIR_MODE)
        created.append(directory)
        if sync:
            fsync_dir(directory.parent, relative_to=relative_to)
    return created


def create_private_file(path: Path, flags: int = os.O_WRONLY) -> int:
    """Create ``path`` exclusively (``O_CREAT | O_EXCL``), already with mode ``0600``.

    Never follows a symlink: an existing path, link or not, raises ``FileExistsError``.
    """
    fd = os.open(path, flags | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, FILE_MODE)
    set_mode(path, FILE_MODE, fd)
    return fd
