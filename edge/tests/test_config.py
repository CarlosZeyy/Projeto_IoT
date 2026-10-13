"""EdgeSettings (SPEC-007 section 4.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from qc_edge.config import EdgeSettings


def _invalid_names(exc: ValidationError) -> set[str]:
    return {str(error["loc"][0]) for error in exc.errors()}


def test_defaults(clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = EdgeSettings()
    assert settings.EDGE_HOST == "0.0.0.0"
    assert settings.EDGE_PORT == 8000
    assert settings.EDGE_SESSION_TOKEN is None
    assert settings.DEVICE_ID == "edge-01"
    assert Path("edge/data") == settings.EDGE_DATA_DIR
    assert (tmp_path / "edge" / "data").is_dir()
    assert settings.DEVICE_API_KEY is None
    assert settings.MODEL_DIR is None
    assert settings.TYPE_THRESHOLD is None


def test_reads_environment(
    clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "k" * 40
    monkeypatch.setenv("EDGE_HOST", "127.0.0.1")
    monkeypatch.setenv("EDGE_PORT", "8080")
    monkeypatch.setenv("EDGE_SESSION_TOKEN", token)
    monkeypatch.setenv("DEVICE_ID", "edge-02")
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("MODEL_DIR", "ml/models/x")
    monkeypatch.setenv("TYPE_THRESHOLD", "0.5")
    settings = EdgeSettings()
    assert settings.EDGE_HOST == "127.0.0.1"
    assert settings.EDGE_PORT == 8080
    assert settings.EDGE_SESSION_TOKEN is not None
    assert settings.EDGE_SESSION_TOKEN.get_secret_value() == token
    assert settings.DEVICE_ID == "edge-02"
    assert tmp_path / "d" == settings.EDGE_DATA_DIR
    assert Path("ml/models/x") == settings.MODEL_DIR
    assert settings.TYPE_THRESHOLD == 0.5


def test_empty_variables_count_as_unset(
    clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The blank lines of .env.example (EDGE_SESSION_TOKEN=, DEVICE_API_KEY=, ...).
    for name in ("EDGE_SESSION_TOKEN", "DEVICE_API_KEY", "MODEL_DIR", "TYPE_THRESHOLD"):
        monkeypatch.setenv(name, "")
    settings = EdgeSettings(EDGE_DATA_DIR=tmp_path)
    assert settings.EDGE_SESSION_TOKEN is None
    assert settings.DEVICE_API_KEY is None
    assert settings.MODEL_DIR is None
    assert settings.TYPE_THRESHOLD is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EDGE_PORT", "70000"),
        ("EDGE_PORT", "0"),
        ("EDGE_PORT", "http"),
        ("DEVICE_ID", "Edge_01"),
        ("DEVICE_ID", "edge-01\n"),
        ("DEVICE_ID", "ed"),
        ("DEVICE_ID", "e" * 33),
        ("EDGE_SESSION_TOKEN", "short12345"),
        ("EDGE_SESSION_TOKEN", "x" * 31),
        ("EDGE_HOST", "localhost"),
        ("EDGE_HOST", "0.0.0.0 "),
    ],
)
def test_invalid_values_name_the_variable(
    clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError) as excinfo:
        EdgeSettings(EDGE_DATA_DIR=tmp_path)
    assert _invalid_names(excinfo.value) == {name}


def test_token_of_exactly_32_chars_is_accepted(clean_edge_env: None, tmp_path: Path) -> None:
    settings = EdgeSettings(EDGE_DATA_DIR=tmp_path, EDGE_SESSION_TOKEN="t" * 32)
    assert settings.EDGE_SESSION_TOKEN is not None


def test_error_never_shows_the_value(
    clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_like = "Zq" + "9" * 8  # 10 characters, too short
    monkeypatch.setenv("EDGE_SESSION_TOKEN", secret_like)
    with pytest.raises(ValidationError) as excinfo:
        EdgeSettings(EDGE_DATA_DIR=tmp_path)
    assert secret_like not in str(excinfo.value)


def test_ipv6_host_literal_is_accepted(clean_edge_env: None, tmp_path: Path) -> None:
    assert EdgeSettings(EDGE_DATA_DIR=tmp_path, EDGE_HOST="::").EDGE_HOST == "::"


def test_data_dir_is_created(clean_edge_env: None, tmp_path: Path) -> None:
    target = tmp_path / "a" / "b"
    EdgeSettings(EDGE_DATA_DIR=target)
    assert target.is_dir()


def test_data_dir_that_is_a_file_is_invalid(clean_edge_env: None, tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(ValidationError) as excinfo:
        EdgeSettings(EDGE_DATA_DIR=blocker)
    assert _invalid_names(excinfo.value) == {"EDGE_DATA_DIR"}
