"""``MqttPublisher`` (SPEC-020 sections 4.1 and 4.3) over the ``InMemoryBroker``.

A hand-made responder plays the bridge, so each ``result``, the correlation, the timeout and the
malformed answers are tested without the real bridge (``test_mqtt_bridge.py`` covers the two
together, with the ``PublishLoop``).
"""

from __future__ import annotations

import json
import logging
import re
import time
import types
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest

from qc_contracts import BatchCreate, InspectionCreate
from qc_edge.mqtt_publisher import (
    CORRELATION_BYTES,
    MqttPublisher,
    batch_topic,
    health_topic,
    rejected_detail,
)
from qc_edge.mqtt_transport import (
    InMemoryBroker,
    InMemoryTransport,
    MqttMessage,
    MqttTransportError,
)
from qc_edge.publisher import (
    PublishAuthError,
    PublishRejectedError,
    PublishResult,
    PublishTransientError,
)

DEVICE = "edge-01"
Answer = Callable[[MqttMessage], list[MqttMessage]]


class Responder:
    """Plays the bridge: ``answer(request)`` returns the messages to publish back."""

    def __init__(self, broker: InMemoryBroker, answer: Answer) -> None:
        self.requests: list[MqttMessage] = []
        self.answer = answer
        self.transport = broker.client("responder")
        self.transport.subscribe(batch_topic(DEVICE), self._handle)
        self.transport.subscribe(health_topic(DEVICE), self._handle)
        self.transport.connect()

    def _handle(self, request: MqttMessage) -> None:
        self.requests.append(request)
        for message in self.answer(request):
            self.transport.publish(message)


def reply(
    request: MqttMessage,
    result: str | None,
    payload: bytes = b"",
    correlation: bytes | None = None,
) -> MqttMessage:
    assert request.response_topic is not None
    props = () if result is None else (("result", result),)
    return MqttMessage(
        request.response_topic,
        payload,
        correlation_data=request.correlation_data if correlation is None else correlation,
        user_properties=props,
    )


def ok_results(request: MqttMessage, status: str = "created") -> bytes:
    items = json.loads(request.payload)["items"]
    return json.dumps(
        {"results": [{"inspection_id": i["inspection_id"], "status": status} for i in items]}
    ).encode()


@pytest.fixture
def broker() -> InMemoryBroker:
    return InMemoryBroker()


@pytest.fixture
def transport(broker: InMemoryBroker) -> InMemoryTransport:
    return broker.client("edge")


def make_items(fake_cloud: types.ModuleType, n: int) -> list[InspectionCreate]:
    return [fake_cloud.make_inspection() for _ in range(n)]


# -- constructor and topics ----------------------------------------------------------------------


def test_topics() -> None:
    assert batch_topic("edge-01") == "partqc/v1/edge-01/batch"
    assert health_topic("edge-01") == "partqc/v1/edge-01/health"


@pytest.mark.parametrize("device_id", ["Edge", "a/b", "ed+", "e#1", "x", ""])
def test_invalid_device_id(transport: InMemoryTransport, device_id: str) -> None:
    with pytest.raises(ValueError):
        MqttPublisher(transport, device_id)


@pytest.mark.parametrize("timeout", [0, -1.0])
def test_invalid_timeout(transport: InMemoryTransport, timeout: float) -> None:
    with pytest.raises(ValueError):
        MqttPublisher(transport, DEVICE, timeout)


def test_reply_topic_has_a_random_session(transport: InMemoryTransport) -> None:
    first = MqttPublisher(transport, DEVICE)
    second = MqttPublisher(transport, DEVICE)
    assert re.fullmatch(r"partqc/v1/edge-01/reply/[0-9a-f]{16}", first.reply_topic)
    assert first.reply_topic != second.reply_topic


@pytest.mark.parametrize("n", [0, 101])
def test_batch_size_is_checked(
    transport: InMemoryTransport, fake_cloud: types.ModuleType, n: int
) -> None:
    publisher = MqttPublisher(transport, DEVICE)
    with pytest.raises(ValueError):
        publisher.publish_batch(make_items(fake_cloud, n))


# -- publish_batch -------------------------------------------------------------------------------


def test_ok_returns_the_results_and_the_request_is_a_batch_create(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    responder = Responder(broker, lambda r: [reply(r, "ok", ok_results(r, "duplicate"))])
    publisher = MqttPublisher(transport, DEVICE)
    items = make_items(fake_cloud, 3)
    results = publisher.publish_batch(items)
    assert results == [PublishResult(i.inspection_id, "duplicate") for i in items]
    (request,) = responder.requests
    assert request.topic == "partqc/v1/edge-01/batch"
    assert request.response_topic == publisher.reply_topic
    assert request.correlation_data is not None
    assert len(request.correlation_data) == CORRELATION_BYTES
    batch = BatchCreate.model_validate_json(request.payload)
    assert [i.inspection_id for i in batch.items] == [i.inspection_id for i in items]
    assert transport.pubacks == 1


def test_each_request_has_a_new_correlation(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    responder = Responder(broker, lambda r: [reply(r, "ok", ok_results(r))])
    publisher = MqttPublisher(transport, DEVICE)
    publisher.publish_batch(make_items(fake_cloud, 1))
    publisher.publish_batch(make_items(fake_cloud, 1))
    first, second = (r.correlation_data for r in responder.requests)
    assert first != second


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"results": []}',
        b"",
    ],
)
def test_malformed_ok_is_transient(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType, payload
) -> None:
    Responder(broker, lambda r: [reply(r, "ok", payload)])
    with pytest.raises(PublishTransientError):
        MqttPublisher(transport, DEVICE).publish_batch(make_items(fake_cloud, 2))


def test_ok_with_other_ids_is_transient(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    other = json.dumps({"results": [{"inspection_id": str(uuid4()), "status": "created"}]})
    Responder(broker, lambda r: [reply(r, "ok", other.encode())])
    with pytest.raises(PublishTransientError, match="does not match"):
        MqttPublisher(transport, DEVICE).publish_batch(make_items(fake_cloud, 1))


def test_ok_in_another_order_is_transient(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    def reversed_ok(r: MqttMessage) -> list[MqttMessage]:
        body = json.loads(ok_results(r))
        body["results"].reverse()
        return [reply(r, "ok", json.dumps(body).encode())]

    Responder(broker, reversed_ok)
    with pytest.raises(PublishTransientError):
        MqttPublisher(transport, DEVICE).publish_batch(make_items(fake_cloud, 2))


def test_rejected_carries_the_summary(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    Responder(broker, lambda r: [reply(r, "rejected", b"HTTP 422: Value cannot be stored")])
    with pytest.raises(PublishRejectedError) as excinfo:
        MqttPublisher(transport, DEVICE).publish_batch(make_items(fake_cloud, 1))
    assert excinfo.value.detail == "HTTP 422: Value cannot be stored"


def test_rejected_detail_is_one_cut_line() -> None:
    assert rejected_detail(b"HTTP 422: a\nb\x00c") == "HTTP 422: a?b?c"
    assert len(rejected_detail(b"x" * 10_000)) == 240
    assert rejected_detail(b"\xff") == "�"
    assert rejected_detail(b"") == "rejected by the bridge"


def test_auth(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    Responder(broker, lambda r: [reply(r, "auth")])
    with pytest.raises(PublishAuthError):
        MqttPublisher(transport, DEVICE).publish_batch(make_items(fake_cloud, 1))


@pytest.mark.parametrize("result", ["transient", "weird", None])
def test_transient_or_unknown_result(
    broker: InMemoryBroker,
    transport: InMemoryTransport,
    fake_cloud: types.ModuleType,
    result: str | None,
) -> None:
    Responder(broker, lambda r: [reply(r, result)])
    with pytest.raises(PublishTransientError):
        MqttPublisher(transport, DEVICE).publish_batch(make_items(fake_cloud, 1))


def test_no_bridge_times_out_after_the_puback(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    publisher = MqttPublisher(transport, DEVICE, response_timeout_s=0.2)
    start = time.monotonic()
    with pytest.raises(PublishTransientError, match="no answer from the mqtt bridge"):
        publisher.publish_batch(make_items(fake_cloud, 3))
    elapsed = time.monotonic() - start
    assert 0.15 <= elapsed < 2
    assert transport.pubacks == 1  # the broker acknowledged; nothing was confirmed
    assert len(broker.published_on("partqc/v1/edge-01/batch")) == 1


def test_unknown_correlation_is_discarded(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    def answers(r: MqttMessage) -> list[MqttMessage]:
        stray = reply(r, "rejected", b"HTTP 422: stray", correlation=b"\x09" * 16)
        return [stray, reply(r, "ok", ok_results(r))]

    Responder(broker, answers)
    results = MqttPublisher(transport, DEVICE).publish_batch(make_items(fake_cloud, 1))
    assert results[0].status == "created"


def test_answer_without_correlation_is_discarded(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    def answers(r: MqttMessage) -> list[MqttMessage]:
        bare = MqttMessage(r.response_topic or "", b"", user_properties=(("result", "auth"),))
        return [bare]

    Responder(broker, answers)
    with pytest.raises(PublishTransientError, match="no answer"):
        MqttPublisher(transport, DEVICE, 0.1).publish_batch(make_items(fake_cloud, 1))


def test_second_answer_with_the_same_correlation_is_ignored(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    Responder(broker, lambda r: [reply(r, "ok", ok_results(r)), reply(r, "auth")])
    results = MqttPublisher(transport, DEVICE).publish_batch(make_items(fake_cloud, 1))
    assert results[0].status == "created"


def test_late_answer_of_an_earlier_request_is_discarded(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    held: list[MqttMessage] = []

    def answers(r: MqttMessage) -> list[MqttMessage]:
        if not held:
            held.append(reply(r, "auth"))  # answered too late
            return []
        late = held.pop()
        return [late, reply(r, "ok", ok_results(r))]

    Responder(broker, answers)
    publisher = MqttPublisher(transport, DEVICE, 0.1)
    with pytest.raises(PublishTransientError):
        publisher.publish_batch(make_items(fake_cloud, 1))
    assert publisher.publish_batch(make_items(fake_cloud, 1))[0].status == "created"


def test_answer_for_another_session_is_not_received(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    old = MqttPublisher(broker.client("old"), DEVICE)

    def answers(r: MqttMessage) -> list[MqttMessage]:
        wrong_topic = MqttMessage(
            old.reply_topic,
            b"",
            correlation_data=r.correlation_data,
            user_properties=(("result", "auth"),),
        )
        return [wrong_topic]

    Responder(broker, answers)
    with pytest.raises(PublishTransientError, match="no answer"):
        MqttPublisher(transport, DEVICE, 0.1).publish_batch(make_items(fake_cloud, 1))


def test_broker_down_is_transient_and_recovers(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    Responder(broker, lambda r: [reply(r, "ok", ok_results(r))])
    publisher = MqttPublisher(transport, DEVICE)
    broker.stop()
    start = time.monotonic()
    with pytest.raises(PublishTransientError, match="not reachable"):
        publisher.publish_batch(make_items(fake_cloud, 1))
    assert time.monotonic() - start < 1  # no wait for an answer that cannot come
    broker.start()
    assert publisher.publish_batch(make_items(fake_cloud, 1))[0].status == "created"


def test_broker_down_before_the_first_connect(
    broker: InMemoryBroker, transport: InMemoryTransport, fake_cloud: types.ModuleType
) -> None:
    broker.stop()
    publisher = MqttPublisher(transport, DEVICE)
    with pytest.raises(PublishTransientError):
        publisher.publish_batch(make_items(fake_cloud, 1))
    broker.start()
    Responder(broker, lambda r: [reply(r, "ok", ok_results(r))])
    assert publisher.publish_batch(make_items(fake_cloud, 1))[0].status == "created"


def test_nothing_is_logged_with_the_payload(
    broker: InMemoryBroker,
    transport: InMemoryTransport,
    fake_cloud: types.ModuleType,
    caplog: pytest.LogCaptureFixture,
) -> None:
    items = make_items(fake_cloud, 2)
    publisher = MqttPublisher(transport, DEVICE, 0.05)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(PublishTransientError):
            publisher.publish_batch(items)
        assert publisher.check_health() is False
    for item in items:
        assert str(item.inspection_id) not in caplog.text


def test_close_disconnects(broker: InMemoryBroker, transport: InMemoryTransport) -> None:
    publisher = MqttPublisher(transport, DEVICE)
    transport.connect()
    publisher.close()
    assert not transport.connected


# -- check_health ----------------------------------------------------------------------------------


def test_health_ok(broker: InMemoryBroker, transport: InMemoryTransport) -> None:
    responder = Responder(broker, lambda r: [reply(r, "ok")])
    assert MqttPublisher(transport, DEVICE).check_health() is True
    (request,) = responder.requests
    assert request.topic == "partqc/v1/edge-01/health"
    assert request.payload == b""
    assert request.correlation_data is not None


@pytest.mark.parametrize("result", ["transient", "auth", "rejected", None])
def test_health_not_ok(
    broker: InMemoryBroker, transport: InMemoryTransport, result: str | None
) -> None:
    Responder(broker, lambda r: [reply(r, result)])
    assert MqttPublisher(transport, DEVICE).check_health() is False


def test_health_without_bridge_is_false_within_the_timeout(transport: InMemoryTransport) -> None:
    start = time.monotonic()
    assert MqttPublisher(transport, DEVICE, 0.2).check_health() is False
    assert time.monotonic() - start < 2


def test_health_with_broker_down(broker: InMemoryBroker, transport: InMemoryTransport) -> None:
    broker.stop()
    assert MqttPublisher(transport, DEVICE).check_health() is False


class _SlowConnect:
    """A transport whose ``connect`` waits the whole ``timeout_s`` and fails (broker down)."""

    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    def connect(self, timeout_s: float | None = None) -> None:
        self.timeouts.append(timeout_s)
        time.sleep(timeout_s if timeout_s is not None else 5.0)
        raise MqttTransportError("mqtt broker not reachable")

    def subscribe(self, topic_filter: str, handler: Any, qos: int = 1) -> None:
        pass

    def publish(self, message: MqttMessage, qos: int = 1, timeout_s: float | None = None) -> None:
        raise AssertionError("never published")

    def disconnect(self) -> None:
        pass


def test_connection_wait_is_inside_the_response_timeout() -> None:
    transport = _SlowConnect()
    start = time.monotonic()
    assert MqttPublisher(transport, DEVICE, 0.3).check_health() is False
    assert time.monotonic() - start < 1.5
    (timeout,) = transport.timeouts
    assert timeout is not None and 0 < timeout <= 0.3
