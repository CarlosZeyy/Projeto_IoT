"""``python -m qc_edge.requeue --outbox-path <file> [--id <inspection_id> ...] [--yes]`` (SPEC-034).

An item that the cloud refuses (413/422) becomes ``dead`` in the outbox and is never sent again
by the publish loop (SPEC-009). After an update of the API or of the edge that fixes the refusal,
the operator runs this command to see the ``dead`` items and then, with ``--yes``, to put them
back to ``pending``; the publish loop sends them in its next cycle, revalidated by the current
contract, and the idempotency by ``inspection_id`` keeps the cloud free of duplicates (R-05).

* Without ``--yes`` (default) it only reads (the file is opened with ``mode=ro``): one line per
  selected ``dead`` item, ``<inspection_id> <created_at> attempts=<n> <last_error or ->``, then
  ``<k> dead item(s); run again with --yes to requeue``. Exit code 0.
* With ``--yes`` it calls ``SqliteOutbox.requeue_dead`` and prints ``requeued <k> item(s)``.
  Exit code 0, also with ``k = 0``.
* ``--id`` (repeatable) restricts both modes to the given ids; each one must be a UUID.
* ``--outbox-path`` must be an existing regular file with the outbox table; it is never created
  (SQLite URI with ``mode=rw``/``mode=ro``). An unknown argument, an invalid ``--id`` or an
  invalid ``--outbox-path`` exits with 2; only option names are logged, never a value (R-03).
* A SQLite failure while reading or updating (for example the busy timeout of 5 s) exits with 1.

The output never carries the payload (nor ``lot_id``, ``device_id`` or confidences) nor the
``DEVICE_API_KEY``, which this command never reads. ``last_error`` is the refusal summary of
SPEC-009 section 4.2; any control or format character left in it is shown as ``?`` so a stored
text cannot forge an output line. It may run while ``qc-edge`` is up: the file is in WAL mode and
the transaction lasts only for the ``UPDATE``. Nothing here opens a network connection (R-02).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import stat
import sys
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO
from uuid import UUID

from qc_edge.argv import (
    EXIT_USAGE_ERROR,
    ArgumentsError,
    QuietArgumentParser,
    describe_arguments,
    resolve_argv,
)
from qc_edge.outbox import DeadItem, NotAnOutboxError, SqliteOutbox, format_timestamp

logger = logging.getLogger("qc_edge.requeue")

EXIT_OK = 0
EXIT_FAILURE = 1
NO_ERROR = "-"
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def printable_error(error: str | None) -> str:
    """``error`` on one line: control and format characters become ``?``; ``-`` when empty."""
    if not error:
        return NO_ERROR
    return "".join(
        "?" if unicodedata.category(char) in _HIDDEN_CATEGORIES else char for char in error
    )


def item_line(item: DeadItem) -> str:
    """``<inspection_id> <created_at ISO 8601 UTC> attempts=<n> <last_error or ->``."""
    return (
        f"{item.inspection_id} {format_timestamp(item.created_at)} "
        f"attempts={item.attempts} {printable_error(item.last_error)}"
    )


def list_dead(outbox: SqliteOutbox, ids: Sequence[UUID] | None, out: TextIO) -> None:
    """Print the selected ``dead`` items and the summary line; changes nothing."""
    wanted = None if ids is None else set(ids)
    selected = [
        item for item in outbox.dead_items() if wanted is None or item.inspection_id in wanted
    ]
    for item in selected:
        out.write(f"{item_line(item)}\n")
    out.write(f"{len(selected)} dead item(s); run again with --yes to requeue\n")


def _parser() -> QuietArgumentParser:
    parser = QuietArgumentParser(
        prog="python -m qc_edge.requeue",
        description="List the dead items of the outbox and put them back to pending.",
        allow_abbrev=False,
    )
    parser.add_argument("--outbox-path", required=True, type=Path, help="OUTBOX_PATH")
    parser.add_argument(
        "--id",
        dest="ids",
        action="append",
        type=UUID,
        metavar="INSPECTION_ID",
        help="only this dead item (repeatable)",
    )
    parser.add_argument("--yes", action="store_true", help="put the dead items back to pending")
    return parser


def _configure_logging() -> None:
    if not logging.getLogger().handlers and not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except (OSError, ValueError):
        return False


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
    path: Path = args.outbox_path
    if not _is_regular_file(path):
        logger.error("--outbox-path must be an existing regular file")
        return EXIT_USAGE_ERROR
    ids: list[UUID] | None = args.ids
    try:
        outbox = SqliteOutbox.open_existing(path, read_only=not args.yes)
    except (sqlite3.Error, NotAnOutboxError) as exc:
        logger.error("--outbox-path is not an outbox file (%s)", type(exc).__name__)
        return EXIT_USAGE_ERROR
    try:
        if args.yes:
            changed = outbox.requeue_dead(ids)
            sys.stdout.write(f"requeued {changed} item(s)\n")
        else:
            list_dead(outbox, ids, sys.stdout)
    except sqlite3.Error as exc:
        logger.error("outbox access failed (%s)", type(exc).__name__)
        return EXIT_FAILURE
    finally:
        outbox.close()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
