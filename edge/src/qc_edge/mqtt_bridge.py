"""``python -m qc_edge.mqtt_bridge``: MQTT -> HTTP bridge of the edge (SPEC-020 section 4.4).

The bridge runs on the notebook, next to the local Mosquitto (loopback only, option C of
ADR-009). It subscribes only to ``partqc/v1/<DEVICE_ID>/batch`` and
``partqc/v1/<DEVICE_ID>/health`` (QoS 1) and, for each request:

* ``batch``: validates the payload as ``qc_contracts.BatchCreate`` (invalid -> ``rejected`` with
  ``HTTP 422: invalid batch payload``) and calls ``HttpPublisher.publish_batch`` (``httpx`` stays
  only in ``qc_edge.publisher``, with the limits of SPEC-030). The answer is ``ok`` with the
  ``BatchResult`` JSON, ``rejected`` with the refusal summary of SPEC-009 section 4.2 (never the
  body of the API), ``auth`` or ``transient``, from the exception of the ``HttpPublisher``;
* ``health``: ``HttpPublisher.check_health()`` -> ``ok`` or ``transient`` (empty payload).

The answer goes to the request's ``ResponseTopic`` with its ``CorrelationData`` and the user
property ``result``. A request without ``ResponseTopic`` or ``CorrelationData`` is ignored with a
warning, and so is one whose ``ResponseTopic`` is not a reply topic of this device
(``partqc/v1/<DEVICE_ID>/reply/<session>``, the form of section 4.1), so the bridge never
publishes on another topic.

The bridge keeps no state: if it stops between the API and the answer, the publisher gets no
answer, sends the batch again, and the idempotency by ``inspection_id`` answers ``duplicate``
(R-05). Logs carry only counts, ``result`` and the topic: never a payload, the MQTT password nor
the ``DEVICE_API_KEY`` (R-03).

Configuration, from the process environment (locally,
``uv run --env-file .env --package qc-edge python -m qc_edge.mqtt_bridge``): ``DEVICE_ID``,
``DEVICE_API_KEY`` and ``CLOUD_API_URL`` (rules of SPEC-009, both required here), ``MQTT_HOST``,
``MQTT_PORT``, ``MQTT_USERNAME`` and ``MQTT_PASSWORD`` (required). Exit codes: 0 after SIGINT or
SIGTERM; 2 for an invalid configuration or command line (the message names the variable or the
option, never a value).
"""

from __future__ import annotations

import logging
import re
import signal
import sys
import threading
from collections.abc import Callable, Sequence
from types import FrameType
from typing import Any

from pydantic import ValidationError

from qc_contracts import BatchCreate, BatchResult, InspectionCreated
from qc_edge.argv import (
    EXIT_USAGE_ERROR,
    ArgumentsError,
    QuietArgumentParser,
    describe_arguments,
    resolve_argv,
)
from qc_edge.config import BridgeSettings, config_error_message, missing_bridge_settings
from qc_edge.mqtt_publisher import (
    QOS,
    RESULT_AUTH,
    RESULT_OK,
    RESULT_PROPERTY,
    RESULT_REJECTED,
    RESULT_TRANSIENT,
    batch_topic,
    health_topic,
    reply_topic_prefix,
)
from qc_edge.mqtt_transport import (
    MqttMessage,
    MqttTransport,
    MqttTransportError,
    PahoMqttTransport,
)
from qc_edge.publisher import (
    HttpPublisher,
    PublishAuthError,
    Publisher,
    PublishRejectedError,
    PublishTransientError,
    check_api_key,
)

logger = logging.getLogger("qc_edge.mqtt_bridge")

EXIT_OK = 0
INVALID_BATCH = "HTTP 422: invalid batch payload"
# The session id of a reply topic (``secrets.token_hex(8)`` in ``MqttPublisher``).
_SESSION_ID = r"[A-Za-z0-9_-]{1,64}"
WAIT_STEP_S = 1.0


class MqttBridge:
    """Answers the ``batch`` and ``health`` requests of ``device_id`` through ``publisher``.

    ``publisher`` is the ``HttpPublisher`` in production (any ``Publisher`` in the tests).
    """

    def __init__(self, transport: MqttTransport, publisher: Publisher, device_id: str) -> None:
        self._transport = transport
        self._publisher = publisher
        self._device_id = device_id
        self._batch_topic = batch_topic(device_id)
        self._health_topic = health_topic(device_id)
        self._reply_pattern = re.compile(re.escape(reply_topic_prefix(device_id)) + _SESSION_ID)

    @property
    def topics(self) -> tuple[str, str]:
        return self._batch_topic, self._health_topic

    def start(self) -> None:
        """Subscribe to the two request topics and connect.

        Raises:
            MqttTransportError: the broker is not reachable now (the real transport keeps
                trying in the background, and the subscriptions are sent when it connects).
        """
        self._transport.subscribe(self._batch_topic, self.handle, qos=QOS)
        self._transport.subscribe(self._health_topic, self.handle, qos=QOS)
        logger.info("mqtt bridge subscribed to %s and %s", *self.topics)
        self._transport.connect()

    def stop(self) -> None:
        self._transport.disconnect()

    def handle(self, message: MqttMessage) -> None:
        """Answer one request (the callback of both subscriptions)."""
        if message.topic not in self.topics:
            return
        if not message.response_topic or not message.correlation_data:
            logger.warning(
                "request without ResponseTopic or CorrelationData ignored (topic %s)",
                message.topic,
            )
            return
        if self._reply_pattern.fullmatch(message.response_topic) is None:
            logger.warning(
                "request with a ResponseTopic outside the reply topics ignored (topic %s)",
                message.topic,
            )
            return
        if message.topic == self._batch_topic:
            result, payload = self._batch(message)
        else:
            result, payload = self._health()
        self._answer(message, result, payload)

    def _batch(self, message: MqttMessage) -> tuple[str, bytes]:
        try:
            batch = BatchCreate.model_validate_json(message.payload)
        except (ValidationError, ValueError):
            logger.info("batch on %s: %s (invalid payload)", message.topic, RESULT_REJECTED)
            return RESULT_REJECTED, INVALID_BATCH.encode("utf-8")
        count = len(batch.items)
        try:
            results = self._publisher.publish_batch(batch.items)
        except PublishRejectedError as exc:
            result, payload = RESULT_REJECTED, exc.detail.encode("utf-8")
        except PublishAuthError:
            result, payload = RESULT_AUTH, b""
        except PublishTransientError:
            result, payload = RESULT_TRANSIENT, b""
        except Exception as exc:
            # Only the class: the message or the traceback could quote a value (R-03).
            logger.error("batch on %s failed unexpectedly (%s)", message.topic, type(exc).__name__)
            result, payload = RESULT_TRANSIENT, b""
        else:
            answer = BatchResult(
                results=[
                    InspectionCreated(inspection_id=r.inspection_id, status=r.status)
                    for r in results
                ]
            )
            result, payload = RESULT_OK, answer.model_dump_json().encode("utf-8")
        logger.info("batch of %d item(s) on %s: %s", count, message.topic, result)
        return result, payload

    def _health(self) -> tuple[str, bytes]:
        try:
            healthy = self._publisher.check_health()
        except Exception as exc:
            logger.error("health check failed unexpectedly (%s)", type(exc).__name__)
            healthy = False
        result = RESULT_OK if healthy else RESULT_TRANSIENT
        logger.info("health on %s: %s", self._health_topic, result)
        return result, b""

    def _answer(self, request: MqttMessage, result: str, payload: bytes) -> None:
        assert request.response_topic is not None
        try:
            self._transport.publish(
                MqttMessage(
                    topic=request.response_topic,
                    payload=payload,
                    correlation_data=request.correlation_data,
                    user_properties=((RESULT_PROPERTY, result),),
                ),
                qos=QOS,
            )
        except MqttTransportError as exc:
            # The publisher times out and sends the request again (R-05).
            logger.warning("answer on %s not published: %s", request.topic, exc)


# -- command line ------------------------------------------------------------------------------

TransportFactory = Callable[[BridgeSettings], MqttTransport]


def _configure_logging() -> None:
    if not logging.getLogger().handlers and not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _paho_transport(settings: BridgeSettings) -> MqttTransport:
    password = settings.MQTT_PASSWORD.get_secret_value() if settings.MQTT_PASSWORD else None
    return PahoMqttTransport(
        settings.MQTT_HOST,
        settings.MQTT_PORT,
        settings.MQTT_USERNAME,
        password,
        client_id=f"partqc-bridge-{settings.DEVICE_ID}",
    )


def _parse_args(argv: Sequence[str] | None) -> bool:
    """``True`` when the command line is valid (the bridge takes no argument)."""
    arguments = resolve_argv(argv)
    parser = QuietArgumentParser(
        prog="python -m qc_edge.mqtt_bridge",
        description="Bridge from the local MQTT broker to the PartQC cloud API (SPEC-020).",
        allow_abbrev=False,
    )
    try:
        _args, unknown = parser.parse_known_args(arguments)
    except ArgumentsError:
        logger.error("invalid command-line argument(s): %s", describe_arguments(arguments))
        return False
    if unknown:
        logger.error("unknown command-line argument(s): %s", describe_arguments(unknown))
        return False
    return True


def main(
    argv: Sequence[str] | None = None,
    *,
    transport_factory: TransportFactory = _paho_transport,
    stop_event: threading.Event | None = None,
) -> int:
    """Entry point; returns the exit code (0 or 2).

    ``transport_factory`` and ``stop_event`` exist for the tests; in production, SIGINT and
    SIGTERM set the stop event.
    """
    _configure_logging()
    if not _parse_args(argv):
        return EXIT_USAGE_ERROR
    try:
        settings = BridgeSettings()
    except ValidationError as exc:
        logger.error("invalid configuration: %s", config_error_message(exc))
        return EXIT_USAGE_ERROR
    missing = missing_bridge_settings(settings)
    if missing:
        logger.error("invalid configuration: %s not set", ", ".join(missing))
        return EXIT_USAGE_ERROR
    assert settings.DEVICE_API_KEY is not None and settings.CLOUD_API_URL is not None
    api_key = settings.DEVICE_API_KEY.get_secret_value()
    try:
        check_api_key(api_key)
    except ValueError as exc:
        logger.error("invalid configuration: DEVICE_API_KEY: %s", exc)
        return EXIT_USAGE_ERROR

    publisher = HttpPublisher(settings.CLOUD_API_URL, api_key)
    bridge = MqttBridge(transport_factory(settings), publisher, settings.DEVICE_ID)
    stop = stop_event if stop_event is not None else threading.Event()
    previous = _install_signal_handlers(stop) if stop_event is None else {}
    try:
        try:
            bridge.start()
        except MqttTransportError as exc:
            logger.warning("%s; retrying in the background", exc)
        logger.info("mqtt bridge running; stop with Ctrl+C")
        while not stop.wait(WAIT_STEP_S):
            pass
    finally:
        bridge.stop()
        publisher.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler if handler is not None else signal.SIG_DFL)
    logger.info("mqtt bridge stopped")
    return EXIT_OK


def _install_signal_handlers(stop: threading.Event) -> dict[int, Any]:
    def _handler(signum: int, frame: FrameType | None) -> None:
        stop.set()

    previous: dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, _handler)
    return previous


if __name__ == "__main__":
    sys.exit(main())
