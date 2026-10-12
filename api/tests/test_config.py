"""Settings (SPEC-004 section 4.1): environment only, required values, no values in errors."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from qc_api.config import Settings

ENV_NAMES = ("DATABASE_URL", "READ_API_KEY", "MAX_BODY_BYTES", "LOG_LEVEL")
DB_URL = "postgresql://localhost/partqc_test"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def test_defaults() -> None:
    settings = Settings(DATABASE_URL=DB_URL, READ_API_KEY="r" * 32)
    assert settings.MAX_BODY_BYTES == 262_144
    assert settings.LOG_LEVEL == "INFO"
    assert settings.DATABASE_URL.get_secret_value() == DB_URL


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("READ_API_KEY", "k" * 40)
    monkeypatch.setenv("MAX_BODY_BYTES", "1024")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = Settings()
    assert settings.READ_API_KEY.get_secret_value() == "k" * 40
    assert settings.MAX_BODY_BYTES == 1024
    assert settings.LOG_LEVEL == "DEBUG"


def test_secrets_are_masked_in_repr() -> None:
    settings = Settings(DATABASE_URL=DB_URL, READ_API_KEY="q" * 32)
    assert DB_URL not in repr(settings)
    assert "q" * 32 not in repr(settings)


def test_dotenv_file_is_not_read(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"DATABASE_URL={DB_URL}\nREAD_API_KEY={'r' * 32}\n")
    with pytest.raises(ValidationError):
        Settings()


def test_short_read_key_error_hides_value() -> None:
    value = "s3cr" + "x" * 27  # 31 characters
    with pytest.raises(ValidationError) as info:
        Settings(DATABASE_URL=DB_URL, READ_API_KEY=value)
    message = str(info.value)
    assert "READ_API_KEY" in message
    assert value not in message


def test_missing_database_url() -> None:
    read_key = "z" * 32
    with pytest.raises(ValidationError) as info:
        Settings(READ_API_KEY=read_key)
    assert "DATABASE_URL" in str(info.value)
    assert read_key not in str(info.value)


def test_empty_database_url_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(DATABASE_URL="", READ_API_KEY="r" * 32)


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_invalid_max_body_bytes(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MAX_BODY_BYTES", value)
    with pytest.raises(ValidationError) as info:
        Settings(DATABASE_URL=DB_URL, READ_API_KEY="r" * 32)
    assert "MAX_BODY_BYTES" in str(info.value)


@pytest.mark.parametrize("value", ["TRACE", "info", ""])
def test_invalid_log_level(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("LOG_LEVEL", value)
    with pytest.raises(ValidationError):
        Settings(DATABASE_URL=DB_URL, READ_API_KEY="r" * 32)


def test_database_url_value_not_in_error(monkeypatch: pytest.MonkeyPatch) -> None:
    secret_url = "postgresql://localhost/" + "dbsecret" * 2
    monkeypatch.setenv("DATABASE_URL", secret_url)
    with pytest.raises(ValidationError) as info:
        Settings(READ_API_KEY="tiny-read-key-value")
    assert secret_url not in str(info.value)
    assert "tiny-read-key-value" not in str(info.value)
