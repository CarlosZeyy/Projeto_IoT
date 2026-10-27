"""Whole pipeline: train -> export -> thresholds -> evaluate (SPEC-012 section 4.8).

Stops at the first failing step with exit code 2. Train and export need the ``train`` extra;
they are imported only when the pipeline runs.

CLI::

    python -m qc_ml.pipeline --config ml/configs/partqc-mnv3-v1.json [--resume] \
        [--latency-machine "Colab CPU"]
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from qc_ml import evaluate, thresholds
from qc_ml.config import load_config
from qc_ml.data import configure_logging
from qc_ml.steps import EXIT_ERROR, EXIT_OK, report_step_error

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qc_ml.pipeline",
        description="Train, export, choose the thresholds (val) and evaluate (test).",
    )
    parser.add_argument("--config", required=True, help="ml/configs/<model_version>.json")
    parser.add_argument("--resume", action="store_true", help="continue training from last.pt")
    parser.add_argument("--latency-machine", default=None, help="where the latency is measured")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; 0 when every step succeeded, 2 at the first failure."""
    configure_logging()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR

    step = "config"
    try:
        config = load_config(args.config)
        step = "train"
        from qc_ml import export, train  # torch: only when the pipeline runs

        result = train.run(config, resume=args.resume)
        step = "export"
        export.run(config, model=result.model, labels=result.labels)
        step = "thresholds"
        thresholds.run(config)
        step = "evaluate"
        evaluate.run(config, latency_machine=args.latency_machine)
    except Exception as exc:  # noqa: BLE001 - every failure is reported and exits with 2
        return report_step_error(step, exc)
    logger.info("pipeline finished: %s", config.model_dir)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
