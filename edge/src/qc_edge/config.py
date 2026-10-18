"""Edge settings (SPEC-007 section 4.1, docs/architecture.md section 6.4).

Read only from the process environment: no ``.env`` file is loaded here. Locally, use
``uv run --env-file .env --package qc-edge qc-edge``. An empty variable counts as unset, so the
blank lines of ``.env.example`` keep their defaults. Validation errors never show the values that
were provided (``hide_input_in_errors``), only the variable names (R-03).

``DEVICE_API_KEY``, ``CLOUD_API_URL`` and ``OUTBOX_PATH`` are only read here; SPEC-009
validates them. ``MODEL_DIR`` is loaded by ``qc_edge.onnx_inferencer`` (SPEC-008); the three
threshold overrides are checked here (a finite number in ``[0, 1]``, SPEC-008 section 4.2, item 6),
so an invalid one stops the start with code 2 naming the variable. ``DATASET_DIR`` (SPEC-010) is not
created here: the collect mode creates it, with mode ``0700``, on the first capture.

SPEC-025: ``EDGE_HOST`` is an IPv4 literal only (with ``::`` uvicorn listens on IPv6 only, and
neither the console URL nor the QR code would open), and an ``EDGE_DATA_DIR`` created here gets
mode ``0700`` (an existing one is left as it is).
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
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

# Threshold override (SPEC-008 section 4.2, item 6): a finite number in [0, 1].
Threshold = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class EdgeSettings(BaseSettings):
    """``qc-edge`` configuration. Field names are the environment variable names."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
        hide_input_in_errors=True,
    )

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

    # Read here, validated by SPEC-009 (cloud and outbox).
    DEVICE_API_KEY: SecretStr | None = None
    CLOUD_API_URL: str | None = None
    OUTBOX_PATH: Path | None = None
    # SPEC-008: model directory (unset or "" = no model; never stripped, so only spaces is an
    # invalid directory, section 4.4) and the overrides of decision.json.
    MODEL_DIR: Path | None = None
    TYPE_THRESHOLD: Threshold | None = None
    UNUSABLE_THRESHOLD: Threshold | None = None
    GRADE_REVIEW_THRESHOLD: Threshold | None = None

    @field_validator("EDGE_HOST")
    @classmethod
    def _ipv4_literal(cls, value: str) -> str:
        try:
            ipaddress.IPv4Address(value)
        except ValueError:
            raise ValueError("must be an IPv4 address literal (e.g. 0.0.0.0)") from None
        return value

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
