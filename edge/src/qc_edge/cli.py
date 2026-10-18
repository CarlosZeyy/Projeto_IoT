"""``qc-edge`` command (SPEC-007 section 4.3): starts the gateway on the LAN.

Exit codes: 2 for an invalid configuration (the message names the variable, never its value) or
an unknown command-line argument (SPEC-025 section 4.5: only option names are logged, never a
value); 1 when ``PIL.ImageFile.LOAD_TRUNCATED_IMAGES`` is enabled (SEC-04).

With ``--stub-model`` the gateway answers with ``StubInferencer`` results. Nothing is ever
published to the cloud in that mode (R-06): in this SPEC the sink is ``InMemorySink``, which
sends nothing anywhere.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import TextIO

import uvicorn
from PIL import ImageFile
from pydantic import ValidationError

from qc_edge.app import create_app
from qc_edge.argv import ArgumentsError, QuietArgumentParser, describe_arguments, resolve_argv
from qc_edge.config import EdgeSettings
from qc_edge.inference import Inferencer, StubInferencer
from qc_edge.sink import InMemorySink, InspectionSink

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
EXIT_RUNTIME_ERROR = 1
EXIT_CONFIG_ERROR = 2

logger = logging.getLogger("qc_edge")


class _StderrHandler(logging.StreamHandler):
    """Writes to the *current* ``sys.stderr`` (resolved at each record, not at creation)."""

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self) -> TextIO:  # type: ignore[override]
        return sys.stderr


def configure_logging() -> None:
    """INFO on the ``qc_edge`` logger, written to stderr; idempotent."""
    logger.setLevel(logging.INFO)
    if not any(isinstance(handler, _StderrHandler) for handler in logger.handlers):
        handler = _StderrHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line; any unknown or invalid argument exits with 2.

    Neither the log nor the stderr ever shows a value from the command line (R-03).
    """
    arguments = resolve_argv(argv)
    parser = QuietArgumentParser(
        prog="qc-edge", description="PartQC edge gateway (LAN)", allow_abbrev=False
    )
    parser.add_argument(
        "--stub-model",
        action="store_true",
        help="answer with a fixed stub result (development only; nothing is published)",
    )
    try:
        args, unknown = parser.parse_known_args(arguments)
    except ArgumentsError:
        logger.error("invalid command-line argument(s): %s", describe_arguments(arguments))
        sys.exit(EXIT_CONFIG_ERROR)
    if unknown:
        logger.error("unknown command-line argument(s): %s", describe_arguments(unknown))
        sys.exit(EXIT_CONFIG_ERROR)
    return args


def _config_error_message(exc: ValidationError) -> str:
    """One ``NAME: reason`` per invalid variable, without the values (R-03)."""
    parts = []
    for error in exc.errors(include_input=False, include_url=False):
        name = ".".join(str(part) for part in error.get("loc", ())) or "configuration"
        parts.append(f"{name}: {error.get('msg', 'invalid value')}")
    return "; ".join(parts)


def main(argv: Sequence[str] | None = None) -> None:
    """Load the settings, build the app and run ``uvicorn`` on ``EDGE_HOST:EDGE_PORT``."""
    configure_logging()
    args = _parse_args(argv)
    try:
        settings = EdgeSettings()
    except ValidationError as exc:
        logger.error("invalid configuration: %s", _config_error_message(exc))
        sys.exit(EXIT_CONFIG_ERROR)

    inferencer: Inferencer | None = StubInferencer() if args.stub_model else None
    sink: InspectionSink = InMemorySink()

    # SEC-04: checked after every edge module (and, from SPEC-008, onnxruntime) is imported and
    # before the server starts. No qc_edge module changes the flag.
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        logger.error(
            "PIL.ImageFile.LOAD_TRUNCATED_IMAGES is enabled; refusing to start because "
            "truncated images would be accepted"
        )
        sys.exit(EXIT_RUNTIME_ERROR)

    app = create_app(settings, inferencer, sink)
    if args.stub_model:
        logger.warning("stub model enabled: results are fake and nothing is published")
    elif inferencer is None:
        logger.warning("no model loaded: inspect mode answers 503 'model not loaded'")
    logger.info("operator console: http://127.0.0.1:%d/", settings.EDGE_PORT)
    # proxy_headers=False: X-Forwarded-For from 127.0.0.1 must never change the client address
    # (the console is loopback-only). The access log is off because it would print the query
    # string of /capture, which carries the session token; RequestLogMiddleware logs instead.
    uvicorn.run(
        app,
        host=settings.EDGE_HOST,
        port=settings.EDGE_PORT,
        proxy_headers=False,
        access_log=False,
        log_level="info",
    )
