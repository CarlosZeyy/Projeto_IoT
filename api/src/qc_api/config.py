"""API settings (SPEC-004 section 4.1).

Read only from the process environment: no ``.env`` file is loaded here. Locally, use
``uv run --env-file .env ...``. Validation errors never show the values that were provided
(``hide_input_in_errors``), only the variable names (R-03).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MAX_BODY_BYTES = 262_144
MIN_READ_API_KEY_LENGTH = 32

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    """``qc-api`` configuration. Field names are the environment variable names."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    DATABASE_URL: Annotated[SecretStr, Field(min_length=1)]
    READ_API_KEY: Annotated[SecretStr, Field(min_length=MIN_READ_API_KEY_LENGTH)]
    MAX_BODY_BYTES: PositiveInt = DEFAULT_MAX_BODY_BYTES
    LOG_LEVEL: LogLevel = "INFO"
