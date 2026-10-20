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


# ---------- SPEC-029 §4.3: control characters and invalid port (SEC-28-02) ----------

# Every character of category Cc: C0 (U+0000-U+001F), DEL (U+007F) and C1 (U+0080-U+009F).
CONTROL_CHARS = [chr(code) for code in (*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0))]

REFUSED_029 = [
    "https://api.example.org:abc",
    "https://api.example.org:99999",
    "https://api.example.org:65536",
    "https://api.example.org:-1",
    "http://localhost:abc",
    "http://localhost:99999",
    "http://local\thost:8001",
    "https://api.exa\nmple.org",
    "https://api.exa\rmple.org",
    "https://api.example.org\x7f",
    "https://api.exa\x85mple.org",
    "https://api.example.org/pa\x00th",
]


def test_control_characters_are_exactly_category_cc() -> None:
    import unicodedata

    assert len(CONTROL_CHARS) == 65
    assert all(unicodedata.category(ch) == "Cc" for ch in CONTROL_CHARS)


@pytest.mark.parametrize("char", CONTROL_CHARS, ids=lambda ch: f"U+{ord(ch):04X}")
@pytest.mark.parametrize("position", ["scheme", "host", "port", "path", "end"])
def test_any_control_character_is_refused(char: str, position: str) -> None:
    url = {
        "scheme": f"htt{char}ps://api.example.org",
        "host": f"https://api.exa{char}mple.org",
        "port": f"https://api.example.org:84{char}43",
        "path": f"https://api.example.org/a{char}b",
        "end": f"https://api.example.org{char}",
    }[position]
    assert config.is_secure_api_url(url) is False


@pytest.mark.parametrize("url", [*REFUSED_029, "https://api.example.org/\x85"])
def test_invalid_port_or_control_character_is_refused(url: str) -> None:
    assert config.is_secure_api_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.org:8443",
        "https://api.example.org",
        "http://localhost:8001",
        "http://127.0.0.1",
        "https://api.example.org:0",
        "https://api.example.org:65535",
        "https://api.exa mple.org".replace(" ", ""),  # NBSP is Zs, not Cc
    ],
)
def test_valid_port_is_still_accepted(url: str) -> None:
    assert config.is_secure_api_url(url) is True


@pytest.mark.parametrize("url", REFUSED_029)
def test_get_settings_refuses_invalid_port_or_control_character(
    monkeypatch, secrets, factory, url: str
) -> None:
    # Through st.secrets: the environment cannot hold U+0000.
    secrets(FakeSecrets(API_BASE_URL=url, READ_API_KEY=factory.new_key()))
    with pytest.raises(config.InsecureApiUrlError) as info:
        config.get_settings()
    message = str(info.value)
    # The same fixed text as before (SPEC-028 §4.1): the value never appears (R-03).
    assert message == "API_BASE_URL must use https:// (http:// only for localhost or 127.0.0.1)"
    assert url not in message
    assert "example.org" not in message


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.org:abc",
        "http://local\thost:8001",
        "https://api.exa\nmple.org",
        "https://api.example.org\x7f",
        "https://api.exa\x85mple.org",
    ],
)
def test_get_settings_refuses_them_from_the_environment(
    monkeypatch, secrets, factory, url: str
) -> None:
    monkeypatch.setenv("API_BASE_URL", url)
    monkeypatch.setenv("READ_API_KEY", factory.new_key())
    with pytest.raises(config.InsecureApiUrlError):
        config.get_settings()


@pytest.mark.parametrize("edge", ["\n", "\t", "\r\n", "\x85", "\x1f"])
def test_control_character_only_at_the_edges_is_trimmed_first(
    monkeypatch, secrets, factory, edge: str
) -> None:
    # SPEC-029 §4.3: _read() trims the value (SPEC-013 §4.1) before the check, and the trimmed
    # URL is the one the client uses.
    monkeypatch.setenv("API_BASE_URL", f"{edge}https://api.example.org/{edge}")
    monkeypatch.setenv("READ_API_KEY", factory.new_key())
    assert config.get_settings().api_base_url == "https://api.example.org"


def test_trailing_del_is_not_trimmed(monkeypatch, secrets, factory) -> None:
    monkeypatch.setenv("API_BASE_URL", "https://api.example.org/\x7f")
    monkeypatch.setenv("READ_API_KEY", factory.new_key())
    with pytest.raises(config.InsecureApiUrlError):
        config.get_settings()
