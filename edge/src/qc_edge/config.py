"""Edge settings (SPEC-007 section 4.1, docs/architecture.md section 6.4).

Read only from the process environment: no ``.env`` file is loaded here. Locally, use
``uv run --env-file .env --package qc-edge qc-edge``. An empty variable counts as unset, so the
blank lines of ``.env.example`` keep their defaults. Validation errors never show the values that
were provided (``hide_input_in_errors``), only the variable names (R-03).

``DEVICE_API_KEY``, ``CLOUD_API_URL``, ``MODEL_DIR``, ``OUTBOX_PATH`` and the three thresholds
are only read here; SPEC-008 and SPEC-009 validate them. ``DATASET_DIR`` (SPEC-010) is not
created here: the collect mode creates it, with mode ``0700``, on the first capture.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from qc_contracts import DEVICE_ID_PATTERN

DEFAULT_EDGE_HOST = "0.0.0.0"
DEFAULT_EDGE_PORT = 8000
DEFAULT_DEVICE_ID = "edge-01"
DEFAULT_EDGE_DATA_DIR = Path("edge/data")
# docs/dataset-protocol.md section 8; ml/data/ is in .gitignore.
DEFAULT_DATASET_DIR = Path("ml/data")
MIN_SESSION_TOKEN_LENGTH = 32


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

    # Read here, validated by later SPECs (008: model and thresholds; 009: cloud and outbox).
    DEVICE_API_KEY: SecretStr | None = None
    CLOUD_API_URL: str | None = None
    MODEL_DIR: Path | None = None
    OUTBOX_PATH: Path | None = None
    TYPE_THRESHOLD: float | None = None
    UNUSABLE_THRESHOLD: float | None = None
    GRADE_REVIEW_THRESHOLD: float | None = None

    @field_validator("EDGE_HOST")
    @classmethod
    def _ip_literal(cls, value: str) -> str:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            raise ValueError("must be an IP address literal (e.g. 0.0.0.0)") from None
        return value

    @field_validator("EDGE_DATA_DIR")
    @classmethod
    def _create_data_dir(cls, value: Path) -> Path:
        try:
            value.mkdir(parents=True, exist_ok=True)
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
