"""MQTT transport (SPEC-020 section 4.2): ``InMemoryBroker`` and ``PahoMqttTransport``.

The ``PahoMqttTransport`` tests without the ``mqtt`` marker never reach a broker: they use a
closed port of ``127.0.0.1`` or call the ``paho`` callbacks directly. The tests marked ``mqtt``
start a real Mosquitto (``mosquitto_broker`` fixture) and are skipped without
``PARTQC_MQTT_TESTS=1``.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
import types
from typing import Any

import paho.mqtt.client as paho
import pytest
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from qc_edge import mqtt_transport
from qc_edge.mqtt_transport import (
    InMemoryBroker,
    MqttMessage,
    MqttTransportError,
    PahoMqttTransport,
    topic_matches,
)


def _collector() -> tuple[list[MqttMessage], Any]:
    received: list[MqttMessage] = []
    return received, received.append


# -- MqttMessage and topics --------------------------------------------------------------------


def test_user_property_returns_the_first_match() -> None:
    message = MqttMessage("t", user_properties=(("result", "ok"), ("result", "x"), ("a", "b")))
    assert message.user_property("result") == "ok"
    assert message.user_property("a") == "b"
    assert message.user_property("missing") is None


@pytest.mark.parametrize(
    ("topic_filter", "topic", "matches"),
    [
        ("partqc/v1/edge-01/batch", "partqc/v1/edge-01/batch", True),
        ("partqc/v1/+/batch", "partqc/v1/edge-01/batch", True),
        ("partqc/v1/#", "partqc/v1/edge-01/reply/abc", True),
        ("partqc/v1/edge-01/batch", "partqc/v1/edge-02/batch", False),
        ("partqc/v1/+/batch", "partqc/v1/edge-01/health", False),
    ],
)
def test_topic_matches(topic_filter: str, topic: str, matches: bool) -> None:
    assert topic_matches(topic_filter, topic) is matches


# -- InMemoryBroker ----------------------------------------------------------------------------


def test_in_memory_delivery_is_synchronous_with_properties() -> None:
    broker = InMemoryBroker()
    sender, receiver = broker.client("a"), broker.client("b")
    received, handler = _collector()
    receiver.subscribe("partqc/v1/+/batch", handler)
    sender.connect()
    receiver.connect()
    message = MqttMessage(
        "partqc/v1/edge-01/batch",
        b"{}",
        response_topic="partqc/v1/edge-01/reply/s1",
        correlation_data=b"\x01" * 16,
        user_properties=(("result", "ok"),),
    )
    sender.publish(message)
    assert received == [message]  # already delivered when publish returns
    assert broker.published == [message]
    assert broker.published_on("partqc/v1/edge-01/#") == [message]
    assert sender.pubacks == 1


def test_in_memory_qos0_has_no_puback() -> None:
    broker = InMemoryBroker()
    client = broker.client()
    client.connect()
    client.publish(MqttMessage("t"), qos=0)
    assert client.pubacks == 0
    assert len(broker.published) == 1


def test_in_memory_publisher_receives_its_own_messages() -> None:
    broker = InMemoryBroker()
    client = broker.client()
    received, handler = _collector()
    client.subscribe("t/#", handler)
    client.connect()
    client.publish(MqttMessage("t/x"))
    assert [m.topic for m in received] == ["t/x"]


def test_in_memory_not_connected_client_gets_nothing() -> None:
    broker = InMemoryBroker()
    sender, idle = broker.client(), broker.client()
    received, handler = _collector()
    idle.subscribe("t", handler)
    sender.connect()
    sender.publish(MqttMessage("t"))
    assert received == []


def test_in_memory_publish_requires_connect() -> None:
    client = InMemoryBroker().client()
    with pytest.raises(MqttTransportError, match="not connected"):
        client.publish(MqttMessage("t"))


def test_in_memory_stop_and_start_keep_subscriptions() -> None:
    broker = InMemoryBroker()
    sender, receiver = broker.client(), broker.client()
    received, handler = _collector()
    receiver.subscribe("t", handler)
    sender.connect()
    receiver.connect()

    broker.stop()
    assert not broker.running
    assert not receiver.connected
    with pytest.raises(MqttTransportError, match="not reachable"):
        sender.publish(MqttMessage("t"))
    with pytest.raises(MqttTransportError, match="not reachable"):
        broker.client().connect()
    assert broker.published == []

    broker.start()
    sender.publish(MqttMessage("t"))
    assert len(received) == 1


def test_in_memory_disconnect_drops_subscriptions() -> None:
    broker = InMemoryBroker()
    sender, receiver = broker.client(), broker.client()
    received, handler = _collector()
    receiver.subscribe("t", handler)
    receiver.connect()
    sender.connect()
    receiver.disconnect()
    receiver.connect()
    sender.publish(MqttMessage("t"))
    assert received == []


def test_in_memory_intercept_acks_without_delivering() -> None:
    broker = InMemoryBroker()
    sender, receiver = broker.client(), broker.client()
    received, handler = _collector()
    receiver.subscribe("t", handler)
    sender.connect()
    receiver.connect()
    broker.intercept = lambda message: message.payload != b"drop"
    sender.publish(MqttMessage("t", b"drop"))
    sender.publish(MqttMessage("t", b"keep"))
    assert [m.payload for m in received] == [b"keep"]
    assert [m.payload for m in broker.published] == [b"drop", b"keep"]
    assert sender.pubacks == 2


def test_in_memory_handler_error_is_logged_without_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broker = InMemoryBroker()
    client = broker.client()
    secret_payload = b"payload-" + b"z" * 8

    def broken(message: MqttMessage) -> None:
        raise RuntimeError(message.payload.decode())

    client.subscribe("t", broken)
    client.connect()
    with caplog.at_level(logging.DEBUG):
        client.publish(MqttMessage("t", secret_payload))
    assert "RuntimeError" in caplog.text
    assert secret_payload.decode() not in caplog.text


@pytest.mark.parametrize("topic", ["", "a/+/b", "a/#"])
def test_in_memory_refuses_wildcards_in_a_publication(topic: str) -> None:
    client = InMemoryBroker().client()
    client.connect()
    with pytest.raises(ValueError):
        client.publish(MqttMessage(topic))


def test_in_memory_refuses_invalid_qos() -> None:
    client = InMemoryBroker().client()
    client.connect()
    with pytest.raises(ValueError):
        client.publish(MqttMessage("t"), qos=3)
    with pytest.raises(ValueError):
        client.subscribe("t", lambda m: None, qos=-1)


# -- PahoMqttTransport without a broker -----------------------------------------------------------


def _closed_port() -> int:
    """A port of 127.0.0.1 with nothing listening (bound and released)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.parametrize("port", [0, 65536])
def test_paho_refuses_invalid_port(port: int) -> None:
    with pytest.raises(ValueError):
        PahoMqttTransport("127.0.0.1", port, "u", "p")


def test_paho_refuses_non_positive_timeouts() -> None:
    with pytest.raises(ValueError):
        PahoMqttTransport("127.0.0.1", 1883, "u", "p", connect_timeout_s=0)
    with pytest.raises(ValueError):
        PahoMqttTransport("127.0.0.1", 1883, "u", "p", publish_timeout_s=-1)


def test_paho_uses_mqtt5_and_credentials() -> None:
    password = "pw-" + "q" * 10
    transport = PahoMqttTransport("127.0.0.1", 1883, "edge", password, client_id="cid")
    client = transport._client
    assert client.protocol == paho.MQTTv5
    assert client._username == b"edge"
    assert client._password == password.encode()
    assert client._client_id == b"cid"


def test_paho_without_username_sends_no_credentials() -> None:
    transport = PahoMqttTransport("127.0.0.1", 1883, None, None)
    assert transport._client._username is None


def test_paho_connect_to_a_closed_port_fails_in_time() -> None:
    transport = PahoMqttTransport("127.0.0.1", _closed_port(), "u", "p", connect_timeout_s=0.5)
    start = time.monotonic()
    try:
        with pytest.raises(MqttTransportError, match="not reachable"):
            transport.connect()
        assert time.monotonic() - start < 3
        with pytest.raises(MqttTransportError, match="not connected"):
            transport.publish(MqttMessage("t"))
    finally:
        transport.disconnect()
    with pytest.raises(MqttTransportError, match="closed"):
        transport.connect()
    with pytest.raises(MqttTransportError, match="closed"):
        transport.publish(MqttMessage("t"))
    transport.disconnect()  # idempotent


def test_paho_publish_validates_topic_and_qos() -> None:
    transport = PahoMqttTransport("127.0.0.1", 1883, "u", "p")
    with pytest.raises(ValueError):
        transport.publish(MqttMessage("a/#"))
    with pytest.raises(ValueError):
        transport.publish(MqttMessage("a"), qos=5)


class _Reason:
    def __init__(self, failure: bool, name: str) -> None:
        self.is_failure = failure
        self._name = name

    def __str__(self) -> str:
        return self._name


def test_paho_on_connect_sends_every_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = PahoMqttTransport("127.0.0.1", 1883, "u", "p")
    sent: list[tuple[str, int]] = []
    monkeypatch.setattr(transport._client, "subscribe", lambda t, qos: sent.append((t, qos)))
    transport.subscribe("a/b", lambda m: None)
    assert sent == []  # not connected yet: sent on the CONNACK
    transport._on_connect(transport._client, None, None, _Reason(False, "Success"), None)
    assert sent == [("a/b", 1)]
    assert transport._connected.is_set()
    transport.subscribe("c/d", lambda m: None, qos=0)
    assert sent[-1] == ("c/d", 0)  # connected: sent at once
    transport._on_disconnect(transport._client, None, None, _Reason(False, "x"), None)
    assert not transport._connected.is_set()
    transport._on_connect(transport._client, None, None, _Reason(False, "Success"), None)
    assert sent[-2:] == [("a/b", 1), ("c/d", 0)]  # restored after a reconnection


def test_paho_refused_connack_names_only_the_reason(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    password = "pw-" + "r" * 12
    transport = PahoMqttTransport("127.0.0.1", 1883, "u", password, connect_timeout_s=0.2)
    # No network: the CONNACK refusal is delivered by hand.
    monkeypatch.setattr(transport._client, "connect_async", lambda *a, **k: None)
    monkeypatch.setattr(transport._client, "loop_start", lambda: None)
    monkeypatch.setattr(transport._client, "loop_stop", lambda: None)
    monkeypatch.setattr(transport._client, "disconnect", lambda: None)
    reason = ReasonCode(PacketTypes.CONNACK, "Not authorized")
    with caplog.at_level(logging.DEBUG):
        transport._on_connect(transport._client, None, None, reason, None)
    assert not transport._connected.is_set()
    try:
        with pytest.raises(MqttTransportError, match=r"refused the connection \(Not authorized"):
            transport.connect()
    finally:
        transport.disconnect()
    assert password not in caplog.text


def test_paho_message_conversion() -> None:
    raw = paho.MQTTMessage(topic=b"partqc/v1/edge-01/reply/s")
    raw.payload = b"{}"
    properties = Properties(PacketTypes.PUBLISH)
    properties.ResponseTopic = "partqc/v1/edge-01/reply/s"
    properties.CorrelationData = b"\x02" * 16
    properties.UserProperty = [("result", "ok")]
    raw.properties = properties
    message = mqtt_transport._from_paho(raw)
    assert message == MqttMessage(
        "partqc/v1/edge-01/reply/s",
        b"{}",
        response_topic="partqc/v1/edge-01/reply/s",
        correlation_data=b"\x02" * 16,
        user_properties=(("result", "ok"),),
    )
    bare = paho.MQTTMessage(topic=b"t")
    bare.payload = b"x"
    assert mqtt_transport._from_paho(bare) == MqttMessage("t", b"x")


def test_paho_properties_conversion() -> None:
    assert mqtt_transport._properties(MqttMessage("t")) is None
    properties = mqtt_transport._properties(
        MqttMessage(
            "t", response_topic="r", correlation_data=b"c", user_properties=(("result", "ok"),)
        )
    )
    assert properties is not None
    assert properties.ResponseTopic == "r"
    assert properties.CorrelationData == b"c"
    assert properties.UserProperty == [("result", "ok")]


def test_paho_handlers_run_in_the_dispatcher_thread() -> None:
    transport = PahoMqttTransport("127.0.0.1", _closed_port(), "u", "p", connect_timeout_s=0.2)
    seen: list[tuple[str, str]] = []
    done = threading.Event()

    def handler(message: MqttMessage) -> None:
        seen.append((message.topic, threading.current_thread().name))
        done.set()

    transport.subscribe("a/+", handler)
    transport.subscribe("other", lambda m: seen.append(("wrong", "")))
    with pytest.raises(MqttTransportError):
        transport.connect()  # starts the dispatcher (and paho, which keeps retrying)
    try:
        raw = paho.MQTTMessage(topic=b"a/b")
        raw.payload = b""
        transport._on_message(transport._client, None, raw)
        assert done.wait(5)
        assert seen == [("a/b", "qc-edge-mqtt-dispatch")]
    finally:
        transport.disconnect()


def test_paho_full_inbound_queue_drops_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(mqtt_transport, "MAX_PENDING_INBOUND", 1)
    transport = PahoMqttTransport("127.0.0.1", 1883, "u", "p")  # dispatcher not started
    raw = paho.MQTTMessage(topic=b"a/b")
    raw.payload = b"secret-payload"
    with caplog.at_level(logging.WARNING):
        transport._on_message(transport._client, None, raw)
        transport._on_message(transport._client, None, raw)
    assert "dropped" in caplog.text
    assert "secret-payload" not in caplog.text


# -- real broker (mqtt marker) ---------------------------------------------------------------


@pytest.mark.mqtt
def test_real_broker_round_trip_with_properties(mosquitto_broker: types.SimpleNamespace) -> None:
    b = mosquitto_broker
    sender = PahoMqttTransport(b.host, b.port, b.username, b.password)
    receiver = PahoMqttTransport(b.host, b.port, b.username, b.password)
    received: list[MqttMessage] = []
    done = threading.Event()

    def handler(message: MqttMessage) -> None:
        received.append(message)
        done.set()

    receiver.subscribe("partqc/v1/edge-01/batch", handler)
    try:
        receiver.connect()
        sender.connect()
        time.sleep(0.2)  # the SUBSCRIBE of the receiver reaches the broker
        message = MqttMessage(
            "partqc/v1/edge-01/batch",
            b"{}",
            response_topic="partqc/v1/edge-01/reply/s",
            correlation_data=b"\x03" * 16,
            user_properties=(("result", "ok"),),
        )
        sender.publish(message)  # returns after the PUBACK
        assert done.wait(5)
        assert received == [message]
    finally:
        sender.disconnect()
        receiver.disconnect()


@pytest.mark.mqtt
def test_real_broker_refuses_a_client_without_password(
    mosquitto_broker: types.SimpleNamespace,
) -> None:
    b = mosquitto_broker
    anonymous = PahoMqttTransport(b.host, b.port, None, None, connect_timeout_s=2)
    wrong = PahoMqttTransport(b.host, b.port, b.username, "wrong", connect_timeout_s=2)
    try:
        with pytest.raises(MqttTransportError, match="refused the connection"):
            anonymous.connect()
        with pytest.raises(MqttTransportError, match="refused the connection"):
            wrong.connect()
    finally:
        anonymous.disconnect()
        wrong.disconnect()
