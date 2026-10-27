"""API settings (SPEC-004 section 4.1, SPEC-017 section 4.6).

Read only from the process environment: no ``.env`` file is loaded here. Locally, use
``uv run --env-file .env ...``. Validation errors never show the values that were provided
(``hide_input_in_errors``), only the variable names (R-03).

The alert variables (SPEC-017) are read here without their rules on purpose: an invalid alert
value must never stop the API (section 4.6). ``qc_api.services.alerts.load_alert_config``
applies the rules and names the invalid variables, never their values. Each one accepts its
final type (a strict ``bool`` or ``int``, so ``True`` is never read as ``1``) or the raw ``str``
of the environment.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, PositiveInt, SecretStr, StrictBool, StrictInt
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

    # Telegram alerts (SPEC-017 section 4.6). Raw values; the rules live in
    # qc_api.services.alerts. The token is a SecretStr, so it never shows in a repr.
    ALERTS_ENABLED: StrictBool | str = False
    TELEGRAM_BOT_TOKEN: SecretStr = SecretStr("")
    TELEGRAM_CHAT_ID: str = ""
    ALERTS_LOT_IDLE_MINUTES: StrictInt | str = 10
    ALERTS_LOOKBACK_HOURS: StrictInt | str = 24
    ALERTS_CHECK_INTERVAL_S: StrictInt | str = 60
    ALERTS_MAX_PER_HOUR: StrictInt | str = 10
    ALERTS_INCLUDE_SIMULATED: StrictBool | str = False
