"""Dashboard settings (SPEC-013 section 4.1, SPEC-028 section 4.1).

Each value is read from ``st.secrets`` first and, when the key is absent or there is no secrets
file, from the environment variable of the same name. Empty values count as absent. The read
key is never logged nor shown (R-03), and ``API_BASE_URL`` must use ``https://`` (``http://``
only for ``localhost`` or ``127.0.0.1``), so the key never travels in clear text.
"""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st

API_BASE_URL = "API_BASE_URL"
READ_API_KEY = "READ_API_KEY"
MODEL_METRICS_PATH = "MODEL_METRICS_PATH"

DEFAULT_MODEL_METRICS_PATH = "ml/models/partqc-mnv3-v1/metrics.json"

# dashboard/src/qc_dashboard/config.py -> parents[3] is the repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]

CONFIG_MISSING_MESSAGE = "Configuração ausente: defina API_BASE_URL e READ_API_KEY."
INSECURE_API_URL_MESSAGE = (
    "Configuração inválida: API_BASE_URL precisa usar https:// "
    "(http:// só em localhost ou 127.0.0.1)."
)

# Hosts where ``http://`` is accepted: the same rule as scripts/simulate.py (SPEC-015 §4.5).
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


class ConfigError(Exception):
    """``API_BASE_URL`` or ``READ_API_KEY`` is missing. The message names variables only."""


class InsecureApiUrlError(ConfigError):
    """``API_BASE_URL`` would send the read key in clear text, or has no host.

    The message names the variable only, never its value.
    """


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


def is_secure_api_url(url: str) -> bool:
    """``https://`` with a host, or ``http://`` with the host ``localhost`` or ``127.0.0.1``.

    ``urlsplit`` returns the scheme and ``hostname`` in lower case. Anything else (another
    ``http://`` host, ``[::1]`` included; another scheme; no scheme; no host) is refused, and
    so is a URL with a control character (category ``Cc``: C0, DEL and C1) or an invalid port
    (not a number, or outside 0-65535), which would otherwise only fail in ``httpx.Client``
    (SPEC-029 §4.3).
    """
    # Before urlsplit, which silently drops "\t", "\n" and "\r" (bpo-43882).
    if any(unicodedata.category(ch) == "Cc" for ch in url):
        return False
    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port  # raises ValueError for a port that is not a number or out of range
    except ValueError:
        return False
    if parts.scheme == "https":
        return bool(host)
    return parts.scheme == "http" and host in LOCAL_HOSTS


def get_settings() -> Settings:
    """All settings.

    Raises ``ConfigError`` when ``API_BASE_URL`` or ``READ_API_KEY`` is missing, and
    ``InsecureApiUrlError`` (a ``ConfigError``) when ``API_BASE_URL`` fails
    ``is_secure_api_url``.
    """
    base_url = _read(API_BASE_URL)
    read_api_key = _read(READ_API_KEY)
    if base_url is None or read_api_key is None:
        raise ConfigError("API_BASE_URL and READ_API_KEY must be set")
    if not is_secure_api_url(base_url):
        raise InsecureApiUrlError(
            "API_BASE_URL must use https:// (http:// only for localhost or 127.0.0.1)"
        )
    return Settings(
        api_base_url=base_url.rstrip("/"),
        read_api_key=read_api_key,
        model_metrics_path=get_model_metrics_path(),
    )
