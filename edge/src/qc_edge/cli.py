"""``qc-edge`` command (SPEC-007 section 4.3): starts the gateway on the LAN.

Exit codes: 2 for an invalid configuration (the message names the variable, never its value), an
unknown command-line argument (SPEC-025 section 4.5: only option names are logged, never a
value) or a ``MODEL_DIR`` that cannot be loaded (SPEC-008 section 4.2: the message names the
file); 1 when ``PIL.ImageFile.LOAD_TRUNCATED_IMAGES`` is enabled (SEC-04).

Model (SPEC-008 section 4.4): ``MODEL_DIR`` set -> ``OnnxInferencer``, with the threshold
overrides of the environment; unset or empty (``""``) -> no model (inspect mode answers 503).
The value is not stripped: ``MODEL_DIR`` with only spaces is set, is not a directory and exits
with code 2 (a typo in ``.env`` must not start the gateway without a model).
``--stub-model`` takes precedence over ``MODEL_DIR`` (a warning is logged and the directory is not
loaded): the gateway answers with ``StubInferencer`` results. Nothing is ever published to the
cloud in that mode (R-06).

Outbox and cloud (SPEC-009): the sink is always ``SqliteOutbox(OUTBOX_PATH)`` (default
``EDGE_DATA_DIR/outbox.sqlite3``); an outbox that cannot be opened exits with code 2 naming
``OUTBOX_PATH``. A ``PublishLoop`` with ``HttpPublisher`` is registered as a background service
only when ``DEVICE_API_KEY`` and ``CLOUD_API_URL`` are both set and ``--stub-model`` is not used;
otherwise ``connectivity`` is ``disabled`` and nothing leaves the notebook. An invalid
``CLOUD_API_URL`` (``EdgeSettings``) or ``DEVICE_API_KEY`` (not visible ASCII) exits with code 2
naming the variable, never its value. The loop stops with the app (lifespan); the outbox stays
open until the process ends (every ``put`` is already committed, so nothing is lost).
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from collections.abc import Sequence
from typing import TextIO

import uvicorn
from PIL import ImageFile
from pydantic import ValidationError

from qc_edge.app import create_app
from qc_edge.argv import ArgumentsError, QuietArgumentParser, describe_arguments, resolve_argv
from qc_edge.config import EdgeSettings
from qc_edge.inference import Inferencer, StubInferencer, short_sha
from qc_edge.onnx_inferencer import THRESHOLD_ENV_VARS, ModelLoadError, OnnxInferencer
from qc_edge.outbox import OUTBOX_FILE_NAME, SqliteOutbox
from qc_edge.publish_loop import ConnectivityState, PublishLoop
from qc_edge.publisher import HttpPublisher, check_api_key
from qc_edge.sink import BackgroundService

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


def _open_outbox(settings: EdgeSettings, connectivity: ConnectivityState | None) -> SqliteOutbox:
    """``SqliteOutbox`` at ``OUTBOX_PATH``; exits with code 2 when it cannot be opened."""
    path = settings.OUTBOX_PATH or settings.EDGE_DATA_DIR / OUTBOX_FILE_NAME
    try:
        return SqliteOutbox(path, connectivity=connectivity)
    except (OSError, sqlite3.Error) as exc:
        logger.error("invalid configuration: OUTBOX_PATH: cannot open the outbox (%s)", exc)
        sys.exit(EXIT_CONFIG_ERROR)


def _build_sink(
    settings: EdgeSettings, stub_model: bool
) -> tuple[SqliteOutbox, list[BackgroundService]]:
    """Outbox and background services (SPEC-009 section 3.1)."""
    api_key = settings.DEVICE_API_KEY.get_secret_value() if settings.DEVICE_API_KEY else None
    url = settings.CLOUD_API_URL
    if stub_model or not api_key or not url:
        outbox = _open_outbox(settings, None)
        if stub_model:
            reason = "--stub-model"
        else:
            missing = [
                name
                for name, value in (("DEVICE_API_KEY", api_key), ("CLOUD_API_URL", url))
                if not value
            ]
            reason = " and ".join(missing) + " not set"
        logger.warning("cloud publishing disabled (%s): inspections stay in the outbox", reason)
        return outbox, []

    try:
        check_api_key(api_key)
    except ValueError as exc:
        logger.error("invalid configuration: DEVICE_API_KEY: %s", exc)
        sys.exit(EXIT_CONFIG_ERROR)
    connectivity = ConnectivityState()
    outbox = _open_outbox(settings, connectivity)
    publisher = HttpPublisher(url, api_key)  # CLOUD_API_URL already checked by EdgeSettings
    loop = PublishLoop(outbox, publisher, connectivity)
    logger.info("cloud publishing enabled (outbox: %s)", outbox.path)
    return outbox, [loop]


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


def _threshold_overrides(settings: EdgeSettings) -> dict[str, float]:
    """``{variable: value}`` of the threshold variables that are set (already in ``[0, 1]``)."""
    overrides: dict[str, float] = {}
    for variable in THRESHOLD_ENV_VARS.values():
        value = getattr(settings, variable)
        if value is not None:
            overrides[variable] = value
    return overrides


def _load_inferencer(settings: EdgeSettings, stub_model: bool) -> Inferencer | None:
    """SPEC-008 section 4.4. Exits with code 2 when ``MODEL_DIR`` cannot be loaded."""
    overrides = _threshold_overrides(settings)
    if stub_model:
        if settings.MODEL_DIR is not None:
            logger.warning("--stub-model takes precedence: MODEL_DIR is not loaded")
        return StubInferencer()
    if settings.MODEL_DIR is None:
        if overrides:
            logger.warning(
                "no MODEL_DIR: threshold overrides ignored (%s)", ", ".join(sorted(overrides))
            )
        return None
    try:
        inferencer = OnnxInferencer(settings.MODEL_DIR, overrides=overrides)
    except ModelLoadError as exc:
        logger.error("cannot load the model: %s", exc)
        sys.exit(EXIT_CONFIG_ERROR)
    info = inferencer.model_info
    logger.info(
        "model loaded: model_version=%s sha256=%s",
        info.model_version,
        short_sha(info.model_sha256),
    )
    for name, source in inferencer.threshold_sources.items():
        logger.info(
            "threshold %s=%r (source: %s)", name, getattr(inferencer.thresholds, name), source
        )
    return inferencer


def main(argv: Sequence[str] | None = None) -> None:
    """Load the settings, build the app and run ``uvicorn`` on ``EDGE_HOST:EDGE_PORT``."""
    configure_logging()
    args = _parse_args(argv)
    try:
        settings = EdgeSettings()
    except ValidationError as exc:
        logger.error("invalid configuration: %s", _config_error_message(exc))
        sys.exit(EXIT_CONFIG_ERROR)

    inferencer = _load_inferencer(settings, args.stub_model)
    sink, background = _build_sink(settings, args.stub_model)

    # SEC-04: checked after every edge module and onnxruntime are imported (and the model is
    # loaded) and before the server starts. No qc_edge module changes the flag.
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        logger.error(
            "PIL.ImageFile.LOAD_TRUNCATED_IMAGES is enabled; refusing to start because "
            "truncated images would be accepted"
        )
        sys.exit(EXIT_RUNTIME_ERROR)

    app = create_app(settings, inferencer, sink, background=background)
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
