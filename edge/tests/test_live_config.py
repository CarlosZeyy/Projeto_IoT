"""HTTPS and configuration of the live mode (SPEC-019 sections 4.1 and 4.6)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qc_edge import cli
from qc_edge.config import EdgeSettings
from qc_edge.security import is_allowed_console_host


@pytest.fixture
def tls_files(tmp_path: Path) -> tuple[Path, Path]:
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("certificate")
    key.write_text("private key content")
    key.chmod(0o600)
    return cert, key


@pytest.mark.parametrize(
    ("host", "port", "tls", "allowed"),
    [
        ("127.0.0.1", 443, True, True),
        ("localhost", 443, True, True),
        ("[::1]", 443, True, True),
        ("127.0.0.1:443", 443, True, True),
        ("127.0.0.1", 443, False, False),
        ("127.0.0.1", 80, True, False),
        ("127.0.0.1:80", 80, True, True),
        ("127.0.0.1", 80, False, True),
        ("127.0.0.1", 8000, True, False),
        ("127.0.0.1:8000", 8000, True, True),
        ("evil.example", 443, True, False),
        ("127.0.0.1.nip.io", 443, True, False),
    ],
)
def test_console_host_with_tls(host: str, port: int, tls: bool, allowed: bool) -> None:
    assert is_allowed_console_host(host, port, tls=tls) is allowed


def test_uvicorn_arguments_without_tls(settings: EdgeSettings) -> None:
    assert cli.uvicorn_kwargs(settings) == {
        "host": "0.0.0.0",
        "port": 8000,
        "proxy_headers": False,
        "access_log": False,
        "log_level": "info",
    }


def test_uvicorn_arguments_with_tls(
    clean_edge_env: None, tmp_path: Path, tls_files: tuple[Path, Path]
) -> None:
    settings = EdgeSettings(
        EDGE_DATA_DIR=tmp_path, EDGE_TLS_CERT=str(tls_files[0]), EDGE_TLS_KEY=str(tls_files[1])
    )
    kwargs = cli.uvicorn_kwargs(settings)
    assert kwargs["ssl_certfile"] == str(tls_files[0])
    assert kwargs["ssl_keyfile"] == str(tls_files[1])
    assert kwargs["proxy_headers"] is False
    assert settings.tls_enabled is True


def test_main_starts_with_tls_and_logs_the_https_console(
    clean_edge_env: None,
    tmp_path: Path,
    tls_files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    spy: list[dict[str, Any]] = []
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EDGE_TLS_CERT", str(tls_files[0]))
    monkeypatch.setenv("EDGE_TLS_KEY", str(tls_files[1]))
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: spy.append(kwargs))
    with caplog.at_level(logging.INFO, logger="qc_edge"):
        cli.main([])
    assert spy[0]["ssl_keyfile"] == str(tls_files[1])
    assert "operator console: https://127.0.0.1:8000/" in caplog.text


def _start(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, **env: str) -> int:
    calls: list[Any] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with caplog.at_level(logging.INFO, logger="qc_edge"), pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert calls == []
    return excinfo.value.code


@pytest.fixture
def edge_env(clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "data"))


def test_tls_only_certificate_exits_2(
    edge_env: None,
    tls_files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert _start(monkeypatch, caplog, EDGE_TLS_CERT=str(tls_files[0])) == 2
    assert "EDGE_TLS_KEY" in caplog.text


def test_tls_only_key_exits_2(
    edge_env: None,
    tls_files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert _start(monkeypatch, caplog, EDGE_TLS_KEY=str(tls_files[1])) == 2
    assert "EDGE_TLS_CERT" in caplog.text


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o620, 0o610, 0o601])
def test_tls_key_with_group_or_other_permission_exits_2(
    edge_env: None,
    tls_files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mode: int,
) -> None:
    tls_files[1].chmod(mode)
    code = _start(
        monkeypatch, caplog, EDGE_TLS_CERT=str(tls_files[0]), EDGE_TLS_KEY=str(tls_files[1])
    )
    assert code == 2
    assert "EDGE_TLS_KEY" in caplog.text
    assert "private key content" not in caplog.text
    assert str(tls_files[1]) not in caplog.text


@pytest.mark.parametrize("mode", [0o600, 0o400])
def test_tls_key_private_modes_are_accepted(
    clean_edge_env: None, tmp_path: Path, tls_files: tuple[Path, Path], mode: int
) -> None:
    tls_files[1].chmod(mode)
    EdgeSettings(EDGE_DATA_DIR=tmp_path, EDGE_TLS_CERT=tls_files[0], EDGE_TLS_KEY=tls_files[1])


@pytest.mark.parametrize("name", ["EDGE_TLS_CERT", "EDGE_TLS_KEY"])
@pytest.mark.parametrize("kind", ["missing", "directory", "fifo", "nul"])
def test_tls_path_that_is_not_a_readable_file_exits_2(
    edge_env: None,
    tmp_path: Path,
    tls_files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    name: str,
    kind: str,
) -> None:
    bad = tmp_path / "bad"
    if kind == "directory":
        bad.mkdir(mode=0o700)
    elif kind == "fifo":
        os.mkfifo(bad, 0o600)
    env = {"EDGE_TLS_CERT": str(tls_files[0]), "EDGE_TLS_KEY": str(tls_files[1])}
    env[name] = str(bad)
    if kind == "nul":
        # The environment cannot carry a NUL: straight to the settings.
        with pytest.raises(ValidationError) as excinfo:
            EdgeSettings(EDGE_DATA_DIR=tmp_path, **{**env, name: "bad\x00path"})
        assert {error["loc"][0] for error in excinfo.value.errors()} == {name}
        return
    assert _start(monkeypatch, caplog, **env) == 2
    assert name in caplog.text


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_tls_certificate_that_does_not_open_exits_2(
    edge_env: None,
    tls_files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tls_files[0].chmod(0o000)
    try:
        code = _start(
            monkeypatch, caplog, EDGE_TLS_CERT=str(tls_files[0]), EDGE_TLS_KEY=str(tls_files[1])
        )
    finally:
        tls_files[0].chmod(0o600)
    assert code == 2
    assert "EDGE_TLS_CERT" in caplog.text


def test_tls_empty_values_mean_http(clean_edge_env: None, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EDGE_TLS_CERT", "")
    monkeypatch.setenv("EDGE_TLS_KEY", "")
    assert EdgeSettings(EDGE_DATA_DIR=tmp_path).tls_enabled is False
    direct = EdgeSettings(EDGE_DATA_DIR=tmp_path, EDGE_TLS_CERT="", EDGE_TLS_KEY="")
    assert direct.tls_enabled is False


def test_tls_certificate_content_is_not_checked(
    clean_edge_env: None, tmp_path: Path, tls_files: tuple[Path, Path]
) -> None:
    tls_files[0].write_bytes(b"\x00not a pem")
    settings = EdgeSettings(
        EDGE_DATA_DIR=tmp_path, EDGE_TLS_CERT=tls_files[0], EDGE_TLS_KEY=tls_files[1]
    )
    assert settings.tls_enabled is True


# -------------------------------------------------------------------------------- configuration


@pytest.fixture
def settings_factory(clean_edge_env: None, tmp_path: Path) -> Callable[..., EdgeSettings]:
    def _make(**values: Any) -> EdgeSettings:
        return EdgeSettings(EDGE_DATA_DIR=tmp_path / "d", DATASET_DIR=tmp_path / "ds", **values)

    return _make


def test_live_defaults(settings_factory: Callable[..., EdgeSettings]) -> None:
    settings = settings_factory()
    assert settings.LIVE_WINDOW == 10
    assert settings.LIVE_MIN_AGREE == 8
    assert settings.LIVE_MIN_CONFIDENCE == 0.80
    assert settings.LIVE_EMPTY_FRAMES == 3
    assert settings.LIVE_MAX_SESSIONS == 4
    assert settings.LIVE_FPS == 2
    assert settings.EDGE_TLS_CERT is None
    assert settings.EDGE_TLS_KEY is None
    assert settings.tls_enabled is False


@pytest.mark.parametrize(
    ("env", "name"),
    [
        ({"LIVE_WINDOW": "2"}, "LIVE_WINDOW"),
        ({"LIVE_WINDOW": "31"}, "LIVE_WINDOW"),
        ({"LIVE_WINDOW": "ten"}, "LIVE_WINDOW"),
        ({"LIVE_MIN_AGREE": "0"}, "LIVE_MIN_AGREE"),
        ({"LIVE_MIN_AGREE": "11", "LIVE_WINDOW": "10"}, "LIVE_MIN_AGREE"),
        ({"LIVE_WINDOW": "5"}, "LIVE_MIN_AGREE"),  # the default 8 does not fit a window of 5
        ({"LIVE_MIN_CONFIDENCE": "1.2"}, "LIVE_MIN_CONFIDENCE"),
        ({"LIVE_MIN_CONFIDENCE": "0.49"}, "LIVE_MIN_CONFIDENCE"),
        ({"LIVE_MIN_CONFIDENCE": "0.995"}, "LIVE_MIN_CONFIDENCE"),
        ({"LIVE_MIN_CONFIDENCE": "nan"}, "LIVE_MIN_CONFIDENCE"),
        ({"LIVE_EMPTY_FRAMES": "0"}, "LIVE_EMPTY_FRAMES"),
        ({"LIVE_EMPTY_FRAMES": "11"}, "LIVE_EMPTY_FRAMES"),
        ({"LIVE_MAX_SESSIONS": "0"}, "LIVE_MAX_SESSIONS"),
        ({"LIVE_MAX_SESSIONS": "9"}, "LIVE_MAX_SESSIONS"),
        ({"LIVE_FPS": "0"}, "LIVE_FPS"),
        ({"LIVE_FPS": "6"}, "LIVE_FPS"),
    ],
)
def test_invalid_live_values_exit_2_naming_the_variable(
    edge_env: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    env: dict[str, str],
    name: str,
) -> None:
    assert _start(monkeypatch, caplog, **env) == 2
    assert name in caplog.text


@pytest.mark.parametrize(
    "values",
    [
        {"LIVE_WINDOW": 3, "LIVE_MIN_AGREE": 1},
        {"LIVE_WINDOW": 3, "LIVE_MIN_AGREE": 3},
        {"LIVE_WINDOW": 30, "LIVE_MIN_AGREE": 30},
        {"LIVE_MIN_CONFIDENCE": 0.50},
        {"LIVE_MIN_CONFIDENCE": 0.99},
        {"LIVE_EMPTY_FRAMES": 1},
        {"LIVE_EMPTY_FRAMES": 10},
        {"LIVE_MAX_SESSIONS": 1},
        {"LIVE_MAX_SESSIONS": 8},
        {"LIVE_FPS": 1},
        {"LIVE_FPS": 5},
    ],
)
def test_live_bounds_are_accepted(
    settings_factory: Callable[..., EdgeSettings], values: dict[str, Any]
) -> None:
    settings = settings_factory(**values)
    assert {name: getattr(settings, name) for name in values} == values


def test_invalid_window_is_reported_once(settings_factory: Callable[..., EdgeSettings]) -> None:
    with pytest.raises(ValidationError) as excinfo:
        settings_factory(LIVE_WINDOW=2)
    assert {error["loc"][0] for error in excinfo.value.errors()} == {"LIVE_WINDOW"}
