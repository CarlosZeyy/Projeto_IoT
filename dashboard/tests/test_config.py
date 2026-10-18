"""``qc_dashboard.config``: secrets first, then the environment (SPEC-013 §4.1, SPEC-028 §4.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from qc_dashboard import config


class FakeSecrets(dict):
    pass


class MissingSecrets:
    """Behaves like ``st.secrets`` without a secrets file."""

    def __contains__(self, key: object) -> bool:
        raise FileNotFoundError("No secrets found")

    def __getitem__(self, key: str) -> object:
        raise FileNotFoundError("No secrets found")


@pytest.fixture
def secrets(monkeypatch: pytest.MonkeyPatch, no_config_env: None):
    def install(value: object) -> None:
        monkeypatch.setattr(config.st, "secrets", value)

    install(MissingSecrets())
    return install


def test_environment_is_used_without_secrets_file(monkeypatch, secrets, factory) -> None:
    key = factory.new_key()
    monkeypatch.setenv("API_BASE_URL", "http://localhost:8001/")
    monkeypatch.setenv("READ_API_KEY", key)
    settings = config.get_settings()
    assert settings.api_base_url == "http://localhost:8001"
    assert settings.read_api_key == key
    assert key not in repr(settings)


def test_secrets_win_over_environment(monkeypatch, secrets, factory) -> None:
    secret_key, env_key = factory.new_key(), factory.new_key()
    secrets(FakeSecrets(API_BASE_URL="https://api.secret", READ_API_KEY=secret_key))
    monkeypatch.setenv("API_BASE_URL", "https://api.env")
    monkeypatch.setenv("READ_API_KEY", env_key)
    settings = config.get_settings()
    assert settings.api_base_url == "https://api.secret"
    assert settings.read_api_key == secret_key


def test_key_missing_in_secrets_falls_back_to_environment(monkeypatch, secrets, factory) -> None:
    key = factory.new_key()
    secrets(FakeSecrets(API_BASE_URL="https://api.secret"))
    monkeypatch.setenv("READ_API_KEY", key)
    assert config.get_settings().read_api_key == key


@pytest.mark.parametrize(
    "env",
    [{}, {"API_BASE_URL": "https://api.test"}, {"READ_API_KEY": "x"}, {"API_BASE_URL": " "}],
)
def test_missing_settings_raise_config_error(monkeypatch, secrets, env) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(config.ConfigError):
        config.get_settings()


def test_model_metrics_path_default_is_under_repo_root(secrets) -> None:
    path = config.get_model_metrics_path()
    assert path == config.REPO_ROOT / "ml/models/partqc-mnv3-v1/metrics.json"
    assert (config.REPO_ROOT / "dashboard" / "app.py").is_file()


def test_model_metrics_path_relative_and_absolute(monkeypatch, secrets, tmp_path: Path) -> None:
    monkeypatch.setenv("MODEL_METRICS_PATH", "ml/models/x/metrics.json")
    assert config.get_model_metrics_path() == config.REPO_ROOT / "ml/models/x/metrics.json"
    absolute = tmp_path / "metrics.json"
    monkeypatch.setenv("MODEL_METRICS_PATH", str(absolute))
    assert config.get_model_metrics_path() == absolute


def test_model_metrics_path_does_not_need_api_settings(monkeypatch, secrets) -> None:
    monkeypatch.setenv("MODEL_METRICS_PATH", "/tmp/m.json")
    assert config.get_model_metrics_path() == Path("/tmp/m.json")


# ---------- SPEC-028 §4.1: https:// only (SEC-13-01) ----------


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.org",
        "http://[::1]:8001",
        "ftp://api.example.org",
        "api.example.org",
        "https://",
        "https:///x",
        "http://localhost.example.org",
        "http://127.0.0.2:8001",
        "http://0.0.0.0:8001",
        "ws://localhost:8001",
        "//api.example.org",
        "http://[::1",
    ],
)
def test_insecure_api_url_is_refused(monkeypatch, secrets, factory, url: str) -> None:
    monkeypatch.setenv("API_BASE_URL", url)
    monkeypatch.setenv("READ_API_KEY", factory.new_key())
    with pytest.raises(config.InsecureApiUrlError) as info:
        config.get_settings()
    assert isinstance(info.value, config.ConfigError)
    message = str(info.value)
    assert "API_BASE_URL" in message
    assert "example.org" not in message
    # A fixed text: the value never appears (R-03).
    assert message == "API_BASE_URL must use https:// (http:// only for localhost or 127.0.0.1)"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.example.org", "https://api.example.org"),
        ("HTTPS://api.example.org/", "HTTPS://api.example.org"),
        ("https://api.example.org:8443/base/", "https://api.example.org:8443/base"),
        ("http://localhost:8001", "http://localhost:8001"),
        ("http://127.0.0.1:8001", "http://127.0.0.1:8001"),
        ("http://LOCALHOST:8001/", "http://LOCALHOST:8001"),
        ("http://localhost", "http://localhost"),
    ],
)
def test_secure_api_url_is_accepted(monkeypatch, secrets, factory, url: str, expected) -> None:
    monkeypatch.setenv("API_BASE_URL", url)
    monkeypatch.setenv("READ_API_KEY", factory.new_key())
    assert config.get_settings().api_base_url == expected


def test_insecure_url_from_secrets_is_refused(secrets, factory) -> None:
    secrets(FakeSecrets(API_BASE_URL="http://api.example.org", READ_API_KEY=factory.new_key()))
    with pytest.raises(config.InsecureApiUrlError):
        config.get_settings()


def test_missing_key_wins_over_insecure_url(monkeypatch, secrets) -> None:
    """Without ``READ_API_KEY`` the message stays ``Configuração ausente`` (SPEC-013)."""
    monkeypatch.setenv("API_BASE_URL", "http://api.example.org")
    with pytest.raises(config.ConfigError) as info:
        config.get_settings()
    assert not isinstance(info.value, config.InsecureApiUrlError)


def test_insecure_message_text() -> None:
    assert config.INSECURE_API_URL_MESSAGE == (
        "Configuração inválida: API_BASE_URL precisa usar https:// "
        "(http:// só em localhost ou 127.0.0.1)."
    )
