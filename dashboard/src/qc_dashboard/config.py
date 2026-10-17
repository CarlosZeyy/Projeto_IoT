"""Dashboard settings (SPEC-013 section 4.1).

Each value is read from ``st.secrets`` first and, when the key is absent or there is no secrets
file, from the environment variable of the same name. Empty values count as absent. The read
key is never logged nor shown (R-03).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import streamlit as st

API_BASE_URL = "API_BASE_URL"
READ_API_KEY = "READ_API_KEY"
MODEL_METRICS_PATH = "MODEL_METRICS_PATH"

DEFAULT_MODEL_METRICS_PATH = "ml/models/partqc-mnv3-v1/metrics.json"

# dashboard/src/qc_dashboard/config.py -> parents[3] is the repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]

CONFIG_MISSING_MESSAGE = "Configuração ausente: defina API_BASE_URL e READ_API_KEY."


class ConfigError(Exception):
    """``API_BASE_URL`` or ``READ_API_KEY`` is missing. The message names variables only."""


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    read_api_key: str = field(repr=False)
    model_metrics_path: Path


def _read(name: str) -> str | None:
    """Value of ``name`` from ``st.secrets`` or, failing that, from the environment."""
    value: object = None
    try:
        if name in st.secrets:
            value = st.secrets[name]
    except FileNotFoundError:
        # No secrets file (StreamlitSecretNotFoundError is a FileNotFoundError).
        value = None
    if value is None:
        value = os.environ.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolve_repo_path(path: str | Path) -> Path:
    """``path`` itself when absolute; otherwise relative to the repository root."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def get_model_metrics_path() -> Path:
    """``MODEL_METRICS_PATH`` (default ``ml/models/partqc-mnv3-v1/metrics.json``), resolved.

    Does not need the API settings: the "Sobre o modelo" page works without them.
    """
    return resolve_repo_path(_read(MODEL_METRICS_PATH) or DEFAULT_MODEL_METRICS_PATH)


def get_settings() -> Settings:
    """All settings; ``ConfigError`` when ``API_BASE_URL`` or ``READ_API_KEY`` is missing."""
    base_url = _read(API_BASE_URL)
    read_api_key = _read(READ_API_KEY)
    if base_url is None or read_api_key is None:
        raise ConfigError("API_BASE_URL and READ_API_KEY must be set")
    return Settings(
        api_base_url=base_url.rstrip("/"),
        read_api_key=read_api_key,
        model_metrics_path=get_model_metrics_path(),
    )
