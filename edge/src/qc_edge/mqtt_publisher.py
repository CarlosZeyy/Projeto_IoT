"""``MqttPublisher``: the ``Publisher`` of SPEC-009 over MQTT 5 (SPEC-020 sections 4.1 and 4.3).

Request and response with the MQTT 5 properties, QoS 1:

* ``partqc/v1/<device_id>/batch``: the ``qc_contracts.BatchCreate`` JSON (1 to 100 items);
* ``partqc/v1/<device_id>/health``: empty payload;
* both carry ``ResponseTopic`` = ``partqc/v1/<device_id>/reply/<session>`` and a
  ``CorrelationData`` of 16 random bytes. ``<session>`` is random per publisher, so a late answer
  meant for an earlier start of ``qc-edge`` never reaches this one.

The bridge (``qc_edge.mqtt_bridge``) answers on the ``ResponseTopic`` with the same
``CorrelationData`` and the user property ``result``:

* ``ok``: the ``BatchResult`` JSON (empty for ``health``). It must have the ids of the batch in
  the same order (``qc_edge.publisher.parse_batch_results``), else ``PublishTransientError``;
* ``rejected``: ``PublishRejectedError(detail=<payload>)``, the refusal summary of SPEC-009 section
  4.2 (``HTTP <status>: ...``); control characters become ``?`` and the text is cut;
* ``auth``: ``PublishAuthError``;
* ``transient``, any other value, a malformed answer, no answer within ``response_timeout_s``,
  the broker down or a disconnection: ``PublishTransientError``.

The PUBACK of QoS 1 only confirms the broker and never marks an item as sent: only an ``ok``
answer of the bridge, which exists only after the answer of the API, does (SPEC-020 section 4.3).
Answers with an unknown ``CorrelationData`` are discarded. Nothing here logs a payload, and the
error messages are fixed texts (R-03). No payload carries an image (R-02).
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
import time
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

from qc_contracts import DEVICE_ID_PATTERN, MAX_BATCH_SIZE, BatchCreate, InspectionCreate
from qc_edge.mqtt_transport import MqttMessage, MqttTransport, MqttTransportError
from qc_edge.publisher import (
    PublishAuthError,
    PublishRejectedError,
    PublishResult,
    PublishTransientError,
    parse_batch_results,
)

logger = logging.getLogger("qc_edge.mqtt")

TOPIC_PREFIX = "partqc/v1"
QOS = 1
CORRELATION_BYTES = 16
DEFAULT_RESPONSE_TIMEOUT_S = 15.0
RESULT_PROPERTY = "result"
RESULT_OK = "ok"
RESULT_REJECTED = "rejected"
RESULT_AUTH = "auth"
RESULT_TRANSIENT = "transient"
RESULTS = frozenset({RESULT_OK, RESULT_REJECTED, RESULT_AUTH, RESULT_TRANSIENT})
# A refusal summary is "HTTP <status>: " plus at most 200 characters (SPEC-009 section 4.2).
MAX_REJECTED_DETAIL_CHARS = 240


def batch_topic(device_id: str) -> str:
    return f"{TOPIC_PREFIX}/{device_id}/batch"


def health_topic(device_id: str) -> str:
    return f"{TOPIC_PREFIX}/{device_id}/health"


def reply_topic_prefix(device_id: str) -> str:
    """``partqc/v1/<device_id>/reply/``; the session id follows."""
    return f"{TOPIC_PREFIX}/{device_id}/reply/"


def rejected_detail(payload: bytes) -> str:
    """The payload of a ``rejected`` answer as one cut line of text (never more than a summary)."""
    text = payload.decode("utf-8", errors="replace")[:MAX_REJECTED_DETAIL_CHARS]
    clean = "".join("?" if unicodedata.category(char) == "Cc" else char for char in text)
    return clean or "rejected by the bridge"


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    answer: MqttMessage | None = None


class MqttPublisher:
    """``Publisher`` (SPEC-009 section 4.2) over an ``MqttTransport`` (SPEC-020 section 4.3).

    The transport is connected and the reply topic subscribed on the first call (and again after
    a failed connection), never in the constructor, so ``qc-edge`` starts with the broker down.

    Raises:
        ValueError: ``device_id`` outside ``DEVICE_ID_PATTERN`` or ``response_timeout_s`` not
            positive.
    """

    def __init__(
        self,
        transport: MqttTransport,
        device_id: str,
        response_timeout_s: float = DEFAULT_RESPONSE_TIMEOUT_S,
    ) -> None:
        if re.fullmatch(DEVICE_ID_PATTERN, device_id) is None:
            raise ValueError("device_id must match DEVICE_ID_PATTERN")
        if not response_timeout_s > 0:
            raise ValueError("response_timeout_s must be > 0")
        self._transport = transport
        self._device_id = device_id
        self._response_timeout_s = response_timeout_s
        self._session_id = secrets.token_hex(8)
        self._reply_topic = reply_topic_prefix(device_id) + self._session_id
        self._lock = threading.Lock()
        self._pending: dict[bytes, _Pending] = {}
        self._subscribed = False

    @property
    def reply_topic(self) -> str:
        """``partqc/v1/<device_id>/reply/<session id>``."""
        return self._reply_topic

    # -- Publisher ---------------------------------------------------------------------------

    def publish_batch(self, items: Sequence[InspectionCreate]) -> list[PublishResult]:
        """Publish ``items`` (1 to 100) as one ``BatchCreate`` and wait for the bridge.

        Raises:
            ValueError: no items or more than 100.
            PublishTransientError, PublishAuthError, PublishRejectedError: see the module.
        """
        if not 1 <= len(items) <= MAX_BATCH_SIZE:
            raise ValueError(f"a batch has 1 to {MAX_BATCH_SIZE} items, got {len(items)}")
        body = BatchCreate(items=list(items)).model_dump_json().encode("utf-8")
        answer = self._request(batch_topic(self._device_id), body)
        result = answer.user_property(RESULT_PROPERTY)
        if result == RESULT_OK:
            return parse_batch_results(answer.payload, items)
        if result == RESULT_REJECTED:
            raise PublishRejectedError(rejected_detail(answer.payload))
        if result == RESULT_AUTH:
            raise PublishAuthError("refused by the cloud, via the mqtt bridge")
        if result == RESULT_TRANSIENT:
            raise PublishTransientError("mqtt bridge answered transient")
        raise PublishTransientError("malformed answer from the mqtt bridge")

    def check_health(self) -> bool:
        """``True`` only with an ``ok`` answer of the bridge to ``health`` within the timeout."""
        try:
            answer = self._request(health_topic(self._device_id), b"")
        except PublishTransientError as exc:
            logger.info("cloud health check over mqtt failed: %s", exc)
            return False
        return answer.user_property(RESULT_PROPERTY) == RESULT_OK

    def close(self) -> None:
        self._transport.disconnect()

    # -- request / response ------------------------------------------------------------------

    def _ensure_ready(self) -> None:
        if not self._subscribed:
            self._transport.subscribe(self._reply_topic, self._on_answer, qos=QOS)
            self._subscribed = True
        self._transport.connect()

    def _request(self, topic: str, payload: bytes) -> MqttMessage:
        """Publish a request and return the answer with the same ``CorrelationData``.

        Raises:
            PublishTransientError: broker down, no PUBACK, or no answer within the timeout.
        """
        deadline = time.monotonic() + self._response_timeout_s
        correlation = secrets.token_bytes(CORRELATION_BYTES)
        pending = _Pending()
        with self._lock:
            self._pending[correlation] = pending
        try:
            try:
                self._ensure_ready()
                self._transport.publish(
                    MqttMessage(
                        topic=topic,
                        payload=payload,
                        response_topic=self._reply_topic,
                        correlation_data=correlation,
                    ),
                    qos=QOS,
                    timeout_s=max(deadline - time.monotonic(), 0.0),
                )
            except MqttTransportError as exc:
                raise PublishTransientError(str(exc) or "mqtt broker unavailable") from None
            if not pending.event.wait(max(deadline - time.monotonic(), 0.0)):
                raise PublishTransientError(
                    f"no answer from the mqtt bridge within {self._response_timeout_s:g} s"
                )
        finally:
            with self._lock:
                self._pending.pop(correlation, None)
        answer = pending.answer
        if answer is None:  # pragma: no cover - the event is set only with an answer
            raise PublishTransientError("malformed answer from the mqtt bridge")
        return answer

    def _on_answer(self, message: MqttMessage) -> None:
        correlation = message.correlation_data
        with self._lock:
            pending = self._pending.get(correlation) if correlation is not None else None
            if pending is None or pending.event.is_set():
                pending = None
            else:
                pending.answer = message
                pending.event.set()
        if pending is None:
            logger.debug("mqtt answer with an unknown CorrelationData discarded")
