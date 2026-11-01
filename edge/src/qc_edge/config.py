"""Edge settings (SPEC-007 section 4.1, docs/architecture.md section 6.4).

Read only from the process environment: no ``.env`` file is loaded here. Locally, use
``uv run --env-file .env --package qc-edge qc-edge``. An empty variable counts as unset, so the
blank lines of ``.env.example`` keep their defaults. Validation errors never show the values that
were provided (``hide_input_in_errors``), only the variable names (R-03).

SPEC-009: ``CLOUD_API_URL``, when set, must be ``https://`` (``http://`` only for the hosts
``localhost`` and ``127.0.0.1``), with a host and without user, password, query or fragment
(``check_cloud_api_url``); otherwise the start stops with code 2 naming the variable.
``DEVICE_API_KEY`` is checked by ``qc_edge.publisher.HttpPublisher`` and ``OUTBOX_PATH`` (default
``EDGE_DATA_DIR/outbox.sqlite3``) is opened by ``qc_edge.outbox.SqliteOutbox``.

``MODEL_DIR`` is loaded by ``qc_edge.onnx_inferencer`` (SPEC-008); the three threshold overrides
are checked here (a finite number in ``[0, 1]``, SPEC-008 section 4.2, item 6), so an invalid one
stops the start with code 2 naming the variable. ``DATASET_DIR`` (SPEC-010) is not created here:
the collect mode creates it, with mode ``0700``, on the first capture.

SPEC-018: ``HEARTBEAT_INTERVAL_S`` (default 60) is an integer from 10 to 3600, or ``0`` to turn the
heartbeat off; anything else stops the start with code 2 naming the variable.

SPEC-020: ``EDGE_PUBLISHER`` (``http``, the default, or ``mqtt``; anything else stops the start
with ``EDGE_PUBLISHER must be http or mqtt``), ``MQTT_HOST`` (only ``127.0.0.1``, ``::1`` or
``localhost``: the broker runs on this notebook), ``MQTT_PORT`` (1 to 65535),
``MQTT_RESPONSE_TIMEOUT_S`` (a number from 1 to 60) and ``MQTT_USERNAME``/``MQTT_PASSWORD``
(required with ``EDGE_PUBLISHER=mqtt``, checked by ``missing_mqtt_credentials``). They are
validated with or without ``EDGE_PUBLISHER=mqtt``. ``BridgeSettings`` holds the variables of
``python -m qc_edge.mqtt_bridge``; it creates no directory.

SPEC-025: ``EDGE_HOST`` is an IPv4 literal only (with ``::`` uvicorn listens on IPv6 only, and
neither the console URL nor the QR code would open), and an ``EDGE_DATA_DIR`` created here gets
mode ``0700`` (an existing one is left as it is).

SPEC-019: ``EDGE_TLS_CERT`` and ``EDGE_TLS_KEY`` turn HTTPS on, both or neither. Each file must
open for reading, and the key must have no permission for group or others; the content is never
read here (an invalid PEM makes ``uvicorn`` fail at startup, before serving any route). ``LIVE_*``
are the parameters of the live video mode (section 4.6).
"""

from __future__ import annotations

import ipaddress
import os
import stat
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    Field,
    SecretStr,
    ValidationError,
    ValidationInfo,
    field_validator,
)
from pydantic_core import PydanticCustomError
from pydantic_settings import BaseSettings, SettingsConfigDict

from qc_contracts import DEVICE_ID_PATTERN
from qc_edge.fsutil import make_private_dirs

DEFAULT_EDGE_HOST = "0.0.0.0"
DEFAULT_EDGE_PORT = 8000
DEFAULT_DEVICE_ID = "edge-01"
DEFAULT_EDGE_DATA_DIR = Path("edge/data")
# docs/dataset-protocol.md section 8; ml/data/ is in .gitignore.
DEFAULT_DATASET_DIR = Path("ml/data")
MIN_SESSION_TOKEN_LENGTH = 32
# SPEC-009 section 4.2: plain HTTP only towards these hosts (local tests).
LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1"})

# Heartbeat (SPEC-018 section 4.4): seconds between two heartbeats; 0 turns it off.
DEFAULT_HEARTBEAT_INTERVAL_S = 60
MIN_HEARTBEAT_INTERVAL_S = 10
MAX_HEARTBEAT_INTERVAL_S = 3600

# Threshold override (SPEC-008 section 4.2, item 6): a finite number in [0, 1].
Threshold = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]

# MQTT transport (SPEC-020 section 4.5).
EDGE_PUBLISHERS = ("http", "mqtt")
DEFAULT_EDGE_PUBLISHER = "http"
EDGE_PUBLISHER_ERROR = "EDGE_PUBLISHER must be http or mqtt"
MQTT_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
DEFAULT_MQTT_HOST = "127.0.0.1"
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_RESPONSE_TIMEOUT_S = 15.0

# Live video mode (SPEC-019 section 4.6).
DEFAULT_LIVE_WINDOW = 10
DEFAULT_LIVE_MIN_AGREE = 8
DEFAULT_LIVE_MIN_CONFIDENCE = 0.80
DEFAULT_LIVE_EMPTY_FRAMES = 3
DEFAULT_LIVE_MAX_SESSIONS = 4
DEFAULT_LIVE_FPS = 2
TLS_PAIR_ERROR = "EDGE_TLS_CERT and EDGE_TLS_KEY must be set together"
# A permission for group or others on the private key (SPEC-019 section 4.1).
TLS_KEY_FORBIDDEN_MODE = 0o077


def _check_mqtt_host(value: str) -> str:
    if value not in MQTT_LOOPBACK_HOSTS:
        raise ValueError("must be 127.0.0.1, ::1 or localhost (the broker runs on this notebook)")
    return value


def _stat_readable_file(path: Path) -> os.stat_result:
    """``stat`` of a regular file that opens for reading; its content is never read.

    ``O_NONBLOCK``: opening a FIFO must not hang the startup.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except (OSError, ValueError) as exc:
        reason = getattr(exc, "strerror", None) or "invalid path"
        raise ValueError(f"cannot open the file for reading ({reason})") from None
    try:
        info = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("must be a regular file")
    return info


MqttHost = Annotated[str, AfterValidator(_check_mqtt_host)]
Port = Annotated[int, Field(ge=1, le=65535)]
ResponseTimeout = Annotated[float, Field(ge=1.0, le=60.0, allow_inf_nan=False)]

_SETTINGS_CONFIG = SettingsConfigDict(
    case_sensitive=True,
    extra="ignore",
    env_ignore_empty=True,
    hide_input_in_errors=True,
)


class EdgeSettings(BaseSettings):
    """``qc-edge`` configuration. Field names are the environment variable names."""

    model_config = _SETTINGS_CONFIG

    EDGE_HOST: str = DEFAULT_EDGE_HOST
    EDGE_PORT: Annotated[int, Field(ge=1, le=65535)] = DEFAULT_EDGE_PORT
    EDGE_SESSION_TOKEN: Annotated[SecretStr, Field(min_length=MIN_SESSION_TOKEN_LENGTH)] | None = (
        None
    )
    # The Pydantic ``pattern`` matches the whole string (``$`` never accepts a trailing ``\n``),
    # the same validation the contract applies to ``InspectionCreate.device_id``.
    DEVICE_ID: Annotated[str, Field(pattern=DEVICE_ID_PATTERN)] = DEFAULT_DEVICE_ID
    EDGE_DATA_DIR: Path = DEFAULT_EDGE_DATA_DIR
    # Collect mode (SPEC-010): images and manifest.csv of the dataset; never served (R-02).
    DATASET_DIR: Path = DEFAULT_DATASET_DIR

    # Cloud and outbox (SPEC-009).
    DEVICE_API_KEY: SecretStr | None = None
    CLOUD_API_URL: str | None = None
    OUTBOX_PATH: Path | None = None
    # SPEC-008: model directory (unset or "" = no model; never stripped, so only spaces is an
    # invalid directory, section 4.4) and the overrides of decision.json.
    MODEL_DIR: Path | None = None
    TYPE_THRESHOLD: Threshold | None = None
    UNUSABLE_THRESHOLD: Threshold | None = None
    GRADE_REVIEW_THRESHOLD: Threshold | None = None
    # SPEC-018: heartbeat interval (0 = off).
    HEARTBEAT_INTERVAL_S: int = DEFAULT_HEARTBEAT_INTERVAL_S
    # SPEC-020: publisher of the outbox and the local MQTT broker.
    EDGE_PUBLISHER: str = DEFAULT_EDGE_PUBLISHER
    MQTT_HOST: MqttHost = DEFAULT_MQTT_HOST
    MQTT_PORT: Port = DEFAULT_MQTT_PORT
    MQTT_USERNAME: str | None = None
    MQTT_PASSWORD: SecretStr | None = None
    MQTT_RESPONSE_TIMEOUT_S: ResponseTimeout = DEFAULT_MQTT_RESPONSE_TIMEOUT_S
    # SPEC-019: HTTPS of the gateway and the live video mode. ``EDGE_TLS_KEY`` and
    # ``LIVE_MIN_AGREE`` are validated even when unset, against the field declared before them.
    EDGE_TLS_CERT: Path | None = None
    EDGE_TLS_KEY: Annotated[Path | None, Field(validate_default=True)] = None
    LIVE_WINDOW: Annotated[int, Field(ge=3, le=30)] = DEFAULT_LIVE_WINDOW
    LIVE_MIN_AGREE: Annotated[int, Field(ge=1, validate_default=True)] = DEFAULT_LIVE_MIN_AGREE
    LIVE_MIN_CONFIDENCE: Annotated[float, Field(ge=0.50, le=0.99, allow_inf_nan=False)] = (
        DEFAULT_LIVE_MIN_CONFIDENCE
    )
    LIVE_EMPTY_FRAMES: Annotated[int, Field(ge=1, le=10)] = DEFAULT_LIVE_EMPTY_FRAMES
    LIVE_MAX_SESSIONS: Annotated[int, Field(ge=1, le=8)] = DEFAULT_LIVE_MAX_SESSIONS
    LIVE_FPS: Annotated[int, Field(ge=1, le=5)] = DEFAULT_LIVE_FPS

    @property
    def tls_enabled(self) -> bool:
        """Whether the gateway serves HTTPS (validation guarantees both files or neither)."""
        return self.EDGE_TLS_CERT is not None

    @field_validator("EDGE_TLS_CERT", "EDGE_TLS_KEY", mode="before")
    @classmethod
    def _tls_empty_is_unset(cls, value: Any) -> Any:
        return None if value == "" else value

    @field_validator("EDGE_TLS_CERT")
    @classmethod
    def _tls_cert_file(cls, value: Path | None) -> Path | None:
        if value is not None:
            _stat_readable_file(value)
        return value

    @field_validator("EDGE_TLS_KEY")
    @classmethod
    def _tls_key_file(cls, value: Path | None, info: ValidationInfo) -> Path | None:
        # An invalid certificate is not in ``info.data`` and was already reported.
        if "EDGE_TLS_CERT" in info.data and (info.data["EDGE_TLS_CERT"] is None) != (value is None):
            raise ValueError(TLS_PAIR_ERROR)
        if value is not None and _stat_readable_file(value).st_mode & TLS_KEY_FORBIDDEN_MODE:
            raise ValueError("must not have permissions for group or others (use chmod 600)")
        return value

    @field_validator("LIVE_MIN_AGREE")
    @classmethod
    def _live_min_agree(cls, value: int, info: ValidationInfo) -> int:
        window = info.data.get("LIVE_WINDOW")  # absent when LIVE_WINDOW itself is invalid
        if window is not None and value > window:
            raise ValueError("must not be greater than LIVE_WINDOW")
        return value

    @field_validator("EDGE_PUBLISHER")
    @classmethod
    def _edge_publisher(cls, value: str) -> str:
        if value not in EDGE_PUBLISHERS:
            # A custom error keeps the text as it is (no "Value error, " prefix).
            raise PydanticCustomError("edge_publisher", EDGE_PUBLISHER_ERROR)
        return value

    @field_validator("EDGE_HOST")
    @classmethod
    def _ipv4_literal(cls, value: str) -> str:
        try:
            ipaddress.IPv4Address(value)
        except ValueError:
            raise ValueError("must be an IPv4 address literal (e.g. 0.0.0.0)") from None
        return value

    @field_validator("HEARTBEAT_INTERVAL_S")
    @classmethod
    def _heartbeat_interval(cls, value: int) -> int:
        if value != 0 and not MIN_HEARTBEAT_INTERVAL_S <= value <= MAX_HEARTBEAT_INTERVAL_S:
            raise ValueError(
                f"must be 0 (off) or an integer from {MIN_HEARTBEAT_INTERVAL_S} to "
                f"{MAX_HEARTBEAT_INTERVAL_S}"
            )
        return value

    @field_validator("CLOUD_API_URL")
    @classmethod
    def _cloud_api_url(cls, value: str | None) -> str | None:
        return None if value is None else check_cloud_api_url(value)

    @field_validator("EDGE_DATA_DIR")
    @classmethod
    def _create_data_dir(cls, value: Path) -> Path:
        # Only the directories created here get 0700 (SPEC-025 section 4.4), whatever the umask.
        try:
            make_private_dirs(value)
        except OSError as exc:
            raise ValueError(f"cannot create the directory ({exc.strerror})") from None
        if not value.is_dir():
            raise ValueError("must be a directory")
        return value

    @field_validator("DATASET_DIR")
    @classmethod
    def _dataset_dir_is_not_a_file(cls, value: Path) -> Path:
        # Not created here (section 4.2, item 5): only an existing non-directory is refused.
        if value.exists() and not value.is_dir():
            raise ValueError("must be a directory")
        return value


class BridgeSettings(BaseSettings):
    """``python -m qc_edge.mqtt_bridge`` configuration (SPEC-020 section 4.4).

    ``DEVICE_API_KEY``, ``CLOUD_API_URL``, ``MQTT_USERNAME`` and ``MQTT_PASSWORD`` are required
    (``missing_bridge_settings``); the URL follows ``check_cloud_api_url`` (SPEC-009).
    """

    model_config = _SETTINGS_CONFIG

    DEVICE_ID: Annotated[str, Field(pattern=DEVICE_ID_PATTERN)] = DEFAULT_DEVICE_ID
    DEVICE_API_KEY: SecretStr | None = None
    CLOUD_API_URL: str | None = None
    MQTT_HOST: MqttHost = DEFAULT_MQTT_HOST
    MQTT_PORT: Port = DEFAULT_MQTT_PORT
    MQTT_USERNAME: str | None = None
    MQTT_PASSWORD: SecretStr | None = None

    @field_validator("CLOUD_API_URL")
    @classmethod
    def _cloud_api_url(cls, value: str | None) -> str | None:
        return None if value is None else check_cloud_api_url(value)


def missing_mqtt_credentials(settings: EdgeSettings | BridgeSettings) -> list[str]:
    """Names of ``MQTT_USERNAME`` and ``MQTT_PASSWORD`` that are not set (empty = not set)."""
    return [
        name
        for name, value in (
            ("MQTT_USERNAME", settings.MQTT_USERNAME),
            ("MQTT_PASSWORD", settings.MQTT_PASSWORD),
        )
        if not value
    ]


def missing_bridge_settings(settings: BridgeSettings) -> list[str]:
    """Names of the required variables of the bridge that are not set."""
    missing = [
        name
        for name, value in (
            ("DEVICE_API_KEY", settings.DEVICE_API_KEY),
            ("CLOUD_API_URL", settings.CLOUD_API_URL),
        )
        if not value
    ]
    return missing + missing_mqtt_credentials(settings)


def config_error_message(exc: ValidationError) -> str:
    """One ``NAME: reason`` per invalid variable, without the values (R-03).

    A reason that already starts with the variable name (``EDGE_PUBLISHER must be http or
    mqtt``) is shown as it is.
    """
    parts = []
    for error in exc.errors(include_input=False, include_url=False):
        name = ".".join(str(part) for part in error.get("loc", ())) or "configuration"
        message = error.get("msg", "invalid value")
        parts.append(message if message.startswith(name) else f"{name}: {message}")
    return "; ".join(parts)


def check_cloud_api_url(url: str) -> str:
    """``url`` without the trailing ``/``, if it is acceptable as ``CLOUD_API_URL`` (SPEC-009).

    ``https://`` with a host; ``http://`` only for ``localhost`` and ``127.0.0.1``. No user or
    password (a secret in a variable that is not one), no query and no fragment. The error
    messages never repeat the value.

    Raises:
        ValueError: any other URL.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError:
        raise ValueError("must be a valid URL") from None
    scheme = parts.scheme.lower()
    if scheme not in ("https", "http") or not host:
        raise ValueError("must be an https:// URL with a host")
    if scheme == "http" and host not in LOCAL_HTTP_HOSTS:
        raise ValueError("must use https:// (http:// only for localhost or 127.0.0.1)")
    if parts.username is not None or parts.password is not None:
        raise ValueError("must not contain a user or password")
    if parts.query or parts.fragment or "?" in url or "#" in url:
        raise ValueError("must not contain a query or fragment")
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        raise ValueError("must not contain spaces or control characters")
    return url.rstrip("/")
