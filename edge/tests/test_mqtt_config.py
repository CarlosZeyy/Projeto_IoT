"""Configuration and choice of the publisher (SPEC-020 section 4.5) and static rules (CA-10).

``qc-edge`` runs with ``create_app`` kept and ``uvicorn.run`` replaced; ``PahoMqttTransport`` is
replaced by an ``InMemoryBroker`` client where a transport is built, so no broker is reached.
"""

from __future__ import annotations

import ast
import importlib.util
import logging
import secrets
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qc_edge import cli
from qc_edge.config import (
    BridgeSettings,
    EdgeSettings,
    config_error_message,
    missing_bridge_settings,
    missing_mqtt_credentials,
)
from qc_edge.heartbeat import HeartbeatLoop
from qc_edge.mqtt_publisher import MqttPublisher
from qc_edge.mqtt_transport import InMemoryBroker
from qc_edge.publish_loop import PublishLoop
from qc_edge.publisher import HttpPublisher
from qc_edge.sink import InMemorySink

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "edge" / "src" / "qc_edge"


def device_key() -> str:
    return "dk-" + secrets.token_urlsafe(24)


def mqtt_password() -> str:
    return "pw-" + secrets.token_urlsafe(12)


# -- EdgeSettings ------------------------------------------------------------------------------


def test_defaults(settings: EdgeSettings) -> None:
    assert settings.EDGE_PUBLISHER == "http"
    assert settings.MQTT_HOST == "127.0.0.1"
    assert settings.MQTT_PORT == 1883
    assert settings.MQTT_USERNAME is None
    assert settings.MQTT_PASSWORD is None
    assert settings.MQTT_RESPONSE_TIMEOUT_S == 15.0


@pytest.mark.parametrize("value", ["http", "mqtt"])
def test_edge_publisher_accepted(clean_edge_env: None, tmp_path: Path, value: str) -> None:
    settings = EdgeSettings(EDGE_DATA_DIR=tmp_path, EDGE_PUBLISHER=value)
    assert value == settings.EDGE_PUBLISHER


@pytest.mark.parametrize("value", ["xyz", "MQTT", " mqtt", "https"])
def test_edge_publisher_refused_with_the_exact_message(
    clean_edge_env: None, tmp_path: Path, value: str
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        EdgeSettings(EDGE_DATA_DIR=tmp_path, EDGE_PUBLISHER=value)
    assert config_error_message(excinfo.value) == "EDGE_PUBLISHER must be http or mqtt"


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_mqtt_host_loopback_only(clean_edge_env: None, tmp_path: Path, host: str) -> None:
    settings = EdgeSettings(EDGE_DATA_DIR=tmp_path, MQTT_HOST=host)
    assert host == settings.MQTT_HOST


@pytest.mark.parametrize(
    "host", ["192.168.0.10", "0.0.0.0", "broker.example.org", "127.0.0.2", "LOCALHOST"]
)
def test_mqtt_host_refused(clean_edge_env: None, tmp_path: Path, host: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        EdgeSettings(EDGE_DATA_DIR=tmp_path, MQTT_HOST=host)
    message = config_error_message(excinfo.value)
    assert message.startswith("MQTT_HOST: ")
    assert host not in message


@pytest.mark.parametrize("port", ["0", "65536", "-1", "abc"])
def test_mqtt_port_refused(
    clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, port: str
) -> None:
    monkeypatch.setenv("MQTT_PORT", port)
    with pytest.raises(ValidationError) as excinfo:
        EdgeSettings(EDGE_DATA_DIR=tmp_path)
    assert "MQTT_PORT" in config_error_message(excinfo.value)


@pytest.mark.parametrize("value", ["1", "60", "2.5"])
def test_response_timeout_accepted(
    clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("MQTT_RESPONSE_TIMEOUT_S", value)
    settings = EdgeSettings(EDGE_DATA_DIR=tmp_path)
    assert float(value) == settings.MQTT_RESPONSE_TIMEOUT_S


@pytest.mark.parametrize("value", ["0.5", "61", "0", "nan", "inf", "abc"])
def test_response_timeout_refused(
    clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("MQTT_RESPONSE_TIMEOUT_S", value)
    with pytest.raises(ValidationError) as excinfo:
        EdgeSettings(EDGE_DATA_DIR=tmp_path)
    assert "MQTT_RESPONSE_TIMEOUT_S" in config_error_message(excinfo.value)


def test_empty_values_keep_the_defaults(
    clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("EDGE_PUBLISHER", "MQTT_HOST", "MQTT_PORT", "MQTT_PASSWORD"):
        monkeypatch.setenv(name, "")
    settings = EdgeSettings(EDGE_DATA_DIR=tmp_path)
    assert settings.EDGE_PUBLISHER == "http"
    assert settings.MQTT_PORT == 1883
    assert missing_mqtt_credentials(settings) == ["MQTT_USERNAME", "MQTT_PASSWORD"]


def test_password_is_a_secret(clean_edge_env: None, tmp_path: Path) -> None:
    password = mqtt_password()
    settings = EdgeSettings(EDGE_DATA_DIR=tmp_path, MQTT_USERNAME="u", MQTT_PASSWORD=password)
    assert password not in repr(settings)
    assert missing_mqtt_credentials(settings) == []


def test_config_error_message_keeps_the_name_prefix_for_other_errors(
    clean_edge_env: None, tmp_path: Path
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        EdgeSettings(EDGE_DATA_DIR=tmp_path, EDGE_PORT=0, EDGE_PUBLISHER="x")
    message = config_error_message(excinfo.value)
    assert "EDGE_PORT: " in message
    assert "; EDGE_PUBLISHER must be http or mqtt" in message


# -- BridgeSettings ----------------------------------------------------------------------------


def test_bridge_settings_create_no_directory(
    clean_edge_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = BridgeSettings()
    assert list(tmp_path.iterdir()) == []
    assert missing_bridge_settings(settings) == [
        "DEVICE_API_KEY",
        "CLOUD_API_URL",
        "MQTT_USERNAME",
        "MQTT_PASSWORD",
    ]


def test_bridge_settings_validate_the_url_and_host(clean_edge_env: None) -> None:
    with pytest.raises(ValidationError):
        BridgeSettings(CLOUD_API_URL="http://api.exemplo.org")
    with pytest.raises(ValidationError):
        BridgeSettings(MQTT_HOST="10.0.0.1")
    settings = BridgeSettings(CLOUD_API_URL="https://api.exemplo.org/")
    assert settings.CLOUD_API_URL == "https://api.exemplo.org"


# -- qc-edge start ---------------------------------------------------------------------------


class _Spy:
    def __init__(self) -> None:
        self.background: list[Any] = []
        self.sink: Any = None

    def create_app(self, settings: Any, inferencer: Any, sink: Any, **kwargs: Any) -> Any:
        self.sink = sink
        self.background = list(kwargs.get("background", ()))
        return _real_create_app(settings, inferencer, sink, **kwargs)


_real_create_app = cli.create_app


@pytest.fixture
def spy(clean_edge_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Spy:
    monkeypatch.setenv("EDGE_DATA_DIR", str(tmp_path / "data"))
    spy = _Spy()
    monkeypatch.setattr(cli, "create_app", spy.create_app)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: None)
    return spy


@pytest.fixture
def transports(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    """Every ``PahoMqttTransport(...)`` built by ``qc-edge``; an in-memory client is returned."""
    built: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    broker = InMemoryBroker()

    def fake(*args: Any, **kwargs: Any) -> Any:
        built.append((args, kwargs))
        return broker.client()

    monkeypatch.setattr(cli, "PahoMqttTransport", fake)
    return built


def cloud_env(monkeypatch: pytest.MonkeyPatch, **extra: str) -> dict[str, str]:
    values = {"DEVICE_API_KEY": device_key(), "CLOUD_API_URL": "http://127.0.0.1:9000", **extra}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def test_http_is_the_default(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch, transports: list[Any]
) -> None:
    cloud_env(monkeypatch)
    cli.main([])
    loop = spy.background[0]
    assert isinstance(loop, PublishLoop)
    assert isinstance(loop._publisher, HttpPublisher)
    assert transports == []


def test_mqtt_publisher_in_the_loop(
    spy: _Spy,
    monkeypatch: pytest.MonkeyPatch,
    transports: list[Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    password = mqtt_password()
    values = cloud_env(
        monkeypatch,
        EDGE_PUBLISHER="mqtt",
        MQTT_USERNAME="partqc-edge",
        MQTT_PASSWORD=password,
        MQTT_PORT="1884",
        MQTT_HOST="localhost",
        MQTT_RESPONSE_TIMEOUT_S="7",
    )
    with caplog.at_level(logging.DEBUG):
        cli.main([])
    loop, heartbeat = spy.background
    assert isinstance(loop, PublishLoop)
    assert isinstance(loop._publisher, MqttPublisher)
    assert loop._publisher._response_timeout_s == 7.0
    # SPEC-018: the heartbeat stays on HTTP.
    assert isinstance(heartbeat, HeartbeatLoop)
    ((args, kwargs),) = transports
    assert args == ("localhost", 1884, "partqc-edge", password)
    assert kwargs == {"client_id": "partqc-edge-edge-01"}
    assert "publisher: mqtt (broker localhost:1884" in caplog.text
    assert password not in caplog.text
    assert values["DEVICE_API_KEY"] not in caplog.text


def test_mqtt_without_the_key_or_url_publishes_nothing(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch, transports: list[Any]
) -> None:
    for name, value in (
        ("EDGE_PUBLISHER", "mqtt"),
        ("MQTT_USERNAME", "u"),
        ("MQTT_PASSWORD", mqtt_password()),
    ):
        monkeypatch.setenv(name, value)
    cli.main([])
    assert spy.background == []
    assert transports == []
    assert spy.sink.stats().connectivity == "disabled"


def test_mqtt_with_stub_model_has_no_publisher(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch, transports: list[Any]
) -> None:
    cloud_env(monkeypatch, EDGE_PUBLISHER="mqtt", MQTT_USERNAME="u", MQTT_PASSWORD=mqtt_password())
    cli.main(["--stub-model"])
    assert isinstance(spy.sink, InMemorySink)
    assert spy.background == []
    assert transports == []


@pytest.mark.parametrize("stub", [False, True], ids=["model", "stub"])
@pytest.mark.parametrize("missing", ["MQTT_PASSWORD", "MQTT_USERNAME"])
def test_mqtt_without_credentials_exits_2(
    spy: _Spy,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    transports: list[Any],
    missing: str,
    stub: bool,
) -> None:
    password = mqtt_password()
    cloud_env(monkeypatch, EDGE_PUBLISHER="mqtt", MQTT_USERNAME="u", MQTT_PASSWORD=password)
    monkeypatch.setenv(missing, "")
    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as excinfo:
        cli.main(["--stub-model"] if stub else [])
    assert excinfo.value.code == 2
    assert f"{missing}: required with EDGE_PUBLISHER=mqtt" in caplog.text
    assert password not in caplog.text
    assert transports == []


def test_invalid_edge_publisher_exits_2_with_the_message(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("EDGE_PUBLISHER", "xyz")
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "invalid configuration: EDGE_PUBLISHER must be http or mqtt" in err


def test_remote_mqtt_host_exits_2(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    cloud_env(
        monkeypatch,
        EDGE_PUBLISHER="mqtt",
        MQTT_HOST="192.168.0.10",
        MQTT_USERNAME="u",
        MQTT_PASSWORD=mqtt_password(),
    )
    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2
    assert "MQTT_HOST" in caplog.text
    assert "192.168.0.10" not in caplog.text


# -- static rules (CA-10) and files ----------------------------------------------------------


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_only_the_transport_imports_paho() -> None:
    importers = {
        path.name
        for path in SRC.rglob("*.py")
        if any(n == "paho" or n.startswith("paho.") for n in _imports(path))
    }
    assert importers == {"mqtt_transport.py"}


def test_paho_is_not_in_the_api_or_dashboard_closure() -> None:
    spec = importlib.util.spec_from_file_location("partqc_lgraph", ROOT / "tests/lockgraph.py")
    assert spec is not None and spec.loader is not None
    lockgraph = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = lockgraph
    spec.loader.exec_module(lockgraph)
    lock = lockgraph.load_lock(ROOT / "uv.lock")
    assert "paho-mqtt" in lockgraph.dependency_closure(lock, "qc-edge")
    for package in ("qc-api", "qc-dashboard"):
        assert "paho-mqtt" not in lockgraph.dependency_closure(lock, package)
    (paho,) = [p for p in lock["package"] if p["name"] == "paho-mqtt"]
    assert paho["version"] == "2.1.0"


def test_mqtt_marker_is_declared() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    markers = config["tool"]["pytest"]["ini_options"]["markers"]
    assert [m for m in markers if m.startswith("mqtt:")]


def test_mosquitto_example_config() -> None:
    lines = [
        line.strip()
        for line in (ROOT / "edge/mosquitto/partqc.conf").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "listener 1883 127.0.0.1" in lines
    assert "allow_anonymous false" in lines
    (password_file,) = [line for line in lines if line.startswith("password_file ")]
    path = Path(password_file.split(" ", 1)[1])
    assert path.is_absolute()
    assert not str(path).startswith(str(ROOT))
    assert not [line for line in lines if line.startswith("listener") and "127.0.0.1" not in line]


def test_env_example_documents_the_variables() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in (
        "EDGE_PUBLISHER=http",
        "MQTT_HOST=127.0.0.1",
        "MQTT_PORT=1883",
        "MQTT_USERNAME=",
        "MQTT_PASSWORD=",
        "MQTT_RESPONSE_TIMEOUT_S=15",
    ):
        assert f"\n{name}\n" in text
