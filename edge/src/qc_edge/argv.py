"""Command-line parsing that never echoes a value (SPEC-025 sections 4.5 and 4.9).

A secret typed by mistake (``--token=<secret>``, or passed as a loose argument) must not reach
the log nor the stderr (R-03). ``argparse`` would print it in its own error messages
(``unrecognized arguments: ...``, ``ignored explicit argument '...'``), so the parser here never
prints an error: it raises ``ArgumentsError``, and the caller logs only ``describe_arguments``.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from typing import NoReturn

EXIT_USAGE_ERROR = 2
# Option names shown in an error; anything else only counts.
_OPTION_NAME = re.compile(r"--?[a-z][a-z0-9-]{0,30}")


class ArgumentsError(Exception):
    """The command line is invalid. Carries no text from the command line."""


class QuietArgumentParser(argparse.ArgumentParser):
    """``ArgumentParser`` whose errors raise ``ArgumentsError`` instead of printing them.

    ``-h``/``--help`` still prints the help and exits with 0.
    """

    def error(self, message: str) -> NoReturn:
        raise ArgumentsError()


def describe_arguments(arguments: Sequence[str]) -> str:
    """Option names of ``arguments`` and how many other items there are, never a value.

    For each item that starts with ``-``, the text before the first ``=`` is shown when it fully
    matches ``--?[a-z][a-z0-9-]{0,30}``; every other item only counts (``N other``).
    """
    names: list[str] = []
    others = 0
    for argument in arguments:
        name = argument.split("=", 1)[0] if argument.startswith("-") else ""
        if name and _OPTION_NAME.fullmatch(name):
            names.append(name)
        else:
            others += 1
    if others:
        names.append(f"{others} other")
    return ", ".join(names) if names else "none"


def resolve_argv(argv: Sequence[str] | None) -> list[str]:
    """``argv`` as a list; ``None`` means ``sys.argv[1:]`` (the ``argparse`` default)."""
    return list(sys.argv[1:] if argv is None else argv)
