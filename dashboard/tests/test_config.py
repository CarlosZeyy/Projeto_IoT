"""``qc_dashboard.config``: secrets first, then the environment (SPEC-013 section 4.1)."""

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
