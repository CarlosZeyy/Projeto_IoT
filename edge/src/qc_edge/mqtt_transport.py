"""MQTT 5 transport of the edge (SPEC-020 section 4.2, option C of ADR-009).

* ``MqttTransport`` (Protocol): connect, publish with properties, subscribe with a callback,
  disconnect. ``MqttPublisher`` and the bridge depend only on it.
* ``PahoMqttTransport``: the real implementation, with ``paho-mqtt`` (``protocol=MQTTv5``,
  user and password). This is the **only** ``qc_edge`` module that imports ``paho``
  (SPEC-020, CA-10).
* ``InMemoryBroker``: a deterministic broker for the tests, without network. Delivery is
  synchronous, in the thread of the publisher, between the clients of the same process;
  ``stop()`` and ``start()`` simulate the broker going down and coming back.

A message is a ``MqttMessage``: topic, payload and the three MQTT 5 properties the project uses
(``ResponseTopic``, ``CorrelationData`` and the user properties). ``publish`` with QoS 1 returns
after the broker's PUBACK, which only confirms the broker: it never means that an inspection
reached the cloud (SPEC-020 section 4.3).

Failures of the broker (not reachable, not connected, refused, no PUBACK in time) raise
``MqttTransportError`` with a fixed text that never carries the password nor a payload (R-03).
``paho`` itself logs nothing: ``enable_logger`` is never called.

Real transport notes:

* ``connect()`` starts the ``paho`` network thread once (``connect_async`` + ``loop_start``) and
  waits for the CONNACK up to ``connect_timeout_s``; the thread keeps reconnecting in the
  background (``reconnect_delay_set(1, 30)``), and every subscription is sent again on each new
  connection (``clean_start=True``).
* ``publish()`` refuses at once when the client is not connected (``paho`` would queue the
  message and send it after a reconnection). A message whose PUBACK did not arrive in time may
  still be sent by ``paho`` after a reconnection; the answer to it is discarded by its unknown
  ``CorrelationData``, and the idempotency by ``inspection_id`` absorbs the repeated batch (R-05).
* The handlers run in a dispatcher thread of the transport, never in the ``paho`` network
  thread, so a handler may call ``publish`` (and wait for its PUBACK) without a deadlock. The
  inbound queue holds at most ``MAX_PENDING_INBOUND`` messages; more are dropped with a warning
  that names only the topic.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import paho.mqtt.client as paho
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

logger = logging.getLogger("qc_edge.mqtt")

DEFAULT_KEEPALIVE_S = 30
DEFAULT_CONNECT_TIMEOUT_S = 5.0
DEFAULT_PUBLISH_TIMEOUT_S = 5.0
RECONNECT_MIN_DELAY_S = 1
RECONNECT_MAX_DELAY_S = 30
MAX_PENDING_INBOUND = 1000
DISPATCHER_JOIN_TIMEOUT_S = 5.0
DISPATCH_POLL_S = 0.5

BROKER_UNREACHABLE = "mqtt broker not reachable"
NOT_CONNECTED = "not connected to the mqtt broker"
NO_PUBACK = "no PUBACK from the mqtt broker in time"
PUBLISH_FAILED = "mqtt publish failed"
TRANSPORT_CLOSED = "mqtt transport closed"


@dataclass(frozen=True)
class MqttMessage:
    """An MQTT 5 message with the properties used by the project (SPEC-020 section 4.1)."""

    topic: str
    payload: bytes = b""
    response_topic: str | None = None
    correlation_data: bytes | None = None
    user_properties: tuple[tuple[str, str], ...] = ()

    def user_property(self, name: str) -> str | None:
        """The first user property called ``name``, or ``None``."""
        for key, value in self.user_properties:
            if key == name:
                return value
        return None


MessageHandler = Callable[[MqttMessage], None]


class MqttTransportError(Exception):
    """The broker is not reachable, refused the client, or did not acknowledge in time."""


class MqttTransport(Protocol):
    def connect(self) -> None:
        """Connect (idempotent). Raises ``MqttTransportError`` when the broker is not reachable."""
        ...

    def publish(self, message: MqttMessage, qos: int = 1, timeout_s: float | None = None) -> None:
        """Publish ``message``; with QoS 1, return after the PUBACK (at most ``timeout_s``).

        Raises ``MqttTransportError`` when not connected or without the PUBACK in time.
        """
        ...

    def subscribe(self, topic_filter: str, handler: MessageHandler, qos: int = 1) -> None:
        """Deliver every message matching ``topic_filter`` to ``handler``.

        May be called before ``connect``; the subscription survives reconnections.
        """
        ...

    def disconnect(self) -> None:
        """Disconnect and drop the subscriptions of this client."""
        ...


def topic_matches(topic_filter: str, topic: str) -> bool:
    """``True`` when ``topic`` matches ``topic_filter`` (MQTT wildcards ``+`` and ``#``)."""
    return paho.topic_matches_sub(topic_filter, topic)


def _check_topic(topic: str) -> None:
    if not topic or "+" in topic or "#" in topic or "\x00" in topic:
        raise ValueError("invalid topic for a publication")


def _check_qos(qos: int) -> None:
    if qos not in (0, 1, 2):
        raise ValueError("qos must be 0, 1 or 2")


def _run_handler(handler: MessageHandler, message: MqttMessage) -> None:
    """Call ``handler``; an exception is logged by its class only (never the payload)."""
    try:
        handler(message)
    except Exception as exc:
        logger.error("mqtt handler failed on %s (%s)", message.topic, type(exc).__name__)


# -- real transport ---------------------------------------------------------------------------


class PahoMqttTransport:
    """``MqttTransport`` over ``paho-mqtt`` 2.x, MQTT 5, user and password (SPEC-020 §4.2).

    ``username`` ``None`` sends no credentials (only useful to show that the broker refuses an
    anonymous client). The password is kept only inside the ``paho`` client.

    Raises:
        ValueError: ``port`` outside 1..65535 or a timeout that is not positive.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        *,
        client_id: str | None = None,
        keepalive_s: int = DEFAULT_KEEPALIVE_S,
        connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
        publish_timeout_s: float = DEFAULT_PUBLISH_TIMEOUT_S,
    ) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("port must be from 1 to 65535")
        if not connect_timeout_s > 0 or not publish_timeout_s > 0:
            raise ValueError("timeouts must be > 0")
        self._host = host
        self._port = port
        self._keepalive_s = keepalive_s
        self._connect_timeout_s = connect_timeout_s
        self._publish_timeout_s = publish_timeout_s
        self._lock = threading.Lock()
        self._subscriptions: list[tuple[str, MessageHandler, int]] = []
        self._connected = threading.Event()
        # True from the CONNACK to the disconnection, under ``_lock``: a subscription made
        # meanwhile is sent at once, one made before is sent by ``_on_connect``.
        self._session = False
        self._started = False
        self._closed = False
        self._connect_error = BROKER_UNREACHABLE
        self._inbound: queue.Queue[MqttMessage | None] = queue.Queue(MAX_PENDING_INBOUND)
        self._dispatcher: threading.Thread | None = None

        identifier = client_id or f"partqc-{secrets.token_hex(6)}"
        self._client = paho.Client(
            callback_api_version=paho.CallbackAPIVersion.VERSION2,
            client_id=identifier,
            protocol=paho.MQTTv5,
        )
        if username is not None:
            self._client.username_pw_set(username, password)
        self._client.reconnect_delay_set(RECONNECT_MIN_DELAY_S, RECONNECT_MAX_DELAY_S)
        self._client.on_connect = self._on_connect
        self._client.on_connect_fail = self._on_connect_fail
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # -- MqttTransport ---------------------------------------------------------------------

    def connect(self) -> None:
        with self._lock:
            if self._closed:
                raise MqttTransportError(TRANSPORT_CLOSED)
            if not self._started:
                self._dispatcher = threading.Thread(
                    target=self._dispatch, name="qc-edge-mqtt-dispatch", daemon=True
                )
                self._dispatcher.start()
                self._client.connect_async(
                    self._host, self._port, keepalive=self._keepalive_s, clean_start=True
                )
                self._client.loop_start()
                self._started = True
        if not self._connected.wait(self._connect_timeout_s):
            raise MqttTransportError(self._connect_error)

    def publish(self, message: MqttMessage, qos: int = 1, timeout_s: float | None = None) -> None:
        _check_topic(message.topic)
        _check_qos(qos)
        if self._closed:
            raise MqttTransportError(TRANSPORT_CLOSED)
        if not self._connected.is_set() or not self._client.is_connected():
            raise MqttTransportError(NOT_CONNECTED)
        try:
            info = self._client.publish(
                message.topic, message.payload, qos=qos, properties=_properties(message)
            )
        except ValueError:
            raise MqttTransportError(PUBLISH_FAILED) from None
        if info.rc != paho.MQTT_ERR_SUCCESS:
            raise MqttTransportError(f"{PUBLISH_FAILED} ({paho.error_string(info.rc)})")
        if qos == 0:
            return
        wait_s = self._publish_timeout_s if timeout_s is None else max(timeout_s, 0.0)
        try:
            info.wait_for_publish(wait_s)
            published = info.is_published()
        except (ValueError, RuntimeError):
            raise MqttTransportError(PUBLISH_FAILED) from None
        if not published:
            raise MqttTransportError(NO_PUBACK)

    def subscribe(self, topic_filter: str, handler: MessageHandler, qos: int = 1) -> None:
        _check_qos(qos)
        with self._lock:
            self._subscriptions.append((topic_filter, handler, qos))
            send_now = self._session
        if send_now:
            self._client.subscribe(topic_filter, qos=qos)

    def disconnect(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._session = False
            started = self._started
            self._subscriptions.clear()
        self._connected.clear()
        if started:
            self._client.disconnect()
            self._client.loop_stop()
        with contextlib.suppress(queue.Full):  # a full queue: the dispatcher sees _closed
            self._inbound.put_nowait(None)
        dispatcher = self._dispatcher
        if dispatcher is not None:
            dispatcher.join(DISPATCHER_JOIN_TIMEOUT_S)

    # -- paho callbacks (network thread) -----------------------------------------------------

    def _on_connect(
        self, client: paho.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any
    ) -> None:
        if reason_code.is_failure:
            # Only the reason name (e.g. "Not authorized"): never the user or the password.
            self._connect_error = f"mqtt broker refused the connection ({reason_code})"
            logger.warning("%s", self._connect_error)
            return
        with self._lock:
            subscriptions = list(self._subscriptions)
            self._session = True
        # The SUBSCRIBE packets go out before any publication of this connection.
        for topic_filter, _handler, qos in subscriptions:
            client.subscribe(topic_filter, qos=qos)
        self._connect_error = BROKER_UNREACHABLE
        self._connected.set()

    def _on_connect_fail(self, client: paho.Client, userdata: Any) -> None:
        self._connect_error = BROKER_UNREACHABLE

    def _on_disconnect(
        self, client: paho.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any
    ) -> None:
        with self._lock:
            self._session = False
        self._connected.clear()

    def _on_message(self, client: paho.Client, userdata: Any, raw: paho.MQTTMessage) -> None:
        message = _from_paho(raw)
        try:
            self._inbound.put_nowait(message)
        except queue.Full:
            logger.warning("mqtt inbound queue full: message on %s dropped", message.topic)

    # -- dispatcher thread -------------------------------------------------------------------

    def _dispatch(self) -> None:
        while not self._closed:
            try:
                message = self._inbound.get(timeout=DISPATCH_POLL_S)
            except queue.Empty:
                continue
            if message is None:
                return
            with self._lock:
                handlers = [
                    handler
                    for topic_filter, handler, _qos in self._subscriptions
                    if topic_matches(topic_filter, message.topic)
                ]
            for handler in handlers:
                _run_handler(handler, message)


def _properties(message: MqttMessage) -> Properties | None:
    if (
        message.response_topic is None
        and message.correlation_data is None
        and not message.user_properties
    ):
        return None
    properties = Properties(PacketTypes.PUBLISH)
    if message.response_topic is not None:
        properties.ResponseTopic = message.response_topic
    if message.correlation_data is not None:
        properties.CorrelationData = message.correlation_data
    if message.user_properties:
        properties.UserProperty = list(message.user_properties)
    return properties


def _from_paho(raw: paho.MQTTMessage) -> MqttMessage:
    properties = getattr(raw, "properties", None)
    response_topic = getattr(properties, "ResponseTopic", None)
    correlation = getattr(properties, "CorrelationData", None)
    user = getattr(properties, "UserProperty", None) or []
    return MqttMessage(
        topic=raw.topic,
        payload=bytes(raw.payload),
        response_topic=response_topic if isinstance(response_topic, str) else None,
        correlation_data=bytes(correlation) if isinstance(correlation, bytes | bytearray) else None,
        user_properties=tuple((str(key), str(value)) for key, value in user),
    )


# -- in-memory broker (tests only) ------------------------------------------------------------


class InMemoryBroker:
    """Deterministic broker for the tests (SPEC-020 section 4.2); no network, no thread.

    * ``client(client_id)`` returns an ``InMemoryTransport`` bound to this broker;
    * a publication is delivered synchronously, in the publisher's thread, to every connected
      client with a matching subscription (the publisher included, as in MQTT);
    * ``stop()``: ``connect`` and ``publish`` raise ``MqttTransportError``; ``start()``: the
      clients that were connected are connected again, with their subscriptions (as the real
      transport does when it reconnects);
    * ``published``: every publication acknowledged by the broker (PUBACK with QoS 1), in order;
    * ``intercept``: optional ``(message) -> bool``; ``False`` acknowledges the publication but
      does not deliver it (a message lost after the broker, for the tests).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._running = True
        self._subscriptions: list[tuple[InMemoryTransport, str, MessageHandler]] = []
        self.published: list[MqttMessage] = []
        self.intercept: Callable[[MqttMessage], bool] | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def client(self, client_id: str = "") -> InMemoryTransport:
        return InMemoryTransport(self, client_id or f"client-{secrets.token_hex(4)}")

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def start(self) -> None:
        with self._lock:
            self._running = True

    def published_on(self, topic_filter: str) -> list[MqttMessage]:
        """The acknowledged publications whose topic matches ``topic_filter``."""
        with self._lock:
            return [m for m in self.published if topic_matches(topic_filter, m.topic)]

    def _subscribe(self, client: InMemoryTransport, topic_filter: str, handler: Any) -> None:
        with self._lock:
            self._subscriptions.append((client, topic_filter, handler))

    def _forget(self, client: InMemoryTransport) -> None:
        with self._lock:
            self._subscriptions = [s for s in self._subscriptions if s[0] is not client]

    def _publish(self, message: MqttMessage) -> None:
        with self._lock:
            if not self._running:
                raise MqttTransportError(BROKER_UNREACHABLE)
            self.published.append(message)
            intercept = self.intercept
            targets = [
                handler
                for client, topic_filter, handler in self._subscriptions
                if client.connected and topic_matches(topic_filter, message.topic)
            ]
        if intercept is not None and not intercept(message):
            return
        for handler in targets:
            _run_handler(handler, message)


class InMemoryTransport:
    """``MqttTransport`` of an ``InMemoryBroker`` client. ``pubacks`` counts the QoS >= 1 acks."""

    def __init__(self, broker: InMemoryBroker, client_id: str) -> None:
        self.broker = broker
        self.client_id = client_id
        self.pubacks = 0
        self._connected = False

    @property
    def connected(self) -> bool:
        """Connected and the broker running."""
        return self._connected and self.broker.running

    def connect(self) -> None:
        if not self.broker.running:
            raise MqttTransportError(BROKER_UNREACHABLE)
        self._connected = True

    def publish(self, message: MqttMessage, qos: int = 1, timeout_s: float | None = None) -> None:
        _check_topic(message.topic)
        _check_qos(qos)
        if not self._connected:
            raise MqttTransportError(NOT_CONNECTED)
        self.broker._publish(message)
        if qos >= 1:
            self.pubacks += 1

    def subscribe(self, topic_filter: str, handler: MessageHandler, qos: int = 1) -> None:
        _check_qos(qos)
        self.broker._subscribe(self, topic_filter, handler)

    def disconnect(self) -> None:
        self._connected = False
        self.broker._forget(self)
