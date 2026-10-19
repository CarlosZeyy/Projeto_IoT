"""Exit codes and error reporting shared by the CLIs of SPEC-012 (no torch)."""

from __future__ import annotations

import logging
import sys

from qc_ml.data import print_problems
from qc_ml.errors import (
    ConfigError,
    EvaluationError,
    ExportError,
    ManifestError,
    ModelArtifactError,
    SplitError,
    TrainError,
)

EXIT_OK = 0
EXIT_ERROR = 2

logger = logging.getLogger("qc_ml")

EXPECTED_ERRORS: tuple[type[BaseException], ...] = (
    ConfigError,
    EvaluationError,
    ExportError,
    ModelArtifactError,
    SplitError,
    TrainError,
    OSError,
)


def report_step_error(step: str, exc: BaseException) -> int:
    """Print why ``step`` failed to stderr and return ``EXIT_ERROR``.

    An expected error (invalid configuration, dataset, split or model files) prints only its
    message; anything else is a bug and is logged with the traceback.
    """
    if isinstance(exc, ManifestError):
        print(f"{step} failed: the dataset has problems", file=sys.stderr)
        print_problems(exc.problems, sys.stderr)
    elif isinstance(exc, EXPECTED_ERRORS):
        print(f"{step} failed: {exc}", file=sys.stderr)
    else:
        logger.error("%s failed with an unexpected error", step, exc_info=exc)
        print(f"{step} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return EXIT_ERROR
